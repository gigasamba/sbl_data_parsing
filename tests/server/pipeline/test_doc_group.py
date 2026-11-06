"""pipeline.extract.doc_lane_group — 문서 처리 그룹(light·medium·vlm) 규칙 표(PRD rn-01)."""

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf

from pipeline.extract.doc_lane_group import doc_lane_group

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


def test_doc_lane_group_rules():
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
            assert doc_lane_group(t / f, name, size) == want, (f, name, size)
        assert doc_lane_group(t / "text.pdf") == "light"  # 이름·크기를 빼면 파일 이름·실제 크기
        cli = [
            sys.executable,
            str(Path(sys.modules[doc_lane_group.__module__].__file__)),
            str(t / "light.zip"),
            "a b.docx",
            str(300 * KB),
        ]
        # 코드 폴더 없이(PYTHONPATH 뺌 — 기록 import 실패, DB에 흔적 없음) 실행해도 마지막 줄이 그룹
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}  # env 남김 — 하위 프로세스(코드 폴더 없는 실행 시험)
        assert subprocess.run(cli, capture_output=True, text=True, check=True, env=env).stdout.strip() == "medium"


def test_cli_traces_classify():
    """op-01(이슈 #117): 원본 이름을 주면 extract.classify 한 행(group·크기·확장자), 파일이 없으면 fail — 그룹과 마지막 줄은 그대로."""
    import io
    import uuid
    from unittest import mock

    from common.core import jsonlog, span
    from pipeline.extract import doc_lane_group as dpg

    rows, out = [], io.StringIO()
    with (
        tempfile.TemporaryDirectory(prefix="test_docgroup_") as td,
        mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)),
        mock.patch("sys.stdout", out),
        jsonlog.context(run_id=str(uuid.uuid4())),  # 부모가 run_id를 줬으면 새 실행 없이 span만
    ):
        doc = Path(td, "a.docx")  # 그림 많은 오피스 zip
        _zip(doc, [10] * 8)
        dpg.main([str(doc), "원본.docx", "2048"])
        dpg.main([str(Path(td, "none")), "없음.docx", "1"])
        dpg.main([str(doc)])  # 이름 없음 — 기록 없이 판별만
        with mock.patch.object(span, "span", side_effect=RuntimeError("db")):
            dpg.main([str(doc), "원본.docx", "2048"])  # 계측 실패 — 판별은 그대로
    assert out.getvalue().splitlines() == ["vlm", "vlm", "vlm", "vlm"]
    ok, bad = (r for r in rows if r["stage"] == "extract.classify")
    assert ok["doc_id"] == "원본.docx" and ok["ext"] == ".docx" and ok["file_bytes"] == 2048 and ok["metrics"] == {"group": "vlm"}
    assert ok["status"] == "ok" and bad["status"] == "fail" and bad["err"] == "file_missing"
