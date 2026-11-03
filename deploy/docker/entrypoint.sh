#!/bin/bash
# 문서 파이프라인 진입점(구조 개편 v4 단계5, 10-13 — 옛 dev/를 deploy/로) — 실행 전 점검(자원·연결·쓰기 권한·
# 시간대) 후 명령 실행. 코드는 /app/deploy/data_pipeline(PYTHONPATH=/app/deploy, Dockerfile) — 전부 `python -m
# data_pipeline.<패키지>.<이름>`으로 부른다(운영자가 쓰는 명령 이름 자체는 그대로).
#   docker run --rm --init -v <settings.yaml>:/etc/rag/settings.yaml:ro,z -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=<dev|prd> \
#     -v <원본>:/data/docs:ro -v <결과>:/app/output data-pipeline:<버전> <명령>   (S7e1·S7e2 — 옛 --env-file pipeline.env 대신 설정 파일 하나)
# 명령: help · check · resources · services · check-modules · tool <이름> [인자] · mcp ·  (이미지 명령 dedup·prepare는 11-01에 지움 — parse가 안에서 부름)
#       ask --q …  (test-stack·night·run-stack·full·structure·load는 11-01에 지움 — 서버 입구는 run_docs 하나, 사용자 10-31)
#   tool <이름> = 고정 표의 도구 하나(check_env·ping_models·check_modules·cli·rdb_discover·gen_roster·glossary_suggest — run_tool.sh가 쓰는 자리)
#     이름만 받는다(옛 `tool cli/<이름>.py` 형태는 0.2.0에 지움 — 종료 64).
#   모듈(트리거 1회): parse(= 가져오기(폴더·rdb:csv, PARSE_SOURCE) → dedup → prepare → 파싱·대표 결과) · structure(구조화·임베딩) · load(PostgreSQL) · publish(대표 결과 .md Object Storage 업로드 + EDW 메타, SI39 — cli/publish_parse.py --apply) — docs/architecture.md
#   migrate up|stamp|current|check [--target search|all] [--schema S] [--dim N|--bundle B] = pgvector 우리 스키마 판 관리(S8a — Alembic,
#     common.store.db.dbtool) — data-pipeline 이미지만, up·stamp는 load와 같은 잠금(current·check는 읽기만 — 잠금 없음). 서버 절차 docs/operations/release-and-patch.md §5-5
#   show-stack = 지금 엔진 구성(파일 — 서버·PC 같음, 바꾸기 = 파일 고쳐 오버레이 패치 · 사용자 11-01: 판 표·set-stack 없앰 · 원천 목록 show-sources는 sources.json과 함께 지움) — 두 이미지. docs/architecture/pipeline_stack.md
#   S6b(D-020) — 이미지 2개: RAG_MODULE마다 쓸 수 있는 명령이 다름(아래 case가 거름):
#     pipeline(data-pipeline — 옛 data-parsing+data-structure, 두 이미지가 받던 명령의 합 + full(S6c))=parse·publish·show-stack·idle·migrate·parse-service ·
#     mcp(mcp-server — 옛 data-retrieval)=mcp·ask·show-stack · 공통(모든 이미지) = help·check·resources·services·
#     check-modules·tool·selftest(S9 — 서버 반입 시험 /app/deploy/tests/server를 파일마다, 다른 이미지(RAG_MODULE) 폴더 사례·다른 이미지 패키지가 없어서만 실패한 사례는 SKIP,
#     서드파티 패키지가 없으면 FAIL(I2c) — 반입 판정은 /app/docker/selftest_gate.sh)  (smoke는 11-01에 지움 — 실문서 점검은 run_docs·trigger.sh parse로)
set -euo pipefail
cd /app
umask 0002   # 그룹도 쓸 수 있게(파일 664·폴더 775) — 서버 운영 계정이 UID 10001이 쓴 결과를 고치고 지우게(결과 폴더 그룹·setgid는 server-guide §1-2)
# 실제로 도는 코드의 판·커밋(운영 고침 8 — [image] 줄의 커밋은 실행 이미지를 빌드한 커밋이라 코드만 바꾼 배포와 다름).
# 코드 폴더(실행 이미지 마운트)·구운 이미지 모두 /app/deploy/VERSION·CODE_COMMIT. CODE_COMMIT은 zip·git archive로 받을 때만 채워짐.
_code_ver=$(tr -d ' \r\n' < /app/deploy/VERSION 2>/dev/null || true)
_code_commit=$(tr -d '\r\n' < /app/deploy/CODE_COMMIT 2>/dev/null || true)
case "$_code_commit" in ''|'$Format'*) _code_commit="표시 없음(git clone — zip·git archive로 받으면 채워짐)" ;; *) _code_commit=${_code_commit##* } ;; esac
echo "[code] 판 ${_code_ver:-?} · 커밋 ${_code_commit}" >&2

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

cmd="${1:-help}"; shift || true
# 이미지마다 자기 앱만 들어 있음(S6b D-020 — RAG_MODULE pipeline·mcp, 사용자 10-27) — 없는 앱의 명령은 바로 거부(종료 코드 64)
case "${RAG_MODULE:-}:$cmd" in
  # 옛 parse·structure 이미지가 거르던 명령의 교집합만 거른다(합친 이미지 = 두 이미지가 받던 명령의 합). full·night·structure·load는 11-01에 지움.
  pipeline:mcp|pipeline:ask)
    echo "[오류] '$cmd'는 이 이미지(data-pipeline)에 없음 — 검색/질문(mcp·ask)은 mcp-server. 이 이미지는 parse·publish·show-stack·idle·migrate·parse-service"; exit 64;;
  mcp:parse|mcp:publish|mcp:idle|mcp:migrate|mcp:parse-service)
    echo "[오류] '$cmd'는 이 이미지(mcp-server)에 없음 — 파싱·구조화·적재·판 관리(migrate)는 data-pipeline. 이 이미지는 mcp·ask·show-stack만"; exit 64;;
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
  tool) case "${1:-}" in check_env) gate=0;; esac;;
