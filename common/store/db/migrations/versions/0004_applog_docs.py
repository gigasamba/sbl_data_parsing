"""op-01·op-17 applog 판 0004: 문서 사건 행에 원천 — applog는 여러 벌(인스턴스)이 함께 쓰므로 행만 보고 어느 원천·문서인지 알게.
pipe_event(월 파티션 부모 — ADD COLUMN은 파티션에 그대로 퍼짐): source_system(확장자·크기는 판 0001의 ext·file_bytes).
except_doc_info: file_ext(소문자, 점 없음 — `pdf`)·file_size(source_system은 판 0003에 있음). 새 칸은 비워 둠(NULL) — 옛 행은 채우지 않는다.
DDL은 이 판에 고정한다(현재 모델을 import하지 않음)."""

from alembic import context, op

revision = "0004_applog"
down_revision = "0003_applog"
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE {S}.pipe_event ADD COLUMN source_system TEXT",
    "ALTER TABLE {S}.except_doc_info ADD COLUMN file_ext TEXT, ADD COLUMN file_size BIGINT",
)


def upgrade():
    s = context.config.attributes["schema"]
    for sql in DDL:
        op.execute(sql.replace("{S}", s))


def downgrade():
    raise NotImplementedError("칸 지우기는 DB 담당 협의 필요")
