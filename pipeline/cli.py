#!/usr/bin/env python3
"""파이프라인 진입점.

단계 2 · 고정 스택(정해진 기술로 실제 파이프라인 + 기본 테스트)
  show-stack  지금 엔진 구성(파일 — 서버·PC 같음, 바꾸기 = 파일 고쳐 오버레이 패치 —
                  docs/architecture/resources.md §1)
  parse           파싱 모듈 1회(run_pipeline이 문서마다 부름) — 끝 표시 _rep/_DONE.json
  (서버 입구는 run_pipeline 하나 — 구조화·적재는 run_pipeline이 모듈을 직접 부름. 검색 명령은 python -m mcp_server.cli.ask)
산출 위치: output/parse(파싱) · output/parse/_rep(대표) · output/edw/bundle(구조화) · output/report(보고서)
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서
from common.core.console import utf8_stdout

# isort: split
import argparse
import contextlib
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import settings as C  # common 칸 설정(cfg()·given()·render())
from common.core.paths import APP_ROOT, DEPLOY_ROOT, PKG_ROOT  # output/ 등 런타임 경로용
from pipeline import config as pc  # pipeline 칸 설정(cfg()·given())

ROOT = PKG_ROOT  # common/ — 하위 프로세스 cwd·저장소 문서 찾기용(ROOT.parent = deploy/)
OUT = Path(pc.cfg().paths.out_root or (APP_ROOT / "output"))  # import 때 한 번
PY = sys.executable


def _run_step(args, env):
    """단계 하나를 자식 프로세스 묶음(메모리·CPU 문을 거침)으로 돌리고 종료 코드를 돌려준다. args[0] = 모듈 점 표기."""
    from common.core import resources as RS
    from pipeline.parse_steps import run_step

    return run_step(args, env, launch=RS.gated_popen).returncode


# ── 단계 2 ───────────────────────────────────────────────────
def show_stack(a=None):
    """지금 엔진 구성(파일 — 서버·PC 같음). mcp-server 이미지에서도 됨(등록부 안 씀)."""
    from common.store.db import cfgfile

    cur = cfgfile.active("stack", refresh=True)
    st = cur.body
    print(f"스택 {cur.name} ({st.get('source', '')}) · {cur.label()}")
    print("| 형식 | 파싱 엔진(우선순위) |\n|---|---|")
    for f, es in sorted(st["parse"].items()):
        print(f"| {f} | {' → '.join(es)} |")
    print(f"청킹 {st['chunk']} · 임베딩 {st['embed']}")


# ── 파싱 모듈(run_pipeline이 문서마다 부름) ──────────
# 파싱 끝 표시(_rep/_DONE.json)는 남김 — 읽고 쓰기는 대표 결과 단계(pipeline.transform.represent.doc_represent.write_mark).


_T_STEP: dict = {}


def _tstep(name):
    _T_STEP[name] = time.time()


def _tdone():
    if not _T_STEP:
        return ""
    keys = list(_T_STEP)
    parts, prev = [], keys[0]
    for k in keys[1:]:
        parts.append(f"{prev.replace('t_', '')}={_T_STEP[k] - _T_STEP[prev]:.1f}s")
        prev = k
    _T_STEP.clear()
    return " · ".join(parts)


def parse_module(a):
    """파싱 모듈: extract(--staged = candidate_ready stage가 끝낸 목록 · --source = 같은 stage_batch를 여기서) → 파싱 → 채점 → 대표 결과 →
    끝 표시 → (s3) 원본 정리. 임베딩·DB 연결 없음. 둘 다 없으면 --src(이미 준비된 폴더)를 그대로."""
    from common.core.paths import child_env
    from pipeline.extract import candidate_pick as PICK
    from pipeline.extract import candidate_ready as SRC
    from pipeline.transform.parse import engine_check
    from pipeline.transform.parse import parse_engines as RE

    _tstep("t_start")
    from pipeline import parse_steps

    run_id = parse_steps.run_id(os.environ)  # env 남김 — 하위 프로세스(이후 하위 호출이 상속으로 받음)
    st = parse_steps.stack()
    from pipeline.shared import runtrace

    runtrace.info(stack=st.get("name"), workers=int(a.workers) if str(a.workers).isdigit() else None)
    engines = a.engines or ",".join(engine_check.engines_of(st))  # parse 엔진(정렬)
    lim, src_info, remote = [], None, False
    if getattr(a, "staged", False):  # extract는 candidate_ready stage가 이 결과 폴더에 끝냄 — 남은 이름 목록만 읽는다
        state = OUT / "parse" / "_source"
        only = state / "only.txt"
        if not only.exists():
            raise SystemExit(f"[parse] 받아 둔 문서 목록 없음({only}) — candidate_ready stage를 먼저")
        C.put(SOURCE_MANIFEST=str(state / "manifest.jsonl"))  # 원본 위치 주소(s3://) — stage가 쓴 manifest
        src_info, remote = state, True
        lim = ["--docs-from", only]
    elif a.source:
        _, _, state, only = SRC.stage_batch(
            a.source, OUT, a.src, a.source_limit, lambda args: _run_step(args, child_env()), done=PICK.done_keys()
        )
        src_info, remote = state, PICK.is_remote(a.source)
        _tstep("t_prepare")
        lim = ["--docs-from", only]
    if a.max_new:
        lim = ["--docs-from", PICK.pick_new(a.src, OUT, a.max_new, lim[1] if lim else None)]
    env = C.child_env(child_env(), VLM_CONCURRENCY=str(RE.vlm_doc_concurrency(a, lim)), LLM_BASE_URL=None)  # 파싱 모듈은 LLM을 부르지 않음

    def step(args):  # 단계마다 걸린 시간(docflow-step 로그 — parse_engines는 parse)
        rc = _run_step(args, env)
        _tstep("t_parse" if args[0] == "pipeline.transform.parse.parse_engines" else "t_" + args[0].rsplit(".", 1)[-1])
        return rc

    engine_args = ["--procs", a.procs, "--workers", a.workers, "--engines", engines, *lim]
    rc = parse_steps.parse_chain(step, a.src, OUT / "parse", OUT / "corpus" / "truth.json", engine_args)
    if rc is not None:  # runs.jsonl 없음: 채점·대표 결과로 넘어가 죽지 않게
        if rc != 0:  # parse_engines가 죽어 못 씀 — 성공으로 덮지 않는다
            print(f"[parse] 파싱 실패 — run_all 종료 {rc}, runs.jsonl 없음", file=sys.stderr, flush=True)
            raise SystemExit(rc)
        print("[parse] 이번 실행 0건 — 파싱한 문서 없음(runs.jsonl 없음) · 채점·대표 결과·끝 표시 건너뜀", flush=True)
        return
    from pipeline.transform.represent import doc_represent as BR

    print(f"[docflow-step] {_tdone()}", flush=True)  # resolve~represent 단계별 시간 로그
    idx, digest = BR.rep_digest(OUT / "parse")
    ok = sum(1 for r in idx if r.get("engine"))
    runtrace.docs(total=len(idx), ok=ok, fail=len(idx) - ok)  # 재사용 수는 없음 — 실행마다 새로 파싱
    if not BR.write_mark(
        OUT / "parse",
        src=str(a.src),
        source=str(a.source or a.src),
        engines=engines.split(","),
        docs=len(idx),
        digest=digest,
        rep_ok=ok,
        run_id=run_id,
    ):
        return
    if src_info and remote:
        SRC.finish(src_info, OUT / "parse" / "_rep" / "index.json")


# ── 운영자 자기 점검(selftest) ──────────────────────────────────
# 이미지 명령 `selftest`는 서버 반입 시험 tests/server/<앱>/test_*.py를
# 파일마다 자식 프로세스(python -m tests.runner <시험 모듈>)로 돌려 PASS/FAIL 표를 낸다 — 반입 판정은 deploy/release/selftest_gate.sh(알려진 FAIL은
# known_fail.txt, 사례 이름 = 시험 모듈 이름). 폴더가 곧 이미지: common = 두 이미지 · pipeline = data-pipeline · mcp = mcp-server(RAG_MODULE).
# PC 일반 시험(tests/general — PC 전용·느린 것·PG·Docker)은 pytest로만(`python -m pytest tests/` — tests/conftest.py가 같은 자식 프로세스·같은 env로).
TESTS_ROOT = DEPLOY_ROOT / "tests"  # 저장소 루트 tests/ · 이미지 /app/deploy/tests(PYTHONPATH와 같은 뿌리)
IMAGE_DIRS = {"common": None, "pipeline": "pipeline", "mcp": "mcp"}  # tests/server/<폴더> → 도는 이미지(None = 둘 다)
_FAKE_LLM_CASES = frozenset({"tests.server.mcp.test_mcp_main"})  # LLM_FAKE를 켜는 사례(질문 분해)
# PC에서 개발자 루트 settings.yaml(실 PG)을 그대로 읽어야 판정되는 사례 — 그 밖 PC 사례는 시험 전용 바탕 설정(case_env)
_PC_SETTINGS_CASES: frozenset[str] = frozenset()


def server_cases():
    """[(시험 모듈, 이미지|None)] — tests/server/<폴더>/test_*.py(이름순). 모르는 폴더는 사례로 넣지 않고 FAIL 사례로(오타·새 앱을 놓치지 않게)."""
    out = []
    for p in sorted((TESTS_ROOT / "server").glob("*/test_*.py")):
        out.append((f"tests.server.{p.parent.name}.{p.stem}", IMAGE_DIRS.get(p.parent.name, "?")))
    return out


_CASE_ENVS: dict = {}


def case_env(mod):
    """사례 자식 env(새 dict) — 모델 주소·예산 비움(외부 호출 없음)·LLM_FAKE(_FAKE_LLM_CASES만)는 덮기 파일로(env dict의 설정 이름은 자식이
    안 읽음). 두 벌만 만든다. PC pytest(tests/conftest.py)도 이것을 쓴다 — 이미지 selftest와 같은 env."""
    from common.core.paths import child_env

    fake = mod in _FAKE_LLM_CASES
    own = not C.IN_IMAGE and mod not in _PC_SETTINGS_CASES  # PC 시험은 시험 전용 바탕 설정(아래 _case_settings)
    if (fake, own) not in _CASE_ENVS:
        import tempfile

        blank: dict[str, str | None] = {
            **dict.fromkeys(("LLM_BASE_URL", "VLM_BASE_URL", "EMBED_BASE_URL", "LLM_BUDGET_USD")),
            **dict.fromkeys(("LLM_ALLOW_EXTERNAL", "VLM_ALLOW_EXTERNAL", "EMBED_ALLOW_EXTERNAL"), "0"),  # 외부 전송 늘 끔
            # 하루 장부를 시험마다 따로 — 개발자의 output/_llm_spend 장부에 섞이지 않게
            "LLM_SPEND_FILE": str(Path(tempfile.mkdtemp(prefix="selftest_spend_")) / "spend.txt"),
        }
        base = child_env({"PYTHONUTF8": "1"})
        if own:  # PC — 개발자 루트 settings.yaml(실 PG·모델 키) 대신 시험 전용 최소 설정 위에 덮음(시험 격리)
            base["SETTINGS_FILE"] = _case_settings()
        _CASE_ENVS[(fake, own)] = C.child_env(base, LLM_FAKE="1" if fake else None, **blank)
    return dict(_CASE_ENVS[(fake, own)])


def _case_settings():
    """PC 시험 사례의 바탕 설정 파일 — run_env: local만(접속·키 없음 → 정형 저장소는 SQLite, 모델 호출 없음). 한 번 만든다."""
    if "file" not in _CASE_ENVS:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="case_settings_", suffix=".yaml")
        os.write(fd, b"required:\n  env:\n    run_env: local\n")
        os.close(fd)
        _CASE_ENVS["file"] = path
    return _CASE_ENVS["file"]


def _spec_missing(mod):
    """이 이미지에 없는 모듈인지 — 중간 패키지가 없으면 find_spec이 ModuleNotFoundError를 던지므로 그것도 없음으로."""
    import importlib.util

    try:
        return importlib.util.find_spec(mod) is None
    except ModuleNotFoundError:
        return True


def _image_lacks(top):
    """이 이미지에 그 앱 코드가 아예 없는지(최상위 이름 pipeline·mcp_server) — pipeline은 mcp 이미지에 명령용 cli.py·config.py만
    들어가므로 단계 코드(pipeline.extract)로, mcp_server는 pipeline 이미지에 설정 모델 config.py만 들어가므로 검색 코드(mcp_server.services)로
    본다. 하위 모듈 이름 하나가 없는 것(오타·빠진 COPY)은 SKIP이 아니라 FAIL로 남긴다."""
    return _spec_missing("pipeline.extract" if top == "pipeline" else "mcp_server.services")


def _selftest_workers():
    """selftest 동시 사례 수 — 이 프로세스가 쓸 수 있는 CPU 수(컨테이너 CPU 고정 반영 — sched_getaffinity), 많아도 8."""
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return max(1, min(8, cpus))


def selftest(a):
    """`docker run … IMG selftest` — 서버 반입 시험(tests/server)을 파일마다 자식 프로세스로(네트워크 0 · case_env) 돌려 PASS/FAIL 표. 하나라도
    FAIL이면 종료 코드 1. 이미지 안(RAG_MODULE=pipeline·mcp)에서는 다른 이미지 폴더의 사례를 SKIP, RAG_MODULE이 비면(PC) 전부. 공용(common) 사례가
    이 이미지에 없는 앱 모듈 때문에만 실패하면 SKIP(진짜 오류는 FAIL) · 서드파티 패키지가 없어 실패한 것은 FAIL(I2c). 시험 폴더가 없거나 사례가 0개면
    FAIL(이미지 COPY 누락). --only <이름 조각>(여러 번) — 그 사례만."""
    import re

    image = os.environ.get("RAG_MODULE", "").strip()  # env 남김 — 내부 신호(5-3 H)
    image = image if image in ("pipeline", "mcp") else ""
    cases = server_cases()
    only = getattr(a, "only", None) or []
    if only:
        cases = [c for c in cases if any(o in c[0] for o in only)]
    rows = []
    if not cases:
        rows.append((str(TESTS_ROOT / "server"), "FAIL", "서버 반입 시험이 없음(tests/server — 이미지 COPY·--only 확인)"))

    def run_case(case):
        mod, img = case
        if img == "?":
            return (mod, "FAIL", "모르는 시험 폴더(tests/server/{common,pipeline,mcp}만)")
        if image and img not in (None, image):
            return (mod, "SKIP", f"다른 이미지 사례({img})")
        r = subprocess.run(
            [PY, "-m", "tests.runner", mod],
            cwd=ROOT,
            env=case_env(mod),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        out = r.stdout + r.stderr
        # 공용 사례가 이 이미지에 없는 앱 모듈 때문에만 실패했으면 SKIP(mcp 이미지에는 pipeline/ 중 cli.py·config.py만 — _image_lacks)
        miss = re.findall(r"ModuleNotFoundError: No module named '(pipeline|mcp_server)['.]", out)
        if r.returncode != 0 and miss and all(_image_lacks(m) for m in set(miss)):
            return (mod, "SKIP", f"다른 이미지 모듈 필요({', '.join(sorted(set(miss)))})")
        return (mod, "PASS" if r.returncode == 0 else "FAIL", "" if r.returncode == 0 else out[-1500:])

    # 사례는 서로 다른 자식 프로세스라 함께 돌림(쓸 수 있는 CPU 수, 많아도 8개) — map은 순서를 지켜 표는 그대로
    for mod, _ in cases:  # 덮기 파일 캐시(_CASE_ENVS)를 먼저 채움 — 스레드가 같은 파일을 두 번 만들지 않게
        case_env(mod)
    with ThreadPoolExecutor(max_workers=_selftest_workers()) as pool:
        rows += pool.map(run_case, cases)
    fails = [name for name, status, _ in rows if status == "FAIL"]
    skips = sum(1 for _, status, _ in rows if status == "SKIP")
    for name, status, detail in rows:
        print(f"{status:4} {name}" + (f"  ({detail})" if status == "SKIP" else ""))
        if status == "FAIL":
            print("     " + detail.replace("\n", "\n     "))
    print(
        f"\n{len(rows) - len(fails) - skips}/{len(rows) - skips} 통과"
        + (f" · SKIP {skips}" if skips else "")
        + (f" · FAIL {len(fails)}: {', '.join(fails)}" if fails else "")
    )
    if fails:
        raise SystemExit(1)


def _default_procs():
    """--procs 기본 — PIPE_PROCS(설정 객체, auto·빈 값 = None) 글자로, 없으면 "auto"(받는 쪽 resolve_procs가 같은 글자를 읽음)."""
    v = C.cfg().runtime.pipe_procs
    return C.render(v) if v is not None else "auto"


def _default_workers():
    """--workers 기본 — PIPE_WORKERS 글자로, 없으면 "4"."""
    v = C.given("PIPE_WORKERS")
    return C.render(v) if v is not None else "4"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    src = C.cfg().paths.doc_dir_prepared or "output/prepared"
    p = sub.add_parser("parse", help="파싱 모듈 1회(run_pipeline이 문서마다 부름): 파싱 → 채점 → 대표 결과 → 끝 표시 · 임베딩·DB 없음")
    p.add_argument("--src", default=src)
    p.add_argument(
        "--source",
        default=pc.cfg().extract.input_source or None,
        help="파싱할 원본 위치 — 폴더(같은 서버 샘플) · rdb:csv:<경로>(문서 위치 표 — run_pipeline이 만듦, AD44). "
        "주면 가져오기·중복 확인·방향 보정부터(11-01 s3://·rdb:*·rdb:<이름>·rdb:<표> 지움)",
    )
    p.add_argument(
        "--staged",
        action="store_true",
        help="extract(받기·중복·거르기)는 candidate_ready stage가 이 결과 폴더에 끝냄 — parse/_source/only.txt의 문서만 파싱(run_pipeline)",
    )
    p.add_argument("--source-limit", type=int, default=0, help="원본 몇 건만(Object Storage 시험 — 0 = 제한 없음)")
    p.add_argument("--engines", default="")
    p.add_argument("--procs", default=_default_procs())
    p.add_argument("--workers", default=_default_workers())
    p.add_argument(
        "--max-new",
        type=lambda x: int(x or 0),
        default=pc.cfg().extract.max_new,
        help="이번 실행에서 처음 파싱할 문서 수 상한(0 = 제한 없음)",
    )
    sub.add_parser("show-stack")
    p = sub.add_parser(
        "selftest", help="서버 반입 시험(tests/server — 이 이미지 폴더 + common)을 파일마다 — PASS/FAIL 표, 실패 있으면 종료 코드 1"
    )
    p.add_argument("--only", action="append", metavar="이름 조각", help="이름에 이 조각이 든 사례만(여러 번)")
    a = ap.parse_args(argv)
    if a.cmd != "selftest":  # 실행 환경 없으면 시작 거부(selftest는 시험이라 뺌)
        from common.config.settings import require_run_env

        require_run_env("pipeline.cli", sections=("pipeline",))  # 서버면 설정 검증 실패도 거부
    {
        "show-stack": show_stack,
        "selftest": selftest,
        "parse": parse_module,
    }[a.cmd](a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(한 번 실행 덮기, 서버 포함 · 호스트 run_pipeline.py 문서별 파싱이 결과 폴더 등을 넘김)
    utf8_stdout()
    subcommand = next((x for x in sys.argv[1:] if not x.startswith("-")), "")
    trace: contextlib.AbstractContextManager = contextlib.nullcontext()
    if (
        subcommand == "parse"
    ):  # 점검·설정 명령은 추적하지 않음(시작 0.5초 절약) · MCP 이미지는 cli.py·config.py만 포함 — 문서 처리 명령에서만 단계 코드를 import
        from pipeline.shared import runtrace

        trace = runtrace.run(subcommand, sys.argv[1:])
    with trace:  # run_id 생성·pipe_run, 하위 프로세스가 이어받음
        main()
