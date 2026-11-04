"""pl-42(사용자 10-30) — 지원 형식 .jpeg·.tif·.tiff·.bmp·.mhtml(+ .hwpx 시험), pl-45(11-01·11-03) 2차 확장자(EXT2 표): 형식마다 임시 폴더에 견본을 만들어 파싱한다
(valid_env에 그 형식 파일이 없음 — CLAUDE.md §6-4). 외부 접속 없음 — 쪽 VLM 호출(vlmcall.vlm_page)만 가짜로 바꿔 끼워 이미지가 실제로 읽히는지 본다."""

import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from common.core.paths import STACK_FILE
from pipeline.extract.engines import registry
from pipeline.extract.run_all import engines_for_doc
from pipeline.shared.exts import IMG_EXTS

IMAGES = (".jpeg", ".tif", ".tiff", ".bmp")
NEW = (*IMAGES, ".mhtml", ".hwpx")
TOKEN = "PL42-견본-0731"


def _stack_parse():
    return json.loads(STACK_FILE.read_text(encoding="utf-8"))["parse"]


def test_stack_lists_new_formats():
    """엔진 구성 파일에 형식마다 엔진이 있고, 그 엔진이 형식을 읽는다고 선언한다(FORMATS)."""
    sp = _stack_parse()
    for ext in NEW:
        assert ext in sp, ext
        assert sp[ext] and set(sp[ext]) <= set(registry.engines_for(ext)), (ext, sp[ext], registry.engines_for(ext))
    for ext in IMAGES:  # 이미지는 .jpg와 같은 엔진 — VLM 하나(0.2.0 — 구성에서 OCR 엔진을 뺌, pl-46)
        assert sp[ext] == sp[".jpg"], ext
        assert engines_for_doc(Path("x" + ext), sp, {}, set()) == ["qwen_vlm"], ext
    assert {
        k for k, v in sp.items() if v == ["qwen_vlm"] and not k.startswith(".pdf_")
    } == IMG_EXTS  # 이미지 묶음 한 곳(exts.py)이 구성과 같게
    assert sp[".mhtml"] == sp[".mht"]
    assert set(engines_for_doc(Path("x.mhtml"), sp, {}, set())) == {"mhtml", "kreuzberg"}
    assert engines_for_doc(Path("x.hwpx"), sp, {}, set()) == ["hwpx"]


def test_images_parse():
    """이미지 4종 — 견본 그림을 그 형식으로 저장해 qwen_vlm으로 파싱(VLM 호출만 가짜: 받은 쪽 그림 크기를 돌려줌)."""
    from PIL import Image

    from pipeline.extract.engines.qwen_vlm import parser as Q
    from pipeline.shared import vlmcall as V

    with tempfile.TemporaryDirectory() as td:
        for ext in IMAGES:
            p = Path(td) / ("sample" + ext)
            Image.new("RGB", (64, 32), "white").save(p)
            fake = lambda b, det=None: (f"{TOKEN} {Image.open(io.BytesIO(b)).size}", {})  # 받은 쪽 그림 크기
            with mock.patch.object(V, "vlm_page", fake):
                out = Q.parse_qwen_vlm(str(p))
            assert TOKEN in out["text"] and out["trace"]["pages"] == 1, (ext, out["text"][:80])


