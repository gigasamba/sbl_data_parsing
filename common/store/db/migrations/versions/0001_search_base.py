"""검색 스키마 기준판(S8a, 5-4 — 사용자 10-28 Q2 a): 옛 `pipeline/load/pg/schema.sql` 글자 그대로(SCHEMA_SQL — {S} 스키마·{DIM} 차원) +
옛 `pgvector_load.deploy()` 코드 안 색인 DDL 그대로. 이미 있는 스키마는 IF NOT EXISTS라 없는 표·색인만 생긴다(dbtool이 먼저 비교 — Q3).
`CREATE EXTENSION vector`는 판 밖(dbtool이 확인 — 관리자 설치, PG_CREATE_EXTENSION 옵트인은 지금처럼). 한 번 배포한 판은 고치지 않는다."""

from alembic import context, op

revision = "0001_search"
down_revision = None
branch_labels = ("search",)
depends_on = None

HNSW_MAX = 2000  # common.store.pg.HNSW_MAX(옛 deploy가 쓰던 값) — 판 파일은 그 값이 뒤에 바뀌어도 이 판의 뜻을 지키게 숫자로 둠

SCHEMA_SQL = """-- 개발 서버 PostgreSQL + pgvector — 대표 파싱·청크·벡터·키워드 색인을 개발 서버에서 관리(EDW로 보내지 않음).
-- {S} = 스키마(기본 ai) · {DIM} = 임베딩 차원. 다시 실행해도 안전(IF NOT EXISTS). EDW 스키마(modules/load/sql/10_tables.sql)와 같은 열 이름.
-- 2026-10-20 축소 스키마 — 검색에 필요한 최소만: doc(14) + chunk + BM25(chunk_term/term_stat/corpus_stat) + v_chunk_source.
-- vector 확장은 여기서 만들지 않음(XS3) — 관리자가 미리 설치, 없으면 pgstore.deploy()가 멈춤.
CREATE SCHEMA IF NOT EXISTS {S};

CREATE TABLE IF NOT EXISTS {S}.load_run (
    run_id      SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    params      JSONB,
    counts      JSONB
);
-- doc — 문서 단위 메타(축소: EDW 식별 + 검색 필터 + 요약만)
CREATE TABLE IF NOT EXISTS {S}.doc (
    doc_id      SERIAL PRIMARY KEY,
    file_path   TEXT NOT NULL,               -- 원본 파일 경로(개발 서버 기준 — 파일명은 여기서 유도)
    clients     TEXT,                        -- 문서에서 추출한 고객(JSON 인코딩 TEXT)
    summary     TEXT,                       -- 요약(검색 결과용)
    source_system VARCHAR(20),              -- SFDC / CRMS / LAS (검색 필터)
    sf_acc_name TEXT,
    sf_op_id    TEXT,
    sf_op_name  TEXT,
    project_code__c TEXT,
    contract_id TEXT,
    contract_date DATE,
    prod_name   TEXT,
    division    VARCHAR(20),
    service_type VARCHAR(20),
    run_id      INT
);
CREATE TABLE IF NOT EXISTS {S}.chunk (
    chunk_id    SERIAL PRIMARY KEY,
    doc_id      INT NOT NULL REFERENCES {S}.doc(doc_id) ON DELETE CASCADE,
    seq         INT NOT NULL,
    page        INT,
    line_start  INT,
    line_end    INT,
    char_start  INT,
    char_end    INT,
    bbox        VARCHAR(80),                   -- 쪽 안 위치 x0,y0,x1,y1(pt)
    section     TEXT,
    chunk_text  TEXT NOT NULL,                 -- 정제 텍스트(쪽 번호 줄 제외)
    n_chars     INT NOT NULL,
    n_terms     INT NOT NULL,
    embed_model VARCHAR(100),
    embedding   vector({DIM}),                  -- L2 정규화 저장 → 코사인 = 1 - (embedding <=> q)
    clients     TEXT[],                        -- 고객 라벨(GIN — client 하드 필터용)
    source_system VARCHAR(20)
);
CREATE INDEX IF NOT EXISTS ix_{S}_chunk_doc ON {S}.chunk(doc_id, seq);
-- 근사 최근접 색인은 modules/load/pgstore.py deploy가 만든다(pgvector HNSW는 vector 2,000차원까지):
--   ≤2000 → HNSW 코사인 · >2000(qwen3-vl-embedding = 4096) → 이진 양자화 HNSW(bit_hamming) + 원 벡터 코사인 재정렬

CREATE TABLE IF NOT EXISTS {S}.chunk_term (
    term     TEXT NOT NULL,
    chunk_id INT NOT NULL,
    tf       SMALLINT NOT NULL,
    PRIMARY KEY (term, chunk_id)
);
CREATE INDEX IF NOT EXISTS ix_{S}_chunk_term_chunk ON {S}.chunk_term(chunk_id);
CREATE TABLE IF NOT EXISTS {S}.term_stat (term TEXT PRIMARY KEY, df INT NOT NULL);
CREATE TABLE IF NOT EXISTS {S}.corpus_stat (
    id SMALLINT PRIMARY KEY DEFAULT 1, n_chunks INT NOT NULL, avg_len DOUBLE PRECISION NOT NULL, dim INT NOT NULL
);

-- 검색 결과 뷰 — chunk ↔ doc 연결(파일명은 file_path에서 추출: splittrecht 대신 SQL에서 계산)
-- 뷰는 열 추가 시 끝에만(CREATE OR REPLACE VIEW 제약) — doc 컬럼 축소 시 뷰도 DROP 후 재생성.
DROP VIEW IF EXISTS {S}.v_chunk_source;
CREATE OR REPLACE VIEW {S}.v_chunk_source AS
SELECT c.chunk_id, c.doc_id,
       d.file_path, regexp_replace(d.file_path, '^.*/', '') AS file_name,  -- 파일명 유도
       c.page, c.line_start, c.line_end, c.bbox, c.section, c.seq,
       c.chunk_text, d.summary, d.clients, c.source_system, c.source_system AS chunk_source_system,
       d.source_system AS doc_source_system, d.sf_acc_name, d.sf_op_id, d.sf_op_name, d.project_code__c,
       d.contract_id, d.contract_date, d.prod_name, d.division, d.service_type
FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id;
"""


def upgrade():
    a = context.config.attributes
    s, d = a["schema"], int(a["dim"])
    bind = op.get_bind()
    bind.exec_driver_sql(SCHEMA_SQL.replace("{S}", s).replace("{DIM}", str(d)))  # 옛 deploy: cur.execute(schema.sql) — 여러 문장 한 번에
    if d <= HNSW_MAX:  # 옛 deploy 코드 그대로(색인 3개)
        bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_{s}_chunk_emb ON {s}.chunk USING hnsw (embedding vector_cosine_ops)")
    else:
        bind.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_{s}_chunk_embq ON {s}.chunk USING hnsw ((binary_quantize(embedding)::bit({d})) bit_hamming_ops)"
        )
    bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_{s}_chunk_clients ON {s}.chunk USING gin (clients)")


def downgrade():
    raise NotImplementedError("기준판은 되돌리지 않음 — 스키마를 지우려면 사람이(DB 담당 협의)")
