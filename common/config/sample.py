"""settings.sample.yaml 만들기·대조 — 앱 설정 모델의 모든 칸을 새 배치(op-08 ② — common.config.layout)로 코드 기본값과 함께 낸다.
맨 위 required(운영자가 채울 값 — 카테고리마다 쓰는 곳 표시 한 번) → 역할 절(common·extract·transform·load·search·ops·dev — 세부 카테고리 제목) →
tuning(코드 상수 후보). 칸마다 한 줄 주석: 설명 · 기본값 · 넣을 수 있는 값. 칸을 더하거나 바꾸면 다시 만든다.
사용: python -m common.config.sample            # 저장소 루트 settings.sample.yaml에 씀
      python -m common.config.sample --check    # 파일이 모델과 같은지(다르면 rc 1)
      python -m common.config.sample --where PG_HOST [이름…]   # 옛 env 이름 → 파일 자리·모델 경로·내부 표시(판정 꼴·지문 등 — sample에서 뺀 것)
"""

import re
import sys

import yaml

from common.config import layout as L
from common.config import settings as S
from common.core.console import utf8_stdout

OUT = S.REPO_ROOT / "settings.sample.yaml"
HEAD = """# settings.sample.yaml — 설정 파일 구조와 설명. 생성: python -m common.config.sample (손으로 고치지 않음)
# 복사해 required 칸을 채우면 시작된다 — PC: 저장소 루트 settings.yaml(권한 600) · 서버: $SERVER_ENV_DIR/settings.yaml(UID 10001·권한 640, SETTINGS_FILE).
# 순서: required(운영자가 채울 값) → 역할 절 common·extract·transform·load·search·ops·dev → tuning(코드 상수 후보 — 보통 비워 둠).
#   빈 칸 = 코드 기본값. 적힌 값은 코드 기본값보다 이긴다(나중에 코드 기본값이 바뀌어도 이 파일을 고치지 않으면 반영 안 됨).
#   [PC·서버]·[서버만]·[PC만] = 그 카테고리를 채워야 하는 곳. 서버만 칸을 PC에서 비우면 그 기능(EDW·Object Storage·게시 등)만 꺼진다.
#   [비밀] = settings.yaml에만 둠(출력·로그에 안 나옴). [파라미터] = 결과(파싱·청크·검색 순위)를 바꾸는 값.
#   각 앱은 자기 칸만 읽는다(pipeline: required·common·extract·transform·load·ops·dev · mcp: required·common·search·ops·dev — tuning은 둘 다).
#   같은 절·칸을 두 번 쓰면 시작 거부(앞 것이 조용히 사라지지 않게). 옛 배치(최상위 common·pipeline·mcp) → python -m common.config.migrate.
#   한 번만 몇 칸 바꿀 때: 덮기 파일(base·overrides — python -m common.config.overrides). 옛 env 이름·판정 꼴: docs/operations/env-guide.md.
"""
# C-39(사용자 10-27 S7e1 Q6 a) — options.conf(옛 카탈로그 — S7e2에 지움)가 env에 채우던 값 중 설정 모델 기본값과 결과가 다른 칸(값에 비밀 없음).
# output/orca/S7e1/base_calc.py로 뽑음(예외 줄 빼고 · 표기만 다른 5.0/5 빼고 · 모델 칸 없는 env 이름 빼고). sample 주석으로만 낸다(모델 기본값은 코드 기본값 그대로).
CATALOG_VALUES = {
    "CHUNK_TABLE": "",
    "DOC_DIR": "",
    "DOC_DIR_PREPARED": "output/prepared",
    "EDW_PATH_PREFIX": "",
    "EDW_QUERY_MAX_ROWS": "1000",
    "EDW_QUERY_TABLES": "",
    "EMBED_MODEL": "",
    "EMBED_QUERY_CACHE": "",
    "EMBED_QUERY_PREFIX": "",
    "INDEX_CONF": "",
    "LLM_MODEL": "",
    "LLM_SPEND_FILE": "",
    "MCP_BUNDLE": "",
    "PARSE_POST": "all",
    "PIPE_EMBED": "",
    "RUNLOG_FILE": "",
    "RUN_MODE": "prod",
    "SECURE_DOC_PASSWORDS_FILE": "",
    "SOFFICE_BIN": "",
    "SOURCE_MANIFEST": "",
    "SOURCE_URI_PREFIX": "",
    "VLM_MODEL": "",
}  # 옛 CHAIN_STRUCTURE_URL 기본값은 11-01에 지움(pl-10 — trigger 서버)
CATALOG_VALUES["MCP_STORE"] = "pg"
# S7e2(VS7e1 B-2) — 옛 이미지 ENV로 굽던 칸(DOC_DIR·DOC_DIR_PREPARED·PIPE_EMBED·SOFFICE_BIN)은 컨테이너에서 options.conf 값이 걸린 적이 없음(이미지 ENV가
# 먼저 있어 카탈로그 setdefault가 건너뜀) — 지금은 이미지 안 모델 기본값이 같은 값이라 표에서 뺀다(env 파일에 적은 값은 migrate가 옮김).
for _k in ("DOC_DIR", "DOC_DIR_PREPARED", "PIPE_EMBED", "SOFFICE_BIN"):
    CATALOG_VALUES.pop(_k)


