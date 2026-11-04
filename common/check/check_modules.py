#!/usr/bin/env python3
"""모듈 경계 점검(docs/architecture.md) — 어기면 종료 코드 1.
단계 4(10-13) — dev/{common,modules,cli,eval,agents,tools/engines}가 deploy/data_pipeline/
{common,parse,structure,load,search,cli,evaluation,prompts,parse/agent,parse/engines}로 재편된 뒤의 규칙
(대상·판정은 그대로, 경로·import 이름만 새 레이아웃으로):
① parse/·structure/·load/·search/ 는 서로(다른 모듈 영역)·cli/·evaluation/ 을 import하지 않음 — 함께 쓰는 것은 common/ 만
   (parse/engines·parse/postprocess·parse/review·parse/agent는 parse 영역 내부라 경계 위반 아님 — 이미지 경계는
   10-16부터 4분할: rag-parse={parse,...}·rag-structure={structure,load,...}·rag-retrieval={search,...}·
   rag-answer={agent_platform,answer_agent}(MODULE_AREAS 밖) — 이 규칙 자체는 영역 네 개가 서로 못 보게 하는
   것이라 분할 전후로 안 바뀜(옛 rag-core={structure,load,search}는 별칭으로 남음, Dockerfile 참고)
② common/ 은 parse/·structure/·load/·search/·cli/·evaluation/·(저장소 루트) tools/ 를 import하지 않음(표준 라이브러리·numpy·선택 드라이버만)
③ 계약 함수(토큰·ID 토큰·색인 본문·정규화·임베딩 호출·내부망 확인·원본 위치·고객 명부)는 common/ 에만 정의 — 복사본이 갈라지는 것 방지
④ (GA) litellm·google.adk 직접 import 금지 — 0.2.0에 common/ai/adk.py(ADK 장치)를 지움(pl-46, 모델 호출은 common.ai.llm.complete HTTP).
   예외는 지시서 패키지의 옛 agent.py(prompts/<id>/agent.py — 바이트 그대로 두는 정의 파일, 코드가 읽지 않음)뿐
⑤ (없음 — agent_platform은 I5·I6에 지움, 0.2.0에 남은 점검 주석도 지움)
⑥ (GA) parse/·structure/·load/·search/ 아래 "openai/" 문자열 금지 — 모델 접두어는 common/ai/llm.py profile()(CT1 — 옛 models.py 병합)에서만 만듦(캐시 열쇠 불변 — I1)
⑦ (GA2) prompts/<id>/agent.py·parse/agent/<id>/agent.py는 data_pipeline.* 를 import하지 않음(모델·ADK만 — 0.2.0부터 코드가
   읽지 않는 옛 정의 파일, 바이트 그대로 둠 — docs/architecture/prompts.md)
⑧ (GA2) parse/·structure/·load/·search/·cli/·evaluation/의 L.chat()·A.complete() 호출은 agent= 키워드 필수(지시문마다
   다른 gamma 패키지 — selftest류 함수 안·cli/ping_models.py의 연결 확인은 업무 프롬프트가 없어 예외)
⑨ (프리즈 전 감사 3b, 10-16 — 4분할 뒤 TOOL_IMAGE 갱신) cli/·evaluation/는 여러 이미지(rag-parse·rag-structure·
   rag-retrieval, 지금도 rag-parse·rag-core 둘 다) 모두에 들어가므로: top-level(모듈 스코프) import에 parse와
   structure/load/search가 같이 있으면 안 됨(어느 이미지에서 돌려도 한쪽이 깨짐) · README "도구별 실행 이미지"
   (=TOOL_IMAGE, deploy/host/scripts/pipe_exec.sh 정본)에 있는 도구는 자기 이미지에 없는 영역을 top-level import하면 안 됨.
   함수 안 늦은(lazy) import는 허용(check_env.py의 parse.engines처럼).
I2(10-23) — 파싱·구조화 두 모듈 폴더가 data_etl/ 하나(extract·transform·load·shared·tools·eval_tools·agent 단계
폴더)로 합쳐져 parse·structure·load 영역이 "etl" 영역 하나가 됨: ① 경계는 etl ↔ search(data_retrieval) 사이에만 남고,
etl 안 단계 사이 방향(extract → transform → load)은 이 점검이 강제하지 않는다(사용자 10-23). ⑨의 "parse와
structure/load/search 동시"는 "etl과 search 동시"로, TOOL_IMAGE의 parse·structure 이미지는 둘 다 data_etl 전체를 넣으므로
같은 영역 집합 {etl}. ⑦의 agent.py 자리에 etl/agent/<id>/agent.py(옛 parse/agent·parse/prompts·structure/prompts)를 더함.
S3(10-26, refactor_plan 9-1·2-1) — 공용 패키지 이름이 common(common/{core,ai,store,check})으로: 새 이름 common도 "common" 영역으로
읽고, 단계 3 밖이라 아직 남은 common_tools/{cli,evaluation,prompts}는 옛 이름 그대로 cli·evaluation·prompts 영역(옛·새 둘 다 허용).
옛 cli/ 중 check_modules·ping_models·os_put은 common/check/로 옮겨 common 영역이 됨(규칙 본문 불변). 아래 규칙의 옛 common/model/ 자리는 common/ai/.
S4(10-26, refactor_plan 9-1·9-2) — data_etl/ → pipeline/(앱 이름 pipeline): 새 이름 pipeline도 "etl" 영역으로 읽는다(① pipeline ↔
data_retrieval import 금지 — S5에서 mcp_server). 단, common_tools/cli·evaluation에서 pipeline/로 옮긴 단계 4 도구 16개(LEGACY_TOOLS)는
파일마다 옛 cli·evaluation 영역 규칙을 그대로 받는다(코디네이터 답 Q3 a — pipeline/cli.py의 ask·pipeline/eval/server_checks.py가
data_retrieval을 함수 안에서 import, T-15) — S5(ask 쪼개기)·S6(평가 도구 정리)에서 etl로 정리.
S5(10-26, refactor_plan 9-1·9-2) — data_retrieval/ → mcp_server/(앱 이름 mcp_server): 새 이름 mcp_server도 "search" 영역으로 읽는다
(① pipeline ↔ mcp_server import 금지 — 옛·새 이름 둘 다). T-15(S5) — pipeline/cli.py의 ask·test-stack은 mcp_server/cli/ask.py로,
server_checks.py의 검색 측정(br54·l8·gh114)은 mcp_server/cli/search_checks.py로 옮겨 단계 4 도구 16개 중 검색을 import하는 것이 없어졌다
→ 16개 모두 etl 규칙(S4의 옛 cli·evaluation 예외를 풂). LEGACY_TOOLS 표는 경계 판정에 더 쓰지 않고 pipeline/cli.py selftest의 이미지
배정(옮긴 단계 4 도구를 옛처럼 "공용"으로 읽음)에만 남는다. common_tools에서 mcp_server/cli/로 옮긴 mcp_eval·qa_report도 search 규칙
(mcp_eval이 쓰던 model_matrix의 문항 로더를 mcp_eval로 옮겨 의존을 끊음 — 코디네이터 답 Q4 c · stack_matrix는 10-30 지움).
S6a(10-26) — common_tools/가 없어짐: 옛 영역 이름표(PKG_AREA·_canon)에서 common_tools 줄을 빼고, PC 전용 평가 도구 자리
validation/e2e/를 옛 evaluation 영역으로 읽는다(⑧ agent= · ⑨ etl·search top-level 동시 금지 그대로 — triple_extract/agent.py는
prompts 영역 ⑦). 옛 이름 import(`import common_tools…`)는 그 자체로 위반(남은 실행 코드 0 유지). LEGACY_TOOLS(옮긴 단계 4 도구 표)는
경계 판정에 안 쓰여 pipeline/cli.py의 이미지 배정 표로 옮겼고, ⑨의 TOOL_IMAGE·IMAGE_AREAS 규칙은 S5부터 걸릴 도구가 없어 뺐다(VS5 R-4).
맨 이름 import 판정표(MOVED_TOOLS — 11-02에 지움 · flat)에 S5 새 도구 ask·search_checks와 validation/e2e 도구를 더함(VS5 R-5 — 같은 앱 안은 허용).
S7e2(10-28, D-028 ④⑤ — 전환 다리 제거): ⑩ "os.environ 0" — 코드가 os.environ·os.getenv·os.environb를 직접 쓰는 줄(토큰 기준 — 주석·문자열 빼고)은
그 문장(또는 바로 위 주석 줄)에 분류 주석(op-09 — 예외 자리 없음: 엔진·인계 파일도 설정 객체로 읽음)
`env 남김 — <분류>`(ENV_KINDS — 라이브러리·하위 프로세스·내부 신호·이미지 신호·설정 파일 자리 신호·RUN_ENV 신호·시험·OS 값·호스트 도구)가
있어야 한다. 설정 값은 settings.yaml(설정 객체 cfg()·덮기 파일 put·child_env)로만 읽고 넘긴다. --env-report: 남은 줄을 분류별로 찍음.
S7e3(10-28, VS7e2 B-1·R-10): ⑩이 os 별칭(`import os as _os`)·`from os import environ` 이름도 잡는다. ⑪ "자식 env의 설정 이름 0" — 자식 env
(os.environ·그 사본·child_env 결과·subprocess 류 env= 값)에 설정 칸 이름(호스트 칸 빼고)을 넣거나 빼는 자리(AST —
dict 리터럴·dict(…, X=)·env[X] =·del·pop·setdefault·update, for 상수 이름 포함)는 위반이다(자식은 env의 설정 이름을 안 읽음 — settings.child_env(
base, X=…)·put). 같은 이름의 env를 읽는 라이브러리·시험·호스트 도구는 분류 주석(ENV_NAME_OK_KINDS)으로 둔다.
사용: python -m common.check.check_modules [--env-report]
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import DEPLOY_ROOT

# 10-14 이미지 단위 분리(사용자) — 코드가 deploy/{data_etl,data_retrieval,common_tools}로 나뉨(I2 전엔 data_etl 자리에 두 폴더 · S3부터 공용은 common/).
# 아래 규칙은 옛 영역 이름(etl/search/common/cli/evaluation/prompts)으로 쓰여 있어, 파일 경로와
# import 이름을 그 영역 이름으로 바꿔 읽는 변환만 둔다(규칙 본문 불변). 새 폴더 → 옛 영역:
PKG_AREA = (
    ("data_etl", "etl"),
    ("pipeline", "etl"),
    ("data_retrieval", "search"),
    ("mcp_server", "search"),  # S4 — pipeline · S5 — mcp_server
    ("resources/prompts", "prompts"),  # S2 — 지시서 패키지 자리
    ("validation/e2e/triple_extract", "prompts/triple_extract"),  # S6a — PC 전용 지시서(⑦ agent.py 규칙)
    (
        "valid_env/answer_test/rag_qa",
        "prompts/rag_qa",
    ),  # S10 — PC 전용 답변 점검 agent(S10에 validation/e2e/rag_qa — 10-29 사용자: valid_env로 되돌림, 같은 규칙)
    ("validation/e2e", "evaluation"),  # S6a — PC 전용 평가 도구(옛 common_tools/evaluation 자리의 규칙)
    ("common", "common"),
)  # S3 — 공용 패키지(S6a에 옛 common_tools 줄 뺌)
ROOT = DEPLOY_ROOT


def _virtual_rel(f):
    """deploy/<새 패키지>/x.py → 옛 영역 기준 상대 경로('parse/x.py' 등). 대상 밖이면 None."""
    rel = f.resolve().relative_to(ROOT.resolve()).as_posix()
    for pkg, area in PKG_AREA:
        if rel == pkg or rel.startswith(pkg + "/"):
            return area + rel[len(pkg) :]
    return None


def _canon(m):
    """새 import 이름 → 옛 data_pipeline.<영역> 이름(규칙 판정용)."""
    for new, old in (
        ("data_etl", "etl"),
        ("pipeline", "etl"),
        ("data_retrieval", "search"),
        ("mcp_server", "search"),
        ("validation", "evaluation"),
        ("common", "common"),
    ):  # S6a — validation.e2e.* = 옛 evaluation 영역
        if m == new or m.startswith(new + "."):
            return "data_pipeline." + old + m[len(new) :]
    return m


MODULE_AREAS = ("etl", "search")  # 옛 modules/<이름> — 서로 못 보는 "모듈 영역"(I2 — parse·structure·load가 etl 하나로)
CONTRACT_FUNCS = {
    "tokens",
    "id_terms",
    "index_text",
    "normalize_value",
    "embed_texts",
    "_embed_api",
    "is_internal",
    "require_internal",
    "make_source_uri",
    "source_record",
    "uri_from_path",
    "file_hash",
    "openviking_key",
    "bundle_chunk_keys",
    "norm",
    "_aliases",
    "match_clients",
    "pairs_of",
    "table_rows",
    "locate",
}
SAME_NAME_OK = {
    ("common/core/meaning.py", "tokens"),
    ("etl/transform/represent/parse_scoring.py", "norm"),
}  # 이름만 같고 다른 규칙(파싱 채점의 유의미 토큰·공백 보존 정규화)
# 단계 4 — 옛 ALLOW의 "tools"(tools/engines·tools/parse_agent_tools) 예외 전부 삭제: 그 코드가 parse/engines·
# parse/agent/agent_tools.py로 옮겨 parse 영역 **안**이 되어 더 이상 경계 위반이 아님(ALLOW 자체가 필요 없어짐).
# I2 — 옛 예외 ("structure/build_bundle.py", "data_pipeline.parse")(--no-rep 실험 경로의 지연 import)는 두 영역이 etl 하나가 되어 필요 없어짐.
ALLOW: set = set()
# ⑫ 단계 방향(CLAUDE.md §1 — pipeline 안 extract → transform → load, 거꾸로 import 금지 · 11-03 사용자: 리뷰에만 맡기지 않고 자동 점검).
#   함수 안 늦은 import도 셈. STAGE_ALLOW = 지금 있는 예외(파일, 가져오는 단계) — 엔진 파일은 바이트를 바꾸면 엔진 지문이 바뀌어(등급 A) 옮기지 않고 적어 둔다.
STAGES = ("extract", "transform", "load")
STAGE_ALLOW: set = set()  # 11-04 — 엔진 qwen_vlm의 VLM 게이트 import는 pipeline/shared/vlmcall.py로 옮겨 예외 없음
AGENT_KWARG_EXEMPT = {"common/check/checker.py"}  # 연결 확인(ping) — 업무 프롬프트가 없음(GA2 ⑧)


def _agent_kwarg_missing(tree):
    """L.chat(/A.complete( 호출 중 agent= 키워드가 없는 줄 번호 — selftest류 함수(가짜 모델·연결 점검) 안은 제외(GA2 ⑧)."""
    missing = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            f = node.func
            is_target = (
                isinstance(f, ast.Attribute)
                and f.attr in ("chat", "complete")
                and isinstance(f.value, ast.Name)
                and f.value.id in ("L", "A", "ADK")
            )
            if is_target and not any(kw.arg == "agent" for kw in node.keywords) and not any("selftest" in name for name in self.stack):
                missing.append(node.lineno)
            self.generic_visit(node)

    V().visit(tree)
    return missing


def imported(f):
    out = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out |= {_canon(a.name) for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(_canon(n.module))
        elif isinstance(n, ast.ImportFrom) and n.level > 0:
            # 상대 import(from ..structure import x)도 절대 이름으로 풀어 같은 경계 규칙에 넣는다(10-13 재검토 C4).
            pkg = ["data_pipeline", *Path(_virtual_rel(f)).parent.parts]
            base = pkg[: len(pkg) - (n.level - 1)] if n.level > 1 else pkg
            out.add(".".join(base + ([n.module] if n.module else [])))
    return out


def _module_scope_imports(tree, f):
    """모듈 스코프에서 실행되는 import만(함수·클래스·람다 본문은 안 내려감 — 그 안은 lazy import라 3b 대상 아님).
    if/try/with 안은 포함(그래도 import 시점에 실행됨). 상대 import 풀이는 imported()와 같은 규칙."""
    out = set()

    class V(ast.NodeVisitor):
        def visit_Import(self, node):
            out.update(_canon(a.name) for a in node.names)

        def visit_ImportFrom(self, node):
            if node.level == 0 and node.module:
                out.add(_canon(node.module))
            elif node.level > 0:
                pkg = ["data_pipeline", *Path(_virtual_rel(f)).parent.parts]
                base = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                out.add(".".join(base + ([node.module] if node.module else [])))

        def visit_FunctionDef(self, node):
            return

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            return

        def visit_Lambda(self, node):
            return

    V().visit(tree)
    return out


def _area_of_import(m):
    """import 모듈 문자열 → MODULE_AREAS 중 하나(data_pipeline.<영역>.*)면 그 이름, 아니면 None."""
    parts = m.split(".")
    if parts[0] == "data_pipeline" and len(parts) > 1 and parts[1] in MODULE_AREAS:
        return parts[1]
    return None


def _cli_eval_violations(rel, tree, f):
    """3b — cli/·evaluation/(S6a부터 validation/e2e/) 모듈 규칙(위 docstring ⑨): top-level import의 etl ↔ search 동시 금지.
    (⑨의 둘째 규칙 TOOL_IMAGE — 이미지별 도구의 top-level import — 은 S5부터 걸릴 도구가 없어 S6a에 뺌, VS5 R-4.)"""
    out = []
    areas = {a for a in (_area_of_import(m) for m in _module_scope_imports(tree, f)) if a}
    if "etl" in areas and "search" in areas:
        out.append(f"{rel}: top-level import에 etl과 search가 같이 있음(3b) — 한쪽은 함수 안에서 늦게(lazy) import")
    return out


def _key_of(m):
    """import 모듈 문자열 → ALLOW/판정에 쓰는 짧은 키. data_pipeline.<모듈 영역>(2단)이면 그대로, 그 밖엔 첫 세그먼트만
    (data_pipeline.cli·data_pipeline.evaluation·tools·dev_tools·pipeline 등 — 단계 4 전 "modules.<모듈>"·"cli"·"tools"와 같은 역할)."""
    top = m.split(".")
    if top[0] == "data_pipeline" and len(top) > 1:
        return "data_pipeline." + top[1]
    return top[0]


def _stage_violations(rel, mods):
    """⑫ etl/<단계>/… 파일이 뒤 단계(data_pipeline.etl.<뒤 단계>)를 import하면 위반 — STAGE_ALLOW에 적힌 것만 통과."""
    parts = rel.split("/")
    if parts[0] != "etl" or len(parts) < 3 or parts[1] not in STAGES:
        return []
    own = STAGES.index(parts[1])
    out = []
    for m in sorted(mods):
        seg = m.split(".")
        if seg[:2] == ["data_pipeline", "etl"] and len(seg) > 2 and seg[2] in STAGES and STAGES.index(seg[2]) > own:
            if (rel, seg[2]) not in STAGE_ALLOW:
                out.append(
                    f"{rel}: {m} import — 단계 방향 위반(extract → transform → load, 거꾸로 import 금지 — 함께 쓸 것은 pipeline/shared·common)"
                )
    return out


def check():
    bad = []
    flat = {
        f.stem for f in (ROOT / "validation" / "e2e").glob("*.py") if f.stem != "__init__"
    }  # PC 평가 도구를 이름만으로 import하는 것도 잡음(S6a — 옛 cli/·evaluation/ glob · 옛 단계 4 도구 이름표 MOVED_TOOLS는 11-02에 지움)
    for f in sorted(ROOT.rglob("*.py")):
        rel = _virtual_rel(f)
        if rel is None or "/output/" in f"/{rel}" or ".venv" in rel or "__pycache__" in rel:
            continue
        text = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError) as e:
            bad.append(f"{rel}: 구문 오류({type(e).__name__}) — 점검할 수 없음(S7e2 리뷰 — 전에는 조용히 건너뜀)")
            continue
        area = rel.split("/")[0]
        if area in MODULE_AREAS and "openai/" in text:
            bad.append(f"{rel}: 'openai/' 문자열 — 모델 접두어는 common/ai/llm.py profile()에서만 만듦(GA ⑥)")
        if not rel.startswith("common/"):
            dup = {
                n.name
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name in CONTRACT_FUNCS and (rel, n.name) not in SAME_NAME_OK
            }
            if dup:
                bad.append(f"{rel}: 계약 함수 {sorted(dup)}를 따로 정의 — common/에서 import")
        mods = imported(f)
        tst = sorted(m for m in mods if m == "tests" or m.startswith("tests."))
        if tst:  # S9(D-018) — 시험(tests/)은 앱을 import해도 되지만 앱·PC 도구는 시험을 import하지 않음(이미지에는 tests/server만 — 실행은 자식 프로세스 문자열로)
            bad.append(f"{rel}: {tst[0]} import — 앱은 tests/를 import하지 않음(S9 — 시험 실행은 pipeline.cli selftest·pytest)")
        old = sorted(m for m in mods if m == "common_tools" or m.startswith("common_tools."))
        if old:  # S6a — 옛 공용 패키지 이름(없어진 폴더) — 지문용 옛 이름 대응표(common/core/fingerprint.py 바이트 글자)는 import가 아니라 대상 밖
            bad.append(f"{rel}: {old[0]} import — common_tools는 S6a에 없어짐(common·pipeline·mcp_server·validation/e2e로)")
        if area in MODULE_AREAS:
            for m in mods:
                key = _key_of(m)
                other = key.startswith("data_pipeline.") and key != f"data_pipeline.{area}" and key.split(".")[1] in MODULE_AREAS
                foreign = key in ("data_pipeline.cli", "data_pipeline.evaluation", "tools", "dev_tools", "pipeline") or (m in flat)
                if (other or foreign) and (rel, key) not in ALLOW:
                    bad.append(f"{rel}: {m} import — 모듈 경계 위반(함께 쓸 것은 common/)")
        bad.extend(_stage_violations(rel, mods))
        if rel.startswith("common/"):
            for m in mods:
                key = _key_of(m)
                if (
                    (key.startswith("data_pipeline.") and key.split(".")[1] in MODULE_AREAS + ("cli", "evaluation"))
                    or key in ("tools", "dev_tools", "pipeline")
                    or m in flat
                ):
                    bad.append(f"{rel}: {m} import — common은 모듈·도구 코드를 쓰지 않음")
        # 10-14 — 한 모듈만 쓰는 prompts/<id>/ 묶음이 그 모듈 폴더로 옮겨가 가상 경로가 "parse/prompts/<id>/agent.py"
        # 처럼 영역 접두어가 붙음(PKG_AREA) — "prompts/" 로 시작하지 않아도 어딘가에 "/prompts/" 조각이 있으면 같은 자리.
        is_agent_py = rel.endswith("/agent.py") and (rel.startswith("prompts/") or "/prompts/" in rel or rel.startswith("etl/agent/"))
        if is_agent_py:
            for m in mods:
                if m.split(".")[0] in ("data_pipeline", "tools", "dev_tools", "pipeline") or m in flat:
                    bad.append(f"{rel}: {m} import — agent.py 패키지는 모델·ADK만(data_pipeline.* 금지, GA2 ⑦)")
        if area in ("cli", "evaluation"):
            bad.extend(_cli_eval_violations(rel, tree, f))
        if (area in MODULE_AREAS or area in ("cli", "evaluation")) and rel not in AGENT_KWARG_EXEMPT:
            for ln in _agent_kwarg_missing(tree):
                bad.append(f"{rel}:{ln}: L.chat()/A.complete() 호출에 agent= 없음(GA2 ⑧ — gamma 패키지 지정 필수)")
        for m in mods:
            top = m.split(".")[0]
            if top == "litellm":
                bad.append(f"{rel}: {m} import — litellm은 쓰지 않음(GA ④ — 0.2.0 ADK 장치 지움)")
            if (m == "google.adk" or m.startswith("google.adk.")) and not is_agent_py:
                bad.append(f"{rel}: {m} import — google.adk는 지시서 패키지 agent.py에서만(GA ④ — 0.2.0 ADK 장치 지움)")
    bad.extend(env_violations())
    bad.extend(child_env_violations())
    return bad


# ⑩ "os.environ 0"(S7e2) — 줄마다 다는 분류 주석(op-09부터 예외 자리 없음)
ENV_KINDS = (
    "라이브러리",
    "하위 프로세스",
    "내부 신호",
    "이미지 신호",
    "설정 파일 자리 신호",
    "RUN_ENV 신호",
    "시험",
    "OS 값",
    "호스트 도구",
)
_ENV_MARK = re.compile(r"env 남김 — (" + "|".join(ENV_KINDS) + ")")
_ENV_SKIP = ("output/", ".venv/", "valid_env/", ".claude/", "docs/", "reference/")  # reference/ — git 밖 참고 자료(PC 전용, 사용자 10-30)


_ENV_ATTRS = ("environ", "getenv", "environb", "putenv", "unsetenv")  # putenv·unsetenv — VS7e3 R-4(⑩·⑪ 둘 다)


def _os_aliases(text):
    """(os 모듈 이름들, os에서 바로 가져온 environ·getenv·environb 이름들) — `import os as _os`·`from os import environ as E`도 잡는다(VS7e2 R-10)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"os"}, set()
    return _file_info(tree)["aliases"][:2]


def _file_info(tree):
    """파일 한 번 걷기 — aliases(os 이름들·os에서 가져온 environ 등·subprocess 이름들·subprocess에서 가져온 run·call — 리뷰 S7e3) ·
    imports(`from m import a as b`의 (a, b)) · funcs(함수 정의들)."""
    os_mods, os_direct, sub_mods, sub_direct, imports, funcs = {"os"}, set(), {"subprocess"}, set(), [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            os_mods |= {a.asname for a in n.names if a.name == "os" and a.asname}
            sub_mods |= {a.asname for a in n.names if a.name == "subprocess" and a.asname}
        elif isinstance(n, ast.ImportFrom):
            imports += [(a.name, a.asname) for a in n.names if a.asname]
            if n.module == "os" and n.level == 0:
                os_direct |= {a.asname or a.name for a in n.names if a.name in _ENV_ATTRS}
            elif n.module == "subprocess" and n.level == 0:
                sub_direct |= {a.asname or a.name for a in n.names if a.name in ("run", "call")}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):  # 람다 몸통도 scope(VS7e3 R-4 — 람다 안 spawn의 env=)
            funcs.append(n)
    return {"aliases": (os_mods, os_direct, sub_mods, sub_direct), "imports": imports, "funcs": funcs}


def _comment_kinds(text, toks=None):
    """줄 → 분류 함수 — 그 줄이 속한 문장(논리 줄) 안이나 바로 위 주석 줄 묶음의 분류 주석(`env 남김 — <분류>`), 없으면 None."""
    toks = toks if toks is not None else list(tokenize.generate_tokens(io.StringIO(text).readline))
    comments = {t.start[0]: t.string for t in toks if t.type == tokenize.COMMENT}
    spans, cur = {}, None
    for t in toks:  # 줄 → 그 줄이 속한 논리 줄의 (첫 줄, 끝 줄)
        if cur is None and t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            cur = t.start[0]
        if t.type == tokenize.NEWLINE and cur is not None:
            for ln in range(cur, t.end[0] + 1):
                spans[ln] = (cur, t.end[0])
            cur = None
    lines = text.splitlines()

    def kind(line):
        first, last = spans.get(line, (line, line))
        texts = [comments.get(ln, "") for ln in range(first, last + 1)]
        ln = first - 1
        while ln >= 1 and lines[ln - 1].strip().startswith("#"):  # 바로 위 주석 줄 묶음
            texts.append(lines[ln - 1])
            ln -= 1
        m = next((m for m in map(_ENV_MARK.search, texts) if m), None)
        return m.group(1) if m else None

    return kind


def _env_lines(text):
    """[(줄, 분류 또는 None)] — os.environ·os.getenv·os.environb 토큰이 있는 줄마다(os 별칭·`from os import environ` 이름 포함 — VS7e2 R-10),
    그 문장(논리 줄) 안이나 바로 위 주석 줄의 분류 주석."""
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    kind = _comment_kinds(text, toks)
    mods, direct = _os_aliases(text)
    out, seen = [], set()
    for i, a in enumerate(toks):
        if a.type != tokenize.NAME:
            continue
        hit = (a.string in mods and i + 2 < len(toks) and toks[i + 1].string == "." and toks[i + 2].string in _ENV_ATTRS) or (
            a.string in direct and not (i and toks[i - 1].string == ".")
        )
        if not hit or a.start[0] in seen:
            continue
        seen.add(a.start[0])
        out.append((a.start[0], kind(a.start[0])))
    return out


# ⑪ 자식 env의 설정 이름(S7e3 — VS7e2 B-1·R-10): S7e2부터 자식은 env의 설정 이름(옛 env 이름)을 읽지 않는다(settings.yaml·덮기 파일만).
# 자식 env를 만드는 dict(os.environ 사본·paths.child_env·settings.child_env 결과, subprocess 류의 env= 값)에 설정 칸 이름(호스트 칸 이름
# 빼고)을 넣거나(dict 리터럴·dict(…, X=)·env[X] = ·update·setdefault) 빼면(pop·del) 효과가 없다 — settings.child_env(base, X=…)
# (비우기 X=None)·put(X=…)로. os.environ에 쓰는 것도 같다. 라이브러리가 같은 이름의 env를 읽는 자리·시험·호스트 도구(셸 자식)는 분류 주석으로 둔다.
ENV_NAME_OK_KINDS = ("라이브러리", "시험", "호스트 도구")


def _setting_names():
    """자식 env에 넣거나 빼도 효과가 없는 설정 이름 — common + 이 이미지의 앱 칸 env 이름(호스트 칸 빼고)."""
    from common.config import settings as S

    return S._all_names() - {"RUN_ENV", "SETTINGS_FILE"}


_SPAWN = (
    "Popen",
    "check_call",
    "check_output",
    "gated_popen",
    "create_subprocess_exec",
    "create_subprocess_shell",
    "execve",
    "execvpe",
    "spawnve",
)
_ENV_FUNCS = (
    "child_env",
)  # 자식 env를 돌려주는 함수(paths.child_env·settings.child_env) — 저장소에서 이것을 돌려주는 함수도 더함(_env_funcs)


def _scope_nodes(scope):
    """scope 안 노드 — 안쪽 함수·람다 몸통은 빼고(그 함수는 따로 봄)."""
    out, todo = [], list(ast.iter_child_nodes(scope))
    while todo:
        n = todo.pop()
        out.append(n)
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(n))
    return out


