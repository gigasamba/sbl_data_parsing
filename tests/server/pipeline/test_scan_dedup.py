"""pipeline.transform.represent.scan_dedup 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.scan_dedup`."""

from pipeline.transform.figures import vlm_page as vp_mod
from pipeline.transform.represent.scan_dedup import _extra_values, dedup, on, pick


def selftest():
    # pick() — 기본 쪽 VLM 우선(OCR이 믿을 만해도 VLM이 빈약하지 않으면 VLM)
    w, lo, src = pick("OCR 본문 저품질 글", "쪽 VLM 전사 더 정돈된 글")
    assert src == "vlm" and w.startswith("쪽 VLM 전사") and lo == "OCR 본문 저품질 글"
    # OCR 신뢰도 높고 VLM이 절반도 안 되면(빈약) OCR
    w2, l2, src2 = pick("표 항목 1 2 3 4 5 6 7 8 9 10 금액 500,000원 합계", "불")
    assert src2 == "ocr" and w2.startswith("표 항목")
    print("[selftest] pick() — 기본 쪽 VLM 우선 · VLM 빈약하면 OCR 통과")

    # 진 쪽에만 있는 숫자·ID는 이긴 쪽 글 끝에 보존(값 재현율 하락 0)
    w3, l3, src3 = pick("계약 D-2024-123 금액 500,000", "정돈된 쪽 전사 금액 500,000")
    assert src3 == "vlm" and "500000" in w3.replace(",", "") or "500,000" in w3
    assert "d-2024-123" in w3.lower()  # OCR에만 있던 ID — VLM 승자 글 끝에 남음
    print("[selftest] 진 쪽에만 있는 숫자·ID 보존 통과")

    assert on() is False and on("1") is True and on("0") is False
    print("[selftest] PARSE_DEDUP_SCAN 기본 꺼짐 통과")

    # dedup() — OCR이 못 읽은 쪽은 중복 아님(그대로 VLM으로 채움)
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    png = d / "scan.png"
    from PIL import Image

    Image.new("RGB", (40, 40), "white").save(png)
    orig = vp_mod.vlm_page
    try:
        vp_mod.vlm_page = lambda img, det=None: ("새로 읽은 쪽 글", {"cached": False})
        new_base, alt, provs, changed, skip = dedup("", png)
        assert new_base == "새로 읽은 쪽 글" and alt == {} and changed == 0 and len(provs) == 1 and skip is None
    finally:
        vp_mod.vlm_page = orig
    print("[selftest] dedup() — OCR이 못 읽은 쪽은 중복 아님(그대로 채움, page_alt 없음) 통과")

    # dedup() — 같은 쪽에 둘 다 있으면 하나만 base, 다른 하나는 page_alt
    try:
        vp_mod.vlm_page = lambda img, det=None: ("쪽 VLM 전사(정돈됨) D-9999", {"cached": False})
        new_base2, alt2, provs2, changed2, skip2 = dedup("OCR 저품질 글", png)
        assert new_base2.startswith("쪽 VLM 전사(정돈됨)") and changed2 == 1 and skip2 is None
        assert alt2[1] == {"from": "ocr", "text": "OCR 저품질 글"}
    finally:
        vp_mod.vlm_page = orig
    print("[selftest] dedup() — 같은 쪽 OCR+VLM 중 하나만 base, 다른 하나는 page_alt 통과")

    # 독립 검토 MAJOR-1 — 3쪽 중 2쪽이 OCR 박스 0개(빈 쪽)일 때 \f로만 나누면 뒤 쪽 번호가 밀려 1쪽·3쪽을 엉뚱하게
    # 비교한다. boxes(실제 "page" 번호)를 주면 빈 쪽이 있어도 밀리지 않아야 한다.
    orig_pages = vp_mod.page_text_pages
    try:
        vp_mod.page_text_pages = lambda doc_path: [(1, "VLM 쪽1", {}), (2, "VLM 쪽2(빈 쪽 보강)", {}), (3, "VLM 쪽3", {})]
        boxes = [{"page": 1, "text": "OCR 쪽1 글"}, {"page": 3, "text": "OCR 쪽3 글"}]  # 2쪽은 박스 0개(빈 쪽)
        base_collapsed = "OCR 쪽1 글\fOCR 쪽3 글"  # _ocr_out 실제 동작 — 빈 쪽은 \f에 안 잡힘(\f 1개뿐)
        nb, alt3, provs3, changed3, skip3 = dedup(base_collapsed, d / "dummy.pdf", boxes=boxes)
        assert skip3 is None and changed3 == 2  # 1·3쪽은 OCR+VLM 둘 다 있어 dedup(2쪽은 보강이라 안 셈)
        parts = nb.split("\f")
        assert len(parts) == 3 and parts[1] == "VLM 쪽2(빈 쪽 보강)"  # 2쪽 번호가 안 밀림 — 1·3쪽 글과 안 섞임
        assert 2 not in alt3  # 2쪽은 비교(dedup)가 아니라 그대로 채움 — page_alt 없음
        assert "OCR 쪽1" not in parts[1] and "OCR 쪽3" not in parts[1] and "쪽3" not in parts[0]
    finally:
        vp_mod.page_text_pages = orig_pages
    print("[selftest] 독립 검토 MAJOR-1 — 3쪽 중 2쪽 빈 쪽이어도 boxes로 쪽 번호 안 밀림 통과")

    # 독립 검토 MAJOR-1 — boxes 없고 \f 개수가 문서의 실제 쪽 수와 다르면(쪽 번호 확정 불가) dedup을 건너뛴다
    import fitz

    pdf3 = d / "three_pages.pdf"
    doc3 = fitz.open()
    for i in range(3):
        doc3.new_page(width=200, height=200).insert_text((10, 10), f"쪽{i + 1}")
    doc3.save(pdf3)
    doc3.close()
    try:
        vp_mod.page_text_pages = lambda doc_path: [(1, "v1", {}), (2, "v2", {}), (3, "v3", {})]
        base_mismatch = "쪽A 글\f쪽B 글"  # \f 1개(2조각) — 실제 문서는 3쪽
        nb4, alt4, provs4, changed4, skip4 = dedup(base_mismatch, pdf3, boxes=None)
        assert nb4 == base_mismatch and alt4 == {} and changed4 == 0 and skip4 is not None and len(provs4) == 3
    finally:
        vp_mod.page_text_pages = orig_pages
    print("[selftest] 독립 검토 MAJOR-1 — \\f 개수 ≠ 실제 쪽 수면 쪽 번호 확정 불가로 dedup 건너뜀(원문 그대로) 통과")

    # 독립 검토 MINOR — 전각↔반각 등 표기만 다른 같은 값은 "진 쪽에만 있다"고 중복 덧붙이지 않는다
    extra_same = _extra_values("금액 500，000 비율 95％", "정돈된 전사 금액 500,000 비율 95%")
    assert extra_same == [], extra_same
    print("[selftest] 독립 검토 MINOR — canon_symbols 정규화로 표기만 다른 값은 중복 안 붙음 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
