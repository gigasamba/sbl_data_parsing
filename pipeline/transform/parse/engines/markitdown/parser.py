"""MarkItDown (MIT, Microsoft)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine markitdown <문서> <out.json>
"""

from pipeline.transform.parse.engines._common.contract import _md_tables, _with_tables


def parse_markitdown(path):
    """MarkItDown(MIT, Microsoft): 여러 형식 → 마크다운(PDF는 pdfminer 텍스트, 오피스는 mammoth·openpyxl·python-pptx). LLM 옵션 끔.
    ponytail(TB6 천장): 마크다운 표 글자만 받아 rowspan·colspan 메타가 없다 — covered 칸이 진짜 빈칸인지
    병합인지 구분 불가라 추측하지 않고 그대로 둔다."""
    from markitdown import MarkItDown
    md = MarkItDown(enable_plugins=False).convert(path).text_content
    return _with_tables(md, _md_tables(md), "markitdown")


ENGINES = {"markitdown": parse_markitdown}
FORMATS = {"markitdown": ('.pdf', '.docx', '.xlsx', '.pptx', '.xls', '.txt', '.mht', '.mhtml', '.html', '.htm', '.eml', '.xlsm')}   # .eml은 인코딩된 머리글(=?utf-8?b?)을 풀지 않음(실측)   # .xls는 xlrd 필요 · .mht는 MIME 원문 그대로(표 없음, 실측)
REQUIRES = {"modules": ['markitdown'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
