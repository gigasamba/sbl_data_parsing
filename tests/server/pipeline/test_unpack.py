"""문서 안 문서 꺼내기(pl-63) — pipeline.extract.unpack(받기 단계 `_parts/`) + 첨부 단계의 절·개체 위치 표시."""

import gzip
import io
import os
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


def _docx(objects, same=None, box=None):
    """objects: {이름: 바이트} — 개체마다 문단 하나(앞 문단 글 '앞 글 <i>', same을 주면 모두 그 글 · box를 주면 앞 문단 끝에 그 글의 글상자)."""
    inner = f"<w:r><w:txbxContent><w:p><w:r><w:t>{box}</w:t></w:r></w:p></w:txbxContent></w:r>" if box else ""
    paras = "".join(
        f'<w:p><w:r><w:t>{same or f"앞 글 {i}"}</w:t></w:r>{inner}</w:p><w:p><w:r><w:object><o:OLEObject r:id="rId{i}"/></w:object></w:r></w:p>'
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
    (
        "같은 글 문단 둘 — 둘째 개체는 둘째 자리(pl-65 ⑫)",
        "w.docx",
        _docx({"a.txt": b"a", "b.txt": b"b"}, same="같은 글"),
        [("a.txt", "개체", 1, {"after": "같은 글"}), ("b.txt", "개체", 1, {"after": "같은 글", "nth": 1})],
    ),
    (
        "글상자 속 문단은 따로 세지 않음 — 바깥 문단 글에 이미 듦",
        "x.docx",
        _docx({"a.txt": b"a"}, box="상자"),
        [("a.txt", "개체", 1, {"after": "앞 글 0상자"})],
    ),
    ("같은 내용 첨부는 한 번만(pl-65 ⑨)", "m.eml", _eml({"a.txt": b"same", "b.txt": b"same"}).as_bytes(), [("a.txt", "첨부", 1, {})]),
]


def _enc_zip(files):
    """첫 항목만 '암호' 표시(일반 목적 플래그 0번 비트) — 표준 라이브러리는 암호 zip을 못 만든다."""
    b = bytearray(_zip(files))
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        b[b.find(sig) + off] |= 1
    return bytes(b)


FAILED = [  # (이름, 파일 이름, 내용, 설정, 꺼낸 안 이름, 못 꺼낸 [(안 이름, 까닭)]) — pl-65 ⑥: 성한 것은 꺼내고 못 꺼낸 것은 parts.json failed에
    (
        "못 벗기는 .bin·안 열리는 안 docx",
        "b.xlsx",
        _xlsx(),
        {},
        ["plan.docx"],
        [("oleObject1.bin", "no_unwrap"), ("plan.docx", "cannot_open")],
    ),
    (
        "첨부 압축 안 암호 항목",
        "m.eml",
        _eml({"in.zip": _enc_zip({"a.txt": b"a", "b.txt": b"b"})}).as_bytes(),
        {},
        ["in.zip/b.txt"],
        [("in.zip/a.txt", "encrypted")],
    ),
    (
        "원본 하나의 꺼낸 합계 상한(pl-65 ②)",
        "m.eml",
        _eml({"a.txt": b"12345678", "b.txt": b"abcdefgh"}).as_bytes(),
        {"ARCHIVE_MAX_TOTAL_MB": "0.00001"},  # 약 10바이트
        ["a.txt"],
        [("b.txt", "total_cap")],
    ),
    (
        "첨부 개수 상한",
        "m.eml",
        _eml({f"a{i:02d}.txt": f"{i}".encode() for i in range(11)}).as_bytes(),
        {},
        [f"a{i:02d}.txt" for i in range(10)],
        [("a10.txt", "too_many")],
    ),
    (
        "안 압축은 합계에 안 파일만 셈",
        "z.zip",
        _zip({"in.zip": _zip({"a.txt": b"x" * 100})}),  # in.zip 약 210바이트 — 상자와 안 파일을 둘 다 세면 300을 넘음
        {"ARCHIVE_MAX_TOTAL_MB": str(300 / 1024 / 1024)},
        ["in.zip/a.txt"],
        [],
    ),
    (
        "같은 내용은 합계 상한보다 먼저 거름",
        "m.eml",
        _eml({"a.txt": b"12345678", "b.txt": b"12345678"}).as_bytes(),
        {"ARCHIVE_MAX_TOTAL_MB": "0.00001"},
        ["a.txt"],
        [],
    ),
    ("tar 아닌 안 .gz는 보통 파일", "x.zip", _zip({"a.txt": b"a", "app.log.gz": gzip.compress(b"log")}), {}, ["a.txt", "app.log.gz"], []),
    (
        "압축 개수 상한은 한 줄",
        "m.eml",
        _eml({"in.zip": _zip({f"f{i}.txt": f"{i}".encode() for i in range(5)})}).as_bytes(),
        {"ARCHIVE_MAX_FILES": "2"},
        ["in.zip/f0.txt", "in.zip/f1.txt"],
        [("in.zip/f2.txt 외 2개", "too_many")],
    ),
]


