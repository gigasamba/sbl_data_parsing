"""host_ctl.sh — 상주 컨테이너 3개의 compose 파일을 늘 함께 붙이고, 실행 이미지(*-runtime)거나
CODE_DIR를 주면 compose.code*.yml 셋을 더하고, 개발 작업 공간(option.devbox — DEVBOX_SSH_PORT)이면 compose.dev.yml(+ opencode 설정이면
compose.opencode.yml)을 더한 뒤(prd·코드가 든 이미지면 거부) 인자를 그대로 넘기는지. DOCKER=echo로 명령 줄만 본다(docker·설정 읽기 없음 — PC 전용)."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_trigger_gate import _bash

SCRIPT = DEPLOY_ROOT / "deploy" / "host" / "scripts" / "host_ctl.sh"
BASE = ["compose.pipeline.yml", "compose.data-parsing.yml", "compose.mcp-server.yml"]
CODE = ["compose.code.yml", "compose.code.data-parsing.yml", "compose.code.mcp-server.yml"]
DEV = ["compose.dev.yml"]
PORTS = {"MCP_PORT": "8775", "DATA_PARSING_PORT": "8776"}  # 포트 칸 — 여러 벌(개발자 벌은 data-pipeline만)은 기본값이어도 됨
SSH = {"DEVBOX_SSH_PORT": "2222"}  # option.devbox.ssh_port — 개발 작업 공간
OC = {**SSH, "DEVBOX_OPENCODE_CONFIG": "/srv/x/opencode.json"}  # + option.devbox.opencode_config
RT = "data-pipeline-runtime:0.2.0"
# (DATA_PIPELINE_IMAGE, CODE_DIR, 덧붙는 compose 파일, 루트(코드 폴더) 이름 — 끝 -<숫자>가 벌 번호, 그 밖 env, compose 묶음 이름 — 종료 코드 2면 거부 문구)
# MCP_SERVER_IMAGE는 따로 안 주면 DATA_PIPELINE_IMAGE와 같은 꼴(개발 서버는 둘 다 실행 이미지). EXTRA_COMPOSE의 {d}는 시험 폴더 — 파일을 만들어 둠(missing* 빼고)
CASES = [
    ("data-pipeline:0.2.0", "", [], "code", {}, "compose"),  # 코드가 든 이미지(운영) · 한 벌 — 묶음 이름은 compose 기본 그대로
    (RT, "", CODE, "code", {}, "compose"),  # 실행 이미지(개발) — 이 코드 폴더를 붙임
    ("data-pipeline:0.2.0", "/srv/x/code", CODE, "code", {}, "compose"),  # CODE_DIR를 주면 그 값
    ("data-pipeline:0.2.0", "", [], "sbl_data_parsing-main-2", PORTS, "compose-2"),  # 여러 벌 — 묶음 이름 끝 -<벌 번호>
    ("data-pipeline:0.2.0", "", [], "sbl_data_parsing-0.3.0", {}, "compose"),  # 판 번호(점)는 벌 번호가 아님
    ("data-pipeline:0.2.0", "", [], "sbl_data_parsing-main-2", {}, "compose-2"),  # 여러 벌·기본 포트 — 받음(개발자 벌은 MCP 없음)
    ("data-pipeline:0.2.0", "", [], "sbl_data_parsing-main-2", {**PORTS, "RUN_ENV": "prd"}, "!운영(prd)"),  # prd는 한 벌
    (RT, "", CODE + DEV, "code", SSH, "compose"),  # 개발 작업 공간 — 코드 폴더 쓰기 가능·홈 폴더
    (RT, "", CODE + DEV + ["compose.opencode.yml"], "code", OC, "compose"),  # + opencode 설정 파일
    (RT, "", CODE, "code", {"DEVBOX_OPENCODE_CONFIG": "/srv/x/opencode.json"}, "compose"),  # 포트 없이 opencode만 — 끔
    (RT, "", [], "code", {**SSH, "RUN_ENV": "prd"}, "!option.devbox.ssh_port는 개발 서버"),  # 운영은 거부
    ("data-pipeline:0.2.0", "", [], "code", SSH, "!실행 이미지(*-runtime)에서만"),  # 코드가 든 이미지는 거부
    ("data-pipeline:0.2.0", "", [], "code", {"COMPOSE_PROJECT": "rag"}, "rag"),  # ops.host.compose_project — 묶음 밑 이름
    ("data-pipeline:0.2.0", "", [], "sbl_data_parsing-main-2", {**PORTS, "COMPOSE_PROJECT": "rag"}, "rag-2"),  # 밑 이름 + 벌 번호
    (
        "data-pipeline:0.2.0",
        "",
        ["a.yml", "b.yml"],
        "code",
        {"EXTRA_COMPOSE": "x/a.yml,{d}/b.yml"},
        "compose",
    ),  # ops.host.extra_compose — 맨 뒤
    (
        "data-pipeline:0.2.0",
        "",
        ["a.yml", "b.yml"],
        "code",
        {"EXTRA_COMPOSE": "x/a.yml, {d}/b.yml"},
        "compose",
    ),  # 쉼표 뒤 빈칸(sample 예 꼴)도 같은 파일들
    (RT, "", CODE + DEV + ["extra.yml"], "code", {**SSH, "EXTRA_COMPOSE": "extra.yml"}, "compose"),  # 개발 작업 공간 파일보다도 뒤
    (RT, "", [], "code", {**SSH, "DEVBOX_HOME": "/nonexistent/home"}, "!option.devbox.home_dir"),  # 홈 폴더(설정 자리)가 없으면 거부
    (
        "data-pipeline:0.2.0",
        "",
        [],
        "code",
        {"EXTRA_COMPOSE": "missing.yml"},
        "!ops.host.extra_compose 파일 없음",
    ),  # 없는 파일 — 한 줄 안내
    ("data-pipeline:0.2.0", "", CODE[2:], "code", {"MCP_SERVER_IMAGE": "mcp-server-runtime:0.2.0"}, "compose"),  # 이미지마다 코드 폴더 짝
    (RT, "", CODE[:2], "code", {"MCP_SERVER_IMAGE": "mcp-server:0.2.0"}, "compose"),
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
        for image, code, more, name, extra, project in CASES:
            root = Path(d) / name
            (root / "home").mkdir(parents=True, exist_ok=True)  # 개발 작업 공간 홈(init이 ssh_port일 때 만듦)
            q = root.resolve().as_posix()
            env = {  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": sp,
                "SETTINGS_LOADED": sp,  # 이미 읽은 것으로 — settings_to_env.py(PyYAML)를 부르지 않음
                "DOCKER": "echo",
                "DATA_PIPELINE_IMAGE": image,
                "MCP_SERVER_IMAGE": image.replace("data-pipeline", "mcp-server"),
                "RAG_ROOT": f"/{q[0].lower()}{q[2:]}" if q[1:2] == ":" else q,  # 루트(코드 폴더) — 이름 끝 -<숫자>가 벌 번호
                **{k: v.format(d=_posix(d)) for k, v in extra.items()},
            }
            for f in (x.strip() for x in env.get("EXTRA_COMPOSE", "").split(",")):  # 붙일 파일(상대 경로는 루트 기준)
                if f and not f.startswith("missing"):
                    p = Path(d) / Path(f).name if f.startswith(_posix(d)) else root / f
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("services: {}\n", encoding="utf-8")
            if code:
                env["CODE_DIR"] = code
            r = subprocess.run(
                [bash, str(SCRIPT), "up", "-d", "mcp"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30
            )
            if project.startswith("!"):
                assert r.returncode == 2 and project[1:] in r.stderr, (name, extra, r.returncode, r.stderr)
                continue
            assert r.returncode == 0, (image, code, r.stderr)
            files = [w.rsplit("/", 1)[-1] for w in r.stdout.split() if w.endswith(".yml")]
            assert r.stdout.split()[:3] == ["compose", "-p", project] and r.stdout.split()[-3:] == ["up", "-d", "mcp"], r.stdout
            assert files == BASE + more, (image, code, extra, files)


STUB = "from pathlib import Path\nprint(f\"export DATA_PIPELINE_IMAGE='{Path(__file__).parents[3].name}'\")\n"  # settings_to_env.py 대역 — 루트 이름을 냄


def test_stale_shell_reads_own_root():
    """루트 a에서 load_settings를 source한 셸(env를 물려받음)로 루트 b의 스크립트를 불러도 b의 루트·설정 파일·설정 값을 쓴다.
    셸에서 사람이 준 값(DOCKER)은 그대로 이긴다."""
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        ls = {}
        for name in ("a", "b"):
            root = Path(d) / name
            scripts = root / "deploy" / "host" / "scripts"  # 루트 = 코드 폴더
            scripts.mkdir(parents=True)
            (scripts / "load_settings.sh").write_bytes((SCRIPT.parent / "load_settings.sh").read_bytes())
            (scripts / "settings_to_env.py").write_text(STUB, encoding="utf-8")
            (root / "settings.yaml").write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
            p = (scripts / "load_settings.sh").resolve().as_posix()
            ls[name] = f"/{p[0].lower()}{p[2:]}" if p[1:2] == ":" else p
        inner = f'. {ls["b"]} && load_settings && echo "$RAG_ROOT|$SETTINGS_FILE|$DATA_PIPELINE_IMAGE|$RAG_OUT|$DOCKER"'
        cmd = f". {ls['a']} && load_settings && export DATA_PIPELINE_IMAGE && bash -c '{inner}'"
        env = {
            "PATH": os.environ.get("PATH", ""),  # env 남김 — 하위 프로세스(시험 셸)
            "PY": Path(sys.executable).as_posix(),
            "DOCKER": "echo",
        }
        r = subprocess.run([bash, "-c", cmd], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        root_b = ls["b"].rsplit("/deploy/", 1)[0]
        assert r.stdout.strip() == f"{root_b}|{root_b}/settings.yaml|b|{root_b}/output|echo", r.stdout


NAME_CASES = [  # (루트 이름, 셸 env(= settings.yaml 호스트 칸), 기대 (파이프라인, 파싱, MCP 컨테이너, compose 묶음, 사슬 원본, 홈 — <루트> 자리는 {r}))
    ("code", {}, ("data-pipeline", "mcp-data-parsing", "mcp-server", "compose", "{r}/edw_chain.yaml", "{r}/home")),  # 코드 기본값
    (
        "sbl_data_parsing-main-2",
        PORTS,
        ("data-pipeline-2", "mcp-data-parsing-2", "mcp-server-2", "compose-2", "{r}/edw_chain.yaml", "{r}/home"),
    ),
    (
        "sbl_data_parsing-main-2",
        {**PORTS, "PIPELINE_CONTAINER": "p", "DATA_PARSING_CONTAINER": "dp", "MCP_CONTAINER": "m", "COMPOSE_PROJECT": "rag"},
        ("p-2", "dp-2", "m-2", "rag-2", "{r}/edw_chain.yaml", "{r}/home"),
    ),  # ops.containers.*_container_name·ops.host.compose_project + 벌 번호
    (
        "code",
        {"EDW_CHAIN_SRC": "alt/chain.yaml", "DEVBOX_HOME": "/srv/home-hong"},
        ("data-pipeline", "mcp-data-parsing", "mcp-server", "compose", "{r}/alt/chain.yaml", "/srv/home-hong"),
    ),  # ops.host.host_edw_chain_file(상대 = 루트 기준)·option.devbox.home_dir
]
SETTINGS = "required:\n  env: {run_env: dev}\n"  # SETTINGS_LOADED로 읽지 않음 — 있기만
COMPOSE_NAMES = {"compose.pipeline.yml": "data-pipeline", "compose.data-parsing.yml": "mcp-data-parsing", "compose.mcp-server.yml": "mcp"}


def test_container_names():
    """load_settings가 밑 이름(설정 > 코드 기본값 host_settings.tsv) + 벌 번호로 컨테이너·묶음 이름을, 사슬·홈 원본 경로를 만들고
    compose 파일은 그 변수로만 이름·원본을 잡는다(치환해 본 값)."""
    import yaml

    from tests.general.deploy.test_compose import COMPOSE, render

    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    ls = SCRIPT.parent / "load_settings.sh"
    with tempfile.TemporaryDirectory() as d:
        sf = Path(d) / "settings.yaml"
        sf.write_text(SETTINGS, encoding="utf-8")
        sp = _posix(sf)
        base = {  # compose `:?` 칸(이름·원본 밖) — 치환만 되게
            "SETTINGS_FILE": sp,
            "RUN_ENV": "dev",
            "DATA_PIPELINE_IMAGE": "data-pipeline:0.2.0",
            "MCP_SERVER_IMAGE": "mcp-server:0.2.0",
            "DOC_SRC": "/srv/docs",
            "RAG_OUT": "/srv/out",
            "APP_DOCS_MOUNT": "/data/docs",
            "APP_OUTPUT_ROOT": "/app/output",
            "APP_CODE_ROOT": "/app/deploy",
            "CODE_DIR": "/c",
            "DEVBOX_SSH_PORT": "2222",
        }
        for name, extra, want in NAME_CASES:
            r_ = _posix(Path(d) / name)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "SETTINGS_FILE": sp,
                "SETTINGS_LOADED": sp,
                "DOCKER": "echo",
                "RAG_ROOT": r_,
                **extra,
            }  # env 남김 — 하위 프로세스(시험 셸)
            out = 'echo "$PIPELINE_CNAME|$DATA_PARSING_CNAME|$MCP_CNAME|$COMPOSE_PNAME|$EDW_CHAIN_SRC|$DEVBOX_HOME"'
            r = subprocess.run(
                [bash, "-c", f". {_posix(ls)} && load_settings && {out}"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            got = r.stdout.strip().split("|")
            assert r.returncode == 0 and got == [w.format(r=r_) for w in want], (name, extra, r.stdout, r.stderr)
            names = dict(zip(("PIPELINE_CNAME", "DATA_PARSING_CNAME", "MCP_CNAME"), got))
            for f, svc in COMPOSE_NAMES.items():
                text = render((COMPOSE / f).read_text(encoding="utf-8"), {**base, **names, "EDW_CHAIN_SRC": got[4]})
                assert yaml.safe_load(text)["services"][svc]["container_name"] in got[:3], (f, name)
            dev = yaml.safe_load(
                render((COMPOSE / "compose.dev.yml").read_text(encoding="utf-8"), {**base, "DEVBOX_HOME": got[5], "EDW_CHAIN_SRC": got[4]})
            )
            vols = dev["services"]["data-pipeline"]["volumes"]
            assert f"{got[5]}:/home/rag:z" in vols and f"{got[4]}:/app/deploy/edw_chain.yaml:ro,z" in vols, vols


def _posix(p):
    p = Path(p).resolve().as_posix()
    return f"/{p[0].lower()}{p[2:]}" if p[1:2] == ":" else p  # Git Bash(Windows)가 절대 경로로 보는 꼴


def test_keepalive_extra_compose():
    """mcp_keepalive.sh는 띄울 때 host_ctl.sh를 불러 같은 compose 파일 묶음(ops.host.extra_compose 포함)·묶음 이름을 쓴다(DOCKER·python3·sleep은
    대역: /health 응답 없음, 기다리지 않음). MCP_HOST auto면 호스트에서 주소를 풀지 않고 컨테이너 안(exec)에서 묻는다."""
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        stub = Path(d) / "bin"
        stub.mkdir()
        calls = Path(d) / "py.log"  # 호스트 python3 대역이 받은 인자(/health 주소)
        py = f'#!/bin/sh\necho "$*" >> "{_posix(calls)}"\nexit 1\n'
        execs = Path(d) / "exec.log"  # 컨테이너 도구 대역 — 명령 줄만 찍고 exec(컨테이너 안 /health — 출력은 버려지므로 따로 남김)는 실패
        dk = f'#!/bin/sh\necho "$*"\n[ "$1" != exec ] || {{ echo "$*" >> "{_posix(execs)}"; exit 1; }}\n'
        for exe, body in (("python3", py), ("sleep", "#!/bin/sh\nexit 0\n"), ("dk", dk)):
            (stub / exe).write_text(body, encoding="utf-8", newline="\n")
            (stub / exe).chmod(0o755)
        sf = Path(d) / "settings.yaml"
        sf.write_text(SETTINGS, encoding="utf-8")
        sp = _posix(sf)
        env = {  # env 남김 — 하위 프로세스(시험 셸)
            "PATH": os.environ.get("PATH", ""),
            "SETTINGS_FILE": sp,
            "SETTINGS_LOADED": sp,
            "DOCKER": "dk",
            "RAG_ROOT": _posix(Path(d) / "sbl_data_parsing-main-3"),
            **PORTS,
            "DATA_PIPELINE_IMAGE": "data-pipeline:0.2.0",
            "MCP_SERVER_IMAGE": "mcp-server-runtime:0.2.0",  # 검색 MCP만 실행 이미지 — 그 짝만 붙음(이미지마다)
            "COMPOSE_PROJECT": "rag",
            "EXTRA_COMPOSE": "extra.yml",
            **SSH,
            "DEVBOX_HOME": "/nonexistent/home",  # 작업 공간 관문(홈 없음)이 살리기를 막지 않음 — base
        }
        root = Path(d) / "sbl_data_parsing-main-3"
        root.mkdir()
        (root / "extra.yml").write_text("services: {}\n", encoding="utf-8")
        # 대역을 PATH 맨 앞에 — Git Bash(Windows) 입구는 시작 때 /usr/bin을 앞에 붙이므로 셸 안에서 붙이고 bash를 다시 부름
        script = _posix(SCRIPT.parent / "mcp_keepalive.sh")
        cmd = f'PATH="{_posix(stub)}:$PATH" exec bash "{script}"'
        # (MCP_HOST, 호스트 python3가 부를 /health — None이면 호스트에서 안 부름, 컨테이너 안 exec로 묻나)
        for host, probe, inside in (("", "http://127.0.0.1:8775/health", False), ("auto", None, True)):
            calls.write_text("", encoding="utf-8")
            execs.write_text("", encoding="utf-8")
            run_env = {**env, "MCP_HOST": host}  # env 남김 — 시험(호스트 셸이 load_settings로 받는 MCP_HOST)
            r = subprocess.run([bash, "-c", cmd], env=run_env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            ups = [w.split() for w in r.stdout.splitlines() if w.startswith("compose ")]
            assert r.returncode == 1 and [u[-1] for u in ups] == ["mcp-data-parsing", "mcp"], (r.returncode, r.stdout, r.stderr)
            for u in ups:
                files = [w.rsplit("/", 1)[-1] for w in u if w.endswith(".yml")]
                assert u[:3] == ["compose", "-p", "rag-3"] and files == BASE + CODE[2:] + ["extra.yml"], u
            seen = calls.read_text(encoding="utf-8")
            assert (probe in seen) if probe else not seen, (host, seen)
            ex = [w for w in execs.read_text(encoding="utf-8").splitlines() if w.startswith("exec mcp-server-3 python -c ")]
            assert bool(ex) == inside and all("gethostbyname(socket.gethostname())" in w and ":8775/health" in w for w in ex), host
