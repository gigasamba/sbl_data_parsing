"""op-01: JSON 필수 키·비밀 마스킹·수준·contextvars/자식 프로세스 전파(외부 접속 없음)."""

import concurrent.futures
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from common.config import settings
from common.core import jsonlog


def test_json_lines():
    with tempfile.TemporaryDirectory() as directory, settings.isolated(APPLOG_DIR=directory, LOG_LEVEL="WARNING", APPLOG_DB_ENABLED="0"):
        log = jsonlog.setup("testjson")
        log.info("filtered")
        with jsonlog.context(request_id="req-1"):
            log.warning("password=hidden-one Authorization: Bearer hidden-two", extra={"event": "test.done", "duration_ms": 12})
            try:
                raise ValueError("token=hidden-three")
            except ValueError:
                log.exception("failed")
        jsonlog.shutdown()
        content = (Path(directory) / "testjson.jsonl").read_text(encoding="utf-8")
        rows = [json.loads(line) for line in content.splitlines()]
        assert len(rows) == 2 and "filtered" not in content
        assert not any(secret in content for secret in ("hidden-one", "hidden-two", "hidden-three"))
        assert {"time", "level", "app", "event", "msg", "request_id", "run_id", "duration_ms", "err"} <= set(rows[0])
        assert rows[0]["request_id"] == "req-1" and rows[0]["duration_ms"] == 12
        assert "ValueError" in rows[1]["err"] and rows[0]["app"] == "testjson"
        # setup은 멱등: 같은 파일에 같은 줄이 중복되지 않는다.
        assert len(jsonlog.setup("testjson").handlers) == 1
        for handler in log.handlers[:]:
            log.removeHandler(handler)
            handler.close()
    nested = jsonlog.masked(
        {
            "password": "hidden-four",
            "Authorization": "Bearer hidden-seven",
            "args": '{"Authorization": "Bearer hidden-eight"}',
            "nested": [{"api_key": "hidden-five"}],
            "value": 'password="hidden six"',
        }
    )
    assert "hidden" not in json.dumps(nested)
    # JSON 직렬화 구조를 마스킹 정규식이 깨뜨리지 않음(따옴표/역슬래시 포함).
    record = logging.makeLogRecord({"msg": 'Authorization: Bearer abc\\"', "levelname": "INFO", "created": 0})
    assert "abc" not in json.loads(jsonlog.JsonFormatter("test").format(record))["msg"]


def test_context_ids():
    original = jsonlog.get_context()
    with jsonlog.context(run_id="parent", span_id="outer"):
        with jsonlog.context(span_id="inner"):
            assert jsonlog.get_context()["span_id"] == "inner"
        assert jsonlog.get_context()["span_id"] == "outer"
        result = subprocess.run(
            [sys.executable, "-c", "import json; from common.core.jsonlog import get_context; print(json.dumps(get_context()))"],
            env=settings.child_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout)["run_id"] == "parent"
        assert json.loads(result.stdout)["span_id"] == "outer"
    assert jsonlog.get_context() == original

    def worker(value):
        with jsonlog.context(request_id=value):
            return jsonlog.get_context()["request_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker, ("one", "two"))) == ["one", "two"]
    assert jsonlog.get_context() == original


def test_stream_preserved():
    import contextlib
    import io
    from unittest.mock import patch

    from common.core import paths

    stream, stdout = io.StringIO(), io.StringIO()
    with settings.isolated(APPLOG_DIR="", APPLOG_DB_ENABLED="0", LOG_LEVEL="INFO"), patch.object(paths, "LOCAL_RUN", False):
        with contextlib.redirect_stdout(stdout):
            log = jsonlog.setup("teststream", stream=stream)
            log.info("first")
            jsonlog.setup("teststream")  # 재설정에도 명시 스트림을 유지한다.
            logging.getLogger("applog.teststream.sdk").info("child")  # 부모 logger Filter에 기대지 않는다.
            assert not stdout.getvalue()
            jsonlog.setup("testdefault").info("default")
        assert [json.loads(line)["msg"] for line in stream.getvalue().splitlines()] == ["first", "child"]
        assert json.loads(stdout.getvalue())["msg"] == "default"
        for name in ("teststream", "testdefault"):
            log = logging.getLogger(f"applog.{name}")
            for handler in log.handlers[:]:
                log.removeHandler(handler)
                handler.close()


def test_setting_secrets():
    from urllib.parse import quote

    secret = 'DEMO_SECRET_VALUE한글"\\tail'
    dsn_password = "dsn-secret-value"
    dsn = f"postgresql://user:{dsn_password}@localhost/db"
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(PG_PASSWORD=secret, RDB_CONNECT_KWARGS=dsn, LLM_API_KEY="abc", APPLOG_DIR=directory, APPLOG_DB_ENABLED="0"),
    ):
        source = {"nested": [{"value": secret}], "argv": ["--key", secret], secret: quote(secret, safe="")}
        safe = json.dumps(jsonlog.masked(source), ensure_ascii=False)
        assert secret not in safe and quote(secret, safe="") not in safe
        assert jsonlog.masked(dsn_password) == "***"
        assert jsonlog.masked("abc") == "***"  # 짧은 값은 토큰 경계에서 보호.
        assert source["nested"][0]["value"] == secret
        log = jsonlog.setup("testvalues")
        try:
            raise ValueError(secret)
        except ValueError:
            log.exception("argv %s %s", "--key", secret)
        for handler in log.handlers[:]:
            log.removeHandler(handler)
            handler.close()
        content = (Path(directory) / "testvalues.jsonl").read_text(encoding="utf-8")
        assert "DEMO_SECRET_VALUE" not in content and "ValueError" in content


