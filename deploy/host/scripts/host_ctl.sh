#!/bin/bash
# 서버 컨테이너 입구 — 환경마다 compose 파일 하나(deploy/host/compose/compose-<환경>.yml — 환경 = 이 코드 폴더 settings.yaml required.env.run_env).
#   bash deploy/host/scripts/host_ctl.sh up -d [서비스…]          compose 하위 명령 그대로(up·down·ps·logs·restart …) — 예 up -d mcp-server
#   bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   코드 폴더(벌의 app) 채우기(root — 여러 번 불러도 안전)
#   bash deploy/host/scripts/host_ctl.sh timers                      systemd 타이머(새벽 배치·MCP 살리기)를 이 코드 폴더 기준으로 설치·켬(root — 운영 묶음 폴더에서)
#   bash deploy/host/scripts/host_ctl.sh check                       배포 뒤 점검을 차례로 — 처음 실패에서 멈추고 마지막 한 줄로 판정
# 이미지·CPU·메모리·포트는 compose 파일에, 스크립트가 들어갈 컨테이너 이름은 settings.yaml ops.host.*_container. PG(compose-pgvector.yml)·Redis(compose-redis.yml)는
#   사람이 한 번 따로 띄운다(늘 always — 비밀번호는 코드 폴더 맨 위 .env). 종료 코드: compose 그대로 · 설정을 못 읽으면 2 · init/timers/check는 아래 설명.
set -uo pipefail
cd "$(dirname "$0")/../../.."   # deploy/host/scripts/ → 코드 폴더 루트
if [ -n "${DC_ROOT:-}" ]; then RAG_ROOT=$DC_ROOT; fi   # 시험 루트(init) — load_settings.sh는 이미 있는 RAG_ROOT를 씀
. deploy/host/scripts/load_settings.sh   # 루트 RAG_ROOT·load_settings 한 곳(값은 아래 load_settings에서)

