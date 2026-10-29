# gaps — where code and requirements differ, unused code, disabled features

Linked from [PRD.md](../PRD.md). Code vs [mcp.md](mcp.md), [pipeline.md](pipeline.md), [e2e.md](e2e.md), checked 10-29.

## 1. Code does not match the requirement

Rows with an ID are open defects; the rest are behaviors to know.

| What the requirement expects | What the code does | Where | ID |
|---|---|---|---|
| 숨김 문서는 검색에서 빠짐 | 숨김 키(sha256)를 검색 키(`file_path`)와 비교 → 안 빠짐 | `pgsearch.py`, `local.py` | mc-14 |
| 근거에 파싱 결과 경로(`rep_uri`) | ParsingMeta를 `file_path`로 찾음(그쪽 키는 sha256) → 늘 비어 있음 | `shaping.py` | mc-15 |
| Aggregation runs without errors | selects removed columns → "aggregation path error" note on every result | `aggregate.py` | mc-11 |
| Fact aggregation answers | `doc_fact` is not loaded any more → that path returns nothing | `aggregate.py`, `pgvector_load.py` | mc-12 |
| Query log in PG | inserts into a `qa_log` table no migration creates (error swallowed; jsonl log works) | `search_svc.py`, `0001_search_base.py` | mc-13 |
| Registry upsert, publish guard | upsert has a PG syntax error; guard off (no `source.json` on the server) | `structdb.py`, `publish_parse_result.py` | pl-12 |
| `--prune` removes stale rows only | also deletes skipped (unchanged) documents | `pgvector_load.py` | pl-13 |
| `pipeline structure/load` modules accept new bundles | contract `DOC_KEYS` rejects them (server does not use these modules) | `common/core/contract.py` | pl-15 |
| Structure without embeddings | `PIPE_EMBED=none` → `vector(0)` table fails | `build_bundle.py`, `pgvector_load.py` | pl-16 |
| Midway stop is visible | `night`/`full` exit 0 after a midway stop | `pipeline/cli.py`, `entrypoint.sh` | pl-18 |
| compose `index_a`/`index_b` run to the end | they fail | `deploy/host/` | pl-19 |
| Evaluation sets path default | `EVAL_SETS_DIR` default still `valid_env/unstructured` (deleted) — set `common.paths.eval_sets_dir` on the PC | `common/core/paths.py` | pl-21 |
| PC tests pass | 7 general tests fail since before the refactor | `tests/conftest.py` | e2-11 |
| Answers citing `query_edw` values pass citation check | recorded as verify failures | `valid_env/answer_test/rag_qa/` | e2-12 |
| PC Docker smoke reaches search | stopped at the retriever (mc-10 — 10-30 고침, 다시 돌려 확인 필요) | `valid_env/docker/` | e2-13 |
| Agent test package found | looks under upstream `dev_tools/unit_test/fixtures/` → `run_agent` test group skipped | `common/core/paths.py` | e2-15 |
| Search page shows real counts | fixed text "10 documents (20 chunks)" | `validation/search_ui/index.html` | e2-16 |
| Load skips only unchanged documents | skips by `file_path` (no sha column) — changed content at the same path is skipped too unless `--replace` | `pgvector_load.py` | pl-07 |
| `query_edw` table allowlist | off by default on mssql (`EDW_QUERY_TABLES_STRICT=0` → every schema except system catalogs) | `edw_query.py` | mc-06 |
| Scan-page number correction (AD47 — hidden text over an image, e.g. 430.000 vs 430,000) | page VLM has no word boxes, so 'hidden_overlap' pages keep the original text — no OCR fallback (user 10-29: accept for now) | `represent.py` `fill_scan_pages` | pl-22 |
| Hard filters on every store | PG store only; local bundle: filters-only returns an error, question + filters searches unfiltered | `search_svc.py` | mc-01 |
| Knowledge graph searchable | built into the bundle, not loaded to PG, no search method reads it now | `build_bundle.py` | pl-06 |
| DRM/password files decrypted in the flow | decryption is a manual CLI (`python -m pipeline.extract.secure_docs decrypt`) | `secure_docs.py` | pl-02 |
| EDW vector load | `edw_insert` exists but nothing calls it (CLI, compose, run_docs) | `pipeline/load/edw_insert.py` | — |

