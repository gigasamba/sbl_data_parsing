"""op-01: 파이프라인 span — 중첩·parent_id, 오류 status/err_kind, wait 분리, 자식 프로세스 전달, 스레드 carry, 검색 경로 no-op(외부 접속 없음)."""

import json
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from common.config import settings
from common.core import jsonlog, paths, span
from common.core import resources as RS

jsonlog._inherited.clear()  # 추적 중인 실행(APPLOG_CONTEXT) 아래에서 돌아도 이 시험은 run_id 없는 상태에서 시작


def _capture():
    rows = []
    return rows, mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row))


def test_no_run_is_noop():
    """run_id가 없으면(MCP 검색·시험) span은 가짜 — emit·로거·스레드 0. 질의 임베딩 경로도 그대로."""
    import numpy as np

    from common.ai import embed

    rows, patched = _capture()
    threads = threading.active_count()
    logger_before = span._STATE["log"]
    with patched, settings.isolated(EMBED_QUERY_CACHE="0"):
        with span.span("extract.parse", doc_id="a.pdf") as sp:
            assert sp is span.NULL
            sp.add(pages=3).observe("x", 1).set(engine="e").result("fail", "doc", "ignored")
        span.add_current(x=1)
        assert span.current() is None
        with mock.patch.object(embed, "_embed_api", lambda texts, kind="passage", timeout=None: np.ones((len(texts), 3), dtype=np.float32)):
            vec = embed.embed_texts("api", ["질문"], "query")
        assert vec.shape == (1, 3)
    assert rows == [] and threading.active_count() == threads and span._STATE["log"] is logger_before
    assert span.with_context({"env": {"A": "1"}}) == {"env": {"A": "1"}}  # run_id 없으면 자식 env를 건드리지 않음


def test_nesting_and_parent_ids():
    rows, patched = _capture()
    run_id = str(uuid.uuid4())
    with patched, jsonlog.context(run_id=run_id, span_id=None):
        with span.span("proc.run", "run", module="m") as outer:
            with span.span("extract.parse", doc_id="a.pdf", engine="pdfplumber", file_bytes=10) as inner:
                assert span.current() is inner
                inner.add(pages=2).add(pages=3)
            assert span.current() is outer
        with span.span("transform.represent", doc_id="a.pdf"):
            pass
        assert jsonlog.get_context().get("span_id") is None
    by_stage = {r["stage"]: r for r in rows}
    assert [r["stage"] for r in rows] == ["extract.parse", "proc.run", "transform.represent"]  # 끝난 순서
    assert by_stage["extract.parse"]["parent_id"] == by_stage["proc.run"]["span_id"]
    assert by_stage["proc.run"]["parent_id"] is None and by_stage["transform.represent"]["parent_id"] is None
    assert all(r["run_id"] == run_id for r in rows)
    inner_row = by_stage["extract.parse"]
    assert inner_row["layer"] == "extract" and inner_row["engine"] == "pdfplumber" and inner_row["file_bytes"] == 10
    assert inner_row["metrics"] == {"pages": 5} and inner_row["status"] == "ok" and inner_row["duration_ms"] >= 0
    assert by_stage["proc.run"]["layer"] == "run" and by_stage["proc.run"]["metrics"] == {"module": "m"}
    assert span.open_counts() == {}


def test_error_status_and_kind():
    class OperationalError(Exception):
        pass

    rows, patched = _capture()
    cases = [
        (ValueError("bad"), "fail", "doc"),
        (TimeoutError("late"), "timeout", "timeout"),
        (subprocess.TimeoutExpired("x", 1), "timeout", "timeout"),
        (ImportError("No module named x"), "fail", "env"),
        (OperationalError("db down"), "fail", "db"),
        (ConnectionError("refused"), "fail", "external"),
    ]
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        for exc, _, _ in cases:
            try:
                with span.span("transform.structure", doc_id="d"):
                    raise exc
            except type(exc):
                pass
            else:
                raise AssertionError("예외는 그대로 다시 던져져야 함")
        body = "x" * 40
        try:
            with span.span("extract.parse"):
                raise ValueError(f"bad '{body}'")
        except ValueError:
            pass
        with span.span("extract.parse") as sp:  # 안에서 정한 결과는 유지
            sp.result("skip", "env", "건너뜀")
        with span.span("extract.parse") as sp:
            sp.result("reused")
        try:
            span.Span("a.b", "a", {}, False).result("nope")
        except ValueError:
            pass
        else:
            raise AssertionError("알 수 없는 status는 거부")
    for row, (_, status, kind) in zip(rows, cases):
        assert (row["status"], row["err_kind"]) == (status, kind), row
        assert row["err"] and row["ts_end"] >= row["ts_start"]
    assert rows[6]["err"] == "ValueError"  # 예외 메시지 원문(문서 본문 조각)은 저장하지 않음 — 타입 이름만
    assert (rows[7]["status"], rows[7]["err_kind"]) == ("skip", "env") and rows[8]["status"] == "reused"


