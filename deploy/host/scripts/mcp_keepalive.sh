#!/bin/bash
# 근거 MCP 상주 확인·기동(수집 서버에서 늘 켜 둠). 여러 번 불러도 안전(멱등):
#   /health가 응답하면 아무것도 안 함 · 컨테이너가 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart.
#   bash deploy/host/scripts/mcp_keepalive.sh   (사람이 한 번) · systemd 타이머 deploy/host/systemd/mcp-server-keepalive.timer가 2분마다
#   이미지 MCP_SERVER_IMAGE, 컨테이너 이름 MCP_CNAME·DATA_PARSING_CNAME(load_settings — ops.containers.*_container_name + 벌 번호)
#   띄우기는 host_ctl.sh base up -d <서비스> — host_ctl.sh와 같은 compose 파일 묶음(이미지마다 코드 폴더 짝·ops.host.extra_compose)에서
#   개발 작업 공간 파일·관문만 뺌(작업 공간 설정이 검색 MCP 살리기를 막지 않게 · data-pipeline은 건드리지 않음)
# 설정: settings.yaml(SETTINGS_FILE, 기본 <루트>/settings.yaml — 루트 = 코드 폴더 자체) — 호스트 칸
#      (MCP_SERVER_IMAGE·RAG_OUT·MCP_HOST·MCP_PORT)을 load_settings.sh load_settings가 셸 env로, 컨테이너는 같은 파일을 붙여 읽음(토큰·PG 접속 등 비밀)
#      DOCKER(셸 env > settings.yaml ops.host.container_cli > docker, 없으면 podman · 두 낱말도 됨: DOCKER="sudo docker")
# 종료 코드: 0 응답 확인(원래 떠 있었거나 다시 띄움) · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # 컨테이너 이름과 /health 주소 — 값은 출력하지 않음
UP="bash deploy/host/scripts/host_ctl.sh base up -d"
# parse_document 작업 서비스 전용 컨테이너(mcp-data-parsing)도 여기서 살핀다(타이머 2분마다). 꺼졌으면 up -d만(응답 확인은 검색 MCP의 몫).
if [ "$($DOCKER inspect -f '{{.State.Running}}' "$DATA_PARSING_CNAME" 2>/dev/null)" != true ]; then
  echo "[mcp_keepalive] $(date '+%F %T') $DATA_PARSING_CNAME 꺼짐 — 띄움"
  $UP mcp-data-parsing ||
    echo "[mcp_keepalive] $DATA_PARSING_CNAME 띄우기 실패 — parse_document는 '연결 실패'를 돌려줌(검색은 그대로)" >&2
fi
if [ "${MCP_HOST:-}" = auto ]; then
  # auto = 컨테이너 자기 사설 IP — 호스트에서 풀면 다를 수 있어(podman이 /etc/hosts를 따로 씀) 컨테이너 안에서
  #   compose.mcp-server.yml healthcheck·mcp_server/main.py와 같은 풀이로 묻는다(풀이 실패 = 응답 없음)
  URL="컨테이너 안 http://<자기 IP>:${MCP_PORT:-8765}/health"
  alive() { $DOCKER exec "$MCP_CNAME" python -c "import socket, urllib.request as u; u.urlopen(f'http://{socket.gethostbyname(socket.gethostname())}:${MCP_PORT:-8765}/health', timeout=5)" >/dev/null 2>&1; }
else
  URL="http://${MCP_HOST:-127.0.0.1}:${MCP_PORT:-8765}/health"
  alive() { python3 -c "import urllib.request as u; u.urlopen('$URL', timeout=5)" >/dev/null 2>&1; }
fi

if alive; then
  exit 0
fi
state=$($DOCKER inspect -f '{{.State.Status}}' "$MCP_CNAME" 2>/dev/null || echo none)
echo "[mcp_keepalive] $(date '+%F %T') /health 응답 없음 — 컨테이너 상태 $state"
if [ "$state" = running ]; then
  $DOCKER restart "$MCP_CNAME" >/dev/null
else
  $UP mcp
fi
for _ in $(seq 1 30); do alive && { echo "[mcp_keepalive] 다시 띄움 — $URL 응답"; exit 0; }; sleep 2; done
echo "[mcp_keepalive] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 "$MCP_CNAME" 2>&1 | tail -20
exit 1
