#!/usr/bin/env python3
"""문서별 flow 러너 — 배치 장벽 없이 문서마다 끝나는 순서대로 흐른다. 한 번 실행 = e2e(rn-05): ① 사전 점검 → ② 문서 처리 → ③ 적재·검색 확인.

실행 자리(run_env — 한 곳 configure()): dev = data-pipeline 컨테이너 안(SSH 셸 — 명령을 바로 부름) · prd = 서버 호스트(컨테이너마다
docker exec) · local은 거부(원본 받기의 PC 대역이 없음 — rn-05). ①③은 settings.yaml ops.run_pipeline.steps(기본 켬), 사람이 돌릴 때
건수는 ops.run_pipeline.run_limit(기본 2, 0 = 전체 — --limit이 덮음). 처음 실패한 단계에서 멈추고 끝 줄 `[판정] 통과|실패 — <단계>`.

0) 대상 목록 — 컨테이너 안 `candidate_pick list`가 EDW FileStorageMap에서 고르고(끝난 문서 빼기·FAQ 먼저) 목록 파일을 쓴다 — 여기는 읽기만.
1) 대기열 — 앞으로 나올 문서 STAGING_TARGET(기본 20)개를 미리 받아 둔다(컨테이너 `candidate_ready stage` — 받기·중복·거르기). 진행중 문서는 대기 개수에서 제외.
   파싱이 하나 시작되면 다음 문서를 즉시 받아 개수를 유지. 문서 flow가 끝나면 docflow 임시 디렉토리 삭제.
2) 파싱 flow — 레인 light·medium·vlm(받은 뒤 분류)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴
   다른 레인에서 가져옴) — 기본 레인마다 1·1(규칙: docs/prd/ops.md rn-01). vlm 문서는 동시 VLM_CAP(2)까지.
   구조화 대기 문서가 STRUCT_BACKLOG(기본 구조화 워커 × 2)개 이상이면 새 파싱을 시작하지 않고 기다림(rn-02).
   레인·대기 길이는 상태가 바뀔 때마다 batch_progress/queue_depth.jsonl에 한 줄(rn-02).
   값은 settings.yaml ops.run_pipeline(비우면 아래 RUN_PIPELINE_DEFAULTS) — --staging·--struct-workers 인자가 그 위를 덮음.
3) 문서별 순서(pl-24): 파싱 → silver 게시(publish — Object Storage + 처리 기록 파일, 게시 스레드 1개) → 원본 삭제(게시 성공 뒤에만) →
   gold(gold_bundle → pgvector_load — doc 행에 처리 기록, STRUCT_WORKERS(기본 2)개 스레드) → 임시 삭제. 배치 장벽 없이 끝나는 순서대로 흐름.
   파싱·게시 실패 = 원본(staging)을 남기고 gold로 안 감 · gold 실패 = silver는 그대로. 실패는 로그와 applog.except_doc_info error
   + applog.dlq_doc 재시도 상태(pl-69). 한 실행에서 한 문서는 시도 1회, 3회 실패하면 dead(사람만 requeue).
4) --skip-done 실행은 pending을 다음 실행 본 흐름에서 다시 시도하며 dead를 본 목록에서 뺀다. 사람이 requeue하면 다시 고른다.
   --seqs만 주거나 --skip-done 없이 실행하면 dead도 처리한다(--seqs와 --skip-done을 함께 주면 같은 제외 규칙 적용).
5) 종료 코드(pl-18): 0 = 대상 0건·모두 끝 · 1 = 실패 문서 있음 · 75 = 마감 도달(실패 없음) 또는 다른 run_pipeline이 도는 중
   (잠금 batch_progress/run_pipeline.lock — 사람이 돌린 실행과 새벽 배치가 겹치지 않게) · 2 = 설정 문제 · 3 = 사전 점검 또는 검색 확인 실패.

사용: python3 run_pipeline.py [--start-offset N](기본 0) [--staging 20] [--struct-workers 2]
                  [--filter RFP,proposal](기본 모든 문서 — 이름 키워드로 좁힐 때만) [--limit N](기본 run_limit) [--no-cleanup](임시 유지)
                  [--set 이름=값](설정 한 번 덮기 — 예 --set RUN_PIPELINE_STEPS_VERIFY=false)
로그: test_space/batch_progress/progress.log · 문서별 파싱 로그 test_space/batch_progress/doc_<seq>.log
"""

import argparse
import collections
import csv
import datetime
import functools
import hashlib
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 운영 접속 값·비밀·운영 고정값은 코드에 두지 않고 서버 settings.yaml에서 읽는다(configure() — 시작 때 한 번).
#   파일: --settings 또는 SETTINGS_FILE, 없으면 <루트>/settings.yaml(루트 = 코드 폴더 자체). 호스트 python에 PyYAML이 있어야 한다(pymssql처럼 —
#   refactor.md C-09). 필요한 칸이 없으면 칸 경로만 찍고 종료 코드 2(값은 찍지 않음).
#   prd: docker exec로 부르는 상주 컨테이너(0번 data-pipeline-0)는 같은 파일을 붙여 읽으므로 명령 줄에 접속 값·비밀을 넣지 않는다(ps·로그에 안 남음).
#   dev(DIRECT): 같은 명령을 이 프로세스가 바로 부른다 — 컨테이너 안(코드 폴더 = 이미지 코드 자리)에서만.
#   작업 폴더(진행 기록 batch_progress/·batches/)는 settings.yaml ops.run_pipeline.run_pipeline_work_dir(비우면 이 스크립트 옆 test_space/), 결과 공유 폴더는
#   prd <루트>/output(compose-prd.yml이 컨테이너 /app/output으로 붙이는 원본 그대로), dev 컨테이너 안은 /app/output.
TEST = PROG = DOCSPACE = DOCFLOW = STAGING = None  # configure()가 채움
DIRECT = False  # dev — 명령을 docker exec 없이 바로(configure()가 run_env로 정함)
PIPE_C = (
    "data-pipeline-0"  # docker exec 대상 상주 컨테이너(목록·받기·파싱·게시·구조화·정리) — 새벽 배치는 0번만(compose-<환경>.yml 이름 그대로)
)
MCP_C = "mcp-server-0"  # ③ 검색 확인 자리(prd — 코드가 든 파이프라인 이미지에는 mcp_server.cli가 없음, 같은 settings.yaml을 붙임)
DOCKER = "docker"  # 컨테이너 명령 — configure()가 ops.host.container_cli(없으면 docker, 그것도 없으면 podman)로 채움
CODE_DIR = None  # --code(설정 배치 모듈 layout.py·이미지 경로 표를 찾을 코드 폴더 — 운영자 폴더에서 돌릴 때, 기본 배치 경로 없음)
SOURCE_BUCKET = PG_CONTAINER = PG_USER = PG_DB = PG_SCHEMA = None  # staging 파일 이름의 원천 버킷 · 문서 수 세기(psql)
SETTINGS_REQUIRED = (  # (칸 경로, 무엇에 쓰나) — 없으면 시작 거부
    ("common.run_env", "실행 환경(dev·prd)"),
    ("common.connections.rdb.host", "EDW 서버 — 대상 목록(컨테이너 candidate_pick list, 읽기 계정 — ops.md#op-03)"),
    ("common.connections.rdb.database", "EDW DB"),
    ("common.connections.rdb.read.user", "EDW 읽기 계정"),
    ("common.connections.rdb.read.password", "EDW 읽기 계정 비밀번호"),
    ("common.connections.object_storage.endpoint", "Object Storage 주소 — publish·받기(컨테이너)"),
    ("common.connections.object_storage.access_key", "Object Storage 키(컨테이너)"),
    ("common.connections.object_storage.secret_key", "Object Storage 비밀 키(컨테이너)"),
    ("pipeline.load.publish.bucket", "publish 업로드 버킷(컨테이너)"),
    ("pipeline.load.publish.prefix", "publish 업로드 접두(컨테이너)"),
    ("pipeline.connections.rdb.bucket", "원천 버킷 — staging 파일 이름(candidate_ready와 같은 값)"),
    ("common.host.pg_container", "PostgreSQL 컨테이너 이름 — 문서 수 세기(psql)"),
    ("common.connections.pg.user", "PostgreSQL 계정 — 문서 수 세기(psql)"),
    ("common.connections.pg.db", "PostgreSQL DB — 문서 수 세기(psql)"),
)
DIRECT_SKIP = ("common.host.pg_container", "common.connections.pg.user", "common.connections.pg.db")  # 바로 부르면 psql 대신 앱이 PG에 붙음


def _code_root():
    """코드 폴더(저장소 트리 — <루트>/common이 있음) — 찾는 순서: --code 폴더 > 이 스크립트가 든 코드 폴더(기본 배치 경로는 없음)."""
    for r in (CODE_DIR, ROOT.parents[2] if len(ROOT.parents) > 2 else None):
        if r is not None and (Path(r) / "common" / "config" / "layout.py").is_file():
            return Path(r)
    sys.exit("run_pipeline: common/config/layout.py 없음 — 코드 폴더 안에서 부르거나 --code <코드 폴더>로 알려 줄 것")


def _root():
    """서버 루트(settings.yaml·output/이 바로 아래) = 코드 폴더 자체 — 셸에 남은 다른 벌의 RAG_ROOT는 보지 않는다."""
    return _code_root().resolve()


def _inside(seq, sub=""):
    """컨테이너 쪽 문서 임시 폴더 <output_root>/_docflow/<seq>[/sub]."""
    return f"{_img('output_root')}/_docflow/{seq}" + (f"/{sub}" if sub else "")


def _img(name):
    """명령이 보는 약속 경로 — prd는 컨테이너 안 약속 경로(settings.IMAGE_PATHS 한 곳), dev(DIRECT)는 이 프로세스가 보는 코드·결과 자리."""
    if DIRECT and name in ("code_root", "output_root"):
        return Path(_code_root() if name == "code_root" else DOCSPACE).as_posix()
    return _const(f"image.{name}")


def _in_image():
    """이 코드 폴더가 이미지 코드 자리(/app/deploy)인가 — dev는 컨테이너 안에서만 돈다."""
    return _code_root().resolve() == Path(_const("image.code_root"))


