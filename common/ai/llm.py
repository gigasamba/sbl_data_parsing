"""LLM 공통 클라이언트 — OpenAI 호환 /chat/completions (서버 GLM-5.2 · 나중에 Gemini OpenAI 호환 주소 · 개발 PC 모의 서버).

설정(.env): LLM_BASE_URL(…/v1) · LLM_MODEL · LLM_API_KEY(있을 때만) · LLM_TIMEOUT(초, 기본 120) · LLM_RPM(분당 호출 상한, 기본 0=무제한)
          · LLM_MAX_CALLS(이번 프로세스 호출 상한, 기본 0=무제한 — 무료 등급 토큰 보호) · LLM_CACHE_DIR(기본 output/eval/llm_cache)
          · LLM_BUDGET_USD(이번 프로세스 추정 지출 상한 — 넘으면 이후 호출을 보내기 전에 거부) · LLM_PRICE_IN·LLM_PRICE_OUT($/M 토큰, 기본 PRICES[모델])
- **응답 캐시**: (모델, 메시지, 온도) 해시가 같으면 다시 부르지 않는다 — 재실행·다른 조합이 같은 질문을 해도 토큰 0.
- **비용 관문(2026-10, OpenRouter 85% 소진 이후)**: LLM_FAKE=1이면 네트워크 호출 없이 모의 응답(마지막 user 메시지 앞 200자+"[FAKE]") —
  캐시에 안 쓰고 usage()에 fake_calls·prompt_chars만 쌈(추정기가 이걸로 호출 수·글자 수를 모음). 실호출은 LLM_BUDGET_USD로 상한.
- **외부 전송 가드(DONT 13, 여기 한 곳에서 강제)**: LLM_BASE_URL이 내부 주소(사설 IP·localhost·.local/.internal/.corp·단일 이름)가 아니면
  `allow_external=True` **그리고** RUN_ENV=local일 때만 호출한다(서버 dev·stage·prd는 외부 호출 불가).
- 호출·토큰 수는 usage()로 — 도구가 결과 파일에 함께 남긴다.
- **빈 응답 안전망(RV12, 2026-10-09 재순위 실측 — glm-5.2가 생각에 max_tokens를 다 써 ~45% 빈 응답)**: 응답이 비어 있고(공백만
  포함) 토큰을 썼다면(completion_tokens>0 — 생각이 출력 상한을 다 썼다는 신호, finish_reason을 3개 전송 경로 모두에서
  따로 끌어오지 않고 이미 있는 값으로 판정) `max_tokens`를 4배(`LLM_EMPTY_RETRY_MAX` 상한, 기본 8000)로 올려 **딱 한 번**
  재요청한다 — `LLM_EMPTY_RETRY=0`으로 끔(기본 켬). 재요청도 공유 장부(LLM_BUDGET_USD·LLM_MAX_CALLS)를 그대로 거친다.
  빈 응답(재요청 뒤에도 빈 경우 포함)은 캐시에 쓰지 않는다 — 전에는 빈 응답이 캐시에 고착돼 다음 호출도 계속 빈 응답을 받았음.
- **생각 끄기(RV12)**: env `LLM_EXTRA_BODY`(JSON 객체)가 OpenRouter·vLLM 요청 본문에 그대로 섞여 들어간다 — 실제 머지는
  `common/adk.py complete()`(VLM도 `VLM_EXTRA_BODY`로 같은 메커니즘, 역할별 분리) 한 곳.
"""

import dataclasses
import hashlib
import json
import threading
import time
import urllib.parse
from pathlib import Path

from common.config.settings import by_env, cfg, checked, reveal
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


from common.ai.guard import external_ok, is_internal, require_internal, run_env_block  # noqa: E402,F401 — 내부망 확인은 common 한 곳

