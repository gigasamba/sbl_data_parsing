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
문서 본문은 넣지 않는다: 오류 글자는 redact_text(인용부호로 감싼 긴 조각을 가림)를 거친다.
"""

import contextlib
import functools
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

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
_LOCK = threading.Lock()
_STATE: dict = {"log": None, "version": None, "cpus": None}


def redact_text(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림 — run_all.redact가 이 함수를 쓴다.
    ponytail: 완벽하지 않음(인용부호 없는 echo는 못 잡음)."""
    return _QUOTED.sub(lambda m: m.group(1) + "…[가림]…" + m.group(1), s or "")


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


def _app_version():
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


def _mem_pct():
    from common.core import resources as RS

    pct = RS.mem_used_pct()
    return None if pct is None else round(pct, 1)


def proc_usage():
    """이 프로세스(자식 제외)의 {cpu_ms, rss_peak_mb} — resource가 없으면 빈 사전."""
    if resource is None:
        return {}
    ru = resource.getrusage(resource.RUSAGE_SELF)
    rss = ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)  # macOS는 바이트, Linux는 KB
    return {"cpu_ms": int((ru.ru_utime + ru.ru_stime) * 1000), "rss_peak_mb": round(rss, 1)}


def usage_line():
    """parse_one가 끝에 찍는 한 줄 — 부모가 read_usage로 자기 span(extract.parse)에 옮김."""
    return USAGE_PREFIX + json.dumps(proc_usage())


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
    log = _STATE["log"]
    if log is None:
        with _LOCK:
            if _STATE["log"] is None:
                _STATE["log"] = jsonlog.setup("pipeline")  # 자식 프로세스도 첫 span에서 스스로 sink를 연다
            log = _STATE["log"]
    return log


def _emit(row, level=logging.INFO):
    err = row.get("err")
    _logger().log(
        level,
        f"{row['stage']} {row['status']}" + (f" {row['doc_id']}" if row.get("doc_id") else ""),
        extra={
            "event": row["stage"],
            "duration_ms": row.get("duration_ms"),
            "err": err,
            "log_table": "pipe_event",
            "log_row": row,
            "log_context": {"run_id": row["run_id"], "span_id": row["span_id"]},
        },
    )


