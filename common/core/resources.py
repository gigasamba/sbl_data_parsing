#!/usr/bin/env python3
"""실행 자원 파악 → 병렬 수 자동 결정 — 개발 서버·수집 서버·Docker 컨테이너 어디서든 같은 규칙.

CPU = min(호스트 코어, CPU 친화도(sched_getaffinity), cgroup 한도(cpu.max · cfs_quota)) — 컨테이너에 --cpus를 주면 그 값.
      os.cpu_count()는 컨테이너 한도를 무시하고 호스트 코어를 돌려줘 스레드를 과하게 띄움(CPU 초과 사용) → 쓰지 않음.
메모리 = min(물리 메모리, cgroup 한도(memory.max · limit_in_bytes)) — 컨테이너에 --memory를 주면 그 값.

결정(환경변수가 있으면 그 값 우선 — Docker 이미지 밖에서 조정):
  PIPE_PROCS     CPU 엔진 프로세스 수  자동 = min(CPU − PIPE_RESERVE_CPUS, (메모리 − PIPE_RESERVE_GB) ÷ PIPE_PROC_GB), 최소 1
  PIPE_THREADS   프로세스당 스레드(OMP·MKL·onnxruntime) 자동 = CPU ÷ 프로세스 수, 최소 1
  PIPE_WORKERS   VLM API 동시 문서 수(CPU를 거의 안 씀 — GPU 서버 한도 기준) 기본 4
  PIPE_RESERVE_CPUS 1 · PIPE_RESERVE_GB 4(PostgreSQL·OS·다른 컨테이너 몫) · PIPE_PROC_GB 3(OCR 모델 + 쪽 이미지 여유) · PIPE_MAX_PROCS 8

메모리 문(새 하위 프로세스를 띄우기 전 — plan()의 처음 개수 결정과는 별개, 띄우는 시점만 늦춤):
  MEM_START_PCT  wait_mem() 기본 상한(90 — 사용자 10-07, 전에는 78) — 실험 도구가 씀, 여유를 넉넉히 두고 느리게
  MEM_MAX_PCT    gated_popen() 상한(90 — 사용자 10-07, 전에는 85) — 생산 파싱(run_all·pipeline)이 씀, 가능한 병렬로 돌리다 이 선만 넘지 않게
  MEM_SETTLE_SEC gated_popen() 뒤 settle(기본 2초) — 사용률이 MEM_MAX_PCT−MEM_SETTLE_MARGIN(기본 5, 상한 90 − 5 = 85% 이상)보다 가까울 때만 쉼
                 (여유 있으면 매번 안 쉼 — 문서×엔진 수천 건 실행에서 매번 쉬면 전체가 크게 느려짐, 성능 회귀 10-04.
                  10-07: 평소 사용률 77%대 PC에서 margin 10(문턱 80%)이 자주 걸려 문서×엔진 평균 2초가 추가되던 걸 margin 5(문턱 85%)로 좁힘 — RB3①)

CPU 문(gated_popen이 메모리 문 다음에 같이 거침 — 측정 못 하면(Windows 등) 바로 통과):
  CPU_MAX_LOAD   wait_cpu() 상한(기본 0.9 = 90%, 사용자 10-07) — cpu_load()가 이 값 이상이면 새 프로세스를 늦춤(실행 중인 건 안 건드림)
  cpu_load()     cgroup CPU 한도가 있으면(v2 cpu.max · v1 cfs_quota) 그 컨테이너 자신의 사용량(cgroup usage 증가 ÷ (한도 코어 × 시간)),
                 없으면 1분 부하 평균 ÷ 호스트 코어(0.2.0 — pl-46: 컨테이너 안 loadavg는 호스트 전체라 한도 코어로 나누면 늘 막혔음)

모델 서버 동시 요청 상한(실험 도구 stack_matrix의 병렬 수 plan_experiment·LLM_MAX_CONCURRENCY는 10-30 지움 — pl-21):
  VLM_MAX_CONCURRENCY  VLM 서버 동시 요청 상한(기본 8) — cli/pipeline.py가 --workers(문서) 기준으로 쪽 동시 수를 줄여 지킴
사용: python common/resources.py           → 감지값·결정 표
      python common/resources.py --env     → export 줄(셸에서 eval)
"""

import math
import os
import sys
import threading
from pathlib import Path

from common.core import exitclean  # pl-27 — 띄운 자식은 종료 때 회수
from common.core.console import utf8_stdout

CG = Path("/sys/fs/cgroup")


