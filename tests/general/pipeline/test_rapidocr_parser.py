"""pipeline.extract.engines.rapidocr.parser(엔진 파일 — 엔진 지문) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.extract.engines.rapidocr.parser`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

from pipeline.extract.engines.rapidocr.parser import MAX_SIDE, _resized, ocr_threads


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 긴 변 상한 축소 + 되돌림 배율(모델 없이 _resized만)` 몸통
    from PIL import Image

    small = Image.new("RGB", (100, 200), "white")
    arr, back = _resized(small)
    assert arr.shape[:2] == (200, 100) and back == 1.0, (arr.shape, back)  # 보통 크기는 그대로
    big = Image.new("RGB", (6000, 8500), "white")
    arr2, back2 = _resized(big)
    assert max(arr2.shape[:2]) == MAX_SIDE and abs(back2 - 8500 / MAX_SIDE) < 1e-6, (arr2.shape, back2)
    import os  # OC1 — 스레드 수 결정 순서

    keep = {k: os.environ.get(k) for k in ("OCR_THREADS", "OMP_NUM_THREADS")}
    try:
        os.environ.update(OCR_THREADS="2", OMP_NUM_THREADS="5")
        assert ocr_threads() == 2  # 명시값 우선
        os.environ["OCR_THREADS"] = "auto"
        assert ocr_threads() == 5  # 숫자가 아니면 무시(엔진이 죽지 않게)
        os.environ["OCR_THREADS"] = "0"
        assert ocr_threads() == -1  # 0 = 옛 동작(onnxruntime 자동)
        os.environ.pop("OCR_THREADS")
        assert ocr_threads() == 5  # run_all이 맞춘 OMP_NUM_THREADS
        os.environ.pop("OMP_NUM_THREADS")
        assert ocr_threads() >= 1  # resources.plan() 대체
    finally:
        for k, v in keep.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    print("rapidocr self-check OK")
