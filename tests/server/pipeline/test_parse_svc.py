"""pipeline.run_mcp_parsing — 작업 자식 설정(10-29): 서비스 쪽당 제한·첫 시도 하한·보통 우선순위."""

import base64
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from common.config import settings
from common.core import jsonlog, parse_limit, span
from pipeline import config as pc


def _submit(source, r):
    import uuid

    from common.store import redisq
    from pipeline import run_mcp_parsing as S

    jid = time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:12]
    ws = S.JOBS_DIR / jid
    (ws / "in").mkdir(parents=True)
    if source.get("content_b64"):
        raw = base64.b64decode(source["content_b64"])
        (ws / "in" / source["filename"]).write_bytes(raw)
        meta = {"mode": "base64", "filename": source["filename"], "bytes": len(raw)}
    else:
        meta = {"mode": "path", "filename": Path(source["path"]).name, "bytes": 0, "path": source["path"]}
    meta["submitted_at"] = time.time()
    return jid, redisq.submit(r, jid, meta, settings.cfg().parse_queue.queue_max)


def test_job_env_overrides():
    from pipeline import run_mcp_parsing as S

    seen = {}

    def fake_env(**names):
        seen.update(names)
        return {"SETTINGS_FILE": "x"}

    S._JOB_ENVS.clear()
    with pc.PIPE.env(DATA_PARSING_TEXT_PAGE_SEC="1", DATA_PARSING_WARMUP_SEC="20"):
        with mock.patch.object(S, "settings_env", fake_env):
            S._job_env("supsub")
    S._JOB_ENVS.clear()
    assert seen["PARSE_LOW_PRIORITY"] == "0", seen  # 서비스 엔진 자식은 보통 우선순위(일괄 파싱보다 먼저)
    assert float(seen["PARSE_TEXT_PAGE_SEC"]) == 1 and "PARSE_VLM_PAGE_SEC" not in seen, seen  # VLM은 models.vlm.timeout 하나(11-04)
    assert float(seen["PARSE_WARMUP_SEC"]) == 20 and seen["PARSE_POST"] == "supsub", seen


def test_scan_pdf_note():
    """mc-18(사용자 11-03) — 스캔 판정은 run_all과 같은 pdf_kind · VLM 설정(VLM_BASE_URL·VLM_MODEL)이 비면 파이프라인 없이 '미설정' 안내,
    있으면 파이프라인(VLM)으로 · 대표 결과가 없으면 스캔은 'VLM 파싱 실패', 그 밖은 DRM 추정."""
    import tempfile
    from pathlib import Path

    import fitz

    from common.config.settings import COMMON
    from pipeline import run_mcp_parsing as S

    # pdf_kind는 pdfium 문서를 닫지 않음(GC가 닫음) — Windows에서는 임시 폴더 지우기가 막힐 수 있어 정리 오류는 무시
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        scan, text = Path(d) / "scan.pdf", Path(d) / "text.pdf"
        doc = fitz.open()
        doc.new_page().draw_rect(fitz.Rect(50, 50, 300, 200))  # 글자층 없음
        doc.save(str(scan))
        doc = fitz.open()
        doc.new_page().insert_text((50, 72), "pH 7.2 buffer solution text layer " * 3)
        doc.save(str(text))
        assert S._is_scan(scan) is True and S._is_scan(text) is False
        assert S._is_scan(Path(d) / "a.docx") is False
    with COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None):
        assert S.skip_note(True) == S.VLM_UNSET_NOTE and S.skip_note(False) is None
    with COMMON.env(VLM_BASE_URL="http://10.0.0.5:8000/v1", VLM_MODEL=None):
        assert S.skip_note(True) == S.VLM_UNSET_NOTE  # 모델 이름도 있어야 qwen_vlm이 돎(REQUIRES_ENV)
    with COMMON.env(VLM_BASE_URL="http://10.0.0.5:8000/v1", VLM_MODEL="qwen-vl"):
        assert S.skip_note(True) is None  # VLM이 있으면 파이프라인으로
    assert S.empty_note(True) == S.VLM_FAIL_NOTE and S.empty_note(False) == S.DRM_NOTE
    # 엔진은 돌았는데 대표 결과 없음
    assert S.empty_note(False, ran=True) == S.NO_REP_NOTE and S.empty_note(True, ran=True) == S.VLM_FAIL_NOTE


