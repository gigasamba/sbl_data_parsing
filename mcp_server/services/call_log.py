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
import queue
import sys
import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from common import pipeline_version
from common.core import exitclean, jsonlog
from common.store import logsink
from mcp_server import config as mc
from mcp_server.services.search.server_state import CALLER

_REQUEST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("mcp_audit", default=None)
_LOG = None
_LOG_LOCK = threading.Lock()
_WORKER = None
_WORKER_LOCK = threading.Lock()


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


def _body(value, limit):
    encoder = json.JSONEncoder(ensure_ascii=False, default=str)
    digest, size = hashlib.sha256(), 0
    for chunk in encoder.iterencode(value):
        for offset in range(0, len(chunk), 65536):
            raw = chunk[offset : offset + 65536].encode("utf-8")
            digest.update(raw)
            size += len(raw)
    saved, safe_size = bytearray(), 0
    for chunk in encoder.iterencode(jsonlog.masked(value)):
        for offset in range(0, len(chunk), 65536):
            raw = chunk[offset : offset + 65536].encode("utf-8")
            saved.extend(raw[: max(0, limit - len(saved))])
            safe_size += len(raw)
    return saved.decode("utf-8", errors="ignore"), size, safe_size > limit, digest.hexdigest()


def _input(tool, args):
    args = dict(args)
    if tool == "parse_document" and args.get("content_b64") is not None:
        encoded = str(args["content_b64"])
        digest, size = hashlib.sha256(), 0
        try:
            for offset in range(0, len(encoded), 65536):
                chunk = encoded[offset : offset + 65536]
                if "=" in chunk and offset + len(chunk) < len(encoded):
                    raise ValueError("non-final padding")
                raw = base64.b64decode(chunk, validate=True)
                digest.update(raw)
                size += len(raw)
            kind = "decoded"
        except ValueError:
            digest, size, kind = hashlib.sha256(), 0, "encoded_invalid"
            for offset in range(0, len(encoded), 65536):
                raw = encoded[offset : offset + 65536].encode("utf-8")
                digest.update(raw)
                size += len(raw)
        args["content_b64"] = {"sha256": digest.hexdigest(), "bytes": size, "representation": kind}
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
    update_request(data, payload)
    token = _REQUEST.set(data)
    caller_token = CALLER.set("mcp:" + data["agent"])
    try:
        with jsonlog.context(request_id=request_id):
            yield data
    finally:
        CALLER.reset(caller_token)
        _REQUEST.reset(token)


def update_request(data, payload):
    """상한 안에서 수신한 JSON의 감사 메타데이터만 현재 요청 dict에 반영."""
    if not isinstance(payload, dict):
        return
    params = payload.get("params")
    params = params if isinstance(params, dict) else {}
    meta = params.get("_meta")
    if not data.get("user_id") and isinstance(meta, dict):
        data["user_id"] = meta.get("user")
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
        self.input_limit = conf.max_input_bytes
        self.arguments = arguments
        self.prepared = False

    def _prepare(self):
        if not self.prepared:
            try:
                text, size, truncated, _ = _body(_input(self.row["tool"], self.arguments), self.input_limit)
                self.row.update(args=text, args_bytes=size, args_truncated=truncated)
            except Exception:
                _debug("mcp.audit.failed", tool=self.row.get("tool"))
            self.prepared = True

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
        """시각/상태를 호출 시 확정하고 본문 처리를 전용 워커에 맡긴다(대기 없음)."""
        try:
            with self.lock:
                if self.done:
                    return
                self.done = True
                now = time.perf_counter()
                inferred, inferred_err = _status(result)
                self.abandoned = status == "timeout" and self.thread_started is not None and self.thread_ended is None
                row = {
                    **self.row,
                    "ts": self.ts,
                    "status": status or inferred,
                    "err": err or inferred_err,
                    "duration_ms": round((now - self.started) * 1000),
                    "queue_wait_ms": round(((self.thread_started or now) - self.started) * 1000),
                    "app_version": pipeline_version(),
                }
            _worker().submit(self, result, row)
        except Exception:
            # 기록 실패는 업무 응답/예외에 전파하지 않는다.
            pass

    def _write(self, result, row, emit):
        try:
            self._prepare()
            text, size, truncated, digest = _body(result, self.output_limit)
            row.update(
                **{k: self.row[k] for k in ("args", "args_bytes", "args_truncated") if k in self.row},
                result=text,
                result_bytes=size,
                result_truncated=truncated,
                result_sha256=digest,
                result_keys=result_keys(self.row["tool"], result),
            )
            # 원본 args/result는 읽기만 한다. 공통 sink가 DB/대체 파일을 맡는다.
            emit(jsonlog.masked(row))
            if row["status"] == "timeout":
                _debug("mcp.thread.abandoned", request_id=row["request_id"], running=self.abandoned, ended_at=self.thread_ended)
            with jsonlog.context(request_id=row["request_id"]):
                _logger().info("%s %s", row["tool"], row["status"], extra={"event": "mcp.call", "duration_ms": row["duration_ms"]})
        except Exception:
            _debug("mcp.audit.failed", tool=self.row.get("tool"))


