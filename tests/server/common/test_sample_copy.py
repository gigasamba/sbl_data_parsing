"""op-05·op-14 — settings.sample.yaml을 그대로 settings.yaml로 복사하고 빈 칸(사람이 꼭 적을 [필수] 칸)만 채우면 바로 시작된다.
local은 run_env·모델 접속만 채우면 시작하고(PG는 비우면 sqlite 대역), 서버 전용 칸을 적어 두면 비우고 경고(칸 이름만)한다.
표 한 줄 = (사례, 채울 칸, 기대 RUN_ENV, 기대 값). 앱 설정·시작 관문·호스트 읽기(있을 때)·PG 스키마·EDW 계정·local 값을 본다.
외부 접속 없음, 임시 폴더만 — 설정 파일은 load(file=…)·environ 사전으로 가리킨다(os.environ 안 건드림)."""

import contextlib
import importlib.util
import io
import json
import re
import tempfile
from pathlib import Path
from unittest import mock

import yaml

from common.config import layout, sample
from common.config import settings as S
from common.core import paths
from common.core.paths import PROJ_ROOT
from common.store import mssql, pg

_HEX = "0123456789abcdef" * 2  # 32자 — 서버 비밀 칸 길이 정책을 넘김
MODELS = {
    "embed_base_url": "http://127.0.0.1:9/v1",
    "embed_model": "test-embed",
    "llm_base_url": "http://127.0.0.1:9/v1",
    "llm_model": "test-llm",
    "vlm_base_url": "http://127.0.0.1:9/v1",
    "vlm_model": "test-vlm",
}
LOCAL_MIN = {"run_env": "local", **MODELS}
PG = {"pg_host": "127.0.0.1", "pg_port": "55433", "pg_database": "rag", "pg_user": "rag", "pg_password": _HEX}
SERVER_ONLY = {  # local이 무시하는 서버 전용 칸(실제 EDW·Object Storage·s3 게시 버킷)
    "edw_host": "edw.example.local",
    "object_storage_endpoint": "https://os.example.local:9000",
    "publish_bucket": "rag-silver",
}
DEV = {**MODELS, **PG, **SERVER_ONLY} | {
    "run_env": "dev",
    "edw_database": "EDW",
    "edw_read_user": "svc_r",
    "edw_read_password": _HEX,
    "object_storage_access_key": _HEX,
    "object_storage_secret_key": _HEX,
    "mcp_token": _HEX,
    "fulltext_sign_key": _HEX,
    "pipeline_image": "data-pipeline-runtime:0.0.0",
    "mcp_image": "mcp-server-runtime:0.0.0",
    "host_docs_dir": "/data/docs",
    "pg_container_name": "pgvector",
}
# 덮기 파일(overrides — env 이름)로 준 서버 전용 칸 전부(LOCAL_IGNORED) — 값은 칸마다 다르게(경고에 값이 새면 잡히게)
_CLS = S.section_class(("common", "pipeline"))[0]
_ENV = {p: e for e, p in S.env_map(_CLS).items()}
ALL_SERVER = {_ENV[p]: f"srv-value-{i}-{_HEX}" for i, p in enumerate(S.LOCAL_IGNORED)}
_LOCAL_BUCKET = f"file://{PROJ_ROOT.as_posix()}/valid_env/object_storage/Parsing_Result"
# (사례, 채울 칸, 기대 RUN_ENV, 기대 값) — 기대 값: schema = PG 스키마(None = PG 접속 없음 — sqlite 대역), write = login("write")의 계정,
# bucket = 게시 버킷, source = 파싱 원본, max_new = 새 문서 상한, ignored = 경고에 나와야 하는 칸 이름(local이 비운 서버 칸),
# overlay = 덮기 파일 overrides로 줄 값(env 이름), blank = sample이 기본값을 적어 낸 칸 중 비울 칸, warn = 나와야 하는 경고 글자(없으면 그 경고가 없어야 함 — pg_schema 기본값 알림)
CASES = (
    (
        "(a) PC — run_env·모델만 채움(PG 없음 → sqlite 대역)",
        LOCAL_MIN,
        "local",
        {
            "schema": None,
            "bucket": _LOCAL_BUCKET,
            "source": f"{PROJ_ROOT.as_posix()}/valid_env/object_storage",
            "max_new": 5,
            "ignored": (),
        },
    ),
    ("PC — PG까지 채움(스키마는 기본값)", {**LOCAL_MIN, **PG}, "local", {"schema": "data_parsing", "bucket": _LOCAL_BUCKET, "ignored": ()}),
    (
        "(b) PC — 서버 EDW 주소·Object Storage 주소·s3 게시 버킷을 적어 둠 → 비우고 경고",
        {**LOCAL_MIN, **SERVER_ONLY},
        "local",
        {"schema": None, "bucket": _LOCAL_BUCKET, "ignored": tuple(SERVER_ONLY)},
    ),
    (
        "PC — 덮기 파일로 서버 전용 칸(LOCAL_IGNORED) 전부를 줌 → 모두 비우고 경고 한 줄(칸 자리만)",
        LOCAL_MIN,
        "local",
        {"schema": None, "bucket": _LOCAL_BUCKET, "overlay": ALL_SERVER, "ignored": tuple(map(layout.to_yaml, S.LOCAL_IGNORED))},
    ),
    (
        "(c)(d) 개발 서버 — pg_schema·EDW 쓰기 계정을 비워 둠",
        DEV,
        "dev",
        {
            "schema": "data_parsing",
            "write": "svc_r",
            "bucket": "rag-silver",
            "ignored": (),
            "warn": "required.pg.pg_schema",
            "blank": "pg_schema",
        },
    ),
)
_HOST = PROJ_ROOT / "deploy" / "host" / "scripts" / "settings_to_env.py"  # 호스트 스크립트 — 이미지에는 없음(PC에서만 봄)


