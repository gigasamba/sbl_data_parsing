"""맥락 기록만(LLM 0회) — 규칙 흐름이 이미 계산한 문서·쪽 신호와 규칙 결정(이유)을
rep["context"](신호)·rep["decisions"](결정 목록)로 남긴다(보고서 표시·나중 파싱 에이전트의 바탕).
새 엔진 실행·VLM 호출 없음 — 이미 계산·캐시된 값만 모은다(원문 전체는 안 담음)."""

from collections import Counter
from pathlib import Path

MAX_PAGES = 200  # 쪽 신호 상한(쪽이 아주 많은 문서에서 rep 크기 과도 증가 방지) — 넘으면 앞 MAX_PAGES쪽만, truncated 표시


def _page_signals(doc_path):
    """쪽 신호(scan_page_vlm.page_signals — 원본 sha 캐시라 다시 불러도 싸다) + scan_pages_detail(스캔 판정 이유)·
    rotation_info(filter_and_rotate 회전 기록)를 쪽마다 합침.
    PDF가 아니거나 원본이 없으면 빈 목록."""
    if not doc_path or not Path(doc_path).exists():
        return [], False
    from pipeline.transform.figures.scan_page_vlm import page_signals, rotation_info, scan_pages_detail

    sig = page_signals(doc_path)
    if not sig:
        return [], False
    scan = scan_pages_detail(doc_path)
    rot = rotation_info(doc_path)
    truncated = len(sig) > MAX_PAGES
    pages = []
    for r in sig[:MAX_PAGES]:
        p = r["page"]
        entry = dict(r)
        if p in scan:
            entry["scan_reason"] = scan[p]
        if p in rot and rot[p].get("angle"):
            entry["rotation"] = rot[p]["angle"]
        pages.append(entry)
    return pages, truncated


def _engine_summary(dd, cands, tried):
    """엔진별 요약 — qa.json(parse_scoring.score_engine이 이미 계산한 값)·runs.jsonl(tried_of)에서만 모음(새로 계산 안 함).
    ok·chars·acc(cross_recall 또는 value_recall을 doc_accuracy가 이미 고른 값)·sec."""
    out = {}
    for c in cands:
        e = c["engine"]
        m = dd["engines"].get(e) or {}
        t = tried.get(e) or {}
        out[e] = {"ok": c["ok"], "acc": c.get("acc"), "chars": m.get("chars"), "sec": t.get("sec")}
    return out


def build_context(doc_path, dd, cands, rep):
    """문서·쪽 신호 — format·쪽 수·표 수·엔진별 요약(이미 계산된 값만) + PDF면 쪽별 신호(글자층 글자 수·이미지
    면적·도형·OCR 신뢰도 대용(garbage_ratio)·회전·스캔 판정 이유)."""
    ctx = {
        "format": dd.get("format"),
        "pages": dd.get("pages"),
        "tables": len(rep.get("tables") or []),
        "engines": _engine_summary(dd, cands, (rep.get("rep") or {}).get("tried") or {}),
    }
    pages, truncated = _page_signals(doc_path)
    if pages:
        ctx["page"] = pages
        if truncated:
            ctx["page_truncated"] = MAX_PAGES
    return ctx


def _ocr_fallback(doc_path, dd, stack):
    """스캔 쪽 신호(scan_page_vlm.scan_pages, 캐시 재사용 — OCR 엔진은 안 합치고 쪽 VLM이 그 쪽을 채움) —
    .pdf_text 문서 안에 스캔 쪽이 있으면 True. registry(엔진 등록,
    무거운 임포트)는 건드리지 않고 stack.json에 이미 적힌 .pdf_image 목록만 본다."""
    if dd.get("format") != ".pdf_text" or not stack["parse"].get(".pdf_image") or not doc_path:
        return None
    try:
        from pipeline.transform.figures.scan_page_vlm import scan_pages

        return bool(scan_pages(doc_path))
    except Exception:
        return True


