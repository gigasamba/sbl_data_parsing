#!/bin/bash
# 파이프라인 단계·도구 하나를 상주 파이프라인 컨테이너(settings.yaml ops.host.pipeline_container) 안에서 돌린다(docker exec). 새벽 배치는 nightly_batch.sh.
#   bash deploy/host/scripts/pipe_exec.sh <도구 이름(.py 생략 가능)> [도구 인자…]   (코드 폴더 루트에서)
#     단계: parse(원천 → <결과 폴더>/parse/_rep) · publish(대표 결과(.md) Object Storage 업로드 + EDW 메타 · --dry-run은 쓰기 0)
#     도구: rdb_discover·check_env·ping_models(엔트리포인트 `tool <이름>`) · migrate(pgvector 판 관리 — `migrate current|check|up|stamp …`)
#           · show-stack(엔진 구성 파일) · check(PG·모델 요약)
# 종료 코드: 그 명령 그대로 · 모르는 도구·컨테이너가 안 떠 있음·settings.yaml 없음은 2. 앱 설정 값은 컨테이너가 붙인 settings.yaml 그대로.
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # DOCKER·PIPE_CONTAINER

tool=${1:?도구 이름 — 예: parse·publish·check_env·migrate·show-stack}; shift || true
tool=${tool%.py}
case "$tool" in
  rdb_discover|check_env|ping_models) set -- tool "$tool" "$@" ;;   # ping_models = 모델 주소 연결 점검(설치 점검)
  parse|publish|migrate|show-stack|check) set -- "$tool" "$@" ;;
  *) echo "[pipe_exec] 모르는 도구: $tool — parse·publish·rdb_discover·check_env·ping_models·migrate·show-stack·check 중 하나" >&2; exit 2 ;;
esac

c=${PIPE_CONTAINER:-data-pipeline}
if [ "${RUN_ENV:-}" = dev ] && [ -z "${PIPE_CONTAINER:-}" ]; then
  echo "[pipe_exec] dev 벌은 settings.yaml ops.host.pipeline_container(data-pipeline-<n>)를 채울 것" >&2; exit 2
fi
# shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
if [ "$($DOCKER inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != true ]; then
  echo "[오류] 상주 컨테이너 $c가 떠 있지 않음 — 먼저 띄울 것: \`bash deploy/host/scripts/host_ctl.sh up -d $c\`" >&2
  exit 2
fi
tty=()
[ -t 0 ] && [ -t 1 ] && tty=(-it)   # 터미널이면 Ctrl-C가 컨테이너 안 작업까지 감
echo "[pipe_exec] $(date '+%F %T') $tool 시작($c 안에서)"
# 시작 스크립트: 구운 이미지는 entrypoint.sh, 실행 이미지(*-runtime)는 runtime_entry.sh
# shellcheck disable=SC2016,SC2086
$DOCKER exec ${tty[@]+"${tty[@]}"} "$c" bash -c 'e=/opt/sbl/docker/entrypoint.sh; [ -f "$e" ] || e=/opt/sbl/docker/runtime_entry.sh; exec bash "$e" "$@"' _ "$@"
rc=$?
echo "[pipe_exec] $(date '+%F %T') $tool 끝 (종료 코드 $rc)"
exit $rc
