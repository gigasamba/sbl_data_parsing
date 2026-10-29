"""pymupdf4llm (AGPL-3.0) — PDF → 마크다운

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine pymupdf4llm <문서> <out.json>
"""

from pipeline.extract.engines._common.contract import _md_tables, _with_tables


def parse_pymupdf4llm(path):
    """pymupdf4llm(AGPL·Artifex 상용): PyMuPDF 기반 PDF → 마크다운(표 탐지 포함)."""
    import pymupdf4llm
    md = pymupdf4llm.to_markdown(path)
    return _with_tables(md, _md_tables(md), "pymupdf4llm")


ENGINES = {"pymupdf4llm": parse_pymupdf4llm}
FORMATS = {"pymupdf4llm": ('.pdf',)}
REQUIRES = {"modules": ['pymupdf4llm'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
