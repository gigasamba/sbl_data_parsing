"""MCP 감사 기록(op-01): 요청 컨텍스트, 바이트 상한, 결과 키, 비차단 공통 sink.

모든 공개 진입점은 fail-soft다. 도구 반환/예외는 바꾸지 않는다.
result_sha256/bytes는 마스킹 전 전체 JSON 기준, 저장 본문은 마스킹 후 UTF-8 앞부분이다.
"""

import base64
import contextlib
import contextvars
import hashlib
import inspect
import itertools
import json
import queue
import sys
import threading
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from common.core import exitclean, jsonlog, span
from common.store import logsink
from mcp_server import config as mc

_REQUEST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("mcp_audit", default=None)
_LOG = None
_LOG_LOCK = threading.Lock()
_WORKER = None
_WORKER_LOCK = threading.Lock()

_ESTIMATE_MAX_NODES = 65536
_META_TEXT_LIMIT = 2048


def _estimate(value, limit):
    """보관 추정: 문자열은 UTF-8 최대 4바이트/글자, 정수는 실제 크기, 다른 노드는 64바이트.

    입력 복사/인코딩 없이 반복자로 순회한다. 순환·다량의 작은 요소·미지원 객체도
    상한에서 생략한다. 실제 RSS나 SDK 입력 크기의 상한은 아니다.
    """
    size, nodes = 0, 0
    pending = [iter((value,))]
    while pending:
        try:
            item = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        nodes += 1
        if nodes > _ESTIMATE_MAX_NODES:
            return None
        size += sys.getsizeof(item) if isinstance(item, int) and not isinstance(item, bool) else 64
        if isinstance(item, str):
            size += 4 * len(item)
        elif isinstance(item, bytes):
            size += len(item)
        elif isinstance(item, dict):
            pending.append(itertools.chain.from_iterable(item.items()))
        elif isinstance(item, (list, tuple)):
            pending.append(iter(item))
        elif item is not None and not isinstance(item, (bool, int, float)):
            return None
        if size > limit:
            return None
    return size


def _text(value, limit=_META_TEXT_LIMIT):
    # 호출 경로에서 미지원 대형 객체의 str()를 실행하지 않는다.
    if isinstance(value, str):
        # 긴 비밀값의 일부만 남아 값 대조 마스킹을 우회하지 않도록 통째로 생략한다.
        return value if len(value) <= limit else "[audit metadata omitted]"
    return str(value)[:limit] if isinstance(value, (bool, int, float)) else None


