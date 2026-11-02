#!/usr/bin/env python3
"""파싱 채점(1-QA, eval-design.md §3-1·§3-2·§6) → output/parse/qa.json · route.json

정답 우선순위(문서별): truth(개발 PC 가상 문서) → answer_key(서버 사람 정답지, 값만)
→ native(그 형식의 원본 구조 파서 출력 — 그 문서 비교에서는 제외) → consensus(인식 계열 3개+ 합의 수치, 참고)
→ none. 어떤 정답이 있느냐에 따라 계산되는 지표가 다르다(§6): 텍스트 있으면 cer·order·diff,
값 있으면 value_recall·num_halluc, truth 표 있으면 table_row_recall·table_cell_recall(엔진 자신의
tables[].grid — 행×열, 선택 칸 — 가 있으면 본문 줄과 함께 그 행도 재현 판정에 씀, C3).
합격선은 paths.CRITERIA_FILE(resources/config/criteria.json — S2)을 읽어서 판정한다(문턱값을 코드에 박지 않는다).

사용: python modules/parse/parse_qa.py [--parse output/parse] [--src <원본 문서 폴더>]   (--src 생략 시 DOC_DIR env 필수)
      [--truth output/corpus/truth.json] [--answer-key answer_key] [--out output/parse]
"""

import argparse
import bisect
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, CRITERIA_FILE, doc_dir  # 폴더 재편 뒤 이 두 상수만 바뀌면 됨
from common.core.text import supsub_mark  # W6: norm()이 score_gold.canon()과 같은 첨자 정규화를 쓰게(AD37·SI17, 각자 맵 금지)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.extract.engines import registry
from pipeline.shared.summarize import FAMILY, nums  # 계열 합의 로직 재사용(중복 금지)
from pipeline.transform.represent.repfmt import (
    doc_accuracy,  # AG11 2단계 착수 조건(10-08), 10-14 함수별 분리로 pipeline/transform/represent/repfmt.py로
)

try:
    from rapidfuzz.distance import Levenshtein as _RFLev

    _lev = _RFLev.distance
except ImportError:
    import difflib

    # ponytail: rapidfuzz 없을 때 폴백 — difflib 정렬의 편집 비용(최소 거리의 상한, 근사).
    # 진짜 O(n·m) DP는 CER_CAP(20만 자)에서 4*10^10회라 불가능 — difflib는 실측 수십만 자도 수 초.
    def _lev(a, b):  # type: ignore[misc]  # rapidfuzz 없을 때 같은 이름의 대체 함수(서명만 다름)
        return sum(
            max(i2 - i1, j2 - j1)
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if tag != "equal"
        )


try:
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz import process as _process

    HAS_RAPIDFUZZ = True

    def _best(rl, out_lines):  # 기준 줄과 가장 비슷한 출력 줄 (텍스트, 점수, 위치)
        m = _process.extractOne(rl, out_lines, scorer=_fuzz.ratio) if out_lines else None
        return m if m else (None, 0.0, None)
except ImportError:
    import difflib

    HAS_RAPIDFUZZ = False  # SI1: 줄 전수 비교(difflib 대체)는 큰 문서에서 멈춘 것처럼 보임 — 호출 쪽(score_engine)에서 생략

    def _best(rl, out_lines):
        best = (None, -1.0, None)
        for i, ol in enumerate(out_lines):
            s = difflib.SequenceMatcher(None, rl, ol).ratio() * 100
            best = (ol, s, i) if s > best[1] else best
        return best


CER_CAP = 200_000
SHEET = {".xlsx", ".xls", ".xlsm"}
IMG = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
_ZW = re.compile(r"[​‌‍﻿]")
_WS = re.compile(r"\s+")
_KO = re.compile(r"[가-힣]")
# 형식 → 그 형식의 "원본 구조 파서" 후보(우선순위 순). 목록에 없는 native 형식(.eml 등)은 registry에 등록된 엔진으로.
NATIVE = {
    ".docx": ["office_stdlib", "office"],
    ".doc": ["office_stdlib", "office"],
    ".xlsx": ["office"],
    ".xlsm": ["office"],
    ".xls": [],  # calamine(0.2.0 지움 — pl-46): 지정 파서 없음 → 계열 합의(전과 같은 결과 — calamine은 돈 적이 없음)
    ".txt": ["plaintext"],
    ".mht": ["mhtml"],
    ".mhtml": ["mhtml"],
    ".html": ["markitdown"],
    ".htm": ["markitdown"],
    ".pptx": [],  # pptx(python_pptx, 0.2.0 지움) — 위와 같음
}


def norm(s):
    """W6 — NFKC 전에 supsub_mark(plain=True)로 <sup>·<sub>·위/아래첨자 숫자를 내용만 남긴다(score_gold.canon()과
    같은 순서) — 안 그러면 NFKC가 10⁵를 105로, CO₂를 CO2로 접어 버려 ^·_ 표기 쪽(엔진이 안 바꾼 원문)과 안 맞는다."""
    s = unicodedata.normalize("NFKC", supsub_mark(s or "", plain=True))
    return _WS.sub(" ", _ZW.sub("", s).lower()).strip()


def norm_nows(s):
    return re.sub(r"\s+", "", norm(s))


def clean_commas(s):
    return re.sub(r"(?<=\d),(?=\d)", "", s)


def out_nums(text):
    """summarize.nums()를 텍스트 문자열에도 그대로 재사용(같은 dict 모양으로 감싸서 — regex 중복 정의 안 함)."""
    return nums({"text": text or ""})


_CONTENT = re.compile(r"[^0-9a-z가-힣]")


def cer(ref_text, out_text):
    """글자·숫자만 비교(표 구분 기호 |·탭·--- 는 파서마다 달라 제외), 1.0 상한 — 원문 덤프처럼 길게 부푼 출력도 1."""
    r, o = _CONTENT.sub("", norm(ref_text)), _CONTENT.sub("", norm(out_text))
    capped = len(r) > CER_CAP or len(o) > CER_CAP
    if capped:
        r, o = r[:CER_CAP], o[:CER_CAP]
    return (min(1.0, _lev(r, o) / len(r)) if r else 0.0), capped


def _lis(seq):
    tails = []
    for x in seq:
        i = bisect.bisect_left(tails, x)
        tails[i : i + 1] = [x]
    return len(tails)


