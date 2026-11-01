"""표 정의 ↔ 실제 DB 비교(S8a, 5-4 — 사용자 10-28 Q3 a): Alembic compare_metadata(표·칸·형식·NULL·FK·기본값) + 기본 키 칸 +
색인은 PostgreSQL 정의 글자(pg_get_indexdef — 스키마 이름은 `{S}`로, vector 확장 이름 앞의 스키마는 뗌) · 뷰는 칸 이름·순서(정의 글자는
PostgreSQL 판마다 꼴이 달라 알림만 — 리뷰 S8a). 칸 순서는 판정 밖(다르면 알림만).
판정: 차이 0 → stamp 가능 · up이 고치는 것(표·색인·뷰 없음, 뷰 칸 다름 — 기준판이 IF NOT EXISTS·뷰는 DROP 뒤 다시 만듦)뿐 → up이 고치고 판
기록 · 그 밖(칸 이름·형식·NULL·기본값·키·남는 표·칸·색인·다른 색인 정의) → 거부. 값은 읽지 않는다(카탈로그만)."""

import re
from dataclasses import dataclass, field

from common.store.db.models import search_tables as ST

UP_FIXES = ("표 없음", "색인 없음", "뷰 없음", "뷰 칸 다름")  # up이 고치는 차이
VERSION_TABLE = "alembic_version"
DIM_SQL = "SELECT atttypmod AS d FROM pg_attribute WHERE attrelid = to_regclass('{schema}.chunk') AND attname = 'embedding'"
_VEC_NAMES = ("binary_quantize", "vector_cosine_ops", "vector_l2_ops", "vector_ip_ops", "bit_hamming_ops", "vector")


@dataclass
class Report:
    diffs: list = field(default_factory=list)  # [(종류, 설명)]
    info: list = field(default_factory=list)  # 판정 밖 알림(칸 순서·뷰 정의 글자)

    def blocking(self):
        return [d for d in self.diffs if d[0] not in UP_FIXES]

    def lines(self):
        return [f"  {k}: {t}" for k, t in self.diffs] + [f"  (알림) {t}" for t in self.info]


def _rows(conn, sql):
    return [dict(r._mapping) for r in conn.exec_driver_sql(sql).fetchall()]


def db_dim(conn, schema):
    """chunk.embedding 차원(표 없으면 None)."""
    r = _rows(conn, DIM_SQL.format(schema=schema))
    return r[0]["d"] if r and r[0]["d"] and r[0]["d"] > 0 else None


def expected(target, schema, dim=None):
    """(표 정의 MetaData, 색인 {이름: 정의}, 뷰 {이름: (칸들, 정의 글자)}) — `{S}` 자리표시 그대로."""
    if target == "applog":
        from common.store.db.models.log_tables import index_defs, log_metadata

        return log_metadata(schema), index_defs(), {}
    return ST.search_metadata(schema, dim), ST.index_defs(dim), ST.VIEWS_EXPECTED  # 갈래는 search 하나(struct는 사용자 11-01에 없앰)


def _norm(schema, s, ext=()):
    for e in ext:  # vector 확장(형식·함수·연산자 묶음)이 어느 스키마에 있든(우리 스키마여도) 그 이름 앞 스키마를 뗌
        s = re.sub(rf"\b{re.escape(e)}\.({'|'.join(_VEC_NAMES)})\b", r"\1", s)
    s = s.replace(f"ix_{schema}_", "ix_{S}_").replace(f"{schema}.", "{S}.")
    return re.sub(r"\s+", " ", s).strip()


def _text(v):
    """비교 문구용 — 표 정의의 기본값(DefaultClause(TextClause))은 글자로(VS8a R-2), 그 밖은 str."""
    arg = getattr(v, "arg", v)
    return getattr(arg, "text", None) or str(arg)


def _register_types(ext):
    """반영(reflect) 때 vector 형식을 알아보게(모르면 NullType이라 차원 차이를 놓침) — search_path 밖이면 '<스키마>.vector'로 옴."""
    from sqlalchemy.dialects.postgresql.base import ischema_names

    for name in ("vector", *(f"{e}.vector" for e in ext)):
        ischema_names.setdefault(name, ST.Vector)


def compare(conn, target, schema, dim=None):
    """conn = SQLAlchemy 연결(PostgreSQL). target search면 dim 없을 때 DB 차원을 쓴다. 정의 글자에 스키마 이름이 늘 붙게 search_path를
    pg_catalog로 잠깐 바꾸고, 끝나면 되돌린다(같은 트랜잭션에서 뒤에 도는 판 DDL이 원래 search_path로 돌게). 비교가 실패하면 되돌리지 않고
    그 오류를 그대로 올린다(트랜잭션은 호출자가 되돌림 — 되돌리기 SQL이 원래 오류를 가리지 않게)."""
    old = _rows(conn, "SELECT current_setting('search_path') AS p")[0]["p"]
    ext = tuple(
        r["s"]
        for r in _rows(
            conn, "SELECT n.nspname AS s FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
        )
    )
    conn.exec_driver_sql("SELECT set_config('search_path', 'pg_catalog', true)")
    # 방언의 기본 스키마(첫 연결 때 current_schema())가 우리 스키마이면 Alembic이 그 스키마를 None으로 바꿔 include_name이 걸러 비교가 빈다
    # (역할 search_path = 스키마·역할 이름 = 스키마·PG_SCHEMA=public — VS8a B-1). 비교 동안만 지금 search_path와 같은 pg_catalog로 둔다.
    dialect, dflt = conn.dialect, conn.dialect.default_schema_name
    dialect.default_schema_name = "pg_catalog"
    try:
        rep = _compare(conn, target, schema, dim, ext)
    finally:
        dialect.default_schema_name = dflt
    conn.exec_driver_sql("SELECT set_config('search_path', '{}', true)".format(old.replace("'", "''")))
    return rep


