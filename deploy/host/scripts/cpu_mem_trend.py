#!/usr/bin/env python3
"""CPU·메모리 사용 추이 로거(2026-10-22 사용자 지정) — 5초 간격, 종료 시까지.

출력: test_space/batch_progress/cpu_mem_trend.csv  — time,cpu_pct,mem_used_gib,mem_avail_gib
사용: nohup python3 cpu_mem_trend.py &  → 분석: tail 후 평균/최고 집계
"""

import time
from pathlib import Path

OUT = Path(__file__).resolve().parent / "cpu_mem_trend.csv"


def cpu():
    t = list(map(int, open("/proc/stat").readline().split()[1:]))
    return sum(t), t[3] + t[4]


def mem():
    d = {}
    for ln in open("/proc/meminfo"):
        k, _, v = ln.partition(":")
        d[k] = int(v.strip().split()[0]) / 1024**2  # GiB
    return d["MemTotal"] - d["MemAvailable"], d["MemAvailable"]


with OUT.open("a", encoding="utf-8") as f:
    f.write("time,cpu_pct,mem_used_gib,mem_avail_gib\n")
    a = cpu()
    while True:
        time.sleep(5)
        b = cpu()
        dt, di = b[0] - a[0], b[1] - a[1]
        a = b
        used, avail = mem()
        f.write(f"{time.strftime('%H:%M:%S')},{(dt - di) / dt * 100 if dt else 0:.1f},{used:.1f},{avail:.1f}\n")
        f.flush()
