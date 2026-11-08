"""문서 안 문서 꺼내기(pl-63) — pipeline.extract.unpack(받기 단계 `_parts/`) + 첨부 단계의 절·개체 위치 표시."""

import io
import struct
import tempfile
import zipfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from pipeline import config as pc
from pipeline.extract import unpack
from pipeline.transform.represent import mail_attachments as ma

R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
OLE = R + "/oleObject"
PKG = R + "/package"


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _rels(*rels):
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in rels)
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def _docx(objects):
    """objects: {이름: 바이트} — 개체마다 문단 하나(앞 문단 글 '앞 글 <i>')."""
    paras = "".join(
        f'<w:p><w:r><w:t>앞 글 {i}</w:t></w:r></w:p><w:p><w:r><w:object><o:OLEObject r:id="rId{i}"/></w:object></w:r></w:p>'
        for i in range(len(objects))
    )
    doc = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'xmlns:r="{R}" xmlns:o="urn:schemas-microsoft-com:office:office"><w:body>{paras}</w:body></w:document>'
    )
    files = {
        "word/document.xml": doc,
        "word/_rels/document.xml.rels": _rels(*[(f"rId{i}", PKG, f"embeddings/{n}") for i, n in enumerate(objects)]),
    }
    files.update({f"word/embeddings/{n}": b for n, b in objects.items()})
    return _zip(files)


def _pptx():
    """슬라이드 2장 — 발표 순서는 slide2 → slide1(파일 번호와 다름). slide1에 워드 개체, 차트 엑셀·그림은 개체 아님."""
    pres = f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="{R}"><p:sldIdLst><p:sldId r:id="rA"/><p:sldId r:id="rB"/></p:sldIdLst></p:presentation>'
    return _zip(
        {
            "ppt/presentation.xml": pres,
            "ppt/_rels/presentation.xml.rels": _rels(("rA", R + "/slide", "slides/slide2.xml"), ("rB", R + "/slide", "slides/slide1.xml")),
            "ppt/slides/slide1.xml": "<x/>",
            "ppt/slides/slide2.xml": "<x/>",
            "ppt/slides/_rels/slide1.xml.rels": _rels(("r1", PKG, "../embeddings/memo.docx"), ("r2", R + "/image", "../media/image1.png")),
            "ppt/embeddings/memo.docx": b"not a zip",
            "ppt/charts/_rels/chart1.xml.rels": _rels(("c1", PKG, "../embeddings/Microsoft_Excel_Sheet1.xlsx")),
            "ppt/embeddings/Microsoft_Excel_Sheet1.xlsx": b"chart data",
            "ppt/media/image1.png": b"\x89PNG",
        }
    )


def _xlsx():
    """시트 '요약'·'매출' — 매출 시트에 워드 개체 하나와 못 벗기는 oleObject.bin 하나."""
    wb = f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{R}"><sheets><sheet name="요약" r:id="s1"/><sheet name="매출" r:id="s2"/></sheets></workbook>'
    return _zip(
        {
            "xl/workbook.xml": wb,
            "xl/_rels/workbook.xml.rels": _rels(
                ("s1", R + "/worksheet", "worksheets/sheet1.xml"), ("s2", R + "/worksheet", "worksheets/sheet2.xml")
            ),
            "xl/worksheets/_rels/sheet2.xml.rels": _rels(
                ("o1", OLE, "../embeddings/oleObject1.bin"), ("o2", PKG, "../embeddings/plan.docx")
            ),
            "xl/embeddings/oleObject1.bin": b"not an ole file",
            "xl/embeddings/plan.docx": b"not a zip",
        }
    )


def _eml(attach, nested=None):
    m = EmailMessage()
    m["Subject"] = "바깥"
    m.set_content("본문")
    for name, data in attach.items():
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    if nested is not None:
        if not m.is_multipart():
            m.make_mixed()
        m.attach(nested)  # 이름 없는 전달 메일(message/rfc822)
    return m


def _fwd():
    inner = _eml({"b.txt": b"beta"})
    inner.replace_header("Subject", "전달")
    part = EmailMessage()
    part.set_content(inner)
    return part


CASES = [  # (이름, 파일 이름, 내용, [(안 이름, 종류, 깊이, 위치)])
    ("메일 첨부", "m.eml", _eml({"a.txt": b"alpha"}).as_bytes(), [("a.txt", "첨부", 1, {})]),
    ("메일 안 메일 — 글은 엔진이 읽음, 첨부만", "m.eml", _eml({}, _fwd()).as_bytes(), [("전달.eml/b.txt", "첨부", 2, {})]),
    (
        "메일 → docx → 개체(깊이 2)",
        "m.eml",
        _eml({"r.docx": _docx({"in.xlsx": b"x"})}).as_bytes(),
        [("r.docx", "첨부", 1, {}), ("r.docx/in.xlsx", "개체", 2, {"after": "앞 글 0"})],
    ),
    (
        "깊이 3은 파일 그대로",
        "z.zip",
        _zip({"in.zip": _zip({"r.docx": _docx({"in.xlsx": b"x"})})}),
        [("in.zip/r.docx", "파일", 2, {})],
    ),
    (
        "pptx 개체 — 발표 순서, 차트 엑셀·그림 안 꺼냄",
        "s.pptx",
        _pptx(),
        [("memo.docx", "개체", 1, {"slide": 2, "slides": 2})],
    ),
    (
        "xlsx 개체 — 시트 위치, 못 벗기는 .bin 건너뜀",
        "b.xlsx",
        _xlsx(),
        [("plan.docx", "개체", 1, {"sheet": "매출", "next": None})],
    ),
    ("개체 없는 docx", "e.docx", _docx({}), []),
    ("그림 개체는 안 꺼냄", "p.docx", _docx({"pic.png": b"\x89PNG"}), []),
    (
        "그림은 개수 상한을 먹지 않음",
        "q.docx",
        _docx({**{f"p{i}.png": b"\x89PNG" for i in range(11)}, "a.txt": b"a"}),
        [("a.txt", "개체", 1, {"after": "앞 글 11"})],
    ),
    (
        "파일로 붙은 .eml은 첨부로 둠",
        "m.eml",
        _eml({"old.eml": _eml({"c.txt": b"c"}).as_bytes()}).as_bytes(),
        [("old.eml", "첨부", 1, {}), ("old.eml/c.txt", "첨부", 2, {})],
    ),
]


