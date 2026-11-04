#!/usr/bin/env python3
"""대표 파싱 결과 — 고정 기술 스택(stack.json `parse`)의 엔진 결과만 모아 문서마다 하나로 → output/parse/_rep/<문서>.json

문서마다:
  후보 = 스택이 그 형식에 지정한 엔진 중 파싱에 성공한 것(15자+, parse_qa ok)
  대표 = 후보 중 정확도(pipeline.transform.represent.rep_accuracy.doc_accuracy — 정답 없으면 교차 재현율, AG11 2단계 착수 조건으로 parse_qa에서 옮김)가 가장 높은 것, 같으면 스택 순서
  추합 = 대표 본문 + 다른 후보의 구조 사실(표 행·키-값, 대표에 없는 것만) · OCR 글자 상자는 대표 것만(위치가 대표 본문과 맞아야 함)
  후보가 하나도 성공 못 하면 스택 밖 성공 엔진으로 대체하고 표시(fallback) — 빠진 문서가 생기지 않게
아래 단계는 늘 켬(되돌리기 스위치 PARSE_STANDARDIZE·SCAN_FILL·CONTEXT·TABLE_INLINE·TABLE_STD·FUSE·MERGE_PAGES는 op-08에 지움):
표준화 — 엔진 묶음 직후·융합 전에 기호 맵·첨자 표기
  (common.core.text.standardize_text)를 본문·facts·표 칸에 적용(SI20·AD46⑤, 표 칸 재현율 저하 원인인 기호 정형화
  부재를 산출 쪽에서 메움). rep.rep.standardize에 바뀐 조각 수 표시, 원문은 output/parse/<엔진>/ 그대로.
스캔 쪽 채움 — PE1 후속(2026-10-07, 정답률 1순위): .pdf_text 대표 문서 안에 스캔 쪽
  (pipeline.transform.figures.scan_page_vlm.scan_pages_detail — reason chars/hidden/garbage/hidden_overlap, AD31·AD47)이 있고 그 쪽의 OCR 엔진
  (.pdf_image 계열, stack.json 순서) 결과가 있으면 그 쪽만 대표 본문을 OCR 쪽 글로 채운다(글자층 쪽은 그대로) —
  기존 한계(대표가 .pdf_text 엔진이면 스캔 쪽 값이 아예 안 들어가던 것, backlog PE1 "후속 과제"). 쪽 경계는
  _page_texts(boxes 있으면 그걸로, 없으면 \f 개수가 문서 실제 쪽 수와 맞을 때만) — 쪽 번호를
  확정할 수 없으면 건너뜀(rep.rep.scan_fill.skip에 기록, 바이트 불변). 그 쪽 OCR 글이 깨져 있으면(garbage_ratio
  > 0.1, 즉 OCR 신뢰도 0.9 미만) 그 쪽도 안 덮고 건너뜀 · reason='hidden'(검색 가능 스캔 PDF 포함)은 원래
  글(숨은 글자층)과 OCR 글의 일치도(HIDDEN_AGREE_MIN)가 높으면 원래 글을 유지(독립 검토 MAJOR, AD31) — 모두
  rep.rep.scan_fill.page_skip에 기록.
맥락 기록 — PA0(2026-10-08): 이미 계산된 문서·쪽 신호
  (pipeline.transform.represent.decision_log)를 rep["context"]·규칙 결정과 이유를 rep["decisions"]로 남긴다(새 엔진 실행·VLM 호출
  없음, 나중 파싱 에이전트 PA2의 바탕).
표 제자리 넣기 — TA1(사용자 10-15): 대표 엔진 하나의 표만 쓰던 것을, 이 문서를
  표로 인식한 엔진 전부(대표 + other_docs)의 그리드를 모아(pipeline.transform.represent.table_inline) 표 자리마다
  가장 구조가 완전한(칸 채움 비율·다른 엔진과의 칸 글자 일치도) 것 하나를 고르고, 대표 본문(rep["text"]) 안
  그 표가 있던 자리를 찾아(순서 보존 보수적 매칭 — 못 찾으면 안 건드림) 그 자리에 GitHub 표로 바꿔 넣는다.
  rep["tables_std"]도 이 고른 그리드들로 다시 만들어(기존 table_std.build_tables 형식 그대로) 자리를 찾아
  넣은 표는 inline:true로 표시(parsing_meta.render_md가 끝에 또 붙이지 않게) — 못 찾은 표는 inline:false로
  그대로 끝에 붙는다. 교체 영역 안 두 칸 사이에 낀 짧은 글(각주·캡션 등, GAP_MAX_CHARS 안)은 지우지 않고
  표 바로 뒤에 원래 순서대로 남긴다(독립 검토 engine-qa 10-21 반영) — rep["rep"]["table_inline"]에 묶음
  수·넣은 수·못 찾은 수·고른 그리드의 엔진별 건수·남긴 각주 수(residue)를 남긴다.
산출 형식 = 엔진 공통 출력 계약(text·tables·facts·boxes) + "rep": {engine, candidates[{engine, ok, acc}], fallback, low_n}
→ modules/structure/bundle.py가 이것만 읽어 청킹·벡터화·그래프(데이터 구조화)를 한다. 목록 = output/parse/_rep/index.json
AD25(b)(c) — fuse_mod(AD29 P1)이 찾은, 같은 표 행(자리)에서 값은 같은데 표기가 갈린 엔진들의 충돌을 문서마다
_rep/<문서>.json["fused"]["conflicts"]에만 담던 것을 _rep/conflicts.jsonl(문서별 한 줄: {doc, conflicts})로도
모은다 — 자리=행 라벨 · 엔진별 원문 표기(losers[].text)·계열 수(engines 길이)는 fuse_mod.vote_fragment가 이미
계산(판정은 AD26 몫, 여기는 표시만). 쪽·줄·OCR 상자 좌표 자리(자유 문장 숫자)는 범위 밖(parse_qa 토큰 충돌,
meta.json["token_conflicts"]은 문서 전체 기준 — 자리 없음, 그대로).
사용: python modules/parse/represent.py [--stack stack.json] [--parse-dir output/parse]
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from common.core import span as SP  # op-01 성능 span
from common.core.console import utf8_stdout
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.ext_groups import IMG_EXTS


def load_stack(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"{p} 없음 — --stack에 엔진 구성 파일 경로(resources/config/pipeline_stack.json 모양)")
    return json.loads(p.read_text(encoding="utf-8"))


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


def _para_has_structure(para):
    """문단에 표(마크다운 표 패턴) 또는 그림 표식이 포함되어 있는지."""
    stripped = para.strip()
    if not stripped:
        return False
    # 표 패턴: 연속된 | 줄 (2줄 이상)
    lines = stripped.split("\n")
    pipe_lines = [ln for ln in lines if "|" in ln and ln.count("|") >= 1]
    has_table = len(pipe_lines) >= 2 or any("|" in ln and ("---" in ln or "─" in ln) for ln in lines)
    # 그림 패턴: [그림 ...] 또는 ![]( 표식
    has_figure = "[그림" in stripped or "![" in stripped
    return has_table or has_figure


def _merge_paragraphs(rep_text, other_texts, other_docs=None):
    """문단별 조각 보정 — 대표 본문의 각 문단을 다른 엔진의 같은 위치 문단과 비교.
    우선순위:
      1) 대표 문단에 구조(표/이미지)가 없는데 다른 엔진에는 있으면 → 무조건 교체
      2) 양쪽 모두 구조가 있으면 → 더 풍부한 엔진(표/이미지를 더 많이 인식한 엔진) 우선
      3) 구조가 양쪽 다 없으면 → 더 긴(정보가 더 많은) 문단으로 교체
    문단 = 빈 줄(\\n\\n) 경계 분할. 위치 매칭은 순서 기반(같은 인덱스의 문단끼리 비교).
    반환: (보정된 본문, 교체된 문단 수)."""
    if not other_texts or not rep_text:
        return rep_text, 0
    rep_paras = rep_text.split("\n\n")
    replaced = 0
    # other_docs가 있으면 엔진별 구조 인식 풍부도로 정렬 — 표/이미지를 더 많이 인식한 엔진 우선
    sorted_texts = other_texts
    if other_docs:
        docs_list = list(other_docs.values())
        scored = sorted(zip(other_texts, docs_list), key=lambda pair: _richness(pair[1]), reverse=True)
        sorted_texts = [t for t, _ in scored]
    split_others = [other.split("\n\n") for other in sorted_texts if other]  # 엔진마다 한 번만 나눔(fp-perf B3 — 문단마다 나누던 것)
    for i, para in enumerate(rep_paras):
        if not para.strip() or "\x0c" in para.lstrip():  # F6(리뷰) — 문단 안·끝 쪽 나눔은 다른 엔진 글에서 자리를 못 맞춤 → 그대로 둔다
            continue
        rep_has_struct = _para_has_structure(para)
        best_para = para
        best_len = len(para.strip())
        best_has_struct = rep_has_struct
        for other_paras in split_others:
            if i < len(other_paras):
                cand = other_paras[i].strip()
                if not cand:
                    continue
                cand_has_struct = _para_has_structure(cand)
                # 우선순위 1: 대표에 구조 없는데 다른 엔진에 있으면 → 무조건 교체
                if not rep_has_struct and cand_has_struct:
                    best_para = cand
                    best_len = len(cand)
                    best_has_struct = True
                    replaced += 1
                    break  # 구조 있는 문단 찾으면 더 이상 안 봄
                # 우선순위 2: 양쪽 다 구조 있으면 → 더 긴 것으로 (구조가 더 풍부할 가능성)
                if rep_has_struct and cand_has_struct and len(cand) > best_len:
                    best_para = cand
                    best_len = len(cand)
                    replaced += 1
                    continue
                # 우선순위 3: 양쪽 다 구조 없으면 → 더 긴 것으로
                if not best_has_struct and not cand_has_struct and len(cand) > best_len:
                    best_para = cand
                    best_len = len(cand)
        # F6(11-03) — 문단 첫머리 쪽 나눔(\f)은 대표 본문의 쪽 시작: 다른 엔진 문단으로 바꿔도 앞에 남긴다(안 남기면 청크 page가 비고 bbox만 남음)
        lost = para.count("\x0c") - best_para.count("\x0c")
        rep_paras[i] = "\x0c" * lost + best_para if lost > 0 else best_para
    return "\n\n".join(rep_paras), replaced


def _merge_pages(rep, other_docs):
    """쪽(\\f 경계) 단위 보정 — 대표 엔진이 인식하지 못한 표/이미지가 있는 쪽을,
    그 표/이미지를 인식한 다른 엔진의 같은 쪽으로 교체.
    교체 조건: 다른 엔진이 그 쪽에 표(tables) 또는 그림(figures)을 인식했고,
               대표 엔진은 해당 쪽에 표/그림이 없거나 더 적은 경우.
    반환: (교체된 쪽 수, 교체 상세 목록)."""
    if not other_docs or not rep.get("text"):
        return 0, []
    rep_pages = rep["text"].split("\f")
    # 대표 엔진의 쪽별 표/그림 수 계산
    rep_table_pages = {}
    for t in rep.get("tables") or []:
        p = t.get("page")
        if p is not None:
            rep_table_pages[p] = rep_table_pages.get(p, 0) + 1
    rep_fig_pages = {}
    for fig in (rep.get("post") or {}).get("figures") or []:
        p = (fig.get("loc") or {}).get("page") or (fig.get("loc") or {}).get("slide")
        if p is not None:
            rep_fig_pages[p] = rep_fig_pages.get(p, 0) + 1

    replaced_pages = []
    for engine, other in other_docs.items():
        if not other.get("text"):
            continue
        other_pages = other["text"].split("\f")
        if len(other_pages) != len(rep_pages):
            continue  # 쪽 수가 다르면 매칭 불가 — 안전하게 건너뜀
        # 다른 엔진의 쪽별 표/그림 수
        other_table_pages = {}
        for t in other.get("tables") or []:
            p = t.get("page")
            if p is not None:
                other_table_pages[p] = other_table_pages.get(p, 0) + 1
        other_fig_pages = {}
        for fig in (other.get("post") or {}).get("figures") or []:
            p = (fig.get("loc") or {}).get("page") or (fig.get("loc") or {}).get("slide")
            if p is not None:
                other_fig_pages[p] = other_fig_pages.get(p, 0) + 1
        # 각 쪽 비교 — 다른 엔진이 표/그림을 더 많이 인식한 쪽만 교체
        for pi in range(len(rep_pages)):
            if not rep_pages[pi].strip() or not other_pages[pi].strip():
                continue
            rep_rich = rep_table_pages.get(pi, 0) + rep_fig_pages.get(pi, 0)
            other_rich = other_table_pages.get(pi, 0) + other_fig_pages.get(pi, 0)
            if other_rich > rep_rich and other_rich > 0:
                rep_pages[pi] = other_pages[pi]
                replaced_pages.append({"page": pi, "engine": engine, "rep_rich": rep_rich, "other_rich": other_rich})
                # 대표의 표/그림 정보도 업데이트
                rep_table_pages[pi] = other_table_pages.get(pi, 0)
                rep_fig_pages[pi] = other_fig_pages.get(pi, 0)
    if replaced_pages:
        rep["text"] = "\f".join(rep_pages)
    return len(replaced_pages), replaced_pages


def row_key(f):
    """보충 사실 중복 판정 키 = 정규화한 행 라벨(쉼표·공백·대소문자 무시). 대표에 이미 있는 행은 다른 엔진 값으로 다시 넣지 않음
    (대표 우선) — '1,000'/'1000'·'A-1 '/'A-1'처럼 표기만 다른 같은 행이 따로 들어가 합계가 늘던 것 방지(백로그 E2).
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
    """SI20·AD46⑤ — 표 칸 재현율 저하 원인(기호 정형화 부재)을 산출 쪽에서 메움: 엔진 묶음 직후·융합(facts 합치기) 전에
    본문·facts·표 칸에 common.core.text.standardize_text(기호 맵 + 첨자 표기 통일)을 적용. 원문(pd/<엔진>/<문서>.json)은
    여기서 손대지 않고 대표 결과(_rep)에만 적용 — 되돌릴 수 있게 바뀐 개수만 돌려준다(rep.rep.standardize)."""
    from pipeline.shared.text_normalize import standardize_text as _std

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


