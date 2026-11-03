#!/bin/bash
# OP18 — 서버에서 cli 도구·판 관리를 돌리는 얇은 래퍼. 사용자 11-02 — 1회 job 컨테이너(compose run --rm)를 없애고 상주 컨테이너
#   data-pipeline-structure 안에서 이미지 시작 스크립트로 돈다(docker exec — image_vars.sh in_pipeline). 컨테이너가 안 떠 있으면 종료 코드 2.
#   bash deploy/host/scripts/run_tool.sh <도구 이름(.py 생략 가능)> [도구 인자…]   (코드 폴더 루트에서)
#     도구: rdb_discover·check_env·ping_models(엔트리포인트 `tool <이름>`) · migrate(pgvector 판 관리 — `migrate current|check|up|stamp …`)
#           · show-stack(엔진 구성 파일) · check(PG·모델 요약)
# 설정: settings.yaml 호스트 칸(trigger.sh와 같음 — settings_env.sh load_settings). 도구가 읽는 앱 설정 값은 컨테이너가 붙인 settings.yaml 그대로 —
#   값을 바꿀 때는 settings.yaml을 직접 고친다(옛 env 이름은 앱이 안 읽음 · 덮기 파일 도구는 PC 전용 — S7e3, 사용자 10-28).
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
. deploy/host/scripts/settings_env.sh && load_settings || exit $?   # DOCKER(셸 env > ops.host.docker > podman — op-10)
. deploy/host/scripts/image_vars.sh

tool=${1:?도구 이름 — 예: check_env·migrate·show-stack}; shift || true
tool=${tool%.py}
case "$tool" in
  rdb_discover|check_env|ping_models) set -- tool "$tool" "$@" ;;   # ping_models = 모델 주소 연결 점검(설치 점검 — 사용자 10-30)
  migrate|show-stack|check) set -- "$tool" "$@" ;;
  *) echo "[run_tool] 모르는 도구: $tool — rdb_discover·check_env·ping_models·migrate·show-stack·check 중 하나" >&2; exit 2 ;;
esac

echo "[run_tool] $(date '+%F %T') $tool 시작(data-pipeline-structure 안에서)"
in_pipeline data-pipeline-structure "$@"; rc=$?
echo "[run_tool] $(date '+%F %T') $tool 끝 (종료 코드 $rc)"
exit $rc
