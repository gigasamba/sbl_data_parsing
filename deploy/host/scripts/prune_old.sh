#!/bin/bash
# OP18 — 디스크·판 보관 기준(image-patch-process.md §7) 그대로: 이미지(S6b — data-pipeline·mcp-server)는
#   지금 판 + 직전 판 1개만 남기고 나머지 rmi + `docker image prune -f`(이름 없는 층만) · 조각·tar 폴더가
#   있으면 남은 것 정리(load.sh가 보통 성공 직후 지움 — 여긴 안전망). 남의 이미지·컨테이너는 안 건드림
#   (이름 필터는 아래 REPOS 목록만, `docker system prune`·`-a` 금지 — §7 그대로).
#   S6c(사용자 10-27, C-30 ③) — 옛 이름 이미지(옛 3분할 data-parsing·data-structure·data-retrieval, 그 전 rag-parse·rag-structure·
#   rag-retrieval·rag-core·rag-all)는 하나도 남기지 않는다(남김 수 0). 옛 이미지는 S6b 전환의 되돌리기(refactor.md C-29)에 쓰므로
#   --apply는 새 판 전환을 확인한 뒤에만 — dry-run은 지울 목록만 보여 준다.
# 기본 dry-run(지울 목록만 출력) · --apply일 때만 실제로 지움.
#   bash deploy/host/scripts/prune_old.sh [--apply] [--stage-dir <조각·tar 폴더>] [--keep N(기본 2 — 새 이름 이미지만)]
# 환경: IMAGE_STAGE_DIR(= --stage-dir 기본값) · PRUNE_KEEP(= --keep 기본값, 기본 2 = 지금 판+직전 판) — S7e1: 설정 파일(SETTINGS_FILE 또는
#   $SERVER_ENV_DIR/settings.yaml)이 있으면 common.host.image_stage_dir·prune_keep을 거기서(settings_env.sh load_settings — 셸 env가 이김), 없으면 셸 env·기본값
set -uo pipefail
# 부른 자리 그대로(cd 안 함 — 상대 --stage-dir·SETTINGS_FILE은 부른 자리 기준, S7e1 리뷰). 설정 파일을 못 읽어도 멈추지 않는다(옛처럼 셸 env·기본값).
if [ -n "${SETTINGS_FILE:-}" ] || [ -f "${SERVER_ENV_DIR:-/srv/rag/env}/settings.yaml" ]; then
  . "$(dirname "$0")/settings_env.sh" && load_settings || echo "[prune_old] 설정 파일을 읽지 못함 — 셸 env·기본값으로 계속" >&2
fi

APPLY=0
STAGE_DIR=${IMAGE_STAGE_DIR:-}
KEEP=${PRUNE_KEEP:-2}
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --stage-dir) STAGE_DIR=$2; shift ;;
    --keep) KEEP=$2; shift ;;
    *) echo "[prune_old] 모르는 인자: $1 (--apply·--stage-dir·--keep만)" >&2; exit 2 ;;
  esac
  shift
done
case "$KEEP" in ""|*[!0-9]*|0) echo "[prune_old] --keep은 1 이상 정수(지금 판은 항상 남김): $KEEP" >&2; exit 2 ;; esac

REPOS="data-pipeline mcp-server"
OLD_REPOS="data-parsing data-structure data-retrieval rag-parse rag-structure rag-retrieval rag-core rag-all"   # S6c — 옛 이름은 모두 지움(남김 0)
prune_repos() {   # prune_repos <남길 수> <이름들> — 이름마다 최신부터 <남길 수>개 유지, 나머지 지움(--apply일 때만)
  local keep=$1 repo rows row tag i; shift
  for repo in "$@"; do
    rows=$(docker images "$repo" --format '{{.CreatedAt}}|{{.Repository}}:{{.Tag}}' 2>/dev/null | sort -r)
    [ -z "$rows" ] && continue
    i=0
    while IFS= read -r row; do
      i=$((i + 1))
      tag=${row#*|}
      if [ "$i" -le "$keep" ]; then
        echo "  유지: $tag"
      else
        echo "  지움: $tag"
        [ "$APPLY" = 1 ] && docker rmi "$tag"
      fi
    done <<< "$rows"
  done
}
echo "== 이미지($REPOS) — 최신 ${KEEP}개(지금 판 + 직전 판) 유지 =="
# shellcheck disable=SC2086
prune_repos "$KEEP" $REPOS
echo "== 옛 이름 이미지($OLD_REPOS) — 모두 지움(남김 0 · S6b 전환 확인 뒤에만 --apply — refactor.md C-29 되돌리기에 씀) =="
# shellcheck disable=SC2086
prune_repos 0 $OLD_REPOS

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
  echo "== docker image prune -f (이름 없는 층만 — system prune·-a 아님) =="
  docker image prune -f
else
  echo "(dry-run — 실제로 지우려면 --apply · 조각·tar 정리는 --stage-dir 또는 env IMAGE_STAGE_DIR)"
fi
