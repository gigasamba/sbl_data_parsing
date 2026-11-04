"""dc.sh init·timers·check(사용자 11-03 · op-13) — init: DC_ROOT 임시 루트에 settings.yaml·edw_chain.yaml·output/·backup/을 만들고(두 번 불러도 같음)
settings.yaml은 없을 때만 복사(덮지 않음), env/·code/·live는 만들지 않음. 루트는 코드 폴더의 부모(settings_env.sh). timers: 단위 파일의 @CODE_DIR@를
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
        for sub in ("output", "output/_mcp_parse/jobs", "backup"):
            assert (root / sub).is_dir(), (sub, r1.stdout)
        for gone in ("env", "code"):
            assert not (root / gone).exists(), (gone, r1.stdout)
        sf = root / "settings.yaml"
        chain = root / "edw_chain.yaml"  # 사슬 서버 사본(사용자 11-03) — 없을 때만 기본 파일에서
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
    r = _run(bash, ["init", "--bad"], {"DC_ROOT": "/nonexistent"})
    assert r.returncode == 2, r.stdout


def test_root_is_code_parent():
    """op-13 규칙 1 — settings_env.sh는 자기 자리(코드 폴더/deploy/host/scripts)에서 루트(코드 폴더의 부모)를 구해 <루트>/settings.yaml을 읽고
    결과 폴더를 <루트>/output으로 둔다(env·고정 경로 없음). SETTINGS_LOADED로 host_env.py(PyYAML) 부르기는 건너뜀."""
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "dev"
        scripts = root / "sbl_data_parsing-0.3.0" / "deploy" / "host" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(SCRIPT.parent / "settings_env.sh", scripts / "settings_env.sh")
        (root / "settings.yaml").write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")
        sf = _posix(root / "settings.yaml")
        cmd = f'. {_posix(scripts / "settings_env.sh")} && load_settings && echo "$SETTINGS_FILE|$RAG_ROOT|$RAG_OUT"'
        r = _run(bash, ["-c", cmd], {"SETTINGS_LOADED": sf, "DOCKER": "echo"}, script=None)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == f"{sf}|{_posix(root)}|{_posix(root)}/output", r.stdout


def test_timers():
    """op-13 규칙 6 — dc.sh timers가 단위 파일 4개의 @CODE_DIR@를 이 코드 폴더로 채워 쓴다(DC_UNIT_DIR — systemctl 없음)."""
    bash = _need_bash()
    if not bash:
        return
    with tempfile.TemporaryDirectory() as d:
        r = _run(bash, ["timers"], {"DC_UNIT_DIR": _posix(d)})
        assert r.returncode == 0, r.stderr + r.stdout
        units = sorted(p.name for p in Path(d).iterdir())
        assert units == sorted(p.name for p in (SCRIPT.parents[1] / "systemd").iterdir()) and len(units) == 4, units
        for name in ("data-pipeline-nightly.service", "mcp-server-keepalive.service"):
            text = (Path(d) / name).read_text(encoding="utf-8")
            assert "@CODE_DIR@" not in text and f"WorkingDirectory={_posix(SCRIPT.parents[3])}\n" in text, (name, text)


FAKE = """case "$1" in
  "$DOWN") echo "[오류] 상주 컨테이너 data-pipeline가 떠 있지 않음 — 먼저 띄울 것"; exit 2 ;;
  "$FAIL") echo boom; exit 1 ;;
  selftest*) [ -n "${NOJUDGE:-}" ] && { echo "N/M 통과"; exit 0; }; echo "[판정] 통과 — FAIL 0" ;;
  *) echo "ok $1" ;;
esac
"""
# (FAIL 단계, NOJUDGE, 컨테이너가 꺼진 단계, 기대 종료 코드, 마지막 줄 시작, 나오면 안 되는 단계)
CHECK_CASES = [
    ("", "", "", 0, "[dc check] 통과 — 6개", None),
    ("migrate check", "", "", 1, "[dc check] 실패 — migrate check:", "── selftest data-pipeline"),
    ("", "1", "", 1, "[dc check] 실패 — selftest data-pipeline:", "── selftest mcp-server"),  # [판정] 줄이 없으면 종료 코드 0이어도 실패
    # run_tool.sh가 "상주 컨테이너가 떠 있지 않음"(종료 코드 2) — 띄우지 않고 안내로 멈춤
    (
        "",
        "",
        "check_env",
        1,
        "[dc check] 실패 — check_env: data-pipeline 컨테이너가 안 떠 있음 → dc.sh up -d data-pipeline",
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
        for fail, nojudge, down, rc, last, absent in CHECK_CASES:
            env = {
                "SETTINGS_FILE": _posix(sf),
                "SETTINGS_LOADED": _posix(sf),  # 이미 읽은 것으로 — host_env.py를 부르지 않음
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
    """edw_chain.yaml 자리에 폴더(docker가 init 전에 띄운 마운트로 만든 것)가 있으면 지우지 않고 종료 4 — 그 안에 복사하지 않음(리뷰 #140)."""
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