# init — 코드 폴더(벌의 app)를 한 번에 채운다(값·파일 내용은 찍지 않음). 여러 번 불러도 안전.
#   폴더: <루트>/output(10001:<그룹>, 2775 — setgid) · <루트>/output/_mcp_parse/jobs(같음)
#   코드 폴더: chmod -R a+rX — settings*.yaml(사본·백업 포함)·.env·output/은 빼고(비밀값 640 그대로)
#   settings.yaml: 코드 폴더의 settings.sample.yaml을 <루트>/settings.yaml로 — **없을 때만**(있으면 절대 덮지 않음), 10001:<그룹> 640.
#   DC_ROOT=<폴더>는 루트 대신(시험용 — 주인 바꾸기·코드 폴더 a+rX를 건너뜀). root가 아니면 거부(종료 코드 3).
#   끝에 settings.yaml `required:` 중 빈 칸 이름(값은 안 찍음). 종료 코드: 0 · 2 인자 틀림 · 3 root 아님 · 5 settings.yaml 복사 실패.
dc_init() {
  local group="" root=$RAG_ROOT test=${DC_ROOT:+1} out jobs sf
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
  out=$root/output
  jobs=$out/_mcp_parse/jobs
  echo "[host_ctl init] 루트: $root"
  _mk() {   # _mk <폴더> <권한> — 주인 UID 10001 고정(이미지의 컨테이너 사용자 rag)
    if [ -d "$1" ]; then echo "  있음  $1"; else mkdir -p "$1" && echo "  만듦  $1"; fi
    chmod "$2" "$1"
    if [ -z "$test" ]; then chown "10001:$group" "$1"; else echo "  (시험 — 주인 바꾸기 건너뜀)"; fi
  }
  _mk "$out" 2775
  _mk "$jobs" 2775
  if [ -z "$test" ]; then   # 코드만 a+rX — 설정(사본·백업 포함)·.env(비밀번호)·결과를 건드리지 않음
    find . \( -path "./settings*.yaml*" -o -path "./settings copy*" -o -path ./.env -o -path ./output \) -prune -o -exec chmod a+rX {} + &&
      echo "  권한  $(pwd) (a+rX — 설정·결과 빼고)"
  else echo "  (시험 — 코드 폴더 a+rX 건너뜀)"; fi
  if [ -e "$sf" ]; then echo "  있음  $sf(덮지 않음)"
  else
    cp settings.sample.yaml "$sf" && chmod 640 "$sf" && echo "  만듦  $sf(settings.sample.yaml에서)" ||
      { echo "[host_ctl init] settings.yaml 복사 실패: $sf" >&2; return 5; }
    [ -n "$test" ] || chown "10001:$group" "$sf"
  fi
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
#   ⓪ .env = settings.yaml(PG·Redis 비밀번호·계정 — 다른 이름만) ① check_env ② ping_models ③ migrate check --target all(pipe_exec.sh — 파이프라인 컨테이너 안) ④⑤ selftest_gate.sh(두 컨테이너의 이미지 — "[판정] 통과" 줄로 판정)
#   ⑥ mcp_keepalive.sh(/health). dev(개발 벌 — 검색 MCP 없음)는 ⑤⑥ 없이 파이프라인만. 검색 근거가 필요한 MCP 호출(mcp_smoke)은 넣지 않음 — 첫 적재 전에는 근거가 없음.
#   DC_FAKE=<명령>이면 각 단계를 `<명령> <단계 이름>`으로 바꿔 부른다(시험용 — 출력·종료 코드를 그대로 판정).
dc_check() {
  local n=0 name out rc
  if [ "$RUN_ENV" = dev ] && [ -z "${PIPE_CONTAINER:-}" ]; then   # 비우면 출시 전 시험 컨테이너(data-pipeline)를 점검함
    echo "[host_ctl check] dev 벌은 settings.yaml ops.host.pipeline_container(data-pipeline-<n>)를 채울 것" >&2; return 2
  fi
  _step() {   # _step <이름> <안내> <명령…>
    name=$1; local hint=$2; shift 2
    echo "[host_ctl check] ── $name"
    if [ -n "${DC_FAKE:-}" ]; then set -- $DC_FAKE "$name"; fi   # shellcheck disable=SC2086 — 시험 명령은 낱말 나눔
    out=$("$@" 2>&1); rc=$?
    printf '%s\n' "$out"
    case "$name" in selftest*) printf '%s\n' "$out" | grep -q '^\[판정\] 통과' || rc=1 ;; esac
    # pipe_exec.sh는 컨테이너가 안 떠 있으면 종료 코드 2와 "떠 있지 않음" 안내 — 띄우지 않고 그 안내로 멈춤
    if [ $rc -eq 2 ] && printf '%s\n' "$out" | grep -q '떠 있지 않음'; then
      echo "[host_ctl check] 실패 — $name: $P 컨테이너가 안 떠 있음 → host_ctl.sh up -d $P"; return 1
    fi
    if [ $rc -ne 0 ]; then echo "[host_ctl check] 실패 — $name: $hint"; return 1; fi
    n=$((n + 1))
  }
  local img vol=()
  _img() {   # _img <컨테이너> — 그 컨테이너가 쓰는 이미지(compose 파일에 적힌 것) · 실행 이미지(*-runtime — 코드 없음)면 이 코드 폴더를 붙임
    # shellcheck disable=SC2086 — DOCKER는 낱말 나눔(sudo docker)
    img=$($DOCKER inspect -f '{{.Config.Image}}' "$1" 2>/dev/null); vol=()
    case "$img" in *-runtime:*) vol=(-v "$(pwd):$APP_CODE_ROOT:ro,z") ;; esac
  }
  # 판정 시험의 DB 사례는 서버 PG에 붙는다(prd는 읽기만): 같은 설정 파일·host 네트워크·RUN_ENV · settings.yaml의 <서버 IP>(PC는 host.docker.internal)로
  local gate=(--network host --add-host host.docker.internal:host-gateway --tmpfs "${APP_OUTPUT_ROOT:?APP_OUTPUT_ROOT 필요 — load_settings}:mode=1777" -v "${SETTINGS_FILE:?SETTINGS_FILE 필요 — load_settings}:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e "RUN_ENV=${RUN_ENV:?RUN_ENV 필요 — load_settings}")
  _step ".env 일치" ".env의 REDIS_PASSWORD·PG_USER·PG_DB·PG_PASSWORD를 settings.yaml과 같게(다른 칸 이름만 찍음)" "${PY:-python3}" deploy/host/scripts/settings_to_env.py --file "$SETTINGS_FILE" --check-env .env || return 1
  _step check_env "출력의 FAIL 줄 확인(docs/operations/settings.md)" bash deploy/host/scripts/pipe_exec.sh check_env || return 1
  _step ping_models "모델 주소·키(settings.yaml required.models) — 서버는 내부망 모델만" bash deploy/host/scripts/pipe_exec.sh ping_models || return 1
  _step "migrate check" "migrate up --target all · master load(promote.sh — docs/operations/prd.md)" bash deploy/host/scripts/pipe_exec.sh migrate check --target all || return 1
  local c cs=("$P")
  [ "$RUN_ENV" = dev ] || cs+=("$M")
  for c in "${cs[@]}"; do
    _img "$c"
    # shellcheck disable=SC2086
    _step "selftest $c" "FAIL 줄의 시험 이름으로 원인 찾기" bash deploy/release/selftest_gate.sh $DOCKER run --rm "${gate[@]}" ${vol[@]+"${vol[@]}"} "$img" selftest || return 1
  done
  if [ "$RUN_ENV" != dev ]; then
    _step "검색 MCP" "\`$DOCKER logs $M\` 마지막 줄 — mcp_keepalive.sh가 다시 띄웠는데도 /health 응답 없음" bash deploy/host/scripts/mcp_keepalive.sh || return 1
  fi
  echo "[host_ctl check] 통과 — ${n}개"
}

