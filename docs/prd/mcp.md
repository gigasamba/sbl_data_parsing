# 검색 MCP

[PRD.md](../PRD.md)의 카테고리 하나 — 이미지 `mcp-server`. 항목마다 무엇·왜·관련 파일. 끝난 항목은 `Status: done`, 열린 항목은 `Status:` 줄에 진행 상황.
도구 계약(이름, 입력, 출력, `tools/list` 순서)은 고정이다 — 협의와 새 판으로만 바꾼다([CLAUDE.md](../../CLAUDE.md) §4).

순서(주제별): `search` 도구 mc-01·mc-02·mc-05 → 집계 mc-04·mc-11·mc-12 → 문서 키·기록 결함 mc-10·mc-13·mc-14·mc-15 → 운영 계약 mc-16·mc-17 → 다른 도구 mc-06·mc-07·mc-08 → 서버 실행 mc-09 → 코드와 다른 점.

<a id="mc-01"></a>
## mc-01 · `search` 도구 — 적재된 문서에서 근거 찾기
- 결정(사용자 10-31 범위 축소 grill): PC 전용 검색 우회로(PG 없이 묶음 검색 local.py, SQLite PG 대역 pg_standin)를 **지운다** — 검색은 PG 하나(op-09와 같음). 단 이미지 selftest가 pg_standin을 쓰면 그것만 남김(확인 후).
- 이유: 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구.
- 무엇: `question`과 원천 하나(`source_system` — SFDC·CRMS·LAS·FAQ·Other, 없으면 오류 — G20)는 필수. 질문만이면 그 원천 스키마 전체에서 혼합 검색, 거르기(14칸 `SEARCH_FILTERS` — 13칸 + `attrs`(원천별 메타 키, pl-52) — 모두 AND, 같은 칸의 목록은 OR)를 더하면 범위를 먼저 구해 후보 `min(50, max(3k, 30))`을 찾은 뒤 번호를 다시 매김(재순위 단계 없음). 맞는 문서가 없으면 빈 결과(`evidence_status` none). 질문 없이 문서 고르기는 `list_doc_fulltext`. 옛 입력 `methods`·`decompose`·`limit`·`index_id`와 로컬 묶음 검색은 지움(mc-16·mc-19 — 검색은 PG만).
- 찾기: 방법은 `vector`·`bm25`·`id`만(graph·concept·image·openviking은 10-29에 지움 — 다른 값은 메모와 함께 무시). vector(pgvector 코사인, HNSW. HNSW 차원을 넘으면 binary quantize + 상위 200 다시 점수) + BM25(`chunk_term`·`term_stat`·`corpus_stat`) + 드문 ID 정규식을 가중 RRF로 합친다(질문 유형별 가중치).
- 출력: 근거 13칸(`mcp_server/schemas/evidence.py` `EVIDENCE_KEYS` — `text`, `file_name`, `file_path`, `page`, `line`, `section`, `client`, `contract_no`, `doc_date`, `version`, `superseded`, `chunk_key`, `attrs`(pl-52 — 11-03), 값이 없으면 null), `evidence_status` found/weak/none(라벨만, 빼는 것 없음). 옛 칸(`chunk_id`·`source_uri`·`bbox`·`score`·`via`·`rank`·`notes` 등)은 11-01에 지움([mc-16](#mc-16)).
- `file_path`는 근거에 남는다(사용자 11-03 — 코드가 맞음, 옛 제거 결정 D1은 뒤집힘 — [mc-16](#mc-16)).
- 파일: `mcp_server/routers/`, `mcp_server/services/search/search_svc.py`, `retriever.py`, `pgsearch.py`, `local.py`, `shaping.py`, `mcp_server/schemas/evidence.py`.
- 한 것(11-01 `feature/scope-cut-search` — A안, 허브·사용자 11-01): PC 전용 로컬 묶음 검색(`Local` 검색·`ask --local`·저장소 칸 `mcp.server.store`·`pgsearch bench`) 지움 — 검색은 PG 하나, PC는 SQLite 대역(`pg_standin` — 이미지 selftest도 씀, 남김). 대역이 PG 검색 SQL·작업 스레드를 받도록 고침(`regexp_replace`·`ln`·VALUES 별칭·스레드 잠금). 묶음은 아직 실행 중에 읽음(`BundleDocs` — 문서 메타·청크 키) — 없애는 것은 [mc-19](#mc-19). 시험은 대역으로 옮김(`tests/server/mcp/pgfix.py`).
- Status: done — A안(11-01 `feature/scope-cut-search`) · B안은 [mc-19](#mc-19)

<a id="mc-02"></a>
## mc-02 · 질문 이해 — 넓히기
- 이유: 사용자는 동의어, 약어, 여러 고객을 한꺼번에 넣어 묻는다.
- 무엇: BM25용 용어집 넓히기(동의어 1.0 / 약어 0.8 / 약한 것 0.3, 고객 명부 별칭, 최대 20 — 용어집·명부는 PG 마스터 표, pl-38), vector 질의에 별칭 글 붙이기, 가중치용 규칙 기반 질문 유형. 고객별 하위 검색(BR23)은 11-02에, LLM 질문 분해(`decompose` 입력·`subs` 출력)는 10-29·mc-16에 지움.
- 파일: `mcp_server/services/search/terms.py`, `qtype.py`, `search_svc.py`.
- Status: done

<a id="mc-05"></a>
## mc-05 · 고객 범위, 판, 중복
- 결정(사용자 10-31 범위 축소 grill): 본문 글자로 판·개정·구판을 추정하는 기능(docmeta 추정, version·superseded 출력 칸)을 **지운다**. 최신성 정렬·날짜 필터는 EDW `created_at`(문서가 생긴 시각). 도구 출력 변경 — 0.2.0.
- 이유: 답이 고객을 섞거나 옛 판을 인용하면 안 된다.
- 무엇(지금): 고객 거르기는 `client_edw` 정확 일치(`client_like`면 부분 일치, 목록은 OR), 사본 묶음이 이름 바뀐 사본을 한 자리로 합친다. 근거의 `version`은 수집 manifest 값만, `superseded`는 늘 null. 본문 고객 라벨 순위(`clientscope`)·최신성 순위(`SEARCH_RECENCY`·`supersede`)는 지움(11-02·11-03).
- 파일: `mcp_server/services/search/search_svc.py`, `shaping.py`.
- 고칠 것(reference 비교(사용자 grill 10-30, 원본은 git 밖) M3·T2 — 버그): `client` 판정을 운영 10-28 방식으로 — 별칭 그룹으로 정확히 일치, `sf_acc_name`이 비었을 때만 라벨로 판정, 목록은 OR로 받는다. 파일: `mcp_server/services/search/search_svc.py`, `clientscope.py`.
- 결정(사용자 10-30 PRD grill): C6 — 검색의 고객 거르기는 EDW에서 조인한 고객(`client_edw`)만 쓴다. 본문에서 찾은 고객(`clients_doc`)은 참고용으로만 둔다. LAS는 EDW 고객이 비어 고객 거르기에서 늘 빠진다(원천별 스키마라 LAS는 따로 검색됨).
- 결정(허브 10-31, 최신 결정 우선): C6이 이긴다 — 고객 거르기는 `client_edw`만. 위 T2의 '`sf_acc_name`이 비었을 때만 라벨로 판정'은 없앤다(별칭 그룹 정확 일치·목록 OR은 남김 — 별칭 CSV는 [load.md#pl-38](load.md#pl-38) 0.2.0 몫). 근거의 `client` = `client_edw`, `clients_doc`은 따로 둔 참고 칸.
- 구현(11-01 `feature/mcp-ops-parity`, 허브 지시 "운영이 version/superseded를 아직 내면 칸은 두고 추정만 멈춤"): 운영 계약(05 §2.4)에 `version`·`superseded`·`doc_date`가 남아 있어 칸은 둔다. 운영 예시 값은 모두 null이라 운영도 본문 추정을 하지 않는 것으로 본다 → `search` 근거의 `version`은 수집 manifest 값만(없으면 null), `superseded`는 늘 null(`shaping._evidence`). `doc_date`는 이 결정 밖이라 그대로. 본문 추정값(`common/core/docmeta.py`)은 안쪽 최신성 순위(L3-1)에만 남는다 — 순위를 EDW `created_at`으로 바꾸는 일은 남음. 시험: `test_search_svc` `_selftest_evidence_rdb_meta`.
- 11-02(사용자 C6): 고객 판정 고침 — 본문 고객 라벨로 앞으로 올리던 길(AD38·BR50 `clientscope`)·고객별 하위 검색(BR23)·설정 `SEARCH_CLIENT_HARD`/`STRICT`를 지우고, `client` 거르기는 `client_edw` 정확 일치(`client_like`면 부분 일치)만. 별칭 묶음은 [pl-38](load.md#pl-38) 몫.
- 결정(사용자 11-03 — [load.md#pl-38](load.md#pl-38)): 판 묶음(family)과 그것으로 옛 판을 뒤로 밀던 최신성 순위(`recency_rerank`·설정 `SEARCH_RECENCY`)를 지운다. `doc_date`·`version`·`superseded` 칸은 남김. 잠재 문제(같은 문서의 다른 판이 `s3_key`가 달라 '최신' 질문에서 옛 판이 위로 올 수 있음)는 pl-38에 기록 — 필요해지면 `created_at`으로 다시 설계.
- Status: done — 고객 판정·version·superseded 출력(11-01·11-02), 최신성 순위 지움(11-03). 같은 문서 다른 판 묶기는 잠재 문제 — [load.md#pl-38](load.md#pl-38) todo 행.

<a id="mc-04"></a>
## mc-04 · 집계 답
- 결정(사용자 10-31 범위 축소 grill): 집계 답(세기·합계·환율 메모·LLM 분류)을 **지금 지운다** — 숫자 질문은 query_edw. MCP 도구 계약은 그대로(via=aggregate만 안 나옴).
- 이유: 건수·합계 질문에는 청크가 아니라 계산한 값이 필요하다.
- 무엇: 고객·계약·기간·모달리티별 규칙 기반 건수·금액·배치·표 합계. 다른 통화는 절대 더하지 않음. 집계 항목에 환율 글을 붙임. 결과는 `via="aggregate"`로 맨 앞. 애매한 질문은 선택적 LLM 라우터.
- 파일: `mcp_server/services/search/aggregate.py`, `resources/prompts/mcp/agg_llm_route/`.
- 한 것(11-01 `feature/scope-cut-search`): `aggregate.py`·`supersede.py`·검색 `structdb.py`·`internal_docs.do_aggregate`·`search_svc`의 집계·환율 갈래·`ask`의 집계 지움. 질문 유형 단서(COUNT·SUM·LIST·MAXMIN)는 `qtype.py`로. 설정 `search.agg` 절·`agg_today`·`data_catalog`·`struct_context_max` 지움(남으면 경고). 프롬프트 `agg_llm_route`는 바이트 그대로(호출부 없음). MCP 도구 계약 그대로 — 근거에 `via=aggregate`가 안 나올 뿐.
- Status: done (11-01 `feature/scope-cut-search`)

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
- 결정(사용자 10-31 범위 축소 grill): 숨김 기능 자체를 지우므로 닫는다(pl-12 결정).
- 이유: 숨김 표(`doc_hidden`, struct 스키마)의 키는 문서 대장 `doc_key` = 원본 sha256인데(`registry.apply()`가 원천에서 사라진 문서를 자동 숨김, `registry_cli hide`도 같은 키), 10-20 축소 스키마 뒤 검색 쪽 문서 키는 `file_path`다. `pgsearch._not_hidden_restrict`가 sha256을 `doc.file_path`와 비교해 절대 안 맞고, 로컬 묶음(`local.py`)·`retriever.hidden_names`는 PG에서 없는 열을 골라 숨김 문서가 하나라도 있으면 오류가 났다 — 10-30부터 PG에서는 빈 집합(오류 대신, 숨김 안 됨은 그대로).
- 조사(10-30): 스키마 변경 없이 잇는 길이 없다. 검색 `doc` 표에는 sha256도 원본 키(`s3_key`)도 없고(`file_path` = `edw_path_prefix` + 파일 이름 또는 PC 경로), 문서 대장의 `source_keys`(`local::<경로>`·`<출처>::<원본 키>`)는 모양이 달라 정확히 맞출 수 없다. 파일 이름으로 맞추면 다른 폴더·고객의 같은 이름 문서가 잘못 숨겨진다(engine-qa 10-08이 이름 짝짓기를 금지한 이유와 같음).
- 결정(사용자 10-30): 모든 문서 키를 `s3_key`로 바꾸고 문서 대장·숨김 표를 DB 명세로 다시 키를 잡는다(pl-25, 스키마 변경 — Alembic·DB 담당자). 그때 이 비교를 같은 키로 고친다.
- 파일: `mcp_server/services/search/pgsearch.py`(`_not_hidden_restrict`), `mcp_server/services/search/local.py`, `mcp_server/services/search/retriever.py`, `common/store/registry.py`.
- Status: dropped (사용자 10-31 범위 축소)

<a id="mc-15"></a>
## mc-15 · 검색 근거의 `rep_uri`(대표 파싱 결과 경로)가 늘 비어 있다
- 이유: `shaping._rep_uri`가 근거의 `doc_key`(= `file_path`)로 `AI.ParsingMeta`를 찾는데(`parsing_meta_db.find_rep_path` → `find_by_doc_key`), ParsingMeta의 `doc_key`는 원본 sha256이다(`docs/operations/parsing_meta_mssql.sql` — 유일한 필수 열). 그래서 한 번도 맞지 않는다.
- 조사(10-30): ParsingMeta에서 원본을 가리키는 열은 `doc_key`(sha256)·`source_key`(Object Storage 원본 전체 키)·`source_uri`·`original_filename`이다. 검색 `doc` 표에는 sha256도 원본 키도 없어서(10-20 축소 스키마가 `s3_key`를 뺌, `build_bundle`의 `_meta`에도 안 남음) 정확히 맞출 열이 없다. `original_filename`으로 맞추면 같은 이름 문서가 섞인다(mc-14와 같은 이유로 하지 않음).
- 결정: mc-14와 같이 pl-25(문서 키 `s3_key` 통일 — 검색 `doc`에 원본 키가 들어옴)를 기다린다. 그 뒤 `source_key`로 조회하도록 고친다(ParsingMeta 쪽 스키마 변경은 필요 없음).
- 파일: `mcp_server/services/search/shaping.py`, `common/store/parsing_meta_db.py`.
- 결정(사용자 10-30 PRD grill): C8 — 근거의 `rep_uri`(대표 파싱 결과의 전체 주소 `s3://<rep_bucket>/<rep_key>`)는 검색 중 EDW에 접속하지 않고 gold `doc`의 `rep_key`(적재 때 ParsingMeta에서 복사)로 만든다. ParsingMeta 조회 길은 없앤다. 0.2.0.
- 결정(사용자 11-01, C8 바꿈): pgvector에는 거르기 메타만 — 대표 결과 위치(`rep_bucket`·`rep_key`)·파싱 시각·원본 sha256은 EDW ParsingMeta에만 두고 원문 도구가 부를 때 읽는다. 연결은 `source_system` + `source_key`(원본 전체 경로 = gold `doc.s3_key`, 사용자 선택 C — 경로 그대로).
- 구현(11-01 `feature/mcp-ops-parity`): 처음엔 적재 때 gold doc에 복사했으나 위 결정으로 되돌렸다. 검색 중 조회 길(`shaping._pm_db`·`_rep_uri`·`find_rep_path`·`find_by_doc_key`)과 `MCP_EVIDENCE_PATHS`는 지운 그대로. `search` 근거에는 `rep_uri`가 없고(운영 12칸), 결과 위치는 `list_doc_fulltext`가 ParsingMeta에서 읽어 `rep_uri`로 낸다([mc-17](#mc-17)). 읽기 함수: `common/store/parsing_meta_db.py` `rows_where`·`rows_parsed`·`pick_rep`.
- Status: done(11-01)

<a id="mc-16"></a>
## mc-16 · `search` 운영 계약 구현
- 결정(사용자 10-31 범위 축소 grill): 필터는 **데이터 있는 것만** 먼저: sf_op_name·contract_id·project_id는 출처 열이 정해지면(D-1) 추가. doc_class(pl-33 유지)·FAQ_group은 남김.
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) M1·T1): `search`를 운영 계약 그대로 구현한다 — `question` 필수, 필터 11종, 출력 축소. 기준 명세는 운영 `05_mcp_tools_schema.md` §2(git 밖). MCP 계약 변경이라 검토 등급 A, 새 판.
- 운영 계약(사용자 10-30 PRD grill A9 — 사용자 로컬 reference의 MCP 규약 최신판에서 필터 이름·뜻·출력 칸만 옮김):
  - 입력: `question` 필수(비면 오류 — 거르기만 하는 방식은 없음) · `k` 기본 8, 상한 50(넘으면 50으로 줄임).
  - 거르기(모두 AND, 같은 거르기의 목록은 OR, 맞는 값이 없으면 오류가 아니라 빈 결과, 모르는 인자는 무시):
    - `source_system` — **필수, 값 하나**(G20 — 그 시스템의 gold 스키마만 찾음, 여러 시스템은 여러 번 부름) · `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`(A2) · `-test` 별칭도 받음(G4).
    - `client` — 고객 이름 하나 또는 목록(OR). 우리 결정은 EDW에서 조인한 고객(`client_edw`)만 본다([mc-05](#mc-05), C6 — 운영처럼 본문 라벨로 대신하지 않음). `client_like`(`true`) — `client`와 함께 쓰는 유일한 부분 일치.
    - `project_id` — SFDC 프로젝트 코드.
    - `division` — EDW에 실제 있는 값을 그대로 받는다(`CD`·`DS`·`DP`는 예 — 허브 10-31).
    - `service_type` — `CDO`·`CMO DS`·`CMO DP`·`ADC`·`mRNA`·`New Platform`·`CMO DS (MTOP Shared)`.
    - `FAQ_group` — FAQ 시트 값(DP·FMD·Study·Facility·Regulatory·Analytical·DS·CLD·Others) — FAQ만([extract.md#pl-39](extract.md#pl-39)).
    - `doc_class` — `source_system`과 함께(SFDC 또는 LAS 분류값 — [transform.md#pl-33](transform.md#pl-33)).
    - `sf_op_id`·`sf_op_name` — SFDC 영업 기회 id(18자 `006…`)·이름.
    - `contract_id` — 계약 번호(CRMS 계약 코드, LAS 관리 번호).
    - `created_since`·`created_until` — 원천 등록 시각(시간대 없으면 KST). `created_at`이 없는 문서는 빠진다.
  - "하드 거르기 최소 1개"는 권고만(G5).
  - 출력 맨 위: `question` · `evidence[]`(길이 k) · `evidence_status`(`found`·`weak`·`none`) · `filter`(정규화한 거르기 메아리) · `scope_docs`(맞은 문서 수, 0도 정상).
  - `evidence[]` 항목: `text` · `file_name`(`list_doc_fulltext`로 잇는 다리 — [mc-17](#mc-17)) · `page` · `line` · `section` · `client` · `contract_no` · `doc_date` · `version` · `superseded` · `chunk_key`, 그리고 `file_path`(Object Storage 원본 경로 — 아래 '운영과 다른 점' ⑤) — 모두 12칸(`EVIDENCE_KEYS`).
  - (11-03 뒤집힘 — 사용자: 코드가 맞음, `file_path`는 근거 12칸에 남는다) `file_path` 키 제거(사용자 10-30 "mcp 기능에서 제거될 것이니 pass" · "reference 기준으로 하면 file_path 관련 부분 뺄거라 제거 대상으로 간주만 하고 일단 pass", D1 — 이 행에서만 다룸): gold `doc.file_path` 삭제([load-schema.md#pl-25](load-schema.md#pl-25))와 함께 0.2.0(C1·C2), 계약 변경이라 등급 A. 열린 점: 운영 `chunk_key`는 `<file_path>:<순번>` 꼴 — `file_path`를 빼면 키 바탕(`s3_key` 등)을 정해야 함 → 해소(10-31 결정 — `<doc_id>:<seq>`, 아래).
- 결정(허브 10-31, 최신 결정 우선): 거르기 이름은 위 그대로 고정(계약). 스키마마다 거르기 이름 → 그 EDW 원본 칸 이름(D-1) 대응표를 코드에 하나씩 둔다. 근거 `client` = `client_edw`, `clients_doc`은 따로 참고 칸([mc-05](#mc-05)). 목록 값(`division` 등)은 예 — EDW에 있는 값을 받는다.
- 필터용 칸 `doc_class`·`created_at`은 gold `doc`에 Alembic으로 더한다(M4 — [load-schema.md#pl-25](load-schema.md#pl-25)).
- 남은 확인: 운영 MCP 서버 소스는 없음 — 명세 기준으로 새로 구현, 구하면 대조.
- 파일: `mcp_server/routers/`, `mcp_server/schemas/`, `mcp_server/services/search/`.
- 결정(2차 grill(사용자 10-30, 원본은 git 밖)):
  - G4: `source_system` 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`로 통일, `-test`가 붙은 입력(`SFDC-test` 등)도 같은 뜻으로 받는다(두 도구 모두).
  - G5: "하드 필터 최소 1개"는 권고만 — 강제하지 않는다.
  - G6: `search` 속도 목표는 두지 않는다.
  - G20(4차 grill(사용자 10-30)): `source_system`은 **필수, 값 하나** — 그 시스템의 gold 스키마만 찾는다([load-schema.md#pl-28](load-schema.md#pl-28)). 여러 시스템은 클라이언트가 여러 번 부른다.
  - G7 → 사용자 10-30 PRD grill C1·C2로 바뀜: 0.1.0(10-30 릴리스)에는 들어가지 않았고 0.2.0에 싣는다. 1.0 전에는 MINOR에서도 계약·스키마를 깰 수 있다(버전 규칙 — 운영이 안정되면 1.0.0).
- 결정(사용자 10-30 PRD grill): A9 — 필터·출력 축소 기준은 사용자 로컬 `reference/`(git 밖, 비밀값 포함 — 커밋·인용 금지)의 MCP 규약 문서를 보고 운영 최신판으로 이 행에 옮겨 적는다(필터 이름·뜻·출력 칸만, 접속 정보·회사 데이터 없이). D1 — MCP 근거의 `file_path` 없애기는 이 행 하나로 합친다(mc-01·pl-25·op-04에는 이 행 링크만).
- (10-31 뒤집힘 — `<doc_id>:<seq>`, 아래) 결정(사용자 10-31 grill): 근거 `chunk_key`는 `<doc_key>:<순번>`(doc_key = 원본 내용 sha256, 계약 함수 `make_chunk_key`)으로 바꾼다 — 운영의 `<file_path>:<순번>`을 대신하며 file_path 제거와 함께 0.2.0, 등급 A.
- 결정(사용자 10-31 grill): 근거 `chunk_key`는 `<doc_id>:<seq>`(gold `doc.doc_id` 자동 번호 — 위 `<doc_key>:<순번>`을 뒤집음). 스키마 5벌이 시퀀스 하나를 함께 써서 겹치지 않는다(허브 제안 — 사용자 확인 11-01). `make_chunk_key`·sha256 `doc_key`는 0.2.0에 없어진다.
- 결정(사용자 11-01, reference ↔ 저장소 비교 — 0.2.0, 등급 A): 이 행에서 함께 지운다 — 이름 붙은 색인(`index_id`·AD41 코드·`deploy/host/compose/compose.index.yml`), 질문 없는 덤프 방식, 옛 입력 `methods`·`decompose`·`limit`, 옛 출력 `subs`·`store`·`images`·`notes`·`ms`와 근거 칸(운영 계약 밖).
- 구현(11-01 `feature/mcp-ops-parity`, 등급 A — MCP 계약·DB 스키마): 운영 계약 그대로 — `question` 필수(빈 글자 → `{"error"}`, 빠지면 MCP 스키마 오류) · `k` 기본 8·상한 50 · 거르기 13칸(`source_system`·`client`+`client_like`·`project_id`·`division`·`service_type`·`FAQ_group`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`·`created_since`·`created_until`, 모두 AND·목록은 OR·정확 일치) · 맨 위 5칸·근거 12칸(`mcp_server/schemas/evidence.py`). 덤프 방식·`index_id`·AD41 코드·`compose.index.yml`·`methods`·`decompose`·`limit`·`subs`·`store`·`images`·`notes`·`ms`·근거의 옛 칸(`rep_uri` 포함)을 지웠다. Alembic 판 `0002_search`가 한 벌 `doc`에 `doc_class`·`created_at`·`rep_key`(mc-15용 — DB 변경 한 번에)를 더하고 뷰 끝에 같은 칸을 붙인다. 적재가 `created_at`(EDW 파일 메타 또는 `rdb:csv` 배치의 `created_at` 칸 — 시간대 없으면 KST)·`doc_class`(EDW 파일 메타에 있을 때만 — 분류 단계 [pl-33](transform.md#pl-33) 전)를 채운다. 시험: `tests/server/mcp/test_search_svc.py` `_selftest_contract`(사례 표).
- 운영과 다른 점(11-02 갱신): ① 거르기 값은 문자열 하나 또는 목록(운영은 `client`만 목록). ② `source_system`은 **필수·값 하나**(G20 — 그 원천 스키마만 찾음, 빠지면 `{"error": "source_system is required …"}`, 여러 원천은 여러 번 부름 — 사용자 11-02, 원천끼리 결과를 섞지 않음). ③ `client`는 EDW 고객 `client_edw` 정확 일치만(C6) — 운영의 본문 라벨 대체·별칭 묶음 없음. ④ 원천 스키마에 없는 칸의 거르기는 0건(예: `division`은 crms만, `sf_op_id`는 sfdc만 — db_schema §2). ⑤ `chunk_key` = `<doc_id>:<seq>`(운영은 `<file_path>:<순번>`), `file_path` = Object Storage 원본 경로(운영은 서버 안 경로). ⑥ 결과가 크기 상한을 넘으면 낮은 순위 근거부터 줄이되 표시 칸은 붙이지 않는다. ⑦ 운영 결함인 `notes` 칸은 없다. ⑧ `FAQ_group`은 FAQ 적재([pl-39](extract.md#pl-39)) 뒤에 결과가 나온다.
- 11-03(사용자 grill — [load-schema.md#pl-52](load-schema.md#pl-52), 등급 A·0.2.0 MINOR): 원천 메타가 `doc.attrs`(JSONB) 한 칸으로 모인다.
  - 입력 `attrs: {키: 값 또는 목록}` — 원천(`source_system`)의 attrs 키로 정확 일치(키끼리 AND, 목록은 OR). 모르는 키는 `{"error"}`에 그 원천의 키 목록을 담는다(조용한 0건 아님). 받는 키는 사슬 파일 `fields`에서 `filter`가 있는 키 + 적재가 쓰는 `doc_class`(SFDC·LAS) — `filter`가 없는 키(분류 힌트 등)는 거를 수 없다(사슬 꼴의 "filter 없음 = 거르기 아님").
  - 옛 거르기 이름(`project_id`·`division`·`service_type`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`)은 그대로 받고 사슬의 `filter:`로 attrs 키에 잇는다(예 `project_id` → `project_code__c`). 그 원천에 잇는 키가 없으면 지금처럼 0건(④). `FAQ_group`은 청크 칸 그대로.
  - 근거 13칸 — 12칸 + `attrs`(사슬에서 `evidence: true`인 키 모두, 값이 없으면 null — 다른 근거 칸과 같은 규칙). `contract_no` = 사슬에서 `filter: contract_id`인 키의 값(없으면 null).
  - `edw_meta` 도구(인자 없이 부를 때) — 원천마다 거를 수 있는 키(`filter` 이름 → attrs 키)와 근거 키를 사슬 파일에서 `search_attrs`로 보여 준다.
- Status: done(11-01 · 11-02 pl-28 원천 스키마·client_edw 반영 · 11-03 pl-52 `attrs` 거르기·근거 칸·`search_attrs` — `feature/attrs-jsonb`, 서버 확인 refactor.md C-88)

<a id="mc-17"></a>
## mc-17 · 원문 전송 도구 `list_doc_fulltext`·`get_doc_fulltext`
- 결정(사용자 10-31 범위 축소 grill): 원문 도구 2개는 0.2.0에 **유지**(미루지 않음 — 사용자 선택 안 함).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) M2·T3): 두 도구를 더한다(운영 명세 `05_mcp_tools_schema.md` §6). 새 도구 — 계약 추가라 검토 등급 A.
- 파일: `mcp_server/routers/`, `mcp_server/services/`(새 파일).
- 결정(2차 grill(사용자 10-30, 원본은 git 밖)): G1 — 목록은 EDW `ParsingMeta`의 `doc_class`·`sf_op_id`·`parsed_at`·`rep_engine`·`created_at`(G9 — `created_since`/`created_until` 거르기·출력, `get_doc_fulltext` 생성 범위 가드)을 읽는다(운영 계약 그대로, [load-schema.md#pl-25](load-schema.md#pl-25)). G4 — `source_system` 통일·`-test` 별칭. G7 — 0.1.0에 함께 싣고 따로 MAJOR 없음.
- 결정(G19·G20 — 4차 grill(사용자 10-30), 위 G1 부분을 뒤집음): 두 도구는 EDW `ParsingMeta`를 읽지 않는다. 목록·거르기(`doc_class`·`sf_op_id`·`created_since/until`)·출력은 **시스템별 gold `doc`**에서 읽는다 — `doc`에 `rep_key`(silver 위치)와 `parsed_at`·`rep_engine`을 복사해 둔다. `get_doc_fulltext`의 등록 시각 가드도 `doc.created_at`. `source_system`은 필수, 값 하나([load-schema.md#pl-28](load-schema.md#pl-28)). EDW 장애가 원문 도구에 영향을 주지 않는다.
- (11-01 바뀜 — 대표 결과 위치는 ParsingMeta에서 부를 때 읽음, [mc-15](#mc-15)) 결정(사용자 10-30 PRD grill): C8 — 원문 전송 도구도 gold `doc.rep_key`를 읽는다(mc-15와 같음). C2 — 0.2.0.
- 결정(사용자 11-01): rep_engine 출력 없음 — 사용자 11-01, 대표 엔진 칸 삭제와 맞춤(운영과 다른 칸 하나).
- 구현(11-01 `feature/mcp-ops-parity`, 등급 A — MCP 계약 추가·DB 스키마): `mcp_server/routers/fulltext_tool.py`(등록) · `services/fulltext.py`(일) · `schemas/fulltext.py`(모양·한도). 목록: gold `doc`에서 거르기(`source_system`·`doc_class`·`sf_op_id`·`created_since/until`·`docs`, 원본 경로 `s3_key`가 있는 문서만, `doc_id` 순 — `cursor` = 마지막 `doc_id`) → 그 쪽 문서의 `s3_key`로 ParsingMeta를 한 번 읽어(active 중 최신, 원천 표기가 다르면 한 원천일 때만 대체) `rep_bucket`·`rep_key`·`parse_date`·`sha256`을 얻고, 결과 폴더 바로 아래 최신 `<이름>_<parse_date>.md`·`.json`만(`engine/`·`source.json` 제외). `docs`: 파일 이름(확장자 포함 — 경로 끝 조각) · 원본 전체 경로(정확히 하나) · 64자 `doc_key`(ParsingMeta `sha256` → 원본 경로). `since`/`until`(파싱 시각)은 ParsingMeta `parsed_at`(UTC)에서 먼저 원본 경로 집합을 구해 좁힌다(IN 목록은 500개씩 나눠 물음 — ponytail). 출력 `doc_key` = ParsingMeta `sha256`. ParsingMeta를 못 읽으면 `registry_unavailable`. sfid = `sf1.<base64url(버킷/키)>.<HMAC-SHA256>` — 서명 키 `search.server.fulltext_secret`(비면 `not_configured`, 바꾸면 발급된 sfid 전부 `bad_sfid`). 한도: docs 200 · limit 기본 50·상한 200 · get 20개 · 파일 16MB(`too_large`) · 합계 24MB(`batch_full`) · 파일 60초. 등록 시각 가드: sfid의 폴더 → ParsingMeta 원본 경로 → gold `doc.created_at`(가드를 걸 때만 EDW를 읽음). 판 0002 = `doc_class`·`created_at`·`s3_key`. 시험: `tests/server/mcp/test_fulltext.py`(ParsingMeta는 SQLite 대역).
- 운영과 다른 점: ① `rep_engine` 없음. ② `source_system` 출력은 저장값(`SFDC`) — 운영은 EDW 값(`SFDC-test`), 입력은 둘 다 받음(G4, 사용자 11-01 승인). ③ 시간대 없는 시각은 KST로 읽음(운영은 기본 시간대를 밝히지 않음). ④ 건너뜀 행에 `status` 칸 없음(운영 예시와 같음). ⑤ 목록은 gold `doc`에서 고른다 — 적재 전 문서는 나오지 않고, ParsingMeta 행이 없는 적재 문서는 `no_files`로 나온다(운영은 ParsingMeta에서 고름). ⑥ `source_system`은 선택 — G20 "필수·값 하나"는 스키마 나누기([pl-28](load-schema.md#pl-28)) 때.
- 11-02(pl-28): 목록은 원천 스키마 5벌(또는 `source_system`이 고른 하나)에서 같은 조건으로 고르고 공용 `doc_id` 순으로 합쳐 쪽을 넘긴다. ParsingMeta와는 gold `doc.file_path`(= 원본 경로)로 잇는다(`doc.s3_key` 칸은 없앰). `source_system` 출력은 스키마의 원천 이름(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`).
- Status: done(11-01)

<a id="mc-19"></a>
## mc-19 · 검색 — PG만, 실행 중 묶음 없음
- 결정(허브·사용자 11-01, [mc-01](#mc-01) B안): 서버 검색 MCP가 묶음 파일(`docs.jsonl`·`chunks.jsonl`·`meta.json`)을 실행 중에 읽지 않게 — 문서 메타(최신성 순위 L3-1)·임베딩 정보·청크 키를 PG에서 읽는다.
- 왜 따로: 검색 동작이 바뀌는 일(r 층) — 자기 PR + 평가(e2e)로.
- 파일: `mcp_server/services/search/{retriever,local,pgsearch,server_state}.py`.
- 사실(11-03 조사 — `feature/mc19-pg-search`): 검색이 실행 중에 묶음에서 읽는 것은 세 가지뿐이다.
  - ① `meta.json`의 `embed`·`embed_model`·`dim`: 질의 임베딩과 모델·차원 불일치 거부(`local.embed_query`·`common.ai.embed.query_model_mismatch`). PG에는 차원만 있다(원천 스키마마다 `corpus_stat.dim` — 한 행짜리 BM25 통계 표).
  - ② `docs.jsonl`의 `doc_date`·`version`·`superseded`·`family`: 최신성 순위(`docmeta.recency_rerank` — 구조화 때 `docmeta.doc_meta(파일 이름, 본문)`이 만듦). gold `doc`에는 이 칸이 없다.
  - ③ `chunks.jsonl`: `Retriever.key_local`을 만들지만 아무도 읽지 않는다(죽은 코드). 청크 키는 이미 PG(`<doc_id>:<seq>`).
  - 설정 `paths.mcp_bundle`(묶음 위치)은 검색만 쓴다. 고객 명부·용어 사전(`terms.py`)은 묶음이 아니라 resources 파일 — [pl-38](load.md#pl-38)(마스터를 PG `<PG_SCHEMA>_master`로)이 맡고 mc-19 범위가 아니다.
- 결정(사용자 11-03 grill 1차):
  - 최신성 4칸(`doc_date`·`version`·`superseded`·`family`)을 gold `doc`(원천 스키마 5벌)에 더한다 — 새 Alembic 마이그레이션 0004, 적재(`pgvector_load`)가 묶음 `docs.jsonl` 값으로 채운다. 순위는 지금과 같아야 한다. 검색 뷰 계약(MCP 출력)은 바꾸지 않는다. 검토 등급 A(DB 스키마).
  - 설정 `paths.mcp_bundle`은 지운다 — 남아 있으면 경고만(시작은 함).
  - 통과 기준: 바꾸기 전후 같은 PC 평가 세트에서 질문마다 상위 근거 목록이 같아야 한다(다르면 원인을 보고).
- 결정(사용자 11-03 grill 2차 — 임베딩 정보 자리):
  - 임베딩 모델 이름은 gold `doc`(원천 스키마 5벌)에 `embed_model` 칸으로 둔다 — 적재가 문서마다 묶음 `meta.json` 값으로 채운다. 이유(사용자): 나중 guard(섞인 모델 거부·그 문서만 다시 임베딩)가 문서 단위로 판단해야 해서. 한 문서의 청크는 늘 같은 모델로 임베딩되므로 `chunk`에는 두지 않는다.
  - `corpus_stat`은 남긴다 — 키워드 검색(BM25)이 검색마다 전체 청크 수·평균 길이를 읽는다(`pgsearch.py`). 없애면 검색마다 청크 표 전체를 세야 해 문서가 늘수록 느려진다.
  - `corpus_stat.dim`은 지운다 — 차원은 `chunk.embedding`의 칸 형식 `vector(차원)`에 이미 고정돼 있어 거기서 읽는다(지금 `dim`을 읽는 곳: `pgvector_load`의 차원 확인·`faq_sync`·`_drop_docs`, 시험 대역 `tests/server/mcp/pgfix.py`).
  - (제안 — 구현 때 확인) 검색의 모델 확인: 질의 임베딩 모델 ≠ 그 스키마 gold `doc.embed_model`(값이 둘 이상이면 섞임 — 거부하고 알림)이면 지금처럼 거부한다.
- 범위(사용자 11-03 — 허브 전달): 0.2.0에 넣는다.
- 구현(11-03 `feature/mc19-pg-search`):
  - 최신성 칸은 `doc_date` 하나만 더했다 — 1차 결정(4칸) 뒤 최신성 순위가 [pl-38](load.md#pl-38)에 지워져(`retriever.py` 주석·`CommonText.search_recency` 지운 칸), 묶음에서 근거로 나가는 값은 `doc_date`뿐이었다. `version`은 근거에서 원천 manifest 값만(`shaping._evidence`), `superseded`는 늘 null(mc-05), `family`는 pl-38에 지움 — 셋 다 검색이 읽지 않아 칸을 만들지 않는다(필요해지면 새 판).
  - 판 `0004_doc_embed.py`: 5벌 `doc`에 `content_date TEXT`(문서에 적힌 날짜 — docmeta가 본문·파일 이름에서 찾은 ISO 글자, `YYYY-MM`·`YYYY`도 있어 DATE가 아님 — 본문의 연도만은 `2026년` 꼴일 때만(맨 연도 숫자는 안 셈, 파일 이름 연도는 셈 — 11-03 F6b). 사용자 11-03: DB 칸 이름은 무슨 날짜인지 드러나게 — 파일 생성·수정 시각이 아니고 원천에 수정 날짜도 없어 `doc_created_at`이 아닌 `content_date`, 등록 시각 `created_at`과 다름. MCP 근거 이름은 `doc_date` 그대로)·`embed_model TEXT` 더함, `corpus_stat.dim` 지움. 모델 `search_tables.DOC_META`. 검색 뷰 `v_chunk_source`는 그대로.
  - 적재(`pgvector_load._load_src`)가 `content_date`(묶음 docs.jsonl `doc_date`)·`embed_model`(묶음 meta.json)을 채움. BM25 통계는 `_corpus_stat_sql` 한 곳(차원 없음).
  - 검색: `pgsearch.index_meta(db)` — 모델 = 그 스키마 `doc.embed_model`(여럿이면 쉼표로 이어 질의 모델과 같을 수 없어 `embed_query`가 거부 — 섞인 색인), 차원 = 벡터 칸 형식(벡터가 없으면 0 — 키워드·ID만). 근거 `doc_date`는 `pgsearch.search`가 `doc.content_date`를 JOIN해 읽음. `Retriever(retrieve, pg)` — 묶음 인자·`BundleDocs`·`doc_meta`·`key_local` 지움. `server_state`는 원천마다 Retriever를 만듦(적재 판이 바뀌면 다시 — 색인 정보도 새로 읽음).
  - 설정 `common.paths.mcp_bundle` 지움 — 지운 칸 표(`common.config.layout.REMOVED`)라 남아 있으면 경고만, `migrate`는 "삭제됨"으로 알림. `mcp_server.cli.ask --bundle`·`pgsearch search --bundle`은 받기만(옛 호출 호환).
  - 통과 확인: 같은 묶음(문서 5건·청크 165)·같은 질문(rag_qa 4 + 문서마다 1 = 9) × 원천 4 × 방법 3(전체·벡터·키워드+ID) = 검색 108번 — develop `479f7cc`와 이 판의 상위 8 근거(순위·경로·청크 키·쪽·`doc_date`·via·점수)가 모두 같음(SQLite 대역, 유료 호출 없이 토큰 해시 임베딩 — 벡터 경로 포함). 서버 확인은 refactor.md C-87.
- Status: done — 0.2.0(11-03)

<a id="mc-18"></a>
## mc-18 · `parse_document` 스캔 PDF 다시 지원
- 결정(사용자 10-31): 지금은 스캔 PDF를 건너뛰고 안내만 보내지만 추후 다시 살린다. 이 행이 그 기억이다.
- 옛(11-01 — [pl-03](transform.md#pl-03)): 엔진 범위가 stack 하나라 `.pdf_image`(VLM 엔진뿐)를 서비스가 돌리지 않아 빈 결과 + "추후 지원 예정" 안내만 보냈다(아래 11-03에 바꿈).
- 결정(사용자 11-03): 내부망 VLM(`qwen_vlm` — stack `.pdf_image`)으로 파싱한다. ① 시간 상한은 작업 제한 시간(`pipeline.service.parse_mcp.job_timeout_sec`, 기본 600초) 하나 — 쪽 수 상한 없음, 넘으면 지금의 시간 초과 오류. ② 큐는 하나 그대로(긴 스캔 작업 뒤의 글자 문서는 기다림). ③ VLM 설정(`common.models.vlm` 주소·모델)이 비면 파이프라인 없이 빈 결과 + "스캔 PDF — VLM 미설정". ④ VLM이 돌았는데 결과가 없으면 "스캔 PDF — VLM 파싱 실패"(DRM 추정 아님). ⑤ 글자층과 스캔 쪽이 섞인 PDF는 범위 밖(pl-03 10-29 결정).
- 한 것(`feature/mc18-scan-vlm`): ① 스캔 판정은 run_all과 같은 `parse_qa.pdf_kind`(전체 쪽 글자층이 쪽당 평균 20자 미만)를 서비스도 빌려 씀(`_is_scan` — 안내가 실제로 돈 엔진과 같게, 옛 첫 5쪽 표본 `_pdf_text_chars` 지움). ② 서비스가 run_all에 주던 `--engines` 목록(OCR·VLM 뺌) 지움 — OCR은 run_all이 이미 빼고(`OCR_ENGINES`) 기본은 설치된 핵심 엔진이라 `qwen_vlm`이 stack `.pdf_image`로 돎. ③ VLM 설정(`qwen_vlm`이 요구하는 VLM_BASE_URL·VLM_MODEL — `registry.missing_env`)이 비면 파이프라인 없이 "스캔 PDF — VLM 미설정". ④ 대표 결과가 없으면 스캔은 "스캔 PDF — VLM 파싱 실패", 그 밖은 옛 DRM 추정 그대로. ⑤ 작업 제한 시간을 단계마다 남은 시간으로 나눠 줌(옛: prepare·run_all·parse_qa·represent가 저마다 전체 시간 — 결정 ①을 지키게). 옛 안내 `SCAN_NOTE` 지움. MCP 출력 칸은 그대로(스캔 PDF의 `engine`이 `qwen_vlm`, `text`가 채워짐, `note` 글자가 바뀜 — 사람 검토). 엔진·핸드오프 파일은 안 건드림. 외부 전송 없음 — `qwen_vlm`이 `require_internal`로 내부망 주소만 부름.
- 파일: `pipeline/mcp_parse_service.py`, `tests/server/pipeline/test_parse_svc.py`.
- Status: done

<a id="mc-06"></a>
## mc-06 · `query_edw` 도구 — 읽기 전용 EDW SQL
- 이유: 정형 질문은 회사 EDW에서 답한다.
- 무엇: SELECT/WITH 하나만, 표 허용 목록(mssql: 기본 꺼짐 — `EDW_QUERY_TABLES_STRICT=0`이면 시스템 카탈로그를 뺀 모든 스키마 허용, sqlite 대역은 함께 든 목록), 행·시간·바이트 상한, 낮은 권한의 별도 로그인, PC 시험용 sqlite 대역.
- 파일: `mcp_server/services/edw_query.py`, `mcp_server/services/edw_calls.py`.
- 배포 주의(reference 비교(사용자 grill 10-30, 원본은 git 밖) T14): `query_edw` 가드의 오탐(정상 SELECT 거부)을 서버에서 확인.
- 결정(사용자 11-03): 행 상한 1,000행 — 운영 서버와 같게. 설정 기본(`search.edw_query.max_rows`, `EDW_QUERY_MAX_ROWS`)과 도구 기본값 `max_rows`를 함께 2000 → 1000(10-22에 둘 다 2000으로 올렸던 것을 되돌림). 도구 계약(tools/list) 바뀜 — 등급 A(사람 검토), 바이트·SHA-256 전후는 `tests/server/mcp/test_call_log.py`(`feature/mcp-limits`).
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
- 스캔 PDF: 내부망 VLM으로 파싱한다([mc-18](#mc-18), 11-03). VLM 설정이 없으면 빈 결과 + "스캔 PDF — VLM 미설정", 실패면 "스캔 PDF — VLM 파싱 실패".
- 결정(사용자 11-03): 파일 크기 상한 100 MB, 처음부터 끝까지. 한 것(`feature/mcp-limits`): ① 상한은 칸 하나 `common.runtime.parse_max_mb`(파일 자리 `ops.runtime.parse_max_mb`, 옛 env 이름 `PARSE_MCP_MAX_MB`, 기본 100 — MB = 1024×1024바이트)를 검색 MCP와 파싱 서비스가 같이 읽는다(옛 `ops.services.parse_mcp.max_mb` 기본 64는 지움 — 남아 있으면 경고만). ② 검색 MCP: 상한을 넘는 `content_b64`는 서비스로 보내지 않고 바로 `{"error": "파일이 크기 상한(100MB)보다 큼(…MB) — ops.runtime.parse_max_mb"}`. HTTP 요청 본문 상한(MCP SDK 기본 4 MiB — 그동안 base64 길은 약 3 MB에서 413으로 막혀 있었음)을 상한의 1.5배 + 1 MiB로 올림. 본문 상한은 `/mcp` 주소 하나라 모든 도구에 걸리므로, 4 MiB보다 크거나 길이를 밝히지 않은 요청은 동시에 2개까지만 처리하고 나머지는 본문을 읽기 전에 기다린다(거부 아님 — 4g 컨테이너 메모리 보호, `mcp_server/main.py` `_BIG_SLOTS`, PR #110 리뷰). 서비스 등록 요청 대기 10초 → 60초(등록 시간도 `time_out_threshold` 안에 셈). base64 크기는 줄바꿈·공백을 빼고 셈(MIME 줄바꿈 base64도 같은 값). ③ 파싱 서비스: 경로(`path`)로 준 파일도 같은 상한으로 거름(전에는 base64만), 본문 상한을 파일 상한의 1.5배 + 1 MiB로(검색 MCP와 같은 식)(전에는 파일 상한 + 64 KB라 base64 본문이 상한의 3/4에서 막힘). 시험 `tests/server/mcp/test_parse_limit.py`·`tests/server/pipeline/test_parse_svc.py`(상한 1 MB로 덮고 0.9 MB 받음·1.1 MB 거부, 두 길). PC 실측(99 MB·101 MB PDF, 실제 서비스+MCP HTTP)은 커밋 메시지·refactor.md C-85. 도구 설명의 "64MB 상한" → "기본 100MB 상한"으로 도구 계약(tools/list) 바뀜 — 등급 A.
- Status: done

<a id="mc-09"></a>
## mc-09 · 서버 실행과 안전
- 이유: 공용 내부 서비스라 계속 떠 있어야 하고 위험한 노출은 거부해야 한다.
- 무엇: FastMCP streamable HTTP(`/mcp`, 기본 127.0.0.1:8765) 또는 `--stdio`. loopback이 아닌 주소는 `MCP_TOKEN` 필요(상수 시간 비교), 0.0.0.0 거부, DNS 리바인딩 가드, `/health`(준비 중이면 503), 동시 8 + 대기열 + 도구 시간 30초, 새 적재 판이면 다시 읽기, `query_edw` 호출을 포함한 jsonl 질의 기록(90일).
- 파일: `mcp_server/main.py`, `mcp_server/routers/dispatch.py`, `mcp_server/config.py`.
- 배포 주의(reference 비교(사용자 grill 10-30, 원본은 git 밖) T14): 질의 기록(`qa_log.jsonl`) 경로를 컨테이너에서 쓰기 가능한 곳으로.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작(알아 둘 동작 — 열린 결함 없음)
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| `query_edw` 표 허용 목록 | mssql에서 기본 꺼짐(`EDW_QUERY_TABLES_STRICT=0` → 시스템 카탈로그를 뺀 모든 스키마) | `edw_query.py` | — (mc-06 done) |

(정리 11-03: 숨김 문서 키 비교 mc-14는 dropped, 파싱 결과 경로 mc-15는 11-01에 칸째 지움, 로컬 묶음 거르기 mc-01은 검색이 PG만이 되며 없어짐.)

### 요건 없는 코드 — 남길지(앵커를 씀) 지울지([test.md#e2-18](test.md#e2-18))
- (11-01 지움 — [mc-15](#mc-15)) `AI.ParsingMeta`에서 근거의 파싱 결과 경로(`MCP_EVIDENCE_PATHS`).
- 질문 개체로 동점 가르기(늘 켬 — 스위치는 op-08에 지움). `search_svc.py`.
- PG 대역(PG 접속 칸이 없으면 SQLite — PC·이미지 selftest). `common/store/pg_standin.py`.
- (지움) 문서 대장 CLI `mcp_server/cli/registry_cli.py` — 지금 `mcp_server/cli/`에는 `ask`·`mcp_smoke`만.

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| `query_edw` | `EDW_QUERY=1` | `common.connections.rdb` + 읽기 계정, 또는 `RDB_SQLITE` |
| `edw_meta` | — | `EDW_META_DIR`의 자료(기본 `/app/config/edw_meta`) |
| `parse_document` | OCR/VLM 엔진 없음(OCR 스위치는 0.2.0에 지움 — pl-46) · 제한 글자 쪽당 1초, VLM 쪽당 60초 | `mcp_parse_service` 실행 + `PARSE_SERVICE_TOKEN` |

### 10-29에 지운 기능(사용자 결정)
- 검색 재순위(`SEARCH_RERANK`, `common.models.rerank`) — `34f398e`.
- LLM 질문 분해(`MCP_DECOMPOSE`, `DECOMPOSE`, 프롬프트 `query_decompose`). 고객별 나누기는 남김 — `dd3e974`.
- 검색 방법 graph, concept, image, openviking — `9e58c71`.
- OpenViking 전부(적재, 요약 가져오기, 검색, 감지, 설정) — `c07dde5`.
- `search`는 입력 스키마를 유지한다: vector·bm25·id 밖의 `methods`와 `decompose`는 받고 무시한다. 응답에는 `"images": []`, `"subs": []`가 남는다.