def order_diff(ref_text, out_text):
    """P4 읽기 순서 + 차이 예시(최대 5개, 기준 줄 ≥8자 중 최고 유사도 <90)."""
    ref_lines = [norm(ln) for ln in ref_text.splitlines() if len(norm(ln)) >= 8]
    out_lines = [norm(ln) for ln in out_text.splitlines() if norm(ln)]
    if not ref_lines:
        return None, []
    idxs, diff = [], []
    for rl in ref_lines:
        ol, score, idx = _best(rl, out_lines)
        if score >= 90:
            idxs.append(idx)
        elif len(diff) < 5:
            diff.append([rl, ol])
    found = len(idxs)
    return (_lis(idxs) / found if found else 0.0), diff


def _key(v):
    """정답 값 하나 → 비교용 정규화 키(쉼표 제거·공백 제거)."""
    return clean_commas(norm_nows(str(v.get("value") if isinstance(v, dict) else v)))


_MON = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})((?:\d{2}:\d{2}(?::\d{2})?)?)$")


def _key_hit(k, out_nows_cleaned):
    """C2 — 정답 키가 출력에 있는지. 정답이 ISO 날짜(2026-03-15[ 14:30])면 메일 머리글의 RFC 2822 표기
    ('Sun, 15 Mar 2026 14:30' → 정규화 '...15mar202614:30')도 같은 값으로 인정(출력 원문은 안 바꿈, 요일·시간대 무시 · 출력 쪽 초는 무시하나 정답에 초가 있으면 출력에도 있어야 함)."""
    if not k:
        return False
    if k in out_nows_cleaned:
        return True
    m = _ISO_DATE.fullmatch(k)
    if not m or not 1 <= int(m.group(2)) <= 12:
        return False
    y, mo, d, t = m.group(1), _MON[int(m.group(2)) - 1], m.group(3), m.group(4)
    return any(f"{dd}{mo}{y}{t}" in out_nows_cleaned for dd in {d, d.lstrip("0")})


def value_recall(ref_values, out_nows_cleaned):
    if not ref_values:
        return None
    hit = sum(1 for v in ref_values if _key_hit(_key(v), out_nows_cleaned))
    return hit / len(ref_values)


def numeric_values(ref_values):
    pool = set()
    for v in ref_values:
        val = str(v.get("value") if isinstance(v, dict) else v).replace(",", "").strip()
        try:
            float(val)
            pool.add(val)
        except ValueError:
            pass
    return pool


def num_halluc(ref_pool, stext):
    """P2h 수치 환각률 — 출력 숫자 토큰(2자리 이상) 중 정답 숫자 풀에 없는 비율."""
    outn = {n for n in out_nums(stext) if sum(c.isdigit() for c in n) >= 2}
    return (len(outn - ref_pool) / len(outn)) if outn else 0.0


def table_recall(tables, out_nows_cleaned, out_lines_nows):
    """P3 표 행 재현율 · P3c 표 셀 재현율.
    out_lines_nows = 본문 text.splitlines() + (있으면) 엔진 자신의 tables[].grid 각 행을 한 줄로 합친 것(C3) —
    구조 보존 엔진(표 셀을 이미 아는 엔진)은 tables[].text가 행 경계 없는 한 덩어리라 본문 줄만으로는 판정이
    안 됐던 것을 grid로 보강한다(호출부 score_engine에서 합침). grid 없는 엔진(OCR 등)은 이전과 동일하게
    본문 줄만으로 판정 — ponytail: 새 비교 경로를 따로 만들지 않고 같은 '줄 풀'에 추가만 함(최소 변경)."""
    cells, rows = [], []
    for t in tables:
        for r in t:
            rc = [str(c).strip() for c in r if str(c or "").strip()]
            cells += rc
            if len(rc) >= 2:
                rows.append(rc)
    if not cells:
        return None, None
    # C2 — 셀·행 모두 _key_hit(메일 날짜 표기 인정). 정규화 뒤 빈 키 셀은 예전처럼 '있음'(빈 문자열 ⊂ 모든 줄) — 표 지표 바이트 동일
    hit = lambda c, s: (not _key(c)) or _key_hit(_key(c), s)
    cell_hit = sum(1 for c in cells if hit(c, out_nows_cleaned))
    row_hit = sum(1 for r in rows if any(all(hit(c, ln) for c in r) for ln in out_lines_nows))
    return (row_hit / len(rows) if rows else None), (cell_hit / len(cells))


def scoring_text(d):
    """엔진 출력 채점용 텍스트 = text + (본문에 없는) 표 텍스트."""
    text = d.get("text") or ""
    base = norm(text)
    parts = [text] + [t.get("text") or "" for t in (d.get("tables") or []) if (t.get("text") or "") and norm(t["text"]) not in base]
    return "\n".join(parts)


def ko_ratio(text):
    body = re.sub(r"\s", "", text)
    return round(len(_KO.findall(text)) / len(body), 4) if body else 0.0


def garbage_ratio(text):
    """ponytail: 정의된 공식이 없어 대체 문자·제어 문자 비율(글자 단위)과 한 글자짜리 줄 비율(줄 단위)의
    평균으로 합성 — 둘 다 §3-2 '깨짐률' 신호(대체 문자·제어 문자·한 글자짜리 줄)를 반영."""
    if not text:
        return 0.0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    ctrl = sum(1 for c in text if unicodedata.category(c) == "Cc" and c not in "\n\t\r")
    repl = text.count("�")
    single = sum(1 for ln in lines if len(ln.strip()) == 1)
    return round(((repl + ctrl) / max(1, len(text)) + single / max(1, len(lines))) / 2, 4)


def pdf_kind(path):
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        n = len(doc)
        chars = sum(len(doc[i].get_textpage().get_text_range().strip()) for i in range(n))
    except Exception:
        try:
            import fitz

            d = fitz.open(str(path))
            n = d.page_count
            chars = sum(len(d[i].get_text().strip()) for i in range(n))
        except Exception:
            return "pdf_text", None  # ponytail: 페이지 텍스트 레이어 확인 불가 — 텍스트형으로 보수적 가정
    if n == 0:
        return "pdf_image", 0
    return ("pdf_image" if chars < 20 * n else "pdf_text"), n


