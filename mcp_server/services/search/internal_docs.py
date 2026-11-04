"""MCP에 노출하지 않는 내부 조회 — RDB 수집 manifest(search 근거 version). 하드 필터 문서 덤프는 11-01에 지움(mc-16 — question 필수), 집계는 mc-04 10-31에 지움. 문서 단건·그림·근거 이미지·용어·개념·문서 목록은
10-30 지움(요건 없음 — e2-18, 사용자 10-30).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)


def _manifest_by_name():
    """AD44 rdb 수집 manifest(output/parse/_source/manifest.jsonl) — doc_type·version·대체 문서·삭제 여부(RDB doc_location 메타)의
    가장 가까운 출처. 없으면 빈 dict — search 근거의 그 칸들은 None."""
    from common.core.contract import jl

    p = Path(mc.cfg().server.manifest or APP_ROOT / "output" / "parse" / "_source" / "manifest.jsonl")  # S7d — 설정 객체
    return {r["file_name"]: r for r in jl(p)} if p.exists() else {}
