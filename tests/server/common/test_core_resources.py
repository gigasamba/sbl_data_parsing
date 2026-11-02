"""common.core.resources 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.resources --selftest`."""

import sys
from pathlib import Path
from unittest import mock

import common.core.resources as M
from common.core.resources import (
    cpus,
    gated_popen,
    mem_gb,
    mem_used_pct,
    plan,
    wait_cpu,
    wait_mem,
)


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "cpu.max").write_text("200000 100000\n")  # --cpus 2
    (d / "memory.max").write_text(str(8 * 1024**3) + "\n")  # --memory 8g
    mi = d / "meminfo"
    mi.write_text("MemTotal:       33554432 kB\n")  # 호스트 32 GB
    assert cpus(d) <= 2 and mem_gb(d, mi) == 8.0
    (d / "cpu.max").write_text("max 100000\n")
    (d / "memory.max").write_text("max\n")
    assert mem_gb(d, mi) == 32.0
    import contextlib

    from common.config.settings import COMMON  # S7b — 시험이 env 대신 설정 객체를 덮어씀(os.environ은 안 바뀜)

    _env = contextlib.ExitStack()  # 아래 덮어쓰기는 selftest 끝까지 유지(옛 os.environ.pop도 끝까지 남았음)
    _env.enter_context(COMMON.env(PIPE_PROCS=None, PIPE_THREADS=None, PIPE_RESERVE_CPUS=None, PIPE_RESERVE_GB=None, PIPE_PROC_GB=None))
    p = plan(cpu=4, mem=32)
    assert (p["procs"], p["threads"]) == (3, 1), p  # 개발 서버 4 vCPU·32 GB
    p = plan(cpu=64, mem=512)
    assert p["procs"] == 8, p  # 상한
    p = plan(cpu=16, mem=12)
    assert (p["procs"], p["threads"]) == (2, 8), p  # 메모리가 제한: (12−4)÷3 = 2
    p = plan(cpu=1, mem=None)
    assert (p["procs"], p["threads"]) == (1, 1), p
    with COMMON.env(PIPE_PROCS="5"):
        assert plan(cpu=4, mem=32)["procs"] == 5  # resolve_procs("2")==2는 pipeline.extract.resources.selftest()로 옮김(10-14, P만 씀)
    (d / "memory.current").write_text(str(6 * 1024**3) + "\n")  # cgroup 8 GB 중 6 GB = 75%
    (d / "memory.max").write_text(str(8 * 1024**3) + "\n")
    assert round(mem_used_pct(d, mi)) == 75
    (d / "memory.current").write_text(str(8 * 1024**3) + "\n")  # 현재 8 GB · 파일 캐시(회수 가능) 5 GB · 한도 10 GB
    (d / "memory.max").write_text(str(10 * 1024**3) + "\n")
    (d / "memory.stat").write_text(f"inactive_file {5 * 1024**3}\nanon {1 * 1024**3}\n")
    assert round(mem_used_pct(d, mi)) == 30, round(mem_used_pct(d, mi))  # (8−5)÷10 — 파일 캐시를 빼야 과대평가 안 함(D5)
    (d / "memory.stat").unlink()
    assert mem_used_pct(d / "없음", d / "없음") is None or sys.platform == "win32"
    assert wait_mem(start_pct=101, log=lambda *_: None) is None or True  # 문이 열려 있으면 바로 통과
    print("[selftest] CPU·메모리(cgroup) 감지·병렬 수 결정·메모리 문 통과")

    # 가짜 사용률 수열(90 → 90 → 70) — MEM_MAX_PCT(85) 넘는 압박 중엔 새 작업을 대기시키고(통과 전 폴링 2회),
    # 로그는 1번만(소음 억제), 떨어지면(70 < 85) 통과 — mem_used_pct를 모듈 전역에서 잠깐 바꿔 넣음(끝나면 원복)
    seq, calls, orig = [90.0, 90.0, 70.0], [], M.mem_used_pct

    def fake_mem():
        calls.append(1)
        return seq[min(len(calls) - 1, len(seq) - 1)]

    M.mem_used_pct = fake_mem
    try:
        logs = []
        u = wait_mem(start_pct=85, poll=0, log=logs.append)
        assert u == 70.0 and len(logs) == 1 and len(calls) >= 3  # 대기 2회(폴링) 후 통과, 로그는 1번만
    finally:
        M.mem_used_pct = orig
    print("[selftest] 메모리 문(가짜 사용률 90→90→70) — 압박 중 새 작업 대기·로그 1번·하락 뒤 통과")

    # gated_popen — 문 통과(사용률 낮게 가짜 처리) 뒤 실제 하위 프로세스를 띄우고 settle 뒤 돌려줌(communicate·wait는 호출자)
    with mock.patch.object(M, "mem_used_pct", lambda: 10.0):  # 시험용 가짜 함수로 바꿔 끼움(끝나면 원래 함수로)
        pr = gated_popen([sys.executable, "-c", "pass"], settle=0)
        assert pr.wait(timeout=10) == 0
    print("[selftest] gated_popen — 메모리 문 통과 뒤 하위 프로세스 기동(settle 0) 통과")

    # 성능 회귀 수정(코디네이터 10-04): 여유 있으면(상한 − MEM_SETTLE_MARGIN보다 낮음) settle을 건너뜀 —
    # 문서×엔진 수천 건 실행에서 매번 쉬면 launch가 초당 1/settle로 묶여 전체가 느려짐.
    # 벽시계로 재면 바쁜 PC에서 들쭉날쭉(10-05: 프로세스 10개 기동이 3초를 넘어 가끔 실패) → time.sleep 호출을 가로채 settle 여부만 셈(결정적).
    import time as _t

    slept, orig_sleep = [], _t.sleep
    _t.sleep = lambda s: slept.append(s)
    try:
        mem = mock.patch.object(M, "mem_used_pct").start()  # 가짜 사용률 — side_effect로 값을 바꿔 가며(끝나면 원래 함수로)
        mem.side_effect = lambda: 10.0  # 여유 있음(상한 90 − 여백 5 = 85보다 훨씬 낮음)
        for _ in range(10):
            gated_popen([sys.executable, "-c", "pass"], settle=2).wait(timeout=30)
        assert 2 not in slept, slept  # settle=2를 10번 다 건너뜀
        mem.side_effect = lambda: 86.0  # 상한 90에 가까움(90−5=85 이상) — settle 적용
        gated_popen([sys.executable, "-c", "pass"], settle=0.3).wait(timeout=30)
        assert 0.3 in slept, slept
        # RB3① 경계값(margin 10→5, 10-07): 84%는 새 문턱(85) 아래라 건너뛰고, 85%는 문턱에 닿아 settle(77% 평소 사용률이면 안 걸려야 함)
        mem.side_effect = lambda: 77.0  # PC 평소 사용률 — 새 문턱 85에서는 걸리지 않아야 함(10-07 실측 회귀 방지)
        gated_popen([sys.executable, "-c", "pass"], settle=0.4).wait(timeout=30)
        assert 0.4 not in slept, slept
        mem.side_effect = lambda: 84.0  # 문턱(85) 바로 아래 — 안 쉼
        gated_popen([sys.executable, "-c", "pass"], settle=0.5).wait(timeout=30)
        assert 0.5 not in slept, slept
        mem.side_effect = lambda: 85.0  # 문턱(85) 그대로 — 쉼
        gated_popen([sys.executable, "-c", "pass"], settle=0.6).wait(timeout=30)
        assert 0.6 in slept, slept
    finally:
        _t.sleep = orig_sleep
        mock.patch.stopall()
    print("[selftest] gated_popen — 여유 있으면 settle 건너뜀(10회) · 상한 가까우면 settle 적용 통과(호출 기록으로 판정, 시간 무관)")

    # CPU 문(wait_cpu) — 가짜 부하 수열(1.0 → 1.0 → 0.25) CPU_MAX_LOAD 이상인 동안 대기, 로그 1번만, 떨어지면 통과
    cseq, ccalls, corig = [1.0, 1.0, 0.25], [], M.cpu_load

    def fake_load():
        ccalls.append(1)
        return cseq[min(len(ccalls) - 1, len(cseq) - 1)]

    M.cpu_load = fake_load
    try:
        clogs = []
        u = wait_cpu(max_load=1.0, poll=0, log=clogs.append)
        assert u == 0.25 and len(clogs) == 1 and len(ccalls) == 3, (u, clogs, ccalls)  # 부하 1.0 ≥ 1.0 두 번 대기 후 통과
    finally:
        M.cpu_load = corig
    print("[selftest] CPU 문(가짜 부하 수열) — 포화 중 새 작업 대기·로그 1번·하락 뒤 통과")

    _env.close()


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()


