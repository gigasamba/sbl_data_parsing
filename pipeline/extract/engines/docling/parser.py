"""Docling (MIT) — 레이아웃 모델 + TableFormer · docling_vlm = 내부망 VLM API로 쪽→마크다운

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine docling <문서> <out.json>
"""

import os

from pipeline.extract.engines._common.contract import _md_tables, _with_tables


_DOCLING = []

_OCR = {}

_VLM = []


def parse_docling(path):
    """Docling(MIT): 레이아웃 모델 + TableFormer로 표 행·열 복원. 텍스트 PDF는 OCR 끔(스캔본은 별도 OCR)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    if not _DOCLING:
        opt = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
        _DOCLING.append(DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opt)}))
    doc = _DOCLING[0].convert(path).document
    tables = []
    for t in getattr(doc, "tables", []):
        try:
            df = t.export_to_dataframe()
            tables.append([list(map(str, df.columns))] + [list(map(str, r)) for r in df.values.tolist()])
        except Exception:
            pass
    return _with_tables(doc.export_to_markdown(), tables, "docling")


def parse_docling_ocr(path):
    """Docling 전 쪽 OCR(스캔 PDF·이미지) — 레이아웃·표 구조 포함, OCR = EasyOCR 한국어+영어."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    if "docling" not in _OCR:
        from docling.document_converter import ImageFormatOption
        from docling.datamodel.pipeline_options import EasyOcrOptions
        opt = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
        # OCR 엔진·언어를 명시: 기본 "auto"는 설치된 패키지에 따라 RapidOCR(중국어)·EasyOCR(유럽어)로 바뀌어 한글이 깨짐(실측)
        opt.ocr_options = EasyOcrOptions(lang=["ko", "en"], force_full_page_ocr=True)
        _OCR["docling"] = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opt),
                                                            InputFormat.IMAGE: ImageFormatOption(pipeline_options=opt)})
    doc = _OCR["docling"].convert(str(path)).document
    tables = []
    for t in getattr(doc, "tables", []):
        try:
            df = t.export_to_dataframe()
            tables.append([list(map(str, df.columns))] + [list(map(str, r)) for r in df.values.tolist()])
        except Exception:
            pass
    return _with_tables(doc.export_to_markdown(), tables, "docling[ocr]")


def parse_docling_vlm(path):
    """Docling VLM 파이프라인 + 내부망 VLM(OpenAI 호환). VLM_BASE_URL·VLM_MODEL·VLM_API_KEY(선택). 외부 주소 금지."""
    from common.ai.guard import require_internal   # 원래 위치에서 직접(eval/llm.py 모듈 바꿔치기 shim은 스레드 import 경합으로 가끔 ImportError — light-hard 시험 10-08)
    require_internal(os.environ.get("VLM_BASE_URL"), "VLM")   # 내부망만(DONT 13)
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.datamodel.pipeline_options_vlm_model import ApiVlmOptions, ResponseFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.vlm_pipeline import VlmPipeline
    if not _VLM:
        key = os.environ.get("VLM_API_KEY")
        opt = VlmPipelineOptions(enable_remote_services=True)
        opt.vlm_options = ApiVlmOptions(
            url=os.environ["VLM_BASE_URL"].rstrip("/") + "/chat/completions",
            params={"model": os.environ["VLM_MODEL"], "temperature": 0},
            headers={"Authorization": "Bearer " + key} if key else {},
            prompt="Convert this page to markdown. Keep tables as markdown tables and numbers exactly as shown.",
            timeout=int(os.environ.get("VLM_TIMEOUT") or 180), scale=2.0,
            response_format=ResponseFormat.MARKDOWN)
        from docling.document_converter import ImageFormatOption
        _VLM.append(DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=opt),
                                                      InputFormat.IMAGE: ImageFormatOption(pipeline_cls=VlmPipeline, pipeline_options=opt)}))
    md = _VLM[0].convert(str(path)).document.export_to_markdown()
    return _with_tables(md, _md_tables(md), "docling[vlm-api]")


ENGINES = {"docling": parse_docling, "docling_ocr": parse_docling_ocr, "docling_vlm": parse_docling_vlm}
FORMATS = {"docling": ('.pdf',), "docling_ocr": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'), "docling_vlm": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')}
REQUIRES = {"modules": ['docling'], "tools": []}
REQUIRES_ENV = {"docling_vlm": ['VLM_BASE_URL', 'VLM_MODEL']}
PROFILED = set()
UNVERIFIED = {"docling_vlm"}   # 모의 서버로 요청 형식만 확인
