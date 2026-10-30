#!/usr/bin/env python3
"""텍스트 파싱 작업 서비스 — data-pipeline-parse 컨테이너(S6b — 옛 data-parsing) 안에서 상주하며 검색 MCP(mcp-server — 옛 data-retrieval)의 parse_document
도구가 localhost HTTP로 호출한다(비정형 파일[base64] → text 파싱 대표 결과 반환).
범위 — prepare → run_all(문서의 엔진들 동시에 · VLM/OCR 엔진 제외) → parse_qa → represent까지.
구조화·임베딩·적재 없음 · 표 인식 유지 · 이미지/스캔 문서는 빈 결과(OCR·VLM 미실행).
[패치 2026-10-22] ① 기본 time_out_threshold 300초 ② 큐 대기 순번을 제출 응답과 시작 시점에 표시(지연 원인 파악)
  ③ 서비스 PID 로그 파일 남김(docker exec -d 로그 없음 문제) ④ _purge_old에서 방금 만든 작업 보호(버그 수정)
실행: docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service
  토큰은 설정 필수(컨테이너에 붙인 settings.yaml pipeline.service.parse_mcp.token — 검색 MCP의 MCP_TOKEN과 같은 값, 없으면 시작 거부, D-028 ⑨ · S7c ·
  S7e2부터 env PARSE_MCP_TOKEN은 읽지 않음 — `docker exec -e PARSE_MCP_TOKEN=…`은 효과 없음, VS7e2 R-6)
API(127.0.0.1:8766 · Bearer):  POST /jobs {content_b64+filename} → 202 {job_id, queue_position}
  GET /health  → {ok, ready, running, queued} · GET /jobs/<id> → {status, result, elapsed_ms}"""

import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common.config.settings import child_env as settings_env
from common.config.settings import reveal
from common.core import exitclean
from common.core.paths import APP_ROOT  # I4 — 컨테이너 경로(/app/…) 대신 런타임 루트 기준(이미지 안 값 같음)
from pipeline import config as pc

SERVICE_DIR = APP_ROOT / "output" / "mcp_parse"  # 이미지 안 /app/output/mcp_parse
_JOB_ENVS: dict = {}  # (PARSE_POST, 판 번호, SETTINGS_FILE) → 작업 자식 env에 얹을 몫(덮기 파일 SETTINGS_FILE + 엔진·인계 칸 — VS7e2 R-4)
_JOB_KEYS = (
    "SETTINGS_FILE",
    "PARSE_FUSE_REREAD_P3",
    "PARSE_POST",
)  # 얹을 몫에 늘 넣는 이름(VS8a R-5) — STACK_VERSION은 env가 아니라 덮기 파일로만 감(VS8b R-8)


def _job_stack():
    """작업마다 엔진 구성 활성 판을 다시 읽어 그 판 번호를(S8b — 사용자 10-28 Q3 a · pl-32 사본 파일 없음 — PC 파일이면 None). 판 표를 못
    읽거나(종료 4) 없는 엔진이면(종료 2) 그 작업만 실패(서비스 스레드는 계속)."""
    from pipeline import stackcfg

    try:
        return stackcfg.resolve(refresh=True, publish=False).version_id
    except SystemExit as e:
        raise RuntimeError(f"엔진 구성(판 표)을 쓰지 못함 — 종료 코드 {e.code}") from None


