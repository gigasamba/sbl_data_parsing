"""mcp_server.services.search.text 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.text`."""

from mcp_server.services.search.text import term_weights


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    assert term_weights(["a", "b"]) == {"a": 1.0, "b": 1.0} and term_weights({"a": 0.8}) == {"a": 0.8}  # X3: list는 1.0, dict는 그대로
    print("[selftest] term_weights — X3 list는 1.0 기본, dict는 그대로 통과")
