#!/usr/bin/env python3
"""텍스트 파싱 작업 서비스 — mcp-data-parsing 컨테이너의 주 프로세스(compose.data-parsing.yml — 죽으면 restart가 다시 띄움).
검색 MCP(mcp-server)의 parse_document 도구가 localhost HTTP로 부른다(비정형 파일 → 텍스트 파싱 대표 결과).
범위 — 준비 → parse_engines(문서의 엔진들 동시에) → 채점 → 대표 결과까지. 구조화·임베딩·적재 없음 · 이미지 파일은 받지 않음 ·
스캔 PDF는 내부망 VLM(qwen_vlm). 토큰은 settings.yaml required.tokens.mcp_token(검색 MCP와 같은 칸, 없으면 시작 거부).
API(127.0.0.1:8766 · Bearer):  POST /jobs {content_b64+filename | path} → 202 {job_id, queue_position}
  GET /health  → {ok, ready, running, queued} · GET /jobs/<id> → {status, result, elapsed_ms}"""

import base64
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common.config.settings import cfg as common_cfg
from common.config.settings import checked, reveal
from common.config.settings import child_env as settings_env
from common.core import exitclean, parse_limit
from common.core.paths import APP_ROOT
from pipeline import config as pc
from pipeline import parse_steps
from pipeline.transform.parse.engine_check import allowed_exts

SERVICE_DIR = APP_ROOT / "output" / "_mcp_parse"  # 이미지 안 /app/output/_mcp_parse(op-13 — 임시 자리는 _ 접두)
_JOB_ENVS: dict = {}  # (PARSE_POST, SETTINGS_FILE) → 작업 자식 env에 얹을 몫(덮기 파일 SETTINGS_FILE + 엔진·인계 칸 — VS7e2 R-4)
_JOB_KEYS = (
    "SETTINGS_FILE",
    "PARSE_POST",
)  # 얹을 몫에 늘 넣는 이름(VS8a R-5)


def _job_env(post):
    """작업 자식 env — 덮기 파일(PARSE_POST 등)을 서비스 설정 파일·후보정 값마다 한 번만 만든다(임시 파일이 작업 수만큼
    쌓이지 않게 — refactor.md C-46). 만든 파일은 서비스가 끝날 때 지운다(pl-27 — child_env가 exitclean에 맡김). OS 임시 폴더 정리(tmpwatch·systemd-tmpfiles·macOS periodic)가 오래 도는 서비스의 그 파일을 지웠으면
    다시 만든다(리뷰 S7e3 — 지워진 파일을 가리키면 서버 자식은 시작 거부, PC는 기본 후보정 all로 돎). 캐시는 덮기 파일이 얹는 몫만 — env는
    작업마다 지금 os.environ에서 새로 만든다(VS7e3 R-6 — 오래 도는 서비스의 라이브러리 env가 바뀌어도 작업 자식에 감). 반환은 새 dict."""
    key = (post, os.environ.get("SETTINGS_FILE"))  # env 남김 — 설정 파일 자리 신호
    extra = _JOB_ENVS.get(key)
    if extra is None or not Path(extra["SETTINGS_FILE"]).is_file():
        pm = pc.cfg().service.data_parsing
        # 10-29 — 파이프라인과 같은 규칙(쪽당 제한 + 두 배로 한 번 더)을 서비스 값으로 · 첫 시도 하한은 서비스 칸 warmup_sec(작업마다 새 run_all이라
        # 늘 '첫 문서' — 파이프라인 warmup 60초면 쪽당 제한이 무의미, 콜드 시작 여유는 이 칸) · 엔진 자식은 보통 우선순위(일괄 파싱보다 CPU 먼저)
        made = settings_env(
            PARSE_POST=post,
            PARSE_TEXT_PAGE_SEC=str(pm.text_page_sec),
            PARSE_WARMUP_SEC=str(pm.warmup_sec),
            PARSE_LOW_PRIORITY="0",
        )
        # 덮기 파일이 얹은 몫만 — 넘긴 칸(SETTINGS_FILE·영구 다리로 env에 든 칸)은 지금 env와 같아도 늘 넣음(뒤에 env가 바뀌어도 자식 env와
        # 덮기 파일이 어긋나지 않게 — VS8a R-5)
        extra = _JOB_ENVS[key] = {k: v for k, v in made.items() if k in _JOB_KEYS or os.environ.get(k) != v}  # env 남김 — 하위 프로세스
    return {**os.environ, **extra}  # env 남김 — 하위 프로세스