def _job_env(post, stack=None):
    """작업 자식 env — 덮기 파일(PARSE_FUSE_REREAD_P3=0·PARSE_POST)을 서비스 설정 파일·후보정 값마다 한 번만 만든다(임시 파일이 작업 수만큼
    쌓이지 않게 — refactor.md C-46). 만든 파일은 서비스가 끝날 때 지운다(pl-27 — child_env가 exitclean에 맡김). OS 임시 폴더 정리(tmpwatch·systemd-tmpfiles·macOS periodic)가 오래 도는 서비스의 그 파일을 지웠으면
    다시 만든다(리뷰 S7e3 — 지워진 파일을 가리키면 서버 자식은 시작 거부, PC는 기본 후보정 all로 돎). 캐시는 덮기 파일이 얹는 몫만 — env는
    작업마다 지금 os.environ에서 새로 만든다(VS7e3 R-6 — 오래 도는 서비스의 라이브러리 env가 바뀌어도 작업 자식에 감). 반환은 새 dict."""
    key = (post, str(stack), os.environ.get("SETTINGS_FILE"))  # env 남김 — 설정 파일 자리 신호
    extra = _JOB_ENVS.get(key)
    if extra is None or not Path(extra["SETTINGS_FILE"]).is_file():
        pm = pc.cfg().service.parse_mcp
        # 10-29 — 파이프라인과 같은 규칙(쪽당 제한 + 두 배로 한 번 더)을 서비스 값으로 · 첫 시도 하한은 서비스 칸 warmup_sec(작업마다 새 run_all이라
        # 늘 '첫 문서' — 파이프라인 warmup 60초면 쪽당 제한이 무의미, 콜드 시작 여유는 이 칸) · 엔진 자식은 보통 우선순위(일괄 파싱보다 CPU 먼저)
        made = settings_env(
            PARSE_FUSE_REREAD_P3="0",
            PARSE_POST=post,
            PARSE_TEXT_PAGE_SEC=str(pm.text_page_sec),
            PARSE_VLM_PAGE_SEC=str(pm.vlm_page_sec),
            PARSE_WARMUP_SEC=str(pm.warmup_sec),
            PARSE_LOW_PRIORITY="0",
            **({"STACK_VERSION": str(stack)} if stack is not None else {}),
        )
        # 덮기 파일이 얹은 몫만 — 넘긴 칸(SETTINGS_FILE·영구 다리로 env에 든 칸)은 지금 env와 같아도 늘 넣음(뒤에 env가 바뀌어도 자식 env와
        # 덮기 파일이 어긋나지 않게 — VS8a R-5)
        extra = _JOB_ENVS[key] = {k: v for k, v in made.items() if k in _JOB_KEYS or os.environ.get(k) != v}  # env 남김 — 하위 프로세스
    return {**os.environ, **extra}  # env 남김 — 하위 프로세스


_PM = pc.cfg().service.parse_mcp  # S7c — 설정 객체(모듈 상수 — 옛처럼 import 때 한 번)
pc.checked("PARSE_MCP_PORT")  # 형식 틀린 포트는 옛처럼 import 때 실패(조용히 기본 포트로 뜨지 않게 — VS7c1 R-2, 사용자 10-27)
PORT = _PM.port
_TOK = reveal(_PM.token) or ""
TOKEN = _TOK if _TOK.strip() else None  # D-028 ⑨ — 코드 기본 토큰 삭제, 설정 필수(없거나 비거나 공백만이면 아래 __main__이 시작 거부 — R-2)
PROCS = str(
    max(1, _PM.procs if _PM.procs is not None else min(3, (os.cpu_count() or 2) - 1))
)  # 엔진 묶음 병렬(2026-10-21) — 30쪽 PDF 순차 시 120초+ 걸리던 것 대폭 단축
ROOTS = [Path(p).resolve() for p in (_PM.roots or [str(SERVICE_DIR / "inbox")])]  # 쉼표 목록은 객체가 strip·빈 것 버림
MAX_MB = _PM.max_mb
JOB_TIMEOUT = _PM.job_timeout_sec
QUEUE_MAX = _PM.queue_max
JOBS_DIR = Path(_PM.jobs_dir or SERVICE_DIR / "jobs")
ALLOWED_EXTS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".hwpx",
    ".txt",
    ".html",
    ".htm",
    ".mht",
    ".mhtml",
    ".eml",
    ".msg",
}  # 이미지 파일(p·jpg 등)은 "이미지 파싱은 수행 안하고 꺼줘" 요구사항에 따라 원천 거부
MAX_JOBS_KEPT = 30
_lock = threading.Lock()
JOBS: dict = {}
Q: queue.Queue = queue.Queue()


