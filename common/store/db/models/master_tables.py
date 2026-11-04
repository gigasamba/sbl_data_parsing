"""마스터 표 정본(pl-38) — 스키마 `<PG_SCHEMA>_master`. 원본은 git `resources/vocab/glossary/*.csv`(CSV 하나 = 표 하나 —
칸은 CSV 머리글 그대로, 모두 글자 + 파일 순서 `row_no`). `dbtool master load`가 CSV로 내용을 통째로 바꾸고 내용 해시를 `master_meta`에 적는다.
CSV 머리글을 바꾸면 새 Alembic 판으로 칸을 바꾼다(판 0001_master는 이 표를 import하지 않고 칸을 굳혀 둠 — 시험이 대조)."""

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text

TABLES = {
    "client_roster": (
        "client_id", "canonical_name", "name_ko", "aliases", "client_type", "segment",
        "country", "parent_client_id", "status", "description", "source", "updated",
    ),
    # client_master·contract_master·units — 지금 앱에서 읽는 곳은 없다(여섯 파일 모두 PG에 둠 — 내용 해시·gold_version에는 들어감,
    # 원본 CSV는 gen_roster 등 오프라인 도구가 그대로 읽음). 읽는 곳이 생기면 Master.rows(<표>)로.
    "client_master": ("company_id", "company", "aliases"),
    "contract_master": (
        "contract_id", "company", "company_id", "product_code", "modality", "site", "line_id", "batches_contracted",
        "contract_value_usd", "currency", "term_months", "signed_on", "start_date", "end_date", "status",
    ),
    "domain_terms": (
        "concept_id", "canonical", "category", "synonyms", "abbreviations", "weak_synonyms", "broader", "related",
        "context_required", "case_sensitive", "definition_ko", "definition_en", "source", "owner", "status", "updated",
    ),
    "id_patterns": ("id_type", "regex", "example", "note", "updated"),
    "units": ("canonical", "variants", "quantity", "equivalent_to", "note", "updated"),
}  # fmt: skip
META = "master_meta"


def master_metadata(schema):
    md = MetaData(schema=schema)
    for name, cols in TABLES.items():
        Table(name, md, Column("row_no", Integer, primary_key=True, autoincrement=False), *(Column(c, Text) for c in cols))
    Table(
        META,
        md,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("hash", Text),
        Column("loaded_at", DateTime(timezone=True)),
    )
    return md


def index_defs():
    return {}
