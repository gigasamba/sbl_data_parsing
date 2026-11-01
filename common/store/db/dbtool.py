#!/usr/bin/env python3
"""pgvector 우리 스키마 판 관리 명령(S8a — refactor_plan 5-4, 사용자 10-28 Step 0 답 Q1~Q10 a).
  python -m common.store.db.dbtool up      --target search|all [--schema S] [--dim N | --bundle B] [--create-extension]
  python -m common.store.db.dbtool stamp   --target …   — 이미 있는 DB에 실행 없이 판만 기록(비교 차이 0일 때만)
  python -m common.store.db.dbtool current --target …   — 지금 판·코드의 끝 판
  python -m common.store.db.dbtool check   --target …   — 표 정의 ↔ 실제 DB 비교(차이·판이 끝이 아니면 종료 코드 1)
  python -m common.store.db.dbtool --pg-cases orca_<이름>  — PC 전용 PG 시험(새 시험 DB — 기본 스키마·vector 확장 자리, VS8a B-1·R-9)
  이미지: `migrate up --target all --bundle …`(entrypoint — pipeline 이미지, load와 같은 잠금).
· 갈래 search = 검색 스키마(PG_SCHEMA — index --pg 스키마는 --schema) 하나(struct 갈래는 사용자 11-01에 없앰 — 엔진 구성·원천 목록은 파일).
  판 기록 표는 스키마마다 <스키마>.alembic_version.
· up: 판 기록이 없는데 표가 있는 스키마(옛 코드가 만든 DB)는 먼저 비교 — 차이가 기준판이 고치는 것(표·색인·뷰 없음, 뷰 칸 다름)뿐이면 고치고
  판 기록(기준판이 IF NOT EXISTS·뷰는 DROP 뒤 다시 만듦), 칸 이름·형식·NULL·기본값·키가 다르거나 남는 표가 있으면 거부(Q3). 적재 앞 자동 길
  (pgvector_load deploy)은 판 기록 없는 기존 스키마면 비교·DDL 없이 경고만(코디네이터 10-28 a — Q5). 검색 스키마는 지금 deploy와 같은 확인을 먼저 —
  vector 확장(없으면 멈춤, --create-extension = 옛 PG_CREATE_EXTENSION=1 옵트인)·남의 스키마 거부(load_run 없음)·차원(DB와 다르면 새 PG_SCHEMA).
· 차원은 --dim 또는 --bundle <묶음>/meta.json, 있는 스키마는 DB 차원(새 설정 칸 없음 — Q4).
· 적재 전 판 확인(require_current — Q5): 판 기록 없음 = 경고 뒤 계속(기준판 = 지금 스키마), 끝보다 낮거나 모르는 판 = 거부. MCP(읽기)는 안 봄.
· SQLite 대체(pg_standin)는 판 관리 밖 — 표 정의에서 바로 만든다(standin_script). 접속 값은 settings.yaml(common.store.pg.conf).
· 비밀값·행 값은 찍지 않는다(카탈로그·판 번호만)."""

import argparse
import json
import re
import sys
from pathlib import Path

from common.core.console import utf8_stdout

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"
TARGETS = ("search",)  # struct 갈래는 사용자 11-01에 없앰(서버에 남은 struct 스키마는 코드가 읽지 않음 — DB 담당자가 두거나 지움)
_SCHEMA_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")  # common/store/pg.conf()의 PG_SCHEMA 규칙(그 함수 안 정규식)과 같음
_SCRIPTS: dict = {}


class DbToolError(SystemExit):
    """판 관리 거부(종료 코드 2 — 안내 글자 찍고). SystemExit이라 CLI·적재 명령은 그대로 멈춘다."""

    def __init__(self, msg):
        print(f"[migrate] {msg}", file=sys.stderr, flush=True)
        super().__init__(2)


# ── Alembic 판 폴더 ─────────────────────────────────────────────────────
def _config(conn=None, **attrs):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes.update(connection=conn, **attrs)
    return cfg


def _script():
    if "s" not in _SCRIPTS:
        from alembic.script import ScriptDirectory

        _SCRIPTS["s"] = ScriptDirectory.from_config(_config())
    return _SCRIPTS["s"]


