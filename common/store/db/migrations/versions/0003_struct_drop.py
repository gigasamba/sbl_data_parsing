"""struct 판 0003 — 기준판 0001의 표 10개를 지운다(pl-08·pl-12 C10 — 사용자 10-31 결정, 마이그레이션 11-01 승인).
문서 대장 doc_registry·doc_hidden·doc_registry_seen(코드는 pl-12 C10에 지움) · 정형 표 contract_master·client_master·prod_master·
doc_contract_link·doc_location · 표 칸 doc_table·doc_cell(코드는 pl-08에 지움 — 마스터는 CSV 파일, docs/architecture/db_schema.md §5).
남는 표: 판 표 stack_version·source_version(0002)과 판 기록 alembic_version.
0001이 IF NOT EXISTS로 만들었으므로(있는 스키마에 없는 표만 생김) 여기도 IF EXISTS로 지운다 — 없는 표는 건너뜀. 표끼리 외래 키는 없고
doc_cell 색인 2개는 표와 함께 지워진다. 행이 함께 사라지므로 서버는 올리기 전에 백업(db_schema.md D-7). 한 번 배포한 판은 고치지 않는다."""

from alembic import context, op

revision = "0003_struct"
down_revision = "0002_struct"
branch_labels = None
depends_on = None

DROPPED = (
    "doc_registry",
    "doc_hidden",
    "doc_registry_seen",
    "contract_master",
    "client_master",
    "prod_master",
    "doc_contract_link",
    "doc_location",
    "doc_table",
    "doc_cell",
)


def upgrade():
    s = context.config.attributes["schema"]
    bind = op.get_bind()
    for table in DROPPED:
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {s}.{table}")


def downgrade():
    raise NotImplementedError("지운 표는 되돌리지 않음 — 다시 만들려면 사람이 백업에서(DB 담당 협의)")
