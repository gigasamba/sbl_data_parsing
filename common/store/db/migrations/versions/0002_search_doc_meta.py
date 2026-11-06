"""검색 스키마 0002(pl-28·mc-16·mc-17, 사용자 11-01·11-02 — 등급 A DB 스키마): 원천 시스템별 스키마 5벌로 나눈다.
기준 스키마(PG_SCHEMA, 예 `ai`)에는 Alembic 판 표와 공용 doc_id 시퀀스만 남기고, `<기준>_sfdc`·`_crms`·`_las`·`_faq`·`_other`마다 같은 표
doc·chunk·chunk_term·term_stat·corpus_stat + 뷰 v_chunk_source(원천 전용 칸만 다름)를 만든다. 0001이 기준 스키마에 만든 한 벌 표(load_run 포함)는
지운다 — 0.2.0은 전체 다시 적재(사용자 10-31, D-6 — DB 담당자 승인·백업 뒤). 칸은 common/store/db/models/search_tables.py와 같은 글자로 굳혀 둔다
(한 번 배포한 판은 고치지 않음 — 그 뒤 칸이 바뀌면 새 판). 되돌리기 없음.
DEV 원천 스키마(op-17): attributes sources = (dev_<n>,)이면 그 스키마만 만든다(Other와 같은 칸 — 기준 스키마의 옛 표 지우기·시퀀스는 건너뜀)."""

from alembic import context, op

from common.store.db.migrations import search_parts

revision = "0002_search"
down_revision = "0001_search"
branch_labels = None
depends_on = None

HNSW_MAX = 2000  # common.store.pg.HNSW_MAX(이 판을 만들 때 값)
SOURCES = ("sfdc", "crms", "las", "faq", "other")
DOC_EXTRA = {  # 원천 전용 doc 칸(이 판의 정의 — 모델 DOC_EXTRA와 같음, EDW 조인 사슬 — db_schema §1 원천별 표)
    "sfdc": "doc_class TEXT, sf_op_id TEXT, sf_op_name TEXT, project_code__c TEXT, service_type TEXT, contract_date DATE",
    "crms": "division TEXT, prod_name TEXT, contract_id TEXT, contract_date DATE",
    "las": "doc_class TEXT, contract_id TEXT, contract_date DATE",
    "faq": "",
    "other": "",
}
DOC_EXTRA_COLS = {k: [c.split()[0] for c in v.split(", ")] if v else [] for k, v in DOC_EXTRA.items()}
CHUNK_EXTRA = {"faq": "faq_group TEXT"}

DROP_OLD = """DROP VIEW IF EXISTS {B}.v_chunk_source;
DROP TABLE IF EXISTS {B}.chunk_term, {B}.term_stat, {B}.corpus_stat, {B}.chunk, {B}.doc, {B}.load_run CASCADE;
CREATE SEQUENCE IF NOT EXISTS {B}.doc_id_seq;
"""

SRC_SQL = """CREATE SCHEMA IF NOT EXISTS {S};
CREATE TABLE IF NOT EXISTS {S}.doc (
    doc_id      INT PRIMARY KEY DEFAULT nextval('{B}.doc_id_seq'::regclass),
    file_path   TEXT NOT NULL,
    summary     TEXT,
    created_at  TIMESTAMPTZ,
    client_edw  TEXT,
    clients_doc TEXT{DOC_EXTRA}
);
CREATE TABLE IF NOT EXISTS {S}.chunk (
    chunk_id    SERIAL PRIMARY KEY,
    doc_id      INT NOT NULL REFERENCES {S}.doc(doc_id) ON DELETE CASCADE,
    seq         INT NOT NULL,
    page        INT,
    line_start  INT,
    line_end    INT,
    bbox        VARCHAR(80),
    section     TEXT,
    chunk_text  TEXT NOT NULL,
    n_terms     INT NOT NULL,
    embedding   vector({DIM}){CHUNK_EXTRA}
);
CREATE INDEX IF NOT EXISTS ix_{S}_chunk_doc ON {S}.chunk(doc_id, seq);
CREATE TABLE IF NOT EXISTS {S}.chunk_term (term TEXT NOT NULL, chunk_id INT NOT NULL, tf SMALLINT NOT NULL, PRIMARY KEY (term, chunk_id));
CREATE INDEX IF NOT EXISTS ix_{S}_chunk_term_chunk ON {S}.chunk_term(chunk_id);
CREATE TABLE IF NOT EXISTS {S}.term_stat (term TEXT PRIMARY KEY, df INT NOT NULL);
CREATE TABLE IF NOT EXISTS {S}.corpus_stat (
    id SMALLINT PRIMARY KEY DEFAULT 1, n_chunks INT NOT NULL, avg_len DOUBLE PRECISION NOT NULL, dim INT NOT NULL
);
DROP VIEW IF EXISTS {S}.v_chunk_source;
CREATE VIEW {S}.v_chunk_source AS {VIEW};
"""


def view(src):
    doc = ["summary", "created_at", "client_edw", "clients_doc", *DOC_EXTRA_COLS.get(src, [])]
    sel = (
        ["c.chunk_id", "c.doc_id", "d.file_path", "regexp_replace(d.file_path, '^.*/', '') AS file_name"]
        + [f"c.{c}" for c in ("page", "line_start", "line_end", "bbox", "section", "seq", "chunk_text")]
        + [f"d.{c}" for c in doc]
        + (["c.faq_group"] if src == "faq" else [])
    )
    return "SELECT " + ", ".join(sel) + " FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id"


def upgrade():
    a = context.config.attributes
    b, d = a["schema"], int(a["dim"])
    bind = op.get_bind()
    if not search_parts.dev_run():
        bind.exec_driver_sql(DROP_OLD.replace("{B}", b))
    for src in search_parts.sources(SOURCES):
        s = f"{b}_{src}"
        extra = DOC_EXTRA.get(src, "")
        sql = (
            SRC_SQL.replace("{VIEW}", view(src))
            .replace("{DOC_EXTRA}", (",\n    " + extra.replace(", ", ",\n    ")) if extra else "")
            .replace("{CHUNK_EXTRA}", (",\n    " + CHUNK_EXTRA[src]) if src in CHUNK_EXTRA else "")
            .replace("{S}", s)
            .replace("{B}", b)
            .replace("{DIM}", str(d))
        )
        bind.exec_driver_sql(sql)
        if d <= HNSW_MAX:
            bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_{s}_chunk_emb ON {s}.chunk USING hnsw (embedding vector_cosine_ops)")
        else:
            bind.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{s}_chunk_embq ON {s}.chunk USING hnsw ((binary_quantize(embedding)::bit({d})) bit_hamming_ops)"
            )


def downgrade():
    raise NotImplementedError("되돌리지 않음 — 0.2.0은 전체 다시 적재(DB 담당 협의·백업)")
