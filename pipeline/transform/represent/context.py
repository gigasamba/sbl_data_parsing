"""W9·W11 — 그림 근처 본문 후보정(캡션 연결·본문 언급·값 일치/충돌 표시) + 그림 기록을 본문 청크 한 덩어리로 렌더.
원본: eval_hard_parse.link_context·value_check·render(설정 F_context)."""

import re

CAP = re.compile(r"^\s*(그림|Figure|Fig\.?|표|Table|도)\s*\d+\s*[\.:．:]")
FIGWORD = re.compile(r"그림|figure|fig\.|차트|그래프|흐름도|절차|도식|캡처|추이", re.I)
PAIR = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}-\d{1,4})(?!\d)[^0-9A-Z]{0,12}?(\d+(?:\.\d+)?)")  # ID 바로 뒤 한글 조사(B-05가)도


def link_context(f, doc_text):
    """캡션 1개 + 본문 언급 문장 → 그림 기록에 붙일 근처 맥락. 캡션 출처를 함께. f = figures.figures()가 낸 기록 하나."""
    cand = [("아래 줄", x) for x in f["after"]] + [("위 줄", x) for x in f["before"]]
    cap = next(((src, x) for src, x in cand if CAP.match(x)), None)
    if not cap:
        meta = ("시트 ", "슬라이드 제목", "메일 제목", "시트 제목")
        near = [("근처 셀·표 칸", x) for x in f["near"] if FIGWORD.search(x) and not x.startswith(meta)]
        near += [("슬라이드 제목", x) for x in f["near"] if x.startswith("슬라이드 제목")]
        near += [("시트 제목", x) for x in f["near"] if x.startswith("시트 제목") and FIGWORD.search(x)]
        near += [
            ("근처 셀·표 칸", x)
            for x in f["near"]
            if not x.startswith(meta) and len(x) < 40 and not re.fullmatch(r"항목|값|구분|비고|no\.?|#", x, re.I)
        ]
        cap = near[0] if near else None
    num = re.search(r"(그림|Figure|Fig\.?)\s*(\d+)", cap[1]) if cap else None
    sents = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", doc_text) if s.strip()]
    mentions = []
    if num:
        mentions = [s for s in sents if re.search(rf"(그림|Figure|Fig\.?)\s*{num.group(2)}(?!\d)", s) and not CAP.match(s)]
    mentions += [x for x in f["before"] + f["after"] if FIGWORD.search(x) and not CAP.match(x) and x not in mentions]
    mentions += [x for x in f["near"] if PAIR.search(x) and x not in mentions]
    return {"caption": cap[1] if cap else None, "caption_source": cap[0] if cap else None, "mentions": mentions[:4]}


def value_check(rec, ctx_lines):
    """VLM 그림 기록 값(rec['values']·rec['text']의 ID-값 쌍) ↔ 본문 근처 줄의 ID-값 쌍 → 일치·충돌·본문에만 있는 값."""
    fig = {}
    for v in rec.get("values") or []:
        m = re.search(r"\d+(?:\.\d+)?", str(v.get("value", "")))
        if v.get("label") and m:
            fig[str(v["label"]).strip()] = m.group(0)
    for m in PAIR.finditer(rec.get("text") or ""):
        fig.setdefault(m.group(1), m.group(2))
    ctx = {}
    for line in ctx_lines:
        for m in PAIR.finditer(line):
            ctx.setdefault(m.group(1), m.group(2))
    agree = {k: v for k, v in ctx.items() if k in fig and float(fig[k]) == float(v)}
    conflict = {k: {"그림": fig[k], "본문": v} for k, v in ctx.items() if k in fig and float(fig[k]) != float(v)}
    only_ctx = {k: v for k, v in ctx.items() if k not in fig}
    return {"agree": agree, "conflict": conflict, "context_only": only_ctx}


def render(f, rec, ctx=None, check=None):
    """그림 기록 → 자르지 않는 청크 1개 본문(V8) — [그림 id](종류)·캡션·요약·글자·값·연결·표·본문 언급·값 확인/충돌."""
    vals = ", ".join(f"{v.get('label')}={v.get('value')}{v.get('unit') or ''}" for v in rec.get("values") or [] if v.get("label"))
    edges = ", ".join(
        f"{e.get('from')} → {e.get('to')}" + (f"({e['label']})" if e.get("label") else "") for e in rec.get("edges") or [] if e.get("from")
    )
    parts = [f"[그림 {f['image_id']}] ({rec.get('kind', '')})"]
    if ctx and ctx.get("caption"):
        parts.append(f"캡션({ctx['caption_source']}): {ctx['caption']}")
    parts += [f"요약: {rec.get('summary', '')}", f"그림 글자: {rec.get('text', '')}"]
    if vals:
        parts.append(f"값: {vals}")
    if edges:
        parts.append(f"연결: {edges}")
    if rec.get("table_md"):
        parts.append(rec["table_md"])
    if ctx and ctx.get("mentions"):
        parts.append("본문 언급: " + " / ".join(ctx["mentions"]))
    if check:
        if check["agree"]:
            parts.append("값 확인(본문 일치): " + ", ".join(f"{k}={v}" for k, v in check["agree"].items()))
        if check["conflict"]:
            parts.append(
                "값 충돌(사람 확인): " + ", ".join(f"{k} 그림 {v['그림']} · 본문 {v['본문']}" for k, v in check["conflict"].items())
            )
        if check["context_only"]:
            parts.append("본문에만 있는 값: " + ", ".join(f"{k}={v}" for k, v in check["context_only"].items()))
    return "\n".join(parts)
