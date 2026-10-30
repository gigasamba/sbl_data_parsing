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
            logging.getLogger("teststream.sdk").info("child")  # 부모 logger Filter에 기대지 않는다.
            assert not stdout.getvalue()
            jsonlog.setup("testdefault").info("default")
        assert [json.loads(line)["msg"] for line in stream.getvalue().splitlines()] == ["first", "child"]
        assert json.loads(stdout.getvalue())["msg"] == "default"
        for name in ("teststream", "testdefault"):
            log = logging.getLogger(name)
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
        assert jsonlog.masked("abc") == "abc"  # 4자 미만은 값 기반 대조만 생략.
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
    for size in (1024 * 1024, 2 * 1024 * 1024):
        value = "a" * size
        started = time.monotonic()
        assert _mask(value) == value
        assert time.monotonic() - started < 1.5  # 기존 제곱 시간 패턴은 1MiB에서도 멎는다.
