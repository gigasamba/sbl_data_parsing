"""pl-38 마스터 기준판(사용자 11-03): 용어집·고객 명부 CSV 여섯 개의 표 + master_meta. 스키마 `<PG_SCHEMA>_master`(dbtool이 이름을 만듦).
칸은 이 판에 굳힌다(모델 common/store/db/models/master_tables.py를 import하지 않음 — test_dbtool이 대조). 내용은 `dbtool master load`가 채운다."""

from alembic import context, op

revision = "0001_master"
down_revision = None
branch_labels = ("master",)
depends_on = None

TABLES = {
    "client_roster": (
        "client_id", "canonical_name", "name_ko", "aliases", "client_type", "segment",
        "country", "parent_client_id", "status", "description", "source", "updated",
    ),
    "client_master": ("company_id", "company", "aliases"),
    "contract_master": (
        "contract_id", "company", "company_id", "product_code", "modality", "site", "line_id", "batches_contracted",
        "contract_value_usd", "currency", "term_months", "signed_on", "start_date", "end_date", "status",
    ),
    "domain_terms": (
        "concept_id", "canonical", "category", "synonyms", "abbreviations", "weak_synonyms", "broader", "related",
        "context_required", "case_sensitive", "definition_ko", "definition_en", "source", "owner", "status", "updated",
    ),
    "id_patterns": ("id_type", "regex", "example", "note", "updated"),
    "units": ("canonical", "variants", "quantity", "equivalent_to", "note", "updated"),
}  # fmt: skip


def upgrade():
    s = context.config.attributes["schema"]
    for name, cols in TABLES.items():
        op.execute(f"CREATE TABLE {s}.{name} (row_no INTEGER NOT NULL, {', '.join(f'{c} TEXT' for c in cols)}, PRIMARY KEY (row_no))")
    op.execute(f"CREATE TABLE {s}.master_meta (id INTEGER NOT NULL, hash TEXT, loaded_at TIMESTAMP WITH TIME ZONE, PRIMARY KEY (id))")


def downgrade():
    s = context.config.attributes["schema"]
    for name in (*TABLES, "master_meta"):
        op.execute(f"DROP TABLE {s}.{name}")
