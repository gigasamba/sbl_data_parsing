"""스택 폴더 자동 등록 + 도구(tool) 진입점.

스택 추가 = tools/engines/<스택>/parser.py 하나 추가 (ENGINES · FORMATS · REQUIRES · PROFILED · UNVERIFIED 정의, 필요 시 REQUIRES_ENV).
사용: from pipeline.transform.parse.engines import registry; registry.run("pymupdf", "x.pdf")
(LLM 도구 API TOOL_SPECS·call_tool은 10-30 지움 — pl-31, 부르는 곳 없음.)
"""
import importlib
import importlib.util
import shutil
from functools import lru_cache
from pathlib import Path

from common.core.paths import PARSING_ROOT
from pipeline.transform.parse.engines._common.contract import _fields

HERE = PARSING_ROOT / "engines"


@lru_cache(maxsize=1)
def stacks():
    """{스택 폴더: 모듈} — parser.py가 있는 폴더만."""
    return {d.name: importlib.import_module(f"pipeline.transform.parse.engines.{d.name}.parser")
            for d in sorted(HERE.iterdir()) if (d / "parser.py").exists() and not d.name.startswith("_")}


@lru_cache(maxsize=1)
def engines():
    """{엔진 이름: (스택, 모듈)}"""
    return {e: (s, m) for s, m in stacks().items() for e in m.ENGINES}


# 핵심 평가 엔진(기본 실행 대상, 2026-09-29 사용자 확정) — 타입별 담당·실측 성능·라이선스로 추림. 나머지는 --engines all이거나 이름을 명시할 때만.
# 제외(사용자 10-07, 스택에서 뺌 — backlog DP6): paddleocr · docling_ocr(EasyOCR 내장).
# openviking_import·cognee_import 엔진 어댑터는 삭제됨(SI33, 10-07) — OpenViking은 서버의 기존 컨테이너를 직접 쓰고(구조화 요약 fallback은 OV_DOC_ROOT), Cognee는 스택에서 제외(DP6).
CORE = {"pymupdf", "kreuzberg",                                                # 텍스트 PDF(+ kreuzberg는 doc·html·eml 등 폭넓게)
        "rapidocr_ko", "qwen_vlm",                                              # 이미지·스캔(ocr_vlm은 10-30 지움 — pl-31)
        "office", "plaintext", "mhtml", "html_stdlib", "msg_extract", "markitdown", "hwpx",   # 오피스·웹·메일
        "archive",  # 압축 원본(pl-57 — 안 파일은 첨부 단계)
        "anydoc"}   # 올인원 내부 파서 단독 — OpenViking 오피스(anydoc)
# 0.2.0(pl-46, 사용자 11-01) 엔진 지움: pdfplumber·pypdf·calamine·pptx(python_pptx)·pymupdf4llm — 한 번도 안 돈 엔진. docx2python은 비교용으로 남김.
# 10-30(pl-31) 엔진 지움: docling·docling_ocr·docling_vlm·unstructured·unstructured_auto·unstructured_ocr·rapidocr(1.x)·kreuzberg_ocr·marker_llm(이름만 남아 있던 것).


def missing_deps(engine):
    """엔진의 REQUIRES(모듈 import·PATH 도구)가 지금 환경에 없는 것 — check_env.py의 스택별 점검과 같은 판정(AD48, 중복 금지로 여기 한 곳).
    한 스택 파일에 엔진이 여러 개면 보통 REQUIRES를 같이 쓰지만, 엔진마다 쓰는 패키지가 서로 다르면(옛 예: rapidocr 1.x·rapidocr_ko — 1.x는 10-30 지움, 지금 쓰는 엔진 없음)
    REQUIRES_ENGINE = {엔진: {"modules": [...], "tools": [...]}}로 엔진별로 따로 적고 여기서 그걸 먼저 본다(없으면 REQUIRES로).
    REQUIRES_ENV(모델 서빙 주소 등 설정값)는 설치 여부와 다른 문제라 missing_env()가 따로 본다."""
    _, m = engines()[engine]
    req = getattr(m, "REQUIRES_ENGINE", {}).get(engine) or getattr(m, "REQUIRES", {"modules": [], "tools": []})
    tools = req.get("tools", [])
    return [x for x in req.get("modules", []) if importlib.util.find_spec(x) is None] + [t for t in tools if not shutil.which(t)]


