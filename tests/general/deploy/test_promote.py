"""promote.sh(op-21) — 단계 다섯 개를 차례로 찍고 돌리며 처음 실패에서 멈춘다. docker·mkdir·load.sh·host_ctl check는 대역(PC 전용)."""

import os
import subprocess
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_dc import _posix
from tests.general.deploy.test_trigger_gate import _bash

SCRIPT = DEPLOY_ROOT / "deploy" / "release" / "promote.sh"
STEPS = ["이미지 불러오기 0.5.0", "폴더 준비", "DB 판 올리기", "컨테이너 3개 띄우기", "배포 뒤 점검"]
# (docker 대역이 실패할 첫 낱말, 종료 코드, 마지막으로 시작한 단계 수)
CASES = [("", 0, 5), ("run", 1, 3)]


def test_promote_steps():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "bin").mkdir()
        (d / "images").mkdir()
        stubs = {
            "bin/dk": '#!/bin/bash\n[ "$1" = "$DK_FAIL" ] && exit 1\necho "dk $*"\n',
            "bin/mkdir": '#!/bin/sh\necho "mkdir $*"\n',  # 저장소 밖(벌 home)에 폴더를 만들지 않게
            "images/load.sh": '#!/bin/bash\necho "load $1"\n',
            "fake.sh": 'case "$1" in selftest*) echo "[판정] 통과 — FAIL 0" ;; *) echo "ok $1" ;; esac\n',
        }
        for rel, body in stubs.items():
            (d / rel).write_text(body, encoding="utf-8", newline="\n")
            (d / rel).chmod(0o755)
        sf = d / "settings.yaml"
        sf.write_text("required:\n  env: {run_env: prd}\n", encoding="utf-8")
        cmd = f'PATH="{_posix(d / "bin")}:$PATH" exec bash "{_posix(SCRIPT)}" 0.5.0 "{_posix(d / "images")}" --dim 1024'
        for fail, rc, last in CASES:
            env = {  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": _posix(sf),
                "SETTINGS_LOADED": _posix(sf),
                "RUN_ENV": "prd",
                "DOCKER": "dk",
                "DK_FAIL": fail,
                "APP_OUTPUT_ROOT": "/app/output",
                "DC_FAKE": f"bash {_posix(d / 'fake.sh')}",
            }
            r = subprocess.run([bash, "-c", cmd], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            started = [ln[len("== 1. ") :] for ln in r.stdout.splitlines() if ln.startswith("== ")]
            assert r.returncode == rc and started == STEPS[:last], (fail, r.returncode, r.stdout, r.stderr)
            if not rc:
                assert (
                    "load 0.5.0" in r.stdout
                    and "dk run --rm --user 0 --network host" in r.stdout
                    and "migrate up --target all --dim 1024" in r.stdout
                ), r.stdout
                assert "compose -f deploy/host/compose/compose-prd.yml up -d --force-recreate" in r.stdout, r.stdout
                assert r.stdout.rstrip().endswith("[promote] 통과 — 0.5.0"), r.stdout
