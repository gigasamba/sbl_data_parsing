#!/bin/bash
# 이미지 불러오기 — 이미지 저장소(sbl_images) 맨 위 사본(stage_images.sh가 복사). 판 폴더의 조각을 sha256으로 확인하고 합쳐서 load.
#   bash load.sh <판>            예: bash load.sh 0.5.0   (조각은 지우지 않음)
#   DOCKER(기본 docker, 없으면 podman) — 일반 사용자 셸이면 DOCKER="sudo docker"(podman에 넣으면 docker·systemd가 못 봄)
# 다음 순서는 docs/operations/dev.md·prd.md(운영은 코드 폴더의 deploy/release/promote.sh가 이 파일부터 차례로 부름).
#   이미지 판은 코드 판과 다를 수 있다 — 코드 deploy/docker/DEPS_HASH가 BUILD.txt의 DEPS_HASH와 같으면 그 이미지에서 돈다.
set -euo pipefail
DOCKER=${DOCKER:-$(command -v docker >/dev/null 2>&1 && echo docker || echo podman)}   # 이미지 저장소에 혼자 복사되므로 load_settings.sh를 못 씀
ver=${1:?판 — 예: 0.1.0 (이 폴더 안의 판 폴더 이름)}
cd "$(dirname "$0")/$ver"
n=0
for d in */; do
  d=${d%/}
  [ -f "$d/$d.sha256" ] || continue
  echo "== $d — sha256 확인"
  (cd "$d" && sha256sum -c --quiet "$d.sha256")
  echo "== $d — load"
  # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
  cat "$d"/"$d".tar.gz.part* | gunzip | $DOCKER load
  n=$((n + 1))
done
[ "$n" -gt 0 ] || { echo "[load] $ver 안에 이미지 폴더(<이미지>/<이미지>.sha256)가 없음" >&2; exit 2; }
[ -f BUILD.txt ] && cat BUILD.txt
echo "== 끝 — compose 파일(deploy/host/compose/compose-<환경>.yml)의 IMAGE_TAG가 위 판인지 확인(기본값과 다르면 셸 env나 compose 파일 옆 .env에 IMAGE_TAG=$ver)"
