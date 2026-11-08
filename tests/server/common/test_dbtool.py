"""common.store.db.dbtool 자기 점검."""

from common.store.db.dbtool import MIGRATIONS, TARGETS, head, index_kind, known, standin_script, status


def selftest():
    import importlib.util

    from common.store.db.models import search_tables as ST

    sp = importlib.util.spec_from_file_location("s8a_base", MIGRATIONS / "versions" / "0001_search_base.py")
    base = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(base)
    assert base.HNSW_MAX == ST.HNSW_MAX  # 판 파일이 굳혀 둔 숫자 = 지금 pg.HNSW_MAX
    assert (
        TARGETS == ("search", "applog", "master")
        and head("search") == "0007_search"
        and known("search") == ["0007_search", "0006_search", "0005_search", "0004_search", "0003_search", "0002_search", "0001_search"]
    )
    assert head("applog") == "0004_applog" and known("applog") == ["0004_applog", "0003_applog", "0002_applog", "0001_applog"]
    assert head("master") == "0002_master" and known("master") == ["0002_master", "0001_master"]
    assert not list((MIGRATIONS / "versions").glob("*struct*"))  # struct 갈래 없음(엔진 구성·원천 목록은 파일)
    print("[selftest] dbtool — 판 폴더 갈래 search 하나·끝 판·HNSW 2000 같음 통과")
    # 판 0002가 굳혀 둔 원천별 칸 = 지금 표 정의(pl-28 — 판 파일은 모델을 import하지 않으므로 여기서 대조)
    sp = importlib.util.spec_from_file_location("s_0002", MIGRATIONS / "versions" / "0002_search_doc_meta.py")
    m2 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m2)
    assert m2.SOURCES == ST.SOURCES and m2.HNSW_MAX == ST.HNSW_MAX
    for src in ST.SOURCES:
        assert [c.split()[0] for c in m2.CHUNK_EXTRA.get(src, "").split(", ") if c] == [n for n, _ in ST.CHUNK_EXTRA.get(src, ())], src
    print("[selftest] dbtool — 판 0002 청크 칸 = 표 정의(5벌) 통과")
    sp = importlib.util.spec_from_file_location("s_0003", MIGRATIONS / "versions" / "0003_doc_hints.py")
    m3 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m3)
    sp = importlib.util.spec_from_file_location("s_0004", MIGRATIONS / "versions" / "0004_doc_embed.py")
    m4 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m4)
    assert m4.SOURCES == ST.SOURCES and m4.DOC_META_COLS == [n for n, _ in ST.DOC_META]
    print("[selftest] dbtool — 판 0004 문서 날짜·임베딩 모델 칸 = 표 정의 통과")
    # 판 0005(pl-52) — 지우는 칸 = 판 0002 원천 전용 + 판 0003 힌트 · 새 뷰 = 표 정의 · 되돌린 뷰 = 판 0002 뷰 · doc 칸 순서 · GIN 색인
    sp = importlib.util.spec_from_file_location("s_0005", MIGRATIONS / "versions" / "0005_doc_attrs.py")
    m5 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m5)
    flat = lambda s: s.replace(" ", "")
    assert m5.SOURCES == ST.SOURCES and m5.down_revision == m4.revision
    for src in ST.SOURCES:
        extra = [n for n, _ in m5.OLD_EXTRA.get(src, ())]
        assert extra == m2.DOC_EXTRA_COLS[src] and [n for n, _ in m5.OLD_HINTS.get(src, ())] == m3.DOC_HINTS_COLS.get(src, []), src
        assert flat(m5.view(src, ("attrs",))) == flat(ST.view_sql(src)) and flat(m5.view(src, extra)) == flat(m2.view(src)), src
    assert ST.index_defs(768)["ix_{S}_doc_attrs"].endswith("USING gin (attrs)")
    print("[selftest] dbtool — 판 0005 attrs(지우는 칸·뷰·되돌린 뷰·GIN) = 표 정의 통과")
    # 판 0006(op-17) — doc 처리 기록 칸 = 표 정의 DOC_RECORD · doc 칸 순서(판이 더한 순서)
    sp = importlib.util.spec_from_file_location("s_0006", MIGRATIONS / "versions" / "0006_doc_record.py")
    m6 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m6)
    assert m6.SOURCES == ST.SOURCES and m6.down_revision == m5.revision and m6.DOC_RECORD_COLS == [n for n, _ in ST.DOC_RECORD]
    for src in ST.SOURCES:
        assert ST.doc_columns(src) == ["doc_id", "file_path", *m5.VIEW_DOC, *m4.DOC_META_COLS, "attrs", *m6.DOC_RECORD_COLS], src
    print("[selftest] dbtool — 판 0006 처리 기록 칸·doc 칸 순서 = 표 정의 통과")
    # 판 0007(op-17) — doc 찾기용 색인 이름·칸 = 표 정의 DOC_INDEX
    sp = importlib.util.spec_from_file_location("s_0007", MIGRATIONS / "versions" / "0007_doc_index.py")
    m7 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m7)
    assert m7.SOURCES == ST.SOURCES and m7.down_revision == m6.revision
    assert m7.DOC_INDEX == ST.DOC_INDEX
    assert ST.index_defs(768)["ix_{S}_doc_silver"] == "CREATE INDEX ix_{S}_doc_silver ON {S}.doc USING btree (silver_bucket, silver_key)"
    print("[selftest] dbtool — 판 0007 doc 색인(sha256·silver 위치·file_path) = 표 정의 통과")
    # 원천 스키마 SQLite 대역 — 표 정의에서 만든 DDL을 pg_standin이 받음(칸 순서·차원 글자 vector(n) 그대로)
    import tempfile

    from common.config.settings import COMMON
    from common.store import pg_standin as PS

    with COMMON.env(PG_STANDIN_DIR=tempfile.mkdtemp()):
        for src in ST.SOURCES:
            sch = ST.src_schema("orca_s8a_t", src)
            db = PS.StandinPG(sch)
            with db.cn.cursor() as cur:
                cur.execute(standin_script(sch, 4096))
            assert PS._dim_of(db) == 4096
            got = {
                n: [r[1] for r in db.sqlite.execute(f"PRAGMA table_info({n})")]
                for (n,) in db.sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            views = {n for (n,) in db.sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
            md = ST.search_metadata(sch, 4096)
            assert got == {t.name: [c.name for c in t.columns] for t in md.sorted_tables} and views == {"v_chunk_source"}, (
                src,
                got,
            )
            db.sqlite.close()
    assert ST.source_of("SFDC-test") == "sfdc" and ST.source_of("Other") == "other" and ST.source_of(None) == "other"
    assert ST.split_schema("ai_las") == ("ai", "las") and ST.split_schema("ai") == ("ai", None)
    print("[selftest] dbtool — 원천 스키마 SQLite 대역 5벌(표 5·뷰 1·칸 순서·vector(4096))·원천 이름 통과")
    assert index_kind(2000) == "HNSW 코사인" and index_kind(4096).startswith("이진")
    assert set(ST.index_defs(768)) == {
        "ix_{S}_doc_attrs",
        "ix_{S}_doc_sha256",
        "ix_{S}_doc_silver",
        "ix_{S}_doc_path",
        "ix_{S}_chunk_doc",
        "ix_{S}_chunk_term_chunk",
        "ix_{S}_chunk_emb",
    }
    assert "ix_{S}_chunk_embq" in ST.index_defs(4096) and "bit(4096)" in ST.index_defs(4096)["ix_{S}_chunk_embq"]
    # 판 상태 판정(가짜 q)
    for have, want in (
        (None, "없음"),
        ([], "없음"),
        (["0007_search"], "끝"),
        (["0006_search"], "낮음"),
        (["0005_search"], "낮음"),
        (["0004_search"], "낮음"),
        (["0003_search"], "낮음"),
        (["0002_search"], "낮음"),
        (["0001_search"], "낮음"),
        (["9999_x"], "모름"),
        (["0007_search", "9999_x"], "모름"),
    ):
        fq = (
            lambda h: lambda sql, p=None: ([{"x": 1}] if h is not None else []) if "to_regclass" in sql else [{"version_num": v} for v in h]
        )(have)
        assert status(fq, "search", "ai")[0] == want, (have, status(fq, "search", "ai"))
    print("[selftest] dbtool — 색인 종류(차원 2,000 경계)·판 상태 판정(없음·끝·모름·끝+모름 섞임) 통과")
    return 0


def test_main():
    selftest()


def test_all_keeps_applog_schema():  # up --target all --schema demo가 applog 표를 검색 스키마에 만들지 않게
    from argparse import Namespace

    from common.store.db.dbtool import _schema_arg

    a = Namespace(target="all", schema="demo")
    assert _schema_arg(a, "search") == "demo" and _schema_arg(a, "applog") is None
    assert _schema_arg(Namespace(target="applog", schema="test_x"), "applog") == "test_x"


def test_applog_schema_only_applog():  # --target applog --schema <검색 스키마>가 applog 표를 엉뚱한 스키마에 만들지 않게(쓰는 쪽은 늘 applog)
    import contextlib
    import io

    from common.store.db.dbtool import DbToolError, main, schema_of

    for given, want in ((None, "applog"), ("applog", "applog"), ("test_applog_ab12", "test_applog_ab12")):
        assert schema_of("applog", given) == want, given
    for call in (
        *(lambda b=b: schema_of("applog", b) for b in ("demo", "data_parsing", "public", "Applog", "test-x")),
        lambda: main(["up", "--target", "applog", "--schema", "demo"]),  # CLI는 PG 접속 확인보다 먼저 거부
    ):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                call()
            raise AssertionError("거부해야 함")
        except DbToolError as e:
            assert e.code == 2 and "applog 스키마에만" in err.getvalue(), err.getvalue()


# up --sql(DB 없이 SQL만) — (인자, 들어 있어야 할 글자, 없어야 할 글자)
UP_SQL = [
    (
        ["--target", "applog"],
        [
            "CREATE TABLE applog.alembic_version",
            "CREATE TABLE applog.except_doc_info",
            "PARTITION OF applog.pipe_event",
            "ALTER TABLE applog.pipe_event ADD COLUMN source_system TEXT;",
            "ADD COLUMN file_ext TEXT",
            "-- 수동: 월 파티션",
            "COMMIT;",
        ],
        [],
    ),
    (
        ["--target", "applog", "--from", "0003_applog"],  # 있는 DB — 0003 → 0004만
        ["ALTER TABLE applog.except_doc_info ADD COLUMN file_ext TEXT, ADD COLUMN file_size BIGINT", "SET version_num='0004_applog'"],
        ["CREATE TABLE applog.except_doc_info", "CREATE TABLE applog.alembic_version"],
    ),
    (
        ["--target", "search", "--schema", "demo", "--dim", "768"],
        [
            "CREATE SCHEMA IF NOT EXISTS demo;",
            "demo_sfdc.chunk",
            "vector(768)",
            "SET version_num='0007_search'",
            "CREATE INDEX IF NOT EXISTS ix_demo_sfdc_doc_sha256 ON demo_sfdc.doc (sha256);",
            "-- 수동: vector 확장",
        ],
        ["applog."],
    ),
    (["--target", "master", "--schema", "demo"], ["CREATE TABLE demo_master.master_meta", "demo_master.alembic_version"], []),
]


def test_up_sql():
    import contextlib
    import io
    import tempfile
    from pathlib import Path
    from unittest import mock

    from common.store import pg
    from common.store.db import dbtool

    no_db = mock.Mock(side_effect=AssertionError("DB에 붙음"))
    with tempfile.TemporaryDirectory() as d, mock.patch.object(dbtool, "engine", no_db), mock.patch.object(pg, "has_conn", no_db):
        for args, has, hasnt in UP_SQL:
            out = Path(d) / "up.sql"
            with contextlib.redirect_stdout(io.StringIO()):
                assert dbtool.main(["up", "--sql", str(out), *args]) == 0, args
            sql = out.read_text(encoding="utf-8")
            assert all(s in sql for s in has) and not any(s in sql for s in hasnt), (args, [s for s in has if s not in sql])


# up --sql 거부 — (인자, 안내 글자): 실패하면 파일을 남기지 않는다
UP_SQL_REJECT = [
    (["--target", "search", "--schema", "demo"], "차원이 필요"),  # 빈 스키마부터(0001·0002가 차원을 읽음)
    (["--target", "search", "--schema", "demo", "--from", "0001_search"], "차원이 필요"),  # 0002가 남음
    (["--target", "applog", "--from", "0005_search"], "고른 갈래"),  # 고르지 않은 갈래의 판
    (["--target", "all", "--schema", "demo", "--from", "nope"], "고른 갈래"),
]


def test_up_sql_rules():
    import contextlib
    import io
    import re
    import tempfile
    from pathlib import Path
    from unittest import mock

    from common.store import pg
    from common.store.db import dbtool

    for f in sorted((MIGRATIONS / "versions").glob("*.py")):  # 차원을 읽는 판 = NEEDS_DIM
        rev = re.search(r'^revision = "([^"]+)"', f.read_text(encoding="utf-8"), re.M).group(1)
        assert ('["dim"]' in f.read_text(encoding="utf-8")) == (rev in dbtool.NEEDS_DIM), rev
    no_pg = mock.Mock(side_effect=AssertionError("접속 정보를 읽음"))
    with tempfile.TemporaryDirectory() as d, mock.patch.object(pg, "conf", no_pg), mock.patch.object(dbtool, "engine", no_pg):
        out = Path(d) / "up.sql"
        for args, msg in UP_SQL_REJECT:
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    dbtool.main(["up", "--sql", str(out), *args])
                raise AssertionError(f"거부해야 함: {args}")
            except dbtool.DbToolError as e:
                assert e.code == 2 and msg in err.getvalue(), (args, err.getvalue())
            assert not list(Path(d).iterdir()), args  # 반쯤 쓴 파일 없음
        err = io.StringIO()  # 스키마 이름은 설정 기본값(접속 정보 없이) · --from 없는 갈래는 경고 줄 + 주석
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            assert dbtool.main(["up", "--sql", str(out), "--target", "all", "--dim", "8", "--from", "0003_applog"]) == 0
        sql = out.read_text(encoding="utf-8")
        assert "빈 스키마부터" in err.getvalue() and sql.count("-- 주의:") == 2 and ";;" not in sql, err.getvalue()
        assert "CREATE TABLE applog.except_doc_info" not in sql and "\r" not in out.read_bytes().decode("utf-8")
        assert [p.name for p in Path(d).iterdir()] == ["up.sql"]
