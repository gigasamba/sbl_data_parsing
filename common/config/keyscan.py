"""코드·스크립트가 읽는 환경변수 이름 모으기 — 설정 모델과 빠진 키 없이 맞는지 본다.
모으는 규칙(git 추적 파일 — valid_env/·.claude/·docs/ 제외):
  파이썬 — os.environ.get·os.getenv·environ.get·setdefault·os.environ["X"](대입 제외)·"X" in os.environ·지역 도우미
           (_f·_cap·g·_list·_case·_flag·base_env.get·env.get·c.get·conf.get)·동적 이름 f"{prefix}_X"(LLM·VLM·EMBED·RERANK)
  셸 — ${X:-…}(그 파일에서 대입해도 입력) · ${X}·$X 중 그 파일에서 대입하지 않은 것 · compose·systemd — ${X} 전부
  (valid_env/ 중 PC 시험 Docker valid_env/docker/는 넣음)
이름 목록을 돌며 읽는 키(for k in ("PG_HOST", …))처럼 규칙으로 못 잡는 것은 NAME_LIST에 적는다.
--check: 모은 키 = 설정 모델 칸(옛 env 이름) + NOT_SETTINGS(YAML에 안 넣는 것)인지 대조 — 빠진 키·모르는 칸을 찍고 rc 1.
사용: python -m common.config.keyscan [--json] [--where KEY] [--check]
"""

import json
import re
import subprocess
import sys
from collections import defaultdict

from common.core.console import utf8_stdout
from common.core.paths import DEPLOY_ROOT

ROOT = DEPLOY_ROOT  # 저장소 루트(PC) — git ls-files 기준
_SKIP = (
    "valid_env/",
    ".claude/",
    "docs/",
    "output/",
    "deploy/release/lint_changed.sh",
)  # 마지막 — PC 개발 점검 스크립트(FIX 등 셸 스위치는 설정 키가 아님)
_KEEP = ("valid_env/docker/",)  # PC 시험 Docker(compose·smoke_test.sh)
PREFIXES = ("LLM", "VLM", "EMBED")

