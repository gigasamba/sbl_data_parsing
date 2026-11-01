#!/usr/bin/env python3
"""AD41 — PG(pgvector) 스탠드인(연결 정보 없을 때만, common/pg.connect()·connect_pool()가 단일 전환점으로 씀).
Docker·새 패키지 없이 sqlite3(표준 라이브러리)만으로 load/pgstore.py·search/pgsearch.py가 실제로 내는 SQL을
스키마 하나당 파일 하나(PG_STANDIN_DIR, 기본 output/pg_standin/<schema>.sqlite)로 돌린다 — 여러 프로세스(cli/index.py가
deploy·load를 따로 띄우는 subprocess들)가 같은 파일을 보게.

ponytail: pgvector 전용(HNSW·이진 양자화·<~>)·BM25(unnest CTE)·그래프 중간 노드는 흉내 안 낸다(여기까지 하면 PG를
새로 만드는 것) — vector(코사인, 전체 스캔으로 파이썬에서 계산)·순수 SQL(ANY→IN 번역)만 지원. 서버는 PG_PASSWORD
또는 PG_CONN_FILE을 pipeline.env에 채우면 코드 변경 없이 이 파일을 거치지 않고 진짜 PG로 전환된다(common/pg.py
has_conn() 단일 분기). bm25·그래프·집계가 필요한 검증은 실 PG에서(이 스탠드인의 한계 — 업그레이드 경로).
"""

import datetime
import math
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from common.config.settings import cfg
from common.core.paths import APP_ROOT

_UNNEST_RE = re.compile(r"unnest\(%s::text\[\], %s::float8\[\]\) AS w\(term, weight\)")
_CAST_RE = re.compile(r"%s::\w+(\[\])?(\(\d+\))?")
_ANY_OR_PH = re.compile(r"(\S+)\s*=\s*ANY\(%s\)|%s")
_SELECT_ONCONFLICT_RE = re.compile(r"(\bFROM\s+\w+)(\s+ON CONFLICT)")
_UPDATE_ALIAS_RE = re.compile(
    r"(UPDATE\s+\w+)\s+(?!AS\b|SET\b)(\w+)\s+SET", re.IGNORECASE
)  # PG는 UPDATE t alias SET(AS 생략 허용) — SQLite는 AS 필수
_SERIAL_RE = re.compile(r"\bBIGSERIAL\b|\bSERIAL\b", re.IGNORECASE)
_DEFAULT_NOW_RE = re.compile(r"DEFAULT\s+now\(\)", re.IGNORECASE)
_ALTER_IFNE_RE = re.compile(r"(ALTER TABLE\s+\S+\s+ADD COLUMN)\s+IF NOT EXISTS\s+", re.IGNORECASE)
_VIEW_RE = re.compile(r"CREATE OR REPLACE VIEW\s+(\S+)\s+AS\s*(.*)", re.IGNORECASE | re.DOTALL)
_COPY_RE = re.compile(r"COPY\s+(\S+?)\((.+?)\)\s+FROM STDIN", re.IGNORECASE)


def standin_dir():
    return Path(cfg().connections.pg.standin_dir or (APP_ROOT / "output" / "pg_standin"))  # S7b — 설정 객체


