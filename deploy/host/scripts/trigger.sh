#!/bin/bash
# 모듈 트리거(1회 실행) — 개발 서버 시험과 새벽 배치 타이머(deploy/host/systemd/)가 부름.
#   bash deploy/host/scripts/trigger.sh parse|publish [모듈 인자…]   (코드 폴더 루트에서 — S6b, 옛 docker/trigger.sh)
#   publish(SI39) = 대표 결과(.md) Object Storage 업로드 + EDW 메타(publish_parse_result --apply)
#   scheduled = 타이머용 — NIGHTLY_TIME 시각(5분 창)에만 run_docs.py(문서별 flow — 서버 입구 하나, 사용자 10-31 "night = run_docs를 바깥에서 부르는 것")
#     run_docs 인자: --start-offset 0 --skip-done(EDW ParsingMeta에 끝난 문서는 건너뜀) --max-docs NIGHTLY_MAX_DOCS --deadline NIGHTLY_DEADLINE
#     (사용자 11-02 — 시작 시각·문서 수 상한·마감 시각 셋이 모두 있어야 돈다, 하나라도 비면 조용히 끝)
#   (11-01 지움: night(NIGHTLY_MODULES 순서 배치)·structure·load·all — 옛 1회 job 배치 입구. 구조화·적재는 run_docs가 문서마다 부름)
#   설정(S7e1 — 사용자 10-27 Q3·Q5): settings.yaml(SETTINGS_FILE, 기본 $SERVER_ENV_DIR/settings.yaml — SERVER_ENV_DIR 기본 배치 /srv/rag/env)의
#     호스트 칸(이미지·RAG_OUT·DOC_SRC·자원·NIGHTLY_*·PARSE_DEADLINE 등)을 settings_env.sh load_settings가 셸 env로 — 이미 셸에 있는 이름은 그대로.
#     옛 ENV_FILE(pipeline.env)은 읽지 않는다(settings.yaml이 없으면 종료 코드 2).
#   parse·publish는 상주 data-pipeline 컨테이너 안에서 돈다(docker exec — 사용자 11-02, 1회 job 컨테이너 없음: parse는 data-pipeline-parse,
#     publish는 data-pipeline-structure). 컨테이너가 안 떠 있으면 종료 코드 2.
# 종료 코드: 모듈·run_docs 그대로(0 끝남·건너뜀·대상 0건 · 1 실패 문서 있음 · 75 실행 중(잠금)·마감 · 2 설정 문제 — run_docs는 pl-18)
#   겹침 잠금은 run_docs.py 안(flock batch_progress/run_docs.lock) — 사람이 trigger 없이 run_docs를 돌려도 같은 잠금을 씀
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
# 서버 설정은 코드 폴더 밖 $SERVER_ENV_DIR/settings.yaml(전체 덮어쓰기에 안 지워짐, env-guide.md) — compose 치환 값은 셸 env로(--env-file 없음)
. deploy/host/scripts/settings_env.sh && load_settings || exit $?   # S7e1 — 컨테이너는 같은 파일을 붙여 읽음(compose x-settings)
mod=${1:?parse|publish|scheduled}; shift || true
# scheduled(pl-32, 사용자 10-30 · 11-02) = systemd 타이머가 5분마다 부름 — settings.yaml ops.nightly.time·max_docs·deadline
# (NIGHTLY_TIME·NIGHTLY_MAX_DOCS·NIGHTLY_DEADLINE) 중 하나라도 비면 조용히 끝(새벽 배치 없음), 지금이 시작 시각부터 5분 안이면 run_docs.py를 부름
# (이미지 확인 전 — 5분마다 도는 몫을 가볍게).
if [ "$mod" = "scheduled" ]; then
  t=$(printf '%s' "${NIGHTLY_TIME:-}" | tr -d '[:space:]')   # 공백만이면 비움과 같음(설정 모델과 같게)
  n=$(printf '%s' "${NIGHTLY_MAX_DOCS:-}" | tr -d '[:space:]')
  dl=$(printf '%s' "${NIGHTLY_DEADLINE:-}" | tr -d '[:space:]')
  { [ -z "$t" ] || [ -z "$n" ] || [ -z "$dl" ]; } && exit 0
  for v in "$t" "$dl"; do
    case "$v" in
      [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
      *) echo "[trigger] NIGHTLY_TIME·NIGHTLY_DEADLINE 형식 오류(HH:MM이어야 함) — 새벽 배치 안 돎" >&2; exit 2 ;;
    esac
  done
  case "$n" in
    '' | *[!0-9]* | 0) echo "[trigger] NIGHTLY_MAX_DOCS는 1 이상 정수 — 새벽 배치 안 돎" >&2; exit 2 ;;
  esac
  # 마감이 시작 창(5분) 안이면 늦게 깬 타이머에서 run_docs가 마감을 다음 날로 읽음 — 거부(리뷰 11-02)
  g=$(( ((10#${dl%%:*} * 60 + 10#${dl#*:}) - (10#${t%%:*} * 60 + 10#${t#*:}) + 1440) % 1440 ))
  if [ "$g" -lt 5 ]; then echo "[trigger] NIGHTLY_DEADLINE은 NIGHTLY_TIME보다 5분 넘게 뒤여야 함 — 새벽 배치 안 돎" >&2; exit 2; fi
  now=$(date +%H:%M)
  d=$(( (10#${now%%:*} * 60 + 10#${now#*:}) - (10#${t%%:*} * 60 + 10#${t#*:}) ))
  d=$(( (d + 1440) % 1440 ))   # 자정을 넘는 창(23:58 → 00:02)
  if [ "$d" -ge 5 ]; then exit 0; fi
  # 11-01(사용자 10-31) — 새벽 배치 = run_docs를 바깥에서 부르는 것. 호스트 python(PyYAML·pymssql — refactor.md C-09)으로, 설정은 load_settings가 준 SETTINGS_FILE.
  echo "[trigger] $(date '+%F %T') 새벽 배치 — run_docs.py 시작"
  python3 deploy/host/scripts/run_docs.py --start-offset 0 --skip-done --max-docs "$n" --deadline "$dl" "$@"; rc=$?
  echo "[trigger] $(date '+%F %T') 새벽 배치 — run_docs.py 끝 (종료 코드 $rc)"
  exit $rc
fi
case "$mod" in
  parse|publish) ;;
  *) echo "[trigger] 모르는 모듈: $mod — parse|publish|scheduled (night·structure·load·all은 11-01에 지움 — 서버 입구는 run_docs)" >&2; exit 2 ;;
esac
. deploy/host/scripts/image_vars.sh   # in_pipeline — 상주 컨테이너 안에서(사용자 11-02 — 1회 job 컨테이너 없음)
case "$mod" in
  parse) ctr=data-pipeline-parse ;;        # 원본 문서 폴더(/data/docs)가 붙은 상주 컨테이너
  *) ctr=data-pipeline-structure ;;
esac
echo "[trigger] $(date '+%F %T') $mod 시작($ctr 안에서)"
in_pipeline "$ctr" "$mod" "$@"; rc=$?
echo "[trigger] $(date '+%F %T') $mod 끝 (종료 코드 $rc)"
exit $rc