# 역할 절 안 세부 카테고리 — (제목, 파일 자리 접두어들). 앞에서부터 처음 맞는 것. 안 드는 칸이 있으면 build가 멈춘다(새 칸이면 여기도).
CATEGORIES = {
    "common": (
        ("접속 — PostgreSQL·EDW·Object Storage 세부", ("common.connections",)),
        ("모델 호출 — 임베딩·LLM·VLM·전송", ("common.models.embed", "common.models.llm", "common.models.vlm", "common.models.transport")),
        ("비용·외부 가드", ("common.models.guard",)),
        ("저장소 — 실행 모드", ("common.store",)),
        ("검색 토큰 정규화", ("common.text",)),
    ),
    "extract": (
        ("원천 목록 DB(EDW 표·열 이름)", ("extract.connections.rdb",)),
        ("보안 문서", ("extract.connections.secure_doc",)),
        (
            "원천 받기·처리 상한",
            (
                "extract.source",
                "extract.prefetch_workers",
                "extract.source_limit",
                "extract.max_new",
                "extract.max_file_mb",
                "extract.skipped_log",
            ),
        ),
        ("회전 준비(prepare)", ("extract.prepare",)),
        (
            "파싱 엔진·쪽 처리",
            (
                "extract.fill_merged",
                "extract.kreuzberg_prose_filter",
                "extract.hidden_overlap_max",
                "extract.low_priority",
                "extract.doc_parallel",
                "extract.rotated_max",
                "extract.text_page_sec",
                "extract.vlm_page_sec",
                "extract.warmup_sec",
            ),
        ),
        ("OCR·표", ("extract.ocr", "extract.ocr_engine", "extract.rapidocr_page_workers", "extract.table_grid_max_rows")),
        ("첨부·중복", ("extract.attach", "extract.dedup")),
    ),
    "transform": (
        ("대표 결과", ("transform.represent",)),
        ("그림", ("transform.figures",)),
        ("VLM 호출", ("transform.vlm",)),
        ("청크·임베딩", ("transform.structure",)),
    ),
    "load": (("게시(publish)", ("load.publish", "load.edw_path_prefix")), ("적재", ("load",))),
    "search": (
        ("MCP 서버", ("search.server",)),
        ("검색 순위·방식", ("search.methods", "search.min_score", "search.weights", "search.pg")),
        ("고객 범위", ("search.client",)),
        ("EDW 도구", ("search.edw_meta", "search.edw_query")),
        ("출력·기록·파싱 프록시", ("search.output", "search.query_log", "search.parse_proxy")),
    ),
    "ops": (
        ("실행 자원 — 비우면 CPU·메모리로 자동", ("ops.runtime",)),
        ("경로", ("ops.paths", "ops.pipeline_paths")),
        ("호스트 — 컨테이너 도구·패치·정리", ("ops.host",)),
        ("서버 컨테이너 — CPU·메모리 한도·폴더", ("ops.pipeline_host", "ops.mcp_host")),
        ("상주 서비스 — 트리거·parse MCP", ("ops.services",)),
        ("새벽 배치", ("ops.nightly", "ops.nightly_run")),
        ("run_docs 레인", ("ops.run_docs",)),
    ),
    "dev": (
        ("가짜 LLM·시험 하네스", ("dev.llm_fake", "dev.pipeline")),
        ("평가", ("dev.eval", "dev.mcp")),
        ("PC 시험 Docker", ("dev.docker",)),
    ),
    "tuning": tuple((f"{sec}의 조정값", (f"tuning.{sec}",)) for sec in ("common", "extract", "transform", "load", "search", "ops")),
}
SPLIT = {"common", "extract", "transform", "load", "search"}  # [파라미터] 표시를 다는 절(결과를 바꾸는 값 — _kind 0)
_OPS = re.compile(
    r"concurrency|parallel|workers|procs|threads|timeout|_sec$|^sec$|deadline|retry|batch$|cache|_gb$|warn|port$|dir$|root|path|"
    r"file$|_bin$|url$|host$|queue|lock|log|^keep_|fetch|warm|slow|rpm|max_calls|budget|est_usd|price|token$|_mb$|max_bytes|max_chars|"
    r"^dim$|^user$|^account$|^root$|^prefix$|^bucket$|^sqlite$|^server$|^database$|^images$|^manifest$|instructions|warmup|^store$|"
    r"stale|max_new|source_limit|^limit$|^tables$|max_rows$|max_px$|parse_date|source_system|text_max|catalog|vocab_file|agg_today"
)
HYPER = {  # 이름 규칙으로는 운영값이지만 결과(파싱·청크·검색 순위)를 바꾸는 칸
    "common.models.llm.extra_body",  # 생각 켬/끔 등 — 답 글자가 바뀜
    "common.models.vlm.extra_body",
    "pipeline.extract.ocr_engine",  # 이미지·스캔 문서에 OCR 엔진도 돌림(파싱 결과가 바뀜)
    "pipeline.extract.table_grid_max_rows",
    "pipeline.extract.ocr.dpi",
    "pipeline.transform.structure.page_chunk_max",
    "pipeline.transform.vlm.fig_photo_max_tokens",
}
OPS = {  # 이름 규칙으로는 결과값이지만 운영값인 칸
    "common.models.llm.empty_retry_max",
    "common.models.transport.down_cooldown",
    "pipeline.extract.isolate_overhead",
    "mcp.server.allowed_hosts",
    "common.models.transport.transport",
    "common.models.guard.external_scope",
    "common.models.guard.external_max_docs",
    "common.models.guard.external_max_questions",
    "common.models.guard.internal_host_suffixes",
    "common.models.guard.internal_ip_ranges",
    "common.models.embed.query_cache_max",
    "common.models.transport.down_after",
    "pipeline.extract.max_file_mb",
    "pipeline.extract.input_source",
    "pipeline.extract.prepare.link",
    "pipeline.load.publish.path_map",
    "pipeline.load.publish.upload_statuses",
    "pipeline.transform.structure.embed_max_chars",
    "pipeline.transform.vlm.page_min_concurrency",
    "mcp.search.pg.filter_exact_max",
    "mcp.search.pg.vector_search",
}


