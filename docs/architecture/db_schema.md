# DB 스키마 명세

이 프로젝트가 쓰는 DB 표와 칸 — 표마다 칸, 타입, 뜻, 쓰는 코드, 읽는 코드, 결정. 요건은 [prd/load-schema.md#pl-25](../prd/load-schema.md#pl-25).

- **결정 칸:** `유지` = 지금 있고 남김 · `삭제` = 지금 있고 없앰 · `새로` = 지금 없고 만듦. 지금 상태 = `유지`+`삭제`, 목표 상태 = `유지`+`새로`.
- **시험:** `tests/server/common/test_db_schema.py`가 gold 표(5벌 칸 합집합)와 master 표를 Alembic 모델(`common/store/db/models/`)과 비교한다. 지금 상태가 다르면 실패하고, 목표 상태와의 차이는 목록으로 찍기만 한다.
- **쓰는 곳·읽는 곳**의 괄호 안은 코드가 아니다 — `(운영자)`처럼 사람이 보는 곳이거나, 아직 코드가 없는 일이다. 코드가 없는 일은 PRD 행이 맡는다: 같은 `s3_key`의 기준 행 고르기는 [pl-32](../prd/load-schema.md#pl-32).
- **예 칸:** 값 꼴을 보여 주는 지어낸 값이다(실제 데이터 아님).

## 1. 공통 규칙

- **문서 키:** 원본 경로 하나 — gold `doc.file_path` = Object Storage 원본 경로 = EDW `FileStorageMap.s3_key`. 원본 sha256은 `doc.sha256`(원문 도구의 `doc_key`). 한 묶음 안에서 같은 내용(sha256)이 여러 원본 경로로 오면 첫 경로만 `doc` 행이 되고 나머지는 묶음 `docs.jsonl`의 `aliases`에만 남는다(적재·검색은 읽지 않음 — 둘째 경로로는 검색 결과·원문 조회가 나오지 않는다).
- **출처 표시 이름:** EDW에서도 문서 본문에서도 나올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — `_edw`·`_doc`. 지금은 고객(`client_edw`·`clients_doc`)뿐이다.
- **고객 거르기:** MCP 고객 거르기는 `doc.client_edw`(문서당 하나)만 쓴다. EDW 고객이 없는 문서(LAS 등)는 고객 거르기를 걸면 빠진다. `clients_doc`은 참고용이다.
- **원천·스키마 배치·근거 키:** [pl-28](../prd/load-schema.md#pl-28). **처리 기록(무엇을 어디에):** [pl-25](../prd/load-schema.md#pl-25). **같은 `s3_key` 여러 행:** [pl-32](../prd/load-schema.md#pl-32).
- **처리 기록:** 파싱·적재 기록은 EDW가 아니라 gold `doc` 칸(`sha256`·`silver_bucket`·`silver_key`·`engines`·`parse_status`·`silver_version`·`gold_version`·`parsed_at`·`loaded_at`)에 둔다. 끝난 문서 = 원천 스키마 어디든 `doc` 행이 있는 원본 키, 내용 중복 = 다른 원본 키의 `doc.sha256`이 같음. 적재되지 않은 문서(영구 뺌·실패)는 §6 `applog.except_doc_info`. EDW는 읽기만 한다.
- **대표 결과 주소 `rep_uri`:** 원문 도구가 `doc.silver_bucket`·`doc.silver_key`(게시한 대표 결과 객체)의 폴더를 그때 읽는다. PG를 못 읽으면 `registry_unavailable`. `search` 근거에는 `rep_uri`가 없다.
- **근거 `file_name`** = `doc.file_path`의 끝 조각.
- **원천별 EDW 사슬:** 적재가 `client_edw`·`created_at`·`attrs`를 채우는 표·칸은 사슬 파일 [`resources/config/edw_chain.yaml`](../../resources/config/edw_chain.yaml)이 정한다. 칸 이름이 실제 EDW와 같은지는 D-1·D-2.

## 2. gold — 검색 스키마 (pgvector — 원천별 스키마 5벌 + 개발 서버의 DEV 원천 스키마)

판: `common/store/db/migrations/versions/0001_search_base.py` … `0007_doc_index.py` · 모델: `common/store/db/models/search_tables.py`(`SOURCES`·`DOC_META`·`ATTRS`·`DOC_RECORD`·`DOC_INDEX`·`LOAD_ATTRS`·`CHUNK_EXTRA`) · 적재: `pipeline/load/pgvector_load.py`(`load`·`_load_src`·`deploy`) · 값 만드는 곳: `pipeline/transform/structure/gold_bundle.py`(`main`)·EDW 조인 `pipeline/load/edw_doc_meta.py`·게시 처리 기록 `pipeline/load/publish_parse_result.py`(`apply` → `publish/silver.jsonl`).

- **스키마 배치:** 기준 스키마 `<PG_SCHEMA>`(예 `ai`)에는 판 표 `alembic_version`과 공용 시퀀스 `doc_id_seq`만. 원천 스키마 `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`에 아래 표 다섯 개와 뷰 `v_chunk_source`가 같은 꼴로 있다(원천 전용 칸은 `faq.chunk.faq_group`뿐 — 그 밖의 원천 메타는 `doc.attrs` 키).
- **DEV 원천 스키마(개발 서버·PC만 — [op-17](../prd/ops.md#op-17)):** 원천 `DEV-<1~99>`(대소문자 무관)는 `<PG_SCHEMA>_dev_<숫자>`에 들어간다 — 표·뷰는 `_other`와 같고 메타가 없다(EDW 사슬 없음). 판 기록 표는 그 스키마 안(`<PG_SCHEMA>_dev_<숫자>.alembic_version`), `doc_id`는 기준 스키마의 `doc_id_seq`를 함께 쓴다. `dbtool up --target search`가 settings.yaml `required.source.source_systems`의 DEV 원천 스키마를 만들고, DB에 이미 있는 `_dev_*` 스키마도 끝 판까지 올린다(`dbtool check`도 함께 봄). 운영(prd)에는 없다.
- 검색 MCP는 실행 중에 묶음 파일(`meta.json`·`docs.jsonl`·`chunks.jsonl`)을 읽지 않는다 — 임베딩 모델·문서 날짜는 `doc` 칸, 차원은 `chunk.embedding`의 `vector(n)`에서 읽는다.

### gold.doc

| 칸 | 타입 | 예 | 뜻 | 원천 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|---|
| doc_id | INT PK | `1042` | 문서 행 번호 — 기본값 `nextval('<PG_SCHEMA>.doc_id_seq')`(5벌이 시퀀스 하나라 겹치지 않음). MCP `chunk_key` `<doc_id>:<seq>`의 앞부분 | 모두 | pgvector_load `_load_src` | 뷰, 원문 도구 쪽 넘김(`cursor`) | 유지 |
| file_path | TEXT NOT NULL | `SFDC/17ae1841-d031-48b5-85b2-2df6058b5857/kvx_rfp_main.pdf` | Object Storage 원본 경로 = EDW `FileStorageMap.s3_key`. PC 폴더 원천은 원천 폴더 기준 상대 경로(같은 꼴). 적재 건너뛰기 키·끝난 문서 키 | 모두 | gold_bundle `main` → 적재 | 뷰(`file_name` = 끝 조각), search_svc 범위, 원문 도구, 고르기 `gold_docs.done_keys` | 유지 |
| summary | TEXT | `KVX ADC 위탁생산 RFP — 2026년 2개 배치 일정·품질 요구 …` | 문서 요약 | 모두 | gold_bundle | 뷰 → 근거 | 유지 |
| created_at | TIMESTAMPTZ | `2026-10-15 09:00:00+09` | 원천 등록 시각(KST) — SFDC `ContentVersion.CreatedDate` 계열 · CRMS `RM_CM_DOCU.INIT_DTTM` · LAS `FileManager.CreateDate` · 그 밖 `FileStorageMap.created_at`(§1 원천별 사슬) | 모두 | 적재(EDW 조인 — pl-29) | `search` `created_since/until`, 원문 도구 거르기·출력·등록 시각 가드 | 유지 |
| client_edw | TEXT | `Korvexa Life Sciences` | EDW 조인 사슬의 고객 하나 — MCP 고객 거르기는 이 칸 정확 일치만 | 모두(채워지는 곳: sfdc·crms) | 적재(EDW 조인) | search_svc 범위, 근거 `client` | 유지 |
| clients_doc | TEXT | `["Korvexa Life Sciences"]` | 본문에서 찾은 고객 라벨(JSON 글자) — 참고만, 거르기·순위에 안 씀 | 모두 | gold_bundle `infer_clients` → 적재 | 없음(참고) | 유지 |
| content_date | TEXT | `2026-03-15` | 문서에 적힌 날짜(ISO 글자 `YYYY-MM-DD`·`YYYY-MM`·`YYYY` — 본문 앞 2000자 먼저, 없으면 파일 이름, `common/core/docmeta.py`. 연도만 있는 `YYYY`는 본문에서는 `2026년`처럼 날짜로 적힌 것만 — 맨 연도 숫자(예: "planned for 2027"·"2027 계획")는 안 셈, 파일 이름의 연도는 그대로 셈). `created_at`(원천 등록 시각)과 다르고, 파일 생성·수정 시각도 아니다 | 모두 | gold_bundle(`docmeta.doc_meta`의 `doc_date`) → 적재(판 0004) | pgsearch → 근거 `doc_date`(출력 이름은 그대로) — 검색 뷰엔 없음 | 유지 |
| embed_model | TEXT | `bge-m3` | 그 문서를 임베딩한 모델 이름(묶음 `meta.json` `embed_model`) | 모두 | 적재(판 0004) | pgsearch `index_meta` — 질의 모델 확인(섞이면 거부), 나중 guard(문서 단위) — 검색 뷰엔 없음 | 유지 |
| attrs | JSONB | `{"doc_class": "RFP", "sf_op_id": "006202604700000000", …}` | 원천마다 다른 문서 메타 `{키: 값}`(GIN 색인 `ix_<스키마>_doc_attrs`) — 키·EDW 칸·검색 거르기 이름·근거 표시는 사슬 파일 `edw_chain.yaml`(`fields`)이 정하고, `doc_class`는 분류가 쓴다(SFDC·LAS). 값 없는 키는 넣지 않는다. 지금 키는 아래 표(판 0005 — [pl-52](../prd/load-schema.md#pl-52)) | 모두(키는 원천마다) | 적재(EDW 조인 `edw_meta` + 분류 `doc_class`) — 판 0005 | 뷰 → `search` `attrs`·이름 있는 거르기(사슬 `filter:`)·근거 `attrs`(`evidence: true`), `list_doc_fulltext` `doc_class`·`sf_op_id`, 분류 힌트(pl-33) | 유지 |
| sha256 | TEXT | `9f2c4e…`(64자) | 원본 파일 sha256(16진 소문자) — 내용 중복 판정·원문 도구 `doc_key` | 모두 | 게시 `apply`(처리 기록) → 적재(판 0006) | 고르기 `gold_docs.done_by_sha`(다른 원본 키와 같으면 내용 중복), 원문 도구 `docs`·출력 `doc_key` | 유지 |
| silver_bucket | TEXT | `rag-publish` | 게시한 대표 결과의 버킷 | 모두 | 게시 `apply` → 적재 | 원문 도구(`rep_uri`·sfid) | 유지 |
| silver_key | TEXT | `Parsing-Result/SFDC/17ae1841-…/kvx_rfp_main_2026-11-06_013000.md` | 게시한 대표 결과(.md) 객체 키 — 그 폴더에 같은 날짜의 `.json`·`engine/` 원결과도 있다 | 모두 | 게시 `apply` → 적재 | 원문 도구(폴더 목록·등록 시각 가드) | 유지 |
| engines | JSONB | `[{"engine": "pymupdf", "role": "rep", "status": "ok", …}, {"engine": "rapidocr_ko", "role": "ocr", …}]` | 그 문서에 돈 엔진 전부(VLM·OCR 포함) — 대표 엔진은 `role` `rep` | 모두 | 게시 `engines_used` → 적재 | (운영자) | 유지 |
| parse_status | TEXT | `ok` | 파싱 상태 `ok`·`partial`(교차 정확도가 기준 미만) | 모두 | 게시 `status_of` → 적재 | 고르기 `done_by_sha` | 유지 |
| silver_version | TEXT | `0.3.0` | 대표 결과를 게시한 코드 판(`VERSION`) | 모두 | 게시 → 적재 | (운영자) | 유지 |
| gold_version | TEXT | `0.3.0+m3f9a1c2e` | 이 문서를 gold에 올린 코드 판 — `<VERSION>+m<마스터 해시 앞 8자>`(§4, 해시가 없는 묶음은 `<VERSION>`만) | 모두 | 적재 `gold_version` | (운영자) | 유지 |
| parsed_at | TIMESTAMPTZ | `2026-11-06 01:30:00+09` | 대표 결과를 게시한 시각(silver) | 모두 | 게시 `apply` → 적재 | 원문 도구 `since`·`until` 거르기 | 유지 |
| loaded_at | TIMESTAMPTZ | `2026-11-06 01:31:12+09` | gold에 적재한 시각 | 모두 | 적재 | (운영자) | 유지 |

**색인(판 0007 — `search_tables.DOC_INDEX`):** 기본 키 `doc_id` 말고는 제약이 없어(`file_path`에도 UNIQUE 없음) 찾기용 btree 색인을 둔다 — 원천 스키마마다(DEV 원천 포함), 이름 `ix_<원천 스키마>_<키>`(63바이트를 넘으면 판 올리기가 멈춤 — 기준 스키마 이름을 줄인다). 색인을 만드는 동안 그 doc에 쓰기가 막히므로 파이프라인이 돌지 않을 때 올린다.

- `ix_<스키마>_doc_sha256` (`sha256`) — 내용 중복 판정(고르기 `gold_docs.done_by_sha`), 원문 도구 `docs`의 `doc_key`(sha256)로 찾기.
- `ix_<스키마>_doc_silver` (`silver_bucket`, `silver_key`) — 게시한 대표 결과 위치로 행 찾기(원문 도구 `get_doc_fulltext`의 등록 시각 가드 — `fulltext_svc`).
- `ix_<스키마>_doc_path` (`file_path`) — 원본 경로로 찾기: 적재(재게시면 그 행만 고침 — `pgvector_load`), `--skip-done` 끝난 문서(`gold_docs.done_keys`), 원문 도구 `docs` 경로(파일 이름만 준 `LIKE '%/이름'` 찾기는 이 색인을 못 씀), `search` 범위·`attrs` 읽기.
- 그 밖: `ix_<스키마>_doc_attrs`(GIN `attrs` — 판 0005).

#### gold.doc.attrs 키(기본 사슬 파일 `resources/config/edw_chain.yaml` 기준 — 서버 사본이 바꾸면 그쪽이 맞음)

거르기 이름·근거 여부는 사슬 파일의 `filter`·`evidence`.

| 키 | 값 | 예 | 뜻 | 원천 | 읽는 곳 |
|---|---|---|---|---|---|
| `doc_class` | 글자 | `RFP` | 문서 분류 라벨 하나(SFDC: RFI/RFP/RFI+RFP/Proposal/Other, LAS: MSA/PSA/QAG/LOI/Amendment/Assignment Letter/Other) | sfdc·las | `search`·`list_doc_fulltext` 거르기 |
| `sf_op_id` | 글자 | `006202604700000000` | 영업 기회 id(18자 `006…`) — 파일 → 영업 기회 사슬로 고른 것 | sfdc | `search`·`list_doc_fulltext` 거르기 |
| `sf_op_name` | 글자 | `Korvexa Life Sciences RFP P2026047` | 영업 기회 이름(`Opportunity.Name`) | sfdc | `search` 거르기 |
| `project_code__c` | 글자 | `P2026047` | 프로젝트 코드(`Opportunity.Project_Code__c`) | sfdc | `search` `project_id` |
| `service_type` | 글자 | `CMO` | 서비스 유형(`Opportunity.Record_Type__c`) | sfdc | `search` 거르기 |
| `division` | 글자 | `DS` | 사업부(`RM_CM_PJTLIST.DIVISION`) | crms | `search` 거르기 |
| `prod_name` | 글자 | `LXT204 공정 이전` | 제품·계약 이름(`RM_CM_PJTLIST.RM_CONTRACT_NAME`) | crms | 없음(근거 메타) |
| `contract_id` | 글자 | `CT-2026-0101` | 계약 번호 — CRMS `rm_contract_code` · LAS `manage_no`(없으면 `Contract.ContractID`) | crms·las | `search` 거르기 |
| `contract_date` | 날짜 글자(YYYY-MM-DD) | `2026-03-15` | 계약일 — SFDC `Opportunity.X1st_Contract_Execution_Date__c` · CRMS `RM_CM_PJTLIST.INIT_DTTM` · LAS `Contract.ContractDate`(없으면 `FileStorageMap_LAS.signed_date`) | sfdc·crms·las | 없음(근거 메타) |
| `title` | 글자 | `KVX_RFP_2025` | 분류 힌트 — 파일 제목(`ContentVersion.Title`). 비면 분류 지시문은 원본 파일 이름 | sfdc | 분류 |
| `entity_type` | 글자 | `Opportunity` | 분류 힌트 — 첫 User 아닌 연결 개체 종류(`ContentDocumentLink.LinkedEntityId` 앞 3자 → `resources/mappings/sfdc_prefix.json`, 표에 없으면 `Unknown:<접두>`) | sfdc | 분류 |
| `entity_class` | 글자 | `opportunity` | 분류 힌트 — 개체 갈래(운영 analyze_clues 그대로): 연결 없음 `unlinked` · 모두 User면 `user_only` · 아니면 개체 종류의 갈래(if_log·event_log·task·event·quote·opportunity·account·contract·dashboard·organization, 그 밖 other) | sfdc | 분류 |
| `entity_id` | 글자 | `006202604700000000` | 분류 힌트 — 그 연결 개체 id(`LinkedEntityId`) | sfdc | 분류 |
| `sent_received__c` | 글자 | `Received` | 분류 힌트 — 연결 개체가 Task/Event일 때 방향(`Sent_Received__c`) | sfdc | 분류 |
| `subject` | 글자 | `RE: KVX RFP 질의 회신` | 분류 힌트 — 연결 개체가 Task/Event일 때 제목(`Subject` 앞 120자) | sfdc | 분류 |
| `stagename` | 글자 | `Proposal` | 분류 힌트 — 연결 개체가 영업 기회 자체일 때 단계(`Opportunity.StageName` — 사슬이 고른 기회가 아님) | sfdc | 분류 |
| `real_rfp__c` | 글자 | `1` | 분류 힌트 — 같은 기회의 `Real_RFP__c`(글자 '1'/'0') | sfdc | 분류 |
| `rfp_received_start_date__c` | 날짜 글자(YYYY-MM-DD) | `2026-02-01` | 분류 힌트 — 같은 기회의 `RFP_Received_Start_Date__c` | sfdc | 분류 |
| `rfp_received_end_date__c` | 날짜 글자(YYYY-MM-DD) | `2026-02-28` | 분류 힌트 — 같은 기회의 `RFP_Received_End_Date__c` | sfdc | 분류 |
| `approvalname` | 글자 | `LXT204 품질 계약(QAG) 체결 품의` | 분류 힌트 — 품의 제목(`LAS.Contract.ApprovalName`, 최신 판) | las | 분류 |

### gold.chunk

| 칸 | 타입 | 예 | 뜻 | 원천 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|---|
| chunk_id | SERIAL PK | `58213` | 청크 행 번호(스키마마다) | 모두 | pgvector_load | pgsearch(후보·BM25·뷰) | 유지 |
| doc_id | INT FK→doc | `1042` | 문서 — 청크가 갖는 문서 키는 이것뿐 | 모두 | pgvector_load | 조인 전부 | 유지 |
| seq | INT NOT NULL | `7` | 문서 안 순번 — `chunk_key` 뒷부분 | 모두 | pgvector_load | 뷰 → 근거 | 유지 |
| page | INT | `3` | 쪽 | 모두 | pgvector_load | 뷰 → 근거 `page` | 유지 |
| line_start | INT | `41` | 시작 줄 | 모두 | pgvector_load | 뷰 → 근거 `line` | 유지 |
| line_end | INT | `58` | 끝 줄 | 모두 | pgvector_load | 뷰 → 근거 `line` | 유지 |
| bbox | VARCHAR(80) | `72,140,523,388` | 쪽 안 위치 x0,y0,x1,y1(pt) 하나 | 모두 | pgvector_load | 뷰 | 유지 |
| section | TEXT | `3. Manufacturing Scope` | 절 제목 | 모두 | pgvector_load | 뷰 → 근거 `section` | 유지 |
| chunk_text | TEXT NOT NULL | `The sponsor requests two GMP batches of LXT204 …` | 청크 본문 | 모두 | pgvector_load | 뷰 → 근거 `text` | 유지 |
| n_terms | INT NOT NULL | `186` | 토큰 수 — BM25 길이 정규화(dl) | 모두 | pgvector_load | pgsearch BM25, `corpus_stat` | 유지 |
| embedding | vector(n) | `[0.012, -0.034, …]`(1024개) | L2 정규화 임베딩(HNSW 코사인 · 2,000차원 넘으면 이진 양자화 HNSW) | 모두 | pgvector_load | pgsearch `vector_top` | 유지 |
| faq_group | TEXT | `품질·QA` | FAQ 시트 이름(`FAQ_group`) | faq | FAQ 적재(`gold_bundle`) | `search` `FAQ_group` 거르기 | 유지 |

### gold.chunk_term

왜 필요한가: `mcp_server/services/search/pgsearch.py` `search`의 BM25가 질의마다 청크별 단어 빈도(tf)를 이 표에서 읽는다(드문 ID 검색의 문서 수 셈도 이 표). 원천 스키마마다 하나.

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| term | TEXT | `lxt204` | 토큰(PK 일부) | pgvector_load(COPY) | pgsearch BM25·ID | 유지 |
| chunk_id | INT | `58213` | 청크(PK 일부) | pgvector_load | pgsearch | 유지 |
| tf | SMALLINT | `3` | 그 청크 안 단어 빈도 | pgvector_load | pgsearch BM25 | 유지 |

### gold.term_stat

왜 필요한가: `pgsearch.py` BM25의 IDF — 단어마다 그 단어가 든 청크 수(df)를 질의 때 다시 세지 않게 둔다. 원천 스키마마다 하나(원천끼리 점수를 섞지 않음).

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| term | TEXT PK | `lxt204` | 토큰 | pgvector_load | pgsearch BM25 | 유지 |
| df | INT | `27` | 문서(청크) 빈도 | pgvector_load(늘리기)·`drop_terms`(줄이기) | pgsearch BM25 | 유지 |

### gold.corpus_stat

왜 필요한가: `pgsearch.py` BM25의 전체 청크 수(N)와 평균 길이(avgdl) — 한 행(검색마다 읽음 — 없으면 검색마다 청크 표 전체를 세야 함).

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| id | SMALLINT PK | `1` | 늘 1 | pgvector_load | pgsearch | 유지 |
| n_chunks | INT | `48210` | 청크 수 N | pgvector_load | pgsearch BM25 | 유지 |
| avg_len | DOUBLE | `171.4` | 평균 n_terms(avgdl) | pgvector_load | pgsearch BM25 | 유지 |

뷰 `v_chunk_source`는 `chunk`↔`doc`을 이은 읽기 전용 뷰다(원천 스키마마다 — 칸 = 청크 칸 + `file_name`(= `file_path` 끝 조각) + 그 원천의 doc 칸 + (faq) `faq_group`). 모델 `view_columns(원천)`(칸 순서)·`view_sql(원천)`(정의 글자)이 비교 기준이다.

## 3. EDW (MSSQL)

접속: `common.connections.rdb` 읽기 계정 `rdb.read` — 이 프로젝트는 EDW에 쓰지 않는다(처리 기록은 §2 gold `doc`).

EDW 표(`AI.FileStorageMap`, 원천 표 SFDC·CRMS·LAS 등)는 서버에서 운영하는 표라 이 문서에 칸 명세를 두지 않는다. 이 프로젝트가 읽는 표·칸·잇는 키는 사슬 파일 [`resources/config/edw_chain.yaml`](../../resources/config/edw_chain.yaml)(서버 사본은 코드 폴더의 `edw_chain.yaml`)이 정하고, 그 값이 §2 gold `doc`의 `client_edw`·`created_at`·`attrs`로 매핑된다. 파싱 대상은 `AI.FileStorageMap`에서 고른다(원천 = `source_system` 칸 — [op-17](../prd/ops.md#op-17)). PC 대역 정의는 `valid_env/edw/*.sql`에 있다.

## 4. master — 마스터 표 (검색 PG, 스키마 `<PG_SCHEMA>_master`)

원본은 git CSV `resources/vocab/glossary/glossary.csv`(샘플 데이터). 실행 중에는 이 표만 읽는다 — `dbtool up --target master`로 표를 만들고 `dbtool master load`가 CSV로 내용을 한 트랜잭션에 통째로 바꾼다(초기화 순서: `dbtool up`(search·applog·master) → `dbtool master load`). 칸은 CSV 머리글 그대로(모두 `TEXT`) + 파일 순서 `row_no`(`INTEGER`, 기본 키). 머리글을 바꾸면 새 Alembic 판(갈래 `master`). 판: `common/store/db/migrations/versions/0001_master_base.py`(옛 표 여섯 개 + `master_meta`) → `0002_master_glossary.py`(`glossary`를 만들고 옛 표 일곱 개를 지움 — 내용의 원본은 git CSV라 잃는 것 없음) · 모델: `common/store/db/models/master_tables.py` · 읽기·채우기: `common/store/master.py`(프로세스마다 한 번 — 못 읽으면 멈춤, PC도 같음). `tests/server/common/test_db_schema.py`가 이 절의 칸을 모델과 대조한다.

- **해시·판:** 마스터 해시 = 머리글·`row_no` 순서 `glossary` 행의 sha256(16진 64자) — 읽을 때 계산한다(해시를 적어 두는 표 없음). 구조화가 읽은 마스터 해시를 묶음 `meta.json` `master_hash`에 남기고 적재가 gold `doc.gold_version` = `<VERSION>+m<해시 앞 8자>`로 쓴다(`master_hash`가 없는 묶음은 `<VERSION>`만). `silver_version`에는 붙이지 않는다. 마스터 해시는 캐시 열쇠·code_fp에 없다 — 마스터가 바뀌어도 자동 전체 재처리는 없고 `gold_version`으로 추적한다.
- **읽는 모양:** `common.store.master`가 `glossary` 줄을 파일 순서로 묶어(고객·용어·ID 꼴 하나는 머리 줄(`client_id`·`concept_id`·`regex`)에서 시작하고, 바로 뒤따르는 같은 `kind`·`canonical` 줄이 거기에 붙는다(이름이 같은 고객 둘·이름이 빈 고객도 따로, ID 꼴은 `regex` 줄마다 하나 — `example`·`updated`는 그 앞 `regex` 줄 것)) `common.core.terms`가 읽는 행 모양(고객 명부·용어 사전·ID 꼴 — 칸 이름 `common.store.master.SHAPES`)으로 되돌려 넘긴다. 모르는 `kind`·`variant_kind`, 머리 줄 없이 나온 줄, 값이 하나인 종류가 한 묶음에 두 줄이면 `master load`가 표를 바꾸지 않고 거부한다(읽을 때도 같은 검사).
- **파일로 남는 것:** `client_master.example.csv`·`client_master_map.example.json`(명부 도구 `gen_roster` 입력·예시 — 출력은 `glossary.csv` 고객 줄) · `client_roster_seed.json`(주요 바이오·제약사 공개 이름 seed — 구조화 `infer_clients`가 파일로 읽음).

### master.glossary

고객 명부·용어 사전·ID 꼴을 합친 표 — melt 꼴(유사값마다 한 줄). 읽는 곳: `common.core.terms` `_aliases`(구조화 고객 판별 `infer_clients` · 검색 질문 고객·별칭) · `load_glossary`(검색 질문 넓히기·근거 상태·고객 별칭의 `org_client`) · `validate_glossary`(ID 꼴 정규식 검사 — 매칭에 쓰는 앱 코드는 없음).

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| row_no | INTEGER PK | `1` | CSV 파일 순서(1부터) | `dbtool master load` | 읽기 순서(ORDER BY) | 새로 |
| kind | TEXT | `term` | 구분 — `client`(고객)·`term`(용어)·`id`(ID 꼴) | `dbtool master load` | `common.store.master.to_tables` | 새로 |
| canonical | TEXT | `Contract Manufacturing Organization` | 원본 값 — 고객은 정식 이름(빈칸이면 `name_ko` 줄이 이름), 용어는 표준 이름, ID는 종류(`contract_no`·`product_code` 등). 묶는 법은 위 "읽는 모양" | 〃 | 〃 | 새로 |
| variant | TEXT | `위탁생산` | 유사값 — `variant_kind`가 정하는 값(별칭·동의어·정규식·참조 ID·속성 값) | 〃 | 〃 | 새로 |
| variant_kind | TEXT | `synonym` | 유사 종류. client: `client_id`·`name_ko`·`alias`(여러 줄)·`client_type`·`segment`·`country`·`parent`·`status`(`inactive`·`deleted`면 건너뜀)·`source`·`updated` · term: `concept_id`·`synonym`·`abbr`·`weak`(약한 동의어)·`broader`·`related`(개념 ID)·`category`(여러 줄 — `org_client`면 고객 명부에도)·`definition_en`·`source`·`owner`·`status`(approved만 씀)·`updated` · id: `regex`(머리 줄 — 줄마다 한 꼴)·`example`·`updated`. 여러 줄이 되는 것은 `alias`·`synonym`·`abbr`·`weak`·`broader`·`related`·`category`·`regex`, 나머지는 한 줄 | 〃 | 〃 | 새로 |
| description | TEXT | `고객이 확립한 공정으로 생산만 위탁 수행` | 설명 — `client_id` 줄은 고객 설명, `concept_id` 줄은 한글 정의, `regex` 줄은 메모. 다른 줄은 비움 | 〃 | 〃 | 새로 |
| context_required | TEXT | `생산\|제조\|계약` | 용어의 문맥 필요 — 동음이의 줄임말이면 질문에 함께 나와야 하는 말(`\|` 구분). term만(변환본은 `concept_id` 줄) | 〃 | `mcp_server.services.search.query_expand`(질문 넓히기) | 새로 |
| case_sensitive | TEXT | `N` | 용어의 대소문자 구분 — `Y`면 구분. term만(변환본은 `concept_id` 줄) | 〃 | 〃 | 새로 |

## 5. DB 담당자 확인 필요

번호 D-3·D-4·D-5·D-7·D-9는 비어 있다(다른 문서가 번호로 가리켜서 다시 매기지 않음).

| # | 무엇 | 왜 |
|---|---|---|
| D-1 | `AI.FileStorageMap`의 실제 정의 — `created_at`이 있는지(같은 `s3_key` 중 가장 늦은 행을 이 칸으로 고름), 원천별 등록 시각(SFDC `ContentVersion.CreatedDate`, CRMS `RM_CM_DOCU.INIT_DTTM`, LAS `FileManager.CreateDate`)과 같은 값인지 · 원천 id 칸의 실제 이름 · SFDC Quote 표의 실제 이름·칸과 `OpportunityId` 연결 | 저장소에는 PC 대역(`valid_env/edw/ai.sql`)뿐 |
| D-2 | `client_edw`·원천 메타를 얻는 사슬(`resources/config/edw_chain.yaml`)의 표·칸 이름이 실제 EDW와 같은지 | 적재가 EDW 읽기 계정으로 직접 조인한다 — 칸 이름은 운영 노트 기준(refactor.md C-76) · LAS 고객은 상대사 출처가 정해질 때까지 비움 |
| D-6 | 원천별 gold 스키마 5벌 + 기준 스키마의 공용 `doc_id_seq`(§2) — 기존 서버 데이터는 백업 뒤 다시 적재 | 첫 적재가 전체 e2e와 함께 · refactor.md C-74·C-76 |
| D-8 | FAQ 원천 등록 — Object Storage `FAQ/<uuid>/<파일>`을 `AI.FileStorageMap`에 등록(candidate_pick list는 `s3_key LIKE 'FAQ/%'`로 고름) | FAQ 행을 누가 어떻게 넣나 |
| D-10 | `applog` 스키마 추가(§6) — `up`의 `CREATE SCHEMA`, `maintain`의 파티션 생성·DROP, 앱의 INSERT와 `pipe_run` UPDATE 권한. 호출량 기준 용량(`mcp_log` 행 본문 최대 약 80KB) | 새 스키마이고 로그 쓰기가 기존 PG 접속 정보를 함께 씀 |
| D-11 | `applog.mcp_log`의 `args`·`result` 읽기 권한 분리 | 문서 본문·EDW 결과가 들어가는데(`get_doc_fulltext` 응답은 문서 원문 전체) 판에 GRANT가 없어 지금은 앱 계정이 읽을 수 있음 |
| D-12 | 실제 보존 기간 약 90~120일(월 단위 DROP)이 감사·개인정보 기준에 맞는지, `dbtool maintain` 매일 예약 | 예약이 약 2개월 이상 멈추면 새 달 파티션이 없어 DB 쓰기가 실패하고 대체 파일로만 쌓임 |

## 6. applog — 로그 저장소 (pgvector PG, 스키마 `applog`)

gold·EDW와 별개인 로그 표다. 서버 적용 절차는 refactor.md C-79.

판: `common/store/db/migrations/versions/0001_applog_base.py`(브랜치 `applog`)·`0002_applog_skip.py`·`0003_applog_except.py`(`except_doc_info` — 옛 `skip_doc_info` 행을 `skip`으로 옮김)·`0004_applog_docs.py`(`pipe_event.source_system`·`except_doc_info`의 확장자·크기 칸)·`0005_applog_dlq.py`(`dlq_doc` — 재시도 상태) · 파티션 관리: `common/store/db/migrations/applog_parts.py` · 모델: `common/store/db/models/log_tables.py` · 쓰기: `common/store/logsink.py`(큐 → 배치 INSERT, 실패하면 `output/logs/*.jsonl`, 앱이 DDL을 실행하지 않음). 켜는 설정: 파일 자리 `ops.log.log_db_enabled`(모델 `ops.log.log_db_enabled`, 서버 이미지 기본 켬·PC 기본 꺼짐 — op-13). `tests/server/common/test_db_schema.py`는 이 절을 대조하지 않는다 — DB 판 확인은 `dbtool check --target applog`.

- **파티션:** `mcp_log`(`requested_at`)·`pipe_event`(`ts_start`)는 월 단위(UTC). 이름은 `<표>_YYYYMM`. `dbtool up`과 `dbtool maintain`이 현재 달부터 3개월 치를 만든다.
- **보존:** `dbtool maintain --target applog`를 매일 실행한다. `ops.log.log_retention_days`(기본 90)가 지난 달의 파티션을 DROP하고 `pipe_run`과 보존 기간이 지난 `dlq_doc` resolved 행은 DELETE한다(pending·dead는 보존). 달이 통째로 지나야 DROP되므로 파티션 표의 행은 약 90~120일 남는다.
- **되돌리기:** `downgrade`는 막혀 있다. 지우려면 DB 담당자가 직접 한다.
- **연결:** `pipe_event.run_id` → `pipe_run.run_id`는 외래 키가 없다(지우는 시점이 달라 짝 없는 행이 생길 수 있음). 파티션 표의 `id`는 기본 키가 시각과 묶여 있어 그것만으로는 고유하지 않다.
- **기록하지 않는 값:** MCP `clientInfo`(`args`에서도 뺌). 접속 IP는 `mcp_log.client_ip`에 남긴다.

### applog.mcp_log

MCP 요청 1건당 1행. 인증 실패와 `initialize`도 행으로 남는다. 기본 키 `(id, requested_at)`. 색인: `requested_at`(BRIN) · `(agent_id, requested_at)` · `(session_id, requested_at)` · `(knox_id, requested_at)` · `(tool_name, requested_at)` · `request_id`. 쓰는 곳: `mcp_server/services/call_log.py`(내부 행을 `_columns`가 이 칸 이름으로 바꿈). 읽는 코드는 없다(감사 조회용). 질의 기록은 이 표뿐이다(`args`에 질문·SQL — 파일 기록 없음, op-13). 이 표는 이전 이름 `mcp_call`에 인증·권한 설계안(DBML: `agent`·`agent_api_key`·`source`·`agent_source_mapping`)의 칸을 합친 것이다. 그 표들은 아직 없어서 `agent_id`·`api_key_id`는 FK 없이 자리만 있다.

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| id | BIGSERIAL | `120394` | 일련번호(PK 일부) | DB | 없음 | 새로 |
| request_id | UUID | `7c1e2f4a-9b3d-4e5f-8a6b-1c2d3e4f5a6b` | 요청 ID(`X-Request-Id`, 없으면 서버가 만듦) — `qa_log`와 연결 | call_log | 없음 | 새로 |
| session_id | VARCHAR(128) | `a3f9c2e17b4d4f0e9c8b7a6d5e4f3c2b` | `Mcp-Session-Id`. 없으면 NULL | 〃 | 없음 | 새로 |
| turn_id | VARCHAR(128) | `NULL` | 대화 턴 ID. 아직 채우는 코드 없음 | (없음) | 없음 | 새로 |
| agent_id | SMALLINT | `NULL` | 인증된 Agent. `agent` 표가 생기면 FK 추가, 그 전까지 NULL | (없음) | 없음 | 새로 |
| api_key_id | INTEGER | `NULL` | 요청에 쓴 API 키. `agent_api_key` 표가 생기면 `agent_api_key.id` FK 추가, 그 전까지 NULL. 키 문자열은 로그에 남기지 않음. 아직 채우는 코드 없음 | (없음) | 없음 | 새로 |
| knox_id | VARCHAR(64) | `tester01` | `X-MCP-User`, 없으면 `_meta.user`(자기 신고 값, 검증 안 함) | call_log | 없음 | 새로 |
| requested_at | TIMESTAMPTZ NOT NULL | `2026-10-15 05:12:03.418+00` | 호출 시각(기본 now, 파티션 키) | 〃 | 없음 | 새로 |
| finished_at | TIMESTAMPTZ | `2026-10-15 05:12:04.902+00` | 끝난 시각 | 〃 | 없음 | 새로 |
| duration_ms | INTEGER | `1484` | 걸린 시간 | 〃 | 없음 | 새로 |
| queue_wait_ms | INTEGER | `3` | 실행 전 대기 시간 | 〃 | 없음 | 새로 |
| rpc_method | VARCHAR(32) CHECK | `tools/call` | initialize·tools/list·tools/call. 인증 거부 행은 본문을 읽기 전이라 NULL. 지금 `tools/list`는 기록하지 않음 | 〃 | 없음 | 새로 |
| tool_name | VARCHAR(64) | `search` | `tools/call`일 때만 도구 이름 | 〃 | 없음 | 새로 |
| status | VARCHAR(16) CHECK | `ok` | ok·error·denied·unauthorized·busy·timeout. `denied`는 권한 설계 전이라 아직 안 씀 | 〃 | 없음 | 새로 |
| error_code | VARCHAR(64) | `NULL` | `tool_timeout`·`busy`·`invalid_key`·`tool_error`·`audit_queue_full` | 〃 | 없음 | 새로 |
| error_message | TEXT | `NULL` | 오류 내용(비밀값 가림) | 〃 | 없음 | 새로 |
| args | TEXT | `{"query": "KVX LXT204 배치 일정", "top_k": 8}` | 입력 JSON 앞부분(`tuning.search.audit.audit_max_input_bytes`, 기본 16KB). 비밀값 가림. `content_b64`는 해시와 크기로 바꿈 | 〃 | 없음 | 새로 |
| args_bytes | INTEGER | `58` | 입력 원본 크기 | 〃 | 없음 | 새로 |
| args_truncated | BOOLEAN | `false` | 입력이 잘렸는지. 잘리면 JSON으로 안 읽힐 수 있음 | 〃 | 없음 | 새로 |
| result | TEXT | `{"evidence": [{"chunk_key": "1042:7", …}], …}` | 출력 JSON 앞부분(`tuning.search.audit.audit_max_output_bytes`, 기본 64KB). 문서 본문·EDW 결과 포함 가능 | 〃 | 없음 | 새로 |
| result_bytes | INTEGER | `18342` | 출력 원본 크기 | 〃 | 없음 | 새로 |
| result_truncated | BOOLEAN | `false` | 출력이 잘렸는지 | 〃 | 없음 | 새로 |
| result_sha256 | CHAR(64) | `5d1e9a07…`(64자) | 출력 원본 전체의 해시 | 〃 | 없음 | 새로 |
| result_keys | JSONB | `{"chunk_keys": ["1042:7", "1042:8"], "evidence_status": "ok"}` | 자르지 않는 응답 식별 정보(search `chunk_keys`, 원문 도구 `doc_keys`·파일 요약, `row_count` 등) | 〃 | 없음 | 새로 |
| result_count | INTEGER | `NULL` | 돌려준 근거 수·행 수. 아직 채우는 코드 없음(`result_keys`에 있음) | (없음) | 없음 | 새로 |
| client_ip | INET | `192.0.2.10` | 접속 소켓 주소(프록시 뒤면 프록시 IP). stdio는 NULL | call_log | 없음 | 새로 |
| app_version | VARCHAR(32) | `0.2.0` | 앱 버전 | 〃 | 없음 | 새로 |

`session_id`·`knox_id`·`tool_name`·`app_version`은 길이를 넘으면 `call_log._columns`가 자른다(넘으면 배치 INSERT가 통째로 실패해 파일 대체 기록으로 간다).

과부하로 감사 대기열이 차면 `args`·`result` 없는 행이 남고(`error_code=audit_queue_full`), 기록기 큐까지 차면 행 없이 건수로만 집계된다(호출 1건 = 1행의 예외, 사용자 11-01).

### applog.pipe_run

파이프라인 실행 1건당 1행. 기본 키 `run_id`. 색인: `started_at`. 시작할 때 `status=running`으로 쓰고 끝날 때 같은 `run_id`로 덮어쓴다(UPSERT — 이 표만). 강제 종료된 실행은 `running`으로 남는다. 쓰는 곳: `pipeline/shared/runtrace.py`. 읽는 곳: `pipeline/tools/perf_report.py`.

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| run_id | UUID PK | `0f6b2c9e-4d1a-4c3b-9e8f-7a6b5c4d3e2f` | 실행 ID | runtrace | perf | 새로 |
| command | TEXT | `parse` | 명령 | 〃 | 〃 | 새로 |
| args | TEXT | `parse --workers 4` | 인자(비밀값 가림) | 〃 | 없음 | 새로 |
| started_at | TIMESTAMPTZ NOT NULL | `2026-10-15 00:00:05+00` | 시작 시각(기본 now) | 〃 | perf | 새로 |
| ended_at | TIMESTAMPTZ | `2026-10-15 00:42:17+00` | 끝 시각 | 〃 | 없음 | 새로 |
| duration_ms | INTEGER | `2532140` | 걸린 시간 | 〃 | perf | 새로 |
| status | TEXT | `ok` | 실행 상태(CHECK 없음) | 〃 | 〃 | 새로 |
| host | TEXT | `pipeline-host-01` | 서버 이름 | 〃 | 없음 | 새로 |
| pid | INTEGER | `48211` | 프로세스 ID | 〃 | 없음 | 새로 |
| app_version | TEXT | `0.2.0` | 앱 버전 | 〃 | perf | 새로 |
| run_env | TEXT | `dev` | 실행 환경 | 〃 | 〃 | 새로 |
| code_fp | JSONB | `{"p0": "a1b2c3d4e5f6", "p1": "…", "r": "…", "s": "…"}` | 레이어별 code_fp(DB 기록이 켜졌을 때만 계산) | 〃 | 〃(실행 비교) | 새로 |
| stack | TEXT | `dev-v1` | 스택 이름 | 〃 | 〃 | 새로 |
| settings_hash | TEXT | `9c4e2a7b1d03` | 설정 해시(DB 기록이 켜졌을 때만 계산) | 〃 | 〃 | 새로 |
| docs_total | INTEGER | `120` | 문서 수 | 〃 | 〃 | 새로 |
| docs_ok | INTEGER | `117` | 성공 문서 수 | 〃 | 〃 | 새로 |
| docs_fail | INTEGER | `3` | 실패 문서 수 | 〃 | 〃 | 새로 |
| docs_reused | INTEGER | `NULL` | 재사용 문서 수. 지금은 비어 있음(실행마다 새로 파싱) | 〃 | 〃 | 새로 |
| workers | INTEGER | `4` | 작업자 수 | 〃 | 〃 | 새로 |
| cpu_max_load | FLOAT | `0.8` | CPU 문턱값 | 〃 | 〃 | 새로 |
| mem_start_pct | FLOAT | `23.5` | 실행 시작 때 메모리 사용률(%) | 〃 | 없음 | 새로 |

### applog.pipe_event

문서×단계 1건당 1행. 60초마다 남는 진행 상황도 `stage=run.progress`로 들어온다. 기본 키 `(id, ts_start)`. 색인: `ts_start`(BRIN) · `run_id` · `(stage, ts_start)`. `doc_id` 색인은 없다(보통 `run_id`로 먼저 좁힌다). 쓰는 곳: `common/core/span.py`(진행 상황은 `pipeline/shared/runtrace.py`). 읽는 곳: `pipeline/tools/perf_report.py`.

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| id | BIGSERIAL | `904112` | 일련번호(PK 일부) | DB | 없음 | 새로 |
| ts_start | TIMESTAMPTZ NOT NULL | `2026-10-15 00:03:11+00` | 시작 시각(기본 now, 파티션 키) | span | perf | 새로 |
| ts_end | TIMESTAMPTZ | `2026-10-15 00:03:19+00` | 끝 시각 | 〃 | 〃 | 새로 |
| run_id | UUID | `0f6b2c9e-4d1a-4c3b-9e8f-7a6b5c4d3e2f` | 실행 ID | 〃 | 〃 | 새로 |
| span_id | UUID | `2b7d…`(UUID) | 단계 ID | 〃 | 없음 | 새로 |
| parent_id | UUID | `NULL` | 부모 단계 ID | 〃 | 없음 | 새로 |
| layer | TEXT | `extract` | 레이어(extract·transform·load 등) | 〃 | perf | 새로 |
| stage | TEXT | `extract.parse` | 단계(`extract.parse`, `run.progress` 등) | 〃 | 〃 | 새로 |
| engine | TEXT | `pymupdf` | 엔진 | 〃 | 〃 | 새로 |
| model | TEXT | `NULL` | 모델 | 〃 | 없음 | 새로 |
| attempt | INTEGER | `1` | 시도 번호(1부터, 시간 초과로 다시 돌면 2 — `extract.parse`만 채움) | 〃 | 없음 | 새로 |
| doc_id | TEXT | `kvx_rfp_main.pdf` | 문서 ID | 〃 | perf | 새로 |
| ext | TEXT | `.pdf` | 확장자(소문자, 점 포함) — 문서 사건에서 span이 안 주면 `doc_id` 이름에서 | 〃 | 없음 | 새로 |
| file_bytes | BIGINT | `448556` | 파일 크기(바이트) — 문서 사건에서 span이 안 주면 이번 실행 manifest `size` | 〃 | 없음 | 새로 |
| seq | INTEGER | `17` | 실행 안에서 몇 번째 | 〃 | perf | 새로 |
| total | INTEGER | `120` | 전체 개수 | 〃 | 〃 | 새로 |
| duration_ms | INTEGER | `8120` | 전체 시간 | 〃 | 〃 | 새로 |
| wait_mem_ms | INTEGER | `0` | 메모리 문 대기 | 〃 | 〃 | 새로 |
| wait_cpu_ms | INTEGER | `250` | CPU 문 대기 | 〃 | 〃 | 새로 |
| cpu_ms | INTEGER | `6930` | CPU 시간(회수된 자식 포함). 다른 단계와 겹쳐 정확히 못 재면 NULL | 〃 | 〃 | 새로 |
| ext_call_ms | INTEGER | `0` | 외부 모델 호출 시간의 합. 병렬 호출은 더해지므로 `duration_ms`보다 클 수 있음 | 〃 | 없음 | 새로 |
| rss_peak_mb | FLOAT | `412.6` | 최대 메모리 | 〃 | perf | 새로 |
| load1_per_cpu_start | FLOAT | `0.42` | 시작 때 코어당 부하 | 〃 | 없음 | 새로 |
| load1_per_cpu_end | FLOAT | `0.61` | 끝날 때 코어당 부하 | 〃 | 없음 | 새로 |
| mem_used_pct | FLOAT | `38.2` | 메모리 사용률(`/proc` 없는 macOS는 빔) | 〃 | 없음 | 새로 |
| inflight | INTEGER | `3` | 같은 단계에서 동시에 돌던 작업 수 | 〃 | 없음 | 새로 |
| metrics | JSONB | `{"pages": 12, "chunks": 34}` | 단계별 지표(쪽 수, 청크 수, 캐시 적중, 표별 적재 행 수 등) | 〃 | perf | 새로 |
| status | TEXT CHECK | `ok` | ok·fail·timeout·skip·reused | 〃 | 〃 | 새로 |
| err_kind | TEXT CHECK | `NULL` | env·timeout·doc·external·db | 〃 | 〃 | 새로 |
| err | TEXT | `NULL` | 예외 타입과 고정 문구만. 외부 예외 원문은 저장 안 함 | 〃 | 없음 | 새로 |
| app_version | TEXT | `0.2.0` | 앱 버전 | 〃 | perf | 새로 |
| source_system | TEXT | `SFDC` | 원천 — 문서 사건(`doc_id` 있음)만, 이번 실행 manifest의 그 문서 행(applog를 여러 벌이 함께 써서 행만 보고 원천을 알게 — 판 0004) | 〃 | 없음 | 새로 |

### applog.except_doc_info

gold에 적재되지 않은 원본 1개·종류 1개당 1행(op-17). 기본 키 (`source_key`, `except_type`). 일반 표(파티션·보존 DELETE 없음 — `skip` 행을 지우면 그 문서를 다시 고름). 판: `common/store/db/migrations/versions/0003_applog_except.py`·`0004_applog_docs.py`(`file_ext`·`file_size`). 쓰는 곳: `pipeline/shared/except_docs.py` — `record()`(`skip`: 받기 전 `candidate_pick._record_source_skipped`·받은 뒤 `candidate_ready._record_filtered`·내용 중복 `candidate_ready._dedup`)·`record_error()`(`error`: 게시의 파싱 실패·적재의 분류 실패·run_pipeline의 파싱·게시·적재 실패 — `except_docs error` 명령). 같은 키·종류면 `last_seen`·`count`만 갱신. 읽는 곳: `candidate_pick.list_targets`(`--skip-done`이면 `skip` 키를 뺌 — `error` 행 자체는 빼지 않으며, 별도 DLQ 상태(pl-69)의 dead만 제외, pending은 다음 실행 본 흐름에서 다시 시도).

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| source_key | TEXT PK | `SFDC/2a9c…/kvx_drm_copy.pdf` | 원본 키(Object Storage `s3_key`, 폴더 원천은 상대 경로·이름) | except_docs | candidate_pick | 새로 |
| except_type | TEXT PK | `skip` | 종류 — `skip`(영구 뺌: 지원 안 하는 확장자·확장자 없음·DRM·암호·내용 중복) · `error`(파싱·적재 실패 — 기록만) · `part`(수준 `warn` — 안 문서를 일부 못 꺼냄, 성한 안 파일은 적재됨 — 기록만, pl-65) · `silver`(수준 `warn` — 실버만 게시, 골드 적재가 성공하면 지움, pl-68) | 〃 | candidate_pick(`skip`만) | 새로 |
| source_system | TEXT | `SFDC` | 원천(FileStorageMap `source_system`) | 〃 | 없음 | 새로 |
| file_name | TEXT | `kvx_drm_copy.pdf` | 파일 이름 | 〃 | 없음 | 새로 |
| reason | TEXT NOT NULL | `drm_fasoo` | 이유 — `skip`: `unsupported_archive`·`encrypted_archive`·`broken_archive`·`archive_too_big`·`unsupported_format`·`no_extension`·`drm_*`·`encrypted_*`·`duplicate_sha256` · `error`: `parse_failed`·`publish_failed`·`load_failed`·`classify_failed` | 〃 | 없음 | 새로 |
| level | TEXT NOT NULL | `error` | 수준(기본 `error`) | 〃 | 없음 | 새로 |
| first_seen | TIMESTAMPTZ NOT NULL | `2026-10-14 15:02:11+00` | 처음 기록한 시각(기본 now) | 〃 | 없음 | 새로 |
| last_seen | TIMESTAMPTZ NOT NULL | `2026-10-15 15:01:47+00` | 마지막으로 기록한 시각(기본 now) | 〃 | 없음 | 새로 |
| count | INTEGER NOT NULL | `2` | 기록한 횟수(기본 1) | 〃 | 없음 | 새로 |
| file_ext | TEXT | `pdf` | 확장자(소문자, 점 없음 — `file_name`에서, 판 0004) | 〃 | 없음 | 새로 |
| file_size | BIGINT | `448556` | 파일 크기(바이트 — 문서 위치 표·manifest의 `file_size`, 모르면 NULL — 판 0004) | 〃 | 없음 | 새로 |

### applog.dlq_doc

실패 문서 재시도 상태([pl-69](../prd/load.md#pl-69)), 원본 키당 한 행. 판 `0005_applog`, 고정 DDL `0005_applog_dlq.py`. 일반 표이며 색인 `ix_dlq_doc_status_failed(status, last_failed_at)`를 둔다. 실패 이력 `except_doc_info error`·`pipe_event`와 별개다. 실패 3회면 dead, 사람이 requeue한다. 자동 재시도 정책은 12월(#174 합의)이다.

쓰는 곳: `pipeline/shared/dlq.py` — 호스트의 `except_docs error` CLI만 실패 upsert(컨테이너 record_error는 이력만), gold 적재 성공과 skip-done 본 목록의 gold/영구 뺌 대조가 resolve, 운영자가 requeue. 읽는 곳: `candidate_pick.list_targets`(`--skip-done`일 때 dead 제외·pending은 다음 실행 본 흐름에서 재시도, FAQ도 동일), 호스트 실행기 요약과 `python -m pipeline.shared.dlq list`. `dbtool maintain --target applog`는 보존 기한 지난 resolved만 지운다.

| 칸 | 형식 | 뜻 |
|---|---|---|
| source_key | TEXT PK | 원본 키(`FileStorageMap.s3_key`·gold `doc.file_path`) |
| source_system | TEXT | 원천 시스템 |
| file_name | TEXT | 원본 파일 이름 |
| stage | TEXT | 마지막 실패 단계(parse·publish·load·classify 등, 실패 이유에서) |
| last_reason | TEXT NOT NULL | 마지막 실패 이유(해소 때도 보존) |
| attempts | INTEGER NOT NULL DEFAULT 1 | 실패 시도 횟수(호스트가 문서당 한 번 기록, requeue 때 0) |
| status | TEXT NOT NULL DEFAULT 'pending' | CHECK pending·dead·resolved |
| first_failed_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 현재 실패 주기의 첫 실패 시각(resolved 뒤 재실패면 새로) |
| last_failed_at | TIMESTAMPTZ NOT NULL DEFAULT now() | 마지막 실패 기록 시각 |
| dead_at | TIMESTAMPTZ | dead가 된 시각(requeue·새 실패 주기 때 비움) |
| resolved_at | TIMESTAMPTZ | gold 완료 또는 영구 뺌 확인 시각(보존 DELETE 기준) |
| pipeline_version | TEXT | 마지막 실패의 `common.pipeline_version()` |

### applog.superseded_doc_log

같은 `s3_key`의 더 새 `FileStorageMap` 행 때문에 밀려난 행의 이력 — 밀려난 행 1개당 1행. 아직 표·코드가 없다(요건 [pl-32](../prd/load-schema.md#pl-32) — applog Alembic 판으로 추가). 시험 비교 대상이 아니다.

| 칸 | 타입 | 예 | 뜻 | 쓰는 곳 | 읽는 곳 | 결정 |
|---|---|---|---|---|---|---|
| file_storage_map_id | BIGINT PK | `23` | 밀려난 `FileStorageMap` 행 id | (파이프라인 — 기준 행 고를 때) | (운영자) | 새로 |
| s3_key | TEXT NOT NULL | `SFDC/17ae1841-…/kvx_rfp_main.pdf` | 겹친 문서의 원본 키 | 〃 | 〃 | 새로 |
| source_system | TEXT | `SFDC` | 원천(FileStorageMap `source_system`) | 〃 | 〃 | 새로 |
| kept_file_storage_map_id | BIGINT NOT NULL | `31` | 기준으로 남은 행 id | 〃 | 〃 | 새로 |
| reparsed | BOOLEAN NOT NULL | `false` | 새 행의 `file_size`가 달라 다시 파싱했는지(같으면 기준·메타만 바꿈) | 〃 | 〃 | 새로 |
| recorded_at | TIMESTAMPTZ NOT NULL | `2026-10-16 00:30:00+00` | 기록한 때(기본 now) | 〃 | 〃 | 새로 |
