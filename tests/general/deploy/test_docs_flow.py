"""호스트 flow 러너 run_docs.py의 main() 흐름 배선(S12, 사용자 10-29 — refactor.md C-59).
10-23 "MCP 업로드 감시" 수정 때 mcp_busy·_mcp_pause_monitor가 main() 한가운데에 끼어들어 lane_worker와 그 뒤(레인 스레드 시작·끝 대기·
구조화 센티널·마지막 로그)가 main() 밖으로 빠졌다 — main()이 파싱 스레드를 띄우지 않고 끝났다(pre-refactor부터). 이 시험이 그 배선을 고정한다.
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

ROOT = DEPLOY_ROOT  # 저장소 루트(op-09 — paths 상수)


def _load():
    spec = importlib.util.spec_from_file_location("run_docs_flow_under_test", ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


def _run_main(work, rows, parse_one, structure_one, cleanup_doc, setup=None):
    """가짜 함수로 main()을 돌리고 모듈을 돌려준다. 외부 명령 가드는 main() 스레드가 끝날 때까지 유지한다(멈추면 가드 안에서 실패)."""
    M = _load()

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
        M.DOCFLOW, M.WARM = M.DOCSPACE / "docflow", M.DOCSPACE / "_warm"
        M.MCP_JOBS_DIR = work / "jobs"
        if setup:
            setup(M)
        return []

    M.configure = configure
    M.code_layout_problems = lambda: []
    M.edw_list = lambda keywords: rows
    M.write_envfile = lambda: 0
    M.stack_version = lambda: ""  # 판 번호(docker exec) 대신 — PC 파일(pl-32)
    M.warm_one = lambda seq, row: True
    M.parse_one, M.structure_one, M.cleanup_doc = parse_one, structure_one, cleanup_doc
    M.pg_count = lambda: (0, 0)
    argv = sys.argv
    sys.argv = ["run_docs.py", "--start-offset", "0", "--settings", str(work / "unused.yaml")]
    # 가짜로 바꾸지 않은 외부 명령(docker exec·셸)이 불리면 바로 실패 — main()에 새 부작용이 생겨도 운영 쪽으로 새지 않게(S12 /simplify)
    no_shell = AssertionError("시험 중 외부 명령 호출 — 가짜로 바꾸지 않은 부작용")
    try:
        with (
            mock.patch.object(M.subprocess, "run", side_effect=no_shell),
            mock.patch.object(M.subprocess, "Popen", side_effect=no_shell),
        ):
            t = threading.Thread(target=M.main, daemon=True)
            t.start()
            t.join(timeout=120)
            assert not t.is_alive(), "main()이 120초 안에 끝나지 않음"  # 가드 안에서 — 멈춘 스레드가 가드 밖에서 실제 명령을 부르지 않게
    finally:
        sys.argv = argv
    return M


def test_main_runs_lanes_to_end():
    """main()이 레인 스레드를 띄워 문서마다 파싱 → 구조화를 부르고, 모두 끝나면 마지막 로그를 남기고 돌아온다."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    calls: dict[str, list[int]] = {"parse": [], "struct": [], "cleanup": []}
    with tempfile.TemporaryDirectory(prefix="orca_s12_") as tmp:
        work = Path(tmp)

        def parse_one(seq, row):
            calls["parse"].append(seq)
            return True, work / f"{seq}"

        def structure_one(seq, row, enq_t=None):
            calls["struct"].append(seq)
            return True

        M = _run_main(work, rows, parse_one, structure_one, lambda seq, row: calls["cleanup"].append(seq))
        assert sorted(calls["parse"]) == [0, 1], calls  # 레인 스레드가 _one → parse_one을 부름(결함 때는 0건)
        assert sorted(calls["struct"]) == [0, 1], calls  # 파싱 OK → 구조화 대기열 → structure_one
        assert calls["cleanup"] == [], calls  # 실패 길(파싱 실패·예외)은 타지 않음
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 2건(완료 2 · 파싱실패 0 · 구조실패 0)" in log, log