def doc_format(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        kind, pages = pdf_kind(path)
        return "." + kind, pages
    if ext in IMG:
        return ext, 1
    if ext == ".pptx":  # A9 — 슬라이드 수를 쪽 수로(zip 목록만 셈) — 한 장짜리면 청크 page=1(bundle 규칙), 보고서 쪽 수도 채워짐
        import re
        import zipfile

        try:
            with zipfile.ZipFile(path) as z:
                return ext, sum(1 for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)) or None
        except (zipfile.BadZipFile, OSError):
            return ext, None
    return ext, None


def group_of(ext, crit):
    if ext in crit["groups"]["native"]:
        return "native"
    if ext in crit["groups"]["image"]:
        return "image"
    return None


def load_answer_key(dirpath, doc):
    if not dirpath:
        return None
    for cand in (dirpath / (doc + ".json"), dirpath / (Path(doc).stem + ".json")):
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8")).get("values") or None
            except Exception:
                return None
    return None


def resolve_ref(doc, ext_key, group, docs_res, truth, akey_dir, meaning=None):
    """기준점: 정답 → 사람 정답지 → 원본 구조 파서(형식별 지정, 없으면 유의미 텍스트가 가장 많은 엔진) → (없으면 호출 쪽에서 계열 합의 수치).
    meaning = {엔진: 다른 계열과 겹친 유의미 토큰 수} — 지정 파서가 없는 형식(.eml 등)에서 알파벳 순 대신 이것으로 고른다."""
    t = truth.get(doc)
    if t:
        return "truth", t.get("text") or "", t.get("values") or [], t.get("tables") or [], None
    ak = load_answer_key(akey_dir, doc)
    if ak:
        return "answer_key", "", ak, [], None
    if group == "native":
        # .pdf_text 지정 파서 pdfplumber는 0.2.0에 지움(돈 적 없음 — 결과 같음)
        cands = [] if ext_key == ".pdf_text" else NATIVE.get(ext_key)
        if cands is None:
            cands = sorted(registry.engines_for(ext_key), key=lambda e: (-(meaning or {}).get(e, 0), e))
        for c in cands:
            if c in docs_res:
                return "native", docs_res[c].get("text") or "", [], [], c
    return None, "", [], [], None


def build_consensus(per_doc_nums, eng_fam, min_stacks=3):
    """summarize.py와 같은 규칙(다른 계열 min_stacks개 이상 합의)으로 문서별 합의 수치 집합을 만든다."""
    out = {}
    for doc, by_eng in per_doc_nums.items():
        fams = defaultdict(set)
        for eng, ns in by_eng.items():
            for n in ns:
                fams[n].add(eng_fam.get(eng, eng))
        out[doc] = {n for n, s in fams.items() if len(s) >= min_stacks}
    return out


MIN_OK_CHARS = 15  # 파싱 성공 기준: 글자 있는 문서에서 출력이 이 글자 수 미만이면 실패(빈 결과) — 사용자 2026-09-30(50 → 20 → 15)


def text_tokens(text):
    """유의미 토큰 — 규칙은 common/meaning.py 한 곳(수치·단어 O · 구분선·기호·쪽 번호·1자 X · 머리말·꼬리말 작업자·날짜는 셈)."""
    from common.core.meaning import tokens

    return tokens(text)


def build_token_consensus(per_doc_toks, eng_fam, min_fams=2):
    """문서별 '유의미 텍스트' = 서로 다른 계열 min_fams개 이상이 뽑은 토큰. 계열이 min_fams보다 적으면 없음(판정 불가).
    반환 = (cons, conflicts). cons는 이전과 완전히 같은 모양(doc → 토큰 집합) — 호출부 로직 불변.
    conflicts는 AD25(a) 추가: 같은 문서에서 숫자 표기가 갈리지만
    같은 값일 수 있는 자리(pipeline.shared.meaning.canon_num_key, 예 430.000↔430,000)를 엔진별 원문 표기와 함께 기록한다
    (합치지 않고 표시만 — 판정은 AD26 이후 몫)."""
    from pipeline.shared.meaning import canon_num_key

    out, conflicts = {}, {}
    for doc, by_eng in per_doc_toks.items():
        fams = defaultdict(set)
        canon = defaultdict(lambda: defaultdict(set))
        for eng, ts in by_eng.items():
            for t in ts:
                fams[t].add(eng_fam.get(eng, eng))
                k = canon_num_key(t)
                if k:
                    canon[k][t].add(eng)
        if len({eng_fam.get(e, e) for e in by_eng}) >= min_fams:
            out[doc] = {t for t, s in fams.items() if len(s) >= min_fams}
            hits = [{"value": k, "forms": {s: sorted(e) for s, e in surf.items()}} for k, surf in canon.items() if len(surf) >= 2]
            if hits:
                conflicts[doc] = hits
    return out, conflicts


