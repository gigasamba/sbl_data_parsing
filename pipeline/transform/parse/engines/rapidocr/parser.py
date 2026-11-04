"""RapidOCR (Apache-2.0, ONNX)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine rapidocr_ko <문서> <out.json> (rapidocr 1.x 엔진 rapidocr은 10-30 지움 — pl-31)

2026-10-22 — 쪽별 OCR 병렬(RAPIDOCR_PAGE_WORKERS, 기본 1=기존 순차): onnx 추론은 GIL을 놓아주므로 스레드로 실속.
쪽 렌더(_pages)는 메인 스레드가 한 쪽씩 계속 공급(한꺼번에 메모리에 안 올림)하고, 워커 스레드마다 RapidOCR 인스턴스를
따로 만든다(인스턴스 공유는 스레드 안전하지 않음 — mobile 모델 몇 MB라 스레드당 1개 부담 없음).
PAGE_WORKERS>1이면 onnx intra 스레드(ko_params)와 곱해질 수 있으니 OCR_THREADS로 함께 조절한다.
"""

import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from pipeline.transform.parse.engines._common.contract import _pages, _ocr_out, _quad


_TL = threading.local()          # 스레드별 RapidOCR 인스턴스 캐시(모듈 전역보다 안전 — 풀 재활용 시 캐시 유지)
_PAGE_EXE = {}                   # 워커 수별 스레드 풀(문서 사이에 재활용 — 문서마다 새 풀이면 매번 모델을 다시 읽음)
MAX_SIDE = 4000   # 긴 변 상한(px) — det 모델(limit_type=min)은 min(h,w)>=736이면 축소를 안 해 초대형 스캔이 전체 해상도로 들어가
                  # 느려지고 메모리를 많이 씀(백로그 L3-4 huge_scan.png 6000×8500). 긴 변만 줄여도 글자 높이가 충분히 남음.


def _resized(im):
    """긴 변이 MAX_SIDE 넘으면 비율 유지 축소(box는 원본 px 좌표로 되돌림) → (array, 되돌림 배율). 보통 크기 이미지는 그대로(배율 1)."""
    import numpy as np
    w, h = im.size
    if max(w, h) <= MAX_SIDE:
        return np.asarray(im), 1.0
    ratio = MAX_SIDE / max(w, h)
    return np.asarray(im.resize((max(1, round(w * ratio)), max(1, round(h * ratio))))), 1 / ratio


def _page_workers():
    """RAPIDOCR_PAGE_WORKERS — 문서 안 쪽별 OCR 병렬 수(기본 1=기존 순차). 숫자가 아니면 1로 침(엔진이 죽지 않게)."""
    from pipeline import config as pc
    return max(1, int(pc.cfg().extract.rapidocr_page_workers))


def _ko_engine():
    """rapidocr 3.x 한국어 — 워커 스레드마다 인스턴스 따로."""
    e = getattr(_TL, "rapid_ko", None)
    if e is None:
        from rapidocr import RapidOCR
        e = _TL.rapid_ko = RapidOCR(params=ko_params())
    return e


def _run_pages(ocr_page, path):
    """쪽 순서 그대로 [(쪽 번호, 쪽 OCR 결과), ...] — RAPIDOCR_PAGE_WORKERS>1이면 풀로 쪽별 병렬.
    제출 창을 2×워커로 제한(렌더된 쪽 이미지와 미회수 future가 메모리에 쌓이지 않게 — 300쪽 스캔이어도
    동시에 워커 수×2쪽만 떠 있음). TimeoutError(run_all의 SIGALRM)이 결과 대기 중 터지면 대기 제출은 취소하고
    그대로 올린다(진행 중이던 쪽 1~2개는 마저 끝나고 끝 — 기존 순차도 중단 시 같은 모양)."""
    nw = _page_workers()
    n = 0
    if nw <= 1:
        out = []
        for im in _pages(path):
            out.append((n + 1, ocr_page(im)))
            n += 1
        return out
    ex = _PAGE_EXE.get(nw) or _PAGE_EXE.setdefault(nw, ThreadPoolExecutor(max_workers=nw, thread_name_prefix="rapidocr-page"))
    inflight = deque()
    out = []
    try:
        for im in _pages(path):
            inflight.append((n, ex.submit(ocr_page, im)))
            n += 1
            while len(inflight) >= nw * 2:
                out.append((inflight[0][0] + 1, inflight.popleft()[1].result()))
        while inflight:
            out.append((inflight[0][0] + 1, inflight.popleft()[1].result()))
        return out
    finally:
        for _, f in inflight:        # 예외로 일찍 나갈 때 — 아직 못 시작한 제출 취소(돌던 쪽은 마저 끝나고 끝)
            f.cancel()


def ocr_threads():
    """onnxruntime 스레드 수(OC1, 사용자 10-15). rapidocr 기본(intra_op=-1)은 OMP_NUM_THREADS를 무시하고 호스트 코어 수만큼
    스레드를 띄워, 컨테이너 CPU 한도(cpus: 3) 안에서 병렬 프로세스마다 코어 전부를 쓰려다 서로 밀림(서버 쪽당 4.5초+).
    순서: OCR_THREADS(명시) → OMP_NUM_THREADS(run_all이 cgroup 한도 ÷ 프로세스 수로 이미 맞춤) → resources.plan()["threads"].
    OCR_THREADS=0이면 옛 동작(-1, onnxruntime 자동)."""
    import os
    from pipeline import config as pc
    t = pc.cfg().extract.ocr.threads      # 숫자가 아니면(예 "auto") 설정이 None으로 — 아래 순서로
    if t is not None:
        return t if t > 0 else -1
    v = os.environ.get("OMP_NUM_THREADS")  # env 남김 — 라이브러리(onnxruntime·OpenMP 스레드 수 — run_all이 맞춤)
    if v and v.isdigit() and int(v) > 0:
        return int(v)
    from common.core import resources
    return resources.plan()["threads"]


def ko_params():
    """rapidocr 3.x 한국어 모델 설정 + OC1 스레드 상한 — rapidocr_ko 엔진과 filter_and_rotate.py 방향 보정이 같이 씀."""
    from rapidocr import LangRec, ModelType, OCRVersion
    params = {"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE}
    n = ocr_threads()
    if n > 0:   # 프로세스마다 n개(합계 = CPU 한도) · inter_op 1 — 쪽 하나를 여러 연산자가 동시에 돌리지 않게
        params.update({"EngineConfig.onnxruntime.intra_op_num_threads": n, "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    return params


def parse_rapidocr_ko(path):
    """RapidOCR 3.x + PP-OCRv5 한국어 인식 모델(mobile). 기본 rapidocr(1.x)는 중국어·영어 모델이라 한글이 한자처럼 깨짐(실측)."""
    def _pg(im):
        arr, back = _resized(im)
        r = _ko_engine()(arr)
        return [{"text": t, "bbox": _quad((b * back).tolist())} for b, t in zip(r.boxes, r.txts)] if r.boxes is not None else []
    boxes = []
    for pno, items in _run_pages(_pg, path):
        boxes += [{"page": pno, "text": it["text"], "bbox": it["bbox"]} for it in items]
    return _ocr_out(boxes, "rapidocr[ko]")


ENGINES = {"rapidocr_ko": parse_rapidocr_ko}
FORMATS = {"rapidocr_ko": ('.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')}
REQUIRES = {"modules": ['rapidocr', 'pypdfium2'], "tools": []}   # rapidocr_ko = rapidocr 3.x
PROFILED = set()
UNVERIFIED = set()
