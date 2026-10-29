"""pipeline.transform.structure.wiki_draft 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.wiki_draft --selftest`."""

import csv
import json
from pathlib import Path

from pipeline import config as pc
from pipeline.transform.structure.wiki_draft import _PROMPT, _domain_prompt, propose_term, write_drafts


def selftest():
    import tempfile

    ask = lambda p: json.dumps(
        {
            "canonical": "Process Performance Qualification",
            "category": "quality",
            "definition_ko": "공정 성능 적격성 평가",
            "definition_en": "",
            "abbreviations": "PPQ",
        }
    )
    row = propose_term("PPQ", ask)
    assert row["status"] == "draft" and row["canonical"] == "Process Performance Qualification" and row["abbreviations"] == "PPQ"
    bad_row = propose_term("없는용어", lambda p: (_ for _ in ()).throw(RuntimeError("LLM 미설정")))  # LLM 실패해도 draft 행은 반환
    assert bad_row["status"] == "draft" and bad_row["canonical"] == "없는용어" and bad_row["definition_ko"] == ""
    out = Path(tempfile.mkdtemp()) / "draft_terms.csv"
    write_drafts([row], out)
    write_drafts([bad_row], out)  # 두 번째 호출 — 기존 draft에 덧붙음(실사전과 분리된 별도 파일)
    with out.open(encoding="utf-8-sig") as fh:
        saved = list(csv.DictReader(fh))
    assert len(saved) == 2 and all(r["status"] == "draft" for r in saved)  # 전부 draft(자동 승인 없음)
    print("[selftest] 용어 사전 LLM 초안 — status=draft만, 실패해도 안전한 기본값, 별도 파일에만 적재 통과")

    # DT1 c1 — WIKI_DOMAIN_PHRASE 미설정이면 prompt.md 글자 그대로(바이트 동일), 설정하면 바꿔치기(파일은 안 건드림)
    assert _domain_prompt("PPQ") == _PROMPT.format(term="PPQ")
    with pc.PIPE.env(WIKI_DOMAIN_PHRASE="가짜회사 반도체"):  # 가짜 회사 예시 · S7c — 설정 객체
        assert "가짜회사 반도체" in _domain_prompt("PPQ") and "바이오 CDMO" not in _domain_prompt("PPQ")
    assert _domain_prompt("PPQ") == _PROMPT.format(term="PPQ")  # 지운 뒤 다시 기본값(바이트 동일)
    print("[selftest] WIKI_DOMAIN_PHRASE — 미설정 바이트 동일·가짜 회사 예시 반영·prompt.md 파일 불변 통과(DT1 c1)")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
