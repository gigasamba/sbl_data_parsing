"""op-17 — DEV 원천(`DEV-<n>` — 개발 서버·PC만): 원천 이름 `dev_<n>` · 스키마 `<기준>_dev_<n>`(5벌과 같은 표, 메타 없음). 스키마는 dbtool up이
설정의 DEV 원천과 DB에 이미 있는 `_dev_*`를 올려 만든다(적재는 DDL 없이 — 없으면 멈춤). 끝난 문서·PC 폴더 원천도 DEV를 본다.
DB 없이 — up은 가짜 연결, --sql은 Alembic 오프라인, 적재·끝난 문서는 PC 대역(임시 폴더)."""

import contextlib
import io
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON, isolated
from common.store import pg
from common.store import pg_standin as PS
from common.store.db import dbtool
from common.store.db.dbtool import MIGRATIONS
from common.store.db.models import search_tables as ST
from pipeline import config as pc
from pipeline.extract import candidate_pick as CP
from pipeline.load import pgvector_load as M
from tests.server.pipeline.goldseed import seed
from tests.server.pipeline.test_pl13_no_prune import _bundle

# (원천 표기, 원천 이름) — DEV-<1~99>는 대소문자 무관·`-test` 별칭 그대로, 그 밖은 other(DEV-100은 설정이 거부 — test_target_list)
MAPPING = [
    ("DEV-1", "dev_1"),
    ("dev-1", "dev_1"),
    ("DEV-99", "dev_99"),
    ("Dev-7-test", "dev_7"),
    ("DEV-100", "other"),
    ("DEV-0", "other"),
    ("SFDC", "sfdc"),
    ("SFDC-test", "sfdc"),
    ("Other", "other"),
    (None, "other"),
]
# (스키마 이름, (기준, 원천))
SPLIT = [
    ("ai_dev_1", ("ai", "dev_1")),
    ("ai_x_dev_12", ("ai_x", "dev_12")),
    ("ai_las", ("ai", "las")),
    ("ai_dev", ("ai_dev", None)),
    ("ai", ("ai", None)),
]


def test_mapping():
    for system, src in MAPPING:
        assert ST.source_of(system) == src, system
    for schema, want in SPLIT:
        assert ST.split_schema(schema) == want, schema
    assert ST.src_schema("ai", "dev_1") == "ai_dev_1" and ST.label("dev_12") == "DEV-12" and ST.label("other") == "Other"
    assert (
        ST.doc_columns("dev_1") == ST.doc_columns("other")
        and ST.view_columns("dev_1") == ST.view_columns("other")
        and ST.view_sql("dev_1") == ST.view_sql("other")
    )
    assert "dev_1" not in ST.SOURCES  # 고정 5벌은 그대로(판 파일이 대조)


# up --target search: (설정 원천 목록, DB에 있는 스키마, 판 올린 DEV 원천) — 설정 DEV는 만들고, 설정에 없어도 DB에 있는 _dev_*는 올린다
UP = [
    (None, [], []),
    ("DEV-1,SFDC", [], ["dev_1"]),
    ("DEV-1", ["ai_dev_2", "ai_dev_x", "aix_dev_3", "ai_dev_10"], ["dev_1", "dev_2", "dev_10"]),
]


