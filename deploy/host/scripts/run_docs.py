#!/usr/bin/env python3
"""문서별 flow 러너(2026-10-22 사용자 지정 설계) — 배치 장벽 제거.

1) 대기열 — 앞으로 나올 문서 WARM_TARGET(기본 20)개를 미리 warm 다운로드. 진행중 문서는 대기 개수에서 제외.
   파싱이 하나 시작되면 다음 문서를 즉시 받아 개수를 유지. 문서 flow가 끝나면 docflow 임시 디렉토리·warm 잔여 삭제.
2) 파싱 flow — 레인 light·medium·vlm(warm 때 분류)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴
   다른 레인에서 가져옴) — 기본 레인마다 1·1(사용자 10-29, docs/prd/runner.md rn-01). vlm 문서는 동시 VLM_CAP(2)까지.
   구조화 대기 문서가 STRUCT_BACKLOG(기본 구조화 워커 × 2)개 이상이면 새 파싱을 시작하지 않고 기다림(rn-02).
   레인·대기 길이는 상태가 바뀔 때마다 batch_progress/queue_depth.jsonl에 한 줄(rn-02).
   값은 settings.yaml ops.run_docs(비우면 아래 RUN_DOCS_DEFAULTS) — --warm·--struct-workers 인자가 그 위를 덮음.
3) 구조화+적재 — 문서 경계 없이: 파싱이 끝난 문서부터 곧바로 build_bundle(EMBED_BATCH=32·EMBED_CONCURRENCY=6,
   문서당 제약 없이 구조화 스트림 안에서 적용) → pgvector_load(BM25_THREADS=2) → publish(OS+EDW) → 임시 삭제.
   STRUCT_WORKERS(기본 2)개 스레드가 문서를 연속으로 처리 — 배치 장벽 없이 파싱 끝나는 순서대로 흐름.

사용: python3 run_docs.py --start-offset 1072 [--warm 20] [--struct-workers 2]
                  [--filter RFP,proposal] [--limit N](시험: N건만) [--no-cleanup](임시 유지)
로그: test_space/batch_progress/progress.log · 문서별 파싱 로그 progress/doc_<seq>.log
"""

import argparse
import csv
import datetime
import functools
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# S7e1(사용자 10-27 Q8 · D-028 ⑨ · C-29 ⑨) — 운영 접속 값·비밀·운영 고정값을 코드에서 지우고 서버 settings.yaml에서 읽는다(configure() — 시작 때 한 번).
#   파일: --settings 또는 SETTINGS_FILE, 없으면 $SERVER_ENV_DIR/settings.yaml(기본 배치 /srv/rag/env). 호스트 python에 PyYAML이 있어야 한다(pymssql처럼 —
#   refactor.md C-09). 필요한 칸이 없으면 칸 경로만 찍고 종료 코드 2(값은 찍지 않음). required.env.run_env가 dev·prd가 아니면 거부(로컬 실행 금지 — CLAUDE.md 3절).
#   docker exec로 부르는 컨테이너(data-pipeline-parse·structure)는 같은 파일을 붙여 읽으므로(compose x-settings) 명령 줄에 접속 값·비밀을 넣지 않는다(ps·로그에 안 남음).
#   작업 폴더(진행 기록 batch_progress/·batches/)는 settings.yaml ops.pipeline_host.run_docs_dir(비우면 이 스크립트 옆 test_space/ — 옛 자리), 결과 공유 폴더(옛 test_space/rfp_all_output)는
#   required.deploy.output_root(RAG_OUT — 컨테이너 /app/output의 원본 그대로, C-29 ⓑ를 코드로 보장 — 사용자 Q8 ⑤).
TEST = PROG = DOCSPACE = DOCFLOW = WARM = ENVFILE = PATCH_CODE = None  # configure()가 채움
DOCKER = "docker"  # 컨테이너 명령 — configure()가 ops.host.docker(없으면 podman, 그것도 없으면 docker — op-10)로 채움
CODE_DIR = None  # --code(설정 배치 모듈 layout.py를 찾을 코드 폴더 — 운영자 폴더에서 돌릴 때, op-10)
DEFAULT_CODE = Path("/srv/rag/code/live")  # 코드 폴더 기본 배치(common.host.patch_code 기본값과 같음)
_EDW: dict = {}  # parsing-meta EDW 접속(호스트 pymssql — edw_list·edw_done_keys)
WARM_BUCKET = PG_CONTAINER = PG_USER = PG_DB = PG_SCHEMA = None  # warm 파일 이름의 원천 버킷 · 문서 수 세기(psql)
SETTINGS_REQUIRED = (  # (칸 경로, 무엇에 쓰나) — 없으면 시작 거부
    ("common.run_env", "실행 환경(dev·prd)"),
    ("common.host.output_root", "결과 공유 폴더(RAG_OUT — 컨테이너 /app/output 원본)"),
    ("common.connections.rdb.host", "EDW 서버 — 호스트 조회(읽기 계정, 사용자 10-29 ops.md#op-03)"),
    ("common.connections.rdb.database", "EDW DB"),
    ("common.connections.rdb.read.user", "EDW 읽기 계정"),
    ("common.connections.rdb.read.password", "EDW 읽기 계정 비밀번호"),
    ("common.connections.object_storage.endpoint", "Object Storage 주소 — publish·warm(컨테이너)"),
    ("common.connections.object_storage.region", "Object Storage 리전(컨테이너)"),
    ("common.connections.object_storage.access_key", "Object Storage 키(컨테이너)"),
    ("common.connections.object_storage.secret_key", "Object Storage 비밀 키(컨테이너)"),
    ("pipeline.load.publish.bucket", "publish 업로드 버킷(컨테이너)"),
    ("pipeline.load.publish.prefix", "publish 업로드 접두(컨테이너)"),
    ("pipeline.connections.rdb.bucket", "원천 버킷 — warm 파일 이름(pipeline.extract.source와 같은 값)"),
    ("common.host.pg_container", "PostgreSQL 컨테이너 이름 — 문서 수 세기(psql)"),
    ("common.connections.pg.user", "PostgreSQL 계정 — 문서 수 세기(psql)"),
    ("common.connections.pg.db", "PostgreSQL DB — 문서 수 세기(psql)"),
    ("common.connections.pg.db_schema", "pgvector 스키마 — 문서 수 세기(psql)"),
)


def _yget(doc, path):
    for k in path.split("."):
        doc = doc.get(k) if isinstance(doc, dict) else None
    return doc