def _call_name(n):
    f = n.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def _flat_targets(targets):
    """대입 대상 — `a["X"], a["Y"] = …`·`[a, b] = …`의 안쪽까지."""
    for t in targets:
        if isinstance(t, (ast.Tuple, ast.List)):
            yield from _flat_targets(t.elts)
        else:
            yield t


def _assign_parts(n):
    """(대상들, 값) — Assign·AnnAssign(값 있음)만, 그 밖은 None."""
    if isinstance(n, ast.Assign):
        return list(_flat_targets(n.targets)), n.value
    if isinstance(n, ast.AnnAssign) and n.value is not None:
        return [n.target], n.value
    return None


class _EnvScope:
    """한 함수(또는 모듈) 안 — 어떤 값이 자식 env인가. 자식 env = os.environ(별칭 포함)·그 사본·자식 env 함수(child_env·그것을 돌려주는 저장소
    함수 — import 별칭 포함) 결과·{**env, …}·dict(env, …)·subprocess 류 env= 값. 이름은 줄 순서로 본다 — 같은 이름에 다른 값(설정 칸 사전 등 —
    validation/e2e Names)을 다시 대입하면 그 뒤로는 자식 env가 아님."""

    def __init__(self, scope, aliases, funcs):
        """aliases = (os 이름들, os에서 바로 가져온 이름들, subprocess 이름들, subprocess에서 바로 가져온 run·call). funcs는 같은 집합 객체를
        계속 보므로(_env_funcs가 키움) 한 번 만든 scope를 패스마다 다시 쓴다."""
        (self.mods, self.direct, self.sub_mods, self.sub_direct), self.funcs = aliases, funcs
        self.nodes = _scope_nodes(scope)
        self.assigns = {}  # 이름 → [(줄, 값 노드)]
        self.stores = {}  # 이름 → [값 노드] — `_C[k] = 값`(캐시 감싸개 — VS7e3 R-4: `return dict(_C[k])`)
        self.consts = {}  # for 변수 → 글자 상수들(for k in ("A", "B"): env.pop(k))
        args = getattr(scope, "args", None)  # 함수·람다 매개변수 — `{**base, "X": …}`의 base(VS7e3 R-4)
        self.params = {a.arg for a in (args.posonlyargs + args.args + args.kwonlyargs)} if args is not None else set()
        for n in self.nodes:
            parts = _assign_parts(n)
            if parts:
                for t in parts[0]:
                    if isinstance(t, ast.Name):
                        self.assigns.setdefault(t.id, []).append((n.lineno, parts[1]))
                    elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                        self.stores.setdefault(t.value.id, []).append(parts[1])
            elif isinstance(n, ast.For) and isinstance(n.target, ast.Name) and isinstance(n.iter, (ast.Tuple, ast.List, ast.Set)):
                self.consts.setdefault(n.target.id, []).extend(e.value for e in n.iter.elts if isinstance(e, ast.Constant))
        for v in self.assigns.values():
            v.sort(key=lambda lv: lv[0])  # _scope_nodes는 줄 순서가 아님
        self.spawned = {
            kw.value.id
            for n in self.nodes
            if isinstance(n, ast.Call) and self.spawns(n)
            for kw in n.keywords
            if kw.arg == "env" and isinstance(kw.value, ast.Name)
        }

    def spawns(self, n):
        cn = _call_name(n)
        f = n.func
        return (
            cn in _SPAWN
            or (cn in ("run", "call") and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in self.sub_mods)
            or (isinstance(f, ast.Name) and f.id in self.sub_direct)
        )

    def is_environ(self, n):
        return (
            isinstance(n, ast.Attribute) and n.attr in ("environ", "environb") and isinstance(n.value, ast.Name) and n.value.id in self.mods
        ) or (isinstance(n, ast.Name) and n.id in self.direct)

    def is_env_name(self, name, line, depth=0):
        """그 줄에서 name이 자식 env인가 — 그 줄 전 마지막 대입 값으로(대입이 없으면 — 매개변수 — subprocess 류 env=로 넘기는지로)."""
        prev = [v for ln, v in self.assigns.get(name, ()) if ln < line]
        if prev:
            return self.origin(prev[-1], line, depth + 1)
        return name in self.spawned

    def origin(self, e, line, depth=0):
        if depth > 20:
            return False
        if self.is_environ(e):
            return True
        if isinstance(e, ast.Name):
            return self.is_env_name(e.id, line, depth)
        if isinstance(e, ast.Call):
            cn = _call_name(e)
            if cn in self.funcs:
                return True
            if cn == "copy" and isinstance(e.func, ast.Attribute):
                return self.origin(e.func.value, line, depth + 1)
            if cn == "dict" and e.args:
                return self.origin(e.args[0], line, depth + 1)
            if cn == "get" and isinstance(e.func, ast.Attribute):  # 캐시 감싸개 `_C.get(k)`
                return self.stored_env(e.func.value, line, depth)
        if isinstance(e, ast.Subscript):  # 캐시 감싸개 `_C[k]`
            return self.stored_env(e.value, line, depth)
        if isinstance(e, ast.Dict):
            return any(k is None and (self.origin(v, line, depth + 1) or self.bare_param(v)) for k, v in zip(e.keys, e.values))
        return False

    def stored_env(self, c, line, depth):
        """c가 자식 env를 담는 사전인가(`c[k] = <자식 env>`가 이 scope에 있음 — VS7e3 R-4)."""
        return isinstance(c, ast.Name) and any(self.origin(v, line, depth + 1) for v in self.stores.get(c.id, ()))

    def bare_param(self, v):
        """`{**base, "X": …}`의 base가 대입 없는 매개변수인가 — 이름을 넣는 사전은 자식 env로 본다(VS7e3 R-4 — 호출자가 os.environ을 넘김)."""
        return isinstance(v, ast.Name) and v.id in self.params and v.id not in self.assigns

    def env_target(self, n, line):
        return self.is_environ(n) or (isinstance(n, ast.Name) and self.is_env_name(n.id, line))

    def key_names(self, k):
        if isinstance(k, ast.Constant):
            return [k.value]
        if isinstance(k, ast.Name):
            return self.consts.get(k.id, [])
        return []

    def hits(self):
        """[(노드, 이름, 꼴)] — 자식 env에 넣거나 빼는 글자 이름."""
        out = []

        def keys(d, node, how):
            for k, v in zip(d.keys, d.values):
                if isinstance(k, ast.Constant):
                    out.append((node, k.value, how))
                elif k is None and isinstance(v, ast.Dict):  # {**os.environ, **{"X": …}}(VS7e3 R-4)
                    keys(v, node, how)

        def env_value(v, node):
            if isinstance(v, ast.Dict):
                keys(v, node, "dict")
            elif isinstance(v, ast.Call) and _call_name(v) == "dict":
                out.extend((node, kw.arg, "dict(…, X=)") for kw in v.keywords)
                for a in v.args:
                    if isinstance(a, ast.Dict):
                        keys(a, node, "dict")

        for n in self.nodes:
            line = getattr(n, "lineno", 0)
            parts = _assign_parts(n)
            if parts:
                targets, value = parts
                named = [t.id for t in targets if isinstance(t, ast.Name)]
                last_spawned = any(nm in self.spawned and not [1 for ln, _ in self.assigns[nm] if ln > n.lineno] for nm in named)
                if named and (self.origin(value, line) or last_spawned):
                    env_value(value, n)  # 자식 env 사본 대입(또는 subprocess 류 env=로 넘기는 마지막 대입)
                for t in targets:
                    if isinstance(t, ast.Subscript) and self.env_target(t.value, line):
                        out.extend((t, k, "env[X] =") for k in self.key_names(t.slice))
            elif isinstance(n, ast.AugAssign) and isinstance(n.op, ast.BitOr) and self.env_target(n.target, line):
                env_value(n.value, n)  # env |= {...}
            elif isinstance(n, ast.Delete):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and self.env_target(t.value, line):
                        out.extend((t, k, "del") for k in self.key_names(t.slice))
            elif isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg == "env" and self.spawns(n):
                        env_value(kw.value, n)
                cn = _call_name(n)
                f = n.func
                if (
                    isinstance(f, ast.Attribute)
                    and f.attr in ("putenv", "unsetenv")
                    and isinstance(f.value, ast.Name)
                    and f.value.id in self.mods
                ) or (isinstance(f, ast.Name) and f.id in self.direct and f.id in ("putenv", "unsetenv")):  # os.putenv·unsetenv(VS7e3 R-4)
                    if n.args:
                        out.extend(
                            (n, k, "putenv" if (f.attr if isinstance(f, ast.Attribute) else f.id) == "putenv" else "del")
                            for k in self.key_names(n.args[0])
                        )
                elif cn in self.funcs:  # paths.child_env(extra)·settings.child_env(base, …)의 위치 인자 dict(설정 이름은 키워드로만)
                    for a in n.args:
                        if isinstance(a, ast.Dict):
                            keys(a, n, "child_env 위치 인자")
                    for kw in n.keywords:  # paths.child_env(extra={…}) 키워드 꼴(VS7e3 R-4)
                        if kw.arg == "extra" and isinstance(kw.value, ast.Dict):
                            keys(kw.value, n, "child_env extra=")
                elif cn == "dict" and n.args and self.origin(n.args[0], line):
                    env_value(n, n)
                elif (
                    isinstance(n.func, ast.Attribute)
                    and cn in ("pop", "setdefault", "update", "__setitem__")
                    and self.env_target(n.func.value, line)
                ):
                    if cn == "update":
                        out.extend((n, kw.arg, "update") for kw in n.keywords)
                        for a in n.args:
                            if isinstance(a, ast.Dict):
                                keys(a, n, "update")
                    elif n.args:
                        out.extend((n, k, cn) for k in self.key_names(n.args[0]))
            elif isinstance(n, ast.Dict) and self.origin(n, line):
                keys(n, n, "dict")
        return out

    def returns_env(self):
        return any(isinstance(n, ast.Return) and n.value is not None and self.origin(n.value, n.lineno + 1) for n in self.nodes)


