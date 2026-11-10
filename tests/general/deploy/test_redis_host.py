"""Redis compose 보호 설정 생성·비밀번호 인자 미노출 — 호스트 PyYAML 경로 그대로 검증."""

import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT


def test_redis_config_and_secret():
    path = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "settings_to_env.py"
    spec = importlib.util.spec_from_file_location("redis_host_settings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    secret = "dummy ' quoted $secret\\line"
    doc = {"common": {"connections": {"redis": {"redis_port": 56379, "redis_password": secret}}}}
    with tempfile.TemporaryDirectory() as directory:
        assert module.redis_files(doc, directory)
        files = [Path(directory) / n for n in ("redis.conf", "health.sh", "start.sh")]
        before = [p.stat().st_mtime_ns for p in files]
        assert not module.redis_files(doc, directory)
        assert before == [p.stat().st_mtime_ns for p in files]
        assert stat.S_IMODE(Path(directory).stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)
        start = files[2].read_text(encoding="utf-8")
        assert "cp /conf/redis.conf /data/redis.conf" in start
        assert "chmod 600 /data/redis.conf" in start
        assert "exec docker-entrypoint.sh redis-server /data/redis.conf" in start
        cfg = Path(directory) / "redis.conf"
        health = Path(directory) / "health.sh"
        assert stat.S_IMODE(cfg.stat().st_mode) == stat.S_IMODE(health.stat().st_mode) == 0o600
        body = cfg.read_text(encoding="utf-8")
        assert "bind 127.0.0.1\nport 56379\nappendonly yes\nappendfsync everysec\ndir /data\n" in body
        assert json.loads(body.split("requirepass ", 1)[1]) == secret
        # 보호 파일의 셸 인용이 특수문자도 원래 비밀번호로 복원함(값은 출력하지 않음).
        shell = health.read_text(encoding="utf-8").split("exec redis-cli", 1)[0]
        script = Path(directory) / "check.sh"
        check = Path(directory) / "check.py"
        check.write_text(
            "import os, sys\nraise SystemExit(0 if os.environ['REDISCLI_AUTH'] == sys.argv[1] else 1)\n", encoding="utf-8"
        )  # env 남김 — 호스트 셸 대역의 라이브러리 인증 신호
        script.write_text(shell + 'exec "$1" "$2" "$3"\n', encoding="utf-8")
        result = subprocess.run(["sh", str(script), sys.executable, str(check), secret], capture_output=True)
        assert result.returncode == 0 and not result.stdout and not result.stderr
        assert module.redis_files({"common": {}}, directory)
        assert "requirepass" not in cfg.read_text(encoding="utf-8") and "REDISCLI_AUTH" not in health.read_text(encoding="utf-8")


def test_redis_compose_and_health():
    import yaml

    compose = DEPLOY_ROOT / "deploy" / "host" / "compose"
    service = yaml.safe_load((compose / "compose.redis.yml").read_text(encoding="utf-8"))["services"]["mcp-redis"]
    assert service["network_mode"] == "host" and service["restart"] == "unless-stopped"
    assert service["command"] == ["sh", "/conf/start.sh"]
    assert service["healthcheck"]["test"] == ["CMD", "sh", "/conf/health.sh"]
    assert all(str(v).endswith((":z", ":ro,z")) for v in service["volumes"])
    assert "${REDIS_CONF_DIR:-${RAG_ROOT}/redis-conf}:/conf:ro,z" in service["volumes"]
    parsing = yaml.safe_load((compose / "compose.data-parsing.yml").read_text(encoding="utf-8"))["services"]["mcp-data-parsing"]
    assert parsing["healthcheck"]["test"] == ["CMD", "python", "-m", "pipeline.run_mcp_parsing", "--health"]
    mcp = yaml.safe_load((compose / "compose.mcp-server.yml").read_text(encoding="utf-8"))["services"]["mcp"]
    assert any(str(v).endswith("/_mcp_parse/jobs:z") for v in mcp["volumes"])
    assert any("APP_OUTPUT_ROOT" in str(v) and str(v).endswith(":ro,z") for v in mcp["volumes"])


def test_prepare_jobs_non_root():
    import shlex

    script = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "load_settings.sh"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "output"
        (output / "_mcp_parse" / "jobs").mkdir(parents=True)
        calls = Path(directory) / "mutations"
        for mode, expected in (("drwxrwsr-x", 0), ("drwxr-sr-x", 2)):
            shell = f""". {shlex.quote(str(script))}
RAG_OUT={shlex.quote(str(output))}
id() {{ echo 2000; }}
ls() {{
  case "$1" in
    -nd) echo '2775 1 10001 10001 0 jobs' ;;
    -ld) echo '{mode} 1 10001 10001 0 jobs' ;;
  esac
}}
chmod() {{ echo chmod >> {shlex.quote(str(calls))}; return 1; }}
chown() {{ echo chown >> {shlex.quote(str(calls))}; return 1; }}
chgrp() {{ echo chgrp >> {shlex.quote(str(calls))}; return 1; }}
prepare_jobs
"""
            result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, encoding="utf-8")
            assert result.returncode == expected and not calls.exists(), (mode, result.stderr)
            if expected:
                assert "UID 10001" in result.stderr and "그룹 쓰기" in result.stderr


