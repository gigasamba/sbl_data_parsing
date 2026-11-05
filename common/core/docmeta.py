"""문서 최신성 메타데이터 — 날짜·개정·구판 표시를 뽑는 규칙 한 곳 + 같은 사건 사본 묶기(copy_key·copy_groups).
structure(gold_bundle.py)가 docs.jsonl에 적고, 검색 근거가 그 칸(doc_date·version·superseded)을 그대로 보여 준다.
판 묶음·최신성 순위는 없다 — 같은 문서의 다른 판이 '최신' 질문에서 위로 올 수 있는 문제는 PRD pl-38.

날짜 우선순위는 **본문 먼저, 파일명은 다음**(파일명이 내용과 다를 수 있음 — 예: final_real.docx(본문 2025-06) vs
final_v2.docx(본문 2025-09)는 이름의 버전 낱말을 우선하면 거꾸로 판단한다)."""

import re
from pathlib import Path

SUPERSEDED_MARKERS = ("[구판]", "구판", "폐기", "이전 판")  # 본문 첫 300자에서(한글) — 영문은 아래 정규식
RE_SUPERSEDED_EN = re.compile(r"\bsuperseded\b|\bobsolete\b", re.I)

RE_LATEST_QUESTION = re.compile(r"최신|현재|최근|latest|current|most recent|newest", re.I)

