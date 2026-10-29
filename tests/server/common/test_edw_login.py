"""EDW 접속 하나·계정 둘(사용자 10-29, docs/prd/ops.md#op-02) — 역할별 계정 선택과 "검색 MCP는 읽기 계정만"을 고정. 실제 접속 없음."""

from unittest import mock

from common.config.settings import COMMON
from common.store import mssql
from common.store import parsing_meta_db as PM

FULL = {
    "RDB_HOST": "h",
    "RDB_DATABASE": "d",
    "RDB_READ_USER": "ru",
    "RDB_READ_PASSWORD": "rp",
    "RDB_WRITE_USER": "wu",
    "RDB_WRITE_PASSWORD": "wp",
}

# (설정, 역할) → (계정 이름, 빠진 칸)
CASES = [
    (FULL, "read", "ru", []),
    (FULL, "write", "wu", []),
    ({**FULL, "RDB_WRITE_PASSWORD": None}, "write", "wu", ["RDB_WRITE_PASSWORD"]),
    ({**FULL, "RDB_WRITE_PASSWORD": None}, "read", "ru", []),  # 쓰기 계정이 없어도 읽기는 됨(검색 MCP 서버)
    ({**FULL, "RDB_HOST": None, "RDB_READ_USER": None}, "read", None, ["RDB_HOST", "RDB_READ_USER"]),
]


def test_login_picks_account_by_role():
    for names, role, user, miss in CASES:
        with COMMON.env(**names):
            kw, got = mssql.login(role)
        assert (kw["user"], got) == (user, miss), (role, names, kw["user"], got)
        assert kw["server"] == names["RDB_HOST"] and kw["port"] == "1433"


def test_connect_kwargs_only_when_extra():
    with COMMON.env(**FULL, RDB_CONNECT_KWARGS='{"login_timeout": 5}'):
        assert mssql.login("read")[0]["login_timeout"] == 5
        assert "login_timeout" not in mssql.login("read", extra=False)[0]


def test_mcp_paths_use_read_account_only():
    """query_edw 접속과 근거 경로 조회(shaping) — 둘 다 "read"만 부른다(쓰기 계정 비밀이 MCP 프로세스로 안 감)."""
    from mcp_server.services import edw_query
    from mcp_server.services.search import shaping
    from mcp_server.services.search.server_state import _STATE

    roles = []
    real = mssql.login
    with COMMON.env(**FULL), mock.patch.object(mssql, "login", lambda role, extra=True: roles.append(role) or real(role, extra)):
        conf = edw_query._mssql_conf()
        assert conf["user"] == "ru" and conf["password"] == "rp", conf["user"]
        with mock.patch.object(PM, "MssqlStore", lambda table, role: ("store", role)):
            saved = dict(_STATE)
            _STATE.pop("_pm_db_tried", None)
            try:
                assert shaping._pm_db() == ("store", "read")
            finally:
                _STATE.clear()
                _STATE.update(saved)
    assert roles and set(roles) == {"read"}, roles


def test_publish_uses_write_and_sqlite_wins():
    with COMMON.env(**FULL), mock.patch.object(PM, "MssqlStore", lambda table, role: ("store", table, role)):
        assert PM.make_db() == ("store", "AI.ParsingMeta", "write")
    with COMMON.env(RDB_SQLITE=":memory:"):
        db = PM.make_db()
        assert isinstance(db, PM.SqliteStore)
        db.close()
