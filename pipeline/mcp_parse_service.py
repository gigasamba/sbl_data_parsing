#!/usr/bin/env python3
"""텍스트 파싱 작업 서비스 — data-pipeline-mcp 컨테이너(11-03 — 옛 data-pipeline-parse; 작업 서비스가 주 프로세스, compose.pipeline-mcp.yml) 안에서 상주하며 검색 MCP(mcp-server — 옛 data-retrieval)의 parse_document
도구가 localhost HTTP로 호출한다(비정형 파일[base64] → text 파싱 대표 결과 반환).
범위 — prepare → run_all(문서의 엔진들 동시에 · OCR 엔진은 run_all이 뺌) → parse_qa → represent까지.
구조화·임베딩·적재 없음 · 표 인식 유지 · 이미지 파일은 받지 않음 · 스캔 PDF는 내부망 VLM(qwen_vlm — mc-18, 11-03).
[패치 2026-10-22] ① 기본 time_out_threshold 300초 ② 큐 대기 순번을 제출 응답과 시작 시점에 표시(지연 원인 파악)
  ③ 서비스 PID 로그 파일 남김(docker exec -d 로그 없음 문제) ④ _purge_old에서 방금 만든 작업 보호(버그 수정)
실행: data-pipeline-mcp 컨테이너의 주 프로세스(compose.pipeline-mcp.yml — 죽으면 restart가 다시 띄움 · 옛 손 기동 `docker exec -d …` 없음)
  토큰은 설정 필수(컨테이너에 붙인 settings.yaml required.tokens.parse_mcp — 검색 MCP의 MCP_TOKEN과 같은 값, 없으면 시작 거부, D-028 ⑨ · S7c ·
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

from common.config.settings import cfg as common_cfg
from common.config.settings import child_env as settings_env
from common.config.settings import reveal
from common.core import exitclean
from common.core.paths import APP_ROOT  # I4 — 컨테이너 경로(/app/…) 대신 런타임 루트 기준(이미지 안 값 같음)
from pipeline import config as pc
from pipeline.shared.exts import IMG_EXTS

SERVICE_DIR = APP_ROOT / "output" / "_mcp_parse"  # 이미지 안 /app/output/_mcp_parse(op-13 — 임시 자리는 _ 접두)
_JOB_ENVS: dict = {}  # (PARSE_POST, SETTINGS_FILE) → 작업 자식 env에 얹을 몫(덮기 파일 SETTINGS_FILE + 엔진·인계 칸 — VS7e2 R-4)
_JOB_KEYS = (
    "SETTINGS_FILE",
    "PARSE_POST",
)  # 얹을 몫에 늘 넣는 이름(VS8a R-5)


def _job_stack():
    """작업마다 엔진 구성 파일을 다시 읽어 검사(S8b — 사용자 10-28 Q3 a). 못 읽거나 없는 엔진이면(종료 2) 그 작업만 실패(서비스 스레드는 계속)."""
    from pipeline import stackcfg

    try:
        stackcfg.resolve(refresh=True)
    except SystemExit as e:
        raise RuntimeError(f"엔진 구성 파일을 쓰지 못함 — 종료 코드 {e.code}") from None


def _job_env(post):
    """작업 자식 env — 덮기 파일(PARSE_POST 등)을 서비스 설정 파일·후보정 값마다 한 번만 만든다(임시 파일이 작업 수만큼
    쌓이지 않게 — refactor.md C-46). 만든 파일은 서비스가 끝날 때 지운다(pl-27 — child_env가 exitclean에 맡김). OS 임시 폴더 정리(tmpwatch·systemd-tmpfiles·macOS periodic)가 오래 도는 서비스의 그 파일을 지웠으면
    다시 만든다(리뷰 S7e3 — 지워진 파일을 가리키면 서버 자식은 시작 거부, PC는 기본 후보정 all로 돎). 캐시는 덮기 파일이 얹는 몫만 — env는
    작업마다 지금 os.environ에서 새로 만든다(VS7e3 R-6 — 오래 도는 서비스의 라이브러리 env가 바뀌어도 작업 자식에 감). 반환은 새 dict."""
    key = (post, os.environ.get("SETTINGS_FILE"))  # env 남김 — 설정 파일 자리 신호
    extra = _JOB_ENVS.get(key)
    if extra is None or not Path(extra["SETTINGS_FILE"]).is_file():
        pm = pc.cfg().service.parse_mcp
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


_PM = pc.cfg().service.parse_mcp  # S7c — 설정 객체(모듈 상수 — 옛처럼 import 때 한 번)
pc.checked("PARSE_MCP_PORT")  # 형식 틀린 포트는 옛처럼 import 때 실패(조용히 기본 포트로 뜨지 않게 — VS7c1 R-2, 사용자 10-27)
PORT = _PM.port
_TOK = reveal(_PM.token) or ""
TOKEN = _TOK if _TOK.strip() else None  # D-028 ⑨ — 코드 기본 토큰 삭제, 설정 필수(없거나 비거나 공백만이면 아래 __main__이 시작 거부 — R-2)
PROCS = str(
    max(1, _PM.procs if _PM.procs is not None else min(3, (os.cpu_count() or 2) - 1))
)  # 엔진 묶음 병렬(2026-10-21) — 30쪽 PDF 순차 시 120초+ 걸리던 것 대폭 단축
ROOTS = [Path(p).resolve() for p in (_PM.roots or [str(SERVICE_DIR / "inbox")])]  # 쉼표 목록은 객체가 strip·빈 것 버림
JOB_TIMEOUT = _PM.job_timeout_sec
QUEUE_MAX = _PM.queue_max
JOBS_DIR = Path(_PM.jobs_dir or SERVICE_DIR / "jobs")


def allowed_exts():
    """받는 확장자 = 엔진 구성의 parse 키(.pdf_text·.pdf_image → .pdf) − 이미지(IMG_EXTS — "이미지 파싱은 수행 안하고 꺼줘" 요구사항에
    따라 원천 거부). 부를 때마다 읽는다(작업마다 다시 읽는 엔진 구성과 같게, 시작 점검보다 먼저 읽지 않게)."""
    return {".pdf" if e.startswith(".pdf_") else e for e in pc.stack()["parse"]} - IMG_EXTS


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
    cli._run_until과 같은 규칙 — common.core.resources). 시간 초과는 subprocess.TimeoutExpired로 올림(옛 subprocess.run과 같음)."""
    from common.core import resources as PR

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


