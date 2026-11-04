#!/usr/bin/env python3
"""파이프라인 실행 1건의 성능·추적 분석(op-01) — applog.pipe_run/pipe_event를 읽어 사람이 보는 표로.

    python -m pipeline.tools.perf_report <run_id>                 # 단계·엔진별 p50/p95/최대·비율, wait/작업, 느린 문서, 쪽당 시간, 캐시·재시도·실패
    python -m pipeline.tools.perf_report                           # run_id를 빼면 가장 최근 실행
    python -m pipeline.tools.perf_report --runs [N]                # 최근 실행 N개(기본 10) 목록
    python -m pipeline.tools.perf_report <run_id> --compare <run_id> ...   # 실행 간 비교(code_fp·stack·settings_hash 차이 + 단계별 p50)
    python -m pipeline.tools.perf_report <run_id> --file output/logs/2026-10-30_123.jsonl   # DB가 안 켜진 PC — logsink 대체 기록 파일에서
    python -m pipeline.tools.perf_report <run_id> --top 20 --json  # 느린 문서 N개 · 표 대신 JSON

읽기 전용 — DB에 쓰거나 DDL을 하지 않는다. 문서 본문은 기록에 없고 이 도구도 모른다(doc_id는 파일 이름).
집계 함수(summarize·compare)는 행 사전 목록만 받으므로 DB 없이 시험할 수 있다.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from common.core.console import utf8_stdout

DOC_STAGES_PREFIX = ("extract.parse", "transform.", "embed.", "load.")  # 느린 문서·쪽당 시간 대상(proc/run 래퍼는 뺌)
FAIL_STATUSES = ("fail", "timeout")
WAIT_METRICS = ("wait_launch_ms", "wait_slot_ms", "settle_ms", "llm_rpm_wait_ms")  # metrics 쪽 대기(열의 wait_mem/cpu와 합산)


def percentile(values, q):
    """선형 보간 백분위(0~100). 빈 목록은 None."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _metrics(row):
    metrics = row.get("metrics")
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except ValueError:
            metrics = {}
    return metrics if isinstance(metrics, dict) else {}


def _wait_ms(row):
    metrics = _metrics(row)
    return _num(row.get("wait_mem_ms")) + _num(row.get("wait_cpu_ms")) + sum(_num(metrics.get(k)) for k in WAIT_METRICS)


