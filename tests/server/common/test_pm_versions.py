"""ParsingMeta 판·칸 이름(규칙: PRD pl-25): pipeline_version → silver_version·source_key → s3_key 이름 바꾸기 전후 모두 쓰기,
적재 때 loaded_at과 gold_version, 원문 도구의 EDW 다시 연결(한 번). 임시 SQLite만 · 외부 접속 없음."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.store import parsing_meta_db as PM
from mcp_server.services import fulltext_svc as F


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
    # 이미 gold에 있어 건너뛴 문서(kept) — gold_version이 빈 행만 채움(안 채우면 매일 밤 다시 고름), 있는 값·loaded_at은 그대로
    st = PM.SqliteStore(str(d / "pm.sqlite"))
    st.insert_new([{"source_system": "SFDC", "source_key": "SFDC/a/y.pdf", "doc_key": "k2", "pipeline_version": "0.1.0"}])
    before = st.cn.execute("SELECT loaded_at FROM ParsingMeta WHERE source_key = 'SFDC/a/x.pdf'").fetchone()[0]
    PM.mark_loaded(st, [], "0.3.0", kept=[("SFDC", "SFDC/a/x.pdf"), ("SFDC", "SFDC/a/y.pdf")])
    rows = dict(st.cn.execute("SELECT source_key, gold_version || '|' || (loaded_at IS NOT NULL) FROM ParsingMeta").fetchall())
    after = st.cn.execute("SELECT loaded_at FROM ParsingMeta WHERE source_key = 'SFDC/a/x.pdf'").fetchone()[0]
    done = st.done_source_keys()
    st.close()
    assert rows == {"SFDC/a/x.pdf": "0.2.0|1", "SFDC/a/y.pdf": "0.3.0|1"} and after == before, (rows, before, after)
    assert done == set(), done  # parse_status가 없는 행 — 끝난 문서 아님(고르기는 parse_status도 봄)


def test_done_keys():
    """끝난 문서 — gold_version 칸이 있으면 ok·partial은 gold_version도 있어야 끝, skipped_dup은 그대로 끝. 칸이 없으면 parse_status만."""
    cn = sqlite3.connect(":memory:")
    cn.execute("CREATE TABLE T (source_key, parse_status, gold_version)")
    rows = [("a", "ok", "0.2.0"), ("b", "ok", None), ("c", "partial", None), ("d", "skipped_dup", None), ("e", "not_parsed", "0.2.0")]
    cn.executemany("INSERT INTO T VALUES (?, ?, ?)", rows)
    assert PM._done_keys_rows(cn.cursor(), "T", gold=True) == {"a", "d"}
    assert PM._done_keys_rows(cn.cursor(), "T", gold=False) == {"a", "b", "c", "d"}  # DB 담당자 DDL 전


def test_done_by_sha():
    """같은 내용의 원본 = 실제로 파싱된 ok·partial 행만(gold_version 칸이 있으면 그 값도) — skipped_dup 행은 원본이 아니다(pl-02)."""
    cases = [  # (행 (sha256, 원본 키, parse_status, gold_version), gold 칸 있음, 기대)
        ([("h1", "a", "ok", "0.2.0")], True, {"h1": ("a", "ok")}),
        ([("h1", "d", "skipped_dup", None)], True, {}),  # 중복 행만 — 원본 없음
        ([("h1", "d", "skipped_dup", "0.2.0")], False, {}),
        ([("h1", "d", "skipped_dup", None), ("h1", "p", "partial", "0.2.0")], True, {"h1": ("p", "partial")}),
        ([("h1", "b", "ok", None)], True, {}),  # gold 결과 없음 — 원본으로 안 씀
        ([("h1", "b", "ok", None)], False, {"h1": ("b", "ok")}),  # DB 담당자 DDL 전 — parse_status만
        ([("h1", "e", "not_parsed", "0.2.0"), ("h2", "f", "failed", None)], False, {}),
    ]
    for rows, gold, want in cases:
        cn = sqlite3.connect(":memory:")
        cn.execute("CREATE TABLE T (sha256, source_key, parse_status, gold_version)")
        cn.executemany("INSERT INTO T VALUES (?, ?, ?, ?)", rows)
        assert PM._done_by_sha(cn.cursor(), "T", "?", ["h1", "h2"], gold=gold) == want, rows


def test_loaded_cols_alone():
    """DB 담당자가 두 칸 중 하나만 먼저 더해도 있는 칸은 쓴다(gold_version만 있을 때 UPDATE가 통째로 실패하지 않게)."""
    cases = [  # (표의 칸, 기대 (loaded_at 채움?, gold_version))
        ({"gold_version"}, (None, "0.2.0")),
        ({"loaded_at"}, (1, None)),
        ({"loaded_at", "gold_version"}, (1, "0.2.0")),
        (set(), (None, None)),  # 둘 다 없음 — 할 일 없음(예외 아님)
    ]
    for cols, want in cases:
        cn = sqlite3.connect(":memory:")
        cn.execute(f"CREATE TABLE T (parse_meta_id, {', '.join(['x', *sorted(cols)])})")
        cn.execute("INSERT INTO T (parse_meta_id) VALUES (1)")
        PM._set_loaded(cn.cursor(), "T", "?", "datetime('now')", [1], "0.2.0", cols, False)
        row = cn.execute(
            f"SELECT {'loaded_at IS NOT NULL OR NULL' if 'loaded_at' in cols else 'NULL'}, {'gold_version' if 'gold_version' in cols else 'NULL'} FROM T"
        ).fetchone()
        assert row == want, (cols, row)


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
