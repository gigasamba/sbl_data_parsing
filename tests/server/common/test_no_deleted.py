"""서버(dev·prd·모르는 RUN_ENV)는 스탠드인으로 조용히 대체하지 않는다(규칙: PRD pl-12)."""

from common.config.settings import COMMON


def test_pg_standin_refused_on_server():
    from common.store.pg import _warn_standin

    with COMMON.env(RUN_ENV="dev"):
        try:
            _warn_standin()
        except SystemExit:
            return
    raise AssertionError("dev에서 스탠드인이 거부되지 않음")
