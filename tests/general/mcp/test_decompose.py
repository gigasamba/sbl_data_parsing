"""mcp_server.services.search.decompose 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.decompose`."""

from mcp_server.services.search.decompose import gather, keep_context, split_question


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    lists = {"orig": [1, 2, 3], "a": [1, 4, 5], "b": [6, 7, 8]}
    assert gather("orig", ["a", "b"], lambda q, n: lists[q][:n], base=3, per=2) == [(1, 0), (6, 2), (2, 0), (4, 1), (7, 2), (3, 0)]
    find = lambda q: ["Pfizer Inc."] if "Pfizer" in q else []
    assert keep_context(["Pfizer 계약 건수는?", "제품별 배치 수는?"], ["Pfizer Inc."], find) == [
        "Pfizer 계약 건수는?",
        "Pfizer Inc. — 제품별 배치 수는?",
    ]
    Q = "AAA-MAB-01 계약 단가와 함께 AAA-ADC-02 계약의 연간 배치 수도 알려줘"
    assert split_question("단가는?", lambda p: 1 / 0) == ([], 0)
    assert split_question(Q, lambda p: "모르겠음") == ([], 1)
    assert split_question(Q, lambda p: '{"subs": ["a 단가는?", "b 배치 수는?"]}') == (["a 단가는?", "b 배치 수는?"], 1)
    print("[selftest] 질문 분해 통과")
