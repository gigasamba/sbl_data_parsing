"""LLM 공통 클라이언트 — OpenAI 호환 /chat/completions (서버 GLM-5.2 · 나중에 Gemini OpenAI 호환 주소 · 개발 PC 모의 서버).

설정(settings.yaml): LLM_BASE_URL(…/v1) · LLM_MODEL · LLM_API_KEY(있을 때만) · LLM_TIMEOUT(초, 기본 120) · LLM_RPM(분당 호출 상한, 기본 0=무제한)
          · LLM_CACHE_DIR(기본 output/eval/llm_cache)
          · LLM_BUDGET_USD(외부 모델 하루 지출 상한, 기본 0.1 — 넘으면 이후 호출을 보내기 전에 거부) · LLM_PRICE_IN·LLM_PRICE_OUT($/M 토큰, 기본 PRICES[모델])
- **응답 캐시**: (모델, 메시지, 온도) 해시가 같으면 다시 부르지 않는다 — 재실행·다른 조합이 같은 질문을 해도 토큰 0.
- **비용 관문(2026-10, OpenRouter 85% 소진 이후)**: LLM_FAKE=1이면 네트워크 호출 없이 모의 응답(마지막 user 메시지 앞 200자+"[FAKE]") —
  캐시에 안 쓰고 usage()에 fake_calls·prompt_chars만 쌈(추정기가 이걸로 호출 수·글자 수를 모음). 실호출은 LLM_BUDGET_USD로 상한.
- **외부 전송 가드(DONT 13, 여기 한 곳에서 강제)**: LLM_BASE_URL이 내부 주소(사설 IP·localhost·.local/.internal/.corp·단일 이름)가 아니면
  설정 `LLM_ALLOW_EXTERNAL=1`(또는 호출 인자 `allow_external=True`) **그리고** RUN_ENV=local일 때만 호출한다(서버 dev·prd는 외부 호출 불가).
- 호출·토큰 수는 usage()로 — 도구가 결과 파일에 함께 남긴다.
- **빈 응답 안전망(RV12, 2026-10-09 재순위 실측 — glm-5.2가 생각에 max_tokens를 다 써 ~45% 빈 응답)**: 응답이 비어 있고(공백만
  포함) 토큰을 썼다면(completion_tokens>0 — 생각이 출력 상한을 다 썼다는 신호, finish_reason을 3개 전송 경로 모두에서
  따로 끌어오지 않고 이미 있는 값으로 판정) `max_tokens`를 4배(`LLM_EMPTY_RETRY_MAX` 상한, 기본 8000)로 올려 **딱 한 번**
  재요청한다. 재요청도 공유 장부(LLM_BUDGET_USD·호출 수)를 그대로 거친다.
  빈 응답(재요청 뒤에도 빈 경우 포함)은 캐시에 쓰지 않는다 — 전에는 빈 응답이 캐시에 고착돼 다음 호출도 계속 빈 응답을 받았음.
- **생각 끄기(RV12)**: env `LLM_EXTRA_BODY`(JSON 객체)가 OpenRouter·vLLM 요청 본문에 그대로 섞여 들어간다 — 실제 머지는
  이 파일 complete()(VLM도 `VLM_EXTRA_BODY`로 같은 메커니즘, 역할별 분리) 한 곳.
- **모델 호출**: complete(role, messages) — OpenAI 호환 HTTP 한 길(0.2.0 — 옛 common/ai/adk.py의 ADK·litellm 장치를 지우고 이리로, pl-46).
"""

import dataclasses
import functools
import hashlib
import json
import threading
import time
import urllib.parse
from pathlib import Path

from common.config.settings import by_env, cfg, checked, reveal
from common.core import span as _span
from common.core.paths import APP_ROOT

ROOT = APP_ROOT
_lock = threading.Lock()
_stats = {"calls": 0, "cache_hits": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0, "fake_calls": 0, "prompt_chars": 0, "spend_usd": 0.0}
_last = [0.0]

# $/M 토큰(OpenRouter 2026-10-05 조회) — env LLM_PRICE_IN/LLM_PRICE_OUT로 덮어씀(추정기·예산 공용). 열쇠는 제조사 접두어 없는 모델 이름.
PRICES = {
    "glm-5.2": {"in": 0.104, "out": 8.0},
    "glm-5.3": {"in": 1.4, "out": 4.4},
    "glm-5.3-flash": {"in": 0.15, "out": 0.5},
    "qwen3.5-397b-a17b": {"in": 0.55, "out": 3.5},
    "qwen3.8-flash": {"in": 0.15, "out": 0.47},
    "qwen3-vl-30b-a3b-instruct": {"in": 0.15, "out": 0.6},
}  # 10-13 VLM(OpenRouter, Qwen3-VL-32B 폐기 대체 — 사용자 결정)


class LLMUnavailable(RuntimeError):
    pass


