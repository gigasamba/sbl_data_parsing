"""pipeline.extract.engines.registry(엔진 등록부 — 엔진 지문 밖) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.extract.engines.registry`(반입 판정 목록 밖 — 일반 시험)."""

from pipeline.extract.engines.registry import CORE, engines, engines_for, installed, select, stacks


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 등록·형식 매핑` 몸통
    e = engines()
    assert (
        len(stacks()) >= 15 and "docling_ocr" in e and "office" in e
    )  # 구조 개편 v4 step1 — 미사용 OCR·오피스 백업 엔진 12개 archive 이동(25→18)
    assert (
        "pdfplumber" in engines_for(".pdf")
        and "calamine" in engines_for(".xlsx")
        and "pptx" in engines_for(".pptx")
        and {"kreuzberg", "anydoc"} <= set(engines_for(".ppt"))
        and "msg_extract" in engines_for(".msg")
    )
    assert all(set(m.FORMATS) == set(m.ENGINES) for _, m in e.values())
    # AD48(10-08, 코디네이터 C 반영) — select("all")은 이 PC·이미지 둘 다 미설치인 엔진을 거르고(docling·
    # unstructured_auto, requirements-image.txt 주석에서 명시 제외) rapidocr_ko처럼 설치된 CORE 엔진은 그대로
    # 남겨야 한다(발견한 회귀 — REQUIRES 하나를 공유하는 rapidocr/rapidocr_ko를 AND로 보면 rapidocr_ko까지
    # "미설치"로 잘못 빠졌었다, REQUIRES_ENGINE로 바로잡음). 이 PC에 docling·unstructured가 미설치인 것이
    # 전제(IMAGE_STACK.md 10-08 확인) — 둘 다 설치돼 있으면 이 assert는 의미가 없어 실패로 알려준다.
    all_engines = select("all")
    assert not installed("docling") and not installed("unstructured_auto"), (
        "이 PC에 docling·unstructured가 설치돼 있음 — AD48 회귀 가드 전제가 깨짐(assert 재설계 필요)"
    )
    assert "docling" not in all_engines and "unstructured_auto" not in all_engines, all_engines
    assert "rapidocr_ko" in all_engines and "rapidocr_ko" in CORE and installed("rapidocr_ko")
    print(f"registry OK — 스택 {len(stacks())} · 엔진 {len(e)}")