def _log(msg):
    print(f"[parse-mcp {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _jail(path_str):
    """허용 루트 하위 경로만 — 벗어나면 ValueError(디렉터리 탈출·시스템 파일 차단)."""
    p = Path(path_str).resolve()
    if not any(str(p).startswith(str(r) + "/") or str(p).startswith(str(r) + os.sep) or p == r for r in ROOTS):
        raise ValueError(f"허용 경로 아님({', '.join(str(r) for r in ROOTS)} 하위만)")
    if not p.is_file():
        raise ValueError(f"파일 없음: {path_str}")
    return p


def _run_group(cmd, timeout, env):
    """작업 단계 하나(python -m …) — 새 프로세스 묶음으로 띄우고 시간 초과면 묶음째 끝냄(run_all이 띄운 parse_one 손자가 남지 않게,
    cli._run_until과 같은 규칙 — pipeline.extract.resources). 시간 초과는 subprocess.TimeoutExpired로 올림(옛 subprocess.run과 같음)."""
    from pipeline.extract import resources as PR

    p = exitclean.track(  # pl-27 — 서비스가 끝날 때 아직 돌면 묶음째 끝내고 회수
        subprocess.Popen(
            ["python", "-m", *cmd], cwd=APP_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, **PR.group_kw()
        ),
        group=True,
    )
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        PR.kill_group(p)
        raise
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def _engines_no_ocr_arg():
    """run_all에 붙일 --engines 인자(2026-10-21 사용자: 이미지 비대상 — OCR 꺼짐 기본).
    CORE에서 이미지·스캔 전용(rapidocr_ko·qwen_vlm)을 빼고 설치된 것만. pipeline.extract.ocr_engine(PARSE_OCR_ENGINE — 10-29에
    옛 PARSE_MCP_OCR를 합침)이 켜지면 비워 run_all 기본(CORE 전체 — OCR·VLM 엔진 포함)으로 돌아간다. 스캔 이미지 PDF는 글자층 엔진만 시도되어
    텍스트가 안 나오면 빠르게 실패한다(수 분 OCR로 큐를 막던 원인 제거 — 실측 10-21)."""
    if pc.cfg().extract.ocr_engine:  # 10-29 — 파이프라인과 같은 OCR 스위치
        return []
    try:
        from pipeline.extract.engines import registry

        ocr = {"rapidocr_ko", "qwen_vlm"}
        picked = [e for e in sorted(registry.CORE - ocr) if registry.installed(e)]
        return ["--engines", ",".join(picked)] if picked else []
    except Exception as e:
        _log(f"엔진 목록 산정 실패({type(e).__name__}: {e}) — OCR 제외 없이 run_all 기본으로")
        return []


_ENGINES_NO_OCR = _engines_no_ocr_arg


def _pdf_text_chars(raw=None, p=None):
    """글자층 샀플(pypdf, 첫 5쪽) — 2026-10-21 사용자: 스캔/이미지 문서도 거부하지 않고 OCR·VLM 없이 그 결과를
    그대로(≈빈) 돌려준다. 이 값은 두 곳에만 쓴다: ① 글자층이 사실상 없는 PDF(<20자)는 OCR 가능성이 있는
    엔진(kreuzberg 폴백 포함)까지 빼고 글자층 추출 전용(pymupdf·pdfplumber·pypdf)만 돈다(시간 보장) ② 응답 note.
    판독 자체에 실패하면 -1(특별 취급 없음 — 파이프라인이 제대로 된 오류를 냄)."""
    try:
        import io

        from pypdf import PdfReader

        r = PdfReader(io.BytesIO(raw) if raw is not None else str(p))
        return len("".join((pg.extract_text() or "") for pg in r.pages[:5]).strip())
    except Exception:
        return -1


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}  # ALLOWED_EXTS에서 뺐으므로 도달 불가 — 참고용(전이해)


