#!/bin/bash
# 운영 묶음 상주 확인·기동(멱등) — Redis · parse_document 작업 컨테이너 · 검색 MCP(이름은 settings.yaml ops.host.parse_container·mcp_container).
#   /health가 응답하면 그대로 · 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart. systemd 타이머 mcp-server-keepalive가 2분마다.
#   /health는 검색 MCP 컨테이너 안에서 http://<mcp_bind_host>:8051/health(서버 네트워크 그대로라 서버 IP에만 열림).
# 종료 코드: 0 응답 확인 · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력) · 2 바인드 주소가 auto·루프백
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?
UP="bash deploy/host/scripts/host_ctl.sh up -d"
MCP=${MCP_CONTAINER:-mcp-server}
PARSE=${PARSE_CONTAINER:-mcp-data-parsing}
# shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
redis_state=$($DOCKER inspect -f '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' redis 2>/dev/null || true)
case "$redis_state" in
  "true healthy"|"true starting") ;;
  "true unhealthy") $DOCKER restart redis >/dev/null || echo "[mcp_keepalive] Redis 재시작 실패 — 검색 MCP 확인은 계속" >&2 ;;
  *) $DOCKER start redis >/dev/null 2>&1 || $UP redis || echo "[mcp_keepalive] Redis 기동 실패(compose 파일 redis의 REDIS_PASSWORD 칸 확인) — 검색 MCP 확인은 계속" >&2 ;;
esac
# parse_document 작업 컨테이너 — 꺼졌으면 up -d만(응답 확인은 검색 MCP의 몫).
if [ "$($DOCKER inspect -f '{{.State.Running}}' "$PARSE" 2>/dev/null)" != true ]; then
  echo "[mcp_keepalive] $(date '+%F %T') $PARSE 꺼짐 — 띄움"
  $UP "$PARSE" || echo "[mcp_keepalive] $PARSE 띄우기 실패 — parse_document는 '연결 실패'를 돌려줌(검색은 그대로)" >&2
fi
# 바인드 주소가 auto·루프백이면 밖에서 못 붙는데 /health는 응답함 — 다시 띄우지 않고 멈춤(settings.yaml을 고쳐야 함)
bad_host() { $DOCKER exec "$MCP" python -c "import sys; from mcp_server import config as mc; sys.exit(mc.cfg().server.host not in ('auto', '127.0.0.1', 'localhost', None))" >/dev/null 2>&1; }
alive() { $DOCKER exec "$MCP" python -c "import urllib.request as u; from mcp_server import config as mc; u.urlopen(f'http://{mc.cfg().server.host}:8051/health', timeout=5)" >/dev/null 2>&1; }   # 바인드 주소는 컨테이너의 settings.yaml

if bad_host; then
  echo "[mcp_keepalive] settings.yaml search.server.mcp_bind_host가 auto·127.0.0.1 — <서버 IP>로 고친 뒤 host_ctl.sh up -d $MCP" >&2
  exit 2
fi
if alive; then
  exit 0
fi
state=$($DOCKER inspect -f '{{.State.Status}}' "$MCP" 2>/dev/null || echo none)
echo "[mcp_keepalive] $(date '+%F %T') /health 응답 없음 — 컨테이너 상태 $state"
if [ "$state" = running ]; then
  $DOCKER restart "$MCP" >/dev/null
else
  $UP "$MCP"
fi
for _ in $(seq 1 30); do alive && { echo "[mcp_keepalive] 다시 띄움 — /health 응답"; exit 0; }; sleep 2; done
echo "[mcp_keepalive] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 "$MCP" 2>&1 | tail -20
exit 1
