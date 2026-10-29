"""mcp_server.services.search.index_cfg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.index_cfg`."""

from common.core.index_cfg import glossary_fp
from mcp_server.services.search.index_cfg import input_drift


def selftest():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        g = Path(d) / "g"
        g.mkdir()
        (g / "domain_terms.csv").write_text("a", encoding="utf-8")
        e1 = {"GLOSSARY_DIR": str(g)}
        inf = {"index_id": "0a1b2c3d", "inputs": {"glossary": glossary_fp(e1), "roster": "none"}}
        assert input_drift(inf, e1) is None and input_drift({"index_id": "0a1b2c3d"}, {}) is None  # 같음·기록 없음 → 경고 없음
        assert "용어 사전" in input_drift(inf, {})  # 사전 없이 연 MCP → 경고
    print("[selftest] mcp_server.services.search.index_cfg — input_drift 경고 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
