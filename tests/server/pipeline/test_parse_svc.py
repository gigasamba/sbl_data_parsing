"""pipeline.mcp_parse_service — 작업 자식 설정(10-29): 서비스 쪽당 제한·첫 시도 하한·보통 우선순위."""

from unittest import mock

from pipeline import config as pc


def test_job_env_overrides():
    from pipeline import mcp_parse_service as S

    seen = {}

    def fake_env(**names):
        seen.update(names)
        return {"SETTINGS_FILE": "x"}

    S._JOB_ENVS.clear()
    with pc.PIPE.env(PARSE_MCP_TEXT_PAGE_SEC="1", PARSE_MCP_VLM_PAGE_SEC="60", PARSE_MCP_WARMUP_SEC="20"):
        with mock.patch.object(S, "settings_env", fake_env):
            S._job_env("supsub")
    S._JOB_ENVS.clear()
    assert seen["PARSE_LOW_PRIORITY"] == "0", seen  # 서비스 엔진 자식은 보통 우선순위(일괄 파싱보다 먼저)
    assert float(seen["PARSE_TEXT_PAGE_SEC"]) == 1 and float(seen["PARSE_VLM_PAGE_SEC"]) == 60, seen
    assert float(seen["PARSE_WARMUP_SEC"]) == 20 and seen["PARSE_POST"] == "supsub", seen


def test_no_ocr_engines():
    from pipeline import mcp_parse_service as S

    args = S._engines_no_ocr_arg()
    assert not args or not {"rapidocr_ko", "qwen_vlm"} & set(args[1].split(","))


def test_scan_pdf_note():
    """pl-03(사용자 10-31) — 스캔 PDF는 파이프라인 없이 임시 안내(돌 엔진이 없음), 표본보다 스캔으로 분류돼 엔진이 하나도 못 돌면
    run_all의 NO_JOB_MARK 줄로 같은 안내 — 엔진이 돌다 다 실패했을 때만 DRM 추정."""
    from pipeline import mcp_parse_service as S
    from pipeline.extract.run_all import IDLE_MARK, NO_JOB_MARK

    assert S.skip_note("a.pdf", 0) == S.SCAN_NOTE and S.skip_note("a.pdf", 19) == S.SCAN_NOTE
    assert S.skip_note("a.pdf", 20) is None and S.skip_note("a.pdf", -1) is None and S.skip_note("a.pdf", None) is None
    assert S.skip_note("a.docx", None) is None
    assert "추후 지원 예정" in S.SCAN_NOTE
    assert S.empty_note(f"== run_all\n{IDLE_MARK}(비교하려면 stack json을 고침): docling\n{NO_JOB_MARK}\n") == S.SCAN_NOTE
    assert S.empty_note(f"== run_all\n{IDLE_MARK}(비교하려면 stack json을 고침): docling\n") == S.DRM_NOTE  # 일부만 안 돎
    assert S.empty_note("== run_all\nTraceback …") == S.DRM_NOTE and S.empty_note(None) == S.DRM_NOTE


def test_size_limit():
    """사용자 11-03 — 파일 크기 상한 한 칸(common.runtime.parse_max_mb)을 path·content_b64 두 길에 같게, HTTP 본문 상한은 base64 크기 기준
    (전에는 파일 상한 + 64KB라 base64 본문이 파일 상한의 3/4에서 막혔음). 상한 1MB로 덮고 루프백 임시 포트의 실제 HTTP 서버로 본다."""
    import base64
    import json
    import tempfile
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path

    from common.config.settings import COMMON
    from pipeline import mcp_parse_service as S

    mb = 1048576
    with tempfile.TemporaryDirectory() as td:
        root = Path(td, "inbox")
        root.mkdir()
        (root / "ok.txt").write_bytes(b"x" * int(0.9 * mb))
        (root / "big.txt").write_bytes(b"x" * int(1.1 * mb))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def post(source):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/jobs", data=json.dumps(source).encode(), method="POST")
            req.add_header("Authorization", "Bearer t")
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        def b64(n):
            return {"content_b64": base64.b64encode(b"x" * n).decode(), "filename": "a.txt"}

        try:
            with (
                COMMON.env(PARSE_MCP_MAX_MB="1"),
                mock.patch.multiple(S, TOKEN="t", ROOTS=[root.resolve()], JOBS_DIR=Path(td, "jobs")),
                mock.patch.object(S, "_purge_old"),
            ):
                assert S._max_bytes() == mb
                assert post(b64(int(0.9 * mb)))[0] == 202
                assert post({"path": str(root / "ok.txt")})[0] == 202
                # 1.1MB의 base64 본문(약 1.47MB)은 옛 본문 상한(파일 상한 + 64KB)이면 "본문 크기 상한 초과"였음 — 이제 크기를 알려 주는 거부
                for source in (b64(int(1.1 * mb)), {"path": str(root / "big.txt")}):
                    code, body = post(source)
                    assert code == 400 and "크기 상한(1MB)" in body["error"] and "1.1MB" in body["error"], (code, body)
        finally:
            srv.shutdown()
            srv.server_close()
            with S._lock:
                for j in [
                    k for k, v in S.JOBS.items() if str(Path(td)) in str(v.get("path", "")) or v.get("filename") in ("a.txt", "ok.txt")
                ]:
                    S.JOBS.pop(j, None)
            while not S.Q.empty():
                S.Q.get_nowait()
