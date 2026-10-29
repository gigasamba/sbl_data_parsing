# e2e — end-to-end runs, tests and evaluation (PC + release gate)

Area of [PRD.md](../PRD.md). Covers how a change is proven: smoke runs, test layers, quality evaluation, answer checks, test data and the image release gate.
One anchor per feature: what, why, code files. Open items carry a `Status:` line with progress.

## e2-01
PC smoke run — parse → embed → migrate → load → search. Why: proves the whole chain on 2–3 documents before a release.
- What: README §4-4 steps; per-run values with `--set`; embedding cache `output/edw/embed_cache.sqlite`.
- Files: `pipeline/cli.py` (`smoke`), `mcp_server/cli/ask.py`, `valid_env/eval_sets/list-smoke10.txt`.
- Status: done

## e2-02
Test layers. Why: release decision must run inside the image without network.
- What: `tests/server/` (image release gate, run by `pipeline.cli selftest` through `tests/runner.py`), `tests/general/` (PC only: PG, Docker, slow); known failures listed, XPASS warns to remove them.
- Files: `tests/runner.py`, `tests/conftest.py`, `deploy/release/known_fail.txt`.
- Status: done

## e2-03
Parse quality evaluation. Why: engine/stack changes must not lower parse accuracy.
- What: CER, value/table recall vs `criteria.json` and human gold, auto questions from cross-confirmed values, stack beam search, stage board and stack report.
- Files: `pipeline/eval/score_gold.py`, `auto_questions.py`, `run_combo.py`, `run_board.py`, `stack_report.py`, `pipeline/transform/represent/parse_qa.py`, `resources/config/criteria.json`.
- Status: done

## e2-04
Search evaluation. Why: retrieval changes must not lower hit rates.
- What: hit@1/5/k, value_in_evidence, p50/p95 latency, `via` mix; tool smoke for the 4 tools; HTML/xlsx report.
- Files: `mcp_server/cli/mcp_eval.py`, `mcp_server/cli/mcp_smoke.py`, `mcp_server/cli/qa_report.py`, `mcp_server/cli/search_checks.py`.
- Status: done

## e2-05
Answer check (PC only). Why: the MCP returns evidence only; answers built on it need a citation check.
- What: `rag_qa` agent calls `search`/`edw_meta`/`query_edw`, deterministic citation check.
- Files: `validation/e2e/answer_gen.py`, `valid_env/answer_test/rag_qa/`.
- Status: done

## e2-06
Stack and model comparison. Why: choose engines and models by measured results and cost.
- What: stack matrix and model matrix runs with cost estimates; paid calls need approval (CLAUDE.md §7).
- Files: `validation/e2e/stack_matrix.py`, `validation/e2e/model_matrix.py`.
- Status: done

