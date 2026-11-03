"""PC 검증 UI가 MCP 연결에 test/test 감사 헤더를 전달한다(네트워크 없음)."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

import mcp
from mcp.client import streamable_http

from common.config import settings


def test_ui_headers():
    with settings.isolated(PG_SCHEMA="ai"):  # serve.py가 import 때 스키마 이름을 요구한다(시험 전용 설정에는 없음)
        from validation.search_ui import serve

    seen = []

    @asynccontextmanager
    async def transport(url, headers):
        seen.append(headers)
        yield None, None, None

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            return None

    async def call(session):
        assert isinstance(session, Session)
        return "called"

    with patch.object(streamable_http, "streamablehttp_client", transport), patch.object(mcp, "ClientSession", Session):
        assert asyncio.run(serve._mcp(call)) == "called"
    assert len(seen) == 1
    assert seen[0]["X-MCP-Client"] == seen[0]["X-MCP-User"] == "test"


def test_ui_sends_source():
    """검색 페이지의 search 호출에 source_system(필수 — search_svc G20)이 있고, 고르는 값이 다섯 원천과 같다."""
    import re

    from common.core.paths import DEPLOY_ROOT
    from common.store.db.models.search_tables import SOURCES

    html = (DEPLOY_ROOT / "validation" / "search_ui" / "index.html").read_text(encoding="utf-8")
    assert 'source_system: $("source").value' in html
    sel = re.search(r'<select id="source">(.*?)</select>', html, re.S)
    assert sel, "원천 고르기 없음"
    assert [v.lower() for v in re.findall(r'value="([^"]+)"', sel.group(1))] == list(SOURCES)
