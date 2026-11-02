# 적재 — DB 스키마

[PRD.md](../PRD.md) 카테고리. [load.md](load.md)의 하위 문서. DB 스키마 명세(pl-25 — 정본 `docs/architecture/db_schema.md`)와 원천 시스템별 gold 스키마(pl-28).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-25 · pl-28.

<a id="pl-25"></a>
## pl-25 · DB 스키마 명세 — pl-26·pl-23·pl-24를 만들기 전에 먼저
- 결정(사용자 10-31 범위 축소 grill): EDW 추가 기록은 **계획대로**(SupersededRow 표 + ParsingMeta 단계별 열). silver·gold 생성 시각 칸 이름은 `silver_at`·`gold_at`(gold doc·ParsingMeta 같은 이름) — `created_at`은 문서가 생긴 시각(원천)으로만.
- 이유: 표·칸 정의가 Alembic 마이그레이션(`common/store/db/migrations/versions/`), `docs/operations/parsing_meta_mssql.sql`(ParsingMeta만), `AI.FileStorageMap`을 읽는 코드(정의 없음)에 흩어져 있다. 10-20 축소 스키마는 코드에 반만 반영됐다(mc-10, mc-11, pl-14, pl-15).
- 결정(사용자 10-29 grill): 문서 하나 `docs/architecture/db_schema.md` — 표마다 칸, 타입, 뜻, 어느 코드가 쓰고 읽는지. 대상: EDW `AI.FileStorageMap`(id, s3_key, original_filename, file_size, `last_modified_time` 가정), `AI.ParsingMeta`(+ `gold_status`), pgvector 검색 스키마, `struct`. 10-20 축소 스키마가 정답이고 다른 코드는 mc-10/mc-11/pl-14/pl-15에서 고친다. 시험 하나가 문서의 칸을 마이그레이션·mssql SQL과 대조한다. 구현 전에 사용자와 DB 담당자가 승인하고, DB 담당자는 이 문서를 받는다.
- 결정(사용자 10-30 grill — gold 스키마):
  - 키: 문서 키는 `s3_key` 하나. sha256 `doc_key`를 없애고 문서 대장·`doc_hidden`·`doc_contract_link`의 키를 `s3_key`로 바꾼다([mcp.md#mc-14](mcp.md#mc-14)·[mcp.md#mc-15](mcp.md#mc-15)를 풂 — `ParsingMeta.source_key`로 rep_uri 조회). 검색 `doc`에 `s3_key`가 있어야 한다 — chunk는 `doc_id`만(`s3_key`는 `doc`에만 — 10-31).
  - gold: 0.2.0에 원천 시스템별 PG 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other` — [pl-28](#pl-28), A2), 스키마마다 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat`. MCP `search`는 원천을 필수·값 하나로 받는다(G20, 계약 변경 — 등급 A). (10-30 처음 안 "지금은 표 한 벌, 나누기는 나중"은 4차 grill에서 뒤집힘.)
  - 원천 = `AI.FileStorageMap.source_system`. (허브 10-31 고침 — `FAQ` 따로, 아래) 비었거나 SFDC/CRMS/LAS가 아니면 → `Other`. s3_key 접두와 다르면 → 경고 기록만.
  - 결정(허브 10-31, 최신 결정 우선): `FAQ`는 제 원천 값이다(G4·A2, 스키마 `faq` — [pl-39](extract.md#pl-39)). 비었거나 `SFDC`·`CRMS`·`LAS`·`FAQ`가 아니면 → `Other`.
  - SFDC 전용 칸(`sf_acc_name`, `sf_op_id`, `sf_op_name`, `project_code__c`)은 `doc` 표 하나에 둔다(다른 원천은 빈 값). 나눌 때 SFDC doc 표로 옮긴다.
  - `load_run`과 Alembic 판 표는 gold에 남고, 나눈 뒤에도 공용. (10-31 고침) `chunk`에는 `source_system`도 `clients[]`도 두지 않는다 — 스키마가 원천을 정하고, 고객 거르기는 `doc.client_edw`로 문서 범위를 고른다([pl-28](#pl-28)). 청크는 `doc_id`만.
  - `AI.ParsingMeta`는 읽는 칸만 남긴다: `source_system`, `source_key`(s3_key), `parse_date`, `parse_status`, `status`, `status_at`, `rep_bucket`, `rep_key`, 새 `gold_status` + 이유([pl-24](ops.md#pl-24)). `doc_key`와 안 읽는 칸 14개는 없앤다. → 10-30 grill에서 단계별 칸을 다시 더함(아래).
  - `struct`: 문서에서 나온 표 `doc_location`, `doc_contract_link`, `doc_table`, `doc_cell`과 그 쓰기·읽기 코드(structured link/tables, `load_tables_db`, `find_table_cells`, 집계 `doc_link_list`/`table_cell_list`/`doc_location_list`, `AG.struct` 서버 길)를 지운다 — 그 내용은 청크 글에만 있다. (11-01) struct 스키마 전체를 코드에서 없앰 — 엔진 구성·원천 목록은 파일([pl-08](load.md#pl-08)).
  - 마스터 성격 자료(용어집, 고객 명부(C-21), `contract_master`, `client_master`)는 모두 **CSV 파일**로 둔다(사용자 10-30 — grill 9~10차 "마스터 PG"를 뒤집음). 별도 마스터 Postgres도, 용어집용 SQLite도 없다. CSV(샘플 데이터)는 git `resources/vocab/glossary/`(지금 폴더)에 두어 이미지에 함께 들어간다 — 서버 폴더·마운트 없음. 파일·머리글은 `db_schema.md` §5.
  - (10-31 고침) `pipeline_version`(C-62)은 두 곳 모두에 둔다 — gold `doc.pipeline_version` = 이 행을 만든 코드 판, ParsingMeta `pipeline_version` = 이 문서를 gold에 올린 판(C9 뜻 그대로, 이름만 맞춤 — `db_schema.md`).
  - 후속 구현: `.example`을 샘플 CSV로(10-30 끝 — `client_roster`·`client_master`·`contract_master.csv`). 결정(사용자 10-30): `glossary_dir`·`client_roster`는 기본값 없는 선택 settings.yaml 키 그대로(코드 기본값 안 바꿈). PG 마스터 표·`structured load --csv-dir` 지우기는 이 행 구현·설계 검토(grill 중) 때(todo).
  - git의 CSV는 샘플 데이터(사용자 10-30) — server-guide §5 기밀 규칙과 충돌 없음.
  - EDW 벡터 표(`chunk_vec`, `edw_insert`, `edw_search`)는 PR #5가 지운다.
- 결정(사용자 10-30 — 고객 칸): 문서당 고객 하나는 EDW 조인 사슬에서 온다(값 하나). 문서 글에서 찾은 고객은 별도 목록. MCP 고객 거르기는 EDW 고객**만** 쓰고, EDW 고객이 없는 문서는 고객 거르기를 걸면 빠진다. 글에서 찾은 고객을 거르기에 쓰는 것은 나중([pl-28](#pl-28)). 지금은 둘이 `clients[]`에 섞여 있고(`build_bundle.infer_clients`) `chunk.clients`가 하드 거르기를 이끈다 — 이 행과 함께 고친다.
- 이름 규칙(사용자 10-30): EDW와 문서 파싱 양쪽에서 올 수 있는 칸은 출처를 이름에 넣어 두 칸으로 둔다(예: `client_edw`, `clients_doc`). 정확한 접미어는 `db_schema.md`가 정한다.
- 나누는 시점(사용자 10-30): 처음 B(지금은 표 한 벌) → 4차 grill에서 뒤집힘 — 0.2.0에 원천별 스키마 5벌로 만든다([pl-28](#pl-28)).
- 결정(사용자 10-30 grill 7차): `db_schema.md` U-1..U-6은 초안대로. U-7: `s3_key`당 `doc` 행 하나, `doc_alias` 없음 — `build_bundle`의 같은 파일 내용 해시 합치기(첫 키로 모음, `aliases`)를 지운다. 같은 내용이 두 키에 있으면 문서 둘(임베딩 캐시가 벡터를 재사용). D-2: EDW 고객 조인은 파이프라인이 직접 만든다 → [pl-29](extract.md#pl-29).
- 결정(사용자 10-30 grill — ParsingMeta 단계별, 성공 때만 씀 — 등급 A, DB 담당자 D-3): 위 "읽는 칸만"에 칸을 다시 더한다 — ① `stack_version`(파싱 엔진 스택 판, 엔진이 모두 실패하면 NULL) ② 성공한 엔진만(이름 + 판) ③ 문서마다 대표 silver 엔진 + 판 ④ gold 모듈·파이프라인 판(gold가 끝나기 전에는 NULL) ⑤ `gold_status`(앞의 결정 그대로) ⑥ 실패한 엔진(이름·이유·걸린 시간 — 사용자 10-30 "EDW에도"). 저장 구조는 [pl-32](load.md#pl-32).
- 결정(사용자 10-30 grill — 검토):
  - 0.2.0에 Alembic 마이그레이션 하나로 gold 변경과 struct 지우기(마스터·문서 파생 표·`prod_master`)를 함께 — DB 담당자 승인 한 번.
  - gold `doc.file_path`는 지운다. 보여 줄 때는 `s3_key` + 새 원본 파일 이름 칸(`FileStorageMap.original_filename`에서). 고칠 곳: `mcp_server/services/search/{pgsearch,retriever,search_svc,shaping,local,aggregate}.py`, `mcp_server/schemas/evidence.py`(`search` 근거 출력의 `file_path` 키), `mcp_server/cli/ask.py`, `common/store/db/models/search_tables.py`(칸·`VIEWS_EXPECTED`·뷰 SQL), `common/store/db/schemas/search_rows.py`, 뷰 `v_chunk_source`(`common/store/db/migrations/versions/0001_search_base.py`), `pipeline/load/pgvector_load.py`·`pipeline/transform/structure/build_bundle.py`(적재가 `file_path`를 건너뛰기 키로 씀 → `s3_key`가 대신함), `validation/search_ui/serve.py`.
  - MCP `search` 근거 출력의 `file_path` 제거는 [mcp.md#mc-16](mcp.md#mc-16)에서 다룬다(사용자 10-30 PRD grill D1).
  - 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 파이프라인이 EDW에서 직접 읽는다 — [pl-29](extract.md#pl-29)의 고객 조인과 같은 자리. 외부 파일 `file_meta_new.jsonl`은 없어진다.
- 파일: `docs/architecture/db_schema.md`(새), `docs/INDEX.md`, `common/store/db/migrations/versions/`, `docs/operations/parsing_meta_mssql.sql`, `tests/server/common/`(시험 하나).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖)):
  - M4·T4: gold `doc`에 `doc_class`(분류 라벨 하나 — C5, low_conf·모델·시각은 두지 않음)와 `created_at`(원천 등록 시각을 KST로 해석)을 더한다 — Alembic(D-6).
  - C2·T8: 분류·고객 결과는 gold(pgvector)에만 doc 단위로. 운영이 ParsingMeta에 더한 분류·고객 칸은 0.2.0과 동시에 지운다(DB 담당자 D-3, 등급 A). 그때 운영 분류 스크립트가 멈춘다 — 운영 담당자에게 알릴 것.
  - (G19로 뒤집힘 — 아래) G1(2차 grill(사용자 10-30, 원본은 git 밖) — C2를 고침): EDW `ParsingMeta`에 `doc_class`·`sf_op_id`·`parsed_at`·`rep_engine`·`created_at` 5칸은 **남긴다**(`created_at` — G9, 원천 등록 시각을 `FileStorageMap.created_at`에서 옮김, KST) — 파이프라인이 쓰고 `list_doc_fulltext`([mcp.md#mc-17](mcp.md#mc-17))가 목록으로 읽는다(운영 계약 그대로). 나머지 운영 고객 칸(`sf_acc_name` 등)은 0.1.0에서 지운다. `doc_class`는 ParsingMeta와 pgvector `doc` 양쪽에 쓴다. T8 범위는 이만큼 줄어든다.
  - G4(2차 grill(사용자 10-30, 원본은 git 밖)): `source_system` 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`로 통일(T9와 함께) — MCP 두 도구에서 `-test`가 붙은 입력(`SFDC-test` 등)도 같은 뜻으로 받는다([mcp.md#mc-16](mcp.md#mc-16)).
  - T9: `source_system`·`parse_status` 값 정리(`pipeline/extract/source.py`, `pipeline/transform/structure/build_bundle.py`).
- 결정(G19 — 4차 grill(사용자 10-30), G1·G9를 뒤집음): EDW `AI.ParsingMeta`에는 **파싱 정보만** 적재한다 — 원천 키·파싱 상태·silver 위치·단계별 칸(`stack_version`·엔진·`rep_engine`·`parsed_at`·`gold_status` 등). **파일 메타**(`doc_class`·`sf_op_id`·`created_at`·고객 등)는 ParsingMeta에 쓰지 않고, 파이프라인이 EDW(`FileStorageMap` 등)에서 읽어 **pgvector 시스템별 `doc`에만** 매핑해 적재한다(중복 적재 없음 — 예외: 원본 지문 `sha256`은 ParsingMeta에 남김, C5 아래). 운영이 ParsingMeta에 더한 분류·고객 칸은 모두 0.2.0에 지운다(사용자 10-30: 지금 코드가 0.1.0, DB·저장 작업은 0.2.0 — T8 범위가 다시 원래대로, DB 담당자 D-3). MCP 원문 도구는 EDW를 읽지 않는다([mcp.md#mc-17](mcp.md#mc-17)). 원천별 스키마는 [pl-28](#pl-28).
- 결정(사용자 10-30 PRD grill): C1 — 0.1.0에 싣기로 했던 행(pl-25·pl-32·pl-33·pl-39·mc-16·mc-17·op-01·pl-17·e2-15)은 0.1.0(10-30 릴리스)에 들어가지 않았다. op-08·pl-28과 함께 0.2.0 한 판에 싣고 서버 재처리·재적재는 한 번. C3 — 파싱이 통째로 실패한 문서는 ParsingMeta에 행을 쓰지 않는다(pl-24 따름 — `stack_version` NULL 문구는 '일부 엔진 실패' 기록용이 아님, 지움). C5 — 같은 내용 묶기용 `sha256`은 ParsingMeta에 남긴다(삭제 목록에서 뺌 — G19 '파싱 정보만'의 예외: 파싱한 원본의 지문).
- (10-31 고침 — 이름은 둘 다 `pipeline_version`, 아래) 결정(사용자 10-30 PRD grill): C9 — 판 표기는 둘 다 두고 뜻을 나눈다: ParsingMeta `gold_version` = 이 문서를 gold에 올린 판(다시 올릴지 판단), gold `doc`의 판 = 이 행을 만든 코드 판(검색 쪽 확인).
- 결정(사용자 10-30 PRD grill): A1 — db_schema.md는 gold-per-system 병합 뒤 오늘 결정(C3·C4·C5·C8·C9·A2)까지 반영해 다시 쓰고, 사용자·DB 담당자 승인을 한 번에 받는다.
- 결정(사용자 10-31 grill, db_schema 질문 답):
  - 판 이름: 두 곳 모두 `pipeline_version` — ParsingMeta `gold_version` 안은 없애고 그 칸 이름을 쓴다(ParsingMeta = gold에 올린 판, gold `doc` = 행을 만든 코드 판 — C9 뜻 그대로, DB 담당자 D-3).
  - `doc.source_system`도 지운다(스키마가 원천을 정함 — 청크와 같음).
  - `s3_key`는 gold `doc`에만(청크에는 없음). `source_uri`는 `doc.s3_key`로, `rep_uri`는 `doc.rep_key`로(C8).
  - 원천 id(영업 기회 id 등)는 스키마마다 그 EDW 원본 표의 칸 이름 그대로 — 한 이름(`sf_op_id`)을 함께 쓰지 않음. 모르는 이름은 D-1 확인.
- 결정(사용자 11-01): ParsingMeta에 s3_key 칸 없음 — 연결은 source_system + source_key(원본 전체 경로). rep_engine·stack_version 없음(gold doc.rep_engine도)
- 결정(사용자 11-02, 위를 고침): 이름을 맞춘다 — ParsingMeta `source_key` → `s3_key`(DB 담당자 DDL, C-76 — 코드는 바꾸기 전후 모두 돎). gold 경로 칸은 `file_path` 하나(= s3_key, 연결 키). gold doc에서 `original_filename`·`clients`·`run_id`·`pipeline_version`·파싱 이력은 두지 않는다(EDW에만). ParsingMeta에 `loaded_at`(적재 시각 — C10 예외, 적재 때 UPDATE).
- Status: dev — `docs/architecture/db_schema.md` 설계안 + 시험 `tests/server/common/test_db_schema.py`(`feature/db-schema-spec`) — 사용자·DB 담당자 승인 대기(코드·스키마 변경 없음).

<a id="pl-28"></a>
## pl-28 · 원천 시스템별 gold 스키마 — 0.2.0에 만든다
- 결정(사용자 10-31 범위 축소 grill): 5벌 그대로(재확인) — 원천 시스템마다 메타 연결 칸이 다르다(사용자). 5벌이 doc_id 시퀀스 하나를 함께 씀 — 사용자 확인(11-01).
- 이유: SFDC · CRMS · LAS · FAQ · Other는 메타데이터가 다르다. 원천마다 표 하나면 칸이 깔끔하다.
- 무엇(사용자 10-30): gold 표 묶음 — `doc`, `chunk`, BM25 표(`chunk_term`, `term_stat`, `corpus_stat`) — 이 원천마다 한 벌씩(5벌 — A2 아래). 원천마다 칸이 다를 수 있다(SFDC 전용 `sf_*`, `project_code__c`는 SFDC doc 표로). `load_run`과 Alembic 판 표는 공용. 그때 MCP `search`가 원천을 필수로 받는다 — 계약 변경 한 번, 새 판, 검토 등급 A. 또 나중에: 글에서 찾은 고객(`clients_doc`)도 고객 거르기에 허용.
- 결정(4차 grill(사용자 10-30) — 위 "나중"을 뒤집음, 0.2.0에 만든다 — 지금 코드가 0.1.0):
  - 나누는 방식: 원천 시스템마다 **PG 스키마 하나**(5벌 `sfdc`·`crms`·`las`·`faq`·`other` — A2 아래). 스키마마다 같은 표 구성 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat` + 그 시스템 전용 메타 칸. BM25 통계도 시스템별. Alembic은 한 모델을 스키마마다 적용한다. `load_run`과 Alembic 판 표는 공용.
  - 파일 메타(고객 `client_edw`, `sf_*`, `doc_class`, `created_at`, `contract_id` 등)는 **`doc`에만** 둔다. `chunk`는 `doc_id`만 갖고(`s3_key`는 `doc`에만 — 10-31) 메타를 복사하지 않는다(예외: `faq` 스키마만 `chunk.faq_group` — C4 아래). `doc` 표는 문서 단위 조회(`list_doc_fulltext`, 수동 갱신 [pl-40](load.md#pl-40))에 쓰이므로 남긴다.
  - 거르기: 먼저 `doc`에서 문서 범위를 고르고 그 안의 `chunk`만 찾는다(지금 "저장소 단계 범위 제한"과 같은 방식). 메타 갱신은 `doc` 행 UPDATE 한 번으로 끝난다(chunk 값이 어긋날 일 없음).
  - MCP: `source_system`이 **필수, 값 하나** — 그 시스템 스키마만 찾는다. 여러 시스템은 클라이언트가 여러 번 부른다(시스템별 BM25 통계라 점수를 섞지 않음). [mcp.md#mc-16](mcp.md#mc-16), [mcp.md#mc-17](mcp.md#mc-17). 계약 변경 — 등급 A, 0.2.0에 함께(지금 코드가 0.1.0이므로 G7의 "0.1.0에 함께" 대신).
  - 위 `chunk`의 `source_system`·`clients[]` 유지([pl-25](#pl-25))는 스키마가 원천을 정하므로 필요 없어진다 — `db_schema.md`를 이에 맞게 고친다.
- 결정(사용자 10-30 PRD grill): C2 — MCP 계약이 바뀌어도 0.2.0(버전 규칙에 '1.0 전에는 MINOR에서도 계약·스키마를 깰 수 있음'을 더함 — 운영이 안정되면 1.0.0). C4 — 원천 스키마마다 칸 구조가 다를 수 있다: `faq` 스키마만 `chunk`에 `faq_group` 칸을 두고, 다른 원천은 '파일 메타는 `doc`에만' 그대로. A2 — 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other`), MCP `source_system`은 `other`도 받는다.
- 결정(사용자 10-31 grill): `chunk_key` = `<doc_id>:<seq>`(gold `doc.doc_id` 자동 번호), 청크는 `doc_id`만(FK). 스키마 5벌이 **시퀀스 하나를 함께 써서** `doc_id`가 겹치지 않는다 — 허브 제안을 사용자가 확인(11-01). 적재는 `s3_key`로 upsert해 `doc_id`가 바뀌지 않는다. `doc.source_system`도 지운다. 원천 id 칸은 스키마마다 EDW 원본 칸 이름.
- 구현(11-02 `feature/mcp-ops-parity`, 등급 A — DB 스키마·MCP 계약): 판 0002를 고쳐(배포 전) 기준 스키마 `<PG_SCHEMA>`(판 표·공용 `doc_id_seq`) + 원천 스키마 5벌 `<PG_SCHEMA>_<원천>`. 원천 전용 칸·EDW 사슬은 [db_schema.md](../architecture/db_schema.md) §1·§2. 적재는 문서의 `source_system`으로 스키마를 고르고(실 PG는 한 트랜잭션), 검색 MCP는 원천마다 Retriever(풀 하나), `search`는 `source_system` 필수·값 하나. chunk는 `char_*`·`n_chars`·`embed_model`·`clients`·`source_system`을 지웠다. `load_run`을 지우고 실행 정보는 실행 기록, 다시 읽기 신호는 원천마다 (MAX(doc_id), COUNT(*)), 우리 스키마 표식은 판 표. 시험: `test_dbtool`·`test_db_schema`·`test_search_svc`·`test_pl13_no_prune`·`test_server_state`.
- Status: done(11-02 — 서버는 판 올리기·전체 다시 적재, refactor.md C-74·C-76)

## 코드와 다른 점 · 지울 코드

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| `vector` 확장 만들기 | `PG_CREATE_EXTENSION=0` | — |
