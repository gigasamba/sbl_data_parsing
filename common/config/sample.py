"""settings.sample.yaml 만들기·대조 — 앱 설정 모델(common + pipeline + mcp 절)의 모든 칸을 코드 기본값과 함께 settings.yaml 꼴로 낸다(op-05 —
카테고리 순서, 필수·비밀 칸은 비움). 칸마다 줄 끝 주석: 설명 · 옛 env 이름 · 형식 · 기본값(비밀은 적지 않음) · 지문 고정. 칸을 더하거나 바꾸면 다시 만든다.
사용: python -m common.config.sample            # 저장소 루트 settings.sample.yaml에 씀
      python -m common.config.sample --check    # 파일이 모델과 같은지(다르면 rc 1)
"""

import re
import sys

import yaml

from common.config import settings as S
from common.core.console import utf8_stdout

OUT = S.REPO_ROOT / "settings.sample.yaml"
HEAD = """\
# settings.sample.yaml — 설정 파일 구조와 설명(값 없음). 생성: python -m common.config.sample (손으로 고치지 않음)
# 실제 파일은 이 파일을 복사해 값을 채운다 — PC: 저장소 루트 settings.yaml(RUN_ENV=local, 권한 600) · 서버: SETTINGS_FILE이 가리키는 자리
# ($SERVER_ENV_DIR/settings.yaml — 주인 UID 10001·권한 640, 컨테이너 사용자가 읽게: docs/operations/release-and-patch.md §5-4 · refactor.md C-09).
# 비운 칸(값 없음)·빈 글자 ''은 코드 기본값을 쓴다(기본값이 없는 글자 칸·[빈 글자 유지] 칸만 ''이 빈 글자 — 옛 env `X=`과 같게). 글자 칸에 쓴 yes·no·1·0은 쓴 글자 그대로.
# 켜기 칸은 true·false. 판정 꼴 표시([켬: 1만]·[끔: 0만]·[끔: ''·0·none·false])가 있는 칸은 YAML에 true·false·0·1만 — yes·on 등은
# 검증 오류(덮기 파일 overrides로 줄 때만 옛 env 판정 꼴 그대로). [auto = 비움] 칸은 auto가 "계산"(코드 기본).
# 각 앱은 common + 자기 절(pipeline 또는 mcp)만 읽는다. 비밀 칸은 출력·로그·오류 메시지에 나오지 않는다.
# 주석: 설명 · env=옛 환경변수 이름(덮기 파일 overrides·migrate가 씀 — S7e2부터 env로 준 값은 읽지 않음) · 형식 · 기본값 · [엔진 지문]/[인계 지문] =
#       그 칸을 읽는 파일이 지문에 들어가 env로도 계속 내준다(영구 다리) · [호스트] = compose·systemd·셸이 `python -m common.config.export`로 꺼내 씀.
# 덮기 파일(S7e2): 최상위 base(원본 설정 파일 경로)·overrides({옛 env 이름: 글자})만 든 yaml — 한 번 실행에 몇 칸만 바꿀 때(python -m common.config.overrides).
# 분류표: docs/refactoring/refactor_plan.md 부록 D
# [서버 옛 값: …] = 옛 옵션 카탈로그(options.conf — S7e2에 지움)·옛 서버 compose environment 기본값이 서버 컨테이너에 주던 값 — 코드 기본값과 결과가
#       다른 칸(C-39·C-45, 사용자 10-27·10-28). 서버(·PC) 설정 파일로 옮길 때 지금 동작을 지키려면 이 값을 적는다(run_mode: prod는 모든 환경 — C-43 · 빠뜨리면 PG 연결 실패 때 문서 대장·정형 저장소가 SQLite로 조용히 대체됨 — C-54).
#       ''는 빈 글자로 적어야 결과가 같은 칸(빈 글자 유지 칸·이미지 기본값이 있는 칸 — VS7e1 R-4). 옮긴 뒤 `python -m common.config.migrate --compare`로 확인.
"""
# C-39(사용자 10-27 S7e1 Q6 a) — options.conf(옛 카탈로그 — S7e2에 지움)가 env에 채우던 값 중 설정 모델 기본값과 결과가 다른 칸(값에 비밀 없음).
# output/orca/S7e1/base_calc.py로 뽑음(예외 줄 빼고 · 표기만 다른 5.0/5 빼고 · 모델 칸 없는 env 이름 빼고). sample 주석으로만 낸다(모델 기본값은 코드 기본값 그대로).
CATALOG_VALUES = {
    "AGG_TODAY": "",
    "CHUNK_TABLE": "",
    "DATA_CATALOG": "",
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
    "MCP_STORE": "",
    "PARSE_ENGINE_SCOPE": "all",
    "PARSE_POST": "all",
    "PIPE_EMBED": "",
    "RUNLOG_FILE": "",
    "RUN_MODE": "prod",
    "SECURE_DOC_PASSWORDS_FILE": "",
    "SOFFICE_BIN": "",
    "SOURCE_MANIFEST": "",
    "SOURCE_URI_PREFIX": "",
    "STRUCT_DB": "",
    "VLM_MODEL": "",
    # S7e2(사용자 10-28) — 옛 서버 compose environment 기본값(이제 settings.yaml 칸 — compose가 env로 덮지 않음). MCP_STORE는 compose가 pg로 덮었음
    "CHAIN_STRUCTURE_URL": "http://127.0.0.1:8771",
}
CATALOG_VALUES["MCP_STORE"] = "pg"
# S7e2(VS7e1 B-2) — 옛 이미지 ENV로 굽던 칸(DOC_DIR·DOC_DIR_PREPARED·PIPE_EMBED·SOFFICE_BIN)은 컨테이너에서 options.conf 값이 걸린 적이 없음(이미지 ENV가
# 먼저 있어 카탈로그 setdefault가 건너뜀) — 지금은 이미지 안 모델 기본값이 같은 값이라 표에서 뺀다(env 파일에 적은 값은 migrate가 옮김).
for _k in ("DOC_DIR", "DOC_DIR_PREPARED", "PIPE_EMBED", "SOFFICE_BIN"):
    CATALOG_VALUES.pop(_k)


