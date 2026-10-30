"""op-01 F2: 계측 fail-soft(P1-2) · err allowlist(P2-5) · cpu_ms 범위(P2-6) — 외부 접속 없음, 로그 쪽 장애는 patch.object로."""

import io
import subprocess
import sys
import threading
import uuid
from contextlib import redirect_stderr
from unittest import mock

from common.core import jsonlog, span
from common.core import resources as RS
from pipeline.shared import runtrace

jsonlog._inherited.clear()

_BUSY = "import time\nt=time.process_time()\nwhile time.process_time()-t<0.3: pass"


def _capture():
    rows = []
    return rows, mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row))


def _reset_warn():
    span._FAIL.update(count=0, warned=False)


def test_emit_oserror_keeps_ok_block_ok():
    """P1-2 재현: _emit이 OSError를 내도 정상 블록은 정상 종료하고 결과를 바꾸지 않는다. 경고는 프로세스당 1회."""
    _reset_warn()
    buf = io.StringIO()
    with mock.patch.object(span, "_emit", side_effect=OSError(13, "Permission denied")), redirect_stderr(buf):
        with jsonlog.context(run_id=str(uuid.uuid4())):
            for _ in range(3):
                with span.span("extract.parse", doc_id="a.pdf") as sp:
                    sp.add(pages=1)
                    value = 42
    assert value == 42 and span.failure_count() == 3
    assert buf.getvalue().count("[applog]") == 1 and "EACCES" in buf.getvalue()


def test_business_exception_not_masked_by_emit_failure():
    """P1-2: 종료 기록이 실패해도 업무 예외는 원래 타입·메시지로 전파."""
    _reset_warn()
    with mock.patch.object(span, "_emit", side_effect=OSError("disk full")), redirect_stderr(io.StringIO()):
        with jsonlog.context(run_id=str(uuid.uuid4())):
            try:
                with span.span("transform.structure", doc_id="d"):
                    raise ValueError("업무 오류 원문")
            except ValueError as ex:
                assert str(ex) == "업무 오류 원문"
            else:
                raise AssertionError("업무 예외가 삼켜짐")
            try:
                with span.span("transform.structure", doc_id="d"):
                    raise KeyError("k")
            except KeyError:
                pass
            else:
                raise AssertionError("업무 예외가 삼켜짐")


def test_start_measurement_failure_degrades_to_null_or_missing_cols():
    """P1-2: 시작 측 자원 측정(proc_usage·load)이 OSError여도 업무는 그대로, 열은 NULL."""
    _reset_warn()
    rows, patched = _capture()
    boom = mock.Mock(side_effect=OSError("proc gone"))
    with (
        patched,
        mock.patch.object(span, "proc_usage", boom),
        mock.patch.object(span, "_load1_per_cpu", boom),
        redirect_stderr(io.StringIO()),
    ):
        with jsonlog.context(run_id=str(uuid.uuid4())):
            with span.span("load.pgvector", "load", cpu=True) as sp:
                sp.add(rows=3)
            try:
                with span.span("load.pgvector", "load", cpu=True):
                    raise RuntimeError("원래 오류")
            except RuntimeError as ex:
                assert str(ex) == "원래 오류"
    assert len(rows) == 2 and all(r["cpu_ms"] is None and r["load1_per_cpu_start"] is None for r in rows)
    assert rows[1]["status"] == "fail" and span.open_counts() == {} and not span._CPU_OPEN


def test_logger_setup_failure_is_soft_and_retried_later():
    """P1-2: 로그 디렉터리 권한 오류로 FileHandler 생성이 실패(jsonlog.setup) — span·run.progress·debug_event 모두 조용히 지나감."""
    _reset_warn()
    saved = dict(span._STATE)
    span._STATE.update(log=None, retry_at=0.0)
    try:
        with mock.patch.object(jsonlog, "setup", side_effect=PermissionError(13, "denied")) as setup, redirect_stderr(io.StringIO()):
            with jsonlog.context(run_id=str(uuid.uuid4())):
                with span.span("extract.parse"):
                    pass
                span.debug_event("model.llm", ms=1)
                runtrace._emit_run({"run_id": "r"}, "run.end")
        assert setup.call_count == 1  # 실패 직후에는 다시 열어 보지 않음(_RETRY_SEC 뒤에 재시도)
    finally:
        span._STATE.update(saved)