def build_decisions(rep, dd, stack, feats, doc_path):
    """규칙 결정 + 이유 — represent()가 이미 계산한 값만 읽어 짧은 문장으로(원문 없음, 결정마다 하나,
    해당 없는 결정 지점은 안 넣어 목록이 자연히 짧게 유지됨)."""
    r = rep.get("rep") or {}
    d = []

    want = stack["parse"].get(dd.get("format"), [])
    d.append(
        {
            "step": "engine_scope",
            "choice": "stack",
            "reason": "stack.json 형식별 목록만(PE1 — pl-03 10-30부터 이 하나뿐)",
            "inputs": {"format": dd.get("format"), "stack_pool": want},
        }
    )

    fb = _ocr_fallback(doc_path, dd, stack)
    if fb is not None:
        d.append(
            {
                "step": "ocr_fallback",
                "choice": fb,
                "reason": "스캔 쪽 감지 — 그 쪽만 쪽 VLM 글로 채움(10-29, OCR 엔진은 안 합침)" if fb else "스캔 쪽 없음",
                "inputs": {"ocr_pool": stack["parse"].get(".pdf_image") or []},
            }
        )

    scanned = [p["page"] for p in (rep.get("context") or {}).get("page", []) if p.get("scan_reason")]
    if scanned:
        reasons = Counter(p["scan_reason"] for p in rep["context"]["page"] if p.get("scan_reason"))
        d.append(
            {
                "step": "page_scan",
                "choice": f"{len(scanned)}쪽",
                "reason": ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items())),
                "inputs": {"pages": scanned[:20]},
            }
        )

    sf = r.get("scan_fill")
    if sf is not None:
        filled = sf.get("filled") or {}
        d.append(
            {
                "step": "scan_fill",
                "choice": f"{len(filled)}쪽 채움" if filled else "채움 없음",
                "reason": sf.get("skip") or (f"OCR 엔진({next(iter(filled.values()))})으로 채움" if filled else "스캔 쪽 없음 또는 건너뜀"),
                "inputs": {"filled_pages": list(filled)[:20], "page_skip": list((sf.get("page_skip") or {}).items())[:20]},
            }
        )

    cand_list = r.get("candidates") or []
    ok_cands = [c for c in cand_list if c.get("ok")]
    best_acc = r.get("acc")
    tie = sum(1 for c in ok_cands if c.get("acc") == best_acc) > 1
    d.append(
        {
            "step": "representative",
            "choice": r.get("engine"),
            "reason": "스택 엔진 전부 실패 — 스택 밖 대체" if r.get("fallback") else ("정확도 동률 — 스택 순서" if tie else "최고 정확도"),
            "inputs": {
                "candidates": [{"engine": c["engine"], "ok": c["ok"], "acc": c.get("acc")} for c in cand_list],
                "low_n": r.get("low_n"),
            },
        }
    )

    tf = r.get("table_fix") or {}
    d.append(
        {
            "step": "table_fix",
            "choice": f"헤더 {tf.get('headers', 0)}건·탭 행 {tf.get('tab_rows', 0)}건",
            "reason": "표 머리글 보정(rep-fix)",
            "inputs": tf,
        }
    )

    std = r.get("standardize") or {}
    d.append(
        {
            "step": "standardize",
            "choice": "on",
            "reason": f"기호·첨자 표준화 {std.get('changed', 0)}건(SI20·AD46⑤)",
            "inputs": {"changed": std.get("changed", 0)},
        }
    )

    d.append(
        {
            "step": "table_std",
            "choice": "on",
            "reason": "표 표준 형식(AD23·SI20③)",
            "inputs": {"tables": len(rep.get("tables_std") or [])},
        }
    )

    if "figures" in feats:
        post = rep.get("post") or {}
        d.append(
            {
                "step": "figures",
                "choice": f"{post.get('figures', 0)}건",
                "reason": "VLM_FIGURES_MAX 상한 걸림(AD21①)" if post.get("figures_capped") else "상한 안 걸림",
                "inputs": {"skip_reasons": post.get("figures_skip_reasons") or {}},
            }
        )

    fused = rep.get("fused") or {}
    d.append(
        {
            "step": "fuse",
            "choice": "on",
            "reason": "조각 단위 융합(AD29 P1)",
            "inputs": {"facts": len(fused.get("facts") or []), "conflicts": len(fused.get("conflicts") or [])},
        }
    )

    return d


def attach(rep, dd, cands, stack, feats, doc_path):
    """represent()에서 부르는 진입점 — rep["context"]·rep["decisions"]를 채운다."""
    rep["context"] = build_context(doc_path, dd, cands, rep)
    rep["decisions"] = build_decisions(rep, dd, stack, feats, doc_path)
