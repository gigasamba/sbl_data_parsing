"""검색 스키마 0002(mc-16·mc-17, 11-01 — 등급 A DB 스키마): 한 벌 doc 표에 칸 3개 + 뷰 v_chunk_source 끝에 같은 칸.
doc_class(문서 분류 — search doc_class 거르기) · created_at(원천 등록 시각 FileStorageMap.created_at — created_since/until 거르기) ·
s3_key(원본 전체 경로 = ParsingMeta.source_key — source_system과 함께 ParsingMeta와 잇는 키, 원문 도구 docs=[경로]). pgvector에는 거르기 메타만 두고
대표 결과 위치·파싱 시각·원본 sha256은 ParsingMeta에만(사용자 11-01 — 원문 도구가 부를 때 읽음). 원천별 스키마 5벌로 나누기(pl-28·D-6)는 이 판이 아니다.
뷰는 칸을 끝에만 더하므로 CREATE OR REPLACE VIEW로 된다. 한 번 배포한 판은 고치지 않는다."""

from alembic import context, op

revision = "0002_search"
down_revision = "0001_search"
branch_labels = None
depends_on = None

SQL = """ALTER TABLE {S}.doc ADD COLUMN IF NOT EXISTS doc_class TEXT;
ALTER TABLE {S}.doc ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE {S}.doc ADD COLUMN IF NOT EXISTS s3_key TEXT;
CREATE OR REPLACE VIEW {S}.v_chunk_source AS
SELECT c.chunk_id, c.doc_id,
       d.file_path, regexp_replace(d.file_path, '^.*/', '') AS file_name,
       c.page, c.line_start, c.line_end, c.bbox, c.section, c.seq,
       c.chunk_text, d.summary, d.clients, c.source_system, c.source_system AS chunk_source_system,
       d.source_system AS doc_source_system, d.sf_acc_name, d.sf_op_id, d.sf_op_name, d.project_code__c,
       d.contract_id, d.contract_date, d.prod_name, d.division, d.service_type,
       d.doc_class, d.created_at, d.s3_key
FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id;
"""


def upgrade():
    op.get_bind().exec_driver_sql(SQL.replace("{S}", context.config.attributes["schema"]))


def downgrade():
    raise NotImplementedError("되돌리지 않음 — 칸을 지우려면 사람이(DB 담당 협의)")
