"""검색 스키마 표 정의(정본 — S8a, 5-4). 0.2.0(pl-28, 사용자 11-01·11-02): 원천 시스템마다 PG 스키마 하나 `<PG_SCHEMA>_<원천>`
(원천 = sfdc·crms·las·faq·other) — 스키마마다 같은 표 doc·chunk·chunk_term·term_stat·corpus_stat + 뷰 v_chunk_source, 그 원천 전용 칸만 다름.
기준 스키마 `<PG_SCHEMA>`에는 Alembic 판 표와 5벌이 함께 쓰는 doc_id 시퀀스(`doc_id_seq`)만 있다(load_run은 지움 — 실행 정보는 실행 기록에).
임베딩 차원은 실행 값이라 함수로 만든다. 색인 정의 글자(index_defs)·뷰(views_expected — 칸 이름 순서 + 정의 글자)는 PostgreSQL이 돌려주는 꼴
(pg_get_indexdef·pg_get_viewdef — `{S}` = 원천 스키마) — 비교용(dbcompare). Alembic 판(migrations/versions/0002_search_doc_meta.py)이 같은 DDL을 글자로 갖고,
PC PG 시험이 둘이 같은지 본다."""

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, MetaData, PrimaryKeyConstraint, SmallInteger, String, Table, Text, text
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, TIMESTAMP
from sqlalchemy.types import UserDefinedType

from common.store.pg import HNSW_MAX  # pgvector HNSW는 vector 2,000차원까지 — 적재·검색과 같은 기준(판 파일만 숫자를 굳혀 둠)

SOURCES = ("sfdc", "crms", "las", "faq", "other")
SEQ = "doc_id_seq"  # 기준 스키마에 하나 — 5벌이 함께 써서 doc_id가 겹치지 않음(chunk_key `<doc_id>:<seq>`)
_SYSTEM = {"SFDC": "sfdc", "CRMS": "crms", "LAS": "las", "FAQ": "faq"}

# 원천 전용 doc 칸 — (이름, 형식). EDW 조인 사슬이 정해진 것만(pl-29·db_schema §1 원천별 표). 공용 칸은 search_metadata.
DOC_EXTRA = {
    "sfdc": (
        ("doc_class", Text),
        ("sf_op_id", Text),
        ("sf_op_name", Text),
        ("project_code__c", Text),
        ("service_type", Text),
        ("contract_date", Date),
    ),
    "crms": (("division", Text), ("prod_name", Text), ("contract_id", Text), ("contract_date", Date)),
    "las": (("doc_class", Text), ("contract_id", Text), ("contract_date", Date)),
    "faq": (),
    "other": (),
}
CHUNK_EXTRA = {"faq": (("faq_group", Text),)}  # C4 — faq.chunk만 시트 이름


def source_of(system):
    """원천 표기(SFDC·CRMS·LAS·FAQ — `-test` 붙어도 같음, G4) → 원천 이름. 그 밖·빈 값은 other(A2)."""
    s = str(system or "").strip()
    if s.lower().endswith("-test"):
        s = s[: -len("-test")]
    return _SYSTEM.get(s.upper(), "other")


def src_schema(base, src):
    """기준 스키마 + 원천 → 원천 스키마 이름(`ai` + `sfdc` → `ai_sfdc`)."""
    return f"{base}_{src}"


def split_schema(schema):
    """원천 스키마 이름 → (기준 스키마, 원천). 원천 스키마가 아니면 (schema, None)."""
    base, _, src = schema.rpartition("_")
    return (base, src) if base and src in SOURCES else (schema, None)


class Vector(UserDefinedType):
    """pgvector `vector(n)` — 파이썬 pgvector 패키지 없이(5-4 — 선택). 적재·검색은 지금처럼 글자 '[…]'로 넘긴다."""

    cache_ok = True

    def __init__(self, dim=None):
        self.dim = dim

    def get_col_spec(self, **kw):
        return f"vector({self.dim})" if self.dim else "vector"


def doc_columns(src):
    """doc 표 칸 이름 순서(공용 + 원천 전용)."""
    return ["doc_id", "file_path", "summary", "created_at", "client_edw", "clients_doc"] + [n for n, _ in DOC_EXTRA[src]]


