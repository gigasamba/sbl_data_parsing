"""개발 작업 공간 git 계정(option.devbox.gitea_* · git_user_*) — dev_entry.sh가 sshd 전에 부른다(컨테이너 안, 붙인 설정 파일에서 읽음).
gitea 주소·계정·토큰을 모두 적었으면 ~/.git-credentials에서 그 호스트 줄만 바꾸고(다른 줄은 그대로) `credential.helper store`,
이름·메일을 적었으면 user.name·user.email. 셋 중 하나라도 비우면 전에 쓴 호스트 줄(~/.devbox/gitea_host에 기록)을 지운다.
파일은 같은 폴더의 새 임시 파일(처음부터 600)에 써서 os.replace로 바꾼다 — 자리가 심볼릭 링크면 따라가지 않고 링크를 바꾼다.
토큰은 env·화면·로그에 내지 않는다(그래서 compose env로 넘기지 않고 설정 파일에서 직접 읽음). 주소 꼴은 설정 모델이 검사한다.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit


def _git(home, *args):
    env = {**os.environ, "HOME": str(home)}  # env 남김 — 하위 프로세스(git --global 자리 = 이 홈)
    subprocess.run(["git", "config", "--global", *args], env=env, check=True)


def _host(line):
    """자격 줄 `scheme://user:token@host[:port]` → host[:port](꼴이 다르면 None)."""
    try:
        return urlsplit(line.strip()).netloc.rsplit("@", 1)[-1] or None
    except ValueError:
        return None


def _write(path, text):
    """같은 폴더 새 임시 파일(mkstemp — 처음부터 600)에 쓰고 os.replace(링크면 링크 자체를 바꿈). 빈 글자면 지운다."""
    if not text:
        path.unlink(missing_ok=True)
        return
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def setup(home, url, user, token, name=None, email=None):
    """자격 파일·git 설정 — 자격 줄을 쓴 호스트(안 썼으면 None)."""
    home = Path(home)
    cred, mark = home / ".git-credentials", home / ".devbox" / "gitea_host"
    host = urlsplit(url).netloc.rsplit("@", 1)[-1] if url and user and token else None
    old = mark.read_text(encoding="utf-8").strip() if mark.is_file() else None
    if host or old:
        lines = [] if cred.is_symlink() or not cred.is_file() else cred.read_text(encoding="utf-8").splitlines()
        keep = [ln for ln in lines if ln.strip() and _host(ln) not in {host, old}]
        if host:
            keep.append(f"{urlsplit(url).scheme}://{quote(user, safe='')}:{quote(token, safe='')}@{host}")
        _write(cred, "".join(f"{ln}\n" for ln in keep))
        mark.parent.mkdir(parents=True, exist_ok=True)
        _write(mark, f"{host}\n" if host else "")
    if host:
        _git(home, "credential.helper", "store")
    if name:
        _git(home, "user.name", name)
    if email:
        _git(home, "user.email", email)
    return host


def main():
    from common.config.settings import cfg

    d = cfg().host.devbox
    token = d.gitea_token.get_secret_value() if d.gitea_token else None
    if setup(Path.home(), d.gitea_url, d.gitea_user, token, d.git_user_name, d.git_user_email):
        print("[devbox] git 자격 파일 ~/.git-credentials의 gitea 줄을 씀(토큰은 출력하지 않음)")


if __name__ == "__main__":
    main()
