#!/bin/bash
# 문서 파이프라인 진입점(구조 개편 v4 단계5, 10-13 — 옛 dev/를 deploy/로) — 실행 전 점검(자원·연결·쓰기 권한·
# 시간대) 후 명령 실행. 코드는 /app/deploy/data_pipeline(PYTHONPATH=/app/deploy, Dockerfile) — 전부 `python -m
# data_pipeline.<패키지>.<이름>`으로 부른다(운영자가 쓰는 명령 이름 자체는 그대로).
#   docker run --rm --init -v <settings.yaml>:/etc/rag/settings.yaml:ro,z -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=<dev|prd> \
#     -v <원본>:/data/docs:ro -v <결과>:/app/output data-pipeline:<버전> <명령>   (S7e1·S7e2 — 옛 --env-file pipeline.env 대신 설정 파일 하나)
# 명령: help · check · resources · services · check-modules · tool <이름> [인자] · mcp · dedup · prepare ·
#       ask --q … · test-stack  (night·run-stack·full·structure·load는 11-01에 지움 — 서버 입구는 run_docs 하나, 사용자 10-31)
#   tool <이름> = cli/<이름>.py 하나를 바로 돌림(rdb_discover·check_env·index 등 — run_tool.sh가 쓰는 자리)
#     옛 형태 `tool cli/<이름>.py`도 이번 판까지는 받아 줌(경고 후 번역) — 다음 판부터 이름만.
#   모듈(트리거 1회): parse(= 가져오기(폴더·s3://, PARSE_SOURCE) → dedup → prepare → 파싱·대표 결과, RUN_MODE=test면 형식별 표본) · structure(구조화·임베딩) · load(PostgreSQL) · publish(대표 결과 .md Object Storage 업로드 + EDW 메타, SI39 — cli/publish_parse.py --apply) — docs/architecture.md
#   migrate up|stamp|current|check [--target search|all] [--schema S] [--dim N|--bundle B] = pgvector 우리 스키마 판 관리(S8a — Alembic,
#     common.store.db.dbtool) — data-pipeline 이미지만, up·stamp는 load와 같은 잠금(current·check는 읽기만 — 잠금 없음). 서버 절차 docs/operations/release-and-patch.md §5-5
#   show-stack·show-sources = 지금 엔진 구성·원천 목록(파일 — 서버·PC 같음, 바꾸기 = 파일 고쳐 오버레이 패치 · 사용자 11-01: 판 표·set-stack·
#     set-sources 없앰) — show-sources는 data-pipeline만, show-stack은 두 이미지. docs/architecture/pipeline_stack.md
#   S6b(D-020) — 이미지 2개: RAG_MODULE마다 쓸 수 있는 명령이 다름(아래 case가 거름):
#     pipeline(data-pipeline — 옛 data-parsing+data-structure, 두 이미지가 받던 명령의 합 + full(S6c))=parse·dedup·prepare·publish·show-stack·show-sources·idle·migrate ·
#     mcp(mcp-server — 옛 data-retrieval)=mcp·ask·test-stack·show-stack · 공통(모든 이미지) = help·check·resources·services·
#     check-modules·tool·selftest(S9 — 서버 반입 시험 /app/deploy/tests/server를 파일마다, 다른 이미지(RAG_MODULE) 폴더 사례·다른 이미지 패키지가 없어서만 실패한 사례는 SKIP,
#     서드파티 패키지가 없으면 FAIL(I2c) — 반입 판정은 /app/docker/selftest_gate.sh)·smoke(10-14 — --src(기본 DOC_DIR) 실문서 폴더를
#     이 이미지에 있는 모듈로 실제 돌려 사람이 읽는 요약, 실문서 투입 전 와이어링 점검 — find_spec으로 없는 단계는 자동 SKIP)
set -euo pipefail
cd /app

