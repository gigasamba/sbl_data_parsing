"""문서 최신성 메타데이터(백로그 L3-1·W15) — 날짜·개정·구판 표시·문서군(family)을 뽑는 규칙 한 곳.
structure(modules/structure/build_bundle.py)가 docs.jsonl에 적고, search(modules/search/retriever.py)가 그 필드로 순위를 조정한다 — 둘이 같은 규칙.

날짜 우선순위는 **본문 먼저, 파일명은 다음**(파일명이 내용과 다를 수 있음 — holdout 실측: final_real.docx(본문 2025-06) vs
final_v2.docx(본문 2025-09), 파일명에는 날짜가 아예 없어 속지는 않지만 버전 낱말도 내용이 아니라 이름이 우선이면 거꾸로 판단할 수 있음)."""

import re
from pathlib import Path

from common.core.terms import load_id_patterns  # id_patterns.csv(L4-7, family가 계약 번호 등을 과병합하지 않게)

SUPERSEDED_MARKERS = ("[구판]", "구판", "폐기", "이전 판")  # 본문 첫 300자에서(한글) — 영문은 아래 정규식
RE_SUPERSEDED_EN = re.compile(r"\bsuperseded\b|\bobsolete\b", re.I)

RE_LATEST_QUESTION = re.compile(r"최신|현재|최근|latest|current|most recent|newest", re.I)
RE_VERSION_PIN = re.compile(r"\b(?:rev(?:ision)?|version|ver|amendment|개정판?|수정판?)\.?\s*([0-9]+(?:\.[0-9]+)?)", re.I)
RE_YEAR = re.compile(r"(20\d{2})")
# 연도 지목 닻말 — 연도 바로 뒤가 아니라 질문 어디든("2024년 단가표 기준") 있으면 됨(실제 family 멤버 날짜와 또 맞아야 지목 확정 — pin_from_question)
RE_PIN_ANCHOR = re.compile(r"기준|현재|시점|당시|as of|as at", re.I)
# 연도 + 문서 명사("2025년 목록에서"·"2024년 판의"·"2025 price list") — 닻말 없이도 특정 연도 판 지목(10-05 dev revisions-dev RD009)
RE_YEAR_DOC = re.compile(r"(20\d{2})\s*년?\s*(?:판|버전|목록|리스트|자료|문서|표|단가표|가격표|edition|version|list|price list)", re.I)

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

_VER_WORD = r"(?:rev(?:ision)?|version|ver|amendment|개정판?|수정판?)"
_SEP = r"[.\s_-]*"  # 키워드·숫자 사이 구분자(파일명은 보통 밑줄·하이픈, 본문은 점·공백) — 0개도 허용(Version2026 류)
_RE_VER_KW = re.compile(
    rf"(?<![A-Za-z]){_VER_WORD}{_SEP}([0-9]+(?:\.[0-9]+)?)", re.I
)  # 앞이 글자면 안 침(forever2026 오탐 방지) — 밑줄·숫자·문자열 시작은 허용
_RE_VER_V = re.compile(r"(?<![A-Za-z0-9])v[.\s_-]?([0-9]+(?:\.[0-9]+)?)\b", re.I)

# family 키에서 지울 토큰 — 날짜/연도, 개정·버전, 복사본 표시("_old"·"(1)") — 이 밖의 임의 낱말("_real"·"_final")은 안 지움(과잉 병합 방지, ponytail)
_FAMILY_DROP = re.compile(
    rf"(?<![A-Za-z]){_VER_WORD}{_SEP}\d+(?:\.\d+)?"
    r"|(?<![A-Za-z0-9])v[.\s_-]?\d+(?:\.\d+)?"
    r"|20\d{2}[-_. ]?\d{0,2}[-_. ]?\d{0,2}"
    r"|_old\b|-old\b|\(\d+\)",
    re.I,
)


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


def _date_in(s):
    """가장 구체적인 패턴부터 — 문자열 안 어디든 먼저 맞는 것(연도만 있는 것보다 전체 날짜를 우선)."""
    if not s:
        return None
    for rx, fn in _DATE_PATTERNS:
        m = rx.search(s)
        if m:
            r = fn(m)
            if r:
                return r
    return None