class Worker:
    """전용 데몬 하나, 본문 대기 최대 64건. 포화 시 본문 없는 메타만 비차단 sink로."""

    def __init__(self, capacity=64):
        self.queue = queue.Queue(maxsize=capacity)
        self.condition = threading.Condition()
        self.pending = 0
        self.omitted = 0
        self.dropped = 0
        self.closed = False
        self.expired = False
        self.active = False
        self.thread = threading.Thread(target=self._run, name="mcp-audit", daemon=True)
        exitclean.on_exit(self._close_at_exit, timeout=jsonlog.cfg().log.shutdown_sec, priority=-10)
        self.thread.start()

    def submit(self, call, result, row):
        with self.condition:
            try:
                if self.closed:
                    raise queue.Full
                self.queue.put_nowait((call, result, row))
                self.pending += 1
                self.condition.notify_all()
                return
            except queue.Full:
                self.omitted += 1
        # 포화 시 본문을 붙잡지 않는다. sink 자체 포화는 기존 dropped 집계.
        row.update(
            args=None,
            result=None,
            args_truncated=True,
            result_truncated=True,
            result_keys={"audit_body_omitted": "queue_full"},
            err="audit_queue_full",
        )
        logsink.emit("mcp_call", jsonlog.masked(row))

    def _run(self):
        while True:
            with self.condition:
                while not self.pending and not self.closed:
                    self.condition.wait()
                if self.closed and not self.pending:
                    return
                item = self.queue.get_nowait()
                self.active = True
            try:
                call, result, row = item
                call._write(result, row, self._emit)
            finally:
                # 다음 대기 중 큰 응답의 참조를 유지하지 않는다.
                del item, call, result, row
                with self.condition:
                    self.pending -= 1
                    self.active = False
                    self.condition.notify_all()

    def drain(self, *, deadline=None):
        deadline = deadline if deadline is not None else time.monotonic() + jsonlog.cfg().log.shutdown_sec
        with self.condition:
            while self.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
        return True

    def close(self, *, deadline=None):
        deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + jsonlog.cfg().log.shutdown_sec)
        if not self.condition.acquire(timeout=max(0, deadline - time.monotonic())):
            return False
        try:
            self.closed = True
            self.condition.notify_all()
        finally:
            self.condition.release()
        self.thread.join(timeout=max(0, deadline - time.monotonic()))
        with self.condition:
            if self.active and not self.expired:
                self.dropped += 1
                self.expired = True
            while not self.queue.empty():
                self.queue.get_nowait()
                self.pending -= 1
                self.dropped += 1
        return True

    def _emit(self, row):
        with self.condition:
            if self.expired:
                return
        logsink.emit("mcp_call", row)

    def _close_at_exit(self, *, deadline):
        if self.close(deadline=deadline) is False:
            return False
        # drain 도중 처음 생성된 sink도 같은 deadline에 비운다.
        return logsink.shutdown(deadline=deadline)

    def stats(self):
        with self.condition:
            return {"pending": self.pending, "queued": self.queue.qsize(), "body_omitted": self.omitted, "dropped": self.dropped}


def _worker():
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = Worker()
        return _WORKER


def drain(*, deadline=None):
    """시험/명시 flush 전용. 도구 응답 경로에서는 호출하지 않는다."""
    return _WORKER.drain(deadline=deadline) if _WORKER else True


def stats():
    return _WORKER.stats() if _WORKER else {"pending": 0, "queued": 0, "body_omitted": 0, "dropped": 0}


class _NoLog:
    def _prepare(self):
        pass

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


def finish(call, *args, **kwargs):
    """감사 처리를 대기하지 않고 전용 워커에 제출한다(anyio limiter와 독립)."""
    call.finish(*args, **kwargs)


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
