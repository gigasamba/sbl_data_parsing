"""개발 작업 공간(option.devbox — op-17): 이미지 ENTRYPOINT dev_entry.sh는 `devbox`만 sshd로, 그 밖의 명령은 인자 그대로 APP_ENTRY(이미지의 시작
스크립트)로 넘기고, compose.dev.yml은 data-pipeline을 `devbox`로 띄우며 코드 폴더를 compose.code.yml과 같은 자리에 쓰기 가능으로·홈을 <루트>/home에 붙인다.
host_ctl.sh가 파일을 더하는 조건(포트·prd·코드가 든 이미지)은 test_dc.py 표. sshd가 실제로 뜨는지는 이미지 시험(server-guide §2-13) — 여기는 bash만(PC 전용)."""

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
    home = dev["volumes"][1]  # option.devbox.home_dir
    assert home.startswith("${DEVBOX_HOME:?") and home.endswith(":/home/rag:z"), dev["volumes"]
    oc = _svc("compose.opencode.yml")
    assert oc["volumes"][0].endswith(":" + oc["environment"]["OPENCODE_CONFIG"] + ":ro,z"), oc


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


SETS = {  # 시험 묶음 compose-dev.yml(op-18) 서비스 → (명령, 포트, 벌 폴더, 홈)
    "data-pipeline-0": (["devbox"], ["0.0.0.0:8020:22"], "main-0", "home"),
    "data-pipeline-1": (["devbox"], ["0.0.0.0:8021:22"], "main-1", "home"),
    "mcp-server-0": (["devbox", "mcp"], ["0.0.0.0:8050:22", "0.0.0.0:8051:8080"], "main-0", "home/mcp"),
}


def test_compose_sets():
    svcs = yaml.safe_load((COMPOSE / "compose-dev.yml").read_text(encoding="utf-8"))["services"]
    assert set(svcs) == set(SETS)
    for name, (cmd, ports, folder, home) in SETS.items():
        s = svcs[name]
        assert s["command"] == cmd and s["ports"] == ports and s["user"] == "0", name
        assert "RUN_ENV" not in s["environment"], name
        b = "${SBL_ROOT:-/home/sbl}/sbl_data_parsing-" + folder
        v = s["volumes"]
        assert v[0] == f"{b}:/app/deploy:z" and v[1] == f"{b}/settings.yaml:/app/deploy/settings.yaml:ro,z", (name, v)
        pw = {
            "type": "bind",
            "source": "${SBL_ROOT:-/home/sbl}/root_pw",
            "target": "/run/secrets/root_pw",
            "read_only": True,
            "bind": {"create_host_path": False, "selinux": "z"},
        }
        assert f"{b}/{home}:/root:z" in v and pw in v, (name, v)


def test_compose_pgvector():
    pg = yaml.safe_load((COMPOSE / "compose-pgvector.yml").read_text(encoding="utf-8"))["services"]["pgvector"]
    # 검색 DB(따로 띄움) — 바깥 5433, 데이터 폴더, 비밀번호는 파일(env에 값 없음)
    assert (
        pg["container_name"] == "pgvector"
        and pg["restart"] == "always"
        and pg["ports"] == ["0.0.0.0:5433:5432"]
        and pg["environment"]["POSTGRES_PASSWORD_FILE"] == "/run/secrets/pg_pw"
    ), pg
    assert "POSTGRES_PASSWORD" not in pg["environment"] and pg["volumes"][0] == "${PG_DATA:-/data/pg/pipeline}:/var/lib/postgresql/data:z"


PRD = {  # 운영 묶음 compose-prd.yml(op-18) 서비스 → (이미지, 명령, 포트 — compose-dev.yml과 같음, 홈)
    "data-pipeline-0": ("data-pipeline:", ["devbox"], ["0.0.0.0:8020:22"], "home"),
    "mcp-server-0": ("mcp-server:", ["devbox", "mcp"], ["0.0.0.0:8050:22", "0.0.0.0:8051:8080"], "home/mcp"),
}


def test_compose_prd():
    def load(name):
        return yaml.safe_load((COMPOSE / name).read_text(encoding="utf-8"))["services"]

    svcs, dev = load("compose-prd.yml"), load("compose-dev.yml")
    assert set(svcs) == set(PRD) and all(s["restart"] == "always" for s in svcs.values()), svcs
    d = "${PRD_DIR:-/home/sbl/sbl_data_parsing-main}"
    for name, (image, cmd, ports, home) in PRD.items():
        s = svcs[name]
        assert s["image"].startswith(image) and s["command"] == cmd and s["ports"] == ports == dev[name]["ports"], name
        assert s["user"] == "0" and s["entrypoint"][-1] == "/etc/devbox/dev_entry.sh", name  # 구운 이미지 ENTRYPOINT를 작업 공간으로
        assert s["environment"]["APP_ENTRY"] == "/app/docker/entrypoint.sh" and "RUN_ENV" not in s["environment"], name
        v = s["volumes"]
        assert f"{d}/settings.yaml:/etc/rag/settings.yaml:ro,z" in v and f"{d}/{home}:/root:z" in v, (name, v)
        assert not any(isinstance(x, str) and ":/app/deploy" in x for x in v), (name, v)  # 코드는 이미지 안


def test_compose_redis():
    svcs = yaml.safe_load((COMPOSE / "compose-redis.yml").read_text(encoding="utf-8"))["services"]
    assert set(svcs) == {"redis"}  # 서버마다 1개
    s = svcs["redis"]
    assert s["ports"] == ["0.0.0.0:${REDIS_PORT:-8010}:${REDIS_PORT:-8010}"] and s["restart"] == "always", s
    pw = "${SBL_ROOT:-/home/sbl}/redis_pw"
    assert any(isinstance(v, dict) and v["source"] == pw and v["read_only"] for v in s["volumes"]), s["volumes"]