# 사용자 10-29 — 입력이 필수인 칸은 맨 위에 settings.yaml 꼴로, 기본값이 있는 칸은 영역별 선택 목록으로(YAML은 같은 절을 두 번 못 써서 선택 칸은 주석 목록).
# 필수 = 비우면 시작을 거부하거나 그 기능이 꺼지는 접속·비밀·모델 주소·원천·게시 위치, 그리고 서버에서 꼭 적어야 동작이 지켜지는 칸(run_mode·mcp store — C-43·C-54).
# 칸 → 어디서 필수인가: 공통(PC·서버) · 서버(dev·prd) · PC(RUN_ENV=local). 사용자 10-29 — settings.yaml에 쓰는 칸 중 필수를 구분.
REQUIRED = {
    "common.run_env": "공통",
    **{f"common.connections.pg.{k}": "공통" for k in ("host", "port", "db", "user", "password", "db_schema")},
    "common.store.run_mode": "공통",
    **{f"common.models.embed.{k}": "공통" for k in ("base_url", "model", "api_key")},
    "common.models.guard.no_paid_calls": "PC",
    **{f"common.connections.object_storage.{k}": "서버" for k in ("endpoint", "access_key", "secret_key")},
    **{f"common.connections.rdb.{k}": "서버" for k in ("host", "database", "read.user", "read.password", "write.user", "write.password")},
    **{f"common.models.{r}.{k}": "서버" for r in ("llm", "vlm") for k in ("base_url", "model", "api_key")},
    "common.paths.doc_dir": "서버",
    "common.text.source_uri_prefix": "서버",
    "pipeline.extract.input_source": "서버",
    "pipeline.load.publish.bucket": "서버",
    "pipeline.load.publish.prefix": "서버",
    "pipeline.service.trigger.token": "서버",
    "pipeline.service.parse_mcp.token": "서버",
    "pipeline.host.image": "서버",
    **{f"mcp.server.{k}": "서버" for k in ("host", "store", "token")},
    "mcp.parse_proxy.token": "서버",
    "mcp.host.image": "서버",
}
# 선택 칸 묶음 — 앞에서부터 처음 맞는 접두어. 어느 묶음에도 안 드는 칸이 있으면 build가 멈춘다(새 절을 더하면 여기도).
GROUPS = [
    ("공통 — 접속·저장소·글자 처리", ("common.run_env", "common.connections", "common.store", "common.text")),
    ("모델 — LLM·VLM·임베딩·재순위·비용 가드", ("common.models",)),
    ("경로", ("common.paths", "pipeline.paths")),
    ("extract — 원천·준비·파싱", ("pipeline.extract", "pipeline.connections.rdb", "pipeline.connections.secure_doc")),
    ("transform — 대표 결과·그림·구조화(청킹·임베딩)", ("pipeline.transform",)),
    ("load — 적재·게시", ("pipeline.load",)),
    (
        "mcp — 검색 서버·검색 동작",
        ("mcp.server", "mcp.search", "mcp.output", "mcp.edw_meta", "mcp.edw_query", "mcp.parse_proxy", "mcp.query_log"),
    ),
    ("실행 자원·상주 서비스·새벽 배치", ("common.runtime", "pipeline.service", "pipeline.night")),
    ("호스트(compose·systemd·셸이 읽음)", ("common.host", "pipeline.host", "mcp.host")),
    ("e2e·시험·평가(PC 전용)", ("common.dev", "pipeline.dev", "pipeline.eval", "mcp.dev")),
]
SPLIT = {
    GROUPS[i][0] for i in (1, 3, 4, 5, 6)
}  # [파라미터] 표시를 다는 카테고리(결과를 바꾸는 값 — _kind 0) — 모델·extract·transform·load·mcp
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
    "mcp.search.struct_context_max",
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
    "pipeline.extract.dedup.fuzzy_max",
    "pipeline.extract.prepare.link",
    "pipeline.load.publish.path_map",
    "pipeline.load.publish.upload_statuses",
    "pipeline.transform.represent.shadow_max",
    "pipeline.transform.structure.embed_max_chars",
    "pipeline.transform.vlm.page_min_concurrency",
    "mcp.search.pg.filter_exact_max",
    "mcp.search.pg.vector_search",
}
REQ_HEAD = """\

# ══════════════════════════════════════════════════════════════════════════════════════════════
# 이 파일을 settings.yaml로 복사해 [필수] 칸과 [비밀] 칸만 채우면 시작된다(사용자 10-30 — op-05). 칸마다 [필수: 공통](PC·서버) · [필수: 서버] · [필수: PC].
#    서버 필수 칸을 PC에서 비우면 그 기능(EDW·Object Storage·RDB·게시 등)만 꺼진다. 비밀 칸은 settings.yaml에만.
# 모든 칸이 코드 기본값과 함께 들어 있다(절 common·pipeline·mcp 아래, 카테고리 제목 ─── N. … ─── 로 묶음).
#    값이 빈 칸(`칸:`) = 코드 기본값을 쓴다 — 기본값이 없거나, 비밀이거나, 이미지·PC마다 기본값이 다른 칸(DOC_DIR 등).
#    적힌 값은 코드 기본값보다 이긴다 — 나중에 코드 기본값이 바뀌어도 이 파일을 고치지(또는 sample을 다시 복사하지) 않으면 반영되지 않는다.
#    [파라미터] = 결과(파싱·청크·검색 순위)를 바꾸는 값 — 바꾸면 같은 문서에서도 결과가 달라진다(평가로 확인 뒤 바꿈). 설정 값은 code_fp에 안 들어간다.
#    줄 끝 주석: 설명 · 기본 <값> · 값: <입력 가능한 값> · env=<옛 이름> [표시]. 숫자 범위는 안내이고 코드가 막지는 않는다.
#    같은 최상위 절을 두 번 쓰지 않는다 — YAML은 뒤의 절이 앞의 절을 통째로 덮는다.
# ══════════════════════════════════════════════════════════════════════════════════════════════"""


