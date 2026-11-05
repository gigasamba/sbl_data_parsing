"""nightly_batch.sh scheduled 시각 게이트(pl-32) — settings.yaml ops.nightly.time·max_docs·deadline(NIGHTLY_TIME·
NIGHTLY_MAX_DOCS·NIGHTLY_DEADLINE) 중 하나라도 비면 조용히 끝, 시작 시각부터 5분 안이면 run_pipeline.py(새벽 배치 = run_pipeline)에
상한·마감을 넘김, 꼴이 틀리면 종료 2. nightly_batch.sh에서 게이트 블록만 떼어 bash로 돌린다(date·python3은 셸 함수로 바꿔 끼움 — run_pipeline은 돌지 않음, 설정·docker 없음, PC 전용)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from common.core.paths import DEPLOY_ROOT

ROOT = DEPLOY_ROOT  # 저장소 루트(paths 상수)

CASES = [  # (NIGHTLY_TIME, 지금, 종료 코드, run_pipeline을 부름?) — 상한 50·마감 06:00
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
OTHER = [  # (NIGHTLY_MAX_DOCS, NIGHTLY_DEADLINE, 종료 코드, run_pipeline을 부름?) — 시작 01:00·지금 01:00(셋 다 있어야 돎)
    ("", "06:00", 0, False),
    ("50", "", 0, False),
    ("  ", " ", 0, False),
    ("0", "06:00", 2, False),
    ("5x", "06:00", 2, False),
    ("50", "6:00", 2, False),
    ("50", "01:03", 2, False),  # 마감이 시작 창 안 — 늦게 깬 타이머면 마감이 다음 날로 밀림
    ("50", "01:00", 2, False),
    ("50", "01:05", 0, True),
]


def _bash():
    if os.name == "nt":  # System32 bash.exe는 WSL — Git Bash를 씀
        git = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"  # env 남김 — OS 값
        return str(git) if git.is_file() else None
    return shutil.which("bash")


def _gate():
    text = (ROOT / "deploy" / "host" / "scripts" / "nightly_batch.sh").read_text(encoding="utf-8")
    m = re.search(r'^if \[ "\$mod" = "scheduled" \]; then\n.*?^fi\n', text, re.S | re.M)
    assert m, "nightly_batch.sh에 scheduled 게이트 블록이 없음"
    return m.group(0)


def test_scheduled_gate():
    bash = _bash()
    if not bash:
        print("[시험] bash 없음 — 건너뜀")
        return
    gate = _gate()
    cases = [(t, now, "50", "06:00", rc, runs) for t, now, rc, runs in CASES] + [
        ("01:00", "01:00", n, dl, rc, runs) for n, dl, rc, runs in OTHER
    ]
    for t, now, n, dl, rc, runs in cases:
        script = f'date() {{ echo "{now}"; }}\npython3() {{ echo "RUN_PIPELINE $*"; }}\nmod=scheduled\n{gate}echo "mod=$mod"\n'
        r = subprocess.run(
            [bash, "-c", script],
            env={
                **os.environ,
                "NIGHTLY_TIME": t,
                "NIGHTLY_MAX_DOCS": n,
                "NIGHTLY_DEADLINE": dl,
            },  # env 남김 — 하위 프로세스(호스트 셸이 load_settings로 받는 이름 — 시험)
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert r.returncode == rc, (t, now, n, dl, r.returncode, r.stderr)
        want = (
            f"RUN_PIPELINE deploy/host/scripts/run_pipeline.py --start-offset 0 --skip-done --max-docs {n.strip()} --deadline {dl.strip()}"
        )
        assert (want in r.stdout) is runs, (t, now, n, dl, r.stdout)