def blank_matters(field):
    """빈 글자 ''를 적어야 결과가 같은 칸인가(VS7e1 R-4) — 빈 글자 유지 칸(keep)이거나, 이미지 기본값이 있어 비우면 그 기본값이 걸리는 칸(DOC_DIR 등 —
    B-2). 그 밖 칸의 ''는 비운 칸과 같은 결과라 sample 표시·migrate --compare에서 같게 본다."""
    return S.keeps_blank(field) or S.env_name(field) in _IMAGE_ENVS


def _fmt_default(f):
    d = f.default
    if S.is_secret(f) or d is None:
        return ""
    if isinstance(d, bool):
        d = "true" if d else "false"
    elif isinstance(d, list):
        d = S.render(d, sep=S.list_sep(f)) if d else "(빈 목록)"
    return f" · 기본 {d}"


# 지운 칸(모델 REMOVED — 남으면 경고만)인데 layout 표에 자리를 남긴 것 — 옛 settings.yaml(sample 복사본)이 "모르는 칸"·"자리가 다른 칸"으로
# 시작을 거부당하지 않게(11-01 pl-10 trigger 서버 — layout.py는 code_fp에 들어가 손대지 않음). 모델에 없는 칸 대조에서만 뺀다.
LAYOUT_GONE = frozenset(
    {
        "pipeline.service.trigger.token",
        "pipeline.service.trigger.client_timeout",
        "pipeline.service.trigger.queue_max",
        "pipeline.service.trigger.shutdown_timeout_sec",
        "pipeline.service.trigger.socket_timeout_sec",
        "pipeline.extract.dedup.fuzzy_max",  # 11-01(pl-02 — 유사 후보 지움)
    }
)