def blank_matters(field):
    """빈 글자 ''를 적어야 결과가 같은 칸인가(VS7e1 R-4) — 빈 글자 유지 칸(keep)이거나, 이미지 기본값이 있어 비우면 그 기본값이 걸리는 칸(DOC_DIR 등 —
    B-2). 그 밖 칸의 ''는 비운 칸과 같은 결과라 sample 표시·migrate --compare에서 같게 본다."""
    return S.keeps_blank(field) or S.env_name(field) in _IMAGE_ENVS


def _fmt_default(f):
    d = f.default
    if S.is_secret(f):
        return ""
    if d is None:
        return " · 기본 없음"
    if isinstance(d, bool):
        d = "true" if d else "false"
    elif isinstance(d, list):
        d = S.render(d, sep=S.list_sep(f)) if d else "(빈 목록)"
    return f" · 기본 {d}"


def build(classes=None):
    classes = classes or S.app_classes()
    tops = {"common": None, "pipeline": None, "mcp": None}
    for cls in classes.values():
        for top in tops:
            if top in cls.model_fields and tops[top] is None:
                tops[top] = S._section_type(cls.model_fields[top].annotation)
    tops = {t: m for t, m in tops.items() if m is not None}
    rows = [(p, f) for top, model in tops.items() for p, f in _leaves(model, top)]
    known = {p for p, _ in rows}
    req = set(REQUIRED)
    if req - known and set(tops) == {"common", "pipeline", "mcp"}:  # 시험이 절 일부로 부를 때는 대조 안 함
        raise SystemExit(f"sample: REQUIRED에 모델에 없는 칸 {sorted(req - known)}")
    if set(VALUES) - known and set(tops) == {"common", "pipeline", "mcp"}:
        raise SystemExit(f"sample: VALUES에 모델에 없는 칸 {sorted(set(VALUES) - known)}")
    gidx = {}
    for p, _ in rows:
        g = next((i for i, (_, pre) in enumerate(GROUPS) if any(p == x or p.startswith(x + ".") for x in pre)), None)
        if g is None:
            raise SystemExit(f"sample: 카테고리(GROUPS)에 안 드는 칸 {p} — GROUPS에 접두어를 더함")
        gidx[p] = g
    lines = [HEAD, REQ_HEAD]
    for top, model in tops.items():
        lines.append(f"\n{top}:")
        _emit(model, 1, top, lines, gidx, [None])
    return "\n".join(lines) + "\n"