def _compare(conn, target, schema, dim, ext):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    _register_types(ext)
    if target == "search" and dim is None:
        dim = db_dim(conn, schema)
        if dim is None:
            dim = 0  # chunk 표가 없음 — 차원과 무관한 차이만 봄(표 없음으로 나옴)
    md, idx_want, view_want = expected(target, schema, dim or 1)
    rep = Report()
    partitions = (
        {
            r["name"]
            for r in _rows(
                conn,
                f"SELECT c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='{schema}' AND c.relispartition",
            )
        }
        if target == "applog"
        else set()
    )

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table" and name == VERSION_TABLE:
            return False
        return type_ not in ("index", "unique_constraint")  # 색인은 아래 정의 글자로

    mc = MigrationContext.configure(
        conn,
        opts={
            "compare_type": True,
            "compare_server_default": True,
            "include_schemas": True,
            "include_name": lambda name, type_, parent: (
                name == schema if type_ == "schema" else name not in partitions if type_ == "table" else True
            ),
            "include_object": include_object,
        },
    )
    for d in compare_metadata(mc, md):
        for op in d if isinstance(d, list) else [d]:
            kind = op[0]
            if kind == "add_table":
                rep.diffs.append(("표 없음", op[1].name))
            elif kind == "remove_table":
                rep.diffs.append(("남는 표", op[1].name))
            elif kind == "add_column":
                rep.diffs.append(("칸 없음", f"{op[2]}.{op[3].name}"))
            elif kind == "remove_column":
                rep.diffs.append(("남는 칸", f"{op[2]}.{op[3].name}"))
            elif kind.startswith("modify_"):
                what = {"modify_type": "형식", "modify_nullable": "NULL", "modify_default": "기본값"}.get(kind, kind)
                old, new = (("NULL 허용" if v else "NOT NULL") for v in op[5:7]) if kind == "modify_nullable" else map(_text, op[5:7])
                rep.diffs.append((f"칸 {what} 다름", f"{op[2]}.{op[3]}: DB {old!s} ≠ 정의 {new!s}"))
            elif kind in ("add_fk", "remove_fk"):
                fk = op[1]
                rep.diffs.append(
                    ("외래 키 " + ("없음" if kind == "add_fk" else "남음"), f"{fk.parent.name}({', '.join(c.name for c in fk.columns)})")
                )
            else:
                rep.diffs.append((kind, str(op[1:])[:200]))
    insp = inspect(conn)
    have_tables = set(insp.get_table_names(schema=schema))
    for t in md.sorted_tables:
        if t.name not in have_tables:
            continue
        pk = insp.get_pk_constraint(t.name, schema=schema).get("constrained_columns") or []
        want = [c.name for c in t.primary_key.columns]
        if pk != want:
            rep.diffs.append(("기본 키 다름", f"{t.name}: DB {pk} ≠ 정의 {want}"))
        order = [c["name"] for c in insp.get_columns(t.name, schema=schema)]
        names = [c.name for c in t.columns]
        if set(order) == set(names) and order != names:
            rep.info.append(f"칸 순서 다름(판정 밖) {t.name}: DB {order}")
    idx_have = {
        r["name"]: r["def"]
        for r in _rows(
            conn,
            f"""
        SELECT i.relname AS name, pg_get_indexdef(i.oid) AS def FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = '{schema}' {"AND NOT t.relispartition" if target == "applog" else ""} AND NOT x.indisprimary AND t.relname <> '{VERSION_TABLE}'""",
        )
    }
    idx_have = {
        _norm(schema, k): _norm(schema, v.replace("ON ONLY ", "ON ") if target == "applog" else v, ext) for k, v in idx_have.items()
    }
    for name, want in idx_want.items():
        if dim == 0 and "_chunk_emb" in name:
            continue  # chunk 표가 없으면 벡터 색인 종류를 모름(표 없음으로 이미 나옴)
        if name not in idx_have:
            rep.diffs.append(("색인 없음", name))
        elif idx_have[name] != _norm(schema, want):
            rep.diffs.append(("색인 정의 다름", f"{name}: DB {idx_have[name]}"))
    for name in sorted(set(idx_have) - set(idx_want)):
        if not (dim == 0 and "_chunk_emb" in name):
            rep.diffs.append(("남는 색인", name))
    view_have = {
        r["viewname"]: _norm(schema, r["definition"], ext)
        for r in _rows(conn, f"SELECT viewname, definition FROM pg_views WHERE schemaname = '{schema}'")
    }
    for name, (cols, text) in view_want.items():
        if name not in view_have:
            rep.diffs.append(("뷰 없음", name))
            continue
        have = [
            r["a"]
            for r in _rows(
                conn,
                f"SELECT attname AS a FROM pg_attribute WHERE attrelid = to_regclass('{schema}.{name}') "
                "AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
            )
        ]
        if have != list(cols):
            rep.diffs.append(("뷰 칸 다름", f"{name}: DB {have}"))
        elif view_have[name] != _norm(schema, text):
            rep.info.append(f"뷰 정의 글자 다름(판정 밖 — 칸은 같음, PostgreSQL 판마다 꼴이 다를 수 있음) {name}")
    for name in sorted(set(view_have) - set(view_want)):
        rep.diffs.append(("남는 뷰", name))
    return rep
