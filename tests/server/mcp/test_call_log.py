"""MCP 감사: 외부 접속 없이 상한·키·오류 격리·큐/timeout/HTTP 컨텍스트 검증."""

import asyncio
import base64
import hashlib
import io
import json
import logging
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from uuid import uuid4

import httpx

from common.core import jsonlog
from mcp_server import config as mc
from mcp_server import main
from mcp_server.services import call_log as audit
from mcp_server.services import tool_runner


def _encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def test_payload():
    rows = []
    raw = b"a document payload"
    source = {"content_b64": base64.b64encode(raw).decode(), "filename": "f.txt", "api_key": "never-store"}
    result = {"text": "가나다" * 30000, "engine": "plain", "job_id": "j1", "rep_path": "out/rep.json", "password": "never-store"}

    def do_parse_document(content_b64, filename, api_key):
        return result

    with patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)):
        call = audit.start(do_parse_document, kwargs=source)
        call.finish(result)
        assert audit.drain()
        call.finish(result)
        assert audit.drain()
    assert len(rows) == 1
    row = rows[0]
    args = json.loads(row["args"])
    assert args["content_b64"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert args["content_b64"]["bytes"] == len(raw)
    assert source["content_b64"] == base64.b64encode(raw).decode()  # 원본 불변
    assert "never-store" not in row["args"] + row["result"]
    assert row["result_bytes"] == len(_encoded(result))
    assert row["result_sha256"] == hashlib.sha256(_encoded(result)).hexdigest()
    assert row["result_truncated"] and len(row["result"].encode()) <= 65536
    assert row["result_keys"] == {"engine": "plain", "job_id": "j1", "rep_path": "out/rep.json", "text_chars": 90000}
    assert "agent" not in row
    assert row["status"] == "ok" and row["duration_ms"] >= 0

    def do_search(question):
        return None

    with patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)):
        call = audit.start(do_search, ("한" * 9000,))
        call.finish({"error": "token=do-not-store"})
        assert audit.drain()
    assert rows[-1]["args_truncated"] and len(rows[-1]["args"].encode()) <= 16384
    assert rows[-1]["args_bytes"] == len(_encoded({"question": "한" * 9000}))
    assert rows[-1]["status"] == "error" and "do-not-store" not in rows[-1]["error_message"]
    assert not row["args_truncated"]


def test_result_keys():
    hits = [{"text": "body", "file_name": "a.pdf", "page": 1, "chunk_key": f"k{i}"} for i in range(2000)]
    result = {"question": "q", "evidence": hits, "evidence_status": "found", "filter": {"source_system": ["SFDC"]}, "scope_docs": 3}
    rows = []
    with patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)):
        with audit.request_context({}) as context:
            audit.update_request(context, {"method": "tools/call", "params": {"name": "search"}})
            audit.start(lambda: None).finish(result)
            assert audit.drain()
    keys = rows[0]["result_keys"]
    assert keys == {"chunk_keys": [f"k{i}" for i in range(2000)], "evidence_status": "found", "filter": result["filter"], "scope_docs": 3}
    assert rows[0]["result_truncated"]
    listed = {"batch": {"matched": 2, "returned": 1, "next_cursor": "7"}, "documents": [{"doc_key": "d1", "files": []}], "ms": 1}
    assert audit.result_keys("list_doc_fulltext", listed) == {"matched": 2, "returned": 1, "next_cursor": "7", "doc_keys": ["d1"]}
    got = {
        "batch": {"requested": 2, "ok": 1, "skipped": 1, "total_bytes": 4, "truncated": False, "json_section": None},
        "files": [
            {"sfid": "s1", "name": "a.md", "kind": "md", "size": 4, "sha256": "h", "status": "ok", "content": "body"},
            {"sfid": "s2", "name": "b.md", "kind": "md", "skip_reason": "too_large"},
        ],
    }
    keys = audit.result_keys("get_doc_fulltext", got)
    assert keys["files"] == [
        {"name": "a.md", "kind": "md", "size": 4, "sha256": "h"},
        {"name": "b.md", "kind": "md", "skip_reason": "too_large"},
    ]
    assert keys["ok"] == 1 and "body" not in str(keys)  # 본문은 요약 키에 없음
    assert audit.result_keys("query_edw", {"row_count": 2, "columns": [{"name": "id"}], "rows": [[1]]}) == {
        "row_count": 2,
        "columns": [{"name": "id"}],
    }
    assert audit.result_keys("edw_meta", {"kind": "table", "schema": "AI", "columns": [{"name": "id"}]}) == {
        "kind": "table",
        "schema": "AI",
        "column_count": 1,
    }