def _ts(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def summarize(run, events, top=10):
    """run: pipe_run 행(없으면 {}), events: pipe_event 행 목록 → 분석 사전(표 만들기 전 값)."""
    groups = defaultdict(list)
    for row in events:
        groups[(row.get("stage") or "?", row.get("engine") or "")].append(row)
    spans = [r for r in events if r.get("stage") != "run.progress"]
    starts = [t for t in (_ts(r.get("ts_start")) for r in spans) if t]
    ends = [t for t in (_ts(r.get("ts_end")) for r in spans) if t]
    wall_ms = _num(run.get("duration_ms")) or (int((max(ends) - min(starts)).total_seconds() * 1000) if starts and ends else 0)
    layer_total = defaultdict(float)
    for row in spans:
        if row.get("layer") not in ("run", "model"):  # model = 부모 span 안의 호출 행 — 층 합계에 이중 집계하지 않음
            layer_total[row.get("layer")] += _num(row.get("duration_ms"))

    stages = []
    for (stage, engine), rows in sorted(groups.items()):
        if stage == "run.progress":
            continue
        durations = [_num(r.get("duration_ms")) for r in rows]
        total = sum(durations)
        wait = sum(_wait_ms(r) for r in rows)
        status = defaultdict(int)
        kinds = defaultdict(int)
        for r in rows:
            status[r.get("status") or "?"] += 1
            if r.get("err_kind"):
                kinds[r["err_kind"]] += 1
        layer = rows[0].get("layer")
        stages.append(
            {
                "stage": stage,
                "engine": engine,
                "layer": layer,
                "n": len(rows),
                "status": dict(status),
                "err_kind": dict(kinds),
                "fail_rate": round(sum(status[s] for s in FAIL_STATUSES) / len(rows), 4),
                "p50_ms": percentile(durations, 50),
                "p95_ms": percentile(durations, 95),
                "max_ms": max(durations),
                "total_ms": total,
                "of_wall": round(total / wall_ms, 3) if wall_ms else None,  # 병렬이면 1을 넘을 수 있음
                "of_layer": round(total / layer_total[layer], 3) if layer_total.get(layer) else None,
                "wait_ms": wait,
                "work_ms": max(0, total - wait),
                "wait_ratio": round(wait / total, 3) if total else None,
                "cpu_ms": sum(_num(r.get("cpu_ms")) for r in rows),
                "rss_peak_mb": max((_num(r.get("rss_peak_mb")) for r in rows), default=0),
            }
        )

    per_page = []
    for (stage, engine), rows in sorted(groups.items()):
        rates = [_num(r.get("duration_ms")) / _metrics(r)["pages"] for r in rows if _num(_metrics(r).get("pages")) > 0]
        if rates:
            per_page.append(
                {"stage": stage, "engine": engine, "n": len(rates), "p50_ms_per_page": percentile(rates, 50), "max_ms_per_page": max(rates)}
            )

    slow = sorted(
        (r for r in spans if r.get("doc_id") and str(r.get("stage")).startswith(DOC_STAGES_PREFIX)),
        key=lambda r: -_num(r.get("duration_ms")),
    )[:top]
    slow_docs = [
        {
            "doc_id": r.get("doc_id"),
            "stage": r.get("stage"),
            "engine": r.get("engine") or "",
            "duration_ms": _num(r.get("duration_ms")),
            "wait_ms": _wait_ms(r),
            "pages": _metrics(r).get("pages"),
            "status": r.get("status"),
        }
        for r in slow
    ]

    sums = defaultdict(float)
    for r in spans:
        for key, value in _metrics(r).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sums[key] += value
    calls = {name[:-6]: sums[name] for name in sums if name.endswith("_calls")}
    ratios = {
        "embed_cache_hit_rate": _ratio(sums["cache_hit"], sums["cache_hit"] + sums["cache_miss"]),
        "llm_cache_hit_rate": _ratio(sums["llm_cache_hit"], sums["llm_cache_hit"] + sums["llm_calls"]),
        "embed_retry_rate": _ratio(sums["embed_retries"], sums["batches"]),
        "extract_proc_retry_rate": _ratio(sums["proc_retries"], sum(r["n"] for r in stages if r["stage"] == "extract.parse")),
        "extract_timeout_retry_rate": _ratio(sums["timeout_retries"], sum(r["n"] for r in stages if r["stage"] == "extract.parse")),
        **{f"{role}_retry_rate": _ratio(sums[f"{role}_retries"], count) for role, count in calls.items() if f"{role}_retries" in sums},
        **{f"{role}_fail_rate": _ratio(sums[f"{role}_fail"], count) for role, count in calls.items() if f"{role}_fail" in sums},
    }
    progress = [r for r in events if r.get("stage") == "run.progress"]
    last = max(progress, key=lambda r: _num(r.get("seq")), default=None)
    return {
        "run": run,
        "wall_ms": wall_ms,
        "n_events": len(events),
        "stages": stages,
        "per_page": per_page,
        "slow_docs": slow_docs,
        "ratios": {k: v for k, v in ratios.items() if v is not None},
        "model_calls": {role: int(count) for role, count in calls.items()},
        "download": download_summary(events),
        "last_progress": None if last is None else {"seq": last.get("seq"), "total": last.get("total"), "metrics": _metrics(last)},
    }


SIZE_BUCKETS = ((1e6, "<1MB"), (1e7, "1~10MB"), (1e8, "10~100MB"), (float("inf"), ">=100MB"))


def _bucket(size):
    return next(label for limit, label in SIZE_BUCKETS if size < limit)


def download_summary(events):
    """extract.download 행 → 파일 크기 구간별 순수 전송 속도(mbps)·head 지연·잠금 대기. 이슈 #117 — 느림이 네트워크 쪽인지 코드 쪽인지 가르는 표.
    크기와 관계없이 mbps가 낮으면 네트워크·스토리지, mbps는 정상인데 전체 시간(duration)이 길면 head·잠금 같은 코드 쪽을 의심한다."""
    rows = [r for r in events if r.get("stage") == "extract.download"]
    if not rows:
        return None
    by_bucket = defaultdict(list)
    for r in rows:
        by_bucket[_bucket(_num(r.get("file_bytes")))].append(r)
    buckets = []
    for _, label in SIZE_BUCKETS:
        group = by_bucket.get(label)
        if not group:
            continue
        ok = [r for r in group if r.get("status") == "ok"]
        mbps = [_metrics(r)["mbps"] for r in ok if _num(_metrics(r).get("mbps")) > 0]
        buckets.append(
            {
                "size": label,
                "n": len(group),
                "fail": len(group) - len(ok),
                "mbps_p50": percentile(mbps, 50),
                "mbps_min": min(mbps, default=None),
                "duration_p50_ms": percentile([_num(r.get("duration_ms")) for r in ok], 50),
                "head_p50_ms": percentile([_num(_metrics(r).get("head_ms")) for r in ok], 50),
                "lock_wait_p95_ms": percentile([_num(_metrics(r).get("lock_wait_ms")) for r in ok], 95),
            }
        )
    return {"n": len(rows), "buckets": buckets}


def _ratio(num, den):
    return round(num / den, 4) if den else None


def compare(runs):
    """runs: [(pipe_run 행, 요약)] → code_fp·stack·settings_hash 차이와 (단계, 엔진)별 p50/p95 나란히."""
    keys = {}
    for run, summary in runs:
        for stage in summary["stages"]:
            keys.setdefault((stage["stage"], stage["engine"]), {})[str(run.get("run_id"))] = stage
    ids = [str(run.get("run_id")) for run, _ in runs]
    meta = {}
    for field in ("app_version", "stack", "settings_hash", "run_env", "workers", "cpu_max_load"):
        values = {rid: run.get(field) for rid, (run, _) in zip(ids, runs)}
        meta[field] = {"values": values, "differs": len({json.dumps(v, default=str) for v in values.values()}) > 1}
    fp = {}
    layers = sorted({layer for run, _ in runs for layer in (run.get("code_fp") or {})})
    for layer in layers:
        values = {rid: (run.get("code_fp") or {}).get(layer) for rid, (run, _) in zip(ids, runs)}
        fp[layer] = {"values": values, "differs": len(set(values.values())) > 1}
    rows = []
    for (stage, engine), by_run in sorted(keys.items()):
        rows.append(
            {
                "stage": stage,
                "engine": engine,
                "by_run": {
                    rid: {"n": s["n"], "p50_ms": s["p50_ms"], "p95_ms": s["p95_ms"], "fail_rate": s["fail_rate"]}
                    for rid, s in by_run.items()
                },
            }
        )
    return {
        "run_ids": ids,
        "meta": meta,
        "code_fp": fp,
        "stages": rows,
        "wall_ms": {rid: summary["wall_ms"] for rid, (_, summary) in zip(ids, runs)},
    }


# ── 읽기 ────────────────────────────────────────────────────────────────────
def _db_rows(sql, params, schema=None):
    from common.store.db import dbtool

    schema = dbtool.schema_of("applog", schema)
    engine = dbtool.engine()
    try:
        with engine.connect() as conn:
            result = conn.exec_driver_sql(sql.replace("{S}", schema), params)
            cols = list(result.keys())
            return [dict(zip(cols, row)) for row in result.fetchall()]
    finally:
        engine.dispose()


def load_db(run_id, schema=None):
    run_rows = _db_rows("SELECT * FROM {S}.pipe_run WHERE run_id = %(r)s::uuid", {"r": run_id}, schema)
    events = _db_rows("SELECT * FROM {S}.pipe_event WHERE run_id = %(r)s::uuid ORDER BY ts_start", {"r": run_id}, schema)
    return (run_rows[0] if run_rows else {}), events


def _file_items(paths):
    """logsink 대체 기록({"table","row"} JSON Lines) — 깨진 줄은 건너뜀."""
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                yield item.get("table"), item.get("row") or {}


def load_file(run_id, paths):
    """pipe_run은 같은 run_id 행들을 시간순으로 합친다(UPSERT와 같은 결과)."""
    run, events = {}, []
    for table, row in _file_items(paths):
        if str(row.get("run_id")) != str(run_id):
            continue
        if table == "pipe_run":
            run.update({k: v for k, v in row.items() if v is not None})
        elif table == "pipe_event":
            events.append(row)
    return run, events


def load_since_db(hours, schema=None):
    return _db_rows(
        "SELECT * FROM {S}.pipe_event WHERE ts_start >= now() - make_interval(secs => %(s)s) ORDER BY ts_start",
        {"s": float(hours) * 3600},
        schema,
    )


def load_since_file(hours, paths, now=None):
    """대체 기록에서 최근 hours시간의 pipe_event — 실행(run_id)을 가리지 않음."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=float(hours))
    return [
        row for table, row in _file_items(paths) if table == "pipe_event" and (ts := _ts(row.get("ts_start"))) is not None and ts >= cutoff
    ]


def latest_run_id():
    rows = _db_rows("SELECT run_id FROM {S}.pipe_run ORDER BY started_at DESC LIMIT 1", {})
    return str(rows[0]["run_id"]) if rows else None


def recent_runs(limit):
    return _db_rows(
        "SELECT run_id, command, status, started_at, duration_ms, docs_total, docs_ok, docs_fail, docs_reused, stack, app_version "
        "FROM {S}.pipe_run ORDER BY started_at DESC LIMIT %(n)s",
        {"n": limit},
    )


# ── 표 출력 ─────────────────────────────────────────────────────────────────
def _ms(value):
    if value is None:
        return "-"
    return f"{value / 1000:.1f}s" if value >= 1000 else f"{value:.0f}ms"


def _pct(value):
    return "-" if value is None else f"{value * 100:.0f}%"


def _table(headers, rows):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]
    lines = ["  ".join(str(h).ljust(w) for h, w in zip(headers, widths)), "  ".join("-" * w for w in widths)]
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)) for r in rows]
    return "\n".join(lines)


def render(summary):
    run = summary["run"]

    def count(name):  # DB 행은 키가 있고 값이 None일 수 있다 — None은 -, 0은 그대로
        return "-" if run.get(name) is None else run[name]

    out = [
        f"실행 {run.get('run_id', '?')} · {run.get('command', '?')} · {run.get('status', '?')} · {_ms(summary['wall_ms'])} · "
        f"문서 {count('docs_total')}(성공 {count('docs_ok')} 실패 {count('docs_fail')} 재사용 {count('docs_reused')}) · "
        f"스택 {run.get('stack') or '-'} · 설정 {run.get('settings_hash') or '-'} · 이벤트 {summary['n_events']}행",
        "",
        "■ 단계·엔진별 (wall 대비는 병렬이면 100%를 넘음 · wait = 메모리/CPU 문·슬롯 대기)",
    ]
    out.append(
        _table(
            ["단계", "엔진", "건", "실패율", "p50", "p95", "최대", "합계", "wall%", "층%", "wait%", "cpu"],
            [
                [
                    s["stage"],
                    s["engine"] or "-",
                    s["n"],
                    _pct(s["fail_rate"]),
                    _ms(s["p50_ms"]),
                    _ms(s["p95_ms"]),
                    _ms(s["max_ms"]),
                    _ms(s["total_ms"]),
                    _pct(s["of_wall"]),
                    _pct(s["of_layer"]),
                    _pct(s["wait_ratio"]),
                    _ms(s["cpu_ms"]) if s["cpu_ms"] else "-",
                ]
                for s in summary["stages"]
            ],
        )
    )
    if summary["per_page"]:
        out += [
            "",
            "■ 쪽당 시간",
            _table(
                ["단계", "엔진", "건", "p50/쪽", "최대/쪽"],
                [
                    [p["stage"], p["engine"] or "-", p["n"], _ms(p["p50_ms_per_page"]), _ms(p["max_ms_per_page"])]
                    for p in summary["per_page"]
                ],
            ),
        ]
    if summary["slow_docs"]:
        out += [
            "",
            f"■ 느린 문서 상위 {len(summary['slow_docs'])}",
            _table(
                ["문서", "단계", "엔진", "시간", "wait", "쪽", "상태"],
                [
                    [
                        d["doc_id"],
                        d["stage"],
                        d["engine"] or "-",
                        _ms(d["duration_ms"]),
                        _ms(d["wait_ms"]),
                        d["pages"] if d["pages"] is not None else "-",
                        d["status"],
                    ]
                    for d in summary["slow_docs"]
                ],
            ),
        ]
    dl = summary.get("download")
    if dl:
        out += [
            "",
            f"■ 다운로드 {dl['n']}건 (mbps = 순수 전송 · 크기와 무관하게 낮으면 네트워크, 시간만 길면 head·잠금)",
            _table(
                ["크기", "건", "실패", "mbps p50", "mbps 최저", "전체 p50", "head p50", "잠금대기 p95"],
                [
                    [
                        b["size"],
                        b["n"],
                        b["fail"],
                        "-" if b["mbps_p50"] is None else f"{b['mbps_p50']:.1f}",
                        "-" if b["mbps_min"] is None else f"{b['mbps_min']:.1f}",
                        _ms(b["duration_p50_ms"]),
                        _ms(b["head_p50_ms"]),
                        _ms(b["lock_wait_p95_ms"]),
                    ]
                    for b in dl["buckets"]
                ],
            ),
        ]
    if summary["ratios"] or summary["model_calls"]:
        out += ["", "■ 캐시 적중·재시도·실패율"]
        out += [f"  {k}: {_pct(v)}" for k, v in summary["ratios"].items()]
        out += [f"  모델 호출 {role}: {count}회" for role, count in summary["model_calls"].items()]
    prog = summary["last_progress"]
    if prog:
        m = prog["metrics"]
        out += ["", f"■ 마지막 진행 기록: {prog['seq']}/{prog['total']} · {m.get('per_min')}건/분 · 남은 {m.get('eta_sec')}초 추정"]
    return "\n".join(out)


def render_compare(result):
    ids = result["run_ids"]
    short = [i[:8] for i in ids]
    out = ["■ 실행 비교 " + " vs ".join(short), ""]
    out.append(
        _table(
            ["항목", *short, "다름"],
            [
                [name, *[json.dumps(info["values"].get(i), default=str) for i in ids], "예" if info["differs"] else ""]
                for name, info in result["meta"].items()
            ],
        )
    )
    out += ["", "■ 코드 지문(code_fp)"]
    out.append(
        _table(
            ["층", *short, "다름"],
            [
                [layer, *[info["values"].get(i) or "-" for i in ids], "예" if info["differs"] else ""]
                for layer, info in result["code_fp"].items()
            ],
        )
    )
    out += ["", "■ 단계·엔진별 p50 (건/실패율)"]
    rows = []
    for item in result["stages"]:
        cells = []
        for rid in ids:
            s = item["by_run"].get(rid)
            cells.append("-" if s is None else f"{_ms(s['p50_ms'])} ({s['n']}/{_pct(s['fail_rate'])})")
        rows.append([item["stage"], item["engine"] or "-", *cells])
    out.append(_table(["단계", "엔진", *short], rows))
    out.append("")
    out.append("wall: " + " · ".join(f"{i[:8]} {_ms(result['wall_ms'][i])}" for i in ids))
    return "\n".join(out)


def _load(run_id, files):
    return load_file(run_id, files) if files else load_db(run_id)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id", nargs="?", help="비우면 가장 최근 실행")
    ap.add_argument("--runs", nargs="?", const=10, type=int, metavar="N", help="최근 실행 N개 목록")
    ap.add_argument("--compare", nargs="+", metavar="RUN_ID", help="이 실행과 비교할 다른 run_id들")
    ap.add_argument("--file", nargs="+", help="DB 대신 logsink 대체 기록 JSON Lines 파일")
    ap.add_argument(
        "--since", type=float, metavar="HOURS", help="최근 N시간의 모든 실행을 합쳐 분석(run_docs는 문서·단계마다 실행이 따로 생김)"
    )
    ap.add_argument("--top", type=int, default=10, help="느린 문서 개수")
    ap.add_argument("--json", action="store_true", help="표 대신 JSON")
    a = ap.parse_args(argv)
    if a.runs is not None:
        rows = recent_runs(a.runs)
        print(
            json.dumps(rows, ensure_ascii=False, default=str, indent=1)
            if a.json
            else _table(
                ["run_id", "명령", "상태", "시작", "시간", "문서", "스택"],
                [
                    [
                        str(r["run_id"]),
                        r["command"],
                        r["status"],
                        str(r["started_at"])[:19],
                        _ms(r["duration_ms"]),
                        r["docs_total"] if r["docs_total"] is not None else "-",
                        r["stack"] or "-",
                    ]
                    for r in rows
                ],
            )
        )
        return 0
    if a.since is not None:
        events = load_since_file(a.since, a.file) if a.file else load_since_db(a.since)
        if not events:
            print(f"최근 {a.since:g}시간의 기록이 없습니다", file=sys.stderr)
            return 1
        summary = summarize({"run_id": f"최근 {a.since:g}시간", "command": "전체 실행"}, events, a.top)
        print(json.dumps(summary, ensure_ascii=False, default=str, indent=1) if a.json else render(summary))
        return 0
    run_id = a.run_id or (None if a.file else latest_run_id())
    if not run_id:
        print("기록된 실행이 없습니다(applog.pipe_run 비어 있음 — common.log.db_enabled·dbtool up --target applog 확인)", file=sys.stderr)
        return 1
    run, events = _load(run_id, a.file)
    if not run and not events:
        print(f"run_id {run_id}의 기록이 없습니다", file=sys.stderr)
        return 1
    summary = summarize(run, events, a.top)
    if a.compare:
        pairs = [(run, summary)]
        for other in a.compare:
            other_run, other_events = _load(other, a.file)
            pairs.append((other_run or {"run_id": other}, summarize(other_run, other_events, a.top)))
        result = compare(pairs)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=1) if a.json else render_compare(result))
        return 0
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=1) if a.json else render(summary))
    return 0


if __name__ == "__main__":
    utf8_stdout()
    raise SystemExit(main())
