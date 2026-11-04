"""pipeline.shared.vlmcall 게이트(옛 figures/vgate.py — 층 p1 파일) — 합 상한 common.models.vlm.max_concurrency(11-04 VLM 통일)."""

import threading

from common.config.settings import COMMON
from pipeline.shared.vlmcall import _SEM, slot


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검 — 상한만큼만 동시 진입, 해제하면 다음이 진입` 몸통
    import sys
    import time
    from concurrent.futures import ThreadPoolExecutor

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    active = [0]
    peak = [0]
    lk = threading.Lock()

    def one(i):
        with slot():
            with lk:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lk:
                active[0] -= 1
        return i

    with COMMON.env(VLM_MAX_CONCURRENCY="3"):  # S7c — 설정 객체만 바꿔 끼움(os.environ 안 건드림)
        _SEM.clear()
        with ThreadPoolExecutor(max_workers=10) as ex:
            got = list(ex.map(one, range(30)))
        assert got == list(range(30)), got
        assert peak[0] == 3, peak[0]  # 10워커·30작업이어도 동시 진입은 상한 3
    with COMMON.env(VLM_MAX_CONCURRENCY="1"):
        _SEM.clear()
        peak[0] = 0
        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(one, range(5)))
        assert peak[0] == 1, peak[0]
    print("vgate self-check OK — 합 상한만 동시 진입")
