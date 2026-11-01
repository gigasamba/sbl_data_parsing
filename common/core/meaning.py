"""유의미 텍스트 기준 — 정의 한 곳(파싱 정확도 교차 재현율 · 조합 정렬 ctx5m · 청크 정제가 모두 이것을 쓴다). stdlib만.

유의미(센다):
  - 수치: 숫자가 든 토큰(금액·수량·비율·날짜·ID — 12,000 · 7.8% · 2026-07-13 · LOT-2026-372 · D-2024-122)
  - 단어·문장: 한글·영문 글자로 된 2자 이상 토큰(문장은 이 토큰들의 합)
  - 머리말·꼬리말의 작업자·작성일·문서 번호 등도 위 규칙대로 센다(지우지 않음 — 중요할 수 있음, 사용자 2026-09-30)
유의미 아님(빼고 센다):
  - 구분선·장식 기호만 있는 것: ///, ---, ===, ***, ___, |, •, ▪, … (글자·숫자가 없는 토큰은 애초에 안 셈)
  - 쪽 번호: 쪽 경계(\\f 앞뒤 줄, 문서 첫·끝 줄)에 홀로 있는 "3", "- 3 -", "3 / 10", "Page 3", "p. 3 of 10", "3쪽", "3페이지"
    — 쪽 번호는 원본 위치 매핑(청크 meta.page)에만 쓰고 정제 텍스트에서는 뺀다(사용자 2026-09-30)
  - 1자 토큰(단일 숫자·글자 — 목록 번호·잡음이 대부분)

AD25(a)(e) 토큰 정규화(늘 켬 — 끄는 스위치는 op-08에 지움):
  (e) 글자(한글·영문) 사이에 낀 마침표만 분리: "무관.배치" → "무관"·"배치"(거짓 누락 제거). 숫자 쪽 마침표(7.8·430.000)·
      하이픈 자리(2026-07-13·D-2024-122·Q-77)·퍼센트는 글자 양쪽 조건이 아니라서 그대로 붙어 있다.
  (a) 숫자 정규화 한 곳: 공백·작은따옴표 천 단위(430 000·1'000)는 쉼표로 통일 → 유효 3자리 쉼표 묶음만 숫자로 합친다
      (4,30,000처럼 묶음이 무효면 조용히 같아지지 않게 그대로 둔다) · 숫자에 바로 붙은 단위 글자(430,000원)는 떼어
      단위 토큰으로. 마침표 묶음(430.000)은 천 단위·소수점 구분이 안 돼 합치지 않는다(pipeline.shared.meaning.
      canon_num_key가 충돌 탐지만).

10-14 함수별 분리(사용자) — pipeline에서만 쓰는 canon_num_key는 pipeline/shared/meaning.py로 옮김(로직
바이트 동일). tokens·chars·strip_page_numbers는 계획과 달리 여기 남긴다: tokens는 check_modules.py
CONTRACT_FUNCS(계약 함수는 common/에만 정의)에 걸리고, chars·strip_page_numbers는 pipeline/eval/stages.py(여러
이미지 공용)가 그대로 부른다 — 재검증 결과 이 셋은 "공통에서 호출" 규칙으로 못 옮긴다(engine-dev 10-14).
"""

import re

TOKEN = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9.,%/-]*")  # 콜론에서 끊음(OCR마다 띄어쓰기가 달라 붙이면 엔진 간 대조가 깨짐)
_PAGE = re.compile(
    r"^\s*(?:[-–—(\[]\s*)?(?:(?:page|p\.?|pg\.?)\s*)?\d{1,4}(?:\s*(?:/|of)\s*\d{1,4})?\s*(?:쪽|페이지|면)?(?:\s*[-–—)\]])?\s*$", re.I
)

_LETTER_DOT = re.compile(r"(?<=[가-힣A-Za-z])\.(?=[가-힣A-Za-z])")  # 글자-글자 사이 마침표만(숫자 쪽 제외)
_SPACE_GROUPED = re.compile(
    r"(?<![\d,.'])\d{1,3}(?:[ ']\d{3})+(?![\d,.'])"
)  # 공백·작은따옴표 3자리 묶음(앞뒤가 숫자·구분자가 아닐 때만 — 다른 숫자 묶음과 안 번짐)
_VALID_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+$")  # 쉼표 묶음이 3자리씩 유효한지(4,30,000은 무효)
_NUM_UNIT = re.compile(r"^(\d[\d,.']*\d|\d)([가-힣A-Za-z]+)$")  # 숫자 바로 뒤 단위 글자


def is_page_number(line):
    return bool(line.strip()) and bool(_PAGE.match(line))


def strip_page_numbers(text):
    """쪽 경계(\\f 앞뒤, 문서 첫·끝)에 홀로 있는 쪽 번호 줄을 지운다 — 표 안의 단독 숫자 줄은 경계가 아니면 그대로."""
    out = []
    for page in (text or "").split("\f"):
        lines = page.split("\n")
        idx = [i for i, ln in enumerate(lines) if ln.strip()]
        edge = set(idx[:2] + idx[-2:])  # 쪽 첫 2줄·끝 2줄(머리말·꼬리말 자리)
        out.append("\n".join(ln for i, ln in enumerate(lines) if not (i in edge and is_page_number(ln))))
    return "\f".join(out)


def _join_space_groups(text):
    """AD25(a) — 공백·작은따옴표 천 단위 구분자를 쉼표로 통일(정규식 구조 자체가 유효 3자리 묶음만 잡는다)."""
    return _SPACE_GROUPED.sub(lambda m: re.sub(r"[ ']", ",", m.group(0)), text)


def _split_letter_dots(tok):
    """AD25(e) — 글자 사이 마침표에서 토큰을 쪼갠다("무관.배치" → ["무관", "배치"])."""
    return [p for p in _LETTER_DOT.split(tok) if p]


def _norm_number(tok):
    """AD25(a) 숫자 정규화 한 곳 — 유효 3자리 쉼표 묶음만 합치고, 붙은 단위 글자를 뗀다.
    마침표 묶음(430.000류)은 천 단위·소수점 구분이 모호해 원문 그대로 둔다(조용히 합치지 않음 — canon_num_key가 충돌만 잡는다)."""
    m = _NUM_UNIT.match(tok)
    num, unit = (m.group(1), m.group(2)) if m else (tok, None)
    if _VALID_GROUPED.match(num):
        num = num.replace(",", "")
    return [num, unit] if unit else [num]


def tokens(text):
    """유의미 토큰 집합(쉼표 제거·쪽 번호 제외) + 모듈 docstring의 AD25(a)(e) 규칙."""
    body = _join_space_groups(strip_page_numbers(text))
    out = set()
    for raw in TOKEN.findall(body):
        for piece in _split_letter_dots(raw):
            t = piece.rstrip(".,:/-")
            if len(t) < 2:
                continue
            for sub in _norm_number(t):
                sub = sub.rstrip(".,:/-") if sub else sub
                if sub and len(sub) >= 2:
                    out.add(sub)
    return out


def chars(texts):
    """유의미 글자 수 — 여러 단위에 겹친 줄은 한 번, 쪽 번호 줄 제외, 한글·영문·숫자만 센다."""
    seen, n = set(), 0
    for t in texts:
        for ln in strip_page_numbers(t or "").splitlines():
            k = ln.strip()
            if k and k not in seen:
                seen.add(k)
                n += sum(1 for c in k if c.isalnum())
    return n
