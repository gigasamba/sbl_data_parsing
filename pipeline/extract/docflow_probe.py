#!/usr/bin/env python3
"""문서 OCR/무게 검사(2026-10-22 사용자 지정, 2026-10-23 확장) — docflow 워커 배분 판별용.
- PDF: 첫 3쪽 텍스트 레이어 평균 300자 미만 → 스캔 'heavy'
- 오피스 zip(docx/xlsx/xlsm/pptx/docm…): 내장 media 수 ≥ 8개 또는 media 용량 ≥ 800KB → 'heavy'
  (2026-10-23 사용자 지적 — 이미지 많은 docx는 light 오분류, 파일 크기로는 예측 불가라 zip 내부를 본다)
- 판별 불가: 'unknown'
사용: python3 pipeline/extract/docflow_probe.py <파일 경로(내용 기준으로 판별)> [문서 이름]
문서 이름을 주면(run_docs) PYTHONPATH에 코드 폴더가 있을 때 판별 1건을 applog.pipe_event(stage=extract.classify)에 남긴다(이슈 #117 —
metrics.probe = 판별 결과, 소요 = 파일을 열어 보는 시간). 기록이 안 되어도(import 실패·DB 꺼짐) 판별과 stdout 마지막 줄은 그대로다."""

import os
import sys

MEDIA_N, MEDIA_BYTES = 8, 800_000


def probe(path):
    """파일 내용으로 heavy·light 판별(실패는 unknown)."""
    try:
        head = open(path, "rb").read(4)
        if head.startswith(b"PK"):
            import zipfile

            with zipfile.ZipFile(path) as z:
                media = [i for i in z.infolist() if "/media/" in i.filename]
                total = sum(i.file_size for i in media)
            return "heavy" if (len(media) >= MEDIA_N or total >= MEDIA_BYTES) else "light"
        if head.startswith(b"%PDF"):
            import pymupdf

            d = pymupdf.Document(path)
            n = min(3, max(len(d), 1))
            t = sum(len(p.get_text() or "") for p in d[:n])
            return "heavy" if t < 300 * n else "light"
        return "light"
    except Exception:
        return "unknown"


def probe_traced(path, name):
    """probe + extract.classify 한 행. 기록 쪽이 어떻게 실패해도 판별 결과는 돌려준다."""
    try:
        from pathlib import Path

        from common.core import span as SP
        from pipeline.shared import runtrace
    except Exception:  # 코드 폴더가 PYTHONPATH에 없음 — 기록 없이 판별만
        return probe(path)
    size = os.path.getsize(path) if os.path.exists(path) else None  # 파일이 없어도 unknown 행은 남김
    try:
        with runtrace.run("docflow_probe", [name]):
            with SP.span("extract.classify", "extract", doc_id=name, ext=Path(name).suffix.lower(), file_bytes=size) as sp:
                verdict = probe(path)
                sp.add(probe=verdict)
                if verdict == "unknown":
                    sp.result("fail", "doc", SP.safe("probe_unknown"))
                return verdict
    except Exception:
        return probe(path)  # 위 계측은 fail-soft라 여기까지 오는 일은 드묾 — 판별만 다시


def main(argv):
    print(probe_traced(argv[0], argv[1]) if len(argv) > 1 else probe(argv[0]))  # 마지막 줄이 판별 결과(run_docs가 거꾸로 읽음)


if __name__ == "__main__":
    main(sys.argv[1:])
