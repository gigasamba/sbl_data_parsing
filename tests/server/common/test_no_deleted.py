"""pl-12(사용자 10-30) — 서버(dev·prd·모르는 RUN_ENV)는 SQLite·스탠드인으로 조용히 대체하지 않고,
publish는 EDW에 'deleted'를 쓰지 않는다(C10 10-31 — 문서 대장과 상태 열 UPDATE 길을 통째로 지움)."""

import inspect
import tempfile
from pathlib import Path

from pydantic import ValidationError

from common.config.settings import COMMON, CommonStore
from common.store.structdb import StructDBError, open_backend

# (RUN_ENV, 설정, 기대) — 기대: "refuse"(StructDBError) · "sqlite"(SQLite 그대로 — PC만)
BACKEND_CASES = [
    ("dev", {"RUN_MODE": "", "STRUCT_BACKEND": "pg"}, "refuse"),  # run_mode 빠짐
    ("prd", {"RUN_MODE": "test", "STRUCT_BACKEND": "pg"}, "refuse"),  # prod 아님
    ("dev", {"RUN_MODE": "prod", "STRUCT_BACKEND": "sqlite"}, "refuse"),  # 서버에서 SQLite 지정
    ("PRD", {"RUN_MODE": "", "STRUCT_BACKEND": "pg"}, "refuse"),  # 모르는 RUN_ENV 글자 = 서버로 봄
    (
        "dev",
        {"RUN_MODE": "prod", "STRUCT_BACKEND": "pg", "PG_HOST": "127.0.0.1", "PG_PORT": "1", "PG_PASSWORD": "x"},
        "refuse",
    ),  # PG 안 닿음 — run_mode prod 길(대체 금지)이 거부
    ("local", {"RUN_MODE": "", "STRUCT_BACKEND": "sqlite"}, "sqlite"),  # PC는 그대로
]


def test_backend_no_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "r.sqlite")
        for run_env, names, want in BACKEND_CASES:
            with COMMON.env(RUN_ENV=run_env, **names):
                try:
                    db = open_backend(path)
                    got = type(db).__name__
                    db.close()
                except StructDBError:
                    got = "refuse"
            assert got == ("SqliteBackend" if want == "sqlite" else "refuse"), (run_env, names, got)


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