## 2. Code with no requirement — keep (write an anchor) or delete?

**mcp**
- EDW vector search — `usp_vec_topk`, `EdwClient`; only `ask --edw`/`--edw-client`, the server builds its retriever with EDW off. `mcp_server/services/search/edw_search.py`, `mcp_server/cli/ask.py`, `common/store/edwdb.py`.
- Evidence parse-result paths from `AI.ParsingMeta` (`MCP_EVIDENCE_PATHS`, on). `shaping.py`.
- Evidence image crops and internal lookups not exposed as tools: `do_evidence_image`, `do_get_image`, `do_related` (tests only), `do_lookup_term`, `do_get_document`, `do_list_documents`. `internal_docs.py`.
- Tie-break by question entities (`SEARCH_TIE_BREAK`, on). `search_svc.py`.
- PG stand-in (SQLite when no PG is set — PC). `common/store/pg_standin.py`.
- Document registry CLI. `mcp_server/cli/registry_cli.py`.

**pipeline**
- EDW vector insert with no caller — `pipeline/load/edw_insert.py` (`EDW_LOAD=0`).
- Email attachments: recursive `.eml`/`.msg` attachment parse (depth 1, 20 MB, 10 files) and quoted-thread folding (`ATTACH_*`). `represent/attachments.py`.
- Streaming parse — fetch a small batch, parse, delete originals at once (`PARSE_STREAM=0`; nothing turns it on, run_docs does not use it). `pipeline/stream.py`.
- Shadow mode — asks an LLM what it would decide at each recorded rule decision and logs agree/disagree to `parse/_shadow/`; never changes results; manual CLI only (`PARSE_SHADOW=0`). Not tied to the removed parse agent. `represent/shadow.py`, `pipeline/eval/parse_shadow.py`.
- Glossary and wiki tools (concept wiki, LLM glossary draft, abbreviation suggestions, roster from EDW masters). `transform/structure/wiki.py`, `wiki_draft.py`, `glossary_suggest.py`, `gen_roster.py`.
- Nightly host timer and trigger chaining (`NIGHTLY_*`, `CHAIN_STRUCTURE_URL`). `deploy/host/`, `pipeline/trigger_server.py`.
- Test upload to Object Storage (MinIO). `common/check/os_put.py`.

**shared tools** — config CLIs `common/config/`; DB tools `common/store/db/`; checks `pipeline/check_env.py`, `common/check/`.

