#!/bin/bash
# 0번 벌 상주 확인·기동 — Redis · parse_document 작업 컨테이너 mcp-data-parsing-0 · 검색 MCP mcp-server-0. 여러 번 불러도 안전(멱등):
#   /health가 응답하면 검색 MCP는 그대로 · 컨테이너가 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart.
#   bash deploy/host/scripts/mcp_keepalive.sh   (사람이 한 번) · systemd 타이머 deploy/host/systemd/mcp-server-keepalive.timer가 2분마다
#   Redis(compose-redis.yml — 이름 redis)는 꺼졌으면 그 파일로 up -d, 건강하지 않으면 restart. 앱 컨테이너는 host_ctl.sh up -d <서비스>
#   (이 코드 폴더 settings.yaml run_env의 compose-<환경>.yml). /health는 서버에서 http://127.0.0.1:8051/health(compose가 안팎 8051로 게시).
# 설정: settings.yaml(<루트>/settings.yaml — 루트 = 코드 폴더 자체) — DOCKER(셸 env > ops.host.container_cli > docker, 없으면 podman)
# 종료 코드: 0 응답 확인(원래 떠 있었거나 다시 띄움) · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?
UP="bash deploy/host/scripts/host_ctl.sh up -d"
MCP=mcp-server-0
PARSE=mcp-data-parsing-0
URL=http://127.0.0.1:8051/health
# shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
redis_state=$($DOCKER inspect -f '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' redis 2>/dev/null || true)
case "$redis_state" in
  "true healthy"|"true starting") ;;
  "true unhealthy") $DOCKER restart redis >/dev/null || echo "[mcp_keepalive] Redis 재시작 실패 — 검색 MCP 확인은 계속" >&2 ;;
  *) $DOCKER compose -f deploy/host/compose/compose-redis.yml up -d || echo "[mcp_keepalive] Redis 기동 실패(host_ctl.sh secrets 먼저) — 검색 MCP 확인은 계속" >&2 ;;
esac
# parse_document 작업 컨테이너 — 꺼졌으면 up -d만(응답 확인은 검색 MCP의 몫).
if [ "$($DOCKER inspect -f '{{.State.Running}}' "$PARSE" 2>/dev/null)" != true ]; then
  echo "[mcp_keepalive] $(date '+%F %T') $PARSE 꺼짐 — 띄움"
  $UP "$PARSE" || echo "[mcp_keepalive] $PARSE 띄우기 실패 — parse_document는 '연결 실패'를 돌려줌(검색은 그대로)" >&2
fi
alive() { python3 -c "import urllib.request as u; u.urlopen('$URL', timeout=5)" >/dev/null 2>&1; }

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
for _ in $(seq 1 30); do alive && { echo "[mcp_keepalive] 다시 띄움 — $URL 응답"; exit 0; }; sleep 2; done
echo "[mcp_keepalive] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 "$MCP" 2>&1 | tail -20
exit 1
