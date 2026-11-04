"""settings.yaml 배치 — 파일의 칸 자리(YAML 경로) ↔ 설정 모델의 칸 경로(common.* · pipeline.* · mcp.*).
파일은 `required`(운영자가 꼭 채울 값) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`(환경마다 운영자가 정하는 값) →
`tuning`(거의 안 바꾸는 값 — 분류별) → `dev`(PC 전용 — 서버는 비워 둠) 순서다.
코드는 모델 경로(`cfg().extract.ocr.dpi` 등)를 그대로 쓰고, read_settings()가 파일을 읽은 직후 to_model()로 모델 배치로 바꾼다.
  · required: 칸마다 자리를 적은 표(REQUIRED). tuning: 모델 경로 모음(TUNING) — 자리는 `tuning.` + 역할 자리.
  · PC 전용 칸(LOCAL): 자리는 `dev.` + 역할 자리(앞 `common.` 뺌).
  · 그 밖: 접두어 규칙(ROLES — 모델 접두 → 파일 접두, 1:1).
  · 모델을 모르고도 바꾼다(표준 라이브러리만 — 호스트 스크립트도 이 파일을 읽음). 검증은 앱 설정 객체가 한다.
모르는 절·모르는 칸·자리가 다른 칸은 시작 거부(칸 자리만 알림, 값은 출력 안 함).
"""

# 파일 최상위 절 — 이 순서로 sample에 낸다.
SECTIONS = ("required", "common", "extract", "transform", "load", "search", "ops", "tuning", "dev")

# required — (카테고리 열쇠, 제목, 쓰는 곳 표시, [(칸 이름, 모델 경로)]). 표시는 카테고리 제목에 한 번(사용자 10-30 op-08).
REQUIRED_GROUPS = (
    ("env", "실행 환경", "PC·서버", (("run_env", "common.run_env"),)),
    (
        "pg",
        "PostgreSQL(pgvector · gold)",
        "PC·서버",
        tuple((k, f"common.connections.pg.{k}") for k in ("host", "port", "db", "user", "password", "db_schema")),
    ),
    ("embed", "임베딩 모델", "PC·서버", tuple((k, f"common.models.embed.{k}") for k in ("base_url", "model", "api_key"))),
    (
        "edw",
        "EDW(회사 DB) — ParsingMeta 표·접속",
        "서버: 접속 칸 · PC: sqlite 하나",
        (
            ("parsing_meta_table", "common.connections.parsing_meta.table"),
            ("host", "common.connections.rdb.host"),
            ("port", "common.connections.rdb.port"),
            ("database", "common.connections.rdb.database"),
            ("read_user", "common.connections.rdb.read.user"),
            ("read_password", "common.connections.rdb.read.password"),
            ("write_user", "common.connections.rdb.write.user"),
            ("write_password", "common.connections.rdb.write.password"),
            ("sqlite", "common.connections.rdb.sqlite"),
        ),
    ),
    (
        "publish",
        "게시(silver 적재) 위치",
        "PC·서버",
        (("bucket", "pipeline.load.publish.bucket"), ("prefix", "pipeline.load.publish.prefix")),
    ),
    (
        "object_storage",
        "Object Storage 접속(게시 업로드)",
        "서버만",
        tuple((k, f"common.connections.object_storage.{k}") for k in ("endpoint", "region", "access_key", "secret_key", "verify_tls")),
    ),
    (
        "models",
        "LLM·VLM 모델",
        "PC·서버",
        tuple((f"{r}_{k}", f"common.models.{r}.{k}") for r in ("llm", "vlm") for k in ("base_url", "model", "api_key")),
    ),
    (
        "source",
        "원천 위치",
        "서버만",
        (
            ("input_source", "pipeline.extract.input_source"),
            ("source_bucket", "pipeline.connections.rdb.bucket"),
            ("source_uri_prefix", "common.text.source_uri_prefix"),
        ),
    ),
    (
        "tokens",
        "서비스 토큰",
        "서버만",
        (
            ("mcp", "common.tokens.mcp"),
            ("fulltext", "mcp.server.fulltext_secret"),
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
        ),
    ),
)
REQUIRED = {m: f"required.{g}.{k}" for g, _t, _w, rows in REQUIRED_GROUPS for k, m in rows}
# 역할 절 — (모델 접두, 파일 접두). 긴 접두가 먼저 맞는다. 파일 접두도 서로 1:1(거꾸로 바꿀 때 가장 긴 파일 접두).
ROLES = (
    ("common.runtime.", "ops.runtime."),
    ("common.log.", "ops.log."),
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
    ("pipeline.service.", "ops.services."),
    ("mcp.search.", "search."),
    ("mcp.server.", "search.server."),
    ("mcp.edw_meta.", "search.edw_meta."),
    ("mcp.edw_query.", "search.edw_query."),
    ("mcp.output.", "search.output."),
    ("mcp.audit.", "search.audit."),
    ("mcp.host.", "ops.mcp_host."),
    ("mcp.dev.", "dev.mcp."),
)

