"""e2-22 — 배포 판정의 DB 읽기 시험: 접속 · vector 확장 · 판 번호가 끝(검색·마스터·applog — dbtool.status) · 원천 스키마마다 표·색인 ·
검색 질의 1회. 운영 서버(prd)는 설정의 스키마를 읽기만 한다(세션을 읽기 전용으로 — 아무것도 쓰지 않음). local·dev는 같은 읽기를 임시 스키마
(`test_*` — 판 올리기로 만들고 시험 뒤 지움)에 한다. PG에 못 붙으면 FAIL(판정 명령이 PG에 닿아야 함)."""

from common.store.db import dbtool
from common.store.db.models import search_tables as ST
from common.store.pg import vec
from tests.server.common import pgcase


def _read(base, log):
    db = pgcase.connect(base)
    try:
        db.q("SET SESSION default_transaction_read_only = on")  # 이 세션은 쓰기 불가 — 운영 DB에 아무것도 남기지 않음
        assert db.q("SELECT 1 AS x FROM pg_extension WHERE extname = 'vector'"), "vector 확장 없음"
        srcs = ST.all_sources(base, db.q)
        versions = [("search", base), ("master", dbtool.schema_of("master", base)), ("applog", log)]
        versions += [("search", ST.src_schema(base, s)) for s in srcs if ST.is_dev(s)]  # DEV 원천은 그 스키마에 판 기록(prd는 없음)
        for target, schema in versions:
            st, have = dbtool.status(db.q, target, schema)
            assert st == "끝", f"{schema} 판 {st} {have} — 코드의 끝 판 {dbtool.head(target)}(migrate up 필요)"
        for src in srcs:
            sch = ST.src_schema(base, src)
            dim = dbtool.check_dim(db.q, sch, None)
            assert dim, f"{sch}.chunk 차원을 모름(표 없음)"
            tables = {r["t"] for r in db.q("SELECT table_name AS t FROM information_schema.tables WHERE table_schema = %s", (sch,))}
            want = {t.name for t in ST.search_metadata(sch, dim).sorted_tables} | {"v_chunk_source"}
            assert want <= tables, f"{sch}: 없는 표 {sorted(want - tables)}"
            idx = {r["i"] for r in db.q("SELECT indexname AS i FROM pg_indexes WHERE schemaname = %s", (sch,))}
            want_idx = {name.replace("{S}", sch) for name in ST.index_defs(dim)}
            assert want_idx <= idx, f"{sch}: 없는 색인 {sorted(want_idx - idx)}"
        sch = ST.src_schema(base, srcs[0])
        q = vec([1.0] * dbtool.check_dim(db.q, sch, None))
        db.q(f"SELECT chunk_id FROM {sch}.chunk ORDER BY embedding <=> %s::vector LIMIT 1", (q,))  # 검색 질의 1회(벡터)
    finally:
        db.cn.close()


def test_pg_read():
    if not pgcase.db_write_allowed():  # prd — 설정의 스키마를 읽기만
        db = pgcase.connect()
        base = db.schema
        db.cn.close()
        _read(base, dbtool.schema_of("applog"))
        return
    with pgcase.schema() as base:  # local·dev — 같은 읽기를 판 올린 임시 스키마에
        dbtool.upgrade_search(base, 4)
        log = dbtool.schema_of("applog", f"{base}_applog")
        dbtool.upgrade("applog", log)
        pgcase.fill_master(base)
        _read(base, log)


def test_no_docker_cli():
    """PC에 docker 명령이 없으면(FileNotFoundError) 시험 PG를 못 띄움 — False(→ 'PG에 붙지 못함' 메시지), 예외로 안 죽음."""
    from types import SimpleNamespace
    from unittest import mock

    for err in (FileNotFoundError("docker"), PermissionError("docker")):
        with (
            mock.patch("common.config.settings.cfg", return_value=SimpleNamespace(host=SimpleNamespace(pg_container="pgvector"))),
            mock.patch("common.core.paths.LOCAL_RUN", True),
            mock.patch("subprocess.run", side_effect=err),
        ):
            assert pgcase._start_local_pg({}) is False, err