def test_observe_rows_and_carry():
    rows, patched = _capture()
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        with span.span("embed.bundle", "embed", model="api") as sp:
            for ms in (10, 20, 30, 40, 100):
                sp.observe("embed_call_ms", ms)
            sp.rows(50)
            sp.set(cpu_ms=5).set(cpu_ms=7, rss_peak_mb=3).set(rss_peak_mb=2)
            sp.ext_call(12)
        with span.span("transform.figures") as parent:

            def work(i):
                with span.span("transform.structure", doc_id=str(i)):
                    pass
                return span.current() is parent

            with ThreadPoolExecutor(2) as pool:
                assert all(pool.map(span.carry(work), range(3)))
                assert list(pool.map(span.carry(lambda i: span.current() is parent), range(2))) == [True, True]
            with ThreadPoolExecutor(1) as pool:  # carry를 안 하면 풀 스레드에는 컨텍스트가 없음
                assert pool.submit(lambda: span.current()).result() is None
    first = rows[0]
    m = first["metrics"]
    assert (m["embed_call_ms_n"], m["embed_call_ms_sum"], m["embed_call_ms_max"], m["embed_call_ms_p50"]) == (5, 200.0, 100.0, 30.0)
    assert m["rows"] == 50 and m["rows_per_sec"] > 0
    assert first["cpu_ms"] == 12 and first["rss_peak_mb"] == 3 and first["ext_call_ms"] == 12 and first["model"] == "api"
    children = [r for r in rows if r["stage"] == "transform.structure"]
    assert len(children) == 3 and {c["parent_id"] for c in children} == {rows[-1]["span_id"]}


def test_gated_popen_wait_split_and_child_context():
    rows, patched = _capture()
    clock = mock.Mock(return_value=0.0)

    def slow_mem(**kw):
        clock.return_value += 0.125
        return 10.0

    def slow_cpu(**kw):
        clock.return_value += 0.25
        return 0.1

    run_id = str(uuid.uuid4())
    with patched, jsonlog.context(run_id=run_id):
        with span.span("extract.parse", doc_id="a.pdf") as sp:
            code = "import json; from common.core import jsonlog; print(json.dumps(jsonlog.get_context()))"
            # launcher 안의 두 문만 가상 시각으로 측정한다. span·자식 대기 제한은 실제 시각을 쓴다.
            with (
                mock.patch.object(time, "monotonic", clock),
                mock.patch.object(RS, "wait_mem", slow_mem),
                mock.patch.object(RS, "wait_cpu", slow_cpu),
            ):
                proc = RS.gated_popen([sys.executable, "-c", code], cwd=paths.PROJ_ROOT, stdout=subprocess.PIPE, text=True)
            try:
                out, _ = proc.communicate(timeout=60)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=10)
            assert proc.returncode == 0
            outer_id = sp.span_id
    row = rows[0]
    # 합계가 아니라 두 문의 대기가 따로 쌓임 · 메모리 문은 잠금 밖 + 잠금 안 재확인 두 번, CPU 문은 잠금 밖 한 번
    assert (row["wait_mem_ms"], row["wait_cpu_ms"]) == (250, 250), row
    assert row["metrics"]["launches"] == 1 and "wait_launch_ms" in row["metrics"] and "settle_ms" in row["metrics"]
    child = json.loads(out.strip().splitlines()[-1])
    assert child["run_id"] == run_id and child["span_id"] == outer_id  # 자식이 run_id와 부모 span을 이어받음


def test_usage_line_roundtrip():
    usage = span.read_usage("engine noise\n" + span.usage_line() + "\n")
    if span.resource is None:  # Windows — resource 모듈이 없어 측정값 없음(NULL, span.py 머리말)
        assert usage == {}
    else:
        assert usage["cpu_ms"] >= 0 and usage["rss_peak_mb"] > 0
    assert span.read_usage("no usage here") == {} and span.read_usage(span.USAGE_PREFIX + "{broken") == {}


def test_model_call_hook():
    from common.ai import llm

    def fake(role, messages, **kw):
        if kw.get("boom"):
            raise RuntimeError("down")
        time.sleep(0.02)  # 성공 2번 ≥ 40ms — Windows 타이머 해상도(~15ms)에서도 아래 ≥ 20 판정이 흔들리지 않게
        return "ok", {"prompt_tokens": 7, "completion_tokens": 3}

    wrapped = llm._traced(fake)
    assert wrapped("vlm", []) == ("ok", {"prompt_tokens": 7, "completion_tokens": 3})  # span 없으면 그대로
    rows, patched = _capture()
    with patched, jsonlog.context(run_id=str(uuid.uuid4())):
        with span.span("transform.figures", doc_id="a.pdf"):
            wrapped("vlm", [])
            wrapped("vlm", [])
            try:
                wrapped("vlm", [], boom=True)
            except RuntimeError:
                pass
    parent = next(r for r in rows if r["stage"] == "transform.figures")  # 호출마다 model.vlm 행이 따로 생김
    assert [r["status"] for r in rows if r["stage"] == "model.vlm"] == ["ok", "ok", "fail"]  # 호출마다 한 행
    m = parent["metrics"]
    assert m["vlm_calls"] == 3 and m["vlm_fail"] == 1 and m["vlm_tok_in"] == 14 and m["vlm_tok_out"] == 6 and m["vlm_ms_n"] == 3
    assert parent["ext_call_ms"] >= 20
