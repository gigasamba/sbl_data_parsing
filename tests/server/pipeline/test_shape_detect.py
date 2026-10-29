"""pipeline.transform.figures.shape_detect 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.shape_detect`."""

from pipeline.transform.figures.shape_detect import docx_has_shapes, xlsx_has_shapes


def selftest():
    import tempfile
    from pathlib import Path

    import docx
    import openpyxl
    from lxml import etree

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"

    def _wsp(shape_id):
        return (
            f'<w:r xmlns:w="{W}"><w:drawing><wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
            f'<wp:extent cx="900000" cy="500000"/><wp:docPr id="{shape_id}" name="s{shape_id}"/>'
            f'<a:graphic xmlns:a="{A}"><a:graphicData uri="{WPS}"><wps:wsp xmlns:wps="{WPS}">'
            f'<wps:cNvPr id="{shape_id}" name="s{shape_id}"/><wps:cNvSpPr/><wps:spPr/><wps:bodyPr/>'
            f"</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>"
        ).encode()

    d = Path(tempfile.mkdtemp())
    empty = d / "empty.docx"
    docx.Document().save(empty)
    assert docx_has_shapes(empty) is False
    print("[selftest] docx — 도형 없는 문서는 False 통과")

    doc = docx.Document()
    p = doc.add_paragraph()
    for i in range(2):
        p._p.append(etree.fromstring(_wsp(10 + i)))
    shaped = d / "shaped.docx"
    doc.save(shaped)
    assert docx_has_shapes(shaped) is True
    print("[selftest] docx — wps:wsp 2개(문턱) → True 통과")

    assert docx_has_shapes(d / "no-such.docx") is False
    print("[selftest] docx — 없는 파일 → False(예외 없음) 통과")

    wb = openpyxl.Workbook()
    wb.active["A1"] = "x"
    plain = d / "plain.xlsx"
    wb.save(plain)
    assert xlsx_has_shapes(plain) is False
    print("[selftest] xlsx — drawing 없는 워크북은 False 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
