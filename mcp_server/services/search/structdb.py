"""검색 MCP(mcp_server) 전용 정형 저장소 조회(10-14 함수별 분리 — common/store/structdb.py에서 이전, 로직 바이트 동일).
근거 MCP(aggregate.py)만 쓴다(연결·스키마·find_table_cells 등은 common.store.structdb 그대로)."""


def find_table_row(db, table_key, row_idx):
    """AD23 leftover — find_table_cells가 찾은 칸 하나와 같은 행의 칸 전부(머리글 포함) — 표 칸 질문 근거로
    '그 행 전체'를 보여줄 때 씀(예: 배치 BT-0137 행에서 '수량' 칸을 찾으려면 그 행 다른 칸도 봐야 함).
    안정 정렬: col_idx. 없으면 빈 목록."""
    try:
        rows = db.query("SELECT col_idx, col_label, value FROM doc_cell WHERE table_key=? AND row_idx=?", (table_key, row_idx))
    except Exception:
        return []
    rows.sort(key=lambda r: r["col_idx"])
    return rows
