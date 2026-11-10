"""개발 작업 공간(op-17·op-18): 이미지 ENTRYPOINT dev_entry.sh는 `devbox`만 sshd로, 그 밖의 명령은 인자 그대로 APP_ENTRY(이미지의 시작
스크립트)로 넘긴다. compose 파일의 SSH 컨테이너·포트는 test_compose.py 표. git_cred.py는 git 이름·메일만 쓴다.
sshd가 실제로 뜨는지는 이미지 시험(server-guide §2-13) — 여기는 bash만(PC 전용)."""

import os
import subprocess
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_dc_init import _posix
from tests.general.deploy.test_trigger_gate import _bash

ENTRY = DEPLOY_ROOT / "deploy" / "docker" / "devbox" / "dev_entry.sh"
CASES = [  # 컨테이너 명령 인자 → APP_ENTRY가 받는 인자(한 줄에 하나)
    (["selftest", "--only", "a b"], ["selftest", "--only", "a b"]),
    (["help"], ["help"]),
    (["run-mcp-parsing"], ["run-mcp-parsing"]),
    (["idle"], ["idle"]),
    ([], []),  # 이미지 CMD(help)가 없을 때도 앱 시작 스크립트로
]


def test_dev_entry_dispatch():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    assert subprocess.run([bash, "-n", str(ENTRY)], capture_output=True).returncode == 0
    with tempfile.TemporaryDirectory() as d:
        stub = Path(d) / "app_entry.sh"
        stub.write_text('#!/usr/bin/env bash\nfor a in "$@"; do echo "$a"; done\n', encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        env = {"PATH": os.environ.get("PATH", ""), "APP_ENTRY": _posix(stub)}  # env 남김 — 하위 프로세스(이미지가 주는 APP_ENTRY 대역)
        for args, want in CASES:
            r = subprocess.run([bash, str(ENTRY), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            assert r.returncode == 0 and r.stdout.splitlines() == want, (args, r.returncode, r.stdout, r.stderr)


GIT_CRED = ENTRY.parent / "git_cred.py"
# 한 홈에서 차례로: (이름, 메일) → 기대 ~/.gitconfig 칸(누적 — 비운 칸은 그대로)
NAME_STEPS = [
    (("홍길동", "dev1@corp.test"), {"user.name": "홍길동", "user.email": "dev1@corp.test"}),
    ((None, "dev2@corp.test"), {"user.name": "홍길동", "user.email": "dev2@corp.test"}),
    ((None, None), {"user.name": "홍길동", "user.email": "dev2@corp.test"}),
]


def _gitconfig(home):
    f = Path(home) / ".gitconfig"
    if not f.exists():
        return {}
    r = subprocess.run(["git", "config", "--file", str(f), "--list"], capture_output=True, text=True, encoding="utf-8")
    return dict(line.split("=", 1) for line in r.stdout.splitlines())


def test_git_cred():
    import importlib.util
    import shutil

    if not shutil.which("git"):
        print("[시험] git 없음 — 건너뜀")
        return
    spec = importlib.util.spec_from_file_location("git_cred", GIT_CRED)
    gc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    with tempfile.TemporaryDirectory() as home:
        for args, want in NAME_STEPS:
            gc.setup(home, *args)
            assert _gitconfig(home) == want, args
        assert not (Path(home) / ".git-credentials").exists()  # 자격 파일은 쓰지 않음
