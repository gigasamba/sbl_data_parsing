#!/bin/bash
# 서버 이미지(2개: pipeline·mcp) — 로컬 스테이징만(push 안 함·저장소 생성 안 함 — 사람 승인 뒤 수동 push, docs/operations/server-guide.md §4-5·§5-3).
#   bash deploy/release/stage_images.sh [태그 — 기본 저장소 루트 VERSION, 예: 0.1.0] [대상들… 기본 pipeline mcp; Redis는 redis 대상 추가]
#   개발 서버: 대상 pipeline-runtime·mcp-runtime(코드 없는 실행 이미지 — 코드는 코드 저장소 zip, server-guide §1-1)
#   운영 서버: bake_prod_image.sh가 pipeline·mcp + CODE_BUNDLE(시험한 코드 폴더 묶음 — 호스트 스크립트용, 판 폴더에 같이 놓음)
# 전제: 이미지가 이미 로컬에 있어야 함(build_ship.sh·bake_prod_image.sh) — 이 스크립트는 빌드하지 않는다.
# 이미지 저장소 배치 하나(server-guide §1-1 — 이미지 git `sbl_images`):
#   $OUT/<저장소>/load.sh                                   ← deploy/release/load.sh 사본(조각 확인 → 합치기 → docker/podman load)
#   $OUT/<저장소>/<판>/BUILD.txt                             ← 판·빌드 커밋·DEPS_HASH·이미지 태그
#   $OUT/<저장소>/<판>/<이미지 이름>/<이미지 이름>.tar.gz.part000… · <이미지 이름>.sha256
#   저장소 이름 SHIP_REPO(기본 sbl_images) · 조각 CHUNK(기본 45m — GitHub 100MB 상한 아래, 저장소 관례) · 서버에서: bash <저장소>/load.sh <판>
set -euo pipefail
cd "$(dirname "$0")/../.."                                # deploy/release/ → 저장소 루트
. deploy/release/image_names.sh   # image_name_of·app_version — 타깃 → 이미지 이름(build_ship.sh와 같은 파일) — 대상은 repo_of()가 이미 걸러냄
case "${1:-}" in
  ""|pipeline|mcp|pipeline-runtime|mcp-runtime|redis) TAG=$(app_version) || exit 2 ;;   # 태그를 안 주면 VERSION(두 이미지 같은 버전 태그)
  *) TAG="$1"; shift ;;
esac
if [ "$#" -gt 0 ]; then TARGETS=("$@"); else TARGETS=(pipeline mcp); fi
OUT="${OUT:-output/ship}"
CHUNK="${CHUNK:-45m}"
. deploy/host/scripts/load_settings.sh   # docker_default 한 곳(docker 우선, bake_prod_image.sh와 같음)
DOCKER="${DOCKER:-$(docker_default)}"
REPO="${SHIP_REPO:-sbl_images}"

repo_of() {    # 대상 검사만 — 이미지 저장소는 하나(mono repo)
  case "$1" in
    pipeline|mcp|pipeline-runtime|mcp-runtime|redis) echo "$REPO" ;;   # 실행 이미지도
    *) return 1 ;;
  esac
}