@functools.cache
def _layout():
    """설정 배치 모듈(common/config/layout.py — 표준 라이브러리만)을 파일로 읽음 — 호스트 python은 pydantic이 없어 common 패키지를 import하지 않는다."""
    import importlib.util

    # 찾는 순서(op-10): --code 폴더 > 이 스크립트가 든 코드 폴더 > 기본 배치 /srv/rag/code/live — 각각 저장소 배치(<루트>/common)·
    # 서버 코드 폴더 배치(<루트>/app/deploy/common — make_patch 오버레이)
    roots = [r for r in (CODE_DIR, ROOT.parents[2], DEFAULT_CODE) if r is not None]
    path = next(
        (p for r in roots for p in (Path(r) / "common", Path(r) / "app" / "deploy" / "common") if (p / "config" / "layout.py").is_file()),
        None,
    )
    if path is None:
        sys.exit("run_docs: common/config/layout.py 없음 — --code <코드 폴더>(기본 /srv/rag/code/live)로 코드 폴더를 알려 줄 것")
    spec = importlib.util.spec_from_file_location("settings_layout", path / "config" / "layout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_settings(settings_file=None):
    """(사전, 문제) — 서버 settings.yaml을 쓴 글자 그대로 읽는다(BaseLoader — 스칼라는 모두 글자: `password: 0123`·`user: no`가 83·False로
    바뀌지 않게, 앱 설정 모델의 글자 칸 규칙과 같음 — S7e1 리뷰). 파일: settings_file > SETTINGS_FILE > $SERVER_ENV_DIR/settings.yaml. 값은 찍지 않는다.
    파일 배치(required·역할 절 — op-08 ②)를 모델 배치(common·pipeline·mcp)로 바꿔 돌려준다 — 이 모듈의 칸 경로는 모델 경로."""
    env_dir = os.environ.get("SERVER_ENV_DIR") or "/srv/rag/env"  # env 남김 — 호스트 도구(settings_env.sh와 같음)
    path = Path(settings_file or os.environ.get("SETTINGS_FILE") or Path(env_dir) / "settings.yaml")  # env 남김 — 설정 파일 자리 신호(5-2)
    try:
        import yaml
    except ImportError:
        return {}, "호스트 python에 PyYAML이 없음 — pip install pyyaml(refactor.md C-09)"
    lay = _layout()
    try:
        # BaseLoader(글자만, 객체 생성 없음) + 같은 칸 두 번 거부(앱과 같게)
        loader = lay.reject_dup_keys(type("Loader", (yaml.BaseLoader,), {}))
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}
    except OSError as e:
        return {}, f"설정 파일을 읽지 못함: {path} ({e.strerror}) — --settings 또는 SETTINGS_FILE·$SERVER_ENV_DIR/settings.yaml"
    except yaml.YAMLError as e:
        dup = getattr(e, "problem", "") or ""
        return {}, f"설정 파일 YAML 형식 오류: {path}" + (f" — {dup}" if dup.startswith(lay.DUP_KEY) else "")
    if not isinstance(doc, dict):
        return {}, f"설정 파일 맨 위는 절(required·common·… tuning) 사전이어야 함: {path}"
    try:
        return lay.to_model(doc, str(path)), None
    except lay.LayoutError as e:
        return {}, str(e)


def work_dir(doc):
    """작업 폴더(진행 기록 batch_progress/·batches/) — settings.yaml ops.pipeline_host.run_docs_dir(모델 pipeline.host.run_docs_dir), 비우면 이 스크립트 옆 test_space/(옛 자리). analyze_docflow.py도 씀."""
    work = _yget(doc, "pipeline.host.run_docs_dir")
    return Path(work) if work else ROOT / "test_space"


def configure(settings_file=None):
    """서버 settings.yaml을 한 번 읽어 모듈 값(경로·접속)을 채운다 — 문제 목록(빈 목록이면 통과). 값은 찍지 않는다."""
    global TEST, PROG, DOCSPACE, DOCFLOW, WARM, ENVFILE, PATCH_CODE, MCP_JOBS_DIR, WARM_BUCKET, PG_CONTAINER, PG_USER, PG_DB, PG_SCHEMA
    global DOCKER
    doc, err = read_settings(settings_file)
    if err:
        return [err]
    probs = [f"설정 필요: {_layout().to_yaml(p)} — {why}" for p, why in SETTINGS_REQUIRED if _yget(doc, p) in (None, "")]
    run_env = _yget(doc, "common.run_env")
    if run_env not in (None, "") and run_env not in ("dev", "prd"):
        probs.append("required.env.run_env가 dev·prd가 아님 — 서버 전용 러너(로컬 실행 금지, CLAUDE.md 3절)")
    policy, bad = run_docs_policy(doc)
    probs += bad
    if probs:
        return probs
    apply_policy(policy)
    TEST = work_dir(doc)
    PROG = TEST / "batch_progress"
    ENVFILE = TEST / "batches" / "docflow_env.list"
    DOCSPACE = Path(_yget(doc, "common.host.output_root"))  # 컨테이너 /app/output 공유 볼륨
    DOCFLOW = DOCSPACE / "docflow"  # 문서별 임시 디렉토리(종료 시 삭제)
    WARM = DOCSPACE / "_warm"  # SOURCE_WARM 대기열 저장소
    # 컨테이너가 마운트하는 코드 폴더 — compose.patch*.yml·systemd·mcp_up.sh와 같은 칸(ops.host.patch_code — 기본 배치 /srv/rag/code/live).
    PATCH_CODE = Path(_yget(doc, "common.host.patch_code") or DEFAULT_CODE)
    DOCKER = _yget(doc, "common.host.docker") or (
        "podman" if shutil.which("podman") else "docker"
    )  # op-10 — 셸 스크립트와 같은 순서(env 대신 설정)
    jobs = _yget(doc, "mcp.host.jobs_dir")
    MCP_JOBS_DIR = Path(jobs) if jobs else DOCSPACE / "mcp_parse" / "jobs"
    rdb = _yget(doc, "common.connections.rdb")  # 조회만 — 읽기 계정(사용자 10-29 ops.md#op-03)
    try:
        port = int(rdb.get("port") or 1433)
    except ValueError:
        return ["common.connections.rdb.port 형식 오류 — 정수만(값은 안 찍음)"]
    _EDW.update(host=rdb["host"], port=port, database=rdb["database"], user=rdb["read"]["user"], password=rdb["read"]["password"])
    WARM_BUCKET = _yget(doc, "pipeline.connections.rdb.bucket")
    PG_CONTAINER = _yget(doc, "common.host.pg_container")
    PG_USER, PG_DB = _yget(doc, "common.connections.pg.user"), _yget(doc, "common.connections.pg.db")
    PG_SCHEMA = _yget(doc, "common.connections.pg.db_schema")
    return []


def _edw_connect():
    import pymssql

    return pymssql.connect(
        server=_EDW["host"], port=_EDW["port"], database=_EDW["database"], user=_EDW["user"], password=_EDW["password"], charset="utf8"
    )


# I4(V3 R1): 옛 DEPLOY(<이 폴더>/patch_code/app/deploy)·IMAGE는 pre-refactor에서 쓰는 곳이 없던 상수였고, I3 확인이 DEPLOY를
# 처음 썼지만 컨테이너가 실제로 그 폴더를 마운트한다는 근거가 없어(V3 R1) 확인을 PATCH_CODE로 옮기고 둘 다 지움.
# S6b(D-020, 사용자 10-27) — 파이프라인 이미지가 하나(data-pipeline)로 합쳐지고 상주 컨테이너 이름이 바뀜(옛 data-parsing·data-structure).
PARSE_C, STRUCT_C = "data-pipeline-parse", "data-pipeline-structure"  # docker inspect·exec 대상(compose.pipeline.yml 상주 서비스)