def configured():
    return bool(cfg().models.llm.base_url and cfg().models.llm.model)


from common.ai.guard import external_ok, fake_llm, is_internal, require_internal, run_env_block  # noqa: E402 — 내부망 확인은 common 한 곳

# CT1(10-16) — models.py 병합(역할별 모델 프로필 조회, agent_platform.config.ModelProfile 재사용 — 사용자 결정 2026-10-06).
# 설정 객체에서만 읽음(S7b — 호출 시점 cfg(), 전환 기간엔 env로 만든 객체라 테스트가 env를 바꾸면 반영). 기존 LLM_BASE_URL·VLM_BASE_URL·EMBED_* 등은 그대로 하위 호환.
_ROLE_PREFIX = {"llm": "LLM", "vlm": "VLM", "embed": "EMBED"}


@dataclasses.dataclass(frozen=True)
class ModelProfile:
    """대체 구현(10-26): 옛 agent_platform.config.ModelProfile(pydantic)과 같은 칸·같은 검사 — TODO 해결 전 임시.
    classification은 선언일 뿐 가드에 쓰지 않는다(complete()가 매 호출 URL을 다시 확인)."""

    model: str
    base_url: str
    key_env: str | None = None
    classification: str = "public"
    version_label: str = "development"

    def __post_init__(self):
        u = urllib.parse.urlsplit(self.base_url)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query:
            raise ValueError("model base_url must be an explicit HTTP(S) endpoint without credentials")
        if not self.model.startswith("openai/"):
            raise ValueError("initial connector requires an explicit openai/ compatible model identifier")
        if self.classification not in {"public", "internal", "external"}:
            raise ValueError(f"classification must be public|internal|external: {self.classification!r}")


def profile(role):
    """역할 → ModelProfile(판정 역할 vlm_judge는 0.2.0에 지움 — pl-46, 부르는 곳 없음).
    agent_platform import는 여기서 늦게(지연) — structure·retrieval 이미지는 agent_platform 없이도 이 모듈을
    import할 수 있어야 한다(profile()을 실제로 부르는 경로만 agent_platform이 필요, MOD 10-14)."""
    # TODO: 리팩토링 후 구현 필요
    # try:
    #     from agent_platform.config import ModelProfile
    # except ImportError as e:
    #     raise ImportError(
    #         f"agent_platform(저장소 루트 deploy/agent_platform)을 못 찾음 — dev/와 deploy/가 같은 저장소 루트의 형제 폴더여야 함: {e}"
    #     ) from e
    prefix = _ROLE_PREFIX[role]
    base, model = by_env(f"{prefix}_BASE_URL"), by_env(f"{prefix}_MODEL")  # key_env는 env 이름 글자 그대로(아래)
    key = reveal(by_env(f"{prefix}_API_KEY"))
    if not (base and model):
        return None
    # TODO: 리팩토링 후 구현 필요
    # return ModelProfile(model="openai/" + model, base_url=base, key_env=(f"{prefix}_API_KEY" if key else None),
    #                      classification="internal" if is_internal(base) else "public")
    # 대체 구현(10-26): agent_platform 없이 env의 OpenRouter(OpenAI 호환) 설정으로 — TODO 해결 전 임시
    return ModelProfile(
        model="openai/" + model,
        base_url=base,
        key_env=(f"{prefix}_API_KEY" if key else None),
        classification="internal" if is_internal(base) else "public",
    )


def usage():
    return dict(_stats)


def reserve_call():
    """호출 1건을 공유 장부(_stats["calls"])에 센다(AG4) — chat()·complete()·PC 도구 왕복(validation/e2e/tool_loop) 모두 같은 장부.
    호출 수 상한(옛 LLM_MAX_CALLS)은 11-03에 지웠다(사용자 — 지출 상한 LLM_BUDGET_USD만 남김) — 세기만 한다(usage())."""
    with _lock:
        _stats["calls"] += 1


def release_call():
    """GH1-08e — reserve_call()로 센 1건을 같은 잠금 안에서 되돌린다(실패한 재요청이 바깥 재시도에서 두 번 세지 않게).
    calls가 이미 0이면 더 깎지 않음(음수 방지). 금액 상한은 guard.py(LLM_BUDGET_USD)가 따로 지킨다."""
    with _lock:
        if _stats["calls"] > 0:
            _stats["calls"] -= 1


def record_fake_call(prompt_chars):
    """LLM_FAKE=1 집계 — chat()과 run_agent() 둘 다 같은 _stats를 쓴다(AG4)."""
    with _lock:
        _stats["calls"] += 1
        _stats["fake_calls"] += 1
        _stats["prompt_chars"] += prompt_chars


