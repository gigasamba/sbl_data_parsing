"""pl-67 — office 엔진(xlsx) 날짜 서식 칸은 YYYY-MM-DD[ HH:MM]로, 숫자 칸은 그대로(엔진마다 날짜 표기가 달라 교차 병합이 시트를 통째로 끼우던 문제)."""

import tempfile
import zipfile
from pathlib import Path

from pipeline.transform.parse.engines.office_stdlib.parser import parse_office

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
CASES = [  # (이름, numFmtId, 사용자 서식 코드, date1904, A1 칸 XML, 기대 A1 글자)
    ("builtin date 14", 14, None, False, "<v>46355</v>", "2026-11-29"),
    ("custom datetime", 200, "yyyy-mm-dd hh:mm", False, "<v>46355.604166666664</v>", "2026-11-29 14:30"),
    ("plain number", 0, None, False, "<v>46355</v>", "46355"),
    ("number custom code", 201, '0.00" days"', False, "<v>46355</v>", "46355"),
    ("date1904", 14, None, True, "<v>44893</v>", "2026-11-29"),
    ("time only", 200, "h:mm", False, "<v>0.604166666666667</v>", "14:30"),
    ("elapsed hours", 200, "[h]:mm", False, "<v>1.5</v>", "36:00"),
    ("formula value", 14, None, False, "<f>MAX(B1:B1)</f>", "=MAX(B1:B1) (계산값) 2026-11-29"),
]


def _xlsx(path, fmt_id, code, d1904, a1):
    fmts = f'<numFmts count="1"><numFmt numFmtId="{fmt_id}" formatCode="{code}"/></numFmts>' if code else ""
    files = {
        "xl/workbook.xml": f'<workbook {NS} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<workbookPr date1904="{int(d1904)}"/><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/styles.xml": f'<styleSheet {NS}>{fmts}<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="{fmt_id}"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<worksheet {NS}><sheetData><row r="1"><c r="A1" s="1">{a1}</c><c r="B1"><v>46355</v></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)


def test_office_dates():
    for name, fmt_id, code, d1904, a1, want in CASES:
        path = Path(tempfile.mkdtemp()) / "t.xlsx"
        _xlsx(path, fmt_id, code, d1904, a1)
        got = parse_office(path)["tables"][0]["grid"][0][0]
        assert got == want, f"{name}: {got!r} != {want!r}"