# S9 Step A(VS8b U-1, 사용자 10-28) — 컨테이너 안 앱이 읽는 설정 칸(옛 env 이름)은 명령 인자 `--set 이름=값`으로 준다(common.config.setarg —
# 그 python이 덮기 파일로 자기와 자식에게 넘김). 전에는 `bash -c 'X=값 python …'` env로 줬는데 S7e2부터 앱이 env의 옛 이름을 읽지 않아
# 문서별 결과 폴더(PIPE_OUT_ROOT 등)·동시 수·후보정·CPU 게이트가 효과가 없었다. 비밀 칸은 --set이 거부한다(명령 줄은 ps·로그에 남음).
EMBED_SET = ("EMBED_CONCURRENCY=6", "EMBED_BATCH=32", "BM25_THREADS=3")
PARSE_SET = (
    "VLM_GLOBAL_CONCURRENCY=8",
    "VLM_CONCURRENCY=8",
    "FIGURES_VLM_PARALLEL=8",
    "VLM_FIGURES_MAX=10",
    "PARSE_POST=supsub,charts,figures,context,attachments",
    "OCR_DPI=120",
    "RAPIDOCR_PAGE_WORKERS=2",
    "OCR_THREADS=1",
    "PIPE_PROCS=4",
    "SOURCE_WARM=/app/output/_warm",
    "SOURCE_FETCH_WORKERS=2",
    "PARSE_REP_SELECT=first",
    "PARSE_QA_LIGHT=1",
)
LIB_ENV = "PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache"  # env 남김 — 라이브러리(파이썬 자체 env, 설정 칸 아님)
DOC_MARK = "RUN_DOCS_DOC"  # 문서 표지 env(설정 칸 아님) — 고아 정리(sweep_cmd)가 /proc/*/environ에서 찾음(옛 PIPE_OUT_ROOT env 자리)


def sets(*pairs):
    """--set 인자 글자(앞 공백 포함) — 같은 이름이 여러 번이면 뒤 값이 이김(setarg — 옛 bash env와 같음)."""
    return "".join(f" --set {p}" for p in pairs)


# ── 컨테이너 명령 줄(S9 Step A — 명령 글자를 시험으로 고정하려고 함수로 뗌, 글자는 뗀 전과 같음) ──
def warm_cmd(seq):
    """문서 1개 warm(프리페치) — 파싱 컨테이너 안 source warm."""
    return (
        f"{DOCKER} exec {PARSE_C} bash -c 'mkdir -p /app/output/_warm && cd /app && "
        f"PYTHONPATH=/app/deploy "
        f"python -m pipeline.extract.source{sets('SOURCE_WARM=/app/output/_warm')} warm --csv /app/output/docflow/{seq}/batch.csv'"
    )


def parse_cmd(seq, chan, scan, gate):
    """문서 1개 파싱 — chan(light·medium·vlm), scan(스캔 PDF), gate(CPU 게이트 글자)."""
    inside = f"/app/output/docflow/{seq}"
    # 2026-10-23 사용자 지정 — heavy(스캔·이미지 다수) 판정 문서만 vlm_page 켬(스캔 쪽만 VLM 전사,
    # 내부 스캔판정이 이중 필터) · light는 종전대로 off. 같은 이름은 뒤 --set이 이기므로 뒤에 붙여 덮어씀.
    # 2026-10-23 사용자 지정 — 채널별 파라미터: heavy는 VLM 6(3동시 × 6 = 글로벌 18으로 gpu02 쏠림 제한),
    # light는 기본 8 유지(그림 거의 없음) · 스캔 PDF에만 vlm_page(40쪽 캡).
    heavy_on = (
        (
            "VLM_GLOBAL_CONCURRENCY=6",
            "VLM_CONCURRENCY=6",
            "FIGURES_VLM_PARALLEL=6",
            "PARSE_POST=supsub,charts,figures,context,attachments,vlm_page",
            "VLM_PAGE_MAX=",
            "VLM_PAGE_SLOW=45",
        )
        if chan == "vlm"
        else ()
    )
    scan_set = ("PREPARE_ROTATE=0",) if scan else ()  # 2026-10-23 B2 — 스캔 회전검토(OCR) 생략(스캔은 heavy → heavy_on과 병행)
    # 11-01 — 스캔용 엔진 목록(scan_eng, rapidocr_ko 제외)은 지움: 스캔(.pdf_image)은 엔진 구성 파일이 qwen_vlm 하나만 줌(같은 동작)
    doc = sets(
        f"PIPE_OUT_ROOT={inside}",
        f"DOC_DIR_PREPARED={inside}/prepared",
        f"PARSE_IMAGES_ROOT={inside}/parse/_images",
        f"PARSE_RAW_ROOT={inside}/parse",
        *PARSE_SET,
        *heavy_on,
        *scan_set,
        f"CPU_MAX_LOAD={gate}",
    )
    return (
        f"{DOCKER} exec {PARSE_C} bash -c 'cd /app && "
        f"echo [envcheck] gate={gate} 채널={chan}; "
        f"{DOC_MARK}={inside} {LIB_ENV} "
        f"python -m pipeline.cli{doc} parse --source rdb:csv:{inside}/batch.csv'"
    )


def struct_cmd(seq):
    """문서 1개 구조화 + 적재(구조화 컨테이너). 엔진 구성은 파싱과 같은 파일(코드 폴더 — 사용자 11-01: 판 번호 없음, 실행 중에는 안 바뀜)."""
    inside = f"/app/output/docflow/{seq}"
    st = sets(*EMBED_SET)  # 묶음·적재 python에(문서 메타는 적재가 EDW 조인으로 — pl-29 11-02, FILE_META_PATH 지움)
    return (
        f"{DOCKER} exec {STRUCT_C} bash -c 'cd /app && "
        f"PYTHONPATH=/app/deploy "
        f"python -m pipeline.transform.structure.build_bundle{st} --parse-dir {inside}/parse"
        f" --out {inside}/bundle && "
        f"python -m pipeline.load.pgvector_load{st} load --bundle {inside}/bundle "
        f">> /app/output/docflow/{seq}/structure.log 2>&1'"
    )


def publish_cmd(seq):
    """문서 1개 publish(OS + EDW — 파싱 컨테이너)."""
    inside = f"/app/output/docflow/{seq}"
    return (
        f"{DOCKER} exec {PARSE_C} bash -c 'cd /app && "
        "PYTHONPATH=/app/deploy python -m pipeline.load.publish_parse_result"
        f"{sets('PM_BUCKET_SKIP_OVERLAP_CHECK=1')} "  # 실행 방침(접속 값 아님) — 버킷·접두·표·EDW·Object Storage는 컨테이너가 설정 파일에서(S7e1 Q8)
        f"--out {inside} --source-system FileStorageMap --apply "
        f">> /app/output/docflow/{seq}/publish.log 2>&1'"
    )


def sweep_cmd(seq):
    """고아 정리 — 이 문서 표지 env(DOC_MARK)를 가진 파싱 컨테이너 안 프로세스(bash·python·soffice까지 env 상속)를 모두 끔. environ 항목(NUL 구분)과
    통째로 같을 때만(-zx — 리뷰 S9: 앞부분만 맞추면 doc 1 정리가 doc 10~19·100…까지 끔, 옛 PIPE_OUT_ROOT 때부터)."""
    inside = f"/app/output/docflow/{seq}"
    return (
        f'{DOCKER} exec {PARSE_C} bash -c "for p in /proc/[0-9]*; do '
        f"grep -aqzx '{DOC_MARK}={inside}' \\$p/environ 2>/dev/null && kill \\${{p##*/}} 2>/dev/null; done\""
    )


