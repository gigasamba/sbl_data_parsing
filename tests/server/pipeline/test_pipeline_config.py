"""pipeline.config 시험."""

from pipeline.config import PipelineAppSettings
from tests.server.common.appcheck import app_selftest


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    app_selftest(PipelineAppSettings, "pipeline")
