#!/bin/bash
# 상주 컨테이너 3개(data-pipeline·data-pipeline-mcp·mcp)를 부르는 compose 입구(사용자 11-03 — 옛 README `dc()` 셸 함수를 대신함).
#   bash deploy/host/scripts/dc.sh up -d data-pipeline data-pipeline-mcp mcp   (서비스 하나만도 됨 · ps·logs·down 등 compose 하위 명령 그대로)
#   bash deploy/host/scripts/dc.sh init --group <운영 그룹>   서버 폴더 처음 만들기(root — 여러 번 불러도 안전, 사용자 11-03)
#   bash deploy/host/scripts/dc.sh check                       배포 뒤 점검을 차례로 — 처음 실패에서 멈추고 마지막 한 줄로 판정(사용자 11-03)
# 하는 일: 코드 폴더 루트로 cd → settings.yaml을 셸 env로(settings_env.sh load_settings — 값은 출력 안 함) → 실행 이미지(*-runtime)면
#   이 코드 폴더를 CODE_DIR로(image_vars.sh code_dir_default — 파이프라인 이미지 기준, 개발 서버는 두 이미지가 함께 runtime) →
#   $DOCKER compose -f compose.pipeline.yml -f compose.pipeline-mcp.yml -f compose.mcp-server.yml [+ CODE_DIR면 compose.code*.yml] "$@".
# 프로젝트 이름은 compose 기본(첫 -f 파일의 폴더) — mcp_up.sh가 따로 부를 때와 같다(mcp_up.sh는 이 파일을 쓰지 않고 혼자 돎).
# 종료 코드: compose 그대로 · 설정을 못 읽으면 load_settings의 코드(2) · init/check는 아래 설명.
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트

