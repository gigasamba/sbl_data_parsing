"""EDW 접속 하나·계정 둘(규칙: docs/prd/ops.md#op-03) — 역할별 계정 선택과 "검색 MCP는 읽기 계정만"을 고정. 실제 접속 없음."""

import contextlib
import io
from unittest import mock

from common.config import settings as S
from common.config.settings import COMMON
from common.core.paths import PROJ_ROOT
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
    ({**FULL, "RDB_WRITE_USER": None, "RDB_WRITE_PASSWORD": None}, "write", "ru", []),  # 쓰기 계정을 둘 다 비우면 읽기 계정(op-03)
    ({**FULL, "RDB_HOST": None, "RDB_READ_USER": None}, "read", None, ["RDB_HOST", "RDB_READ_USER"]),
]


def test_login_picks_account_by_role():
    for names, role, user, miss in CASES:
        with COMMON.env(**names):
            kw, got = mssql.login(role)
        assert (kw["user"], got) == (user, miss), (role, names, kw["user"], got)
        assert kw["server"] == names["RDB_HOST"] and kw["port"] == "1433"


def test_connect_kwargs_only_when_extra():
    with COMMON.env(**FULL, RDB_CONNECT_KWARGS='{"login_timeout": 5, "user": "wu", "password": "wp"}'):
        kw = mssql.login("read")[0]
        assert kw["login_timeout"] == 5 and (kw["user"], kw["password"]) == ("ru", "rp")  # 추가 인자가 계정을 못 바꿈
        assert "login_timeout" not in mssql.login("read", extra=False)[0]


def test_standin_refused_off_pc():
    with COMMON.env(RDB_SQLITE="x.sqlite", RUN_ENV="dev"):
        try:
            mssql.standin_path()
            raise AssertionError("stand-in accepted on a server RUN_ENV")
        except ValueError:
            pass
    with COMMON.env(RDB_SQLITE="x.sqlite", RUN_ENV="local"):
        assert mssql.standin_path() == (PROJ_ROOT / "x.sqlite").as_posix()  # 상대 경로는 저장소 루트 기준


def test_mcp_process_never_holds_write_account():
    """edw_read_only()(검색 MCP 시작) 뒤에는 공용 설정에 쓰기 계정이 있어도 설정 객체가 비어 있음 — 쓰기 접속도 빠진 칸으로 거부."""
    from common.config import settings as S

    S.edw_read_only()  # MCP 시작 때처럼 설정을 읽기 전에
    try:
        with COMMON.env(**FULL):
            w = S.cfg().connections.rdb.write
            assert w.user is None and w.password is None, "write account visible in a read-only process"
            assert mssql.login("read")[1] == []
            assert mssql.login("write")[1] == ["RDB_WRITE_USER", "RDB_WRITE_PASSWORD"]
    finally:
        S.edw_read_only(False)
    with COMMON.env(**FULL):
        assert S.cfg().connections.rdb.write.user == "wu"


def test_unknown_role_refused():
    for bad in ("Read", "ro", "", None):
        try:
            mssql.login(bad)
            raise AssertionError(f"role {bad!r} accepted")
        except ValueError:
            pass


def test_mcp_paths_use_read_account_only():
    """query_edw 접속과 ParsingMeta 조회 — 둘 다 "read"만 부른다(쓰기 계정 비밀이 MCP 프로세스로 안 감)."""
    from mcp_server.services import edw_query

    roles = []
    real = mssql.login
    with COMMON.env(**FULL), mock.patch.object(mssql, "login", lambda role, extra=True: roles.append(role) or real(role, extra)):
        conf = edw_query._mssql_conf()
        assert conf["user"] == "ru" and conf["password"] == "rp", conf["user"]
    assert roles and set(roles) == {"read"}, roles


def test_publish_uses_write_and_sqlite_wins():
    with (
        COMMON.env(**FULL, RUN_ENV="dev"),
        mock.patch.object(PM, "MssqlStore", lambda table, role: ("store", table, role)),
    ):  # local은 늘 가짜 EDW(op-14)
        assert PM.make_db("write") == ("store", "AI.ParsingMeta", "write")
    with COMMON.env(RDB_SQLITE=":memory:", RUN_ENV="local"):  # 가짜 EDW는 local 전용 — 이미지에서도 시험 안에서만
        db = PM.make_db("write")
        assert isinstance(db, PM.SqliteStore)
        db.close()


def test_write_fallback_warns_on_server():
    """쓰기 계정을 비워 읽기 계정으로 쓸 때 — 서버(dev·prd)는 경고 한 줄(값 없음), local은 조용히(op-03)."""
    no_write = {**FULL, "RDB_WRITE_USER": None, "RDB_WRITE_PASSWORD": None}
    # (run_env, 경고?)
    for run, warned in (("dev", True), ("prd", True), ("local", False)):
        err = io.StringIO()
        with mock.patch.object(S, "_warned", set()), COMMON.env(**no_write, RUN_ENV=run), contextlib.redirect_stderr(err):
            assert mssql.login("write")[0]["user"] == "ru"
        out = err.getvalue()
        assert ("읽기 계정으로" in out) == warned and len(out.splitlines()) == int(warned), (run, out)
        assert "rp" not in out, out  # 계정 값은 안 찍음
