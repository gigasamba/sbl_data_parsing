#!/bin/bash
# settings.yaml → 셸 env 다리(S7e1 정식 — refactor_plan 5-2 · D-028 ⑭, 사용자 10-27 Q3~Q5). 비밀 칸은 내보내지 않는다(컨테이너 안 앱이 붙인 설정 파일에서 읽음).
#   source: . deploy/host/scripts/load_settings.sh && load_settings || exit $?   — nightly_batch.sh·pipe_exec.sh·mcp_keepalive.sh·host_ctl.sh·prune_images.sh가 씀
#     루트(op-13): 코드 폴더(deploy/가 든 폴더)의 부모 — 스크립트 자리에서 구한다(고정 경로 없음 — 이미 셸에 RAG_ROOT가 있으면 그 값:
#       부른 부모 스크립트·host_ctl.sh의 시험 루트 DC_ROOT). RAG_ROOT로 export(compose 마운트 원본).
#     설정 파일: SETTINGS_FILE(있으면) > <루트>/settings.yaml > (RUN_ENV=local) 저장소 루트 settings.yaml
#     결과 폴더 RAG_OUT: settings.yaml common.host.output_root(적었을 때) > <루트>/output
#     없으면 종료 코드 2
#     호스트 칸(host_settings.tsv 전부 — deploy/release/gen_host_keys.py HOST_SECTIONS: 이미지·자원·포트·호스트 경로·RUN_ENV·새벽 배치 PARSE_DEADLINE, compose healthcheck·mcp_keepalive.sh가 쓰는 앱 칸 MCP_HOST·MCP_PORT)을
#     export한다. 이미 셸 env에 있는 이름은 덮지 않는다(옛 compose의 "셸 env > --env-file"과 같음).
#     S7e2 — 컨테이너는 이 값을 env로 받지 않는다(앱이 붙인 settings.yaml에서 직접 — compose environment의 덮기 줄 없앰).
#     YAML에 없는 칸은 내지 않으므로 compose 파일 기본값(${X:-…})이 그대로 걸린다(R-h). SETTINGS_FILE은 절대 경로로 export(compose 마운트 원본).
#   실행: bash deploy/host/scripts/load_settings.sh [--sh] <절>...     예: pipeline.host  common.host  mcp.host
#     기본: compose --env-file용 KEY=값 줄(값에 $가 있으면 거부) · --sh: `export KEY='값'` 줄
# 호스트 python(python3 — 다르면 PY=<경로>)에 PyYAML만 있으면 된다: deploy/host/scripts/settings_to_env.py가 host_settings.tsv(설정 모델에서 자동 생성 —
# `PYTHONPATH=. python deploy/release/gen_host_keys.py`)와 common/config/layout.py로 읽는다(사용자 11-02 — 옛 이미지 안 export 길·SETTINGS_IMAGE 지움).
# DOCKER로 docker·podman을 고른다(`DOCKER="sudo podman"`처럼 두 낱말도 — 따옴표 없이 펼침, VS7e1 R-1). 값은 출력하지 않는다(source 쪽 — 실행 쪽은 요청한 줄만 표준 출력에).
#   op-10 — 셸 env와 settings.yaml(ops.host.docker)에 없으면 podman(서버 기본 컨테이너 도구), podman이 없으면 docker(docker_default).
docker_default() { command -v podman >/dev/null 2>&1 && echo podman || echo docker; }   # op-10 — 서버(RHEL) 기본 podman, 없으면 docker(bake_prod_image.sh와 같음)
_SETTINGS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)   # 코드 폴더(deploy/host가 바로 아래 — 서버 sbl_data_parsing-<판> · PC 저장소 루트)
RAG_ROOT=${RAG_ROOT:-$(dirname "$_SETTINGS_ROOT")}   # 서버 루트(op-13) — 코드 폴더의 부모. settings.yaml·edw_chain.yaml·output/이 바로 아래

settings_export() {   # settings_export <env|sh> [<절>...] — 줄을 표준 출력에(절이 없으면 호스트 칸 전부), 실패면 0 아닌 종료 코드(안내는 표준 오류)
  local fmt=$1
  shift
  "${PY:-python3}" "$_SETTINGS_ROOT/deploy/host/scripts/settings_to_env.py" --format "$fmt" "$@"
}

load_settings() {   # 위 설명(source) — 성공 0 · 설정 파일 없음·틀림 2
  export RAG_ROOT
  if [ -z "${SETTINGS_FILE:-}" ]; then
    if [ -f "$RAG_ROOT/settings.yaml" ]; then
      SETTINGS_FILE=$RAG_ROOT/settings.yaml
    elif [ "${RUN_ENV:-}" = local ] && [ -f "$_SETTINGS_ROOT/settings.yaml" ]; then
      SETTINGS_FILE=$_SETTINGS_ROOT/settings.yaml        # PC(저장소 루트)
    fi
  fi
  if [ -z "${SETTINGS_FILE:-}" ] || [ ! -f "$SETTINGS_FILE" ]; then
    echo "[설정] 설정 파일 없음: ${SETTINGS_FILE:-$RAG_ROOT/settings.yaml} — 루트(코드 폴더의 부모)에 settings.yaml을 둘 것(docs/operations/env-guide.md)" >&2
    return 2
  fi
  case "$SETTINGS_FILE" in /*) ;; *) SETTINGS_FILE=$PWD/$SETTINGS_FILE ;; esac
  export SETTINGS_FILE
  if [ "${SETTINGS_LOADED:-}" != "$SETTINGS_FILE" ]; then   # 같으면 이 셸(또는 부른 부모 스크립트)이 같은 파일로 이미 냄
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
  fi
  DOCKER=${DOCKER:-$(docker_default)}; export DOCKER   # op-10 — 셸 env > settings.yaml(ops.host.docker) > podman(없으면 docker)
  RAG_OUT=${RAG_OUT:-$RAG_ROOT/output}; export RAG_OUT   # op-13 — 적지 않으면 <루트>/output
  case "${INSTANCE:-}" in -*|*[!a-z0-9-]*) echo "[설정] ops.host.instance는 영소문자·숫자·-만(앞은 글자·숫자)" >&2; return 2 ;; esac
  NAME_SUFFIX=${INSTANCE:+-$INSTANCE}; export NAME_SUFFIX   # 여러 벌 — 컨테이너·compose 묶음·타이머 이름 끝(비우면 한 벌, 이름 그대로)
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
  [ ${#sections[@]} -gt 0 ] || { echo "[load_settings] 절 이름이 필요함(예: pipeline.host)" >&2; exit 2; }
  settings_export "$fmt" "${sections[@]}"
fi