# init — release-and-patch §8-3·server-guide §1-2가 손으로 만들던 서버 폴더를 한 번에(값·파일 내용은 찍지 않음).
#   폴더: <ENV>(10001:<그룹> 750 — data-pipeline이 /etc/rag/env로 읽음, 사용자 11-03) · <결과 폴더>(UID 10001:<그룹>, 2775 — setgid) · <결과 폴더>/mcp_parse/jobs(같음) · /srv/rag/code·/srv/rag/backup(700)
#   코드 폴더(이 스크립트의 폴더): chmod -R a+rX · /srv/rag/code/live 링크 → 이 폴더(없을 때만 — 있으면 가리키는 곳만 찍고 그대로)
#   settings.yaml: 코드 폴더의 settings.sample.yaml을 <ENV>/settings.yaml로 — **없을 때만**(있으면 절대 덮지 않음), 10001:<그룹> 640.
#   경로: SERVER_ENV_DIR(기본 /srv/rag/env) · RAG_OUT(셸 env > settings.yaml common.host.output_root > /srv/rag/output) ·
#         MCP_JOBS_DIR(셸 env > settings.yaml mcp.host.jobs_dir > <결과 폴더>/mcp_parse/jobs). DC_ROOT=<폴더>는 /srv/rag 대신 · DC_CODE=<폴더>는 live가 가리킬 코드 폴더(기본 이 코드 폴더) — 둘 다 시험용.
#   root가 아니면 거부(종료 코드 3 — 주인을 10001로 못 바꿔 반쯤 만든 폴더가 남지 않게). 단 DC_ROOT 시험은 주인 바꾸기만 건너뜀.
#   끝에 settings.yaml `required:` 중 빈 칸 이름(값은 안 찍음). 종료 코드: 0 · 2 인자 틀림 · 3 root 아님.
dc_init() {
  local group="" root=${DC_ROOT:-/srv/rag} test=${DC_ROOT:+1} env out jobs sf src
  while [ $# -gt 0 ]; do
    case "$1" in
      --group) group=${2:-}; shift 2 || true ;;
      *) echo "[dc init] 모르는 인자: $1 — 사용: dc.sh init --group <운영 그룹>" >&2; return 2 ;;
    esac
  done
  if [ "$(id -u)" != 0 ] && [ -z "$test" ]; then
    echo "[dc init] root로 실행할 것(sudo) — 폴더 주인을 UID 10001로 바꾼다" >&2; return 3
  fi
  [ -n "$group" ] || [ -n "$test" ] || { echo "[dc init] --group <운영 그룹> 필요(결과 폴더·settings.yaml 그룹 — 운영 계정이 고치고 지움)" >&2; return 2; }
  env=${SERVER_ENV_DIR:-$root/env}
  sf=$env/settings.yaml
  if [ -f "$sf" ] && [ -z "${RAG_OUT:-}${MCP_JOBS_DIR:-}" ]; then
    . deploy/host/scripts/settings_env.sh
    SETTINGS_FILE=$sf load_settings 2>/dev/null || echo "[dc init] settings.yaml에서 경로를 못 읽음 — 기본 경로를 씀"
  fi
  src="설정"; [ -n "${RAG_OUT:-}" ] || src="기본"
  out=${RAG_OUT:-$root/output}
  jobs=${MCP_JOBS_DIR:-$out/mcp_parse/jobs}
  echo "[dc init] 결과 폴더: $src 값 사용"
  _mk() {   # _mk <폴더> <권한> <주인 바꿈?>
    if [ -d "$1" ]; then echo "  있음  $1"; else mkdir -p "$1" && echo "  만듦  $1"; fi
    chmod "$2" "$1"
    if [ "$3" = 1 ]; then
      if [ -z "$test" ]; then chown "10001:$group" "$1"; else echo "  (시험 — 주인 바꾸기 건너뜀)"; fi
    fi
  }
  _mk "$env" 750 1   # 컨테이너 UID 10001이 열어야 함(EDW 사슬 사본 등 — /etc/rag/env:ro) · 그 밖 사용자는 못 봄(비밀 — settings.yaml 640)
  _mk "$out" 2775 1
  _mk "$jobs" 2775 1
  _mk "$root/code" 755 0
  _mk "$root/backup" 700 0
  # 코드 폴더(이 스크립트가 든 폴더 — zip을 푼 sbl_data_parsing-main·sbl_data_parsing-<판>)를 컨테이너 UID 10001이 읽게 · live 링크는 없을 때만
  if [ -z "$test" ]; then chmod -R a+rX . && echo "  권한  $(pwd) (a+rX)"; else echo "  (시험 — 코드 폴더 a+rX 건너뜀)"; fi
  if [ -e "$root/code/live" ] || [ -L "$root/code/live" ]; then
    echo "  있음  $root/code/live → $(readlink "$root/code/live" 2>/dev/null || echo '(링크 아님)') (옮기지 않음 — 판을 바꿀 때는 ln -sfn을 손으로)"
  else
    ln -s "${DC_CODE:-$(pwd)}" "$root/code/live" && echo "  만듦  $root/code/live → ${DC_CODE:-$(pwd)}"
  fi
  if [ -f "$sf" ]; then
    echo "  있음  $sf(덮지 않음)"
  else
    cp settings.sample.yaml "$sf" && chmod 640 "$sf" && echo "  만듦  $sf(settings.sample.yaml에서)"
    if [ -z "$test" ]; then chown "10001:$group" "$sf"; fi
  fi
  echo "[dc init] settings.yaml에서 아직 비어 있는 필수 칸(값을 채울 것 — 이름만):"
  PYTHONIOENCODING=utf-8 "${PY:-python3}" - "$sf" <<'PY' || echo "  (확인 못 함 — 호스트 python3에 PyYAML 필요)"
import sys

import yaml

def walk(d, path):
    for k, v in (d or {}).items():
        p = f"{path}.{k}"
        if isinstance(v, dict):
            yield from walk(v, p)
        elif v is None or v == "" or v == []:
            yield p

with open(sys.argv[1], encoding="utf-8") as f:
    doc = yaml.safe_load(f) or {}
names = list(walk(doc.get("required"), "required"))
print("\n".join(f"  - {n}" for n in names) if names else "  (없음)")
PY
  return 0
}

