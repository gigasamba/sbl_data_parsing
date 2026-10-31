"""settings.yaml 배치(op-08 ②) — 파일의 칸 자리(YAML 경로) ↔ 설정 모델의 칸 경로(common.* · pipeline.* · mcp.*).
파일은 `required`(운영자가 꼭 채울 값) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(코드 상수 후보) 순서다.
코드는 모델 경로(`cfg().extract.ocr.dpi` 등)를 그대로 쓰고, read_settings()가 파일을 읽은 직후 to_model()로 모델 배치로 바꾼다.
  · required: 칸마다 자리를 적은 표(REQUIRED). tuning: 모델 경로 모음(TUNING) — 자리는 `tuning.` + 역할 자리.
  · 그 밖: 접두어 규칙(ROLES — 모델 접두 → 파일 접두, 1:1). 사전 값 칸(lib_env·extra_body 등)도 접두어로 그대로 옮겨진다.
  · 모델을 모르고도 바꾼다(표준 라이브러리만) — 이미지에 없는 앱의 칸도 자리만 옮기고, 검증은 그 앱 설정 객체가 한다(U-a).
옛 배치(최상위 common·pipeline·mcp — op-08 전)는 거부하고 `python -m common.config.migrate <옛 settings.yaml>`로 바꾸게 안내한다.
"""

# 파일 최상위 절 — 이 순서로 sample에 낸다.
SECTIONS = ("required", "common", "extract", "transform", "load", "search", "ops", "dev", "tuning")
MIGRATE_HINT = "python -m common.config.migrate <옛 settings.yaml> --out <새 파일>"

# required — (카테고리 열쇠, 제목, 쓰는 곳 표시, [(칸 이름, 모델 경로)]). 표시는 카테고리 제목에 한 번(사용자 10-30 op-08).
REQUIRED_GROUPS = (
    ("env", "실행 환경", "PC·서버", (("run_env", "common.run_env"), ("run_mode", "common.store.run_mode"))),
    (
        "pg",
        "PostgreSQL(pgvector · gold)",
        "PC·서버",
        tuple((k, f"common.connections.pg.{k}") for k in ("host", "port", "db", "user", "password", "db_schema")),
    ),
    ("embed", "임베딩 모델", "PC·서버", tuple((k, f"common.models.embed.{k}") for k in ("base_url", "model", "api_key"))),
    (
        "edw",
        "EDW(회사 DB)",
        "서버만",
        (
            ("host", "common.connections.rdb.host"),
            ("database", "common.connections.rdb.database"),
            ("read_user", "common.connections.rdb.read.user"),
            ("read_password", "common.connections.rdb.read.password"),
            ("write_user", "common.connections.rdb.write.user"),
            ("write_password", "common.connections.rdb.write.password"),
        ),
    ),
    (
        "object_storage",
        "Object Storage",
        "서버만",
        tuple((k, f"common.connections.object_storage.{k}") for k in ("endpoint", "access_key", "secret_key")),
    ),
    (
        "models",
        "LLM·VLM 모델",
        "서버만",
        tuple((f"{r}_{k}", f"common.models.{r}.{k}") for r in ("llm", "vlm") for k in ("base_url", "model", "api_key")),
    ),
    (
        "source",
        "원천·게시 위치",
        "서버만",
        (
            ("input_source", "pipeline.extract.input_source"),
            ("source_bucket", "pipeline.connections.rdb.bucket"),
            ("source_uri_prefix", "common.text.source_uri_prefix"),
            ("publish_bucket", "pipeline.load.publish.bucket"),
            ("publish_prefix", "pipeline.load.publish.prefix"),
        ),
    ),
    (
        "tokens",
        "서비스 토큰",
        "서버만",
        (
            ("trigger", "pipeline.service.trigger.token"),
            ("parse_mcp", "pipeline.service.parse_mcp.token"),
            ("mcp", "mcp.server.token"),
            ("parse_proxy", "mcp.parse_proxy.token"),
        ),
    ),
    (
        "deploy",
        "서버 배포(이미지·호스트 폴더)",
        "서버만",
        (
            ("pipeline_image", "pipeline.host.image"),
            ("mcp_image", "mcp.host.image"),
            ("doc_src", "common.host.doc_src"),
            ("output_root", "common.host.output_root"),
            ("pg_container", "common.host.pg_container"),
            ("mcp_store", "mcp.server.store"),
        ),
    ),
)
REQUIRED = {m: f"required.{g}.{k}" for g, _t, _w, rows in REQUIRED_GROUPS for k, m in rows}

