#!/usr/bin/env python3
"""실행 자원 — pipeline(P) 전용 결정(10-14 common.core.resources에서 옮김 — run_all.py·cli/parse_parallel.py만
쓴다). CPU·메모리 감지·plan()·메모리/CPU 문·gated_popen 등 공용 핵심은 common.core.resources에 그대로 남아 있다.

resolve_procs(v) — 명령 인자 --procs 값('auto'·숫자) → 정수(common.core.resources.plan() 기준).
thread_env(threads) — 수치 라이브러리 스레드 수 고정(OMP·MKL 등, 프로세스마다 호스트 코어 수만큼 띄우는 CPU 폭주 방지)."""

from common.core import resources as RS


def resolve_procs(v):
    """명령 인자 --procs 값('auto'·숫자) → 정수."""
    return RS.plan()["procs"] if str(v).strip().lower() in ("", "auto", "0") else max(1, int(v))


def thread_share(cpus, procs, workers=1):
    """동시 실행 단위 하나가 쓸 스레드 수(OC2, 사용자 10-15) — 실제 동시 수 = procs × workers로 CPU를 나눔.
    run_all은 --procs만큼 조각(shard)을 띄우고 각 조각이 --workers건을 동시에 돈다(phase 3 VLM은 둘 다 넘김 —
    cli/pipeline.py) → procs·workers 어느 한쪽만으로 나누면 과다 할당(fb 검토 10-15). phase 1·2(workers 1)는 전과 같음. 최소 1."""
    return max(1, int(cpus) // (max(1, int(procs)) * max(1, int(workers))))


def thread_env(threads):
    """수치 라이브러리 스레드 수 고정 — 정하지 않으면 각 프로세스가 호스트 코어 수만큼 스레드를 띄움(프로세스 × 코어 = CPU 폭주)."""
    t = str(threads)
    return {k: t for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "TORCH_NUM_THREADS")}