HIDDEN_AGREE_MIN = 0.6  # 독립 검토 MAJOR(AD31) — '검색 가능 스캔 PDF'(이미지와 같은 내용의 양질 숨은 OCR 글자층)
# 판정 기준. reason='hidden'인 쪽만 적용 — 숨은 층과 우리 OCR 글의 정규화 후 글자 2-gram
# Jaccard가 이 값 이상이면 숨은 층이 이미 정답과 같다고 보고 원래 글을 유지(OCR로 덮지 않음).
HIDDEN_AGREE_MIN_LEN = 20  # 독립 검토 MAJOR 후속 — 정규화한 글이 둘 중 하나라도 이보다 짧으면 일치도 판단이
# 불안정(2-gram 몇 개로 우연히 겹치거나 안 겹칠 수 있음) → 판단 불가로 **원래 글 유지**
# (애매하면 안 덮는 쪽이 정답률을 더 보호 — _page_agreement가 None을 돌려준다).
# 30이 아니라 20인 이유(실측, 2026-10-07): synth-mixedpdf garbled_layer.pdf의 실제 쓰레기
# 숨은 글자층이 정규화하면 29자라 30 문턱이면 매번 "판단 불가"로 묻혀 원래(틀린) 글이
# 유지됐다(value_recall 1.0→0.6 회귀, e2e 재측정으로 발견) — 짧은 쪽 가드는 극단적으로
# 짧은 조각(10여 자 이하, 예 'MX-H1')만 거르는 안전판이지 일반 문장까지 막는 문턱이 아님.


