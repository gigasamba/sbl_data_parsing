"""전역 VLM in-flight 게이트 — 2026-10-22 사용자 지정(모든 VLM 호출의 동시 합 = VLM_GLOBAL_CONCURRENCY, 기본 12).

쪽 VLM(vlm_page — PDF 쪽·pptx 슬라이드 전사), 그림 VLM(vlm_fig·figoverlay), 엔진 qwen_vlm(_chat)이
**같은 서버 예산**을 공유한다 — 문서 병렬(PARSE_DOC_PARALLEL)로 문서 2개가 동시에 figures 풀에 몰려도,
또는 vlm_page 도중 다른 문서의 그림 VLM이 겹쳐도, 실제 서버에 날아가는 요청 수 합이 상한을 못 넘게 한다.
게이트는 호출 단위(1건 = 1 slot) — 풀의 워커 수(FIGURES_VLM_PARALLEL·VLM_PAGE_CONCURRENCY 등)는 그대로
각자의 상한으로 남고, 이 게이트가 그 위의 전역 합 상한이 된다.
"""

import threading
from contextlib import contextmanager

from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

_LOCK = threading.Lock()
_SEM: dict = {}


def _sem():
    v = (
        pc.cfg().transform.vlm.global_concurrency
    )  # S7c — 설정 객체(옛 int(get(X) or "12")) — 잠금 밖에서 읽음(객체를 다시 만들 때 다른 VLM 쓰레드가 기다리지 않게)
    n = max(1, int(v if v is not None else 12))
    with _LOCK:
        if n not in _SEM:
            _SEM[n] = threading.BoundedSemaphore(n)
        return _SEM[n]


@contextmanager
def slot():
    """VLM 호출 1건 자리 — 획득 실패 없이 차례를 기다린다(합이 상한을 넘는 문서·쓰레드는 여기서 대기)."""
    s = _sem()
    s.acquire()
    try:
        yield
    finally:
        s.release()
