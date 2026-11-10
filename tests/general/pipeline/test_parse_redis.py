"""실제 로컬 Redis Streams — 고유 test_<uuid>만 사용·삭제, 연결 불가면 건너뜀."""

import multiprocessing
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

from common.config import settings
from common.store import redisq


def _available():
    try:
        import redis

        r = redis.Redis(host="127.0.0.1", port=56379, socket_connect_timeout=1, socket_timeout=1)
        try:
            return bool(r.ping())
        finally:
            r.close()
    except Exception:
        print("[시험] SKIP 로컬 Redis 127.0.0.1:56379 연결 불가")
        return False


def _consume(prefix, directory, mode, pipe=None):
    from pipeline import run_mcp_parsing as S

    with settings.isolated(REDIS_PORT=56379, REDIS_HOST="127.0.0.1", REDIS_PASSWORD=None, REDIS_KEY_PREFIX=prefix):
        r = redisq.client()
        try:
            redisq.ensure_group(r)
            if mode == "block":
                item = S._receive(r, "dead-consumer")
                pipe.send(item)
                pipe.recv()  # PID 강제 종료 전까지 미완료 상태 유지
            else:
                with (
                    mock.patch.object(S, "JOBS_DIR", Path(directory)),
                    mock.patch.object(
                        S, "_run_job", side_effect=lambda jid, j, ws, fname, t0: S._result(jid, fname, {"text": "redis result"})
                    ),
                ):
                    item = S._receive(r, "rescuer" if mode == "recover" else "worker", min_idle_ms=1 if mode == "recover" else None)
                    assert item
                    S._process(r, *item)
        finally:
            r.close()


def _job(r, directory):
    from mcp_server.services import parse_proxy as P

    with mock.patch.object(redisq, "JOBS_DIR", Path(directory)):
        return P._submit({"content_b64": "dGV4dA==", "filename": "a.txt"}, r)[0]


def _cleanup(r):
    keys = list(r.scan_iter(match=redisq.prefix() + ":*"))
    if keys:
        r.delete(*keys)
    r.close()


def test_redis_submit_and_wakeup():
    if not _available():
        return
    prefix = "test_" + uuid.uuid4().hex
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(REDIS_PORT=56379, REDIS_HOST="127.0.0.1", REDIS_PASSWORD=None, REDIS_KEY_PREFIX=prefix),
    ):
        r = redisq.client()
        process = None
        try:
            redisq.ensure_group(r)
            jid = _job(r, directory)
            context = multiprocessing.get_context("spawn")
            process = context.Process(target=_consume, args=(prefix, directory, "normal"))
            received = []
            waiter = threading.Thread(target=lambda: received.append(r.blpop(redisq.key("done", jid), timeout=10)))
            waiter.start()
            process.start()
            waiter.join(timeout=15)
            process.join(timeout=15)
            assert process.exitcode == 0 and received[0]
            job = r.hgetall(redisq.key("job", jid))
            assert job["status"] == "done" and job["attempts"] == "1"
            assert r.scard(redisq.key("active")) == 0 and r.xpending(redisq.key("queue"), redisq.group())["pending"] == 0
            assert r.xlen(redisq.key("queue")) == 0
            assert 0 < r.ttl(redisq.key("job", jid)) <= 86400
            assert (Path(directory) / jid / "result.json").is_file()
        finally:
            if process and process.is_alive():
                process.terminate()
                process.join(timeout=10)
            _cleanup(r)


