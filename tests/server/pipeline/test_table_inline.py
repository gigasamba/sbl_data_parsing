"""pipeline.transform.represent.table_inline 시험."""

from pipeline.transform.represent.table_inline import inline_tables


def selftest():
    # (1) one-cell-per-line body + a grid -> span replaced by a markdown table, neighbors untouched
    rep = {"text": "앞 문단\nA\nB\n1\n2\n뒤 문단", "tables": [{"grid": [["A", "B"], ["1", "2"]], "page": None}]}
    info = inline_tables(rep, "eng1", {})
    assert info == {"on": True, "groups": 1, "inlined": 1, "unmatched": 0, "sources": {"eng1": 1}, "residue": 0}, info
    assert rep["text"] == "앞 문단\n| A | B |\n|---|---|\n| 1 | 2 |\n뒤 문단", rep["text"]
    assert rep["tables_std"] == [
        {"id": "t0", "page": None, "source_engine": "eng1", "header": ["A", "B"], "rows": [["1", "2"]], "merged": [], "inline": True}
    ], rep["tables_std"]
    print("[selftest] inline_tables — one-cell-per-line span replaced in place, neighbors kept 통과")

    # (2) two engines' grids for the same table -> the more complete one wins and is recorded
    rep2 = {"text": "A\nB\n1\n2", "tables": [{"grid": [["A", "B"], ["1", ""]], "page": 1}]}  # winner's own grid has a hole
    other2 = {"eng2": {"tables": [{"grid": [["A", "B"], ["1", "2"]], "page": 1}]}}  # another engine saw it whole
    info2 = inline_tables(rep2, "eng1", other2)
    assert info2["sources"] == {"eng2": 1} and info2["inlined"] == 1, info2
    assert rep2["tables_std"][0]["source_engine"] == "eng2" and rep2["tables_std"][0]["rows"] == [["1", "2"]], rep2["tables_std"]
    print("[selftest] choose_grid — more complete grid (no hole) wins over the winning engine's own weaker one 통과")

    # (3) no confident span -> text unchanged, recorded as unmatched
    rep3 = {"text": "표와 전혀 무관한 본문", "tables": [{"grid": [["X", "Y", "Z"], ["1", "2", "3"]], "page": None}]}
    info3 = inline_tables(rep3, "eng1", {})
    assert info3 == {"on": True, "groups": 1, "inlined": 0, "unmatched": 1, "sources": {"eng1": 1}, "residue": 0}, info3
    assert rep3["text"] == "표와 전혀 무관한 본문"
    assert rep3["tables_std"][0]["inline"] is False
    print("[selftest] find_span — 확신 없는 표는 본문 불변·unmatched로만 기록 통과")

    # (4) cells containing '|' are escaped
    rep4 = {"text": "A|B\n1\n2", "tables": [{"grid": [["A|B"], ["1"], ["2"]], "page": None}]}
    info4 = inline_tables(rep4, "eng1", {})
    assert info4["inlined"] == 1 and "| A\\|B |" in rep4["text"], rep4["text"]
    print("[selftest] to_markdown 재사용 — 칸 안 '|' escape 통과")

    # (6) render_md does not duplicate an inline table but still appends an unmatched one — see
    # pipeline/load/publish_parse_result.py render_md()'s own test (TA1 adds the `inline` skip there);
    # here we only check the flag table_inline sets is what render_md keys off of.
    assert rep["tables_std"][0]["inline"] is True and rep3["tables_std"][0]["inline"] is False

    # (7) merged cells filled by TB6 (contract._fill_merged) appear in the inline table — covered cells
    # already carry the origin value by the time this module sees the grid (that's TB6's job, done at parse
    # time); reading_order_cells must still find the table span correctly despite the filled duplicates.
    filled_grid = [["배치", "배치", "품목"], ["1", "1", "사과"]]  # colspan-merged header (dup in row0) + a real 3rd col
    rep7 = {"text": "머리말\n배치\n품목\n1\n사과\n꼬리말", "tables": [{"grid": filled_grid, "page": None}]}
    info7 = inline_tables(rep7, "eng1", {})
    assert info7["inlined"] == 1, info7
    assert rep7["tables_std"][0]["rows"] == [["1", "1", "사과"]], rep7["tables_std"]  # merge-filled duplicate kept in the rendered grid
    assert "| 배치 | 배치 | 품목 |" in rep7["text"], rep7["text"]
    print("[selftest] TB6 병합 채움 — reading_order_cells는 채워진 중복을 건너뛰고 찾되, 칸 자체는 그대로(병합 값 유지) 통과")

    # (8) 리뷰 지적 5(engine-qa, 10-21) — 두 칸 사이에 짧은 각주(10자 안팎)가 끼어 있어도(GAP_MAX_CHARS 안이라
    # 교체 영역에 함께 들어가는) 지워지지 않고 표 바로 뒤에 원래 순서대로 남는다.
    footnote = "※측정오차있음"  # 9자 — GAP_MAX_CHARS(20) 안
    rep8 = {"text": f"머리말\nA\nB\n1\n{footnote}\n2\n꼬리말", "tables": [{"grid": [["A", "B"], ["1", "2"]], "page": None}]}
    info8 = inline_tables(rep8, "eng1", {})
    assert info8["inlined"] == 1 and info8["residue"] == 1, info8
    assert footnote in rep8["text"] and "꼬리말" in rep8["text"] and "머리말" in rep8["text"], rep8["text"]
    # 각주는 표 뒤에, 표 자체 칸 값은 안 바뀜
    assert rep8["text"].index("| 1 | 2 |") < rep8["text"].index(footnote), rep8["text"]
    print("[selftest] 리뷰 지적 5 — 칸 사이 짧은 각주는 지워지지 않고 표 뒤에 원래 순서대로 남음(rep.table_inline.residue 집계) 통과")

    # (9) 0.3.0 엔진 비교 — 위 칸과 같아 찾기에서 빠진 칸 둘이 이어진 간격 글("ABX-101 고객사A")과 본문 엔진만의
    # 표기("46355" — 고른 grid는 날짜)는 표에 이미 있는 칸이라 표 뒤에 다시 붙지 않는다(한글 xlsx 334줄 중복).
    own = [["ID", "과제", "고객", "기록일"], ["B1", "ABX-101", "고객사A", "46355"], ["B2", "ABX-101", "고객사A", "46356"]]
    other = [["ID", "과제", "고객", "기록일"], ["B1", "ABX-101", "고객사A", "2026-11-29"], ["B2", "ABX-101", "고객사A", "2026-11-30"]]
    rep9 = {"text": "ID 과제 고객 기록일 B1 ABX-101 고객사A 46355 B2 ABX-101 고객사A 46356", "tables": [{"grid": own, "page": 1}]}
    info9 = inline_tables(rep9, "eng1", {"eng2": {"tables": [{"grid": other, "page": 1}]}})
    assert info9["inlined"] == 1 and info9["residue"] == 0, (info9, rep9["text"])
    assert rep9["text"].count("ABX-101") == 2, rep9["text"]
    print("[selftest] 표 칸으로만 된 간격 글(이어진 칸·본문 엔진 표기)은 표 뒤에 다시 안 붙음 통과")

    # (10) 한 글자 칸("1")을 이어 만든 숫자 각주("11")는 칸이 아니라 각주 — 남는다
    rep10 = {"text": "머리말\nA\nB\n1\n11\n2\n꼬리말", "tables": [{"grid": [["A", "B"], ["1", "2"]], "page": None}]}
    info10 = inline_tables(rep10, "eng1", {})
    assert info10["inlined"] == 1 and info10["residue"] == 1 and "\n11\n" in rep10["text"], (info10, rep10["text"])
    print("[selftest] 한 글자 칸으로 이은 숫자 각주는 지우지 않음 통과")

    print("[selftest] table_inline 전체 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
