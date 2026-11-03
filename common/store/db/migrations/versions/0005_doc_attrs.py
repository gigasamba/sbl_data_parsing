"""검색 스키마 0005(pl-52, 사용자 11-03 — 등급 A DB 스키마): 원천마다 다른 문서 메타를 `doc.attrs`(JSONB) 한 칸으로 모은다.
원천 스키마 5벌의 doc에 `attrs` + GIN 색인을 더하고, 옛 원천 전용 칸(판 0002)·분류 힌트 칸(판 0003)의 값을 `attrs`의 같은 이름 키로 옮긴 뒤
(NULL은 넣지 않음 — jsonb_strip_nulls, 날짜는 'YYYY-MM-DD' 글자) 그 칸을 지운다. 뷰 v_chunk_source는 옛 칸 대신 `attrs`를 낸다.
0.2.0은 새 PG_SCHEMA·전체 다시 적재지만 올리기는 값을 잃지 않는다. 되돌리기는 attrs에서 옛 칸을 되살리고(형식 그대로) attrs·색인을 지운다.
칸·뷰는 common/store/db/models/search_tables.py와 같은 글자로 굳혀 둔다(한 번 배포한 판은 고치지 않음 — 시험이 대조)."""

from alembic import context, op

revision = "0005_search"
down_revision = "0004_search"
branch_labels = None
depends_on = None

SOURCES = ("sfdc", "crms", "las", "faq", "other")
OLD_EXTRA = {  # 판 0002 원천 전용 doc 칸(뷰에도 있던 칸) — 형식은 되돌리기용
    "sfdc": (
        ("doc_class", "TEXT"),
        ("sf_op_id", "TEXT"),
        ("sf_op_name", "TEXT"),
        ("project_code__c", "TEXT"),
        ("service_type", "TEXT"),
        ("contract_date", "DATE"),
    ),
    "crms": (("division", "TEXT"), ("prod_name", "TEXT"), ("contract_id", "TEXT"), ("contract_date", "DATE")),
    "las": (("doc_class", "TEXT"), ("contract_id", "TEXT"), ("contract_date", "DATE")),
}
OLD_HINTS = {  # 판 0003 분류 힌트 doc 칸(뷰에는 없던 칸)
    "sfdc": (
        ("title", "TEXT"),
        ("entity_type", "TEXT"),
        ("entity_class", "TEXT"),
        ("entity_id", "TEXT"),
        ("sent_received__c", "TEXT"),
        ("subject", "TEXT"),
        ("stagename", "TEXT"),
        ("real_rfp__c", "TEXT"),
        ("rfp_received_start_date__c", "DATE"),
        ("rfp_received_end_date__c", "DATE"),
    ),
    "las": (("approvalname", "TEXT"),),
}
OLD_COLS = {s: (*OLD_EXTRA.get(s, ()), *OLD_HINTS.get(s, ())) for s in SOURCES}  # 지우는 칸(값은 attrs의 같은 이름 키로)
VIEW_DOC = ("summary", "created_at", "client_edw", "clients_doc")  # 뷰의 고정 문서 칸(판 0002 그대로) — 이 판이 끝에 attrs를 붙임
VIEW_CHUNK = ("page", "line_start", "line_end", "bbox", "section", "seq", "chunk_text")


def view(src, doc_cols):
    """v_chunk_source 본문 — doc_cols = 고정 칸 다음에 낼 문서 칸(이 판: attrs · 되돌리기: 옛 판 0002 원천 전용 칸)."""
    sel = (
        ["c.chunk_id", "c.doc_id", "d.file_path", "regexp_replace(d.file_path, '^.*/', '') AS file_name"]
        + [f"c.{c}" for c in VIEW_CHUNK]
        + [f"d.{c}" for c in (*VIEW_DOC, *doc_cols)]
        + (["c.faq_group"] if src == "faq" else [])
    )
    return "SELECT " + ", ".join(sel) + " FROM {S}.chunk c JOIN {S}.doc d ON d.doc_id = c.doc_id"


def upgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    for src in SOURCES:
        s = f"{b}_{src}"
        cols = OLD_COLS[src]
        bind.exec_driver_sql(f"ALTER TABLE {s}.doc ADD COLUMN IF NOT EXISTS attrs JSONB")
        obj = "jsonb_strip_nulls(jsonb_build_object(" + ", ".join(f"'{n}', {n}" for n, _ in cols) + "))" if cols else "'{}'::jsonb"
        bind.exec_driver_sql(f"UPDATE {s}.doc SET attrs = {obj}")
        bind.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_{s}_doc_attrs ON {s}.doc USING gin (attrs)")
        bind.exec_driver_sql(f"DROP VIEW IF EXISTS {s}.v_chunk_source")
        if cols:
            bind.exec_driver_sql(f"ALTER TABLE {s}.doc " + ", ".join(f"DROP COLUMN IF EXISTS {n}" for n, _ in cols))
        bind.exec_driver_sql(f"CREATE VIEW {s}.v_chunk_source AS " + view(src, ("attrs",)).replace("{S}", s))


def downgrade():
    b = context.config.attributes["schema"]
    bind = op.get_bind()
    for src in SOURCES:
        s = f"{b}_{src}"
        cols = OLD_COLS[src]
        bind.exec_driver_sql(f"DROP VIEW IF EXISTS {s}.v_chunk_source")
        if cols:
            bind.exec_driver_sql(f"ALTER TABLE {s}.doc " + ", ".join(f"ADD COLUMN IF NOT EXISTS {n} {t}" for n, t in cols))
            bind.exec_driver_sql(f"UPDATE {s}.doc SET " + ", ".join(f"{n} = (attrs->>'{n}')::{t}" for n, t in cols))
        bind.exec_driver_sql(f"DROP INDEX IF EXISTS {s}.ix_{s}_doc_attrs")
        bind.exec_driver_sql(f"ALTER TABLE {s}.doc DROP COLUMN IF EXISTS attrs")
        bind.exec_driver_sql(f"CREATE VIEW {s}.v_chunk_source AS " + view(src, [n for n, _ in OLD_EXTRA.get(src, ())]).replace("{S}", s))
