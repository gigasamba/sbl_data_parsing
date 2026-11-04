# DB 스키마 명세 (pl-25)

이 프로젝트가 쓰는 DB 표와 칸 — 표마다 칸, 타입, 뜻, 쓰는 코드, 읽는 코드, 결정. 요건은 [prd/load-schema.md#pl-25](../prd/load-schema.md#pl-25).

- **결정 칸:** `유지` = 지금 있고 남김 · `삭제` = 지금 있고 없앰 · `새로` = 지금 없고 만듦. 지금 상태 = `유지`+`삭제`, 목표 상태 = `유지`+`새로`. EDW 쪽 `새로`·`삭제`는 DB 담당자 DDL 대기(§5, refactor.md C-76).
- **시험:** `tests/server/common/test_db_schema.py`가 gold 표(5벌 칸 합집합)를 Alembic 모델(`common/store/db/models/`)과, ParsingMeta를 [`docs/operations/parsing_meta_mssql.sql`](../operations/parsing_meta_mssql.sql)과, master 표를 모델과 비교한다. 지금 상태가 다르면 실패하고, 목표 상태와의 차이는 목록으로 찍기만 한다.
- **쓰는 곳·읽는 곳**의 괄호 안은 아직 코드가 없는 계획이다.

## 1. 공통 규칙

- **문서 키:** 원본 경로 하나 — gold `doc.file_path` = Object Storage 원본 경로 = EDW `FileStorageMap.s3_key` = ParsingMeta `source_key`. gold에는 `s3_key` 칸도 sha256 `doc_key`도 없다(sha256은 ParsingMeta `sha256`만 — 원문 도구의 `doc_key`). 한 묶음 안에서 같은 내용(sha256)이 여러 원본 경로로 오면 첫 경로만 `doc` 행이 되고 나머지는 묶음 `docs.jsonl`의 `aliases`에만 남는다(적재·검색은 읽지 않음 — 둘째 경로로는 검색 결과·ParsingMeta 조회가 나오지 않는다).
- **출처 표시 이름:** EDW에서도 문서 본문에서도 나올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — `_edw`·`_doc`. 지금은 고객(`client_edw`·`clients_doc`)뿐이다.
- **고객 거르기:** MCP 고객 거르기는 `doc.client_edw`(문서당 하나)만 쓴다. EDW 고객이 없는 문서(LAS 등)는 고객 거르기를 걸면 빠진다. `clients_doc`은 참고용이다.
- **원천·스키마 배치·근거 키:** [pl-28](../prd/load-schema.md#pl-28). **ParsingMeta에 쓰는 것·판 칸:** [pl-25](../prd/load-schema.md#pl-25). **같은 `s3_key` 여러 행:** [pl-32](../prd/load-schema.md#pl-32).
- **대표 결과 주소 `rep_uri`:** gold에는 거르기 메타만 둔다. 대표 결과 위치(`rep_bucket`·`rep_key`)·`parsed_at`·원본 sha256은 ParsingMeta에만 있고, 원문 도구가 부를 때 `source_key`(= gold `doc.file_path`)와 `source_system`으로 행을 고른다(`pick_rep` — `status='active'` 중 `parse_date`가 가장 늦은 행, `active`가 없으면 전체 중). EDW를 못 읽으면 `registry_unavailable`. `search` 근거에는 `rep_uri`가 없다.
- **근거 `file_name`** = `doc.file_path`의 끝 조각.
- **원천별 EDW 사슬:** 적재가 `client_edw`·`created_at`·`attrs`를 채우는 표·칸은 사슬 파일 [`resources/config/edw_chain.yaml`](../../resources/config/edw_chain.yaml)이 정한다([pl-29](../prd/load.md#pl-29)·[pl-52](../prd/load-schema.md#pl-52)). 칸 이름이 실제 EDW와 같은지는 D-1·D-2.

## 2. gold — 검색 스키마 (pgvector — 원천별 스키마 5벌)

판: `common/store/db/migrations/versions/0001_search_base.py` … `0005_doc_attrs.py` · 모델: `common/store/db/models/search_tables.py`(`SOURCES`·`DOC_META`·`ATTRS`·`LOAD_ATTRS`·`CHUNK_EXTRA`) · 적재: `pipeline/load/pgvector_load.py`(`load`·`_load_src`·`deploy`) · 값 만드는 곳: `pipeline/transform/structure/build_bundle.py`(`main`)·EDW 조인 `pipeline/load/edw_doc_meta.py`.

- **스키마 배치:** 기준 스키마 `<PG_SCHEMA>`(예 `ai`)에는 판 표 `alembic_version`과 공용 시퀀스 `doc_id_seq`만. 원천 스키마 `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`에 아래 표 다섯 개와 뷰 `v_chunk_source`가 같은 꼴로 있다(원천 전용 칸은 `faq.chunk.faq_group`뿐 — 그 밖의 원천 메타는 `doc.attrs` 키).
- 검색 MCP는 실행 중에 묶음 파일(`meta.json`·`docs.jsonl`·`chunks.jsonl`)을 읽지 않는다 — 임베딩 모델·문서 날짜는 `doc` 칸, 차원은 `chunk.embedding`의 `vector(n)`에서 읽는다.

### gold.doc

| 칸 | 타입 | 뜻 | 원천 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| doc_id | INT PK | 문서 행 번호 — 기본값 `nextval('<PG_SCHEMA>.doc_id_seq')`(5벌이 시퀀스 하나라 겹치지 않음). MCP `chunk_key` `<doc_id>:<seq>`의 앞부분 | 모두 | pgvector_load `_load_src` | 뷰, 원문 도구 쪽 넘김(`cursor`) | 유지 |
| file_path | TEXT NOT NULL | Object Storage 원본 경로 = EDW `FileStorageMap.s3_key` = ParsingMeta 원본 키 — ParsingMeta와 잇는 키. PC 폴더 원천은 원천 폴더 기준 상대 경로(같은 꼴). 적재 건너뛰기 키 | 모두 | build_bundle `main` → 적재 | 뷰(`file_name` = 끝 조각), search_svc 범위, 원문 도구 | 유지 |
| summary | TEXT | 문서 요약 | 모두 | build_bundle | 뷰 → 근거 | 유지 |
| created_at | TIMESTAMPTZ | 원천 등록 시각(KST) — SFDC `ContentVersion.CreatedDate` 계열 · CRMS `RM_CM_DOCU.INIT_DTTM` · LAS `FileManager.CreateDate` · 그 밖 `FileStorageMap.created_at`(§1 원천별 사슬) | 모두 | 적재(EDW 조인 — pl-29) | `search` `created_since/until`, 원문 도구 거르기·출력·등록 시각 가드 | 유지 |
| client_edw | TEXT | EDW 조인 사슬의 고객 하나 — MCP 고객 거르기는 이 칸 정확 일치만 | 모두(채워지는 곳: sfdc·crms) | 적재(EDW 조인) | search_svc 범위, 근거 `client` | 유지 |
| clients_doc | TEXT | 본문에서 찾은 고객 라벨(JSON 글자) — 참고만, 거르기·순위에 안 씀 | 모두 | build_bundle `infer_clients` → 적재 | 없음(참고) | 유지 |
| content_date | TEXT | 문서에 적힌 날짜(ISO 글자 `YYYY-MM-DD`·`YYYY-MM`·`YYYY` — 본문 앞 2000자 먼저, 없으면 파일 이름, `common/core/docmeta.py`. 연도만 있는 `YYYY`는 본문에서는 `2026년`처럼 날짜로 적힌 것만 — 맨 연도 숫자(예: "planned for 2027"·"2027 계획")는 안 셈, 파일 이름의 연도는 그대로 셈). `created_at`(원천 등록 시각)과 다르고, 파일 생성·수정 시각도 아니다 | 모두 | build_bundle(`docmeta.doc_meta`의 `doc_date`) → 적재(판 0004) | pgsearch → 근거 `doc_date`(출력 이름은 그대로) — 검색 뷰엔 없음 | 유지 |
| embed_model | TEXT | 그 문서를 임베딩한 모델 이름(묶음 `meta.json` `embed_model`) | 모두 | 적재(판 0004) | pgsearch `index_meta` — 질의 모델 확인(섞이면 거부), 나중 guard(문서 단위) — 검색 뷰엔 없음 | 유지 |
| attrs | JSONB | 원천마다 다른 문서 메타 `{키: 값}`(GIN 색인 `ix_<스키마>_doc_attrs`) — 키·EDW 칸·검색 거르기 이름·근거 표시는 사슬 파일 `edw_chain.yaml`(`fields`)이 정하고, `doc_class`는 분류가 쓴다(SFDC·LAS). 값 없는 키는 넣지 않는다. 지금 키는 아래 표(판 0005 — [pl-52](../prd/load-schema.md#pl-52)) | 모두(키는 원천마다) | 적재(EDW 조인 `edw_meta` + 분류 `doc_class`) — 판 0005 | 뷰 → `search` `attrs`·이름 있는 거르기(사슬 `filter:`)·근거 `attrs`(`evidence: true`), `list_doc_fulltext` `doc_class`·`sf_op_id`, 분류 힌트(pl-33) | 유지 |

#### gold.doc.attrs 키(기본 사슬 파일 `resources/config/edw_chain.yaml` 기준 — 서버 사본이 바꾸면 그쪽이 맞음)

거르기 이름·근거 여부는 사슬 파일의 `filter`·`evidence`.

| 키 | 값 | 뜻 | 원천 | 읽는 곳 |
|---|---|---|---|---|
| `doc_class` | 글자 | 문서 분류 라벨 하나(SFDC: RFI/RFP/RFI+RFP/Proposal/Other, LAS: MSA/PSA/QAG/LOI/Amendment/Assignment Letter/Other) — [pl-33](../prd/transform.md#pl-33) | sfdc·las | `search`·`list_doc_fulltext` 거르기 |
| `sf_op_id` | 글자 | 영업 기회 id(18자 `006…`) — 파일 → 영업 기회 사슬로 고른 것 | sfdc | `search`·`list_doc_fulltext` 거르기 |
| `sf_op_name` | 글자 | 영업 기회 이름(`Opportunity.Name`) | sfdc | `search` 거르기 |
| `project_code__c` | 글자 | 프로젝트 코드(`Opportunity.Project_Code__c`) | sfdc | `search` `project_id` |
| `service_type` | 글자 | 서비스 유형(`Opportunity.Record_Type__c`) | sfdc | `search` 거르기 |
| `division` | 글자 | 사업부(`RM_CM_PJTLIST.DIVISION`) | crms | `search` 거르기 |
| `prod_name` | 글자 | 제품·계약 이름(`RM_CM_PJTLIST.RM_CONTRACT_NAME`) | crms | 없음(근거 메타) |
| `contract_id` | 글자 | 계약 번호 — CRMS `rm_contract_code` · LAS `manage_no`(없으면 `Contract.ContractID`) | crms·las | `search` 거르기 |
| `contract_date` | 날짜 글자(YYYY-MM-DD) | 계약일 — SFDC `Opportunity.X1st_Contract_Execution_Date__c` · CRMS `RM_CM_PJTLIST.INIT_DTTM` · LAS `Contract.ContractDate`(없으면 `FileStorageMap_LAS.signed_date`) | sfdc·crms·las | 없음(근거 메타) |
| `title` | 글자 | 분류 힌트 — 파일 제목(`ContentVersion.Title`). 비면 분류 지시문은 원본 파일 이름 | sfdc | 분류(pl-33) |
| `entity_type` | 글자 | 분류 힌트 — 첫 User 아닌 연결 개체 종류(`ContentDocumentLink.LinkedEntityId` 앞 3자 → `resources/mappings/sfdc_prefix.json`, 표에 없으면 `Unknown:<접두>`) | sfdc | 분류(pl-33) |
| `entity_class` | 글자 | 분류 힌트 — 개체 갈래(운영 analyze_clues 그대로): 연결 없음 `unlinked` · 모두 User면 `user_only` · 아니면 개체 종류의 갈래(if_log·event_log·task·event·quote·opportunity·account·contract·dashboard·organization, 그 밖 other) | sfdc | 분류(pl-33) |
| `entity_id` | 글자 | 분류 힌트 — 그 연결 개체 id(`LinkedEntityId`) | sfdc | 분류(pl-33) |
| `sent_received__c` | 글자 | 분류 힌트 — 연결 개체가 Task/Event일 때 방향(`Sent_Received__c`) | sfdc | 분류(pl-33) |
| `subject` | 글자 | 분류 힌트 — 연결 개체가 Task/Event일 때 제목(`Subject` 앞 120자) | sfdc | 분류(pl-33) |
| `stagename` | 글자 | 분류 힌트 — 연결 개체가 영업 기회 자체일 때 단계(`Opportunity.StageName` — 사슬이 고른 기회가 아님) | sfdc | 분류(pl-33) |
| `real_rfp__c` | 글자 | 분류 힌트 — 같은 기회의 `Real_RFP__c`(글자 '1'/'0') | sfdc | 분류(pl-33) |
| `rfp_received_start_date__c` | 날짜 글자(YYYY-MM-DD) | 분류 힌트 — 같은 기회의 `RFP_Received_Start_Date__c` | sfdc | 분류(pl-33) |
| `rfp_received_end_date__c` | 날짜 글자(YYYY-MM-DD) | 분류 힌트 — 같은 기회의 `RFP_Received_End_Date__c` | sfdc | 분류(pl-33) |
| `approvalname` | 글자 | 분류 힌트 — 품의 제목(`LAS.Contract.ApprovalName`, 최신 판) | las | 분류(pl-33) |

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
| faq_group | TEXT | FAQ 시트 이름(`FAQ_group`) | faq | (FAQ 적재 — [pl-39](../prd/extract.md#pl-39)) | `search` `FAQ_group` 거르기 | 유지 |

### gold.chunk_term

왜 필요한가: `mcp_server/services/search/pgsearch.py` `search`의 BM25가 질의마다 청크별 단어 빈도(tf)를 이 표에서 읽는다(드문 ID 검색의 문서 수 셈도 이 표). 원천 스키마마다 하나.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT | 토큰(PK 일부) | pgvector_load(COPY) | pgsearch BM25·ID | 유지 |
| chunk_id | INT | 청크(PK 일부) | pgvector_load | pgsearch | 유지 |
| tf | SMALLINT | 그 청크 안 단어 빈도 | pgvector_load | pgsearch BM25 | 유지 |

### gold.term_stat

왜 필요한가: `pgsearch.py` BM25의 IDF — 단어마다 그 단어가 든 청크 수(df)를 질의 때 다시 세지 않게 둔다. 원천 스키마마다 하나(원천끼리 점수를 섞지 않음).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| term | TEXT PK | 토큰 | pgvector_load | pgsearch BM25 | 유지 |
| df | INT | 문서(청크) 빈도 | pgvector_load(늘리기)·`drop_terms`(줄이기) | pgsearch BM25 | 유지 |

### gold.corpus_stat

왜 필요한가: `pgsearch.py` BM25의 전체 청크 수(N)와 평균 길이(avgdl) — 한 행(검색마다 읽음 — 없으면 검색마다 청크 표 전체를 세야 함).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | SMALLINT PK | 늘 1 | pgvector_load | pgsearch | 유지 |
| n_chunks | INT | 청크 수 N | pgvector_load | pgsearch BM25 | 유지 |
| avg_len | DOUBLE | 평균 n_terms(avgdl) | pgvector_load | pgsearch BM25 | 유지 |

뷰 `v_chunk_source`는 `chunk`↔`doc`을 이은 읽기 전용 뷰다(원천 스키마마다 — 칸 = 청크 칸 + `file_name`(= `file_path` 끝 조각) + 그 원천의 doc 칸 + (faq) `faq_group`). 모델 `views_expected(원천)`이 비교 기준이다.

## 3. EDW (MSSQL)

접속: `common.connections.rdb`(읽기 계정 `rdb.read`·쓰기 계정 `rdb.write`). `query_edw` 도구는 아무 칸이나 읽을 수 있어 아래 "읽는 곳"에서 뺀다.

### edw.FileStorageMap

`AI.FileStorageMap` — 원본 파일 목록(EDW 쪽 표 — 이 프로젝트는 칸을 더하거나 지우지 않는다). 저장소에는 PC 대역 정의만 있다(`valid_env/edw/ai.sql`). 아래는 이 프로젝트가 읽는 칸만이다. 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | (EDW) | 행 번호 — 증분 수집 기준 | EDW | extract/fetch_docs `_rdb_rows`, run_docs `edw_list` | 유지 |
| s3_key | (EDW) | 원본 전체 키 = 문서 키 | EDW | source `_rdb_rows`(매니페스트 `key`), run_docs | 유지 |
| original_filename | (EDW) | 원본 파일 이름 | EDW | source, run_docs | 유지 |
| file_size | (EDW) | 크기 | EDW | source, run_docs | 유지 |
| content_version_id | (EDW) | 판 id | EDW | source `_rdb_rows` | 유지 |
| source_system | (EDW) | 원천 — 코드는 읽지 않는다. 원천은 `s3_key` 첫 마디로 정한다(§1 원천) | EDW | 없음 | 유지 |
| created_at | (EDW) | 원천 등록 시각 — 같은 `s3_key` 여러 행 중 기준 행 고르기([pl-32](../prd/load-schema.md#pl-32)), 원천 표에 등록 시각이 없을 때 gold `doc.created_at`의 대체값(KST). 실제 EDW에 있는지는 D-1 | EDW | 적재 `edw_meta`(사슬 `file.created_at`) · (기준 행 고르기 — [pl-32](../prd/load-schema.md#pl-32)) | 유지 |

### edw.SupersededRow

같은 `s3_key`의 더 새 `FileStorageMap` 행 때문에 밀려난 행의 예외 이력([pl-32](../prd/load-schema.md#pl-32)). 표 이름과 칸은 DB 담당자가 정한다(D-9) — 아래는 안이다. 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| file_storage_map_id | (EDW, 안) | 밀려난 `FileStorageMap` 행 id | (파이프라인 — 기준 행 고를 때) | (운영자) | 새로 |
| s3_key | (EDW, 안) | 겹친 문서의 원본 키 | 〃 | 〃 | 새로 |
| kept_file_storage_map_id | (EDW, 안) | 기준으로 남은 행 id | 〃 | 〃 | 새로 |
| reason | (EDW, 안) | "파싱 대상 아님 — 같은 s3_key의 더 새 행" | 〃 | 〃 | 새로 |
| recorded_at | (EDW, 안) | 기록한 때 | 〃 | 〃 | 새로 |

### edw.Quote

PC 대역 EDW(`valid_env/edw/sfdc.sql`)에만 있는 **예시 칸**이다. 서버 EDW에는 Quote 표가 없어 기본 사슬에서 빠져 있다 — 표가 생기면 사슬 파일의 Quote 주석 줄을 켠다(실제 표·칸 이름은 D-1). 시험 비교 대상이 아니다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| Id | (예시) | Quote id | (PC 대역 시드) | (사슬 파일에서 켤 때만) | 새로 |
| OpportunityId | (예시) | 연결된 영업 기회 | 〃 | 〃 | 새로 |
| AccountId | (예시) | 연결된 고객 계정 — 고객 이름은 `SFDC.Account` | 〃 | 〃 | 새로 |

### edw.ParsingMeta

`AI.ParsingMeta` — 파싱 결과(silver) 게시 기록. 정의: `docs/operations/parsing_meta_mssql.sql`. 쓰는 곳: `pipeline/load/publish_parse_result.py`(`plan`·`apply` — 행 만들기), `common/store/parsing_meta_db.py`(`insert_new` — INSERT, `set_loaded` — `loaded_at`·`gold_version` UPDATE). UPDATE는 이것뿐이다(`status` 바꾸기 없음). 무엇을 쓰는지는 [pl-25](../prd/load-schema.md#pl-25).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| parse_meta_id | BIGINT IDENTITY PK | 행 번호 | DB | 없음(기본 키) | 유지 |
| source_system | NVARCHAR(64) | 원천 | publish_parse_result `plan` | parsing_meta_db 겹침 확인·`pick_rep`(원문 도구·`set_loaded` 행 고르기) | 유지 |
| source_key | NVARCHAR(1024) | 원본 전체 경로 = `AI.FileStorageMap.s3_key` 값 = gold `doc.file_path`. 원본과의 연결 키는 `source_system` + 이 칸. 이름을 `s3_key`로 바꾼다(아래 `s3_key` 줄 — DB 담당자 DDL, C-76) | publish_parse_result `plan` | 〃, run_docs `edw_done_keys`, mcp `fulltext_svc` | 유지 |
| s3_key | NVARCHAR(1024) | 위 `source_key`의 새 이름 — DB 담당자가 이름을 바꾸면 계산 칸 `source_key_hash`·유일 색인 `UQ_ParsingMeta_key`도 다시 만든다(C-76). 코드는 연결할 때 `s3_key`가 있으면 그것, 없으면 `source_key`를 쓴다(`parsing_meta_db` `key_col`·run_docs) | (DDL 뒤 같은 곳) | (같은 곳) | 새로 |
| source_uri | NVARCHAR(2048) | 원본 주소 | 〃 | 없음 | 삭제 |
| original_filename | NVARCHAR(512) | 원본 파일 이름 | 〃 | 없음 | 삭제 |
| file_format | NVARCHAR(32) | 형식 | 〃 | 없음 | 삭제 |
| file_size | BIGINT | 크기 | 〃 | 없음 | 삭제 |
| sha256 | NVARCHAR(64) | 원본 sha256 — 원문 도구 `doc_key`(입력·출력) · 같은 내용 묶기에 씀("파싱 정보만"의 예외) | publish_parse_result `plan` | mcp `fulltext_svc`(`list_doc_fulltext` `doc_key` 입력·출력) | 유지 |
| rep_bucket | NVARCHAR(256) | 대표 결과 버킷 | publish_parse_result `plan` | mcp `fulltext_svc`(`parsing_meta_db.rows_where`·`pick_rep` — 원문 도구가 부를 때 읽음) | 유지 |
| rep_key | NVARCHAR(2048) | 대표 결과 폴더 | publish_parse_result `apply` | 〃(목록 `rep_uri`·sfid 발급, 등록 시각 가드의 폴더 → 원본 찾기) | 유지 |
| rep_etag | NVARCHAR(128) | 대표 결과 etag | 〃 | 없음 | 삭제 |
| parse_status | NVARCHAR(32) | ok·partial | publish_parse_result `plan` | run_docs `edw_done_keys` | 유지 |
| status_reason | NVARCHAR(2000) | 상태 이유 | 〃 | 없음 | 삭제 |
| rep_engine | NVARCHAR(128) | 대표 엔진(gold에도 두지 않음) | publish_parse_result `plan` | 없음 | 삭제 |
| rep_acc | FLOAT | 대표 정확도 | 〃 | 없음 | 삭제 |
| page_count | INT | 쪽 수 | 〃 | 없음 | 삭제 |
| doc_key | NVARCHAR(64) | 원본 sha256(지금 유일한 필수 칸) | 〃 | 없음 | 삭제 |
| parse_date | NVARCHAR(32) | 파싱 시각 글자(`YYYY-MM-DD_HHMMSS`) | publish_parse_result `apply` | `pick_rep`(가장 늦은 행) | 유지 |
| pipeline_version | NVARCHAR(64) | 이 행의 silver를 만든 코드 판(`VERSION` — `common.pipeline_version()`, 게시 때). 이름을 `silver_version`으로 바꾼다(아래 줄 — DB 담당자 DDL, C-76) | publish_parse_result `plan` | (운영자·재처리 판정) | 유지 |
| silver_version | NVARCHAR(64) | 위 `pipeline_version`의 새 이름 — 이 행의 silver를 만든 코드 판. 코드는 연결할 때 `silver_version`이 있으면 그것, 없으면 `pipeline_version`에 쓴다(`parsing_meta_db.RENAMES`) | (DDL 뒤 같은 곳) | (같은 곳) | 새로 |
| status | NVARCHAR(16) | 행 상태 — 게시는 늘 `active`로 쓴다(다른 값으로 바꾸는 코드는 없음, 운영이 바꾼 행은 읽음) | publish_parse_result `plan` | `pick_rep`(`active` 중 `parse_date`가 가장 늦은 행, `active`가 없으면 전체 중 — `parse_status`는 안 봄) | 유지 |
| status_at | NVARCHAR(32) | 상태 바뀐 때(UTC) — 게시는 비워 둔다 | publish_parse_result `plan`(NULL) | 없음(SELECT 안 함 — 운영자가 봄) | 유지 |
| engines_used | NVARCHAR(MAX) | 쓰인 엔진(JSON) — 목표: 성공한 엔진만(이름 + 판) | publish_parse_result `plan` | 없음 | 유지 |
| engines_summary | NVARCHAR(512) | 엔진 한 줄 요약 | 〃 | 없음 | 삭제 |
| parsed_at | DATETIME2(0) | 넣은 때(기본 SYSUTCDATETIME — UTC) | DB 기본값 | mcp `fulltext_svc`(`list_doc_fulltext` `since`/`until`) | 유지 |
| source_key_hash | BINARY(32) 계산 칸 | `source_key` sha256 — 유일 색인 키(1700바이트 상한 우회) | DB | 유일 색인 | 유지 |
| gold_status | NVARCHAR(32) | gold(검색 DB) 적재 상태 | ([pl-55](../prd/ops.md#pl-55) — run_docs·적재) | (운영자) | 새로 |
| gold_reason | NVARCHAR(2000) | gold 상태 이유(실패 원인 등) | ([pl-55](../prd/ops.md#pl-55)) | (운영자) | 새로 |
| engines_failed | NVARCHAR(MAX) | 실패한 엔진(JSON — 이름·이유·걸린 시간), 없으면 NULL | (파싱 단계 — [pl-32](../prd/load-schema.md#pl-32)) | (운영자) | 새로 |
| loaded_at | DATETIME2(0) | gold에 적재한 시각(UTC) — 적재가 PG 커밋 뒤 쓸 행(active 중 최신)에 UPDATE. 칸이 없으면 그 칸만 빼고 쓰고, 쓰기 계정이 없거나 실패하면 경고와 건수만(적재는 그대로) | pgvector_load `_mark_loaded` → parsing_meta_db `mark_loaded`·`set_loaded` | (운영자 — 적재 확인) | 새로 |
| gold_version | NVARCHAR(64) | 이 문서를 gold에 올린 코드 판 — `<VERSION>+m<마스터 해시 앞 8자>`([pl-38](../prd/load.md#pl-38)). `loaded_at`과 같은 UPDATE로 쓴다. 칸이 없으면 그 칸만 빼고 `loaded_at`만 | pgvector_load `_mark_loaded` → parsing_meta_db `set_loaded` | parsing_meta_db `done_source_keys`·run_docs `edw_done_keys`(비면 다시 대상 — ok·partial만) | 새로 |
## 4. master — 마스터 표 (검색 PG, 스키마 `<PG_SCHEMA>_master`, [pl-38](../prd/load.md#pl-38))

원본은 git CSV `resources/vocab/glossary/<표>.csv`(샘플 데이터). 실행 중에는 이 표만 읽는다 — `dbtool up --target master`로 표를 만들고 `dbtool master load`가 CSV로 내용을 한 트랜잭션에 통째로 바꾼다(초기화 순서: `dbtool up`(search·applog·master) → `dbtool master load`). CSV 하나 = 표 하나 — 칸은 CSV 머리글 그대로(모두 `TEXT`) + 파일 순서 `row_no`(`INTEGER`, 기본 키), 목록 칸은 지금처럼 `;`·`|` 글자. 머리글을 바꾸면 새 Alembic 판(갈래 `master`). 판: `common/store/db/migrations/versions/0001_master_base.py` · 모델: `common/store/db/models/master_tables.py` · 읽기·채우기: `common/store/master.py`(프로세스마다 한 번 — 서버(dev·prd)는 못 읽으면 멈춤, PC는 같은 CSV로 채운 SQLite 대역). `tests/server/common/test_db_schema.py`가 이 절의 칸을 모델과 대조한다.

- **해시·판:** `master_meta.hash` = 표 이름·머리글·`row_no` 순서 행의 sha256(16진 64자). 구조화가 읽은 마스터 해시를 묶음 `meta.json` `master_hash`에 남기고 적재가 ParsingMeta `gold_version` = `<VERSION>+m<해시 앞 8자>`로 쓴다(`master_hash`가 없는 묶음은 `<VERSION>`만). `silver_version`에는 붙이지 않는다. 마스터 해시는 캐시 열쇠·code_fp에 없다 — 마스터가 바뀌어도 자동 전체 재처리는 없고 `gold_version`으로 추적한다.
- **파일로 남는 것:** `client_master.example.csv`·`client_master_map.example.json`(명부 초안 도구 `gen_roster` 입력·예시) · `client_roster_seed.json`(주요 바이오·제약사 공개 이름 seed — 구조화 `infer_clients`가 파일로 읽음).

### master.client_roster

고객 명부 — 읽는 칸: `canonical_name`(비면 `name_ko`), `aliases`(`;`·`|` 구분), `status`(inactive·deleted면 건너뜀). 읽는 곳: `common.core.terms` `_aliases`(구조화 고객 판별 `infer_clients` · 검색 질문 고객·별칭).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| client_id | TEXT | CSV 칸 `client_id` | `dbtool master load` | 〃 | 새로 |
| canonical_name | TEXT | CSV 칸 `canonical_name` | `dbtool master load` | 〃 | 새로 |
| name_ko | TEXT | CSV 칸 `name_ko` | `dbtool master load` | 〃 | 새로 |
| aliases | TEXT | CSV 칸 `aliases` | `dbtool master load` | 〃 | 새로 |
| client_type | TEXT | CSV 칸 `client_type` | `dbtool master load` | 〃 | 새로 |
| segment | TEXT | CSV 칸 `segment` | `dbtool master load` | 〃 | 새로 |
| country | TEXT | CSV 칸 `country` | `dbtool master load` | 〃 | 새로 |
| parent_client_id | TEXT | CSV 칸 `parent_client_id` | `dbtool master load` | 〃 | 새로 |
| status | TEXT | CSV 칸 `status` | `dbtool master load` | 〃 | 새로 |
| description | TEXT | CSV 칸 `description` | `dbtool master load` | 〃 | 새로 |
| source | TEXT | CSV 칸 `source` | `dbtool master load` | 〃 | 새로 |
| updated | TEXT | CSV 칸 `updated` | `dbtool master load` | 〃 | 새로 |

### master.client_master

고객 마스터(별칭 `|` 구분). 읽는 곳: 없음.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| company_id | TEXT | CSV 칸 `company_id` | `dbtool master load` | 〃 | 새로 |
| company | TEXT | CSV 칸 `company` | `dbtool master load` | 〃 | 새로 |
| aliases | TEXT | CSV 칸 `aliases` | `dbtool master load` | 〃 | 새로 |

### master.contract_master

계약 마스터. 읽는 곳: 없음.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| contract_id | TEXT | CSV 칸 `contract_id` | `dbtool master load` | 〃 | 새로 |
| company | TEXT | CSV 칸 `company` | `dbtool master load` | 〃 | 새로 |
| company_id | TEXT | CSV 칸 `company_id` | `dbtool master load` | 〃 | 새로 |
| product_code | TEXT | CSV 칸 `product_code` | `dbtool master load` | 〃 | 새로 |
| modality | TEXT | CSV 칸 `modality` | `dbtool master load` | 〃 | 새로 |
| site | TEXT | CSV 칸 `site` | `dbtool master load` | 〃 | 새로 |
| line_id | TEXT | CSV 칸 `line_id` | `dbtool master load` | 〃 | 새로 |
| batches_contracted | TEXT | CSV 칸 `batches_contracted` | `dbtool master load` | 〃 | 새로 |
| contract_value_usd | TEXT | CSV 칸 `contract_value_usd` | `dbtool master load` | 〃 | 새로 |
| currency | TEXT | CSV 칸 `currency` | `dbtool master load` | 〃 | 새로 |
| term_months | TEXT | CSV 칸 `term_months` | `dbtool master load` | 〃 | 새로 |
| signed_on | TEXT | CSV 칸 `signed_on` | `dbtool master load` | 〃 | 새로 |
| start_date | TEXT | CSV 칸 `start_date` | `dbtool master load` | 〃 | 새로 |
| end_date | TEXT | CSV 칸 `end_date` | `dbtool master load` | 〃 | 새로 |
| status | TEXT | CSV 칸 `status` | `dbtool master load` | 〃 | 새로 |

### master.domain_terms

용어 사전(`status`는 approved·draft — approved만 씀). 읽는 곳: `common.core.terms` `load_glossary`(검색 질문 넓히기·근거 상태·고객 별칭의 org_client).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| concept_id | TEXT | CSV 칸 `concept_id` | `dbtool master load` | 〃 | 새로 |
| canonical | TEXT | CSV 칸 `canonical` | `dbtool master load` | 〃 | 새로 |
| category | TEXT | CSV 칸 `category` | `dbtool master load` | 〃 | 새로 |
| synonyms | TEXT | CSV 칸 `synonyms` | `dbtool master load` | 〃 | 새로 |
| abbreviations | TEXT | CSV 칸 `abbreviations` | `dbtool master load` | 〃 | 새로 |
| weak_synonyms | TEXT | CSV 칸 `weak_synonyms` | `dbtool master load` | 〃 | 새로 |
| broader | TEXT | CSV 칸 `broader` | `dbtool master load` | 〃 | 새로 |
| related | TEXT | CSV 칸 `related` | `dbtool master load` | 〃 | 새로 |
| context_required | TEXT | CSV 칸 `context_required` | `dbtool master load` | 〃 | 새로 |
| case_sensitive | TEXT | CSV 칸 `case_sensitive` | `dbtool master load` | 〃 | 새로 |
| definition_ko | TEXT | CSV 칸 `definition_ko` | `dbtool master load` | 〃 | 새로 |
| definition_en | TEXT | CSV 칸 `definition_en` | `dbtool master load` | 〃 | 새로 |
| source | TEXT | CSV 칸 `source` | `dbtool master load` | 〃 | 새로 |
| owner | TEXT | CSV 칸 `owner` | `dbtool master load` | 〃 | 새로 |
| status | TEXT | CSV 칸 `status` | `dbtool master load` | 〃 | 새로 |
| updated | TEXT | CSV 칸 `updated` | `dbtool master load` | 〃 | 새로 |

### master.id_patterns

ID 모양 정규식(계약 번호·제품 코드 등). 읽는 곳: `common.core.terms` `load_id_patterns_typed`(검색 tie-break·엔티티 힌트).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| id_type | TEXT | CSV 칸 `id_type` | `dbtool master load` | 〃 | 새로 |
| regex | TEXT | CSV 칸 `regex` | `dbtool master load` | 〃 | 새로 |
| example | TEXT | CSV 칸 `example` | `dbtool master load` | 〃 | 새로 |
| note | TEXT | CSV 칸 `note` | `dbtool master load` | 〃 | 새로 |
| updated | TEXT | CSV 칸 `updated` | `dbtool master load` | 〃 | 새로 |

### master.units

단위 표기(숫자+단위 나누기는 코드 규칙). 읽는 곳: 없음.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| row_no | INTEGER PK | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| canonical | TEXT | CSV 칸 `canonical` | `dbtool master load` | 〃 | 새로 |
| variants | TEXT | CSV 칸 `variants` | `dbtool master load` | 〃 | 새로 |
| quantity | TEXT | CSV 칸 `quantity` | `dbtool master load` | 〃 | 새로 |
| equivalent_to | TEXT | CSV 칸 `equivalent_to` | `dbtool master load` | 〃 | 새로 |
| note | TEXT | CSV 칸 `note` | `dbtool master load` | 〃 | 새로 |
| updated | TEXT | CSV 칸 `updated` | `dbtool master load` | 〃 | 새로 |

### master.master_meta

마스터 내용 해시 1행(`id` = 1). 쓰는 곳: `dbtool master load`. 읽는 곳: `common.store.master.read`(표가 비었으면 멈춤).

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | INTEGER PK | 늘 1 | `dbtool master load` | — | 새로 |
| hash | TEXT | 내용 sha256(위 해시 규칙) | 〃 | `common.store.master.read` | 새로 |
| loaded_at | TIMESTAMP WITH TIME ZONE | 채운 시각(UTC) | 〃 | (운영자) | 새로 |

## 5. DB 담당자 확인 필요

번호 D-5·D-7은 비어 있다(다른 문서가 번호로 가리켜서 다시 매기지 않음).

| # | 무엇 | 왜 |
|---|---|---|
| D-1 | `AI.FileStorageMap`의 실제 정의 — `created_at`이 있는지(같은 `s3_key` 중 가장 늦은 행을 이 칸으로 고름), 원천별 등록 시각(SFDC `ContentVersion.CreatedDate`, CRMS `RM_CM_DOCU.INIT_DTTM`, LAS `FileManager.CreateDate`)과 같은 값인지 · 원천 id 칸의 실제 이름 · SFDC Quote 표의 실제 이름·칸과 `OpportunityId` 연결 | 저장소에는 PC 대역(`valid_env/edw/ai.sql`)뿐 |
| D-2 | `client_edw`·원천 메타를 얻는 사슬(`resources/config/edw_chain.yaml`)의 표·칸 이름이 실제 EDW와 같은지 | 적재가 EDW 읽기 계정으로 직접 조인한다([pl-29](../prd/load.md#pl-29)) — 칸 이름은 운영 노트 기준(refactor.md C-76) · LAS 고객은 상대사 출처가 정해질 때까지 비움 |
| D-3 | `AI.ParsingMeta` 칸 정리(ALTER) — §3 `삭제` 칸 지우기, `gold_status`·`gold_reason`·`engines_failed`·`loaded_at`·`gold_version` 더하기, `source_key` → `s3_key`·`pipeline_version` → `silver_version` 이름 바꾸기, `engines_used` 뜻 바꿈(성공한 엔진만), 운영이 더한 분류·고객 칸(`doc_class`·`doc_class_low_conf`·`doc_class_at`·`doc_class_model`·`sf_op_id`·`created_at`·`sf_acc_name` 등) 지우기 | 이 프로젝트 밖에서 그 칸을 읽는 곳이 있는지 모름 · 운영 분류 스크립트가 멈추므로 운영 담당자에게 알린다 |
| D-4 | `ParsingMeta.doc_key` 삭제 때 `UQ_ParsingMeta_dockey`·`IX_ParsingMeta_doc_key` 색인 처리 · `source_key`를 필수(NOT NULL)로 | 지금 `source_key`가 비면 `doc_key`가 겹침 키 |
| D-6 | 원천별 gold 스키마 5벌 + 기준 스키마의 공용 `doc_id_seq`(§2) — 기존 서버 데이터는 백업 뒤 다시 적재 | 첫 적재가 전체 e2e([pl-54](../prd/ops.md#pl-54))와 함께 · refactor.md C-74·C-76 |
| D-8 | FAQ 원천 등록 — Object Storage `FAQ/<uuid>/<파일>`을 `AI.FileStorageMap`에 등록(run_docs는 `s3_key LIKE 'FAQ/%'`로 고름 — [pl-39](../prd/extract.md#pl-39)) | FAQ 행을 누가 어떻게 넣나 |
| D-9 | 밀려난 `FileStorageMap` 행의 예외 이력 표(§3 `edw.SupersededRow` 안) — 표 이름·칸·누가 쓰나 | [pl-32](../prd/load-schema.md#pl-32) |
| D-10 | `applog` 스키마 추가(§6) — `up`의 `CREATE SCHEMA`, `maintain`의 파티션 생성·DROP, 앱의 INSERT와 `pipe_run` UPDATE 권한. 호출량 기준 용량(`mcp_log` 행 본문 최대 약 80KB) | 새 스키마이고 로그 쓰기가 기존 PG 접속 정보를 함께 씀 |
| D-11 | `applog.mcp_log`의 `args`·`result` 읽기 권한 분리 | 문서 본문·EDW 결과가 들어가는데(`get_doc_fulltext` 응답은 문서 원문 전체) 판에 GRANT가 없어 지금은 앱 계정이 읽을 수 있음 |
| D-12 | 실제 보존 기간 약 90~120일(월 단위 DROP)이 감사·개인정보 기준에 맞는지, `dbtool maintain` 매일 예약 | 예약이 약 2개월 이상 멈추면 새 달 파티션이 없어 DB 쓰기가 실패하고 대체 파일로만 쌓임 |

## 6. applog — 로그 저장소 (pgvector PG, 스키마 `applog`, [op-01](../prd/ops.md#op-01))

gold·EDW와 별개인 로그 표다. 서버 적용 절차는 refactor.md C-79.

판: `common/store/db/migrations/versions/0001_applog_base.py`(브랜치 `applog`) · 파티션 관리: `common/store/db/migrations/applog_parts.py` · 모델: `common/store/db/models/log_tables.py` · 쓰기: `common/store/logsink.py`(큐 → 배치 INSERT, 실패하면 `output/logs/*.jsonl`, 앱이 DDL을 실행하지 않음). 켜는 설정: 파일 자리 `ops.log.db_enabled`(모델 `common.log.db_enabled`, 서버 이미지 기본 켬·PC 기본 꺼짐 — op-13). `tests/server/common/test_db_schema.py`는 이 절을 대조하지 않는다 — 판과 실제 DB 대조는 `dbtool check --target applog`.

- **파티션:** `mcp_log`(`requested_at`)·`pipe_event`(`ts_start`)는 월 단위(UTC). 이름은 `<표>_YYYYMM`. `dbtool up`과 `dbtool maintain`이 현재 달부터 3개월 치를 만든다.
- **보존:** `dbtool maintain --target applog`를 매일 실행한다. `ops.log.retention_days`(기본 90)가 지난 달의 파티션을 DROP하고 `pipe_run`은 DELETE한다. 달이 통째로 지나야 DROP되므로 파티션 표의 행은 약 90~120일 남는다.
- **되돌리기:** `downgrade`는 막혀 있다. 지우려면 DB 담당자가 직접 한다.
- **연결:** `pipe_event.run_id` → `pipe_run.run_id`는 외래 키가 없다(지우는 시점이 달라 짝 없는 행이 생길 수 있음). 파티션 표의 `id`는 기본 키가 시각과 묶여 있어 그것만으로는 고유하지 않다.
- **기록하지 않는 값:** MCP `clientInfo`(사용자 11-02, `args`에서도 뺌). 접속 IP는 11-04에 `mcp_log.client_ip`로 되살렸다(사용자 11-04).

### applog.mcp_log

MCP 요청 1건당 1행. 인증 실패와 `initialize`도 행으로 남는다. 기본 키 `(id, requested_at)`. 색인: `requested_at`(BRIN) · `(agent_id, requested_at)` · `(session_id, requested_at)` · `(knox_id, requested_at)` · `(tool_name, requested_at)` · `request_id`. 쓰는 곳: `mcp_server/services/call_log.py`(내부 행을 `_columns`가 이 칸 이름으로 바꿈). 읽는 코드는 없다(감사 조회용). 질의 기록은 이 표뿐이다(`args`에 질문·SQL — 파일 기록 없음, op-13). 이 표는 이전 이름 `mcp_call`에 인증·권한 설계안(DBML: `agent`·`agent_api_key`·`source`·`agent_source_mapping`)의 칸을 합친 것이다. 그 표들은 아직 없어서 `agent_id`·`api_key_id`는 FK 없이 자리만 있다.

| 칸 | 타입 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|
| id | BIGSERIAL | 일련번호(PK 일부) | DB | 없음 | 새로 |
| request_id | UUID | 요청 ID(`X-Request-Id`, 없으면 서버가 만듦) — `qa_log`와 연결 | call_log | 없음 | 새로 |
| session_id | VARCHAR(128) | `Mcp-Session-Id`. 없으면 NULL | 〃 | 없음 | 새로 |
| turn_id | VARCHAR(128) | 대화 턴 ID. 아직 채우는 코드 없음 | (없음) | 없음 | 새로 |
| agent_id | SMALLINT | 인증된 Agent. `agent` 표가 생기면 FK 추가, 그 전까지 NULL | (없음) | 없음 | 새로 |
| api_key_id | INTEGER | 요청에 쓴 API 키. `agent_api_key` 표가 생기면 `agent_api_key.id` FK 추가, 그 전까지 NULL. 키 문자열은 로그에 남기지 않음. 아직 채우는 코드 없음 | (없음) | 없음 | 새로 |
| knox_id | VARCHAR(64) | `X-MCP-User`, 없으면 `_meta.user`(자기 신고 값, 검증 안 함) | call_log | 없음 | 새로 |
| requested_at | TIMESTAMPTZ NOT NULL | 호출 시각(기본 now, 파티션 키) | 〃 | 없음 | 새로 |
| finished_at | TIMESTAMPTZ | 끝난 시각 | 〃 | 없음 | 새로 |
| duration_ms | INTEGER | 걸린 시간 | 〃 | 없음 | 새로 |
| queue_wait_ms | INTEGER | 실행 전 대기 시간 | 〃 | 없음 | 새로 |
| rpc_method | VARCHAR(32) CHECK | initialize·tools/list·tools/call. 인증 거부 행은 본문을 읽기 전이라 NULL. 지금 `tools/list`는 기록하지 않음 | 〃 | 없음 | 새로 |
| tool_name | VARCHAR(64) | `tools/call`일 때만 도구 이름 | 〃 | 없음 | 새로 |
| status | VARCHAR(16) CHECK | ok·error·denied·unauthorized·busy·timeout. `denied`는 권한 설계 전이라 아직 안 씀 | 〃 | 없음 | 새로 |
| error_code | VARCHAR(64) | `tool_timeout`·`busy`·`invalid_key`·`tool_error`·`audit_queue_full` | 〃 | 없음 | 새로 |
| error_message | TEXT | 오류 내용(비밀값 가림) | 〃 | 없음 | 새로 |
| args | TEXT | 입력 JSON 앞부분(`tuning.search.audit.max_input_bytes`, 기본 16KB). 비밀값 가림. `content_b64`는 해시와 크기로 바꿈 | 〃 | 없음 | 새로 |
| args_bytes | INTEGER | 입력 원본 크기 | 〃 | 없음 | 새로 |
| args_truncated | BOOLEAN | 입력이 잘렸는지. 잘리면 JSON으로 안 읽힐 수 있음 | 〃 | 없음 | 새로 |
| result | TEXT | 출력 JSON 앞부분(`tuning.search.audit.max_output_bytes`, 기본 64KB). 문서 본문·EDW 결과 포함 가능 | 〃 | 없음 | 새로 |
| result_bytes | INTEGER | 출력 원본 크기 | 〃 | 없음 | 새로 |
| result_truncated | BOOLEAN | 출력이 잘렸는지 | 〃 | 없음 | 새로 |
| result_sha256 | CHAR(64) | 출력 원본 전체의 해시 | 〃 | 없음 | 새로 |
| result_keys | JSONB | 자르지 않는 응답 식별 정보(search `chunk_keys`, 원문 도구 `doc_keys`·파일 요약, `row_count` 등) | 〃 | 없음 | 새로 |
| result_count | INTEGER | 돌려준 근거 수·행 수. 아직 채우는 코드 없음(`result_keys`에 있음) | (없음) | 없음 | 새로 |
| client_ip | INET | 접속 소켓 주소(프록시 뒤면 프록시 IP). stdio는 NULL | call_log | 없음 | 새로 |
| app_version | VARCHAR(32) | 앱 버전 | 〃 | 없음 | 새로 |

`session_id`·`knox_id`·`tool_name`·`app_version`은 길이를 넘으면 `call_log._columns`가 자른다(넘으면 배치 INSERT가 통째로 실패해 파일 대체 기록으로 간다).

과부하로 감사 대기열이 차면 `args`·`result` 없는 행이 남고(`error_code=audit_queue_full`), 기록기 큐까지 차면 행 없이 건수로만 집계된다(호출 1건 = 1행의 예외, 사용자 11-01).

### applog.pipe_run

파이프라인 실행 1건당 1행. 기본 키 `run_id`. 색인: `started_at`. 시작할 때 `status=running`으로 쓰고 끝날 때 같은 `run_id`로 덮어쓴다(UPSERT — 이 표만). 강제 종료된 실행은 `running`으로 남는다. 쓰는 곳: `pipeline/shared/runtrace.py`. 읽는 곳: `pipeline/tools/perf_report.py`.

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
| code_fp | JSONB | 레이어별 code_fp(DB 기록이 켜졌을 때만 계산) | 〃 | 〃(실행 비교) | 새로 |
| stack | TEXT | 스택 이름 | 〃 | 〃 | 새로 |
| settings_hash | TEXT | 설정 해시(DB 기록이 켜졌을 때만 계산) | 〃 | 〃 | 새로 |
| docs_total | INTEGER | 문서 수 | 〃 | 〃 | 새로 |
| docs_ok | INTEGER | 성공 문서 수 | 〃 | 〃 | 새로 |
| docs_fail | INTEGER | 실패 문서 수 | 〃 | 〃 | 새로 |
| docs_reused | INTEGER | 재사용 문서 수. 지금은 비어 있음(실행마다 새로 파싱) | 〃 | 〃 | 새로 |
| workers | INTEGER | 작업자 수 | 〃 | 〃 | 새로 |
| cpu_max_load | FLOAT | CPU 문턱값 | 〃 | 〃 | 새로 |
| mem_start_pct | FLOAT | 메모리 문턱값 | 〃 | 없음 | 새로 |

### applog.pipe_event

문서×단계 1건당 1행. 60초마다 남는 진행 상황도 `stage=run.progress`로 들어온다. 기본 키 `(id, ts_start)`. 색인: `ts_start`(BRIN) · `run_id` · `(stage, ts_start)`. `doc_id` 색인은 없다(보통 `run_id`로 먼저 좁힌다). 쓰는 곳: `common/core/span.py`(진행 상황은 `pipeline/shared/runtrace.py`). 읽는 곳: `pipeline/tools/perf_report.py`.

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
