# 적재 — pgvector·게시·마스터

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md) 다음: EDW 메타(pl-29) → pgvector 적재(pl-07·pl-13·pl-16·pl-51·pl-19) → 게시(silver — pl-09·pl-26) → FAQ 다시 올리기(pl-41) → 정형 DB·문서 대장 없음(pl-08·pl-12) → 마스터 표(pl-38). 저장 구조·DB 스키마는 [load-schema.md](load-schema.md).

순서: pl-29 · pl-07 · pl-13 · pl-16 · pl-51 · pl-19 · pl-09 · pl-26 · pl-41 · pl-08 · pl-12 · pl-38 · pl-56 · pl-61.

<a id="pl-29"></a>
## pl-29 · EDW 고객·원천 메타를 적재 때 붙인다

### 무엇·왜
문서마다 EDW 고객 하나(`client_edw` — MCP 고객 거르기의 유일한 키)와 원천 메타(`doc.attrs` 키)가 필요하다. 파싱·구조화는 이 값을 쓰지 않는다 — 매핑이 바뀌어도 다시 파싱하지 않는다.

### 규칙
1. 적재(`pipeline/load/edw_doc_meta.py`)가 PG 트랜잭션 밖에서 EDW 읽기 계정(`common.connections.rdb.read`)으로 원천별 사슬을 따라 `client_edw`·`attrs`·`created_at`을 채운다. 결과는 gold `doc`에만 쓴다.
2. 사슬(표·칸 이름·단계·`attrs` 키)은 사슬 파일 [`resources/config/edw_chain.yaml`](../../resources/config/edw_chain.yaml)이 정한다 — 꼴은 [load-schema.md#pl-52](load-schema.md#pl-52), 키 뜻은 [db_schema.md](../architecture/db_schema.md) gold.doc.attrs 키.
3. SFDC 고객 순서: 영업 기회 직접(`006`) > `Task.WhatId`(`00T`) > `Event.WhatId`(`00U`) > (Quote — 사슬 파일에서 켤 때만), 기회가 없으면 계정 직접 연결. 같은 단계에 후보가 둘 이상이면 비운다.
4. CRMS는 `FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST`, LAS는 `FileStorageMap_LAS.manage_no → LAS.Contract`(최신 판). LAS `client_edw`(`PartnerCorpName`)는 지금 모두 비어 있다. FAQ는 고객 연결이 없다.
5. 같은 sha256 묶음에도 고객은 전파하지 않는다.
6. 만약 EDW를 못 읽으면 → 메타 없이 적재하고 경고·실행 기록 `meta_missing`을 남긴다. 적재 뒤 바뀐 연결은 자동으로 갱신하지 않는다 — `--replace`로 다시 적재해 채운다.
7. 사슬 파일 자리 = 설정 `ops.paths.edw_chain_file`(적재·검색 MCP가 함께 읽음). 비우면 `resources/config/edw_chain.yaml`. 만약 파일이 없거나 틀리면 → 적재는 시작 때 멈추고 검색은 오류(기본 파일로 돌아가지 않음). 서버 사본을 고쳐 쓰는 법은 [release-and-patch §8](../operations/release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버).
8. 파일만 점검: `python -m pipeline.load.edw_doc_meta --check [--file F]`(EDW·PG에 붙지 않음).

### QA
- `tests/server/pipeline/test_edw_meta.py`(사슬 사례·틀린 설정·힌트 칸 — PC 대역 `valid_env/edw`).
- Status: done

<a id="pl-07"></a>
## pl-07 · pgvector 적재

### 무엇·왜
검색 MCP는 PG만 읽는다. 문서 묶음을 원천 스키마별 검색 표에 넣는다.

### 규칙
1. 표·뷰는 Alembic으로만 만든다(실행 중 DDL 금지) — 원천 스키마 5벌마다 `doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + 뷰 `v_chunk_source`([pl-28](load-schema.md#pl-28)).
2. 묶음 하나를 실 PG에서는 한 트랜잭션으로 적재한다(`python -m pipeline.load.pgvector_load load`) — 하나라도 실패하면 5벌 모두 되돌린다. 원천(`source_system`)이 스키마를 고른다.
3. 이미 있는 문서(`doc.file_path` 같음)는 건너뛴다. 내용이 바뀌어도 경로가 같으면 `--replace` 없이는 건너뛴다(내용 지문 칸 없음).
4. 적재 전 판 확인: 판 기록이 없는 기존 스키마면 경고 후 계속, 판이 낮거나 모르는 판이면 종료 2. 새 스키마면 판을 올린다. `--replace`·`faq-sync --reset`은 판 표(`alembic_version`)가 있는 우리 스키마에서만.
5. `vector` 확장이 없으면 멈춘다 — 관리자가 한 번 `CREATE EXTENSION vector`. 직접 만들기(`dbtool up --create-extension`)는 PC·단독 시험만.
6. 본문 글자의 NUL(0x00)은 지운다. 원천 등록 시각에 시간대가 없으면 KST(+09:00)로 읽고, 형식이 틀리면 비운다.
7. PG 접속은 필수다([ops-settings.md#op-09](ops-settings.md#op-09)).

### QA
- `tests/server/pipeline/test_pgvector_load.py` · `tests/server/common/test_dbtool.py`.
- Status: done

<a id="pl-13"></a>
## pl-13 · 적재는 지우지 않는다

### 무엇·왜
건너뛴 문서까지 지워지면 안 된다. 적재는 더하고 고치기만 한다.

### 규칙
1. 묶음에 없는 저장 문서는 그대로 둔다. 원천에서 지워진 문서·파싱 실패 문서는 로그에만 남긴다(자동 삭제 없음).
2. 원본 경로(`file_path`)는 원천 스키마 5벌을 통틀어 하나다 — 적재는 5벌 모두에서 찾는다. `--replace` 없이 어느 스키마에든 있으면 건너뛰고, `--replace`면 다른 원천 스키마의 옛 사본(키워드 색인·문서 빈도·`corpus_stat` 포함)을 같은 트랜잭션에서 지운 뒤 새 원천 스키마에 넣는다.
3. 경로가 바뀐 같은 내용의 옛 행은 남는다 — 사람이 지운다. 예외는 FAQ([pl-41](#pl-41)).

### QA
- `tests/server/pipeline/test_pl13_no_prune.py`.
- Status: done

<a id="pl-16"></a>
## pl-16 · 임베딩 없는 묶음은 적재 거부

### 규칙
1. 묶음 `meta.json`의 `embed`가 `none`이거나, 청크가 있는데 `dim`이 0·없음이면 → 판 확인·배포·적재 전에 한 줄 안내(`gold_bundle`을 `--embed api`로 다시)와 함께 종료 2(`require_vectors`).

### QA
- `tests/server/pipeline/test_pgvector_load.py::test_require_vectors`.
- Status: done

<a id="pl-51"></a>
## pl-51 · 임베딩 모델이 다른 묶음은 적재 거부

### 무엇·왜
검색은 원천 스키마마다 `doc.embed_model`이 하나여야 질의를 임베딩한다(섞이면 벡터 검색 거부 — [mcp.md#mc-19](mcp.md#mc-19)). 검색 MCP 하나가 한 질의 모델로 5벌을 모두 보므로 기준은 설정이 아니라 **이미 적재된 문서의 모델**(5벌 전체)이다.

### 규칙
1. `load()`에서 `require_vectors` 바로 뒤(EDW 조인·분류·쓰기 전): 5벌의 `doc.embed_model`(빈 칸 제외, 표가 없는 스키마는 건너뜀)을 모아 묶음 `meta.json` `embed_model`과 `embed.model_key`로 비교한다(`openai/` 앞붙이는 같게 봄). 모은 것이 비었거나 묶음 모델 하나와 같으면 통과.
2. 다르면 → 아무것도 쓰지 않고 종료 2. stderr에 `[load] 임베딩 모델이 다름 — 적재 거부(…)` 한 줄, `ops.log.log_db_enabled`가 켜져 있으면 `applog.pipe_event` 한 행: `layer` `load` · `stage` `load.embed_guard` · `model` 묶음 모델 · `status` `fail` · `err_kind` `env` · `err` `embed_model_mismatch: expected <기존>, got <묶음> (bundle <경로>)`.
3. 모델을 바꾸려면 새 검색 스키마에 적재한다(`--replace`도 거부).

### QA
- `tests/server/pipeline/test_pgvector_load.py::test_embed_guard`(SQLite 대역 — 같은 모델·표기만 다른 같은 모델은 적재, 다른 모델은 거부 + `pipe_event` 한 행).
- Status: done

<a id="pl-19"></a>
## pl-19 · 이름 있는 색인 예시 없음

### 무엇·왜
검색 색인은 원천 스키마의 표 하나뿐이다. compose에 색인 비교용 서비스(`index_a`·`index_b`)를 두지 않는다.
- Status: done

<a id="pl-09"></a>
## pl-09 · 파싱 결과 게시(silver)

### 무엇·왜
다른 팀은 파싱 결과를 Object Storage에서 읽는다(위치는 원문 도구 — gold `doc` 칸).

### 규칙
1. 올리는 것: 대표 결과 `.md`(`render_md` — 본문 + 표) + 같은 폴더에 대표 결과 JSON(`<이름>_<날짜>.json`)·엔진별 원결과(`engine/<엔진>_<판>_<이름>.json`)·그림 기록(`engine/vlm_<모델>_<이름>.jsonl`). 원본 파일은 올리지 않는다. `.md`를 마지막에 써서 완료 표시로 삼는다.
2. 대표 결과 키 = `<required.publish.publish_prefix>/<source_system>/<원본 키 폴더들>/<원본 파일 이름(확장자 뺌)>_<parse_date>.md`. 원본 키 첫 마디가 이미 `<source_system>`이면(대소문자 무시 — PC 폴더 원천 `CRMS/<uuid>/<파일>`) 원천 이름을 한 번만 쓴다(`CRMS/CRMS/…` 아님). 조각마다 파일 이름에 쓸 수 없는 글자를 정리하고, 정리로 원본 키와 달라지면 마지막 조각에 `__h<원본 키 sha1 앞 10자>`를 붙인다. `parse_date` = `YYYY-MM-DD_HHMMSS`. 같은 키가 이미 있으면 `<parse_date>-2`, `-3` …으로 새 폴더 — 덮어쓰지 않는다. 처리 기록 `silver_key`는 그 `.md` 객체 키(폴더 = 끝 `/` 앞까지).
3. 게시는 EDW에 쓰지 않는다 — 올린 문서마다 처리 기록 한 줄(`doc_name`·`source_key`·`sha256`·`silver_bucket`·`silver_key`·`engines`·`parse_status`·`silver_version`·`parsed_at`)을 `<문서 폴더>/publish/silver.jsonl`에 남기고, 적재(`--silver`)가 gold `doc` 칸으로 쓴다([load-schema.md#pl-25](load-schema.md#pl-25)). gold에 이미 있는 원본 키는 올리지 않는다([pl-61](#pl-61)).
4. 상태 `parse_status` = `ok` · `partial`(교차 정확도 < 0.95 — [transform.md#pl-04](transform.md#pl-04)) · `failed` · `skipped_drm` · `skipped_dup` · `not_parsed`. 올리는 상태는 `tuning.load.publish.publish_upload_statuses`(기본 `ok`·`partial`).
5. `skipped_drm`·`failed`는 올리지 않고 `output/publish/excluded_<날짜>.md` 보고서에만(`failed`는 `applog.except_doc_info` `error` `parse_failed`도).
6. 게시 버킷이 원천 원본 버킷과 같은지는 검사하지 않는다(rn-07 — `run_pipeline`가 늘 끄던 검사를 지움). `required.publish.publish_bucket`을 원천 버킷과 다르게 두는 것은 운영자 몫.

### QA
- `tests/server/pipeline/test_publish_parse.py` · `tests/server/common/test_no_deleted.py`.
- Status: done

<a id="pl-26"></a>
## pl-26 · 늘 게시하고 게시 대상은 필수

### 규칙
1. 게시(silver → Object Storage + 처리 기록 파일)는 기본이자 유일한 방식이다 — 끄는 선택지가 없다. `run_pipeline`는 문서마다 늘 게시한다([ops.md#pl-24](ops.md#pl-24) — gold 전).
2. 게시·EDW 칸은 settings.yaml `required` 한곳에 있다 — 게시 위치 `required.publish.publish_bucket`·`publish_prefix`, Object Storage 접속 `required.object_storage`(`object_storage_endpoint`·`object_storage_region`·`object_storage_access_key`·`object_storage_secret_key`·`object_storage_verify_tls`), EDW `required.edw`(`edw_host`·`edw_port`·`edw_database`·`read_*`). 칸마다 주석에 서버·PC에 넣을 값을 적는다. PC 전용 값은 `dev.local`(op-14).
3. 서버(`run_pipeline`)는 게시 버킷·접두, Object Storage 주소·키, EDW 주소·읽기 계정이 비면 칸 이름을 찍고 시작을 거부한다(종료 2 — 쓰기 계정은 쓰지 않음, op-17). `object_storage_region`·`object_storage_verify_tls`·`edw_port`는 비우면 코드 기본값(`us-east-1`·`1`·1433).
4. PC(`local`)는 로컬 대역만 쓴다 — 게시 폴더 `dev.local.local_publish_dir`(기본 `valid_env/object_storage/Parsing_Result`), EDW `dev.local.local_edw_sqlite_file`(비우면 `valid_env/edw/edw_copy.sqlite`). 서버 게시 버킷·Object Storage·EDW 접속 칸은 적혀 있어도 비우고 경고한다(op-14). 가짜 EDW는 `local`에서만 열린다(서버 설정에 있으면 EDW를 쓸 때 거부). PC에서는 운영 EDW·Object Storage에 접속하지 않는다(CLAUDE.md §4).

### QA
- 칸 자리·옛 자리: `tests/server/common/test_layout.py::test_publish_edw_keys_in_required`. 서버 시작 검사는 `run_pipeline.py` `SETTINGS_REQUIRED`(자동 시험 없음).
- Status: done

<a id="pl-41"></a>
## pl-41 · FAQ 다시 올리기 — 통째 교체

### 무엇·왜
FAQ는 판을 잇지 않는다. 새 FAQ가 오면 gold faq를 비우고 FAQ 전체를 다시 넣는다 — [pl-13](#pl-13)("지우지 않음")의 FAQ 한정 예외. 검토 등급 A.

### 규칙
1. 새 FAQ = FileStorageMap에서 `source_system`이 `FAQ`(대소문자 무관)인 행의 키 중 결과 폴더의 `_faq_seen.txt`(교체를 마친 키 목록)에 없는 것. 파일이 없으면(처음) FAQ 전체를 한 번 교체한다.
2. 컨테이너 안 `candidate_pick list --faq-seen <파일>`의 `faq_first`(처리 순서를 정한 뒤 — `--skip-done` 뒤, `--max-docs` 앞): FAQ 목록은 `--filter`와 상관없이 FileStorageMap에서 따로 읽는다(대상에 없는 FAQ는 목록 뒤에 덧붙임). `--start-offset`이 대상 수보다 커도 확인한다.
3. 새 FAQ가 있으면 → 자식 프로세스 `pgvector_load faq-sync --reset`으로 gold faq의 문서·청크·키워드 색인을 한 트랜잭션에서 지우고, FAQ 전체를 이번 처리 맨 앞에 넣는다(이미 끝난 FAQ도). `_faq_seen.txt`는 `faq-sync` 결과(`--out` JSON — 목록 파일 옆 `faq_sync.json` — 지운 수·남은 `file_path`)를 읽은 **뒤에만** 적는다.
4. 새 FAQ가 없으면 → 지우지 않고 gold에 없는 FAQ만 넣는다(영구 뺌 `except_doc_info` `skip`은 뺌) — 중간에 멈춘 교체와 파싱 실패를 다음 실행이 채운다.
5. 만약 `faq-sync` 결과를 못 읽으면(실패·시간 초과 1,800초) → 경고와 함께 FAQ 전체를 넣고 `_faq_seen.txt`는 그대로 둔다.
6. `--seqs`·`--limit` 실행과 원천 목록(`required.source.source_systems`)에 `FAQ`가 없는 실행에서는 FAQ 교체를 하지 않는다(로그 한 줄).
7. 한계: 같은 실행 안에서 지우고 다시 넣는 사이에는 검색에 FAQ가 일부만 보인다. FileStorageMap에서 사라진 FAQ는 다음 교체 때 함께 빠진다.

### QA
- `tests/server/pipeline/test_faq_rows.py::test_faq_sync`(SQLite 대역) · `tests/server/pipeline/test_target_list.py`(FAQ 순서 사례).
- Status: done

<a id="pl-08"></a>
## pl-08 · 정형 DB(`struct` 스키마) 없음

### 무엇·왜
계약·고객·문서 파생 표(정형 DB)를 두지 않는다. `dbtool`·`migrate`의 대상은 `search`·`applog`·`master`·`all`뿐이고, 엔진 구성은 파일이다([transform.md#pl-03](transform.md#pl-03)). 파싱·검색 MCP 컨테이너는 PG 없이 시작한다(PG는 적재·검색에만).
- Status: done

<a id="pl-12"></a>
## pl-12 · 문서 대장·숨김·원천 삭제 처리 없음

### 무엇·왜
빼야 할 문서는 원천에서 지우거나 사람이 SQL로 지운다. 대장·숨김 표와 그 처리 길을 두지 않는다.

### 규칙
1. 게시·적재는 EDW에 쓰지 않는다(`deleted`도 — [ops.md#op-17](ops.md#op-17) 규칙 18).
2. 서버(`dev`·`prd`)는 PG가 없으면 로컬 대체 DB(SQLite 대역)로 바꿔 타지 않고 멈춘다.

### QA
- `tests/server/common/test_no_deleted.py`.
- Status: done

<a id="pl-38"></a>
## pl-38 · 마스터 표 — 용어집·고객 명부를 PostgreSQL로

### 무엇·왜
용어집·고객 명부를 검색 PG의 마스터 표로 두고 구조화·검색이 같은 값을 읽는다. 원본은 git CSV다. ETL 규칙: 변환 = 문서 내용 + 고객 명부로 고객 알아보기(청크 머리의 고객이 임베딩 입력), 적재 = EDW 조인·분류·DB 쓰기, 대표 결과(silver)는 마스터를 읽지 않는다.

### 규칙
1. 대상 CSV 하나 `resources/vocab/glossary/glossary.csv` — 고객 명부·용어 사전·ID 꼴을 합친 표 `glossary`(꼴은 [ops.md#op-17](ops.md#op-17) 규칙 19~21). `client_master.example.csv`·`client_master_map.example.json`·`client_roster_seed.json`은 파일로 남는다.
2. 스키마 `<PG_SCHEMA>_master`, 표·칸은 Alembic 갈래 `master`로만(`dbtool up --target master`, `--target all`에 포함). 칸·해시 규칙은 [db_schema.md](../architecture/db_schema.md) §4.
3. `dbtool master load`가 CSV로 표 내용을 한 트랜잭션에 통째로 바꾼다. 내용 해시는 읽을 때 계산한다. 초기화 순서: `dbtool up`(search·applog·master) → `dbtool master load`.
4. 읽는 곳: `common/core/terms.py`의 용어 사전·ID 모양·고객 명부 로더(프로세스마다 한 번, 마스터 해시가 바뀌면 다시) — 구조화 고객 판별(`infer_clients`)과 검색. PC·시험은 같은 CSV로 채운 SQLite 대역. 서버(`dev`·`prd`)는 마스터를 못 읽으면 시작하지 않는다.
5. `gold_version` = `<VERSION>+m<마스터 해시 앞 8자>` — 구조화가 읽은 해시를 묶음 `meta.json` `master_hash`로 넘기고 적재가 gold `doc.gold_version`에 쓴다(`master_hash`가 없는 묶음은 `<VERSION>`만). `silver_version`에는 붙이지 않는다. 마스터 해시는 캐시 열쇠·code_fp에 넣지 않는다(마스터가 바뀌어도 자동 재처리 없음).

### 예시
- `VERSION` `0.2.0`, 마스터 해시 `58a24b02…` → `gold_version` `0.2.0+m58a24b02`.

### QA
- `tests/server/common/test_master.py` · `tests/server/common/test_db_schema.py`(§4 칸 대조).
- Status: done

<a id="pl-56"></a>
## pl-56 · (잠재 문제) 같은 문서의 다른 판 묶기

### 무엇·왜
같은 문서의 다른 판은 `s3_key`가 달라 따로 적재된다 — 검색 '최신' 질문에서 옛 판이 위로 올 수 있다. 필요해지면 `created_at`으로 다시 설계한다. 지금 근거의 `version`은 수집 매니페스트 값만, `superseded`는 늘 null([mcp.md#mc-05](mcp.md#mc-05)).
- Status: todo

<a id="pl-61"></a>
## pl-61 · 게시는 gold를 먼저 본다

### 무엇·왜
끝난 문서의 결과를 Object Storage에 또 쌓지 않는다.

### 규칙
1. 게시(`publish_parse_result.apply`)는 올리기 전에 gold `doc`에 같은 원본 키가 있는지 본다(`gold_docs.done_keys` 한 번). 있으면 → 올리지 않고 건너뜀으로 센다(결과 `upload_skip_existing`). `--reparse` 목록의 키만 예외(새 날짜 폴더).

### QA
- `tests/server/pipeline/test_publish_parse.py` — gold에 있는 문서 다시 게시 → 업로드 0·`upload_skip_existing` 1·처리 기록 없음 · `--reparse`는 새 날짜 폴더로 올림 · 통과.
- Status: done
