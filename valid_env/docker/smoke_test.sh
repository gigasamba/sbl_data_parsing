#!/bin/bash
# 모듈 컨테이너 연결 시험 — 시험용 pg → parse → structure → load(트리거 1회씩) → mcp 상주 → 밖(호스트)에서 MCP HTTP 호출 → 정리.
#   DATA_PIPELINE_IMAGE=data-pipeline:<태그> MCP_SERVER_IMAGE=mcp-server:<태그> DOC_SRC=<시험 문서 폴더> RAG_OUT=<빈 결과 폴더> \
#   SMOKE_SETTINGS=<settings.yaml: mcp.server.token · common.models.embed(base_url·model — 내부망) · (s3://면) common.connections.object_storage 키> SMOKE_PG_PASSWORD=<시험용> \
#   [SMOKE_SOURCE=/data/docs | s3://버킷/접두] [SMOKE_LIMIT=10] [SMOKE_MODE=test] [SMOKE_KEEP=1 — 끝나도 pg·minio 남김] bash valid_env/docker/smoke_test.sh [질문]   (S6b — 옛 docker/server_sim/, PC 시험 Docker)
#   [PY=호스트 python(boto3 필요, PYTHONPATH=저장소 루트로 common.check.os_put 등 -m 호출)]
#   [SMOKE_NIGHTLY=1 — 자정 배치 모양(NIGHTLY_MODULES="parse publish"): 구조화·적재·MCP 건너뜀, s3:// 원천 필요 — S8b부터 파싱도 pg(판 표)가 필요해 pg는 띄움]
#   s3:// 원천이면 추가로: ①-1 임시 원본 삭제 확인(SI39 — 대표 결과가 나온 문서의 _source_files·prepared 사본 0) · ⑥ 결과 게시(publish 트리거, MinIO 버킷+SQLite 가짜 EDW) 확인
# 종료 코드: 0 통과 · 그 밖 = 실패 단계의 종료 코드. 비밀값은 설정 파일에만(이 스크립트는 출력하지 않음).
# S7e1(사용자 10-27 Q1) — 컨테이너는 SMOKE_SETTINGS를 읽기 전용으로 붙여 읽는다(서버 compose와 같은 꼴 — 옛 SMOKE_ENV env 파일 대신). 이 스크립트가
#   호스트에서 쓰는 값(MCP 토큰·minio 계정)은 그 파일에서 꺼낸다(PY에 PyYAML 필요 — BaseLoader로 쓴 글자 그대로, VS7e1 R-5).
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
setting() {   # setting <칸 경로> — 설정 파일 값(없으면 빈 글자, 값은 출력하지 않고 부른 쪽 변수로만 — 쓴 글자 그대로, VS7e1 R-5)
  $PY -c 'import sys, yaml
d = yaml.load(open(sys.argv[1], encoding="utf-8"), Loader=yaml.BaseLoader) or {}
for k in sys.argv[2].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$SMOKE_SETTINGS" "$1"
}
: "${SMOKE_PG_PASSWORD:?SMOKE_PG_PASSWORD=<시험용 PG 비밀번호> 필요}"
SMOKE_OVERLAY_DIR=$(mktemp -d); export SMOKE_OVERLAY_DIR   # S7e2 — 시험망 덮기 파일(지우지 않음 — OS 임시 폴더)
$PY - "$SMOKE_OVERLAY_DIR" <<'PYEOF' || { echo "[실패] 덮기 파일 만들기"; exit 2; }
import os, sys, yaml
from pathlib import Path
d, e = Path(sys.argv[1]), os.environ
job = {"PG_HOST": "pg", "PG_PORT": "5432", "PG_PASSWORD": e["SMOKE_PG_PASSWORD"], "PARSE_SOURCE": e.get("SMOKE_SOURCE") or "/data/docs",
       "RUN_MODE": e.get("SMOKE_MODE") or "prod", "PARSE_SOURCE_LIMIT": e.get("SMOKE_LIMIT") or "0", "OS_ENDPOINT": "http://minio:9000",
       "PM_BUCKET": e.get("SMOKE_PM_BUCKET") or "rag-publish", "PM_PREFIX": "smoke", "RDB_SQLITE": "/app/output/pm_test/edw.sqlite"}
