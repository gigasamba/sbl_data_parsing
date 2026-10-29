# sbl_data_parsing — PRD

Goal: cited evidence search over company documents on the closed network — parse → structure → load (pgvector) → search MCP — same results on the server as on the PC.
Row = one open feature. ID prefix = area = `prd/<area>.md` (mc = search MCP · pl = data pipeline · e2 = e2e runs, tests, evaluation · rn = server flow runner · do = docs layout · op = logging). Status: todo | dev | done.

| ID | Bundle | Status | Detail |
|---|---|---|---|
| mc-10 | Retriever reads removed `file_sha256` | todo | [→](prd/mcp.md#mc-10) |
| mc-11 | Aggregation path queries removed `file_sha256` | todo | [→](prd/mcp.md#mc-11) |
| mc-12 | Fact aggregation queries dropped `doc_fact` | todo | [→](prd/mcp.md#mc-12) |
| mc-13 | PG `qa_log` table never created | todo | [→](prd/mcp.md#mc-13) |
| pl-12 | Registry upsert PG error · publish guard off (C-54) | todo | [→](prd/pipeline.md#pl-12) |
| pl-13 | `load --prune` deletes skipped docs (C-60) | todo | [→](prd/pipeline.md#pl-13) |
| pl-14 | Deploy backfill reads removed `doc.client` | todo | [→](prd/pipeline.md#pl-14) |
| pl-15 | structure/load contract rejects new bundles | todo | [→](prd/pipeline.md#pl-15) |
| pl-16 | `PIPE_EMBED=none` builds `vector(0)` | todo | [→](prd/pipeline.md#pl-16) |
| pl-17 | Parse step location extract/transform (C-61) | todo | [→](prd/pipeline.md#pl-17) |
| pl-18 | `night`/`full` exit 0 after midway stop (C-33) | todo | [→](prd/pipeline.md#pl-18) |
| pl-19 | compose `index_a`/`index_b` fail (C-32) | todo | [→](prd/pipeline.md#pl-19) |
| pl-20 | Stack snapshot file review (C-50) | todo | [→](prd/pipeline.md#pl-20) |
| pl-21 | Deferred settings removal (fingerprint) | todo | [→](prd/pipeline.md#pl-21) |
| pl-22 | `full` always publishes, targets required (C-31) | todo | [→](prd/pipeline.md#pl-22) |
| pl-23 | Incremental only; full reparse = full e2e (C-52) | todo | [→](prd/pipeline.md#pl-23) |
| pl-24 | run_docs order: silver → delete original → gold | todo | [→](prd/pipeline.md#pl-24) |
| pl-25 | DB schema spec doc + column check test (first) | todo | [→](prd/pipeline.md#pl-25) |
| e2-10 | Minimize PC eval tools (old set names) and settings | todo | [→](prd/e2e.md#e2-10) |
| e2-11 | PC general test known failures | todo | [→](prd/e2e.md#e2-11) |
| e2-12 | EDW answer citation check (C-56) | todo | [→](prd/e2e.md#e2-12) |
| e2-13 | PC Docker smoke stops at retriever | todo | [→](prd/e2e.md#e2-13) |
| e2-14 | Release tests only inside the image (C-53) | todo | [→](prd/e2e.md#e2-14) |
| e2-15 | Agent test package path points upstream | todo | [→](prd/e2e.md#e2-15) |
| e2-16 | Search page fixed document count text | todo | [→](prd/e2e.md#e2-16) |
| e2-17 | Remaining unused functions (10-29 audit) | todo | [→](prd/e2e.md#e2-17) |
| rn-01 | Lanes: owner first, per-lane steal list | todo | [→](prd/runner.md#rn-01) |
| rn-02 | Mid-queue cap + queue depth log | todo | [→](prd/runner.md#rn-02) |
| do-01 | Move `refactor.md` to `docs/refactoring/` | todo | [→](prd/doc.md#do-01) |
| do-02 | Glossary in `docs/index.md` | todo | [→](prd/doc.md#do-02) |
| do-03 | Sync `refactor.md` with 10-29 merges | todo | [→](prd/doc.md#do-03) |
| op-01 | JSON Lines event log | todo | [→](prd/ops.md#op-01) |

Done: mcp 8 → [prd/mcp.md](prd/mcp.md) · pipeline 11 → [prd/pipeline.md](prd/pipeline.md) · e2e 9 → [prd/e2e.md](prd/e2e.md)
Code vs requirements — mismatches, code with no requirement, off-by-default features, removed 10-29: [prd/gaps.md](prd/gaps.md)
