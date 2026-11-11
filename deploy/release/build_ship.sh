#!/bin/bash
# PC에서 이미지 하나 빌드 → 판정(selftest_gate.sh) → resources·비밀값 흔적 점검. 실행 이미지(*-runtime)면 코드 폴더 묶음도 만든다.
#   [IMAGE_TARGET=pipeline|mcp|pipeline-runtime|mcp-runtime(기본 pipeline)] [TAG=<이미지>:<태그>] [DOCKER=docker|podman] \
#   [BUILD_ARGS="--build-arg BASE=<사내 기반 이미지> --build-arg APT=0"] bash deploy/release/build_ship.sh
#   서버로 옮기기는 stage_images.sh(이미지 저장소) → 서버 load.sh. 운영 이미지는 개발 서버 bake_prod_image.sh.
# 태그: 기본 <이미지 이름>:<VERSION>. 같은 태그가 있으면 멈춤(시험 빌드는 TAG=<다른 태그>, 다시 만들 때만 FORCE_TAG=1).
# 빌드 컨텍스트 = 저장소 루트(.dockerignore 허용 목록). 비밀값은 이미지에 넣지 않는다.
set -euo pipefail
cd "$(dirname "$0")/../.."                                # deploy/release/ → 저장소 루트 = 빌드 컨텍스트
IMAGE_TARGET=${IMAGE_TARGET:-pipeline}
case "$IMAGE_TARGET" in
  pipeline|mcp|pipeline-runtime|mcp-runtime) ;;
  *) echo "[오류] 모르는 IMAGE_TARGET: $IMAGE_TARGET (pipeline·mcp·pipeline-runtime·mcp-runtime)" >&2; exit 2 ;;
esac
. deploy/release/image_names.sh   # image_name_of·app_version
APP_VERSION=$(app_version) || exit 2
APP_CODE_ROOT=$(awk -F'\t' '$1=="image.code_root"{print $4}' deploy/host/scripts/host_settings.tsv)     # 컨테이너 안 코드 자리(settings.IMAGE_PATHS)
APP_OUTPUT_ROOT=$(awk -F'\t' '$1=="image.output_root"{print $4}' deploy/host/scripts/host_settings.tsv) # 컨테이너 안 결과 자리
VCS_REF=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
if [ "$VCS_REF" != unknown ] && ! git diff --quiet HEAD -- 2>/dev/null; then VCS_REF="$VCS_REF-dirty"; fi   # 커밋 안 한 변경이 섞인 빌드 표시
TAG_DEFAULT=0; [ -n "${TAG:-}" ] || TAG_DEFAULT=1
TAG=${TAG:-$(image_name_of "$IMAGE_TARGET"):$APP_VERSION}
DOCKER=${DOCKER:-docker}
RUNTIME=0; case "$IMAGE_TARGET" in *-runtime) RUNTIME=1 ;; esac
CODE_OUT=${CODE_OUT:-output/ship/code-$APP_VERSION-$VCS_REF.tar.gz}   # 실행 이미지의 코드 폴더 묶음

