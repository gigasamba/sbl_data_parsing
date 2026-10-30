#!/usr/bin/env python3
"""QA1 — 구조 의존 질문-답변 초안(VLM 초안 + 사람 검수, 사용자 10-14). 개발 서버에서 내부 VLM으로 실행(원문은 밖으로 안 나감).

파싱·검색이 표·그래프·흐름도의 **구조를 정확히 읽어야만** 맞출 수 있는 질문을 쪽 이미지에서 VLM이 만든다:
  table_cell  — 표의 행 라벨 × 열 머리글 칸 값(병합 칸은 덮는 모든 칸에 같은 값)
  chart_value — 그래프의 x값(범주) → y값(눈금 사이 어림이면 범위 + confidence low → 자동 채점 키워드 없음)
  flow_next · flow_input · flow_order — 흐름도의 다음 단계 · 단계에 들어가는 물질·조건 · 단계 순서
gold_draft(쪽 옮겨 적기)와는 다른 지시문(prompts/qa_draft)·캐시 열쇠 — 파싱 VLM·gold_draft 캐시와 동작에 영향 없음.

산출(--out, 기본 output/qa_draft):
  questions.jsonl — 평가 질문 형식(auto_questions·mcp_eval load_question_items와 같은 칸: id·category·question·answer·
    docs·doc·gold_evidence[{file,page,section,snippet}] + answer_keywords(confidence high만)·evidence·confidence·
    status=draft·gold_source) — 사람 검수 전 후보, 정답셋에 바로 넣지 않음.
  review.csv — 문항마다 한 줄(질문·답·근거·확신·상태 draft). 검수자가 원본을 보며 질문·답을 고치고 상태를 reviewed
    (또는 rejected)로 바꿈.
검수 뒤: `python -m pipeline.eval.qa_draft --finalize <out>` → review.csv의 reviewed 줄만(고친 질문·답 반영)
  questions_reviewed.jsonl로 — 이것만 평가(mcp_eval --questions 등)에 쓴다.
대상: PDF·이미지(png·jpg·tif 등)·docx/doc(GS3, 사용자 10-15 — gold_draft.office_pdf로 soffice PDF 변환본의 쪽 이미지(본문 속
  그림 포함)로 문항을 만들고, 그래프 값 확인은 변환본 글자층으로. soffice 없음·변환 실패면 건너뜀). 그 밖(xlsx·pptx)은
  건너뛰고 review.csv에 표시 안 함(로그에 'PDF로 저장해 다시').
비용: 쪽마다 VLM 1회(캐시 재사용) · QA_DRAFT_MAX_PAGES(기본 20) 문서당 쪽 상한 · QA_DRAFT_PER_PAGE(기본 5) 쪽당 문항 상한 ·
  유료 외부 모델이면 LLM_MAX_CALLS·LLM_BUDGET_USD를 함께(개발 중엔 문서 몇 건으로 기능 시험만).
사용: python -m pipeline.eval.qa_draft --src <원본 폴더> [--out output/qa_draft]
      python -m pipeline.eval.qa_draft --finalize output/qa_draft
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from common.ai.guard import fake_llm
from common.config import settings as C  # S7c — 설정 객체(common 칸: VLM_*·LLM_FAKE)
from common.core.console import utf8_stdout
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸: VLM_DEADLINE·QA_DRAFT_*)

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
TYPES = ("table_cell", "chart_value", "flow_next", "flow_input", "flow_order")
REVIEW_HDR = ["id", "문서", "쪽", "유형", "질문", "답", "대상(표·그래프·흐름도)", "근거", "확신", "상태", "검수 메모"]
EVIDENCE_KEYS = ("row", "col", "x", "series", "step", "related")
DOC_WORKERS = 2  # ponytail: 동시에 펼치는 문서 수(쪽 이미지 메모리 상한 — 문서당 최대 QA_DRAFT_MAX_PAGES쪽 × 2)


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


def _vlm_qa(img_bytes, max_items):
    """쪽 1장 → (VLM 응답 글자, provenance). gold_draft._vlm_gold와 같은 호출부 모양(template()+tail(), 원본 층 캐시)."""
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
    p_qa = _template("qa_draft", "qa").replace("{max_items}", str(max_items))
    prompt_text = p_qa + "\n\n" + _tail("qa_draft")
    if fake_llm():  # S7c — 설정 객체(옛 env == "1") · 네트워크·캐시 0 모의 응답(경로 연기 시험 — c0 10-14)
        from common.ai.llm import fake_reply

        text, u = fake_reply([{"role": "user", "content": [{"type": "text", "text": prompt_text}]}])
        return text, {"model": "fake", "fake": True, "cached": False}
    dpath = raw_vlm_path(V.raw_root(), model_dir, "qa", "v1", p_qa, V.sha(img_bytes))
    if dpath.exists():
        rec = json.loads(dpath.read_text(encoding="utf-8"))
        return rec["text"], {**rec["provenance"], "cached": True}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 문항 없이", "cached": False}
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
            agent="qa_draft",
        )
    except A.ModelUnavailable as ex:
        return "", {"error": str(ex)[:200], "ms": round((time.perf_counter() - t0) * 1000), "cached": False}
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        return "", {"error": "빈 응답", "ms": ms, "cached": False}  # 실패·빈 답은 캐시에 안 남김(다음 실행에서 다시)
    prov = {
        "model": model,
        "prompt_id": _prompt_id("qa", "v1", p_qa),
        "px": px,
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
    }
    dpath.parent.mkdir(parents=True, exist_ok=True)
    dpath.write_text(json.dumps({"text": text, "provenance": prov}, ensure_ascii=False), encoding="utf-8")
    return text, {**prov, "cached": False}


def parse_items(text, max_items, page_text=None):
    """VLM 응답 → 검증된 문항 목록. 형식이 깨졌거나 칸이 빠진 문항·모르는 유형·같은 질문 중복은 버림(초안이라 조용히)."""
    from common.ai.llm import parse_json

    try:
        items = parse_json(text).get("items") or []
    except (ValueError, AttributeError):
        return []
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        q, a, t = str(it.get("question") or "").strip(), str(it.get("answer") or "").strip(), it.get("type")
        if not q or not a or t not in TYPES or q in seen:
            continue
        if len(a) >= 2 and a.casefold() in q.casefold():  # 답이 질문에 이미 들어 있음(실측 10-14: "A와 B 사이 단계는?" → B)
            continue
        seen.add(q)
        ev = it.get("evidence") if isinstance(it.get("evidence"), dict) else {}
        snippet = str(it.get("snippet") or "").strip()[:200]
        conf = "high" if it.get("confidence") == "high" else "low"
        # 그래프 값 high = 이미지에 숫자 라벨이 적혀 있을 때만. PDF 글자층이 있으면 그것으로 확인(모델이 지어낸 값을 snippet에도
        # 적어 snippet 검사를 통과한 실측 10-14 — 글자층은 모델이 못 꾸밈), 글자층이 없으면(스캔·이미지) snippet으로.
        if t == "chart_value" and conf == "high" and not _label_visible(a, page_text if page_text is not None else snippet):
            conf = "low"  # 실측 10-14: 값 라벨 없는 막대를 눈대중으로 '48.75'처럼 지어내고 high — 이미지에 적힌 숫자(snippet)가 아니면 low
        out.append(
            {
                "type": t,
                "question": q,
                "answer": a,
                "object": str(it.get("object") or "").strip(),
                "evidence": {k: ev[k] for k in EVIDENCE_KEYS if ev.get(k) not in (None, "", [])},
                "snippet": snippet,
                "confidence": conf,
            }
        )
    # flow_* 는 흐름도에만 — 같은 대상(object)에 표·그래프 문항이 있으면 그 대상은 흐름도가 아님(실측 10-14: 막대그래프 x축 순서를
    # flow_order로 물음, 지시문으로 막아도 남음 → 코드로 버림)
    non_flow = {it["object"] for it in out if it["type"] in ("table_cell", "chart_value") and it["object"]}
    out = [it for it in out if not (it["type"].startswith("flow_") and it["object"] in non_flow)]
    return out[:max_items]


def _label_visible(answer, snippet):
    """그래프 값이 이미지에 숫자 라벨로 적혀 있는지 — 답의 첫 숫자가 snippet(이미지에 보이는 글자)에 그대로 있을 때만."""
    import re

    m = re.search(r"-?\d+(?:\.\d+)?", answer.replace(",", "").replace(" ", ""))
    # 글자층·snippet은 띄어쓰기를 지우면 '41 47 39'가 '414739'로 붙어 경계가 사라짐 — 천 단위 쉼표만 지움
    return bool(m and snippet and re.search(r"(?<![\d.])" + re.escape(m.group()) + r"(?![\d])", snippet.replace(",", "")))


def _ev_text(ev):
    return " · ".join(f"{k}={'/'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in ev.items())


def _value_labels(words):
    """쪽 낱말(get_text("words")) → 그래프 값 라벨일 수 있는 숫자 글자(공백 구분). 축 눈금은 뺀다 — 숫자 3개 이상이 같은 세로줄
    (오른쪽 끝 x가 같음, y축 눈금)이나 같은 가로줄(y가 같음, 숫자형 x축 눈금)에 늘어선 것(실측 10-14: 값 라벨 없는 막대를 모델이
    눈금 값 32.5·48.75로 답해 글자층 확인을 통과)."""
    import re

    nums = [w for w in words if re.fullmatch(r"[-+]?[\d.,]+%?", w[4]) and re.search(r"\d", w[4])]

    def lined(key):
        groups = {}
        for w in nums:
            groups.setdefault(round(key(w) / 3), []).append(w)
        return {id(w) for g in groups.values() if len(g) >= 3 for w in g}

    ticks = lined(lambda w: w[2]) | lined(lambda w: (w[1] + w[3]) / 2)
    return " ".join(w[4] for w in nums if id(w) not in ticks)


def _page_texts(path, n):
    """PDF 쪽별 값 라벨 숫자(축 눈금 뺌 — _value_labels) — 글자층이 거의 없는 쪽(스캔)·이미지 파일은 None(그때는 snippet으로)."""
    if Path(path).suffix.lower() != ".pdf":
        return [None] * n
    try:
        import fitz

        with fitz.open(path) as d:
            out = []
            for i in range(min(n, d.page_count)):
                pg = d[i]
                out.append(_value_labels(pg.get_text("words")) if len(pg.get_text().strip()) >= 20 else None)
    except Exception:
        return [None] * n
    return out + [None] * (n - len(out))


def draft_doc(path, max_pages, max_items):
    """원본 1건 → (문항 목록[(쪽, item)], 쪽 수, 실패한 쪽 번호, 모델)."""
    from pipeline.transform.figures import vlm_page as V

    pages = V.pages_of(path)[:max_pages]
    ptexts = _page_texts(path, len(pages))

    def one(img):
        with _vlm_slot():
            return _vlm_qa(img, max_items)

    found, failed, model = [], [], None
    for i, (text, prov) in enumerate(_pool_map(one, pages, _vlm_workers()), 1):  # 쪽 동시 요청(순서 보존)
        model = model or prov.get("model")
        if not text.strip():
            failed.append(i)
            continue
        found += [(i, it) for it in parse_items(text, max_items, ptexts[i - 1])]
    return found, len(pages), failed, model


def run(src, out, max_pages, max_items):
    out.mkdir(parents=True, exist_ok=True)
    qrows, rrows, summary = [], [], []
    from pipeline.eval.gold_draft import OFFICE_EXT, office_pdf

    docs, pdfs = [], {}
    for p in sorted(x for x in Path(src).rglob("*") if x.is_file()):
        ext = p.suffix.lower()
        if ext in OFFICE_EXT:  # GS3 — docx → PDF(soffice), pages and glyph layer come from it
            pdfs[p] = office_pdf(p, out / "_pdf")
            if pdfs[p] is None:
                print(f"[qa_draft] {p.name}: 건너뜀 — soffice 없음·변환 실패(PDF로 저장해 다시)", flush=True)
                continue
        elif ext != ".pdf" and ext not in IMG_EXT:
            print(f"[qa_draft] {p.name}: 건너뜀 — PDF로 저장해 다시(PDF·이미지·docx만 대상)", flush=True)
            continue
        docs.append(p)
    results = _pool_map(lambda p: draft_doc(pdfs.get(p) or p, max_pages, max_items), docs, min(DOC_WORKERS, _vlm_workers()))
    for p, (found, n, failed, model) in zip(docs, results):
        for k, (page, it) in enumerate(found):
            qid = f"qa-draft::{p.name}::p{page}::{k}"
            qrows.append(
                {
                    "id": qid,
                    "category": it["type"],
                    "question": it["question"],
                    "answer": it["answer"],
                    "answer_keywords": [it["answer"]] if it["confidence"] == "high" else [],
                    "docs": [p.name],
                    "doc": p.name,
                    "gold_evidence": [{"file": p.name, "page": page, "section": it["object"], "snippet": it["snippet"]}],
                    "evidence": it["evidence"],
                    "confidence": it["confidence"],
                    "auto": True,
                    "status": "draft",
                    "gold_source": f"VLM 초안({model or '모델 미상'}, 사람 검수 전)",
                }
            )
            rrows.append(
                [
                    qid,
                    p.name,
                    page,
                    it["type"],
                    it["question"],
                    it["answer"],
                    it["object"],
                    _ev_text(it["evidence"]),
                    it["confidence"],
                    "draft",
                    "",
                ]
            )
        summary.append((p.name, n, len(found), failed))
        print(f"[qa_draft] {p.name}: {n}쪽 · 문항 {len(found)}" + (f" · 실패 쪽 {failed}" if failed else ""), flush=True)
    with open(out / "questions.jsonl", "w", encoding="utf-8") as f:
        for r in qrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rf = out / "review.csv"
    if rf.exists():  # 검수자가 고친 줄은 다시 실행해도 덮지 않음(같은 id면 기존 줄 유지)
        with open(rf, encoding="utf-8-sig", newline="") as fh:
            old = {r["id"]: r for r in csv.DictReader(fh) if r.get("상태") not in ("", "draft")}
        rrows = [[old[r[0]][h] for h in REVIEW_HDR] if r[0] in old else r for r in rrows]
    with open(rf, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(REVIEW_HDR)
        w.writerows(rrows)
    return qrows, summary


def finalize(out):
    """review.csv의 reviewed 줄만 → questions_reviewed.jsonl(검수자가 고친 질문·답 반영, answer_keywords = 고친 답)."""
    out = Path(out)
    draft = {}
    for ln in (out / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            draft[r["id"]] = r
    with open(out / "review.csv", encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("상태", "").strip() == "reviewed"]
    kept = []
    for r in rows:
        base = draft.get(r["id"])
        if not base:
            continue
        q, a = r["질문"].strip(), r["답"].strip()
        kept.append(
            {
                **base,
                "question": q,
                "answer": a,
                "answer_keywords": [a],
                "status": "reviewed",
                "gold_source": base["gold_source"].replace("사람 검수 전", "사람 검수됨"),
                "review_note": r.get("검수 메모", ""),
            }
        )
    with open(out / "questions_reviewed.jsonl", "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return kept


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src")
    ap.add_argument("--out", default="output/qa_draft")
    ap.add_argument("--finalize", metavar="OUT", help="검수 뒤 — review.csv의 reviewed 줄만 questions_reviewed.jsonl로")
    a = ap.parse_args(argv)
    if a.finalize:
        kept = finalize(a.finalize)
        print(f"[qa_draft] 검수 확정 {len(kept)}문항 → {Path(a.finalize) / 'questions_reviewed.jsonl'}", flush=True)
        return 0
    if not a.src:
        ap.error("--src 필요(또는 --finalize)")
    qrows, summary = run(
        a.src,
        Path(a.out),
        pc.cfg().eval.qa_draft_max_pages,  # S7c — 설정 객체(칸 기본값 20·5)
        pc.cfg().eval.qa_draft_per_page,
    )
    by_type = {}
    for r in qrows:
        by_type[r["category"]] = by_type.get(r["category"], 0) + 1
    print(
        f"[qa_draft] 문서 {len(summary)}건 · 문항 {len(qrows)}개 {by_type} → {a.out}/questions.jsonl·review.csv (검수 뒤 --finalize)",
        flush=True,
    )


if __name__ == "__main__":
    utf8_stdout()
    sys.exit(main() or 0)
