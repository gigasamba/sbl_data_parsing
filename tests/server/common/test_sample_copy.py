"""op-05 — settings.sample.yaml을 그대로 settings.yaml로 복사하고 빈 칸(사람이 꼭 적을 [필수] 칸)만 채우면 바로 시작된다.
표 한 줄 = (사례, 채울 칸, 비울 칸, 기대 RUN_ENV 또는 거부 글자). 앱 설정·시작 관문·호스트 읽기(있을 때)·PG 접속 거부를 본다.
외부 접속 없음, 임시 폴더만 — 설정 파일은 load(file=…)·environ 사전으로 가리킨다(os.environ 안 건드림)."""

import importlib.util
import json
import re
import tempfile
from pathlib import Path

from common.config import sample
from common.config import settings as S
from common.core.paths import PROJ_ROOT
from common.store import pg

_HEX = "0123456789abcdef" * 2  # 32자 — 서버 비밀 칸 길이 정책을 넘김
LOCAL = {
    "run_env": "local",
    "pg_host": "127.0.0.1",
    "pg_port": "55433",
    "pg_database": "rag",
    "pg_user": "rag",
    "pg_password": _HEX,
    "pg_schema": "rag_test",
    "embed_base_url": "http://127.0.0.1:9/v1",
    "embed_model": "test-embed",
    "llm_base_url": "http://127.0.0.1:9/v1",
    "llm_model": "test-llm",
    "vlm_base_url": "http://127.0.0.1:9/v1",
    "vlm_model": "test-vlm",
    "edw_local_sqlite_file": "output/edw.sqlite",
    "publish_bucket": "file://output/object_storage/silver",
}
DEV = {k: v for k, v in LOCAL.items() if k != "edw_local_sqlite_file"} | {
    "run_env": "dev",
    "publish_bucket": "rag-silver",
    "edw_host": "edw.example.local",
    "edw_database": "EDW",
    "edw_read_user": "svc_r",
    "edw_read_password": _HEX,
    "edw_write_user": "svc_w",
    "edw_write_password": _HEX,
    "object_storage_endpoint": "https://os.example.local:9000",
    "object_storage_access_key": _HEX,
    "object_storage_secret_key": _HEX,
    "mcp_token": _HEX,
    "fulltext_sign_key": _HEX,
    "pipeline_image": "data-pipeline-runtime:0.0.0",
    "mcp_image": "mcp-server-runtime:0.0.0",
    "host_docs_dir": "/data/docs",
    "pg_container_name": "pgvector",
}
# (사례, 채울 칸, 비울 칸, 기대) — 기대가 local·dev면 시작, 그 밖의 글자는 PG 접속 거부 안내에 나와야 하는 칸 이름
CASES = (
    ("PC 개발자 — local 빈 칸만 채움", LOCAL, (), "local"),
    ("개발 서버 — dev 빈 칸만 채움", DEV, (), "dev"),
    ("개발 서버 — pg_schema를 비워 둠", DEV, ("pg_schema",), "required.pg.pg_schema"),
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
    for what, fills, empty, want in CASES:
        with tempfile.TemporaryDirectory() as d:
            y = Path(d) / "settings.yaml"
            y.write_text(_fill(text, {k: v for k, v in fills.items() if k not in empty}), encoding="utf-8")
            env = {"SETTINGS_FILE": str(y)}
            if want in ("local", "dev"):
                for cls in (S.CommonAppSettings, *S.app_classes().values()):
                    S.load(cls, file=y, environ={})  # STRICT — 모르는 칸·틀린 값이면 SettingsError
                for app in ("pipeline", "mcp"):
                    assert S.require_run_env(app, environ=env, sections=(app,)) == want, what
                with S.COMMON.override(file=y, environ={}):
                    assert pg.conf()["PG_SCHEMA"] == "rag_test", what
                if _HOST.is_file():
                    host = _host()
                    doc, err = host.load_or_error(y)
                    out = host.lines(doc, None)
                    image = any(x.startswith("export DATA_PIPELINE_IMAGE=") for x in out)  # local은 빈 칸 그대로 = 안 냄
                    assert err is None and f"export RUN_ENV='{want}'" in out and image == (want == "dev"), (what, err)
                continue
            with S.COMMON.override(file=y, environ={}):
                try:
                    pg.conf()
                except SystemExit as e:
                    assert want in str(e), (what, str(e))
                else:
                    raise AssertionError(f"{what}: 거부되지 않음")
