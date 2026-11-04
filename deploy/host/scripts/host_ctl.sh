#!/bin/bash
# 상주 컨테이너 3개(data-pipeline·data-pipeline-mcp·mcp)를 부르는 compose 입구(사용자 11-03 — 옛 README `dc()` 셸 함수를 대신함).
#   bash deploy/host/scripts/host_ctl.sh up -d data-pipeline data-pipeline-mcp mcp   (서비스 하나만도 됨 · ps·logs·down 등 compose 하위 명령 그대로)
#   bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   서버 루트(이 코드 폴더의 부모 — op-13) 채우기(root — 여러 번 불러도 안전)
#   bash deploy/host/scripts/host_ctl.sh timers                      systemd 타이머(새벽 배치·MCP 살리기)를 이 코드 폴더 기준으로 설치·켬(root — op-13)
#   bash deploy/host/scripts/host_ctl.sh check                       배포 뒤 점검을 차례로 — 처음 실패에서 멈추고 마지막 한 줄로 판정(사용자 11-03)
# 하는 일: 코드 폴더 루트로 cd → settings.yaml을 셸 env로(load_settings.sh load_settings — 값은 출력 안 함) → 실행 이미지(*-runtime)면
#   이 코드 폴더를 CODE_DIR로(in_container.sh code_dir_default — 파이프라인 이미지 기준, 개발 서버는 두 이미지가 함께 runtime) →
#   $DOCKER compose -f compose.pipeline.yml -f compose.pipeline-mcp.yml -f compose.mcp-server.yml [+ CODE_DIR면 compose.code*.yml] "$@".
# 프로젝트 이름은 compose 기본(첫 -f 파일의 폴더) — mcp_keepalive.sh가 따로 부를 때와 같다(mcp_keepalive.sh는 이 파일을 쓰지 않고 혼자 돎).
# 종료 코드: compose 그대로 · 설정을 못 읽으면 load_settings의 코드(2) · init/check는 아래 설명.
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
if [ -n "${DC_ROOT:-}" ]; then RAG_ROOT=$DC_ROOT; fi   # 시험 루트(init) — load_settings.sh는 이미 있는 RAG_ROOT를 씀(결과 폴더 기본도 그 아래)
. deploy/host/scripts/load_settings.sh   # 루트 RAG_ROOT·load_settings 한 곳(값은 아래 load_settings에서)

