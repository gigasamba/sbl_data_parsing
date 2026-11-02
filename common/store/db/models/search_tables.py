"""검색 스키마 표 정의(정본 — S8a, 5-4) — 10-20 축소 스키마 그대로(refactor_plan 9-3, D-008): load_run·doc·chunk·chunk_term·term_stat·
corpus_stat + 뷰 v_chunk_source. 스키마 이름(PG_SCHEMA — index --pg면 <PG_SCHEMA>_<index_id>)과 임베딩 차원은 실행 값이라 함수로 만든다.
Alembic 판(migrations/versions/0001_search_base.py — 옛 DDL 글자 그대로 + 0002_search_doc_meta.py — doc_class·created_at·s3_key)을 끝까지 올린 DB와 같은지 시험이 본다(dbcompare).
색인 정의 글자(index_defs)·뷰(VIEWS_EXPECTED — 칸 이름 순서 + 정의 글자)는 PostgreSQL이 돌려주는 꼴(pg_get_indexdef·pg_get_viewdef —
`{S}` = 스키마) — 비교용(dbcompare)."""

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, MetaData, PrimaryKeyConstraint, SmallInteger, String, Table, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB, TIMESTAMP
from sqlalchemy.types import UserDefinedType

from common.store.pg import HNSW_MAX  # pgvector HNSW는 vector 2,000차원까지 — 적재·검색과 같은 기준(판 파일만 숫자를 굳혀 둠)


class Vector(UserDefinedType):
    """pgvector `vector(n)` — 파이썬 pgvector 패키지 없이(5-4 — 선택). 적재·검색은 지금처럼 글자 '[…]'로 넘긴다."""

    cache_ok = True

    def __init__(self, dim=None):
        self.dim = dim

    def get_col_spec(self, **kw):
        return f"vector({self.dim})" if self.dim else "vector"


def search_metadata(schema, dim):
    """검색 스키마 표 정의 — schema(PG_SCHEMA)·dim(임베딩 차원). 색인은 이름에 스키마가 들어감(ix_<schema>_…)."""
    md = MetaData(schema=schema)
    Table(
        "load_run",
        md,
        Column("run_id", Integer, primary_key=True),
        Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
        Column("finished_at", TIMESTAMP(timezone=True)),
        Column("params", JSONB),
        Column("counts", JSONB),
    )
    Table(
        "doc",
        md,
        Column("doc_id", Integer, primary_key=True),
        Column("file_path", Text, nullable=False),
        Column("clients", Text),
        Column("summary", Text),
        Column("source_system", String(20)),
        Column("sf_acc_name", Text),
        Column("sf_op_id", Text),
        Column("sf_op_name", Text),
        Column("project_code__c", Text),
        Column("contract_id", Text),
        Column("contract_date", Date),
        Column("prod_name", Text),
        Column("division", String(20)),
        Column("service_type", String(20)),
        Column("run_id", Integer),
        Column("doc_class", Text),  # 0002(11-01 — mc-16 거르기)
        Column("created_at", TIMESTAMP(timezone=True)),  # 0002 — 원천 등록 시각(FileStorageMap.created_at)
        Column("s3_key", Text),  # 0002 — 원본 전체 경로 = ParsingMeta.source_key(mc-17 연결 키)
    )
    chunk = Table(
        "chunk",
        md,
        Column("chunk_id", Integer, primary_key=True),
        Column("doc_id", Integer, ForeignKey(f"{schema}.doc.doc_id", ondelete="CASCADE"), nullable=False),
        Column("seq", Integer, nullable=False),
        Column("page", Integer),
        Column("line_start", Integer),
        Column("line_end", Integer),
        Column("char_start", Integer),
        Column("char_end", Integer),
        Column("bbox", String(80)),
        Column("section", Text),
        Column("chunk_text", Text, nullable=False),
        Column("n_chars", Integer, nullable=False),
        Column("n_terms", Integer, nullable=False),
        Column("embed_model", String(100)),
        Column("embedding", Vector(int(dim))),
        Column("clients", ARRAY(Text)),
        Column("source_system", String(20)),
    )
    chunk_term = Table(
        "chunk_term",
        md,
        Column("term", Text, nullable=False),
        Column("chunk_id", Integer, nullable=False, autoincrement=False),
        Column("tf", SmallInteger, nullable=False),
        PrimaryKeyConstraint("term", "chunk_id"),
    )
    Table("term_stat", md, Column("term", Text, primary_key=True), Column("df", Integer, nullable=False))
    Table(
        "corpus_stat",
        md,
        Column("id", SmallInteger, primary_key=True, autoincrement=False, server_default=text("1")),
        Column("n_chunks", Integer, nullable=False),
        Column("avg_len", DOUBLE_PRECISION, nullable=False),
        Column("dim", Integer, nullable=False),
    )
    Index(f"ix_{schema}_chunk_doc", chunk.c.doc_id, chunk.c.seq)
    Index(f"ix_{schema}_chunk_term_chunk", chunk_term.c.chunk_id)
    return md


