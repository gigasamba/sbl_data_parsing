"""pl-25 — DB 스키마 명세(docs/architecture/db_schema.md)와 실제 정의가 같은지.
지금 상태(결정 칸 유지+삭제)가 gold(원천 스키마 5벌의 칸 합집합 — pl-28)는 Alembic 판(모델 common/store/db/models — 판과 같은지는 기존 dbcompare 시험이 봄)과,
ParsingMeta는 docs/operations/parsing_meta_mssql.sql과 같아야 한다(다르면 실패). 목표 상태와의 차이(새로·삭제)는 일부러 다른 것이라
목록으로 찍기만 한다. 문서가 없는 이미지(docs/ 미포함)에서는 건너뜀."""

import re

from common.core.paths import DEPLOY_ROOT
from common.store import parsing_meta_db as PM
from common.store.db import dbcompare

ROOT = DEPLOY_ROOT  # 저장소 루트(PC) · 이미지 /app/deploy — paths 상수
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
        if line.startswith("#"):
            cur = None  # 다른 머리글 아래 표는 어느 표에도 안 붙임
        if cur is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[-1] in DECISIONS:
            cur[cells[0].strip("`")] = cells[-1]
    return out


def _pm_columns():
    """parsing_meta_mssql.sql의 CREATE TABLE [AI].[ParsingMeta] 칸 이름."""
    body = PM_SQL.read_text(encoding="utf-8").split("CREATE TABLE [AI].[ParsingMeta] (", 1)[1].split("\n);", 1)[0]
    return {m.group(1) for m in re.finditer(r"^\s+(\w+)\s", body, re.M) if m.group(1) != "CONSTRAINT"}


def _actual():
    """gold = dbcompare.expected(판 비교 시험과 같은 모델 — 차원은 칸 이름과 무관) · ParsingMeta = DDL 파일."""
    from common.store.db.models import search_tables as ST

    cols = {}
    for src in ST.SOURCES:  # 원천 스키마 5벌의 같은 표 이름은 칸을 합쳐서(원천 전용 칸은 문서의 "원천" 칸에 적음)
        for t in dbcompare.expected("search", ST.src_schema("ai", src), 1024)[0].tables.values():
            cols.setdefault(f"gold.{t.name}", set()).update(c.name for c in t.columns)
    cols["edw.ParsingMeta"] = _pm_columns()
    return cols


def test_schema_doc_matches():
    if not DOC.is_file() or not PM_SQL.is_file():
        print("[시험] 건너뜀 — docs/가 없음(이미지)")
        return
    doc, actual = _doc_tables(), _actual()
    assert set(PM.COLUMNS) <= actual["edw.ParsingMeta"], (
        f"코드가 쓰는 ParsingMeta 칸이 DDL에 없음: {sorted(set(PM.COLUMNS) - actual['edw.ParsingMeta'])}"
    )
    missing = sorted(set(actual) - set(doc))
    assert not missing, f"문서에 없는 표: {missing}"
    stale = sorted(
        n for n, cols in doc.items() if n.split(".")[0] == "gold" and n not in actual and any(d != "새로" for d in cols.values())
    )
    assert not stale, f"문서에는 지금 있다는데 정의에 없는 표: {stale}"
    for name, real in sorted(actual.items()):
        now = {c for c, d in doc[name].items() if d != "새로"}
        assert now == real, f"{name} — 문서의 지금 칸과 실제가 다름: 문서에만 {sorted(now - real)} · 실제에만 {sorted(real - now)}"
    from common.store.db.models.master_tables import master_metadata  # 마스터 표(§4, 결정 모두 새로)는 칸 전부를 모델과 대조

    for tbl in master_metadata("m").tables.values():
        name = f"master.{tbl.name}"
        assert name in doc, f"문서에 없는 마스터 표: {name}"
        assert set(doc[name]) == {c.name for c in tbl.columns}, (
            f"{name} — 문서 칸 {sorted(doc[name])} · 모델 칸 {sorted(c.name for c in tbl.columns)}"
        )
    targets = []
    for name, cols in sorted(doc.items()):
        new = sorted(c for c, d in cols.items() if d == "새로")
        gone = sorted(c for c, d in cols.items() if d == "삭제")
        if new or gone:
            targets.append(f"{name}: 새로 {new} · 삭제 {gone}")
    print("[시험] 지금 상태 일치 — 목표 상태와의 차이(설계안, 승인 전):\n  " + "\n  ".join(targets))