def test_size_limit():
    """크기 상한은 proxy 업로드와 worker path·base64 모두 같음(HTTP 전송·폴링 없음)."""
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    mb = 1048576
    r = FakeRedis()
    with tempfile.TemporaryDirectory() as td, settings.isolated(DATA_PARSING_MAX_MB="1"):
        root = Path(td, "inbox")
        root.mkdir()
        (root / "ok.txt").write_bytes(b"x" * int(0.9 * mb))
        (root / "big.txt").write_bytes(b"x" * int(1.1 * mb))
        with (
            mock.patch.object(S, "_run_job", side_effect=lambda jid, j, ws, fname, t0: S._result(jid, fname)),
            mock.patch.multiple(S, ROOTS=[root.resolve()], JOBS_DIR=Path(td, "jobs")),
            mock.patch.object(redisq, "JOBS_DIR", S.JOBS_DIR),
        ):
            assert parse_limit.max_bytes() == mb
            for source in (
                {"path": str(root / "ok.txt")},
                {"content_b64": base64.b64encode(b"x" * int(0.9 * mb)).decode(), "filename": "a.txt"},
            ):
                jid, _ = _submit(source, r)
                S._process(r, *S._receive(r, "worker"))
                assert r.hgetall(redisq.key("job", jid))["status"] != "rejected"
            jid, _ = _submit({"path": str(root / "big.txt")}, r)
            S._process(r, *S._receive(r, "worker"))
            job = r.hgetall(redisq.key("job", jid))
            assert job["status"] == "rejected" and "1.1MB" in job["error"]


def test_result_shape():
    """작업 결과 사전 하나(_result) — 빈 결과와 대표 결과의 칸이 parse_document 응답 그대로."""
    from pipeline import run_mcp_parsing as S

    empty = S._result("j", "a.pdf", note=S.DRM_NOTE, ms=1.0)
    assert empty == {
        "job_id": "j",
        "filename": "a.pdf",
        "status": "done",
        "engine": None,
        "text": "",
        "tables_std": [],
        "tables": [],
        "facts": [],
        "fields": {},
        "rep_path": None,
        "all_keys": [],
        "note": S.DRM_NOTE,
        "ms": 1.0,
    }, empty
    rep = {"text": "t", "rep": {"engine": "e"}, "tables": [1], "x": 0}
    got = S._result("j", "a.pdf", rep, rep_path="r", workspace="w", ms=2.0)
    assert got["engine"] == "e" and got["text"] == "t" and got["tables"] == [1] and got["facts"] is None, got
    assert got["all_keys"] == ["rep", "tables", "text", "x"] and "status" not in got and "note" not in got, got
    assert (got["rep_path"], got["workspace"], got["ms"]) == ("r", "w", 2.0), got


def _worker_rows(run_job, count=1, scan=False):
    """실제 제출·worker를 Redis 대역으로 돌린다. 로그 logger만 가로채 DB·sink·모델 없이 행을 확인."""
    from pipeline import run_mcp_parsing as S

    rows, jobs = [], {}
    from common.store import redisq
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    log = mock.Mock()
    log.log.side_effect = lambda *a, extra: rows.append({"table": extra["log_table"], "row": extra["log_row"]})
    with (
        tempfile.TemporaryDirectory() as directory,
        settings.isolated(APPLOG_DB_ENABLED="0", VLM_BASE_URL=None, VLM_MODEL=None),
        mock.patch.object(S, "JOBS_DIR", Path(directory)),
        mock.patch.object(redisq, "JOBS_DIR", Path(directory)),
        mock.patch.object(S, "_JOB_ENVS", {}),
        mock.patch.object(S, "_is_scan", return_value=scan),
        mock.patch.object(S, "_purge_old"),
        mock.patch.object(S, "_run_job", run_job),
        mock.patch.object(span, "_logger", return_value=log),
        mock.patch.object(S.runtrace, "_STATE", {"info": {}, "docs": {}}),
        jsonlog.context(run_id="service-parent", span_id="service-span"),
    ):
        ids = []
        for _ in range(count):
            jid, ahead = _submit({"content_b64": base64.b64encode(b"text").decode(), "filename": "a.txt"}, r)
            assert int(r.hgetall(redisq.key("job", jid))["queue_position"]) == ahead == len(ids)
            r.hset(redisq.key("job", jid), mapping={"submitted_at": time.time() - 1})
            ids.append(jid)
        for jid in ids:
            S._process(r, *S._receive(r, "test-worker"))
            jobs[jid] = redisq.decode_job(r.hgetall(redisq.key("job", jid)))
        assert jsonlog.get_context()["run_id"] == "service-parent"
    return jobs, rows


