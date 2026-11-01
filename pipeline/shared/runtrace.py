"""파이프라인 실행 1건의 추적 기록(op-01) — applog.pipe_run 시작·종료 + 60초 run.progress.

    with run("parse", sys.argv[1:]):      # 최상위 진입점에서 한 번 — command는 하위 명령/모듈 이름(pipe_run.command)
        main()                              # 부모가 run_id를 이어줬으면(자식 프로세스) 새로 시작하지 않음
    info(stack="...")                       # 실행 중 알게 된 값(스택 이름 등)을 종료 행에 보탬
    docs(total=40, ok=38, fail=2)           # 문서 수(여러 번 불러도 덮어씀)
    with Progress(total=len(jobs), done=lambda: n[0]) as pg: ...   # 오래 도는 반복문 옆에서 60초마다 run.progress

기존 runs.jsonl·RUNLOG.md·PROGRESS.md는 그대로 — 이 모듈은 DB/JSON 로그에만 쓴다. 모든 행은 logsink가 비차단으로 보낸다.
"""

import contextlib
import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime

from common.config import settings as C
from common.core import jsonlog, span

PROGRESS_SEC = 60
_STATE: dict = {"info": {}, "docs": {}}


def _log():
    return span._logger()  # 같은 logger를 두 번 setup하지 않게(핸들러를 지우고 다시 달기 때문) — span과 한 곳에서. 열기 실패면 None


def _emit_run(row, event, level=logging.INFO):
    log = _log()
    if log is None:
        return
    log.log(
        level,
        f"{event} {row.get('command', '')} {row.get('status', '')}".strip(),
        extra={
            "event": event,
            "duration_ms": row.get("duration_ms"),
            "log_table": "pipe_run",
            "log_row": row,
            "log_context": {"run_id": row["run_id"], "span_id": None},
        },
    )


@span._soft_fn
def info(**values):
    """종료 행에 보탤 값(stack·workers …) — 실행 중 알게 된 것."""
    _STATE["info"].update({k: v for k, v in values.items() if v is not None})


@span._soft_fn
def docs(**counts):
    """문서 수(total·ok·fail·reused) — 단계마다 알려주면 마지막 값이 종료 행에 들어감."""
    _STATE["docs"].update({f"docs_{k}": int(v) for k, v in counts.items() if v is not None})


def settings_hash():
    """사용자가 명시한 설정(비밀값 제외)의 sha256[:12] — 같은 코드여도 설정이 다른 실행을 가르는 열쇠."""
    items = sorted((name, text) for name, text, _ in C.env_items(C.cfg(), hosts=None, secrets=False, only_set=True) if text is not None)
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _code_fp():
    from common.core import artifacts

    return {layer: artifacts.code_fp(layer) for layer in sorted(artifacts.LAYER_CODE)}


def _start_row(run_id, command, argv):
    from common.core import resources as RS
    from common.core.fingerprint import pipeline_version

    cfg = C.cfg()
    pct = RS.mem_used_pct()
    return {
        "run_id": run_id,
        "command": command,
        "args": " ".join(jsonlog.masked([str(a) for a in argv])),  # 인자별로 가린 뒤 잇는다(분리된 비밀값도 값 기반 마스킹이 잡도록)
        "started_at": datetime.now(UTC),
        "status": "running",
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "app_version": pipeline_version(),
        "run_env": cfg.run_env,
        "code_fp": _code_fp(),
        "settings_hash": settings_hash(),
        "cpu_max_load": cfg.runtime.cpu_max_load,
        "mem_start_pct": None if pct is None else round(pct, 1),
    }


def _status_of(ex):
    if ex is None:
        return "ok"
    if isinstance(ex, SystemExit):
        return "ok" if ex.code in (0, None) else ("stopped" if ex.code == 75 else "fail")  # 75 = 마감 시각 도달(다음 실행이 이어 감)
    return "interrupted" if isinstance(ex, KeyboardInterrupt) else "fail"


@contextlib.contextmanager
def run(command, argv=()):
    """최상위 실행 1건 — run_id 생성 + pipe_run(running → 종료). 부모가 이미 run_id를 이어줬으면 아무것도 안 함."""
    if jsonlog.get_context().get("run_id"):
        yield None
        return
    run_id = str(uuid.uuid4())
    _STATE["info"], _STATE["docs"] = {}, {}
    t0 = time.monotonic()
    started = False
    with jsonlog.context(run_id=run_id, span_id=None):
        try:
            _emit_run(_start_row(run_id, command, list(argv)), "run.start")
            started = True
        except Exception as ex:  # 추적 실패가 파이프라인을 멈추면 안 됨 — 예외 글자는 남기지 않음(타입만 경고 1회)
            span.soft_fail("run.start", ex)
        failure = None
        try:
            yield run_id
        except BaseException as ex:
            failure = ex
            raise
        finally:
            if started:
                try:
                    row = {
                        "run_id": run_id,
                        "ended_at": datetime.now(UTC),
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                        "status": _status_of(failure),
                        **_STATE["info"],
                        **_STATE["docs"],
                    }
                    _emit_run(row, "run.end")
                except Exception as ex:  # 업무 예외(failure)를 덮지 않음
                    span.soft_fail("run.end", ex)


class Progress:
    """오래 도는 반복문 옆의 진행 스레드 — PROGRESS_SEC마다 stage='run.progress' 1행(완료/전체·docs/min·남은 시간·진행 중 개수·부하·메모리).

    done: 지금까지 끝난 수를 돌려주는 함수. total: 전체(모르면 None). unit: 무엇을 세는지(metrics.unit).
    run_id가 없으면(시험·MCP) 스레드를 만들지 않는다."""

    def __init__(self, total, done, unit="doc", every=None):
        self.total, self.done, self.unit = total, done, unit
        self.every = PROGRESS_SEC if every is None else every
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread = None

    def __enter__(self):
        try:
            if jsonlog.get_context().get("run_id"):
                self._thread = threading.Thread(
                    target=span.carry(self._loop), name="run-progress", daemon=True
                )  # 풀·새 스레드는 컨텍스트를 안 물려받음
                self._thread.start()
        except Exception as ex:  # 스레드를 못 만들어도 업무는 진행
            self._thread = None
            span.soft_fail("progress.start", ex)
        return self

    def __exit__(self, *exc):
        try:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2)
                self.emit()  # 마지막 상태 1행
        except Exception as ex:
            span.soft_fail("progress.stop", ex)

    def _loop(self):
        while not self._stop.wait(self.every):
            self.emit()  # emit이 예외를 삼키므로 스레드가 죽지 않음

    def emit(self):
        try:
            done, total = int(self.done()), self.total
            elapsed = max(1e-6, time.monotonic() - self._t0)
            rate = done / elapsed * 60
            eta = (total - done) / (done / elapsed) if total and done else None
            open_now = span.open_counts()
            with span.span("run.progress", "run", seq=done, total=total) as sp:
                sp.add(
                    unit=self.unit,
                    per_min=round(rate, 2),
                    eta_sec=None if eta is None else int(eta),
                    elapsed_sec=int(elapsed),
                    open=open_now,
                )
        except Exception as ex:  # done() 등 진행 계산 실패 — 다음 주기에 다시
            span.soft_fail("progress.emit", ex)
