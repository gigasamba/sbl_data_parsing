#!/bin/bash
# 검색 MCP 서버(로컬 검증용) 기동 — http://127.0.0.1:<mcp.server.port>/mcp
#   bash validation/search_ui/start_mcp.sh
# 설정은 저장소 루트 settings.yaml 하나(mcp.server 절 · PG 접속(required.pg — 검색은 PG만) · 외부 임베딩은 models.embed.allow_external(EMBED_ALLOW_EXTERNAL)).
# 이 PC는 8765를 다른 프로그램이 써서 루트 파일에 다른 포트를 둔다. 셸 env의 설정 이름(LLM_* 등)은 읽지 않지만, 엔진 칸(VLM_* —
# 영구 다리, env가 이김)은 env로 읽히므로 셸에 남은 값이 새지 않게 지운다(VLM/LLM 없는 검증 서버).
set -euo pipefail
. "$(dirname "$0")/_env.sh"
unset VLM_BASE_URL VLM_MODEL VLM_API_KEY VLM_CONCURRENCY VLM_RETRY VLM_TIMEOUT
exec "$PY" -m mcp_server.main
