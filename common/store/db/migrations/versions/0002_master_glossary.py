"""op-17 마스터 판 0002(규칙 19·20): 표 `glossary` 하나(melt — 유사값마다 한 줄)가 옛 마스터 표 여섯 개와 master_meta를 바꾼다.
옛 표는 지운다 — 내용의 원본은 git CSV라 지워도 잃는 것이 없다(`dbtool master load`가 glossary를 다시 채움). 해시는 읽을 때 계산한다.
칸은 이 판에 굳힌다(모델 common/store/db/models/master_tables.py를 import하지 않음 — test_master가 대조)."""

from alembic import context, op

revision = "0002_master"
down_revision = "0001_master"
branch_labels = None
depends_on = None

COLS = ("kind", "canonical", "variant", "variant_kind", "description", "context_required", "case_sensitive")
OLD = ("client_roster", "client_master", "contract_master", "domain_terms", "id_patterns", "units", "master_meta")


def upgrade():
    s = context.config.attributes["schema"]
    op.execute(f"CREATE TABLE {s}.glossary (row_no INTEGER NOT NULL, {', '.join(f'{c} TEXT' for c in COLS)}, PRIMARY KEY (row_no))")
    for name in OLD:
        op.execute(f"DROP TABLE {s}.{name}")


def downgrade():
    raise NotImplementedError("옛 마스터 표 되살리기는 DB 담당 협의 필요")
