"""호스트 flow 러너 run_docs.py의 main() 흐름 배선 — main()이 레인 스레드를 띄우고 끝까지 기다리며 구조화 센티널·마지막 로그까지
도는지 고정한다(refactor.md C-59).
run_docs.py는 로컬에서 실행하지 않는다(CLAUDE.md §4) — 설정·docker·EDW·다운로드·파싱·구조화 함수를 가짜로 바꾸고 문서 2건으로 main()만 돌린다
(운영 접속·docker·DB 없음). 끝 대기가 5초 간격이라 몇 초 걸린다. main()이 umask·모듈 상태를 바꾸므로 자식 프로세스로 돈다(INPROCESS 아님)."""

import importlib.util
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from common.core.paths import DEPLOY_ROOT

ROOT = DEPLOY_ROOT  # 저장소 루트(paths 상수)


def _load():
    spec = importlib.util.spec_from_file_location("run_docs_flow_under_test", ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


def _ok_pub(seq, row):
    return True


def _ok_gold(seq, row, enq_t=None):
    return True


def _run_main(work, rows, parse_one, gold_one=_ok_gold, publish_one=_ok_pub, drops=None, setup=None, args=()):
    """가짜 함수로 main()을 돌리고 모듈을 돌려준다(종료 코드는 M.rc). 외부 명령 가드는 main() 스레드가 끝날 때까지 유지한다(멈추면 가드 안에서 실패).
    drops(목록)를 주면 정리 호출을 ("orig"|"temp", seq)로 적는다(pl-24 순서 시험) — 정리 함수가 예외를 내게 하려면 setup에서 바꿈."""
    M = _load()
    rec = drops if drops is not None else []

    class _FastTime:  # run_docs의 5초 대기 고리(_mcp_pause_monitor·흐름 끝 기다림)를 짧게 — 다른 time 기능은 그대로
        def __getattr__(self, name):
            return getattr(time, name)

        @staticmethod
        def sleep(sec):
            time.sleep(min(sec, 0.05))

    M.time = _FastTime()

    def configure(_settings):  # 설정 파일 대신 — 작업 폴더만 임시 폴더로
        M.TEST, M.PROG = work, work / "batch_progress"
        M.DOCSPACE = work / "out"
        M.DOCFLOW, M.WARM = M.DOCSPACE / "_docflow", M.DOCSPACE / "_warm"
        M.MCP_JOBS_DIR = work / "jobs"
        if setup:
            setup(M)
        return []

    M.configure = configure
    M.edw_list = lambda keywords=(), where=None: rows
    M.faq_first = lambda rows, order: order  # FAQ 교체는 test_run_docs.test_faq_first에서
    M.stack_check = lambda: None  # 엔진 구성 파일 확인(docker exec) 대신
    M.warm_one = lambda seq, row: True
    M.classify_doc = lambda seq, row, cache=None: M._class.setdefault(seq, "light")  # 레인 분류(docker exec) 대신 — 규칙은 test_doc_group
    M.parse_one, M.publish_one, M.gold_one = parse_one, publish_one, gold_one
    M.drop_original = lambda seq, row: rec.append(("orig", seq))
    M.drop_temp = lambda seq: rec.append(("temp", seq))
    M.take_lock = lambda path: object()  # flock(fcntl — Linux 호스트)은 test_lock_blocks_second_run이 따로
    M.pg_count = lambda: (0, 0)
    M.rc = None
    argv = sys.argv
    sys.argv = ["run_docs.py", "--start-offset", "0", "--settings", str(work / "unused.yaml"), *args]
    # 가짜로 바꾸지 않은 외부 명령(docker exec·셸)이 불리면 바로 실패 — main()에 새 부작용이 생겨도 운영 쪽으로 새지 않게
    no_shell = AssertionError("시험 중 외부 명령 호출 — 가짜로 바꾸지 않은 부작용")
    try:
        with (
            mock.patch.object(M.subprocess, "run", side_effect=no_shell),
            mock.patch.object(M.subprocess, "Popen", side_effect=no_shell),
        ):
            t = threading.Thread(target=lambda: setattr(M, "rc", M.main()), daemon=True)
            t.start()
            t.join(timeout=120)
            assert not t.is_alive(), "main()이 120초 안에 끝나지 않음"  # 가드 안에서 — 멈춘 스레드가 가드 밖에서 실제 명령을 부르지 않게
    finally:
        sys.argv = argv
    return M


def test_main_runs_lanes_to_end():
    """main()이 레인 스레드를 띄워 문서마다 파싱 → 구조화를 부르고, 모두 끝나면 마지막 로그를 남기고 돌아온다."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    calls: dict[str, list[int]] = {"parse": [], "struct": []}
    with tempfile.TemporaryDirectory(prefix="orca_s12_") as tmp:
        work = Path(tmp)

        def parse_one(seq, row):
            calls["parse"].append(seq)
            return True, work / f"{seq}"

        def gold_one(seq, row, enq_t=None):
            calls["struct"].append(seq)
            return True

        M = _run_main(work, rows, parse_one, gold_one)
        assert sorted(calls["parse"]) == [0, 1], calls  # 레인 스레드가 _one → parse_one을 부름
        assert sorted(calls["struct"]) == [0, 1], calls  # 파싱 OK → 게시 → 구조화 대기열 → gold_one
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 2건(완료 2 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 0)" in log, log
        assert M.rc == 0


def test_main_survives_errors_in_failure_path():
    """예외 처리 중 다시 예외(정리 함수 실패 — 디스크 가득 등)가 나도 작업 스레드가 죽지 않고 main()이 실패 수를 세고 끝난다."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    with tempfile.TemporaryDirectory(prefix="orca_s12_") as tmp:
        work = Path(tmp)

        def parse_one(seq, row):  # 문서 0은 파싱 실패, 문서 1은 통과
            return seq == 1, work / f"{seq}"

        def gold_one(seq, row, enq_t=None):
            raise RuntimeError("구조화 실패(시험)")

        def setup(M):
            def boom(*a):
                raise OSError("정리 실패(시험 — 디스크 가득 흉내)")

            M.drop_original = M.drop_temp = boom

        M = _run_main(work, rows, parse_one, gold_one, setup=setup)
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 2건(완료 0 · 파싱실패 1 · 게시실패 0 · gold실패 1 · 스레드 예외 0)" in log, log
        assert M.rc == 1


def test_thread_error_fails_the_run():
    """gold 뒤 기록(mark — 디스크 가득 등)이 예외를 내도 집계는 먼저 되고, 스레드 예외는 실패로 세어 종료 코드 1."""
    rows = [{"id": 0, "s3_key": "k0", "original_filename": "doc0.txt", "file_size": 10}]
    with tempfile.TemporaryDirectory(prefix="orca_thr_") as tmp:
        work = Path(tmp)

        def setup(M):
            real = M.mark

            def mark(seq, event, **extra):
                if event == "done":
                    raise OSError("기록 실패(시험 — 디스크 가득 흉내)")
                return real(seq, event, **extra)

            M.mark = mark

        M = _run_main(work, rows, lambda seq, row: (True, work / f"{seq}"), setup=setup)
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "완료 1 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 1" in log, log
        assert M.rc == 1


def test_warm_error_does_not_hang():
    """받기 워커에서 예외가 나도 main()이 끝나고(_warming에 남지 않음) 실패로 세어 종료 코드 1."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    with tempfile.TemporaryDirectory(prefix="orca_warm_") as tmp:
        work = Path(tmp)

        def setup(M):
            def warm_one(seq, row):
                if seq == 0:
                    raise OSError("받기 실패(시험 — 디스크 가득 흉내)")
                return True

            M.warm_one = warm_one

        M = _run_main(work, rows, lambda seq, row: (True, work / f"{seq}"), setup=setup)
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "완료 1 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 1" in log, log
        assert M.rc == 1 and not M._warming


def test_depth_write_error_does_not_hang():
    """대기열 깊이 기록(depth)이 디스크 오류를 내도 main()이 멈추지 않고 정상 끝(관찰용 기록)."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    with tempfile.TemporaryDirectory(prefix="orca_depth_") as tmp:
        work = Path(tmp)

        def setup(M):
            (M.PROG / "queue_depth.jsonl").mkdir(parents=True)  # 파일 자리에 폴더 — open("a")가 OSError

        M = _run_main(work, rows, lambda seq, row: (True, work / f"{seq}"), setup=setup)
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "완료 2 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 0" in log, log
        assert M.rc == 0


def test_struct_backlog_holds_new_parses():
    """중간 대기(파싱 끝·구조화 대기)가 상한이면 레인 워커가 새 파싱을 시작하지 않는다(rn-02) — pick 순간의 대기 길이 < 상한."""
    import json
    import time

    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(8)]
    with tempfile.TemporaryDirectory(prefix="orca_rn02_") as tmp:
        work = Path(tmp)

        def setup(M):
            M._BACKLOG_SETTING, M.STRUCT_WORKERS = 1, 1  # 상한 1 · 구조화 1개(느림)

        def gold_one(seq, row, enq_t=None):
            time.sleep(0.3)
            return True

        M = _run_main(work, rows, lambda seq, row: (True, work / f"{seq}"), gold_one, setup=setup)
        lines = [json.loads(x) for x in (M.PROG / "queue_depth.jsonl").read_text(encoding="utf-8").splitlines()]
        picks = [x for x in lines if x["event"] == "pick"]
        assert len(picks) == 8, len(picks)
        waits = [x["pub_wait"] + x["struct_wait"] for x in picks]
        assert all(w < 1 for w in waits), waits  # 상한 = 게시 대기 + 구조화 대기(파싱 끝·gold 전)
        assert max(x["struct_wait"] for x in lines) >= 1  # 실제로 쌓였다가 막힘(시험이 헛돌지 않음)
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 8건(완료 8" in log and "light 1/1 medium 1/1 vlm 1/1" in log, log


def _lanes_by_name(M):  # 분류(docker probe)를 가짜로 — 파일 이름 앞부분이 레인(rn-04)
    def classify_doc(seq, row, cache=None):
        M._class[seq] = row["original_filename"].split("_", 1)[0]
        return M._class[seq]

    M.classify_doc = classify_doc


def test_medium_vlm_lanes_and_vlm_cap():
    """medium·vlm 레인도 끝까지 돌고, vlm 문서 동시 파싱은 vlm_cap을 넘지 않는다(rn-04)."""
    lanes = ["light", "medium", "vlm"] * 3
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"{c}_{i}.bin", "file_size": 10} for i, c in enumerate(lanes)]
    seen, live, peak, lock = [], {"vlm": 0}, {"vlm": 0}, threading.Lock()
    with tempfile.TemporaryDirectory(prefix="orca_rn04_") as tmp:
        work = Path(tmp)

        def parse_one(seq, row):
            lane = lanes[seq]
            with lock:
                seen.append((seq, lane, threading.current_thread().name))
                live[lane] = live.get(lane, 0) + 1
                peak["vlm"] = max(peak["vlm"], live["vlm"])
            time.sleep(0.1)
            with lock:
                live[lane] -= 1
            return True, work / f"{seq}"

        def setup(M):
            _lanes_by_name(M)
            M.VLM_CAP = 1

        M = _run_main(work, rows, parse_one, setup=setup)
        assert sorted(s for s, _, _ in seen) == list(range(9)), seen
        assert {M._class[s] for s, _, _ in seen} == {"light", "medium", "vlm"}, M._class
        assert peak["vlm"] <= 1, peak  # vlm_cap 1 — 전담·공유 워커가 함께 있어도
        assert any(t == "lane-medium-own" and lane == "medium" for _, lane, t in seen), seen  # medium 전담 워커가 실제로 일함
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 9건(완료 9" in log, log


def test_mcp_busy_yields_medium_own_worker():
    """MCP 업로드 처리 중(_mcp_pause)이면 medium 전담 워커는 새 문서를 안 뽑고, medium 문서는 공유 워커가 처리한다(rn-04)."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"medium_{i}.bin", "file_size": 10} for i in range(4)]
    seen = []
    with tempfile.TemporaryDirectory(prefix="orca_rn04_") as tmp:
        work = Path(tmp)
        job = work / "jobs" / (time.strftime("%Y%m%d") + "-abc")
        job.mkdir(parents=True)

        def parse_one(seq, row):
            (job / "status").write_text("running", encoding="utf-8")  # 작업 파일이 계속 갱신됨 — 감시가 계속 '처리 중'으로 봄
            seen.append(threading.current_thread().name)
            return True, work / f"{seq}"

        def setup(M):
            _lanes_by_name(M)
            (job / "status").write_text("running", encoding="utf-8")
            M._mcp_pause = True  # 감시 스레드의 첫 판정 전에 레인이 뽑지 않게(감시도 같은 값을 냄)

        M = _run_main(work, rows, parse_one, setup=setup)
        # medium 전담 워커는 안 뽑음 — 공유 워커(어느 레인이든)가 처리(어느 공유 워커가 먼저 뜨는지는 스레드 순서라 묻지 않음)
        assert len(seen) == 4 and all(t.endswith("-shared") for t in seen), seen
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}


def test_mcp_busy_scans_recent_job_folders_only():
    """mcp_busy는 이름 날짜가 어제·오늘·내일인 작업 폴더에서 30초 안에 바뀐 파일만 본다(rn-04 — 5초마다 jobs 전체를 훑지 않게)."""
    import os

    M = _load()
    today = time.strftime("%Y%m%d")
    cases = [  # (작업 폴더 이름, 파일 나이(초), 기대)
        (f"{today}-new", 0, True),
        (f"{today}-old", 120, False),
        ("20000101-stale", 0, False),  # 지난 날 작업은 파일이 새로 바뀌어도 안 봄
        (None, 0, False),  # 작업 폴더 없음
    ]
    for name, age, want in cases:
        with tempfile.TemporaryDirectory(prefix="orca_rn04_") as tmp:
            M.MCP_JOBS_DIR = Path(tmp) / "jobs"
            if name:
                f = M.MCP_JOBS_DIR / name / "out" / "x.json"
                f.parent.mkdir(parents=True)
                f.write_text("{}", encoding="utf-8")
                t = time.time() - age
                os.utime(f, (t, t))
            assert M.mcp_busy() is want, (name, age, want)


# ── pl-24 문서별 순서 · pl-18 종료 코드 ──
# (파싱 OK, 게시 OK, gold OK) → 문서 하나의 호출 차례(정리 포함), 종료 코드
ORDER_CASES = [
    ((True, True, True), ["parse", "publish", "orig", "gold", "temp"], 0),
    ((True, True, False), ["parse", "publish", "orig", "gold", "temp"], 1),  # gold 실패 — silver는 이미 게시됨, 원본은 게시 뒤 지움
    ((True, False, True), ["parse", "publish", "temp"], 1),  # 게시 실패 — 원본 남김, gold 안 감
    ((False, True, True), ["parse", "temp"], 1),  # 파싱 실패 — 원본 남김, 게시·gold 안 감
]


def test_doc_order_and_exit_code():
    """pl-24: 파싱 → silver 게시 → 원본 삭제(게시 성공 뒤에만) → gold → 임시 삭제. pl-18: 실패가 있으면 1."""
    rows = [{"id": 0, "s3_key": "k0", "original_filename": "doc0.txt", "file_size": 10}]
    for (p_ok, pub_ok, g_ok), want, rc in ORDER_CASES:
        ev: list = []
        with tempfile.TemporaryDirectory(prefix="orca_pl24_") as tmp:
            work = Path(tmp)
            M = _run_main(
                work,
                rows,
                lambda seq, row, ok=p_ok, ev=ev, w=work: (ev.append("parse"), (ok, w))[1],
                lambda seq, row, enq_t=None, ok=g_ok, ev=ev: (ev.append("gold"), ok)[1],
                lambda seq, row, ok=pub_ok, ev=ev: (ev.append("publish"), ok)[1],
                drops=_Rec(ev),
            )
        assert ev == want and M.rc == rc, ((p_ok, pub_ok, g_ok), ev, M.rc)


class _Rec(list):
    """정리 호출을 같은 차례 목록에 이름만 넣음(("orig", 0) → "orig")."""

    def __init__(self, ev):
        super().__init__()
        self.ev = ev

    def append(self, item):
        self.ev.append(item[0])


def test_exit_codes():
    """pl-18: 대상 0건 = 0 · 마감 도달(실패 없음) = 75 · 다른 run_docs가 도는 중 = 75."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    ok_parse = lambda seq, row: (True, Path("."))  # 시험 한 줄

    def past_deadline(M):
        M.deadline_at = lambda hhmm: time.time() - 1

    def locked(M):
        M.take_lock = lambda path: None

    cases = [  # (rows, setup, args, 기대 종료 코드, 로그에 있어야 할 글자)
        ([], None, (), 0, "종료"),
        (rows, past_deadline, ("--deadline", "05:00"), 75, "마감 — 남은 2건"),
        (rows, locked, (), 75, "다른 run_docs가 도는 중"),
    ]
    for rws, setup, args, want, text in cases:
        with tempfile.TemporaryDirectory(prefix="orca_pl18_") as tmp:
            M = _run_main(Path(tmp), rws, ok_parse, setup=setup, args=args)
            log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert M.rc == want and text in log, (args, M.rc, log)


def test_lock_blocks_second_run():
    """pl-18 잠금: 한 프로세스가 쥐면 다른 열기는 None(flock — 호스트 Linux 전용, fcntl 없는 PC는 건너뜀)."""
    import importlib.util as iu
    import subprocess

    if iu.find_spec("fcntl") is None:  # 실행기(tests/runner.py)에 건너뛰기가 없어 그냥 끝냄 — macOS·Linux·WSL에서 돎
        print("[시험] fcntl 없음(Windows) — 잠금 시험 건너뜀")
        return

    M = _load()
    with tempfile.TemporaryDirectory(prefix="orca_pl18_") as tmp:
        lock = Path(tmp) / "run_docs.lock"
        held = M.take_lock(lock)
        assert held is not None
        # flock은 같은 프로세스 안 다른 열기도 막지만, 실제 상황(다른 프로세스)으로 확인
        code = (
            "import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('rd',{str(ROOT / 'deploy' / 'host' / 'scripts' / 'run_docs.py')!r});"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            f"sys.exit(0 if m.take_lock({str(lock)!r}) is None else 1)"
        )
        assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
        held.close()
        assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 1  # 풀린 뒤에는 잡힘
