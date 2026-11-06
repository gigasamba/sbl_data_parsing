"""검색 스키마 0007(op-17, 사용자 11-06 — 등급 A DB 스키마): 원천 스키마 5벌(+ DEV 원천)의 doc에 찾기용 btree 색인 3개를 더한다.
doc에는 기본 키(doc_id)와 attrs GIN(판 0005) 말고 색인이 없어 처리 기록·원본 경로로 찾는 질의가 표 전체를 읽었다 — `sha256`(내용 중복 판정),
`silver_bucket, silver_key`(게시한 대표 결과 위치), `file_path`(게시·--skip-done 끝난 문서·get_doc_fulltext가 원본 경로로 찾음).
색인 글자는 common/store/db/models/search_tables.py index_defs와 같은 이름·칸으로 굳혀 둔다(시험이 대조). 되돌리기는 색인을 지운다."""

from alembic import context, op

from common.store.db.migrations import search_parts

revision = "0007_search"
down_revision = "0006_search"
branch_labels = None
depends_on = None

SOURCES = ("sfdc", "crms", "las", "faq", "other")
DOC_INDEX = {"doc_sha256": ("sha256",), "doc_silver": ("silver_bucket", "silver_key"), "doc_path": ("file_path",)}  # 이름 ix_{S}_<키> → 칸
PG_NAME_MAX = 63  # PostgreSQL 이름 길이(바이트) — 넘으면 조용히 잘려 두 색인 이름이 같아짐


def upgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    for src in search_parts.sources(SOURCES):
        s = f"{b}_{src}"
        for name, cols in DOC_INDEX.items():
            ix = f"ix_{s}_{name}"
            if len(ix.encode()) > PG_NAME_MAX:
                raise SystemExit(f"색인 이름 {ix}이 {PG_NAME_MAX}바이트를 넘음 — 기준 스키마 이름을 줄인다")
            bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {ix} ON {s}.doc ({', '.join(cols)})")


def downgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    for src in search_parts.sources(SOURCES):
        s = f"{b}_{src}"
        for name in DOC_INDEX:
            bind.exec_driver_sql(f"DROP INDEX IF EXISTS {s}.ix_{s}_{name}")