def fake_reply(messages):
    """LLM_FAKE=1 모의 응답 — chat()과 같은 모양(마지막 user 메시지 글자 앞 200자 + "[FAKE]", 네트워크·캐시 0). content가
    [{type:text}, {type:image_url}] 목록(VLM)이어도 글자 부분만. complete(agent=) 단일 턴을 직접 부르는 도구(gold_draft·
    qa_draft — c0 10-14: LLM_FAKE가 그 경로를 안 가로채 PC 연기 시험 불가)가 호출 전에 이걸로 갈음. → (글자, usage)."""

    def text_of(c):
        if isinstance(c, list):
            return "".join(p.get("text") or "" for p in c if isinstance(p, dict) and p.get("type") == "text")
        return c or ""

    last_user = next((text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    record_fake_call(sum(len(text_of(m.get("content"))) for m in messages))
    return last_user[:200] + "[FAKE]", {"prompt_tokens": 0, "completion_tokens": 0, "fake": True}


def settle_calls(extra):
    """reserve_call() 1건 예약 뒤 실제로 더 쓴 통화 수만큼 장부에 더한다(run_agent 다중 턴 정산, AG4 후속 F3) —
    extra<=0이면 아무것도 안 함(이미 예약한 1건으로 충분했던 경우)."""
    if extra <= 0:
        return
    with _lock:
        _stats["calls"] += extra


def price(model):
    """($/M 입력, $/M 출력) — env LLM_PRICE_IN·LLM_PRICE_OUT이 있으면 그 값, 없으면 PRICES[모델 이름(접두어 'z-ai/' 등 뗌)].
    모르는 모델은 (None, None) — 10-05 결함: 'z-ai/glm-5.2'를 못 찾아 0으로 보고 추정 $0·예산 상한 무력. 예산이 켜져 있으면 호출 전 거부."""
    pin, pout = cfg().models.llm.price_in, cfg().models.llm.price_out  # S7b — float|None(옛 글자 "0"도 참이었으므로 is not None)
    d = PRICES.get(model or "") or PRICES.get((model or "").split("/")[-1].split(":")[0])
    if pin is not None and pout is not None:
        return pin, pout
    if d is None:
        return None, None
    return pin if pin is not None else d["in"], pout if pout is not None else d["out"]


def _cache_path(key):
    d = Path(cfg().models.llm.cache_dir or ROOT / "output" / "eval" / "llm_cache")
    return d / key[:2] / f"{key}.json"


def cache_key(model, messages, temperature=0.0, max_tokens=1024, json_mode=False):
    parts = [model, messages, temperature, max_tokens, json_mode]
    checked("LLM_EXTRA_BODY")  # 형식 틀린 JSON은 옛 json.loads처럼 실패(S7b)
    eb = cfg().models.llm.extra_body  # S7b — 푼 JSON(dict|list|None). 옛 `if eb`(글자 "{}"도 참)와 같게 is not None
    if eb is not None:  # 생각 켬/끔이 다른 답을 서로의 캐시로 돌려주지 않게(security 리뷰 SEC-2) — 미설정이면 기존 열쇠 그대로
        parts.append(json.dumps(eb, sort_keys=True))
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _do_call(messages, temperature, max_tokens, json_mode, base, model, agent, timeout):
    """실호출 1건 — 분당 상한·예산 상한·공유 장부(_stats) 갱신까지(chat()의 비-캐시 경로 공용, RV12로 빈
    응답 재요청이 2건째를 같은 방식으로 치르도록 분리). 캐시는 호출자(chat())가 처리."""
    reserve_call()
    # 실패 출구마다 돌려준다(한 곳 — try/finally): complete()에 넘기기 전 실패면 위 자리, 성공 전 실패면 예산 선차감(reserved).
    # complete()가 시작된 뒤의 자리는 complete()가 실패할 때 스스로 돌려준다(call_reserved=True).
    from common.ai import guard as G

    reserved, handed, done = 0.0, False, False
    try:
        with _lock:
            rpm = cfg().models.llm.rpm
            if rpm:
                wait = _last[0] + 60 / rpm - time.monotonic()
                if wait > 0:
                    _span.add_current(llm_rpm_wait_ms=int(wait * 1000))  # op-01 — 분당 상한 때문에 기다린 시간
                    time.sleep(wait)
                _last[0] = time.monotonic()
        # 예산(10-05 독립 검토 반영) — 호출 전 예상 최대 비용(입력 글자/3 토큰 + max_tokens 출력)을 공유 장부에 선차감(잠금 안 확인+기록),
        # 호출 뒤 실제 사용량으로 정산 — 사용량이 없으면 예상치 그대로(보수적). 외부 호출이고 단가 미상이면 상한을 지킬 수 없어 거부.
        pin, pout = price(model)
        if not is_internal(base) and G.budget_usd() is not None:
            if pin is None:
                raise LLMUnavailable(f"모델 {model} 단가 미상 — LLM_PRICE_IN·LLM_PRICE_OUT 지정 전엔 예산 상한을 지킬 수 없어 호출 안 함")
            est = (sum(len(m.get("content") or "") for m in messages) / 3 * pin + max_tokens * pout) / 1e6
            try:
                G.spend_reserve(est, "LLM")
            except G.BudgetExceeded as e:
                raise LLMUnavailable(str(e)) from e
            reserved = est
        try:
            # preguarded=True — chat()이 이미 allow_external 인자·LLM_ALLOW_EXTERNAL 설정으로 가드를 통과시켰음(GA3).
            # call_reserved=True — 위 reserve_call()이 이 1차 호출의 자리를 이미 예약함(GH1-08d — 이중 집계 방지). 형식 재요청(AD33)의
            # 2차 호출은 complete()가 그 자리에서 reserve_call()로 직접 센다(GH1-08c) — 여기서 다시 더하지 않는다.
            handed = True
            text, u = complete(
                "llm",
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                timeout=float(timeout or cfg().models.llm.timeout),
                preguarded=True,
                agent=agent,
                call_reserved=True,
            )  # timeout: 호출별 상한(검색 경로처럼 지연 민감한 곳)
        except ModelUnavailable as ex:
            with _lock:
                _stats["errors"] += 1
            raise RuntimeError(f"LLM 호출 실패: {ex}") from ex
        done = True
    finally:
        if not done:
            _refund(not handed, reserved)  # 호출이 안 나갔거나 실패 — 자리·선차감을 돌려줌
    usd = ((u.get("prompt_tokens", 0) * pin + u.get("completion_tokens", 0) * pout) / 1e6) if (pin is not None and u) else reserved
    if reserved and u:
        G.spend_settle(usd - reserved)  # 실제로 정산(사용량 없으면 선차감액이 그대로 지출로 남음)
    with _lock:
        _stats["tokens_in"] += u.get("prompt_tokens", 0)
        _stats["tokens_out"] += u.get("completion_tokens", 0)
        _stats["spend_usd"] += usd
    return text, u


def _empty_truncated(text, u):
    """RV12 — 응답이 비었는데(공백만) 토큰을 썼다(completion_tokens>0)면 생각이 max_tokens를 다 써 답 글자가 하나도
    안 나온 것으로 본다. finish_reason을 전송 경로마다 새로 끌어오지 않고 이미 공용으로
    돌아오는 completion_tokens만으로 판정 — 토큰을 전혀 안 썼는데 빈 응답(모델이 설정 자체가 없거나 즉시 빈 글자)은
    재요청해도 같은 결과일 뿐이라 대상이 아니다."""
    return not (text or "").strip() and (u.get("completion_tokens") or 0) > 0


def chat(messages, temperature=0.0, max_tokens=1024, json_mode=False, allow_external=False, agent=None, timeout=None):
    """메시지 목록 → 응답 텍스트. 설정 없으면 LLMUnavailable. 캐시·분당 상한·예산 상한·외부 가드 적용.
    LLM_FAKE=1이면 그 무엇도 거치지 않고 네트워크 없는 모의 응답(캐시에 안 씀) — 비용 추정·preflight 전용.
    agent=dev/agents/<agent_id> — 지시문 패키지 id를 그대로 complete()에 전달(GA2, 호출부는 agent= 필수 —
    cli/check_modules.py 정적 검사). 캐시 열쇠(messages·temperature 등)는 agent와 무관 — 요청 본문만 바뀐다.
    빈 응답 안전망(RV12) — _empty_truncated()면 max_tokens×4(LLM_EMPTY_RETRY_MAX
    상한, 기본 8000)로 딱 한 번 재요청, 두 호출 다 공유 장부(_do_call)를 거쳐 예산·호출 수에 그대로 반영된다."""
    if fake_llm():
        last_user = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
        pc = sum(len(m.get("content") or "") for m in messages)
        record_fake_call(pc)
        return last_user[:200] + "[FAKE]"
    base, model = cfg().models.llm.base_url, cfg().models.llm.model
    if not (base and model):
        raise LLMUnavailable("LLM_BASE_URL·LLM_MODEL 미설정(settings.yaml required.models.llm_base_url·llm_model)")
    if not is_internal(base) and not external_ok(allow_external or cfg().models.llm.allow_external):
        why = run_env_block()
        raise LLMUnavailable(
            f"외부 LLM 주소({urllib.parse.urlparse(base).hostname}) — 회사 문서는 내부망 LLM만(DONT 13). "
            "개발 PC 합성 문서 실험이면 LLM_ALLOW_EXTERNAL=1(RUN_ENV=local)" + (f" ({why})" if why else "")
        )
    key = cache_key(model, messages, temperature, max_tokens, json_mode)
    cp = _cache_path(key)
    if cp.exists():
        with _lock:
            _stats["cache_hits"] += 1
        _span.add_current(llm_cache_hit=1)  # op-01 — 열린 span(문서×단계)에 응답 캐시 적중 수
        return json.loads(cp.read_text(encoding="utf-8"))["text"]
    text, u = _do_call(messages, temperature, max_tokens, json_mode, base, model, agent, timeout)
    if _empty_truncated(text, u):
        retry_tokens = min(max_tokens * 4, cfg().models.llm.empty_retry_max)
        if retry_tokens > max_tokens:
            text, u = _do_call(messages, temperature, retry_tokens, json_mode, base, model, agent, timeout)
    if u.get("schema_failed") or not (text or "").strip():  # 형식 재요청도 틀림(AD33) 또는 빈 응답(재요청 뒤에도) —
        return text  # 캐시에 고착시키지 않음(10-09 재순위 실측: 빈 응답이 캐시에서 계속 재생됨)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"text": text, "usage": u}, ensure_ascii=False), encoding="utf-8")
    return text


def parse_json(text):
    """응답에서 JSON 객체 하나 — 코드펜스·앞뒤 설명이 붙어도."""
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("JSON 없음")
    return json.loads(t[i : j + 1])


# ── 모델 호출(0.2.0 — 옛 common/ai/adk.py의 ADK·litellm 장치를 지우고 OpenAI 호환 HTTP 한 길로, pl-46) ──────────────────
# complete(role, messages) — 역할(llm·vlm) 하나에 단일 턴 1건. 가드(require_internal·precheck — 매 호출 URL을 그 자리에서 다시 확인)·
# 재시도(429·5xx·연결·타임아웃만, 마지막 실패 뒤 대기 없음, Retry-After 존중)·base_url별 "모델 다운" 회로 차단기(RV24)·
# 공유 호출 장부(호출 수 — GH1-08d)·agent=의 출력 형식 1회 재요청(AD33 ⓑ, 패키지 agent.json output_schema)·직접 호출자의
# 빈 응답 1회 재요청(RV16)·LLM_EXTRA_BODY/VLM_EXTRA_BODY 병합(RV12)은 옛 adk.complete와 같은 규칙이다. 지시문 패키지(resources/prompts/…)는
# 그대로 — 글자는 common.ai.agent_prompts가 읽고, 여기서는 agent.json의 model_role·output_schema만 본다.
# tools=를 주면(OpenAI 함수 도구 목록) 응답 message 사전을 그대로 돌려준다 — PC 답변 점검의 도구 왕복(validation/e2e/tool_loop.py)만 쓴다.
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from common.ai.guard import BudgetExceeded as _BudgetExceeded  # noqa: E402
from common.ai.guard import open_guarded as _g_open  # noqa: E402 — precheck는 complete()가 한 번만
from common.ai.guard import precheck  # noqa: E402
from common.core.paths import resolve_agent_dir  # noqa: E402

_ROLE_GUARD_PREFIX = {"llm": "LLM", "vlm": "VLM"}


class ModelUnavailable(RuntimeError):
    pass


class GuardBlocked(ModelUnavailable, _BudgetExceeded):
    """가드가 호출을 막음(외부 주소 거부·예산) — 호출은 안 나감. ModelUnavailable이기도 해서 '모델 없음'처럼
    그 단계만 건너뛰는 호출부(그림·쪽 VLM 등)가 파싱을 멈추지 않음. BudgetExceeded를 기대하는 호출부도 그대로 잡힘."""


class _Retryable(RuntimeError):
    def __init__(self, inner, retry_after=None):
        super().__init__(str(inner))
        self.inner = inner
        self.retry_after = retry_after


def _prof_key(prof):
    """모델 프로필 key_env가 가리키는 API 키 글자(없으면 None). 값은 출력·로그 안 함."""
    return reveal(by_env(prof.key_env)) if prof.key_env else None


# RV24 — base_url별 공유 "모델 다운" 회로 차단기: 연결·타임아웃 실패가 연속 MODEL_DOWN_AFTER회면 MODEL_DOWN_COOLDOWN초 동안 즉시 거부.
_model_down_lock = threading.Lock()
_model_down_state: dict = {}


def _model_down(base_url):
    """True면 쿨다운 중. ponytail: 쿨다운이 끝나면 바로 전부 다시 허용(half-open 확인 호출 없음) — 워커가 많아지면 추가."""
    with _model_down_lock:
        st = _model_down_state.get(base_url)
        return bool(st and st["until"] is not None and time.monotonic() < st["until"])


def _model_down_mark_failure(base_url):
    after = cfg().models.transport.down_after
    if after <= 0:  # MODEL_DOWN_AFTER=0 — 끔
        return
    with _model_down_lock:
        st = _model_down_state.setdefault(base_url, {"fails": 0, "until": None})
        st["fails"] += 1
        if st["fails"] >= after:
            st["until"] = time.monotonic() + cfg().models.transport.down_cooldown


def _model_down_reset(base_url):
    with _model_down_lock:
        _model_down_state.pop(base_url, None)


# AD33 ⓑ — 출력 형식 검사·1회 재요청(output_schema가 있는 패키지만). 그래도 안 맞으면 그대로 돌려줘 호출부 기본값 처리에 맡김.
_SCHEMA_RETRY_NOTE = "앞 응답이 형식에 맞지 않았다 — 스키마에 맞는 JSON 하나만"
_schema_stats = {"invalid": 0, "retry_ok": 0, "retry_failed": 0}


def _bump_schema_stat(key):
    with _lock:
        _schema_stats[key] += 1


def schema_stats():
    """invalid: 1차 응답이 output_schema에 안 맞아 재요청한 수 · retry_ok·retry_failed: 재요청 결과(AD33 ⓑ)."""
    with _lock:
        return dict(_schema_stats)


def _schema_ok(text, schema):
    try:
        data = parse_json(text or "")
    except ValueError:
        return False
    import jsonschema

    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False


def _append_retry_note(messages, note):
    """원 messages는 두고 마지막 메시지에 안내 한 줄을 덧붙인 새 목록(글·이미지 content 둘 다)."""
    new = [dict(m) for m in messages]
    last = dict(new[-1])
    content = last.get("content")
    last["content"] = (content + "\n\n" + note) if isinstance(content, str) else list(content) + [{"type": "text", "text": note}]
    new[-1] = last
    return new


_EXTRA_ENV_KEY = {"llm": "LLM_EXTRA_BODY", "vlm": "VLM_EXTRA_BODY"}
_EXTRA_RESERVED = {"model", "messages", "max_tokens", "max_completion_tokens", "stream"}


def _env_extra_body(role):
    """LLM_EXTRA_BODY·VLM_EXTRA_BODY(RV12 — 생각 끄기 등) — 역할별. 모델·메시지·한도·스트림 키는 거부(코드가 정함)."""
    import copy

    key = _EXTRA_ENV_KEY.get(role)
    if not key:
        return None
    checked(key)  # 형식 틀린 JSON은 실패(조용히 빼고 보내지 않게)
    body = cfg().models.llm.extra_body if key == "LLM_EXTRA_BODY" else cfg().models.vlm.extra_body
    if body is None:
        return None
    body = copy.deepcopy(body)
    bad = sorted(set(body) & _EXTRA_RESERVED)
    if bad:
        raise ValueError(f"{key}에 넣을 수 없는 키: {bad}")
    return body


def _merged_extra(role, extra):
    """호출자 extra가 env 기본값의 같은 키를 덮어씀."""
    env_extra = _env_extra_body(role)
    return {**env_extra, **(extra or {})} if env_extra else extra


@functools.cache
def _manifest(agent_id):
    """지시문 패키지 agent.json(그대로 — 글자는 agent_prompts가 읽음) → model_role·output_schema 등 사전."""
    return json.loads((resolve_agent_dir(agent_id) / "agent.json").read_text(encoding="utf-8"))


def _post_chat(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix, tools=None):
    """/chat/completions 1건 → (message 사전, usage). 429·5xx·연결·타임아웃은 _Retryable(바깥 루프가 재시도)."""
    body = {"model": prof.model.removeprefix("openai/"), "temperature": temperature, "messages": messages}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    body.update(extra or {})
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    key = _prof_key(prof)
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(prof.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    try:
        with _g_open(req, timeout, guard_prefix) as r:
            data = json.load(r)
    except urllib.error.HTTPError as ex:
        if ex.code in (429, 500, 502, 503, 504):
            ra = ex.headers.get("Retry-After") if ex.headers else None
            raise _Retryable(ex, retry_after=float(ra) if ra else None) from ex
        raise ModelUnavailable(f"모델 호출 실패: HTTPError {ex.code}: {str(ex)[:200]}") from ex
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        raise _Retryable(ex) from ex
    except RuntimeError as ex:  # 리다이렉트 가드 거부 등(guard._Redirect) — 재시도 대상 아님, '모델 없음'처럼 건너뛰게
        raise GuardBlocked(str(ex)) from ex
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    u = data.get("usage") or {}
    return msg, {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0)}


def _once(agent, role, prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix):
    """1건 + agent=면 출력 형식 1회 재요청(AD33 ⓑ — 재요청도 공유 장부를 원자적으로 거침, GH1-08c·08e)."""
    msg, usage = _post_chat(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix)
    text = msg.get("content") or ""
    schema = _manifest(agent).get("output_schema") if agent else None
    if schema is None or _schema_ok(text, schema):
        return text, usage
    _bump_schema_stat("invalid")
    first = usage or {}
    reserve_call()
    try:
        msg, usage = _post_chat(
            prof, _append_retry_note(messages, _SCHEMA_RETRY_NOTE), temperature, max_tokens, json_mode, extra, timeout, guard_prefix
        )
    except _Retryable:
        release_call()  # 못 쓴 재요청 슬롯을 돌려주고 바깥 재시도 루프에 맡김(GH1-08e)
        raise
    text = msg.get("content") or ""
    ok = _schema_ok(text, schema)
    _bump_schema_stat("retry_ok" if ok else "retry_failed")
    usage = dict(usage or {})
    for k in ("prompt_tokens", "completion_tokens"):
        usage[k] = (first.get(k) or 0) + (usage.get(k) or 0)
    usage["calls"] = 2
    if not ok:
        usage["schema_failed"] = True
    return text, usage


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
    tools=None,
):
    """역할(llm·vlm) → (응답 글자, usage) — tools=를 주면 (응답 message 사전, usage). 위 섹션 설명의 규칙 그대로.
    preguarded=True는 chat()만(allow_external 인자·LLM_ALLOW_EXTERNAL 설정으로 이미 가드를 통과) — 그 밖은 매번 require_internal.
    agent=(지시문 패키지 id)면 model_role이 role과 같아야 하고, 아직 예약 안 됐으면(call_reserved=False — 직접 호출자) 1차 호출을
    재시도 루프 전에 딱 한 번 공유 장부에 예약한다(GH1-08d). call_reserved=True는 호출자가 이미 예약한 경우(chat()의 _do_call).
    max_tokens=None이면 그 필드를 안 보냄."""
    # 실패 출구마다 자리·선차감을 돌려준다(한 곳 — try/finally): 성공(ok=True)이면 그대로 쓰고, 그 밖의 모든 출구(가드 거부·설정 없음·
    # 재시도 소진·_Retryable 아닌 예외)에서 call_reserved 자리(chat()의 _do_call이 예약했거나 아래 direct가 예약)와 flat 선차감(reserved)을 되돌림.
    ok, reserved = False, 0.0
    try:
        prof = profile(role)
        if prof is None:
            raise ModelUnavailable(f"{role.upper()}_BASE_URL·{role.upper()}_MODEL 미설정")
        if agent is not None:
            mr = _manifest(agent).get("model_role")
            if mr != role:
                raise ModelUnavailable(f"{agent}: model_role={mr!r} != 호출 role={role!r}")
        guard_prefix = _ROLE_GUARD_PREFIX[role]
        if _model_down(prof.base_url):
            host = urllib.parse.urlparse(prof.base_url).hostname or prof.base_url
            raise ModelUnavailable(
                f"모델 다운({role}_down) — {host} 연속 {cfg().models.transport.down_after}회 이상 실패, 쿨다운 중(MODEL_DOWN_COOLDOWN) — 호출 안 보냄"
            )
        try:
            if not preguarded:
                require_internal(prof.base_url, guard_prefix)
            reserved = precheck(prof.base_url, guard_prefix)  # role!=llm 외부 호출의 flat 선차감액(내부망·llm이면 0.0)
        except GuardBlocked:
            raise
        except RuntimeError as ex:  # 외부 주소·BudgetExceeded — 호출 전에 막힘
            raise GuardBlocked(str(ex)) from ex
        extra = _merged_extra(role, extra)
        deadline = float(timeout) if timeout else 120.0
        direct = agent is not None and not call_reserved  # RV16·GH1-08d — chat()은 call_reserved=True(자기 안전망을 따로 가짐)
        if direct:
            reserve_call()
            call_reserved = True
        last_err, last_elapsed = None, None
        for attempt in range(retries):
            t0 = time.monotonic()
            try:
                if tools:
                    out, u = _post_chat(prof, messages, temperature, max_tokens, json_mode, extra, deadline, guard_prefix, tools=tools)
                else:
                    out, u = _once(agent, role, prof, messages, temperature, max_tokens, json_mode, extra, deadline, guard_prefix)
                    if direct and _empty_truncated(out, u):  # RV16 — 생각이 max_tokens를 다 써 빈 응답 → 4배로 딱 한 번
                        cap = cfg().models.llm.empty_retry_max
                        retry_tokens = cap if max_tokens is None else min(max_tokens * 4, cap)
                        if retry_tokens > (max_tokens or 0):
                            reserve_call()
                            first = dict(u)
                            try:
                                out, u = _once(
                                    agent, role, prof, messages, temperature, retry_tokens, json_mode, extra, deadline, guard_prefix
                                )
                            except BaseException:
                                release_call()  # 2차(빈 응답 재요청) 자리 — 1차 자리는 아래 finally가
                                raise
                            u = dict(u or {})
                            for k in ("prompt_tokens", "completion_tokens"):
                                u[k] = (first.get(k) or 0) + (u.get(k) or 0)
                            u["calls"] = 2
                ok = True
                if reserved:  # 실제 토큰 usage로 사후 정산(BR45)
                    from common.ai import guard as G

                    G.settle_tokens(reserved, prof.model, u)
                _model_down_reset(prof.base_url)
                return out, u
            except _Retryable as ex:
                last_err, last_elapsed = ex.inner, time.monotonic() - t0
                _span.add_current(**{f"{role}_retries": 1})  # op-01 — 열린 span(문서×단계)에 재시도 수(span 없으면 no-op)
                if attempt < retries - 1:
                    time.sleep(ex.retry_after if ex.retry_after else 2**attempt * 2)
        # 빨리 끝난 실패(연결 자체가 안 됨)만 회로 실패로 센다 — 느린 응답(살아있지만 느림)은 안 셈(RV24 BLOCK)
        if last_elapsed is not None and last_elapsed <= min(cfg().models.transport.connect_timeout * 1.5, deadline * 0.5):
            _model_down_mark_failure(prof.base_url)
        raise ModelUnavailable(f"모델 호출 실패(재시도 {retries}회): {type(last_err).__name__}: {str(last_err)[:200]}") from last_err
    finally:
        if not ok:
            _refund(call_reserved, reserved)  # 끝내 못 쓴 자리·flat 선차감을 되돌림(BR45 후속)


def _refund(slot, usd):
    """실패한 호출이 쥔 것을 돌려준다 — slot이면 호출 수 1건, usd면 예산 선차감(_do_call·complete 공용, 리뷰 11-03)."""
    if slot:
        release_call()
    if usd:
        from common.ai import guard as G

        G.spend_settle(-usd)


def _traced(fn):
    """op-01 — 열린 span(문서×단계)이 있으면 모델 호출 수·지연·토큰·실패를 그 span의 metrics에 쌓는다(개별 호출 기록은 DEBUG만).
    span이 없으면(MCP 검색 등) 원래 함수를 그대로 부른다."""

    @functools.wraps(fn)
    def wrapper(role, messages, **kwargs):
        sp = _span.current()
        if sp is None:
            return fn(role, messages, **kwargs)
        t0 = time.monotonic()
        try:
            text, usage = fn(role, messages, **kwargs)
        except Exception as ex:
            ms = (time.monotonic() - t0) * 1000
            sp.add(**{f"{role}_calls": 1, f"{role}_fail": 1}).observe(f"{role}_ms", ms).ext_call(ms)
            _span.call_event(f"model.{role}", ms, ex)
            raise
        ms = (time.monotonic() - t0) * 1000
        sp.add(**{f"{role}_calls": 1}).observe(f"{role}_ms", ms).ext_call(ms)
        usage = usage or {}
        _span.call_event(f"model.{role}", ms, None, tok_in=usage.get("prompt_tokens"), tok_out=usage.get("completion_tokens"))
        sp.add(**{f"{role}_tok_in": usage.get("prompt_tokens") or 0, f"{role}_tok_out": usage.get("completion_tokens") or 0})
        _span.debug_event(
            f"model.{role}", role=role, ms=round(ms), tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens")
        )
        return text, usage

    return wrapper


complete = _traced(complete)


class _Turn:
    """admit_turn()의 턴 하나 — 통과했으면 응답 usage로 settle(), 응답을 못 받았으면 release()(선차감 반환 — 옛 GA9)."""

    def __init__(self, model, usd):
        self.model, self.usd = model, usd

    def settle(self, usage):
        """응답 usage를 role=llm 단가(price — LLM_PRICE_IN·OUT 포함)로 계산해 차이를 정산(리뷰 11-03 — 옛 settle_tokens는 PRICES 표만 봐
        표에 없는 모델은 고정 추정액에 머묾). 한 턴이 상한을 넘을 수는 있다(사후 정산) — 다음 턴의 admit_turn이 거부."""
        if self.usd and usage:
            from common.ai import guard as G

            pin, pout = price(self.model)
            if pin is not None and pout is not None:
                G.spend_settle((usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout) / 1e6 - self.usd)

    def release(self):
        if self.usd:
            from common.ai import guard as G

            G.release_reserve(self.usd)


def admit_turn(role="llm"):
    """여러 턴 도구 왕복의 턴 하나 장부(옛 run_agent per_turn_admit) — 호출 수 세기 + 외부 주소면 고정 추정액(LLM_EST_USD) 선차감.
    → _Turn(통과) 또는 None(장부 거부 — 예산). 통과하면 이 턴 호출은 complete(call_reserved=True)로."""
    from common.ai import guard as G

    prof = profile(role)
    budget = G.budget_usd() if prof is not None and not is_internal(prof.base_url) else None  # 예산 읽기(형식 오류)는 세기 앞에서
    if budget is not None and price(prof.model)[0] is None:  # _do_call과 같은 규칙 — 단가를 모르면 하루 상한을 지킬 수 없음
        raise LLMUnavailable(f"모델 {prof.model} 단가 미상 — LLM_PRICE_IN·LLM_PRICE_OUT 지정 전엔 예산 상한을 지킬 수 없어 호출 안 함")
    reserve_call()
    if budget is None:
        return _Turn(prof.model if prof else "", 0.0)
    usd = cfg().models.llm.est_usd
    try:
        G.spend_reserve(usd, "LLM")
    except G.BudgetExceeded:
        release_call()
        return None
    return _Turn(prof.model, usd)
