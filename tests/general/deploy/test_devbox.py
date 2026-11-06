"""개발 작업 공간(option.devbox — op-17): 이미지 ENTRYPOINT dev_entry.sh는 `devbox`만 sshd로, 그 밖의 명령은 인자 그대로 APP_ENTRY(이미지의 시작
스크립트)로 넘기고, compose.dev.yml은 data-pipeline을 `devbox`로 띄우며 코드 폴더를 compose.code.yml과 같은 자리에 쓰기 가능으로·홈을 <루트>/home에 붙인다.
host_ctl.sh가 파일을 더하는 조건(포트·prd·코드가 든 이미지)은 test_dc.py 표. sshd가 실제로 뜨는지는 이미지 시험(README §5) — 여기는 bash만(PC 전용)."""

import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_dc_init import _posix
from tests.general.deploy.test_trigger_gate import _bash

ENTRY = DEPLOY_ROOT / "deploy" / "docker" / "devbox" / "dev_entry.sh"
COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"
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


def _svc(name):
    return yaml.safe_load((COMPOSE / name).read_text(encoding="utf-8"))["services"]["data-pipeline"]


def _target(v):
    """마운트 줄 `${원본}:${자리}:선택지` → [자리, 선택지]."""
    return v.split("}:", 1)[1].rsplit(":", 1)


def test_compose_dev():
    dev, code = _svc("compose.dev.yml"), _svc("compose.code.yml")
    assert dev["command"] == ["devbox"] and "DEVBOX_SSH_PORT" in dev["environment"]["SSH_PORT"]
    ro = code["volumes"][0]
    assert _target(ro)[1] == "ro,z" and _target(dev["volumes"][0]) == [_target(ro)[0], "z"], dev["volumes"][0]  # 같은 자리 — 쓰기 가능
    assert dev["volumes"][1].endswith("/home:/home/rag:z"), dev["volumes"]
    oc = _svc("compose.opencode.yml")
    assert oc["volumes"][0].endswith(":" + oc["environment"]["OPENCODE_CONFIG"] + ":ro,z"), oc
