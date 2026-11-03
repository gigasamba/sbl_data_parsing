#!/bin/bash
# 서버 이미지(S6b D-020 — 2개: pipeline·mcp) — 로컬 스테이징만(push 안 함·저장소 생성 안 함 — 사람 승인 뒤 수동 push, docs/operations/release-and-patch.md §1-1·§1-2).
#   bash deploy/release/ship_stage.sh [태그 — 기본 저장소 루트 VERSION(D-036), 예: 0.1.0] [대상들… 기본 pipeline mcp]
#   개발 서버(op-06): 대상 pipeline-runtime·mcp-runtime(코드 없는 실행 이미지 — 코드는 코드 저장소 zip, README §5-0)
#   운영 서버(op-07): bake.sh가 pipeline·mcp + CODE_BUNDLE(시험한 코드 폴더 묶음 — 호스트 스크립트용, 판 폴더에 같이 놓음)
# 전제: 이미지가 이미 로컬에 있어야 함(build_ship.sh·bake.sh) — 이 스크립트는 빌드하지 않는다.
# 이미지 저장소 배치 하나(op-10, README §5-0 — 이미지 git `sbl_images`):
#   $OUT/<저장소>/load.sh                                   ← deploy/release/load.sh 사본(조각 확인 → 합치기 → docker/podman load)
#   $OUT/<저장소>/<판>/BUILD.txt                             ← 판·빌드 커밋·DEPS_HASH·이미지 태그
#   $OUT/<저장소>/<판>/<이미지 이름>/<이미지 이름>.tar.gz.part000… · <이미지 이름>.sha256
#   저장소 이름 SHIP_REPO(기본 sbl_images) · 조각 CHUNK(기본 45m — GitHub 100MB 상한 아래, 저장소 관례) · 서버에서: bash <저장소>/load.sh <판>
set -euo pipefail
cd "$(dirname "$0")/../.."                                # deploy/release/ → 저장소 루트(S6b)
. deploy/release/image_names.sh   # image_name_of·app_version — 타깃 → 이미지 이름(S6c, build_ship.sh와 같은 파일) — 대상은 repo_of()가 이미 걸러냄
case "${1:-}" in
  ""|pipeline|mcp|pipeline-runtime|mcp-runtime) TAG=$(app_version) || exit 2 ;;   # 태그를 안 주면 VERSION(두 이미지 같은 버전 태그)
  *) TAG="$1"; shift ;;
esac
if [ "$#" -gt 0 ]; then TARGETS=("$@"); else TARGETS=(pipeline mcp); fi
OUT="${OUT:-output/ship}"
CHUNK="${CHUNK:-45m}"
DOCKER="${DOCKER:-$(command -v podman >/dev/null 2>&1 && echo podman || echo docker)}"   # op-10 — podman 우선(bake.sh와 같음)
REPO="${SHIP_REPO:-sbl_images}"

repo_of() {    # 대상 검사만 — 이미지 저장소는 하나(사용자 10-14 mono repo)
  case "$1" in
    pipeline|mcp|pipeline-runtime|mcp-runtime) echo "$REPO" ;;   # op-06 — 실행 이미지도
    *) return 1 ;;
  esac
}


stage_one() {
  local target="$1" tag name dir n
  repo_of "$target" >/dev/null || { echo "[ship_stage] 모르는 대상: $target (pipeline·mcp·pipeline-runtime·mcp-runtime만)"; return 2; }
  name=$(image_name_of "$target")
  tag="$name:$TAG"
  if ! $DOCKER image inspect "$tag" >/dev/null 2>&1; then
    echo "[ship_stage] 이미지 없음: $tag — 먼저 빌드(build_ship.sh·bake.sh), 건너뜀"
    return 1
  fi
  dir="$OUT/$REPO/$TAG/$name"
  mkdir -p "$dir"
  rm -f "$dir/$name.tar.gz.part"* "$dir/$name.sha256"   # 재실행 시 옛 조각 수와 안 섞이게
  echo "[ship_stage] $tag 저장·분할 → $dir"
  # `if stage_one`에서는 set -e가 꺼짐 — 저장 실패(디스크 부족 등)를 직접 실패로(잘린 조각에 sha256을 만들지 않게)
  $DOCKER save "$tag" | gzip -1 | split -b "$CHUNK" -d -a 3 - "$dir/$name.tar.gz.part" \
    || { echo "[ship_stage] 저장 실패: $tag"; rm -f "$dir/$name.tar.gz.part"*; return 1; }
  ( cd "$dir" && sha256sum "$name".tar.gz.part* > "$name.sha256" ) \
    || { echo "[ship_stage] sha256 실패: $dir"; rm -f "$dir/$name.sha256"; return 1; }
  n=$(ls "$dir/$name".tar.gz.part* | wc -l)
  echo "[ship_stage] $name → $REPO/$TAG: 조각 ${n}개 · 합계 $(du -ch "$dir/$name".tar.gz.part* 2>/dev/null | tail -1 | cut -f1)"
}

mkdir -p "$OUT/$REPO/$TAG"
cp deploy/release/load.sh "$OUT/$REPO/load.sh" || { echo "[ship_stage] load.sh 복사 실패"; exit 1; }
ok=0; fail=0
if [ -n "${CODE_BUNDLE:-}" ]; then   # op-07 — 운영 반입 때 시험한 코드 폴더 묶음(호스트 스크립트용)도 판 폴더에
  d="$OUT/$REPO/$TAG"
  b=$(basename "$CODE_BUNDLE")
  { cp "$CODE_BUNDLE" "$d/" && ( cd "$d" && sha256sum "$b" > "$b.sha256" ); } \
    || { echo "[ship_stage] 코드 폴더 묶음 복사·sha256 실패: $d/$b"; rm -f "$d/$b" "$d/$b.sha256"; exit 1; }
  echo "[ship_stage] 코드 폴더 묶음 → $d/$b"
fi
for t in "${TARGETS[@]}"; do
  if stage_one "$t"; then ok=$((ok + 1)); else fail=$((fail + 1)); fi
done
# 빌드 커밋 — 서버 zip(GitHub archive·git archive)은 CODE_COMMIT이 채워져 있고, clone은 틀($Format…) 그대로라 git으로(bake.sh와 같음)
commit=$(cut -d' ' -f1 CODE_COMMIT 2>/dev/null); case "$commit" in ''|'$Format'*) commit=$(git rev-parse HEAD 2>/dev/null || echo unknown) ;; esac
{
  echo "판: $TAG"
  echo "빌드 커밋: $commit"
  echo "DEPS_HASH: $(tr -d '\r\n' < deploy/docker/DEPS_HASH 2>/dev/null || echo unknown)"
  printf '이미지:'; for d in "$OUT/$REPO/$TAG"/*/; do d=${d%/}; d=${d##*/}; [ -f "$OUT/$REPO/$TAG/$d/$d.sha256" ] && printf ' %s' "$d:$TAG"; done; echo   # 판 폴더에 있는 것 전부(bake는 대상마다 부름)
  echo "만든 날: $(date +%F)"
} > "$OUT/$REPO/$TAG/BUILD.txt"
echo "[ship_stage] 끝 — 완료 $ok · 건너뜀/실패 $fail · $OUT/$REPO/(load.sh · $TAG/BUILD.txt · $TAG/<이미지>/) 확인 뒤 사람이 push(저장소 생성·push는 이 스크립트가 안 함)"
[ "$fail" -eq 0 ]
