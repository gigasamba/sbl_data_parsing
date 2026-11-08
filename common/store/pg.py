"""PostgreSQL(pgvector) 연결 — 적재·검색·서비스 탐색 공통. 비밀번호는 settings.yaml에만.
접속: PG_HOST · PG_PORT · PG_DB · PG_USER · PG_PASSWORD — 모두 필수, 코드 기본값 없음 · PG_SCHEMA는 비우면 data_parsing.
PG_CONNECT_TIMEOUT(기본 10초) — 공유 PG가 방화벽·주소 문제로 안 보일 때 수십 초씩 매달리지 않게.
PG_POOL_MAX(기본 8, PGPool) — 공유 PG의 max_connections 여유 안에서 잡을 것(다른 팀 서비스도 같은 PG를 씀).
PGPool(statement_timeout_sec — 부르는 쪽이 줌: 검색 MCP는 mcp.server.pg_statement_timeout_sec 25초, 0 = 없음) — 질의 하나가 넘으면 DB가 멈춤(QueryCanceled → 도구는 timeout).
PG는 적재(pipeline/load/pgvector_load.py — 단일 연결), PGPool은 검색 MCP(mcp_server/services/search/server_state.py
connect_sources() — 상주 Retriever)가 쓴다. 접속 정보가 없으면 conf()가 채울 자리를 적고 멈춘다(로컬 대체 DB 없음 — PC도 pgvector).
conf·PG·PGPool·vec은 두 쪽이 같이 쓰고
점검 도구도 PG·conf를 직접 쓰므로 여기(공용)에 둔다."""

import re
from contextlib import contextmanager

from common.config.settings import cfg, checked, given, guard_run_env, reveal

_PG_KEYS = {"PG_HOST": "host", "PG_PORT": "port", "PG_DB": "db", "PG_USER": "user", "PG_PASSWORD": "password", "PG_SCHEMA": "db_schema"}
HNSW_MAX = 2000  # pgvector HNSW 차원 상한(vector) — 적재(색인 종류)와 검색(질의 방식)이 같은 기준


def conf():
    c = {}
    # 준(비지 않은) 값만 — given()(빈 값·기본값은 None). 값은 글자(포트도 str)
    checked("PG_PORT")  # 형식 틀린 포트는 실패(기본 포트로 조용히 붙지 않게)
    for k in _PG_KEYS:
        v = given(k)
        if v is not None:
            c[k] = str(reveal(v))
    c["PG_SCHEMA"] = cfg().connections.pg.db_schema or ""  # 코드 기본값 data_parsing(벌마다 스키마를 나누지 않음)
    missing = [k for k in _PG_KEYS if not c.get(k)]  # 코드 기본값(127.0.0.1·5432 등) 없음, 빈 칸이면 거부
    if missing:
        from common.config.layout import to_yaml

        where = ", ".join(to_yaml(f"common.connections.pg.{_PG_KEYS[k]}") for k in missing)
        raise SystemExit(f"PG 접속 정보 없음 — settings.yaml {where}를 채움")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", c["PG_SCHEMA"]):
        raise SystemExit("PG_SCHEMA는 소문자·숫자·_ 만")
    if given("PG_SCHEMA") is None and guard_run_env() != "local":  # 서버가 스키마를 안 적음 — 어느 스키마에 쓰는지 알림
        from common.config.layout import to_yaml
        from common.config.settings import _warn_once

        _warn_once(f"[pg] {to_yaml('common.connections.pg.db_schema')}가 비어 기본 스키마 {c['PG_SCHEMA']}를 씀")
    return c


class _ScopedConn:
    """SET LOCAL + 그 뒤 질의를 한 연결·한 트랜잭션에 묶어서 돌린다(q()와 같은 인터페이스).
    트랜잭션이 끝나면(scope() 블록 종료 = COMMIT) SET LOCAL 효과가 자동으로 사라짐 — 다음 체크아웃·다음 요청에
    안 샘(PGPool.q()는 호출마다 풀에서 다른 연결을 꺼내므로 따로 부르면 SET과 SELECT가 갈라짐)."""

    def __init__(self, cn):
        self.cn = cn

    def q(self, sql, params=None):
        with self.cn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        return []


