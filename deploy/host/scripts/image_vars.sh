#!/bin/bash
# 이미지 변수 확인(S6b, D-020 — trigger.sh·run_tool.sh·mcp_up.sh가 source). 서버 이미지 2개(사용자 10-27):
#   DATA_PIPELINE_IMAGE = data-pipeline:<태그>(옛 data-parsing+data-structure) · MCP_SERVER_IMAGE = mcp-server:<태그>(옛 data-retrieval)
# 옛 이름 DATA_PARSING_IMAGE·DATA_STRUCTURE_IMAGE·DATA_RETRIEVAL_IMAGE·RAG_PARSE_IMAGE·RAG_STRUCTURE_IMAGE·RAG_RETRIEVAL_IMAGE·RAG_IMAGE는
#   별칭으로 읽지 않는다 — 새 이름이 셸 env에 없는데 옛 이름만 있으면 안내를 찍고 2를 돌려준다(코디네이터 답 Q2 a — 부르는 쪽이 `|| exit 2`).
#   둘 다 없으면 0(compose가 `${…:?}` 필수 안내로 멈춤). 값은 출력하지 않는다.
#   S7e1 — 새 이름은 settings.yaml(pipeline.host.image·mcp.host.image)에서 settings_env.sh load_settings가 셸 env로 낸다. 부르기 전에 load_settings.
#   (옛 env 파일(ENV_FILE=pipeline.env)은 더 읽지 않는다 — 옛 이름은 settings.yaml 칸이 아니라 migrate가 "삭제 후보"로만 보고함)
#   need_image pipeline   — 파이프라인 이미지(compose.pipeline.yml의 parse~publish·상주 트리거)
#   need_image mcp        — 검색 MCP 이미지(compose.mcp.yml·compose.pipeline.yml의 mcp·retrieval 서비스)
_set_somewhere() {   # _set_somewhere <이름들> — 셸 env에 값이 있으면 0
  local n
  for n in $1; do [ -n "${!n:-}" ] && return 0; done
  return 1
}
# op-06(사용자 10-30) — 실행 이미지(*-runtime:태그)인데 CODE_DIR가 비면 이 코드 폴더 루트(부른 스크립트가 cd한 곳 —
#   git zip을 푼 폴더 그대로)를 코드 폴더로 쓴다. 이미 CODE_DIR가 있으면 그 값(옛 live 링크 배치). 코드가 든 이미지는 손대지 않음.
code_dir_default() {   # code_dir_default <이미지 변수 이름>
  [ -n "${CODE_DIR:-}" ] && return 0
  case "${!1:-}" in *-runtime:*) CODE_DIR=$(pwd); export CODE_DIR ;; esac
  return 0
}
need_image() {
  local new old example
  case "$1" in
    pipeline) new=DATA_PIPELINE_IMAGE; old="DATA_PARSING_IMAGE DATA_STRUCTURE_IMAGE RAG_PARSE_IMAGE RAG_STRUCTURE_IMAGE"; example=data-pipeline ;;
    mcp)      new=MCP_SERVER_IMAGE;    old="DATA_RETRIEVAL_IMAGE RAG_RETRIEVAL_IMAGE RAG_IMAGE"; example=mcp-server ;;
    *) echo "[image_vars] need_image pipeline|mcp" >&2; return 2 ;;
  esac
  _set_somewhere "$new" && return 0
  if _set_somewhere "$old"; then
    echo "[오류] 새 이미지 판 필요 — 서버 이미지 이름이 바뀌었다(S6b): settings.yaml $1.host.image에 $example:<태그>를 적고(env $new) 옛 이름(${old// /·})은 셸 env에서 지운다" \
         "(옛 태그는 옛 이미지라 별칭으로 읽지 않음 — docs/operations/release-and-patch.md §5-2 · refactor.md C-29)" >&2
    return 2
  fi
  return 0
}