def _is_scan(path):
    """스캔 PDF인지 — run_all과 같은 판정(parse_qa.pdf_kind: 전체 쪽 글자층이 쪽당 평균 20자 미만 → .pdf_image → qwen_vlm).
    서비스 안내(VLM 미설정·실패)가 실제로 돈 엔진과 어긋나지 않게 판정을 한 곳에서 빌려 쓴다(mc-18 리뷰)."""
    from pipeline.transform.represent.parse_qa import pdf_kind

    return Path(path).suffix.lower() == ".pdf" and pdf_kind(path)[0] == "pdf_image"


# mc-18(사용자 11-03) — 스캔 PDF는 내부망 VLM(qwen_vlm — stack .pdf_image)으로 파싱한다. VLM 주소가 없으면 파이프라인 없이 빈 결과 + 안내,
#   VLM이 돌았는데 결과가 없으면 실패 안내(DRM 추정 아님). 글자층과 스캔 쪽이 섞인 PDF는 범위 밖(pl-03 10-29 결정 그대로).
VLM_UNSET_NOTE = "스캔 PDF — VLM 미설정"
VLM_FAIL_NOTE = "스캔 PDF — VLM 파싱 실패"
DRM_NOTE = "텍스트 추출 실패 — DRM/암호화 문서일 가능성(엔진 전부 파싱 실패)"


def skip_note(scan):
    """파이프라인 없이 바로 빈 결과로 끝낼 문서면 그 안내(VLM 설정 — qwen_vlm REQUIRES_ENV — 이 빈 스캔 PDF), 아니면 None.
    (이미지 확장자는 allowed_exts()에 없어 여기 오지 않음 — 11-01에 도달 불가 갈래 _IMAGE_EXTS·IMAGE_NOTE 지움.)"""
    from pipeline.extract.engines import registry

    return VLM_UNSET_NOTE if scan and registry.missing_env("qwen_vlm") else None


def empty_note(scan):
    """파이프라인이 대표 결과를 못 남겼을 때의 안내 — 스캔 PDF면 VLM 실패, 아니면 DRM 추정(엔진 전부 실패)."""
    return VLM_FAIL_NOTE if scan else DRM_NOTE


def _max_bytes():
    """파일 1건 크기 상한(바이트) — common.runtime.parse_max_mb(검색 MCP와 같은 칸 — 사용자 11-03, 기본 100MB), 요청마다 읽음."""
    return int(common_cfg().runtime.parse_max_mb * 1048576)