def head(target):
    return _script().get_revision(f"{target}@head").revision


def known(target):
    """그 갈래의 판 번호 전부(끝 → 처음)."""
    return [r.revision for r in _script().iterate_revisions(f"{target}@head", "base")]


# ── 판 상태 — q는 SQL 글자 → [dict] 함수(psycopg PG.q·SQLAlchemy 연결 둘레) ───────────────────
def schema_of(target, schema=None):
    if schema is None:
        from common.store.pg import conf

        schema = conf()["PG_SCHEMA"]
    if not _SCHEMA_RE.fullmatch(schema):
        raise DbToolError(f"검색 스키마 이름이 틀림: {schema!r} — 소문자·숫자·_ 만")
    return schema


def versions(q, schema):
    """판 기록 표의 판 번호들 — 표가 없으면 None."""
    if not q(f"SELECT 1 AS x WHERE to_regclass('{schema}.alembic_version') IS NOT NULL"):
        return None
    return [r["version_num"] for r in q(f"SELECT version_num FROM {schema}.alembic_version")]


def status(q, target, schema):
    """('없음'|'끝'|'낮음'|'모름', 판 번호들). 갈래 판 번호만 본다 — 코드가 모르는 판이 하나라도 섞이면 '모름'(새 이미지 → 옛 이미지로 되돌린
    뒤 적재가 '끝'으로 통과하지 않게 — VS8a R-4)."""
    have = versions(q, schema)
    if have is None or not have:
        return "없음", have or []
    if set(have) - set(known(target)):
        return "모름", have
    return ("끝" if head(target) in have else "낮음"), have


def require_current(q, target, schema):
    """적재·쓰기 전 판 확인(Q5) — 판 기록 없음: 경고 뒤 계속 · 끝보다 낮거나 모르는 판: DbToolError(종료 2)."""
    st, have = status(q, target, schema)
    if st == "끝":
        return st
    if st == "없음":
        print(
            f"[migrate] 경고: {schema} 판 기록 없음(alembic_version) — 기준판과 같은 스키마로 보고 계속. "
            f"서버는 `migrate check --target {target}` 뒤 `migrate stamp`(또는 up)로 판을 기록(docs/operations/release-and-patch.md §5-5)",
            file=sys.stderr,
            flush=True,
        )
        return st
    if st == "낮음":
        msg = (
            f"{schema} 판 {have} — 코드의 끝 판 {head(target)}보다 낮음: 적재 전에 `migrate up --target {target}`"
            f"(PC: python -m common.store.db.dbtool up --target {target})"
        )
    else:
        msg = (
            f"{schema} 판 {have} — 이 코드가 모르는 판(DB가 코드보다 새 판이거나 남의 판 표): 이미지·코드 판을 DB와 맞춘 뒤 다시"
            f"(코드의 끝 판 {head(target)})"
        )
    raise DbToolError(msg)


# ── 연결 ─────────────────────────────────────────────────────────────
def engine(**over):
    """settings.yaml 접속 값(common.store.pg.conf — 비밀번호는 설정 파일에만)으로 SQLAlchemy 엔진(psycopg 3, 연결 풀 없음).
    over = 접속 인자 덮기(PC 시험 pg_cases — dbname·options)."""
    import psycopg
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from common.config.settings import cfg
    from common.store.pg import conf

    c = conf()
    kw = dict(
        host=c["PG_HOST"],
        port=int(c["PG_PORT"]),
        dbname=c["PG_DB"],
        user=c["PG_USER"],
        password=c["PG_PASSWORD"],
        connect_timeout=cfg().connections.pg.connect_timeout,
    )
    kw.update(over)
    return create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(**kw), poolclass=NullPool)


def _q(conn):
    def q(sql, params=None):
        res = conn.exec_driver_sql(sql)
        return [dict(r._mapping) for r in res.fetchall()] if res.returns_rows else []

    return q


def has_tables(q, schema):
    """판 기록 표 말고 표가 하나라도 있나."""
    return bool(
        q(f"SELECT 1 AS x FROM information_schema.tables WHERE table_schema = '{schema}' AND table_name <> 'alembic_version' LIMIT 1")
    )


