"""검색 스키마 0004(mc-19, 사용자 11-03 — 등급 A DB 스키마): 검색이 묶음 파일(meta.json·docs.jsonl) 없이 PG만 읽게 한다.
원천 스키마 5벌의 doc에 `content_date`(문서에 적힌 날짜 — created_at(원천 등록 시각)과 다름. 구조화 docmeta가 본문·파일 이름에서 찾은 ISO 글자 YYYY-MM-DD·YYYY-MM·YYYY, 검색 근거
칸)와 `embed_model`(그 문서를 임베딩한 모델 이름 — 검색의 질의 모델 확인, 나중 guard가 문서 단위로 판단)을 더하고, corpus_stat의 `dim`을
지운다(차원은 chunk.embedding 칸 형식 vector(n)에 이미 고정). 적재가 채운다 — 있는 행은 NULL로 남으니 0.2.0은 전체 다시 적재.
검색 뷰 v_chunk_source는 그대로(MCP 출력 계약). 칸은 common/store/db/models/search_tables.py DOC_META와 같은 글자로 굳혀 둔다. 되돌리기 없음."""

from alembic import context, op

from common.store.db.migrations import search_parts

revision = "0004_search"
down_revision = "0003_search"
branch_labels = None
depends_on = None

SOURCES = ("sfdc", "crms", "las", "faq", "other")
DOC_META = "content_date TEXT, embed_model TEXT"  # 5벌 모두 같은 칸(이 판의 정의 — 모델 DOC_META와 같음)
DOC_META_COLS = [c.split()[0] for c in DOC_META.split(", ")]


def upgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    adds = ", ".join(f"ADD COLUMN IF NOT EXISTS {c}" for c in DOC_META.split(", "))
    for src in search_parts.sources(SOURCES):
        bind.exec_driver_sql(f"ALTER TABLE {b}_{src}.doc {adds}")
        bind.exec_driver_sql(f"ALTER TABLE {b}_{src}.corpus_stat DROP COLUMN IF EXISTS dim")


def downgrade():
    raise NotImplementedError("되돌리지 않음 — 칸을 지우려면 DB 담당 협의 뒤 새 판")
