"""회사 DB(SQL Server — EDW·RDB) 연결 — SQLAlchemy `mssql+pymssql`. 우리 소유가 아니라 DDL·
Alembic 없음(DDL은 EDW 담당 — docs/operations/parsing_meta_mssql.sql).
· 연결 인자는 지금 pymssql.connect 그대로(creator) — 연결 풀 없음(NullPool — 지금처럼 쓰고 닫음). 비밀은 설정 객체에서 받아 넘기기만.
· session_sql(parsing_meta의 세션 옵션 7개)은 그 엔진의 연결마다 **첫 실행문**(creator 안 — 방언의 첫 연결 카탈로그 질의보다 먼저, 지금처럼 commit).
· 엔진은 접속 인자마다 하나(캐시) — 방언이 첫 연결 때 카탈로그 질의 6개(@@version·schema_name()·sys.system_views·격리 수준·NVARCHAR(max)·
  fn_listextendedproperty)를 한 번만 낸다. 권한이 없어 격리 수준 질의가 실패해도 방언이 넘어간다(서버 계정 확인 — refactor.md C-49).
· 질의: rows(conn, sql, params) — SQL 글자·%s 자리 그대로(exec_driver_sql). DBAPI 커서를 그대로 쓰는 곳(여러 결과 집합 · SQLite 대역과 같은
  코드 · executemany)은 raw()로 SQLAlchemy가 연 DBAPI 연결을 받는다.
· 경계: 이 파일은 common/store/db(pgvector 판 관리)를 import하지 않는다 — 여러 층이 import해서(공용 의존)."""

import hashlib

_ENGINES: dict = {}


def _key(session_sql, kw):
    return hashlib.sha256(repr((session_sql, sorted((k, repr(v)) for k, v in kw.items()))).encode("utf-8")).hexdigest()  # 비밀은 해시로만


def engine(session_sql=None, **connect_kw):
    """접속 인자(pymssql.connect 그대로)마다 엔진 하나."""
    k = _key(session_sql, connect_kw)
    if k not in _ENGINES:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        def creator():
            import pymssql  # 호출 때 찾음(시험이 pymssql.connect를 바꿔 끼울 수 있게)

            cn = pymssql.connect(**connect_kw)
            if session_sql:
                cn.cursor().execute(session_sql)  # 이 세션의 첫 실행문(필터 유일 색인 표 쓰기 조건 — parsing_meta_db)
                cn.commit()
            return cn

        _ENGINES[k] = create_engine("mssql+pymssql://", creator=creator, poolclass=NullPool)
    return _ENGINES[k]


def connect(session_sql=None, **connect_kw):
    """SQLAlchemy 연결(Connection) — with 문으로 닫음."""
    return engine(session_sql, **connect_kw).connect()


def raw(session_sql=None, **connect_kw):
    """SQLAlchemy가 연 DBAPI 연결(cursor·commit·rollback·close — 지금 pymssql 연결 자리 그대로)."""
    return engine(session_sql, **connect_kw).raw_connection()


def rows(conn, sql, params=()):
    """질의 → dict 행 목록(지금 pymssql cursor(as_dict=True)·fetchall 자리). params는 %s 자리 순서대로."""
    res = conn.exec_driver_sql(sql, tuple(params)) if params else conn.exec_driver_sql(sql)
    return [dict(r) for r in res.mappings().all()]


def clear():
    """엔진 캐시 비움(시험)."""
    _ENGINES.clear()


def login(role, extra=True):
    """EDW 접속 인자(pymssql.connect 그대로)와 빠진 칸 이름 목록 — common.connections.rdb의 서버·DB + role 계정
    ("read" | "write" — docs/prd/ops.md#op-03). extra=False면 connect_kwargs를 안 넘김(gen_roster).
    형식 틀린 포트는 연결 전에 실패(checked — 1433으로 조용히 붙지 않게). 값은 출력하지 않는다.
    role은 둘 중 하나만(오타가 쓰기 계정으로 새지 않게) · connect_kwargs는 계정·서버 칸을 덮지 못함."""
    import json

    from common.config.settings import cfg, checked, reveal

    if role not in ("read", "write"):
        raise ValueError(f"EDW 계정 역할은 read·write만 — {role!r}")
    c = cfg().connections.rdb
    acct = c.read if role == "read" else c.write
    checked("RDB_PORT")
    kw = {
        "server": c.host,
        "port": str(c.port),  # 포트는 글자로(pymssql)
        "user": acct.user,
        "password": reveal(acct.password),
        "database": c.database,
    }
    names = {
        "server": "RDB_HOST",
        "database": "RDB_DATABASE",
        "user": f"RDB_{role.upper()}_USER",
        "password": f"RDB_{role.upper()}_PASSWORD",
    }
    miss = [names[k] for k in names if not kw[k]]
    if extra:
        kw = {**json.loads(reveal(c.connect_kwargs) or "{}"), **kw}  # 추가 인자가 계정·서버를 덮지 못함
    return kw, miss


def rdb_connect(extra_kwargs=True):
    """RDB(mssql) 연결 — SQLAlchemy `mssql+pymssql`(연결 풀 없음). 접속은 common.connections.rdb의
    **읽기 계정** + RDB_CONNECT_KWARGS(JSON — extra_kwargs=False면 안 넘김).
    discover_columns·roster_from_edw가 쓴다."""
    kw, miss = login("read", extra=extra_kwargs)
    if miss:  # 없으면 KeyError(parsing_meta_db와 같은 꼴)
        raise KeyError(miss[0])
    return connect(**kw)


def standin_path():
    """PC 가짜 EDW 경로(common.connections.rdb.sqlite) — RUN_ENV=local 전용. 서버 설정에 남아 있으면 실패한다
    (원천 조회·게시·query_edw가 한꺼번에 가짜 파일로 가지 않게). 없으면 None."""
    from common.config.settings import cfg, guard_run_env

    p = cfg().connections.rdb.sqlite
    if p and guard_run_env() != "local":
        raise ValueError("common.connections.rdb.sqlite(RDB_SQLITE)는 PC(RUN_ENV=local) 전용 — 서버 설정에서 지울 것")
    return p


STANDIN_SCHEMAS = ("AI", "CRMS", "LAS", "SFDC")  # PC 가짜 EDW sqlite 하나에 든 스키마(valid_env/edw/*.sql — validation/e2e/edw_standin.py)


def standin(path, readonly=True, timeout=5.0):
    """PC 가짜 EDW(common.connections.rdb.sqlite — 파일 하나에 모든 표) 연결 — 같은 파일을 스키마 이름마다 ATTACH해
    `AI.FileStorageMap`·`CRMS.RM_MAS_CLIENT` 같은 T-SQL 이름이 그대로 돈다(ops.md#op-03).
    readonly면 SQLite `?mode=ro`(드라이버 수준 — ATTACH도 같은 URI라 쓰기 불가)."""
    import sqlite3
    from pathlib import Path

    uri = f"file:{Path(path).resolve().as_posix()}" + ("?mode=ro" if readonly else "")
    cn = sqlite3.connect(uri, uri=True, timeout=timeout)
    for s in STANDIN_SCHEMAS:
        cn.execute(f"ATTACH DATABASE ? AS {s}", (uri,))
    return cn