class PG(_ScopedConn):
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

    @contextmanager
    def scope(self):
        """SET LOCAL(인덱스·ef_search 등 질의 한정 설정)과 그 뒤 질의를 한 트랜잭션으로. PG는 연결이 1개뿐이라
        q() 여러 번도 항상 같은 연결이지만, PGPool과 같은 인터페이스를 쓰게(스텁 테스트·호출부가 db 종류를 안 가림)."""
        with self.cn.transaction():
            yield _ScopedConn(self.cn)


class PGPool:
    """PG와 같은 인터페이스(schema·q) — 여러 스레드가 동시에 같은 객체를 쓸 때만(검색 MCP의 상주 Retriever.pg).
    연결 1개를 공유하면 스레드끼리 같은 커서를 동시에 건드려 깨짐 — psycopg_pool로 호출마다 빈 연결을 꺼내 쓰고 돌려줌.
    한 연결을 트랜잭션으로 묶어 쓰는 쪽(적재)은 PG를 그대로 쓴다(단일 호출자·명시적 커밋).
    꺼낼 때 연결을 확인해(check) 끊긴 연결은 새 연결로 바꾼다 — 재시도는 이 한 번뿐(그래도 실패하면 도구가 db_unavailable)."""

    def __init__(self, c, max_size=None, statement_timeout_sec=0):
        from psycopg_pool import ConnectionPool

        self.schema = c["PG_SCHEMA"]
        st = cfg().connections.pg
        kwargs = dict(
            host=c["PG_HOST"],
            port=int(c["PG_PORT"]),
            dbname=c["PG_DB"],
            user=c["PG_USER"],
            password=c["PG_PASSWORD"],
            autocommit=True,
            connect_timeout=st.connect_timeout,
        )
        if statement_timeout_sec:  # 0·비움 = 제한 없음
            kwargs["options"] = f"-c statement_timeout={int(statement_timeout_sec) * 1000}"
        self.pool = ConnectionPool(
            kwargs=kwargs, min_size=1, max_size=max_size or st.pool_max, open=True, check=ConnectionPool.check_connection
        )

    def q(self, sql, params=None):
        with self.pool.connection() as cn, cn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        return []

    @contextmanager
    def scope(self):
        """풀에서 연결 1개를 체크아웃해 트랜잭션 하나로 묶는다. SET LOCAL + 그 뒤 질의가 같은 연결에서 돌고,
        블록이 끝나면(COMMIT) 그 연결을 풀에 돌려주기 전에 설정이 리셋됨 — 다른 요청이 꺼내 쓸 때 안 샘."""
        with self.pool.connection() as cn, cn.transaction():
            yield _ScopedConn(cn)


def vec(v):
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


# 연결 고르기(점검 표는 common.check.checker)
def _pg_capable(c):
    """이름이 아니라 붙어서 능력 확인: SELECT 1 + vector 확장 존재 + PG_SCHEMA 접근 가능(있음 또는 만들 권한).
    → (ok, 설명). 비밀값은 반환·로그에 내지 않는다."""
    db = PG(c)
    db.q("SELECT 1")
    if not db.q("SELECT 1 FROM pg_extension WHERE extname='vector'"):
        return False, "vector 확장 없음"
    if not db.q("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (c["PG_SCHEMA"],)):
        priv = db.q("SELECT has_database_privilege(current_user, current_database(), 'CREATE') p")
        if not (priv and priv[0].get("p")):
            return False, f"스키마 {c['PG_SCHEMA']} 없음·만들 권한 없음"
    return True, "능력 확인됨"


def detect_pg():
    """설정의 PG에 붙어 능력 확인 → (ok, 설명). 접속 칸이 비면 pg.conf()가 거부(SystemExit — 채울 자리를 적음)."""
    c = conf()
    try:
        ok, why = _pg_capable(c)  # 이름이 아니라 붙어서 확인(vector 확장·스키마)
    except Exception as e:
        return False, f"{c['PG_HOST']}:{c['PG_PORT']}: 접속 실패({type(e).__name__})"
    return ok, f"{c['PG_HOST']}:{c['PG_PORT']}" + ("" if ok else f": {why}")