def test_dead_worker_reclaim():
    if not _available():
        return
    prefix = "test_" + uuid.uuid4().hex
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(REDIS_PORT=56379, REDIS_HOST="127.0.0.1", REDIS_PASSWORD=None, REDIS_KEY_PREFIX=prefix),
    ):
        r = redisq.client()
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe()
        dead = context.Process(target=_consume, args=(prefix, directory, "block", send))
        rescuer = None
        try:
            redisq.ensure_group(r)
            jid = _job(r, directory)
            dead.start()
            assert receive.poll(10)
            item = receive.recv()
            assert item[1] == jid and item[3] == 1
            dead.kill()  # 새 subprocess 하나만 PID로 강제 종료, 운영 worker는 안 건드림
            dead.join(timeout=10)
            time.sleep(0.02)
            rescuer = context.Process(target=_consume, args=(prefix, directory, "recover"))
            rescuer.start()
            assert r.blpop(redisq.key("done", jid), timeout=10)
            rescuer.join(timeout=10)
            assert rescuer.exitcode == 0
            job = r.hgetall(redisq.key("job", jid))
            assert job["status"] == "done" and job["attempts"] == "2" and job["worker"] == "rescuer"
            assert r.xlen(redisq.key("queue")) == 0
        finally:
            for process in (dead, rescuer):
                if process and process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
            receive.close()
            send.close()
            _cleanup(r)


def test_worker_supervisor_and_health():
    if not _available():
        return
    import os
    import signal
    import subprocess
    import sys

    prefix = "test_" + uuid.uuid4().hex
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(REDIS_PORT=56379, REDIS_HOST="127.0.0.1", REDIS_PASSWORD=None, REDIS_KEY_PREFIX=prefix),
    ):
        r = redisq.client()
        env = settings.child_env(MCP_PARSE_WORKERS=1)
        output = (Path(directory) / "worker.log").open("w", encoding="utf-8")
        # 같은 worktree의 실행 중 데모 service.json·inbox·jobs를 건드리지 않도록 이 supervisor의 자리만 격리.
        code = """import sys
from pathlib import Path
from pipeline import run_mcp_parsing as S
S.SERVICE_DIR = Path(sys.argv[1])
S.JOBS_DIR = S.SERVICE_DIR / 'jobs'
S.ROOTS = [S.SERVICE_DIR / 'inbox']
raise SystemExit(S.main())
"""
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(Path(directory) / "service")],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        (Path(directory) / "worker.pid").write_text(str(process.pid), encoding="utf-8")
        try:
            deadline = time.monotonic() + 15
            first = []
            while time.monotonic() < deadline and not first:
                first = list(r.scan_iter(match=redisq.key("worker", "*")))
                time.sleep(0.05)
            assert first and process.poll() is None
            child_pid = int(first[0].rsplit("-", 1)[1])
            os.kill(child_pid, signal.SIGKILL)  # 이 시험 supervisor가 띄운 소비자 PID만
            deadline = time.monotonic() + 15
            replacements = []
            while time.monotonic() < deadline and not replacements:
                replacements = [k for k in r.scan_iter(match=redisq.key("worker", "*")) if k not in first]
                time.sleep(0.05)
            assert replacements and process.poll() is None
            result = subprocess.run(
                [sys.executable, "-m", "pipeline.run_mcp_parsing", "--health"], env=env, capture_output=True, timeout=10
            )
            assert result.returncode == 0
            process.terminate()
            process.wait(timeout=30)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
            output.close()
            _cleanup(r)


def test_concurrent_capacity():
    if not _available():
        return
    from concurrent.futures import ThreadPoolExecutor

    prefix = "test_" + uuid.uuid4().hex
    with settings.isolated(REDIS_PORT=56379, REDIS_HOST="127.0.0.1", REDIS_PASSWORD=None, REDIS_KEY_PREFIX=prefix):
        r = redisq.client()
        try:

            def submit(number):
                try:
                    return redisq.submit(r, str(number), {"filename": "a.txt"}, 3)
                except redisq.QueueFull:
                    return None

            with ThreadPoolExecutor(max_workers=12) as pool:
                positions = list(pool.map(submit, range(12)))
            assert sorted(p for p in positions if p is not None) == [0, 1, 2]
            assert r.scard(redisq.key("active")) == r.xlen(redisq.key("queue")) == 3
            assert len(list(r.scan_iter(match=redisq.key("job", "*")))) == 3
        finally:
            _cleanup(r)