def build(classes=None):
    classes = classes or S.app_classes()
    rows = {}
    for cls in classes.values():
        for p, f, _ in S.walk(cls):
            rows.setdefault(p, f)
    tree = {}
    for p, f in rows.items():
        L.set_path(tree, L.to_yaml(p), (p, f))
    if {"pipeline", "mcp"} <= set(classes):  # 시험이 앱 일부로 부를 때는 대조 안 함
        unknown = (set(L.REQUIRED) | L.TUNING | set(VALUES)) - set(rows) - LAYOUT_GONE
        if unknown:
            raise SystemExit(f"sample: layout·VALUES에 모델에 없는 칸 {sorted(unknown)}")
    lines = [HEAD]
    for sec in L.SECTIONS:
        if sec not in tree:
            continue
        lines.append(f"\n# {'═' * 94}" if sec in ("common", "tuning") else "")
        if sec == "tuning":
            lines.append(
                "# tuning — 코드 상수 후보(사용자 10-30 op-08): 기본값 말고 쓴 흔적이 없는 내부 조정값·자원 세부값. 보통 비워 둔다."
            )
            lines.append(f"# {'═' * 94}")
        lines.append(f"{sec}:")
        _emit(tree[sec], 1, sec, lines, [None])
    return "\n".join(lines) + "\n"


def _cat(y):
    """파일 자리 → (카테고리 번호, 제목). required는 REQUIRED_GROUPS 순서, 그 밖은 CATEGORIES."""
    sec = y.split(".", 1)[0]
    if sec == "required":
        g = y.split(".")[1]
        i, (_k, title, where, _r) = next((i, r) for i, r in enumerate(L.REQUIRED_GROUPS) if r[0] == g)
        return i, f"{title} [{where}]"
    for i, (title, pre) in enumerate(CATEGORIES[sec]):
        if any(y == x or y.startswith(x + ".") for x in pre):
            return i, title
    raise SystemExit(f"sample: 세부 카테고리(CATEGORIES)에 안 드는 칸 {y} — CATEGORIES에 접두어를 더함")


