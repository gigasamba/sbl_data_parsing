"""pl-14 — 실 PG(전용 pgvector)의 현재 검색 스키마(Alembic 기준판)에서 deploy()가 오류 없이 돌고, clients가 NULL인 청크를
backfill이 doc.clients로 채운다. 임시 스키마 `test_pl14_<임의>`를 만들고 끝나면 지운다(공용 개발 PG에 흔적 없음 — CLAUDE.md §6-4).
PG 접속 설정이 없으면 건너뜀(시험 격리 — 루트 settings.yaml이 없는 새 작업 폴더). 서버 반입 시험(가짜 DB)은
tests/server/pipeline/test_pl14_backfill.py."""

import uuid

import pytest

from common.store.pg import PG, conf, has_conn
from pipeline.load.pgvector_load import deploy

INPROCESS = True  # pytest가 그대로 모음 — PG가 없을 때 skip을 쓰려고(자식 프로세스 시험은 skip을 못 알림)


def test_deploy_backfills_null_chunk():
    if not has_conn():
        pytest.skip("PG 접속 설정 없음 — 루트 settings.yaml에 전용 PG를 적으면 돎")
    schema = f"test_pl14_{uuid.uuid4().hex[:8]}"
    db = PG({**conf(), "PG_SCHEMA": schema})
    try:
        deploy(db, 4)  # 새 스키마 — 판 올리기(표 생성) 뒤 backfill(빈 표)
        doc = db.q(f"INSERT INTO {schema}.doc (file_path, clients) VALUES ('/d/a.txt', %s) RETURNING doc_id", ('["A사", "B사"]',))[0][
            "doc_id"
        ]
        db.q(
            f"INSERT INTO {schema}.chunk (doc_id, seq, chunk_text, n_chars, n_terms, clients) VALUES (%s, 0, 'x', 1, 1, NULL) RETURNING chunk_id",
            (doc,),
        )
        deploy(db, 4)  # 기존 스키마(판 끝) — backfill이 NULL 청크를 채움(pl-14 전에는 d.client 조회 오류로 멈춤)
        rows = db.q(f"SELECT clients FROM {schema}.chunk")
        assert [r["clients"] for r in rows] == [["A사", "B사"]], rows
        deploy(db, 4)  # 멱등 — NULL이 없으면 그대로
    finally:
        assert schema.startswith("test_pl14_")  # 지우기 전 이름 확인
        db.q(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
