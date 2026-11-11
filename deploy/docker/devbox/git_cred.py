"""개발 작업 공간 git 이름·메일(option.devbox.git_user_*) — dev_entry.sh가 sshd 전에 부른다(컨테이너 안, 붙인 설정 파일에서 읽음).
적은 값만 git config --global user.name·user.email로 쓴다. git 로그인(자격)은 사람이 컨테이너 안에서 직접 한다.
"""

import os
import subprocess
from pathlib import Path


def _git(home, *args):
    env = {**os.environ, "HOME": str(home)}  # env 남김 — 하위 프로세스(git --global 자리 = 이 홈)
    subprocess.run(["git", "config", "--global", *args], env=env, check=True)


def setup(home, name=None, email=None):
    """적은 이름·메일만 git 설정에 쓴다(비운 칸은 그대로 둠)."""
    if name:
        _git(Path(home), "user.name", name)
    if email:
        _git(Path(home), "user.email", email)


def main():
    from common.config.settings import cfg

    d = cfg().host.devbox
    setup(Path.home(), d.git_user_name, d.git_user_email)


if __name__ == "__main__":
    main()
