"""공통 출력 계약 헬퍼 — 모든 스택이 공유(엔진 간 가드 비대칭 방지).

출력 계약(모든 엔진 공통):
  {"text": str, "tables": [{"rows": int, "cols": int, "text": str, "grid": [[str]]}],
   "facts": [{"value": str, "context": [str]}],   # 표 행 라벨 → 값 (구조 보존형 엔진만)
   "fields": {...},                               # facts → 업무 필드 정규화(fields.py)
   "boxes": [{"page", "text", "bbox"}],            # OCR 엔진만 — bbox는 pt, 왼쪽 위 원점
   "trace": {...}, "chunks": null}
  text의 쪽 사이에는 \\f(폼피드)를 넣는다 — 청크·그래프 근거의 쪽 번호(common_tools.evaluation.stages.locate). 현재 pdfplumber·pymupdf·pypdf·OCR 엔진.
  tables[].grid(행×열, 선택 칸 — _mk_table이 만듦, 없으면 기존 동작) = 표 셀을 이미 아는 구조 보존 엔진의 2D 칸
  (AD23·SI20③ table_std가 쓰던 것) — C3: data_parsing.parse_qa의 P3(표 행 재현율)도 있으면 본문 줄과 함께 이걸로
  판정(엔진마다 새로 "cells" 채울 필요 없음 — 이미 모든 _mk_table 기반 엔진이 채움)."""

import re
import sys
from html.parser import HTMLParser as _PyHTMLParser

from pipeline import config as _pc   # op-09 — 설정 객체(옛 env 다리)


_NUMVAL = re.compile(r"^[±~<>≥≤+\-]?\s*\d[\d,]*(?:\.\d+)?")

# 수치 중심 셀: 숫자 1개 이상 + 한글 없음 (단위·기호·영문 약어 허용)
_NUMERIC_CELL = re.compile(r"^[^가-힣]*\d[^가-힣]*$")

OCR_DPI = int(_pc.cfg().extract.ocr.dpi)                  # 쪽 이미지 해상도 — A4 200 DPI ≈ 11.6 MB/쪽(RGB)
OCR_MAX_PAGES = int(_pc.cfg().extract.ocr.max_pages)      # 문서당 OCR·VLM 쪽 수 상한(0 = 제한 없음) — 수백 쪽 스캔 문서의 시간·메모리 상한


def fill_merged_on(config=None):
    """TB6 — 설정 fill_merged(PARSE_FILL_MERGED, 기본 켬). 끄면 _fill_merged를 안 불러 바이트 동일(병합 덮인 칸이
    빈칸으로 남는 옛 동작)."""
    if config is None:
        return bool(_pc.cfg().extract.fill_merged)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def _fill_merged(rows):
    """TB6 — None 칸(병합이 덮어 실제 칸 경계가 없는 자리 — pdfplumber·pymupdf의 find_tables/extract_tables()
    grid가 covered 칸은 None, 진짜 빈칸은 ""로 구분해 돌려줌)을 origin 값으로 채움: 먼저 행 안에서 왼→오
    (colspan), 그다음 칸마다 위→아래(rowspan) — pymupdf Table.to_markdown(fill_empty=True)가 쓰는 같은
    2-패스 순서(좌표 없이 rowspan·colspan 동시 처리) — covered 칸 = origin 값이라는 점에서 html 계열
    _html_expand_rows와 같은 convention. 호출부가 fill_merged_on()으로 게이트(꺼지면 호출 안 함 — 바이트 동일)."""
    if not rows:
        return rows
    width = max((len(r) for r in rows), default=0)
    grid = [list(r) + [None] * (width - len(r)) for r in rows]
    for row in grid:
        for i in range(1, len(row)):
            if row[i] is None:
                row[i] = row[i - 1]
    for c in range(width):
        for r in range(1, len(grid)):
            if grid[r][c] is None:
                grid[r][c] = grid[r - 1][c]
    return grid

