#!/usr/bin/env python3
"""용어 사전 LLM 초안(X4 ④) — 후보 용어(미등록 약어 등)를 LLM에 물어 사전 행(domain_terms.csv와 같은 열)을 **status=draft로만** 제안한다.
자동 승인 없음 — 실사전(dev/glossary/domain_terms.csv)은 절대 건드리지 않고, 사람이 검토할 별도 CSV(--out)에만 쓴다.

외부 LLM 가드: common/llm.py chat()의 두 겹 잠금(내부망 주소 또는 allow_external=True + 합성 정답 파일)을 그대로 쓴다 —
실명 고객·거래 용어는 사내 데이터이므로 서버(내부망 LLM)에서만, 개발 PC 실험은 --allow-external(합성 정답 파일 필요).
사용: python cli/wiki_draft.py --terms "PPQ,MTOP" [--out output/wiki/draft_terms.csv] [--allow-external] [--selftest]
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸 WIKI_DOMAIN_PHRASE)

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from common.ai.agent_prompts import load as _load_prompt  # noqa: E402 — AD33

FIELDS = [
    "concept_id",
    "canonical",
    "category",
    "synonyms",
    "abbreviations",
    "weak_synonyms",
    "broader",
    "related",
    "context_required",
    "case_sensitive",
    "definition_ko",
    "definition_en",
    "source",
    "owner",
    "status",
    "updated",
]

_PROMPT = _load_prompt("wiki_term_draft", "draft")  # 글자는 dev/agents/wiki_term_draft/prompt.md(파일은 절대 안 건드림 — 캐시 열쇠 불변)
_DEFAULT_DOMAIN = "바이오 CDMO"  # DT1 c1 — prompt.md에 박힌 도메인 예시 문구(CDMO). env WIKI_DOMAIN_PHRASE로 다른 업종 교체 가능


def _domain_prompt(term):
    """_PROMPT의 "바이오 CDMO" 문구를 env WIKI_DOMAIN_PHRASE로 바꿔치기(메모리상의 글자만 — prompt.md 파일은 안 건드려
    패키지 지문·캐시 열쇠가 그대로). 미설정이면 교체 자체를 안 해 바이트 동일(DT1 c1 원칙)."""
    domain = pc.cfg().transform.structure.wiki_domain_phrase  # S7c — 설정 객체(기본 '바이오 CDMO' — 빈 글자도 기본값, 옛 `get(X) or 기본`)
    text = _PROMPT if domain == _DEFAULT_DOMAIN else _PROMPT.replace(_DEFAULT_DOMAIN, domain)
    return text.format(term=term)


def propose_term(term, llm_complete, concept_id=None):
    """용어 하나 → draft 행(dict, FIELDS). llm_complete(prompt)->str 주입(시험·mock 가능). 실패해도 draft 행은 돌려줌(사람이 비워진 칸을 채움)."""
    data = {}
    try:
        raw = llm_complete(_domain_prompt(term))
        m = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(m.group()) if m else {}
    except Exception:
        data = {}
    return {
        "concept_id": concept_id or f"DRAFT.{re.sub(r'[^A-Za-z0-9]+', '_', term.upper())}",
        "canonical": data.get("canonical") or term,
        "category": data.get("category") or "",
        "synonyms": "",
        "abbreviations": data.get("abbreviations") or "",
        "weak_synonyms": "",
        "broader": "",
        "related": "",
        "context_required": "",
        "case_sensitive": "Y",
        "definition_ko": data.get("definition_ko") or "",
        "definition_en": data.get("definition_en") or "",
        "source": "llm-draft",
        "owner": "",
        "status": "draft",
        "updated": time.strftime("%Y-%m-%d"),
    }


def write_drafts(rows, out):
    """draft 행을 --out CSV에 덧붙임(실사전 파일은 절대 쓰지 않음) — 같은 concept_id는 마지막 제안으로 덮음."""
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if p.exists():
        with p.open(encoding="utf-8-sig") as fh:
            existing = {r["concept_id"]: r for r in csv.DictReader(fh)}
    for r in rows:
        existing[r["concept_id"]] = r
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(existing.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--terms", required=True, help="쉼표로 구분한 후보 용어(미등록 약어 등)")
    ap.add_argument("--out", default=str(ROOT / "output" / "wiki" / "draft_terms.csv"))
    ap.add_argument(
        "--allow-external", action="store_true", help="개발 PC 가상 데이터 실험에서만(두 겹 잠금 — 합성 정답 파일 필요, common/llm.py)"
    )
    a = ap.parse_args(argv)
    from common.ai import llm as L

    if not L.configured():
        raise SystemExit("LLM_BASE_URL·LLM_MODEL 미설정(.env) — 내부망 LLM만 허용(DONT 13)")
    ask = lambda p: L.chat(
        [{"role": "user", "content": p}], temperature=0.0, max_tokens=300, allow_external=a.allow_external, agent="wiki_term_draft"
    )
    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    rows = [propose_term(t, ask) for t in terms]
    write_drafts(rows, a.out)
    print(
        f"초안 {len(rows)}건(모두 status=draft) → {a.out} — 사람이 검토·승인(status=approved로 바꿔 GLOSSARY_DIR(예시 resources/vocab/glossary)의 domain_terms.csv에 반영)할 때까지 검색에 반영되지 않음"
    )


if __name__ == "__main__":
    utf8_stdout()
    main()
