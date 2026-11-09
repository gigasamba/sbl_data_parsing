#!/bin/bash
# settings.yaml → 셸 env 다리. 비밀 칸은 내보내지 않는다(컨테이너 안 앱이 붙인 설정 파일에서 읽음).
#   source: . deploy/host/scripts/load_settings.sh && load_settings || exit $?   — nightly_batch.sh·pipe_exec.sh·mcp_keepalive.sh·host_ctl.sh·prune_images.sh가 씀
#     루트: 코드 폴더(deploy/가 든 폴더) 자체 = 한 벌 — 스크립트 자리에서 구한다(고정 경로 없음 — 셸에 RAG_ROOT를 주면 그 값:
#       사람·host_ctl.sh의 시험 루트 DC_ROOT). RAG_ROOT로 export(compose 마운트 원본). PC는 저장소 루트.
#     벌 번호: 코드 폴더 이름 끝 -<1~99>(예 sbl_data_parsing-main-2 → 2 · -20261106 같은 날짜는 아님) — 컨테이너·compose 묶음·타이머 이름 끝 -<숫자>(NAME_SUFFIX). 없으면 한 벌.
#     설정 파일: SETTINGS_FILE(있으면) > <루트>/settings.yaml
#     앞선 load_settings가 스스로 구해 export한 루트·설정 파일·설정 값은 물려받지 않고 이 코드 폴더에서 다시 구한다
#       (다른 루트에서 source한 셸로 이 루트의 스크립트를 불러도 이 루트 값 — 같은 파일이면 다시 읽지 않음).
#     결과 폴더 RAG_OUT: settings.yaml ops.host.host_output_dir(적었을 때) > <루트>/output
#     없으면 종료 코드 2
#     호스트 칸(host_settings.tsv 전부 — deploy/release/gen_host_keys.py HOST_SECTIONS: 이미지·자원·포트·호스트 경로·RUN_ENV, compose healthcheck·mcp_keepalive.sh가 쓰는 앱 칸 MCP_HOST·MCP_PORT)을
#     export한다. 이미 셸 env에 있는 이름은 덮지 않는다(셸 env가 이김).
#     컨테이너는 이 값을 env로 받지 않는다(앱이 붙인 settings.yaml에서 직접 읽음).
#     YAML에 없는 칸은 내지 않으므로 compose 파일 기본값(${X:-…})이 그대로 걸린다. SETTINGS_FILE은 절대 경로로 export(compose 마운트 원본).
#   실행: bash deploy/host/scripts/load_settings.sh [--sh] <절>...     예: pipeline.host  common.host  mcp.host
#     기본: compose --env-file용 KEY=값 줄(값에 $가 있으면 거부) · --sh: `export KEY='값'` 줄
# 호스트 python(python3 — 다르면 PY=<경로>)에 PyYAML만 있으면 된다: deploy/host/scripts/settings_to_env.py가 host_settings.tsv(설정 모델에서 자동 생성 —
# `PYTHONPATH=. python deploy/release/gen_host_keys.py`)와 common/config/layout.py로 읽는다.
# DOCKER로 docker·podman을 고른다(`DOCKER="sudo docker"`처럼 두 낱말도 — 따옴표 없이 펼침). 값은 출력하지 않는다(source 쪽 — 실행 쪽은 요청한 줄만 표준 출력에).
#   셸 env와 settings.yaml(ops.host.container_cli)에 없으면 docker(서버 기본 컨테이너 도구), docker가 없으면 podman(docker_default).
docker_default() { command -v docker >/dev/null 2>&1 && echo docker || echo podman; }   # 서버 기본 docker(재부팅 때 docker 서비스가 restart: unless-stopped 컨테이너를 다시 띄움), 없으면 podman(bake_prod_image.sh·stage_images.sh도 이 함수를 씀)
_SETTINGS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)   # 코드 폴더(deploy/host가 바로 아래 — 서버 sbl_data_parsing-<판> · PC 저장소 루트)
# 서버 루트 — 코드 폴더 자체(settings.yaml·edw_chain.yaml·output/이 바로 아래). 앞선 load_settings가 구한 값이면 다시 구함
if [ -z "${RAG_ROOT:-}" ] || [ "$RAG_ROOT" = "${_SETTINGS_AUTO_ROOT:-}" ]; then
  RAG_ROOT=$_SETTINGS_ROOT; _SETTINGS_AUTO_ROOT=$RAG_ROOT
fi

