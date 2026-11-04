# 적재 — 저장 구조·DB 스키마

[PRD.md](../PRD.md) 카테고리. [load.md](load.md)의 하위 문서. 저장 구조(pl-32), DB 스키마 명세(pl-25 — 정본 [db_schema.md](../architecture/db_schema.md)), 원천 시스템별 gold 스키마(pl-28), 원천 메타 한 칸 `attrs`(pl-52).

순서: pl-32 · pl-25 · pl-28 · pl-52.

<a id="pl-32"></a>
## pl-32 · 저장 구조 — silver는 Object Storage 문서 폴더, 메타는 EDW, gold는 pgvector

### 무엇·왜
결과의 저장 자리를 셋으로 한정한다 — 파싱 결과 저장본(silver)은 Object Storage, 파싱 기록은 EDW `AI.ParsingMeta`, 검색 DB(gold)는 pgvector. 로컬에는 로그와 임베딩 캐시만 남긴다.

### 규칙
1. silver는 Object Storage에만 둔다(PC는 `valid_env/object_storage` — `file://` 대역). 문서마다 폴더 하나 — 이름은 원본 경로(`s3_key`)에서 만든 uuid5(같은 경로 = 같은 uuid), 다시 처리하면 그 폴더를 덮어쓴다.
2. `AI.FileStorageMap`에 같은 `s3_key` 행이 여럿이면 `created_at`이 가장 늦은 행만 처리한다.
3. 같은 `s3_key`의 더 새 행이 오면 같은 `doc_id`를 유지한다 — `file_size`가 같으면 다시 파싱하지 않고 기준·메타만 새 행으로, 다르면 다시 파싱·다시 적재한다(원본을 받아 sha256을 비교하지 않는다 — 같은 크기로 덮어쓴 경우는 놓친다).
4. 밀려난 행은 EDW 예외 이력 표 `SupersededRow`([db_schema.md](../architecture/db_schema.md) §3)에 남긴다.
5. ParsingMeta는 단계마다 성공했을 때만 쓴다. 실패한 엔진(이름·이유·걸린 시간)은 로컬 로그와 ParsingMeta `engines_failed`에 남긴다. 재시도 횟수는 어디에도 두지 않는다 — 실패한 문서는 성공 행이 없어 다음 실행에서 다시 대상이 된다.
6. 실행을 넘어 남는 로컬 완료 표시를 두지 않는다. 문서별 작업 폴더는 문서가 끝나면 지운다(그 안의 `_DONE.json`·`runs.jsonl`은 그 실행의 기록). gold만 다시 만들 때는 Object Storage 문서 폴더에서 silver를 받는다.
7. PC도 서버와 같은 흐름이다 — 대역만 다르다(Object Storage 폴더, EDW SQLite, PC pgvector).

