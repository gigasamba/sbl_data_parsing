"""PC 가짜 EDW sqlite 하나(사용자 10-29 — docs/prd/ops.md#op-03) — 같은 파일로 원천 조회(읽기)·query_edw(읽기 전용)·ParsingMeta 게시(쓰기)가
모두 돈다. valid_env/edw/*.sql이 필요해 PC 전용(tests/general). 실제 접속 없음."""

import tempfile
from pathlib import Path

from common.config.settings import COMMON
from common.store import mssql
from common.store import parsing_meta_db as PM
from validation.e2e.edw_standin import build


def _standin(d):
    p = Path(d) / "edw.sqlite"
    tables = build(p)
    assert {"FileStorageMap", "ParsingMeta", "RM_MAS_CLIENT", "Account"} <= set(tables), tables
    return p


def test_every_schema_name_resolves_read_only():
    with tempfile.TemporaryDirectory() as d:
        cn = mssql.standin(_standin(d))
        try:
            for t in ("AI.FileStorageMap", "[CRMS].[RM_MAS_CLIENT]", "LAS.PROD_MAS", "SFDC.Account"):
                assert cn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] >= 0, t
            try:
                cn.execute("DELETE FROM AI.ParsingMeta")
                raise AssertionError("read-only stand-in accepted a write")
            except Exception as e:  # sqlite3.OperationalError: attempt to write a readonly database
                assert "readonly" in str(e), e
        finally:
            cn.close()


def test_query_and_publish_share_one_file():
    """(11-01 — 파싱 입구의 표 직접 질의 _mssql_rows는 rdb:* 길과 함께 지움 — 읽기는 대역 파일을 바로 셈.)"""
    from mcp_server.services import edw_query

    with tempfile.TemporaryDirectory() as d:
        p = _standin(d)
        with COMMON.env(RDB_SQLITE=str(p)):
            cn = mssql.standin(p)
            try:
                n = cn.execute("SELECT COUNT(*) FROM AI.FileStorageMap").fetchone()[0]
            finally:
                cn.close()
            assert n > 0, n
            assert edw_query.backend() == ("sqlite", str(p))
            res = edw_query.query("SELECT COUNT(*) AS n FROM AI.FileStorageMap")
            assert res["ok"] and res["rows"][0][0] == n, res
            db = PM.make_db("write")
            try:
                assert isinstance(db, PM.SqliteStore)
                before = db.count()
                db.insert_new([{"doc_key": "k1", "source_system": "SFDC", "source_key": "s1", "parse_date": "2026-10-29_000000"}])
                assert db.count() == before + 1
            finally:
                db.close()


def test_read_role_never_changes_the_file():
    """검색 MCP 조회(role "read")는 대역 파일을 ?mode=ro로 열고 표·색인을 만들지 않음 — 파일 바이트 그대로."""
    import hashlib

    with tempfile.TemporaryDirectory() as d:
        p = _standin(d)
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        with COMMON.env(RDB_SQLITE=str(p)):
            db = PM.make_db("read")
            try:
                assert db.find_by_doc_key("none") in (None, [], ())
            finally:
                db.close()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == h
