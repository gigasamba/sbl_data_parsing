"""pl-42(사용자 10-30) — 지원 형식 .jpeg·.tif·.tiff·.bmp·.mhtml(+ .hwpx 시험): 형식마다 임시 폴더에 견본을 만들어 파싱한다
(valid_env에 그 형식 파일이 없음 — CLAUDE.md §6-4). 외부 접속 없음 — VLM 호출(_chat)만 가짜로 바꿔 끼워 이미지가 실제로 읽히는지 본다."""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from common.core.paths import STACK_FILE
from pipeline.extract.engines import registry
from pipeline.extract.run_all import engines_for_doc
from pipeline.stackcfg import over_limit

IMAGES = (".jpeg", ".tif", ".tiff", ".bmp")
NEW = (*IMAGES, ".mhtml", ".hwpx")
TOKEN = "PL42-견본-0731"


def _stack_parse():
    return json.loads(STACK_FILE.read_text(encoding="utf-8"))["parse"]


def test_stack_lists_new_formats():
    """엔진 구성 파일에 형식마다 엔진이 있고(형식당 2개 이하), 그 엔진이 형식을 읽는다고 선언한다(FORMATS)."""
    sp = _stack_parse()
    assert over_limit({"parse": sp}) == []
    for ext in NEW:
        assert ext in sp, ext
        assert sp[ext] and set(sp[ext]) <= set(registry.engines_for(ext)), (ext, sp[ext], registry.engines_for(ext))
    for ext in IMAGES:  # 이미지는 .jpg와 같은 엔진 — OCR 엔진은 ocr_engine 켤 때만이라 기본은 VLM 하나
        assert sp[ext] == sp[".jpg"], ext
        assert engines_for_doc(Path("x" + ext), sp, {}, set()) == ["qwen_vlm"], ext
    assert sp[".mhtml"] == sp[".mht"]
    assert set(engines_for_doc(Path("x.mhtml"), sp, {}, set())) == {"mhtml", "kreuzberg"}
    assert engines_for_doc(Path("x.hwpx"), sp, {}, set()) == ["hwpx"]


def test_images_parse():
    """이미지 4종 — 견본 그림을 그 형식으로 저장해 qwen_vlm으로 파싱(VLM 호출만 가짜: 받은 쪽 그림 크기를 돌려줌)."""
    from PIL import Image

    from pipeline.extract.engines.qwen_vlm import parser as Q

    with tempfile.TemporaryDirectory() as td:
        for ext in IMAGES:
            p = Path(td) / ("sample" + ext)
            Image.new("RGB", (64, 32), "white").save(p)
            with mock.patch.object(Q, "_chat", lambda im: f"{TOKEN} {im.size[0]}x{im.size[1]}"):
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
