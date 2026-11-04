"""run_docs.py의 호스트 사본(rn-06)이 컨테이너 쪽과 같은지 — 끝난 문서 SQL 조건(DONE_STATUSES·GOLD_STATUSES·gold_version),
원본 키 칸 규칙(source_key ↔ s3_key), warm 파일 이름. 한쪽만 고치면 여기서 깨진다. 가짜 커서만 — EDW·docker·설정 파일 없음(PC 전용)."""

import importlib.util
from pathlib import Path
from unittest import mock

from common.core.paths import DEPLOY_ROOT
from common.store import parsing_meta_db as PM
from pipeline.extract import candidate_ready

INPROCESS = True  # 상태를 바꾸지 않는 시험(tests/conftest.py)


def _run_docs():
    spec = importlib.util.spec_from_file_location("run_docs_copies", DEPLOY_ROOT / "deploy" / "host" / "scripts" / "run_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 맨 위는 정의만(configure()·docker 호출 없음)
    return mod


RD = _run_docs()


class _Cur:
    """COL_LENGTH 질의는 cols에 있으면 길이, 없으면 NULL — 그 밖의 SQL은 적어 두고 빈 결과."""

    def __init__(self, cols):
        self.cols, self.sql = cols, []

    def execute(self, sql):
        self.sql.append(sql)
        self._one = None
        if "COL_LENGTH" in sql:
            self._one = (100 if sql.split("'")[3] in self.cols else None,)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []


def _host(cols):
    """run_docs.edw_done_keys가 낸 (키 칸, WHERE 조건)."""
    cur = _Cur(cols)
    conn = mock.Mock(cursor=lambda: cur)
    with mock.patch.object(RD, "_edw_connect", return_value=conn):
        assert RD.edw_done_keys() == set()
    sql = cur.sql[-1]
    kc = sql.split()[1]
    return kc, sql.split(" WHERE ", 1)[1]


def _container(cols):
    """parsing_meta_db._done_keys_rows가 낸 (키 칸, WHERE 조건) — 키 칸은 저장소 쪽 규칙(renames)."""
    kc = PM.renames(cols).get("source_key", "source_key")
    cur = _Cur(cols)
    assert PM._done_keys_rows(cur, "AI.ParsingMeta", kc, "gold_version" in cols) == set()
    return kc, cur.sql[-1].split(" WHERE ", 1)[1].replace(f"{kc} IS NOT NULL AND ", "", 1)


COLSETS = [  # 표의 칸 — 칸 이름 바꾸기(C-76) 전·후·중간 × gold_version 있음·없음
    {"source_key"},
    {"s3_key"},
    {"source_key", "s3_key"},
    {"source_key", "gold_version"},
    {"s3_key", "gold_version"},
]


def test_status_lists_same():
    assert RD.DONE_STATUSES == PM.DONE_STATUSES and RD.GOLD_STATUSES == PM.GOLD_STATUSES


def test_done_keys_sql_same():
    for cols in COLSETS:
        assert _host(cols) == _container(cols), cols


def test_warm_name_same():
    for bucket, key in [("raw", "SFDC/a.pdf"), ("버킷", "CRMS/한글 이름.hwp"), ("", "x")]:
        with mock.patch.object(RD, "WARM_BUCKET", bucket):
            assert RD._warm_bin({"s3_key": key}) == candidate_ready._warm_key_path(Path("w"), bucket, key).name, (bucket, key)