# 규칙(아래 정규식)으로 못 잡는 읽기 — 이름 목록·동적 이름
NAME_LIST = {
    "VLM_EXTRA_BODY": "common/ai/llm.py(_EXTRA_ENV_KEY 표)",
    **{
        f"RDB_COL_{f}": "pipeline/extract/candidate_pick.py(_rdb_cols — 설정 칸 tuning.extract.source_columns.source_column_*)"
        for f in ("DOC_ID", "FILENAME", "KEY", "SIZE", "SOURCE_SYSTEM")
    },
}
# YAML에 넣지 않는 이름 — env로 남김(라이브러리가 읽음) · 인자(빌드·반입·시험 스크립트). 코드가 읽지 않는 이름은 대조하지 않는다.
NOT_SETTINGS = {
    "APPLOG_CONTEXT": ("env로 남김", "내부 신호 — 부모 → 자식 request/run/span ID(JSON), 설정 아님"),
    "SETTINGS_FILE": ("env로 남김", "설정 파일 위치(새 — D-015)"),
    "SETTINGS_LENIENT": (
        "env로 남김",
        "내부 신호 — entrypoint가 점검 명령(check·selftest 등)에만 줌: 서버에서도 틀린 설정 파일을 경고만(원인을 볼 수 있게 — S7e2)",
    ),
    **{
        f"APP_{k.upper()}": (
            "env로 남김",
            "컨테이너 안 약속 경로 — settings.IMAGE_PATHS 고정값(load_settings.sh가 냄, compose 마운트 자리 — 사용자 11-02)",
        )
        for k in ("output_root", "code_root", "docs_mount")
    },
    "SETTINGS_LOADED": (
        "env로 남김",
        "내부 신호 — load_settings.sh load_settings가 이미 낸 설정 파일(하위 스크립트가 다시 안 읽게, 새 — S7e1)",
    ),
    "PYTHONUTF8": ("env로 남김", "파이썬 실행 옵션(이미지·셸)"),
    "APP_ENTRY": ("env로 남김", "이미지 신호(Dockerfile ENV) — dev_entry.sh가 `devbox` 밖의 명령을 넘길 이미지 시작 스크립트"),
    "SSH_PORT": ("env로 남김", "compose.dev.yml → dev_entry.sh — 값은 option.devbox.ssh_port(DEVBOX_SSH_PORT)"),
    "UV_VERSION": ("env로 남김", "Dockerfile 빌드 인자(uv 판)"),
    "DO_NOT_TRACK": ("env로 남김", "외부 라이브러리 원격 측정 끄기 — Dockerfile ENV(U-1, S7a2) · settings·빈 틀에서만 뺌(S7e)"),
    "HF_HOME": ("env로 남김", "라이브러리(huggingface)가 읽음"),
    "HF_HUB_OFFLINE": ("env로 남김", "라이브러리가 읽음"),
    "LITELLM_LOCAL_MODEL_COST_MAP": ("env로 남김", "라이브러리(litellm)가 읽음"),
    "NETWORK_HOST": ("env로 남김", "entrypoint 신호(compose)"),
    "OMP_NUM_THREADS": ("env로 남김", "라이브러리(OpenMP)가 읽음"),
    "PARSE_RUN_ID": ("env로 남김", "부모 → 자식 프로세스 신호"),
    "PIPELINE_VERSION": ("env로 남김", "버전 표기 마지막 대체(VERSION이 없거나 SemVer가 아닐 때 — D-036)"),
    "PYTHONPATH": ("env로 남김", "이미지·셸"),
    "RAG_MODULE": ("env로 남김", "이미지 신호(Dockerfile ENV)"),
    "RUN_ENV": ("env로 남김", "새 키(D-015) — local·dev·prd"),
    "SCARF_NO_ANALYTICS": ("env로 남김", "외부 라이브러리 원격 측정 끄기 — Dockerfile ENV(U-1, S7a2) · settings·빈 틀에서만 뺌(S7e)"),
    "TESSDATA_PREFIX": ("env로 남김", "라이브러리(tesseract)가 읽음"),
    "TRANSFORMERS_OFFLINE": ("env로 남김", "라이브러리가 읽음"),
    "TZ": ("env로 남김", "OS·이미지 ENV"),
    "USER": ("env로 남김", "OS 사용자 이름(OS가 줌)"),
    "USERNAME": ("env로 남김", "OS 사용자 이름(Windows)"),
    "ALLOW_NO_ASSETS": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    **{
        n: ("인자", "빌드·굽기 스크립트 변수(build_ship.sh·bake_prod_image.sh·stage_images.sh — op-06·op-07)")
        for n in ("APP_VERSION", "VCS_REF", "BAKE_TEST", "CODE_BUNDLE", "CODE_DIR", "CODE_OUT")
    },
    "NF": ("인자", "awk 내장 변수($NF — build_ship.sh tar 권한 점검), 설정 아님"),
    "SMOKE_OVERLAY_DIR": ("인자", "PC 시험 Docker 덮기 파일 폴더 — smoke_test.sh가 mktemp로 만들어 compose에 넘김(S7e2)"),
    "SMOKE_SYSTEM": ("인자", "PC 시험 Docker 원천 이름 — smoke_test.sh 인자(search는 원천 하나 필수 — mc-16)"),
    "ASSET_SRC": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "BUILDKIT_SYNTAX": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "BUILD_ARGS": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "BUILD_ONLY": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "CHUNK": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "FORCE_TAG": ("인자", "build_ship.sh — 이미 있는 버전 태그를 다시 만들 때만 1(D-036)"),
    "IMAGE_TARGET": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "KNOWN_FAIL": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "OUT": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "PY": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "REMOTE_DIR": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "REMOTE_DOCKER": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "SHIP_REPO": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "TAG": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "TARGET": ("인자", "빌드·반입·시험 스크립트 인자(5-3 B)"),
    "APP_VERSION": ("인자", "Dockerfile 빌드 인자 — 이미지에 버전을 새김(build_ship.sh가 VERSION 파일에서, op-09)"),
    "VCS_REF": ("인자", "Dockerfile 빌드 인자 — 이미지에 커밋을 새김(build_ship.sh, op-09)"),
    "CODE_OUT": ("인자", "build_ship.sh — 코드 묶음 출력 파일(op-09)"),
    "CODE_BUNDLE": ("인자", "stage_images.sh — 실행 이미지와 함께 옮길 코드 묶음 파일(bake_prod_image.sh가 넘김, op-09)"),
    "BAKE_TEST": ("인자", "bake_prod_image.sh — PC 시험 태그면 1(태그가 VERSION과 달라도 멈추지 않음, op-09)"),
    "CODE_DIR": (
        "인자",
        "호스트 스크립트 변수 — 개발 서버 코드 폴더(in_container.sh가 실행 이미지일 때 pwd로 채움, compose.code*.yml 마운트 — op-09)",
    ),
    "RAG_ROOT": (
        "인자",
        "호스트 스크립트 변수 — 서버 루트(코드 폴더 자체 — load_settings.sh가 구해 compose edw_chain.yaml 마운트에, op-13)",
    ),
    "INSTANCE": ("인자", "호스트 스크립트 변수 — 벌 번호(코드 폴더 이름 끝 -<숫자> — load_settings.sh가 구함, op-17)"),
    "NAME_SUFFIX": (
        "인자",
        "호스트 스크립트 변수 — 여러 벌 이름 끝 -<벌 번호 — 코드 폴더 이름 끝 숫자>(load_settings.sh가 구해 compose container_name·묶음 이름·타이머에, op-15)",
    ),
    **{
        n: ("인자", f"호스트 스크립트 변수 — {what} 이름 = 밑 이름(설정 {key}) + NAME_SUFFIX(load_settings.sh가 구해 compose·스크립트에)")
        for n, what, key in (
            ("PIPELINE_CNAME", "data-pipeline 컨테이너", "PIPELINE_CONTAINER"),
            ("DATA_PARSING_CNAME", "mcp-data-parsing 컨테이너", "DATA_PARSING_CONTAINER"),
            ("MCP_CNAME", "mcp-server 컨테이너", "MCP_CONTAINER"),
            ("COMPOSE_PNAME", "compose 묶음", "COMPOSE_PROJECT"),
        )
    },
    "POSTGRES_DB": ("env로 남김", "PG 컨테이너 env — compose가 PG_DB로 채움(설정 칸은 op-08에 지움)"),
    "POSTGRES_USER": ("env로 남김", "PG 컨테이너 env — compose가 PG_USER로 채움(설정 칸은 op-08에 지움)"),
}
# 모은 키가 아닌 것(셸 문법·Dockerfile ARG·selftest 가짜 이름)
IGNORE = {
    "BASE",
    "X_ALLOW_EXTERNAL",
    "NF",
    "PATH",
    "DC_ROOT",
    "DC_UNIT_DIR",
    "DC_FAKE",
}  # NF=awk `$NF` · PATH·DC_*=host_ctl.sh 시험용

