#!/usr/bin/env python3
"""대표 결과 만들기 — 엔진 구성(stack `parse`)의 엔진 결과를 문서마다 하나로 → <parse>/_rep/<문서>.json · index.json.

문서마다:
  후보 = 그 형식에 구성된 엔진 중 파싱에 성공한 것. 대표 = 정확도(parse_scoring.doc_accuracy) → 구조 풍부도 → 구성 순서.
  모두 실패하면 구성 밖 성공 엔진으로 대체(fallback) — 빠진 문서가 없게.
  표준화(기호·첨자 표기) → 다른 후보의 표 행·키-값 보충 → 교차 병합(cross_merge — 대표 본문은 그대로, 다른 엔진에만 있는 조각을 끼움).
  스캔 쪽 채움 — .pdf_text 대표 안의 스캔 쪽만 쪽 VLM 글로(쪽 번호를 확정할 수 없거나 글이 깨졌으면 건너뜀).
  후보정(apply_post — vlm_page·figures·charts·supsub·attachments) → 표 제자리 넣기(table_inline).
산출 = 엔진 공통 출력 계약(text·tables·facts·boxes) + "rep" — 구조화(gold_bundle)는 이것만 읽는다.
사용: python -m pipeline.transform.represent.doc_represent [--stack stack.json] [--parse-dir output/parse]
"""

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

from common.core import span as SP
from common.core.console import utf8_stdout
from pipeline import config as pc
from pipeline.shared.env_error import is_env_error
from pipeline.shared.ext_groups import IMG_EXTS
from pipeline.shared.pdf_kind import doc_pages


def _richness(rep_json):
    """엔진 결과의 구조 인식 풍부도 — (tables, facts, figures, boxes) 개수.
    대표 엔진 선택 시 acc 동점이면 이 값이 높은 엔진을 우선 (표·이미지를 더 많이 인식한 엔진)."""
    if not rep_json:
        return (0, 0, 0, 0)
    return (
        len(rep_json.get("tables") or []),
        len(rep_json.get("facts") or []),
        len((rep_json.get("post") or {}).get("figures") or []),
        len(rep_json.get("boxes") or []),
    )


def _select_best(ok, pd, doc):
    """대표 엔진 선택 — 1) acc(정확도) 2) 구조 인식 풍부도(tables > facts > figures > boxes) 3) 스택 순서.
    ok: [{"engine", "ok", "acc"}] — 성공한 후보 목록. pd: parse_dir, doc: 문서명."""

    def score(c):
        acc = c["acc"] if c["acc"] is not None else -1
        try:
            rep = json.loads((pd / c["engine"] / f"{doc}.json").read_text(encoding="utf-8"))
            r = _richness(rep)
        except (OSError, ValueError):
            r = (0, 0, 0, 0)
        return (acc, r, -ok.index(c))

    return max(ok, key=score)


COVER_MIN = 0.98  # 다른 엔진 조각의 낱말이 이 비율 이상 대표(같은 쪽)에 있으면 같은 내용 — 끼우지 않음
_SEP = re.compile(r"\f|(?:\r?\n[ \t]*){2,}")  # 조각 경계 = 쪽 나눔 또는 빈 줄(\r\n도 같은 줄 끝)


def _words(s):
    return re.findall(r"\w+", s.lower())


def _blocks(text):
    """본문 → 조각 [(시작, 끝, 쪽 번호 0부터)] — 빈 줄·쪽 나눔(\\f) 경계(소제목·표·문단이 각각 한 조각)."""
    out, start, page = [], 0, 0
    for m in _SEP.finditer(text):
        if text[start : m.start()].strip():
            out.append((start, m.start(), page))
        page += m.group() == "\f"
        start = m.end()
    if text[start:].strip():
        out.append((start, len(text), page))
    return out


