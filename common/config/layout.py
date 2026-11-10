"""settings.yaml 배치 — 파일의 칸 자리(YAML 경로) ↔ 설정 모델의 칸 경로(common.* · pipeline.* · mcp.*).
파일은 `required`(운영자가 꼭 채울 값) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`(환경마다 운영자가 정하는 값) →
`tuning`(거의 안 바꾸는 값 — 분류별) → `dev`(PC 전용 — 서버는 비워 둠) → `option`(선택 기능 — 비우면 끔) 순서다.
코드는 모델 경로(`cfg().extract.ocr.dpi` 등)를 그대로 쓰고, read_settings()가 파일을 읽은 직후 to_model()로 모델 배치로 바꾼다.
  · required: 칸마다 자리를 적은 표(REQUIRED). 이름·자리를 바꾼 칸: 표(PLACED — 모델 경로 → 파일 자리).
  · tuning: 모델 경로 모음(TUNING) — 자리는 `tuning.` + 역할 자리. PC 전용 칸(LOCAL): 자리는 `dev.` + 역할 자리(앞 `common.` 뺌).
  · 그 밖: 접두어 규칙(ROLES — 모델 접두 → 파일 접두, 1:1). 옛 자리도 ROLES로 모델 칸을 찾아 "옛 자리 → 새 자리"로 거부한다.
  · 모델을 모르고도 바꾼다(표준 라이브러리만 — 호스트 스크립트도 이 파일을 읽음). 검증은 앱 설정 객체가 한다.
모르는 절·모르는 칸·자리가 다른 칸은 시작 거부(칸 자리만 알림, 값은 출력 안 함).
"""

# 파일 최상위 절 — 이 순서로 sample에 낸다.
SECTIONS = ("required", "common", "extract", "transform", "load", "search", "ops", "tuning", "dev", "option")

