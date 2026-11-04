#!/usr/bin/env python3
"""문서 OCR/무게 검사(2026-10-22 사용자 지정, 2026-10-23 확장) — docflow 워커 배분 판별용.
- PDF: 첫 3쪽 텍스트 레이어 평균 300자 미만 → 스캔 'heavy'
- 오피스 zip(docx/xlsx/xlsm/pptx/docm…): 내장 media 수 ≥ 8개 또는 media 용량 ≥ 800KB → 'heavy'
  (2026-10-23 사용자 지적 — 이미지 많은 docx는 light 오분류, 파일 크기로는 예측 불가라 zip 내부를 본다)
- 판별 불가: 'unknown'
사용: python3 pipeline/extract/doc_parsing_group.py <파일 경로(내용 기준으로 판별)>"""

import sys

MEDIA_N, MEDIA_BYTES = 8, 800_000

try:
    head = open(sys.argv[1], "rb").read(4)
    if head.startswith(b"PK"):
        import zipfile

        with zipfile.ZipFile(sys.argv[1]) as z:
            media = [i for i in z.infolist() if "/media/" in i.filename]
            total = sum(i.file_size for i in media)
        print("heavy" if (len(media) >= MEDIA_N or total >= MEDIA_BYTES) else "light")
    elif head.startswith(b"%PDF"):
        import pymupdf

        d = pymupdf.Document(sys.argv[1])
        n = min(3, max(len(d), 1))
        t = sum(len(p.get_text() or "") for p in d[:n])
        print("heavy" if t < 300 * n else "light")
    else:
        print("light")
except Exception:
    print("unknown")
