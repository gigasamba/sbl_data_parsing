#!/bin/bash
# PC에서: 이미지 빌드 → 점검 → 압축 저장(sha256) → ssh로 수집 서버에 전송·적재 → 원격 점검(운영 이미지는 개발 서버 bake_prod_image.sh가 기본 — release-and-patch §1-2).
#   [IMAGE_TARGET=pipeline|mcp|pipeline-runtime|mcp-runtime — 이미지 2개, *-runtime = 코드 없는 실행 이미지(코드 폴더 묶음도 만듦), 기본 pipeline]
#   TARGET=user@수집서버 [TAG=data-pipeline:0.1.0] [REMOTE_DIR=/var/tmp] [DOCKER=docker|podman] [REMOTE_DOCKER=docker] \
#   [BUILD_ARGS="--build-arg BASE=<사내 기반 이미지> --build-arg APT=0"] bash deploy/release/build_ship.sh
#   BUILD_ONLY=1 — 빌드·로컬 점검(selftest 판정·resources·비밀값 흔적)까지만(TARGET·ssh 없음, 저장·전송 안 함 — PC 로컬 빌드)
# 빌드 컨텍스트 = 이 저장소 루트(.dockerignore 허용 목록). Docker 23 미만은 BuildKit + BUILDKIT_SYNTAX를 자동으로 붙인다
#   (Dockerfile heredoc — 직접 주려면 BUILDKIT_SYNTAX=docker/dockerfile:1.7, podman은 서버에서 확인).
# selftest 판정은 selftest_gate.sh — 알려진 FAIL(known_fail.txt) 밖의 FAIL 0이면 통과.
# IMAGE_TARGET→이미지 이름: pipeline→data-pipeline·mcp→mcp-server(image_names.sh).
# 태그: 기본 <이미지 이름>:<저장소 루트 VERSION> — 두 이미지가 같은 버전 태그. 빌드한 커밋·버전은 이미지 라벨
#   (org.opencontainers.image.revision·version)에 넣는다. 같은 태그가 이미 있으면 멈춘다(한 번 붙인 버전 태그는 옮기지 않음):
#   VERSION을 올리거나, 시험 빌드는 TAG=<다른 태그>, 정말 다시 만들 때만 FORCE_TAG=1.
# 비밀값은 이미지에 넣지 않는다 — settings.yaml은 따로(주인 UID 10001·640 — refactor.md C-09) 수집 서버에 둔다(아래 안내).
set -euo pipefail
cd "$(dirname "$0")/../.."                                # deploy/release/ → 저장소 루트 = 빌드 컨텍스트
BUILD_ONLY=${BUILD_ONLY:-0}
[ "$BUILD_ONLY" = 1 ] || TARGET=${TARGET:?TARGET=user@수집서버 를 지정(빌드만 하려면 BUILD_ONLY=1)}
IMAGE_TARGET=${IMAGE_TARGET:-pipeline}
case "$IMAGE_TARGET" in
  pipeline|mcp|pipeline-runtime|mcp-runtime) ;;   # *-runtime = 코드 없는 실행 이미지(개발 서버, 코드 폴더를 /app/deploy에 마운트)
  *) echo "[오류] 모르는 IMAGE_TARGET: $IMAGE_TARGET (pipeline·mcp·pipeline-runtime·mcp-runtime)" >&2; exit 2 ;;
esac
. deploy/release/image_names.sh   # image_name_of — 타깃 → 이미지 이름(stage_images.sh와 같은 파일)
APP_VERSION=$(app_version) || exit 2
VCS_REF=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
if [ "$VCS_REF" != unknown ] && ! git diff --quiet HEAD -- 2>/dev/null; then VCS_REF="$VCS_REF-dirty"; fi   # 커밋 안 한 변경이 섞인 빌드 표시
TAG_DEFAULT=0; [ -n "${TAG:-}" ] || TAG_DEFAULT=1
TAG=${TAG:-$(image_name_of "$IMAGE_TARGET"):$APP_VERSION}
REMOTE_DIR=${REMOTE_DIR:-/var/tmp}
DOCKER=${DOCKER:-docker}
REMOTE_DOCKER=${REMOTE_DOCKER:-docker}
OUT=${OUT:-/var/tmp/$(echo "$TAG" | tr ':/' '__').tar.gz}
RUNTIME=0; case "$IMAGE_TARGET" in *-runtime) RUNTIME=1 ;; esac
# 실행 이미지면 코드 폴더 묶음(이 커밋의 git 추적 파일 + CODE_COMMIT, valid_env/·validation/ 뺌)도 이미지 옆에 만든다.
CODE_OUT=${CODE_OUT:-output/ship/code-$APP_VERSION-$VCS_REF.tar.gz}   # 저장소 안(OUT의 /var/tmp는 Windows Git Bash에 없음)

