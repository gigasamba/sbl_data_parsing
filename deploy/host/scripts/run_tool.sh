#!/bin/bash
# OP18 — 서버에서 cli 도구를 맞는 이미지로 돌리는 얇은 래퍼. 구조 개편 v4 단계5(10-13)부터 entrypoint.sh의
#   `tool <이름>` 명령으로(엔트리포인트가 `python -m <패키지>.<이름>`(S3 — common.check를 먼저 · S4부터 pipeline·pipeline.extract·… — S6a에 common_tools.cli·evaluation 빠짐, 11-01 pipeline.eval·mcp_server.cli 평가 도구 지움 — e2-10)으로 번역 — --entrypoint python 덮어쓰기 불필요).
#   bash deploy/host/scripts/run_tool.sh <도구 이름(.py 생략 가능)> [도구 인자…]   (코드 폴더 루트에서 — S6b, 옛 docker/run_tool.sh)
#   S6b(D-020) — rdb_discover·check_env·ping_models → load 서비스(data-pipeline·DATA_PIPELINE_IMAGE)
#   GOLD_DIR(settings.yaml ops.pipeline_host.gold_dir)에 해당하는 서버 폴더가 있으면 자동으로 /data/gold:ro 읽기 전용 연결 — 컨테이너 안 앱은 앱 칸
#   pipeline.paths.gold_dir가 비었으면 /data/gold를 읽음(pipeline.config.gold_dir — 옛 `-e GOLD_DIR=/data/gold` 자리, S7e2·S7e3 B-3: migrate는 서버 env의
#   GOLD_DIR를 호스트 칸에만 옮김. 서버 settings.yaml에 앱 칸을 적으면 그 값이 이김 — 비워 둠)
# 설정: settings.yaml 호스트 칸(trigger.sh와 같음 — settings_env.sh load_settings, S7e1) · DATA_PIPELINE_IMAGE · MCP_SERVER_IMAGE(image_vars.sh — 옛 이미지 변수만 있으면 멈춤)
#   · PATCH_CODE(셸 env에 있으면 compose.patch.yml도 덧붙임, image-patch-process §2-1 — 옛처럼 부른 쪽 셸 env만 — settings.yaml ops.host.patch_code는 compose 마운트 원본으로만)
#   · 도구가 읽는 앱 설정 값을 바꿀 때는 settings.yaml을 직접 고친다(`X=값 run_tool.sh …`의 옛 env 이름은 앱이 안 읽음 · 덮기 파일 도구는 PC 전용 — S7e3, 사용자 10-28)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트(S6b)
patch_given=${PATCH_CODE:-}             # 부른 쪽이 준 PATCH_CODE만(아래 load_settings 전 — 옛 동작 그대로)
. deploy/host/scripts/settings_env.sh && load_settings || exit $?   # S7e1 — settings.yaml 호스트 칸 → 셸 env(trigger.sh와 같음)
. deploy/host/scripts/image_vars.sh; code_dir_default DATA_PIPELINE_IMAGE   # op-06 — 실행 이미지면 코드 폴더 루트 · S6b — need_image(아래 — compose.pipeline.yml이 두 변수를 다 치환하므로 둘 다)
DC="${DOCKER:-docker} compose -f deploy/host/compose/compose.pipeline.yml"   # DOCKER(settings ops.host.docker) — podman이면 podman compose(사용자 10-30 검토 B4)
[ -n "${CODE_DIR:-}" ] && DC="$DC -f deploy/host/compose/compose.code.yml"   # op-06 — 개발 서버(실행 이미지): 코드 폴더를 /app/deploy에
[ -n "$patch_given" ] && [ -f deploy/host/compose/compose.patch.yml ] && DC="$DC -f deploy/host/compose/compose.patch.yml"

tool=${1:?도구 이름 — 예: rdb_discover·check_env}; shift || true
tool=${tool%.py}
case "$tool" in
  rdb_discover|check_env|ping_models) svc=load ;;   # data-pipeline(load 서비스 — common/* 의존성만, 자원 한도가 작음) · ping_models = 모델 주소 연결 점검(설치 점검 — 사용자 10-30)
  *) echo "[run_tool] 모르는 도구: $tool — rdb_discover·check_env·ping_models(data-pipeline 이미지) 중 하나" >&2; exit 2 ;;
esac

need_image pipeline || exit 2; need_image mcp || exit 2   # S6b — 옛 이미지 변수만 있으면 종료 코드 2

extra=()
if [ -n "${GOLD_DIR:-}" ] && [ -d "$GOLD_DIR" ]; then
  extra=(-v "$GOLD_DIR:/data/gold:ro")   # S7e2 — 컨테이너 안은 앱이 /data/gold를 기본으로 봄(pipeline.config.gold_dir — 옛 -e GOLD_DIR, 사용자 10-28)
fi

echo "[run_tool] $(date '+%F %T') $tool ($svc 서비스) 시작"
$DC run --rm ${extra[@]+"${extra[@]}"} "$svc" tool "$tool" "$@"; rc=$?   # 빈 배열 + set -u — bash 3.2에서도(CLAUDE.md §2)
echo "[run_tool] $(date '+%F %T') $tool 끝 (종료 코드 $rc)"
exit $rc
