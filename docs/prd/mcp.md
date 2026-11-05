# 검색 MCP

[PRD.md](../PRD.md)의 카테고리 하나 — 이미지 `mcp-server`. 도구 계약(이름, 입력, 출력, `tools/list` 순서)은 고정이다 — 협의와 새 판으로만 바꾼다([CLAUDE.md](../../CLAUDE.md) §4). 도구별 입출력 표는 [operations/mcp-guide.md](../operations/mcp-guide.md)(시험 `tests/general/mcp/test_mcp_guide.py`가 코드와 대조).

순서: `search` mc-01·mc-16·mc-02·mc-05·mc-19 → 문서 키·기록 mc-10·mc-13·mc-15 → 원문 mc-17 → 다른 도구 mc-06·mc-07·mc-08·mc-18 → 서버 mc-09 → 코드와 다른 점.

<a id="mc-01"></a>
## mc-01 · `search` 도구 — 적재된 문서에서 근거 찾기
- 이유: 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구.
- 규칙:
  1. `question`과 `source_system`(값 하나)은 필수다. 그 원천의 gold 스키마(`<PG_SCHEMA>_<원천>`)만 찾는다.
  2. 거르기가 있으면 먼저 범위(맞는 문서)를 구하고, 후보 `min(50, max(3k, 30))`개를 찾은 뒤 순위를 다시 매긴다(재순위 모델 없음).
  3. 방법 `vector`·`bm25`·`id`(기본 셋 다 — `tuning.search.methods`)를 가중 RRF로 합친다. 가중치 `tuning.search.weights` — vector 1.0 · bm25 1.0 · id 2.0 · 집계 단서 질문의 bm25 0.2.
  4. vector = pgvector 코사인, HNSW(거르기 범위가 `search.pg.filter_exact_max` 문서 이하면 정확 검색). 차원이 HNSW 한도를 넘으면 `binary_quantize`로 후보를 고른 뒤 상위 200을 원 벡터로 다시 점수.
  5. BM25 = `chunk_term`·`term_stat`·`corpus_stat`(전체 청크 수·평균 길이). id = 드문 ID 정규식.
  6. 맞는 문서가 없으면 오류가 아니라 빈 결과(`scope_docs` 0, `evidence_status` none).
  7. `evidence_status`: 근거 없음 → `none`, 질문 핵심어가 근거에 없으면 `weak`, 그 밖 `found`. 근거 목록은 줄이지 않는다(표시만).
  8. 응답 JSON이 `tuning.search.output.max_chars`(기본 20000바이트, UTF-8)를 넘으면 가장 낮은 순위 근거부터 본문을 반으로(300자를 넘는 것만, 질문 낱말 주변을 남김), 더 줄일 게 없으면 가장 낮은 순위 근거를 통째로 뺀다. 1위 근거는 그것만 남을 때까지 지킨다. 줄였다는 표시 칸은 붙이지 않는다.
