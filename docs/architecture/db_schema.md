# DB 스키마 명세 (pl-25)

이 프로젝트가 쓰는 DB 표와 칸을 한곳에 모은 문서다. 표마다 칸, 타입, 뜻, 그 칸을 쓰는 코드, 읽는 코드, 그리고 10-29~10-31 사용자 결정에 따른 0.2.0의 처리(유지·삭제·새로)를 적는다. 요건과 결정의 원문은 [prd/load-schema.md#pl-25](../prd/load-schema.md#pl-25)에 있다.

- **이 문서는 설계안이다.** 사용자와 DB 담당자가 승인한 뒤 구현한다. 이 문서를 고치는 브랜치는 코드·스키마·마이그레이션을 바꾸지 않는다.
- **결정 칸:** `유지` = 지금 있고 남김 · `삭제` = 지금 있고 없앰 · `새로` = 지금 없고 만듦. 지금 상태 = `유지`+`삭제`, 목표 상태 = `유지`+`새로`.
- **시험:** `tests/server/common/test_db_schema.py`가 이 문서의 gold 표를 Alembic 판(모델 `common/store/db/models/` — 기존 시험이 판과 같은지 본다)과, ParsingMeta를 [`docs/operations/parsing_meta_mssql.sql`](../operations/parsing_meta_mssql.sql)과 비교한다. 지금 상태가 다르면 실패하고, 목표 상태와의 차이(새로·삭제)는 목록으로 찍기만 한다.
- **쓰는 곳·읽는 곳**은 10-31 develop 기준 코드다(괄호 안은 0.2.0에 생길 곳). 경로는 저장소 기준이고 함수 이름만 적는다.

## 1. 공통 규칙 (10-30·10-31 결정 — 0.2.0)

| 규칙 | 내용 |
|---|---|
| 문서 키 | 원본 경로 하나 — gold `doc.file_path` = Object Storage 원본 경로 = EDW `FileStorageMap.s3_key` = ParsingMeta 원본 키(사용자 11-02 — 개발 서버 로컬 경로·`doc.s3_key` 칸은 두지 않음). sha256 `doc_key`는 gold에 두지 않는다(ParsingMeta `sha256`만 — 원문 도구 `doc_key`). 문서 대장·숨김은 지웠다(pl-12 C10). 같은 내용이 여러 원본 경로로 들어오면 문서도 여러 개다(U-7, `doc_alias` 없음). |
| 출처 표시 이름 | EDW에서도, 문서 파싱에서도 나올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — EDW `_edw`, 문서 본문 `_doc`. 지금 해당하는 값: 고객(`client_edw`·`clients_doc`). |
| 고객 거르기 | MCP의 고객 거르기는 EDW 고객(`doc.client_edw`, 문서당 하나)만 쓴다(C6). EDW 고객이 없는 문서(LAS 등)는 고객 거르기를 걸면 빠진다. 본문에서 찾은 고객(`clients_doc`)은 참고용. |
| 원천 | `source_system` = `AI.FileStorageMap.source_system`(SFDC·CRMS·LAS·FAQ — `-test` 붙어도 같음). 비었거나 그 밖의 값이면 `Other`. 원본 경로 첫 마디(`SFDC/…`)로도 정함(build_bundle). |
| 원천별 gold 스키마 | 원천 시스템마다 PG 스키마 하나 `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`(판 0002 — [pl-28](../prd/load-schema.md#pl-28), 11-02 구현). 스키마마다 같은 표 `doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat`(BM25 통계도 원천별) + 뷰. 기준 스키마 `<PG_SCHEMA>`에는 판 표와 공용 `doc_id_seq`만. 원천 전용 칸은 §2 표의 "원천" 칸. MCP `search`는 `source_system`을 필수·값 하나로 받아 그 스키마만 찾는다(G20 — 운영과 다름, 등급 A). |
| 파일 메타는 `doc`에만 | 고객·`sf_*`·`doc_class`·`created_at`·`contract_id` 같은 파일 메타는 시스템별 `doc`에만 둔다. `chunk`는 문서 키만 갖고 메타를 복사하지 않는다(예외 `faq.chunk.faq_group`). 거르기는 `doc`에서 문서 범위를 고른 뒤 그 안의 `chunk`만 찾는다([pl-28](../prd/load-schema.md#pl-28)). |
| ParsingMeta = 파싱 정보만 | EDW `AI.ParsingMeta`에는 원천 키·파싱 상태·silver 위치·단계별 칸만 쓴다(G19). 예외: 같은 내용 묶기용 원본 지문 `sha256`은 남긴다(C5). 파일 메타는 쓰지 않는다. 파싱이 통째로 실패한 문서는 행을 쓰지 않는다(C3 — 다음 실행에서 다시 후보). |
| 판 표기 | ParsingMeta `pipeline_version` = 이 문서를 gold에 올린 판(다시 올릴지 판단, C9). gold에는 판 칸을 두지 않는다(사용자 11-02 — 파싱 이력은 EDW에만). |
| 근거 주소 `rep_uri` | (11-01 사용자 — C8 바뀜) pgvector에는 거르기 메타만 둔다. 대표 결과 위치(`rep_bucket`·`rep_key`)·파싱 시각(`parsed_at`)·원본 sha256은 ParsingMeta에만 두고, 원문 도구(`list_doc_fulltext`·`get_doc_fulltext` 등록 시각 가드)가 부를 때 `source_system` + `source_key`(= gold `doc.s3_key`)로 읽는다 — EDW를 못 읽으면 `registry_unavailable`. `search` 근거에는 `rep_uri`가 없다(운영 12칸). 적재 때 복사하던 길(mc-15 첫 구현)은 지웠다. |
| 가장 늦은 행 | 같은 `s3_key`가 `AI.FileStorageMap`에 여러 행이면 `created_at`이 가장 큰 행을 기준으로 삼는다(A4). 나중에 같은 `s3_key`의 더 새 행이 오면 **같은 `doc_id`를 유지한다** — `file_size`가 같으면 다시 파싱하지 않고 저장된 기준·메타만 새 행으로 고치며, `file_size`가 조금이라도 다르면 같은 `doc_id`로 다시 파싱·다시 적재한다(원본을 내려받는 sha256 비교는 하지 않음 — 사용자 10-31). 밀려난 행은 EDW 예외 이력 표(§3 `edw.SupersededRow`, 새로 — D-9)에 남긴다(사용자 10-31 grill, A4 고침). |
| 근거 키 | MCP 근거의 `chunk_key`는 `<doc_id>:<seq>`(11-02 구현) — `doc_id`는 5벌이 함께 쓰는 시퀀스라 스키마끼리 겹치지 않는다. 청크는 `doc_id`만 갖는다(FK). 적재는 `file_path`로 건너뛰기(`--replace`면 지우고 다시 넣어 새 `doc_id`). `make_chunk_key`·sha256 `doc_key`는 검색에서 쓰지 않는다. |
| 원본 주소 | `source_uri`·근거 `file_name`은 gold `doc.file_path`(원본 경로)에서 만든다(`file_name` = 끝 조각 — 원본 파일 이름, 실제 EDW에서 확인은 C-76). 대표 결과 주소 `rep_uri`는 ParsingMeta에서(위 줄). |
| 원천별 EDW 사슬(pl-29, 사용자 11-02 — 적재 때, 읽기 계정) | **SFDC:** `FileStorageMap.content_version_id → ContentVersion.Id`(→ `ContentDocumentId`, 등록 시각 `CreatedDate`) `→ ContentDocumentLink.ContentDocumentId`(`IsDeleted=0`)`.LinkedEntityId` 접두로 영업 기회 — `006` 직접 > `00T` `Task.WhatId` > `00U` `Event.WhatId` > `0Q0` `Quote.OpportunityId`(§3 `edw.Quote` — 표가 없으면 그 단계만 건너뜀) · 고객 `Opportunity.AccountId → Account.Name`, 기회가 없으면 `Task`/`Event.WhatId` `001` > `LinkedEntityId` `001` · 같은 단계 후보 둘 이상이면 비움. 칸: `sf_op_name`=`Opportunity.Name`, `project_code__c`=`Project_Code__c`, `service_type`=`Record_Type__c`, `contract_date`=`X1st_Contract_Execution_Date__c`. **CRMS:** `FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST.RM_CONTRACT_CODE` — `client_edw`=`SF_ACC_NAME`, `division`=`DIVISION`, `prod_name`=`RM_CONTRACT_NAME`, `contract_date`=`INIT_DTTM`, `contract_id`=`rm_contract_code` · 등록 시각 `RM_CM_DOCU.INIT_DTTM`(키 4개 `rm_contract_code`·`gate_code`·`gate_version`·`docu_seq`). **LAS:** `FileStorageMap_LAS.manage_no → LAS.Contract.ManageNo`(최신 판 — `IsActive`·`ContractID` 내림차순) — `contract_id`=`manage_no`(없으면 `ContractID`), `contract_date`=`ContractDate`(없으면 `signed_date`), `client_edw`=`PartnerCorpName`(지금 모두 비어 있음 — G2) · 등록 시각 `FileStorageMap_LAS.las_file_id → LAS.FileManager.CreateDate`. **FAQ·Other:** `FileStorageMap.created_at`만. EDW를 못 읽으면 메타를 비운 채 적재(경고·실행 기록 `meta_missing`) — 자동 갱신 없음, 나중에 `--replace`로 다시 적재해 채움(C-76). 칸 이름은 운영 gold 스키마 노트 기준(D-1 — DB 담당자 확인). |
| 원천 id 칸 | 원천 전용 칸은 §2 `gold.doc` 표의 "원천" 칸대로(sfdc: `sf_op_id`·`sf_op_name`·`project_code__c`·`service_type` · crms: `division`·`prod_name` · crms·las: `contract_id` · sfdc·crms·las: `contract_date` · sfdc·las: `doc_class`). 값은 적재 때 EDW 조인으로(아래 원천별 사슬 — pl-29). |

## 2. gold — 검색 스키마 (pgvector — 원천별 스키마 5벌, 판 0002)

판: `common/store/db/migrations/versions/0001_search_base.py`(옛 한 벌) + `0002_search_doc_meta.py`(11-02 — 원천별 5벌로 나누고 옛 한 벌 표·`load_run`을 지움) · 모델: `common/store/db/models/search_tables.py`(`SOURCES`·`DOC_EXTRA`·`CHUNK_EXTRA`) · 적재: `pipeline/load/pgvector_load.py`(`load`·`_load_src`, `deploy`) · 값 만드는 곳: `pipeline/transform/structure/build_bundle.py`(`main`)·EDW 조인(`pipeline/load/edw_meta.py` — pl-29).

- **스키마 배치:** 기준 스키마 `<PG_SCHEMA>`(예 `ai`)에는 Alembic 판 표 `alembic_version`과 공용 doc_id 시퀀스 `doc_id_seq`만 둔다. 원천마다 스키마 `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`에 아래 표 다섯 개와 뷰 `v_chunk_source`가 같은 꼴로 있다(원천 전용 칸만 다름 — 표의 "원천" 칸). 원천은 문서의 `source_system`(SFDC·CRMS·LAS·FAQ, `-test` 붙어도 같음 — 그 밖은 `other`)으로 고른다.
- **적재 규칙(11-02 — [pl-13](../prd/load.md#pl-13)):** 원본 경로(`file_path`)는 5벌을 통틀어 하나다 — 적재는 5벌 모두에서 찾아, `--replace` 없이 이미 있으면 건너뛰고, `--replace`면 다른 원천 스키마의 옛 사본을 지운 뒤 새 원천 스키마에 넣는다(원천이 바뀐 문서).
- **지운 것(11-02):** `load_run` 표(실행 정보는 실행 기록에, 적재 시각은 ParsingMeta `loaded_at`) · `doc.clients`(본문 고객 — `clients_doc`으로 이름 바꿈)·`doc.run_id`·`doc.source_system`(스키마가 원천)·`doc.s3_key`(`file_path`가 원본 경로)·`doc.sf_acc_name`(`client_edw`와 같은 값) · `chunk.char_start`·`char_end`·`n_chars`·`embed_model`·`clients`·`source_system` · 색인 `ix_<스키마>_chunk_clients`.

### gold.doc

| 칸 | 타입 | 뜻 | 원천 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| doc_id | INT PK | 문서 행 번호 — 기본값 `nextval('<PG_SCHEMA>.doc_id_seq')`(5벌이 시퀀스 하나라 겹치지 않음). MCP `chunk_key` `<doc_id>:<seq>`의 앞부분 | 모두 | pgvector_load `_load_src` | 뷰, 원문 도구 쪽 넘김(`cursor`) | 유지 |
| file_path | TEXT NOT NULL | Object Storage 원본 경로 = EDW `FileStorageMap.s3_key` = ParsingMeta 원본 키 — ParsingMeta와 잇는 키(사용자 11-02). PC 폴더 원천은 원천 폴더 기준 상대 경로(같은 꼴). 적재 건너뛰기 키 | 모두 | build_bundle `main` → 적재 | 뷰(`file_name` = 끝 조각), search_svc 범위, 원문 도구 | 유지 |
| summary | TEXT | 문서 요약 | 모두 | build_bundle | 뷰 → 근거 | 유지 |
| created_at | TIMESTAMPTZ | 원천 등록 시각(KST) — SFDC `ContentVersion.CreatedDate` 계열 · CRMS `RM_CM_DOCU.INIT_DTTM` · LAS `FileManager.CreateDate` · 그 밖 `FileStorageMap.created_at`(§1 원천별 사슬) | 모두 | 적재(EDW 조인 — pl-29) | `search` `created_since/until`, 원문 도구 거르기·출력·등록 시각 가드 | 유지 |
| client_edw | TEXT | EDW 조인 사슬의 고객 하나 — MCP 고객 거르기는 이 칸 정확 일치만(C6) | 모두(채워지는 곳: sfdc·crms) | 적재(EDW 조인) | search_svc 범위, 근거 `client` | 유지 |
| clients_doc | TEXT | 본문에서 찾은 고객 라벨(JSON 글자) — 참고만, 거르기·순위에 안 씀 | 모두 | build_bundle `infer_clients` → 적재 | 없음(참고) | 유지 |
| doc_class | TEXT | 문서 분류 라벨 하나(SFDC: RFI/RFP/RFI+RFP/Proposal/Other, LAS: MSA/PSA/QAG/LOI/Amendment/Assignment Letter/Other) — [pl-33](../prd/transform.md#pl-33) | sfdc·las | (분류 단계 → 적재) | `search`·`list_doc_fulltext` 거르기 | 유지 |
| sf_op_id | TEXT | 영업 기회 id(18자 `006…`) — 파일 → 영업 기회 사슬로 고른 것 | sfdc | 적재(EDW 조인) | `search`·`list_doc_fulltext` 거르기 | 유지 |
| sf_op_name | TEXT | 영업 기회 이름(`Opportunity.Name`) | sfdc | 적재(EDW 조인) | `search` 거르기 | 유지 |
| project_code__c | TEXT | 프로젝트 코드(`Opportunity.Project_Code__c`) | sfdc | 적재(EDW 조인) | `search` `project_id` | 유지 |
| service_type | TEXT | 서비스 유형(`Opportunity.Record_Type__c`) | sfdc | 적재(EDW 조인) | `search` 거르기 | 유지 |
| division | TEXT | 사업부(`RM_CM_PJTLIST.DIVISION`) | crms | 적재(EDW 조인) | `search` 거르기 | 유지 |
| prod_name | TEXT | 제품·계약 이름(`RM_CM_PJTLIST.RM_CONTRACT_NAME`) | crms | 적재(EDW 조인) | 없음(근거 메타) | 유지 |
| contract_id | TEXT | 계약 번호 — CRMS `rm_contract_code` · LAS `manage_no`(없으면 `Contract.ContractID`) | crms·las | 적재(EDW 조인) | `search` 거르기 | 유지 |
| contract_date | DATE | 계약일 — SFDC `Opportunity.X1st_Contract_Execution_Date__c` · CRMS `RM_CM_PJTLIST.INIT_DTTM` · LAS `Contract.ContractDate`(없으면 `FileStorageMap_LAS.signed_date`) | sfdc·crms·las | 적재(EDW 조인) | 없음(근거 메타) | 유지 |

### gold.chunk

| 칸 | 타입 | 뜻 | 원천 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| chunk_id | SERIAL PK | 청크 행 번호(스키마마다) | 모두 | pgvector_load | pgsearch(후보·BM25·뷰) | 유지 |
| doc_id | INT FK→doc | 문서 — 청크가 갖는 문서 키는 이것뿐 | 모두 | pgvector_load | 조인 전부 | 유지 |
| seq | INT NOT NULL | 문서 안 순번 — `chunk_key` 뒷부분 | 모두 | pgvector_load | 뷰 → 근거 | 유지 |
| page | INT | 쪽 | 모두 | pgvector_load | 뷰 → 근거 `page` | 유지 |
| line_start | INT | 시작 줄 | 모두 | pgvector_load | 뷰 → 근거 `line` | 유지 |
| line_end | INT | 끝 줄 | 모두 | pgvector_load | 뷰 → 근거 `line` | 유지 |
| bbox | VARCHAR(80) | 쪽 안 위치 x0,y0,x1,y1(pt) 하나 | 모두 | pgvector_load | 뷰 | 유지 |
| section | TEXT | 절 제목 | 모두 | pgvector_load | 뷰 → 근거 `section` | 유지 |
| chunk_text | TEXT NOT NULL | 청크 본문 | 모두 | pgvector_load | 뷰 → 근거 `text` | 유지 |
| n_terms | INT NOT NULL | 토큰 수 — BM25 길이 정규화(dl) | 모두 | pgvector_load | pgsearch BM25, `corpus_stat` | 유지 |
| embedding | vector(n) | L2 정규화 임베딩(HNSW 코사인 · 2,000차원 넘으면 이진 양자화 HNSW) | 모두 | pgvector_load | pgsearch `vector_top` | 유지 |
| faq_group | TEXT | FAQ 시트 이름(`FAQ_group`) — C4 | faq | (FAQ 적재 — [pl-39](../prd/extract.md#pl-39)) | `search` `FAQ_group` 거르기 | 유지 |

### gold.chunk_term

왜 필요한가: `mcp_server/services/search/pgsearch.py` `search`의 BM25가 질의마다 청크별 단어 빈도(tf)를 이 표에서 읽는다(드문 ID 검색의 문서 수 셈도 이 표). 원천 스키마마다 하나.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT | 토큰(PK 일부) | pgvector_load(COPY) | pgsearch BM25·ID | 유지 |
| chunk_id | INT | 청크(PK 일부) | pgvector_load | pgsearch | 유지 |
| tf | SMALLINT | 그 청크 안 단어 빈도 | pgvector_load | pgsearch BM25 | 유지 |

### gold.term_stat

왜 필요한가: `pgsearch.py` BM25의 IDF — 단어마다 그 단어가 든 청크 수(df)를 질의 때 다시 세지 않게 둔다. 원천 스키마마다 하나(원천끼리 점수를 섞지 않음 — G20).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT PK | 토큰 | pgvector_load | pgsearch BM25 | 유지 |
| df | INT | 문서(청크) 빈도 | pgvector_load(늘리기)·`drop_terms`(줄이기) | pgsearch BM25 | 유지 |

### gold.corpus_stat

왜 필요한가: `pgsearch.py` BM25의 전체 청크 수(N)와 평균 길이(avgdl) — 한 행. 차원(dim)은 대역·확인용.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | SMALLINT PK | 늘 1 | pgvector_load | pgsearch | 유지 |
| n_chunks | INT | 청크 수 N | pgvector_load | pgsearch BM25 | 유지 |
| avg_len | DOUBLE | 평균 n_terms(avgdl) | pgvector_load | pgsearch BM25 | 유지 |
| dim | INT | 임베딩 차원 | pgvector_load | pg_standin(대역 차원) | 유지 |

뷰 `v_chunk_source`는 `chunk`↔`doc`을 이은 읽기 전용 뷰다(원천 스키마마다 — 칸 = 청크 칸 + `file_name`(= `file_path` 끝 조각) + 그 원천의 doc 칸 + (faq) `faq_group`). 판 0002가 만들고, 모델 `views_expected(원천)`이 비교 기준이다.

## 3. EDW (MSSQL)

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

PC 대역 예시 — [pl-29](../prd/extract.md#pl-29) 10-31. 고객 연결 4단계의 마지막(Quote)을 PC에서 구현·시험하려고 PC 대역 EDW(`valid_env/edw`)에 SFDC Quote 표를 **예시 칸**으로 새로 만든다(A3). 서버 레플리카에는 Quote 표가 없다 — Quote는 `OpportunityId`로 파일과 이어진다고 가정한다(사용자 10-31 grill). 실제 표·칸 이름은 DB 담당자 답(D-1)으로 맞춘다. 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| Id | (예시) | Quote id | (PC 대역 시드) | (고객 연결 4단계) | 새로 |
| OpportunityId | (예시) | 연결된 영업 기회 | 〃 | 〃 | 새로 |
| AccountId | (예시) | 연결된 고객 계정 — 고객 이름은 `SFDC.Account` | 〃 | 〃 | 새로 |

### edw.ParsingMeta

`AI.ParsingMeta` — 파싱 결과(silver) 게시 기록. 정의: `docs/operations/parsing_meta_mssql.sql`. 쓰는 곳: `pipeline/load/parsing_meta.py`(`plan`·`apply` — 행 만들기, `apply_registry_status` — 상태 UPDATE), `common/store/parsing_meta_db.py`(`insert_new`, `update_status`). 0.2.0 결정: **파싱 정보만** 둔다(G19) — 연결 키(`source_system` + `source_key` = 원본 전체 경로, `s3_key` 칸 없음)·파싱 상태·silver 위치(`rep_bucket`·`rep_key`)·`engines_used`·`engines_failed`·`parsed_at`·`pipeline_version`·`gold_status`·`gold_reason`, 예외로 원본 지문 `sha256`(C5). `rep_engine`·`stack_version`은 두지 않는다(사용자 11-01). 파일 메타(`doc_class`·`sf_op_id`·`created_at`·고객)는 쓰지 않고 시스템별 gold `doc`에만 둔다. 파싱이 통째로 실패하면 행을 쓰지 않는다(C3). `gold_status`·`gold_reason`을 더한다([pl-24](../prd/ops.md#pl-24)).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| parse_meta_id | BIGINT IDENTITY PK | 행 번호 | DB | 없음(기본 키) | 유지 |
| source_system | NVARCHAR(64) | 원천 | parsing_meta `plan` | parsing_meta_db 겹침 확인·`rows_where`(원문 도구 — 11-01 mc-17), 상태 UPDATE 조건 | 유지 |
| source_key | NVARCHAR(1024) | 원본 전체 경로 = `AI.FileStorageMap.s3_key` 값 = gold `doc.file_path`. 원본과의 연결 키는 `source_system` + 이 칸. 이름을 `s3_key`로 바꾼다(아래 `s3_key` 줄 — DB 담당자 DDL, C-76) | parsing_meta `plan` | 〃, run_docs `edw_done_keys`, mcp `fulltext` | 유지 |
| s3_key | NVARCHAR(1024) | (사용자 11-02) 위 `source_key`의 새 이름 — DB 담당자가 이름을 바꾸면 계산 칸 `source_key_hash`·유일 색인 `UQ_ParsingMeta_key`도 다시 만든다(C-76). 코드는 연결할 때 `s3_key`가 있으면 그것, 없으면 `source_key`를 쓴다(`parsing_meta_db` `key_col`·run_docs) | (DDL 뒤 같은 곳) | (같은 곳) | 새로 |
| source_uri | NVARCHAR(2048) | 원본 주소 | 〃 | 없음 | 삭제 |
| original_filename | NVARCHAR(512) | 원본 파일 이름 | 〃 | 없음 | 삭제 |
| file_format | NVARCHAR(32) | 형식 | 〃 | 없음 | 삭제 |
| file_size | BIGINT | 크기 | 〃 | 없음 | 삭제 |
| sha256 | NVARCHAR(64) | 원본 sha256 — 원문 도구 `doc_key`(입력·출력) · 같은 내용 묶기에 씀(C5 — G19 "파싱 정보만"의 예외, 파싱한 원본의 지문) | parsing_meta `plan` | mcp `fulltext`(`list_doc_fulltext` `doc_key` 입력·출력 — 11-01 mc-17) · (분류 단계 같은 내용 묶음 — [pl-33](../prd/transform.md#pl-33)) | 유지 |
| rep_bucket | NVARCHAR(256) | 대표 결과 버킷 | parsing_meta `plan` | mcp `fulltext`(`parsing_meta_db.rows_where`·`pick_rep` — 원문 도구가 부를 때 읽음, 11-01 mc-17) | 유지 |
| rep_key | NVARCHAR(2048) | 대표 결과 폴더 | parsing_meta `apply` | 〃(목록 `rep_uri`·sfid 발급, 등록 시각 가드의 폴더 → 원본 찾기) | 유지 |
| rep_etag | NVARCHAR(128) | 대표 결과 etag | 〃 | 없음 | 삭제 |
| parse_status | NVARCHAR(32) | ok·partial | parsing_meta `plan` | run_docs `edw_done_keys` | 유지 |
| status_reason | NVARCHAR(2000) | 상태 이유 | 〃 | 없음 | 삭제 |
| rep_engine | NVARCHAR(128) | 대표 엔진 — 0.2.0에 지움(gold `doc.rep_engine`도 두지 않음 — 사용자 11-01) | parsing_meta `plan` | 없음 | 삭제 |
| rep_acc | FLOAT | 대표 정확도 | 〃 | 없음 | 삭제 |
| page_count | INT | 쪽 수 | 〃 | 없음 | 삭제 |
| doc_key | NVARCHAR(64) | 원본 sha256(지금 유일한 필수 칸 — 검색 키와 안 맞아 `rep_uri`가 늘 빔, mc-15) | 〃 | 없음(11-01 `find_by_doc_key` 지움 — mc-15) | 삭제 |
| parse_date | NVARCHAR(32) | 파싱 시각 글자(`YYYY-MM-DD_HHMMSS`) | parsing_meta `apply` | find·상태 UPDATE 조건 | 유지 |
| pipeline_version | NVARCHAR(64) | 이 문서를 gold에 올린 판 — 다시 올릴지 판단. 지금은 파싱 때 쓰는 파이프라인 판이었으나 0.2.0에는 gold 성공 때 쓰고 gold가 끝나기 전에는 NULL(C9 — gold `doc.pipeline_version`은 행을 만든 코드 판, 이름 같고 뜻 다름 — 사용자 10-31 grill: `gold_version` 새 칸 대신 이 칸 이름을 씀) | parsing_meta `plan` → (gold 성공 때) | (운영자·재처리 판정) | 유지 |
| status | NVARCHAR(16) | active·changed·deleted | 〃, `apply_registry_status` | `pick_rep`(active 중 최신 — 원문 도구가 부를 때, 11-01 mc-17)·상태 UPDATE 조건 | 유지 |
| status_at | NVARCHAR(32) | 상태 바뀐 때(UTC) | `apply_registry_status` | 없음(SELECT 안 함 — 운영자가 봄) | 유지 |
| engines_used | NVARCHAR(MAX) | 쓰인 엔진 전부(JSON) — 0.2.0: 성공한 엔진만(이름 + 판, 사용자 10-30 grill) | parsing_meta `plan` | 없음 | 유지 |
| engines_summary | NVARCHAR(512) | 엔진 한 줄 요약 | 〃 | 없음 | 삭제 |
| parsed_at | DATETIME2(0) | 넣은 때(기본 SYSUTCDATETIME — UTC) — 파싱 정보라 남김(G19) | DB 기본값 | mcp `fulltext`(`list_doc_fulltext` `since`/`until` — 11-01 mc-17) | 유지 |
| source_key_hash | BINARY(32) 계산 칸 | `source_key` sha256 — 유일 색인 키(1700바이트 상한 우회) | DB | 유일 색인 | 유지 |
| gold_status | NVARCHAR(32) | gold(검색 DB) 적재 상태 | (pl-24 — run_docs·적재) | (pl-24 재시도·건너뜀) | 새로 |
| gold_reason | NVARCHAR(2000) | gold 상태 이유(실패 원인 등) | (pl-24) | (운영자) | 새로 |
| engines_failed | NVARCHAR(MAX) | 실패한 엔진(JSON — 이름·이유·걸린 시간), 없으면 NULL | (파싱 단계 — 사용자 10-30 "EDW에도") | (운영자·재시도 판단) | 새로 |
| loaded_at | DATETIME2(0) | (사용자 11-02 — C10 예외) gold에 적재한 시각(UTC) — 적재가 PG 커밋 뒤 쓸 행(active 중 최신)에 UPDATE. 칸이 없거나 쓰기 계정이 없으면 경고와 건수만(적재는 그대로) | pgvector_load `_mark_loaded` → parsing_meta_db `mark_loaded`·`set_loaded` | (운영자 — 적재 확인) | 새로 |

**운영이 더한 분류·고객 칸(G19 — 4차 grill, G1·G9를 뒤집음):** 운영이 ParsingMeta에 더한 분류·고객 칸(`doc_class`·`sf_op_id`·`created_at`·`sf_acc_name` 등 — 이 저장소의 DDL에는 없음)은 0.2.0에 모두 지운다(DB 담당자 D-3, 등급 A). 분류·고객·등록 시각은 시스템별 gold `doc`에만 둔다([pl-33](../prd/transform.md#pl-33), [pl-29](../prd/extract.md#pl-29)). 그때 운영 분류 스크립트가 멈추므로 운영 담당자에게 알린다.

**단계별 기록(사용자 10-30 grill — 등급 A, DB 담당자 D-3):** 단계마다 성공했을 때만 쓴다(파싱이 통째로 실패하면 행 없음 — C3) — 파싱: 성공한 엔진(`engines_used`)·실패한 엔진(`engines_failed`)·`parsed_at` · gold: `pipeline_version`·`gold_status`. `stack_version`·`rep_engine`은 두지 않는다(사용자 11-01). 3차의 "읽는 칸만" 안에 칸을 다시 더한 것이다. 저장 구조(silver = Object Storage uuid5 폴더 · gold = pgvector)는 [pl-32](../prd/load.md#pl-32).

## 4. master — CSV 파일 (`resources/vocab/glossary/`, 사용자 10-30)

마스터 성격 자료(용어집, 고객 명부, `contract_master`, `client_master`)는 **DB가 아니라 CSV 파일**이다. 별도 마스터 PostgreSQL도, 용어집용 SQLite 대역도 없다(10-30 grill 9~10차의 "마스터 PG + PC SQLite 대역" 결정을 뒤집음). CSV(샘플 데이터)는 git의 `resources/vocab/glossary/`(지금 폴더)에 두어 이미지에 함께 들어간다 — 서버 폴더·마운트 없음, `glossary_dir`는 이미지 경로. 샘플 CSV 넷이 들어 있다(10-30 — `client_roster.example.csv`·`domain_terms.example.csv`를 대신함, 한빛 샘플 문서의 고객·제품 포함). git의 CSV는 샘플 데이터(사용자 10-30) — server-guide §5 기밀 규칙과 충돌 없음.

| 파일 | 무엇 | 머리글 | 읽는 곳 |
|---|---|---|---|
| `domain_terms.csv` | 용어 사전(C-21) | `concept_id,canonical,category,synonyms,abbreviations,weak_synonyms,broader,related,context_required,case_sensitive,definition_ko,definition_en,source,owner,status,updated` (`status`는 approved·draft) | `common.core.terms` |
| `client_roster.csv` | 고객 명부(C-21, 새 형식) | `client_id,canonical_name,name_ko,aliases,client_type,segment,country,parent_client_id,status,description,source,updated` — 읽는 칸: `canonical_name`(비면 `name_ko`), `aliases`(`;`·`\|` 구분), `status`(inactive·deleted면 건너뜀) | `common.core.terms` 고객 별칭(초안은 `gen_roster`) |
| `contract_master.csv` | 계약 마스터 | `contract_id,company,company_id,product_code,modality,site,line_id,batches_contracted,contract_value_usd,currency,term_months,signed_on,start_date,end_date,status` (옛 `struct.contract_master`와 같은 칸) | 계약 연결·고객 별칭 |
| `client_master.csv` | 고객 마스터 | `company_id,company,aliases`(별칭 `\|` 구분) | 고객 별칭 |

- `client_master.example.csv`(머리글 `Account_Id,Account_Name,Account_Name_KR,Alias_List,Account_Type,Billing_Country,Parent_Id,Account_Status`)는 EDW 모양 원본 — `gen_roster --kind client --source csv:client_master.csv --mapping …`이 명부 초안을 만들 때 읽는다.
- 같이 있는 `id_patterns.csv`·`units.csv`·`client_roster_seed.json`·`client_master_map.example.json`은 그대로.

## 5. DB 담당자 확인 필요

| # | 무엇 | 왜 |
|---|---|---|
| D-1 | `AI.FileStorageMap`의 실제 정의 — 특히 고친 때 칸 이름(`last_modified_time` 가정)과 `source_system` 값 목록 | 저장소에는 PC 대역(`valid_env/edw/ai.sql` — `created_at`만)뿐 · **G9(사용자 10-30) 확인:** 지금 운영 `ParsingMeta.created_at`은 원천별 표에서 온다(SFDC `ContentVersion_dump.CreatedDate`, CRMS `RM_CM_DOCU.INIT_DTTM`, LAS `FileManager.CreateDate`) — `FileStorageMap.created_at`이 같은 값을 갖는지 · **0.2.0(A4·A3):** `FileStorageMap.created_at`이 실제로 있는지(같은 `s3_key` 중 가장 늦은 행을 이 칸으로 고름) · SFDC Quote 표의 실제 이름·칸(PC 대역은 예시 칸 — §3 `edw.Quote`) · **사용자 10-31 grill:** 원천 id 칸(영업 기회 id 등)의 원천별 실제 칸 이름 · Quote가 `OpportunityId`로 파일과 이어지는지 |
| D-2 | 문서당 EDW 고객 하나(`client_edw`)를 얻는 조인 경로 — 원천별(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account.Name`로 보임, CRMS·LAS는?) | 지금은 외부에서 뽑은 `file_meta_new.jsonl`을 읽고, 그 파일을 만드는 코드가 저장소에 없음 → **결정(사용자 10-30):** 파이프라인이 EDW 읽기 계정으로 조인을 직접 만든다(SFDC: `FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`) — `file_meta_new.jsonl`을 대신함, [pl-29](../prd/extract.md#pl-29). CRMS·LAS 경로는 여전히 확인 필요 · **2차 grill(사용자 10-30, G2):** CRMS는 `FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST`로 채움(DB 담당자 확인) · LAS는 상대사 출처가 정해질 때까지 비움 |
| D-3 | `AI.ParsingMeta` 칸 정리(ALTER) — 안 읽는 칸 삭제, `gold_status`·`gold_reason`·단계별 칸 `engines_failed` 추가, `rep_engine` 삭제(`stack_version`은 만들지 않음 — 사용자 11-01), `pipeline_version` 뜻 바꿈(gold에 올린 판 — gold 성공 때 씀, 10-31: 새 칸 `gold_version` 대신), `engines_used` 뜻 바꿈(성공한 엔진만) — 권한, 기존 행, 다른 사용처 | 이 프로젝트 밖에서 그 칸을 읽는 곳이 있는지 모름 · **G19·C5(0.2.0):** 파싱 정보만 — 운영이 더한 분류·고객 칸(`doc_class`·`sf_op_id`·`created_at`·`sf_acc_name` 등)은 모두 지움, `sha256`은 남김 · 운영 분류 스크립트가 멈춤 |
| D-4 | `ParsingMeta.doc_key` 삭제 때 `UQ_ParsingMeta_dockey`·`IX_ParsingMeta_doc_key` 색인 처리 · `source_key`를 필수(NOT NULL)로 | 지금 `source_key`가 비면 `doc_key`가 겹침 키 |
| D-5 | (없어짐 — 사용자 10-30: 마스터는 CSV 파일, 마스터 PostgreSQL 없음) | — |
| D-6 | 판 0002(11-02 구현) — 원천별 gold 스키마 5벌(`<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`) + 기준 스키마의 공용 `doc_id_seq`, 옛 한 벌 표·`load_run` 삭제(§2) — 기존 서버 데이터는 다시 적재(백업 뒤) | DB 담당자 승인 한 번([pl-25](../prd/load-schema.md#pl-25)·[pl-28](../prd/load-schema.md#pl-28)) · 첫 적재가 전체 e2e([pl-23](../prd/ops.md#pl-23))와 함께 · refactor.md C-74·C-76 |
| D-8 | FAQ 원천 등록 — Object Storage `FAQ/<uuid>/<파일>`을 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록(G3, 사용자 10-30 — [pl-39](../prd/extract.md#pl-39)) | EDW 담당자 협의 필요 — FAQ 행을 누가 어떻게 넣나 |
| D-9 | 밀려난 `FileStorageMap` 행의 예외 이력 표(새 EDW 표 — §3 `edw.SupersededRow` 안) — 표 이름·칸·누가 쓰나 | 사용자 10-31: 같은 `s3_key`의 더 새 행이 오면 같은 `doc_id`(`file_size`가 다를 때만 다시 파싱)이고 옛 행을 이력에 남김 |

## 6. 사용자 결정 (10-30 grill 7차)

U-1~U-6은 이 문서의 안대로, U-7은 아래 결정대로 한다.

| # | 무엇 | 결정 |
|---|---|---|
| U-1 | `chunk.clients[]`(지금 고객 거르기 키, GIN) — 10-30 결정 "청크는 `clients[]` 유지"와 "거르기는 EDW 고객만"이 겹침 | `chunk.clients` 삭제 → `chunk.client_edw` 새로(거르기 키) → **10-30 4차 grill(pl-28)로 바뀜:** 청크에는 고객 칸을 두지 않고 `doc.client_edw`로 문서 범위를 고른다 |
| U-3 | `doc_contract_link` — pl-25에 "s3_key로 다시 키"와 "문서 파생 표 삭제"가 함께 있음 | 삭제 |
| U-4 | 마스터 읽는 곳 — pl-25는 `gen_roster`·`terms.py`라 했지만 DB를 읽는 곳은 없다(`gen_roster`는 CSV·EDW 표, `terms.py`는 안 읽음) | 남는 읽는 곳은 고객 별칭뿐 — CSV(`resources/vocab/glossary/`)에서 읽음(10-30 바뀜: 마스터 PG 없음) |
| U-5 | 출처 표시 이름을 붙일 값 — 지금은 고객만. 계약 id(`contract_id`)·제품 이름은 EDW에서만 옴 | 고객만 `_edw`·`_doc`로 나눔, 나머지는 그대로 |
| U-6 | `ParsingMeta.status_at`은 SELECT하는 코드가 없음(운영자가 봄) · `parse_meta_id`·`source_key_hash`는 DB 키 | 셋 다 유지 |
| U-7 | 같은 내용이 여러 `s3_key`로 들어온 문서 — 지금은 첫 키만 `doc` 행, 나머지는 `aliases`(묶음 안). 키가 하나뿐인 설계라 둘째 키는 숨김·ParsingMeta 조회가 안 맞음 | `s3_key`마다 `doc` 행 하나 — `doc_alias` 없음. `build_bundle`의 내용 해시 합치기(첫 키로 `aliases`)를 없앰 — 같은 내용이 두 키면 문서 둘(임베딩은 캐시가 다시 씀) |
