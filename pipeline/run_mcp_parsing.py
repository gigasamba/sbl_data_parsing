#!/usr/bin/env python3
"""parse_document Redis Streams worker — 공유 파일에서 파싱, 완료 LIST로 즉시 알림.
엔진 구성·파싱 사슬은 일괄 파싱과 같고, 각 소비자는 별도 spawn 프로세스에서 실행한다.
"""

import hashlib
import json
import multiprocessing
import os
import shutil
import signal
import socket
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

from common.config.settings import cfg as common_cfg
from common.config.settings import child_env as settings_env
from common.core import exitclean, jsonlog, parse_limit
from common.core import span as SP
from common.store import redisq
from common.store.redisq import JOBS_DIR, SERVICE_DIR
from pipeline import config as pc
from pipeline import parse_steps
from pipeline.shared import runtrace
from pipeline.transform.parse.engine_check import allowed_exts

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
        # 덮기 파일·인계 칸만 캐시 — settings_env가 실은 작업 컨텍스트까지 캐시하면 다음 작업이 앞 실행에 붙는다.
        extra = _JOB_ENVS[key] = {k: v for k, v in made.items() if k in _JOB_KEYS}
    env = {**os.environ, **extra}  # env 남김 — 하위 프로세스
    return SP.with_context({"env": env})["env"]  # 컨텍스트는 캐시 밖에서 작업마다 새로 얹음


_PM = pc.cfg().service.data_parsing  # S7c — 설정 객체(모듈 상수 — 옛처럼 import 때 한 번)
PROCS = str(
    max(1, _PM.procs if _PM.procs is not None else min(2, (os.cpu_count() or 2) - 1))
)  # worker마다 엔진 병렬 — 기본 worker 2 × 엔진 2 = 4(사용자 결정 2026-11-09)
ROOT_PATHS = [Path(os.path.normpath(p)) for p in (_PM.roots or [str(SERVICE_DIR / "inbox")])]  # resolve 전 설정 경로도 정책에 보존
ROOTS = [p.resolve() for p in ROOT_PATHS]  # 실제 파일 접근 검사는 resolve된 경로로
JOB_TIMEOUT = _PM.job_timeout_sec
QUEUE_MAX = common_cfg().parse_queue.queue_max


MAX_JOBS_KEPT = 30