preflight() {
  echo "[점검] $(date '+%F %T %Z') · 시간대 ${TZ:-?} · 사용자 $(id -un)"
  python -m common.core.resources
  [ -w /app/output ] || { echo "[오류] /app/output 쓰기 불가 — -v <결과폴더>:/app/output 와 그 폴더 소유자(UID 10001) 확인"; exit 2; }
  [ -z "${DOC_DIR:-}" ] || [ -d "$DOC_DIR" ] || echo "[경고] 원본 폴더 ${DOC_DIR} 없음 — -v <원본>:${DOC_DIR}:ro"   # mcp 이미지는 DOC_DIR 없음
  if [ -n "${PG_HOST:-}" ] && { [ "$PG_HOST" = "127.0.0.1" ] || [ "$PG_HOST" = "localhost" ]; } && [ "${NETWORK_HOST:-0}" != "1" ]; then
    echo "[경고] 컨테이너 안의 PG_HOST=$PG_HOST 는 컨테이너 자신 — 호스트의 PostgreSQL이면 --network host(+NETWORK_HOST=1) 또는 PG_HOST=<서버 IP>/host.docker.internal"
  fi
  [ -n "${PG_HOST:-}" ] || echo "[안내] PG_HOST 없음 — 컨테이너 안에서는 docker ps로 찾을 수 없으므로 PostgreSQL 적재를 하려면 PG_HOST·PG_PORT·PG_PASSWORD를 지정(없으면 로컬 묶음만)"
  df -h /app/output | tail -1 | awk '{print "[디스크] /app/output 남은 공간 " $4}'
}

# 같은 결과 폴더에 두 작업이 동시에 쓰지 않게(cron 겹침·사람이 두 번 실행) — 잡혀 있으면 바로 끝냄
#   종료 코드 75 = 이미 실행 중. exec로 바꿔 띄워 docker stop 신호가 파이프라인까지 그대로 감(--init 권장)
locked() { echo "[잠금] /app/output/.pipeline.lock (이미 실행 중이면 종료 코드 75로 바로 끝남)"; exec flock -n -E 75 /app/output/.pipeline.lock "$@"; }

