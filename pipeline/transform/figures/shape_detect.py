"""Word·Excel 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음) soffice 호출 전 cheap 문턱.
XML 신호만 보고 "이 문서를 렌더할 가치가 있나"(문서/drawing 단위 bool)만 답한다 — 어느 쪽(페이지)이 실제
도식인지는 soffice 변환 뒤 pptx_render.shape_render_pages()가 벡터 신호(그려진 선·채움, 래스터 이미지 없음)로
가린다. pptx_edges.py의 PPTX_SHAPES_MIN·_is_smartart와 같은 관례 — 원본 XML에서 네임스페이스 문자열만 찾아
오탐 없는 쪽으로(false 가능, 실제 쪽 판단은 렌더 뒤)."""

import re
import zipfile

SHAPE_MIN = 2  # 도형 2개 이상 또는 연결선·SmartArt(ponytail: 단순 문턱, 과·오탐이 보이면 재조정)

_SMARTART = re.compile(rb'uri="[^"]*drawingml/2006/diagram"')

_DOCX_SHAPE = re.compile(rb"<wps:wsp[ >]|<wpc:wpc[ >]|<wpg:wgp[ >]")
_DOCX_CONNECTOR = re.compile(rb"<wps:cNvCnPr[ >]|<a:cxnSp[ >]")
_DOCX_PICTURE = re.compile(rb"<a:blip[ >]")

_XLSX_SHAPE = re.compile(rb"<xdr:sp[ >]|<xdr:cxnSp[ >]|<xdr:grpSp[ >]")
_XLSX_PICTURE = re.compile(rb"<xdr:pic[ >]")


def _read(path, name):
    try:
        with zipfile.ZipFile(path) as z:
            return z.read(name)
    except (KeyError, zipfile.BadZipFile, FileNotFoundError, OSError):
        return b""


def docx_has_shapes(path):
    """word/document.xml에 도형·연결선·SmartArt가 문턱 이상이고, 문서 전체에 삽입 그림(a:blip)이 전혀 없을
    때만 True — 그림이 있는 문서는 도형이 그 그림의 캡션·장식일 수 있어 보수적으로 거른다(쪽 단위가 아니라
    문서 전체 신호라 섞인 문서는 과탐 대신 미탐 쪽으로)."""
    xml = _read(path, "word/document.xml")
    if not xml or _DOCX_PICTURE.search(xml):
        return False
    return bool(_SMARTART.search(xml) or _DOCX_CONNECTOR.search(xml) or len(_DOCX_SHAPE.findall(xml)) >= SHAPE_MIN)


def xlsx_has_shapes(path):
    """xl/drawings/drawingN.xml 중 하나라도 도형·연결선·SmartArt가 문턱 이상이고 그 drawing에 삽입 그림
    (xdr:pic)이 없으면 True(그림과 도형이 섞인 drawing은 보수적으로 거름)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if re.match(r"xl/drawings/drawing\d+\.xml$", n)]
            for n in names:
                xml = z.read(n)
                if _XLSX_PICTURE.search(xml):
                    continue
                if _SMARTART.search(xml) or len(_XLSX_SHAPE.findall(xml)) >= SHAPE_MIN:
                    return True
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        return False
    return False
