# DB 스키마 명세 (pl-25)

이 프로젝트가 쓰는 DB 표와 칸을 한곳에 모은 문서다. 표마다 칸, 타입, 뜻, 그 칸을 쓰는 코드, 읽는 코드, 그리고 10-29·10-30 사용자 결정에 따른 앞으로의 처리(유지·삭제·새로)를 적는다. 요건과 결정의 원문은 [prd/pipeline.md#pl-25](../prd/pipeline.md#pl-25)에 있다.

- **이 문서는 설계안이다.** 사용자와 DB 담당자가 승인한 뒤 구현한다. 이 문서를 고치는 브랜치는 코드·스키마·마이그레이션을 바꾸지 않는다.
- **결정 칸:** `유지` = 지금 있고 남김 · `삭제` = 지금 있고 없앰 · `새로` = 지금 없고 만듦. 지금 상태 = `유지`+`삭제`, 목표 상태 = `유지`+`새로`.
- **시험:** `tests/server/common/test_db_schema.py`가 이 문서의 gold·struct 표를 Alembic 판(모델 `common/store/db/models/` — 기존 시험이 판과 같은지 본다)과, ParsingMeta를 [`docs/operations/parsing_meta_mssql.sql`](../operations/parsing_meta_mssql.sql)과 비교한다. 지금 상태가 다르면 실패하고, 목표 상태와의 차이(새로·삭제)는 목록으로 찍기만 한다.
- **쓰는 곳·읽는 곳**은 10-30 develop 기준 코드다. 경로는 저장소 기준이고 함수 이름만 적는다.

## 1. 공통 규칙 (10-30 결정)

| 규칙 | 내용 |
|---|---|
| 문서 키 | `s3_key`(Object Storage 원본 전체 키)만 문서 키로 쓴다. sha256 `doc_key`는 없앤다. 문서 대장(`doc_registry`·`doc_registry_seen`)과 숨김(`doc_hidden`)은 `s3_key`로 다시 키를 잡는다. 검색 `doc`·`chunk`도 `s3_key`를 든다. 같은 내용이 여러 `s3_key`로 들어오면 문서도 여러 개다 — `s3_key`마다 `doc` 행 하나(U-7 결정, `doc_alias` 없음). `build_bundle`의 내용 해시로 첫 키에 합치기(`aliases`)는 없앤다. 임베딩은 캐시가 다시 씀. |
| 출처 표시 이름 | EDW에서도, 문서 파싱에서도 나올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — EDW `_edw`, 문서 본문 `_doc`. 지금 해당하는 값: 고객(`client_edw`·`clients_doc`). |
| 고객 거르기 | MCP의 고객 거르기는 EDW 고객(`client_edw`, 문서당 하나)만 쓴다. EDW 고객이 없는 문서는 고객 거르기를 걸면 빠진다. 본문에서 찾은 고객(`clients_doc`)으로 거르는 것은 나중([pl-28](../prd/pipeline.md#pl-28)). |
| 원천 | `source_system` = `AI.FileStorageMap.source_system`. 비었거나 SFDC·CRMS·LAS가 아니면 `Other`. `s3_key` 접두와 다르면 경고만 남김. |
| 표 나누기 시점 | B — 지금은 gold 표 한 벌. 원천별(SFDC·CRMS·LAS·Other) 표 나누기와 MCP `search`의 원천 필수 입력은 [pl-28](../prd/pipeline.md#pl-28)(MCP 계약 변경 — 검토 등급 A). |

## 2. gold — 검색 스키마 (pgvector, `PG_SCHEMA`)

판: `common/store/db/migrations/versions/0001_search_base.py` · 모델: `common/store/db/models/search_tables.py` · 적재: `pipeline/load/pgvector_load.py`(`load`, `deploy`) · 값 만드는 곳: `pipeline/transform/structure/build_bundle.py`(`main`). `load_run`과 Alembic 판 표는 나눈 뒤에도 gold에 하나로 둔다.

### gold.load_run

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| run_id | SERIAL PK | 적재 한 번 | pgvector_load `load` | server_state(최근 적재 판) | 유지 |
| started_at | TIMESTAMPTZ | 시작 시각(기본 now) | DB 기본값 | 없음 | 유지 |
| finished_at | TIMESTAMPTZ | 끝 시각 | pgvector_load `load` | 없음 | 유지 |
| params | JSONB | 묶음 meta.json | pgvector_load `load` | 없음 | 유지 |
| counts | JSONB | 적재 건수 | pgvector_load `load` | 없음 | 유지 |

### gold.doc

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_id | SERIAL PK | 문서 행 번호(내부) | pgvector_load `load` | pgsearch, 뷰 `v_chunk_source` | 유지 |
| file_path | TEXT | 개발 서버 기준 원본 경로(파일 이름은 여기서 뽑음) | build_bundle `main` | pgsearch, retriever, search_svc, 뷰 | 유지 |
| s3_key | TEXT | 문서 키 — Object Storage 원본 전체 키(`AI.FileStorageMap.s3_key`) | (build_bundle가 이미 `_s3_key`로 알지만 묶음에 안 넣음) | (대장·숨김·ParsingMeta 조회) | 새로 |
| clients | TEXT(JSON) | 고객 목록 — 지금은 본문에서 찾은 이름(`infer_clients`)과 섞여 있음 | build_bundle `infer_clients` | pgsearch `_client_restrict`, retriever, internal_docs, search_svc | 삭제 |
| client_edw | TEXT | EDW 조인으로 얻은 고객 하나 — MCP 고객 거르기의 유일한 키 | (파이프라인이 EDW 읽기 계정으로 직접 조인 — [pl-29](../prd/pipeline.md#pl-29)) | (pgsearch 고객 거르기) | 새로 |
| clients_doc | TEXT(JSON) | 문서 본문에서 찾은 고객 목록(참고용 — 거르기에 안 씀) | (build_bundle `infer_clients`) | (근거 표시) | 새로 |
| summary | TEXT | 요약(검색 결과용) | build_bundle | 뷰 → retriever → shaping | 유지 |
| source_system | VARCHAR(20) | SFDC·CRMS·LAS·Other | build_bundle(`s3_key` 접두, 없으면 file_meta) | 뷰 → search_svc, internal_docs | 유지 |
| sf_acc_name | TEXT | SFDC 고객사 이름(SFDC 문서만 — 다른 원천은 빔, pl-28에 SFDC 표로) | build_bundle(file_meta JSONL) | 뷰 → search_svc, internal_docs | 유지 |
| sf_op_id | TEXT | SFDC 영업 기회 id(SFDC만) | build_bundle(file_meta) | 뷰 → internal_docs(그대로 내보냄) | 유지 |
| sf_op_name | TEXT | SFDC 영업 기회 이름(SFDC만) | build_bundle(file_meta) | 뷰 → internal_docs | 유지 |
| project_code__c | TEXT | SFDC 프로젝트 코드(SFDC만) | build_bundle(file_meta) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| contract_id | TEXT | 계약 id | build_bundle(file_meta) | 뷰 → internal_docs | 유지 |
| contract_date | DATE | 계약일 | build_bundle(file_meta) | 뷰 → internal_docs | 유지 |
| prod_name | TEXT | 제품 이름 | build_bundle(file_meta) | 뷰 → internal_docs | 유지 |
| division | VARCHAR(20) | 사업부(DS/DP/CD/CM/AD/AS) | build_bundle(file_meta) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| service_type | VARCHAR(20) | 서비스 종류(CMO DS 등) | build_bundle(file_meta) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| run_id | INT | 이 행을 넣은 적재(`load_run`) | pgvector_load `load` | 없음 | 유지 |

### gold.chunk

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| chunk_id | SERIAL PK | 청크 행 번호 | pgvector_load `load` | pgsearch, 뷰, server_checks | 유지 |
| doc_id | INT FK→doc | 문서 | pgvector_load `load` | 조인 전부 | 유지 |
| s3_key | TEXT | 문서 키(문서와 같은 값 — 청크만으로 대장·숨김 조회) | (pgvector_load) | (pgsearch 숨김 거르기) | 새로 |
| seq | INT | 문서 안 순번(`chunk_key` = 문서 키:seq) | pgvector_load | 뷰 → retriever, internal_docs | 유지 |
| page | INT | 쪽 | pgvector_load | 뷰 → retriever, internal_docs | 유지 |
| line_start | INT | 시작 줄 | pgvector_load | 뷰 → retriever | 유지 |
| line_end | INT | 끝 줄 | pgvector_load | 뷰 → retriever | 유지 |
| char_start | INT | 시작 글자 위치 | pgvector_load | 없음 | 유지 |
| char_end | INT | 끝 글자 위치 | pgvector_load | 없음 | 유지 |
| bbox | VARCHAR(80) | 쪽 안 위치 x0,y0,x1,y1(pt) | pgvector_load | 뷰 → retriever | 유지 |
| section | TEXT | 절 제목 | pgvector_load | 뷰 → retriever | 유지 |
| chunk_text | TEXT | 정제 본문 | pgvector_load | 뷰 → retriever, internal_docs | 유지 |
| n_chars | INT | 글자 수 | pgvector_load | 검증 페이지(serve.py)만 | 유지 |
| n_terms | INT | 토큰 수(BM25 길이) | pgvector_load | pgsearch `search` | 유지 |
| embed_model | VARCHAR(100) | 임베딩 모델 이름 | pgvector_load | 검증 페이지만 | 유지 |
| embedding | vector(차원) | L2 정규화 벡터 | pgvector_load | pgsearch `vector_top`, dbtool | 유지 |
| clients | TEXT[] | 고객 라벨(GIN — 지금 고객 거르기 키, `doc.clients`에서 복사) | pgvector_load `_chunk_clients`, `backfill_chunk_clients` | pgsearch `_client_restrict` | 삭제 |
| client_edw | TEXT | 고객 거르기 키(문서의 `client_edw` 복사 — 색인) | (pgvector_load) | (pgsearch 고객 거르기) | 새로 |
| source_system | VARCHAR(20) | 원천(거르기용 — 문서와 같은 값) | pgvector_load | 뷰 → search_svc, internal_docs | 유지 |

### gold.chunk_term

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT | 토큰 | pgvector_load(COPY) | pgsearch BM25·ID | 유지 |
| chunk_id | INT | 청크 | pgvector_load | pgsearch | 유지 |
| tf | SMALLINT | 청크 안 빈도 | pgvector_load | pgsearch BM25 | 유지 |

### gold.term_stat

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT PK | 토큰 | pgvector_load | pgsearch | 유지 |
| df | INT | 문서 빈도 | pgvector_load | pgsearch BM25 | 유지 |

### gold.corpus_stat

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | SMALLINT PK | 한 줄(1) | pgvector_load | pgsearch | 유지 |
| n_chunks | INT | 청크 수 | pgvector_load | pgsearch BM25 | 유지 |
| avg_len | DOUBLE PRECISION | 평균 길이 | pgvector_load | pgsearch BM25 | 유지 |
| dim | INT | 임베딩 차원 | pgvector_load | 없음(차원은 `pg_attribute`에서 읽음) | 유지 |

뷰 `v_chunk_source`는 `chunk`↔`doc`을 이은 읽기 전용 뷰다(파일 이름은 `file_path`에서 계산). 지금 `d.clients`를 고르므로 `doc.clients`를 지우는 판은 뷰를 먼저 `DROP VIEW` 하고 다시 만들어야 한다(`CREATE OR REPLACE VIEW`로는 칸을 뺄 수 없음) — 모델의 `VIEWS_EXPECTED`도 같이 고친다. 새 칸(`s3_key`·`client_edw`·`clients_doc`)도 그때 넣는다.

## 3. struct — 정형 저장소 (PostgreSQL `struct`, PC는 SQLite 대체)

판: `0001_struct_base.py`·`0002_struct_config.py` · 모델: `common/store/db/models/struct_tables.py` · SQLite 대체: `common/store/structdb.py`. 문서에서 뽑은 내용을 담던 표(`doc_location`·`doc_contract_link`·`doc_table`·`doc_cell`)는 지운다 — 그 내용은 청크 본문에만 둔다. 지우면 함께 가는 코드: `pipeline/load/structured.py`(`link`·`tables` 명령, `load_tables_docs`), `pipeline/cli.py` `load_tables_db`, `common/store/structdb.py` `find_table_cells`, `mcp_server/services/search/structdb.py` `find_table_row`, `aggregate.py`(`struct`, `struct_context`, `doc_link_list`, `doc_location_list`, `table_cell_list`, `_table_cell_scope_docs`)와 호출부(`internal_docs.py`, `cli/ask.py`). 마스터(`contract_master`·`client_master`)는 별도 PostgreSQL로 옮긴다(§5).

### struct.contract_master

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| contract_id | TEXT PK | 계약 id | structured `load_csv`(CSV — 사람) | structured `link_docs`, aggregate | 삭제 |
| company | TEXT | 고객사 이름 | 〃 | 〃 | 삭제 |
| company_id | TEXT | 고객사 id | 〃 | 〃 | 삭제 |
| product_code | TEXT | 제품 코드 | 〃 | 〃 | 삭제 |
| modality | TEXT | 모달리티 | 〃 | 〃 | 삭제 |
| site | TEXT | 생산지 | 〃 | 〃 | 삭제 |
| line_id | TEXT | 라인 | 〃 | 〃 | 삭제 |
| batches_contracted | INTEGER | 계약 배치 수 | 〃 | 〃 | 삭제 |
| contract_value_usd | INTEGER | 계약 금액(USD) | 〃 | 〃 | 삭제 |
| currency | TEXT | 통화 | 〃 | 〃 | 삭제 |
| term_months | INTEGER | 기간(개월) | 〃 | 〃 | 삭제 |
| signed_on | TEXT | 서명일 | 〃 | 〃 | 삭제 |
| start_date | TEXT | 시작일 | 〃 | 〃 | 삭제 |
| end_date | TEXT | 종료일 | 〃 | 〃 | 삭제 |
| status | TEXT | 상태 | 〃 | 〃 | 삭제 |

(struct에서는 지우고 같은 칸으로 `master.contract_master`에 새로 만든다.)

### struct.client_master

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| company_id | TEXT PK | 고객사 id | structured `load_csv`(CSV — 사람) | aggregate `_struct_client_aliases`, structured `_client_aliases` | 삭제 |
| company | TEXT | 고객사 이름 | 〃 | 〃 | 삭제 |
| aliases | TEXT | 별칭(`\|` 구분) | 〃 | 〃 | 삭제 |

(struct에서는 지우고 `master.client_master`로 옮긴다.)

### struct.prod_master

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| prod_code | TEXT | 제품 코드 | structured `load_csv`(파일 있을 때만) | 없음 | 삭제 |
| division | TEXT | 사업부 | 〃 | 없음 | 삭제 |
| prod_name | TEXT | 제품 이름 | 〃 | 없음 | 삭제 |
| pjt_name | TEXT | 프로젝트 이름 | 〃 | 없음 | 삭제 |
| client_code | TEXT | 고객 코드 | 〃 | 없음 | 삭제 |

(읽는 코드가 없음 — 지우는 안. 확인 목록 U-2.)

### struct.doc_contract_link

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_key | TEXT PK | 문서(sha256) | structured `link_docs` | aggregate `doc_link_list` | 삭제 |
| contract_id | TEXT | 이어진 계약 | 〃 | 〃 | 삭제 |
| score | INTEGER | 점수 | 〃 | 〃 | 삭제 |
| how | TEXT | 이은 방법 | 〃 | 〃 | 삭제 |
| status | TEXT | 상태 | 〃 | 〃 | 삭제 |
| evidence_chunk_keys | TEXT | 근거 청크(늘 `[]`) | 〃 | 〃 | 삭제 |
| created_at | TEXT | 만든 때 | 〃 | 〃 | 삭제 |

### struct.doc_location

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_id | TEXT PK | RDB 문서 id | structured `load_csv`(파일 있을 때만) | structured `_doc_locations`, aggregate `doc_location_list` | 삭제 |
| bucket | TEXT | 버킷 | 〃 | 〃 | 삭제 |
| object_key | TEXT | 객체 키 | 〃 | 〃 | 삭제 |
| etag | TEXT | etag | 〃 | 〃 | 삭제 |
| size_bytes | INTEGER | 크기 | 〃 | 〃 | 삭제 |
| content_type | TEXT | 형식 | 〃 | 〃 | 삭제 |
| company_id | TEXT | 고객사 id | 〃 | 〃 | 삭제 |
| doc_type | TEXT | 문서 종류 | 〃 | 〃 | 삭제 |
| contract_id | TEXT | 계약 id | 〃 | 〃 | 삭제 |
| version | INTEGER | 판 | 〃 | 〃 | 삭제 |
| supersedes_doc_id | TEXT | 대체한 문서 | 〃 | 〃 | 삭제 |
| language | TEXT | 언어 | 〃 | 〃 | 삭제 |
| received_at | TEXT | 받은 때 | 〃 | 〃 | 삭제 |
| updated_at | TEXT | 고친 때 | 〃 | 〃 | 삭제 |
| is_deleted | INTEGER | 삭제 표시 | 〃 | 〃 | 삭제 |

### struct.doc_registry

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_key | TEXT PK | 문서(원본 sha256) | registry `apply` | registry `diff_against`·`nightly_plan`, search/registry | 삭제 |
| s3_key | TEXT PK | 문서 키(원본 전체 키 — 매니페스트 `key`) | (registry `apply`) | (registry, search/registry) | 새로 |
| names | TEXT | 파일 이름 목록(JSON) | registry `apply` | registry `classify` | 유지 |
| size | INTEGER | 크기 | 〃 | 〃 | 유지 |
| mtime | TEXT | 고친 때 | 〃 | 〃 | 유지 |
| etag | TEXT | etag | 〃 | 〃 | 유지 |
| status | TEXT | 상태(parsed·failed·deleted…) | 〃 | 〃 | 유지 |
| source | TEXT | 원천 종류 | 〃 | 〃 | 유지 |
| doc_id | TEXT | RDB 문서 id | 〃 | 〃 | 유지 |
| version | TEXT | 판 | 〃 | 〃 | 유지 |
| first_seen | TEXT | 처음 본 때 | 〃 | search/registry `history` | 유지 |
| last_seen | TEXT | 마지막 본 때 | 〃 | 〃 | 유지 |
| last_build | TEXT | 마지막 build_id | 〃 | 〃 | 유지 |
| rep_sha | TEXT | 대표 본문 sha256(전 판 비교) | registry `update_rep_fingerprints` | registry `link_editions` | 유지 |
| rep_pairs | TEXT | (라벨,값,쪽) 목록(JSON) | 〃 | 〃 | 유지 |
| edition_of | TEXT | 전 판의 문서 키 | registry `link_editions` | search/registry | 유지 |
| content_group | TEXT | 같은 글 묶음 id | registry `content_groups` | 〃 | 유지 |
| value_changes | TEXT | 바뀐 값 목록(JSON) | registry `link_editions` | 〃 | 유지 |
| source_keys | TEXT | `원천::원본 키` 목록(JSON — 지금 sha256↔원본 키 다리) | registry `apply` | registry `link_editions` | 유지 |
| fail_count | INTEGER | 연속 파싱 실패 수 | registry `apply` | registry `nightly_plan`, registry_cli | 유지 |

### struct.doc_registry_seen

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_key | TEXT PK | 문서(sha256) | registry `apply` | search/registry `history`·`report_by_date` | 삭제 |
| s3_key | TEXT PK | 문서 키 | (registry `apply`) | (search/registry) | 새로 |
| build_id | TEXT PK | build 한 번 | registry `apply` | search/registry | 유지 |
| names | TEXT | 파일 이름 목록 | 〃 | 〃 | 유지 |
| size | INTEGER | 크기 | 〃 | 〃 | 유지 |
| mtime | TEXT | 고친 때 | 〃 | 〃 | 유지 |
| etag | TEXT | etag | 〃 | 〃 | 유지 |
| status | TEXT | 상태 | 〃 | 〃 | 유지 |
| source | TEXT | 원천 종류 | 〃 | 〃 | 유지 |
| seen_at | TEXT | 본 때 | 〃 | 〃 | 유지 |

### struct.doc_hidden

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| doc_key | TEXT PK | 숨긴 문서(sha256 — 검색 키 `file_path`와 안 맞아 지금 숨김이 안 먹음, mc-14) | registry `hide`(자동 — 원천에서 삭제), registry_cli `hide`·`unhide` | search/registry `hidden_set` → retriever | 삭제 |
| s3_key | TEXT PK | 숨긴 문서 키(검색 `doc`·`chunk.s3_key`와 같은 값) | (registry `hide`, registry_cli) | (retriever, pgsearch) | 새로 |
| hidden | INTEGER | 1=숨김·0=복구 | registry `hide`·`unhide` | search/registry | 유지 |
| reason | TEXT | 왜 | 〃 | 〃 | 유지 |
| by | TEXT | 누가 | 〃 | 〃 | 유지 |
| at | TEXT | 언제(UTC) | 〃 | 〃 | 유지 |

### struct.doc_table

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| table_key | TEXT PK | 문서 키:표 id | structured `load_tables_docs` | structdb `find_table_cells` | 삭제 |
| doc_key | TEXT | 문서(sha256) | 〃 | 〃 | 삭제 |
| table_id | TEXT | 표 id | 〃 | 〃 | 삭제 |
| page | INTEGER | 쪽 | 〃 | 〃 | 삭제 |
| source_engine | TEXT | 뽑은 엔진 | 〃 | 〃 | 삭제 |
| n_rows | INTEGER | 줄 수 | 〃 | 〃 | 삭제 |
| n_cols | INTEGER | 칸 수 | 〃 | 〃 | 삭제 |
| header_json | TEXT | 머리글 | 〃 | 〃 | 삭제 |
| merged_json | TEXT | 병합 칸 | 〃 | 〃 | 삭제 |
| created_at | TEXT | 만든 때 | 〃 | 〃 | 삭제 |

### struct.doc_cell

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| table_key | TEXT | 표 | structured `load_tables_docs` | structdb `find_table_cells`, search/structdb `find_table_row` | 삭제 |
| row_idx | INTEGER | 줄 | 〃 | 〃 | 삭제 |
| col_idx | INTEGER | 칸 | 〃 | 〃 | 삭제 |
| col_label | TEXT | 칸 이름 | 〃 | 〃 | 삭제 |
| value | TEXT | 값 | 〃 | 〃 | 삭제 |
| value_norm | TEXT | 정규화 값 | 〃 | 〃 | 삭제 |

### struct.stack_version

엔진 구성 판 표(검토 등급 A — [architecture/pipeline_stack.md](pipeline_stack.md)). MCP·파이프라인이 시작할 때 활성 판을 읽는다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| version_id | SERIAL PK | 판 번호 | 판 0002 시드, cfgtables `put` | cfgtables `active`·`history` | 유지 |
| name | TEXT | 판 이름(dev-v1 등) | 〃 | 〃 | 유지 |
| body | JSONB | 설정 전체 | 〃 | cfgtables `active` → server_state, mcp main, stackcfg | 유지 |
| body_sha | CHAR(64) UNIQUE | body sha256 | 〃 | cfgtables `put`(같은 판 거름) | 유지 |
| is_active | BOOLEAN | 활성 판(하나) | cfgtables `activate` | cfgtables `active` | 유지 |
| created_at | TIMESTAMPTZ | 만든 때 | 〃 | cfgtables `history` | 유지 |
| created_by | TEXT | 만든 사람 | 〃 | 〃 | 유지 |
| reason | TEXT | 이유 | 〃 | 〃 | 유지 |
| activated_at | TIMESTAMPTZ | 활성이 된 때 | cfgtables `activate` | 〃 | 유지 |
| activated_by | TEXT | 활성으로 바꾼 사람 | 〃 | 〃 | 유지 |

### struct.source_version

원천 목록 판 표 — `stack_version`과 같은 모양. 읽는 곳: `common/core/sources.py` `load_sources` → cfgtables `active("sources")`.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| version_id | SERIAL PK | 판 번호 | 판 0002 시드, cfgtables `put` | cfgtables | 유지 |
| name | TEXT | 판 이름 | 〃 | 〃 | 유지 |
| body | JSONB | 원천 목록 전체 | 〃 | sources `load_sources` | 유지 |
| body_sha | CHAR(64) UNIQUE | body sha256 | 〃 | cfgtables `put` | 유지 |
| is_active | BOOLEAN | 활성 판 | cfgtables `activate` | cfgtables `active` | 유지 |
| created_at | TIMESTAMPTZ | 만든 때 | 〃 | cfgtables `history` | 유지 |
| created_by | TEXT | 만든 사람 | 〃 | 〃 | 유지 |
| reason | TEXT | 이유 | 〃 | 〃 | 유지 |
| activated_at | TIMESTAMPTZ | 활성이 된 때 | cfgtables `activate` | 〃 | 유지 |
| activated_by | TEXT | 활성으로 바꾼 사람 | 〃 | 〃 | 유지 |

## 4. EDW (MSSQL)

접속: `common.connections.rdb`(읽기 계정 `rdb.read`·쓰기 계정 `rdb.write` — op-03). `query_edw` 도구는 아무 칸이나 읽을 수 있어 아래 "읽는 곳"에서 뺀다.

### edw.FileStorageMap

`AI.FileStorageMap` — 원본 파일 목록(EDW 쪽 표, 이 프로젝트가 만들지 않음 — 칸을 더하거나 지우지 않는다). 저장소에 정의가 없고 PC 대역만 있다(`valid_env/edw/ai.sql` — `id, content_id, content_version_id, s3_key, source_system, original_filename, file_size, sha256, sf_op_id, contract_id, created_at`). 아래는 이 프로젝트가 읽는(읽을) 칸만이고, 결정 칸은 모두 `유지`(EDW 표는 그대로). 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | (EDW) | 행 번호 — 증분 수집 기준 | EDW | extract/source `_rdb_rows`, run_docs `edw_list` | 유지 |
| s3_key | (EDW) | 원본 전체 키 = 문서 키 | EDW | source `_rdb_rows`(매니페스트 `key`), run_docs | 유지 |
| original_filename | (EDW) | 원본 파일 이름 | EDW | source, run_docs | 유지 |
| file_size | (EDW) | 크기 | EDW | source, run_docs | 유지 |
| content_version_id | (EDW) | 판 id | EDW | source `_rdb_rows` | 유지 |
| source_system | (EDW) | 원천(SFDC·CRMS·LAS — 아니면 Other) — 이미 있는 칸, 코드가 아직 직접 안 읽음(지금은 외부 추출 file_meta JSONL로만) → 읽기 시작 | EDW | (source `_rdb_rows`) | 유지 |
| last_modified_time | (EDW, 가정) | 원본 고친 때(10-29 가정 — 있는 칸으로 보고 실제 이름 확인 필요, D-1) → 읽기 시작 | EDW | (변경 감지) | 유지 |

### edw.ParsingMeta

`AI.ParsingMeta` — 파싱 결과(silver) 게시 기록. 정의: `docs/operations/parsing_meta_mssql.sql`. 쓰는 곳: `pipeline/load/parsing_meta.py`(`plan`·`apply` — 행 만들기, `apply_registry_status` — 상태 UPDATE), `common/store/parsing_meta_db.py`(`insert_new`, `update_status`). 10-30 결정: 읽는 칸만 남기고 `gold_status`·`gold_reason`을 더한다([pl-24](../prd/pipeline.md#pl-24)).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| parse_meta_id | BIGINT IDENTITY PK | 행 번호 | DB | 없음(기본 키) | 유지 |
| source_system | NVARCHAR(64) | 원천 | parsing_meta `plan` | parsing_meta_db 겹침 확인·`find_by_doc_key`, 상태 UPDATE 조건 | 유지 |
| source_key | NVARCHAR(1024) | 원본 키 = `s3_key`(문서 키) | 〃 | 〃, run_docs `edw_done_keys` | 유지 |
| source_uri | NVARCHAR(2048) | 원본 주소 | 〃 | 없음 | 삭제 |
| original_filename | NVARCHAR(512) | 원본 파일 이름 | 〃 | 없음 | 삭제 |
| file_format | NVARCHAR(32) | 형식 | 〃 | 없음 | 삭제 |
| file_size | BIGINT | 크기 | 〃 | 없음 | 삭제 |
| sha256 | NVARCHAR(64) | 원본 sha256 | 〃 | 없음 | 삭제 |
| rep_bucket | NVARCHAR(256) | 대표 결과 버킷 | 〃 | parsing_meta_db `find_rep_path` → shaping `rep_uri` | 유지 |
| rep_key | NVARCHAR(2048) | 대표 결과 폴더 | parsing_meta `apply` | 〃 | 유지 |
| rep_etag | NVARCHAR(128) | 대표 결과 etag | 〃 | 없음 | 삭제 |
| parse_status | NVARCHAR(32) | ok·partial | parsing_meta `plan` | run_docs `edw_done_keys` | 유지 |
| status_reason | NVARCHAR(2000) | 상태 이유 | 〃 | 없음 | 삭제 |
| rep_engine | NVARCHAR(128) | 대표 엔진 | 〃 | 없음 | 삭제 |
| rep_acc | FLOAT | 대표 정확도 | 〃 | 없음 | 삭제 |
| page_count | INT | 쪽 수 | 〃 | 없음 | 삭제 |
| doc_key | NVARCHAR(64) | 원본 sha256(지금 유일한 필수 칸 — 검색 키와 안 맞아 `rep_uri`가 늘 빔, mc-15) | 〃 | parsing_meta_db `find_by_doc_key` | 삭제 |
| parse_date | NVARCHAR(32) | 파싱 시각 글자(`YYYY-MM-DD_HHMMSS`) | parsing_meta `apply` | find·상태 UPDATE 조건 | 유지 |
| pipeline_version | NVARCHAR(64) | 파이프라인 판 | parsing_meta `plan` | 없음 | 삭제 |
| status | NVARCHAR(16) | active·changed·deleted | 〃, `apply_registry_status` | find·`find_rep_path`·상태 UPDATE 조건 | 유지 |
| status_at | NVARCHAR(32) | 상태 바뀐 때(UTC) | `apply_registry_status` | 없음(SELECT 안 함 — 운영자가 봄) | 유지 |
| engines_used | NVARCHAR(MAX) | 쓰인 엔진 전부(JSON) | parsing_meta `plan` | 없음 | 삭제 |
| engines_summary | NVARCHAR(512) | 엔진 한 줄 요약 | 〃 | 없음 | 삭제 |
| parsed_at | DATETIME2(0) | 넣은 때(기본 SYSUTCDATETIME) | DB 기본값 | 없음 | 삭제 |
| source_key_hash | BINARY(32) 계산 칸 | `source_key` sha256 — 유일 색인 키(1700바이트 상한 우회) | DB | 유일 색인 | 유지 |
| gold_status | NVARCHAR(32) | gold(검색 DB) 적재 상태 | (pl-24 — run_docs·적재) | (pl-24 재시도·건너뜀) | 새로 |
| gold_reason | NVARCHAR(2000) | gold 상태 이유(실패 원인 등) | (pl-24) | (운영자) | 새로 |

## 5. master — 마스터 PostgreSQL (새 DB, 10-30 결정)

검색 PG와 다른 별도 PostgreSQL(접속 설정 따로 — 아직 없음). 사람이 CSV로 채운다(지금 `structured load --csv-dir`와 같은 방식). 칸은 지금 `struct`의 같은 이름 표 그대로 옮긴다.

### master.contract_master

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| contract_id | TEXT PK | 계약 id | (CSV 적재 — 사람) | (계약 연결·고객 별칭) | 새로 |
| company | TEXT | 고객사 이름 | 〃 | 〃 | 새로 |
| company_id | TEXT | 고객사 id | 〃 | 〃 | 새로 |
| product_code | TEXT | 제품 코드 | 〃 | 〃 | 새로 |
| modality | TEXT | 모달리티 | 〃 | 〃 | 새로 |
| site | TEXT | 생산지 | 〃 | 〃 | 새로 |
| line_id | TEXT | 라인 | 〃 | 〃 | 새로 |
| batches_contracted | INTEGER | 계약 배치 수 | 〃 | 〃 | 새로 |
| contract_value_usd | INTEGER | 계약 금액(USD) | 〃 | 〃 | 새로 |
| currency | TEXT | 통화 | 〃 | 〃 | 새로 |
| term_months | INTEGER | 기간(개월) | 〃 | 〃 | 새로 |
| signed_on | TEXT | 서명일 | 〃 | 〃 | 새로 |
| start_date | TEXT | 시작일 | 〃 | 〃 | 새로 |
| end_date | TEXT | 종료일 | 〃 | 〃 | 새로 |
| status | TEXT | 상태 | 〃 | 〃 | 새로 |

### master.client_master

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| company_id | TEXT PK | 고객사 id | (CSV 적재 — 사람) | (고객 별칭 — aggregate `_struct_client_aliases` 자리) | 새로 |
| company | TEXT | 고객사 이름 | 〃 | 〃 | 새로 |
| aliases | TEXT | 별칭(`\|` 구분) | 〃 | 〃 | 새로 |

## 6. DB 담당자 확인 필요

| # | 무엇 | 왜 |
|---|---|---|
| D-1 | `AI.FileStorageMap`의 실제 정의 — 특히 고친 때 칸 이름(`last_modified_time` 가정)과 `source_system` 값 목록 | 저장소에는 PC 대역(`valid_env/edw/ai.sql` — `created_at`만)뿐 |
| D-2 | 문서당 EDW 고객 하나(`client_edw`)를 얻는 조인 경로 — 원천별(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account.Name`로 보임, CRMS·LAS는?) | 지금은 외부에서 뽑은 `file_meta_new.jsonl`을 읽고, 그 파일을 만드는 코드가 저장소에 없음 → **결정(사용자 10-30):** 파이프라인이 EDW 읽기 계정으로 조인을 직접 만든다(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`) — `file_meta_new.jsonl`을 대신함, [pl-29](../prd/pipeline.md#pl-29). CRMS·LAS 경로는 여전히 확인 필요 |
| D-3 | `AI.ParsingMeta` 칸 15개 삭제·`gold_status`·`gold_reason` 추가(ALTER) — 권한, 기존 행, 다른 사용처 | 이 프로젝트 밖에서 그 칸을 읽는 곳이 있는지 모름 |
| D-4 | `ParsingMeta.doc_key` 삭제 때 `UQ_ParsingMeta_dockey`·`IX_ParsingMeta_doc_key` 색인 처리 · `source_key`를 필수(NOT NULL)로 | 지금 `source_key`가 비면 `doc_key`가 겹침 키 |
| D-5 | 마스터 PostgreSQL 자리·계정·백업 | 새 DB(검색 PG와 분리) |
| D-6 | gold 스키마 변경(`s3_key`·`client_edw`·`clients_doc` 추가, `clients` 삭제)은 Alembic 새 판 — 뷰 `v_chunk_source`를 지우고 다시 만듦(`doc.clients`에 걸려 있음), 기존 서버 데이터는 다시 적재 | 첫 적재가 전체 e2e([pl-23](../prd/pipeline.md#pl-23))와 함께 |
| D-7 | struct 표 지우기(`doc_location`·`doc_contract_link`·`doc_table`·`doc_cell`·`prod_master`, 마스터 2개 이동) 전 백업 | 되돌릴 수 없는 삭제 |

## 7. 사용자 결정 (10-30 grill 7차)

U-1~U-6은 이 문서의 안대로, U-7은 아래 결정대로 한다.

| # | 무엇 | 결정 |
|---|---|---|
| U-1 | `chunk.clients[]`(지금 고객 거르기 키, GIN) — 10-30 결정 "청크는 `clients[]` 유지"와 "거르기는 EDW 고객만"이 겹침 | `chunk.clients` 삭제 → `chunk.client_edw` 새로(거르기 키) |
| U-2 | `struct.prod_master` — 쓰기만 하고 읽는 코드가 없음 | 삭제 |
| U-3 | `doc_contract_link` — pl-25에 "s3_key로 다시 키"와 "문서 파생 표 삭제"가 함께 있음 | 삭제 |
| U-4 | 마스터 읽는 곳 — pl-25는 `gen_roster`·`terms.py`라 했지만 실제로 DB를 읽는 곳은 `aggregate`(`_struct_client_aliases`, 지울 `struct_context`·`_table_cell_scope_docs`·`doc_location_list`)와 `structured._client_aliases`(`gen_roster`는 CSV·EDW 표, `terms.py`는 안 읽음) | 남는 읽는 곳은 고객 별칭뿐 — 마스터 PG에서 읽음 |
| U-5 | 출처 표시 이름을 붙일 값 — 지금은 고객만. 계약 id(`contract_id`)·제품 이름은 EDW에서만 옴 | 고객만 `_edw`·`_doc`로 나눔, 나머지는 그대로 |
| U-6 | `ParsingMeta.status_at`은 SELECT하는 코드가 없음(운영자가 봄) · `parse_meta_id`·`source_key_hash`는 DB 키 | 셋 다 유지 |
| U-7 | 같은 내용이 여러 `s3_key`로 들어온 문서 — 지금은 첫 키만 `doc` 행, 나머지는 `aliases`(묶음 안). 키가 하나뿐인 설계라 둘째 키는 숨김·ParsingMeta 조회가 안 맞음 | `s3_key`마다 `doc` 행 하나 — `doc_alias` 없음. `build_bundle`의 내용 해시 합치기(첫 키로 `aliases`)를 없앰 — 같은 내용이 두 키면 문서 둘(임베딩은 캐시가 다시 씀) |
