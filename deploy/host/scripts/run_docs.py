#!/usr/bin/env python3
"""문서별 flow 러너(2026-10-22 사용자 지정 설계) — 배치 장벽 제거.

1) 대기열 — 앞으로 나올 문서 WARM_TARGET(기본 20)개를 미리 warm 다운로드. 진행중 문서는 대기 개수에서 제외.
   파싱이 하나 시작되면 다음 문서를 즉시 받아 개수를 유지. 문서 flow가 끝나면 docflow 임시 디렉토리·warm 잔여 삭제.
2) 파싱 flow — 레인 light·medium·vlm(warm 때 분류)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴
   다른 레인에서 가져옴) — 기본 레인마다 1·1(사용자 10-29, docs/prd/ops.md rn-01). vlm 문서는 동시 VLM_CAP(2)까지.
   구조화 대기 문서가 STRUCT_BACKLOG(기본 구조화 워커 × 2)개 이상이면 새 파싱을 시작하지 않고 기다림(rn-02).
   레인·대기 길이는 상태가 바뀔 때마다 batch_progress/queue_depth.jsonl에 한 줄(rn-02).
   값은 settings.yaml ops.run_docs(비우면 아래 RUN_DOCS_DEFAULTS) — --warm·--struct-workers 인자가 그 위를 덮음.
3) 문서별 순서(pl-24): 파싱 → silver 게시(publish — OS+EDW, 게시 스레드 1개) → 원본 삭제(게시 성공 뒤에만) →
   gold(build_bundle → pgvector_load, STRUCT_WORKERS(기본 2)개 스레드) → 임시 삭제. 배치 장벽 없이 끝나는 순서대로 흐름.
   파싱·게시 실패 = 원본(warm)을 남기고 로그에만, gold로 안 감 · gold 실패 = silver는 그대로(로그 — gold_status 칸은 DB 담당 C-81).
4) 종료 코드(pl-18): 0 = 대상 0건·모두 끝 · 1 = 실패 문서 있음 · 75 = 마감 도달(실패 없음) 또는 다른 run_docs가 도는 중
   (잠금 batch_progress/run_docs.lock — 사람이 돌린 실행과 새벽 배치가 겹치지 않게) · 2 = 설정 문제.

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
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# S7e1(사용자 10-27 Q8 · D-028 ⑨ · C-29 ⑨) — 운영 접속 값·비밀·운영 고정값을 코드에서 지우고 서버 settings.yaml에서 읽는다(configure() — 시작 때 한 번).
#   파일: --settings 또는 SETTINGS_FILE, 없으면 <루트>/settings.yaml(루트 = 코드 폴더의 부모 — op-13). 호스트 python에 PyYAML이 있어야 한다(pymssql처럼 —
#   refactor.md C-09). 필요한 칸이 없으면 칸 경로만 찍고 종료 코드 2(값은 찍지 않음). required.env.run_env가 dev·prd가 아니면 거부(로컬 실행 금지 — CLAUDE.md 3절).
#   docker exec로 부르는 상주 컨테이너(data-pipeline — 11-03 하나로)는 같은 파일을 붙여 읽으므로(compose x-settings) 명령 줄에 접속 값·비밀을 넣지 않는다(ps·로그에 안 남음).
#   작업 폴더(진행 기록 batch_progress/·batches/)는 settings.yaml ops.pipeline_host.run_docs_dir(비우면 이 스크립트 옆 test_space/ — 옛 자리), 결과 공유 폴더는
#   ops.host.output_root(RAG_OUT — 컨테이너 /app/output의 원본 그대로), 비우면 <루트>/output(settings_env.sh와 같음 — op-13).
TEST = PROG = DOCSPACE = DOCFLOW = WARM = None  # configure()가 채움
DOCKER = "docker"  # 컨테이너 명령 — configure()가 ops.host.docker(없으면 podman, 그것도 없으면 docker — op-10)로 채움
CODE_DIR = None  # --code(설정 배치 모듈 layout.py·이미지 경로 표를 찾을 코드 폴더 — 운영자 폴더에서 돌릴 때, op-10 · 기본 배치 경로 없음 — 사용자 11-02)
_EDW: dict = {}  # parsing-meta EDW 접속(호스트 pymssql — edw_list·edw_done_keys)
WARM_BUCKET = PG_CONTAINER = PG_USER = PG_DB = PG_SCHEMA = None  # warm 파일 이름의 원천 버킷 · 문서 수 세기(psql)
SETTINGS_REQUIRED = (  # (칸 경로, 무엇에 쓰나) — 없으면 시작 거부
    ("common.run_env", "실행 환경(dev·prd)"),
    ("common.connections.rdb.host", "EDW 서버 — 호스트 조회(읽기 계정, 사용자 10-29 ops.md#op-03)"),
    ("common.connections.rdb.database", "EDW DB"),
    ("common.connections.rdb.read.user", "EDW 읽기 계정"),
    ("common.connections.rdb.read.password", "EDW 읽기 계정 비밀번호"),
    ("common.connections.rdb.write.user", "EDW 쓰기 계정 — publish의 ParsingMeta INSERT(컨테이너)"),
    ("common.connections.rdb.write.password", "EDW 쓰기 계정 비밀번호(컨테이너)"),
    ("common.connections.object_storage.endpoint", "Object Storage 주소 — publish·warm(컨테이너)"),
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


def _code_root():
    """코드 폴더 — 찾는 순서(op-10): --code 폴더 > 이 스크립트가 든 코드 폴더(기본 배치 경로는 없음 — 사용자 11-02). 반환 (루트, common 폴더) —
    common은 <루트>/common(코드 폴더 = 저장소 트리 — 옛 app/deploy 배치는 11-03 지움)."""
    for r in (CODE_DIR, ROOT.parents[2] if len(ROOT.parents) > 2 else None):
        if r is not None and (Path(r) / "common" / "config" / "layout.py").is_file():
            return Path(r), Path(r) / "common"
    sys.exit("run_docs: common/config/layout.py 없음 — 코드 폴더 안에서 부르거나 --code <코드 폴더>로 알려 줄 것")


def _root():
    """서버 루트(op-13 — settings.yaml·edw_chain.yaml·output/이 바로 아래): settings_env.sh load_settings가 낸 RAG_ROOT, 없으면 같은 규칙(코드 폴더의 부모)."""
    r = os.environ.get("RAG_ROOT")  # env 남김 — 호스트 도구(settings_env.sh load_settings가 냄)
    return Path(r) if r else _code_root()[0].resolve().parent


def _inside(seq, sub=""):
    """컨테이너 쪽 문서 임시 폴더 <output_root>/_docflow/<seq>[/sub]."""
    return f"{_img('output_root')}/_docflow/{seq}" + (f"/{sub}" if sub else "")


@functools.cache
def _img(name):
    """컨테이너 안 약속 경로(사용자 11-02 — settings.IMAGE_PATHS 한 곳): 코드 폴더 deploy/host/scripts/host_keys.tsv(없으면 이 스크립트 옆)의 const 줄(deploy/release/hostkeys.py가 만듦)."""
    f = next((p for p in (_code_root()[0] / "deploy" / "host" / "scripts" / "host_keys.tsv", ROOT / "host_keys.tsv") if p.is_file()), None)
    if f is None:
        sys.exit("run_docs: host_keys.tsv 없음 — 코드 폴더(deploy/host/scripts/) 또는 이 스크립트 옆에 둘 것(--code)")
    rows = f.read_text(encoding="utf-8").splitlines()
    for row in rows:
        path, _, kind, *val = row.split("\t") if "\t" in row else ("", "", "")
        if kind == "const" and path == f"image.{name}":
            return val[0]
    sys.exit(f"run_docs: host_keys.tsv에 image.{name} 없음 — PYTHONPATH=. python deploy/release/hostkeys.py로 다시 만들 것")


def _app():
    return _img("code_root").rsplit("/", 1)[0]  # 컨테이너 작업 자리(코드 자리의 부모 — 이미지 WORKDIR)


@functools.cache
def _layout():
    """설정 배치 모듈(common/config/layout.py — 표준 라이브러리만)을 파일로 읽음 — 호스트 python은 pydantic이 없어 common 패키지를 import하지 않는다."""
    import importlib.util

    path = _code_root()[1]
    spec = importlib.util.spec_from_file_location("settings_layout", path / "config" / "layout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_settings(settings_file=None):
    """(사전, 문제) — 서버 settings.yaml을 쓴 글자 그대로 읽는다(BaseLoader — 스칼라는 모두 글자: `password: 0123`·`user: no`가 83·False로
    바뀌지 않게, 앱 설정 모델의 글자 칸 규칙과 같음 — S7e1 리뷰). 파일: settings_file > SETTINGS_FILE > <루트>/settings.yaml. 값은 찍지 않는다.
    파일 배치(required·역할 절 — op-08 ②)를 모델 배치(common·pipeline·mcp)로 바꿔 돌려준다 — 이 모듈의 칸 경로는 모델 경로."""
    path = Path(settings_file or os.environ.get("SETTINGS_FILE") or _root() / "settings.yaml")  # env 남김 — 설정 파일 자리 신호(5-2)
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
        return {}, f"설정 파일을 읽지 못함: {path} ({e.strerror}) — --settings 또는 SETTINGS_FILE·<루트>/settings.yaml"
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
    """작업 폴더(진행 기록 batch_progress/·batches/) — settings.yaml ops.pipeline_host.run_docs_dir(모델 pipeline.host.run_docs_dir), 비우면 이 스크립트 옆 test_space/(옛 자리)."""
    work = _yget(doc, "pipeline.host.run_docs_dir")
    return Path(work) if work else ROOT / "test_space"


def configure(settings_file=None):
    """서버 settings.yaml을 한 번 읽어 모듈 값(경로·접속)을 채운다 — 문제 목록(빈 목록이면 통과). 값은 찍지 않는다."""
    global TEST, PROG, DOCSPACE, DOCFLOW, WARM, MCP_JOBS_DIR, WARM_BUCKET, PG_CONTAINER, PG_USER, PG_DB, PG_SCHEMA
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
    # 컨테이너 /app/output 공유 볼륨 — load_settings가 낸 RAG_OUT(셸 env > common.host.output_root > <루트>/output), 없으면 같은 규칙
    DOCSPACE = Path(
        os.environ.get("RAG_OUT")  # env 남김 — 호스트 도구(settings_env.sh load_settings가 냄)
        or _yget(doc, "common.host.output_root")
        or _root() / "output"
    )
    DOCFLOW = DOCSPACE / "_docflow"  # 문서별 임시 디렉토리(종료 시 삭제)
    WARM = DOCSPACE / "_warm"  # SOURCE_WARM 대기열 저장소
    DOCKER = _yget(doc, "common.host.docker") or (
        "podman" if shutil.which("podman") else "docker"
    )  # op-10 — 셸 스크립트와 같은 순서(env 대신 설정)
    jobs = _yget(doc, "mcp.host.jobs_dir")
    MCP_JOBS_DIR = Path(jobs) if jobs else DOCSPACE / "_mcp_parse" / "jobs"
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


# 11-02 — 시작 때 코드 배치 확인(code_layout_problems·CODE_MARKER·PATCH_CODE)은 운영 마지막 버전에 없어 지움(사용자 규칙).
# S6b(D-020, 사용자 10-27) — 파이프라인 이미지가 하나(data-pipeline)로 합쳐지고 상주 컨테이너 이름이 바뀜(옛 data-parsing·data-structure).
# 11-03(사용자) — 상주 컨테이너 둘(data-pipeline-parse·data-pipeline-structure)을 하나로 합침: warm·파싱·게시·구조화·정리 모두 이 안에서 docker exec.
PIPE_C = "data-pipeline"  # docker exec 대상(compose.pipeline.yml 상주 서비스)

# S9 Step A(VS8b U-1, 사용자 10-28) — 컨테이너 안 앱이 읽는 설정 칸(옛 env 이름)은 명령 인자 `--set 이름=값`으로 준다(common.config.setarg —
# 그 python이 덮기 파일로 자기와 자식에게 넘김). 전에는 `bash -c 'X=값 python …'` env로 줬는데 S7e2부터 앱이 env의 옛 이름을 읽지 않아
# 문서별 결과 폴더(PIPE_OUT_ROOT 등)·동시 수·후보정·CPU 게이트가 효과가 없었다. 비밀 칸은 --set이 거부한다(명령 줄은 ps·로그에 남음).
EMBED_SET = ("EMBED_CONCURRENCY=6", "EMBED_BATCH=32", "BM25_THREADS=3")
PARSE_SET = (
    "VLM_MAX_CONCURRENCY=8",  # 11-04 VLM 통일 — 옛 VLM_GLOBAL_CONCURRENCY(전역 합) · FIGURES_VLM_PARALLEL(그림)은 VLM_CONCURRENCY 하나로
    "VLM_CONCURRENCY=8",
    "VLM_FIGURES_MAX=10",
    "PARSE_POST=supsub,charts,figures,context,attachments",
    "RAPIDOCR_PAGE_WORKERS=2",
    "OCR_THREADS=1",
    "PIPE_PROCS=4",
    "SOURCE_WARM={out}/_warm",  # {out} = 컨테이너 결과 자리(_img — parse_cmd가 채움)
    "SOURCE_FETCH_WORKERS=2",
    "PARSE_REP_SELECT=first",
    "PARSE_QA_LIGHT=1",
)
LIB_ENV = "PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache"  # env 남김 — 라이브러리(파이썬 자체 env, 설정 칸 아님)
DOC_MARK = "RUN_DOCS_DOC"  # 문서 표지 env(설정 칸 아님) — 고아 정리(sweep_cmd)가 /proc/*/environ에서 찾음(옛 PIPE_OUT_ROOT env 자리)
#   파싱 명령에만 붙인다(11-03 — 컨테이너 하나): 정리는 그 문서 파싱이 실패한 직후에만 돌고, 그 문서의 게시·구조화는 파싱 성공 뒤에만 시작하므로
#   정리 때 그 문서의 게시·구조화 프로세스는 없다. 다른 문서의 구조화·게시·파싱은 표지가 없거나 값이 달라(-zx 통째 비교) 끄지 않는다.


def sets(*pairs):
    """--set 인자 글자(앞 공백 포함) — 같은 이름이 여러 번이면 뒤 값이 이김(setarg — 옛 bash env와 같음)."""
    return "".join(f" --set {p}" for p in pairs)


# ── 컨테이너 명령 줄(S9 Step A — 명령 글자를 시험으로 고정하려고 함수로 뗌, 글자는 뗀 전과 같음) ──
def warm_cmd(seq):
    """문서 1개 warm(프리페치) — 상주 컨테이너 안 source warm."""
    o = _img("output_root")
    return (
        f"{DOCKER} exec {PIPE_C} bash -c 'umask 0002 && mkdir -p {o}/_warm && cd {_app()} && "
        f"PYTHONPATH={_img('code_root')} {LIB_ENV} "
        f"python -m pipeline.extract.fetch_docs{sets(f'SOURCE_WARM={o}/_warm')} warm --csv {_inside(seq, 'batch.csv')}'"
    )


def parse_cmd(seq, chan, scan, gate):
    """문서 1개 파싱 — chan(light·medium·vlm), scan(스캔 PDF), gate(CPU 게이트 글자)."""
    inside = _inside(seq)
    # 2026-10-23 사용자 지정 — heavy(스캔·이미지 다수) 판정 문서만 vlm_page 켬(스캔 쪽만 VLM 전사,
    # 내부 스캔판정이 이중 필터) · light는 종전대로 off. 같은 이름은 뒤 --set이 이기므로 뒤에 붙여 덮어씀.
    # 2026-10-23 사용자 지정 — 채널별 파라미터: heavy는 VLM 6(3동시 × 6 = 글로벌 18으로 gpu02 쏠림 제한),
    # light는 기본 8 유지(그림 거의 없음) · 스캔 PDF에만 vlm_page(40쪽 캡).
    heavy_on = (
        (
            "VLM_MAX_CONCURRENCY=6",
            "VLM_CONCURRENCY=6",
            "PARSE_POST=supsub,charts,figures,context,attachments,vlm_page",
            "VLM_PAGE_MAX=",
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
        *(p.format(out=_img("output_root")) for p in PARSE_SET),
        *heavy_on,
        *scan_set,
        f"CPU_MAX_LOAD={gate}",
    )
    return (
        f"{DOCKER} exec {PIPE_C} bash -c 'umask 0002 && cd {_app()} && "
        f"echo [envcheck] gate={gate} 채널={chan}; "
        f"{DOC_MARK}={inside} {LIB_ENV} "
        f"python -m pipeline.cli{doc} parse --source rdb:csv:{inside}/batch.csv'"
    )


def struct_cmd(seq):
    """문서 1개 구조화 + 적재. 엔진 구성은 파싱과 같은 파일(코드 폴더 — 사용자 11-01: 판 번호 없음, 실행 중에는 안 바뀜)."""
    inside = _inside(seq)
    st = sets(*EMBED_SET)  # 묶음·적재 python에(문서 메타는 적재가 EDW 조인으로 — pl-29 11-02, FILE_META_PATH 지움)
    return (
        f"{DOCKER} exec {PIPE_C} bash -c 'umask 0002 && cd {_app()} && "
        f"PYTHONPATH={_img('code_root')} {LIB_ENV} "
        f"python -m pipeline.transform.structure.build_bundle{st} --parse-dir {inside}/parse"
        f" --out {inside}/bundle && "
        f"{LIB_ENV} python -m pipeline.load.pgvector_load{st} load --bundle {inside}/bundle --rep-dir {inside}/parse/_rep "
        f">> {inside}/structure.log 2>&1'"
    )


def faq_sync_cmd(reset):
    """pl-41 FAQ 교체 확인(파이프라인 컨테이너) — 결과는 _docflow/faq_sync.json(지운 수·남은 gold faq)."""
    return (
        f"{DOCKER} exec {PIPE_C} bash -c 'umask 0002 && cd {_app()} && PYTHONPATH={_img('code_root')} {LIB_ENV} "
        f"python -m pipeline.load.pgvector_load faq-sync{' --reset' if reset else ''} --out {_inside('faq_sync.json')}'"
    )


def publish_cmd(seq):
    """문서 1개 publish(OS + EDW)."""
    inside = _inside(seq)
    return (
        f"{DOCKER} exec {PIPE_C} bash -c 'umask 0002 && cd {_app()} && "
        f"PYTHONPATH={_img('code_root')} {LIB_ENV} python -m pipeline.load.publish_parse_result"
        f"{sets('PM_BUCKET_SKIP_OVERLAP_CHECK=1')} "  # 실행 방침(접속 값 아님) — 버킷·접두·표·EDW·Object Storage는 컨테이너가 설정 파일에서(S7e1 Q8)
        f"--out {inside} --source-system FileStorageMap --apply "
        f">> {inside}/publish.log 2>&1'"
    )


def sweep_cmd(seq):
    """고아 정리 — 이 문서 표지 env(DOC_MARK)를 가진 컨테이너 안 프로세스(bash·python·soffice까지 env 상속)를 모두 끔. environ 항목(NUL 구분)과
    통째로 같을 때만(-zx — 리뷰 S9: 앞부분만 맞추면 doc 1 정리가 doc 10~19·100…까지 끔, 옛 PIPE_OUT_ROOT 때부터)."""
    inside = _inside(seq)
    return (
        f'{DOCKER} exec {PIPE_C} bash -c "for p in /proc/[0-9]*; do '
        f"grep -aqzx '{DOC_MARK}={inside}' \\$p/environ 2>/dev/null && kill \\${{p##*/}} 2>/dev/null; done\""
    )


# ── 레인·대기열 정책(사용자 10-29 — docs/prd/ops.md rn-01·rn-02) — settings.yaml ops.run_docs(configure()가 읽음).
# 기본값은 설정 모델 pipeline.config.PipelineHostRunDocs와 같다(이 스크립트는 호스트 python이라 모델을 import하지 않음 — 시험이 둘을 대조).
RUN_DOCS_DEFAULTS = {
    "warm": 20,  # 진입 대기열 — 미리 받아 둘 문서 수(받는 중 포함 · 파싱 중 제외)
    "warm_workers": 2,  # 미리 받기 동시 수(pl-48 — 사용자 11-02) — 실제 동시 받기 = min(이 값, 대기열 빈자리)
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
WARM_WORKERS = RUN_DOCS_DEFAULTS["warm_workers"]
LANE_WORKERS = {c: (RUN_DOCS_DEFAULTS[f"{c}_dedicated"], RUN_DOCS_DEFAULTS[f"{c}_shared"]) for c in LANES}  # 레인 → (전담, 공유)
_BACKLOG_SETTING = RUN_DOCS_DEFAULTS["struct_backlog"]  # main()이 STRUCT_BACKLOG로 풂(구조화 워커 수 인자가 덮은 뒤)
STRUCT_BACKLOG = 0
NO_CLEANUP = False
CPU_GATE = 1.3  # 2026-10-23 사용자 지정 — 파이프라인 게이트 기본 · 조정 시 --cpu-gate 1.1
_class: dict = {}  # seq → "light"/"medium"/"vlm"(warm 시점 분류)
_scan: set = set()  # seq — 스캔 판정된 PDF(vlm_page 대상)만 담음(2026-10-23 사용자 지정)

LANEQ = {c: __import__("collections").deque() for c in LANES}  # 레인별 대기 문서(dispatched 순서)
_struct_q: "queue.Queue" = queue.Queue()  # 중간 대기열 — 게시 끝·구조화(gold) 대기(main()이 씀)
_pub_q: "queue.Queue" = queue.Queue()  # 파싱 끝·게시 대기(pl-24 — 게시를 gold 앞에, 따로 한 스레드)
_LOCK = None  # take_lock() 파일 — 프로세스 끝까지 쥠(pl-18)


def _waiting():
    """파싱은 끝났고 gold가 아직 시작 안 한 문서 수(게시 대기 + 구조화 대기) — STRUCT_BACKLOG가 이 값을 봄(rn-02)."""
    return _pub_q.qsize() + _struct_q.qsize()


MCP_JOBS_DIR = None  # MCP parse_document 업로드 작업 경로 — configure()(mcp.host.jobs_dir, 없으면 결과 폴더/_mcp_parse/jobs — data-pipeline-mcp의 mcp_parse_service와 공유 볼륨, rn-03)
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
            "pub_wait": _pub_q.qsize(),
            "struct_wait": _struct_q.qsize(),
        }
    try:  # 관찰용 기록 — 못 써도(디스크 가득 등) 예외를 내지 않는다: 스레드·대기열 집계 사이에서 불려, 죽으면 main()이 멈춤(PR #107 리뷰)
        with _stats_lock:
            with (PROG / "queue_depth.jsonl").open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(rec) + "\n")
    except OSError as ex:
        _thread_error("대기열 기록", event, ex)


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
    for k in (
        "warm",
        "warm_workers",
        "vlm_cap",
    ):  # 0이면 문서를 안 받거나(warm·warm_workers) vlm 레인을 아무도 안 집어 배치가 끝나지 않음(PR #7 리뷰)
        if vals[k] < 1:
            probs.append(f"pipeline.host.run_docs.{k} — 1 이상만")
    shared = sum(vals[f"{c}_shared"] for c in LANES)
    for c in LANES:  # 어느 워커도 못 집는 레인이 있으면 그 큐가 안 비어 배치가 끝나지 않음
        if vals[f"{c}_dedicated"] + shared < 1:
            probs.append(f"pipeline.host.run_docs — {c} 레인을 처리할 워커가 없음({c}_dedicated와 모든 *_shared가 0)")
    return vals, probs


def apply_policy(vals):
    """run_docs_policy() 값 → 모듈 값(configure()가 부름)."""
    global WARM_TARGET, WARM_WORKERS, STRUCT_WORKERS, VLM_CAP, LANE_WORKERS, _BACKLOG_SETTING
    WARM_TARGET, STRUCT_WORKERS, VLM_CAP = vals["warm"], vals["struct_workers"], vals["vlm_cap"]
    WARM_WORKERS = vals["warm_workers"]
    LANE_WORKERS = {c: (vals[f"{c}_dedicated"], vals[f"{c}_shared"]) for c in LANES}
    _BACKLOG_SETTING = vals["struct_backlog"]


def stack_check():
    """엔진 구성 파일 확인 — 시작 때 한 번(파싱 컨테이너 안 show-stack — 파일을 못 읽거나 모양이 틀리면 종료 2, 시작하지 않음).
    없는 엔진은 파싱 입구가 거부한다(engine_stack.resolve)."""
    rc, _, err = sh(
        f"{DOCKER} exec {PIPE_C} bash -c 'cd {_app()} && PYTHONPATH={_img('code_root')} python -m pipeline.cli show-stack'", timeout=120
    )
    if rc != 0:
        print(f"[중단] 엔진 구성 파일을 읽지 못함(종료 코드 {rc}) — {(err or '').strip()[-200:]}", flush=True)
        raise SystemExit(2)  # 설정 문제 = 2(pl-18 — 실패 문서 1과 가름)


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


def edw_list(keywords=(), where=None):
    """EDW FileStorageMap 전체(파일 크기 오름차순) — make_batch.py와 같은 질의·순서. where(코드 상수)를 주면 이름 키워드 대신 그 조건(pl-41 FAQ)."""

    conds = where or " OR ".join(f"LOWER(original_filename) LIKE '%{k.lower()}%'" for k in keywords)
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


DONE_STATUSES = (
    "ok",
    "partial",
    "skipped_dup",
)  # 끝난 문서 = common/store/parsing_meta_db.DONE_STATUSES와 같게(C10 — 사용자 11-01, 운영 고침 11b)
GOLD_STATUSES = ("ok", "partial")  # parsing_meta_db.GOLD_STATUSES와 같게 — gold_version도 있어야 끝(사용자 11-02)


def edw_done_keys():
    """EDW AI.ParsingMeta에서 끝난(DONE_STATUSES — ok·partial은 gold_version도, 11-02) source_key 집합(2026-10-22 사용자 지정 — 재실행 skip용 · 키는 FileStorageMap s3_key와 글자 그대로 비교)."""

    conn = _edw_connect()  # S7e1 — 설정 파일의 parsing-meta 접속(옛 코드 기본값 — 운영 접속 값·비밀 삭제, D-028 ⑨)
    cur = conn.cursor()
    kc = _pm_key_col(cur)
    cur.execute("SELECT COL_LENGTH('AI.ParsingMeta', 'gold_version')")
    gold = cur.fetchone()[0] is not None
    q = lambda xs: ", ".join(f"'{s}'" for s in xs)  # 코드 상수만 SQL에 넣음(값 바인딩 없음)
    cond = f"parse_status IN ({q(DONE_STATUSES)})"
    if gold:  # 11-02 — ok·partial은 gold에도 올라가야 끝(gold_version) · 칸이 생기기 전(C-76 ③)에는 parse_status만
        rest = [s for s in DONE_STATUSES if s not in GOLD_STATUSES]
        cond = f"(parse_status IN ({q(rest)}) OR (parse_status IN ({q(GOLD_STATUSES)}) AND gold_version IS NOT NULL))"
    cur.execute(f"SELECT {kc} FROM AI.ParsingMeta WHERE {cond}")
    keys = {r[0] for r in cur.fetchall()}
    conn.close()
    return keys


def write_doc_csv(row, path):
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "s3_key", "original_filename", "file_size"])
        w.writerow([row["id"], row["s3_key"], row["original_filename"], row["file_size"]])


_warm_reused: set = set()  # 이미 받아 둔 파일이라 컨테이너를 부르지 않은 문서(소요 기록의 reused)


def warm_one(seq, row):
    """문서 1개를 warm에 미리 받기(source warm CLI — 상주 컨테이너 env 그대로)."""
    d = DOCFLOW / f"{seq}"
    d.mkdir(parents=True, exist_ok=True)
    write_doc_csv(row, d / "batch.csv")
    if (WARM / _warm_bin(row)).exists() and (d / ".warmed").exists():
        _warm_reused.add(seq)
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


_class_lock = threading.Lock()  # 분류 캐시 — 미리 받기 워커 여럿(pl-48)이 같은 사전·파일을 씀


def _class_save(cache):
    """호출자가 _class_lock을 잡은 채로 부른다(사전을 글자로 바꾸는 동안 다른 워커가 넣지 않게)."""
    p = PROG / "docflow_class.json"
    p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def classify_doc(seq, row, cache=None):
    """레인 분류(PRD rn-01) — 규칙은 컨테이너 안 pipeline/extract/doc_parsing_group.py의 doc_parsing_group() 하나.
    캐시(s3_key) 우선 — 캐시에 있으면 docker exec를 안 부른다. 답(마지막 줄 — pymupdf 경고 섞임 방지)이 없으면 보수적으로 vlm.
    PDF의 vlm은 내용 검사 heavy(스캔)일 때뿐이라 PDF vlm = 스캔(_scan) 표시(캐시에서 되살릴 때도 같음)."""
    import pathlib

    t_c = time.time()  # 소요 기록(pl-op01 — 이슈 #117): 분류 전체 · probe_sec = 컨테이너 호출만
    name = _doc_name(row)
    is_pdf = pathlib.Path(name).suffix.lower() == ".pdf"
    if cache is not None:
        with _class_lock:
            hit = cache.get(row["s3_key"])
        if hit:
            if is_pdf and hit == "vlm":
                _scan.add(seq)
            _class[seq] = hit
            mark(seq, "classify", doc=_doc_name(row), ocr=hit, cached=True, sec=round(time.time() - t_c, 2))
            return hit
    t_p = time.time()
    rc, out, _ = sh(  # PYTHONPATH = 코드 폴더 — 그러면 그룹 판별 1건이 extract.classify 행으로 남는다(이슈 #117, doc_id = name)
        f"{DOCKER} exec -e PYTHONPATH={_img('code_root')} {PIPE_C} python3 {_img('code_root')}/pipeline/extract/doc_parsing_group.py "
        f"{_img('output_root')}/_warm/{_warm_bin(row)} {shlex.quote(name)} {int(row.get('file_size') or 0)}",
        timeout=60,
    )
    probe_sec = time.time() - t_p
    cls = next((ln.strip() for ln in reversed((out or "").splitlines()) if ln.strip() in LANES), "vlm")
    if is_pdf and cls == "vlm":
        _scan.add(seq)  # OCR 대체가 필요한 스캔 PDF 표시
    if cache is not None:
        with _class_lock:
            cls = cache.setdefault(row["s3_key"], cls)  # 다른 워커가 먼저 넣었으면 그 값(옛 동작과 같음)
            _class_save(cache)
    _class[seq] = cls
    mark(seq, "classify", doc=_doc_name(row), ocr=cls, cached=False, sec=round(time.time() - t_c, 2), probe_sec=round(probe_sec, 2))
    return cls


DEADLINE_AT = None  # --deadline(새벽 배치 마감, 사용자 11-02) — 이 시각(epoch 초)이 지나면 새 문서를 받기 시작하지 않음
_deadline_hit = threading.Event()  # 마감으로 남은 문서를 받지 않았음 → 종료 코드 75(pl-18)
# 종료 코드(pl-18, 사용자 10-30): 대상 0건·모두 끝 = 0, 실패 있음 = 1, 마감 도달(실패 없음)·다른 run_docs가 도는 중 = 75
EXIT_FAIL = 1
EXIT_DEADLINE = 75


def deadline_at(hhmm, now=None):
    """HH:MM → 다음 그 시각(epoch 초) — 지금보다 이르거나 같으면 다음 날(자정을 넘는 배치 — 23:00 시작·05:00 마감)."""
    now = datetime.datetime.now() if now is None else now
    h, m = (int(x) for x in hhmm.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        t += datetime.timedelta(days=1)
    return t.timestamp()


_WARM_ERR = [0]  # 받기 워커 스레드 예외 수 — main()이 실패 수(thread_err)에 더함(PR #107 리뷰)


def downloader(rows, order):
    """대기열 유지 — 지정 문서 순서대로 WARM_TARGET개(받는 중 포함)까지 미리 받아 둔다(파싱 중 제외). 받기 워커 WARM_WORKERS개가
    차례(order)를 하나씩 집어 동시에 받는다(pl-48 — 사용자 11-02): 실제 동시 받기 = min(WARM_WORKERS, 대기열 빈자리).
    빈자리가 없으면 워커가 있어도 받지 않는다. 다 집으면 워커가 끝나고, 모두 끝나면 이 함수도 끝난다."""
    global _next_warm
    cache = _class_cache()
    pos = {"ptr": 0}
    with _warm_lock:
        _next_warm = order[0] if order else 10**12

    def worker():
        global _next_warm
        while not _stop.is_set():
            with _warm_lock:
                if pos["ptr"] >= len(order):
                    return
                if DEADLINE_AT is not None and time.time() >= DEADLINE_AT:  # 마감 — 남은 차례는 다음 새벽 배치가 다시 고름
                    if pos["ptr"] < len(order):
                        _deadline_hit.set()  # 종료 코드 75(pl-18)
                        log(f"마감 — 남은 {len(order) - pos['ptr']}건은 받지 않음(받은 문서는 끝까지)")
                        pos["ptr"] = len(order)
                        _next_warm = 10**12
                    return
                if _lane_total() + len(_warming) >= WARM_TARGET:  # 빈자리 없음 — 파싱이 하나 시작되면 notify
                    _warm_lock.wait(5)
                    continue
                seq = order[pos["ptr"]]
                pos["ptr"] += 1
                _next_warm = order[pos["ptr"]] if pos["ptr"] < len(order) else 10**12
                _warming.add(seq)
            row = rows[seq]
            t_w = time.time()
            try:
                ok = warm_one(seq, row)
                # sec = 컨테이너 기동·head·전송·기록을 모두 합친 단계 전체 시간(순수 전송 속도 아님 — 그건 source.py 쪽 계측, 2단계)
                mark(
                    seq,
                    "warm_end",
                    ok=ok,
                    sec=round(time.time() - t_w, 1),
                    bytes=row.get("file_size"),
                    doc=_doc_name(row),
                    reused=seq in _warm_reused,
                )
                classify_doc(seq, row, cache=cache)  # OCR 필요도 사전 분류(캐시 우선) → 워커 배분용
                with _warm_lock:
                    LANEQ[_class.get(seq) or "light"].append(seq)
                    _warming.discard(seq)
                    _warm_lock.notify_all()
                mark(seq, "dispatched")
            except Exception as ex:  # 받기·분류·기록 예외(디스크 가득 등) — 워커가 죽으면 _warming에 남아 _flow_done()이 안 끝남
                _thread_error("받기", seq, ex)
                with _warm_lock:
                    _WARM_ERR[0] += 1
                    _warming.discard(seq)
                    _warm_lock.notify_all()
                continue
            depth("dispatch")

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, WARM_WORKERS))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def _sweep_orphan(seq):
    """docker exec 고아 방지(2026-10-22) — 타임아웃·실패 시 이 문서 PIPE_OUT_ROOT env를 가진
    컨테이너 내 프로세스(bash·python·soffice까지 환경 상속)를 전부 종료."""
    sh(sweep_cmd(seq), timeout=30)


def parse_one(seq, row):
    """문서 1개 파싱 — 공유 상주 컨테이너(PIPE_C) 안에서 워커별 분리(경로 격리).
    PIPE_OUT_ROOT + DOC_DIR_PREPARED로 문서별 출력 루트 분리(pipeline이 두 env를 지원).
    문서당 VLM 8(vlm 레인 6)·OCR 쪽 2(쓰레드 1)·vlm_page off(vlm 레인만 켬) · 쪽 해상도는 settings.yaml extract.ocr.dpi(11-04 — OCR_DPI=120 덮기 지움)."""
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


def publish_one(seq, row):
    """silver 게시(OS + EDW — pl-24: 파싱 바로 뒤, gold 전). 성공해야 원본을 지우고 gold로 넘어간다."""
    t1 = time.time()
    mark(seq, "pub_start")
    rc, _, err = sh(publish_cmd(seq), timeout=900, log=PROG / f"doc_{seq}.log")
    ok = rc == 0
    mark(seq, "pub_end", ok=ok, sec=round(time.time() - t1, 1))
    log(
        f"doc#{seq} publish {'OK' if ok else 'FAIL'}({(time.time() - t1) / 60:.1f}분)" + ("" if ok else f" — 원본 남김 · {str(err)[-150:]}")
    )
    return ok


def gold_one(seq, row, enq_t=None):
    """gold = 구조화+적재(문서 경계 없이 — pl-24: 게시 성공 뒤). enq_t=게시 끝 시각(구조화 대기 계산)."""
    t0 = time.time()
    wait = round(t0 - enq_t, 1) if enq_t else 0
    mark(seq, "struct_start", queue_wait=wait)
    rc, _, err = sh(struct_cmd(seq), timeout=1800, log=PROG / f"doc_{seq}.log")
    ok = rc == 0
    mark(seq, "struct_end", ok=ok, sec=round(time.time() - t0, 1))
    log(
        f"doc#{seq} 구조화+적재 {'OK' if ok else 'FAIL'}(대기 {wait / 60:.1f}분 · 실행 {(time.time() - t0) / 60:.1f}분)"
        + ("" if ok else f" — silver는 남김(게시됨, gold는 silver에서 다시 만듦) · {str(err)[-150:]}")
    )
    # TODO(pl-24 · refactor.md C-81): DB 담당자가 AI.ParsingMeta.gold_status(pending·ok·failed)+이유 칸을 더하면 여기서 실패를 적는다.
    #   지금은 칸이 없어 로그에만. gold_version 칸(C-76 ③)이 있으면 비어 있으므로 다음 --skip-done이 다시 고른다(C10) —
    #   칸이 없으면 게시한 행(parse_status ok)만 보고 끝난 문서로 친다 → 이 순서는 gold_version 칸이 생긴 뒤에 배포(C-81).
    return ok


def _doc_name(row):
    """pipe_event.doc_id와 맞추는 파일 이름 — 호스트 기록(seq)과 DB 행(doc_id)을 잇는 열쇠."""
    return row["original_filename"].rsplit("/", 1)[-1]


def _warm_bin(row):
    return hashlib.sha1(f"{WARM_BUCKET}|{row['s3_key']}".encode()).hexdigest() + ".bin"


def drop_original(seq, row):
    """원본 삭제(pl-24 — silver 게시가 성공한 뒤에만): warm 원본과 문서 폴더의 원본 사본(_source_files). 파싱 결과(parse/)는 gold가 씀.
    컨테이너(uid 10001)가 만든 파일은 호스트가 못 지우므로 docker exec(같은 공유 볼륨, 그 uid)로 지우고 잔여만 호스트가 마무리."""
    if NO_CLEANUP:
        return
    o = _img("output_root")
    sh(f"{DOCKER} exec {PIPE_C} bash -c 'rm -rf {_inside(seq, '_source_files')} ; rm -f {o}/_warm/{_warm_bin(row)}'", timeout=60)
    shutil.rmtree(DOCFLOW / f"{seq}" / "_source_files", ignore_errors=True)
    (WARM / _warm_bin(row)).unlink(missing_ok=True)


def drop_temp(seq):
    """문서 끝 — docflow 임시 폴더만 지움(어느 길이든). 원본(warm)은 drop_original만 지운다 — 파싱·게시 실패면 남음(pl-24)."""
    if NO_CLEANUP:
        return
    sh(f"{DOCKER} exec {PIPE_C} bash -c 'rm -rf {_inside(seq)}'", timeout=60)
    shutil.rmtree(DOCFLOW / f"{seq}", ignore_errors=True)


def take_lock(path):
    """겹침 막는 잠금(pl-18) — 사람이 돌린 run_docs와 새벽 배치가 함께 돌지 않게. 잡으면 파일 객체(프로세스 끝까지 쥠), 이미 잡혀 있으면 None.
    flock은 프로세스가 죽으면 커널이 풀어 줘 남은 잠금 파일 문제가 없다. 호스트는 Linux(RHEL)뿐 — fcntl은 여기 한 곳만."""
    import fcntl

    fp = open(path, "a", encoding="utf-8")  # 프로세스 끝까지 열어 둠(닫으면 잠금이 풀림)
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fp.close()
        return None
    return fp


def _pm_key_col(cur):
    """ParsingMeta 원본 키 칸 이름 — 11-02 칸 이름 바꾸기(source_key → s3_key, C-76) 전후 모두(튜플 커서)."""
    cur.execute("SELECT COL_LENGTH('AI.ParsingMeta', 'source_key')")
    return "source_key" if cur.fetchone()[0] is not None else "s3_key"


def edw_faq():
    """pl-41 — FileStorageMap의 FAQ 전체(--filter와 상관없이, edw_list와 같은 질의)와 ParsingMeta의 FAQ 키 → 상태(한 번이라도 기록된 것)."""
    rows = edw_list(where="s3_key LIKE 'FAQ/%'")
    conn = _edw_connect()
    cur = conn.cursor()
    kc = _pm_key_col(cur)
    cur.execute(f"SELECT {kc}, parse_status FROM AI.ParsingMeta WHERE {kc} LIKE 'FAQ/%'")
    status = {k: st for k, st in cur.fetchall()}
    conn.close()
    return rows, status


def faq_first(rows, order):
    """pl-41(사용자 11-03) — FAQ는 판을 잇지 않고 통째로 교체. 새 FAQ(교체를 마친 키 목록 faq_seen.txt에 없는 키)가 있으면 구조화 컨테이너의
    `pgvector_load faq-sync --reset`으로 gold faq를 비우고 FAQ 전체를 이번 처리 맨 앞에 넣는다(--filter·--skip-done과 상관없이 — 없는 FAQ 행은
    rows 뒤에 덧붙임). 새 FAQ가 없으면 지우지 않고 gold에 없는 FAQ만 넣는다(중간에 멈춘 교체·파싱 실패를 채움 — 완전 중복 skipped_dup은 gold에
    안 올라가므로 뺌). faq-sync 결과를 못 읽으면(실패·시간 초과 — 지웠는지 모름) FAQ 전체를 넣고 faq_seen.txt는 그대로 둬 다음 실행이 교체를
    다시 시도한다(적재는 이미 있는 문서를 건너뜀). ParsingMeta는 새 FAQ 판정에 쓰지 않는다(--seqs·--limit 실행이 교체 없이 기록할 수 있어서)."""
    faq_rows, status = edw_faq()
    seen_f = PROG / "faq_seen.txt"  # 교체를 마친 FAQ 키 — 처음 실행(파일 없음)은 FAQ 전체가 새 FAQ라 한 번 교체함
    seen = set(seen_f.read_text(encoding="utf-8").splitlines()) if seen_f.exists() else set()
    seq = {r["s3_key"]: i for i, r in enumerate(rows)}
    for r in faq_rows:
        if r["s3_key"] not in seq:
            seq[r["s3_key"]] = len(rows)
            rows.append(r)
    faq = [seq[r["s3_key"]] for r in faq_rows]
    new = [r["s3_key"] for r in faq_rows if r["s3_key"] not in seen]
    res = DOCFLOW / "faq_sync.json"
    res.unlink(missing_ok=True)
    rc, _, err = sh(
        faq_sync_cmd(bool(new))
    )  # ponytail: 시간 초과(기본 1800초)면 컨테이너 안 명령은 계속 돌 수 있음 — 다음 실행의 채움이 메움
    try:
        got = json.loads(res.read_text(encoding="utf-8")) if rc == 0 else None
    except (OSError, ValueError):
        got = None
    if got is not None and new:  # 교체가 끝난 뒤에만 적음 — 실패하면 다음 실행이 다시 교체
        seen_f.write_text("".join(f"{k}\n" for k in sorted(seen | set(new))), encoding="utf-8")
    if got is None or new:
        log(
            f"[경고] FAQ 교체 확인(faq-sync) 결과 없음(rc={rc}: {err[-200:]}) — FAQ {len(faq)}건 전체를 넣음(이미 있는 문서는 적재가 건너뜀)"
            if got is None
            else f"FAQ 교체: 새 FAQ {len(new)}건 — gold faq 문서 {got['faq_reset']}건을 지우고 지금 FAQ {len(faq)}건 전체를 맨 앞에서 다시 처리"
        )
        want = faq
    else:
        gold = set(got["gold"])
        want = [seq[r["s3_key"]] for r in faq_rows if r["s3_key"] not in gold and status.get(r["s3_key"]) != "skipped_dup"]
        if want:
            log(f"FAQ 채움: gold에 없는 FAQ {len(want)}건을 다시 처리(지우지 않음)")
    keep = set(want)
    return want + [s for s in order if s not in keep]


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


def mcp_busy():
    """MCP 업로드 처리 중이면 True(공유 볼륨 _mcp_parse/jobs/<id>의 파일 mtime이 30초 내 갱신).
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