esac
shell_names=""
case "$cmd" in
  parse|publish|check|idle|migrate|show-stack)
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
  check)         preflight; python -m common.check.checker services;;
  resources)     python -m common.core.resources "$@";;
  services)      python -m common.check.checker services "$@";;
  check-modules) exec python -m common.check.check_modules "$@";;
  tool)
    name="${1:?도구 이름(예: rdb_discover·check_env)}"; shift || true
    # C3(독립 검토 10-13) — 이름을 python -c 소스 문자열에 그대로 끼워 넣으면 코드 주입 경로가 됨. 모듈 이름 문법만 허용.
    [[ "$name" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "bad tool name"; exit 64; }
    # 0.2.0(pl-46) — 도구 이름 → 모듈 고정 표(옛 TOOL_PKGS 패키지 목록 찾기 대신). 표 밖 이름은 거부. 이 이미지에 없는 모듈(mcp-server의 pipeline)도 거부.
    case "$name" in
      check_env)        set -- common.check.checker env "$@";;
      ping_models)      set -- common.check.checker ping "$@";;
      check_modules)    set -- common.check.check_modules "$@";;
      cli|pipeline)     set -- pipeline.cli "$@";;
      rdb_discover)     set -- pipeline.extract.rdb_discover "$@";;
      gen_roster)       set -- pipeline.transform.structure.gen_roster "$@";;
      glossary_suggest) set -- pipeline.transform.structure.glossary_suggest "$@";;
      *) echo "[tool] 모르는 도구: $name (check_env·ping_models·check_modules·cli·rdb_discover·gen_roster·glossary_suggest 중 하나)" >&2; exit 2;;
    esac
    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1].rsplit('.', 1)[0]) else 2)" "$1" 2>/dev/null \
      || { echo "[tool] 이 이미지에 없는 도구: $name ($1)" >&2; exit 2; }
    exec python -m "$@";;
  mcp)        exec python -m mcp_server.main "$@";;        # 검색 MCP(deploy/host/compose/compose.mcp.yml) — 잠금 없음(읽기 전용)
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
  ask)   # S5(T-15) — 검색 명령은 mcp_server/cli/ask.py(test-stack은 11-01에 지움)
    preflight; exec python -m mcp_server.cli.ask ask "$@";;
  show-stack|selftest)   # 실행 기록을 /app/output/logs에 씀 — mcp-server(/app/output:ro)에서는 안 됨(VS8b R-9 — data-pipeline 컨테이너에서)
    preflight; exec python -m pipeline.cli "$cmd" "$@";;
  # 11-01(pl-10 — trigger 서버 serve-trigger 지움) — 상주 컨테이너 data-pipeline(11-03 — 옛 둘을 하나로)은 일을 하지 않고 떠 있기만 한다.
  # run_docs.py가 그 안에서 docker exec로 문서별 작업을 돌린다. MCP parse_document 작업 서비스는 위 parse-service(전용 컨테이너 data-pipeline-mcp — 여기에 띄우지 않음, 8766 겹침).
  parse-service)   # 11-03(사용자 — PRD rn-03) — MCP parse_document 작업 서비스(127.0.0.1:8766), 전용 상주 컨테이너 data-pipeline-mcp의 주 프로세스
    preflight; exec python -u -m pipeline.mcp_parse_service;;
  idle)
    preflight
    exec sleep infinity;;
  *) echo "모르는 명령: $cmd (help 참고)"; exit 64;;
esac
