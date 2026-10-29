"""pipeline.eval.diagram_edges_score 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.diagram_edges_score --selftest`."""

from pipeline.eval.diagram_edges_score import consistency, edge_score


def selftest():
    # edge_score — 방향 오류(짝은 맞고 방향만 틀림)·완전 일치·완전 불일치
    s = edge_score([{"from": "A", "to": "B"}], [{"from": "B", "to": "A"}])
    assert s["precision"] == 0.0 and s["recall"] == 0.0 and s["direction_acc"] == 0.0 and s["n_pair_matched"] == 1, s
    s2 = edge_score([{"from": "A", "to": "B"}, {"from": "B", "to": "C"}], [{"from": "A", "to": "B"}, {"from": "B", "to": "C"}])
    assert s2["precision"] == s2["recall"] == s2["f1"] == 1.0 and s2["direction_acc"] == 1.0, s2
    s3 = edge_score([], [{"from": "A", "to": "B"}])  # 하나도 못 뽑음 — precision 0.0(틀린 걸 낸 적도 없지만 맞춘 적도 없음), recall 0.0
    assert s3["precision"] == 0.0 and s3["recall"] == 0.0 and s3["direction_acc"] is None, s3
    s4 = edge_score([], [])
    assert s4["precision"] == 1.0 and s4["recall"] == 1.0, s4  # 둘 다 빈 집합 — 할 일이 없었으므로 완벽
    print("[selftest] edge_score — 방향 오류·완전 일치·공집합 통과")

    c1 = consistency([[{"from": "A", "to": "B"}], [{"from": "A", "to": "B"}], [{"from": "B", "to": "A"}]])
    assert c1 == round(2 / 3, 4), c1
    c2 = consistency([[{"from": "A", "to": "B"}]])
    assert c2 == 1.0
    print("[selftest] consistency — 다수 모양 비율(2/3)·변형 1개는 1.0 통과")


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
