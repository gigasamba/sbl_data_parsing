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
