"""PA2 — 그림자 모드(제안만, 실행은 언제나 규칙). PA0(trace.py)이 `_rep/<문서>.json`에 남긴 `rep.context`·
`rep.decisions`를 입력으로 `dev/agents/parse_shadow` 패키지에 "이 결정 지점이면 네 제안은?"을 묻고, 규칙 선택과
나란히 놓아 동의·불일치를 집계한다(docs/architecture.md §2·§7 PA2, backlog PA2행 "규칙과 다른 제안 집계").
파싱 결과(_rep)·점수에는 아무것도 안 바꾼다 — 이 모듈은 output/parse/_shadow/ 아래에만 쓴다(cli/parse_shadow.py).

순수 함수만(adk·네트워크 import 없음) — modules/search/decompose.py split_question()과 같은 DI 패턴: 실제 모델
호출은 호출자가 `llm_complete(프롬프트 글자) -> 응답 글자` 콜백으로 주입한다(테스트는 가짜 콜백, CLI는
common.ai.llm.chat(agent="parse_shadow")). PARSE_SHADOW(환경변수, 기본 꺼짐 — 구조 개편 v4 step1, =1로 켬) 게이트는 CLI가 on()으로 확인.

STEP_ACTIONS = 결정 지점(step)마다 허용되는 행동의 **고정 목록**(한 곳에서만 정의) — "keep"은 모든 지점에 항상
있고 "규칙 그대로(동의)"를 뜻한다. 모델 응답이 이 목록 밖의 action이거나 입력 decisions에 없는 step을 말하면
parse_proposals()가 그 항목을 버린다(출력을 믿지 않음 — AD19 "지어내지 않음"과 같은 원칙).

사용: python modules/parse/post/shadow.py (자기 점검)"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # dev/

from pipeline import config as pc  # noqa: E402   # pipeline 칸 설정 객체(S7c)

# 결정 지점(step)별 허용 행동 — dev/agents/parse_shadow/prompts/propose.md의 목록과 글자 그대로 같아야 한다(이 상수가
# 정본, 프롬프트는 사람이 읽을 설명일 뿐 — 모델이 목록 밖을 답해도 여기서 걸러진다).
STEP_ACTIONS = {
    "engine_scope": ("keep", "all", "stack"),
    "ocr_fallback": ("keep", "add_ocr", "skip_ocr"),
    "page_scan": ("keep", "recheck"),
    "scan_fill": ("keep", "refill"),
    "representative": ("keep", "alternate"),
    "table_fix": ("keep", "retry"),
    "standardize": ("keep", "on", "off"),
    "table_std": ("keep", "on", "off"),
    "figures": ("keep", "raise_cap", "skip"),
    "fuse": ("keep", "on", "off"),
}

MAX_PAGES_IN_PROMPT = 10  # LLM 입력에 넣는 '문제 쪽'(scan_reason·rotation 있는 쪽) 상한 — 설계 §3 "문제 쪽만"
MAX_EXAMPLES = 5  # summary.json 불일치 예시 상한(step마다)


def on(config=None):
    """PARSE_SHADOW(기본 꺼짐, =1로 켬)."""
    config = (
        pc.cfg().transform.represent.shadow if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def _prompt():
    from common.ai.agent_prompts import load as load_prompt

    return load_prompt("parse_shadow", "propose")


def build_payload(ctx, decisions):
    """PA0 context·decisions → LLM 입력용으로 줄임(원문 전체 대신 요약·신호만, 설계 §3). page는 문제가 있는
    쪽(scan_reason 또는 rotation이 있는 쪽)만 상한 MAX_PAGES_IN_PROMPT개 — 쪽이 많은 문서에서 지시문이 과도하게
    길어지지 않게."""
    ctx = ctx or {}
    trimmed = {k: v for k, v in ctx.items() if k != "page"}
    pages = [p for p in (ctx.get("page") or []) if p.get("scan_reason") or p.get("rotation")]
    if pages:
        trimmed["page"] = pages[:MAX_PAGES_IN_PROMPT]
    return {"context": trimmed, "decisions": decisions or []}


def propose_rules_only(decisions):
    """모델 없이(rules-only 모드) 규칙 결정을 그대로 "keep"으로 echo — 배선 시험용(과제 요건 "선택적 rules-only 모드")."""
    return [
        {"step": d["step"], "action": "keep", "reason": "규칙 그대로(모델 미사용 — rules-only 모드)", "confidence": 1.0}
        for d in (decisions or [])
    ]


def _clamp_confidence(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    if v != v:  # NaN
        return 0.5
    return max(0.0, min(1.0, v))


def parse_proposals(text, decisions):
    """모델 응답 글자 → 검증된 제안만. step이 입력 decisions에 없거나 action이 STEP_ACTIONS[step] 밖이면 버림,
    같은 step이 두 번 나오면 첫 번째만(뒤는 버림). 응답이 JSON이 아니거나 모양이 다르면 빈 목록."""
    from common.ai.llm import parse_json

    steps_present = {d["step"] for d in (decisions or [])}
    try:
        data = parse_json(text or "")
    except ValueError:
        return []
    raw = data.get("proposals") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        step, action = item.get("step"), item.get("action")
        if step in seen or step not in steps_present or action not in STEP_ACTIONS.get(step, ()):
            continue
        seen.add(step)
        out.append(
            {
                "step": step,
                "action": action,
                "reason": str(item.get("reason") or "")[:200],
                "confidence": _clamp_confidence(item.get("confidence")),
            }
        )
    return out


def propose_llm(ctx, decisions, llm_complete):
    """payload를 프롬프트에 채워 llm_complete(프롬프트 글자) → 응답 글자를 받아 검증된 제안만 돌려준다(decompose.
    split_question과 같은 DI — 이 함수는 adk를 모름, 호출 실패는 빈 목록으로 폴백해 집계를 막지 않는다)."""
    payload = build_payload(ctx, decisions)
    prompt = _prompt().format(payload=json.dumps(payload, ensure_ascii=False, sort_keys=True))
    try:
        text = llm_complete(prompt)
    except Exception:
        return []
    return parse_proposals(text, decisions)


def diff(decisions, proposals):
    """제안이 있는 결정 지점마다(제안 없는 step은 집계에서 빠짐 — 모른다고 동의로 치지 않음) 규칙 선택과
    나란히: agree = action=="keep"."""
    by_step = {p["step"]: p for p in proposals}
    out = []
    for d in decisions or []:
        p = by_step.get(d["step"])
        if p is None:
            continue
        out.append(
            {
                "step": d["step"],
                "rule_choice": d.get("choice"),
                "action": p["action"],
                "agree": p["action"] == "keep",
                "reason": p["reason"],
                "confidence": p["confidence"],
            }
        )
    return out


def build_summary(records):
    """records: [{"doc":..., "diffs":[diff() 결과]}] → step별 동의/불일치 수 + 불일치 예시(최대 MAX_EXAMPLES)."""
    steps = {}
    for rec in records:
        for d in rec.get("diffs") or []:
            s = steps.setdefault(d["step"], {"agree": 0, "disagree": 0, "examples": []})
            if d["agree"]:
                s["agree"] += 1
            else:
                s["disagree"] += 1
                if len(s["examples"]) < MAX_EXAMPLES:
                    s["examples"].append(
                        {"doc": rec.get("doc"), "rule_choice": d["rule_choice"], "action": d["action"], "reason": d["reason"]}
                    )
    return {"docs": len(records), "steps": steps}