def _metadata(row):
    """마스킹 전에 동기 메타의 글자 수를 제한한다. 본문은 전달하지 않는다."""
    safe = dict(row)
    for key in ("request_id", "agent", "user_id", "session_id", "tool", "app_version", "err"):
        if key in safe:
            safe[key] = _text(safe[key])
    return safe


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
        return {
            "chunk_keys": [x.get("chunk_key") for x in hits],  # 목록 순서 = 순위(mc-16 — rank·via 칸 없음)
            **{k: result[k] for k in ("evidence_status", "filter", "scope_docs") if k in result},
        }
    if tool == "list_doc_fulltext":
        b = result.get("batch") or {}
        return {
            **{k: b[k] for k in ("matched", "returned", "next_cursor", "files_total_bytes") if k in b},
            "doc_keys": [d.get("doc_key") for d in result.get("documents", []) if isinstance(d, dict)],
        }
    if tool == "get_doc_fulltext":  # 본문(content)은 빼고 파일 요약만 — 본문은 args/result 상한 안에서 따로 남음
        b = result.get("batch") or {}
        files = [f for f in result.get("files", []) if isinstance(f, dict)]
        return {
            **{k: b[k] for k in ("requested", "ok", "skipped", "total_bytes", "truncated", "json_section") if k in b},
            "files": [{k: f.get(k) for k in ("name", "kind", "size", "sha256", "skip_reason") if f.get(k) is not None} for f in files],
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
        err = _text(result.get("error")) or "tool error"
        if err in ("busy", "unauthorized"):
            return err, err
        if "timeout" in err.lower() or "시간 안에" in err:
            return "timeout", err
        return "error", err
    return "ok", None


@contextlib.contextmanager
def request_context(headers):
    """ASGI 요청 범위. 헤더 우선 user, 없으면 본문을 받은 뒤 update_request가 tools/call params._meta.user로 채운다."""
    request_id = headers.get("x-request-id")
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        request_id = str(uuid4())
    data = {
        "request_id": request_id,
        "agent": (headers.get("x-mcp-client") or "http")[:60],
        "user_id": headers.get("x-mcp-user"),
        "session_id": headers.get("mcp-session-id"),
    }
    token = _REQUEST.set(data)
    try:
        with jsonlog.context(request_id=request_id):
            yield data
    finally:
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
        # 클라이언트 정보는 기록하지 않는다(args에도 남기지 않음).
        data.update(tool="initialize", arguments={k: v for k, v in params.items() if k != "clientInfo"})
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
        self.row = _metadata({"request_id": request_id, "agent": "stdio", **context, "tool": tool})  # HTTP 요청이면 context의 agent가 덮음
        conf = mc.cfg().audit
        self.output_limit = conf.max_output_bytes
        self.input_limit = conf.max_input_bytes
        self.arguments = arguments

    def _prepare(self):
        try:
            text, size, truncated, _ = _body(_input(self.row["tool"], self.arguments), self.input_limit)
            self.row.update(args=text, args_bytes=size, args_truncated=truncated)
        except Exception:
            _debug("mcp.audit.failed", tool=self.row.get("tool"))

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
                    "err": _text(err) or inferred_err,
                    "duration_ms": round((now - self.started) * 1000),
                    "queue_wait_ms": round(((self.thread_started or now) - self.started) * 1000),
                    "app_version": span.app_version(),
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
    """전용 데몬 하나, 대기 64건 및 처리 중 포함 추정 바이트 상한. 초과는 메타만."""

    def __init__(self, capacity=64, max_queue_bytes=None):
        self.max_queue_bytes = mc.cfg().audit.max_queue_bytes if max_queue_bytes is None else max_queue_bytes
        self.pending_bytes = 0
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
        row = _metadata(row)
        size = _estimate((call.arguments, result), self.max_queue_bytes)
        with self.condition:
            try:
                if self.closed or size is None or self.pending_bytes + size > self.max_queue_bytes:
                    raise queue.Full
                self.queue.put_nowait((call, result, row, size))
                self.pending_bytes += size
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
                call, result, row, size = item
                call._write(result, row, self._emit)
            finally:
                # 다음 대기 중 큰 응답의 참조를 유지하지 않는다.
                del item, call, result, row
                with self.condition:
                    self.pending -= 1
                    self.pending_bytes -= size
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
                _, _, _, size = self.queue.get_nowait()
                self.pending_bytes -= size
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
            return {
                "pending": self.pending,
                "pending_bytes": self.pending_bytes,
                "queued": self.queue.qsize(),
                "body_omitted": self.omitted,
                "dropped": self.dropped,
            }


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
    return _WORKER.stats() if _WORKER else {"pending": 0, "pending_bytes": 0, "queued": 0, "body_omitted": 0, "dropped": 0}


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


def http():
    """인증 거부 행의 tool 이름(본문을 받지 않아 도구를 모름)."""


def unauthorized():
    """HTTP 인증 거부도 한 행. tools/call 외에는 tool=http로 기록한다."""
    start(http).finish({"error": "unauthorized"}, status="unauthorized")


def initialize_call(payload):
    """initialize 요청을 자체 행으로 남긴다(clientInfo는 빼고 기록)."""
    return start(lambda: None) if isinstance(payload, dict) and payload.get("method") == "initialize" else None


def finish_initialize(call, body, http_status):
    try:
        reply = json.loads(body)
        call.finish(reply.get("result", reply), status="error" if http_status >= 400 or reply.get("error") else None)
    except Exception:
        call.finish({"http_status": http_status}, status="error")
