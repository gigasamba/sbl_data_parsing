"""pipeline.transform.figures.diagram_edges 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.diagram_edges`."""

from pipeline.transform.figures.diagram_edges import _box_name, _chevron_apex, glyph_edges, merge_edges, vector_edges_from_page


def selftest():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    boxA, boxB = fitz.Rect(50, 50, 150, 100), fitz.Rect(250, 50, 350, 100)
    shape.draw_rect(boxA)
    shape.finish(color=(0, 0, 0), fill=(0.9, 0.9, 1), width=1.2)
    shape.draw_rect(boxB)
    shape.finish(color=(0, 0, 0), fill=(0.9, 0.9, 1), width=1.2)
    shape.draw_line((150, 75), (240, 75))
    shape.finish(color=(0, 0, 0), width=1.0)
    shape.draw_polyline([(240, 75), (230, 70), (230, 80), (240, 75)])  # 화살촉(채운 삼각형) — B쪽 끝
    shape.finish(color=(0, 0, 0), fill=(0, 0, 0), width=1.0)
    shape.commit()
    page.insert_textbox(fitz.Rect(50, 55, 150, 95), "A", fontname="helv", fontsize=12, align=1)
    page.insert_textbox(fitz.Rect(250, 55, 350, 95), "B", fontname="helv", fontsize=12, align=1)
    edges = vector_edges_from_page(page, (0, 0, page.rect.width, page.rect.height))
    assert edges == [{"from": "A", "to": "B", "label": None}], edges

    # 세로 + 엘보, 화살촉(채운 삼각형) D쪽 끝 — 세로 방향도 같은 규칙으로 head 인식
    doc2 = fitz.open()
    pg2 = doc2.new_page()
    boxC, boxD = fitz.Rect(50, 50, 150, 100), fitz.Rect(50, 200, 150, 250)
    sh2 = pg2.new_shape()
    sh2.draw_rect(boxC)
    sh2.finish(color=(0, 0, 0), width=1.0)
    sh2.draw_rect(boxD)
    sh2.finish(color=(0, 0, 0), width=1.0)
    sh2.draw_line((100, 100), (100, 193))
    sh2.finish(color=(0, 0, 0), width=1.0, closePath=False)
    sh2.draw_polyline([(100, 200), (95, 191), (105, 191), (100, 200)])
    sh2.finish(color=(0, 0, 0), fill=(0, 0, 0), width=1.0)
    sh2.commit()
    pg2.insert_textbox(fitz.Rect(50, 55, 150, 95), "C", fontname="helv", fontsize=12, align=1)
    pg2.insert_textbox(fitz.Rect(50, 205, 150, 245), "D", fontname="helv", fontsize=12, align=1)
    edges2 = vector_edges_from_page(pg2, (0, 0, pg2.rect.width, pg2.rect.height))
    assert edges2 == [{"from": "C", "to": "D", "label": None}], edges2
    print("[selftest] vector_edges_from_page — 가로·세로 채운 화살촉 통과")

    # 화살촉 없는 상자+직선(AD13류) — 독립 검토 CONCERN② 대응: 더 이상 읽는 순서로 대체하지 않고 버린다
    doc2b = fitz.open()
    pg2b = doc2b.new_page()
    sh2b = pg2b.new_shape()
    sh2b.draw_rect(fitz.Rect(50, 50, 150, 100))
    sh2b.finish(color=(0, 0, 0), width=1.0)
    sh2b.draw_rect(fitz.Rect(50, 200, 150, 250))
    sh2b.finish(color=(0, 0, 0), width=1.0)
    sh2b.draw_line((100, 100), (100, 200))
    sh2b.finish(color=(0, 0, 0), width=1.0)
    sh2b.commit()
    pg2b.insert_textbox(fitz.Rect(50, 55, 150, 95), "C", fontname="helv", fontsize=12, align=1)
    pg2b.insert_textbox(fitz.Rect(50, 205, 150, 245), "D", fontname="helv", fontsize=12, align=1)
    edges2b = vector_edges_from_page(pg2b, (0, 0, pg2b.rect.width, pg2b.rect.height))
    assert edges2b == [], edges2b
    print("[selftest] vector_edges_from_page — 화살촉 없으면 버림(읽는 순서 대체 없음) 통과")

    # 엘보(여러 꼭짓점) 되돌림 연결선 — E(오른쪽 위) → F(왼쪽 아래), 화살촉은 F쪽. closePath=False로 열린 경로로
    # 그려도(실제 연결선 관례) _path_endpoints가 첫·마지막 점을 그대로 쓴다(닫기 선분이 없으니 뗄 것도 없음).
    doc3 = fitz.open()
    pg3 = doc3.new_page(width=400, height=300)
    boxE, boxF = fitz.Rect(300, 20, 380, 60), fitz.Rect(20, 220, 100, 260)
    sh3 = pg3.new_shape()
    sh3.draw_rect(boxE)
    sh3.finish(color=(0, 0, 0), width=1.0)
    sh3.draw_rect(boxF)
    sh3.finish(color=(0, 0, 0), width=1.0)
    sh3.draw_line((340, 60), (340, 240))
    sh3.draw_line((340, 240), (100, 240))
    sh3.finish(color=(0, 0, 0), width=1.0, closePath=False)  # 엘보 2구간, 열린 경로(닫기 선분 없음)
    sh3.draw_polyline([(100, 240), (118, 236), (118, 244), (100, 240)])  # 화살촉(뾰족하게 — apex 판정용) — F쪽 끝
    sh3.finish(color=(0, 0, 0), fill=(0, 0, 0), width=1.0)
    sh3.commit()
    pg3.insert_textbox(fitz.Rect(300, 25, 380, 55), "E", fontname="helv", fontsize=12, align=1)
    pg3.insert_textbox(fitz.Rect(20, 225, 100, 255), "F", fontname="helv", fontsize=12, align=1)
    edges3 = vector_edges_from_page(pg3, (0, 0, pg3.rect.width, pg3.rect.height))
    assert edges3 == [{"from": "E", "to": "F", "label": None}], edges3
    print("[selftest] vector_edges_from_page — 엘보(되돌림) 연결선, 화살촉 쪽이 head 통과")

    # 열린 쉐브론(두 짧은 선분, 채움 없음) 화살촉 — 독립 검토 CONCERN①: 채운 다각형만 보던 것을 넓힘
    doc4 = fitz.open()
    pg4 = doc4.new_page()
    boxG, boxH = fitz.Rect(50, 50, 150, 100), fitz.Rect(250, 50, 350, 100)
    sh4 = pg4.new_shape()
    sh4.draw_rect(boxG)
    sh4.finish(color=(0, 0, 0), width=1.0)
    sh4.draw_rect(boxH)
    sh4.finish(color=(0, 0, 0), width=1.0)
    sh4.draw_line((150, 75), (242, 75))
    sh4.finish(color=(0, 0, 0), width=1.0, closePath=False)
    sh4.draw_line((234, 68), (242, 75))
    sh4.draw_line((234, 82), (242, 75))
    sh4.finish(color=(0, 0, 0), width=1.0, closePath=False)  # 쉐브론(화살촉) — 채움 없음
    sh4.commit()
    pg4.insert_textbox(fitz.Rect(50, 55, 150, 95), "G", fontname="helv", fontsize=12, align=1)
    pg4.insert_textbox(fitz.Rect(250, 55, 350, 95), "H", fontname="helv", fontsize=12, align=1)
    edges4 = vector_edges_from_page(pg4, (0, 0, pg4.rect.width, pg4.rect.height))
    assert edges4 == [{"from": "G", "to": "H", "label": None}], edges4
    print("[selftest] vector_edges_from_page — 열린 쉐브론 화살촉(채움 없음) 통과")

    # 라벨이 상자 밖(아래)에 있는 스타일 — 상자 안이 비어 있으면 아래 가까운 글자줄로 이름 대체
    doc5 = fitz.open()
    pg5 = doc5.new_page()
    boxI, boxJ = fitz.Rect(50, 50, 150, 90), fitz.Rect(250, 50, 350, 90)
    sh5 = pg5.new_shape()
    sh5.draw_rect(boxI)
    sh5.finish(color=(0, 0, 0), width=1.0)
    sh5.draw_rect(boxJ)
    sh5.finish(color=(0, 0, 0), width=1.0)
    sh5.draw_line((150, 70), (240, 70))
    sh5.finish(color=(0, 0, 0), width=1.0)
    sh5.draw_polyline([(240, 70), (230, 65), (230, 75), (240, 70)])
    sh5.finish(color=(0, 0, 0), fill=(0, 0, 0), width=1.0)
    sh5.commit()
    pg5.insert_textbox(fitz.Rect(50, 94, 150, 120), "I", fontname="helv", fontsize=10, align=1)  # 상자 밖(아래)
    pg5.insert_textbox(fitz.Rect(250, 94, 350, 120), "J", fontname="helv", fontsize=10, align=1)
    edges5 = vector_edges_from_page(pg5, (0, 0, pg5.rect.width, pg5.rect.height))
    assert edges5 == [{"from": "I", "to": "J", "label": None}], edges5
    print("[selftest] vector_edges_from_page — 상자 밖(아래) 라벨 대체 통과")

    # 영역 보호장치 — 화살촉 없는 표(상자 여러 개·직선 여러 개, 화살표 없음)는 edges 전혀 안 냄
    doc6 = fitz.open()
    pg6 = doc6.new_page()
    sh6 = pg6.new_shape()
    for i in range(3):
        sh6.draw_rect(fitz.Rect(50 + i * 110, 50, 150 + i * 110, 90))
        sh6.finish(color=(0, 0, 0), width=1.0)
    sh6.draw_line((150, 70), (160, 70))
    sh6.draw_line((260, 70), (270, 70))
    sh6.finish(color=(0, 0, 0), width=1.0)
    sh6.commit()
    pg6.insert_textbox(fitz.Rect(50, 55, 150, 85), "K1", fontname="helv", fontsize=10, align=1)
    pg6.insert_textbox(fitz.Rect(160, 55, 260, 85), "K2", fontname="helv", fontsize=10, align=1)
    pg6.insert_textbox(fitz.Rect(270, 55, 370, 85), "K3", fontname="helv", fontsize=10, align=1)
    edges6 = vector_edges_from_page(pg6, (0, 0, pg6.rect.width, pg6.rect.height))
    assert edges6 == [], edges6
    print("[selftest] vector_edges_from_page — 화살촉 없는 영역(표류) 보호장치로 빈 목록 통과")

    g = glyph_edges("접수 Intake → 검토 Review\n검토 Review -> 승인 Approval\n승인 Approval ↓ 시행 Execute\n반려 Reject ← 검토 Review")
    assert g == [
        {"from": "접수 Intake", "to": "검토 Review", "label": None},
        {"from": "검토 Review", "to": "승인 Approval", "label": None},
        {"from": "승인 Approval", "to": "시행 Execute", "label": None},
        {"from": "검토 Review", "to": "반려 Reject", "label": None},  # ← 는 역방향
    ], g
    chain = glyph_edges("A -> B -> C")
    assert chain == [{"from": "A", "to": "B", "label": None}, {"from": "B", "to": "C", "label": None}], chain
    print("[selftest] glyph_edges — →·->·↓·←(역방향)·사슬 통과")

    merged, used = merge_edges(
        [
            ("vector", [{"from": "A", "to": "B", "label": None}]),
            ("glyph", [{"from": "A", "to": "B", "label": "x"}, {"from": "B", "to": "C", "label": None}]),
            ("vlm", [{"from": "C", "to": "D", "label": None}]),
        ]
    )
    assert merged == [
        {"from": "A", "to": "B", "label": None},
        {"from": "B", "to": "C", "label": None},
        {"from": "C", "to": "D", "label": None},
    ]
    assert used == ["vector", "glyph", "vlm"], used
    merged2, used2 = merge_edges([("vector", []), ("vlm", [{"from": "A", "to": "B", "label": None}])])
    assert used2 == ["vlm"] and merged2 == [{"from": "A", "to": "B", "label": None}]
    # 독립 검토 CONCERN③ — 역방향 VLM edge(B→A)가 우선순위 높은 소스(vector, A→B)와 같은 무방향 짝이면
    # vlm은 기여하지 못하고(used에 안 들어감) vector의 방향(A→B)만 남는다.
    merged3, used3 = merge_edges(
        [("vector", [{"from": "A", "to": "B", "label": None}]), ("vlm", [{"from": "B", "to": "A", "label": None}])]
    )
    assert merged3 == [{"from": "A", "to": "B", "label": None}], merged3
    assert used3 == ["vector"], used3
    print("[selftest] merge_edges — 우선순위 중복 제거(무방향 정규화 짝, 역방향 VLM은 안 이김) + 쓰인 소스만 통과")

    # 재검 CONCERN③ — 쉐브론은 팔 길이 비슷·벌어진 각 15~100°만(표 모서리처럼 한쪽 팔이 길거나 일자로 펴진 것은 아님)
    def _chev(p0, apex, p1):
        P = fitz.Point
        return {
            "items": [("l", P(*p0), P(*apex)), ("l", P(*apex), P(*p1))],
            "fill": None,
            "rect": fitz.Rect(
                min(p0[0], apex[0], p1[0]), min(p0[1], apex[1], p1[1]), max(p0[0], apex[0], p1[0]), max(p0[1], apex[1], p1[1])
            ),
        }

    assert _chevron_apex(_chev((0, 0), (8, 4), (0, 8)), 20) is not None  # 진짜 쉐브론(약 53°)
    assert _chevron_apex(_chev((0, 0), (8, 0), (8, 3)), 20) is None  # 직각 모서리, 팔 길이 8 vs 3
    assert _chevron_apex(_chev((0, 0), (5, 1), (10, 0)), 20) is None  # 거의 일자(≈158°)
    # 재검 CONCERN② — 상자 밖 이름은 그 상자에 가장 가까운 글자만(옆 상자에 더 가까운 글자는 안 가져감)
    W = [(10, 32, 30, 40, "lab1"), (52, 32, 72, 40, "lab2")]
    r1, r2 = fitz.Rect(10, 10, 30, 30), fitz.Rect(52, 10, 72, 30)
    assert _box_name(r1, W, 25, [r1, r2]) == "lab1" and _box_name(r2, W, 25, [r1, r2]) == "lab2"
    assert _box_name(r1, [(34, 15, 46, 25, "mid")], 25, [r1, fitz.Rect(36, 10, 56, 30)]) == ""  # 옆 상자 안 글자는 남의 것
    print("[selftest] 재검 — 쉐브론 팔 길이·각도 조건 · 상자 밖 이름 소유권(더 가까운 상자 우선) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
