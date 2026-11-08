"""common.check.check_modules 자기 점검."""

import ast
import sys
from pathlib import Path

import common.check.check_modules as M
from common.check.check_modules import (
    _area_of_import,
    _cli_eval_violations,
    _module_scope_imports,
    _virtual_rel,
    check,
)


def selftest():
    """판정 변환 시험(저장소 파일 없이) — 점 이름 import(`import pipeline.eval.stages`)도 상위 패키지 영역으로 읽는지
    (하위 모듈 이름으로 영역을 정하면 top-level import를 놓친다) · 옛 이름 data_retrieval·새 이름 mcp_server 둘 다 search · 함수 안 import는 top-level 판정 밖."""

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
    _env_selftest()
    _planted_selftest()


ENV_NAMES = frozenset({"PG_SCHEMA", "LLM_FAKE", "LLM_BASE_URL"})
ENV_CASES = [  # (코드 조각, 위반 꼴 ⑩·⑪ — 빈 값은 통과)
    ("import os\ny = os.environ.get('HF_HOME')  # env 남김 — 라이브러리\n", ""),
    ("import os\n# env 남김 — 하위 프로세스\nz = dict(os.environ,\n         A='1')\n", ""),  # 바로 위 주석 줄
    ("import os\nw = f(os.getenv('B'),\n      1)  # env 남김 — 내부 신호\n", ""),  # 여러 줄 문장 끝 주석
    ("import os\nx = os.environ.get('A')\n", "⑩"),  # 분류 주석 없음
    ("import os as _os\nx = _os.getenv('A')\n", "⑩"),
    ("import os as o\nx = o.environ.get('A')\n", "⑩"),  # 아무 별칭
    ("from os import environ\nx = environ['A']\n", "⑩"),
    ("from os import path, getenv as ge\nx = ge('A')\n", "⑩"),
    ("from os import getenv as ge  # env 남김 — 라이브러리\nx = ge('A')  # env 남김 — 라이브러리\n", ""),
    ("from os import path\nx = cfg.environ\n", ""),  # os 아닌 것의 .environ
    ("import os\nv = os.environ['C']  # env 남김 — 아무거나\n", "⑩"),  # 모르는 분류
    ("s = 'os.environ in text'  # 문자열·주석은 대상 밖\n", ""),
    ("import os\nenv = {**os.environ, 'PG_SCHEMA': 'x'}  # env 남김 — 하위 프로세스\n", "⑪"),  # 자식 env 사전 키
    ("env.pop('LLM_BASE_URL', None)\n", "⑪"),
    ("env['LLM_FAKE'] = '1'\n", "⑪"),
    ("import os\nos.environ['PG_SCHEMA'] = 't'  # env 남김 — 시험\n", ""),  # ⑪ 허용 분류
    ("env = child_env(base, LLM_FAKE='1', VLM_CONCURRENCY='2')\n", ""),  # 키워드는 맞는 길
    ("env['PYTHONUTF8'] = '1'\nconn = {'PG_SCHEMA': 'ai'}\n", ""),  # 설정 밖 이름 · env 없는 줄
]


def _env_selftest():
    """⑩·⑪ 글자 검색(e2-23) — 표의 코드 조각마다 위반 꼴이 맞는지."""
    for src, want in ENV_CASES:
        rows = M.env_lines(src, ENV_NAMES)
        got = "⑩" * any(used and kind is None for _, kind, used, _ in rows) + "⑪" * any(
            names and kind not in M.ENV_NAME_OK_KINDS for _, kind, _, names in rows
        )
        assert got == want, (src, got, want, rows)
    print(f"[selftest] check_modules ⑩⑪ — 글자 검색 {len(ENV_CASES)}건(분류 주석·별칭·문자열 제외·자식 env 설정 이름) 통과")


def _planted_selftest():
    """임시 폴더에 위반을 심은 가짜 트리로 check() 전체를 돌려 잡히는지·허용 사례가 통과하는지(저장소 파일 안 건드림)."""
    import tempfile

    bad_cases = {  # 경로 → 내용(모두 위반이어야 함)
        "pipeline/v_e2e_flat.py": "import stack_matrix\n",  # etl → PC 평가 도구 맨 이름
        "pipeline/v_e2e.py": "from validation.e2e import graph_llm\n",  # etl → validation 정적 import
        "pipeline/v_tests.py": "from tests.server.common import appcheck\n",  # 앱 → tests/ import
        "common/v_tests.py": "import tests.runner\n",
        "mcp_server/v_e2e.py": "import validation.e2e.stack_matrix\n",
        "common/v_e2e.py": "import validation.e2e.model_matrix\n",
        "pipeline/v_old.py": "import common_tools\n",  # 옛 공용 패키지 이름
        "mcp_server/v_old.py": "from common_tools.evaluation import stack_matrix\n",
        "validation/e2e/v_old.py": "import common_tools.cli.assets\n",
        "mcp_server/v_etl.py": "import pipeline.eval.stages\n",  # 앱 사이(기존 규칙)
        "validation/e2e/v_both.py": "import pipeline.eval.stages\nimport mcp_server.main\n",  # ⑨
        "pipeline/v_env.py": "import os\nx = os.environ.get('A')\n",  # ⑩ 분류 주석 없음
        "common/v_child.py": "env = {}\nenv['LLM_FAKE'] = '1'\n",  # ⑪ 설정 이름(실제 설정 모델의 이름 묶음)
    }
    ok_cases = {  # 위반이 아니어야 함
        "mcp_server/cli/ok_ask.py": "import ask\n",  # 맨 이름 import는 경계 위반 아님
        "pipeline/eval/ok_stages.py": "import stages\n",
        "validation/e2e/ok_etl.py": "import pipeline.eval.stages\n\ndef f():\n    import mcp_server.main\n",
        "pipeline/eval/ok_dyn.py": "import importlib\nimportlib.import_module('validation.e2e.graph_llm')\n",  # 문자열 — 정적 점검 밖
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
    missed = [r for r in bad_cases if virt[r] not in hit and r not in hit]  # ⑩⑪은 저장소 경로로 알림
    wrong = [r for r in ok_cases if virt[r] in hit]
    assert not missed and not wrong, (missed, wrong, errs)
    print(
        f"[selftest] check_modules — 심은 위반 {len(bad_cases)}건 모두 잡힘 · 허용 {len(ok_cases)}건 통과(맨 이름 ask·"
        "validation/e2e·옛 common_tools 이름)"
    )


def test_main():  # selftest() 뒤 저장소 경계 점검 check()까지
    selftest()
    errs = check()
    print("모듈 경계 통과" if not errs else "모듈 경계 위반:\n- " + "\n- ".join(errs))
    sys.exit(1 if errs else 0)
