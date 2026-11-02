# 검색 MCP 사용 가이드

검색 MCP 서버(`mcp-server` 이미지)에 붙는 클라이언트(답변 agent·개발자)를 위한 안내다. 도구 6개의 입력, 돌려주는 모양, 한도, 오류, 쓰는 순서를 적는다. 서버 주소·토큰 같은 접속 값은 여기에 적지 않는다. 운영 담당자에게 받는다.

- 기준: 운영 MCP 규약(05 §2~§6, 10-27 측정)을 따르고, 이 저장소의 코드(`mcp_server/routers/`·`schemas/`)와 맞춘다. 운영과 다른 곳은 **⚠ 운영과 다름**으로 표시했다.
- 이 문서의 입력·출력 표는 `tests/general/mcp/test_mcp_guide.py`가 코드(도구 서명·`schemas/`)와 대조한다. 지원 확장자 목록도 그 시험이 엔진 구성 파일·파싱 서비스 코드와 대조한다.
- 관련 요건: [mc-16](../prd/mcp.md#mc-16)(search) · [mc-17](../prd/mcp.md#mc-17)(원문 도구) · [mc-15](../prd/mcp.md#mc-15)(대표 결과 위치) · [mc-05](../prd/mcp.md#mc-05)(판·구판 칸).

## 1. 부르는 법

- MCP Streamable HTTP(JSON-RPC 2.0), 한 주소 `http://<서버>:<포트>/mcp`. 머리글 `Content-Type: application/json`, `Accept: application/json`, `Authorization: Bearer <토큰>`.
- 호출: `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"<도구>","arguments":{…}}}`. 결과는 `result.content[0].text`의 JSON 글자다(클라이언트가 파싱).
- 상태 확인: `GET /health`(토큰 없음). 기동 직후 예열하는 동안은 503 `{"warming": true}`, 끝나면 200 `{"ready": true}`.
- 토큰이 없거나 틀리면 HTTP 401 `{"error":"unauthorized"}`.
- 도구 하나의 시간 상한은 서버 설정 `MCP_TOOL_TIMEOUT_SEC`(기본 30초)다. 넘으면 `{"error":"timeout"}`. **⚠ 운영과 다름:** 운영 안내서는 60초라고 적었다. 클라이언트 쪽 제한 시간은 60초 이상으로 넉넉히 둔다.
- 동시에 돌 수 있는 수를 넘어 대기열까지 차면 바로 `{"error":"busy"}` — 잠시 뒤 다시 부른다.

## 2. 도구 목록

| 도구 | 하는 일 |
|---|---|
| `search` | 자연어 질문으로 근거 청크 상위 k개 — 거르기(문서 범위) 안에서만 |
| `query_edw` | EDW 읽기 전용 SQL(SELECT·WITH 한 문장) — 원래 행만 돌려줌 |
| `parse_document` | 파일 1건을 그 자리에서 text 파싱해 대표 결과를 돌려줌 |
| `edw_meta` | EDW 표·칸의 한글 설명(정적 자료, DB 접속 없음) |
| `list_doc_fulltext` | 문서의 대표 파싱 결과 파일(.md·.json) 목록 + 받기 손잡이(`sfid`) 발급 |
| `get_doc_fulltext` | `sfid`로 파일 내용을 받기 |

모르는 도구 이름은 JSON-RPC 오류(`isError: true`, "Unknown tool")다. 옛 이름 `list_rep_files`·`get_rep_files`는 없다.

## 3. 지원 확장자

<!-- 시험이 대조하는 목록: 바꿀 때는 resources/config/pipeline_stack.json(parse)·pipeline/mcp_parse_service.py(ALLOWED_EXTS)를 먼저 고친다 -->
- **검색 대상(파이프라인이 파싱해 적재하는 형식)** — 엔진 구성 파일 `resources/config/pipeline_stack.json`의 `parse` 표: `.bmp` `.doc` `.docx` `.eml` `.htm` `.html` `.hwpx` `.jpeg` `.jpg` `.mht` `.mhtml` `.msg` `.pdf` `.png` `.ppt` `.pptx` `.tif` `.tiff` `.txt` `.xls` `.xlsm` `.xlsx`
  - `.pdf`는 글자 PDF와 스캔(이미지) PDF를 따로 판정해 다른 엔진으로 읽는다. 압축 파일(`.zip` 등)과 위 목록 밖 형식은 파싱 대상이 아니다.
- **`parse_document`가 받는 형식** — `pipeline/mcp_parse_service.py`의 `ALLOWED_EXTS`: `.doc` `.docx` `.eml` `.htm` `.html` `.hwpx` `.mht` `.mhtml` `.msg` `.pdf` `.ppt` `.pptx` `.txt` `.xls` `.xlsm` `.xlsx`
  - 이미지 파일은 받지 않는다(그림 VLM 단계를 돌리지 않음). 스캔 PDF는 text가 비고 안내 문구가 붙는다.

## 4. `search`

검색 길(vector·bm25·id를 합쳐 순위)은 서버 설정으로만 정한다. 호출 인자로 바꿀 수 없다.

### 4-1. 입력

<!-- guide:search-inputs -->
| 이름 | 형식 | 필수 | 기본 | 한도·규칙 |
|---|---|---|---|---|
| `question` | 글자 | 예 | — | 빠지면 MCP 스키마 오류(`Field required`, 도구가 돌기 전). 빈 글자면 `{"error": "question is required — …"}` |
| `k` | 정수 | 아니요 | 8 | 상한 50 — 더 크면 50으로 줄인다(오류 아님). 근거 개수의 최대값 |
| `source_system` | 글자 또는 목록 | 아니요 | — | `SFDC`·`CRMS`·`LAS`·`FAQ`. `-test`가 붙은 값(`SFDC-test`)도 같은 뜻 |
| `client` | 글자 또는 목록 | 아니요 | — | 고객(계정) 이름 전체, 정확 일치. 목록은 OR |
| `client_like` | 참·거짓 | 아니요 | — | `true`면 `client`를 부분 일치로. `client`와 함께만 뜻이 있다 |
| `project_id` | 글자 또는 목록 | 아니요 | — | 프로젝트 코드, 정확 일치 |
| `division` | 글자 또는 목록 | 아니요 | — | 예 `CD`·`DS`·`DP`, 정확 일치(`D`는 0건) |
| `service_type` | 글자 또는 목록 | 아니요 | — | 예 `CDO`·`CMO DS`·`CMO DP`·`ADC`·`mRNA`·`New Platform`, 정확 일치 |
| `FAQ_group` | 글자 또는 목록 | 아니요 | — | FAQ 시트 이름(`DP`·`FMD`·`Study` 등) |
| `doc_class` | 글자 또는 목록 | 아니요 | — | SFDC: `Proposal`·`RFP`·`RFI`·`RFI+RFP`·`Other` / LAS: `MSA`·`PSA`·`QAG`·`LOI`·`Amendment`·`Assignment Letter`·`Other`. 제 원천의 분류값끼리만 맞음 |
| `sf_op_id` | 글자 또는 목록 | 아니요 | — | SFDC 영업 기회 id(18자 `006…`) |
| `sf_op_name` | 글자 또는 목록 | 아니요 | — | 영업 기회 이름 전체 |
| `contract_id` | 글자 또는 목록 | 아니요 | — | 계약 코드 |
| `created_since` | 글자 | 아니요 | — | 원천 등록 시각부터. `YYYY-MM-DD`(그날 00:00 KST부터) 또는 ISO 8601 시각(시간대 없으면 KST) |
| `created_until` | 글자 | 아니요 | — | 원천 등록 시각까지. 날짜만 주면 그날 전체 포함(다음 날 00:00 미만) |
<!-- /guide:search-inputs -->

규칙:
- 서로 다른 거르기는 모두 AND, 한 거르기 안의 목록은 OR. `client_like`만 부분 일치이고 나머지는 모두 정확 일치다.
- 모르는 인자(예 `"year": 2025`)는 오류 없이 무시한다.
- 거르기에 맞는 문서가 없으면 오류가 아니라 빈 결과다(`evidence: []`, `scope_docs: 0`, `evidence_status: "none"`).
- `created_since`·`created_until`을 주면 등록 시각이 없는 문서는 빠진다. 날짜 형식이 틀리면 `{"error": "created_since/created_until 형식 — …"}`.
- 거르기를 하나 이상 주기를 권한다(강제하지 않음). 범위가 좁을수록 근거가 촘촘하고 빠르다.
- **⚠ 운영과 다름:** ① 운영은 `client`만 목록을 받는다 — 여기서는 모든 거르기가 목록을 받는다(운영처럼 부르면 그대로 된다). ② `FAQ_group`은 지금 늘 0건이다 — FAQ 원천을 아직 적재하지 않았다([pl-39](../prd/extract.md#pl-39)). ③ `client`는 계정 이름 또는 문서의 고객 라벨과 정확히 맞춘다 — 운영의 고객 별칭 묶음은 없다. ④ 응답 크기가 상한(`MCP_MAX_CHARS`)을 넘으면 낮은 순위 근거부터 줄이되 표시 칸은 붙이지 않는다.

### 4-2. 돌려주는 모양

<!-- guide:search-top -->
| 칸 | 형식 | 언제 | 뜻 |
|---|---|---|---|
| `question` | 글자 | 늘 | 받은 질문 그대로 |
| `evidence` | 목록 | 늘 | 근거 청크, 순위 순. 최대 `k`개(없으면 빈 목록) |
| `evidence_status` | 글자 | 늘 | `found`(근거 있음) · `weak`(근거는 있으나 질문 핵심어가 근거에 없거나 점수가 서버 하한 미만) · `none`(근거 0개) |
| `filter` | 객체 | 거르기를 줬을 때만 | 정리한 거르기 메아리(예 `{"source_system": "SFDC"}` — `-test`는 떼어 냄) |
| `scope_docs` | 정수 | 거르기를 줬을 때만 | 거르기에 맞은 문서 수 — 검색은 이 문서들 안에서만 했다 |
<!-- /guide:search-top -->

근거 한 건(`evidence[]`)은 늘 12칸이다. 값이 없으면 `null`.

<!-- guide:evidence -->
| 칸 | 형식 | 뜻 |
|---|---|---|
| `text` | 글자 | 청크 본문(표는 행 글자로) |
| `file_name` | 글자 | 원본 파일 이름 — `list_doc_fulltext(docs=[file_name])`로 잇는 다리 |
| `file_path` | 글자 | 서버 안 원본 경로 |
| `page` | 정수 또는 null | 쪽 번호 |
| `line` | 글자 또는 null | 줄 범위(예 `"27-28"`) |
| `section` | 글자 또는 null | 절 제목 |
| `client` | 글자 또는 null | 문서 고객 |
| `contract_no` | 글자 또는 null | 계약 번호 |
| `doc_date` | 글자 또는 null | 문서 날짜 |
| `version` | 글자 또는 null | 문서 판 — 수집 목록(manifest)에 값이 있을 때만 |
| `superseded` | null | 구판 표시 — 지금은 늘 null([mc-05](../prd/mcp.md#mc-05): 본문 글자로 추정한 값은 내보내지 않음) |
| `chunk_key` | 글자 | 청크를 다시 가리키는 키 |
<!-- /guide:evidence -->

### 4-3. 예

```json
{"name": "search", "arguments": {"question": "<주제> 단가", "source_system": "SFDC", "k": 3}}
{"name": "search", "arguments": {"question": "<주제>", "sf_op_id": "006<…>"}}
{"name": "search", "arguments": {"question": "<주제>", "client": ["<고객 A>", "<고객 B>"], "doc_class": "RFI", "k": 5}}
{"name": "search", "arguments": {"question": "<주제>", "client": "<이름 일부>", "client_like": true}}
{"name": "search", "arguments": {"question": "<주제>", "project_id": "<코드>", "division": "DS", "service_type": "CDO"}}
{"name": "search", "arguments": {"question": "<주제>", "source_system": "LAS", "doc_class": "MSA", "contract_id": "<계약 코드>"}}
{"name": "search", "arguments": {"question": "<주제>", "sf_op_name": "<영업 기회 이름 전체>"}}
{"name": "search", "arguments": {"question": "<FAQ 질문>", "FAQ_group": "DP"}}
{"name": "search", "arguments": {"question": "<주제>", "source_system": "CRMS", "created_since": "2025-01-01", "created_until": "2025-06-30"}}
```

응답 예(값은 꾸민 것):

```json
{"question": "<주제> 단가", "evidence": [
  {"text": "… 단가 100 USD …", "file_name": "<파일>.pdf", "file_path": "/app/output/prepared/<파일>.pdf", "page": 3, "line": "27-28",
   "section": "가격", "client": null, "contract_no": null, "doc_date": null, "version": null, "superseded": null, "chunk_key": "<키>"}],
 "evidence_status": "found", "filter": {"source_system": "SFDC"}, "scope_docs": 1234}
```

## 5. `list_doc_fulltext` → `get_doc_fulltext`

문서의 대표 파싱 결과 파일을 두 단계로 받는다: 먼저 목록에서 `sfid`(서명된 손잡이)를 받고, 그 `sfid`로 내용을 받는다. 대표 결과 폴더의 가장 늦은 `.md`(본문)·`.json`(구조 결과)만 나온다(`engine/` 아래 엔진별 결과는 없음).

### 5-1. `list_doc_fulltext` 입력 — 조건을 하나 이상(모두 AND)

<!-- guide:list-inputs -->
| 이름 | 형식 | 기본 | 한도·규칙 |
|---|---|---|---|
| `docs` | 글자 목록 | — | 원본 파일 이름(확장자 포함 — 빼면 0건) 또는 64자 `doc_key`(섞어도 됨). 200개까지 — 넘으면 `bad_request` |
| `source_system` | 글자 | — | `SFDC`·`CRMS`·`LAS`·`FAQ`(`-test` 붙어도 같은 뜻) |
| `doc_class` | 글자 | — | 분류값, 정확 일치 |
| `sf_op_id` | 글자 | — | 영업 기회 id, 정확 일치 |
| `since` | 글자 | — | 파싱 시각부터. `YYYY-MM-DD` 또는 `YYYY-MM-DD HH:MM:SS`(시간대 없이 — KST) |
| `until` | 글자 | — | 파싱 시각까지. 날짜만이면 그날 전체 |
| `created_since` | 글자 | — | 원천 등록 시각부터(형식은 위와 같음). 등록 시각이 없는 문서는 빠짐 |
| `created_until` | 글자 | — | 원천 등록 시각까지 |
| `limit` | 정수 | 50 | 한 쪽 문서 수, 상한 200(넘으면 200) |
| `cursor` | 글자 | — | 앞 응답의 `batch.next_cursor` 그대로 |
<!-- /guide:list-inputs -->

- 조건이 하나도 없으면 `bad_request`. 날짜에 시간대를 붙이거나 형식이 틀리면 `bad_request`(`detail`에 이유).
- `docs`·`sf_op_id`는 한 고객·영업 기회로 좁히고, `doc_class`·날짜만 주면 모든 고객의 문서가 나온다.
- 맞는 문서가 없으면 빈 틀: `{"batch": {"matched": 0, "returned": 0, "next_cursor": null, "files_total_bytes": 0}, "documents": [], "ms": …}`.

### 5-2. `list_doc_fulltext` 돌려주는 모양

<!-- guide:list-output -->
| 칸 | 뜻 |
|---|---|
| `batch.matched` | 조건에 맞는 문서 수(쪽과 무관) |
| `batch.returned` | 이번 쪽 문서 수 |
| `batch.next_cursor` | 다음 쪽 손잡이, 마지막 쪽이면 `null` |
| `batch.files_total_bytes` | 이번 쪽 파일 크기 합 — 받기 계획(합계 24MB)에 씀 |
| `documents[].file_name` | 원본 파일 이름 |
| `documents[].doc_key` | 원본 sha256(64자) — 같은 이름 문서가 여럿이면 이것으로 하나를 고름 |
| `documents[].source_system` | 원천 |
| `documents[].doc_class` | 분류(없으면 null) |
| `documents[].sf_op_id` | 영업 기회 id(없으면 null) |
| `documents[].created_at` | 원천 등록 시각(KST ISO, 없으면 null) |
| `documents[].parse_date` | 파싱 시각 `YYYY-MM-DD_HHMMSS`(결과 파일 이름 끝과 같음) |
| `documents[].rep_uri` | 대표 결과 폴더 `s3://<버킷>/<폴더>/` |
| `documents[].status` | `ok` 또는 `no_files`(기록은 있으나 저장소에 파일이 없음 — 오류 아님) |
| `documents[].files` | `{"md": {name, size, etag, sfid} 또는 null, "json": {…} 또는 null}` — `no_files`면 통째로 null |
| `ms` | 걸린 시간(밀리초) |
<!-- /guide:list-output -->

**⚠ 운영과 다름:** ① 운영 목록에 있는 대표 엔진 칸 `rep_engine`은 없다(사용자 11-01 — 대표 엔진 칸을 지운 결정과 맞춤). ② `source_system`은 저장값(`SFDC`)으로 나간다 — 운영은 EDW 값(`SFDC-test`). ③ 목록은 EDW가 아니라 검색 DB(gold `doc`)에서 고른다 — 적재 전 문서는 나오지 않는다.

### 5-3. `get_doc_fulltext` 입력

<!-- guide:get-inputs -->
| 이름 | 형식 | 필수 | 한도·규칙 |
|---|---|---|---|
| `files` | 글자 목록 | 예 | `list_doc_fulltext`가 준 `sfid` 1~20개(0개·넘으면 `bad_request`). 고치거나 만들 수 없다 |
| `json_section` | 글자 | 아니요 | `.json` 내용에서 남길 맨 위 키(쉼표 목록, 예 `"text,tables"`). 안 주면 전체(수십 MB일 수 있음) |
| `created_since` | 글자 | 아니요 | 등록 시각 가드 — 문서 등록 시각이 범위 밖이면 그 파일은 `created_out_of_range` |
| `created_until` | 글자 | 아니요 | 위와 같음 |
<!-- /guide:get-inputs -->

### 5-4. `get_doc_fulltext` 돌려주는 모양

<!-- guide:get-output -->
| 칸 | 뜻 |
|---|---|
| `batch.requested` · `batch.ok` · `batch.skipped` | 요청·성공·건너뜀 수 |
| `batch.total_bytes` | 받은 파일 원본 크기 합 |
| `batch.truncated` | 합계 24MB에 닿아 `batch_full`로 건너뛴 파일이 있으면 `true` |
| `batch.json_section` | 받은 `json_section` 그대로(없으면 null) |
| `files[]`(성공) | `{sfid, name, kind ("md"·"json"), size, sha256, status: "ok", content}` — md는 원래 글자 그대로, json은 파싱한 객체 |
| `files[]`(건너뜀) | `{sfid, skip_reason, name, kind}` — `bad_sfid`는 `{sfid(앞 32자), skip_reason}`만 |
| `ms` | 걸린 시간(밀리초) |
<!-- /guide:get-output -->

건너뜀 사유(`skip_reason`): `bad_sfid`(위조·서명 키가 바뀜 — 목록을 다시 부름) · `missing`(목록 뒤 지워짐) · `too_large`(원본 16MB 초과 — md를 받음) · `batch_full`(한 번 합계 24MB 도달 — 나머지는 다음 호출로) · `created_out_of_range`(등록 시각 가드) · `download_failed`(받기 실패·깨진 JSON — 다시 시도).

무결성: md는 `sha256(content를 UTF-8로)`가 `sha256`과 같아야 한다. json은 파싱한 객체라 다시 해시할 수 없다.

### 5-5. 예

```json
{"name": "list_doc_fulltext", "arguments": {"source_system": "SFDC", "sf_op_id": "006<…>"}}
{"name": "list_doc_fulltext", "arguments": {"docs": ["<파일>.pdf", "<64자 doc_key>"]}}
{"name": "list_doc_fulltext", "arguments": {"doc_class": "RFP", "since": "2025-04-01", "until": "2025-04-30", "limit": 200}}
{"name": "list_doc_fulltext", "arguments": {"created_since": "2025-01-01 00:00:00", "limit": 200, "cursor": "<앞 응답 next_cursor>"}}
{"name": "get_doc_fulltext", "arguments": {"files": ["sf1.<…>", "sf1.<…>"]}}
{"name": "get_doc_fulltext", "arguments": {"files": ["sf1.<…>"], "json_section": "text,tables"}}
{"name": "get_doc_fulltext", "arguments": {"files": ["sf1.<…>"], "created_since": "2025-01-01"}}
```

## 6. `query_edw`

EDW 읽기 전용 SQL. 요약 없이 원래 행만 돌려준다(집계는 SQL에서).

| 이름 | 형식 | 필수 | 기본 | 규칙 |
|---|---|---|---|---|
| `sql` | 글자 | 예 | — | `SELECT` 또는 `WITH`로 시작하는 한 문장. 시스템 표, DML·DDL·EXEC 단어(글자 안이라도), `@` 변수, 큰따옴표 이름(대괄호만), 여러 문장은 거부 |
| `max_rows` | 정수 | 아니요 | 2000 | 서버 상한(`EDW_QUERY_MAX_ROWS`, 기본 2000)을 넘을 수 없음 |

- 한도: 질의 20초(`EDW_QUERY_TIMEOUT_SEC` — 넘으면 `timeout`) · 응답 2MB(`EDW_QUERY_MAX_BYTES` — 넘으면 끝 행을 버리고 `truncated: true`) · 칸 글자 2,000자(넘으면 ` …(truncated)` 표시, `truncated` 깃발은 안 바뀜).
- 돌려주는 모양(성공·실패 같은 9칸): `ok` · `columns`(`[{name, type}]`, type은 `int`·`float`·`decimal`·`str`·`date`·`datetime`·`time`·`bool`·`binary`·`unknown`) · `rows`(칸 순서대로 값 목록) · `row_count` · `truncated` · `elapsed_ms` · `dialect`(`tsql`) · `source`(`mssql`) · `error`(성공이면 null, 실패면 `"<코드>: <설명>"`).
- 소수 있는 `decimal`은 정확한 글자(`"12.50"`) — 실수로 바꿔 반올림하지 않는다. 날짜는 ISO 글자.
- 대표 오류 코드: `not_configured`(접속 설정 없음) · `rejected:<이유>`(읽기 전용 가드 — 예 `rejected:first_keyword`·`rejected:multi_statement`·`rejected:double_quote`·`rejected:top_percent`·`rejected:table:<표>`) · `query_failed`(실행 오류 — 문법·없는 표·칸) · `connect_failed` · `timeout`.
- 허용 표 목록 검사(`EDW_QUERY_TABLES_STRICT`)는 기본 꺼짐이다(모든 스키마 허용).

```json
{"name": "query_edw", "arguments": {"sql": "SELECT TOP 5 id, original_filename, file_size FROM AI.FileStorageMap ORDER BY file_size DESC", "max_rows": 5}}
```

## 7. `parse_document`

파일 1건을 그 자리에서 text 파싱한다(구조화·임베딩·적재 없음, 그림 VLM 없음, 표 인식 포함).

| 이름 | 형식 | 필수 | 기본 | 규칙 |
|---|---|---|---|---|
| `path` | 글자 | 둘 중 하나 | — | 서버 컨테이너 안 경로 — 허용 폴더(`/app/output/mcp_parse/inbox`) 아래만 |
| `content_b64` + `filename` | 글자 | 둘 중 하나 | — | 파일 내용(base64)과 파일 이름(확장자로 형식을 정함 — 3절 목록만) |
| `time_out_threshold` | 정수 | 아니요 | 300 | 초. 이 안에 끝나면 결과, 못 끝내면 `{"error": "시간 안에 수행 못했습니다", "job_id": …}` — 같은 파일을 바로 다시 내면 새 작업이 생긴다 |
| `max_chars` | 정수 | 아니요 | 200000 | 응답 `text` 상한 — 넘으면 잘리고 `text_truncated` |

돌려주는 모양(완료): `text`(대표 본문, 표 포함) · `tables_std` · `tables` · `facts` · `fields` · `engine`(대표 엔진) · `rep_path`(전체 대표 결과 JSON 경로) · `ms`. 대기열이 차면 HTTP 429.

```json
{"name": "parse_document", "arguments": {"content_b64": "<base64>", "filename": "<파일>.docx", "time_out_threshold": 300}}
```

## 8. `edw_meta`

EDW 표·칸의 한글 설명을 정적 자료에서 3단으로 찾는다(DB 접속·벡터·LLM 없음, 표본 값은 내보내지 않음).

| 이름 | 형식 | 필수 | 뜻 |
|---|---|---|---|
| `schema` | 글자 | 아니요 | 없으면 스키마 요약 · 있으면 그 스키마의 표 전체(칸 목록 제외) |
| `table` | 글자 | 아니요 | `schema`와 함께 주면 그 표의 칸 전체(한글 설명·형식·키) — 표 이름이 유일하면 `schema` 없이도 됨 |
| `column_filter` | 글자 | 아니요 | 칸 이름 부분 일치로 넓은 표를 줄임 |

모르는 이름은 `{"error": …, "suggestions": [...]}`. SQL을 쓸 때는 결과의 `qualified_name`을 쓴다.

```json
{"name": "edw_meta", "arguments": {}}
{"name": "edw_meta", "arguments": {"schema": "AI", "table": "FileStorageMap"}}
```

## 9. 쓰는 순서와 주의

- **근거 → 원문:** `search(질문, 거르기)` → `evidence[].file_name`(중복 제거) → `list_doc_fulltext(docs=[…])` → `files`가 null인 문서 빼기 → `get_doc_fulltext(files=[sfid…])`를 20개·24MB씩 나눠서.
- **같은 이름 문서:** `doc_key`나 가장 늦은 `parse_date`로 하나를 고른 뒤 `docs=[doc_key]`.
- **전체 훑기:** `list_doc_fulltext`를 `limit: 200`으로 부르고 `cursor = batch.next_cursor`가 null이 될 때까지 반복.
- **SQL 전에:** `edw_meta`로 표·칸을 확인한다.
- `sfid`는 받자마자 쓰고 오래 저장하지 않는다. 서버 서명 키가 바뀌면 모두 `bad_sfid`가 된다 — 그때는 목록을 다시 부른다.
- `source_system`은 두 표기를 다 받지만, search와 원문 도구 사이를 이을 때는 값을 바꾸지 말고 `file_name`이나 `doc_key`로 잇는다.
- 도구 오류는 HTTP 200 + JSON `error` 칸으로 온다(원문 도구의 `bad_request`는 `detail`도). 원문 도구의 다른 오류: `not_configured`(서버 서명 키 없음) · `source_storage_unavailable`(저장소 접속 없음·실패) · `registry_unavailable`(검색 DB를 못 읽음 — 등록 시각 가드를 줬을 때 확인을 못 하면 조용히 통과시키지 않음).
