"""기호 정규화·산출 표준화(파싱 전용) — canon_symbols(Symbol 글꼴 PUA·대시·특수 공백·전각→반각)·standardize_text
(대표 결과 본문·facts·표 칸 표준화, 텍스트 파싱 직후·융합 전). score_gold.py 채점(canon())·represent.py·
postprocess/{diagram_edges,scan_dedup,table_std}.py가 공용 — 각자 맵을 두면 또 벌어짐(SI20·AD25, 서버 실측 10-06).
첨자 표기(supsub_mark)는 common.core.text 쪽(파싱·검색 공용, parse_qa·synth_score도 씀)에 그대로 둔다."""

import re

from common.core.text import supsub_mark

# SI20·AD25 — 기호 정규화 맵(산출 쪽 표준화·score_gold 채점 공용 — 각자 맵을 두면 또 벌어짐, 서버 실측 10-06).
# Symbol 글꼴(PDF·Word가 사용자 영역 U+F0xx로 내보냄) → 표준 글자 — 자주 나오는 것만(score_gold에서 옮김, 값 불변).
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
# RV14 — 위 5글자(μαβγδλ)만 있던 Symbol 글꼴 그리스 문자를 전부로(Adobe/MS Symbol 폰트 표준 배치 — 영문 자리값
# 그대로 그리스 글자를 그려 PUA(U+F0xx = 영문 자리값+0xF000)로 저장됨, 수십 년 된 고정 표). 소문자 a-z 26자리 전부
# 그리스 글자 하나씩(j·v는 변이형 phi1·final-sigma) · 대문자는 A-Z 중 24자리만(Symbol 폰트에 J·V 자리의 그리스
# 대문자가 없음 — 건너뜀, 억지로 안 채움). 표 칸 안 공식·단위 표기(α·β·π·σ·θ 등)에서 자주 나옴 — SI13/SI17 연계.
# Wingdings의 동그라미 숫자(①~⑩)는 **일부가 이 자리(L~U)와 겹침** — 같은 PUA 코드가 Symbol이면 그리스 대문자,
# Wingdings이면 동그라미 숫자로 뜻이 갈려 글자만으론 못 가른다(폰트 run 정보가 여기까지 안 내려옴) → 둘 다 못
# 넣느니 더 흔한 그리스 대문자만 넣는다. 실제 표본에서 Wingdings 동그라미 숫자가 보이면 폰트 run까지 보는
# 별도 경로가 필요(지금 범위 밖 — 독립 검토 필요 시 플래그).
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
    첨자 표기는 안 건드림(supsub_mark가 따로 함) — score_gold.canon()과 modules/parse/represent.py의 산출 표준화가 공용."""
    if not s:
        return s
    s = "".join(SYMBOL_PUA.get(ord(c), c) for c in s)
    s = s.translate(_FULLWIDTH)
    s = DASH_CHARS.sub("-", s)
    return SPACE_CHARS.sub(" ", s)


def standardize_text(s):
    """SI20·AD46⑤ — 대표 결과 본문·facts·표 칸 표준화(텍스트 파싱 직후·융합 전) = 첨자 표기 통일(supsub_mark, 마커는
    유지 — AD37과 같은 표기) + 기호 정규화 맵(canon_symbols). 원문(엔진별 output/parse/<엔진>/)은 그대로 두고 대표 결과에만 적용."""
    if not s:
        return s
    return canon_symbols(supsub_mark(s))
