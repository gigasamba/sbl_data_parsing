"""시험 도우미 — 실 pgvector 임시 스키마(tests/server/common/pgcase — test_*, 시험 뒤 지움)에 gold를 만든다(e2-22).
- gold(dim): 임시 기준 스키마 + 검색 판(원천 5벌)·마스터(git CSV)·applog(`<기준>_applog` — 적재·게시가 쓰는 예외 기록을 거기로) — prd면 SKIP.
- seed(rows): gold `doc` 행(op-17 처리 기록)을 심는다(gold() 또는 pgcase.schema() 안에서)."""

from contextlib import contextmanager
from unittest.mock import patch

from common.store.db import dbtool
from common.store.db.models import search_tables as ST
from tests.server.common import pgcase


@contextmanager
def gold(dim=4, **names):
    from pipeline.shared import except_docs

    with pgcase.with_master(**names) as base:
        dbtool.upgrade_search(base, dim)
        log = applog(base)
        with patch.object(except_docs, "_schema", lambda: log):
            yield base


def applog(base):
    """`<base>_applog`에 applog 판 올리기 — 이름(test_* 만 허용 — dbtool.schema_of)."""
    log = dbtool.schema_of("applog", f"{base}_applog")
    dbtool.upgrade("applog", log)
    return log


def seed(rows, dim=4):
    """rows = [{file_path, source_system?(기본 SFDC), sha256?, parse_status?(기본 ok)}] — 그 원천 스키마의 doc에 한 행씩."""
    db = pgcase.connect()
    base = db.schema
    assert base.startswith("test_"), base  # 시험 스키마에만 심음
    try:
        dbtool.upgrade("search", base, dim)
        for src in ST.dev_order({ST.source_of(r.get("source_system", "SFDC")) for r in rows} - set(ST.SOURCES)):
            dbtool.upgrade("search", base, dim, src=src)  # DEV 원천 스키마(dbtool up이 만드는 것과 같게)
        for r in rows:
            schema = ST.src_schema(base, ST.source_of(r.get("source_system", "SFDC")))
            db.q(
                f"INSERT INTO {schema}.doc (file_path, sha256, parse_status) VALUES (%s, %s, %s)",
                (r["file_path"], r.get("sha256"), r.get("parse_status", "ok")),
            )
    finally:
        db.cn.close()
