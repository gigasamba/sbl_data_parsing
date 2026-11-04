#!/usr/bin/env python3
"""인식 계열(FAMILY)과 숫자 토큰(nums) — 대표 결과 만들기(represent·fuse·crosscheck·parse_qa)가 쓰는 공용 규칙.

같은 인식 모델·같은 텍스트 레이어를 쓰는 엔진은 같은 곳에서 같이 틀리므로 한 계열(1표)로 센다.
(11-01 — 엔진 비교 요약 명령 main(summary.md·engines.csv·docs.csv)은 지움: 부르는 곳 없음, 비교는 필요할 때 다시 만든다 — PRD e2-10 C7.)
"""

import re

# 인식 계열: 같은 인식 모델(또는 같은 텍스트 레이어 추출기)을 쓰는 엔진 묶음. 목록에 없으면 스택 이름이 계열.
FAMILY = {  # 11-01 — 지운 엔진 easyocr·docling_ocr·marker·marker_llm 줄은 뺌
    # 이미지 인식 모델
    "paddleocr": "paddle",
    "rapidocr": "paddle",
    "rapidocr_ko": "paddle",
    "paddleocr_vl": "paddle-vl",
    "ppstructure": "paddle",
    "mineru": "paddle",  # RapidOCR = Paddle 모델 ONNX
    "tesseract": "tesseract",
    "unstructured_ocr": "tesseract",
    "kreuzberg_ocr": "tesseract",
    "tika": "tesseract",
    "qwen_vlm": "qwen",
    "docling_vlm": "qwen",
    # 텍스트 레이어 추출기
    "pdfplumber": "pdfminer",
    "markitdown": "pdfminer",
    "unstructured": "pdfminer",
    "camelot": "pdfminer",
    "dual_local": "pdfminer",
    "pymupdf": "mupdf",
    "pymupdf4llm": "mupdf",
}

_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def nums(res):
    """출력의 숫자 토큰(쉼표 제거, 1자리 정수·연도처럼 흔한 값도 포함 — 참고 지표라 단순하게)."""
    text = res.get("text", "") + " " + " ".join(t.get("text", "") for t in res.get("tables") or [])
    return {x.replace(",", "") for x in _NUM.findall(text)}
