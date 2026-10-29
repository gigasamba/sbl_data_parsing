"""settings.sample.yaml 만들기·대조 — 앱 설정 모델(common + pipeline + mcp 절)에서 절·칸 구조와 설명만 뽑는다(값은 비움, S7a · D-015).
칸마다 주석: 설명 · 옛 env 이름 · 형식 · 기본값(비밀은 적지 않음) · 지문 고정. 칸을 더하거나 바꾸면 다시 만든다.
사용: python -m common.config.sample            # 저장소 루트 settings.sample.yaml에 씀
      python -m common.config.sample --check    # 파일이 모델과 같은지(다르면 rc 1)
"""

import re
import sys

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
    "EDW_CONN_FILE": "",
    "EDW_PATH_PREFIX": "",
    "EDW_QUERY_CONN_FILE": "",
    "EDW_QUERY_MAX_ROWS": "1000",
    "EDW_QUERY_SQLITE": "",
    "EDW_QUERY_TABLES": "",
    "EMBED_MODEL": "",
    "EMBED_QUERY_CACHE": "",
    "EMBED_QUERY_PREFIX": "",
    "INDEX_CONF": "",
    "LLM_EST_OUT_TOKENS": "1200",
    "LLM_MODEL": "",
    "LLM_SPEND_FILE": "",
    "MCP_BUNDLE": "",
    "MCP_STORE": "",
    "OV_PROCESSING_MODE": "",
    "OV_ROOT": "",
    "PADDLE_PYTHON": "",
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
REQUIRED = {
    "common.run_env",
    *(f"common.connections.pg.{k}" for k in ("host", "port", "db", "user", "password", "db_schema")),
    *(f"common.connections.edw.{k}" for k in ("server", "database", "user", "password")),
    *(f"common.connections.object_storage.{k}" for k in ("endpoint", "access_key", "secret_key")),
    *(f"common.connections.parsing_meta.{k}" for k in ("host", "database", "user", "password")),
    *(f"common.models.{r}.{k}" for r in ("llm", "vlm", "embed") for k in ("base_url", "model", "api_key")),
    "common.models.guard.no_paid_calls",
    "common.paths.config_dir",
    "common.paths.doc_dir",
    "common.text.source_uri_prefix",
    "common.store.run_mode",
    *(f"pipeline.connections.rdb.{k}" for k in ("host", "database", "user", "password")),
    "pipeline.extract.input_source",
    "pipeline.load.publish.bucket",
    "pipeline.load.publish.prefix",
    "pipeline.service.trigger.token",
    "pipeline.service.parse_mcp.token",
    "pipeline.host.image",
    *(f"mcp.server.{k}" for k in ("host", "store", "token")),
    *(f"mcp.edw_query.{k}" for k in ("server", "database", "user", "password")),
    "mcp.parse_proxy.token",
    "mcp.host.image",
}
# 선택 칸 묶음 — 앞에서부터 처음 맞는 접두어. 어느 묶음에도 안 드는 칸이 있으면 build가 멈춘다(새 절을 더하면 여기도).
GROUPS = [
    ("공통 — 접속·저장소·글자 처리", ("common.run_env", "common.connections", "common.store", "common.text")),
    ("모델 — LLM·VLM·임베딩·재순위·비용 가드", ("common.models",)),
    ("경로", ("common.paths", "pipeline.paths")),
    ("extract — 원천·준비·파싱", ("pipeline.extract", "pipeline.connections.rdb", "pipeline.connections.secure_doc")),
    ("transform — 대표 결과·그림·구조화(청킹·임베딩)", ("pipeline.transform",)),
    ("load — 적재·게시·OpenViking", ("pipeline.load", "pipeline.connections.openviking")),
    (
        "mcp — 검색 서버·검색 동작",
        ("mcp.server", "mcp.search", "mcp.output", "mcp.edw_meta", "mcp.edw_query", "mcp.parse_proxy", "mcp.query_log"),
    ),
    ("실행 자원·상주 서비스·새벽 배치", ("common.runtime", "pipeline.service", "pipeline.night")),
    ("호스트(compose·systemd·셸이 읽음)", ("common.host", "pipeline.host", "mcp.host")),
    ("e2e·시험·평가(PC 전용)", ("common.dev", "pipeline.dev", "pipeline.eval", "mcp.dev", "pipeline.connections.graphiti")),
]
SPLIT = {GROUPS[i][0] for i in (1, 3, 4, 5, 6)}  # 종류(KINDS)로 한 번 더 나누는 묶음 — 모델·extract·transform·load·mcp
KINDS = ("결과를 바꾸는 값(하이퍼파라미터)", "기능 켬/끔", "운영값(동시성·시간·용량·경로·접속)")
_OPS = re.compile(
    r"concurrency|parallel|workers|procs|threads|timeout|_sec$|^sec$|deadline|retry|batch$|cache|_gb$|warn|port$|dir$|root|path|"
    r"file$|_bin$|url$|host$|queue|lock|log|^keep_|fetch|warm|slow|rpm|max_calls|budget|est_usd|price|token$|_mb$|max_bytes|max_chars|"
    r"^dim$|^user$|^account$|^root$|^prefix$|^bucket$|^sqlite$|^server$|^database$|^images$|^manifest$|instructions|warmup|^store$|"
    r"stale|max_new|source_limit|^limit$|^tables$|max_rows$|max_px$|parse_date|source_system|text_max|catalog|vocab_file|agg_today"
)
HYPER = {  # 이름 규칙으로는 운영값이지만 결과(파싱·청크·검색 순위)를 바꾸는 칸
    "common.models.llm.extra_body",  # 생각 켬/끔 등 — 답 글자가 바뀜
    "common.models.vlm.extra_body",
    "pipeline.extract.phases",  # 3r = 성공 엔진 없는 문서만 VLM
    "pipeline.extract.table_grid_max_rows",
    "pipeline.extract.ocr.dpi",
    "pipeline.transform.represent.reread.dpi",
    "pipeline.transform.structure.page_chunk_max",
    "pipeline.transform.vlm.fig_photo_max_tokens",
    "pipeline.transform.represent.reread.vlm_max_tokens",
    "mcp.search.ocr_dpi",
    "mcp.search.rerank.max_chars",
    "mcp.search.struct_context_max",
}
OPS = {  # 이름 규칙으로는 결과값이지만 운영값인 칸
    "common.models.llm.empty_retry_max",
    "common.models.guard.synthetic_truth",
    "common.models.transport.down_cooldown",
    "pipeline.extract.isolate_overhead",
    "mcp.output.max_image_px",
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
    "pipeline.extract.phase_sec",
    "pipeline.extract.input_source",
    "pipeline.extract.dedup.fuzzy_max",
    "pipeline.extract.prepare.link",
    "pipeline.load.prune_min_ratio",
    "pipeline.load.structure_target",
    "pipeline.load.publish.path_map",
    "pipeline.load.publish.upload_statuses",
    "pipeline.transform.agent.max_docs",
    "pipeline.transform.agent.tokens",
    "pipeline.transform.represent.shadow_max",
    "pipeline.transform.structure.embed_max_chars",
    "pipeline.transform.vlm.page_min_concurrency",
    "pipeline.connections.openviking.processing_mode",
    "pipeline.connections.openviking.args_json",
    "mcp.search.ov_search_path",
    "mcp.search.pg.filter_exact_max",
    "mcp.search.pg.vector_search",
    "mcp.search.agg.llm_timeout",
}
REQ_HEAD = """\

# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. 필수 입력 — 이 블록을 settings.yaml로 복사해 값을 채운다(비우면 시작 거부·그 기능 꺼짐·서버 동작이 바뀜).
#    PC에서 쓰지 않는 접속(EDW·Object Storage·RDB 등)은 비워 둔다 — 그 기능만 꺼진다.
# ══════════════════════════════════════════════════════════════════════════════════════════════"""
OPT_HEAD = """\

# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. 선택 — 기본값이 있어 비워 두면 된다. 바꿀 칸만 위 1의 같은 절(common·pipeline·mcp) 아래 같은 자리에 넣는다
#    (예: pipeline.transform.structure.chunk_size → pipeline: / transform: / structure: / chunk_size: 900).
#    같은 최상위 절(common·pipeline·mcp)을 두 번 쓰지 않는다 — YAML은 뒤의 절이 앞의 절을 통째로 덮는다.
#    모델·extract·transform·load·mcp 묶음은 [결과를 바꾸는 값]·[기능 켬/끔]·[운영값]으로 한 번 더 나눴다
#    — [결과를 바꾸는 값]·[기능 켬/끔]을 바꾸면 같은 문서에서도 파싱·청크·검색 결과가 달라진다(평가로 확인 뒤 바꿈).
# ══════════════════════════════════════════════════════════════════════════════════════════════"""


