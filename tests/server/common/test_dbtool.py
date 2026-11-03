"""common.store.db.dbtool 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.db.dbtool --selftest`."""

from common.store.db.dbtool import MIGRATIONS, TARGETS, head, index_kind, known, standin_script, status


def selftest():
    import importlib.util

    from common.store.db.models import search_tables as ST

    sp = importlib.util.spec_from_file_location("s8a_base", MIGRATIONS / "versions" / "0001_search_base.py")
    base = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(base)
    assert base.HNSW_MAX == ST.HNSW_MAX  # 판 파일이 굳혀 둔 숫자 = 지금 pg.HNSW_MAX
    assert (
        TARGETS == ("search", "applog")
        and head("search") == "0003_search"
        and known("search") == ["0003_search", "0002_search", "0001_search"]
    )
    assert head("applog") == "0001_applog" and known("applog") == ["0001_applog"]
    assert not list((MIGRATIONS / "versions").glob("*struct*"))  # 사용자 11-01 — struct 갈래 없음(엔진 구성·원천 목록은 파일)
    print("[selftest] dbtool — 판 폴더 갈래 search 하나·끝 판·HNSW 2000 같음 통과")
    # 판 0002가 굳혀 둔 원천별 칸 = 지금 표 정의(pl-28 — 판 파일은 모델을 import하지 않으므로 여기서 대조)
    sp = importlib.util.spec_from_file_location("s_0002", MIGRATIONS / "versions" / "0002_search_doc_meta.py")
    m2 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m2)
    assert m2.SOURCES == ST.SOURCES and m2.HNSW_MAX == ST.HNSW_MAX
    for src in ST.SOURCES:
        assert m2.DOC_EXTRA_COLS[src] == [n for n, _ in ST.DOC_EXTRA[src]], src
        assert [c.split()[0] for c in m2.CHUNK_EXTRA.get(src, "").split(", ") if c] == [n for n, _ in ST.CHUNK_EXTRA.get(src, ())], src
        assert m2.view(src).replace(" ", "") == ST.view_sql(src).replace(" ", ""), src
    print("[selftest] dbtool — 판 0002 원천별 칸·뷰 = 표 정의(5벌) 통과")
    sp = importlib.util.spec_from_file_location("s_0003", MIGRATIONS / "versions" / "0003_doc_hints.py")
    m3 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m3)
    assert m3.DOC_HINTS_COLS == {k: [n for n, _ in v] for k, v in ST.DOC_HINTS.items()}
    print("[selftest] dbtool — 판 0003 분류 힌트 칸 = 표 정의 통과")
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
            assert got == {t.name: [c.name for c in t.columns] for t in md.sorted_tables} and views == set(ST.views_expected(src)), (
                src,
                got,
            )
            db.sqlite.close()
    assert ST.source_of("SFDC-test") == "sfdc" and ST.source_of("Other") == "other" and ST.source_of(None) == "other"
    assert ST.split_schema("ai_las") == ("ai", "las") and ST.split_schema("ai") == ("ai", None)
    print("[selftest] dbtool — 원천 스키마 SQLite 대역 5벌(표 5·뷰 1·칸 순서·vector(4096))·원천 이름 통과")
    assert index_kind(2000) == "HNSW 코사인" and index_kind(4096).startswith("이진")
    assert set(ST.index_defs(768)) == {"ix_{S}_chunk_doc", "ix_{S}_chunk_term_chunk", "ix_{S}_chunk_emb"}
    assert "ix_{S}_chunk_embq" in ST.index_defs(4096) and "bit(4096)" in ST.index_defs(4096)["ix_{S}_chunk_embq"]
    # 판 상태 판정(가짜 q)
    for have, want in (
        (None, "없음"),
        ([], "없음"),
        (["0003_search"], "끝"),
        (["0002_search"], "낮음"),
        (["0001_search"], "낮음"),
        (["9999_x"], "모름"),
        (["0003_search", "9999_x"], "모름"),
    ):
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


def test_all_keeps_applog_schema():  # PR #87 리뷰 — up --target all --schema demo가 applog 표를 검색 스키마에 만들지 않게
    from argparse import Namespace

    from common.store.db.dbtool import _schema_arg

    a = Namespace(target="all", schema="demo")
    assert _schema_arg(a, "search") == "demo" and _schema_arg(a, "applog") is None
    assert _schema_arg(Namespace(target="applog", schema="test_x"), "applog") == "test_x"