# CT1(10-16) — models.py 병합(역할별 모델 프로필 조회, agent_platform.config.ModelProfile 재사용 — 사용자 결정 2026-10-06).
# 설정 객체에서만 읽음(S7b — 호출 시점 cfg(), 전환 기간엔 env로 만든 객체라 테스트가 env를 바꾸면 반영). 기존 LLM_BASE_URL·VLM_BASE_URL·VLM_MODEL_ALT·EMBED_* 등은 그대로 하위 호환.
_ROLE_PREFIX = {"llm": "LLM", "vlm": "VLM", "ocrvlm": "OCRVLM", "embed": "EMBED"}


@dataclasses.dataclass(frozen=True)
class ModelProfile:
    """대체 구현(10-26): 옛 agent_platform.config.ModelProfile(pydantic)과 같은 칸·같은 검사 — TODO 해결 전 임시.
    classification은 선언일 뿐 가드에 쓰지 않는다(adk.py가 매 호출 URL을 다시 확인)."""

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
    """역할 → ModelProfile. vlm_judge는 VLM_MODEL_ALT가 있으면 그 모델, 주소·키는 VLM_*
    (AD22 전제 — 지금은 judge용 다른 VLM 서버를 못 씀, 없으면 VLM_MODEL과 같음).
    agent_platform import는 여기서 늦게(지연) — structure·retrieval 이미지는 agent_platform 없이도 이 모듈을
    import할 수 있어야 한다(profile()을 실제로 부르는 경로만 agent_platform이 필요, MOD 10-14)."""
    # TODO: 리팩토링 후 구현 필요
    # try:
    #     from agent_platform.config import ModelProfile
    # except ImportError as e:
    #     raise ImportError(
    #         f"agent_platform(저장소 루트 deploy/agent_platform)을 못 찾음 — dev/와 deploy/가 같은 저장소 루트의 형제 폴더여야 함: {e}"
    #     ) from e
    if role == "vlm_judge":
        prefix = "VLM"
        v = cfg().models.vlm
        base, model, key = v.base_url, v.model_alt or v.model, reveal(v.api_key)
    else:
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


def _max_calls():
    """LLM_MAX_CALLS(0 = 무제한) — 형식이 틀리면 옛 int() 오류처럼 ValueError(이름만, S7b). 읽는 곳은 모두 이것으로(VS7b R-5)."""
    checked("LLM_MAX_CALLS")
    return cfg().models.guard.max_calls


def reserve_call():
    """LLM_MAX_CALLS 공유 집계(AG4) — chat()과 dev/common/adk.py run_agent() 둘 다 같은 _stats["calls"] 장부·같은 상한을
    쓴다(한쪽만 호출해도 다른 쪽의 남은 예산이 줄어듦). cap 도달이면 LLMUnavailable(실제로 세지 않음)."""
    with _lock:
        cap = _max_calls()
        if cap and _stats["calls"] >= cap:
            raise LLMUnavailable(f"LLM_MAX_CALLS={cap} 도달 — 캐시에 없는 요청은 더 보내지 않음")
        _stats["calls"] += 1


def try_reserve_call():
    """GH1-08c — reserve_call()과 같은 확인+예약을 **같은 잠금 한 번**으로(원자적): remaining_calls()로 읽고 나중에
    reserve_call()하면 그 사이에 다른 스레드가 끼어들 수 있다(run_all --procs 동시 재요청이 상한을 넘김, 실측).
    cap 도달이면 예외 대신 False(예약 안 됨) — 호출자가 그 자리에서 거부 처리(네트워크 요청 없이)."""
    with _lock:
        cap = _max_calls()
        if cap and _stats["calls"] >= cap:
            return False
        _stats["calls"] += 1
        return True


