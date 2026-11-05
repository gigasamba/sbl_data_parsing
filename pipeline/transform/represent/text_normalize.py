"""기호·숫자 정규화(대표 결과·채점 공용) — canon_symbols·standardize_text·canon_num_key."""

import re

from common.core.text import supsub_mark

# 기호 정규화 맵 — 대표 결과 표준화와 채점이 함께 쓴다(각자 맵을 두면 또 벌어짐).
# Symbol 글꼴(PDF·Word가 사용자 영역 U+F0xx로 내보냄) → 표준 글자 — 자주 나오는 것만.
SYMBOL_PUA = {
    0xF0B3: "≥",
    0xF0A3: "≤",
    0xF0B1: "±",
    0xF0B4: "×",
    0xF0B8: "÷",
    0xF0B9: "≠",
    0xF0BB: "≈",
    0xF0B0: "°",
    0xF0B7: "•",
    0xF0AE: "→",
    0xF0AC: "←",
    0xF06D: "μ",
    0xF061: "α",
    0xF062: "β",
    0xF067: "γ",
    0xF064: "δ",
    0xF06C: "λ",
    0xF0D7: "·",
    0xF02D: "-",
}
# Symbol 글꼴 그리스 문자 전부(영문 자리값 + 0xF000 = PUA, 고정 표). 소문자 26자리 · 대문자 24자리(J·V 자리 없음).
# Wingdings 동그라미 숫자(①~⑩)가 일부 자리(L~U)와 겹치나 글자만으론 못 가르므로 더 흔한 그리스 대문자만 넣는다.
_SYMBOL_GREEK = {
    "a": "α",
    "b": "β",
    "c": "χ",
    "d": "δ",
    "e": "ε",
    "f": "φ",
    "g": "γ",
    "h": "η",
    "i": "ι",
    "j": "ϕ",
    "k": "κ",
    "l": "λ",
    "m": "μ",
    "n": "ν",
    "o": "ο",
    "p": "π",
    "q": "θ",
    "r": "ρ",
    "s": "σ",
    "t": "τ",
    "u": "υ",
    "v": "ς",
    "w": "ω",
    "x": "ξ",
    "y": "ψ",
    "z": "ζ",
    "A": "Α",
    "B": "Β",
    "C": "Χ",
    "D": "Δ",
    "E": "Ε",
    "F": "Φ",
    "G": "Γ",
    "H": "Η",
    "I": "Ι",
    "K": "Κ",
    "L": "Λ",
    "M": "Μ",
    "N": "Ν",
    "O": "Ο",
    "P": "Π",
    "Q": "Θ",
    "R": "Ρ",
    "S": "Σ",
    "T": "Τ",
    "U": "Υ",
    "W": "Ω",
    "X": "Ξ",
    "Y": "Ψ",
    "Z": "Ζ",  # J·V 없음(Symbol 폰트에 그리스 대문자 없는 자리)
}
for _k, _ch in _SYMBOL_GREEK.items():
    SYMBOL_PUA[0xF000 + ord(_k)] = _ch
del _k, _ch
DASH_CHARS = re.compile(r"[‐‑‒–—―−﹣－]")  # 대시 종류 → '-'
SPACE_CHARS = re.compile(r"[  -​  　]")  # 특수 공백 → ' '
_FULLWIDTH = {c: chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}  # 전각 영숫자·기호 → 반각(％→%도 포함) — NFKC 전체(로마 숫자 등
# 의미가 바뀌는 변환 포함)가 아니라 이 범위만(저장될 산출물엔 안전한 부분집합만)


def canon_symbols(s):
    """기호 정규화 맵 적용 — Symbol 글꼴 PUA → 표준 글자 · 대시 종류 → '-' · 특수 공백 → ' ' · 전각 → 반각(안전한 NFKC 부분집합).
    첨자 표기는 안 건드림(supsub_mark가 따로 함)."""
    if not s:
        return s
    s = "".join(SYMBOL_PUA.get(ord(c), c) for c in s)
    s = s.translate(_FULLWIDTH)
    s = DASH_CHARS.sub("-", s)
    return SPACE_CHARS.sub(" ", s)


def standardize_text(s):
    """대표 결과 본문·facts·표 칸 표준화 = 첨자 표기 통일(supsub_mark, 마커 유지) + 기호 정규화(canon_symbols)."""
    if not s:
        return s
    return canon_symbols(supsub_mark(s))


def canon_num_key(tok):
    """숫자 표기 충돌 탐지 전용(tokens()는 이 값으로 합치지 않는다 — 모호해서) — 430.000과 430,000처럼 천 단위
    구분자로 보이는 자리를 모두 지운 정규값. parse_scoring.build_token_consensus가 같은 계열 사이에서 표기가 갈리는
    숫자(conflicts)를 찾을 때만 쓴다. 3자리 묶음 모양(쉼표·마침표)이 아니면 None(충돌 비교 대상 아님 — 4,30,000은
    묶음이 무효라 여기도 안 걸린다)."""
    core = tok.rstrip(".,:/-")
    if not re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", core):
        return None
    return re.sub(r"[,.]", "", core)