echo "== 0. 사전 점검"
if [ "$BUILD_ONLY" != 1 ]; then
  L_ARCH=$(uname -m); R_ARCH=$(ssh "$TARGET" uname -m)
  [ "$L_ARCH" = "$R_ARCH" ] || { echo "[오류] CPU 아키텍처 다름: 개발 $L_ARCH / 수집 $R_ARCH — 같은 아키텍처에서 빌드(buildx --platform)"; exit 1; }
  ssh "$TARGET" "$REMOTE_DOCKER version --format '{{.Server.Version}}' >/dev/null" || { echo "[오류] 수집 서버 $REMOTE_DOCKER 사용 불가(설치·권한·docker 그룹)"; exit 1; }
fi
[ -f .dockerignore ] || { echo "[오류] .dockerignore 없음 — 허용 목록 없이 빌드하면 .venv·output·valid_env가 컨텍스트에 들어감"; exit 2; }
ls deploy/docker/wheels/*.whl >/dev/null 2>&1 && echo "[안내] deploy/docker/wheels 휠로 오프라인 설치" || echo "[안내] deploy/docker/wheels 비어 있음 — PyPI 접속 필요(폐쇄망이면 실패)"
# Dockerfile pipeline 단계 heredoc — Docker 23 미만 기본 프런트엔드는 파일을 못 읽음. podman·23 이상은 손대지 않음.
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
  [ "${ALLOW_NO_ASSETS:-0}" = 1 ] && echo "[경고] assets/rapidocr 없음 — ALLOW_NO_ASSETS=1로 계속(rapidocr_ko가 첫 실행에 모델을 받으려다 실패·폐쇄망이면 그대로 실패)" \
    || { echo "[오류] assets/rapidocr/*.onnx 없음 — Git worktree에서 빌드할 때 메인 체크아웃의 assets/를 먼저 복사하세요(Git 제외 자산, image-patch-process.md §4). 계속하려면 ALLOW_NO_ASSETS=1"; exit 2; }
fi
if [ ! -f assets/opencode/opencode ]; then   # 개발 작업 공간의 opencode(선택 — 네 이미지 모두 base 단계에서 넣음)
  [ "${ALLOW_NO_ASSETS:-0}" = 1 ] && echo "[경고] assets/opencode/opencode 없음 — ALLOW_NO_ASSETS=1로 opencode 없이 빌드" \
    || { echo "[오류] assets/opencode/opencode 없음 — assets.py pack으로 채우거나(release-and-patch §5-6) opencode 없이 빌드하려면 ALLOW_NO_ASSETS=1"; exit 2; }
fi

if [ "$TAG_DEFAULT" = 1 ] && [ "${FORCE_TAG:-0}" != 1 ] && $DOCKER image inspect "$TAG" >/dev/null 2>&1; then
  echo "[오류] 이미 있는 태그 $TAG — VERSION을 올리거나(D-036) TAG=<다른 태그>로 빌드(다시 만들 때만 FORCE_TAG=1)" >&2; exit 2
fi
echo "== 1. 빌드 $TAG (버전 $APP_VERSION · 커밋 $VCS_REF)"
$DOCKER build ${BUILD_ARGS:-} $SYNTAX_ARG --build-arg APP_VERSION="$APP_VERSION" --build-arg VCS_REF="$VCS_REF" -f deploy/docker/Dockerfile --target "$IMAGE_TARGET" -t "$TAG" .
RUN_ARGS=""
if [ "$RUNTIME" = 1 ]; then
  # 코드 없이 띄우면 바로 멈춰야 함(runtime_entry.sh)
  if MSYS_NO_PATHCONV=1 $DOCKER run --rm "$TAG" help >/dev/null 2>&1; then echo "[오류] 코드 마운트 없이 실행 이미지가 떴음"; exit 1; fi
  # 판정·묶음은 이 커밋의 코드 트리(git archive — 커밋 안 한 변경은 안 들어감) + CODE_COMMIT
  CODE_DIR=$(mktemp -d); trap 'rm -rf "$CODE_DIR"' EXIT
  git archive HEAD -- . ':(exclude)valid_env' ':(exclude)validation' | tar -x -C "$CODE_DIR"
  echo "$(git rev-parse HEAD 2>/dev/null || echo unknown) $VCS_REF $APP_VERSION" > "$CODE_DIR/CODE_COMMIT"
  # mktemp -d는 0700 — 그대로 묶으면 서버에서 푼 판 폴더를 컨테이너 사용자 10001이 못 읽음. 모두가 읽게(폴더 755·파일 644, 실행 비트는 유지)
  chmod -R u=rwX,go=rX "$CODE_DIR"
  mkdir -p "$(dirname "$CODE_OUT")"
  tar -czf - -C "$CODE_DIR" . > "$CODE_OUT"   # 표준 출력으로(Windows 경로 C:/…를 tar가 원격 호스트로 읽지 않게)
  # 맨 위 폴더 755 + 모든 항목 모두가 읽기(head로 자르지 않음 — pipefail에서 tar가 SIGPIPE로 실패함)
  bad=$(tar -tvzf - < "$CODE_OUT" | awk 'NR==1 && $1 != "drwxr-xr-x" {print "맨위폴더 " $1} $1 !~ /^.r..r..r/ {print $NF}')
  [ -z "$bad" ] || { echo "[오류] 코드 폴더 묶음 권한 — 컨테이너 사용자 10001이 못 읽음: $bad"; exit 1; }
  echo "[코드 폴더 묶음] $CODE_OUT ($(du -h "$CODE_OUT" | cut -f1)) — 서버의 벌 폴더(sbl_data_parsing-main-<번호>)로 풂(release-and-patch.md §8 — op-13)"
  export MSYS_NO_PATHCONV=1   # Windows Git Bash가 -v 인자를 바꾸지 않게
  RUN_ARGS="-v $(cygpath -m "$CODE_DIR" 2>/dev/null || echo "$CODE_DIR"):/app/deploy:ro"
fi
bash deploy/release/selftest_gate.sh $DOCKER run --rm $RUN_ARGS "$TAG" selftest   # 알려진 FAIL 밖 FAIL 0이어야 통과(selftest 종료 코드만 보지 않음)
$DOCKER run --rm $RUN_ARGS "$TAG" resources
if $DOCKER history --no-trunc "$TAG" | grep -Eiq 'PASSWORD=[^ $]|API_KEY=[^ $]'; then echo "[오류] 이미지 기록에 비밀값 흔적"; exit 1; fi
if [ "$BUILD_ONLY" = 1 ]; then echo "완료(빌드만): $TAG — 저장·전송 안 함(BUILD_ONLY=1)"; exit 0; fi

echo "== 2. 저장 $OUT"
need=$($DOCKER image inspect "$TAG" --format '{{.Size}}'); need=$((need / 1024 / 1024 / 1024 + 2))
avail=$(df -BG --output=avail "$(dirname "$OUT")" | tail -1 | tr -dc 0-9)
[ "$avail" -gt "$need" ] || { echo "[오류] 저장 공간 부족: ${avail}G < 약 ${need}G"; exit 1; }
$DOCKER save "$TAG" | gzip -1 > "$OUT"
SUM=$(sha256sum "$OUT" | cut -d' ' -f1); ls -lh "$OUT"

echo "== 3. 전송·적재 $TARGET:$REMOTE_DIR"
r_avail=$(ssh "$TARGET" "df -BG --output=avail $REMOTE_DIR | tail -1" | tr -dc 0-9)
r_root=$(ssh "$TARGET" "df -BG --output=avail \$($REMOTE_DOCKER info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/containers) | tail -1" | tr -dc 0-9)
echo "수집 서버 여유: 전송 폴더 ${r_avail}G · Docker 저장소 ${r_root}G (필요 약 압축본 + 이미지 ${need}G)"
[ "$r_root" -gt "$need" ] || { echo "[오류] 수집 서버 Docker 저장소 공간 부족"; exit 1; }
rsync --partial --progress "$OUT" "$TARGET:$REMOTE_DIR/" 2>/dev/null || scp "$OUT" "$TARGET:$REMOTE_DIR/"   # rsync면 끊겨도 이어받기
ssh "$TARGET" "cd $REMOTE_DIR && echo '$SUM  $(basename "$OUT")' | sha256sum -c - && gunzip -c $(basename "$OUT") | $REMOTE_DOCKER load"

echo "== 4. 원격 점검"
R_ARGS=""
if [ "$RUNTIME" = 1 ]; then   # 판정용 코드 폴더를 같이 보내 붙임
  rsync --partial "$CODE_OUT" "$TARGET:$REMOTE_DIR/" 2>/dev/null || scp "$CODE_OUT" "$TARGET:$REMOTE_DIR/"
  RCODE="$REMOTE_DIR/code-$APP_VERSION-$VCS_REF"
  ssh "$TARGET" "rm -rf $RCODE && mkdir -p $RCODE && tar -xzf $REMOTE_DIR/$(basename "$CODE_OUT") --no-same-owner -C $RCODE"
  R_ARGS="-v $RCODE:/app/deploy:ro,z"
fi
ssh "$TARGET" "$REMOTE_DOCKER run --rm $R_ARGS $TAG resources"
bash deploy/release/selftest_gate.sh ssh "$TARGET" "$REMOTE_DOCKER run --rm $R_ARGS $TAG selftest"
cat <<EOF
완료: $TAG
다음(수집 서버):
  1) 공용 폴더(예 /home/sbl/)에 코드 zip을 풀어 벌 폴더(sbl_data_parsing-main-<번호>)로 두고 그 안에서 sudo bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>(op-13)
  2) <벌 폴더>/settings.yaml의 맨 위 required 빈 값을 채움(새 판 덮어쓰기면 settings.yaml·edw_chain.yaml·output/은 그대로 둠)
  3) 띄우기·점검: README §5(host_ctl.sh up -d … → host_ctl.sh check)
  압축본 $REMOTE_DIR/$(basename "$OUT") 은 적재 확인 뒤 지워도 됨
EOF
