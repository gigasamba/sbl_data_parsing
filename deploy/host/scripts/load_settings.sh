#!/bin/bash
# settings.yaml → 셸 env 다리. 비밀 칸은 내보내지 않는다(컨테이너 안 앱이 붙인 설정 파일에서 읽음).
#   source: . deploy/host/scripts/load_settings.sh && load_settings || exit $?   — nightly_batch.sh·pipe_exec.sh·mcp_keepalive.sh·host_ctl.sh·prune_images.sh가 씀
#     루트: 코드 폴더(deploy/가 든 폴더)의 부모 — 스크립트 자리에서 구한다(고정 경로 없음 — 셸에 RAG_ROOT를 주면 그 값:
#       사람·host_ctl.sh의 시험 루트 DC_ROOT). RAG_ROOT로 export(compose 마운트 원본).
#     설정 파일: SETTINGS_FILE(있으면) > <루트>/settings.yaml > (RUN_ENV=local) 저장소 루트 settings.yaml
#     앞선 load_settings가 스스로 구해 export한 루트·설정 파일·설정 값은 물려받지 않고 이 코드 폴더에서 다시 구한다
#       (다른 루트에서 source한 셸로 이 루트의 스크립트를 불러도 이 루트 값 — 같은 파일이면 다시 읽지 않음).
#     결과 폴더 RAG_OUT: settings.yaml ops.host.output_dir(적었을 때) > <루트>/output
#     없으면 종료 코드 2
#     호스트 칸(host_settings.tsv 전부 — deploy/release/gen_host_keys.py HOST_SECTIONS: 이미지·자원·포트·호스트 경로·RUN_ENV, compose healthcheck·mcp_keepalive.sh가 쓰는 앱 칸 MCP_HOST·MCP_PORT)을
#     export한다. 이미 셸 env에 있는 이름은 덮지 않는다(셸 env가 이김 — 단 INSTANCE는 settings.yaml에서만).
#     컨테이너는 이 값을 env로 받지 않는다(앱이 붙인 settings.yaml에서 직접 읽음).
#     YAML에 없는 칸은 내지 않으므로 compose 파일 기본값(${X:-…})이 그대로 걸린다. SETTINGS_FILE은 절대 경로로 export(compose 마운트 원본).
#   실행: bash deploy/host/scripts/load_settings.sh [--sh] <절>...     예: pipeline.host  common.host  mcp.host
#     기본: compose --env-file용 KEY=값 줄(값에 $가 있으면 거부) · --sh: `export KEY='값'` 줄
# 호스트 python(python3 — 다르면 PY=<경로>)에 PyYAML만 있으면 된다: deploy/host/scripts/settings_to_env.py가 host_settings.tsv(설정 모델에서 자동 생성 —
# `PYTHONPATH=. python deploy/release/gen_host_keys.py`)와 common/config/layout.py로 읽는다.
# DOCKER로 docker·podman을 고른다(`DOCKER="sudo podman"`처럼 두 낱말도 — 따옴표 없이 펼침). 값은 출력하지 않는다(source 쪽 — 실행 쪽은 요청한 줄만 표준 출력에).
#   셸 env와 settings.yaml(ops.host.container_cli)에 없으면 podman(서버 기본 컨테이너 도구), podman이 없으면 docker(docker_default).
docker_default() { command -v podman >/dev/null 2>&1 && echo podman || echo docker; }   # 서버(RHEL) 기본 podman, 없으면 docker(bake_prod_image.sh·stage_images.sh도 이 함수를 씀)
_SETTINGS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)   # 코드 폴더(deploy/host가 바로 아래 — 서버 sbl_data_parsing-<판> · PC 저장소 루트)
# 서버 루트 — 코드 폴더의 부모(settings.yaml·edw_chain.yaml·output/이 바로 아래). 앞선 load_settings가 구한 값이면 다시 구함
if [ -z "${RAG_ROOT:-}" ] || [ "$RAG_ROOT" = "${_SETTINGS_AUTO_ROOT:-}" ]; then
  RAG_ROOT=$(dirname "$_SETTINGS_ROOT"); _SETTINGS_AUTO_ROOT=$RAG_ROOT
fi

settings_export() {   # settings_export <env|sh> [<절>...] — 줄을 표준 출력에(절이 없으면 호스트 칸 전부), 실패면 0 아닌 종료 코드(안내는 표준 오류)
  local fmt=$1
  shift
  "${PY:-python3}" "$_SETTINGS_ROOT/deploy/host/scripts/settings_to_env.py" --format "$fmt" "$@"
}