# ── 레인·대기열 정책(사용자 10-29 — docs/prd/runner.md rn-01·rn-02) — settings.yaml ops.run_docs(configure()가 읽음).
# 기본값은 설정 모델 pipeline.config.PipelineHostRunDocs와 같다(이 스크립트는 호스트 python이라 모델을 import하지 않음 — 시험이 둘을 대조).
RUN_DOCS_DEFAULTS = {
    "warm": 20,  # 진입 대기열 — 미리 받아 둘 문서 수(진행 중 제외)
    "struct_workers": 2,  # 구조화·적재 스레드 수
    "struct_backlog": None,  # 중간 대기열 상한(파싱 끝·구조화 대기) — 비우면 구조화 워커 × 2, 0 = 상한 없음
    "vlm_cap": 2,  # vlm 문서 동시 파싱 상한(gpu 예산)
    "light_dedicated": 1,  # 레인별 전담 워커(자기 레인 문서만)
    "light_shared": 1,  # 레인별 공유 워커(자기 레인 먼저, 비면 다른 레인에서 가져옴)
    "medium_dedicated": 1,
    "medium_shared": 1,
    "vlm_dedicated": 1,
    "vlm_shared": 1,
}
LANES = ("light", "medium", "vlm")
WARM_TARGET, STRUCT_WORKERS, VLM_CAP = RUN_DOCS_DEFAULTS["warm"], RUN_DOCS_DEFAULTS["struct_workers"], RUN_DOCS_DEFAULTS["vlm_cap"]
LANE_WORKERS = {c: (RUN_DOCS_DEFAULTS[f"{c}_dedicated"], RUN_DOCS_DEFAULTS[f"{c}_shared"]) for c in LANES}  # 레인 → (전담, 공유)
_BACKLOG_SETTING = RUN_DOCS_DEFAULTS["struct_backlog"]  # main()이 STRUCT_BACKLOG로 풂(구조화 워커 수 인자가 덮은 뒤)
STRUCT_BACKLOG = 0
NO_CLEANUP = False
CPU_GATE = 1.3  # 2026-10-23 사용자 지정 — 파이프라인 게이트 기본 · 조정 시 --cpu-gate 1.1
_class: dict = {}  # seq → "light"/"medium"/"vlm"(warm 시점 분류)
_scan: set = set()  # seq — 스캔 판정된 PDF(vlm_page 대상)만 담음(2026-10-23 사용자 지정)

LANEQ = {c: __import__("collections").deque() for c in LANES}  # 레인별 대기 문서(dispatched 순서)
_struct_q: "queue.Queue" = queue.Queue()  # 중간 대기열 — 파싱 끝·구조화 대기(main()이 씀)
MCP_JOBS_DIR = None  # MCP parse_document 업로드 작업 경로 — configure()(mcp.host.jobs_dir, 없으면 결과 폴더/mcp_parse/jobs — data-pipeline-parse의 mcp_parse_service 공유 볼륨)
_mcp_pause = False  # 2026-10-23 사용자 지정 — MCP 업로드 파싱 중 medium 레인 완보(사람 대기 응답 우선)
_last_write: dict = dict()  # 방어용 마지막 활동 시각 저장
_lane_inflight = {"light": 0, "medium": 0, "vlm": 0}


def _lane_total():
    with _warm_lock:
        return sum(len(q) for q in LANEQ.values())


_warm_lock = threading.Condition()
_warmed: list = []  # 다운로드 완료·미시작 문서 seq(대기열)
_warming: set = set()  # 지금 다운로드 진행 중인 seq(마지막 문서 조기 종료 방지)
_next_warm = 0  # 다음에 받을 seq
_stop = threading.Event()
_stats_lock = threading.Lock()


def mark(seq, event, **extra):
    """단계 이벤트 기록(2026-10-22 사용자 지정 — queue 대기·단계별 소요 로그) → doc_stats.jsonl"""
    rec = {"seq": seq, "event": event, "time": time.time(), **extra}
    with _stats_lock:
        with (PROG / "doc_stats.jsonl").open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def depth(event):
    """대기열 깊이 한 줄(rn-02) → queue_depth.jsonl — 레인별 [대기, 진행]·받는 중·구조화 대기. 상태가 바뀌는 자리(dispatch·
    pick·파싱 끝·구조화 넣기·꺼내기)에서 부른다. _warm_lock은 재진입 가능(Condition 기본 RLock)."""
    with _warm_lock:
        rec = {
            "time": time.time(),
            "event": event,
            "lanes": {c: [len(LANEQ[c]), _lane_inflight[c]] for c in LANES},
            "warming": len(_warming),
            "struct_wait": _struct_q.qsize(),
        }
    with _stats_lock:
        with (PROG / "queue_depth.jsonl").open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec) + "\n")


def pick_lane(own, shared, queues, inflight, vlm_cap):
    """다음 문서를 꺼낼 레인(없으면 None) — 자기 레인 먼저, 공유 워커만 자기 레인이 비었을 때 가장 긴 다른 레인에서(rn-01).
    vlm 문서는 진행 중이 vlm_cap이면 건너뜀(전담 워커도)."""
    order = [own] + (sorted((c for c in queues if c != own), key=lambda c: -len(queues[c])) if shared else [])
    for c in order:
        if queues[c] and not (c == "vlm" and inflight["vlm"] >= vlm_cap):
            return c
    return None


def run_docs_policy(doc):
    """settings.yaml ops.run_docs(모델 pipeline.host.run_docs) → (값, 문제 목록). 비운 칸은 RUN_DOCS_DEFAULTS. 글자 그대로 읽으므로(BaseLoader) 정수로 바꿈."""
    sec = _yget(doc, "pipeline.host.run_docs")
    sec = sec if isinstance(sec, dict) else {}
    vals, probs = {}, []
    for k, d in RUN_DOCS_DEFAULTS.items():
        v = sec.get(k)
        if v in (None, ""):
            vals[k] = d
            continue
        try:
            vals[k] = int(v)
        except ValueError:
            vals[k] = -1
        if vals[k] < 0:
            probs.append(f"pipeline.host.run_docs.{k} 형식 오류 — 0 이상 정수만")
    if probs:
        return vals, probs
    for k in ("warm", "vlm_cap"):  # 0이면 문서를 안 받거나(warm) vlm 레인을 아무도 안 집어 배치가 끝나지 않음(PR #7 리뷰)
        if vals[k] < 1:
            probs.append(f"pipeline.host.run_docs.{k} — 1 이상만")
    shared = sum(vals[f"{c}_shared"] for c in LANES)
    for c in LANES:  # 어느 워커도 못 집는 레인이 있으면 그 큐가 안 비어 배치가 끝나지 않음
        if vals[f"{c}_dedicated"] + shared < 1:
            probs.append(f"pipeline.host.run_docs — {c} 레인을 처리할 워커가 없음({c}_dedicated와 모든 *_shared가 0)")
    return vals, probs


def apply_policy(vals):
    """run_docs_policy() 값 → 모듈 값(configure()가 부름)."""
    global WARM_TARGET, STRUCT_WORKERS, VLM_CAP, LANE_WORKERS, _BACKLOG_SETTING
    WARM_TARGET, STRUCT_WORKERS, VLM_CAP = vals["warm"], vals["struct_workers"], vals["vlm_cap"]
    LANE_WORKERS = {c: (vals[f"{c}_dedicated"], vals[f"{c}_shared"]) for c in LANES}
    _BACKLOG_SETTING = vals["struct_backlog"]


