"""MCP 감사 기록(op-01): 요청 컨텍스트, 바이트 상한, 결과 키, 비차단 공통 sink.

모든 공개 진입점은 fail-soft다. 도구 반환/예외와 qa_log는 바꾸지 않는다.
result_sha256/bytes는 마스킹 전 전체 JSON 기준, 저장 본문은 마스킹 후 UTF-8 앞부분이다.
"""

import base64
import contextlib
import contextvars
import hashlib
import inspect
import json
import sys
import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from common import pipeline_version
from common.core import jsonlog
from common.store import logsink
from mcp_server import config as mc
from mcp_server.services.search.server_state import CALLER

_REQUEST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("mcp_audit", default=None)
_LOG = None
_LOG_LOCK = threading.Lock()


def _debug(event, **fields):
    try:
        with jsonlog.context(**({"request_id": fields["request_id"]} if fields.get("request_id") else {})):
            _logger().debug(json.dumps(jsonlog.masked(fields), ensure_ascii=False, default=str), extra={"event": event})
    except Exception:
        pass


def _logger():
    global _LOG
    if _LOG is None:
        with _LOG_LOCK:
            if _LOG is None:
                _LOG = jsonlog.setup("mcp")
    return _LOG


def configure_stdio():
    """stdio stdout은 MCP 전용. 공통 setup의 서버 스트림을 stderr로 보존."""
    global _LOG
    try:
        with _LOG_LOCK:
            _LOG = jsonlog.setup("mcp", stream=sys.stderr)
    except Exception:
        pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def _body(value, limit):
    original = _json(value)
    safe = _json(jsonlog.masked(value))
    saved = safe[:limit].decode("utf-8", errors="ignore")
    return saved, len(original), len(safe) > limit, hashlib.sha256(original).hexdigest()


def _input(tool, args):
    args = dict(args)
    if tool == "parse_document" and args.get("content_b64") is not None:
        encoded = str(args["content_b64"]).encode("utf-8")
        try:
            raw = base64.b64decode(encoded, validate=True)
            kind = "decoded"
        except ValueError:
            raw, kind = encoded, "encoded_invalid"
        args["content_b64"] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "representation": kind}
    return args


def result_keys(tool, result):
    """응답 dict에서 원문 없이 고정 필드만 복사(본문 상한과 독립)."""
    if not isinstance(result, dict):
        return {}
    if tool == "search":
        hits = [x for x in result.get("evidence", []) if isinstance(x, dict)]
        for doc in result.get("docs", []):
            if isinstance(doc, dict):
                hits.extend(x for x in doc.get("chunks", []) if isinstance(x, dict))
        return {
            "chunk_ids": [x.get("chunk_id") for x in hits],
            "rank": [x.get("rank") for x in hits],
            "via": [x.get("via") for x in hits],
            **{k: result[k] for k in ("evidence_status", "total_docs", "total_chunks") if k in result},
        }
    if tool == "query_edw":
        return {k: result[k] for k in ("row_count", "columns") if k in result}
    if tool == "parse_document":
        return {**{k: result[k] for k in ("job_id", "engine", "rep_path") if k in result}, "text_chars": len(result.get("text") or "")}
    if tool == "edw_meta":
        keys = {
            k: result[k] for k in ("kind", "schema", "table", "qualified_name", "table_count", "column_total", "row_count") if k in result
        }
        for field, name in (("schemas", "schema_count"), ("tables", "table_count"), ("columns", "column_count")):
            if isinstance(result.get(field), list):
                keys[name] = len(result[field])
        return keys
    return {}


def _status(result):
    if isinstance(result, dict) and (result.get("error") or result.get("ok") is False):
        err = str(result.get("error") or "tool error")
        if err in ("busy", "unauthorized"):
            return err, err
        if "timeout" in err.lower() or "시간 안에" in err:
            return "timeout", err
        return "error", err
    return "ok", None


@contextlib.contextmanager
def request_context(headers, scope, payload=None, client_info=None):
    """ASGI 요청 범위. 헤더 우선 user, 없으면 tools/call params._meta.user."""
    payload = payload if isinstance(payload, dict) else {}
    params = payload.get("params") or {}
    params = params if isinstance(params, dict) else {}
    meta = params.get("_meta") or {}
    meta = meta if isinstance(meta, dict) else {}
    request_id = headers.get("x-request-id")
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        request_id = str(uuid4())
    data = {
        "request_id": request_id,
        "agent": (headers.get("x-mcp-client") or "http")[:60],
        "user_id": headers.get("x-mcp-user") or meta.get("user"),
        "remote_addr": str((scope.get("client") or ("",))[0]),
        "session_id": headers.get("mcp-session-id"),
        "client_info": client_info,
    }
    if payload.get("method") == "initialize":
        data.update(
            tool="initialize",
            arguments=params,
            client_info={
                **(params["clientInfo"] if isinstance(params.get("clientInfo"), dict) else {}),
                "protocolVersion": params.get("protocolVersion"),
            },
        )
    if payload.get("method") == "tools/call":
        data.update(tool=params.get("name"), arguments=params.get("arguments") or {})
    token = _REQUEST.set(data)
    caller_token = CALLER.set("mcp:" + data["agent"])
    try:
        with jsonlog.context(request_id=request_id):
            yield data
    finally:
        CALLER.reset(caller_token)
        _REQUEST.reset(token)


