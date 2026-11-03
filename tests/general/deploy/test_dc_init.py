"""dc.sh init·check(사용자 11-03) — init: DC_ROOT 임시 폴더에 서버 폴더를 만들고(두 번 불러도 같음) settings.yaml은 없을 때만 복사(덮지 않음),
code/live 링크는 없을 때만 만들고 있으면 그대로. check: DC_FAKE로 단계를 바꿔 끼워 처음 실패에서 멈추는지·selftest는 "[판정] 통과" 줄로 판정하는지.
docker·root·/srv 없음 — PC 전용."""

import os
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


def _run(bash, args, extra):
    env = {"PATH": os.environ.get("PATH", ""), "PY": Path(sys.executable).as_posix(), **extra}  # env 남김 — 하위 프로세스(시험 셸)
    return subprocess.run([bash, str(SCRIPT), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_init():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "rag"
        code = Path(d) / "sbl_data_parsing-main"  # live가 가리킬 코드 폴더(작게 — Windows Git Bash의 ln -s는 폴더를 복사함)
        (code / "deploy").mkdir(parents=True)
        base = {"DC_ROOT": _posix(root), "DC_CODE": _posix(code)}
        r1 = _run(bash, ["init"], base)
        assert r1.returncode == 0, r1.stderr + r1.stdout
        for sub in ("env", "output", "output/mcp_parse/jobs", "code", "backup"):
            assert (root / sub).is_dir(), (sub, r1.stdout)
        sf = root / "env" / "settings.yaml"
        chain = root / "env" / "edw_chain.yaml"  # 사슬 서버 사본(사용자 11-03) — 없을 때만 기본 파일에서
        assert chain.read_bytes() == (DEPLOY_ROOT / "resources" / "config" / "edw_chain.yaml").read_bytes(), "init이 사슬 사본을 안 만듦"
        assert sf.read_bytes() == (SCRIPT.parents[3] / "settings.sample.yaml").read_bytes()
        assert (root / "code" / "live").exists() and "만듦" in r1.stdout and "required.env.run_env" in r1.stdout, r1.stdout
        if os.name != "nt":  # Windows(Git Bash)는 권한·심볼릭 링크를 POSIX처럼 안 둠
            assert oct((root / "env").stat().st_mode & 0o7777) == "0o700" and oct(sf.stat().st_mode & 0o777) == "0o640"
            assert oct((root / "output").stat().st_mode & 0o7777) == "0o2775"
            assert os.path.realpath(root / "code" / "live") == os.path.realpath(code)
        sf.write_text("required:\n  env: {run_env: dev}\n", encoding="utf-8")  # 사람이 채운 설정 — 다시 불러도 그대로여야
        chain.write_text("files: {}\n", encoding="utf-8")  # 사람이 고친 사슬 사본 — 다시 불러도 그대로여야
        r2 = _run(bash, ["init"], {**base, "RAG_OUT": _posix(root / "output")})
        assert r2.returncode == 0, r2.stderr + r2.stdout
        assert sf.read_text(encoding="utf-8") == "required:\n  env: {run_env: dev}\n", "init이 settings.yaml을 덮음"
        assert chain.read_text(encoding="utf-8") == "files: {}\n", "init이 사슬 사본을 덮음"
        assert "덮지 않음" in r2.stdout and "만듦" not in r2.stdout, r2.stdout  # 멱등 — 두 번째는 모두 "있음"
    with tempfile.TemporaryDirectory() as d:  # live가 이미 있으면(옛 판을 가리킴) 옮기지 않음
        root = Path(d) / "rag"
        old = root / "code" / "live"
        old.mkdir(parents=True)
        (old / "OLD").write_text("x", encoding="utf-8")
        r = _run(bash, ["init"], {"DC_ROOT": _posix(root)})
        assert r.returncode == 0 and (old / "OLD").is_file() and "옮기지 않음" in r.stdout, r.stdout
    r = _run(bash, ["init", "--bad"], {"DC_ROOT": "/nonexistent"})
    assert r.returncode == 2, r.stdout


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
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
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