def stack_check():
    """엔진 구성 파일 확인 — 시작 때 한 번(파싱 컨테이너 안 show-stack — 파일을 못 읽거나 모양이 틀리면 종료 2, 시작하지 않음).
    없는 엔진은 파싱 입구가 거부한다(stackcfg.resolve)."""
    rc, _, err = sh(f"{DOCKER} exec {PARSE_C} bash -c 'cd /app && PYTHONPATH=/app/deploy python -m pipeline.cli show-stack'", timeout=120)
    if rc != 0:
        raise SystemExit(f"[run_docs] 엔진 구성 파일을 읽지 못함(종료 코드 {rc}) — {(err or '').strip()[-200:]}")


def sh(cmd, timeout=1800, log=None):
    """셸 명령 — (rc, stdout, stderr). log를 주면 stdout(±stderr)을 그 파일에."""
    kw = {}
    if log:
        f = open(log, "a", encoding="utf-8", errors="replace")
        kw = dict(stdout=f, stderr=subprocess.STDOUT)
    else:
        kw = dict(capture_output=True, text=True)
    try:
        r = subprocess.run(cmd, shell=True, timeout=timeout, **kw)
        out, err = (None, None) if log else (r.stdout, r.stderr)
        return r.returncode, out, err
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT"
    finally:
        if log:
            f.close()


def now():
    return datetime.datetime.now()


def log(msg):
    print(f"[{now():%H:%M:%S}] {msg}", flush=True)
    with (PROG / "progress.log").open("a", encoding="utf-8") as fp:
        fp.write(f"[{now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def edw_list(keywords):
    """EDW FileStorageMap 전체(파일 크기 오름차순) — make_batch.py와 같은 질의·순서."""

    conds = " OR ".join(f"LOWER(original_filename) LIKE '%{k.lower()}%'" for k in keywords)
    sql = (
        f"SELECT id, s3_key, original_filename, file_size FROM AI.FileStorageMap "
        f"WHERE ({conds}) AND file_size IS NOT NULL ORDER BY file_size ASC"
    )
    conn = _edw_connect()  # S7e1 — 설정 파일의 parsing-meta 접속(옛 코드 기본값 — 운영 접속 값·비밀 삭제, D-028 ⑨)
    cur = conn.cursor(as_dict=True)
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


def edw_done_keys():
    """EDW AI.ParsingMeta에서 ok·parallel 종료된 source_key 집합(2026-10-22 사용자 지정 — 재실행 skip용)."""

    conn = _edw_connect()  # S7e1 — 설정 파일의 parsing-meta 접속(옛 코드 기본값 — 운영 접속 값·비밀 삭제, D-028 ⑨)
    cur = conn.cursor()
    cur.execute("SELECT COL_LENGTH('AI.ParsingMeta', 'source_key')")  # 11-02 — 원본 키 칸 이름 바꾸기(source_key → s3_key, C-76) 전후 모두
    kc = "source_key" if cur.fetchone()[0] is not None else "s3_key"
    cur.execute(f"SELECT {kc} FROM AI.ParsingMeta WHERE parse_status IN ('ok','partial')")
    keys = {r[0] for r in cur.fetchall()}
    conn.close()
    return keys


def write_envfile():
    """data-pipeline-parse 컨테이너(S6b — 옛 data-parsing) env → docker run용 --env-file. 여러 줄 값(PM_PATH_MAP)·HOSTNAME 제외 —
    파싱 컨테이너는 publish를 안 돌고, publish는 docker exec(compose env 그대로)로 돌리므로 문제없음."""
    rc, out, _ = sh(
        f"{DOCKER} inspect " + PARSE_C + " --format '{{json .Config.Env}}'", timeout=30
    )  # docker 템플릿 {{…}} 그대로(f-string 아님)
    envs = json.loads(out.strip())
    ENVFILE.parent.mkdir(parents=True, exist_ok=True)
    with ENVFILE.open("w", encoding="utf-8") as fp:
        for e in envs:
            k, _, v = e.partition("=")
            if k in ("HOSTNAME", "PM_PATH_MAP"):
                continue
            fp.write(f"{k}={v}\n")
    return len(envs)


def write_doc_csv(row, path):
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "s3_key", "original_filename", "file_size"])
        w.writerow([row["id"], row["s3_key"], row["original_filename"], row["file_size"]])


def warm_one(seq, row):
    """문서 1개를 warm에 미리 받기(source warm CLI — 파싱 컨테이너 env 그대로)."""
    d = DOCFLOW / f"{seq}"
    d.mkdir(parents=True, exist_ok=True)
    write_doc_csv(row, d / "batch.csv")
    if (WARM / (hashlib.sha1(f"{WARM_BUCKET}|{row['s3_key']}".encode()).hexdigest() + ".bin")).exists() and (d / ".warmed").exists():
        return True
    rc, _, err = sh(warm_cmd(seq), timeout=900, log=PROG / "warm.log")
    if rc == 0:
        (d / ".warmed").touch()
    else:
        log(f"doc#{seq} warm 실패 — 파싱 시 자체 다운로드 폴백 ({str(err)[-100:]})")
    return rc == 0


def _class_cache():
    """분류 캐시(s3_key → heavy/light) — 재실행 시 probe 재사용(2026-10-22)."""
    p = PROG / "docflow_class.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _class_save(cache):
    p = PROG / "docflow_class.json"
    p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def classify_doc(seq, row, cache=None):
    """OCR 필요도 사전 분류(2026-10-22 사용자 지정, 2026-10-23 확장) —
    · 텍스트형(txt/html/eml 등): 즉시 light
    · PDF: 첫 3쪽 텍스트 레이어 평균 300자 → 스캔 판정(heavy)
    · 오피스 zip(docx/xlsx/xlsm/pptx 등): 내장 media ≥ 8개 또는 ≥ 800KB → heavy(이미지 많은 docx 사용자 지적)
    · probe 결과 마지막 줄만 판독(fitz 경고 오염 방지) · 실패는 보수적 heavy · 캐시(s3_key) 우선."""
    import pathlib

    ext = pathlib.Path(row["original_filename"].rsplit("/", 1)[-1]).suffix.lower()
    probe_ext = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".pptx", ".ppt", ".docm")
    # 2026-10-23 3클래스(사용자 지정) — vlm(GPU집중: 스캔/미디어/pptx) · medium(CPU집중: probe light + 크기 초과) · light
    meta_heavy_kb = {".mht": 300, ".docx": 300, ".doc": 300, ".xlsx": 500, ".xlsm": 500, ".xls": 500, ".pdf": 1024}
    size_kb = (row.get("file_size") or 0) // 1024
    meta_heavy = ext in (".pptx", ".ppt") or size_kb >= meta_heavy_kb.get(ext, 1 << 30)
    if ext in (".txt", ".hwpx", ".hwp", ".csv", ".eml", ".msg", ".html", ".htm"):
        cls = "light"
    elif ext in probe_ext:
        bin_name = hashlib.sha1(f"{WARM_BUCKET}|{row['s3_key']}".encode()).hexdigest() + ".bin"
        rc, out, _ = sh(
            f"{DOCKER} exec {PARSE_C} python3 /app/deploy/pipeline/extract/docflow_probe.py /app/output/_warm/{bin_name}", timeout=60
        )
        probe = next((ln.strip() for ln in reversed((out or "").splitlines()) if ln.strip() in ("heavy", "light")), "heavy")
        if ext == ".pdf" and probe == "heavy":
            _scan.add(seq)  # 2026-10-23 — OCR 대체가 필요한 스캔 PDF 표시
        cls = "vlm" if (probe == "heavy" or ext in (".pptx", ".ppt")) else ("medium" if meta_heavy else "light")
    else:
        cls = (
            "vlm"  # 모르는 형식 — 보수적으로 vlm(예산 캡 안에서 처리)                                     # 모르는 형식 — 보수적으로 heavy
        )
    if cache is not None and row["s3_key"] in cache:
        cls = cache[row["s3_key"]]
    elif cache is not None:
        cache[row["s3_key"]] = cls
        _class_save(cache)
    _class[seq] = cls
    mark(seq, "classify", ocr=cls)
    return cls


