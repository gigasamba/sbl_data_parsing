"""struct 스키마 표 정의(정본 — S8a, 5-4) — 이름 고정 `struct`(common/store/structdb.py STRUCT_SCHEMA). 지금 structdb.py의 DDL 글자
(SCHEMA·REGISTRY_SCHEMA·TABLE_SCHEMA — SQLite 대체도 그 글자로 만듦) 그대로: 표 10개 + doc_cell 색인 2개(D-008). structdb.py는 이 파일을
import하지 않는다(사용자 10-28 Q7 — 시험이 둘이 같은지 고정). Alembic 기준판은 migrations/versions/0001_struct_base.py.
S8b(D-031) — 판 표 2개(엔진 구성 stack_version·원천 목록 source_version — 판 0002_struct_config)는 PostgreSQL에만(PC는 파일 — SQLite 대체에
없음, CONFIG_TABLES)."""

from sqlalchemy import CHAR, Boolean, Column, DateTime, Index, Integer, MetaData, PrimaryKeyConstraint, Table, Text, false, text
from sqlalchemy.dialects.postgresql import JSONB

SCHEMA = "struct"
# 묶음(옛 ensure_* 게이트 — AD16·AD23): base = ensure_schema · registry = ensure_registry_schema · cells = ensure_table_schema
GROUPS = {
    "base": ("contract_master", "client_master", "prod_master", "doc_contract_link", "doc_location"),
    "registry": ("doc_registry", "doc_registry_seen", "doc_hidden"),
    "cells": ("doc_table", "doc_cell"),
}
TABLES = tuple(t for g in GROUPS.values() for t in g)
CONFIG_TABLES = ("stack_version", "source_version")  # S8b 판 표(엔진 구성·원천 목록) — SQLite 대체에는 없음


def struct_metadata(schema=SCHEMA):
    md = MetaData(schema=schema)
    T, I = Text, Integer  # noqa: E741 — 칸 형식 짧은 별칭(Text·Integer) — 표 정의를 한 줄씩 읽게(표 모양은 그대로)
    Table(
        "contract_master",
        md,
        Column("contract_id", T, primary_key=True),
        Column("company", T, nullable=False),
        Column("company_id", T, nullable=False),
        Column("product_code", T, nullable=False),
        Column("modality", T, nullable=False),
        Column("site", T, nullable=False),
        Column("line_id", T),
        Column("batches_contracted", I, nullable=False),
        Column("contract_value_usd", I, nullable=False),
        Column("currency", T, nullable=False),
        Column("term_months", I, nullable=False),
        Column("signed_on", T, nullable=False),
        Column("start_date", T, nullable=False),
        Column("end_date", T, nullable=False),
        Column("status", T, nullable=False),
    )
    Table("client_master", md, Column("company_id", T, primary_key=True), Column("company", T, nullable=False), Column("aliases", T))
    Table(
        "prod_master",
        md,  # 기본 키 없음(지금 DDL 그대로)
        Column("prod_code", T),
        Column("division", T),
        Column("prod_name", T),
        Column("pjt_name", T),
        Column("client_code", T),
    )
    Table(
        "doc_contract_link",
        md,
        Column("doc_key", T, primary_key=True),
        Column("contract_id", T),
        Column("score", I),
        Column("how", T),
        Column("status", T),
        Column("evidence_chunk_keys", T),
        Column("created_at", T),
    )
    Table(
        "doc_location",
        md,
        Column("doc_id", T, primary_key=True),
        Column("bucket", T),
        Column("object_key", T),
        Column("etag", T),
        Column("size_bytes", I),
        Column("content_type", T),
        Column("company_id", T),
        Column("doc_type", T),
        Column("contract_id", T),
        Column("version", I),
        Column("supersedes_doc_id", T),
        Column("language", T),
        Column("received_at", T),
        Column("updated_at", T),
        Column("is_deleted", I),
    )
    Table(
        "doc_registry",
        md,
        Column("doc_key", T, primary_key=True),
        Column("names", T),
        Column("size", I),
        Column("mtime", T),
        Column("etag", T),
        Column("status", T),
        Column("source", T),
        Column("doc_id", T),
        Column("version", T),
        Column("first_seen", T, nullable=False),
        Column("last_seen", T, nullable=False),
        Column("last_build", T, nullable=False),
        Column("rep_sha", T),
        Column("rep_pairs", T),
        Column("edition_of", T),
        Column("content_group", T),
        Column("value_changes", T),
        Column("source_keys", T),
        Column("fail_count", I),
    )
    Table(
        "doc_registry_seen",
        md,
        Column("doc_key", T, nullable=False),
        Column("build_id", T, nullable=False),
        Column("names", T),
        Column("size", I),
        Column("mtime", T),
        Column("etag", T),
        Column("status", T),
        Column("source", T),
        Column("seen_at", T, nullable=False),
        PrimaryKeyConstraint("doc_key", "build_id"),
    )
    Table(
        "doc_hidden",
        md,
        Column("doc_key", T, primary_key=True),
        Column("hidden", I, nullable=False),
        Column("reason", T),
        Column("by", T),
        Column("at", T, nullable=False),
    )
    Table(
        "doc_table",
        md,
        Column("table_key", T, primary_key=True),
        Column("doc_key", T, nullable=False),
        Column("table_id", T, nullable=False),
        Column("page", I),
        Column("source_engine", T),
        Column("n_rows", I),
        Column("n_cols", I),
        Column("header_json", T),
        Column("merged_json", T),
        Column("created_at", T, nullable=False),
    )
    cell = Table(
        "doc_cell",
        md,  # 기본 키 없음(지금 DDL 그대로)
        Column("table_key", T, nullable=False),
        Column("row_idx", I, nullable=False),
        Column("col_idx", I, nullable=False),
        Column("col_label", T),
        Column("value", T),
        Column("value_norm", T),
    )
    Index("idx_doc_cell_table", cell.c.table_key)
    Index("idx_doc_cell_value", cell.c.value_norm)
    for name in CONFIG_TABLES:  # S8b — 두 표 같은 모양(판 행은 고치지 않음 — 활성 표시·활성 기록 칸만 바뀜)
        t = Table(
            name,
            md,
            Column("version_id", Integer, primary_key=True),
            Column("name", T, nullable=False),
            Column("body", JSONB, nullable=False),
            Column("body_sha", CHAR(64), nullable=False, unique=True),
            Column("is_active", Boolean, nullable=False, server_default=false()),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
            Column("created_by", T),
            Column("reason", T),
            Column("activated_at", DateTime(timezone=True)),
            Column("activated_by", T),
        )
        Index(f"ux_{name}_active", t.c.is_active, unique=True, postgresql_where=t.c.is_active)
    return md


# 색인 이름 → pg_get_indexdef 글자(`{S}` = 스키마 — 기본 키 색인 빼고)
INDEX_DEFS = {
    "idx_doc_cell_table": "CREATE INDEX idx_doc_cell_table ON {S}.doc_cell USING btree (table_key)",
    "idx_doc_cell_value": "CREATE INDEX idx_doc_cell_value ON {S}.doc_cell USING btree (value_norm)",
}
CONFIG_INDEX_DEFS = {
    i: d
    for t in CONFIG_TABLES
    for i, d in (
        (f"{t}_body_sha_key", f"CREATE UNIQUE INDEX {t}_body_sha_key ON {{S}}.{t} USING btree (body_sha)"),
        (f"ux_{t}_active", f"CREATE UNIQUE INDEX ux_{t}_active ON {{S}}.{t} USING btree (is_active) WHERE is_active"),
    )
}