def test_handler_raising_does_not_leak():
    """P1-2: sink handler.emit이 예외를 내도(logging은 custom handler 예외를 안 삼킴) span 종료가 전파하지 않는다."""
    import logging

    class Bad(logging.Handler):
        def emit(self, record):
            raise OSError("sink down")

    log = logging.getLogger("span-soft-test")
    log.handlers[:] = [Bad()]
    log.propagate = False
    log.setLevel(logging.INFO)
    saved = span._STATE["log"]
    span._STATE["log"] = log
    try:
        with redirect_stderr(io.StringIO()), jsonlog.context(run_id=str(uuid.uuid4())):
            with span.span("extract.parse") as sp:
                sp.add(pages=1)
            span.instant("extract.plan", "reused")
    finally:
        span._STATE["log"] = saved
        log.handlers[:] = []


def test_span_api_misuse_is_soft_but_result_validation_kept():
    """Span 메서드는 잘못된 값에도 업무 코드에 예외를 안 던진다(체인 유지). result()의 status 검증은 프로그래머 오류라 그대로."""
    _reset_warn()
    rows, patched = _capture()
    with patched, redirect_stderr(io.StringIO()), jsonlog.context(run_id=str(uuid.uuid4())):
        with span.span("embed.bundle") as sp:
            assert sp.observe("x", "not-a-number").add_wait(mem_ms="x").set(pages=1) is sp
    assert rows[0]["status"] == "ok" and span.failure_count() >= 2


def test_run_start_end_failures_are_soft():
    """P1-2: pipe_run 시작·종료 기록이 실패해도 정상 종료, 업무 예외는 원래 그대로."""
    _reset_warn()
    with mock.patch.object(runtrace, "_emit_run", side_effect=OSError("down")), redirect_stderr(io.StringIO()):
        with runtrace.run("parse", ["--x"]) as run_id:
            assert run_id
        try:
            with runtrace.run("parse", []):
                raise ValueError("진짜 오류")
        except ValueError as ex:
            assert str(ex) == "진짜 오류"
        else:
            raise AssertionError("업무 예외가 삼켜짐")
    assert span.failure_count() >= 2


def test_run_progress_thread_survives_and_never_raises():
    """P1-2: done()이 예외를 내도 run.progress 스레드가 죽지 않고 __exit__도 전파하지 않는다. 스레드 생성 실패도 무시."""
    _reset_warn()
    calls = []

    def done():
        calls.append(1)
        raise OSError("counter gone")

    with redirect_stderr(io.StringIO()), jsonlog.context(run_id=str(uuid.uuid4())):
        with runtrace.Progress(total=3, done=done, every=0.01) as pg:
            for _ in range(100):
                if len(calls) >= 3:
                    break
                threading.Event().wait(0.02)
            assert pg._thread.is_alive()  # 첫 실패 뒤에도 계속 돈다
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("can't start new thread")):
            with runtrace.Progress(total=1, done=lambda: 1):
                pass
    assert len(calls) >= 3


def test_err_never_stores_exception_text():
    """P2-5: 따옴표 없는 본문·짧은 인용을 담은 예외도 err에는 타입 이름만 — pipe_event.err와 JSON 로그 err 모두."""
    rows, patched = _capture()
    body = "환자 홍길동 혈압 120/80 그대로 에코된 문서 본문"
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        for exc in (ValueError(body), RuntimeError(f"bad 'abc' {body}"), subprocess.CalledProcessError(2, ["x", body])):
            try:
                with span.span("extract.parse", doc_id="d.pdf"):
                    raise exc
            except Exception:
                pass
        with span.span("extract.parse") as sp:  # result()에 글자로 준 외부 오류 문자열도 클래스 이름만
            sp.result("fail", "doc", f"RuntimeError: {body}")
        with span.span("extract.parse") as sp:
            sp.result("fail", "doc", f"문서 내용 시작 {body}")
        with span.span("extract.parse") as sp:
            sp.result("skip", "env", span.safe("건너뜀(환경)"))
        with span.span("extract.parse") as sp:
            sp.result("fail", "doc", span.safe(None))
    errs = [r["err"] for r in rows]
    assert errs == ["ValueError", "RuntimeError", "CalledProcessError[rc=2]", "RuntimeError", None, "건너뜀(환경)", None]
    assert not any(body in str(r) for r in rows) and "abc" not in str(rows)