@functools.cache
def _const(key):
    """고정값(약속 경로 image.*): 코드 폴더 deploy/host/scripts/host_settings.tsv(없으면 이 스크립트 옆)의 const 줄(deploy/release/gen_host_keys.py가 만듦)."""
    f = next(
        (p for p in (_code_root() / "deploy" / "host" / "scripts" / "host_settings.tsv", ROOT / "host_settings.tsv") if p.is_file()),
        None,
    )
    if f is None:
        sys.exit("run_pipeline: host_settings.tsv 없음 — 코드 폴더(deploy/host/scripts/) 또는 이 스크립트 옆에 둘 것(--code)")
    for row in _host().table_rows(f):
        if len(row) >= 4 and row[2] == "const" and row[0] == key:  # 칸이 모자란 줄(손 편집·잘린 사본)은 건너뜀
            return row[3]
    sys.exit(f"run_pipeline: host_settings.tsv에 {key} 없음 — PYTHONPATH=. python deploy/release/gen_host_keys.py로 다시 만들 것")


def _app():
    return _img("code_root").rsplit("/", 1)[0]  # 컨테이너 작업 자리(코드 자리의 부모 — 이미지 WORKDIR)


@functools.cache
def _host():
    """호스트 설정 읽기 모듈(코드 폴더 deploy/host/scripts/settings_to_env.py — settings.yaml 읽기·호스트 칸 표 한 곳)을 파일로 읽음 —
    호스트 python은 pydantic이 없어 common 패키지를 import하지 않는다(그 모듈이 common/config/layout.py를 파일로 읽음)."""
    import importlib.util

    f = _code_root() / "deploy" / "host" / "scripts" / "settings_to_env.py"
    if not f.is_file():
        sys.exit("run_pipeline: deploy/host/scripts/settings_to_env.py 없음 — 코드 폴더 안에서 부르거나 --code <코드 폴더>로 알려 줄 것")
    spec = importlib.util.spec_from_file_location("settings_to_env", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_settings(settings_file=None):
    """(사전, 문제) — 서버 settings.yaml을 쓴 글자 그대로 읽는다(BaseLoader — 스칼라는 모두 글자: `password: 0123`·`user: no`가 83·False로
    바뀌지 않게, 앱 설정 모델의 글자 칸 규칙과 같음). 파일: settings_file > SETTINGS_FILE > <루트>/settings.yaml. 값은 찍지 않는다.
    파일 배치(required·역할 절)를 모델 배치(common·pipeline·mcp)로 바꿔 돌려준다 — 이 모듈의 칸 경로는 모델 경로."""
    path = Path(settings_file or os.environ.get("SETTINGS_FILE") or _root() / "settings.yaml")  # env 남김 — 설정 파일 자리 신호
    return _host().load_or_error(path)  # BaseLoader(글자만) + 같은 칸 두 번 거부 — 앱과 같은 규칙


def work_dir(doc):
    """작업 폴더(진행 기록 batch_progress/·batches/) — settings.yaml ops.run_pipeline.run_pipeline_work_dir(모델 pipeline.host.run_pipeline_dir), 비우면 이 스크립트 옆 test_space/."""
    work = _host().get(doc, "pipeline.host.run_pipeline_dir")
    return Path(work) if work else ROOT / "test_space"


def configure(settings_file=None, overrides=()):
    """서버 settings.yaml을 한 번 읽어 모듈 값(경로·접속)을 채운다 — 문제 목록(빈 목록이면 통과). 값은 찍지 않는다.
    overrides = --set 글자(`RUN_PIPELINE_<칸>=값`) — ops.run_pipeline 칸만 이 실행에서 덮는다."""
    global TEST, PROG, DOCSPACE, DOCFLOW, STAGING, MCP_JOBS_DIR, SOURCE_BUCKET, PG_CONTAINER, PG_USER, PG_DB, PG_SCHEMA
    global DOCKER, STAGING_TARGET, STAGING_WORKERS, STRUCT_WORKERS, VLM_CAP, LANE_WORKERS, _BACKLOG_SETTING, DIRECT
    doc, err = read_settings(settings_file)
    if err:
        return [err]
    run_env = _host().get(doc, "common.run_env")
    DIRECT = run_env == "dev"
    skip = DIRECT_SKIP if DIRECT else ()
    probs = [
        f"설정 필요: {_host().layout().to_yaml(p)} — {why}"
        for p, why in SETTINGS_REQUIRED
        if p not in skip and _host().get(doc, p) in (None, "")
    ]
    if run_env not in (None, "") and run_env not in ("dev", "prd"):
        probs.append("required.env.run_env가 dev·prd가 아님 — 서버 전용 러너(PC는 원본 받기 대역이 없음 — rn-05, CLAUDE.md 4절)")
    elif DIRECT and not _in_image():
        probs.append("dev는 data-pipeline 컨테이너 안에서 실행 — ssh -p <SSH 포트> root@<서버> 뒤 cd /app/deploy (server-guide §0-2)")
    policy, bad = run_pipeline_policy(doc, overrides)
    probs += bad
    if probs:
        return probs
    POLICY.update(policy)
    STAGING_TARGET, STRUCT_WORKERS, VLM_CAP = policy["staging"], policy["struct_workers"], policy["vlm_cap"]
    STAGING_WORKERS = policy["staging_workers"]
    LANE_WORKERS = {c: (policy[f"{c}_dedicated"], policy[f"{c}_shared"]) for c in LANES}
    _BACKLOG_SETTING = policy["struct_backlog"]
    TEST = work_dir(doc)
    PROG = TEST / "batch_progress"
    # prd: 컨테이너 /app/output 공유 볼륨의 원본(compose-prd.yml과 같은 자리) · dev: 컨테이너 안 그 자리(/app/deploy/output은 빈 자리로 가려짐)
    DOCSPACE = Path(_const("image.output_root")) if DIRECT else _root() / "output"
    DOCFLOW = DOCSPACE / "_docflow"  # 문서별 임시 디렉토리(종료 시 삭제)
    STAGING = DOCSPACE / "_staging"  # SOURCE_STAGING 대기열 저장소
    DOCKER = (
        os.environ.get("DOCKER")  # env 남김 — 호스트 도구(셸 env > ops.host.container_cli — load_settings.sh와 같은 순서)
        or _host().get(doc, "common.host.docker")
        or ("docker" if shutil.which("docker") else "podman")
    )
    MCP_JOBS_DIR = DOCSPACE / "_mcp_parse" / "jobs"  # mcp-data-parsing의 작업 폴더(같은 결과 폴더 — run_mcp_parsing.JOBS_DIR)
    SOURCE_BUCKET = _host().get(doc, "pipeline.connections.rdb.bucket")
    PG_CONTAINER = _host().get(doc, "common.host.pg_container")
    PG_USER, PG_DB = _host().get(doc, "common.connections.pg.user"), _host().get(doc, "common.connections.pg.db")
    PG_SCHEMA = _host().get(doc, "common.connections.pg.db_schema") or "data_parsing"  # 앱 설정 모델 기본값과 같음
    return []


# 컨테이너 안 앱이 읽는 설정 칸은 명령 인자 `--set 이름=값`으로 준다(common.config.setarg — 그 python이 덮기 파일로 자기와 자식에게 넘김).
# 앱은 env에서 설정을 읽지 않으므로 env로 주면 효과가 없다. 비밀 칸은 --set이 거부한다(명령 줄은 ps·로그에 남음).
def _embed_set():
    p = POLICY
    return (f"EMBED_CONCURRENCY={p['embed_concurrency']}", f"EMBED_BATCH={p['embed_batch']}", f"BM25_THREADS={p['bm25_threads']}")


def _parse_set(chan):
    """파싱 명령의 --set 값 — settings.yaml ops.run_pipeline(비우면 RUN_PIPELINE_DEFAULTS). 같은 이름은 뒤 값이 이기므로 vlm 레인 값을 뒤에 붙인다."""
    p = POLICY
    out = [
        f"VLM_MAX_CONCURRENCY={p['vlm_concurrency']}",
        f"VLM_CONCURRENCY={p['vlm_concurrency']}",
        f"VLM_FIGURES_MAX={p['figures_max']}",
        f"PARSE_POST={p['parse_post']}",
        f"RAPIDOCR_PAGE_WORKERS={p['rapidocr_page_workers']}",
        f"OCR_THREADS={p['ocr_threads']}",
        f"PIPE_PROCS={p['pipe_procs']}",
        f"PARSE_REP_SELECT={p['rep_select']}",
        f"PARSE_QA_LIGHT={int(p['qa_light'])}",
    ]
    if chan == "vlm":  # vlm 레인 — VLM 동시 수를 낮추고(vlm_cap 문서가 GPU 서버를 나눔) 스캔 쪽 VLM 전사(vlm_page)를 켬, 쪽 상한 없음
        n = p["vlm_lane_concurrency"]
        out += [f"VLM_MAX_CONCURRENCY={n}", f"VLM_CONCURRENCY={n}", f"PARSE_POST={p['vlm_lane_post']}", "VLM_PAGE_MAX="]
    return out


def cpu_gate(chan):
    """파싱 CPU 게이트(CPU_MAX_LOAD) 글자 — light 레인은 따로(heavy가 CPU·VLM을 기다리는 틈에 바로 소화)."""
    return f"{POLICY['light_cpu_gate' if chan == 'light' else 'cpu_gate']:g}"


LIB_ENV = "PYTHONDONTWRITEBYTECODE=0 PYTHONPYCACHEPREFIX=/tmp/pycache"  # env 남김 — 라이브러리(파이썬 자체 env, 설정 칸 아님)
DOC_MARK = "RUN_PIPELINE_DOC"  # 문서 표지 env(설정 칸 아님) — 고아 정리(sweep_cmd)가 /proc/*/environ에서 찾음
#   문서 하나의 파싱·게시·구조화 명령에 붙인다: 한 문서의 세 단계는 차례로만 돌아 정리 때 그 문서의 다른 단계 프로세스는 없다.
#   다른 문서의 프로세스는 값이 달라(-zx 통째 비교) 끄지 않는다.


_ERROR_NOTED: set = set()  # 호스트만 DLQ 기록 — 한 실행의 문서 번호마다 실패 CLI를 한 번만 호출


def pexec(script, seq=None, box=None):
    """컨테이너 명령 한 줄(목록·받기·분류·파싱·게시·구조화·정리 모두 여기서) — docker exec(dev는 이미 컨테이너 안이라 bash만) · umask ·
    작업 폴더 · PYTHONPATH · 라이브러리 env가 모두 같다. seq를 주면 그 문서 표지 env(DOC_MARK)도 붙인다(실패·시간 초과 뒤 sweep_cmd가 끔).
    export라 script 안 여러 python(구조화 → 적재)에 같은 env가 간다. script는 통째로 따옴표(shlex) — 안의 따옴표도 그대로."""
    env = f"PYTHONPATH={_img('code_root')} {LIB_ENV}" + (f" {DOC_MARK}={_inside(seq)}" if seq is not None else "")
    run = "bash -c " if DIRECT else f"{DOCKER} exec {box or PIPE_C} bash -c "
    return run + shlex.quote(f"umask 0002 && cd {_app()} && export {env} && {script}")


def sets(*pairs):
    """--set 인자 글자(앞 공백 포함) — 같은 이름이 여러 번이면 뒤 값이 이김(setarg)."""
    return "".join(f" --set {p}" for p in pairs)


# ── 컨테이너 명령 줄(명령 글자를 시험으로 고정하려고 함수로 둠) ──
def list_cmd(a):
    """대상 목록(컨테이너 안 candidate_pick list — EDW 읽기·끝난 문서 빼기·FAQ 먼저) → <결과 폴더>/_docflow/targets.json."""
    o = _img("output_root")
    opt = (f" --filter {a.filter}" if a.filter else "") + f" --start-offset {a.start_offset}"  # 글자는 main()이 거른 것만
    opt += (f" --limit {a.limit}" if a.limit else "") + (f" --seqs {a.seqs}" if a.seqs else "")
    opt += (" --skip-done" if a.skip_done else "") + (f" --max-docs {a.max_docs}" if a.max_docs else "")
    return pexec(f"python -m pipeline.extract.candidate_pick list{opt} --faq-seen {o}/{FAQ_SEEN} --out {_inside('targets.json')}")


def stage_cmd(seq):
    """문서 1개 미리 받기 — 컨테이너 안 candidate_ready stage(받기 → 같은 내용 하나만 → 형식·DRM·암호 거르기 → 파싱할 목록)."""
    o, inside = _img("output_root"), _inside(seq)
    st = sets(f"SOURCE_STAGING={o}/_staging", f"SOURCE_FETCH_WORKERS={POLICY['fetch_workers']}")
    return pexec(
        f"mkdir -p {o}/_staging && "
        f"python -m pipeline.extract.candidate_ready{st} stage --csv {inside}/batch.csv --out {inside} --prepared {inside}/prepared"
        f"{'' if POLICY['scan_rotate'] else ' --no-scan-rotate'}"
    )


def parse_cmd(seq, chan, gate):
    """문서 1개 파싱(받기·거르기는 stage가 끝냄) — chan(light·medium·vlm), gate(CPU 게이트 글자)."""
    inside = _inside(seq)
    doc = sets(
        f"PIPE_OUT_ROOT={inside}",
        f"DOC_DIR_PREPARED={inside}/prepared",
        f"PARSE_IMAGES_ROOT={inside}/parse/_images",
        f"PARSE_RAW_ROOT={inside}/parse",
        *_parse_set(chan),
        f"CPU_MAX_LOAD={gate}",
    )
    return pexec(f"echo [envcheck] gate={gate} 채널={chan}; python -m pipeline.cli{doc} parse --staged", seq)


def struct_cmd(seq):
    """문서 1개 구조화 + 적재. 엔진 구성은 파싱과 같은 파일(코드 폴더 — 판 번호 없음, 실행 중에는 안 바뀜)."""
    inside = _inside(seq)
    st = sets(*_embed_set())  # 묶음·적재 python에
    return pexec(
        f"python -m pipeline.transform.structure.gold_bundle{st} --parse-dir {inside}/parse --src {inside}/prepared"
        f" --out {inside}/bundle && "
        f"python -m pipeline.load.pgvector_load{st} load --fail-on-classify --bundle {inside}/bundle --rep-dir {inside}/parse/_rep "
        f"--silver {inside}/publish/silver.jsonl >> {inside}/structure.log 2>&1",
        seq,
    )


def publish_cmd(seq):
    """문서 1개 publish(Object Storage + 처리 기록 파일 publish/silver.jsonl — 적재가 doc 칸으로)."""
    inside = _inside(seq)
    return pexec(
        f"python -m pipeline.load.publish_parse_result --out {inside} --source-system FileStorageMap --apply >> {inside}/publish.log 2>&1",
        seq,
    )


def error_cmd(seq, reason, row=None, dlq_only=False):
    """문서 1개 실패 기록 — applog.except_doc_info error + DLQ 상태(pl-69). 문서 위치 표는 stage_one이 쓴 batch.csv."""
    opt = ""
    if row is not None:
        opt = f" --key={shlex.quote(row['s3_key'])} --name={shlex.quote(_doc_name(row))}"
        if row.get("source_system"):
            opt += f" --system={shlex.quote(row['source_system'])}"
    opt += " --dlq-only" if dlq_only else ""
    return pexec(f"python -m pipeline.shared.except_docs error --csv {_inside(seq)}/batch.csv --reason {reason}{opt}")


def note_error(seq, reason, row=None, dlq_only=False):
    """실패 기록(error_cmd) — 기록이 실패해도 흐름은 계속(경고 로그). 임시 폴더를 지우기 전에 부른다."""
    with _flow_lock:
        if seq in _ERROR_NOTED:
            return
        _ERROR_NOTED.add(seq)
    rc, out, err = sh(error_cmd(seq, reason, row, dlq_only), timeout=120)
    for line in ((out or "") + "\n" + (err or "")).splitlines():
        if line.startswith("[DLQ]"):
            log(line)  # dead 전이·기록 경고는 컨테이너 출력에만 묻히지 않게
    if rc != 0:
        log(f"doc#{seq} 실패 기록(DLQ·except_doc_info) 못 씀 — rc {rc}")


def sweep_cmd(seq):
    """고아 정리 — 이 문서 표지 env(DOC_MARK)를 가진 컨테이너 안 프로세스(bash·python·soffice까지 env 상속)를 모두 끔. environ 항목(NUL 구분)과
    통째로 같을 때만(-zx — 앞부분만 맞추면 doc 1 정리가 doc 10~19·100…까지 끔). 정리 명령 자신은 표지를 받지 않는다(seq 없이 pexec)."""
    return pexec(
        f'for p in /proc/[0-9]*; do grep -aqzx "{DOC_MARK}={_inside(seq)}" $p/environ 2>/dev/null && kill ${{p##*/}} 2>/dev/null; done'
    )


# ── 레인·대기열 정책(규칙: docs/prd/ops.md rn-01·rn-02) — settings.yaml ops.run_pipeline(configure()가 읽음).
# 기본값은 설정 모델 pipeline.config.PipelineHostRunPipeline와 같다(이 스크립트는 호스트 python이라 모델을 import하지 않음 — 시험이 둘을 대조).
RUN_PIPELINE_DEFAULTS = {
    "staging": 20,  # 진입 대기열 — 미리 받아 둘 문서 수(받는 중 포함 · 파싱 중 제외)
    "staging_workers": 2,  # 미리 받기 동시 수 — 실제 동시 받기 = min(이 값, 대기열 빈자리)
    "struct_workers": 2,  # 구조화·적재 스레드 수
    "struct_backlog": None,  # 중간 대기열 상한(파싱 끝·구조화 대기) — 비우면 구조화 워커 × 2, 0 = 상한 없음
    "vlm_cap": 2,  # vlm 문서 동시 파싱 상한(gpu 예산)
    "light_dedicated": 1,  # 레인별 전담 워커(자기 레인 문서만)
    "light_shared": 1,  # 레인별 공유 워커(자기 레인 먼저, 비면 다른 레인에서 가져옴)
    "medium_dedicated": 1,
    "medium_shared": 1,
    "vlm_dedicated": 1,
    "vlm_shared": 1,
    # 컨테이너 안 파싱·구조화 명령에 --set으로 넘기는 값(문서 하나씩 도는 서버 배치에 맞춘 값)
    "vlm_concurrency": 8,
    "vlm_lane_concurrency": 6,
    "figures_max": 10,
    "parse_post": "supsub,charts,figures,context,attachments",
    "vlm_lane_post": "supsub,charts,figures,context,attachments,vlm_page",
    "rapidocr_page_workers": 2,
    "ocr_threads": 1,
    "pipe_procs": 4,
    "fetch_workers": 2,
    "rep_select": "first",
    "qa_light": True,
    "scan_rotate": False,
    "cpu_gate": 1.3,
    "light_cpu_gate": 9.0,
    "embed_concurrency": 6,
    "embed_batch": 32,
    "bm25_threads": 3,
    # e2e 단계(rn-05) — ① 사전 점검 · ③ 적재·검색 확인 켜기, 사람이 돌릴 때 건수(0 = 전체 — 새벽 배치는 --limit 0)
    "steps_precheck": True,
    "steps_verify": True,
    "run_limit": 2,
}
POLICY = dict(RUN_PIPELINE_DEFAULTS)  # configure()가 settings.yaml 값으로 바꿈
LANES = ("light", "medium", "vlm")
STAGING_TARGET, STRUCT_WORKERS, VLM_CAP = (
    RUN_PIPELINE_DEFAULTS["staging"],
    RUN_PIPELINE_DEFAULTS["struct_workers"],
    RUN_PIPELINE_DEFAULTS["vlm_cap"],
)
STAGING_WORKERS = RUN_PIPELINE_DEFAULTS["staging_workers"]
LANE_WORKERS = {c: (RUN_PIPELINE_DEFAULTS[f"{c}_dedicated"], RUN_PIPELINE_DEFAULTS[f"{c}_shared"]) for c in LANES}  # 레인 → (전담, 공유)
_BACKLOG_SETTING = RUN_PIPELINE_DEFAULTS["struct_backlog"]  # main()이 STRUCT_BACKLOG로 풂(구조화 워커 수 인자가 덮은 뒤)
STRUCT_BACKLOG = 0
NO_CLEANUP = False
_class: dict = {}  # seq → "light"/"medium"/"vlm"(받은 뒤 분류)

LANEQ: dict = {c: collections.deque() for c in LANES}  # 레인별 대기 문서(dispatched 순서)
_struct_q: "queue.Queue" = queue.Queue()  # 중간 대기열 — 게시 끝·구조화(gold) 대기(main()이 씀)
_pub_q: "queue.Queue" = queue.Queue()  # 파싱 끝·게시 대기(게시를 gold 앞에, 따로 한 스레드)
_LOCK = None  # take_lock() 파일 — 프로세스 끝까지 쥠


def _waiting():
    """파싱은 끝났고 gold가 아직 시작 안 한 문서 수(게시 대기 + 구조화 대기) — STRUCT_BACKLOG가 이 값을 봄."""
    return _pub_q.qsize() + _struct_q.qsize()


MCP_JOBS_DIR = None  # MCP parse_document 작업 폴더 — configure()가 <결과 폴더>/_mcp_parse/jobs로
_mcp_pause = False  # MCP 업로드 파싱 중 medium 레인 완보(사람 대기 응답 우선)
_lane_inflight = {c: 0 for c in LANES}  # 레인 → 지금 파싱 중인 문서 수


def _lane_total():
    with _flow_lock:
        return sum(len(q) for q in LANEQ.values())


_flow_lock = threading.Condition()
_fetching: set = set()  # 지금 다운로드 진행 중인 seq(마지막 문서 조기 종료 방지)
_picked_all = threading.Event()  # 받기 워커가 차례를 모두 집음(마감으로 남은 차례를 버린 경우 포함)
_stop = threading.Event()
_stats_lock = threading.Lock()


def mark(seq, event, **extra):
    """단계 이벤트 기록(queue 대기·단계별 소요 로그) → doc_stats.jsonl"""
    rec = {"seq": seq, "event": event, "time": time.time(), **extra}
    with _stats_lock:
        with (PROG / "doc_stats.jsonl").open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def depth(event):
    """대기열 깊이 한 줄 → queue_depth.jsonl — 레인별 [대기, 진행]·받는 중·구조화 대기. 상태가 바뀌는 자리(dispatch·
    pick·파싱 끝·구조화 넣기·꺼내기)에서 부른다. _flow_lock은 재진입 가능(Condition 기본 RLock)."""
    with _flow_lock:
        rec = {
            "time": time.time(),
            "event": event,
            "lanes": {c: [len(LANEQ[c]), _lane_inflight[c]] for c in LANES},
            "fetching": len(_fetching),
            "pub_wait": _pub_q.qsize(),
            "struct_wait": _struct_q.qsize(),
        }
    try:  # 관찰용 기록 — 못 써도(디스크 가득 등) 예외를 내지 않는다: 스레드·대기열 집계 사이에서 불려, 죽으면 main()이 멈춤
        with _stats_lock:
            with (PROG / "queue_depth.jsonl").open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(rec) + "\n")
    except OSError as ex:
        _thread_error("대기열 기록", event, ex)