def _leaves(model, path):
    for name, f in model.model_fields.items():
        sub = S._section_type(f.annotation)
        if sub is None:
            yield f"{path}.{name}", f
        else:
            yield from _leaves(sub, f"{path}.{name}")


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


def _emit(model, depth, path, lines, gidx, last):
    """절 안 칸을 settings.yaml 꼴로 — 카테고리(GROUPS) 순서로 놓고, 카테고리가 바뀌는 자리에 제목 주석(op-05)."""
    pad = "  " * depth
    kids = []
    for name, f in model.model_fields.items():
        p = f"{path}.{name}"
        sub = S._section_type(f.annotation)
        g = gidx[p] if sub is None else min(v for k, v in gidx.items() if k.startswith(p + "."))
        kids.append((g, name, p, f, sub))
    for g, name, p, f, sub in sorted(kids, key=lambda k: k[0]):  # sorted는 안정 — 같은 카테고리 안은 모델 순서
        if last[0] != g:
            last[0] = g
            lines.append(f"{pad}# ─── {g + 1}. {GROUPS[g][0]} ───")
        if sub is not None:
            lines.append(f"{pad}{name}:")
            _emit(sub, depth + 1, p, lines, gidx, last)
            continue
        tag = f"[필수: {REQUIRED[p]}] " if p in REQUIRED else "[파라미터] " if GROUPS[g][0] in SPLIT and _kind(p, f) == 0 else ""
        val = _value(p, f)
        lines.append(f"{pad}{name}:{' ' + val if val else ''}  # {tag}{_note(p, f)}")


def _value(p, f):
    """칸에 적을 기본값(YAML 한 줄) — 비우는 칸: 필수·비밀·기본 없음·빈 글자·이미지 기본값 칸·적었는지로 동작이 갈리는 칸(SET_MATTERS·pinned)·저장소 경로가 든 기본값(만든 PC마다 달라짐)."""
    d = f.get_default(call_default_factory=True)
    if p in REQUIRED or S.is_secret(f) or d is None or d == "" or S.env_name(f) in _IMAGE_ENVS | SET_MATTERS:
        return ""
    if (f.json_schema_extra or {}).get("pinned"):  # pin_env가 적힌 칸만 env로 냄 — 적으면 자식 프로세스의 자기 설정 값을 덮음
        return ""
    if isinstance(d, str) and str(S.REPO_ROOT) in d:
        return ""
    return yaml.safe_dump(d, default_flow_style=True, allow_unicode=True, width=10**9).removesuffix("\n").removesuffix("\n...")


