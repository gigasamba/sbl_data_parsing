"""runs.jsonl 프로세스 간 잠금 점검(백로그 E11): 프로세스 4개가 같은 파일에 큰 줄 300개씩 동시에 → 모든 줄이 JSON으로 읽혀야 함.
사용: python -m pipeline.tools.check_runlog .   (dev 폴더에서) — 서버(Linux, fcntl)에서 한 번 확인"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _main():
    HERE = Path(sys.argv[1])
    if len(sys.argv) > 3:
        from pipeline.extract.run_all import RunLog

        log = RunLog(sys.argv[2])
        for i in range(300):
            log.write(json.dumps({"p": sys.argv[3], "i": i, "pad": "가" * 20000}, ensure_ascii=False) + "\n")
        return
    d = Path(tempfile.mkdtemp()) / "runs.jsonl"
    ps = [subprocess.Popen([sys.executable, "-m", "pipeline.tools.check_runlog", str(HERE), str(d), str(k)], cwd=HERE) for k in range(4)]
    assert all(p.wait() == 0 for p in ps)
    rows = [json.loads(x) for x in d.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1200 and len({(r["p"], r["i"]) for r in rows}) == 1200
    print("[check] 4 프로세스 × 300줄 동시 쓰기 → 1200줄 모두 정상")


if __name__ == "__main__":
    _main()