def test_worker_trace_and_child_context():
    from pipeline import run_mcp_parsing as S

    children, overlays = [], []

    def run_job(job_id, job, ws, fname, t0):
        env = S._job_env("supsub")
        overlays.append(env["SETTINGS_FILE"])
        # 실제 자식 import가 컨텍스트를 읽고 runtrace.run(run_all)이 새 실행을 만들지 않는지 확인.
        code = """import json
from common.core.jsonlog import get_context
from pipeline.shared.runtrace import run
with run('run_all') as created:
    print(json.dumps({'context': get_context(), 'created': created}))
"""
        children.append(json.loads(subprocess.check_output([sys.executable, "-c", code], env=env, text=True)))
        return S._result(job_id, fname, {"text": "text"})

    jobs, rows = _worker_rows(run_job, count=2)
    events = [r["row"] for r in rows if r["table"] == "pipe_event"]
    starts = [r["row"] for r in rows if r["table"] == "pipe_run" and r["row"]["status"] == "running"]
    ends = [r["row"] for r in rows if r["table"] == "pipe_run" and r["row"]["status"] != "running"]
    assert len(events) == len(starts) == len(ends) == 2 and overlays[0] == overlays[1]  # 덮기 파일은 재사용
    assert len({r["run_id"] for r in starts}) == 2 and "service-parent" not in {r["run_id"] for r in starts}
    for i, row in enumerate(events):
        assert row["stage"] == "mcp_parse.job" and row["status"] == "ok" and row["inflight"] == 1
        assert (row["doc_id"], row["ext"], row["file_bytes"]) == ("a.txt", ".txt", 4)
        metrics = row["metrics"]
        assert metrics["job_id"] in jobs and metrics["queue_wait_ms"] >= 1000 and metrics["queue_position"] == i
        assert metrics["mode"] == "base64" and metrics["scan"] is False
        assert starts[i]["command"] == "mcp_parse" and metrics["job_id"] in starts[i]["args"]
        assert children[i]["context"] == {"run_id": row["run_id"], "span_id": row["span_id"]} and children[i]["created"] is None
        assert starts[i]["run_id"] == ends[i]["run_id"] == row["run_id"] and ends[i]["status"] == "ok"
    assert all(j["status"] == "done" for j in jobs.values())


def test_worker_fail_timeout_and_continue():
    from pipeline import run_mcp_parsing as S

    attempts = [RuntimeError("문서 본문은 추적 행에 남지 않음"), subprocess.TimeoutExpired("parse", 1), None]

    def run_job(job_id, job, ws, fname, t0):
        exc = attempts.pop(0)
        if exc:
            raise exc
        return S._result(job_id, fname, note=S.DRM_NOTE)

    jobs, rows = _worker_rows(run_job, count=3)
    events = [r["row"] for r in rows if r["table"] == "pipe_event"]
    assert [j["status"] for j in jobs.values()] == ["failed", "failed", "done"]
    assert [r["status"] for r in events] == ["fail", "timeout", "ok"]
    assert [r["err_kind"] for r in events] == ["doc", "timeout", None]
    assert events[0]["err"] == "RuntimeError" and events[-1]["metrics"]["note"] == S.DRM_NOTE
    ends = [r["row"] for r in rows if r["table"] == "pipe_run" and "ended_at" in r["row"]]
    assert [r["status"] for r in ends] == ["fail", "fail", "ok"]  # pipe_run은 timeout을 fail로 묶고 span이 세분


def test_worker_scan_without_pipeline():
    from pipeline import run_mcp_parsing as S

    run_job = mock.Mock(side_effect=AssertionError("파이프라인을 부르면 안 됨"))
    jobs, rows = _worker_rows(run_job, scan=True)
    run_job.assert_not_called()
    event = next(r["row"] for r in rows if r["table"] == "pipe_event")
    assert event["status"] == "ok" and event["metrics"]["scan"] is True and event["metrics"]["note"] == S.VLM_UNSET_NOTE
    assert next(iter(jobs.values()))["status"] == "done"


