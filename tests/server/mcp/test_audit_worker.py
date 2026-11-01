"""감사 지연은 응답/도구 limiter와 독립, 포화 메타와 종료 deadline을 검증한다."""

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import anyio

from common.config import settings
from common.store import logsink
from mcp_server import config as mc
from mcp_server.routers import dispatch
from mcp_server.services import call_log as audit


def test_response_deadlines():
    rows, threads = [], []
    original = audit.Call._prepare
    result = {"answer": [1, 2, 3]}

    def delayed(call):
        threads.append(threading.current_thread().name)
        time.sleep(0.3)
        original(call)

    async def run():
        dispatch._LIMITER, dispatch._INFLIGHT = None, 0
        # 공용 anyio limiter가 포화돼도 전용 감사 워커는 진행한다.
        default = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = default.total_tokens
        default.total_tokens = 1
        await default.acquire()
        try:
            with mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1", MCP_TOOL_TIMEOUT_SEC="0.05"):
                started = time.monotonic()
                assert await dispatch._bg(lambda: time.sleep(0.15)) == {"error": "timeout"}
                elapsed = time.monotonic() - started
                assert 0.035 <= elapsed < 0.12, elapsed
                dispatch._INFLIGHT = 2
                for invoke in (lambda: dispatch._bg(lambda: None), lambda: dispatch._bg_long(lambda: None, 1)):
                    started = time.monotonic()
                    assert await invoke() == {"error": "busy"}
                    assert time.monotonic() - started < 0.05
                dispatch._INFLIGHT = 0
                for invoke in (lambda: dispatch._bg(lambda: result), lambda: dispatch._bg_long(lambda: result, 1)):
                    started = time.monotonic()
                    reply = await invoke()
                    assert reply is result and time.monotonic() - started < 0.05
                assert audit.drain(deadline=time.monotonic() + 5)
                assert len(rows) == 5 and all(name == "mcp-audit" for name in threads)
                assert rows[0]["status"] == "timeout" and 35 <= rows[0]["duration_ms"] < 120
                assert [row["status"] for row in rows] == ["timeout", "busy", "busy", "ok", "ok"]
                assert rows[-1]["duration_ms"] < 50 and result == {"answer": [1, 2, 3]}
        finally:
            default.release()
            default.total_tokens = previous_tokens
            dispatch._LIMITER, dispatch._INFLIGHT = None, 0

    assert audit.drain()
    with patch.object(audit.Call, "_prepare", delayed), patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)):
        asyncio.run(run())


def test_queue_metadata():
    entered, release = threading.Event(), threading.Event()
    rows = []
    original = audit.Call._prepare

    def blocked(call):
        entered.set()
        assert release.wait(3)
        original(call)

    with settings.isolated(PG_PASSWORD="abc"):
        worker = audit.Worker(capacity=1)
        with (
            patch.object(audit, "_WORKER", worker),
            patch.object(audit.Call, "_prepare", blocked),
            patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)),
        ):
            try:
                first = audit.start(lambda query: None, ("abc",))
                first.finish({"query": "abc"})
                assert entered.wait(1)
                audit.start(lambda: None).finish({"query": "abc"})
                started = time.monotonic()
                overflow = audit.start(lambda query: None, ("abc",))
                overflow.finish({"query": "abc"}, err="abc")
                overflow.finish({"query": "abc"})
                assert time.monotonic() - started < 0.05
                assert len(rows) == 1 and rows[0]["args"] is None and rows[0]["result"] is None
                assert rows[0]["err"] == "audit_queue_full"
                assert rows[0]["result_keys"] == {"audit_body_omitted": "queue_full"}
                assert worker.stats()["body_omitted"] == 1 and worker.stats()["queued"] == 1
            finally:
                release.set()
                assert worker.drain()
                worker.close()
            assert len(rows) == 3 and len({row["request_id"] for row in rows}) == 3
            assert "abc" not in json.dumps(rows)
            assert rows[1]["args"] == '{"query": "***"}'
            assert rows[1]["result"] == '{"query": "***"}'


