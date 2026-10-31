# ETL — 수집·퍼블리시·적재·DB

[PRD.md](../PRD.md) 카테고리. 수집 → 파싱([parse.md](parse.md)) → 구조화 → 적재(pgvector·정형 DB)·게시(silver), 서버 러너(`run_docs.py`) 레인·대기열.

순서(주제별): 수집 pl-01·pl-29 → 구조화 pl-06·pl-15·pl-16 → 적재 pl-07·pl-13·pl-14·pl-19 → 정형 DB·문서 대장 pl-08·pl-38·pl-12 → 게시 pl-09·pl-26 → 실행·흐름 러너 pl-10·pl-18·pl-23·pl-24·rn-01·rn-02·rn-03·rn-04 → DB 스키마·저장 구조·분류·FAQ·수동 갱신 pl-25·pl-32·pl-33·pl-39·pl-41·pl-40·pl-28 → 코드와 다른 점.

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기
- 이유: 문서는 폴더, Object Storage, 회사 RDB 목록에서 온다.
- 무엇: `input_source` = 폴더 · `s3://버킷/접두` · `rdb:csv:<경로>` · `rdb:<표>`. RDB 열 대응(`RDB_COL_*`), since/watermark 증분, 스트리밍(한 묶음 받기 → 파싱 → 지우기), 미리 받기(warm), 서버 원천 목록은 `struct.source_version`에 판으로 둔다.
- 파일: `pipeline/extract/source.py`, `pipeline/extract/rdb_discover.py`, `pipeline/stream.py`, `resources/mappings/sources.json`.
- Status: done

