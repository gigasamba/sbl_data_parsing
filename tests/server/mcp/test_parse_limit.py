"""parse_document 크기 상한(사용자 11-03, 기본 100MB) — 검색 MCP 쪽: 상한을 넘는 content_b64는 서비스로 보내지 않고 이유를 돌려주며,
HTTP 본문 상한(SDK 기본 4MiB)은 base64 크기에 맞춰 올린다. 상한은 1MB로 덮어 작은 데이터로 본다(외부 접속 없음)."""

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx

from common.config.settings import COMMON
from common.core import parse_limit
from common.store import redisq
from mcp_server import main
from mcp_server.services import parse_proxy, tool_runner
from tests.server.common.test_redisq import FakeRedis

MB = 1048576


def _b64(n):
    return base64.b64encode(b"x" * n).decode()


def _stub(sent):
    def fake(source, r):
        sent.append(source)
        ws = redisq.JOBS_DIR / "j1"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "result-1.json").write_text(json.dumps({"text": "ok"}), encoding="utf-8")
        r.hset(redisq.key("job", "j1"), mapping={"status": "done", "result_file": "result-1.json"})
        r.lpush(redisq.key("done", "j1"), "done")
        return "j1", 0

    return fake


def test_proxy_limit():
    with COMMON.env(DATA_PARSING_MAX_MB="1"):
        assert parse_limit.max_bytes() == MB and parse_limit.body_cap() == MB * 3 // 2 + MB
        sent: list = []
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(redisq, "JOBS_DIR", Path(td)),
            patch.object(redisq, "client", return_value=FakeRedis()),
            patch.object(parse_proxy, "_submit", _stub(sent)),
        ):
            ok = parse_proxy.do_parse_document(content_b64=_b64(int(0.9 * MB)), filename="a.txt")
            assert ok == {"text": "ok", "status": "done"} and sent[0]["filename"] == "a.txt", (ok, sent)
            sent.clear()
            big = parse_proxy.do_parse_document(content_b64=_b64(int(1.1 * MB)), filename="a.txt")
            assert "크기 상한(1MB)" in big["error"] and "1.1MB" in big["error"] and not sent, (big, sent)
            exact = parse_proxy.do_parse_document(content_b64=_b64(MB), filename="a.txt")  # 딱 상한은 받음(패딩 '=' 셈 제외)
            assert exact.get("status") == "done", exact
            mime = base64.encodebytes(b"x" * MB).decode()  # 76자마다 줄바꿈 — 줄바꿈은 크기에 안 셈
            assert parse_proxy.do_parse_document(content_b64=mime, filename="a.txt").get("status") == "done"


def test_http_body_cap():
    """HTTP 길 끝까지 — 본문 상한이 SDK 기본(4MiB)이 아니라 설정에서 오고, 1.1MB 파일은 413이 아니라 도구가 이유를 답한다.
    큰 본문은 동시 2개 자리 하나를 쥐고 처리된다(PR #110 — 기준을 1000바이트로 낮춰 봄)."""
    assert main.build("127.0.0.1", 8765).settings.max_request_body_size == parse_limit.body_cap() > 133 * MB  # 기본 100MB의 base64

    async def call(client, n):
        args = {"content_b64": _b64(n), "filename": "a.txt", "time_out_threshold": 5}
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "parse_document", "arguments": args}}
        r = await client.post("/mcp", json=payload)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return json.loads(r.json()["result"]["content"][0]["text"])

    async def run():
        app_main = main.build("127.0.0.1", 8765)
        with patch.object(main, "build", return_value=app_main):
            app = main.build_guarded_app("127.0.0.1", 8765, "")
        holder.append(app.big_slots)
        headers = {"Accept": "application/json, text/event-stream"}
        async with (
            app_main.session_manager.run(),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765", headers=headers) as client,
        ):
            assert (await call(client, int(0.9 * MB))).get("status") == "done"
            assert "크기 상한(1MB)" in (await call(client, int(1.1 * MB)))["error"]

    sent: list = []
    holder: list = []
    free: list = []
    stub = _stub(sent)

    def watched(source, r):
        free.append(holder[0].value)
        return stub(source, r)

    with (
        tempfile.TemporaryDirectory() as td,
        patch.object(redisq, "JOBS_DIR", Path(td)),
        patch.object(redisq, "client", return_value=FakeRedis()),
        COMMON.env(DATA_PARSING_MAX_MB="1"),
        patch.object(parse_proxy, "_submit", watched),
        patch.object(main, "_BIG_BODY", 1000),
    ):
        try:
            asyncio.run(run())
        finally:
            tool_runner._LANES.clear()
    assert len(sent) == 1, sent  # 1.1MB는 서비스로 안 감
    assert free and set(free) == {main._BIG_SLOTS - 1}, free  # 처리 중엔 자리 하나를 쥠
    assert holder[0].value == main._BIG_SLOTS  # 끝나면 돌려줌