# init — 서버 루트(op-13 — 이 코드 폴더의 부모)를 한 번에 채운다(값·파일 내용은 찍지 않음). 여러 번 불러도 안전.
#   폴더: <결과 폴더>(UID 10001:<그룹>, 2775 — setgid) · <결과 폴더>/_mcp_parse/jobs(같음) · <루트>/backup(700)
#   코드 폴더(이 스크립트의 폴더 — zip을 푼 sbl_data_parsing-<판>): chmod -R a+rX(컨테이너 UID 10001이 읽게)
#   settings.yaml: 코드 폴더의 settings.sample.yaml을 <루트>/settings.yaml로 — **없을 때만**(있으면 절대 덮지 않음), 10001:<그룹> 640.
#   edw_chain.yaml: resources/config/edw_chain.yaml을 <루트>/edw_chain.yaml로 — 같은 규칙(없을 때만, 10001:<그룹> 640). data-pipeline·mcp-server가 이 파일을
#     /etc/rag/edw_chain.yaml로 붙이므로(compose.pipeline.yml·compose.mcp-server.yml) 파일이 늘 있어야 함 — 앱은 ops.paths.edw_chain(적재·검색 같은 칸)을 적었을 때만 씀.
#   결과 폴더: RAG_OUT(셸 env > settings.yaml common.host.output_root > <루트>/output) · 작업 폴더: MCP_JOBS_DIR(셸 env > settings.yaml mcp.host.jobs_dir >
#     <결과 폴더>/_mcp_parse/jobs). DC_ROOT=<폴더>는 루트 대신(시험용 — 주인 바꾸기·코드 폴더 a+rX를 건너뜀).
#   root가 아니면 거부(종료 코드 3 — 주인을 10001로 못 바꿔 반쯤 만든 폴더가 남지 않게).
#   끝에 settings.yaml `required:` 중 빈 칸 이름(값은 안 찍음). 종료 코드: 0 · 2 인자 틀림 · 3 root 아님 · 4 edw_chain.yaml 자리에 폴더(init 전에 컨테이너를 띄움).
dc_init() {
  local group="" root=$RAG_ROOT test=${DC_ROOT:+1} out jobs sf chain
  while [ $# -gt 0 ]; do
    case "$1" in
      --group) group=${2:-}; shift 2 || true ;;
      *) echo "[host_ctl init] 모르는 인자: $1 — 사용: host_ctl.sh init --group <운영 그룹>" >&2; return 2 ;;
    esac
  done
  if [ "$(id -u)" != 0 ] && [ -z "$test" ]; then
    echo "[host_ctl init] root로 실행할 것(sudo) — 폴더 주인을 UID 10001로 바꾼다" >&2; return 3
  fi
  [ -n "$group" ] || [ -n "$test" ] || { echo "[host_ctl init] --group <운영 그룹> 필요(결과 폴더·settings.yaml 그룹 — 운영 계정이 고치고 지움)" >&2; return 2; }
  sf=$root/settings.yaml
  chain=$root/edw_chain.yaml
  if [ -f "$sf" ]; then   # 셸 env에 이미 있는 이름은 load_settings가 덮지 않음
    SETTINGS_FILE=$sf load_settings 2>/dev/null || echo "[host_ctl init] settings.yaml에서 경로를 못 읽음 — 기본 경로를 씀"
  fi
  out=${RAG_OUT:-$root/output}
  jobs=${MCP_JOBS_DIR:-$out/_mcp_parse/jobs}
  echo "[host_ctl init] 루트: $root"
  _mk() {   # _mk <폴더> <권한> <주인 바꿈?>
    if [ -d "$1" ]; then echo "  있음  $1"; else mkdir -p "$1" && echo "  만듦  $1"; fi
    chmod "$2" "$1"
    if [ "$3" = 1 ]; then
      if [ -z "$test" ]; then chown "10001:$group" "$1"; else echo "  (시험 — 주인 바꾸기 건너뜀)"; fi
    fi
  }
  _cp() {   # _cp <원본> <대상> — 대상이 없을 때만 복사(있으면 절대 덮지 않음), 640 · 10001:<그룹>
    if [ -e "$2" ]; then echo "  있음  $2(덮지 않음)"; return 0; fi
    cp "$1" "$2" && chmod 640 "$2" && echo "  만듦  $2($1에서)" || return 1
    if [ -z "$test" ]; then chown "10001:$group" "$2"; fi
  }
  _mk "$out" 2775 1
  _mk "$jobs" 2775 1
  _mk "$root/backup" 700 0
  if [ -z "$test" ]; then chmod -R a+rX . && echo "  권한  $(pwd) (a+rX)"; else echo "  (시험 — 코드 폴더 a+rX 건너뜀)"; fi
  _cp settings.sample.yaml "$sf"
  if [ -d "$chain" ]; then   # docker가 init 전에 띄운 마운트로 빈 폴더를 만든 경우 — 지우지 않고 멈춤(앱은 IsADirectoryError)
    echo "[host_ctl init] $chain 자리에 폴더가 있음 — 컨테이너를 init 전에 띄운 흔적: 비어 있으면 rmdir 뒤 다시(종료 4 — 지우지 않음)" >&2; return 4
  fi
  _cp resources/config/edw_chain.yaml "$chain"   # 앱은 ops.paths.edw_chain을 적었을 때만 씀
  echo "[host_ctl init] settings.yaml에서 아직 비어 있는 필수 칸(값을 채울 것 — 이름만):"
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

