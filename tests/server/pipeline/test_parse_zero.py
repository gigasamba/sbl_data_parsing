"""F1(11-03 PC 시험) — run_all 뒤 runs.jsonl이 없을 때: run_all이 0으로 끝났으면(돈 문서 0건) 한 줄 남기고 종료 0,
run_all이 죽었으면(종료 코드 ≠ 0) 성공으로 덮지 않고 그 코드로 멈춘다(리뷰). 어느 쪽이든 채점·대표 결과는 부르지 않는다."""

import argparse
import contextlib
import io
import tempfile
from pathlib import Path
from unittest import mock

from pipeline import cli


def test_zero_docs():
    cases = [  # (run_all 종료 코드, 기대 — None = 정상 끝 또는 SystemExit 코드, 출력에 든 말)
        (0, None, "이번 실행 0건"),
        (3, 3, "run_all 종료 3"),
    ]
    for rc, want, says in cases:
        out = Path(tempfile.mkdtemp())
        src = out / "prepared"
        src.mkdir()
        a = argparse.Namespace(
            src=str(src), source=None, engines="plaintext", procs="1", workers="1", vlm_concurrency=1, max_new=0, deadline=None
        )
        calls = []
        buf = io.StringIO()
        with (
            mock.patch.object(cli, "OUT", out),
            mock.patch.object(cli, "_run_until", lambda args, *_, rc=rc, calls=calls: calls.append(args[0]) or rc),
        ):
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    got = cli.parse_module(a)
                except SystemExit as e:
                    got = e.code
        assert got == want and says in buf.getvalue(), (rc, got, buf.getvalue())
        assert calls == ["pipeline.extract.run_all"], calls  # 채점(parse_qa)·대표 결과(represent)는 부르지 않음
