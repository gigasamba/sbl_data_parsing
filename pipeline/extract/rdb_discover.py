#!/usr/bin/env python3
"""SI41 ⑤ — 원천 표 열 자동 탐색(읽기 전용, INFORMATION_SCHEMA) → `common/sources.json` 초안 출력.

서버 LLM·사람이 표·열 **이름만** 보고(값·행 내용은 전혀 읽지 않음) sources.json에 더할 항목을 만든다. 이름 규칙
(s3_key·object_path·object_key → key · id·file_id → doc_id · original_filename·file_name → filename · file_size·
size_bytes·size → size · updated_at·mod_seq·id → increment)으로 맞춰 보고, 못 맞춘 필수 열은 `_missing_columns`로
표시(그 열은 사람이 sources.json에서 직접 채움) — bucket·enabled는 늘 빈 값·false로 출력(사람이 검토 후 채움).

사용:
  python cli/rdb_discover.py --like "FileStorageMap%"        # RDB_ENGINE(기본 mssql) · 접속은 common.connections.rdb 읽기 계정
  python cli/rdb_discover.py --from-csv <경로> [--table <이름>]  # 시험용 — RDB 없이 csv 머리글만 열로(행 값은 안 읽음)

접속(실제 질의일 때만): RDB_ENGINE(기본 mssql, common/sources.py와 무관 — pipeline/extract/fetch_docs.py와 같은 env) ·
mssql(pymssql) common.connections.rdb(RDB_HOST·RDB_PORT·RDB_DATABASE·RDB_READ_USER·RDB_READ_PASSWORD·RDB_CONNECT_KWARGS) · pg는 common/pg.py 재사용.
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서
from common.core.console import utf8_stdout

# isort: split
import argparse
import csv
import json
from pathlib import Path

from common.core.paths import PKG_ROOT  # 공용 자산 루트(10-14 이미지 단위 분리)

ROOT = PKG_ROOT
from common.store.parsing_meta_db import TABLE_ID_RE  # noqa: E402 — 표 이름 화이트리스트(옛 common.core.sources와 같은 규칙)
from pipeline import config as pc  # noqa: E402 — S7c: 설정 객체(pipeline 칸)

NAME_RULES = (
    (("s3_key", "object_path", "object_key"), "key"),
    (("id", "file_id"), "doc_id"),
    (("original_filename", "file_name"), "filename"),
    (("file_size", "size_bytes", "size"), "size"),
)
INCREMENT_RULES = ("updated_at", "mod_seq", "id")
REQUIRED_COLUMNS = ("doc_id", "key", "filename", "size", "increment")


def _map_columns(col_names):
    """열 이름 목록 → sources.json columns 초안(이름 규칙, 대소문자 무시) — 값은 전혀 안 봄."""
    mapping = {}
    for col in col_names:
        low = col.lower()
        for names, field in NAME_RULES:
            if low in names and field not in mapping:
                mapping[field] = col
    for inc in INCREMENT_RULES:
        hit = next((c for c in col_names if c.lower() == inc), None)
        if hit:
            mapping["increment"] = hit
            break
    return mapping


def _draft(table, col_names):
    cols = _map_columns(col_names)
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    out = {"name": table.split(".")[-1], "table": table, "bucket": "", "enabled": False, "columns": cols}
    if missing:
        out["_missing_columns"] = missing  # 사람이 직접 채울 열 — sources.json에 올리기 전에 지워야 함
    return out


def _from_csv(path, table):
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    return [_draft(table, header)]


_COLS_SQL = "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION"


def _mssql_tables(like):
    """S8b — 연결·질의는 SQLAlchemy(source.rdb_connect·mssql.rows — SQL 글자 그대로)."""
    from common.store import mssql
    from pipeline.extract.fetch_docs import rdb_connect

    with rdb_connect() as cn:
        drafts = []
        rows = mssql.rows(cn, "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE %s", (like,))
        for schema, tname in [(r["TABLE_SCHEMA"], r["TABLE_NAME"]) for r in rows]:
            table_id = f"{schema}.{tname}"
            if not TABLE_ID_RE.match(table_id):
                continue  # 식별자 화이트리스트 밖(이름 자체가 비정상) — 안전 쪽으로 건너뜀
            cols = [r["COLUMN_NAME"] for r in mssql.rows(cn, _COLS_SQL, (schema, tname))]
            drafts.append(_draft(table_id, cols))
        return drafts


def table_columns(table):
    """원천 표의 열 이름(값·행은 안 읽음 — S8b set-sources --check-columns, Q9). csv:<경로>면 머리글, RDB_ENGINE=pg면 information_schema,
    mssql(기본)이면 INFORMATION_SCHEMA(SQLAlchemy — source.rdb_connect). 표가 없으면 []."""
    if table.startswith("csv:"):
        f = Path(table[4:])
        if not f.is_file():
            return []
        with open(f, encoding="utf-8-sig", newline="") as fh:
            return next(csv.reader(fh), [])
    schema, _, bare = table.rpartition(".")
    if pc.cfg().connections.rdb.engine == "pg":
        from common.store.pg import PG, conf

        return [
            r["column_name"]
            for r in PG(conf()).q(
                "SELECT column_name FROM information_schema.columns WHERE lower(table_schema)=lower(%s) AND lower(table_name)=lower(%s) "
                "ORDER BY ordinal_position",  # 따옴표 없이 만든 표는 소문자로 저장(_pg_tables의 ILIKE와 같게)
                [schema or "public", bare],
            )
        ]
    from common.store import mssql
    from pipeline.extract.fetch_docs import rdb_connect

    with rdb_connect() as cn:
        if schema:
            return [r["COLUMN_NAME"] for r in mssql.rows(cn, _COLS_SQL, (schema, bare))]
        return [
            r["COLUMN_NAME"]
            for r in mssql.rows(
                cn, "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (bare,)
            )
        ]


def _pg_tables(like):
    from common.store.pg import PG, conf

    db = PG(conf())
    rows = db.q("SELECT table_schema, table_name FROM information_schema.tables WHERE table_name ILIKE %s", [like])
    drafts = []
    for r in rows:
        schema, tname = r["table_schema"], r["table_name"]
        table_id = f"{schema}.{tname}"
        if not TABLE_ID_RE.match(table_id):
            continue
        cols = [
            c["column_name"]
            for c in db.q(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                [schema, tname],
            )
        ]
        drafts.append(_draft(table_id, cols))
    return drafts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--like", default="FileStorageMap%", help="표 이름 패턴(SQL LIKE, 기본 FileStorageMap%%)")
    ap.add_argument("--from-csv", help="시험용 — RDB 대신 csv 머리글만 읽어 열 이름으로(행 값은 안 읽음)")
    ap.add_argument("--table", help="--from-csv일 때 표 이름(기본 파일 이름)")
    a = ap.parse_args(argv)
    if a.from_csv:
        table = a.table or Path(a.from_csv).stem
        drafts = _from_csv(a.from_csv, table)
    else:
        engine = pc.cfg().connections.rdb.engine  # S7c — 설정 객체(blank keep: 옛 `get(X, "mssql")` — `RDB_ENGINE=`은 '' 유지)
        drafts = _pg_tables(a.like) if engine == "pg" else _mssql_tables(a.like)
    print(json.dumps(drafts, ensure_ascii=False, indent=1))
    return drafts


if __name__ == "__main__":
    utf8_stdout()
    main()
