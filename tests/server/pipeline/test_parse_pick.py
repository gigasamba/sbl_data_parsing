"""pl-32(사용자 10-30) — 실행을 넘는 문서 고르기는 문서 대장 하나만: 파싱 성공 행(status parsed)이 있으면 안 고름, 실패·새 문서는 고름,
대장을 못 열면 run_mode prod는 종료 4(전체 재파싱 안 함)·그 밖은 받은 목록 그대로. 앞 실행 runs.jsonl은 보지 않는다. 외부 접속 없음."""

import json
from unittest import mock

from common.config.settings import COMMON
from common.store import registry as REG
from pipeline import cli


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, sql, params=None):
        assert "status = 'parsed'" in sql, sql  # 성공 행만 봄
        return [{"names": json.dumps(r["names"])} for r in self.rows if r["status"] == "parsed"]

    def close(self):
        pass


ROWS = [
    {"names": ["ok.pdf"], "status": "parsed"},  # 앞 실행 성공 — 안 고름
    {"names": ["bad.pdf"], "status": "failed"},  # 실패 — 다시 고름
    {"names": ["seen.pdf"], "status": "seen"},  # 아직 시도 전 — 고름
]
CASES = [  # (대장 행, run_mode, 기대 — 이름 목록 또는 종료 코드)
    (ROWS, "prod", ["bad.pdf", "new.pdf", "seen.pdf"]),
    (ROWS, None, ["bad.pdf", "new.pdf", "seen.pdf"]),
    (None, None, ["bad.pdf", "new.pdf", "ok.pdf", "seen.pdf"]),  # 대장 없음(PC·DOC_REGISTRY=0) — 받은 목록 그대로
    (None, "prod", 4),  # 대장 없음(서버) — 멈춤
]


def test_registry_pick():
    names = ["bad.pdf", "new.pdf", "ok.pdf", "seen.pdf"]
    for rows, mode, want in CASES:
        db = None if rows is None else _FakeDB(rows)
        with COMMON.env(RUN_MODE=mode), mock.patch.object(REG, "try_open_db", return_value=db):
            if isinstance(want, int):
                try:
                    cli._registry_unparsed(names)
                    raise AssertionError(f"대장 없음 + run_mode {mode} — 멈추지 않음")
                except SystemExit as e:
                    assert e.code == want, (mode, e.code)
                try:
                    cli._registry_new_names(cli.OUT, names)  # --source 길도 같은 규칙
                    raise AssertionError("--source 길: 대장 없음 + prod인데 멈추지 않음")
                except SystemExit as e:
                    assert e.code == want
            else:
                assert cli._registry_unparsed(names) == want, (rows is None, mode)
