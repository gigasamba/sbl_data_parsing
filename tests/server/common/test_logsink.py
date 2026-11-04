"""op-01: DB 실패·느림·큐 포화·정상/SIGTERM 종료(외부 접속 없음)."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from common.config import settings
from common.store import logsink


def _rows(directory):
    return [json.loads(line) for path in Path(directory).glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]


def test_db_fallback():
    def failed(batch):
        raise RuntimeError("password=never-print-exception")

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=failed, fallback_dir=directory, flush_sec=60)
        assert sink.emit("mcp_log", {"args": '{"token": "never-store-secret"}', "result_keys": {"password": "never-store-secret"}})
        sink.close()
        sink.close()
        rows = _rows(directory)
        assert len(rows) == 1 and rows[0]["table"] == "mcp_log"
        assert "never-store-secret" not in json.dumps(rows)
        assert sink.stats()["fallback"] == 1 and sink.stats()["dropped"] == 0


def test_full_queue():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow(batch):
        started.set()
        release.wait(30)
        finished.set()

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=slow, fallback_dir=directory, queue_size=1, batch_size=1, flush_sec=0.01, shutdown_sec=1.0)
        assert sink.emit("pipe_event", {"stage": "first"})
        assert started.wait(3)
        assert sink.emit("pipe_event", {"stage": "second"})
        assert not sink.emit("pipe_event", {"stage": "dropped"})
        assert not release.is_set() and not finished.is_set()
        assert sink.stats()["dropped"] == 1
        sink.close()
        assert {r["row"]["stage"] for r in _rows(directory)} == {"first", "second"}
        assert sink.stats()["fallback"] == 2
        release.set()
        sink._thread.join(timeout=2)
        assert not sink._thread.is_alive()


def test_shutdown_flush():
    received = []
    sink = logsink.Sink(writer=received.extend, flush_sec=60, batch_size=2)
    for n in range(5):
        assert sink.emit("pipe_event", {"seq": n})
    sink.close()
    assert [row["seq"] for _, row in received] == list(range(5))
    assert sink.stats()["written"] == 5
    assert not sink.emit("pipe_event", {"seq": 6})


def test_process_flush():
    script = """
import sys, time
from common.store.logsink import Sink
def failed(batch):
    raise RuntimeError("offline")
s = Sink(writer=failed, fallback_dir=sys.argv[1], flush_sec=60)
s.emit("pipe_event", {"stage": "exit"})
print("ready", flush=True)
if sys.argv[2] == "locked":
    import os, signal
    with s._state:
        os.kill(os.getpid(), signal.SIGTERM)
if sys.argv[2] == "term":
    time.sleep(60)
"""
    for mode in ("ok", "term", "locked") if os.name != "nt" else ("ok",):
        with tempfile.TemporaryDirectory() as directory:
            proc = subprocess.Popen(
                [sys.executable, "-c", script, directory, mode],
                env=settings.child_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
            if mode == "term":
                proc.terminate()
            _, err = proc.communicate(timeout=15)
            assert proc.returncode == (0 if mode == "ok" else 143), err
            assert len(_rows(directory)) == 1


def test_setting_rows():
    secret = "DEMO_SECRET_VALUE"
    received = []
    with tempfile.TemporaryDirectory() as directory, settings.isolated(PG_PASSWORD=secret):
        sink = logsink.Sink(writer=received.extend, fallback_dir=directory, flush_sec=60)
        assert sink.emit("pipe_run", {"args": ["--key", secret], "err": secret})
        sink.close()
        assert len(received) == 1 and secret not in json.dumps(received)

        def failed(batch):
            raise RuntimeError("offline")

        sink = logsink.Sink(writer=failed, fallback_dir=directory, flush_sec=60)
        assert sink.emit("mcp_log", {"args": json.dumps({"nested": [secret]}), "result": secret, "error_message": secret})
        sink.close()
        assert len(_rows(directory)) == 1 and secret not in json.dumps(_rows(directory))


def test_blocked_fallback():
    # 잠금을 쥔 기존 fallback과 종료 때 처음 시작한 파일 쓰기 양쪽을 재현한다.
    for mode in ("lock", "write"):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def failed(batch):
            raise RuntimeError("offline")

        class BlockedFile:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, text, entered=entered, release=release, finished=finished):
                entered.set()
                release.wait(30)
                finished.set()

        with tempfile.TemporaryDirectory() as directory:
            sink = logsink.Sink(writer=failed, fallback_dir=directory, flush_sec=0.01, shutdown_sec=0.08)
            if mode == "lock":
                sink._file_lock.acquire()
            try:
                with patch.object(Path, "open", return_value=BlockedFile()) if mode == "write" else patch.object(logsink, "_warn_once"):
                    assert sink.emit("pipe_event", {"seq": 1})
                    if mode == "write":
                        assert entered.wait(2)
                    else:
                        time.sleep(0.03)
                    assert sink.close()
                    assert not release.is_set() and not finished.is_set()
                    assert sink.stats()["dropped"] == 1
                    sink.close()
                    assert sink.stats()["dropped"] == 1
            finally:
                release.set()
                if mode == "lock":
                    sink._file_lock.release()
                sink._thread.join(timeout=2)
            assert sink.stats()["fallback"] == 0  # 늦은 완료를 중복 집계하지 않음.
