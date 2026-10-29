# Operations — logging, DB accounts (op)

Source: COMPANY governance per-project review, 10-29 (interim standard).

## op-01
JSON Lines event log for both apps. Why: today `common/core/runlog.py` writes one summary per run (`output/runlog.jsonl`) and raw console logs (`output/logs/*.log`, masked by `_mask()`); the runner writes `doc_stats.jsonl`; the MCP server writes a query jsonl. There is no common per-event line (level, request id, duration), and no log level setting.
- Steps: (1) stdlib `logging` + one small JSON formatter in `common/core/` — keys `time, level, msg, request_id, duration_ms, err`; reuse `_mask()` (no new package). (2) Log level as a **settings.yaml** item (the review's `LOG_LEVEL` env conflicts with CLAUDE.md §3; keep the old env name as alias only). (3) PC writes `logs/<app>.jsonl` (gitignored); server writes stdout. (4) Mask secrets and personal data.
- Risk: edits `common/` → code_fp may change (server reprocessing) — tell the user at design, put before/after fingerprints in the commit. Review grade A (secret handling).
- Acceptance / QA: each line parses as JSON with the required keys; a sample secret string is masked; level setting filters lines.
- Files: `common/core/` (new formatter), `common/config/settings.py`, `mcp_server/main.py`, `pipeline/cli.py`, `.gitignore`.
- Status: todo

## op-02
One EDW connection with two shared accounts (read, write). Why: user 10-29 "계정 하나로 합침" — four blocks (`common.connections.edw`, `common.connections.parsing_meta`, `pipeline.connections.rdb`, `mcp.edw_query`) each carry server/port/database/user/password for what is one EDW, so the server file repeats the same values four times.

Settled (user 10-29, grill round 1–2):
- Vectors go to pgvector only, never EDW. Delete the EDW vector path: `pipeline/load/edw_insert.py` (`usp_vec_load`), `mcp_server/services/search/edw_search.py`, the EDW branch of `retriever.py`, `common/store/edwdb.py`, settings block `common.connections.edw` (+ `EDW_LOAD`).
- ParsingMeta, FileStorageMap, RDB source tables and `query_edw` live on the same EDW server and database → one connection block.
- Two accounts, both shared: **read** and **write**. MCP server uses only read. Pipeline picks by function: reads (RDB source list, discover, roster, FileStorageMap, ParsingMeta status) → read; ParsingMeta publish (INSERT/UPDATE) → write. Host runner `run_docs.py` reads → read.
- PC stand-in: one sqlite file holding all tables (AI, CRMS, LAS, SFDC tables together); `query_edw` keeps opening it read-only.
- Old keys: no migration — the sample is regenerated and the server file is filled in again. Old fields go to `Section.REMOVED` (warning for one version, no start refusal). env-guide + refactor.md C-xx record the server step.

Decided from rules (not asked):
- Block `common.connections.rdb` (both apps use it → `common`; CLAUDE.md §1): `host`, `port`, `database`, `connect_kwargs`, `sqlite`, `read.{user,password}`, `write.{user,password}`. Driver pymssql only (the pyodbc option belonged to the deleted vector path).
- Purpose-specific items stay where they are: `PM_TABLE`; RDB `engine`/`bucket`/`columns`/filters; `query_edw` `enabled`/`tables`/`tables_strict`/limits.
- `CONN_FILE` (`EDW_CONN_FILE`, `EDW_QUERY_CONN_FILE`) removed — secrets live only in settings.yaml (§3).
- sqlite: code ATTACHes the one file under each schema alias (`AI`, `CRMS`, `LAS`, `SFDC`) so `AI.ParsingMeta`-style SQL runs unchanged. RDB source gains `engine: sqlite` for PC tests (today csv only).
- code_fp: `settings.py` and `retriever.py` (layer r) change → every layer code_fp changes; ride with this round's fingerprint change, before/after in the commit.
- Review grade A (DB accounts, operating access): human review in the PR, not Claude's.

Overlap: `deploy/host/scripts/run_docs.py` lines ~116–134 read the PM keys from raw YAML — owned by the parse-phase work; hand the new key names to that owner.
- Acceptance / QA: one table test per path (read vs write account chosen; MCP never gets write credentials; sqlite file serves PM write + query_edw read-only + RDB source read); `common.config.sample --check`, `keyscan --check`, full `pytest tests/` and `selftest` at baseline; grep for `EDW_SERVER|PM_DB_|RDB_HOST|EDW_QUERY_SERVER|usp_vec_load` = 0 outside REMOVED/history.
- Files: `common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`, `common/store/{parsing_meta_db,edwdb,mssql}.py`, `pipeline/extract/{source,rdb_discover}.py`, `pipeline/transform/structure/gen_roster.py`, `pipeline/load/{parsing_meta,edw_insert}.py`, `mcp_server/services/{edw_query,search/edw_search,search/retriever,search/shaping}.py`, `valid_env/edw/`, tests, `docs/operations/{env-guide,server-guide}.md`.
- Built: `common.store.mssql.login(role)` (accounts) · `mssql.standin(path)` (one file ATTACHed as AI·CRMS·LAS·SFDC, read-only by default) · builder `python -m validation.e2e.edw_standin` → `valid_env/edw/edw.sqlite` (the four per-schema .sqlite files removed; .sql sources kept) · `query_edw` sqlite allowlist = the nine stand-in tables. Not done (no need found): sqlite for `rdb_discover`/`gen_roster` (server tools).
- Tests: `tests/server/common/test_edw_login.py`, `tests/general/common/test_edw_standin.py`.
- Status: dev — steps 1–3 done (user confirmed design 10-29); waiting for PR.
