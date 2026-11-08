"""표준 라이브러리 zip+XML — 의존성 0 (오피스 정답 기준)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine office <문서> <out.json>
"""
import re
import zipfile
from xml.etree import ElementTree as ET

from pipeline.transform.parse.engines._common.contract import _table_facts, _mk_table, TABLE_GRID_MAX_ROWS


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_FORMULA_RANGE = re.compile(
    r"^(SUM|AVERAGE|MIN|MAX|COUNT)\(\s*(?:'([^']+)'|([A-Za-z0-9_]+))?!?\$?([A-Za-z]+)\$?(\d+):\$?([A-Za-z]+)\$?(\d+)\s*\)$", re.I)

def _docx_table_grid(tbl):
    """AD23 — <w:tbl> → (grid, merges): gridSpan(가로 병합)·vMerge(세로 병합) 칸을 펼쳐 같은 값으로 채우고
    원래 병합 시작 칸의 범위를 merges(0-base, {r,c,rowspan,colspan})에 기록. vMerge "continue" 칸(워드가 본문을
    안 채워 둠)은 같은 열의 가장 최근 "restart" 칸 글자를 그대로 채운다.
    ponytail: gridSpan 경계가 행마다 달라지는 불규칙 표(열 모양이 안 맞는 드문 경우)까지는 안 봄 — 필요하면
    OOXML tblGrid(gridCol) 기준 전체 재구성으로 올림."""
    rows_meta, ncols = [], 0
    for tr in tbl.findall(_W + "tr"):
        col, cells = 0, []
        for tc in tr.findall(_W + "tc"):
            tcPr = tc.find(_W + "tcPr")
            colspan, vmerge = 1, None
            if tcPr is not None:
                gs = tcPr.find(_W + "gridSpan")
                if gs is not None:
                    try:
                        colspan = int(gs.get(_W + "val") or 1)
                    except ValueError:
                        colspan = 1
                vm = tcPr.find(_W + "vMerge")
                if vm is not None:
                    vmerge = vm.get(_W + "val") or "continue"
            text = "".join(n.text or "" for n in tc.iter(_W + "t"))
            cells.append((col, colspan, text, vmerge))
            col += colspan
        ncols = max(ncols, col)
        rows_meta.append(cells)
    grid = [["" for _ in range(ncols)] for _ in rows_meta]
    open_col, info = {}, {}       # open_col: col → (시작 행, colspan, 글자) · info: (행,칸) → {rowspan, colspan}
    for r, cells in enumerate(rows_meta):
        for col, colspan, text, vmerge in cells:
            if vmerge == "continue" and col in open_col:
                sr, scs, stext = open_col[col]
                for cc in range(col, min(col + scs, ncols)):
                    grid[r][cc] = stext
                info[(sr, col)]["rowspan"] += 1
                continue
            for cc in range(col, min(col + colspan, ncols)):
                grid[r][cc] = text
            if colspan > 1 or vmerge == "restart":
                info[(r, col)] = {"rowspan": 1, "colspan": colspan}
            if vmerge == "restart":
                open_col[col] = (r, colspan, text)
            elif col in open_col:
                del open_col[col]
    merges = [{"r": r, "c": c, **v} for (r, c), v in info.items() if v["rowspan"] > 1 or v["colspan"] > 1]
    return grid, merges


