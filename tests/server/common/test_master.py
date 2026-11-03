"""pl-38(사용자 11-03) — 마스터 표 `<PG_SCHEMA>_master`: 판 0001_master ↔ 모델 칸 · 스키마 이름 · `master load`(한 트랜잭션·해시) ·
읽는 값이 옛 파일 로더와 같음 · 서버는 못 읽으면 멈춤 · gold_version 꼴. 임시 SQLite 대역만 — 외부 접속 없음."""

import importlib.util
import shutil
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from common.core import terms as T
from common.core.paths import GLOSSARY_ROOT
from common.store import master as M
from common.store import pg as PGC
from common.store.db import dbtool as D
from common.store.db.models.master_tables import TABLES, master_metadata


def _standin(d):
    """임시 대역 폴더 + 접속 정보 없음(PC) — 끝나면 되돌림."""
    M.reset()
    stack = [COMMON.env(PG_STANDIN_DIR=str(d), RUN_ENV="local"), mock.patch.object(PGC, "has_conn", return_value=False)]
    for c in stack:
        c.__enter__()
    return stack


def _close(stack):
    for c in reversed(stack):
        c.__exit__(None, None, None)
    M.reset()


def test_migration_matches_model():
    sp = importlib.util.spec_from_file_location("m0001", D.MIGRATIONS / "versions" / "0001_master_base.py")
    mig = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mig)
    assert mig.TABLES == TABLES  # 판이 굳힌 칸 = 모델
    assert set(master_metadata("x").tables) == {f"x.{n}" for n in (*TABLES, "master_meta")}
    for name, cols in TABLES.items():  # 표 칸 = git CSV 머리글
        head = tuple(
            h.strip().lstrip("﻿") for h in (GLOSSARY_ROOT / f"{name}.csv").read_text(encoding="utf-8-sig").splitlines()[0].split(",")
        )
        assert head == cols, (name, head)


def test_schema_names():
    cases = [  # (--target, --schema, 갈래 → 기대 스키마 인자)
        ("all", "demo", {"search": "demo", "applog": None, "master": "demo"}),
        ("master", "x", {"master": "x"}),
        ("applog", "test_a", {"applog": "test_a"}),
    ]
    for target, schema, want in cases:
        a = Namespace(target=target, schema=schema)
        assert {t: D._schema_arg(a, t) for t in want} == want, (target, schema)
    assert D.schema_of("master", "demo") == "demo_master" and D.head("master") == "0001_master"


def test_load_hash_and_transaction():
    d = Path(tempfile.mkdtemp())
    st = _standin(d)
    try:
        m1 = M.get()
        assert {n: len(r) for n, r in m1.tables.items()} == {n: len(M.read_csvs()[n]) for n in TABLES} and m1.hash == M.content_hash(
            M.read_csvs()
        )
        M.reset()
        assert M.get().hash == m1.hash  # 같은 CSV — 같은 해시(다시 읽어도)
        db = M._standin("ai")
        g = d / "g"
        shutil.copytree(GLOSSARY_ROOT, g)
        p = g / "id_patterns.csv"
        p.write_text(p.read_text(encoding="utf-8-sig") + "test_id,TST-\\d+,TST-1,,\n", encoding="utf-8")
        h2 = M.load(db, M.read_csvs(g))
        assert h2 != m1.hash and M.read(db).hash == h2 and len(M.read(db).rows("id_patterns")) == len(m1.rows("id_patterns")) + 1
        # 한 트랜잭션 — 중간에 실패하면 옛 내용 그대로
        real = db.cn.cursor
        calls = {"n": 0}

        def flaky():
            cur = real()
            ex = cur.execute

            def execute(sql, params=None):
                calls["n"] += 1
                if calls["n"] == 20:
                    raise RuntimeError("boom")
                return ex(sql, params)

            cur.execute = execute
            return cur

        with mock.patch.object(db.cn, "cursor", flaky):
            try:
                M.load(db)
                raise AssertionError("실패가 안 남")
            except RuntimeError:
                pass
        assert M.read(db).hash == h2  # 바뀌지 않음
    finally:
        _close(st)


