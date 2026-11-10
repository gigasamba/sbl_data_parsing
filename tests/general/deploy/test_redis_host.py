"""host_ctl.sh secrets(op-20) — settings_to_env.py --secrets-dir가 settings.yaml의 PG·Redis 비밀번호를 보호 파일(폴더 700 · 파일 600)로만
쓰고(pg_pw · redis/redis.conf·health.sh·start.sh), 값은 표준 출력·오류에 찍지 않으며, 같은 값으로 다시 부르면 아무것도 바꾸지 않는다.
비밀번호가 비거나 줄바꿈이 있으면 종료 2. 호스트 PyYAML 경로 그대로(PC 전용)."""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_host_env import _load

TOOL = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "settings_to_env.py"
PG = "pg-dummy-1"
REDIS = "dummy ' quoted $secret\\line"  # 셸 인용·JSON이 특수문자도 원래 값으로 돌려주는지
FILES = ("pg_pw", "redis/redis.conf", "redis/health.sh", "redis/start.sh")


def _yaml(pg, redis):
    return (
        "required:\n  env: {run_env: dev}\n"
        f"  pg: {{pg_password: {json.dumps(pg)}}}\n"
        f"common:\n  connections:\n    redis: {{redis_password: {json.dumps(redis)}}}\n"
    )


def _run(sf, directory):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}  # env 남김 — 하위 프로세스(호스트 python 대역)
    cmd = [sys.executable, str(TOOL), "--file", str(sf), "--secrets-dir", str(directory)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)


CASES = [  # (PG 비밀번호, Redis 비밀번호, 종료 코드, 표준 오류에 나올 문구)
    ("", REDIS, 2, "required.pg.pg_password"),
    (PG, "", 2, "common.connections.redis.redis_password"),
    (PG, "a\nb", 2, "줄바꿈"),
]


def test_secret_files():
    with tempfile.TemporaryDirectory() as d:
        sf, out = Path(d) / "settings.yaml", Path(d) / "secrets"
        for pg, redis, rc, msg in CASES:
            sf.write_text(_yaml(pg, redis), encoding="utf-8")
            r = _run(sf, out)
            assert r.returncode == rc and msg in r.stderr and not out.exists(), (pg, r.returncode, r.stderr)
            assert all(v not in r.stdout + r.stderr for v in (pg, redis) if v), "값이 출력에 나옴"
        sf.write_text(_yaml(PG, REDIS), encoding="utf-8")
        r1 = _run(sf, out)
        assert r1.returncode == 0 and r1.stdout.strip() == "changed" and not r1.stderr, r1.stderr
        before = [(out / n).stat().st_mtime_ns for n in FILES]
        r2 = _run(sf, out)  # 같은 값 — 바꾸지 않음
        assert r2.returncode == 0 and r2.stdout == "" and before == [(out / n).stat().st_mtime_ns for n in FILES]
        assert PG not in r1.stdout + r2.stdout and REDIS not in r1.stdout + r2.stdout
        if os.name != "nt":  # Windows(Git Bash)는 권한을 POSIX처럼 안 둠
            assert {stat.S_IMODE(p.stat().st_mode) for p in (out, out / "redis")} == {0o700}
            assert {stat.S_IMODE((out / n).stat().st_mode) for n in FILES} == {0o600}
        assert (out / "pg_pw").read_text(encoding="utf-8") == PG
        conf = (out / "redis" / "redis.conf").read_text(encoding="utf-8")
        assert conf.startswith("protected-mode yes\nbind 0.0.0.0\nport 6379\nappendonly yes\n"), conf.split("requirepass")[0]
        assert json.loads(conf.split("requirepass ", 1)[1]) == REDIS
        start = (out / "redis" / "start.sh").read_text(encoding="utf-8")
        assert "cp /conf/redis.conf /data/redis.conf" in start and "exec docker-entrypoint.sh redis-server /data/redis.conf" in start
        # health.sh의 셸 인용이 원래 비밀번호로 돌아오는지(값은 출력하지 않음 — 종료 코드로만)
        health = (out / "redis" / "health.sh").read_text(encoding="utf-8")
        assert "-p 6379 ping" in health
        check = Path(d) / "check.py"
        check.write_text("import os, sys\nraise SystemExit(0 if os.environ['REDISCLI_AUTH'] == sys.argv[1] else 1)\n", encoding="utf-8")
        script = Path(d) / "check.sh"
        script.write_text(health.split("exec redis-cli", 1)[0] + 'exec "$1" "$2" "$3"\n', encoding="utf-8", newline="\n")
        r = subprocess.run(["sh", str(script), sys.executable, str(check), REDIS], capture_output=True)
        assert r.returncode == 0 and not r.stdout and not r.stderr


def test_permission_error_hides_value():
    module = _load("secrets_host", TOOL.relative_to(DEPLOY_ROOT))
    doc = {"common": {"connections": {"pg": {"password": PG}, "redis": {"redis_password": REDIS}}}}  # 모델 배치(load_model)
    with tempfile.TemporaryDirectory() as d:
        errors = io.StringIO()
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(REDIS)), contextlib.redirect_stderr(errors):
            try:
                module.secret_files(doc, d)
            except ValueError as e:
                msg = str(e)
            else:
                raise AssertionError("권한 오류가 ValueError로 안 바뀜")
        assert "권한 확인" in msg and REDIS not in msg + errors.getvalue(), msg