_K = r"([A-Z][A-Z0-9_]{1,})"
_PY = [
    re.compile(r'(?:os\.environ|environ|base_env|\benv|\bc|\bconf|_ENV|\benviron_)\.(?:get|setdefault)\(\s*["\']' + _K + r'["\']'),
    re.compile(r'os\.getenv\(\s*["\']' + _K + r'["\']'),
    re.compile(r'os\.environ\[\s*["\']' + _K + r'["\']\s*\](?!\s*=[^=])'),
    re.compile(r'["\']' + _K + r'["\']\s+(?:not\s+)?in\s+(?:os\.)?environ'),
    re.compile(r'(?<![\w.])(?:_f|_cap|g|_list|_case|_flag|_int|_float|_bool|_envf?|env_int|env_float|env_flag)\(\s*["\']' + _K + r'["\']'),
    re.compile(r'\bMM\.(?:own|setting)\(\s*["\']' + _K + r'["\']'),  # PC 평가 도구(validation/e2e)가 설정 칸을 옛 env 이름으로 읽음
]
_PY_DYN = re.compile(r'f["\']\{[a-z_]+\}_' + _K + r'["\']')
_SH_USE = re.compile(r"\$\{" + _K + r"(?=[:}\-?=+#%/])|\$" + _K + r"\b")
_SH_DEF = re.compile(r"\$\{" + _K + r":?[-=?]")  # ${X:-기본} — 그 파일에서 대입해도 바깥 값을 먼저 보는 입력
_SH_SET = re.compile(
    r"(?:^|[\s;(])(?:export\s+|local\s+|readonly\s+)?" + _K + r"=|\bread\s+(?:-\w+\s+)*" + _K + r"|\bfor\s+" + _K + r"\s+in"
)
_SH_BUILTIN = {
    "BASH_SOURCE",
    "PWD",
    "HOME",
    "PATH",
    "USER",
    "IFS",
    "OPTARG",
    "OPTIND",
    "RANDOM",
    "SECONDS",
    "LINENO",
    "BASH_REMATCH",
    "PIPESTATUS",
    "HOSTNAME",
    "UID",
    "EUID",
    "TMPDIR",
    "SHELL",
    "OLDPWD",
    "BASH_VERSION",
    "FUNCNAME",
    "PPID",
    "TERM",
    "LANG",
    "LC_ALL",
}


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return [p for p in out if p and (p.startswith(_KEEP) or not p.startswith(_SKIP))]