def _norm_agree(text):
    """AD31 독립 검토 MAJOR 후속 — 일치도 비교 전 정규화: canon_symbols(SI20, 기호·대시·특수공백·전각→반각) →
    common.core.text.normalize_value(NFKC·소문자·제로폭 제거·숫자 사이 쉼표 제거·공백 전부 제거) → 숫자 사이 마침표도
    추가로 제거(430,000·430.000·430000이 전부 같아지게 — OCR이 천단위 구분자를 다르게 읽는 경우가 흔함)."""
    import re

    from common.core.text import normalize_value
    from pipeline.shared.text_normalize import canon_symbols

    return re.sub(r"(?<=\d)\.(?=\d)", "", normalize_value(canon_symbols(text or "")))


def _char_ngrams(s, n=2):
    return {s[i : i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def _page_agreement(text_a, text_b, min_len=HIDDEN_AGREE_MIN_LEN):
    """AD31 독립 검토 MAJOR 후속 — 두 글의 일치도: 정규화(_norm_agree) 후 글자 2-gram Jaccard(공백·표기·대소문자
    차이·OCR 오타 1~2자에 강함 — 어순이 섞이는 토큰 비교보다 붙여쓰기·구분자 차이에 안정적). 숨은 글자층이 OCR과
    '같은 내용을 옮긴 것'인지(검색 가능 스캔 PDF) 보는 용도. min_len(기본 HIDDEN_AGREE_MIN_LEN, AD47 검토자
    반영 — 쪽 전체가 아니라 국소(겹친 숨은 글자 상자 주변)만 비교할 때는 원래 짧으므로 더 작은 값을 넘겨 쓴다).
    정규화한 글이 둘 중 하나라도 min_len보다 짧으면(짧은 조각 몇 개로 우연히 갈릴 수 있어 판단 불안정)
    None(호출부가 "애매하면 원래 글 유지"로 처리 — 안 덮는 쪽이 정답률을 더 보호)."""
    a, b = _norm_agree(text_a), _norm_agree(text_b)
    if min(len(a), len(b)) < min_len:
        return None
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    return round(len(ga & gb) / len(ga | gb), 4)


def _doc_page_count(doc_path):
    """문서의 실제 쪽 수 — \\f(쪽 경계) 개수가 이것과 다르면 중간에 글자 0개(빈) 쪽이 있어 \\f로 나눈 쪽 번호를
    못 믿는다(독립 검토 MAJOR-1: `_ocr_out`은 박스가 있는 쪽 사이에서만 \\f를 찍어, 빈 쪽이 있으면 뒤 쪽 번호가 밀림).
    이미지 파일은 항상 1쪽. 못 세면(손상 등) None — 호출부가 안전하게(쪽 번호 확정 불가) 처리.
    (pl-34 10-30 — scan_dedup.py를 지우며 이리로 옮김, 로직 그대로)"""
    p = Path(doc_path)
    if p.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(p)))
    except Exception:
        return None