def score_engine(eng, r, d, ref, ctx):
    ref_type, ref_text, ref_values, ref_tables, ref_pool = ref
    err = r["error"] if r else "실행 안 됨"
    text = (d.get("text") or "") if d else ""
    chars = len(text)
    has_text_doc = ctx["ref_chars"] == 0 or ctx["ref_chars"] >= MIN_OK_CHARS
    ok = bool(d) and not err and not (has_text_doc and chars < MIN_OK_CHARS)
    m = {
        "ok": ok,
        "error": err,
        "sec": r["sec"] if r else None,
        "chars": chars,
        "lines": sum(1 for ln in text.splitlines() if ln.strip()),
        "tables": len(d.get("tables") or []) if d else 0,
        "figures": len((d.get("post") or {}).get("figures") or []) if d else 0,
        "nums": len(nums(d)) if d else 0,
        "ko_ratio": ko_ratio(text),
        "garbage": garbage_ratio(text),
    }
    if not d:
        return m
    consensus_set = ctx["consensus"]
    if consensus_set:
        eng_nums = ctx["per_doc_nums"].get(eng, set())
        m["consensus_recall"] = round(len(eng_nums & consensus_set) / len(consensus_set), 4)
    tcons = ctx.get("tok_cons")
    if tcons:
        mine = ctx["per_doc_toks"].get(eng, set())
        m["cross_recall"] = round(len(mine & tcons) / len(tcons), 4)  # 다른 엔진과 대조한 유의미 텍스트 재현율(정답 없는 실데이터 정확도)
        m["meaningful"] = sum(len(t) for t in mine & tcons)
    stext = scoring_text(d)
    if pc.cfg().transform.represent.qa_light:  # S7c — 설정 객체(on=("1",) = 옛 =="1")
        pass  # 2026-10-22 사용자 지정 — 경량화: native 대비 풀문서 CER·order fuzzy 생략(cross_recall·tables/figures는 유지 → doc_accuracy 무손상)
    elif ref_text and not ctx.get("sheet"):  # 스프레드시트는 셀 잇는 순서가 파서마다 달라 CER·순서 대신 값 재현율로(백로그 C10)
        c, capped = cer(ref_text, text)
        m["cer"] = round(c, 4)
        if capped:
            ctx["capped"].append(f"{ctx['doc']}:{eng}")
        if HAS_RAPIDFUZZ:  # SI1: 없으면 줄마다 difflib 전수 비교 — 큰 문서에서 멈춘 것처럼 보임(서버 실측) → 생략
            order, diff = order_diff(ref_text, text)
            if order is not None:
                m["order"], m["diff"] = round(order, 4), diff
    if ref_values:
        m["value_recall"] = round(value_recall(ref_values, clean_commas(norm_nows(stext))), 4)
    if ref_pool is not None:
        m["num_halluc"] = round(num_halluc(ref_pool, stext), 4)
    if ref_type == "truth" and ref_tables:
        out_lines_nows = [norm_nows(ln) for ln in text.splitlines() if ln.strip()]
        grid_lines = [
            norm_nows(" ".join(str(c or "").strip() for c in row))  # C3 — 구조 보존 엔진의
            for t in (d.get("tables") or [])
            for row in (t.get("grid") or [])  # tables[].grid(행×열, 선택
            if any(str(c or "").strip() for c in row)
        ]  # 칸)를 줄 풀에 추가
        rr, rc = table_recall(ref_tables, clean_commas(norm_nows(stext)), [clean_commas(x) for x in out_lines_nows + grid_lines])
        if rr is not None:
            m["table_row_recall"] = round(rr, 4)
        if rc is not None:
            m["table_cell_recall"] = round(rc, 4)
    return m


def check_pass(row, group, crit_parse):
    passed = {}
    for c in crit_parse:
        thr = c.get(group) if group in ("native", "image") else c.get("value")
        if thr is None or c["metric"] not in row or row[c["metric"]] is None:
            continue
        passed[c["id"]] = (row[c["metric"]] >= thr) if c["dir"] == ">=" else (row[c["metric"]] <= thr)
    return passed


def aggregate(qa_docs, crit):
    buckets, oks = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: [0, 0])
    for dd in qa_docs.values():
        for b in {x for x in (dd["group"], dd["format"]) if x}:
            for eng, m in dd["engines"].items():
                oks[(eng, b)][1] += 1
                oks[(eng, b)][0] += 1 if m.get("ok") else 0
                for k, v in m.items():
                    if k != "ok" and isinstance(v, (int, float)) and not isinstance(v, bool):
                        buckets[(eng, b)][k].append(v)
    out = defaultdict(dict)
    for (eng, b), metrics in buckets.items():
        row = {k: round(statistics.mean(vs), 4) for k, vs in metrics.items() if vs}
        ok, tot = oks[(eng, b)]
        row["ok_rate"] = round(ok / tot, 4) if tot else 0.0
        g = b if b in ("native", "image") else group_of(b, crit)
        row["pass"] = check_pass(row, g, crit["parse"]) if g else {}
        out[eng][b] = row
    return out


def build_route(agg, qa_docs, exts):
    route = {}
    for ext in sorted(exts):
        ran = {eng for dd in qa_docs.values() if dd["format"] == ext for eng, m in dd["engines"].items() if m.get("error") is None}
        cand = [(eng, agg[eng][ext]) for eng in ran if ext in agg.get(eng, {})]
        if not cand:
            continue

        def acc(eng):  # doc_accuracy 평균(실패 = 0) — 요약·선정과 같은 정확도
            vs = [
                doc_accuracy(dd["engines"][eng], dd.get("ref")) or 0.0
                for dd in qa_docs.values()
                if dd["format"] == ext and eng in dd["engines"]  # noqa: B023 — acc는 같은 반복 안에서만 부름
            ]
            return sum(vs) / len(vs) if vs else -1

        cand.sort(
            key=lambda x: (
                -round(acc(x[0]), 4),
                x[1].get("cer") if x[1].get("cer") is not None else 9e9,
                -x[1].get("ok_rate", 0),
                x[1].get("sec") if x[1].get("sec") is not None else 9e9,
                x[0],
            )
        )
        route[ext] = [e for e, _ in cand]
    return route


def flags(qa_docs):
    hits = []
    for doc, dd in qa_docs.items():
        chars_by = {e: m.get("chars", 0) for e, m in dd["engines"].items()}
        max_chars = max(chars_by.values(), default=0)
        ko_vals = [m["ko_ratio"] for m in dd["engines"].values() if m.get("ko_ratio") is not None]
        ko_med = statistics.median(ko_vals) if ko_vals else 0
        for eng, m in dd["engines"].items():
            if m.get("chars", 0) < MIN_OK_CHARS and max_chars > 500:
                hits.append((doc, eng, "F1"))
            lr = m.get("len_ratio")
            if lr is not None and (lr < 0.5 or lr > 2.0):
                hits.append((doc, eng, "F2"))
            if (m.get("garbage") or 0) > 0.05:
                hits.append((doc, eng, "F3"))
            if ko_med and m.get("ko_ratio", 0) < ko_med * 0.5:
                hits.append((doc, eng, "F4"))
    return hits


def _unavailable(err):
    from pipeline.shared.progress import is_env_error  # 환경 실패 단서 한 곳(SI45)

    return is_env_error(err)


