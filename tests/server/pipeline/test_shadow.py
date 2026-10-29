"""pipeline.transform.represent.shadow 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.shadow`."""

import json

from pipeline import config as pc
from pipeline.transform.represent.shadow import (
    MAX_EXAMPLES,
    build_payload,
    build_summary,
    diff,
    on,
    parse_proposals,
    propose_llm,
    propose_rules_only,
)


def selftest():
    with pc.PIPE.env(PARSE_SHADOW=None):  # S7c — 설정 객체만 바꿔 끼움
        assert on() is False and on("1") is True and on("0") is False

    decisions = [
        {"step": "engine_scope", "choice": "all", "reason": "형식별 등록 엔진 전부", "inputs": {}},
        {"step": "figures", "choice": "3건", "reason": "상한 안 걸림", "inputs": {"skip_reasons": {"unconvertible": 2}}},
    ]
    ctx = {
        "format": ".pdf_text",
        "pages": 3,
        "tables": 0,
        "engines": {},
        "page": [{"page": 1, "scan_reason": "chars"}, {"page": 2}, {"page": 3, "rotation": 90}],
    }

    # build_payload — 문제 없는 2쪽은 빠지고(scan_reason·rotation 있는 쪽만), decisions는 그대로
    payload = build_payload(ctx, decisions)
    assert [p["page"] for p in payload["context"]["page"]] == [1, 3]
    assert payload["decisions"] == decisions
    print("[selftest] build_payload — 문제 쪽만 남김(scan_reason·rotation) 통과")

    # propose_rules_only — 모델 없이 전부 keep
    rules_props = propose_rules_only(decisions)
    assert [p["action"] for p in rules_props] == ["keep", "keep"]
    print("[selftest] propose_rules_only — LLM 없이 규칙 그대로 keep echo 통과")

    # parse_proposals — 유효(keep)·유효(목록 안 다른 값)·무효(목록 밖 action)·무효(decisions에 없는 step)·중복 step(두 번째 버림)
    text = json.dumps(
        {
            "proposals": [
                {"step": "engine_scope", "action": "keep", "reason": "충분", "confidence": 0.9},
                {"step": "figures", "action": "raise_cap", "reason": "변환 실패 2건", "confidence": 1.7},  # confidence 상한 밖 — clamp
                {"step": "figures", "action": "keep", "reason": "두 번째 — 버려짐", "confidence": 0.1},  # 같은 step 중복 — 버림
                {"step": "fuse", "action": "on", "reason": "decisions에 없는 step", "confidence": 0.5},  # steps_present 밖 — 버림
                {
                    "step": "engine_scope",
                    "action": "nonsense",
                    "reason": "목록 밖",
                    "confidence": 0.5,
                },  # 이미 engine_scope 채워짐(중복)이자 action도 밖
            ]
        },
        ensure_ascii=False,
    )
    props = parse_proposals(text, decisions)
    by_step = {p["step"]: p for p in props}
    assert set(by_step) == {"engine_scope", "figures"}, by_step
    assert by_step["engine_scope"]["action"] == "keep"
    assert by_step["figures"]["action"] == "raise_cap" and by_step["figures"]["confidence"] == 1.0  # clamp
    print("[selftest] parse_proposals — 목록 밖 action·decisions 밖 step·중복 step 버림, confidence clamp 통과")

    assert parse_proposals("이건 JSON이 아님", decisions) == []
    assert parse_proposals(json.dumps({"proposals": "문자열"}), decisions) == []
    print("[selftest] parse_proposals — JSON 아님·proposals 모양 다름이면 빈 목록 통과")

    # propose_llm — 가짜 LLM(결정적 스텁, 알려진 한 step에서 규칙과 다름 — engine_scope는 keep, figures는 raise_cap)
    def _fake_disagree_on_figures(prompt):
        assert "engine_scope" in prompt and "figures" in prompt  # payload가 프롬프트에 실제로 들어갔는지
        return json.dumps(
            {
                "proposals": [
                    {"step": "engine_scope", "action": "keep", "reason": "충분", "confidence": 0.8},
                    {"step": "figures", "action": "raise_cap", "reason": "변환 실패 2건 — 해상도 올려 재시도", "confidence": 0.6},
                ]
            }
        )

    props2 = propose_llm(ctx, decisions, _fake_disagree_on_figures)
    assert len(props2) == 2 and {p["step"]: p["action"] for p in props2} == {"engine_scope": "keep", "figures": "raise_cap"}
    print("[selftest] propose_llm — 가짜 LLM(네트워크 0) 결정적 응답 파싱, 알려진 step(figures)에서 규칙과 불일치 통과")

    def _boom(prompt):
        raise RuntimeError("모델 호출 실패")

    assert propose_llm(ctx, decisions, _boom) == []
    print("[selftest] propose_llm — llm_complete 예외면 빈 목록(집계를 막지 않음) 통과")

    # diff — engine_scope는 keep(동의), figures는 raise_cap(불일치, 규칙 choice="3건"과 나란히)
    diffs = diff(decisions, props2)
    by_step2 = {d["step"]: d for d in diffs}
    assert by_step2["engine_scope"]["agree"] is True
    assert by_step2["figures"]["agree"] is False and by_step2["figures"]["rule_choice"] == "3건"
    print("[selftest] diff — 규칙 choice와 제안 action을 나란히, agree=action==keep 통과")

    # diff — 제안이 아예 없는 step(여기선 rules-only로 전부 채워 빈 사례를 별도 구성)
    assert diff(decisions, []) == []
    print("[selftest] diff — 제안이 하나도 없으면 빈 목록(모른다고 동의로 안 침) 통과")

    # build_summary — 두 문서(하나는 전부 동의, 하나는 1건 불일치) → step별 집계 + 불일치 예시
    records = [{"doc": "docA", "diffs": diff(decisions, propose_rules_only(decisions))}, {"doc": "docB", "diffs": diffs}]
    summary = build_summary(records)
    assert summary["docs"] == 2
    assert summary["steps"]["engine_scope"] == {"agree": 2, "disagree": 0, "examples": []}
    assert summary["steps"]["figures"]["agree"] == 1 and summary["steps"]["figures"]["disagree"] == 1
    ex = summary["steps"]["figures"]["examples"]
    assert len(ex) == 1 and ex[0]["doc"] == "docB" and ex[0]["action"] == "raise_cap"
    print("[selftest] build_summary — step별 agree/disagree 집계 + 불일치 예시(docB만) 통과")

    # MAX_EXAMPLES 상한 — 불일치 문서가 상한보다 많아도 예시는 MAX_EXAMPLES개만
    many = [
        {
            "doc": f"doc{i}",
            "diffs": [{"step": "figures", "rule_choice": "3건", "action": "raise_cap", "agree": False, "reason": "r", "confidence": 0.5}],
        }
        for i in range(MAX_EXAMPLES + 3)
    ]
    summary2 = build_summary(many)
    assert summary2["steps"]["figures"]["disagree"] == MAX_EXAMPLES + 3
    assert len(summary2["steps"]["figures"]["examples"]) == MAX_EXAMPLES
    print("[selftest] build_summary — 불일치 수는 전부 세되 예시는 MAX_EXAMPLES개만 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
