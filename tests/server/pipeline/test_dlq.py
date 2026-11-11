"""pl-69 — 실 PG 임시 스키마에서 실패 횟수·호스트 기록·해소·재투입·보존과 조회 CLI를 확인한다."""

import io
import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import common
from common.store.db import dbtool
from pipeline.shared import dlq as D
from pipeline.shared import except_docs as E
from tests.server.common import pgcase
from tests.server.pipeline.goldseed import applog


def row(key="SFDC/a.pdf", reason="parse_failed"):
    return {"source_key": key, "source_system": "SFDC", "file_name": "a.pdf", "reason": reason}


@contextmanager
def log_schema():
    with pgcase.schema() as base:
        schema = applog(base)
        with patch.object(E, "_schema", return_value=schema):
            yield schema


def test_failures_and_requeue():
    with log_schema():
        out = io.StringIO()
        with redirect_stdout(out):
            for i, status in ((1, "pending"), (2, "pending"), (3, "dead")):
                assert D.record_failure([row()]) == 1
                r = D.list_rows()[0]
                assert (r["attempts"], r["status"], r["stage"]) == (i, status, "parse")
                assert r["pipeline_version"] == common.pipeline_version()
            dead_at = r["dead_at"]
            D.record_failure([row(reason="load_failed")])
            r = D.list_rows()[0]
            assert (r["attempts"], r["status"], r["stage"], r["dead_at"]) == (3, "dead", "load", dead_at)
        assert out.getvalue().count("[DLQ] 확인 필요") == 1, out.getvalue()
        assert "3회 실패" in out.getvalue() and "list --status dead" in out.getvalue()
        assert not D.list_rows("pending") and row()["source_key"] in D.excluded_keys()
        assert D.requeue(["missing"]) == 0
        assert D.requeue([row()["source_key"]]) == 1
        assert D.list_rows()[0]["attempts"] == 0
        D.record_failure([row()])  # requeue 뒤 새 실패는 첫 시도
        assert (D.list_rows()[0]["attempts"], D.list_rows()[0]["status"]) == (1, "pending")
        D.record_failure([row("one"), row("two")], max_attempts=1)
        assert D.requeue(all_dead=True) == 2
        assert all(r["status"] == "pending" for r in D.list_rows())


def test_failures_and_resolve():
    with log_schema():
        D.record_failure([row()])
        D.record_failure([row(reason="publish_failed")])
        assert (D.list_rows()[0]["attempts"], D.list_rows()[0]["last_reason"]) == (2, "publish_failed")
        D.record_failure([row()])
        assert D.list_rows()[0]["attempts"] == 3
        assert D.resolve([row()["source_key"], row()["source_key"]]) == 1
        r = D.list_rows()[0]
        assert r["status"] == "resolved" and r["resolved_at"] is not None
        resolved_at = r["resolved_at"]
        D.resolve([row()["source_key"]])
        assert D.list_rows()[0]["resolved_at"] == resolved_at
        assert not D.excluded_keys()
        D.record_failure([row()])
        r = D.list_rows()[0]
        assert (r["attempts"], r["status"], r["dead_at"], r["resolved_at"]) == (1, "pending", None, None)
        D.resolve([row()["source_key"]])
        assert D.list_rows()[0]["status"] == "resolved"


def test_host_error_cli_and_history():
    with log_schema():
        E.record_error([row()])  # 컨테이너는 이력만
        assert not D.list_rows()
        args = ["--key", row()["source_key"], "--system", "SFDC", "--name", "a.pdf", "--reason", "parse_failed", "--dlq-only"]
        for i in range(1, 4):
            E._error_cmd(args)
            assert D.list_rows()[0]["attempts"] == i
        db = pgcase.connect(E._schema())
        try:
            assert db.q(f"SELECT count FROM {db.schema}.except_doc_info WHERE except_type='error'")[0]["count"] == 1
        finally:
            db.cn.close()
        E.record_part([row("part")])
        E.record_silver([row("silver")])
        assert len(D.list_rows()) == 1
        out = io.StringIO()
        with redirect_stdout(out):
            assert D.main(["list", "--status", "dead", "--json"]) == 0
        assert json.loads(out.getvalue())[0]["attempts"] == 3
        with redirect_stdout(io.StringIO()):
            D.main(["list", "--status", "all"])
            D.main(["requeue", "--key", row()["source_key"]])
        D.record_failure([row("other")], max_attempts=1)
        with redirect_stdout(io.StringIO()):
            D.main(["requeue", "--all-dead"])
        assert not D.list_rows("dead")


def test_logging_failure_continues():
    with patch.object(E, "_upsert", return_value=1), patch.object(D, "record_failure", side_effect=RuntimeError("secret")):
        err = io.StringIO()
        with redirect_stderr(err):
            assert E.record_error([row()], to_dlq=True) == 1
        assert "RuntimeError" in err.getvalue() and "secret" not in err.getvalue()
    with patch.object(E, "_db", side_effect=RuntimeError("secret")), redirect_stderr(io.StringIO()):
        assert D.resolve(["k"]) == 1