def _read(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None


def cpus(cg=CG):
    """사용 가능한 CPU 수(정수, cgroup·친화도 반영)."""
    n = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        n = min(n, len(os.sched_getaffinity(0)))
    q = _read(cg / "cpu.max")  # cgroup v2: "<quota> <period>" 또는 "max <period>"
    if q and not q.startswith("max"):
        quota, period = q.split()[:2]
        n = min(n, max(1, math.ceil(int(quota) / int(period))))
    quota, period = _read(cg / "cpu" / "cpu.cfs_quota_us"), _read(cg / "cpu" / "cpu.cfs_period_us")  # cgroup v1
    if quota and period and int(quota) > 0:
        n = min(n, max(1, math.ceil(int(quota) / int(period))))
    return max(1, n)


def mem_gb(cg=CG, meminfo="/proc/meminfo"):
    """사용 가능한 메모리 상한(GB, cgroup 반영). 못 읽으면 None(Windows 등)."""
    vals = []
    mi = _read(meminfo)
    if mi:
        for ln in mi.splitlines():
            if ln.startswith("MemTotal:"):
                vals.append(int(ln.split()[1]) * 1024)
    for p in (cg / "memory.max", cg / "memory" / "memory.limit_in_bytes"):
        v = _read(p)
        if v and v.isdigit() and int(v) < 1 << 60:  # 'max'·아주 큰 값 = 한도 없음
            vals.append(int(v))
    if not vals and sys.platform == "win32":
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [
                    ("l", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong),
                    ("pt", ctypes.c_ulonglong),
                    ("pa", ctypes.c_ulonglong),
                    ("vt", ctypes.c_ulonglong),
                    ("va", ctypes.c_ulonglong),
                    ("ve", ctypes.c_ulonglong),
                ]

            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            vals.append(m.total)
        except Exception:
            pass
    return round(min(vals) / 1024**3, 1) if vals else None


def mem_used_pct(cg=CG, meminfo="/proc/meminfo"):
    """지금 쓰는 메모리 % — cgroup 한도가 있으면 그 안(memory.current/max), 없으면 시스템(MemAvailable·Windows dwMemoryLoad). 못 읽으면 None.
    cgroup v2: memory.current에는 파일 캐시(회수 가능)가 섞여 있어 큰 파일을 한 번 읽으면 사용률이 계속 높게 보여 새 작업이 영영 못 뜰 수 있음
    (docker stats·kubelet과 같은 보정) — memory.stat의 inactive_file(없으면 file)을 current에서 뺀다. v1·stat 없으면 current/max 그대로."""
    cur, mx = _read(cg / "memory.current"), _read(cg / "memory.max")
    if cur and mx and cur.isdigit() and mx.isdigit():
        used = int(cur)
        stat = _read(cg / "memory.stat")
        if stat:
            cache = {}
            for ln in stat.splitlines():
                k, _, v = ln.partition(" ")
                if v.isdigit():
                    cache[k] = int(v)
            reclaimable = cache.get("inactive_file", cache.get("file"))
            if reclaimable:
                used = max(0, used - reclaimable)
        return 100.0 * used / int(mx)
    mi = _read(meminfo)
    if mi:
        v = {ln.split(":")[0]: int(ln.split()[1]) for ln in mi.splitlines() if ln.split()[1:2] and ln.split()[1].isdigit()}
        if v.get("MemTotal") and "MemAvailable" in v:
            return 100.0 * (1 - v["MemAvailable"] / v["MemTotal"])
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [
                ("l", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("avail", ctypes.c_ulonglong),
                ("pt", ctypes.c_ulonglong),
                ("pa", ctypes.c_ulonglong),
                ("vt", ctypes.c_ulonglong),
                ("va", ctypes.c_ulonglong),
                ("ve", ctypes.c_ulonglong),
            ]

        m = MS()
        m.l = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return 100.0 * (1 - m.avail / m.total)
    return None


def wait_mem(start_pct=None, poll=5, log=print):
    """새 작업(프로세스)을 띄우기 전 문 — 메모리 사용률이 MEM_START_PCT(기본 90) 아래로 내려올 때까지 기다림.
    상한 85%(사용자 10-04)를 넘지 않게: 새 프로세스 몫(수 %)을 남기고 문을 닫는다. 측정 못 하면 그냥 통과."""
    import time

    lim = start_pct if start_pct is not None else _f("MEM_START_PCT", 90)
    waited = False
    while (u := mem_used_pct()) is not None and u >= lim:
        if not waited:
            log(f"[mem] 사용률 {u:.0f}% ≥ {lim:.0f}% — 새 작업 대기")
            waited = True
        time.sleep(poll)
    return mem_used_pct()


def cpu_limit(cg=CG):
    """cgroup CPU 한도(코어 수, 소수 가능) — v2 cpu.max "<quota> <period>"·v1 cpu.cfs_quota_us/cfs_period_us. 없거나("max", -1) 못 읽으면 None."""
    try:
        q = _read(cg / "cpu.max")
        if q and not q.startswith("max"):
            quota, period = q.split()[:2]
            return int(quota) / int(period)
        quota, period = _read(cg / "cpu" / "cpu.cfs_quota_us"), _read(cg / "cpu" / "cpu.cfs_period_us")
        if quota and period and int(quota) > 0:
            return int(quota) / int(period)
    except ValueError:
        pass
    return None


def _cg_usage_usec(cg=CG):
    """cgroup 누적 CPU 사용 시간(마이크로초) — v2 cpu.stat usage_usec · v1 cpuacct.usage(나노초). 못 읽으면 None."""
    st = _read(cg / "cpu.stat")
    for ln in (st or "").splitlines():
        k, _, v = ln.partition(" ")
        if k == "usage_usec" and v.strip().isdigit():
            return int(v)
    for rel in ("cpuacct/cpuacct.usage", "cpu,cpuacct/cpuacct.usage", "cpu/cpuacct.usage"):
        v = _read(cg / rel)
        if v and v.isdigit():
            return int(v) / 1000
    return None


def _host_cpus():
    n = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        n = min(n, len(os.sched_getaffinity(0)))
    return max(1, n)


_LAST: dict[str, tuple] = {}  # cg 경로 → (시각, usage_usec) — 앞 측정을 재사용해 매번 기다리지 않게


def cpu_load(cg=CG, sample=0.25, now=None, sleep=None, loadavg=None):
    """지금 CPU 부하(비율 — 1.0 = 쓸 수 있는 코어를 다 씀) 또는 None(측정 못 함 — 바로 통과).
    cgroup 한도가 있으면 그 cgroup의 사용량 증가 ÷ (한도 코어 × 지난 시간) — 앞 측정이 0.2~10초 전이면 그 사이로, 아니면 sample초 재서.
    ponytail: 앞 측정 재사용은 근사(띄우는 간격이 길면 최근 평균) — 정밀하게 하려면 배경 표본 스레드로.
    한도가 없거나 사용량을 못 읽으면 1분 부하 평균 ÷ 호스트 코어. now·sleep·loadavg는 시험용 바꿔 끼우기."""
    import time

    now, sleep, loadavg = now or time.monotonic, sleep or time.sleep, loadavg or _loadavg1
    lim = cpu_limit(cg)
    if lim:
        u1 = _cg_usage_usec(cg)
        if u1 is not None:
            t1 = now()
            prev = _LAST.get(str(cg))
            if not prev or not 0.2 <= t1 - prev[0] <= 10:
                sleep(sample)
                prev, (t1, u1) = (t1, u1), (now(), _cg_usage_usec(cg))
            _LAST[str(cg)] = (t1, u1)
            if u1 is not None and t1 > prev[0]:
                return max(0.0, (u1 - prev[1]) / (lim * (t1 - prev[0]) * 1e6))
    la = loadavg()
    return None if la is None else la / _host_cpus()


def _loadavg1():
    """1분 부하 평균(코어 환산 전) — Windows(getloadavg 없음)·못 읽으면 None."""
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):
        return None


def wait_cpu(max_load=None, poll=5, log=print):
    """새 작업을 띄우기 전 문 — cpu_load()(컨테이너면 자기 cgroup 사용량, 아니면 부하 평균 ÷ 호스트 코어)가 CPU_MAX_LOAD(기본 0.9 — 사용자 10-07:
    CPU 상한 90%) 아래로 내려올 때까지 기다림. 측정 못 하면(Windows 등) 바로 통과. 실행 중인 프로세스는 절대 안 건드림 — 새로 띄우는 것만 늦춤.
    반환: 마지막에 잰 부하(비율) 또는 None."""
    import time

    lim = max_load if max_load is not None else _f("CPU_MAX_LOAD", 0.9)
    waited = False
    while (load := cpu_load()) is not None and load >= lim:
        if not waited:
            log(f"[cpu] 부하 {load:.2f} ≥ {lim:.2f} — 새 작업 대기")
            waited = True
        time.sleep(poll)
    return load


_LAUNCH = threading.Lock()


def gated_popen(args, settle=None, log=print, **kwargs):
    """생산 파싱 경로(run_all·cli/pipeline)의 하위 프로세스 공용 launcher(옛 stack_matrix._sub 패턴을 공유 함수로).
    한 번에 하나씩: 메모리 문(사용률 < MEM_MAX_PCT, 기본 90 — 실험 도구 MEM_START_PCT와 같은 90) →
    CPU 문(부하 ÷ cpus() < CPU_MAX_LOAD, 기본 1.0 — Windows는 측정 못 해 바로 통과) 통과
    → subprocess.Popen(args, **kwargs) → (여유 있으면 바로 잠금 해제, 상한 가까이면만 settle초 쉬고 해제).
    settle은 사용률이 MEM_MAX_PCT − MEM_SETTLE_MARGIN(기본 5) 이상일 때만 적용 — 여유 있을 때 매번 쉬면 문서×엔진이
    많은 실행(예 200×16=3200건)에서 launch가 초당 1/settle로 묶여 전체가 크게 느려짐(코디네이터 10-04 성능 회귀 지적).
    측정 못 하면(None) settle 안 함. 실행 중인 프로세스는 절대 안 건드림(죽이지 않음) — 새로 띄우는 것만 늦춤.
    communicate·wait는 호출자가 잠금 밖에서(여기선 Popen만 — 느린 프로세스가 다음 launcher를 막지 않게)."""
    import subprocess
    import time

    lim = _f("MEM_MAX_PCT", 90)
    with _LAUNCH:
        u = wait_mem(start_pct=lim, log=log)
        wait_cpu(log=log)
        pr = exitclean.track(
            subprocess.Popen(args, **kwargs), group=bool(kwargs.get("start_new_session"))
        )  # pl-27 — 끝날 때 아직 돌면 끝내고 회수
        if u is not None and u >= lim - _f("MEM_SETTLE_MARGIN", 5):
            time.sleep(settle if settle is not None else _f("MEM_SETTLE_SEC", 2))
    return pr


def _given(name):
    """env 이름 칸에 값을 실제로 준 것(YAML·env·시험 — 기본값은 아님)이면 그 값(아니면 None) — settings.given.
    S7b — 이 파일의 숫자 칸은 모델에 기본값이 있어도 읽는 쪽 기본값이 호출마다 달라서(예: PIPE_PROCS는 계산값) 준 값인지부터 가린다.
    비움·auto·형식 틀린 값은 준 것으로 치지 않는다(객체가 설정 안 함·경고 뒤 기본값으로 처리). 칸 없는 이름도 None."""
    from common.config.settings import given  # 늦게 import(이 파일은 거의 모든 프로세스가 import)

    v = given(name)
    return None if v == "auto" else v  # PIPE_PROCS 칸은 'auto'를 글자로 기억(S7c1 — run_all 기본이 가름) — 여기서는 옛처럼 비움과 같게


def _f(name, default):
    v = _given(name)
    return float(v) if v is not None else default


def plan(cpu=None, mem=None):
    """→ {cpus, mem_gb, procs, threads, workers, why}."""
    cpu = cpus() if cpu is None else cpu
    mem = mem_gb() if mem is None else mem
    by_cpu = max(1, cpu - int(_f("PIPE_RESERVE_CPUS", 1)))
    by_mem = max(1, int((mem - _f("PIPE_RESERVE_GB", 4)) // _f("PIPE_PROC_GB", 3))) if mem else by_cpu
    procs = int(
        _f("PIPE_PROCS", min(by_cpu, by_mem, int(_f("PIPE_MAX_PROCS", 8))))
    )  # 상한: 프로세스마다 모델을 올리므로 많이 띄워도 이득이 줄어듦
    threads = int(_f("PIPE_THREADS", max(1, cpu // procs)))
    workers = int(_f("PIPE_WORKERS", 4))
    why = (
        "PIPE_PROCS 지정"
        if _given("PIPE_PROCS") is not None
        else f"CPU {cpu} − 예비 → {by_cpu} · 메모리 {mem} GB → {by_mem} · 상한 {int(_f('PIPE_MAX_PROCS', 8))}"
    )
    return {"cpus": cpu, "mem_gb": mem, "procs": max(1, procs), "threads": max(1, threads), "workers": max(1, workers), "why": why}


def vlm_page_concurrency(doc_workers, requested):
    """파싱 VLM 쪽 동시 요청 수 — 문서 동시 수(doc_workers) × 이 값이 공유 VLM 서버 동시 요청 총량.
    VLM_MAX_CONCURRENCY(기본 8)를 넘지 않게 요청값을 줄인다(문서 동시 수는 그대로 — CPU·메모리로 이미 정해짐)."""
    cap = int(_f("VLM_MAX_CONCURRENCY", 8))
    return max(1, min(int(requested), cap // max(1, int(doc_workers))))


if __name__ == "__main__":
    utf8_stdout()
    if "--env" in sys.argv:
        p = plan()
        print(f"export PIPE_PROCS={p['procs']} PIPE_THREADS={p['threads']} PIPE_WORKERS={p['workers']}")
    else:
        p = plan()
        print(
            f"CPU {p['cpus']} · 메모리 {p['mem_gb']} GB → CPU 엔진 프로세스 {p['procs']} × 스레드 {p['threads']} · VLM 동시 문서 {p['workers']}  ({p['why']})"
        )
