"""개발 작업 공간(op-17·op-18): 이미지 ENTRYPOINT dev_entry.sh는 `devbox`만 sshd로, 그 밖의 명령은 인자 그대로 APP_ENTRY(이미지의 시작
스크립트)로 넘긴다. compose 파일의 SSH 컨테이너·포트는 test_compose.py 표. git_cred.py는 gitea 계정 줄만 고친다.
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
OTHER = "https://me:x@github.test"  # 우리가 관리하지 않는 줄 — 늘 남음
# 한 홈에서 차례로: (주소, 계정, 토큰, 이름, 메일) → 기대 ~/.git-credentials 줄, 기대 ~/.gitconfig 칸(누적)
CRED_STEPS = [
    (
        ("http://gitea.test:3000", "dev1", "t/k:n@1", "홍길동", "dev1@corp.test"),
        [OTHER, "http://dev1:t%2Fk%3An%401@gitea.test:3000"],  # 옛 같은 호스트 줄은 바뀜
        {"credential.helper": "store", "user.name": "홍길동", "user.email": "dev1@corp.test"},
    ),
    (
        ("https://gitea2.test/git", "dev1", "tok", None, None),
        [OTHER, "https://dev1:tok@gitea2.test"],
        None,
    ),  # 주소 바뀜 — 옛 호스트 줄 지움
    (("https://gitea2.test", "dev1", "", None, None), [OTHER], None),  # 토큰 비움 — 우리 줄만 지움
    ((None, None, None, None, None), [OTHER], None),  # 다시 비움 — 그대로
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
        cred = Path(home) / ".git-credentials"
        cred.write_text(f"{OTHER}\nhttp://old:y@gitea.test:3000\n", encoding="utf-8")
        cfg = {}
        for args, want_lines, want_cfg in CRED_STEPS:
            gc.setup(home, *args)
            assert cred.read_text(encoding="utf-8").splitlines() == want_lines, (args, want_lines)
            if os.name == "posix":
                assert cred.stat().st_mode & 0o777 == 0o600, oct(cred.stat().st_mode)
            cfg = want_cfg or cfg
            assert _gitconfig(home) == cfg, args
        assert not (Path(home) / ".devbox" / "gitea_host").exists()  # 다 지우면 기록도 없음
    if os.name == "posix":  # 자리가 링크면 따라가지 않고 링크를 바꿈(링크가 가리키던 파일은 그대로)
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as out:
            target = Path(out) / "victim"
            target.write_text("keep\n", encoding="utf-8")
            (Path(home) / ".git-credentials").symlink_to(target)
            gc.setup(home, "https://gitea.test", "u", "t")
            assert target.read_text(encoding="utf-8") == "keep\n" and not (Path(home) / ".git-credentials").is_symlink()
