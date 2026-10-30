"""두 앱의 JSON Lines 기록(op-01), 표준 logging만 사용한다.

    log = setup("mcp")  # PC logs/mcp.jsonl, 이미지 stdout; common.log.* 설정
    with context(request_id="..."):  # pipeline: run_id=..., span_id=...
        log.info("done", extra={"event": "tool.done", "duration_ms": 12})

get_context()/set_context(**ids)/reset_context(token)은 contextvars API다.
settings.child_env()가 현재 ID를 내부 신호로 자식에 전달한다. DB 감사/성능 행은
common.store.logsink.emit(table, row), 또는 extra={"log_table": ..., "log_row": ...}.
setup은 같은 앱에 멱등이며 기존 앱 밖 logger는 건드리지 않는다. shutdown()은 flush한다.
"""

import contextlib
import contextvars
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from common.config.settings import cfg
from common.core import paths
from common.core.runlog import _mask

_IDS = ("request_id", "run_id", "span_id")
try:
    _inherited = json.loads(os.environ.get("APPLOG_CONTEXT", "{}"))  # env 남김 — 내부 신호(상관 ID, 설정 아님)
except (ValueError, TypeError):
    _inherited = {}
if not isinstance(_inherited, dict):
    _inherited = {}
_CONTEXT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("applog_context", default=None)
_LOGGERS: dict[str, logging.Logger] = {}


def get_context():
    """현재 request/run/span ID 사본(자식은 부모가 전달한 ID에서 시작)."""
    return {**{k: v for k, v in _inherited.items() if k in _IDS}, **(_CONTEXT.get() or {})}


def set_context(**ids):
    """ID를 겹쳐 설정하고 reset_context에 줄 토큰을 반환한다(None은 ID 지움)."""
    if set(ids) - set(_IDS):
        raise ValueError("context keys: request_id, run_id, span_id")
    return _CONTEXT.set({**get_context(), **ids})


def reset_context(token):
    _CONTEXT.reset(token)


@contextlib.contextmanager
def context(**ids):
    token = set_context(**ids)
    try:
        yield get_context()
    finally:
        reset_context(token)


def masked(value):
    """문자열/중첩 JSON 값을 기존 runlog._mask로 가린 사본(원본은 그대로)."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            probe = f"{key}=applog_secret_probe"
            auth_probe = f"{key}: Bearer applog_secret_probe"
            result[str(key)] = "***" if _mask(probe) != probe or _mask(auth_probe) != auth_probe else masked(item)
        return result
    if isinstance(value, (list, tuple)):
        return [masked(item) for item in value]
    if isinstance(value, str):
        return _mask(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _mask(str(value))


class JsonFormatter(logging.Formatter):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def format(self, record):
        ids = getattr(record, "log_context", None) or get_context()
        err = getattr(record, "err", None)
        if record.exc_info:
            err = self.formatException(record.exc_info)
        row = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "app": self.app,
            "event": getattr(record, "event", record.name),
            "msg": record.getMessage(),
            "request_id": ids.get("request_id"),
            "run_id": ids.get("run_id"),
            "span_id": ids.get("span_id"),
            "duration_ms": getattr(record, "duration_ms", None),
            "err": err,
        }
        return json.dumps(masked(row), ensure_ascii=False)


def setup(app):
    """앱 logger 반환; common.log.level/dir/db_enabled를 읽는다. 재호출 시 설정 반영."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", app):
        raise ValueError("app must be a filename-safe name")
    from common.store import logsink

    log = logging.getLogger(app)
    for handler in log.handlers[:]:
        log.removeHandler(handler)
        handler.close()
    conf = cfg().log
    log.setLevel(conf.level)
    log.propagate = False
    if conf.dir or paths.LOCAL_RUN:
        directory = Path(conf.dir) if conf.dir else paths.PROJ_ROOT / "logs"
        if not directory.is_absolute():
            directory = paths.PROJ_ROOT / directory
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(directory / f"{app}.jsonl", encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(app))
    log.addHandler(handler)
    if conf.db_enabled:
        log.addHandler(logsink.Handler())
    _LOGGERS[app] = log
    return log


def shutdown():
    from common.store import logsink

    logsink.shutdown()
    for log in _LOGGERS.values():
        for handler in log.handlers:
            handler.flush()
