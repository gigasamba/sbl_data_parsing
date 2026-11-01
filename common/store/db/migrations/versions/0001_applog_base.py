"""op-01 applog 기준판: 감사 호출·실행 요약·단계 사건, 현재/앞으로 2개월 파티션.
스키마 DDL은 이 판에 고정한다(현재 모델을 import하지 않음). 배포 후에는 새 판을 추가한다.
"""

from alembic import context, op

from common.store.db.migrations.applog_parts import ensure_partitions

revision = "0001_applog"
down_revision = None
branch_labels = ("applog",)
depends_on = None

DDL = (
    """CREATE TABLE {S}.mcp_call (
    id BIGSERIAL NOT NULL,
    ts TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    request_id UUID,
    session_id TEXT,
    tool TEXT,
    agent TEXT,
    user_id TEXT,
    args TEXT,
    args_bytes INTEGER,
    args_truncated BOOLEAN,
    result TEXT,
    result_bytes INTEGER,
    result_truncated BOOLEAN,
    result_sha256 TEXT,
    result_keys JSONB,
    status TEXT,
    err TEXT,
    queue_wait_ms INTEGER,
    duration_ms INTEGER,
    app_version TEXT,
    PRIMARY KEY (id, ts),
    CONSTRAINT mcp_call_status CHECK (status IN ('ok','error','busy','timeout','unauthorized'))
)
 PARTITION BY RANGE (ts)""",
    """CREATE INDEX ix_mcp_call_request ON {S}.mcp_call (request_id)""",
    """CREATE INDEX ix_mcp_call_tool_ts ON {S}.mcp_call (tool, ts)""",
    """CREATE INDEX ix_mcp_call_ts ON {S}.mcp_call USING brin (ts)""",
    """CREATE INDEX ix_mcp_call_user_ts ON {S}.mcp_call (user_id, ts)""",
    """CREATE TABLE {S}.pipe_event (
    id BIGSERIAL NOT NULL,
    ts_start TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    ts_end TIMESTAMP WITH TIME ZONE,
    run_id UUID,
    span_id UUID,
    parent_id UUID,
    layer TEXT,
    stage TEXT,
    engine TEXT,
    model TEXT,
    attempt INTEGER,
    doc_id TEXT,
    ext TEXT,
    file_bytes BIGINT,
    seq INTEGER,
    total INTEGER,
    duration_ms INTEGER,
    wait_mem_ms INTEGER,
    wait_cpu_ms INTEGER,
    cpu_ms INTEGER,
    ext_call_ms INTEGER,
    rss_peak_mb FLOAT,
    load1_per_cpu_start FLOAT,
    load1_per_cpu_end FLOAT,
    mem_used_pct FLOAT,
    inflight INTEGER,
    metrics JSONB,
    status TEXT,
    err_kind TEXT,
    err TEXT,
    app_version TEXT,
    PRIMARY KEY (id, ts_start),
    CONSTRAINT pipe_event_status CHECK (status IN ('ok','fail','timeout','skip','reused')),
    CONSTRAINT pipe_event_err_kind CHECK (err_kind IN ('env','timeout','doc','external','db'))
)
 PARTITION BY RANGE (ts_start)""",
    """CREATE INDEX ix_pipe_event_run ON {S}.pipe_event (run_id)""",
    """CREATE INDEX ix_pipe_event_stage_ts ON {S}.pipe_event (stage, ts_start)""",
    """CREATE INDEX ix_pipe_event_ts ON {S}.pipe_event USING brin (ts_start)""",
    """CREATE TABLE {S}.pipe_run (
    run_id UUID NOT NULL,
    command TEXT,
    args TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    status TEXT,
    host TEXT,
    pid INTEGER,
    app_version TEXT,
    run_env TEXT,
    code_fp JSONB,
    stack TEXT,
    settings_hash TEXT,
    docs_total INTEGER,
    docs_ok INTEGER,
    docs_fail INTEGER,
    docs_reused INTEGER,
    workers INTEGER,
    cpu_max_load FLOAT,
    mem_start_pct FLOAT,
    PRIMARY KEY (run_id)
)""",
    """CREATE INDEX ix_pipe_run_started ON {S}.pipe_run (started_at)""",
)


def upgrade():
    schema = context.config.attributes["schema"]
    for statement in DDL:
        op.execute(statement.replace("{S}", schema))
    ensure_partitions(op, schema)


def downgrade():
    raise NotImplementedError("감사 기록 삭제는 DB 담당 협의 필요")
