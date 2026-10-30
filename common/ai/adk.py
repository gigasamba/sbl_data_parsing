"""ADK 모델 어댑터 — dev/ 전역 LLM·VLM 호출을 한 곳에서(GA2). 두 경로:
  agent=<dev/agents/<id>> 지정 — gamma(ADK) 에이전트 패키지(agent_platform.pipeline)를 통해: 패키지의 LlmAgent(instruction=""·
    mode="single_turn", GA2 설계 docs/architecture.md §1)를 이 역할의 실제 모델로 다시 지어(_lite_llm 캐시 재사용)
    Runner로 한 번 실행(run_once, 세션 SQLite 없음). instruction=""이면 ADK가 identity 시스템 문구를 안 붙여(flows/llm_flows/
    identity.py) 요청 본문이 비-에이전트 경로와 같다 — system/extra_body는 호출마다 agent.model_copy로 덮어써 그대로 전달(I3~I5).
  agent=None — google.adk.models.lite_llm.LiteLlm을 LlmRequest로 직접 불러 응답을 받는다(Runner·세션 없음, 옛 GA2 경로 —
    1회성 호출(selftest·ping 등)에만 남겨 둠, 업무 호출부는 전부 agent=를 넘김 — cli/check_modules.py가 집행).
흐름(되돌이 횟수·판정)은 둘 다 호출자 파이썬 코드가 쥔다(GA4 — LoopAgent 등을 쓰지 않음, 패키지는 도구도 안 받음).

전송: MODEL_TRANSPORT=adk(기본) | http(기존 urllib 경로 — 어댑터를 아직 안 한 곳의 롤백·GA-T3 parity 비교용).
가드(호출 전, 두 전송 공통): common.ai.guard.require_internal + common.ai.guard.precheck — **URL을 그 자리에서 다시 확인**(is_internal) —
ModelProfile.classification은 선언일 뿐 검증에 쓰지 않음(캐시된 분류가 틀렸을 때 가드를 비켜 가면 안 되므로, I7).
외부 주소 거부·NO_PAID_CALLS 차단·비-LLM 외부 호출 고정 예상액 선차감(LLM 토큰 기준 예산은 common/llm.py가 따로 함). 키는 절대 출력·로그 안 함.
리다이렉트(adk 전송): client 생성 시 follow_redirects=False를 줘도 openai SDK가 매 요청마다 강제로 True를 덮어써
무력하다(실측, openai/_base_client.py) — httpx event_hooks로 리다이렉트 **응답 자체**를 가로채 거부(_guarded_client).
재시도: 429·5xx·연결·타임아웃만 최대 retries회, 마지막 실패 뒤엔 대기하지 않음, Retry-After 헤더가 있으면 존중(가능한 범위 —
litellm 경로는 실측상 헤더가 비어 와 지수 백오프로 대체됨, http 경로는 헤더를 그대로 읽음).

LLM_EXTRA_BODY·VLM_EXTRA_BODY(.env, JSON 객체, RV12) — complete() 한 곳에서 role별로 읽어 호출자의 extra=와 합쳐
요청 본문에 보낸다(OpenRouter 생각 끄기·vLLM enable_thinking=false 공용, `_env_extra_body`/`_merged_extra`). 추론
모델이 max_tokens를 생각에 다 써 빈 응답을 내는 문제(common/llm.py 쪽 재시도 안전망과 별개 완화책).

무거운 의존(google.adk·litellm·agent_platform.models)은 전부 함수 안에서 지연 import — 이 모듈을 import만 해도(VLM을 안 쓰는
파싱 하위 프로세스가 공통 코드를 거칠 때) 무거운 패키지를 로드하지 않는다(+70MB·1.8초 안 냄). google.adk·litellm 직접 import는
이 파일 한 곳만(cli/check_modules.py가 집행)."""

import base64
import contextlib
import contextvars
import hashlib
import json
import logging
import os
import re
import sys as _sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path as _Path

from common.ai.guard import fake_llm, precheck, require_internal
from common.ai.guard import urlopen as _g_urlopen
from common.ai.llm import profile
from common.config.settings import by_env, cfg, checked, reveal  # S7b — 설정 객체(호출 때마다 cfg() — 옛 env 읽기와 같은 시점 값)
from common.core.paths import resolve_agent_dir

_ROLE_GUARD_PREFIX = {"llm": "LLM", "vlm": "VLM", "vlm_judge": "VLM", "embed": "EMBED"}


class ModelUnavailable(RuntimeError):
    pass


def _prof_key(prof):
    """모델 프로필 key_env가 가리키는 API 키 글자(없으면 None) — 옛 env 읽기(prof.key_env). 값은 출력·로그 안 함."""
    return reveal(by_env(prof.key_env)) if prof.key_env else None


from common.ai.guard import BudgetExceeded as _BudgetExceeded  # noqa: E402


class GuardBlocked(ModelUnavailable, _BudgetExceeded):
    """가드가 호출을 막음(외부 주소 거부·NO_PAID_CALLS·예산) — 호출은 안 나감. ModelUnavailable이기도 해서 '모델 없음'처럼
    그 단계만 건너뛰는 호출부(그림·쪽 VLM, AD29 P3, 집계 LLM 등)가 파싱을 멈추지 않음(샘플 세션 지적 10-08: NO_PAID_CALLS=1 +
    외부 VLM 주소면 BudgetExceeded가 represent까지 올라가 파싱 중단). BudgetExceeded를 기대하는 기존 호출부도 그대로 잡힘."""


class _Retryable(RuntimeError):
    def __init__(self, inner, retry_after=None):
        super().__init__(str(inner))
        self.inner = inner
        self.retry_after = retry_after


class _RedirectBlocked(RuntimeError):
    """_guarded_client 후킹이 리다이렉트를 거부할 때 던지는 원래 예외. 직접 adk 경로는 litellm이 밖에서 generic한 타입으로
    재매핑해도 __cause__/__context__ 체인에 그대로 남아(실측) _find_redirect_block로 다시 꺼낼 수 있다 — 그러나 agent=
    경로(ADK Workflow/노드 재시작)는 내부적으로 같은 예외 객체를 다른 except 블록에서 다시 raise해 __context__를 덮어써
    체인이 끊긴다(실측, 2026-10 보완) — 그래서 _redirect_block 플래그(아래)가 1차 판정 수단이고, 체인 탐색은 보조 경로로 남긴다."""


def _find_redirect_block(ex, depth=6):
    cur, seen = ex, set()
    for _ in range(depth):
        if isinstance(cur, _RedirectBlocked):
            return cur
        nxt = cur.__cause__ or cur.__context__
        if nxt is None or id(nxt) in seen:
            return None
        seen.add(id(nxt))
        cur = nxt
    return None


# 호출 1건의 리다이렉트 차단 신호 — 예외 __cause__/__context__ 체인 대신 쓰는 1차 판정(위 설명). ContextVar는 각 호출이
# _run_async(_call())로 새로 만드는 asyncio Task마다 독립된 컨텍스트를 받으므로(복사), _call()이 맨 먼저 자신의 상자(dict)를
# set해 두면 깊이 중첩된 자식 Task(ADK Workflow 내부)에서도 **같은 상자 객체**를 읽어 mutate할 수 있다(상자를 가리키는 값 자체가
# 아니라 상자 내부를 바꾸므로 Task 경계에서도 보임) — 동시 호출끼리는 각자 다른 상자라 섞이지 않는다.
_redirect_block = contextvars.ContextVar("adk_redirect_block", default=None)


_model_cache: dict = {}
_cache_lock = threading.Lock()
_bg_loop = None
_bg_lock = threading.Lock()
_hardened = False

# 단계 4(10-13) — 옛 dev/agents/<agent_id>/는 prompts/<id>/·parse/agent/<id>/로 나뉨(resolve_agent_dir, 아래)
_pipeline_cache: dict = {}
_pipeline_lock = threading.Lock()

# ── RV24 — base_url별 공유 "모델 다운" 회로 차단기(complete() 한 곳에서, 호출부마다 손대지 않음). 쪽 VLM 호출이
# 병렬로 돌아도(--procs) 같은 주소를 보는 모든 스레드가 같은 상태를 공유 — 연결 실패·타임아웃이 연속
# MODEL_DOWN_AFTER(기본 3)회 쌓이면 MODEL_DOWN_COOLDOWN(기본 300)초 동안 네트워크를 전혀 안 보내고 즉시 거부한다
# (한 서버가 멈춰도 그 뒤 쪽마다 최대 재시도 시간을 다시 치르지 않음, RV24 증상). 성공 1회로 reset.
_model_down_lock = threading.Lock()
_model_down_state: dict = {}  # base_url -> {"fails": int, "until": time.monotonic() 시각 또는 None}


def _model_down_after():
    return cfg().models.transport.down_after  # S7b — 설정 객체(옛 int(env or 3))


def _model_down_cooldown():
    return cfg().models.transport.down_cooldown  # S7b — 설정 객체(옛 float(env or 300))


def _fast_failure_threshold():
    """독립 검토 BLOCK — connect/read 타임아웃을 예외 타입으로 못 가르니(litellm이 둘 다 litellm.Timeout으로
    매핑) 걸린 시간으로 가른다. MODEL_CONNECT_TIMEOUT(연결 전용 상한)×1.5 — 연결 자체가 안 열려 끊긴 실패는
    이보다 훨씬 빨리 끝나고, 연결되고 응답만 늦는 실패(살아있지만 느림)는 read 상한(몇십 초 이상)까지 걸려
    이 문턱을 넘는다. 같은 env를 agent_platform.models.create_model()·common/guard.py도 각자 읽음(공용
    헬퍼로 묶지 않음 — 세 곳 다 기본값 10이 같고, 서로 다른 모듈이라 import로 묶으면 지연 import 경계가 깨짐)."""
    return cfg().models.transport.connect_timeout * 1.5  # S7b — 설정 객체(옛 float(env or 10))


def _model_down(base_url):
    """True면 쿨다운 중 — complete()가 네트워크 호출 전에 바로 거부해야 함.
    # ponytail: 쿨다운이 끝나면 바로 전부 다시 허용(half-open 확인 호출 1건으로 먼저 찔러보지 않음) —
    # PIPE_WORKERS가 커져 쿨다운 만료 순간에 다수가 동시에 몰리면 추가, 지금은 단일 워커 기준 충분."""
    with _model_down_lock:
        st = _model_down_state.get(base_url)
        return bool(st and st["until"] is not None and time.monotonic() < st["until"])


def _model_down_mark_failure(base_url):
    """complete()가 재시도를 다 쓰고도 연결·타임아웃으로 실패했을 때만(그 밖의 ModelUnavailable — 외부 주소 거부·
    스키마 불일치 등은 '모델이 내려감'의 신호가 아니므로 호출부가 그 자리에서 바로 raise해 여기를 거치지 않는다)."""
    after = _model_down_after()
    if after <= 0:  # OP11 — MODEL_DOWN_AFTER=0으로 기능 끔(기본은 켬)
        return
    with _model_down_lock:
        st = _model_down_state.setdefault(base_url, {"fails": 0, "until": None})
        st["fails"] += 1
        if st["fails"] >= after:
            st["until"] = time.monotonic() + _model_down_cooldown()


def _model_down_reset(base_url):
    with _model_down_lock:
        _model_down_state.pop(base_url, None)


# ── 출력 형식 검사·1회 재요청(AD33 ⓑ) — output_schema가 있는 패키지(agent=)만. 호출부 각자의 파서(_chat_json·
# parse_json 등)는 그대로 두고, 여기서는 "형식이 아예 어긋났나"만 보고 한 번 더 같은 요청을 보낸다 — 그래도 어긋나면
# 지금처럼 호출부 기본값 처리에 맡긴다(여기서 예외를 던지지 않음). 통계는 schema_stats()로.
_SCHEMA_RETRY_NOTE = "앞 응답이 형식에 맞지 않았다 — 스키마에 맞는 JSON 하나만"
_schema_stats = {"invalid": 0, "retry_ok": 0, "retry_failed": 0}
_schema_stats_lock = threading.Lock()