def _submit(source):
    """작업 등록 — source: {"path": 컨테이너 경로} 또는 {"content_b64": ..., "filename": ...}."""
    with _lock:
        running_or_queued = sum(1 for j in JOBS.values() if j["status"] in ("queued", "running"))
        if running_or_queued >= QUEUE_MAX:
            raise queue.Full
    path = source.get("path")
    b64 = source.get("content_b64")
    if b64:
        fname = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(source.get("filename") or ""))
        if not fname or fname.startswith("."):
            raise ValueError("content_b64와 함께 filename 필요")
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as e:
            raise ValueError(f"base64 디코딩 실패: {e}") from e
        if len(raw) > MAX_MB * 1024 * 1024:
            raise ValueError(f"파일이 상한({MAX_MB}MB)보다 큼")
    else:
        p = _jail(path)
        fname = p.name
    if Path(fname).suffix.lower() not in ALLOWED_EXTS:
        raise ValueError(f"지원하지 않는 확장자({Path(fname).suffix or '없음'}) — {sorted(ALLOWED_EXTS)}")
    job_id = time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:12]
    ws = JOBS_DIR / job_id
    (ws / "in").mkdir(parents=True, exist_ok=True)
    if b64:
        (ws / "in" / fname).write_bytes(raw)
        meta = {"filename": fname, "mode": "base64", "bytes": len(raw)}
    else:
        meta = {"filename": fname, "mode": "path", "bytes": p.stat().st_size, "path": str(p)}
    meta["pdf_text_chars"] = (
        _pdf_text_chars(raw=raw if b64 else None, p=p if not b64 else None) if Path(fname).suffix.lower() == ".pdf" else None
    )
    open(ws / "job.json", "w", encoding="utf-8").write(json.dumps({"job_id": job_id, **meta}, ensure_ascii=False))
    with _lock:
        JOBS[job_id] = {"job_id": job_id, **meta, "status": "queued", "submitted": time.time()}
    Q.put(job_id)
    _purge_old(keep_job_id=job_id)
    with _lock:
        # 대기 순번 — 자신 제외한 앞의 작업 수(경합으로 자신이 이미 running이 됐으면 0)
        ahead = max(0, sum(1 for j in JOBS.values() if j["status"] in ("queued", "running")) - 1)
        _log(f"제출 {job_id} · 파일: {fname:40s} {meta.get('bytes', 0)}B · 대기 {ahead}건")
    return job_id, ahead