def test_failed_parts():
    with tempfile.TemporaryDirectory() as td, pc.PIPE.env(ATTACH_MAX_DEPTH="2"):  # 표는 기본 깊이 2 기준 — 서버 settings.yaml 값과 상관없이
        for label, fname, data, env, names, failed in FAILED:
            d = Path(td) / label.replace(" ", "_")
            d.mkdir()
            p = d / fname
            p.write_bytes(data)
            with pc.PIPE.env(**env):
                got = unpack.unpack(p, d / "_parts")
            assert [it["name"] for it in got] == names, (label, got)
            miss = unpack.failed_of(p, d / "_parts")
            assert [(f["name"], f["why"]) for f in miss] == failed, (label, miss)
            assert unpack.miss_reason(miss) == "; ".join(f"{n}({w})" for n, w in failed), label


def test_miss_reason_short():
    failed = [{"name": f"f{i}.txt", "why": "too_big"} for i in range(12)]
    assert unpack.miss_reason(failed) == "; ".join(f"f{i}.txt(too_big)" for i in range(10)) + " 외 2개"


def test_unpack_cases():
    with tempfile.TemporaryDirectory() as td, pc.PIPE.env(ATTACH_MAX_DEPTH="2"):  # 표는 기본 깊이 2 기준 — 서버 settings.yaml 값과 상관없이
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
    ("같은 글 둘째 자리(pl-65 ⑫)", "같은 글\n가\n같은 글\n나", {"after": "같은 글", "nth": 1}, "같은 글\n가\n같은 글\n[개체 o]\n나"),
    ("차례가 모자라면 마지막 자리", "같은 글\n가", {"after": "같은 글", "nth": 3}, "같은 글\n[개체 o]\n가"),
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
            return f"{entry['bytes'].decode()} 글이\f열다섯 글자를 넘습니다", False, "plaintext"

        with patch.object(ma, "parse_attachment", fake):
            text, blocks, stats = ma.mail_blocks(p, "제목\n앞 글 0\n끝")
        assert text == "제목\n앞 글 0\n[개체 in.txt]\n끝", text
        # 제목 줄로 시작하고 첨부 글의 쪽 나눔은 줄바꿈(pl-65 ③)
        assert blocks == ["## [개체 in.txt]\ninner 글이\n열다섯 글자를 넘습니다"] and stats["sources"] == ["r.docx#in.txt"], (blocks, stats)


def test_attach_temp_names():
    """같은 첨부를 두 번 파싱해도 임시 파일 이름이 겹치지 않는다(pl-65 ⑧ — 문서 둘이 동시에 돌 때)."""
    from pipeline.transform.parse import parse_engines

    seen = []

    def isolated(eng, tmp, out_json, mode, timeout):
        seen.append(Path(tmp).name)
        Path(out_json).write_text('{"text": "짧음"}', encoding="utf-8")  # 15자 못 넘음 — 캐시에 안 남아 두 번째도 엔진을 부름

    with tempfile.TemporaryDirectory() as td:
        with (
            patch.object(ma, "attach_dir", lambda: Path(td) / "attach"),
            patch.object(ma, "_stack_parse", lambda: {".txt": ["plaintext"]}),
            patch.object(parse_engines, "_isolated", isolated),
        ):
            for _ in range(2):
                ma.parse_attachment({"name": "a.txt", "bytes": b"same"}, store=Path(td) / "raw")
        assert len(seen) == 2 and seen[0] != seen[1], seen
        assert list((Path(td) / "attach").iterdir()) == []  # 다 지움


def test_parts_json_atomic():
    """parts.json은 다 쓴 뒤에만 보인다(pl-65 ④) — 바꿔 놓기(os.replace)가 실패하면 목록이 없다."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "z.zip"
        p.write_bytes(_zip({"a.txt": b"a"}))
        with patch("os.replace", side_effect=OSError("disk")):
            try:
                unpack.unpack(p, Path(td) / "_parts")
            except OSError:
                pass
        assert not (Path(td) / "_parts" / "z.zip" / "parts.json").exists()


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
        p.write_bytes(_zip({"b.txt": b"b"}))  # 내용이 바뀌었는데 고친 시각은 더 옛날 — 원본 sha256으로 본다(pl-65 ⑤)
        os.utime(p, (0, 0))
        assert not unpack.is_fresh(p, Path(td) / "_parts")
        unpack.unpack(p, Path(td) / "_parts")
        j = Path(td) / "_parts" / "z.zip" / "parts.json"
        j.write_text('[{"file": "00001.txt"}]', encoding="utf-8")  # 옛 목록 형식(sha256 없음)은 다시 품
        assert not unpack.is_fresh(p, Path(td) / "_parts")