def test_mask_linear():
    import re
    import time

    from common.core.runlog import _SECRET_PATTERNS, _mask

    original_dsn = re.compile(r"(?i)[a-z][a-z0-9+.\-]*://[^:/@\s]+:(?P<val>[^@\s]+)@")
    examples = [
        "completion_tokens=18 max_tokens=20 token_budget=100 ev_tokens5=3 tokens()",
        "token=hidden password='with space' api_key=one AWS_SECRET_ACCESS_KEY=two",
        '{"Authorization": "Bearer abc", "password": "quoted secret"}',
        "postgresql://user:secret@host/db",
        "1+.-postgresql://user:secret@host/db -https://u:pwd@host",
        "a://user:secret@host a://missing/user a://user:missing",
    ]
    for value in examples:
        old = value
        for pattern in (*_SECRET_PATTERNS[:-1], original_dsn):
            old = pattern.sub(lambda m: m.group(0)[: m.start("val") - m.start()] + "***" + m.group(0)[m.end("val") - m.start() :], old)
        assert _mask(value) == old
    from statistics import median

    timings = []
    for size in (1024 * 1024, 4 * 1024 * 1024):
        value, samples = "a" * size, []
        for _ in range(3):
            # 스케줄링 대기는 제외: 부하 환경에서도 알고리즘의 크기별 증가율을 비교.
            started = time.thread_time()
            assert _mask(value) == value
            samples.append(time.thread_time() - started)
        timings.append(median(samples))
    assert timings[1] / timings[0] < 10, timings  # 선형 4배 허용, 종전 제곱 16배는 거부.


def test_short_and_json_options():
    import contextlib
    import io
    from unittest.mock import patch

    options = '{"driver":"ODBC Driver 18 for SQL Server","host":"localhost","token_budget":"visible-budget","password":"option-password","nested":{"api_key":"nested-key"},"items":["unlabelled-value",{"pwd":"xy"}]}'
    warning = io.StringIO()
    with settings.isolated(PG_PASSWORD="abc", RDB_CONNECT_KWARGS=options), patch.object(jsonlog, "_SHORT_WARNED", False):
        with contextlib.redirect_stderr(warning):
            source = {"query": "abc", "argv": ["--query", "abc"], "text": "x=abc; _abc_ abc1 1abc 한abc abc한", "long": "abcd"}
            safe = jsonlog.masked(source)
            assert safe["query"] == "***" and safe["argv"] == ["--query", "***"]
            assert safe["text"] == "x=***; _***_ abc1 1abc 한abc abc한" and safe["long"] == "abcd"
            assert source["query"] == "abc"
            values = [
                "ODBC Driver 18 for SQL Server",
                "localhost",
                "option-password",
                "nested-key",
                "unlabelled-value",
                "xy",
                "visible-budget",
            ]
            assert jsonlog.masked(values) == [values[0], values[1], "***", "***", values[4], "***", "visible-budget"]
            jsonlog.masked("abc")
        notice = warning.getvalue()
        assert len(notice.splitlines()) == 1 and "connections.pg.password" in notice
        assert all(secret not in notice for secret in ("abc", "xy", "option-password", "nested-key"))
    for secret in ("a", "ab"):
        with settings.isolated(PG_PASSWORD=secret):
            assert jsonlog.masked([secret, "x=" + secret + ";", secret + "d"]) == ["***", "x=***;", secret + "d"]


def test_secret_key_cache_bounded():
    """긴 키는 캐시에 남기지 않되 판정은 같다. 짧은 키는 캐시한다."""
    long_secret = "password" + "x" * 300  # 라벨 판정은 키 이름 전체 모양으로
    long_plain = "k" * 5000
    jsonlog._secret_key_cached.cache_clear()
    for key in ("api_key", "password", "model", "Authorization", "id", long_secret, long_plain, "x" * 257):
        assert jsonlog._secret_key(key) == jsonlog._secret_key_probe(key)
    assert jsonlog._secret_key("api_key") is True and jsonlog._secret_key("model") is False
    assert jsonlog._secret_key("x" * 257) is False
    info = jsonlog._secret_key_cached.cache_info()
    assert info.currsize == 5  # 긴 키 3개(257·300+·5000자)는 캐시를 거치지 않았다
    assert jsonlog.masked({long_plain: {"api_key": "v"}}) == {long_plain: {"api_key": "***"}}
    assert jsonlog._secret_key_cached.cache_info().currsize == 5
