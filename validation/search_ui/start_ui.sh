#!/bin/bash
# 검증 페이지 서버 기동 — http://127.0.0.1:<mcp.dev.ui_port> (MCP 서버를 먼저 띄운다: start_mcp.sh)
#   bash validation/search_ui/start_ui.sh
set -euo pipefail
. "$(dirname "$0")/_env.sh"
exec "$PY" "$V/serve.py"