def _emit(node, depth, path, lines, last):
    """절 안 칸을 settings.yaml 꼴로 — 세부 카테고리 순서로 놓고, 카테고리가 바뀌는 자리에 제목 주석."""
    pad = "  " * depth

    def first(y, v):
        return _cat(y)[0] if isinstance(v, tuple) else min(first(f"{y}.{k}", x) for k, x in v.items())

    order = list(L.REQUIRED.values())  # required는 표 순서, 그 밖은 카테고리 안 모델 순서(안정 정렬)
    kids = sorted(
        ((first(f"{path}.{k}", v), k, v) for k, v in node.items()),
        key=lambda r: (r[0], order.index(f"{path}.{r[1]}") if f"{path}.{r[1]}" in order else 0),
    )
    for i, name, v in kids:
        y = f"{path}.{name}"
        if last[0] != (path.split(".")[0], i):
            last[0] = (path.split(".")[0], i)
            lines.append(f"{pad}# ─── {_cat(y if isinstance(v, tuple) else _first_leaf(y, v))[1]} ───")
        if not isinstance(v, tuple):
            lines.append(f"{pad}{name}:")
            _emit(v, depth + 1, y, lines, last)
            continue
        p, f = v
        sec = y.split(".", 1)[0]
        tag = "[파라미터] " if sec in SPLIT and _kind(p, f) == 0 else "(자원) " if p in L.TUNING_RESOURCE else ""
        val = _value(p, f)
        lines.append(f"{pad}{name}:{' ' + val if val else ''}  # {tag}{_note(p, f)}")


def _first_leaf(y, node):
    k, v = min(node.items(), key=lambda kv: _cat(f"{y}.{kv[0]}" if isinstance(kv[1], tuple) else _first_leaf(f"{y}.{kv[0]}", kv[1]))[0])
    return f"{y}.{k}" if isinstance(v, tuple) else _first_leaf(f"{y}.{k}", v)


def _kind(path, f):
    """선택 칸 종류 — 0 결과를 바꾸는 값 · 1 켬/끔 · 2 운영값. 이름 규칙(_OPS)으로 가르고 틀리는 칸만 HYPER·OPS로 고친다."""
    # ponytail: 이름 규칙 분류 — sample 안내용이라 틀려도 동작과 무관, 틀린 칸은 HYPER·OPS에 더함
    if path in HYPER:
        return 0
    if S.type_label(f.annotation) == "bool":
        return 1
    if path in OPS or S.is_secret(f) or ".connections." in path or _OPS.search(path.rsplit(".", 1)[1]):
        return 2
    return 0


def _value(p, f):
    """칸에 적을 기본값(YAML 한 줄) — 비우는 칸: 필수·비밀·기본 없음·빈 글자·이미지 기본값 칸·적었는지로 동작이 갈리는 칸(SET_MATTERS)·저장소 경로가 든 기본값(만든 PC마다 달라짐)."""
    d = f.get_default(call_default_factory=True)
    if p in L.REQUIRED or S.is_secret(f) or d is None or d == "" or S.env_name(f) in _IMAGE_ENVS | SET_MATTERS:
        return ""
    if isinstance(d, str) and str(S.REPO_ROOT) in d:
        return ""
    return yaml.safe_dump(d, default_flow_style=True, allow_unicode=True, width=10**9).removesuffix("\n").removesuffix("\n...")


_IMAGE_ENVS = {k for d in S._IMAGE_DEFAULTS.values() for k in d}
# 적었는지(기본값과 구별 — given()·resources._f·model_matrix.own)로 동작이 갈리는 칸 — 기본값을 적으면 기능이 켜지거나 읽는 쪽 기본값이 밀림
# (op-05 리뷰: 모듈 포트 → 공통 포트 무시 · RDB 목록 [] → 빈 필터). 비워 둔다.
# 시험 test_sample_yaml이 코드의 given("X")·_f("X")·own("X") 이름이 여기(또는 비우는 칸)에 다 있는지 본다.
SET_MATTERS = {
    "CPU_MAX_LOAD",
    "MCP_METHODS",
    "MEM_MAX_PCT",
    "MEM_SETTLE_MARGIN",
    "MEM_SETTLE_SEC",
    "MEM_START_PCT",
    "NIGHT_WORKERS",
    "PIPE_MAX_PROCS",
    "PIPE_PROC_GB",
    "PIPE_PROCS",
    "PIPE_RESERVE_CPUS",
    "PIPE_RESERVE_GB",
    "PIPE_THREADS",
    "PIPE_WORKERS",
    "PM_BUCKET",
    "VLM_MAX_CONCURRENCY",
    "RDB_COMPANY",
    "RDB_DOC_TYPE",
    "EMBED_ALLOW_EXTERNAL",
    "LLM_ALLOW_EXTERNAL",
    "VLM_ALLOW_EXTERNAL",
}


