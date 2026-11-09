#!/bin/bash
# 개발 → 운영 — 개발 서버(폐쇄망)에서 실행. 개발 서버에서 쓰던 실행 이미지(*-runtime) 그 판 + 시험한 코드 폴더를
# 그대로 묶어 운영용 이미지(코드가 든 이미지 — 코드 폴더 마운트 없이 뜸)를 만들고, 반입 판정 뒤 저장·분할한다. 패키지 설치·네트워크 없음.
#   bash deploy/release/bake_prod_image.sh <실행 이미지 태그 판> [대상… 기본 pipeline mcp]
#     예: bash <루트>/sbl_data_parsing-<판>/deploy/release/bake_prod_image.sh 0.1.0   → data-pipeline-runtime:0.1.0 + 코드 폴더 → data-pipeline:<VERSION>
#   CODE_DIR  코드 폴더(기본: 이 스크립트가 든 코드 폴더 — <루트>/sbl_data_parsing-<판>)
#   TAG       새 이미지 태그 판 = 코드 폴더 VERSION(다르면 멈춤, PC 시험 태그만 BAKE_TEST=1)
#   OUT       저장 폴더(기본 /var/tmp/bake — 코드 폴더 밖) · DOCKER(기본 docker, 없으면 podman)
#   한 대상만 실패했으면 그 대상만 다시: bash bake_prod_image.sh <판> mcp(이미 구운 대상은 "이미 있는 태그"로 멈춤)
# 순서(대상마다): ① 코드 DEPS_HASH = 실행 이미지 deps_hash ② Dockerfile.bake 빌드(문맥 = 코드 폴더) ③ selftest_gate [판정] 통과
#   ④ stage_images.sh로 저장·gzip·분할·sha256 → $OUT/sbl_images/<TAG>/<이미지>/ + load.sh·BUILD.txt(개발 서버와 같은 배치, 서버에서 load.sh <TAG>)
#   + 시험한 코드 폴더 묶음(code-<판>-<커밋>.tar.gz — 운영 서버 호스트 스크립트 deploy/host/·compose용, 이미지와 같은 커밋 —
#     .git·deploy/host/scripts/test_space/·valid_env/·validation/·settings*.yaml(sample 빼고)·output/은 넣지 않음)
set -euo pipefail
[ $# -ge 1 ] || { echo "사용: bash bake_prod_image.sh <실행 이미지 태그 판> [pipeline mcp]" >&2; exit 2; }
RT_VER="$1"; shift
if [ "$#" -gt 0 ]; then TARGETS=("$@"); else TARGETS=(pipeline mcp); fi
OUT="${OUT:-/var/tmp/bake}"; mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)   # stage_images.sh가 cd하므로 절대 경로로
CODE_DIR=$(cd "${CODE_DIR:-$(dirname "$0")/../..}" && pwd)
. "$(dirname "$0")/../host/scripts/load_settings.sh"   # docker_default 한 곳(docker, 없으면 podman) · 이 스크립트가 든 코드 폴더의 것(CODE_DIR가 다른 판 코드 폴더여도)
DOCKER="${DOCKER:-$(docker_default)}"
HERE=$(cd "$(dirname "$0")" && pwd)   # 이 스크립트 폴더 — stage_images.sh는 여기 것(CODE_DIR가 stage_images.sh 없는 다른 판 코드 폴더여도)
cd "$CODE_DIR"
. deploy/release/image_names.sh
TAG="${TAG:-$(app_version)}"
[ "$TAG" = "$(app_version)" ] || [ "${BAKE_TEST:-}" = 1 ] \
  || { echo "[bake_prod_image] TAG($TAG) ≠ 코드 VERSION($(app_version)) — 태그 = 버전(D-036). 다시 구우려면 VERSION을 올린 코드로" >&2; exit 2; }