def test_keepalive_continues_after_redis_failure():
    import shlex

    original = DEPLOY_ROOT / "deploy" / "host" / "scripts"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / "deploy" / "host" / "scripts"
        scripts.mkdir(parents=True)
        commands = root / "commands.log"
        marker = root / "first-health"
        # 실제 스크립트를 복사하되 load_settings·컨테이너 명령·HTTP만 대역으로 바꾼다.
        (scripts / "mcp_keepalive.sh").write_bytes((original / "mcp_keepalive.sh").read_bytes())
        docker = root / "docker-stub"
        docker.write_text(
            f"""#!/bin/bash
printf '%s\\n' "$*" >> {shlex.quote(str(commands))}
case "$*" in
  *inspect*State.Running*) echo false ;;
  *inspect*State.Status*) echo exited ;;
  *up*\\ mcp-redis|*up*\\ mcp-data-parsing) exit 1 ;;
esac
""",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        python = root / "python3"
        python.write_text(
            f"""#!/bin/bash
if [ ! -e {shlex.quote(str(marker))} ]; then touch {shlex.quote(str(marker))}; exit 1; fi
exit 0
""",
            encoding="utf-8",
        )
        python.chmod(0o755)
        (scripts / "load_settings.sh").write_text(
            f"""load_settings() {{
  DOCKER={shlex.quote(str(docker))}
  INSTANCE=
  NAME_SUFFIX=
  MCP_CNAME=mcp-server
  DATA_PARSING_CNAME=mcp-data-parsing
  export DOCKER
  CODE_DIR=
  MCP_HOST=127.0.0.1
  MCP_PORT=8765
  PATH={shlex.quote(str(root))}:$PATH
}}
prepare_jobs() {{ return 2; }}
prepare_redis() {{ return 2; }}
""",
            encoding="utf-8",
        )
        (scripts / "host_ctl.sh").write_text(
            '. deploy/host/scripts/load_settings.sh; load_settings\nshift; $DOCKER compose -f compose.mcp-server.yml "$@"\n',
            encoding="utf-8",
        )
        result = subprocess.run(["bash", str(scripts / "mcp_keepalive.sh")], capture_output=True, text=True, encoding="utf-8", timeout=15)
        logged = commands.read_text(encoding="utf-8")
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "jobs 준비 실패" in result.stderr and "Redis 설정 준비 실패" in result.stderr
        assert "Redis 기동 실패" in result.stderr and "mcp-data-parsing 띄우기 실패" in result.stderr
        assert "compose.mcp-server.yml up -d mcp" in logged, logged


def test_numbered_keepalive_has_no_services():
    original = DEPLOY_ROOT / "deploy" / "host" / "scripts"
    with tempfile.TemporaryDirectory() as directory:
        scripts = Path(directory) / "deploy" / "host" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "mcp_keepalive.sh").write_bytes((original / "mcp_keepalive.sh").read_bytes())
        (scripts / "load_settings.sh").write_text(
            "load_settings() { INSTANCE=2; DOCKER=false; }\n"
            "prepare_jobs() { echo unexpected-jobs; return 1; }\n"
            "prepare_redis() { echo unexpected-redis; return 1; }\n",
            encoding="utf-8",
        )
        result = subprocess.run(["bash", str(scripts / "mcp_keepalive.sh")], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0 and result.stdout == result.stderr == "", (result.stdout, result.stderr)


def test_redis_host_password_required():
    import pytest

    path = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "settings_to_env.py"
    spec = importlib.util.spec_from_file_location("redis_password_settings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for run in ("local", "dev", "prd"):
        for password in (None, "   ", "test-secret"):
            doc = {"common": {"run_env": run, "connections": {"redis": {"redis_password": password}}}}
            with tempfile.TemporaryDirectory() as d:
                target = Path(d) / "conf"
                if run != "local" and not (password or "").strip():
                    with pytest.raises(ValueError, match="common.connections.redis.redis_password"):
                        module.redis_files(doc, target)
                    assert not target.exists()
                else:
                    module.redis_files(doc, target)
                    assert "protected-mode yes" in (target / "redis.conf").read_text(encoding="utf-8")


def test_prepare_redis_change_and_restart():
    import shlex

    script = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "load_settings.sh"
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        settings = root / "settings.yaml"
        settings.write_text(
            "required:\n  env:\n    run_env: local\ncommon:\n  connections:\n    redis:\n      redis_port: 56379\n", encoding="utf-8"
        )
        calls = root / "calls"
        shell = f"""set -eu
. {shlex.quote(str(script))}
RAG_ROOT={shlex.quote(str(root))}
SETTINGS_FILE={shlex.quote(str(settings))}
PY={shlex.quote(sys.executable)}
DATA_PARSING_CNAME=parsing
MCP_CNAME=mcp
DOCKER=docker_stub
docker_stub() {{
  case "$1" in
    inspect) case "$*" in *parsing) echo false ;; *) echo true ;; esac ;;
    restart) echo "$2" >> {shlex.quote(str(calls))} ;;
  esac
}}
prepare_redis
[ "$REDIS_CONF_CHANGED" = 1 ]
restart_redis_changed
prepare_redis
[ "$REDIS_CONF_CHANGED" = 0 ]
restart_redis_changed
"""
        result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert calls.read_text(encoding="utf-8").splitlines() == ["mcp-redis", "mcp"]
        assert (root / "redis-conf" / "start.sh").is_file() and not (root / "redis").exists()
        assert "Redis 보호 설정 변경" in result.stdout
        # CLI는 값 없이 변경 여부만 출력하고 동일 내용은 조용히 끝냄.
        command = [
            sys.executable,
            str(script.parent / "settings_to_env.py"),
            "--file",
            str(settings),
            "--redis-dir",
            str(root / "other-conf"),
        ]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        again = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        assert first.returncode == again.returncode == 0
        assert first.stdout == "changed\n" and not again.stdout


def test_changed_config_restarts_apps_when_redis_stopped():
    import shlex

    script = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "load_settings.sh"
    with tempfile.TemporaryDirectory() as d:
        calls = Path(d) / "calls"
        shell = f"""set -eu
. {shlex.quote(str(script))}
REDIS_CONF_CHANGED=1
DATA_PARSING_CNAME=parsing
MCP_CNAME=mcp
DOCKER=docker_stub
docker_stub() {{
  case "$1" in
    inspect) case "$*" in *mcp-redis) echo false ;; *) echo true ;; esac ;;
    restart) echo "$2" >> {shlex.quote(str(calls))} ;;
  esac
}}
restart_redis_changed
"""
        result = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert calls.read_text(encoding="utf-8").splitlines() == ["parsing", "mcp"]


def test_redis_config_permission_errors_are_actionable():
    import contextlib
    import io
    from unittest import TestCase, mock

    path = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "settings_to_env.py"
    spec = importlib.util.spec_from_file_location("redis_permission_settings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    secret = "dummy-private-marker"
    doc = {"common": {"connections": {"redis": {"redis_password": secret}}}}
    with tempfile.TemporaryDirectory() as d:
        module.redis_files(doc, d)
        for target, attribute in ((Path, "read_text"), (Path, "chmod"), (module.tempfile, "mkstemp")):
            with mock.patch.object(target, attribute, side_effect=PermissionError(secret)):
                with TestCase().assertRaisesRegex(ValueError, "소유자·권한 확인") as caught:
                    # port를 바꿔 mkstemp도 반드시 실행한다.
                    changed = {"common": {"connections": {"redis": {"redis_port": 56380, "redis_password": secret}}}}
                    module.redis_files(changed, d)
            error = str(caught.exception)
            assert d in error and "server-guide §4-6" in error and secret not in error
        output, errors = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(module, "load_or_error", return_value=(doc, None)),
            mock.patch.object(Path, "read_text", side_effect=PermissionError(secret)),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            assert module.main(["--file", str(Path(d) / "settings.yaml"), "--redis-dir", d]) == 2
        assert not output.getvalue()
        assert "Redis 설정 폴더/파일을 읽거나 쓰지 못함" in errors.getvalue()
        assert "Traceback" not in errors.getvalue() and secret not in errors.getvalue()


def test_direct_redis_start_matches_compose():
    guide = (DEPLOY_ROOT / "docs" / "operations" / "server-guide.md").read_text(encoding="utf-8")
    start = guide.split("$DOCKER run -d --name mcp-redis", 1)[1].split(" )", 1)[0]
    assert '-v "${REDIS_CONF_DIR:-$RAG_ROOT/redis-conf}:/conf:ro,z"' in start
    assert '"${REDIS_IMAGE:-redis:7.4.2-alpine}" sh /conf/start.sh' in start
    assert "redis-server /data/redis.conf" not in start
