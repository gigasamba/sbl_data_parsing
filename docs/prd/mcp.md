# 검색 MCP

[PRD.md](../PRD.md)의 카테고리 하나 — 이미지 `mcp-server`. 항목마다 무엇·왜·관련 파일. 끝난 항목은 `Status: done`, 열린 항목은 `Status:` 줄에 진행 상황.
도구 계약(이름, 입력, 출력, `tools/list` 순서)은 고정이다 — 협의와 새 판으로만 바꾼다([CLAUDE.md](../../CLAUDE.md) §4).

순서(주제별): `search` 도구 mc-01·mc-02·mc-05 → 집계 mc-04·mc-11·mc-12 → 문서 키·기록 결함 mc-10·mc-13·mc-14·mc-15 → 운영 계약 mc-16·mc-17 → 다른 도구 mc-06·mc-07·mc-08 → 서버 실행 mc-09 → 코드와 다른 점.

<a id="mc-01"></a>
## mc-01 · `search` 도구 — 적재된 문서에서 근거 찾기
- 이유: 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구.
- 무엇: 세 방식 — 질문만(혼합 검색), 거르기만(맞는 문서의 모든 청크, 점수 없음), 질문 + 거르기(저장소 질의에서 범위를 걸고 후보 `min(50, max(3k, 30))`을 거른 뒤 번호를 다시 매김 — 재순위 단계 없음). 거르기 `client`, `client_like`, `source_system`, `project_id`, `division`, `service_type`은 PG 저장소에서만 동작(로컬 묶음: 거르기만이면 오류, 질문 + 거르기면 거르지 않고 검색). `index_id`는 이름 붙은 색인을 고른다. `limit`은 거르기만 방식에 적용.
- 찾기: 방법은 `vector`·`bm25`·`id`만(graph·concept·image·openviking은 10-29에 지움 — 다른 값은 메모와 함께 무시). vector(pgvector 코사인, HNSW. HNSW 차원을 넘으면 binary quantize + 상위 200 다시 점수) + BM25(`chunk_term`·`term_stat`·`corpus_stat`) + 드문 ID 정규식을 가중 RRF로 합친다(질문 유형별 가중치).
- 출력: 근거 항목(`chunk_id`, `source_uri`, `page`, `bbox`, `section`, `text`, `score`, `via`, `rank`, …), `evidence_status` found/weak/none(라벨만, 빼는 것 없음), `notes`.
- `file_path` 키 제거는 [mc-16](#mc-16)에서 다룬다(사용자 10-30 PRD grill D1).
- 파일: `mcp_server/routers/`, `mcp_server/services/search/search_svc.py`, `retriever.py`, `pgsearch.py`, `local.py`, `shaping.py`, `mcp_server/schemas/evidence.py`.
- Status: done

<a id="mc-02"></a>
## mc-02 · 질문 이해 — 넓히기
- 이유: 사용자는 동의어, 약어, 여러 고객을 한꺼번에 넣어 묻는다.
- 무엇: BM25용 용어집 넓히기(동의어 1.0 / 약어 0.8 / 약한 것 0.3, 고객 목록 별칭, 최대 20), vector 질의에 별칭 글 붙이기, 비교 질문은 고객별로 나눠 찾기(`SEARCH_ENTITY_SPLIT`, 번갈아 합치기 `search_svc._gather`), 가중치용 규칙 기반 질문 유형. LLM 질문 분해는 10-29에 지움(`decompose` 입력은 받고 무시, `subs`는 늘 `[]`).
- 파일: `mcp_server/services/search/terms.py`, `qtype.py`, `search_svc.py`.
- Status: done

<a id="mc-05"></a>
## mc-05 · 고객 범위, 판, 중복
- 이유: 답이 고객을 섞거나 옛 판을 인용하면 안 된다.
- 무엇: 부드러운/하드 고객 범위, 숨김 문서 제외, 최신을 묻는 질문에서는 새 판을 옛 판보다 위로(`SEARCH_RECENCY=1` 기본, `2` = 늘. 옛 판은 남기고 `superseded` 표시), 사본 묶음이 이름 바뀐 사본을 합친다.
- 파일: `mcp_server/services/search/clientscope.py`, `supersede.py`, `common/core/docmeta.py`.
- 고칠 것(reference 비교(사용자 grill 10-30, 원본은 git 밖) M3·T2 — 버그): `client` 판정을 운영 10-28 방식으로 — 별칭 그룹으로 정확히 일치, `sf_acc_name`이 비었을 때만 라벨로 판정, 목록은 OR로 받는다. 파일: `mcp_server/services/search/search_svc.py`, `clientscope.py`.
- 결정(사용자 10-30 PRD grill): C6 — 검색의 고객 거르기는 EDW에서 조인한 고객(`client_edw`)만 쓴다. 본문에서 찾은 고객(`clients_doc`)은 참고용으로만 둔다. LAS는 EDW 고객이 비어 고객 거르기에서 늘 빠진다(원천별 스키마라 LAS는 따로 검색됨).
- Status: todo — client 판정 고침(T2). 나머지는 done.

<a id="mc-04"></a>
## mc-04 · 집계 답
- 이유: 건수·합계 질문에는 청크가 아니라 계산한 값이 필요하다.
- 무엇: 고객·계약·기간·모달리티별 규칙 기반 건수·금액·배치·표 합계. 다른 통화는 절대 더하지 않음. 집계 항목에 환율 글을 붙임. 결과는 `via="aggregate"`로 맨 앞. 애매한 질문은 선택적 LLM 라우터.
- 파일: `mcp_server/services/search/aggregate.py`, `resources/prompts/mcp/agg_llm_route/`.
- Status: done

<a id="mc-11"></a>
## mc-11 · 집계 길이 지운 칸을 고름
- 이유: `aggregate.pg()`가 `file_sha256`, `client`, `contract_no`, `meta_confirmed`, `contract`를 골라 모든 검색 결과에 "집계 경로 오류" 메모가 붙는다(근거 자체는 정상).
- 파일: `mcp_server/services/search/aggregate.py`.
- 끝남 10-30: mc-12와 함께 닫음 — `aggregate.pg()`(집계 길에서 그 칸을 읽던 곳)를 지움. `retriever.py`는 아직 그 칸을 읽는다(mc-10).
- Status: done

<a id="mc-12"></a>
## mc-12 · 사실 집계가 지운 표를 질의
- 이유: `kg_node`·`kg_edge`·`doc_fact`·`concept_chunk`·`doc_image`·`chunk_image`는 더는 만들거나 적재하지 않는다(`pipeline/load/pgvector_load.py`). 그 표를 읽던 graph·concept 검색 방법은 10-29에 지웠지만 `aggregate.py`의 `doc_fact` 기반 집계 길은 아직 `doc_fact`를 질의해 PG에서는 아무것도 돌려주지 않는다.
- 끝남 10-30(사용자 결정): 그 길을 지움 — `aggregate.pg()` 삭제. PG 저장소에서 `do_aggregate`는 "집계 질문이 아님 — search를 쓰세요" 메모를 돌려주고, `ask --pg`는 문서 집계를 보이지 않는다(`--pg` 옵션 자체는 남음 — PG 검색을 고름). 숫자 질문은 `query_edw`로. 묶음(`local()`)과 정형 DB(`struct()`) 집계는 그대로. MCP 도구 계약·DB 변경 없음.
- 파일: `mcp_server/services/search/{aggregate,internal_docs}.py`, `mcp_server/cli/ask.py`, `pipeline/load/pgvector_load.py`.
- Status: done

<a id="mc-10"></a>
## mc-10 · retriever가 지운 칸 `file_sha256`을 읽음
- 이유: 10-20 축소 스키마가 `file_sha256`·`client`·`file_name`·`s3_key`를 지웠는데 retriever는 아직 `doc.file_sha256`(`hidden_names`)과 `doc.client`·`doc.file_name`(`_client_rows`)을 읽어 새 묶음으로 retriever를 만들면 실패한다.
- 파일: `mcp_server/services/search/retriever.py`.
- Status: done (10-30, `feature/search-path-fixes`) — 묶음 `docs.jsonl`을 읽을 때(`local.Local`) 문서마다 `doc_key`(새 묶음 `file_path`, 옛 묶음 `file_sha256`)와 `file_name`(`doc_name`, 없으면 `file_path`의 마지막 `/` 뒤 — `v_chunk_source` 뷰와 같은 규칙)을 한 번 채운다 — 검색 근거·`client_map`·`internal_docs`의 문서 목록·조회·용어 찾기가 같은 값을 봄. PG `doc` 조회는 남은 열(`file_path`·`clients`)만 고름(`_client_rows`). 시험 `tests/server/mcp/test_mc10_doc_key.py`(새·옛 묶음, Windows 경로, 목록·조회). 범위 밖으로 남은 것: `internal_docs`의 PG 쪽 문서 조회·목록(없는 열 `file_name`·`file_sha256`·`client`를 고름 — 별도 항목) · `get_document`는 `:` 앞을 문서 키로 봐서 Windows 경로(`C:\…`)로는 못 찾음(서버 경로는 해당 없음) · 숨김 키 비교는 [mc-14](#mc-14).

<a id="mc-13"></a>
## mc-13 · PG 질의 기록이 마이그레이션에 없는 표에 씀
- 이유: `search_svc`가 PG 저장소에서 `INSERT INTO qa_log`를 하는데 `0001_search_base`에 `qa_log` 표가 없다. 오류를 삼켜서 jsonl 기록만 동작한다.
- 파일: `mcp_server/services/search/search_svc.py`, `mcp_server/services/search/qa_log.py`, `common/store/db/migrations/versions/0001_search_base.py`.
- Status: done (10-30, `feature/search-path-fixes`) — 사용자 결정: 질의 기록은 파일(`qa_log.jsonl`)만. `search_svc._log`와 `ask.py`의 PG `qa_log` INSERT를 지움(표는 만들지 않음). jsonl 기록은 그대로. 시험 `tests/server/mcp/test_mc13_qa_log.py`. 남은 것: `ask --retrieve cosine`(옛 직접 검색 길)은 전에도 PG에만 남겼고 이제 기록이 없음 — 기본 길(`do_search`)은 jsonl에 남김.

<a id="mc-14"></a>
## mc-14 · 숨김 문서가 검색에서 빠지지 않는다
- 이유: 숨김 표(`doc_hidden`, struct 스키마)의 키는 문서 대장 `doc_key` = 원본 sha256인데(`registry.apply()`가 원천에서 사라진 문서를 자동 숨김, `registry_cli hide`도 같은 키), 10-20 축소 스키마 뒤 검색 쪽 문서 키는 `file_path`다. `pgsearch._not_hidden_restrict`가 sha256을 `doc.file_path`와 비교해 절대 안 맞고, 로컬 묶음(`local.py`)·`retriever.hidden_names`는 PG에서 없는 열을 골라 숨김 문서가 하나라도 있으면 오류가 났다 — 10-30부터 PG에서는 빈 집합(오류 대신, 숨김 안 됨은 그대로).
- 조사(10-30): 스키마 변경 없이 잇는 길이 없다. 검색 `doc` 표에는 sha256도 원본 키(`s3_key`)도 없고(`file_path` = `edw_path_prefix` + 파일 이름 또는 PC 경로), 문서 대장의 `source_keys`(`local::<경로>`·`<출처>::<원본 키>`)는 모양이 달라 정확히 맞출 수 없다. 파일 이름으로 맞추면 다른 폴더·고객의 같은 이름 문서가 잘못 숨겨진다(engine-qa 10-08이 이름 짝짓기를 금지한 이유와 같음).
- 결정(사용자 10-30): 모든 문서 키를 `s3_key`로 바꾸고 문서 대장·숨김 표를 DB 명세로 다시 키를 잡는다(pl-25, 스키마 변경 — Alembic·DB 담당자). 그때 이 비교를 같은 키로 고친다.
- 파일: `mcp_server/services/search/pgsearch.py`(`_not_hidden_restrict`), `mcp_server/services/search/local.py`, `mcp_server/services/search/retriever.py`, `common/store/registry.py`.
- Status: todo — pl-25 대기(코드 수정 없음 — 키 설계는 [db_schema.md](../architecture/db_schema.md) §1·§3).

<a id="mc-15"></a>
## mc-15 · 검색 근거의 `rep_uri`(대표 파싱 결과 경로)가 늘 비어 있다
- 이유: `shaping._rep_uri`가 근거의 `doc_key`(= `file_path`)로 `AI.ParsingMeta`를 찾는데(`parsing_meta_db.find_rep_path` → `find_by_doc_key`), ParsingMeta의 `doc_key`는 원본 sha256이다(`docs/operations/parsing_meta_mssql.sql` — 유일한 필수 열). 그래서 한 번도 맞지 않는다.
- 조사(10-30): ParsingMeta에서 원본을 가리키는 열은 `doc_key`(sha256)·`source_key`(Object Storage 원본 전체 키)·`source_uri`·`original_filename`이다. 검색 `doc` 표에는 sha256도 원본 키도 없어서(10-20 축소 스키마가 `s3_key`를 뺌, `build_bundle`의 `_meta`에도 안 남음) 정확히 맞출 열이 없다. `original_filename`으로 맞추면 같은 이름 문서가 섞인다(mc-14와 같은 이유로 하지 않음).
- 결정: mc-14와 같이 pl-25(문서 키 `s3_key` 통일 — 검색 `doc`에 원본 키가 들어옴)를 기다린다. 그 뒤 `source_key`로 조회하도록 고친다(ParsingMeta 쪽 스키마 변경은 필요 없음).
- 파일: `mcp_server/services/search/shaping.py`, `common/store/parsing_meta_db.py`.
- 결정(사용자 10-30 PRD grill): C8 — 근거의 `rep_uri`(대표 파싱 결과의 전체 주소 `s3://<rep_bucket>/<rep_key>`)는 검색 중 EDW에 접속하지 않고 gold `doc`의 `rep_key`(적재 때 ParsingMeta에서 복사)로 만든다. ParsingMeta 조회 길은 없앤다. 0.2.0.
- Status: todo — pl-25 대기(코드 수정 없음 — 키 설계는 [db_schema.md](../architecture/db_schema.md) §1·§3).

<a id="mc-16"></a>
## mc-16 · `search` 운영 계약 구현
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) M1·T1): `search`를 운영 계약 그대로 구현한다 — `question` 필수, 필터 11종, 출력 축소. 기준 명세는 운영 `05_mcp_tools_schema.md` §2(git 밖). MCP 계약 변경이라 검토 등급 A, 새 판.
- 운영 계약(사용자 10-30 PRD grill A9 — 사용자 로컬 reference의 MCP 규약 최신판에서 필터 이름·뜻·출력 칸만 옮김):
  - 입력: `question` 필수(비면 오류 — 거르기만 하는 방식은 없음) · `k` 기본 8, 상한 50(넘으면 50으로 줄임).
  - 거르기(모두 AND, 같은 거르기의 목록은 OR, 맞는 값이 없으면 오류가 아니라 빈 결과, 모르는 인자는 무시):
    - `source_system` — `SFDC`·`CRMS`·`LAS`·`FAQ`(G4 — `-test` 별칭도 받음).
    - `client` — 고객 이름 하나 또는 목록(OR). 우리 결정은 EDW에서 조인한 고객(`client_edw`)만 본다([mc-05](#mc-05), C6 — 운영처럼 본문 라벨로 대신하지 않음). `client_like`(`true`) — `client`와 함께 쓰는 유일한 부분 일치.
    - `project_id` — SFDC 프로젝트 코드.
    - `division` — `CD`·`DS`·`DP`.
    - `service_type` — `CDO`·`CMO DS`·`CMO DP`·`ADC`·`mRNA`·`New Platform`·`CMO DS (MTOP Shared)`.
    - `FAQ_group` — FAQ 시트 값(DP·FMD·Study·Facility·Regulatory·Analytical·DS·CLD·Others) — FAQ만([etl.md#pl-39](etl.md#pl-39)).
    - `doc_class` — `source_system`과 함께(SFDC 또는 LAS 분류값 — [etl.md#pl-33](etl.md#pl-33)).
    - `sf_op_id`·`sf_op_name` — SFDC 영업 기회 id(18자 `006…`)·이름.
    - `contract_id` — 계약 번호(CRMS 계약 코드, LAS 관리 번호).
    - `created_since`·`created_until` — 원천 등록 시각(시간대 없으면 KST). `created_at`이 없는 문서는 빠진다.
  - "하드 거르기 최소 1개"는 권고만(G5).
  - 출력 맨 위: `question` · `evidence[]`(길이 k) · `evidence_status`(`found`·`weak`·`none`) · `filter`(정규화한 거르기 메아리) · `scope_docs`(맞은 문서 수, 0도 정상).
  - `evidence[]` 항목: `text` · `file_name`(`list_doc_fulltext`로 잇는 다리 — [mc-17](#mc-17)) · `page` · `line` · `section` · `client` · `contract_no` · `doc_date` · `version` · `superseded` · `chunk_key`. 운영에는 `file_path`도 있으나 뺀다(아래).
  - `file_path` 키 제거(사용자 10-30 "mcp 기능에서 제거될 것이니 pass" · "reference 기준으로 하면 file_path 관련 부분 뺄거라 제거 대상으로 간주만 하고 일단 pass", D1 — 이 행에서만 다룸): gold `doc.file_path` 삭제([etl.md#pl-25](etl.md#pl-25))와 함께 0.2.0(C1·C2), 계약 변경이라 등급 A. 열린 점: 운영 `chunk_key`는 `<file_path>:<순번>` 꼴 — `file_path`를 빼면 키 바탕(`s3_key` 등)을 정해야 함.
- 필터용 칸 `doc_class`·`created_at`은 gold `doc`에 Alembic으로 더한다(M4 — [etl.md#pl-25](etl.md#pl-25)).
- 남은 확인: 운영 MCP 서버 소스는 없음 — 명세 기준으로 새로 구현, 구하면 대조.
- 파일: `mcp_server/routers/`, `mcp_server/schemas/`, `mcp_server/services/search/`.
- 결정(2차 grill(사용자 10-30, 원본은 git 밖)):
  - G4: `source_system` 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`로 통일, `-test`가 붙은 입력(`SFDC-test` 등)도 같은 뜻으로 받는다(두 도구 모두).
  - G5: "하드 필터 최소 1개"는 권고만 — 강제하지 않는다.
  - G6: `search` 속도 목표는 두지 않는다.
  - G7 → 사용자 10-30 PRD grill C1·C2로 바뀜: 0.1.0(10-30 릴리스)에는 들어가지 않았고 0.2.0에 싣는다. 1.0 전에는 MINOR에서도 계약·스키마를 깰 수 있다(버전 규칙 — 운영이 안정되면 1.0.0).
- 결정(사용자 10-30 PRD grill): A9 — 필터·출력 축소 기준은 사용자 로컬 `reference/`(git 밖, 비밀값 포함 — 커밋·인용 금지)의 MCP 규약 문서를 보고 운영 최신판으로 이 행에 옮겨 적는다(필터 이름·뜻·출력 칸만, 접속 정보·회사 데이터 없이). D1 — MCP 근거의 `file_path` 없애기는 이 행 하나로 합친다(mc-01·pl-25·op-04에는 이 행 링크만).
- Status: todo — 순서는 허브가 정함([etl.md#pl-32](etl.md#pl-32)).

<a id="mc-17"></a>
## mc-17 · 원문 전송 도구 `list_doc_fulltext`·`get_doc_fulltext`
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) M2·T3): 두 도구를 더한다(운영 명세 `05_mcp_tools_schema.md` §6). 새 도구 — 계약 추가라 검토 등급 A.
- 파일: `mcp_server/routers/`, `mcp_server/services/`(새 파일).
- 결정(2차 grill(사용자 10-30, 원본은 git 밖)): G1 — 목록은 EDW `ParsingMeta`의 `doc_class`·`sf_op_id`·`parsed_at`·`rep_engine`·`created_at`(G9 — `created_since`/`created_until` 거르기·출력, `get_doc_fulltext` 생성 범위 가드)을 읽는다(운영 계약 그대로, [etl.md#pl-25](etl.md#pl-25)). G4 — `source_system` 통일·`-test` 별칭. G7 — 0.1.0에 함께 싣고 따로 MAJOR 없음.
- 결정(사용자 10-30 PRD grill): C8 — 원문 전송 도구도 gold `doc.rep_key`를 읽는다(mc-15와 같음). C2 — 0.2.0.
- Status: todo — 순서는 허브가 정함.

<a id="mc-06"></a>
## mc-06 · `query_edw` 도구 — 읽기 전용 EDW SQL
- 이유: 정형 질문은 회사 EDW에서 답한다.
- 무엇: SELECT/WITH 하나만, 표 허용 목록(mssql: 기본 꺼짐 — `EDW_QUERY_TABLES_STRICT=0`이면 시스템 카탈로그를 뺀 모든 스키마 허용, sqlite 대역은 함께 든 목록), 행·시간·바이트 상한, 낮은 권한의 별도 로그인, PC 시험용 sqlite 대역.
- 파일: `mcp_server/services/edw_query.py`, `mcp_server/services/edw_calls.py`.
- 배포 주의(reference 비교(사용자 grill 10-30, 원본은 git 밖) T14): `query_edw` 가드의 오탐(정상 SELECT 거부)을 서버에서 확인.
- Status: done

<a id="mc-07"></a>
## mc-07 · `edw_meta` 도구 — EDW 카탈로그 찾기
- 이유: 클라이언트는 SQL을 쓰기 전에 표·칸 이름이 필요하다.
- 무엇: 정적 개인정보 제거 자료(`catalog.json` + `columns.jsonl`)에서 3단계 찾기(스키마 → 표 → 칸). 모르는 이름은 difflib 제안. LLM·벡터 없음.
- 파일: `mcp_server/services/edw_meta.py`.
- 배포 주의(reference 비교(사용자 grill 10-30, 원본은 git 밖) T14): `edw_meta` 표 이름 끝 공백 확인.
- Status: done

<a id="mc-08"></a>
## mc-08 · `parse_document` 도구 — 파일 하나를 바로 파싱
- 이유: 클라이언트가 아직 적재되지 않은 파일을 묻는다.
- 무엇: 경로(inbox 루트 아래) 또는 base64 내용을 127.0.0.1:8766의 파싱 서비스에 Bearer 토큰으로 넘긴다. 글, 표준 표, 사실, 엔진, 시간을 돌려주고 시간 초과면 `job_id`.
- 파일: `mcp_server/services/parse_proxy.py`, `pipeline/mcp_parse_service.py`.
- Status: done

<a id="mc-09"></a>
## mc-09 · 서버 실행과 안전
- 이유: 공용 내부 서비스라 계속 떠 있어야 하고 위험한 노출은 거부해야 한다.
- 무엇: FastMCP streamable HTTP(`/mcp`, 기본 127.0.0.1:8765) 또는 `--stdio`. loopback이 아닌 주소는 `MCP_TOKEN` 필요(상수 시간 비교), 0.0.0.0 거부, DNS 리바인딩 가드, `/health`(준비 중이면 503), 동시 8 + 대기열 + 도구 시간 30초, 새 적재 판이면 다시 읽기, `query_edw` 호출을 포함한 jsonl 질의 기록(90일).
- 파일: `mcp_server/main.py`, `mcp_server/routers/dispatch.py`, `mcp_server/config.py`.
- 배포 주의(reference 비교(사용자 grill 10-30, 원본은 git 밖) T14): 질의 기록(`qa_log.jsonl`) 경로를 컨테이너에서 쓰기 가능한 곳으로.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작(ID 있는 행은 열린 결함, 나머지는 알아 둘 동작)
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 숨김 문서는 검색에서 빠짐 | 숨김 키(sha256)를 검색 키(`file_path`)와 비교 → 안 빠짐 | `pgsearch.py`, `local.py` | mc-14 |
| 근거에 파싱 결과 경로(`rep_uri`) | ParsingMeta를 `file_path`로 찾음(그쪽 키는 sha256) → 늘 비어 있음 | `shaping.py` | mc-15 |
| `query_edw` 표 허용 목록 | mssql에서 기본 꺼짐(`EDW_QUERY_TABLES_STRICT=0` → 시스템 카탈로그를 뺀 모든 스키마) | `edw_query.py` | mc-06 |
| 모든 저장소에서 하드 거르기 | PG 저장소만. 로컬 묶음: 거르기만이면 오류, 질문 + 거르기면 거르지 않고 검색 | `search_svc.py` | mc-01 |

### 요건 없는 코드 — 남길지(앵커를 씀) 지울지([test.md#e2-18](test.md#e2-18))
- `AI.ParsingMeta`에서 근거의 파싱 결과 경로(`MCP_EVIDENCE_PATHS`, 켜짐). `shaping.py`.
- 도구로 노출되지 않은 근거 이미지 자르기와 내부 조회: `do_evidence_image`, `do_get_image`, `do_related`(시험만), `do_lookup_term`, `do_get_document`, `do_list_documents`. `internal_docs.py`.
- 질문 개체로 동점 가르기(`SEARCH_TIE_BREAK`, 켜짐). `search_svc.py`.
- PG 대역(PG 설정이 없으면 SQLite — PC). `common/store/pg_standin.py`.
- 문서 대장 CLI. `mcp_server/cli/registry_cli.py`.

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 하드 고객 격리 | `SEARCH_CLIENT_HARD=0`, `SEARCH_CLIENT_STRICT=0` | — |
| 늘 새 판 먼저 | `SEARCH_RECENCY=1`("최신" 질문만, `2` = 늘) | — |
| 애매한 집계용 LLM 라우터 | `SEARCH_AGG_LLM=0` | LLM |
| `query_edw` | `EDW_QUERY=1` | `common.connections.rdb` + 읽기 계정, 또는 `RDB_SQLITE` |
| `edw_meta` | — | `EDW_META_DIR`의 자료(기본 `/app/config/edw_meta`) |
| `parse_document` | `PARSE_OCR_ENGINE=0`(OCR/VLM 엔진 없음 — `PARSE_MCP_OCR`은 10-29에 합침) · 제한 글자 쪽당 1초, VLM 쪽당 60초 | `mcp_parse_service` 실행 + `PARSE_SERVICE_TOKEN` |

### 10-29에 지운 기능(사용자 결정)
- 검색 재순위(`SEARCH_RERANK`, `common.models.rerank`) — `34f398e`.
- LLM 질문 분해(`MCP_DECOMPOSE`, `DECOMPOSE`, 프롬프트 `query_decompose`). 고객별 나누기는 남김 — `dd3e974`.
- 검색 방법 graph, concept, image, openviking — `9e58c71`.
- OpenViking 전부(적재, 요약 가져오기, 검색, 감지, 설정) — `c07dde5`.
- `search`는 입력 스키마를 유지한다: vector·bm25·id 밖의 `methods`와 `decompose`는 받고 무시한다. 응답에는 `"images": []`, `"subs": []`가 남는다.
