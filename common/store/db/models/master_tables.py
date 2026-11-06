"""마스터 표 정본(pl-38·op-17) — 스키마 `<PG_SCHEMA>_master`, 표 `glossary` 하나(melt — 유사값마다 한 줄).
원본은 git `resources/vocab/glossary/glossary.csv`(칸 = CSV 머리글 그대로, 모두 글자 + 파일 순서 `row_no`).
`dbtool master load`가 CSV로 내용을 통째로 바꾼다. 내용 해시는 읽을 때 계산한다(common.store.master).
CSV 머리글을 바꾸면 새 Alembic 판으로 칸을 바꾼다(판 0002_master는 이 표를 import하지 않고 칸을 굳혀 둠 — 시험이 대조)."""

from sqlalchemy import Column, Integer, MetaData, Table, Text

TABLE = "glossary"
COLS = ("kind", "canonical", "variant", "variant_kind", "description", "context_required", "case_sensitive")


def master_metadata(schema):
    md = MetaData(schema=schema)
    Table(TABLE, md, Column("row_no", Integer, primary_key=True, autoincrement=False), *(Column(c, Text) for c in COLS))
    return md


def index_defs():
    return {}
