"""settings.yaml 배치(op-08 ②) — 파일의 칸 자리(YAML 경로) ↔ 설정 모델의 칸 경로(common.* · pipeline.* · mcp.*).
파일은 `required`(운영자가 꼭 채울 값) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(코드 상수 후보) 순서다.
코드는 모델 경로(`cfg().extract.ocr.dpi` 등)를 그대로 쓰고, read_settings()가 파일을 읽은 직후 to_model()로 모델 배치로 바꾼다.
  · required: 칸마다 자리를 적은 표(REQUIRED). tuning: 모델 경로 모음(TUNING) — 자리는 `tuning.` + 역할 자리.
  · 그 밖: 접두어 규칙(ROLES — 모델 접두 → 파일 접두, 1:1). 사전 값 칸(lib_env·extra_body 등)도 접두어로 그대로 옮겨진다.
  · 모델을 모르고도 바꾼다(표준 라이브러리만) — 이미지에 없는 앱의 칸도 자리만 옮기고, 검증은 그 앱 설정 객체가 한다(U-a).
옛 배치(최상위 common·pipeline·mcp — op-08 전)는 거부하고 `python -m common.config.migrate <옛 settings.yaml>`로 바꾸게 안내한다.
"""

import sys

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
        ),
    ),
)
REQUIRED = {m: f"required.{g}.{k}" for g, _t, _w, rows in REQUIRED_GROUPS for k, m in rows}
RETIRED = frozenset(
    {"required.deploy.mcp_store"}
)  # 지운 파일 자리 — 남아 있으면 경고만(mc-01 11-01: 검색 저장소는 PG 하나, op-09가 필수로 적게 했던 칸)

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
    ("mcp.audit.", "search.audit."),
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


_WARNED: set[str] = set()


def warn_removed(name):
    """지운 칸이 설정 파일에 남았다는 경고 — 프로세스마다 이름 하나에 한 번(F7, 11-03 PC 시험: 설정을 읽을 때마다 5~10번 나오던 것)."""
    if name not in _WARNED:
        _WARNED.add(name)
        sys.stderr.write(f"[settings] 지운 칸 무시: {name} — 설정 파일에서 지울 것(값은 출력 안 함)\n")


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
        if y in RETIRED:
            warn_removed(y)
            continue
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