# timers — systemd 단위 4개(deploy/host/systemd — 새벽 배치·MCP 살리기)의 코드 폴더 자리(@CODE_DIR@)를 이 코드 폴더로 채워
#   /etc/systemd/system에 쓰고 두 타이머를 켠다. 운영 묶음 폴더(${PRD_DIR}/app)에서 부른다(다른 폴더에서 부르면 그 폴더로 바뀜).
#   root가 아니면 종료 3. DC_UNIT_DIR=<폴더>는 /etc/systemd/system 대신(시험용 — root 확인·systemctl을 건너뜀).
dc_timers() {
  local dest=${DC_UNIT_DIR:-/etc/systemd/system} t u timers=(data-pipeline-nightly mcp-server-keepalive)
  if [ "$(id -u)" != 0 ] && [ -z "${DC_UNIT_DIR:-}" ]; then
    echo "[host_ctl timers] root로 실행할 것(sudo) — /etc/systemd/system에 쓴다" >&2; return 3
  fi
  for t in "${timers[@]}"; do
    for u in "deploy/host/systemd/$t.service" "deploy/host/systemd/$t.timer"; do
      sed "s#@CODE_DIR@#$(pwd)#g" "$u" > "$dest/$(basename "$u")" && echo "  씀  $dest/$(basename "$u")" || return 1
    done
  done
  [ -n "${DC_UNIT_DIR:-}" ] && return 0
  systemctl daemon-reload && systemctl enable --now "${timers[@]/%/.timer}"
}

case "${1:-}" in
  init) shift; dc_init "$@"; exit $? ;;
esac
load_settings || exit $?
P=${PIPE_CONTAINER:-data-pipeline} M=${MCP_CONTAINER:-mcp-server}   # settings.yaml ops.host.pipeline_container·mcp_container
BENCH=$(dirname "$RAG_ROOT")   # 벌 폴더 = <벌>/{app,home} — 이 코드 폴더는 app
export SBL_ROOT=${SBL_ROOT:-$(dirname "$BENCH")} PRD_DIR=${PRD_DIR:-$BENCH}   # compose-dev.yml·compose-prd.yml의 폴더 자리
case "${1:-}" in
  timers) dc_timers; exit $? ;;
  check) dc_check; exit $? ;;
esac
F=deploy/host/compose/compose-${RUN_ENV:-}.yml   # 환경 = settings.yaml required.env.run_env(load_settings가 RUN_ENV로 냄)
[ -f "$F" ] || { echo "[host_ctl] $F 없음 — settings.yaml required.env.run_env는 local·dev·prd 중 하나" >&2; exit 2; }
# shellcheck disable=SC2086 — DOCKER(sudo docker처럼 두 낱말)는 낱말 나눔
exec $DOCKER compose -f "$F" "$@"   # compose 변수 DOC_SRC(ops.host.host_docs_dir)는 load_settings가 셸 env로 냄
