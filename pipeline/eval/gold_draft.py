#!/usr/bin/env python3
"""GS1·GS2 — 텍스트 파싱 정답셋 초안(AI 초안 + 사람 검수, 사용자 10-14). 개발 서버에서 내부 VLM으로 실행(원문은 밖으로 안 나감).

초안은 **원본 쪽 이미지를 VLM이 옮겨 적은 글**로 만든다 — page_transcribe와는 다른 지시문·캐시 열쇠(gold_draft, 파싱 쪽 VLM
캐시·동작에 영향 없음). GS2(사용자 10-14 "텍스트 파싱 정답셋 확대" — 사람 검수만으론 한계) — 우리 파싱 대표 결과(_rep)를
**참고로만** 같이 보여준다: 이미지에서 실제로 보이는 내용만 옮기고, 참고 글은 철자·숫자가 헷갈릴 때만 확인용으로 쓰게
지시문에 못박음(정답이 파서 쪽으로 기우는 것 방지). --with-parse로 파싱 결과 폴더를 주면(기본 output/parse, 없으면 참고
없이 GS1 그대로 이미지만 보고 옮김) 문서별 `_rep/<문서>.json`의 text를 쪽 나눔(\\f, 엔진 공용 규칙 — contract.py·
pymupdf parser 등)으로 쪼개 쪽마다 맞는 참고 글을 건넨다.
표는 마크다운 표(병합 칸은 덮는 모든 칸에 같은 값 — TB6과 같은 규칙), 흐름도는 Mermaid 코드 블록(F13·to_mermaid()와
같은 표기 — flowchart LR, n0["이름"] --> n1["이름"], 글자 있는 화살표는 -->|"글자"|)로 지시문에 적음.

산출(--out, 기본 output/gold_draft): <문서>.md(쪽마다 옮긴 글 — 표는 마크다운 표, score_gold 정답 형식 그대로) ·
  values.csv(머리글만 — 검수자가 꼭 맞아야 할 값을 문서,라벨,값으로 채움) · review.csv(문서별 상태 draft·쪽 수·모델·
  실패 쪽·메모 — 검수자가 상태를 reviewed로 바꾸고 메모) · <문서>.check.csv(GS2 ④ — VLM 초안과 파싱 참고 글이 쪽마다
  갈린 숫자·표 칸·짧은 줄 목록, '확인할 곳' — score_gold와 같은 정규화(canon)로 비교해 정답이 파서 쪽으로 기우는
  것을 막는다. 검수자는 원본 전체를 다시 보지 않고 이 목록만 봐도 됨).
검수 절차: 원본을 옆에 두고 <문서>.md를 고침(빠진 글·표 칸·숫자 표기, <문서>.check.csv '확인할 곳'부터) → values.csv
  채움 → review.csv 상태 reviewed → reviewed 문서만 정답 폴더(GOLD_DIR)로 옮김 → `score_gold --gold <GOLD_DIR>`.
  draft 그대로는 정답 폴더에 넣지 않는다.
대상: PDF·이미지(png·jpg·tif 등)·docx/doc(GS3, 사용자 10-15 — soffice로 PDF로 바꿔 쪽 이미지를 만들고(본문 속 그림도
  그 쪽에 그대로 보임), 쪽 참고 글은 우리 파서 결과 대신 **문서 파일 자체의 글자**(변환 PDF 글자층)를 줌 — 글자·숫자는 원문을
  따르고, 표 구조·그림 속 내용은 이미지를 보고 맥락에 맞게 옮김. 변환본은 <out>/_pdf/에 재사용). soffice가 없으면 docx는
  건너뜀. 그 밖(xlsx·pptx)은 건너뛰고 review.csv에 'PDF로 저장해 다시' 표시.
비용: 쪽마다 VLM 1회(캐시 재사용) · GOLD_DRAFT_MAX_PAGES(기본 30)로 문서당 쪽 상한 · 유료 외부 모델이면 LLM_MAX_CALLS·LLM_BUDGET_USD 함께.
사용: python -m pipeline.eval.gold_draft --src <원본 폴더> [--out output/gold_draft] [--with-parse output/parse]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from common.ai.guard import fake_llm
from common.config import settings as C  # S7c — 설정 객체(common 칸: VLM_*·LLM_FAKE)
from common.core.console import utf8_stdout
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸: VLM_DEADLINE·GOLD_DRAFT_*)

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
OFFICE_EXT = {".docx", ".doc"}  # GS3 — rendered to PDF with soffice; pptx/xlsx: add when a gold set needs them
CHECK_SPAN_MAX = 40  # 표 칸·짧은 줄 — 이보다 길면 '확인할 곳'에서 뺌(본문 문단은 사람이 어차피 다 읽음, 짧은 값·라벨만 겨냥)
CHECK_LINE_MAX = 60
DOC_WORKERS = 2  # ponytail: 동시에 펼치는 문서 수(쪽 이미지 메모리 상한 — 문서당 최대 GOLD_DRAFT_MAX_PAGES쪽 × 2)


def _vlm_workers():
    """동시 VLM 호출 수 — 파이프라인과 같은 VLM_CONCURRENCY(기본 4). 1이면 옛 순차 동작."""
    return max(1, C.cfg().models.vlm.concurrency)  # S7c — 설정 객체(칸 기본값 4 — 빈 값·형식 틀림도 4)


_VLM_SEM = None


def _vlm_slot():
    """프로세스 전체 동시 VLM 호출 상한(문서 2개 × 쪽 동시라도 합계 VLM_CONCURRENCY 이하)."""
    global _VLM_SEM
    if _VLM_SEM is None:
        import threading

        _VLM_SEM = threading.BoundedSemaphore(_vlm_workers())
    return _VLM_SEM


def _pool_map(fn, items, workers):
    """순서 보존 병렬 map(스레드 — VLM 호출은 네트워크 대기라 CPU·메모리 부담 작음). workers<=1이면 순차."""
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def office_pdf(p, work):
    """GS3 — docx/doc → PDF via soffice (the same converter the parse figures use), kept at <work>/<name>.pdf and
    reused while it is newer than the source. None when soffice is missing or the conversion fails."""
    import shutil
    import tempfile

    from pipeline.transform.figures import pptx_render as R

    dst = Path(work) / f"{p.name}.pdf"
    if dst.exists() and dst.stat().st_mtime >= p.stat().st_mtime:
        return dst
    if R.soffice_bin() is None:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory() as td
    ):  # short system temp path: soffice crashed (0xC0000409) with its profile under a long --out path
        pdf = R._convert_to_pdf(p, Path(td), R._cap("PARSE_PPTX_CONVERT_SEC", 60))
        if pdf is None:
            return None
        shutil.move(str(pdf), dst)
    return dst


def source_pages(pdf):
    """GS3 — per-page text of the document itself (text layer of the soffice PDF). Used as the page reference for
    docx instead of our parser output: the parser has no page breaks for docx, and this text is the original."""
    import fitz

    with fitz.open(pdf) as d:
        return [pg.get_text() for pg in d]


def ref_pages(parse_dir, doc_name):
    """GS2 — <문서>의 파싱 대표 결과(_rep/<문서>.json)의 text를 쪽 나눔(\\f)으로 쪼갠 쪽별 참고 글 목록. parse_dir이
    없거나 그 문서의 _rep 파일이 없으면 빈 목록(참고 없이 GS1처럼 이미지만 보고 옮김)."""
    if not parse_dir:
        return []
    f = Path(parse_dir) / "_rep" / f"{doc_name}.json"
    if not f.exists():
        return []
    try:
        text = json.loads(f.read_text(encoding="utf-8")).get("text") or ""
    except (OSError, ValueError, AttributeError):
        return []
    return text.split("\f")


SOURCE_REF_HEAD = (
    "\n\n[원문 글자 — 이 쪽에 있는 문서 파일 자체의 글자(정확함)]\n이 글은 문서 파일에서 직접 뽑은 원문 글자다. "
    "글자·숫자·단위의 철자는 이 원문을 따르고, 읽는 순서·표 구조(행·열·병합 칸)·흐름도는 이미지를 보고 정해라. "
    "원문 글자에 없는 그림·사진·차트 안의 글자는 이미지에서 보이는 대로 옮기고, 그림이 무엇을 보여 주는지 "
    "앞뒤 문맥에 맞게 판단해 표·Mermaid로 옮겨라. 그림 속 숫자가 본문 글과 달라도 고치지 말고 그림에 적힌 대로 "
    "옮겨라(본문과 그림이 다른 것도 정답의 일부다). 이미지에 보이지 않는 내용은 쓰지 마라.\n"
)


def _vlm_gold(img_bytes, ref_text, source=False):
    """쪽 1장 + 파싱 참고 글(정답 아님) → (마크다운 글자, provenance). page_transcribe(vlm_page.py)와는 다른 지시문
    (gold_draft 패키지) · 다른 캐시 열쇠(이미지 바이트 + 참고 글 — 참고 글이 바뀌면(파싱이 좋아지면) 새 열쇠, 파싱이
    그대로면 다시 안 부름) — page_transcribe의 캐시·동작에는 전혀 손 안 댐(agent_prompts 모듈 설명의
    template()+자료+tail() 패턴, value_choice와 같은 호출부 모양)."""
    import base64
    import time

    from common.ai import adk as A
    from common.ai.agent_prompts import tail as _tail
    from common.ai.agent_prompts import template as _template
    from pipeline.shared.artifacts import prompt_id as _prompt_id
    from pipeline.shared.artifacts import raw_vlm_path
    from pipeline.transform.figures import vlm_page as V

    vlm = C.cfg().models.vlm  # S7c — 설정 객체
    base, model = vlm.base_url, vlm.model
    model_dir = V._model_dir(model)
    p_gold = _template("gold_draft", "draft")
    ref_block = (
        SOURCE_REF_HEAD + ((ref_text or "").strip() or "(이 쪽 원문 글자 없음 — 이미지만 보고 옮겨라)")
        if source
        else "\n\n[참고 글 — 우리 파서가 이 쪽에서 뽑은 글, 정답 아님]\n이 참고 글은 이미지가 아니라 우리 파서가 "
        "미리 뽑은 글이다. 이미지에서 실제로 보이는 내용만 옮기고, 참고 글에 있지만 이미지로 확인할 수 없는 "
        "내용은 베끼지 마라. 철자·숫자가 헷갈릴 때(0과 O, 1과 l 등)만 확인용으로 써라.\n"
        + (ref_text.strip() if ref_text and ref_text.strip() else "(참고 글 없음 — 이미지만 보고 옮겨라)")
    )
    prompt_text = p_gold + ref_block + _tail("gold_draft")
    combo_sha = V.sha(img_bytes + ref_block.encode("utf-8", "ignore"))  # 참고 글이 열쇠에 섞임 — 파싱이 바뀌면 새 캐시
    if fake_llm():  # S7c — 설정 객체(옛 env == "1") · 네트워크·캐시 0 모의 응답(경로 연기 시험 — c0 10-14)
        from common.ai.llm import fake_reply

        text, u = fake_reply([{"role": "user", "content": [{"type": "text", "text": prompt_text}]}])
        return text, {"model": "fake", "fake": True, "cached": False}
    dpath = raw_vlm_path(V.raw_root(), model_dir, "gold", "v1", p_gold, combo_sha)
    if dpath.exists():
        rec = json.loads(dpath.read_text(encoding="utf-8"))
        return rec["text"], {**rec["provenance"], "cached": True}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 쪽 옮기기 없이", "cached": False}
    data, px = V._png(img_bytes)
    deadline = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체(칸 기본값 360)
    t0 = time.perf_counter()
    try:
        text, u = A.complete(
            "vlm",
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=None,
            timeout=deadline,
            agent="gold_draft",
        )
    except A.ModelUnavailable as ex:
        return "", {"error": str(ex)[:200], "ms": round((time.perf_counter() - t0) * 1000), "cached": False}
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        return "", {"error": "빈 응답", "ms": ms, "cached": False}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
    prov = {
        "model": model,
        "prompt_id": _prompt_id("draft", "v1", p_gold),
        "px": px,
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
    }
    dpath.parent.mkdir(parents=True, exist_ok=True)
    dpath.write_text(json.dumps({"text": text, "provenance": prov}, ensure_ascii=False), encoding="utf-8")
    return text, {**prov, "cached": False}


MERMAID_BLOCK_RX = r"```mermaid\s*\n(.*?)```"
_EDGE_RX = (
    r'(\w+)(?:\["?([^"\]]*)"?\]|\(([^)]*)\)|\{([^}]*)\})?\s*-+>\s*(?:\|"?([^|"]*)"?\|)?\s*'
    r'(\w+)(?:\["?([^"\]]*)"?\]|\(([^)]*)\)|\{([^}]*)\})?'
)


def parse_mermaid(block):
    """Mermaid flowchart 글자 → edges[{from,to,label}](노드 id 대신 보이는 이름). to_mermaid()의 역 — n0["이름"] 뿐 아니라
    VLM이 흔히 쓰는 A(이름)·A{이름}·라벨 없는 id도 받음."""
    import re

    names, edges = {}, []
    for m in re.finditer(_EDGE_RX, block):
        a, b = m.group(1), m.group(6)
        la, lb = m.group(2) or m.group(3) or m.group(4), m.group(7) or m.group(8) or m.group(9)
        if la:
            names[a] = la
        if lb:
            names[b] = lb
        edges.append((a, b, (m.group(5) or "").strip() or None))
    return [{"from": names.get(a, a), "to": names.get(b, b), "label": lab} for a, b, lab in edges]


def _vlm_check_mermaid(img_bytes, nodes):
    """2차 점검(사용자 10-14) — 옮긴 화살표는 안 보여 주고 단계 이름만 줘서(앵커링 방지) 원본 이미지에 '각 단계에서 나가는
    화살표'를 다시 묻는다. → (응답 dict 또는 None, provenance). _vlm_gold와 같은 원본 층 캐시(열쇠 = 이미지 + 단계 이름)."""
    import base64
    import time

    from common.ai import adk as A
    from common.ai.agent_prompts import tail as _tail
    from common.ai.agent_prompts import template as _template
    from common.ai.llm import parse_json
    from pipeline.shared.artifacts import prompt_id as _prompt_id
    from pipeline.shared.artifacts import raw_vlm_path
    from pipeline.transform.figures import vlm_page as V

    vlm = C.cfg().models.vlm  # S7c — 설정 객체
    base, model = vlm.base_url, vlm.model
    p_chk = _template("mermaid_check", "check")
    block = "\n\n[단계 이름]\n" + "\n".join(f"- {n}" for n in nodes)
    prompt_text = p_chk + block + "\n\n" + _tail("mermaid_check")
    if fake_llm():  # S7c — 설정 객체(옛 env == "1") · 네트워크·캐시 0 모의 응답(경로 연기 시험 — c0 10-14)
        from common.ai.llm import fake_reply

        text, u = fake_reply([{"role": "user", "content": [{"type": "text", "text": prompt_text}]}])
        return None, {"model": "fake", "fake": True, "error": "LLM_FAKE — 점검 없이(1차 그대로)"}
    dpath = raw_vlm_path(V.raw_root(), V._model_dir(model), "mmdchk", "v1", p_chk, V.sha(img_bytes + block.encode("utf-8")))
    if dpath.exists():
        rec = json.loads(dpath.read_text(encoding="utf-8"))
        text, prov = rec["text"], {**rec["provenance"], "cached": True}
    else:
        if not (base and model):
            return None, {"error": "VLM 미설정 — 점검 없이"}
        data, px = V._png(img_bytes)
        t0 = time.perf_counter()
        try:
            text, u = A.complete(
                "vlm",
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                        ],
                    }
                ],
                temperature=0,
                max_tokens=None,
                timeout=pc.cfg().transform.vlm.deadline,
                agent="mermaid_check",
            )  # S7c — 설정 객체
        except A.ModelUnavailable as ex:
            return None, {"error": str(ex)[:200]}
        if not text.strip():
            return None, {"error": "빈 응답"}
        prov = {
            "model": model,
            "prompt_id": _prompt_id("check", "v1", p_chk),
            "px": px,
            "ms": round((time.perf_counter() - t0) * 1000),
            "in": u.get("prompt_tokens"),
            "out": u.get("completion_tokens"),
        }
        dpath.parent.mkdir(parents=True, exist_ok=True)
        dpath.write_text(json.dumps({"text": text, "provenance": prov}, ensure_ascii=False), encoding="utf-8")
    try:
        res = parse_json(text)
    except ValueError:
        return None, {**prov, "error": "JSON 아님"}
    return (res if isinstance(res, dict) else None), prov


