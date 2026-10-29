"""struct 판 0002 — 판 표 2개(S8b, D-031 — 사용자 10-28 Q1·Q2·Q5 a): 엔진 구성 `stack_version`·원천 목록 `source_version`(같은 모양) +
판 1 시드를 활성으로. 시드는 판 번호 붙인 사본 `resources/sql/0002_stack_seed.json`·`0002_sources_seed.json`(그때의 resources/config/
pipeline_stack.json 설정 칸·resources/mappings/sources.json — 한 번 배포하면 고치지 않음, 바꾸려면 set-stack·set-sources로 새 판).
표가 이미 있으면 실패한다(IF NOT EXISTS 없음 — 시드를 두 번 넣지 않게). 한 번 배포한 판은 고치지 않는다."""

import hashlib
import json

from alembic import context, op

from common.core.paths import RES_ROOT

revision = "0002_struct"
down_revision = "0001_struct"
branch_labels = None
depends_on = None

TABLE_SQL = """CREATE TABLE {S}.{T} (
    version_id   SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,                        -- 판 이름(엔진 구성 name, 예 dev-v1)
    body         JSONB NOT NULL,                       -- 설정 칸 전체(모양은 pydantic — common/store/db/schemas/config_body.py)
    body_sha     CHAR(64) NOT NULL UNIQUE,             -- 정규 JSON(키 정렬·공백 없음·UTF-8) sha256 — 같은 body는 한 판
    is_active    BOOLEAN NOT NULL DEFAULT false,       -- 활성 판(표마다 하나 — 아래 색인)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   TEXT,
    reason       TEXT,
    activated_at TIMESTAMPTZ,                          -- 마지막으로 활성이 된 때·사람(되돌리기 기록)
    activated_by TEXT
)"""
INDEX_SQL = "CREATE UNIQUE INDEX ux_{T}_active ON {S}.{T} (is_active) WHERE is_active"
SEEDS = (("stack_version", "0002_stack_seed.json"), ("source_version", "0002_sources_seed.json"))
SEED_DIR = RES_ROOT / "sql"


def _sha(body):  # cfgtables.sha와 같은 규칙을 이 판에 굳힘(dbtool selftest가 같은지 확인)
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def upgrade():
    s = context.config.attributes["schema"]
    bind = op.get_bind()
    for table, seed in SEEDS:
        bind.exec_driver_sql(TABLE_SQL.replace("{S}", s).replace("{T}", table))
        bind.exec_driver_sql(INDEX_SQL.replace("{S}", s).replace("{T}", table))
        doc = json.loads((SEED_DIR / seed).read_text(encoding="utf-8"))
        bind.exec_driver_sql(
            f"INSERT INTO {s}.{table} (name, body, body_sha, is_active, created_by, reason, activated_at, activated_by) "
            "VALUES (%(n)s, %(b)s::jsonb, %(h)s, true, 'migrate 0002', %(r)s, now(), 'migrate 0002')",
            {"n": doc["name"], "b": json.dumps(doc["body"], ensure_ascii=False), "h": _sha(doc["body"]), "r": doc["reason"]},
        )


def downgrade():
    raise NotImplementedError("판 표는 되돌리지 않음 — 지우려면 사람이(DB 담당 협의)")
