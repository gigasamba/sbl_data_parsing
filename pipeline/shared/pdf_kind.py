"""스캔 PDF 판정 — 글자층이 쪽당 평균 20자 미만이면 pdf_image."""


def pdf_kind(path):
    """스캔 PDF 판정 하나(엔진 고르기·그림 VLM·parse_document 공용) — 글자층이 쪽당 평균 20자 미만이면 pdf_image.
    레인 고르기(run_docs 작업자 배분)는 목적이 달라 extract/doc_lane_group(앞 3쪽 쪽당 300자)을 따로 쓴다."""
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        try:
            n = len(doc)
            chars = sum(len(doc[i].get_textpage().get_text_range().strip()) for i in range(n))
        finally:
            doc.close()
    except Exception:
        try:
            import fitz

            with fitz.open(str(path)) as d:
                n = d.page_count
                chars = sum(len(d[i].get_text().strip()) for i in range(n))
        except Exception:
            return "pdf_text", None  # ponytail: 페이지 텍스트 레이어 확인 불가 — 텍스트형으로 보수적 가정
    if n == 0:
        return "pdf_image", 0
    return ("pdf_image" if chars < 20 * n else "pdf_text"), n
