"""pipeline.extract.doc_parsing_group — 문서 처리 그룹(light·medium·vlm) 규칙 표(PRD rn-01)."""

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf

from pipeline.extract.doc_parsing_group import doc_parsing_group

KB = 1024


def _pdf(p, text):
    d = pymupdf.open()
    for _ in range(3):
        d.new_page().insert_text((50, 72), text)
    d.save(p)


def _zip(p, media):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", "<w/>")
        for i, n in enumerate(media):
            z.writestr(f"word/media/i{i}.png", b"\0" * n)


def test_doc_parsing_group_rules():
    with tempfile.TemporaryDirectory(prefix="test_docgroup_") as td:
        t = Path(td)
        (t / "plain.bin").write_bytes(b"hello")
        _pdf(t / "scan.pdf", "")  # 글자 없음 — 스캔
        _pdf(t / "text.pdf", ("x" * 50 + "\n") * 8)  # 쪽당 약 400자
        _zip(t / "many.zip", [10] * 8)  # 그림 8개
        _zip(t / "big.zip", [800_000])  # 그림 합계 800,000바이트
        _zip(t / "light.zip", [10] * 7)
        (t / "ole.bin").write_bytes(b"\xd0\xcf\x11\xe0 old office")
        (t / "bad.pdf").write_bytes(b"%PDF broken")
        (t / "bad.zip").write_bytes(b"PK broken")
        rows = [  # (파일, 원본 이름, 크기, 기대)
            ("plain.bin", "a.txt", 50 * 1024 * KB, "light"),  # 글자 형식 — 크기 무관
            ("plain.bin", "a.EML", 1, "light"),  # 확장자는 소문자로
            ("plain.bin", "a.mht", 1, "vlm"),  # 검사 목록 밖 형식
            ("plain.bin", "a.png", 1, "vlm"),
            ("plain.bin", "a", 1, "vlm"),  # 확장자 없음
            ("light.zip", "a.pptx", 1, "vlm"),  # pptx·ppt는 늘 vlm
            ("ole.bin", "a.ppt", 1, "vlm"),
            ("scan.pdf", "a.pdf", 1, "vlm"),  # 첫 3쪽 평균 300자 미만
            ("text.pdf", "a.pdf", 1023 * KB, "light"),
            ("text.pdf", "a.pdf", 1024 * KB, "medium"),  # pdf 1024KB 이상
            ("many.zip", "a.docx", 1, "vlm"),
            ("big.zip", "a.xlsx", 1, "vlm"),
            ("light.zip", "a.docx", 299 * KB, "light"),
            ("light.zip", "a.docx", 300 * KB, "medium"),  # docx·doc 300KB
            ("light.zip", "a.xlsm", 499 * KB, "light"),
            ("light.zip", "a.xlsx", 500 * KB, "medium"),  # xlsx·xlsm·xls 500KB
            ("light.zip", "a.docm", 50 * 1024 * KB, "light"),  # docm은 크기 기준 없음
            ("ole.bin", "a.doc", 299 * KB, "light"),  # zip·pdf가 아닌 내용 — 가벼움
            ("ole.bin", "a.xls", 500 * KB, "medium"),
            ("bad.pdf", "a.pdf", 1, "vlm"),  # 검사 실패 — heavy
            ("bad.zip", "a.docx", 1, "vlm"),
            ("missing", "a.docx", 1, "vlm"),
        ]
        for f, name, size, want in rows:
            assert doc_parsing_group(t / f, name, size) == want, (f, name, size)
        assert doc_parsing_group(t / "text.pdf") == "light"  # 이름·크기를 빼면 파일 이름·실제 크기
        cli = [
            sys.executable,
            str(Path(sys.modules[doc_parsing_group.__module__].__file__)),
            str(t / "light.zip"),
            "a b.docx",
            str(300 * KB),
        ]
        assert subprocess.run(cli, capture_output=True, text=True, check=True).stdout.strip() == "medium"
