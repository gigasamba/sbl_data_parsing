# sbl_data_parsing — PRD

Goal: cited evidence search over company docs on the closed network — parse → structure → load (pgvector) → search MCP — same on server and PC.
Row = one open feature. ID prefix = `prd/<area>.md` (mc = search MCP · pl = data pipeline · e2 = e2e, tests, eval · rn = flow runner · do = docs layout · op = logs, DB accounts). Status: todo | dev | done.

| ID | Bundle | Status | Detail |
|---|---|---|---|
| mc-14 | 숨김 문서가 검색에서 안 빠짐(숨김 키 sha256 ↔ 검색 키 file_path) — pl-25 대기 | todo | [→](prd/mcp.md#mc-14) |
| mc-15 | 근거의 `rep_uri`(파싱 결과 경로)가 늘 비어 있음(ParsingMeta 키 sha256 ↔ 검색 키 file_path) — pl-25 대기 | todo | [→](prd/mcp.md#mc-15) |
| pl-12 | Registry upsert PG error · publish guard off (C-54) | todo | [→](prd/pipeline.md#pl-12) |
| pl-13 | `load --prune` deletes skipped docs (C-60) | todo | [→](prd/pipeline.md#pl-13) |
| pl-15 | structure/load contract rejects new bundles | todo | [→](prd/pipeline.md#pl-15) |
| pl-16 | `PIPE_EMBED=none` builds `vector(0)` | todo | [→](prd/pipeline.md#pl-16) |
| pl-17 | Parse step location extract/transform (C-61) | todo | [→](prd/pipeline.md#pl-17) |
| pl-18 | `night`/`full` exit 0 after midway stop (C-33) | todo | [→](prd/pipeline.md#pl-18) |
| pl-19 | compose `index_a`/`index_b` fail (C-32) | todo | [→](prd/pipeline.md#pl-19) |
| pl-20 | Stack snapshot file review (C-50) | todo | [→](prd/pipeline.md#pl-20) |
| pl-21 | Deferred settings removal (fingerprint) | todo | [→](prd/pipeline.md#pl-21) |
| pl-22 | Remove parse phases · engines per doc in parallel · OCR engine off | dev | [→](prd/pipeline.md#pl-22) |
| pl-23 | Incremental only; full reparse = full e2e (C-52) | todo | [→](prd/pipeline.md#pl-23) |
| pl-24 | run_docs order: silver → delete original → gold | todo | [→](prd/pipeline.md#pl-24) |
| pl-25 | DB schema spec doc + column check test (first) | todo | [→](prd/pipeline.md#pl-25) |
| pl-26 | `full` always publishes, targets required (C-31) | todo | [→](prd/pipeline.md#pl-26) |
| pl-27 | 프로세스 종료 정리 — 임시 설정 파일·PID 기록 지움, 자식 회수 | dev | [→](prd/pipeline.md#pl-27) |
| pl-28 | Per-source gold tables · source required in search (later) | todo | [→](prd/pipeline.md#pl-28) |
| pl-29 | EDW 고객 매핑을 파이프라인이 직접 만든다 | todo | [→](prd/pipeline.md#pl-29) |
| pl-30 | 아무도 안 읽는 env 이름 4개 삭제(C-51) | todo | [→](prd/pipeline.md#pl-30) |
| e2-10 | Minimize PC eval tools (old set names) and settings | todo | [→](prd/e2e.md#e2-10) |
| e2-11 | PC general test known failures | todo | [→](prd/e2e.md#e2-11) |
| e2-13 | PC Docker smoke stops at retriever | todo | [→](prd/e2e.md#e2-13) |
| e2-14 | Release tests only inside the image (C-53) | todo | [→](prd/e2e.md#e2-14) |
| e2-15 | Agent test package path points upstream | todo | [→](prd/e2e.md#e2-15) |
| e2-16 | Search page fixed document count text | todo | [→](prd/e2e.md#e2-16) |
| e2-17 | Remaining unused functions (10-29 audit) | todo | [→](prd/e2e.md#e2-17) |
| e2-18 | Delete code with no requirement (gaps §2) | todo | [→](prd/e2e.md#e2-18) |
| do-01 | Move `refactor.md` to `docs/refactoring/` | todo | [→](prd/doc.md#do-01) |
| do-02 | Glossary in `docs/index.md` | todo | [→](prd/doc.md#do-02) |
| do-03 | Sync `refactor.md` with 10-29 merges | todo | [→](prd/doc.md#do-03) |
| do-04 | Docs restructure · `docs/history/` · Korean | todo | [→](prd/doc.md#do-04) |
| op-01 | JSON Lines event log | todo | [→](prd/ops.md#op-01) |
| op-02 | RUN_ENV `local`·`dev`·`prd` (drop `stage`) · LLM_FAKE only in `local` | design done | [→](prd/ops.md#op-02) |
| op-03 | One EDW connection, read/write account | dev | [→](prd/ops.md#op-03) |
| op-04 | First release tag `v0.1.0` + release notes | todo | [→](prd/ops.md#op-04) |

Done: mcp 10 → [prd/mcp.md](prd/mcp.md) · pipeline 11 → [prd/pipeline.md](prd/pipeline.md) · e2e 10 → [prd/e2e.md](prd/e2e.md) · runner 2 → [prd/runner.md](prd/runner.md)
Code vs requirements — mismatches, code with no requirement, off-by-default features, removed 10-29: [prd/gaps.md](prd/gaps.md)
