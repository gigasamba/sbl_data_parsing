#!/bin/bash
# 개발 → 운영(op-07, 사용자 10-30) — 개발 서버(폐쇄망)에서 실행. 개발 서버에서 쓰던 실행 이미지(*-runtime) 그 판 + 시험한 코드 폴더를
# 그대로 묶어 운영용 이미지(코드가 든 이미지 — 코드 폴더 마운트 없이 뜸)를 만들고, 반입 판정 뒤 저장·분할한다. 패키지 설치·네트워크 없음.
#   bash deploy/release/bake.sh <실행 이미지 태그 판> [대상… 기본 pipeline mcp]
#     예: bash /srv/rag/code/live/deploy/release/bake.sh 0.1.0   → data-pipeline-runtime:0.1.0 + 코드 폴더 → data-pipeline:<VERSION>
#   CODE_DIR  코드 폴더(기본: 이 스크립트가 든 코드 폴더 — /srv/rag/code/live/deploy/release/bake.sh면 /srv/rag/code/live)
#   TAG       새 이미지 태그 판(기본: 코드 폴더 VERSION) · OUT 저장 폴더(기본 ./output/bake) · DOCKER(기본 podman, 없으면 docker)
# 순서(대상마다): ① 코드 DEPS_HASH = 실행 이미지 deps_hash ② Dockerfile.bake 빌드(문맥 = 코드 폴더) ③ selftest_gate [판정] 통과
#   ④ ship_stage.sh로 저장·gzip·분할·sha256 → $OUT/<repo>/images/<TAG>/<이미지>/ (재조립은 ship_stage.sh 머리말)
set -euo pipefail
[ $# -ge 1 ] || { echo "사용: bash bake.sh <실행 이미지 태그 판> [pipeline mcp]" >&2; exit 2; }
RT_VER="$1"; shift
if [ "$#" -gt 0 ]; then TARGETS=("$@"); else TARGETS=(pipeline mcp); fi
OUT="${OUT:-$PWD/output/bake}"; mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)   # ship_stage.sh가 cd하므로 절대 경로로
CODE_DIR=$(cd "${CODE_DIR:-$(dirname "$0")/../..}" && pwd)
DOCKER="${DOCKER:-$(command -v podman >/dev/null 2>&1 && echo podman || echo docker)}"
cd "$CODE_DIR"
. deploy/release/image_names.sh
TAG="${TAG:-$(app_version)}"
want=$(tr -d '\r\n' < deploy/docker/DEPS_HASH)
commit=$(cut -d' ' -f1 CODE_COMMIT 2>/dev/null || git rev-parse HEAD 2>/dev/null || echo unknown)

for t in "${TARGETS[@]}"; do
  case "$t" in pipeline|mcp) ;; *) echo "[bake] 모르는 대상: $t (pipeline·mcp)" >&2; exit 2 ;; esac
  rt="$(image_name_of "$t-runtime"):$RT_VER"; tag="$(image_name_of "$t"):$TAG"
  $DOCKER image inspect "$rt" >/dev/null 2>&1 || { echo "[bake] 실행 이미지 없음: $rt" >&2; exit 2; }
  $DOCKER image inspect "$tag" >/dev/null 2>&1 && { echo "[bake] 이미 있는 태그 $tag — TAG=<다른 판>으로" >&2; exit 2; }
  img=$(MSYS_NO_PATHCONV=1 $DOCKER run --rm --entrypoint cat "$rt" /app/docker/deps_hash | tr -d '\r\n')
  [ "$img" = "$want" ] || { echo "[bake] 의존성 지문이 다름 — 실행 이미지 $img · 코드 $want — 이 코드에는 새 실행 이미지가 필요(op-06)" >&2; exit 2; }
  rid=$($DOCKER image inspect --format '{{.Id}}' "$rt")
  echo "== [bake] $tag ← $rt ($rid) + 코드 $CODE_DIR ($commit)"
  $DOCKER build --network=none -f deploy/docker/Dockerfile.bake --target "$t" \
    --build-arg RUNTIME_IMAGE="$rt" --build-arg RUNTIME_ID="$rid" \
    --build-arg APP_VERSION="$(app_version)" --build-arg VCS_REF="$commit" -t "$tag" .
  bash deploy/release/selftest_gate.sh $DOCKER run --rm "$tag" selftest   # 코드 폴더 마운트 없이 — [판정] 통과여야 다음으로
  OUT="$OUT" DOCKER="$DOCKER" bash deploy/release/ship_stage.sh "$TAG" "$t"
done
echo "[bake] 끝 — $OUT 아래 조각·sha256을 운영 서버로 옮겨 재조립·load(release-and-patch.md §1-2)"
