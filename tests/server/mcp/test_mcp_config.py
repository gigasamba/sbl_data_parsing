"""mcp_server.config 시험."""

from mcp_server.config import McpAppSettings
from tests.server.common.appcheck import (
    app_selftest,
)  # 옛 `show.app_selftest`(common/config/show.py) — S9에 tests/server/common/appcheck.py로 옮김


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    app_selftest(McpAppSettings, "mcp")
