# pipeline — data pipeline (image `data-pipeline`)

Area of [PRD.md](../PRD.md). Flow: extract (source → prepare → parse) → transform (represent → figures → structure) → load (pgvector · struct DB · publish). Shared model/config layer (`common/`) is listed here too.
One anchor per feature: what, why, code files. Open items carry a `Status:` line with progress.

## pl-01
Sources and fetch. Why: documents come from folders, Object Storage or the company RDB listing.
- What: `input_source` = folder · `s3://bucket/prefix` · `rdb:csv:<path>` · `rdb:<table>`; RDB column mapping (`RDB_COL_*`); incremental since/watermark; streaming (fetch a batch → parse → delete); prefetch (warm); server source lists versioned in `struct.source_version`.
- Files: `pipeline/extract/source.py`, `pipeline/extract/rdb_discover.py`, `pipeline/stream.py`, `resources/mappings/sources.json`.
- Status: done

## pl-02
Prepare. Why: skip junk before the expensive parse.
- What: sha256 dedup + similar name/content candidates, scanned-page rotation by RapidOCR score, DRM/password detection (decryption with msoffcrypto/pikepdf is a manual CLI — `python -m pipeline.extract.secure_docs decrypt`, not part of prepare or stream), archives marked unsupported.
- Files: `pipeline/extract/prepare.py`, `pipeline/extract/dedup.py`, `pipeline/extract/secure_docs.py`.
- Status: done

