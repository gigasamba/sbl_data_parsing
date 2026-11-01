#!/bin/bash
# 이미지 불러오기(op-10) — 이미지 저장소(sbl_images) 맨 위에 놓이는 사본(ship_stage.sh가 복사). 판 폴더의 조각을 sha256으로 확인하고,
# 합쳐서 docker/podman load. 조각은 지우지 않는다. 개발 서버(실행 이미지)·운영 서버(구운 이미지) 같은 배치(README §5-0).
#   bash load.sh <판>            예: bash load.sh 0.1.0
#   DOCKER(기본 podman, 없으면 docker). 서버는 root podman 하나 — 일반 사용자 셸이면 DOCKER="sudo podman" bash load.sh <판>
#   (일반 사용자 podman(rootless)으로 load하면 root podman·systemd가 이미지를 못 봄)
# 코드는 이 저장소에 없다 — 코드 저장소(sbl_data_parsing) zip을 같은 폴더에 풀고 그 README §5-0을 따른다.
set -euo pipefail
DOCKER=${DOCKER:-$(command -v podman >/dev/null 2>&1 && echo podman || echo docker)}
ver=${1:?판 — 예: 0.1.0 (이 폴더 안의 판 폴더 이름)}
cd "$(dirname "$0")/$ver"
n=0
for d in */; do
  d=${d%/}
  [ -f "$d/$d.sha256" ] || continue
  echo "== $d — sha256 확인"
  (cd "$d" && sha256sum -c --quiet "$d.sha256")
  echo "== $d — load"
  # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo podman)
  cat "$d"/"$d".tar.gz.part* | gunzip | $DOCKER load
  n=$((n + 1))
done
[ "$n" -gt 0 ] || { echo "[load] $ver 안에 이미지 폴더(<이미지>/<이미지>.sha256)가 없음" >&2; exit 2; }
[ -f BUILD.txt ] && cat BUILD.txt
echo "== 끝 — settings.yaml 이미지 칸(required.deploy.pipeline_image·mcp_image)을 위 태그로(예: data-pipeline-runtime:$ver)"
