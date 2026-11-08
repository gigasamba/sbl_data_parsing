#!/usr/bin/env python3
"""모듈 경계 점검(docs/architecture.md) — 어기면 종료 코드 1.
규칙은 영역 이름(etl·search·common·cli·evaluation·prompts)으로 쓰고, 파일 경로·import 이름은 PKG_AREA·_canon으로
영역 이름으로 바꿔 읽는다(pipeline → etl, mcp_server → search, validation/e2e → evaluation, resources/prompts → prompts).
① etl과 search는 서로 import하지 않음 — 함께 쓰는 것은 common/ 만
② common/ 은 etl·search·cli·evaluation·(저장소 루트) tools/ 를 import하지 않음(표준 라이브러리·numpy·선택 드라이버만)
③ 계약 함수(토큰·ID 토큰·색인 본문·정규화·임베딩 호출·내부망 확인·원본 위치·고객 명부)는 common/ 에만 정의 — 복사본이 갈라지는 것 방지
④ litellm import 금지, google.adk는 지시서 패키지 agent.py에서만 — 모델 호출은 common.ai.llm.complete(HTTP)
⑥ etl·search 아래 "openai/" 문자열 금지 — 모델 접두어는 common/ai/llm.py profile()에서만 만듦(캐시 열쇠 유지)
⑦ 지시서 패키지 agent.py(prompts/<id>/agent.py — 코드가 읽지 않는 정의 파일, 바이트 그대로 둠 — docs/architecture/resources.md §2)는
   앱 코드를 import하지 않음(모델·ADK만)
⑧ etl·search·cli·evaluation의 L.chat()·A.complete() 호출은 agent= 키워드 필수(지시문마다 다른 패키지 — selftest류 함수 안과
   연결 확인은 업무 프롬프트가 없어 예외)
⑨ cli·evaluation은 여러 이미지에 들어가므로 top-level(모듈 스코프) import에 etl과 search가 같이 있으면 안 됨(어느 이미지에서
   돌려도 한쪽이 깨짐). 함수 안 늦은(lazy) import는 허용.
⑩ "os.environ 0" — 앱 코드(common·pipeline·mcp_server)에서 os.environ·os.getenv 등을 쓰는 줄(토큰 검색 — 주석·문자열 빼고,
   `os.`·`_os.` 뒤만)은 그 문장(또는 바로 위 주석 줄)에 분류 주석 `env 남김 — <분류>`(ENV_KINDS)가 있어야 한다. 설정 값은
   settings.yaml(설정 객체 cfg()·덮기 파일 put·child_env)로만 읽고 넘긴다.
⑪ "자식 env의 설정 이름 0" — 같은 앱 코드에서 env가 든 줄에 설정 칸 이름(호스트 칸 빼고)을 글자로 env 사전 키·env[…]·pop·setdefault·
   putenv에 쓰면 위반이다(글자 검색 — 자식은 env의 설정 이름을 안 읽음, settings.child_env(base, X=…)·put). 같은 이름의 env를 읽는
   라이브러리·시험·호스트 도구는 분류 주석(ENV_NAME_OK_KINDS)으로 둔다.
⑫ pipeline 안 단계 방향 extract → transform → load — 거꾸로 import 금지(함수 안 늦은 import도 셈).
앱·PC 도구는 tests/를 import하지 않는다.
사용: python -m common.check.check_modules
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import DEPLOY_ROOT

# 저장소 폴더 → 규칙 영역 이름. 규칙은 영역 이름으로 쓰여 있어 경로·import 이름만 바꿔 읽는다.
PKG_AREA = (
    ("data_etl", "etl"),
    ("pipeline", "etl"),
    ("data_retrieval", "search"),
    ("mcp_server", "search"),
    ("resources/prompts", "prompts"),  # 지시서 패키지 자리
    ("validation/e2e/triple_extract", "prompts/triple_extract"),  # PC 전용 지시서(⑦ agent.py 규칙)
    (
        "valid_env/answer_test/rag_qa",
        "prompts/rag_qa",
    ),  # PC 전용 답변 점검 agent(⑦ agent.py 규칙)
    ("validation/e2e", "evaluation"),  # PC 전용 평가 도구
    ("common", "common"),
)
ROOT = DEPLOY_ROOT


def _virtual_rel(f):
    """저장소 안 x.py → 영역 기준 상대 경로('etl/x.py' 등). 대상 밖이면 None."""
    rel = f.resolve().relative_to(ROOT.resolve()).as_posix()
    for pkg, area in PKG_AREA:
        if rel == pkg or rel.startswith(pkg + "/"):
            return area + rel[len(pkg) :]
    return None


def _canon(m):
    """import 이름 → data_pipeline.<영역> 이름(규칙 판정용)."""
    for new, old in (
        ("data_etl", "etl"),
        ("pipeline", "etl"),
        ("data_retrieval", "search"),
        ("mcp_server", "search"),
        ("validation", "evaluation"),
        ("common", "common"),
    ):  # validation.e2e.* = evaluation 영역
        if m == new or m.startswith(new + "."):
            return "data_pipeline." + old + m[len(new) :]
    return m


MODULE_AREAS = ("etl", "search")  # 서로 못 보는 "모듈 영역"
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
    "table_rows",
    "locate",
}
SAME_NAME_OK = {
    ("common/core/meaning.py", "tokens"),
    ("etl/transform/represent/parse_scoring.py", "norm"),
}  # 이름만 같고 다른 규칙(파싱 채점의 유의미 토큰·공백 보존 정규화)
ALLOW: set = set()  # 모듈 경계 예외(파일, import 키) — 지금은 없음
# ⑫ 단계 방향(CLAUDE.md §1 — pipeline 안 extract → transform → load, 거꾸로 import 금지). 함수 안 늦은 import도 셈.
#   STAGE_ALLOW = 예외(파일, 가져오는 단계) — 엔진 파일은 바이트를 바꾸면 엔진 지문이 바뀌어(등급 A) 옮기지 않고 여기 적는다.
STAGES = ("extract", "transform", "load")
STAGE_ALLOW = {
    (
        "etl/extract/filter_and_rotate.py",
        "transform",
    ),  # 형식 거르기(registry.engines_for)·회전 OCR(rapidocr ko_params) — 엔진은 transform/parse에
}
AGENT_KWARG_EXEMPT = {"common/check/checker.py"}  # 연결 확인(ping) — 업무 프롬프트가 없음(⑧)


def _agent_kwarg_missing(tree):
    """L.chat(/A.complete( 호출 중 agent= 키워드가 없는 줄 번호 — selftest류 함수(가짜 모델·연결 점검) 안은 제외(⑧)."""
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
            # 상대 import(from ..structure import x)도 절대 이름으로 풀어 같은 경계 규칙에 넣는다.
            pkg = ["data_pipeline", *Path(_virtual_rel(f)).parent.parts]
            base = pkg[: len(pkg) - (n.level - 1)] if n.level > 1 else pkg
            out.add(".".join(base + ([n.module] if n.module else [])))
    return out


def _module_scope_imports(tree, f):
    """모듈 스코프에서 실행되는 import만(함수·클래스·람다 본문은 안 내려감 — 그 안은 lazy import라 ⑨ 대상 아님).
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
    """⑨ — cli·evaluation(validation/e2e) 모듈: top-level import의 etl ↔ search 동시 금지."""
    out = []
    areas = {a for a in (_area_of_import(m) for m in _module_scope_imports(tree, f)) if a}
    if "etl" in areas and "search" in areas:
        out.append(f"{rel}: top-level import에 etl과 search가 같이 있음(3b) — 한쪽은 함수 안에서 늦게(lazy) import")
    return out


def _key_of(m):
    """import 모듈 문자열 → ALLOW/판정에 쓰는 짧은 키. data_pipeline.<영역>(2단)이면 그대로, 그 밖엔 첫 세그먼트만
    (tools·dev_tools·pipeline 등)."""
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
    }  # PC 평가 도구를 맨 이름으로 import하는 것도 잡음
    for f in sorted(ROOT.rglob("*.py")):
        if ".venv" in f.relative_to(ROOT).parts:  # before resolve(): a worktree's .venv may be a link to another checkout's venv
            continue
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
        if tst:  # 앱·PC 도구는 시험을 import하지 않음(이미지에는 tests/server만 — 실행은 자식 프로세스 문자열로)
            bad.append(f"{rel}: {tst[0]} import — 앱은 tests/를 import하지 않음(S9 — 시험 실행은 pipeline.cli selftest·pytest)")
        old = sorted(m for m in mods if m == "common_tools" or m.startswith("common_tools."))
        if old:  # 없는 패키지 이름 — fingerprint.py의 이름 대응표 글자는 import가 아니라 대상 밖
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
        # 모듈 폴더 안 지시서 묶음은 가상 경로에 영역 접두어가 붙으므로("etl/prompts/<id>/agent.py")
        # "prompts/"로 시작하지 않아도 "/prompts/" 조각이 있으면 같은 자리.
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
    return bad


# ⑩·⑪ 글자 검색(e2-23) — 앱 코드(common·pipeline·mcp_server)만, 줄마다 다는 분류 주석 `env 남김 — <분류>`(예외 자리 없음)
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
ENV_NAME_OK_KINDS = ("라이브러리", "시험", "호스트 도구")  # ⑪ — 같은 이름의 env를 읽는 라이브러리·시험·호스트 도구
_ENV_MARK = re.compile(r"env 남김 — (" + "|".join(ENV_KINDS) + ")")
_ENV_ATTRS = ("environ", "getenv", "environb", "putenv", "unsetenv")
_APP_DIRS = ("common", "pipeline", "mcp_server")
_NON_CODE = (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)
# ⑪ env 사전 키("X": …)·env…[ "X" ]·env….pop/setdefault("X")·putenv("X") — env가 든 줄의 글자 이름만
_NAME_SET = re.compile(r"""(?:env\w*\[|env\w*\.(?:pop|setdefault)\(|putenv\()\s*["']([A-Z][A-Z0-9_]*)["']|["']([A-Z][A-Z0-9_]*)["']\s*:""")


def _setting_names():
    """자식 env에 넣거나 빼도 효과가 없는 설정 이름 — common + 이 이미지의 앱 칸 env 이름(호스트 칸 빼고)."""
    from common.config import settings as S

    return S._all_names() - {"RUN_ENV", "SETTINGS_FILE"}


def env_lines(text, names=frozenset()):
    """[(줄, 분류 또는 None, ⑩ env 직접 사용?, ⑪ 설정 이름들)] — ⑩ 코드(주석·문자열 빼고)의 os.environ·os.getenv 등(`os.`·`_os.` 뒤),
    ⑪ env가 든 줄의 설정 이름 글자(_NAME_SET). 분류 주석은 그 문장(논리 줄) 안이나 바로 위 주석 줄에서 찾는다."""
    lines, out = text.splitlines(), []
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    start, hits = None, set()
    for i, t in enumerate(toks):
        if start is None and t.type not in _NON_CODE:
            start = t.start[0]
        if (
            t.type == tokenize.NAME
            and t.string in _ENV_ATTRS
            and i > 1
            and toks[i - 1].string == "."
            and toks[i - 2].string in ("os", "_os")
        ):
            hits.add(t.start[0])
        if t.type != tokenize.NEWLINE or start is None:
            continue
        found = {}
        for ln in range(start, t.end[0] + 1):
            code = lines[ln - 1].split("#")[0]
            ns = {n for m in _NAME_SET.findall(code) for n in m if n in names} if "env" in code else set()
            if ns:
                found[ln] = ns
        if hits or found:
            top = start
            while top > 1 and lines[top - 2].strip().startswith("#"):  # 바로 위 주석 줄 묶음
                top -= 1
            m = _ENV_MARK.search("\n".join(lines[top - 1 : t.end[0]]))
            out += [(ln, m.group(1) if m else None, ln in hits, found.get(ln, set())) for ln in sorted(hits | set(found))]
        start, hits = None, set()
    return out


def env_violations(root=None, names=None):
    """⑩·⑪ — 앱 코드 .py 전부(output·__pycache__ 빼고)."""
    root = Path(root) if root else ROOT
    names = _setting_names() if names is None else names
    bad = []
    for d in _APP_DIRS:
        for f in sorted((root / d).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if "__pycache__" in rel or "/output/" in f"/{rel}":
                continue
            try:
                rows = env_lines(f.read_text(encoding="utf-8"), names)
            except (tokenize.TokenError, SyntaxError):
                continue  # 구문 오류는 check()가 따로 알림
            for ln, kind, used, found in rows:
                if used and kind is None:
                    bad.append(
                        f"{rel}:{ln}: os.environ 직접 사용 — 설정 값은 settings.yaml(cfg()·put·child_env)로, 남겨야 하면 분류 주석 "
                        f"`env 남김 — <{'·'.join(ENV_KINDS)}>`(⑩)"
                    )
                for name in sorted(found) if kind not in ENV_NAME_OK_KINDS else ():
                    bad.append(
                        f"{rel}:{ln}: 자식 env에 설정 이름 {name} — 자식은 env의 설정 이름을 안 읽음, settings.child_env(base, {name}=…)·"
                        f"put({name}=…)로. 같은 이름의 env를 읽는 라이브러리·시험·호스트 도구면 분류 주석 `env 남김 — <{'·'.join(ENV_NAME_OK_KINDS)}>`(⑪)"
                    )
    return bad


if __name__ == "__main__":
    utf8_stdout()
    errs = check()
    print("모듈 경계 통과" if not errs else "모듈 경계 위반:\n- " + "\n- ".join(errs))
    sys.exit(1 if errs else 0)
