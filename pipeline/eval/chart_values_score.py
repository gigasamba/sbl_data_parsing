#!/usr/bin/env python3
"""F14(d) — valid_env/unstructured/synth-charts-hard/(dev_tools/synthetic_data_gen/gen_hard_charts.py) 값 채점.
gold/<파일>.json = {"values": [{"series","x","value"}], "trend": {"direction"}}과 실 파이프라인
(pipeline.transform.figures.figures.build_records — vector_regions()로 그림 영역을 먼저 찾는 단계까지
그대로 거침, chart_values.extract_vector()를 직접 부르는 지름길이 아님: 독립 검토 10-14 — 지름길로는 못
잡는 '그림으로 아예 안 잡히는' 회귀를 이 채점기가 숨길 수 있었음)의 예측을 (series,x)로 맞춰 상대·절대 오차,
coverage(= 맞춘 gold 값 수 / gold 값 수 — 부정 샘플은 예측이 비었는지), 추세 일치를 종류(bar·stacked_bar·
line)×표현(vector·raster, raster는 아직 결정적 경로가 없어 skip)별로 묶는다. 한 PDF가 vector_regions()에서
여러 그림 영역으로 나뉘면(예: 열마다 따로 묶이는 누적 막대) 모든 벡터 그림의 값을 합쳐 한 파일로 채점한다.
raster(.jpg·.png)는 F14(b) 배선 전까지 집계에서 빠지고 "stub" 행만 남는다(실 VLM 승인 전).

사용: PYTHONPATH=deploy python -m pipeline.eval.chart_values_score [--dir valid_env/unstructured/synth-charts-hard]
      PYTHONPATH=deploy python -m pipeline.eval.chart_values_score --selftest
"""

import argparse
import json
import statistics
from pathlib import Path

from common.core.paths import EVAL_SETS_DIR
from pipeline.transform.figures import chart_values as CV
from pipeline.transform.figures.figures import build_records

_KIND_SUBSTR = [("stacked_bar", "stacked_bar"), ("log_axis", "line"), ("line", "line"), ("bar", "bar"), ("negative", "negative")]


def _kind_of(name):
    for sub, kind in _KIND_SUBSTR:
        if sub in name:
            return kind
    return "other"


def score_file(fpath, gold):
    """gold(dict) + 파일 경로 → 1건 채점 dict. .pdf만 결정적 채점(그 밖은 raster — skip="stub"). 실
    build_records()를 거쳐(vector_regions 포함) 그 문서의 모든 벡터 그림 values를 합쳐서 본다."""
    gold_values = gold.get("values") or []
    if fpath.suffix.lower() != ".pdf":
        return {
            "skip": "stub(raster)",
            "coverage": None,
            "rel_errs": [],
            "abs_errs": [],
            "trend_ok": None,
            "n_gold": len(gold_values),
            "n_pred": None,
            "false_positive": False,
        }
    recs, _plain, _enriched = build_records(fpath.name, fpath, "", "chart_values_score")
    pred_values = []
    for r in recs:
        if r["origin"] == "vector":
            pred_values += r["vlm"]["content"]["values"] or []
    by_key = {(v.get("series"), v.get("x")): v["value"] for v in pred_values}
    rel_errs, abs_errs, matched = [], [], 0
    for gv in gold_values:
        key = (gv.get("series"), gv.get("x"))
        if key not in by_key:
            continue
        matched += 1
        g, p = gv["value"], by_key[key]
        abs_errs.append(abs(p - g))
        rel_errs.append(abs(p - g) / abs(g) if g else (0.0 if p == g else abs(p - g)))
    coverage = (matched / len(gold_values)) if gold_values else None
    gold_trend = (gold.get("trend") or {}).get("direction")
    pred_trend = (CV.compute_trend(pred_values) or {}).get("direction") if pred_values else None
    trend_ok = (pred_trend == gold_trend) if gold_trend else None
    return {
        "skip": None,
        "coverage": coverage,
        "rel_errs": rel_errs,
        "abs_errs": abs_errs,
        "trend_ok": trend_ok,
        "n_gold": len(gold_values),
        "n_pred": len(pred_values),
        "false_positive": bool(pred_values) and not gold_values,
    }


def run(ds_dir):
    """gold/*.json을 전부 채점 → 행 목록(파일당 1행, kind·rep 포함)."""
    rows = []
    for gp in sorted((ds_dir / "gold").glob("*.json")):
        fname = gp.stem  # "<file>.json" → stem == "<file>"(예: bar_basic.pdf)
        fpath = ds_dir / fname
        if not fpath.exists():
            continue
        gold = json.loads(gp.read_text(encoding="utf-8"))
        r = score_file(fpath, gold)
        r.update(file=fname, kind=_kind_of(fname), rep=("raster" if fpath.suffix.lower() != ".pdf" else "vector"))
        rows.append(r)
    return rows


def summarize(rows):
    """(종류,표현)별 coverage 평균·상대오차 median/p90·추세 정확도 표 + 부정 샘플(값이 아예 없어야 함) 결과."""
    groups = {}
    for r in rows:
        groups.setdefault((r["kind"], r["rep"]), []).append(r)
    table = []
    for (kind, rep), rs in sorted(groups.items()):
        rel = sorted(e for r in rs for e in r["rel_errs"])
        cov = [r["coverage"] for r in rs if r["coverage"] is not None]
        trend = [r["trend_ok"] for r in rs if r["trend_ok"] is not None]
        table.append(
            {
                "kind": kind,
                "rep": rep,
                "n_files": len(rs),
                "coverage_mean": round(sum(cov) / len(cov), 4) if cov else None,
                "rel_err_median": round(statistics.median(rel), 4) if rel else None,
                "rel_err_p90": round(rel[max(0, int(len(rel) * 0.9) - 1)], 4) if rel else None,
                "trend_acc": round(sum(trend) / len(trend), 4) if trend else None,
                "n_stub": sum(1 for r in rs if r["skip"]),
            }
        )
    neg = [r for r in rows if r["n_gold"] == 0 and not r["skip"]]
    negative = {"n": len(neg), "ok": sum(1 for r in neg if not r["false_positive"])}
    return table, negative


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=None)
    a = ap.parse_args(argv)
    ds_dir = Path(a.dir) if a.dir else (EVAL_SETS_DIR / "synth-charts-hard")
    rows = run(ds_dir)
    table, negative = summarize(rows)
    for t in table:
        print(t)
    print("negatives(차트 값이 없어야 함):", negative)


if __name__ == "__main__":
    main()
