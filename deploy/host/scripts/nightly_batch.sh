#!/bin/bash
# 새벽 배치 — 새벽 배치 타이머(deploy/host/systemd/data-pipeline-nightly.*)가 부름. parse·publish 한 번 실행은 pipe_exec.sh.
#   bash deploy/host/scripts/nightly_batch.sh scheduled [run_pipeline 인자…]   (코드 폴더 루트에서)
#   scheduled = 타이머용 — NIGHTLY_TIME 시각(5분 창)에만 run_pipeline.py(문서별 flow — 서버 입구 하나)
#     run_pipeline 인자: --start-offset 0 --skip-done(EDW ParsingMeta에 끝난 문서는 건너뜀) --max-docs NIGHTLY_MAX_DOCS --deadline NIGHTLY_DEADLINE
#     (시작 시각·문서 수 상한·마감 시각 셋이 모두 있어야 돈다, 하나라도 비면 조용히 끝)
#   구조화·적재는 run_pipeline이 문서마다 부른다.
#   설정: settings.yaml(SETTINGS_FILE, 기본 <루트>/settings.yaml — 루트 = 코드 폴더의 부모)의
#     호스트 칸(이미지·RAG_OUT·DOC_SRC·자원·NIGHTLY_* 등)을 load_settings.sh load_settings가 셸 env로 — 이미 셸에 있는 이름은 그대로.
#     settings.yaml이 없으면 종료 코드 2.
# 종료 코드: run_pipeline 그대로(0 끝남·건너뜀·대상 0건 · 1 실패 문서 있음 · 75 실행 중(잠금)·마감 · 2 설정 문제) · scheduled가 아니면 2
#   겹침 잠금은 run_pipeline.py 안(flock batch_progress/run_pipeline.lock) — 사람이 이 스크립트 없이 run_pipeline을 돌려도 같은 잠금을 씀
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
# 서버 설정은 코드 폴더 밖 <루트>/settings.yaml(env-guide.md) — compose 치환 값은 셸 env로(--env-file 없음)
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # 컨테이너는 같은 파일을 붙여 읽음(compose x-settings)
mod=${1:?scheduled}; shift || true
# scheduled = systemd 타이머가 5분마다 부름 — settings.yaml ops.nightly.start_time·max_docs·stop_time
# (NIGHTLY_TIME·NIGHTLY_MAX_DOCS·NIGHTLY_DEADLINE) 중 하나라도 비면 조용히 끝(새벽 배치 없음), 지금이 시작 시각부터 5분 안이면 run_pipeline.py를 부름
# (이미지 확인 전 — 5분마다 도는 몫을 가볍게).
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
  # 새벽 배치 = run_pipeline을 바깥에서 부르는 것. 호스트 python(PyYAML·pymssql — refactor.md C-09)으로, 설정은 load_settings가 준 SETTINGS_FILE.
  echo "[nightly_batch] $(date '+%F %T') 새벽 배치 — run_pipeline.py 시작"
  python3 deploy/host/scripts/run_pipeline.py --start-offset 0 --skip-done --max-docs "$n" --deadline "$dl" "$@"; rc=$?
  echo "[nightly_batch] $(date '+%F %T') 새벽 배치 — run_pipeline.py 끝 (종료 코드 $rc)"
  exit $rc
fi
echo "[nightly_batch] 모르는 인자: $mod — scheduled만(parse·publish는 pipe_exec.sh — rn-06)" >&2
exit 2