## e2-07
Search check page. Why: humans inspect evidence in a browser.
- What: local page proxying to the MCP server and pgvector (default port 8790 — `mcp.dev.ui_port`; README's example settings use 8791).
- Files: `validation/search_ui/serve.py`, `validation/search_ui/start_mcp.sh`, `start_ui.sh`.
- Status: done

## e2-08
Image build and release gate. Why: the server must get images that passed selftest.
- What: build/ship script, selftest gate reads the `[판정]` line, overlay patch for code-only changes.
- Files: `deploy/release/build_ship.sh`, `deploy/release/selftest_gate.sh`, `docs/operations/release-and-patch.md`.
- Status: done

## e2-09
PC test data from PwC_Structure `valid_env`. Why: PwC lays test data out like the server — `object_storage/<system>/<uuid>/<file>` documents, `eval_sets/` gold and run lists, `edw/` synthetic EDW sqlite — and this repo had no EDW stand-in.
- What (10-29): `valid_env/unstructured/` deleted (781 files, 40 MB); brought `edw/` (sql + sqlite), `eval_sets/`, `object_storage/{CRMS,SFDC}` + `test_doc_purpose.md` from PwC HEAD with `git archive` (33 documents, sha256 match `object_keys.csv`); `unstructured/synth-meta-rdb/meta/` moved to `edw/meta_rdb/` because three server tests read it.
- Files: `valid_env/README.md`, `.gitattributes`, `tests/server/mcp/test_internal_docs.py`, `tests/server/mcp/test_search_svc.py`, `tests/server/pipeline/test_source.py`, README §4-4.
- Left: `EVAL_SETS_DIR` default → [pipeline.md#pl-21](pipeline.md#pl-21); PC tools that name old sets → [e2-10](#e2-10).
- Status: done

## e2-10
Minimize PC evaluation tools, then keep or delete their settings. Why: about 50 settings exist only for PC tests and experiments (`common.dev.*`, `pipeline.dev.*`, `pipeline.eval.*`, `mcp.dev.*`, `runtime.exp_*`, `graphiti.*`).
- Files: `validation/e2e/`, `pipeline/eval/`, `mcp_server/cli/`, `common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`.
- Decided (user 10-30 grill): keep ONLY `validation/search_ui` (search check page) and `valid_env/answer_test` (answer check). Delete stack comparison, automatic question generation, scorers for deleted sets (e.g. `chart_values_score.py`) and their settings.
- Status: todo

## e2-11
PC general test known failures. Why: 7 general tests fail since before the refactor (C-54 ①, C-58): 3 read the shared dev PG (use temp SQLite/schemas), 2 need missing packages/modules (mark skip or fix), 1 needs EDW, 1 is a `find_table_cells` assertion in `test_structured`.
- Files: `tests/conftest.py` (`GENERAL_KNOWN_FAIL`), `tests/general/`.
- Progress 10-29 (`feature/test-cleanup`): the 3 shared-dev-PG failures are fixed — PC test subprocesses no longer read the dev root `settings.yaml` (`pipeline/cli.py` `case_env` gives a test-only base `run_env: local`); `test_structured`, `test_structdb`, `test_aggregate` removed from the list. Left: `test_kg_external`, `test_run_combo`, `test_edwdb`, and `test_pub_registry` (real PG on purpose, C-54 ①).
- Status: partly done

## e2-12
EDW value answers fail citation verification. Why: answers citing `query_edw` values are recorded as verify failures (C-56 M-1).
- What: choose (a) a `kind="edw"` citation rule or (b) remove EDW values from the prompt.
- Files: `valid_env/answer_test/rag_qa/`, `validation/e2e/answer_gen.py`.
- Decided (user 10-29/10-30 grill): keep as is — no change.
- Status: done

## e2-13
PC Docker smoke stops at the retriever. Why: depends on [mcp.md#mc-10](mcp.md#mc-10).
- Files: `valid_env/docker/compose.test.yml`, `valid_env/docker/smoke_test.sh`.
- Fixed with [mcp.md#mc-10](mcp.md#mc-10) (PR #12); re-run the smoke after it merges.
- Status: todo — mc-10은 10-30에 고침(`feature/search-path-fixes`). PC Docker 스모크를 다시 돌려 검색까지 가는지 확인할 것.

## e2-14
Release tests live only inside the image. Why: an overlay patch cannot update them (C-53).
- Files: `deploy/docker/Dockerfile`, `tests/server/`.
- Status: todo

## e2-15
Agent test package path points at upstream. Why: `resolve_agent_dir` looks for `example_agentic` under `dev_tools/unit_test/fixtures/` (not in this repo), so the `run_agent` group in `test_adk` is skipped and `test_paths` asserts that path.
- Files: `common/core/paths.py` (every-layer dependency → code_fp), `tests/server/common/test_adk.py`, `tests/server/common/test_paths.py`.
- Status: todo — fix with the next fingerprint-changing release.

## e2-16
Search check page shows fixed text "10 documents (20 chunks)".
- Files: `validation/search_ui/index.html`.
- Status: todo

## e2-17
Remove unused functions found by the 10-29 audit. Why: dead code costs reading time and lint upkeep.
- Removed 10-29 (no caller, fingerprints unchanged): `parse_env_file` (`common/config/migrate.py`), `_lane_push` (`deploy/host/scripts/run_docs.py`), `_bg_img` (`mcp_server/routers/dispatch.py`), `_scan_paren` (`mcp_server/services/edw_query.py`), `_local_sidecar_name` (`pipeline/load/parsing_meta.py`), module `pipeline/tools/check_runlog.py` (one-time runs.jsonl lock check — restore from git if needed).
- Left: `fields_table` (`common/config/settings.py`) — wait for the next fingerprint release (`checklist` went with `decompose.py`, 10-29); tests only — `do_evidence_image`, `do_related` (`internal_docs.py`), `eval_labels` (`qtype.py`), `availability_note` (`stack_report.py`), `raster_chart_values` (`chart_values.py`, layer p1), `pool_distractor_files` (`stack_matrix.py`).
- Decided (user 10-30 grill): delete the tests-only ones too, with their tests ([e2-18](#e2-18)).
- Status: todo

## e2-18
Delete code with no requirement (gaps §2, user 10-30 grill). Why: unused paths still read removed columns and cost upkeep.
- Delete: `internal_docs.py` hidden-doc functions (6, incl. document get/list that still SELECT removed doc columns), wiki tools, external KG adapter, tests-only functions ([e2-17](#e2-17)), scorers for deleted eval sets ([e2-10](#e2-10)).
- Keep: `PARSE_STREAM`, shadow mode, `MCP_EVIDENCE_PATHS`, `SEARCH_TIE_BREAK`, SQLite fallback, registry CLI, mail attachments, glossary/roster tools, nightly timer, `os_put`, server checks.
- Rule: MCP tool names and input/output stay unchanged; stop and ask if one would change.
- Status: todo