def extract_date(filename, text):
    """문서 날짜(ISO YYYY-MM-DD·YYYY-MM·YYYY) — **본문 먼저, 파일명은 본문에 없을 때만**(파일명은 내용과 다를 수 있음)."""
    return _date_in((text or "")[:2000]) or _date_in(filename or "")


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


def _id_pattern_spans(stem):
    """id_patterns.csv(GLOSSARY_DIR)에 맞는 구간(대소문자 무시, 겹치면 병합) — 계약 번호처럼 연도·숫자가 ID의 일부인 곳을
    찾아 family_key의 날짜·개정 제거에서 뺀다(L4-7). 사전 없으면 빈 목록(오늘 동작 그대로)."""
    spans = sorted(m.span() for pat in load_id_patterns() for m in pat.finditer(stem))
    if not spans:
        return []
    merged = [spans[0]]
    for s, e in spans[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def family_key(filename):
    """문서군 키 — 파일명 stem을 소문자화하고 날짜·개정·버전·복사본 토큰만 지움(그 밖의 낱말은 그대로 — 과잉 병합 방지).
    단 그 토큰이 id_patterns.csv ID 모양(계약 번호 등)의 일부면 지우지 않는다 — 같은 ID의 다른 연도는 다른 문서(L4-7,
    4clients C-PFE-2022-01 vs C-PFE-2024-03 과병합 수정)."""
    stem = Path(filename or "").stem
    spans = _id_pattern_spans(stem)
    low = stem.lower()
    if spans:
        parts, last = [], 0
        for s, e in spans:
            parts.append(_FAMILY_DROP.sub(" ", low[last:s]))
            parts.append(low[s:e])
            last = e
        parts.append(_FAMILY_DROP.sub(" ", low[last:]))
        low = "".join(parts)
    else:
        low = _FAMILY_DROP.sub(" ", low)
    low = re.sub(r"[\s_\-.]+", "_", low).strip("_")
    return low or Path(filename or "").stem.lower()


def doc_meta(filename, text):
    """structure(build_bundle.py)가 docs.jsonl에 적는 한 벌 — doc_date·version·superseded·family."""
    return {
        "doc_date": extract_date(filename, text),
        "version": extract_version(filename, text),
        "superseded": is_superseded(text),
        "family": family_key(filename),
    }


def pin_from_question(question):
    """질문이 특정 개정·연도를 콕 집었나("Rev.1 기준"·"2024년 단가표 기준") — 있으면 그 버전은 최신성 순위에서 밀지 않는다(holdout W15 — MTOP 실측).
    연도는 "기준" 류 닻말이 질문 어디든 있어야(그래야 "2025년에 체결" 같은 평서문을 지목으로 안 봄) — 실제로 그 연도인 family 멤버가 있어야 최종 확정(recency_rerank)."""
    if not question:
        return None, None
    mv = RE_VERSION_PIN.search(question)
    my = (RE_YEAR.search(question) if RE_PIN_ANCHOR.search(question) else None) or RE_YEAR_DOC.search(question)
    return (mv.group(1) if mv else None), (my.group(1) if my else None)


def _recency_key(meta):
    """정렬 키 — 구판 아님 > 날짜 최신 > 개정 번호 큼(튜플 자체가 최댓값 비교에 바로 씀)."""
    ver = meta.get("version")
    try:
        vnum = float(ver) if ver not in (None, "") else -1.0
    except (TypeError, ValueError):
        vnum = -1.0
    return (not meta.get("superseded"), meta.get("doc_date") or "", vnum)


def recency_rerank(hits, doc_of, question=None, mode=None):
    """같은 family(결과 안 ≥2건) 묶음 → 최신(doc_date·version·superseded)만 원래 자리에 두고 옛 것은 뒤로 — **지우지 않는다**
    (holdout 실측: 개정 3이 지불조건만 바꾸고 MTOP 값은 개정 2에만 있음 — 지우면 그 값을 영영 못 찾음).
    질문이 특정 개정·연도를 콕 집으면(pin_from_question) 그 버전도 밀지 않는다. 끄기: SEARCH_RECENCY=0.
    mode 인자가 오면 그 질의 1건에만 그 모드를 쓴다(전역 env는 그대로 — AG1 engine-qa 보완, 동시 요청 사이 데이터 경쟁 방지).
    인자가 없으면(None) env(SEARCH_RECENCY, 기본 "1")를 본다.
    hits: [{"doc_key": ...}, ...] · doc_of: {doc_key: {doc_date, version, superseded, family}} → (새 hits, notes 메모|None)."""
    from common.config.settings import cfg  # S7b — 설정 객체(옛 `get("SEARCH_RECENCY", "1")` — 빈 글자 유지)

    mode = cfg().text.search_recency if mode is None else str(mode)  # 0 끔 · 1 최신을 묻는 질문에서만(기본) · 2 늘
    if mode == "0" or not hits:
        return hits, None
    # 10-05 dev 실측: 늘 적용하면 4clients R@1 0.78→0.51 — family가 파일명에서 연도를 빼 같은 고객의 연도별 '다른 계약'(C-PFE-2022-01·2024-03)을
    # 한 문서의 판으로 묶어 옛 계약을 밀었음. 최신을 묻는 질문에서만 순위를 바꾸고, 나머지는 날짜·판 표시(답변 프롬프트)로만 가리게.
    if mode == "1" and not (question and RE_LATEST_QUESTION.search(question)):
        return hits, None
    fam = {}
    for h in hits:
        m = doc_of.get(h.get("doc_key"))
        if m and m.get("family"):
            fam.setdefault(m["family"], set()).add(h["doc_key"])
    multi = {f: dks for f, dks in fam.items() if len(dks) >= 2}
    if not multi:
        return hits, None
    # 최신 '열쇠값'만 비교 — 확실히 더 오래된(열쇠가 엄격히 작은) 것만 뒤로. 동률(날짜·개정 둘 다 없는 같은 이름 사본 등)은 안 건드림
    # (10-05 결함: set에서 max로 '최신 1건'을 골라 동률이면 실행마다 다른 문서가 뽑히고, 근거 없이 나머지를 뒤로 밀었음 — 비결정·오강등)
    newest = {f: max(_recency_key(doc_of[dk]) for dk in dks) for f, dks in multi.items()}
    pin_v, pin_y = pin_from_question(question)
    pinned = set()
    if pin_v or pin_y:
        for dks in multi.values():
            for dk in dks:
                m = doc_of[dk]
                if (pin_v and m.get("version") == pin_v) or (pin_y and (m.get("doc_date") or "").startswith(pin_y)):
                    pinned.add(dk)
    kept, demoted = [], []
    for h in hits:
        dk = h.get("doc_key")
        f = (doc_of.get(dk) or {}).get("family")
        if f in multi and dk not in pinned and _recency_key(doc_of[dk]) < newest[f]:
            demoted.append(h)
        else:
            kept.append(h)
    if not demoted:
        return hits, None
    # L4-8 — 옛 판은 맨 뒤가 아니라 '같은 family에서 남은 문서 바로 뒤'로(최신 개정에 없는 항목은 옛 판에만
    # 있음 — 근거 k 안에 남게). BR33: 삽입 지점은 family의 첫 kept occurrence가 아니라 **그 문서(doc_key)의
    # 마지막 occurrence** 뒤 — 같은 문서가 여러 청크로 갈려 kept에 흩어져 있을 때(실측 QA095: 최신판 청크가
    # 여러 개, 그중 가장 먼저 나온 청크가 하필 질문과 약하게만 맞음) 첫 청크 뒤에 바로 끼우면 옛 판 청크들이
    # 그 문서의 '더 적합한(뒤에 나온)' 청크보다 위로 올라가 버렸다(최신판 MTOP 값 청크가 구판 청크들 뒤로 밀려
    # 순위 밖). 같은 family에서 다른 문서가 섞여 있으면(예: 특정 개정 지목 — pin_from_question) 그 경계는
    # 그대로 지킨다(옛 판을 앞선 문서 occurrence 뒤에 바로 붙임, 뒤에 나오는 다른 kept 문서를 건너뛰지 않음).
    fam_of = lambda h: (doc_of.get(h.get("doc_key")) or {}).get("family")
    anchor_doc, last_idx = {}, {}  # family -> (앵커 문서 doc_key, 그 문서의 kept 안 마지막 위치)
    for i, h in enumerate(kept):
        f = fam_of(h)
        if not f:
            continue
        dk = h.get("doc_key")
        anchor_doc.setdefault(f, dk)
        if dk == anchor_doc[f]:
            last_idx[f] = i
    by_fam = {}
    for h in demoted:
        by_fam.setdefault(fam_of(h), []).append(h)
    order = []
    for i, h in enumerate(kept):
        order.append(h)
        f = fam_of(h)
        if f in by_fam and last_idx.get(f) == i:
            order += by_fam.pop(f)
    order += [h for hs in by_fam.values() for h in hs]  # (이론상 없음) 남은 것은 뒤로
    out = [{**h, "rank": i + 1} for i, h in enumerate(order)]
    label = "최신 질문 — " if (question and RE_LATEST_QUESTION.search(question)) else ""
    note = f"{label}구판 {len(demoted)}건 뒤로" + ("(지정 버전 유지)" if pinned else "")
    return out, note


_COPY_POOL_RE = re.compile(r"^synth-[\w-]+__[\w-]+__", re.I)  # 평가 풀 접두(같은 원본의 재명명 사본, synth-distractors-v2 등)
_COPY_FMT_RE = re.compile(
    r"^(mailshot|screenshot|scan)_", re.I
)  # 형식 접두(메일 캡처·스캔 사본) — 실 코퍼스 실측(MAIL-MRH-02.eml/.msg/mailshot_MAIL-MRH-02.png)


def copy_key(filename):
    """R2-c 요건① 사본 그룹 규칙(engine-qa CONCERN 반영, 문서화) — 1차 후보 키는 평가 풀 접두·형식 접두를 뗀
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
    """R2-c 요건① — items: [{"file_name", "text"}, ...](do_search 근거 순서, 보통 수십 건 이하) →
    {대표 인덱스: [사본 인덱스, ...]}. 같은 copy_key 후보 안에서만 본문 정규화 완전 일치 또는 5-gram
    Jaccard ≥ text_sim(실 코퍼스 실측: 같은 메일의 .eml/.msg/mailshot 0.6~0.72, 다른 계약서 0.02~0.43)이면
    사본으로 묶는다. 대표 = 그룹 안에서 원래 순서(검색 순위)가 가장 앞선 항목 — **지우지 않는다**(RV11 회귀:
    "점수 가장 높은 사본만 남김"은 gold가 특정 사본을 지목하면 오히려 miss가 됐다 — 호출자가 variants로 보존)."""
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
    """engine-qa CONCERN(QA066) 반영 — 사본 그룹 안에서 **근거 텍스트로 쓸 대표**를 고른다(슬롯 자리는 그대로
    최상위 순위 — copy_groups의 대표 인덱스 선택과 무관, do_search가 그 자리의 내용만 바꿔 끼운다).
    QA066 결함: 최상위 순위가 하필 mailshot(이미지 OCR) 청크라, eml·msg에만 온전히 있던 배치 수 문장이
    대표 텍스트에서 빠졌다. 그래서 순위가 아니라 **형식 우선순위**(eml > msg > htm/mht > docx/pdf류 > 이미지,
    본문 텍스트가 원래부터 있는 형식일수록 위) → 동일 형식이면 **본문이 더 긴 쪽**으로 고른다.
    members: [{"file_name", "text"}, ...](그룹 원소, 순서 임의) → members 안 인덱스(동점이면 먼저 나온 원소)."""
    return max(range(len(members)), key=lambda i: (_format_tier(members[i].get("file_name")), len(members[i].get("text") or ""), -i))