def test_mhtml_parse():
    """.mhtml — MIME 묶음(html 한 부분) 견본을 mhtml 엔진으로 파싱."""
    from pipeline.extract.engines.mhtml import parser as M

    body = (
        "From: <Saved by Blink>\r\nSubject: sample\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/related; type="text/html"; boundary="B"\r\n\r\n'
        "--B\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
        f"<html><body><p>{TOKEN}</p></body></html>\r\n--B--\r\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.mhtml"
        p.write_bytes(body.encode("utf-8"))
        out = M.parse_mhtml(str(p))
    assert TOKEN in out["text"], out["text"][:200]


def test_hwpx_parse():
    """.hwpx — Contents/section0.xml(hp:p·hp:t) 하나 든 zip 견본을 hwpx 엔진으로 파싱."""
    from pipeline.extract.engines.hwpx import parser as H

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f"<hp:p><hp:run><hp:t>{TOKEN}</hp:t></hp:run></hp:p></hs:sec>"
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.hwpx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/section0.xml", xml)
        out = H.parse_hwpx(str(p))
    assert TOKEN in out["text"], out["text"][:200]


# pl-45(사용자 11-01·11-03) — 2차 확장자: (확장자, 엔진 구성의 엔진 순서, 견본 만들기 | None).
# None = 순수 파이썬으로 만들 견본이 없는 옛 이진 형식(.xlsb·.dot·.xlt·.pot) — 구성·등록부만 본다(11-03 PC에서 LibreOffice·Excel로 만든 견본을 kreuzberg가 읽음).
# .hwp는 뺌 — kreuzberg에 판독기가 있으나 만든 견본에서 글이 안 나옴(실제 문서 시험 뒤에 넣음).
def _text(body):
    return lambda p: p.write_bytes(body.encode("utf-8"))


def _rtf(p):
    esc = "".join(c if ord(c) < 128 else f"\\u{ord(c) - 65536 if ord(c) > 32767 else ord(c)}?" for c in TOKEN)
    p.write_bytes(("{\\rtf1\\ansi\\deff0 {\\fonttbl{\\f0 Arial;}}\\f0 " + esc + "\\par}").encode("ascii"))


def _ooxml(kind, main):
    """python-docx·python-pptx로 만든 문서의 본문 형식(content type)만 바꿔 매크로·서식·쇼 파일로."""

    def make(p):
        buf = io.BytesIO()
        if kind == "word":
            from docx import Document

            d = Document()
            d.add_paragraph(TOKEN)
            d.save(buf)
            old = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        else:
            from pptx import Presentation

            pr = Presentation()
            pr.slides.add_slide(pr.slide_layouts[5]).shapes.title.text = TOKEN
            pr.save(buf)
            old = b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
        with zipfile.ZipFile(buf) as zin, zipfile.ZipFile(p, "w") as z:
            for i in zin.infolist():
                data = zin.read(i.filename)
                z.writestr(i, data.replace(old, main.encode()) if i.filename == "[Content_Types].xml" else data)

    return make


def _xltx(p):
    """시트 하나(A1 = TOKEN, 인라인 글자)짜리 엑셀 서식 파일."""
    ns = "http://schemas.openxmlformats.org/"
    rel = f"{ns}officeDocument/2006/relationships"
    rels = (
        f'<Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" Type="{rel}/{{}}" Target="{{}}"/></Relationships>'
    )
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="{ns}package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        z.writestr("_rels/.rels", rels.format("officeDocument", "xl/workbook.xml"))
        z.writestr("xl/_rels/workbook.xml.rels", rels.format("worksheet", "worksheets/sheet1.xml"))
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}spreadsheetml/2006/main" xmlns:r="{rel}"><sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>{TOKEN}</t></is></c></row></sheetData></worksheet>',
        )


def _odf(kind, body):
    """오픈문서(content.xml 하나) — body의 {t} 자리에 TOKEN."""
    mime = f"application/vnd.oasis.opendocument.{kind}"
    ns = "urn:oasis:names:tc:opendocument:xmlns"

    def make(p):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), mime)  # 첫 항목·압축 안 함(ODF 규칙)
            z.writestr(
                "META-INF/manifest.xml",
                f'<manifest:manifest xmlns:manifest="{ns}:manifest:1.0" manifest:version="1.2">'
                f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
            )
            z.writestr(
                "content.xml",
                f'<office:document-content xmlns:office="{ns}:office:1.0" xmlns:text="{ns}:text:1.0" xmlns:table="{ns}:table:1.0" '
                f'xmlns:draw="{ns}:drawing:1.0" office:version="1.2"><office:body>{body.format(t=TOKEN)}</office:body></office:document-content>',
            )

    return make


