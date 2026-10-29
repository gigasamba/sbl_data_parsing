"""Unstructured (Apache-2.0)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine unstructured <문서> <out.json>
"""
from pathlib import Path

from pipeline.extract.engines._common.contract import _html_rows, _with_tables


def parse_unstructured(path, profile="default"):
    """Unstructured(Apache-2.0): default=fast(pdfminer 텍스트, 표 구조 없음) · tuned=hi_res(레이아웃 모델 + 표 구조 추론)."""
    from unstructured.partition.pdf import partition_pdf
    strategy = "hi_res" if profile == "tuned" else "fast"
    els = partition_pdf(filename=path, strategy=strategy, infer_table_structure=(strategy == "hi_res"))
    tables = [t for e in els if e.category == "Table" and getattr(e.metadata, "text_as_html", None)
              for t in _html_rows(e.metadata.text_as_html) if t]   # TB2 — _html_rows가 표 목록을 돌려줌(span 펼침·중첩 분리)
    return _with_tables("\n".join(str(e) for e in els), tables, f"unstructured[{strategy}]")


def parse_unstructured_auto(path):
    """Unstructured(Apache-2.0) 형식별 partition — docx·pptx·xlsx·html. (auto 판별은 libmagic 의존이라 쓰지 않음)"""
    import importlib
    ext = {"xls": "xlsx", "xlsm": "xlsx", "txt": "text", "htm": "html", "eml": "email"}.get(Path(path).suffix.lower().lstrip("."), Path(path).suffix.lower().lstrip("."))
    mod = importlib.import_module(f"unstructured.partition.{ext}")
    els = getattr(mod, f"partition_{ext}")(filename=str(path))
    tables = [t for e in els if e.category == "Table" and getattr(e.metadata, "text_as_html", None)
              for t in _html_rows(e.metadata.text_as_html) if t]   # TB2 — _html_rows가 표 목록을 돌려줌(span 펼침·중첩 분리)
    return _with_tables("\n".join(str(e) for e in els), tables, "unstructured[auto]")


ENGINES = {"unstructured": parse_unstructured, "unstructured_auto": parse_unstructured_auto}
def parse_unstructured_ocr(path):
    """Unstructured hi_res + Tesseract OCR(kor+eng) — 이미지·이미지 PDF, 표 구조 추론."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        from unstructured.partition.pdf import partition_pdf as part
    else:
        from unstructured.partition.image import partition_image as part
    els = part(filename=str(path), strategy="hi_res", infer_table_structure=True, languages=["kor", "eng"])
    tables = [t for e in els if e.category == "Table" and getattr(e.metadata, "text_as_html", None)
              for t in _html_rows(e.metadata.text_as_html) if t]   # TB2 — _html_rows가 표 목록을 돌려줌(span 펼침·중첩 분리)
    return _with_tables("\n".join(str(e) for e in els), tables, "unstructured[ocr]")


ENGINES["unstructured_ocr"] = parse_unstructured_ocr
FORMATS = {"unstructured": ('.pdf',), "unstructured_auto": ('.docx', '.xlsx', '.pptx', '.xls', '.txt', '.html', '.htm', '.eml', '.msg', '.xlsm'), "unstructured_ocr": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')}
REQUIRES = {"modules": ['unstructured'], "tools": []}
PROFILED = {'unstructured'}
UNVERIFIED = {"unstructured_ocr"}   # Tesseract·poppler 필요 — 개발 PC 미실측