stage_one() {
  local target="$1" tag name dir n
  repo_of "$target" >/dev/null || { echo "[stage_images] 모르는 대상: $target (pipeline·mcp·pipeline-runtime·mcp-runtime·redis)"; return 2; }
  if [ "$target" = redis ]; then
    # 앱 판과 Redis 판은 별개. 호스트 설정 표로 이미지 칸만 읽음(비밀값 없음), 기본값도 설정 모델 한 곳.
    local value
    if [ -z "${REDIS_IMAGE:-}" ]; then
      load_settings || return 2
      value=$(settings_export sh common.host.redis_image) || return 2
      [ -z "$value" ] || eval "$value"
    fi
    tag=${REDIS_IMAGE:-redis:7.4.2-alpine}
    name=mcp-redis
  else
    name=$(image_name_of "$target")
    tag="$name:$TAG"
  fi
  if ! $DOCKER image inspect "$tag" >/dev/null 2>&1; then
    echo "[stage_images] 이미지 없음: $tag — 먼저 빌드(build_ship.sh·bake_prod_image.sh), 건너뜀"
    return 1
  fi
  dir="$OUT/$REPO/$TAG/$name"
  mkdir -p "$dir"
  rm -f "$dir/$name.tar.gz.part"* "$dir/$name.sha256"   # 재실행 시 이전 조각과 안 섞이게
  printf '%s\n' "$tag" > "$dir/image.txt"
  echo "[stage_images] $tag 저장·분할 → $dir"
  # `if stage_one`에서는 set -e가 꺼짐 — 저장 실패(디스크 부족 등)를 직접 실패로(잘린 조각에 sha256을 만들지 않게)
  $DOCKER save "$tag" | gzip -1 | split -b "$CHUNK" -d -a 3 - "$dir/$name.tar.gz.part" \
    || { echo "[stage_images] 저장 실패: $tag"; rm -f "$dir/$name.tar.gz.part"*; return 1; }
  ( cd "$dir" && sha256sum "$name".tar.gz.part* > "$name.sha256" ) \
    || { echo "[stage_images] sha256 실패: $dir"; rm -f "$dir/$name.sha256"; return 1; }
  n=$(ls "$dir/$name".tar.gz.part* | wc -l)
  echo "[stage_images] $name → $REPO/$TAG: 조각 ${n}개 · 합계 $(du -ch "$dir/$name".tar.gz.part* 2>/dev/null | tail -1 | cut -f1)"
}

mkdir -p "$OUT/$REPO/$TAG"
cp deploy/release/load.sh "$OUT/$REPO/load.sh" || { echo "[stage_images] load.sh 복사 실패"; exit 1; }
ok=0; fail=0
if [ -n "${CODE_BUNDLE:-}" ]; then   # 운영 반입 때 시험한 코드 폴더 묶음(호스트 스크립트용)도 판 폴더에
  d="$OUT/$REPO/$TAG"
  b=$(basename "$CODE_BUNDLE")
  { cp "$CODE_BUNDLE" "$d/" && ( cd "$d" && sha256sum "$b" > "$b.sha256" ); } \
    || { echo "[stage_images] 코드 폴더 묶음 복사·sha256 실패: $d/$b"; rm -f "$d/$b" "$d/$b.sha256"; exit 1; }
  echo "[stage_images] 코드 폴더 묶음 → $d/$b"
fi
for t in "${TARGETS[@]}"; do
  if stage_one "$t"; then ok=$((ok + 1)); else fail=$((fail + 1)); fi
done
# 빌드 커밋 — 서버 zip(GitHub archive·git archive)은 CODE_COMMIT이 채워져 있고, clone은 틀($Format…) 그대로라 git으로(bake_prod_image.sh와 같음)
commit=$(cut -d' ' -f1 CODE_COMMIT 2>/dev/null); case "$commit" in ''|'$Format'*) commit=$(git rev-parse HEAD 2>/dev/null || echo unknown) ;; esac
{
  echo "판: $TAG"
  echo "빌드 커밋: $commit"
  echo "DEPS_HASH: $(tr -d '\r\n' < deploy/docker/DEPS_HASH 2>/dev/null || echo unknown)"
  printf '이미지:'; for d in "$OUT/$REPO/$TAG"/*/; do d=${d%/}; d=${d##*/}; [ -f "$OUT/$REPO/$TAG/$d/$d.sha256" ] && printf ' %s' "$(cat "$OUT/$REPO/$TAG/$d/image.txt" 2>/dev/null || echo "$d:$TAG")"; done; echo   # 판 폴더에 있는 것 전부(bake는 대상마다 부름)
  echo "만든 날: $(date +%F)"
} > "$OUT/$REPO/$TAG/BUILD.txt"
echo "[stage_images] 끝 — 완료 $ok · 건너뜀/실패 $fail · $OUT/$REPO/(load.sh · $TAG/BUILD.txt · $TAG/<이미지>/) 확인 뒤 사람이 push(저장소 생성·push는 이 스크립트가 안 함)"
[ "$fail" -eq 0 ]
