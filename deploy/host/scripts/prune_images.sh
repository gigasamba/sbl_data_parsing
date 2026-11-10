#!/bin/bash
# 이미지·조각 정리 — 디스크·판 보관 기준(docs/operations/server-guide.md §5-7). 저장소(REPOS)마다 최신 KEEP개만 남기고
#   rmi + `image prune -f`(이름 없는 층만). 컨테이너(`ps -a` — 멈춘 것 포함)가 쓰는 태그는 남김 수와 상관없이 남긴다.
#   조각·tar 폴더가 있으면 남은 것도 지운다(load.sh가 보통 직후 지움 — 여긴 안전망). 남의 이미지는 건드리지 않는다
#   (이름 필터는 REPOS만, `system prune`·`-a` 금지).
# 기본 dry-run(지울 목록만 출력) · --apply일 때만 실제로 지움.
#   bash deploy/host/scripts/prune_images.sh [--apply] [--stage-dir <조각·tar 폴더>] [--keep N(기본 2 = 지금 판 + 직전 판)]
# 설정 파일(SETTINGS_FILE 또는 <루트>/settings.yaml)이 있으면 ops.host.prune_stage_dir·prune_keep_versions·container_cli를 거기서 읽는다.
set -uo pipefail
# 부른 자리 그대로(cd 안 함 — 상대 --stage-dir·SETTINGS_FILE은 부른 자리 기준). 설정 파일을 못 읽어도 멈추지 않는다(기본값으로).
. "$(dirname "$0")/load_settings.sh"   # 루트 RAG_ROOT(코드 폴더 자체)·load_settings·docker_default
if [ -n "${SETTINGS_FILE:-}" ] || [ -f "$RAG_ROOT/settings.yaml" ]; then
  load_settings || echo "[prune_images] 설정 파일을 읽지 못함 — 기본값으로 계속" >&2
fi
DOCKER=${DOCKER:-$(docker_default)}   # 두 낱말(`sudo docker`)도 — 아래는 따옴표 없이 펼침

APPLY=0
STAGE_DIR=${IMAGE_STAGE_DIR:-}
KEEP=${PRUNE_KEEP:-2}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --stage-dir) STAGE_DIR=$2; shift ;;
    --keep) KEEP=$2; shift ;;
    *) echo "[prune_images] 모르는 인자: $1 (--apply·--stage-dir·--keep만)" >&2; exit 2 ;;
  esac
  shift
done
case "$KEEP" in ""|*[!0-9]*|0) echo "[prune_images] --keep은 1 이상 정수(지금 판은 항상 남김): $KEEP" >&2; exit 2 ;; esac

# 저장소 = 두 앱 이미지와 그 짝(실행 이미지 <이름>-runtime ↔ 코드가 든 이미지 <이름>) — compose-<환경>.yml·image_names.sh와 같은 이름
. "$(dirname "$0")/../../release/image_names.sh"   # image_name_of — 이미지 이름 한 곳
REPOS=$(for t in pipeline pipeline-runtime mcp mcp-runtime; do image_name_of "$t"; done | tr '
' ' ')
USED=" $($DOCKER ps -a --format '{{.Image}}' 2>/dev/null | tr '\n' ' ') "   # 컨테이너가 쓰는 이미지(멈춘 것 포함)
echo "== 이미지($REPOS) — 최신 ${KEEP}개(지금 판 + 직전 판) + 컨테이너가 쓰는 태그 유지 =="
for repo in $REPOS; do
  rows=$($DOCKER images "$repo" --format '{{.CreatedAt}}|{{.Repository}}:{{.Tag}}' 2>/dev/null | sort -r)
  [ -z "$rows" ] && continue
  i=0
  while IFS= read -r row; do
    i=$((i + 1))
    tag=${row#*|}
    if [ "$i" -le "$KEEP" ]; then
      echo "  유지: $tag"
    elif case "$USED" in *" $tag "* | *" localhost/$tag "*) true ;; *) false ;; esac; then
      echo "  유지(컨테이너가 씀): $tag"
    else
      echo "  지움: $tag"
      [ "$APPLY" = 1 ] && $DOCKER rmi "$tag"
    fi
  done <<< "$rows"
done

if [ -n "$STAGE_DIR" ] && [ -d "$STAGE_DIR" ]; then
  echo "== 조각·tar 안전망 ($STAGE_DIR — load.sh가 보통 직후 지움, 남은 것만) =="
  found=0
  while IFS= read -r f; do
    found=1
    echo "  지움: $f"
    [ "$APPLY" = 1 ] && rm -f "$f"
  done < <(find "$STAGE_DIR" -maxdepth 1 -type f \( -name '*.tar' -o -name '*.tar.*' -o -name '*.part*' \) 2>/dev/null)
  [ "$found" = 0 ] && echo "  없음"
fi

if [ "$APPLY" = 1 ]; then
  echo "== $DOCKER image prune -f (이름 없는 층만 — system prune·-a 아님) =="
  $DOCKER image prune -f
else
  echo "(dry-run — 실제로 지우려면 --apply · 조각·tar 정리는 --stage-dir 또는 ops.host.prune_stage_dir)"
fi
