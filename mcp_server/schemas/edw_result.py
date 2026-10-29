"""query_edw 도구 출력 모양(MCP 계약 — FastMCP가 이 TypedDict로 outputSchema를 만든다, EQ1). 바꾸지 않는다.
S5(10-26, refactor_plan 5-1 schemas/)에 mcp_server/services/edw_query.py(옛 data_retrieval/tools/edw_query.py)에서 옮김 — 내용 그대로.
"""

from typing import TypedDict


class ColumnMeta(TypedDict):
    name: str
    type: str


class QueryResult(TypedDict):
    ok: bool
    columns: list
    rows: list
    row_count: int
    truncated: bool
    elapsed_ms: float
    dialect: str
    source: str
    error: str | None
