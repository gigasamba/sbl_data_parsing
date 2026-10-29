# mcp — search MCP server (image `mcp-server`)

Area of [PRD.md](../PRD.md). One anchor per feature: what it does, why, code files. Open items carry a `Status:` line with progress; done features carry `Status: done`.
Tool contract (names, inputs, outputs, `tools/list` order) is fixed — change only by agreement and a new version ([CLAUDE.md](../../CLAUDE.md) §4).

## mc-01
`search` tool — evidence search over loaded documents. Why: the single entry clients use to get cited evidence.
- What: three modes — question only (hybrid search), filters only (every chunk of matching docs, no scoring), question + filters (scope applied in the store query, pool `min(50, max(3k, 30))`, then filtered and renumbered — no re-rank step). Filters `client`, `client_like`, `source_system`, `project_id`, `division`, `service_type` work on the PG store only (local bundle: filters-only returns an error, question + filters searches unfiltered); `index_id` picks a named index; `limit` applies to filters-only mode.
- Retrieval: methods `vector`·`bm25`·`id` only (graph·concept·image·openviking removed 10-29 — other values are ignored with a note): vector (pgvector cosine, HNSW; binary quantize + top-200 re-score above HNSW dims) + BM25 (`chunk_term`·`term_stat`·`corpus_stat`) + rare-ID regex, fused by weighted RRF (weights by question type).
- Output: evidence items (`chunk_id`, `source_uri`, `page`, `bbox`, `section`, `text`, `score`, `via`, `rank`, …), `evidence_status` found/weak/none (labels only, drops nothing), `notes`.
- Files: `mcp_server/routers/`, `mcp_server/services/search/search_svc.py`, `retriever.py`, `pgsearch.py`, `local.py`, `shaping.py`, `mcp_server/schemas/evidence.py`.
- Status: done

## mc-02
Query understanding — expansion. Why: users ask with synonyms, abbreviations and several clients at once.
- What: glossary expansion for BM25 (synonym 1.0 / abbreviation 0.8 / weak 0.3, roster aliases, max 20), alias text on the vector query, per-client split for comparison questions (`SEARCH_ENTITY_SPLIT`, round-robin merge `search_svc._gather`), rule-based question type for weights. LLM decomposition was removed 10-29 (`decompose` input accepted and ignored, `subs` always `[]`).
- Files: `mcp_server/services/search/terms.py`, `qtype.py`, `search_svc.py`.
- Status: done

## mc-04
Aggregation answers. Why: count/sum questions need computed values, not chunks.
- What: rule-based count, amount, batch and table sums by client, contract, period, modality; never adds different currencies; appends FX text to the aggregate item; result goes first with `via="aggregate"`; optional LLM router for borderline questions.
- Files: `mcp_server/services/search/aggregate.py`, `resources/prompts/mcp/agg_llm_route/`.
- Status: done

## mc-05
Client scope, versions and duplicates. Why: answers must not mix clients or cite old versions.
- What: soft/hard client scope, hidden docs excluded, newer versions ranked above older ones for questions that ask for the latest (`SEARCH_RECENCY=1` default, `2` = always; older kept, marked `superseded`), copy groups merge renamed copies.
- Files: `mcp_server/services/search/clientscope.py`, `supersede.py`, `common/core/docmeta.py`.
- Status: done

## mc-06
`query_edw` tool — read-only EDW SQL. Why: structured questions answered from the company EDW.
- What: one SELECT/WITH only, table allowlist (mssql: off by default — `EDW_QUERY_TABLES_STRICT=0` allows every schema except system catalogs; the sqlite stand-in uses its bundled list), row/time/byte caps, separate low-privilege login; sqlite stand-in for PC tests.
- Files: `mcp_server/services/edw_query.py`, `mcp_server/services/edw_calls.py`.
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
- What: FastMCP streamable HTTP (`/mcp`, default 127.0.0.1:8765) or `--stdio`; non-loopback bind needs `MCP_TOKEN` (constant-time compare); 0.0.0.0 refused; DNS-rebinding guard; `/health` (503 while warming); concurrency 8 + queue + 30 s tool timeout; reload on new load version; jsonl query log incl. `query_edw` calls (90 days).
- Files: `mcp_server/main.py`, `mcp_server/routers/dispatch.py`, `mcp_server/config.py`.
- Status: done

