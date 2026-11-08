"""host_ctl.sh init·timers·check — init: DC_ROOT 임시 루트에 settings.yaml·edw_chain.yaml·output/을 만들고(두 번 불러도 같음 — home/은
option.devbox.ssh_port가 있을 때만, backup/은 없음) settings.yaml은 없을 때만 복사(덮지 않음), env/·code/·live는 만들지 않음.
루트는 코드 폴더 자체(load_settings.sh) — 벌 번호는 그 이름 끝 -<숫자>. timers: 단위 파일의 @CODE_DIR@를
코드 폴더로 채움. check: DC_FAKE로 단계를 바꿔 끼워 처음 실패에서 멈추는지·selftest는 "[판정] 통과" 줄로 판정하는지. docker·root·systemctl 없음 — PC 전용."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common.core.paths import DEPLOY_ROOT
from tests.general.deploy.test_dc import SCRIPT
from tests.general.deploy.test_trigger_gate import _bash


def _posix(p):
    p = Path(p).resolve().as_posix()
    return f"/{p[0].lower()}{p[2:]}" if p[1:2] == ":" else p  # Git Bash(Windows)가 절대 경로로 보는 꼴


def _need_bash():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
    return bash


def _run(bash, args, extra, script=SCRIPT):
    env = {"PATH": os.environ.get("PATH", ""), "PY": Path(sys.executable).as_posix(), **extra}  # env 남김 — 하위 프로세스(시험 셸)
    cmd = [bash, *args] if script is None else [bash, str(script), *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_init():
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "dev"
        base = {"DC_ROOT": _posix(root)}
        r1 = _run(bash, ["init"], base)
        assert r1.returncode == 0, r1.stderr + r1.stdout
        for sub in ("output", "output/_mcp_parse/jobs"):
            assert (root / sub).is_dir(), (sub, r1.stdout)
        for gone in ("env", "code", "backup", "home"):  # home — ssh_port가 없으면 안 만듦
            assert not (root / gone).exists(), (gone, r1.stdout)
        sf = root / "settings.yaml"
        chain = root / "edw_chain.yaml"  # 사슬 서버 사본 — 없을 때만 기본 파일에서
        assert chain.read_bytes() == (DEPLOY_ROOT / "resources" / "config" / "edw_chain.yaml").read_bytes(), "init이 사슬 사본을 안 만듦"
        assert sf.read_bytes() == (SCRIPT.parents[3] / "settings.sample.yaml").read_bytes()
        assert "만듦" in r1.stdout and "required.env.run_env" in r1.stdout, r1.stdout
        if os.name != "nt":  # Windows(Git Bash)는 권한을 POSIX처럼 안 둠
            assert oct(sf.stat().st_mode & 0o777) == "0o640"
            assert oct((root / "output").stat().st_mode & 0o7777) == "0o2775"
        sf.write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")  # 사람이 채운 설정 — 다시 불러도 그대로여야
        chain.write_text("files: {}\n", encoding="utf-8")  # 사람이 고친 사슬 사본 — 다시 불러도 그대로여야
        r2 = _run(bash, ["init"], base)  # 두 번째는 settings.yaml을 읽음 — 결과 폴더 기본도 DC_ROOT 아래(코드 폴더의 부모가 아님)
        assert r2.returncode == 0, r2.stderr + r2.stdout
        assert sf.read_text(encoding="utf-8") == "required:\n  env: {run_env: dev}\n", "init이 settings.yaml을 덮음"
        assert chain.read_text(encoding="utf-8") == "files: {}\n", "init이 사슬 사본을 덮음"
        assert "덮지 않음" in r2.stdout and "만듦" not in r2.stdout, r2.stdout  # 멱등 — 두 번째는 모두 "있음"
        assert f"있음  {_posix(root)}/output\n" in r2.stdout, r2.stdout  # 결과 폴더가 시험 루트 밖으로 새지 않음
        sf.write_text("required:\n  env: {run_env: dev}\noption:\n  devbox: {ssh_port: 2222}\n", encoding="utf-8")
        r3 = _run(bash, ["init"], base)  # ssh_port를 적은 뒤 — 개발 작업 공간 홈을 만듦
        assert r3.returncode == 0 and (root / "home").is_dir(), r3.stderr + r3.stdout
    r = _run(bash, ["init", "--bad"], {"DC_ROOT": "/nonexistent"})
    assert r.returncode == 2, r.stdout


def test_root_is_code_folder():
    """load_settings.sh는 자기 자리(코드 폴더/deploy/host/scripts)에서 루트(코드 폴더 자체)를 구해 <루트>/settings.yaml을 읽고
    결과 폴더를 <루트>/output으로, 벌 번호를 그 이름 끝 -<숫자>로 둔다(env·고정 경로 없음). SETTINGS_LOADED로 settings_to_env.py(PyYAML) 부르기는 건너뜀."""
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        ports = {"MCP_PORT": "8775", "DATA_PARSING_PORT": "8776"}
        for name, inst in (("sbl_data_parsing-main-2", "2"), ("sbl_data_parsing-0.3.0", ""), ("sbl_data_parsing-main", "")):
            root = Path(d) / name
            scripts = root / "deploy" / "host" / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy(SCRIPT.parent / "load_settings.sh", scripts / "load_settings.sh")
            (root / "settings.yaml").write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
            sf = _posix(root / "settings.yaml")
            cmd = f'. {_posix(scripts / "load_settings.sh")} && load_settings && echo "$SETTINGS_FILE|$RAG_ROOT|$RAG_OUT|$NAME_SUFFIX"'
            r = _run(bash, ["-c", cmd], {"SETTINGS_LOADED": sf, "DOCKER": "echo", **ports}, script=None)
            assert r.returncode == 0, r.stderr
            want = f"{sf}|{_posix(root)}|{_posix(root)}/output|{'-' + inst if inst else ''}"
            assert r.stdout.strip() == want, (name, r.stdout)


def test_timers():
    """host_ctl.sh timers가 단위 파일 4개의 @CODE_DIR@를 이 코드 폴더로 채워 쓴다(DC_UNIT_DIR — systemctl 없음).
    여러 벌(루트 이름 끝 -<숫자>)이면 단위 이름 끝에 -<숫자>(타이머·서비스 짝이 같은 이름).
    개발 서버(dev)는 새벽 배치 2개만(검색 MCP를 띄우지 않아 MCP 살리기 없음), 운영 서버(prd)는 4개."""
    bash = _need_bash()
    if not bash:
        return
    src = sorted(p.name for p in (SCRIPT.parents[1] / "systemd").iterdir())
    for inst, run_env in (("", "prd"), ("2", "dev"), ("", "dev")):
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / "settings.yaml"
            sf.write_text(f"required:\n  env: {{run_env: {run_env}}}\n", encoding="utf-8")
            units_dir = Path(d) / "units"
            units_dir.mkdir()
            sp = _posix(sf)
            env = {
                "DC_UNIT_DIR": _posix(units_dir),
                "SETTINGS_FILE": sp,
                "SETTINGS_LOADED": sp,
                "RAG_ROOT": _posix(Path(d) / f"sbl_data_parsing-main{'-' + inst if inst else ''}"),  # 루트 이름 끝 -<숫자> = 벌 번호
                "RUN_ENV": run_env,  # load_settings가 내던 값(위 파일과 같음)
            }
            r = _run(bash, ["timers"], env)
            assert r.returncode == 0, r.stderr + r.stdout
            suffix = f"-{inst}" if inst else ""
            units = sorted(p.name for p in units_dir.iterdir())
            want = [n for n in src if run_env != "dev" or n.startswith("data-pipeline-nightly")]
            assert units == sorted(n.replace(".", suffix + ".", 1) for n in want) and len(units) == (2 if run_env == "dev" else 4), units
            for name in [n for n in want if n.endswith(".service")]:
                text = (units_dir / name.replace(".", suffix + ".", 1)).read_text(encoding="utf-8")
                assert "@CODE_DIR@" not in text and f"WorkingDirectory={_posix(SCRIPT.parents[3])}\n" in text, (name, text)
                assert "DOCKER=" not in text, (name, "컨테이너 도구는 settings.yaml ops.host.container_cli — unit이 덮지 않음")


FAKE = """case "$1" in
  "$DOWN") echo "[오류] 상주 컨테이너 data-pipeline가 떠 있지 않음 — 먼저 띄울 것"; exit 2 ;;
  "$FAIL") echo boom; exit 1 ;;
  selftest*) [ -n "${NOJUDGE:-}" ] && { echo "N/M 통과"; exit 0; }; echo "[판정] 통과 — FAIL 0" ;;
  *) echo "ok $1" ;;
