#!/bin/bash
# 서버에서 파이프라인 단계(parse·publish)·cli 도구·판 관리를 한 번 돌리는 얇은 래퍼(새벽 배치는 nightly_batch.sh). 상주 컨테이너
#   data-pipeline 안에서 이미지 시작 스크립트로 돈다(docker exec — in_container.sh in_pipeline). 컨테이너가 안 떠 있으면 종료 코드 2.
#   bash deploy/host/scripts/pipe_exec.sh <도구 이름(.py 생략 가능)> [도구 인자…]   (코드 폴더 루트에서)
#     단계: parse(원천 → <결과 폴더>/parse/_rep) · publish(대표 결과(.md) Object Storage 업로드 + EDW 메타 · --dry-run은 쓰기 0)
#     도구: rdb_discover·check_env·ping_models(엔트리포인트 `tool <이름>`) · migrate(pgvector 판 관리 — `migrate current|check|up|stamp …`)
#           · show-stack(엔진 구성 파일) · check(PG·모델 요약)
# 종료 코드: 그 명령 그대로 · 모르는 도구·컨테이너가 안 떠 있음·settings.yaml 없음은 2.
# 설정: settings.yaml 호스트 칸(load_settings.sh load_settings). 도구가 읽는 앱 설정 값은 컨테이너가 붙인 settings.yaml 그대로 —
#   값을 바꿀 때는 settings.yaml을 직접 고친다(앱은 env 이름을 읽지 않음 · 덮기 파일 도구는 PC 전용).
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
. deploy/host/scripts/load_settings.sh && load_settings || exit $?   # DOCKER(셸 env > ops.host.container_cli > podman)
. deploy/host/scripts/in_container.sh

tool=${1:?도구 이름 — 예: parse·publish·check_env·migrate·show-stack}; shift || true
tool=${tool%.py}
case "$tool" in
  rdb_discover|check_env|ping_models) set -- tool "$tool" "$@" ;;   # ping_models = 모델 주소 연결 점검(설치 점검)
  parse|publish|migrate|show-stack|check) set -- "$tool" "$@" ;;
  *) echo "[pipe_exec] 모르는 도구: $tool — parse·publish·rdb_discover·check_env·ping_models·migrate·show-stack·check 중 하나" >&2; exit 2 ;;
esac

echo "[pipe_exec] $(date '+%F %T') $tool 시작(data-pipeline 안에서)"
in_pipeline "$PIPELINE_CNAME" "$@"; rc=$?   # 컨테이너 이름 — load_settings(ops.containers.pipeline.pipeline_container_name + 벌 번호)
echo "[pipe_exec] $(date '+%F %T') $tool 끝 (종료 코드 $rc)"
exit $rc