# ── 검색 스키마 확인(옛 pgvector_load.deploy 그대로 — q 함수로) ──────────────────────────────
def precheck_search(q, schema, dim, create_extension=False):
    """vector 확장 · 남의 스키마 거부 · 차원(있는 chunk 표와 다르면 거부). 옛 deploy와 같은 글자·같은 종료(SystemExit)."""
    if not q("SELECT 1 FROM pg_extension WHERE extname='vector'"):
        if create_extension:  # 명시 옵트인(PC·단독 시험)만 — 공유 PG에서는 켜지 말 것
            try:
                q("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as e:
                raise SystemExit(f"vector 확장 설치 실패 — 관리자 설치 필요: {type(e).__name__}: {e}") from e
        if not q("SELECT 1 FROM pg_extension WHERE extname='vector'"):
            raise SystemExit(
                f"vector 확장 없음 — 관리자 설치 필요(PG_CREATE_EXTENSION=1이면 직접 생성 시도 — 공유 PG에서는 켜지 말 것) · 스키마={schema}"
            )
    if (
        q(f"SELECT 1 FROM information_schema.schemata WHERE schema_name='{schema}'")
        and q(f"SELECT 1 FROM information_schema.tables WHERE table_schema='{schema}' LIMIT 1")
        and not q(f"SELECT 1 FROM information_schema.tables WHERE table_schema='{schema}' AND table_name='load_run'")
    ):
        raise SystemExit(
            f"deploy 거부: 스키마 {schema}에 표가 있지만 우리 표식(load_run)이 없음 — 남의 기존 스키마일 수 있음(다른 PG_SCHEMA 사용)"
        )
    check_dim(q, schema, dim)


def check_dim(q, schema, dim):
    """있는 chunk 표의 차원(없으면 None) — dim과 다르면 거부(옛 deploy 글자 그대로)."""
    from common.store.db.dbcompare import DIM_SQL

    have = q(DIM_SQL.format(schema=schema))
    if dim is not None and have and have[0]["d"] not in (None, -1) and have[0]["d"] != int(dim):
        raise SystemExit(f"{schema}.chunk.embedding 차원 {have[0]['d']} ≠ 묶음 {dim} — 임베딩 모델이 바뀜: 새 PG_SCHEMA로 배포")
    return have[0]["d"] if have and have[0]["d"] not in (None, -1) else None


def index_kind(dim):
    from common.store.pg import HNSW_MAX

    return "HNSW 코사인" if int(dim) <= HNSW_MAX else "이진 양자화 HNSW + 코사인 재정렬"


# ── 판 올리기·기록 ─────────────────────────────────────────────────────
def upgrade(target, schema, dim=None, conn=None):
    """판을 끝까지(한 트랜잭션). 판 기록 없는 기존 스키마는 먼저 비교(위 설명). 반환: 비교 보고(올리기 전 — 없으면 None)."""
    from alembic import command

    from common.store.db import dbcompare

    if conn is None:
        with engine().begin() as c:
            return upgrade(target, schema, dim, c)
    q = _q(conn)
    if target == "search":
        dim = check_dim(q, schema, dim) or dim
        if dim is None:
            raise DbToolError(f"{schema}: 차원을 모름 — --dim N 또는 --bundle <묶음>(meta.json dim)")
    st, have = status(q, target, schema)
    if st == "모름":
        raise DbToolError(f"{schema} 판 {have} — 이 코드가 모르는 판(코드보다 새 판?) — 올리지 않음")
    before = None
    if st == "없음" and has_tables(q, schema):
        before = dbcompare.compare(conn, target, schema, dim)
        bad = before.blocking()
        if bad:
            raise DbToolError(
                f"{schema}: 판 기록 없는 기존 스키마가 표 정의와 다름 — 올리지 않음(사람 확인·DB 담당 협의):\n" + "\n".join(before.lines())
            )
        if before.diffs:
            print(
                f"[migrate] {schema}: 판 기록 없는 기존 스키마 — 기준판이 고치는 것만(없는 표·색인·뷰 만들기, 뷰 다시 만들기) 고치고 판 기록:\n"
                + "\n".join(before.lines()),
                file=sys.stderr,
            )
    command.upgrade(_config(conn, target=target, schema=schema, dim=dim, create_schema=True), f"{target}@head")
    return before


def stamp(target, schema, dim=None, conn=None):
    """실행 없이 판만 기록 — 비교 차이 0일 때만(Q3). 모르는 판이 있으면 올리기와 같이 거부(VS8a R-3). conn = 호출자 트랜잭션(없으면 새로)."""
    from alembic import command

    from common.store.db import dbcompare

    if conn is None:
        with engine().begin() as c:
            return stamp(target, schema, dim, c)
    q = _q(conn)
    st, have = status(q, target, schema)
    if st == "모름":
        raise DbToolError(f"{schema} 판 {have} — 이 코드가 모르는 판(코드보다 새 판?) — stamp 안 함")
    if target == "search":
        dim = check_dim(q, schema, dim) or dim
    rep = dbcompare.compare(conn, target, schema, dim)
    if rep.diffs:
        raise DbToolError(f"{schema}: 표 정의와 다름 — stamp 안 함(없는 것만이면 up이 만듦):\n" + "\n".join(rep.lines()))
    for line in rep.info:
        print(f"[migrate] (알림) {line}", file=sys.stderr)
    command.stamp(_config(conn, target=target, schema=schema, dim=dim, create_schema=False), f"{target}@head")


def check(target, schema, dim=None, conn=None):
    """(판 상태, 판 번호들, 비교 보고) — 읽기만(conn이 없으면 새 연결에서 하고 되돌림)."""
    from common.store.db import dbcompare

    if conn is None:
        with engine().connect() as c:
            try:
                return check(target, schema, dim, c)
            finally:
                c.rollback()
    q = _q(conn)
    st, have = status(q, target, schema)
    if target == "search":
        dim = check_dim(q, schema, dim) or dim
    rep = dbcompare.compare(conn, target, schema, dim) if has_tables(q, schema) else None
    return st, have, rep


# ── SQLite 대역(pg_standin) — 판 관리 밖, 표 정의에서 바로(5-4) ───────────────────────────────
def standin_script(schema, dim):
    """검색 스키마를 PostgreSQL 꼴 DDL 글자로(표 정의에서 컴파일 + 뷰) — pg_standin이 옛 schema.sql처럼 받아 SQLite로 번역한다
    (첫 문장 CREATE SCHEMA로 DDL 묶음임을 알아봄). HNSW·GIN 색인은 대역이 흉내 내지 않아 넣지 않는다."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from common.store.db.models import search_tables as ST

    md = ST.search_metadata(schema, dim)
    d = postgresql.dialect()
    parts = [f"CREATE SCHEMA IF NOT EXISTS {schema}"]
    for t in md.tables.values():  # 정의 순서(옛 schema.sql 순서 — load_run·doc·chunk·…)
        parts.append(str(CreateTable(t, if_not_exists=True).compile(dialect=d)).strip())
        parts += [str(CreateIndex(i, if_not_exists=True).compile(dialect=d)).strip() for i in sorted(t.indexes, key=lambda i: i.name)]
    parts.append(ST.VIEW_SQL.replace("{S}", schema))
    return ";\n".join(parts) + ";\n"


# ── 명령 ─────────────────────────────────────────────────────────────
def _dim_arg(a):
    if a.dim is not None:
        return a.dim
    if a.bundle:
        return json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8")).get("dim") or None
    return None


def _targets(a):
    return TARGETS if a.target == "all" else (a.target,)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("cmd", nargs="?", choices=["up", "stamp", "current", "check"])
    ap.add_argument("--target", choices=[*TARGETS, "all"], default="all")
    ap.add_argument("--schema", help="검색 스키마(기본 settings PG_SCHEMA — index --pg 스키마는 <PG_SCHEMA>_<index_id>)")
    ap.add_argument("--dim", type=int, help="임베딩 차원(새 검색 스키마 — 있는 스키마는 DB 차원)")
    ap.add_argument("--bundle", help="묶음 폴더 — meta.json의 dim")
    ap.add_argument(
        "--create-extension", action="store_true", help="vector 확장이 없으면 만들기(옛 PG_CREATE_EXTENSION=1 — PC·단독 시험만)"
    )
    ap.add_argument(
        "--pg-cases", metavar="DB", help="PC 전용 PG 시험 — 새 시험 DB(orca_…)를 만들어 기본 스키마·vector 확장 자리 사례(VS8a B-1·R-9)"
    )
    a = ap.parse_args(argv)
    if a.pg_cases:
        return 1 if pg_cases(a.pg_cases) else 0
    if not a.cmd:
        ap.error("명령: up·stamp·current·check")
    from common.store.pg import has_conn

    if not has_conn():
        raise DbToolError("PG 접속 정보 없음(settings.yaml required.pg) — SQLite 대역은 판 관리 밖(표 정의에서 바로 만듦)")
    dim, rc = _dim_arg(a), 0
    for target in _targets(a):
        schema = schema_of(target, a.schema)
        if a.cmd == "up":
            if target == "search":
                with engine().begin() as conn:
                    precheck_search(_q(conn), schema, dim, a.create_extension)
                    upgrade(target, schema, dim, conn)
            else:
                upgrade(target, schema, dim)
            st, have, rep = check(target, schema, dim)
            print(
                f"[migrate] {target} {schema}: 판 {have} (끝 {head(target)})" + ("" if not rep or not rep.diffs else " — 올린 뒤에도 차이:")
            )
            if rep and rep.diffs:
                print("\n".join(rep.lines()))
                rc = 1
        elif a.cmd == "stamp":
            stamp(target, schema, dim)
            print(f"[migrate] {target} {schema}: 판 {head(target)} 기록(실행 없이 — 비교 차이 0)")
        else:
            st, have, rep = check(target, schema, dim)
            print(
                f"[migrate] {target} {schema}: 판 {st} {have or ''} · 코드의 끝 판 {head(target)}"
                + ("" if rep is not None else " · 표 없음(새 스키마 — up으로 만듦)")
            )
            if a.cmd == "check":
                if rep is not None:
                    print(
                        "  비교: "
                        + ("차이 없음" if not rep.diffs else f"차이 {len(rep.diffs)}")
                        + (f" · 알림 {len(rep.info)}" if rep.info else "")
                    )
                    print("\n".join(rep.lines()))
                rc = max(rc, 0 if st == "끝" and rep is not None and not rep.diffs else 1)
    return rc


# ── PC 전용 PG 시험(VS8a B-1·R-9) — 새 시험 DB를 만들어 비교·거부가 스키마 배치와 무관한지 ──────────────────────
def pg_cases(name):
    """새 시험 DB `<name>`·`<name>_e1`·`<name>_e2`를 만들어(이미 있으면 거부 — 아무것도 지우지 않음) 확인한다:
    ① 우리 스키마 = 연결의 기본 스키마(current_schema()) 세 꼴 — PG_SCHEMA=public · 역할 이름 = 스키마("$user") · search_path = 스키마
       : up 뒤 check 차이 0, 판 표를 지우고 남는 칸·형식 다름을 넣으면 check가 그 둘을 보이고 up·stamp 거부(B-1)
    ② vector 확장이 다른 스키마(e1 — 차원 8·4096)·우리 스키마(e2 — 4096)에 있을 때 up 뒤 check 차이 0(색인 글자 정규화 — R-9).
    PC(RUN_ENV=local)·이름 orca_… 만. 반환: 실패 수."""
    from common.core import paths

    if not paths.LOCAL_RUN:
        raise DbToolError("pg_cases는 PC 전용(RUN_ENV=local)")
    if not re.fullmatch(r"orca_[a-z0-9_]{1,40}", name):
        raise DbToolError(f"시험 DB 이름은 orca_[a-z0-9_]…: {name!r}")
    from common.store.db.dbcompare import VERSION_TABLE

    dbs = (name, f"{name}_e1", f"{name}_e2")
    with engine(dbname="postgres").connect() as c:
        c = c.execution_options(isolation_level="AUTOCOMMIT")
        user = c.exec_driver_sql("SELECT current_user").scalar()
        if c.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = ANY(%(n)s)", {"n": list(dbs)}).first():
            raise DbToolError(f"시험 DB가 이미 있음({'·'.join(dbs)} 중) — 새 이름으로")
        for d in dbs:
            c.exec_driver_sql(f"CREATE DATABASE {d}")
    fails = []

    def run(db, sql, options=None):
        with engine(dbname=db, **({"options": options} if options else {})).begin() as c:
            for stmt in sql.split(";"):
                if stmt.strip():
                    c.exec_driver_sql(stmt)

    def ok(cond, what):
        print(f"[pg_cases] {'통과' if cond else '실패'} — {what}")
        if not cond:
            fails.append(what)

    def same(db, target, schema, dim, options=None, label=""):
        eng = lambda: engine(dbname=db, **({"options": options} if options else {}))  # 단계마다 새 엔진(첫 연결 때 기본 스키마를 정함)
        with eng().begin() as c:
            upgrade(target, schema, dim, c)
        with eng().connect() as c:
            cur = c.exec_driver_sql("SELECT current_schema()").scalar()
            st, have, rep = check(target, schema, dim, c)
        ok(
            st == "끝" and rep is not None and not rep.diffs,
            f"{label} {schema}(current_schema={cur}): up 뒤 check 차이 0 — {st} {[] if rep is None else rep.diffs}",
        )
        return eng, cur

    def bad_case(target, schema, opts, label):
        eng, cur = same(name, target, schema, 8, opts, label)
        ok(cur == schema, f"{label}: 기본 스키마가 우리 스키마({cur})")
        bad = (
            f"DROP TABLE {schema}.{VERSION_TABLE}; ALTER TABLE {schema}.doc ADD COLUMN file_sha256 CHAR(64); "
            f"ALTER TABLE {schema}.chunk ALTER COLUMN n_terms TYPE BIGINT"
        )
        run(name, bad, opts)
        with eng().connect() as c:
            kinds = {k for k, _ in check(target, schema, None, c)[2].diffs}
        ok({"남는 칸", "칸 형식 다름"} <= kinds and "표 없음" not in kinds, f"{label}: 남는 칸·형식 다름이 보임 {sorted(kinds)}")
        for fn in (upgrade, stamp):
            try:
                with eng().begin() as c:
                    fn(target, schema, None, c)
                ok(False, f"{label}: {fn.__name__} 거부")
            except DbToolError as e:
                ok(e.code == 2, f"{label}: {fn.__name__} 거부(종료 2)")
        with eng().connect() as c:
            ok(versions(_q(c), schema) is None, f"{label}: 판 기록 안 생김")

    def guarded(fn, *args):
        try:
            fn(*args)
        except Exception as e:  # 한 사례가 깨져도 나머지는 돎(오류 종류만 — SQL 글자는 길어 줄임)
            ok(False, f"{args[-1]}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")

    run(name, "CREATE EXTENSION IF NOT EXISTS vector")
    guarded(bad_case, "search", "public", None, "PG_SCHEMA=public")  # 기본 search_path "$user", public — 사용자 스키마가 아직 없음
    run(name, f"CREATE SCHEMA {user}")  # 역할 이름 = 스키마 — "$user"가 고름
    guarded(bad_case, "search", user, None, "역할 이름 = 스키마")
    guarded(bad_case, "search", "orca_sp", "-c search_path=orca_sp,public", "search_path = 스키마(역할 설정 꼴)")
    run(f"{name}_e1", "CREATE SCHEMA ext; CREATE EXTENSION vector SCHEMA ext")
    for dim in (8, 4096):
        guarded(
            same, f"{name}_e1", "search", f"orca_v{dim}", dim, "-c search_path=public,ext", f"vector 확장이 다른 스키마(ext) · 차원 {dim}"
        )
    run(f"{name}_e2", "CREATE SCHEMA orca_v; CREATE EXTENSION vector SCHEMA orca_v")
    guarded(same, f"{name}_e2", "search", "orca_v", 4096, "-c search_path=orca_v", "vector 확장이 우리 스키마 · 차원 4096")
    print(f"[pg_cases] {'모두 통과' if not fails else f'실패 {len(fails)}'} — 시험 DB {'·'.join(dbs)}(남겨 둠)")
    return len(fails)


if __name__ == "__main__":
    utf8_stdout()
    raise SystemExit(main())