def test_dispatch_audit():
    rows, events = [], []
    stopped = threading.Event()

    def slow():
        time.sleep(0.08)
        stopped.set()
        return {"answer": 1}

    async def run():
        tool_runner._LIMITER, tool_runner._INFLIGHT = None, 0
        with mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1", MCP_TOOL_TIMEOUT_SEC="0.02"):
            out = await asyncio.gather(*[tool_runner._bg(slow) for _ in range(4)])
            assert out.count({"error": "busy"}) == 2
            assert out.count({"error": "timeout"}) == 2
            await asyncio.sleep(0.12)  # abandoned가 끝나도 감사 행은 늘지 않는다.
        assert stopped.is_set()
        assert audit.drain()
        assert len(rows) == 4
        assert any(e == "mcp.thread.finished" for e in events)
        assert all(r["queue_wait_ms"] >= 0 for r in rows)
        tool_runner._LIMITER = None
        with mc.senv(MCP_TOOL_TIMEOUT_SEC="0"):
            assert await tool_runner._bg(lambda: {"answer": 2}) == {"answer": 2}
        assert audit.drain()
        assert rows[-1]["status"] == "ok"
        assert await tool_runner._bg_long(lambda: {"engine": "x"}, 1) == {"engine": "x"}
        assert audit.drain()
        assert rows[-1]["status"] == "ok"
        tool_runner._LIMITER = None
        tool_runner._INFLIGHT = 2
        with mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1"):
            assert await tool_runner._bg_long(lambda: None, 1) == {"error": "busy"}
        tool_runner._INFLIGHT = 0
        assert await tool_runner._bg_long(slow, -9.99) == {"error": "timeout"}
        await asyncio.sleep(0.1)
        assert audit.drain()
        assert rows[-1]["status"] == "timeout"
        count = len(rows)
        assert await tool_runner._bg_long(slow, -10) == {"error": "timeout"}  # 상한 0.0초 = 바로 시간 초과, 무제한이 아님
        await asyncio.sleep(0.1)
        assert audit.drain()
        assert len(rows) == count + 1 and rows[-1]["status"] == "timeout"
        assert await tool_runner._dispatch(slow, None, (), {}) == {"answer": 1}  # None만 무제한
        assert audit.drain()
        assert rows[-1]["status"] == "ok"

        def slow_error():
            raise TimeoutError("tool says so")

        try:
            await tool_runner._dispatch(slow_error, None, (), {})  # 무제한 모드의 도구 TimeoutError는 그대로 올라온다
            raise AssertionError("TimeoutError expected")
        except TimeoutError:
            pass
        assert audit.drain()
        assert rows[-1]["status"] == "error"

        def broken():
            raise ValueError("api_key=do-not-store")

        try:
            await tool_runner._bg(broken)
        except ValueError:
            pass
        else:
            raise AssertionError("tool exception swallowed")
        assert audit.drain()
        assert rows[-1]["status"] == "error" and "do-not-store" not in rows[-1]["error_message"]
        with patch.object(audit.logsink, "emit", side_effect=RuntimeError("sink failed")):
            assert await tool_runner._bg(lambda: 42) == 42
            # 실패 sink 모의를 유지한 채 이 감사까지 비워 다음 HTTP 시험에 행을 넘기지 않는다.
            assert audit.drain()
        with patch.object(audit, "Call", side_effect=RuntimeError("serialization failed")):
            assert await tool_runner._bg(lambda: 43) == 43

    with (
        patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)),
        patch.object(audit, "_debug", side_effect=lambda e, **kw: events.append(e)),
    ):
        try:
            asyncio.run(run())
        finally:
            tool_runner._LIMITER, tool_runner._INFLIGHT = None, 0


