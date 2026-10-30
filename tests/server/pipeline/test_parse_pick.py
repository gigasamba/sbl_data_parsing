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
        return [{"names": json.dumps(r["names"]), "status": r["status"], "last_seen": r.get("last_seen")} for r in self.rows]

    def close(self):
        pass


ROWS = [
    {"names": ["ok.pdf"], "status": "parsed"},  # 앞 실행 성공 — 안 고름
    {"names": ["bad.pdf"], "status": "failed"},  # 실패 — 다시 고름
    {"names": ["seen.pdf"], "status": "seen"},  # 아직 시도 전 — 고름
]
CASES = [  # (대장 행, run_mode, 기대 — 이름 목록 또는 종료 코드)
    (ROWS, "prod", ["new.pdf", "seen.pdf", "bad.pdf"]),  # 새·시도 전 먼저, 실패는 뒤
    (ROWS, None, ["new.pdf", "seen.pdf", "bad.pdf"]),
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


def test_failed_docs_do_not_starve_new():
    """PR #49 리뷰 — 늘 실패하는 문서가 이름순으로 앞서도 --max-new 자리를 막지 않는다: 새 문서 먼저, 실패는 마지막 시도가 오래된 것부터."""
    rows = [
        {"names": ["a1.pdf"], "status": "failed", "last_seen": "2026-10-03T00:00:00Z"},
        {"names": ["a2.pdf"], "status": "failed", "last_seen": "2026-10-01T00:00:00Z"},
        {"names": ["a3.pdf"], "status": "failed", "last_seen": "2026-10-02T00:00:00Z"},
    ]
    names = ["a1.pdf", "a2.pdf", "a3.pdf", "z_new.pdf"]
    with COMMON.env(RUN_MODE="prod"), mock.patch.object(REG, "try_open_db", return_value=_FakeDB(rows)):
        pick = cli._registry_unparsed(names)
    assert pick == ["z_new.pdf", "a2.pdf", "a3.pdf", "a1.pdf"], pick
    assert pick[:2] == ["z_new.pdf", "a2.pdf"]  # max_new=2 — 새 문서가 들고 실패 중 가장 오래된 것 하나