def test_unpack_cases():
    with tempfile.TemporaryDirectory() as td:
        for label, fname, data, want in CASES:
            d = Path(td) / label.replace(" ", "_")
            d.mkdir()
            p = d / fname
            p.write_bytes(data)
            got = unpack.unpack(p, d / "_parts")
            assert [(it["name"], it["kind"], it["depth"], it["where"]) for it in got] == want, (label, got)
            for it in got:
                assert (d / "_parts" / fname / it["file"]).is_file(), label
            assert ma.parts_of(p)[1] == got, label


def test_depth_setting():
    with tempfile.TemporaryDirectory() as td, pc.PIPE.env(ATTACH_MAX_DEPTH="1"):
        p = Path(td) / "m.eml"
        p.write_bytes(_eml({}, _fwd()).as_bytes())
        assert [it["name"] for it in unpack.unpack(p, Path(td) / "_parts")] == []  # 깊이 1 — 안 메일은 열지 않음(글은 엔진이 읽음)


def test_not_a_box():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.pdf"
        p.write_bytes(b"%PDF-1.4")
        assert unpack.unpack(p, Path(td) / "_parts") == [] and not (Path(td) / "_parts").exists()
        assert ma.mail_blocks(p, "본문") == ("본문", [], {"n": 0, "parsed": 0, "cached": 0, "sources": []})


def test_ole_native():
    body = b"memo text"
    tmp = b"C:\\t\\memo.txt\0"
    raw = struct.pack("<IH", 0, 2) + "메모.txt".encode("cp949") + b"\0" + b"C:\\memo.txt\0" + struct.pack("<I", 0x30000)
    raw += struct.pack("<I", len(tmp)) + tmp + struct.pack("<I", len(body)) + body
    assert unpack._native(raw) == ("메모.txt", body)
    assert unpack._unwrap("oleObject1.bin", b"junk") is None


MARKS = [  # (이름, 본문, 위치, 기대 본문)
    ("슬라이드 끝", "s1\fs2 글\fs3", {"slide": 2, "slides": 3}, "s1\fs2 글\n[개체 o]\n\fs3"),
    ("쪽 수가 안 맞으면 안 넣음", "s1\fs2", {"slide": 2, "slides": 3}, "s1\fs2"),
    ("시트 끝", "요약\n1 2\n매출\n3 4\n비용\n5", {"sheet": "매출", "next": "비용"}, "요약\n1 2\n매출\n3 4\n[개체 o]\n비용\n5"),
    ("마지막 시트", "요약\n1\n매출\n3", {"sheet": "매출", "next": None}, "요약\n1\n매출\n3\n[개체 o]"),
    ("문단 뒤", "가\n앞 글 0 끝\n나", {"after": "앞 글 0"}, "가\n앞 글 0 끝\n[개체 o]\n나"),
    ("못 찾음", "가\n나", {"after": "없는 글"}, "가\n나"),
]


def test_place_marks():
    for label, text, where, want in MARKS:
        assert ma.place_marks(text, [{"name": "o", "where": where}]) == want, label


def test_blocks_and_marks():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "r.docx"
        p.write_bytes(_docx({"in.txt": b"inner"}))
        unpack.unpack(p, Path(td) / "_parts")

        def fake(entry, store=None):
            return f"{entry['bytes'].decode()} 글이 열다섯 글자를 넘습니다", False, "plaintext"

        with patch.object(ma, "parse_attachment", fake):
            text, blocks, stats = ma.mail_blocks(p, "제목\n앞 글 0\n끝")
        assert text == "제목\n앞 글 0\n[개체 in.txt]\n끝", text
        assert blocks == ["[개체 in.txt]\ninner 글이 열다섯 글자를 넘습니다"] and stats["sources"] == ["r.docx#in.txt"], (blocks, stats)


def test_unsupported_method():
    """지원 안 하는 압축 방식(Deflate64 등 — NotImplementedError)은 거기까지 꺼내고 묶음을 멈추지 않는다."""
    from pipeline.extract import archive

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "w.zip"
        p.write_bytes(_zip({"a.txt": b"a", "b.txt": b"b"}))
        real = archive._read

        def read(a, kind, item):
            if item.filename == "b.txt":
                raise NotImplementedError("That compression method is not supported")
            return real(a, kind, item)

        with patch.object(archive, "_read", read):
            assert [it["name"] for it in unpack.unpack(p, Path(td) / "_parts")] == ["a.txt"]


def test_fresh():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "z.zip"
        p.write_bytes(_zip({"a.txt": b"a"}))
        assert not unpack.is_fresh(p, Path(td) / "_parts")
        unpack.unpack(p, Path(td) / "_parts")
        assert unpack.is_fresh(p, Path(td) / "_parts")
