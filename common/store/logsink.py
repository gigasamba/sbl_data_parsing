"""비차단 applog sink: 메모리 큐 → 데몬 스레드 → 배치 INSERT, 장애 시 jsonl.

    emit("mcp_call", {"ts": datetime.now(UTC), "request_id": uuid, ...})
    emit("pipe_run", {"run_id": uuid, "started_at": ..., ...})
    emit("pipe_event", {"ts_start": ..., "run_id": uuid, ...})

pipe_run은 시작(running)·종료를 같은 run_id로 emit하면 UPSERT한다.
TEXT 칸(args/result/stack 등)은 문자열, JSONB 칸(client_info/result_keys/code_fp/metrics)은
dict/list, 시각은 datetime 또는 ISO 문자열을 준다.
common.log.db_enabled=false면 emit은 False(기록 안 함). True면 첫 emit에 시작한다.
Handler는 log_table/log_row extra가 있는 LogRecord만 받는다. 수준 필터는 logger가 맡는다.
Sink(writer=callable, ...)는 테스트/독립 소비자용, callable 인자는 [(table, masked_row)].
stats()는 accepted/dropped/written/fallback/fallback_errors 집계. 큐가 가득 차면 즉시
False를 반환하고 dropped를 올린다. shutdown은 exitclean에 등록되며 제한 시간 뒤
미처리 행을 파일에 기록한다. 종료 중 DB 커밋 결과가 불명확한 배치는 파일과 DB 양쪽에
있을 수 있다(at-least-once); 상관 ID로 대조한다. sink는 DDL을 실행하지 않는다.
"""

import json
import logging
import os
import queue
import sys
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from common.config.settings import cfg
from common.core import exitclean, paths

_TABLES = ("mcp_call", "pipe_run", "pipe_event")
_SINGLETON = None
_SINGLE_LOCK = threading.Lock()
_WARN_LOCK = threading.Lock()
_WARNED = False


def _warn_once():
    global _WARNED
    with _WARN_LOCK:
        if _WARNED:
            return
        _WARNED = True
    # 예외 글자는 DSN/행 값을 포함할 수 있으므로 찍지 않음. logging 재귀도 피한다.
    print("[applog] DB 기록 실패/지연 — jsonl 대체 기록(이 프로세스에서 한 번 알림)", file=sys.stderr)


def _write_db(batch, schema="applog"):
    from psycopg.types.json import Jsonb

    from common.store.db import dbtool
    from common.store.db.models.log_tables import JSON_COLUMNS, log_metadata

    schema = dbtool.schema_of("applog", schema)
    limit = cfg().log.db_timeout_sec
    eng = dbtool.engine(connect_timeout=limit, options=f"-c statement_timeout={limit * 1000} -c lock_timeout={limit * 1000}")
    try:
        groups = defaultdict(list)
        for table, row in batch:
            groups[(table, tuple(sorted(row)))].append(row)
        md = log_metadata()
        with eng.begin() as conn:
            for (table, keys), rows in groups.items():
                cols = md.tables[f"applog.{table}"].columns
                if not keys or set(keys) - set(cols.keys()):
                    raise ValueError("unknown applog column")
                values = [{k: Jsonb(v) if k in JSON_COLUMNS and v is not None else v for k, v in row.items()} for row in rows]
                conflict = ""
                if table == "pipe_run":
                    update = [k for k in keys if k != "run_id"]
                    conflict = " ON CONFLICT (run_id) " + (
                        "DO UPDATE SET " + ", ".join(f"{k} = EXCLUDED.{k}" for k in update) if update else "DO NOTHING"
                    )
                conn.exec_driver_sql(
                    f"INSERT INTO {schema}.{table} ({', '.join(keys)}) VALUES ({', '.join('%(' + k + ')s' for k in keys)})" + conflict,
                    values,
                )
    finally:
        eng.dispose()