# tuning — 거의 안 바꾸는 값(사용자 10-30 op-08 4차 · 11-04: 코드로 내리지 않고 sample 아래쪽에 분류별로 모음 — 비우면 코드 기본값).
TUNING_INTERNAL = (  # 내부 조정값 — 재시도·내부 대기·묶음 크기·출력 상한
    "common.models.embed.query_cache_max",
    "common.models.llm.empty_retry_max",
    "common.models.vlm.retry",
    "common.models.transport.connect_timeout",
    "common.models.transport.down_after",
    "common.models.transport.down_cooldown",
    "common.text.draft_terms_max",
    "common.runtime.draft_terms_lock_timeout",
    "pipeline.extract.attach.max_mb",
    "pipeline.extract.cache.parse_cache_max_gb",
    "pipeline.extract.engine_retry",
    "pipeline.extract.isolate_overhead",
    "pipeline.transform.figures.ocr_parallel",
    "pipeline.transform.figures.pptx_convert_sec",
    "pipeline.transform.structure.embed_batch",
    "pipeline.transform.structure.embed_max_chars",
    "pipeline.transform.structure.embed_retry",
    "pipeline.service.data_parsing.job_timeout_sec",
    "pipeline.service.data_parsing.queue_max",
    "pipeline.service.data_parsing.text_page_sec",
    "pipeline.service.data_parsing.warmup_sec",
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
    "pipeline.service.data_parsing.procs",
)
TUNING_RARE = (  # 사용자 11-04 — 역할 절에서 옮긴 칸: 결과 파라미터(청크·순위·그림 고르기)·내부 상한·로그 대기열(운영자가 환경마다 정하지 않음)
    "common.connections.pg.connect_timeout",
    "common.connections.pg.pool_max",
    "common.text.search_en_stem",
    "common.text.token_num_norm",
    "common.log.queue_size",
    "common.log.batch_size",
    "common.log.flush_sec",
    "common.log.db_timeout_sec",
    "common.log.shutdown_sec",
    "pipeline.connections.rdb.increment_col",
    "pipeline.connections.rdb.columns.content_version",
    "pipeline.connections.rdb.columns.doc_id",
    "pipeline.connections.rdb.columns.filename",
    "pipeline.connections.rdb.columns.key",
    "pipeline.connections.rdb.columns.size",
    "pipeline.extract.fill_merged",
    "pipeline.extract.hidden_overlap_max",
    "pipeline.extract.kreuzberg_prose_filter",
    "pipeline.extract.low_priority",
    "pipeline.extract.rotated_max",
    "pipeline.extract.text_page_sec",
    "pipeline.extract.warmup_sec",
    "pipeline.extract.table_grid_max_rows",
    "pipeline.extract.ocr.table_grid",
    "pipeline.extract.attach.max_depth",
    "pipeline.extract.attach.max_n",
    "pipeline.transform.figures.ocr_fallback_min_chars",
    "pipeline.transform.figures.pptx_render_max",
    "pipeline.transform.figures.pptx_shapes_max",
    "pipeline.transform.figures.pptx_smartart_max",
    "pipeline.transform.figures.vectors_max",
    "pipeline.transform.vlm.fig_min_px",
    "pipeline.transform.vlm.fig_ocr_max",
    "pipeline.transform.vlm.fig_photo_area_min",
    "pipeline.transform.vlm.fig_photo_max_tokens",
    "pipeline.transform.vlm.fig_photo_ocr_max",
    "pipeline.transform.vlm.fig_text_ocr_min",
    "pipeline.transform.structure.chunk_overlap",
    "pipeline.transform.structure.chunk_size",
    "pipeline.transform.structure.chunk_table",
    "pipeline.transform.structure.chunk_table_rows",
    "pipeline.transform.structure.page_chunk_max",
    "pipeline.load.publish.upload_statuses",
    "mcp.server.max_queue",
    "mcp.search.methods",
    "mcp.search.weights.bm25",
    "mcp.search.weights.bm25_table",
    "mcp.search.weights.id",
    "mcp.search.weights.vector",
    "mcp.audit.max_queue_bytes",
    "mcp.audit.max_input_bytes",
    "mcp.audit.max_output_bytes",
)
TUNING = frozenset(TUNING_INTERNAL + TUNING_RESOURCE + TUNING_RARE)