def _check_size(n):
    """path·content_b64 두 길 모두 같은 상한 — 넘으면 ValueError(400, 크기와 상한을 MB로)."""
    if n > _max_bytes():
        raise ValueError(
            f"파일이 크기 상한({common_cfg().runtime.parse_max_mb:g}MB)보다 큼({n / 1048576:.1f}MB) — ops.runtime.parse_max_mb"
        )


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
        _check_size(p.stat().st_size)  # 11-03 — 경로로 준 파일도 같은 상한(전에는 content_b64만 봄)
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
    meta["scan"] = _is_scan(ws / "in" / fname if b64 else p)  # mc-18 — run_all과 같은 판정
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
            note = skip_note(j.get("scan"))
            if note:  # mc-18(11-03): VLM 주소가 없는 스캔 PDF — 파이프라인 없이 빈 결과 즉시
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
                    "note": note,
                }
                j["status"] = "done"
            else:
                only = ws / "only.txt"
                only.write_text(fname + "\n", encoding="utf-8")
                log = open(ws / "run.log", "w", encoding="utf-8")
                left = JOB_TIMEOUT
                post = pc.cfg().transform.represent.post  # S7c — 옛 get(X) or "supsub"(없음·빈 값 → supsub)
                _job_stack()  # S8b — 작업마다 엔진 구성 파일 다시 검사
                job_env = _job_env(post or "supsub")  # 하위 프로세스 — 덮기 파일(S7e2), 같은 값이면 한 번 만든 것 재사용(VS7e2 R-4)
                # 2026-10-22 병목 해소: post 기본 all→supsub — RapidOCR·figures·vlm_page·context·attachments를 끔
                # 교차재현율(③)·table_inline(⑦)은 0.0초로 병목이 아니었으므로 그대로 유지 — 실측 47→~0.3초
                # mc-18(11-03) — 작업 제한 시간 하나: 단계마다 남은 시간만(옛: 단계마다 전체 시간)
                _run = lambda cmd: _run_group(cmd, max(1.0, left - (time.time() - t0)), job_env)  # noqa: B023 — 같은 반복 안에서만 부름

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
                    ],
                ):
                    p = _run(cmd)
                    log.write(f"== {' '.join(cmd)}\n{p.stdout}\n{p.stderr}\n")
                    log.flush()
                    if p.returncode != 0:
                        raise RuntimeError(f"단계 실패({cmd[0]}): {(p.stdout + p.stderr).strip().splitlines()[-1:] or ['?']}")

                # ② 결과 없음 → runs.jsonl 부재 → 빈 결과(스캔 PDF면 VLM 실패 안내, 아니면 DRM 추정)
                runs_file = ws / "parse" / "runs.jsonl"
                scan = bool(j.get("scan"))
                if not runs_file.exists():
                    note = empty_note(scan)
                    _log(f"{job_id} · 결과 없음 → 빈 결과({'VLM 실패' if note == VLM_FAIL_NOTE else 'DRM 추정'})")
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
                        "note": note,
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
                            "note": VLM_FAIL_NOTE if scan else "텍스트 추출 결과 없음 — DRM/암호화 문서일 가능성",
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
            # 본문 = JSON 속 base64(파일의 4/3배, 줄바꿈 이스케이프 여유 포함 1.5배 — 검색 MCP 본문 상한과 같은 식) + 1MiB — 11-03: 전에는
            # 파일 상한 + 64KB라 base64 본문은 파일 상한의 3/4에서 막혔음. 상한 안 파일이면 크기 판정은 아래 _check_size가 함
            if n > _max_bytes() * 3 // 2 + 1048576:
                raise ValueError(
                    f"요청 본문이 크기 상한보다 큼 — 파일 상한 {common_cfg().runtime.parse_max_mb:g}MB(ops.runtime.parse_max_mb)"
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
        "mcp_parse_service", sections=("pipeline",)
    )  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    if not TOKEN:  # D-028 ⑨(S7c) — 옛 코드 기본 토큰 없앰: 설정에 없으면 시작 거부(값은 찍지 않음)
        print(
            "[설정] mcp_parse_service: 토큰 없음 — settings.yaml required.tokens.parse_mcp에 검색 MCP의 MCP_TOKEN과 "
            "같은 값을 적음(env로 준 값은 읽지 않음 — S7e2 · 코드 기본 토큰은 없앰 — refactor.md C-42)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)  # service.json 자리 — ROOTS·JOBS_DIR를 env로 다른 곳에 둬도
    from pipeline import stackcfg

    stackcfg.resolve()  # S8b(Q7) — 엔진 구성 파일을 못 읽거나 없는 엔진이면 시작 거부(종료 2)
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
