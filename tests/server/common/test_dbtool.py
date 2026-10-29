"""common.store.db.dbtool 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.db.dbtool --selftest`."""

from common.store.db.dbtool import MIGRATIONS, STRUCT, head, index_kind, known, standin_script, status


def selftest():
    import importlib.util
    import sqlite3

    from common.store import structdb as SDB
    from common.store.db.models import search_tables as ST
    from common.store.db.models import struct_tables as SS
    from common.store.db.schemas import search_rows as SR
    from common.store.db.schemas import struct_rows as SRW

    sp = importlib.util.spec_from_file_location("s8a_base", MIGRATIONS / "versions" / "0001_search_base.py")
    base = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(base)
    assert STRUCT == SDB.STRUCT_SCHEMA == SS.SCHEMA and base.HNSW_MAX == ST.HNSW_MAX  # 판 파일이 굳혀 둔 숫자 = 지금 pg.HNSW_MAX
    assert head("search") == "0001_search" and head("struct") == "0002_struct", (head("search"), head("struct"))
    assert known("search") == ["0001_search"] and known("struct") == ["0002_struct", "0001_struct"]
    sp2 = importlib.util.spec_from_file_location("s8b_cfg", MIGRATIONS / "versions" / "0002_struct_config.py")
    v2 = importlib.util.module_from_spec(sp2)
    sp2.loader.exec_module(v2)
    from common.store.db import cfgtables

    for kind, (table, seed_file) in zip(("stack", "sources"), v2.SEEDS):
        name, reason, body = cfgtables.seed(kind)  # 시드 모양 검사(pydantic) 통과
        assert table == cfgtables.KINDS[kind] and seed_file == f"0002_{kind}_seed.json" and v2._sha(body) == cfgtables.sha(body)
    print(
        "[selftest] dbtool — 판 폴더 갈래 2개(search·struct)·끝 판(struct 0002 — 판 표 S8b)·이름 상수(struct·HNSW 2000)·시드 모양·sha 규칙 같음 통과"
    )
    # pydantic 행 모델 칸 = SQLAlchemy 표 칸(이름·순서·필수 여부)
    pairs = [(ST.search_metadata("ai", 8), SR.ROWS), (SS.struct_metadata(), SRW.ROWS)]
    n = 0
    for md, rows in pairs:
        assert set(rows) == {t.name for t in md.sorted_tables}, (set(rows), [t.name for t in md.sorted_tables])
        for t in md.sorted_tables:
            fields = rows[t.name].model_fields
            assert list(fields) == [c.name for c in t.columns], (t.name, list(fields))
            for c in t.columns:
                serial = (
                    c.primary_key and len(t.primary_key.columns) == 1 and c.autoincrement in ("auto", True) and c.type.python_type is int
                )
                need = not c.nullable and c.server_default is None and not serial  # 필수 = NOT NULL·기본값 없음·SERIAL 아님
                assert fields[c.name].is_required() == need, (t.name, c.name, fields[c.name].is_required(), need)
            n += 1
    print(f"[selftest] dbtool — pydantic 행 모델 칸 = SQLAlchemy 표 칸(표 {n}개 — 이름·순서·필수 여부) 통과")
    # struct 표 정의 = structdb의 SQLite DDL 글자(Q7 — structdb는 이 패키지를 import 안 함, 여기서 고정)
    cn = sqlite3.connect(":memory:")
    for stmt in SDB.SCHEMA + SDB.REGISTRY_SCHEMA + SDB.TABLE_SCHEMA:
        cn.execute(stmt)
    md = SS.struct_metadata()
    sqlite_tables = [t for t in md.sorted_tables if t.name not in SS.CONFIG_TABLES]  # 판 표(S8b)는 PostgreSQL에만 — PC는 파일
    assert (
        {r[0] for r in cn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == set(SS.TABLES) == {t.name for t in sqlite_tables}
    )
    assert {t.name for t in md.sorted_tables} == set(SS.TABLES) | set(SS.CONFIG_TABLES)
    for t in sqlite_tables:
        info = [(r[1], r[2].upper(), bool(r[3]), r[5]) for r in cn.execute(f"PRAGMA table_info({t.name})")]
        want = [
            (
                c.name,
                "INTEGER" if c.type.python_type is int else "TEXT",
                not c.nullable and not (c.primary_key and len(t.primary_key.columns) == 1),
                [p.name for p in t.primary_key.columns].index(c.name) + 1 if c.primary_key else 0,
            )
            for c in t.columns
        ]
        assert info == want, (t.name, info, want)
    idx = {r[0]: r[1] for r in cn.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
    assert set(idx) == set(SS.INDEX_DEFS) == {i.name for t in sqlite_tables for i in t.indexes}, idx
    assert {i.name for t in md.sorted_tables if t.name in SS.CONFIG_TABLES for i in t.indexes} | {
        f"{t}_body_sha_key" for t in SS.CONFIG_TABLES
    } == set(SS.CONFIG_INDEX_DEFS)
    assert {g: SS.GROUPS[g] for g in SS.GROUPS} == {
        "base": tuple(SDB._ddl_tables(SDB.SCHEMA)),
        "registry": tuple(SDB._ddl_tables(SDB.REGISTRY_SCHEMA)),
        "cells": tuple(SDB._ddl_tables(SDB.TABLE_SCHEMA)),
    }
    print("[selftest] dbtool — struct 표 정의 = structdb SQLite DDL(표 10·칸·형식·NOT NULL·기본 키·색인 2·묶음 3) 통과")
    # 검색 스키마 SQLite 대역 — 표 정의에서 만든 DDL을 pg_standin이 받음(칸 순서·차원 글자 vector(n) 그대로)
    import tempfile

    from common.config.settings import COMMON
    from common.store import pg_standin as PS

    with COMMON.env(PG_STANDIN_DIR=tempfile.mkdtemp()):
        db = PS.StandinPG("orca_s8a_t")
        with db.cn.cursor() as cur:
            cur.execute(standin_script("orca_s8a_t", 4096))
        assert PS._dim_of(db) == 4096
        got = {
            n: [r[1] for r in db.sqlite.execute(f"PRAGMA table_info({n})")]
            for (n,) in db.sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        views = {
            n for (n,) in db.sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
        }  # 대역은 regexp_replace가 없어 뷰를 읽지는 못함(전과 같음)
    md = ST.search_metadata("orca_s8a_t", 4096)
    assert got == {t.name: [c.name for c in t.columns] for t in md.sorted_tables} and views == set(ST.VIEWS_EXPECTED), (got, views)
    print("[selftest] dbtool — 검색 스키마 SQLite 대역(표 정의 → pg_standin: 표 6·뷰 1·칸 순서·vector(4096)) 통과")
    assert index_kind(2000) == "HNSW 코사인" and index_kind(4096).startswith("이진")
    assert set(ST.index_defs(768)) == {"ix_{S}_chunk_doc", "ix_{S}_chunk_term_chunk", "ix_{S}_chunk_clients", "ix_{S}_chunk_emb"}
    assert "ix_{S}_chunk_embq" in ST.index_defs(4096) and "bit(4096)" in ST.index_defs(4096)["ix_{S}_chunk_embq"]
    # 판 상태 판정(가짜 q)
    for have, want in ((None, "없음"), ([], "없음"), (["0001_search"], "끝"), (["9999_x"], "모름"), (["0001_search", "9999_x"], "모름")):
        fq = (
            lambda h: lambda sql, p=None: ([{"x": 1}] if h is not None else []) if "to_regclass" in sql else [{"version_num": v} for v in h]
        )(have)
        assert status(fq, "search", "ai")[0] == want, (have, status(fq, "search", "ai"))
    from sqlalchemy import DefaultClause, text

    from common.store.db.dbcompare import _text

    assert _text(DefaultClause(text("now()"))) == "now()" and _text("1") == "1" and _text(None) == "None"  # 기본값 다름 문구(VS8a R-2)
    print("[selftest] dbtool — 색인 종류(차원 2,000 경계)·판 상태 판정(없음·끝·모름·끝+모름 섞임)·기본값 문구 통과")
    return 0


def test_main():  # 옛 `--selftest` 갈래(`if a.selftest: return selftest()`)
    selftest()