# required — (카테고리 열쇠, 제목, [(칸 이름, 모델 경로, 필수 조건)]). 조건은 sample 주석 머리에 그대로 — "필수 · <언제·어느 앱>" 또는 "선택".
_PG_NEED = "필수 · 모두(local·dev·prd — pipeline·mcp)"
_SERVER_NEED = "필수 · dev·prd(pipeline·mcp) — local은 무시(비움)"
REQUIRED_GROUPS = (
    ("env", "실행 환경", (("run_env", "common.run_env", "필수 · 모두(local·dev·prd)"),)),
    (
        "source",
        "파싱할 원천",
        (("source_systems", "pipeline.extract.source.systems", "선택 — DEV-<숫자>는 dev·local만(prd면 시작 거부)"),),
    ),
    (
        "pg",
        "PostgreSQL(pgvector) — 접속 5칸 모두 필수(PC는 시험 pgvector 컨테이너 — 비거나 일부만 적으면 거부)",
        (
            *(
                (f"pg_{k}", f"common.connections.pg.{m}", _PG_NEED)
                for k, m in (("host", "host"), ("port", "port"), ("database", "db"), ("user", "user"), ("password", "password"))
            ),
            ("pg_schema", "common.connections.pg.db_schema", "선택 — 비우면 data_parsing"),
        ),
    ),
    (
        "models",
        "모델 접속 — 임베딩·LLM·VLM(모델마다 따로)",
        (
            "임베딩 모델",
            ("embed_base_url", "common.models.embed.base_url", "필수 · 모두(pipeline·mcp)"),
            ("embed_api_key", "common.models.embed.api_key", "선택 — 엔드포인트가 키를 요구할 때"),
            ("embed_model", "common.models.embed.model", "필수 · 모두(pipeline·mcp)"),
            *(
                row
                for r in ("llm", "vlm")
                for row in (
                    r.upper(),
                    (f"{r}_base_url", f"common.models.{r}.base_url", "필수 · 모두(pipeline)"),
                    (f"{r}_api_key", f"common.models.{r}.api_key", "선택 — 엔드포인트가 키를 요구할 때"),
                    (f"{r}_model", f"common.models.{r}.model", "필수 · 모두(pipeline)"),
                )
            ),
        ),
    ),
    (
        "edw",
        "EDW(회사 DB) 접속 — 읽기 계정만",
        (
            ("edw_host", "common.connections.rdb.host", _SERVER_NEED),
            ("edw_port", "common.connections.rdb.port", "선택"),
            ("edw_database", "common.connections.rdb.database", _SERVER_NEED),
            ("edw_read_user", "common.connections.rdb.read.user", _SERVER_NEED),
            ("edw_read_password", "common.connections.rdb.read.password", _SERVER_NEED),
            ("edw_file_table", "pipeline.connections.rdb.file_table", "필수 · 모두(pipeline) — 기본값 그대로 두면 AI.FileStorageMap"),
        ),
    ),
    (
        "publish",
        "게시(silver 적재) 위치",
        (
            ("publish_bucket", "pipeline.load.publish.bucket", "필수 · dev·prd(pipeline) — local은 무시(dev.local.local_publish_dir)"),
            ("publish_prefix", "pipeline.load.publish.prefix", "선택"),
        ),
    ),
    (
        "object_storage",
        "Object Storage 접속",
        (
            (
                "object_storage_endpoint",
                "common.connections.object_storage.endpoint",
                _SERVER_NEED,
            ),
            ("object_storage_access_key", "common.connections.object_storage.access_key", _SERVER_NEED),
            ("object_storage_secret_key", "common.connections.object_storage.secret_key", _SERVER_NEED),
        ),
    ),
    (
        "tokens",
        "서비스 토큰·서명 키",
        (
            ("mcp_token", "common.tokens.mcp", "필수 · dev·prd(mcp)"),
            ("fulltext_sign_key", "mcp.server.fulltext_secret", "필수 · dev·prd(mcp — 원문 도구를 쓸 때)"),
        ),
    ),
    (
        "deploy",
        "서버 배포(이미지·호스트 폴더)",
        (
            ("pipeline_image", "pipeline.host.image", "필수 · dev·prd(호스트 compose)"),
            ("mcp_image", "mcp.host.image", "필수 · dev·prd(호스트 compose)"),
            ("host_docs_dir", "common.host.doc_src", "필수 · dev·prd(호스트 compose)"),
            ("pg_container_name", "common.host.pg_container", "필수 · dev·prd(호스트 run_pipeline·백업)"),
        ),
    ),
)
# 묶음 안 글자 한 줄 = 작은 묶음 제목(sample에 `# ---- 제목 ----`) — 칸 줄은 (파일 이름, 모델 경로, 필수 조건).
REQUIRED = {r[1]: f"required.{g}.{r[0]}" for g, _t, rows in REQUIRED_GROUPS for r in rows if isinstance(r, tuple)}
NEED = {r[1]: r[2] for _g, _t, rows in REQUIRED_GROUPS for r in rows if isinstance(r, tuple)}
# 역할 절 — (모델 접두, 파일 접두). 긴 접두가 먼저 맞는다. 파일 접두도 서로 1:1(거꾸로 바꿀 때 가장 긴 파일 접두).
ROLES = (
    ("common.parse_queue.", "ops.services.data_parsing."),
    ("common.runtime.", "ops.runtime."),
    ("common.log.", "ops.log."),
    ("common.paths.", "ops.paths."),
    ("common.host.devbox.", "option.devbox."),  # 선택 기능(개발 작업 공간) — 파일 맨 아래 option 절
    ("common.host.", "ops.host."),
    ("common.dev.", "dev."),
    ("common.", "common."),
    ("pipeline.extract.", "extract."),
    ("pipeline.connections.", "extract.connections."),
    ("pipeline.transform.", "transform."),
    ("pipeline.load.", "load."),
    ("pipeline.paths.", "ops.pipeline_paths."),
    ("pipeline.host.nightly.", "ops.nightly."),
    ("pipeline.host.run_pipeline.", "ops.run_pipeline."),
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

# 이름·자리를 바꾼 칸 — {모델 경로: 파일 자리}. 모델 경로·옛 env 이름·--set 이름은 그대로(코드는 안 바뀜), 파일 자리만 다르다.
# 이름은 줄임 없이 뜻이 보이게(단위·꼴을 끝에 — _sec·_file·_dir·max_…). 표에 없는 칸은 LOCAL·TUNING·ROLES 규칙대로.
PLACED = {
    # parse_document Redis 큐 — 서버당 한 벌(번호 벌은 파싱 MCP 없음).
    "common.connections.redis.redis_host": "common.connections.redis.redis_host",
    "common.connections.redis.redis_port": "common.connections.redis.redis_port",
    "common.connections.redis.redis_password": "common.connections.redis.redis_password",
    "common.connections.redis.redis_db": "common.connections.redis.redis_db",
    "common.connections.redis.redis_key_prefix": "common.connections.redis.redis_key_prefix",
    "common.host.redis_image": "ops.host.redis_image",
    "common.host.redis_mem_limit": "ops.host.redis_mem_limit",
    "common.host.redis_data_dir": "ops.host.redis_data_dir",
    "common.parse_queue.mcp_parse_workers": "ops.services.data_parsing.mcp_parse_workers",
    "common.parse_queue.mcp_parse_max_attempts": "tuning.ops.services.data_parsing.mcp_parse_max_attempts",
    "common.parse_queue.mcp_parse_result_ttl_sec": "tuning.ops.services.data_parsing.mcp_parse_result_ttl_sec",
    # common
    "common.connections.rdb.connect_kwargs": "common.connections.edw.edw_extra_connect_args",
    "common.connections.object_storage.region": "common.connections.object_storage.object_storage_region",
    "common.connections.object_storage.verify_tls": "common.connections.object_storage.object_storage_verify_tls",
    "common.models.embed.query_prefix": "common.models.embed.embed_query_instruction",
    "common.models.llm.extra_body": "common.models.llm.llm_extra_request_body",
    "common.models.llm.rpm": "common.models.llm.llm_max_calls_per_minute",
    "common.models.llm.cache_dir": "common.models.llm.llm_response_cache_dir",
    "common.models.vlm.extra_body": "common.models.vlm.vlm_extra_request_body",
    "common.models.vlm.max_concurrency": "common.models.vlm.vlm_max_total_requests",
    "common.models.vlm.concurrency": "common.models.vlm.vlm_requests_per_doc",
    "common.models.vlm.timeout": "common.models.vlm.vlm_timeout_sec",
    # extract
    "pipeline.extract.max_new": "extract.max_new_docs_per_run",
    "pipeline.extract.max_file_mb": "extract.max_source_file_mb",
    "pipeline.extract.ocr.max_pages": "extract.ocr.ocr_max_pages_per_doc",
    "pipeline.extract.ocr.threads": "extract.ocr.ocr_onnx_threads",
    "pipeline.extract.rapidocr_page_workers": "extract.ocr.rapidocr_page_threads",
    "pipeline.extract.ocr.dpi": "extract.page_render_dpi",
    "pipeline.extract.prepare.rotate": "extract.prepare.rotate_pages",
    "pipeline.connections.rdb.bucket": "extract.source.source_default_bucket",
    "pipeline.extract.source.fetch_workers": "extract.source.source_fetch_threads",
    "pipeline.extract.input_source": "extract.source.source_input_location",
    "pipeline.extract.source.staging": "extract.source.source_staging_dir",
    "common.text.source_uri_prefix": "extract.source.source_uri_prefix",
    # transform
    "pipeline.transform.represent.rep_select": "transform.represent.engine_pick",
    "pipeline.transform.represent.post": "transform.represent.post_steps",
    "pipeline.extract.doc_parallel": "transform.represent.represent_parallel_docs",
    "pipeline.transform.represent.qa_light": "transform.represent.skip_full_qa",
    "pipeline.transform.structure.embed_cache": "transform.structure.embed_cache_file",
    "pipeline.transform.vlm.figures_max": "transform.vlm.vlm_max_figures_per_doc",
    "pipeline.transform.vlm.page_max": "transform.vlm.vlm_max_pages_per_doc",
    # load
    "pipeline.load.edw_path_prefix": "load.stored_path_prefix",
    # search
    "mcp.edw_meta.dir": "search.edw_meta.edw_meta_catalog_dir",
    "mcp.edw_query.max_rows": "search.edw_query.edw_query_max_rows",
    "mcp.server.allowed_hosts": "search.server.mcp_allowed_hosts",
    "mcp.server.host": "search.server.mcp_bind_host",
    "mcp.server.manifest": "search.server.mcp_manifest_file",
    "mcp.server.max_concurrency": "search.server.mcp_max_concurrent_tools",
    "mcp.server.port": "search.server.mcp_port",
    # ops
    "pipeline.host.data_parsing_cpu_shares": "ops.containers.data_parsing.data_parsing_cpu_shares",
    "pipeline.host.data_parsing_cpus": "ops.containers.data_parsing.data_parsing_cpus",
    "pipeline.host.data_parsing_mem_limit": "ops.containers.data_parsing.data_parsing_mem_limit",
    "mcp.host.cpus": "ops.containers.mcp.mcp_cpus",
    "mcp.host.mem_limit": "ops.containers.mcp.mcp_mem_limit",
    "pipeline.host.parse_cpus": "ops.containers.pipeline.pipeline_cpus",
    "pipeline.host.parse_mem_limit": "ops.containers.pipeline.pipeline_mem_limit",
    "common.host.pipeline_container": "ops.containers.pipeline.pipeline_container_name",
    "common.host.data_parsing_container": "ops.containers.data_parsing.data_parsing_container_name",
    "common.host.mcp_container": "ops.containers.mcp.mcp_container_name",
    "common.host.docker": "ops.host.container_cli",
    "common.host.edw_chain_src": "ops.host.host_edw_chain_file",
    "common.host.output_root": "ops.host.host_output_dir",
    "common.host.prune_keep": "ops.host.prune_keep_versions",
    "common.host.image_stage_dir": "ops.host.prune_stage_dir",
    "common.log.db_enabled": "ops.log.log_db_enabled",
    "common.log.fallback_dir": "ops.log.log_fallback_dir",
    "common.log.dir": "ops.log.log_json_dir",
    "common.log.level": "ops.log.log_level",
    "common.log.retention_days": "ops.log.log_retention_days",
    "pipeline.host.nightly.max_docs": "ops.nightly.nightly_max_docs",
    "pipeline.host.nightly.time": "ops.nightly.nightly_start_time",
    "pipeline.host.nightly.deadline": "ops.nightly.nightly_stop_time",
    "pipeline.paths.out_root": "ops.paths.container_output_dir",
    "common.paths.edw_chain": "ops.paths.edw_chain_file",
    "pipeline.paths.images_root": "ops.paths.figure_images_dir",
    "common.paths.draft_terms_out": "ops.paths.glossary_draft_file",
    "pipeline.paths.parse_tmp": "ops.paths.parse_temp_dir",
    "common.paths.doc_dir_prepared": "ops.paths.prepared_docs_dir",
    "pipeline.paths.raw_root": "ops.paths.raw_cache_dir",
    "pipeline.paths.soffice_bin": "ops.paths.soffice_path",
    "common.paths.doc_dir": "ops.paths.source_docs_dir",
    "common.paths.source_manifest": "ops.paths.source_manifest_file",
    "pipeline.host.run_pipeline.light_dedicated": "ops.run_pipeline.light_lane.light_lane_dedicated_workers",
    "pipeline.host.run_pipeline.light_cpu_gate": "ops.run_pipeline.light_lane.light_lane_max_cpu_load",
    "pipeline.host.run_pipeline.light_shared": "ops.run_pipeline.light_lane.light_lane_shared_workers",
    "pipeline.host.run_pipeline.medium_dedicated": "ops.run_pipeline.medium_lane.medium_lane_dedicated_workers",
    "pipeline.host.run_pipeline.medium_shared": "ops.run_pipeline.medium_lane.medium_lane_shared_workers",
    "pipeline.host.run_pipeline.rep_select": "ops.run_pipeline.parse.batch_engine_pick",
    "pipeline.host.run_pipeline.pipe_procs": "ops.run_pipeline.parse.batch_engine_processes",
    "pipeline.host.run_pipeline.cpu_gate": "ops.run_pipeline.parse.batch_max_cpu_load",
    "pipeline.host.run_pipeline.figures_max": "ops.run_pipeline.parse.batch_max_figures_per_doc",
    "pipeline.host.run_pipeline.ocr_threads": "ops.run_pipeline.parse.batch_ocr_onnx_threads",
    "pipeline.host.run_pipeline.parse_post": "ops.run_pipeline.parse.batch_post_steps",
    "pipeline.host.run_pipeline.rapidocr_page_workers": "ops.run_pipeline.parse.batch_rapidocr_page_threads",
    "pipeline.host.run_pipeline.scan_rotate": "ops.run_pipeline.parse.batch_rotate_scans",
    "pipeline.host.run_pipeline.qa_light": "ops.run_pipeline.parse.batch_skip_full_qa",
    "pipeline.host.run_pipeline.vlm_concurrency": "ops.run_pipeline.parse.batch_vlm_requests_per_doc",
    "pipeline.host.run_pipeline_dir": "ops.run_pipeline.run_pipeline_work_dir",
    "pipeline.host.run_pipeline.fetch_workers": "ops.run_pipeline.staging.staging_fetch_threads",
    "pipeline.host.run_pipeline.staging": "ops.run_pipeline.staging.staging_max_docs",
    "pipeline.host.run_pipeline.staging_workers": "ops.run_pipeline.staging.staging_workers",
    "pipeline.host.run_pipeline.bm25_threads": "ops.run_pipeline.structure.batch_bm25_threads",
    "pipeline.host.run_pipeline.embed_batch": "ops.run_pipeline.structure.batch_embed_batch_size",
    "pipeline.host.run_pipeline.embed_concurrency": "ops.run_pipeline.structure.batch_embed_concurrency",
    "pipeline.host.run_pipeline.struct_backlog": "ops.run_pipeline.structure.structure_max_backlog",
    "pipeline.host.run_pipeline.struct_workers": "ops.run_pipeline.structure.structure_workers",
    "pipeline.host.run_pipeline.vlm_dedicated": "ops.run_pipeline.vlm_lane.vlm_lane_dedicated_workers",
    "pipeline.host.run_pipeline.vlm_cap": "ops.run_pipeline.vlm_lane.vlm_lane_max_concurrent_docs",
    "pipeline.host.run_pipeline.vlm_lane_post": "ops.run_pipeline.vlm_lane.vlm_lane_post_steps",
    "pipeline.host.run_pipeline.vlm_lane_concurrency": "ops.run_pipeline.vlm_lane.vlm_lane_requests_per_doc",
    "pipeline.host.run_pipeline.vlm_shared": "ops.run_pipeline.vlm_lane.vlm_lane_shared_workers",
    "common.runtime.pipe_procs": "ops.runtime.engine_processes",
    "common.runtime.lib_env": "ops.runtime.library_env",
    "common.runtime.pipe_workers": "ops.runtime.vlm_parallel_docs",
    "common.runtime.data_parsing_port": "ops.services.data_parsing.data_parsing_port",
    "pipeline.service.data_parsing.roots": "ops.services.data_parsing.mcp_parse_allowed_roots",
    "common.runtime.parse_max_mb": "ops.services.data_parsing.mcp_parse_max_file_mb",
    # tuning
    "common.connections.pg.connect_timeout": "tuning.common.connections.pg.pg_connect_timeout_sec",
    "common.connections.pg.pool_max": "tuning.common.connections.pg.pg_pool_max_connections",
    "common.models.embed.timeout": "tuning.common.models.embed.embed_timeout_sec",
    "common.models.llm.empty_retry_max": "tuning.common.models.llm.llm_empty_retry_max_tokens",
    "common.models.llm.timeout": "tuning.common.models.llm.llm_timeout_sec",
    "common.models.transport.connect_timeout": "tuning.common.models.transport.model_connect_timeout_sec",
    "common.models.transport.down_after": "tuning.common.models.transport.model_down_after_failures",
    "common.models.transport.down_cooldown": "tuning.common.models.transport.model_down_cooldown_sec",
    "common.models.vlm.retry": "tuning.common.models.vlm.vlm_retries",
    "common.text.search_en_stem": "tuning.common.text.english_singularize",
    "common.text.draft_terms_max": "tuning.common.text.glossary_draft_max_rows",
    "common.text.token_num_norm": "tuning.common.text.number_unit_normalize",
    "pipeline.extract.archive.max_files": "tuning.extract.archive.archive_max_files",
    "pipeline.extract.archive.max_total_mb": "tuning.extract.archive.archive_max_total_mb",
    "pipeline.extract.attach.max_n": "tuning.extract.attach.attachment_max_count",
    "pipeline.extract.attach.max_depth": "tuning.extract.attach.attachment_max_depth",
    "pipeline.extract.attach.max_mb": "tuning.extract.attach.attachment_max_mb",
    "pipeline.extract.attach.timeout": "tuning.extract.attach.attachment_timeout_sec",
    "pipeline.extract.isolate_overhead": "tuning.extract.engine_isolate_startup_sec",
    "pipeline.extract.engine_retry": "tuning.extract.engine_retries",
    "pipeline.extract.fill_merged": "tuning.extract.fill_merged_cells",
    "pipeline.extract.warmup_sec": "tuning.extract.first_doc_min_timeout_sec",
    "pipeline.extract.low_priority": "tuning.extract.low_priority_engines",
    "pipeline.extract.hidden_overlap_max": "tuning.extract.max_hidden_overlap_pages",
    "pipeline.extract.rotated_max": "tuning.extract.max_rotated_pages",
    "pipeline.extract.ocr.table_grid": "tuning.extract.ocr.table_grid_from_boxes",
    "pipeline.connections.rdb.columns.doc_id": "tuning.extract.source_columns.source_column_doc_id",
    "pipeline.connections.rdb.columns.size": "tuning.extract.source_columns.source_column_file_size",
    "pipeline.connections.rdb.columns.filename": "tuning.extract.source_columns.source_column_filename",
    "pipeline.connections.rdb.increment_col": "tuning.extract.source_columns.source_column_increment",
    "pipeline.connections.rdb.columns.key": "tuning.extract.source_columns.source_column_storage_key",
    "pipeline.connections.rdb.columns.source_system": "tuning.extract.source_columns.source_column_source_system",
    "pipeline.extract.text_page_sec": "tuning.extract.text_engine_page_timeout_sec",
    "pipeline.load.publish.upload_statuses": "tuning.load.publish.publish_upload_statuses",
    "common.log.batch_size": "tuning.ops.log.log_batch_size",
    "common.log.db_timeout_sec": "tuning.ops.log.log_db_timeout_sec",
    "common.log.flush_sec": "tuning.ops.log.log_flush_sec",
    "common.log.queue_size": "tuning.ops.log.log_queue_size",
    "common.log.shutdown_sec": "tuning.ops.log.log_shutdown_sec",
    "common.runtime.pipe_threads": "tuning.ops.runtime.engine_threads_per_process",
    "common.runtime.pipe_proc_gb": "tuning.ops.runtime.gb_per_engine_process",
    "common.runtime.draft_terms_lock_timeout": "tuning.ops.runtime.glossary_lock_timeout_sec",
    "common.runtime.cpu_max_load": "tuning.ops.runtime.max_cpu_load",
    "common.runtime.pipe_max_procs": "tuning.ops.runtime.max_engine_processes",
    "common.runtime.mem_settle_margin": "tuning.ops.runtime.mem_settle_margin_pct",
    "common.runtime.pipe_reserve_cpus": "tuning.ops.runtime.reserved_cpus",
    "common.runtime.pipe_reserve_gb": "tuning.ops.runtime.reserved_gb",
    "pipeline.service.data_parsing.procs": "tuning.ops.services.data_parsing.mcp_parse_engine_processes",
    "pipeline.service.data_parsing.warmup_sec": "tuning.ops.services.data_parsing.mcp_parse_first_try_min_timeout_sec",
    "pipeline.service.data_parsing.job_timeout_sec": "tuning.ops.services.data_parsing.mcp_parse_job_timeout_sec",
    "common.parse_queue.queue_max": "tuning.ops.services.data_parsing.mcp_parse_max_queued_jobs",
    "pipeline.service.data_parsing.text_page_sec": "tuning.ops.services.data_parsing.mcp_parse_text_engine_page_timeout_sec",
    "mcp.audit.max_input_bytes": "tuning.search.audit.audit_max_input_bytes",
    "mcp.audit.max_output_bytes": "tuning.search.audit.audit_max_output_bytes",
    "mcp.audit.max_queue_bytes": "tuning.search.audit.audit_max_queue_bytes",
    "mcp.edw_meta.max_bytes": "tuning.search.edw_meta.edw_meta_max_response_bytes",
    "mcp.edw_query.max_bytes": "tuning.search.edw_query.edw_query_max_response_bytes",
    "mcp.edw_query.timeout_sec": "tuning.search.edw_query.edw_query_timeout_sec",
    "mcp.output.max_chars": "tuning.search.output.tool_max_response_bytes",
    "mcp.search.pg.filter_exact_max": "tuning.search.pg.exact_search_max_chunks",
    "mcp.search.methods": "tuning.search.search_default_methods",
    "mcp.server.max_queue": "tuning.search.server.mcp_max_queued_tools",
    "mcp.server.pg_statement_timeout_sec": "tuning.search.server.mcp_pg_statement_timeout_sec",
    "mcp.server.reload_check_sec": "tuning.search.server.mcp_reload_check_sec",
    "mcp.server.tool_timeout_sec": "tuning.search.server.mcp_tool_timeout_sec",
    "mcp.search.weights.bm25_table": "tuning.search.weights.bm25_table_weight",
    "mcp.search.weights.bm25": "tuning.search.weights.bm25_weight",
    "mcp.search.weights.id": "tuning.search.weights.id_match_weight",
    "mcp.search.weights.vector": "tuning.search.weights.vector_weight",
    "pipeline.transform.vlm.fig_ocr_max": "tuning.transform.figures.figure_max_ocr_per_doc",
    "pipeline.transform.figures.vectors_max": "tuning.transform.figures.figure_max_vector_pages",
    "pipeline.transform.vlm.fig_min_px": "tuning.transform.figures.figure_min_side_px",
    "pipeline.transform.figures.ocr_fallback_min_chars": "tuning.transform.figures.figure_ocr_fallback_min_chars",
    "pipeline.transform.figures.ocr_parallel": "tuning.transform.figures.figure_ocr_threads",
    "pipeline.transform.vlm.fig_photo_ocr_max": "tuning.transform.figures.figure_photo_max_ocr_chars",
    "pipeline.transform.vlm.fig_photo_max_tokens": "tuning.transform.figures.figure_photo_max_tokens",
    "pipeline.transform.vlm.fig_photo_area_min": "tuning.transform.figures.figure_photo_min_area_ratio",
    "pipeline.transform.vlm.fig_text_ocr_min": "tuning.transform.figures.figure_text_image_min_ocr_chars",
    "pipeline.transform.figures.pptx_render_max": "tuning.transform.figures.pptx_max_rendered_slides",
    "pipeline.transform.figures.pptx_shapes_max": "tuning.transform.figures.pptx_max_shape_slides",
    "pipeline.transform.figures.pptx_smartart_max": "tuning.transform.figures.pptx_max_smartart_slides",
    "pipeline.transform.figures.pptx_convert_sec": "tuning.transform.figures.soffice_timeout_sec",
    "pipeline.transform.structure.chunk_size": "tuning.transform.structure.chunk_target_chars",
    "pipeline.transform.structure.embed_batch": "tuning.transform.structure.embed_batch_size",
    "pipeline.transform.structure.embed_retry": "tuning.transform.structure.embed_retries",
    "pipeline.transform.structure.chunk_table": "tuning.transform.structure.split_tables",
    "pipeline.transform.structure.chunk_table_rows": "tuning.transform.structure.table_rows_per_chunk",
    # dev
    "common.dev.docker.smoke_keep": "dev.docker.smoke_keep_pg",
    "common.dev.docker.smoke_limit": "dev.docker.smoke_max_docs",
    "common.dev.docker.pg_image": "dev.docker.smoke_pg_image",
    "common.dev.docker.smoke_settings": "dev.docker.smoke_settings_file",
    "common.dev.llm_fake": "dev.fake_llm",
    "common.models.embed.allow_external": "dev.models.embed.embed_allow_external",
    "common.models.embed.est_usd": "dev.models.embed.embed_est_usd_per_call",
    "common.models.guard.budget_usd": "dev.models.guard.daily_budget_usd",
    "common.models.guard.spend_file": "dev.models.guard.spend_ledger_file",
    "common.models.llm.allow_external": "dev.models.llm.llm_allow_external",
    "common.models.llm.est_usd": "dev.models.llm.llm_est_usd_per_turn",
    "common.models.llm.price_in": "dev.models.llm.llm_price_in_usd_per_mtok",
    "common.models.llm.price_out": "dev.models.llm.llm_price_out_usd_per_mtok",
    "common.models.vlm.allow_external": "dev.models.vlm.vlm_allow_external",
    "common.models.vlm.est_usd": "dev.models.vlm.vlm_est_usd_per_call",
    "mcp.dev.mcp_url": "dev.search_ui.search_ui_mcp_url",
    "mcp.dev.ui_port": "dev.search_ui.search_ui_port",
    # dev — local(PC) 전용 값(op-14: local은 서버 전용 칸을 무시하고 이 값을 씀)
    "common.connections.rdb.sqlite": "dev.local.local_edw_sqlite_file",
    "pipeline.load.publish.local_dir": "dev.local.local_publish_dir",
    "pipeline.extract.local_source": "dev.local.local_source_dir",
    "pipeline.extract.local_max_new": "dev.local.local_max_new_docs_per_run",
}
# 자리를 옮긴 required 칸 — {옛 파일 자리: 새 파일 자리}. 남아 있으면 "옛 자리 → 새 자리"로 거부(refactor.md C-95 대응표).
MOVED = {"required.edw.edw_local_sqlite_file": "dev.local.local_edw_sqlite_file"}

# tuning — 거의 안 바꾸는 값(sample 아래쪽에 분류별로 모음 — 비우면 코드 기본값).
TUNING_INTERNAL = (  # 내부 조정값 — 재시도·내부 대기·묶음 크기·출력 상한
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
    "common.parse_queue.queue_max",
    "pipeline.service.data_parsing.text_page_sec",
    "pipeline.service.data_parsing.warmup_sec",
    "mcp.server.pg_statement_timeout_sec",
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
TUNING_RARE = (  # 결과 파라미터(청크·순위·그림 고르기)·내부 상한·로그 대기열(운영자가 환경마다 정하지 않음)
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
    "pipeline.connections.rdb.columns.doc_id",
    "pipeline.connections.rdb.columns.filename",
    "pipeline.connections.rdb.columns.key",
    "pipeline.connections.rdb.columns.size",
    "pipeline.connections.rdb.columns.source_system",
    "pipeline.extract.fill_merged",
    "pipeline.extract.hidden_overlap_max",
    "pipeline.extract.kreuzberg_prose_filter",
    "pipeline.extract.low_priority",
    "pipeline.extract.rotated_max",
    "pipeline.extract.text_page_sec",
    "pipeline.extract.warmup_sec",
    "pipeline.extract.table_grid_max_rows",
    "pipeline.extract.ocr.table_grid",
    "pipeline.extract.archive.max_files",
    "pipeline.extract.archive.max_total_mb",
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
    "pipeline.transform.structure.chunk_size",
    "pipeline.transform.structure.chunk_table",
    "pipeline.transform.structure.chunk_table_rows",
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

# PC 전용 칸 — 서버(dev·prd)는 외부 모델을 거부하므로 비워 둔다. 파일 자리 dev.<역할 자리>(sample 맨 아래 절).
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
)


class LayoutError(ValueError):
    """파일 배치 오류 — 메시지에는 칸 자리만(값 없음)."""


DUP_KEY = "같은 칸 두 번"


def reject_dup_keys(loader_cls):
    """YAML Loader 클래스가 같은 절·칸을 두 번 쓴 파일을 거부하게(앞 것이 조용히 사라지므로 — 값은 안 찍음). 앱(settings)·호스트(run_pipeline)가 같이 쓴다."""
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


def _lookup(path, table):
    """표에서 경로 또는 그 앞부분(사전 값 칸 — library_env 아래 TZ 등)을 찾아 바꾼다. 없으면 None."""
    head, rest = path, ""
    while head:
        if head in table:
            return table[head] + rest
        head, _, leaf = head.rpartition(".")
        rest = f".{leaf}{rest}"
    return None


_FWD = REQUIRED | PLACED


def to_yaml(model_path):
    """모델 경로 → 파일 자리."""
    y = _lookup(model_path, _FWD)
    if y is not None:
        return y
    if model_path in LOCAL:
        return "dev." + _role(model_path).removeprefix("common.")
    if model_path in TUNING:
        return "tuning." + _role(model_path)
    return _role(model_path)


_REQ_BACK = {y: m for m, y in _FWD.items()} | {to_yaml(m): m for m in LOCAL}
_LOCAL_PARENTS = {to_yaml(m).rpartition(".")[0] for m in LOCAL}  # PC 전용 칸이 든 절(dev.models.guard 등) — 그 안의 다른 이름은 모르는 칸
_ROLES_BACK = sorted(((y, m) for m, y in ROLES), key=lambda r: -len(r[0]))


def to_model_path(yaml_path):
    """파일 자리 → 모델 경로. 모르는 절·required/tuning에 없는 칸이면 None. 자리가 바뀐 칸(다른 절에 있어야 함)도 그대로 돌려준다 —
    판정은 to_model이(to_yaml로 되돌려 견줌)."""
    m = _lookup(yaml_path, _REQ_BACK)
    if m is not None:
        return m
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
        if y in MOVED:
            moved.append(f"{y} → {MOVED[y]}")
            continue
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
    """모델 배치 사전 → 파일 사전(SECTIONS 순서). 시험이 설정 파일을 만들 때 쓴다."""
    out = {}
    for p, v in _leaves(model_doc or {}):
        set_path(out, to_yaml(p), v)
    return {s: out[s] for s in SECTIONS if s in out}
