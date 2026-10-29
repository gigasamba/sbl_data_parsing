"""common.core.index_cfg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.index_cfg`."""

import json
from pathlib import Path

from common.core.index_cfg import bundle_dir, check_id, glossary_fp, info, list_ids, roster_fp


def selftest():
    import tempfile

    a = "0a1b2c3d"  # 유효한 index_id 형식(소문자 16진 8자) — 실제 계산은 pipeline.load.index_cfg.index_id가 함
    for bad in ("ABCDEF12", "1234567", "../../x", None, "1234567g"):
        try:
            check_id(bad)
            raise AssertionError(f"거부 안 됨: {bad}")
        except ValueError:
            pass
    from common.config.settings import COMMON  # S7b — 시험이 env 대신 설정 객체를 덮어씀

    with tempfile.TemporaryDirectory() as d, COMMON.env(INDEX_ROOT=d):
        (Path(d) / a).mkdir()
        assert info(a) is None and list_ids() == []  # 완료 표시 없음 = 없는 색인
        (Path(d) / a / "index.json").write_text(json.dumps({"index_id": a}), encoding="utf-8")
        assert info(a) == {"index_id": a} and list_ids() == [a]
        assert bundle_dir(a) == Path(d) / a / "bundle"
    with tempfile.TemporaryDirectory() as d:
        g = Path(d) / "g"
        g.mkdir()
        (g / "domain_terms.csv").write_text("a", encoding="utf-8")
        e1 = {"GLOSSARY_DIR": str(g)}
        assert glossary_fp({}) == "none" and roster_fp({}) == "none" and glossary_fp(e1) != "none"
    print("[selftest] index_cfg — check_id 거부·완료 표시(info·list_ids·bundle_dir)·사전·명부 지문 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
