#!/bin/bash
# settings.yaml → 셸 env 다리(S7e1 정식 — refactor_plan 5-2 · D-028 ⑭, 사용자 10-27 Q3~Q5). 비밀 칸은 내보내지 않는다(컨테이너 안 앱이 붙인 설정 파일에서 읽음).
#   source: . deploy/host/scripts/settings_env.sh && load_settings || exit $?   — trigger.sh·run_tool.sh·mcp_up.sh·systemd nightly가 씀
#     설정 파일: SETTINGS_FILE(있으면) > $SERVER_ENV_DIR/settings.yaml(서버 기본 배치 /srv/rag/env) > (RUN_ENV=local) 저장소 루트 settings.yaml
#     없으면 종료 코드 2 — $SERVER_ENV_DIR/pipeline.env만 있으면 "설정 이관 필요" 안내(옛 env 파일은 더 읽지 않음 — Q5)
#     호스트 칸(HOST_SECTIONS — 이미지·자원·포트·호스트 경로·RUN_ENV·새벽 배치 PARSE_DEADLINE, compose healthcheck·mcp_up.sh가 쓰는 앱 칸 MCP_HOST·MCP_PORT·
#     TRIGGER_PARSE_PORT·TRIGGER_STRUCTURE_PORT)을 export한다. 이미 셸 env에 있는 이름은 덮지 않는다(옛 compose의 "셸 env > --env-file"과 같음).
#     S7e2 — 컨테이너는 이 값을 env로 받지 않는다(앱이 붙인 settings.yaml에서 직접 — compose environment의 덮기 줄 없앰).
#     YAML에 없는 칸은 내지 않으므로 compose 파일 기본값(${X:-…})이 그대로 걸린다(R-h). SETTINGS_FILE은 절대 경로로 export(compose 마운트 원본).
#   실행: bash deploy/host/scripts/settings_env.sh [--sh] [--image <이미지>] <절>...     예: pipeline.host  common.host  mcp.host
#     기본: compose --env-file용 KEY=값 줄(값에 $가 있으면 거부) · --sh: `export KEY='값'` 줄
# 호스트 python이 코드 폴더의 common.config.export를 import할 수 있으면(pydantic·PyYAML 포함) 그것으로, 없으면 이미지 안에서 돈다(--image, 없으면
# SETTINGS_IMAGE·DATA_PIPELINE_IMAGE — 설정 파일을 표준 입력으로 넘김: 마운트가 없어 파일 권한·컨테이너 UID·rootless podman·SELinux 라벨과 무관, VS7a R-6 · C-36).
# 코드 폴더: 서버 배치 <루트>/app/deploy(release-and-patch §4 — live/app/deploy/{common,pipeline,mcp_server})가 있으면 그것, 없으면 저장소 루트(PC) — VS7e1 B-1.
# DOCKER로 docker·podman을 고른다(`DOCKER="sudo podman"`처럼 두 낱말도 — 따옴표 없이 펼침, VS7e1 R-1). 값은 출력하지 않는다(source 쪽 — 실행 쪽은 요청한 줄만 표준 출력에).
#   op-10 — 셸 env와 settings.yaml(ops.host.docker)에 없으면 podman(서버 기본 컨테이너 도구), podman이 없으면 docker(docker_default).
HOST_SECTIONS="common.run_env common.host pipeline.host pipeline.night.parse_deadline pipeline.service.trigger.parse_port pipeline.service.trigger.structure_port mcp.host mcp.server.host mcp.server.port"
docker_default() { command -v podman >/dev/null 2>&1 && echo podman || echo docker; }   # op-10 — 서버(RHEL) 기본 podman, 없으면 docker(bake.sh와 같음)
_SETTINGS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)   # 배치 루트(서버 live/ — deploy/host가 바로 아래 · PC 저장소 루트)
if [ -d "$_SETTINGS_ROOT/app/deploy/common" ]; then
  _SETTINGS_CODE=$_SETTINGS_ROOT/app/deploy      # 서버 배치(이미지 /app/deploy와 같은 꼴)
