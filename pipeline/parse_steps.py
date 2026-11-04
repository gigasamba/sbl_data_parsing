"""파싱 단계 실행 — 파이프라인 입구(pipeline.cli parse)와 MCP 작업 서비스(pipeline.parse_service)가 함께 쓴다(rn-06)."""

import subprocess

from common.core import exitclean
from common.core import resources as RS  # 프로세스 묶음(OS 분기 한 곳)
from common.core.paths import APP_ROOT


def run_group(cmd, env, timeout=None, launch=subprocess.Popen, track=False, **kw):
    """명령 cmd를 새 프로세스 묶음으로 띄워 끝날 때까지 기다린다. timeout(초)을 넘으면 묶음째 끝내고(run_all이 띄운 엔진 손자까지)
    subprocess.TimeoutExpired를 올린다. cwd = APP_ROOT(런타임 루트 — 코드 루트로 하면 --src 상대경로가 거기 기준으로 풀려 못 찾음, FS v4 회귀).
    launch = 띄우는 함수(일괄 파싱은 메모리·CPU 문을 거치는 RS.gated_popen) · track = 이 프로세스가 끝날 때 아직 돌면 묶음째 끝냄
    (상주 작업 서비스 — exitclean, pl-27) · kw = Popen 인자(stdout=PIPE 등). 반환: CompletedProcess."""
    p = launch(cmd, cwd=APP_ROOT, env=env, **kw, **RS.group_kw())
    if track:
        exitclean.track(p, group=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        RS.kill_group(p)
        raise
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)