def _split_num(value):
    """'92.5 ±0.3℃' → (92.5, '±0.3℃'). 숫자로 시작 안 하면 (None, None) — 하류 재파싱 제거."""
    m = _NUMVAL.match(value.strip())
    if not m:
        return None, None
    try:
        num = float(re.sub(r"[^\d.\-]", "", m.group()))
    except ValueError:
        return None, None
    return num, value.strip()[m.end():].strip() or None

def _table_facts(rows, strict=False):
    """표 행 → 수치-맥락 매핑: [라벨, 값(, ...)] 행에서 {value, context:[라벨], number?, unit?}.
    strict(저신뢰 표): 값 셀이 전부 수치 중심(한글 없음)인 행만 fact로 인정하고
    나머지는 rejected로 반환 — 제목·서술 파편의 fact 오염 차단."""
    facts, rejected = [], []
    rows = _clean_rows(rows)
    # 헤더 행(첫 행이 숫자 없는 라벨뿐 — '문항 (Question) | 응답 (Response)')은 fact가 아니다.
    # 숫자 유무 대신 "순수 수치 셀" 유무로 판정(AD24③) — '1월'·'2월'처럼 머리글에 숫자+한글이 섞이면
    # 예전 판정(숫자 하나라도 있으면 데이터 행)은 머리글을 사실로 잘못 들여왔다.
    # 다만 그것만으로는 '3개·5명·10건'처럼 모든 데이터 행이 숫자+한글 단위뿐인 표의 첫 데이터 행도 머리글로
    # 오판한다 — 그래서 둘째 행(실제 데이터)에 순수 수치 칸이 있을 때만(모양이 다를 때만) 첫 행을 머리글로 버림.
    if (len(rows) > 1 and not any(_NUMERIC_CELL.match(str(c or "")) for c in rows[0])
            and any(_NUMERIC_CELL.match(str(c or "")) for c in rows[1])):
        rows = rows[1:]
    for r in rows:
        cells = [str(c or "").strip() for c in r]
        if not (len(cells) >= 2 and cells[0] and any(cells[1:])):
            continue
        value = " ".join(c for c in cells[1:] if c)
        if strict and not all(_NUMERIC_CELL.match(c) for c in cells[1:] if c):
            rejected.append(" | ".join(cells))
            continue
        f = {"value": value, "context": [cells[0]]}
        vals = [c for c in cells[1:] if c]
        num, unit = _split_num(vals[0])          # 첫 값 셀 기준 — 옆 열이 단위로 붙지 않게
        if num is not None:
            f["number"], f["unit"] = num, unit
        if len(vals) > 1:
            f["cells"] = vals                     # 다열 행은 열별 값 보존
        facts.append(f)
    return (facts, rejected) if strict else facts

def _clean_rows(rows):
    """완전 빈 행 제거 — text 전략 표 감지가 만드는 공백 행 정규화(내용 판단은 안 함)."""
    return [r for r in rows if any(str(c or "").strip() for c in r)]

def _filled(row):
    return [c for c in row if str(c or "").strip()]


def split_tables(rows):
    """한 그리드에 표 여러 개가 합쳐진 것을 빈 행·제목 행(칸 1개만 채워진 행) 경계로 나눔(AD24② — 셀 경계를
    모르는 엔진이 시트 전체를 표 하나로 반환할 때 대표(kreuzberg 등)에서 씀) → [(caption 또는 None, rows), …].
    경계 = 완전 공백 행 2개 이상 연속, 또는 공백·제목 행 뒤가 더는 같은 표(앞뒤 모두 칸 2개↑) 모양이 아닐 때만 —
    공백 행 1개가 표 가운데 끼거나 칸 1개짜리 행이 병합 셀 데이터 행(앞뒤가 다 칸 2개↑ 데이터)이면 안 쪼개고
    앞 표에 그대로 붙인다(review 1차, 행을 버리지 않음). 제목 행 글자는 캡션으로 들고 있다가 다음 표가 시작될 때
    같이 돌려준다 — rows 안에는 안 넣어 머리글 판정(rows[0] 기준)을 안 틀어지게 한다."""
    groups, cur, cap = [], [], None
    n = len(rows)
    for i, row in enumerate(rows):
        filled = _filled(row)
        nxt_filled = _filled(rows[i + 1]) if i + 1 < n else None
        lone = len(row) > 1 and len(filled) <= 1                     # 완전 공백 또는 제목 행 모양(칸 1개)
        mid_table = bool(cur) and len(_filled(cur[-1])) >= 2 and nxt_filled is not None and len(nxt_filled) >= 2
        if lone and not mid_table:
            if cur:
                groups.append((cap, cur))
                cur, cap = [], None
            if len(filled) == 1:                                     # 제목 행 — 다음 표 캡션으로(소계처럼 뒤에 표가
                cap = str(filled[0]).strip()                          # 안 이어지면 더 뒤 캡션에 덮여 조용히 버려짐)
            continue
        cur.append(row)                                               # 데이터 행 또는 병합 셀 중간 행 — 앞 표에 붙임
    if cur:
        groups.append((cap, cur))
    return groups or ([(None, rows)] if rows else [])

