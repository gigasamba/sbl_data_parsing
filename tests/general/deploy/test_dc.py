"""host_ctl.sh(op-20) — compose 하위 명령은 `docker compose -f deploy/host/compose/compose-<run_env>.yml <인자…>` 그대로(덧붙임 파일·
묶음 이름 계산 없음), 모르는 run_env면 종료 2. mcp_keepalive.sh는 0번 벌만(redis·mcp-data-parsing-0·mcp-server-0) 보고 /health는
http://127.0.0.1:8051/health. DOCKER=echo·대역 명령으로 명령 줄만 본다(docker·설정 읽기 없음 — PC 전용)."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_trigger_gate import _bash

SCRIPT = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "host_ctl.sh"


def _posix(p):
    p = Path(p).resolve().as_posix()
    return f"/{p[0].lower()}{p[2:]}" if p[1:2] == ":" else p  # Git Bash(Windows)가 절대 경로로 보는 꼴


CASES = [  # (run_env, 인자, 종료 코드, 표준 출력(compose 파일 자리는 이름만) 또는 표준 오류에 나올 문구)
    ("local", ["up", "-d"], 0, "compose -f compose-local.yml up -d"),
    ("dev", ["up", "-d", "mcp-server-0"], 0, "compose -f compose-dev.yml up -d mcp-server-0"),
    ("prd", ["ps"], 0, "compose -f compose-prd.yml ps"),
    ("prd", ["logs", "--tail", "5", "data-pipeline-0"], 0, "compose -f compose-prd.yml logs --tail 5 data-pipeline-0"),
    ("qa", ["up", "-d"], 2, "required.env.run_env는 local·dev·prd"),
]


def test_dc_command():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    assert subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True).returncode == 0
    with tempfile.TemporaryDirectory() as d:
        sf = Path(d) / "settings.yaml"
        sf.write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
        for run_env, args, rc, want in CASES:
            env = {  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": _posix(sf),
                "SETTINGS_LOADED": _posix(sf),  # 이미 읽은 것으로 — settings_to_env.py(PyYAML)를 부르지 않음
                "RUN_ENV": run_env,
                "DOCKER": "echo",
            }
            r = subprocess.run([bash, str(SCRIPT), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            assert r.returncode == rc, (run_env, args, r.returncode, r.stderr)
            if rc:
                assert want in r.stderr, r.stderr
                continue
            words = [w.rsplit("/", 1)[-1] if w.endswith(".yml") else w for w in r.stdout.split()]
            assert " ".join(words) == want, r.stdout


STUB = (
    "from pathlib import Path\nprint(f\"export DOC_SRC='{Path(__file__).parents[3].name}'\")\n"  # settings_to_env.py 대역 — 루트 이름을 냄
)


def test_stale_shell_reads_own_root():
    """루트 a에서 load_settings를 source한 셸(env를 물려받음)로 루트 b의 스크립트를 불러도 b의 루트·설정 파일·설정 값을 쓴다.
    셸에서 사람이 준 값(DOCKER)은 그대로 이긴다."""
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        ls = {}
        for name in ("a", "b"):
            root = Path(d) / name
            scripts = root / "deploy" / "host" / "scripts"  # 루트 = 코드 폴더
            scripts.mkdir(parents=True)
            (scripts / "load_settings.sh").write_bytes((SCRIPT.parent / "load_settings.sh").read_bytes())
            (scripts / "settings_to_env.py").write_text(STUB, encoding="utf-8")
            (root / "settings.yaml").write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
            ls[name] = _posix(scripts / "load_settings.sh")
        inner = f'. {ls["b"]} && load_settings && echo "$RAG_ROOT|$SETTINGS_FILE|$DOC_SRC|$DOCKER"'
        cmd = f". {ls['a']} && load_settings && export DOC_SRC && bash -c '{inner}'"
        env = {
            "PATH": os.environ.get("PATH", ""),  # env 남김 — 하위 프로세스(시험 셸)
            "PY": Path(sys.executable).as_posix(),
            "DOCKER": "echo",
        }
        r = subprocess.run([bash, "-c", cmd], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        root_b = ls["b"].rsplit("/deploy/", 1)[0]
        assert r.stdout.strip() == f"{root_b}|{root_b}/settings.yaml|b|echo", r.stdout


# (redis 상태, mcp-data-parsing-0 Running, mcp-server-0 상태, 기대 docker 명령(앞 낱말들))
#   /health는 늘 응답 없음(대역 python3 실패) — 다시 띄운 뒤에도 없어 종료 1
KEEP_CASES = [
    ("true healthy", "true", "running", [["restart", "mcp-server-0"]]),
    ("true unhealthy", "true", "running", [["restart", "redis"], ["restart", "mcp-server-0"]]),
    (
        "",
        "false",
        "none",
        [
            ["compose", "--env-file", ".env", "-f", "compose-redis.yml", "up", "-d"],
            ["compose", "-f", "compose-dev.yml", "up", "-d", "mcp-data-parsing-0"],
            ["compose", "-f", "compose-dev.yml", "up", "-d", "mcp-server-0"],
        ],
    ),
]


def test_keepalive():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        stub = Path(d) / "bin"
        stub.mkdir()
        calls = Path(d) / "py.log"  # 호스트 python3 대역이 받은 인자(/health 주소)
        py = f'#!/bin/sh\necho "$*" >> "{_posix(calls)}"\nexit 1\n'
        # 컨테이너 도구 대역: inspect는 STATE_<컨테이너> 값, 그 밖은 명령 줄을 log에
        log = Path(d) / "dk.log"
        dk = (
            "#!/bin/bash\n"
            'if [ "$1" = inspect ]; then n=${@: -1}; n=STATE_${n//-/_}; echo "${!n:-}"; [ -n "${!n:-}" ]; exit; fi\n'
            f'echo "$*" >> "{_posix(log)}"\n'
        )
        for exe, body in (("python3", py), ("sleep", "#!/bin/sh\nexit 0\n"), ("dk", dk)):
            (stub / exe).write_text(body, encoding="utf-8", newline="\n")
            (stub / exe).chmod(0o755)
        sf = Path(d) / "settings.yaml"
        sf.write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
        script = _posix(SCRIPT.parent / "mcp_keepalive.sh")
        # 대역을 PATH 맨 앞에 — Git Bash(Windows) 입구는 시작 때 /usr/bin을 앞에 붙이므로 셸 안에서 붙이고 bash를 다시 부름
        cmd = f'PATH="{_posix(stub)}:$PATH" exec bash "{script}"'
        for redis, parse, mcp, want in KEEP_CASES:
            calls.write_text("", encoding="utf-8")
            log.write_text("", encoding="utf-8")
            env = {  # env 남김 — 하위 프로세스(시험 셸 — 대역 docker가 읽는 상태)
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": _posix(sf),
                "SETTINGS_LOADED": _posix(sf),
                "RUN_ENV": "dev",
                "DOCKER": "dk",
                "STATE_redis": redis,
                "STATE_mcp_data_parsing_0": parse,
                "STATE_mcp_server_0": "" if mcp == "none" else mcp,
            }
            r = subprocess.run([bash, "-c", cmd], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            got = [
                [w.rsplit("/", 1)[-1] if w.endswith(".yml") else w for w in line.split()]
                for line in log.read_text(encoding="utf-8").splitlines()
                if not line.startswith("logs ")
            ]
            assert r.returncode == 1 and got == want, (redis, parse, mcp, got, r.stdout, r.stderr)
            assert "http://127.0.0.1:8051/health" in calls.read_text(encoding="utf-8"), calls.read_text(encoding="utf-8")
