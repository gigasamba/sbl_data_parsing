"""pl-14 — pgvector_load.backfill_chunk_clients가 10-20 축소 스키마 doc 표(client 열 없음, clients JSON TEXT만)에서 돈다.
전에는 d.client를 읽어 실 PG에서 deploy()가 오류로 멈췄다(night·load_module·run_stack이 적재 전에 멈춤)."""

import importlib
import re

from pipeline.load.pgvector_load import backfill_chunk_clients


def _doc_cols():
    """검색 스키마 기준판(0001_search_base)의 doc 표 열 이름 — 시험이 실제 표 정의를 따라가게."""
    sql = importlib.import_module("common.store.db.migrations.versions.0001_search_base").SCHEMA_SQL
    body = sql.split("CREATE TABLE IF NOT EXISTS {S}.doc (", 1)[1].split(");", 1)[0]
    return {m.group(1) for m in re.finditer(r"^\s*(\w+)\s+\w", body, re.M)}


class _Cur:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sink.append(params)


class _DB:
    """doc 표에 없는 열(d.<열>)을 읽으면 실 PG처럼 오류."""

    schema = "ai"

    def __init__(self, cols):
        self.cols, self.updates = cols, []
        self.cn = self

    def q(self, sql, params=None):
        bad = set(re.findall(r"\bd\.(\w+)", sql)) - self.cols
        if bad:
            raise RuntimeError(f"column d.{sorted(bad)[0]} does not exist")
        return [{"doc_id": 1, "clients": '["A사", "B사"]'}, {"doc_id": 2, "clients": None}]

    def transaction(self):
        return _Cur([])

    def cursor(self):
        return _Cur(self.updates)


def test_backfill_reduced_doc():
    cols = _doc_cols()
    assert "clients" in cols and "client" not in cols, cols  # 시험 전제 — 축소 스키마
    db = _DB(cols)
    assert backfill_chunk_clients(db) == 2
    assert db.updates == [(["A사", "B사"], 1), ([], 2)], db.updates  # clients 목록 그대로 · 없으면 [](고객 미상)
