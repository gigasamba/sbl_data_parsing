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

    # AD25 — PARSE_TOKEN_NORM=0 = 지금과 바이트 동일(기존 동작: 쉼표는 무조건 제거·마침표/공백은 안 건드림)
    from common.config.settings import COMMON  # S7b — 시험이 env 대신 설정 객체를 덮어씀(os.environ을 안 건드리므로 되돌릴 코드도 없음)

    CASES = "단가 무관.배치 430,000원 430.000 4,30,000 430 000"
    with COMMON.env(PARSE_TOKEN_NORM="0"):
        ts_off = tokens(CASES)
        assert ts_off == {"단가", "무관.배치", "430000원", "430.000", "430000", "430", "000"}, sorted(ts_off)
        assert "무관" not in ts_off  # (e) 끔: 아직 붙어서 거짓 누락(무관.배치 ≠ 무관)

    for norm_val in (None, "1"):  # 기본(미설정) = 켬과 명시적 "1" — 둘 다 같은 동작
        with COMMON.env(PARSE_TOKEN_NORM=norm_val):
            ts_on = tokens(CASES)
            assert ts_on == {"단가", "무관", "배치", "430000", "430.000", "4,30,000"}, (norm_val, sorted(ts_on))
            assert "무관.배치" not in ts_on and "430,000원" not in ts_on and "430" not in ts_on and "000" not in ts_on
            assert (
                "430.000" in ts_on and "4,30,000" in ts_on
            )  # 모호한 마침표·무효 쉼표 묶음은 원문 그대로(430000과 다른 토큰 — 조용히 안 합침)
            assert tokens("작성자 2026-07-13 D-2024-122 Q-77 7.8%") == {
                "작성자",
                "2026-07-13",
                "D-2024-122",
                "Q-77",
                "7.8%",
            }  # 날짜·ID·퍼센트는 안 건드림
    print("[selftest] AD25(a)(e) PARSE_TOKEN_NORM 기본 켬(미설정·'1') 통과", sorted(ts_on))

    with COMMON.env(PARSE_TOKEN_NORM="0"):  # =0만 끔 — 미설정(기본)은 이제 켬이라 되돌리려면 명시적으로 꺼야 한다
        assert tokens(CASES) == ts_off, (tokens(CASES), ts_off)  # =0이면 다시 바이트 동일
