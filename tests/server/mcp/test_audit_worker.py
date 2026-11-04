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
from mcp_server.routers import tool_runner
from mcp_server.services import call_log as audit


def test_response_deadlines():
    rows, threads = [], []
    original = audit.Call._prepare
    entered, release = threading.Event(), threading.Event()
    result = {"answer": [1, 2, 3]}

    def delayed(call):
        threads.append(threading.current_thread().name)
        entered.set()
        assert release.wait(30)
        original(call)

    async def run():
        tool_runner._LIMITER, tool_runner._INFLIGHT = None, 0
        # 공용 anyio limiter가 포화돼도 전용 감사 워커는 진행한다.
        default = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = default.total_tokens
        default.total_tokens = 1
        await default.acquire()
        try:
            with mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1", MCP_TOOL_TIMEOUT_SEC="0.05"):

                async def wait_until_entered():
                    while not entered.is_set():
                        await asyncio.sleep(0.001)

                # 업무도 감사도 release 전에는 끝나지 않는다. timeout 응답은 먼저 온다.
                assert await tool_runner._bg(lambda: release.wait(30)) == {"error": "timeout"}
                await asyncio.wait_for(wait_until_entered(), 30)
                assert not release.is_set() and not rows
                tool_runner._INFLIGHT = 2
                for invoke in (lambda: tool_runner._bg(lambda: None), lambda: tool_runner._bg_long(lambda: None, 1)):
                    assert await invoke() == {"error": "busy"}
                    assert not release.is_set() and not rows
                tool_runner._INFLIGHT = 0
                for invoke in (lambda: tool_runner._bg(lambda: result), lambda: tool_runner._bg_long(lambda: result, 1)):
                    reply = await invoke()
                    assert reply is result and not release.is_set() and not rows
                release.set()
                assert audit.drain(deadline=time.monotonic() + 30)
                assert len(rows) == 5 and all(name == "mcp-audit" for name in threads)
                assert rows[0]["status"] == "timeout" and rows[0]["duration_ms"] >= 0
                assert [row["status"] for row in rows] == ["timeout", "busy", "busy", "ok", "ok"]
                assert result == {"answer": [1, 2, 3]}
        finally:
            release.set()
            default.release()
            default.total_tokens = previous_tokens
            tool_runner._LIMITER, tool_runner._INFLIGHT = None, 0

    assert audit.drain()
    with patch.object(audit.Call, "_prepare", delayed), patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)):
        asyncio.run(run())


def test_queue_metadata():
    entered, release = threading.Event(), threading.Event()
    rows = []
    original = audit.Call._prepare

    def blocked(call):
        entered.set()
        assert release.wait(30)
        original(call)

    with settings.isolated(PG_PASSWORD="zqz"):
        worker = audit.Worker(capacity=1)
        with (
            patch.object(audit, "_WORKER", worker),
            patch.object(audit.Call, "_prepare", blocked),
            patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)),
        ):
            try:
                first = audit.start(lambda query: None, ("zqz",))
                first.finish({"query": "zqz"})
                assert entered.wait(30)
                audit.start(lambda: None).finish({"query": "zqz"})
                overflow = audit.start(lambda query: None, ("zqz",))
                overflow.finish({"query": "zqz"}, err="zqz")
                overflow.finish({"query": "zqz"})
                assert not release.is_set()
                assert len(rows) == 1 and rows[0]["args"] is None and rows[0]["result"] is None
                assert rows[0]["error_code"] == "audit_queue_full" and rows[0]["error_message"] is None
                assert rows[0]["result_keys"] == {"audit_body_omitted": "queue_full"}
                assert worker.stats()["body_omitted"] == 1 and worker.stats()["queued"] == 1
            finally:
                release.set()
                assert worker.drain()
                worker.close()
            assert len(rows) == 3 and len({row["request_id"] for row in rows}) == 3
            assert "zqz" not in json.dumps(rows)
            assert rows[1]["args"] == '{"query": "***"}'
            assert rows[1]["result"] == '{"query": "***"}'