def run(parse_dir, src_dir, truth_path, akey_dir, prev_docs=None):
    runs, unavailable = {}, {}
    for line in (parse_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if _unavailable(r.get("error")):  # 미설치·미설정·외부 바이너리 없음 = 이 환경에서 미실행(실패와 구분)
            unavailable[r["engine"]] = r["error"][:120]
            continue
        runs[(r["doc"], r["engine"])] = r
    for _, e in runs:
        unavailable.pop(e, None)
    # 중간(phase 1·2) 시간 초과 = 다음 phase 대기 — 실패로 세지 않고 이번 채점에서 뺀다(phase 단위 보고서가 대기분을 0점으로 만들지 않게)
    pending = Counter()
    for k, r in list(runs.items()):
        if "Timeout" in (r.get("error") or "") and (r.get("phase") or 3) < 3:
            pending[r["engine"]] += 1
            del runs[k]
    phase_done = max((r.get("phase") or 0 for r in runs.values()), default=0) or None
    res = {}
    for (doc, eng), r in runs.items():
        f = parse_dir / eng / (doc + ".json")
        if not r.get("error") and f.exists():
            try:
                res[(doc, eng)] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # 깨진 결과 파일 하나가 파싱 모듈 전체를 세우지 않게 — 그 엔진만 빼고 알림
                print(f"[parse_qa] 결과 파일을 읽을 수 없어 뺌: {eng}/{doc}.json", flush=True)
    eng_fam = {e: FAMILY.get(e, s) for e, (s, _) in registry.engines().items()}
    per_doc_nums = defaultdict(dict)
    for (doc, eng), d in res.items():
        per_doc_nums[doc][eng] = nums(d)
    consensus = build_consensus(per_doc_nums, eng_fam)
    per_doc_toks = defaultdict(dict)
    for (doc, eng), d in res.items():
        per_doc_toks[doc][eng] = text_tokens(d.get("text"))
    tok_cons, tok_conflicts = build_token_consensus(per_doc_toks, eng_fam)
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else {}
    src_map = {p.name: p for p in src_dir.iterdir()} if src_dir.exists() else {}
    crit = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))

    qa_docs, capped = {}, []
    doc_list = sorted({d for d, _ in runs})
    for i, doc in enumerate(doc_list, 1):
        docs_res = {e: d for (dd, e), d in res.items() if dd == doc}
        cur_engs = sorted({e for d_, e in runs if d_ == doc})
        prev_entry = (prev_docs or {}).get(doc)
        prev_fp = (prev_entry or {}).get("fp") or {}
        # 독립 검토 #4(10-14) — sha(원본 내용)·p0_code(그 엔진 코드 지문, run_all.engine_code_fp)가 전부
        # 그대로일 때만 들고 온다. 둘 중 하나라도 다르면(문서 내용이 바뀌었거나 엔진 코드가 바뀜) 이전 점수가
        # 지금 상황과 안 맞을 수 있어 그냥 안 들고 온다 — 파일이 없으니 "실행 안 됨"으로 다시 채점되고(현재
        # 동작과 같음), 실제로 재파싱되면 그때 새 점수로 바뀐다.
        fresh = bool(cur_engs) and all(
            prev_fp.get(e, {}).get("sha") == (runs.get((doc, e)) or {}).get("sha")
            and prev_fp.get(e, {}).get("p0_code") == (runs.get((doc, e)) or {}).get("p0_code")
            for e in cur_engs
        )
        if not docs_res and prev_entry and fresh:
            # O3(백로그 server.md) — 스트리밍: 이 문서는 전 배치에서 이미 채점됐고 그 뒤 엔진별 중간 결과를
            # 지웠다(원본 즉시 삭제, X2) — 파일이 없어 다시 못 채점하니 이전 qa.json의 그 문서 항목을 그대로
            # 들고 온다. score_engine()은 그 결과 json의 내용만 보는 순수 함수라 "그때 계산된 값"과 "지금 다시
            # 계산한 값"이 같다(파일이 안 바뀌었으므로) — 그래서 qa_docs를 전부 모으면(이번 배치 새 채점 +
            # 과거 배치 들고오기) 파일을 전부 보존한 채 통째로 다시 채점한 것과 같은 aggregate·route.json이 나온다.
            print(f"[parse_qa] 채점 {i}/{len(doc_list)}: {doc} — 이전 결과 그대로(중간 결과 삭제됨)", flush=True)
            qa_docs[doc] = prev_entry
            continue
        print(f"[parse_qa] 채점 {i}/{len(doc_list)}: {doc}", flush=True)  # SI1: 진행 표시 — 무한 대기처럼 보이지 않게
        path = src_map.get(doc)
        ext_key, pages = doc_format(path) if path else (Path(doc).suffix.lower(), None)
        group = group_of(ext_key, crit)
        ref_type, ref_text, ref_values, ref_tables, native_eng = resolve_ref(
            doc,
            ext_key,
            group,
            docs_res,
            truth,
            akey_dir,
            {e: len(ts & (tok_cons.get(doc) or set())) for e, ts in per_doc_toks.get(doc, {}).items()},
        )
        if ref_type == "native" and ref_text:
            ref_values = [{"value": n} for n in sorted(out_nums(ref_text))]
        if not ref_type:
            cset = consensus.get(doc)
            ref_type, ref_values = ("consensus", [{"value": n} for n in sorted(cset)]) if cset else ("none", [])
        ref_pool = out_nums(ref_text) if ref_text else (numeric_values(ref_values) if ref_values else None)
        ctx = {
            "doc": doc,
            "ref_chars": len(ref_text),
            "sheet": ext_key in SHEET,
            "per_doc_nums": per_doc_nums.get(doc, {}),
            "consensus": consensus.get(doc, set()),
            "capped": capped,
            "per_doc_toks": per_doc_toks.get(doc, {}),
            "tok_cons": tok_cons.get(doc),
        }
        ref = (ref_type, ref_text, ref_values, ref_tables, ref_pool)
        engines_dict = {}
        for eng in sorted({e for d, e in runs if d == doc}):
            r_ = (ref_type, "", [], [], None) if eng == native_eng else ref  # 기준 파서 자신과는 값 비교 안 함
            engines_dict[eng] = score_engine(eng, runs.get((doc, eng)), docs_res.get(eng), r_, ctx)
            if eng == native_eng:
                engines_dict[eng]["is_ref"] = True
        chars_ok = [m["chars"] for m in engines_dict.values() if m["ok"]]
        med = statistics.median(chars_ok) if chars_ok else 0
        for m in engines_dict.values():
            m["len_ratio"] = round(m["chars"] / med, 4) if med else None
        qa_docs[doc] = {
            "format": ext_key,
            "group": group,
            "pages": pages,
            "ref": ref_type,
            "ref_chars": len(ref_text),
            "engines": engines_dict,
            "n_fam": len({eng_fam.get(e, e) for e, m in engines_dict.items() if m.get("ok")}),  # 성공한 독립 인식 계열 수
            "fp": {
                e: {"sha": (runs.get((doc, e)) or {}).get("sha"), "p0_code": (runs.get((doc, e)) or {}).get("p0_code")} for e in cur_engs
            },
        }  # 독립 검토 #4 — 다음 배치의 캐리 포워드 신선도 확인용(원본 sha·엔진 코드 지문)

    agg = aggregate(
        qa_docs, crit
    )  # 회전은 prepare.py가 가장 잘 읽히는 방향으로 돌린 문서만 채점(회전 강건성 P6 없음 — 사용자 결정 2026-09-30)
    route = build_route(agg, qa_docs, {dd["format"] for dd in qa_docs.values()})
    meta = {
        "parse": str(parse_dir),
        "src": str(src_dir),
        "truth": str(truth_path) if truth else None,
        "answer_key": str(akey_dir) if akey_dir else None,
        "ref_by_doc": {d: dd["ref"] for d, dd in qa_docs.items()},
        "cer_capped": capped,
        "unavailable": unavailable,
        "phase": phase_done,
        "pending": dict(pending),
    }
    if tok_conflicts:  # AD25 — 갈린 숫자 표기가 있을 때만
        meta["token_conflicts"] = tok_conflicts
    return {"meta": meta, "docs": qa_docs, "engines": dict(agg)}, route