def test_up_dev_schemas():
    for systems, in_db, want in UP:
        calls = []

        @contextlib.contextmanager
        def begin():
            yield object()

        q = lambda sql, params=None, in_db=in_db: [{"s": s} for s in in_db] if "schemata" in sql else []  # 가짜 질의
        with (
            mock.patch.object(pg, "has_conn", lambda: True),
            mock.patch.object(dbtool, "engine", lambda: mock.Mock(begin=begin)),
            mock.patch.object(dbtool, "_q", lambda c, q=q: q),
            mock.patch.object(dbtool, "precheck_search", lambda *a: None),
            mock.patch.object(dbtool, "upgrade", lambda t, s, d=None, c=None, src=None, calls=calls: calls.append((t, s, src))),
            mock.patch.object(dbtool, "check", lambda t, s: ("끝", [dbtool.head(t)])),
            isolated(SOURCE_SYSTEMS=systems),  # dbtool은 설정 객체로 읽음(pipeline 캐시 아님)
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            assert dbtool.main(["up", "--target", "search", "--schema", "ai", "--dim", "8"]) == 0
        assert calls == [("search", "ai", None), *(("search", "ai", s) for s in want)], (systems, calls)
        assert all(f"search ai_{s}: 판" in out.getvalue() for s in want), out.getvalue()


# check --target search: (DB에 있는 DEV 스키마의 판 상태, 종료 코드) — 있는 _dev_*도 끝 판이어야 0
CHECK = [("끝", 0), ("낮음", 1)]


def test_check_dev_schemas():
    for dev_st, rc in CHECK:
        st = lambda t, s, dev_st=dev_st: (dev_st if s == "ai_dev_2" else "끝", [])  # 가짜 판 상태
        with (
            mock.patch.object(pg, "has_conn", lambda: True),
            mock.patch.object(dbtool, "_dev_in_db", lambda s: ["dev_2"]),
            mock.patch.object(dbtool, "check", st),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            assert dbtool.main(["check", "--target", "search", "--schema", "ai"]) == rc, dev_st
        assert f"search ai_dev_2: 판 {dev_st}" in out.getvalue()


def test_prd_refuses_dev():
    """prd — 설정의 DEV 원천은 거부, DB의 _dev_* 스키마는 찾지도 않음(빈 목록). dev — 찾음."""
    q = lambda sql, params=None: [{"s": "ai_dev_2"}]  # 가짜 질의
    with COMMON.env(RUN_ENV="prd"):
        with isolated(SOURCE_SYSTEMS="DEV-1"), contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                dbtool.dev_from_settings()
                raise AssertionError("prd에서 DEV 원천은 거부해야 함")
            except dbtool.DbToolError as e:
                assert e.code == 2 and "개발 서버" in err.getvalue()
        assert ST.dev_sources("ai", q) == [] and ST.all_sources("ai", q) == list(ST.SOURCES)
    with COMMON.env(RUN_ENV="dev"), isolated(SOURCE_SYSTEMS="dev-3,DEV-1"):
        assert dbtool.dev_from_settings() == ["dev_1", "dev_3"] and ST.dev_sources("ai", q) == ["dev_2"]


def test_up_sql_dev():
    """--sql: 설정의 DEV 원천 스키마를 빈 스키마부터(판 기록 표·doc_id 공용 시퀀스) — 고정 5벌 부분은 DEV가 없을 때와 글자 그대로.
    DB에 있는 다른 _dev_*는 DB를 읽어야 알아 `-- 수동:` 줄로."""
    no_db = mock.Mock(side_effect=AssertionError("DB에 붙음"))
    with tempfile.TemporaryDirectory() as d, mock.patch.object(dbtool, "engine", no_db), mock.patch.object(pg, "conf", no_db):
        got = {}
        for systems in (None, "DEV-1"):
            out = Path(d) / f"{systems}.sql"
            with isolated(SOURCE_SYSTEMS=systems), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                assert dbtool.main(["up", "--sql", str(out), "--target", "search", "--schema", "demo", "--dim", "8"]) == 0
            got[systems] = out.read_text(encoding="utf-8")
    base, dev = got[None], got["DEV-1"]
    assert dev.startswith(base), "고정 5벌 부분이 달라짐"
    part = dev[len(base) :]
    for s in (
        "CREATE SCHEMA IF NOT EXISTS demo_dev_1;",
        "CREATE TABLE demo_dev_1.alembic_version",
        "CREATE TABLE IF NOT EXISTS demo_dev_1.doc",
        "nextval('demo.doc_id_seq'::regclass)",
        "CREATE VIEW demo_dev_1.v_chunk_source",
        "ALTER TABLE demo_dev_1.doc ADD COLUMN IF NOT EXISTS attrs JSONB",
        "ALTER TABLE demo_dev_1.doc ADD COLUMN IF NOT EXISTS sha256 TEXT",
        "-- 수동: DB에 이미 있는 다른 demo_dev_*",
        "CREATE INDEX IF NOT EXISTS ix_demo_dev_1_doc_path ON demo_dev_1.doc (file_path)",
        "SET version_num='0007_search'",
    ):
        assert s in part, s
    for s in ("DROP TABLE", "demo.load_run", "demo_sfdc", "demo.alembic_version", "approvalname"):
        assert s not in part, s


def test_load_dev():
    """DEV-1 문서는 `<기준>_dev_1`에(EDW 메타 없음 — EDW를 열지 않음) · 끝난 문서가 그 행을 봄 · 실 PG에 스키마가 없으면 멈춤(DDL 없음)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        with COMMON.env(RUN_ENV="local", PG_STANDIN_DIR=str(tmp / "pg"), PG_SCHEMA="test_dev"):
            db = PS.StandinPG("test_dev")
            no_edw = mock.Mock(side_effect=AssertionError("EDW를 엶"))
            with mock.patch("pipeline.load.edw_doc_meta._Edw", no_edw):
                counts = M.load(db, _bundle(["DEV-1/u1/a.pdf"], tmp, "DEV-1"))
            assert counts["by_source"]["dev_1"]["docs"] == 1, counts
            rows = PS.StandinPG("test_dev_dev_1").q("SELECT file_path, created_at FROM test_dev_dev_1.doc")
            assert rows == [{"file_path": "DEV-1/u1/a.pdf", "created_at": "2025-03-01T10:00:00+09:00"}], rows
            seed([{"file_path": "DEV-2/u/b.pdf", "source_system": "dev-2"}])
            assert CP.done_keys() == {"DEV-1/u1/a.pdf", "DEV-2/u/b.pdf"}
            assert ST.all_sources("test_dev")[5:] == ["dev_1", "dev_2"]
        real = mock.Mock(is_standin=False, schema="ai", q=lambda sql, params=None: [])  # 실 PG 꼴 — DEV 스키마 없음
        err = None
        try:
            M.src_dbs(real, {"dev_1"})
        except SystemExit as e:
            err = str(e.code)
        assert err and "ai_dev_1" in err and "dbtool up" in err, err
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# PC 폴더 원천: (원천 목록, 기대 파일) — 맨 위 DEV-1/ 폴더도 원천 폴더, 목록이 있으면 그 원천 폴더만, 비우면 운영 5개 원천(DEV 폴더 뺌 —
# 규칙 8) · 다 빠지면 빈 목록(평평한 폴더 아님)
FOLDER = [
    (None, ["SFDC/u2/b.txt"]),
    ("DEV-1", ["DEV-1/u1/a.txt"]),
    ("dev-1,SFDC", ["DEV-1/u1/a.txt", "SFDC/u2/b.txt"]),
    ("CRMS", []),
]


def test_folder_dev():
    assert CP._known_source("dev-1") == "DEV-1" and CP._known_source("DEV-100") is None and CP._known_source("other") is None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d)
        for rel in ("DEV-1/u1/a.txt", "SFDC/u2/b.txt"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        for systems, want in FOLDER:
            with pc.PIPE.env(SOURCE_SYSTEMS=systems):
                files = CP._tree_files(src)
            assert files is not None and [p.relative_to(src).as_posix() for p in files] == want, (systems, files)


# 원천 목록 → 고름 여부(candidate_pick.picked — 목록 파일·rdb:csv·PC 폴더가 같이 씀): 비우면 운영 5개 원천(DEV-<n>만 뺌, 원천 칸이 빈 행은 Other)
PICKED = [
    ((), "SFDC", True),
    ((), "OTHER", True),
    ((), None, True),
    ((), "DEV-1", False),
    ((), "DEV-1-TEST", False),
    (("DEV-1",), "DEV-1", True),
    (("DEV-1",), "SFDC", False),
]


def test_picked():
    for systems, system, want in PICKED:
        assert CP.picked(system, systems) is want, (systems, system)


def test_migrations_use_search_parts():
    """검색 갈래 판 파일은 원천 목록을 직접 돌지 않고 search_parts.sources()로 — 새 판(0007…)이 DEV 원천 스키마를 조용히 건너뛰지 않게.
    원천 스키마에 손대는 판(0002부터)은 search_parts를 부른다."""
    files = sorted(
        f for f in (MIGRATIONS / "versions").glob("*.py") if re.search(r'^revision = "\d+_search"', f.read_text(encoding="utf-8"), re.M)
    )
    assert len(files) == len(dbtool.known("search")), files
    for f in files:
        text = f.read_text(encoding="utf-8")
        loops = re.findall(r"^\s*for \w+(?:, \w+)? in (?!search_parts\.sources\()([^:]+):", text, re.M)
        bad = [x for x in loops if re.search(r"\b(SOURCES|DOC_HINTS|OLD_COLS|OLD_EXTRA)\b", x)]
        assert not bad, (f.name, bad)
        assert "search_parts." in text, f.name
