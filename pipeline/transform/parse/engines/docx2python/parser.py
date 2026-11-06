"""docx2python (MIT)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine docx2python <문서> <out.json>
"""

from pipeline.transform.parse.engines._common.contract import _with_tables


def parse_docx2python(path):
    """docx2python(MIT): docx 본문·표(중첩 리스트)."""
    from docx2python import docx2python
    with docx2python(path) as r:
        body, text = r.body, r.text
    tables = []
    for tbl in body:
        rows = [[" ".join(" ".join(p) if isinstance(p, list) else str(p) for p in cell).strip() for cell in row] for row in tbl]
        rows = [r for r in rows if len(r) > 1]
        if rows:
            tables.append(rows)
    return _with_tables(text, tables, "docx2python")


ENGINES = {"docx2python": parse_docx2python}
FORMATS = {"docx2python": ('.docx',)}
REQUIRES = {"modules": ['docx2python'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
