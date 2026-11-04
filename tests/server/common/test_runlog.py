"""op-13 규칙 7 — 실행 묶음(session·note)은 파일을 쓰지 않는다(옛 output/RUNLOG.md·runlog.jsonl·logs/<시각>_<도구>.log 없음 — 로그는 applog만).
묶음 안에서 파일 열기를 막아도 끝까지 돌고, 오류는 그대로 올라온다."""

import io
from unittest.mock import patch

from common.core import runlog


def _no_file(*a, **k):
    raise AssertionError(f"파일을 열면 안 됨: {a[:1]}")


def test_session_writes_nothing():
    with patch("builtins.open", _no_file), patch("pathlib.Path.open", _no_file), patch("pathlib.Path.mkdir", _no_file):
        with runlog.session("demo"):
            print("작업 출력 1줄", file=io.StringIO())
            runlog.note("핵심: 성공 3")
        assert runlog._state["notes"] == ["핵심: 성공 3"]
        try:
            with runlog.session("demo_fail"):
                raise ValueError("일부러")
        except ValueError:
            pass
        else:
            raise AssertionError("오류가 삼켜짐")
    assert runlog._state["notes"] == [] and not hasattr(runlog, "OUT"), runlog._state
