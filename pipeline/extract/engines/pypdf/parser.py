"""pypdf (BSD)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine pypdf <문서> <out.json>
"""


def parse_pypdf(path, profile="default"):
    from pypdf import PdfReader
    mode = "layout" if profile == "tuned" else "plain"
    text = "\n\f".join((p.extract_text(extraction_mode=mode) or "") for p in PdfReader(path).pages)   # 쪽 사이 \f(근거 쪽 번호)
    return {"text": text, "tables": [], "chunks": None,
            "trace": {"engine": f"pypdf[{profile}]"}}


ENGINES = {"pypdf": parse_pypdf}
FORMATS = {"pypdf": ('.pdf',)}
REQUIRES = {"modules": ['pypdf'], "tools": []}
PROFILED = {'pypdf'}
UNVERIFIED = set()
