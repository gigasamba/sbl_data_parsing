"""pl-27 — 프로세스가 끝날 때(정상·오류·SIGTERM) 덮기 설정 파일·PID 기록이 지워지고, 띄운 자식이 끝나고 회수된다(common.core.exitclean).
가운데 프로세스가 overlay_file로 덮기 파일을 만들고 gated_popen으로 심장박동 자식(파일에 0.1초마다 씀)을 띄운 뒤 세 방식으로 끝난다.
SIGTERM 사례는 POSIX 전용(Windows는 건너뜀 — 신호가 없음). 외부 접속 없음, 임시 폴더만."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common.core.paths import child_env

_HEART = "import sys, time\nfor _ in range(600):\n    open(sys.argv[1], 'w').write(str(time.time()))\n    time.sleep(0.1)\n"

_MID = f"""
import sys, time
from common.config import settings as C
from common.core import exitclean, resources as RS
mode, hb, pid_file = sys.argv[1], sys.argv[2], sys.argv[3]
p = C.overlay_file({{"PIPE_PROCS": "1"}})
exitclean.remove_at_exit(pid_file)
open(pid_file, "w").write("1")
child = RS.gated_popen([sys.executable, "-c", {_HEART!r}, hb], **exitclean.group_kw())
while not __import__("os").path.exists(hb):
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


def test_exit_cleanup():
    for mode in ("ok", "error"):
        _case(mode)
    if os.name == "nt":
        print("[시험] term — 건너뜀(POSIX 전용: Windows에는 SIGTERM이 없음)")
    else:
        _case("term")