_IMAGE_ENVS = {k for d in S._IMAGE_DEFAULTS.values() for k in d}
# 적었는지(기본값과 구별 — given()·resources._f·model_matrix.own)로 동작이 갈리는 칸 — 기본값을 적으면 기능이 켜지거나 읽는 쪽 기본값이 밀림
# (op-05 리뷰: STRUCT_BACKEND=pg → 정형 저장소 켬 · 모듈 포트 → 공통 포트 무시 · RDB 목록 [] → 빈 필터). 비워 둔다.
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
    "STRUCT_BACKEND",
    "STRUCT_DB",
    "TRIGGER_PARSE_PORT",
    "TRIGGER_STRUCTURE_PORT",
    "VLM_MAX_CONCURRENCY",
    "RDB_COMPANY",
    "RDB_DOC_TYPE",
    "EMBED_ALLOW_EXTERNAL",
    "LLM_ALLOW_EXTERNAL",
    "VLM_ALLOW_EXTERNAL",
}


def _note(p, f):
    """칸 주석 — 설명 · env · 형식 · 기본값 · 표시(옛 _emit 본문 그대로)."""
    tags = []
    extra = f.json_schema_extra or {}
    if extra.get("pinned"):
        tags.append("[엔진 지문]" if extra["pinned"] == "engine" else "[인계 지문]")
    if S.is_host(p):
        tags.append("[호스트]")
    if S.is_secret(f):
        tags.append("[비밀]")
    if S.keeps_blank(f):
        tags.append("[빈 글자 유지]")
    truth = extra.get("truth")
    if truth:
        words = "·".join(repr(x) if x == "" else x for x in (truth["on"] or truth["off"]))
        tags.append(f"[{'켬' if truth['on'] else '끔'}: {words}{'' if len(truth['on'] or truth['off']) > 1 else '만'}]")
    if extra.get("unset") == ["auto"]:
        tags.append("[auto = 비움]")
    elif extra.get("unset") == "nondigit":
        tags.append("[숫자 아니면 비움]")
    env = S.env_name(f)
    if env in CATALOG_VALUES and (CATALOG_VALUES[env] or blank_matters(f)):
        v = CATALOG_VALUES[env]
        tags.append(f"[서버 옛 값: {v if v else repr('')}]")
    note = f"{' '.join((f.description or '').split())}{_fmt_default(f)} · 값: {_values(p, f)} · env={env}"
    return f"{note}{(' ' + ' '.join(tags)) if tags else ''}"


_CHOICES = re.compile(r"(?<![\w/.<])([a-z][a-z0-9_]*(?: ?\| ?[a-z][a-z0-9_:]*)+)(?![\w/])")
_PATHY = re.compile(r"(dir|root|path|file|_bin|_out|cache|log|manifest|snapshot|roster|catalog|images|conf|font|warm|jobs_dir|sqlite|db)$")


# 설명 글자로는 선택지를 못 뽑는 칸 — 코드가 받는 값(읽는 코드·설명 기준).
VALUES = {
    "common.run_env": "local·dev·prd 중 하나",
    "common.store.run_mode": "prod·test 중 하나",
    "common.store.struct_backend": "pg·sqlite·tsql 중 하나",
    "common.text.search_recency": "0(끔)·1(최신을 묻는 질문만)·2(항상) 중 하나",
    "common.connections.object_storage.verify_tls": "1(검증)·0(끔)·CA 파일 경로",
    "common.models.guard.external_scope": "func·e2e 중 하나",
    "common.models.transport.transport": "adk·http 중 하나",
    "common.runtime.pipe_procs": "1 이상 정수 · auto 또는 비우면 자동 계산",
    "pipeline.connections.rdb.engine": "mssql·pg 중 하나",
    "pipeline.extract.engine_scope": "stack·all 중 하나",
    "pipeline.extract.prepare.ocr": "auto·v1·v3 중 하나",
    "pipeline.transform.represent.post": "all·none·쉼표 목록(vlm_page·supsub·charts·figures·context·attachments)",
    "pipeline.transform.represent.rep_select": "first·acc·best 중 하나(그 밖 값 = best)",
    "pipeline.transform.structure.embed": "api·bge-m3·e5-small·e5-base·none 중 하나",
    "pipeline.transform.structure.chunk_table": "rows 또는 비움(표 통째로)",
    "mcp.server.host": "127.0.0.1·auto(컨테이너 사설 IP)·사설 IP — 0.0.0.0은 거부",
    "mcp.server.store": "pg·local 중 하나 또는 비움(자동 탐지)",
    "mcp.search.pg.vector_search": "exact 또는 비움(HNSW 근사)",
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


def main(argv):
    utf8_stdout()
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
