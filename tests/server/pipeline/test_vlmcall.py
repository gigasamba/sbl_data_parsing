"""pipeline.shared.vlmcall — VLM 호출 한 길(11-04 사용자: VLM 처리 통일). 엔진 qwen_vlm·쪽 VLM 후보정·그림·중첩 그림이 같은
요청(extra_body·제한 시간·재시도·렌더 해상도)으로 나가고, 엔진이 옮긴 쪽은 후보정이 캐시로 다시 쓰는지 — 가짜 로컬 VLM 서버만(외부 접속 없음)."""

import base64
import io
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from common.ai import llm
from common.config.settings import COMMON
from pipeline import config as pc

EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}
ANSWER = "| 항목 | 값 |\n|---|---|\n| 온도 | 25℃ |"
FIG_JSON = json.dumps({"kind": "표", "regions": []}, ensure_ascii=False)  # 그림·중첩 그림 출력 형식(output_schema)을 맞춘 답


def _server(fail_first=0):
    """가짜 VLM 서버 — 받은 요청 본문을 모으고, 처음 fail_first건은 500."""
    seen, lock = [], threading.Lock()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                seen.append(body)
                fail = len(seen) <= fail_first
            text = FIG_JSON if body.get("max_tokens") else ANSWER  # 쪽 옮기기는 출력 상한 없음 · 그림류는 JSON
            out = b'{"error":"x"}' if fail else json.dumps({"choices": [{"message": {"content": text}}], "usage": {}}).encode()
            self.send_response(500 if fail else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _scan_pdf(path, pages=2):
    import fitz

    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=144, height=144)  # 2인치 정사각형 — 글자층 없음(스캔으로 판정)
    d.save(path)


def _png_width(body):
    from PIL import Image

    url = body["messages"][0]["content"][1]["image_url"]["url"]
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).width


def _env(base, raw, common=(), pipe=()):
    c = {"VLM_BASE_URL": base, "VLM_MODEL": "fake-vlm", "VLM_EXTRA_BODY": json.dumps(EXTRA), "VLM_TIMEOUT": "7", **dict(common)}
    return COMMON.env(**c), pc.PIPE.env(PARSE_RAW_ROOT=raw, OCR_DPI="100", PARSE_POST="vlm_page", **dict(pipe))


def test_one_vlm_path():
    from pipeline.shared import vlmcall as V
    from pipeline.transform.figures import nested_figures as nested
    from pipeline.transform.figures import scan_page_vlm as vlm_page
    from pipeline.transform.figures.figure_extract import vlm_fig
    from pipeline.transform.parse.engines.qwen_vlm.parser import parse_qwen_vlm

    d = Path(tempfile.mkdtemp())
    pdf = d / "scan.pdf"
    _scan_pdf(pdf)
    srv, seen = _server()
    timeouts = []
    real_post = llm._post_chat

    def spy(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix, tools=None):
        timeouts.append(timeout)
        return real_post(prof, messages, temperature, max_tokens, json_mode, extra, timeout, guard_prefix, tools)

    ce, pe = _env(f"http://127.0.0.1:{srv.server_address[1]}/v1", str(d / "raw"))
    try:
        with ce, pe, mock.patch.object(llm, "_post_chat", spy):
            # (경로, 부르기, 늘어날 호출 수, 마지막 요청의 max_tokens) — 표 한 줄 = 한 경로
            rows = [
                ("엔진 qwen_vlm", lambda: parse_qwen_vlm(str(pdf)), 2, None),
                ("쪽 VLM 후보정(엔진이 옮긴 쪽은 캐시)", lambda: vlm_page.page_text_pages(pdf), 0, None),
                ("그림 VLM", lambda: vlm_fig(V.render(pdf, [1])[0]), 1, 1500),
                ("중첩 그림", lambda: nested.bbox_regions(V.render(pdf, [2])[0]), 1, 500),
            ]
            for name, call, calls, max_tokens in rows:
                before = len(seen)
                out = call()
                assert len(seen) - before == calls, (name, len(seen) - before)
                for body in seen[before:]:
                    assert body["chat_template_kwargs"] == EXTRA["chat_template_kwargs"], (name, body.keys())  # extra_body 한 칸
                    assert _png_width(body) == 200, name  # 2인치 × extract.ocr.dpi 100
                    assert body.get("max_tokens") == max_tokens, (name, body.get("max_tokens"))
                if name.startswith("엔진"):
                    assert "| 온도 | 25℃ |" in out["text"] and out["trace"]["pages"] == 2, out
                if name.startswith("쪽 VLM"):
                    assert [(i, t) for i, t, _ in out] == [(1, ANSWER), (2, ANSWER)] and all(p["cached"] for _, _, p in out), out
            assert timeouts and set(timeouts) == {7.0}, timeouts  # 호출 1건 제한 = common.models.vlm.timeout
    finally:
        srv.shutdown()


def test_retry_and_page_cap():
    from pipeline.transform.parse.engines.qwen_vlm.parser import parse_qwen_vlm

    d = Path(tempfile.mkdtemp())
    pdf = d / "scan.pdf"
    _scan_pdf(pdf, pages=3)
    for retry, fail_first, ok in ((2, 2, True), (0, 1, False)):  # 재시도 = models.vlm.retry(시도 = retry + 1)
        srv, seen = _server(fail_first)
        ce, pe = _env(
            f"http://127.0.0.1:{srv.server_address[1]}/v1", str(d / f"raw{retry}"), {"VLM_RETRY": str(retry)}, {"VLM_PAGE_MAX": "1"}
        )
        try:
            with ce, pe, mock.patch.object(llm.time, "sleep"):
                try:
                    out = parse_qwen_vlm(str(pdf))
                    assert ok and out["trace"]["pages"] == 1 and out["trace"]["pages_total"] == 3, (
                        out
                    )  # 쪽 상한 transform.vlm.page_max(엔진도)
                except RuntimeError as ex:
                    assert not ok and "VLM 실패" in str(ex), ex  # 재시도 소진 → 엔진 실패(반쪽 결과를 성공으로 남기지 않음)
            assert len(seen) == fail_first + (1 if ok else 0), (retry, len(seen))
        finally:
            srv.shutdown()