def installed(engine):
    """엔진 실행에 필요한 모듈·도구가 지금 환경(PC 또는 이미지)에 다 있는지(AD48)."""
    return not missing_deps(engine)


def select(spec=""):
    """--engines 값 → 대상 엔진 집합. ""=핵심(CORE 중 설치된 것만, cognee_<조합>은 제외 — 사용자 10-07) ·
    "all"=설치된 전부(AD48 — 이미지·PC에 없는 패키지의 엔진은 all에서 빠짐, 미설치 엔진은 시도 자체가 안 됨) ·
    "a,b"=그것만(엔진 이름을 직접 줄 때는 미설치여도 그대로 — 사용자가 알고 선택한 것, ImportError로 바로 알려준다)."""
    if spec == "all":
        return {e for e in engines() if installed(e)}
    if spec:
        return {e for e in spec.split(",") if e}
    return {e for e in engines() if e in CORE and installed(e)}


# pl-45(사용자 11-01·11-03) 엔진별 추가 확장자 — 엔진 parser.py의 FORMATS를 고치면 엔진 지문(run_all.engine_code_fp)이 바뀌어
# 서버의 모든 문서를 그 엔진으로 다시 파싱하므로 여기 둔다(이 파일은 엔진 지문에 안 들어감). 형식별 엔진 순서는 resources/config/pipeline_stack.json.
# 견본으로 읽히는 것을 확인한 것만(tests/server/pipeline/test_ext_formats.py). .hwp는 kreuzberg에 판독기가 있으나 만든 견본에서 글이 안 나와 뺌(실제 문서 시험 뒤에).
EXTRA_FORMATS = {
    "kreuzberg": (".docm", ".pptm", ".rtf", ".csv", ".tsv", ".odt", ".ods", ".xlsb",
                  ".dotx", ".xltx", ".potx", ".ppsx", ".dot", ".xlt", ".pot"),
    "anydoc": (".docm", ".pptm", ".rtf", ".odt", ".ods", ".odp"),
    "markitdown": (".csv", ".md"),
    "plaintext": (".tsv", ".md", ".json", ".xml", ".log"),   # .json·.xml·.log는 글 그대로(사용자 11-03 — markitdown 아님)
}


def formats(engine):
    """엔진이 읽는 확장자 = parser.py FORMATS + EXTRA_FORMATS."""
    _, m = engines()[engine]
    return tuple(m.FORMATS[engine]) + EXTRA_FORMATS.get(engine, ())


def engines_for(ext):
    """확장자(.pdf 등)를 처리하는 엔진 이름 목록."""
    return [e for e in engines() if ext.lower() in formats(e)]


def missing_env(engine):
    """엔진이 요구하는 설정 칸(옛 env 이름) 중 비어 있는 것 (parser.py의 REQUIRES_ENV = {엔진: [이름]}, "A|B"는 둘 중 하나).
    op-09 — env가 아니라 설정 객체(common 칸 — by_env)로 본다."""
    from common.config.settings import by_env

    _, m = engines()[engine]
    return [v for v in getattr(m, "REQUIRES_ENV", {}).get(engine, []) if not any(by_env(x) for x in v.split("|"))]


def run(engine, path, profile="default", fields="normalized"):
    """문서 1건 → 공통 출력 계약 dict (+ fields)."""
    stack, m = engines()[engine]
    out = m.ENGINES[engine](str(path), profile) if engine in m.PROFILED else m.ENGINES[engine](str(path))
    out["fields"] = _fields(out.get("facts") or [], fields)
    out.setdefault("trace", {})["stack"] = stack
    return out