class Sink:
    def __init__(self, *, writer=None, fallback_dir=None, queue_size=None, batch_size=None, flush_sec=None, shutdown_sec=None):
        conf = cfg().log
        self.writer = writer or _write_db
        directory = Path(fallback_dir or conf.fallback_dir)
        self.directory = directory if directory.is_absolute() else paths.PROJ_ROOT / directory
        self.queue: queue.Queue = queue.Queue(maxsize=queue_size or conf.queue_size)
        self.batch_size = batch_size or conf.batch_size
        self.flush_sec = flush_sec or conf.flush_sec
        self.shutdown_sec = conf.shutdown_sec if shutdown_sec is None else shutdown_sec
        self._stop = threading.Event()
        self._state = threading.Lock()
        self._file_lock = threading.Lock()
        self._active: list = []
        self._counts = dict.fromkeys(("accepted", "dropped", "written", "fallback", "fallback_errors"), 0)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="applog", daemon=True)
        exitclean.on_exit(self.close)
        self._thread.start()

    def emit(self, table, row):
        """마스킹한 행을 put_nowait; DB·파일 접근은 백그라운드에서만."""
        if table not in _TABLES:
            raise ValueError("unknown applog table")
        from common.core.jsonlog import masked

        item = (table, masked(row))
        with self._state:
            if self._closed:
                self._counts["dropped"] += 1
                return False
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                self._counts["dropped"] += 1
                return False
            self._counts["accepted"] += 1
        return True

    def stats(self):
        with self._state:
            return {**self._counts, "queued": self.queue.qsize()}

    def _fallback(self, batch):
        if not batch:
            return
        _warn_once()
        try:
            with self._file_lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / f"{datetime.now(UTC):%Y-%m-%d}_{os.getpid()}.jsonl"
                with path.open("a", encoding="utf-8") as fh:
                    for table, row in batch:
                        fh.write(json.dumps({"table": table, "row": row}, ensure_ascii=False) + "\n")
            with self._state:
                self._counts["fallback"] += len(batch)
        except OSError:
            with self._state:
                self._counts["fallback_errors"] += len(batch)

    def _take(self):
        with self._state:
            batch = []
            while len(batch) < self.batch_size:
                try:
                    batch.append(self.queue.get_nowait())
                except queue.Empty:
                    break
            self._active = batch
            return batch

    def _run(self):
        while True:
            self._stop.wait(self.flush_sec)
            batch = self._take()
            if batch:
                try:
                    self.writer(batch)
                    failed = False
                except Exception:
                    failed = True
                with self._state:
                    # close가 소유권을 가져갔으면 파일 기록은 close가 맡는다.
                    owned = self._active is batch
                    if owned:
                        self._active = []
                        if not failed:
                            self._counts["written"] += len(batch)
                if owned and failed:
                    self._fallback(batch)
            if self._stop.is_set() and self.queue.empty():
                return

    def close(self):
        """신규 기록을 막고 제한 시간까지 drain, 남는 큐/진행 배치는 파일로."""
        # SIGTERM이 주 스레드의 emit 잠금 안에서 끼어들 수 있다. 그때는 atexit가 재시도.
        if not self._state.acquire(timeout=0.1):
            return False
        try:
            if self._closed:
                return True
            self._closed = True
            self._stop.set()
        finally:
            self._state.release()
        self._thread.join(timeout=self.shutdown_sec)
        with self._state:
            batch, self._active = list(self._active), []
            while True:
                try:
                    batch.append(self.queue.get_nowait())
                except queue.Empty:
                    break
        self._fallback(batch)
        return True


def get_sink():
    global _SINGLETON
    if not cfg().log.db_enabled:
        return None
    with _SINGLE_LOCK:
        if _SINGLETON is None:
            _SINGLETON = Sink()
        return _SINGLETON


def emit(table, row):
    sink = get_sink()
    return sink.emit(table, row) if sink else False


def stats():
    return (
        _SINGLETON.stats() if _SINGLETON else dict.fromkeys(("accepted", "dropped", "written", "fallback", "fallback_errors", "queued"), 0)
    )


def shutdown():
    global _SINGLETON
    with _SINGLE_LOCK:
        sink, _SINGLETON = _SINGLETON, None
    if sink:
        sink.close()


class Handler(logging.Handler):
    def emit(self, record):
        table, row = getattr(record, "log_table", None), getattr(record, "log_row", None)
        if table and row is not None:
            emit(table, row)