def _nkey(s):
    return "".join(str(s).casefold().split())


def reconcile_mermaid(edges, check):
    """1차 Mermaid edges ↔ 2차 블라인드 답(check) → (최종 edges 또는 None(흐름도 아님 → 블록 뺌), 메모 목록).
    규칙: 둘 다 본 화살표는 유지 · 2차에서만 보인 화살표는 추가(되돌림·갈림길을 1차가 자주 놓침 — 10-14 실측 재현율 86%) ·
    1차에만 있고 2차가 그 출발 단계에 답했는데 안 나온 화살표는 뺌(출발 단계 답이 아예 없으면 1차 그대로).
    전부 메모로 남겨 검수자가 확인(정답 초안이라 사람이 최종 판단)."""
    if not check:
        return edges, []
    if check.get("is_flowchart") is False:
        return None, ["흐름도 아님(2차 점검) → Mermaid 뺌"]
    names = {_nkey(e[k]): e[k] for e in edges for k in ("from", "to")}

    def canon(n):  # 2차 답의 이름 → 1차 이름(띄어쓰기·대소문자·한쪽 포함)
        k = _nkey(n)
        if k in names:
            return names[k]
        hit = [v for kk, v in names.items() if k and (k in kk or kk in k)]
        return hit[0] if len(hit) == 1 else n

    nxt = check.get("next") if isinstance(check.get("next"), dict) else {}
    answered, blind = set(), {}
    for src, outs in nxt.items():
        s = canon(src)
        answered.add(s)
        for o in outs if isinstance(outs, list) else []:
            to = o.get("to") if isinstance(o, dict) else o
            if to:
                blind[(s, canon(to))] = (o.get("label") if isinstance(o, dict) else None) or None
    first = {(e["from"], e["to"]): e.get("label") for e in edges}
    final, notes = [], []
    for k, lab in first.items():
        if k in blind or k[0] not in answered:
            final.append({"from": k[0], "to": k[1], "label": lab or blind.get(k)})
        else:
            notes.append(f"뺌(2차 점검에서 안 보임): {k[0]} → {k[1]}")
    for k, lab in blind.items():
        if k not in first:
            final.append({"from": k[0], "to": k[1], "label": lab})
            notes.append(f"추가(2차 점검에서만 보임): {k[0]} → {k[1]}")
    agree = sum(1 for k in first if k in blind)
    added, dropped = sum(n.startswith("추가") for n in notes), sum(n.startswith("뺌") for n in notes)
    notes.insert(0, f"Mermaid 2차 점검: 1차 화살표 {len(first)}개 중 {agree}개 일치 · 추가 {added} · 뺌 {dropped}")
    return final, notes


