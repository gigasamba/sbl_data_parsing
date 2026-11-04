"""pipeline.parse_service — 작업 자식 설정(10-29): 서비스 쪽당 제한·첫 시도 하한·보통 우선순위."""

from unittest import mock

from pipeline import config as pc


def test_job_env_overrides():
    from pipeline import parse_service as S

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
    from pipeline import parse_service as S

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
    from pipeline import parse_service as S

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
                COMMON.env(DATA_PARSING_MAX_MB="1"),
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
