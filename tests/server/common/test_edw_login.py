"""EDW 접속 하나·읽기 계정(규칙: docs/prd/ops.md#op-03·op-17 — EDW에 쓰지 않음) — 계정·빠진 칸·추가 인자, query_edw도 같은 길. 실제 접속 없음."""

from unittest import mock

from common.config.settings import COMMON
from common.core.paths import PROJ_ROOT
from common.store import mssql

FULL = {"RDB_HOST": "h", "RDB_DATABASE": "d", "RDB_READ_USER": "ru", "RDB_READ_PASSWORD": "rp"}

# (설정) → (계정 이름, 빠진 칸)
CASES = [
    (FULL, "ru", []),
    ({**FULL, "RDB_READ_PASSWORD": None}, "ru", ["RDB_READ_PASSWORD"]),
    ({**FULL, "RDB_HOST": None, "RDB_READ_USER": None}, None, ["RDB_HOST", "RDB_READ_USER"]),
]


def test_login_read_account():
    for names, user, miss in CASES:
        with COMMON.env(**names):
            kw, got = mssql.login()
        assert (kw["user"], got) == (user, miss), (names, kw["user"], got)
        assert kw["server"] == names["RDB_HOST"] and kw["port"] == "1433"


def test_connect_kwargs_only_when_extra():
    with COMMON.env(**FULL, RDB_CONNECT_KWARGS='{"login_timeout": 5, "user": "wu", "password": "wp"}'):
        kw = mssql.login()[0]
        assert kw["login_timeout"] == 5 and (kw["user"], kw["password"]) == ("ru", "rp")  # 추가 인자가 계정을 못 바꿈
        assert "login_timeout" not in mssql.login(extra=False)[0]


def test_standin_refused_off_pc():
    with COMMON.env(RDB_SQLITE="x.sqlite", RUN_ENV="dev"):
        try:
            mssql.standin_path()
            raise AssertionError("stand-in accepted on a server RUN_ENV")
        except ValueError:
            pass
    with COMMON.env(RDB_SQLITE="x.sqlite", RUN_ENV="local"):
        assert mssql.standin_path() == (PROJ_ROOT / "x.sqlite").as_posix()  # 상대 경로는 저장소 루트 기준


def test_query_edw_uses_login():
    """query_edw 접속도 같은 login()(읽기 계정)."""
    from mcp_server.services import edw_query

    calls = []
    real = mssql.login
    with COMMON.env(**FULL), mock.patch.object(mssql, "login", lambda extra=True: calls.append(1) or real(extra)):
        conf = edw_query._mssql_conf()
        assert conf["user"] == "ru" and conf["password"] == "rp", conf["user"]
    assert calls