# 역할 절 — (모델 접두, 파일 접두). 긴 접두가 먼저 맞는다. 파일 접두도 서로 1:1(거꾸로 바꿀 때 가장 긴 파일 접두).
ROLES = (
    ("common.runtime.", "ops.runtime."),
    ("common.paths.", "ops.paths."),
    ("common.host.", "ops.host."),
    ("common.dev.", "dev."),
    ("common.", "common."),
    ("pipeline.extract.", "extract."),
    ("pipeline.connections.", "extract.connections."),
    ("pipeline.transform.", "transform."),
    ("pipeline.load.", "load."),
    ("pipeline.paths.", "ops.pipeline_paths."),
    ("pipeline.host.nightly.", "ops.nightly."),
    ("pipeline.host.run_docs.", "ops.run_docs."),
    ("pipeline.host.", "ops.pipeline_host."),
    ("pipeline.night.", "ops.nightly_run."),
    ("pipeline.service.", "ops.services."),
    ("pipeline.dev.", "dev.pipeline."),
    ("pipeline.eval.", "dev.eval."),
    ("mcp.search.", "search."),
    ("mcp.server.", "search.server."),
    ("mcp.edw_meta.", "search.edw_meta."),
    ("mcp.edw_query.", "search.edw_query."),
    ("mcp.output.", "search.output."),
    ("mcp.parse_proxy.", "search.parse_proxy."),
    ("mcp.query_log.", "search.query_log."),
    ("mcp.host.", "ops.mcp_host."),
    ("mcp.dev.", "dev.mcp."),
)

# tuning — 코드 상수 후보(사용자 10-30 op-08 4차): 기본값 말고 다른 값을 쓴 흔적이 없는 운영 값. 상수로 내릴지는 나중에 정한다.
TUNING_INTERNAL = (  # 내부 조정값 — 재시도·내부 대기·묶음 크기·출력 상한
    "common.models.embed.query_cache_max",
    "common.models.llm.empty_retry_max",
    "common.models.vlm.retry",
    "common.models.transport.connect_timeout",
    "common.models.transport.down_after",
    "common.models.transport.down_cooldown",
    "common.models.transport.ping_timeout",
    "common.text.draft_terms_max",
    "common.runtime.draft_terms_lock_timeout",
    "pipeline.extract.attach.max_mb",
    "pipeline.extract.cache.parse_cache_max_gb",
    "pipeline.extract.dedup.fuzzy_max",
    "pipeline.extract.engine_retry",
    "pipeline.extract.isolate_overhead",
    "pipeline.transform.figures.ocr_parallel",
    "pipeline.transform.figures.pptx_convert_sec",
    "pipeline.transform.structure.embed_batch",
    "pipeline.transform.structure.embed_max_chars",
    "pipeline.transform.structure.embed_retry",
    "pipeline.load.index_lock_stale_sec",
    "pipeline.service.parse_mcp.job_timeout_sec",
    "pipeline.service.parse_mcp.queue_max",
    "pipeline.service.parse_mcp.text_page_sec",
    "pipeline.service.parse_mcp.vlm_page_sec",
    "pipeline.service.parse_mcp.warmup_sec",
    "pipeline.service.trigger.client_timeout",
    "pipeline.service.trigger.queue_max",
    "pipeline.service.trigger.shutdown_timeout_sec",
    "pipeline.service.trigger.socket_timeout_sec",
    "mcp.server.reload_check_sec",
    "mcp.server.tool_timeout_sec",
    "mcp.edw_meta.max_bytes",
    "mcp.edw_query.max_bytes",
    "mcp.edw_query.timeout_sec",
    "mcp.search.pg.filter_exact_max",
    "mcp.output.max_chars",
)
TUNING_RESOURCE = (  # 자원·대기·병렬 세부값 — 자동 계산 내부 계수와 호출 제한 시간·병렬
    "common.runtime.mem_max_pct",
    "common.runtime.mem_settle_margin",
    "common.runtime.mem_settle_sec",
    "common.runtime.mem_start_pct",
    "common.runtime.pipe_max_procs",
    "common.runtime.pipe_proc_gb",
    "common.runtime.pipe_reserve_gb",
    "common.runtime.pipe_reserve_cpus",
    "common.runtime.pipe_threads",
    "common.runtime.cpu_max_load",
    "common.models.llm.timeout",
    "common.models.embed.timeout",
    "pipeline.extract.attach.timeout",
    "pipeline.transform.vlm.deadline",
    "pipeline.transform.vlm.page_concurrency",
    "pipeline.transform.vlm.page_min_concurrency",
    "pipeline.transform.figures.vlm_parallel",
    "pipeline.night.vlm_concurrency",
    "pipeline.night.workers",
    "pipeline.service.parse_mcp.procs",
)
TUNING = frozenset(TUNING_INTERNAL + TUNING_RESOURCE)


class LayoutError(ValueError):
    """파일 배치 오류 — 메시지에는 칸 자리만(값 없음)."""


DUP_KEY = "같은 칸 두 번"


