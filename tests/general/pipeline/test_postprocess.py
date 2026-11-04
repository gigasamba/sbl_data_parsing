"""pipeline.shared.post_config 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.shared.post_config`."""

from pathlib import Path

from pipeline import config as pc
from pipeline.shared.post_config import FEATURES, active_features, raw_root


def selftest_raw_root():
    import tempfile

    with pc.PIPE.env(PARSE_RAW_ROOT=str(Path(tempfile.gettempdir()) / "x" / "raw")):  # 실수로 .../raw까지 줌 — S7c: 객체만 바꿔 끼움
        assert raw_root().name != "raw"


def selftest():
    assert active_features("none") == frozenset()
    assert active_features("all") == frozenset(FEATURES)
    assert active_features("supsub,charts") == {"supsub", "charts"}
    assert active_features("") == frozenset()
    print("[selftest] PARSE_POST 설정 해석 통과")
    selftest_raw_root()
    print("[selftest] raw_root — '.../raw'를 줘도 raw/vlm 이중 중첩 방지 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
