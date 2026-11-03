#!/bin/bash
# 상주 컨테이너 3개(data-pipeline·data-pipeline-mcp·mcp)를 부르는 compose 입구(사용자 11-03 — 옛 README `dc()` 셸 함수를 대신함).
#   bash deploy/host/scripts/dc.sh up -d data-pipeline data-pipeline-mcp mcp   (서비스 하나만도 됨 · ps·logs·down 등 compose 하위 명령 그대로)
# 하는 일: 코드 폴더 루트로 cd → settings.yaml을 셸 env로(settings_env.sh load_settings — 값은 출력 안 함) → 실행 이미지(*-runtime)면
#   이 코드 폴더를 CODE_DIR로(image_vars.sh code_dir_default — 파이프라인 이미지 기준, 개발 서버는 두 이미지가 함께 runtime) →
#   $DOCKER compose -f compose.pipeline.yml -f compose.pipeline-mcp.yml -f compose.mcp-server.yml [+ CODE_DIR면 compose.code*.yml] "$@".
# 프로젝트 이름은 compose 기본(첫 -f 파일의 폴더) — mcp_up.sh가 따로 부를 때와 같다(mcp_up.sh는 이 파일을 쓰지 않고 혼자 돎).
# 종료 코드: compose 그대로 · 설정을 못 읽으면 load_settings의 코드(2).
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/settings_env.sh && load_settings || exit $?
. deploy/host/scripts/image_vars.sh && code_dir_default DATA_PIPELINE_IMAGE
C=deploy/host/compose
files="-f $C/compose.pipeline.yml -f $C/compose.pipeline-mcp.yml -f $C/compose.mcp-server.yml"
[ -n "${CODE_DIR:-}" ] && files="$files -f $C/compose.code.yml -f $C/compose.code.pipeline-mcp.yml -f $C/compose.code.mcp-server.yml"
# shellcheck disable=SC2086 — DOCKER(sudo podman처럼 두 낱말)·파일 인자는 낱말 나눔
exec $DOCKER compose $files "$@"
