"""PC 전용 loopback PG: 실행 1건의 pipe_run·pipe_event가 임시 스키마에 들어가고 perf.py가 DB에서 읽는다(시험 스키마 정리)."""

import subprocess
import sys
import uuid
from functools import partial
from unittest import mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from common.config import settings
from common.core import jsonlog, paths, span
from common.store import logsink
from common.store.db import dbtool
from pipeline.shared import runtrace
from pipeline.tools import perf

INPROCESS = True


def test_run_spans_reach_pg_and_perf_reads_them(tmp_path):
    pg = settings.cfg().connections.pg
    if not paths.LOCAL_RUN or pg.host not in ("127.0.0.1", "localhost", "::1") or not pg.port:
        pytest.skip("명시적 PC 전용 loopback PG 설정 필요")
    schema = f"test_t2perf_{uuid.uuid4().hex[:8]}"
    eng = dbtool.engine()
    try:
        with settings.isolated(NO_PAID_CALLS="1"):
            result = subprocess.run(
                [sys.executable, "-m", "common.store.db.dbtool", "up", "--target", "applog", "--schema", schema],
                env=settings.child_env(),
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        with (
            settings.isolated(NO_PAID_CALLS="1", APPLOG_DB_ENABLED="1", APPLOG_DIR=str(tmp_path), APPLOG_FALLBACK_DIR=str(tmp_path / "fb")),
            mock.patch.object(logsink, "_write_db", partial(logsink._write_db, schema=schema)),
            mock.patch.object(runtrace, "_code_fp", lambda: {"p0": "t2"}),
        ):
            span._STATE["log"] = None
            with runtrace.run("parse", ["parse"]) as run_id:
                runtrace.docs(total=2, ok=1, fail=1)
                with span.span("proc.run", "run", module="m"):
                    with span.span("extract.parse", doc_id="a.pdf", engine="pymupdf") as sp:
                        sp.add(pages=3)
                    try:
                        with span.span("extract.parse", doc_id="b.pdf", engine="pymupdf"):
                            raise TimeoutError("late")
                    except TimeoutError:
                        pass
                    with span.span("embed.bundle", "embed", model="api") as sp:
                        sp.add(cache_hit=9, cache_miss=1, batches=1)
                    with span.span("load.chunk", "load", table="chunk") as sp:
                        sp.rows(10)
            logsink.shutdown()
            assert logsink.stats()["fallback"] == 0
            run, events = perf.load_db(run_id, schema)
        assert run["status"] == "ok" and run["command"] == "parse" and run["docs_total"] == 2 and run["code_fp"] == {"p0": "t2"}
        assert {e["layer"] for e in events} >= {"run", "extract", "embed", "load"}
        parents = {e["span_id"]: e for e in events}
        proc = next(e for e in events if e["stage"] == "proc.run")
        assert all(
            parents[e["parent_id"]]["stage"] == "proc.run" for e in events if e["stage"] in ("extract.parse", "embed.bundle", "load.chunk")
        )
        assert proc["parent_id"] is None and all(str(e["run_id"]) == run_id for e in events)
        timeout = next(e for e in events if e["status"] == "timeout")
        assert timeout["err_kind"] == "timeout" and timeout["doc_id"] == "b.pdf"
        summary = perf.summarize(run, events)
        assert summary["ratios"]["embed_cache_hit_rate"] == 0.9 and any(s["fail_rate"] == 0.5 for s in summary["stages"])
    finally:
        assert schema.startswith("test_t2perf_") and len(schema) == len("test_t2perf_") + 8
        jsonlog.shutdown()
        with eng.begin() as conn, Operations.context(MigrationContext.configure(conn)) as op:
            op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        with eng.connect() as conn:
            assert not conn.exec_driver_sql("SELECT 1 FROM pg_namespace WHERE nspname=%(s)s", {"s": schema}).first()
        eng.dispose()
        span._STATE["log"] = None