_PM = pc.cfg().service.data_parsing  # S7c — 설정 객체(모듈 상수 — 옛처럼 import 때 한 번)
checked("DATA_PARSING_PORT")  # 형식 틀린 포트는 import 때 실패(조용히 기본 포트로 뜨지 않게)
PORT = common_cfg().runtime.data_parsing_port
_TOK = reveal(common_cfg().tokens.mcp) or ""
TOKEN = _TOK if _TOK.strip() else None  # D-028 ⑨ — 코드 기본 토큰 삭제, 설정 필수(없거나 비거나 공백만이면 아래 __main__이 시작 거부 — R-2)
PROCS = str(
    max(1, _PM.procs if _PM.procs is not None else min(3, (os.cpu_count() or 2) - 1))
)  # 엔진 묶음 병렬(2026-10-21) — 30쪽 PDF 순차 시 120초+ 걸리던 것 대폭 단축
ROOTS = [Path(p).resolve() for p in (_PM.roots or [str(SERVICE_DIR / "inbox")])]  # 쉼표 목록은 객체가 strip·빈 것 버림
JOB_TIMEOUT = _PM.job_timeout_sec
QUEUE_MAX = _PM.queue_max
JOBS_DIR = SERVICE_DIR / "jobs"  # 호스트 <결과 폴더>/_mcp_parse/jobs — run_pipeline.py가 같은 자리를 봄


MAX_JOBS_KEPT = 30
_lock = threading.Lock()
JOBS: dict = {}
Q: queue.Queue = queue.Queue()