### 단계
1. 게시 키를 uuid5 문서 폴더로 바꾼다 — 지금은 [load.md#pl-09](load.md#pl-09) 규칙 2(실행마다 새 날짜 폴더).
2. 같은 `s3_key` 여러 행 처리(규칙 2·3)와 `SupersededRow` 쓰기 — 표는 DB 담당자가 만든 뒤(refactor.md C-76).
3. `engines_failed` 쓰기 — 칸이 생긴 뒤.
- Status: todo

<a id="pl-25"></a>
## pl-25 · DB 스키마 명세

### 무엇·왜
이 프로젝트가 쓰는 DB 표·칸(검색 DB gold·EDW·마스터·applog)을 문서 하나 [db_schema.md](../architecture/db_schema.md)에 두고 시험으로 실제 정의와 맞춘다.

### 규칙
1. 문서 키는 원본 경로 하나 — gold `doc.file_path` = Object Storage 원본 경로 = EDW `FileStorageMap.s3_key` = ParsingMeta `source_key`(새 이름 `s3_key`). 청크는 `doc_id`만 갖는다. sha256 `doc_key`는 gold에 두지 않는다(ParsingMeta `sha256`만).
2. ParsingMeta에는 파싱 정보만 쓴다 — 원천 키·파싱 상태·silver 위치·엔진·`parsed_at`·`silver_version`·`gold_version`·`loaded_at`·`gold_status`·`gold_reason`, 예외로 원본 지문 `sha256`. 파일 메타(고객·분류 라벨·`sf_op_id`·`created_at`)는 gold `doc`에만 쓴다.
3. 파싱이 통째로 실패한 문서는 ParsingMeta에 행을 쓰지 않는다.
4. 판 칸: `silver_version` = 그 silver를 만든 `VERSION`(게시 때), `gold_version` = gold에 올린 판(적재 때 `loaded_at`과 함께 UPDATE — 꼴은 [load.md#pl-38](load.md#pl-38)).
5. 끝난 원본 키(새 문서 고르기에서 뺄 것) = `parse_status`가 `skipped_dup`인 행 + `ok`·`partial`이면서 `gold_version`이 있는 행. `gold_version` 칸이 아직 없으면 `ok`·`partial`·`skipped_dup` 모두(`parsing_meta_db.done_source_keys`). 이것이 유일한 대상 선택 규칙이다.
6. 이름 바꾸기 전후 모두 돈다 — 표에 새 이름만 있으면 새 이름을 쓴다(`parsing_meta_db.RENAMES`: `source_key` → `s3_key`, `pipeline_version` → `silver_version`).
7. EDW와 문서 본문 양쪽에서 올 수 있는 값은 칸을 둘로 나누고 이름 끝에 출처를 붙인다 — `_edw`·`_doc`(지금은 고객 `client_edw`·`clients_doc`뿐).

### 단계
1. DB 담당자 DDL(refactor.md C-76): ParsingMeta 이름 바꾸기·칸 더하기·지우기([db_schema.md](../architecture/db_schema.md) §3 결정 칸 `새로`·`삭제`, §5), 운영이 더한 분류·고객 칸 지우기, `SupersededRow` 만들기.

### QA
- `tests/server/common/test_db_schema.py`(gold ↔ Alembic 모델 · ParsingMeta ↔ `docs/operations/parsing_meta_mssql.sql` · master ↔ 모델) · `tests/server/common/test_pm_versions.py`.
- Status: dev

<a id="pl-28"></a>
## pl-28 · 원천 시스템별 gold 스키마

### 무엇·왜
SFDC·CRMS·LAS·FAQ·Other는 메타가 다르고 BM25 통계도 원천마다 따로 두어야 점수가 섞이지 않는다.

### 규칙
1. 기준 스키마 `<PG_SCHEMA>`에는 Alembic 판 표와 공용 `doc_id_seq`만, 원천 스키마 5벌 `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`에 같은 표 `doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + 뷰 `v_chunk_source`.
2. 5벌이 시퀀스 하나를 함께 써서 `doc_id`가 겹치지 않는다. 근거 키 `chunk_key` = `<doc_id>:<seq>`.
3. 원천 = 원본 경로(`s3_key`) 첫 마디 — `SFDC`·`CRMS`·`LAS`·`FAQ`(대소문자 무관)이거나 `SFDC-`·`SFDC_`·`CRMS-`·`CRMS_`·`las_`·`LAS_`로 시작하면 그 원천, 아니면 `other`(`build_bundle`). `AI.FileStorageMap.source_system` 칸은 읽지 않는다.
4. 파일 메타는 `doc`에만 둔다. `chunk`는 `doc_id`만 갖고 메타를 복사하지 않는다 — 예외 `faq.chunk.faq_group`. 거르기는 `doc`에서 문서 범위를 고른 뒤 그 안의 `chunk`만 찾는다.
5. MCP `search`는 `source_system`을 필수·값 하나로 받아 그 스키마만 찾는다(`Other`·`-test` 별칭 포함 — [mcp.md#mc-16](mcp.md#mc-16)). 여러 원천은 클라이언트가 여러 번 부른다.
6. 검색 MCP는 원천마다 다시 읽기 신호 (MAX(doc_id), COUNT(*))로 새 적재를 알아챈다. 우리 스키마 표식은 판 표다.

### QA
- `tests/server/common/test_dbtool.py` · `tests/server/common/test_db_schema.py` · `tests/server/mcp/test_search_svc.py` · `tests/server/pipeline/test_pl13_no_prune.py`.
- Status: done

<a id="pl-52"></a>
## pl-52 · 원천 메타 한 칸 `doc.attrs`(JSONB) — 사슬 파일이 키·거르기·근거를 정함

### 무엇·왜
원천 칸을 더하거나 이름을 바꿀 때마다 Alembic 판·적재·검색 코드를 함께 고치지 않게 한다. 사슬 파일 하나가 EDW 칸 → attrs 키 → 거르기 이름 → 근거 표시를 정하고, 운영 쪽은 파일만 고친다.

### 규칙
1. `doc` 고정 칸(5벌 모두): `doc_id`·`file_path`·`summary`·`created_at`·`client_edw`·`clients_doc`·`content_date`·`embed_model`. 그 밖의 원천 메타(영업 기회·계약·분류 힌트 등)는 모두 `doc.attrs JSONB`(GIN 색인)의 키다. 값이 없는 키는 넣지 않는다. `faq.chunk.faq_group`은 청크 칸 그대로.
2. 판 `0005_doc_attrs`: 5벌에 `attrs` + GIN 색인, `v_chunk_source`가 `attrs`를 낸다. 올리기는 판 0002·0003의 원천 칸 값을 같은 이름 키로 옮기고(날짜는 `YYYY-MM-DD` 글자) 그 칸을 뺀다. 되돌리기는 최선만(날짜가 아닌 글자는 NULL).
3. 사슬 파일 꼴(`steps` → `fields` · `client_edw` · `created`, 단계 칸 `table`·`on`·`when`·`where`·`latest`·`optional`·`tz`·`sfdc_entity`, 칸 `from`·`filter`·`evidence`·`type`·`max`)은 [`resources/config/edw_chain.yaml`](../../resources/config/edw_chain.yaml) 머리 주석이 정본이다. 첫 단계는 `file`이어야 하고 그 단계에 행이 없는 문서는 메타가 없다. 한 단계의 칸을 못 읽으면 그 칸만 빈다.
4. 파일을 읽을 때 검사한다 — 빠진 이름, SQL에 넣을 수 없는 이름(표 `스키마.표`, 칸은 영문·숫자·_, 접두 3자), 단계·칸 참조, 원천 안에서 겹치는 거르기 이름이면 이유를 모두 말하고 멈춘다. 값은 늘 바인딩한다.
5. `doc_class`는 분류가 쓰는 attrs 키다(`search_tables.LOAD_ATTRS` — 사슬 키로 못 씀).
6. MCP `search`: `attrs: {키: 값}` 거르기는 그 원천에서 `filter`가 있는 키만 받는다 — 모르는 키는 그 원천의 키 목록과 함께 오류(빈 결과 아님). 이름 있는 거르기는 사슬의 `filter:`로 attrs 키에 잇는다(`project_id` → `project_code__c` 등). 근거 `attrs`는 `evidence: true` 키 모두(값 없으면 null), `contract_no` = `filter: contract_id` 키의 값. `edw_meta` 도구가 원천마다 거를 수 있는 키·근거 키를 보여 준다.
7. `list_doc_fulltext`의 `doc_class`·`sf_op_id`는 attrs 키 이름 그대로 읽는다(사슬을 거치지 않음). 이 키와 분류 힌트 키는 서버 사본에서 이름을 바꾸면 안 된다.
8. 검색은 사슬 파일이 바뀌면 다음 호출부터 다시 읽는다.
9. 사슬 `fields`에 `filter:`가 있는 칸을 더하면 코드 수정 없이 그 원천의 이름 거르기·`attrs` 거르기·`edw_meta` `search_attrs`가 함께 열린다(사용자 11-04 — CRMS `sf_op_id`는 지금 사슬에 없어 그 거르기는 0건, 칸이 생기면 이 길로 더한다). 시험: `tests/server/mcp/test_search_svc.py`(`_selftest_search_attrs`).

### QA
  - 시험: `tests/server/common/test_dbtool.py`(0005 — 옮기는 칸 = 0002+0003, 뷰·되돌리기·GIN) · `tests/server/pipeline/test_edw_meta.py`(사슬 사례·틀린 설정 15개) · `tests/server/pipeline/test_classify.py`(EDW attrs → `doc.attrs` · 힌트) · `tests/server/mcp/test_search_svc.py`(attrs 거르기·오류·근거 attrs·`contract_no`·`search_attrs`) · `tests/server/mcp/test_call_log.py`(tools/list 바이트 — 지금 값은 시험 파일).
  - 서버 확인: [refactor.md C-89](../refactoring/refactor.md).
- 파일: `common/store/db/models/search_tables.py` · `common/store/db/migrations/versions/0005_doc_attrs.py` · `common/store/edw_chain.py`(사슬 읽기·검사 — 두 앱) · `pipeline/load/edw_doc_meta.py`(해석기) · `mcp_server/services/search/search_svc.py` · `mcp_server/services/edw_calls.py`.
- Status: done
