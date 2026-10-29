"""pipeline.load.index_cfg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.load.index_cfg`."""

import re
from pathlib import Path

from pipeline.load.index_cfg import DEFAULTS, env_for, index_id, inputs, normalize, pg_schema


def selftest():
    import tempfile

    a = index_id({})
    assert re.fullmatch(r"[0-9a-f]{8}", a) and a == index_id(DEFAULTS) == index_id({"embed_model": "bge-m3"})  # 기본값 표기 차이 → 같은 id
    assert index_id({"chunk_size": 512}) != index_id({"chunk_size": 1024}) != a
    assert index_id({"chunk_size": 512, "overlap": 64}) == index_id({"overlap": 64, "chunk_size": 512})  # 칸 순서 무관
    for bad in (
        {"x": 1},
        {"chunk_size": 0},
        {"chunk_size": True},
        {"embed": "openai"},
        {"embed": "api"},
        {"embed": "bge-m3", "embed_model": "e5-small"},
        {"embed": "none", "dim": 1024},
        {"summary": "x"},
        {"overlap": 600},
        {"chunk_size": 100, "overlap": 100},
        {"chunker": "../x"},
    ):
        try:
            normalize(bad)
            raise AssertionError(f"거부 안 됨: {bad}")
        except ValueError:
            pass
    assert pg_schema("0a1b2c3d", "ai") == "ai_0a1b2c3d" and pg_schema("0a1b2c3d", "ai_test") == "ai_test_0a1b2c3d"
    import yaml

    def _over(env):
        return yaml.safe_load(Path(env["SETTINGS_FILE"]).read_text(encoding="utf-8"))["overrides"]

    e = env_for({"chunk_size": 512}, {"X": "1"})
    assert e["X"] == "1" and _over(e) == {"CHUNK_SIZE": "512", "CHUNK_OVERLAP": None}, _over(e)  # 설정 밖 겹침 값은 비움(S7e2 — 덮기 파일)
    assert _over(env_for({"embed": "api", "embed_model": "m1"}, {}))["EMBED_MODEL"] == "m1"
    with tempfile.TemporaryDirectory() as d:
        g = Path(d) / "g"
        g.mkdir()
        (g / "domain_terms.csv").write_text("a", encoding="utf-8")
        e1 = {"GLOSSARY_DIR": str(g)}
        i1 = inputs(Path(d), Path(d) / "none.json", e1)
        (g / "domain_terms.csv").write_text("b", encoding="utf-8")
        i2 = inputs(Path(d), Path(d) / "none.json", e1)
        assert i1["glossary"] != i2["glossary"] and {k: v for k, v in i1.items() if k != "glossary"} == {
            k: v for k, v in i2.items() if k != "glossary"
        }
    print("[selftest] pipeline.load.index_cfg — 지문(기본값·순서 무관)·거부·스키마·env·입력 지문(사전·명부) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
