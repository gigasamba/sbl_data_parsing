"""trigger.sh scheduled 시각 게이트(pl-32, 사용자 10-30) — settings.yaml ops.nightly.time(NIGHTLY_TIME)이 비면 조용히 끝, 그 시각부터
5분 안이면 night, 꼴이 틀리면 종료 2. trigger.sh에서 게이트 블록만 떼어 bash로 돌린다(date는 셸 함수로 바꿔 끼움 — 설정·docker 없음, PC 전용)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

CASES = [  # (NIGHTLY_TIME, 지금, 종료 코드, night로 넘어감?)
    ("", "01:00", 0, False),  # 비움 = 새벽 배치 없음
    ("  ", "01:00", 0, False),  # 공백만 = 비움
    ("01:00", "01:00", 0, True),
    ("01:00", "01:04", 0, True),
    ("01:00", "01:05", 0, False),  # 창은 5분
    ("01:00", "00:59", 0, False),
    ("23:58", "00:01", 0, True),  # 자정을 넘는 창
    ("23:58", "23:55", 0, False),
    ("08:09", "08:09", 0, True),  # 앞자리 0(8진수로 읽지 않음)
    ("1:30", "01:30", 2, False),  # 꼴 오류
    ("24:00", "00:00", 2, False),
    ("01:30:00", "01:30", 2, False),
]


def _bash():
    if os.name == "nt":  # System32 bash.exe는 WSL — Git Bash를 씀
        git = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"  # env 남김 — OS 값
        return str(git) if git.is_file() else None
    return shutil.which("bash")


def _gate():
    text = (ROOT / "deploy" / "host" / "scripts" / "trigger.sh").read_text(encoding="utf-8")
    m = re.search(r'^if \[ "\$mod" = "scheduled" \]; then\n.*?^fi\n', text, re.S | re.M)
    assert m, "trigger.sh에 scheduled 게이트 블록이 없음"
    return m.group(0)


def test_scheduled_gate():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    gate = _gate()
    for t, now, rc, runs in CASES:
        script = f'date() {{ echo "{now}"; }}\nmod=scheduled\n{gate}echo "mod=$mod"\n'
        r = subprocess.run(
            [bash, "-c", script],
            env={**os.environ, "NIGHTLY_TIME": t},  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert r.returncode == rc, (t, now, r.returncode, r.stderr)
        assert ("mod=night" in r.stdout) is runs, (t, now, r.stdout)