def _kind(rel):
    name = rel.rsplit("/", 1)[-1]
    if rel.endswith(".py"):
        return "py"
    if rel.endswith(".sh") or name == "entrypoint.sh":
        return "sh"
    if rel.endswith((".yml", ".yaml", ".service", ".timer")) or name == "Dockerfile":
        return "unit"
    return None


def scan(root=ROOT):
    """{키: [읽는 곳 "경로:행", …]} — 위 규칙으로 잡히는 것만."""
    found = defaultdict(list)
    for rel in _tracked():
        kind = _kind(rel)
        if not kind:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        if kind == "py":
            for i, line in enumerate(lines, 1):
                for rx in _PY:
                    for m in rx.finditer(line):
                        found[m.group(1)].append(f"{rel}:{i}")
                for m in _PY_DYN.finditer(line):
                    if "environ" in line or "getenv" in line:
                        for p in PREFIXES:
                            found[f"{p}_{m.group(1)}"].append(f"{rel}:{i}")
        elif kind == "sh":
            assigned = {k for line in lines for m in _SH_SET.finditer(line) for k in m.groups() if k}
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                defaulted = {m.group(1) for m in _SH_DEF.finditer(line)}
                for m in _SH_USE.finditer(line):
                    k = m.group(1) or m.group(2)
                    if k and (k not in assigned or k in defaulted) and k not in _SH_BUILTIN:
                        found[k].append(f"{rel}:{i}")
        else:
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                for m in re.finditer(r"\$\{" + _K, line):
                    if m.group(1) not in _SH_BUILTIN:
                        found[m.group(1)].append(f"{rel}:{i}")
    return {k: sorted(set(v)) for k, v in sorted(found.items())}


