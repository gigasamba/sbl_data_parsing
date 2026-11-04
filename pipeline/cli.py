#!/usr/bin/env python3
"""파이프라인 진입점 — 두 단계를 나눠 부른다(요청 문장 → 명령 대응표는 AGENTS.md "요청 → 명령").

(단계 1 비교 명령 compare-parse·compare-all은 11-01에 지움 — PC 평가 도구 삭제, PRD e2-10)
단계 2 · 고정 스택(정해진 기술로 실제 파이프라인 + 기본 테스트)
  show-stack  지금 엔진 구성(파일 — 서버·PC 같음, 바꾸기 = 파일 고쳐 오버레이 패치 · 사용자 11-01 —
                  docs/architecture/pipeline_stack.md)
  parse           파싱 모듈 1회(run_docs가 문서마다 부름) — 끝 표시 _rep/_DONE.json
  (night·run-stack·structure·load는 11-01에 지움 — 서버 입구는 run_docs 하나, 구조화·적재는 run_docs가 모듈을 직접 부름)
  (ask — 검색 명령은 S5(10-26, T-15)에 python -m mcp_server.cli.ask로 옮김: 파이프라인 CLI가 검색 코드를 import하지 않게)
산출 위치: output/parse(파싱) · output/parse/_rep(대표) · output/edw/bundle(구조화) · output/report(보고서) · output/stack_test.md
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서
from common.core.console import utf8_stdout

# isort: split
import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import settings as C  # common 칸(S7c — 설정 객체 · cfg()·given()·render())
from common.core.paths import APP_ROOT, DEPLOY_ROOT, PKG_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체 · cfg()·given())

ROOT = PKG_ROOT  # common/(S6a — 옛 common_tools/와 같은 깊이) — 하위 프로세스 cwd·저장소 문서 찾기용(ROOT.parent = deploy/)
OUT = Path(
    pc.cfg().paths.out_root or (APP_ROOT / "output")
)  # S7c — 설정 객체(import 때 한 번) · D2 — 격리 빌드(stack_matrix.py sources)가 데이터셋마다 다른 out을 쓰게
PY = sys.executable
_STACK: dict = {}


def _stack():
    """엔진 구성(사전) — 프로세스마다 한 번(pipeline/stackcfg.py: 파일 → 이미지에 없는 엔진 거부 — 서버·PC 같은 파일, 사용자 11-01).
    파일을 못 읽거나 없는 엔진이면 종료 2."""
    if "v" not in _STACK:
        from pipeline import stackcfg

        stackcfg.resolve()
        _STACK["v"] = pc.stack()
    return _STACK["v"]


def _traced(module, call):
    """하위 프로세스 1개 = proc.run span(op-01) — 자식이 이어받는 parent span이 되고, 메모리·CPU 문 대기가 이 span에 쌓임.
    call()은 종료 코드(마감으로 끝냈으면 None)를 돌려준다."""
    from common.core.span import safe, span

    with span("proc.run", "run", module=module) as sp:
        rc = call()
        sp.add(rc=-1 if rc is None else rc)
        if rc is None:
            sp.result("timeout", "timeout", safe("마감 시각 도달"))
        elif rc:
            sp.result("fail", None, safe(f"종료 코드 {rc}"))
        return rc


# ── 마감 시각(parse --deadline) ─────────
def _until(deadline):
    """'HH:MM'(오늘, 이미 지났으면 내일) → 남은 초."""
    import datetime as dt

    now = dt.datetime.now()
    h, m = map(int, deadline.split(":"))
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= now:
        end += dt.timedelta(days=1)
    return (end - now).total_seconds()


def _run_until(args, env, sec):
    """마감까지만 실행 — 넘으면 프로세스 묶음(--procs 자식 포함)을 끝냄. 다음 밤은 문서 대장에 파싱 성공 행이 없는 문서를 다시 고른다(pl-32 — 마감에 걸린 밤의 문서는 PR 4 전까지 반복될 수 있음).
    args[0] = 모듈 점 표기(예: pipeline.extract.run_all)."""
    cmd = [PY, "-m", str(args[0]), *map(str, args[1:])]
    print("$ " + " ".join(cmd), flush=True)
    from common.core import resources as PR  # 프로세스 묶음(OS 분기 한 곳)
    from common.core import resources as RS

    def call():
        # cwd=APP_ROOT(런타임 루트) — ROOT(코드 루트)로 하면 --src 상대경로가 거기 기준으로 풀려 못 찾음(FS v4 회귀)
        p = RS.gated_popen(cmd, cwd=APP_ROOT, env=env, **PR.group_kw())
        try:
            return p.wait(timeout=max(1, sec))
        except subprocess.TimeoutExpired:
            PR.kill_group(p)
            return None

    return _traced(str(args[0]), call)


# ── 단계 2 ───────────────────────────────────────────────────
def _engines_of(st):
    """parse 엔진(정렬) — stackcfg.engines_of 하나로(VS8b R-8)."""
    from pipeline.stackcfg import engines_of

    return engines_of(st)


def show_stack(a=None):
    """지금 엔진 구성(파일 — 서버·PC 같음). mcp-server 이미지에서도 됨(등록부 안 씀)."""
    from common.store.db import cfgfile

    cur = cfgfile.active("stack", refresh=True)
    st = cur.body
    print(f"스택 {cur.name} ({st.get('source', '')}) · {cur.label()}")
    print("| 형식 | 파싱 엔진(우선순위) |\n|---|---|")
    for f, es in sorted(st["parse"].items()):
        print(f"| {f} | {' → '.join(es)} |")
    print(f"청킹 {st['chunk']} · 임베딩 {st['embed']} · 그래프 {st['graph']} · 검색 {st['retrieve']} · 상위 k {st['k']}")


# ── 파싱 모듈(run_docs가 문서마다 부름 — 서버 입구는 run_docs 하나, 사용자 10-31) ──────────
# 11-01: 옛 배치 입구 night·run-stack·structure·load 모듈과 그 끝 표시 확인(need)은 지움 — 구조화·적재는 run_docs가 build_bundle·pgvector_load를 직접 부름.
# 파싱 끝 표시(_rep/_DONE.json)는 남김.
from common import CONTRACT, FINGERPRINT  # noqa: E402 — 인계 형식 버전 · common 코드 지문(이미지 버전 어긋남 확인)

MARK = {
    "parse": OUT / "parse" / "_rep" / "_DONE.json",
}


def read_mark(name):
    f = MARK[name]
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def write_mark(name, **kw):
    m = {
        "module": name,
        "contract": CONTRACT,
        "common": FINGERPRINT,
        "run_id": time.strftime("%Y%m%d-%H%M%S"),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **kw,
    }
    MARK[name].parent.mkdir(parents=True, exist_ok=True)
    MARK[name].write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{name}] 끝 표시 → {MARK[name]} (run_id {m['run_id']})", flush=True)


def _left(a):
    return _until(a.deadline) if getattr(a, "deadline", None) else 10**7


def _unparsed(names):
    """C10(pl-12 · pl-32, 사용자 10-31) — 새 문서 후보 = EDW FileStorageMap ∖ ParsingMeta. FileStorageMap 쪽은 이미 받은 이름 목록
    (`--source rdb:`가 FileStorageMap을 읽어 만든 것 — 이름 ↔ 원본 키 s3_key 대응은 source.py가 쓴 manifest.jsonl), ParsingMeta 쪽은
    여기서 **EDW를 한 번 읽는다**(파싱 입구의 EDW 읽기 — 읽기 계정, PC는 EDW 대역 sqlite `RDB_SQLITE`): parse_status가 ok·partial인
    행의 source_key 집합(`done_source_keys`). 통째 실패는 ParsingMeta에 안 쓰므로(C3) 실패한 문서는 행이 없어 다음 실행이 다시 고른다.
    키 = manifest의 "key"(없으면 이름 그대로 — publish의 source_key와 같은 규칙, parsing_meta.plan).
    순서: 받은 이름 순서 그대로(문서 대장이 없어져 시도 이력이 없음 — 실패 문서를 뒤로 미루지 않는다).
    EDW를 못 읽으면: 서버(run_mode prod 또는 RUN_ENV dev·prd·모르는 값)는 종료 4(전체 재파싱 안 함), PC는 받은 목록 그대로 + 로그 한 줄."""
    from common.core.contract import jl
    from common.store import parsing_meta_db as PMDB

    try:
        db = PMDB.make_db("read")
        try:
            done = db.done_source_keys()
        finally:
            db.close()
    except (Exception, SystemExit) as ex:  # make_db는 접속 정보가 없으면 SystemExit
        if C.cfg().store.run_mode == "prod" or C.guard_run_env() not in (None, "local"):  # pl-12 — 서버(dev·prd·모르는 값)
            print(
                f"[parse] EDW ParsingMeta를 읽지 못함 — 멈춤(종료 4, 전체 재파싱 안 함): {type(ex).__name__}", file=sys.stderr, flush=True
            )
            raise SystemExit(4) from None
        print(f"[parse] EDW ParsingMeta 못 읽음({type(ex).__name__}) — 이력 없이 받은 목록 그대로 처리", flush=True)
        return list(names)
    man = OUT / "parse" / "_source" / "manifest.jsonl"
    key_of = {r["file_name"]: r.get("key") for r in jl(man)} if man.exists() else {}
    return [n for n in names if (key_of.get(n) or n) not in done]


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
    """파싱 모듈: (--source면) 가져오기·시험 표본 → 중복 확인 → 방향 보정 → 파싱 → 채점 → 대표 결과 → 끝 표시 → (s3) 원본 정리.
    임베딩·DB 연결 없음 — 수집 서버에 이것만 보낼 수 있음. --source 없으면 --src(이미 준비된 폴더)를 그대로."""
    from common.core.paths import child_env

    _tstep("t_start")
    run_id = os.environ.get("PARSE_RUN_ID") or time.strftime(
        "%Y%m%d-%H%M%S"
    )  # env 남김 — 내부 신호(5-3 H) · SI23 — run_all·_DONE.json이 같은 id를 쓰게(run_board가 이번 실행만 거르는 기준)
    os.environ["PARSE_RUN_ID"] = (
        run_id  # env 남김 — 하위 프로세스·엔진에 넘김 · 이후 모든 하위 호출(dedup·prepare·run_all)이 os.environ 상속으로 받음
    )
    st = _stack()
    from pipeline.shared import runtrace

    runtrace.info(stack=st.get("name"), workers=int(a.workers) if str(a.workers).isdigit() else None)
    engines = a.engines or ",".join(_engines_of(st))
    # OP26 문서 단위 병렬(parse_parallel)은 10-30 지움(pl-35) · 스트리밍 파싱은 op-08에 지움
    lim, src_info = [], None
    if a.source:  # 문서 위치: 같은 서버 폴더 → Object Storage 몇 건 → 전체(사용자 10-02)
        from pipeline.extract import source as SRC

        local, names, state = SRC.resolve(a.source, OUT, a.source_limit)
        src_info = (state, local)
        _tstep("t_resolve")
        if not SRC.is_remote(a.source):
            C.put(
                DOC_DIR=str(Path(local).resolve())
            )  # S7e2 — 덮기 파일 + 인계 키라 env에도(contract.py) · 원본 위치 주소 = 이 폴더의 file:///
        sel = OUT / "parse" / "_source" / "selected.txt"
        sel.write_text("\n".join(names) + "\n", encoding="utf-8")
        # fp-perf B7 — 문서 1건(run_docs 문서별 흐름)은 자식 프로세스 없이 같은 함수로(결과 파일 같음)
        if sum(1 for f in Path(local).iterdir() if f.is_file() and f.name != ".gitkeep") <= 1:
            from common.core.runlog import session
            from pipeline.extract import dedup

            try:
                with session("dedup"):  # 자식이 남기던 실행 기록 그대로
                    dedup.run_folder(local, OUT / "dedup")
                rc = 0
            except Exception as e:  # 자식 실패와 같게 종료 코드로(아래 SystemExit)
                print(f"[dedup] 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                rc = 1
        else:
            rc = _run_until(["pipeline.extract.dedup", "--src", local, "--out", OUT / "dedup"], child_env(), _left(a) - 120)
        _tstep("t_dedup")
        if rc != 0:
            raise SystemExit(75 if rc is None else rc)
        keep = set((OUT / "dedup" / "keep.txt").read_text(encoding="utf-8").splitlines())
        keep &= set(_unparsed(names))  # C10 — ParsingMeta에 성공 행이 있는 문서는 다시 파싱 안 함
        only = OUT / "parse" / "_source" / "only.txt"
        only.write_text("\n".join(n for n in names if n in keep) + "\n", encoding="utf-8")
        rc = _run_until(["pipeline.extract.prepare", "--src", local, "--out", a.src, "--only", only], child_env(), _left(a) - 120)
        _tstep("t_prepare")
        if rc != 0:
            raise SystemExit(75 if rc is None else rc)
        lim = ["--docs-from", only]
    from common.core import resources as RS

    vlm_conc = RS.vlm_page_concurrency(a.workers, a.vlm_concurrency)  # 문서 동시 수 × 쪽 동시 수가 VLM_MAX_CONCURRENCY를 넘지 않게
    from common.core.paths import child_env

    env = C.child_env(child_env(), VLM_CONCURRENCY=str(vlm_conc), LLM_BASE_URL=None)  # 파싱 모듈은 LLM을 부르지 않음 — 덮기 파일(S7e3 B-1)
    if a.max_new:  # 밤당 새 문서 상한(GH1-10: test 모드도 적용) — 밀린 문서가 많아도 매일 밤 대표 결과·구조화·적재까지 끝나게
        names = sorted(p.name for p in Path(a.src).iterdir() if p.is_file())
        new = _unparsed(names)  # C10 — ParsingMeta에 성공 행 없는 문서(새 + 실패)만 · 앞 실행 runs.jsonl은 안 봄
        pick = new[: a.max_new]
        f = OUT / "parse" / "_batch_docs.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        if lim:  # --source 선택과 겹치는 것만
            sel_names = set(Path(lim[1]).read_text(encoding="utf-8").splitlines())
            pick = [n for n in pick if n in sel_names]
        f.write_text("\n".join(pick) + "\n", encoding="utf-8")
        lim = ["--docs-from", f]
        print(f"[parse] 새·실패 문서 {min(len(new), a.max_new)}/{len(new)}개(PARSE_MAX_NEW {a.max_new}) — 나머지는 다음 실행", flush=True)
    args = [
        "pipeline.extract.run_all",
        "--src",
        a.src,
        "--out",
        OUT / "parse",
        "--procs",
        a.procs,
        "--workers",
        a.workers,
        "--engines",
        engines,
        *lim,
    ]
    rc = _run_until(args, env, _left(a) - 120)
    if rc is None:
        raise SystemExit(75)  # 마감 — 끝 표시 안 바꿈, 다음 실행이 이어 감
    _tstep("t_parse")
    if not (OUT / "parse" / "runs.jsonl").exists():  # F1(11-03 PC 시험) — runs.jsonl 없음: 채점·대표 결과로 넘어가 죽지 않게
        if rc != 0:  # run_all이 죽어 못 씀 — 성공으로 덮지 않는다(리뷰)
            print(f"[parse] 파싱 실패 — run_all 종료 {rc}, runs.jsonl 없음", file=sys.stderr, flush=True)
            raise SystemExit(rc)
        print("[parse] 이번 실행 0건 — 파싱한 문서 없음(runs.jsonl 없음) · 채점·대표 결과·끝 표시 건너뜀", flush=True)
        return
    for args in (
        ["pipeline.transform.represent.parse_qa", "--src", a.src, "--parse", OUT / "parse", "--truth", OUT / "corpus" / "truth.json"],
        ["pipeline.transform.represent.represent", "--src", a.src, "--parse-dir", OUT / "parse"],
    ):
        rc = _run_until(args, env, _left(a) - 60)
        _tstep("t_" + args[0].rsplit(".", 1)[-1])  # 2026-10-22 — qa·represent 분리 계측(docflow 기타 분해)
        if rc != 0:
            raise SystemExit(75 if rc is None else rc)
    import hashlib

    print(f"[docflow-step] {_tdone()}", flush=True)  # 2026-10-22 — resolve~represent까지 docflow 기타 분해 로그
    idx = json.loads((OUT / "parse" / "_rep" / "index.json").read_text(encoding="utf-8"))["docs"]
    ok = sum(1 for r in idx if r.get("engine"))
    runtrace.docs(total=len(idx), ok=ok, fail=len(idx) - ok)  # 재사용 수는 없음 — 실행마다 새로 파싱(pl-32)
    core = [{k: v for k, v in r.items() if k != "tried"} for r in idx]  # 시도 기록(시각)은 빼고 대표 결과만 비교
    content = []  # GH1-05 — core는 chars·facts_added(길이·개수)만 있어 길이·개수가 같은 내용 교체를 못 잡음 → 본문·facts 자체의 sha256
    for r in idx:
        if not r.get("engine"):
            continue
        rep = json.loads((OUT / "parse" / "_rep" / f"{r['doc']}.json").read_text(encoding="utf-8"))
        content.append(
            {
                "doc": r["doc"],
                "text_sha": hashlib.sha256((rep.get("text") or "").encode("utf-8")).hexdigest(),
                "facts_sha": hashlib.sha256(
                    json.dumps(rep.get("facts") or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
        )
    digest = hashlib.sha256(json.dumps({"core": core, "content": content}, sort_keys=True).encode()).hexdigest()[:16]
    old = read_mark("parse") or {}
    if old.get("digest") == digest and old.get("contract") == CONTRACT:
        print(f"[parse] 대표 결과 변화 없음 — 끝 표시 그대로(run_id {old['run_id']}), 구조화는 건너뛰게 됨", flush=True)
        return
    write_mark(
        "parse",
        src=str(a.src),
        source=str(a.source or a.src),
        engines=engines.split(","),
        docs=len(idx),
        digest=digest,
        rep_ok=sum(1 for r in idx if r.get("engine")),
        run_id=run_id,
    )
    if src_info:
        from pipeline.extract import source as SRC

        if SRC.is_remote(a.source):
            SRC.finish(src_info[0], src_info[1], OUT / "parse" / "_rep" / "index.json")


# ── 운영자 자기 점검(selftest) ──────────────────────────────────
# S9(D-018, 사용자 10-28) — 자기 점검은 모두 저장소 루트 tests/로 옮겼다. 이미지 명령 `selftest`는 서버 반입 시험 tests/server/<앱>/test_*.py를
# 파일마다 자식 프로세스(python -m tests.runner <시험 모듈>)로 돌려 PASS/FAIL 표를 낸다 — 반입 판정은 deploy/release/selftest_gate.sh(알려진 FAIL은
# known_fail.txt, 사례 이름 = 시험 모듈 이름). 폴더가 곧 이미지: common = 두 이미지 · pipeline = data-pipeline · mcp = mcp-server(RAG_MODULE).
# PC 일반 시험(tests/general — PC 전용·느린 것·PG·Docker)은 pytest로만(`python -m pytest tests/` — tests/conftest.py가 같은 자식 프로세스·같은 env로).
# 옛 사례 이름(모듈 이름) → 새 시험 모듈 대응표는 output/orca/S9-impl.md.
TESTS_ROOT = DEPLOY_ROOT / "tests"  # 저장소 루트 tests/ · 이미지 /app/deploy/tests(PYTHONPATH와 같은 뿌리)
IMAGE_DIRS = {"common": None, "pipeline": "pipeline", "mcp": "mcp"}  # tests/server/<폴더> → 도는 이미지(None = 둘 다)
_FAKE_LLM_CASES = frozenset({"tests.server.mcp.test_mcp_main"})  # LLM_FAKE를 켜는 사례(질문 분해 — 옛 mcp_server.main 사례)
# PC에서 개발자 루트 settings.yaml(실 PG)을 그대로 읽어야 판정되는 사례 — 그 밖 PC 사례는 시험 전용 바탕 설정(case_env, 10-29)
# (유일한 사례 test_pub_registry는 C10 10-31에 문서 대장과 함께 지움 — 지금 비어 있음)
_PC_SETTINGS_CASES: frozenset[str] = frozenset()


def server_cases():
    """[(시험 모듈, 이미지|None)] — tests/server/<폴더>/test_*.py(이름순). 모르는 폴더는 사례로 넣지 않고 FAIL 사례로(오타·새 앱을 놓치지 않게)."""
    out = []
    for p in sorted((TESTS_ROOT / "server").glob("*/test_*.py")):
        out.append((f"tests.server.{p.parent.name}.{p.stem}", IMAGE_DIRS.get(p.parent.name, "?")))
    return out


_CASE_ENVS: dict = {}


def case_env(mod):
    """사례 자식 env(새 dict) — 모델 주소·예산 비움(외부 호출 없음)·LLM_FAKE(_FAKE_LLM_CASES만)는 덮기 파일로(S7e3 B-1 — env dict의 설정 이름은 자식이
    안 읽음). 두 벌만 만든다(임시 파일 수 — R-4). PC pytest(tests/conftest.py)도 이것을 쓴다 — 이미지 selftest와 같은 env."""
    from common.core.paths import child_env

    fake = mod in _FAKE_LLM_CASES
    own = not C.IN_IMAGE and mod not in _PC_SETTINGS_CASES  # PC 시험은 시험 전용 바탕 설정(아래 _case_settings)
    if (fake, own) not in _CASE_ENVS:
        import tempfile

        blank: dict[str, str | None] = {
            **dict.fromkeys(("LLM_BASE_URL", "VLM_BASE_URL", "EMBED_BASE_URL", "LLM_BUDGET_USD")),
            **dict.fromkeys(
                ("LLM_ALLOW_EXTERNAL", "VLM_ALLOW_EXTERNAL", "EMBED_ALLOW_EXTERNAL"), "0"
            ),  # 외부 전송 늘 끔(옛 NO_PAID_CALLS 대신 — 11-03)
            # 하루 장부(11-03)를 시험마다 따로 — 개발자의 output/_llm_spend 장부에 섞이지 않게
            "LLM_SPEND_FILE": str(Path(tempfile.mkdtemp(prefix="selftest_spend_")) / "spend.txt"),
        }
        base = child_env({"PYTHONUTF8": "1"})
        if own:  # PC — 개발자 루트 settings.yaml(실 PG·모델 키) 대신 시험 전용 최소 설정 위에 덮음(10-29 — 시험 격리)
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
    들어가므로(S4·S7c1) 단계 코드(pipeline.extract)로, mcp_server는 pipeline 이미지에 설정 모델 config.py만 들어가므로(S7e1) 검색 코드(mcp_server.services)로
    본다(VS7e1 R-8). 하위 모듈 이름 하나가 없는 것(오타·빠진 COPY)은 SKIP이 아니라 FAIL로 남긴다."""
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
    """--procs 기본 — PIPE_PROCS(설정 객체, auto·빈 값 = None) 글자로, 없으면 "auto"(S7c — 받는 쪽 resolve_procs가 같은 글자를 읽음)."""
    v = C.cfg().runtime.pipe_procs
    return C.render(v) if v is not None else "auto"


