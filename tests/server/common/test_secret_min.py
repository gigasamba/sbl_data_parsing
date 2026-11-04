"""서버 비밀 최소 길이: 시작 관문, 경로만 오류, local 경계 정책 유지."""

import contextlib
import io
import json
import tempfile
from pathlib import Path

import yaml

from common.config import layout, settings


def test_start_secret_policy():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "settings.yaml"
        for run in ("dev", "prd", "local"):
            for value, suffix, rejected in (
                ("seven77", "", True),
                ("a://xyz", "", True),
                ("eight888", "", False),
                ("", "", False),
                (None, "", False),
                (json.dumps({"driver": "x", "host": "y", "items": ["a", {"pwd": "seven77"}]}), ".items[1].pwd", True),
                (json.dumps({"password": "eight888", "token": "", "token_budget": "x"}), "", False),
                ("{}", "", False),
                ("postgresql://u:seven77@localhost/db", ".password", True),
                ("postgresql://u:eight888@localhost/db", "", False),
                ("postgresql://u:@localhost/db", "", False),
                ("postgresql://u:abc%64efg@localhost/db", ".password", True),
            ):
                json_or_dsn = bool(suffix) or bool(value and (value.startswith(("{", "postgresql:"))))
                field = "connect_kwargs" if json_or_dsn else "password"
                connection = "rdb" if json_or_dsn else "pg"
                doc = {"common": {"run_env": run, "connections": {connection: {field: value}}}}
                path.write_text(yaml.safe_dump(layout.to_file(doc)), encoding="utf-8")
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    try:
                        actual = settings.require_run_env(environ={"SETTINGS_FILE": str(path)}, sections=("mcp",))
                    except SystemExit as exc:
                        assert exc.code == 2 and rejected and run != "local"
                        message = errors.getvalue()
                        assert f"common.connections.{connection}.{field}{suffix}" in message
                        assert "seven77" not in message and "abcdefg" not in message
                        assert "8" not in message and "7" not in message
                    else:
                        assert actual == run and (not rejected or run == "local")
        # 앱 전용 비밀도 같은 시작 관문에서 검사한다.
        for run in ("dev", "prd"):
            path.write_text(
                yaml.safe_dump(layout.to_file({"common": {"run_env": run}, "mcp": {"server": {"fulltext_secret": "seven77"}}})),
                encoding="utf-8",
            )
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                try:
                    settings.require_run_env(environ={"SETTINGS_FILE": str(path)}, sections=("mcp",))
                except SystemExit as exc:
                    assert exc.code == 2 and "mcp.server.fulltext_secret" in errors.getvalue() and "seven77" not in errors.getvalue()
                else:
                    raise AssertionError("short app secret accepted")
