"""common.check.check_modules 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.check.check_modules --selftest`."""

import ast
import re
import sys
from pathlib import Path

import common.check.check_modules as M
from common.check.check_modules import (
    _area_of_import,
    _child_env_names,
    _cli_eval_violations,
    _comment_kinds,
    _env_funcs,
    _env_lines,
    _EnvFile,
    _module_scope_imports,
    _virtual_rel,
    check,
)


def selftest():
    """판정 변환 시험(저장소 파일 없이) — 점 이름 import(`import pipeline.eval.stages`)도 상위 패키지 영역으로 읽는지(VS4 R-5:
    S4의 단계 4 도구 옛 이름 표가 이 꼴을 옛 evaluation 영역으로 읽어 retrieval 도구의 top-level etl import를 놓쳤음 — S5에 그 표를
    경계 판정에서 뺌) · 옛 이름 data_retrieval·새 이름 mcp_server 둘 다 search · 함수 안 import는 top-level 판정 밖."""

    def areas(src):
        return {_area_of_import(m) for m in _module_scope_imports(ast.parse(src), None)} - {None}

    assert areas("import pipeline.eval.stages") == {"etl"}, areas("import pipeline.eval.stages")
    assert areas("from pipeline.eval import stages") == {"etl"}
    assert areas("import mcp_server.cli.mcp_eval") == {"search"}
    assert areas("import data_retrieval.retriever") == {"search"}
    assert areas("def f():\n    import pipeline.eval.stages") == set()
    two = ast.parse("import pipeline.eval.stages\nimport mcp_server.main")
    assert len(_cli_eval_violations("evaluation/stack_matrix.py", two, None)) == 1  # ⑨ etl+search top-level 동시
    print("[selftest] check_modules — 점 이름 import 영역 판정·옛/새 검색 이름·⑨ 동시 import 통과")
    src = (
        "import os\nx = os.environ.get('A')\n"  # 2 분류 없음
        "y = os.environ.get('HF_HOME')   # env 남김 — 라이브러리\n"  # 3
        "# env 남김 — 하위 프로세스\nz = dict(os.environ,\n         A='1')\n"  # 5 위 주석 줄
        "w = f(os.getenv('B'),\n      1)   # env 남김 — 내부 신호(여러 줄 문장 끝 주석)\n"  # 7
        "s = 'os.environ in text'   # 문자열은 대상 밖\n"
        "v = os.environ['C']   # env 남김 — 아무거나\n"
    )  # 10 모르는 분류
    got = _env_lines(src)
    assert got == [(2, None), (3, "라이브러리"), (5, "하위 프로세스"), (7, "내부 신호"), (10, None)], got
    print("[selftest] check_modules ⑩ — os.environ 토큰·분류 주석(같은 문장·바로 위 주석 줄)·문자열 제외 통과")
    src = (
        "import os as _o\nfrom os import environ as E, getenv\n"  # 2 import 줄도(별칭 이름)
        "a = _o.environ.get('A')\nb = E['B']\n"  # 3·4
        "c = getenv('C')   # env 남김 — 라이브러리\nd = x.environ\ne = y.E\n"  # 5 · 6·7 os가 아님
        "_o.putenv('P', '1')\n_o.unsetenv('P')   # env 남김 — 시험\n"
    )  # 8·9 putenv·unsetenv(VS7e3 R-4)
    got = _env_lines(src)
    assert got == [(2, None), (3, None), (4, None), (5, "라이브러리"), (8, None), (9, "시험")], got
    print(
        "[selftest] check_modules ⑩ — os 별칭(import os as _o)·from os import environ 이름(VS7e2 R-10)·os.putenv·unsetenv(VS7e3 R-4)도 잡음 통과"
    )
    _child_env_selftest()
    _planted_selftest()


