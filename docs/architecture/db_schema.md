# DB 스키마 명세 (pl-25)

이 프로젝트가 쓰는 DB 표와 칸을 한곳에 모은 문서다. 표마다 칸, 타입, 뜻, 그 칸을 쓰는 코드, 읽는 코드, 그리고 10-29~10-31 사용자 결정에 따른 0.2.0의 처리(유지·삭제·새로)를 적는다. 요건과 결정의 원문은 [prd/etl.md#pl-25](../prd/etl.md#pl-25)에 있다.

- **이 문서는 설계안이다.** 사용자와 DB 담당자가 승인한 뒤 구현한다. 이 문서를 고치는 브랜치는 코드·스키마·마이그레이션을 바꾸지 않는다.
- **결정 칸:** `유지` = 지금 있고 남김 · `삭제` = 지금 있고 없앰 · `새로` = 지금 없고 만듦. 지금 상태 = `유지`+`삭제`, 목표 상태 = `유지`+`새로`.
- **시험:** `tests/server/common/test_db_schema.py`가 이 문서의 gold 표를 Alembic 판(모델 `common/store/db/models/` — 기존 시험이 판과 같은지 본다)과, ParsingMeta를 [`docs/operations/parsing_meta_mssql.sql`](../operations/parsing_meta_mssql.sql)과 비교한다. 지금 상태가 다르면 실패하고, 목표 상태와의 차이(새로·삭제)는 목록으로 찍기만 한다.
- **쓰는 곳·읽는 곳**은 10-31 develop 기준 코드다(괄호 안은 0.2.0에 생길 곳). 경로는 저장소 기준이고 함수 이름만 적는다.

## 1. 공통 규칙 (10-30·10-31 결정 — 0.2.0)

| 규칙 | 내용 |
|---|---|
| 문서 키 | `s3_key`(Object Storage 원본 전체 키)만 문서 키로 쓴다. sha256 `doc_key`는 없앤다. 문서 대장(`doc_registry`·`doc_registry_seen`)과 숨김(`doc_hidden`)은 지웠다(pl-12 C10 — 판 0003). 검색 `doc`이 `s3_key`를 든다(청크는 `doc_id`만 — 10-31). 같은 내용이 여러 `s3_key`로 들어오면 문서도 여러 개다 — `s3_key`마다 `doc` 행 하나(U-7 결정, `doc_alias` 없음). `build_bundle`의 내용 해시로 첫 키에 합치기(`aliases`)는 없앤다. 임베딩은 캐시가 다시 씀. |
| 출처 표시 이름 | EDW에서도, 문서 파싱에서도 나올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — EDW `_edw`, 문서 본문 `_doc`. 지금 해당하는 값: 고객(`client_edw`·`clients_doc`). |
| 고객 거르기 | MCP의 고객 거르기는 EDW 고객(`doc.client_edw`, 문서당 하나)만 쓴다(C6). EDW 고객이 없는 문서(LAS 등)는 고객 거르기를 걸면 빠진다. 본문에서 찾은 고객(`clients_doc`)은 참고용. |
| 원천 | `source_system` = `AI.FileStorageMap.source_system`(SFDC·CRMS·LAS·FAQ). 비었거나 그 밖의 값이면 `Other`. `s3_key` 접두와 다르면 경고만 남김. |
| 원천별 gold 스키마 | 0.2.0에 원천 시스템마다 PG 스키마 하나 — `sfdc`·`crms`·`las`·`faq`·`other` 5벌([pl-28](../prd/etl.md#pl-28), A2). 스키마마다 같은 표 `doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat`(BM25 통계도 시스템별) — 아래 §2의 `gold.<표>`가 그 틀이다. `load_run`과 Alembic 판 표는 공용 하나. Alembic은 한 모델을 스키마마다 적용한다. 칸 차이: `faq` 스키마만 `chunk.faq_group`(C4), SFDC 전용 칸(`sf_*`·`project_code__c`)은 `sfdc.doc`에만. MCP `search`는 `source_system`을 필수·값 하나로 받아 그 스키마만 찾는다(G20, MCP 계약 변경 — 등급 A). |
| 파일 메타는 `doc`에만 | 고객·`sf_*`·`doc_class`·`created_at`·`contract_id` 같은 파일 메타는 시스템별 `doc`에만 둔다. `chunk`는 문서 키만 갖고 메타를 복사하지 않는다(예외 `faq.chunk.faq_group`). 거르기는 `doc`에서 문서 범위를 고른 뒤 그 안의 `chunk`만 찾는다([pl-28](../prd/etl.md#pl-28)). |
| ParsingMeta = 파싱 정보만 | EDW `AI.ParsingMeta`에는 원천 키·파싱 상태·silver 위치·단계별 칸만 쓴다(G19). 예외: 같은 내용 묶기용 원본 지문 `sha256`은 남긴다(C5). 파일 메타는 쓰지 않는다. 파싱이 통째로 실패한 문서는 행을 쓰지 않는다(C3 — 다음 실행에서 다시 후보). |
| 판 표기 둘 | 두 곳 모두 이름은 `pipeline_version` — ParsingMeta `pipeline_version` = 이 문서를 gold에 올린 판(다시 올릴지 판단) · gold `doc.pipeline_version` = 이 행을 만든 코드 판(검색 쪽 확인). 뜻은 C9대로 나누고 이름만 맞춘다(사용자 10-31 grill — C9 고침, ParsingMeta `gold_version` 안은 없앰). |
| 근거 주소 `rep_uri` | 검색 중 EDW에 접속하지 않는다 — 적재 때 ParsingMeta의 `rep_key`를 gold `doc.rep_key`로 복사하고, `rep_uri`(`s3://<버킷>/<rep_key>`)는 그 값으로 만든다(C8 — mc-15·mc-17). |
| 가장 늦은 행 | 같은 `s3_key`가 `AI.FileStorageMap`에 여러 행이면 `created_at`이 가장 큰 행을 기준으로 삼는다(A4). 나중에 같은 `s3_key`의 더 새 행이 오면 **같은 `doc_id`를 유지한다** — `file_size`가 같으면 다시 파싱하지 않고 저장된 기준·메타만 새 행으로 고치며, `file_size`가 조금이라도 다르면 같은 `doc_id`로 다시 파싱·다시 적재한다(원본을 내려받는 sha256 비교는 하지 않음 — 사용자 10-31). 밀려난 행은 EDW 예외 이력 표(§4 `edw.SupersededRow`, 새로 — D-9)에 남긴다(사용자 10-31 grill, A4 고침). |
| 근거 키 | `doc.file_path`는 지운다. MCP 근거의 `chunk_key`는 `<doc_id>:<순번>` — `doc_id`는 gold `doc.doc_id`(자동 번호), 청크는 `doc_id`만 갖는다(FK, 청크에 `s3_key` 없음). 스키마 5벌이 **시퀀스 하나를 함께 써서** `doc_id`가 스키마끼리 겹치지 않는다(허브 제안 — 사용자 확인 11-01). 적재는 `s3_key`로 upsert하고 다시 넣지 않으므로 `doc_id`가 바뀌지 않는다. `make_chunk_key`·sha256 `doc_key`는 0.2.0에 없어진다(사용자 10-31 grill — mc-16의 `<doc_key>:<순번>`을 뒤집음). |
| 원본 주소 | `source_uri`는 gold `doc.s3_key`로 만들고, 근거 주소 `rep_uri`는 `doc.rep_key`로 만든다(C8) — `s3_key`는 `doc`에만 둔다(사용자 10-31 grill). |
| 원천 id 칸 | 원천 시스템의 id(영업 기회 id 등)는 스키마마다 그 EDW 원본 표의 칸 이름 그대로 둔다(예: `crms.doc`은 CRMS 원본 칸 이름) — `sf_op_id` 같은 한 이름을 함께 쓰지 않는다. 아직 모르는 이름은 "EDW 원본 칸 이름 — D-1 확인"(사용자 10-31 grill). |

## 2. gold — 검색 스키마 (pgvector — 0.2.0에 원천별 스키마 5벌, 아래는 그 틀)

판: `common/store/db/migrations/versions/0001_search_base.py` · 모델: `common/store/db/models/search_tables.py` · 적재: `pipeline/load/pgvector_load.py`(`load`, `deploy`) · 값 만드는 곳: `pipeline/transform/structure/build_bundle.py`(`main`). 아래 `gold.<표>`는 지금 표 한 벌(`PG_SCHEMA`)의 칸과 0.2.0 목표다 — 0.2.0에는 이 틀을 `sfdc`·`crms`·`las`·`faq`·`other` 스키마마다 만든다(§1). `load_run`과 Alembic 판 표는 나눈 뒤에도 하나로 둔다.

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
| doc_id | SERIAL PK | 문서 행 번호(내부) — MCP `chunk_key`의 앞부분. 0.2.0: 스키마 5벌이 시퀀스 하나를 함께 씀(겹치지 않음 — 허브가 정함), `s3_key`로 upsert해 번호가 바뀌지 않음(사용자 10-31 grill) | pgvector_load `load` | pgsearch, 뷰 `v_chunk_source` | 유지 |
| file_path | TEXT | 개발 서버 기준 원본 경로 — 0.2.0에 지움(보여 줄 때는 `s3_key` + `original_filename`, MCP 출력에서도 뺌 — mc-16, 등급 A) | build_bundle `main` | pgsearch, retriever, search_svc, shaping, local, aggregate, `schemas/evidence.py`(MCP `search` 출력 키), `cli/ask.py`, `models/search_tables.py`(칸·`VIEWS_EXPECTED`·뷰 SQL), `schemas/search_rows.py`, 뷰, pgvector_load·build_bundle(건너뛰기 키 → `s3_key`), `validation/search_ui/serve.py` | 삭제 |
| original_filename | TEXT | 원본 파일 이름(보여 주기용) | (파이프라인 — `AI.FileStorageMap.original_filename`) | (pgsearch, retriever, search_svc, shaping, 뷰) | 새로 |
| s3_key | TEXT | 문서 키 — Object Storage 원본 전체 키(`AI.FileStorageMap.s3_key`). 적재 upsert 키, `source_uri`를 만듦. `doc`에만 둔다(청크에는 없음 — 사용자 10-31 grill) | (build_bundle가 이미 `_s3_key`로 알지만 묶음에 안 넣음) | (대장·숨김·ParsingMeta 조회) | 새로 |
| clients | TEXT(JSON) | 고객 목록 — 지금은 본문에서 찾은 이름(`infer_clients`)과 섞여 있음 | build_bundle `infer_clients` | pgsearch `_client_restrict`, retriever, internal_docs, search_svc | 삭제 |
| client_edw | TEXT | EDW 조인으로 얻은 고객 하나 — MCP 고객 거르기의 유일한 키 | (파이프라인이 EDW 읽기 계정으로 직접 조인 — [pl-29](../prd/etl.md#pl-29)) | (pgsearch 고객 거르기) | 새로 |
| clients_doc | TEXT(JSON) | 문서 본문에서 찾은 고객 목록(참고용 — 거르기에 안 씀) | (build_bundle `infer_clients`) | (근거 표시) | 새로 |
| summary | TEXT | 요약(검색 결과용) | build_bundle | 뷰 → retriever → shaping | 유지 |
| source_system | VARCHAR(20) | SFDC·CRMS·LAS·Other — 0.2.0에는 스키마가 원천을 정하므로 지운다(사용자 10-31 grill) | build_bundle(`s3_key` 접두, 없으면 file_meta) | 뷰 → search_svc, internal_docs | 삭제 |
| sf_acc_name | TEXT | SFDC 고객사 이름 — 0.2.0: 스키마마다 그 EDW 원본 표의 칸 이름으로 둔다(`sfdc.doc`은 SFDC 원본 칸 이름, 다른 스키마는 그 원본 칸 이름 — EDW 원본 칸 이름 — D-1 확인, 사용자 10-31 grill) | build_bundle(file_meta JSONL → EDW 직접 — [pl-29](../prd/etl.md#pl-29)) | 뷰 → search_svc, internal_docs | 유지 |
| sf_op_id | TEXT | SFDC 영업 기회 id — 0.2.0: 스키마마다 그 EDW 원본 표의 칸 이름으로 둔다(`sfdc.doc`은 SFDC 원본 칸 이름, 다른 스키마는 그 원본 칸 이름 — EDW 원본 칸 이름 — D-1 확인, 사용자 10-31 grill) | build_bundle(file_meta → EDW 직접) | 뷰 → internal_docs(그대로 내보냄) | 유지 |
| sf_op_name | TEXT | SFDC 영업 기회 이름 — 0.2.0: 스키마마다 그 EDW 원본 표의 칸 이름으로 둔다(`sfdc.doc`은 SFDC 원본 칸 이름, 다른 스키마는 그 원본 칸 이름 — EDW 원본 칸 이름 — D-1 확인, 사용자 10-31 grill) | build_bundle(file_meta → EDW 직접) | 뷰 → internal_docs | 유지 |
| project_code__c | TEXT | SFDC 프로젝트 코드 — 0.2.0: 스키마마다 그 EDW 원본 표의 칸 이름으로 둔다(`sfdc.doc`은 SFDC 원본 칸 이름, 다른 스키마는 그 원본 칸 이름 — EDW 원본 칸 이름 — D-1 확인, 사용자 10-31 grill) | build_bundle(file_meta → EDW 직접) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| contract_id | TEXT | 계약 id | build_bundle(file_meta → EDW 직접) | 뷰 → internal_docs | 유지 |
| contract_date | DATE | 계약일 | build_bundle(file_meta → EDW 직접) | 뷰 → internal_docs | 유지 |
| prod_name | TEXT | 제품 이름 | build_bundle(file_meta → EDW 직접) | 뷰 → internal_docs | 유지 |
| division | VARCHAR(20) | 사업부(DS/DP/CD/CM/AD/AS) | build_bundle(file_meta → EDW 직접) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| service_type | VARCHAR(20) | 서비스 종류(CMO DS 등) | build_bundle(file_meta → EDW 직접) | 뷰 → search_svc, internal_docs(거르기) | 유지 |
| run_id | INT | 이 행을 넣은 적재(`load_run`) | pgvector_load `load` | 없음 | 유지 |
| pipeline_version | TEXT | 이 행을 만든 코드 판(`VERSION`) — ParsingMeta `pipeline_version`(gold에 올린 판)과 이름은 같고 뜻은 다르다(C9, 사용자 10-31 grill) | (pgvector_load `load`) | (검색 쪽 확인·운영자) | 새로 |
| doc_class | TEXT | 문서 분류 라벨 하나(SFDC: RFI/RFP/RFI+RFP/Proposal/Other, LAS: MSA/PSA/QAG/LOI/Amendment/Assignment Letter/Other, 다른 원천 NULL) — low_conf·모델·시각은 두지 않음. ParsingMeta에는 두지 않는다(G19) — D-6 | (분류 단계 → 적재 — [pl-33](../prd/etl.md#pl-33)) | (MCP `search`·`list_doc_fulltext` 거르기 — mc-16, mc-17) | 새로 |
| created_at | TIMESTAMPTZ | 원천 등록 시각 — 출처는 `AI.FileStorageMap.created_at`(시간대 없는 값은 KST로 읽음). ParsingMeta에는 두지 않는다(G19). `search`의 `created_since`/`created_until` 거르기, `list_doc_fulltext` 거르기·출력, `get_doc_fulltext` 등록 시각 가드에 씀 — D-6 | (적재 — FileStorageMap) | (MCP 거르기 — mc-16, mc-17) | 새로 |
| rep_key | TEXT | 대표 파싱 결과(silver) 위치 — 적재 때 ParsingMeta `rep_key`에서 복사. `rep_uri`는 이 값으로 만든다(C8) | (적재) | (shaping `rep_uri`, mc-17 원문 도구) | 새로 |
| rep_engine | TEXT | 대표 silver 엔진 + 판 — 적재 때 ParsingMeta에서 복사(G19 — 원문 도구가 EDW를 읽지 않게) | (적재) | (mc-17 `list_doc_fulltext` 출력) | 새로 |
| parsed_at | TIMESTAMPTZ | 파싱한 때 — 적재 때 ParsingMeta `parsed_at`에서 복사(G19) | (적재) | (mc-17 `list_doc_fulltext` 출력) | 새로 |

### gold.chunk

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| chunk_id | SERIAL PK | 청크 행 번호 | pgvector_load `load` | pgsearch, 뷰, server_checks | 유지 |
| doc_id | INT FK→doc | 문서 — 청크가 갖는 문서 키는 이것뿐(`s3_key`는 `doc`에만, 사용자 10-31 grill) | pgvector_load `load` | 조인 전부 | 유지 |
| seq | INT | 문서 안 순번 — MCP `chunk_key` = `<doc_id>:<seq>`(사용자 10-31 grill) | pgvector_load | 뷰 → retriever, internal_docs | 유지 |
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
| clients | TEXT[] | 고객 라벨(GIN — 지금 고객 거르기 키, `doc.clients`에서 복사) — 0.2.0: 청크에 고객 칸 없음, `doc.client_edw`로 범위를 고름(pl-28) | pgvector_load `_chunk_clients`, `backfill_chunk_clients` | pgsearch `_client_restrict` | 삭제 |
| source_system | VARCHAR(20) | 원천(거르기용 — 문서와 같은 값) — 0.2.0에는 스키마가 원천을 정하므로 지운다(pl-28) | pgvector_load | 뷰 → search_svc, internal_docs | 삭제 |
| faq_group | TEXT | FAQ 시트 이름(`FAQ_group`) — `faq.chunk`에만(C4, [pl-39](../prd/etl.md#pl-39)) | (FAQ 적재) | (MCP `search` `FAQ_group` 거르기) | 새로 |

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

뷰 `v_chunk_source`는 `chunk`↔`doc`을 이은 읽기 전용 뷰다(지금은 파일 이름을 `file_path`에서 계산). 0.2.0에는 스키마마다 다시 만든다 — 지금 `d.clients`·`d.file_path`를 고르므로 먼저 `DROP VIEW` 하고 새 칸(`s3_key`·`original_filename`·`client_edw`·`clients_doc`·`rep_key` 등)으로 다시 만든다(`CREATE OR REPLACE VIEW`로는 칸을 뺄 수 없음). 모델의 `VIEWS_EXPECTED`도 같이 고친다.

## 3. struct — 없음 (사용자 11-01)

PostgreSQL `struct` 스키마는 코드에서 모두 없앴다(사용자 11-01 — [D-031·pl-08](../prd/etl.md#pl-08)). 정형 표·문서 대장·마스터(판 `0003_struct`로 지우려던 표 10개)와 버전 테이블 `stack_version`·`source_version`, 그 Alembic 판(`0001_struct`~`0003_struct`)이 모두 없다. 엔진 구성은 `resources/config/pipeline_stack.json`, 원천 목록은 `resources/mappings/sources.json` 파일을 서버·PC가 같이 읽는다(바꾸기 = 파일을 고쳐 오버레이 패치). 마스터는 CSV 파일이다(§5). 서버에 남은 struct 스키마(운영 문서 기준 쓰이지 않음 — `doc_registry` 0행)는 코드가 읽지 않는다 — 그대로 두거나 DB 담당자가 지운다(D-7).

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
| created_at | (EDW) | 원천 등록 시각 — 같은 `s3_key`의 여러 행 중 가장 큰 값의 행이 기준(A4). 더 새 행이 오면 같은 `doc_id`를 유지하고, `file_size`가 같으면 기준·메타만 고치고 다르면 다시 파싱·적재한다(사용자 10-31). gold `doc.created_at`으로 복사(KST). PC 대역에 칸이 있음, 실제 EDW는 D-1 | EDW | (source — 기준 행 고르기, 적재) | 유지 |
| last_modified_time | (EDW, 가정) | 원본 고친 때(10-29 가정 — 있는 칸으로 보고 실제 이름 확인 필요, D-1) → 읽기 시작 | EDW | (변경 감지) | 유지 |

### edw.SupersededRow

같은 `s3_key`의 더 새 `FileStorageMap` 행 때문에 밀려난 행의 **예외 이력**(새 EDW 표 — 사용자 10-31 grill). 어느 행이 어느 문서와 겹쳤는지, "파싱 대상 아님"을 남긴다. 표 이름과 칸은 DB 담당자가 정한다(D-9) — 아래는 안이다. 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| file_storage_map_id | (EDW, 안) | 밀려난 `FileStorageMap` 행 id | (파이프라인 — 기준 행 고를 때) | (운영자) | 새로 |
| s3_key | (EDW, 안) | 겹친 문서의 원본 키 | 〃 | 〃 | 새로 |
| kept_file_storage_map_id | (EDW, 안) | 기준으로 남은 행 id | 〃 | 〃 | 새로 |
| reason | (EDW, 안) | "파싱 대상 아님 — 같은 s3_key의 더 새 행" | 〃 | 〃 | 새로 |
| recorded_at | (EDW, 안) | 기록한 때 | 〃 | 〃 | 새로 |

### edw.Quote

PC 대역 예시 — [pl-29](../prd/etl.md#pl-29) 10-31. 고객 연결 4단계의 마지막(Quote)을 PC에서 구현·시험하려고 PC 대역 EDW(`valid_env/edw`)에 SFDC Quote 표를 **예시 칸**으로 새로 만든다(A3). 서버 레플리카에는 Quote 표가 없다 — Quote는 `OpportunityId`로 파일과 이어진다고 가정한다(사용자 10-31 grill). 실제 표·칸 이름은 DB 담당자 답(D-1)으로 맞춘다. 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| Id | (예시) | Quote id | (PC 대역 시드) | (고객 연결 4단계) | 새로 |
| OpportunityId | (예시) | 연결된 영업 기회 | 〃 | 〃 | 새로 |
| AccountId | (예시) | 연결된 고객 계정 — 고객 이름은 `SFDC.Account` | 〃 | 〃 | 새로 |

### edw.ParsingMeta

`AI.ParsingMeta` — 파싱 결과(silver) 게시 기록. 정의: `docs/operations/parsing_meta_mssql.sql`. 쓰는 곳: `pipeline/load/parsing_meta.py`(`plan`·`apply` — 행 만들기, `apply_registry_status` — 상태 UPDATE), `common/store/parsing_meta_db.py`(`insert_new`, `update_status`). 0.2.0 결정: **파싱 정보만** 둔다(G19) — 원천 키·파싱 상태·silver 위치·단계별 칸, 예외로 원본 지문 `sha256`(C5). 파일 메타(`doc_class`·`sf_op_id`·`created_at`·고객)는 쓰지 않고 시스템별 gold `doc`에만 둔다. 파싱이 통째로 실패하면 행을 쓰지 않는다(C3). `gold_status`·`gold_reason`을 더한다([pl-24](../prd/etl.md#pl-24)).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| parse_meta_id | BIGINT IDENTITY PK | 행 번호 | DB | 없음(기본 키) | 유지 |
| source_system | NVARCHAR(64) | 원천 | parsing_meta `plan` | parsing_meta_db 겹침 확인·`find_by_doc_key`, 상태 UPDATE 조건 | 유지 |
| source_key | NVARCHAR(1024) | 원본 키 = `s3_key`(문서 키) | 〃 | 〃, run_docs `edw_done_keys` | 유지 |
| source_uri | NVARCHAR(2048) | 원본 주소 | 〃 | 없음 | 삭제 |
| original_filename | NVARCHAR(512) | 원본 파일 이름 | 〃 | 없음 | 삭제 |
| file_format | NVARCHAR(32) | 형식 | 〃 | 없음 | 삭제 |
| file_size | BIGINT | 크기 | 〃 | 없음 | 삭제 |
| sha256 | NVARCHAR(64) | 원본 sha256 — 같은 내용 묶기에 씀(C5 — G19 "파싱 정보만"의 예외, 파싱한 원본의 지문) | parsing_meta `plan` | (분류 단계 같은 내용 묶음 — [pl-33](../prd/etl.md#pl-33)) | 유지 |
| rep_bucket | NVARCHAR(256) | 대표 결과 버킷 | parsing_meta `plan` | parsing_meta_db `find_rep_path` → shaping `rep_uri`(0.2.0에는 이 조회 길을 없애고 적재 때 gold `doc.rep_key`로 복사 — C8) | 유지 |
| rep_key | NVARCHAR(2048) | 대표 결과 폴더 | parsing_meta `apply` | 〃 → (적재가 gold `doc.rep_key`로 복사 — C8) | 유지 |
| rep_etag | NVARCHAR(128) | 대표 결과 etag | 〃 | 없음 | 삭제 |
| parse_status | NVARCHAR(32) | ok·partial | parsing_meta `plan` | run_docs `edw_done_keys` | 유지 |
| status_reason | NVARCHAR(2000) | 상태 이유 | 〃 | 없음 | 삭제 |
| rep_engine | NVARCHAR(128) | 대표 엔진 — 0.2.0: 대표 silver 엔진 + 판(아래 단계별 칸). gold `doc.rep_engine`으로 복사(G19) | parsing_meta `plan` | (적재 — gold `doc` 복사) | 유지 |
| rep_acc | FLOAT | 대표 정확도 | 〃 | 없음 | 삭제 |
| page_count | INT | 쪽 수 | 〃 | 없음 | 삭제 |
| doc_key | NVARCHAR(64) | 원본 sha256(지금 유일한 필수 칸 — 검색 키와 안 맞아 `rep_uri`가 늘 빔, mc-15) | 〃 | parsing_meta_db `find_by_doc_key` | 삭제 |
| parse_date | NVARCHAR(32) | 파싱 시각 글자(`YYYY-MM-DD_HHMMSS`) | parsing_meta `apply` | find·상태 UPDATE 조건 | 유지 |
| pipeline_version | NVARCHAR(64) | 이 문서를 gold에 올린 판 — 다시 올릴지 판단. 지금은 파싱 때 쓰는 파이프라인 판이었으나 0.2.0에는 gold 성공 때 쓰고 gold가 끝나기 전에는 NULL(C9 — gold `doc.pipeline_version`은 행을 만든 코드 판, 이름 같고 뜻 다름 — 사용자 10-31 grill: `gold_version` 새 칸 대신 이 칸 이름을 씀) | parsing_meta `plan` → (gold 성공 때) | (운영자·재처리 판정) | 유지 |
| status | NVARCHAR(16) | active·changed·deleted | 〃, `apply_registry_status` | find·`find_rep_path`·상태 UPDATE 조건 | 유지 |
| status_at | NVARCHAR(32) | 상태 바뀐 때(UTC) | `apply_registry_status` | 없음(SELECT 안 함 — 운영자가 봄) | 유지 |
| engines_used | NVARCHAR(MAX) | 쓰인 엔진 전부(JSON) — 0.2.0: 성공한 엔진만(이름 + 판, 사용자 10-30 grill) | parsing_meta `plan` | 없음 | 유지 |
| engines_summary | NVARCHAR(512) | 엔진 한 줄 요약 | 〃 | 없음 | 삭제 |
| parsed_at | DATETIME2(0) | 넣은 때(기본 SYSUTCDATETIME) — 파싱 정보라 남김(G19), gold `doc.parsed_at`으로 복사 | DB 기본값 | (적재 — gold `doc` 복사) | 유지 |
| source_key_hash | BINARY(32) 계산 칸 | `source_key` sha256 — 유일 색인 키(1700바이트 상한 우회) | DB | 유일 색인 | 유지 |
| gold_status | NVARCHAR(32) | gold(검색 DB) 적재 상태 | (pl-24 — run_docs·적재) | (pl-24 재시도·건너뜀) | 새로 |
| gold_reason | NVARCHAR(2000) | gold 상태 이유(실패 원인 등) | (pl-24) | (운영자) | 새로 |
| stack_version | INT | 파싱 엔진 스택 판 — **결정 대기(11-01):** 판 표가 없어져 판 번호가 없다(엔진 구성 파일의 sha·이름으로 바꿀지, 칸을 뺄지). 파싱이 통째로 실패하면 행 자체를 쓰지 않는다(C3) | (파싱 단계 성공 때) | (운영자·재처리 판정) | 새로 |
| engines_failed | NVARCHAR(MAX) | 실패한 엔진(JSON — 이름·이유·걸린 시간), 없으면 NULL | (파싱 단계 — 사용자 10-30 "EDW에도") | (운영자·재시도 판단) | 새로 |

**운영이 더한 분류·고객 칸(G19 — 4차 grill, G1·G9를 뒤집음):** 운영이 ParsingMeta에 더한 분류·고객 칸(`doc_class`·`sf_op_id`·`created_at`·`sf_acc_name` 등 — 이 저장소의 DDL에는 없음)은 0.2.0에 모두 지운다(DB 담당자 D-3, 등급 A). 분류·고객·등록 시각은 시스템별 gold `doc`에만 둔다([pl-33](../prd/etl.md#pl-33), [pl-29](../prd/etl.md#pl-29)). 그때 운영 분류 스크립트가 멈추므로 운영 담당자에게 알린다.

**단계별 기록(사용자 10-30 grill — 등급 A, DB 담당자 D-3):** 단계마다 성공했을 때만 쓴다(파싱이 통째로 실패하면 행 없음 — C3) — 파싱: `stack_version`·성공한 엔진(`engines_used`)·실패한 엔진(`engines_failed`)·대표 silver 엔진 + 판(`rep_engine`) · gold: `pipeline_version`·`gold_status`. 3차의 "읽는 칸만" 안에 칸을 다시 더한 것이다. 저장 구조(silver = Object Storage uuid5 폴더 · gold = pgvector)는 [pl-32](../prd/etl.md#pl-32).

## 5. master — CSV 파일 (`resources/vocab/glossary/`, 사용자 10-30)

마스터 성격 자료(용어집, 고객 명부, `contract_master`, `client_master`)는 **DB가 아니라 CSV 파일**이다. 별도 마스터 PostgreSQL도, 용어집용 SQLite 대역도 없다(10-30 grill 9~10차의 "마스터 PG + PC SQLite 대역" 결정을 뒤집음). CSV(샘플 데이터)는 git의 `resources/vocab/glossary/`(지금 폴더)에 두어 이미지에 함께 들어간다 — 서버 폴더·마운트 없음, `glossary_dir`는 이미지 경로. 샘플 CSV 넷이 들어 있다(10-30 — `client_roster.example.csv`·`domain_terms.example.csv`를 대신함, 한빛 샘플 문서의 고객·제품 포함). git의 CSV는 샘플 데이터(사용자 10-30) — server-guide §5 기밀 규칙과 충돌 없음.

| 파일 | 무엇 | 머리글 | 읽는 곳 |
|---|---|---|---|
| `domain_terms.csv` | 용어 사전(C-21) | `concept_id,canonical,category,synonyms,abbreviations,weak_synonyms,broader,related,context_required,case_sensitive,definition_ko,definition_en,source,owner,status,updated` (`status`는 approved·draft) | `common.core.terms` |
| `client_roster.csv` | 고객 명부(C-21, 새 형식) | `client_id,canonical_name,name_ko,aliases,client_type,segment,country,parent_client_id,status,description,source,updated` — 읽는 칸: `canonical_name`(비면 `name_ko`), `aliases`(`;`·`\|` 구분), `status`(inactive·deleted면 건너뜀) | `common.core.terms` 고객 별칭(초안은 `gen_roster`) |
| `contract_master.csv` | 계약 마스터 | `contract_id,company,company_id,product_code,modality,site,line_id,batches_contracted,contract_value_usd,currency,term_months,signed_on,start_date,end_date,status` (옛 `struct.contract_master`와 같은 칸) | 계약 연결·고객 별칭 |
| `client_master.csv` | 고객 마스터 | `company_id,company,aliases`(별칭 `\|` 구분 — 옛 `struct.client_master`와 같은 칸) | 고객 별칭(aggregate `_struct_client_aliases` 자리) |

- `client_master.example.csv`(머리글 `Account_Id,Account_Name,Account_Name_KR,Alias_List,Account_Type,Billing_Country,Parent_Id,Account_Status`)는 EDW 모양 원본 — `gen_roster --kind client --source csv:client_master.csv --mapping …`이 명부 초안을 만들 때 읽는다.
- 같이 있는 `id_patterns.csv`·`units.csv`·`client_roster_seed.json`·`client_master_map.example.json`은 그대로.

## 6. DB 담당자 확인 필요

| # | 무엇 | 왜 |
|---|---|---|
| D-1 | `AI.FileStorageMap`의 실제 정의 — 특히 고친 때 칸 이름(`last_modified_time` 가정)과 `source_system` 값 목록 | 저장소에는 PC 대역(`valid_env/edw/ai.sql` — `created_at`만)뿐 · **G9(사용자 10-30) 확인:** 지금 운영 `ParsingMeta.created_at`은 원천별 표에서 온다(SFDC `ContentVersion_dump.CreatedDate`, CRMS `RM_CM_DOCU.INIT_DTTM`, LAS `FileManager.CreateDate`) — `FileStorageMap.created_at`이 같은 값을 갖는지 · **0.2.0(A4·A3):** `FileStorageMap.created_at`이 실제로 있는지(같은 `s3_key` 중 가장 늦은 행을 이 칸으로 고름) · SFDC Quote 표의 실제 이름·칸(PC 대역은 예시 칸 — §4 `edw.Quote`) · **사용자 10-31 grill:** 원천 id 칸(영업 기회 id 등)의 원천별 실제 칸 이름 · Quote가 `OpportunityId`로 파일과 이어지는지 |
| D-2 | 문서당 EDW 고객 하나(`client_edw`)를 얻는 조인 경로 — 원천별(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account.Name`로 보임, CRMS·LAS는?) | 지금은 외부에서 뽑은 `file_meta_new.jsonl`을 읽고, 그 파일을 만드는 코드가 저장소에 없음 → **결정(사용자 10-30):** 파이프라인이 EDW 읽기 계정으로 조인을 직접 만든다(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`) — `file_meta_new.jsonl`을 대신함, [pl-29](../prd/etl.md#pl-29). CRMS·LAS 경로는 여전히 확인 필요 · **2차 grill(사용자 10-30, G2):** CRMS는 `FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST`로 채움(DB 담당자 확인) · LAS는 상대사 출처가 정해질 때까지 비움 |
| D-3 | `AI.ParsingMeta` 칸 정리(ALTER) — 안 읽는 칸 삭제, `gold_status`·`gold_reason`·단계별 칸(`stack_version`·`engines_failed`) 추가, `pipeline_version` 뜻 바꿈(gold에 올린 판 — gold 성공 때 씀, 10-31: 새 칸 `gold_version` 대신), `engines_used`·`rep_engine` 뜻 바꿈 — 권한, 기존 행, 다른 사용처 | 이 프로젝트 밖에서 그 칸을 읽는 곳이 있는지 모름 · **G19·C5(0.2.0):** 파싱 정보만 — 운영이 더한 분류·고객 칸(`doc_class`·`sf_op_id`·`created_at`·`sf_acc_name` 등)은 모두 지움, `sha256`은 남김 · 운영 분류 스크립트가 멈춤 |
| D-4 | `ParsingMeta.doc_key` 삭제 때 `UQ_ParsingMeta_dockey`·`IX_ParsingMeta_doc_key` 색인 처리 · `source_key`를 필수(NOT NULL)로 | 지금 `source_key`가 비면 `doc_key`가 겹침 키 |
| D-5 | (없어짐 — 사용자 10-30: 마스터는 CSV 파일, 마스터 PostgreSQL 없음) | — |
| D-6 | 0.2.0 Alembic 마이그레이션 하나 — 원천별 gold 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other`) 만들기 — `doc_id`는 스키마 5벌이 함께 쓰는 시퀀스 하나(허브가 정함)(칸: `s3_key`·`original_filename`·`client_edw`·`clients_doc`·`doc_class`·`created_at`·`rep_key`·`rep_engine`·`parsed_at`·`pipeline_version` 추가, `file_path`·`clients`·`doc.source_system`·`chunk.source_system` 삭제, 청크는 `doc_id`만(청크 `s3_key` 없음), `faq.chunk.faq_group`) — struct는 코드에서 없앰(D-7), 뷰 `v_chunk_source`는 스키마마다 다시 만듦 — 기존 서버 데이터는 다시 적재 | DB 담당자 승인 한 번([pl-25](../prd/etl.md#pl-25)) · 첫 적재가 전체 e2e([pl-23](../prd/etl.md#pl-23))와 함께 |
| D-7 | 서버에 남은 struct 스키마 — 그대로 둘지 지울지(지운다면 백업 뒤 DB 담당자가 직접 — 코드에는 struct 판이 없음, 사용자 11-01) | 코드가 읽지 않음 · 지우면 되돌릴 수 없음 |
| D-8 | FAQ 원천 등록 — Object Storage `FAQ/<uuid>/<파일>`을 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록(G3, 사용자 10-30 — [pl-39](../prd/etl.md#pl-39)) | EDW 담당자 협의 필요 — FAQ 행을 누가 어떻게 넣나 |
| D-9 | 밀려난 `FileStorageMap` 행의 예외 이력 표(새 EDW 표 — §4 `edw.SupersededRow` 안) — 표 이름·칸·누가 쓰나 | 사용자 10-31: 같은 `s3_key`의 더 새 행이 오면 같은 `doc_id`(`file_size`가 다를 때만 다시 파싱)이고 옛 행을 이력에 남김 |
| D-10 | `applog` 스키마 추가(§8) — `up`의 `CREATE SCHEMA`, `maintain`의 파티션 생성·DROP, 앱의 INSERT와 `pipe_run` UPDATE 권한. 호출량 기준 용량(`mcp_call` 행 본문 최대 약 80KB) | 새 스키마이고 로그 쓰기가 기존 PG 접속 정보를 함께 씀 |
| D-11 | `applog.mcp_call`의 `args`·`result` 읽기 권한 분리 | 문서 본문·EDW 결과가 들어가는데 판에 GRANT가 없어 지금은 앱 계정이 읽을 수 있음 |
| D-12 | 실제 보존 기간 약 90~120일(월 단위 DROP)이 감사·개인정보 기준에 맞는지, `dbtool maintain` 매일 예약 | 예약이 약 2개월 이상 멈추면 새 달 파티션이 없어 DB 쓰기가 실패하고 대체 파일로만 쌓임 |

## 7. 사용자 결정 (10-30 grill 7차)

U-1~U-6은 이 문서의 안대로, U-7은 아래 결정대로 한다.

| # | 무엇 | 결정 |
|---|---|---|
| U-1 | `chunk.clients[]`(지금 고객 거르기 키, GIN) — 10-30 결정 "청크는 `clients[]` 유지"와 "거르기는 EDW 고객만"이 겹침 | `chunk.clients` 삭제 → `chunk.client_edw` 새로(거르기 키) → **10-30 4차 grill(pl-28)로 바뀜:** 청크에는 고객 칸을 두지 않고 `doc.client_edw`로 문서 범위를 고른다 |
| U-2 | `struct.prod_master` — 쓰기만 하고 읽는 코드가 없음 | 삭제 |
| U-3 | `doc_contract_link` — pl-25에 "s3_key로 다시 키"와 "문서 파생 표 삭제"가 함께 있음 | 삭제 |
| U-4 | 마스터 읽는 곳 — pl-25는 `gen_roster`·`terms.py`라 했지만 실제로 DB를 읽는 곳은 `aggregate`(`_struct_client_aliases`, 지울 `struct_context`·`_table_cell_scope_docs`·`doc_location_list`)와 `structured._client_aliases`(`gen_roster`는 CSV·EDW 표, `terms.py`는 안 읽음) | 남는 읽는 곳은 고객 별칭뿐 — CSV(`resources/vocab/glossary/`)에서 읽음(10-30 바뀜: 마스터 PG 없음) |
| U-5 | 출처 표시 이름을 붙일 값 — 지금은 고객만. 계약 id(`contract_id`)·제품 이름은 EDW에서만 옴 | 고객만 `_edw`·`_doc`로 나눔, 나머지는 그대로 |
| U-6 | `ParsingMeta.status_at`은 SELECT하는 코드가 없음(운영자가 봄) · `parse_meta_id`·`source_key_hash`는 DB 키 | 셋 다 유지 |
| U-7 | 같은 내용이 여러 `s3_key`로 들어온 문서 — 지금은 첫 키만 `doc` 행, 나머지는 `aliases`(묶음 안). 키가 하나뿐인 설계라 둘째 키는 숨김·ParsingMeta 조회가 안 맞음 | `s3_key`마다 `doc` 행 하나 — `doc_alias` 없음. `build_bundle`의 내용 해시 합치기(첫 키로 `aliases`)를 없앰 — 같은 내용이 두 키면 문서 둘(임베딩은 캐시가 다시 씀) |

## 8. applog — 로그 저장소 (pgvector PG, 스키마 `applog`, [op-01](../prd/settings.md#op-01))

위 §2~§7의 pl-25 설계안과 별개인 표다. 기존 gold·EDW 표는 바꾸지 않는다. 서버에는 아직 없어서 칸의 결정은 모두 `새로`다(적용 절차는 refactor.md C-74).

판: `common/store/db/migrations/versions/0001_applog_base.py`(브랜치 `applog`) · 파티션 관리: `common/store/db/migrations/applog_parts.py` · 모델: `common/store/db/models/log_tables.py` · 쓰기: `common/store/logsink.py`(큐 → 배치 INSERT, 실패하면 `output/applog/*.jsonl`, 앱이 DDL을 실행하지 않음). 켜는 설정: 파일 자리 `ops.log.db_enabled`(모델 `common.log.db_enabled`, 기본 꺼짐). `tests/server/common/test_db_schema.py`는 이 절을 대조하지 않는다 — 판과 실제 DB 대조는 `dbtool check --target applog`.

- **파티션:** `mcp_call`(`ts`)·`pipe_event`(`ts_start`)는 월 단위(UTC). 이름은 `<표>_YYYYMM`. `dbtool up`과 `dbtool maintain`이 현재 달부터 3개월 치를 만든다.
- **보존:** `dbtool maintain --target applog`를 매일 실행한다. `ops.log.retention_days`(기본 90)가 지난 달의 파티션을 DROP하고 `pipe_run`은 DELETE한다. 달이 통째로 지나야 DROP되므로 파티션 표의 행은 약 90~120일 남는다.
- **되돌리기:** `downgrade`는 막혀 있다. 지우려면 DB 담당자가 직접 한다.
- **연결:** `pipe_event.run_id` → `pipe_run.run_id`는 외래 키가 없다(지우는 시점이 달라 짝 없는 행이 생길 수 있음). 파티션 표의 `id`는 기본 키가 시각과 묶여 있어 그것만으로는 고유하지 않다.
- **기록하지 않는 값:** 접속 IP와 MCP `clientInfo`(사용자 11-02, `args`에서도 뺌).

### applog.mcp_call

MCP 호출 1건당 1행. 인증 실패(`tool=http`)와 `initialize`도 행으로 남는다. 기본 키 `(id, ts)`. 색인: `ts`(BRIN) · `(user_id, ts)` · `(tool, ts)` · `request_id`. 쓰는 곳: `mcp_server/services/call_log.py`. 읽는 코드는 없다(감사 조회용). 질의 기록 `qa_log.jsonl`은 그대로 따로 있다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | BIGSERIAL | 일련번호(PK 일부) | DB | 없음 | 새로 |
| ts | TIMESTAMPTZ NOT NULL | 호출 시각(기본 now, 파티션 키) | call_log | 없음 | 새로 |
| request_id | UUID | 요청 ID(`X-Request-Id`, 없으면 서버가 만듦) | 〃 | 없음 | 새로 |
| session_id | TEXT | `Mcp-Session-Id`. 없으면 NULL | 〃 | 없음 | 새로 |
| tool | TEXT | 도구 이름 | 〃 | 없음 | 새로 |
| agent | TEXT | `X-MCP-Client`(자기 신고 값) | 〃 | 없음 | 새로 |
| user_id | TEXT | `X-MCP-User`, 없으면 `_meta.user`(자기 신고 값, 검증 안 함) | 〃 | 없음 | 새로 |
| args | TEXT | 입력 JSON 앞부분(`search.audit.max_input_bytes`, 기본 16KB). 비밀값 가림. `content_b64`는 해시와 크기로 바꿈 | 〃 | 없음 | 새로 |
| args_bytes | INTEGER | 입력 원본 크기 | 〃 | 없음 | 새로 |
| args_truncated | BOOLEAN | 입력이 잘렸는지. 잘리면 JSON으로 안 읽힐 수 있음 | 〃 | 없음 | 새로 |
| result | TEXT | 출력 JSON 앞부분(`search.audit.max_output_bytes`, 기본 64KB). 문서 본문·EDW 결과 포함 가능 | 〃 | 없음 | 새로 |
| result_bytes | INTEGER | 출력 원본 크기 | 〃 | 없음 | 새로 |
| result_truncated | BOOLEAN | 출력이 잘렸는지 | 〃 | 없음 | 새로 |
| result_sha256 | TEXT | 출력 원본 전체의 해시 | 〃 | 없음 | 새로 |
| result_keys | JSONB | 자르지 않는 응답 식별 정보(`chunk_ids`, `row_count` 등) | 〃 | 없음 | 새로 |
| status | TEXT CHECK | ok·error·busy·timeout·unauthorized | 〃 | 없음 | 새로 |
| err | TEXT | 오류 내용(비밀값 가림) | 〃 | 없음 | 새로 |
| queue_wait_ms | INTEGER | 실행 전 대기 시간 | 〃 | 없음 | 새로 |
| duration_ms | INTEGER | 걸린 시간 | 〃 | 없음 | 새로 |
| app_version | TEXT | 앱 버전 | 〃 | 없음 | 새로 |

과부하로 감사 대기열이 차면 `args`·`result` 없는 행이 남고, 기록기 큐까지 차면 행 없이 건수로만 집계된다(호출 1건 = 1행의 예외, 사용자 11-01).

### applog.pipe_run

파이프라인 실행 1건당 1행. 기본 키 `run_id`. 색인: `started_at`. 시작할 때 `status=running`으로 쓰고 끝날 때 같은 `run_id`로 덮어쓴다(UPSERT — 이 표만). 강제 종료된 실행은 `running`으로 남는다. 쓰는 곳: `pipeline/shared/runtrace.py`. 읽는 곳: `pipeline/tools/perf.py`.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| run_id | UUID PK | 실행 ID | runtrace | perf | 새로 |
| command | TEXT | 명령 | 〃 | 〃 | 새로 |
| args | TEXT | 인자(비밀값 가림) | 〃 | 없음 | 새로 |
| started_at | TIMESTAMPTZ NOT NULL | 시작 시각(기본 now) | 〃 | perf | 새로 |
| ended_at | TIMESTAMPTZ | 끝 시각 | 〃 | 없음 | 새로 |
| duration_ms | INTEGER | 걸린 시간 | 〃 | perf | 새로 |
| status | TEXT | 실행 상태(CHECK 없음) | 〃 | 〃 | 새로 |
| host | TEXT | 서버 이름 | 〃 | 없음 | 새로 |
| pid | INTEGER | 프로세스 ID | 〃 | 없음 | 새로 |
| app_version | TEXT | 앱 버전 | 〃 | perf | 새로 |
| run_env | TEXT | 실행 환경 | 〃 | 〃 | 새로 |
| code_fp | JSONB | 레이어별 code_fp | 〃 | 〃(실행 비교) | 새로 |
| stack | TEXT | 스택 이름 | 〃 | 〃 | 새로 |
| settings_hash | TEXT | 설정 해시 | 〃 | 〃 | 새로 |
| docs_total | INTEGER | 문서 수 | 〃 | 〃 | 새로 |
| docs_ok | INTEGER | 성공 문서 수 | 〃 | 〃 | 새로 |
| docs_fail | INTEGER | 실패 문서 수 | 〃 | 〃 | 새로 |
| docs_reused | INTEGER | 재사용 문서 수(parse만 채움) | 〃 | 〃 | 새로 |
| workers | INTEGER | 작업자 수 | 〃 | 〃 | 새로 |
| cpu_max_load | FLOAT | CPU 문턱값 | 〃 | 〃 | 새로 |
| mem_start_pct | FLOAT | 메모리 문턱값 | 〃 | 없음 | 새로 |

### applog.pipe_event

문서×단계 1건당 1행. 60초마다 남는 진행 상황도 `stage=run.progress`로 들어온다. 기본 키 `(id, ts_start)`. 색인: `ts_start`(BRIN) · `run_id` · `(stage, ts_start)`. `doc_id` 색인은 없다(보통 `run_id`로 먼저 좁힌다). 쓰는 곳: `common/core/span.py`(진행 상황은 `pipeline/shared/runtrace.py`). 읽는 곳: `pipeline/tools/perf.py`.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | BIGSERIAL | 일련번호(PK 일부) | DB | 없음 | 새로 |
| ts_start | TIMESTAMPTZ NOT NULL | 시작 시각(기본 now, 파티션 키) | span | perf | 새로 |
| ts_end | TIMESTAMPTZ | 끝 시각 | 〃 | 〃 | 새로 |
| run_id | UUID | 실행 ID | 〃 | 〃 | 새로 |
| span_id | UUID | 단계 ID | 〃 | 없음 | 새로 |
| parent_id | UUID | 부모 단계 ID | 〃 | 없음 | 새로 |
| layer | TEXT | 레이어(extract·transform·load 등) | 〃 | perf | 새로 |
| stage | TEXT | 단계(`extract.parse`, `run.progress` 등) | 〃 | 〃 | 새로 |
| engine | TEXT | 엔진 | 〃 | 〃 | 새로 |
| model | TEXT | 모델 | 〃 | 없음 | 새로 |
| attempt | INTEGER | 시도 번호(1부터, 시간 초과로 다시 돌면 2 — `extract.parse`만 채움) | 〃 | 없음 | 새로 |
| doc_id | TEXT | 문서 ID | 〃 | perf | 새로 |
| ext | TEXT | 확장자 | 〃 | 없음 | 새로 |
| file_bytes | BIGINT | 파일 크기 | 〃 | 없음 | 새로 |
| seq | INTEGER | 실행 안에서 몇 번째 | 〃 | perf | 새로 |
| total | INTEGER | 전체 개수 | 〃 | 〃 | 새로 |
| duration_ms | INTEGER | 전체 시간 | 〃 | 〃 | 새로 |
| wait_mem_ms | INTEGER | 메모리 문 대기 | 〃 | 〃 | 새로 |
| wait_cpu_ms | INTEGER | CPU 문 대기 | 〃 | 〃 | 새로 |
| cpu_ms | INTEGER | CPU 시간(회수된 자식 포함). 다른 단계와 겹쳐 정확히 못 재면 NULL | 〃 | 〃 | 새로 |
| ext_call_ms | INTEGER | 외부 모델 호출 시간의 합. 병렬 호출은 더해지므로 `duration_ms`보다 클 수 있음 | 〃 | 없음 | 새로 |
| rss_peak_mb | FLOAT | 최대 메모리 | 〃 | perf | 새로 |
| load1_per_cpu_start | FLOAT | 시작 때 코어당 부하 | 〃 | 없음 | 새로 |
| load1_per_cpu_end | FLOAT | 끝날 때 코어당 부하 | 〃 | 없음 | 새로 |
| mem_used_pct | FLOAT | 메모리 사용률(`/proc` 없는 macOS는 빔) | 〃 | 없음 | 새로 |
| inflight | INTEGER | 같은 단계에서 동시에 돌던 작업 수 | 〃 | 없음 | 새로 |
| metrics | JSONB | 단계별 지표(쪽 수, 청크 수, 캐시 적중, 표별 적재 행 수 등) | 〃 | perf | 새로 |
| status | TEXT CHECK | ok·fail·timeout·skip·reused | 〃 | 〃 | 새로 |
| err_kind | TEXT CHECK | env·timeout·doc·external·db | 〃 | 〃 | 새로 |
| err | TEXT | 예외 타입과 고정 문구만. 외부 예외 원문은 저장 안 함 | 〃 | 없음 | 새로 |
| app_version | TEXT | 앱 버전 | 〃 | perf | 새로 |
