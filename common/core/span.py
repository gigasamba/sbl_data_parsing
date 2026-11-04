"""파이프라인 성능·추적 span(op-01) — 문서×단계 1건 = applog.pipe_event 1행.

    with span("extract.parse", doc_id=name, engine="pdfplumber") as s:
        ...
        s.add(pages=12)             # metrics(숫자는 더해짐) — s.observe("vlm_ms", 830)은 n·sum·max·p50으로 요약
        s.set(attempt=2)            # 열(engine·model·attempt·doc_id·ext·file_bytes·seq·total·cpu_ms·rss_peak_mb …)
        s.result("reused")          # 기본 ok · 예외는 fail/timeout + err_kind(classify)로 기록하고 다시 던짐

run_id가 없으면(MCP 검색·시험) span()은 아무것도 하지 않는 가짜 span을 돌려준다(DB·스레드·로그 0).
run_id/span_id는 common.core.jsonlog 컨텍스트를 그대로 쓴다. 자식 프로세스는 resources.gated_popen이
APPLOG_CONTEXT 내부 신호로 현재 ID를 이어준다(with_context). 스레드 풀은 contextvars를 안 물려주므로
carry(fn)로 감싼다. 행은 INFO 로그의 log_table/log_row extra로 내보내 T0 logsink가 DB에 쓴다.
개별 호출은 DEBUG 로그만(debug_event) — span.metrics에 요약.
cpu_ms·rss_peak_mb는 span(cpu=True)처럼 프로세스에서 하나만 도는 span만 잰다(스레드로 겹치면 섞이므로 기본 끔).
cpu_ms 범위: 이 프로세스(RUSAGE_SELF) + 그 사이에 끝나 회수된(wait) 자식 프로세스(RUSAGE_CHILDREN)의 CPU 시간 합 —
subprocess 작업도 들어간다. 같은 프로세스에서 cpu=True span이 겹쳐 돌면(서로 조상이 아닌 경우) 어느 쪽 몫인지 가를 수 없어 둘 다 NULL.
Windows(resource 없음)·측정 실패도 NULL — 0으로 채우지 않는다. 아직 안 끝난 자식·손자 프로세스의 CPU는 들어가지 않는다.
문서 본문은 넣지 않는다: err는 예외 타입 이름(+errno 이름)과 safe()로 표시한 우리 코드의 고정 문구만 저장한다(allowlist).
외부 라이브러리·파서 예외 문자열 원문은 저장하지 않는다.
계측은 fail-soft: 측정·기록의 어떤 예외도 업무 코드에 전파되지 않고(업무 예외는 원래 그대로 다시 던짐) soft_fail이 프로세스당 1회
stderr 경고 + failure_count()로만 남긴다.
"""

import contextlib
import errno
import functools
import json
import logging
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from common.core import jsonlog

try:
    import resource
except ImportError:  # Windows — cpu_ms·rss_peak_mb는 None으로 남김(OS 분기는 이 파일 한 곳)
    resource = None  # type: ignore[assignment]  # Windows에는 resource 모듈이 없음

STATUSES = ("ok", "fail", "timeout", "skip", "reused")
ERR_KINDS = ("env", "timeout", "doc", "external", "db")
COLUMNS = (
    "engine",
    "model",
    "attempt",
    "doc_id",
    "ext",
    "file_bytes",
    "seq",
    "total",
    "wait_mem_ms",
    "wait_cpu_ms",
    "cpu_ms",
    "ext_call_ms",
    "rss_peak_mb",
)
USAGE_PREFIX = "@@applog-usage "  # parse_one가 stdout 끝에 남기는 자원 사용 한 줄(부모 span이 읽음)
_ADD_COLUMNS = ("wait_mem_ms", "wait_cpu_ms", "ext_call_ms", "cpu_ms")  # set()하면 더해지는 열(재시도·여러 호출의 합)
_SAMPLES = 512  # observe가 p50 계산용으로 들고 있는 표본 상한(n·sum·max는 정확)
_QUOTED = re.compile(r"""(['"])((?:(?!\1).){30,})\1""", re.S)

