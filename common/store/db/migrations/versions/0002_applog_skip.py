"""pl-58 applog 판 0002: 영구 건너뜀 문서 표 skip_doc_info(원본 키당 한 행) — 새 표만, 기존 표는 그대로.
DDL은 이 판에 고정한다(현재 모델을 import하지 않음)."""

from alembic import context, op

revision = "0002_applog"
down_revision = "0001_applog"
branch_labels = None
depends_on = None

DDL = """CREATE TABLE {S}.skip_doc_info (
    source_key TEXT NOT NULL,
    source_system TEXT,
    file_name TEXT,
    reason TEXT NOT NULL,
    level TEXT DEFAULT 'error' NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    count INTEGER DEFAULT 1 NOT NULL,
    PRIMARY KEY (source_key)
)"""


def upgrade():
    op.execute(DDL.replace("{S}", context.config.attributes["schema"]))


def downgrade():
    raise NotImplementedError("건너뜀 기록 삭제는 DB 담당 협의 필요")
