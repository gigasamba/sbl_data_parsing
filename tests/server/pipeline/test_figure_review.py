"""pipeline.transform.figures.figure_review 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.figure_review --selftest`."""

import copy
import json

import pipeline.transform.figures.figure_review as M
from pipeline.transform.figures.figure_review import _verdict, compare, review


# ── 자기점검(네트워크 없음) ─────────────────────────────────────────────
def selftest():
    # compare(): 값 불일치
    rec = {"values": [{"label": "A", "value": "10", "unit": "kg"}], "edges": []}
    ext = {"values": [{"label": "A", "value": "12", "unit": "kg"}], "nodes": []}
    d = compare(rec, ext)
    assert d["value_mismatch"] and d["value_mismatch"][0]["label"] == "A", d

    # compare(): 순서 바뀜(LCS)
    rec = {"edges": [{"from": "X", "to": "Y"}, {"from": "Y", "to": "Z"}]}
    ext = {"nodes": ["Z", "Y", "X"]}
    d = compare(rec, ext)
    assert d["order_mismatch"], d

    # compare(): 빠진 노드
    rec = {"edges": [{"from": "A", "to": "B"}]}
    ext = {"nodes": ["A", "B", "C"]}
    d = compare(rec, ext)
    assert any(m.get("type") == "node" and m.get("name") == "C" for m in d["missing_in_ours"]), d

    # compare(): 같으면 빈 diff
    rec = {
        "values": [{"label": "A", "value": "1.2B", "unit": "USD"}],
        "edges": [{"from": "A", "to": "B", "label": "x"}],
        "text": "A B 설명",
        "table_md": "| a | b |\n|---|---|\n| 1 | 2 |",
    }
    ext = {
        "values": [{"label": "A", "value": "1,200,000,000", "unit": "USD"}],
        "edges": [{"from": "A", "to": "B", "label": "x"}],
        "nodes": ["A", "B"],
        "texts": ["A B"],
        "table": {"header": ["a", "b"], "rows": [["1", "2"]]},
    }
    d = compare(rec, ext)
    assert not d["missing_in_ours"] and not d["extra_in_ours"] and not d["value_mismatch"]
    assert not d["edge_mismatch"]["missing_in_ours"] and not d["edge_mismatch"]["extra_in_ours"]
    assert not d["order_mismatch"] and not d["table_mismatch"], d
    print("[selftest] compare() 값·순서·누락·동일 4종 통과")

    # review(): stub VLM(네트워크 없음) — pass 경로
    real = M._vlm_call
    record0 = {"values": [{"label": "A", "value": "10", "unit": "kg"}], "edges": [], "image_id": "t"}
    before = copy.deepcopy(record0)
    ext_ok = json.dumps({"kind": "chart", "values": [{"label": "A", "value": "10", "unit": "kg"}]})
    judge_pass = json.dumps({"items": [{"item": "A", "verdict": "ok"}], "semantic_ok": True, "verdict": "pass", "issues": []})
    q = iter([ext_ok, judge_pass])
    M._vlm_call = lambda img, prompt, which="extract": next(q)
    res = review(b"img", record0, max_rounds=2)
    assert res["verdict"] == "pass" and res["rounds"] == 0 and record0 == before, res

    # review(): fix → pass 경로(재추출 반영)
    ext_bad = json.dumps({"kind": "chart", "values": [{"label": "A", "value": "99", "unit": "kg"}]})
    judge_fix = json.dumps(
        {"items": [{"item": "A", "verdict": "wrong"}], "semantic_ok": True, "verdict": "fix", "issues": ["값 확인 필요"]}
    )
    ext_fixed = json.dumps({"kind": "chart", "values": [{"label": "A", "value": "99", "unit": "kg"}]})
    q = iter([ext_bad, judge_fix, ext_fixed, judge_pass])
    M._vlm_call = lambda img, prompt, which="extract": next(q)
    res = review(b"img", record0, max_rounds=2)
    assert res["verdict"] == "pass" and res["rounds"] == 1 and record0 == before, res
    assert res["fixed_record"]["values"][0]["value"] == "99"  # 보정 반영

    # review(): 끝까지 안 풀림 → human
    q = iter([ext_bad, judge_fix, ext_bad, judge_fix, ext_bad, judge_fix])
    M._vlm_call = lambda img, prompt, which="extract": next(q)
    res = review(b"img", record0, max_rounds=2)
    assert res["verdict"] == "human" and res["rounds"] == 2 and record0 == before, res
    M._vlm_call = real
    print("[selftest] review() pass·fix→pass·unresolved→human(원본 불변) 통과")
    m = lambda v, sev="material": {"item": "x", "verdict": v, "severity": sev}
    assert _verdict({"items": [m("ok"), m("missing", "minor")], "verdict": "fix"}) == "pass"  # 사소한 것만 → 통과
    assert _verdict({"items": [m("wrong")]}) == "fix" and _verdict({"items": [m("ok")], "semantic_ok": False}) == "fix"
    assert _verdict({"items": [m("unsure")]}) == "human" and _verdict({}) == "human"
    print("[selftest] 판정은 material 항목만(사소한 것·그림 밖 글자는 통과) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
