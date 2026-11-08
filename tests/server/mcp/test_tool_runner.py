"""mcp_server.services.tool_runner 시험."""

import time

from mcp_server import config as mc
from mcp_server.services import tool_runner as M
from mcp_server.services.tool_runner import _bg


def _selftest_concurrency():
    """_bg(S12) — MCP_MAX_CONCURRENCY보다 많은 호출이 와도 한 번에 상한만큼만 동시에 돈다(이벤트 루프 밖 스레드)."""
    import asyncio
    import threading

    _env = mc.senv(MCP_MAX_CONCURRENCY="2")
    M._LIMITER = None
    active, peak, lock = [0], [0], threading.Lock()

    def slow():
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return 1

    async def main():
        return await asyncio.gather(*[_bg(slow) for _ in range(6)])

    try:
        out = asyncio.run(main())
        assert out == [1] * 6 and peak[0] <= 2, peak[0]
    finally:
        _env.close()
        M._LIMITER = None
    print("[selftest] _bg — 동시 상한(MCP_MAX_CONCURRENCY=2) 넘지 않음 통과")


def _selftest_overload():
    """MC2(RV2) — 대기열 상한(MCP_MAX_QUEUE)을 넘는 호출은 기다리지 않고 바로 busy(프로세스는 안 죽음) ·
    시간 상한(MCP_TOOL_TIMEOUT_SEC)을 넘으면 timeout(스레드 자체는 못 끊지만 호출자는 바로 돌려받음)."""
    import asyncio

    def slow():
        time.sleep(0.3)
        return 1

    async def main():
        return await asyncio.gather(*[_bg(slow) for _ in range(4)])

    _env = mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1", MCP_TOOL_TIMEOUT_SEC=None)
    M._LIMITER = None
    M._INFLIGHT = 0
    try:
        out = asyncio.run(main())
        busy = sum(1 for r in out if r == {"error": "busy"})
        assert busy >= 1 and out.count(1) >= 1, out  # 동시1 + 대기열1만 받아줌 — 나머지는 바로 busy, 서버는 안 죽음
    finally:
        _env.close()
        M._LIMITER = None
        M._INFLIGHT = 0

    _env = mc.senv(MCP_MAX_CONCURRENCY="1", MCP_TOOL_TIMEOUT_SEC="0.05", MCP_MAX_QUEUE=None)
    M._LIMITER = None
    M._INFLIGHT = 0
    try:
        r = asyncio.run(_bg(slow))
        assert r == {"error": "timeout"}, r
    finally:
        _env.close()
        M._LIMITER = None
        M._INFLIGHT = 0
    print("[selftest] _bg — 대기열 상한(MCP_MAX_QUEUE) 넘으면 바로 busy · 시간 상한(MCP_TOOL_TIMEOUT_SEC) 넘으면 timeout 통과(MC2)")


def test_db_errors():
    """도구가 던진 PG 오류 → 질의 시간 제한(QueryCanceled)은 timeout, 접속 오류(OperationalError·풀 대기 초과)는 db_unavailable ·
    감사 행 상태도 같이. 그 밖의 예외는 그대로 올라간다."""
    import asyncio
    from unittest.mock import patch

    import psycopg
    import psycopg_pool

    class Audit:
        def run(self, fn, *a, **kw):
            return fn(*a, **kw)

        def finish(self, result=None, *, status=None, err=None):
            rows.append((result, status))

    cases = [  # (던질 예외, 기대 결과, 감사 상태)
        (psycopg.errors.QueryCanceled("canceling statement due to statement timeout"), {"error": "timeout"}, "timeout"),
        (psycopg.OperationalError("server closed the connection"), {"error": "db_unavailable"}, "error"),
        (psycopg_pool.PoolTimeout("couldn't get a connection"), {"error": "db_unavailable"}, "error"),
        (ValueError("bug"), ValueError, "error"),
    ]
    _env = mc.senv(MCP_MAX_CONCURRENCY="2", MCP_TOOL_TIMEOUT_SEC=None, MCP_MAX_QUEUE=None)
    M._LIMITER = None
    M._INFLIGHT = 0
    try:
        for exc, want, status in cases:
            rows = []

            def tool(exc=exc):
                raise exc

            with patch.object(M.call_log, "start", return_value=Audit()):
                try:
                    got = asyncio.run(_bg(tool))
                except Exception as e:
                    got = type(e)
            assert got == want and rows[-1][1] == status, (exc, got, rows)
    finally:
        _env.close()
        M._LIMITER = None
        M._INFLIGHT = 0
    print("[selftest] _bg — PG 질의 시간 제한 timeout · 접속 오류 db_unavailable 통과")


def test_main():  # 옛 자기 점검 사례(__main__이 없어 import해 부르던 순서 — main.py 옛 selftest)
    _selftest_concurrency()
    _selftest_overload()