load_settings() {   # 위 설명(source) — 성공 0 · 설정 파일 없음·틀림 2
  export RAG_ROOT _SETTINGS_AUTO_ROOT
  local auto=
  if [ -z "${SETTINGS_FILE:-}" ] || [ "$SETTINGS_FILE" = "${_SETTINGS_AUTO_FILE:-}" ]; then   # 앞선 load_settings가 구한 값이면 이 루트에서 다시
    auto=1 SETTINGS_FILE=
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
  [ -n "$auto" ] && _SETTINGS_AUTO_FILE=$SETTINGS_FILE
  export SETTINGS_FILE _SETTINGS_AUTO_FILE
  if [ "${SETTINGS_LOADED:-}" != "$SETTINGS_FILE" ]; then   # 같으면 이 셸(또는 부른 부모 스크립트)이 같은 파일로 이미 냄
    local out line name
    out=$(settings_export sh) || { echo "[설정] 설정 파일에서 호스트 값을 읽지 못함($SETTINGS_FILE) — 위 안내 확인" >&2; return 2; }
    # 벌 이름은 settings.yaml 하나에서(run_pipeline.py와 같게) · 앞선 load_settings가 다른 파일에서 낸 값도 지움(셸 env는 사람이 준 값만 이김)
    # shellcheck disable=SC2086 — 이름 목록 낱말 나눔
    unset INSTANCE ${_SETTINGS_KEYS:-}
    _SETTINGS_KEYS=
    while IFS= read -r line; do
      case "$line" in "export "*=*) ;; *) continue ;; esac
      name=${line#export }; name=${name%%=*}
      case "$name" in ''|*[!A-Za-z0-9_]*) continue ;; esac
      eval "[ -n \"\${$name+x}\" ]" && continue          # 셸 env에 이미 있으면 그 값(사람이 한 번만 덮어 부를 때)
      eval "$line"
      _SETTINGS_KEYS="$_SETTINGS_KEYS $name"
    done <<EOF
$out
EOF
    export SETTINGS_LOADED=$SETTINGS_FILE   # 내부 신호 — 하위 스크립트가 같은 파일을 다시 읽지 않게
  fi
  # 기본값도 이 load_settings가 낸 이름으로 적음(다른 루트에서 다시 읽을 때 지움)
  [ -n "${DOCKER:-}" ] || { DOCKER=$(docker_default); _SETTINGS_KEYS="${_SETTINGS_KEYS:-} DOCKER"; }   # 셸 env > ops.host.container_cli > podman(없으면 docker)
  [ -n "${RAG_OUT:-}" ] || { RAG_OUT=$RAG_ROOT/output; _SETTINGS_KEYS="${_SETTINGS_KEYS:-} RAG_OUT"; }   # 적지 않으면 <루트>/output
  export DOCKER RAG_OUT _SETTINGS_KEYS   # _SETTINGS_KEYS — 내부 신호: 이 load_settings가 낸 이름
  case "${INSTANCE:-}" in -*|*[!a-z0-9-]*) echo "[설정] ops.host.instance_name는 영소문자·숫자·-만(앞은 글자·숫자)" >&2; return 2 ;; esac
  if [ -n "${INSTANCE:-}" ]; then   # 여러 벌 — 운영(prd)은 한 벌, 포트는 벌마다 달라야 함
    [ "${RUN_ENV:-}" = prd ] && { echo "[설정] ops.host.instance_name는 개발 서버(dev)에서만 — 운영(prd)은 한 벌" >&2; return 2; }
    local d   # 코드 기본 포트 — host_settings.tsv의 default.* 줄(gen_host_keys.py가 설정 모델에서 만듦)
    d=$(awk -F'\t' '$1=="default.mcp.server.port"{print $4}' "$_SETTINGS_ROOT/deploy/host/scripts/host_settings.tsv")
    [ "${MCP_PORT:-$d}" = "$d" ] && { echo "[설정] 여러 벌 — search.server.port가 기본값($d) 그대로: 벌마다 다른 포트를 적음" >&2; return 2; }
    d=$(awk -F'\t' '$1=="default.common.runtime.data_parsing_port"{print $4}' "$_SETTINGS_ROOT/deploy/host/scripts/host_settings.tsv")
    [ "${DATA_PARSING_PORT:-$d}" = "$d" ] && { echo "[설정] 여러 벌 — ops.services.data_parsing.port가 기본값($d) 그대로: 벌마다 다른 포트를 적음" >&2; return 2; }
  fi
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
