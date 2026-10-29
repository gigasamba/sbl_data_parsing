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
- What: per file type, every engine in the stack runs (not a fallback chain); phases 1 (no model) → 2 (phase-1 timeouts) → 3 (VLM, `3r` = only docs with no successful engine); per-engine isolation; engine stack versioned in `struct.stack_version` (PC: `pipeline_stack.json`). Types: pdf (text/image), doc(x), ppt(x), xls(x/m), hwpx, txt, html/htm, mht, eml, msg, png, jpg. Not supported: old `.hwp`, zip.
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
- What: tables `load_run`·`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + view `v_chunk_source` (Alembic only); docs already loaded are skipped by `file_path` (no sha column — changed content at the same path is skipped too unless `--replace`); `--prune` removes stale rows; named indexes (`index_id`). Vectors live only in pgvector (EDW vector insert deleted 10-29 — [ops.md#op-02](ops.md#op-02)).
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
- What: OpenAI-compatible roles llm/vlm/ocr_vlm/embed (rerank removed 10-29); servers (dev/stage/prd) refuse external models; external send needs `*_ALLOW_EXTERNAL` + synthetic-corpus truth file; budget, call caps, RPM, spend ledger; response cache; fake LLM for tests.
- Files: `common/ai/guard.py`, `common/ai/llm.py`, `common/ai/adk.py`, `common/config/settings.py`.
- Status: done

## pl-12
Document registry upsert and publish guard. Why: registry upsert has a PG syntax error (C-54 ①); the publish guard is off because the server does not upload `source.json` (C-54 ②).
- Files: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `tests/server/pipeline/test_publish_guard.py` (known fail).
- Status: todo — design in the next version.

## pl-13
`load --prune` deletes skipped documents. Why: unchanged docs that were skipped are pruned too (C-60).
- Files: `pipeline/load/pgvector_load.py`.
- Status: todo — decide whether to fix (one line, changes server load behavior).

## pl-14
`pgvector_load deploy` backfill reads removed `doc.client`. Why: `backfill_chunk_clients` fails after the 10-20 reduced schema (tables and indexes are still created).
- Files: `pipeline/load/pgvector_load.py`.
- Status: todo

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
- Status: todo — user decision.

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
Deferred settings removal. Why: unused/retired settings whose removal changes fingerprints, so they wait for the next image version: `common.paths.korean_font` (settings.py → every layer code_fp), `pipeline.paths.paddle_python` and `pipeline.eval.phase_report_legacy` (read in `run_all.py` → p0 of every engine).
- Also: the `EVAL_SETS_DIR` PC default in `common/core/paths.py` still says `valid_env/unstructured` (deleted 10-29, [e2e.md#e2-09](e2e.md#e2-09)) — change to `valid_env/eval_sets` with `tests/server/common/test_paths.py`; until then set `common.paths.eval_sets_dir` on the PC.
- Files: `common/config/settings.py`, `pipeline/config.py`, `pipeline/extract/run_all.py`, `common/core/paths.py`.
- Status: todo — bundle with the next fingerprint-changing release.