# check — 이미 있는 점검을 차례로(새 점검 없음). 처음 실패에서 멈추고 마지막 한 줄 "[host_ctl check] 통과 — N개" 또는 "[host_ctl check] 실패 — <단계>: <안내>".
#   ① check_env ② ping_models ③ migrate check --target all(pipe_exec.sh — 상주 data-pipeline 안) ④⑤ selftest_gate.sh(두 이미지 — "[판정] 통과" 줄로 판정)
#   ⑥ mcp_keepalive.sh(/health). 검색 근거가 필요한 MCP 호출(mcp_smoke)은 넣지 않음 — 첫 적재 전에는 근거가 없음(§8-3 7 손 확인).
#   DC_FAKE=<명령>이면 각 단계를 `<명령> <단계 이름>`으로 바꿔 부른다(시험용 — 출력·종료 코드를 그대로 판정).
dc_check() {
  local n=0 name out rc
  _step() {   # _step <이름> <안내> <명령…>
    name=$1; local hint=$2; shift 2
    echo "[host_ctl check] ── $name"
    if [ -n "${DC_FAKE:-}" ]; then set -- $DC_FAKE "$name"; fi   # shellcheck disable=SC2086 — 시험 명령은 낱말 나눔
    out=$("$@" 2>&1); rc=$?
    printf '%s\n' "$out"
    case "$name" in selftest*) printf '%s\n' "$out" | grep -q '^\[판정\] 통과' || rc=1 ;; esac
    # pipe_exec.sh(in_container.sh in_pipeline)는 상주 컨테이너가 안 떠 있으면 종료 코드 2와 "떠 있지 않음" 안내 — 띄우지 않고 그 안내로 멈춤
    if [ $rc -eq 2 ] && printf '%s\n' "$out" | grep -q '떠 있지 않음'; then
      echo "[host_ctl check] 실패 — $name: data-pipeline$NAME_SUFFIX 컨테이너가 안 떠 있음 → host_ctl.sh up -d data-pipeline"; return 1
    fi
    if [ $rc -ne 0 ]; then echo "[host_ctl check] 실패 — $name: $hint"; return 1; fi
    n=$((n + 1))
  }
  local vol=()
  _vol() { vol=(); case "$1" in *-runtime:*) vol=(-v "$(pwd):/app/deploy:ro,z") ;; esac; }   # 실행 이미지(개발)는 이 코드 폴더를 붙임
  # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo podman)
  _step check_env "출력의 FAIL 줄 확인(server-guide §2)" bash deploy/host/scripts/pipe_exec.sh check_env || return 1
  _step ping_models "모델 주소·키(settings.yaml common.models) — 서버는 내부망 모델만" bash deploy/host/scripts/pipe_exec.sh ping_models || return 1
  _step "migrate check" "migrate up --target all · master load(§8-3 5)" bash deploy/host/scripts/pipe_exec.sh migrate check --target all || return 1
  _vol "${DATA_PIPELINE_IMAGE:-}"
  _step "selftest data-pipeline" "FAIL 줄의 시험 이름으로 원인 찾기(release-and-patch §3-3)" bash deploy/release/selftest_gate.sh $DOCKER run --rm ${vol[@]+"${vol[@]}"} "${DATA_PIPELINE_IMAGE:-}" selftest || return 1
  _vol "${MCP_SERVER_IMAGE:-}"
  _step "selftest mcp-server" "FAIL 줄의 시험 이름으로 원인 찾기(release-and-patch §3-3)" bash deploy/release/selftest_gate.sh $DOCKER run --rm ${vol[@]+"${vol[@]}"} "${MCP_SERVER_IMAGE:-}" selftest || return 1
  _step "검색 MCP" "\`$DOCKER logs mcp-server$NAME_SUFFIX\` 마지막 줄 — mcp_keepalive.sh가 다시 띄웠는데도 /health 응답 없음" bash deploy/host/scripts/mcp_keepalive.sh || return 1
  echo "[host_ctl check] 통과 — ${n}개"
}

# timers — systemd 단위 4개(deploy/host/systemd — 새벽 배치·MCP 살리기)의 코드 폴더 자리(@CODE_DIR@)를 이 코드 폴더로 채워
#   /etc/systemd/system에 쓰고 두 타이머를 켠다(op-13). 새 루트에서 다시 부르면 그 루트로 바뀐다. root가 아니면 종료 3.
#   DC_UNIT_DIR=<폴더>는 /etc/systemd/system 대신(시험용 — root 확인·systemctl을 건너뜀).
dc_timers() {
  local dest=${DC_UNIT_DIR:-/etc/systemd/system} u n
  if [ "$(id -u)" != 0 ] && [ -z "${DC_UNIT_DIR:-}" ]; then
    echo "[host_ctl timers] root로 실행할 것(sudo) — /etc/systemd/system에 쓴다" >&2; return 3
  fi
  for u in deploy/host/systemd/*.service deploy/host/systemd/*.timer; do   # 여러 벌이면 단위 이름 끝에 -<instance>(타이머·서비스 짝이 같은 이름)
    n=$(basename "$u"); n="${n%.*}$NAME_SUFFIX.${n##*.}"
    sed "s#@CODE_DIR@#$(pwd)#g" "$u" > "$dest/$n" && echo "  씀  $dest/$n" || return 1
  done
  [ -n "${DC_UNIT_DIR:-}" ] && return 0
  systemctl daemon-reload && systemctl enable --now "data-pipeline-nightly$NAME_SUFFIX.timer" "mcp-server-keepalive$NAME_SUFFIX.timer"
}

case "${1:-}" in
  init) shift; dc_init "$@"; exit $? ;;
esac
load_settings || exit $?
case "${1:-}" in
  timers) dc_timers; exit $? ;;
  check) dc_check; exit $? ;;
esac
. deploy/host/scripts/in_container.sh && code_dir_default DATA_PIPELINE_IMAGE
C=deploy/host/compose
files="-f $C/compose.pipeline.yml -f $C/compose.pipeline-mcp.yml -f $C/compose.mcp-server.yml"
[ -n "${CODE_DIR:-}" ] && files="$files -f $C/compose.code.yml -f $C/compose.code.pipeline-mcp.yml -f $C/compose.code.mcp-server.yml"
# shellcheck disable=SC2086 — DOCKER(sudo podman처럼 두 낱말)·파일 인자는 낱말 나눔
exec $DOCKER compose -p "compose$NAME_SUFFIX" $files "$@"   # 묶음 이름 — 한 벌은 compose 기본(폴더 이름 compose) 그대로, 여러 벌은 compose-<instance>