def _page_texts(base, doc_path, boxes):
    """base를 실제 쪽 번호별 글로 나눈다 — 독립 검토 MAJOR-1 반영:
    1) boxes(엔진 출력의 rep["boxes"] — OCR 엔진만, 박스마다 실제 "page" 번호) 있으면 그걸로 그룹화한다.
       글자 0개(박스 없는) 빈 쪽은 그냥 키가 없을 뿐이라 뒤 쪽 번호가 안 밀린다(\\f 세는 방식과 다름 — 이게 고친 점).
    2) boxes가 없으면(OCR 아닌 엔진) \\f로 나누되, \\f 개수가 문서의 실제 쪽 수와 같을 때만 믿는다(빈 쪽이 없다는
       뜻). 다르면 쪽 번호를 확정할 수 없음 → None(호출부가 그 문서는 건너뛴다 — 틀린 쪽끼리 비교·치환하는
       것보다 안전한 쪽). (pl-34 10-30 — scan_dedup.py를 지우며 이리로 옮김, 로직 그대로)"""
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
    n_pages = _doc_page_count(doc_path)
    if n_pages is not None and len(parts) != n_pages:
        return None  # 쪽 번호 확정 불가 — 건너뜀(MAJOR-1)
    return {i + 1: p for i, p in enumerate(parts)}


def fill_scan_pages(rep, dd, doc_path, page_vlm=None):
    """PE1 후속 — .pdf_text 대표 결과의 스캔 쪽(scan_pages_detail)만 쪽 VLM 글로 채운다(글자층 쪽은 그대로 — 쪽 전체를 바꾸지 않음).
    page_vlm(쪽 VLM 함수, vlm_page.page_text_pages — 스캔 신호 쪽만 병렬 호출)의 글을 쓴다(기록 엔진 이름 "vlm_page").
    0.2.0(pl-46, 사용자 11-01) — 옛 OCR 엔진(.pdf_image) 대체 길과 숨은 글자 국소 충돌 확인(AD47)은 지웠다: 쪽 VLM 글이 없으면 채우지 않는다.
    쪽 경계는 _page_texts(boxes 있으면 그걸로, 없으면 \f 개수가 문서의 실제 쪽 수와 같을 때만) — 쪽 번호를 확정할 수 없으면 건너뛴다.
    쪽 단위 품질 검사 — 그 쪽 글의 garbage_ratio가 0.1을 넘으면 덮지 않고 건너뛴다(원래 글 유지) — page_skip에 기록.
    AD31 reason='hidden' — 그림과 같은 내용을 옮긴 숨은 글자층('검색 가능 스캔 PDF')은 원래 글과 쪽 VLM 글의 일치도(_page_agreement)가
    HIDDEN_AGREE_MIN 이상이거나 판단 불가(짧음)면 원래 글을 유지, 미만이면 쪽 VLM 글로 채운다.
    reason='hidden_overlap'(그림과 겹친 숨은 글자) — 쪽 VLM은 글자 상자가 없어 국소 확인을 못 하므로 늘 원래 글을 유지한다(전과 같은 결과).
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
    """runs.jsonl 기록 하나 → 상태: 성공 · 시간 초과 · 환경(미설치·미설정·연결) · 실패."""
    e = r.get("error") or ""
    if not e:
        return "성공"
    if "Timeout" in e:
        return "시간 초과"
    if any(k in e for k in ("미설정", "미설치", "NotFoundError", "not found", "FileNotFoundError", "SpawnError", "initialization fai")):
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
    PM2 — version(runs.jsonl의 engine_version, raw_artifacts()가 이미 쓰던 값 재사용)도 같이 남겨 EDW
    engines_used()가 rep_json만 보고 엔진 판까지 알 수 있게(새 계산 없음, 같은 값을 한 자리 더 적음)."""
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
from common.core.contract import source_record  # noqa: E402 — 문서 ID·원본 위치 규칙(모듈 계약)
from pipeline.shared import post_features as post_cfg  # noqa: E402 — PARSE_POST 해석(W1~W3·W9·W11 후보정 패키지)
from pipeline.shared import runtrace  # noqa: E402 — op-01 run.progress
from pipeline.transform.represent import decision_log as trace_mod  # noqa: E402 — PA0 맥락 기록
from pipeline.transform.represent import fragment_vote as fuse_mod  # noqa: E402 — AD29 P1 조각 단위 융합
from pipeline.transform.represent import table_inline  # noqa: E402 — TA1(사용자 10-15) 엔진별 표 그리드를 본문 제자리에 GFM 표로


