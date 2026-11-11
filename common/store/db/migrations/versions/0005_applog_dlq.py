"""pl-69 applog 판 0005: 실패 문서 재시도 상태. DDL은 이 판에 고정(현재 모델을 import하지 않음)."""

from alembic import context, op

revision = "0005_applog"
down_revision = "0004_applog"
branch_labels = None
depends_on = None

DDL = """CREATE TABLE {S}.dlq_doc (
    source_key TEXT PRIMARY KEY,
    source_system TEXT,
    file_name TEXT,
    stage TEXT,
    last_reason TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending' CONSTRAINT dlq_doc_status CHECK (status IN ('pending','dead','resolved')),
    first_failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    last_failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    dead_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    pipeline_version TEXT
)"""
INDEX = "CREATE INDEX ix_dlq_doc_status_failed ON {S}.dlq_doc (status, last_failed_at)"


def upgrade():
    s = context.config.attributes["schema"]
    for sql in (DDL, INDEX):
        op.execute(sql.replace("{S}", s))


def downgrade():
    raise NotImplementedError("DLQ 표 지우기는 DB 담당 협의 필요")
