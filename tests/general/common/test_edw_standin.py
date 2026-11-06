"""PC 가짜 EDW sqlite 하나(규칙: docs/prd/ops.md#op-03) — 같은 파일로 원천 조회·query_edw가 읽기 전용으로 돈다(이 프로젝트는 EDW에 쓰지 않음 — op-17).
valid_env/edw/*.sql이 필요해 PC 전용(tests/general). 실제 접속 없음."""

import tempfile
from pathlib import Path

from common.config.settings import COMMON
from common.store import mssql
from validation.e2e.edw_standin import build


def _standin(d):
    p = Path(d) / "edw.sqlite"
    tables = build(p)
    assert {"FileStorageMap", "RM_MAS_CLIENT", "Account"} <= set(tables), tables
    return p


def test_every_schema_name_resolves_read_only():
    with tempfile.TemporaryDirectory() as d:
        cn = mssql.standin(_standin(d))
        try:
            for t in ("AI.FileStorageMap", "[CRMS].[RM_MAS_CLIENT]", "LAS.PROD_MAS", "SFDC.Account"):
                assert cn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] >= 0, t
            try:
                cn.execute("DELETE FROM AI.FileStorageMap")
                raise AssertionError("read-only stand-in accepted a write")
            except Exception as e:  # sqlite3.OperationalError: attempt to write a readonly database
                assert "readonly" in str(e), e
        finally:
            cn.close()


def test_query_reads_same_file_unchanged():
    """query_edw와 원천 조회가 같은 대역 파일을 읽는다 — 파일 바이트는 그대로(표·색인을 만들지 않음)."""
    import hashlib

    from mcp_server.services import edw_query

    with tempfile.TemporaryDirectory() as d:
        p = _standin(d)
        h = hashlib.sha256(p.read_bytes()).hexdigest()
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
        assert hashlib.sha256(p.read_bytes()).hexdigest() == h