def _note(p, f):
    """칸 주석 한 줄 — 설명(첫 마디) · 기본값 · 넣을 수 있는 값 · [비밀]. 옛 env 이름·판정 꼴은 docs/operations/env-guide.md에."""
    desc, parts = "", " ".join((f.description or "").split()).split(" — ")
    for part in parts:  # 첫 마디 — 괄호 안의 ' — '에서는 자르지 않음
        desc = f"{desc} — {part}" if desc else part
        if desc.count("(") <= desc.count(")"):
            break
    note = f"{desc}{_fmt_default(f)} · 값: {_values(p, f)}"
    return note + (" [비밀]" if S.is_secret(f) else "")


_CHOICES = re.compile(r"(?<![\w/.<])([a-z][a-z0-9_]*(?: ?\| ?[a-z][a-z0-9_:]*)+)(?![\w/])")
_PATHY = re.compile(r"(dir|root|path|file|_bin|_out|cache|log|manifest|snapshot|roster|catalog|images|conf|font|warm|jobs_dir|sqlite|db)$")


# 설명 글자로는 선택지를 못 뽑는 칸 — 코드가 받는 값(읽는 코드·설명 기준).
VALUES = {
    "common.run_env": "local·dev·prd 중 하나",
    "common.store.run_mode": "prod·test 중 하나",
    "common.text.search_recency": "0(끔)·1(최신을 묻는 질문만)·2(항상) 중 하나",
    "common.connections.object_storage.verify_tls": "1(검증)·0(끔)·CA 파일 경로",
    "common.models.guard.external_scope": "func·e2e 중 하나",
    "common.models.transport.transport": "adk·http 중 하나",
    "common.runtime.pipe_procs": "1 이상 정수 · auto 또는 비우면 자동 계산",
    "pipeline.connections.rdb.engine": "mssql·pg 중 하나",
    "pipeline.extract.prepare.ocr": "auto·v1·v3 중 하나",
    "pipeline.transform.represent.post": "all·none·쉼표 목록(vlm_page·supsub·charts·figures·context·attachments)",
    "pipeline.transform.represent.rep_select": "first·acc·best 중 하나(그 밖 값 = best)",
    "pipeline.transform.structure.embed": "api·bge-m3·e5-small·e5-base·none 중 하나",
    "pipeline.transform.structure.chunk_table": "rows 또는 비움(표 통째로)",
    "mcp.server.host": "127.0.0.1·auto(컨테이너 사설 IP)·사설 IP — 0.0.0.0은 거부",
    "mcp.search.pg.vector_search": "exact 또는 비움(HNSW 근사)",
    "common.connections.pg.db": "글자",
    "common.host.doc_src": "경로",
    "common.host.output_root": "경로",
    "common.host.pg_container": "글자(컨테이너 이름)",
}


