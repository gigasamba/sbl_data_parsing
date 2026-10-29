"""pl-27 — 프로세스가 끝날 때(정상·오류·SIGTERM) 그 프로세스가 맡은 덮기 설정 파일(child_env)·PID 기록이 지워지고, 띄운 자식이 끝나고
회수된다(common.core.exitclean). 가운데 프로세스가 child_env로 덮기 파일을 만들고 gated_popen으로 심장박동 자식(파일에 0.1초마다 씀)을
띄운 뒤 세 방식으로 끝난다. SIGTERM 사례는 POSIX 전용(Windows는 건너뜀 — 신호가 없음).
지우면 안 되는 것도 본다: overrides 도구가 다른 프로세스에 넘기는 덮기 파일은 남고, settings.isolated는 블록이 끝날 때 지운다.
외부 접속 없음, 임시 폴더만."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common.config import settings as C
from common.core.paths import child_env

_HEART = "import sys, time\nfor _ in range(600):\n    open(sys.argv[1], 'w').write(str(time.time()))\n    time.sleep(0.1)\n"

_MID = f"""
import os, sys, time
from common.config import settings as C
from common.core import exitclean, resources as RS
mode, hb, pid_file = sys.argv[1], sys.argv[2], sys.argv[3]
p = C.child_env(None, PIPE_PROCS="1")["SETTINGS_FILE"]
exitclean.remove_at_exit(pid_file)
open(pid_file, "w").write("1")
child = RS.gated_popen([sys.executable, "-c", {_HEART!r}, hb])
while not os.path.exists(hb):
    time.sleep(0.05)
print(p, child.pid, flush=True)
if mode == "error":
    raise RuntimeError("시험 — 오류 종료")
if mode == "term":
    time.sleep(60)
"""


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _case(mode):
    d = Path(tempfile.mkdtemp())
    hb, pid_file = d / "heart.txt", d / "service.json"
    m = subprocess.Popen(
        [sys.executable, "-c", _MID, mode, str(hb), str(pid_file)],
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert m.stdout is not None
    overlay, child_pid = m.stdout.readline().split()
    assert Path(overlay).exists() and pid_file.exists(), (mode, overlay)
    if mode == "term":
        m.terminate()  # POSIX SIGTERM
    _, err = m.communicate(timeout=60)
    assert m.returncode == {"ok": 0, "error": 1, "term": 143}[mode], (mode, m.returncode, err[-500:])
    assert not Path(overlay).exists(), f"{mode}: 덮기 파일이 남음 {overlay}"
    assert not pid_file.exists(), f"{mode}: PID 기록이 남음"
    beat = hb.read_text(encoding="utf-8")
    time.sleep(0.5)
    assert hb.read_text(encoding="utf-8") == beat, f"{mode}: 자식이 아직 돎(심장박동 계속)"
    if os.name != "nt":
        assert _gone(int(child_pid)), f"{mode}: 자식 PID {child_pid}가 남음(좀비·고아)"
    print(f"[시험] {mode} — 덮기 파일·PID 기록 지움, 자식 끝내고 회수")


def _kept_files():
    """지우면 안 되는 것 — overrides 도구의 출력 파일(다른 프로세스가 읽음)은 남고, isolated는 블록 끝에서 지움."""
    r = subprocess.run(
        [sys.executable, "-m", "common.config.overrides", "PIPE_PROCS=1"], env=child_env(), capture_output=True, text=True, timeout=60
    )
    out = Path(r.stdout.strip())
    assert r.returncode == 0 and out.is_file(), (r.returncode, r.stderr[-300:])
    out.unlink()
    with C.isolated(PIPE_PROCS="1"):
        inner = Path(os.environ["SETTINGS_FILE"])  # env 남김 — 시험: 덮기 파일 자리
        assert inner.is_file()
    assert not inner.exists(), "isolated 블록이 끝났는데 덮기 파일이 남음"
    print("[시험] overrides 출력 파일은 남김 · isolated는 블록 끝에서 지움")


def _setarg_exec():
    """POSIX — `--set`은 덮기 파일을 만든 뒤 os.execve로 자기를 다시 띄운다(atexit가 안 돎) → 새 프로세스가 그 파일을 맡아 끝날 때 지움."""
    d = tempfile.mkdtemp()
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.stackcfg", "--set", "PIPE_PROCS=1"],
        env={**child_env(), "TMPDIR": d},
        capture_output=True,
        timeout=60,
    )
    left = sorted(Path(d).glob("settings-*.yaml"))
    assert not left, (r.returncode, left)
    print("[시험] --set(execve) — 덮기 파일 지움")


def test_exit_cleanup():
    _kept_files()
    for mode in ("ok", "error"):
        _case(mode)
    if os.name == "nt":
        print("[시험] term — 건너뜀(POSIX 전용: Windows에는 SIGTERM이 없음)")
    else:
        _case("term")
        _setarg_exec()
