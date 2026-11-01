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
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote, urlsplit

from common.config.settings import cfg, secret_values
from common.core import paths
from common.core.runlog import _LABEL, _mask

_IDS = ("request_id", "run_id", "span_id")
try:
    _inherited = json.loads(os.environ.get("APPLOG_CONTEXT", "{}"))  # env 남김 — 내부 신호(상관 ID, 설정 아님)
except (ValueError, TypeError):
    _inherited = {}
if not isinstance(_inherited, dict):
    _inherited = {}
_CONTEXT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("applog_context", default=None)
_LOGGERS: dict[str, logging.Logger] = {}
_STREAMS: dict = {}
_SHORT_WARNED = False
_SECRET_LOCK = threading.Lock()
_SECRET_LABEL = re.compile(r"(?:" + _LABEL + r")$", re.IGNORECASE)


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


def _secret_variants():
    global _SHORT_WARNED
    fields = secret_values(named=True)
    values = set(fields.values())
    short_fields = set()
    for name, value in fields.items():
        extracted = {value}
        # JSON 옵션은 비밀 라벨의 문자열 값만 수집(라벨 없는 리스트 제외).
        if value.startswith(("{", "[")):
            try:
                pending = [json.loads(value)]
                while pending:
                    item = pending.pop()
                    if isinstance(item, dict):
                        for key, child in item.items():
                            if isinstance(child, str) and _SECRET_LABEL.search(key):
                                extracted.add(child)
                            elif isinstance(child, (dict, list)):
                                pending.append(child)
                    elif isinstance(item, list):
                        pending.extend(child for child in item if isinstance(child, (dict, list)))
            except (ValueError, TypeError):
                pass
        if "://" in value:
            try:
                password = urlsplit(value).password
                if password:
                    extracted.add(unquote(password))
            except ValueError:
                pass
        extracted.update(m.group(1).strip("\"'{}") for m in re.finditer(r"(?i)(?:password|pwd)\s*=\s*([^;]+)", value))
        values.update(extracted)
        if any(0 < len(item) < 4 for item in extracted):
            short_fields.add(name)
    if short_fields:
        with _SECRET_LOCK:
            warn = not _SHORT_WARNED
            _SHORT_WARNED = True
        if warn:
            print("[applog] 비밀 설정은 토큰 경계에서만 마스킹: " + ", ".join(sorted(short_fields)), file=sys.stderr)
    variants = {}
    for value in values:
        if value:
            forms = {value, quote(value, safe=""), quote_plus(value)}
            forms.update(json.dumps(value, ensure_ascii=ascii_only)[1:-1] for ascii_only in (False, True))
            for form in forms:
                # 길이가 늘어난 이스케이프 표기도 원래 비밀값의 경계 정책 유지.
                variants[form] = variants.get(form, True) and len(value) < 4
    return sorted(variants.items(), key=lambda item: len(item[0]), reverse=True)


def masked(value):
    """중첩 JSON/문자열의 패턴 및 현재 settings 비밀 칸 값을 가린 사본.

    4자 이상은 부분 문자열, 1~3자는 앞뒤가 문자·숫자가 아닌 토큰 경계에서만
    가린다. 짧은 비밀값이 다른 문자·숫자에 붙으면 값 대조로 가려지지 않는다.
    설정 시작은 거부하지 않으며 해당 설정 칸만 프로세스당 한 번 stderr로 알린다.
    DSN 비밀번호와 URL/JSON 이스케이프 표기도 포함하며 원본은 바꾸지 않는다.
    CLI의 분리된 인자, 라벨 없는 오류/traceback도 같은 API를 사용한다.
    """
    return _masked(value, _secret_variants())


def _masked(value, secrets):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            probe = f"{key}=applog_secret_probe"
            auth_probe = f"{key}: Bearer applog_secret_probe"
            result[_masked(str(key), secrets)] = (
                "***" if _mask(probe) != probe or _mask(auth_probe) != auth_probe else _masked(item, secrets)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_masked(item, secrets) for item in value]
    if isinstance(value, str):
        for secret, bounded in secrets:
            if bounded:
                value = re.sub(r"(?<![^\W_])" + re.escape(secret) + r"(?![^\W_])", lambda _: "***", value)
            else:
                value = value.replace(secret, "***")
        return _mask(value) if ":" in value or "=" in value else value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _masked(str(value), secrets)


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


def setup(app, *, stream=None):
    """앱 logger 반환; common.log 설정 반영. stream 지정은 앱별 보존(stdio stderr)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", app):
        raise ValueError("app must be a filename-safe name")
    from common.store import logsink

    if stream is not None:
        _STREAMS[app] = stream
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
        handler = logging.StreamHandler(_STREAMS.get(app, sys.stdout))
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