def _child_env_selftest():
    """⑪(S7e3 — VS7e2 B-1 다섯 갈래 꼴) — 심은 자리는 잡히고, 덮기 파일·설정 밖 이름·설정 칸 사전·연결 사전·분류 주석은 통과."""
    names = frozenset({"PG_SCHEMA", "EDW_SUMMARY_LLM", "LLM_BASE_URL", "NO_PAID_CALLS", "LLM_FAKE", "PARSE_SKIPPED_LOG"})
    src = """import os
import os as _o
import subprocess
import subprocess as sp
from subprocess import run as srun
from os import environ as E
from common.config.settings import child_env as settings_env
from common.core.paths import child_env


def env_for(conf):
    return settings_env(None, CHUNK_SIZE="1")


def night(vlm):
    env = {**child_env(), "VLM_CONCURRENCY": vlm, "EDW_SUMMARY_LLM": "0"}  # 14 bad EDW_SUMMARY_LLM(설정 밖 이름 VLM_CONCURRENCY는 통과)
    env.pop("LLM_BASE_URL", None)                                          # 15 bad
    penv = {**env_for({}), "PG_SCHEMA": "idx"}                              # 16 bad(저장소 함수 env_for — 별칭 settings_env 사슬)
    e2 = child_env({"PYTHONUTF8": "1", "NO_PAID_CALLS": "1"})               # 17 bad(위치 인자 dict)
    for k in ("LLM_BASE_URL", "VLM_BASE_URL", "OTHER"):
        e2.pop(k, None)                                                    # 19 bad LLM_BASE_URL(설정 밖 이름 VLM_BASE_URL은 통과)
    e2["PARSE_SKIPPED_LOG"] = "x"                                          # 20 bad
    subprocess.run(["x"], env=dict(os.environ, LLM_FAKE="1"))              # 21 bad
    _o.environ["PG_SCHEMA"] = "x"                                          # 22 bad(os 별칭)
    E.update(PG_SCHEMA="y")                                                # 23 bad(from os import environ)
    del env["LLM_FAKE"]                                                    # 24 bad


def param(env):
    env["LLM_FAKE"] = "1"                                                  # 28 bad(매개변수 — subprocess env=로 넘김)
    subprocess.run(["x"], env=env)


def ok(c, Names, MM):
    env = settings_env(child_env(), VLM_CONCURRENCY="2", LLM_BASE_URL=None)
    env["VLM_CONCURRENCY"] = "3"
    env["PYTHONUTF8"] = "1"
    conn = {"PG_SCHEMA": "ai"}
    os.environ["PG_SCHEMA"] = "t"   # env 남김 — 시험
    names = Names()
    names["LLM_FAKE"] = "1"
    names = MM.child_env(names)
    env = c.load()
    env["LLM_FAKE"] = "1"
    env = child_env(env)
    subprocess.run(["x"], env=env)
    return conn


def more(c):
    env = dict(os.environ)
    env["PG_SCHEMA"], env["LLM_FAKE"] = c, "1"                             # bad 튜플 대상 PG_SCHEMA·LLM_FAKE
    env |= {"NO_PAID_CALLS": "1"}                                          # bad |=
    e3: dict = {**os.environ, "EDW_SUMMARY_LLM": "0"}                      # bad 형 주석 대입
    sp.run(["x"], env=e3)
    p = {"LLM_BASE_URL": "x"}                                              # bad subprocess 별칭 env=로 넘김
    sp.call(["x"], env=p)
    q = {"PARSE_SKIPPED_LOG": "x"}                                         # bad from subprocess import run
    srun(["x"], env=q)


def blind(base, key, conn):
    run = lambda: subprocess.run(["x"], env={**os.environ, "PG_SCHEMA": "a"})   # bad 람다 몸통(VS7e3 R-4)
    _C[key] = child_env()
    e4 = dict(_C[key])
    e4["LLM_FAKE"] = "1"                                                   # bad 캐시 감싸개 사전
    e5 = {**base, "NO_PAID_CALLS": "1"}                                    # bad 매개변수 base
    e6 = child_env(extra={"EDW_SUMMARY_LLM": "0"})                         # bad child_env(extra=…)
    e7 = {**os.environ, **{"PARSE_SKIPPED_LOG": "x"}}                      # bad 겹친 사전
    os.putenv("LLM_BASE_URL", "x")                                         # bad putenv
    c2 = dict(conn)
    c2["PG_SCHEMA"] = "struct"
    _D[key] = {"PG_SCHEMA": "ai"}
    d2 = dict(_D[key])
    d2["LLM_FAKE"] = "1"
    return run, e5, e6, e7, c2, d2


def cached(k):
    if k not in _J:
        _J[k] = settings_env(None, CHUNK_SIZE="1")
    return dict(_J[k])


def use_cached():
    e8 = cached("a")
    e8["LLM_FAKE"] = "1"                                                   # bad 캐시 감싸개 함수
    return e8
"""
    tree = ast.parse(src)
    ef = _EnvFile(tree)
    _env_funcs([ef])
    got = {(ln, n) for ln, n, _ in _child_env_names(ef, lambda: _comment_kinds(src), names)}
    want = {
        (14, "EDW_SUMMARY_LLM"),
        (15, "LLM_BASE_URL"),
        (16, "PG_SCHEMA"),
        (17, "NO_PAID_CALLS"),
        (19, "LLM_BASE_URL"),
        (20, "PARSE_SKIPPED_LOG"),
        (21, "LLM_FAKE"),
        (22, "PG_SCHEMA"),
        (23, "PG_SCHEMA"),
        (24, "LLM_FAKE"),
        (28, "LLM_FAKE"),
    }
    want = {(ln + 2, n) for ln, n in want}  # 위 import 두 줄(subprocess 별칭) 만큼
    lines = src.splitlines()
    for i, line in enumerate(lines, 1):  # more() — "# bad" 줄의 이름(글자 상수)
        if "# bad" in line and i > 40:
            want |= {(i, n) for n in re.findall(r'"([A-Z_]+)"', line.split("#")[0]) if n in names}
    assert got == want, (sorted(got - want), sorted(want - got))
    print(
        f"[selftest] check_modules ⑪ — 자식 env의 설정 이름 심은 {len(want)}곳 모두 잡힘(dict·pop·for 상수·위치 인자·dict(…, X=)·os 별칭·"
        "from os import environ·del·매개변수·저장소 env 함수 사슬·튜플 대상·|=·형 주석 대입·subprocess 별칭·람다 몸통·캐시 감싸개·"
        "매개변수 {**base}·child_env(extra=)·겹친 **{…}·os.putenv — VS7e3 R-4) · 덮기 파일·설정 밖 이름·설정 칸 사전(Names)·연결 사전·분류 주석 통과"
    )


