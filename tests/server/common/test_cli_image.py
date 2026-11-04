"""MCP 이미지의 최소 pipeline 패키지(cli/config만)로 실제 CLI selftest에 진입한다."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common.config import settings
from common.core import paths


def test_selftest_without_pipeline_stages():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # common도 같은 뿌리에 두어 자식 실행기의 PYTHONPATH가 개발 트리를 앞세우지 않게 한다.
        shutil.copytree(
            paths.DEPLOY_ROOT / "common",
            root / "common",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "output", "settings*.yaml", ".env*"),
        )
        package = root / "pipeline"
        package.mkdir()
        # deploy/docker/Dockerfile의 MCP COPY와 같은 세 파일. shared·extract 등은 없다.
        for name in ("__init__.py", "cli.py", "config.py"):
            shutil.copyfile(paths.DEPLOY_ROOT / "pipeline" / name, package / name)
        for relative in ("tests", "tests/server", "tests/server/common"):
            folder = root / relative
            folder.mkdir(exist_ok=True)
            (folder / "__init__.py").write_text("", encoding="utf-8")
        shutil.copyfile(paths.DEPLOY_ROOT / "tests" / "runner.py", root / "tests" / "runner.py")
        (root / "tests" / "server" / "common" / "test_ready.py").write_text("def test_ready():\n    assert 2 + 2 == 4\n", encoding="utf-8")
        base = paths.child_env(
            {
                "PYTHONPATH": os.pathsep.join((str(root), str(paths.DEPLOY_ROOT))),
                "RAG_MODULE": "mcp",  # env 남김 — 이미지 종류 내부 신호: 최소 MCP 배치를 재현
            }
        )
        env = settings.child_env(base, RUN_ENV="local", PIPE_OUT_ROOT=str(root / "output"))
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.cli", "selftest"],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        try:
            output, _ = proc.communicate(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=10)
        assert proc.returncode == 0, output
        assert "PASS tests.server.common.test_ready" in output and "1/1 통과" in output, output
