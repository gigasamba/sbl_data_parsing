"""pipeline.transform.parse.engines.registry(엔진 등록부 — 엔진 지문 밖) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.transform.parse.engines.registry`(반입 판정 목록 밖 — 일반 시험)."""

from pipeline.transform.parse.engines.registry import CORE, engines, engines_for, installed, select, stacks


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 등록·형식 매핑` 몸통
    e = engines()
    gone = {
        "docling",
        "docling_ocr",
        "docling_vlm",
        "unstructured",
        "unstructured_auto",
        "unstructured_ocr",
        "rapidocr",
        "kreuzberg_ocr",
        "marker_llm",
    }
    assert len(stacks()) >= 11 and "office" in e and not gone & set(e), sorted(gone & set(e))  # pl-31(10-30) — 지운 엔진은 등록 안 됨
    assert CORE <= set(e), sorted(CORE - set(e))  # 핵심 목록의 엔진은 모두 등록됨
    assert (
        "pymupdf" in engines_for(".pdf")
        and "office" in engines_for(".xlsx")
        and "anydoc" in engines_for(".pptx")
        and not {"pdfplumber", "pypdf", "calamine", "pptx", "pymupdf4llm"} & set(e)  # pl-46(0.2.0) — 지운 엔진
        and {"kreuzberg", "anydoc"} <= set(engines_for(".ppt"))
        and "msg_extract" in engines_for(".msg")
    )
    assert all(set(m.FORMATS) == set(m.ENGINES) for _, m in e.values())
    # AD48 — select("all")은 설치된 엔진만, rapidocr_ko처럼 설치된 CORE 엔진은 그대로(REQUIRES를 공유하던 rapidocr 1.x는 10-30 지움 — pl-31)
    all_engines = select("all")
    assert "rapidocr_ko" in all_engines and "rapidocr_ko" in CORE and installed("rapidocr_ko")
    print(f"registry OK — 스택 {len(stacks())} · 엔진 {len(e)}")