def downloader(rows, order):
    """대기열 유지 스레드 — 지정 문서 순서대로 WARM_TARGET개까지 미리 받아 둔다(진행중 제외)."""
    global _next_warm
    _cache = _class_cache()
    ptr = 0
    with _warm_lock:
        _next_warm = order[ptr] if order else 10**12
    while not _stop.is_set():
        with _warm_lock:
            if ptr >= len(order):
                if _lane_total() == 0 and not any(_lane_inflight.values()):
                    return
                _warm_lock.wait(5)
                continue
            if _lane_total() >= WARM_TARGET:
                _warm_lock.wait(5)
                continue
            seq = order[ptr]
            ptr += 1
            _next_warm = order[ptr] if ptr < len(order) else 10**12
            _warming.add(seq)
        row = rows[seq]
        t_w = time.time()
        ok = warm_one(seq, row)
        mark(seq, "warm_end", ok=ok, sec=round(time.time() - t_w, 1))
        classify_doc(seq, row, cache=_cache)  # OCR 필요도 사전 분류(캐시 우선) → 워커 배분용
        with _warm_lock:
            LANEQ[_class.get(seq) or "light"].append(seq)
            mark(seq, "dispatched")
            _warming.discard(seq)
            _warm_lock.notify_all()
        depth("dispatch")


def _sweep_orphan(seq):
    """docker exec 고아 방지(2026-10-22) — 타임아웃·실패 시 이 문서 PIPE_OUT_ROOT env를 가진
    컨테이너 내 프로세스(bash·python·soffice까지 환경 상속)를 전부 종료."""
    sh(sweep_cmd(seq), timeout=30)


def parse_one(seq, row):
    """문서 1개 파싱 — 공유 파싱 컨테이너(PARSE_C) 안에서 워커별 분리(경로 격리).
    PIPE_OUT_ROOT + DOC_DIR_PREPARED로 문서별 출력 루트 분리(pipeline이 두 env를 지원).
    문서당 VLM 6·OCR 쪽 2(쓰레드 1)·vlm_page off·OCR_DPI=120."""
    d = DOCFLOW / f"{seq}"
    d.mkdir(parents=True, exist_ok=True)
    write_doc_csv(row, d / "batch.csv")
    doc_log = PROG / f"doc_{seq}.log"
    t0 = time.time()
    mark(seq, "parse_start")
    print(f"[{now():%H:%M:%S}] doc#{seq} 파싱 시작 — {row['original_filename'][:44]}", flush=True)
    # 2026-10-23 — light PIPE_PROCS는 기본 4 유지(코어 4와 정합) · 별도 오버라이드 없음
    gate = (
        "9" if _class.get(seq) == "light" else str(CPU_GATE)
    )  # 2026-10-23 사용자 지정 — light 전용채널은 게이트 bypass(heavy의 CPU/VLM 대기 틈 즉시 소화)
    chan = _class.get(seq) or "light"
    rc, _, _ = sh(parse_cmd(seq, chan, seq in _scan, gate), timeout=2700, log=doc_log)
    if rc != 0:
        _sweep_orphan(seq)
    rep = d / "parse" / "_rep"
    n = len([p2 for p2 in rep.glob("*.json") if p2.name != "index.json"]) if rep.exists() else 0
    ok = rc == 0 and n > 0
    mark(seq, "parse_end", ok=ok, rep=n, sec=round(time.time() - t0, 1))
    log(f"doc#{seq} 파싱 {'OK' if ok else 'FAIL'}({(time.time() - t0) / 60:.1f}분) · rep {n}건 — {row['original_filename'][:44]}")
    return ok, d


def structure_one(seq, row, enq_t=None):
    """구조화+적재+publish(문서 경계 없이). 끝나면 임시·warm 정리. enq_t=파싱 완료 시각(구조화 대기 계산)."""
    t0 = time.time()
    wait = round(t0 - enq_t, 1) if enq_t else 0
    mark(seq, "struct_start", queue_wait=wait)
    rc, _, err = sh(struct_cmd(seq), timeout=1800, log=PROG / f"doc_{seq}.log")
    ok = rc == 0
    mark(seq, "struct_end", ok=ok, sec=round(time.time() - t0, 1))
    log(
        f"doc#{seq} 구조화+적재 {'OK' if ok else 'FAIL'}(대기 {wait / 60:.1f}분 · 실행 {(time.time() - t0) / 60:.1f}분)"
        + ("" if ok else f" — {str(err)[-150:]}")
    )
    t1 = time.time()
    mark(seq, "pub_start")
    if ok:
        rc, _, err = sh(publish_cmd(seq), timeout=900, log=PROG / f"doc_{seq}.log")
        ok = rc == 0
        mark(seq, "pub_end", ok=ok, sec=round(time.time() - t1, 1))
        log(f"doc#{seq} publish {'OK' if ok else 'FAIL'}({(time.time() - t1) / 60:.1f}분)" + ("" if ok else f" — {str(err)[-150:]}"))
    cleanup_doc(seq, row)
    mark(seq, "done")
    return ok


def cleanup_doc(seq, row):
    """문서 종료 — docflow 임시·warm 잔여 삭제. 컨테이너(uid 10001)가 만든 파일은 호스트가 못 지우므로
    docker exec(같은 공유 볼륨 마운트, 그 uid로 실행)로 지우고 잔여만 호스트가 마무리."""
    if NO_CLEANUP:
        return
    bin_name = hashlib.sha1(f"{WARM_BUCKET}|{row['s3_key']}".encode()).hexdigest() + ".bin"
    sh(f"{DOCKER} exec {PARSE_C} bash -c 'rm -rf /app/output/docflow/{seq} ; rm -f /app/output/_warm/{bin_name}'", timeout=60)
    shutil.rmtree(DOCFLOW / f"{seq}", ignore_errors=True)
    (WARM / bin_name).unlink(missing_ok=True)


def pg_count():
    rc, out, _ = sh(
        f"{DOCKER} exec {PG_CONTAINER} psql -U {PG_USER} -d {PG_DB} -Atc "
        f"'SELECT (SELECT count(*) FROM {PG_SCHEMA}.doc), (SELECT count(*) FROM {PG_SCHEMA}.chunk)'",
        timeout=60,
    )  # S7e1 — 설정 칸(옛 고정 postgres·pgvector·category)
    try:
        parts = out.replace("|", " ").split()
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


CODE_MARKER = Path("pipeline") / "extract" / "run_all.py"  # pipeline 배치(S4)에 늘 있는 파일(컨테이너 안 /app/deploy/ 아래 같은 자리)