def _docx_stdlib(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    texts, tables, grids = [], [], []
    body = root.find(_W + "body")
    for el in body:
        if el.tag == _W + "p":
            t = "".join(n.text or "" for n in el.iter(_W + "t"))
            if t.strip():
                texts.append(t)
        elif el.tag == _W + "tbl":
            rows = [["".join(n.text or "" for n in tc.iter(_W + "t"))
                     for tc in tr.findall(_W + "tc")] for tr in el.findall(_W + "tr")]
            tables.append(rows)
            texts.append(" ".join(c for r in rows for c in r))
            grids.append(_docx_table_grid(el))   # AD23 — rows(기존, 위치 기반)는 그대로, 병합 펼침 그리드는 따로
    return texts, tables, grids

def _col_num(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n

def _col_letters(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def _sheet_paths(z):
    """workbook.xml 선언 순서로 (이름, 숨김여부, xml 경로) — 숨김/매우숨김 시트도 포함. 못 읽으면 None(파일 목록으로 대체)."""
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return None
    targets = {rel.get("Id"): rel.get("Target") for rel in rels}
    out = []
    for sh in wb.iter(_S + "sheet"):
        target = targets.get(sh.get(_R + "id"))
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        out.append((sh.get("name"), (sh.get("state") or "visible") in ("hidden", "veryHidden"), path))
    return out or None

def _sheet_numbers(root):
    """셀 주소 → 수치 값(숫자 셀만, 수식 셀 제외) — 다른 시트의 수식 범위 계산 재료."""
    out = {}
    for c in root.iter(_S + "c"):
        if c.get("t") in ("s", "inlineStr", "str") or c.find(_S + "f") is not None:
            continue
        v = c.find(_S + "v")
        if v is not None and (v.text or "").strip():
            try:
                out[c.get("r")] = float(v.text)
            except ValueError:
                pass
    return out

def _eval_formula(formula, cur_sheet, numbers_by_sheet):
    """SUM·AVERAGE·MIN·MAX·COUNT + 연속 범위만 계산(그 외·범위 안에 수치 아닌 칸이 있으면 None — 수식 글자만 남김)."""
    m = _FORMULA_RANGE.match(formula.strip())
    if not m:
        return None
    func, s1, s2, c1, r1, c2, r2 = m.groups()
    nums = numbers_by_sheet.get(s1 or s2 or cur_sheet)
    if nums is None:
        return None
    vals = []
    for col in range(min(_col_num(c1), _col_num(c2)), max(_col_num(c1), _col_num(c2)) + 1):
        for row in range(min(int(r1), int(r2)), max(int(r1), int(r2)) + 1):
            ref = _col_letters(col) + str(row)
            if ref not in nums:
                return None
            vals.append(nums[ref])
    if not vals:
        return None
    func = func.upper()
    val = (sum(vals) if func == "SUM" else sum(vals) / len(vals) if func == "AVERAGE"
           else min(vals) if func == "MIN" else max(vals) if func == "MAX" else len(vals))
    return int(val) if val == int(val) else round(val, 4)

_DATE_IDS = {14: "d", 15: "d", 16: "d", 17: "d", 18: "t", 19: "t", 20: "t", 21: "t", 22: "d",
             45: "t", 46: "e", 47: "t"}                    # 기본 날짜·시각 서식 번호 → d(날짜 있음)·t(시각만)·e(경과 시간)
_DATE_IDS.update({i: "d" for i in (*range(27, 37), *range(50, 59))})   # 동아시아(한국어 엑셀) 내장 서식 — numFmt 없이 씀
_DATE_IDS.update({32: "t", 33: "t"})                       # 그중 h"시" mm"분"[ ss"초"]는 시각만
_FMT_LITERAL = re.compile(r'"[^"]*"|\[(?![hms]+\])[^\]]*\]|[\\_*].', re.I)    # 따옴표 글자·[색/조건]·이스케이프는 날짜 기호가 아님


def _date_styles(z):
    """styles.xml cellXfs 순번 → "d"/"t"(날짜·시각 서식인 칸만) + workbook.xml date1904 기준일.
    날짜는 어느 엔진이든 YYYY-MM-DD[ HH:MM] 한 가지로 보인다(pl-67 — 사용자 11-08)."""
    import datetime as dt
    try:
        base = dt.datetime(1904, 1, 1) if re.search(rb'date1904="(1|true)"', z.read("xl/workbook.xml")) else dt.datetime(1899, 12, 30)
    except KeyError:
        base = dt.datetime(1899, 12, 30)
    try:
        st = ET.fromstring(z.read("xl/styles.xml"))
    except (KeyError, ET.ParseError):
        return {}, base
    kinds = dict(_DATE_IDS)
    for n in st.iter(_S + "numFmt"):
        code = _FMT_LITERAL.sub("", (n.get("formatCode") or "").split(";")[0]).lower()
        fid = int(n.get("numFmtId") or 0)
        if re.search(r"\[[hms]+\]", code):
            kinds[fid] = "e"                                   # 경과 시간 [h]:mm — 24시간 넘어도 그대로
        elif re.search(r"[dy]", code) or (re.search(r"m", code) and not re.search(r"[hs]", code)):
            kinds[fid] = "d"
        elif re.search(r"[hs]", code):
            kinds[fid] = "t"
        else:
            kinds.pop(fid, None)                               # 같은 번호를 숫자 서식으로 다시 정의
    xfs = st.find(_S + "cellXfs")
    styles = {i: kinds[int(xf.get("numFmtId") or 0)] for i, xf in enumerate(xfs if xfs is not None else [])
              if int(xf.get("numFmtId") or 0) in kinds}
    return styles, base


def _as_date(c, raw, dates):
    """날짜·시각 서식 칸의 일련번호 → 2026-11-29 · 2026-11-29 14:30 · 14:30(초는 0이 아닐 때만). 아니면 raw 그대로.
    ponytail: 1900-03-01 이전(일련번호 60 이하, 엑셀 윤년 버그)은 하루 어긋남 — 그런 문서가 나오면 보정."""
    styles, base = dates
    kind = styles.get(int(c.get("s") or 0))
    if kind is None:
        return raw
    try:
        secs = round(float(raw) * 86400)
    except (TypeError, ValueError):
        return raw
    if not 0 <= secs < 2958466 * 86400:                       # 9999-12-31까지
        return raw
    import datetime as dt
    d = base + dt.timedelta(seconds=secs)
    hm = d.strftime("%H:%M") + (d.strftime(":%S") if d.second else "")
    if kind == "t":
        return hm
    if kind == "e":
        return f"{secs // 3600:02d}:{secs // 60 % 60:02d}" + (f":{secs % 60:02d}" if secs % 60 else "")
    return d.strftime("%Y-%m-%d") + ("" if hm == "00:00" else " " + hm)


def _cell_value(c, sheet_key, ss, numbers_by_sheet, dates):
    """<c> 하나 → 글자값(수식·공유문자열·inlineStr·일반값) — 기존 _xlsx_stdlib 본문 루프에서 그대로 옮김
    (AD23 — _xlsx_table_grid와 공유, 동작 불변). 날짜 서식 칸은 _as_date로(pl-67)."""
    f_el, v = c.find(_S + "f"), c.find(_S + "v")
    it = c.find(f".//{_S}t")
    if f_el is not None and not (v is not None and (v.text or "").strip()):
        val = _eval_formula(f_el.text or "", sheet_key, numbers_by_sheet)
        return f"={(f_el.text or '').strip()}" + (f" (계산값) {_as_date(c, val, dates)}" if val is not None else "")
    if c.get("t") == "s" and v is not None:
        return ss[int(v.text)]
    if it is not None:
        return "".join(t.text or "" for t in c.iter(_S + "t"))   # 서식 조각(<r>)이 여러 개인 inlineStr
    if v is not None and c.get("t") in (None, "n"):
        return _as_date(c, v.text or "", dates)
    return (v.text or "") if v is not None else ""

_CELL_REF = re.compile(r"^([A-Za-z]+)(\d+)$")

def _xlsx_table_grid(root, sheet_key, ss, numbers_by_sheet, dates):
    """AD23 — 시트 XML → (조밀 그리드, 병합): 실제 칸 참조(r="B2")로 행·열을 채우고(참조 없는 칸은 ""),
    mergeCells 범위는 좌상단 글자로 펼쳐 같은 값을 채운다. 기존 rows(위치 기반, 성긴 칸 — 빈 칸은 XML에
    없을 수 있어 순서가 실제 열과 안 맞을 수 있음)와는 독립 — 이 그리드는 표 원본 보존(tables_std)에만 쓴다."""
    cell_map, max_r, max_c = {}, 0, 0
    for c in root.iter(_S + "c"):
        m = _CELL_REF.match(c.get("r") or "")
        if not m:
            continue
        col, row = _col_num(m.group(1)), int(m.group(2))
        cell_map[(row, col)] = _cell_value(c, sheet_key, ss, numbers_by_sheet, dates)
        max_r, max_c = max(max_r, row), max(max_c, col)
    if not cell_map:
        return [], []
    grid = [["" for _ in range(max_c)] for _ in range(max_r)]
    for (r, c), v in cell_map.items():
        grid[r - 1][c - 1] = v
    merges = []
    for mc in root.iter(_S + "mergeCell"):
        a, _, b = (mc.get("ref") or "").partition(":")
        ma, mb = _CELL_REF.match(a), _CELL_REF.match(b)
        if not (ma and mb):
            continue
        c1, r1 = _col_num(ma.group(1)), int(ma.group(2))
        c2, r2 = _col_num(mb.group(1)), int(mb.group(2))
        val = grid[r1 - 1][c1 - 1]
        for rr in range(r1, r2 + 1):
            for cc in range(c1, c2 + 1):
                grid[rr - 1][cc - 1] = val
        rowspan, colspan = r2 - r1 + 1, c2 - c1 + 1
        if rowspan > 1 or colspan > 1:
            merges.append({"r": r1 - 1, "c": c1 - 1, "rowspan": rowspan, "colspan": colspan})
    return grid, merges

def _xlsx_stdlib(path):
    with zipfile.ZipFile(path) as z:
        try:
            ss = ["".join(t.text or "" for t in si.iter(_S + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_S + "si")]
        except KeyError:
            ss = []
        sheets = _sheet_paths(z) or [(None, False, n) for n in
                                      sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))]
        roots = {}
        for _, _, sh in sheets:
            try:
                roots[sh] = ET.fromstring(z.read(sh))
            except (KeyError, ET.ParseError):
                roots[sh] = None
        dates = _date_styles(z)
        numbers_by_sheet = {name or sh: _sheet_numbers(roots[sh]) for name, _, sh in sheets if roots[sh] is not None}
        texts, tables, grids = [], [], []
        for name, hidden, sh in sheets:
            root = roots[sh]
            if root is None:
                continue
            if name:
                texts.append(f"[숨김 시트] {name}" if hidden else name)   # 시트 이름표(숨긴/매우 숨긴은 표시 — 백로그 L3-4)
            rows = []
            for row in root.iter(_S + "row"):
                cells = [_cell_value(c, name or sh, ss, numbers_by_sheet, dates) for c in row.iter(_S + "c")]
                if any(str(x).strip() for x in cells):
                    rows.append(cells)
            if rows:
                tables.append(rows)
                texts.append(" ".join(str(c) for r in rows for c in r))
                grids.append(_xlsx_table_grid(root, name or sh, ss, numbers_by_sheet, dates))   # AD23 — 병합 펼침 그리드(독립)
    return texts, tables, grids


def parse_office(path):
    """stdlib zip+XML — 의존성 0, 표 구조·행 라벨 보존(구조 보존형)."""
    texts, tables, grids = (_docx_stdlib if str(path).endswith(".docx") else _xlsx_stdlib)(path)
    facts = [f for t in tables for f in _table_facts(t)]
    out_tables = []
    for t, (grid, merges) in zip(tables, grids):
        mt = _mk_table(t)                 # rows·cols·text는 기존 동작 그대로(위치 기반 t) + 상한(TABLE_GRID_MAX_ROWS) 처리됨
        if grid:
            mt["grid"] = grid[:TABLE_GRID_MAX_ROWS]      # AD23 — 병합 펼침 그리드로 덮음(위치 기반 grid보다 정확), 같은 상한
            if len(grid) > TABLE_GRID_MAX_ROWS:
                mt["truncated"] = True
        if merges:
            mt["merges"] = [m for m in merges if m["r"] < TABLE_GRID_MAX_ROWS]   # 잘린 뒤에 없는 행을 가리키지 않게
        out_tables.append(mt)
    return {"text": "\n".join(texts), "tables": out_tables,
            "facts": facts, "chunks": None,
            "trace": {"engine": "office-stdlib", "tables_found": len(tables)}}


ENGINES = {"office": parse_office}
FORMATS = {"office": ('.docx', '.xlsx', '.xlsm')}   # .xlsm = 같은 OOXML(매크로만 추가)
REQUIRES = {"modules": [], "tools": []}
PROFILED = set()
UNVERIFIED = set()