# check — 이미 있는 점검을 차례로(새 점검 없음). 처음 실패에서 멈추고 마지막 한 줄 "[dc check] 통과 — N개" 또는 "[dc check] 실패 — <단계>: <안내>".
#   ① check_env ② ping_models ③ migrate check --target all(run_tool.sh — 상주 data-pipeline 안) ④⑤ selftest_gate.sh(두 이미지 — "[판정] 통과" 줄로 판정)
#   ⑥ mcp_up.sh(/health). 검색 근거가 필요한 MCP 호출(mcp_smoke)은 넣지 않음 — 첫 적재 전에는 근거가 없음(§8-3 7 손 확인).
#   DC_FAKE=<명령>이면 각 단계를 `<명령> <단계 이름>`으로 바꿔 부른다(시험용 — 출력·종료 코드를 그대로 판정).
dc_check() {
  local n=0 name out rc
  _step() {   # _step <이름> <안내> <명령…>
    name=$1; local hint=$2; shift 2
    echo "[dc check] ── $name"
    if [ -n "${DC_FAKE:-}" ]; then set -- $DC_FAKE "$name"; fi   # shellcheck disable=SC2086 — 시험 명령은 낱말 나눔
    out=$("$@" 2>&1); rc=$?
    printf '%s\n' "$out"
    case "$name" in selftest*) printf '%s\n' "$out" | grep -q '^\[판정\] 통과' || rc=1 ;; esac
    # run_tool.sh(image_vars.sh in_pipeline)는 상주 컨테이너가 안 떠 있으면 종료 코드 2와 "떠 있지 않음" 안내 — 띄우지 않고 그 안내로 멈춤
    if [ $rc -eq 2 ] && printf '%s\n' "$out" | grep -q '떠 있지 않음'; then
      echo "[dc check] 실패 — $name: data-pipeline 컨테이너가 안 떠 있음 → dc.sh up -d data-pipeline"; return 1
    fi
    if [ $rc -ne 0 ]; then echo "[dc check] 실패 — $name: $hint"; return 1; fi
    n=$((n + 1))
  }
  local vol=()
  _vol() { vol=(); case "$1" in *-runtime:*) vol=(-v "$(pwd):/app/deploy:ro,z") ;; esac; }   # 실행 이미지(개발)는 이 코드 폴더를 붙임
  # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo podman)
  _step check_env "출력의 FAIL 줄 확인(server-guide §2)" bash deploy/host/scripts/run_tool.sh check_env || return 1
  _step ping_models "모델 주소·키(settings.yaml common.models) — 서버는 내부망 모델만" bash deploy/host/scripts/run_tool.sh ping_models || return 1
  _step "migrate check" "migrate up --target all · master load(§8-3 5)" bash deploy/host/scripts/run_tool.sh migrate check --target all || return 1
  _vol "${DATA_PIPELINE_IMAGE:-}"
  _step "selftest data-pipeline" "FAIL 줄의 시험 이름으로 원인 찾기(release-and-patch §3-3)" bash deploy/release/selftest_gate.sh $DOCKER run --rm ${vol[@]+"${vol[@]}"} "${DATA_PIPELINE_IMAGE:-}" selftest || return 1
  _vol "${MCP_SERVER_IMAGE:-}"
  _step "selftest mcp-server" "FAIL 줄의 시험 이름으로 원인 찾기(release-and-patch §3-3)" bash deploy/release/selftest_gate.sh $DOCKER run --rm ${vol[@]+"${vol[@]}"} "${MCP_SERVER_IMAGE:-}" selftest || return 1
  _step "검색 MCP" "\`$DOCKER logs mcp-server\` 마지막 줄 — mcp_up.sh가 다시 띄웠는데도 /health 응답 없음" bash deploy/host/scripts/mcp_up.sh || return 1
  echo "[dc check] 통과 — ${n}개"
}

case "${1:-}" in
  init) shift; dc_init "$@"; exit $? ;;
esac
. deploy/host/scripts/settings_env.sh && load_settings || exit $?
case "${1:-}" in
  check) dc_check; exit $? ;;
esac
. deploy/host/scripts/image_vars.sh && code_dir_default DATA_PIPELINE_IMAGE
C=deploy/host/compose
files="-f $C/compose.pipeline.yml -f $C/compose.pipeline-mcp.yml -f $C/compose.mcp-server.yml"
[ -n "${CODE_DIR:-}" ] && files="$files -f $C/compose.code.yml -f $C/compose.code.pipeline-mcp.yml -f $C/compose.code.mcp-server.yml"
# shellcheck disable=SC2086 — DOCKER(sudo podman처럼 두 낱말)·파일 인자는 낱말 나눔
exec $DOCKER compose $files "$@"
