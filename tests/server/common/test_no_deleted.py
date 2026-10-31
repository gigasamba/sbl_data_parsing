"""pl-12(사용자 10-30) — 서버(dev·prd·모르는 RUN_ENV)는 스탠드인으로 조용히 대체하지 않고,
publish는 EDW에 'deleted'를 쓰지 않는다(C10 10-31 — 문서 대장과 상태 열 UPDATE 길을 통째로 지움).
(정형 저장소 SQLite 대체 거부 사례는 저장소째 지워 없음 — pl-08, 사용자 10-31.)"""

import inspect

from pydantic import ValidationError

from common.config.settings import COMMON, CommonStore


def test_pg_standin_refused_on_server():
    from common.store.pg import _warn_standin

    with COMMON.env(RUN_ENV="dev"):
        try:
            _warn_standin()
        except SystemExit:
            return
    raise AssertionError("dev에서 스탠드인이 거부되지 않음")


def test_run_mode_values():
    assert CommonStore(run_mode="prod").run_mode == "prod"
    assert CommonStore(run_mode="").run_mode is None  # 빈 글자 = 설정 안 함
    try:
        CommonStore(run_mode="production")
    except ValidationError:
        return
    raise AssertionError("run_mode='production'이 받아들여짐")


def test_publish_never_updates():
    from common.store import parsing_meta_db

    assert "UPDATE {" not in inspect.getsource(parsing_meta_db)  # EDW는 INSERT만 — status를 deleted·changed로 바꾸는 길 없음
