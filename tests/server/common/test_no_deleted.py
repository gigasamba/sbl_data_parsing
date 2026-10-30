"""pl-12(사용자 10-30) — 서버(dev·prd)는 SQLite·스탠드인으로 조용히 대체하지 않고, publish는 'deleted'를 쓰지 않는다."""

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
    (
        "dev",
        {"RUN_MODE": "prod", "STRUCT_BACKEND": "pg", "PG_HOST": "127.0.0.1", "PG_PORT": "1", "PG_PASSWORD": "x"},
        "refuse",
    ),  # PG 안 닿음
    ("local", {"RUN_MODE": "", "STRUCT_BACKEND": "sqlite"}, "sqlite"),  # PC는 그대로
]


def test_backend_no_fallback():
    path = str(Path(tempfile.mkdtemp()) / "r.sqlite")
    for run_env, names, want in BACKEND_CASES:
        with COMMON.env(RUN_ENV=run_env, **names):
            try:
                got = type(open_backend(path)).__name__
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
    try:
        CommonStore(run_mode="production")
    except ValidationError:
        return
    raise AssertionError("run_mode='production'이 받아들여짐")


def test_publish_never_marks_deleted():
    from pipeline.load.parsing_meta import apply_registry_status

    class FakeEDW:
        def __init__(self):
            self.updates = []

        def find_by_doc_key(self, key):
            return [{"source_system": "S", "source_key": key, "parse_date": "d", "status": "active"}]

        def update_status(self, *a):
            self.updates.append(a)

        def update_status_at(self, *a):
            return 1

    db = FakeEDW()
    counts = apply_registry_status(db, {"changed": ["c"], "deleted": ["gone1", "gone2"], "touched": []})
    assert counts["deleted"] == 0 and [a[1] for a in db.updates] == ["c"], (counts, db.updates)
