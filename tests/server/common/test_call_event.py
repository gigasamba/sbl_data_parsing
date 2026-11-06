"""op-01: 모델 호출별 pipe_event — 성공·실패 모든 호출이 한 행."""

import uuid
from unittest import mock

from common.ai import llm
from common.core import jsonlog, span


def _rows(fn):
    rows = []
    with mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)), jsonlog.context(run_id=str(uuid.uuid4())):
        fn()
    return rows


def test_every_call_gets_a_row():
    def run():
        with span.span("transform.figures", doc_id="a.pdf", ext=".pdf"):
            span.call_event("model.vlm", 100, None, tok_in=10)
            span.call_event("model.vlm", 200, ConnectionError("x"))

    rows = _rows(run)
    calls = [r for r in rows if r["stage"] == "model.vlm"]
    parent = next(r for r in rows if r["stage"] == "transform.figures")
    assert len(calls) == 2 and all(r["layer"] == "model" and r["doc_id"] == "a.pdf" for r in calls)
    assert all(r["parent_id"] == parent["span_id"] for r in calls)
    fast, failed = calls
    assert fast["status"] == "ok" and fast["duration_ms"] == 100 and fast["metrics"] == {"tok_in": 10}
    assert failed["status"] == "fail" and failed["err_kind"] == "external" and failed["err"] == "ConnectionError"


def test_traced_failure_row_and_no_run_id():
    def boom(role, messages, **kw):
        raise ConnectionError("down")

    def run():
        with span.span("transform.figures", doc_id="b.pdf"):
            try:
                llm._traced(boom)("vlm", [])
            except ConnectionError:
                pass

    assert [r["status"] for r in _rows(run) if r["stage"] == "model.vlm"] == ["fail"]
    span.call_event("model.vlm", 99999)  # run_id 없으면 아무 일도 안 함(예외 없음)