# PC 전용 칸(사용자 11-04) — 서버(dev·prd)는 외부 모델·로컬 대체 DB를 거부하므로 비워 둔다. 파일 자리 dev.<역할 자리>(sample 맨 아래 절).
LOCAL = (
    "common.models.embed.allow_external",
    "common.models.llm.allow_external",
    "common.models.vlm.allow_external",
    "common.models.embed.est_usd",
    "common.models.llm.est_usd",
    "common.models.vlm.est_usd",
    "common.models.llm.price_in",
    "common.models.llm.price_out",
    "common.models.guard.budget_usd",
    "common.models.guard.spend_file",
    "common.connections.pg.standin_dir",
    "common.connections.pg.standin_schema",
)


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


def per_instance(name, instance):
    """여러 벌 — 이름 끝에 `_<벌>`(`-`는 `_`로). 벌 이름이 없거나 이미 붙어 있으면(따로 적은 값) 그대로. 앱(settings)·호스트(run_docs)가 같이 쓴다."""
    if not name or not instance:
        return name
    tail = "_" + str(instance).replace("-", "_")
    return name if name.endswith(tail) else name + tail


def _role(model_path):
    for m, y in ROLES:
        if model_path.startswith(m):
            return y + model_path[len(m) :]
    raise LayoutError(f"역할 절 규칙에 없는 모델 칸: {model_path}")


def to_yaml(model_path):
    """모델 경로 → 파일 자리."""
    if model_path in REQUIRED:
        return REQUIRED[model_path]
    if model_path in LOCAL:
        return "dev." + _role(model_path).removeprefix("common.")
    if model_path in TUNING:
        return "tuning." + _role(model_path)
    return _role(model_path)


_REQ_BACK = {y: m for m, y in REQUIRED.items()} | {to_yaml(m): m for m in LOCAL}
_LOCAL_PARENTS = {to_yaml(m).rpartition(".")[0] for m in LOCAL}  # PC 전용 칸이 든 절(dev.models.guard 등) — 그 안의 다른 이름은 모르는 칸
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


def to_model(doc, source=""):
    """파일 사전 → 모델 배치 사전. 모르는 절·모르는 칸·자리가 다른 칸이면 LayoutError(칸 자리만, 값 없음)."""
    if not doc:
        return {}
    where = f": {source}" if source else ""
    unknown = sorted(set(doc) - set(SECTIONS))
    if unknown:
        raise LayoutError(f"설정 파일에 모르는 최상위 절 {unknown} — {'·'.join(SECTIONS)}만(덮기 파일은 base·overrides){where}")
    out, bad, moved = {}, [], []
    for y, v in _leaves(doc):
        m = None if y.rpartition(".")[0] in _LOCAL_PARENTS and y not in _REQ_BACK else to_model_path(y)
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
        raise LayoutError(f"자리가 다른 칸 {len(moved)}개: {', '.join(moved)}{where}")
    if bad:
        raise LayoutError(f"모르는 칸 {len(bad)}개: {', '.join(bad)}{where}")
    return out


def to_file(model_doc):
    """모델 배치 사전 → 파일 사전(SECTIONS 순서). sample·시험이 쓴다."""
    out = {}
    for p, v in _leaves(model_doc or {}):
        set_path(out, to_yaml(p), v)
    return {s: out[s] for s in SECTIONS if s in out}