def _fill(text, fills):
    """빈 칸 줄(`이름:` 뒤가 비고 주석만)에 값을 적는다 — 칸 이름은 파일 전체에서 하나라 이름만으로 찾는다."""
    for k, v in fills.items():
        text, n = re.subn(rf"(?m)^( +{k}): *#", lambda m, v=v: f"{m.group(1)}: {json.dumps(v)}  #", text)
        assert n == 1, (k, "빈 칸이 아님 — sample이 이 칸을 빈 칸으로 내야 함")
    return text


def _host():
    spec = importlib.util.spec_from_file_location("settings_to_env", _HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_copied_sample_runs_after_filling_blanks():
    text = sample.build()
    for what, fills, want, exp in CASES:
        with tempfile.TemporaryDirectory() as d, mock.patch.object(S, "_warned", set()):
            y = Path(d) / "settings.yaml"
            filled = _fill(text, fills)
            if "blank" in exp:
                filled, n = re.subn(rf"(?m)^( +{exp['blank']}):[^#\n]*#", r"\1:  #", filled)
                assert n == 1, (what, exp["blank"])
            y.write_text(filled, encoding="utf-8")
            f = y
            if "overlay" in exp:  # 덮기 파일 — base(복사한 sample) 위에 overrides
                f = Path(d) / "overlay.yaml"
                f.write_text(yaml.safe_dump({"base": str(y), "overrides": exp["overlay"]}), encoding="utf-8")
            env = {"SETTINGS_FILE": str(f)}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                for cls in (S.CommonAppSettings, *S.app_classes().values()):
                    S.load(cls, file=f, environ={})  # STRICT — 모르는 칸·틀린 값이면 SettingsError
                for app in ("pipeline", "mcp"):
                    assert S.require_run_env(app, environ=env, sections=(app,)) == want, what
            st = S.load(_CLS, file=f, environ={})
            c, p = st.common.connections, getattr(st, "pipeline", None)  # mcp 이미지에는 pipeline 절이 없음
            for k in exp["ignored"]:
                assert k in err.getvalue(), (what, k, err.getvalue())
            if "overlay" in exp:  # 한 줄에 전부
                assert any(all(k in line for k in exp["ignored"]) for line in err.getvalue().splitlines()), what
                left = [q for q in S.LOCAL_IGNORED if _peek(st, q) not in (None, "")]
                assert left == ["pipeline.load.publish.bucket"], (what, left)  # 게시 버킷만 다시 채움(local 게시 폴더 — 아래 bucket)
            secrets = (*SERVER_ONLY.values(), *ALL_SERVER.values())
            assert all(v not in err.getvalue() for v in secrets), what  # 칸 이름만, 값은 안 찍음
            if want == "local":
                assert not c.rdb.host and not c.object_storage.endpoint, what
            if p is not None:
                assert p.load.publish.bucket == exp["bucket"], (what, p.load.publish.bucket)
            if p is not None and "source" in exp:
                assert (p.extract.input_source, p.extract.max_new) == (exp["source"], exp["max_new"]), what
            err = io.StringIO()
            with S.COMMON.override(file=f, environ={}), contextlib.redirect_stderr(err):
                assert (pg.conf()["PG_SCHEMA"] if pg.has_conn() else None) == exp["schema"], what
                if "write" in exp:
                    assert mssql.login("write")[0]["user"] == exp["write"], what
            warn = [line for line in err.getvalue().splitlines() if "required.pg.pg_schema" in line]
            assert len(warn) == ("warn" in exp) and all(exp["schema"] in line for line in warn), (what, warn)  # 쓰는 기본값도 알림
            if _HOST.is_file():
                host = _host()
                doc, herr = host.load_or_error(y)
                out = host.lines(doc, None)
                image = any(x.startswith("export DATA_PIPELINE_IMAGE=") for x in out)  # local은 빈 칸 그대로 = 안 냄
                assert herr is None and f"export RUN_ENV='{want}'" in out and image == (want == "dev"), (what, herr)


def _peek(st, path):
    v = st
    for part in path.split("."):
        v = getattr(v, part, None)
    return S.reveal(v)


def test_local_edw_copy_made_from_valid_env():
    """(a) local에서 가짜 EDW 칸을 비우면 valid_env/edw/edw_copy.sqlite — 없으면 git의 edw.sqlite를 복사해 만들고 원본은 그대로."""
    with tempfile.TemporaryDirectory() as d:
        seed, copy = Path(d) / "edw.sqlite", Path(d) / "edw_copy.sqlite"
        seed.write_bytes(b"seed-bytes")
        with (
            mock.patch.object(paths, "LOCAL_EDW_SEED", seed),
            mock.patch.object(paths, "LOCAL_EDW_COPY", copy),
            S.COMMON.env(RUN_ENV="local", RDB_SQLITE=None),
        ):
            got = mssql.standin_path()
            assert got == copy.as_posix() and not list(Path(d).glob("*.tmp")), got
            assert Path(got).read_bytes() == b"seed-bytes" and seed.read_bytes() == b"seed-bytes"
            Path(got).write_bytes(b"used")
            assert Path(mssql.standin_path()).read_bytes() == b"used"  # 있으면 다시 복사하지 않음
            with mock.patch.object(Path, "exists", lambda self: False):  # 경합 — 확인 뒤 다른 프로세스가 먼저 만든 경우
                assert Path(mssql.standin_path()).read_bytes() == b"used"  # 먼저 생긴 사본을 덮지 않음
            assert not list(Path(d).glob("*.tmp")), list(Path(d).iterdir())  # 임시 파일은 지움
        with mock.patch.object(paths, "LOCAL_EDW_COPY", copy), S.COMMON.env(RUN_ENV="dev", RDB_SQLITE=None):
            assert mssql.standin_path() is None  # 서버는 대역 없음