def search_metadata(schema, dim, shared_seq=True):
    """원천 스키마 하나의 표 정의 — schema = `<PG_SCHEMA>_<원천>`, dim = 임베딩 차원. shared_seq: doc_id 기본값을 기준 스키마의 공용 시퀀스로
    (SQLite 대역은 False — 대역은 스키마마다 파일 하나라 시퀀스를 흉내 내지 않고 자동 번호)."""
    base, src = split_schema(schema)
    if src is None:
        raise ValueError(f"원천 스키마 이름이 아님(<기준>_<{'|'.join(SOURCES)}>): {schema!r}")
    md = MetaData(schema=schema)
    doc_id = (
        Column(
            "doc_id", Integer, primary_key=True, server_default=text(f"nextval('{base}.{SEQ}')")
        )  # PG가 ::regclass를 붙여 저장 — Alembic 비교는 그것을 떼고 봄
        if shared_seq
        else Column("doc_id", Integer, primary_key=True)
    )
    Table(
        "doc",
        md,
        doc_id,
        Column("file_path", Text, nullable=False),  # Object Storage 원본 경로 = EDW FileStorageMap.s3_key(= ParsingMeta 키) — 연결 키
        Column("summary", Text),
        Column("created_at", TIMESTAMP(timezone=True)),  # 원천 등록 시각(FileStorageMap.created_at, KST)
        Column("client_edw", Text),  # EDW 조인 사슬의 고객 하나 — client 거르기는 이 칸 정확 일치만(C6)
        Column("clients_doc", Text),  # 본문에서 찾은 고객 라벨(JSON 글자) — 참고만, 거르기·순위에 안 씀
        *(Column(n, t) for n, t in DOC_EXTRA[src]),
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
        Column("bbox", String(80)),
        Column("section", Text),
        Column("chunk_text", Text, nullable=False),
        Column("n_terms", Integer, nullable=False),
        Column("embedding", Vector(int(dim))),
        *(Column(n, t) for n, t in CHUNK_EXTRA.get(src, ())),
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
    """색인 이름 → pg_get_indexdef 글자(`{S}` = 원천 스키마) — 기본 키 색인 빼고. 차원 ≤2,000이면 HNSW 코사인, 넘으면 이진 양자화 HNSW."""
    out = {
        "ix_{S}_chunk_doc": "CREATE INDEX ix_{S}_chunk_doc ON {S}.chunk USING btree (doc_id, seq)",
        "ix_{S}_chunk_term_chunk": "CREATE INDEX ix_{S}_chunk_term_chunk ON {S}.chunk_term USING btree (chunk_id)",
    }
    if int(dim) <= HNSW_MAX:
        out["ix_{S}_chunk_emb"] = "CREATE INDEX ix_{S}_chunk_emb ON {S}.chunk USING hnsw (embedding vector_cosine_ops)"
    else:
        out["ix_{S}_chunk_embq"] = (
            f"CREATE INDEX ix_{{S}}_chunk_embq ON {{S}}.chunk USING hnsw (((binary_quantize(embedding))::bit({int(dim)})) bit_hamming_ops)"
        )
    return out


_VIEW_CHUNK = ("chunk_id", "doc_id", "file_path", "file_name", "page", "line_start", "line_end", "bbox", "section", "seq", "chunk_text")


def view_columns(src):
    """v_chunk_source 칸 순서 — 청크 칸 + 문서 칸(공용·원천 전용) + (faq) faq_group."""
    doc_cols = [c for c in doc_columns(src) if c not in ("doc_id", "file_path")]
    return [*_VIEW_CHUNK, *doc_cols, *(n for n, _ in CHUNK_EXTRA.get(src, ()))]


def view_sql(src):
    """CREATE VIEW 본문(`{S}` = 원천 스키마) — 판 0002와 SQLite 대역이 같은 글자를 쓴다."""
    doc_cols = [c for c in doc_columns(src) if c not in ("doc_id", "file_path")]
    sel = (
        ["c.chunk_id", "c.doc_id", "d.file_path", "regexp_replace(d.file_path, '^.*/', '') AS file_name"]
        + [f"c.{c}" for c in _VIEW_CHUNK[4:]]
        + [f"d.{c}" for c in doc_cols]
        + [f"c.{n}" for n, _ in CHUNK_EXTRA.get(src, ())]
    )
    return "SELECT " + ", ".join(sel) + " FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id"


def views_expected(src):
    """뷰 이름 → (칸 이름 순서 — 판정, 정의 글자 — 알림만)."""
    return {"v_chunk_source": (tuple(view_columns(src)), view_sql(src))}


def view_ddl(src):
    """SQLite 대역(pg_standin)에 줄 뷰 DDL(대역 번역기가 CREATE OR REPLACE VIEW를 DROP+CREATE로 바꿈)."""
    return "DROP VIEW IF EXISTS {S}.v_chunk_source;\nCREATE OR REPLACE VIEW {S}.v_chunk_source AS\n" + view_sql(src)