def test_proxy_completion_and_contract():
    from mcp_server.services import parse_proxy as P

    r = FakeRedis()
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.object(redisq, "JOBS_DIR", Path(directory)),
        patch.object(redisq, "client", return_value=r),
    ):

        def done():
            job_id = next(iter(r.sets[redisq.key("active")]))
            result = {"job_id": job_id, "filename": "a.txt", "text": "abcdef", "engine": "plain"}
            (Path(directory) / job_id / "result-1.json").write_text(json.dumps(result), encoding="utf-8")
            redisq.finish(r, "1-0", job_id, "done", result_file="result-1.json", elapsed_ms=1)

        r.on_wait = done
        out = P.do_parse_document(content_b64="dGV4dA==", filename="a.txt", max_chars=3)
        assert out["status"] == "done" and out["text"] == "abc" and out["text_truncated"] is True
        assert set(out) == {"job_id", "filename", "text", "engine", "status", "text_truncated"}
        r.on_wait = None
        timeout = P.do_parse_document(path="/worker/in/a.txt", time_out_threshold=2)
        assert "시간 안에 수행 못했습니다" in timeout["error"] and timeout["queue_position_at_submit"] == 0
        assert set(timeout) == {"error", "job_id", "elapsed_s", "queue_position_at_submit", "note"}
        r.on_wait = lambda: redisq.finish(r, "2-0", timeout["job_id"], "failed", error="parse failed", elapsed_ms=2)

        # 다음 제출 작업에 대한 rejected 응답
        def rejected():
            jid = next(j for j in r.sets[redisq.key("active")] if j != timeout["job_id"])
            redisq.finish(r, "3-0", jid, "rejected", error="허용 경로 아님")

        r.on_wait = rejected
        assert P.do_parse_document(path="/etc/secret") == {"error": "허용 경로 아님"}


def test_proxy_failed_full_and_connection():
    from common.config import settings

    r = FakeRedis()
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(DATA_PARSING_QUEUE_MAX=1),
        patch.object(redisq, "JOBS_DIR", Path(directory)),
        patch.object(redisq, "client", return_value=r),
    ):

        def failed():
            jid = next(iter(r.sets[redisq.key("active")]))
            redisq.finish(r, "1-0", jid, "failed", error="parse failed", elapsed_ms=2.5)

        r.on_wait = failed
        out = parse_proxy.do_parse_document(content_b64="eA==", filename="a.txt")
        assert out == {"job_id": out["job_id"], "filename": "a.txt", "status": "failed", "error": "parse failed", "elapsed_ms": 2.5}
        redisq.submit(r, "busy", {"filename": "busy.txt"}, 1)
        assert parse_proxy.do_parse_document(content_b64="eA==", filename="a.txt") == {"error": redisq.FULL_MESSAGE}
    with patch.object(redisq, "client", side_effect=ConnectionError("connection refused")):
        out = parse_proxy.do_parse_document(path="/worker/in/a.txt")
        assert "연결 실패(Redis" in out["error"] and "connection refused" in out["error"]


def test_base64_wins_over_path():
    r = FakeRedis()
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.object(redisq, "JOBS_DIR", Path(directory)),
        patch.object(redisq, "client", return_value=r),
    ):
        source = {"path": "/ignored/missing.docx", "content_b64": "dXBsb2Fk", "filename": "upload.txt"}
        jid, _ = parse_proxy._submit(source, r)
        job = r.hgetall(redisq.key("job", jid))
        assert job["mode"] == "base64" and job["filename"] == "upload.txt" and "path" not in job
        assert (Path(directory) / jid / "in" / "upload.txt").read_bytes() == b"upload"
        redisq.finish(r, "1-0", jid, "done")

        def done():
            job_id = next(iter(r.sets[redisq.key("active")]))
            result = {"filename": "upload.txt", "text": "upload"}
            (Path(directory) / job_id / "result-1.json").write_text(json.dumps(result), encoding="utf-8")
            redisq.finish(r, "2-0", job_id, "done", result_file="result-1.json")

        r.on_wait = done
        assert parse_proxy.do_parse_document(**source) == {"filename": "upload.txt", "text": "upload", "status": "done"}


def test_failed_submit_cleans_upload():
    r = FakeRedis()
    for error in (redisq.QueueFull(redisq.FULL_MESSAGE), ConnectionError("Redis down")):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(redisq, "JOBS_DIR", Path(directory)),
            patch.object(redisq, "submit", side_effect=error),
        ):
            try:
                parse_proxy._submit({"content_b64": "dGV4dA==", "filename": "a.txt"}, r)
                raise AssertionError("제출 실패가 전달되어야 함")
            except (redisq.QueueFull, parse_proxy.RedisFailure):
                pass
            assert list(Path(directory).iterdir()) == []


