"""MCP 도구 등록(routers). TOOL_NAMES = 노출 도구 이름과 tools/list 순서(MCP 계약) — main.build()가 이 순서로 등록하고
(tests/server/mcp/test_mcp_main.py가 대조), 바깥 점검 mcp_smoke가 기대 목록으로 쓴다. 가벼운 import만(호스트 python에서도 읽힘)."""

TOOL_NAMES = ("search", "query_edw", "parse_document", "edw_meta", "list_doc_fulltext", "get_doc_fulltext")
