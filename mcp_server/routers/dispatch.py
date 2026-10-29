"""도구 실행 창구 — 스레드 실행·동시 상한(MCP_MAX_CONCURRENCY)·대기열 상한(MCP_MAX_QUEUE)·요청 시간 상한(MCP_TOOL_TIMEOUT_SEC).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로.
"""

from functools import partial

import anyio

from mcp_server import config as mc  # 설정 객체(S7d — 요청마다 읽는 값은 호출 때 cfg())

_LIMITER = None


def _limiter():
    """동시 도구 실행 상한(MCP_MAX_CONCURRENCY, 기본 8 — LLM_MAX_CONCURRENCY·VLM_MAX_CONCURRENCY와 같은 기본값)."""
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = anyio.CapacityLimiter(int(mc.cfg().server.max_concurrency))  # 기본 8(모델) — 한 번 만들어 둠
    return _LIMITER


def _queue_cap(limiter):
    """대기열 상한(MCP_MAX_QUEUE — 요청마다 읽음, 없으면 동시 상한×4, "0"은 0=무제한 — `or`로 쓰면 0이 ×4로 바뀜)."""
    v = mc.cfg().server.max_queue
    return int(v) if v is not None else limiter.total_tokens * 4


_INFLIGHT = 0  # MC2(RV2) — _bg가 받아들인(실행 중+대기 중) 요청 수. 체크→증가 사이에 await가 없어


async def _bg(fn, *a, **kw):
    """동기 도구 함수를 이벤트 루프 밖 스레드로 돌림(S12) — 느린 도구 하나가 /health·다른 요청을 막지 않게.
    MC2(RV2) 과부하 보호, 기본 켬: 동시 상한(MCP_MAX_CONCURRENCY)만큼 돌고 있는 것 + 그 뒤로 밀린 대기가
    대기열 상한(MCP_MAX_QUEUE, 기본 동시 상한×4, =0이면 무제한)까지 차 있으면 **기다리지 않고** 바로
    {"error": "busy"} — 꽉 찼을 때 요청이 무한정 쌓여 죽는 대신 호출자가 바로 알고 재시도하게.
    받아들여진 요청은 시간 상한(MCP_TOOL_TIMEOUT_SEC, 기본 30초, =0이면 무제한) 안에 끝나야 하며 넘으면
    {"error": "timeout"}(실행 중인 스레드 자체는 못 끊어 뒤에서 마칠 때까지 자리를 비우지 않음 —
    ponytail: 완전한 강제 종료는 아님, 반복 타임아웃이 쌓이면 MCP_MAX_CONCURRENCY를 올리거나 도구를 손봄).
    호출자별 동시 상한은 안 둠 — MCP_TOKEN이 서버 전체에 하나뿐이라 X-MCP-Client 머리글(자기 신고값,
    검증 없음)로 자원을 나누면 신뢰 경계가 아닌 값으로 과설계만 늘어남."""
    global _INFLIGHT
    limiter = _limiter()
    queue_cap = _queue_cap(limiter)
    budget = limiter.total_tokens + queue_cap if queue_cap else None
    if budget is not None and _INFLIGHT >= budget:
        return {"error": "busy"}
    timeout = float(mc.cfg().server.tool_timeout_sec)  # 기본 30(모델) — 요청마다
    call = partial(fn, *a, **kw)
    _INFLIGHT += 1
    try:
        if not timeout:
            return await anyio.to_thread.run_sync(call, limiter=limiter)
        try:
            with anyio.fail_after(timeout):
                return await anyio.to_thread.run_sync(call, limiter=limiter, abandon_on_cancel=True)
        except TimeoutError:
            return {"error": "timeout"}
    finally:
        _INFLIGHT -= 1


async def _bg_img(fn, *a, **kw):
    """get_image·get_evidence_image는 (meta, png) 튜플을 돌려줌 — _bg가 과부하로 {"error": ...} dict를
    돌려주면 (dict, None)으로 맞춰 호출부의 튜플 풀기가 그대로 동작하게."""
    r = await _bg(fn, *a, **kw)
    return r if isinstance(r, tuple) else (r, None)


async def _bg_long(fn, budget, *a, **kw):
    """parse_document 전용 _bg 변형(2026-10-21 단일화) — 도구 시간 상한을 MCP_TOOL_TIMEOUT_SEC(기본 30초) 대신
    budget(+10초 여유)으로 기다린다. 대기열·동시 상한·busy 판정은 _bg와 같은 규칙(S12·MC2) — 파싱은 서버 부하에 따라
    60초를 넘길 수 있어서 사용자가 준 time_out_threshold 예산 안에서 한 자리에서 끝내는 게 이 도구의 계약."""
    global _INFLIGHT
    limiter = _limiter()
    queue_cap = _queue_cap(limiter)
    bq = limiter.total_tokens + queue_cap if queue_cap else None
    if bq is not None and _INFLIGHT >= bq:
        return {"error": "busy"}
    timeout = float(budget) + 10.0
    call = partial(fn, *a, **kw)
    _INFLIGHT += 1
    try:
        with anyio.fail_after(timeout):
            return await anyio.to_thread.run_sync(call, limiter=limiter, abandon_on_cancel=True)
    except TimeoutError:
        return {"error": "timeout"}
    finally:
        _INFLIGHT -= 1