def pick_lane(own, shared, queues, inflight, vlm_cap):
    """다음 문서를 꺼낼 레인(없으면 None) — 자기 레인 먼저, 공유 워커만 자기 레인이 비었을 때 가장 긴 다른 레인에서.
    vlm 문서는 진행 중이 vlm_cap이면 건너뜀(전담 워커도)."""
    order = [own] + (sorted((c for c in queues if c != own), key=lambda c: -len(queues[c])) if shared else [])
    for c in order:
        if queues[c] and not (c == "vlm" and inflight["vlm"] >= vlm_cap):
            return c
    return None


def run_pipeline_policy(doc, overrides=()):
    """settings.yaml ops.run_pipeline(모델 pipeline.host.run_pipeline) → (값, 문제 목록). 비운 칸은 RUN_PIPELINE_DEFAULTS. 글자 그대로 읽으므로(BaseLoader) 정수로 바꿈.
    overrides(--set `RUN_PIPELINE_<칸>=값` — 칸 이름은 설정 모델의 옛 env 이름과 같음)가 파일 값을 이 실행에서만 덮는다."""
    sec = _host().get(doc, "pipeline.host.run_pipeline")
    sec = dict(sec) if isinstance(sec, dict) else {}
    vals, probs = {}, []
    for o in overrides:
        name, eq, v = o.partition("=")
        up = name.strip().upper()
        k = up[len("RUN_PIPELINE_") :].lower()
        if not eq or not up.startswith("RUN_PIPELINE_") or k not in RUN_PIPELINE_DEFAULTS:
            probs.append(f"--set {name} — RUN_PIPELINE_<칸>=값만(칸: {', '.join(k.upper() for k in RUN_PIPELINE_DEFAULTS)})")
            continue
        sec[k] = v.strip()
    where = lambda k: _host().layout().to_yaml(f"pipeline.host.run_pipeline.{k}")  # 안내 글자에 파일 자리
    for k, d in RUN_PIPELINE_DEFAULTS.items():
        v = sec.get(k)
        if v in (None, ""):  # YAML null은 읽을 때 None(settings_to_env.load_model)
            vals[k] = d
            continue
        try:
            if isinstance(d, bool):
                b = _host().render(v, "bool")  # 켜기 칸 규칙 한 곳(settings_to_env) — 모르는 글자는 ValueError
                if b is None:
                    raise ValueError
                vals[k] = b == "1"
            elif isinstance(d, str):
                vals[k] = str(v)
            else:
                vals[k] = (float if isinstance(d, float) else int)(v)
                if vals[k] < 0:
                    raise ValueError
        except ValueError:
            vals[k] = d
            probs.append(f"{where(k)} 형식 오류 — " + ("true·false만" if isinstance(d, bool) else "0 이상 수만"))
    if probs:
        return vals, probs
    for k in (
        "staging",
        "staging_workers",
        "vlm_cap",
    ):  # 0이면 문서를 안 받거나(staging·staging_workers) vlm 레인을 아무도 안 집어 배치가 끝나지 않음
        if vals[k] < 1:
            probs.append(f"{where(k)} — 1 이상만")
    shared = sum(vals[f"{c}_shared"] for c in LANES)
    for c in LANES:  # 어느 워커도 못 집는 레인이 있으면 그 큐가 안 비어 배치가 끝나지 않음
        if vals[f"{c}_dedicated"] + shared < 1:
            probs.append(f"ops.run_pipeline — {c} 레인을 처리할 워커가 없음({where(c + '_dedicated')}와 모든 *_lane.shared_workers가 0)")
    return vals, probs


