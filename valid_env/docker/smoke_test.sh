#!/bin/bash
# 모듈 컨테이너 연결 시험 — 시험용 pg → 마스터 표 → parse → structure(build_bundle) → migrate·load(pgvector_load) → mcp 상주 → 밖(호스트)에서 MCP HTTP 호출 → 정리.
#   DATA_PIPELINE_IMAGE=data-pipeline:<태그> MCP_SERVER_IMAGE=mcp-server:<태그> DOC_SRC=<시험 문서 폴더> RAG_OUT=<빈 결과 폴더> \
#   SMOKE_SETTINGS=<settings.yaml: mcp.server.token · common.models.embed(base_url·model — 내부망)> SMOKE_PG_PASSWORD=<시험용> \
#   SMOKE_SYSTEM=<원천 — 예 SFDC> [SMOKE_LIMIT=10] [SMOKE_KEEP=1 — 끝나도 pg 남김] bash valid_env/docker/smoke_test.sh [질문]   (S6b — 옛 docker/server_sim/, PC 시험 Docker)
#   [PY=호스트 python(PYTHONPATH=저장소 루트로 mcp_server.cli.mcp_smoke 등 -m 호출)]
#   원본은 DOC_SRC 폴더 하나(/data/docs) — 11-01 사용자: 원천 s3://를 지워 SMOKE_SOURCE(s3:// — MinIO 대역·원본 삭제 확인·결과 게시 ⑥)와
#   SMOKE_NIGHTLY(자정 배치 모양 — s3:// 원천 필요)도 지움. 게시(publish)는 서버 run_docs·nightly_batch.sh publish로 확인.
# 종료 코드: 0 통과 · 그 밖 = 실패 단계의 종료 코드. 비밀값은 설정 파일에만(이 스크립트는 출력하지 않음).
# S7e1(사용자 10-27 Q1) — 컨테이너는 SMOKE_SETTINGS를 읽기 전용으로 붙여 읽는다(서버 compose와 같은 꼴 — 옛 SMOKE_ENV env 파일 대신). 이 스크립트가
#   호스트에서 쓰는 값(MCP 토큰)은 그 파일에서 꺼낸다(PY에 PyYAML 필요 — BaseLoader로 쓴 글자 그대로, VS7e1 R-5).
# S7e2(사용자 10-28 — 설정은 yaml로만): 시험망 덮기(PG_HOST: pg·PG_PASSWORD=SMOKE_PG_PASSWORD·OS_ENDPOINT·PM_*·MCP_*·PARSE_SOURCE 등 — 옛 compose
#   environment 줄)는 이 스크립트가 덮기 파일 3개(SMOKE_OVERLAY_DIR — mktemp: job·load·mcp.yaml, base는 컨테이너 /etc/rag/base.yaml = SMOKE_SETTINGS)로
#   만든다. 시험용 PG 비밀번호가 들어가므로 PC 시험 전용(권한 644 — 컨테이너 사용자 UID 10001이 읽게, OS 임시 폴더).
# 구조 개편 v4 단계5(10-13) — 이 스크립트는 저장소 루트에서 실행(cli/os_put.py·cli/mcp_smoke.py가
# 옛 공용 cli 패키지로 옮겨 패키지 경유 -m 호출이 필요해짐 — S3부터 os_put은 common.check.os_put, import 기준은 저장소 루트 PYTHONPATH=.(D-014)).
set -uo pipefail
cd "$(dirname "$0")/../.."   # valid_env/docker/ -> 저장소 루트
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD"
DC="docker compose -f valid_env/docker/compose.test.yml"
# S6c(사용자 10-27, C-30 ②) — 옛 SMOKE_PATCH=1(compose.patch.yml 덧씌우기)은 삭제: 그 파일이 시험 compose에 없는 서비스(retrieval·index_*·상주 트리거)를
#   선언해 compose가 불러오지 못했다(pre-refactor부터). 덧씌우기 확인은 서버 절차(release-and-patch.md §3-3).
PY=${PY:-python}
: "${SMOKE_SETTINGS:?SMOKE_SETTINGS=<settings.yaml> 필요(S7e1)}"
case "$SMOKE_SETTINGS" in /*) ;; *) SMOKE_SETTINGS=$PWD/$SMOKE_SETTINGS ;; esac; export SMOKE_SETTINGS   # compose 마운트 원본은 절대 경로
setting() {   # setting <파일 자리(op-08 ② 새 배치)> — 설정 파일 값(없으면 빈 글자, 값은 출력하지 않고 부른 쪽 변수로만 — 쓴 글자 그대로, VS7e1 R-5)
  $PY -c 'import sys, yaml
d = yaml.load(open(sys.argv[1], encoding="utf-8"), Loader=yaml.BaseLoader) or {}
for k in sys.argv[2].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$SMOKE_SETTINGS" "$1"
}
: "${SMOKE_PG_PASSWORD:?SMOKE_PG_PASSWORD=<시험용 PG 비밀번호> 필요}"
: "${SMOKE_SYSTEM:?SMOKE_SYSTEM=<DOC_SRC 문서의 원천 — SFDC·CRMS·LAS·FAQ·Other> 필요(search는 원천 하나 필수)}"
SMOKE_OVERLAY_DIR=$(mktemp -d); export SMOKE_OVERLAY_DIR   # S7e2 — 시험망 덮기 파일(지우지 않음 — OS 임시 폴더)
$PY - "$SMOKE_OVERLAY_DIR" <<'PYEOF' || { echo "[실패] 덮기 파일 만들기"; exit 2; }
import os, sys, yaml
from pathlib import Path
d, e = Path(sys.argv[1]), os.environ
job = {"PG_HOST": "pg", "PG_PORT": "5432", "PG_PASSWORD": e["SMOKE_PG_PASSWORD"], "PARSE_SOURCE": "/data/docs",
       "RUN_MODE": "prod", "PARSE_SOURCE_LIMIT": e.get("SMOKE_LIMIT") or "0"}
files = {"job": {"base": "/etc/rag/base.yaml", "overrides": job},
         "load": {"base": "/etc/rag/smoke/job.yaml", "overrides": {"PG_CREATE_EXTENSION": "1"}},
         "mcp": {"base": "/etc/rag/smoke/job.yaml", "overrides": {"MCP_HOST": "auto", "MCP_PORT": "8765",
                                                                   # S9(C-38) — 비루프백 바인드(auto)라 DNS 리바인딩 보호가 켜짐: 호스트 게시 주소로 부르는 ⑤를 허용(옛 421)
                                                                   "MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*"}}}
for name, doc in files.items():
    p = d / f"{name}.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    p.chmod(0o644)
PYEOF
chmod 755 "$SMOKE_OVERLAY_DIR"
Q="${1:-계약 단가}"
cleanup() { [ "${SMOKE_KEEP:-0}" = 1 ] || $DC --profile job down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT
step() { echo "== $1"; shift; "$@"; rc=$?; [ $rc -eq 0 ] || { echo "[실패] 종료 코드 $rc"; exit $rc; }; }
step "시험용 PostgreSQL" $DC up -d --wait pg               # 적재(load)·검색이 씀(엔진 구성·원천 목록은 파일 — 사용자 11-01)
# ⓪ 마스터 표(용어집·고객 명부 — pl-38): 구조화의 고객 판별이 읽고 비었으면 멈추므로 파싱 전에 판을 올리고 git CSV로 채운다.
step "⓪ 마스터 판(migrate up --target master)" $DC run --rm load migrate up --target master
step "⓪ 마스터 표 채우기(migrate master load)" $DC run --rm load migrate master load
step "① 파싱(data-pipeline)" $DC run --rm parse parse
step "② 구조화(data-pipeline — run_docs와 같은 build_bundle)" $DC run --rm --entrypoint python structure -m pipeline.transform.structure.build_bundle --parse-dir /app/output/parse --out /app/output/edw/bundle
# 적재는 서버 실제 길(run_docs.py와 같은 `python -m pipeline.load.pgvector_load load` — 옛 `pipeline.cli load`는 11-01에 지움, README §4-4).
#   표·vector 확장은 migrate가 먼저(S8a — 실행 중 DDL 없음, 차원은 묶음 meta.json). 마스터 표는 맨 앞(⓪ — 구조화가 읽음).
step "③-0 판(migrate up --target all — 묶음 차원·vector 확장)" $DC run --rm load migrate up --target all --bundle /app/output/edw/bundle --create-extension
step "③ 적재(data-pipeline → pg — pgvector_load load)" $DC run --rm --entrypoint python load -m pipeline.load.pgvector_load load --bundle /app/output/edw/bundle
step "④ 검색 MCP 띄우기" $DC up -d mcp
for i in $(seq 1 30); do $DC logs mcp 2>/dev/null | grep -q "검색 MCP http" && break; sleep 1; done
TOKEN=$(setting required.tokens.mcp)   # S7e1 — 설정 파일(옛 SMOKE_ENV의 MCP_TOKEN)
step "⑤ 밖에서 MCP 호출" $PY -m mcp_server.cli.mcp_smoke --url "http://127.0.0.1:${MCP_PUBLISH_PORT:-18765}/mcp" --token "$TOKEN" --source "$SMOKE_SYSTEM" --q "$Q"
echo "모듈 컨테이너 연결 시험 통과"
