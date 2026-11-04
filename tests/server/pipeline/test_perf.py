"""op-01: pipeline.tools.perf_report — 임시 행으로 p50/p95·wait 비율·느린 문서·쪽당·캐시/재시도/실패율·run 비교(DB 없이)."""

import contextlib
import io
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.tools import perf_report as perf


def _ev(stage, ms, engine=None, doc="a.pdf", status="ok", **kw):
    layer = kw.pop("layer", stage.split(".")[0])
    return {
        "stage": stage,
        "layer": layer,
        "engine": engine,
        "doc_id": doc,
        "duration_ms": ms,
        "status": status,
        "err_kind": kw.pop("err_kind", None),
        "metrics": kw.pop("metrics", None),
        "ts_start": "2026-10-30T10:00:00+00:00",
        "ts_end": "2026-10-30T10:00:10+00:00",
        **kw,
    }


def _events():
    parse = [
        _ev(
            "extract.parse",
            ms,
            "pdfplumber",
            doc=f"d{i}.pdf",
            metrics={"pages": 10, "proc_retries": 1 if i == 0 else 0},
            wait_mem_ms=ms // 4,
            wait_cpu_ms=ms // 4,
        )
        for i, ms in enumerate((1000, 2000, 3000, 4000, 10000))
    ]
    parse.append(
        _ev("extract.parse", 500, "docling", doc="d9.pdf", status="timeout", err_kind="timeout", metrics={"pages": 5, "timeout_retries": 1})
    )
    other = [
        _ev("transform.represent", 800, doc="d0.pdf", metrics={"vlm_calls": 4, "vlm_retries": 1, "vlm_fail": 1}),
        _ev("embed.bundle", 3000, doc=None, metrics={"cache_hit": 90, "cache_miss": 10, "batches": 4, "embed_retries": 1}),
        _ev("load.chunk", 200, doc=None, metrics={"rows": 100, "rows_per_sec": 500.0}),
        _ev("run.progress", 0, doc=None, layer="run", seq=3, total=6, metrics={"per_min": 12.0, "eta_sec": 90}),
        _ev("run.progress", 0, doc=None, layer="run", seq=5, total=6, metrics={"per_min": 15.0, "eta_sec": 20}),
    ]
    return parse + other


RUN = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "command": "parse",
    "status": "ok",
    "duration_ms": 20000,
    "docs_total": 6,
    "stack": "s1",
    "settings_hash": "abc",
}


def test_summarize_stage_table():
    summary = perf.summarize(RUN, _events(), top=3)
    stages = {(s["stage"], s["engine"]): s for s in summary["stages"]}
    plumber = stages[("extract.parse", "pdfplumber")]
    assert plumber["n"] == 5 and plumber["p50_ms"] == 3000 and plumber["max_ms"] == 10000 and plumber["total_ms"] == 20000
    assert abs(plumber["p95_ms"] - 8800) < 1e-6  # 선형 보간: 4000 + 6000 * 0.8
    assert plumber["of_wall"] == 1.0 and plumber["wait_ms"] == 10000 and plumber["wait_ratio"] == 0.5 and plumber["work_ms"] == 10000
    docling = stages[("extract.parse", "docling")]
    assert docling["fail_rate"] == 1.0 and docling["err_kind"] == {"timeout": 1} and docling["status"] == {"timeout": 1}
    assert ("run.progress", "") not in stages  # 진행 기록은 단계 표에서 제외
    assert 0 < stages[("extract.parse", "pdfplumber")]["of_layer"] < 1  # 같은 층(extract) 안 비율
    assert summary["last_progress"]["seq"] == 5 and summary["last_progress"]["metrics"]["eta_sec"] == 20


def test_slow_docs_per_page_and_ratios():
    summary = perf.summarize(RUN, _events(), top=3)
    assert [d["doc_id"] for d in summary["slow_docs"]] == ["d4.pdf", "d3.pdf", "d2.pdf"]  # 시간순, 상위 N
    assert summary["slow_docs"][0]["pages"] == 10 and summary["slow_docs"][0]["wait_ms"] == 5000
    per_page = {(p["stage"], p["engine"]): p for p in summary["per_page"]}
    assert per_page[("extract.parse", "pdfplumber")]["p50_ms_per_page"] == 300.0
    ratios = summary["ratios"]
    assert ratios["embed_cache_hit_rate"] == 0.9 and ratios["embed_retry_rate"] == 0.25
    assert ratios["vlm_retry_rate"] == 0.25 and ratios["vlm_fail_rate"] == 0.25
    assert ratios["extract_proc_retry_rate"] == round(1 / 6, 4) and ratios["extract_timeout_retry_rate"] == round(1 / 6, 4)
    assert summary["model_calls"] == {"vlm": 4}


