"""firecrawl-anydoc (MIT, Rust) — OpenViking의 오피스 변환기

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine anydoc <문서> <out.json>
"""

from pipeline.transform.parse.engines._common.contract import _md_tables, _with_tables


def _pptx_slide_breaks(md, path):
    """A9 — anydoc 마크다운에는 슬라이드 경계가 없어 청크 meta.page가 비었다(합본 pptx 5/33). python-pptx(이미 의존성)로
    슬라이드마다 첫 글 줄을 읽고, 마크다운에서 앞에서부터 차례로 찾아 그 줄 앞에 쪽 나눔(\\f)을 넣는다(2번째 슬라이드부터).
    못 찾은 슬라이드는 건너뜀(경계 하나 덜 들어갈 뿐, 본문은 그대로)."""
    from pptx import Presentation
    firsts = []
    for slide in Presentation(path).slides:
        lines = [ln.strip() for sh in slide.shapes if getattr(sh, "has_text_frame", False)
                 for ln in sh.text_frame.text.splitlines() if ln.strip()]
        firsts.append(lines[0] if lines else None)
    pos = 0
    for t in firsts[1:]:
        j = md.find(t, pos) if t else -1
        if j < 0:
            continue
        ls = md.rfind("\n", 0, j) + 1
        md = md[:ls] + "\f\n" + md[ls:]
        pos = ls + 2 + len(t)
    return md


def _iter_pptx_shapes(shapes):
    """독립 검토 CONCERN — slide.shapes만 보면 그룹 도형(GroupShape) 안의 표를 놓친다. 그룹은 재귀로
    펼쳐서(그룹 속 그룹도) 안의 모든 도형을 돌려준다."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_pptx_shapes(shape.shapes)


def _pptx_tables(path):
    """TB1 — python-pptx(이미 의존성)로 pptx 표를 직접 읽어 병합(span) 칸을 origin 값으로 채운다
    (office_stdlib의 _docx_table_grid·_xlsx_table_grid와 같은 방식) — anydoc 마크다운 표(`_md_tables`)는
    변환 중 병합으로 덮인 칸을 빈칸으로 내보내고, `_table_facts`는 첫 칸이 비면 그 행을 통째로 버린다(값 소실).
    그룹 도형 속 표도 찾음(_iter_pptx_shapes). 반환: [(grid, merges), …] — 슬라이드 등장 순 → 슬라이드 안 표 등장 순
    (그룹 속 표는 그 그룹이 나온 자리에, 그룹 안에서는 도형 등장 순)."""
    from pptx import Presentation
    out = []
    for slide in Presentation(path).slides:
        for shape in _iter_pptx_shapes(slide.shapes):
            if not getattr(shape, "has_table", False):
                continue
            tbl = shape.table
            nrows, ncols = len(tbl.rows), len(tbl.columns)
            grid = [["" for _ in range(ncols)] for _ in range(nrows)]
            merges = []
            for r in range(nrows):
                for c in range(ncols):
                    cell = tbl.cell(r, c)
                    if cell.is_spanned:
                        continue   # 병합으로 덮인 칸 — origin 칸을 처리할 때 같이 채움(아래)
                    text = cell.text
                    grid[r][c] = text
                    if cell.is_merge_origin:
                        rh, rw = cell.span_height, cell.span_width
                        for rr in range(r, min(r + rh, nrows)):
                            for cc in range(c, min(c + rw, ncols)):
                                grid[rr][cc] = text
                        if rh > 1 or rw > 1:
                            merges.append({"r": r, "c": c, "rowspan": rh, "colspan": rw})
            out.append((grid, merges))
    return out


def parse_anydoc(path):
    """firecrawl-anydoc(MIT, Rust): OpenViking이 오피스·EPUB에 쓰는 변환기 → 마크다운. OCR 없음.
    TB1 — .pptx는 표만 python-pptx 직접 추출로 교체(병합 칸 채움) — **표 개수가 anydoc 마크다운 표 개수와
    같을 때만**(가장 단순하고 표를 잃지 않는 규칙 — 독립 검토 CONCERN: 안 맞으면 어느 쪽이 어느 표에 대응하는지
    확신할 수 없어 섣불리 섞느니 anydoc 결과를 그대로 둔다, 병합 칸은 그 문서에서만 못 고침). 대표 엔진 선택
    로직(.pptx → anydoc)은 그대로, 이 함수 안에서만 표 출처를 보강."""
    import anydoc
    md = anydoc.to_markdown(path)
    tables = _md_tables(md)
    merges_by_table = []
    if str(path).lower().endswith(".pptx"):
        md = _pptx_slide_breaks(md, path)
        pptx_tables = _pptx_tables(path)
        if pptx_tables and len(pptx_tables) == len(tables):   # 개수 불일치 — 대응 확신 없음, anydoc 표 그대로 둠(표 손실 없음)
            tables = [g for g, _ in pptx_tables]
            merges_by_table = [m for _, m in pptx_tables]
    out = _with_tables(md, tables, "anydoc")
    for mt, merges in zip(out["tables"], merges_by_table):
        if merges:
            mt["merges"] = merges
    return out


ENGINES = {"anydoc": parse_anydoc}
FORMATS = {"anydoc": ('.docx', '.xlsx', '.pptx', '.ppt')}   # .ppt(구형 이진) — 합성 4고객 10/10(2026-10-01)
REQUIRES = {"modules": ['anydoc'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