def code_layout_problems(code=None, containers=(PARSE_C, STRUCT_C)):
    """I3(V2-R4) — 이 러너는 pipeline 배치(S4 10-26, 새 이미지 판 — 그 전 I2 data_etl 배치)를 전제로 `docker exec … python -m pipeline.…`를 부른다.
    컨테이너가 마운트하는 코드 폴더(PATCH_CODE/app/deploy)와 떠 있는 컨테이너가 그 배치인지 시작 전에 본다 — 문제 목록(빈 목록이면 통과).
    I4(V3 R1): PATCH_CODE 폴더를 이 호스트에서 볼 수 없으면 폴더 확인은 건너뛰고 컨테이너 확인(실제 마운트)만 믿는다.
    I4b(V4 R2): 폴더가 아니라 파일(CODE_MARKER)로 본다 — docker는 bind 마운트 원본이 없으면 빈 폴더를 만들어 붙여 `test -d`가 통과한다."""
    code = Path(code) if code else PATCH_CODE
    probs = []
    if code.is_dir():
        deploy = code / "app" / "deploy"
        if not deploy.is_dir():  # op-06(10-30) — 개발 서버 코드 폴더는 저장소 트리 그대로(실행 이미지가 /app/deploy에 붙임)
            deploy = code
        if not (deploy / CODE_MARKER).is_file():
            probs.append(
                f"코드 폴더 {deploy}에 {CODE_MARKER.as_posix()} 없음 — 새 이미지 판(S4 pipeline)과 코드 폴더를 같은 때에 반입했는지 확인"
            )
        old = [d for d in ("data_parsing", "data_structure") if (deploy / d).exists()]
        if old:
            probs.append(f"코드 폴더 {deploy}에 옛 폴더 {', '.join(old)}가 남아 있음 — I2 전 배치가 섞임(반입 절차 확인)")
    else:
        log(f"[안내] 코드 폴더 {code}(PATCH_CODE)를 이 호스트에서 볼 수 없음 — 폴더 확인은 건너뛰고 컨테이너 확인만")
    for c in containers:
        rc, _, _ = sh(f"{DOCKER} exec {c} test -f /app/deploy/{CODE_MARKER.as_posix()}", timeout=60)
        if rc != 0:
            probs.append(
                f"컨테이너 {c}에 /app/deploy/{CODE_MARKER.as_posix()} 없음(rc {rc}) — 새 이미지·compose.patch.yml 마운트로 다시 띄웠는지 확인"
            )
    return probs


def mcp_busy():
    """MCP 업로드 처리 중이면 True(공유 볼륨 mcp_parse/jobs/<id>의 파일 mtime이 30초 내 갱신).
    5초마다 불리므로 작업 폴더 전체가 아니라 이름 날짜(<YYYYMMDD>-…, mcp_parse_service)가 어제·오늘·내일인 폴더만 본다(rn-04 —
    지난 날의 끝난 작업 파일까지 stat하지 않게, 호스트·컨테이너 시간대가 달라도 걸리게 앞뒤 하루)."""
    # ponytail: 날짜 이름 거르기 — 하루 넘게 도는 MCP 작업은 놓침(작업은 분 단위), 필요하면 작업 서비스가 심장 박동 파일을 씀
    if not MCP_JOBS_DIR.exists():
        return False
    now = time.time()
    recent, days = now - 30, {time.strftime("%Y%m%d", time.localtime(now + d * 86400)) for d in (-1, 0, 1)}
    try:
        for job in MCP_JOBS_DIR.iterdir():
            if job.name[:8] not in days:
                continue
            for p in job.rglob("*"):
                try:
                    if p.is_file() and p.stat().st_mtime > recent:
                        return True
                except OSError:  # 훑는 사이 지워진 파일(_purge_old) — 그 파일만 건너뜀(나머지 작업 폴더는 계속 봄)
                    continue
    except OSError:
        pass
    return False


def _mcp_pause_monitor():
    """5초마다 MCP 작업 감지해 _mcp_pause 토글(사람 대기 파싱 → medium 레인 완보)."""
    global _mcp_pause
    while not _stop.is_set():
        _mcp_pause = mcp_busy()
        time.sleep(5)


def _thread_error(stage, seq, ex):
    """작업 스레드가 예외 처리·기록 중 다시 예외를 만났을 때 — 로그 파일도 못 쓸 수 있어 표준 오류로만(스레드는 계속)."""
    print(f"[run_docs] doc#{seq} {stage} 스레드 예외(계속) — {type(ex).__name__}: {str(ex)[:160]}", file=sys.stderr, flush=True)


def _safe_cleanup(seq, row):
    """실패 문서 정리 — 정리 자체가 실패해도(디스크 가득·docker 없음) 작업 스레드는 계속(집계는 호출자가 이미 함)."""
    try:
        cleanup_doc(seq, row)
    except Exception as ex:
        _thread_error("정리", seq, ex)