def apply_post(rep, doc, doc_path, feats, out_images=None, figures_max=None, vp_pages=None, page_covered=False):
    """후보정 패키지 적용 — base 본문에 쪽 VLM 옮기기·차트·그림 기록 블록을 덧붙이고, 첨자(supsub)는 그 줄만 base 안에서
    바꿔 넣는다(AD37 — 전엔 문서 전체를 다시 옮긴 블록을 덧붙여 대표 본문이 ~2배였음·청크·BM25·임베딩 중복). rep.post{config,
    features, code_fp, supsub(첨자 표기본 전체 — 색인에는 안 들어가고 여기만)}를 남긴다.
    프로토타입(eval_hard_parse) 설정 F_context의 쌓는 순서(base, vtext, 그림 기록(+근처 본문), 차트)를 그대로 따름.
    PARSE_POST=none(feats 빔) → rep["text"] 불변(이전 동작과 바이트 동일, W10 설계대로 원본 층은 손대지 않음).
    out_images — 그림 PNG·index.jsonl·capped.jsonl이 쓰일 폴더(AG11 2단계 착수 조건, 10-08: 전엔 호출자가
    PARSE_IMAGES_ROOT 환경변수를 바꿔 치환해야 했던 것을 인자로 — 기본값 None이면 fig_mod.images_root()를 써
    이전과 바이트 동일, 운영 배치는 그대로 안 넘겨 기본 경로를 그대로 쓴다).
    figures_max — 그림 VLM 상한을 이번 호출만 바꿈(figures_resume — 기본 None = 설정 VLM_FIGURES_MAX, S7c2).
    vp_pages — represent()가 이 문서에 한 번만 부른 쪽 VLM 결과(10-29 M4 — scan_fill과 같은 결과를 써서 실패한 쪽도 다시 안 부름,
    None이면 여기서 부름) · page_covered — 이미지·스캔 문서를 VLM 엔진이 이미 쪽마다 옮김(10-29 C — 쪽 VLM·쪽 전체 그림 VLM 생략)."""
    post_spec = (
        pc.cfg().transform.represent.post
    )  # S7c — 설정 객체(글자 칸 — 쓴 글자 그대로라 rep.post.config가 옛 env 글자와 바이트 같음, 없으면 "all")
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
    }  # 2026-10-22 — apply_post 하위 소요
    _pt0 = time.time()
    if not feats or not doc_path or not Path(doc_path).exists():
        return info
    from pipeline.transform.figures import figure_extract as fig_mod
    from pipeline.transform.figures import office_charts as charts
    from pipeline.transform.figures import scan_page_vlm as vp_mod
    from pipeline.transform.represent import superscripts as supsub

    base = rep.get("text") or ""
    blocks = []
    doc_text = base  # 그림 근처 본문 언급(link_context) 검색 대상 — 쪽 VLM 옮기기 글자도 포함(스캔은 OCR 본문이 부실할 수 있어)
    if "vlm_page" in feats:
        # 10-29 — scan_fill이 쪽 VLM 글로 이미 채운 쪽은 덧붙이지 않음(같은 쪽이 본문에 두 번 — 호출은 캐시라 다시 안 감)
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
        from pipeline.transform.figures.pptx_render import pptx_slide_vlm  # AD20(남은 것): pptx 아니면 즉시 []( 바이트 영향 0)

        slides = pptx_slide_vlm(doc_path)
        if slides:
            pt = "\n".join(f"[슬라이드 {n}] {t}" for n, t, _pv in slides if t.strip())
            if pt.strip():
                blocks.append(pt)
                doc_text += "\n" + pt
            info["vlm_page_calls"] += len(slides)
            info["vlm_page_cached"] += sum(1 for _, _, pv in slides if pv.get("cached"))
        # PM2 — 쪽 VLM 모델 이름(지금까진 env VLM_MODEL에만 있었음, publish는 나중·다른 env로 돌 수 있어 rep에 남김)
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
        info["figures_capped"] = any(r.get("skipped") == "VLM_FIGURES_MAX" for r in records)  # AD21① — 상한 걸린 문서 표시
        skips = [
            r["skipped"] for r in records if r.get("skipped")
        ]  # PA0 — 건너뜀 이유별 건수(SI30 unconvertible 등, 이미 계산된 records만 읽음)
        if skips:
            from collections import Counter as _Counter

            info["figures_skip_reasons"] = dict(_Counter(skips))
        # PM2 — 그림 VLM 모델 이름(각 그림의 vlm.model, figure_extract.py build_records가 이미 채움 — 새 계산 없음)
        fig_models = sorted({(r.get("vlm") or {}).get("model") for r in records if (r.get("vlm") or {}).get("model")})
        if fig_models:
            info.setdefault("vlm_models", {})["figure"] = "+".join(fig_models)
    _pt["figures"] = time.time() - _pt0
    _pt0 = time.time()
    if "charts" in feats:
        ct = charts.chart_text(doc_path)
        if ct.strip():
            blocks.append(ct)
    _pt["attachments"] = time.time() - _pt0
    if "supsub" in feats:
        base, sup_full, n_unmatched = supsub.merge_supsub(base, doc_path)  # AD37 — 줄만 바꿔 넣고 전체는 rep.post에 따로
        if sup_full.strip():
            info["supsub"] = sup_full
            info["supsub_unmatched"] = n_unmatched
    _pt["charts"] = time.time() - _pt0
    _pt0 = time.time()
    if "attachments" in feats:
        from pipeline.transform.represent import mail_attachments as att_mod

        att_blocks, att_stats = att_mod.mail_blocks(doc_path, base)
        blocks += att_blocks
        info["attachments_parsed"] = att_stats["parsed"]
        info["attachments_cached"] = att_stats["cached"]
    _pt["supsub"] = time.time() - _pt0  # 2026-10-22 — supsub 완료
    info["post_times"] = {k: round(v, 2) for k, v in _pt.items()}  # 2026-10-22 — apply_post 하위 소요(초)
    rep["text"] = base + "\n\n" + "\n\n".join(blocks) if blocks else base
    return info


IMAGE_TYPES = IMG_EXTS | {".pdf_image"}  # run_all과 같은 형식 키(qa.json format — progress.doc_types)