def test_http_context():
    rows, observations = [], []
    request_id = str(uuid4())

    async def inner(scope, receive, send):
        # 두 청크였던 본문도 그대로 재생되어야 한다.
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        observations.append((json.loads(body), jsonlog.get_context()))
        result = await tool_runner._bg(lambda: {"row_count": 2, "columns": ["id"]})
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": _encoded(result)})

    class FakeMcp:
        def streamable_http_app(self):
            return inner

    async def run():
        with patch.object(main, "build", return_value=FakeMcp()), patch.object(main.health, "register"):
            app = main.build_guarded_app("127.0.0.1", 8765, "secret")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            params = {"name": "query_edw", "arguments": {"sql": "select 1"}, "_meta": {"user": "meta-user"}}
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
            r = await client.post("/mcp", json=payload)
            assert audit.drain()
            assert r.status_code == 401 and rows[-1]["status"] == "unauthorized"
            hdr = {"Authorization": "Bearer secret", "X-MCP-Client": "test", "X-MCP-User": "header-user", "X-Request-Id": request_id}
            r = await client.post("/mcp", json=payload, headers=hdr)
            assert r.status_code == 200 and r.headers["x-request-id"] == request_id
            assert audit.drain()
            assert rows[-1]["request_id"] == request_id and rows[-1]["knox_id"] == "header-user"
            assert "agent" not in rows[-1] and rows[-1]["tool_name"] == "query_edw" and rows[-1]["rpc_method"] == "tools/call"
            assert json.loads(rows[-1]["args"]) == {"sql": "select 1"}
            assert observations[-1][1]["request_id"] == request_id
            del hdr["X-MCP-User"]
            r = await client.post("/mcp", json=payload, headers=hdr)
            assert audit.drain()
            assert r.status_code == 200 and rows[-1]["knox_id"] == "meta-user"
            assert "remote_addr" not in rows[-1] and rows[-1]["client_ip"] == "127.0.0.1" and rows[-1]["finished_at"]
        assert audit._REQUEST.get() is None
        assert len(rows) == 3, (len(rows), [(row.get("tool_name"), row.get("status"), row.get("request_id")) for row in rows])

    with patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)):
        try:
            asyncio.run(run())
        finally:
            tool_runner._LIMITER = None


def test_sdk_logs_stay_out_of_audit_log():
    """SDK(mcp.*) 줄: INFO는 DEBUG일 때만, 그 밖의 줄은 비밀값을 가려 stderr로만 — root·stdout·감사 로그에는 안 감."""
    from pathlib import Path

    from common.config import settings

    secret = "SDK_SECRET_VALUE_9f3a"
    sdk = logging.getLogger("mcp.server.lowlevel.server")  # 요청마다 INFO를 내는 SDK logger
    root, base = logging.getLogger(), logging.getLogger("mcp")
    saved = (base.handlers[:], base.level, base.propagate)

    class Spy(logging.Handler):
        def __init__(self):
            super().__init__()
            self.seen = []

        def emit(self, record):
            self.seen.append(record)

    spy = Spy()
    root.addHandler(spy)
    try:
        for level in ("INFO", "DEBUG"):
            err, out = io.StringIO(), io.StringIO()
            with (
                tempfile.TemporaryDirectory() as directory,
                settings.isolated(PG_PASSWORD=secret, LOG_LEVEL=level, APPLOG_DIR=directory, APPLOG_DB_ENABLED="0"),
                patch.object(sys, "stderr", err),
                patch.object(sys, "stdout", out),
            ):
                main.build("127.0.0.1", 0)
                app = jsonlog.setup("mcp")
                sdk.info("Processing request of type CallToolRequest")
                try:
                    raise ValueError(f"boom password={secret}")
                except ValueError:
                    sdk.exception("handler failed %s", secret)
                for handler in app.handlers:
                    handler.flush()
                audit_text = (Path(directory) / "mcp.jsonl").read_text(encoding="utf-8") if (Path(directory) / "mcp.jsonl").exists() else ""
                for handler in app.handlers[:]:
                    app.removeHandler(handler)
                    handler.close()
            lines = [json.loads(line) for line in err.getvalue().splitlines()]
            assert secret not in err.getvalue() and "***" in err.getvalue()
            assert any(row["level"] == "ERROR" and "ValueError" in row["err"] for row in lines)  # 예외는 항상
            assert any("Processing request" in row["msg"] for row in lines) == (level == "DEBUG")
            assert out.getvalue() == "" and audit_text == "" and not spy.seen
    finally:
        root.removeHandler(spy)
        for handler in base.handlers[:]:
            base.removeHandler(handler)
        for handler in saved[0]:
            base.addHandler(handler)
        base.setLevel(saved[1])
        base.propagate = saved[2]


