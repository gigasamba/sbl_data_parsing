"""python-calamine (MIT, Rust)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine calamine <문서> <out.json>
"""

from pipeline.extract.engines._common.contract import _with_tables


def parse_calamine(path):
    """python-calamine(MIT, Rust): xlsx/xls/ods 셀 값."""
    from python_calamine import CalamineWorkbook
    wb = CalamineWorkbook.from_path(str(path))
    tables = [[[str(c) for c in r] for r in wb.get_sheet_by_name(n).to_python() if any(str(c).strip() for c in r)]
              for n in wb.sheet_names]
    tables = [t for t in tables if t]
    return _with_tables("\n".join(" ".join(c for r in t for c in r) for t in tables), tables, "calamine")


ENGINES = {"calamine": parse_calamine}
FORMATS = {"calamine": ('.xlsx', '.xls', '.xlsm')}
REQUIRES = {"modules": ['python_calamine'], "tools": []}
PROFILED = set()
UNVERIFIED = set()
