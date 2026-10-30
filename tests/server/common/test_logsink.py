"""op-01: DB 실패·느림·큐 포화·정상/SIGTERM 종료(외부 접속 없음)."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from common.config import settings
from common.store import logsink


def _rows(directory):
    return [json.loads(line) for path in Path(directory).glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]


def test_db_fallback():
    def failed(batch):
        raise RuntimeError("password=never-print-exception")

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=failed, fallback_dir=directory, flush_sec=60)
        assert sink.emit("mcp_call", {"args": '{"token": "never-store-secret"}', "client_info": {"password": "never-store-secret"}})
        sink.close()
        sink.close()
        rows = _rows(directory)
        assert len(rows) == 1 and rows[0]["table"] == "mcp_call"
        assert "never-store-secret" not in json.dumps(rows)
        assert sink.stats()["fallback"] == 1 and sink.stats()["dropped"] == 0


def test_full_queue():
    started, release = threading.Event(), threading.Event()

    def slow(batch):
        started.set()
        release.wait(5)

    with tempfile.TemporaryDirectory() as directory:
        sink = logsink.Sink(writer=slow, fallback_dir=directory, queue_size=1, batch_size=1, flush_sec=0.01, shutdown_sec=0.02)
        assert sink.emit("pipe_event", {"stage": "first"})
        assert started.wait(3)
        begin = time.monotonic()
        assert sink.emit("pipe_event", {"stage": "second"})
        assert not sink.emit("pipe_event", {"stage": "dropped"})
        assert time.monotonic() - begin < 0.5
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