def stack_check():
    """엔진 구성 파일 확인 — 시작 때 한 번(파싱 컨테이너 안 show-stack — 파일을 못 읽거나 모양이 틀리면 종료 2, 시작하지 않음).
    없는 엔진은 파싱 입구가 거부한다(engine_check.resolve)."""
    rc, _, err = sh(pexec("python -m pipeline.cli show-stack"), timeout=120)
    if rc != 0:
        print(f"[중단] 엔진 구성 파일을 읽지 못함(종료 코드 {rc}) — {(err or '').strip()[-200:]}", flush=True)
        raise SystemExit(verdict(2, "엔진 구성 파일"))  # 설정 문제 = 2(실패 문서 1과 가름)


# ① 사전 점검 — (이름, 컨테이너 명령, 시간 제한 초), 이 순서로 처음 실패에서 멈춤(host_ctl.sh check와 같은 점검 — 검색 MCP 응답은 ③에서).
#   배포 시험 판정은 종료 코드가 아니라 알려진 실패 목록으로(selftest_gate.sh {gate} — prd 이미지 /app/docker, dev는 붙인 코드 폴더 deploy/release).
PRECHECK = (
    ("설정", "python -m common.check.checker env", 300),
    ("모델 연결", "python -m common.check.checker ping", 300),
    ("DB 판", "python -m common.store.db.dbtool check --target all", 300),
    ("배포 시험", "bash {gate} python -m pipeline.cli selftest", 3600),
)


def _step_fail(step, name, rc, out, err):
    """점검 하나 실패 — 그 명령 출력 끝(최대 20줄)을 진행 기록에 남기고 그 이름을 돌려줌."""
    log(f"[{step}] {name} — 실패(종료 코드 {rc})")
    for ln in f"{out or ''}\n{err or ''}".strip().splitlines()[-20:]:
        log(f"  {ln}")
    return name


def precheck():
    """① 사전 점검 → 실패한 점검 이름(통과면 None)."""
    gate = (
        f"{_img('code_root')}/deploy/release/selftest_gate.sh" if DIRECT else "/app/docker/selftest_gate.sh"
    )  # dev 실행 이미지 /app/docker에는 없음
    for name, cmd, t in PRECHECK:
        rc, out, err = sh(pexec(cmd.format(gate=gate)), timeout=t)
        if rc != 0:
            return _step_fail("점검", name, rc, out, err)
        log(f"[점검] {name} — 통과")
    return None


def verify(rows, done_keys, since=0.0):
    """③ 적재·검색 확인 → 실패한 확인 이름(통과면 None). 이번 실행에서 적재까지 끝난 문서 하나로 — 실행 기록(applog: since 뒤
    pipe_run 1행+ · 그 문서 pipe_event 1행+) → 그 이름(확장자 뺌)을 질문으로 원천 DB 검색(search_ask, 근거 1건 이상) →
    검색 MCP 바깥 호출(mcp_smoke — 주소 dev.search_ui.search_ui_mcp_url · 토큰 required.tokens.mcp_token)."""
    row = next((rows[s] for s in rows if rows[s]["s3_key"] in done_keys), None)
    if row is None:
        log("[확인] 적재 — 이번 실행에서 적재까지 끝난 문서 0건")
        return "적재"
    src, q = shlex.quote(str(row["source_system"])), shlex.quote(Path(_doc_name(row)).stem)
    log(f"[확인] 적재 — 통과(원천 {row['source_system']} · 질문 {Path(_doc_name(row)).stem})")
    t, doc = f"to_timestamp({since:.0f})", "'" + _doc_name(row).replace("'", "''") + "'"
    rc, out, err = _psql(
        f"SELECT (SELECT count(*) FROM applog.pipe_run WHERE started_at >= {t}),"
        f" (SELECT count(*) FROM applog.pipe_event WHERE doc_id = {doc} AND ts_start >= {t})"
    )
    try:
        runs, events = (int(x) for x in (out or "").strip().splitlines()[-1].split("|")) if rc == 0 else (0, 0)
    except (ValueError, IndexError):
        runs = events = 0
    if runs < 1 or events < 1:
        return _step_fail("확인", f"실행 기록(pipe_run {runs}행 · 그 문서 pipe_event {events}행)", rc or 1, out, err)
    log(f"[확인] 실행 기록 — 통과(pipe_run {runs}행 · 그 문서 pipe_event {events}행)")
    rc, out, err = sh(pexec(f"python -m mcp_server.cli.search_ask ask --source {src} --k 3 --q={q} --json", box=MCP_C), timeout=300)
    try:
        n = len(json.loads((out or "")[(out or "").index("{") :]).get("evidence") or []) if rc == 0 else 0
    except ValueError:
        n = 0
    if n < 1:
        return _step_fail("확인", "DB 검색", rc or 1, out, err)
    log(f"[확인] DB 검색 — 통과(근거 {n}건)")
    rc, out, err = sh(pexec(f"python -m mcp_server.cli.mcp_smoke --source {src} --q={q}", box=MCP_C), timeout=300)
    if rc != 0:
        return _step_fail("확인", "검색 MCP", rc, out, err)
    log("[확인] 검색 MCP — 통과")
    return None


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