TABLE_GRID_MAX_ROWS = int(_pc.cfg().extract.table_grid_max_rows)   # AD23 독립 검토 — 큰 엑셀 grid JSON 폭주 방지

def _mk_table(rows):
    """rows·cols·text는 그대로(기존 호출부 전부 바이트 동일) + grid(2D 칸 — AD23·SI20③ data_parsing.postprocess.table_std
    가 읽어 표 표준 형식 tables_std를 만든다) 추가. 병합 칸을 펼친 다른 그리드가 있는 호출부(office_stdlib)는
    이 grid를 그대로 덮어쓴다(_clean_rows로 행이 밀려도 merges 좌표와 안 엉키게 — 여기선 안 건드림).
    grid는 TABLE_GRID_MAX_ROWS(기본 2000) 넘으면 앞부분만 자르고 truncated=True(rows·cols·text는 영향 없음 —
    집계·채점은 그대로, grid만 큰 엑셀에서 JSON이 폭주하지 않게)."""
    rows = _clean_rows(rows)
    grid_rows = rows[:TABLE_GRID_MAX_ROWS]
    out = {"rows": len(rows), "cols": max((len(r) for r in rows), default=0),
           "text": " ".join(str(c or "").strip() for r in rows for c in r),
           "grid": [[str(c or "") for c in r] for r in grid_rows]}
    if len(rows) > TABLE_GRID_MAX_ROWS:
        out["truncated"] = True
    return out

def _facts_with_review(tables, weak_flags):
    """표 → facts. 저신뢰(텍스트 전략) 표는 strict로 파편 배제 + confidence=low + 셀 단위 검수 대상.
    모든 PDF 엔진이 이 함수를 공유(엔진 간 가드 비대칭 방지)."""
    facts, rejected, review_cells = [], [], []
    for tb, weak in zip(tables, weak_flags):
        if weak:
            f, rej = _table_facts(tb, strict=True)
            for x in f:
                x["confidence"], x["human_confirmed"] = "low", False   # 사람 검수 확정 시 True
            facts += f
            rejected += rej
            review_cells += [{"label": x["context"][0], "value": x["value"]} for x in f]
        else:
            facts += _table_facts(tb)
    res = {"facts": facts}
    if review_cells or rejected:
        res["review"] = {"needs_review": True,
                         "reason": "저신뢰 표 감지(텍스트 정렬 전략) — 수치 셀 사람 검수 필요",
                         "review_cells": review_cells[:30], "rejected_fragments": rejected[:10]}
    return res

def _md_tables(md):
    """마크다운 표(| a | b |) → 행 목록들. 구분선(|---|) 제외."""
    tables, cur = [], []
    for line in md.splitlines() + [""]:
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            if not re.fullmatch(r"\|[\s:\-|]+\|", s):
                cur.append([c.strip() for c in s.strip("|").split("|")])
        elif cur:
            tables.append(cur)
            cur = []
    return tables

HTML_SPAN_MAX = 1000          # 독립 검토 BLOCK — colspan·rowspan 위조값(예: 999999999) 1칸으로 메모리 폭주 방지 상한
HTML_TABLE_MAX_CELLS = 50_000    # 재검토(10-13): 200k는 표 하나 약 5초·41MB라 50k로 낮춤 — 독립 검토 BLOCK — 표 하나가 펼쳐진 뒤 가질 수 있는 최대 칸 수(행×열, TABLE_GRID_MAX_ROWS와 같은 취지)
                                  # 넘으면 열을 앞에서부터 자름(결정적) — 본문 글자·facts는 안 건드림, 이 표의 grid만


