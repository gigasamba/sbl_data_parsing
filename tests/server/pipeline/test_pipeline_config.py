"""pipeline.config 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.config --selftest`."""

from pipeline.config import PipelineAppSettings
from tests.server.common.appcheck import app_selftest


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    app_selftest(PipelineAppSettings, "pipeline")
