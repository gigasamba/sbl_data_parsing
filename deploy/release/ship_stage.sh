#!/bin/bash
# 서버 이미지(S6b D-020 — 2개: pipeline·mcp) — 로컬 스테이징만(push 안 함·저장소 생성 안 함 — 사람 승인 뒤 수동 push, release-20261016.md §1-2).
#   bash deploy/release/ship_stage.sh [태그 — 기본 저장소 루트 VERSION(D-036), 예: 0.1.0] [대상들… 기본 pipeline mcp]
#   실행 이미지(op-06): 대상 pipeline-runtime·mcp-runtime + CODE_BUNDLE=output/ship/code-<버전>-<커밋>.tar.gz(태그 폴더에 같이 놓음)
# 전제: 이미지가 이미 로컬에 빌드돼 있어야 함(release-20261016.md §1-1) — 이 스크립트는 빌드하지 않는다.
# 이미지를 저장(docker save) → gzip → CHUNK(기본 95m, GitHub 100 MB 상한 — image-patch-process.md §4-1 관례) 조각 →
#   sha256 체크섬 → output/ship/<repo>/images/<태그>/<이미지 이름>/ 에 쌓는다. 사용자 10-14: 이미지 단위로 저장소를
#   쪼개지 않고 기존 개인 이미지 저장소 하나(mono repo — jehunlee302/data_parsing_split)에 이미지별 폴더로:
#     data-pipeline/ · mcp-server/   (S6b — 옛 data-parsing/·data-structure/는 합침, data-retrieval/는 이름 바뀜)
# 서버 쪽 재조립: cat <이름>.tar.gz.part* > <이름>.tar.gz && sha256sum -c <이름>.sha256 && gunzip -c <이름>.tar.gz | docker load
set -euo pipefail
cd "$(dirname "$0")/../.."                                # deploy/release/ → 저장소 루트(S6b)
. deploy/release/image_names.sh   # image_name_of·app_version — 타깃 → 이미지 이름(S6c, build_ship.sh와 같은 파일) — 대상은 repo_of()가 이미 걸러냄
case "${1:-}" in
  ""|pipeline|mcp|pipeline-runtime|mcp-runtime) TAG=$(app_version) || exit 2 ;;   # 태그를 안 주면 VERSION(두 이미지 같은 버전 태그)
  *) TAG="$1"; shift ;;
esac
if [ "$#" -gt 0 ]; then TARGETS=("$@"); else TARGETS=(pipeline mcp); fi
OUT="${OUT:-output/ship}"
CHUNK="${CHUNK:-95m}"
DOCKER="${DOCKER:-docker}"

repo_of() {    # 사용자 10-14: 이미지 저장소는 하나(mono repo) — 대상 검사만 하고 같은 저장소 이름을 돌려준다
  case "$1" in
    pipeline|mcp|pipeline-runtime|mcp-runtime) echo "${SHIP_REPO:-data_parsing_split}" ;;   # op-06 — 실행 이미지도
    *) return 1 ;;
  esac
}


stage_one() {
  local target="$1" tag repo dir n
  repo=$(repo_of "$target") || { echo "[ship_stage] 모르는 대상: $target (pipeline·mcp·pipeline-runtime·mcp-runtime만 — 옛 parse·structure는 S6b에 pipeline으로 합침, retrieval은 mcp로)"; return 2; }
  tag="$(image_name_of "$target"):$TAG"
  if ! $DOCKER image inspect "$tag" >/dev/null 2>&1; then
    echo "[ship_stage] 이미지 없음: $tag — 먼저 빌드(release-20261016.md §1-1), 건너뜀"
    return 1
  fi
  dir="$OUT/$repo/images/$TAG/$(image_name_of "$target")"
  mkdir -p "$dir"
  rm -f "$dir/$target.tar.gz.part"* "$dir/$target.sha256"   # 재실행 시 옛 조각 수와 안 섞이게
  echo "[ship_stage] $tag 저장·분할 → $dir"
  $DOCKER save "$tag" | gzip -1 | split -b "$CHUNK" -d -a 3 - "$dir/$target.tar.gz.part"
  ( cd "$dir" && sha256sum "$target".tar.gz.part* > "$target.sha256" )
  n=$(ls "$dir/$target".tar.gz.part* | wc -l)
  echo "[ship_stage] $target → $repo: 조각 ${n}개 · 합계 $(du -ch "$dir/$target".tar.gz.part* 2>/dev/null | tail -1 | cut -f1)"
}

ok=0; fail=0
if [ -n "${CODE_BUNDLE:-}" ]; then   # op-06 — 실행 이미지와 함께 보낼 코드 폴더 묶음(build_ship.sh가 만든 code-<버전>-<커밋>.tar.gz)
  d="$OUT/$(repo_of pipeline)/images/$TAG"; mkdir -p "$d"
  cp "$CODE_BUNDLE" "$d/" && ( cd "$d" && sha256sum "$(basename "$CODE_BUNDLE")" > "$(basename "$CODE_BUNDLE").sha256" )
  echo "[ship_stage] 코드 폴더 묶음 → $d/$(basename "$CODE_BUNDLE")"
fi
for t in "${TARGETS[@]}"; do
  if stage_one "$t"; then ok=$((ok + 1)); else fail=$((fail + 1)); fi
done
echo "[ship_stage] 끝 — 완료 $ok · 건너뜀/실패 $fail · $OUT/<repo>/images/$TAG/<이미지>/ 확인 뒤 사람이 push(저장소 생성·push는 이 스크립트가 안 함)"
[ "$fail" -eq 0 ]
