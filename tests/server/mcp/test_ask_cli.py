"""ask CLI(0.2.0) — 원천 하나 필수(--source, search의 source_system과 같은 이름), 오류 답은 KeyError 대신 오류 글로 끝남. SQLite 대역(실 PG 안 닿음)."""

import contextlib
import io

from mcp_server.cli import ask as A
from mcp_server.services.search.server_state import _STATE
from tests.server.mcp import pgfix


def test_ask_source():
    body = "ABX101 분석 결과 순도 99.1"
    d = pgfix.mk_bundle(
        [{"file_path": "rep.pdf", "file_name": "rep.pdf"}],
        [{"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": body, "n_terms": 5, "bbox": None, "section": None}],
    )
    _STATE.clear()
    env = pgfix.use(d)
    try:
        rows = [  # (인자, 화면에 있어야 할 글, 끝 — None = 정상)
            (["--source", "Other"], "rep.pdf", None),  # pgfix는 원천 없는 문서를 other에
            (["--source", "SFDC"], "질문:", None),  # 빈 원천 — 오류 아님, 근거 0
            (["--source", "Nope"], "", "source_system"),  # 모르는 원천 — 오류 글로 끝남(KeyError 아님)
            ([], "", "2"),  # --source 없음 — argparse 거부(종료 2)
        ]
        for extra, want_out, want_exit in rows:
            out = io.StringIO()
            got_exit = None
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    A.main(["ask", "--q", "ABX101 분석 결과", "--k", "3", *extra])
            except SystemExit as e:
                got_exit = str(e.code)
            assert want_out in out.getvalue(), (extra, out.getvalue())
            assert (got_exit is None) == (want_exit is None) and (want_exit is None or want_exit in got_exit), (extra, got_exit)
    finally:
        env.close()
        _STATE.clear()