def test_initialize_contract():
    from mcp.types import LATEST_PROTOCOL_VERSION, ListToolsResult

    from mcp_server.routers import edw_tools

    rows = []

    async def run():
        m = main.build("127.0.0.1", 8765)
        wire = ListToolsResult(tools=await m.list_tools()).model_dump_json(by_alias=True, exclude_none=True)
        # 직렬화 바이트 고정(로깅은 도구 계약을 바꾸지 않음). 계약 변경 시 별도 협의 필요. 11-03(사용자 결정, 등급 A): query_edw 기본
        # max_rows 2000→1000·설명 "default 1000", parse_document 설명 "64MB 상한"→"기본 100MB 상한" — 전 develop 8c4e078 11886바이트·7d24d867…
        # 11-03 pl-52(사용자 결정, 등급 A): search에 attrs 인자·근거 attrs 칸, edw_meta 인자 없음에 search_attrs — 전 11894바이트·80ab2ace…
        # (검토 고침: 근거 attrs null·search_attrs의 attrs 목록·오류면 안 붙음 설명 — 12608바이트·f7845fd7… 다음)
        # 11-04(사용자 결정, 등급 A): search 설명을 실제 동작으로 — source_system 필수·Other 포함, filter·scope_docs 늘 있음 — 전 12725바이트·1f4d4a53…
        # 11-04 op-13(사용자 결정, 등급 A): parse_document 허용 루트 `_mcp_parse/inbox`·호스트 `<루트>/output/` — 전 12810바이트·c458eda7…
        # 11-06 op-17(사용자 결정, 등급 A): search·list_doc_fulltext 설명에 "(개발 서버: DEV-<숫자>)" — 전 12802바이트·92449c45…
        assert len(wire.encode()) == 12862
        assert hashlib.sha256(wire.encode()).hexdigest() == "3bc3253e31ba08aa24726283c368d915425202b5ca2a74c511804959e56a4668"
        with patch.object(main, "build", return_value=m):
            app = main.build_guarded_app("127.0.0.1", 8765, "")
        headers = {"Accept": "application/json, text/event-stream", "X-MCP-Client": "test", "X-MCP-User": "test"}
        async with (
            m.session_manager.run(),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765", headers=headers) as client,
        ):
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "audit-test", "version": "1"},
                },
            }
            response = await client.post("/mcp", json=payload)
            assert response.status_code == 200, response.text
            assert audit.drain()
            assert len(rows) == 1 and rows[0]["rpc_method"] == "initialize" and rows[0]["tool_name"] is None
            assert "client_info" not in rows[0] and "audit-test" not in rows[0]["args"]
            assert json.loads(rows[0]["args"])["protocolVersion"] == LATEST_PROTOCOL_VERSION
            assert "serverInfo" in json.loads(rows[0]["result"])
            with patch.object(edw_tools, "do_edw_meta", return_value={"kind": "schemas", "schemas": []}):
                response = await client.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "edw_meta", "arguments": {}}}
                )
            assert audit.drain()
            assert response.status_code == 200 and len(rows) == 2
            assert rows[-1]["tool_name"] == "edw_meta" and rows[-1]["status"] == "ok"
            assert rows[-1]["session_id"] is None
            assert audit._REQUEST.get() is None

    with patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)):
        try:
            asyncio.run(run())
        finally:
            tool_runner._LIMITER = None


def test_stdio_channel():
    import sys

    from mcp.types import LATEST_PROTOCOL_VERSION

    from common.config import settings
    from common.core import paths

    script = """
from common.core import jsonlog, paths
from mcp_server.services import call_log
from mcp_server.routers import edw_tools
from mcp_server.main import build
paths.LOCAL_RUN = False  # 서버 stdout 기본값을 PC에서 재현(네트워크 없음).
call_log.configure_stdio()
jsonlog.setup("mcp")  # 이후 재설정에도 stdout Handler가 되살아나지 않는다.
def do_edw_meta(*args):
    return {"kind": "schemas", "schemas": []}
edw_tools.do_edw_meta = do_edw_meta
build("127.0.0.1", 8765).run(transport="stdio")
"""

    async def run():
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            cwd=paths.PROJ_ROOT,
            env=settings.child_env(APPLOG_DIR="", APPLOG_DB_ENABLED="0"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:

            async def request(payload):
                proc.stdin.write(_encoded(payload) + b"\n")
                await proc.stdin.drain()
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
                value = json.loads(line)
                assert value["jsonrpc"] == "2.0" and value["id"] == payload["id"]
                return value

            await request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
            )
            proc.stdin.write(_encoded({"jsonrpc": "2.0", "method": "notifications/initialized"}) + b"\n")
            reply = await request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "edw_meta", "arguments": {}}})
            assert not reply["result"].get("isError")
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            assert not stdout.strip(), stdout
            assert '"event": "mcp.call"' in stderr.decode()
            assert proc.returncode == 0
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    remaining, errors = await asyncio.wait_for(proc.communicate(), timeout=5)
                except TimeoutError:
                    proc.kill()
                    remaining, errors = await proc.communicate()
                print("stdio child:", remaining.decode(), errors.decode())

    asyncio.run(run())