def debug_event(event, msg="", **fields):
    """개별 호출 기록 — DEBUG에서만(INFO에선 span.metrics 요약만). DB에는 안 감."""
    log = _logger() if jsonlog.get_context().get("run_id") else None
    if log is not None and log.isEnabledFor(logging.DEBUG):
        log.debug((msg or event) + (" " + json.dumps(fields, ensure_ascii=False, default=str) if fields else ""), extra={"event": event})


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

    def rows(self, count, nbytes=None):
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
        self.set(**cols)

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

    def add_col(self, key, value):
        with self._lock:
            self.cols[key] = (self.cols.get(key) or 0) + int(value)

    def add(self, **metrics):
        with self._lock:
            for key, value in metrics.items():
                old = self.metrics.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(old, (int, float)):
                    self.metrics[key] = old + value
                else:
                    self.metrics[key] = value
        return self

    def observe(self, name, value):
        with self._lock:
            entry = self._obs.setdefault(name, [0, 0.0, 0.0, []])
            entry[0] += 1
            entry[1] += value
            entry[2] = max(entry[2], value)
            if len(entry[3]) < _SAMPLES:
                entry[3].append(value)
        return self

    def rows(self, count, nbytes=None):
        """적재·내보내기 처리량 — rows·rows_per_sec(span 시작부터)·bytes."""
        elapsed = max(1e-6, time.monotonic() - self._t0)
        self.add(rows=count, rows_per_sec=round(count / elapsed, 1))
        if nbytes is not None:
            self.add(bytes=nbytes)
        return self

    def add_wait(self, mem_ms=0, cpu_ms=0):
        """gated_popen의 메모리 문·CPU 문 대기(ms) — 작업 시간과 분리해 쌓음."""
        self.add_col("wait_mem_ms", mem_ms)  # 0도 기록 — NULL은 '재지 않음', 0은 '기다릴 일 없었음'
        self.add_col("wait_cpu_ms", cpu_ms)
        return self

    def ext_call(self, ms):
        """외부 호출(모델·HTTP·DB) 대기 합(ms) → ext_call_ms 열."""
        self.add_col("ext_call_ms", ms)
        return self

    def result(self, status, err_kind=None, err=None):
        if status not in STATUSES or (err_kind is not None and err_kind not in ERR_KINDS):
            raise ValueError("pipe_event status/err_kind")
        self._status, self._err_kind = status, err_kind
        self._err = redact_text(str(err))[:500] if err else None
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
    """문서×단계 span. layer 기본은 stage의 앞 토큰(extract.parse → extract). 예외는 기록한 뒤 그대로 던진다."""
    if not jsonlog.get_context().get("run_id"):
        yield NULL
        return
    sp = Span(stage, layer or stage.split(".", 1)[0], cols, cpu)
    start_wall, start_mono = datetime.now(UTC), time.monotonic()
    usage0 = proc_usage() if cpu else {}
    load0 = _load1_per_cpu()
    with _LOCK:
        sp.inflight = 1 + sum(1 for s in _OPEN.values() if s.stage == stage)
        _OPEN[sp.span_id] = sp
    token = jsonlog.set_context(span_id=sp.span_id)
    try:
        yield sp
    except BaseException as ex:
        status, kind = classify(ex)
        if sp._status == "ok" and not (isinstance(ex, SystemExit) and ex.code in (0, None)):  # 안에서 이미 result()를 정했으면 그대로
            sp._status, sp._err_kind = status, kind
            sp._err = redact_text(f"{type(ex).__name__}: {ex}")[:500]
        raise
    finally:
        jsonlog.reset_context(token)
        with _LOCK:
            _OPEN.pop(sp.span_id, None)
        _finish(sp, start_wall, start_mono, usage0, load0)


def _finish(sp, start_wall, start_mono, usage0, load0):
    cols = sp.cols
    if sp._cpu and usage0:
        now = proc_usage()
        cols["cpu_ms"] = now["cpu_ms"] - usage0["cpu_ms"]
        cols["rss_peak_mb"] = now["rss_peak_mb"]
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
        "load1_per_cpu_end": _load1_per_cpu(),
        "mem_used_pct": _mem_pct(),
        "inflight": sp.inflight,
        "metrics": sp._finish_metrics() or None,
        "status": sp._status,
        "err_kind": sp._err_kind,
        "err": sp._err,
        "app_version": _app_version(),
    }
    for key in COLUMNS:
        row[key] = cols.get(key)
    _emit(row)


def instant(stage, status, layer=None, err_kind=None, err=None, **cols):
    """시간이 안 드는 결정 하나(reused·skip) — 시작=끝인 span 1행. run_id 없으면 아무것도 안 함."""
    with span(stage, layer, **cols) as sp:
        sp.result(status, err_kind, err)


def current():
    """지금 컨텍스트의 열린 span(없으면 None) — common/ai·resources가 지표를 더할 때 씀."""
    if not _OPEN:
        return None
    return _OPEN.get(jsonlog.get_context().get("span_id"))


def result_current(status, err_kind=None, err=None):
    sp = current()
    if sp is not None:
        sp.result(status, err_kind, err)


def add_current(**metrics):
    sp = current()
    if sp is not None:
        sp.add(**metrics)


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
    """Popen kwargs에 현재 run/span ID(내부 신호 APPLOG_CONTEXT)를 env로 이어 붙인 사본 — run_id 없으면 그대로."""
    ids = jsonlog.get_context()
    if not ids.get("run_id"):
        return kwargs
    env = dict(kwargs.get("env") or os.environ)  # env 남김 — 하위 프로세스용(상관 ID 전달, 설정 아님)
    env["APPLOG_CONTEXT"] = json.dumps(ids)  # env 남김 — 내부 신호(상관 ID, 설정 아님)
    return {**kwargs, "env": env}