def render_mermaid_png(edges, path):
    """edges → 흐름도 PNG(검수자가 원본 이미지와 나란히 대조, 사용자 10-14). 새 패키지 없이 PyMuPDF로 직접 그림:
    단계 = 시작 단계(들어오는 화살표 없음)에서의 거리로 왼→오 층 배치, 앞으로 가는 화살표 = 직선, 되돌아가는 화살표 = 아래로 도는
    빨간 꺾은선. ponytail: 단순 층 배치 — 단계 수십 개·교차 많은 그림은 겹칠 수 있음(검수 보조용, 정답 판정에는 안 씀)."""
    import fitz

    nodes = []
    for e in edges:
        for k in ("from", "to"):
            if e[k] not in nodes:
                nodes.append(e[k])
    if not nodes:
        return None
    incoming = {e["to"] for e in edges}
    level = {n: 0 for n in nodes if n not in incoming} or {nodes[0]: 0}
    frontier = list(level)
    while frontier:  # BFS 거리(사이클은 처음 방문만 — 되돌림 화살표는 층을 안 늘림)
        nxt = []
        for n in frontier:
            for e in edges:
                if e["from"] == n and e["to"] not in level:
                    level[e["to"]] = level[n] + 1
                    nxt.append(e["to"])
        frontier = nxt
    for n in nodes:
        level.setdefault(n, 0)
    cols = {}
    for n in nodes:
        cols.setdefault(level[n], []).append(n)
    bw, bh, gx, gy = 130, 36, 60, 34
    W = 40 + (max(cols) + 1) * (bw + gx)
    H = 70 + max(len(v) for v in cols.values()) * (bh + gy) + 60
    font = "C:/Windows/Fonts/malgun.ttf" if Path("C:/Windows/Fonts/malgun.ttf").exists() else None
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)
    fn = "helv"
    if font:
        pg.insert_font(fontname="kr", fontfile=font)
        fn = "kr"
    rect = {}
    for lv, ns in cols.items():
        for i, n in enumerate(ns):
            r = fitz.Rect(30 + lv * (bw + gx), 50 + i * (bh + gy), 30 + lv * (bw + gx) + bw, 50 + i * (bh + gy) + bh)
            rect[n] = r
            pg.draw_rect(r, color=(0, 0, 0), fill=(0.93, 0.95, 1), width=0.8)
            pg.insert_textbox(fitz.Rect(r.x0 + 3, r.y0 + 9, r.x1 - 3, r.y1), str(n), fontsize=9, fontname=fn, align=1)

    def head(tip, frm, color):
        v = fitz.Point(tip.x - frm.x, tip.y - frm.y)
        ln = max((v.x**2 + v.y**2) ** 0.5, 1e-6)
        u = fitz.Point(v.x / ln, v.y / ln)
        b = fitz.Point(tip.x - u.x * 9, tip.y - u.y * 9)
        pg.draw_polyline(
            [fitz.Point(b.x - u.y * 4, b.y + u.x * 4), tip, fitz.Point(b.x + u.y * 4, b.y - u.x * 4)],
            color=color,
            fill=color,
            closePath=True,
        )

    for k, e in enumerate(edges):
        ra, rb = rect[e["from"]], rect[e["to"]]
        lab = e.get("label")
        if level[e["to"]] > level[e["from"]]:
            pa, pb = fitz.Point(ra.x1, (ra.y0 + ra.y1) / 2), fitz.Point(rb.x0, (rb.y0 + rb.y1) / 2)
            pg.draw_line(pa, pb, color=(0, 0, 0), width=1)
            head(pb, pa, (0, 0, 0))
            mid = fitz.Point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2 - 4)
        else:  # 되돌아가는(또는 같은 층) 화살표 — 아래로 돌아감
            y = H - 30 - (k % 3) * 8
            pa, pb = fitz.Point((ra.x0 + ra.x1) / 2, ra.y1), fitz.Point((rb.x0 + rb.x1) / 2 + 8, rb.y1)
            pg.draw_polyline([pa, fitz.Point(pa.x, y), fitz.Point(pb.x, y), pb], color=(0.75, 0, 0), width=1)
            head(pb, fitz.Point(pb.x, pb.y + 10), (0.75, 0, 0))
            mid = fitz.Point((pa.x + pb.x) / 2, y - 3)
        if lab:
            pg.insert_text(mid, str(lab), fontsize=8, fontname=fn, color=(0.2, 0.2, 0.6))
    pg.get_pixmap(dpi=110).save(str(path))
    return path