def _purge_old(keep_job_id=None):
    """오래된 작업 폴더 정리(최근 MAX_JOBS_KEPT개만 보관 — 디스크 방치 방지).
    keep_job_id(2026-10-21 버그 수정): _submit이 방금 만든 작업은 이름(UUID) 정렬 위치에 무관하게
    절대 지우지 않는다 — 원인: 이름 정렬이 무작위(UUID)라 새 작업이 done[:-N]에 걸려 현장에서 사라졌음."""
    try:
        import shutil

        done = sorted([p for p in JOBS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name)
        victim = done[:-MAX_JOBS_KEPT] if len(done) > MAX_JOBS_KEPT else []
        for p in victim:
            if p.name != keep_job_id:
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _worker():
    """작업자 스레드(서버당 1개 — 트리거 서버와 같은 패턴): 큐에서 꺼내 파싱 파이프라인 실행.
    2026-10-22 패치: 픽업 시각·큐 대기시간을 기록(txt 3분 대기 이슈 — '파싱 자체는 1초, 접수→픽업이 3분' 원인 추적용)."""
    while True:
        job_id = Q.get()
        j = JOBS.get(job_id)
        if j is None:
            continue
        j["picked_at"] = time.time()
        j["queue_wait_s"] = round(j["picked_at"] - j.get("submitted", j["picked_at"]), 1)
        if j["queue_wait_s"] > 5:
            _log(f"{job_id} 픽업 · 큐 대기 {j['queue_wait_s']}초(앞 작업이 오래 걸린 것 — 파싱 자체 지연 아님)")
        j["status"], t0 = "running", time.time()
        ws = JOBS_DIR / job_id
        try:
            fname = j["filename"]
            (ws / "in").mkdir(parents=True, exist_ok=True)
            if j.get("mode") == "path":  # 허용 루트의 원본을 작업 폴더로 복사(버그 수정 2026-10-21 — 복사가 없어 파싱 대상이 비어 실패)
                import shutil

                shutil.copy2(Path(j["path"]), ws / "in" / fname)
            if Path(fname).suffix.lower() in _IMAGE_EXTS:  # 2026-10-21 사용자: 이미지 문서 — OCR·VLM 미실행, 파이프라인 없이 빈 결과 즉시
                j["result"] = {
                    "job_id": job_id,
                    "filename": fname,
                    "status": "done",
                    "engine": None,
                    "text": "",
                    "tables_std": [],
                    "tables": [],
                    "facts": [],
                    "fields": {},
                    "rep_path": None,
                    "all_keys": [],
                    "note": "이미지 문서 — text 파싱 결과 없음(OCR·VLM 기본 미실행 · 재가능: pipeline.extract.ocr_engine 켬)",
                }
                j["status"] = "done"
            else:
                engines = _ENGINES_NO_OCR()
                if Path(fname).suffix.lower() == ".pdf" and 0 <= (j.get("pdf_text_chars") or -1) < 20:
                    engines = ["--engines", "pymupdf,pdfplumber,pypdf"]
                only = ws / "only.txt"
                only.write_text(fname + "\n", encoding="utf-8")
                log = open(ws / "run.log", "w", encoding="utf-8")
                left = JOB_TIMEOUT
                post = pc.cfg().transform.represent.post  # S7c — 옛 get(X) or "supsub"(없음·빈 값 → supsub)
                stack = (
                    _job_stack()
                )  # S8b·pl-32 — 작업마다 활성 판 번호(run_all·attachments는 STACK_VERSION 칸, represent는 --stack-version)
                job_env = _job_env(post or "supsub", stack)  # 하위 프로세스 — 덮기 파일(S7e2), 같은 값이면 한 번 만든 것 재사용(VS7e2 R-4)
                # 2026-10-22 병목 해소: post 기본 all→supsub — RapidOCR·figures·vlm_page·context·attachments를 끔
                # 교차재현율(③)·table_inline(⑦)은 0.0초로 병목이 아니었으므로 그대로 유지 — 실측 47→~0.3초
                _run = lambda cmd: _run_group(cmd, left, job_env)  # noqa: B023 — 같은 반복 안에서만 부름

                # ① prepare → run_all
                for cmd in (
                    ["pipeline.extract.prepare", "--src", str(ws / "in"), "--out", str(ws / "prep"), "--only", str(only)],
                    [
                        "pipeline.extract.run_all",
                        "--src",
                        str(ws / "prep"),
                        "--out",
                        str(ws / "parse"),
                        "--limit",
                        "1",
                        "--procs",
                        PROCS,
                        *engines,
                    ],
                ):
                    p = _run(cmd)
                    log.write(f"== {' '.join(cmd)}\n{p.stdout}\n{p.stderr}\n")
                    log.flush()
                    if p.returncode != 0:
                        raise RuntimeError(f"단계 실패({cmd[0]}): {(p.stdout + p.stderr).strip().splitlines()[-1:] or ['?']}")

                # ② 엔진 전부 실패(DRM/암호화)? → runs.jsonl 부재 → 빈 결과
                runs_file = ws / "parse" / "runs.jsonl"
                if not runs_file.exists():
                    _log(f"{job_id} · 엔진 전부 실패 → 빈 결과(DRM 추정)")
                    j["result"] = {
                        "job_id": job_id,
                        "filename": fname,
                        "status": "done",
                        "engine": None,
                        "text": "",
                        "tables_std": [],
                        "tables": [],
                        "facts": [],
                        "fields": {},
                        "rep_path": None,
                        "all_keys": [],
                        "note": "텍스트 추출 실패 — DRM/암호화 문서일 가능성(엔진 전부 파싱 실패)",
                        "ms": round((time.time() - t0) * 1000, 1),
                    }
                else:
                    # ③ parse_qa → represent
                    for cmd in (
                        [
                            "pipeline.transform.represent.parse_qa",
                            "--src",
                            str(ws / "prep"),
                            "--parse",
                            str(ws / "parse"),
                            "--truth",
                            str(ws / "truth.json"),
                        ],
                        [
                            "pipeline.transform.represent.represent",
                            *([] if stack is None else ["--stack-version", str(stack)]),
                            "--src",
                            str(ws / "prep"),
                            "--parse-dir",
                            str(ws / "parse"),
                        ],
                    ):
                        p = _run(cmd)
                        log.write(f"== {' '.join(cmd)}\n{p.stdout}\n{p.stderr}\n")
                        log.flush()
                        if p.returncode != 0:
                            raise RuntimeError(f"단계 실패({cmd[0]}): {(p.stdout + p.stderr).strip().splitlines()[-1:] or ['?']}")

                    # ④ 대표 결과 파일 확인 → 정상 반환 or 빈 결과
                    rep_path = ws / "parse" / "_rep" / (fname + ".json")
                    if not rep_path.exists():
                        j["result"] = {
                            "job_id": job_id,
                            "filename": fname,
                            "status": "done",
                            "engine": None,
                            "text": "",
                            "tables_std": [],
                            "tables": [],
                            "facts": [],
                            "fields": {},
                            "rep_path": None,
                            "all_keys": [],
                            "note": "텍스트 추출 결과 없음 — DRM/암호화 문서일 가능성",
                            "ms": round((time.time() - t0) * 1000, 1),
                        }
                    else:
                        rep = json.loads(rep_path.read_text(encoding="utf-8"))
                        j["result"] = {
                            "job_id": job_id,
                            "filename": fname,
                            "rep_path": str(rep_path),
                            "workspace": str(ws),
                            "engine": (rep.get("rep") or {}).get("engine"),
                            "text": rep.get("text"),
                            "tables_std": rep.get("tables_std"),
                            "tables": rep.get("tables"),
                            "facts": rep.get("facts"),
                            "fields": rep.get("fields"),
                            "rep": rep.get("rep"),
                            "provenance": rep.get("provenance"),
                            "all_keys": sorted(rep.keys()),
                            "ms": round((time.time() - t0) * 1000, 1),
                        }
                j["status"] = "done"
        except Exception as e:
            j["status"] = "failed"
            j["error"] = f"{type(e).__name__}: {e}"
        finally:
            j["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        _log(f"{job_id} → {j['status']} ({j.get('elapsed_ms')}ms)")


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return TOKEN and self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        if self.path == "/health":
            with _lock:
                r = {
                    "running": sum(1 for j in JOBS.values() if j["status"] == "running"),
                    "queued": sum(1 for j in JOBS.values() if j["status"] == "queued"),
                }
            return self._json(200, {"ok": True, "ready": True, **r})
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        if self.path.startswith("/jobs/"):
            j = JOBS.get(self.path[len("/jobs/") :])
            if not j:
                return self._json(404, {"error": "job 없음"})
            with _lock:
                out = {
                    k: v
                    for k, v in j.items()
                    if k in ("job_id", "filename", "status", "error", "result", "elapsed_ms", "mode", "bytes", "path", "queue_wait_s")
                }
            return self._json(200, out)
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {"error": "unauthorized"})
        if self.path != "/jobs":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_MB * 1024 * 1024 + 65536:
                raise ValueError("본문 크기 상한 초과")
            source = json.loads(self.rfile.read(n) or b"{}")
            job_id, ahead = _submit(source)
            return self._json(202, {"job_id": job_id, "queue_position": ahead})
        except queue.Full:
            return self._json(429, {"error": "작업 대기열 가득 — 잠시 뒤 재시도"})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    from common.config.settings import require_run_env

    require_run_env(
        "mcp_parse_service", sections=("pipeline",)
    )  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    if not TOKEN:  # D-028 ⑨(S7c) — 옛 코드 기본 토큰 없앰: 설정에 없으면 시작 거부(값은 찍지 않음)
        print(
            "[설정] mcp_parse_service: 토큰 없음 — settings.yaml pipeline.service.parse_mcp.token(PARSE_MCP_TOKEN)에 검색 MCP의 MCP_TOKEN과 "
            "같은 값을 적음(env로 준 값은 읽지 않음 — S7e2 · 코드 기본 토큰은 없앰 — refactor.md C-42)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)  # service.json 자리 — ROOTS·JOBS_DIR를 env로 다른 곳에 둬도
    from pipeline import stackcfg

    stackcfg.resolve(publish=False)  # S8b(Q7) — 서버에서 판 표를 못 읽으면 시작 거부(종료 4), 없는 엔진이면 종료 2
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for r in ROOTS:
        Path(r).mkdir(parents=True, exist_ok=True)
    # 2026-10-22 패치: docker exec -d 기동이라 표준출력이 안 남는다 → PID·환경을 파일로 남긴다(지연 원인 추적용 — txt 3분 대기 이슈)
    svc = exitclean.remove_at_exit(SERVICE_DIR / "service.json")  # pl-27 — PID 기록은 서비스가 끝나면 지움
    with open(svc, "w", encoding="utf-8") as f:
        json.dump(
            {
                "pid": os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "procs": PROCS,
                "max_mb": MAX_MB,
                "job_timeout": JOB_TIMEOUT,
                "queue_max": QUEUE_MAX,
            },
            f,
            indent=2,
        )
    threading.Thread(target=_worker, daemon=True).start()
    _log(f"준비 — http://127.0.0.1:{PORT}/health · roots={[str(r) for r in ROOTS]} · jobs={JOBS_DIR} · pid={os.getpid()}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
