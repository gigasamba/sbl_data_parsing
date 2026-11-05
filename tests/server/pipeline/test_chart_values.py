"""pipeline.transform.figures.chart_values 시험."""

import math

from pipeline.transform.figures.chart_values import (
    _is_log_axis,
    _to_number,
    compute_trend,
    extract_vector,
    merge_values,
)


def selftest():
    import fitz

    # fitz insert_text의 y는 글자 기준선 — 글자 bbox 수직 중심은 기준선보다 TXT_DY만큼 위(실측, 기본 폰트 크기 고정값).
    # 눈금 글자를 실제 눈금 픽셀에 정확히 맞추려면 baseline = target_px + TXT_DY로 넣어야 한다(안 그러면 글자 중심이
    # 눈금과 몇 pt 어긋나 피팅 자체가 아니라 시험 데이터 생성 쪽 오차가 섞인다).
    TXT_DY = 4.27

    # 막대그래프 — 눈금 0·100, 막대 2개(60·30) + x 라벨
    doc = fitz.open()
    pg = doc.new_page(width=400, height=400)
    pg.draw_line((20, 20), (20, 380), color=(0, 0, 0), width=1)
    pg.draw_line((20, 380), (380, 380), color=(0, 0, 0), width=1)
    pg.insert_text((2, 20 + TXT_DY), "100")
    pg.insert_text((10, 380 + TXT_DY), "0")
    pg.draw_rect(fitz.Rect(50, 200, 100, 380), fill=(0.2, 0.4, 0.6))  # top=200 → (380-200)/(380-20)*100=50
    pg.draw_rect(fitz.Rect(150, 290, 200, 380), fill=(0.2, 0.4, 0.6))  # top=290 → 25
    pg.insert_text((60, 392), "Q1")
    pg.insert_text((160, 392), "Q2")
    vals, meta = extract_vector(pg, [0, 0, 400, 400])
    by_x = {v["x"]: v["value"] for v in vals}
    assert meta["axis"] == "linear" and meta["chart_type"] == "bar"
    assert abs(by_x["Q1"] - 50) < 1 and abs(by_x["Q2"] - 25) < 1, by_x
    print("[selftest] F14(a) — 선형 막대그래프 값 추출(Q1≈50·Q2≈25) 통과")

    # 누적 막대 — 한 열에 세그먼트 2개(위 40~60, 아래 60~100 → 각 20)
    doc2 = fitz.open()
    pg2 = doc2.new_page(width=400, height=400)
    pg2.draw_line((20, 20), (20, 380), color=(0, 0, 0), width=1)
    pg2.draw_line((20, 380), (380, 380), color=(0, 0, 0), width=1)
    pg2.insert_text((2, 20 + TXT_DY), "100")
    pg2.insert_text((10, 380 + TXT_DY), "0")
    pg2.draw_rect(fitz.Rect(50, 110, 100, 236), fill=(0.2, 0.4, 0.6))  # value(110)=75, value(236)=40 → 세그먼트 35
    pg2.draw_rect(fitz.Rect(50, 236, 100, 380), fill=(0.8, 0.3, 0.1))  # value(236)=40, value(380)=0 → 세그먼트 40
    pg2.insert_text((60, 392), "2025")
    vals2, meta2 = extract_vector(pg2, [0, 0, 400, 400])
    assert meta2["chart_type"] == "stacked_bar" and len(vals2) == 2
    mags = sorted(round(v["value"]) for v in vals2)
    assert mags == [35, 40], mags
    print("[selftest] F14(a) — 누적 막대 세그먼트 2개(35·40) 통과")

    # 로그축 — 10^6·10^4·10^2 눈금(90px/decade로 일정), 중간(10^6·10^4 사이, px110=10^5) 점 1개
    doc3 = fitz.open()
    pg3 = doc3.new_page(width=400, height=400)
    pg3.draw_line((20, 20), (20, 380), color=(0, 0, 0), width=1)
    pg3.draw_line((20, 380), (380, 380), color=(0, 0, 0), width=1)
    pg3.insert_text((2, 20 + TXT_DY), "10^6")
    pg3.insert_text((2, 200 + TXT_DY), "10^4")
    pg3.insert_text((2, 380 + TXT_DY), "10^2")
    pg3.draw_line((100, 110), (200, 110), color=(0.5, 0, 0.5), width=2)  # 10^6(px20)·10^4(px200) 중간 → 10^5
    pg3.insert_text((90, 392), "D1")
    pg3.insert_text((190, 392), "D2")
    vals3, meta3 = extract_vector(pg3, [0, 0, 400, 400])
    assert meta3["axis"] == "log", meta3
    assert vals3 and abs(math.log10(vals3[0]["value"]) - 5) < 0.1, vals3
    print("[selftest] F14(a) — 로그축(10^n 눈금) 판정·보간 통과")

    # 표·흐름도(숫자 눈금 없음) — 값 0건, 지어내지 않음
    doc4 = fitz.open()
    pg4 = doc4.new_page(width=300, height=300)
    pg4.draw_rect(fitz.Rect(20, 20, 280, 280), color=(0, 0, 0))
    pg4.insert_text((30, 40), "항목")
    vals4, meta4 = extract_vector(pg4, [0, 0, 300, 300])
    assert vals4 == [] and meta4["axis"] is None
    print("[selftest] F14(a) — 숫자 눈금 없는 표·흐름도는 값 0건(지어내지 않음) 통과")

    # 추세
    assert compute_trend([]) is None
    assert (
        compute_trend([{"x": "Q1", "value": 41}, {"x": "Q2", "value": 47}, {"x": "Q3", "value": 39}, {"x": "Q4", "value": 52}])["direction"]
        == "변동"
    )
    assert compute_trend([{"x": "Q1", "value": 10}, {"x": "Q2", "value": 20}, {"x": "Q3", "value": 30}])["direction"] == "증가"
    assert compute_trend([{"x": "Q1", "value": 30}, {"x": "Q2", "value": 20}, {"x": "Q3", "value": 10}])["direction"] == "감소"
    assert compute_trend([{"x": "Q1", "value": 10}, {"x": "Q2", "value": 10.1}, {"x": "Q3", "value": 9.9}])["direction"] == "유지"
    t = compute_trend([{"x": "Q1", "value": 10}, {"x": "Q2", "value": 50}, {"x": "Q3", "value": 30}, {"x": "Q4", "value": 20}])
    assert t["direction"] == "정점 후 감소", t
    t2 = compute_trend([{"x": "Q1", "value": 41}, {"x": "Q4", "value": 52}])
    assert t2["basis"] == "Q1 41 → Q4 52" and t2["period"] == "Q1–Q4"
    print("[selftest] F14(c) — 추세 규칙(증가·감소·유지·정점 후 감소·변동·basis 표기) 통과")

    # 독립 검토(10-14) — 왕복(처음=끝이지만 중간에 뚜렷한 정점)은 "유지"로 뭉개지면 안 됨(정점 판정이 유지보다 먼저)
    rt = compute_trend([{"x": "Q1", "value": 10}, {"x": "Q2", "value": 100}, {"x": "Q3", "value": 10}])
    assert rt["direction"] == "정점 후 감소", rt
    # 2점만(정점 판정 자체가 불가능해야 — 중간점이 없음) — 단순 증가/감소로
    assert compute_trend([{"x": "Q1", "value": 10}, {"x": "Q2", "value": 10}])["direction"] == "유지"
    # 완전 평탄
    assert (
        compute_trend([{"x": "Q1", "value": 50}, {"x": "Q2", "value": 50.1}, {"x": "Q3", "value": 49.9}, {"x": "Q4", "value": 50.05}])[
            "direction"
        ]
        == "유지"
    )
    # 잡음 섞인 대체로 증가(41→40→42→52, 중간의 작은 되돌림은 전체 범위의 15% 안 → 증가로 봄)
    noisy = compute_trend([{"x": "Q1", "value": 41}, {"x": "Q2", "value": 40}, {"x": "Q3", "value": 42}, {"x": "Q4", "value": 52}])
    assert noisy["direction"] == "증가", noisy
    print("[selftest] F14(c) 독립 검토(10-14) — 정점 판정이 유지보다 먼저(왕복 10→100→10)·2점·완전 평탄·잡음 섞인 증가 통과")

    # merge_values — 같은 (series,x)(정규화 비교)는 det 우선, vlm 전용 지점은 보존
    det = [{"series": None, "x": "Q1", "value": 50.0, "unit": None, "label": "Q1"}]
    vlm = [{"label": "Q1", "value": "50?", "unit": None}, {"label": "Q2", "value": "30", "unit": None}]
    merged = merge_values(det, vlm)
    assert len(merged) == 2 and merged[0]["value"] == 50.0 and merged[1]["label"] == "Q2"
    # 독립 검토(10-14) — VLM 라벨 서식이 달라도(공백·대소문자·전각) 같은 지점으로 잡아 중복 안 남김
    vlm_fmt = [{"label": "  q1  ", "value": "50?", "unit": None}, {"label": "Ｑ２", "value": "30", "unit": None}]
    merged2 = merge_values(det, vlm_fmt)
    assert len(merged2) == 2 and merged2[0]["value"] == 50.0, merged2  # "q1"(공백·대소문자만 다름)은 det와 겹쳐 안 남음
    assert merged2[1]["label"] == "Ｑ２"  # "Q2"는 det에 없어 보존
    print("[selftest] merge_values — 정규화 (series,x) 비교로 겹치는 지점은 det 우선, 서식 달라도 중복 안 남김 통과")

    # 독립 검토(10-14) — 눈금 글자 파싱 확장: 쉼표·통화 기호·K/M/B 단위·과학적 표기
    assert _to_number("1,200") == 1200.0
    assert _to_number("45%") == 45.0
    assert _to_number("₩1,200") == 1200.0
    assert _to_number("$45") == 45.0
    assert _to_number("1.2K") == 1200.0
    assert _to_number("3M") == 3_000_000.0
    assert _to_number("2B") == 2_000_000_000.0
    assert _to_number("1e6") == 1_000_000.0
    assert _to_number("10^3") == 1000.0
    assert _to_number("abc") is None
    print("[selftest] F14(a) 독립 검토(10-14) — 눈금 파싱 확장(쉼표·통화·K/M/B·과학적 표기) 통과")

    # 독립 검토(10-14) — 로그축: 문자 그대로 "10^n"이 아닌 일반 기하수열(2·20·200·2000)도 로그축으로 인식
    assert _is_log_axis([(20, 2), (120, 20), (220, 200), (320, 2000)]) is True
    assert _is_log_axis([(20, 10), (120, 20), (220, 30), (320, 40)]) is False  # 선형(등차)은 로그 아님
    print("[selftest] F14(a) 독립 검토(10-14) — 일반 기하수열 로그축 판정(10^n 리터럴 아니어도) 통과")

    # 독립 검토(10-14) — 스파인(축 선) 없는 "내보내기 스타일" 막대그래프: 축 선 없이 눈금 숫자(세로 정렬)만,
    # 막대는 둥근 모서리('re'가 아닌 닫힌 채움 경로 — 'l' 세그먼트 4개로 닫은 사각형, 둥근 모서리의 대역)
    doc5 = fitz.open()
    pg5 = doc5.new_page(width=400, height=400)
    for v, y in ((0, 380), (25, 290), (50, 200), (75, 110), (100, 20)):
        pg5.insert_text((10, y + TXT_DY), str(v))
    shape = pg5.new_shape()  # 닫힌 사각형을 'l' 4개로(둥근 모서리 막대의 단순화 대역) — 're' 아님
    shape.draw_line((60, 200), (100, 200))
    shape.draw_line((100, 200), (100, 380))
    shape.draw_line((100, 380), (60, 380))
    shape.draw_line((60, 380), (60, 200))
    shape.finish(fill=(0.2, 0.4, 0.6), closePath=True)
    shape.commit()
    pg5.insert_text((65, 392), "Q1")
    vals5, meta5 = extract_vector(pg5, [0, 0, 400, 400])
    assert meta5["axis"] == "linear", meta5
    assert vals5 and abs(vals5[0]["value"] - 50) < 2, vals5
    print("[selftest] F14(a) 독립 검토(10-14) — 스파인 없는 축(눈금 정렬로 추론) + 닫힌 경로 막대('re' 아님) 통과")

    # 독립 검토(10-14) — Gantt류 거짓 양성 가드: 행마다 세로 위치가 제각각인 수평 막대(공통 기준선 없음)는
    # 세로 막대그래프로 오인하면 안 됨(값을 지어내지 않음)
    doc6 = fitz.open()
    pg6 = doc6.new_page(width=400, height=400)
    pg6.draw_line((20, 20), (20, 380), color=(0, 0, 0), width=1)
    pg6.draw_line((20, 380), (380, 380), color=(0, 0, 0), width=1)
    pg6.insert_text((2, 20 + TXT_DY), "100")
    pg6.insert_text((10, 380 + TXT_DY), "0")
    # 행마다 다른 세로 위치·가로 시작점·가로 길이(날짜 축 느낌의 Gantt 막대) — 공통 바닥선 없음
    pg6.draw_rect(fitz.Rect(60, 60, 160, 100), fill=(0.2, 0.4, 0.6))
    pg6.draw_rect(fitz.Rect(120, 150, 260, 190), fill=(0.3, 0.5, 0.2))
    pg6.draw_rect(fitz.Rect(40, 240, 220, 280), fill=(0.6, 0.3, 0.1))
    pg6.insert_text((60, 392), "W1")
    vals6, meta6 = extract_vector(pg6, [0, 0, 400, 400])
    assert vals6 == [] and meta6.get("chart_type") != "bar", (vals6, meta6)
    print("[selftest] F14 독립 검토(10-14) — Gantt류(공통 기준선 없는 수평 막대) 거짓 양성 가드 통과")

    # 독립 검토(10-14) — 다계열 꺾은선: 선 색을 범례 상자(같은 채움 색) 이름과 맞춰 series를 채움
    doc7 = fitz.open()
    pg7 = doc7.new_page(width=400, height=400)
    pg7.draw_line((20, 20), (20, 380), color=(0, 0, 0), width=1)
    pg7.draw_line((20, 380), (380, 380), color=(0, 0, 0), width=1)
    pg7.insert_text((2, 20 + TXT_DY), "100")
    pg7.insert_text((10, 380 + TXT_DY), "0")
    pg7.draw_polyline([(100, 300), (200, 240), (300, 180)], color=(0.8, 0.1, 0.1), width=2)  # A: 25→40→55
    pg7.draw_polyline([(100, 200), (200, 140), (300, 80)], color=(0.1, 0.1, 0.8), width=2)  # B: 50→65→80
    pg7.draw_rect(fitz.Rect(330, 60, 344, 74), fill=(0.8, 0.1, 0.1))
    pg7.insert_text((348, 71), "A", fontsize=8)
    pg7.draw_rect(fitz.Rect(330, 84, 344, 98), fill=(0.1, 0.1, 0.8))
    pg7.insert_text((348, 95), "B", fontsize=8)
    pg7.insert_text((95, 392), "J1")
    pg7.insert_text((195, 392), "J2")
    pg7.insert_text((295, 392), "J3")
    vals7, meta7 = extract_vector(pg7, [0, 0, 400, 400])
    assert meta7["chart_type"] == "line", meta7
    series_set = {v["series"] for v in vals7}
    assert series_set == {"A", "B"}, vals7
    print("[selftest] F14(a) 독립 검토(10-14) — 다계열 꺾은선(선 색 → 범례 이름) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
