"""python-pptx (MIT) — 글상자·표·차트 값

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine pptx <문서> <out.json>
"""

from pipeline.extract.engines._common.contract import _with_tables, _fill_merged, fill_merged_on


def parse_pptx(path):
    """python-pptx(MIT): 슬라이드 글상자 문단·표·차트 데이터(범주·값)를 슬라이드 순서대로. 차트는 '범주 | 값' 표로.
    TB6 — pptx 표 병합: python-pptx는 covered(spanned) 칸도 빈 글자("")를 돌려줘 진짜 빈칸과 안 구분되지만
    cell.is_spanned로 병합 정보 자체는 있다 — PARSE_FILL_MERGED(기본 켬)면 spanned 칸만 None으로 바꿔 넘겨
    _fill_merged가 origin 값으로 채운다."""
    fill_on = fill_merged_on()
    from pptx import Presentation
    texts, tables = [], []
    for s in Presentation(path).slides:
        blocks = []
        for sh in s.shapes:
            if sh.has_text_frame:
                blocks.append("\n".join(p.text for p in sh.text_frame.paragraphs if p.text))
            if getattr(sh, "has_table", False) and sh.has_table:
                rows = [[(None if fill_on and c.is_spanned else c.text) for c in r.cells] for r in sh.table.rows]
                tables.append(_fill_merged(rows) if fill_on else rows)
            if getattr(sh, "has_chart", False) and sh.has_chart:
                pl = sh.chart.plots[0]
                cats = list(pl.categories)
                for ser in pl.series:
                    tables.append([["범주", ser.name]] + [[str(c), f"{v:g}"] for c, v in zip(cats, ser.values)])
        texts.append("\n\n".join(b for b in blocks if b))
    return _with_tables("\n\n".join(texts), tables, "python-pptx")


ENGINES = {"pptx": parse_pptx}
FORMATS = {"pptx": ('.pptx',)}
REQUIRES = {"modules": ['pptx'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