def test_err_reaches_json_log_as_label_only():
    """P2-5: _emit이 로거에 넘기는 extra.err도 같은 안전 글자(JSON 로그·DB 공통 경로)."""
    seen = []
    log = mock.Mock()
    log.log.side_effect = lambda level, msg, extra=None: seen.append(extra)
    with mock.patch.object(span, "_logger", return_value=log), jsonlog.context(run_id=str(uuid.uuid4())):
        try:
            with span.span("extract.parse"):
                raise OSError(2, "No such file: /data/문서본문.pdf")
        except OSError:
            pass
    assert seen[0]["err"] == "FileNotFoundError[ENOENT]" and "문서본문" not in str(seen)


def test_exc_label_and_safe_err_rules():
    assert span.exc_label(SystemExit(3)) == "SystemExit[code=3]" and span.exc_label(KeyError("secret-key")) == "KeyError"
    assert span.safe_err(None) is None and span.safe_err("") is None
    assert span.safe_err("ValueError: x") == "ValueError" and span.safe_err("some text ValueError: x") is None
    assert span.safe_err(span.safe("가" * 300)) == "가" * 200


def test_cpu_ms_includes_child_process_work():
    """P2-6: 자식 프로세스(subprocess)가 CPU를 쓴 cpu=True span의 cpu_ms는 0이 아니다(또는 측정 불가면 NULL — 0으로 채우지 않음)."""
    rows, patched = _capture()
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        with span.span("load.pgvector", "load", cpu=True):
            subprocess.run([sys.executable, "-c", _BUSY], check=True)
    cpu = rows[0]["cpu_ms"]
    assert cpu is None or cpu >= 150, cpu
    if span.resource is not None:
        assert cpu is not None


def test_cpu_ms_via_gated_popen_child():
    """P2-6: gated_popen으로 띄운 자식 작업도 포함(실제 프로덕션 경로)."""
    rows, patched = _capture()
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        with span.span("load.pgvector", "load", cpu=True):
            RS.gated_popen([sys.executable, "-c", _BUSY]).wait()
    cpu = rows[0]["cpu_ms"]
    assert cpu is None or cpu >= 150, cpu


def test_cpu_ms_null_when_cpu_spans_overlap():
    """P2-6: 서로 조상이 아닌 cpu=True span이 겹치면 둘 다 NULL(어느 쪽 CPU인지 가를 수 없음). 중첩(부모-자식)은 NULL이 아님."""
    rows, patched = _capture()
    gate_in, gate_out = threading.Event(), threading.Event()
    run_id = str(uuid.uuid4())

    def other():
        with jsonlog.context(run_id=run_id, span_id=None):
            with span.span("represent.a", cpu=True):
                gate_in.set()
                gate_out.wait(5)

    with patched, jsonlog.context(run_id=run_id):
        t = threading.Thread(target=other)
        t.start()
        gate_in.wait(5)
        with span.span("represent.b", cpu=True):
            gate_out.set()
            t.join(5)
        with span.span("outer", cpu=True):
            with span.span("inner", cpu=True):
                pass
    by_stage = {r["stage"]: r for r in rows}
    assert by_stage["represent.a"]["cpu_ms"] is None and by_stage["represent.b"]["cpu_ms"] is None
    if span.resource is not None:
        assert by_stage["outer"]["cpu_ms"] is not None and by_stage["inner"]["cpu_ms"] is not None
    assert not span._CPU_OPEN
