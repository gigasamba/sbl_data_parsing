"""PostgreSQL(pgvector) 연결 — 적재(modules/load)·검색(modules/search)·서비스 탐색 공통. 비밀번호는 파일·환경변수에만.
접속: PG_CONN_FILE=<KEY=VALUE 파일> 또는 PG_HOST(127.0.0.1) · PG_PORT(5432) · PG_DB(rag) · PG_USER(rag) · PG_PASSWORD · PG_SCHEMA(ai).
PG_CONNECT_TIMEOUT(기본 10초) — 공유 PG가 방화벽·주소 문제로 안 보일 때 수십 초씩 매달리지 않게(XS4).
PG_POOL_MAX(기본 8, PGPool) — 공유 PG의 max_connections 여유 안에서 잡을 것(다른 팀 서비스도 같은 PG를 씀).
10-14 함수별 분리(사용자) — connect()는 pipeline(load, 단일 연결)에서만, connect_pool()은 검색 MCP
(상주 Retriever)에서만 써서 각각 pipeline/load/pg_load_connect.py·mcp_server/services/search/pg_mcp_connect.py(옛 data_retrieval/tools/pg.py)로 옮김(로직
바이트 동일). has_conn·conf·_standin_schema·_warn_standin·PG·PGPool·vec은 두 전환점이 같이 쓰고
cli/server_checks.py 등 공통 쪽도 PG·conf를 직접 쓰므로 여기(공용)에 남는다."""

import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from common.config.settings import cfg, checked, given, guard_run_env, reveal

HNSW_MAX = 2000  # pgvector HNSW 차원 상한(vector) — 적재(색인 종류)와 검색(질의 방식)이 같은 기준


def conf():
    c = {}
    st = cfg().connections.pg  # S7b — 설정 객체(옛 os.environ.get)
    f = st.conn_file
    if f and Path(f).exists():
        for ln in Path(f).read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                c[k.strip()] = v.strip()
    # 옛 `if os.environ.get(k): c[k] = os.environ[k]` — env로 실제 준(비지 않은) 값만 파일 값을 덮음. 기본값 있는 칸(db·user)이
    # 기본값으로 덮지 않게 given()(준 값만 — 빈 값·기본값은 None). 값은 옛처럼 글자(포트도 str)
    checked("PG_PORT")  # 형식 틀린 포트는 옛처럼 실패(VS7b R-7 — 파일·기본 포트로 조용히 붙지 않게)
    for k in ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD", "PG_SCHEMA"):
        v = given(k)
        if v is not None:
            c[k] = str(reveal(v))
    c.setdefault("PG_HOST", "127.0.0.1")
    c.setdefault("PG_PORT", "5432")
    c.setdefault("PG_DB", "rag")
    c.setdefault("PG_USER", "rag")
    c.setdefault("PG_SCHEMA", "ai")
    if not c.get("PG_PASSWORD"):
        raise SystemExit("PG_PASSWORD 없음 — PG_CONN_FILE 또는 환경변수(modules/load/README.md 'PostgreSQL')")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", c["PG_SCHEMA"]):
        raise SystemExit("PG_SCHEMA는 소문자·숫자·_ 만")
    return c


def has_conn():
    """AD41 — 연결 정보가 실제로 있는지(기본값만 있는 상태는 '없음') — PG_PASSWORD 또는 PG_CONN_FILE 중 하나.
    connect()·connect_pool()의 단일 전환점: 있으면 진짜 PG, 없으면 스탠드인(sqlite, common/pg_standin.py)."""
    # PG_HOST·libpq 표준(PGPASSWORD·PGPASSFILE)도 '있음' — 비밀번호 없이 .pgpass·trust 인증 쓰는 서버가 스탠드인으로 빠지지 않게
    st = cfg().connections.pg
    return any((reveal(st.password), st.conn_file, st.host)) or any(
        os.environ.get(k) for k in ("PGPASSWORD", "PGPASSFILE")
    )  # env 남김 — 내부 신호(5-3 H): libpq 표준 변수


def _standin_schema(pg_schema=None):
    s = pg_schema or cfg().connections.pg.db_schema or "ai"
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", s):
        raise SystemExit("PG_SCHEMA는 소문자·숫자·_ 만")
    return s


