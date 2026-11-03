"""query_edw·edw_meta 도구 등록 — 서비스(do_query_edw·do_edw_meta)를 스레드 창구(_bg)로 부르기만.
등록 순서가 tools/list 순서라 두 함수로 나눔(main.build()가 search · query_edw · parse_document · edw_meta 순으로 부름).
S5(10-26, refactor_plan 5-1 routers/ — 코디네이터 답 Q5 a)에 mcp_server/main.py build() 안에서 옮김 — 함수 이름·독스트링·서명·
반환 형식은 MCP 도구 계약(🔒 CLAUDE.md 3절 — tools/list 바이트가 같아야 함)이라 글자 그대로 둔다(들여쓰기까지).
"""

from mcp_server.routers.dispatch import _bg
from mcp_server.schemas.edw_result import QueryResult as _EdwQueryResult  # module-level import so query_edw's

# TypedDict return annotation resolves (FastMCP reads it from the function's module globals for outputSchema, EQ1).
from mcp_server.services.edw_calls import do_edw_meta, do_query_edw


def register_query_edw(m):
    @m.tool()
    async def query_edw(sql: str, max_rows: int = 1000) -> _EdwQueryResult:
        """Read-only SQL against EDW (EQ1) — exactly one SELECT/WITH statement, tables limited to the
        EDW_QUERY_TABLES allowlist, no DML/DDL/exec keywords anywhere (rejected even inside a comment).
        max_rows is capped by EDW_QUERY_MAX_ROWS (default 1000). Returns raw rows only (no summarization —
        do that yourself): {ok, columns:[{name,type}], rows, row_count, truncated, elapsed_ms, dialect,
        source, error}. rows is a list of value lists in column order (JSON, not markdown). type is one of
        int|float|decimal|str|date|datetime|time|bool|binary|unknown; a "decimal" value with a fraction is an
        exact string (e.g. "12.50") — parse it as a number, never round it through float. Dates are ISO
        strings. truncated=true means more rows exist: narrow the query or aggregate in SQL.
        Tables are limited to the EDW_QUERY_TABLES allowlist — only those can be queried."""
        return await _bg(do_query_edw, sql, max_rows)


def register_edw_meta(m):
    @m.tool()
    async def edw_meta(schema: str | None = None, table: str | None = None, column_filter: str | None = None) -> dict:
        """Rule-based 3-level lookup of EDW table/column metadata (Korean descriptions, domain tags,
        inventory stats) from a PII-sanitized static dataset as-of the build date (2026-10-22 user
        decision — no vector search, no embedding, no LLM calls, no live DB; the single-column view
        and the `query` keyword search were removed by the user).
        - No args: schema summary (5 schemas, table/column counts, excluded-BCMS note) plus
          `search_attrs`: per source_system, the `search` attrs keys — {filter: {filter name: attrs key}, evidence: [keys]}.
        - `schema` only: ALL tables of that schema, column list EXCLUDED — name, Korean description,
          row_count, data_period, column_count, qualified_name.
        - `schema`+`table`: table meta + FULL column list with Korean descriptions (type, nullability,
          PK/FK, domain tags). `column_filter` (case-insensitive substring on the column name) narrows
          wide tables (Account 172 cols).
        Keys tolerate case and trailing spaces (`BSCM`/`mst_stock_mgt `). `table` without `schema`
        resolves when unique across schemas. Unknown names return {'error': ..., 'suggestions': [...]}
        via difflib; a missing dataset/tool file returns {'error': ...} instead of breaking this
        server's other tools. sample_values are never returned (PII policy at build time).
        Use `qualified_name` from results when composing SQL for `query_edw`."""
        return await _bg(do_edw_meta, schema, table, column_filter)
