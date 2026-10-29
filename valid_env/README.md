# valid_env/ — PC stand-ins for external systems (PC only, not in any image)

Data that imitates what the server reads from outside systems lives here, in one place (NM16). Layout taken from PwC_Structure `valid_env` on 10-29 (PRD `e2-09`); the old `unstructured/<set>/` folders were deleted (restore from git history if needed).

| Folder | Stands in for | Content | Git |
|---|---|---|---|
| `object_storage/` | Object Storage bucket (original documents) | one document = `<system>/<uuid>/<file>`: `CRMS/` 21 hard cases, `SFDC/` 12 RFP documents. Why each document exists: [object_storage/test_doc_purpose.md](object_storage/test_doc_purpose.md) | tracked, bytes as-is |
| `eval_sets/` | answers and run lists | `object_keys.csv` (document list + sha256 — the source of truth), `doc_catalog.jsonl`, `hard_cases/` (gold, spec, qa, expected), `rfp/` (gold, spec, questions), `list-smoke10.txt`, `list-integration*.txt`, `integration-questions.jsonl` | tracked |
| `edw/` | company EDW (SQL Server) | `ai`·`crms`·`las`·`sfdc` `.sql` (schema + synthetic rows, `[SYNTHETIC]`) and the `.sqlite` built from them; `meta_rdb/` = RDB document-location and master tables (old `unstructured/synth-meta-rdb/meta`, read by three server tests) | tracked |
| `answer_test/rag_qa/` | serving Answer Agent (PC answer check) | agent package used by `python -m validation.e2e.answer_gen` | tracked |
| `docker/` | server containers | PC test compose (`compose.pg.yml`, `compose.test.yml`, `smoke_test.sh`) | tracked |

- Everything here is synthetic. Nothing is written here at run time — results go under `out_root`.
- List files hold repo-relative paths (`valid_env/object_storage/...`). `--src` takes a folder, so copy the listed files into one folder first (README §4-4).
- Not wired yet (PRD `e2-09`): the `EVAL_SETS_DIR` default in `common/core/paths.py` still points at `valid_env/unstructured` (changing it changes every layer code_fp — next fingerprint release; on the PC set `common.paths.eval_sets_dir: valid_env/eval_sets`), and the PC evaluation tools that name old sets (`synth-4clients` …) are handled in PRD `e2-10`.

## Production DB guard

| Path | Content |
| --- | --- |
| `structured/sales.sqlite` | production master DB of the archived price·legal·deal·RFI pipeline — **never open or write it** (CLAUDE.md §4 production guard, `common/store/structdb.py` `PROD_DBS`). Review only on a copy after human approval. Not in git. |
| `structured/input/` | its source CSVs and schema |
