"""${message}

갈래: search(검색 스키마 — context.config.attributes["schema"]·["dim"]) 또는 struct(이름 고정). 표·칸을 바꾸는 판은 데이터 계약 변경 —
DB 담당 협의·검토 등급 A(D-008). 한 번 배포한 판은 고치지 않는다(새 판으로). 시드 데이터는 resources/sql/<판 번호>_*.(5-4)
"""
from alembic import context, op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    s = context.config.attributes["schema"]
    ${upgrades if upgrades else "raise NotImplementedError"}


def downgrade():
    ${downgrades if downgrades else "raise NotImplementedError"}