def main():
    global WARM_TARGET, STRUCT_WORKERS, NO_CLEANUP, CPU_GATE, STRUCT_BACKLOG, CODE_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-offset", type=int, default=1072)
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="쓰지 않음(옛 인자 — 옛 호출이 깨지지 않게 받기만 함, rn-04) — 레인 워커 수는 settings.yaml ops.run_docs",
    )
    ap.add_argument("--warm", type=int, default=None, help="진입 대기열(미리 받을 문서 수) — 기본 settings.yaml ops.run_docs.warm(20)")
    ap.add_argument("--struct-workers", type=int, default=None, help="구조화 스레드 수 — 기본 settings.yaml ops.run_docs.struct_workers(2)")
    ap.add_argument("--filter", default="RFP,proposal")
    ap.add_argument("--limit", type=int, default=0, help="시험 — 이 개수만 처리")
    ap.add_argument("--seqs", default="", help="임의 문서 집합(쉼표 seq 목록) — 지정 시 연속 범위 대신 이 목록만 처리")
    ap.add_argument("--cpu-gate", type=float, default=1.3, help="파이프라인 CPU 게이트(CPU_MAX_LOAD) — 기본 1.3, 조정할 때 --cpu-gate 1.1")
    ap.add_argument("--skip-done", action="store_true", help="EDW ParsingMeta에 ok·partial로 이미 끝난 문서는 건너뜀(재실행 시간 절약)")
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--settings", default=None, help="서버 settings.yaml(기본 SETTINGS_FILE 또는 $SERVER_ENV_DIR/settings.yaml — S7e1)")
    ap.add_argument(
        "--code",
        default=None,
        help="코드 폴더(설정 배치 모듈을 찾음 — 기본: 이 스크립트가 든 코드 폴더, 없으면 /srv/rag/code/live · op-10)",
    )
    a = ap.parse_args()
    CODE_DIR = Path(a.code) if a.code else None
    bad = configure(a.settings)
    if bad:
        for msg in bad:
            print(f"[중단] {msg}", flush=True)
        raise SystemExit(2)
    NO_CLEANUP, CPU_GATE = a.no_cleanup, a.cpu_gate
    if a.warm is not None:
        WARM_TARGET = a.warm
    if a.struct_workers is not None:
        STRUCT_WORKERS = a.struct_workers
    STRUCT_BACKLOG = _BACKLOG_SETTING if _BACKLOG_SETTING is not None else 2 * max(1, STRUCT_WORKERS)

    PROG.mkdir(parents=True, exist_ok=True)
    probs = code_layout_problems()
    if not MCP_JOBS_DIR.is_dir():
        log(
            f"[안내] MCP 업로드 작업 폴더 {MCP_JOBS_DIR} 없음 — MCP 업로드 감지(medium 레인 양보) 꺼짐, 다른 자리면 settings.yaml ops.mcp_host.jobs_dir"
        )
    if probs:
        for msg in probs:
            log(f"[중단] {msg}")
        raise SystemExit(2)
    os.umask(0)  # 컨테이너( uid 10001 rag )가 /app/output(=docflow/<seq>)에 쓰려면 777 필요
    WARM.mkdir(mode=0o777, parents=True, exist_ok=True)
    DOCFLOW.mkdir(mode=0o777, parents=True, exist_ok=True)
    rows = edw_list([k.strip() for k in a.filter.split(",") if k.strip()])
    n_env = write_envfile()
    stack_check()
    start = a.start_offset
    if start >= len(rows):
        log(f"start-offset {start} ≥ 대상 {len(rows)}건 — 종료")
        return
    log(
        f"=== 문서별 flow 시작: offset={start} · 남은 {len(rows) - start}건 · 레인(전담/공유) "
        f"{' '.join(f'{c} {d}/{s}' for c, (d, s) in LANE_WORKERS.items())} · vlm 동시 {VLM_CAP} · "
        f"warm {WARM_TARGET} · 구조화 {STRUCT_WORKERS}동시(대기 상한 {STRUCT_BACKLOG or '없음'}) · env {n_env}개 · {'제한 ' + str(a.limit) + '건' if a.limit else '제한 없음'} ==="
    )

    order = (
        sorted(int(x) for x in a.seqs.split(",") if x.strip())
        if a.seqs
        else list(range(start, len(rows) if not a.limit else min(len(rows), start + a.limit)))
    )
    if a.skip_done:
        done = edw_done_keys()
        before = len(order)
        order = [s for s in order if rows[s]["s3_key"] not in done]
        log(f"skip-done: {before - len(order)}건 이미 완료(ok·partial) — 남은 {len(order)}건 처리")
    if not order:
        log("처리할 문서 없음 — 종료")
        return
    t_all = time.time()
    tf = threading.Thread(target=downloader, args=(rows, order), daemon=True)
    tf.start()

    cnt = {"ok": 0, "parse_fail": 0, "struct_fail": 0}
    struct_q = _struct_q

    def _struct_loop():
        while True:
            item = struct_q.get()
            depth("struct_get")
            with _warm_lock:
                _warm_lock.notify_all()  # 중간 대기 하나 줄어듦 → 상한에서 기다리던 레인 워커
            if item is None:
                struct_q.task_done()
                return
            seq, row, enq_t = item
            try:
                try:
                    ok = structure_one(seq, row, enq_t)
                except Exception as ex:
                    log(f"doc#{seq} 구조화 예외 — {type(ex).__name__}: {str(ex)[:120]}")
                    _safe_cleanup(seq, row)
                    ok = False
                with _warm_lock:
                    if ok:
                        cnt["ok"] += 1
                        if cnt["ok"] % 5 == 0:
                            nd, nc = pg_count()
                            log(f"PG 누적: doc={nd} chunk={nc}")
                    else:
                        cnt["struct_fail"] += 1
            except (
                Exception
            ) as ex:  # 예외 처리·기록 중 예외(디스크 가득 등)도 스레드를 죽이지 않게 — 죽으면 struct_q.join()이 안 끝남(S12 리뷰)
                _thread_error("구조화", seq, ex)
            finally:
                struct_q.task_done()

    for _ in range(max(1, STRUCT_WORKERS)):
        threading.Thread(target=_struct_loop, daemon=True).start()

    def _one(doc_seq, row_doc):
        try:
            ok, _d = parse_one(doc_seq, row_doc)
            enq_t = time.time()
        except Exception as ex:
            log(f"doc#{doc_seq} 파싱 예외 — {type(ex).__name__}: {str(ex)[:120]}")
            ok = False
        if ok:
            struct_q.put((doc_seq, row_doc, enq_t))
            depth("struct_put")
        else:
            with _warm_lock:
                cnt["parse_fail"] += 1
            _safe_cleanup(doc_seq, row_doc)

    # ── 레인 워커(사용자 10-29 — rn-01·rn-02): 레인마다 전담(자기 레인만)·공유(자기 레인 먼저, 비면 가장 긴 다른 레인 — pick_lane).
    # 구조화 대기가 STRUCT_BACKLOG 이상이면 새 파싱을 시작하지 않음. MCP 업로드 처리 중에는 medium 전담 워커가 쉼(2026-10-23 사용자 지정).
    def _flow_done():
        with _warm_lock:
            return (
                _next_warm >= 10**12
                and not _warming
                and all(not q for q in LANEQ.values())
                and all(v == 0 for v in _lane_inflight.values())
            )

    def lane_worker(own, shared):
        while not _stop.is_set():
            seq = None
            with _warm_lock:
                hold = (own == "medium" and not shared and _mcp_pause) or (STRUCT_BACKLOG and _struct_q.qsize() >= STRUCT_BACKLOG)
                c = None if hold else pick_lane(own, shared, LANEQ, _lane_inflight, VLM_CAP)
                if c is None:
                    if _flow_done():
                        return
                    _warm_lock.wait(5)
                    continue
                seq = LANEQ[c].popleft()
                _lane_inflight[_class.get(seq) or "light"] += 1
                depth("pick")
                _warm_lock.notify_all()  # 파싱 1개 시작 → warm 보충 신호
            try:
                _one(seq, rows[seq])
            except (
                Exception
            ) as ex:  # 예외 처리·기록 중 예외도 레인을 죽이지 않게 — 죽으면 큐가 안 비어 _flow_done() 대기가 안 끝남(S12 리뷰)
                _thread_error("파싱", seq, ex)
            finally:
                with _warm_lock:
                    _lane_inflight[_class.get(seq) or "light"] -= 1
                    _warm_lock.notify_all()  # 슬롯 반납 → warm 보충 신호
                depth("parse_end")

    threading.Thread(target=_mcp_pause_monitor, daemon=True, name="mcp-watch").start()  # 2026-10-23 — MCP 업로드 감시(medium 전담 워커 쉼)

    lane_threads = []
    for c in LANES:
        ded, shr = LANE_WORKERS[c]
        for shared in [False] * ded + [True] * shr:
            t = threading.Thread(target=lane_worker, args=(c, shared), daemon=True, name=f"lane-{c}-{'shared' if shared else 'own'}")
            t.start()
            lane_threads.append(t)
    while not _flow_done() and not _stop.is_set():
        time.sleep(5)
    for t in lane_threads:
        t.join(timeout=30)

    for _ in range(max(1, STRUCT_WORKERS)):  # 파싱 전부 끝 → 구조화 스레드 종료 센티널
        struct_q.put(None)
    struct_q.join()
    _stop.set()
    with _warm_lock:
        _warm_lock.notify_all()
    tf.join(timeout=5)
    nd, nc = pg_count()
    done = cnt["ok"] + cnt["parse_fail"] + cnt["struct_fail"]
    log(
        f"=== 문서별 flow 끝: {done}건(완료 {cnt['ok']} · 파싱실패 {cnt['parse_fail']} · 구조실패 {cnt['struct_fail']}) · "
        f"{(time.time() - t_all) / 60:.1f}분 · PG doc={nd} chunk={nc} · 문서당 평균 {(time.time() - t_all) / max(done, 1) / 60:.1f}분 ==="
    )


if __name__ == "__main__":
    main()
