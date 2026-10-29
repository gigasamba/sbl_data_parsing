"""pipeline.shared.text 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.shared.text`."""

from pipeline.shared.text import SYMBOL_PUA, canon_symbols, standardize_text


def test_main():  # 옛 `if __name__ == "__main__":` 몸통(인라인 점검)
    # SI20·AD25 — 기호 정규화 맵(canon_symbols) 공용화: Symbol 글꼴 PUA·대시·특수 공백·전각
    assert canon_symbols("") == "≥" and canon_symbols("") == "±"
    assert canon_symbols("B–1") == "B-1" and canon_symbols("B−1") == "B-1"  # 대시 종류 → '-'
    assert canon_symbols("a b") == "a b"  # 특수 공백 → ' '
    assert canon_symbols("5％") == "5%" and canon_symbols("ABC") == "ABC"  # 전각 % → 반각(안전한 부분집합)
    assert canon_symbols("") == ""
    print("[selftest] SI20 — 기호 정규화 맵(canon_symbols) 통과")

    # RV14 — Symbol 글꼴 그리스 문자 전체(소문자 a-z 26·대문자 24, J·V 자리 없음) + 표 칸에서 자주 보는 조합
    assert canon_symbols(chr(0xF070)) == "π" and canon_symbols(chr(0xF073)) == "σ" and canon_symbols(chr(0xF071)) == "θ"
    assert canon_symbols(chr(0xF050)) == "Π" and canon_symbols(chr(0xF047)) == "Γ" and canon_symbols(chr(0xF057)) == "Ω"
    assert canon_symbols(chr(0xF076)) == "ς" and canon_symbols(chr(0xF06A)) == "ϕ"  # 변이형(final sigma·phi1)
    assert 0xF04A not in SYMBOL_PUA and 0xF056 not in SYMBOL_PUA  # J·V 자리 — 그리스 대문자 없음(안 채움)
    assert canon_symbols(chr(0xF070) + chr(0xF073) + "95") == "πσ95"  # 표 칸 전형 — 공식 기호 + 숫자
    print("[selftest] RV14 — Symbol 글꼴 그리스 문자 전체(표 칸 기호 정규화 확장) 통과")

    # SI20·AD46⑤ — 산출 표준화(standardize_text) = 첨자 표기(마커 유지) + 기호 맵
    assert standardize_text("10×10⁶ m") == "10≥×10^6 m"
    assert standardize_text("CO<sub>2</sub> 5％") == "CO_2 5%"
    assert standardize_text("") == ""
    print("[selftest] SI20 — 산출 표준화(standardize_text) 통과")