_host_default() {   # _host_default <모델 경로> — 코드 기본값(host_settings.tsv의 default.* 줄 — gen_host_keys.py가 설정 모델에서 만듦)
  awk -F'\t' -v k="default.$1" '$1==k{print $4}' "$_SETTINGS_ROOT/deploy/host/scripts/host_settings.tsv" 2>/dev/null
}

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
    [ -f "$RAG_ROOT/settings.yaml" ] && SETTINGS_FILE=$RAG_ROOT/settings.yaml
  fi
  if [ -z "${SETTINGS_FILE:-}" ] || [ ! -f "$SETTINGS_FILE" ]; then
    echo "[설정] 설정 파일 없음: ${SETTINGS_FILE:-$RAG_ROOT/settings.yaml} — 루트(코드 폴더)에 settings.yaml을 둘 것(docs/operations/env-guide.md)" >&2
    return 2
  fi
  case "$SETTINGS_FILE" in /*) ;; *) SETTINGS_FILE=$PWD/$SETTINGS_FILE ;; esac
  [ -n "$auto" ] && _SETTINGS_AUTO_FILE=$SETTINGS_FILE
  export SETTINGS_FILE _SETTINGS_AUTO_FILE
  if [ "${SETTINGS_LOADED:-}" != "$SETTINGS_FILE" ]; then   # 같으면 이 셸(또는 부른 부모 스크립트)이 같은 파일로 이미 냄
    local out line name
    out=$(settings_export sh) || { echo "[설정] 설정 파일에서 호스트 값을 읽지 못함($SETTINGS_FILE) — 위 안내 확인" >&2; return 2; }
    # 앞선 load_settings가 다른 파일에서 낸 값은 지움(셸 env는 사람이 준 값만 이김)
    # shellcheck disable=SC2086 — 이름 목록 낱말 나눔
    unset ${_SETTINGS_KEYS:-}
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
  [ -n "${DOCKER:-}" ] || { DOCKER=$(docker_default); _SETTINGS_KEYS="${_SETTINGS_KEYS:-} DOCKER"; }   # 셸 env > ops.host.container_cli > docker(없으면 podker)
  [ -n "${RAG_OUT:-}" ] || { RAG_OUT=$RAG_ROOT/output; _SETTINGS_KEYS="${_SETTINGS_KEYS:-} RAG_OUT"; }   # 적지 않으면 <루트>/output
  # 호스트 쪽 붙일 원본(compose·host_ctl.sh) — 적지 않으면 <루트> 아래. 상대 경로는 <루트> 기준(compose는 상대 경로를 compose 파일 폴더 기준으로 읽으므로 절대 경로로)
  [ -n "${EDW_CHAIN_SRC:-}" ] || { EDW_CHAIN_SRC=$RAG_ROOT/edw_chain.yaml; _SETTINGS_KEYS="${_SETTINGS_KEYS:-} EDW_CHAIN_SRC"; }   # ops.host.host_edw_chain_file
  [ -n "${DEVBOX_HOME:-}" ] || { DEVBOX_HOME=$RAG_ROOT/home; _SETTINGS_KEYS="${_SETTINGS_KEYS:-} DEVBOX_HOME"; }   # option.devbox.home_dir
  case "$EDW_CHAIN_SRC" in /*) ;; *) EDW_CHAIN_SRC=$RAG_ROOT/$EDW_CHAIN_SRC ;; esac
  case "$DEVBOX_HOME" in /*) ;; *) DEVBOX_HOME=$RAG_ROOT/$DEVBOX_HOME ;; esac
  if [ -n "${EXTRA_COMPOSE:-}" ]; then   # ops.host.extra_compose(쉼표 목록) — 상대 경로는 <루트> 기준 절대 경로로(host_ctl.sh가 -f로 붙임)
    local f fs abs=
    IFS=, read -r -a fs <<< "$EXTRA_COMPOSE"
    for f in ${fs[@]+"${fs[@]}"}; do
      f=${f#"${f%%[! ]*}"}; f=${f%"${f##*[! ]}"}   # 앞뒤 빈칸 — "a.yml, b.yml"(쉼표 뒤 빈칸)도 받음(앱 CsvList와 같게)
      case "$f" in "") continue ;; /*) ;; *) f=$RAG_ROOT/$f ;; esac
      abs="${abs:+$abs,}$f"
    done
    EXTRA_COMPOSE=$abs; export EXTRA_COMPOSE
  fi
  export DOCKER RAG_OUT EDW_CHAIN_SRC DEVBOX_HOME _SETTINGS_KEYS   # _SETTINGS_KEYS — 내부 신호: 이 load_settings가 낸 이름
  INSTANCE=; [[ $(basename "$RAG_ROOT") =~ -([1-9][0-9]?)$ ]] && INSTANCE=${BASH_REMATCH[1]}   # 벌 번호 — 루트(코드 폴더) 이름 끝 -<1~99>(날짜·판 꼴 숫자는 아님 — run_pipeline.py instance_of와 같은 규칙)
  # 여러 벌(개발자별)은 개발 서버만 — 운영(prd)은 한 벌. 개발 벌은 data-pipeline 하나만 띄우므로(검색 MCP 포트를 쓰지 않음) 포트 칸은 보지 않는다
  if [ -n "$INSTANCE" ] && [ "${RUN_ENV:-}" = prd ]; then
    echo "[설정] 코드 폴더 이름 끝 -$INSTANCE(벌 번호)는 개발 서버(dev)에서만 — 운영(prd)은 한 벌(폴더 이름을 바꿀 것)" >&2; return 2
  fi
  NAME_SUFFIX=${INSTANCE:+-$INSTANCE}; export INSTANCE NAME_SUFFIX   # 여러 벌 — 컨테이너·compose 묶음·타이머 이름 끝(비우면 한 벌, 이름 그대로)
  # 컨테이너·compose 묶음 이름(셸·compose는 이 넷만 씀) = 밑 이름(settings.yaml ops.containers.<서비스>.<서비스>_container_name·
  #   ops.host.compose_project > 코드 기본값) + NAME_SUFFIX. 파이썬 쪽은 run_pipeline.py configure()가 같은 규칙.
  PIPELINE_CNAME=${PIPELINE_CONTAINER:-$(_host_default common.host.pipeline_container)}$NAME_SUFFIX
  DATA_PARSING_CNAME=${DATA_PARSING_CONTAINER:-$(_host_default common.host.data_parsing_container)}$NAME_SUFFIX
  MCP_CNAME=${MCP_CONTAINER:-$(_host_default common.host.mcp_container)}$NAME_SUFFIX
  COMPOSE_PNAME=${COMPOSE_PROJECT:-$(_host_default common.host.compose_project)}$NAME_SUFFIX
  export PIPELINE_CNAME DATA_PARSING_CNAME MCP_CNAME COMPOSE_PNAME
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
