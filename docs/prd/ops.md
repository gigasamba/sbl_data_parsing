# Operations — logging (op)

Source: COMPANY governance per-project review, 10-29 (interim standard).

## op-01
JSON Lines event log for both apps. Why: today `common/core/runlog.py` writes one summary per run (`output/runlog.jsonl`) and raw console logs (`output/logs/*.log`, masked by `_mask()`); the runner writes `doc_stats.jsonl`; the MCP server writes a query jsonl. There is no common per-event line (level, request id, duration), and no log level setting.
- Steps: (1) stdlib `logging` + one small JSON formatter in `common/core/` — keys `time, level, msg, request_id, duration_ms, err`; reuse `_mask()` (no new package). (2) Log level as a **settings.yaml** item (the review's `LOG_LEVEL` env conflicts with CLAUDE.md §3; keep the old env name as alias only). (3) PC writes `logs/<app>.jsonl` (gitignored); server writes stdout. (4) Mask secrets and personal data.
- Risk: edits `common/` → code_fp may change (server reprocessing) — tell the user at design, put before/after fingerprints in the commit. Review grade A (secret handling).
- Acceptance / QA: each line parses as JSON with the required keys; a sample secret string is masked; level setting filters lines.
- Files: `common/core/` (new formatter), `common/config/settings.py`, `mcp_server/main.py`, `pipeline/cli.py`, `.gitignore`.
- Status: todo