_MONTHS = {n: i + 1 for i, n in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"

_RE_YMD = re.compile(r"(20\d{2})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)")
_RE_KO_YMD = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_RE_DMY_EN = re.compile(rf"\b(\d{{1,2}})\s+({_MON_RE})\.?,?\s+(20\d{{2}})\b", re.I)
_RE_MDY_EN = re.compile(rf"\b({_MON_RE})\.?\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I)
_RE_YM = re.compile(r"(20\d{2})[-_./](\d{1,2})(?!\d)")
_RE_KO_YM = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월")
_RE_MY_EN = re.compile(rf"\b({_MON_RE})\.?\s+(20\d{{2}})\b", re.I)
_RE_Y = re.compile(r"(20\d{2})(?!\d)")
# 본문의 연도만은 "2026년"처럼 날짜로 적은 것만(본문 속 맨 연도 "planned for 2027"은 문서 날짜가 아님)
_RE_KO_Y = re.compile(r"(20\d{2})\s*년")

_VER_WORD = r"(?:rev(?:ision)?|version|ver|amendment|개정판?|수정판?)"
_SEP = r"[.\s_-]*"  # 키워드·숫자 사이 구분자(파일명은 보통 밑줄·하이픈, 본문은 점·공백) — 0개도 허용(Version2026 류)
_RE_VER_KW = re.compile(
    rf"(?<![A-Za-z]){_VER_WORD}{_SEP}([0-9]+(?:\.[0-9]+)?)", re.I
)  # 앞이 글자면 안 침(forever2026 오탐 방지) — 밑줄·숫자·문자열 시작은 허용
_RE_VER_V = re.compile(r"(?<![A-Za-z0-9])v[.\s_-]?([0-9]+(?:\.[0-9]+)?)\b", re.I)


def _mon(s):
    return _MONTHS.get((s or "")[:3].lower())


def _fmt(y, m=None, d=None):
    y = int(y)
    if m is None:
        return f"{y:04d}"
    m = int(m)
    if not 1 <= m <= 12:
        return None
    if d is None:
        return f"{y:04d}-{m:02d}"
    d = int(d)
    if not 1 <= d <= 31:
        return f"{y:04d}-{m:02d}"
    return f"{y:04d}-{m:02d}-{d:02d}"


_DATE_PATTERNS = (
    (_RE_YMD, lambda m: _fmt(m[1], m[2], m[3])),
    (_RE_KO_YMD, lambda m: _fmt(m[1], m[2], m[3])),
    (_RE_DMY_EN, lambda m: _fmt(m[3], _mon(m[2]), m[1])),
    (_RE_MDY_EN, lambda m: _fmt(m[3], _mon(m[1]), m[2])),
    (_RE_YM, lambda m: _fmt(m[1], m[2])),
    (_RE_KO_YM, lambda m: _fmt(m[1], m[2])),
    (_RE_MY_EN, lambda m: _fmt(m[2], _mon(m[1]))),
    (_RE_Y, lambda m: _fmt(m[1])),
)


def _date_in(s, bare_year=True):
    """가장 구체적인 패턴부터 — 문자열 안 어디든 먼저 맞는 것(연도만 있는 것보다 전체 날짜를 우선).
    bare_year=False(본문)면 맨 연도(_RE_Y) 대신 "2026년" 꼴만 연도로 본다 — 본문의 맨 연도는 계획·이력 글이 많아 문서 날짜가 아님."""
    if not s:
        return None
    pats = _DATE_PATTERNS if bare_year else (*_DATE_PATTERNS[:-1], (_RE_KO_Y, lambda m: _fmt(m[1])))
    for rx, fn in pats:
        m = rx.search(s)
        if m:
            r = fn(m)
            if r:
                return r
    return None


def extract_date(filename, text):
    """문서 날짜(ISO YYYY-MM-DD·YYYY-MM·YYYY) — **본문 먼저, 파일명은 본문에 없을 때만**(파일명은 내용과 다를 수 있음)."""
    return _date_in((text or "")[:2000], bare_year=False) or _date_in(filename or "")


def extract_version(filename, text):
    """개정·버전 번호(그대로 "2"·"1.2") — rev/revision/개정/ver/version/amendment/v 다음 숫자. 본문 먼저, 파일명은 다음."""
    for s in ((text or "")[:2000], filename or ""):
        m = _RE_VER_KW.search(s) or _RE_VER_V.search(s)
        if m:
            return m.group(1)
    return None


def is_superseded(text):
    """구판 표시 — 본문 첫 300자에 한글 표지어 또는 superseded/obsolete."""
    head = (text or "")[:300]
    return any(mk in head for mk in SUPERSEDED_MARKERS) or bool(RE_SUPERSEDED_EN.search(head))


def doc_meta(filename, text):
    """structure(gold_bundle.py)가 docs.jsonl에 적는 한 벌 — doc_date·version·superseded."""
    return {
        "doc_date": extract_date(filename, text),
        "version": extract_version(filename, text),
        "superseded": is_superseded(text),
    }


_COPY_POOL_RE = re.compile(r"^synth-[\w-]+__[\w-]+__", re.I)  # 평가 풀 접두(같은 원본의 재명명 사본, synth-distractors-v2 등)
_COPY_FMT_RE = re.compile(
    r"^(mailshot|screenshot|scan)_", re.I
)  # 형식 접두(메일 캡처·스캔 사본) — 실 코퍼스 실측(MAIL-MRH-02.eml/.msg/mailshot_MAIL-MRH-02.png)


def copy_key(filename):
    """사본 그룹 규칙 — 1차 후보 키는 평가 풀 접두·형식 접두를 뗀
    소문자 파일명 stem. **규칙과 의도**: 같은 copy_key 후보 안에서만(그래야 전혀 다른 문서가 섞이지 않음) 본문
    5-gram Jaccard ≥ 0.6(copy_groups)이어야 비로소 "같은 사건의 사본"으로 묶는다 — 이름만 비슷해도 내용이
    다르면(예: 같은 양식의 다른 계약서) 안 묶고, 확장자·접두가 달라도(.eml/.msg/mailshot_*.png 등) 내용이
    같으면 묶는다. 1차 키는 비교 후보만 좁히는 용도(과잉 비교 방지), 최종 판정은 항상 내용(Jaccard)."""
    stem = Path(filename or "").stem.lower()
    stem = _COPY_POOL_RE.sub("", stem)
    stem = _COPY_FMT_RE.sub("", stem)
    return stem


def _copy_shingles(t, k=5):
    t = re.sub(r"\s+", "", (t or "").lower())
    return {t[i : i + k] for i in range(max(len(t) - k + 1, 0))}


def copy_groups(items, text_sim=0.6):
    """items: [{"file_name", "text"}, ...](do_search 근거 순서, 보통 수십 건 이하) →
    {대표 인덱스: [사본 인덱스, ...]}. 같은 copy_key 후보 안에서만 본문 정규화 완전 일치 또는 5-gram
    Jaccard ≥ text_sim(실 코퍼스 실측: 같은 메일의 .eml/.msg/mailshot 0.6~0.72, 다른 계약서 0.02~0.43)이면
    사본으로 묶는다. 대표 = 그룹 안에서 원래 순서(검색 순위)가 가장 앞선 항목 — **지우지 않는다**(
    "점수 가장 높은 사본만 남김"은 gold가 특정 사본을 지목하면 miss가 된다 — 호출자가 variants로 보존)."""
    cand = {}
    for idx, it in enumerate(items):
        cand.setdefault(copy_key(it.get("file_name")), []).append(idx)
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)  # 작은 인덱스(원래 순위 앞선 쪽)가 항상 대표

    for idxs in cand.values():
        if len(idxs) < 2:
            continue
        norm = {i: re.sub(r"\s+", "", (items[i].get("text") or "").lower()) for i in idxs}
        sh = {i: _copy_shingles(items[i].get("text")) for i in idxs}
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if norm[i] and norm[i] == norm[j]:
                    union(i, j)
                    continue
                A, B = sh[i], sh[j]
                if A and B and len(A & B) / len(A | B) >= text_sim:
                    union(i, j)
    groups = {}
    for idx in range(len(items)):
        r = find(idx)
        if r != idx:
            groups.setdefault(r, []).append(idx)
    return groups


_FORMAT_TIERS = (
    ({"eml"}, 5),
    ({"msg"}, 4),
    ({"htm", "mht", "html"}, 3),
    ({"docx", "doc", "pdf", "xlsx", "xls", "pptx", "ppt", "csv", "txt"}, 2),
    ({"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif"}, 1),
)  # 숫자가 클수록 본문이 더 믿을만한 형식(원문 텍스트 > 변환 문서 > OCR 이미지)


def _format_tier(filename):
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return next((t for exts, t in _FORMAT_TIERS if ext in exts), 0)


def copy_representative(members):
    """사본 그룹 안에서 **근거 텍스트로 쓸 대표**를 고른다(슬롯 자리는 그대로
    최상위 순위 — copy_groups의 대표 인덱스 선택과 무관, do_search가 그 자리의 내용만 바꿔 끼운다).
    최상위 순위가 이미지 OCR(mailshot) 청크면 eml·msg에만 온전히 있는 문장이
    대표 텍스트에서 빠진다. 그래서 순위가 아니라 **형식 우선순위**(eml > msg > htm/mht > docx/pdf류 > 이미지,
    본문 텍스트가 원래부터 있는 형식일수록 위) → 동일 형식이면 **본문이 더 긴 쪽**으로 고른다.
    members: [{"file_name", "text"}, ...](그룹 원소, 순서 임의) → members 안 인덱스(동점이면 먼저 나온 원소)."""
    return max(range(len(members)), key=lambda i: (_format_tier(members[i].get("file_name")), len(members[i].get("text") or ""), -i))
