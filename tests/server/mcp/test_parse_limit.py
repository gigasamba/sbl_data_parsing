"""parse_document 크기 상한(사용자 11-03, 기본 100MB) — 검색 MCP 쪽: 상한을 넘는 content_b64는 서비스로 보내지 않고 이유를 돌려주며,
HTTP 본문 상한(SDK 기본 4MiB)은 base64 크기에 맞춰 올린다. 상한은 1MB로 덮어 작은 데이터로 본다(외부 접속 없음)."""

import asyncio
import base64
import json
from unittest.mock import patch

import httpx

from common.config.settings import COMMON
from mcp_server import main
from mcp_server.routers import tool_runner
from mcp_server.services import parse_proxy

MB = 1048576


def _b64(n):
    return base64.b64encode(b"x" * n).decode()


def _stub(sent):
    def fake(method, path, payload=None, timeout=10):
        sent.append((method, path))
        return {"job_id": "j1"} if method == "POST" else {"status": "done", "result": {"text": "ok"}}

    return fake


def test_proxy_limit():
    with COMMON.env(PARSE_MCP_MAX_MB="1"):
        assert parse_proxy.max_bytes() == MB and parse_proxy.body_cap() == MB * 3 // 2 + MB
        sent: list = []
        with patch.object(parse_proxy, "_parse_service", _stub(sent)):  # 완료까지 폴링 1회(1초)
            ok = parse_proxy.do_parse_document(content_b64=_b64(int(0.9 * MB)), filename="a.txt")
            assert ok == {"text": "ok", "status": "done"} and sent[0] == ("POST", "/jobs"), (ok, sent)
            sent.clear()
            big = parse_proxy.do_parse_document(content_b64=_b64(int(1.1 * MB)), filename="a.txt")
            assert "크기 상한(1MB)" in big["error"] and "1.1MB" in big["error"] and not sent, (big, sent)
            exact = parse_proxy.do_parse_document(content_b64=_b64(MB), filename="a.txt")  # 딱 상한은 받음(패딩 '=' 셈 제외)
            assert exact.get("status") == "done", exact
            mime = base64.encodebytes(b"x" * MB).decode()  # 76자마다 줄바꿈 — 줄바꿈은 크기에 안 셈
            assert parse_proxy.do_parse_document(content_b64=mime, filename="a.txt").get("status") == "done"


def test_http_body_cap():
    """HTTP 길 끝까지 — 본문 상한이 SDK 기본(4MiB)이 아니라 설정에서 오고, 1.1MB 파일은 413이 아니라 도구가 이유를 답한다.
    큰 본문은 동시 2개 자리 하나를 쥐고 처리된다(PR #110 — 기준을 1000바이트로 낮춰 봄)."""
    assert main.build("127.0.0.1", 8765).settings.max_request_body_size == parse_proxy.body_cap() > 133 * MB  # 기본 100MB의 base64

    async def call(client, n):
        args = {"content_b64": _b64(n), "filename": "a.txt", "time_out_threshold": 5}
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "parse_document", "arguments": args}}
        r = await client.post("/mcp", json=payload)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return json.loads(r.json()["result"]["content"][0]["text"])

    async def run():
        app_main = main.build("127.0.0.1", 8765)
        with patch.object(main, "build", return_value=app_main):
            app = main.build_guarded_app("127.0.0.1", 8765, "")
        holder.append(app.big_slots)
        headers = {"Accept": "application/json, text/event-stream"}
        async with (
            app_main.session_manager.run(),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765", headers=headers) as client,
        ):
            assert (await call(client, int(0.9 * MB))).get("status") == "done"
            assert "크기 상한(1MB)" in (await call(client, int(1.1 * MB)))["error"]

    sent: list = []
    holder: list = []
    free: list = []
    stub = _stub(sent)

    def watched(method, path, payload=None, timeout=10):
        free.append(holder[0].value)
        return stub(method, path, payload, timeout)

    with COMMON.env(PARSE_MCP_MAX_MB="1"), patch.object(parse_proxy, "_parse_service", watched), patch.object(main, "_BIG_BODY", 1000):
        try:
            asyncio.run(run())
        finally:
            tool_runner._LIMITER = None
    assert [m for m, _ in sent].count("POST") == 1, sent  # 1.1MB는 서비스로 안 감
    assert free and set(free) == {main._BIG_SLOTS - 1}, free  # 처리 중엔 자리 하나를 쥠
    assert holder[0].value == main._BIG_SLOTS  # 끝나면 돌려줌