class _EnvFile:
    """파일 하나 — scope(모듈·함수)마다 _EnvScope를 한 번만 만들고, 자식 env 함수 이름(funcs + import 별칭)은 같은 집합 객체를 키운다."""

    def __init__(self, tree):
        info = _file_info(tree)
        self.tree, self.fa, self.imports = tree, set(_ENV_FUNCS), info["imports"]
        self.scopes = [(s, _EnvScope(s, info["aliases"], self.fa)) for s in [tree] + info["funcs"]]

    def update(self, funcs):
        """funcs + `from m import child_env as settings_env` 같은 import 별칭."""
        self.fa |= funcs | {alias for name, alias in self.imports if name in funcs}


def _env_funcs(files):
    """저장소에서 자식 env를 돌려주는 함수 이름(child_env + 그것을 돌려주는 함수 — 몇 단 사슬까지). files: [_EnvFile]."""
    funcs = set(_ENV_FUNCS)
    cands = [
        (f, s, sc)
        for f in files
        for s, sc in f.scopes
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(n, ast.Return) and n.value is not None for n in sc.nodes)
    ]
    for _ in range(4):
        for f in files:
            f.update(funcs)
        found = {s.name for _, s, sc in cands if s.name not in funcs and sc.returns_env()}
        if not found:
            break
        funcs |= found
    for f in files:
        f.update(funcs)
    return funcs