def _bump_schema_stat(key):
    with _schema_stats_lock:
        _schema_stats[key] += 1


def schema_stats():
    """invalid: 1차 응답이 output_schema에 안 맞아 재요청한 수 · retry_ok: 재요청이 맞아 통과한 수 ·
    retry_failed: 재요청도 안 맞아 호출부 기본값 처리로 넘어간 수(AD33 ⓑ)."""
    with _schema_stats_lock:
        return dict(_schema_stats)


def _extract_json_loose(text):
    """형식 검사용 느슨한 JSON 추출(호출부 각자의 파서를 대신하지 않음 — 검사만, common/llm.py parse_json과 같은 규칙:
    코드펜스 벗기고 첫 '{'~마지막 '}' 사이)."""
    t = (text or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(t[i : j + 1])
    except ValueError:
        return None


def _schema_ok(text, schema):
    data = _extract_json_loose(text)
    if not isinstance(data, dict):
        return False
    import jsonschema

    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False


def _append_retry_note(messages, note):
    """스키마 재요청용 — 원 messages는 바꾸지 않고, 마지막 메시지에 안내 한 줄을 덧붙인 **새** 목록(글·이미지 content
    둘 다). 메시지가 달라지므로 common/llm.py 캐시 열쇠도 달라진다(원 요청 캐시는 형식 맞는 응답만 저장, AD33 ⓑ)."""
    new = [dict(m) for m in messages]
    last = dict(new[-1])
    content = last.get("content")
    last["content"] = (content + "\n\n" + note) if isinstance(content, str) else list(content) + [{"type": "text", "text": note}]
    new[-1] = last
    return new


# ── 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시.
# 옛 agent_platform.{config,contracts,build,pipeline,models}에서 이 파일이 실제로 부르던 부분만 옮겼다(서빙·빌드 보관·
# 평가·RuntimeSession·ModelGuardPlugin은 옮기지 않음). 함수 이름 앞에 _를 붙인 것 말고는 동작·문구·지문 계산이 같다 —
# google.adk·litellm·pydantic은 전처럼 함수 안에서 지연 import(S7b부터 설정 객체 — common.config.settings — 때문에 pydantic은 import 때 들어옴).
_PIPE_LOG = logging.getLogger("common.ai.adk")
_PIPELINE_MODEL_ROLES = frozenset({"llm", "vlm", "vlm_judge"})


class PlatformError(Exception):
    """옛 agent_platform.config.PlatformError — 패키지·예산 경계 위반(호출자에게 보여도 되는 문구). RuntimeError가 아니다
    (옛 그대로 — agent_step 세션 경계는 문구 "budget exceeded"로 가른다)."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _package_digest(path):
    """지시서 패키지 지문 — 옛 agent_platform.pipeline._package_digest와 같은 값(상대 경로 → 파일 sha256의 canonical JSON을
    다시 sha256). 패키지 모듈 이름(_load_factory)·로그에 들어간다."""
    files = [p for p in sorted(path.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    table = {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(_canonical(table).encode()).hexdigest()


_manifest_cls = None


def _manifest_model():
    """옛 agent_platform.contracts.AgentManifest(+Budget·EvaluationPolicy) — 같은 칸·기본값·검사. pydantic은 처음 쓸 때만 import."""
    global _manifest_cls
    if _manifest_cls is not None:
        return _manifest_cls
    from typing import Literal

    from pydantic import BaseModel, ConfigDict, Field, model_validator

    class _Strict(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class Budget(_Strict):
        seconds: float = Field(default=300, gt=0, le=300)
        model_calls: int = Field(default=10, gt=0, le=100)
        tool_calls: int = Field(default=20, gt=0, le=200)

    class EvaluationPolicy(_Strict):
        repeats: int = Field(default=1, ge=1, le=10)
        min_passes: int | None = Field(default=None, ge=1)
        advisory: list[str] = Field(default_factory=list)

        @model_validator(mode="after")
        def consistent(self):
            if self.min_passes is None:
                self.min_passes = self.repeats
            if self.min_passes > self.repeats:
                raise ValueError("min_passes must not exceed repeats")
            if len(set(self.advisory)) != len(self.advisory):
                raise ValueError("advisory criteria must be unique")
            if any(x not in {"max_duration_seconds", "max_model_calls", "max_tool_calls", "output_chars"} for x in self.advisory):
                raise ValueError("only limit criteria may be advisory")
            return self

    class AgentManifest(_Strict):
        agent_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
        owner: str = Field(min_length=1)
        description: str = Field(min_length=1)
        kind: str = Field(default="chat", pattern=r"^(chat|pipeline)$")
        model_role: str | None = None
        prompt_ids: list[str] = Field(default_factory=list)
        model_profile: str = "default"
        bindings: list[str] = Field(default_factory=list)
        local_tools: list[str] = Field(default_factory=list)
        classification: str = Field(default="public", pattern=r"^(public|internal)$")
        input_schema: dict = Field(default_factory=lambda: {"type": "string", "minLength": 1})
        output_schema: dict | None = None
        budget: Budget = Field(default_factory=Budget)
        evaluation: EvaluationPolicy = Field(default_factory=EvaluationPolicy)
        agentic: bool = False
        max_turns: int | None = Field(default=None, ge=1, le=50)
        sub_agents: list[str] = Field(default_factory=list)
        common_tail: bool | Literal["free_text"] = True

        @model_validator(mode="after")
        def pipeline_shape(self):
            if self.kind != "pipeline":
                if self.agentic:
                    raise ValueError('agentic requires kind="pipeline"')
                return self
            if self.model_role not in _PIPELINE_MODEL_ROLES:
                raise ValueError(f"pipeline agent model_role must be one of {sorted(_PIPELINE_MODEL_ROLES)}")
            if self.classification != "internal":
                raise ValueError("pipeline agent handles internal documents — classification must be internal")
            if self.bindings:
                raise ValueError("pipeline agent bindings are unsupported (MCP binding is out of scope — AG4)")
            if self.agentic:
                if self.max_turns is None:
                    raise ValueError("agentic pipeline agent requires max_turns (1..50)")
                if "budget" not in self.model_fields_set:
                    raise ValueError("agentic pipeline agent requires an explicit budget block")
            else:
                if self.local_tools:
                    raise ValueError("pipeline agent is single-turn and tool-free (GA4) — local_tools requires agentic: true")
                if self.max_turns is not None:
                    raise ValueError("max_turns is only valid for an agentic pipeline agent")
                if self.sub_agents:
                    raise ValueError("sub_agents is only valid for an agentic pipeline agent")
            return self

    _manifest_cls = AgentManifest
    return _manifest_cls


def _validation_error(source, exc, fields):
    """계약 해석 오류에서 믿을 수 있는 칸 이름·번호와 오류 종류만 보여 준다(옛 contracts.validation_error)."""
    errors = exc.errors(include_input=False, include_context=False, include_url=False)
    details = []
    for error in errors[:5]:
        location = source
        for part in error["loc"]:
            location += f"[{part}]" if isinstance(part, int) else "." + (part if part in fields else "<key>")
        details.append(f"{location}: {error['type']}")
    if len(errors) > 5:
        details.append("additional validation errors omitted")
    return PlatformError("; ".join(details))


@contextlib.contextmanager
def _load_factory(path, identity):
    """패키지 agent.py를 이 로드 전용 모듈 이름으로 읽어 create_agent(model, tools)를 내준다(옛 build.load_factory)."""
    import importlib.util
    import types as _types

    package = "agent_bundle_" + identity + "_" + uuid.uuid4().hex
    try:
        module = _types.ModuleType(package)
        module.__path__ = [str(path)]
        _sys.modules[package] = module
        spec = importlib.util.spec_from_file_location(package + ".agent", path / "agent.py")
        module = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        if not callable(getattr(module, "create_agent", None)):
            raise PlatformError("agent.py must export create_agent(model, tools)")
        yield module.create_agent
    finally:
        for name in list(_sys.modules):
            if name == package or name.startswith(package + "."):
                del _sys.modules[name]


def _validate_graph(root, model, tools, manifest):
    """옛 build.validate_graph — 허용 노드(LlmAgent·SequentialAgent·순차 Workflow)·주입 모델·모드·도구 집합 검사."""
    from google.adk.agents import LlmAgent, SequentialAgent
    from google.adk.apps import App
    from google.adk.tools.agent_tool import AgentTool
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool
    from google.adk.workflow import Workflow

    App(name="validation", root_agent=root)
    seen = set()

    def _bad_tool(tool):
        return isinstance(tool, BaseToolset) or getattr(tool, "is_long_running", False) or getattr(tool, "_require_confirmation", False)

    def visit(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        if not isinstance(node, (LlmAgent, Workflow, SequentialAgent)):
            raise PlatformError("initial supported graph: LlmAgent, SequentialAgent or sequential Workflow")
        if node.retry_config and node.retry_config.max_attempts not in {0, 1}:
            raise PlatformError("automatic node retries are unsupported")
        if isinstance(node, LlmAgent):
            if node.model is not model:
                raise PlatformError("all agents must use the injected model profile")
            if manifest.kind == "pipeline":
                allowed_modes = {None, "single_turn"} | ({"chat"} if manifest.agentic else set())
            else:
                allowed_modes = {None, "chat"}
            if node.mode not in allowed_modes:
                raise PlatformError(
                    "initial agent mode must be default, chat, (pipeline kind) single_turn, or (agentic pipeline kind) chat"
                )
            if node.code_executor or node.planner:
                raise PlatformError("code executors and implicit planner model calls are unsupported")
            if node.generate_content_config and node.generate_content_config.http_options:
                raise PlatformError("model transport options are owned by the profile")
            if manifest.kind == "pipeline" and manifest.agentic:
                func_names, agent_names = set(), set()
                for tool in node.tools:
                    if _bad_tool(tool):
                        raise PlatformError("unregistered/interactive tool is unsupported")
                    name = getattr(tool, "name", getattr(tool, "__name__", ""))
                    if isinstance(tool, AgentTool):
                        agent_names.add(name)
                    elif tool in tools or callable(tool) or isinstance(tool, FunctionTool):
                        func_names.add(name)
                    else:
                        raise PlatformError(f"unsupported agentic tool: {name}")
                if func_names != set(manifest.local_tools):
                    raise PlatformError("agentic pipeline tools must match local_tools exactly")
                if agent_names != set(manifest.sub_agents):
                    raise PlatformError("agentic pipeline tools must match sub_agents exactly")
            else:
                for tool in node.tools:
                    if _bad_tool(tool):
                        raise PlatformError("unregistered/interactive tool is unsupported")
                    if tool in tools:
                        continue
                    name = getattr(tool, "name", getattr(tool, "__name__", ""))
                    if not (callable(tool) or isinstance(tool, FunctionTool)) or name not in manifest.local_tools:
                        raise PlatformError(f"undeclared local tool: {name}")
        for child in getattr(node, "sub_agents", []):
            visit(child)
        if isinstance(node, Workflow):
            if len(node.edges) != 1 or node.edges[0][0] != "START":
                raise PlatformError("initial Workflow support requires one sequential START path")
            for child in node.edges[0][1:]:
                if not isinstance(child, str):
                    visit(child)

    visit(root)


class _PipelineAgent:
    """한 번 검사한 패키지(매니페스트+그래프) — build()가 호출마다 실제 모델로 LlmAgent를 다시 짓는다(옛 PipelineAgent)."""

    def __init__(self, path, manifest, identity):
        self.path, self.manifest, self.identity = path, manifest, identity

    def build(self, model, tools=()):
        with _load_factory(self.path, self.identity) as factory:
            return factory(model, list(tools))


def _dummy_model():
    """그래프 구조 검사 전용 — 요청을 보내지 않는다."""
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model="openai/validate-only", api_base="http://127.0.0.1:1", api_key="validate-only")


def _dummy_function_tool(name):
    from google.adk.tools.function_tool import FunctionTool

    def _stub(**_kwargs):
        return {}

    _stub.__name__ = name
    _stub.__doc__ = "AG4 validate-only stand-in for local tool " + name
    return FunctionTool(_stub)


def _validation_tools(manifest, path):
    """agentic 패키지 로드 시 검사용 가짜 도구(local_tools 이름) + 형제 패키지 sub_agents(각자 검사, agentic이면 거부)."""
    from google.adk.tools.agent_tool import AgentTool

    tools = [_dummy_function_tool(name) for name in manifest.local_tools]
    for sub_id in manifest.sub_agents:
        sub_pkg = _load_pipeline_agent(path.parent / sub_id)
        if sub_pkg.manifest.agentic:
            raise PlatformError(f"sub_agent {sub_id!r} must not be agentic (AG4: sub_agents are single-turn only)")
        tools.append(AgentTool(sub_pkg.build(_dummy_model())))
    return tools


def _load_pipeline_agent(package_dir):
    """옛 agent_platform.pipeline.load_pipeline_agent — agent.json 검사(kind=pipeline·폴더 이름=agent_id) + 그래프 검사."""
    from pydantic import ValidationError

    path = _Path(package_dir).resolve()
    manifest_cls = _manifest_model()
    try:
        manifest = manifest_cls.model_validate_json((path / "agent.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlatformError(f"missing agent.json: {path}") from None
    except ValidationError as exc:
        raise _validation_error("agent.json", exc, manifest_cls.model_fields.keys()) from None
    if manifest.kind != "pipeline":
        raise PlatformError(f'{path.name}: load_pipeline_agent requires agent.json kind="pipeline"')
    if path.name != manifest.agent_id:
        raise PlatformError(f"{path.name}: package directory name must equal agent.json agent_id ({manifest.agent_id!r})")
    identity = _package_digest(path)
    model = _dummy_model()
    validation_tools = _validation_tools(manifest, path) if manifest.agentic else []
    with _load_factory(path, identity) as factory:
        root = factory(model, validation_tools)
        _validate_graph(root, model, validation_tools, manifest)
    _PIPE_LOG.info("pipeline agent loaded agent=%s identity=%s", manifest.agent_id, identity)
    return _PipelineAgent(path, manifest, identity)


def _create_model(prof, timeout=120, guard_prefix="LLM", **extra):
    """옛 agent_platform.models.create_model — ADK LiteLlm(OpenAI 호환), 자동 재시도 0. 주소·모델·키는 ModelProfile(env)에서만.
    connect 상한만 MODEL_CONNECT_TIMEOUT(기본 10초, <=0이면 timeout 하나로)으로 따로(RV24). client=를 안 주면 옛 코드처럼
    _guarded_client(prof, guard_prefix)로 채운다(리다이렉트 가드 기본값, V5 R-7) — 이 파일의 호출자(_lite_llm)는 직접 넘긴다."""
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # env 남김 — 라이브러리(5-3 H)
    import httpx
    from google.adk.models.lite_llm import LiteLlm

    connect = cfg().models.transport.connect_timeout  # S7b — 설정 객체
    t = httpx.Timeout(timeout, connect=min(connect, timeout) if timeout else connect) if connect > 0 else timeout
    if "client" not in extra:
        extra["client"] = _guarded_client(prof, guard_prefix)
    key = _prof_key(prof)
    if prof.key_env and not key:
        raise PlatformError(f"missing required secret reference: {prof.key_env}")
    return LiteLlm(
        model=prof.model, api_base=prof.base_url, api_key=key if prof.key_env else "local-no-key", num_retries=0, timeout=t, **extra
    )


async def _run_once(agent, content, *, system=None, config=None, timeout=120, max_llm_calls=1):
    """옛 agent_platform.pipeline.run_once — 단일 턴 1회 → (text, usage). system/config는 이 호출에만 model_copy로 덮어쓴다
    (패키지는 instruction=""만 선언 — 요청 본문이 비-에이전트 경로와 같음). 노드 1개짜리 Workflow로 감싸 Runner로 돌린다."""
    import asyncio

    from google.adk import Runner
    from google.adk.agents.run_config import RunConfig
    from google.adk.apps import App
    from google.adk.sessions import InMemorySessionService
    from google.adk.workflow import Workflow

    updates = {}
    if system:
        updates["instruction"] = system
    if config is not None:
        updates["generate_content_config"] = config
    if updates:
        agent = agent.model_copy(update=updates)
    root = Workflow(name=agent.name + "_run", edges=[("START", agent)])
    service = InMemorySessionService()
    user_id, session_id = "pipeline", uuid.uuid4().hex
    await service.create_session(app_name=root.name, user_id=user_id, session_id=session_id)
    runner = Runner(app=App(name=root.name, root_agent=root), session_service=service)
    text, usage = "", {"prompt_tokens": 0, "completion_tokens": 0}
    async with runner:
        async with asyncio.timeout(timeout):
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=content, run_config=RunConfig(max_llm_calls=max_llm_calls)
            ):
                if event.usage_metadata:
                    u = event.usage_metadata
                    usage = {
                        "prompt_tokens": getattr(u, "prompt_token_count", None) or 0,
                        "completion_tokens": getattr(u, "candidates_token_count", None) or 0,
                    }
                if event.is_final_response() and event.content:
                    text = "".join(p.text or "" for p in event.content.parts or [] if p.text and not getattr(p, "thought", False))
    return text, usage


_SENSITIVE_ARG_KEY = re.compile(r"key|token|secret|password|authorization", re.I)
_TOKEN_OR_BLOB = re.compile(r"data:[^,]{0,100},[A-Za-z0-9+/=]{20,}|Bearer\s+[A-Za-z0-9._-]{10,}|[A-Za-z0-9+/]{80,}={0,2}")


def _redact_arg_value(key, value):
    """궤적 기록용 도구 인자 값 — 민감 키는 통째로, 토큰·base64·data URI는 종류+길이로, 60자 넘는 글자는 길이로만 가린다."""
    if _SENSITIVE_ARG_KEY.search(str(key)):
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _redact_arg_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_arg_value("", v) for v in value]
    if isinstance(value, str):
        if _TOKEN_OR_BLOB.search(value):
            return f"<string {len(value)}자, token/base64 — 가림>"
        if len(value) > 60:
            return f"<text {len(value)}자>"
    return value


def _summarize_args(args):
    redacted = {k: _redact_arg_value(k, v) for k, v in args.items()} if isinstance(args, dict) else args
    return _canonical(redacted)[:200]


async def _run_agentic(
    agent,
    content,
    *,
    tools,
    sub_agents,
    max_turns,
    budget,
    timeout=120,
    live=None,
    token_budget=None,
    soft_deadline=None,
    admit=None,
    settle=None,
):
    """옛 agent_platform.pipeline.run_agentic(AG4·ADK2·AG11·GH1-08b·GA9) — 다중 턴·도구 사용 패키지를 끝까지 1회 실행.
    콜백 한 자리에서: 모델 호출 수 상한(min(max_turns, budget.model_calls))·토큰 상한·admit(턴별 공유 장부)·soft_deadline에
    걸리면 "예산 초과"/"공유 호출 상한"/"시간 상한" 글자로 정상 멈춤, 허용 밖 도구·도구 예산·토큰 예산 초과는 PlatformError.
    AgentTool로 감싼 sub_agent에도 같은 모델 콜백을 붙여 호출 수·토큰을 같이 센다. 턴 단위 재시도 없음.
    → (text, trajectory, usage) — usage는 prompt/completion 토큰 합계 + model_calls·tool_calls."""
    import asyncio

    from google.adk import Runner
    from google.adk.agents.run_config import RunConfig
    from google.adk.apps import App
    from google.adk.models.llm_response import LlmResponse
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools.agent_tool import AgentTool
    from google.genai import types

    allowed = set(tools) | set(sub_agents)
    model_cap = max(0, min(max_turns, budget.model_calls))
    state = {"model_calls": 0, "tool_calls": 0, "trajectory": [], "started": {}}
    if live is not None:  # 호출자가 실패·중단 때도 지금까지 쓴 호출 수를 읽게(같은 dict를 공유 — 보안 재검토 F3)
        live["state"] = state
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    clock = {"t0": time.monotonic(), "last": None, "max_turn": 0.0}

    def _tokens_spent():
        return usage["prompt_tokens"] + usage["completion_tokens"]

    def _stop(text):
        return LlmResponse(content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))

    async def before_model_callback(callback_context, llm_request):
        if state["model_calls"] >= model_cap or (token_budget and _tokens_spent() >= token_budget):
            return _stop("예산 초과")
        if admit is not None and not admit(callback_context):
            return _stop("공유 호출 상한")
        now = time.monotonic()
        if clock["last"] is not None:
            clock["max_turn"] = max(clock["max_turn"], now - clock["last"])
        if soft_deadline is not None and (now - clock["t0"]) + clock["max_turn"] > soft_deadline:
            return _stop("시간 상한")
        clock["last"] = now
        state["model_calls"] += 1
        return None

    async def after_model_callback(callback_context, llm_response):
        u = llm_response.usage_metadata
        turn_usage = (
            {
                "prompt_tokens": getattr(u, "prompt_token_count", None) or 0,
                "completion_tokens": getattr(u, "candidates_token_count", None) or 0,
            }
            if u
            else {}
        )
        if u:
            usage["prompt_tokens"] += turn_usage["prompt_tokens"]
            usage["completion_tokens"] += turn_usage["completion_tokens"]
        if settle is not None:
            settle(callback_context, turn_usage)
        return None

    async def before_tool_callback(tool, args, tool_context):
        if tool.name not in allowed:
            raise PlatformError(f"agentic pipeline: disallowed tool call — {tool.name}")
        if state["tool_calls"] >= budget.tool_calls:
            raise PlatformError("agentic pipeline: tool call budget exceeded")
        if token_budget and _tokens_spent() >= token_budget:
            raise PlatformError("agentic pipeline: token budget exceeded")
        state["tool_calls"] += 1
        state["started"][tool_context.function_call_id] = time.monotonic()
        state["trajectory"].append({"seq": len(state["trajectory"]), "tool": tool.name, "args_summary": _summarize_args(args)})
        return None

    async def after_tool_callback(tool, args, tool_context, result):
        entry = state["trajectory"][-1]
        started = state["started"].pop(tool_context.function_call_id, None)
        entry["duration_seconds"] = round(time.monotonic() - started, 3) if started is not None else None
        entry["result_bytes"] = len(_canonical(result).encode())
        return None

    def _with_budget(tool):
        if not isinstance(tool, AgentTool):
            return tool
        sub = tool.agent.model_copy(update={"before_model_callback": before_model_callback, "after_model_callback": after_model_callback})
        return AgentTool(
            sub,
            skip_summarization=tool.skip_summarization,
            include_plugins=tool.include_plugins,
            propagate_grounding_metadata=tool.propagate_grounding_metadata,
        )

    agent = agent.model_copy(
        update={
            "tools": [_with_budget(tool) for tool in agent.tools],
            "before_model_callback": before_model_callback,
            "after_model_callback": after_model_callback,
            "before_tool_callback": before_tool_callback,
            "after_tool_callback": after_tool_callback,
        }
    )
    service = InMemorySessionService()
    user_id, session_id = "pipeline", uuid.uuid4().hex
    await service.create_session(app_name=agent.name, user_id=user_id, session_id=session_id)
    runner = Runner(app=App(name=agent.name, root_agent=agent), session_service=service)
    text = ""
    async with runner:
        async with asyncio.timeout(timeout):
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=content, run_config=RunConfig(max_llm_calls=model_cap)
            ):
                if event.is_final_response() and event.content:
                    text = "".join(p.text or "" for p in event.content.parts or [] if p.text and not getattr(p, "thought", False))
    usage["model_calls"] = state["model_calls"]
    usage["tool_calls"] = state["tool_calls"]
    return text, state["trajectory"], usage


def _load_pipeline(agent_id):
    """dev/agents/<agent_id>/ 패키지 — 그래프 검사는 1회(프로세스 캐시), 실제 모델은 매 호출 build()로 다시 지음(가벼움)."""
    with _pipeline_lock:
        pkg = _pipeline_cache.get(agent_id)
        if pkg is None:
            # TODO: 리팩토링 후 구현 필요
            # from agent_platform.pipeline import load_pipeline_agent
            # pkg = _pipeline_cache[agent_id] = load_pipeline_agent(resolve_agent_dir(agent_id))
            # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
            pkg = _pipeline_cache[agent_id] = _load_pipeline_agent(resolve_agent_dir(agent_id))
        return pkg


def _loop():
    """모든 스레드가 공유하는 백그라운드 asyncio 루프(데몬 스레드 1개) — 스레드마다 새 루프를 쓰면 litellm의 내부 비동기
    로깅 워커가 루프를 옮겨 다니며 끝나지 않는 task를 남긴다(실측) — 루프 하나로 고정해 피한다."""
    global _bg_loop
    if _bg_loop is None:
        with _bg_lock:
            if _bg_loop is None:
                import asyncio

                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True, name="adk-loop").start()
                _bg_loop = loop
    return _bg_loop


def _run_async(coro):
    import asyncio

    return asyncio.run_coroutine_threadsafe(coro, _loop()).result()


_client_cache: dict = {}
_client_cache_lock = threading.Lock()


def _redirect_ok(loc, prefix):
    """리다이렉트 대상(loc)을 따라가도 되나 — common.guard와 같은 규칙(내부 주소 또는 <prefix>_ALLOW_EXTERNAL=1
    + RUN_ENV=local). 순수 함수로 빼서 네트워크 없이 단위 시험 가능(_guarded_client 후킹의 판단 로직 그대로)."""
    from common.ai.guard import external_allowed, is_internal

    return is_internal(loc) or external_allowed(prefix)


def _guarded_client(prof, prefix):
    """litellm에 client=로 넘길 openai.AsyncOpenAI — 내부 httpx 클라이언트에 event_hooks로 리다이렉트 응답 자체를
    가로채 거부한다(실측: openai SDK가 매 요청마다 kwargs.setdefault("follow_redirects", True)를 넣어 client 생성 시점의
    follow_redirects=False를 덮어써 무력하다 — openai/_base_client.py 확인. response 후킹은 follow_redirects 값과
    무관하게 모든 응답(중간 리다이렉트 포함)에서 불린다 — _redirect_ok 단위 시험 + 실호출 둘 다로 증명). 후킹은 _RedirectBlocked를
    던진다 — litellm이 밖에서 generic한 타입(InternalServerError 등)으로 재매핑해도 __cause__/__context__ 체인에는 원본이
    그대로 남아(실측) _complete_adk가 _find_redirect_block로 다시 꺼내 원래 문구("…외부(host)로 리다이렉트…")로 올린다.
    litellm._get_openai_client는 client=를 그대로 쓰되 api_key만 동적으로 다시 씀(_set_dynamic_params_on_client) —
    그래서 raw httpx client가 아니라 AsyncOpenAI여야 함. (base_url·key_env·prefix)별로 하나 캐시 — 그래서 이 후킹은 호출마다
    새로 만들지 않고, 차단 신호는 예외 체인이 아니라 _redirect_block 상자(호출 1건 스코프, 위 설명)에 적는다."""
    key = (prof.base_url, prof.key_env, prefix)
    with _client_cache_lock:  # _lite_llm이 이미 _cache_lock을 쥔 채 이 함수를 부름(재진입 안 되는 Lock) — 별도 잠금 필요
        c = _client_cache.get(key)
        if c is None:
            import httpx
            from openai import AsyncOpenAI

            async def _check_redirect(response):
                if response.is_redirect and not _redirect_ok(response.headers.get("location") or "", prefix):
                    import urllib.parse

                    loc = response.headers.get("location") or ""
                    host = urllib.parse.urlparse(loc).hostname or loc
                    box = _redirect_block.get()
                    if box is not None:
                        box["host"] = host  # 1차 신호(호출자의 상자를 직접 mutate — Task 경계를 넘어도 보임)
                    raise _RedirectBlocked(f"내부 엔드포인트가 외부({host})로 리다이렉트 — 거부(DONT 13)")

            httpx_client = httpx.AsyncClient(follow_redirects=False, event_hooks={"response": [_check_redirect]})
            api_key = _prof_key(prof) or "local-no-key"
            c = _client_cache[key] = AsyncOpenAI(api_key=api_key, base_url=prof.base_url, http_client=httpx_client)
        return c


def _harden_litellm():
    """1회성 전역 설정 — 가격표 외부 조회 금지(폐쇄망)·죽은 텔레메트리 플래그 끔. 리다이렉트 차단은 역할마다
    _guarded_client(prefix)를 LiteLlm(client=...)로 넘겨서 하지(여기서 전역으로 하면 무력화됨, 위 설명)."""
    global _hardened
    if _hardened:
        return
    import os

    os.environ.setdefault(
        "LITELLM_LOCAL_MODEL_COST_MAP", "True"
    )  # env 남김 — 라이브러리(5-3 H) — litellm import 직전, 폐쇄망, 가격표를 외부로 받으러 가지 않게
    import litellm

    litellm.telemetry = False  # 1.101.0 실측: 어디서도 안 읽힘(죽은 플래그) — 그래도 공짜라 꺼 둠
    _hardened = True


def _lite_llm(prof, timeout, guard_prefix):
    _harden_litellm()
    key = (prof.model, prof.base_url, prof.key_env, timeout, guard_prefix)
    with _cache_lock:
        m = _model_cache.get(key)
        if m is None:
            # TODO: 리팩토링 후 구현 필요
            # from agent_platform.models import create_model
            # m = _model_cache[key] = create_model(prof, timeout=timeout, client=_guarded_client(prof, guard_prefix))
            # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
            m = _model_cache[key] = _create_model(prof, timeout=timeout, client=_guarded_client(prof, guard_prefix))
        return m


def _to_contents(messages):
    """OpenAI 형식 messages(문자열 또는 [{"type":"text"/"image_url"}] content) → (system_instruction 글자, [types.Content]).
    role이 원래 system인 메시지만 system_instruction으로 옮긴다 — user 메시지 1개짜리 호출은 그대로 user로 둔다(I4).
    image_url은 data: base64만(원격 URL은 가드를 못 거치므로 지원 안 함)."""
    from google.genai import types

    system_parts, contents = [], []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            system_parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
            continue
        parts = []
        if isinstance(content, str):
            parts.append(types.Part.from_text(text=content))
        else:
            for c in content or []:
                if c.get("type") == "text":
                    parts.append(types.Part.from_text(text=c.get("text") or ""))
                elif c.get("type") == "image_url":
                    url = (c.get("image_url") or {}).get("url") or ""
                    if not url.startswith("data:"):
                        raise ModelUnavailable("image_url은 data: base64만 지원(원격 URL은 가드를 못 거침)")
                    header, _, b64 = url.partition(",")
                    mime = header.split(";")[0].removeprefix("data:") or "image/png"
                    parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime))
        contents.append(types.Content(role="model" if role == "assistant" else "user", parts=parts))
    return ("\n".join(system_parts) if system_parts else None), contents


_EXTRA_ENV_KEY = {"llm": "LLM_EXTRA_BODY", "vlm": "VLM_EXTRA_BODY", "vlm_judge": "VLM_EXTRA_BODY"}


def _env_extra_body(role):
    """LLM_EXTRA_BODY·VLM_EXTRA_BODY(.env, JSON 객체, RV12) — OpenRouter 생각 끄기(`{"reasoning":{"enabled":false}}`·
    `{"reasoning":{"effort":"low"}}`)와 vLLM(`{"chat_template_kwargs":{"enable_thinking":false}}`) 둘 다 이 한
    메커니즘으로 보낸다. 여기 한 곳(complete())에서 role별로 읽어 호출자의 extra=와 합치므로 common/llm.py chat()
    (agent= 경유라 extra= 없이 호출)과 VLM 직접 호출부(figures.py·vlm_page.py·agent_step.py·reread_stage3.py 등) 둘 다
    같은 env로 적용된다 — 호출부마다 손대지 않음. 형식이 틀리면 바로 실패(기존 env JSON 관례 — RDB_CONNECT_KWARGS·
    RDB_CONNECT_KWARGS와 같게 조용히 무시하지 않음)."""
    import copy

    key = _EXTRA_ENV_KEY.get(role)
    if not key:
        return None
    # S7b — 설정 객체(models.llm·vlm.extra_body, 이미 푼 dict/list). 형식이 틀린 값은 아래 checked()가 옛 json.loads처럼 실패시킴.
    # 빈 글자·없음 = None(옛 `if not raw`). 목록은 옛처럼 set(body) 검사만 거침.
    checked(key)  # 형식 틀린 JSON은 옛 json.loads처럼 실패(S7b — 조용히 빼고 보내지 않게)
    body = cfg().models.llm.extra_body if key == "LLM_EXTRA_BODY" else cfg().models.vlm.extra_body
    if body is None:
        return None
    body = copy.deepcopy(body)
    bad = sorted(set(body) & _EXTRA_RESERVED)
    if bad:  # 모델·메시지·한도·스트림은 코드가 정함 — env로 바꾸면 비용·결과가 조용히 달라짐(be-qa RV12 지적)
        raise ValueError(f"{key}에 넣을 수 없는 키: {bad}")
    return body


_EXTRA_RESERVED = {"model", "messages", "max_tokens", "max_completion_tokens", "stream"}


def _merged_extra(role, extra):
    """호출자가 준 extra가 env 기본값의 같은 키를 덮어씀(figure_review.py의 기존 수동 reasoning-off 분기가 여전히
    이김) — env는 "그 밖의 호출부도 끄고 싶을 때"의 전역 기본값."""
    env_extra = _env_extra_body(role)
    return {**env_extra, **(extra or {})} if env_extra else extra


def _extra_body(json_mode, extra, max_tokens=None):
    """response_format·max_tokens·호출자 extra(생각 끄기 등)를 한 dict로 — 전부 http_options.extra_body로 보내
    litellm이 요청 본문에 그대로 얹게 한다. max_tokens를 여기로 보내는 이유(BLOCKER 2, engine-qa 2026-10-06 지적):
    GenerateContentConfig.max_output_tokens를 쓰면 ADK가 max_completion_tokens로만 보내(lite_llm.py _get_completion_inputs
    의 param_mapping) 구버전 vLLM이 무시한다 — http 전송과 똑같이 "max_tokens" 키로만 보내 전송 간 차이를 없앤다."""
    body = dict(extra or {})
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body or None


def _retry_after(ex):
    resp = getattr(ex, "response", None)
    try:
        v = resp.headers.get("retry-after") if resp is not None else None
        return float(v) if v else None
    except (ValueError, AttributeError):
        return None


def _raise_classified(ex, blocked_box=None):
    """ADK/litellm 예외 → ModelUnavailable(즉시 실패, 재시도 대상 아님) 또는 _Retryable(429·5xx·연결·타임아웃) —
    _complete_adk·_complete_agent 공용(둘 다 결국 같은 LiteLlm.generate_content_async를 거치므로 같은 분류가 맞음).
    리다이렉트 차단 판정은 blocked_box(호출 1건 스코프 상자, _redirect_block)를 **먼저** 본다 — agent= 경로는 ADK Workflow가
    예외 __context__를 덮어써 체인 탐색(_find_redirect_block)이 못 찾고 일반 연결 오류로 잘못 분류(재시도 대상)할 수 있어서
    (실측, 2026-10 보완) — 상자가 비어 있을 때만 체인 탐색으로 넘어간다(옛 경로·단위 시험 하위 호환)."""
    import litellm

    if blocked_box is not None and blocked_box.get("host"):
        raise ModelUnavailable(f"내부 엔드포인트가 외부({blocked_box['host']})로 리다이렉트 — 거부(DONT 13)") from ex
    blocked = _find_redirect_block(ex)  # 리다이렉트 거부는 litellm이 재매핑해도 체인에 원본이 남음(위 설명) — 재시도 대상 아님
    if blocked is not None:
        raise ModelUnavailable(str(blocked)) from blocked
    if isinstance(
        ex,
        (litellm.RateLimitError, litellm.APIConnectionError, litellm.Timeout, litellm.InternalServerError, litellm.ServiceUnavailableError),
    ):
        raise _Retryable(ex, retry_after=_retry_after(ex)) from ex
    if isinstance(ex, TimeoutError):  # 10-14 실측: run_once(timeout=) 초과가 asyncio/concurrent TimeoutError로 올라와 분류 없이
        raise _Retryable(
            ex
        ) from ex  # 그대로 던져져 gold_draft 실행 전체가 멈춤 — 위 litellm.Timeout과 같이 재시도 → 끝나면 ModelUnavailable
    if isinstance(ex, litellm.APIError):
        if getattr(ex, "status_code", None) in (429, 500, 502, 503, 504):
            raise _Retryable(ex, retry_after=_retry_after(ex)) from ex
        raise ModelUnavailable(f"모델 호출 실패: {type(ex).__name__}: {str(ex)[:200]}") from ex
    raise


def _complete_adk(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix):
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    system, contents = _to_contents(messages)
    extra_body = _extra_body(json_mode, extra, max_tokens)  # max_tokens은 extra_body로만(BLOCKER 2) — config.max_output_tokens은
    cfg = types.GenerateContentConfig(  # max_completion_tokens로 나가 구버전 vLLM이 무시하므로 안 씀
        system_instruction=system, temperature=temperature, http_options=types.HttpOptions(extra_body=extra_body) if extra_body else None
    )
    req = LlmRequest(contents=contents, config=cfg)
    model = _lite_llm(prof, timeout, guard_prefix)
    blocked_box = {"host": None}

    async def _call():
        _redirect_block.set(blocked_box)
        last = None
        async for resp in model.generate_content_async(req):
            last = resp
        return last

    try:
        resp = _run_async(_call())
    except Exception as ex:
        _raise_classified(ex, blocked_box)
    if resp is None or resp.content is None or not resp.content.parts:
        return "", {"prompt_tokens": 0, "completion_tokens": 0}
    # BLOCKER 1(engine-qa 2026-10-06): vLLM reasoning_content는 ADK가 thought=True인 Part로 parts에 끼워 넣음 —
    # llm 역할은 생각 끄기를 안 보내고 vlm_page도 의도적으로 안 꺼서(출력 상한 넉넉히) 추론 글자가 그대로 올 수 있다.
    # 기존 http 경로(choices[0].message.content)는 추론을 안 담으므로 여기서도 thought Part는 빼고 이어붙인다.
    text = "".join(p.text or "" for p in resp.content.parts if not getattr(p, "thought", False))
    u = resp.usage_metadata
    usage = (
        {"prompt_tokens": getattr(u, "prompt_token_count", None) or 0, "completion_tokens": getattr(u, "candidates_token_count", None) or 0}
        if u
        else {"prompt_tokens": 0, "completion_tokens": 0}
    )
    return text, usage


def _complete_agent(agent_id, role, prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix):
    """gamma 에이전트 패키지(dev/agents/<agent_id>/) 경유 — _complete_adk와 같은 요청 모양(system/extra_body)을 매 호출
    agent.model_copy로 덮어써 보낸다(패키지 자신은 instruction=""만 아는 정적 선언, GA2 설계 §1). 실행은 agent_platform.pipeline
    .run_once(ADK Runner + InMemorySessionService, 세션 SQLite 없음 — §0).
    output_schema가 있으면(AD33 ⓑ) 응답이 안 맞을 때 **같은 요청 + 안내 한 줄**로 1회만 재요청 — 그래도 안 맞으면
    (재요청 결과를) 그대로 돌려줘 호출부가 지금처럼 기본값으로 처리하게 둔다(여기서 예외를 던지지 않음).
    GH1-08a/08c — 재요청도 모델을 한 번 더 부르는 '실제 호출'이라 LLM_MAX_CALLS 공유 장부(chat()·run_agent() 둘 다
    거치는 바로 그 장부)를 다시 거친다. 1차 호출의 자리는 이미 adk.complete()가 예약했으므로(call_reserved, GH1-08d)
    여기서는 **이 재요청 1건만** common/llm.try_reserve_call()로 확인+예약을 원자적으로 한다(GH1-08c — 예전엔
    remaining_calls()로 읽고 나중에 reserve_call()하는 두 단계라 그 사이 동시 스레드(run_all --procs)가 끼어들어
    상한을 넘길 수 있었다, 실측). 거부면(상한 도달) 재요청을 보내지 않고 1차 결과를 그대로 돌린다(기존 '안 맞아도
    예외 안 던짐'과 같은 모양). 무제한(cap=0)이면 지금까지와 동일하게 항상 재요청."""
    from google.genai import types

    pkg = _load_pipeline(agent_id)
    if pkg.manifest.model_role != role:
        raise ModelUnavailable(f"{agent_id}: model_role={pkg.manifest.model_role!r} != 호출 role={role!r}")

    def _once(msgs):
        system, contents = _to_contents(msgs)
        if len(contents) != 1:
            raise ModelUnavailable(f"{agent_id}: pipeline agent는 사용자 턴 1개만 지원(messages={len(contents)}개 턴)")
        extra_body = _extra_body(json_mode, extra, max_tokens)
        cfg = types.GenerateContentConfig(
            temperature=temperature, http_options=types.HttpOptions(extra_body=extra_body) if extra_body else None
        )
        model = _lite_llm(prof, timeout, guard_prefix)
        concrete = pkg.build(model)
        blocked_box = {"host": None}

        async def _call():
            _redirect_block.set(blocked_box)
            # TODO: 리팩토링 후 구현 필요
            # from agent_platform.pipeline import run_once
            # return await run_once(concrete, contents[0], system=system, config=cfg, timeout=timeout)
            # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
            return await _run_once(concrete, contents[0], system=system, config=cfg, timeout=timeout)

        try:
            return _run_async(_call())
        except Exception as ex:
            _raise_classified(ex, blocked_box)

    text, usage = _once(messages)
    schema = pkg.manifest.output_schema
    if schema is not None and not _schema_ok(text, schema):
        _bump_schema_stat("invalid")
        first = usage or {}
        from common.ai import llm as _L  # GH1-08a/08c — chat()·run_agent()과 같은 공유 호출 상한 장부

        if not _L.try_reserve_call():  # 확인+예약 원자적(GH1-08c) — 성공하면 이 재요청 1건이 장부에 이미 들어감
            _bump_schema_stat("retry_failed")  # 상한 도달 — 2차 호출을 내보내지 않음(둘 다 깨진 것과 같은 결과로 취급)
            usage = dict(first)
            usage["schema_failed"] = True
            return text, usage
        try:
            text, usage = _once(_append_retry_note(messages, _SCHEMA_RETRY_NOTE))
        except _Retryable:
            # GH1-08e — 이 재요청이 429/5xx/연결로 못 끝나면 complete()의 전송 재시도 루프가 _complete_agent를
            # 처음부터 다시 돌려 여기를 또 거친다(try_reserve_call()을 또 부름) — 같은 논리적 1회 재요청이
            # 슬롯 2개를 먹지 않게, 못 쓴 이 슬롯을 먼저 돌려주고 그대로 전파(바깥 루프가 재시도 판단).
            _L.release_call()
            raise
        ok = _schema_ok(text, schema)
        _bump_schema_stat("retry_ok" if ok else "retry_failed")
        usage = dict(usage or {})  # 독립 검토(10-06) — 두 호출의 토큰을 합산(예산·집계가 실제 호출 수 반영)
        for k in ("prompt_tokens", "completion_tokens"):
            usage[k] = (first.get(k) or 0) + (usage.get(k) or 0)
        usage["calls"] = 2
        if not ok:
            usage["schema_failed"] = True  # 호출부 캐시에 고착시키지 않게(llm.chat이 캐시 안 씀)
    return text, usage


def _policy_model(policy):
    """LLM_FAKE=1 + fake_policy(AG11 2단계) — 네트워크 없이 **결정적 정책 함수**가 다음 행동을 고르는 가짜 BaseLlm.
    policy(results) — results = 지금까지 도구 응답 [(도구 이름, 응답 dict), ...](요청 contents에서 순서대로) →
    ("call", 도구 이름, 인자 dict) 또는 ("text", 최종 글자). 토큰은 요청 글자 수/4로 흉내(usage_metadata) — 그래야
    run_agentic의 토큰 예산 콜백(ADK2)도 가짜 실행에서 실제로 걸린다."""
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    class _PolicyModel(BaseLlm):
        model: str = "fake-policy"

        async def generate_content_async(self, llm_request, stream=False):
            results, chars = [], 0
            for c in llm_request.contents or []:
                for part in c.parts or []:
                    chars += len(part.text or "")
                    fr = part.function_response
                    if fr is not None:
                        results.append((fr.name, dict(fr.response or {})))
                        chars += len(json.dumps(fr.response or {}, ensure_ascii=False))
            act = policy(results)
            if act[0] == "call":
                part = types.Part(function_call=types.FunctionCall(name=act[1], args=act[2]))
                out_chars = len(json.dumps(act[2], ensure_ascii=False)) + len(act[1])
            else:
                part, out_chars = types.Part(text=act[1]), len(act[1])
            yield LlmResponse(
                content=types.Content(role="model", parts=[part]),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=chars // 4 + 1, candidates_token_count=out_chars // 4 + 1
                ),
            )

    return _PolicyModel()


def _to_thread_tool(fn):
    """GH1-07 — local_tools 함수가 안에서 모델을 다시 부르면(실제 유발: dev/tools/parse_agent_tools.py의
    extract_images·vlm_read·summarize_document가 common/adk.complete를 동기로 부름, parse_agent 패키지의
    agentic:true local_tools로 실제 등록돼 있음) 교착이 난다 — run_agent()의 run_agentic() 코루틴이 공유
    백그라운드 루프(_loop())의 스레드에서 실행되는데, ADK FunctionTool은 기본적으로 동기 함수를 그 **같은**
    스레드에서 직접 호출한다(_SYNC_CALLABLE_RUNNER 미설정 — google/adk/tools/function_tool.py 확인). 그 안에서
    fn이 common/adk.complete()를 부르면 또 _run_async(_call())가 같은 루프에 작업을 넣고 .result()로 기다리는데,
    루프 자신이 지금 fn을 동기로 돌리느라 막혀 있어 그 작업을 처리할 수 없다(자기 자신을 기다리는 교착).
    asyncio.to_thread로 fn을 별도 스레드에서 돌리면 루프 스레드는 비어 있어 안의 _run_async가 걸어도 바로 처리된다.
    functools.wraps로 __name__·시그니처(__wrapped__ 경유 inspect.signature)를 그대로 보존 — ADK가 도구 이름·
    인자 스키마를 뽑을 때 원래 fn과 같아야 한다(run_agent()의 __name__ 일치 검사도 이 래퍼 이전에 끝남).
    fn이 이미 async면 그대로 돌려준다(이중 래핑 금지) — dev/modules/parse/post/agent_step.py의 _off_loop가
    이미 바로 이 교착을 10-08에 같은 방식으로 직접 고쳐 자기 tools를 async로 바꿔 run_agent에 넘긴다(실측
    커밋 주석 "10-08 기능 시험 ① 실측"). 거기에 asyncio.to_thread(이미 async인 콜러블, ...)을 또 씌우면 그
    async 함수를 "호출"만 하고(코루틴 객체 생성, 실행은 안 함) 그 코루틴 객체를 스레드의 "결과"로 돌려주므로
    아무도 await를 안 해(RuntimeWarning: coroutine was never awaited) 실제 결과 대신 코루틴 객체가 그대로
    도구 응답이 돼 JSON 직렬화가 깨진다(실측, dev_tools/unit_test/pipeline/test_dev_selftests.py agent_step.py 회귀)."""
    import asyncio
    import functools
    import inspect

    if inspect.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    async def _wrapped(**kwargs):
        return await asyncio.to_thread(fn, **kwargs)

    return _wrapped


class _TurnReserves:
    """GA9 독립 검토 — run_agent()의 턴별 $ 선차감을 턴 하나짜리 공용 슬롯(dict 한 칸)에 두면, root 턴과
    AgentTool로 감싼 sub_agent 턴이 겹칠 때(ADK가 모델이 요청한 병렬 도구 호출을 asyncio.gather로 동시에
    돌림 — run_agentic의 before_model_callback/after_model_callback은 root와 모든 sub_agent에 **같은 콜백**이
    붙음) 한 턴의 settle이 다른(아직 안 끝난) 턴의 예약을 지워버린다. 턴마다 다른 열쇠로 따로 추적한다 —
    **callback_context 자체가 아니라 callback_context.actions**를 열쇠로 쓴다(설치된 ADK 실측: base_llm_flow.py가
    before_model_callback·after_model_callback마다 매번 **새** CallbackContext를 만들어 callback_context 객체 자체는
    같은 턴에서도 매번 다르다 — 그러나 둘 다 같은 model_response_event.actions를 넘겨 만들므로 공개 속성
    `.actions`는 같은 턴의 before/after에서 같고, 턴마다는 다르다).
    add/pop/drain 전부 잠금 안에서(실제로는 이 run의 모든 async 콜백이 adk.py 공유 백그라운드 이벤트 루프의
    한 스레드에서만 돌아 경합이 거의 없지만, 다른 스레드가 같은 run_agent() 호출을 또 건드릴 가능성을 막는
    방어적 잠금 — 값싸므로 그냥 둔다)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}

    def add(self, key, usd):
        with self._lock:
            self._pending[key] = usd

    def pop(self, key):
        """이 열쇠의 예약을 꺼내 비운다(없으면 0.0) — 한 번 꺼내면 다시 못 꺼냄(이중 처리 방지)."""
        with self._lock:
            return self._pending.pop(key, 0.0)

    def drain(self):
        """끝까지 settle도 release도 안 된 전부를 한 번에 비워 돌려준다(실행 종료 finally)."""
        with self._lock:
            vals = list(self._pending.values())
            self._pending.clear()
        return vals


def run_agent(
    agent_id, contents, *, role, tools=None, timeout=None, fake_policy=None, token_budget=None, soft_deadline=None, per_turn_admit=False
):
    """agentic:true 패키지(dev/agents/<agent_id>/) 다중 턴 왕복(AG4, docs/architecture.md §7). `contents`는
    OpenAI messages가 아니라 google.genai.types.Content 하나(role="user", 그림 Part 포함 가능) — agent_platform.pipeline이
    쓰는 바로 그 타입을 그대로 받아 그대로 넘긴다(다중 턴은 ADK 안에서 모델이 도구를 다시 부르는 것으로 일어나므로
    OpenAI messages 왕복이 필요 없음, _complete_agent의 단일 턴 경로와 다름).
    tools: {이름: python 함수} — 패키지 agent.json의 local_tools와 정확히 같은 이름 집합이어야(다르면 모델 호출 전에 거부).
    sub_agents는 매니페스트에 선언된 대로 이 함수가 직접 로드·빌드해 AgentTool로 붙인다(호출자가 줄 것 없음) — 각자의
    model_role로 **자기 역할 주소**를 가드한다(보안 독립 검토, AG4 후속 F1 — 메인 role만 가드하면 vlm 등 다른 role의
    서브 에이전트가 외부 주소를 들고도 통과했음).
    가드는 complete()의 기본값과 같다(preguarded 아님 — 매 호출 require_internal·precheck) + 리다이렉트 차단(_guarded_client,
    _redirect_block 상자) 그대로. role="llm"·LLM_FAKE=1이면 common/llm.chat()과 같은 모양의 모의 응답(네트워크 0).
    fake_policy(AG11 2단계) — LLM_FAKE=1일 때만 쓰임(role llm·vlm): 주면 _policy_model(결정적 정책)로 run_agentic을 실제로 돌려 콜백·예산·
    궤적까지 시험(없으면 아래 옛 모의 응답 — 도구 호출 0). 실모델 경로에서는 무시.
    token_budget(AG11 2단계, ADK2) — 이 실행의 LLM 토큰(입력+출력) 상한, run_agentic 콜백이 강제(None = 상한 없음 — 기존 동작).
    soft_deadline(AG11 3단계) — 초. 다음 턴 시작 전 '지금까지 + 가장 긴 턴'이 넘으면 "시간 상한"으로 정상 멈춤(run_agentic, None = 기존).
    LLM_MAX_CALLS는 common/llm.reserve_call()/remaining_calls()/settle_calls()로 chat()과 같은 장부를 공유(AG4 후속
    F3) — 진입 시 1건만 예약(cap이 이미 바닥이면 네트워크 전에 거부)하고, 남은 수만큼만 max_turns를 깎아 실행 중
    (root+sub_agent 합산) 실제 모델 호출이 공유 장부의 남은 수를 넘지 못하게 한 뒤, 끝나고 실제 호출 수(1건 뺀 나머지)를
    정산한다 — 그래야 한 번의 run_agent 호출이 여러 번의 실모델 호출을 내면서도 장부를 1건치로만 아는 일이 없다.
    턴 단위 재시도는 하지 않는다(retries 매개변수 없음) — 모델 호출이 실패하면 이 실행 전체가 ModelUnavailable로 끝나고,
    다시 부를지는 호출자가 결정(AG4 — ADK/여기 어디에도 전체 재시도 루프를 두지 않음).
    반환: (text, trajectory, usage) — agent_platform.pipeline.run_agentic과 같은 모양.

    per_turn_admit 한계(독립 검토 10-12): 턴 단위 LLM_BUDGET_USD 선차감은 **root 역할의 호스트**로만 판정한다 — root가
    llm이 아니고 sub_agent가 외부 llm 호스트면 그 sub_agent 턴엔 금액 선차감이 없다(지금 운영 manifest엔 그런 조합 없음:
    per_turn_admit을 켜는 parse_decide는 sub_agents가 비어 있음). sub_agents를 쓰는 manifest에 켜기 전에 턴별 역할로 일반화.
    per_turn_admit(GH1-08b, 옵트인·기본 False — 기존 동작 그대로, PARSE_AGENT 경로만 켬): 위 F3의 "진입 시 1건만
    예약 + 남은 수만큼 max_turns 깎기"는 **한 번 찍은 스냅샷**이라, 동시에 여러 run_agent() 호출이 겹치면(--procs)
    서로 같은 순간의 remaining_calls()를 읽어 둘 다 통과시킬 수 있다(실측 — 공유 상한을 넘김). True면 그 대신 매 턴
    (root+sub_agent 모델 호출마다, run_agentic의 before_model_callback)마다 common/llm.try_reserve_call()로 원자적
    확인+예약 — 동시 실행끼리도 상한을 못 넘는다(cap 도달 턴은 네트워크 전에 "공유 호출 상한"으로 정상 멈춤, 예외
    아님). 같은 자리에서 외부 LLM 호스트의 LLM_BUDGET_USD도 턴 단위로 선차감(VLM·EMBED와 같은 고정 추정액 —
    common/guard.precheck()는 role=LLM을 건너뛴다, llm.chat()의 토큰 기준 정산 경로를 run_agent는 안 거치므로) —
    예산 소진이면 역시 그 턴에서 정상 멈춤.
    GA9(10-13 독립 검토 — 18턴×flat $0.01=$0.18 vs 토큰 기준 실비 $0.031): 위 턴별 선차감은 **전엔 settle 없이
    영구히 남았다**(VLM 호출은 settle_tokens로 전부 정산되는데 이 role=LLM 경로만 빠져 있었음). 이제 매 턴 응답의
    usage로 guard.settle_tokens(VLM/llm.chat과 같은 함수, BR45)로 정산하고(settle_fn·run_agentic의 settle=),
    턴 응답을 못 받고 실행이 실패·취소되면(이 함수의 바깥 try/finally) 그 턴의 선차감을 guard.release_reserve로
    전액 반환한다 — ModelGuardPlugin.release_if_outstanding과 같은 자세(두 경로 다 같은 release_reserve 재사용)."""

    pkg = _load_pipeline(agent_id)
    if not pkg.manifest.agentic:
        raise ModelUnavailable(f"{agent_id}: agentic:true 패키지가 아님(run_agent는 agentic 전용 — complete(agent=)를 쓸 것)")
    if pkg.manifest.model_role != role:
        raise ModelUnavailable(f"{agent_id}: model_role={pkg.manifest.model_role!r} != 호출 role={role!r}")
    tools = tools or {}
    if set(tools) != set(pkg.manifest.local_tools):
        raise ModelUnavailable(f"{agent_id}: tools 이름이 local_tools와 다름 — {sorted(tools)} != {sorted(pkg.manifest.local_tools)}")
    for name, fn in tools.items():
        # ADK의 FunctionTool은 등록 이름을 fn.__name__에서 가져온다(딕셔너리 키가 아님) — 둘이 다르면 모델은 실제로
        # fn.__name__으로 등록된 도구를 보게 되어 local_tools 이름과 어긋난다(실측: __name__이 다르면 ADK가 "Tool not
        # found"로 조용히 실패하고도 trajectory·allow-list는 (요청받은) 선언 이름 기준이라 들키지 않음).
        if getattr(fn, "__name__", None) != name:
            raise ModelUnavailable(
                f"{agent_id}: tools[{name!r}] 함수의 __name__={getattr(fn, '__name__', None)!r} — "
                "ADK가 도구를 등록하는 이름과 달라 모델이 같은 이름으로 못 찾음"
            )

    if role in ("llm", "vlm") and fake_policy is not None and fake_llm():
        # AG11 2단계 — 가짜 정책 모델로(3단계: vlm 역할 판단 세션 parse_decide_vlm도 같은 시험 경로 — AG6 M2) run_agentic(실제 콜백: 허용 도구·도구/모델 호출·토큰 예산·궤적)을 끝까지(네트워크 0)
        # TODO: 리팩토링 후 구현 필요
        # from agent_platform.pipeline import run_agentic
        # from google.adk.tools.function_tool import FunctionTool
        # _L.record_fake_call(sum(len(p.text or "") for p in (contents.parts or [])))
        # concrete = pkg.build(_policy_model(fake_policy), [FunctionTool(_to_thread_tool(fn)) for fn in tools.values()])
        # return _run_async(run_agentic(concrete, contents, tools=pkg.manifest.local_tools, sub_agents=pkg.manifest.sub_agents,
        #                               max_turns=pkg.manifest.max_turns, budget=pkg.manifest.budget,
        #                               timeout=float(timeout) if timeout else 120.0, token_budget=token_budget,
        #                               soft_deadline=soft_deadline))
        # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
        from google.adk.tools.function_tool import FunctionTool

        from common.ai import llm as _L

        _L.record_fake_call(sum(len(p.text or "") for p in (contents.parts or [])))
        concrete = pkg.build(_policy_model(fake_policy), [FunctionTool(_to_thread_tool(fn)) for fn in tools.values()])
        return _run_async(
            _run_agentic(
                concrete,
                contents,
                tools=pkg.manifest.local_tools,
                sub_agents=pkg.manifest.sub_agents,
                max_turns=pkg.manifest.max_turns,
                budget=pkg.manifest.budget,
                timeout=float(timeout) if timeout else 120.0,
                token_budget=token_budget,
                soft_deadline=soft_deadline,
            )
        )

    if role == "llm" and fake_llm():
        from common.ai import llm as _L

        text_in = "".join(p.text or "" for p in (contents.parts or []) if p.text)
        _L.record_fake_call(len(text_in))
        return text_in[:200] + "[FAKE]", [], {"prompt_tokens": 0, "completion_tokens": 0, "model_calls": 0, "tool_calls": 0, "fake": True}

    prof = profile(role)
    if prof is None:
        raise ModelUnavailable(f"{role.upper()}_BASE_URL·{role.upper()}_MODEL 미설정")
    guard_prefix = _ROLE_GUARD_PREFIX[role]
    require_internal(prof.base_url, guard_prefix)
    precheck(prof.base_url, guard_prefix)

    # sub_agents 선주소 가드(F1) — 아래에서 실제로 빌드하기 전에, 모델 호출을 시작하기도 전에 전부 먼저 확인한다
    # (메인 role과 같은 두 겹: require_internal + precheck, 역할별 prefix로 — vlm 서브 에이전트가 외부 주소를
    # 들고도 메인 role만 가드돼 통과하던 구멍, 보안 독립 검토).
    sub_profiles = {}
    for sub_id in pkg.manifest.sub_agents:
        sub_pkg = _load_pipeline(sub_id)
        sub_role = sub_pkg.manifest.model_role
        sub_prof = profile(sub_role)
        if sub_prof is None:
            raise ModelUnavailable(f"{sub_id}: {sub_role.upper()}_BASE_URL·{sub_role.upper()}_MODEL 미설정")
        sub_guard_prefix = _ROLE_GUARD_PREFIX[sub_role]
        require_internal(sub_prof.base_url, sub_guard_prefix)
        precheck(sub_prof.base_url, sub_guard_prefix)
        sub_profiles[sub_id] = (sub_pkg, sub_role, sub_prof, sub_guard_prefix)

    from common.ai import llm as _L

    admit_fn = None
    settle_fn = None
    turn_reserves = _TurnReserves()  # GA9 — 턴별(callback_context로 구분) 미정산 예약, root+sub_agent 동시 턴 안전
    if per_turn_admit:  # GH1-08b — 턴마다 원자적 확인+예약(동시 실행 안전), 위 F3의 1회 스냅샷 대신
        from common.ai import guard as G

        def admit_fn(callback_context):
            from common.ai.guard import is_internal as _is_internal

            # guard_prefix=="LLM"만 — VLM 등 다른 역할은 위 precheck()가 호출 전에 이미 flat 선차감을 함(prefix!="LLM").
            # role=LLM만 그 분기에서 빠지므로(llm.chat()의 토큰 기준 정산을 run_agent는 안 거침) 여기서 턴 단위로 채운다.
            # 상한 읽기(형식 틀리면 ValueError)는 호출 수 예약 앞에서 — 예약한 뒤 실패해 자리가 새지 않게(S7c1 리뷰)
            budget = G.budget_usd() if guard_prefix == "LLM" and not _is_internal(prof.base_url) else None
            if not _L.try_reserve_call():
                return False
            if budget is not None:  # S7b — 옛 truthy(글자 "0"도 참)와 같게 is not None
                usd = cfg().models.llm.est_usd  # 옛 float(env or G._EST_USD.get("LLM", 0.01)) — 모델 기본 0.01 같음
                try:
                    G.spend_reserve(usd, "LLM")
                except G.BudgetExceeded:
                    _L.release_call()
                    return False
                turn_reserves.add(id(callback_context.actions), usd)
            return True

        def settle_fn(callback_context, usage):
            """GA9(독립 검토 반영) — admit_fn이 이 턴에 선차감했으면 턴 응답의 실제 usage로 guard.settle_tokens
            정산(VLM/llm.chat과 같은 함수, 중복 구현 없음). usage가 비어 있는데 settle_fn이 **불렸다는 것**은
            실제 응답은 왔지만 그 응답에 토큰 수가 없었다는 뜻(모델/전송이 usage를 안 주는 드문 경우) — settle_tokens
            자신의 보수적 자세와 같게, 선차감한 flat $를 **그대로 둔다**(반환하지 않음, CRITICAL 독립 검토 — 실제
            과금된 턴을 release_reserve로 0으로 되돌리면 안 됨). pop()으로 이미 '미정산' 목록에서는 뺐으니 바깥
            finally가 이걸 다시 release하지도 않는다(이중 처리 없음) — settle도 release도 전혀 못 받은, 응답 자체가
            안 온 턴(예외·취소·short-circuit)만 finally의 drain()이 반환한다."""
            usd = turn_reserves.pop(id(callback_context.actions))
            if usd and usage:
                G.settle_tokens(usd, prof.model, usage)

        max_turns = pkg.manifest.max_turns
    else:
        try:
            _L.reserve_call()  # common/llm.LLMUnavailable — chat()·run_agent() 공유 장부(한쪽이 쓰면 다른 쪽도 줄어듦)
        except _L.LLMUnavailable as ex:
            raise ModelUnavailable(str(ex)) from ex
        max_turns = pkg.manifest.max_turns
        remaining = _L.remaining_calls()  # None=무제한 — reserve_call()이 이미 이번 실행의 1건째를 차감한 뒤의 나머지
        if remaining is not None:
            max_turns = min(max_turns, remaining + 1)  # 이미 예약한 1건 + 남은 만큼만(합산해도 장부를 못 넘음, F3)
    deadline = float(timeout) if timeout else 120.0

    from google.adk.tools.agent_tool import AgentTool
    from google.adk.tools.function_tool import FunctionTool

    model = _lite_llm(prof, deadline, guard_prefix)
    real_tools = [FunctionTool(_to_thread_tool(fn)) for fn in tools.values()]  # GH1-07 — 교착 방지(위 설명)
    for _sub_id, (sub_pkg, _sub_role, sub_prof, sub_guard_prefix) in sub_profiles.items():
        sub_model = _lite_llm(sub_prof, deadline, sub_guard_prefix)
        # mode="chat"으로 덮어씀 — AgentTool.run_async는 감싼 에이전트를 자기 Runner의 **root**로 돌리는데, ADK
        # Runner는 root가 mode="chat"/"task"만 허용한다(실측: single_turn root는 ValueError). 이 패키지의 '원래'
        # 선언(단일 턴 — 보통 호출부인 run_once/Workflow 경유 path)은 그대로 두고, 여기(AgentTool로 쓸 때)만 바꾼다
        # — identity 시스템 문구가 덧붙는 대가가 있지만(I3/I4는 그 '원래' 경로에만 약속된 것이라 영향 없음) 그 경로는
        # 안 건드렸으므로 기존 16개 패키지의 단일 턴 동작(캐시 열쇠 포함)은 그대로다.
        sub_agent = sub_pkg.build(sub_model).model_copy(update={"mode": "chat"})
        real_tools.append(AgentTool(sub_agent))
    concrete = pkg.build(model, real_tools)
    blocked_box = {"host": None}

    async def _call():
        _redirect_block.set(blocked_box)
        # TODO: 리팩토링 후 구현 필요
        # from agent_platform.pipeline import run_agentic
        # return await run_agentic(concrete, contents, tools=pkg.manifest.local_tools, sub_agents=pkg.manifest.sub_agents,
        #                           max_turns=max_turns, budget=pkg.manifest.budget, timeout=deadline, live=live,
        #                           token_budget=token_budget, soft_deadline=soft_deadline, admit=admit_fn, settle=settle_fn)
        # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
        return await _run_agentic(
            concrete,
            contents,
            tools=pkg.manifest.local_tools,
            sub_agents=pkg.manifest.sub_agents,
            max_turns=max_turns,
            budget=pkg.manifest.budget,
            timeout=deadline,
            live=live,
            token_budget=token_budget,
            soft_deadline=soft_deadline,
            admit=admit_fn,
            settle=settle_fn,
        )

    live = {}
    try:
        text, trajectory, usage = _run_async(_call())
    except Exception as ex:
        _raise_classified(ex, blocked_box)
    finally:
        if not per_turn_admit:  # F3 정산 — per_turn_admit은 턴마다 이미 집계했으므로 끝에 다시 정산하면 이중 집계
            _L.settle_calls(max(0, int((live.get("state") or {}).get("model_calls") or 1) - 1))
        else:  # GA9 — 응답을 못 받아(예외·취소·short-circuit) settle_fn이 못 돈 턴들의 예약을 전부 반환
            for usd in turn_reserves.drain():
                from common.ai import guard as G

                G.release_reserve(usd)
    return text, trajectory, usage


def _complete_http(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix):
    """기존 urllib 경로(MODEL_TRANSPORT=http) — 어댑터 안 한 호출의 롤백·GA-T3 parity 비교용. body는 전환 전과 같은 모양
    (model은 접두어 없는 원래 이름 — I1, 캐시 열쇠·로그에 "openai/"가 섞이지 않게)."""

    model_name = prof.model.removeprefix("openai/")
    body = {"model": model_name, "temperature": temperature, "messages": messages}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    extra_body = _extra_body(json_mode, extra)
    if extra_body:
        body.update(extra_body)
    headers = {"Content-Type": "application/json"}
    key = _prof_key(prof)
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(prof.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    try:
        with _g_urlopen(req, timeout, guard_prefix) as r:
            data = json.load(r)
    except urllib.error.HTTPError as ex:
        if ex.code in (429, 500, 502, 503, 504):
            ra = ex.headers.get("Retry-After") if ex.headers else None
            raise _Retryable(ex, retry_after=float(ra) if ra else None) from ex
        raise ModelUnavailable(f"모델 호출 실패: HTTPError {ex.code}: {str(ex)[:200]}") from ex
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise _Retryable(ex) from ex
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    u = data.get("usage") or {}
    return text, {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0)}


def complete(
    role,
    messages,
    *,
    temperature=0.0,
    max_tokens=1024,
    json_mode=False,
    timeout=None,
    extra=None,
    retries=3,
    preguarded=False,
    agent=None,
    call_reserved=False,
):
    """역할(llm·vlm·vlm_judge — 임베딩은 common/embed.py 유지, GA6) → (응답 글자, usage_dict).
    agent=dev/agents/<agent_id> — gamma 에이전트 패키지 경유(_complete_agent, GA2 설계 §1). 업무 호출부(modules/·cli/·eval/)는
    전부 이걸 넘겨야 한다(cli/check_modules.py 정적 검사) — 패키지의 model_role이 role과 달라도 이 자리에서 바로 막힌다.
    agent=None은 옛 직접 모델 경로(이 파일 자신의 selftest·cli/ping_models.py의 연결 확인처럼 업무 프롬프트가 없는 호출용).
    MODEL_TRANSPORT=http이면 ADK/에이전트를 아예 안 쓰므로 agent는 무시(롤백 경로 — 기존 urllib 본문 그대로).
    max_tokens=None이면 그 필드를 요청 본문에 안 보냄(쪽 전체 VLM 옮기기처럼 출력 상한을 서버 기본값에 맡기던 호출용 — 전환 전과 같음).
    가드는 **기본으로 항상** 호출 전(require_internal·precheck, 둘 다 매번 URL을 그 자리에서 다시 확인) — 외부 주소 거부·
    NO_PAID_CALLS 차단·비-LLM 외부 고정 예상액 선차감. preguarded=True는 common/llm.py chat()만 쓴다 — chat()이 자기
    allow_external 매개변수(env 아닌 파라미터 기반, run_answers·wiki_draft 호환)로 이미 더 엄격하게 가드를 통과시킨
    뒤에만 — 그 밖의 모든 직접 호출자(cli/ping_models.py 포함)는 기본값(preguarded=False)으로 매번 require_internal을
    거친다(보안 독립 검토 2026-10-06 지적 — 역할별 예외를 두면 새 호출자가 가드 없이 외부로 나갈 수 있어 공용 함수가
    기본으로 막고 신뢰하는 호출자만 명시적으로 건너뛰게 바꿈). 재시도는 ADK/litellm 자동 재시도가 아니라 여기 우리
    코드(429·5xx·연결·타임아웃만, 마지막 실패 뒤엔 대기 없음).
    GH1-08d — agent=인 경로(_complete_agent)의 1차 호출은 common/llm.LLM_MAX_CALLS 공유 장부를 거쳐야 한다. 지금까지
    post/vlm_page.py·post/figures.py 등 chat()을 안 거치는 직접 호출자는 reserve_call()을 전혀 안 거쳐 상한 밖이었다
    (개별 호출부를 고치는 대신 이 공용 진입점 한 곳에서: agent= + 아직 예약 안 됨이면 여기서 common/llm.try_reserve_call()로
    **전송 재시도 루프 진입 전에 딱 한 번** 예약 — 429/5xx 재시도가 같은 논리적 1호출을 여러 번 예약하지 않게). call_reserved=True는
    common/llm.chat()의 _do_call()처럼 **호출자가 이미 reserve_call()로 이 1차 호출의 자리를 예약한** 경우 — 여기서
    다시 예약하면 이중 집계라 건너뜀. 상한 도달이면 ModelUnavailable(네트워크 요청 0건 — 기존 에러 모양과 같아 호출부가
    그대로 처리, 캐시·크래시 없음).
    RV16 — 직접 호출자(post/figures.py·post/vlm_page.py·post/agent_step.py·post/reread_stage3.py)는 common/llm.chat()을
    안 거쳐 RV12 빈 응답 안전망(생각이 max_tokens를 다 써 빈 응답 → 4배로 딱 한 번 재요청) 밖에 있었다 — 호출부마다
    고치는 대신 agent= 경로의 이 공용 지점에서 한 번만: call_reserved가 **원래 False로 들어왔을 때**만(= chat()이
    아닌 직접 호출자 — chat()은 이미 자기 자리에서 같은 안전망을 가짐, 여기서 또 하면 두 안전망이 겹쳐 최대 4번까지
    늘어난다) LLM_EMPTY_RETRY(기본 켬·=0으로 끔)·LLM_EMPTY_RETRY_MAX(기본 8000)를 그대로 재사용해 같은 재요청을
    한다. 재요청도 try_reserve_call()로 공유 장부를 거치고(캐시·과금 이중 집계 없음), 재요청이 전송 오류로 못
    끝나면 그 슬롯을 release_call()로 돌려주고 바깥 재시도 루프(429/5xx)에 맡긴다(GH1-08e와 같은 모양).
    RV24 — 전송 전에 base_url별 공유 회로 차단기(_model_down)를 본다: 연속 MODEL_DOWN_AFTER회 연결·타임아웃
    실패 뒤 MODEL_DOWN_COOLDOWN초는 네트워크를 전혀 안 보내고 즉시 ModelUnavailable(그 자리에서 거부 —
    호출자가 이미 reserve_call()로 자리를 예약해 둔 경우(call_reserved=True)는 release_call()로 돌려줌,
    그 밖엔 이 함수가 아직 아무 자리도 예약하지 않은 시점이라 돌려줄 것이 없음).
    독립 검토 BLOCK(2026-10-12) — litellm은 connect 타임아웃과 read 타임아웃을 둘 다 같은 litellm.Timeout으로
    매핑해(exception_mapping_utils.py) 예외 타입만으로 못 가른다. 살아있지만 느린 서버(정상 쪽 35~65초)가 read
    타임아웃을 반복하면(연결은 매번 바로 됨, 응답만 늦음) 그걸 '다운'으로 세면 그 뒤 빠른 쪽까지 전부 회로에
    막혀 OCR로 떨어진다(정확도 회귀) — 그래서 마지막 시도가 걸린 시간이 MODEL_CONNECT_TIMEOUT×1.5 이내(연결
    자체가 안 되는 빠른 실패)일 때만 회로 실패로 센다. 그보다 오래 걸렸으면(연결은 됐고 응답만 늦음) 안 센다."""
    prof = profile(role)
    if prof is None:
        raise ModelUnavailable(f"{role.upper()}_BASE_URL·{role.upper()}_MODEL 미설정")
    guard_prefix = _ROLE_GUARD_PREFIX[role]
    if _model_down(prof.base_url):
        if call_reserved:
            from common.ai import llm as _L

            _L.release_call()
        host = urllib.parse.urlparse(prof.base_url).hostname or prof.base_url
        raise ModelUnavailable(
            f"모델 다운({role}_down) — {host} 연속 {_model_down_after()}회 이상 실패, 쿨다운 중(MODEL_DOWN_COOLDOWN) — 호출 안 보냄"
        )
    reserved = 0.0
    try:
        if not preguarded:
            require_internal(prof.base_url, guard_prefix)
        reserved = precheck(prof.base_url, guard_prefix)  # BR45 — role!=llm 외부 호출의 flat 선차감액(내부망·llm이면 0.0)
    except GuardBlocked:
        raise
    except RuntimeError as ex:  # require_internal(외부 주소)·precheck(BudgetExceeded) — 호출 전에 막힘 → GuardBlocked로 한 곳에서
        raise GuardBlocked(str(ex)) from ex
    extra = _merged_extra(role, extra)  # LLM_EXTRA_BODY·VLM_EXTRA_BODY(RV12) — 호출자 extra가 우선, 세 전송 분기 공용
    deadline = float(timeout) if timeout else 120.0
    transport = cfg().models.transport.transport  # S7b — 설정 객체(옛 env or "adk")
    direct_agent_call = (
        agent is not None and transport != "http" and not call_reserved
    )  # RV16 — chat() 호출은 call_reserved=True로 들어와 여기선 False(자기 안전망을 따로 가짐)
    if direct_agent_call:
        from common.ai import llm as _L  # GH1-08d — 직접 호출자의 1차 호출도 공유 장부에(재시도 루프 진입 전, 딱 한 번)

        if not _L.try_reserve_call():
            raise ModelUnavailable("LLM_MAX_CALLS 도달 — 호출 보내지 않음(GH1-08d, 직접 호출자)")
        call_reserved = True
    last_err = None
    last_attempt_elapsed = None  # RV24 BLOCK — 마지막 시도가 걸린 시간(연결 실패 vs 느린 응답 가름용)
    for attempt in range(retries):
        attempt_t0 = time.monotonic()
        try:
            if transport == "http":
                text, u = _complete_http(prof, messages, temperature, max_tokens, json_mode, extra, deadline, guard_prefix)
            elif agent is not None:
                text, u = _complete_agent(agent, role, prof, messages, temperature, max_tokens, json_mode, extra, deadline, guard_prefix)
                if (
                    direct_agent_call and cfg().models.llm.empty_retry and _L._empty_truncated(text, u)
                ):  # RV16 — RV12와 같은 판정 함수(중복 구현 안 함)
                    cap = cfg().models.llm.empty_retry_max
                    retry_tokens = cap if max_tokens is None else min(max_tokens * 4, cap)
                    if retry_tokens > (max_tokens or 0):
                        from common.ai import llm as _L

                        if _L.try_reserve_call():  # 재요청도 공유 장부 거침(GH1-08c 원자적 확인+예약) — 못 받으면 1차 결과 그대로
                            first = dict(u)
                            try:
                                text, u = _complete_agent(
                                    agent, role, prof, messages, temperature, retry_tokens, json_mode, extra, deadline, guard_prefix
                                )
                            except _Retryable:  # GH1-08e와 같은 모양 — 못 쓴 슬롯을 돌려주고 바깥 429/5xx 루프에 맡김
                                _L.release_call()
                                raise
                            u = dict(u or {})
                            for k in ("prompt_tokens", "completion_tokens"):
                                u[k] = (first.get(k) or 0) + (u.get(k) or 0)
                            u["calls"] = 2
            else:
                text, u = _complete_adk(prof, messages, temperature, max_tokens, json_mode, extra, deadline, guard_prefix)
            if reserved:  # BR45 — 실제 토큰 usage로 사후 정산(단가 모르면 settle_tokens가 그대로 둠, 기존 flat 유지)
                from common.ai import guard as G

                G.settle_tokens(reserved, prof.model, u)
            _model_down_reset(prof.base_url)  # RV24 — 성공 1회로 연속 실패 수를 지움
            return text, u
        except _Retryable as ex:
            last_err = ex.inner
            last_attempt_elapsed = time.monotonic() - attempt_t0
            if attempt < retries - 1:
                time.sleep(ex.retry_after if ex.retry_after else 2**attempt * 2)
    # 재검토 CONCERN(a) — 문턱을 이 호출의 deadline에도 묶는다: deadline이 문턱 이하로 짧으면(빠른 분류용 짧은 호출 등)
    # 느린 응답도 deadline에서 잘려 '빠른 실패'로 잘못 세지므로 deadline의 절반을 넘지 않게.
    if last_attempt_elapsed is not None and last_attempt_elapsed <= min(_fast_failure_threshold(), deadline * 0.5):
        # RV24 BLOCK — 마지막 시도가 빨리 끝났을 때만(연결 자체가 안 됨) 회로 실패로 센다. 느리게 끝났으면(연결은
        # 됐고 응답만 늦음 — 살아있지만 느린 서버) 안 센다, 그래야 그 신호로 빠른 쪽까지 묶어 OCR로 떨어지지 않음.
        _model_down_mark_failure(prof.base_url)
    if call_reserved:  # GH1-08 family 누수 — 1차 호출의 예약 자리(직접 호출자는 위에서, chat()은 _do_call()이 예약)를
        from common.ai import llm as _L  # 끝까지 못 쓰면 여기 한 곳에서 돌려줌(재검토 CONCERN(b) — chat() 경로도 같은 규칙,

        _L.release_call()  # 쿨다운 즉시 거부 분기와 같은 주인 — _do_call()은 돌려주지 않음, 이중 release 없음)
    if reserved:  # BR45 후속(10-13) — precheck()가 선차감한 flat $(reserved)는 지금까지 성공(line 870 settle_tokens)
        from common.ai import guard as G  # 에서만 정산됐다 — 재시도를 전부 못 쓰면(usage 없음) 여기까지 settle이

        G.spend_settle(-reserved)  # 전혀 안 거쳐 flat 추정이 영구히 장부에 남는다(release_call()의 "실패=과금 안 됨"과
        # 같은 가정 — 과금됐을 수 있는 드문 경우는 그 쪽 가정과 함께 보수적 위험을 진다). F7 중첩(nested.py)처럼 재시도가
        # 잦은 경로에서 실측된 6배 과대 집계(장부 $0.193 vs 토큰 기준 실비 $0.031, 49호출)의 원인 — 이 공용 지점 한
        # 곳만 고치면 role=vlm인 모든 직접 호출자(nested.py·figures.py 등)에 똑같이 적용된다(중복 구현 없음).
    raise ModelUnavailable(f"모델 호출 실패(재시도 {retries}회): {type(last_err).__name__}: {str(last_err)[:200]}") from last_err
