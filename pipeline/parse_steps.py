"""파싱 단계 실행 — 파이프라인 입구(pipeline.cli parse)와 MCP 작업 서비스(pipeline.parse_service)가 함께 쓴다(rn-06)."""

import subprocess
from pathlib import Path

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


def parse_chain(run, prep, parse_dir, truth, engine_args=()):
    """파싱 단계 사슬 run_engines(prep → parse_dir) → parse_scoring → build_rep. 준비(filter_and_rotate)는 호출자가 먼저 부른다
    (일괄 파싱은 준비와 엔진 사이에 새 문서 상한·VLM 동시 수를 정함). run(args) = 단계 하나(모듈 점 표기 + 인자)를 돌리고 종료 코드를
    돌려줌(작업 서비스는 실패면 run이 바로 RuntimeError). 채점·대표 결과가 실패하면 SystemExit(그 코드).
    반환: run_engines가 runs.jsonl을 못 남겼으면(돈 문서 0건, 또는 run_all이 죽음) 채점·대표 결과 없이 run_engines 종료 코드, 끝까지 돌면 None."""
    parse_dir = Path(parse_dir)
    rc = run(["pipeline.extract.run_engines", "--src", prep, "--out", parse_dir, *engine_args])
    if not (parse_dir / "runs.jsonl").exists():
        return rc
    for args in (
        ["pipeline.transform.represent.parse_scoring", "--src", prep, "--parse", parse_dir, "--truth", truth],
        ["pipeline.transform.represent.build_rep", "--src", prep, "--parse-dir", parse_dir],
    ):
        rc = run(args)
        if rc != 0:
            raise SystemExit(rc)
    return None