def test_setting_audit():
    from common.config import settings

    rows = []
    secret = "DEMO_SECRET_VALUE"
    with (
        settings.isolated(PG_PASSWORD=secret),
        mc.senv(MCP_TOKEN="mcp-secret-value"),
        patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)),
    ):
        call = audit.start(lambda query: None, ({"nested": [secret, "mcp-secret-value"]},))
        call.finish({"nested": [secret, "mcp-secret-value"]}, err=secret)
        assert audit.drain()
        assert secret not in json.dumps(rows) and "mcp-secret-value" not in json.dumps(rows)
        assert audit._body({"query": secret}, 1000)[0] == '{"query": "***"}'


def test_audit_off_loop():
    rows, seen = [], []
    entered, output_entered, release = threading.Event(), threading.Event(), threading.Event()
    input_release = threading.Event()
    original_input, original_body = audit._input, audit._body
    loop_thread = threading.get_ident()
    encoded = base64.b64encode(b"a" * (8 * 1024 * 1024)).decode()

    def observed_input(tool, args):
        assert threading.get_ident() != loop_thread
        seen.append(tool_runner._INFLIGHT)
        entered.set()
        assert input_release.wait(30)  # 감사 입력 처리가 막혀 있어도 health/도구 응답은 먼저 온다.
        return original_input(tool, args)

    def observed_body(*args):
        assert threading.get_ident() != loop_thread
        if isinstance(args[0], dict) and "text" in args[0]:
            output_entered.set()
            assert release.wait(30)
        return original_body(*args)

    def do_parse_document(content_b64):
        return {"text": "result" * 1000000, "job_id": "j"}

    async def health(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    class FakeMcp:
        def streamable_http_app(self):
            return health

    async def ready(event):
        async with asyncio.timeout(30):
            while not event.is_set():
                await asyncio.sleep(0.001)

    async def run():
        with patch.object(main, "build", return_value=FakeMcp()), patch.object(main.health, "register"):
            app = main.build_guarded_app("127.0.0.1", 8765, "")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            tool_runner._LIMITER, tool_runner._INFLIGHT = None, 2
            with mc.senv(MCP_MAX_CONCURRENCY="1", MCP_MAX_QUEUE="1"):
                task = asyncio.create_task(tool_runner._bg_long(do_parse_document, 1, encoded))
                await ready(entered)
                assert (await client.get("/health")).status_code == 200
                assert not release.is_set()
                assert await task == {"error": "busy"}
                input_release.set()
                assert audit.drain()
                assert seen == [2]  # busy 판정/거부 뒤에만 입력 처리, 업무 함수는 안 돌림.
            entered.clear()
            input_release.clear()
            tool_runner._INFLIGHT = 0
            task = asyncio.create_task(tool_runner._bg(do_parse_document, encoded))
            for event in (entered, output_entered):
                await ready(event)
                assert (await client.get("/health")).status_code == 200
                assert not release.is_set()
                if event is entered:
                    input_release.set()
            release.set()
            result = await task
            assert audit.drain()
            assert result["job_id"] == "j" and rows[-1]["result_truncated"]
            args = json.loads(rows[-1]["args"])["content_b64"]
            assert args["bytes"] == 8 * 1024 * 1024
            assert args["sha256"] == hashlib.sha256(b"a" * args["bytes"]).hexdigest()

    with (
        patch.object(audit, "_input", side_effect=observed_input),
        patch.object(audit, "_body", side_effect=observed_body),
        patch.object(audit.logsink, "emit", side_effect=lambda t, r: rows.append(r)),
    ):
        try:
            asyncio.run(run())
        finally:
            input_release.set()
            release.set()
            tool_runner._LIMITER, tool_runner._INFLIGHT = None, 0


def test_bounded_receive():
    messages = [
        {"type": "http.request", "body": b"x" * 600000, "more_body": True},
        {"type": "http.request", "body": b"y" * 600000, "more_body": False},
    ]
    consumed = []

    async def inner(scope, receive, send):
        assert not consumed  # wrapper가 먼저 수신 완료까지 기다리지 않음.
        for expected in messages:
            message = await receive()
            assert message is expected  # 바이트와 more_body를 그대로 SDK에 전달.
            consumed.append(message)
        assert audit._REQUEST.get()["user_id"] == "header-user"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    class FakeMcp:
        def streamable_http_app(self):
            return inner

    async def run():
        with patch.object(main, "build", return_value=FakeMcp()), patch.object(main.health, "register"):
            app = main.build_guarded_app("127.0.0.1", 8765, "")
        iterator = iter(messages)

        async def receive():
            return next(iterator)

        async def send(message):
            pass

        # oversized 본문은 JSON 파싱을 시도하지 않는다.
        with patch.object(main.json, "loads", side_effect=AssertionError("audit parsed oversized body")):
            await app({"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"x-mcp-user", b"header-user")]}, receive, send)

    asyncio.run(run())
