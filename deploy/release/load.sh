#!/bin/bash
# 이미지 불러오기 — 이미지 저장소(sbl_images) 맨 위에 놓이는 사본(stage_images.sh가 복사). 판 폴더의 조각을 sha256으로 확인하고,
# 합쳐서 docker/podman load. 조각은 지우지 않는다. 개발 서버(실행 이미지)·운영 서버(구운 이미지) 같은 배치(server-guide §1-2).
#   bash load.sh <판>            예: bash load.sh 0.1.0
#   DOCKER(기본 docker, 없으면 podman). 서버는 docker 하나 — 일반 사용자 셸이면 DOCKER="sudo docker" bash load.sh <판>
#   (같은 서버의 podman에 load하면 docker·systemd가 이미지를 못 봄 — 두 도구는 저장소가 따로)
# 코드는 이 저장소에 없다 — 코드 저장소(sbl_data_parsing) zip을 같은 루트 폴더에 풀고(코드 폴더 sbl_data_parsing-<판> — 루트 = 그 부모)
#   그 server-guide §1-5를 따른다: load.sh → host_ctl.sh init → 설정 채우기 → host_ctl.sh up -d data-pipeline → migrate up --target all · master load → host_ctl.sh up -d mcp-data-parsing mcp → host_ctl.sh check.
#   이미지 판은 코드 판과 다를 수 있다 — 코드 deploy/docker/DEPS_HASH가 이 판 BUILD.txt의 DEPS_HASH와 같으면 그 이미지에서 돈다.
set -euo pipefail
DOCKER=${DOCKER:-$(command -v docker >/dev/null 2>&1 && echo docker || echo podman)}   # docker_default(load_settings.sh)를 쓰지 않음 — 이 파일은 이미지 저장소에 혼자 복사됨(stage_images.sh)
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
echo "== 끝 — settings.yaml 이미지 칸(required.deploy.pipeline_image·mcp_image)을 위 태그로(예: data-pipeline-runtime:$ver)"
