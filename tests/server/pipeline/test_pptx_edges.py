"""pipeline.transform.figures.pptx_edges 시험."""

from pathlib import Path

from pipeline import config as pc
from pipeline.transform.figures.pptx_edges import candidate_slides, pptx_edges, slide_signals


def _add_connector(slide, id1, id2, label=""):
    """시험용 — python-pptx에 없는 connector를 슬라이드 XML에 직접 꽂음(selftest 전용)."""
    from lxml import etree

    txt = (
        f'<p:txBody xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:bodyPr/><a:p><a:r><a:t>{label}</a:t></a:r></a:p></p:txBody>'
        if label
        else ""
    )
    xml = (
        f'<p:cxnSp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f'<p:nvCxnSpPr><p:cNvPr id="99" name="연결선"/><p:cNvCxnSpPr><a:stCxn id="{id1}" idx="3"/><a:endCxn id="{id2}" idx="1"/></p:cNvCxnSpPr><p:nvPr/></p:nvCxnSpPr>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom></p:spPr>{txt}</p:cxnSp>'
    )
    slide.shapes._spTree.append(etree.fromstring(xml))


def _add_smartart(slide):
    """시험용 — _is_smartart가 보는 diagram graphicData만 있는 최소 graphicFrame(selftest 전용, 실제 렌더는 못 함)."""
    from lxml import etree

    xml = (
        '<p:graphicFrame xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:nvGraphicFramePr><p:cNvPr id="77" name="SmartArt"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram"/></a:graphic>'
        "</p:graphicFrame>"
    )
    slide.shapes._spTree.append(etree.fromstring(xml))


def selftest():
    import tempfile

    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    a = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(1), Inches(1))
    a.text_frame.text = "Seed"
    b = slide.shapes.add_textbox(Inches(3), Inches(1), Inches(1), Inches(1))
    b.text_frame.text = "Bioreactor"
    _add_connector(slide, a.shape_id, b.shape_id, "48h")
    f = Path(tempfile.mkdtemp()) / "x.pptx"
    prs.save(f)
    edges = pptx_edges(f)
    assert edges == {1: [{"from": "Seed", "to": "Bioreactor", "label": "48h"}]}, edges
    print("[selftest] pptx 연결선(p:cxnSp stCxn/endCxn) → edges 추출 통과")

    # AD20(남은 것) — 2쪽: 도형 PPTX_SHAPES_MIN(4)개 이상·연결선 0개(상자 배치만, 사용자 지적 사례) ·
    # 3쪽: SmartArt graphicFrame
    slide2 = prs.slides.add_slide(prs.slide_layouts[6])
    for i in range(5):
        box = slide2.shapes.add_shape(1, Inches(i), Inches(1), Inches(0.8), Inches(0.8))  # MSO_SHAPE_TYPE RECTANGLE(1)
        box.text_frame.text = f"단계{i}"
    slide3 = prs.slides.add_slide(prs.slide_layouts[6])
    _add_smartart(slide3)
    f2 = Path(tempfile.mkdtemp()) / "y.pptx"
    prs.save(f2)
    sig = slide_signals(f2)
    assert sig[0]["shapes"] == 3 and sig[0]["connectors"] == 1 and not sig[0]["smartart"], sig[0]  # 1쪽(연결선 있음) — 후보 아님
    assert sig[1]["shapes"] == 5 and sig[1]["connectors"] == 0 and not sig[1]["smartart"], sig[1]  # 2쪽
    assert sig[2]["smartart"], sig[2]  # 3쪽
    got = candidate_slides(f2)
    assert got == {2: "shapes_no_connector", 3: "smartart"}, got
    with pc.PIPE.env(PARSE_PPTX_SHAPES_MAX="0", PARSE_PPTX_SMARTART_MAX="0"):  # 끔 — 둘 다 조건 자체를 안 봄(S7c — 설정 객체만 바꿔 끼움)
        assert candidate_slides(f2) == {}
    print("[selftest] AD20(남은 것) — 연결선 없는 도형 배치·SmartArt 슬라이드 후보(candidate_slides) + 상한 env=0으로 끔 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