## mc-10
Retriever reads removed column `file_sha256`. Why: the 10-20 reduced schema dropped `file_sha256`·`client`·`file_name`·`s3_key`, but the retriever still reads `doc.file_sha256` (`hidden_names`) and `doc.client`·`doc.file_name` (`_client_rows`), so building a retriever on a new bundle fails.
- Files: `mcp_server/services/search/retriever.py`.
- Status: done (10-30, `feature/search-path-fixes`) — 묶음 문서 키를 `doc_key` 우선(옛 묶음은 `file_sha256`)으로 읽고(`_doc_key`), PG `doc` 조회는 남은 열(`file_path`·`clients`)만 고름(`_client_rows`·`client_map`). 파일 이름은 `file_path`의 마지막 `/` 뒤(`_file_name` — `v_chunk_source` 뷰와 같은 규칙, 로컬 묶음 검색·`client_map`·`do_lookup_term`). 시험 `tests/server/mcp/test_mc10_doc_key.py`. `hidden_names`의 `file_sha256` 조회는 숨김 키 문제라 [mc-14](#mc-14)로. 범위 밖으로 남은 것: EDW 벡터 키(`sha:seq`)는 새 묶음 키와 안 맞음(PR #5가 EDW 벡터 경로를 지움) · `internal_docs.py`의 문서 조회·목록(PG `doc`에서 `file_name`·`file_sha256`·`source_uri` 등 없는 열을 고름)은 별도 항목으로 볼 것.

## mc-11
Aggregation path queries removed columns. Why: `aggregate.pg()` selects `file_sha256`, `client`, `contract_no`, `meta_confirmed`, `contract`, so every search result gets an "aggregation path error" note (evidence itself is fine).
- Files: `mcp_server/services/search/aggregate.py`.
- Status: todo

## mc-12
Fact aggregation queries a dropped table. Why: `kg_node`·`kg_edge`·`doc_fact`·`concept_chunk`·`doc_image`·`chunk_image` are no longer created or loaded (`pipeline/load/pgvector_load.py`). The graph and concept search methods that read them were removed 10-29; the `doc_fact`-based aggregation path in `aggregate.py` still queries `doc_fact`, so it returns nothing on PG.
- Files: `mcp_server/services/search/aggregate.py`, `pipeline/load/pgvector_load.py`.
- Status: todo — decide: load `doc_fact` again (Alembic migration, DB owner) or drop that aggregation path.

## mc-13
PG query log writes to a table no migration creates. Why: `search_svc` does `INSERT INTO qa_log` on the PG store, but `0001_search_base` has no `qa_log` table; the error is swallowed, so only the jsonl log works.
- Files: `mcp_server/services/search/search_svc.py`, `mcp_server/services/search/qa_log.py`, `common/store/db/migrations/versions/0001_search_base.py`.
- Status: done (10-30, `feature/search-path-fixes`) — 사용자 결정: 질의 기록은 파일(`qa_log.jsonl`)만. `search_svc._log`와 `ask.py`의 PG `qa_log` INSERT를 지움(표는 만들지 않음). jsonl 기록은 그대로. 시험 `tests/server/mcp/test_mc13_qa_log.py`.

## mc-14
숨김 문서가 검색에서 빠지지 않는다. 왜: 숨김 표(`doc_hidden`, struct 스키마)의 키는 문서 대장 `doc_key` = 원본 sha256인데(`registry.apply()`가 원천에서 사라진 문서를 자동 숨김, `registry_cli hide`도 같은 키), 10-20 축소 스키마 뒤 검색 쪽 문서 키는 `file_path`다 — `pgsearch._not_hidden_restrict`가 sha256을 `doc.file_path`와 비교해 절대 안 맞고, 로컬 묶음(`local.py`)·`retriever.hidden_names`는 PG에서 없는 열(`file_name`·`file_sha256`)을 골라 숨김 문서가 하나라도 있으면 오류가 난다(그림 조회 `internal_docs.py`).
- 조사(10-30): 스키마 변경 없이 잇는 길이 없다. 검색 `doc` 표에는 sha256도 원본 키(`s3_key`)도 없고(`file_path` = `edw_path_prefix` + 파일 이름 또는 PC 경로), 문서 대장의 `source_keys`(`local::<경로>`·`<출처>::<원본 키>`)는 모양이 달라 정확히 맞출 수 없다. 파일 이름으로 맞추면 다른 폴더·고객의 같은 이름 문서가 잘못 숨겨진다(engine-qa 10-08이 이름 짝짓기를 금지한 이유와 같음).
- 결정(사용자 10-30): 모든 문서 키를 `s3_key`로 바꾸고 문서 대장·숨김 표를 DB 명세로 다시 키를 잡는다(pl-25, 스키마 변경 — Alembic·DB 담당자). 그때 이 비교를 같은 키로 고친다.
- Files: `mcp_server/services/search/pgsearch.py`(`_not_hidden_restrict`), `mcp_server/services/search/local.py`, `mcp_server/services/search/retriever.py`(`hidden_names`), `common/store/registry.py`.
- Status: todo — pl-25 대기(코드 수정 없음).

## mc-15
검색 근거의 `rep_uri`(대표 파싱 결과 경로)가 늘 비어 있다. 왜: `shaping._rep_uri`가 근거의 `doc_key`(= `file_path`)로 `AI.ParsingMeta`를 찾는데(`parsing_meta_db.find_rep_path` → `find_by_doc_key`), ParsingMeta의 `doc_key`는 원본 sha256이다(`docs/operations/parsing_meta_mssql.sql` — 유일한 필수 열). 그래서 한 번도 맞지 않는다.
- 조사(10-30): ParsingMeta에서 원본을 가리키는 열은 `doc_key`(sha256)·`source_key`(Object Storage 원본 전체 키)·`source_uri`·`original_filename`이다. 검색 `doc` 표에는 sha256도 원본 키도 없어서(10-20 축소 스키마가 `s3_key`를 뺌, `build_bundle`의 `_meta`에도 안 남음) 정확히 맞출 열이 없다. `original_filename`으로 맞추면 같은 이름 문서가 섞인다(mc-14와 같은 이유로 하지 않음).
- 결정: mc-14와 같이 pl-25(문서 키 `s3_key` 통일 — 검색 `doc`에 원본 키가 들어옴)를 기다린다. 그 뒤 `source_key`로 조회하도록 고친다(ParsingMeta 쪽 스키마 변경은 필요 없음).
- Files: `mcp_server/services/search/shaping.py`, `common/store/parsing_meta_db.py`.
- Status: todo — pl-25 대기(코드 수정 없음).
