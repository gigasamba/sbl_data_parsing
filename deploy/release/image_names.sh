#!/bin/bash
# 이미지 타깃 → 서버 이미지 이름 대응(S6c — C-30 ⑤, 사용자 10-27): build_ship.sh·ship_stage.sh가 source한다(전에는 두 파일에 같은 함수가 따로 있었음).
#   S6b(D-020·D-026) — pipeline → data-pipeline(옛 data-parsing+data-structure) · mcp → mcp-server(옛 data-retrieval).
#   모르는 타깃은 빈 출력 — 타깃 검사는 부르는 쪽이 먼저 한다.
image_name_of() {
  case "$1" in
    pipeline) echo data-pipeline ;; mcp) echo mcp-server ;;
  esac
}
