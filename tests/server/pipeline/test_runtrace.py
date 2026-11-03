"""op-01: pipe_run 시작·종료, 60초 run.progress 주기, run_all/parse_one 계측(외부 접속 없음)."""

import sys
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

from common.config import settings
from common.core import jsonlog, span
from common.core import resources as RS
from pipeline.shared import runtrace

jsonlog._inherited.clear()  # 추적 중인 실행(APPLOG_CONTEXT) 아래에서 돌아도 이 시험은 run_id 없는 상태에서 시작


def _runs():
    rows = []
    return rows, mock.patch.object(runtrace, "_emit_run", lambda row, event, level=None: rows.append((event, dict(row))))


def test_run_start_end_rows():
    rows, patched = _runs()
    with patched, mock.patch.object(runtrace, "_code_fp", lambda: {"p0": "aaa", "s": "bbb"}), settings.isolated(APPLOG_DB_ENABLED="1"):
        with runtrace.run("parse", ["parse", "--set", "X=1", "token=secret-value"]) as run_id:
            assert run_id and jsonlog.get_context()["run_id"] == run_id
            runtrace.info(stack="s1", workers=4)
            runtrace.docs(total=10, ok=8, fail=2, reused=3)
            with runtrace.run("pipeline", ["load"]) as inner:  # 부모가 이어준 run_id가 있으면 새 실행을 시작하지 않음
                assert inner is None
        assert jsonlog.get_context().get("run_id") is None
    assert [e for e, _ in rows] == ["run.start", "run.end"]
    start, end = rows[0][1], rows[1][1]
    assert start["status"] == "running" and start["command"] == "parse" and start["code_fp"] == {"p0": "aaa", "s": "bbb"}
    assert start["host"] and start["pid"] and start["app_version"] and len(start["settings_hash"]) == 12
    assert start["run_id"] == end["run_id"] == run_id
    assert end["status"] == "ok" and end["duration_ms"] >= 0 and end["ended_at"] >= start["started_at"]
    assert (end["stack"], end["workers"], end["docs_total"], end["docs_ok"], end["docs_fail"], end["docs_reused"]) == ("s1", 4, 10, 8, 2, 3)


def test_run_status_by_exit():
    for exc, status in (
        (SystemExit(75), "stopped"),
        (SystemExit(3), "fail"),
        (SystemExit(0), "ok"),
        (ValueError("x"), "fail"),
        (KeyboardInterrupt(), "interrupted"),
    ):
        rows, patched = _runs()
        with patched, mock.patch.object(runtrace, "_code_fp", lambda: {}):
            try:
                with runtrace.run("pipeline", ["night"]):
                    raise exc
            except BaseException as ex:
                assert ex is exc  # 그대로 다시 던짐
        assert rows[-1][0] == "run.end" and rows[-1][1]["status"] == status, (exc, rows[-1])


def test_tracing_failure_never_blocks():
    def boom(row, event, level=None):
        raise OSError("disk full")

    with mock.patch.object(runtrace, "_emit_run", boom), mock.patch.object(runtrace, "_code_fp", lambda: {}):
        with runtrace.run("pipeline", ["parse"]) as run_id:
            assert run_id  # 시작 기록이 실패해도 파이프라인은 그대로 돈다


def test_progress_every_period():
    rows = []
    done = [0]
    with mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)), jsonlog.context(run_id=str(uuid.uuid4())):
        with runtrace.Progress(total=10, done=lambda: done[0], unit="doc", every=0.05):
            with span.span("extract.parse", doc_id="a.pdf"):
                done[0] = 4
                time.sleep(0.3)
    progress = [r for r in rows if r["stage"] == "run.progress"]
    assert len(progress) >= 4, len(progress)  # 주기마다 + 마지막 1행
    last = progress[-1]
    assert (last["seq"], last["total"], last["layer"]) == (4, 10, "run")
    m = last["metrics"]
    assert m["unit"] == "doc" and m["per_min"] > 0 and m["eta_sec"] >= 0
    assert any(r["metrics"]["open"] == {"extract.parse": 1} for r in progress)  # 단계별 진행 중 개수
    assert progress[0]["parent_id"] is None and "load1_per_cpu_end" in last and "mem_used_pct" in last


def test_progress_without_run_has_no_thread():
    before = threading.active_count()
    with runtrace.Progress(total=1, done=lambda: 0, every=0.01):
        assert threading.active_count() == before


def test_run_all_job_spans_and_usage():
    from pipeline.extract import run_all

    rows = []
    with mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)), jsonlog.context(run_id=str(uuid.uuid4())):
        # 풀 스레드(--workers)에서도 span이 부모 아래에 붙는다
        def job(item):
            with span.span("extract.parse", doc_id=item[0].name, engine=item[1]):
                pass

        with span.span("extract.plan") as plan:
            run_all._run_docs([(Path("a.pdf"), "e1"), (Path("a.pdf"), "e2"), (Path("b.pdf"), "e1")], job, 2)
        jobs = [r for r in rows if r["stage"] == "extract.parse"]
        assert len(jobs) == 3 and {r["parent_id"] for r in jobs} == {plan.span_id}

        # 자식(parse_one)이 stdout에 남긴 자원 사용이 문서×엔진 span에 옮겨진다
        class Proc:
            pid, returncode = 1, 0

            def communicate(self, timeout=None):
                return "엔진 출력\n" + span.USAGE_PREFIX + '{"cpu_ms": 1234, "rss_peak_mb": 321.5}\n', ""

        rows.clear()
        with span.span("extract.parse", doc_id="a.pdf", engine="e1"):
            with mock.patch.object(RS, "gated_popen", lambda *a, **k: Proc()):
                run_all._isolated_once("e1", Path("a.pdf"), Path("/nonexistent/out.json"), "default", 5, sys.executable)
    assert rows[0]["cpu_ms"] == 1234 and rows[0]["rss_peak_mb"] == 321.5


def test_run_all_redact_shared():
    from pipeline.extract import run_all

    body = "민감한 문서 본문 조각이 여기에 길게 들어 있습니다 1234567890"
    assert run_all.redact(f"ValueError: '{body}'") == span.redact_text(f"ValueError: '{body}'") and body not in run_all.redact(
        f"E '{body}'"
    )
