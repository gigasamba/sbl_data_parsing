#!/bin/bash
# 근거 MCP 상주 확인·기동(사용자 10-08 — 수집 서버에서 늘 켜 둠). 여러 번 불러도 안전(멱등):
#   /health가 응답하면 아무것도 안 함 · 컨테이너가 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart.
#   bash deploy/host/scripts/mcp_up.sh   (사람이 한 번, S6b — 옛 docker/mcp_up.sh) · systemd 타이머 deploy/host/systemd/mcp-server-keepalive.timer가 2분마다
#   S6b(D-020, 사용자 10-27) — 이미지 mcp-server(MCP_SERVER_IMAGE), 컨테이너 이름 mcp-server(옛 data-retrieval)
# 설정: settings.yaml(SETTINGS_FILE, 기본 $SERVER_ENV_DIR/settings.yaml — SERVER_ENV_DIR 기본 배치 /srv/rag/env, S7e1 사용자 10-27 Q3·Q5) — 호스트 칸
#      (MCP_SERVER_IMAGE·RAG_OUT·MCP_HOST·MCP_PORT)을 settings_env.sh load_settings가 셸 env로, 컨테이너는 같은 파일을 붙여 읽음(토큰·PG 접속 등 비밀)
#      DOCKER(셸 env > settings.yaml ops.host.docker > podman, 없으면 docker — op-10 · 두 낱말도 됨: DOCKER="sudo podman") · PATCH_CODE(덧씌우기/전체 덮어쓰기 코드 폴더 — 있으면 compose.patch.mcp.yml도)
# 종료 코드: 0 응답 확인(원래 떠 있었거나 다시 띄움) · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
. deploy/host/scripts/settings_env.sh && load_settings || exit $?   # S7e1 — compose 치환(MCP_SERVER_IMAGE·RAG_OUT)과 /health 주소 — 값은 출력하지 않음
. deploy/host/scripts/image_vars.sh; need_image mcp || exit 2; code_dir_default MCP_SERVER_IMAGE   # op-06 — 실행 이미지면 코드 폴더 루트 · S6b — compose.mcp.yml은 MCP_SERVER_IMAGE만 봄(옛 DATA_RETRIEVAL_IMAGE·RAG_IMAGE만 있으면 종료 코드 2)
PATCH_CODE=${PATCH_CODE:-/srv/rag/code/live}
files="-f deploy/host/compose/compose.mcp.yml"
[ -n "${CODE_DIR:-}" ] && files="$files -f deploy/host/compose/compose.code.mcp.yml"   # op-06 — 개발 서버(실행 이미지): 코드 폴더를 /app/deploy에
[ -d "$PATCH_CODE/app" ] && files="$files -f deploy/host/compose/compose.patch.mcp.yml"
DC="$DOCKER compose $files"
URL="http://${MCP_HOST:-127.0.0.1}:${MCP_PORT:-8765}/health"

alive() { python3 -c "import urllib.request as u; u.urlopen('$URL', timeout=5)" >/dev/null 2>&1; }

if alive; then
  exit 0
fi
state=$($DOCKER inspect -f '{{.State.Status}}' mcp-server 2>/dev/null || echo none)   # S6b — 옛 data-retrieval(그 전 rag-mcp)
echo "[mcp_up] $(date '+%F %T') /health 응답 없음 — 컨테이너 상태 $state"
if [ "$state" = running ]; then
  $DOCKER restart mcp-server >/dev/null
else
  $DC up -d mcp
fi
for _ in $(seq 1 30); do alive && { echo "[mcp_up] 다시 띄움 — $URL 응답"; exit 0; }; sleep 2; done
echo "[mcp_up] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 mcp-server 2>&1 | tail -20
exit 1