def test_rejected_and_reclaimed_attempts():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    with tempfile.TemporaryDirectory() as d, mock.patch.object(redisq, "JOBS_DIR", Path(d)), mock.patch.object(S, "JOBS_DIR", Path(d)):
        for source, expected in (
            ({"path": "/etc/passwd"}, "허용 경로 아님"),
            ({"content_b64": "eA==", "filename": "a.exe"}, "지원하지 않는 확장자"),
        ):
            jid, _ = _submit(source, r)
            S._process(r, *S._receive(r, "worker"))
            job = r.hgetall(redisq.key("job", jid))
            assert job["status"] == "rejected" and expected in job["error"]
        jid, _ = _submit({"content_b64": "eA==", "filename": "a.txt"}, r)
        item = S._receive(r, "dead")
        mid = item[0]
        r.pending[mid].update(dead=True, times_delivered=3)
        recovered = S._receive(r, "rescuer", min_idle_ms=1)
        assert recovered[3] == 4
        with mock.patch.object(S, "_run_job", side_effect=AssertionError("시도 상한을 넘겨 실행하면 안 됨")):
            S._process(r, *recovered)
        job = r.hgetall(redisq.key("job", jid))
        assert job["status"] == "failed" and "worker가 3번 중단됨 — 작업 포기" in job["error"]
        assert jid not in r.sets[redisq.key("active")] and r.lists[redisq.key("done", jid)]


def test_purge_order_and_upload_grace():
    import os

    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    with tempfile.TemporaryDirectory() as directory, mock.patch.multiple(S, JOBS_DIR=Path(directory), MAX_JOBS_KEPT=1):
        now = time.time()
        old, newer = Path(directory) / "z-old", Path(directory) / "a-newer"
        for folder, age in ((old, 2000), (newer, 1000)):
            folder.mkdir()
            os.utime(folder, (now - age, now - age))
        S._purge_old(r)
        assert not old.exists() and newer.exists()  # 이름순이 아니라 수정 시간순으로 최근 폴더 유지
        upload, recent, active = (Path(directory) / name for name in ("0-upload", "1-recent", "2-active"))
        for folder, age in ((upload, 0), (recent, 599), (active, 3000)):
            folder.mkdir()
            os.utime(folder, (now - age, now - age))
        r.sadd(redisq.key("active"), active.name)
        S._purge_old(r)
        assert upload.exists() and recent.exists() and active.exists()
        assert not newer.exists()  # 등록 전·최근 10분 폴더·active만 유예


def test_terminal_job_ack_deletes_stream():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    redisq.submit(r, "terminal", {"filename": "a.txt"}, 1)
    item = S._receive(r, "worker")
    r.hset(redisq.key("job", "terminal"), mapping={"status": "done"})
    S._process(r, *item)
    assert r.transactions[-1] == ["xack", "xdel"] and not r.streams[redisq.key("queue")] and not r.pending


def test_health_is_local_to_supervisor():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    with (
        tempfile.TemporaryDirectory() as directory,
        mock.patch.object(S, "_token_file", return_value=Path(directory) / "worker.id"),
        mock.patch.object(redisq, "client", return_value=r),
    ):
        # 같은 hostname·prefix의 다른 컨테이너 heartbeat만으로 정상 판정하지 않음.
        r.set(redisq.key("worker", "shared-host-111-deadbeef-222"), "1", ex=30)
        assert S.health() is False  # 로컬 token 파일이 없음
        token = "shared-host-333-cafebabe"
        S._token_file().write_text(token, encoding="utf-8")
        assert S.health() is False
        r.set(redisq.key("worker", token + "-444"), "1", ex=30)
        assert S.health() is True
        S._token_file().write_text("*", encoding="utf-8")
        assert S.health() is False  # 손상된 token으로 다른 worker를 찾지 않음


def test_engine_process_default_per_worker():
    import importlib

    from pipeline import run_mcp_parsing as S

    try:
        for cores, wanted in ((None, 1), (1, 1), (2, 1), (3, 2), (16, 2)):
            with pc.PIPE.env(DATA_PARSING_PROCS=None), mock.patch.object(S.os, "cpu_count", return_value=cores):
                importlib.reload(S)
                assert S.PROCS == str(wanted), (cores, S.PROCS)
        with pc.PIPE.env(DATA_PARSING_PROCS=1), mock.patch.object(S.os, "cpu_count", return_value=16):
            importlib.reload(S)
            assert S.PROCS == "1"  # 작은 호스트의 명시적 엔진 수를 보존
    finally:
        importlib.reload(S)