**e2e (PC evaluation — decide together with [e2e.md#e2-10](e2e.md#e2-10))**
- External knowledge-graph adapters (LightRAG, Cognee, Graphiti/Neo4j). `pipeline/eval/kg_external.py`, `validation/e2e/graph_llm.py`.
- Gold and question drafts. `pipeline/eval/gold_draft.py`, `qa_draft.py`, `make_questions.py`.
- Scorers for sets deleted with `valid_env/unstructured`. `pipeline/eval/diagram_edges_score.py`, `chart_values_score.py`.
- Explorer HTML, server measurement pack, combo report. `pipeline/eval/explorer.py`, `server_checks.py`, `report.py`.
- Stack/model matrices that name deleted sets (`synth-4clients` …). `validation/e2e/stack_matrix.py`, `model_matrix.py`, `mcp_server/cli/mcp_eval.py`, `pipeline/eval/stack_report.py`.
- Functions only tests call: `eval_labels` (`qtype.py`), `availability_note` (`stack_report.py`), `raster_chart_values` (`chart_values.py`), `pool_distractor_files` (`stack_matrix.py`); unused `fields_table` (`settings.py`).

## 3. Off by default or needs setup

Full switch list with defaults: `settings.sample.yaml` part 2, groups "[기능 켬/끔]".

| Feature | Switch = default | Needs | Area |
|---|---|---|---|
| Hard client isolation | `SEARCH_CLIENT_HARD=0`, `SEARCH_CLIENT_STRICT=0` | — | mcp |
| Newest version first always | `SEARCH_RECENCY=1` (only "latest" questions; `2` = always) | — | mcp |
| LLM router for borderline aggregation | `SEARCH_AGG_LLM=0` | LLM | mcp |
| `query_edw` | `EDW_QUERY=1` | `EDW_QUERY_SERVER/USER/PASSWORD` or `EDW_QUERY_SQLITE` | mcp |
| `edw_meta` | — | dataset at `EDW_META_DIR` (default `/app/config/edw_meta`) | mcp |
| `parse_document` | `PARSE_OCR_ENGINE=0` (no OCR/VLM engines — `PARSE_MCP_OCR` merged 10-29) · limits 1 s/page text, 60 s/page VLM | `mcp_parse_service` running + `PARSE_SERVICE_TOKEN` | mcp |
| VLM engine, figures, page VLM | on (OCR engines off — `PARSE_OCR_ENGINE=0`, pl-22) | VLM endpoint; soffice (`SOFFICE_BIN`) for slides/shapes | pipeline |
| Streaming parse · per-doc parallel pipeline | `PARSE_STREAM=0` · `PARSE_PARALLEL_PIPELINE=0` | — | pipeline |
| Scan OCR/VLM de-dup · render-OCR signals · auto re-parse changed | `PARSE_DEDUP_SCAN=0` · `PARSE_SIGNAL_OCR=0` · `AUTO_REPARSE_CHANGED=0` | — | pipeline |
| Shadow mode | `PARSE_SHADOW=0` | LLM, manual CLI | pipeline |
| Split big tables by rows | `CHUNK_TABLE` unset (tables whole) | — | pipeline |
| LLM summaries | `EDW_SUMMARY_LLM=0` (lead text) | LLM | pipeline |
| Embeddings | image default `PIPE_EMBED=api` | `EMBED_BASE_URL`, `EMBED_MODEL` | pipeline |
| EDW vector load | `EDW_LOAD=0` | a call site (none today) + EDW settings | pipeline |
| Publish to Object Storage + `AI.ParsingMeta` | runs by default in `night`, run_docs and the image `publish` step (all pass `--apply`; `NIGHTLY_PUBLISH=1`) | `PM_BUCKET`, `PM_DB_*` (exits without `PM_BUCKET`) | pipeline |
| Nightly schedule | `NIGHTLY_ENABLED=0` | — | pipeline |
| `--prune`, create `vector` extension | opt-in · `PG_CREATE_EXTENSION=0` | — | pipeline |
| Trigger server | — | `TRIGGER_TOKEN` (refuses to start without) | pipeline |
| External (paid) models | `*_ALLOW_EXTERNAL=0`, PC only (`RUN_ENV=local`) | budget caps (`LLM_BUDGET_USD`, `LLM_MAX_CALLS`) | shared |
| Answer check, stack/model matrices | — | LLM; paid runs need approval | e2e |

Requested 10-29 "EDW and Object Storage load on by default": publish (Object Storage + `AI.ParsingMeta`) already runs by default once `PM_BUCKET`/`PM_DB_*` are set; what is off is the nightly schedule (`NIGHTLY_ENABLED=0`) and the EDW vector load (`EDW_LOAD=0`, no caller). Not changed yet — needs the user's choice (and the DB owner for EDW writes).

## 4. Removed 10-29 (user decision)

- Parse judgment agent (`PARSE_AGENT`, default shadow — it opened LLM sessions on the server without changing results) — `77433fe`.
- Search re-ranking (`SEARCH_RERANK`, `common.models.rerank`) — `34f398e`.
- LLM question decomposition (`MCP_DECOMPOSE`, `DECOMPOSE`, prompt `query_decompose`); per-client split kept — `dd3e974`.
- Search methods graph, concept, image, openviking — `9e58c71`.
- OpenViking everywhere (load, summary import, search, detection, settings) — `c07dde5`.
- `search` keeps its input schema: `methods` other than vector·bm25·id and `decompose` are accepted and ignored; responses keep `"images": []`, `"subs": []`.
