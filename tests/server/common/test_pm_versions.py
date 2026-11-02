"""ParsingMeta 판·칸 이름(사용자 11-02 — PRD pl-25): pipeline_version → silver_version·source_key → s3_key 이름 바꾸기 전후 모두 쓰기,
적재 때 loaded_at과 gold_version, 원문 도구의 EDW 다시 연결(한 번). 임시 SQLite만 · 외부 접속 없음."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.store import parsing_meta_db as PM
from mcp_server.services import fulltext as F


def test_renames():
    old = set(PM.COLUMNS)
    new = (old - {"source_key", "pipeline_version"}) | {"s3_key", "silver_version"}
    cases = [  # (표의 칸, 기대)
        (old, {}),  # DB 담당자 DDL 전
        (new, {"source_key": "s3_key", "pipeline_version": "silver_version"}),  # 뒤
        (old | {"s3_key", "silver_version"}, {}),  # 둘 다 있는 중간 — 옛 칸
    ]
    for found, want in cases:
        assert PM.renames(found) == want, (found ^ old, PM.renames(found))
    cn = sqlite3.connect(":memory:")
    cn.execute(f"CREATE TABLE T ({', '.join(sorted(new))})")
    row = {"source_system": "SFDC", "source_key": "SFDC/a/x.pdf", "doc_key": "k", "pipeline_version": "0.2.0"}
    ren = PM.renames(new)
    assert PM._insert_new_rows(cn.cursor(), "T", "?", [row], sqlite3.IntegrityError, ren=ren) == (1, 0)
    assert PM._insert_new_rows(cn.cursor(), "T", "?", [row], sqlite3.IntegrityError, ren=ren) == (0, 1)  # 같은 키 — 건너뜀
    assert cn.execute("SELECT s3_key, silver_version FROM T").fetchall() == [("SFDC/a/x.pdf", "0.2.0")]


def test_gold_version():
    d = Path(tempfile.mkdtemp())
    st = PM.SqliteStore(str(d / "pm.sqlite"))
    st.insert_new([{"source_system": "SFDC", "source_key": "SFDC/a/x.pdf", "doc_key": "k", "pipeline_version": "0.1.0"}])
    PM.mark_loaded(st, [("SFDC", "SFDC/a/x.pdf")], "0.2.0")
    got = st.cn.execute("SELECT pipeline_version, gold_version, loaded_at IS NOT NULL FROM ParsingMeta").fetchone()
    st.close()
    assert got == ("0.1.0", "0.2.0", 1), got  # silver 판은 그대로, gold 판·적재 시각만


class _Db:
    def __init__(self, fail):
        self.fail = fail

    def rows_where(self, col, values):
        if self.fail:
            raise OSError("connection dropped")
        return [{"col": col}]

    def rows_parsed(self, lo, hi):
        return self.rows_where("parsed_at", [lo, hi])

    def close(self):
        pass


def test_pm_reconnect():
    cases = [  # (연결마다 실패하나, 기대 — 결과 또는 예외, 연 횟수)
        ([False], [{"col": "sha256"}], 1),
        ([True, False], [{"col": "sha256"}], 2),  # 끊김 → 한 번 다시 연결
        ([True, True], OSError, 2),  # 또 실패 — 예외(호출부가 registry_unavailable)
    ]
    for fails, want, opens in cases:
        dbs = iter([_Db(f) for f in fails])
        n = []
        with patch.object(F, "_open_pm", lambda dbs=dbs, n=n: n.append(1) or next(dbs)):
            pm = F._pm()
            try:
                got = pm.rows_where("sha256", ["x"])
            except OSError as e:
                got = type(e)
            pm.close()
        assert (got, len(n)) == (want, opens), (fails, got, len(n))
    with patch.object(F, "_open_pm", lambda: _Db(False)):  # 파싱 시각 범위 조회도 같은 길(_parsed_keys)
        assert F._pm().rows_parsed(None, None) == [{"col": "parsed_at"}]