def _log(msg):
    print(f"[data-parsing {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _jail(path_str):
    """허용 루트 하위 경로만 — 벗어나면 ValueError(디렉터리 탈출·시스템 파일 차단)."""
    p = Path(path_str).resolve()
    if not any(p.is_relative_to(root) for root in ROOTS):
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


def _purge_old(r, keep_job_id=None):
    """mtime 순으로 최근 MAX_JOBS_KEPT개 보관. active·최근 10분 폴더는 등록 전 업로드까지 보호."""
    try:
        done = sorted([p for p in JOBS_DIR.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
        victim = done[:-MAX_JOBS_KEPT] if len(done) > MAX_JOBS_KEPT else []
        for p in victim:
            if p.name != keep_job_id and p.stat().st_mtime < time.time() - 600 and not r.sismember(redisq.key("active"), p.name):
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _validate(j, ws):
    """worker 컨테이너에서 경로·크기·확장자를 검사하고 입력을 준비."""
    if j["mode"] == "path":
        source = _jail(j["path"])
        j["filename"] = source.name
    else:
        source = ws / "in" / redisq.filename(j["filename"])
    _check_size(source.stat().st_size)
    j["bytes"] = source.stat().st_size
    fname = j["filename"]
    if Path(fname).suffix.lower() not in (ok := allowed_exts()):
        raise ValueError(f"지원하지 않는 확장자({Path(fname).suffix or '없음'}) — {sorted(ok)}")
    j["scan"] = _is_scan(source)
    if j["mode"] == "path":
        (ws / "in").mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=ws / "in", suffix=".tmp")
        os.close(fd)
        tmp = Path(temporary)
        try:
            shutil.copy2(source, tmp)
            tmp.replace(ws / "in" / fname)
        finally:
            tmp.unlink(missing_ok=True)


def _process(r, message_id, job_id, consumer, attempts=1):
    """작업 1건 = pipe_run 1건 + mcp_parse.job span. 프로세스마다 runtrace 전역을 따로 가짐."""
    picked = time.time()
    # claim이 반환한 HASH만 사용 — 완료와 경쟁해도 종료 상태를 running으로 덮지 않음.
    raw = r.hgetall(redisq.key("job", job_id))
    try:
        wait_s = round(max(0, picked - float(raw.get("submitted_at", picked))), 1)
    except (TypeError, ValueError):
        wait_s = 0
    j = redisq.claim(r, job_id, consumer, attempts, picked, wait_s)
    if j is None:
        with r.pipeline(transaction=True) as tx:
            tx.multi()
            tx.xack(redisq.key("queue"), redisq.group(), message_id)
            tx.xdel(redisq.key("queue"), message_id)
            tx.execute()
        return
    queue_wait_ms = wait_s * 1000
    t0, status, error = time.time(), "done", ""
    ws = JOBS_DIR / job_id
    result_file = ""
    abandoned = attempts > common_cfg().parse_queue.mcp_parse_max_attempts
    try:
        j = redisq.decode_job(j)
        attempt_ws = ws / f"a{attempts}"
        attempt_ws.mkdir(parents=True, exist_ok=True)
        with (
            jsonlog.context(run_id=None, span_id=None),
            runtrace.run("mcp_parse", ["--job-id", job_id]),
            SP.span("mcp_parse.job", doc_id=j["filename"], ext=Path(j["filename"]).suffix.lower(), file_bytes=j.get("bytes")) as sp,
        ):
            sp.add(job_id=job_id, queue_wait_ms=queue_wait_ms, queue_position=j.get("queue_position", 0), mode=j.get("mode"))
            if abandoned:
                raise RuntimeError(f"worker가 {attempts - 1}번 중단됨 — 작업 포기")
            try:
                _validate(j, ws)
            except (ValueError, FileNotFoundError) as exc:
                status = "rejected"
                raise ValueError(str(exc)) from exc
            sp.add(scan=bool(j.get("scan")))
            sp.set(file_bytes=j["bytes"])
            fname = j["filename"]
            note = skip_note(j.get("scan"))
            result = _result(job_id, fname, note=note) if note else _run_job(job_id, j, attempt_ws, fname, t0)
            if result.get("note"):
                sp.add(note=result["note"])
            # 각 시도 파일 → 최종 파일은 종료 직전에. 완료 알림보다 파일 기록이 먼저다.
            result_path = ws / f"result-{attempts}.json"
            temp_path = ws / f"result-{os.getpid()}.tmp"
            temp_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(result_path)
            result_file = result_path.name
    except Exception as exc:
        if status != "rejected":
            status = "failed"
        error = str(exc) if status == "rejected" or abandoned else f"{type(exc).__name__}: {exc}"
    elapsed = round((time.time() - t0) * 1000, 1)
    redisq.finish(
        r,
        message_id,
        job_id,
        status,
        worker=consumer,
        attempts=attempts,
        filename=j.get("filename", ""),
        bytes=j.get("bytes", 0),
        result_file=result_file,
        elapsed_ms=elapsed,
        finished_at=time.time(),
        error=error,
    )
    _log(f"{job_id} → {status} ({elapsed}ms) · 큐 대기 {j['queue_wait_s']}초")
    _purge_old(r, keep_job_id=job_id)


_CLAIM_CURSORS: dict[str, str] = {}


def _receive(r, consumer, min_idle_ms=None):
    """유실 작업부터 회수, 없으면 새 STREAM 메시지 하나를 기다림."""
    idle = int((JOB_TIMEOUT + 60) * 1000) if min_idle_ms is None else min_idle_ms
    dead = redisq.reclaim_dead(r, consumer)
    rows = [dead] if dead else []
    if not rows:
        claimed = r.xautoclaim(
            redisq.key("queue"), redisq.group(), consumer, min_idle_time=idle, start_id=_CLAIM_CURSORS.get(consumer, "0-0"), count=1
        )
        _CLAIM_CURSORS[consumer] = claimed[0]
        rows = claimed[1]
    if rows:
        message_id, fields = rows[0]
        pending = r.xpending_range(redisq.key("queue"), redisq.group(), message_id, message_id, 1)
        attempts = pending[0]["times_delivered"] if pending else 1
        return message_id, fields["job_id"], consumer, attempts
    messages = r.xreadgroup(redisq.group(), consumer, {redisq.key("queue"): ">"}, count=1, block=5000)
    if messages:
        message_id, fields = messages[0][1][0]
        return message_id, fields["job_id"], consumer, 1
    return None


def _publish_policy(r):
    try:
        redisq.publish_policy(r, allowed_exts(), list(dict.fromkeys([*ROOT_PATHS, *ROOTS])), common_cfg().runtime.parse_max_mb)
    except (Exception, SystemExit) as exc:
        _log(redisq.redact(f"정책 갱신 실패: {type(exc).__name__}: {exc}"))


def _heartbeat(stop, consumer):
    r = redisq.client()
    try:
        while not stop.is_set():
            try:
                r.set(redisq.key("worker", consumer), "1", ex=30)
                _publish_policy(r)
            except Exception as exc:
                _log(redisq.connection_error(exc))
            stop.wait(10)
    finally:
        r.close()


def _worker(supervisor_token):
    consumer = f"{supervisor_token}-{os.getpid()}"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, exitclean._on_term)
    signal.signal(signal.SIGINT, exitclean._on_term)
    pulse = threading.Thread(target=_heartbeat, args=(stop, consumer), daemon=True)
    pulse.start()
    r = redisq.client()
    try:
        redisq.ensure_group(r)
        while not stop.is_set():
            try:
                item = _receive(r, consumer)
                if item:
                    _process(r, *item)
            except Exception as exc:
                if redisq.is_redis_error(exc):
                    _log(redisq.connection_error(exc))
                else:
                    _log(redisq.redact(f"worker 오류: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
                if "NOGROUP" in str(exc):
                    redisq.ensure_group(r)
                stop.wait(2)
    finally:
        stop.set()
        pulse.join(timeout=6)
        try:
            r.delete(redisq.key("worker", consumer))
        except Exception:
            pass
        r.close()


def _run_job(job_id, j, ws, fname, t0):
    """작업 하나의 파싱 사슬(준비 → 엔진 → 채점 → 대표 결과 — 일괄 파싱과 같은 parse_steps) → 결과 사전.
    제한 시간은 작업 하나(JOB_TIMEOUT)에 걸고 단계마다 남은 시간만 준다. 단계가 실패하면 RuntimeError(작업 실패)."""
    try:
        parse_steps.stack(refresh=True)  # 작업마다 엔진 구성 파일을 다시 검사
    except SystemExit as e:  # 그 작업만 실패(소비자 프로세스는 계속)
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
        step(["pipeline.extract.filter_and_rotate", "--src", ws.parent / "in", "--out", ws / "prep", "--only", ws / "only.txt"])
        empty = parse_steps.parse_chain(step, ws / "prep", ws / "parse", ws / "truth.json", ["--limit", "1", "--procs", PROCS])
    ms = round((time.time() - t0) * 1000, 1)
    rep_path = ws / "parse" / "_rep" / (fname + ".json")
    if empty is not None or not rep_path.exists():  # 대표 결과 없음 — 스캔 PDF면 VLM 실패, 아니면 DRM 추정
        note = empty_note(bool(j.get("scan")), ran=empty is None)
        _log(f"{job_id} · 결과 없음 → 빈 결과({'VLM 실패' if note == VLM_FAIL_NOTE else 'DRM 추정'})")
        return _result(job_id, fname, note=note, ms=ms)
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    return _result(job_id, fname, rep, rep_path=str(rep_path), workspace=str(ws), ms=ms)


def _token_file():
    """컨테이너 로컬 임시 폴더. PC에서 다른 큐를 시험해도 서로 덮지 않도록 접두별 파일."""
    ident = hashlib.sha256(redisq.prefix().encode()).hexdigest()[:8]
    return Path(tempfile.gettempdir()) / f"mcp_{ident}.id"


def health():
    r = None
    try:
        token = _token_file().read_text(encoding="utf-8").strip()
        if not token or any(char in token for char in "*?[]"):
            return False
        r = redisq.client()
        return bool(r.ping() and next(r.scan_iter(match=redisq.key("worker", token + "-*")), None))
    except Exception:
        return False
    finally:
        if r is not None:
            r.close()


def main():
    from common.config import setarg
    from common.config.settings import require_run_env
    from common.core.console import utf8_stdout

    utf8_stdout()
    setarg.apply()
    import sys

    if "--health" in sys.argv:
        return 0 if health() else 1
    require_run_env("run_mcp_parsing", sections=("pipeline",))
    try:
        redisq.require_password()
    except redisq.RedisConfigError as exc:
        _log(str(exc))
        return 2
    parse_steps.stack()
    SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for root in ROOTS:
        root.mkdir(parents=True, exist_ok=True)
    r = redisq.client()
    try:
        redisq.ensure_group(r)
        _publish_policy(r)
    finally:
        r.close()
    workers = common_cfg().parse_queue.mcp_parse_workers
    addr = common_cfg().connections.redis
    svc = exitclean.remove_at_exit(SERVICE_DIR / "service.json")
    svc.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "procs": PROCS,
                "max_mb": common_cfg().runtime.parse_max_mb,
                "job_timeout": JOB_TIMEOUT,
                "queue_max": QUEUE_MAX,
                "redis": f"{addr.redis_host}:{addr.redis_port}",
                "workers": workers,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _log(f"준비 — Redis {addr.redis_host}:{addr.redis_port} · workers={workers} · jobs={JOBS_DIR} · pid={os.getpid()}")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    supervisor_token = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    token_file = exitclean.remove_at_exit(_token_file())
    token_file.write_text(supervisor_token, encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    children = []
    try:
        while not stop.is_set():
            children = [child for child in children if child.is_alive() or not _joined(child)]
            while len(children) < workers:
                child = context.Process(target=_worker, args=(supervisor_token,))
                child.start()
                children.append(child)
            stop.wait(1)
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.join(timeout=20)
            if child.is_alive():
                child.kill()
                child.join()
    return 0


def _joined(child):
    child.join()
    _log(f"worker 종료({child.pid}, code={child.exitcode}) — 다시 띄움")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
