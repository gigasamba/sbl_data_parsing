"""op-17 applog 판 0003: 적재되지 않은 문서 표 except_doc_info(원본 키 + 종류당 한 행)가 skip_doc_info(판 0002)를 바꾼다.
except_type `skip`(영구 뺌) · `error`(파싱·적재 실패 — 기록만). skip_doc_info 행은 `skip`으로 옮긴다. 옛 표 skip_doc_info는 이 판이 지우지 않는다
(지우기는 되돌릴 수 없어 사람이 확인한 뒤 DB 담당자가 — refactor.md). 앱은 옛 표를 더 읽거나 쓰지 않는다.
DDL은 이 판에 고정한다(현재 모델을 import하지 않음)."""

from alembic import context, op

revision = "0003_applog"
down_revision = "0002_applog"
branch_labels = None
depends_on = None

DDL = """CREATE TABLE {S}.except_doc_info (
    source_key TEXT NOT NULL,
    except_type TEXT NOT NULL,
    source_system TEXT,
    file_name TEXT,
    reason TEXT NOT NULL,
    level TEXT DEFAULT 'error' NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    count INTEGER DEFAULT 1 NOT NULL,
    PRIMARY KEY (source_key, except_type)
)"""
COPY = """INSERT INTO {S}.except_doc_info (source_key, except_type, source_system, file_name, reason, level, first_seen, last_seen, count)
SELECT source_key, 'skip', source_system, file_name, reason, level, first_seen, last_seen, count FROM {S}.skip_doc_info"""


def upgrade():
    s = context.config.attributes["schema"]
    for sql in (DDL, COPY):
        op.execute(sql.replace("{S}", s))


def downgrade():
    raise NotImplementedError("제외 기록 되돌리기는 DB 담당 협의 필요")
