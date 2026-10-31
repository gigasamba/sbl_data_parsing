"""struct 스키마 표 정의(정본 — S8a, 5-4) — 이름 고정 `struct`. 판 표 2개(엔진 구성 stack_version·원천 목록 source_version — S8b D-031,
판 0002_struct_config)만 남는다 — PostgreSQL에만(PC는 파일). 기준판 0001_struct_base의 나머지 표 10개(정형 표·문서 대장·표 칸)는
판 0003_struct_drop이 지운다(pl-08·pl-12 C10, 사용자 10-31·11-01)."""

from sqlalchemy import CHAR, Boolean, Column, DateTime, Index, Integer, MetaData, Table, Text, false, text
from sqlalchemy.dialects.postgresql import JSONB

SCHEMA = "struct"
CONFIG_TABLES = ("stack_version", "source_version")  # S8b 판 표(엔진 구성·원천 목록)


def struct_metadata(schema=SCHEMA):
    md = MetaData(schema=schema)
    for name in CONFIG_TABLES:  # S8b — 두 표 같은 모양(판 행은 고치지 않음 — 활성 표시·활성 기록 칸만 바뀜)
        t = Table(
            name,
            md,
            Column("version_id", Integer, primary_key=True),
            Column("name", Text, nullable=False),
            Column("body", JSONB, nullable=False),
            Column("body_sha", CHAR(64), nullable=False, unique=True),
            Column("is_active", Boolean, nullable=False, server_default=false()),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
            Column("created_by", Text),
            Column("reason", Text),
            Column("activated_at", DateTime(timezone=True)),
            Column("activated_by", Text),
        )
        Index(f"ux_{name}_active", t.c.is_active, unique=True, postgresql_where=t.c.is_active)
    return md


# 색인 이름 → pg_get_indexdef 글자(`{S}` = 스키마 — 기본 키 색인 빼고)
CONFIG_INDEX_DEFS = {
    i: d
    for t in CONFIG_TABLES
    for i, d in (
        (f"{t}_body_sha_key", f"CREATE UNIQUE INDEX {t}_body_sha_key ON {{S}}.{t} USING btree (body_sha)"),
        (f"ux_{t}_active", f"CREATE UNIQUE INDEX ux_{t}_active ON {{S}}.{t} USING btree (is_active) WHERE is_active"),
    )
}