def verify_mermaid(img_bytes, text):
    """쪽 초안의 Mermaid 블록마다 2차 블라인드 점검 → (고친 쪽 글, 메모, 최종 edges 목록[블록별]). 끄기: GOLD_DRAFT_MERMAID_CHECK=0."""
    import re

    if not pc.cfg().eval.gold_draft_mermaid_check or "```mermaid" not in text:  # S7c — 설정 객체(옛 .strip() in ("0","false","no")면 끔)
        return text, [], []
    from pipeline.transform.figures.mermaid import to_mermaid

    notes, finals = [], []

    def fix(m):
        edges = parse_mermaid(m.group(1))
        if not edges:
            return m.group(0)
        nodes = list(dict.fromkeys(n for e in edges for n in (e["from"], e["to"])))
        check, prov = _vlm_check_mermaid(img_bytes, nodes)
        if check is None and prov.get("error"):
            notes.append(f"Mermaid 2차 점검 못 함: {prov['error']}")
        final, nts = reconcile_mermaid(edges, check)
        notes.extend(nts)
        if final is None:
            return ""
        finals.append(final)
        return "```mermaid\n" + to_mermaid(final) + "\n```\n"

    return re.sub(MERMAID_BLOCK_RX, fix, text, flags=re.S), notes, finals


