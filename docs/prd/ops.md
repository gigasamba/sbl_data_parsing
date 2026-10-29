# Operations — logging (op)

Source: COMPANY governance per-project review, 10-29 (interim standard).

## op-01
JSON Lines event log for both apps. Why: today `common/core/runlog.py` writes one summary per run (`output/runlog.jsonl`) and raw console logs (`output/logs/*.log`, masked by `_mask()`); the runner writes `doc_stats.jsonl`; the MCP server writes a query jsonl. There is no common per-event line (level, request id, duration), and no log level setting.
- Steps: (1) stdlib `logging` + one small JSON formatter in `common/core/` — keys `time, level, msg, request_id, duration_ms, err`; reuse `_mask()` (no new package). (2) Log level as a **settings.yaml** item (the review's `LOG_LEVEL` env conflicts with CLAUDE.md §3; keep the old env name as alias only). (3) PC writes `logs/<app>.jsonl` (gitignored); server writes stdout. (4) Mask secrets and personal data.
- Risk: edits `common/` → code_fp may change (server reprocessing) — tell the user at design, put before/after fingerprints in the commit. Review grade A (secret handling).
- Acceptance / QA: each line parses as JSON with the required keys; a sample secret string is masked; level setting filters lines.
- Files: `common/core/` (new formatter), `common/config/settings.py`, `mcp_server/main.py`, `pipeline/cli.py`, `.gitignore`.
- Status: todo

## op-02
RUN_ENV becomes three values: `local` (PC), `dev` (dev server), `prd` (production). `stage` is removed. Why: `stage` behaved exactly like `prd` (only written to the run log); hub asked for fewer modes (10-29); LLM_FAKE had no RUN_ENV check, so fake answers could run on a server.
- Decisions (user, grill-me 10-29):
  1. Keep `local` as the PC signal (repo-root settings.yaml lookup, file-based stack/sources, `paths.LOCAL_RUN`) — no new setting, no code-location rule. (Hub had proposed dev/prd only; user chose three values.)
  2. External models (OpenRouter etc.) and `LLM_FAKE` are allowed **only in `local`**. `dev` and `prd` refuse both.
  3. `LLM_FAKE` on in `dev`/`prd` → refuse at app start (`require_run_env` gate), not per call.
  4. Old `stage` in settings files or env → read as `prd` with a one-line warning (one release); then removed.
  5. RUN_ENV stays required everywhere (PC too) — no default.
- Derived (no question needed): commands without RUN_ENV (in-image `selftest`, check commands) are not app starts, so they keep working with LLM_FAKE in test cases; PC Docker smoke (`valid_env/docker/compose.test.yml`) keeps `RUN_ENV: local`; external-model rule `external_models_allowed` = `local` only (unchanged).
- Files: `common/config/settings.py` (RUN_ENVS, SERVER_ENVS, run_env Literal, stage mapping, start gate), `common/ai/llm.py`/`adk.py` untouched if the start gate covers it, `common/config/{migrate,keyscan,overrides,setarg}.py`, `deploy/host/compose/*.yml` text, `deploy/host/scripts/settings_env.sh`, `deploy/docker/entrypoint.sh`, docs (CLAUDE.md §3, README §3, env-guide, refactor.md), `settings.sample.yaml` regen, tests.
- Risk: `common/config/settings.py` is in every layer's code_fp → server reprocessing; record fingerprints before/after. Keep the settings.py diff small (92 and r2-phase edit it too).
- Acceptance / QA: `RUN_ENV=stage` loads as `prd` with warning; `RUN_ENV=dev`/`prd` + `LLM_FAKE=1` app start exits non-zero; `local` + `LLM_FAKE=1` starts; external models refused in dev/prd, allowed in local; in-image selftest still passes; full pytest + lint pass.
- Status: design done (user confirm pending)