def test_overflow_sink_nonblocking():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked_writer(batch):
        entered.set()
        release.wait(30)
        finished.set()

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=blocked_writer, fallback_dir=directory, queue_size=1, batch_size=1, flush_sec=0.001)
        worker = audit.Worker(capacity=1)
        with settings.isolated(APPLOG_DB_ENABLED="1"), patch.object(logsink, "_SINGLETON", sink):
            try:
                sink.emit("mcp_log", {"tool_name": "occupied"})
                assert entered.wait(30)
                sink.emit("mcp_log", {"tool_name": "queued"})
                # 닫힌 감사 큐도 같은 본문 생략 경로, sink 포화도 기다리지 않음.
                worker.close()
                worker.submit(audit.start(lambda: None), None, {"tool": "overflow", "status": "ok"})
                assert not release.is_set()
                assert not finished.is_set()
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
with settings.isolated(APPLOG_SHUTDOWN_SEC="1", APPLOG_DB_ENABLED="1"):
    rows=[]
    worker=audit._worker()
    with patch.object(logsink, "_SINGLETON", None), patch.object(logsink, "_write_db", side_effect=lambda batch: rows.extend(batch)):
        # 감사 drain 중 처음 만들어지는 sink도 같은 종료 호출에서 비운다.
        audit.start(lambda: None).finish({"answer":1})
        with patch.object(worker, "close", wraps=worker.close) as close_worker, patch.object(logsink, "shutdown", wraps=logsink.shutdown) as close_sink:
            assert exitclean._cleanup()
            assert close_worker.call_args.kwargs["deadline"] == close_sink.call_args.kwargs["deadline"]
        assert not worker.thread.is_alive()
        assert len(rows)==1 and not worker.thread.is_alive() and not logsink._SINGLETON._thread.is_alive()
    entered, release=threading.Event(),threading.Event()
    worker=audit.Worker()
    def blocked(call):
        entered.set()
        release.wait(30)
    sink=logsink.Sink(writer=lambda batch: None, flush_sec=0.001)
    with patch.object(audit,"_WORKER",worker), patch.object(audit.Call,"_prepare",blocked), patch.object(logsink,"_SINGLETON",sink):
        audit.start(lambda: None).finish(None)
        assert entered.wait(30)
        started=time.monotonic()
        assert exitclean._cleanup()
        elapsed=time.monotonic()-started
        assert not release.is_set() and worker.thread.is_alive()
        assert worker.stats()["dropped"] == 1
        release.set()
        worker.thread.join(30)
        sink._thread.join(30)
        assert not worker.thread.is_alive() and not sink._thread.is_alive()
        print("AUDIT_TEST_RESULT:" + json.dumps({"elapsed":elapsed,"rows":len(rows)}))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", program], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=settings.child_env()
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    assert proc.returncode == 0, stdout + stderr
    # 서버 이미지는 JSON 로그도 stdout에 쓴다. 시험 결과 줄만 읽어 로그와 섞이지 않게 한다.
    results = [json.loads(line.removeprefix("AUDIT_TEST_RESULT:")) for line in stdout.splitlines() if line.startswith("AUDIT_TEST_RESULT:")]
    assert len(results) == 1 and results[0]["rows"] == 1


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


def test_byte_budget():
    entered, release = threading.Event(), threading.Event()
    rows, sizes, processing_bytes = [], [], []
    original = audit.Call._prepare

    def blocked(call):
        processing_bytes.append(worker.stats()["pending_bytes"])
        entered.set()
        assert release.wait(30)
        original(call)

    call = audit.start(lambda query: None, ("first",))
    result = {"answer": "한글"}
    size = audit._estimate((call.arguments, result), 10000)
    assert size is not None
    worker = audit.Worker(max_queue_bytes=size * 2)
    with (
        patch.object(audit, "_WORKER", worker),
        patch.object(audit.Call, "_prepare", blocked),
        patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)),
    ):
        try:
            call.finish(result)
            assert entered.wait(30)
            sizes.append(worker.stats()["pending_bytes"])
            audit.start(lambda query: None, ("first",)).finish(result)
            sizes.append(worker.stats()["pending_bytes"])
            # 각 항목은 한도 안이지만 합계가 초과: 원문을 보관하지 않고 즉시 메타만.
            audit.start(lambda query: None, ("first",)).finish(result, err="x" * 1000000)
            assert len(rows) == 1 and rows[0]["args"] is None and rows[0]["result"] is None
            assert not release.is_set() and worker.stats()["body_omitted"] == 1
            assert sizes == [size, 2 * size]
            assert worker.stats()["pending_bytes"] == 2 * size
        finally:
            release.set()
            assert worker.drain(deadline=time.monotonic() + 30)
            worker.close()
    assert len(rows) == 3 and worker.stats()["pending_bytes"] == 0
    assert processing_bytes == [size, size]


