"""applog 정본(op-01). MCP/pipe_event PK는 PG 제약에 따라 월 키를 포함한다.
pipe_run은 실행당 한 행으로 작아 일반 테이블(run_id PK)로 두고 보존 DELETE한다.
실행 중 DDL 금지: 생성/보존 관리는 Alembic과 dbtool maintain만 사용한다.
"""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, Index, Integer, MetaData, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

PARTITION_KEYS = {"mcp_call": "ts", "pipe_event": "ts_start"}
JSON_COLUMNS = {"client_info", "result_keys", "code_fp", "metrics"}


def log_metadata(schema="applog"):
    md = MetaData(schema=schema)
    specs = {
        "mcp_call": {
            "id": BigInteger,
            "ts": DateTime(timezone=True),
            "request_id": UUID,
            "session_id": Text,
            "tool": Text,
            "agent": Text,
            "user_id": Text,
            "remote_addr": Text,
            "client_info": JSONB,
            "args": Text,
            "args_bytes": Integer,
            "args_truncated": Boolean,
            "result": Text,
            "result_bytes": Integer,
            "result_truncated": Boolean,
            "result_sha256": Text,
            "result_keys": JSONB,
            "status": Text,
            "err": Text,
            "queue_wait_ms": Integer,
            "duration_ms": Integer,
            "app_version": Text,
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
            if key in ("ts", "ts_start", "started_at"):
                kw.update(nullable=False, server_default=text("now()"))
            cols.append(Column(key, type_, **kw))
        table = Table(name, md, *cols, **({"postgresql_partition_by": f"RANGE ({partition})"} if partition else {}))
        if name == "mcp_call":
            table.append_constraint(CheckConstraint("status IN ('ok','error','busy','timeout','unauthorized')", name="mcp_call_status"))
            Index("ix_mcp_call_ts", table.c.ts, postgresql_using="brin")
            Index("ix_mcp_call_user_ts", table.c.user_id, table.c.ts)
            Index("ix_mcp_call_tool_ts", table.c.tool, table.c.ts)
            Index("ix_mcp_call_request", table.c.request_id)
        elif name == "pipe_event":
            table.append_constraint(CheckConstraint("status IN ('ok','fail','timeout','skip','reused')", name="pipe_event_status"))
            table.append_constraint(CheckConstraint("err_kind IN ('env','timeout','doc','external','db')", name="pipe_event_err_kind"))
            Index("ix_pipe_event_ts", table.c.ts_start, postgresql_using="brin")
            Index("ix_pipe_event_run", table.c.run_id)
            Index("ix_pipe_event_stage_ts", table.c.stage, table.c.ts_start)
        else:
            Index("ix_pipe_run_started", table.c.started_at)
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