def test_main_survives_errors_in_failure_path():
    """예외 처리 중 다시 예외(정리 함수 실패 — 디스크 가득 등)가 나도 작업 스레드가 죽지 않고 main()이 실패 수를 세고 끝난다(S12 리뷰 ①)."""
    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(2)]
    with tempfile.TemporaryDirectory(prefix="orca_s12_") as tmp:
        work = Path(tmp)

        def parse_one(seq, row):  # 문서 0은 파싱 실패, 문서 1은 통과
            return seq == 1, work / f"{seq}"

        def structure_one(seq, row, enq_t=None):
            raise RuntimeError("구조화 실패(시험)")

        def cleanup_doc(seq, row):
            raise OSError("정리 실패(시험 — 디스크 가득 흉내)")

        M = _run_main(work, rows, parse_one, structure_one, cleanup_doc)
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 2건(완료 0 · 파싱실패 1 · 구조실패 1)" in log, log


def test_struct_backlog_holds_new_parses():
    """중간 대기(파싱 끝·구조화 대기)가 상한이면 레인 워커가 새 파싱을 시작하지 않는다(rn-02) — pick 순간의 대기 길이 < 상한."""
    import json
    import time

    rows = [{"id": i, "s3_key": f"k{i}", "original_filename": f"doc{i}.txt", "file_size": 10} for i in range(8)]
    with tempfile.TemporaryDirectory(prefix="orca_rn02_") as tmp:
        work = Path(tmp)

        def setup(M):
            M._BACKLOG_SETTING, M.STRUCT_WORKERS = 1, 1  # 상한 1 · 구조화 1개(느림)

        def structure_one(seq, row, enq_t=None):
            time.sleep(0.3)
            return True

        M = _run_main(work, rows, lambda seq, row: (True, work / f"{seq}"), structure_one, lambda seq, row: None, setup)
        lines = [json.loads(x) for x in (M.PROG / "queue_depth.jsonl").read_text(encoding="utf-8").splitlines()]
        picks = [x for x in lines if x["event"] == "pick"]
        assert len(picks) == 8, len(picks)
        assert all(x["struct_wait"] < 1 for x in picks), [x["struct_wait"] for x in picks]
        assert max(x["struct_wait"] for x in lines) >= 1  # 실제로 쌓였다가 막힘(시험이 헛돌지 않음)
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 8건(완료 8" in log and "light 1/1 medium 1/1 vlm 1/1" in log, log


def _lanes_by_name(M):  # 분류(docker probe)를 가짜로 — 파일 이름 앞부분이 레인(rn-04)
    def classify_doc(seq, row, cache=None):
        M._class[seq] = row["original_filename"].split("_", 1)[0]
        return M._class[seq]

    M.classify_doc = classify_doc


def test_medium_vlm_lanes_and_vlm_cap():
    """medium·vlm 레인도 끝까지 돌고, vlm 문서 동시 파싱은 vlm_cap을 넘지 않는다(rn-04 — 전에는 light만 시험)."""
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

        M = _run_main(work, rows, parse_one, lambda seq, row, enq_t=None: True, lambda seq, row: None, setup)
        assert sorted(s for s, _, _ in seen) == list(range(9)), seen
        assert {M._class[s] for s, _, _ in seen} == {"light", "medium", "vlm"}, M._class
        assert peak["vlm"] <= 1, peak  # vlm_cap 1 — 전담·공유 워커가 함께 있어도
        assert any(t == "lane-medium-own" and lane == "medium" for _, lane, t in seen), seen  # medium 전담 워커가 실제로 일함
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}
        log = (M.PROG / "progress.log").read_text(encoding="utf-8")
        assert "문서별 flow 끝: 9건(완료 9" in log, log


def test_mcp_busy_yields_medium_own_worker():
    """MCP 업로드 처리 중(_mcp_pause)이면 medium 전담 워커는 새 문서를 안 뽑고, medium 문서는 공유 워커가 처리한다(10-23 양보 길 — rn-04)."""
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

        M = _run_main(work, rows, parse_one, lambda seq, row, enq_t=None: True, lambda seq, row: None, setup)
        # medium 전담 워커는 안 뽑음 — 공유 워커(어느 레인이든)가 처리(어느 공유 워커가 먼저 뜨는지는 스레드 순서라 묻지 않음)
        assert len(seen) == 4 and all(t.endswith("-shared") for t in seen), seen
        assert M._lane_inflight == {"light": 0, "medium": 0, "vlm": 0}


def test_mcp_busy_scans_recent_job_folders_only():
    """mcp_busy는 이름 날짜가 어제·오늘·내일인 작업 폴더에서 30초 안에 바뀐 파일만 본다(rn-04 — 5초마다 jobs 전체 rglob 대신)."""
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
