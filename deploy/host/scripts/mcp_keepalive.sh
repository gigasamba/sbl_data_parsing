#!/bin/bash
# 근거 MCP 상주 확인·기동(사용자 10-08 — 수집 서버에서 늘 켜 둠). 여러 번 불러도 안전(멱등):
#   /health가 응답하면 아무것도 안 함 · 컨테이너가 없거나 꺼졌으면 up -d · 떠 있는데 응답 없으면 restart.
#   bash deploy/host/scripts/mcp_keepalive.sh   (사람이 한 번, S6b — 옛 docker/mcp_keepalive.sh) · systemd 타이머 deploy/host/systemd/mcp-server-keepalive.timer가 2분마다
#   S6b(D-020, 사용자 10-27) — 이미지 mcp-server(MCP_SERVER_IMAGE), 컨테이너 이름 mcp-server(옛 data-retrieval)
# 설정: settings.yaml(SETTINGS_FILE, 기본 <루트>/settings.yaml — 루트 = 코드 폴더의 부모, op-13) — 호스트 칸
#      (MCP_SERVER_IMAGE·RAG_OUT·MCP_HOST·MCP_PORT)을 load_settings.sh load_settings가 셸 env로, 컨테이너는 같은 파일을 붙여 읽음(토큰·PG 접속 등 비밀)
#      DOCKER(셸 env > settings.yaml ops.host.docker > podman, 없으면 docker — op-10 · 두 낱말도 됨: DOCKER="sudo podman")
# 종료 코드: 0 응답 확인(원래 떠 있었거나 다시 띄움) · 1 다시 띄웠는데도 응답 없음(로그 마지막 줄 출력)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # S7e1 — compose 치환(MCP_SERVER_IMAGE·RAG_OUT)과 /health 주소 — 값은 출력하지 않음
[ -d app ] && echo "[mcp_keepalive] 경고: 코드 폴더에 옛 오버레이 app/이 남아 있음 — 11-03부터 쓰지 않음(덧씌우기 compose 지움, 이미지·코드 폴더 코드로 뜸)" >&2
# compose는 host_ctl.sh 한 곳(rn-06 — 같은 묶음 이름·compose 파일·실행 이미지면 코드 폴더 마운트). 코드 폴더 판단은 파이프라인 이미지 기준 —
#   개발 서버(두 이미지 모두 *-runtime)·운영 서버(두 이미지 모두 구운 이미지)에서는 옛 이미지별 판단과 같다.
# parse_document 작업 서비스 전용 컨테이너(data-pipeline-mcp — rn-03)도 여기서 살핀다(타이머 2분마다). 꺼졌으면 up -d만(응답 확인은 검색 MCP의 몫).
if [ "$($DOCKER inspect -f '{{.State.Running}}' "data-pipeline-mcp$NAME_SUFFIX" 2>/dev/null)" != true ]; then
  echo "[mcp_keepalive] $(date '+%F %T') data-pipeline-mcp 꺼짐 — 띄움"
  bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-mcp ||
    echo "[mcp_keepalive] data-pipeline-mcp 띄우기 실패 — parse_document는 '연결 실패'를 돌려줌(검색은 그대로)" >&2
fi
URL="http://${MCP_HOST:-127.0.0.1}:${MCP_PORT:-8765}/health"

alive() { python3 -c "import urllib.request as u; u.urlopen('$URL', timeout=5)" >/dev/null 2>&1; }

if alive; then
  exit 0
fi
state=$($DOCKER inspect -f '{{.State.Status}}' "mcp-server$NAME_SUFFIX" 2>/dev/null || echo none)   # S6b — 옛 data-retrieval(그 전 rag-mcp)
echo "[mcp_keepalive] $(date '+%F %T') /health 응답 없음 — 컨테이너 상태 $state"
if [ "$state" = running ]; then
  $DOCKER restart "mcp-server$NAME_SUFFIX" >/dev/null
else
  bash deploy/host/scripts/host_ctl.sh up -d mcp
fi
for _ in $(seq 1 30); do alive && { echo "[mcp_keepalive] 다시 띄움 — $URL 응답"; exit 0; }; sleep 2; done
echo "[mcp_keepalive] 다시 띄웠는데도 응답 없음 — 마지막 로그:"
$DOCKER logs --tail 20 "mcp-server$NAME_SUFFIX" 2>&1 | tail -20
exit 1