- 데이터: 입력·출력 칸은 [mc-16](#mc-16). 질문 없이 문서 고르기는 `list_doc_fulltext`([mc-17](#mc-17)).
- 파일: `mcp_server/routers/`, `mcp_server/services/search/{search_svc,retriever,pgsearch,shaping}.py`, `mcp_server/schemas/evidence.py`.
- QA: `tests/server/mcp/test_search_svc.py` · 통과.
- Status: done

<a id="mc-16"></a>
## mc-16 · `search` 입력·출력 계약
- 이유: 운영 MCP 규약(필터 이름·뜻·출력 칸)과 같은 계약으로 클라이언트를 붙인다.
- 입력:
  - `question` 필수 — 빈 글자면 `{"error": …}`, 빠지면 MCP 스키마 오류. `k` 기본 8, 상한 50(넘으면 50으로 줄임 — 오류 아님).
  - 거르기 14칸(`SEARCH_FILTERS`): `source_system` · `client` · `client_like` · `project_id` · `division` · `service_type` · `FAQ_group` · `doc_class` · `sf_op_id` · `sf_op_name` · `contract_id` · `created_since` · `created_until` · `attrs`. 모두 AND, 같은 칸의 목록은 OR, 정확 일치. 모르는 인자는 무시.
  - `source_system` — `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other` 중 하나. 끝에 `-test`가 붙은 값(`SFDC-test`)도 같은 뜻. 없으면 `{"error": "source_system is required — exactly one of SFDC, CRMS, LAS, FAQ, Other…"}`.
  - `client` — 글자 하나 또는 목록, 적재 때 EDW에서 조인한 고객 `client_edw`와 정확 일치. `client_like: true`면 부분 일치.
  - `created_since`·`created_until` — gold `doc.created_at`(원천 등록 시각)과 비교. 시간대 없는 값은 KST. 날짜만이면 since = 그날 00:00, until = 그날 끝까지. `created_at`이 없는 문서는 빠진다. 형식이 틀리면 오류.
  - `attrs: {키: 값 또는 목록}` — 그 원천 `doc.attrs`(JSONB)의 키로 정확 일치(키끼리 AND, 목록 OR). 받는 키 = 사슬 파일(`resources/config/edw_chain.yaml`) `fields`에서 `filter`가 있는 키 + `doc_class`(SFDC·LAS). 모르는 키는 `{"error"}`에 그 원천의 키 목록을 담는다. SQL은 `attrs @> %s::jsonb`(GIN 색인).
  - 이름 있는 거르기 `project_id`·`division`·`service_type`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`는 사슬의 `filter:`로 attrs 키에 이어진다(예 `project_id` → `project_code__c`). 그 원천에 이어진 키가 없으면 0건. `FAQ_group`은 청크 칸.
- 출력:
  - 맨 위 5칸(`SEARCH_TOP_KEYS`): `question` · `evidence[]`(최대 k) · `evidence_status`(`found`·`weak`·`none`) · `filter`(정규화한 거르기 메아리 — 빈 값 뺌, `-test` 뗌) · `scope_docs`(맞은 문서 수). `filter`·`scope_docs`는 늘 나온다.
  - 근거 13칸(`EVIDENCE_KEYS`, 값이 없으면 null): `text` · `file_name`(원본 경로의 마지막 조각) · `file_path`(Object Storage 원본 전체 경로) · `page` · `line` · `section` · `client`(= `client_edw`) · `contract_no`(사슬에서 `filter: contract_id`인 키의 값) · `doc_date`(gold `doc.content_date`) · `version`(수집 manifest 값만) · `superseded`(늘 null) · `chunk_key`(`<doc_id>:<seq>` — `doc_id`는 스키마 5벌이 함께 쓰는 시퀀스) · `attrs`(사슬에서 `evidence: true`인 키 모두 — 근거 키가 없는 FAQ·Other는 null).
- 운영과 다른 점:
  - 거르기 값은 모두 글자 하나 또는 목록(운영 명세는 `client`만 목록).
  - `source_system`은 필수·값 하나 — 여러 원천은 여러 번 부른다.
  - `client`는 `client_edw` 정확 일치만 — 본문 라벨 대체·별칭 묶음 없음.
  - 원천 스키마에 이어진 키가 없는 거르기는 0건(예: `division`은 CRMS만, `sf_op_id`는 SFDC만).
  - `chunk_key` = `<doc_id>:<seq>`(운영 `<file_path>:<순번>`), `file_path` = Object Storage 원본 경로(운영은 서버 안 경로).
  - 근거에 `file_path`·`attrs` 2칸을 더했고, 입력에 `attrs` 거르기를 더했다.
  - 크기 상한으로 근거를 줄여도 표시 칸을 붙이지 않는다. `notes` 칸은 없다.
- 파일: `mcp_server/schemas/evidence.py`, `mcp_server/services/search/search_svc.py`, `resources/config/edw_chain.yaml`.
- QA: `tests/server/mcp/test_search_svc.py`(`_selftest_contract` 사례 표) · 통과. 서버 확인 [refactor.md](../refactoring/refactor.md) C-89.
- Status: done

<a id="mc-02"></a>
## mc-02 · 질문 이해 — 넓히기
- 이유: 사용자는 동의어, 약어, 여러 고객을 한꺼번에 넣어 묻는다.
- 규칙: BM25용 용어집 넓히기 — 가중치 동의어 1.0 · 약어 0.8 · 약한 것 0.3, 고객 명부 별칭은 질문 1건당 토큰 20개까지(가중치 1.0). 용어집·명부는 PG 마스터 표(`<PG_SCHEMA>_master` — [load.md#pl-38](load.md#pl-38)). vector 질의에는 별칭 글을 붙인다. 가중치를 고르는 질문 유형은 규칙 기반(`question_type.py`).
- 파일: `mcp_server/services/search/{query_expand,question_type,search_svc}.py`.
- QA: `tests/server/mcp/test_question_type.py` · 통과.
- Status: done

<a id="mc-05"></a>
## mc-05 · 고객 범위, 판, 중복
- 이유: 답이 고객을 섞거나 옛 판을 인용하면 안 된다.
- 규칙: 고객 거르기는 `client_edw`만 쓴다(본문에서 찾은 `clients_doc`은 참고 칸). LAS는 EDW 고객이 비어 고객 거르기에서 늘 빠진다. 이름만 바뀐 사본은 한 자리로 합친다. 근거 `version`은 수집 manifest 값만(없으면 null), `superseded`는 늘 null(본문으로 판을 추정하지 않음).
- 남은 한계: 같은 문서의 다른 판이 `s3_key`가 달라 둘 다 나올 수 있다 — [load.md#pl-56](load.md#pl-56).
- 파일: `mcp_server/services/search/{search_svc,shaping}.py`.
- QA: `tests/server/mcp/test_search_svc.py`(`_selftest_evidence_rdb_meta`) · 통과.
- Status: done

<a id="mc-19"></a>
## mc-19 · 검색 — PG만, 실행 중 묶음 없음
- 이유: 서버 검색이 묶음 파일(`docs.jsonl`·`chunks.jsonl`·`meta.json`)에 기대지 않게.
- 규칙:
  1. 검색은 PG만 읽는다. 묶음 경로 설정은 없다.
  2. 색인 정보(`pgsearch.index_meta`): 모델 = 그 스키마 `doc.embed_model`의 값(여러 값이면 쉼표로 이어 질의 모델과 같을 수 없음 → 벡터 검색 거부), 차원 = `chunk.embedding`의 `vector(차원)` 형식(벡터가 없으면 0 — 키워드·ID만).
  3. 질의 임베딩 모델이 색인 모델과 다르면 거부한다.
  4. 근거 `doc_date`는 `doc.content_date`(문서에 적힌 날짜 — ISO 글자, `YYYY-MM`·`YYYY`도 있음)를 JOIN해 읽는다.
  5. 적재 판이 바뀌면 원천마다 Retriever와 색인 정보를 다시 읽는다(`server_state`).
- 데이터: 판 `0004_doc_embed`(5벌 `doc`에 `content_date TEXT`·`embed_model TEXT`, `corpus_stat.dim` 없음) — [architecture/db_schema.md](../architecture/db_schema.md).
- 파일: `mcp_server/services/search/{retriever,pgsearch,server_state}.py`.
- QA: `tests/server/mcp/` 검색 시험(SQLite 대역 `tests/server/mcp/pgfix.py`) · 통과. 서버 확인 refactor.md C-87.
- Status: done

<a id="mc-10"></a>
## mc-10 · 근거의 문서 키·이름
- 규칙: 문서 키·이름은 PG 뷰 `v_chunk_source`에서 읽는다 — `file_path`, `file_name` = 경로의 마지막 `/` 뒤.
- 파일: `mcp_server/services/search/retriever.py`.
- QA: `tests/server/mcp/test_mc10_doc_key.py` · 통과.
- Status: done

<a id="mc-13"></a>
## mc-13 · 질의 기록은 DB `applog.mcp_log`만
- 규칙: 질의 기록 파일은 없다(사용자 11-04 — op-13 규칙 7). MCP 호출마다 `applog.mcp_log` 한 행(op-01)이 질문·SQL(`args`)과 근거 키(`result_keys`)를 남긴다. `search.query_log` 칸은 지웠다(옛 설정 파일에 남으면 시작 거부). MCP를 거치지 않는 PC 명령 `mcp_server.cli.search_ask`는 기록하지 않는다.
- 파일: `mcp_server/services/call_log.py` · `mcp_server/services/search/search_svc.py` · `mcp_server/services/edw_query.py`.
- QA: `tests/server/mcp/test_call_log.py` · 통과.
- Status: done

<a id="mc-15"></a>
## mc-15 · 대표 파싱 결과 위치는 ParsingMeta에서
- 규칙: pgvector에는 거르기 메타만 둔다. 대표 결과 위치(`rep_bucket`·`rep_key`)·파싱 시각·원본 sha256은 EDW `AI.ParsingMeta`에만 있고, 원문 도구([mc-17](#mc-17))가 부를 때 읽는다. 연결 = `source_system` + 원본 전체 경로(gold `doc.file_path` = ParsingMeta 원본 키). `search` 근거에는 `rep_uri`가 없다.
- 파일: `common/store/parsing_meta_db.py`(`rows_where`·`rows_parsed`·`pick_rep`).
- QA: `tests/server/mcp/test_fulltext.py` · 통과.
- Status: done

<a id="mc-17"></a>
## mc-17 · 원문 전송 도구 `list_doc_fulltext`·`get_doc_fulltext`
- 이유: 클라이언트가 근거의 원 파싱 결과(.md·.json)를 받는다.
- 규칙:
  1. 목록: 원천 스키마 5벌(또는 `source_system`이 고른 하나)의 gold `doc`에서 거른다 — `source_system`·`doc_class`·`sf_op_id`(둘은 `attrs` 키)·`created_since/until`·`docs`. 공용 `doc_id` 순으로 합치고 `cursor` = 마지막 `doc_id`.
  2. `docs` 항목은 파일 이름(확장자 포함 — 경로 끝 조각) · 원본 전체 경로(정확히 하나) · 64자 `doc_key`(ParsingMeta `sha256`) 중 하나.
  3. 고른 문서의 `file_path`로 ParsingMeta를 한 번 읽어 `pick_rep`로 행 하나를 고른다 — active 중 최신, active가 없으면 전체 중 최신(파싱 상태는 보지 않음). 원천 표기가 다르면 한 원천일 때만 대체.
  4. 파일 = 결과 폴더 바로 아래 최신 `<이름>_<parse_date>.md`·`.json`만(`engine/`·`source.json` 제외). 출력 `doc_key` = ParsingMeta `sha256`, `source_system` = 스키마 원천 이름(`SFDC` 등).
  5. `since`/`until`(파싱 시각)은 ParsingMeta `parsed_at`(UTC)으로 먼저 원본 경로 집합을 구해 좁힌다(IN 목록은 500개씩).
  6. sfid = `sf1.<base64url(버킷/키)>.<HMAC-SHA256>`, 서명 키 `required.tokens.fulltext`.
  7. `get_doc_fulltext`의 등록 시각 가드: sfid 폴더 → ParsingMeta 원본 경로 → gold `doc.created_at`.
  8. 한도: `docs` 200 · `limit` 기본 50, 상한 200 · get 한 번 20개 · 파일 16 MiB(`too_large`) · 합계 24 MiB(나머지 `batch_full`) · 파일 하나 60초.
  9. 오류: 서명 키가 비면 `not_configured` · 키를 바꾸면 옛 sfid는 `bad_sfid` · ParsingMeta를 못 읽으면 `registry_unavailable` · Object Storage를 못 읽으면 `source_storage_unavailable` · ParsingMeta 행이 없는 적재 문서는 `no_files`.
- 운영과 다른 점:
  - `rep_engine` 출력 없음.
  - `source_system` 출력은 저장값(`SFDC`) — 운영은 EDW 값(`SFDC-test`). 입력은 둘 다 받는다.
  - 시간대 없는 시각은 KST로 읽는다.
  - `get_doc_fulltext`의 건너뜀 행에 `status` 칸이 없다(`skip_reason`만).
  - 목록은 gold `doc`에서 고른다 — 적재 전 문서는 나오지 않는다(운영은 ParsingMeta에서 고름).
  - `pick_rep`는 파싱 상태를 보지 않고, active가 없으면 active 아닌 최신 행으로 대체한다(운영은 active·성공·위치 있는 행만).
  - 등록 시각 가드는 검색 DB(gold `doc.created_at`)에서 읽는다.
  - `docs`에 원본 전체 경로도 받는다.
- 파일: `mcp_server/routers/fulltext_tool.py`, `mcp_server/services/fulltext_svc.py`, `mcp_server/schemas/fulltext.py`.
- QA: `tests/server/mcp/test_fulltext.py`(ParsingMeta는 SQLite 대역) · 통과. 서버 확인 refactor.md C-75.
- Status: done

<a id="mc-06"></a>
## mc-06 · `query_edw` 도구 — 읽기 전용 EDW SQL
- 이유: 정형 질문은 회사 EDW에서 답한다.
- 규칙: SELECT/WITH 문 하나만. 낮은 권한의 읽기 계정(`required.edw.read_*`)으로 연다. 상한 — 행 `search.edw_query.max_rows` 1000(도구 인자 `max_rows` 기본 1000과 작은 쪽) · 시간 20초 · 응답 2,000,000바이트. 표는 시스템 카탈로그를 뺀 모든 스키마를 허용한다(설정 허용 목록 없음 — 좁히기는 읽기 계정 권한). PC는 sqlite 대역(`valid_env/edw/edw.sqlite` — 대역 표 아홉 허용).
- 파일: `mcp_server/services/edw_query.py`, `mcp_server/services/edw_calls.py`, `mcp_server/config.py`.
- QA: `tests/server/mcp/test_call_log.py`(tools/list 바이트·SHA-256) · 통과.
- Status: done

<a id="mc-07"></a>
## mc-07 · `edw_meta` 도구 — EDW 카탈로그 찾기
- 이유: 클라이언트는 SQL을 쓰기 전에 표·칸 이름이 필요하다.
- 규칙: 개인정보를 뺀 정적 자료(`search.edw_meta.dir`의 `catalog.json` + `columns.jsonl`)에서 3단계(스키마 → 표 → 칸)로 찾는다. 모르는 이름은 difflib 제안. 응답 200,000바이트를 넘으면 목록 꼬리를 자른다. 인자 없이 부르면 원천마다 `search_attrs`(`filter` — `search` 인자 이름 → attrs 키, `attrs` — 거를 수 있는 키 전부, `evidence` — 근거 키)를 사슬 파일에서 만들어 붙인다(요약이 오류면 붙이지 않음). LLM·벡터 없음.
- 자료 꼴(`mcp_server/services/edw_meta.py`가 읽는 칸): `catalog.json` = JSON 하나 — `tables[]`(표마다 `schema`·`table`·`qualified_name`·`table_desc_ko`·`row_count`·`data_period`·`column_count` 등) + `meta`(`as_of`·`schemas`). `columns.jsonl` = 한 줄에 열 하나 — `schema`·`table`·`column_name`·`data_type`·`nullable`·`description_ko`·`primary_key`·`foreign_key`·`fk_reference` 등. 개인정보가 없는 자료만 둔다(표본 값은 응답에 내지 않는다).
- 서버 자리: 저장소에 자료와 만드는 스크립트가 없다. 운영자가 폴더를 `<루트>/output/edw_meta/`에 복사하고 `search.edw_meta.dir: /app/output/edw_meta`를 적는다(결과 폴더가 검색 MCP에 읽기 전용으로 붙음). 비우면 `/app/config/edw_meta`(서버 compose는 이 자리를 붙이지 않음). 두 파일이 없으면 `edw_meta`가 `not_configured`로 답해 에이전트가 EDW 표·열 설명을 못 찾는다 — `query_edw`는 그대로 동작. 자료 받기는 refactor.md C-91.
- 운영과 다른 점: 인자 없는 호출에 `search_attrs`를 더 붙인다.
- 파일: `mcp_server/services/edw_meta.py`, `mcp_server/config.py`(`search.edw_meta.dir` 설명).
- Status: done — 서버 자료 폴더는 사람이 채움(C-91)

<a id="mc-08"></a>
## mc-08 · `parse_document` 도구 — 파일 하나를 바로 파싱
- 이유: 클라이언트가 아직 적재되지 않은 파일을 묻는다.
- 규칙:
  1. 경로(inbox 루트 아래) 또는 base64 내용을 파싱 서비스(`http://127.0.0.1:<ops.runtime.data_parsing_port>` — 기본 8766)에 Bearer 토큰(`required.tokens.mcp` — 검색 MCP와 같은 값)으로 넘긴다. 글·표·사실·엔진·시간을 돌려주고, 시간 초과면 `job_id`.
  2. 파일 크기 상한 `ops.runtime.parse_max_mb`(기본 100, MB = 1024×1024바이트)를 검색 MCP와 파싱 서비스가 같이 읽는다. base64 크기는 줄바꿈·공백을 빼고 센다. 넘는 `content_b64`는 서비스로 보내지 않고 `{"error": "파일이 크기 상한(100MB)보다 큼(…MB) — ops.runtime.parse_max_mb"}`. 경로로 준 파일도 같은 상한.
  3. HTTP 요청 본문 상한 = 파일 상한 × 1.5 + 1 MiB(검색 MCP·파싱 서비스 같음). 4 MiB보다 크거나 길이를 밝히지 않은 요청은 동시에 2개까지만 처리하고 나머지는 본문을 읽기 전에 기다린다(`mcp_server/main.py` `_BIG_SLOTS`).
  4. 서비스 등록 요청 대기 60초.
  5. 받는 확장자 = 엔진 구성의 parse 키(`pipeline/transform/parse/engine_check.py` `allowed_exts()`).
- 운영과 다른 점: 파일 크기 상한 기본 100MB(운영 64MB) · 스캔 PDF를 내부망 VLM으로 파싱([mc-18](#mc-18)) · 받는 확장자가 더 많다.
- 파일: `common/core/parse_limit.py`(크기 상한·본문 상한 — 두 쪽이 함께 씀), `mcp_server/services/parse_proxy.py`, `pipeline/parse_service.py`, `mcp_server/main.py`.
- QA: `tests/server/mcp/test_parse_limit.py`·`tests/server/pipeline/test_parse_svc.py`(상한 1 MB로 덮고 0.9 MB 받음·1.1 MB 거부, 두 길) · 통과. 서버 확인 refactor.md C-85.
- Status: done

<a id="mc-18"></a>
## mc-18 · `parse_document` 스캔 PDF — 내부망 VLM
- 규칙:
  1. 스캔 판정 = `pipeline.shared.pdf_kind.pdf_kind()`(전체 쪽 글자층이 쪽당 평균 20자 미만) — 일괄 파싱과 같은 함수.
  2. 스캔 PDF는 stack `.pdf_image`의 `qwen_vlm`으로 파싱한다(내부망 주소만 — `require_internal`).
  3. 시간 상한은 작업 제한 시간 `tuning.ops.services.data_parsing.job_timeout_sec`(기본 600초) 하나, 단계마다 남은 시간을 나눠 준다. 쪽 수 상한 없음. 큐는 하나.
  4. VLM 설정(`required.models.vlm_base_url`·`vlm_model`)이 비면 파이프라인 없이 빈 결과 + note "스캔 PDF — VLM 미설정".
  5. VLM이 돌았는데 대표 결과가 없으면 note "스캔 PDF — VLM 파싱 실패".
  6. 글자층과 스캔 쪽이 섞인 PDF는 범위 밖.
- 파일: `pipeline/parse_service.py`.
- QA: `tests/server/pipeline/test_parse_svc.py` · 통과.
- Status: done

<a id="mc-09"></a>
## mc-09 · 서버 실행과 안전
- 이유: 공용 내부 서비스라 계속 떠 있어야 하고 위험한 노출은 거부해야 한다.
- 규칙: FastMCP streamable HTTP(`/mcp`, 기본 `search.server.host` 127.0.0.1 · `port` 8765) 또는 `--stdio`. loopback이 아닌 주소는 `required.tokens.mcp` 필요(상수 시간 비교), 0.0.0.0 거부, DNS 리바인딩 가드(`search.server.allowed_hosts`). `/health`(준비 중이면 503). 도구 동시 8(`search.server.max_concurrency`) + 대기열, 도구 한 번 30초. 새 적재 판이면 다시 읽는다. 호출 감사 기록은 [ops.md#op-01](ops.md#op-01).
- 파일: `mcp_server/main.py`, `mcp_server/services/tool_runner.py`, `mcp_server/config.py`.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건 없는 코드 — 남길지 지울지
- 질문 개체로 동점 가르기(늘 켬). `search_svc.py`.
- PG 대역(PG 접속 칸이 없으면 SQLite — PC·이미지 selftest). `common/store/pg_standin.py`.

### 설정이 있어야 도는 것
| 기능 | 필요한 것 |
|---|---|
| `query_edw` | `required.edw` 읽기 계정, 또는 PC sqlite 대역 |
| `edw_meta` | `search.edw_meta.dir`의 자료 |
| `parse_document` | `mcp-data-parsing`(파싱 서비스) + `required.tokens.mcp` |
| 원문 도구 | `required.tokens.fulltext` · Object Storage 읽기 · EDW 읽기 계정 |
