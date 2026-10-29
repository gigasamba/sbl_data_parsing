"""mcp_server.services.search.supersede 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.supersede`."""

from mcp_server.services.search.supersede import is_superseded, superseded_set


def selftest():
    recs = [{"doc_id": "v1", "supersedes_doc_id": None}, {"doc_id": "v2", "supersedes_doc_id": "v1"}]
    s = superseded_set(recs)
    assert s == {"v1"}
    assert is_superseded("v1", s) is True and is_superseded("v2", s) is False
    assert superseded_set([]) == set()
    print("[selftest] 대체판(superseded) 판정 단일 규칙 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