def test_overflow_sink_nonblocking():
    entered, release = threading.Event(), threading.Event()

    def blocked_writer(batch):
        entered.set()
        release.wait(3)

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=blocked_writer, fallback_dir=directory, queue_size=1, batch_size=1, flush_sec=0.001)
        worker = audit.Worker(capacity=1)
        with settings.isolated(APPLOG_DB_ENABLED="1"), patch.object(logsink, "_SINGLETON", sink):
            try:
                sink.emit("mcp_call", {"tool": "occupied"})
                assert entered.wait(1)
                sink.emit("mcp_call", {"tool": "queued"})
                # 닫힌 감사 큐도 같은 본문 생략 경로, sink 포화도 기다리지 않음.
                worker.close()
                started = time.monotonic()
                worker.submit(audit.start(lambda: None), None, {"tool": "overflow", "status": "ok"})
                assert time.monotonic() - started < 0.05
                assert worker.stats()["body_omitted"] == 1 and sink.stats()["dropped"] == 1
            finally:
                release.set()
                sink.close()


def test_shutdown_deadline():
    # 별도 프로세스에서 실제 exitclean 순서/공유 deadline, 정상 drain과 막힌 감사 확인.
    program = r"""
import json, threading, time
from unittest.mock import patch
from common.config import settings
from common.core import exitclean
from common.store import logsink
from mcp_server.services import call_log as audit
with settings.isolated(APPLOG_SHUTDOWN_SEC="0.08", APPLOG_DB_ENABLED="1"):
    rows=[]
    worker=audit._worker()
    with patch.object(logsink, "_SINGLETON", None), patch.object(logsink, "_write_db", side_effect=lambda batch: rows.extend(batch)):
        # 감사 drain 중 처음 만들어지는 sink도 같은 종료 호출에서 비운다.
        audit.start(lambda: None).finish({"answer":1})
        started=time.monotonic()
        assert exitclean._cleanup()
        assert time.monotonic()-started < 0.2
        assert len(rows)==1 and not worker.thread.is_alive() and not logsink._SINGLETON._thread.is_alive()
    entered, release=threading.Event(),threading.Event()
    worker=audit.Worker()
    def blocked(call):
        entered.set()
        release.wait(2)
    sink=logsink.Sink(writer=lambda batch: None, flush_sec=0.001)
    with patch.object(audit,"_WORKER",worker), patch.object(audit.Call,"_prepare",blocked), patch.object(logsink,"_SINGLETON",sink):
        audit.start(lambda: None).finish(None)
        assert entered.wait(1)
        started=time.monotonic()
        assert exitclean._cleanup()
        elapsed=time.monotonic()-started
        assert 0.06 <= elapsed < 0.2, elapsed
        assert worker.stats()["dropped"] == 1
        release.set()
        worker.thread.join(1)
        sink._thread.join(1)
        assert not worker.thread.is_alive() and not sink._thread.is_alive()
        print(json.dumps({"elapsed":elapsed,"rows":len(rows)}))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", program], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=settings.child_env()
    )
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    assert proc.returncode == 0, stdout + stderr
    assert json.loads(stdout)["rows"] == 1


def test_short_secrets_sink():
    rows = []
    with tempfile.TemporaryDirectory() as directory, settings.isolated(PG_PASSWORD="abc", APPLOG_DB_ENABLED="1"):
        sink = logsink.Sink(writer=lambda batch: rows.extend(batch), fallback_dir=directory, flush_sec=0.001)
        with patch.object(logsink, "_SINGLETON", sink):
            audit.start(lambda query, argv: None, ("abc", ["--query", "abc"])).finish({"query": "abc", "other": "abcd"})
            assert audit.drain()
            sink.close()
        assert len(rows) == 1
        row = rows[0][1]
        assert json.loads(row["args"]) == {"query": "***", "argv": ["--query", "***"]}
        assert json.loads(row["result"]) == {"query": "***", "other": "abcd"}