FULL = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))["run"][
    "cross_acc_full"
]  # 문서 "성공" 판정(0.95 — 사용자 2026-09-30, 0.999 → 0.95) · 정본 criteria.json run(RB3)
LOW_N = 2  # 파싱 성공 엔진이 이 수 이하인 문서 = 모수 적음(교차 대조·정확도 판단이 약함) — 보고서 강조
# doc_accuracy·GOLD는 pipeline/transform/represent/repfmt.py에 있음(AG11 2단계 착수 조건 10-08 → 10-14 함수별 분리) — 위 import로 재사용(로직 불변)


def parse_summary(qa, src_dir=None):
    """타입별(PDF는 텍스트/이미지 구분) 지원 문서 · 수집 성공(엔진 1개 이상) · 정확도 95% 이상 문서 · 평균 정확도(문서별 최고 엔진)
    + 엔진 × 타입(평균 정확도 · 교차 재현율 0.95 이상 문서 수) + 합계. PHASE_REPORT·report.py·finalize·RUNLOG가 모두 이 결과를 쓴다(정의 한 곳)."""
    types = defaultdict(
        lambda: {"docs": 0, "collected": 0, "full": 0, "judged": 0, "acc": [], "unjudged": [], "failed": [], "partial": [], "low_n": []}
    )
    eng = defaultdict(lambda: defaultdict(list))
    xr = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 엔진 × 타입 → [성공(15자+) 문서 수, 교차 재현율 ≥ FULL 문서 수]
    for doc, d in qa["docs"].items():
        for e, m in d["engines"].items():
            c = xr[e][d["format"]]
            if m.get("ok"):
                c[0] += 1
                a = m.get("cross_recall") if m.get("cross_recall") is not None else doc_accuracy(m, d.get("ref"))
                c[1] += a is not None and a >= FULL
        t = types[d["format"]]
        t["docs"] += 1
        accs = {e: doc_accuracy(m, d.get("ref")) for e, m in d["engines"].items()}
        oks = [e for e, m in d["engines"].items() if m.get("ok")]
        has_ref = any(a is not None for a in accs.values())
        for e, a in accs.items():
            if a is not None:
                eng[e][d["format"]].append(a)
            elif has_ref:  # 기준점 있는 문서에서 실패·빈 결과 = 정확도 0(엔진 표가 좋게만 보이지 않게)
                eng[e][d["format"]].append(0.0)
        nf = d.get("n_fam", len(oks))
        if oks and (len(oks) <= LOW_N or nf <= LOW_N):
            t["low_n"].append(
                f"{doc}(성공 {len(oks)} · 계열 {nf})"
            )  # 계열 ≤2면 정답 없이 대조(교차 재현율)가 순위를 잘 못 가림(개발 PC png·jpg 실측)
        if oks:
            t["collected"] += 1
        else:
            t["failed"].append(doc)
        judged = [a for a in accs.values() if a is not None]
        if not judged:
            if oks:
                t["unjudged"].append(doc)  # 수집은 됐지만 기준점(정답·원본·합의 수치)이 없어 정확도 판정 불가
            continue
        best = max(judged)
        t["judged"] += 1
        t["acc"].append(best)
        if best >= FULL:
            t["full"] += 1
        else:
            t["partial"].append(f"{doc}({best:.2f})")
    unsupported = []
    if src_dir and Path(src_dir).is_dir():
        seen = set(qa["docs"])
        unsupported = sorted(
            p.name for p in Path(src_dir).iterdir() if p.is_file() and p.name not in seen and p.name not in (".gitkeep", "rotation.csv")
        )
    rows = {
        k: {
            "docs": v["docs"],
            "collected": v["collected"],
            "full": v["full"],
            "judged": v["judged"],
            "mean_acc": round(sum(v["acc"]) / len(v["acc"]), 4) if v["acc"] else None,
            "failed": v["failed"],
            "unjudged": v["unjudged"],
            "partial": v["partial"],
            "low_n": v["low_n"],
        }
        for k, v in sorted(types.items())
    }
    n = sum(r["docs"] for r in rows.values())
    all_acc = [a for v in types.values() for a in v["acc"]]
    total = {
        "supported_docs": n,
        "collected": sum(r["collected"] for r in rows.values()),
        "full": sum(r["full"] for r in rows.values()),
        "judged": sum(r["judged"] for r in rows.values()),
        "mean_acc": round(sum(all_acc) / len(all_acc), 4) if all_acc else None,
        "unsupported": unsupported,
        "low_n": sum(len(r["low_n"]) for r in rows.values()),
    }
    total["line"] = (
        f"성공 문서 합계 {total['full']}/{n} (지원 타입 문서 {n}개 중 정확도 95% 이상 {total['full']}개) · 수집 성공 {total['collected']}/{n}"
        + (f" · 평균 정확도 {total['mean_acc']:.3f}" if total["mean_acc"] is not None else "")
        + (f" · 판정 불가 {n - total['judged'] - (n - total['collected'])}개" if n - total["judged"] - (n - total["collected"]) else "")
        + (f" · 지원 안 되는 형식 {len(unsupported)}개" if unsupported else "")
        + (f" · 모수 적음(성공 엔진·독립 계열 ≤{LOW_N}) {total['low_n']}개" if total["low_n"] else "")
    )
    engines = {
        e: {
            t: {
                "mean_acc": round(sum(v) / len(v), 4),
                "n": len(v),
                "full": sum(x >= FULL for x in v),
                "ok": xr[e][t][0],
                "xr95": xr[e][t][1],
            }
            for t, v in by.items()
        }
        for e, by in sorted(eng.items())
    }
    for e, by in xr.items():  # 기준점 없어 정확도 목록엔 없지만 실행한 엔진·형식도 표에 나오게
        for t, (ok, x) in by.items():
            engines.setdefault(e, {}).setdefault(t, {"mean_acc": None, "n": 0, "full": 0, "ok": ok, "xr95": x})
    return {"types": rows, "total": total, "engines": engines}


