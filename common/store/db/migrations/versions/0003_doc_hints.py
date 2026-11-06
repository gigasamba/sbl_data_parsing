"""검색 스키마 0003(pl-33, 사용자 11-02 — 등급 A DB 스키마): 분류 힌트 doc 칸을 더한다. `<기준>_sfdc.doc`에 운영 분류가 쓰던 SFDC 근거
(제목·첫 User 아닌 연결 개체·Task/Event 방향과 제목·영업 기회 단계와 RFP 기간), `<기준>_las.doc`에 품의 제목. 적재 때 edw_meta가 EDW에서
채운다. 칸 이름 = 원본 칸 이름의 소문자. 검색 뷰 v_chunk_source는 그대로(힌트는 검색에 안 씀). 칸은 common/store/db/models/search_tables.py
DOC_HINTS와 같은 글자로 굳혀 둔다(한 번 배포한 판은 고치지 않음). 있는 행은 NULL로 남는다 — 이미 라벨이 있는 문서는 다시 분류하지 않으므로
힌트가 필요 없다. 되돌리기 없음."""

from alembic import context, op

from common.store.db.migrations import search_parts

revision = "0003_search"
down_revision = "0002_search"
branch_labels = None
depends_on = None

DOC_HINTS = {  # 원천 → 더하는 doc 칸(이 판의 정의 — 모델 DOC_HINTS와 같음)
    "sfdc": "title TEXT, entity_type TEXT, entity_class TEXT, entity_id TEXT, sent_received__c TEXT, subject TEXT, stagename TEXT, "
    "real_rfp__c TEXT, rfp_received_start_date__c DATE, rfp_received_end_date__c DATE",
    "las": "approvalname TEXT",
}
DOC_HINTS_COLS = {k: [c.split()[0] for c in v.split(", ")] for k, v in DOC_HINTS.items()}


def upgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    for src in search_parts.sources(tuple(DOC_HINTS)):
        cols = DOC_HINTS.get(src)
        if not cols:  # DEV 원천 실행(op-17) — 힌트 칸 없음
            continue
        adds = ", ".join(f"ADD COLUMN IF NOT EXISTS {c}" for c in cols.split(", "))
        bind.exec_driver_sql(f"ALTER TABLE {b}_{src}.doc {adds}")


def downgrade():
    raise NotImplementedError("되돌리지 않음 — 칸을 지우려면 DB 담당 협의 뒤 새 판")