files = {"job": {"base": "/etc/rag/base.yaml", "overrides": job},
         "load": {"base": "/etc/rag/smoke/job.yaml", "overrides": {"PG_CREATE_EXTENSION": "1"}},
         "mcp": {"base": "/etc/rag/smoke/job.yaml", "overrides": {"MCP_STORE": "pg", "MCP_HOST": "auto", "MCP_PORT": "8765",
                                                                   # S9(C-38) — 비루프백 바인드(auto)라 DNS 리바인딩 보호가 켜짐: 호스트 게시 주소로 부르는 ⑤를 허용(옛 421)
                                                                   "MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*"}}}
for name, doc in files.items():
    p = d / f"{name}.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    p.chmod(0o644)
PYEOF
chmod 755 "$SMOKE_OVERLAY_DIR"
Q="${1:-계약 단가}"
cleanup() { [ "${SMOKE_KEEP:-0}" = 1 ] || $DC --profile job --profile os down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT
step() { echo "== $1"; shift; "$@"; rc=$?; [ $rc -eq 0 ] || { echo "[실패] 종료 코드 $rc"; exit $rc; }; }
NIGHT=${SMOKE_NIGHTLY:-0}
step "시험용 PostgreSQL" $DC up -d --wait pg               # S8b — 파싱도 판 표(엔진 구성·원천 목록)를 읽음(못 읽으면 종료 4)
step "⓪ struct 판(판 표 2개 + 시드 — S8b)" $DC run --rm load migrate up --target struct
if [[ "${SMOKE_SOURCE:-}" == s3://* ]]; then             # Object Storage 시험: minio 띄우고 DOC_SRC를 올림(이미 있으면 덮어씀)
  OS_ACCESS_KEY=$(setting common.connections.object_storage.access_key); OS_SECRET_KEY=$(setting common.connections.object_storage.secret_key)
  export OS_ACCESS_KEY OS_SECRET_KEY                     # minio 계정 = 파싱 컨테이너 접속 키(설정 파일 — S7e1)
  step "모의 Object Storage(minio)" $DC --profile os up -d --wait minio
  # os_put은 설정 객체를 읽음 — 호스트에서 minio 주소는 덮기 파일로(env OS_ENDPOINT는 안 읽음 — VS7e2 R-7). PC 시험이라 RUN_ENV=local(덮기 파일 도구는 PC 전용)
  os_settings=$(RUN_ENV=local $PY -m common.config.overrides --base "$SMOKE_SETTINGS" OS_ENDPOINT="http://127.0.0.1:${MINIO_PUBLISH_PORT:-19000}") \
    || { echo "[실패] os_put 덮기 파일 만들기"; exit 2; }
  step "원본 올리기 → $SMOKE_SOURCE" env RUN_ENV=local SETTINGS_FILE="$os_settings" $PY -m common.check.os_put "$DOC_SRC" "$SMOKE_SOURCE"
fi
step "① 파싱(data-pipeline)" $DC run --rm parse parse
if [[ "${SMOKE_SOURCE:-}" == s3://* ]]; then
  step "①-1 임시 원본 삭제 확인(SI39)" $PY - "$RAG_OUT" <<'EOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
idx = out / "parse" / "_rep" / "index.json"
done = {d["doc"] for d in json.loads(idx.read_text(encoding="utf-8"))["docs"] if d.get("engine")} if idx.exists() else set()
left = [p.name for d in ("_source_files", "prepared") if (out / d).exists() for p in (out / d).iterdir() if p.is_file() and p.name in done]
rest = [p.name for p in (out / "_source_files").iterdir() if p.is_file()] if (out / "_source_files").exists() else []
print(f"대표 결과 {len(done)}건 · 남은 임시 원본(대표 결과 있는 문서) {len(left)}건 · _source_files 전체 남음 {len(rest)}건(실패·DRM 문서)")
sys.exit(1 if left or not done else 0)
EOF
fi
if [ "$NIGHT" != 1 ]; then
step "② 구조화(data-pipeline)" $DC run --rm structure structure
# S9(C-38 — 사용자 10-28 a): 적재는 서버 실제 길(run_docs.py와 같은 pgvector_load load — `pipeline.cli load`는 축소 스키마 묶음을 인계 계약
#   DOC_KEYS로 거부하는 알려진 문제, CLAUDE.md §10). 표·vector 확장은 migrate가 먼저(S8a — 실행 중 DDL 없음, 차원은 묶음 meta.json).
step "③-0 검색 판(migrate — 묶음 차원·vector 확장)" $DC run --rm load migrate up --target search --bundle /app/output/edw/bundle --create-extension
step "③ 적재(data-pipeline → pg — pgvector_load load)" $DC run --rm --entrypoint python load -m pipeline.load.pgvector_load load --bundle /app/output/edw/bundle
step "④ 검색 MCP 띄우기" $DC up -d mcp
for i in $(seq 1 30); do $DC logs mcp 2>/dev/null | grep -q "검색 MCP http" && break; sleep 1; done
TOKEN=$(setting mcp.server.token)   # S7e1 — 설정 파일(옛 SMOKE_ENV의 MCP_TOKEN)
step "⑤ 밖에서 MCP 호출" $PY -m mcp_server.cli.mcp_smoke --url "http://127.0.0.1:${MCP_PUBLISH_PORT:-18765}/mcp" --token "$TOKEN" --q "$Q"
fi
if [[ "${SMOKE_SOURCE:-}" == s3://* ]]; then             # ⑥ 결과 게시(SI39) — 맨 마지막 별도 단계, 트리거로만
  B=${SMOKE_PM_BUCKET:-rag-publish}
  mkdir -p "$RAG_OUT/pm_test"                          # 가짜 EDW(SQLite) 폴더 — SqliteStore는 상위 폴더를 만들지 않음
  step "⑥-0 게시 버킷 준비($B)" env OS_ENDPOINT="http://127.0.0.1:${MINIO_PUBLISH_PORT:-19000}" $PY -c "import os,boto3; c=boto3.client('s3',endpoint_url=os.environ['OS_ENDPOINT'],aws_access_key_id=os.environ['OS_ACCESS_KEY'],aws_secret_access_key=os.environ['OS_SECRET_KEY'],region_name='us-east-1'); c.create_bucket(Bucket='$B') if '$B' not in [b['Name'] for b in c.list_buckets()['Buckets']] else None"
  step "⑥ 결과 게시(publish 트리거)" $DC run --rm publish publish
  step "⑥-1 게시 확인(rep.md·source.json·EDW 행)" env OS_ENDPOINT="http://127.0.0.1:${MINIO_PUBLISH_PORT:-19000}" $PY - "$RAG_OUT" "$B" <<'EOF'
import os, sqlite3, sys
from pathlib import Path
import boto3
out, b = Path(sys.argv[1]), sys.argv[2]
c = boto3.client("s3", endpoint_url=os.environ["OS_ENDPOINT"], aws_access_key_id=os.environ["OS_ACCESS_KEY"], aws_secret_access_key=os.environ["OS_SECRET_KEY"], region_name="us-east-1")
keys = [o["Key"] for pg in c.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix="smoke/") for o in pg.get("Contents", [])]
md = [k for k in keys if k.endswith("/rep.md")]
sc = [k for k in keys if k.endswith("/source.json")]
bad = [k for k in keys if not k.endswith(("/rep.md", "/source.json"))]
db = out / "pm_test" / "edw.sqlite"
con = sqlite3.connect(db) if db.exists() else None
tab = con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall() if con else []
rows = sum(con.execute(f"select count(*) from [{t[0]}]").fetchone()[0] for t in tab) if con else 0
if con: con.close()
ex = sorted((out / "publish").glob("excluded_*.md")) if (out / "publish").exists() else []
print(f"rep.md {len(md)} · source.json {len(sc)} · 다른 객체 {len(bad)} · EDW 행 {rows} · 제외 보고 {len(ex)}개 · 예: {md[:2]}")
sys.exit(0 if md and len(md) == len(sc) and not bad and rows == len(md) else 1)   # DRM·실패는 EDW에 안 들어감(SI39⑥)
EOF
fi
echo "모듈 컨테이너 연결 시험 통과"
