"""pipeline.parse_steps — 일괄 파싱(cli)과 작업 서비스가 함께 쓰는 단계 도우미: 실행 id·준비 단계·단계 실행."""

import io
import os
import tempfile
from pathlib import Path

from pipeline import parse_steps


def test_run_id_keeps_given():
    env = {"PARSE_RUN_ID": "r1"}
    assert parse_steps.run_id(env) == "r1" and env["PARSE_RUN_ID"] == "r1"
    env = {}
    assert parse_steps.run_id(env) == env["PARSE_RUN_ID"] and len(env["PARSE_RUN_ID"]) == 15  # YYYYmmdd-HHMMSS
    env = {"PARSE_RUN_ID": ""}  # 빈 값은 없는 것과 같다
    assert len(parse_steps.run_id(env)) == 15 and env["PARSE_RUN_ID"]


def test_place_inputs_writes_only_and_runs_prepare():
    calls = []
    with tempfile.TemporaryDirectory() as d:
        only = Path(d) / "only.txt"
        rc = parse_steps.place_inputs(lambda args: calls.append(args) or 7, "src", "out", ["a.pdf", "b.txt"], only)
        assert rc == 7 and only.read_text(encoding="utf-8") == "a.pdf\nb.txt\n"
    assert calls == [["pipeline.extract.filter_and_rotate", "--src", "src", "--out", "out", "--only", only]], calls


def test_run_step_logs_output():
    log = io.StringIO()
    p = parse_steps.run_step(["platform"], dict(os.environ), timeout=120, log=log)  # env 남김 — 하위 프로세스(시험)
    assert p.returncode == 0 and log.getvalue().startswith("== platform\n") and p.stdout.strip(), log.getvalue()
