"""pl-25 — DB 스키마 명세(docs/architecture/db_schema.md)와 실제 정의가 같은지.
지금 상태(결정 칸 유지+삭제)가 gold·struct는 Alembic 판(모델 common/store/db/models — 판과 같은지는 기존 dbcompare 시험이 봄)과,
ParsingMeta는 docs/operations/parsing_meta_mssql.sql과 같아야 한다(다르면 실패). 목표 상태와의 차이(새로·삭제)는 일부러 다른 것이라
목록으로 찍기만 한다. 문서가 없는 이미지(docs/ 미포함)에서는 건너뜀."""

import re
from pathlib import Path

from common.store.db.models import struct_tables as ST
from common.store.db.models.search_tables import search_metadata

ROOT = Path(__file__).resolve().parents[3]  # 저장소 루트(tests/server/common/ 위)
DOC = ROOT / "docs" / "architecture" / "db_schema.md"
PM_SQL = ROOT / "docs" / "operations" / "parsing_meta_mssql.sql"
DECISIONS = ("유지", "삭제", "새로")


def _doc_tables():
    """### <db>.<표> 아래 표의 (칸, 결정) — {"gold.doc": {"doc_id": "유지", ...}}."""
    out, cur = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^### (\w+)\.(\w+)\s*$", line)
        if m:
            cur = out.setdefault(f"{m.group(1)}.{m.group(2)}", {})
            continue
        if line.startswith("## "):
            cur = None
        if cur is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[-1] in DECISIONS:
            cur[cells[0].strip("`")] = cells[-1]
    return out


def _pm_columns():
    """parsing_meta_mssql.sql의 CREATE TABLE [AI].[ParsingMeta] 칸 이름."""
    body = PM_SQL.read_text(encoding="utf-8").split("CREATE TABLE [AI].[ParsingMeta] (", 1)[1].split("\n);", 1)[0]
    return {m.group(1) for m in re.finditer(r"^\s{4}(\w+)\s+(?!--)", body, re.M) if m.group(1) != "CONSTRAINT"}


def _actual():
    cols = {f"gold.{t.name}": {c.name for c in t.columns} for t in search_metadata("ai", 1024).tables.values()}
    cols |= {f"struct.{t.name}": {c.name for c in t.columns} for t in ST.struct_metadata().tables.values()}
    cols["edw.ParsingMeta"] = _pm_columns()
    return cols


def test_schema_doc_matches():
    if not DOC.is_file() or not PM_SQL.is_file():
        print("[시험] 건너뜀 — docs/가 없음(이미지)")
        return
    doc, actual = _doc_tables(), _actual()
    missing = sorted(set(actual) - set(doc))
    assert not missing, f"문서에 없는 표: {missing}"
    for name, real in sorted(actual.items()):
        now = {c for c, d in doc[name].items() if d != "새로"}
        assert now == real, f"{name} — 문서의 지금 칸과 실제가 다름: 문서에만 {sorted(now - real)} · 실제에만 {sorted(real - now)}"
    targets = []
    for name, cols in sorted(doc.items()):
        new = sorted(c for c, d in cols.items() if d == "새로")
        gone = sorted(c for c, d in cols.items() if d == "삭제")
        if new or gone:
            targets.append(f"{name}: 새로 {new} · 삭제 {gone}")
    print("[시험] 지금 상태 일치 — 목표 상태와의 차이(설계안, 승인 전):\n  " + "\n  ".join(targets))
