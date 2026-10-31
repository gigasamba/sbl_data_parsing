#!/bin/bash
# 모듈 트리거(1회 실행) — docs/architecture.md. 개발 서버 시험·나중의 새벽 배치(deploy/host/systemd/)가 같은 스크립트를 부름.
#   bash deploy/host/scripts/trigger.sh parse|structure|load|publish|all|night [모듈 인자…]   (코드 폴더 루트에서 — S6b, 옛 docker/trigger.sh)
#   publish(SI39) = 대표 결과(.md) Object Storage 업로드 + EDW 메타(cli/publish_parse.py --apply) — "all"에 포함(파싱 직후)
#   night(OP13) = 자정 배치 순서(NIGHTLY_MODULES, 기본 "parse publish structure load") — 시각과 무관하게 요청하면 바로 돎
#   scheduled = 타이머용 — NIGHTLY_TIME 시각(5분 창)에만 night(아래 — §env-guide 1-3)
#     NIGHTLY_PUBLISH=1(기본)이면 publish 실행 · parse 단계는 PARSE_DEADLINE 있으면 전달, 새 문서 상한은 NIGHTLY_MAX_NEW(기본 2000)
#     이 night(컨테이너별 모듈 트리거, OP13 정본)과 cli/pipeline.py의 night()(한 프로세스 안 단계별 마감 예산)은
#     서로 다른 배포 모양(compose 여러 컨테이너 ↔ 단일 컨테이너·Docker 밖 직접 실행, AGENTS.md 45행)을 각자 맡음 —
#     RV5(10-09) 점검: pipeline.py night은 호출처 있음(AGENTS.md 지시표·entrypoint.sh night/full·requirements.md S8
#     cron 예시) → 강제 병합 대신, 건너뜀 사유는 이 스크립트의 echo(아래 publish·75) → cron 리다이렉션으로
#     /srv/rag/output/batch.log 한 곳에(batch.env.example 참고) 모은다
#   설정(S7e1 — 사용자 10-27 Q3·Q5): settings.yaml(SETTINGS_FILE, 기본 $SERVER_ENV_DIR/settings.yaml — SERVER_ENV_DIR 기본 배치 /srv/rag/env)의
#     호스트 칸(이미지·RAG_OUT·DOC_SRC·자원·NIGHTLY_*·PARSE_DEADLINE 등)을 settings_env.sh load_settings가 셸 env로 — 이미 셸에 있는 이름은 그대로.
#     옛 ENV_FILE(pipeline.env)은 읽지 않는다(settings.yaml이 없고 pipeline.env만 있으면 "설정 이관 필요"로 종료 코드 2).
#     S6b(D-020, 사용자 10-27): 이미지 변수 확인은 image_vars.sh — 옛 DATA_PARSING_IMAGE·DATA_STRUCTURE_IMAGE·DATA_RETRIEVAL_IMAGE·RAG_*만 있으면 "새 이미지 판 필요"로 멈춤
# 종료 코드(모듈 그대로): 0 끝남·건너뜀 · 3 앞 모듈 결과 없음 · 4 PostgreSQL 없음 · 75 실행 중(잠금)·마감 · 그 밖 = 실패
#   night는 각 단계의 75(마감·잠금)를 실패로 안 치고 다음 단계로(옛 rag-nightly.service — S6b부터 data-pipeline-nightly.service — 동작 그대로) · 그 밖 실패는 그 코드로 바로 멈춤
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
# 서버 설정은 코드 폴더 밖 $SERVER_ENV_DIR/settings.yaml(전체 덮어쓰기에 안 지워짐, env-guide.md) — compose 치환 값은 셸 env로(--env-file 없음)
. deploy/host/scripts/settings_env.sh && load_settings || exit $?   # S7e1 — 컨테이너는 같은 파일을 붙여 읽음(compose x-settings)
mod=${1:?parse|structure|load|all|night|scheduled}; shift || true
# scheduled(pl-32, 사용자 10-30) = systemd 타이머가 5분마다 부름 — settings.yaml ops.nightly.time(NIGHTLY_TIME, HH:MM)이
# 비면 조용히 끝(새벽 배치 없음), 지금이 그 시각부터 5분 안이면 night로 이어감(이미지 확인 전 — 5분마다 도는 몫을 가볍게). 켬/끔과 시각은 이 칸 하나(옛 NIGHTLY_ENABLED·고정 01:00 대신).
if [ "$mod" = "scheduled" ]; then
  t=$(printf '%s' "${NIGHTLY_TIME:-}" | tr -d '[:space:]')   # 공백만이면 비움과 같음(설정 모델과 같게)
  [ -z "$t" ] && exit 0
  case "$t" in
    [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
    *) echo "[trigger] NIGHTLY_TIME 형식 오류(HH:MM이어야 함) — 새벽 배치 안 돎" >&2; exit 2 ;;
  esac
  now=$(date +%H:%M)
  d=$(( (10#${now%%:*} * 60 + 10#${now#*:}) - (10#${t%%:*} * 60 + 10#${t#*:}) ))
  d=$(( (d + 1440) % 1440 ))   # 자정을 넘는 창(23:58 → 00:02)
  if [ "$d" -ge 5 ]; then exit 0; fi
  mod=night
fi
. deploy/host/scripts/image_vars.sh   # S6b — compose.pipeline.yml은 두 이미지 변수를 다 치환하므로 둘 다 확인(옛 변수만 있으면 종료 코드 2)
need_image pipeline || exit 2; need_image mcp || exit 2
code_dir_default DATA_PIPELINE_IMAGE   # op-06 — 실행 이미지면 이 코드 폴더 루트를 /app/deploy에(CODE_DIR 없을 때)
DC="${DOCKER:-docker} compose -f deploy/host/compose/compose.pipeline.yml"   # DOCKER(settings ops.host.docker) — podman이면 podman compose(사용자 10-30 검토 B4)
[ -n "${CODE_DIR:-}" ] && DC="$DC -f deploy/host/compose/compose.code.yml"   # op-06 — 개발 서버(실행 이미지): 코드 폴더를 /app/deploy에
run() {
  echo "[trigger] $(date '+%F %T') $1 시작"
  $DC run --rm "$1" "$1" "${@:2}"; rc=$?          # compose run의 인자는 command를 덮음 → 모듈 이름을 다시 줌
  echo "[trigger] $(date '+%F %T') $1 끝 (종료 코드 $rc)"
  return $rc
}
if [ "$mod" = "all" ]; then
  for m in parse publish structure load; do run "$m" || exit $?; done
elif [ "$mod" = "night" ]; then
  modules=${NIGHTLY_MODULES:-"parse publish structure load"}
  publish_on=${NIGHTLY_PUBLISH:-1}
  for m in $modules; do
    if [ "$m" = "publish" ] && [ "$publish_on" != 1 ]; then
      echo "[trigger] $(date '+%F %T') publish 건너뜀(NIGHTLY_PUBLISH=0)"
      continue
    fi
    if [ "$m" = "parse" ]; then
      args=()
      [ -n "${PARSE_DEADLINE:-}" ] && args+=(--deadline "$PARSE_DEADLINE")
      args+=(--max-new "${NIGHTLY_MAX_NEW:-2000}")   # night 전용 안전 상한(기본 2000, settings.yaml ops.nightly.max_new) — 인터랙티브 PARSE_MAX_NEW와 분리
      run parse "${args[@]}"
    else
      run "$m"
    fi
    rc=$?
    if [ "$rc" -eq 75 ]; then
      echo "[trigger] $(date '+%F %T') $m 건너뜀(종료 코드 75 — 마감·잠금) — 다음 모듈로"   # RV5 — 75 건너뜀 사유 한 줄(batch.log 집계)
    elif [ "$rc" -ne 0 ]; then
      exit "$rc"
    fi
  done
else
  run "$mod" "$@"
fi