def object_reads():
    """설정 객체로 읽는 칸의 옛 env 이름 — common 칸(common/·pipeline/ 코드가 cfg()·by_env·given으로 읽음)·pipeline 칸(
    pipeline/ 코드가 pipeline.config의 cfg()·given으로 읽음)·mcp 칸(mcp_server/ 코드가 mcp_server.config의 cfg()·given으로 읽음). 정적 근사(알리기용 — 빠진 키 판정에는 안 씀), 파일마다: `.<절>.<칸>`이
    나오거나, `= ….<절>`로 절을 변수에 받은 파일에 `.<칸>`이 나오거나, 옛 env 이름 글자가 나오거나(by_env("X")·given("X")·checked("X")),
    역할 접두로 짓는 이름(`{prefix}_BASE_URL` 꼴 — PREFIXES)의 꼬리가 나오면 읽는 것으로 친다."""
    from common.config import settings as S

    root = ROOT

    def texts(folder, skip):
        return (
            [f.read_text(encoding="utf-8") for f in sorted((root / folder).rglob("*.py")) if not skip(f)]
            if (root / folder).is_dir()
            else []
        )

    common_texts = texts("common", lambda f: "config" in f.parts)
    pipeline_texts = texts("pipeline", lambda f: f == root / "pipeline" / "config.py")
    mcp_texts = texts("mcp_server", lambda f: f == root / "mcp_server" / "config.py")
    mcfg = root / "mcp_server" / "config.py"
    if mcfg.is_file():  # 칸 정의(F(…, "X", …))는 빼고 시작 때 읽는 상수(CFG — class MCPConfig 아래)만
        mcp_texts.append(mcfg.read_text(encoding="utf-8").partition("class MCPConfig")[2])
    sections = [(S.CommonSettings, common_texts + pipeline_texts + mcp_texts)]
    apps = S.app_classes(("pipeline", "mcp"))
    for name, pool in (("pipeline", pipeline_texts), ("mcp", mcp_texts)):
        if name in apps:
            sections.append((apps[name].model_fields[name].annotation, pool))
    out = set()
    for model, pool in sections:
        for path, f, _ in S.walk(model):
            env = S.env_name(f)
            if S.is_host("x." + path):
                continue
            parts = path.split(".")
            leaf, sect = parts[-1], parts[-2] if len(parts) > 1 else "common"
            tail = next((env[len(p) :] for p in PREFIXES if env.startswith(p + "_")), None)
            for text in pool:
                if (
                    re.search(r"\." + sect + r"\." + leaf + r"\b", text)
                    or (re.search(r"=[^\n]*\." + sect + r"\s*(#|$)", text, re.M) and re.search(r"\b\w+\." + leaf + r"\b", text))
                    or f'"{env}"' in text
                    or (tail and re.search(r"\{p(?:refix)?\}" + re.escape(tail) + r"\b", text))
                ):
                    out.add(env)
                    break
    return out


def check(found=None):
    """(빠진 키, 모델에만 있는 칸) — 빠진 키: 코드가 읽는데 모델 칸·NOT_SETTINGS 어디에도 없음(0이어야 함).
    모델에만 있는 칸: 새 칸(아직 안 읽는 것)이나 지운 읽기 — 알리기만(설정 객체로 읽는 칸은 읽는 것으로 침)."""
    from common.config import settings as S

    found = scan() if found is None else found
    read = (set(found) | set(NAME_LIST)) - IGNORE
    fields = {S.env_name(f) for cls in S.app_classes().values() for _, f, _ in S.walk(cls)} - {None}
    missing = sorted(read - fields - set(NOT_SETTINGS))
    model_only = sorted(fields - read - object_reads())
    return missing, model_only


def main(argv):
    found = scan()
    if "--check" in argv:
        missing, model_only = check(found)
        read = (set(found) | set(NAME_LIST)) - IGNORE
        print(
            f"코드가 읽는 키 {len(read)}개(9-4 규칙 {len(found)} ∪ 이름 목록 {len(NAME_LIST)} − IGNORE {len((set(found) | set(NAME_LIST)) & IGNORE)}"
            f" — git 추적 코드·셸·compose·systemd, 새 키 RUN_ENV·SETTINGS_FILE 포함) · 빠진 키 {len(missing)}개"
            + (": " + " ".join(missing) if missing else "")
        )
        obj = object_reads() - read
        print(f"설정 객체로만 읽는 칸 {len(obj)}개(common — S7b · pipeline — S7c · mcp — S7d부터 cfg()·by_env·given, env 직접 읽기 없음)")
        print(f"모델에만 있는 칸 {len(model_only)}개" + (": " + " ".join(model_only) if model_only else ""))
        return 1 if missing else 0
    if "--where" in argv:
        k = argv[argv.index("--where") + 1]
        print("\n".join(found.get(k, [])) or "(없음)")
        return 0
    if "--json" in argv:
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return 0
    for k, v in found.items():
        print(f"{k}\t{len(v)}\t{v[0]}")
    print(f"# 키 {len(found)}개", file=sys.stderr)
    return 0


if __name__ == "__main__":
    utf8_stdout()
    raise SystemExit(main(sys.argv[1:]))