def test_readers_same_as_files():
    d = Path(tempfile.mkdtemp())
    st = _standin(d)
    try:
        assert T.load_glossary() == T.load_glossary(GLOSSARY_ROOT)
        assert [(t, p.pattern) for t, p in T.load_id_patterns_typed()] == [
            (t, p.pattern) for t, p in T.load_id_patterns_typed(GLOSSARY_ROOT)
        ]
        old = {}  # 옛 _aliases: stack client_aliases + 명부 파일(read_roster) + 용어 사전 org_client
        for c, al in T.read_roster(GLOSSARY_ROOT / "client_roster.csv").items():
            old[c] = sorted(set(old.get(c, [])) | set(al))
        for r in T.load_glossary(GLOSSARY_ROOT).values():
            if "org_client" in T.split_terms(r.get("category")):
                al = [x for x in T.split_terms(r.get("synonyms")) + T.split_terms(r.get("abbreviations")) if not T._SHORT_EN.fullmatch(x)]
                old[r["canonical"]] = sorted(set(old.get(r["canonical"], [])) | set(al))
        assert T._aliases() == old
    finally:
        _close(st)


def test_server_refuses_and_empty_meta():
    d = Path(tempfile.mkdtemp())
    M.reset()
    with COMMON.env(PG_STANDIN_DIR=str(d), RUN_ENV="dev"), mock.patch.object(PGC, "has_conn", return_value=False):
        try:
            M.get()
            raise AssertionError("서버가 대역으로 시작함")
        except SystemExit:
            pass
    st = _standin(d)
    try:
        db = M._standin("ai")
        db.q(f"DELETE FROM {db.schema}.master_meta")
        try:
            M.read(db)
            raise AssertionError("빈 master_meta를 읽음")
        except SystemExit as e:
            assert "master load" in str(e)
    finally:
        _close(st)


def test_gold_version():
    from pipeline.load import pgvector_load as L
    from pipeline.load.parsing_meta import pipeline_version

    v = pipeline_version()
    cases = [({"master_hash": "58a24b0258b4a00772"}, f"{v}+m58a24b02"), ({}, v), (None, v)]
    for meta, want in cases:
        assert L.gold_version(meta) == want, (meta, L.gold_version(meta))
    assert len(f"{v}+m12345678") <= 64  # ParsingMeta gold_version NVARCHAR(64)


def test_standin_follows_csv_and_mcp_preload():
    """리뷰 — PC 대역은 git CSV가 바뀌면 다시 채움(옛 명부로 남지 않게) · 검색 MCP는 검색기를 만들 때 마스터를 미리 읽어, 못 읽으면 RuntimeError."""
    d = Path(tempfile.mkdtemp())
    st = _standin(d)
    try:
        h1 = M.get().hash
        g = d / "g"
        shutil.copytree(GLOSSARY_ROOT, g)
        p = g / "units.csv"
        p.write_text(p.read_text(encoding="utf-8-sig") + "zz,zz,length,,,\n", encoding="utf-8")
        changed = M.read_csvs(g)
        with mock.patch.object(M, "read_csvs", lambda folder=None: changed):
            M.reset()
            h2 = M.get().hash
        assert h2 != h1 and h2 == M.content_hash(changed), (h1, h2)
        M.reset()
        assert M.get().hash == h1  # 원래 CSV로 돌아오면 다시 맞춤
    finally:
        _close(st)
    from mcp_server.services.search import server_state as SS

    with mock.patch.object(SS, "check_store", lambda: None), mock.patch.object(M, "get", side_effect=SystemExit("[master] 비어 있음")):
        try:
            SS._build_retriever()
            raise AssertionError("마스터 못 읽는데 검색기를 만듦")
        except RuntimeError as e:
            assert "master" in str(e)
