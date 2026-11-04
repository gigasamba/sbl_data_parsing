#!/usr/bin/env python3
"""문서 처리 그룹 판별 — 받은 원본 하나를 light·medium·vlm 중 하나로 가른다(run_docs 레인 배분, PRD rn-01).

사용: python3 pipeline/extract/doc_parsing_group.py <파일> <원본 이름> <크기(바이트)>  → 그룹 한 줄
표준 라이브러리 + pymupdf(PDF일 때만)만 쓴다 — run_docs가 컨테이너 안에서 파일 경로로 바로 실행한다."""

import os
import sys
import zipfile

TEXT_EXTS = {".txt", ".hwpx", ".hwp", ".csv", ".eml", ".msg", ".html", ".htm", ".tsv", ".md", ".json", ".xml", ".log", ".rtf"}
VLM_EXTS = {".pptx", ".ppt"}
MEDIUM_KB = {
    ".docx": 300,
    ".doc": 300,
    ".xlsx": 500,
    ".xlsm": 500,
    ".xls": 500,
    ".pdf": 1024,
}  # 내용 검사가 가볍다고 해도 이 크기(KB) 이상이면 medium
PROBE_EXTS = {".docm", *VLM_EXTS, *MEDIUM_KB}  # 내용을 보는 형식 — 그 밖(mht·이미지 등)은 모르는 형식이라 vlm


def doc_parsing_group(path, name=None, size=None):
    """→ "light" | "medium" | "vlm". name = 원본 파일 이름(확장자 기준, 없으면 path), size = 바이트(없으면 파일 크기).
    내용 검사(heavy): PDF는 첫 3쪽 글자가 쪽당 평균 300자 미만(스캔), 오피스 zip은 내장 그림 8개 이상 또는 합계 800,000바이트 이상.
    검사 실패도 heavy로 본다(보수적으로 vlm)."""
    ext = os.path.splitext(os.path.basename(str(name or path)))[1].lower()
    if ext in TEXT_EXTS:
        return "light"
    if ext not in PROBE_EXTS or ext in VLM_EXTS:
        return "vlm"
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        if head.startswith(b"PK"):
            with zipfile.ZipFile(path) as z:
                media = [i for i in z.infolist() if "/media/" in i.filename]
            heavy = len(media) >= 8 or sum(i.file_size for i in media) >= 800_000
        elif head.startswith(b"%PDF"):
            import pymupdf

            d = pymupdf.Document(path)
            n = min(3, max(len(d), 1))
            heavy = sum(len(p.get_text() or "") for p in d[:n]) < 300 * n
        else:
            heavy = False
    except Exception:
        heavy = True
    if heavy:
        return "vlm"
    size = os.path.getsize(path) if size is None else size
    return "medium" if size // 1024 >= MEDIUM_KB.get(ext, 1 << 30) else "light"


if __name__ == "__main__":
    print(doc_parsing_group(sys.argv[1], sys.argv[2], int(sys.argv[3])))
