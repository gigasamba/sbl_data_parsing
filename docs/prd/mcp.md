# mcp — search MCP server (image `mcp-server`)

Area of [PRD.md](../PRD.md). One anchor per feature: what it does, why, code files. Open items carry a `Status:` line with progress; done features carry `Status: done`.
Tool contract (names, inputs, outputs, `tools/list` order) is fixed — change only by agreement and a new version ([CLAUDE.md](../../CLAUDE.md) §4).

## mc-01
`search` tool — evidence search over loaded documents. Why: the single entry clients use to get cited evidence.
- What: three modes — question only (hybrid search), filters only (every chunk of matching docs, no scoring), question + filters (search inside the filtered docs, pool k×3 then re-rank). Filters: `client`, `client_like`, `index_id`, `source_system`, `project_id`, `division`, `service_type`, `limit`.
- Retrieval: vector (pgvector cosine, HNSW; binary quantize + top-200 re-score above HNSW dims) + BM25 (`chunk_term`·`term_stat`·`corpus_stat`) + rare-ID regex, fused by weighted RRF (weights by question type).
- Output: evidence items (`chunk_id`, `source_uri`, `page`, `bbox`, `section`, `text`, `score`, `via`, `rank`, …), `evidence_status` found/weak/none (labels only, drops nothing), `notes`.
- Files: `mcp_server/routers/`, `mcp_server/services/search/search_svc.py`, `retriever.py`, `pgsearch.py`, `local.py`, `shaping.py`, `mcp_server/schemas/evidence.py`.
- Status: done

## mc-02
Query understanding — expansion and decomposition. Why: users ask with synonyms, abbreviations and compound questions.
- What: glossary expansion for BM25 (synonym 1.0 / abbreviation 0.8 / weak 0.3, roster aliases, max 20), alias text on the vector query, LLM decomposition into ≤ 5 sub-questions (only when a cheap regex fires), per-client split for comparison questions, rule-based question type for weights.
- Files: `mcp_server/services/search/terms.py`, `decompose.py`, `qtype.py`, `resources/prompts/mcp/query_decompose/`.
- Status: done

## mc-03
Re-ranking (optional, default off). Why: better top-k when fused scores are close.
- What: local cross-encoder `BAAI/bge-reranker-v2-m3` or `api:<model>`; conditional mode re-ranks only on a small top-2 gap, results spread across docs, or comparison/latest questions; timeout falls back to fused order.
- Files: `mcp_server/services/search/rerank.py`.
- Status: done

## mc-04
Aggregation answers. Why: count/sum questions need computed values, not chunks.
- What: rule-based count, amount, batch and table sums by client, contract, period, modality; never adds different currencies; adds an FX evidence item; result goes first with `via="aggregate"`; optional LLM router for borderline questions.
- Files: `mcp_server/services/search/aggregate.py`, `resources/prompts/mcp/agg_llm_route/`.
- Status: done

## mc-05
Client scope, versions and duplicates. Why: answers must not mix clients or cite old versions.
- What: soft/hard client scope, hidden docs excluded, newer versions ranked above older ones (kept, marked `superseded`), copy groups merge renamed copies.
- Files: `mcp_server/services/search/clientscope.py`, `supersede.py`, `common/core/docmeta.py`.
- Status: done

## mc-06
`query_edw` tool — read-only EDW SQL. Why: structured questions answered from the company EDW.
- What: one SELECT/WITH only, table allowlist, row/time/byte caps, separate low-privilege login; sqlite stand-in for PC tests.
- Files: `mcp_server/services/edw_query.py`, `mcp_server/services/edw_calls.py`, `common/store/edwdb.py`.
- Status: done

## mc-07
`edw_meta` tool — EDW catalog lookup. Why: clients need table/column names before writing SQL.
- What: three-level lookup (schema → table → columns) over a static PII-cleaned dataset (`catalog.json` + `columns.jsonl`); difflib suggestions for unknown names; no LLM, no vectors.
- Files: `mcp_server/services/edw_meta.py`.
- Status: done

## mc-08
`parse_document` tool — parse one file on demand. Why: clients ask about a file that is not loaded yet.
- What: forwards a path (under the inbox root) or base64 content to the parse service on 127.0.0.1:8766 with a Bearer token; returns text, standard tables, facts, engine, timing; timeout returns `job_id`.
- Files: `mcp_server/services/parse_proxy.py`, `pipeline/mcp_parse_service.py`.
- Status: done

## mc-09
Server runtime and safety. Why: shared internal service — must stay up and refuse unsafe exposure.
- What: FastMCP streamable HTTP (`/mcp`, default 127.0.0.1:8765) or `--stdio`; non-loopback bind needs `MCP_TOKEN` (constant-time compare); 0.0.0.0 refused; DNS-rebinding guard; `/health` (503 while warming); concurrency 8 + queue + 30 s tool timeout; reload on new load version; query log (90 days).
- Files: `mcp_server/main.py`, `mcp_server/routers/dispatch.py`, `mcp_server/config.py`.
- Status: done

## mc-10
Retriever reads removed column `file_sha256`. Why: the 10-20 reduced schema dropped `file_sha256`·`client`·`file_name`·`s3_key`, but the retriever still reads `file_sha256`, so building a retriever on a new bundle fails.
- Files: `mcp_server/services/search/retriever.py`.
- Status: todo — PC avoids it through the local branch (`paths.LOCAL_RUN`); server uses the PG path only; the PC Docker smoke stops here ([e2e.md#e2-13](e2e.md#e2-13)).

## mc-11
Aggregation path queries removed column `file_sha256`. Why: every search result gets an "aggregation path error" note (evidence itself is fine).
- Files: `mcp_server/services/search/aggregate.py`.
- Status: todo

## mc-12
`graph` / `concept` search methods and fact aggregation query dropped tables. Why: `kg_node`·`kg_edge`·`doc_fact`·`concept_chunk`·`doc_image`·`chunk_image` are no longer created or loaded (`pipeline/load/pgvector_load.py`), but `pgsearch.graph_neighbors` and `concept_broader_chunks` still query them, so these methods return nothing or fail on PG.
- Files: `mcp_server/services/search/pgsearch.py`, `mcp_server/services/search/aggregate.py`.
- Status: todo — decide: restore the tables (Alembic migration, DB owner) or remove the methods and their settings (`mcp.search.graph.*`).
