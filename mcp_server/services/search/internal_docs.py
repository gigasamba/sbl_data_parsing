"""MCP에 노출하지 않는 내부 조회 — RDB 수집 manifest(search 근거 version)."""

from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc


def _manifest_by_name():
    """AD44 rdb 수집 manifest(output/parse/_source/manifest.jsonl) — doc_type·version·대체 문서·삭제 여부(RDB doc_location 메타)의
    가장 가까운 출처. 없으면 빈 dict — search 근거의 그 칸들은 None."""
    from common.core.contract import jl

    p = Path(mc.cfg().server.manifest or APP_ROOT / "output" / "parse" / "_source" / "manifest.jsonl")
    return {r["file_name"]: r for r in jl(p)} if p.exists() else {}
