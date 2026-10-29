"""근거(evidence) 칸 목록 — search 응답 근거 한 건의 기본 칸과 RDB 문서 위치 메타(AD44)가 있을 때만 붙는 칸(MCP 계약 — 바꾸지 않음).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
"""

_EVIDENCE_BASE_KEYS = {
    "chunk_id",
    "chunk_key",
    "doc_key",
    "doc_id",
    "source_uri",
    "file_path",
    "file_name",
    "page",
    "line",
    "bbox",
    "section",
    "text",
    "doc_summary",
    "client",
    "contract_no",
    "score",
    "via",
    "rank",
    "image_ids",
    "doc_date",
    "version",
    "superseded",
}
_MANIFEST_EXTRA_KEYS = {"doc_type", "supersedes_doc_id", "is_deleted", "contract_id", "updated_at", "company"}