def test_resolved_retention():
    with log_schema() as s:
        D.record_failure([row("old"), row("new"), row("pending"), row("dead")])
        D.resolve(["old", "new"])
        db = pgcase.connect(s)
        try:
            old = datetime.now(UTC) - timedelta(days=365)
            db.q(f"UPDATE {s}.dlq_doc SET resolved_at = %s WHERE source_key IN ('old','pending','dead')", (old,))
            db.q(f"UPDATE {s}.dlq_doc SET status = 'dead' WHERE source_key = 'dead'")
        finally:
            db.cn.close()
        dbtool.maintain_applog(s)
        assert {r["source_key"] for r in D.list_rows()} == {"new", "pending", "dead"}


def test_concurrent_failures():
    from concurrent.futures import ThreadPoolExecutor

    with log_schema():
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(lambda _: D.record_failure([row()], max_attempts=10), range(4))) == [1] * 4
        assert D.list_rows()[0]["attempts"] == 4


def test_container_history_does_not_write_dlq():
    assert D.MAX_ATTEMPTS == 3
    with patch.object(D, "record_failure") as failure, patch.object(E, "_upsert"):
        E.record_error([row()])
        E.note_error([row()])
        E.record_part([row()])
        E.record_silver([row()])
        failure.assert_not_called()
        E.record_error([row()], to_dlq=True)
        failure.assert_called_once_with([row()])


def test_statuses_and_null_metadata():
    with log_schema():
        D.record_failure([row()])
        D.record_failure([{"source_key": row()["source_key"], "reason": "load_failed"}])
        r = D.list_rows()[0]
        assert (r["source_system"], r["file_name"], r["attempts"]) == ("SFDC", "a.pdf", 2)
        assert r["last_reason"] == "load_failed"
        D.record_failure([row("dead")], max_attempts=1)
        D.record_failure([row("resolved")])
        D.resolve(["resolved"])
        assert {r["source_key"] for r in D.list_rows(("pending", "dead"))} == {row()["source_key"], "dead"}
        out = io.StringIO()
        with redirect_stdout(out):
            D.main(["list", "--status", "pending,dead", "--json"])
        assert {r["source_key"] for r in json.loads(out.getvalue())} == {row()["source_key"], "dead"}


def test_error_cli_without_csv():
    import csv
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp, patch.object(E, "record_error") as record:
        path = Path(tmp) / "batch.csv"
        opt = ["--key", "SFDC/key ' ;$", "--system", "DEV-1", "--name", "a ' ;$.pdf", "--reason", "stage_failed"]
        assert E._error_cmd(opt) == 0
        assert record.call_args.args[0] == [
            {"source_key": "SFDC/key ' ;$", "source_system": "DEV-1", "file_name": "a ' ;$.pdf", "reason": "stage_failed"}
        ]
        assert E._error_cmd(["--csv", str(path), *opt]) == 0
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=("s3_key", "original_filename", "source_system"))
            writer.writeheader()
            writer.writerow({"s3_key": "from-csv", "original_filename": "csv.pdf", "source_system": "FAQ"})
        assert E._error_cmd(["--csv", str(path), *opt]) == 0
        assert record.call_args.args[0][0] == {"source_key": opt[1], "source_system": opt[3], "file_name": opt[5], "reason": "stage_failed"}
        assert E._error_cmd(["--csv", str(path), "--reason", "stage_failed"]) == 0
        assert record.call_args.args[0][0]["source_key"] == "from-csv"
        with redirect_stderr(io.StringIO()):
            try:
                E._error_cmd(["--reason", "stage_failed"])
            except SystemExit as ex:
                assert ex.code == 2
            else:
                raise AssertionError("no CSV or key must fail")


def test_error_cli_header_only_csv_uses_key():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp, patch.object(E, "record_error") as record:
        path = Path(tmp) / "batch.csv"
        path.write_text("s3_key,original_filename,source_system\n", encoding="utf-8")
        assert (
            E._error_cmd(["--csv", str(path), "--key", "SFDC/a.pdf", "--system", "SFDC", "--name", "a.pdf", "--reason", "stage_failed"])
            == 0
        )
        record.assert_called_once_with(
            [{"source_key": "SFDC/a.pdf", "source_system": "SFDC", "file_name": "a.pdf", "reason": "stage_failed"}],
            to_dlq=True,
            history=True,
        )


def test_error_cli_matching_csv_fills_metadata():
    import csv
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp, patch.object(E, "record_error") as record:
        path = Path(tmp) / "batch.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=("s3_key", "original_filename", "source_system", "file_size"))
            writer.writeheader()
            writer.writerows(
                [
                    {"s3_key": "other", "original_filename": "other.pdf", "source_system": "FAQ", "file_size": 99},
                    {"s3_key": "SFDC/key", "original_filename": "csv.pdf", "source_system": "SFDC", "file_size": 1234},
                ]
            )
        base = ["--csv", str(path), "--key", "SFDC/key", "--reason", "stage_failed"]
        for options, name, system in (
            ([], "csv.pdf", "SFDC"),
            (["--name", "", "--system", ""], "csv.pdf", "SFDC"),
            (["--name", "explicit.pdf"], "explicit.pdf", "SFDC"),
            (["--system", "DEV-1"], "csv.pdf", "DEV-1"),
            (["--name", "explicit.pdf", "--system", "DEV-1"], "explicit.pdf", "DEV-1"),
        ):
            assert E._error_cmd([*base, *options]) == 0
            assert record.call_args.args[0] == [
                {
                    "source_key": "SFDC/key",
                    "reason": "stage_failed",
                    "file_name": name,
                    "source_system": system,
                    "file_size": "1234",
                }
            ]