echo "== 0. 사전 점검"
[ -f .dockerignore ] || { echo "[오류] .dockerignore 없음 — 허용 목록 없이 빌드하면 .venv·output·valid_env가 컨텍스트에 들어감"; exit 2; }
ls deploy/docker/wheels/*.whl >/dev/null 2>&1 && echo "[안내] deploy/docker/wheels 휠로 오프라인 설치" || echo "[안내] deploy/docker/wheels 비어 있음 — PyPI 접속 필요(폐쇄망이면 실패)"
# Dockerfile heredoc — Docker 23 미만 기본 프런트엔드는 못 읽으므로 BuildKit 문법 이미지를 붙인다
SYNTAX_ARG=""
if [ -n "${BUILDKIT_SYNTAX:-}" ]; then SYNTAX_ARG="--build-arg BUILDKIT_SYNTAX=$BUILDKIT_SYNTAX"
elif [ "$(basename "$DOCKER")" = docker ]; then
  dv=$($DOCKER version --format '{{.Server.Version}}' 2>/dev/null || echo 0); dv=${dv%%.*}
  case "$dv" in
    ''|*[!0-9]*) ;;
    *) if [ "$dv" -lt 23 ]; then SYNTAX_ARG="--build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7"
         echo "[안내] Docker $dv.x — BuildKit + $SYNTAX_ARG (docker/dockerfile 이미지를 받음 — 인터넷 필요)"; fi ;;
  esac
fi
[ "$(basename "$DOCKER")" = docker ] && export DOCKER_BUILDKIT=1
if [ "${IMAGE_TARGET%-runtime}" = pipeline ] && ! ls assets/rapidocr/*.onnx >/dev/null 2>&1; then   # assets/는 pipeline 이미지만 씀
  [ "${ALLOW_NO_ASSETS:-0}" = 1 ] && echo "[경고] assets/rapidocr 없음 — ALLOW_NO_ASSETS=1로 계속(폐쇄망에서 rapidocr_ko 첫 실행 실패)" \
    || { echo "[오류] assets/rapidocr/*.onnx 없음 — assets.py pack(worktree면 메인 체크아웃의 assets/ 복사). 계속하려면 ALLOW_NO_ASSETS=1"; exit 2; }
fi
if [ ! -f assets/opencode/opencode ]; then   # 개발 작업 공간의 opencode(선택)
  [ "${ALLOW_NO_ASSETS:-0}" = 1 ] && echo "[경고] assets/opencode/opencode 없음 — ALLOW_NO_ASSETS=1로 opencode 없이 빌드" \
    || { echo "[오류] assets/opencode/opencode 없음 — assets.py pack으로 채우거나 opencode 없이 빌드하려면 ALLOW_NO_ASSETS=1"; exit 2; }
fi
if [ "$TAG_DEFAULT" = 1 ] && [ "${FORCE_TAG:-0}" != 1 ] && $DOCKER image inspect "$TAG" >/dev/null 2>&1; then
  echo "[오류] 이미 있는 태그 $TAG — VERSION을 올리거나 TAG=<다른 태그>로 빌드(다시 만들 때만 FORCE_TAG=1)" >&2; exit 2
fi

echo "== 1. 빌드 $TAG (버전 $APP_VERSION · 커밋 $VCS_REF)"
$DOCKER build ${BUILD_ARGS:-} $SYNTAX_ARG --build-arg APP_VERSION="$APP_VERSION" --build-arg VCS_REF="$VCS_REF" -f deploy/docker/Dockerfile --target "$IMAGE_TARGET" -t "$TAG" .
export MSYS_NO_PATHCONV=1   # Windows Git Bash가 -v 인자를 바꾸지 않게
RUN_ARGS=""
if [ "$RUNTIME" = 1 ]; then
  if $DOCKER run --rm "$TAG" help >/dev/null 2>&1; then echo "[오류] 코드 마운트 없이 실행 이미지가 떴음"; exit 1; fi   # runtime_entry.sh가 멈춰야 함
  # 판정·묶음 = 이 커밋의 코드 트리(git archive — 커밋 안 한 변경은 빠짐) + CODE_COMMIT
  CODE_DIR=$(mktemp -d); trap 'rm -rf "$CODE_DIR"' EXIT
  git archive HEAD -- . ':(exclude)valid_env' ':(exclude)validation' | tar -x -C "$CODE_DIR"
  echo "$(git rev-parse HEAD 2>/dev/null || echo unknown) $VCS_REF $APP_VERSION" > "$CODE_DIR/CODE_COMMIT"
  chmod -R u=rwX,go=rX "$CODE_DIR"   # mktemp -d는 0700 — 서버에서 푼 폴더를 모두가 읽게
  mkdir -p "$(dirname "$CODE_OUT")"
  tar -czf - -C "$CODE_DIR" . > "$CODE_OUT"   # 표준 출력으로(Windows 경로 C:/…를 tar가 원격 호스트로 읽지 않게)
  bad=$(tar -tvzf - < "$CODE_OUT" | awk 'NR==1 && $1 != "drwxr-xr-x" {print "맨위폴더 " $1} $1 !~ /^.r..r..r/ {print $NF}')
  [ -z "$bad" ] || { echo "[오류] 코드 폴더 묶음 권한 — 모두가 읽을 수 없음: $bad"; exit 1; }
  echo "[코드 폴더 묶음] $CODE_OUT ($(du -h "$CODE_OUT" | cut -f1)) — 서버 벌의 app 폴더로 풂"
  mkdir -p "$CODE_DIR/output"   # 읽기 전용 코드 위 임시 결과 폴더(--tmpfs)의 붙일 자리(묶음엔 안 들어감)
  RUN_ARGS="-v $(cygpath -m "$CODE_DIR" 2>/dev/null || echo "$CODE_DIR"):$APP_CODE_ROOT:ro"
fi

echo "== 2. 판정"
# DB 사례는 PG에 붙는다(e2-22) — 설정 파일·RUN_ENV를 주고 host 네트워크로. Docker Desktop의 127.0.0.1은 PC가 아니라 PG 주소만 덮음.
G_SET=${SETTINGS_FILE:-$PWD/settings.yaml}
[ -f "$G_SET" ] || { echo "[오류] 판정에 쓸 설정 파일 없음: $G_SET (SETTINGS_FILE 또는 루트 settings.yaml — PG 접속 required.pg)"; exit 1; }
G_ARGS="--network host --add-host host.docker.internal:host-gateway --tmpfs $APP_OUTPUT_ROOT:mode=1777 -v $(cygpath -m "$G_SET" 2>/dev/null || echo "$G_SET"):/etc/rag/settings.yaml:ro,z -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=${RUN_ENV:-local}"
bash deploy/release/selftest_gate.sh $DOCKER run --rm $G_ARGS $RUN_ARGS "$TAG" selftest --set PG_HOST=host.docker.internal
$DOCKER run --rm $RUN_ARGS "$TAG" resources
if $DOCKER history --no-trunc "$TAG" | grep -Eiq 'PASSWORD=[^ $]|API_KEY=[^ $]'; then echo "[오류] 이미지 기록에 비밀값 흔적"; exit 1; fi
echo "완료: $TAG"
