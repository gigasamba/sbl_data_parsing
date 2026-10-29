"""pipeline.transform.represent.trace 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.trace`."""

from pathlib import Path

from pipeline import config as pc
from pipeline.transform.represent.trace import attach, build_context, build_decisions, on


def selftest():
    import tempfile

    with pc.PIPE.env(PARSE_CONTEXT=None):  # S7c — 설정 객체만 바꿔 끼움(on()이 객체로 읽음)
        assert on() is True and on("1") is True and on("0") is False

    # build_context — PDF 없는 간단 문서: 엔진 요약만, page 키 없음
    dd = {"format": ".txt", "pages": None, "engines": {"eng1": {"ok": True, "chars": 10, "cross_recall": 0.9}}}
    cands = [{"engine": "eng1", "ok": True, "acc": 0.9}]
    rep = {"tables": [], "rep": {"tried": {"eng1": {"sec": 0.5}}}}
    ctx = build_context(None, dd, cands, rep)
    assert ctx == {"format": ".txt", "pages": None, "tables": 0, "engines": {"eng1": {"ok": True, "acc": 0.9, "chars": 10, "sec": 0.5}}}, (
        ctx
    )
    print("[selftest] build_context — PDF 아닌 문서: 엔진 요약만(page 키 없음) 통과")

    # build_decisions — 최소 rep(대표 하나, 표·표준화·fuse 전부 기본값)에서 결정 목록이 짧고 구조가 일정함
    stack = {"parse": {".txt": ["eng1"]}}
    rep2 = {
        "context": ctx,
        "rep": {
            "engine": "eng1",
            "acc": 0.9,
            "candidates": cands,
            "fallback": False,
            "low_n": False,
            "table_fix": {"headers": 0, "tab_rows": 0},
            "standardize": {"on": False, "changed": 0},
        },
    }
    dec = build_decisions(rep2, dd, stack, frozenset(), None)
    steps = [x["step"] for x in dec]
    assert steps == ["engine_scope", "representative", "table_fix", "standardize", "table_std", "fuse"], steps
    for x in dec:
        assert set(x) == {"step", "choice", "reason", "inputs"}
    assert dec[0] == {
        "step": "engine_scope",
        "choice": "all",
        "reason": "형식별 등록 엔진 전부(제한 없음)",
        "inputs": {"format": ".txt", "stack_pool": ["eng1"]},
    }
    assert dec[1]["choice"] == "eng1" and dec[1]["reason"] == "최고 정확도"
    print("[selftest] build_decisions — 해당 없는 결정 지점(ocr_fallback·page_scan·scan_fill·figures)은 빠짐·고정 구조 통과")

    # attach — PARSE_CONTEXT 켰을 때만 represent()가 부르는 진입점(통합) — rep에 두 키가 생김
    rep3 = dict(rep2)
    attach(rep3, dd, cands, stack, frozenset(), None)
    assert "context" in rep3 and "decisions" in rep3
    print("[selftest] attach — rep.context·rep.decisions 둘 다 채움 통과")

    # 쪽 신호 — 실제 작은 PDF(2쪽, 1쪽은 스캔)로 page_signals·scan_pages_detail·rotation_info 연결 확인
    import io

    import fitz
    from PIL import Image

    d = Path(tempfile.mkdtemp())
    pdf = d / "a.pdf"
    png_buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(png_buf, format="PNG")
    doc = fitz.open()
    doc.new_page(width=200, height=200).insert_text((10, 10), "글자층 본문")
    p2 = doc.new_page(width=200, height=200)  # 글자층 없음 + 쪽 전체를 덮는 이미지 — AD12 스캔 쪽(reason=chars)
    p2.insert_image(fitz.Rect(0, 0, 200, 200), stream=png_buf.getvalue())
    doc.save(pdf)
    doc.close()
    dd2 = {"format": ".pdf_text", "pages": 2, "engines": {"pymupdf": {"ok": True, "chars": 5}}}
    cands2 = [{"engine": "pymupdf", "ok": True, "acc": 1.0}]
    rep4 = {"tables": [], "rep": {"tried": {}}}
    ctx2 = build_context(pdf, dd2, cands2, rep4)
    assert ctx2["pages"] == 2 and len(ctx2["page"]) == 2
    assert ctx2["page"][1]["scan_reason"] == "chars" and ctx2["page"][0].get("scan_reason") is None
    assert "image_area_ratio" in ctx2["page"][0] and "garbage_ratio" in ctx2["page"][0]
    rep4["context"] = ctx2
    stack2 = {"parse": {".pdf_text": ["pymupdf"], ".pdf_image": ["rapidocr_ko"]}}
    rep4["rep"].update(
        {
            "engine": "pymupdf",
            "acc": 1.0,
            "candidates": cands2,
            "fallback": False,
            "low_n": False,
            "table_fix": {"headers": 0, "tab_rows": 0},
            "standardize": {"on": False, "changed": 0},
        }
    )
    dec2 = build_decisions(rep4, dd2, stack2, frozenset(), pdf)
    by_step = {x["step"]: x for x in dec2}
    assert by_step["ocr_fallback"]["choice"] is True  # 2쪽이 스캔 쪽이라 OCR 엔진을 합침
    assert by_step["page_scan"]["choice"] == "1쪽" and by_step["page_scan"]["inputs"]["pages"] == [2]
    print("[selftest] 쪽 신호 — 실 PDF(스캔 쪽 1장) page_signals·scan_pages_detail 연결·ocr_fallback·page_scan 결정 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