def _default_workers():
    """--workers 기본 — NIGHT_WORKERS → PIPE_WORKERS 중 준 값(설정 객체) 글자로, 없으면 "4"(S7c — 옛 `get(N) or get(P) or "4"`)."""
    v = pc.given("NIGHT_WORKERS")
    if v is None:
        v = C.given("PIPE_WORKERS")
    return C.render(v) if v is not None else "4"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    src = C.cfg().paths.doc_dir_prepared or "output/prepared"
    p = sub.add_parser("parse", help="파싱 모듈 1회(run_docs가 문서마다 부름): 파싱 → 채점 → 대표 결과 → 끝 표시 · 임베딩·DB 없음")
    p.add_argument("--src", default=src)
    p.add_argument(
        "--force", action="store_true", help=argparse.SUPPRESS
    )  # 11-01 — 옛 호출 호환으로 받기만(끝 표시 확인 need()는 structure·load와 함께 지움)
    p.add_argument("--deadline", default=None, help="HH:MM — 넘으면 멈춤(종료 코드 75, 다음 실행이 이어 감). 새벽 배치용")
    p.add_argument(
        "--source",
        default=pc.cfg().extract.input_source or None,
        help="파싱할 원본 위치 — 폴더(같은 서버 샘플) · rdb:csv:<경로>(문서 위치 표 — run_docs가 만듦, AD44). "
        "주면 가져오기·중복 확인·방향 보정부터(11-01 s3://·rdb:*·rdb:<이름>·rdb:<표> 지움)",
    )
    p.add_argument("--source-limit", type=int, default=pc.cfg().extract.source_limit, help="원본 몇 건만(Object Storage 시험)")
    p.add_argument("--engines", default="")
    p.add_argument("--procs", default=_default_procs())
    p.add_argument("--workers", default=_default_workers())
    p.add_argument("--vlm-concurrency", type=int, default=pc.cfg().night.vlm_concurrency)
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
    if a.cmd != "selftest":  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(selftest는 시험이라 뺌)
        from common.config.settings import require_run_env

        require_run_env("pipeline.cli", sections=("pipeline",))  # 서버면 설정 검증 실패도 거부(S7e2 U-1)
    {
        "show-stack": show_stack,
        "selftest": selftest,
        "parse": parse_module,
    }[a.cmd](a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 한 번 실행 덮기, 서버 포함 · 호스트 run_docs.py 문서별 파싱이 결과 폴더 등을 넘김)
    utf8_stdout()
    from common.core.runlog import session

    subcommand = next((x for x in sys.argv[1:] if not x.startswith("-")), "")
    trace: contextlib.AbstractContextManager = contextlib.nullcontext()
    if (
        subcommand == "parse"
    ):  # 점검·설정 명령은 추적하지 않음(시작 0.5초 절약) · MCP 이미지는 cli.py·config.py만 포함 — 문서 처리 명령에서만 단계 코드를 import
        from pipeline.shared import runtrace

        trace = runtrace.run(subcommand, sys.argv[1:])
    with (
        session("pipeline"),
        trace,
    ):  # op-01 — run_id 생성·pipe_run, 하위 프로세스가 이어받음
        main()
