#!/bin/bash
# settings.yaml → 셸 env 다리(S7e1 정식 — refactor_plan 5-2 · D-028 ⑭, 사용자 10-27 Q3~Q5). 비밀 칸은 내보내지 않는다(컨테이너 안 앱이 붙인 설정 파일에서 읽음).
#   source: . deploy/host/scripts/settings_env.sh && load_settings || exit $?   — trigger.sh·run_tool.sh·mcp_up.sh·systemd nightly가 씀
#     설정 파일: SETTINGS_FILE(있으면) > $SERVER_ENV_DIR/settings.yaml(서버 기본 배치 /srv/rag/env) > (RUN_ENV=local) 저장소 루트 settings.yaml
#     없으면 종료 코드 2
#     호스트 칸(host_keys.tsv 전부 — deploy/release/hostkeys.py HOST_SECTIONS: 이미지·자원·포트·호스트 경로·RUN_ENV·새벽 배치 PARSE_DEADLINE, compose healthcheck·mcp_up.sh가 쓰는 앱 칸 MCP_HOST·MCP_PORT)을
#     export한다(옛 TRIGGER_PARSE_PORT·TRIGGER_STRUCTURE_PORT는 trigger 서버와 함께 11-01에 지움 — host_keys.tsv에 없음). 이미 셸 env에 있는 이름은 덮지 않는다(옛 compose의 "셸 env > --env-file"과 같음).
#     S7e2 — 컨테이너는 이 값을 env로 받지 않는다(앱이 붙인 settings.yaml에서 직접 — compose environment의 덮기 줄 없앰).
#     YAML에 없는 칸은 내지 않으므로 compose 파일 기본값(${X:-…})이 그대로 걸린다(R-h). SETTINGS_FILE은 절대 경로로 export(compose 마운트 원본).
#   실행: bash deploy/host/scripts/settings_env.sh [--sh] <절>...     예: pipeline.host  common.host  mcp.host
#     기본: compose --env-file용 KEY=값 줄(값에 $가 있으면 거부) · --sh: `export KEY='값'` 줄
# 호스트 python(python3 — 다르면 PY=<경로>)에 PyYAML만 있으면 된다: deploy/host/scripts/host_env.py가 host_keys.tsv(설정 모델에서 자동 생성 —
# `PYTHONPATH=. python deploy/release/hostkeys.py`)와 common/config/layout.py로 읽는다(사용자 11-02 — 옛 이미지 안 export 길·SETTINGS_IMAGE 지움).
# DOCKER로 docker·podman을 고른다(`DOCKER="sudo podman"`처럼 두 낱말도 — 따옴표 없이 펼침, VS7e1 R-1). 값은 출력하지 않는다(source 쪽 — 실행 쪽은 요청한 줄만 표준 출력에).
#   op-10 — 셸 env와 settings.yaml(ops.host.docker)에 없으면 podman(서버 기본 컨테이너 도구), podman이 없으면 docker(docker_default).
docker_default() { command -v podman >/dev/null 2>&1 && echo podman || echo docker; }   # op-10 — 서버(RHEL) 기본 podman, 없으면 docker(bake.sh와 같음)
_SETTINGS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)   # 배치 루트(서버 live/ — deploy/host가 바로 아래 · PC 저장소 루트)

settings_export() {   # settings_export <env|sh> [<절>...] — 줄을 표준 출력에(절이 없으면 호스트 칸 전부), 실패면 0 아닌 종료 코드(안내는 표준 오류)
  local fmt=$1
  shift
  "${PY:-python3}" "$_SETTINGS_ROOT/deploy/host/scripts/host_env.py" --format "$fmt" "$@"
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
    echo "[설정] 설정 파일 없음: ${SETTINGS_FILE:-$SERVER_ENV_DIR/settings.yaml} — SETTINGS_FILE 또는 \$SERVER_ENV_DIR/settings.yaml(docs/operations/env-guide.md)" >&2
    return 2
  fi
  case "$SETTINGS_FILE" in /*) ;; *) SETTINGS_FILE=$PWD/$SETTINGS_FILE ;; esac
  export SETTINGS_FILE
  SETTINGS_DIR=$(dirname "$SETTINGS_FILE"); export SETTINGS_DIR   # settings.yaml이 실제로 있는 폴더 — data-pipeline이 /etc/rag/env로 읽기 전용(EDW 사슬 사본 등, 사용자 11-03)
  if [ "${SETTINGS_LOADED:-}" = "$SETTINGS_FILE" ]; then   # 이 셸(또는 부른 부모 — systemd nightly → trigger.sh)이 같은 파일로 이미 냄
    DOCKER=${DOCKER:-$(docker_default)}; export DOCKER
    return 0
  fi
  local out line name
  out=$(settings_export sh) || { echo "[설정] 설정 파일에서 호스트 값을 읽지 못함($SETTINGS_FILE) — 위 안내 확인" >&2; return 2; }
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
  sections=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --sh) fmt=sh; shift ;;
      -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
      *) sections+=("$1"); shift ;;
    esac
  done
  [ ${#sections[@]} -gt 0 ] || { echo "[settings_env] 절 이름이 필요함(예: pipeline.host)" >&2; exit 2; }
  settings_export "$fmt" "${sections[@]}"
fi
