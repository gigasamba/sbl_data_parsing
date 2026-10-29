#!/bin/bash
# 이미지 타깃 → 서버 이미지 이름 대응 · 앱 버전(app_version — 아래)(S6c — C-30 ⑤, 사용자 10-27): build_ship.sh·ship_stage.sh가 source한다(전에는 두 파일에 같은 함수가 따로 있었음).
#   S6b(D-020·D-026) — pipeline → data-pipeline(옛 data-parsing+data-structure) · mcp → mcp-server(옛 data-retrieval).
#   모르는 타깃은 빈 출력 — 타깃 검사는 부르는 쪽이 먼저 한다.
image_name_of() {
  case "$1" in
    pipeline) echo data-pipeline ;; mcp) echo mcp-server ;;
  esac
}

# 앱 버전(D-036, 사용자 10-29) — 두 이미지(data-pipeline·mcp-server)가 함께 쓰는 SemVer. 저장소 루트 VERSION 한 줄(MAJOR.MINOR.PATCH)을
#   이미지 태그(<이미지>:<버전>)·이미지 라벨·버전 표기(common.pipeline_version)가 같이 쓴다. 저장소 루트에서 부른다.
app_version() {
  local v
  v=$(tr -d ' \t\r\n' 2>/dev/null < VERSION) || v=
  if printf '%s\n' "$v" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "$v"
  else
    echo "[오류] 저장소 루트 VERSION이 없거나 MAJOR.MINOR.PATCH 꼴이 아님(D-036)" >&2
    return 2
  fi
}
