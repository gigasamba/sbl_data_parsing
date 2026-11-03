"""마스터 표 읽기·채우기(pl-38, 사용자 11-03) — 용어집·고객 명부의 원본은 git CSV(`resources/vocab/glossary`), 실행 중에는 검색 PG의
`<PG_SCHEMA>_master` 표만 읽는다. 읽는 곳: common.core.terms(구조화 고객 판별·검색) — 프로세스마다 한 번(get()).
서버(dev·prd)는 마스터를 못 읽으면 멈춘다(SystemExit). PC·시험(PG 접속 없음)은 같은 CSV로 채운 SQLite 대역(output/pg_standin/<스키마>_master.sqlite).
해시 = 표 이름·머리글·row_no 순서 행의 sha256(16진) — `gold_version` `<VERSION>+m<앞 8자>`(적재 — 구조화가 읽은 값을 묶음 meta.json으로 넘김)."""

import datetime
import hashlib
import json
import threading

from common.core.paths import RES_ROOT
from common.store.db.models.master_tables import META, TABLES

GLOSSARY = RES_ROOT / "vocab" / "glossary"
_GOT: dict = {}  # 프로세스마다 한 번 — {"m": Master}
_GOT_LOCK = threading.Lock()  # 검색 MCP는 여러 스레드 — 확인·채우기·비우기를 한 잠금으로


class Master:
    """읽은 마스터 — hash(16진 64자)·tables {표: [행 사전…](row_no 순서, 칸 = CSV 머리글, 빈 칸은 '')}."""

    def __init__(self, tables):
        self.tables = tables
        self.hash = content_hash(tables)

    def rows(self, name):
        return self.tables.get(name, [])


def schema_name(base):
    return f"{base}_master"


def content_hash(tables):
    """표 이름·머리글·행(row_no 순서)으로 만든 sha256 — 같은 CSV면 같은 값(PG·대역 어디서 읽어도)."""
    body = [[n, list(TABLES[n]), [[r.get(c) or "" for c in TABLES[n]] for r in tables.get(n, [])]] for n in sorted(TABLES)]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_csvs(folder=GLOSSARY):
    """git CSV 여섯 개 → {표: [행 사전…]}. 머리글이 표 정의와 다르면 거부(칸을 바꾸려면 새 Alembic 판)."""
    import csv

    from common.core.terms import _read_text

    out = {}
    for name, cols in TABLES.items():
        rows = list(csv.reader(_read_text(folder / f"{name}.csv")[0].splitlines()))
        head = tuple(h.strip() for h in rows[0])
        if head != cols:
            raise SystemExit(f"[master] {name}.csv 머리글이 표와 다름 — 칸을 바꾸려면 새 Alembic 판(master): {head}")
        out[name] = [dict(zip(cols, [*(v for v in r), *[""] * len(cols)][: len(cols)])) for r in rows[1:] if r]
    return out


def load(db, tables=None):
    """표 내용을 CSV로 통째로 바꾸고(한 트랜잭션) master_meta에 해시·시각을 적는다. db = PG·StandinPG(schema = 마스터 스키마). 반환: 해시."""
    tables = read_csvs() if tables is None else tables
    h = content_hash(tables)
    s = db.schema
    with db.cn.transaction():
        cur = db.cn.cursor()
        for name, cols in TABLES.items():
            cur.execute(f"DELETE FROM {s}.{name}")
            sql = f"INSERT INTO {s}.{name} (row_no, {', '.join(cols)}) VALUES ({', '.join(['%s'] * (len(cols) + 1))})"
            for i, r in enumerate(tables.get(name, []), 1):
                cur.execute(sql, (i, *(r.get(c) or "" for c in cols)))
        cur.execute(f"DELETE FROM {s}.{META}")
        cur.execute(
            f"INSERT INTO {s}.{META} (id, hash, loaded_at) VALUES (1, %s, %s)", (h, datetime.datetime.now(datetime.UTC).isoformat())
        )
    return h


def read(db):
    """마스터 표 → Master. 표가 없거나 비었으면(master load 전) SystemExit.
    master_meta와 표 6개를 한 트랜잭션(PG는 REPEATABLE READ)으로 읽는다 — 그 사이 `master load`가 커밋돼도 옛·새 내용이 섞이지 않게."""
    s = db.schema
    try:
        with db.cn.transaction():
            if not getattr(db, "is_standin", False):
                db.q("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            meta = db.q(f"SELECT hash FROM {s}.{META}")
            tables = {n: db.q(f"SELECT {', '.join(cols)} FROM {s}.{n} ORDER BY row_no") for n, cols in TABLES.items()}
    except Exception as e:  # 표 없음·권한 등 — 원인은 메시지에
        raise SystemExit(
            f"[master] 마스터 표를 못 읽음({s} — {type(e).__name__}): `dbtool up --target master` 뒤 `dbtool master load`"
        ) from e
    if not meta:
        raise SystemExit(f"[master] {s}.{META}가 비어 있음 — `dbtool master load`로 채움")
    return Master({n: [{c: r.get(c) or "" for c in TABLES[n]} for r in rows] for n, rows in tables.items()})


def _standin(base):
    """PC 대역 — 표가 없으면 만들고 CSV로 채움(실 PG와 같은 칸)."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from common.store.db.models.master_tables import master_metadata
    from common.store.pg_standin import StandinPG

    db = StandinPG(schema_name(base))
    if not db.q("SELECT name FROM sqlite_master WHERE type='table' AND name=%s", (META,)):
        d = postgresql.dialect()
        for t in master_metadata(db.schema).tables.values():
            db.q(str(CreateTable(t).compile(dialect=d)).strip())
    have = db.q(f"SELECT hash FROM {db.schema}.{META}")
    tables = read_csvs()
    if not have or have[0]["hash"] != content_hash(
        tables
    ):  # 비었거나 git CSV가 바뀌었으면 다시 채움(PC 대역만 — 서버는 `dbtool master load`)
        load(db, tables)
    return db


def get():
    """이 프로세스의 마스터(처음 한 번 읽음). 실 PG(common.store.pg 접속)는 `<PG_SCHEMA>_master`, 접속 정보가 없으면 PC 대역 — 서버는 대역을 쓰지 않고 멈춤."""
    with _GOT_LOCK:
        m = _GOT.get("m")
        if m is None:
            from common.store.pg import PG, _standin_schema, _warn_standin, conf, has_conn

            if has_conn():
                c = conf()
                db = PG({**c, "PG_SCHEMA": schema_name(c["PG_SCHEMA"])})
                try:
                    m = read(db)
                finally:
                    db.cn.close()
            else:
                _warn_standin()  # 서버(dev·prd)는 여기서 SystemExit
                m = read(_standin(_standin_schema(None)))
            _GOT["m"] = m
        return m


def reset():
    """다시 읽게(검색 서버가 적재 판 바뀜을 볼 때·시험)."""
    with _GOT_LOCK:
        _GOT.clear()