def _log(msg):
    print(f"[data-parsing {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _jail(path_str):
    """허용 루트 하위 경로만 — 벗어나면 ValueError(디렉터리 탈출·시스템 파일 차단)."""
    p = Path(path_str).resolve()
    if not any(str(p).startswith(str(r) + "/") or str(p).startswith(str(r) + os.sep) or p == r for r in ROOTS):
        raise ValueError(f"허용 경로 아님({', '.join(str(r) for r in ROOTS)} 하위만)")
    if not p.is_file():
        raise ValueError(f"파일 없음: {path_str}")
    return p


def _is_scan(path):
    """스캔 PDF인지 — 엔진 고르기와 같은 판정(pdf_kind)이라 안내가 실제로 돈 엔진과 어긋나지 않는다."""
    from pipeline.shared.pdf_kind import pdf_kind

    return Path(path).suffix.lower() == ".pdf" and pdf_kind(path)[0] == "pdf_image"


# mc-18(사용자 11-03) — 스캔 PDF는 내부망 VLM(qwen_vlm — stack .pdf_image)으로 파싱한다. VLM 주소가 없으면 파이프라인 없이 빈 결과 + 안내,
#   VLM이 돌았는데 결과가 없으면 실패 안내(DRM 추정 아님). 글자층과 스캔 쪽이 섞인 PDF는 범위 밖(pl-03 10-29 결정 그대로).
VLM_UNSET_NOTE = "스캔 PDF — VLM 미설정"
VLM_FAIL_NOTE = "스캔 PDF — VLM 파싱 실패"
DRM_NOTE = "텍스트 추출 실패 — DRM/암호화 문서일 가능성(엔진 전부 파싱 실패)"
NO_REP_NOTE = "텍스트 추출 결과 없음 — DRM/암호화 문서일 가능성"


def skip_note(scan):
    """파이프라인 없이 바로 빈 결과로 끝낼 문서면 그 안내(VLM 설정 — qwen_vlm REQUIRES_ENV — 이 빈 스캔 PDF), 아니면 None.
    (이미지 확장자는 allowed_exts()에 없어 여기 오지 않음 — 11-01에 도달 불가 갈래 _IMAGE_EXTS·IMAGE_NOTE 지움.)"""
    from pipeline.transform.parse.engines import registry

    return VLM_UNSET_NOTE if scan and registry.missing_env("qwen_vlm") else None


def empty_note(scan, ran=False):
    """파이프라인이 대표 결과를 못 남겼을 때의 안내 — 스캔 PDF면 VLM 실패, 아니면 DRM 추정
    (ran=True: 엔진은 돌았는데 대표 결과가 없음 · False: 엔진 전부 실패)."""
    return VLM_FAIL_NOTE if scan else NO_REP_NOTE if ran else DRM_NOTE


_EMPTY: dict = {"engine": None, "text": "", "tables_std": [], "tables": [], "facts": [], "fields": {}, "rep_path": None, "all_keys": []}
_REP_KEYS = ("text", "tables_std", "tables", "facts", "fields", "rep", "provenance")


def _result(job_id, fname, rep=None, **extra):
    """작업 결과 사전 — rep(대표 결과 JSON)가 없으면 빈 결과(extra에 안내 note). extra = 걸린 시간 ms·rep_path·workspace 등."""
    head = {"job_id": job_id, "filename": fname}
    if rep is None:
        return {**head, "status": "done", **_EMPTY, **extra}
    return {**head, "engine": (rep.get("rep") or {}).get("engine"), **{k: rep.get(k) for k in _REP_KEYS}, "all_keys": sorted(rep), **extra}


def _check_size(n):
    """path·content_b64 두 길 모두 같은 상한 — 넘으면 ValueError(400, 크기와 상한을 MB로)."""
    if msg := parse_limit.too_big(n):
        raise ValueError(msg)


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
        _check_size(len(raw))
    else:
        p = _jail(path)
        fname = p.name
        _check_size(p.stat().st_size)
    if Path(fname).suffix.lower() not in (ok := allowed_exts()):
        raise ValueError(f"지원하지 않는 확장자({Path(fname).suffix or '없음'}) — {sorted(ok)}")
    job_id = time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:12]
    ws = JOBS_DIR / job_id
    (ws / "in").mkdir(parents=True, exist_ok=True)
    if b64:
        (ws / "in" / fname).write_bytes(raw)
        meta = {"filename": fname, "mode": "base64", "bytes": len(raw)}
    else:
        meta = {"filename": fname, "mode": "path", "bytes": p.stat().st_size, "path": str(p)}
    meta["scan"] = _is_scan(ws / "in" / fname if b64 else p)
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
    """오래된 작업 폴더 정리(최근 MAX_JOBS_KEPT개만 보관). keep_job_id(방금 만든 작업)는 이름(UUID) 정렬 위치와 상관없이 남긴다."""
    try:
        done = sorted([p for p in JOBS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name)
        victim = done[:-MAX_JOBS_KEPT] if len(done) > MAX_JOBS_KEPT else []
        for p in victim:
            if p.name != keep_job_id:
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _worker():
    """작업자 스레드(서비스당 1개) — 큐에서 꺼내 파싱 사슬을 돌린다. 큐 대기 시간을 남겨 지연 원인(대기·파싱)을 가른다."""
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
            if j.get("mode") == "path":  # 허용 루트의 원본을 작업 폴더로 복사
                shutil.copy2(Path(j["path"]), ws / "in" / fname)
            note = skip_note(j.get("scan"))
            if note:  # VLM 주소가 없는 스캔 PDF — 파이프라인 없이 빈 결과 즉시
                j["result"] = _result(job_id, fname, note=note)
            else:
                j["result"] = _run_job(job_id, j, ws, fname, t0)
            j["status"] = "done"
        except Exception as e:
            j["status"] = "failed"
            j["error"] = f"{type(e).__name__}: {e}"
        finally:
            j["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        _log(f"{job_id} → {j['status']} ({j.get('elapsed_ms')}ms)")


def _run_job(job_id, j, ws, fname, t0):
    """작업 하나의 파싱 사슬(준비 → 엔진 → 채점 → 대표 결과 — 일괄 파싱과 같은 parse_steps) → 결과 사전.
    제한 시간은 작업 하나(JOB_TIMEOUT)에 걸고 단계마다 남은 시간만 준다. 단계가 실패하면 RuntimeError(작업 실패)."""
    try:
        parse_steps.stack(refresh=True)  # 작업마다 엔진 구성 파일을 다시 검사
    except SystemExit as e:  # 그 작업만 실패(서비스 스레드는 계속)
        raise RuntimeError(f"엔진 구성 파일을 쓰지 못함 — 종료 코드 {e.code}") from None
    post = pc.cfg().transform.represent.post or "supsub"
    job_env = _job_env(post)
    job_env.pop("PARSE_RUN_ID", None)  # 작업마다 새 실행 id(서비스가 물려받은 값을 쓰지 않음)
    parse_steps.run_id(job_env)
    with open(ws / "run.log", "w", encoding="utf-8") as log:

        def step(args):
            p = parse_steps.run_step(args, job_env, max(1.0, JOB_TIMEOUT - (time.time() - t0)), track=True, log=log)
            if p.returncode != 0:
                raise RuntimeError(f"단계 실패({args[0]}): {(p.stdout + p.stderr).strip().splitlines()[-1:] or ['?']}")
            return 0

        (ws / "only.txt").write_text(fname + "\n", encoding="utf-8")
        step(["pipeline.extract.filter_and_rotate", "--src", ws / "in", "--out", ws / "prep", "--only", ws / "only.txt"])
        empty = parse_steps.parse_chain(step, ws / "prep", ws / "parse", ws / "truth.json", ["--limit", "1", "--procs", PROCS])
    ms = round((time.time() - t0) * 1000, 1)
    rep_path = ws / "parse" / "_rep" / (fname + ".json")
    if empty is not None or not rep_path.exists():  # 대표 결과 없음 — 스캔 PDF면 VLM 실패, 아니면 DRM 추정
        note = empty_note(bool(j.get("scan")), ran=empty is None)
        _log(f"{job_id} · 결과 없음 → 빈 결과({'VLM 실패' if note == VLM_FAIL_NOTE else 'DRM 추정'})")
        return _result(job_id, fname, note=note, ms=ms)
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    return _result(job_id, fname, rep, rep_path=str(rep_path), workspace=str(ws), ms=ms)


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
            if n > parse_limit.body_cap():  # 상한 안 파일이면 크기 판정은 _submit의 _check_size가 함
                raise ValueError(
                    f"요청 본문이 크기 상한보다 큼 — 파일 상한 {common_cfg().runtime.parse_max_mb:g}MB(ops.services.data_parsing.mcp_parse_max_file_mb)"
                )
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
        "run_mcp_parsing", sections=("pipeline",)
    )  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    if not TOKEN:  # D-028 ⑨(S7c) — 옛 코드 기본 토큰 없앰: 설정에 없으면 시작 거부(값은 찍지 않음)
        print(
            "[설정] run_mcp_parsing: 토큰 없음 — settings.yaml required.tokens.mcp_token를 적음(검색 MCP와 같은 칸)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)  # service.json 자리 — ROOTS·JOBS_DIR를 env로 다른 곳에 둬도
    parse_steps.stack()  # 엔진 구성 파일을 못 읽거나 없는 엔진이면 시작 거부(종료 2)
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
                "max_mb": common_cfg().runtime.parse_max_mb,
                "job_timeout": JOB_TIMEOUT,
                "queue_max": QUEUE_MAX,
            },
            f,
            indent=2,
        )
    threading.Thread(target=_worker, daemon=True).start()
    _log(f"준비 — http://127.0.0.1:{PORT}/health · roots={[str(r) for r in ROOTS]} · jobs={JOBS_DIR} · pid={os.getpid()}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