def _warn_standin():
    """코디네이터 지시(10-14) — 연결 정보를 잊고 서버에 올려도 조용히 넘어가지 않게, 스탠드인을 고를 때마다
    첫 줄 WARNING(stderr). 억제 스위치 없음(의도 — 서버에서 안 보여야 할 줄이지, 숨길 일이 아님)."""
    if guard_run_env() not in (None, "local"):  # pl-12(사용자 10-30) — 서버(dev·prd·모르는 값)는 스탠드인으로 대체하지 않고 멈춤
        raise SystemExit(f"RUN_ENV={guard_run_env()} — PG 접속 정보 없음(common.connections.pg) · 서버는 로컬 대체 DB를 쓰지 않음(pl-12)")
    print(
        "WARNING: PG 접속 정보 없음 → 로컬 대체 DB(output/pg_standin) 사용 — 서버면 pipeline.env의 PG_* 확인", file=sys.stderr, flush=True
    )


class _ScopedConn:
    """GH1-14 — SET LOCAL + 그 뒤 질의를 한 연결·한 트랜잭션에 묶어서 돌린다(q()와 같은 인터페이스).
    트랜잭션이 끝나면(scope() 블록 종료 = COMMIT) SET LOCAL 효과가 자동으로 사라짐 — 다음 체크아웃·다음 요청에
    안 샘(PGPool이 매 q() 호출마다 풀에서 다른 연결을 꺼내 와 SET과 SELECT가 갈라지던 문제)."""

    def __init__(self, cn):
        self.cn = cn

    def q(self, sql, params=None):
        with self.cn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        return []


class PG:
    def __init__(self, c):
        import psycopg

        self.schema = c["PG_SCHEMA"]
        self.cn = psycopg.connect(
            host=c["PG_HOST"],
            port=int(c["PG_PORT"]),
            dbname=c["PG_DB"],
            user=c["PG_USER"],
            password=c["PG_PASSWORD"],
            autocommit=True,
            connect_timeout=cfg().connections.pg.connect_timeout,
        )

    def q(self, sql, params=None):
        with self.cn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        return []

    @contextmanager
    def scope(self):
        """GH1-14 — SET LOCAL(인덱스·ef_search 등 질의 한정 설정)과 그 뒤 질의를 한 트랜잭션으로. PG는 연결이 1개뿐이라
        q() 여러 번도 항상 같은 연결이지만, PGPool과 같은 인터페이스를 쓰게(스텁 테스트·호출부가 db 종류를 안 가림)."""
        with self.cn.transaction():
            yield _ScopedConn(self.cn)


class PGPool:
    """PG와 같은 인터페이스(schema·q) — 여러 스레드가 동시에 같은 객체를 쓸 때만(검색 MCP의 상주 Retriever.pg, S12).
    연결 1개를 공유하면 스레드끼리 같은 커서를 동시에 건드려 깨짐 — psycopg_pool로 호출마다 빈 연결을 꺼내 쓰고 돌려줌.
    한 연결을 트랜잭션으로 묶어 쓰는 쪽(modules/load/pgstore.py)은 PG를 그대로 쓴다(단일 호출자·명시적 커밋)."""

    def __init__(self, c, max_size=None):
        from psycopg_pool import ConnectionPool

        self.schema = c["PG_SCHEMA"]
        kwargs = dict(
            host=c["PG_HOST"],
            port=int(c["PG_PORT"]),
            dbname=c["PG_DB"],
            user=c["PG_USER"],
            password=c["PG_PASSWORD"],
            autocommit=True,
            connect_timeout=cfg().connections.pg.connect_timeout,
        )
        self.pool = ConnectionPool(kwargs=kwargs, min_size=1, max_size=max_size or cfg().connections.pg.pool_max, open=True)

    def q(self, sql, params=None):
        with self.pool.connection() as cn, cn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        return []

    @contextmanager
    def scope(self):
        """GH1-14 — 풀에서 연결 1개를 체크아웃해 트랜잭션 하나로 묶는다. SET LOCAL + 그 뒤 질의가 같은 연결에서 돌고,
        블록이 끝나면(COMMIT) 그 연결을 풀에 돌려주기 전에 설정이 리셋됨 — 다른 요청이 꺼내 쓸 때 안 샘."""
        with self.pool.connection() as cn, cn.transaction():
            yield _ScopedConn(cn)


def vec(v):
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"
