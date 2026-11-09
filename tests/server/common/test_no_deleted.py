"""PG 접속 정보가 없으면 어느 RUN_ENV든 멈춘다 — 로컬 대체 DB(sqlite 대역)로 조용히 바꿔 타지 않는다(PRD pl-12 · e2-22)."""

import importlib.util

from common.config.settings import COMMON


def test_no_pg_standin():
    from common.store.pg import conf

    assert importlib.util.find_spec("common.store.pg_standin") is None  # 대역 모듈 없음
    for run_env in ("local", "dev", "prd"):
        with COMMON.env(RUN_ENV=run_env, PG_HOST=None):
            try:
                conf()
            except SystemExit as e:
                assert "PG 접속 정보 없음" in str(e), (run_env, e)
                continue
        raise AssertionError(f"{run_env}: PG 접속 정보 없이 통과")