def _child_env_names(ef, kind, names):
    """[(줄, 이름, 꼴)] — 자식 env dict·os.environ에 설정 이름을 넣거나 빼는 자리(분류 주석 ENV_NAME_OK_KINDS 줄 빼고).
    ef = _EnvFile(_env_funcs를 거친 것), kind = 줄 → 분류 함수를 돌려주는 함수(필요할 때만 토큰화), names = 설정 이름 묶음."""
    hits, kinds = set(), None
    for _, sc in ef.scopes:
        for node, name, how in sc.hits():
            if not isinstance(name, str) or name not in names:
                continue
            kinds = kinds or kind()
            if kinds(node.lineno) not in ENV_NAME_OK_KINDS:
                hits.add((node.lineno, name, how))
    return sorted(hits)


def child_env_violations(root=None, names=None):
    """⑪ — 저장소 .py 전부(⑩과 같은 범위·예외 자리)에서 자식 env·os.environ에 설정 이름을 넣거나 빼는 자리."""
    root = Path(root) if root else ROOT
    names = _setting_names() if names is None else names
    files = []
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith(_ENV_SKIP) or "__pycache__" in rel or "/output/" in f"/{rel}":
            continue
        text = f.read_text(encoding="utf-8")
        if "env" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue  # 구문 오류는 check()가 따로 알림
        files.append((rel, text, _EnvFile(tree)))
    _env_funcs([ef for _, _, ef in files])
    bad = []
    for rel, text, ef in files:
        for ln, name, how in _child_env_names(ef, lambda text=text: _comment_kinds(text), names):
            bad.append(
                f"{rel}:{ln}: 자식 env·os.environ에 설정 이름 {name}({how}) — 자식은 env의 설정 이름을 안 읽음, "
                f"settings.child_env(base, {name}=…)·put({name}=…)로(None = 비움). 같은 이름의 env를 읽는 라이브러리·시험·호스트 도구면 "
                f"분류 주석 `env 남김 — <{'·'.join(ENV_NAME_OK_KINDS)}>`(⑪ S7e3)"
            )
    return bad


