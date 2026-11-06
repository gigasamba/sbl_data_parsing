"""검색 스키마 0006(op-17, 사용자 11-06 — 등급 A DB 스키마): 처리 기록을 EDW `AI.ParsingMeta` 대신 원천 스키마 5벌의 doc에 둔다.
더하는 칸(모두 NULL 허용): `sha256`(원본 sha256 — 내용 중복 판정) · `silver_bucket`·`silver_key`(게시한 대표 결과 객체) · `engines`(돈 엔진 전부 JSON,
대표는 role "rep") · `parse_status`(ok·partial) · `silver_version`·`gold_version`(게시·적재한 코드 판) · `parsed_at`(게시 시각) · `loaded_at`(적재 시각).
있는 행은 NULL로 남는다(서버의 옛 ParsingMeta 기록은 사람이 옮김 — refactor.md). 검색 뷰 v_chunk_source는 그대로(MCP 출력 계약).
칸은 common/store/db/models/search_tables.py DOC_RECORD와 같은 글자로 굳혀 둔다(시험이 대조). 되돌리기는 칸을 지운다."""

from alembic import context, op

revision = "0006_search"
down_revision = "0005_search"
branch_labels = None
depends_on = None

SOURCES = ("sfdc", "crms", "las", "faq", "other")
DOC_RECORD = (
    "sha256 TEXT, silver_bucket TEXT, silver_key TEXT, engines JSONB, parse_status TEXT, silver_version TEXT, gold_version TEXT, "
    "parsed_at TIMESTAMP WITH TIME ZONE, loaded_at TIMESTAMP WITH TIME ZONE"
)
DOC_RECORD_COLS = [c.split()[0] for c in DOC_RECORD.split(", ")]


def upgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    adds = ", ".join(f"ADD COLUMN IF NOT EXISTS {c}" for c in DOC_RECORD.split(", "))
    for src in SOURCES:
        bind.exec_driver_sql(f"ALTER TABLE {b}_{src}.doc {adds}")


def downgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    drops = ", ".join(f"DROP COLUMN IF EXISTS {c}" for c in DOC_RECORD_COLS)
    for src in SOURCES:
        bind.exec_driver_sql(f"ALTER TABLE {b}_{src}.doc {drops}")