else
  _SETTINGS_CODE=$_SETTINGS_ROOT                 # PC 저장소(common·pipeline·mcp_server가 루트 바로 아래)
fi

settings_export() {   # settings_export <env|sh> [--image <이미지>] <절>... — 줄을 표준 출력에, 실패면 0 아닌 종료 코드(안내는 표준 오류)
  local fmt=$1 image="" py=${PY:-python3} s
  shift
  if [ "${1:-}" = --image ]; then image=${2:-}; shift 2; fi
  local args=()
  for s in "$@"; do args+=(--section "$s"); done
  [ ${#args[@]} -gt 0 ] || { echo "[settings_env] 절 이름이 필요함(예: pipeline.host)" >&2; return 2; }
  # 확인은 export 모듈 import 그대로(B-1 — 코드 폴더를 못 찾거나 pydantic·PyYAML이 없으면 이미지 경로로). 설정 파일은 안 읽게 SETTINGS_FILE·RUN_ENV를 빼고
  # 확인한다 — 틀린 설정 파일이면 아래 export가 [export] 줄로 알림(이미지로 넘겨도 같은 오류라 넘기지 않음)
  if (cd "$_SETTINGS_CODE" && env -u SETTINGS_FILE -u RUN_ENV PYTHONPATH="$_SETTINGS_CODE" "$py" -c 'import common.config.export' >/dev/null 2>&1); then
    (cd "$_SETTINGS_CODE" && PYTHONPATH="$_SETTINGS_CODE" "$py" -m common.config.export --format "$fmt" "${args[@]}")
    return
  fi
  image=${image:-${SETTINGS_IMAGE:-${DATA_PIPELINE_IMAGE:-}}}
  # 이미지 이름은 settings.yaml 안에 있어 아직 모름 → 코드 폴더 VERSION의 실행 이미지(태그 = 버전, D-036 — zip 배치 개발 서버, 사용자 10-30 검토 B2)
  if [ -z "$image" ] && [ -f "$_SETTINGS_CODE/VERSION" ]; then image=data-pipeline-runtime:$(tr -d ' \t\r\n' < "$_SETTINGS_CODE/VERSION"); fi
  [ -n "$image" ] || { echo "[settings_env] 호스트 python에 pydantic·PyYAML이 없음 — SETTINGS_IMAGE=<data-pipeline:태그>(또는 --image)로 이미지 안에서 돌림" >&2; return 2; }
  local code=()                             # 실행 이미지(코드 없음)면 이 코드 폴더를 붙여 export 모듈을 읽게(op-06)
  case "$image" in *-runtime:*) code=(-v "$_SETTINGS_CODE:/app/deploy:ro,z" -e PYTHONPATH=/app/deploy) ;; esac
  [ -n "${SETTINGS_FILE:-}" ] && [ -f "$SETTINGS_FILE" ] || { echo "[settings_env] 이미지로 돌릴 때는 SETTINGS_FILE(설정 파일 경로)이 있어야 함" >&2; return 2; }
  local run_env=()                          # 호출자 RUN_ENV를 컨테이너에도 — 호스트 python 경로와 같게(env > 파일 common.run_env, VS7a2 R-b)
  [ -z "${RUN_ENV:-}" ] || run_env=(-e "RUN_ENV=$RUN_ENV")
  # 표준 입력을 컨테이너 안 임시 파일로 먼저 옮긴다 — SETTINGS_FILE=/dev/stdin이면 import common의 다리가 먼저 읽어 export가 빈 파일을 봄(S7e1 리뷰)
  # shellcheck disable=SC2016,SC2086 — DOCKER는 낱말 나눔(sudo podman)
  ${DOCKER:-$(docker_default)} run --rm -i --network none --entrypoint bash ${run_env[@]+"${run_env[@]}"} ${code[@]+"${code[@]}"} "$image" \
    -c 'umask 077 && cat > /tmp/settings.yaml && SETTINGS_FILE=/tmp/settings.yaml exec python -m common.config.export "$@"' _ \
    --format "$fmt" "${args[@]}" < "$SETTINGS_FILE"
}

load_settings() {   # 위 설명(source) — 성공 0 · 설정 파일 없음·틀림 2
  export SERVER_ENV_DIR=${SERVER_ENV_DIR:-/srv/rag/env}
  if [ -z "${SETTINGS_FILE:-}" ]; then
    if [ -f "$SERVER_ENV_DIR/settings.yaml" ]; then
      SETTINGS_FILE=$SERVER_ENV_DIR/settings.yaml
    elif [ "${RUN_ENV:-}" = local ] && [ -f "$_SETTINGS_ROOT/settings.yaml" ]; then
      SETTINGS_FILE=$_SETTINGS_ROOT/settings.yaml        # PC(저장소 루트)
    fi
  fi
  if [ -z "${SETTINGS_FILE:-}" ] || [ ! -f "$SETTINGS_FILE" ]; then
    if [ -f "$SERVER_ENV_DIR/pipeline.env" ]; then
      echo "[설정] 설정 이관 필요 — 이 판부터 $SERVER_ENV_DIR/settings.yaml만 읽는다(옛 pipeline.env는 읽지 않음). 옮기기:" \
           "python -m common.config.migrate $SERVER_ENV_DIR/pipeline.env --out $SERVER_ENV_DIR/settings.yaml 뒤 --compare로 확인" \
           "(docs/operations/release-and-patch.md §5-4 · refactor.md C-09)" >&2
    else
      echo "[설정] 설정 파일 없음: ${SETTINGS_FILE:-$SERVER_ENV_DIR/settings.yaml} — SETTINGS_FILE 또는 \$SERVER_ENV_DIR/settings.yaml(docs/operations/env-guide.md)" >&2
    fi
    return 2
  fi
  case "$SETTINGS_FILE" in /*) ;; *) SETTINGS_FILE=$PWD/$SETTINGS_FILE ;; esac
  export SETTINGS_FILE
  if [ "${SETTINGS_LOADED:-}" = "$SETTINGS_FILE" ]; then   # 이 셸(또는 부른 부모 — systemd nightly → trigger.sh)이 같은 파일로 이미 냄
    DOCKER=${DOCKER:-$(docker_default)}; export DOCKER
    return 0
  fi
  local out line name
  # shellcheck disable=SC2086
  out=$(settings_export sh $HOST_SECTIONS) || { echo "[설정] 설정 파일에서 호스트 값을 읽지 못함($SETTINGS_FILE) — 위 안내 확인" >&2; return 2; }
  while IFS= read -r line; do
    case "$line" in "export "*=*) ;; *) continue ;; esac
    name=${line#export }; name=${name%%=*}
    case "$name" in ''|*[!A-Za-z0-9_]*) continue ;; esac
    eval "[ -n \"\${$name+x}\" ]" && continue          # 셸 env에 이미 있으면 그 값(사람이 한 번만 덮어 부를 때)
    eval "$line"
  done <<EOF
$out
EOF
  export SETTINGS_LOADED=$SETTINGS_FILE   # 내부 신호 — 하위 스크립트가 같은 파일을 다시 읽지 않게
  DOCKER=${DOCKER:-$(docker_default)}; export DOCKER   # op-10 — 셸 env > settings.yaml(ops.host.docker) > podman(없으면 docker)
  return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then        # 실행(source가 아님)
  set -euo pipefail
  if [ -n "${SETTINGS_FILE:-}" ]; then
    case "$SETTINGS_FILE" in /*) ;; *) SETTINGS_FILE="$PWD/$SETTINGS_FILE";; esac
    export SETTINGS_FILE
  fi
  fmt=env
  image=""
  sections=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --sh) fmt=sh; shift ;;
      --image) image=${2:?--image 이미지}; shift 2 ;;
      -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
      *) sections+=("$1"); shift ;;
    esac
  done
  [ ${#sections[@]} -gt 0 ] || { echo "[settings_env] 절 이름이 필요함(예: pipeline.host)" >&2; exit 2; }
  if [ -n "$image" ]; then
    settings_export "$fmt" --image "$image" "${sections[@]}"
  else
    settings_export "$fmt" "${sections[@]}"
  fi
fi
