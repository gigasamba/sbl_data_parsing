"""applog 정본(op-01). MCP/pipe_event PK는 PG 제약에 따라 월 키를 포함한다.
pipe_run은 실행당 한 행으로 작아 일반 테이블(run_id PK)로 두고 보존 DELETE한다.
except_doc_info(적재되지 않은 문서 — 원본 키 + 종류 PK)는 일반 테이블 — 보존 DELETE 없음(skip 행을 지우면 그 문서를 다시 고름).
실행 중 DDL 금지: 생성/보존 관리는 Alembic과 dbtool maintain만 사용한다.
"""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

PARTITION_KEYS = {"mcp_log": "requested_at", "pipe_event": "ts_start"}
JSON_COLUMNS = {"result_keys", "code_fp", "metrics"}


def log_metadata(schema="applog"):
    md = MetaData(schema=schema)
    specs = {
        "mcp_log": {
            "id": BigInteger,
            "request_id": UUID,
            "session_id": String(128),
            "turn_id": String(128),
            "agent_id": SmallInteger,
            "api_key_id": Integer,
            "knox_id": String(64),
            "requested_at": DateTime(timezone=True),
            "finished_at": DateTime(timezone=True),
            "duration_ms": Integer,
            "queue_wait_ms": Integer,
            "rpc_method": String(32),
            "tool_name": String(64),
            "status": String(16),
            "error_code": String(64),
            "error_message": Text,
            "args": Text,
            "args_bytes": Integer,
            "args_truncated": Boolean,
            "result": Text,
            "result_bytes": Integer,
            "result_truncated": Boolean,
            "result_sha256": CHAR(64),
            "result_keys": JSONB,
            "result_count": Integer,
            "client_ip": INET,
            "app_version": String(32),
        },
        "pipe_run": {
            "run_id": UUID,
            "command": Text,
            "args": Text,
            "started_at": DateTime(timezone=True),
            "ended_at": DateTime(timezone=True),
            "duration_ms": Integer,
            "status": Text,
            "host": Text,
            "pid": Integer,
            "app_version": Text,
            "run_env": Text,
            "code_fp": JSONB,
            "stack": Text,
            "settings_hash": Text,
            "docs_total": Integer,
            "docs_ok": Integer,
            "docs_fail": Integer,
            "docs_reused": Integer,
            "workers": Integer,
            "cpu_max_load": Float,
            "mem_start_pct": Float,
        },
        "pipe_event": {
            "id": BigInteger,
            "ts_start": DateTime(timezone=True),
            "ts_end": DateTime(timezone=True),
            "run_id": UUID,
            "span_id": UUID,
            "parent_id": UUID,
            "layer": Text,
            "stage": Text,
            "engine": Text,
            "model": Text,
            "attempt": Integer,
            "doc_id": Text,
            "ext": Text,
            "file_bytes": BigInteger,
            "seq": Integer,
            "total": Integer,
            "duration_ms": Integer,
            "wait_mem_ms": Integer,
            "wait_cpu_ms": Integer,
            "cpu_ms": Integer,
            "ext_call_ms": Integer,
            "rss_peak_mb": Float,
            "load1_per_cpu_start": Float,
            "load1_per_cpu_end": Float,
            "mem_used_pct": Float,
            "inflight": Integer,
            "metrics": JSONB,
            "status": Text,
            "err_kind": Text,
            "err": Text,
            "app_version": Text,
        },
    }
    for name, fields in specs.items():
        partition = PARTITION_KEYS.get(name)
        pk = {"id", partition} if partition else {"run_id"}
        cols = []
        for key, type_ in fields.items():
            kw = {"primary_key": key in pk}
            if key == "id":
                kw["autoincrement"] = True
            if key in ("requested_at", "ts_start", "started_at"):
                kw.update(nullable=False, server_default=text("now()"))
            cols.append(Column(key, type_, **kw))
        table = Table(name, md, *cols, **({"postgresql_partition_by": f"RANGE ({partition})"} if partition else {}))
        if name == "mcp_log":
            table.append_constraint(
                CheckConstraint("status IN ('ok','error','denied','unauthorized','busy','timeout')", name="mcp_log_status")
            )
            table.append_constraint(CheckConstraint("rpc_method IN ('initialize','tools/list','tools/call')", name="mcp_log_rpc_method"))
            Index("ix_mcp_log_time", table.c.requested_at, postgresql_using="brin")
            Index("ix_mcp_log_agent_time", table.c.agent_id, table.c.requested_at)
            Index("ix_mcp_log_session_time", table.c.session_id, table.c.requested_at)
            Index("ix_mcp_log_knox_time", table.c.knox_id, table.c.requested_at)
            Index("ix_mcp_log_tool_time", table.c.tool_name, table.c.requested_at)
            Index("ix_mcp_log_request", table.c.request_id)
        elif name == "pipe_event":
            table.append_constraint(CheckConstraint("status IN ('ok','fail','timeout','skip','reused')", name="pipe_event_status"))
            table.append_constraint(CheckConstraint("err_kind IN ('env','timeout','doc','external','db')", name="pipe_event_err_kind"))
            Index("ix_pipe_event_ts", table.c.ts_start, postgresql_using="brin")
            Index("ix_pipe_event_run", table.c.run_id)
            Index("ix_pipe_event_stage_ts", table.c.stage, table.c.ts_start)
        else:
            Index("ix_pipe_run_started", table.c.started_at)
    # 적재되지 않은 문서(op-17 — 판 0003, 옛 skip_doc_info): 원본 키 + 종류당 한 행, pipeline/shared/except_docs가 upsert.
    # except_type skip = 영구 뺌(미지원·DRM·암호·내용 중복 — 대상 목록이 뺌) · error = 파싱·적재 실패(기록만 — 다음 실행이 다시 고름). 작은 일반 표.
    now = text("now()")
    Table(
        "except_doc_info",
        md,
        Column("source_key", Text, primary_key=True),
        Column("except_type", Text, primary_key=True),
        Column("source_system", Text),
        Column("file_name", Text),
        Column("reason", Text, nullable=False),
        Column("level", Text, nullable=False, server_default=text("'error'")),
        Column("first_seen", DateTime(timezone=True), nullable=False, server_default=now),
        Column("last_seen", DateTime(timezone=True), nullable=False, server_default=now),
        Column("count", Integer, nullable=False, server_default=text("1")),
    )
    return md


def index_defs():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex

    definitions = {}
    for table in log_metadata().tables.values():
        for index in table.indexes:
            sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            if " USING " not in sql:
                sql = sql.replace(" (", " USING btree (")
            definitions[index.name] = sql.replace("applog.", "{S}.")
    return definitions