def blank_matters(field):
    """빈 글자 ''를 적어야 결과가 같은 칸인가(VS7e1 R-4) — 빈 글자 유지 칸(keep)이거나, 이미지 기본값이 있어 비우면 그 기본값이 걸리는 칸(DOC_DIR 등 —
    B-2). 그 밖 칸의 ''는 비운 칸과 같은 결과라 sample 표시·migrate --compare에서 같게 본다."""
    return S.keeps_blank(field) or S.env_name(field) in {k for d in S._IMAGE_DEFAULTS.values() for k in d}


def _fmt_default(f):
    d = f.default
    if S.is_secret(f) or d is None:
        return ""
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
    if REQUIRED - known and set(tops) == {"common", "pipeline", "mcp"}:  # 시험이 절 일부로 부를 때는 대조 안 함
        raise SystemExit(f"sample: REQUIRED에 모델에 없는 칸 {sorted(REQUIRED - known)}")
    lines = [HEAD, REQ_HEAD]
    for top, model in tops.items():
        if any(p.startswith(top + ".") for p in REQUIRED & known):
            lines.append(f"\n{top}:")
            _emit(model, 1, top, lines)
    lines.append(OPT_HEAD)
    groups = {name: [] for name, _ in GROUPS}
    for p, f in rows:
        if p in REQUIRED:
            continue
        g = next((name for name, pre in GROUPS if any(p == x or p.startswith(x + ".") for x in pre)), None)
        if g is None:
            raise SystemExit(f"sample: 선택 묶음(GROUPS)에 안 드는 칸 {p} — GROUPS에 접두어를 더함")
        groups[g].append((p, f))
    for i, (name, items) in enumerate(((n, v) for n, v in groups.items() if v), 1):
        lines.append(f"\n# ─── 2-{i}. {name} ({len(items)}칸) ───")
        if name not in SPLIT:
            lines += [f"#   {p}:  # {_note(p, f)}" for p, f in items]
            continue
        for k, label in enumerate(KINDS):
            part = [(p, f) for p, f in items if _kind(p, f) == k]
            if part:
                lines.append(f"#  [{label}]")
                lines += [f"#   {p}:  # {_note(p, f)}" for p, f in part]
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


def _emit(model, depth, path, lines):
    """필수 칸만 settings.yaml 꼴(절 안 칸)로 — 필수 칸이 없는 절은 건너뜀."""
    pad = "  " * depth
    for name, f in model.model_fields.items():
        p = f"{path}.{name}"
        sub = S._section_type(f.annotation)
        if sub is None:
            if p in REQUIRED:
                lines.append(f"{pad}{name}:  # {_note(p, f)}")
        elif any(r.startswith(p + ".") for r in REQUIRED):
            lines.append(f"{pad}{name}:")
            _emit(sub, depth + 1, p, lines)


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
    note = f"{' '.join((f.description or '').split())} · env={env} · {S.type_label(f.annotation)}{_fmt_default(f)}"
    return f"{note}{(' ' + ' '.join(tags)) if tags else ''}"


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
