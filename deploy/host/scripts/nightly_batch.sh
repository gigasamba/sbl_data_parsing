#!/bin/bash
# 새벽 배치 — systemd 타이머(data-pipeline-nightly)가 5분마다 부르고, NIGHTLY_TIME부터 5분 창 안일 때만 run_pipeline.py를 돌린다.
#   bash deploy/host/scripts/nightly_batch.sh scheduled [run_pipeline 인자…]   (코드 폴더 루트에서)
#   시작 시각·문서 수 상한·마감(settings.yaml ops.nightly.*) 중 하나라도 비면 조용히 끝. 앞에 applog 월 파티션 정리(실패해도 계속).
#   dev는 run_pipeline을 벌 컨테이너(ops.host.pipeline_container) 안에서 부른다.
# 종료 코드: run_pipeline 그대로(0 끝 · 1 실패 문서 · 75 마감·잠금 · 2 설정 문제 · 3 사전 점검·적재 확인 실패) · scheduled가 아니면 2
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # 컨테이너는 같은 파일을 붙여 읽음
mod=${1:?scheduled}; shift || true
if [ "$mod" = "scheduled" ]; then
  t=$(printf '%s' "${NIGHTLY_TIME:-}" | tr -d '[:space:]')   # 공백만이면 비움과 같음(설정 모델과 같게)
  n=$(printf '%s' "${NIGHTLY_MAX_DOCS:-}" | tr -d '[:space:]')
  dl=$(printf '%s' "${NIGHTLY_DEADLINE:-}" | tr -d '[:space:]')
  { [ -z "$t" ] || [ -z "$n" ] || [ -z "$dl" ]; } && exit 0
  for v in "$t" "$dl"; do
    case "$v" in
      [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
      *) echo "[nightly_batch] NIGHTLY_TIME·NIGHTLY_DEADLINE 형식 오류(HH:MM이어야 함) — 새벽 배치 안 돎" >&2; exit 2 ;;
    esac
  done
  case "$n" in
    '' | *[!0-9]* | 0) echo "[nightly_batch] NIGHTLY_MAX_DOCS는 1 이상 정수 — 새벽 배치 안 돎" >&2; exit 2 ;;
  esac
  # 마감이 시작 창(5분) 안이면 늦게 깬 타이머에서 run_pipeline이 마감을 다음 날로 읽음 — 거부
  g=$(( ((10#${dl%%:*} * 60 + 10#${dl#*:}) - (10#${t%%:*} * 60 + 10#${t#*:}) + 1440) % 1440 ))
  if [ "$g" -lt 5 ]; then echo "[nightly_batch] NIGHTLY_DEADLINE은 NIGHTLY_TIME보다 5분 넘게 뒤여야 함 — 새벽 배치 안 돎" >&2; exit 2; fi
  now=$(date +%H:%M)
  d=$(( (10#${now%%:*} * 60 + 10#${now#*:}) - (10#${t%%:*} * 60 + 10#${t#*:}) ))
  d=$(( (d + 1440) % 1440 ))   # 자정을 넘는 창(23:58 → 00:02)
  if [ "$d" -ge 5 ]; then exit 0; fi
  # 호스트 python(PyYAML·pymssql — refactor.md C-09)
  bash deploy/host/scripts/pipe_exec.sh migrate maintain --target applog \
    || echo "[nightly_batch] 경고 — applog 파티션 정리(migrate maintain --target applog) 실패, 배치는 계속" >&2
  echo "[nightly_batch] $(date '+%F %T') 새벽 배치 — run_pipeline.py 시작"
  # 건수 제한 없음(--limit 0 — 사람 실행 기본 run_limit을 덮음, 상한은 --max-docs). dev는 컨테이너 안에서 돈다(rn-05).
  rp=(deploy/host/scripts/run_pipeline.py --start-offset 0 --skip-done --max-docs "$n" --deadline "$dl" --limit 0 "$@")
  if [ "${RUN_ENV:-}" = dev ]; then
    ${DOCKER:-docker} exec -w "$APP_CODE_ROOT" "${PIPE_CONTAINER:?dev는 settings.yaml ops.host.pipeline_container 필요}" python3 "${rp[@]}"; rc=$?
  else
    python3 "${rp[@]}"; rc=$?
  fi
  echo "[nightly_batch] $(date '+%F %T') 새벽 배치 — run_pipeline.py 끝 (종료 코드 $rc)"
  exit $rc
fi
echo "[nightly_batch] 모르는 인자: $mod — scheduled만(parse·publish는 pipe_exec.sh — rn-06)" >&2
exit 2