_OPEN: dict[str, "Span"] = {}
_CPU_OPEN: dict[str, "Span"] = {}  # cpu=True로 열린 span — 서로 겹치면 cpu_ms를 NULL로
_LOCK = threading.Lock()
_STATE: dict = {"log": None, "version": None, "cpus": None, "retry_at": 0.0}
_RETRY_SEC = 30  # 로그 설정(디렉터리 권한·디스크)이 실패하면 이 시간 동안은 다시 열어 보지 않음
_FAIL: dict = {"count": 0, "warned": False}
_FAIL_LOCK = threading.Lock()
_LEAD = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]{0,80}(?:Error|Exception|Timeout|Expired|Exit|Interrupt|Unavailable|Exceeded|Exists))\b")


class Safe(str):
    """우리 코드가 직접 쓴 고정 문구(문서·외부 라이브러리 글자 없음) 표시 — result()가 이것만 그대로 저장한다."""


def safe(text):
    """고정 문구를 Safe로(비면 None). 변수는 정수·열거값처럼 안전한 것만 f-string에 넣을 것."""
    return Safe(text) if text else None


def soft_fail(where, ex):
    """계측 안의 예외 처리 — 삼키고 카운트, 프로세스당 1회만 stderr 경고. 예외 글자는 쓰지 않는다(타입·errno만)."""
    try:
        with _FAIL_LOCK:
            _FAIL["count"] += 1
            first, _FAIL["warned"] = not _FAIL["warned"], True
        if first:
            sys.stderr.write(f"[applog] 계측 실패(무시하고 계속 · 이 경고는 1회): {where}: {exc_label(ex)}\n")
    except Exception:  # stderr까지 막혀도 업무 코드를 건드리지 않음
        pass


def failure_count():
    """이 프로세스에서 삼킨 계측 실패 수."""
    return _FAIL["count"]