_W, _P, _OX = "application/vnd.ms-word", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument"
_CELL = '<table:table table:name="S1"><table:table-row><table:table-cell office:value-type="string"><text:p>{t}</text:p></table:table-cell></table:table-row></table:table>'
_FRAME = '<draw:page draw:name="p1"><draw:frame><draw:text-box><text:p>{t}</text:p></draw:text-box></draw:frame></draw:page>'
EXT2 = (
    (".docm", ["kreuzberg", "anydoc"], _ooxml("word", f"{_W}.document.macroEnabled.main+xml")),
    (".pptm", ["kreuzberg", "anydoc"], _ooxml("ppt", f"{_P}.presentation.macroEnabled.main+xml")),
    (".rtf", ["anydoc", "kreuzberg"], _rtf),
    (".csv", ["markitdown", "kreuzberg"], _text(f"name,value\n{TOKEN},1\n")),
    (".tsv", ["plaintext", "kreuzberg"], _text(f"name\tvalue\n{TOKEN}\t1\n")),
    (".md", ["plaintext", "markitdown"], _text(f"# 제목\n\n{TOKEN}\n")),
    (".odt", ["anydoc", "kreuzberg"], _odf("text", "<office:text><text:p>{t}</text:p></office:text>")),
    (".ods", ["anydoc", "kreuzberg"], _odf("spreadsheet", f"<office:spreadsheet>{_CELL}</office:spreadsheet>")),
    (".odp", ["anydoc"], _odf("presentation", f"<office:presentation>{_FRAME}</office:presentation>")),
    (".xlsb", ["kreuzberg"], None),
    (".dotx", ["kreuzberg"], _ooxml("word", f"{_OX}.wordprocessingml.template.main+xml")),
    (".xltx", ["kreuzberg"], _xltx),
    (".potx", ["kreuzberg"], _ooxml("ppt", f"{_OX}.presentationml.template.main+xml")),
    (".ppsx", ["kreuzberg"], _ooxml("ppt", f"{_OX}.presentationml.slideshow.main+xml")),
    (".dot", ["kreuzberg"], None),
    (".xlt", ["kreuzberg"], None),
    (".pot", ["kreuzberg"], None),
    (".json", ["plaintext"], _text(f'{{"k": "{TOKEN}"}}\n')),  # .json·.xml·.log = 글 그대로(사용자 11-03 — markitdown 아님)
    (".xml", ["plaintext"], _text(f'<?xml version="1.0" encoding="UTF-8"?><r><k>{TOKEN}</k></r>\n')),
    (".log", ["plaintext"], _text(f"2026-11-03 INFO {TOKEN}\n")),
)


def test_ext2_stack_and_parse():
    """2차 확장자 — 엔진 구성 순서, 등록부가 그 엔진을 고름, 견본이 있으면 구성의 엔진마다 파싱해 글이 나옴(.json·.xml·.log는 파일 그대로)."""
    sp = _stack_parse()
    # 엔진 이름 오타·지운 엔진이면 그 확장자가 조용히 빠짐
    assert set(registry.EXTRA_FORMATS) <= set(registry.engines()), list(registry.EXTRA_FORMATS)
    for ext, want, _ in EXT2:
        assert sp.get(ext) == want, (ext, sp.get(ext))
        assert set(engines_for_doc(Path("x" + ext), sp, {}, set())) == set(want), (ext, registry.engines_for(ext))
    assert ".hwp" not in sp and not registry.engines_for(".hwp")
    with tempfile.TemporaryDirectory() as td:
        for ext, want, make in EXT2:
            if make is None:
                continue
            p = Path(td) / ("sample" + ext)
            make(p)
            for eng in want:
                text = registry.run(eng, p)["text"]
                assert TOKEN in text, (ext, eng, text[:200])
                if ext in (".json", ".xml", ".log"):
                    assert text == p.read_bytes().decode("utf-8"), (ext, text[:200])
