"""mcp_server.services.search.bm25_weights 시험."""

from mcp_server.services.search.bm25_weights import term_weights


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    assert term_weights(["a", "b"]) == {"a": 1.0, "b": 1.0} and term_weights({"a": 0.8}) == {"a": 0.8}  # X3: list는 1.0, dict는 그대로
    print("[selftest] term_weights — X3 list는 1.0 기본, dict는 그대로 통과")
