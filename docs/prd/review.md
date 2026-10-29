# review — code with no requirement anchor (keep → add an anchor · or delete the code)

Linked from [PRD.md](../PRD.md). Found by the 10-29 code check of `docs/prd/*.md`. For each line the user decides: **keep** (write an anchor in the area file) or **delete** (remove the code). Not yet decided = listed here. Features already chosen for deletion on 10-29 (OpenViking, re-ranking, question decomposition, extra search methods, parse judgment agent) are not listed.

## mcp
- EDW vector search — `usp_vec_topk` stored procedure, `EdwClient`; only reachable through `ask --edw` / `--edw-client`, the server builds its retriever with EDW off. Files: `mcp_server/services/search/edw_search.py`, `mcp_server/cli/ask.py`, `common/store/edwdb.py`.
- Evidence parse-result paths — looks up the published result location in `AI.ParsingMeta` and adds it to evidence (`MCP_EVIDENCE_PATHS`, default on). Files: `mcp_server/services/search/shaping.py`.
- Evidence image crops — crops a page region from the original for an evidence item (`MCP_EVID_*`); internal function, no MCP tool exposes it. Files: `mcp_server/services/search/internal_docs.py` (`do_evidence_image`, `do_get_image`).
- Tie-break by question entities (`SEARCH_TIE_BREAK`, default on). Files: `mcp_server/services/search/search_svc.py`.
- PG stand-in — SQLite in place of pgvector when no PG connection is set (PC). Files: `common/store/pg_standin.py`.
- Document registry CLI — inspect/hide documents in the registry. Files: `mcp_server/cli/registry_cli.py`.

## pipeline
- Email attachments — recursive parse of `.eml`/`.msg` attachments (depth 1, 20 MB, 10 files) and quoted-thread folding (`ATTACH_*`). Files: `pipeline/transform/represent/attachments.py`.
- Streaming parse — fetch a small batch, parse, delete the originals (`PARSE_STREAM`, default off). Files: `pipeline/stream.py`.
- Shadow mode — compares rule decisions with model proposals without applying them (`PARSE_SHADOW`, default off). Files: `pipeline/transform/represent/shadow.py`, `pipeline/eval/parse_shadow.py`.
- Glossary and wiki tools — concept wiki, LLM glossary draft, abbreviation suggestions, client/product roster from EDW masters. Files: `pipeline/transform/structure/wiki.py`, `wiki_draft.py`, `glossary_suggest.py`, `gen_roster.py`.
- Nightly host timer and trigger chaining (parse → structure, `NIGHTLY_*`, `CHAIN_STRUCTURE_URL`). Files: `deploy/host/`, `pipeline/trigger_server.py`.
- Test upload to Object Storage (MinIO). Files: `common/check/os_put.py`.

## shared tools (config, DB, checks)
- Config CLIs — `show`, `export` (shell/compose bridge), `migrate` (old env files → settings.yaml), `keyscan`, `overrides`, `--set`. Files: `common/config/`.
- DB tools — Alembic version management and model ↔ DB compare. Files: `common/store/db/dbtool.py`, `dbcompare.py`.
- Checks — server environment check, model ping, module boundaries. Files: `pipeline/check_env.py`, `common/check/ping_models.py`, `common/check/check_modules.py`.

## e2e (PC evaluation tools — see [e2e.md#e2-10](e2e.md#e2-10))
- External knowledge-graph adapters (LightRAG, Cognee, Graphiti; Neo4j). Files: `pipeline/eval/kg_external.py`, `validation/e2e/graph_llm.py`, `pipeline.connections.graphiti.*`.
- Gold and question drafts (VLM draft + human review). Files: `pipeline/eval/gold_draft.py`, `qa_draft.py`, `make_questions.py`.
- Scorers for synthetic sets that were deleted with `valid_env/unstructured` (`synth-diagrams-hard`, `synth-charts-hard`). Files: `pipeline/eval/diagram_edges_score.py`, `chart_values_score.py`.
- Question explorer HTML, server measurement pack, combo report. Files: `pipeline/eval/explorer.py`, `server_checks.py`, `report.py`.