def _soft_method(fn):
    """Span 메서드 — 예외를 삼키고 self를 돌려줌(체인 호출 `sp.add(..).observe(..)`이 안 끊기게)."""

    @functools.wraps(fn)
    def inner(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as ex:
            soft_fail(fn.__qualname__, ex)
            return self

    return inner


def _soft_fn(fn):
    """모듈 함수 — 예외를 삼키고 None."""

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as ex:
            soft_fail(fn.__qualname__, ex)
            return None

    return inner


def _try(where, fn, *args):
    try:
        return fn(*args)
    except Exception as ex:
        soft_fail(where, ex)
        return None


def redact_text(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림 — run_all.redact(runs.jsonl용)가 쓴다.
    ponytail: 완벽하지 않음(인용부호 없는 echo는 못 잡음) — 그래서 span/pipe_event의 err는 이 함수가 아니라 safe_err(allowlist)를 쓴다."""
    return _QUOTED.sub(lambda m: m.group(1) + "…[가림]…" + m.group(1), s or "")


def exc_label(ex):
    """예외 → 저장해도 되는 짧은 글자: 타입 이름 + (OSError면 errno 이름 · CalledProcessError면 종료 코드 · SystemExit면 코드).
    예외 메시지 원문은 문서 내용을 echo할 수 있어 쓰지 않는다."""
    name = type(ex).__name__
    detail = None
    if isinstance(ex, OSError) and ex.errno in errno.errorcode:
        detail = errno.errorcode[ex.errno]
    elif isinstance(ex, subprocess.CalledProcessError) and isinstance(ex.returncode, int):
        detail = f"rc={ex.returncode}"
    elif isinstance(ex, SystemExit) and isinstance(ex.code, int):
        detail = f"code={ex.code}"
    return f"{name}[{detail}]" if detail else name


def safe_err(err):
    """result()·instant()의 err 인자 → 저장할 글자 또는 None(allowlist).
    Safe(우리 고정 문구)만 그대로(200자까지), 예외 객체는 exc_label, 그 밖의 글자는 맨 앞의 예외 클래스 이름만 남김(없으면 None)."""
    if not err:
        return None
    if isinstance(err, BaseException):
        return exc_label(err)
    if isinstance(err, Safe):
        return str(err)[:200]
    m = _LEAD.match(str(err))
    return m.group(1) if m else None


def classify(ex):
    """예외 → (status, err_kind). 이름·모듈로 가른다: 시간 초과=timeout, 미설치·미설정=env, 모델·네트워크=external, DB=db, 그 밖=doc."""
    names = {c.__name__ for c in type(ex).__mro__}
    module = type(ex).__module__ or ""
    if names & {"TimeoutError", "TimeoutExpired"}:
        return "timeout", "timeout"
    if names & {"ImportError", "ModuleNotFoundError"}:
        return "fail", "env"
    if module.startswith(("psycopg", "sqlalchemy", "sqlite3")) or names & {"OperationalError", "DatabaseError"}:
        return "fail", "db"
    if names & {"ModelUnavailable", "LLMUnavailable", "URLError", "HTTPError", "ConnectionError", "BudgetExceeded"}:
        return "fail", "external"
    return "fail", "doc"


def app_version():
    if _STATE["version"] is None:
        from common.core.fingerprint import pipeline_version

        _STATE["version"] = pipeline_version()
    return _STATE["version"]


def _load1_per_cpu():
    """1분 부하 평균 ÷ 코어 수(cgroup 반영) — 측정 못 하면 None(Windows)."""
    from common.core import resources as RS

    load = RS._loadavg1()
    if load is None:
        return None
    if _STATE["cpus"] is None:
        _STATE["cpus"] = RS.cpus()
    return round(load / max(1, _STATE["cpus"]), 3)


def mem_pct():
    from common.core import resources as RS

    pct = RS.mem_used_pct()
    return None if pct is None else round(pct, 1)


def proc_usage():
    """{cpu_ms, rss_peak_mb} — cpu_ms는 이 프로세스 + 이미 끝나 회수된 자식들의 CPU 시간 합(RUSAGE_SELF+CHILDREN, 누적값),
    rss_peak_mb는 이 프로세스의 최대 상주 메모리. resource가 없으면 빈 사전."""
    if resource is None:
        return {}
    me, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    rss = me.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)  # macOS는 바이트, Linux는 KB
    cpu = me.ru_utime + me.ru_stime + kids.ru_utime + kids.ru_stime
    return {"cpu_ms": int(cpu * 1000), "rss_peak_mb": round(rss, 1)}


def usage_line():
    """parse_one가 끝에 찍는 한 줄 — 부모가 read_usage로 자기 span(extract.parse)에 옮김. 측정 실패면 빈 사전."""
    return USAGE_PREFIX + json.dumps(_try("proc_usage", proc_usage) or {})


def read_usage(text):
    """자식 stdout 글자에서 usage_line 사전을 찾아 돌려줌(없거나 깨졌으면 {})."""
    for line in reversed((text or "").splitlines()):
        if line.startswith(USAGE_PREFIX):
            try:
                value = json.loads(line[len(USAGE_PREFIX) :])
            except ValueError:
                return {}
            return value if isinstance(value, dict) else {}
    return {}


def _logger():
    """앱 logger — 열기에 실패하면(로그 디렉터리 권한·디스크) None을 돌려주고 _RETRY_SEC 뒤에 다시 시도."""
    log = _STATE["log"]
    if log is not None:
        return log
    with _LOCK:
        if _STATE["log"] is None:
            now = time.monotonic()
            if now < _STATE["retry_at"]:
                return None
            try:
                _STATE["log"] = jsonlog.setup("pipeline")  # 자식 프로세스도 첫 span에서 스스로 sink를 연다
            except Exception as ex:
                _STATE["retry_at"] = now + _RETRY_SEC
                soft_fail("logger.setup", ex)
                return None
        return _STATE["log"]


def _emit(row, level=logging.INFO):
    log = _logger()
    if log is None:
        return
    log.log(
        level,
        f"{row['stage']} {row['status']}" + (f" {row['doc_id']}" if row.get("doc_id") else ""),
        extra={
            "event": row["stage"],
            "duration_ms": row.get("duration_ms"),
            "err": row.get("err"),
            "log_table": "pipe_event",
            "log_row": row,
            "log_context": {"run_id": row["run_id"], "span_id": row["span_id"]},
        },
    )


@_soft_fn
def debug_event(event, msg="", **fields):
    """개별 호출 기록 — DEBUG에서만(INFO에선 span.metrics 요약만). DB에는 안 감."""
    log = _logger() if jsonlog.get_context().get("run_id") else None
    if log is not None and log.isEnabledFor(logging.DEBUG):
        log.debug((msg or event) + (" " + json.dumps(fields, ensure_ascii=False, default=str) if fields else ""), extra={"event": event})


@_soft_fn
def call_event(stage, ms, exc=None, **metrics):
    """모델 호출 1건 = pipe_event 1행(이슈 #117) — 성공·실패 모두. 열린 span의 metrics 합산(_traced)과 별개로 호출마다 남겨
    어느 호출이 느리거나 실패했는지 본다. 부모 = 지금 열린 span(없으면 컨텍스트의 span_id), doc_id·ext는 그 span에서 이어받음. layer는 model — 층 합계에서 빠짐(부모와 이중 집계)."""
    ids = jsonlog.get_context()
    if not ids.get("run_id"):
        return
    parent = current()
    status, kind = ("ok", None) if exc is None else classify(exc)
    now = datetime.now(UTC)
    row = {
        "ts_start": now - timedelta(milliseconds=ms),
        "ts_end": now,
        "run_id": ids["run_id"],
        "span_id": str(uuid.uuid4()),
        "parent_id": parent.span_id if parent is not None else ids.get("span_id"),
        "layer": "model",
        "stage": stage,
        "duration_ms": int(ms),
        "metrics": jsonlog.masked(metrics) or None,
        "status": status,
        "err_kind": kind,
        "err": jsonlog.masked(exc_label(exc)) if exc is not None else None,
        "app_version": _try("app_version", app_version),
    }
    for key in COLUMNS:
        row[key] = parent.cols.get(key) if parent is not None and key in ("doc_id", "ext") else None
    _emit(row)


class _Null:
    """run_id가 없을 때 span이 돌려주는 가짜 — 모든 호출이 아무 일도 안 함."""

    span_id = None

    def set(self, **cols):
        return self

    def add(self, **metrics):
        return self

    def observe(self, name, value):
        return self

    def add_wait(self, mem_ms=0, cpu_ms=0):
        return self

    def rows(self, count):
        return self

    def ext_call(self, ms):
        return self

    def result(self, status, err_kind=None, err=None):
        return self


NULL = _Null()


class Span:
    def __init__(self, stage, layer, cols, cpu):
        self.stage, self.layer = stage, layer
        ids = jsonlog.get_context()
        self.run_id, self.parent_id = ids.get("run_id"), ids.get("span_id")
        self.span_id = str(uuid.uuid4())
        self.cols: dict = {}
        self.metrics: dict = {}
        self._obs: dict = {}
        self.inflight = 1
        self._t0 = time.monotonic()
        self._status, self._err_kind, self._err = "ok", None, None
        self._lock = threading.Lock()
        self._cpu = cpu
        self.cpu_overlap = False  # cpu=True span끼리 겹쳤으면 True → cpu_ms NULL
        self.set(**cols)

    @_soft_method
    def set(self, **cols):
        for key, value in cols.items():
            if key in COLUMNS and key not in _ADD_COLUMNS and key != "rss_peak_mb":
                self.cols[key] = value
            elif key in _ADD_COLUMNS:
                self.add_col(key, value)
            elif key == "rss_peak_mb":
                self.cols[key] = max(self.cols.get(key) or 0, value)
            else:
                self.add(**{key: value})
        return self

    @_soft_method
    def add_col(self, key, value):
        with self._lock:
            self.cols[key] = (self.cols.get(key) or 0) + int(value)

    @_soft_method
    def add(self, **metrics):
        with self._lock:
            for key, value in metrics.items():
                old = self.metrics.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(old, (int, float)):
                    self.metrics[key] = old + value
                else:
                    self.metrics[key] = value
        return self

    @_soft_method
    def observe(self, name, value):
        with self._lock:
            entry = self._obs.setdefault(name, [0, 0.0, 0.0, []])
            entry[0] += 1
            entry[1] += value
            entry[2] = max(entry[2], value)
            if len(entry[3]) < _SAMPLES:
                entry[3].append(value)
        return self

    @_soft_method
    def rows(self, count):
        """적재·내보내기 처리량 — rows·rows_per_sec(span 시작부터)."""
        elapsed = max(1e-6, time.monotonic() - self._t0)
        self.add(rows=count, rows_per_sec=round(count / elapsed, 1))
        return self

    @_soft_method
    def add_wait(self, mem_ms=0, cpu_ms=0):
        """gated_popen의 메모리 문·CPU 문 대기(ms) — 작업 시간과 분리해 쌓음."""
        self.add_col("wait_mem_ms", mem_ms)  # 0도 기록 — NULL은 '재지 않음', 0은 '기다릴 일 없었음'
        self.add_col("wait_cpu_ms", cpu_ms)
        return self

    @_soft_method
    def ext_call(self, ms):
        """외부 호출(모델·HTTP·DB) 대기 합(ms) → ext_call_ms 열."""
        self.add_col("ext_call_ms", ms)
        return self

    def result(self, status, err_kind=None, err=None):
        if status not in STATUSES or (err_kind is not None and err_kind not in ERR_KINDS):
            raise ValueError("pipe_event status/err_kind")
        self._status, self._err_kind = status, err_kind
        self._err = safe_err(err)
        return self

    def _finish_metrics(self):
        out = dict(self.metrics)
        for name, (n, total, high, samples) in self._obs.items():
            ordered = sorted(samples)
            out[f"{name}_n"] = n
            out[f"{name}_sum"] = round(total, 1)
            out[f"{name}_max"] = round(high, 1)
            out[f"{name}_p50"] = round(ordered[len(ordered) // 2], 1) if ordered else None
        return out


@contextlib.contextmanager
def span(stage, layer=None, *, cpu=False, **cols):
    """문서×단계 span. layer 기본은 stage의 앞 토큰(extract.parse → extract). 업무 예외는 기록한 뒤 원래 그대로 던진다.
    계측(시작 측정·종료 기록)의 예외는 모두 안에서 삼킨다 — 정상 결과를 바꾸지 않고 업무 예외를 덮지 않는다."""
    if not jsonlog.get_context().get("run_id"):
        yield NULL
        return
    began = _begin(stage, layer, cols, cpu)
    if began is None:  # 시작 계측 실패 — 가짜 span으로 업무만 진행
        yield NULL
        return
    sp, token, start_wall, start_mono, usage0, load0 = began
    try:
        yield sp
    except BaseException as ex:
        _note_exception(sp, ex)
        raise
    finally:
        _end(sp, token, start_wall, start_mono, usage0, load0)


def _begin(stage, layer, cols, cpu):
    sp = token = None
    try:
        sp = Span(stage, layer or stage.split(".", 1)[0], cols, cpu)
        start_wall, start_mono = datetime.now(UTC), time.monotonic()
        usage0 = (_try("proc_usage", proc_usage) or {}) if cpu else {}
        load0 = _try("load1", _load1_per_cpu)
        with _LOCK:
            sp.inflight = 1 + sum(1 for s in _OPEN.values() if s.stage == stage)
            _OPEN[sp.span_id] = sp
            if cpu:
                _register_cpu(sp)
        token = jsonlog.set_context(span_id=sp.span_id)
        return sp, token, start_wall, start_mono, usage0, load0
    except Exception as ex:
        soft_fail("span.begin", ex)
        _unregister(sp)
        if token is not None:
            _try("context.reset", jsonlog.reset_context, token)
        return None


def _register_cpu(sp):
    """_LOCK 안에서. 열려 있는 다른 cpu span(내 조상 제외)과 겹치면 서로 cpu_ms를 못 가르므로 둘 다 표시."""
    ancestors, cur = set(), sp.parent_id
    while cur and cur in _OPEN and cur not in ancestors:
        ancestors.add(cur)
        cur = _OPEN[cur].parent_id
    for other_id, other in _CPU_OPEN.items():
        if other_id not in ancestors:
            other.cpu_overlap = sp.cpu_overlap = True
    _CPU_OPEN[sp.span_id] = sp


def _unregister(sp):
    if sp is not None:
        with _LOCK:
            _OPEN.pop(sp.span_id, None)
            _CPU_OPEN.pop(sp.span_id, None)


def _note_exception(sp, ex):
    try:
        status, kind = classify(ex)
        if sp._status == "ok" and not (isinstance(ex, SystemExit) and ex.code in (0, None)):  # 안에서 이미 result()를 정했으면 그대로
            sp._status, sp._err_kind, sp._err = status, kind, exc_label(ex)
    except Exception as ex2:
        soft_fail("span.note_exception", ex2)


def _end(sp, token, start_wall, start_mono, usage0, load0):
    try:
        _try("context.reset", jsonlog.reset_context, token)
        _unregister(sp)
        _finish(sp, start_wall, start_mono, usage0, load0)
    except Exception as ex:
        soft_fail("span.end", ex)


def _finish(sp, start_wall, start_mono, usage0, load0):
    cols = sp.cols
    if sp._cpu:
        now = _try("proc_usage", proc_usage) if usage0 else None
        if now:
            cols["cpu_ms"] = None if sp.cpu_overlap else now["cpu_ms"] - usage0["cpu_ms"]  # 겹침은 NULL(0으로 오해하지 않게)
            cols["rss_peak_mb"] = now["rss_peak_mb"]
        else:
            cols["cpu_ms"] = None
    row = {
        "ts_start": start_wall,
        "ts_end": datetime.now(UTC),
        "run_id": sp.run_id,
        "span_id": sp.span_id,
        "parent_id": sp.parent_id,
        "layer": sp.layer,
        "stage": sp.stage,
        "duration_ms": int((time.monotonic() - start_mono) * 1000),
        "load1_per_cpu_start": load0,
        "load1_per_cpu_end": _try("load1", _load1_per_cpu),
        "mem_used_pct": _try("mem_pct", mem_pct),
        "inflight": sp.inflight,
        "metrics": jsonlog.masked(_try("metrics", sp._finish_metrics) or {}) or None,
        "status": sp._status,
        "err_kind": sp._err_kind,
        "err": jsonlog.masked(sp._err),
        "app_version": _try("app_version", app_version),
    }
    for key in COLUMNS:
        row[key] = cols.get(key)
    _emit(row)


@_soft_fn
def current():
    """지금 컨텍스트의 열린 span(없으면 None) — common/ai·resources가 지표를 더할 때 씀."""
    if not _OPEN:
        return None
    return _OPEN.get(jsonlog.get_context().get("span_id"))


@_soft_fn
def result_current(status, err_kind=None, err=None):
    sp = current()
    if sp is not None:
        sp.result(status, err_kind, err)


@_soft_fn
def add_current(**metrics):
    sp = current()
    if sp is not None:
        sp.add(**metrics)


@_soft_fn
def observe_current(name, value):
    sp = current()
    if sp is not None:
        sp.observe(name, value)


def open_counts():
    """이 프로세스에서 열려 있는 span 수를 stage별로 — run.progress의 '단계별 진행 중 개수'."""
    with _LOCK:
        counts: dict = {}
        for sp in _OPEN.values():
            counts[sp.stage] = counts.get(sp.stage, 0) + 1
    return counts


def carry(fn):
    """스레드 풀에 넘길 fn이 만든 시점의 run/span 컨텍스트에서 돌게 감쌈(풀 스레드는 contextvars를 안 물려받음)."""
    ids = jsonlog.get_context()

    @functools.wraps(fn)
    def run(*args, **kwargs):
        with jsonlog.context(**{k: v for k, v in ids.items() if v}):
            return fn(*args, **kwargs)

    return run


def with_context(kwargs):
    """Popen kwargs에 현재 run/span ID(내부 신호 APPLOG_CONTEXT)를 env로 이어 붙인 사본 — run_id 없으면 그대로. 실패하면 원래 kwargs."""
    try:
        if not jsonlog.get_context().get("run_id"):
            return kwargs
        from common.config import settings

        return {**kwargs, "env": settings.child_env(kwargs.get("env"))}  # 상관 ID는 child_env가 싣는다
    except Exception as ex:
        soft_fail("with_context", ex)
        return kwargs