def _values(p, f):
    """입력 가능한 값 — 형식(코드가 검증)과 설명에서 뽑은 선택지·범위(안내 — 숫자 범위는 코드가 막지 않음). 사용자 10-29."""
    # ponytail: 설명 글자에서 뽑는 규칙 — 틀린 칸은 VALUES에 적거나 설명을 고친다
    if p in VALUES:
        return VALUES[p]
    lab = S.type_label(f.annotation)
    desc = " ".join((f.description or "").split())
    leaf = p.rsplit(".", 1)[1]
    if S.is_secret(f):
        return "비밀 글자"
    if lab == "bool":
        return "true·false"
    if "포트" in lab:
        return "1~65535"
    if lab.startswith(("목록", "글자(쉼표")):
        return "쉼표 목록 또는 YAML 목록"
    if lab.startswith("JSON"):
        return "JSON 객체"
    if lab.startswith("사전"):
        return "사전(이름: 글자)"
    m = _CHOICES.search(desc)
    if m and lab.split(" | ")[0] in ("str", "float", "int"):
        return "·".join(x.strip() for x in m.group(1).split("|")) + " 중 하나"
    if lab == "str":
        if "HH:MM" in desc:
            return "HH:MM"
        if "YYYY-MM-DD" in desc:
            return "YYYY-MM-DD"
        if leaf.endswith("url") or "URL" in desc or "주소(" in desc and "호스트" not in desc:
            return "URL"
        if leaf in ("host", "server", "endpoint") or "호스트" in desc:
            return "호스트 이름·IP"
        if _PATHY.search(leaf) or "경로" in desc or "폴더" in desc:
            return "경로"
        return "글자"
    is_int = lab.startswith("int")
    if "%" in desc or leaf.endswith("_pct"):
        rng = "0~100"
    elif re.search(r"0~1|확신도|비율", desc):
        rng = "0~1"
    elif re.search(r"\(초\)|시간\(초\)|제한 시간|상한\(초\)|_sec$|timeout", desc + " " + leaf):
        rng = "0 이상 초" if not is_int else "0 이상 정수(초)"
    else:
        rng = "0 이상 정수" if is_int else "0 이상"
    z = re.search(r"0(?:이면| ?= ?| 이하면)\s*([^,·)—(]+)", desc)
    if z:
        rng += f" (0 = {z.group(1).strip()})"
    if "auto" in lab or (f.json_schema_extra or {}).get("unset") == ["auto"]:
        rng += " · auto 또는 비우면 자동 계산"
    return rng


def marks(f):
    """sample 주석에서 뺀 내부 표시(op-08 ②) — 지문 고정·빈 글자 유지·켜기 판정 꼴·auto."""
    extra = f.json_schema_extra or {}
    out = []
    if S.keeps_blank(f):
        out.append("[빈 글자 유지]")
    truth = extra.get("truth")
    if truth:
        words = "·".join(repr(x) if x == "" else x for x in (truth["on"] or truth["off"]))
        out.append(f"[{'켬' if truth['on'] else '끔'}: {words}{'' if len(truth['on'] or truth['off']) > 1 else '만'}]")
    if extra.get("unset") == ["auto"]:
        out.append("[auto = 비움]")
    elif extra.get("unset") == "nondigit":
        out.append("[숫자 아니면 비움]")
    return out


def where(names):
    """옛 env 이름 → (이름, 파일 자리, 모델 경로, 표시) — 모르는 이름은 자리 None."""
    from common.config.setarg import _fields  # 같은 이름이 호스트 칸·앱 칸 둘 다면 앱 칸(--set과 같은 규칙)

    paths = _fields()
    rows = {p: f for cls in (S.CommonAppSettings, *S.app_classes().values()) for p, f, _ in S.walk(cls)}
    out = []
    for n in names:
        p = paths.get(n, (None,))[0]
        f = rows.get(p)
        out.append((n, L.to_yaml(p) if p else None, p, marks(f) if f is not None else []))
    return out


def main(argv):
    utf8_stdout()
    if "--where" in argv:
        found = where(argv[argv.index("--where") + 1 :])
        for n, y, p, m in found:
            print(f"{n}\t{y or '(설정 칸 없음)'}" + (f"\t(모델 {p}) {' '.join(m)}".rstrip() if p else ""))
        return 0 if all(y for _, y, _, _ in found) else 1
    text = build()
    if "--check" in argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        ok = cur == text
        print(
            "settings.sample.yaml: 모델과 같음" if ok else "settings.sample.yaml: 모델과 다름 — python -m common.config.sample로 다시 만듦"
        )
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"씀: {OUT.relative_to(S.REPO_ROOT)} ({text.count(chr(10))}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