def test_file_errors_are_not_redis_errors():
    r = FakeRedis()
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.object(redisq, "JOBS_DIR", Path(directory)),
        patch.object(redisq, "client", return_value=r),
    ):
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            result = parse_proxy.do_parse_document(content_b64="dGV4dA==", filename="a.txt")
        assert result["error"] == "parse 작업 파일 오류: OSError: disk full" and result["job_id"]
        assert list(Path(directory).iterdir()) == []

        # 완료 알림 뒤 결과 파일이 사라져도 연결 실패로 표시하지 않음.
        def done_without_file():
            jid = next(iter(r.sets[redisq.key("active")]))
            redisq.finish(r, "1-0", jid, "done")

        r.on_wait = done_without_file
        result = parse_proxy.do_parse_document(content_b64="dGV4dA==", filename="a.txt")
        assert result["error"].startswith("parse 작업 파일 오류: FileNotFoundError:") and result["job_id"]
        assert "연결 실패" not in result["error"]


def test_redis_errors_without_redis_import():
    # redis-py 없는 서버 이미지 시험에서도 RedisError의 하위 클래스를 식별.
    error_type = type("RedisError", (Exception,), {"__module__": "redis.exceptions"})
    for name in ("ConnectionError", "TimeoutError", "AuthenticationError"):
        error = type(name, (error_type,), {})("Redis refused")
        r = FakeRedis()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(redisq, "JOBS_DIR", Path(directory)),
            patch.object(redisq, "client", return_value=r),
            patch.object(r, "blpop", side_effect=error),
        ):
            result = parse_proxy.do_parse_document(content_b64="dGV4dA==", filename="a.txt")
            assert "연결 실패(Redis" in result["error"] and name in result["error"]


def test_policy_rejects_before_files_and_submit():
    from unittest.mock import Mock

    import pytest

    for available in (True, False):
        for source in (
            {"content_b64": "eA==", "filename": "a.exe"},
            {"path": "/outside/a.txt"},
            {"path": "relative/a.txt"},
            {"path": "/allowed/../outside/a.txt"},
        ):
            r = FakeRedis()
            if available:
                redisq.publish_policy(r, [".txt"], ["/allowed"], 100)
            with tempfile.TemporaryDirectory() as d, patch.object(redisq, "JOBS_DIR", Path(d)):
                submit = Mock(wraps=redisq.submit)
                with patch.object(redisq, "submit", submit):
                    if available:
                        with pytest.raises(ValueError, match="지원하지 않는 확장자|허용 경로 아님"):
                            parse_proxy._submit(source, r)
                        assert not list(Path(d).iterdir())
                        submit.assert_not_called()
                    else:
                        jid, _ = parse_proxy._submit(source, r)
                        assert (Path(d) / jid).is_dir()
                        submit.assert_called_once()
    r = FakeRedis()
    redisq.publish_policy(r, [".txt"], ["/allowed"], 100)
    assert r.ttls[redisq.key("policy")] == 120
    with tempfile.TemporaryDirectory() as d, patch.object(redisq, "JOBS_DIR", Path(d)):
        assert parse_proxy._submit({"path": "/allowed/missing.txt"}, r)[0]  # 존재 확인은 worker 몫
        assert parse_proxy._submit({"path": "/ignored/a.exe", "content_b64": "eA==", "filename": "a.txt"}, r)[0]


def test_submit_response_lost():
    import pytest

    for committed, verify_fails in ((True, False), (False, False), (False, True)):
        r = FakeRedis()
        original = redisq.submit

        def lose_response(r, jid, meta, maximum, committed=committed, original=original):
            if committed:
                original(r, jid, meta, maximum)
            raise ConnectionError("EXEC response lost")

        with (
            tempfile.TemporaryDirectory() as d,
            patch.object(redisq, "JOBS_DIR", Path(d)),
            patch.object(redisq, "client", return_value=r),
            patch.object(redisq, "submit", side_effect=lose_response),
            patch.object(r, "exists", side_effect=ConnectionError("still down") if verify_fails else r.exists),
        ):
            if committed:

                def done(r=r, d=d):
                    jid = next(iter(r.sets[redisq.key("active")]))
                    (Path(d) / jid / "result-1.json").write_text('{"text": "ok"}', encoding="utf-8")
                    redisq.finish(r, "1-0", jid, "done", result_file="result-1.json")

                r.on_wait = done
                out = parse_proxy.do_parse_document(content_b64="eA==", filename="a.txt")
                assert out == {"text": "ok", "status": "done"}
                assert len(list(Path(d).iterdir())) == 1
            else:
                out = parse_proxy.do_parse_document(content_b64="eA==", filename="a.txt")
                assert "연결 실패" in out["error"] and out["job_id"]
                assert (Path(d) / out["job_id"]).exists() == verify_fails
            with pytest.raises(ValueError):
                parse_proxy._submit({}, r)


def test_result_filename_validation():
    for name in ("", "result.json", "../result-1.json", "sub/result-1.json", "sub\\result-1.json", "result-1..json"):
        r = FakeRedis()
        with tempfile.TemporaryDirectory() as d, patch.object(redisq, "JOBS_DIR", Path(d)), patch.object(redisq, "client", return_value=r):

            def done(r=r, name=name):
                jid = next(iter(r.sets[redisq.key("active")]))
                redisq.finish(r, "1-0", jid, "done", result_file=name)

            r.on_wait = done
            out = parse_proxy.do_parse_document(content_b64="eA==", filename="a.txt")
            assert out["error"].startswith("parse 작업 파일 오류:")