def cross_merge(rep, other):
    """대표 본문(rep["text"])은 그대로 두고 다른 엔진 본문(other) 조각 중 대표에 없는 것만 끼운다 → 끼운 조각 수.
    쪽 수(\\f)가 같으면 쪽끼리, 다르면 문서 전체끼리 비교. 공백을 뺀 글이 같은 쪽은 조각 비교 없이 건너뜀(가벼운 비교 먼저).
    조각 낱말의 COVER_MIN 이상이 대표 쪽에 있으면 같은 내용(그 조각과 드문 낱말을 가장 많이 함께 가진 대표 조각을
    맞은 자리로 기억), 아니면 바로 앞에 맞은 대표 조각 뒤(없으면 그 쪽 첫머리)에 끼운다. 비교 전 \\r\\n → \\n."""
    text = rep.get("text") or ""
    otext = (other or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip() or not otext.strip():
        return 0
    rb, ob = _blocks(text), _blocks(otext)
    same_pages = text.count("\f") == otext.count("\f")
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\f"]
    r_pages, o_pages = text.split("\f"), otext.split("\f")
    inserts: dict = {}  # 대표 본문 위치 → 끼울 조각들(순서대로)
    for p in range(len(r_pages)) if same_pages else [None]:
        if p is None:
            rs, os_ = rb, ob
            same = "".join(text.split()) == "".join(otext.split())
        else:
            rs, os_ = [b for b in rb if b[2] == p], [b for b in ob if b[2] == p]
            same = "".join(r_pages[p].split()) == "".join(o_pages[p].split())
        if same:
            continue
        have: Counter = Counter()
        post: dict = {}  # 낱말 → 그 낱말이 있는 대표 조각 번호(rs 안)
        for i, (s, e, _) in enumerate(rs):
            ws = _words(text[s:e])
            have.update(ws)
            for w in set(ws):
                post.setdefault(w, []).append(i)
        last = None
        for s, e, _ in os_:
            seg = otext[s:e].strip()
            c = Counter(_words(seg))
            n = sum(c.values())
            if n and sum(min(k, have[w]) for w, k in c.items()) >= COVER_MIN * n:
                votes = Counter(i for w in sorted((w for w in c if w in post), key=lambda w: len(post[w]))[:5] for i in post[w])
                if votes:
                    last = max(votes, key=lambda i: (votes[i], -abs(i - (last or 0))))
                continue
            at = rs[last][1] if last is not None else (rs[0][0] if rs else starts[p or 0])
            inserts.setdefault(at, []).append(seg)
    for at in sorted(inserts, reverse=True):
        segs = inserts[at]
        before = any(b[1] == at for b in rb)  # 대표 조각 끝 = 그 뒤에 / 아니면(쪽 첫머리) 그 앞에
        add = "".join("\n\n" + s for s in segs) if before else "".join(s + "\n\n" for s in segs)
        text = text[:at] + add + text[at:]
    rep["text"] = text
    return sum(len(v) for v in inserts.values())


def row_key(f):
    """보충 사실 중복 판정 키 = 정규화한 행 라벨(쉼표·공백·대소문자 무시). 대표에 이미 있는 행은 다른 엔진 값으로 다시 넣지 않음
    (대표 우선) — '1,000'/'1000'·'A-1 '/'A-1'처럼 표기만 다른 같은 행이 따로 들어가지 않게.
    라벨 없는 사실은 값 전체로."""
    from common.core.text import normalize_value

    label = (f.get("context") or [""])[0]
    return ("row", normalize_value(label)) if label.strip() else ("value", normalize_value(f.get("value") or ""))


def fix_tables(rep, texts=()):
    """표 머리글 보정(결정적, LLM 없음) — 집계(수량 열 합계)가 머리글로 열을 찾기 때문.
    (1) 공통 계약(_common/contract._table_facts)은 숫자 없는 첫 행(머리글)을 사실에서 버린다 → 표 텍스트에서
        첫 데이터 행 라벨 앞부분을 머리글로 되살린다. 칸 나눔은 대표·다른 후보 본문(texts)에서 '|'·탭으로 칸이 나뉜 같은
        머리글 줄을 먼저 쓰고('Unit Price'처럼 칸 안 공백), 없으면 공백으로 나눈 칸 수 = 표 열 수일 때만.
    (2) 구조 사실이 없는 문서(kreuzberg .doc 등)는 본문의 탭 표(칸 = 탭, 행 = 탭 두 개)를 행·셀 사실로 만든다.
    → 고친 수 {"headers": n, "tab_rows": m}"""
    import re

    facts, n_h, n_t = rep.setdefault("facts", []), 0, 0
    for t in rep.get("tables") or []:
        text, cols = t.get("text") or "", t.get("cols") or 0
        for i, f in enumerate(facts):
            row = (f.get("context") or [""])[0]
            if f.get("header") or not f.get("cells") or not row or row not in text:
                continue
            hs = " ".join(text[: text.index(row)].split())
            hdr = next(
                (
                    cs
                    for t2 in (rep.get("text") or "", *texts)
                    for ln in t2.splitlines()
                    for cs in [[c.strip() for c in re.split(r"\||	", ln) if c.strip()]]
                    if len(cs) == cols and " ".join(cs) == hs
                ),
                hs.split(),
            )
            if len(hdr) == cols == len(f["cells"]) + 1 and not any(re.search(r"\d", h) for h in hdr):
                facts.insert(i, {"value": " ".join(hdr[1:]), "context": [hdr[0]], "cells": hdr[1:], "header": True, "from": "rep-fix"})
                n_h += 1
            break
    if not any(f.get("cells") for f in facts):
        for ln in (rep.get("text") or "").splitlines():
            rows = [r.split("\t") for r in re.split(r"\t{2,}", ln.strip("\t")) if r.strip()]
            if len(rows) < 2 or len(rows[0]) < 3 or any(re.search(r"\d", c) for c in rows[0]):
                continue
            hdr = rows[0]
            facts.append({"value": " ".join(hdr[1:]), "context": [hdr[0]], "cells": hdr[1:], "header": True, "from": "rep-fix"})
            for r in rows[1:]:
                if len(r) == len(hdr):
                    facts.append({"value": " ".join(r[1:]), "context": [r[0]], "cells": r[1:], "from": "rep-fix"})
                    n_t += 1
    return {"headers": n_h, "tab_rows": n_t}


def standardize_rep(d):
    """본문·facts·표 칸의 기호·첨자 표기를 통일(standardize_text) — 엔진 묶음 직후·융합 전, 대표 결과(_rep)에만.
    바뀐 조각 수를 돌려준다(rep.rep.standardize)."""
    from pipeline.transform.represent.text_normalize import standardize_text as _std

    n = 0
    if d.get("text"):
        new = _std(d["text"])
        n += new != d["text"]
        d["text"] = new
    for t in d.get("tables") or []:
        if t.get("text"):
            new = _std(t["text"])
            n += new != t["text"]
            t["text"] = new
    for f in d.get("facts") or []:
        if f.get("value"):
            f["value"] = _std(f["value"])
        if f.get("context"):
            f["context"] = [_std(c) for c in f["context"]]
        if f.get("cells"):
            f["cells"] = [_std(c) for c in f["cells"]]
    return n


# reason='hidden' 쪽: 숨은 층과 쪽 VLM 글의 일치도(2-gram Jaccard)가 이 이상이면 '검색 가능 스캔 PDF'로 보고 원래 글 유지
HIDDEN_AGREE_MIN = 0.6
# 정규화한 글이 이보다 짧으면 일치도 판단 불가 → 원래 글 유지. 30이면 실제 쓰레기 숨은 층(29자)을 못 거르므로 20
HIDDEN_AGREE_MIN_LEN = 20


def _norm_agree(text):
    """일치도 비교 전 정규화: canon_symbols(기호·대시·특수공백·전각→반각) →
    common.core.text.normalize_value(NFKC·소문자·제로폭 제거·숫자 사이 쉼표 제거·공백 전부 제거) → 숫자 사이 마침표도
    추가로 제거(430,000·430.000·430000이 전부 같아지게 — OCR이 천단위 구분자를 다르게 읽는 경우가 흔함)."""
    import re

    from common.core.text import normalize_value
    from pipeline.transform.represent.text_normalize import canon_symbols

    return re.sub(r"(?<=\d)\.(?=\d)", "", normalize_value(canon_symbols(text or "")))


def _char_ngrams(s, n=2):
    return {s[i : i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def _page_agreement(text_a, text_b, min_len=HIDDEN_AGREE_MIN_LEN):
    """두 글의 일치도: 정규화(_norm_agree) 후 글자 2-gram Jaccard(공백·표기·대소문자
    차이·OCR 오타 1~2자에 강함 — 어순이 섞이는 토큰 비교보다 붙여쓰기·구분자 차이에 안정적). 숨은 글자층이 OCR과
    '같은 내용을 옮긴 것'인지(검색 가능 스캔 PDF) 보는 용도. min_len(기본 HIDDEN_AGREE_MIN_LEN —
    쪽 전체가 아니라 국소(겹친 숨은 글자 상자 주변)만 비교할 때는 원래 짧으므로 더 작은 값을 넘겨 쓴다).
    정규화한 글이 둘 중 하나라도 min_len보다 짧으면(짧은 조각 몇 개로 우연히 갈릴 수 있어 판단 불안정)
    None(호출부가 "애매하면 원래 글 유지"로 처리 — 안 덮는 쪽이 정답률을 더 보호)."""
    a, b = _norm_agree(text_a), _norm_agree(text_b)
    if min(len(a), len(b)) < min_len:
        return None
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    return round(len(ga & gb) / len(ga | gb), 4)


def _page_texts(base, doc_path, boxes):
    """base를 실제 쪽 번호별 글로 나눈다:
    1) boxes(엔진 출력의 rep["boxes"] — OCR 엔진만, 박스마다 실제 "page" 번호) 있으면 그걸로 그룹화한다.
       글자 0개(박스 없는) 빈 쪽은 그냥 키가 없을 뿐이라 뒤 쪽 번호가 안 밀린다.
    2) boxes가 없으면(OCR 아닌 엔진) \\f로 나누되, \\f 개수가 문서의 실제 쪽 수와 같을 때만 믿는다(빈 쪽이 없다는
       뜻). 다르면 쪽 번호를 확정할 수 없음 → None(호출부가 그 문서는 건너뛴다 — 틀린 쪽끼리 비교·치환하는
       것보다 안전한 쪽)."""
    if boxes:
        pages = {}
        for b in boxes:
            p = b.get("page")
            if p is None:
                continue
            pages.setdefault(p, []).append(b.get("text") or "")
        return {p: "\n".join(ts) for p, ts in pages.items()}
    if not base:
        return {}
    parts = base.split("\f")
    if len(parts) == 1:
        return {1: base}
    n_pages = doc_pages(doc_path)  # 실제 쪽 수 — \f 개수와 다르면 빈 쪽이 있어 쪽 번호를 못 믿음
    if n_pages is not None and len(parts) != n_pages:
        return None  # 쪽 번호 확정 불가 — 건너뜀
    return {i + 1: p for i, p in enumerate(parts)}


def fill_scan_pages(rep, dd, doc_path, page_vlm=None):
    """.pdf_text 대표 결과의 스캔 쪽(scan_pages_detail)만 쪽 VLM 글로 채운다(글자층 쪽은 그대로).
    page_vlm(scan_page_vlm.page_text_pages — 스캔 신호 쪽만 병렬 호출)의 글을 쓴다(기록 엔진 이름 "vlm_page"). 쪽 VLM 글이 없으면 채우지 않는다.
    쪽 경계는 _page_texts(boxes 있으면 그걸로, 없으면 \f 개수가 문서의 실제 쪽 수와 같을 때만) — 쪽 번호를 확정할 수 없으면 건너뛴다.
    쪽 단위 품질 검사 — 그 쪽 글의 garbage_ratio가 0.1을 넘으면 덮지 않고 건너뛴다(원래 글 유지) — page_skip에 기록.
    reason='hidden' — 그림과 같은 내용을 옮긴 숨은 글자층('검색 가능 스캔 PDF')은 원래 글과 쪽 VLM 글의 일치도(_page_agreement)가
    HIDDEN_AGREE_MIN 이상이거나 판단 불가(짧음)면 원래 글을 유지, 미만이면 쪽 VLM 글로 채운다.
    reason='hidden_overlap'(그림과 겹친 숨은 글자) — 쪽 VLM은 글자 상자가 없어 국소 확인을 못 하므로 늘 원래 글을 유지한다.
    반환: {"filled": {쪽(문자열): 엔진}, "skip": 이유 또는 None, "page_skip": {쪽: 이유}(있을 때만)} — 채울 스캔
    쪽이 없으면(형식이 .pdf_text 아님·스캔 쪽 없음) None."""
    if dd.get("format") != ".pdf_text" or not doc_path or not Path(doc_path).exists():
        return None
    from pipeline.transform.figures.scan_page_vlm import scan_pages_detail
    from pipeline.transform.represent.parse_scoring import garbage_ratio

    pages_detail = scan_pages_detail(doc_path)
    pages = list(pages_detail.keys())
    if not pages:
        return None
    vlm = {i: t for i, t, _ in page_vlm(doc_path) if (t or "").strip()} if page_vlm else {}
    if not vlm:
        return {"filled": {}, "skip": "쪽 VLM 글 없음"}
    base_pages = _page_texts(rep.get("text") or "", doc_path, rep.get("boxes"))
    if base_pages is None:
        return {"filled": {}, "skip": "대표 쪽 번호 확정 불가(\\f 개수 ≠ 문서 쪽 수, boxes 없음)"}
    filled, page_skip = {}, {}
    for p in pages:
        text = vlm.get(p, "")
        if not text.strip():
            continue
        if garbage_ratio(text) > 0.1:  # 깨진 글로 덮지 않음
            page_skip[p] = "쪽 VLM 글 품질 낮음(garbage_ratio > 0.1) — 원래 글 유지"
            continue
        if pages_detail.get(p) == "hidden":
            agree = _page_agreement(base_pages.get(p, ""), text)
            if agree is None:  # 정규화한 글이 너무 짧아 판단 불가 — 애매하면 원래 글 유지(정답률 보호)
                page_skip[p] = "hidden-agree(정규화한 글이 짧아 일치도 판단 불가) — 원래 글(숨은 층) 유지"
                continue
            if agree >= HIDDEN_AGREE_MIN:  # 검색 가능 스캔 PDF — 숨은 층이 이미 같은 내용 → 원래 글 유지
                page_skip[p] = f"hidden-agree(원래 글과 일치 {agree} ≥ {HIDDEN_AGREE_MIN}) — 원래 글(숨은 층) 유지"
                continue
        elif pages_detail.get(p) == "hidden_overlap":
            page_skip[p] = "hidden-overlap(쪽 VLM은 글자 상자가 없어 국소 확인 불가) — 원래 글(숨은 층) 유지"
            continue
        base_pages[p] = text
        filled[p] = "vlm_page"
    if not filled:
        out = {"filled": {}, "skip": None}
        if page_skip:
            out["page_skip"] = {str(p): r for p, r in page_skip.items()}
        return out
    n = max(base_pages)
    rep["text"] = "\f".join(base_pages.get(i, "") for i in range(1, n + 1))
    out = {"filled": {str(p): e for p, e in filled.items()}, "skip": None}
    if page_skip:
        out["page_skip"] = {str(p): r for p, r in page_skip.items()}
    return out


def status(r):
    """runs.jsonl 기록 하나 → 상태: 성공 · 시간 초과 · 환경(미설치·미설정 — env_error.is_env_error) · 실패."""
    e = r.get("error") or ""
    if not e:
        return "성공"
    if "Timeout" in e:
        return "시간 초과"
    if is_env_error(e):
        return "환경"
    return "실패"


def last_runs(parse_dir):
    """output/parse/runs.jsonl → {(문서, 엔진): 마지막 기록} — 이 엔진으로 이 문서를 돌렸는지·결과(나중에 고칠 때 근거)."""
    f = Path(parse_dir) / "runs.jsonl"
    last = {}
    for ln in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        if ln.strip():
            r = json.loads(ln)
            last[(r["doc"], r["engine"])] = r
    return last


def tried_of(doc, last, pd):
    """문서 하나의 엔진별 시도 기록 — 상태·phase·걸린 초·제한·시각·글자 수·오류·결과 파일(엔진별 결과는 output/parse/<엔진>/<문서>.json에 따로 남음).
    version(runs.jsonl의 engine_version)도 남겨 게시 engines_used()가 rep_json만 보고 엔진 판까지 알 수 있게."""
    return {
        eng: {
            "status": status(r),
            "phase": r.get("phase"),
            "sec": r.get("sec"),
            "limit": r.get("limit"),
            "at": r.get("at"),
            "chars": r.get("chars"),
            "sha": r.get("sha"),
            "error": (r.get("error") or "")[:200] or None,
            "version": r.get("engine_version"),
            "file": f"{eng}/{doc}.json" if (pd / eng / f"{doc}.json").exists() else None,
        }
        for (d, eng), r in sorted(last.items())
        if d == doc
    }


from common.core.artifacts import code_fp  # noqa: E402
from common.core.contract import source_record  # noqa: E402
from pipeline.shared import runtrace  # noqa: E402
from pipeline.transform.figures.chart_values import chart_text  # noqa: E402
from pipeline.transform.represent import table_inline  # noqa: E402


# 후보정 기능 — transform.represent.post_steps: 없음/"all" = 전부 · "none" = 꺼짐 · 콤마 목록("supsub,charts") = 그것만.
# "context"는 "figures" 없이는 효과 없음(그림 기록이 있어야 캡션·값 확인을 붙임).
def apply_post(rep, doc, doc_path, feats, out_images=None, figures_max=None, vp_pages=None, page_covered=False):
    """후보정 패키지 적용 — base 본문에 쪽 VLM 옮기기·차트·그림 기록 블록을 덧붙이고, 첨자(supsub)는 그 줄만 base 안에서
    바꿔 넣는다(본문이 두 배가 되지 않게). rep.post{config, features, code_fp, supsub(첨자 표기본 전체 — 색인에는 안 들어감)}를 남긴다.
    쌓는 순서: base, 쪽 VLM 글, 그림 기록(+근처 본문), 차트. PARSE_POST=none(feats 빔)이면 rep["text"] 그대로.
    out_images — 그림 PNG·index.jsonl이 쓰일 폴더(None = fig_mod.images_root()).
    figures_max — 그림 VLM 상한을 이번 호출만 바꿈(None = 설정 VLM_FIGURES_MAX).
    vp_pages — represent()가 이 문서에 한 번만 부른 쪽 VLM 결과(scan_fill과 같은 결과 — 실패한 쪽도 다시 안 부름, None이면 여기서 부름).
    page_covered — 이미지·스캔 문서를 VLM 엔진이 이미 쪽마다 옮김(쪽 VLM·쪽 전체 그림 VLM 생략)."""
    post_spec = pc.cfg().transform.represent.post  # 쓴 글자 그대로 기록(없으면 "all")
    info = {
        "config": post_spec if post_spec is not None else "all",
        "features": sorted(feats),
        "code_fp": code_fp("p1"),
        "figures": 0,
        "figures_capped": False,
        "vlm_page_calls": 0,
        "vlm_page_cached": 0,
        "attachments_parsed": 0,
        "attachments_cached": 0,
    }
    _pt = {
        "vlm_page": 0.0,
        "figures": 0.0,
        "charts": 0.0,
        "attachments": 0.0,
        "supsub": 0.0,
    }  # 기능별 소요(초)
    _pt0 = time.time()
    if not feats or not doc_path or not Path(doc_path).exists():
        return info
    from pipeline.transform.figures import figure_extract as fig_mod
    from pipeline.transform.figures import scan_page_vlm as vp_mod
    from pipeline.transform.represent import superscripts as supsub

    base = rep.get("text") or ""
    blocks = []
    doc_text = base  # 그림 근처 본문 언급(link_context) 검색 대상 — 쪽 VLM 옮기기 글자도 포함(스캔은 OCR 본문이 부실할 수 있어)
    if "vlm_page" in feats:
        # scan_fill이 쪽 VLM 글로 이미 채운 쪽은 덧붙이지 않음(같은 쪽이 본문에 두 번 — 호출은 캐시라 다시 안 감)
        sf = ((rep.get("rep") or {}).get("scan_fill") or {}).get("filled") or {}
        if vp_pages is None:
            vp_pages = vp_mod.page_text_pages(doc_path)
        vt = "\n".join(t for i, t, _ in vp_pages if t and sf.get(str(i)) != "vlm_page")
        provs = [pv for _, _, pv in vp_pages]
        if vt.strip():
            blocks.append(vt)
            doc_text = base + "\n" + vt
        info["vlm_page_calls"] = len(provs)
        info["vlm_page_cached"] = sum(1 for pv in provs if pv.get("cached"))
        from pipeline.transform.figures.pptx_render import pptx_slide_vlm  # pptx 아니면 즉시 []

        slides = pptx_slide_vlm(doc_path)
        if slides:
            pt = "\n".join(f"[슬라이드 {n}] {t}" for n, t, _pv in slides if t.strip())
            if pt.strip():
                blocks.append(pt)
                doc_text += "\n" + pt
            info["vlm_page_calls"] += len(slides)
            info["vlm_page_cached"] += sum(1 for _, _, pv in slides if pv.get("cached"))
        # 쪽 VLM 모델 이름 — 게시는 나중·다른 설정으로 돌 수 있어 rep에 남김
        page_models = sorted(
            {pv.get("model") for pv in provs if pv.get("model")}
            | ({pv.get("model") for _, _, pv in slides if pv.get("model")} if slides else set())
        )
        if page_models:
            info.setdefault("vlm_models", {})["page"] = "+".join(page_models)
    _pt["vlm_page"] = time.time() - _pt0
    _pt0 = time.time()
    if "figures" in feats:
        doc_sha = (rep.get("rep") or {}).get("source", {}).get("sha256") or fig_mod.sha(Path(doc_path).read_bytes())
        records, plain, enriched = fig_mod.build_records(
            doc, doc_path, doc_text, doc_sha, figures_max=figures_max, page_covered=page_covered
        )
        use_context = "context" in feats
        blocks += enriched if use_context else plain
        fig_mod.write_index(doc, records, out_images=out_images)
        info["figures"] = len(records)
        info["figures_capped"] = any(r.get("skipped") == "VLM_FIGURES_MAX" for r in records)  # 상한 걸린 문서 표시
        skips = [r["skipped"] for r in records if r.get("skipped")]  # 건너뜀 이유별 건수
        if skips:
            from collections import Counter as _Counter

            info["figures_skip_reasons"] = dict(_Counter(skips))
        # 그림 VLM 모델 이름(build_records가 채운 vlm.model)
        fig_models = sorted({(r.get("vlm") or {}).get("model") for r in records if (r.get("vlm") or {}).get("model")})
        if fig_models:
            info.setdefault("vlm_models", {})["figure"] = "+".join(fig_models)
    _pt["figures"] = time.time() - _pt0
    _pt0 = time.time()
    if "charts" in feats:
        ct = chart_text(doc_path)
        if ct.strip():
            blocks.append(ct)
    _pt["charts"] = time.time() - _pt0
    _pt0 = time.time()
    if "supsub" in feats:
        base, sup_full, n_unmatched = supsub.merge_supsub(base, doc_path)  # 줄만 바꿔 넣고 전체는 rep.post에 따로
        if sup_full.strip():
            info["supsub"] = sup_full
            info["supsub_unmatched"] = n_unmatched
    _pt["supsub"] = time.time() - _pt0
    _pt0 = time.time()
    if "attachments" in feats:
        from pipeline.transform.represent import mail_attachments as att_mod

        base, att_blocks, att_stats = att_mod.mail_blocks(doc_path, base)  # base — 오피스 개체 자리 표시만 더함(pl-63)
        blocks += att_blocks
        info["attachments_parsed"] = att_stats["parsed"]
        info["attachments_cached"] = att_stats["cached"]
    _pt["attachments"] = time.time() - _pt0
    info["post_times"] = {k: round(v, 2) for k, v in _pt.items()}
    rep["text"] = base + "\n\n" + "\n\n".join(blocks) if blocks else base
    return info


IMAGE_TYPES = IMG_EXTS | {".pdf_image"}  # 형식 키(qa.json format — parse_engines.doc_types)


def _vlm_transcribed(rep, dd):
    """이미지·스캔 형식(.pdf_image 포함) 문서의 대표가 VLM 엔진(parse_engines.VLM_ENGINES)이고
    본문이 비어 있지 않음 = 쪽을 이미 VLM으로 옮김. OCR 엔진이 대표거나 VLM 글이 비면 False(쪽 VLM을 막지 않음)."""
    from pipeline.transform.parse.parse_engines import VLM_ENGINES

    return dd.get("format") in IMAGE_TYPES and (rep.get("rep") or {}).get("engine") in VLM_ENGINES and bool((rep.get("text") or "").strip())


def _current_sha16(doc, last):
    """runs.jsonl(last_runs) 중 이 문서의 가장 최근 시도 기록의 sha(앞 16자) — 없으면 None.
    엔진 여럿이 다른 때 시도됐어도 '가장 최근' 한 번이 그때 파일 내용을 반영."""
    recs = [r for (d, _e), r in last.items() if d == doc and r.get("sha")]
    if not recs:
        return None
    return max(recs, key=lambda r: r.get("at") or "")["sha"]


def _old_source(out_dir, doc):
    """원본이 이 서버에 없을 때(Object Storage에서 받아 처리 후 지움) — 이전 대표 결과의 rep.source를 그대로(문서 ID·원본 위치가 끊기지 않게)."""
    f = Path(out_dir) / f"{doc}.json"
    try:
        return (json.loads(f.read_text(encoding="utf-8")).get("rep") or {}).get("source") if f.exists() else None
    except (OSError, ValueError):
        return None


def represent(stack, parse_dir, src=None):
    from pipeline.transform.represent.parse_scoring import LOW_N, doc_accuracy

    pd = Path(parse_dir)
    qa = json.loads((pd / "qa.json").read_text(encoding="utf-8"))
    out_dir = pd / "_rep"
    out_dir.mkdir(parents=True, exist_ok=True)
    index, last = [], last_runs(pd)
    side: dict = {}  # 문서 → (stage_times, 본문·facts sha) — 끝에서 _rep/<문서>.json을 다시 읽지 않게

    feats = pc.active_features()  # PARSE_POST(기본 all)

    def _doc_one(_pair):
        """문서 1개 → index 행(정상 대표·이전 결과 재사용·성공 엔진 없음)."""
        doc, dd = _pair
        want = stack["parse"].get(dd["format"], [])
        cands = [
            {
                "engine": e,
                "ok": bool((dd["engines"].get(e) or {}).get("ok")),
                "acc": doc_accuracy(dd["engines"][e], dd.get("ref")) if e in dd["engines"] else None,
            }
            for e in want
        ]
        ok = [c for c in cands if c["ok"]]
        fallback = False
        if not ok:  # 스택 엔진 전부 실패 → 성공한 다른 엔진(정확도 순)
            ok = sorted(
                ({"engine": e, "ok": True, "acc": doc_accuracy(m, dd.get("ref"))} for e, m in dd["engines"].items() if m.get("ok")),
                key=lambda c: -(c["acc"] or 0),
            )
            fallback = bool(ok)
        if not ok:
            prev = out_dir / f"{doc}.json"
            if prev.exists():
                # 엔진별 중간 결과를 지운 뒤라도 전에 만든 대표 결과를 그대로 올림("성공한 엔진 없음"으로 덮지 않게).
                # 같은 이름의 '다른' 문서(내용이 바뀜)일 수 있으니 sha로 확인 — 다르면 보존 안 함.
                try:
                    old = json.loads(prev.read_text(encoding="utf-8"))
                    old_rep = old.get("rep") or {}
                    SP.result_current("reused")
                    old_sha = (old_rep.get("source") or {}).get("sha256")  # 64자 — runs.jsonl(last)의 sha는 앞 16자
                    cur_sha = _current_sha16(doc, last)
                    if old_sha and cur_sha and old_sha[:16] == cur_sha:
                        side[doc] = (old_rep.get("stage_times", {}), _content(doc, old))
                        return {
                            "doc": doc,
                            "format": dd["format"],
                            "pages": old_rep.get("pages"),
                            **{k: old_rep.get(k) for k in ("engine", "acc", "fallback", "facts_added", "low_n")},
                            "tried": old_rep.get("tried") or tried_of(doc, last, pd),
                            "doc_key": (old_rep.get("source") or {}).get("doc_key"),
                            "uri": (old_rep.get("source") or {}).get("uri"),
                            "chars": len(old.get("text") or ""),
                            "figures_capped": (old.get("post") or {}).get("figures_capped", False),
                        }
                except (OSError, ValueError):
                    pass  # 못 읽으면 아래 일반 경로로(성공한 엔진 없음)
            return {
                "doc": doc,
                "format": dd["format"],
                "engine": None,
                "candidates": cands,
                "fallback": False,
                "reason": "성공한 엔진 없음",
                "tried": tried_of(doc, last, pd),
            }
        _t = {"load": 0.0, "merge": 0.0, "scanfill": 0.0, "post": 0.0, "table": 0.0}
        _t0 = time.time()
        # PARSE_REP_SELECT: first(첫 성공 엔진·파일 읽기 0) | acc(정확도만·파일 읽기 0) | best(정확도+풍부도, 기본)
        _sel = pc.cfg().transform.represent.rep_select or ""
        if _sel == "first":
            best = max(ok, key=lambda c: -ok.index(c))  # 스택 순서 첫 성공 — 교차 재현율·richness 파일 읽기 없음
        elif _sel == "acc":
            best = max(ok, key=lambda c: ((c["acc"] if c["acc"] is not None else -1), -ok.index(c)))
        else:
            best = _select_best(ok, pd, doc)
        rep = json.loads((pd / best["engine"] / f"{doc}.json").read_text(encoding="utf-8"))
        _t["load"] = time.time() - _t0
        _t0 = time.time()
        std_n = standardize_rep(rep)  # 엔진 묶음 직후·병합 전
        other_docs = {}  # {엔진: 그 엔진 원본 결과}(table_inline 입력)
        have = {row_key(f) for f in rep.get("facts") or []}
        _t["load"] += time.time() - _t0
        _t0 = time.time()
        texts = []  # 다른 후보 본문 — 교차 병합·표 머리글 칸 나눔 규칙(fix_tables) 근거
        added = 0
        for c in ok:
            if c is best:
                continue
            f = pd / c["engine"] / f"{doc}.json"
            if not f.exists():
                continue
            other = json.loads(f.read_text(encoding="utf-8"))
            other_docs[c["engine"]] = other  # 아래서 제자리 표준화된 뒤의 값을 가짐(의도)
            std_n += standardize_rep(other)
            texts.append(other.get("text") or "")
            for fact in other.get("facts") or []:
                k = row_key(fact)
                if k not in have:
                    have.add(k)
                    rep.setdefault("facts", []).append({**fact, "from": c["engine"]})
                    added += 1
        # 교차 병합 — 대표 본문은 그대로, 다른 엔진에만 있는 조각을 맞은 자리 뒤에 끼움(엔진 하나면 그대로)
        merged = {e: cross_merge(rep, od.get("text")) for e, od in other_docs.items()}
        _t["merge"] = time.time() - _t0
        _t0 = time.time()
        n_ok = sum(1 for m in dd["engines"].values() if m.get("ok"))
        rep["rep"] = {
            "engine": best["engine"],
            "acc": best["acc"],
            "candidates": cands,
            "fallback": fallback,
            "tried": tried_of(doc, last, pd),  # 어떤 엔진으로 돌렸고 결과가 어땠는지 — 다시 파싱·대표 바꿀 때 근거
            "source": source_record(src, doc) or _old_source(out_dir, doc),  # Object Storage 원본을 지운 뒤에도 이전 기록 유지
            "format": dd["format"],
            "pages": dd.get("pages"),
            "meta": {},  # 인계 계약 칸(contract.REP_KEYS) — 내용은 없음(교차 확인은 pl-67에 지움)
            "facts_added": added,
            "table_fix": fix_tables(rep, texts),
            "low_n": n_ok <= LOW_N or (dd.get("n_fam", 9) <= LOW_N and dd.get("ref") not in ("truth", "answer_key")),
            "merge": merged,  # 엔진별 끼운 조각 수(교차 병합)
            "standardize": {"on": True, "changed": std_n},
        }  # standardize.on은 늘 True(형식 유지)
        source = rep["rep"]["source"]
        doc_path = Path(source["path"]) if source else None
        # 쪽 VLM은 PARSE_POST에 vlm_page가 있을 때만, 문서당 한 번만.
        # 이미지·스캔 문서를 VLM 엔진이 이미 옮겼으면 쪽 VLM을 안 부르고 쪽 전체 그림 VLM도 생략(쪽마다 VLM 한 번)
        # covered는 vlm_page 기능과 무관하게(그림 VLM 생략에도 씀 — run_pipeline light 레인처럼 vlm_page 없이 figures만 켠 경우)
        covered, vp_pages = _vlm_transcribed(rep, dd), None
        if "vlm_page" in feats and doc_path and Path(doc_path).exists():
            from pipeline.transform.figures import scan_page_vlm as vp_mod

            vp_pages = [] if covered else vp_mod.page_text_pages(doc_path)
        # .pdf_text 대표의 스캔 쪽만 쪽 VLM 글로 채움(apply_post 전, 후보정이 채운 본문을 기준으로 돌게)
        fill = fill_scan_pages(rep, dd, doc_path, page_vlm=(lambda _p: vp_pages) if vp_pages is not None else None)
        if fill is not None:
            rep["rep"]["scan_fill"] = fill
        _t["scanfill"] = time.time() - _t0
        _t0 = time.time()
        with SP.span("transform.figures", doc_id=doc, ext=Path(doc).suffix.lower()):  # 쪽 VLM·그림 VLM/OCR 호출 지표가 이 span에
            rep["post"] = apply_post(rep, doc, doc_path, feats, vp_pages=vp_pages, page_covered=covered)
        _t["post"] = time.time() - _t0
        _t0 = time.time()
        # apply_post·scan_fill 뒤, 즉 내보낼 rep["text"]가 다 정해진 뒤에 부른다:
        # table_inline이 찾는 표 자리(span)는 이 최종 본문 기준이어야 맞다(더 일찍 부르면 scan_fill이 쪽 전체를 OCR
        # 글로 갈아치울 수 있어 자리가 어긋날 수 있음 — 그때는 그냥 못 찾은 걸로 남고 본문은 안 바뀜, 안전).
        rep["rep"]["table_inline"] = table_inline.inline_tables(rep, best["engine"], other_docs)  # rep["text"]도 바꿈
        _t["table"] = time.time() - _t0
        _t0 = time.time()
        rep["rep"]["stage_times"] = {k: round(v, 2) for k, v in _t.items()}  # 단계별 소요(초)
        SP.add_current(stage_s=rep["rep"]["stage_times"])  # 같은 값을 span.metrics에도
        _pdt = (rep.get("post") or {}).get("post_times") or {}
        _pdetail = (
            " | post["
            + " ".join(f"{k}={_pdt[k]:.1f}s" for k in ("vlm_page", "figures", "charts", "attachments", "supsub") if k in _pdt)
            + "]"
            if _pdt
            else ""
        )
        print(
            f"[represent] {doc[:50]:50s} "
            + " ".join(f"{k}={_t[k]:.1f}s" for k in ("load", "merge", "scanfill", "post", "table"))
            + _pdetail,
            flush=True,
        )
        (out_dir / f"{doc}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        side[doc] = (rep["rep"]["stage_times"], _content(doc, rep))
        return {
            "doc": doc,
            "format": dd["format"],
            "pages": dd.get("pages"),
            **{k: rep["rep"][k] for k in ("engine", "acc", "fallback", "facts_added", "low_n", "tried")},
            "doc_key": (rep["rep"]["source"] or {}).get("doc_key"),
            "uri": (rep["rep"]["source"] or {}).get("uri"),
            "chars": len(rep.get("text") or ""),
            "figures_capped": rep["post"].get("figures_capped", False),
        }

    _done = [0]

    def _doc_traced(_pair):
        """문서 1개 = transform.represent span 1행 — 단계별 시간·모델 호출 지표는 span.metrics에."""
        _doc, _dd = _pair
        with SP.span("transform.represent", doc_id=_doc, ext=Path(_doc).suffix.lower(), cpu=_par == 1) as _sp:
            _r = _doc_one(_pair)
            if not _r.get("engine"):
                _sp.result("fail", "doc", SP.safe(_r.get("reason")))
            _sp.add(pages=_dd.get("pages"), format=_dd.get("format"))
            _done[0] += 1
            return _r

    _pairs = sorted(qa["docs"].items())
    _par = max(1, pc.cfg().extract.doc_parallel)  # 문서 병렬(기본 1 = 순차)
    with runtrace.Progress(total=len(_pairs), done=lambda: _done[0], unit="doc"):  # 60초마다 run.progress
        if _par > 1:
            import concurrent.futures as _cf  # 문서간 병렬 — ex.map 회수는 제출 순서라 index·engines.csv 순서 불변

            with _cf.ThreadPoolExecutor(max_workers=_par) as _ex:
                index.extend(_ex.map(SP.carry(_doc_traced), _pairs))
        else:
            index.extend(map(_doc_traced, _pairs))
    with (out_dir / "sources.jsonl").open("w", encoding="utf-8") as f:  # 문서 ID ↔ 원본 위치 표(인계용 — 검색 결과에서 원본 찾기)
        for r in index:
            if r.get("doc_key"):
                f.write(
                    json.dumps({"doc_key": r["doc_key"], "uri": r["uri"], "file_name": r["doc"], "engine": r["engine"]}, ensure_ascii=False)
                    + "\n"
                )
    engines = sorted({e for r in index for e in r["tried"]})
    import csv

    with (out_dir / "engines.csv").open("w", encoding="utf-8-sig", newline="") as f:  # 문서 × 엔진 시도 표(엑셀) — 대표 = ★
        w = csv.writer(f)
        w.writerow(["문서", "형식", "대표 엔진", *engines])
        for r in index:
            w.writerow(
                [
                    r["doc"],
                    r["format"],
                    r["engine"] or "(없음)",
                    *[
                        ("★" if e == r["engine"] else "")
                        + (f"{r['tried'][e]['status']}(p{r['tried'][e]['phase'] or '-'})" if e in r["tried"] else "")
                        for e in engines
                    ],
                ]
            )
    done = [r["doc"] for r in index if r.get("engine")]
    digest = _digest(json.loads(json.dumps(index)), [side[d][1] for d in done])  # 파일에서 읽은 것과 같은 값으로(JSON 왕복)
    (out_dir / "index.json").write_text(
        json.dumps({"stack": stack.get("name"), "docs": index, "digest": digest}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _times = [side[d][0] for d in done]
    _agg = {k: round(sum(t.get(k, 0) for t in _times), 1) for k in ("load", "merge", "scanfill", "post", "table")}
    print(
        "[represent] 단계별 누적: " + " ".join(f"{k}={_agg[k]:.0f}s" for k in ("load", "merge", "scanfill", "post", "table")),
        flush=True,
    )
    return index


def _content(doc, rep):
    """digest의 문서 하나 몫 — 길이·개수가 같은 내용 교체도 잡게 본문·facts의 sha256(facts는 파일에서 읽은 것과 같게 JSON 왕복)."""
    facts = json.loads(json.dumps(rep.get("facts") or [], ensure_ascii=False))
    return {
        "doc": doc,
        "text_sha": hashlib.sha256((rep.get("text") or "").encode("utf-8")).hexdigest(),
        "facts_sha": hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }


def _digest(index, content):
    """대표 결과 digest — index 행(시도 기록 tried는 시각이라 뺌) + 대표 결과가 있는 문서의 _content 목록(index 순서)."""
    core = [{k: v for k, v in r.items() if k != "tried"} for r in index]
    return hashlib.sha256(json.dumps({"core": core, "content": content}, sort_keys=True).encode()).hexdigest()[:16]


def rep_digest(parse_dir):
    """(index.json 문서 목록, 대표 결과 digest) — 파싱 끝 표시(_DONE.json)가 바뀌었는지 가르는 값. digest는 represent()가
    문서를 쓸 때 메모리에서 계산해 index.json에 넣어 둔 것(_rep/<문서>.json을 다시 읽지 않음)."""
    idx = json.loads((Path(parse_dir) / "_rep" / "index.json").read_text(encoding="utf-8"))
    return idx["docs"], idx["digest"]


def write_mark(parse_dir, **kw):
    """파싱 끝 표시 _rep/_DONE.json — 앞 표시와 digest(kw — rep_digest 값)·인계 형식 버전(CONTRACT)이 같으면 그대로 두고 False(구조화는 건너뛰게 됨),
    다르면 common 코드 지문(FINGERPRINT)과 함께 새로 쓰고 True. kw의 run_id가 있으면 그 값(같은 실행의 parse_engines와 같은 id)."""
    from common import CONTRACT, FINGERPRINT  # 인계 형식 버전 · common 코드 지문(이미지 버전 어긋남 확인)

    f = Path(parse_dir) / "_rep" / "_DONE.json"
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if old.get("digest") == kw.get("digest") and old.get("contract") == CONTRACT:
        print(f"[parse] 대표 결과 변화 없음 — 끝 표시 그대로(run_id {old['run_id']}), 구조화는 건너뛰게 됨", flush=True)
        return False
    m = {
        "module": "parse",
        "contract": CONTRACT,
        "common": FINGERPRINT,
        "run_id": time.strftime("%Y%m%d-%H%M%S"),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **kw,
    }
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[parse] 끝 표시 → {f} (run_id {m['run_id']})", flush=True)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default=None, help="엔진 구성 파일(PC 실험·시험용 — 비우면 resources/config/pipeline_stack.json)")
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", default=None, help="파싱한 문서 폴더(원본 경로·sha256을 대표 결과에 남김 — 구조화 모듈이 원본 없이 돌 때 씀)")
    a = ap.parse_args(argv)
    idx = represent(json.loads(Path(a.stack).read_text(encoding="utf-8")) if a.stack else pc.stack(), a.parse_dir, a.src)
    done = [r for r in idx if r["engine"]]
    from collections import Counter

    c = Counter(r["engine"] for r in done)
    line = (
        f"대표 파싱 {len(done)}/{len(idx)}문서 · 엔진 "
        + ", ".join(f"{e} {n}" for e, n in c.most_common())
        + f" · 스택 밖 대체 {sum(r['fallback'] for r in done)} · 모수 적음 {sum(r['low_n'] for r in done)} · 실패 {len(idx) - len(done)}"
        + f" · 그림 상한 걸린 문서 {sum(1 for r in idx if r.get('figures_capped'))}건"
    )
    print(line + f" → {Path(a.parse_dir) / '_rep'}")


if __name__ == "__main__":
    import sys

    utf8_stdout()
    with runtrace.run("represent", sys.argv[1:]):  # 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