def test_large_integer_byte_budget():
    huge = int("9" * 4000)
    actual = sys.getsizeof(huge)
    assert actual > 1024
    for value in (0, 1, -1, huge, -huge):
        size = sys.getsizeof(value)
        assert audit._estimate(value, size) == size
        assert audit._estimate(value, size - 1) is None
    for value in (None, False, True, 1.5):
        assert audit._estimate(value, 64) == 64

    rows = []
    worker = audit.Worker(max_queue_bytes=1024)
    with (
        patch.object(audit, "_WORKER", worker),
        patch.object(audit.Call, "_write") as write,
        patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)),
    ):
        try:
            # 입력·결과 각각의 큰 정수를 큐나 활성 처리에 보관하지 않고 메타로 보낸다.
            audit.start(lambda query: None, (huge,)).finish(None)
            audit.start(lambda: None).finish(huge)
            assert worker.stats()["body_omitted"] == 2
            assert worker.stats()["pending_bytes"] == 0 and worker.stats()["queued"] == 0
            assert worker.pending == 0 and worker.queue.empty()
            write.assert_not_called()
        finally:
            worker.close()
    assert not worker.thread.is_alive() and len(rows) == 2
    for row in rows:
        assert row["args"] is None and row["result"] is None
        assert row["result_keys"] == {"audit_body_omitted": "queue_full"}
        assert row["error_code"] == "audit_queue_full"


def test_estimate_bound():
    class CountingList(list):
        visited = 0

        def __iter__(self):
            for value in super().__iter__():
                self.visited += 1
                yield value

    many = CountingList([None] * (audit._ESTIMATE_MAX_NODES * 2))
    assert audit._estimate(many, 10**12) is None
    assert many.visited == audit._ESTIMATE_MAX_NODES
    many.visited = 0
    assert audit._estimate(many, 128) is None and many.visited <= 2
    assert audit._estimate("한" * 1000, 4000) is None
    loop = []
    loop.append(loop)
    assert audit._estimate(loop, 10**12) is None


def test_large_metadata():
    rows, seen = [], []
    original = audit.jsonlog.masked
    huge = "x" * 1000000

    def observe(row):
        if isinstance(row, dict) and "error_message" in row:
            seen.append(row)
            assert len(row["error_message"] or "") <= audit._META_TEXT_LIMIT
            assert len(row.get("knox_id") or "") <= audit._META_TEXT_LIMIT
        return original(row)

    assert len(audit._status({"error": huge})[1]) <= audit._META_TEXT_LIMIT
    with settings.isolated(PG_PASSWORD="long-secret-" * 300):
        assert "long-secret-" not in audit.jsonlog.masked(audit._metadata({"err": "long-secret-" * 300}))["err"]
    worker = audit.Worker(max_queue_bytes=0)
    with (
        patch.object(audit, "_WORKER", worker),
        patch.object(audit.jsonlog, "masked", side_effect=observe),
        patch.object(logsink, "emit", side_effect=lambda _, row: rows.append(row)),
        audit.request_context({"x-mcp-user": huge, "x-mcp-client": huge}),
    ):
        try:
            audit.start(lambda: None).finish({"error": huge}, err=huge)
        finally:
            worker.close()
    assert len(rows) == 1 and seen and rows[0]["result"] is None


def test_cancelled_bytes():
    entered, release = threading.Event(), threading.Event()
    worker = audit.Worker(max_queue_bytes=10000)
    call = audit.start(lambda: None)
    size = audit._estimate((call.arguments, None), 10000)

    def blocked(*args):
        entered.set()
        assert release.wait(30)

    with patch.object(audit.Call, "_write", blocked):
        try:
            worker.submit(call, None, {})
            assert entered.wait(30)
            worker.submit(audit.start(lambda: None), None, {})
            worker.submit(audit.start(lambda: None), None, {})
            assert worker.stats()["pending_bytes"] == 3 * size
            worker.close(deadline=time.monotonic())
            assert worker.stats()["pending_bytes"] == size  # 활성 한 건만 남음.
            assert worker.stats()["queued"] == 0 and worker.stats()["dropped"] == 3
        finally:
            release.set()
            worker.thread.join(30)
    assert not worker.thread.is_alive() and worker.stats()["pending_bytes"] == 0
