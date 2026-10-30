"""PC 전용 loopback PG: applog Alembic up/check·월 파티션·UPSERT·보존 DROP, 시험 스키마 정리."""

import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from common.config import settings
from common.core import paths
from common.store import logsink
from common.store.db import dbtool
from common.store.db.migrations.applog_parts import month_start, next_month

INPROCESS = True


def test_applog_migration():
    pg = settings.cfg().connections.pg
    if not paths.LOCAL_RUN or pg.host not in ("127.0.0.1", "localhost", "::1") or not pg.port:
        pytest.skip("명시적 PC 전용 loopback PG 설정 필요")
    schema = f"test_applog_{uuid.uuid4().hex[:10]}"
    eng = dbtool.engine()
    try:
        with settings.isolated(NO_PAID_CALLS="1"):
            for cmd in ("up", "up", "check", "maintain", "check"):
                result = subprocess.run(
                    [sys.executable, "-m", "common.store.db.dbtool", cmd, "--target", "applog", "--schema", schema],
                    env=settings.child_env(),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode == 0, result.stdout + result.stderr
            with eng.connect() as conn:
                st, _, rep = dbtool.check("applog", schema, conn=conn)
                assert st == "끝" and rep is not None and not rep.diffs, rep.lines() if rep else "no tables"
                names = set(conn.exec_driver_sql(f"SELECT tablename FROM pg_tables WHERE schemaname='{schema}'").scalars())
                assert {"mcp_call", "pipe_run", "pipe_event", "alembic_version"} <= names
                assert len([n for n in names if n.startswith(("mcp_call_", "pipe_event_"))]) == 6
                constraints = set(
                    conn.exec_driver_sql(
                        f"SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='{schema}' AND c.contype='c'"
                    ).scalars()
                )
                assert {"mcp_call_status", "pipe_event_status", "pipe_event_err_kind"} <= constraints
            run_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            sink = logsink.Sink(writer=partial(logsink._write_db, schema=schema), flush_sec=60)
            sink.emit("pipe_run", {"run_id": run_id, "started_at": now, "status": "running", "code_fp": {"p0": "test"}})
            sink.close()
            with eng.connect() as conn:
                assert conn.exec_driver_sql(f"SELECT status FROM {schema}.pipe_run").scalar() == "running"
            sink = logsink.Sink(writer=partial(logsink._write_db, schema=schema), flush_sec=60)
            sink.emit("pipe_run", {"run_id": run_id, "started_at": now, "ended_at": now, "status": "ok", "docs_total": 1})
            sink.emit(
                "mcp_call",
                {
                    "ts": now,
                    "request_id": str(uuid.uuid4()),
                    "status": "ok",
                    "client_info": {"password": "never-store"},
                    "result_keys": {"chunks": [1, 2]},
                },
            )
            sink.emit(
                "pipe_event",
                {"ts_start": now, "run_id": run_id, "span_id": str(uuid.uuid4()), "stage": "test", "status": "ok", "metrics": {"count": 2}},
            )
            sink.close()
            assert sink.stats()["written"] == 3 and sink.stats()["fallback"] == 0
            with eng.connect() as conn:
                assert conn.exec_driver_sql(f"SELECT count(*) FROM {schema}.pipe_run").scalar() == 1
                assert conn.exec_driver_sql(f"SELECT status FROM {schema}.pipe_run").scalar() == "ok"
                assert conn.exec_driver_sql(f"SELECT client_info FROM {schema}.mcp_call").scalar() == {"password": "***"}
                assert conn.exec_driver_sql(f"SELECT metrics FROM {schema}.pipe_event").scalar() == {"count": 2}
            start = month_start(now - timedelta(days=400))
            end = next_month(start)
            with eng.begin() as conn, Operations.context(MigrationContext.configure(conn)) as op:
                for parent in ("mcp_call", "pipe_event"):
                    op.execute(
                        f"CREATE TABLE {schema}.{parent}_{start:%Y%m} PARTITION OF {schema}.{parent} FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
                    )
                conn.exec_driver_sql(
                    f"INSERT INTO {schema}.pipe_run (run_id, started_at, status) VALUES (%(id)s, %(ts)s, 'running')",
                    {"id": str(uuid.uuid4()), "ts": start},
                )
            with eng.begin() as conn:
                report = dbtool.maintain_applog(schema, conn=conn, now=now)
                assert set(report["dropped"]) == {f"{t}_{start:%Y%m}" for t in ("mcp_call", "pipe_event")}
                assert conn.exec_driver_sql(f"SELECT count(*) FROM {schema}.pipe_run").scalar() == 1
            with eng.connect() as conn:
                assert not dbtool.check("applog", schema, conn=conn)[2].diffs
    finally:
        assert schema.startswith("test_applog_") and len(schema) == len("test_applog_") + 10
        with eng.begin() as conn, Operations.context(MigrationContext.configure(conn)) as op:
            op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        with eng.connect() as conn:
            assert not conn.exec_driver_sql("SELECT 1 FROM pg_namespace WHERE nspname=%(s)s", {"s": schema}).first()
        eng.dispose()
