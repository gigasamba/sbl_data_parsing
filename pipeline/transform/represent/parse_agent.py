#!/usr/bin/env python3
"""파싱 에이전트 실행(AG11 1단계 — docs/architecture.md 'AG11 구현 계획' 절, 단계 ①: 도구 층 + 패키지 +
shadow 모드, 행동 변화 0). dev/tools/parse_agent_tools.py.build_tools()로 문서 1건짜리 세션을 만들고:

  --mode off(기본): **지금 규칙**(결정적 — LLM 0회)만으로 도구를 정해진 순서로 불러 세션을 끝낸다(run_rule_based).
  --mode shadow: off와 같은 결정적 순서를 **그대로 먼저** 돌려 제안(rep.json, off와 바이트 동일) 만들고,
    **새 세션**으로 dev/common/adk.py.run_agent("parse_agent", ...)를 불러 모델의 다음 행동 제안·도구 호출
    궤적을 받아 rag_out()/parse/_agent/shadow.jsonl에 덧붙인다(실행에는 안 씀 — PA2, 설계 §0 "실행은 지금 규칙").
  --mode on|apply: 거부 — 2단계 판단 지점 apply는 파이프라인 안(modules/parse/post/agent_step.py, PARSE_AGENT=apply),
    이 CLI의 전 범위 계획 적용은 PA4.

PARSE_AGENT env로 --mode 기본값을 줄 수 있다(--mode 인자가 더 우선).
경로 — rag_out()/doc_src()(dev/tools/parse_agent_tools.py, RAG_OUT·DOC_DIR 기준, 하드코딩 금지 — 10-07 결정 ①).

사용: python cli/parse_agent.py <이미 준비된 문서 경로> [--mode off|shadow|on] [--doc-name 이름] [--out 폴더] [--parse-dir 폴더]
      python cli/parse_agent.py --selftest
"""

import argparse
import json
import time
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import PKG_ROOT  # 공용 자산 루트(10-14 이미지 단위 분리)

ROOT = PKG_ROOT  # dev/
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)
from pipeline.transform.represent.agent_tools import build_tools, rag_out  # noqa: E402


def _engines_for(fmt):
    """형식에 맞는 핵심 엔진들(비우면 등록된 첫 엔진 1개 — 빈 결과보다 낫다)."""
    from pipeline.extract.engines import registry

    core = registry.select("")
    matched = registry.engines_for(fmt)
    return [e for e in matched if e in core] or matched[:1]


def run_rule_based(tools):
    """지금 규칙(결정적, LLM 0회) — 기본 계획을 그대로: inspect→parse_text→extract_images→cross_check→
    choose_representative→apply_post→finalize(설계 'AG11 구현 계획' 절 "기본 계획")."""
    sig = tools["inspect_document"]()
    tools["parse_text"](_engines_for(sig.get("format", "")))
    tools["extract_images"]()
    tools["cross_check"]()
    tools["choose_representative"]()
    tools["apply_post"]()
    return tools["finalize"]()


def _proposal(ctx):
    """off/shadow가 바이트로 비교하는 결정적 산출물 — 운영 _rep가 아니라 이 세션의 제안(설계 §0 "실행은 지금
    규칙" 역할을 이 CLI의 결정적 순서가 맡음). sort_keys=True로 저장해 바이트 비교가 쉽게."""
    return {
        "doc": ctx["doc"],
        "engine": ctx.get("rep_engine"),
        "post": ctx.get("post"),
        "crosscheck": ctx.get("crosscheck"),
        "final": ctx.get("final"),
    }


def run_shadow_agent(doc, doc_path, out_dir, parse_dir):
    """새 세션(규칙 실행과 ctx를 안 섞음)으로 모델에게 다음 행동만 묻는다 — 실행에는 안 쓴다(PA2)."""
    from google.genai import types

    from common.ai import adk as A
    from common.ai.agent_prompts import tail as tail_prompt
    from common.ai.agent_prompts import template as load_template

    tools, _ctx = build_tools(doc, doc_path, out_dir, parse_dir=parse_dir)
    sig = tools["inspect_document"]()
    plan = load_template("parse_agent", "plan")  # 문자열로 [문서 신호]를 이어붙이므로 template()+tail()(ADK14 P1,
    msg = (
        plan + f"\n\n[문서 신호] doc={doc} format={sig.get('format')} pages={sig.get('pages')} "  # 꼬리는
        f"is_image_pdf={sig.get('is_image_pdf')} drm={sig.get('drm')}" + tail_prompt("parse_agent")
    )  # 자료 뒤)
    contents = types.Content(role="user", parts=[types.Part.from_text(text=msg)])
    return A.run_agent("parse_agent", contents, role="llm", tools=tools)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_path")
    ap.add_argument("--doc-name", default=None, help="문서 ID(기본 파일 이름)")
    ap.add_argument(
        "--mode", default=pc.cfg().transform.agent.enabled or "off", choices=["off", "shadow", "apply", "on"]
    )  # S7c — 설정 객체(글자 칸 — 없음·'' = off)
    ap.add_argument("--out", default=None, help="세션 스크래치 폴더(기본 rag_out()/parse/_agent/<문서 이름>)")
    ap.add_argument("--parse-dir", default=None, help="P0 캐시 폴더(기본 rag_out()/parse)")
    a = ap.parse_args(argv)

    if a.mode in (
        "on",
        "apply",
    ):  # PARSE_AGENT=apply(2단계)는 represent 안 판단 세션(post/agent_step.py) 몫 — 이 CLI의 전 범위 계획 적용은 PA4
        raise SystemExit(
            f"--mode {a.mode}은 이 CLI(전 범위 계획)에서 거부 — 판단 지점 apply는 파이프라인 PARSE_AGENT=apply(post/agent_step.py), 전 범위는 PA4"
        )

    doc_path = Path(a.doc_path)
    doc = a.doc_name or doc_path.name
    out_dir = Path(a.out) if a.out else rag_out() / "parse" / "_agent" / doc
    parse_dir = a.parse_dir

    tools, ctx = build_tools(doc, doc_path, out_dir, parse_dir=parse_dir)
    run_rule_based(tools)
    proposal = _proposal(ctx)
    (out_dir / "rep.json").write_text(json.dumps(proposal, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(proposal, ensure_ascii=False, indent=1, sort_keys=True))

    if a.mode == "shadow":
        text, trajectory, usage = run_shadow_agent(doc, doc_path, out_dir, parse_dir)
        parse_root = Path(parse_dir) if parse_dir else rag_out() / "parse"
        shadow_log = parse_root / "_agent" / "shadow.jsonl"
        shadow_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "doc": doc,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rule_proposal": proposal,
            "agent_text": text,
            "trajectory": trajectory,
            "usage": usage,
        }
        with shadow_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"shadow 기록: {shadow_log}")
    return proposal


if __name__ == "__main__":
    utf8_stdout()
    main()
