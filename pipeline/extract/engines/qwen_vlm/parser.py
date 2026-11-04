"""내부망 VLM 엔진 — 스캔·이미지 문서의 쪽마다 VLM에 보내 마크다운(표 포함)으로 받는다.
  qwen_vlm = 범용 VLM(서버의 Qwen VLM). (OCR 전용 소형 VLM 엔진 ocr_vlm은 10-30 지움 — pl-31)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(engines/_common/contract.py).
11-04(사용자 — VLM 처리 통일): 쪽 옮기기는 쪽 VLM 후보정과 같은 함수(pipeline.shared.vlmcall.transcribe) — 같은 지시문(page_transcribe)·
렌더(extract.ocr.dpi)·캐시·내부망 가드·예산·extra_body·재시도·제한 시간·동시 수(common.models.vlm.*). 쪽 수 상한 transform.vlm.page_max.
설정(common.models.vlm): base_url(OpenAI 호환, 예 http://10.0.0.5:8000/v1) · model · api_key(있을 때만).
**외부 API 주소 금지 — 내부망 엔드포인트만**(llm.complete의 require_internal).
"""
from common.config.settings import cfg as _cfg
from pipeline.extract.engines._common.contract import _md_tables, _with_tables
from pipeline.shared import vlmcall as V

# ponytail(TB6 천장): VLM이 돌려주는 건 마크다운 글자뿐 — rowspan·colspan 메타가 없어 covered 칸이 진짜
# 빈칸인지 병합인지 구분 불가(GS2처럼 VLM에 '병합 칸은 덮인 칸 전부에 같은 값'을 프롬프트로 직접 지시하는 건
# 정답셋 생성 경로일 때만 — 이 파싱 엔진 프롬프트는 안 건드림, 채점 대상 산출 바뀌는 변경은 범위 밖).


def _pages_md(path):
    """(쪽 순서대로 마크다운(코드펜스 제거), 문서 쪽 수). 모델 없음·호출 실패는 예외(문서×엔진 실패로 기록 — 반쪽 결과를 성공으로 남기지 않음), 빈 답은 빈 쪽."""
    cap, n = V.page_max(), V.page_count(path)
    out = []
    for i, text, prov in V.transcribe(path, range(1, (n if cap is None else min(n, cap)) + 1)):
        if prov.get("error") and prov["error"] != V.EMPTY:
            raise RuntimeError(f"쪽 {i} VLM 실패: {prov['error']}")
        out.append(text.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip())
    return out, n


def parse_qwen_vlm(path):
    """쪽마다 VLM 호출(쪽 이미지 DPI는 extract.ocr.dpi, 병렬). 마크다운 코드펜스는 벗긴다."""
    pages, total = _pages_md(path)
    md = "\n\n".join(pages)
    out = _with_tables(md, _md_tables(md), "qwen_vlm")
    out["trace"].update({"model": _cfg().models.vlm.model, "pages": len(pages)})
    if len(pages) < total:  # 쪽 상한(transform.vlm.page_max)에 걸려 앞쪽만 — 결과에 남김(성공으로 기록되므로 다시 파싱하지 않음)
        out["trace"]["pages_total"] = total
    return out


ENGINES = {"qwen_vlm": parse_qwen_vlm}
FORMATS = {"qwen_vlm": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')}
REQUIRES = {"modules": ['fitz'], "tools": []}
REQUIRES_ENV = {"qwen_vlm": ['VLM_BASE_URL', 'VLM_MODEL']}
PROFILED = set()
UNVERIFIED = set(ENGINES)   # 모의 서버로 요청 형식만 확인 — 실제 Qwen VLM 응답은 서버에서 첫 실행 때 확인
