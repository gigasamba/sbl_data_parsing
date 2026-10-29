"""pipeline.eval.chart_values_score 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.chart_values_score --selftest`."""

import json
from pathlib import Path

from pipeline.eval.chart_values_score import run, summarize


def selftest():
    import tempfile

    import fitz

    def _bar_pdf(path):
        """선택기(axis·tick)를 한 drawing으로 묶어야(아래 shape) vector_regions()의 12pt 묶기 거리 안에서
        막대와 함께 그림으로 잡힌다 — 이 채점기는 extract_vector()를 지름길로 부르지 않고 실 파이프라인
        (build_records→vector_regions)을 거치므로, 이 selftest 픽스처도 그 문턱을 실제로 넘어야 한다."""
        doc = fitz.open()
        pg = doc.new_page(width=600, height=600)  # 그림이 쪽 면적의 60%를 넘으면 "쪽 전체"로 보고 제외(vector.py) — 여유 있게
        shape = pg.new_shape()
        shape.draw_line((20, 20), (20, 380))
        shape.draw_line((20, 380), (380, 380))
        for y in (20, 145, 270, 380):  # 눈금 표시(min_items=5 문턱을 넘기려고 — 축 2줄만으론 항목 수가 모자람)
            shape.draw_line((16, y), (20, y))
        shape.finish(color=(0, 0, 0), width=1)
        shape.commit()
        dy = 4.27
        pg.insert_text((2, 20 + dy), "100")
        pg.insert_text((10, 380 + dy), "0")
        pg.draw_rect(fitz.Rect(50, 128, 100, 380), fill=(0.2, 0.4, 0.6))  # value(128) = 70
        pg.draw_rect(fitz.Rect(150, 200, 200, 380), fill=(0.2, 0.4, 0.6))  # 장식용(최소 막대 신호 bars>=3를 넘기려고)
        pg.draw_rect(fitz.Rect(250, 236, 300, 380), fill=(0.2, 0.4, 0.6))
        pg.insert_text((60, 392), "bar_x1")
        pg.insert_text((160, 392), "bar_x2")
        pg.insert_text((260, 392), "bar_x3")
        doc.save(path)

    d = Path(tempfile.mkdtemp())
    ds = d / "ds"
    (ds / "gold").mkdir(parents=True)
    _bar_pdf(ds / "bar_selftest.pdf")

    gold_exact = {"values": [{"series": None, "x": "bar_x1", "value": 70.0}], "trend": None}
    (ds / "gold" / "bar_selftest.pdf.json").write_text(json.dumps(gold_exact), encoding="utf-8")
    gold_off = {"values": [{"series": None, "x": "bar_x1", "value": 77.0}], "trend": None}
    (ds / "gold" / "bar_off.pdf.json").write_text(json.dumps(gold_off), encoding="utf-8")
    _bar_pdf(ds / "bar_off.pdf")  # 같은 그림(값 70) — gold를 77로 둬서 상대오차 계산을 검증

    gold_neg = {"values": [], "trend": None}
    doc2 = fitz.open()
    pg2 = doc2.new_page(width=200, height=200)
    pg2.insert_text((20, 20), "no chart here")
    doc2.save(ds / "bar_table.pdf")
    (ds / "gold" / "bar_table.pdf.json").write_text(json.dumps(gold_neg), encoding="utf-8")

    rows = run(ds)
    by_file = {r["file"]: r for r in rows}
    assert by_file["bar_selftest.pdf"]["coverage"] == 1.0 and by_file["bar_selftest.pdf"]["rel_errs"][0] < 1e-3
    exp_rel = abs(70.0 - 77.0) / 77.0
    assert abs(by_file["bar_off.pdf"]["rel_errs"][0] - exp_rel) < 1e-3
    assert by_file["bar_table.pdf"]["n_gold"] == 0 and not by_file["bar_table.pdf"]["false_positive"]
    table, negative = summarize(rows)
    assert negative == {"n": 1, "ok": 1}
    row_bar = next(t for t in table if t["kind"] == "bar")
    assert row_bar["coverage_mean"] == 1.0 and row_bar["rel_err_median"] is not None
    print("[selftest] F14(d) — chart_values_score(실 build_records 경유): 상대오차·coverage·부정 샘플(값 0건) 집계 통과")


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