esac
"""
# (FAIL 단계, NOJUDGE, 컨테이너가 꺼진 단계, 기대 종료 코드, 마지막 줄 시작, 나오면 안 되는 단계[, RUN_ENV — 없으면 dev])
CHECK_CASES = [
    ("", "", "", 0, "[host_ctl check] 통과 — 4개(개발 서버 — data-pipeline만)", "── selftest mcp-server"),  # 개발 서버 — 검색 MCP 단계 없음
    ("", "", "", 0, "[host_ctl check] 통과 — 6개", None, "prd"),
    ("migrate check", "", "", 1, "[host_ctl check] 실패 — migrate check:", "── selftest data-pipeline"),
    (
        "",
        "1",
        "",
        1,
        "[host_ctl check] 실패 — selftest data-pipeline:",
        "── selftest mcp-server",
    ),  # [판정] 줄이 없으면 종료 코드 0이어도 실패
    # pipe_exec.sh가 "상주 컨테이너가 떠 있지 않음"(종료 코드 2) — 띄우지 않고 안내로 멈춤
    (
        "",
        "",
        "check_env",
        1,
        "[host_ctl check] 실패 — check_env: data-pipeline 컨테이너가 안 떠 있음 → host_ctl.sh up -d data-pipeline",
        "── ping_models",
    ),
]


def test_check():
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "fake.sh"
        fake.write_text(FAKE, encoding="utf-8", newline="\n")
        sf = Path(d) / "settings.yaml"
        sf.write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
        for fail, nojudge, down, rc, last, absent, *run in CHECK_CASES:
            env = {
                "SETTINGS_FILE": _posix(sf),
                "SETTINGS_LOADED": _posix(sf),  # 이미 읽은 것으로 — settings_to_env.py를 부르지 않음
                "RUN_ENV": run[0] if run else "dev",  # load_settings가 내던 값 — 판정 명령이 -e RUN_ENV로 넘김(e2-22)
                "DOCKER": "echo",
                "DC_FAKE": f"bash {_posix(fake)}",
                "FAIL": fail,
                "NOJUDGE": nojudge,
                "DOWN": down or "-",
            }
            r = _run(bash, ["check"], env)
            lines = r.stdout.strip().splitlines()
            assert r.returncode == rc and lines[-1].startswith(last), (fail, nojudge, r.returncode, r.stdout, r.stderr)
            assert absent is None or absent not in r.stdout, (fail, r.stdout)


def test_init_refuses_chain_dir():
    """edw_chain.yaml 자리에 폴더(docker가 init 전에 띄운 마운트로 만든 것)가 있으면 지우지 않고 종료 4 — 그 안에 복사하지 않음."""
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "dev"
        bad = root / "edw_chain.yaml"
        bad.mkdir(parents=True)
        r = _run(bash, ["init"], {"DC_ROOT": _posix(root)})
        assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
        assert "edw_chain.yaml 자리에 폴더가 있음" in r.stderr and bad.is_dir() and not any(bad.iterdir()), r.stderr


PLACE_CASES = [  # (settings.yaml 덧붙임, 사슬 사본 자리, 홈 자리 — 루트 기준, 종료 코드) — ops.host.host_edw_chain_file·option.devbox.home_dir
    ("option:\n  devbox: {ssh_port: 2222}\n", "edw_chain.yaml", "home", 0),  # 비우면 <루트> 아래
    (
        "ops:\n  host: {host_edw_chain_file: chain_alt.yaml}\noption:\n  devbox: {ssh_port: 2222, home_dir: devhome}\n",
        "chain_alt.yaml",
        "devhome",
        0,
    ),
    (
        "ops:\n  host: {host_edw_chain_file: sub/c.yaml}\noption:\n  devbox: {ssh_port: 2222, home_dir: a/b/h}\n",
        "sub/c.yaml",
        "a/b/h",
        0,
    ),  # 위 폴더도 만듦
    ("ops:\n  host: {host_edw_chain_file: blocker/c.yaml}\n", "blocker/c.yaml", "", 5),  # 위 자리가 파일 — 복사 실패면 init 실패
]


def test_init_places_from_settings():
    """init이 사슬 사본·개발 작업 공간 홈을 설정 자리(상대 = 루트 기준, 위 폴더도)에 만들고 코드 폴더 a+rX에서 그 자리를 뺀다 —
    기본 자리에는 안 만듦. 복사가 실패하면 종료 5."""
    bash = _need_bash()
    if not bash:
        return
    for more, chain, home, rc in PLACE_CASES:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "dev"
            root.mkdir()
            (root / "blocker").write_text("", encoding="utf-8")
            (root / "settings.yaml").write_text("required:\n  env: {run_env: dev}\n" + more, encoding="utf-8")
            r = _run(bash, ["init"], {"DC_ROOT": _posix(root)})
            assert r.returncode == rc, (more, r.returncode, r.stderr + r.stdout)
            if rc:
                assert "복사 실패" in r.stderr, r.stderr
                continue
            assert (root / chain).is_file() and (root / home).is_dir(), (chain, home, r.stdout)
            skip = r.stdout.split("빼는 자리:", 1)[1].splitlines()[0]  # 코드 폴더 a+rX에서 빼는 자리(find -path)
            assert f"./{chain}" in skip.split() and f"./{home}" in skip.split(), skip
            for other in {"edw_chain.yaml", "home"} - {chain, home}:
                assert not (root / other).exists(), (other, r.stdout)
