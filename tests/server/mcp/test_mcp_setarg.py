"""op-22 — 검색 쪽 진입점(`mcp_server.main`·`ask`)도 `--set 이름=값`을 받는다(setarg.apply). 값이 실제로 먹는지는 그 값 때문에
시작이 멈추는 것으로 본다(멈추지 않으면 서버가 떠 시간 초과로 실패). 임시 설정 파일(run_env local, PG 없음)만 — 외부 접속 없음."""

import subprocess
import sys
import tempfile
from pathlib import Path

from common.core.paths import child_env

# (모듈, 인자, 출력에 있어야 할 글자, 없어야 할 글자)
CASES = [
    ("mcp_server.main", ["--set", "MCP_PORT=notaport"], "MCP_PORT", None),  # 포트 형식 검사에서 멈춤
    (
        "mcp_server.cli.search_ask",
        ["--set", "PG_HOST=127.0.0.9", "ask", "--source", "CRMS", "--q", "x"],
        "pg_port",
        "pg_host",  # PG 칸 일부만 채움 → 빠진 칸 목록에서 pg_host가 빠짐
    ),
]


def test_entry_set():
    d = Path(tempfile.mkdtemp())
    sf = d / "settings.yaml"
    sf.write_text("required:\n  env: {run_env: local}\n", encoding="utf-8")
    env = child_env({"SETTINGS_FILE": str(sf), "RUN_ENV": "local"})  # env 남김 — 시험: 자식 프로세스 설정 파일 자리·실행 환경 신호
    for module, args, want, unwanted in CASES:
        r = subprocess.run([sys.executable, "-m", module, *args], env=env, capture_output=True, timeout=120)
        out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        assert r.returncode != 0 and want in out, (module, r.returncode, out[-500:])
        assert unwanted is None or unwanted not in out, (module, out[-500:])