# 지운 설정 칸 — 설정 절 클래스 이름 → 칸 이름(0.2.0 — 절마다 두던 Section.REMOVED를 이 표 하나로, pl-46).
# 설정 파일에 남아 있으면 경고만 하고 무시(시작 거부 막기 — 0.1.0 settings.yaml도 시작됨) · migrate는 "삭제됨"으로 알림.
REMOVED: dict[str, frozenset[str]] = {
    # CommonModelsTransport(common/config/settings.py) — 0.2.0(pl-46) 전송은 HTTP 한 길(ADK 장치 지움 — 남으면 경고만)
    "CommonModelsTransport": frozenset({"transport"}),
    # CommonConnections(common/config/settings.py) — 사용자 10-29 — 지운 칸·절(남으면 경고만) · edw = EDW 벡터 경로(ops.md#op-03)
    "CommonConnections": frozenset({"edw", "openviking"}),
    # CommonConnectionsParsingMeta(common/config/settings.py) — 사용자 10-29 — 접속은 common.connections.rdb(ops.md#op-03)
    "CommonConnectionsParsingMeta": frozenset({"connect_kwargs", "database", "host", "password", "port", "sqlite", "user"}),
    # CommonDev(common/config/settings.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치) — 지운 칸(남으면 경고만)
    "CommonDev": frozenset({"exp_store", "llm_est_in_tokens", "llm_est_out_tokens", "min_gold_coverage"}),
    # CommonDevDocker(common/config/settings.py) — 사용자 10-30(op-08) — compose는 PG_DB·PG_USER로 채움 · 0.2.0(pl-46) MinIO·s3 원천·자정 배치 모양 시험 칸(11-01 스모크에서 지움)(남으면 경고만)
    "CommonDevDocker": frozenset(
        {
            "minio_image",
            "minio_publish_port",
            "postgres_db",
            "postgres_user",
            "smoke_mode",
            "smoke_nightly",
            "smoke_pm_bucket",
            "smoke_source",
        }
    ),
    # CommonModels(common/config/settings.py) — 사용자 10-29 · ocrvlm 10-30(pl-31) — 지운 칸·절(남으면 경고만)
    "CommonModels": frozenset({"ocrvlm", "rerank"}),
    # CommonModelsEmbed(common/config/settings.py) — 사용자 10-30(op-08) — ping_models는 받은 차원만 보여 줌(남으면 경고만)
    "CommonModelsEmbed": frozenset({"dim"}),
    # CommonModelsGuard(common/config/settings.py) — 사용자 10-29 — 합성 문서 선언 잠금 삭제(옛 migrate C-35가 옮겨 둔 서버 파일 보호)
    "CommonModelsGuard": frozenset({"synthetic_truth"}),
    # CommonModelsLlm(common/config/settings.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치: 읽는 코드가 지워짐) — 지운 칸(남으면 경고만)
    "CommonModelsLlm": frozenset({"empty_retry", "max_concurrency"}),
    # CommonModelsVlm(common/config/settings.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치: 읽는 코드가 지워짐) — 지운 칸(남으면 경고만)
    "CommonModelsVlm": frozenset({"model_alt"}),
    # CommonPaths(common/config/settings.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치 · op-08) · 0.2.0(pl-46) 이름 있는 색인·원천 목록 파일 — 지운 칸(남으면 경고만)
    "CommonPaths": frozenset(
        {
            "client_roster",
            "config_dir",
            "criteria_file",
            "eval_sets_dir",
            "glossary_dir",
            "index_root",
            "korean_font",
            "mcp_bundle",
            "sources_file",
        }
    ),  # client_roster·glossary_dir — pl-38(사용자 11-03): 용어집·고객 명부는 PG 마스터 표(<PG_SCHEMA>_master) · mcp_bundle — mc-19(사용자 11-03): 검색은 PG만
    # CommonRuntime(common/config/settings.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치) — 지운 칸(남으면 경고만)
    "CommonRuntime": frozenset({"exp_max_workers", "exp_proc_gb_answer", "exp_proc_gb_build", "exp_proc_gb_run", "exp_reserve_gb"}),
    # CommonStore(common/config/settings.py) — 사용자 10-30(pl-32 — 재시도 횟수 없음) · 10-31(pl-12 C10 — 문서 대장·숨김 통째로 지움 · pl-08 — 정형 저장소 통째로 지움) — 옛 파일에 남아도 경고만
    "CommonStore": frozenset(
        {"doc_registry", "registry_editions", "registry_etag_md5", "registry_retry_max", "struct_backend", "struct_db"}
    ),
    # CommonText(common/config/settings.py) — 사용자 10-30(op-08) — 지운 칸(남으면 경고만)
    "CommonText": frozenset({"parse_token_norm", "search_recency"}),  # search_recency — pl-38: 판 묶음(family)·최신성 순위 지움
    # McpDev(mcp_server/config.py) — 11-01(e2-10 — mcp_eval 지움) — 지운 칸(남으면 경고만)
    "McpDev": frozenset({"eval_s_parts"}),
    # McpEdwQuery(mcp_server/config.py) — 사용자 10-29 — 접속은 common.connections.rdb 읽기 계정(ops.md#op-03)
    "McpEdwQuery": frozenset({"conn_file", "database", "password", "port", "server", "sqlite", "user"}),
    # McpHost(mcp_server/config.py) — 11-01(e2-10 — 검색 도구 컨테이너 retrieval·mcp_eval 지움) — 지운 칸(남으면 경고만)
    "McpHost": frozenset({"tool_cpus", "tool_mem_limit"}),
    # McpOutput(mcp_server/config.py) — 사용자 10-29·10-30(e2-18 — 근거 이미지·그림 조회 지움) — 지운 칸·절(남으면 경고만)
    "McpOutput": frozenset(
        {
            "cap_ranked",
            "evid_local_roots",
            "evid_max_concurrency",
            "evid_max_mb",
            "evid_timeout_sec",
            "evidence_paths",
            "images",
            "list_docs_max",
            "max_image_px",
        }
    ),
    # McpSearch(mcp_server/config.py) — 사용자 10-29 · ocr_dpi 10-30(op-08) · agg 절·agg_today·data_catalog·struct_context_max 11-01(mc-04 집계 지움) · agg_vocab_file 11-01(사전 파일이 코드 기본값과 같아 지움) · client 절 11-02(본문 고객 라벨 순위·하드 격리 지움 — 고객은 client_edw 거르기만, C6) — 지운 칸·절(남으면 경고만)
    "McpSearch": frozenset(
        {
            "agg",
            "agg_today",
            "agg_vocab_file",
            "client",
            "copy_group",
            "data_catalog",
            "decompose",
            "decompose_llm",
            "entity_split",
            "evidence_gate",
            "graph",
            "ocr_dpi",
            "ov_search_path",
            "query_expand",
            "rerank",
            "struct_context_max",
            "tie_break",
            "type_weights",
            "vector_alias_expand",
        }
    ),
    # McpServer(mcp_server/config.py) — store 11-01(mc-01 — 검색 저장소는 PG 하나) · 사용자 10-30(op-08) — common.models.embed.query_cache로 합침(mcp 이미지 기본은 그 칸에) — 옛 설정 파일에 남아도 경고만
    "McpServer": frozenset({"query_cache", "store"}),
    # PipelineConnections(pipeline/config.py) — 사용자 10-29 · graphiti 10-30(e2-18 — 외부 KG 어댑터 지움) — 지운 칸·절(남으면 경고만)
    "PipelineConnections": frozenset({"graphiti", "openviking"}),
    # PipelineConnectionsRdb(pipeline/config.py) — 사용자 10-29 — 접속은 common.connections.rdb(ops.md#op-03)
    "PipelineConnectionsRdb": frozenset({"connect_kwargs", "database", "host", "password", "port", "user"}),
    # PipelineDev(pipeline/config.py) — 사용자 10-29 · parallel_test_crash 10-30(pl-35) · allow_common_mismatch 11-01(structure·load 모듈의 끝 표시 확인 지움) · test_min_docs·test_per_type 11-01(--mode test 표본 모드 지움) — 지운 칸·절(남으면 경고만)
    "PipelineDev": frozenset(
        {"allow_common_mismatch", "parallel_test_crash", "parse_agent_fake", "stream_test_crash", "test_min_docs", "test_per_type"}
    ),
    # PipelineEval(pipeline/config.py) — 사용자 10-29 · e2e_* 10-30(op-08) · 정답·질문 초안·표 채점·재순위 모델(op-09가 stages.py용으로 더함) 11-01(e2-10 — PC 평가 도구 지움) · review_max_rounds 11-01(figure_review 지움) — 지운 칸·절(남으면 경고만)
    "PipelineEval": frozenset(
        {
            "diagram_raster_vlm",
            "e2e_qa_set",
            "e2e_questions",
            "gold_draft_max_pages",
            "gold_draft_mermaid_check",
            "phase_report_legacy",
            "qa_draft_max_pages",
            "qa_draft_per_page",
            "rerank_model",
            "review_max_rounds",
            "score_table_judge",
        }
    ),
    # PipelineExtract(pipeline/config.py) — 사용자 10-29 — phase 없앰 · 10-30 auto_reparse_changed·parallel 지움(pl-35) · dedup_scan·ocr_gt_max·signal_ocr 지움(pl-34) · engine_scope 지움(pl-03 — stack 하나) · 0.2.0 ocr_engine 지움(pl-46)(남으면 경고만)
    "PipelineExtract": frozenset(
        {
            "auto_reparse_changed",
            "dedup_scan",
            "disk_free_warn_gb",
            "engine_cache_warn_gb",
            "engine_scope",
            "merge_pages",
            "ocr_engine",
            "ocr_gt_max",
            "page_scan",
            "parallel",
            "phase_sec",
            "phases",
            "scan_fill",
            "signal_ocr",
            "stream",
        }
    ),
    # PipelineExtractCache(pipeline/config.py) — 사용자 10-30(op-08) — 지운 칸(남으면 경고만)
    "PipelineExtractCache": frozenset(
        {"keep_engine_cache", "keep_local_originals", "keep_raw_layer", "parse_keep_max_gb", "parse_tmp_max_gb"}
    ),
    # PipelineExtractDedup(pipeline/config.py) — 11-01(pl-02 — 이름·내용 유사 후보 지움, 완전 중복만) — 지운 칸(남으면 경고만)
    "PipelineExtractDedup": frozenset({"common_max", "fuzzy_max"}),
    # PipelineExtractPrepare(pipeline/config.py) — 사용자 10-30(op-08) · ocr 11-01(rapidocr 1.x 길 지움 — 늘 3.x) · rotate_lead·rotate_probe_fast·rotate_s0_min 11-02(회전 판단 규칙 지움 — 켬/끔만) — 지운 칸(남으면 경고만)
    "PipelineExtractPrepare": frozenset({"ocr", "rotate_fast", "rotate_lead", "rotate_probe_fast", "rotate_s0_min"}),
    # PipelineHost(pipeline/config.py) — 0.2.0(pl-46) — 이름 있는 색인·1회 job 컨테이너(load·publish — #100에서 지움) 칸(남으면 경고만)
    # CommonHost(common/config/settings.py) — 11-03(사용자) 오버레이 패치 compose 지움(refactor.md C-83) — 남으면 경고만
    "CommonHost": frozenset({"patch_code"}),
    "PipelineHost": frozenset(
        {
            "index_conf_dir",
            "load_cpus",
            "load_mem_limit",
            "publish_cpus",
            "publish_mem_limit",
            "structure_cpus",
            "structure_mem_limit",
        }
    ),  # structure_* — 11-03(사용자) 상주 컨테이너 하나(data-pipeline — refactor.md C-82)
    # PipelineHostNightly(pipeline/config.py) — 사용자 10-30(pl-32) — 켬/끔은 time 하나로 · max_new·modules·publish 11-01(night 모듈 배치 지움 — 새벽 배치는 run_docs)
    "PipelineHostNightly": frozenset({"enabled", "max_new", "modules", "publish"}),
    # PipelineLoad(pipeline/config.py) — 사용자 10-29(prune_* — 적재가 안 지움, pl-13 · edw_load — EDW 벡터 경로 삭제, ops.md#op-03) · index_lock_stale_sec 11-01(mc-16 — 이름 있는 색인 AD41 지움) — 지운 칸·절(남으면 경고만)
    "PipelineLoad": frozenset(
        {"bm25_stat_rebuild", "edw_load", "index_lock_stale_sec", "prune_force", "prune_min_ratio", "structure_target"}
    ),
    # PipelineLoadPublish(pipeline/config.py) — 사용자 10-30(op-08) — 지운 칸(남으면 경고만)
    "PipelineLoadPublish": frozenset({"source_system", "upload_raw"}),
    # PipelineNight(pipeline/config.py) — 11-01(night·trigger.sh night 지움) — 지운 칸(남으면 경고만)
    "PipelineNight": frozenset({"deadline", "parse_deadline"}),
    # PipelinePaths(pipeline/config.py) — 0.2.0 index_conf(pl-46 — 이름 있는 색인) · 사용자 10-29 · stack_snapshot 10-30(pl-32) · stack_version 11-01(판 표 없앰 — 엔진 구성은 파일) · report_digest_dir 11-01(e2-10 — run_board 지움) · file_meta_path 11-02(pl-29 — 적재가 EDW 조인) · edw_chain 11-03(pl-52 — 적재·검색이 함께 쓰는 common.paths.edw_chain = ops.paths.edw_chain으로) — 지운 칸·절(남으면 경고만)
    "PipelinePaths": frozenset(
        {
            "edw_chain",
            "file_meta_path",
            "index_conf",
            "mineru_bin",
            "paddle_python",
            "report_digest_dir",
            "soffice_candidates",
            "stack_snapshot",
            "stack_version",
        }
    ),
    # PipelineService(pipeline/config.py) — 11-01(pl-10 — trigger 서버 지움) — 지운 절(남으면 경고만)
    "PipelineService": frozenset({"trigger"}),
    # PipelineServiceParseMcp(pipeline/config.py) — 10-29 PARSE_MCP_OCR → extract.ocr_engine으로 합침(그 스위치도 0.2.0에 지움) · max_mb 11-03
    # (파일 크기 상한은 검색 MCP와 함께 쓰는 common.runtime.parse_max_mb = ops.runtime.parse_max_mb로 옮김, 기본 100) — 남으면 경고만
    "PipelineServiceParseMcp": frozenset({"max_mb", "ocr"}),
    # PipelineTransform(pipeline/config.py) — 사용자 10-29 — 지운 칸·절(남으면 경고만)
    "PipelineTransform": frozenset({"agent"}),
    # PipelineTransformFigures(pipeline/config.py) — 사용자 10-30(pl-31 — ocr_vlm 엔진과 함께 지움) — 지운 칸(남으면 경고만)
    "PipelineTransformFigures": frozenset(
        {
            "chart_values_det",
            "diagram_edges_det",
            "doc_shape_figure",
            "nested_figure",
            "ocr_fallback",
            "ocrvlm_prompt",
            "overlay_cluster",
            "page_child_dedup",
            "pptx_slide_vlm",
            "vector_box_diagram",
        }
    ),
    # PipelineTransformRepresent(pipeline/config.py) — pl-34(10-30) — 재판독 P2·P3를 모두 지움(사용자 10-30, 남으면 경고만)
    "PipelineTransformRepresent": frozenset(
        {
            "context",
            "fuse",
            "fuse_reread",
            "fuse_reread_p3",
            "fuse_signals",
            "qa_carry_forward",
            "reread",
            "reread_fallback_best",
            "shadow",
            "shadow_max",
            "standardize",
            "table_db",
            "table_inline",
            "table_std",
            "table_stitch",
        }
    ),
    # PipelineTransformStructure(pipeline/config.py) — 사용자 10-30(pl-21 — 0.1.0 지문 배치: 읽는 코드가 지워짐 · op-08 edw_embed → embed로 합침) — 지운 칸(남으면 경고만)
    "PipelineTransformStructure": frozenset(
        {"bundle_keep_empty_fig", "chunk_head", "client_roster_seed", "draft_terms", "edw_embed", "edw_summary_llm", "wiki_domain_phrase"}
    ),
    # PipelineTransformVlm(pipeline/config.py) — 사용자 10-30(op-08) — 지운 칸(남으면 경고만)
    "PipelineTransformVlm": frozenset({"fig_kind", "fig_select", "fig_text_skip"}),
}
