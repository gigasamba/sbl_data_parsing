"""코드 폴더 셸 조각 — 실행 이미지 시작 기록의 코드 커밋(runtime_entry.sh)과 운영 코드 묶음(bake_prod_image.sh)에서 뺄 것.
스크립트에서 그 블록만 떼어 bash로 돌린다(docker·이미지 없음, PC 전용 — git·tar가 있는 bash 필요)."""

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_trigger_gate import _bash

ROOT = DEPLOY_ROOT  # 저장소 루트(paths 상수)


def _block(rel, pattern):
    text = (ROOT / rel).read_text(encoding="utf-8")
    m = re.search(pattern, text, re.S | re.M)
    assert m, f"{rel}에 블록이 없음"
    return m.group(0)


def _run(bash, script, env):
    r = subprocess.run(
        [bash, "-c", script],
        env={**os.environ, **env},  # env 남김 — 하위 프로세스(셸 조각의 입력 — 시험)
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def _git(d, *args):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


# (CODE_COMMIT 내용(None = 없음), .git 있음, 기대 표시) — 'HEAD' = 그 폴더 git의 짧은 커밋
COMMIT_CASES = [
    ("0123456789abcdef 0123456\n", False, "0123456"),  # zip·git archive로 받음 — 짧은 커밋
    ("$Format:%H %h$\n", True, "HEAD"),  # git clone — 틀 글자 대신 HEAD
    ("$Format:%H %h$\n", False, ""),  # 틀 글자인데 .git 없음 — 표시 없음
    (None, False, ""),
]


def test_runtime_entry_commit():
    bash = _bash()
    if not bash or not shutil.which("git"):
        print("[시험] bash·git 없음 — 건너뜀")
        return
    block = _block("deploy/docker/runtime_entry.sh", r"^commit=\$\(tr .*?^esac\n")
    for content, has_git, want in COMMIT_CASES:
        with tempfile.TemporaryDirectory(prefix="orca_rt_") as d:
            if has_git:
                _git(d, "init", "-q")
                _git(d, "commit", "-q", "--allow-empty", "-m", "x")
                want = subprocess.run(["git", "-C", d, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
            if content is not None:
                Path(d, "CODE_COMMIT").write_text(content, encoding="utf-8", newline="\n")
            out = _run(bash, f'CODE="$T"\n{block}echo "got=$commit"\n', {"T": Path(d).as_posix()})
        assert f"got={want}\n" in out, (content, has_git, out)


KEEP = ["deploy/host/scripts/run.sh", "settings.sample.yaml", "valid_env.md"]
DROP = ["deploy/host/scripts/test_space/x.log", "valid_env/a.txt", "validation/b.py", "settings.yaml", "settings copy.yaml"]


def test_prd_bundle_excludes():
    """운영 코드 묶음에 .git·러너 작업 폴더·PC 검증 데이터·검증 도구·비밀 settings가 없다(git clone이면 git archive, 아니면 tar)."""
    bash = _bash()
    if not bash or not shutil.which("git"):
        print("[시험] bash·git 없음 — 건너뜀")
        return
    block = _block("deploy/release/bake_prod_image.sh", r"^NOT_PRD=.*?^fi\n")
    for use_git in (True, False):
        with tempfile.TemporaryDirectory(prefix="orca_bake_") as d:
            code = Path(d) / "code"
            for rel in KEEP + DROP:
                (code / rel).parent.mkdir(parents=True, exist_ok=True)
                (code / rel).write_text("x", encoding="utf-8")
            if use_git:
                (code / ".gitignore").write_text("settings.yaml\nsettings copy.yaml\n", encoding="utf-8")
                _git(code, "init", "-q")
                _git(code, "add", "-A")
                _git(code, "commit", "-q", "-m", "x")
            bundle = Path(d) / "b.tar.gz"
            _run(bash, f'CODE_DIR="$C"; BUNDLE="$B"\n{block}', {"C": code.as_posix(), "B": bundle.as_posix()})
            with tarfile.open(bundle) as tf:
                names = {n.removeprefix("./") for n in tf.getnames()}
        assert all(k in names for k in KEEP), (use_git, sorted(names))
        bad = [
            n
            for n in names
            if n.split("/")[0] in {".git", "valid_env", "validation"}
            or n.startswith("deploy/host/scripts/test_space")
            or n in {"settings.yaml", "settings copy.yaml"}
        ]
        assert not bad, (use_git, bad)