def release_call():
    """GH1-08e — try_reserve_call()로 예약한 자리를 같은 잠금 안에서 돌려준다. _complete_agent의 스키마 재요청이
    429/5xx/연결 오류로 끝까지 못 가면(_Retryable) adk.complete()의 전송 재시도 루프가 _complete_agent를 처음부터
    다시 돌리는데, 그때 재요청이 다시 try_reserve_call()을 불러 같은 논리적 1회 재요청이 슬롯 2개를 먹는다(독립
    검토 CONCERN) — 실패한 재요청을 여기로 반환해 둔 뒤 다시 돌면 슬롯 1개만 쓴다. calls가 이미 0이면 더 깎지
    않음(음수 방지 — try_reserve_call() 호출 없이 잘못 불려도 장부가 깨지지 않게).
    가정(독립 검토 10-12): 실패한 재요청은 과금되지 않았다고 본다. 요청은 갔는데 응답만 잃은 시간 초과·일부 5xx는
    실제로 과금됐을 수 있어 그때는 LLM_MAX_CALLS를 1 적게 센다(위험한 쪽, 드묾) — complete() 바깥 재시도가 1차 호출을
    다시 예약하지 않는 기존 관례와 같은 가정. 금액 상한은 guard.py(LLM_BUDGET_USD)가 따로 지킨다."""
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
    [{type:text}, {type:image_url}] 목록(VLM)이어도 글자 부분만. adk.complete(agent=) 단일 턴을 직접 부르는 도구(gold_draft·
    qa_draft — c0 10-14: LLM_FAKE가 그 경로를 안 가로채 PC 연기 시험 불가)가 호출 전에 이걸로 갈음. → (글자, usage)."""

    def text_of(c):
        if isinstance(c, list):
            return "".join(p.get("text") or "" for p in c if isinstance(p, dict) and p.get("type") == "text")
        return c or ""

    last_user = next((text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    record_fake_call(sum(len(text_of(m.get("content"))) for m in messages))
    return last_user[:200] + "[FAKE]", {"prompt_tokens": 0, "completion_tokens": 0, "fake": True}


def remaining_calls():
    """LLM_MAX_CALLS 남은 수(AG4 후속 F3) — None이면 무제한(LLM_MAX_CALLS 미설정). run_agent()가 reserve_call()로
    1건을 예약한 **뒤**에 불러 "그 1건 포함 지금부터 몇 건을 더 쓸 수 있는지"를 run_agentic의 max_turns 상한에
    반영한다 — 다중 턴 1회 실행이 실제로는 여러 번 모델을 불러도 공유 장부의 남은 수를 넘지 않게."""
    with _lock:
        cap = _max_calls()
        return None if not cap else max(0, cap - _stats["calls"])


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
    """실호출 1건 — 호출 상한·분당 상한·예산 상한·공유 장부(_stats) 갱신까지(chat()의 비-캐시 경로 공용, RV12로 빈
    응답 재요청이 2건째를 같은 방식으로 치르도록 분리). 캐시는 호출자(chat())가 처리."""
    reserve_call()
    with _lock:
        rpm = cfg().models.llm.rpm
        if rpm:
            wait = _last[0] + 60 / rpm - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.monotonic()
    # 예산(10-05 독립 검토 반영) — 호출 전 예상 최대 비용(입력 글자/3 토큰 + max_tokens 출력)을 공유 장부에 선차감(잠금 안 확인+기록),
    # 호출 뒤 실제 사용량으로 정산 — 사용량이 없으면 예상치 그대로(보수적). 외부 호출이고 단가 미상이면 상한을 지킬 수 없어 거부.
    from common.ai import guard as G

    reserved = 0.0
    pin, pout = price(model)
    if not is_internal(base) and G.budget_usd() is not None:
        if pin is None:
            raise LLMUnavailable(f"모델 {model} 단가 미상 — LLM_PRICE_IN·LLM_PRICE_OUT 지정 전엔 예산 상한을 지킬 수 없어 호출 안 함")
        reserved = (sum(len(m.get("content") or "") for m in messages) / 3 * pin + max_tokens * pout) / 1e6
        try:
            G.spend_reserve(reserved, "LLM")
        except G.BudgetExceeded as e:
            raise LLMUnavailable(str(e)) from e
    from common.ai import adk as A

    try:
        # preguarded=True — 호출자(chat())가 이미 자기 allow_external 매개변수로 가드를 통과시켰음
        # (adk.complete의 기본 가드는 env 기반이라 run_answers·wiki_draft의 매개변수 기반 허용과 충돌 — GA3).
        # call_reserved=True — 위 reserve_call()이 이 1차 호출의 자리를 이미 예약함(GH1-08d): adk.complete()의
        # agent= 경로가 1차 호출을 다시 예약하면 이중 집계가 되므로(그 책임은 여기 reserve_call() 한 곳). 형식
        # 재요청(AD33)으로 2차 호출이 더 나가도, 그 호출은 adk._complete_agent가 그 자리에서
        # common/llm.try_reserve_call()로 직접 예약·집계한다(GH1-08c — 원자적 확인+예약) — 그래서 여기선
        # u.get("calls")로 다시 더하지 않는다(예전엔 이 reconciliation이 2차 호출을 집계하는 유일한 통로였지만,
        # 이제 _complete_agent가 자기 몫을 직접 예약하므로 여기서 또 더하면 이중 집계가 된다).
        text, u = A.complete(
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
    except A.ModelUnavailable as ex:
        with _lock:
            _stats["errors"] += 1
        raise RuntimeError(f"LLM 호출 실패: {ex}") from ex
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
    안 나온 것으로 본다. finish_reason을 3개 전송 경로(http·adk 직접·agent=) 각각에서 새로 끌어오지 않고 이미 공용으로
    돌아오는 completion_tokens만으로 판정 — 토큰을 전혀 안 썼는데 빈 응답(모델이 설정 자체가 없거나 즉시 빈 글자)은
    재요청해도 같은 결과일 뿐이라 대상이 아니다."""
    return not (text or "").strip() and (u.get("completion_tokens") or 0) > 0


