"""내부망 VLM API — 쪽 이미지를 VLM에 보내 마크다운(표 포함)으로 받는다.
  qwen_vlm = 범용 VLM(서버의 Qwen VLM). (OCR 전용 소형 VLM 엔진 ocr_vlm은 10-30 지움 — pl-31)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine qwen_vlm <문서> <out.json>
쪽은 병렬로 호출(VLM_CONCURRENCY, 기본 4) · 쪽당 제한 VLM_TIMEOUT(기본 180초) · 시간 초과·연결 오류는 1번 재시도(VLM_RETRY).
설정(common.models.vlm — op-09, 옛 env 다리): VLM_BASE_URL(OpenAI 호환, 예 http://10.0.0.5:8000/v1) · VLM_MODEL · VLM_API_KEY(있을 때만)
**외부 API 주소 금지 — 내부망 엔드포인트만.**
"""
import base64
import io
import json
import urllib.request

from common.config.settings import cfg as _cfg, reveal as _reveal

from pipeline.extract.engines._common.contract import _pages, _with_tables, _md_tables

PROMPT = ("이 문서 쪽을 마크다운으로 옮겨라. 표는 마크다운 표(| a | b |)로, 숫자·단위·기호는 원문 그대로. "
          "설명·요약·추측을 덧붙이지 말고 보이는 내용만. 그림 속 글자도 옮긴다.")

# ponytail(TB6 천장): VLM이 돌려주는 건 마크다운 글자뿐 — rowspan·colspan 메타가 없어 covered 칸이 진짜
# 빈칸인지 병합인지 구분 불가(GS2처럼 VLM에 '병합 칸은 덮인 칸 전부에 같은 값'을 프롬프트로 직접 지시하는 건
# 정답셋 생성 경로일 때만 — 이 파싱 엔진 프롬프트는 안 건드림, 채점 대상 산출 바뀌는 변경은 범위 밖).


def _chat(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    v = _cfg().models.vlm
    body = {"model": v.model, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}}]}]}
    from common.ai.guard import require_internal, urlopen as _g_urlopen   # 원래 위치에서 직접(eval/llm.py 모듈 바꿔치기 shim은 스레드 import 경합으로 가끔 ImportError — light-hard 시험 10-08)
    require_internal(v.base_url, "VLM")            # 문서 쪽 이미지가 나가므로 내부망만(DONT 13)
    req = urllib.request.Request(v.base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if _reveal(v.api_key):
        req.add_header("Authorization", "Bearer " + _reveal(v.api_key))
    # 리다이렉트도 같은 내부망 가드로 재확인(L7) — raw urllib.request.urlopen은 리다이렉트 대상을 다시 검사하지 않음
    from pipeline.transform.figures.vgate import slot as _vgate_slot   # 전역 VLM in-flight 게이트(합 VLM_GLOBAL_CONCURRENCY — 2026-10-22)
    with _vgate_slot(), _g_urlopen(req, int(v.timeout), "VLM") as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _pages_md(path):
    """쪽 이미지를 병렬로 VLM에 보내 쪽 순서대로 마크다운(코드펜스 제거). 다중 쪽 PDF가 쪽 수 × 응답 시간만큼 늘어지지 않게."""
    from concurrent.futures import ThreadPoolExecutor
    retry = int(_cfg().models.vlm.retry)

    def one(im):
        for i in range(retry + 1):
            try:
                return _chat(im).strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
            except (TimeoutError, OSError):          # urllib 시간 초과·연결 오류 — HTTP 4xx/5xx 응답(HTTPError)도 OSError 계열
                if i == retry:
                    raise
    from itertools import islice
    n = max(1, int(_cfg().models.vlm.concurrency))
    pages, out = _pages(path), []
    with ThreadPoolExecutor(max_workers=n) as ex:           # n쪽씩 묶어서 — 메모리에는 동시 요청 수만큼의 쪽 이미지만
        while True:
            batch = list(islice(pages, n))
            if not batch:
                return out
            out += list(ex.map(one, batch))


def parse_qwen_vlm(path):
    """쪽마다 VLM 호출(쪽 이미지 DPI는 contract.OCR_DPI, 병렬). 마크다운 코드펜스는 벗긴다."""
    pages = _pages_md(path)
    md = "\n\n".join(pages)
    out = _with_tables(md, _md_tables(md), "qwen_vlm")
    out["trace"].update({"model": _cfg().models.vlm.model, "pages": len(pages)})
    return out


ENGINES = {"qwen_vlm": parse_qwen_vlm}
FORMATS = {"qwen_vlm": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')}
REQUIRES = {"modules": ['pypdfium2'], "tools": []}
REQUIRES_ENV = {"qwen_vlm": ['VLM_BASE_URL', 'VLM_MODEL']}
PROFILED = set()
UNVERIFIED = set(ENGINES)   # 모의 서버로 요청 형식만 확인 — 실제 Qwen VLM 응답은 서버에서 첫 실행 때 확인
