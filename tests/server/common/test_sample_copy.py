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

from common.config import sample
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
_LOCAL_BUCKET = f"file://{PROJ_ROOT.as_posix()}/valid_env/object_storage/Parsing_Result"
# (사례, 채울 칸, 기대 RUN_ENV, 기대 값) — 기대 값: schema = PG 스키마(None = PG 접속 없음 — sqlite 대역), write = login("write")의 계정,
# bucket = 게시 버킷, source = 파싱 원본, max_new = 새 문서 상한, ignored = 경고에 나와야 하는 칸 이름(local이 비운 서버 칸)
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
        "(c)(d) 개발 서버 — pg_schema·EDW 쓰기 계정을 비워 둠",
        DEV,
        "dev",
        {"schema": "data_parsing", "write": "svc_r", "bucket": "rag-silver", "ignored": ()},
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
            y.write_text(_fill(text, fills), encoding="utf-8")
            env = {"SETTINGS_FILE": str(y)}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                for cls in (S.CommonAppSettings, *S.app_classes().values()):
                    S.load(cls, file=y, environ={})  # STRICT — 모르는 칸·틀린 값이면 SettingsError
                for app in ("pipeline", "mcp"):
                    assert S.require_run_env(app, environ=env, sections=(app,)) == want, what
            st = S.load(S.section_class(("common", "pipeline"))[0], file=y, environ={})
            c, p = st.common.connections, getattr(st, "pipeline", None)  # mcp 이미지에는 pipeline 절이 없음
            for k in exp["ignored"]:
                assert k in err.getvalue(), (what, k, err.getvalue())
            assert all(v not in err.getvalue() for v in SERVER_ONLY.values()), what  # 칸 이름만, 값은 안 찍음
            if want == "local":
                assert not c.rdb.host and not c.object_storage.endpoint, what
            if p is not None:
                assert p.load.publish.bucket == exp["bucket"], (what, p.load.publish.bucket)
            if p is not None and "source" in exp:
                assert (p.extract.input_source, p.extract.max_new) == (exp["source"], exp["max_new"]), what
            with S.COMMON.override(file=y, environ={}):
                assert (pg.conf()["PG_SCHEMA"] if pg.has_conn() else None) == exp["schema"], what
                if "write" in exp:
                    assert mssql.login("write")[0]["user"] == exp["write"], what
            if _HOST.is_file():
                host = _host()
                doc, herr = host.load_or_error(y)
                out = host.lines(doc, None)
                image = any(x.startswith("export DATA_PIPELINE_IMAGE=") for x in out)  # local은 빈 칸 그대로 = 안 냄
                assert herr is None and f"export RUN_ENV='{want}'" in out and image == (want == "dev"), (what, herr)


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
        with mock.patch.object(paths, "LOCAL_EDW_COPY", copy), S.COMMON.env(RUN_ENV="dev", RDB_SQLITE=None):
            assert mssql.standin_path() is None  # 서버는 대역 없음