def chat(messages, temperature=0.0, max_tokens=1024, json_mode=False, allow_external=False, agent=None, timeout=None):
    """메시지 목록 → 응답 텍스트. 설정 없으면 LLMUnavailable. 캐시·호출 상한·분당 상한·예산 상한·외부 가드 적용.
    LLM_FAKE=1이면 그 무엇도 거치지 않고 네트워크 없는 모의 응답(캐시에 안 씀) — 비용 추정·preflight 전용.
    agent=dev/agents/<agent_id> — gamma 에이전트 패키지 경유로 그대로 adk.complete에 전달(GA2, 호출부는 agent= 필수 —
    cli/check_modules.py 정적 검사). 캐시 열쇠(messages·temperature 등)는 agent와 무관 — 요청 본문만 바뀐다.
    빈 응답 안전망(RV12, 기본 켬·LLM_EMPTY_RETRY=0으로 끔) — _empty_truncated()면 max_tokens×4(LLM_EMPTY_RETRY_MAX
    상한, 기본 8000)로 딱 한 번 재요청, 두 호출 다 공유 장부(_do_call)를 거쳐 예산·호출 수에 그대로 반영된다."""
    if cfg().dev.llm_fake:
        last_user = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
        pc = sum(len(m.get("content") or "") for m in messages)
        record_fake_call(pc)
        return last_user[:200] + "[FAKE]"
    base, model = cfg().models.llm.base_url, cfg().models.llm.model
    if not (base and model):
        raise LLMUnavailable("LLM_BASE_URL·LLM_MODEL 미설정(.env)")
    if not is_internal(base) and not external_ok(allow_external):
        why = run_env_block()
        raise LLMUnavailable(
            f"외부 LLM 주소({urllib.parse.urlparse(base).hostname}) — 회사 문서는 내부망 LLM만(DONT 13). "
            "개발 PC 가상 문서 실험이면 도구의 --allow-external" + (f" ({why})" if why else "")
        )
    key = cache_key(model, messages, temperature, max_tokens, json_mode)
    cp = _cache_path(key)
    if cp.exists():
        with _lock:
            _stats["cache_hits"] += 1
        return json.loads(cp.read_text(encoding="utf-8"))["text"]
    text, u = _do_call(messages, temperature, max_tokens, json_mode, base, model, agent, timeout)
    if cfg().models.llm.empty_retry and _empty_truncated(text, u):
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
