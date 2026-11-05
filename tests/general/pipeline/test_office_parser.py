"""pipeline.transform.parse.engines.office_stdlib.parser(엔진 파일 — 엔진 지문) 자기 점검 — S9(D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 사례 `python -m pipeline.transform.parse.engines.office_stdlib.parser`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

import zipfile

from pipeline.transform.parse.engines.office_stdlib.parser import parse_office


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 숨김 시트 읽기·표시 + 저장값 없는 수식(연속 범위 계산값)` 몸통
    import tempfile

    wb = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheets><sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'name="Vis" sheetId="1" r:id="rId1"/><sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'name="Hid" sheetId="2" state="hidden" r:id="rId2"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="/xl/worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>'
    )
    sheet1 = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="n"><v>10</v></c><c r="A2" t="n"><v>20</v></c></row>'
        '<row r="2"><c r="B1"><f>SUM(A1:A2)</f><v></v></c></row></sheetData></worksheet>'
    )
    sheet2 = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>숨김값</t></is></c></row></sheetData></worksheet>'
    )
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/_rels/workbook.xml.rels", rels)
            z.writestr("xl/worksheets/sheet1.xml", sheet1)
            z.writestr("xl/worksheets/sheet2.xml", sheet2)
        tmp = f.name
    r = parse_office(tmp)
    assert "Vis" in r["text"] and "[숨김 시트] Hid" in r["text"] and "숨김값" in r["text"], r
    assert "=SUM(A1:A2)" in r["text"] and "(계산값) 30" in r["text"], r
    print("office self-check OK")

    # AD23 — xlsx mergeCells(가로 병합, B1:C1) 펼침: 좌상단 값이 covered 칸까지 채워지고 merges에 범위 기록
    wb3 = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheets><sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'name="M" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels3 = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="/xl/worksheets/sheet1.xml"/></Relationships>'
    )
    sheet3 = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>항목</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>제목</t></is></c><c r="C1"/></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>행1</t></is></c>'
        '<c r="B2" t="n"><v>1</v></c><c r="C2" t="n"><v>2</v></c></row></sheetData>'
        '<mergeCells count="1"><mergeCell ref="B1:C1"/></mergeCells></worksheet>'
    )
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("xl/workbook.xml", wb3)
            z.writestr("xl/_rels/workbook.xml.rels", rels3)
            z.writestr("xl/worksheets/sheet1.xml", sheet3)
        tmp3 = f.name
    r3 = parse_office(tmp3)
    grid3 = r3["tables"][0]["grid"]
    assert grid3 == [["항목", "제목", "제목"], ["행1", "1", "2"]], grid3  # covered 칸(C1)에 좌상단 값이 채워짐
    assert r3["tables"][0]["merges"] == [{"r": 0, "c": 1, "rowspan": 1, "colspan": 2}], r3["tables"][0]["merges"]
    print("[selftest] AD23 — xlsx mergeCells 가로 병합 펼침·merges 범위 기록 통과")

    # AD23 — docx gridSpan(가로)·vMerge(세로) 동시: 세로 병합(restart→continue, 본문 비어 있음)·가로 병합(gridSpan=2)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    docx_xml = (
        f"<w:document {ns}><w:body><w:tbl>"
        '<w:tr><w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>머리</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>제목</w:t></w:r></w:p></w:tc></w:tr>'
        "<w:tr><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>"
        "<w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl></w:body></w:document>"
    )
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", docx_xml)
        tmp4 = f.name
    r4 = parse_office(tmp4)
    grid4 = r4["tables"][0]["grid"]
    assert grid4 == [["머리", "제목", "제목"], ["머리", "A", "B"]], grid4  # 세로·가로 병합 둘 다 펼쳐짐(continue 칸도 채움)
    assert {(m["r"], m["c"], m["rowspan"], m["colspan"]) for m in r4["tables"][0]["merges"]} == {
        (0, 0, 2, 1),  # 머리 — 세로 병합(2행)
        (0, 1, 1, 2),  # 제목 — 가로 병합(2칸)
    }, r4["tables"][0]["merges"]
    print("[selftest] AD23 — docx gridSpan·vMerge 동시 펼침·merges 범위 기록 통과")
