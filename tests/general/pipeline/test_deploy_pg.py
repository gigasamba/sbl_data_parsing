"""실 PG(전용 pgvector)에서 deploy()가 새 검색 스키마를 만들고(기준 스키마 + 원천 스키마 5벌 — pl-28) 두 번째 호출은 그대로 둔다(멱등).
임시 스키마 `test_deploy_<임의>`와 그 원천 스키마를 만들고 끝나면 지운다(공용 개발 PG에 흔적 없음 — CLAUDE.md §6-4).
PG 접속 설정이 없으면 건너뜀(시험 격리 — 루트 settings.yaml이 없는 새 작업 폴더)."""

import uuid

import pytest

from common.store.db.models import search_tables as ST
from common.store.pg import PG, conf, has_conn
from pipeline.load.pgvector_load import deploy

INPROCESS = True  # pytest가 그대로 모음 — PG가 없을 때 skip을 쓰려고(자식 프로세스 시험은 skip을 못 알림)


def test_deploy_creates_source_schemas():
    if not has_conn():
        pytest.skip("PG 접속 설정 없음 — 루트 settings.yaml에 전용 PG를 적으면 돎")
    schema = f"test_deploy_{uuid.uuid4().hex[:8]}"
    names = [schema] + [ST.src_schema(schema, src) for src in ST.SOURCES]
    db = PG({**conf(), "PG_SCHEMA": schema})
    try:
        deploy(db, 4)  # 새 스키마 — 판 올리기(표·색인·뷰 생성)
        tables = {
            (r["schemaname"], r["tablename"])
            for r in db.q("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(%s)", (names,))
        }
        for src in ST.SOURCES:
            assert (ST.src_schema(schema, src), "doc") in tables, sorted(tables)
            assert (ST.src_schema(schema, src), "chunk") in tables, sorted(tables)
        deploy(db, 4)  # 판 끝 — 그대로(멱등)
    finally:
        for n in names:
            assert n.startswith("test_deploy_")  # 지우기 전 이름 확인
            db.q(f"DROP SCHEMA IF EXISTS {n} CASCADE")