def draft_doc(path, max_pages, refs=(), source=False):
    """원본 1건 → (마크다운 초안, 쪽 수, 실패한 쪽 번호 목록, 모델, 쪽별 글 목록). refs[i] = (i+1)쪽의 파싱 참고 글
    (모자라면 그 쪽은 참고 없이). source=True(GS3 docx) — refs가 문서 원문 글자."""
    from pipeline.transform.figures import vlm_page as V

    pages = V.pages_of(path)[:max_pages]

    def one(arg):
        i, img = arg
        ref = refs[i - 1] if i - 1 < len(refs) else ""
        with _vlm_slot():
            text, prov = _vlm_gold(img, ref, source=True) if source else _vlm_gold(img, ref)
        text, notes, finals = verify_mermaid(img, text)  # 사용자 10-14 — Mermaid를 원본 이미지에 블라인드 질문으로 2차 점검
        return i, text, prov, notes, finals

    texts, failed, model, mermaid = [], [], None, []
    for i, text, prov, notes, finals in _pool_map(one, list(enumerate(pages, 1)), _vlm_workers()):  # 쪽 동시 요청(순서 보존)
        model = model or prov.get("model")
        if not text.strip():
            failed.append(i)
        if notes or finals:
            mermaid.append((i, notes, finals))
        texts.append(text.strip())
    return "\n\n".join(t for t in texts if t) + "\n", len(pages), failed, model, texts, mermaid