def test_compare_runs_and_file_loader():
    run_b = {**RUN, "run_id": "22222222-2222-2222-2222-222222222222", "settings_hash": "xyz", "code_fp": {"p0": "new", "s": "same"}}
    run_a = {**RUN, "code_fp": {"p0": "old", "s": "same"}}
    fast = [{**e, "duration_ms": e["duration_ms"] // 2} for e in _events()]
    result = perf.compare([(run_a, perf.summarize(run_a, _events())), (run_b, perf.summarize(run_b, fast))])
    assert result["code_fp"]["p0"]["differs"] and not result["code_fp"]["s"]["differs"]
    assert result["meta"]["settings_hash"]["differs"] and not result["meta"]["stack"]["differs"]
    row = next(r for r in result["stages"] if r["stage"] == "extract.parse" and r["engine"] == "pdfplumber")
    assert [row["by_run"][i]["p50_ms"] for i in result["run_ids"]] == [3000, 1500]
    assert "다름" in perf.render_compare(result)

    with tempfile.TemporaryDirectory() as directory:  # logsink 대체 기록 파일(DB가 안 켜진 PC)
        path = Path(directory) / "applog.jsonl"
        lines = [
            {"table": "pipe_run", "row": {"run_id": RUN["run_id"], "status": "running", "command": "parse"}},
            {"table": "pipe_run", "row": {"run_id": RUN["run_id"], "status": "ok", "duration_ms": 20000}},
            {"table": "pipe_run", "row": {"run_id": "other", "status": "fail"}},
        ]
        lines += [{"table": "pipe_event", "row": {**e, "run_id": RUN["run_id"]}} for e in _events()]
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
        run, events = perf.load_file(RUN["run_id"], [path])
        assert run["status"] == "ok" and run["command"] == "parse" and len(events) == len(_events())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert perf.main([RUN["run_id"], "--file", str(path), "--top", "2"]) == 0
        text = out.getvalue()
        assert "extract.parse" in text and "느린 문서" in text and "캐시" in text and "d4.pdf" in text
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            perf.main([RUN["run_id"], "--file", str(path), "--json"])
        assert json.loads(out.getvalue())["wall_ms"] == 20000


def test_since_merges_runs():
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    rows = [
        {"run_id": "a", "stage": "extract.parse", "duration_ms": 10, "ts_start": (now - timedelta(hours=1)).isoformat()},
        {"run_id": "b", "stage": "load.pgvector", "duration_ms": 20, "ts_start": (now - timedelta(hours=2)).isoformat()},
        {"run_id": "c", "stage": "extract.parse", "duration_ms": 30, "ts_start": (now - timedelta(hours=9)).isoformat()},
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "applog.jsonl"
        lines = [{"table": "pipe_event", "row": r} for r in rows] + [{"table": "pipe_run", "row": {"run_id": "a"}}]
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
        assert [r["run_id"] for r in perf.load_since_file(3, [path], now=now)] == ["a", "b"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert perf.main(["--since", "100000", "--file", str(path)]) == 0
        assert "전체 실행" in out.getvalue() and "load.pgvector" in out.getvalue()


def test_render_null_counts():
    """DB 행은 문서 수 키가 있고 값이 None일 수 있다 — None은 -, 0은 그대로."""
    db_run = {**RUN, "docs_total": None, "docs_ok": None, "docs_fail": None, "docs_reused": None}
    head = perf.render(perf.summarize(db_run, _events())).splitlines()[0]
    assert "None" not in head and "문서 -(성공 - 실패 - 재사용 -)" in head
    zero_run = {**RUN, "docs_total": 3, "docs_ok": 3, "docs_fail": 0, "docs_reused": 0}
    assert "문서 3(성공 3 실패 0 재사용 0)" in perf.render(perf.summarize(zero_run, _events())).splitlines()[0]