want=$(tr -d '\r\n' < deploy/docker/DEPS_HASH)
commit=$(cut -d' ' -f1 CODE_COMMIT 2>/dev/null); case "$commit" in ''|'$Format'*) commit=$(git rev-parse HEAD 2>/dev/null || echo unknown) ;; esac   # clone이면 틀 그대로
# 운영 서버 호스트 스크립트(deploy/host/ — nightly_batch.sh·compose·systemd)도 이미지와 같은 코드로 — 시험한 코드 폴더를 묶음.
# 운영에 필요 없는 것(git 기록·러너 작업 폴더·PC 검증 데이터·검증 도구)은 뺀다. git clone이면 git archive(추적 파일만 — settings*.yaml 사본·output 없음)
BUNDLE="$OUT/code-$TAG-$(echo "$commit" | cut -c1-7).tar.gz"
NOT_PRD=(deploy/host/scripts/test_space valid_env validation)
if [ -d "$CODE_DIR/.git" ] && command -v git >/dev/null 2>&1; then
  xs=(); for d in "${NOT_PRD[@]}"; do xs+=(":(exclude)$d"); done
  git -c safe.directory='*' -C "$CODE_DIR" archive --format=tar.gz HEAD -- . "${xs[@]}" > "$BUNDLE"
else
  ex=(--exclude=./.git --exclude=./output --exclude=./home --exclude=./edw_chain.yaml)   # 벌 폴더(= 코드 폴더)의 결과·개발 작업 공간 홈·사슬 사본, 루트의 settings*.yaml·그 사본·백업(비밀값 — `settings copy.yaml` 포함)도 뺌, sample만 묶음
  for d in "${NOT_PRD[@]}"; do ex+=("--exclude=./$d"); done
  for f in "$CODE_DIR"/settings*.yaml*; do
    [ -e "$f" ] || continue
    case "${f##*/}" in settings.sample.yaml) ;; *) ex+=("--exclude=./${f##*/}") ;; esac
  done
  tar -czf - "${ex[@]}" -C "$CODE_DIR" . > "$BUNDLE"
fi

for t in "${TARGETS[@]}"; do
  case "$t" in pipeline|mcp) ;; *) echo "[bake_prod_image] 모르는 대상: $t (pipeline·mcp)" >&2; exit 2 ;; esac
  rt="$(image_name_of "$t-runtime"):$RT_VER"; tag="$(image_name_of "$t"):$TAG"
  $DOCKER image inspect "$rt" >/dev/null 2>&1 || { echo "[bake_prod_image] 실행 이미지 없음: $rt" >&2; exit 2; }
  $DOCKER image inspect "$tag" >/dev/null 2>&1 && { echo "[bake_prod_image] 이미 있는 태그 $tag — 다시 구우려면 VERSION을 올린 코드로(이미 구운 대상은 빼고 남은 대상만 지정)" >&2; exit 2; }
  img=$(MSYS_NO_PATHCONV=1 $DOCKER run --rm --entrypoint cat "$rt" /app/docker/deps_hash | tr -d '\r\n')
  [ "$img" = "$want" ] || { echo "[bake_prod_image] 의존성 지문이 다름 — 실행 이미지 $img · 코드 $want — 이 코드에는 새 실행 이미지가 필요(op-06)" >&2; exit 2; }
  rid=$($DOCKER image inspect --format '{{.Id}}' "$rt")
  echo "== [bake_prod_image] $tag ← $rt ($rid) + 코드 $CODE_DIR ($commit)"
  $DOCKER build --network=none -f deploy/docker/Dockerfile.bake --target "$t" \
    --build-arg RUNTIME_IMAGE="$rt" --build-arg RUNTIME_ID="$rid" \
    --build-arg APP_VERSION="$(app_version)" --build-arg VCS_REF="$commit" -t "$tag" .
  # 판정·저장이 실패하면 구운 태그를 지운다(다시 실행이 "이미 있는 태그"로 막히지 않게)
  bash deploy/release/selftest_gate.sh $DOCKER run --rm "$tag" selftest \
    || { echo "[bake_prod_image] 반입 판정 실패 — $tag 지움" >&2; $DOCKER rmi "$tag" >/dev/null || true; exit 1; }   # 코드 폴더 마운트 없이
  OUT="$OUT" DOCKER="$DOCKER" CODE_BUNDLE="$BUNDLE" bash "$HERE/stage_images.sh" "$TAG" "$t" \
    || { echo "[bake_prod_image] 저장 실패 — $tag 지움" >&2; $DOCKER rmi "$tag" >/dev/null || true; exit 1; }
done
echo "[bake_prod_image] 끝 — $OUT 아래 조각·sha256을 운영 서버로 옮겨 재조립·load(server-guide.md §5-4)"