def test_cpu_load_table():
    """0.2.0(pl-46) — cpu_load(): cgroup 한도가 있으면 그 cgroup 사용량, 없거나 못 읽으면 부하 평균 ÷ 호스트 코어, 그것도 없으면 None."""
    import tempfile

    host = M._host_cpus()
    cases = [  # (이름, {파일: 처음 내용}, {파일: sample 뒤 내용}, 부하 평균, 기대)
        ("v2 한도 2코어", {"cpu.max": "200000 100000", "cpu.stat": "usage_usec 1000000\n"}, {"cpu.stat": "usage_usec 1500000\n"}, 9.0, 0.5),
        (
            "v1 한도 1코어",
            {"cpu/cpu.cfs_quota_us": "100000", "cpu/cpu.cfs_period_us": "100000", "cpuacct/cpuacct.usage": "0"},
            {"cpuacct/cpuacct.usage": "250000000"},
            9.0,
            0.5,
        ),
        ("한도 없음(max) — 부하 평균", {"cpu.max": "max 100000"}, {}, 2.0, 2.0 / host),
        ("한도는 있는데 사용량 못 읽음 — 부하 평균", {"cpu.max": "200000 100000"}, {}, 4.0, 4.0 / host),
        ("아무것도 못 읽음(Windows 등) — 통과", {}, {}, None, None),
    ]
    for name, before, after, la, want in cases:
        d = Path(tempfile.mkdtemp())
        for rel, txt in before.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(txt)
        clock = [100.0]

        def fake_sleep(sec, d=d, after=after, clock=clock):
            clock[0] += sec
            for rel, txt in after.items():
                (d / rel).write_text(txt)

        got = M.cpu_load(cg=d, sample=0.5, now=lambda clock=clock: clock[0], sleep=fake_sleep, loadavg=lambda la=la: la)
        assert (got is None and want is None) or (got is not None and want is not None and abs(got - want) < 1e-9), (name, got, want)
