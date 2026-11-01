"""common.store.db.dbtool 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.db.dbtool --selftest`."""

from common.store.db.dbtool import MIGRATIONS, TARGETS, head, index_kind, known, standin_script, status


def selftest():
    import importlib.util

    from common.store.db.models import search_tables as ST
    from common.store.db.schemas import search_rows as SR

    sp = importlib.util.spec_from_file_location("s8a_base", MIGRATIONS / "versions" / "0001_search_base.py")
    base = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(base)
    assert base.HNSW_MAX == ST.HNSW_MAX  # 판 파일이 굳혀 둔 숫자 = 지금 pg.HNSW_MAX
    assert TARGETS == ("search", "applog") and head("search") == "0001_search" and known("search") == ["0001_search"]
    assert head("applog") == "0001_applog" and known("applog") == ["0001_applog"]
    assert not list((MIGRATIONS / "versions").glob("*struct*"))  # 사용자 11-01 — struct 갈래 없음(엔진 구성·원천 목록은 파일)
    print("[selftest] dbtool — 판 폴더 갈래 search 하나·끝 판·HNSW 2000 같음 통과")
    # pydantic 행 모델 칸 = SQLAlchemy 표 칸(이름·순서·필수 여부)
    pairs = [(ST.search_metadata("ai", 8), SR.ROWS)]
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
