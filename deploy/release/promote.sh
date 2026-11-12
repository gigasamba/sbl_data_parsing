#!/bin/bash
# 운영 반영 — 구운 이미지 판 하나를 운영 묶음(compose-prd.yml)으로 올린다. 단계마다 명령 한 줄을 찍고 돌리며, 처음 실패에서 멈춘다.
#   bash deploy/release/promote.sh <판> <이미지 저장소 폴더> [migrate up 인자…]   (운영 묶음 코드 폴더 ${PRD_DIR}/app에서 — 개발 서버의 출시 전 시험도 같음)
#   ① 이미지 불러오기(<이미지 저장소>/load.sh) ② 폴더 준비(output·작업 폴더·홈) ③ DB 판 올리기(migrate up --target all — 처음이면 --dim <차원>)
#   ④ 컨테이너 3개 띄우기(host_ctl.sh up -d) ⑤ 배포 뒤 점검(host_ctl.sh check)
# 종료 코드: 0 통과 · 2 인자·설정 문제 · 그 밖은 실패한 단계의 종료 코드
set -euo pipefail
cd "$(dirname "$0")/../.."   # deploy/release/ → 코드 폴더 루트
ver=${1:?판 — 예: 0.5.0}
images=${2:?이미지 저장소 폴더 — 예: /home/sbl/sbl_images}
shift 2
. deploy/host/scripts/load_settings.sh && load_settings || exit 2
[ "${RUN_ENV:-}" = prd ] || { echo "[promote] settings.yaml required.env.run_env가 prd가 아님 — 운영 묶음 폴더에서 부를 것" >&2; exit 2; }
[ -f "$images/load.sh" ] || { echo "[promote] $images/load.sh 없음" >&2; exit 2; }
bench=$(dirname "$RAG_ROOT")
export IMAGE_TAG=$ver

n=0
step() {   # step <설명> <명령…> — 명령 줄을 찍고 돌림(set -e로 실패에서 멈춤)
  n=$((n + 1)); echo "== $n. $1"; shift
  echo "+ $*"
  "$@"
}
# shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
step "이미지 불러오기 $ver" env DOCKER="$DOCKER" bash "$images/load.sh" "$ver"
step "폴더 준비" mkdir -p "$RAG_ROOT/output/_mcp_parse/jobs" "$bench/home/mcp"
step "DB 판 올리기" $DOCKER run --rm --user 0 --network host -v "$SETTINGS_FILE:/etc/rag/settings.yaml:ro,z" -v "$RAG_ROOT/output:$APP_OUTPUT_ROOT:z" \
  -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=prd "data-pipeline:$ver" migrate up --target all "$@"
step "컨테이너 3개 띄우기" bash deploy/host/scripts/host_ctl.sh up -d --force-recreate
step "배포 뒤 점검" bash deploy/host/scripts/host_ctl.sh check
echo "[promote] 통과 — $ver"
