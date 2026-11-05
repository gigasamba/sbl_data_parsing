"""서버(dev·prd·모르는 RUN_ENV)는 스탠드인으로 조용히 대체하지 않고(규칙: PRD pl-12),
publish는 EDW에 'deleted'를 쓰지 않는다(상태 열 UPDATE 길 없음)."""

import inspect

from common.config.settings import COMMON


def test_pg_standin_refused_on_server():
    from common.store.pg import _warn_standin

    with COMMON.env(RUN_ENV="dev"):
        try:
            _warn_standin()
        except SystemExit:
            return
    raise AssertionError("dev에서 스탠드인이 거부되지 않음")


def test_publish_never_updates():
    from common.store import parsing_meta_db

    src = inspect.getsource(parsing_meta_db)
    # EDW는 INSERT만 — status를 deleted·changed로 바꾸는 길 없음. 예외는 적재 때 loaded_at·gold_version뿐
    ups = [ln for ln in src.splitlines() if "UPDATE {" in ln]
    assert ups and all("SET {', '.join(sets)}" in ln for ln in ups), ups
    assert parsing_meta_db.LOADED_COLS == ("loaded_at", "gold_version")
    sets = [ln.split("sets.append(", 1)[1] for ln in src.splitlines() if "sets.append(" in ln]
    assert sets and all(s.lstrip('f"').startswith(parsing_meta_db.LOADED_COLS) for s in sets), sets
