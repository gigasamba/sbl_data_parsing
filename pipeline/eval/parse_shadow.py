#!/usr/bin/env python3
"""PA2 — 그림자 모드 CLI(docs/architecture.md §2·§7 PA2, backlog PA2행). represent()가 이미 쓴
`output/parse/_rep/<문서>.json`(PA0 — `rep.context`·`rep.decisions`, PARSE_CONTEXT 기본 켬일 때만 있음)을 읽어 문서마다
결정 지점별 "다음 행동" 제안을 `modules/parse/post/shadow.py`로 받고, 규칙 선택과 나란히 놓아 동의·불일치를
집계한다. **제안만** — _rep·파싱 결과·점수는 전혀 안 건드린다(별도 CLI라 파싱 자체를 느리게도 안 함).

PARSE_SHADOW(기본 켬, =0으로 끔) — =0이면 아무 파일도 안 읽고 안 씀(--force로 무시 가능, 시험용).
PARSE_SHADOW_MAX(기본 50) — 한 번에 훑는 문서 상한. --mode rules는 LLM 호출 0(규칙 그대로 "keep" echo, 배선
시험용) · --mode llm(기본)은 common/llm.py chat(agent="parse_shadow")로 실호출(캐시·내부망 가드는 그 안에서,
LLM_BASE_URL·LLM_MODEL 미설정이면 chat()이 LLMUnavailable을 올리고 shadow.propose_llm이 그 예외를 잡아 빈
제안 목록으로 조용히 넘어간다 — 외부·유료 호출 없음, 실행은 안 막힘).

경로 — tools/parse_agent_tools.rag_out()과 같은 관례(RAG_OUT 환경변수, 기본 dev/out) 아래 parse/_rep(입력)·
parse/_shadow(출력) — 하드코딩 금지.

사용: python cli/parse_shadow.py [--rep-dir 폴더] [--out 폴더] [--mode llm|rules] [--max N] [--force]
      python cli/parse_shadow.py --selftest
"""

import argparse
import json
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import PKG_ROOT  # 공용 자산 루트(10-14 이미지 단위 분리)
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체: PARSE_SHADOW_MAX)

ROOT = PKG_ROOT  # dev/
from pipeline.transform.represent import shadow as S  # noqa: E402

DEFAULT_MAX = 50


def rag_out():
    """결과 루트 — common.paths.output_root(없으면 저장소 output/). 옛 agent_tools.rag_out(10-29 파싱 판단 에이전트와 함께 지움)."""
    from common.config.settings import cfg
    from common.core.paths import APP_ROOT

    base = cfg().paths.output_root
    return Path(base) if base else APP_ROOT / "output"


def _default_llm_complete(prompt):
    """실제 호출 — common.ai.llm.chat(agent="parse_shadow")로 가드·캐시·내부망 확인은 그쪽이 집행(⑧ agent= 필수)."""
    from common.ai import llm as L

    return L.chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=800, json_mode=True, agent="parse_shadow")


def iter_rep_docs(rep_dir, max_docs=None):
    """rep_dir/*.json(index.json 제외) 중 PA0이 켜져 있던(context·decisions 둘 다 있는) 문서만, 이름순, max_docs개까지."""
    rep_dir = Path(rep_dir)
    if not rep_dir.exists():
        return
    n = 0
    for f in sorted(rep_dir.glob("*.json")):
        if f.stem == "index":
            continue
        if max_docs is not None and n >= max_docs:
            break
        try:
            rep = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "context" not in rep or "decisions" not in rep:
            continue  # PARSE_CONTEXT 꺼진 채 만든 _rep — 그림자 대상 아님(PA0 전제)
        n += 1
        yield f.stem, rep


def run(rep_dir, out_dir, mode="llm", max_docs=None, llm_complete=None):
    """핵심 로직(argparse를 거치지 않아 테스트가 가짜 llm_complete를 바로 줄 수 있음). 문서마다
    out_dir/<문서>.json(제안+diff)을 쓰고, 끝나면 out_dir/summary.json(step별 동의·불일치 집계)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    complete = llm_complete or _default_llm_complete
    records = []
    for doc, rep in iter_rep_docs(rep_dir, max_docs):
        ctx, decisions = rep["context"], rep["decisions"]
        proposals = S.propose_rules_only(decisions) if mode == "rules" else S.propose_llm(ctx, decisions, complete)
        diffs = S.diff(decisions, proposals)
        record = {"doc": doc, "mode": mode, "proposals": proposals, "diffs": diffs}
        (out_dir / f"{doc}.json").write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        records.append(record)
    summary = dict(S.build_summary(records), mode=mode)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep-dir", default=None, help="기본 rag_out()/parse/_rep")
    ap.add_argument("--out", default=None, help="기본 rag_out()/parse/_shadow")
    ap.add_argument("--mode", default="llm", choices=["llm", "rules"])
    ap.add_argument("--max", type=int, default=None, help="문서 상한(기본 PARSE_SHADOW_MAX 환경변수, 그것도 없으면 50)")
    ap.add_argument("--force", action="store_true", help="PARSE_SHADOW=0이어도 게이트 무시(시험용)")
    a = ap.parse_args(argv)

    if not a.force and not S.on():
        print("PARSE_SHADOW=0 — 아무것도 읽거나 쓰지 않음(--force로 무시)")
        return None

    rep_dir = Path(a.rep_dir) if a.rep_dir else rag_out() / "parse" / "_rep"
    out_dir = Path(a.out) if a.out else rag_out() / "parse" / "_shadow"
    max_docs = a.max if a.max is not None else pc.cfg().transform.represent.shadow_max  # S7c — 설정 객체(칸 기본값 50 = DEFAULT_MAX)

    summary = run(rep_dir, out_dir, mode=a.mode, max_docs=max_docs)
    print(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"→ {out_dir}")
    return summary


if __name__ == "__main__":
    utf8_stdout()
    main()