def _planted_selftest():
    """S6a(VS5 R-5) — 임시 폴더에 위반을 심은 가짜 트리로 check() 전체를 돌려 잡히는지·허용 사례가 통과하는지(저장소 파일 안 건드림)."""
    import tempfile

    bad_cases = {  # 경로 → 내용(모두 위반이어야 함)
        "pipeline/v_ask.py": "import ask\n",  # etl → 검색 도구 맨 이름(S5 새 도구)
        "common/v_ask.py": "from ask import main\n",
        "pipeline/v_e2e_flat.py": "import stack_matrix\n",  # etl → PC 평가 도구 맨 이름
        "pipeline/v_e2e.py": "from validation.e2e import graph_llm\n",  # etl → validation 정적 import
        "pipeline/v_tests.py": "from tests.server.common import appcheck\n",  # S9 — 앱 → tests/ import
        "common/v_tests.py": "import tests.runner\n",
        "mcp_server/v_e2e.py": "import validation.e2e.stack_matrix\n",
        "common/v_e2e.py": "import validation.e2e.model_matrix\n",
        "pipeline/v_old.py": "import common_tools\n",  # 옛 공용 패키지 이름
        "mcp_server/v_old.py": "from common_tools.evaluation import stack_matrix\n",
        "validation/e2e/v_old.py": "import common_tools.cli.assets\n",
        "mcp_server/v_etl.py": "import pipeline.eval.stages\n",  # 앱 사이(기존 규칙)
        "validation/e2e/v_both.py": "import pipeline.eval.stages\nimport mcp_server.main\n",  # ⑨
    }
    ok_cases = {  # 위반이 아니어야 함
        "mcp_server/cli/ok_ask.py": "import ask\n",  # 같은 앱 안 맨 이름
        "pipeline/eval/ok_stages.py": "import stages\n",
        "validation/e2e/ok_etl.py": "import pipeline.eval.stages\n\ndef f():\n    import mcp_server.main\n",
        "pipeline/eval/ok_dyn.py": "import importlib\nimportlib.import_module('validation.e2e.graph_llm')\n",  # 문자열 — 정적 점검 밖(T-02)
        "validation/e2e/triple_extract/agent.py": "from google.adk.agents import LlmAgent\n",  # ⑦ 지시서 agent.py
        "common/core/ok_fp.py": "OLD = b'common_tools.text'\n",  # 바이트 글자(지문 대응표)는 import 아님
    }
    saved = M.ROOT
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for rel, src in {**bad_cases, **ok_cases}.items():
            (t / rel).parent.mkdir(parents=True, exist_ok=True)
            (t / rel).write_text(src, encoding="utf-8")
        (t / "validation" / "e2e" / "stack_matrix.py").write_text("", encoding="utf-8")  # flat 표(validation/e2e glob)
        (t / "validation" / "e2e" / "model_matrix.py").write_text("", encoding="utf-8")
        M.ROOT = t
        try:
            errs = check()
            virt = {rel: _virtual_rel(t / rel) for rel in {**bad_cases, **ok_cases}}  # check()와 같은 변환
        finally:
            M.ROOT = saved
    hit = {e.split(":", 1)[0] for e in errs}
    missed = [r for r in bad_cases if virt[r] not in hit]
    wrong = [r for r in ok_cases if virt[r] in hit]
    assert not missed and not wrong, (missed, wrong, errs)
    print(
        f"[selftest] check_modules — 심은 위반 {len(bad_cases)}건 모두 잡힘 · 허용 {len(ok_cases)}건 통과(맨 이름 ask·"
        "validation/e2e·옛 common_tools 이름)"
    )


def test_main():  # 옛 `python -m common.check.check_modules --selftest`: selftest() 뒤 저장소 경계 점검 check()까지(옛 __main__ 그대로)
    selftest()
    errs = check()
    print("모듈 경계 통과" if not errs else "모듈 경계 위반:\n- " + "\n- ".join(errs))
    sys.exit(1 if errs else 0)