def doc_sh(seq, cmd, timeout, log):
    """문서 하나의 파싱·게시·구조화 명령 → 종료 코드(124 = 시간 초과). 실패·시간 초과면 호스트 쪽 docker exec만 끝나고 컨테이너 안
    프로세스는 남을 수 있어 그 문서 표지 env를 가진 프로세스를 끈다(sweep_cmd)."""
    rc, _, _ = sh(cmd, timeout=timeout, log=log)
    if rc != 0:
        sh(sweep_cmd(seq), timeout=30)
    return rc


def _tail(path, n=150):
    """실패 안내용 — 로그 파일 끝 n자(못 읽으면 빈 글자). sh(log=…)는 출력을 파일로 보내 오류 글자가 없다(None)."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - 4 * n))
            return f.read().decode("utf-8", "replace")[-n:]
    except OSError:
        return ""


def _fail_note(rc, seq, log_name):
    """실패 안내 꼬리 — 시간 초과(rc 124) 표시 + 그 문서 로그 끝."""
    return ("시간 초과 · " if rc == 124 else "") + _tail(DOCFLOW / str(seq) / log_name)


def now():
    return datetime.datetime.now()


def log(msg):
    print(f"[{now():%H:%M:%S}] {msg}", flush=True)
    with (PROG / "progress.log").open("a", encoding="utf-8") as fp:
        fp.write(f"[{now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def write_doc_csv(row, path):
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "s3_key", "original_filename", "file_size", "source_system"])  # 원천 = FileStorageMap.source_system(op-17)
        w.writerow([row["id"], row["s3_key"], row["original_filename"], row["file_size"], row["source_system"]])


def stage_one(seq, row):
    """문서 1개 미리 받기(candidate_ready stage — 상주 컨테이너 env 그대로). 실패하면 그 문서 파싱이 실패로 끝난다(따로 받는 길 없음).
    늘 stage를 부른다 — ETag 확인·같은 밤 중복 표시는 stage 안에 있고, staging 원본의 ETag가 같으면 stage가 다시 받지 않는다.
    앞 실행의 _docflow/<seq>는 지우고 새로 만든다(seq는 실행마다 바뀜)."""
    d = DOCFLOW / f"{seq}"
    if d.exists():
        _wipe(seq)
    d.mkdir(parents=True, exist_ok=True)
    write_doc_csv(row, d / "batch.csv")
    rc, _, err = sh(stage_cmd(seq), timeout=900, log=d / "stage.log")
    if rc == 0:
        (d / ".staged").touch()
    else:
        log(f"doc#{seq} 받기(stage) 실패 — 이 문서는 파싱 실패로 끝남 ({err or _tail(d / 'stage.log', 100)})")
    return rc == 0


def _class_cache():
    """분류 캐시(s3_key → heavy/light) — 재실행 시 probe 재사용."""
    p = PROG / "docflow_class.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


_class_lock = threading.Lock()  # 분류 캐시 — 미리 받기 워커 여럿이 같은 사전·파일을 씀


def _class_save(cache):
    """호출자가 _class_lock을 잡은 채로 부른다(사전을 글자로 바꾸는 동안 다른 워커가 넣지 않게)."""
    p = PROG / "docflow_class.json"
    p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def classify_doc(seq, row, cache=None):
    """레인 분류(규칙: PRD rn-01) — 규칙은 컨테이너 안 pipeline/extract/doc_lane_group.py의 doc_lane_group() 하나.
    캐시(s3_key) 우선 — 캐시에 있으면 docker exec를 안 부른다. 답(마지막 줄 — pymupdf 경고 섞임 방지)이 없으면 보수적으로 vlm."""
    t_c = time.time()  # 소요 기록: 분류 전체 · probe_sec = 컨테이너 호출만
    name = _doc_name(row)
    if cache is not None:
        with _class_lock:
            hit = cache.get(row["s3_key"])
        if hit:
            _class[seq] = hit
            mark(seq, "classify", doc=_doc_name(row), ocr=hit, cached=True, sec=round(time.time() - t_c, 2))
            return hit
    t_p = time.time()
    rc, out, _ = sh(  # PYTHONPATH = 코드 폴더 — 그러면 그룹 판별 1건이 extract.classify 행으로 남는다(doc_id = name)
        pexec(
            f"python3 {_img('code_root')}/pipeline/extract/doc_lane_group.py "
            f"{_img('output_root')}/_staging/{_staging_bin(row)} {shlex.quote(name)} {int(row.get('file_size') or 0)}"
        ),
        timeout=60,
    )
    probe_sec = time.time() - t_p
    cls = next((ln.strip() for ln in reversed((out or "").splitlines()) if ln.strip() in LANES), "vlm")
    if cache is not None:
        with _class_lock:
            cls = cache.setdefault(row["s3_key"], cls)  # 다른 워커가 먼저 넣었으면 그 값
            _class_save(cache)
    _class[seq] = cls
    mark(seq, "classify", doc=_doc_name(row), ocr=cls, cached=False, sec=round(time.time() - t_c, 2), probe_sec=round(probe_sec, 2))
    return cls


DEADLINE_AT = None  # --deadline(새벽 배치 마감) — 이 시각(epoch 초)이 지나면 새 문서를 받기 시작하지 않음
_deadline_hit = threading.Event()  # 마감으로 남은 문서를 받지 않았음 → 종료 코드 75
# 종료 코드(규칙: pl-18): 대상 0건·모두 끝 = 0, 실패 있음 = 1, 마감 도달(실패 없음)·다른 run_pipeline이 도는 중 = 75,
# ① 사전 점검·③ 적재·검색 확인 실패 = 3(rn-05)
EXIT_FAIL = 1
EXIT_CHECK = 3
EXIT_DEADLINE = 75


def verdict(rc, why=""):
    """끝 줄 판정 — 사람이 돌린 e2e·새벽 배치 모두 이 줄 하나로 본다(rn-05). rc를 그대로 돌려줌."""
    log(f"[판정] {'통과' if rc == 0 else '멈춤' if rc == EXIT_DEADLINE else '실패'}{' — ' + why if why else ''} · 종료 코드 {rc}")
    return rc


def deadline_at(hhmm, now=None):
    """HH:MM → 다음 그 시각(epoch 초) — 지금보다 이르거나 같으면 다음 날(자정을 넘는 배치 — 23:00 시작·05:00 마감)."""
    now = datetime.datetime.now() if now is None else now
    h, m = (int(x) for x in hhmm.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now:
        t += datetime.timedelta(days=1)
    return t.timestamp()


_STAGE_FAILED: set = set()  # 받기 스레드 예외가 난 문서 자리(실행 중 누적)
_STAGE_ERR = [0]  # 받기 워커 스레드 예외 수 — main()이 실패 수(thread_err)에 더함


def downloader(rows, order):
    """대기열 유지 — 지정 문서 순서대로 STAGING_TARGET개(받는 중 포함)까지 미리 받아 둔다(파싱 중 제외). 받기 워커 STAGING_WORKERS개가
    차례(order)를 하나씩 집어 동시에 받는다: 실제 동시 받기 = min(STAGING_WORKERS, 대기열 빈자리).
    빈자리가 없으면 워커가 있어도 받지 않는다. 다 집으면 워커가 끝나고, 모두 끝나면 이 함수도 끝난다."""
    cache = _class_cache()
    pos = {"ptr": 0}
    if not order:
        _picked_all.set()

    def worker():
        while not _stop.is_set():
            with _flow_lock:
                if pos["ptr"] >= len(order):
                    return
                if DEADLINE_AT is not None and time.time() >= DEADLINE_AT:  # 마감 — 남은 차례는 다음 새벽 배치가 다시 고름
                    _deadline_hit.set()  # 종료 코드 75
                    log(f"마감 — 남은 {len(order) - pos['ptr']}건은 받지 않음(받은 문서는 끝까지)")
                    pos["ptr"] = len(order)
                    _picked_all.set()
                    return
                if _lane_total() + len(_fetching) >= STAGING_TARGET:  # 빈자리 없음 — 파싱이 하나 시작되면 notify
                    _flow_lock.wait(5)
                    continue
                seq = order[pos["ptr"]]
                pos["ptr"] += 1
                if pos["ptr"] >= len(order):
                    _picked_all.set()
                _fetching.add(seq)
            row = rows[seq]
            t_w = time.time()
            dispatched = False  # 레인에 넘긴 뒤에는 기록만 실패해도 문서 처리를 레인에 맡김
            try:
                ok = stage_one(seq, row)
                # sec = 컨테이너 기동·head·전송·기록을 모두 합친 단계 전체 시간(순수 전송 속도 아님 — 그건 source.py 쪽 계측)
                mark(
                    seq,
                    "stage_end",
                    ok=ok,
                    sec=round(time.time() - t_w, 1),
                    bytes=row.get("file_size"),
                    doc=_doc_name(row),
                )
                classify_doc(seq, row, cache=cache)  # OCR 필요도 사전 분류(캐시 우선) → 워커 배분용
                with _flow_lock:
                    LANEQ[_class.get(seq) or "light"].append(seq)
                    dispatched = True
                    _fetching.discard(seq)
                    _flow_lock.notify_all()
                mark(seq, "dispatched")
            except Exception as ex:  # 받기·분류·기록 예외(디스크 가득 등) — 워커가 죽으면 _fetching에 남아 _flow_done()이 안 끝남
                _thread_error("받기", seq, ex)
                if dispatched:  # 임시 파일·실패 상태는 레인이 끝까지 책임짐
                    continue
                with _flow_lock:
                    _STAGE_ERR[0] += 1
                    _STAGE_FAILED.add(seq)
                    _fetching.discard(seq)
                    _flow_lock.notify_all()
                _safe(note_error, seq, "stage_failed", row)
                _safe(drop_temp, seq)
                continue
            depth("dispatch")

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, STAGING_WORKERS))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def parse_one(seq, row):
    """문서 1개 파싱 — 공유 상주 컨테이너(PIPE_C) 안에서 워커별 분리(경로 격리).
    문서마다 출력 루트(PIPE_OUT_ROOT·DOC_DIR_PREPARED — --set으로 넘김)를 따로 둔다.
    VLM·OCR·후처리 값은 settings.yaml ops.run_pipeline, 쪽 해상도는 extract.page_render_dpi.
    → True(성공) · False(실패) · SKIP(받기가 중복·DRM·암호로 빼서 파싱할 것 없음 — 실패 아님, 받기가 except_doc_info skip에 이미 씀 — 게시·gold 없음, pl-02)."""
    d = DOCFLOW / f"{seq}"  # stage_one이 만든 문서 폴더(batch.csv 포함)
    doc_log = PROG / f"doc_{seq}.log"
    t0 = time.time()
    mark(seq, "parse_start")
    only = d / "parse" / "_source" / "only.txt"  # stage가 쓴 파싱할 이름 목록(거르기를 지난 것)
    if (d / ".staged").exists() and only.exists() and not only.read_text(encoding="utf-8").strip():
        mark(seq, "parse_end", ok=True, skip=True, rep=0, sec=0)
        log(f"doc#{seq} 파싱 건너뜀 — 받기가 중복·DRM·암호로 뺌(게시·gold 없음) — {row['original_filename'][:44]}")
        return SKIP
    print(f"[{now():%H:%M:%S}] doc#{seq} 파싱 시작 — {row['original_filename'][:44]}", flush=True)
    chan = _class.get(seq) or "light"
    gate = cpu_gate(chan)
    rc = doc_sh(seq, parse_cmd(seq, chan, gate), 2700, doc_log)
    rep = d / "parse" / "_rep"
    n = len([p2 for p2 in rep.glob("*.json") if p2.name != "index.json"]) if rep.exists() else 0
    ok = rc == 0 and n > 0
    mark(seq, "parse_end", ok=ok, rep=n, sec=round(time.time() - t0, 1))
    log(f"doc#{seq} 파싱 {'OK' if ok else 'FAIL'}({(time.time() - t0) / 60:.1f}분) · rep {n}건 — {row['original_filename'][:44]}")
    return ok


SKIP = "skip"  # parse_one — 받기가 뺀 문서(파싱·게시·gold 없이 원본·임시 폴더만 지움)


PARSE_FAILED = "parse_failed"  # publish 명령은 성공했지만 그 문서를 파싱 실패로 제외함


def _publish_parse_failed(seq):
    """기존 publish JSON 출력의 by_status만 읽는다(게시 출력·종료 코드 계약은 그대로)."""
    report = DOCFLOW / str(seq) / "publish.log"
    for line in reversed(report.read_text(encoding="utf-8").splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and "by_status" in result:
            return result["by_status"].get("failed", 0) > 0
    raise ValueError("publish 결과 JSON 없음")


def publish_one(seq):
    """silver 게시(Object Storage + 처리 기록 파일 — 파싱 바로 뒤, gold 전). 성공해야 원본을 지우고 gold로 넘어간다."""
    t1 = time.time()
    mark(seq, "pub_start")
    rc = doc_sh(seq, publish_cmd(seq), 900, PROG / f"doc_{seq}.log")
    parse_failed = rc == 0 and _publish_parse_failed(seq)
    ok = rc == 0 and not parse_failed
    mark(seq, "pub_end", ok=ok, sec=round(time.time() - t1, 1))
    log(
        f"doc#{seq} publish {'OK' if ok else 'FAIL'}({(time.time() - t1) / 60:.1f}분)"
        + (" — 파싱 실패(parse_failed)로 게시 제외 · 원본 남김" if parse_failed else "")
        + (f" — 원본 남김 · {_fail_note(rc, seq, 'publish.log')}" if rc != 0 else "")
    )
    return PARSE_FAILED if parse_failed else ok


def gold_one(seq, enq_t=None):
    """gold = 구조화+적재(문서 경계 없이 — 게시 성공 뒤). 반환은 명령 종료 코드(3=분류 실패). enq_t=게시 끝 시각(구조화 대기 계산)."""
    t0 = time.time()
    wait = round(t0 - enq_t, 1) if enq_t else 0
    mark(seq, "struct_start", queue_wait=wait)
    rc = doc_sh(seq, struct_cmd(seq), 1800, PROG / f"doc_{seq}.log")
    ok = rc == 0
    mark(seq, "struct_end", ok=ok, sec=round(time.time() - t0, 1))
    log(
        f"doc#{seq} 구조화+적재 {'OK' if ok else 'FAIL'}(대기 {wait / 60:.1f}분 · 실행 {(time.time() - t0) / 60:.1f}분)"
        + (" — 분류 실패(classify_failed)" if rc == 3 else "")
        + ("" if ok else f" — silver는 남김(게시됨, gold는 silver에서 다시 만듦) · {_fail_note(rc, seq, 'structure.log')}")
    )
    return rc


def _doc_name(row):
    """pipe_event.doc_id와 맞추는 파일 이름 — 호스트 기록(seq)과 DB 행(doc_id)을 잇는 열쇠."""
    return row["original_filename"].rsplit("/", 1)[-1]


def _staging_bin(row):
    return hashlib.sha1(f"{SOURCE_BUCKET}|{row['s3_key']}".encode()).hexdigest() + ".bin"


def _staging_etag(row):
    """받은 판의 ETag 파일 — candidate_ready가 원본 옆에 같은 이름 .etag로 씀."""
    return _staging_bin(row)[: -len(".bin")] + ".etag"


def drop_original(seq, row):
    """원본 삭제(silver 게시가 성공한 뒤에만): staging 원본·그 ETag 파일(<sha1>.etag — stage가 받은 판 표시)과 문서 폴더의 링크(_source_files). 파싱 결과(parse/)는 gold가 씀.
    컨테이너(uid 10001)가 만든 파일은 호스트가 못 지우므로 docker exec(같은 공유 볼륨, 그 uid)로 지우고 잔여만 호스트가 마무리."""
    if NO_CLEANUP:
        return
    o = _img("output_root")
    sh(
        pexec(f"rm -rf {_inside(seq, '_source_files')} ; rm -f {o}/_staging/{_staging_bin(row)} {o}/_staging/{_staging_etag(row)}"),
        timeout=60,
    )
    shutil.rmtree(DOCFLOW / f"{seq}" / "_source_files", ignore_errors=True)
    (STAGING / _staging_bin(row)).unlink(missing_ok=True)
    (STAGING / _staging_etag(row)).unlink(missing_ok=True)


def drop_temp(seq):
    """문서 끝 — docflow 임시 폴더만 지움(어느 길이든). 원본(staging)은 drop_original만 지운다 — 파싱·게시 실패면 남음."""
    if NO_CLEANUP:
        return
    _wipe(seq)


def _wipe(seq):
    """_docflow/<seq> 통째로 지움 — 컨테이너(uid 10001)가 만든 파일은 docker exec로, 잔여는 호스트가."""
    sh(pexec(f"rm -rf {_inside(seq)}"), timeout=60)
    shutil.rmtree(DOCFLOW / f"{seq}", ignore_errors=True)


def take_lock(path):
    """겹침 막는 잠금 — 사람이 돌린 run_pipeline과 새벽 배치가 함께 돌지 않게. 잡으면 파일 객체(프로세스 끝까지 쥠), 이미 잡혀 있으면 None.
    flock은 프로세스가 죽으면 커널이 풀어 줘 남은 잠금 파일 문제가 없다. 호스트는 Linux(RHEL)뿐 — fcntl은 여기 한 곳만."""
    import fcntl

    fp = open(path, "a", encoding="utf-8")  # 프로세스 끝까지 열어 둠(닫으면 잠금이 풀림)
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fp.close()
        return None
    return fp


FAQ_SEEN = "_faq_seen.txt"  # 교체를 마친 FAQ 키(결과 폴더 — 컨테이너가 읽고 씀)


def pick_targets(a):
    """대상 목록 — 컨테이너 list 명령을 부르고 목록 파일을 읽음 → (rows {seq: 행}, order, total, start). 실패면 None(로그)."""
    res = DOCFLOW / "targets.json"
    res.unlink(missing_ok=True)
    rc, out, err = sh(list_cmd(a), timeout=2400)  # 안쪽 FAQ 맞추기(candidate_pick — 1800초)가 먼저 끊기게 더 길게
    for ln in (out or "").splitlines():  # 컨테이너가 낸 판단 줄(skip-done·FAQ·max-docs)을 진행 기록에
        if ln.strip() and not ln.lstrip().startswith("{"):
            log(ln.strip())
    try:
        got = json.loads(res.read_text(encoding="utf-8")) if rc == 0 else None
    except (OSError, ValueError):
        got = None
    if got is None:
        log(f"대상 목록(candidate_pick list) 실패 — rc={rc}: {str(err)[-300:]}")
        return None
    return {d["seq"]: d for d in got["docs"]}, [d["seq"] for d in got["docs"]], got["total"], got["start"]


PG_SOURCES = (
    "sfdc",
    "crms",
    "las",
    "faq",
    "other",
)  # 원천 스키마 <스키마>_<원천>(search_tables.SOURCES와 같음 — 호스트 python은 common을 못 읽음)


# dev 컨테이너 안에는 psql·docker가 없어 앱의 PG 접속(required.pg)으로 같은 꼴(psql -At: 칸은 |, 행은 줄)을 찍는다.
PG_PY = "import sys; from common.store.pg import PG, conf; [print('|'.join(map(str, r.values()))) for r in PG(conf()).q(sys.argv[1])]"


def _psql(sql):
    if DIRECT:
        return sh(pexec(f"python -c {shlex.quote(PG_PY)} {shlex.quote(sql)}"), timeout=60)
    return sh(
        f"{DOCKER} exec {PG_CONTAINER} psql -U {PG_USER} -d {PG_DB} -Atc {shlex.quote(sql)}", timeout=60
    )  # 설정 칸(PG 컨테이너·DB·스키마)


def pg_sources():
    """원천 이름 — 5벌 + DB에 있는 DEV 원천 스키마 `<스키마>_dev_<n>`(op-17 — 설정에 넣은 DEV 원천은 dbtool up이 만든 뒤 여기 잡힘). 못 읽으면 5벌만."""
    rc, out, _ = _psql(f"SELECT schema_name FROM information_schema.schemata WHERE schema_name ~ '^{PG_SCHEMA}_dev_[1-9][0-9]?$'")
    dev = (
        [n[len(PG_SCHEMA) + 1 :] for n in (out or "").split() if re.fullmatch(rf"{re.escape(PG_SCHEMA)}_dev_[1-9][0-9]?", n)]
        if rc == 0
        else []
    )
    return (*PG_SOURCES, *sorted(dev, key=lambda s: int(s[len("dev_") :])))


def pg_count():
    """(문서 수, 청크 수) — 원천 스키마(5벌 + 있는 DEV 원천)의 합. 못 세면 (0, 0)."""
    srcs = pg_sources()
    doc, chunk = (" + ".join(f"(SELECT count(*) FROM {PG_SCHEMA}_{s}.{t})" for s in srcs) for t in ("doc", "chunk"))
    rc, out, _ = _psql(f"SELECT {doc}, {chunk}")
    try:
        parts = out.replace("|", " ").split()
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def mcp_busy():
    """MCP 업로드 처리 중이면 True(공유 볼륨 _mcp_parse/jobs/<id>의 파일 mtime이 30초 내 갱신).
    5초마다 불리므로 작업 폴더 전체가 아니라 이름 날짜(<YYYYMMDD>-…, run_mcp_parsing)가 어제·오늘·내일인 폴더만 본다(
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


def _mcp_pause_monitor_once():
    """레인 워커를 띄우기 전에 초기 MCP 양보 상태를 읽는다."""
    global _mcp_pause
    _mcp_pause = mcp_busy()


def _mcp_pause_monitor():
    """5초마다 MCP 작업 감지해 _mcp_pause 토글(사람 대기 파싱 → medium 레인 완보)."""
    global _mcp_pause
    while not _stop.is_set():
        _mcp_pause = mcp_busy()
        _stop.wait(5)


def _thread_error(stage, seq, ex):
    """작업 스레드가 예외 처리·기록 중 다시 예외를 만났을 때 — 로그 파일도 못 쓸 수 있어 표준 오류로만(스레드는 계속)."""
    print(f"[run_pipeline] doc#{seq} {stage} 스레드 예외(계속) — {type(ex).__name__}: {str(ex)[:160]}", file=sys.stderr, flush=True)


def _safe(fn, *args):
    """정리(drop_original·drop_temp) — 정리 자체가 실패해도(디스크 가득·docker 없음) 작업 스레드는 계속(집계는 호출자가 함)."""
    try:
        fn(*args)
    except Exception as ex:
        _thread_error("정리", args[0], ex)


def _ran(stage, fn, seq, *args, failure=False):
    """단계(파싱·게시·구조화) 실행 — 예외는 그 단계 실패로(progress.log에 남기고 False). 집계·정리는 호출자가 함."""
    try:
        return fn(seq, *args)
    except Exception as ex:
        log(f"doc#{seq} {stage} 예외 — {type(ex).__name__}: {str(ex)[:120]}")
        return failure


def dlq_state():
    """호스트는 앱을 import하지 않고 컨테이너 CLI로 상태를 읽는다(접속 정보 출력 없음)."""
    rc, out, _ = sh(pexec("python -m pipeline.shared.dlq list --status pending,dead --json"), timeout=120)
    try:
        return {r["source_key"]: r for r in json.loads(out.strip().splitlines()[-1])} if rc == 0 else None
    except (ValueError, IndexError, TypeError, KeyError):
        return None


def run_flow(rows, order):
    """받기 → 파싱 → silver 게시 → gold를 한 번 실행하고 결과를 반환."""
    completed, failed_keys, loaded = set(), set(), set()  # loaded = gold까지 끝난 문서(③ 확인 대상 — 건너뜀 제외)
    t_all = time.time()
    tf = threading.Thread(target=downloader, args=(rows, order), daemon=True, name="downloader")
    tf.start()

    # 문서별 순서: 파싱 → silver 게시(pub_q, 게시 스레드) → 원본 삭제 → gold(struct_q, 구조화 스레드) → 임시 삭제.
    # 게시를 따로 두어 구조화가 업로드를 기다리지 않는다. 파싱 실패·게시 실패면 원본을 남기고 gold로 가지 않는다.
    cnt = {
        "ok": 0,
        "skipped": 0,
        "parse_fail": 0,
        "pub_fail": 0,
        "gold_fail": 0,
        "thread_err": 0,
    }  # thread_err — 집계 전에 스레드 예외(종료 코드 1로)

    def _queue_loop(q, stage, work):
        """q에서 꺼내 work(*item)를 돌리는 스레드 — None이면 끝. 예외 처리·기록 중 예외(디스크 가득 등)도 스레드를 죽이지 않게 —
        죽으면 q.join()이 안 끝남."""
        while True:
            item = q.get()
            depth(f"{stage}_get")
            with _flow_lock:
                _flow_lock.notify_all()  # 중간 대기 하나 줄어듦 → 상한에서 기다리던 레인 워커
            if item is None:
                q.task_done()
                return
            try:
                work(*item)
            except Exception as ex:
                _thread_error(stage, item[0], ex)
                with _flow_lock:
                    if rows[item[0]]["s3_key"] in completed:
                        continue  # 성공 뒤 관찰·정리 오류는 문서 실패가 아님
                    cnt["thread_err"] += 1
                    failed_keys.add(rows[item[0]]["s3_key"])
                _safe(note_error, item[0], {"pub": "publish_failed", "struct": "load_failed"}[stage], rows[item[0]])
            finally:
                q.task_done()

    def _skip(seq, row):  # 받기가 뺀 문서(중복·DRM·암호) — 기록은 받기가 except_doc_info skip에 씀, 게시·gold 없음
        _safe(drop_original, seq, row)
        with _flow_lock:
            cnt["skipped"] += 1
            completed.add(row["s3_key"])
        _safe(drop_temp, seq)
        _safe(mark, seq, "done")

    def _publish(seq, row):
        result = _ran("publish", publish_one, seq)
        if result == PARSE_FAILED or not result:
            parse_failed = result == PARSE_FAILED
            with _flow_lock:
                cnt["parse_fail" if parse_failed else "pub_fail"] += 1
                failed_keys.add(row["s3_key"])
            if parse_failed:
                _safe(note_error, seq, "parse_failed", row, True)  # 게시가 이미 쓴 실패 이력은 중복 집계하지 않음
            else:
                _safe(note_error, seq, "publish_failed", row)
            _safe(drop_temp, seq)
            return
        _safe(drop_original, seq, row)  # 게시 성공 뒤에만
        _struct_q.put((seq, row, time.time()))
        _safe(depth, "struct_put")

    def _gold(seq, row, enq_t):
        rc = _ran("구조화", gold_one, seq, enq_t, failure=-1)
        ok = rc == 0
        with _flow_lock:  # 집계를 기록(mark — 디스크 가득이면 예외)보다 먼저
            cnt["ok" if ok else "gold_fail"] += 1
            (completed if ok else failed_keys).add(row["s3_key"])
            if ok:
                loaded.add(row["s3_key"])
            report = ok and cnt["ok"] % 5 == 0
        if not ok:
            if rc == 3:
                _safe(note_error, seq, "classify_failed", row, True)  # 적재가 쓴 이력은 유지, DLQ는 호스트만
            else:
                _safe(note_error, seq, "load_failed", row)
        _safe(drop_temp, seq)
        _safe(mark, seq, "done")
        if report:  # psql(최대 60초)은 잠금 밖에서 — 레인·받기 워커를 막지 않게
            nd, nc = pg_count()
            log(f"PG 누적: doc={nd} chunk={nc}")

    # ponytail: 게시 스레드 1개 — 업로드는 파싱·구조화보다 훨씬 짧음, 밀리면 설정 칸(설정 모델 — 핑거프린트 파일)으로
    queue_threads = [threading.Thread(target=_queue_loop, args=(_pub_q, "pub", _publish), daemon=True, name="publish")]
    for _ in range(max(1, STRUCT_WORKERS)):
        queue_threads.append(threading.Thread(target=_queue_loop, args=(_struct_q, "struct", _gold), daemon=True, name=f"structure-{_}"))
    for thread in queue_threads:
        thread.start()

    def _one(doc_seq, row_doc):
        res = _ran("파싱", parse_one, doc_seq, row_doc)
        if res == SKIP:  # 실패 아님 — 다음 밤에는 대상 목록이 except_doc_info skip 키로 뺌
            _skip(doc_seq, row_doc)
        elif res:
            _pub_q.put((doc_seq, row_doc))
            _safe(depth, "pub_put")
        else:
            with _flow_lock:
                cnt["parse_fail"] += 1
                failed_keys.add(row_doc["s3_key"])
            _safe(note_error, doc_seq, "parse_failed", row_doc)
            _safe(drop_temp, doc_seq)  # 원본(staging)은 남김

    # ── 레인 워커(규칙: rn-01·rn-02): 레인마다 전담(자기 레인만)·공유(자기 레인 먼저, 비면 가장 긴 다른 레인 — pick_lane).
    # 구조화 대기가 STRUCT_BACKLOG 이상이면 새 파싱을 시작하지 않음. MCP 업로드 처리 중에는 medium 전담 워커가 쉼.
    def _flow_done():
        with _flow_lock:
            return (
                _picked_all.is_set()
                and not _fetching
                and all(not q for q in LANEQ.values())
                and all(v == 0 for v in _lane_inflight.values())
            )

    def lane_worker(own, shared):
        while not _stop.is_set():
            seq = None
            with _flow_lock:
                hold = (own == "medium" and not shared and _mcp_pause) or (STRUCT_BACKLOG and _waiting() >= STRUCT_BACKLOG)
                c = None if hold else pick_lane(own, shared, LANEQ, _lane_inflight, VLM_CAP)
                if c is None:
                    if _flow_done():
                        return
                    _flow_lock.wait(5)
                    continue
                seq = LANEQ[c].popleft()
                _lane_inflight[c] += 1
                depth("pick")
                _flow_lock.notify_all()  # 파싱 1개 시작 → 받기 보충 신호
            try:
                _one(seq, rows[seq])
            except Exception as ex:  # 예외 처리·기록 중 예외도 레인을 죽이지 않게 — 죽으면 큐가 안 비어 _flow_done() 대기가 안 끝남
                _thread_error("파싱", seq, ex)
                with _flow_lock:
                    if rows[seq]["s3_key"] in completed:
                        continue  # 영구 뺌·성공 뒤 오류는 경고만
                    cnt["thread_err"] += 1
                    failed_keys.add(rows[seq]["s3_key"])
                _safe(note_error, seq, "parse_failed", rows[seq])
            finally:
                with _flow_lock:
                    _lane_inflight[c] -= 1
                    _flow_lock.notify_all()  # 슬롯 반납 → 받기 보충 신호
                depth("parse_end")

    _mcp_pause_monitor_once()
    monitor = threading.Thread(target=_mcp_pause_monitor, daemon=True, name="mcp-watch")
    monitor.start()  # MCP 업로드 감시(medium 전담 워커 쉼)

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

    _pub_q.put(None)  # 파싱 전부 끝 → 게시 끝 → 구조화 끝(센티널 차례로)
    _pub_q.join()
    for _ in range(max(1, STRUCT_WORKERS)):
        _struct_q.put(None)
    _struct_q.join()
    _stop.set()
    with _flow_lock:
        _flow_lock.notify_all()
    tf.join(timeout=5)
    monitor.join(timeout=5)
    for thread in queue_threads:
        thread.join(timeout=30)
    alive = [thread.name for thread in [*lane_threads, tf, monitor, *queue_threads] if thread.is_alive()]
    if alive:
        log(f"[중단] 종료 대기 시간 초과 — 남은 스레드: {', '.join(alive)}")
    cnt["thread_err"] += _STAGE_ERR[0]
    failed_keys.update(rows[i]["s3_key"] for i in _STAGE_FAILED)
    cnt.update(completed=completed, loaded=loaded, failed_keys=failed_keys, deadline=_deadline_hit.is_set(), stuck=bool(alive))
    failed = len(failed_keys)
    log(
        f"=== flow 끝: 완료 {cnt['ok']} · 건너뜀 {cnt['skipped']} · 실패 {failed} "
        f"(파싱 {cnt['parse_fail']} · 게시 {cnt['pub_fail']} · gold {cnt['gold_fail']} · 스레드 예외 {cnt['thread_err']}) · "
        f"{(time.time() - t_all) / 60:.1f}분 ==="
    )
    return cnt


def main():
    global STAGING_TARGET, STRUCT_WORKERS, NO_CLEANUP, STRUCT_BACKLOG, CODE_DIR, DEADLINE_AT, _LOCK
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-offset", type=int, default=0, help="목록에서 시작할 자리(기본 0 = 처음부터)")
    ap.add_argument(
        "--staging",
        type=int,
        default=None,
        help="진입 대기열(미리 받을 문서 수) — 기본 settings.yaml ops.run_pipeline.staging.staging_max_docs(20)",
    )
    ap.add_argument(
        "--struct-workers",
        type=int,
        default=None,
        help="구조화 스레드 수 — 기본 settings.yaml ops.run_pipeline.structure.structure_workers(2)",
    )
    ap.add_argument("--filter", default="", help="원본 파일 이름 키워드(쉼표 — 하나라도 들면)로 좁힘 — 기본 모든 문서")
    ap.add_argument(
        "--limit", type=int, default=None, help="이 개수만 처리 — 기본 settings.yaml ops.run_pipeline.run_limit(2), 0 = 전체(새벽 배치)"
    )
    ap.add_argument("--max-docs", type=int, default=0, help="새벽 배치 — 끝난 문서를 뺀 뒤 앞에서 이 개수만(0 = 상한 없음, 사용자 11-02)")
    ap.add_argument("--deadline", default="", help="새벽 배치 마감(HH:MM) — 지나면 새 문서를 받기 시작하지 않음(사용자 11-02)")
    ap.add_argument("--seqs", default="", help="임의 문서 집합(쉼표 seq 목록) — 지정 시 연속 범위 대신 이 목록만 처리")
    ap.add_argument(
        "--cpu-gate",
        type=float,
        default=None,
        help="파이프라인 CPU 게이트(CPU_MAX_LOAD) — 기본 settings.yaml ops.run_pipeline.parse.batch_max_cpu_load",
    )
    ap.add_argument(
        "--skip-done",
        action="store_true",
        help="gold에 이미 끝난(doc 행이 있는) 문서와 영구 뺌(except_doc_info skip) 문서는 건너뜀(재실행 시간 절약)",
    )
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--settings", default=None, help="서버 settings.yaml(기본 SETTINGS_FILE 또는 <루트>/settings.yaml — op-13)")
    ap.add_argument(
        "--code",
        default=None,
        help="코드 폴더(설정 배치 모듈·이미지 경로 표를 찾음 — 기본: 이 스크립트가 든 코드 폴더 · op-10, 기본 배치 경로 없음 — 사용자 11-02)",
    )
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="이름=값",
        help="ops.run_pipeline 칸 한 번 덮기 — 이름은 RUN_PIPELINE_<칸>(예 RUN_PIPELINE_STEPS_VERIFY=false · RUN_PIPELINE_RUN_LIMIT=5)",
    )
    a = ap.parse_args()
    if not re.fullmatch(r"[\w,.\-]*", a.filter) or not re.fullmatch(r"[0-9,]*", a.seqs):  # 컨테이너 명령 줄에 그대로 들어감
        print("[중단] --filter는 글자·숫자·_ , . -만(띄어쓰기 없음), --seqs는 숫자와 쉼표만", flush=True)
        raise SystemExit(2)
    CODE_DIR = Path(a.code) if a.code else None
    bad = configure(a.settings, a.set)
    if bad:
        for msg in bad:
            print(f"[중단] {msg}", flush=True)
        print("[판정] 실패 — 설정 · 종료 코드 2", flush=True)  # 설정을 못 읽어 progress.log 자리도 모름 — 화면에만
        raise SystemExit(2)
    if a.limit is None:
        a.limit = POLICY["run_limit"]
    NO_CLEANUP = a.no_cleanup
    if a.cpu_gate is not None:
        POLICY["cpu_gate"] = a.cpu_gate
    DEADLINE_AT = deadline_at(a.deadline) if a.deadline else None
    if a.staging is not None:
        STAGING_TARGET = a.staging
    if a.struct_workers is not None:
        STRUCT_WORKERS = a.struct_workers
    STRUCT_BACKLOG = _BACKLOG_SETTING if _BACKLOG_SETTING is not None else 2 * max(1, STRUCT_WORKERS)

    PROG.mkdir(parents=True, exist_ok=True)
    _LOCK = take_lock(PROG / "run_pipeline.lock")
    if _LOCK is None:
        return verdict(EXIT_DEADLINE, f"다른 run_pipeline이 도는 중({PROG / 'run_pipeline.lock'}) — 다음 실행에서 다시")
    if not MCP_JOBS_DIR.is_dir():
        log(f"[안내] MCP 업로드 작업 폴더 {MCP_JOBS_DIR} 없음 — MCP 업로드 감지(medium 레인 양보) 꺼짐")
    os.umask(0)  # 컨테이너( uid 10001 rag )가 /app/output(=_docflow/<seq>)에 쓰려면 777 필요
    STAGING.mkdir(mode=0o777, parents=True, exist_ok=True)
    DOCFLOW.mkdir(mode=0o777, parents=True, exist_ok=True)
    stack_check()
    t_all = time.time()
    if POLICY["steps_precheck"]:
        bad_check = precheck()
        if bad_check:
            return verdict(EXIT_CHECK, f"① 사전 점검 {bad_check}")
    before = dlq_state()
    if before is None:
        log("[DLQ] 상태 못 읽음 — 단계별 결과로 진행(applog 판 0005·접속 확인)")
    else:
        log(
            f"[DLQ] 시작: pending {sum(r['status'] == 'pending' for r in before.values())}건 · dead {sum(r['status'] == 'dead' for r in before.values())}건"
        )
    picked = pick_targets(a)
    if picked is None:
        return verdict(EXIT_FAIL, "② 문서 처리 — 대상 목록")
    rows, order, total, start = picked
    log(
        f"=== 문서별 flow 시작: offset={start} · 남은 {total - start}건 · 레인(전담/공유) "
        f"{' '.join(f'{c} {d}/{s}' for c, (d, s) in LANE_WORKERS.items())} · vlm 동시 {VLM_CAP} · "
        f"staging {STAGING_TARGET} · 구조화 {STRUCT_WORKERS}동시(대기 상한 {STRUCT_BACKLOG or '없음'}) · {'제한 ' + str(a.limit) + '건' if a.limit else '제한 없음'} ==="
    )
    if not order:
        log("처리할 문서 없음 — 종료")
        return verdict(0, "대상 0건(③ 검색 확인 안 함)")
    t_main = time.time()
    main_flow = run_flow(rows, order)
    main_elapsed = time.time() - t_main
    failed = main_flow["failed_keys"] or main_flow["stuck"]
    rc = EXIT_FAIL if failed else (EXIT_DEADLINE if main_flow["deadline"] else 0)
    state = dlq_state() if before is not None else None
    if before is not None and state is None:
        log("[DLQ] 실행 뒤 상태 못 읽음 — 단계별 결과로 진행(applog 판 0005·접속 확인)")
    dlq_summary = "DLQ 상태 모름"
    if state is not None:
        dead = {k for k, r in state.items() if r["status"] == "dead"}
        new_dead = {k for k in dead if before.get(k, {}).get("status") != "dead" and k in main_flow["failed_keys"]}
        dlq_summary = f"DLQ pending {sum(r['status'] == 'pending' for r in state.values())}건 · dead {len(dead)}건(이번 실행 새로 {len(new_dead)}건) — 조회: python -m pipeline.shared.dlq list --status dead"
    nd, nc = pg_count()
    main_failed = sum(main_flow[k] for k in ("parse_fail", "pub_fail", "gold_fail", "thread_err"))
    main_done = main_flow["ok"] + main_flow["skipped"] + main_failed
    log(
        f"=== 문서별 flow 끝: {main_done}건(완료 {main_flow['ok']} · 건너뜀 {main_flow['skipped']} · "
        f"파싱실패 {main_flow['parse_fail']} · 게시실패 {main_flow['pub_fail']} · gold실패 {main_flow['gold_fail']} · "
        f"스레드 예외 {main_flow['thread_err']}) · 최종 실패 {len(main_flow['failed_keys'])} · "
        f"{dlq_summary} · "
        f"{(time.time() - t_all) / 60:.1f}분 · 문서당 평균 {main_elapsed / 60 / main_done if main_done else 0:.1f}분 · PG doc={nd} chunk={nc} · 종료 코드 {rc} ==="
    )
    return finish(rc, main_flow, rows, t_all)


def finish(rc, flow, rows, since=0.0):
    """② 뒤 끝 판정 — 실패 문서면 1(③ 안 함) · 적재 0건(마감·모두 건너뜀)이면 rc 그대로(③ 안 함) · ③ 실패면 3 · 그 밖은 rc 그대로."""
    if rc == EXIT_FAIL:
        return verdict(rc, f"② 문서 처리 — 실패 {len(flow['failed_keys'])}건")
    if not flow["loaded"]:  # 마감에 걸렸거나 모두 건너뜀(중복·DRM·암호 — pl-24) — 실패 아님, 확인할 문서 없음
        return verdict(rc, ("마감 도달" if rc == EXIT_DEADLINE else "모두 건너뜀") + "(적재 0건 — ③ 안 함)")
    if POLICY["steps_verify"]:
        bad_check = verify(rows, flow["loaded"], since)
        if bad_check:
            return verdict(EXIT_CHECK, f"③ 적재·검색 확인 {bad_check}")
    return verdict(rc, "마감 도달" if rc == EXIT_DEADLINE else "")


if __name__ == "__main__":
    sys.exit(main())