def _vlm_transcribed(rep, dd):
    """이미지·스캔 형식(run_all과 같은 형식 키 — 글자 쪽이 몇 장 섞인 .pdf_image 포함) 문서의 대표가 VLM 엔진(run_all.VLM_ENGINES)이고
    본문이 비어 있지 않음 = 쪽을 이미 VLM으로 옮김(10-29 C). OCR 엔진이 대표거나 VLM 글이 비면 False(쪽 VLM을 막지 않음)."""
    from pipeline.extract.run_engines import VLM_ENGINES

    return dd.get("format") in IMAGE_TYPES and (rep.get("rep") or {}).get("engine") in VLM_ENGINES and bool((rep.get("text") or "").strip())


def _current_sha16(doc, last):
    """runs.jsonl(last_runs) 중 이 문서의 가장 최근 시도 기록의 sha(앞 16자, run_all._sha와 같은 계산) — 없으면 None.
    문서 하나에 엔진 여럿이 다른 때 시도됐어도 '가장 최근' 한 번이면 그때 파일 내용을 반영(독립 보안 검토 MAJOR 3)."""
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
    from pipeline.transform.represent.parse_scoring import LOW_N
    from pipeline.transform.represent.rep_accuracy import doc_accuracy

    pd = Path(parse_dir)
    qa = json.loads((pd / "qa.json").read_text(encoding="utf-8"))
    out_dir = pd / "_rep"
    out_dir.mkdir(parents=True, exist_ok=True)
    index, last, conflicts_out = [], last_runs(pd), []  # conflicts_out — AD25(b)(c) 표 행 라벨 자리의 엔진 간 표기 충돌(아래)
    from pipeline.transform.represent.crosscheck import build

    meta = build(parse_dir, src) if src else {}  # 교차 확인 (라벨, 값) — 엔진별 결과가 있는 파싱 모듈에서 미리 → 구조화는 _rep만 읽음
    feats = post_cfg.active_features()  # PARSE_POST(기본 all) — none이면 이전 동작과 바이트 동일(W10)

    def _doc_one(_pair):
        """문서 1개 represent 처리(2026-10-22 문서 병렬 리팩터) — index 행 반환:
        정상 대표·'이전 결과 재사용(X2)'·'성공 엔진 없음' 모두 index 행을 그대로 되돌린다."""
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
                # X2 스트리밍: 전에 대표 결과를 만든 뒤 그 문서의 엔진별 중간 결과를 지웠다(원본 즉시 삭제) — 다시 긁지 않고
                # 전에 만든 결과를 그대로 목록에 올림(여기서 "성공한 엔진 없음"으로 덮어쓰면 이미 만든 대표 결과가 사라짐).
                # 단 같은 이름의 '다른' 문서(내용이 바뀜)일 수 있으니 sha로 확인(독립 보안 검토 MAJOR 3) — 다르면 보존 안 함.
                try:
                    old = json.loads(prev.read_text(encoding="utf-8"))
                    old_rep = old.get("rep") or {}
                    SP.result_current("reused")  # op-01 — 이전 대표 결과를 그대로 올림
                    old_sha = (old_rep.get("source") or {}).get("sha256")  # 64자 — run_all 기록(last)의 sha는 앞 16자
                    cur_sha = _current_sha16(doc, last)
                    if old_sha and cur_sha and old_sha[:16] == cur_sha:
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
                        return None
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
            return None
        _t = {"load": 0.0, "merge": 0.0, "fuse": 0.0, "scanfill": 0.0, "post": 0.0, "table": 0.0, "agent": 0.0}
        _t0 = time.time()
        # 2026-10-22 — PARSE_REP_SELECT: first(첫 성공 엔진·파일 읽기 0) | acc(정확도만·파일 읽기 0) | best(정확도+풍부도, 기본)
        _sel = pc.cfg().transform.represent.rep_select or ""  # S7c — 설정 객체(없음·'' = "")
        if _sel == "first":
            best = max(ok, key=lambda c: -ok.index(c))  # 스택 순서 첫 성공 — 교차 재현율·richness 파일 읽기 없음
        elif _sel == "acc":
            best = max(ok, key=lambda c: ((c["acc"] if c["acc"] is not None else -1), -ok.index(c)))
        else:
            best = _select_best(ok, pd, doc)
        rep = json.loads((pd / best["engine"] / f"{doc}.json").read_text(encoding="utf-8"))
        _t["load"] = time.time() - _t0
        _t0 = time.time()
        std_n = standardize_rep(rep)  # 엔진 묶음(텍스트 파싱) 직후·융합(아래 facts 합치기) 전 — SI20·AD46⑤
        best_facts_raw = [dict(f) for f in rep.get("facts") or []]  # AD29 P1 — 대표 자신의 원본 facts 스냅샷(아래서 rep["facts"]를
        # 다른 엔진 것으로 보충하기 전, fuse_mod가 엔진별 원본을 보게)
        other_docs = {}  # AD29 P1 — {엔진: 그 엔진 원본 결과}(fuse_mod 입력)
        have = {row_key(f) for f in rep.get("facts") or []}
        _t["load"] += time.time() - _t0
        _t0 = time.time()  # 2026-10-22 stage timer — load 완료
        texts = []  # 다른 후보 본문 — 표 머리글 칸 나눔 규칙(fix_tables) + 문단 보정 근거
        added = 0
        for c in ok:
            if c is best:
                continue
            f = pd / c["engine"] / f"{doc}.json"
            if not f.exists():
                continue
            other = json.loads(f.read_text(encoding="utf-8"))
            other_docs[c["engine"]] = other  # AD29 P1 — 아래서 제자리 표준화된 뒤의 값을 가짐(의도)
            std_n += standardize_rep(other)
            texts.append(other.get("text") or "")
            for fact in other.get("facts") or []:
                k = row_key(fact)
                if k not in have:
                    have.add(k)
                    rep.setdefault("facts", []).append({**fact, "from": c["engine"]})
                    added += 1
        # 쪽 단위 보정 — 대표 엔진이 표/이미지를 인식 못한 쪽을, 인식한 다른 엔진의 쪽으로 교체
        page_merged, page_details = 0, []
        para_merged, para_replaced = 0, 0
        if other_docs and rep.get("text"):
            page_merged, page_details = _merge_pages(rep, other_docs)
        # 문단별 조각 보정 — 표/이미지를 더 많이 인식한 엔진의 문단을 우선, 같은 위치 문단 중 더 긴 것으로 교체
        if texts and rep.get("text"):
            merged, para_replaced = _merge_paragraphs(rep["text"], texts, other_docs)
            if para_replaced:
                rep["text"] = merged
            para_merged = para_replaced
        _t["merge"] = time.time() - _t0
        _t0 = time.time()  # 2026-10-22 — merge(팩트병합·pages·paragraphs) 완료
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
            "meta": {k: (meta.get(doc) or {}).get(k, []) for k in ("pairs", "all")},
            "facts_added": added,
            "table_fix": fix_tables(rep, texts),
            "low_n": n_ok <= LOW_N or (dd.get("n_fam", 9) <= LOW_N and dd.get("ref") not in ("truth", "answer_key")),
            "para_merged": para_merged,  # 문단 보정으로 교체된 문단 수
            "page_merged": page_merged,  # 쪽 보정으로 교체된 쪽 수 (표/이미지 인식 우선)
            "page_merge_details": page_details if page_merged else [],  # 쪽별 교체 상세
            "richness": _richness(rep),  # 대표 엔진의 구조 인식 풍부도 (tables, facts, figures, boxes)
            "standardize": {"on": True, "changed": std_n},
        }  # SI20·AD46⑤ — 기호 맵·첨자 표기 표준화 바뀐 조각 수(되돌림 근거) · "on"은 옛 형식 유지(늘 True)
        # AD29 P1 — 조각(라벨:값·표 칸) 단위 맞추기+투표(모델 호출 0)
        engine_docs = {best["engine"]: {"facts": best_facts_raw}}
        engine_docs.update({e: {"facts": od.get("facts") or []} for e, od in other_docs.items()})
        rep["fused"] = fuse_mod.fuse(engine_docs, best["engine"])  # 대표 본문·기존 facts는 안 건드림 — 새 칸만 추가
        _t["fuse"] = time.time() - _t0
        _t0 = time.time()  # 2026-10-22 — fuse 완료
        if rep["fused"].get("conflicts"):  # AD25(b)(c) — 자리(행 라벨)·엔진별 원문 표기·계열 수를 문서 밖
            conflicts_out.append(
                {"doc": doc, "conflicts": rep["fused"]["conflicts"]}
            )  # conflicts.jsonl로도 모음(지금까진 각 문서 _rep/<문서>.json 안에만 있었음)
        source = rep["rep"]["source"]
        doc_path = Path(source["path"]) if source else None
        # 10-29 — 쪽 VLM은 PARSE_POST에 vlm_page가 있을 때만(run_docs light 레인·parse MCP의 supsub만 존중 — P1-1), 문서당 한 번만(M4).
        # 이미지·스캔 문서를 VLM 엔진이 이미 옮겼으면 쪽 VLM을 안 부르고 쪽 전체 그림 VLM도 생략(쪽마다 VLM 한 번 — C)
        # covered는 vlm_page 기능과 무관하게(그림 VLM 생략에도 씀 — run_docs light 레인처럼 vlm_page 없이 figures만 켠 경우)
        covered, vp_pages = _vlm_transcribed(rep, dd), None
        if "vlm_page" in feats and doc_path and Path(doc_path).exists():
            from pipeline.transform.figures import scan_page_vlm as vp_mod

            vp_pages = [] if covered else vp_mod.page_text_pages(doc_path)
        # PE1 후속 — .pdf_text 대표의 스캔 쪽만 쪽 VLM 글로 채움(apply_post 전, 후보정이 채운 본문을 기준으로 돌게)
        fill = fill_scan_pages(rep, dd, doc_path, page_vlm=(lambda _p: vp_pages) if vp_pages is not None else None)
        if fill is not None:
            rep["rep"]["scan_fill"] = fill
        _t["scanfill"] = time.time() - _t0
        _t0 = time.time()  # 2026-10-22 — scan_fill 완료
        with SP.span("transform.figures", doc_id=doc, ext=Path(doc).suffix.lower()):  # op-01 — 쪽 VLM·그림 VLM/OCR 호출 지표가 이 span에
            rep["post"] = apply_post(
                rep, doc, doc_path, feats, vp_pages=vp_pages, page_covered=covered
            )  # W1~W3·W9·W11 후보정(rep["text"]에 덧붙임)
        _t["post"] = time.time() - _t0
        _t0 = time.time()  # 2026-10-22 — apply_post(그림 추출·쪽 VLM) 완료
        # TA1(사용자 10-15) — apply_post·scan_fill 뒤, 즉 이 문서가 실제로 내보낼 rep["text"]가 다 정해진 뒤에 부른다:
        # table_inline이 찾는 표 자리(span)는 이 최종 본문 기준이어야 맞다(더 일찍 부르면 scan_fill이 쪽 전체를 OCR
        # 글로 갈아치울 수 있어 자리가 어긋날 수 있음 — 그때는 그냥 못 찾은 걸로 남고 본문은 안 바뀜, 안전).
        rep["rep"]["table_inline"] = table_inline.inline_tables(rep, best["engine"], other_docs)  # TA1 — rep["text"]도 바꿈
        trace_mod.attach(rep, dd, cands, stack, feats, doc_path)  # PA0 — 맥락 기록(rep.context·rep.decisions)
        _t["table"] = time.time() - _t0
        _t0 = time.time()  # 2026-10-22 — table_inline+trace 완료
        rep["rep"]["stage_times"] = {k: round(v, 2) for k, v in _t.items()}  # 2026-10-22 — 단계별 소요(초) 기록
        SP.add_current(stage_s=rep["rep"]["stage_times"])  # op-01 — 같은 값을 span.metrics에도
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
            + " ".join(f"{k}={_t[k]:.1f}s" for k in ("load", "merge", "fuse", "scanfill", "post", "table"))
            + _pdetail,
            flush=True,
        )
        (out_dir / f"{doc}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
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
        """문서 1개 = transform.represent span 1행(op-01) — 단계별 시간·모델 호출 지표는 span.metrics에."""
        _doc, _dd = _pair
        with SP.span("transform.represent", doc_id=_doc, ext=Path(_doc).suffix.lower(), cpu=_par == 1) as _sp:
            _r = _doc_one(_pair)
            if _r is None:
                _sp.result("skip", None, SP.safe("대표 결과 없음"))
            elif not _r.get("engine"):
                _sp.result("fail", "doc", SP.safe(_r.get("reason")))
            _sp.add(pages=_dd.get("pages"), format=_dd.get("format"))
            _done[0] += 1
            return _r

    _pairs = sorted(qa["docs"].items())
    _par = max(1, pc.cfg().extract.doc_parallel)  # S7c — 설정 객체 · 2026-10-22 사용자 지정 — 문서 병렬(기본 1=기존 순차와 동일)
    with runtrace.Progress(total=len(_pairs), done=lambda: _done[0], unit="doc"):  # op-01 — 60초마다 run.progress
        if _par > 1:
            import concurrent.futures as _cf  # 문서간 병렬 — ex.map 회수는 제출 순서라 index·engines.csv 순서 불변

            with _cf.ThreadPoolExecutor(max_workers=_par) as _ex:
                index.extend(r for r in _ex.map(SP.carry(_doc_traced), _pairs) if r is not None)
        else:
            for _p in _pairs:
                _r = _doc_traced(_p)
                if _r is not None:
                    index.append(_r)
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
    (out_dir / "index.json").write_text(
        json.dumps({"stack": stack.get("name"), "docs": index}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (out_dir / "conflicts.jsonl").open("w", encoding="utf-8") as f:  # AD25(b)(c) — 표 행(자리)에서 값은 같은데 표기가
        for r in conflicts_out:  # 갈린 엔진들(승자·패자·원문 표기) 문서 밖 한 파일로
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _times = [  # 문서마다 _rep/<문서>.json을 한 번만 읽음(fp-perf B6 — 단계 칸마다 6번 다시 읽던 것)
        json.loads((out_dir / f"{r['doc']}.json").read_text(encoding="utf-8")).get("rep", {}).get("stage_times", {})
        for r in index
        if r.get("engine")
    ]
    _agg = {k: round(sum(t.get(k, 0) for t in _times), 1) for k in ("load", "merge", "fuse", "scanfill", "post", "table")}
    print(
        "[represent] 단계별 누적: " + " ".join(f"{k}={_agg[k]:.0f}s" for k in ("load", "merge", "fuse", "scanfill", "post", "table")),
        flush=True,
    )
    return index


def rep_digest(parse_dir):
    """(index.json 문서 목록, 대표 결과 digest) — 파싱 끝 표시(_DONE.json)가 바뀌었는지 가르는 값(옛 pipeline.cli에서 옮김 — rn-06).
    GH1-05 — core는 chars·facts_added(길이·개수)만 있어 길이·개수가 같은 내용 교체를 못 잡음 → 본문·facts 자체의 sha256도 넣음."""
    rep_dir = Path(parse_dir) / "_rep"
    idx = json.loads((rep_dir / "index.json").read_text(encoding="utf-8"))["docs"]
    core = [{k: v for k, v in r.items() if k != "tried"} for r in idx]  # 시도 기록(시각)은 빼고 대표 결과만 비교
    content = []
    for r in idx:
        if not r.get("engine"):
            continue
        rep = json.loads((rep_dir / f"{r['doc']}.json").read_text(encoding="utf-8"))
        content.append(
            {
                "doc": r["doc"],
                "text_sha": hashlib.sha256((rep.get("text") or "").encode("utf-8")).hexdigest(),
                "facts_sha": hashlib.sha256(
                    json.dumps(rep.get("facts") or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
        )
    return idx, hashlib.sha256(json.dumps({"core": core, "content": content}, sort_keys=True).encode()).hexdigest()[:16]


def write_mark(parse_dir, **kw):
    """파싱 끝 표시 _rep/_DONE.json — 앞 표시와 digest(kw — rep_digest 값)·인계 형식 버전(CONTRACT)이 같으면 그대로 두고 False(구조화는 건너뛰게 됨),
    다르면 common 코드 지문(FINGERPRINT)과 함께 새로 쓰고 True. kw의 run_id가 있으면 그 값(같은 실행의 run_all과 같은 id)."""
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
    ap.add_argument("--stack", default=None, help="엔진 구성 파일(PC 실험·시험용 — 비우면 설정 common.paths.stack_file)")
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", default=None, help="파싱한 문서 폴더(원본 경로·sha256을 대표 결과에 남김 — 구조화 모듈이 원본 없이 돌 때 씀)")
    a = ap.parse_args(argv)
    idx = represent(load_stack(a.stack) if a.stack else pc.stack(), a.parse_dir, a.src)
    done = [r for r in idx if r["engine"]]
    from collections import Counter

    c = Counter(r["engine"] for r in done)
    line = (
        f"대표 파싱 {len(done)}/{len(idx)}문서 · 엔진 "
        + ", ".join(f"{e} {n}" for e, n in c.most_common())
        + f" · 스택 밖 대체 {sum(r['fallback'] for r in done)} · 모수 적음 {sum(r['low_n'] for r in done)} · 실패 {len(idx) - len(done)}"
        + f" · 그림 상한 걸린 문서 {sum(1 for r in idx if r.get('figures_capped'))}건"
    )  # AD21① — 이어서 VLM 대상(cli/figures_resume.py)
    print(line + f" → {Path(a.parse_dir) / '_rep'}")


if __name__ == "__main__":
    import sys

    utf8_stdout()
    with runtrace.run("represent", sys.argv[1:]):  # op-01 — 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
