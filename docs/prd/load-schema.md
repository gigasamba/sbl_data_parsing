# 적재 — 저장 구조·DB 스키마

[PRD.md](../PRD.md) 카테고리. [load.md](load.md)의 하위 문서. 저장 구조(pl-32 — 파싱 결과 저장본은 Object Storage, 메타는 EDW, 검색 DB는 pgvector), DB 스키마 명세(pl-25 — 정본 `docs/architecture/db_schema.md`)와 원천 시스템별 gold 스키마(pl-28), 원천 메타 한 칸 `attrs`(pl-52).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-32 · pl-25 · pl-28 · pl-52.

<a id="pl-32"></a>
## pl-32 · 저장 구조 — silver는 Object Storage uuid 폴더, 메타는 EDW, gold는 pgvector
- 결정(사용자 10-31 범위 축소 grill): 같은 s3_key 최신 행만 남김(기존) — 구판 표시는 쓰지 않음(mc-05). 대체된 행은 SupersededRow(pl-25 계획대로).
- 결정(사용자 10-30 grill): 결과 저장 자리를 셋으로 정한다 — [transform.md#pl-20](transform.md#pl-20)(엔진 스택 사본 파일)을 대신함.
- silver(파싱 결과)는 Object Storage에만. PC는 `valid_env/object_storage`(file:// 대역). 문서마다 폴더 하나 — 이름은 파일 경로(`s3_key`)에서 uuid5로 만든 uuid(같은 경로 = 같은 uuid, 다시 처리하면 그 폴더를 덮어씀).
- `AI.FileStorageMap`에 같은 `s3_key` 행이 여럿이면(SFDC 판 등) 갱신·수정 시각이 가장 늦은 행만 처리.
- 결정(허브 10-31, 최신 결정 우선): 밀려난 `FileStorageMap` 행은 로컬 기록이 아니라 EDW 예외 이력 표에 남긴다(D-9, `db_schema.md` §4 `edw.SupersededRow`, PR #70).
- 메타는 EDW `AI.ParsingMeta`에 단계별로, 성공했을 때만 쓴다([pl-25](load-schema.md#pl-25)).
- gold는 pgvector만.
- 로컬에 남기는 것: 로그와 임베딩 캐시뿐. 문서별 작업 폴더는 지금처럼 문서가 끝나면 지운다. 지울 것: `_stack/stack-v*.json` 사본과 `STACK_SNAPSHOT`, `runs.jsonl` 재사용 저장소, `_DONE` 표시, 로컬 대장·작업 상태 파일.
- 새벽 배치 계획(사용자 10-30 "새벽 배치 계획은 parameter로 하면 될 것 같아. null 이면 새벽 배치 안하고, 입력되어있으면 작동"): settings.yaml 키 하나(op-05 — settings.yaml 하나). 값이 null이면 새벽 배치를 하지 않고, 값이 있으면 돈다([pl-23](ops.md#pl-23)).
- 실패 횟수(사용자 10-30): 재시도 횟수를 어디에도 두지 않는다. ParsingMeta는 성공했을 때만 갱신.
- 실패한 엔진(사용자 10-30 "EDW에도"): 실패한 엔진(이름·이유·걸린 시간)을 로컬 로그와 EDW ParsingMeta 실패 엔진 칸에 함께 남긴다([pl-25](load-schema.md#pl-25), D-3).
- 구현 결정(허브 — 사용자 결정 안에서, 10-30):
  - 새벽 배치 파라미터 = 새벽 실행 시각을 담는 settings.yaml 키 하나, null이면 새벽 배치 없음.
  - 실패한 문서는 성공 행이 없어 다음 실행에서 다시 시도된다. 실패 정보는 로컬 로그와 ParsingMeta 실패 엔진 칸으로.
  - 엔진 구성은 서버·PC 같은 파일 하나라 판 번호를 넘기지 않는다 — 진입점이 `stackcfg.resolve()`로 검사하고 층은 `pipeline.config.stack()`으로 같은 파일을 읽음, 호스트 `run_docs.py`는 시작 때 `show-stack`으로 확인만. `--stack <파일>`은 PC 실험·시험 전용 명시 덮기 — 생산 경로(run_docs·entrypoint)는 주지 않는다([pl-08](load.md#pl-08)).
  - 레이어 핸드오프 `_DONE.json`은 남는다 — 문서마다 지우는 작업 폴더 안에 있고 FINGERPRINT도 그대로. 없애는 것은 실행을 넘어 남던 완료 표시(`run_all`, `figures_resume`, 색인 건너뛰기).
  - `runs.jsonl`: 재사용 역할만 없애고 작업 폴더 안 실행별 기록으로 남긴다.
  - 구현(10-30 `feature/no-cross-run-done`, 허브): `run_all`은 앞 실행의 `runs.jsonl`로 건너뛰거나 결과를 복사하지 않는다(이미 성공·같은 내용 복사·이전 실패·`encrypted_detected` 건너뜀과 `--force`·`--retry-failed`·`--refresh-unknown` 지움 — 같은 실행 안 같은 내용 사본은 한 번만 파싱) · `figures/figures_resume.py`와 시험 지움(pl-35 그 항목도 끝) · 내용으로 열쇠를 거는 임베딩 캐시는 남김.
  - `StandinPG`는 시험과 이미지 관문에만 — dev/prd 실행 중 조용히 대신하는 일은 없다.
- 0.2.0 구현 PR 순서(사용자 10-30, PR 1은 3a에 합침): 2a ∥ 2b → 2c → (DB 담당자 D-1~D-7) → 3a + 3b 연달아 병합 ∥ 4 → 2d → 5(SFDC 먼저, CRMS·LAS는 D-2 전까지 Other) → 6.
  - FAQ 원천 [pl-39](extract.md#pl-39)는 PR 3a 뒤(gold 칸이 필요).
  - reference 비교 행(10-30): 분류 단계 [pl-33](transform.md#pl-33)와 MCP [mc-16](mcp.md#mc-16)·[mc-17](mcp.md#mc-17)은 PR 5 뒤 — 정확한 자리는 허브가 정함. 파싱 p1 묶음 [pl-34](transform-cleanup.md#pl-34)·잔재 정리 [pl-35](transform-cleanup.md#pl-35)는 순서 미정(허브).
- 구조화 입력: 같은 실행 안에서는 로컬 작업 폴더를 읽고, 나중에 gold만 다시 만들 때는 Object Storage uuid 폴더에서 silver를 받는다.
- PC도 서버와 같은 흐름 — 대역만 다름(OS 폴더, EDW SQLite, PC pgvector), 따로 생기는 로컬 파일 없음.
- 파일: `pipeline/load/{publish_parse_result,parsing_meta}.py`, `pipeline/extract/run_all.py`(`runs.jsonl`·`_DONE`), `pipeline/stackcfg.py`·`pipeline/config.py`(`STACK_SNAPSHOT`), `pipeline/cli.py`(`_unparsed`), `deploy/host/scripts/run_docs.py`, `docs/architecture/db_schema.md`.
- 결정(사용자 10-31, A4): 같은 `s3_key`의 여러 행 중 기준은 `FileStorageMap.created_at`이 가장 늦은 행(PC 대역 EDW에도 `created_at` 칸 — 실제 EDW는 D-1 확인). 밀려난 행은 EDW 예외 이력 표에 남긴다(D-9, `db_schema.md` §4). 원본을 내려받아 sha256을 비교하지 않는다. 같은 `s3_key`의 더 새 행은 `FileStorageMap.file_size`만 본다 — 크기가 같으면 같은 `doc_id`로 건너뛰고(기준·메타만 새 행으로), 크기가 조금이라도 다르면 같은 `doc_id`로 다시 파싱·다시 적재한다(EDW에 이미 있는 칸이라 내려받기 없음). 같은 키에 같은 크기로 덮어쓰는 드문 경우는 놓친다(받아들임).
- 결정(허브 10-31, 최신 결정 우선): 새 문서 = C10 — 모든 입구(run_docs·`parse --max-new`·`--source`)에서 EDW `FileStorageMap`에 있고 `ParsingMeta`에 없는 것([pl-23](ops.md#pl-23)). 이미 ParsingMeta에 있는 `s3_key`를 다시 처리하는 길은 위 A4(`file_size`가 다른 더 새 행 — 10-31 최종)와 사람이 시작하는 전체 e2e뿐.
- Status: todo — 0.2.0.

<a id="pl-25"></a>
## pl-25 · DB 스키마 명세 — pl-26·pl-23·pl-24를 만들기 전에 먼저
- 결정(사용자 10-31 범위 축소 grill): EDW 추가 기록은 **계획대로**(SupersededRow 표 + ParsingMeta 단계별 열). silver·gold 생성 시각 칸 이름은 `silver_at`·`gold_at`(gold doc·ParsingMeta 같은 이름) — `created_at`은 문서가 생긴 시각(원천)으로만.
- 이유: 표·칸 정의가 Alembic 마이그레이션(`common/store/db/migrations/versions/`), `docs/operations/parsing_meta_mssql.sql`(ParsingMeta만), `AI.FileStorageMap`을 읽는 코드(정의 없음)에 흩어져 있다. 10-20 축소 스키마는 코드에 반만 반영됐다(mc-10, mc-11).
- 결정(사용자 10-29 grill): 문서 하나 `docs/architecture/db_schema.md` — 표마다 칸, 타입, 뜻, 어느 코드가 쓰고 읽는지. 대상: EDW `AI.FileStorageMap`(id, s3_key, original_filename, file_size, `last_modified_time` 가정), `AI.ParsingMeta`(+ `gold_status`), pgvector 검색 스키마. 10-20 축소 스키마가 정답이고 다른 코드는 mc-10/mc-11에서 고친다. 시험 하나가 문서의 칸을 마이그레이션·mssql SQL과 대조한다. 구현 전에 사용자와 DB 담당자가 승인하고, DB 담당자는 이 문서를 받는다.
- 결정(사용자 10-30 grill — gold 스키마):
  - 키: 문서 키는 `s3_key` 하나(gold `doc.file_path` = 원본 경로 — 아래). sha256 `doc_key`는 검색 DB에 두지 않는다([mcp.md#mc-15](mcp.md#mc-15)). chunk는 `doc_id`만.
  - gold: 0.2.0에 원천 시스템별 PG 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other` — [pl-28](#pl-28), A2), 스키마마다 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat`. MCP `search`는 원천을 필수·값 하나로 받는다(G20, 계약 변경 — 등급 A).
  - 원천 = `AI.FileStorageMap.source_system`. s3_key 접두와 다르면 → 경고 기록만.
  - 결정(허브 10-31, 최신 결정 우선): `FAQ`는 제 원천 값이다(G4·A2, 스키마 `faq` — [pl-39](extract.md#pl-39)). 비었거나 `SFDC`·`CRMS`·`LAS`·`FAQ`가 아니면 → `Other`.
  - SFDC 전용 칸(`sf_acc_name`, `sf_op_id`, `sf_op_name`, `project_code__c`)은 `sfdc` 스키마의 `doc`에 둔다([pl-28](#pl-28)).
  - Alembic 판 표는 기준 스키마에 남고 공용. `chunk`에는 `source_system`도 `clients[]`도 두지 않는다 — 스키마가 원천을 정하고, 고객 거르기는 `doc.client_edw`로 문서 범위를 고른다([pl-28](#pl-28)). 청크는 `doc_id`만.
  - `AI.ParsingMeta`는 읽는 칸만 남긴다: `source_system`, `source_key`(s3_key), `parse_date`, `parse_status`, `status`, `status_at`, `rep_bucket`, `rep_key`, 새 `gold_status` + 이유([pl-24](ops.md#pl-24)). `doc_key`와 안 읽는 칸 14개는 없앤다. → 10-30 grill에서 단계별 칸을 다시 더함(아래).
  - 마스터 성격 자료(용어집, 고객 명부(C-21), `contract_master`, `client_master`)는 git `resources/vocab/glossary/` CSV가 원본이고 검색 PG `<PG_SCHEMA>_master`에 적재한다([load.md#pl-38](load.md#pl-38)). 파일·머리글은 `db_schema.md` §5.
  - git의 CSV는 샘플 데이터(사용자 10-30) — server-guide §5 기밀 규칙과 충돌 없음.
- 결정(사용자 10-30 — 고객 칸): 문서당 고객 하나는 EDW 조인 사슬에서 온다(값 하나). 문서 글에서 찾은 고객은 별도 목록. MCP 고객 거르기는 EDW 고객**만** 쓰고, EDW 고객이 없는 문서는 고객 거르기를 걸면 빠진다. 글에서 찾은 고객을 거르기에 쓰는 것은 나중([pl-28](#pl-28)).
- 이름 규칙(사용자 10-30): EDW와 문서 파싱 양쪽에서 올 수 있는 칸은 출처를 이름에 넣어 두 칸으로 둔다(예: `client_edw`, `clients_doc`). 정확한 접미어는 `db_schema.md`가 정한다.
- 나누는 시점(사용자 10-30 4차 grill): 0.2.0에 원천별 스키마 5벌로 만든다([pl-28](#pl-28)).
- 결정(사용자 10-30 grill 7차): `db_schema.md` U-1..U-6은 초안대로. U-7: `s3_key`당 `doc` 행 하나, `doc_alias` 없음 — `build_bundle`의 같은 파일 내용 해시 합치기(첫 키로 모음, `aliases`)를 지운다. 같은 내용이 두 키에 있으면 문서 둘(임베딩 캐시가 벡터를 재사용). D-2: EDW 고객 조인은 파이프라인이 직접 만든다 → [pl-29](load.md#pl-29).
- 결정(사용자 10-30 grill — ParsingMeta 단계별, 성공 때만 씀 — 등급 A, DB 담당자 D-3): 위 "읽는 칸만"에 칸을 다시 더한다 — ② 성공한 엔진만(이름 + 판) ③ 문서마다 대표 silver 엔진 + 판 ④ gold 모듈·파이프라인 판(gold가 끝나기 전에는 NULL) ⑤ `gold_status`(앞의 결정 그대로) ⑥ 실패한 엔진(이름·이유·걸린 시간 — 사용자 10-30 "EDW에도"). 저장 구조는 [pl-32](#pl-32).
- 결정(사용자 10-30 grill — 검토):
  - 0.2.0에 Alembic 마이그레이션 하나로 gold 변경과 struct 지우기(마스터·문서 파생 표·`prod_master`)를 함께 — DB 담당자 승인 한 번.
  - gold `doc.file_path`는 **남는다**(11-03 확인): 문서 키 = Object Storage 원본 경로 = EDW `s3_key`(사용자 11-02 — [db_schema.md](../architecture/db_schema.md) 문서 키), 적재가 건너뛰기 키로 쓰고 원문 도구가 ParsingMeta와 이 칸으로 잇는다([mcp.md#mc-17](mcp.md#mc-17)), 검색 근거 `file_path`도 이 값이다(`doc.s3_key` 칸은 없음).
  - 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 파이프라인이 EDW에서 직접 읽는다 — [pl-29](load.md#pl-29)의 고객 조인과 같은 자리.
- 파일: `docs/architecture/db_schema.md`(새), `docs/INDEX.md`, `common/store/db/migrations/versions/`, `docs/operations/parsing_meta_mssql.sql`, `tests/server/common/`(시험 하나).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖)):
  - M4·T4: gold `doc`에 `doc_class`(분류 라벨 하나 — C5. 모델·시각·`low_conf` 칸은 어디에도 없음 — 판은 ParsingMeta `silver_version`·`gold_version`, 사용자 11-02)와 `created_at`(원천 등록 시각을 KST로 해석)을 더한다 — Alembic(D-6).
  - C2·T8: 분류·고객 결과는 gold(pgvector)에만 doc 단위로. 운영이 ParsingMeta에 더한 분류·고객 칸은 0.2.0과 동시에 지운다(DB 담당자 D-3, 등급 A). 그때 운영 분류 스크립트가 멈춘다 — 운영 담당자에게 알릴 것.
  - G4(2차 grill(사용자 10-30, 원본은 git 밖)): `source_system` 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`로 통일(T9와 함께) — MCP 두 도구에서 `-test`가 붙은 입력(`SFDC-test` 등)도 같은 뜻으로 받는다([mcp.md#mc-16](mcp.md#mc-16)).
  - T9: `source_system`·`parse_status` 값 정리(`pipeline/extract/source.py`, `pipeline/transform/structure/build_bundle.py`).
- 결정(G19 — 4차 grill(사용자 10-30)): EDW `AI.ParsingMeta`에는 **파싱 정보만** 적재한다 — 원천 키·파싱 상태·silver 위치·단계별 칸(엔진·`rep_engine`·`parsed_at`·`gold_status` 등). **파일 메타**(`doc_class`·`sf_op_id`·`created_at`·고객 등)는 ParsingMeta에 쓰지 않고, 파이프라인이 EDW(`FileStorageMap` 등)에서 읽어 **pgvector 시스템별 `doc`에만** 매핑해 적재한다(중복 적재 없음 — 예외: 원본 지문 `sha256`은 ParsingMeta에 남김, C5 아래). 운영이 ParsingMeta에 더한 분류·고객 칸은 모두 0.2.0에 지운다(사용자 10-30: 지금 코드가 0.1.0, DB·저장 작업은 0.2.0 — T8 범위가 다시 원래대로, DB 담당자 D-3). 원천별 스키마는 [pl-28](#pl-28).
- 결정(사용자 10-30 PRD grill): C1 — 0.1.0에 싣기로 했던 행(pl-25·pl-32·pl-33·pl-39·mc-16·mc-17·op-01·e2-15)은 0.1.0(10-30 릴리스)에 들어가지 않았다. op-08·pl-28과 함께 0.2.0 한 판에 싣고 서버 재처리·재적재는 한 번. C3 — 파싱이 통째로 실패한 문서는 ParsingMeta에 행을 쓰지 않는다(pl-24 따름). C5 — 같은 내용 묶기용 `sha256`은 ParsingMeta에 남긴다(삭제 목록에서 뺌 — G19 '파싱 정보만'의 예외: 파싱한 원본의 지문).
- 결정(사용자 10-30 PRD grill): A1 — db_schema.md는 gold-per-system 병합 뒤 오늘 결정(C3·C4·C5·C8·C9·A2)까지 반영해 다시 쓰고, 사용자·DB 담당자 승인을 한 번에 받는다.
- 결정(사용자 10-31 grill, db_schema 질문 답):
  - `doc.source_system`도 지운다(스키마가 원천을 정함 — 청크와 같음).
  - 원천 id(영업 기회 id 등)는 스키마마다 그 EDW 원본 표의 칸 이름 그대로 — 한 이름(`sf_op_id`)을 함께 쓰지 않음. 모르는 이름은 D-1 확인.
- 결정(사용자 11-02): 이름을 맞춘다 — ParsingMeta `source_key` → `s3_key`(DB 담당자 DDL, C-76 — 코드는 바꾸기 전후 모두 돎). gold 경로 칸은 `file_path` 하나(= s3_key, 연결 키). gold doc에서 `original_filename`·`clients`·`run_id`·`pipeline_version`·파싱 이력은 두지 않는다(EDW에만). ParsingMeta에 `loaded_at`(적재 시각 — C10 예외, 적재 때 UPDATE).
- 결정(사용자 11-02): ParsingMeta 판 칸은 둘 — `silver_version`(이 행의 silver를 만든 코드 판, 게시 때 — 지금 칸 `pipeline_version`의 이름을 바꿈)·`gold_version`(gold에 올린 코드 판, 적재 때 `loaded_at`과 함께 UPDATE). 분류: 라벨 `doc_class`만 gold `doc`에 — 모델 글자·분류 시각·낮은 확신 표시 칸은 어디에도 두지 않는다(판은 `silver_version`·`gold_version`이 대신함). 대상 고르기(사용자 11-02): 추출은 EDW ParsingMeta에 그 문서의 silver 결과나 gold 결과(`gold_version`)가 없으면 대상으로 고른다 — 이것이 유일한 선택 규칙이다(따로 다시 시도하는 고리·분류 명령 없음). 분류([pl-33](transform.md#pl-33))는 적재 안에서 적재의 보통 silver 고르기로 하고, 실패하면 그 문서의 적재가 실패로 세어져 `gold_version`이 안 써지므로 다음 실행에서 다시 대상이 된다. 구현(`feature/pm-versions`): `parsing_meta_db.done_source_keys`·run_docs `edw_done_keys` — `gold_version` 칸이 있으면 ok·partial은 `gold_version`도 있어야 끝(`skipped_dup`은 gold에 안 올리므로 그대로 끝), 칸이 생기기 전(C-76 ③)에는 지금처럼 `parse_status`만. DB 담당자 DDL은 refactor.md C-76 한 곳(값 꼴은 0.2.0에 DB 담당자와). 구현(`feature/pm-versions`): 코드는 이름 바꾸기 전후 모두 돎(`parsing_meta_db.RENAMES` — `source_key`→`s3_key`와 같은 길), 원문 도구는 EDW 조회가 끊기면 한 번 다시 연결(운영 `_pm_retry`와 같음), 시험 `tests/server/common/test_pm_versions.py`.
- 결정(사용자 11-03 — [load.md#pl-38](load.md#pl-38)): `gold_version` 꼴 = `<VERSION>+m<마스터 해시 앞 8자>` — 구조화가 읽은 PG 마스터 표(`<PG_SCHEMA>_master`, 용어집·고객 명부)의 내용 해시를 묶음 `meta.json` `master_hash`로 넘기고 적재가 쓴다(`master_hash`가 없는 묶음은 `<VERSION>`만, 예 `0.2.0+m58a24b02`). `silver_version`은 `<VERSION>` 그대로(대표 결과는 마스터를 읽지 않음). 마스터 해시는 캐시 열쇠·code_fp에 없다 — 마스터를 고쳐도 자동 재처리 없이 `gold_version`으로 추적. 칸 길이 NVARCHAR(64) 안(판 + 10자). 구현 `pipeline/load/pgvector_load.py` `gold_version`.
- Status: dev — `docs/architecture/db_schema.md` 설계안 + 시험 `tests/server/common/test_db_schema.py`(`feature/db-schema-spec`) — 사용자·DB 담당자 승인 대기(코드·스키마 변경 없음).

<a id="pl-28"></a>
## pl-28 · 원천 시스템별 gold 스키마 — 0.2.0에 만든다
- 결정(사용자 10-31 범위 축소 grill): 5벌 그대로(재확인) — 원천 시스템마다 메타 연결 칸이 다르다(사용자). 5벌이 doc_id 시퀀스 하나를 함께 씀 — 사용자 확인(11-01).
- 이유: SFDC · CRMS · LAS · FAQ · Other는 메타데이터가 다르다. 원천마다 표 하나면 칸이 깔끔하다.
- 무엇(사용자 10-30): gold 표 묶음 — `doc`, `chunk`, BM25 표(`chunk_term`, `term_stat`, `corpus_stat`) — 이 원천마다 한 벌씩(5벌 — A2 아래). 원천마다 칸이 다를 수 있다(SFDC 전용 `sf_*`, `project_code__c`는 SFDC doc 표로). Alembic 판 표는 공용. 그때 MCP `search`가 원천을 필수로 받는다 — 계약 변경 한 번, 새 판, 검토 등급 A. 또 나중에: 글에서 찾은 고객(`clients_doc`)도 고객 거르기에 허용.
- 결정(4차 grill(사용자 10-30) — 0.2.0에 만든다):
  - 나누는 방식: 원천 시스템마다 **PG 스키마 하나**(5벌 `sfdc`·`crms`·`las`·`faq`·`other` — A2 아래). 스키마마다 같은 표 구성 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat` + 그 시스템 전용 메타 칸. BM25 통계도 시스템별. Alembic은 한 모델을 스키마마다 적용한다. Alembic 판 표(+ `doc_id_seq`)는 기준 스키마에 공용.
  - 파일 메타(고객 `client_edw`, `sf_*`, `doc_class`, `created_at`, `contract_id` 등)는 **`doc`에만** 둔다. `chunk`는 `doc_id`만 갖고(`s3_key`는 `doc`에만 — 10-31) 메타를 복사하지 않는다(예외: `faq` 스키마만 `chunk.faq_group` — C4 아래). `doc` 표는 문서 단위 조회(`list_doc_fulltext`)에 쓰이므로 남긴다.
  - 거르기: 먼저 `doc`에서 문서 범위를 고르고 그 안의 `chunk`만 찾는다(지금 "저장소 단계 범위 제한"과 같은 방식). 메타 갱신은 `doc` 행 UPDATE 한 번으로 끝난다(chunk 값이 어긋날 일 없음).
  - MCP: `source_system`이 **필수, 값 하나** — 그 시스템 스키마만 찾는다. 여러 시스템은 클라이언트가 여러 번 부른다(시스템별 BM25 통계라 점수를 섞지 않음). [mcp.md#mc-16](mcp.md#mc-16), [mcp.md#mc-17](mcp.md#mc-17). 계약 변경 — 등급 A, 0.2.0에 함께.
- 결정(사용자 10-30 PRD grill): C2 — MCP 계약이 바뀌어도 0.2.0(버전 규칙에 '1.0 전에는 MINOR에서도 계약·스키마를 깰 수 있음'을 더함 — 운영이 안정되면 1.0.0). C4 — 원천 스키마마다 칸 구조가 다를 수 있다: `faq` 스키마만 `chunk`에 `faq_group` 칸을 두고, 다른 원천은 '파일 메타는 `doc`에만' 그대로. A2 — 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other`), MCP `source_system`은 `other`도 받는다.
- 결정(사용자 10-31 grill): `chunk_key` = `<doc_id>:<seq>`(gold `doc.doc_id` 자동 번호), 청크는 `doc_id`만(FK). 스키마 5벌이 **시퀀스 하나를 함께 써서** `doc_id`가 겹치지 않는다 — 허브 제안을 사용자가 확인(11-01). 적재는 `s3_key`로 upsert해 `doc_id`가 바뀌지 않는다. `doc.source_system`도 지운다. 원천 id 칸은 스키마마다 EDW 원본 칸 이름.
- 구현(11-02 `feature/mcp-ops-parity`, 등급 A — DB 스키마·MCP 계약): 판 0002를 고쳐(배포 전) 기준 스키마 `<PG_SCHEMA>`(판 표·공용 `doc_id_seq`) + 원천 스키마 5벌 `<PG_SCHEMA>_<원천>`. 원천 전용 칸·EDW 사슬은 [db_schema.md](../architecture/db_schema.md) §1·§2. 적재는 문서의 `source_system`으로 스키마를 고르고(실 PG는 한 트랜잭션), 검색 MCP는 원천마다 Retriever(풀 하나), `search`는 `source_system` 필수·값 하나. 다시 읽기 신호는 원천마다 (MAX(doc_id), COUNT(*)), 우리 스키마 표식은 판 표. 시험: `test_dbtool`·`test_db_schema`·`test_search_svc`·`test_pl13_no_prune`·`test_server_state`.
- Status: done(11-02 — 서버는 판 올리기·전체 다시 적재, refactor.md C-74·C-76)

<a id="pl-52"></a>
## pl-52 · 원천 메타 한 칸 `doc.attrs`(JSONB) — 사슬 파일이 키·거르기·근거를 정함
- 결정(사용자 11-03 grill — 0.2.0에 함께):
  - 고정 칸(5벌 모두): `doc_id`·`file_path`·`summary`·`created_at`·`client_edw`(고객 거르기는 이 칸 정확 일치 — C6)·`clients_doc`·`content_date`·`embed_model`. 그 밖의 원천 메타(영업 기회·계약·분류 힌트 등)는 모두 `doc.attrs JSONB`(GIN 색인)의 키다. `faq.chunk.faq_group`은 청크 칸이라 그대로 둔다(시트 이름은 청크마다 — `FAQ_group` 거르기도 그대로).
  - 판 0005(Alembic만, 실행 중 DDL 없음): 5벌에 `attrs` + GIN 색인, `v_chunk_source`가 `attrs`를 낸다. 올리기는 판 0002·0003의 원천 칸 값을 같은 이름 키로 옮기고 그 칸을 뺀다(값이 없는 키는 넣지 않음, 날짜는 `YYYY-MM-DD` 글자). 되돌리기는 그 칸을 최선만 되살린다(칸 순서가 다르고, 실제 날짜가 아닌 글자는 NULL — C-89).
  - 사슬 파일 `edw_chain.yaml` — 모든 원천이 같은 꼴: `steps`(이름·`table`·`on`·선택 `when: {prefix}`) → `fields`(attrs 키마다 `from`·선택 `filter`·`evidence`·`type`) · `client_edw` · `created`. LAS 대응·SFDC 힌트·SFDC 접두 갈래도 이 파일에 있고, 코드는 사슬을 따라가는 해석기 하나다. 점검(`python -m pipeline.load.edw_meta --check`)은 단계·칸 참조, 원천마다 거르기 이름이 겹치지 않는지, 형식을 본다.
  - MCP(등급 A — 0.2.0 MINOR, 사람 검토): `search`에 `attrs: {키: 값}` 거르기(원천마다 — 모르는 키는 그 원천의 키 목록과 함께 오류, 조용한 0건 아님). 이름 있는 거르기는 사슬의 `filter:`로 attrs 키에 잇는다(`project_id` → `project_code__c` 등). 근거마다 `attrs`(사슬에서 `evidence: true`인 키만) — 근거 13칸. `contract_no`는 사슬이 잇는 계약 키의 값(없으면 null). `edw_meta` 도구가 원천마다 거를 수 있는 키·근거 키를 사슬 파일에서 보여 준다.
  - 분류(`pgvector_load._classify`)는 힌트를 `attrs`에서 읽는다.
  - 서버 사본은 settings.yaml 옆 `$SERVER_ENV_DIR/edw_chain.yaml`(파일 마운트 — #140), 기본 파일은 `resources/config/edw_chain.yaml`. 쓰는 법은 [release-and-patch §8-6](../operations/release-and-patch.md).
- 이유: 원천 칸을 더하거나 이름을 바꿀 때마다 Alembic 판·적재·검색 코드를 함께 고쳐야 했다. 사슬 파일 하나가 EDW 칸 → attrs 키 → 거르기 이름 → 근거 표시를 정하면 운영 쪽이 파일만 고친다.
- 구현(11-03 `feature/attrs-jsonb`):
  - 사슬 꼴의 그 밖 칸 — 단계 `where`(고정 값)·`latest`(최신 행)·`optional`·`tz`, 열쇠 목록(앞 자리부터 — 동률이면 비움), SFDC 힌트용 `sfdc_entity` 단계(접두 표·`ENTITY_CLASS`는 코드), 칸 `type: flag`·`max`. 첫 단계는 `file`이어야 하고 그 단계에 행이 없는 문서는 메타가 없다. 한 단계의 칸을 못 읽으면 그 칸만 빈다.
  - `doc_class`는 적재(분류)가 쓰는 attrs 키(`search_tables.LOAD_ATTRS` — 사슬 키로 못 씀), `doc_class` 거르기는 그 키 그대로.
  - 검색: `attrs` 거르기는 그 원천에서 `filter`가 있는 키만 받는다(힌트 키는 못 거름). 근거 `attrs`는 `evidence: true` 키 모두(값 없으면 null), `contract_no` = `filter: contract_id` 키의 값. 문서 attrs는 `search_svc`가 한 번에 읽는다(검색 층 r 코드 지문 그대로). 사슬 파일 칸은 적재·검색이 함께 읽는 하나 — `ops.paths.edw_chain`(`common.paths.edw_chain`, env 이름 `EDW_CHAIN_FILE`, 검색은 파일이 바뀌면 다음 호출부터 다시 읽음). 공용 설정 모델에 두어 모든 레이어 code_fp가 바뀌지만 0.2.0은 어차피 전체를 다시 처리한다(코디네이터 11-03). `mcp-server` compose도 사본을 붙인다. 이름을 바꾸면 안 되는 키(`doc_class`·`sf_op_id`·분류 힌트 키)는 release-and-patch §8-6에 적었다. `list_doc_fulltext`의 `doc_class`·`sf_op_id`는 attrs 키 이름 그대로 읽는다(사슬을 거치지 않음).
  - 시험: `tests/server/common/test_dbtool.py`(0005 — 옮기는 칸 = 0002+0003, 뷰·되돌리기·GIN) · `tests/server/pipeline/test_edw_meta.py`(사슬 사례·틀린 설정 15개) · `tests/server/pipeline/test_classify.py`(EDW attrs → `doc.attrs` · 힌트) · `tests/server/mcp/test_search_svc.py`(attrs 거르기·오류·근거 attrs·`contract_no`·`search_attrs`) · `tests/server/mcp/test_call_log.py`(tools/list 바이트 — 지금 값은 시험 파일).
  - 서버 확인: [refactor.md C-89](../refactoring/refactor.md).
- 파일: `common/store/db/models/search_tables.py` · `common/store/db/migrations/versions/0005_doc_attrs.py` · `common/store/edw_chain.py`(사슬 읽기·검사 — 두 앱) · `pipeline/load/edw_meta.py`(해석기) · `pipeline/load/pgvector_load.py` · `pipeline/load/classify.py` · `mcp_server/services/search/search_svc.py` · `mcp_server/services/edw_calls.py` · `mcp_server/schemas/evidence.py` · `mcp_server/routers/search_tool.py` · `mcp_server/routers/edw_tools.py` · `common/config/settings.py`(`CommonPaths.edw_chain`) · `resources/config/edw_chain.yaml` · `deploy/host/compose/compose.mcp-server.yml`.
- Status: done(11-03 — `feature/attrs-jsonb`, 서버 확인 C-89)

## 코드와 다른 점 · 지울 코드

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| `vector` 확장 만들기 | `PG_CREATE_EXTENSION=0` | — |