def env_reads(root=None):
    """⑩ — [(경로, 줄, 분류)] 저장소의 .py 전부(_ENV_SKIP·__pycache__ 빼고)."""
    root = Path(root) if root else ROOT
    rows = []
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith(_ENV_SKIP) or "__pycache__" in rel or "/output/" in f"/{rel}":
            continue
        text = f.read_text(encoding="utf-8")
        if "os." not in text:
            continue
        try:
            found = _env_lines(text)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        rows += [(rel, ln, kind) for ln, kind in found]
    return rows


def env_violations(root=None):
    return [
        f"{rel}:{ln}: os.environ 직접 사용 — 설정 값은 settings.yaml(cfg()·put·child_env)로, 남겨야 하면 분류 주석 "
        f"`env 남김 — <{'·'.join(ENV_KINDS)}>`(⑩ S7e2)"
        for rel, ln, kind in env_reads(root)
        if kind is None
    ]


def env_report(root=None):
    from collections import Counter

    rows = env_reads(root)
    by = Counter((kind or "분류 없음") for _, _, kind in rows)
    out = [f"os.environ 남은 줄 {len(rows)}개(⑩ — 토큰 기준):"]
    out += [f"  {n:4d}  {k}" for k, n in sorted(by.items(), key=lambda kv: -kv[1])]
    return out


if __name__ == "__main__":
    utf8_stdout()
    errs = check()
    if "--env-report" in sys.argv:
        print("\n".join(env_report()))
    print("모듈 경계 통과" if not errs else "모듈 경계 위반:\n- " + "\n- ".join(errs))
    sys.exit(1 if errs else 0)