def check_rows(doc_name, page_texts, refs):
    """GS2 ④ — VLM 초안과 파싱 참고 글이 쪽마다 갈리는 곳(숫자·표 칸·짧은 줄)을 '확인할 곳'으로(score_gold.canon과
    같은 정규화 — 정답이 파서 쪽으로 기우는 것 방지, 사람은 여기만 보면 됨). 참고 글이 없거나(그 쪽 참고 없음) 초안이
    빈 쪽은 비교할 게 없어 건너뜀."""
    from pipeline.eval import score_gold as SG
    from pipeline.transform.represent import parse_qa as Q

    rows = []
    for i, draft in enumerate(page_texts, 1):
        ref = refs[i - 1] if i - 1 < len(refs) else ""
        if not ref.strip() or not draft.strip():
            continue
        cdraft, cref = SG.canon(draft), SG.canon(ref)
        ref_nows = Q.norm_nows(cref)
        for n in sorted(Q.out_nums(cdraft) - Q.out_nums(cref)):
            rows.append([doc_name, i, "숫자", n])
        for t in SG.md_tables(cdraft):
            for row in t:
                for cell in row:
                    c = cell.strip()
                    if c and len(c) <= CHECK_SPAN_MAX and Q.norm_nows(c) not in ref_nows:
                        rows.append([doc_name, i, "표 칸", c])
        for ln in draft.splitlines():
            s = ln.strip()
            if not s or s.startswith("|") or len(s) > CHECK_LINE_MAX:
                continue
            if Q.norm_nows(SG.canon(s)) not in ref_nows:
                rows.append([doc_name, i, "줄", s])
    return rows


