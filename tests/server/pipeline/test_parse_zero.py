"""F1(11-03 PC 시험) — 파싱 모듈이 돈 문서 0건(runs.jsonl 없음)이면 채점·대표 결과로 넘어가 죽지 않고 한 줄 남기고 끝남(종료 0)."""

import argparse
import contextlib
import io
import tempfile
from pathlib import Path
from unittest import mock

from pipeline import cli


def test_zero_docs():
    out = Path(tempfile.mkdtemp())
    src = out / "prepared"
    src.mkdir()
    a = argparse.Namespace(
        src=str(src), source=None, engines="plaintext", procs="1", workers="1", vlm_concurrency=1, max_new=0, deadline=None
    )
    calls = []
    buf = io.StringIO()
    with mock.patch.object(cli, "OUT", out), mock.patch.object(cli, "_run_until", lambda args, *_: calls.append(args[0]) or 0):
        with contextlib.redirect_stdout(buf):
            assert cli.parse_module(a) is None
    assert calls == ["pipeline.extract.run_all"], calls  # 채점(parse_qa)·대표 결과(represent)는 부르지 않음
    assert "이번 실행 0건" in buf.getvalue(), buf.getvalue()