<a id="pl-29"></a>
## pl-29 · EDW 고객 매핑을 파이프라인이 직접 만든다
- 이유: 문서마다 EDW 고객 하나(`client_edw` — MCP 고객 거르기의 유일한 키, [pl-25](#pl-25))와 SFDC 칸(`sf_acc_name`·`sf_op_id`·`sf_op_name`·`project_code__c` 등)을 지금은 외부에서 뽑은 `file_meta_new.jsonl`(`pipeline.paths.file_meta_path`)에서 읽는데, 그 파일을 만드는 코드가 저장소에 없다(db_schema.md D-2).
- 결정(사용자 10-30 grill 7차): 파이프라인이 EDW 읽기 계정(`common.connections.rdb.read`)으로 조인을 직접 만든다. SFDC: `AI.FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`(고객 = Account 이름). CRMS·LAS 경로는 DB 담당자 확인(D-2). `file_meta_new.jsonl` 읽기를 대신한다.
- 결정(사용자 10-30 grill — pl-25 검토): 고객뿐 아니라 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 같은 자리에서 EDW에서 직접 읽는다 — 외부 파일 `file_meta_new.jsonl`은 없어진다.
- 파일: `pipeline/extract/source.py`(FileStorageMap 읽기), `pipeline/transform/structure/build_bundle.py`(`_file_meta` → 조인 결과), `pipeline/config.py`(`file_meta_path`), `deploy/host/scripts/run_docs.py`(`FILE_META_PATH`), `docs/architecture/db_schema.md`.
- 선행: [pl-25](#pl-25)(스키마 — `client_edw` 칸), [pl-32](#pl-32)(저장 구조).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) C6·T7): 고객 연결은 운영 4단계를 따른다 — 출발점 `FileStorageMap`, 순서 기회 직접 > `Task.WhatId` > `Event.WhatId` > Quote 스냅샷, 계정 직접 연결도 포함. 결과는 pgvector doc에만. 같은 sha256 묶음에도 고객은 전파하지 않는다(C3).
- 열린 점: Quote 단계는 레플리카에 Quote 표가 없어 SFDC REST 스냅샷에 기댄다 — 서버에서 스냅샷을 어떻게 공급할지 정해야 함. → 해소(10-31 결정 — PC 대역 Quote 표, 아래).
- 결정(G2·T16 — 2차 grill(사용자 10-30, 원본은 git 밖)): `client_edw`(문서당 고객 하나)는 SFDC(4단계 연결)와 **CRMS**(`FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST` — DB 담당자 확인, D-2)에서 채운다. LAS는 상대사 출처가 정해질 때까지 비워 둔다. FAQ는 고객 연결 없음([pl-39](#pl-39)).
- 결정(G11 — 3차 grill(사용자 10-30, 원본은 git 밖)): 적재 뒤 바뀐 SFDC 연결(고객·`sf_op_id` 등)은 자동으로 갱신하지 않는다. 수동 요청 때 전체 문서를 갱신한다([pl-40](#pl-40)).
- 결정(사용자 10-30 PRD grill): A3 — 고객 연결의 마지막 단계(SFDC Quote 스냅샷)는 미정으로 둔다(서버 레플리카에 Quote 표 없음). 허브가 0.2.0 설계 확인 때 사용자에게 다시 묻는다. 그 전까지 구현은 기회 직접 > Task > Event 3단계(+계정 직접).
- 결정(사용자 10-31 grill): A3 — Quote 단계도 0.2.0에 넣는다. PC 대역 EDW(`valid_env/edw`)에 SFDC Quote 표를 예시 칸으로 새로 만들어 4단계(기회 직접 > Task > Event > Quote, +계정 직접)로 구현한다. 실제 표·칸 이름은 DB 담당자 답으로 맞춘다(A4 `created_at`과 같은 방식).
- Status: todo

<a id="pl-06"></a>
## pl-06 · 구조화 — 청크·메타데이터·임베딩
- 이유: 검색에는 출처가 달린 청크와 메타데이터가 필요하다.
- 무엇: 청크 나누기 structure(기본, 800자, 제목, 표는 통째) / fixed 512+64 / sentence / page, 큰 표는 25행씩. 요약(`EDW_SUMMARY_LLM=1`이면 LLM, 아니면 앞부분 — OpenViking 요약은 10-29에 지움). 사실(제품, 모달리티, 날짜, 단가, 금액, 통화, 배치). 고객·계약은 교차 확인된 것만 남긴다. 규칙 기반 지식 그래프(묶음에는 만들지만 PG에는 더 적재하지 않음 — [mcp.md#mc-12](mcp.md#mc-12)). 임베딩은 로컬(e5, bge-m3) 또는 내부 `api`.
- 파일: `pipeline/transform/structure/build_bundle.py`, `chunking.py`, `facts.py`, `draft_terms.py`, `common/ai/embed.py`.
- Status: done

<a id="pl-15"></a>
## pl-15 · structure/load 계약 점검이 새 묶음을 거부
- 이유: `contract.py`의 `DOC_KEYS`가 지운 키를 아직 기대한다(서버는 이 모듈을 쓰지 않음).
- 파일: `common/core/contract.py`(핸드오프 핑거프린트 — 사람 검토), `pipeline/cli.py`.
- 결정(사용자 10-30 PRD grill): A5 — 구조화·적재 계약 `DOC_KEYS`를 새 묶음 키에 맞게 고친다. 핸드오프 지문 파일이라 등급 A(사람 검토)이고 0.2.0 재처리에 함께 싣는다.
- Status: todo

<a id="pl-16"></a>
## pl-16 · `PIPE_EMBED=none`이면 `vector(0)`을 만든다
- 이유: 차원 0으로는 표를 만들 수 없어 임베딩 없는 구조화가 실패한다.
- 파일: `pipeline/transform/structure/build_bundle.py`, `pipeline/load/pgvector_load.py`.
- 결정(사용자 10-30 PRD grill): A6 — `PIPE_EMBED=none`(임베딩 없음)은 적재 시작 때 거부한다(검색에 벡터가 필수). 0.2.0.
- Status: todo

<a id="pl-07"></a>
## pl-07 · pgvector 적재
- 이유: 검색 서버는 PG를 읽는다.
- 무엇: 표 `load_run`·`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + 뷰 `v_chunk_source`(Alembic으로만). 이미 적재된 문서는 `file_path`로 건너뛴다(sha 열 없음 — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀). `--prune`은 남은 옛 행을 지운다. 이름 붙은 색인(`index_id`). 벡터는 pgvector에만 둔다(EDW 벡터 적재는 10-29에 지움 — [settings.md#op-03](settings.md#op-03)).
- 파일: `pipeline/load/pgvector_load.py`, `pipeline/load/index.py`, `common/store/db/migrations/`.
- Status: done

<a id="pl-13"></a>
## pl-13 · `load --prune`이 건너뛴 문서까지 지움
- 이유: 바뀌지 않아 건너뛴 문서도 지워진다(C-60).
- 파일: `pipeline/load/pgvector_load.py`.
- 결정(사용자 10-29 grill): 적재는 더하고 고치기만 하고 지우지 않는다. 건너뛴(이미 있는) 문서는 남는다. 원천에서 지워진 문서와 파싱 실패는 로컬에 기록만(원인 + 걸린 시간), 자동 삭제 없음. `load`와 그 호출부(`pipeline/cli.py` load, 색인 빌드 `--pg`)에서 prune 길을 없앤다.
- 결정(사용자 10-30 PRD grill): S1 — 브랜치가 병합됐으므로 done으로 닫는다(남은 서버 확인은 refactor.md C 항목으로).
- 한 것(10-30 병합, #17): `feature/load-no-prune`: `prune`·`--prune`·`PRUNE_*` 설정 없앰(옛 설정 칸은 경고만), `cli load`·`run-stack`·색인 빌드 `--pg`가 더는 안 붙임, `--no-prune`은 옛 호출 호환으로 받기만, 색인 빌드 `--pg`는 `--replace`로(다시 빌드 때 고침). 남은 한계: `file_path`가 바뀐 같은 내용은 옛 행이 남음(사람이 지움 — 사용자 확인). 시험 `tests/server/pipeline/test_pl13_no_prune.py`. 검토 등급 A(서버 적재 동작).
- Status: done — 남은 서버 확인은 refactor.md C-68.

<a id="pl-14"></a>
## pl-14 · 배포 backfill이 지운 `doc.client`를 읽음
- 이유: 10-20 축소 스키마 뒤 `pgvector_load deploy`의 `backfill_chunk_clients`가 실패한다(표와 색인은 그래도 만들어짐).
- 파일: `pipeline/load/pgvector_load.py`.
- Status: done (10-30, `feature/search-path-fixes`) — backfill은 남기고(사용자 10-30) `doc.clients`만 읽음(없는 `doc.client` 안 고름, `_doc_row_clients`도 `clients`만 받음). NULL인 청크만 채우고 멱등인 것은 그대로. 동작은 같음 — 축소 스키마의 고객 라벨은 원래 `clients`에만 있음. 시험: `tests/server/pipeline/test_pl14_backfill.py`(가짜 DB, 이미지) · `tests/general/pipeline/test_pl14_deploy.py`(실 PG 임시 스키마에서 `deploy()` — PG 설정 없으면 건너뜀).

<a id="pl-19"></a>
## pl-19 · compose `index_a`/`index_b`가 끝까지 돌면 실패
- 이유: C-32.
- 결정(사용자 10-30 grill): compose `index_a`/`index_b` 예시를 지운다.
- 파일: `deploy/host/`.
- Status: todo

<a id="pl-08"></a>
## pl-08 · 정형 DB와 문서 대장
- 이유: 계약·고객·문서 판이 정형 질문에 답하고 증분 실행을 이끈다.
- 무엇: `contract_master`·`client_master`·`prod_master`·`doc_contract_link`(점수 매기는 연결기)·`doc_location`·`doc_registry`·`doc_hidden`·`doc_table`·`doc_cell`. PG 또는 SQLite.
- 파일: `pipeline/load/structured.py`, `common/store/structdb.py`.
- Status: done

<a id="pl-38"></a>
## pl-38 · 마스터 CSV 활용 방안 설계(후순위)
- 결정(사용자 10-30): "contract_master, client_master 등 활용하는 방안 같이 설계하자. 후순위로 해줘."
- 사실: PR 3a 뒤에는 `resources/vocab/glossary/contract_master.csv`·`client_master.csv`를 읽는 코드가 없다. `client_master.example.csv`는 `gen_roster` 입력. 두 파일은 설계가 끝날 때까지 git에 남긴다 — 3a에서 지우지 않는다.
- 열린 질문: 마스터마다 무엇에 쓰나(검색 거르기 / 분류 단서 / mc-05의 고객 별칭 그룹), EDW 고객 연결([pl-29](#pl-29))·분류 단계([pl-33](#pl-33))와 어떻게 이어지나.
- Status: todo — 후순위, 사용자와 함께 설계(grill). 0.1.0 아님.

<a id="pl-12"></a>
## pl-12 · 문서 대장 upsert와 게시 가드
- 이유: 문서 대장 upsert에 PG 문법 오류가 있다(C-54 ①). 서버가 `source.json`을 올리지 않아 게시 가드가 꺼져 있다(C-54 ②).
- 파일: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `tests/server/pipeline/test_publish_guard.py`(알려진 실패).
- 결정(사용자 10-30 grill):
  - ① 문서 대장은 남기고 고친다 — `INSERT OR REPLACE`의 PG 번역(`structdb._pg_sql` 정규식 ↔ `registry.apply`의 여러 줄 SQL). [pl-25](#pl-25)와 함께 키를 `s3_key`로 바꾼다. 새 문서 판별은 FileStorageMap ↔ ParsingMeta 그대로([pl-23](#pl-23)).
  - ② 게시 가드는 `source.json` 사이드카 대신 EDW `AI.ParsingMeta`(`source_key` + `rep_bucket`/`rep_key`)를 읽는다. 같은 문서 → 같은 파일에 덮어씀(`-2`/`-3.md` 사본 없음). 다른 원천이 같은 결과 키로 오면 → 거부. 그러면 `test_publish_guard`가 통과 → `deploy/release/known_fail.txt`에서 뺀다.
- 결정(사용자 10-30 grill 12~13차): 원천에서 사라진 문서(deleted) 처리 길은 통째로 없앤다 — 지우기·숨기기·EDW `deleted` 표시 모두 없음, 로컬 기록만(refactor.md C-54).
- 10-30 [pl-32](#pl-32): PG `doc_registry`는 남고 로컬 SQLite 대체는 없앤다. 실패 횟수(`fail_count`)·재시도 설정(`registry_retry_max`)은 없앤다 — 성공했을 때만 갱신(사용자 10-30).
- 한 것(10-30, B1 — 개발 서버 반입 전 검토): deleted 길 없앰 — `registry.apply`가 관측에 없는 문서에 `status='deleted'`·자동 숨김을 쓰지 않고, `parsing_meta.apply_registry_status`가 EDW에 `deleted`를 쓰지 않는다(`diff["deleted"]`는 판 잇기 정보로만). 서버(dev·prd)는 SQLite·PG 스탠드인으로 대체하지 않고 멈춘다(`structdb.open_backend` — `run_mode: prod`·`struct_backend` pg/tsql 필수, `pg._warn_standin`). `common.store.run_mode`는 `prod`·`test`만. 시험 `tests/server/common/test_no_deleted.py`. code_fp p0·p1·r·s 바뀜(공용 `settings.py`·`pg.py`·`structdb.py`).
- Status: partly done — deleted 길·서버 대체 금지 끝(10-30). 남음: ① upsert PG 번역 · ② ParsingMeta 게시 가드([pl-25](#pl-25) 뒤).

<a id="pl-09"></a>
## pl-09 · 파싱 결과 게시
- 이유: 다른 팀은 결과를 Object Storage + `AI.ParsingMeta`에서 읽는다.
- 무엇: 대표 `.md` + 원결과(원본은 절대 아님)를 Object Storage에 올리고, `AI.ParsingMeta`에 INSERT만 한다. 원본 버킷으로 게시는 거부, DRM·실패 문서는 제외 보고서로.
- 파일: `pipeline/load/publish_parse_result.py`, `pipeline/load/parsing_meta.py`, `docs/operations/parsing_meta_mssql.sql`.
- Status: done

<a id="pl-26"></a>
## pl-26 · `full`은 늘 게시하고 게시 대상은 필수
- 이유: 도움말은 "EDW 적재 없음"이라 했지만 `full`은 게시했고 `NIGHTLY_PUBLISH`를 무시했다(C-31).
- 결정(사용자 10-29 grill): 게시(silver → Object Storage + EDW)가 기본이자 유일한 방식 — `--no-publish`와 `pipeline.host.nightly.publish`를 없앤다. 게시 대상은 필수 설정이고 없으면 시작을 거부한다.
- `RUN_ENV`별 대상: `local`·`dev`는 (a) 로컬 경로(Object Storage는 폴더, EDW는 파일 DB) 또는 (b) 실제 접속 정보(API·DB) 중 하나. `prd`는 실제 접속만(`stage`는 RUN_ENV에서 없앰 — op-02). PC는 CLAUDE.md §4 가드를 그대로 지킨다(PC에서 운영 EDW·OS 접속 금지).
- 파일: `pipeline/cli.py`(`night`, `full`), `deploy/docker/entrypoint.sh`, `pipeline/load/`의 게시, `pipeline/config.py`, `docs/operations/server-guide.md`.
- Status: todo

<a id="pl-10"></a>
## pl-10 · 실행 관리(오케스트레이션)
- 이유: 서버는 문서 수천 건을 사람 없이 돌린다.
- 무엇: CLI `parse`·`structure`·`load`·`night`(마감 시각, 다음 밤에 이어서)·`run-stack`·`compare-parse`·`compare-all`·`set-stack`·`show-stack`·`set-sources`·`show-sources`·`smoke`·`selftest`. 이미지 entrypoint가 `dedup`·`prepare`·`publish`·`full`·`serve-trigger`·`migrate`·`check`를 더한다(`deploy/docker/entrypoint.sh`). 서버 flow 러너(EDW 목록, 12개 미리 받기, light/medium/vlm 레인, 문서마다 컨테이너, `parse_document` 작업에 양보). trigger 서버(`/jobs`, `/upload`, Bearer). 문서별 병렬 파싱.
- 서버 flow 러너 요구(사용자 10-22·10-23 — 원문 [../history/run_docs_req.md](../history/run_docs_req.md), 바뀐 값은 rn-01·rn-02·[parse.md#pl-22](parse.md#pl-22)):
  - 문서별 flow(배치 장벽 없음) · warm 12(진행 중 제외, 끝나면 tmp 지움 — 10-29부터 20) · 컨테이너 하나에 worker 4.
  - VLM 동시 12(figure·vlm_page 포함), 문서 병렬 4, 문서당 VLM 4·OCR 1, vlm_page 끔, OCR dpi 150. 구조화+적재도 문서 단위 — 임베딩 묶음 호출(32 → 12)·문서당 병렬 4, BM25 병렬 4, 단계별 시간 기록.
  - 튜닝: `PIPE_PROCS=3`, CPU 75~85%, `RAPIDOCR_PAGE_WORKERS`·OCR threads 3(→ 2 검토), CPU 게이트 1.15 → 1.3/1.1.
  - 3클래스: warm에서 무게 평가(과거 소요 시간 규칙), vlm_page는 스캔 PDF처럼 꼭 필요한 문서만, 1/2/1 + 빈 레인 가져가기, light 1개 강하게 점유, 전담 분류 먼저, light 전용 executor. MCP 업로드가 오면 medium 전담 1개를 멈추고 먼저.
  - 속도: phase 1 건너뛰기(→ pl-22), 끝난 문서 건너뛰기, parse_qa 가볍게, 10-23 OCR 끔. SSH가 끊겨도 작업은 계속(nohup 확인).
- 파일: `pipeline/cli.py`, `deploy/host/scripts/run_docs.py`(서버 전용 — PC에서 실행 금지), `pipeline/trigger_server.py`, `pipeline/parse_parallel.py`, `docs/history/run_docs_req.md`, `docs/architecture/run_docs_design.md`.
- Status: done

<a id="pl-18"></a>
## pl-18 · 중간에 멈춰도 `night`/`full`이 종료 코드 0
- 이유: 스케줄러가 실패를 못 본다(C-33).
- 결정(사용자 10-30 grill): 종료 코드 — 대상 0건 = 0, 실패 = 1, 마감 시각 도달 = 75.
- 파일: `pipeline/cli.py`(`night`), `deploy/docker/entrypoint.sh`(`full`).
- Status: todo

<a id="pl-23"></a>
## pl-23 · 증분 실행만, 전체 재파싱은 명시적인 전체 e2e
- 이유: 엔진·핸드오프·코드 핑거프린트가 모든 문서에서 바뀌었다. 전체 자동 재파싱은 밤 작업 시간을 넘긴다(C-52, C-08).
- 결정(사용자 10-29 grill): 밤 작업과 `run_docs`는 핑거프린트가 바뀌어도 **새** 문서만 처리한다. "새" = `AI.FileStorageMap.s3_key`가 아직 `AI.ParsingMeta`에 없음(s3 키만 — 갱신 시각 확인 없음, `run_docs`는 이미 이렇게 동작). 전체 재파싱은 사람이 전체 e2e를 시작할 때만(가끔 — 로직을 바꾼 뒤, 결과를 검토). 이 판의 첫 적재는 전체 e2e 한 번.
- 결정(사용자 10-30 grill): 밤 배치는 꺼 둔다(systemd 타이머는 켜지 않음). 나중에 사람이 settings.yaml에서 켠다. → 켜기·끄기와 시각은 아래 새벽 일정 키 하나가 정한다(null = 끔) — 그 키를 구현하면 지금의 `pipeline.host.nightly.enabled`는 없어진다(그때까지 서버 절차는 enabled false).
- 결정(사용자 10-30): 새벽 배치 계획을 settings.yaml 키(파라미터)로 — null이면 새벽 배치 안 함, 값이 있으면 돈다([pl-32](#pl-32)). 켜기·끄기 스위치와 시각을 이 한 값이 정한다 — 구현(10-30 `feature/registry-success-only`): `pipeline.host.nightly.time`(`NIGHTLY_TIME`, HH:MM — 비우면 없음, 꼴이 틀리면 설정 읽기에서 거부) · 타이머 5분마다 + `trigger.sh scheduled` · `nightly.enabled` 지움(남아 있으면 경고만).
- 지금 안 씀: FileStorageMap 갱신 시각 — 가정한 칸 `last_modified_time`, 나중에 EDW 예시에 추가([pl-25](#pl-25)).
- 파일: `deploy/host/scripts/run_docs.py`(처리 끝난 집합), `pipeline/cli.py`(`night` — 같게 동작하는지 확인).
- 결정(사용자 10-30 PRD grill): C10 — '새 문서' 후보는 모든 입구(run_docs·night)에서 EDW `FileStorageMap`에 있고 `ParsingMeta`에 없는 것. 문서 대장은 숨김·판 관리에만 쓴다.
- Status: todo

<a id="pl-24"></a>
## pl-24 · `run_docs` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 지금은 게시가 gold를 기다리고, `cleanup_doc`이 실패해도 원본을 지운다.
- 결정(사용자 10-29 grill): 원본은 Object Storage에서 수집 서버로 받아 파싱하고, silver 게시가 성공한 뒤에만 지운다. 파싱 실패 → 원본은 남기고 원인 + 걸린 시간을 로컬에만 기록, EDW에는 아무것도 안 씀. gold 실패 → EDW 행은 남고 `gold_status` = failed(+ 이유). gold는 silver에서 다시 만들 수 있다.
- 새 EDW 칸 `AI.ParsingMeta.gold_status`(pending · ok · failed) + 이유 — DDL은 DB 담당자에게(회사 DB, Alembic 아님) — 검토 등급 A. 줄인 ParsingMeta 칸 목록은 [pl-25](#pl-25).
- `valid_env/`로 하는 로컬 시험은 문서를 먼저 임시 폴더로 복사해 거기서 돌린다(제자리에서 돌리지 않음).
- 파일: `deploy/host/scripts/run_docs.py`(`doc_flow`, `cleanup_doc`, 처리 끝난 질의), `docs/operations/parsing_meta_mssql.sql`, 게시(`parsing_meta`).
- 결정(사용자 10-30 PRD grill): C3 — 파싱이 통째로 실패하면 ParsingMeta에 쓰지 않는다(이 행 그대로). 실패는 로그·문서 대장에만 남고 다음 실행에서 다시 후보가 된다.
- Status: todo — [pl-25](#pl-25) 뒤.

<a id="rn-01"></a>
## rn-01 · 레인 정책을 표 하나로 — 담당 레인 먼저, 허용한 레인만 가져오기
- 범위: `deploy/host/scripts/run_docs.py`(서버 호스트에서 이미지 밖으로 실행 — 핑거프린트 영향 없음). 설계 [../architecture/run_docs_design.md](../architecture/run_docs_design.md), 발화 기록 [../history/run_docs_req.md](../history/run_docs_req.md).
- 사용자 10-29: "data-pipeline 하는데 3개 lane으로 해서, light/medium/vlm 구분해서 배분하고, 특정 lane은 담당, 일부 lane은 steal 허용하는 대신 우선순위는 담당 lane으로 지정. queue 관리해서 진입 시점 개수와 중간 개수 등을 관리."
- rn-01 전 러너(3레인 1/2/1·warm·MCP 멈춤): [../history/run_docs_history.md](../history/run_docs_history.md) 끝.
- 이유: 규칙이 `lane_worker()`에 하드코딩돼 있었다(light/vlm은 medium을 안 가져감, 가장 긴 다른 대기열 먼저, vlm은 `VLM_CAP` 상한) — 죽은 분기도 있고 워커 수가 상수라 조정하려면 코드를 고쳐야 했다.
- 파일: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`, `docs/architecture/run_docs_design.md`.
- 겹침: 파싱 phase 없애기([parse.md#pl-22](parse.md#pl-22), `feature/r2-phase`)는 러너에서 `PARSE_PHASES` `--set`만 뺐고 레인은 건드리지 않았다.
- 처음 계획(단계·수용 기준): [../history/run_docs_history.md](../history/run_docs_history.md) 끝.
- 끝남 10-29(사용자 grill): settings.yaml `pipeline.host.run_docs` — 레인마다 `<레인>_dedicated`(자기 레인만)와 `<레인>_shared`(자기 레인 먼저, 비면 가장 긴 다른 레인), 기본 각 1 + 1(워커 6개). `vlm_cap` 2는 전담 워커에도 적용. 배치가 끝나지 않을 설정은 시작 때 거부(`warm`이나 `vlm_cap`이 1 미만, 또는 전담·공유 워커가 하나도 없는 레인). MCP 멈춤은 medium 전담 워커를 잡아 둔다. `pick_lane()`은 순수 함수이고 표 시험이 있다. 죽은 상수는 지웠고 `--workers`는 받기만 하고 쓰지 않는다.
- Status: done

<a id="rn-02"></a>
## rn-02 · 중간 대기열 상한(파싱 끝 → 구조화 대기)과 대기열 길이 기록
- 이유: `struct_q`에 상한이 없어 구조화가 느리면 파싱 결과가 쌓인다(디스크, 대기 시간). 10-22 질문 "queue 더 쌓이면 구조화 대기가 더 오래 걸리는지"에 답할 길이 자료가 없다 — `doc_stats.jsonl`의 문서별 `queue_wait`뿐.
- 파일: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`.
- 처음 계획(단계·수용 기준): [../history/run_docs_history.md](../history/run_docs_history.md) 끝.
- 끝남 10-29(사용자 grill): `pipeline.host.run_docs.warm` 20(진입), `struct_workers` 2, `struct_backlog` 기본 = struct_workers × 2(0 = 끔). 레인 워커는 고르는 시점에서 상한을 본다(`test_struct_backlog_holds_new_parses`). `batch_progress/queue_depth.jsonl`에 dispatch / pick / parse_end / struct_put / struct_get마다 한 줄.
- Status: done

<a id="rn-03"></a>
## rn-03 · MCP `parse_document`에 CPU 먼저 주기
- 이유: 일괄 파싱이 CPU를 다 쓰면 `parse_document`(사람이 기다리는 요청)가 느려진다. 일괄 엔진 자식은 nice +10(`pipeline.extract.low_priority`, [parse.md#pl-22](parse.md#pl-22))이지만 nice는 한 세션·autogroup 안에서만 듣고, 컨테이너끼리는 cgroup CPU 가중치가 정한다(refactor.md C-65 ⑥).
- 선택지:
  1. 같은 이미지로 컨테이너를 따로 띄우고 cgroup `cpu.weight`로 나눔(허브 추천). 장점: 컨테이너끼리도 확실히 먼저, 서버에서 숫자로 조정. 단점: 컨테이너·compose·systemd 하나 더, 메모리 더, 서버 설정 일.
  2. 같은 컨테이너(`data-pipeline-parse`) 안에서 nice(지금 결정 — 사용자 10-30). 장점: 구성 변경 없음, `low_priority` 재사용. 단점: 다른 컨테이너·세션과는 안 겨룸(`sched_autogroup_enabled=1`), 효과는 서버에서 재 봐야 앎.
- 서버 확인(C-65 ⑥): 일괄 파싱만 / + `parse_document` 동시의 응답 시간 비교 — 효과 없으면 선택지 1.
- 파일: `deploy/host/compose/`, `pipeline/mcp_parse_service.py`, `common/core/resources.py`.
- Status: todo — 논의 대상(지금 2).

<a id="rn-04"></a>
## rn-04 · run_docs 작은 수정·레인 테스트
- 결정(사용자 10-30, C-59 ⓑ): MCP 감시 루프의 5초마다 `jobs_dir` 전체 `rglob`·`stat` → 최근 작업 폴더만 또는 심장 박동 파일 · 효과 없는 `--workers`를 시작 로그에서 뺌 · 남은 빈 분기 정리 · 흐름 테스트에 medium·vlm 레인·MCP 양보 길.
- 파일: `run_docs.py`, `tests/general/deploy/test_docs_flow.py`.
- Status: done (10-30, `feature/rundocs-fixes`) — ① `mcp_busy`는 이름 날짜(`<YYYYMMDD>-…`)가 어제·오늘·내일인 작업 폴더만 본다(지난 날의 끝난 작업 파일은 stat 안 함 · 하루 넘게 도는 작업은 놓침 — 작업은 분 단위) ② 안 쓰는 `PARSE_WORKERS` 지움 — `--workers`는 옛 호출이 깨지지 않게 받기만(시작 로그에는 이미 안 찍힘) ③ `lane_worker`의 빈 분기 2개는 rn-01(`pick_lane`)에서 이미 없어짐 ④ 테스트: medium·vlm 레인과 vlm 동시 상한, MCP 양보(medium 전담 워커 쉼), `mcp_busy` 표.

<a id="pl-25"></a>
## pl-25 · DB 스키마 명세 — pl-26·pl-23·pl-24를 만들기 전에 먼저
- 이유: 표·칸 정의가 Alembic 마이그레이션(`common/store/db/migrations/versions/`), `docs/operations/parsing_meta_mssql.sql`(ParsingMeta만), `AI.FileStorageMap`을 읽는 코드(정의 없음)에 흩어져 있다. 10-20 축소 스키마는 코드에 반만 반영됐다(mc-10, mc-11, pl-14, pl-15).
- 결정(사용자 10-29 grill): 문서 하나 `docs/architecture/db_schema.md` — 표마다 칸, 타입, 뜻, 어느 코드가 쓰고 읽는지. 대상: EDW `AI.FileStorageMap`(id, s3_key, original_filename, file_size, `last_modified_time` 가정), `AI.ParsingMeta`(+ `gold_status`), pgvector 검색 스키마, `struct`. 10-20 축소 스키마가 정답이고 다른 코드는 mc-10/mc-11/pl-14/pl-15에서 고친다. 시험 하나가 문서의 칸을 마이그레이션·mssql SQL과 대조한다. 구현 전에 사용자와 DB 담당자가 승인하고, DB 담당자는 이 문서를 받는다.
- 결정(사용자 10-30 grill — gold 스키마):
  - 키: 문서 키는 `s3_key` 하나. sha256 `doc_key`를 없애고 문서 대장·`doc_hidden`·`doc_contract_link`의 키를 `s3_key`로 바꾼다([mcp.md#mc-14](mcp.md#mc-14)·[mcp.md#mc-15](mcp.md#mc-15)를 풂 — `ParsingMeta.source_key`로 rep_uri 조회). 검색 `doc`에 `s3_key`가 있어야 한다 — chunk는 `doc_id`만(`s3_key`는 `doc`에만 — 10-31).
  - gold: 0.2.0에 원천 시스템별 PG 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other` — [pl-28](#pl-28), A2), 스키마마다 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat`. MCP `search`는 원천을 필수·값 하나로 받는다(G20, 계약 변경 — 등급 A). (10-30 처음 안 "지금은 표 한 벌, 나누기는 나중"은 4차 grill에서 뒤집힘.)
  - 원천 = `AI.FileStorageMap.source_system`. 비었거나 SFDC/CRMS/LAS가 아니면 → `Other`. s3_key 접두와 다르면 → 경고 기록만.
  - SFDC 전용 칸(`sf_acc_name`, `sf_op_id`, `sf_op_name`, `project_code__c`)은 `doc` 표 하나에 둔다(다른 원천은 빈 값). 나눌 때 SFDC doc 표로 옮긴다.
  - `load_run`과 Alembic 판 표는 gold에 남고, 나눈 뒤에도 공용. (10-31 고침) `chunk`에는 `source_system`도 `clients[]`도 두지 않는다 — 스키마가 원천을 정하고, 고객 거르기는 `doc.client_edw`로 문서 범위를 고른다([pl-28](#pl-28)). 청크는 `doc_id`만.
  - `AI.ParsingMeta`는 읽는 칸만 남긴다: `source_system`, `source_key`(s3_key), `parse_date`, `parse_status`, `status`, `status_at`, `rep_bucket`, `rep_key`, 새 `gold_status` + 이유([pl-24](#pl-24)). `doc_key`와 안 읽는 칸 14개는 없앤다. → 10-30 grill에서 단계별 칸을 다시 더함(아래).
  - `struct`: 문서에서 나온 표 `doc_location`, `doc_contract_link`, `doc_table`, `doc_cell`과 그 쓰기·읽기 코드(structured link/tables, `load_tables_db`, `find_table_cells`, 집계 `doc_link_list`/`table_cell_list`/`doc_location_list`, `AG.struct` 서버 길)를 지운다 — 그 내용은 청크 글에만 있다. `stack_version`/`source_version`은 남긴다(MCP 시작 때 읽음).
  - 마스터 성격 자료(용어집, 고객 명부(C-21), `contract_master`, `client_master`)는 모두 **CSV 파일**로 둔다(사용자 10-30 — grill 9~10차 "마스터 PG"를 뒤집음). 별도 마스터 Postgres도, 용어집용 SQLite도 없다. CSV(샘플 데이터)는 git `resources/vocab/glossary/`(지금 폴더)에 두어 이미지에 함께 들어간다 — 서버 폴더·마운트 없음. 파일·머리글은 `db_schema.md` §5.
  - (10-31 고침) `pipeline_version`(C-62)은 두 곳 모두에 둔다 — gold `doc.pipeline_version` = 이 행을 만든 코드 판, ParsingMeta `pipeline_version` = 이 문서를 gold에 올린 판(C9 뜻 그대로, 이름만 맞춤 — `db_schema.md`).
  - 후속 구현: `.example`을 샘플 CSV로(10-30 끝 — `client_roster`·`client_master`·`contract_master.csv`). 결정(사용자 10-30): `glossary_dir`·`client_roster`는 기본값 없는 선택 settings.yaml 키 그대로(코드 기본값 안 바꿈). PG 마스터 표·`structured load --csv-dir` 지우기는 이 행 구현·설계 검토(grill 중) 때(todo).
  - git의 CSV는 샘플 데이터(사용자 10-30) — server-guide §5 기밀 규칙과 충돌 없음.
  - EDW 벡터 표(`chunk_vec`, `edw_insert`, `edw_search`)는 PR #5가 지운다.
- 결정(사용자 10-30 — 고객 칸): 문서당 고객 하나는 EDW 조인 사슬에서 온다(값 하나). 문서 글에서 찾은 고객은 별도 목록. MCP 고객 거르기는 EDW 고객**만** 쓰고, EDW 고객이 없는 문서는 고객 거르기를 걸면 빠진다. 글에서 찾은 고객을 거르기에 쓰는 것은 나중([pl-28](#pl-28)). 지금은 둘이 `clients[]`에 섞여 있고(`build_bundle.infer_clients`) `chunk.clients`가 하드 거르기를 이끈다 — 이 행과 함께 고친다.
- 이름 규칙(사용자 10-30): EDW와 문서 파싱 양쪽에서 올 수 있는 칸은 출처를 이름에 넣어 두 칸으로 둔다(예: `client_edw`, `clients_doc`). 정확한 접미어는 `db_schema.md`가 정한다.
- 나누는 시점(사용자 10-30): 처음 B(지금은 표 한 벌) → 4차 grill에서 뒤집힘 — 0.2.0에 원천별 스키마 5벌로 만든다([pl-28](#pl-28)).
- 결정(사용자 10-30 grill 7차): `db_schema.md` U-1..U-6은 초안대로. U-7: `s3_key`당 `doc` 행 하나, `doc_alias` 없음 — `build_bundle`의 같은 파일 내용 해시 합치기(첫 키로 모음, `aliases`)를 지운다. 같은 내용이 두 키에 있으면 문서 둘(임베딩 캐시가 벡터를 재사용). D-2: EDW 고객 조인은 파이프라인이 직접 만든다 → [pl-29](#pl-29).
- 결정(사용자 10-30 grill — ParsingMeta 단계별, 성공 때만 씀 — 등급 A, DB 담당자 D-3): 위 "읽는 칸만"에 칸을 다시 더한다 — ① `stack_version`(파싱 엔진 스택 판, 엔진이 모두 실패하면 NULL) ② 성공한 엔진만(이름 + 판) ③ 문서마다 대표 silver 엔진 + 판 ④ gold 모듈·파이프라인 판(gold가 끝나기 전에는 NULL) ⑤ `gold_status`(앞의 결정 그대로) ⑥ 실패한 엔진(이름·이유·걸린 시간 — 사용자 10-30 "EDW에도"). 저장 구조는 [pl-32](#pl-32).
- 결정(사용자 10-30 grill — 검토):
  - 0.2.0에 Alembic 마이그레이션 하나로 gold 변경과 struct 지우기(마스터·문서 파생 표·`prod_master`)를 함께 — DB 담당자 승인 한 번.
  - gold `doc.file_path`는 지운다. 보여 줄 때는 `s3_key` + 새 원본 파일 이름 칸(`FileStorageMap.original_filename`에서). 고칠 곳: `mcp_server/services/search/{pgsearch,retriever,search_svc,shaping,local,aggregate}.py`, `mcp_server/schemas/evidence.py`(`search` 근거 출력의 `file_path` 키), `mcp_server/cli/ask.py`, `common/store/db/models/search_tables.py`(칸·`VIEWS_EXPECTED`·뷰 SQL), `common/store/db/schemas/search_rows.py`, 뷰 `v_chunk_source`(`common/store/db/migrations/versions/0001_search_base.py`), `pipeline/load/pgvector_load.py`·`pipeline/transform/structure/build_bundle.py`(적재가 `file_path`를 건너뛰기 키로 씀 → `s3_key`가 대신함), `validation/search_ui/serve.py`.
  - MCP `search` 근거 출력의 `file_path` 제거는 [mcp.md#mc-16](mcp.md#mc-16)에서 다룬다(사용자 10-30 PRD grill D1).
  - 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 파이프라인이 EDW에서 직접 읽는다 — [pl-29](#pl-29)의 고객 조인과 같은 자리. 외부 파일 `file_meta_new.jsonl`은 없어진다.
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
- Status: dev — `docs/architecture/db_schema.md` 설계안 + 시험 `tests/server/common/test_db_schema.py`(`feature/db-schema-spec`) — 사용자·DB 담당자 승인 대기(코드·스키마 변경 없음).

<a id="pl-32"></a>
## pl-32 · 저장 구조 — silver는 Object Storage uuid 폴더, 메타는 EDW, gold는 pgvector
- 결정(사용자 10-30 grill): 결과 저장 자리를 셋으로 정한다 — [parse.md#pl-20](parse.md#pl-20)(엔진 스택 사본 파일)을 대신함.
- silver(파싱 결과)는 Object Storage에만. PC는 `valid_env/object_storage`(file:// 대역). 문서마다 폴더 하나 — 이름은 파일 경로(`s3_key`)에서 uuid5로 만든 uuid(같은 경로 = 같은 uuid, 다시 처리하면 그 폴더를 덮어씀).
- `AI.FileStorageMap`에 같은 `s3_key` 행이 여럿이면(SFDC 판 등) 갱신·수정 시각이 가장 늦은 행만 처리. 나머지는 로컬에 "duplicate of <행>"으로 기록만, EDW에는 아무것도 안 씀.
- 메타는 EDW `AI.ParsingMeta`에 단계별로, 성공했을 때만 쓴다([pl-25](#pl-25)).
- gold는 pgvector만.
- 로컬에 남기는 것: 로그와 임베딩 캐시뿐. 문서별 작업 폴더는 지금처럼 문서가 끝나면 지운다. 지울 것: `_stack/stack-v*.json` 사본과 `STACK_SNAPSHOT`, `runs.jsonl` 재사용 저장소, `_DONE` 표시, 로컬 대장·작업 상태 파일.
- [pl-12](#pl-12)("대장은 고쳐서 남김")와 맞춤: PG `doc_registry`는 남고, 로컬 SQLite 대체만 없앤다.
- 새벽 배치 계획(사용자 10-30 "새벽 배치 계획은 parameter로 하면 될 것 같아. null 이면 새벽 배치 안하고, 입력되어있으면 작동"): settings.yaml 키 하나(op-05 — settings.yaml 하나). 값이 null이면 새벽 배치를 하지 않고, 값이 있으면 돈다([pl-23](#pl-23)).
- 실패 횟수 없앰(사용자 10-30 "fail count 는 제거하자. 그냥 현재 상태에만 성공하면 업데이트"): 재시도 횟수를 어디에도 두지 않는다 — `doc_registry.fail_count`와 `common.store.registry_retry_max`(`REGISTRY_RETRY_MAX`) 설정을 지운다(todo). ParsingMeta는 성공했을 때만 갱신.
- 실패한 엔진(사용자 10-30 "EDW에도"): 실패한 엔진(이름·이유·걸린 시간)을 로컬 로그와 EDW ParsingMeta 실패 엔진 칸에 함께 남긴다([pl-25](#pl-25), D-3).
- 구현 결정(허브 — 사용자 결정 안에서, 10-30):
  - 새벽 배치 파라미터 = 새벽 실행 시각을 담는 settings.yaml 키 하나, null이면 새벽 배치 없음. 대상 고르기 `nightly_plan()`(새 문서 + 바뀐 문서)은 그대로.
  - 실패한 문서는 성공 행이 없어 다음 실행에서 다시 시도된다. 실패 정보는 로컬 로그와 ParsingMeta 실패 엔진 칸으로.
  - `doc_registry.fail_count` 칸은 PR 3a 마이그레이션이 지운다.
  - `STACK_SNAPSHOT` 파일 → 부모가 `STACK_VERSION=N`을 넘기고 자식은 `struct.stack_version` 행을 읽는다(PC: `stack_file`), 인자 `--stack-version N`. 구현(10-30 `feature/stack-version`): `pipeline.config.stack()`·`stackcfg.resolve/current`, 호스트 `run_docs.py`는 시작 때 `stackcfg --version`으로 판 번호를 한 번 받아 파싱·구조화에 줌 · 허브 승인 예외: `--stack <파일>`은 PC 실험·시험 전용 명시 덮기로 남김(`model_matrix`는 C7로 지움 — 비교는 필요할 때 다시 만든다, [test.md#e2-10](test.md#e2-10)) — 생산 경로(run_docs·trigger·entrypoint·night/full)는 주지 않고, `--stack`과 `--stack-version`을 같이 주면 거부(종료 2 — 시험 `test_stackcfg`).
  - 레이어 핸드오프 `_DONE.json`은 남는다 — 문서마다 지우는 작업 폴더 안에 있고 FINGERPRINT도 그대로. 없애는 것은 실행을 넘어 남던 완료 표시(`run_all`, `figures_resume`, 색인 건너뛰기).
  - `runs.jsonl`: 재사용 역할만 없애고 작업 폴더 안 실행별 기록으로 남긴다.
  - 구현(10-30 `feature/no-cross-run-done`, 허브): `run_all`은 앞 실행의 `runs.jsonl`로 건너뛰거나 결과를 복사하지 않는다(이미 성공·같은 내용 복사·이전 실패·`encrypted_detected` 건너뜀과 `--force`·`--retry-failed`·`--refresh-unknown` 지움 — 같은 실행 안 같은 내용 사본은 한 번만 파싱) · `figures/figures_resume.py`와 시험 지움(pl-35 그 항목도 끝) · 남김: `pipeline.cli` `need()`(한 실행 안 모듈 사이 인계 — 문서 결과 재사용 아님) · 내용으로 열쇠를 거는 캐시는 남김: 임베딩 캐시, 색인 `index_cfg` 입력 지문(같으면 다시 안 지음).
  - 문서 고르기(10-30 허브 B — 2c): 실행을 넘어 다시 처리할 문서는 문서 대장(성공 행만)으로만 고른다 — `pipeline.cli` 파싱의 `--max-new` 고르기는 대장에 파싱 성공 행(status parsed)이 없는 문서(새 + 실패)만(앞 실행 `runs.jsonl`의 seen은 안 봄), `--source` 길은 지금처럼 `nightly_plan`. 대장을 못 열면 run_mode prod(서버)는 종료 4(전체 재파싱 안 함), 그 밖(PC·`DOC_REGISTRY=0`)은 받은 목록 그대로 + 로그 한 줄. 시험 `tests/server/pipeline/test_parse_pick.py`.
  - **알려진 빈틈(PR 4에서 고침):** 파싱 성공 행은 지금 게시(publish) 단계의 `REG.build`에서만 써진다. 마감에 걸리면 파싱이 종료 75로 바로 끝나 대표 결과·게시가 없으니 그 밤에 끝난 문서도 성공 행이 없어 다음 밤에 다시 골라진다(밤을 넘는 진행이 없음). 서버는 새벽 배치가 꺼져 있어(nightly.time 비움) 지금 운영 영향은 없음. → PR 4(ParsingMeta·대장 단계별, D-3)에 넣음: 파싱 직후(마감으로 멈춰도) 끝난 문서는 represent + `REG.build`(파싱 상태)로 성공 행을 쓰고, 그 몫의 시간을 마감 전에 남김.
  - `StandinPG`·structdb SQLite는 시험과 이미지 관문에만 — dev/prd 실행 중 조용히 대신하는 일은 없다.
- 0.2.0 구현 PR 순서(사용자 10-30, PR 1은 3a에 합침): 2a ∥ 2b → 2c → (DB 담당자 D-1~D-7) → 3a + 3b 연달아 병합 ∥ 4 → 2d → 5(SFDC 먼저, CRMS·LAS는 D-2 전까지 Other) → 6.
  - PR 4에 더할 것(#49 리뷰 10-30): ① 실패 문서 고르기 순서를 대장 `last_seen`(훑은 시각 — 실패 문서끼리 같아져 이름순이 됨) 대신 PR 4가 쓰는 마지막 시도 시각으로 ② `_registry_unparsed`의 대장 읽기는 같은 이름이 행 둘이면 마지막 행이 이김 — "한 행이라도 parsed면 성공"으로(또는 3a 뒤 s3_key당 한 행).
  - FAQ 원천 [pl-39](#pl-39)는 PR 3a 뒤(gold 칸이 필요).
  - reference 비교 행(10-30): 분류 단계 [pl-33](#pl-33)와 MCP [mc-16](mcp.md#mc-16)·[mc-17](mcp.md#mc-17)은 PR 5 뒤 — 정확한 자리는 허브가 정함. 파싱 p1 묶음 [pl-34](parse.md#pl-34)·잔재 정리 [pl-35](parse.md#pl-35)는 순서 미정(허브).
- 구조화 입력: 같은 실행 안에서는 로컬 작업 폴더를 읽고, 나중에 gold만 다시 만들 때는 Object Storage uuid 폴더에서 silver를 받는다.
- PC도 서버와 같은 흐름 — 대역만 다름(OS 폴더, EDW SQLite, PC pgvector), 따로 생기는 로컬 파일 없음.
- 파일: `pipeline/load/{publish_parse_result,parsing_meta}.py`, `pipeline/extract/run_all.py`(`runs.jsonl`·`_DONE`), `pipeline/stackcfg.py`·`pipeline/config.py`(`STACK_SNAPSHOT`), `pipeline/cli.py`(`nightly_plan`), `common/store/{registry,structdb}.py`(SQLite 대체), `deploy/host/scripts/run_docs.py`, `docs/architecture/db_schema.md`.
- (10-31 고침 — 더 새 행은 같은 doc_id·다시 파싱 안 함, 아래) 결정(사용자 10-30 PRD grill): A4 — 같은 `s3_key`의 여러 행 중 가장 늦은 행은 `FileStorageMap.created_at`이 가장 큰 행으로 고른다. PC 대역 EDW(`valid_env/edw`)의 FileStorageMap에 `created_at` 칸을 새로 만들고 값은 임의로 채운다. 실제 EDW에 이 칸이 있는지는 DB 담당자 답(D-1)으로 확인한다. 0.2.0.
- 결정(사용자 10-31 grill, A4 고침): 같은 `s3_key`의 기준은 `created_at`이 가장 늦은 `FileStorageMap` 행 그대로. 더 새 행이 오면 같은 `doc_id`를 유지하고 **다시 파싱하지 않는다**(같은 내용) — 저장된 기준·메타만 새 행으로 고친다. 밀려난 행은 새 EDW 예외 이력 표에 남긴다(어느 행이 어느 문서와 겹쳤는지, "파싱 대상 아님" — 표 이름·칸은 DB 담당자 D-9, `db_schema.md` §4).
- Status: todo — 0.2.0.

<a id="pl-33"></a>
## pl-33 · 분류 단계 — silver 뒤, gold 앞
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) C1·C3·C4·C5·C7·C8·C9, T5·T6):
  - 분류는 파이프라인 단계다 — silver 뒤, gold 적재 전에 분류하고 적재가 `doc_class`를 함께 넣는다([pl-24](#pl-24) 순서). 운영의 gold 동기화 스크립트 같은 별도 동기화는 두지 않는다.
  - 대상: SFDC(RFI/RFP/RFI+RFP/Proposal/Other), LAS(MSA/PSA/QAG/LOI/Amendment/Assignment Letter/Other)만. 다른 원천은 NULL.
  - 같은 sha256 묶음에는 라벨만 전파(LLM은 묶음당 한 번). 고객은 전파하지 않음. U-7(키가 다르면 별개 문서)은 그대로.
  - 운영 ParsingMeta의 기존 라벨(SFDC 5,647·LAS 881)은 쓰지 않는다 — 칸 구성·값 종류만 참고, 0.2.0 전체 e2e에서 새로 분류.
  - gold 분류 칸은 `doc_class` 하나([pl-25](#pl-25)).
  - LLM은 서버 내부 모델만 `llm.chat`으로 예산 장부를 거쳐(CLAUDE.md §7). 프롬프트는 `resources/prompts/pipeline/`. 라벨이 정해진 값이 아니면 NULL.
  - 원본 등록표나 Object Storage를 지우는 동작(운영 `purge_delete_targets.py` 같은 것)은 옮겨 오지 않는다.
- 파일: `pipeline/transform/structure/`(새 파일), `resources/prompts/pipeline/`(새 프롬프트), `pipeline/load/`.
- 결정(G1·G8 — 2차 grill(사용자 10-30, 원본은 git 밖); G19로 고침): `doc_class`는 시스템별 gold `doc`에만 쓴다(EDW `ParsingMeta`에는 쓰지 않음 — [pl-25](#pl-25) G19). FAQ는 분류하지 않는다([pl-39](#pl-39)).
- 결정(G10 — 3차 grill(사용자 10-30, 원본은 git 밖)): 분류에 실패한 문서(`doc_class` NULL — LLM 실패나 라벨 밖 값)는 자동으로 다시 하지 않는다. 수동 명령으로만 다시 분류한다([pl-40](#pl-40), [pl-23](#pl-23) 증분 원칙 그대로).
- 결정(사용자 10-30 PRD grill): C1 — 0.2.0. C5 — 같은 내용 묶음은 ParsingMeta `sha256`으로 찾는다.
- Status: todo — 0.2.0, 순서는 허브가 정함([pl-32](#pl-32)).

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로
- 결정(G3·G8·T15 — 2차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 이번 범위에 넣는다.
  - 질의응답 엑셀: 시트 이름 = `FAQ_group`, 행 하나 = 청크 하나(칸: type, client question, answer, last modified date). 청크 메타에 `FAQ_group`, `search` 필터로 쓸 수 있게.
  - Object Storage에 `FAQ/<uuid>/<파일>`로 올리고 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록 — 다른 원천과 같은 길로 파싱·적재(EDW 담당자 협의, DB 담당자 D-8).
  - 분류(C7)·고객 연결은 하지 않는다. `created_at`은 FileStorageMap 등록 시각.
  - PC 예제: `valid_env/object_storage/FAQ/`(지금은 로컬에만 — 이 PR에는 넣지 않음).
  - 옮겨 올 참고 코드: GitHub `gigasamba/bio_data_parsing` 브랜치 `feature/qna-dataset-embedding`의 `_qna_rows.py`·`test_qna_rows.py`.
- 파일: `pipeline/extract/`(행 단위 엑셀 처리), `pipeline/transform/structure/`(청크 메타), `mcp_server/services/search/`(필터).
- 선행: PR 3a(gold 칸) 뒤([pl-32](#pl-32)).
- Status: todo — 0.2.0.

<a id="pl-40"></a>
## pl-40 · 수동 갱신 명령 — 분류·시스템 메타를 따로
- 결정(G10·G11·G12·T17 — 3차 grill(사용자 10-30, 원본은 git 밖)): 수동 갱신 명령은 두 갈래를 **각각 따로** 고른다(한 번에 둘을 같이 고치는 길은 없음).
  - ① LLM 갈래: 분류(`doc_class`) — 기본 대상은 `doc_class`가 NULL인 문서(G10).
  - ② 시스템 메타 갈래: EDW에서 오는 고객·`sf_op_id`·`created_at` 등 — 요청하면 전체 문서(G11).
  - 재파싱·재임베딩은 하지 않는다. 시스템별 gold `doc` 칸만 UPDATE한다(G19 — 파일 메타는 ParsingMeta에 없음).
- 관련: [pl-33](#pl-33)(분류), [pl-29](#pl-29)(고객 연결), [pl-25](#pl-25)(칸).
- Status: todo

<a id="pl-41"></a>
## pl-41 · FAQ 다시 올리기 — 행 단위 비교 적재
- 결정(G13·T18 — 3차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 고쳐 새 `s3_key`로 올리면 기존 FAQ 청크와 **행(청크) 단위로** 비교한다.
  - 같은 항목 = `FAQ_group`과 질문 글이 같음.
  - 가장 최신 답만 남긴다 — `last modified date`, 없으면 새 파일. 예전 행은 gold에서 지우고 새 행을 더한다. 같은 질문이 없는 새 행은 더한다.
  - [pl-13](#pl-13)("적재는 지우지 않음")의 **FAQ 한정 예외** — 검토 등급 A(서버 적재 동작).
- 관련: [pl-39](#pl-39)(FAQ 원천).
- 결정(사용자 10-30 PRD grill): A7 — FAQ를 다시 올려 청크가 0개가 된 옛 `doc` 행은 적재 때 지운다(pl-13 '적재는 지우지 않음'의 FAQ 예외).
- Status: todo

<a id="pl-28"></a>
## pl-28 · 원천 시스템별 gold 스키마 — 0.2.0에 만든다
- 이유: SFDC · CRMS · LAS · FAQ · Other는 메타데이터가 다르다. 원천마다 표 하나면 칸이 깔끔하다.
- 무엇(사용자 10-30): gold 표 묶음 — `doc`, `chunk`, BM25 표(`chunk_term`, `term_stat`, `corpus_stat`) — 이 원천마다 한 벌씩(5벌 — A2 아래). 원천마다 칸이 다를 수 있다(SFDC 전용 `sf_*`, `project_code__c`는 SFDC doc 표로). `load_run`과 Alembic 판 표는 공용. 그때 MCP `search`가 원천을 필수로 받는다 — 계약 변경 한 번, 새 판, 검토 등급 A. 또 나중에: 글에서 찾은 고객(`clients_doc`)도 고객 거르기에 허용.
- 결정(4차 grill(사용자 10-30) — 위 "나중"을 뒤집음, 0.2.0에 만든다 — 지금 코드가 0.1.0):
  - 나누는 방식: 원천 시스템마다 **PG 스키마 하나**(5벌 `sfdc`·`crms`·`las`·`faq`·`other` — A2 아래). 스키마마다 같은 표 구성 `doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat` + 그 시스템 전용 메타 칸. BM25 통계도 시스템별. Alembic은 한 모델을 스키마마다 적용한다. `load_run`과 Alembic 판 표는 공용.
  - 파일 메타(고객 `client_edw`, `sf_*`, `doc_class`, `created_at`, `contract_id` 등)는 **`doc`에만** 둔다. `chunk`는 `doc_id`만 갖고(`s3_key`는 `doc`에만 — 10-31) 메타를 복사하지 않는다(예외: `faq` 스키마만 `chunk.faq_group` — C4 아래). `doc` 표는 문서 단위 조회(`list_doc_fulltext`, 수동 갱신 [pl-40](#pl-40))에 쓰이므로 남긴다.
  - 거르기: 먼저 `doc`에서 문서 범위를 고르고 그 안의 `chunk`만 찾는다(지금 "저장소 단계 범위 제한"과 같은 방식). 메타 갱신은 `doc` 행 UPDATE 한 번으로 끝난다(chunk 값이 어긋날 일 없음).
  - MCP: `source_system`이 **필수, 값 하나** — 그 시스템 스키마만 찾는다. 여러 시스템은 클라이언트가 여러 번 부른다(시스템별 BM25 통계라 점수를 섞지 않음). [mcp.md#mc-16](mcp.md#mc-16), [mcp.md#mc-17](mcp.md#mc-17). 계약 변경 — 등급 A, 0.2.0에 함께(지금 코드가 0.1.0이므로 G7의 "0.1.0에 함께" 대신).
  - 위 `chunk`의 `source_system`·`clients[]` 유지([pl-25](#pl-25))는 스키마가 원천을 정하므로 필요 없어진다 — `db_schema.md`를 이에 맞게 고친다.
- 결정(사용자 10-30 PRD grill): C2 — MCP 계약이 바뀌어도 0.2.0(버전 규칙에 '1.0 전에는 MINOR에서도 계약·스키마를 깰 수 있음'을 더함 — 운영이 안정되면 1.0.0). C4 — 원천 스키마마다 칸 구조가 다를 수 있다: `faq` 스키마만 `chunk`에 `faq_group` 칸을 두고, 다른 원천은 '파일 메타는 `doc`에만' 그대로. A2 — 스키마 5벌(`sfdc`·`crms`·`las`·`faq`·`other`), MCP `source_system`은 `other`도 받는다.
- 결정(사용자 10-31 grill): `chunk_key` = `<doc_id>:<seq>`(gold `doc.doc_id` 자동 번호), 청크는 `doc_id`만(FK). 스키마 5벌이 **시퀀스 하나를 함께 써서** `doc_id`가 겹치지 않는다 — 이 부분은 허브가 정함(사용자 확인 필요). 적재는 `s3_key`로 upsert해 `doc_id`가 바뀌지 않는다. `doc.source_system`도 지운다. 원천 id 칸은 스키마마다 EDW 원본 칸 이름.
- Status: todo — 0.2.0, 전체 다시 적재 필요. 설계 반영(`db_schema.md`)과 DB 담당자 협의 먼저(등급 A).

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작(ID 있는 행은 열린 결함, 나머지는 알아 둘 동작)
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 문서 대장 upsert, 게시 가드 | upsert에 PG 문법 오류, 가드 꺼짐(서버에 `source.json` 없음) | `structdb.py`, `publish_parse_result.py` | pl-12 |
| `--prune`은 옛 행만 지움 | 건너뛴(안 바뀐) 문서도 지움 | `pgvector_load.py` | pl-13 |
| `pipeline structure/load` 모듈이 새 묶음을 받음 | 계약 `DOC_KEYS`가 거부(서버는 이 모듈을 안 씀) | `common/core/contract.py` | pl-15 |
| 임베딩 없이 구조화 | `PIPE_EMBED=none` → `vector(0)` 표 실패 | `build_bundle.py`, `pgvector_load.py` | pl-16 |
| 중간에 멈추면 보임 | 중간에 멈춰도 `night`/`full` 종료 코드 0 | `pipeline/cli.py`, `entrypoint.sh` | pl-18 |
| compose `index_a`/`index_b`가 끝까지 돎 | 실패 | `deploy/host/` | pl-19 |
| 적재는 안 바뀐 문서만 건너뜀 | `file_path`로 건너뜀(sha 칸 없음) — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀 | `pgvector_load.py` | pl-07 |
| 지식 그래프 검색 가능 | 묶음에는 만들지만 PG에 적재하지 않고 지금 읽는 검색 방법도 없음 | `build_bundle.py` | pl-06 |

### 요건 없는 코드 — 남길지(앵커를 씀) 지울지([test.md#e2-18](test.md#e2-18))
- 메일 첨부: `.eml`/`.msg` 첨부를 재귀 파싱(깊이 1, 20 MB, 10개)하고 인용 스레드 접기(`ATTACH_*`). `represent/attachments.py`.
- 스트리밍 파싱 — 작은 묶음을 받아 파싱하고 원본을 바로 지움(`PARSE_STREAM=0` — 켜는 곳 없음, run_docs는 안 씀). `pipeline/stream.py`.
- 용어집·위키 도구(개념 위키, LLM 용어집 초안, 약어 제안, EDW 마스터로 만드는 고객 목록). `transform/structure/wiki.py`, `wiki_draft.py`, `glossary_suggest.py`, `gen_roster.py`.
- 밤 호스트 타이머와 trigger 연결(`NIGHTLY_*`, `CHAIN_STRUCTURE_URL`). `deploy/host/`, `pipeline/trigger_server.py`.
- Object Storage 시험 업로드(MinIO). `common/check/os_put.py`.
- 공용 도구 — 설정 CLI `common/config/`, DB 도구 `common/store/db/`, 점검 `pipeline/check_env.py`, `common/check/`.

### 기본 꺼짐·설정 필요
전체 스위치와 기본값: `settings.sample.yaml` 2부, "[기능 켬/끔]" 묶음.

| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 스트리밍 파싱 | `PARSE_STREAM=0` | — (문서별 병렬 파이프라인 `PARSE_PARALLEL_PIPELINE`은 10-30 지움 — pl-35) |
| 큰 표를 행으로 나누기 | `CHUNK_TABLE` 비움(표는 통째) | — |
| LLM 요약 | `EDW_SUMMARY_LLM=0`(앞부분) | LLM |
| 임베딩 | 이미지 기본 `PIPE_EMBED=api` | `EMBED_BASE_URL`, `EMBED_MODEL` |
| Object Storage + `AI.ParsingMeta` 게시 | `night`, run_docs, 이미지 `publish` 단계에서 기본 실행(모두 `--apply`, `NIGHTLY_PUBLISH=1`) | `PM_BUCKET`, `common.connections.rdb` 쓰기 계정(`PM_BUCKET` 없으면 종료) |
| 밤 일정 | `NIGHTLY_TIME` 비움 | 시각(HH:MM) |
| `--prune`, `vector` 확장 만들기 | 선택 · `PG_CREATE_EXTENSION=0` | — |
| trigger 서버 | — | `TRIGGER_TOKEN`(없으면 시작 거부) |

10-29 요청 "EDW와 Object Storage 적재를 기본으로 켬": 게시(Object Storage + `AI.ParsingMeta`)는 `PM_BUCKET`과 EDW 쓰기 계정만 있으면 이미 기본으로 돈다. 꺼져 있는 것은 밤 일정(`NIGHTLY_TIME` 비움 — 10-30 pl-32, 켤 때 시각을 적음). EDW 벡터 적재는 10-29에 지웠다(벡터는 pgvector에만 — [settings.md#op-03](settings.md#op-03)).
