"""파싱 단계 실행 — 파이프라인 입구(pipeline.cli parse)와 MCP 작업 서비스(pipeline.parse_service)가 함께 쓴다(rn-06)."""

import subprocess
import sys
import time
from pathlib import Path

from common.core import exitclean
from common.core import resources as RS  # 프로세스 묶음(OS 분기 한 곳)
from common.core.paths import APP_ROOT
from pipeline import config as pc


def stack(refresh=False):
    """엔진 구성(사전) — 파일을 읽어 없는 엔진을 거부(종료 2)한 뒤. refresh=True면 파일을 다시 읽는다(작업 서비스는 작업마다)."""
    from pipeline.extract import engine_stack

    engine_stack.resolve(refresh=refresh)
    return pc.stack()


def run_id(env):
    """이번 실행 id(PARSE_RUN_ID) — env에 있으면 그대로, 없으면 지금 시각을 넣는다. run_engines·끝 표시가 같은 id를 쓴다."""
    return env.setdefault("PARSE_RUN_ID", time.strftime("%Y%m%d-%H%M%S"))  # env 남김 — 하위 프로세스


def run_step(args, env, timeout=None, launch=subprocess.Popen, track=False, log=None):
    """단계 하나(`python -m <모듈> 인자…`)를 프로세스 묶음으로 돌린다 — proc.run span 하나(자식이 이어받는 부모 span).
    log(열린 글자 파일)를 주면 명령·출력을 거기에 남기고, 아니면 명령 줄만 화면에. 반환: CompletedProcess."""
    from common.core.span import safe, span

    cmd = [sys.executable, "-m", *map(str, args)]
    kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True} if log else {}
    if log is None:
        print("$ " + " ".join(cmd), flush=True)
    with span("proc.run", "run", module=str(args[0])) as sp:
        p = run_group(cmd, env, timeout, launch=launch, track=track, **kw)
        sp.add(rc=p.returncode)
        if p.returncode:
            sp.result("fail", None, safe(f"종료 코드 {p.returncode}"))
    if log:
        log.write(f"== {' '.join(map(str, args))}\n{p.stdout}\n{p.stderr}\n")
        log.flush()
    return p


def place_inputs(run, src, out, names, only):
    """준비 단계 — 파일 이름 목록을 only 파일에 적고 filter_and_rotate(src → out, 그 이름만)를 돌린다. 반환: run의 종료 코드."""
    Path(only).write_text("\n".join(names) + "\n", encoding="utf-8")
    return run(["pipeline.extract.filter_and_rotate", "--src", src, "--out", out, "--only", only])


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