def _now_iso():
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_vec(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    v = v.strip()
    return [float(x) for x in v.strip("[]").split(",")] if v else None


def _cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db_ = sum(y * y for y in b) ** 0.5
    return num / (da * db_) if da and db_ else 0.0


def _xlat(sql, params, schema):
    """%s→? · X = ANY(%s)→X IN (...) · %s::TYPE 캐스트 제거 · unnest(...) 2-배열 CTE→제거(한 곳, X4-BM25는 스탠드인
    미지원이라 호출 전에 걸러짐) — 한 번에(파라미터 위치가 꼬이지 않게, enforcement §2 — 번역은 이 함수 하나)."""
    sql = sql.replace(f"{schema}.", "")
    sql = _SELECT_ONCONFLICT_RE.sub(r"\1 WHERE 1=1\2", sql)  # SQLite upsert 파싱 모호성(SELECT 기반 INSERT 뒤 ON CONFLICT)
    sql = _UPDATE_ALIAS_RE.sub(r"\1 AS \2 SET", sql)  # UPDATE t alias SET(AS 생략, PG 허용) → SQLite는 AS 필수
    params = list(params or ())
    prefix = []
    um = _UNNEST_RE.search(sql)
    if um:
        terms, weights = params[0], params[1]
        vsql = ",".join("(?,?)" for _ in terms) or "(NULL,NULL)"
        sql = (
            sql[: um.start()] + f"(SELECT column1 AS term, column2 AS weight FROM (VALUES {vsql})) AS w" + sql[um.end() :]
        )  # SQLite는 AS w(칸 별칭) 꼴이 없음(mc-01)
        for t, w in zip(terms, weights):
            prefix += [t, w]
        params = params[2:]
    sql = _CAST_RE.sub("%s", sql)
    out, new_params, pi, i = [], [], 0, 0
    for m in _ANY_OR_PH.finditer(sql):
        out.append(sql[i : m.start()])
        val = params[pi]
        pi += 1
        if m.group(1):
            vals = list(val) if val else []
            if vals:
                out.append(f"{m.group(1)} IN ({','.join('?' for _ in vals)})")
            else:
                out.append(f"{m.group(1)} IN (SELECT 1 WHERE 0)")
            new_params.extend(vals)
        else:
            out.append("?")
            new_params.append(val)
        i = m.end()
    out.append(sql[i:])
    return "".join(out), prefix + new_params


def _sql_only(sql, schema):
    """executemany용 — 값이 행마다 달라 _xlat의 ANY 전개(파라미터 선택)를 할 수 없음(이 저장소의 executemany 호출은
    전부 ANY를 안 씀 — load/pgstore.py 확인됨)."""
    sql = sql.replace(f"{schema}.", "")
    sql = _CAST_RE.sub("%s", sql)
    return sql.replace("%s", "?")


def _dim_of(con):
    for _cid, name, decltype, *_r in con.sqlite.execute("PRAGMA table_info(chunk)").fetchall():
        if name == "embedding":
            m = re.search(r"\d+", decltype or "")
            return int(m.group()) if m else None
    return None


def _run_ddl_script(con, sql):
    """deploy()가 schema.sql 전체(여러 문장)를 한 번에 cur.execute(sql)로 보냄 — SQLite는 한 번에 한 문장만이라
    ;로 나눠 돌린다(이 파일의 주석엔 ;가 없음, 안전). SERIAL→INTEGER · DEFAULT now()→DEFAULT (now()) · ALTER TABLE
    ADD COLUMN IF NOT EXISTS→중복이면 무시 · CREATE OR REPLACE VIEW→DROP+CREATE 로 바꾼다."""
    sql = re.sub(r"--[^\n]*", "", sql)  # 줄 주석 제거(먼저) — 안 그러면 주석이 섞인 첫 덩어리가 "CREATE SCHEMA"로 안 시작해 건너뛰기를 놓침
    sql = _SERIAL_RE.sub("INTEGER", sql)
    sql = sql.replace("TEXT[]", "TEXT")  # 10-15 chunk.clients — SQLite has no arrays: stored as JSON text, filtered in Python
    sql = _DEFAULT_NOW_RE.sub("DEFAULT (now())", sql)
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if not stmt or stmt.upper().startswith("CREATE SCHEMA"):
            continue
        vm = _VIEW_RE.match(stmt)
        if vm:
            name, body = vm.group(1), vm.group(2)
            con.sqlite.execute(f"DROP VIEW IF EXISTS {name}")
            con.sqlite.execute(f"CREATE VIEW {name} AS {body}")
            continue
        am = _ALTER_IFNE_RE.match(stmt)
        if am:
            stmt = am.group(1) + " " + stmt[am.end() :]
            try:
                con.sqlite.execute(stmt)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):
                    raise
            continue
        con.sqlite.execute(stmt)


def _vector_top(con, sql, params):
    """embedding <=> %s::vector 전용(코사인, 전체 스캔) — WHERE chunk_id = ANY(%s)(선택)·LIMIT만 해석.
    ponytail: 이진 양자화·HNSW 색인 흉내 없음(천 단위면 몰라도 여기선 느림) — 합성 데이터(수십 건)에만."""
    m = re.search(r"chunk_id\s*=\s*ANY\(%s\)", sql)
    params = list(params or ())
    restrict, pi = None, 0
    if m:
        restrict = set(params[0])
        pi = 1
    qv = _parse_vec(params[pi])
    n = int(params[pi + 1])
    scored = []
    for cid, emb in con.sqlite.execute("SELECT chunk_id, embedding FROM chunk").fetchall():
        if restrict is not None and cid not in restrict:
            continue
        v = _parse_vec(emb)
        if not v or len(v) != len(qv):
            continue
        scored.append((1 - _cosine(qv, v), cid))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(cid,) for _, cid in scored[:n]]


def _run(con, sql, params=None):
    """단일 실행 지점 — .q()·커서 .execute() 둘 다 이걸 거침. 반환 (rows:list[tuple], cols:list[str]|None).
    mc-01(11-01) — 검색 MCP는 작업 스레드에서 부르므로 연결 하나를 잠금(con.lock)으로 줄 세움."""
    with con.lock:
        return _run_locked(con, sql, params)


