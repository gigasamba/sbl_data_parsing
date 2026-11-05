#!/bin/bash
# 근거 MCP 상주 확인·기동(수집 서버에서 늘 켜 둠). 여러 번 불러도 안전(멱등):
#   /health가 응답하면 아무것도 안 함 · 컨테이너가 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart.
#   bash deploy/host/scripts/mcp_keepalive.sh   (사람이 한 번) · systemd 타이머 deploy/host/systemd/mcp-server-keepalive.timer가 2분마다
#   이미지 mcp-server(MCP_SERVER_IMAGE), 컨테이너 이름 mcp-server
# 설정: settings.yaml(SETTINGS_FILE, 기본 <루트>/settings.yaml — 루트 = 코드 폴더의 부모) — 호스트 칸
#      (MCP_SERVER_IMAGE·RAG_OUT·MCP_HOST·MCP_PORT)을 load_settings.sh load_settings가 셸 env로, 컨테이너는 같은 파일을 붙여 읽음(토큰·PG 접속 등 비밀)
#      DOCKER(셸 env > settings.yaml ops.host.container_cli > podman, 없으면 docker · 두 낱말도 됨: DOCKER="sudo podman")
# 종료 코드: 0 응답 확인(원래 떠 있었거나 다시 띄움) · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # compose 치환(MCP_SERVER_IMAGE·RAG_OUT)과 /health 주소 — 값은 출력하지 않음
code0=${CODE_DIR:-}   # 사람·unit이 준 값(code_dir_default 전) — 파이프라인 컨테이너는 자기 이미지로 따로 정함(아래)
. deploy/host/scripts/in_container.sh; code_dir_default MCP_SERVER_IMAGE   # 실행 이미지면 코드 폴더 루트 · compose.mcp-server.yml은 MCP_SERVER_IMAGE만 봄
files="-f deploy/host/compose/compose.mcp-server.yml"
[ -n "${CODE_DIR:-}" ] && files="$files -f deploy/host/compose/compose.code.mcp-server.yml"   # 개발 서버(실행 이미지): 코드 폴더를 컨테이너 코드 자리에
DC="$DOCKER compose -p compose$NAME_SUFFIX $files"   # 묶음 이름 — host_ctl.sh와 같게(여러 벌)
# parse_document 작업 서비스 전용 컨테이너(mcp-data-parsing)도 여기서 살핀다(타이머 2분마다). 꺼졌으면 up -d만(응답 확인은 검색 MCP의 몫).
if [ "$($DOCKER inspect -f '{{.State.Running}}' "mcp-data-parsing$NAME_SUFFIX" 2>/dev/null)" != true ]; then
  echo "[mcp_keepalive] $(date '+%F %T') mcp-data-parsing 꺼짐 — 띄움"
  # shellcheck disable=SC2086 — 파일 인자(낱말 나눔)
  (CODE_DIR=$code0 && code_dir_default DATA_PIPELINE_IMAGE && $DOCKER compose -p "compose$NAME_SUFFIX" -f deploy/host/compose/compose.data-parsing.yml ${CODE_DIR:+-f deploy/host/compose/compose.code.data-parsing.yml} up -d mcp-data-parsing) ||
    echo "[mcp_keepalive] mcp-data-parsing 띄우기 실패 — parse_document는 '연결 실패'를 돌려줌(검색은 그대로)" >&2
fi
URL="http://${MCP_HOST:-127.0.0.1}:${MCP_PORT:-8765}/health"

alive() { python3 -c "import urllib.request as u; u.urlopen('$URL', timeout=5)" >/dev/null 2>&1; }

if alive; then
  exit 0
fi
state=$($DOCKER inspect -f '{{.State.Status}}' "mcp-server$NAME_SUFFIX" 2>/dev/null || echo none)
echo "[mcp_keepalive] $(date '+%F %T') /health 응답 없음 — 컨테이너 상태 $state"
if [ "$state" = running ]; then
  $DOCKER restart "mcp-server$NAME_SUFFIX" >/dev/null
else
  $DC up -d mcp
fi
for _ in $(seq 1 30); do alive && { echo "[mcp_keepalive] 다시 띄움 — $URL 응답"; exit 0; }; sleep 2; done
echo "[mcp_keepalive] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 "mcp-server$NAME_SUFFIX" 2>&1 | tail -20
exit 1