def reject_dup_keys(loader_cls):
    """YAML Loader 클래스가 같은 절·칸을 두 번 쓴 파일을 거부하게(앞 것이 조용히 사라지므로 — 값은 안 찍음). 앱(settings)·호스트(run_docs)가 같이 쓴다."""
    import yaml

    def no_dup(loader, node):  # 글자 열쇠만 견줌(병합 `<<`·사전 열쇠는 construct_mapping이 처리 — 못 쓰는 열쇠도 YAML 오류로)
        seen = set()
        for k, _ in node.value:
            if isinstance(k, yaml.ScalarNode) and k.tag != "tag:yaml.org,2002:merge":
                if k.value in seen:
                    raise yaml.constructor.ConstructorError(None, None, f"{DUP_KEY}: {k.value}", k.start_mark)
                seen.add(k.value)
        return loader.construct_mapping(node)

    loader_cls.add_constructor("tag:yaml.org,2002:map", no_dup)
    return loader_cls


def _role(model_path):
    for m, y in ROLES:
        if model_path.startswith(m):
            return y + model_path[len(m) :]
    raise LayoutError(f"역할 절 규칙에 없는 모델 칸: {model_path}")


def to_yaml(model_path):
    """모델 경로 → 파일 자리."""
    if model_path in REQUIRED:
        return REQUIRED[model_path]
    if model_path in TUNING:
        return "tuning." + _role(model_path)
    return _role(model_path)


_REQ_BACK = {y: m for m, y in REQUIRED.items()}
_ROLES_BACK = sorted(((y, m) for m, y in ROLES), key=lambda r: -len(r[0]))


def to_model_path(yaml_path):
    """파일 자리 → 모델 경로. 모르는 절·required/tuning에 없는 칸이면 None. 자리가 바뀐 칸(다른 절에 있어야 함)도 그대로 돌려준다 —
    판정은 to_model이(to_yaml로 되돌려 견줌)."""
    if yaml_path in _REQ_BACK:
        return _REQ_BACK[yaml_path]
    rest = yaml_path.removeprefix("tuning.")
    for y, m in _ROLES_BACK:
        if rest.startswith(y):
            return m + rest[len(y) :]
    return None


def set_path(doc, path, value):
    """점 경로 자리에 값을 넣는다(중간 사전은 만들고, 사전이 아닌 값은 사전으로 바꿈)."""
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = cur[p] = {}
        cur = nxt
    cur[parts[-1]] = value


def _leaves(doc, prefix=""):
    """(자리, 값) — 사전은 끝까지 내려간다(사전 값 칸도 접두어 규칙상 자리가 그대로 옮겨짐)."""
    for k, v in doc.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            yield from _leaves(v, p + ".")
        else:
            yield p, v


def is_old(doc):
    """옛 배치(op-08 전 — 최상위 pipeline·mcp, 또는 common 아래 run_env·paths·runtime·host·dev)인가."""
    if not isinstance(doc, dict):
        return False
    common = doc.get("common")
    return bool({"pipeline", "mcp"} & set(doc)) or (
        isinstance(common, dict) and bool({"run_env", "paths", "runtime", "host", "dev"} & set(common))
    )


def to_model(doc, source=""):
    """파일 사전(새 배치) → 모델 배치 사전. 옛 배치·모르는 절·자리가 바뀐 칸이면 LayoutError(칸 자리만, 값 없음)."""
    if not doc:
        return {}
    where = f": {source}" if source else ""
    if is_old(doc):
        raise LayoutError(f"옛 설정 배치(최상위 common·pipeline·mcp — op-08 전)는 읽지 않음 — {MIGRATE_HINT}로 바꿈{where}")
    unknown = sorted(set(doc) - set(SECTIONS))
    if unknown:
        raise LayoutError(f"설정 파일에 모르는 최상위 절 {unknown} — {'·'.join(SECTIONS)}만(덮기 파일은 base·overrides){where}")
    out, bad, moved = {}, [], []
    for y, v in _leaves(doc):
        m = to_model_path(y)
        if m is None:
            if v not in (None, {}):
                bad.append(y)
            continue  # 빈 절 머리(`extract:`)
        want = to_yaml(m)
        if want != y:
            moved.append(f"{y} → {want}")
            continue
        set_path(out, m, v)
    if moved:
        raise LayoutError(f"자리가 다른 칸 {len(moved)}개: {', '.join(moved)} — 옛 배치면 {MIGRATE_HINT}{where}")
    if bad:
        raise LayoutError(f"모르는 칸 {len(bad)}개: {', '.join(bad)}{where}")
    return out


def to_file(model_doc):
    """모델 배치 사전 → 파일 사전(새 배치, SECTIONS 순서). migrate·시험이 쓴다."""
    out = {}
    for p, v in _leaves(model_doc or {}):
        set_path(out, to_yaml(p), v)
    return {s: out[s] for s in SECTIONS if s in out}