def index_defs(dim):
    """색인 이름 → pg_get_indexdef 글자(`{S}` = 스키마) — 기본 키 색인 빼고. 차원 ≤2,000이면 HNSW 코사인, 넘으면 이진 양자화 HNSW."""
    out = {
        "ix_{S}_chunk_doc": "CREATE INDEX ix_{S}_chunk_doc ON {S}.chunk USING btree (doc_id, seq)",
        "ix_{S}_chunk_term_chunk": "CREATE INDEX ix_{S}_chunk_term_chunk ON {S}.chunk_term USING btree (chunk_id)",
        "ix_{S}_chunk_clients": "CREATE INDEX ix_{S}_chunk_clients ON {S}.chunk USING gin (clients)",
    }
    if int(dim) <= HNSW_MAX:
        out["ix_{S}_chunk_emb"] = "CREATE INDEX ix_{S}_chunk_emb ON {S}.chunk USING hnsw (embedding vector_cosine_ops)"
    else:
        out["ix_{S}_chunk_embq"] = (
            f"CREATE INDEX ix_{{S}}_chunk_embq ON {{S}}.chunk USING hnsw (((binary_quantize(embedding))::bit({int(dim)})) bit_hamming_ops)"
        )
    return out


# 뷰 이름 → (칸 이름 순서 — 판정, pg_get_viewdef 글자 — 알림만: `{S}` = 스키마, 공백은 비교 때 하나로 줄임, PostgreSQL 16 꼴)
VIEWS_EXPECTED = {
    "v_chunk_source": (
        (
            "chunk_id",
            "doc_id",
            "file_path",
            "file_name",
            "page",
            "line_start",
            "line_end",
            "bbox",
            "section",
            "seq",
            "chunk_text",
            "summary",
            "clients",
            "source_system",
            "chunk_source_system",
            "doc_source_system",
            "sf_acc_name",
            "sf_op_id",
            "sf_op_name",
            "project_code__c",
            "contract_id",
            "contract_date",
            "prod_name",
            "division",
            "service_type",
            "doc_class",
            "created_at",
            "s3_key",
        ),
        "SELECT c.chunk_id, c.doc_id, d.file_path, regexp_replace(d.file_path, '^.*/'::text, ''::text) AS file_name, c.page, "
        "c.line_start, c.line_end, c.bbox, c.section, c.seq, c.chunk_text, d.summary, d.clients, c.source_system, "
        "c.source_system AS chunk_source_system, d.source_system AS doc_source_system, d.sf_acc_name, d.sf_op_id, d.sf_op_name, "
        "d.project_code__c, d.contract_id, d.contract_date, d.prod_name, d.division, d.service_type, d.doc_class, d.created_at, d.s3_key "
        "FROM ({S}.chunk c JOIN {S}.doc d ON ((d.doc_id = c.doc_id)));",
    ),
}

# SQLite 대역(pg_standin)에 줄 뷰 — 옛 schema.sql 끝 두 문장 그대로(대역 번역기가 CREATE OR REPLACE VIEW를 DROP+CREATE로 바꿈)
VIEW_SQL = """DROP VIEW IF EXISTS {S}.v_chunk_source;
CREATE OR REPLACE VIEW {S}.v_chunk_source AS
SELECT c.chunk_id, c.doc_id,
       d.file_path, regexp_replace(d.file_path, '^.*/', '') AS file_name,
       c.page, c.line_start, c.line_end, c.bbox, c.section, c.seq,
       c.chunk_text, d.summary, d.clients, c.source_system, c.source_system AS chunk_source_system,
       d.source_system AS doc_source_system, d.sf_acc_name, d.sf_op_id, d.sf_op_name, d.project_code__c,
       d.contract_id, d.contract_date, d.prod_name, d.division, d.service_type,
       d.doc_class, d.created_at, d.s3_key
FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id"""
