"""pipeline.extract.engines._common.contract(엔진 공용 도우미 — 엔진 지문 파일) 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로,
`global TABLE_GRID_MAX_ROWS` 두 줄만 모듈 속성으로). 옛 사례 `python -m pipeline.extract.engines._common.contract`.
⚠️ 이 옮기기는 엔진 지문 27개를 바꾼다(사용자 10-28 — 따로 한 커밋, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

from pipeline.extract.engines._common import contract as M
from pipeline.extract.engines._common.contract import _fill_merged, _html_rows, _mk_table, _table_facts, fill_merged_on, split_tables


def selftest():
    # AD24② — 한 시트의 표 3개가 빈 행·제목 행(칸 1개만 채워짐)으로 떨어져 있으면 표 3개로 나뉨(kreuzberg 대표 실측 그리드)
    grid = [
        ["원료 사용 현황 (가상)", "", "", ""],
        ["", "", "", ""],
        ["원료", "1월", "2월", "3월"],
        ["Glucose", "120", "135", "128"],
        ["Glutamine", "40", "42", "39"],
        ["소계", "", "", ""],
        ["", "", "", ""],
        ["", "", "", ""],
        ["두 번째 표: 장비 가동률", "", "", ""],
        ["장비", "가동률", "비고", ""],
        ["BR-2001", "92%", "", ""],
        ["BR-2002", "71%", "점검 2주", ""],
        ["", "", "", ""],
        ["세 번째 표: 시험 기준(첨자)", "", "", ""],
        ["항목", "기준", "", ""],
        ["CO2 농도", "5%", "", ""],
        ["세포 밀도", "≥ 1.0×106 cells/mL", "", ""],
    ]
    groups = split_tables(grid)
    assert len(groups) == 3, groups
    (cap0, tb0), (cap1, tb1), (cap2, tb2) = groups
    assert cap0 == "원료 사용 현황 (가상)" and tb0[0] == ["원료", "1월", "2월", "3월"] and tb0[-1][0] == "Glutamine"
    assert cap1 == "두 번째 표: 장비 가동률" and tb1[0][0] == "장비"
    assert cap2 == "세 번째 표: 시험 기준(첨자)" and tb2[0][0] == "항목"
    assert split_tables([]) == []
    assert split_tables([["단일 칸"]]) == [(None, [["단일 칸"]])]  # 열 1개뿐인 표는 경계로 안 쪼개짐
    print("[selftest] 표 경계 분리(빈 행·제목 행, 캡션 분리, AD24②) 통과")

    # review 1차 ② — 표 가운데 낀 빈 행 1개(양옆이 다 데이터)는 안 쪼개짐
    mid_blank = [["이름", "수량"], ["A", "10"], ["", ""], ["B", "20"]]
    g = split_tables(mid_blank)
    assert len(g) == 1 and g[0][0] is None and g[0][1] == mid_blank, g  # 안 쪼개짐 · 캡션 없음 · 행 전부 보존(안 버림)
    # 빈 행 2개 이상 연속은 경계
    g2 = split_tables([["이름", "수량"], ["A", "10"], ["", ""], ["", ""], ["B", "20"]])
    assert len(g2) == 2 and g2[0][1] == [["이름", "수량"], ["A", "10"]] and g2[1][1] == [["B", "20"]], g2
    # 병합 셀 데이터 행(칸 1개뿐)이 표 중간(양옆 다 데이터)에 끼면 버리지 않고 앞 표에 붙음
    mid_merge = [["이름", "수량", "비고"], ["A", "10", "-"], ["구간2 합계", "", ""], ["B", "20", "-"]]
    g3 = split_tables(mid_merge)
    assert len(g3) == 1 and g3[0][0] is None and g3[0][1] == mid_merge, g3
    print("[selftest] 표 중간 빈 행 1개·병합 셀 행 보존(review 1차②) 통과")

    # AD24③ — 머리글(1월·2월·3월처럼 숫자+한글 섞인 열 이름)이 사실로 안 들어감
    facts = _table_facts(tb0)
    assert all(f["context"][0] != "원료" for f in facts), facts
    assert {f["context"][0] for f in facts} == {"Glucose", "Glutamine"}
    print("[selftest] 머리글 행 제외(AD24③) 통과")

    # review 1차 ① — '3개·5명·10건'처럼 데이터 행이 전부 숫자+한글 단위뿐이면(아래 행과 모양이 같으면) 머리글로 안 버림
    same_shape = [["재고", "3개", "5명", "10건"], ["재고2", "7개", "2명", "4건"]]
    facts2 = _table_facts(same_shape)
    assert {f["context"][0] for f in facts2} == {"재고", "재고2"}, facts2
    print("[selftest] 숫자+한글 단위뿐인 첫 데이터 행을 머리글로 오판 안 함(review 1차①) 통과")

    # AD23 독립 검토 — TABLE_GRID_MAX_ROWS: grid만 상한에서 잘리고(truncated=True) rows·cols·text는 그대로(집계 불변)
    saved_max = M.TABLE_GRID_MAX_ROWS  # S9 — 옛 `global TABLE_GRID_MAX_ROWS`(모듈 전역을 _mk_table이 읽음 → 모듈 속성으로)
    M.TABLE_GRID_MAX_ROWS = 2
    try:
        big = [["r0", "a"], ["r1", "b"], ["r2", "c"]]
        t = _mk_table(big)
        assert len(t["grid"]) == 2 and t["grid"] == [["r0", "a"], ["r1", "b"]] and t.get("truncated") is True
        assert t["rows"] == 3 and t["cols"] == 2  # 집계용 칸은 상한과 무관
        small = _mk_table([["x"]])
        assert "truncated" not in small and len(small["grid"]) == 1
    finally:
        M.TABLE_GRID_MAX_ROWS = saved_max
    print("[selftest] AD23 — TABLE_GRID_MAX_ROWS 넘으면 grid만 잘림(truncated 표시)·rows·cols·text 불변 통과")

    # TB2 — rowspan·colspan 펼침(office_stdlib와 같은 방식: covered 칸 = origin 값)
    span_html = (
        "<table><tr><th rowspan='2'>항목</th><th colspan='2'>시험</th></tr>"
        "<tr><th>세부</th><th>판정</th></tr>"
        "<tr><td>L1</td><td>7.0</td><td>적합</td></tr></table>"
    )
    tabs = _html_rows(span_html)
    assert len(tabs) == 1, tabs
    assert tabs[0] == [["항목", "시험", "시험"], ["항목", "세부", "판정"], ["L1", "7.0", "적합"]], tabs[0]
    print("[selftest] TB2 — rowspan·colspan 펼침(covered 칸 origin 값) 통과")

    # TB2 — 중첩 <table>은 별도 표로(바깥 표가 안쪽 </table>에서 안 잘림, nested_table.html '적합' 소실 재현)
    nested_html = (
        "<table><tr><th rowspan='2'>로트</th><th colspan='2'>시험</th></tr>"
        "<tr><th>세부 결과</th><th>판정</th></tr>"
        "<tr><td>L-2702</td><td>"
        "<table><tr><td>pH</td><td>7.0</td></tr><tr><td>엔도톡신</td><td>&lt;0.05 EU/mL</td></tr></table>"
        "</td><td>적합</td></tr></table>"
    )
    outer_tabs = _html_rows(nested_html)
    assert len(outer_tabs) == 2, outer_tabs  # 중첩 표 + 바깥 표, 둘 다 보존
    inner, outer = outer_tabs
    assert inner == [["pH", "7.0"], ["엔도톡신", "<0.05 EU/mL"]], inner  # 중첩 표(엔터티 &lt; 해석 포함)
    assert outer[0] == ["로트", "시험", "시험"]  # colspan 머리글이 하위 칸 모두에
    assert outer[1] == ["로트", "세부 결과", "판정"]  # rowspan 값이 덮인 행마다
    assert outer[2][0] == "L-2702" and outer[2][2] == "적합", outer[2]  # 바깥 표 마지막 칸("적합") 보존 — 이전 정규식 버그
    print("[selftest] TB2 — 중첩 <table> 분리·바깥 표 마지막 칸 보존(nested_table.html 재현) 통과")

    # TB6 — _fill_merged: None(병합 covered 칸, pdfplumber·pymupdf 그리드 신호) → origin 값, ""(진짜 빈칸)는 안 건드림
    merged_grid = [["항목", "시험", None], [None, "세부", "판정"], ["L1", "7.0", "적합"], ["L2", "", "부적합"]]
    filled = _fill_merged(merged_grid)
    assert filled == [["항목", "시험", "시험"], ["항목", "세부", "판정"], ["L1", "7.0", "적합"], ["L2", "", "부적합"]], filled
    assert _fill_merged([]) == [] and _fill_merged(None) is None
    assert fill_merged_on("1") is True and fill_merged_on("0") is False and fill_merged_on() in (True, False)
    print('[selftest] TB6 — _fill_merged: rowspan·colspan covered 칸(None)만 origin 값 채움·진짜 빈칸("") 불변 통과')


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