def summary_md(ps):
    """parse_summary → 마크다운 표(PHASE_REPORT·FINAL_SUMMARY 공용)."""
    md = [
        "| 타입 | 지원 문서 | 수집 성공(엔진 1개 이상) | 정확도 95% 이상 | 평균 정확도(문서별 최고 엔진) | 판정 불가 | 100% 미만 문서 | ⚠ 모수 적음(성공 엔진·독립 계열 ≤2) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t, r in ps["types"].items():
        md.append(
            f"| {t} | {r['docs']} | {r['collected']}/{r['docs']} | **{r['full']}/{r['docs']}** | "
            + (f"{r['mean_acc']:.3f}" if r["mean_acc"] is not None else "—")
            + f" | {len(r['unjudged'])} | {', '.join(r['partial'][:5]) or '—'} | {', '.join(r.get('low_n', [])[:5]) or '—'} |"
        )
    tt = ps["total"]
    md.append(
        f"| **합계** | {tt['supported_docs']} | {tt['collected']}/{tt['supported_docs']} | **{tt['full']}/{tt['supported_docs']}** | "
        + (f"{tt['mean_acc']:.3f}" if tt["mean_acc"] is not None else "—")
        + f" | {tt['supported_docs'] - tt['judged'] - (tt['supported_docs'] - tt['collected'])} | | {tt.get('low_n', 0)} |"
    )
    md += ["", f"**{tt['line']}**"]
    if tt["unsupported"]:
        md.append(f"- 지원 안 되는 형식(처리 엔진 없음): {', '.join(tt['unsupported'][:20])}")
    md += [
        "",
        "정확도 = 값 재현율(기준: 정답 → 사람 정답지 → 원본 구조 파서), 이미지 실데이터는 인식 계열 합의 수치 재현율. 문서 정확도 = 그 문서에서 가장 잘 뽑은 엔진. "
        "판정 불가 = 수집은 됐으나 기준점이 없음(사람 검토 대상).",
    ]
    return md


VLM_ENV = ("VLM_", "LLM_")  # 서버 모델 연결 설정 — 개발 PC에서 비어 있어 못 돈 엔진은 '문제'가 아니라 '서버에서 추가'


def select_final(qa, per_type=3, target=10, tol=0.05):
    """실데이터 파싱에 쓸 엔진 ~target개 — 형식마다 2~3개(속도·정확도).
    정확도(문서별) = 값 재현율(정답·사람 정답지·원본 파서 기준) → 없으면 교차 재현율(다른 계열 엔진 2개+가 함께 뽑은 유의미 토큰 중 뽑은 비율).
    기준점 있는 문서의 실패·빈 결과 = 0. 형식별 후보 = 최고 정확도 - tol 이내 → 정확도(0.01 단위) 내림차순, 같으면 쪽당 초 오름차순.
    전체 선정 = 형식마다 2개가 찰 때까지 여러 형식에 걸친 엔진부터, 남으면 3번째(target까지)."""
    unavail = (qa.get("meta") or {}).get("unavailable") or {}
    vlm = {e: w for e, w in unavail.items() if any(k in w for k in VLM_ENV)}
    stats = defaultdict(lambda: defaultdict(lambda: {"acc": [], "ok": 0, "n": 0, "spp": [], "basis": set()}))
    for d in qa["docs"].values():
        t, pages = d["format"], d.get("pages") or 1
        for e, m in d["engines"].items():
            if e in unavail:
                continue
            s = stats[t][e]
            s["n"] += 1
            s["ok"] += bool(m.get("ok"))
            a = doc_accuracy(m, d.get("ref"))
            if a is not None:
                s["acc"].append(a)
                s["basis"].add(
                    "교차 재현율"
                    if m.get("cross_recall") is not None
                    else "계열 합의 재현율"
                    if m.get("consensus_recall") is not None
                    else "값 재현율(원본 파서)"
                )
            elif not m.get("ok") and d.get("ref") != "none":
                s["acc"].append(0.0)
            if m.get("ok") and m.get("sec") is not None:
                s["spp"].append(m["sec"] / pages)
    cand, issues, ranked_all = {}, [], {}
    for t, by in sorted(stats.items()):
        rows = []
        for e, s in by.items():
            acc = sum(s["acc"]) / len(s["acc"]) if s["acc"] else None
            spp = statistics.median(s["spp"]) if s["spp"] else None
            rows.append(
                {
                    "engine": e,
                    "acc": round(acc, 4) if acc is not None else None,
                    "ok_rate": round(s["ok"] / s["n"], 4),
                    "sec_page": round(spp, 3) if spp is not None else None,
                    "basis": "·".join(sorted(s["basis"])) or "—",
                    "n": s["n"],
                }
            )
            if s["ok"] < s["n"]:
                issues.append({"engine": e, "type": t, "issue": f"실패 {s['n'] - s['ok']}/{s['n']}건"})
            elif acc is not None and acc < 0.9:
                issues.append({"engine": e, "type": t, "issue": f"정확도 {acc:.2f}(부분 추출)"})
        ok_rows = [r for r in rows if r["acc"] is not None and r["ok_rate"] >= 0.5]
        best = max((r["acc"] for r in ok_rows), default=None)
        near = [r for r in ok_rows if best is not None and r["acc"] >= best - tol]
        order = lambda r: (-round(r["acc"], 2), r["sec_page"] if r["sec_page"] is not None else 9e9, r["engine"])
        near.sort(key=order)
        cand[t] = near[:per_type]
        ranked_all[t] = [r["engine"] for r in sorted(ok_rows, key=order)]
    cover = Counter(r["engine"] for rs in cand.values() for r in rs)
    selected = []
    for need in (2, per_type):
        for _t, rs in cand.items():
            while sum(r["engine"] in selected for r in rs) < min(need, len(rs)):
                if need > 2 and len(selected) >= target:
                    break
                pool = [r for r in rs[:need] if r["engine"] not in selected] or [
                    r for r in rs if r["engine"] not in selected
                ]  # 상위 need개 안에서 먼저
                pick = min(pool, key=lambda r: (-cover[r["engine"]], rs.index(r)))
                selected.append(pick["engine"])
    # 형식별 최종 담당 = 선정 엔진 중 그 형식 순위가 가장 높은 것(주) + 다음(예비) — 모든 형식이 덮이는지 확인
    final = {t: [e for e in ranked_all.get(t, []) if e in selected][:2] for t in stats}
    uncovered = sorted(t for t, es in final.items() if not es)
    # 추천도 = 형식마다 순위 점수(1위 3 · 2위 2 · 3위 1) 합 + 주 담당 형식 수 — 보고서 표 정렬 기준(선정 엔진 먼저)
    score = Counter()
    for _t, es in ranked_all.items():
        for i, e in enumerate(es[:3]):
            score[e] += 3 - i
    for es in final.values():
        if es:
            score[es[0]] += 1
    sel = sorted(
        (
            {
                "engine": e,
                "score": score[e],
                "types": [t for t, rs in cand.items() if any(r["engine"] == e for r in rs)],
                "primary": [t for t, es in final.items() if es and es[0] == e],
                "backup": [t for t, es in final.items() if len(es) > 1 and es[1] == e],
            }
            for e in selected
        ),
        key=lambda x: (-x["score"], x["engine"]),
    )
    engines_all = {e for by in stats.values() for e in by} | set(unavail)
    recommend = sorted(engines_all, key=lambda e: (e not in selected, -score[e], e))
    for e, w in unavail.items():
        if e not in vlm:
            issues.append({"engine": e, "type": "전체", "issue": "미설치·미설정: " + w[:80]})
    return {
        "rule": select_final.__doc__.split("\n", 1)[1].strip(),
        "types": cand,
        "selected": sel,
        "final": final,
        "uncovered": uncovered,
        "recommend": recommend,
        "score": dict(score),
        "excluded_vlm": [{"engine": e, "why": w[:100]} for e, w in sorted(vlm.items())],
        "issues": sorted(issues, key=lambda x: (x["engine"], x["type"])),
    }


def write_summary(qa, src_dir, out_dir):
    ps = parse_summary(qa, src_dir)
    (Path(out_dir) / "parse_summary.json").write_text(json.dumps(ps, ensure_ascii=False, indent=1), encoding="utf-8")
    (Path(out_dir) / "selection.json").write_text(json.dumps(select_final(qa), ensure_ascii=False, indent=1), encoding="utf-8")
    return ps


def _fmt(v, w=7):
    return f"{v:{w}.3f}" if isinstance(v, (int, float)) else f"{'—':>{w}}"


def print_console(qa):
    print("\n엔진 × 형식군 — ok_rate · cer · value_recall · sec_mean")
    print(f"{'engine':22s} {'group':7s} {'ok_rate':>8s} {'cer':>8s} {'val_recall':>11s} {'sec':>8s}")
    for eng in sorted(qa["engines"]):
        for grp in ("native", "image"):
            row = qa["engines"][eng].get(grp)
            if row:
                print(
                    f"{eng:22s} {grp:7s} {_fmt(row.get('ok_rate'), 8)} {_fmt(row.get('cer'), 8)} "
                    f"{_fmt(row.get('value_recall'), 11)} {_fmt(row.get('sec'), 8)}"
                )


def print_flags(qa_docs):
    hits = flags(qa_docs)
    by_flag = defaultdict(list)
    for doc, eng, f in hits:
        by_flag[f].append(f"{doc}/{eng}")
    print(f"\n참조 없는 문서 신호(F1-F4) {len(hits)}건")
    for f in sorted(by_flag):
        ex = by_flag[f][:10]
        more = f" 외 {len(by_flag[f]) - 10}건" if len(by_flag[f]) > 10 else ""
        print(f"  {f}: {len(by_flag[f])}건 — {', '.join(ex)}{more}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", default=str(APP_ROOT / "output" / "parse"))
    ap.add_argument(
        "--src", default=None, help="원본 문서 폴더(기본 DOC_DIR env — --help·import 때는 안 풀어야 하므로 여기서는 default=None)"
    )
    ap.add_argument("--truth", default=str(APP_ROOT / "output" / "corpus" / "truth.json"))
    ap.add_argument("--answer-key", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.src is None:
        a.src = str(doc_dir())
    if not HAS_RAPIDFUZZ:
        print(
            "[parse_qa] 경고: rapidfuzz 미설치 — 읽기 순서(order) 채점 생략(없으면 줄마다 difflib 전수 비교로 큰 문서에서 멈춘 것처럼 보임). "
            "pip install rapidfuzz 권장",
            flush=True,
        )
    out_dir = Path(a.out) if a.out else Path(a.parse)
    prev_docs = None
    prev_qa = out_dir / "qa.json"  # O3 — 지워진 문서 결과를 이전 qa.json에서 들고옴
    if prev_qa.exists():
        try:
            prev_docs = json.loads(prev_qa.read_text(encoding="utf-8")).get("docs")
        except (OSError, ValueError):
            prev_docs = None
    qa, route = run(Path(a.parse), Path(a.src), Path(a.truth), Path(a.answer_key) if a.answer_key else None, prev_docs=prev_docs)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "route.json").write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    ps = write_summary(qa, Path(a.src), out_dir)
    print("\n" + "\n".join(summary_md(ps)))
    from common.core.runlog import note

    note(ps["total"]["line"])
    print_console(qa)
    print_flags(qa["docs"])
    print(f"\nqa.json · route.json → {out_dir}")


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("parse_qa"):
        main()
