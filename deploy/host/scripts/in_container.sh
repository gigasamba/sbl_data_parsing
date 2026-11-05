#!/bin/bash
# 이미지 변수 확인(pipe_exec.sh·mcp_keepalive.sh·host_ctl.sh가 source). 서버 이미지 2개:
#   DATA_PIPELINE_IMAGE = data-pipeline:<태그> · MCP_SERVER_IMAGE = mcp-server:<태그>
#   없으면 compose가 `${…:?}` 필수 안내로 멈춘다. 값은 출력하지 않는다.
#   이 이름은 settings.yaml(required.deploy.pipeline_image·mcp_image)에서 load_settings.sh load_settings가 셸 env로 낸다. 부르기 전에 load_settings.
# 실행 이미지(*-runtime:태그)인데 CODE_DIR가 비면 이 코드 폴더 루트(부른 스크립트가 cd한 곳 —
#   git zip을 푼 폴더 그대로)를 코드 폴더로 쓴다. 이미 CODE_DIR가 있으면 그 값. 코드가 든 이미지는 손대지 않음.
code_dir_default() {   # code_dir_default <이미지 변수 이름>
  [ -n "${CODE_DIR:-}" ] && return 0
  case "${!1:-}" in *-runtime:*) CODE_DIR=$(pwd); export CODE_DIR ;; esac
  return 0
}
# 운영 작업(parse·publish·도구·migrate·show-stack)은 상주 data-pipeline 컨테이너
#   안에서 이미지 시작 스크립트로 돈다(docker exec — 컨테이너가 붙인 설정 파일·폴더·코드 그대로). 시작 스크립트: 코드가 든 이미지는
#   /app/docker/entrypoint.sh, 실행 이미지(*-runtime — 코드 폴더를 붙임)는 /app/docker/runtime_entry.sh.
in_pipeline() {   # in_pipeline <상주 컨테이너> <명령> [인자…] — 종료 코드는 그 명령 그대로 · 컨테이너가 안 떠 있으면 2
  local c=$1
  shift
  # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo podman)
  if [ "$($DOCKER inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != true ]; then
    echo "[오류] 상주 컨테이너 $c가 떠 있지 않음 — 먼저 띄울 것: \`bash deploy/host/scripts/host_ctl.sh up -d data-pipeline\`(실행 이미지면 compose.code.yml도 — host_ctl.sh가 붙임)" >&2
    return 2
  fi
  local tty=()
  [ -t 0 ] && [ -t 1 ] && tty=(-it)   # 터미널에서 부르면 Ctrl-C가 컨테이너 안 작업까지 감(tty 없으면 exec는 신호를 넘기지 않음)
  # shellcheck disable=SC2016,SC2086
  $DOCKER exec ${tty[@]+"${tty[@]}"} "$c" bash -c 'e=/app/docker/entrypoint.sh; [ -f "$e" ] || e=/app/docker/runtime_entry.sh; exec bash "$e" "$@"' _ "$@"
}
