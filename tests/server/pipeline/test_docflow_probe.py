"""op-01(이슈 #117): docflow_probe — 판별 결과는 그대로, 문서 이름이 있으면 extract.classify 한 행."""

import io
import tempfile
import uuid
import zipfile
from pathlib import Path
from unittest import mock

from common.core import jsonlog, span
from pipeline.extract import docflow_probe


def _zip(path, media):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "x")
        for i in range(media):
            z.writestr(f"word/media/{i}.png", "p")


def test_probe_verdicts():
    with tempfile.TemporaryDirectory() as tmp:
        few, many, txt = Path(tmp, "a.docx"), Path(tmp, "b.docx"), Path(tmp, "c.txt")
        _zip(few, 2)
        _zip(many, docflow_probe.MEDIA_N)
        txt.write_text("hi", encoding="utf-8")
        assert [docflow_probe.probe(str(p)) for p in (few, many, txt)] == ["light", "heavy", "light"]
        assert docflow_probe.probe(str(Path(tmp, "none.docx"))) == "unknown"


def test_probe_traced_row():
    rows = []
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)):
        doc = Path(tmp, "a.docx")
        _zip(doc, docflow_probe.MEDIA_N)
        with jsonlog.context(run_id=str(uuid.uuid4())):  # 부모가 run_id를 줬으면 새 실행 없이 span만
            assert docflow_probe.probe_traced(str(doc), "원본.docx") == "heavy"
            assert docflow_probe.probe_traced(str(Path(tmp, "none.docx")), "없음.docx") == "unknown"
    ok, bad = (r for r in rows if r["stage"] == "extract.classify")
    assert ok["doc_id"] == "원본.docx" and ok["ext"] == ".docx" and ok["file_bytes"] > 0 and ok["metrics"] == {"probe": "heavy"}
    assert ok["status"] == "ok" and bad["status"] == "fail" and bad["err"] == "probe_unknown"


def test_main_last_line_is_verdict():
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, mock.patch("sys.stdout", out):
        txt = Path(tmp, "c.txt")
        txt.write_text("hi", encoding="utf-8")
        docflow_probe.main([str(txt)])
        docflow_probe.main([str(txt), "c.txt"])  # run_id 없음 — 기록 없이 판별만
    assert out.getvalue().splitlines()[-2:] == ["light", "light"]
