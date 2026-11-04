"""docs/operations/mcp-guide.md ↔ 코드 대조(mc-16·mc-17): 입력 표 = 도구 서명, 출력 표 = schemas/, 지원 확장자 = 엔진 구성·파싱 서비스.
안내서를 손으로 고치다 코드와 어긋나면 여기서 걸린다(PC 전용 — pipeline과 mcp_server를 함께 import)."""

import asyncio
import json
import re
from unittest.mock import patch

from common.core.paths import PROJ_ROOT, STACK_FILE
from mcp_server.schemas import evidence as EV
from mcp_server.schemas import fulltext as FT

GUIDE = (PROJ_ROOT / "docs" / "operations" / "mcp-guide.md").read_text(encoding="utf-8")


def _block(name):
    """<!-- guide:name --> … <!-- /guide:name --> 표의 첫 칸(백틱 안 이름들) 목록."""
    body = GUIDE.split(f"<!-- guide:{name} -->")[1].split(f"<!-- /guide:{name} -->")[0]
    out = []
    for ln in body.splitlines():
        if ln.startswith("| `"):
            out += re.findall(r"`([^`]+)`", ln.split("|")[1])
    return out


def _tool_params():
    """등록된 도구 이름 → 입력 칸 이름(tools/list의 inputSchema)."""
    from mcp.server.fastmcp import FastMCP

    from mcp_server.routers import edw_tools, fulltext_tool, parse_tool, search_tool

    m = FastMCP("guide-check")
    for r in (search_tool.register, edw_tools.register_query_edw, parse_tool.register, edw_tools.register_edw_meta, fulltext_tool.register):
        r(m)
    return {t.name: list(t.inputSchema["properties"]) for t in asyncio.run(m.list_tools())}


def test_inputs_match_signatures():
    tools = _tool_params()
    assert _block("search-inputs") == tools["search"], (_block("search-inputs"), tools["search"])
    assert _block("list-inputs") == tools["list_doc_fulltext"]
    assert _block("get-inputs") == tools["get_doc_fulltext"]
    for name in tools:  # 도구 6개가 모두 안내서에 있음
        assert f"`{name}`" in GUIDE, name


def test_outputs_match_schemas():
    assert _block("evidence") == list(EV.EVIDENCE_KEYS)
    assert _block("search-top") == list(EV.SEARCH_TOP_KEYS)
    lo = _block("list-output")
    assert [x.split(".")[1] for x in lo if x.startswith("batch.")] == list(FT.LIST_BATCH_KEYS)
    assert [x.split(".")[1] for x in lo if x.startswith("documents[].")] == list(FT.DOC_KEYS)
    go = " ".join(_block("get-output"))
    assert all(k in go for k in FT.GET_BATCH_KEYS), go
    assert all(f"`{r}`" in GUIDE for r in FT.SKIP_REASONS)


def _exts(label):
    line = next(ln for ln in GUIDE.splitlines() if label in ln)
    return sorted(re.findall(r"`(\.[a-z0-9]+)`", line.split(":", 1)[1] if ":" in line else line))


def test_extensions_match_code():
    stack = json.loads(STACK_FILE.read_text(encoding="utf-8"))["parse"]
    want_search = sorted({".pdf" if k.startswith(".pdf_") else k for k in stack})
    assert _exts("**검색 대상") == want_search, (_exts("**검색 대상"), want_search)
    with patch("sys.argv", ["x"]):
        from pipeline.extract.engine_stack import allowed_exts
    assert _exts("**`parse_document`가 받는 형식**") == sorted(allowed_exts())
