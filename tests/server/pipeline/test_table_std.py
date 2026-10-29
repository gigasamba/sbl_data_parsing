"""pipeline.transform.represent.table_std 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.table_std`."""

from pipeline import config as pc
from pipeline.transform.represent.table_std import build_tables, on, stitch_on, to_markdown


def _parse_markdown(md):
    """to_markdown()의 출력만 되돌리는 최소 파서(일반 마크다운 표 전부를 다루진 않음, 왕복 selftest 전용) —
    구분선(|---|) 행은 버리고 나머지 행을 칸으로 쪼갠다. `\\|`는 되돌려 원래 `|`로."""
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        if set(s.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
            continue  # 구분선
        cells, buf, i = [], "", 0
        body = s[1:-1]
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body) and body[i + 1] == "|":
                buf += "|"
                i += 2
                continue
            if body[i] == "|":
                cells.append(buf.strip())
                buf = ""
                i += 1
                continue
            buf += body[i]
            i += 1
        cells.append(buf.strip())
        rows.append(cells)
    return rows


def selftest():
    # 그리드 없는 표(과거 캐시)는 건너뜀 — 새 칸을 억지로 만들지 않음
    assert build_tables([{"rows": 1, "cols": 1, "text": "x"}], "eng1", False) == []
    assert build_tables([], "eng1", False) == [] and build_tables(None, "eng1", False) == []

    # 기본 — 그리드 있는 표는 header(첫 행)·rows(나머지)·merged·source_engine·page로 정규화
    t = {"rows": 2, "cols": 2, "text": "a b 1 2", "grid": [["a", "b"], ["1", "2"]], "page": 1}
    out = build_tables([t], "pymupdf", False)
    assert out == [{"id": "t0", "page": 1, "source_engine": "pymupdf", "header": ["a", "b"], "rows": [["1", "2"]], "merged": []}], out

    # 독립 검토 — 불규칙 그리드(행마다 칸 수 다름, pymupdf류 — 병합 메타 없이 셀 누락)는 가장 긴 행 기준으로 패딩
    ragged = {"rows": 3, "cols": 3, "text": "", "grid": [["a", "b", "c"], ["1", "2"], ["x"]]}
    out_r = build_tables([ragged], "pymupdf", False)[0]
    assert out_r["header"] == ["a", "b", "c"] and out_r["rows"] == [["1", "2", ""], ["x", "", ""]], out_r
    md_r = to_markdown(out_r)
    assert all(len(ln.split("|")) == 5 for ln in md_r.splitlines()), md_r  # 모든 행이 칸 수 3(구분자 5개)로 맞음
    print("[selftest] build_tables — 불규칙 그리드 패딩(칸 수 맞춤, to_markdown 구분선과 일치) 통과")
    print("[selftest] build_tables — 그리드 있는 표만 정규화 · 그리드 없으면 건너뜀 통과")

    # 병합 칸 펼침 — office_stdlib이 이미 펼친 그리드(같은 값 채움) + merges 범위를 그대로 옮김
    t2 = {"rows": 2, "cols": 2, "text": "", "grid": [["A", "A"], ["1", "2"]], "merges": [{"r": 0, "c": 0, "rowspan": 1, "colspan": 2}]}
    out2 = build_tables([t2], "office", False)
    assert out2[0]["header"] == ["A", "A"] and out2[0]["merged"] == [{"r": 0, "c": 0, "rowspan": 1, "colspan": 2}]
    print("[selftest] build_tables — merges 그대로 보존(펼친 값은 엔진이 이미 채움) 통과")

    # TB5 — 머리글 행 3단(merges가 행별로 덮는 범위로 depth=3 추정) — header_rows에 원본 3행 그대로,
    # header는 칸별 평펴 라벨, rows는 데이터 행부터
    t_tb5 = {
        "grid": [
            ["부문", "2026년", "2026년", "2026년", "2026년"],
            ["부문", "상반기", "상반기", "하반기", "하반기"],
            ["부문", "1분기", "2분기", "3분기", "4분기"],
            ["CDMO", "120", "135", "150", "162"],
            ["CDO", "40", "38", "45", "51"],
        ],
        "merges": [
            {"r": 0, "c": 0, "rowspan": 3, "colspan": 1},
            {"r": 0, "c": 1, "rowspan": 1, "colspan": 4},
            {"r": 1, "c": 1, "rowspan": 1, "colspan": 2},
            {"r": 1, "c": 3, "rowspan": 1, "colspan": 2},
        ],
    }
    out_tb5 = build_tables([t_tb5], "office", False)[0]
    assert out_tb5["rows"][0] == ["CDMO", "120", "135", "150", "162"], out_tb5  # 데이터 행부터(머리글 3행 안 섞임)
    assert len(out_tb5["header_rows"]) == 3 and out_tb5["header_rows"][2] == t_tb5["grid"][2], out_tb5
    assert out_tb5["header"] == [
        "부문",
        "2026년 / 상반기 / 1분기",
        "2026년 / 상반기 / 2분기",
        "2026년 / 하반기 / 3분기",
        "2026년 / 하반기 / 4분기",
    ], out_tb5
    # 단일 머리글(흔한 경우)은 기존과 바이트 동일 — header_rows 칸 자체가 안 생김
    assert "header_rows" not in out[0], out
    print("[selftest] build_tables — TB5: 다단 머리글은 header_rows 보존·header는 평펴 라벨·단일 머리글은 불변 통과")

    # TB5 재검토(블록 acc829ab) 음성 시험 — 맨 위에 안 닿은 병합·숫자/비숫자 추정(옛 rule-b, 완전히 제거)은
    # 머리글 증거로 안 셈
    # (a) 데이터 행 한가운데서 시작하는 rowspan('비고' 칸이 데이터 행 2개를 덮음, r=1 — row0 아래) → depth 1
    t_neg_a = {
        "grid": [["부문", "수치", "비고"], ["CDMO", "120", "해당없음"], ["CDO", "40", "해당없음"]],
        "merges": [{"r": 1, "c": 2, "rowspan": 2, "colspan": 1}],
    }
    out_neg_a = build_tables([t_neg_a], "office", False)[0]
    assert "header_rows" not in out_neg_a and out_neg_a["header"] == ["부문", "수치", "비고"], out_neg_a
    assert out_neg_a["rows"] == [["CDMO", "120", "해당없음"], ["CDO", "40", "해당없음"]], out_neg_a
    # (b') 중간의 전체 폭 비고 행 바로 뒤에 순수 숫자 행들이 옴(옛 rule-b가 걸리던 모양) — 병합 없어도,
    # 병합이 있어도(중간 행이라 r>=depth라 무시) depth 1
    grid_note_then_numbers = [["품목", "수량"], ["단가", "100"], ["전체 특이사항 없음", "전체 특이사항 없음"], ["10", "20"], ["30", "40"]]
    out_neg_b1 = build_tables([{"grid": grid_note_then_numbers}], "pymupdf", False)[0]  # 병합 정보 자체가 없음
    assert "header_rows" not in out_neg_b1 and out_neg_b1["header"] == ["품목", "수량"], out_neg_b1
    assert out_neg_b1["rows"] == grid_note_then_numbers[1:], out_neg_b1
    out_neg_b2 = build_tables(
        [{"grid": grid_note_then_numbers, "merges": [{"r": 2, "c": 0, "rowspan": 1, "colspan": 2}]}], "office", False
    )[0]
    assert "header_rows" not in out_neg_b2 and out_neg_b2["header"] == ["품목", "수량"], out_neg_b2
    assert out_neg_b2["rows"] == grid_note_then_numbers[1:], out_neg_b2
    # (c') 병합 없는 표 — 텍스트 라벨 행(비숫자) 바로 뒤에 순수 숫자 행들이 옴(옛 rule-b가 걸리던 모양) → depth 1
    grid_text_then_numbers = [["항목", "값1", "값2"], ["라벨A", "라벨B", "라벨C"], ["10", "20", "30"], ["40", "50", "60"]]
    out_neg_c = build_tables([{"grid": grid_text_then_numbers}], "pymupdf", False)[0]
    assert "header_rows" not in out_neg_c and out_neg_c["header"] == ["항목", "값1", "값2"], out_neg_c
    assert out_neg_c["rows"] == grid_text_then_numbers[1:], out_neg_c
    print(
        "[selftest] build_tables — TB5 음성: 데이터 행 한가운데서 시작하는 병합·중간 비고 행(병합 유무 "
        "둘 다)·비숫자 라벨 행+숫자 행(병합 없음)은 전부 depth 1(옛 rule-b 제거 확인) 통과"
    )

    # PARSE_STANDARDIZE 스위치 따름 — 켜지면(std_on=True) 칸 글자에 기호 맵 적용
    t3 = {"rows": 1, "cols": 2, "text": "", "grid": [["95％", "B–1"]]}
    out3 = build_tables([t3], "office", True)
    assert out3[0]["header"] == ["95%", "B-1"], out3  # canon_symbols(전각·대시) 적용
    out3b = build_tables([t3], "office", False)
    assert out3b[0]["header"] == ["95％", "B–1"]  # 꺼지면 원문 그대로
    print("[selftest] build_tables — PARSE_STANDARDIZE 스위치 따름(켜짐=기호 맵 적용·꺼짐=원문) 통과")

    # BR36 — 쪽 경계 표 이어 붙이기: 쪽1·쪽2가 같은 머리행(longtable.pdf 실측 모양)이면 하나로 합치고
    # 뒤 표의 반복 머리행은 버림(행만 이어붙임)
    p1 = {"page": 1, "grid": [["배치", "순도"], ["B-01", "99.3"], ["B-02", "99.1"]]}
    p2 = {"page": 2, "grid": [["배치", "순도"], ["B-03", "99.0"]]}
    stitched = build_tables([p1, p2], "pymupdf", False)
    assert stitched == [
        {
            "id": "t0",
            "page": 2,
            "source_engine": "pymupdf",
            "header": ["배치", "순도"],
            "rows": [["B-01", "99.3"], ["B-02", "99.1"], ["B-03", "99.0"]],
            "merged": [],
        }
    ], stitched
    print("[selftest] stitch_tables — 쪽 경계(N→N+1)·같은 머리행 — 하나로 합침·반복 머리행 버림 통과")

    # 오합 방지 ① 머리행이 다름(칸 수 같아도 글자 다름) — 안 합침(표 2개 그대로)
    p2_diff_header = {"page": 2, "grid": [["구분", "비율"], ["B-03", "99.0"]]}
    not_stitched = build_tables([p1, p2_diff_header], "pymupdf", False)
    assert len(not_stitched) == 2 and not_stitched[0]["page"] == 1 and not_stitched[1]["page"] == 2, not_stitched
    # 오합 방지 ② 칸 수가 다름 — 안 합침
    p2_diff_cols = {"page": 2, "grid": [["배치", "순도", "수율"], ["B-03", "99.0", "91.0"]]}
    not_stitched2 = build_tables([p1, p2_diff_cols], "pymupdf", False)
    assert len(not_stitched2) == 2, not_stitched2
    # 오합 방지 ③ 쪽 정보가 없음(엔진이 page를 안 남김, kreuzberg·markitdown류) — 안 합침
    no_page1 = {"page": None, "grid": [["배치", "순도"], ["B-01", "99.3"]]}
    no_page2 = {"page": None, "grid": [["배치", "순도"], ["B-03", "99.0"]]}
    not_stitched3 = build_tables([no_page1, no_page2], "kreuzberg", False)
    assert len(not_stitched3) == 2, not_stitched3
    # 오합 방지 ④ 쪽이 이웃이 아님(N→N+2, 중간 쪽 건너뜀) — 안 합침
    p3 = {"page": 3, "grid": [["배치", "순도"], ["B-05", "98.0"]]}
    not_stitched4 = build_tables([p1, p3], "pymupdf", False)
    assert len(not_stitched4) == 2, not_stitched4
    print("[selftest] stitch_tables — 오합 방지(머리행 다름·칸 수 다름·쪽 정보 없음·쪽 안 이웃) 통과")

    # PARSE_TABLE_STITCH=0이면 꺼짐(쪽마다 쪼개진 채 그대로, 이 기능 이전 동작)
    with pc.PIPE.env(PARSE_TABLE_STITCH="0"):  # S7c — 설정 객체만 바꿔 끼움(바깥 값은 저절로 복원)
        off = build_tables([p1, p2], "pymupdf", False)
        assert len(off) == 2, off
    print("[selftest] stitch_tables — PARSE_TABLE_STITCH=0 끔(쪽마다 쪼개진 채 그대로) 통과")

    assert on("1") is True and on("0") is False and on() in (True, False)
    assert stitch_on("1") is True and stitch_on("0") is False and stitch_on() in (True, False)

    # 마크다운 왕복 — tables_std → 마크다운 → 다시 파싱 = 같은 표(header+rows, merged는 마크다운에 없음 — 값은 이미 펼쳐짐)
    entry = {
        "id": "t0",
        "page": None,
        "source_engine": "office",
        "header": ["제품", "단가"],
        "rows": [["A-1", "1,000"], ["B-2", "2,000"]],
        "merged": [],
    }
    md = to_markdown(entry)
    back = _parse_markdown(md)
    assert back == [entry["header"]] + entry["rows"], (md, back)
    # escape 왕복 — 칸 안 '|'도 같게 돌아옴
    entry2 = {"id": "t1", "page": None, "source_engine": "office", "header": ["a|b", "c"], "rows": [["1", "2"]], "merged": []}
    back2 = _parse_markdown(to_markdown(entry2))
    assert back2 == [entry2["header"]] + entry2["rows"], back2
    print("[selftest] 마크다운 왕복(tables_std → md → 다시 파싱 = 같은 표, '|' escape 포함) 통과")
    print("[selftest] table_std 전체 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