# 단계5(10-13, 이번 판까지만) — `tool` 인자로 옛 'cli/<이름>.py' 형태가 오면 경고 뒤 모듈 이름만 남김.
legacy_tool_name() {
  case "$1" in
    cli/*.py) echo "[경고] 옛 형태 'cli/<이름>.py'는 이번 판까지만 지원 — 다음부터 이름만(예: score_gold)" >&2; n=${1#cli/}; echo "${n%.py}" ;;
    *.py)     echo "${1%.py}" ;;
    *)        echo "$1" ;;
  esac
}

cmd="${1:-help}"; shift || true
# 이미지마다 자기 앱만 들어 있음(S6b D-020 — RAG_MODULE pipeline·mcp, 사용자 10-27) — 없는 앱의 명령은 바로 거부(종료 코드 64)
case "${RAG_MODULE:-}:$cmd" in
  # 옛 parse·structure 이미지가 거르던 명령의 교집합만 거른다(합친 이미지 = 두 이미지가 받던 명령의 합). full·night·structure·load는 11-01에 지움.
  pipeline:mcp|pipeline:ask|pipeline:test-stack)
    echo "[오류] '$cmd'는 이 이미지(data-pipeline)에 없음 — 검색/질문(mcp·ask·test-stack)은 mcp-server. 이 이미지는 parse·dedup·prepare·publish·show-stack·show-sources·idle·migrate"; exit 64;;
  mcp:parse|mcp:dedup|mcp:prepare|mcp:publish|mcp:idle|mcp:migrate|mcp:show-sources)
    echo "[오류] '$cmd'는 이 이미지(mcp-server)에 없음 — 파싱·구조화·적재·판 관리(migrate)·show-sources는 data-pipeline. 이 이미지는 mcp·ask·test-stack·show-stack만"; exit 64;;
esac
# S7a(D-028 ②, 사용자 10-27) — 실행 환경(RUN_ENV) 없이는 앱 명령을 시작하지 않음. 이미지 ENV에는 넣지 않는다(서버가 dev·prd를
# 정해 compose environment로 줌 — refactor.md C-34). 시험·점검 명령(help·selftest·check·check-modules·resources·services·tool check_env)은 뺀다
# (tool ping_models는 외부 모델을 부르므로 빼지 않음 — RUN_ENV가 외부 모델 허용을 정함, S7a2).
# S7e2(VS7e1 R-9·U-1·C-45 ⑤, 사용자 10-28) — python 한 번(common.config.boot)으로: ① 관문(--gate — 서버면 설정 파일을 못 읽거나 이 이미지 절
# 검증에 실패해도 이유만 찍고 종료 2) ② 이 셸이 쓰는 칸(DOC_DIR·DOC_DIR_PREPARED·PARSE_SOURCE·PG_HOST — settings.yaml, 비면 이미지 기본값(common/config/settings.py IMAGE_PATHS — op-09: 셸에는 기본값 없음)) ③ 라이브러리 env
# (settings.yaml ops.runtime.lib_env — 사용자 env는 안 덮고 이미지 ENV 값(/app/docker/image_env.txt)은 덮음). 값은 출력하지 않는다(eval만).
gate=1
case "$cmd" in
  help|selftest|check|check-modules|resources|services) gate=0;;
  tool) case "${1:-}" in check_env|check_env.py|cli/check_env.py) gate=0;; esac;;
esac
shell_names=""
case "$cmd" in
  parse|dedup|prepare|publish|check|smoke|idle|migrate|show-stack|show-sources)
    shell_names="DOC_DIR DOC_DIR_PREPARED PARSE_SOURCE PG_HOST";;
esac
# 점검 명령(관문 면제)은 설정 파일이 틀려도 돌아 원인을 보이게 — 내부 신호 SETTINGS_LENIENT=1(영구 다리가 서버에서도 경고만, 앱 명령은 안 줌)
[ "$gate" = 1 ] || export SETTINGS_LENIENT=1
if [ "$cmd" != help ]; then
  gate_arg=""
  [ "$gate" = 0 ] || gate_arg=--gate
  # shellcheck disable=SC2086 — 이름 목록(공백 나눔)
  boot_out=$(python -m common.config.boot $gate_arg $shell_names) || exit 2
  eval "$boot_out"
fi
case "$cmd" in
  help)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//';;
  check)         preflight; python -m common.store.services;;
  resources)     python -m common.core.resources "$@";;
  services)      python -m common.store.services "$@";;
  check-modules) exec python -m common.check.check_modules "$@";;
  tool)
    name=$(legacy_tool_name "${1:?도구 이름(예: rdb_discover·check_env)}"); shift || true
    # C3(독립 검토 10-13) — 이름을 python -c 소스 문자열에 그대로 끼워 넣으면 코드 주입 경로가 됨. 모듈 이름 문법만 허용.
    [[ "$name" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "bad tool name"; exit 64; }
    # ping_models·os_put·check_modules는 common/check/(S3 — 옛 common_tools/cli/) — common.check를 맨 먼저(덧씌우기 live에 옛 사본이 남아도 새 것이 이김), 그다음 이 순서로 시도.
    # S4 — 단계 4 도구는 pipeline/로: check_env는 pipeline/, rdb_discover는 pipeline/extract/,
    # gen_roster·glossary_suggest는 pipeline/transform/structure/ (figure_review는 11-01에 지움) ·
    # (pipeline/eval/의 평가 도구와 mcp_server/cli/의 mcp_eval·search_checks는 11-01에 지움 — e2-10) ·
    # S6c(사용자 10-27, C-30 ①) — index(AD41 색인 빌더 — compose.pipeline.yml index_a·index_b의 `tool index build`)는 pipeline/load/(옛 data_structure/ —
    #   pre-refactor부터 찾는 목록에 없어 "모르는 도구"였음).
    # assets는 /app/docker/assets.py(파일로 실행 — `python /app/docker/assets.py install`, 저장소 자리 deploy/release/ — S6b), eval_research는 S5a 삭제.
    # 옛 `tool pipeline`(common_tools.cli.pipeline)은 pipeline.cli로. `패키지:이름,…`은 그 이름만 — S4 전에 tool로 부를 수 있던 것만
    # (pipeline 단계 모듈 run_all·dedup·stream 등을 preflight·잠금 없이 부르지 않게).
    # 이름은 sys.argv로 전달(소스 문자열에 끼워 넣지 않음). 찾기는 python 한 번에(VS3 R-7 — 전에는 패키지마다 프로세스 하나).
    [ "$name" = pipeline ] && name=cli
    TOOL_PKGS="common.check pipeline:check_env,cli pipeline.extract:rdb_discover pipeline.transform.structure:gen_roster,glossary_suggest pipeline.load:index"
    # shellcheck disable=SC2086
    mod=$(python -c "
import importlib.util, sys
for entry in sys.argv[2:]:
    pkg, _, names = entry.partition(':')
    if names and sys.argv[1] not in names.split(','):
        continue
    try:
        found = importlib.util.find_spec(pkg + '.' + sys.argv[1])
    except Exception:   # 이미지에 없는 패키지(중간 패키지가 없으면 ModuleNotFoundError) → 다음
        found = None
    if found:
        print(pkg + '.' + sys.argv[1])
        break
" "$name" $TOOL_PKGS 2>/dev/null) || mod=""
    [ -n "$mod" ] && exec python -m "$mod" "$@"
    echo "[tool] 모르는 도구: $name (${TOOL_PKGS// /·} 어디에도 없음)" >&2; exit 2;;
  mcp)        exec python -m mcp_server.main "$@";;        # 검색 MCP(deploy/host/compose/compose.mcp.yml) — 잠금 없음(읽기 전용)
  dedup)      preflight; exec python -m pipeline.extract.dedup --src "${DOC_DIR:?}" "$@";;
  prepare)    preflight; exec python -m pipeline.extract.prepare --src "${DOC_DIR:?}" --out "${DOC_DIR_PREPARED:?}" "$@";;
  # 모듈(트리거 1회 실행 — docs/architecture.md). 종료 코드: 0 끝남·건너뜀 · 3 앞 모듈 결과 없음 · 4 PostgreSQL 없음 · 75 실행 중·마감
  parse)
    preflight
    locked python -m pipeline.cli parse --source "${PARSE_SOURCE:-${DOC_DIR:?}}" --src "${DOC_DIR_PREPARED:?}" "$@";;
  migrate)    # S8a(5-4, 사용자 10-28 Q4) — pgvector 판 관리. up·stamp는 적재와 겹치지 않게 같은 잠금, 읽기만 하는 current·check는 잠금·
    # 쓰기 확인(preflight) 없이. 명령 낱말은 인자 어디에 있어도 찾는다(옵션 값은 건너뜀 — VS8a R-6: `migrate --target x check`)
    verb=""; skip=0
    for arg in "$@"; do
      if [ "$skip" = 1 ]; then skip=0; continue; fi
      case "$arg" in
        --target|--schema|--dim|--bundle|--pg-cases) skip=1;;
        -*) ;;
        *) verb="$arg"; break;;
      esac
    done
    case "$verb" in
      current|check) exec python -m common.store.db.dbtool "$@";;
      *)             preflight; locked python -m common.store.db.dbtool "$@";;
    esac;;
  publish)    # SI39 — 대표 결과(.md) Object Storage 업로드 + EDW AI.ParsingMeta 기록(원본은 올리지 않음) — 자동 스케줄 없음, 트리거 전용
    # publish --dry-run = 무엇을 올리고 쓸지 표만(쓰기 0) — 첫 publish 전에(사용자 10-30 검토 S3). 그 밖은 늘 --apply.
    if [ "${1:-}" = --dry-run ]; then shift; preflight; exec python -m pipeline.load.publish_parse_result "$@"; fi
    preflight; locked python -m pipeline.load.publish_parse_result --apply "$@";;
  ask|test-stack)   # S5(T-15) — 검색 명령은 mcp_server/cli/ask.py(옛 pipeline.cli ask·test-stack)
    preflight; exec python -m mcp_server.cli.ask "$cmd" "$@";;
  show-stack|show-sources|selftest|smoke)   # 실행 기록을 /app/output/logs에 씀 — mcp-server(/app/output:ro)에서는 안 됨(VS8b R-9 — data-pipeline 컨테이너에서)
    preflight; exec python -m pipeline.cli "$cmd" "$@";;
  # 11-01(pl-10 — trigger 서버 serve-trigger 지움) — 상주 컨테이너 data-pipeline-parse·data-pipeline-structure는 일을 하지 않고 떠 있기만 한다.
  # run_docs.py가 그 안에서 docker exec로 문서별 작업을 돌리고, MCP parse_document 작업 서비스(mcp_parse_service)도 그 안에 띄운다.
  idle)
    preflight
    exec sleep infinity;;
  *) echo "모르는 명령: $cmd (help 참고)"; exit 64;;
esac
