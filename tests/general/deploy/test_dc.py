"""host_ctl.sh(사용자 11-03 — 옛 README dc() 셸 함수를 대신함) — 상주 컨테이너 3개의 compose 파일을 늘 함께 붙이고, 실행 이미지(*-runtime)거나
CODE_DIR를 주면 compose.code*.yml 셋을 더한 뒤 인자를 그대로 넘기는지. DOCKER=echo로 명령 줄만 본다(docker·설정 읽기 없음 — PC 전용)."""

import os
import subprocess
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_trigger_gate import _bash

SCRIPT = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "host_ctl.sh"
BASE = ["compose.pipeline.yml", "compose.data-parsing.yml", "compose.mcp-server.yml"]
CODE = ["compose.code.yml", "compose.code.data-parsing.yml", "compose.code.mcp-server.yml"]
PORTS = {"MCP_PORT": "8775", "DATA_PARSING_PORT": "8776"}  # 여러 벌은 포트가 기본값이 아니어야 함
CASES = [  # (DATA_PIPELINE_IMAGE, CODE_DIR, 코드 덧씌우기?, ops.host.instance, 그 밖 env, compose 묶음 이름 — 종료 코드 2면 거부 문구)
    ("data-pipeline:0.2.0", "", False, "", {}, "compose"),  # 코드가 든 이미지(운영) · 한 벌 — 묶음 이름은 compose 기본 그대로
    ("data-pipeline-runtime:0.2.0", "", True, "", {}, "compose"),  # 실행 이미지(개발) — 이 코드 폴더를 붙임
    ("data-pipeline:0.2.0", "/srv/x/code", True, "", {}, "compose"),  # CODE_DIR를 주면 그 값
    ("data-pipeline:0.2.0", "", False, "hong", PORTS, "compose-hong"),  # 여러 벌 — 묶음 이름 끝 -<instance>
    ("data-pipeline:0.2.0", "", False, "Hong_1", PORTS, "!ops.host.instance"),  # 영소문자·숫자·-만 — 시작 거부
    ("data-pipeline:0.2.0", "", False, "hong", {"MCP_PORT": "8775"}, "!data_parsing_port"),  # 여러 벌인데 기본 포트 — 거부
    ("data-pipeline:0.2.0", "", False, "hong", {"DATA_PARSING_PORT": "8776"}, "!search.server.port"),
    ("data-pipeline:0.2.0", "", False, "hong", {**PORTS, "RUN_ENV": "prd"}, "!운영(prd)"),  # prd는 한 벌
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
        p = sf.resolve().as_posix()
        sp = f"/{p[0].lower()}{p[2:]}" if p[1:2] == ":" else p  # Git Bash(Windows)가 절대 경로로 보는 꼴
        for image, code, overlay, inst, extra, project in CASES:
            env = {  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": sp,
                "SETTINGS_LOADED": sp,  # 이미 읽은 것으로 — settings_to_env.py(PyYAML)를 부르지 않음
                "DOCKER": "echo",
                "DATA_PIPELINE_IMAGE": image,
                "INSTANCE": inst,
                **extra,
            }
            if code:
                env["CODE_DIR"] = code
            r = subprocess.run(
                [bash, str(SCRIPT), "up", "-d", "mcp"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30
            )
            if project.startswith("!"):
                assert r.returncode == 2 and project[1:] in r.stderr, (inst, extra, r.returncode, r.stderr)
                continue
            assert r.returncode == 0, (image, code, r.stderr)
            files = [w.rsplit("/", 1)[-1] for w in r.stdout.split() if w.endswith(".yml")]
            assert r.stdout.split()[:3] == ["compose", "-p", project] and r.stdout.split()[-3:] == ["up", "-d", "mcp"], r.stdout
            assert files == BASE + (CODE if overlay else []), (image, code, files)
