"""mcp_server.config 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.config --selftest`."""

from mcp_server.config import McpAppSettings
from tests.server.common.appcheck import (
    app_selftest,
)  # 옛 `show.app_selftest`(common/config/show.py) — S9에 tests/server/common/appcheck.py로 옮김


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    app_selftest(McpAppSettings, "mcp")