def test_claim_finish_race():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    redisq.submit(r, "race", {"filename": "a.txt"}, 1)
    item = S._receive(r, "rescuer")
    claim = redisq.claim

    def finish_first(*args):
        redisq.finish(r, item[0], "race", "done", result_file="result-1.json")
        return claim(*args)

    with mock.patch.object(redisq, "claim", side_effect=finish_first), mock.patch.object(S, "_run_job") as run:
        S._process(r, *item)
    assert r.hgetall(redisq.key("job", "race"))["status"] == "done"
    assert r.transactions[-1] == ["xack", "xdel"]
    run.assert_not_called()


def test_attempt_files_are_isolated():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    with tempfile.TemporaryDirectory() as d, mock.patch.object(S, "JOBS_DIR", Path(d)):
        jid, _ = _submit({"content_b64": "eA==", "filename": "a.txt"}, r)
        item = S._receive(r, "first")
        workspaces = []

        def run(jid, j, ws, fname, t0):
            workspaces.append(ws)
            (ws / "run.log").write_text(str(j["attempts"]), encoding="utf-8")
            if j["attempts"] == 1:
                S._process(r, item[0], jid, "second", 2)
            return S._result(jid, fname, text=str(j["attempts"]))

        with mock.patch.object(S, "_run_job", side_effect=run):
            S._process(r, *item)
        job = r.hgetall(redisq.key("job", jid))
        assert job["status"] == "done" and job["result_file"] == "result-2.json"
        assert [p.name for p in workspaces] == ["a1", "a2"]
        for n in (1, 2):
            assert json.loads((Path(d) / jid / f"result-{n}.json").read_text(encoding="utf-8"))["text"] == str(n)
            assert (Path(d) / jid / f"a{n}" / "run.log").read_text(encoding="utf-8") == str(n)


def test_dead_consumer_heartbeat_and_cleanup():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    redisq.submit(r, "j", {"filename": "a.txt"}, 1)
    item = S._receive(r, "dead")
    r.consumers.update(dead=60001, empty=60001)
    r.set(redisq.key("worker", "dead"), "1", ex=30)
    assert redisq.reclaim_dead(r, "rescuer") is None
    assert "empty" not in r.consumers and r.pending[item[0]]["consumer"] == "dead"
    r.delete(redisq.key("worker", "dead"))
    got = S._receive(r, "rescuer")
    assert got == (item[0], "j", "rescuer", 2)
    assert r.pending[item[0]]["consumer"] == "rescuer"


def test_corrupt_hash_finishes_failed():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    redisq.submit(r, "bad", {"filename": "a.txt", "bytes": "broken"}, 1)
    S._process(r, *S._receive(r, "worker"))
    job = r.hgetall(redisq.key("job", "bad"))
    assert job["status"] == "failed" and "ValueError" in job["error"]
    assert not r.pending


def test_worker_nonredis_error_log():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    stop = mock.Mock()
    stop.is_set.side_effect = [False, True]
    with (
        mock.patch.object(S.threading, "Event", return_value=stop),
        mock.patch.object(S.threading, "Thread"),
        mock.patch.object(S.signal, "signal"),
        mock.patch.object(redisq, "client", return_value=FakeRedis()),
        mock.patch.object(S, "_receive", side_effect=ValueError("bad hash")),
        mock.patch.object(redisq, "ensure_group") as ensure,
        mock.patch.object(S, "_log") as log,
    ):
        S._worker("supervisor")
    ensure.assert_called_once()
    assert "worker 오류: ValueError: bad hash" in log.call_args.args[0]
    assert "Traceback" in log.call_args.args[0] and "연결 실패" not in log.call_args.args[0]


def test_policy_refresh_reads_engine_configuration():
    from common.store import redisq
    from pipeline import run_mcp_parsing as S
    from tests.server.common.test_redisq import FakeRedis

    r = FakeRedis()
    with mock.patch.object(S, "allowed_exts", side_effect=[{".txt"}, {".pdf"}, ValueError("bad stack")]):
        S._publish_policy(r)
        assert redisq.read_policy(r)["exts"] == [".txt"]
        S._publish_policy(r)
        assert redisq.read_policy(r)["exts"] == [".pdf"]
        with mock.patch.object(S, "_log") as log:
            S._publish_policy(r)
        assert "정책 갱신 실패" in log.call_args.args[0]