def _safe(fn, *args):
    """정리(drop_original·drop_temp) — 정리 자체가 실패해도(디스크 가득·docker 없음) 작업 스레드는 계속(집계는 호출자가 함)."""
    try:
        fn(*args)
    except Exception as ex:
        _thread_error("정리", args[0], ex)


def main():
    global WARM_TARGET, STRUCT_WORKERS, NO_CLEANUP, CPU_GATE, STRUCT_BACKLOG, CODE_DIR, DEADLINE_AT, _LOCK
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
    ap.add_argument("--max-docs", type=int, default=0, help="새벽 배치 — 끝난 문서를 뺀 뒤 앞에서 이 개수만(0 = 상한 없음, 사용자 11-02)")
    ap.add_argument("--deadline", default="", help="새벽 배치 마감(HH:MM) — 지나면 새 문서를 받기 시작하지 않음(사용자 11-02)")
    ap.add_argument("--seqs", default="", help="임의 문서 집합(쉼표 seq 목록) — 지정 시 연속 범위 대신 이 목록만 처리")
    ap.add_argument("--cpu-gate", type=float, default=1.3, help="파이프라인 CPU 게이트(CPU_MAX_LOAD) — 기본 1.3, 조정할 때 --cpu-gate 1.1")
    ap.add_argument(
        "--skip-done",
        action="store_true",
        help="EDW ParsingMeta에 이미 끝난(ok·partial — gold_version도, skipped_dup) 문서는 건너뜀(재실행 시간 절약)",
    )
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--settings", default=None, help="서버 settings.yaml(기본 SETTINGS_FILE 또는 <루트>/settings.yaml — op-13)")
    ap.add_argument(
        "--code",
        default=None,
        help="코드 폴더(설정 배치 모듈·이미지 경로 표를 찾음 — 기본: 이 스크립트가 든 코드 폴더 · op-10, 기본 배치 경로 없음 — 사용자 11-02)",
    )
    a = ap.parse_args()
    CODE_DIR = Path(a.code) if a.code else None
    bad = configure(a.settings)
    if bad:
        for msg in bad:
            print(f"[중단] {msg}", flush=True)
        raise SystemExit(2)
    NO_CLEANUP, CPU_GATE = a.no_cleanup, a.cpu_gate
    DEADLINE_AT = deadline_at(a.deadline) if a.deadline else None
    if a.warm is not None:
        WARM_TARGET = a.warm
    if a.struct_workers is not None:
        STRUCT_WORKERS = a.struct_workers
    STRUCT_BACKLOG = _BACKLOG_SETTING if _BACKLOG_SETTING is not None else 2 * max(1, STRUCT_WORKERS)

    PROG.mkdir(parents=True, exist_ok=True)
    _LOCK = take_lock(PROG / "run_docs.lock")
    if _LOCK is None:
        log(f"다른 run_docs가 도는 중({PROG / 'run_docs.lock'}) — 종료 코드 {EXIT_DEADLINE}, 다음 실행에서 다시")
        return EXIT_DEADLINE
    if not MCP_JOBS_DIR.is_dir():
        log(
            f"[안내] MCP 업로드 작업 폴더 {MCP_JOBS_DIR} 없음 — MCP 업로드 감지(medium 레인 양보) 꺼짐, 다른 자리면 settings.yaml ops.mcp_host.jobs_dir"
        )
    os.umask(0)  # 컨테이너( uid 10001 rag )가 /app/output(=_docflow/<seq>)에 쓰려면 777 필요
    WARM.mkdir(mode=0o777, parents=True, exist_ok=True)
    DOCFLOW.mkdir(mode=0o777, parents=True, exist_ok=True)
    rows = edw_list([k.strip() for k in a.filter.split(",") if k.strip()])
    stack_check()
    start = a.start_offset
    if start >= len(rows):  # 대상은 없어도 FAQ 교체(pl-41)는 확인 — 할 일이 없으면 아래 '처리할 문서 없음'에서 끝남
        log(f"start-offset {start} ≥ 대상 {len(rows)}건")
        start = len(rows)
    log(
        f"=== 문서별 flow 시작: offset={start} · 남은 {len(rows) - start}건 · 레인(전담/공유) "
        f"{' '.join(f'{c} {d}/{s}' for c, (d, s) in LANE_WORKERS.items())} · vlm 동시 {VLM_CAP} · "
        f"warm {WARM_TARGET} · 구조화 {STRUCT_WORKERS}동시(대기 상한 {STRUCT_BACKLOG or '없음'}) · {'제한 ' + str(a.limit) + '건' if a.limit else '제한 없음'} ==="
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
        log(f"skip-done: {before - len(order)}건 이미 완료({'·'.join(DONE_STATUSES)}) — 남은 {len(order)}건 처리")
    if a.seqs or a.limit:  # 골라 돌리기·시험은 FAQ 교체 안 함
        log("FAQ 교체 확인(pl-41) 건너뜀 — --seqs·--limit 실행")
    else:
        order = faq_first(rows, order)
    if a.max_docs and len(order) > a.max_docs:
        log(f"max-docs: {len(order)}건 중 앞 {a.max_docs}건만(나머지는 다음 실행)")
        order = order[: a.max_docs]
    if not order:
        log("처리할 문서 없음 — 종료")
        return 0
    t_all = time.time()
    tf = threading.Thread(target=downloader, args=(rows, order), daemon=True)
    tf.start()

    # 문서별 순서(pl-24): 파싱 → silver 게시(pub_q, 게시 스레드) → 원본 삭제 → gold(struct_q, 구조화 스레드) → 임시 삭제.
    # 게시를 따로 두어 구조화가 업로드·EDW 쓰기를 기다리지 않는다. 파싱 실패·게시 실패면 원본을 남기고 gold로 가지 않는다.
    cnt = {"ok": 0, "parse_fail": 0, "pub_fail": 0, "gold_fail": 0, "thread_err": 0}  # thread_err — 집계 전에 스레드 예외(종료 코드 1로)
    struct_q, pub_q = _struct_q, _pub_q

    def _queue_loop(q, stage, work):
        """q에서 꺼내 work(*item)를 돌리는 스레드 — None이면 끝. 예외 처리·기록 중 예외(디스크 가득 등)도 스레드를 죽이지 않게 —
        죽으면 q.join()이 안 끝남(S12 리뷰)."""
        while True:
            item = q.get()
            depth(f"{stage}_get")
            with _warm_lock:
                _warm_lock.notify_all()  # 중간 대기 하나 줄어듦 → 상한에서 기다리던 레인 워커
            if item is None:
                q.task_done()
                return
            try:
                work(*item)
            except Exception as ex:
                _thread_error(stage, item[0], ex)
                with _warm_lock:
                    cnt["thread_err"] += 1
            finally:
                q.task_done()

    def _publish(seq, row):
        try:
            ok = publish_one(seq, row)
        except Exception as ex:
            log(f"doc#{seq} publish 예외 — 원본 남김 · {type(ex).__name__}: {str(ex)[:120]}")
            ok = False
        if not ok:
            with _warm_lock:
                cnt["pub_fail"] += 1
            _safe(drop_temp, seq)
            return
        _safe(drop_original, seq, row)  # 게시 성공 뒤에만(pl-24)
        struct_q.put((seq, row, time.time()))
        depth("struct_put")

    def _gold(seq, row, enq_t):
        try:
            ok = gold_one(seq, row, enq_t)
        except Exception as ex:
            log(f"doc#{seq} 구조화 예외 — silver는 남김 · {type(ex).__name__}: {str(ex)[:120]}")
            ok = False
        with _warm_lock:  # 집계를 기록(mark — 디스크 가득이면 예외)보다 먼저
            cnt["ok" if ok else "gold_fail"] += 1
            report = ok and cnt["ok"] % 5 == 0
        _safe(drop_temp, seq)
        mark(seq, "done")
        if report:  # psql(최대 60초)은 잠금 밖에서 — 레인·받기 워커를 막지 않게
            nd, nc = pg_count()
            log(f"PG 누적: doc={nd} chunk={nc}")

    # ponytail: 게시 스레드 1개 — 업로드+EDW 한 줄은 파싱·구조화보다 훨씬 짧음, 밀리면 설정 칸(설정 모델 — 핑거프린트 파일)으로
    threading.Thread(target=_queue_loop, args=(pub_q, "pub", _publish), daemon=True).start()
    for _ in range(max(1, STRUCT_WORKERS)):
        threading.Thread(target=_queue_loop, args=(struct_q, "struct", _gold), daemon=True).start()

    def _one(doc_seq, row_doc):
        try:
            ok, _d = parse_one(doc_seq, row_doc)
        except Exception as ex:
            log(f"doc#{doc_seq} 파싱 예외 — {type(ex).__name__}: {str(ex)[:120]}")
            ok = False
        if ok:
            pub_q.put((doc_seq, row_doc))
            depth("pub_put")
        else:
            with _warm_lock:
                cnt["parse_fail"] += 1
            _safe(drop_temp, doc_seq)  # 원본(warm)은 남김 — 로그에만(pl-24)

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
                hold = (own == "medium" and not shared and _mcp_pause) or (STRUCT_BACKLOG and _waiting() >= STRUCT_BACKLOG)
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
                with _warm_lock:
                    cnt["thread_err"] += 1
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

    pub_q.put(None)  # 파싱 전부 끝 → 게시 끝 → 구조화 끝(센티널 차례로)
    pub_q.join()
    for _ in range(max(1, STRUCT_WORKERS)):
        struct_q.put(None)
    struct_q.join()
    _stop.set()
    with _warm_lock:
        _warm_lock.notify_all()
    tf.join(timeout=5)
    nd, nc = pg_count()
    cnt["thread_err"] += _WARM_ERR[0]
    failed = cnt["parse_fail"] + cnt["pub_fail"] + cnt["gold_fail"] + cnt["thread_err"]
    done = cnt["ok"] + failed
    rc = EXIT_FAIL if failed else (EXIT_DEADLINE if _deadline_hit.is_set() else 0)
    log(
        f"=== 문서별 flow 끝: {done}건(완료 {cnt['ok']} · 파싱실패 {cnt['parse_fail']} · 게시실패 {cnt['pub_fail']} · gold실패 {cnt['gold_fail']} · 스레드 예외 {cnt['thread_err']}) · "
        f"{(time.time() - t_all) / 60:.1f}분 · PG doc={nd} chunk={nc} · 문서당 평균 {(time.time() - t_all) / max(done, 1) / 60:.1f}분 · 종료 코드 {rc} ==="
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