def run(src, out, max_pages, parse_dir=None):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    files = sorted(x for x in Path(src).rglob("*") if x.is_file())
    docs = [p for p in files if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMG_EXT]
    pdfs = {p: office_pdf(p, out / "_pdf") for p in files if p.suffix.lower() in OFFICE_EXT}  # GS3 — docx → PDF(soffice)
    docs += [p for p, pdf in pdfs.items() if pdf]
    refs_of = {p: source_pages(pdfs[p]) if p in pdfs else ref_pages(parse_dir, p.name) for p in docs}

    def one_doc(p):
        return draft_doc(pdfs.get(p) or p, max_pages, refs_of[p], source=p in pdfs)

    results = dict(zip(docs, _pool_map(one_doc, docs, min(DOC_WORKERS, _vlm_workers()))))  # 문서 동시 — 기록은 아래에서 원래 순서대로
    for p in files:
        if p not in results:
            why = "soffice 없음·변환 실패 — PDF로 저장해 다시" if p in pdfs else "PDF로 저장해 다시(PDF·이미지·docx만 대상)"
            rows.append([p.name, "skipped", 0, "", "", why, ""])
            continue
        md, n, failed, model, page_texts, mmd = results[p]
        refs = refs_of[p]
        (out / f"{p.name}.md").write_text(md, encoding="utf-8")
        memo = ""
        crows = check_rows(p.name, page_texts, refs)
        for page, notes, finals in mmd:
            crows += [[p.name, page, "흐름도", n] for n in notes]
            for k, fe in enumerate(finals):  # 검수자가 원본과 나란히 볼 렌더 그림
                png = render_mermaid_png(fe, out / f"{p.name}.p{page}.flow{k + 1}.png")
                if png:
                    crows.append([p.name, page, "흐름도", f"Mermaid 렌더 → {png.name}(원본 쪽 이미지와 나란히 대조)"])
        if crows:
            cf = out / f"{p.name}.check.csv"
            with open(cf, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["문서", "쪽", "구분", "확인할 곳(VLM 초안, 참고 글과 다름 · 흐름도 2차 점검)"])
                w.writerows(crows)
            memo = f"확인할 곳 {len(crows)}건 → {cf.name}"
        rows.append([p.name, "draft", n, model or "", " ".join(map(str, failed)), memo, ""])
        print(f"[gold_draft] {p.name}: {n}쪽" + (f" · 실패 쪽 {failed}" if failed else "") + (f" · {memo}" if memo else ""), flush=True)
    vf = out / "values.csv"
    if not vf.exists():  # 검수자가 채운 값을 다시 실행해도 덮지 않음
        vf.write_text("문서,라벨,값\n", encoding="utf-8-sig")
    with open(out / "review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["문서", "상태", "쪽 수", "모델", "실패 쪽", "메모", "검수자"])
        w.writerows(rows)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src")
    ap.add_argument("--out", default="output/gold_draft")
    ap.add_argument(
        "--with-parse",
        default="output/parse",
        help="우리 파싱 결과 폴더(_rep 포함) — 쪽별 참고 글로 씀(GS2). 없는 경로면 참고 없이 GS1처럼 이미지만 보고 옮김",
    )
    a = ap.parse_args(argv)
    if not a.src:
        ap.error("--src 필요")
    parse_dir = Path(a.with_parse) if a.with_parse and Path(a.with_parse).exists() else None
    rows = run(a.src, Path(a.out), pc.cfg().eval.gold_draft_max_pages, parse_dir)  # S7c — 설정 객체(칸 기본값 30)
    print(
        f"[gold_draft] 초안 {sum(r[1] == 'draft' for r in rows)}건 · 건너뜀 {sum(r[1] == 'skipped' for r in rows)}건"
        f" · 파싱 참고 {'씀(' + str(parse_dir) + ')' if parse_dir else '없음(GS1처럼 이미지만)'} → {a.out}"
        " (검수 뒤 reviewed 문서만 정답 폴더로)",
        flush=True,
    )


if __name__ == "__main__":
    utf8_stdout()
    sys.exit(main() or 0)
