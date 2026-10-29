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

ROOT = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("run_docs_flow_under_test", ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 모듈 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


def _run_main(work, rows, parse_one, structure_one, cleanup_doc):
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
        return []

    M.configure = configure
    M.code_layout_problems = lambda: []
    M.edw_list = lambda keywords: rows
    M.write_envfile = lambda: 0
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