def _html_span_int(v, default=1):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return min(max(n, 1), HTML_SPAN_MAX) if n > 0 else default


def _html_expand_rows(rows_meta):
    """rows_meta = 표 하나의 행 목록, 각 행은 [(글자, colspan, rowspan), …](등장 순) → 2D 칸(rowspan·colspan
    펼침, covered 칸은 origin 값으로 채움 — office_stdlib(_docx_table_grid·_xlsx_table_grid)와 같은 방식).
    표준 브라우저 표 레이아웃 알고리즘(열 포인터 + 위에서 내려오는 rowspan 보류분을 칸마다 먼저 소비)과 같음.
    독립 검토 BLOCK — colspan·rowspan은 이미 _html_span_int가 HTML_SPAN_MAX로 눌러 들어오지만, 표 하나가 펼쳐진
    전체 칸 수(행×열)도 HTML_TABLE_MAX_CELLS로 눌러 열을 앞에서부터 자른다(결정적, rows·facts·text는 안 건드림)."""
    pending = {}   # col → {"left": 남은 행 수, "text": 값} — 위 행의 rowspan이 이 칸을 아직 덮고 있음
    out = []
    for cells in rows_meta:
        row, col, ci = {}, 0, 0
        while ci < len(cells) or col in pending:
            if col in pending:
                p = pending[col]
                row[col] = p["text"]
                p["left"] -= 1
                if p["left"] <= 0:
                    del pending[col]
                col += 1
                continue
            text, colspan, rowspan = cells[ci]
            ci += 1
            for cc in range(col, col + colspan):
                row[cc] = text
                if rowspan > 1:
                    pending[cc] = {"left": rowspan - 1, "text": text}
            col += colspan
        out.append(row)
    ncols = max((max(r) + 1 for r in out if r), default=0)
    if ncols * max(len(out), 1) > HTML_TABLE_MAX_CELLS:
        keep = max(1, HTML_TABLE_MAX_CELLS // max(len(out), 1))
        # 재검토 — 조용히 자르지 않고 남긴다(grid는 칸 목록이라 표시 칸이 없어 로그로; _mk_table의 truncated와 같은 취지)
        print(f"[html-table] 칸 수 상한({HTML_TABLE_MAX_CELLS}) 넘음 — {len(out)}행×{ncols}열 중 앞 {keep}열만 남김",
              file=sys.stderr, flush=True)
        ncols = keep
    return [[r.get(c, "") for c in range(ncols)] for r in out]


class _HTMLTableParser(_PyHTMLParser):
    """표준 html.parser 기반 표 추출(TB2) — rowspan·colspan을 펼치고(_html_expand_rows), 중첩 <table>은
    별도 표로 끝낸다(바깥 표를 안 자름 — 이전 정규식 `<table>.*?</table>`은 non-greedy라 중첩 표의 안쪽 닫힘에서
    멈춰 바깥 표 마지막 칸을 잃었다(nested_table.html '적합' 소실)). html.parser(convert_charrefs=True)가 글자
    참조(엔터티)를 자동 해석 — 기존 수동 `html.unescape`와 결과 같음."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []   # 완료된 표들, 등장 순(중첩 표는 자신을 닫은 뒤라 바깥보다 먼저 들어감)
        self._stack = []    # 각 원소: {"rows": [...], "row": None or [...], "cell": None or {"buf":[...], "colspan", "rowspan"}}

    @staticmethod
    def _close_cell(top):
        """독립 검토 CONCERN — 깨진 html(`<td>a<td>b</td>`, 닫는 태그 생략)도 HTML5 파싱 규칙대로: 새 td/th·tr·
        </table>가 열린 칸을 암시적으로 닫는다(안 그러면 'a'가 통째로 사라짐). 열린 칸이 없으면 아무 일도 안 함."""
        if top["cell"] is not None:
            if top["row"] is not None:
                c = top["cell"]
                top["row"].append(("".join(c["buf"]).strip(), c["colspan"], c["rowspan"]))
            top["cell"] = None

    @classmethod
    def _close_row(cls, top):
        """독립 검토 CONCERN — 깨진 html(`<tr>...<tr>...` 닫는 태그 생략)도 암시적으로 행을 닫는다(칸도 먼저 닫음)."""
        cls._close_cell(top)
        if top["row"] is not None:
            top["rows"].append(top["row"])
            top["row"] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append({"rows": [], "row": None, "cell": None})
            return
        if not self._stack:
            return
        top = self._stack[-1]
        if tag == "tr":
            self._close_row(top)                          # 이전 <tr>이 안 닫혔으면 먼저 끝냄(암시적 닫힘)
            top["row"] = []
        elif tag in ("td", "th"):
            self._close_cell(top)                          # 이전 <td>/<th>가 안 닫혔으면 먼저 끝냄(암시적 닫힘)
            if top["row"] is None:
                top["row"] = []                             # <tr> 없이 바로 <td>가 나온 경우(malformed) — 행 하나로 봄
            a = dict(attrs)
            top["cell"] = {"buf": [], "colspan": _html_span_int(a.get("colspan")), "rowspan": _html_span_int(a.get("rowspan"))}

    def handle_data(self, data):
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"]["buf"].append(data)

    def handle_endtag(self, tag):
        if not self._stack:
            return
        top = self._stack[-1]
        if tag in ("td", "th"):
            self._close_cell(top)
        elif tag == "tr":
            self._close_row(top)
        elif tag == "table":
            self._close_row(top)                           # </table> 전에 안 닫힌 행·칸을 먼저 끝냄(데이터 안 버림)
            finished = self._stack.pop()
            self.tables.append(_html_expand_rows(finished["rows"]))


def _html_rows(h):
    """html 전체(또는 표 포함 조각) → 표마다 2D 칸 목록([[[칸,…],…],…]) — TB2: 더는 호출부가 바깥 정규식으로
    `<table>` 조각을 미리 잘라 넘길 필요 없음(그 정규식이 중첩 표 버그의 원인이었다). 중첩 <table>은 별도 표로
    나뉘어 나온다(바깥 표는 안 잘림). html_stdlib·mhtml·msg/eml·kreuzberg 보조(unstructured)가 공유."""
    p = _HTMLTableParser()
    p.feed(h)
    p.close()
    return p.tables

def _with_tables(text, tables, engine):
    facts = [f for t in tables for f in _table_facts(t)]
    return {"text": text, "tables": [_mk_table(t) for t in tables], "facts": facts, "chunks": None,
            "trace": {"engine": engine, "tables_found": len(tables)}}


def _with_split_tables(text, groups, engine):
    """split_tables() 결과([(caption, rows), …]) → 엔진 공통 출력 계약. facts는 캡션 없는 rows만으로 뽑고
    (캡션이 rows[0]에 끼면 머리글 판정이 틀어짐), 캡션은 표 렌더 text 앞에만 붙인다."""
    facts, tables = [], []
    for cap, tb in groups:
        facts += _table_facts(tb)
        mt = _mk_table(tb)
        if cap:
            mt = {**mt, "text": cap + " " + mt["text"]}
        tables.append(mt)
    return {"text": text, "tables": tables, "facts": facts, "chunks": None,
            "trace": {"engine": engine, "tables_found": len(tables)}}

def _pages(path):
    """PDF → 쪽 이미지(PIL, OCR_DPI)를 **한 쪽씩** 내보냄(생성기 — 전체 쪽을 한꺼번에 메모리에 올리지 않음: 300쪽 스캔 = 약 3.5 GB였음),
    이미지 파일 → 1쪽. OCR_MAX_PAGES로 쪽 수 상한."""
    if str(path).lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            for i in range(len(pdf) if not OCR_MAX_PAGES else min(len(pdf), OCR_MAX_PAGES)):
                pg = pdf[i]
                yield pg.render(scale=OCR_DPI / 72).to_pil().convert("RGB")
                pg.close()
        finally:
            pdf.close()
        return
    from PIL import Image
    with Image.open(path) as im:
        yield im.convert("RGB")

def _ocr_out(boxes, engine):
    k = 72 / OCR_DPI
    for b in boxes:
        b["bbox"] = [round(v * k, 1) for v in b["bbox"]]      # px → pt
    text = "".join(("\n\f" if i and b.get("page") != boxes[i - 1].get("page") else "\n" if i else "") + b["text"]
                   for i, b in enumerate(boxes))   # 쪽이 바뀌면 \f — 근거의 쪽 번호(common_tools.evaluation.stages.locate)
    return {"text": text, "tables": _ocr_tables(boxes), "facts": [], "boxes": boxes, "chunks": None,
            "trace": {"engine": engine, "dpi": OCR_DPI, "boxes": len(boxes)}}


def _ocr_tables(boxes):
    """TB3 — OCR 박스 좌표로 최소 격자 추정: 같은 높이 박스 = 한 행, 짧은 칸(30자↓) 2개+ 행이 3줄 이상 이어지면 표(2열은 숫자 행 절반↑),
    열은 행들의 왼쪽 x 군집. 본문 text는 그대로(표만 추가). OCR_TABLE_GRID=0이면 옛 동작(tables=[]).
    ponytail: 선 없는 왼쪽 정렬 가정 — 오른쪽 정렬 숫자 열·병합 칸은 근사(병합 칸은 한 칸에만 들어감)."""
    if not _pc.cfg().extract.ocr.table_grid or not boxes:
        return []
    tables = []
    for page in dict.fromkeys(b.get("page") for b in boxes):
        bs = [b for b in boxes if b.get("page") == page and (b.get("text") or "").strip()]
        if not bs:
            continue
        h = sorted(b["bbox"][3] - b["bbox"][1] for b in bs)[len(bs) // 2] or 1
        lines = []                                    # [y 중심, 마지막 박스 아래 y, [박스…]]
        for b in sorted(bs, key=lambda b: (b["bbox"][1] + b["bbox"][3]) / 2):
            yc = (b["bbox"][1] + b["bbox"][3]) / 2
            if lines and abs(yc - lines[-1][0]) <= h / 2:
                lines[-1][2].append(b)
            else:
                lines.append([yc, b["bbox"][3], [b]])
        run = []
        for ln in lines + [None]:                     # None = 끝 표시(마지막 묶음 내보내기)
            ok = bool(ln) and len(ln[2]) >= 2 and all(len(b["text"].strip()) <= 30 for b in ln[2])
            if ok and (not run or ln[0] - run[-1][0] <= 3 * h):   # 행 사이가 너무 벌면 다른 표
                run.append(ln)
                continue
            if len(run) >= 3:
                xs = sorted(b["bbox"][0] for r in run for b in r[2])
                cols = [xs[0]] + [x for p, x in zip(xs, xs[1:]) if x - p > 1.5 * h]
                rows = []
                for r in run:
                    row = [""] * len(cols)
                    for b in sorted(r[2], key=lambda b: b["bbox"][0]):
                        c = max(i for i, x in enumerate(cols) if x <= b["bbox"][0] + h)
                        row[c] = (row[c] + " " + b["text"].strip()).strip()
                    rows.append(row)
                numeric = sum(any(ch.isdigit() for c in r for ch in c) for r in rows) * 2 >= len(rows)
                if len(cols) >= 3 or (len(cols) == 2 and numeric):   # 2열은 숫자 행이 절반 이상일 때만(2단 본문 오인 방지)
                    tables.append({**_mk_table(rows), "page": page})
            run = [ln] if ok else []
    return tables

def _quad(q):
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]

def _fields(facts, mode):
    from pipeline.extract.engines._common import fields as F
    if mode == "normalized":
        return F.normalize_facts(facts)
    out = {}                                     # baseline: 라벨→키 매핑만 같고 값은 fact.number/unit 그대로
    for f in facts:
        k = F.field_key((f.get("context") or [""])[0])
        if k and k not in out:
            out[k] = {"value": f.get("number"), "unit": f.get("unit"), "qualifiers": {}}
    return out