def _run_locked(con, sql, params=None):
    sql = sql.replace(f"{con.schema}.", "")
    low = sql.lower()
    if "create schema" in low:  # schema.sql 전체(여러 문장) — 먼저 걸러야 함(그 안의 주석에 "create extension" 글자가 섞여 있음)
        _run_ddl_script(con, sql)
        return [], None
    if low.lstrip().startswith("set local"):
        return [], None
    if "pg_extension" in low and "vector" in low:
        return [(1,)], ["x"]
    if "create extension" in low:
        return [], None
    if "information_schema.schemata" in low:
        return ([(1,)] if con.existed_before else []), ["x"]
    if "information_schema.tables" in low and "load_run" in sql:
        r = con.sqlite.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='load_run'").fetchall()
        return r, ["x"]
    if "information_schema.tables" in low:
        r = con.sqlite.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchall()
        return r, ["x"]
    if "pg_attribute" in low and "atttypmod" in low:
        return [(_dim_of(con),)], ["d"]
    if "using hnsw" in low or "bit_hamming_ops" in low or "using gin" in low:
        return [], None
    if "<=>" in sql:
        return _vector_top(con, sql, params), ["chunk_id"]
    sql2, params2 = _xlat(sql, params, con.schema)
    cur = con.sqlite.execute(sql2, params2)
    if cur.description:
        return cur.fetchall(), [d[0] for d in cur.description]
    return [], None


class _Cp:
    """psycopg Cursor.copy() 자리 — COPY ... FROM STDIN을 행마다 INSERT로."""

    def __init__(self, pg, table, cols):
        self.pg, self.table, self.cols = pg, table, cols

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write_row(self, values):
        ph = ",".join("?" for _ in values)
        with self.pg.lock:
            self.pg.sqlite.execute(f"INSERT INTO {self.table}({self.cols}) VALUES ({ph})", values)


class _Cur:
    def __init__(self, pg):
        self.pg = pg
        self.description = None
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._rows, cols = _run(self.pg, sql, params)
        self.description = [(c,) for c in cols] if cols else None
        return self

    def executemany(self, sql, rows):
        sql = sql.replace(f"{self.pg.schema}.", "")
        with self.pg.lock:
            self.pg.sqlite.executemany(_sql_only(sql, self.pg.schema), rows)
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def copy(self, sql):
        m = _COPY_RE.search(sql.replace(f"{self.pg.schema}.", ""))
        return _Cp(self.pg, m.group(1), m.group(2))


class _Conn:
    def __init__(self, pg):
        self.pg = pg

    def cursor(self):
        return _Cur(self.pg)

    @contextmanager
    def transaction(self):
        with self.pg.lock:  # 거래 동안 다른 스레드가 끼어들지 않게(RLock — 같은 스레드의 _run은 그대로 들어감)
            self.pg.sqlite.execute("BEGIN")
            try:
                yield
            except Exception:
                self.pg.sqlite.execute("ROLLBACK")
                raise
            else:
                self.pg.sqlite.execute("COMMIT")


class StandinPG:
    """common.pg.PG·PGPool과 같은 자리(schema·q()·scope()·cn.cursor()·cn.transaction()) — load/pgstore.py·
    search/pgsearch.py가 db 종류를 안 가리고 그대로 쓴다."""

    is_standin = True  # 코디네이터 10-14 — MCP /health가 "db": "standin"|"pg"를 구분하는 자리(PG·PGPool엔 없음 → False 취급)

    def __init__(self, schema):
        d = standin_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{schema}.sqlite"
        self.schema = schema
        self.existed_before = path.exists()
        # check_same_thread=False + lock(RLock) — 검색 MCP 작업 스레드에서도 쓰게(mc-01 11-01, 실 PG는 PGPool)
        self.sqlite = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
        self.lock = threading.RLock()
        self.sqlite.execute("PRAGMA foreign_keys=ON")
        self.sqlite.create_function("now", 0, _now_iso)
        # mc-01(11-01) — PG 검색 SQL을 대역에서 그대로 돌리게: v_chunk_source 뷰의 regexp_replace · BM25의 ln(이미지 sqlite에 수학 함수가 없을 수도)
        self.sqlite.create_function("regexp_replace", 3, lambda s, p, r: None if s is None else re.sub(p, r, s))
        self.sqlite.create_function("ln", 1, lambda x: None if x is None or x <= 0 else math.log(x))
        self.cn = _Conn(self)

    def q(self, sql, params=None):
        rows, cols = _run(self, sql, params)
        return [dict(zip(cols, r)) for r in rows] if cols else []

    @contextmanager
    def scope(self):
        yield self
