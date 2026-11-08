"""도구 실행 창구 — 스레드 실행·도구별 자리(공용 MCP_MAX_CONCURRENCY · parse_document 2 · get_doc_fulltext 2)·대기열 상한(MCP_MAX_QUEUE)·
요청 시간 상한(MCP_TOOL_TIMEOUT_SEC)·감사 1행."""

from functools import partial

import anyio
import psycopg

from mcp_server import config as mc  # 요청마다 읽는 값은 호출 때 cfg()
from mcp_server.services import call_log

PARSE_MAX_SEC = 600.0  # parse_document 기다림 상한(초) — time_out_threshold가 더 커도 10분에서 자름
# 자기 자리를 따로 쓰는 도구(함수 이름 → 자리 수). 나머지는 공용 자리(MCP_MAX_CONCURRENCY).
# parse_document는 최대 10분 걸려 공용 자리를 오래 쥐고, get_doc_fulltext는 한 번에 최대 24 MB를 메모리에 올린다.
_OWN_SLOTS = {"do_parse_document": 2, "do_get": 2}
_LANES: dict = {}  # 자리 이름("shared" 또는 _OWN_SLOTS의 이름) → _Lane


class _Lane:
    """한 무리의 자리. accepted = 받아들인(실행 중+대기 중) 요청 수 — limiter 통계는 판정과 자리 잡기 사이에 await가 끼어
    동시에 온 요청을 못 세므로 따로 센다(판정→증가 사이에 await가 없음)."""

    def __init__(self, slots):
        self.limiter = anyio.CapacityLimiter(slots)
        self.total = slots
        self.accepted = 0


def _lane(name):
    if name not in _LANES:
        _LANES[name] = _Lane(_OWN_SLOTS.get(name) or int(mc.cfg().server.max_concurrency))  # 공용 기본 8(모델) — 한 번 만들어 둠
    return _LANES[name]


def _queue_cap(total):
    """대기열 상한(MCP_MAX_QUEUE — 요청마다 읽음, 없으면 자리 수×4, "0"은 0=무제한 — `or`로 쓰면 0이 ×4로 바뀜)."""
    v = mc.cfg().server.max_queue
    return int(v) if v is not None else total * 4


async def _dispatch(fn, timeout, a, kw, lane_name):
    """_bg·_bg_long 공통 — busy 판정, 스레드 실행, 시간 상한(초, None이면 무제한 — 0은 바로 시간 초과), 감사 1행.
    도구가 던진 PG 오류(풀이 끊긴 연결을 한 번 바꾼 뒤에도): 질의 시간 제한(QueryCanceled)은 timeout, 그 밖의 접속 오류는 db_unavailable."""
    lane = _lane(lane_name)
    queue_cap = _queue_cap(lane.total)
    if queue_cap and lane.accepted >= lane.total + queue_cap:
        call_log.start(fn, a, kw).finish({"error": "busy"})
        return {"error": "busy"}
    lane.accepted += 1
    audit = call_log.start(fn, a, kw)
    call = partial(audit.run, fn, *a, **kw)
    try:
        with anyio.fail_after(timeout):
            result = await anyio.to_thread.run_sync(call, limiter=lane.limiter, abandon_on_cancel=timeout is not None)
        audit.finish(result)
        return result
    except TimeoutError as exc:
        if timeout is None:  # 무제한이면 도구가 던진 TimeoutError — 시간 상한이 아니므로 그대로 올림
            audit.finish(status="error", err=str(exc))
            raise
        audit.finish({"error": "timeout"}, status="timeout")
        return {"error": "timeout"}
    except psycopg.errors.QueryCanceled as exc:  # PG 질의 시간 제한 — OperationalError의 하위라 먼저
        audit.finish({"error": "timeout"}, status="timeout", err=str(exc))
        return {"error": "timeout"}
    except psycopg.OperationalError as exc:
        audit.finish({"error": "db_unavailable"}, status="error", err=str(exc))
        return {"error": "db_unavailable"}
    except BaseException as exc:
        audit.finish(status="error", err=str(exc))
        raise
    finally:
        lane.accepted -= 1


async def _bg(fn, *a, **kw):
    """동기 도구 함수를 이벤트 루프 밖 스레드로 돌림 — 느린 도구 하나가 /health·다른 요청을 막지 않게.
    과부하 보호: 자리(공용 MCP_MAX_CONCURRENCY, get_doc_fulltext는 자기 2자리)만큼 돌고 있는 것 + 그 뒤로 밀린 대기가
    대기열 상한(MCP_MAX_QUEUE, 기본 자리 수×4, =0이면 무제한)까지 차 있으면 **기다리지 않고** 바로
    {"error": "busy"} — 꽉 찼을 때 요청이 무한정 쌓여 죽는 대신 호출자가 바로 알고 재시도하게.
    받아들여진 요청은 시간 상한(MCP_TOOL_TIMEOUT_SEC, 기본 30초, =0이면 무제한) 안에 끝나야 하며 넘으면 {"error": "timeout"}.
    호출자별 동시 상한은 안 둠 — MCP_TOKEN이 서버 전체에 하나뿐이라 X-MCP-Client 머리글(자기 신고값,
    검증 없음)로 자원을 나누면 신뢰 경계가 아닌 값으로 과설계만 늘어남."""
    timeout = float(mc.cfg().server.tool_timeout_sec)  # 기본 30(모델) — 요청마다
    name = getattr(fn, "__name__", "")
    # 설정값 0 = 무제한 (_bg_long의 0은 바로 시간 초과)
    return await _dispatch(fn, timeout or None, a, kw, name if name in _OWN_SLOTS else "shared")


async def _bg_long(fn, budget, *a, **kw):
    """parse_document 전용 _bg 변형 — 자기 2자리에서, 도구 시간 상한을 MCP_TOOL_TIMEOUT_SEC(기본 30초) 대신
    budget(PARSE_MAX_SEC 10분에서 자름, +10초 여유)으로 기다린다. 대기열·busy 판정은 _bg와 같은 규칙 — 파싱은 서버 부하에 따라
    60초를 넘길 수 있어서 사용자가 준 time_out_threshold 예산 안에서 한 자리에서 끝내는 게 이 도구의 계약."""
    return await _dispatch(fn, min(float(budget), PARSE_MAX_SEC) + 10.0, a, kw, "do_parse_document")
