#!/usr/bin/env python3
"""실행 자원 — pipeline(P) 전용 결정(10-14 common.core.resources에서 옮김 — run_all.py·cli/parse_parallel.py만
쓴다). CPU·메모리 감지·plan()·메모리/CPU 문·gated_popen 등 공용 핵심은 common.core.resources에 그대로 남아 있다.

resolve_procs(v) — 명령 인자 --procs 값('auto'·숫자) → 정수(common.core.resources.plan() 기준).
thread_env(threads) — 수치 라이브러리 스레드 수 고정(OMP·MKL 등, 프로세스마다 호스트 코어 수만큼 띄우는 CPU 폭주 방지).
low_priority_kw()·renice_low(pid) — 일괄 파싱 엔진 자식을 낮은 우선순위로(parse MCP 요청이 CPU를 먼저, 사용자 10-29).
group_kw()·kill_group(p) — 자식을 프로세스 묶음으로 띄우고 시간 초과면 묶음째 끝냄(손자 parse_one이 남지 않게).
OS별 분기(POSIX·Windows)는 이 파일에만 둔다(CLAUDE.md §2)."""

import os
import subprocess

from common.core import resources as RS

LOW_NICE = 10  # POSIX nice 증가분 — 일괄 파싱 엔진 자식(parse MCP 서비스의 자식은 0)


def resolve_procs(v):
    """명령 인자 --procs 값('auto'·숫자) → 정수."""
    return RS.plan()["procs"] if str(v).strip().lower() in ("", "auto", "0") else max(1, int(v))


def thread_share(cpus, procs, workers=1):
    """동시 실행 단위 하나가 쓸 스레드 수(OC2, 사용자 10-15) — 실제 동시 수 = procs × workers로 CPU를 나눔.
    run_all은 --procs만큼 조각(shard)을 띄우고 각 조각이 동시 자식(글자 엔진 상한 text_slots)을 돌린다 → 호출자가 그 수를 workers로. 최소 1."""
    return max(1, int(cpus) // (max(1, int(procs)) * max(1, int(workers))))


def text_slots(cpus, procs):
    """조각 하나에서 동시에 돌릴 글자(CPU) 엔진 자식 수 상한(10-29) — 코어 ÷ 조각 수(최소 1). VLM 엔진(API 대기)은 이 상한 밖 —
    --workers(문서 동시 수, VLM에 맞춘 값)를 글자 엔진이 그대로 물려받지 않게."""
    return max(1, int(cpus) // max(1, int(procs)))


def low_priority_kw(low=True):
    """일괄 파싱 엔진 자식을 띄울 때 Popen 추가 인자 — Windows는 BELOW_NORMAL 우선순위 클래스, POSIX는 없음(띄운 뒤 renice_low)."""
    if low and os.name == "nt":
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {}


def renice_low(pid, low=True):
    """POSIX — 띄운 자식의 nice를 LOW_NICE만큼 올림(preexec_fn은 스레드와 같이 쓰면 위험해 띄운 뒤에). Windows·실패는 아무것도 안 함."""
    if low and os.name != "nt":
        try:
            os.setpriority(os.PRIO_PROCESS, pid, os.getpriority(os.PRIO_PROCESS, pid) + LOW_NICE)
        except OSError:
            pass  # 이미 끝난 자식 등 — 우선순위는 최선(실패해도 파싱은 계속)


def group_kw():
    """자식을 새 프로세스 묶음(세션)으로 — kill_group이 손자까지 끝낼 수 있게."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_group(p):
    """group_kw로 띄운 자식과 그 아래 프로세스 전부를 끝내고 기다림(시간 초과 처리)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        import signal

        # SIGTERM 뒤 10초 기다린 다음 묶음째 SIGKILL — 맨 위 자식이 먼저 끝나도 SIGTERM을 무시한 손자가 파이프를 붙잡지 않도록 항상 보냄
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    p.communicate()


def thread_env(threads):
    """수치 라이브러리 스레드 수 고정 — 정하지 않으면 각 프로세스가 호스트 코어 수만큼 스레드를 띄움(프로세스 × 코어 = CPU 폭주)."""
    t = str(threads)
    return {k: t for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "TORCH_NUM_THREADS")}