## pl-03
Engine stack parse. Why: no single parser handles every format well.
- What: per file type, every engine in the stack runs (not a fallback chain), max 2 per type, in parallel per document (no phases since 10-29 — [pl-22](#pl-22)); per-engine isolation; engine stack versioned in `struct.stack_version` (PC: `pipeline_stack.json`). Types: pdf (text/image), doc(x), ppt(x), xls(x/m), hwpx, txt, html/htm, mht, eml, msg, png, jpg. Not supported: old `.hwp`, zip.
- Files: `pipeline/extract/run_all.py`, `pipeline/extract/engines/` (engine fingerprint — human review to change), `resources/config/pipeline_stack.json`, `docs/architecture/pipeline_stack.md`.
- Status: done

## pl-04
Represent — pick and repair the best result. Why: engines disagree; the hand-off must be the most accurate text.
- What: choose the representative engine (accuracy + richness), line-level fusion by vote, OCR/VLM re-read of disputed spots, cross-engine label/value check, fill scanned pages inside text PDFs, standard tables (`tables_std`), symbol/sub-superscript standardization, table stitching, parse QA.
- Files: `pipeline/transform/represent/represent.py`, `fuse.py`, `reread.py`, `reread_stage3.py`, `crosscheck.py`, `table_std.py`, `parse_qa.py`.
- Status: done

## pl-05
Figures. Why: charts, diagrams and images carry values that text extraction misses.
- What: VLM descriptions of images (pdf, docx, xlsx, pptx, eml), native chart XML and vector-chart values without VLM, rule-based diagram edges, Mermaid output, overlay groups, nested figures, whole-page VLM for scans, soffice render of shapes/slides, global VLM gate (default 12).
- Files: `pipeline/transform/figures/figures.py`, `charts.py`, `pptx_render.py`, `vgate.py`, `resources/prompts/pipeline/`.
- Status: done

## pl-06
Structure — chunks, metadata, embeddings. Why: search needs cited chunks with metadata.
- What: chunking structure (default, 800 chars, headings, tables whole) / fixed 512+64 / sentence / page, big tables by 25 rows; summaries (LLM when `EDW_SUMMARY_LLM=1`, else lead text — OpenViking summaries removed 10-29); facts (product, modality, date, price, amount, currency, batch); client/contract kept only when cross-checked; rule-based knowledge graph (built into the bundle, no longer loaded to PG — [mcp.md#mc-12](mcp.md#mc-12)); embeddings local (e5, bge-m3) or internal `api`.
- Files: `pipeline/transform/structure/build_bundle.py`, `chunking.py`, `facts.py`, `draft_terms.py`, `common/ai/embed.py`.
- Status: done

## pl-07
Load to pgvector. Why: the search server reads PG.
- What: tables `load_run`·`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + view `v_chunk_source` (Alembic only); docs already loaded are skipped by `file_path` (no sha column — changed content at the same path is skipped too unless `--replace`); `--prune` removes stale rows; named indexes (`index_id`). Vectors live only in pgvector (EDW vector insert deleted 10-29 — [ops.md#op-03](ops.md#op-03)).
- Files: `pipeline/load/pgvector_load.py`, `pipeline/load/index.py`, `common/store/db/migrations/`.
- Status: done

## pl-08
Struct DB and document registry. Why: contracts, clients and doc versions answer structured questions and drive incremental runs.
- What: `contract_master`·`client_master`·`prod_master`·`doc_contract_link` (scored linker)·`doc_location`·`doc_registry`·`doc_hidden`·`doc_table`·`doc_cell`; PG or SQLite.
- Files: `pipeline/load/structured.py`, `common/store/structdb.py`.
- Status: done

## pl-09
Publish parse results. Why: other teams read results from Object Storage + `AI.ParsingMeta`.
- What: upload representative `.md` + raw results (never originals) to Object Storage, INSERT-only `AI.ParsingMeta` rows, refuse publishing to the originals' bucket, DRM/failed docs to an excluded report.
- Files: `pipeline/load/publish_parse_result.py`, `pipeline/load/parsing_meta.py`, `docs/operations/parsing_meta_mssql.sql`.
- Status: done

## pl-10
Orchestration. Why: the server runs thousands of documents unattended.
- What: CLI `parse`·`structure`·`load`·`night` (deadline, resumes next night)·`run-stack`·`compare-parse`·`compare-all`·`set-stack`·`show-stack`·`set-sources`·`show-sources`·`smoke`·`selftest`; image entrypoint adds `dedup`·`prepare`·`publish`·`full`·`serve-trigger`·`migrate`·`check` (`deploy/docker/entrypoint.sh`); server flow runner (EDW listing, 12 ahead, light/medium/vlm lanes, per-doc container, yields to `parse_document` jobs); trigger server (`/jobs`, `/upload`, Bearer); per-doc parallel parse.
- Files: `pipeline/cli.py`, `deploy/host/scripts/run_docs.py` (server only — never run on PC), `pipeline/trigger_server.py`, `pipeline/parse_parallel.py`, `docs/requirements/run_docs_req.md`, `docs/architecture/run_docs_design.md`.
- Status: done

## pl-11
Model calls, cost and external-send guard (shared). Why: closed-network servers must never call external models; PC calls must stay cheap.
- What: OpenAI-compatible roles llm/vlm/ocr_vlm/embed (rerank removed 10-29); servers (dev/prd) refuse external models; external send needs `*_ALLOW_EXTERNAL` + `RUN_ENV=local`; budget, call caps, RPM, spend ledger; response cache; fake LLM for tests.
- Files: `common/ai/guard.py`, `common/ai/llm.py`, `common/ai/adk.py`, `common/config/settings.py`.
- Status: done

## pl-12
Document registry upsert and publish guard. Why: registry upsert has a PG syntax error (C-54 ①); the publish guard is off because the server does not upload `source.json` (C-54 ②).
- Files: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `tests/server/pipeline/test_publish_guard.py` (known fail).
- Decided (user 10-30 grill): ① keep the registry and fix it — the PG translation of `INSERT OR REPLACE` (`structdb._pg_sql` regex vs multi-line SQL in `registry.apply`); re-key to `s3_key` with [pl-25](#pl-25). New-doc detection stays FileStorageMap vs ParsingMeta ([pl-23](#pl-23)). ② publish guard reads EDW `AI.ParsingMeta` (`source_key` + `rep_bucket`/`rep_key`) instead of `source.json` sidecars: same doc → overwrite the same file (no `-2`/`-3.md` copies); a different source mapping to the same result key → refuse. Then `test_publish_guard` passes → remove it from `deploy/release/known_fail.txt`.
- Status: todo — after [pl-25](#pl-25).

## pl-13
`load --prune` deletes skipped documents. Why: unchanged docs that were skipped are pruned too (C-60).
- Files: `pipeline/load/pgvector_load.py`.
- Decided (user 10-29 grill): load only adds/updates — never deletes. Skipped (existing) docs stay. Docs deleted at the source and parse failures are only logged locally (cause + duration), no automatic removal. Drop the prune path from `load` and its callers (`pipeline/cli.py` load, the index builder `--pg`).
- Status: dev — `feature/load-no-prune`: `prune`·`--prune`·`PRUNE_*` 설정 없앰(옛 설정 칸은 경고만), `cli load`·`run-stack`·색인 빌드 `--pg`가 더는 안 붙임, `--no-prune`은 옛 호출 호환으로 받기만, 색인 빌드 `--pg`는 `--replace`로(다시 빌드 때 고침). 남은 한계: `file_path`가 바뀐 같은 내용은 옛 행이 남음(사람이 지움 — 사용자 확인). 시험 `tests/server/pipeline/test_pl13_no_prune.py`. 검토 등급 A(서버 적재 동작).

## pl-14
`pgvector_load deploy` backfill reads removed `doc.client`. Why: `backfill_chunk_clients` fails after the 10-20 reduced schema (tables and indexes are still created).
- Files: `pipeline/load/pgvector_load.py`.
- Status: done (10-30, `feature/search-path-fixes`) — backfill은 남기고(사용자 10-30) `doc.clients`만 읽음(없는 `doc.client` 안 고름, `_doc_row_clients`도 `clients`만 받음). NULL인 청크만 채우고 멱등인 것은 그대로. 동작은 같음 — 축소 스키마의 고객 라벨은 원래 `clients`에만 있음. 시험: `tests/server/pipeline/test_pl14_backfill.py`(가짜 DB, 이미지) · `tests/general/pipeline/test_pl14_deploy.py`(실 PG 임시 스키마에서 `deploy()` — PG 설정 없으면 건너뜀).

## pl-15
`pipeline structure`/`load` contract check rejects new bundles. Why: `contract.py` `DOC_KEYS` still expects removed keys (the server does not use these modules).
- Files: `common/core/contract.py` (hand-off fingerprint — human review), `pipeline/cli.py`.
- Status: todo

## pl-16
`PIPE_EMBED=none` builds `vector(0)`. Why: dimension 0 cannot create the table, so structure without embeddings fails.
- Files: `pipeline/transform/structure/build_bundle.py`, `pipeline/load/pgvector_load.py`.
- Status: todo

## pl-17
Parse step location — `extract` or `transform`. Why: moving it changes code_fp p0; cheapest before the first deployment (C-61).
- Decided (user 10-29 grill): move `pipeline/extract/{engines/,run_all.py,parse_one.py}` → `pipeline/transform/parse/`; rename `run_all.py` → `run_parse.py` (it only parses docs × engines; "run all" reads like e2e). `extract/` keeps source · rdb_discover · dedup · prepare. One commit moves, a second renames (CLAUDE.md §1). Keep engine fingerprints via `_LEGACY_NAMES`; code_fp p0 changes — free now because the first load is a full e2e ([pl-23](#pl-23)).
- Files: `pipeline/extract/`, `pipeline/transform/`, `common/core/artifacts.py` (`LAYER_CODE`), `pipeline/cli.py`, docs and command tables.
- Status: todo — review grade A (fingerprints).

## pl-18
`night`/`full` exit 0 after a midway stop. Why: schedulers cannot see the failure (C-33).
- Files: `pipeline/cli.py` (`night`), `deploy/docker/entrypoint.sh` (`full`).
- Status: todo

## pl-19
compose `index_a`/`index_b` fail when run to the end (C-32).
- Files: `deploy/host/`.
- Status: todo

## pl-20
Engine stack snapshot file approach review (C-50).
- Files: `pipeline/config.py` (`paths.stack_snapshot`), `docs/architecture/pipeline_stack.md`.
- Status: todo

## pl-21
Deferred settings removal. Why: unused/retired settings whose removal changes fingerprints, so they wait for the next image version: `common.paths.korean_font` (settings.py → every layer code_fp).
- Also (user 10-29 grill): remove `common.paths.eval_sets_dir` / `paths.EVAL_SETS_DIR` (and its cases in `tests/server/common/test_paths.py`) — the only reader is `validation/e2e/stack_matrix.py` (old sets, [e2e.md#e2-10](e2e.md#e2-10)). The folder `valid_env/eval_sets/` is deleted together with its doc references in [doc.md#do-03](doc.md#do-03) (no code reads its files); eval data may come back later under `tests/`.
- Files: `common/config/settings.py`, `pipeline/config.py`, `pipeline/extract/run_all.py`, `common/core/paths.py`.
- Status: todo — bundle with the next fingerprint-changing release.

## pl-22
Remove the parse phase concept (user 10-29). Why: phases 1/2/3r re-ran engines with tiny per-page limits and pushed timeouts to later passes; the `need_vlm` rule and OCR engines made image docs slow and duplicated the page VLM.
- What: each document runs its stack engines (max 2 per type — more is a config error in `stackcfg.over_limit`) in parallel, one isolated child per engine; documents in parallel via `--workers` and `--procs` (doc shards). Limit per doc×engine = pages × `pipeline.extract.text_page_sec` (10) or `vlm_page_sec` (120) for VLM engines, `warmup_sec` floor for an engine's first doc, plus `isolate_overhead`; on timeout one retry with the limit doubled, then a failure record. Old phased timeout records are retried. OCR engines (`rapidocr`, `rapidocr_ko`) run only with `pipeline.extract.ocr_engine` (default off) — image/scan docs get the VLM engine only; the stack table is unchanged. Scan pages inside text PDFs: no `.pdf_image` engines any more; represent fills those pages from page VLM (`vlm_page.page_text_pages`, scan-signal pages only, parallel). Image/scan docs: one VLM pass per page — when the representative is a VLM engine with non-empty text on an image/scan type (`.pdf_image`, png, jpg — same type keys as run_all), represent skips page VLM and marks whole-page figures as covered (no figure VLM, also without `vlm_page`); page VLM runs only when `PARSE_POST` has `vlm_page`, once per doc (failed pages are not re-called). VLM engine children get `VLM_TIMEOUT` = min(`models.vlm.timeout`, `vlm_page_sec`). Batch engine children run at low priority (`pipeline.extract.low_priority` — nice +10 / Windows BELOW_NORMAL; only within one session/autogroup, containers follow cgroup CPU weights — C-65 ⑥); the parse service (`parse_document`) turns that off and uses its own limits (`pipeline.service.parse_mcp.text_page_sec` 1, `vlm_page_sec` 60, `warmup_sec` 20 — cold engine start) and kills the whole process group on job timeout. `PARSE_MCP_OCR` merged into `PARSE_OCR_ENGINE`. Known loss: AD47 number correction on 'hidden_overlap' pages (gaps §1); "covered" is per document — when it holds, pages the VLM engine left blank get no page VLM, and embedded figures on text pages of a mixed `.pdf_image` get no figure VLM. Removed: `--phase(s)`, `--rescue`, `--vlm-all`, `--need-vlm`, `--timeout`, `PARSE_PHASES`, `PARSE_PHASE_SEC`, `PARSE_MCP_OCR`, `PHASE2_FAILED`.
- Files: `pipeline/extract/run_all.py`, `pipeline/stackcfg.py`, `pipeline/config.py`, `pipeline/cli.py`, `pipeline/stream.py`, `pipeline/parse_parallel.py`, `pipeline/mcp_parse_service.py`, `pipeline/transform/represent/represent.py`, `pipeline/transform/figures/vlm_page.py`, `deploy/host/scripts/run_docs.py`.
- Tests: `tests/server/pipeline/test_run_all.py` (over_limit, OCR switch, page_timeout, old phase timeout), `tests/server/pipeline/test_vlm_page.py` (`pick_pages`), `tests/general/pipeline/test_represent.py` (page-VLM fill).
- Open: text engines are not split per page (one child per doc×engine; per-page parallelism only inside the VLM engine via `VLM_CONCURRENCY`).
- Status: dev — branch `feature/r2-phase`; server check pending (refactor.md C-65). VLM concurrency knobs not merged (separate follow-up).

## pl-23
Incremental runs only; full reparse = explicit full e2e (C-52, C-08). Why: engine/handoff/code fingerprints changed for every doc; an automatic reparse of all docs would blow the nightly window.
- Decided (user 10-29 grill): nightly and `run_docs` process **new** docs only, even after a fingerprint change. "New" = `AI.FileStorageMap.s3_key` not yet in `AI.ParsingMeta` (s3 key only — no update-time check; `run_docs` already works this way). A full reparse runs only when a person starts a full e2e (occasional — after logic changes, then results are reviewed). The first load of this version is one full e2e.
- Decided (user 10-30 grill): the nightly batch stays OFF (systemd timer and `pipeline.host.nightly.enabled` false); a person turns it on later in settings.yaml. No run time is fixed now.
- Not used now: FileStorageMap update time — assumed column `last_modified_time`, to be added to the EDW example later ([pl-25](#pl-25)).
- Files: `deploy/host/scripts/run_docs.py` (done set), `pipeline/cli.py` (`night` — check it does the same).
- Status: todo

## pl-24
Per-doc order in `run_docs`: parse → silver publish → delete original → gold (structure + load). Why: today publish waits for gold, and `cleanup_doc` deletes the original even on failure.
- Decided (user 10-29 grill): originals are downloaded from Object Storage to the collection server, parsed, and deleted only after silver publish succeeds. Parse failure → keep the original, log cause + duration locally only, nothing in EDW. Gold failure → the EDW row stays with `gold_status` = failed (+ reason); gold can be rebuilt from silver.
- New EDW column `AI.ParsingMeta.gold_status` (pending · ok · failed) + reason — DDL to the DB owner (company DB, not Alembic) — review grade A. The reduced ParsingMeta column list is in [pl-25](#pl-25).
- Local test runs from `valid_env/` copy docs into a temp folder first and run there (never in place).
- Files: `deploy/host/scripts/run_docs.py` (`doc_flow`, `cleanup_doc`, done query), `docs/operations/parsing_meta_mssql.sql`, publish (`parsing_meta`).
- Status: todo — after [pl-25](#pl-25).

## pl-25
DB schema spec, written before pl-26·pl-23·pl-24 are built. Why: table/column definitions are spread over Alembic migrations (`common/store/db/migrations/versions/`), `docs/operations/parsing_meta_mssql.sql` (ParsingMeta only) and code reading `AI.FileStorageMap` (no definition); the 10-20 reduced schema is only half applied in code (mc-10, mc-11, pl-14, pl-15).
- Decided (user 10-29 grill): one doc `docs/architecture/db_schema.md` — per table: columns, type, meaning, which code writes/reads it — for EDW `AI.FileStorageMap` (id, s3_key, original_filename, file_size, `last_modified_time` assumed), `AI.ParsingMeta` (+ `gold_status`), pgvector search schema and `struct`. The reduced 10-20 schema is the truth; code that disagrees is fixed in mc-10/mc-11/pl-14/pl-15. One test compares the doc's columns with the migrations and the mssql sql. The user and the DB owner sign it off before implementation; the DB owner gets this doc.
- Decided (user 10-30 grill — gold schema):
  - Keys: `s3_key` is the only document key. Drop sha256 `doc_key`; re-key registry, `doc_hidden` and `doc_contract_link` to `s3_key` (unblocks [mcp.md#mc-14](mcp.md#mc-14) and [mcp.md#mc-15](mcp.md#mc-15) — rep_uri lookup by `ParsingMeta.source_key`). Search `doc`/`chunk` must carry `s3_key`.
  - Gold now: ONE table set (`doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat`). Later (design now, build later): every table per source system — SFDC · CRMS · LAS · Other, columns may differ per source; at that split MCP `search` requires a source (one contract change, new version, grade A). No optional `source` input before then.
  - Source = `AI.FileStorageMap.source_system`; empty or not SFDC/CRMS/LAS → `Other`; mismatch with the s3_key prefix → log warning only.
  - SFDC-only columns (`sf_acc_name`, `sf_op_id`, `sf_op_name`, `project_code__c`) stay in the one `doc` table (empty for other sources); they move to the SFDC doc table at the split.
  - `load_run` and the Alembic version table stay in gold, shared after the split. `chunk` keeps `source_system` and `clients[]` (client isolation, source filter).
  - `AI.ParsingMeta` keeps only read columns: `source_system`, `source_key` (s3_key), `parse_date`, `parse_status`, `status`, `status_at`, `rep_bucket`, `rep_key`, plus new `gold_status` + reason ([pl-24](#pl-24)). Drop `doc_key` and the 14 unread columns.
  - `struct`: delete the document-derived tables `doc_location`, `doc_contract_link`, `doc_table`, `doc_cell` and their writers/readers (structured link/tables, `load_tables_db`, `find_table_cells`, aggregate `doc_link_list`/`table_cell_list`/`doc_location_list`, `AG.struct` server path) — that content lives only in chunk text. Keep `stack_version`/`source_version` (read at MCP start).
  - Masters `contract_master`, `client_master` move to a SEPARATE Postgres (own connection setting, not the search PG), filled by a person from CSV (`structured load` style). Readers `gen_roster` (client_master) and `terms.py` (contract_master) use the new connection.
  - EDW vector tables (`chunk_vec`, `edw_insert`, `edw_search`) are removed by PR #5.
- Decided (user 10-30 — client fields): one client per doc comes from the EDW join chain (scalar). Clients found in the document text are a separate list. The MCP client filter uses ONLY the EDW client; a doc without an EDW client is excluded when a client filter is set. Using text-found clients in the filter is later ([pl-28](#pl-28)). Today both are mixed in `clients[]` (`build_bundle.infer_clients`) and `chunk.clients` drives the hard filter — fix with this row.
- Naming rule (user 10-30): any field that can come from EDW and from document parsing gets two columns with the origin in the name (e.g. `client_edw`, `clients_doc`); `db_schema.md` fixes the exact suffixes.
- Split timing (user 10-30): B — build ONE table set now; the per-source split is [pl-28](#pl-28).
- Files: `docs/architecture/db_schema.md` (new), `docs/index.md`, `common/store/db/migrations/versions/`, `docs/operations/parsing_meta_mssql.sql`, `tests/server/common/` (one test).
- Status: dev — `docs/architecture/db_schema.md` 설계안 + 시험 `tests/server/common/test_db_schema.py`(`feature/db-schema-spec`) — 사용자·DB 담당자 승인 대기(코드·스키마 변경 없음).

## pl-26
`full` always publishes; no "skip publish" path (C-31). Why: help text said "no EDW load" while `full` published, and it ignored `NIGHTLY_PUBLISH`.
- Decided (user 10-29 grill): publish (silver → Object Storage + EDW) is the default and only mode — remove `--no-publish` and `pipeline.host.nightly.publish`. Publish targets are required settings; missing → refuse to start.
- Targets per `RUN_ENV`: `local`·`dev` pick one of (a) local path (folder for Object Storage, file DB for EDW) or (b) real connection info (API/DB); `prd` real connection only (`stage` was dropped from RUN_ENV — op-02). The PC keeps the CLAUDE.md §4 guard (no prod EDW/OS from the PC).
- Files: `pipeline/cli.py` (`night`, `full`), `deploy/docker/entrypoint.sh`, publish in `pipeline/load/`, `pipeline/config.py`, `docs/operations/server-guide.md`.
- Status: todo

## pl-28
Per-source gold tables (designed in [pl-25](#pl-25), built later). Why: SFDC · CRMS · LAS · Other have different metadata; one table per source keeps columns clean.
- What (user 10-30): every gold pair — `doc`, `chunk` and the BM25 tables (`chunk_term`, `term_stat`, `corpus_stat`) — exists once per source (4 sets); columns may differ per source (SFDC-only `sf_*`, `project_code__c` move to the SFDC doc table). `load_run` and the Alembic version table stay shared. MCP `search` then requires a source — one contract change, new version, review grade A. Also later: allow text-found clients (`clients_doc`) in the client filter.
- Status: todo — later version; needs a full reload.
