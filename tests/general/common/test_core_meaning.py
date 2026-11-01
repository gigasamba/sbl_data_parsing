"""common.core.meaning 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.meaning`."""

from common.core.meaning import strip_page_numbers, tokens


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    doc = "작성자: 김서윤 · 작성일 2026-07-13\n계약 D-2024-122 단가 USD 188 / g\n------\n/// 표 ///\n12,000 | 7.8%\n- 1 -\f머리말 문서번호 Q-77\n본문 2\n3\nPage 2 of 3"
    ts = tokens(doc)
    for must in ("작성자", "2026-07-13", "D-2024-122", "12000", "7.8%", "USD", "Q-77", "머리말"):
        assert must in ts, must
    for never in ("---", "///", "1", "Page"):
        assert never not in ts, never
    assert "Page 2 of 3" not in strip_page_numbers(doc) and "- 1 -" not in strip_page_numbers(doc)
    assert "본문 2" in strip_page_numbers(doc)
    print("[selftest] 유의미 텍스트 규칙 통과", sorted(ts)[:12])

    # AD25(a)(e) — 토큰 정규화(늘 켬)
    CASES = "단가 무관.배치 430,000원 430.000 4,30,000 430 000"
    ts_on = tokens(CASES)
    assert ts_on == {"단가", "무관", "배치", "430000", "430.000", "4,30,000"}, sorted(ts_on)
    assert "무관.배치" not in ts_on and "430,000원" not in ts_on and "430" not in ts_on and "000" not in ts_on
    assert "430.000" in ts_on and "4,30,000" in ts_on  # 모호한 마침표·무효 쉼표 묶음은 원문 그대로(430000과 다른 토큰 — 조용히 안 합침)
    assert tokens("작성자 2026-07-13 D-2024-122 Q-77 7.8%") == {
        "작성자",
        "2026-07-13",
        "D-2024-122",
        "Q-77",
        "7.8%",
    }  # 날짜·ID·퍼센트는 안 건드림
    print("[selftest] AD25(a)(e) 토큰 정규화 통과", sorted(ts_on))