class Call:
    def __init__(self, fn, args, kwargs):
        self.started = time.perf_counter()
        self.ts = datetime.now(UTC)
        self.thread_started = None
        self.thread_ended = None
        self.abandoned = False
        self.done = False
        self.lock = threading.Lock()
        context = dict(_REQUEST.get() or {})
        tool = context.pop("tool", None) or getattr(fn, "__name__", "unknown").removeprefix("do_")
        arguments = context.pop("arguments", None)
        if arguments is None:
            arguments = dict(inspect.signature(fn).bind(*args, **kwargs).arguments)
        request_id = context.get("request_id") or jsonlog.get_context().get("request_id") or str(uuid4())
        self.row = {"request_id": request_id, "agent": CALLER.get().removeprefix("mcp:"), **context, "tool": tool}
        conf = mc.cfg().audit
        self.output_limit = conf.max_output_bytes
        text, size, truncated, _ = _body(_input(tool, arguments), conf.max_input_bytes)
        self.row.update(args=text, args_bytes=size, args_truncated=truncated)

    def run(self, fn, *args, **kwargs):
        """실제 스레드 시작 시각으로 큐 대기를 측정, 취소 후 종료는 DEBUG만."""
        with self.lock:
            self.thread_started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            with self.lock:
                self.thread_ended = datetime.now(UTC)
                if self.abandoned:
                    _debug("mcp.thread.finished", request_id=self.row["request_id"], ended_at=self.thread_ended)

    def finish(self, result=None, *, status=None, err=None):
        try:
            with self.lock:
                if self.done:
                    return
                self.done = True
                now = time.perf_counter()
                if status == "timeout":
                    self.abandoned = self.thread_started is not None and self.thread_ended is None
                    _debug("mcp.thread.abandoned", request_id=self.row["request_id"], running=self.abandoned, ended_at=self.thread_ended)
            inferred, inferred_err = _status(result)
            text, size, truncated, digest = _body(result, self.output_limit)
            row = {
                **self.row,
                "ts": self.ts,
                "result": text,
                "result_bytes": size,
                "result_truncated": truncated,
                "result_sha256": digest,
                "result_keys": jsonlog.masked(result_keys(self.row["tool"], result)),
                "status": status or inferred,
                "err": jsonlog.masked(err or inferred_err),
                "duration_ms": round((now - self.started) * 1000),
                "queue_wait_ms": round(((self.thread_started or now) - self.started) * 1000),
                "app_version": pipeline_version(),
            }
            # 공통 sink가 DB/장애 시 파일을 맡는다. Handler로 중복 기록하지 않는다.
            logsink.emit("mcp_call", jsonlog.masked(row))
            with jsonlog.context(request_id=row["request_id"]):
                _logger().info("%s %s", row["tool"], row["status"], extra={"event": "mcp.call", "duration_ms": row["duration_ms"]})
        except Exception:
            # 기록 실패로 본래 응답·예외를 바꾸지 않는다. 예외 본문은 비밀을 포함할 수 있다.
            _debug("mcp.audit.failed", tool=self.row.get("tool"))


class _NoLog:
    def run(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def finish(self, *args, **kwargs):
        pass


def start(fn, args=(), kwargs=None):
    try:
        return Call(fn, args, kwargs or {})
    except Exception:
        _debug("mcp.audit.failed")
        return _NoLog()


def unauthorized():
    """HTTP 인증 거부도 한 행. tools/call 외에는 tool=http로 기록한다."""
    call = start(lambda: None)
    if isinstance(call, Call) and call.row["tool"] == "<lambda>":
        call.row["tool"] = "http"
    call.finish({"error": "unauthorized"}, status="unauthorized")


def initialize_call(payload):
    """stateless 연결의 clientInfo를 추정 연결 없이 initialize 자체 행에 남긴다."""
    return start(lambda: None) if isinstance(payload, dict) and payload.get("method") == "initialize" else None


def finish_initialize(call, body, http_status):
    try:
        reply = json.loads(body)
        call.finish(reply.get("result", reply), status="error" if http_status >= 400 or reply.get("error") else None)
    except Exception:
        call.finish({"http_status": http_status}, status="error")
