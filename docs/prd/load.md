# 적재 — pgvector·게시·저장 구조

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md) 다음: pgvector 적재(pl-07·pl-13·pl-14·pl-16·pl-19) → 게시(silver — pl-09·pl-26) → FAQ 다시 올리기(pl-41) → 지운 정형 DB·문서 대장(pl-08·pl-12)·마스터 CSV(pl-38) → 저장 구조(pl-32). DB 스키마는 [load-schema.md](load-schema.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-07 · pl-13 · pl-14 · pl-16 · pl-19 · pl-09 · pl-26 · pl-41 · pl-40 · pl-08 · pl-12 · pl-38 · pl-32.

<a id="pl-07"></a>
## pl-07 · pgvector 적재
- 이유: 검색 서버는 PG를 읽는다.
- 무엇: 표 `load_run`·`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + 뷰 `v_chunk_source`(Alembic으로만). 이미 적재된 문서는 `file_path`로 건너뛴다(sha 열 없음 — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀). (`--prune`은 10-30에 없앰 — [pl-13](#pl-13).) 이름 붙은 색인(`index_id`). 벡터는 pgvector에만 둔다(EDW 벡터 적재는 10-29에 지움 — [ops.md#op-03](ops.md#op-03)).
- 파일: `pipeline/load/pgvector_load.py`, `common/store/db/migrations/`.
- 결정(허브 10-31, 최신 결정 우선): 이름 붙은 색인(`index_id`)은 0.2.0에 없앤다 — 원천(`source_system`)이 gold 스키마를 고르므로 색인 이름이 필요 없다(선택지 줄이기 원칙). 구현은 [pl-28](load-schema.md#pl-28)과 함께.
- 결정(사용자 10-31): PG 자동 찾기(`docker ps` pgvector·대체 포트·코드 기본 `127.0.0.1`/`5432`/`rag`)를 없애고 PG 접속은 필수 — [ops-ops-settings.md#op-09](ops-ops-settings.md#op-09).
- Status: done

<a id="pl-13"></a>
## pl-13 · `load --prune`이 건너뛴 문서까지 지움
- 이유: 바뀌지 않아 건너뛴 문서도 지워진다(C-60).
- 파일: `pipeline/load/pgvector_load.py`.
- 결정(사용자 10-29 grill): 적재는 더하고 고치기만 하고 지우지 않는다. 건너뛴(이미 있는) 문서는 남는다. 원천에서 지워진 문서와 파싱 실패는 로컬에 기록만(원인 + 걸린 시간), 자동 삭제 없음. `load`와 그 호출부(`pipeline/cli.py` load, 색인 빌드 `--pg`)에서 prune 길을 없앤다.
- 결정(사용자 10-30 PRD grill): S1 — 브랜치가 병합됐으므로 done으로 닫는다(남은 서버 확인은 refactor.md C 항목으로).
- 한 것(10-30 병합, #17): `feature/load-no-prune`: `prune`·`--prune`·`PRUNE_*` 설정 없앰(옛 설정 칸은 경고만), `cli load`·`run-stack`·색인 빌드 `--pg`가 더는 안 붙임, `--no-prune`은 옛 호출 호환으로 받기만, 색인 빌드 `--pg`는 `--replace`로(다시 빌드 때 고침). 남은 한계: `file_path`가 바뀐 같은 내용은 옛 행이 남음(사람이 지움 — 사용자 확인). 시험 `tests/server/pipeline/test_pl13_no_prune.py`. 검토 등급 A(서버 적재 동작).
- 11-02(pl-28, 리뷰 #86): 원천 스키마 5벌을 함께 본다 — 적재는 묶음 문서의 원본 경로(`file_path`)를 5벌 모두에서 찾는다. `--replace` 없이 어느 스키마에든 이미 있으면 건너뛴다(두 스키마에 같은 문서가 생기지 않게). `--replace`면 다른 원천 스키마에 남은 옛 사본을 먼저 지우고(키워드 색인·문서 빈도·그 스키마 `corpus_stat` 포함, 실 PG는 같은 트랜잭션) 새 원천 스키마에 넣는다 — 원천(`source_system`)이 바뀐 문서가 옮겨 간다. 시험: `test_pl13_no_prune`.
- Status: done — 남은 서버 확인은 refactor.md C-68.

<a id="pl-14"></a>
## pl-14 · 배포 backfill이 지운 `doc.client`를 읽음
- 이유: 10-20 축소 스키마 뒤 `pgvector_load deploy`의 `backfill_chunk_clients`가 실패한다(표와 색인은 그래도 만들어짐).
- 파일: `pipeline/load/pgvector_load.py`.
- 11-02(pl-28): `chunk.clients`·`doc.clients`와 backfill(`backfill_chunk_clients`)·그 시험을 지웠다 — 고객은 `client_edw` 거르기만(C6).
- Status: done (10-30) · 11-02 backfill 길 지움(pl-28)

<a id="pl-16"></a>
## pl-16 · `PIPE_EMBED=none`이면 `vector(0)`을 만든다
- 이유: 차원 0으로는 표를 만들 수 없어 임베딩 없는 구조화가 실패한다.
- 파일: `pipeline/transform/structure/build_bundle.py`, `pipeline/load/pgvector_load.py`.
- 결정(사용자 10-30 PRD grill): A6 — `PIPE_EMBED=none`(임베딩 없음)은 적재 시작 때 거부한다(검색에 벡터가 필수). 0.2.0.
- Status: todo

<a id="pl-19"></a>
## pl-19 · compose `index_a`/`index_b`가 끝까지 돌면 실패
- 이유: C-32.
- 결정(사용자 10-30 grill): compose `index_a`/`index_b` 예시를 지운다.
- 파일: `deploy/host/`.
- 11-01(`feature/mcp-ops-parity`, mc-16): 이름 있는 색인(AD41)을 통째로 지우며 `compose.index.yml`·`pipeline/load/index.py`·`index_cfg.py`도 지웠다.
- Status: done

<a id="pl-09"></a>
## pl-09 · 파싱 결과 게시
- 이유: 다른 팀은 결과를 Object Storage + `AI.ParsingMeta`에서 읽는다.
- 무엇: 대표 `.md` + 원결과(원본은 절대 아님)를 Object Storage에 올리고, `AI.ParsingMeta`에 INSERT만 한다. 원본 버킷으로 게시는 거부, DRM·실패 문서는 제외 보고서로.
- 파일: `pipeline/load/publish_parse_result.py`, `pipeline/load/parsing_meta.py`, `docs/operations/parsing_meta_mssql.sql`.
- Status: done

<a id="pl-26"></a>
## pl-26 · `full`은 늘 게시하고 게시 대상은 필수
- 결정(사용자 10-31 범위 축소 grill): run_docs 하나로 합침(pl-18 결정) — 규칙(C10 고르기·종료 코드·항상 게시)은 run_docs에만 만든다.
- 이유: 도움말은 "EDW 적재 없음"이라 했지만 `full`은 게시했고 `NIGHTLY_PUBLISH`를 무시했다(C-31).
- 결정(사용자 10-29 grill): 게시(silver → Object Storage + EDW)가 기본이자 유일한 방식 — `--no-publish`와 `pipeline.host.nightly.publish`를 없앤다. 게시 대상은 필수 설정이고 없으면 시작을 거부한다.
- `RUN_ENV`별 대상: `local`·`dev`는 (a) 로컬 경로(Object Storage는 폴더, EDW는 파일 DB) 또는 (b) 실제 접속 정보(API·DB) 중 하나. `prd`는 실제 접속만(`stage`는 RUN_ENV에서 없앰 — op-02). PC는 CLAUDE.md §4 가드를 그대로 지킨다(PC에서 운영 EDW·OS 접속 금지).
- 파일: `pipeline/cli.py`(`night`, `full`), `deploy/docker/entrypoint.sh`, `pipeline/load/`의 게시, `pipeline/config.py`, `docs/operations/server-guide.md`.
- Status: todo — 11-01 `full`·`night` 입구는 지움([pl-18](ops.md#pl-18)) — 항상 게시·게시 대상 필수는 run_docs에 만든다.

<a id="pl-41"></a>
## pl-41 · FAQ 다시 올리기 — 행 단위 비교 적재
- 결정(사용자 10-31 범위 축소 grill): 행 단위 비교 대신 **통째 교체** — FAQ 파일을 다시 올리면 그 FAQ 문서의 청크를 지우고 다시 적재.
- 결정(G13·T18 — 3차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 고쳐 새 `s3_key`로 올리면 기존 FAQ 청크와 **행(청크) 단위로** 비교한다.
  - 같은 항목 = `FAQ_group`과 질문 글이 같음.
  - 가장 최신 답만 남긴다 — `last modified date`, 없으면 새 파일. 예전 행은 gold에서 지우고 새 행을 더한다. 같은 질문이 없는 새 행은 더한다.
  - [pl-13](#pl-13)("적재는 지우지 않음")의 **FAQ 한정 예외** — 검토 등급 A(서버 적재 동작).
- 관련: [pl-39](extract.md#pl-39)(FAQ 원천).
- 결정(사용자 10-30 PRD grill): A7 — FAQ를 다시 올려 청크가 0개가 된 옛 `doc` 행은 적재 때 지운다(pl-13 '적재는 지우지 않음'의 FAQ 예외).
- Status: todo

<a id="pl-40"></a>
## pl-40 · 수동 갱신 명령 — 분류·시스템 메타를 따로
- 결정(사용자 10-31 범위 축소 grill): 수동 갱신 명령 2개를 **만들지 않는다** — load --replace나 다시 실행으로 대신.
- 결정(G10·G11·G12·T17 — 3차 grill(사용자 10-30, 원본은 git 밖)): 수동 갱신 명령은 두 갈래를 **각각 따로** 고른다(한 번에 둘을 같이 고치는 길은 없음).
  - ① LLM 갈래: 분류(`doc_class`) — 기본 대상은 `doc_class`가 NULL인 문서(G10).
  - ② 시스템 메타 갈래: EDW에서 오는 고객·`sf_op_id`·`created_at` 등 — 요청하면 전체 문서(G11).
  - 재파싱·재임베딩은 하지 않는다. 시스템별 gold `doc` 칸만 UPDATE한다(G19 — 파일 메타는 ParsingMeta에 없음).
- 관련: [pl-33](transform.md#pl-33)(분류), [pl-29](extract.md#pl-29)(고객 연결), [pl-25](load-schema.md#pl-25)(칸).
- Status: dropped (사용자 10-31 범위 축소)

<a id="pl-08"></a>
## pl-08 · 정형 DB와 문서 대장
- 결정(사용자 10-31 범위 축소 grill): 정형 DB 파생 표·마스터 표(contract/client/prod master, doc_contract_link, doc_location, doc_table, doc_cell)와 적재 코드를 **지금 지운다**(mc-04와 함께). 마스터는 따로 둔 마스터 DB로 옮김(pl-38).
- 이유: 계약·고객·문서 판이 정형 질문에 답하고 증분 실행을 이끈다.
- 무엇: `contract_master`·`client_master`·`prod_master`·`doc_contract_link`(점수 매기는 연결기)·`doc_location`·`doc_registry`·`doc_hidden`·`doc_table`·`doc_cell`. PG 또는 SQLite.
- 결정(사용자 11-01 — D-031): struct 스키마를 코드에서 모두 없앰, 파일만 — 서버에 남은 쓰이지 않는 struct 스키마는 그대로 두거나 DB 담당자가 지움, 코드는 읽지 않음. 근거: 서버의 struct 스키마는 있지만 쓰이지 않음(`doc_registry` 0행), 운영 코드에서 `stack_version`·`source_version`을 쓴 곳 없음.
- 파일: (지움) `pipeline/load/structured.py`, `common/store/structdb.py`, struct Alembic 갈래(`0001_struct_base`·`0002_struct_config`·`0003_struct_drop`), `common/store/db/models/struct_tables.py`·`schemas/struct_rows.py`·`cfgtables.py`, `resources/sql/0002_*_seed.json` · (새로) `common/store/db/cfgfile.py`(파일 읽기 + 모양 검사).
- 결정(허브 10-31, 최신 결정 우선): 지울 표 저장소(`doc_table`·`doc_cell` — [pl-25](load-schema.md#pl-25) `struct`)를 읽는 검색 쪽 코드는 죽은 코드다 — `mcp_server/services/search/aggregate.py`의 `table_cell_list`·`find_table_cells`·`struct()`, `common/store/structdb.py:406`. 0.2.0에 표를 지우는 마이그레이션과 함께 지운다.
- 한 것(11-01 — 사용자 10-31 결정): 위 표 10개(+ `doc_registry_seen`)와 그 코드를 지웠다 — 연결기·CSV 적재(`structured.py`), 연결·SQLite 대체(`structdb.py`), 설정 `common.store.struct_backend`·`struct_db`(경고만).
- 한 것(11-01 — 사용자 11-01 결정): struct 스키마를 코드에서 모두 없앴다 — Alembic struct 갈래·표 정의·시드 지움, `dbtool`/`migrate --target`은 `search`·`all`만. 엔진 구성은 서버(dev·prd)·PC 모두 파일 `resources/config/pipeline_stack.json`(`ops.paths.stack_file`)을 `cfgfile`로 읽고 모양을 검사한다(못 읽거나 틀리면 시작 때 종료 2). 바꾸기 = 파일을 고쳐 오버레이 패치, 되돌리기 = git. `set-stack`·`set-sources` 명령과 내부 칸 `STACK_VERSION`·`--stack-version`을 지웠고(`show-stack`은 파일을 보여 줌 · 원천 목록 `sources.json`·`show-sources`는 11-01 뒤 결정으로 지움 — [pl-01](extract.md#pl-01)), `run_docs.py`는 시작 때 `show-stack`으로 확인만 한다. 파싱·검색 MCP 컨테이너는 PG 없이 시작한다(PG는 적재·검색에만). 설명은 [pipeline_stack.md](../architecture/pipeline_stack.md).
- Status: done

<a id="pl-12"></a>
## pl-12 · 문서 대장 upsert와 게시 가드
- 결정(사용자 10-31 범위 축소 grill): 문서 대장(doc_registry)·숨김(doc_hidden)·숨김 명령을 **모두 지운다**(hidden 열도 두지 않음). 빼야 할 문서는 원천에서 지우거나 사람이 SQL로. ① PG upsert 번역 문제는 대장과 함께 닫힘.
- 이유: 문서 대장 upsert에 PG 문법 오류가 있다(C-54 ①). 서버가 `source.json`을 올리지 않아 게시 가드가 꺼져 있다(C-54 ②).
- 파일: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `tests/server/pipeline/test_publish_guard.py`(알려진 실패).
- 결정(사용자 10-30 grill):
  - ① 문서 대장은 남기고 고친다 — `INSERT OR REPLACE`의 PG 번역(`structdb._pg_sql` 정규식 ↔ `registry.apply`의 여러 줄 SQL). [pl-25](load-schema.md#pl-25)와 함께 키를 `s3_key`로 바꾼다. 새 문서 판별은 FileStorageMap ↔ ParsingMeta 그대로([pl-23](ops.md#pl-23)).
  - ② 게시 가드는 `source.json` 사이드카 대신 EDW `AI.ParsingMeta`(`source_key` + `rep_bucket`/`rep_key`)를 읽는다. 같은 문서 → 같은 파일에 덮어씀(`-2`/`-3.md` 사본 없음). 다른 원천이 같은 결과 키로 오면 → 거부. 그러면 `test_publish_guard`가 통과 → `deploy/release/known_fail.txt`에서 뺀다.
- 결정(사용자 10-30 grill 12~13차): 원천에서 사라진 문서(deleted) 처리 길은 통째로 없앤다 — 지우기·숨기기·EDW `deleted` 표시 모두 없음, 로컬 기록만(refactor.md C-54).
- 10-30 [pl-32](#pl-32): PG `doc_registry`는 남고 로컬 SQLite 대체는 없앤다. 실패 횟수(`fail_count`)·재시도 설정(`registry_retry_max`)은 없앤다 — 성공했을 때만 갱신(사용자 10-30).
- 한 것(10-30, B1 — 개발 서버 반입 전 검토): deleted 길 없앰 — `registry.apply`가 관측에 없는 문서에 `status='deleted'`·자동 숨김을 쓰지 않고, `parsing_meta.apply_registry_status`가 EDW에 `deleted`를 쓰지 않는다(`diff["deleted"]`는 판 잇기 정보로만). 서버(dev·prd)는 SQLite·PG 스탠드인으로 대체하지 않고 멈춘다(`structdb.open_backend` — `run_mode: prod`·`struct_backend` pg/tsql 필수, `pg._warn_standin`). `common.store.run_mode`는 `prod`·`test`만. 시험 `tests/server/common/test_no_deleted.py`. code_fp p0·p1·r·s 바뀜(공용 `settings.py`·`pg.py`·`structdb.py`).
- 한 것(11-01 `feature/scope-cut-search`): `common/store/registry.py`·`registry_cli`·검색 `registry.py`·숨김 거르기(retriever·pgsearch)·게시의 대장 상태 갱신·ParsingMeta 상태 갱신 길 지움. 표는 struct 스키마와 함께 코드에서 없앰([pl-08](#pl-08)). 설정 `common.store.doc_registry`·`registry_etag_md5` 지움(남으면 경고).
- 11-02 C10 예외(사용자): ParsingMeta `loaded_at` 한 칸만 적재 때 UPDATE(`parsing_meta_db.mark_loaded`) — 다른 칸은 그대로 INSERT만(`test_no_deleted`가 UPDATE는 `SET loaded_at`뿐인지 본다).
- Status: done (11-01 `feature/scope-cut-search`)

<a id="pl-38"></a>
## pl-38 · 마스터 CSV 활용 방안 설계(후순위)
- 결정(사용자 10-31 범위 축소 grill): 마스터는 **모두 별도 RDB로 관리**. 지금은 마스터용 SQLite 하나를 만들어 마스터 CSV를 모두 그리로 옮긴다 — 나중 logging 자리와 같은 DB. 명부 생성·용어 제안 도구는 그 DB를 읽게 바꾸거나 지움(구현 때).
- 결정(사용자 10-30): "contract_master, client_master 등 활용하는 방안 같이 설계하자. 후순위로 해줘."
- 사실: PR 3a 뒤에는 `resources/vocab/glossary/contract_master.csv`·`client_master.csv`를 읽는 코드가 없다. `client_master.example.csv`는 `gen_roster` 입력. 두 파일은 설계가 끝날 때까지 git에 남긴다 — 3a에서 지우지 않는다.
- 열린 질문: 마스터마다 무엇에 쓰나(검색 거르기 / 분류 단서 / mc-05의 고객 별칭 그룹), EDW 고객 연결([pl-29](extract.md#pl-29))·분류 단계([pl-33](transform.md#pl-33))와 어떻게 이어지나.
- 결정(허브 10-31, 최신 결정 우선): 고객 별칭 CSV 몫(고객 명부·별칭 그룹 — [mcp.md#mc-05](mcp.md#mc-05))은 0.2.0으로 당긴다 — struct 마스터 표를 지우기 전에 CSV로 읽을 수 있어야 한다. 나머지 활용 설계는 후순위 그대로.
- Status: todo — 고객 별칭 CSV 몫은 0.2.0, 나머지는 후순위(사용자와 grill).

<a id="pl-32"></a>
## pl-32 · 저장 구조 — silver는 Object Storage uuid 폴더, 메타는 EDW, gold는 pgvector
- 결정(사용자 10-31 범위 축소 grill): 같은 s3_key 최신 행만 남김(기존) — 구판 표시는 쓰지 않음(mc-05). 대체된 행은 SupersededRow(pl-25 계획대로).
- 결정(사용자 10-30 grill): 결과 저장 자리를 셋으로 정한다 — [transform.md#pl-20](transform.md#pl-20)(엔진 스택 사본 파일)을 대신함.
- silver(파싱 결과)는 Object Storage에만. PC는 `valid_env/object_storage`(file:// 대역). 문서마다 폴더 하나 — 이름은 파일 경로(`s3_key`)에서 uuid5로 만든 uuid(같은 경로 = 같은 uuid, 다시 처리하면 그 폴더를 덮어씀).
- `AI.FileStorageMap`에 같은 `s3_key` 행이 여럿이면(SFDC 판 등) 갱신·수정 시각이 가장 늦은 행만 처리. (허브 10-31 고침 — 아래) 나머지는 로컬에 "duplicate of <행>"으로 기록만, EDW에는 아무것도 안 씀.
- 결정(허브 10-31, 최신 결정 우선): 밀려난 `FileStorageMap` 행은 로컬 기록이 아니라 EDW 예외 이력 표에 남긴다(D-9, `db_schema.md` §4 `edw.SupersededRow`, PR #70).
- 메타는 EDW `AI.ParsingMeta`에 단계별로, 성공했을 때만 쓴다([pl-25](load-schema.md#pl-25)).
- gold는 pgvector만.
- 로컬에 남기는 것: 로그와 임베딩 캐시뿐. 문서별 작업 폴더는 지금처럼 문서가 끝나면 지운다. 지울 것: `_stack/stack-v*.json` 사본과 `STACK_SNAPSHOT`, `runs.jsonl` 재사용 저장소, `_DONE` 표시, 로컬 대장·작업 상태 파일.
- [pl-12](#pl-12)("대장은 고쳐서 남김")와 맞춤: PG `doc_registry`는 남고, 로컬 SQLite 대체만 없앤다.
- 새벽 배치 계획(사용자 10-30 "새벽 배치 계획은 parameter로 하면 될 것 같아. null 이면 새벽 배치 안하고, 입력되어있으면 작동"): settings.yaml 키 하나(op-05 — settings.yaml 하나). 값이 null이면 새벽 배치를 하지 않고, 값이 있으면 돈다([pl-23](ops.md#pl-23)).
- 실패 횟수 없앰(사용자 10-30 "fail count 는 제거하자. 그냥 현재 상태에만 성공하면 업데이트"): 재시도 횟수를 어디에도 두지 않는다 — `doc_registry.fail_count`와 `common.store.registry_retry_max`(`REGISTRY_RETRY_MAX`) 설정을 지운다(todo). ParsingMeta는 성공했을 때만 갱신.
- 실패한 엔진(사용자 10-30 "EDW에도"): 실패한 엔진(이름·이유·걸린 시간)을 로컬 로그와 EDW ParsingMeta 실패 엔진 칸에 함께 남긴다([pl-25](load-schema.md#pl-25), D-3).
- 구현 결정(허브 — 사용자 결정 안에서, 10-30):
  - 새벽 배치 파라미터 = 새벽 실행 시각을 담는 settings.yaml 키 하나, null이면 새벽 배치 없음. (허브 10-31 고침 — C10, 아래) 대상 고르기 `nightly_plan()`(새 문서 + 바뀐 문서)은 그대로.
  - 실패한 문서는 성공 행이 없어 다음 실행에서 다시 시도된다. 실패 정보는 로컬 로그와 ParsingMeta 실패 엔진 칸으로.
  - `doc_registry.fail_count` 칸은 PR 3a 마이그레이션이 지운다.
  - `STACK_SNAPSHOT` 사본 파일은 없앴다. (11-01 고침 — [pl-08](#pl-08)) 엔진 구성은 서버·PC 같은 파일 하나라 판 번호를 넘기지 않는다 — 진입점이 `stackcfg.resolve()`로 검사하고 층은 `pipeline.config.stack()`으로 같은 파일을 읽음, 호스트 `run_docs.py`는 시작 때 `show-stack`으로 확인만. `--stack <파일>`은 PC 실험·시험 전용 명시 덮기로 남김(`model_matrix`는 C7로 지움 — [test.md#e2-10](test.md#e2-10)) — 생산 경로(run_docs·trigger·entrypoint·night/full)는 주지 않는다.
  - 레이어 핸드오프 `_DONE.json`은 남는다 — 문서마다 지우는 작업 폴더 안에 있고 FINGERPRINT도 그대로. 없애는 것은 실행을 넘어 남던 완료 표시(`run_all`, `figures_resume`, 색인 건너뛰기).
  - `runs.jsonl`: 재사용 역할만 없애고 작업 폴더 안 실행별 기록으로 남긴다.
  - 구현(10-30 `feature/no-cross-run-done`, 허브): `run_all`은 앞 실행의 `runs.jsonl`로 건너뛰거나 결과를 복사하지 않는다(이미 성공·같은 내용 복사·이전 실패·`encrypted_detected` 건너뜀과 `--force`·`--retry-failed`·`--refresh-unknown` 지움 — 같은 실행 안 같은 내용 사본은 한 번만 파싱) · `figures/figures_resume.py`와 시험 지움(pl-35 그 항목도 끝) · 남김: `pipeline.cli` `need()`(한 실행 안 모듈 사이 인계 — 문서 결과 재사용 아님) · 내용으로 열쇠를 거는 캐시는 남김: 임베딩 캐시, 색인 `index_cfg` 입력 지문(같으면 다시 안 지음).
  - (허브 10-31 고침 — C10, 아래) 문서 고르기(10-30 허브 B — 2c): 실행을 넘어 다시 처리할 문서는 문서 대장(성공 행만)으로만 고른다 — `pipeline.cli` 파싱의 `--max-new` 고르기는 대장에 파싱 성공 행(status parsed)이 없는 문서(새 + 실패)만(앞 실행 `runs.jsonl`의 seen은 안 봄), `--source` 길은 지금처럼 `nightly_plan`. 대장을 못 열면 run_mode prod(서버)는 종료 4(전체 재파싱 안 함), 그 밖(PC·`DOC_REGISTRY=0`)은 받은 목록 그대로 + 로그 한 줄. 시험 `tests/server/pipeline/test_parse_pick.py`.
  - **알려진 빈틈(PR 4에서 고침):** 파싱 성공 행은 지금 게시(publish) 단계의 `REG.build`에서만 써진다. 마감에 걸리면 파싱이 종료 75로 바로 끝나 대표 결과·게시가 없으니 그 밤에 끝난 문서도 성공 행이 없어 다음 밤에 다시 골라진다(밤을 넘는 진행이 없음). 서버는 새벽 배치가 꺼져 있어(nightly.time 비움) 지금 운영 영향은 없음. → PR 4(ParsingMeta·대장 단계별, D-3)에 넣음: 파싱 직후(마감으로 멈춰도) 끝난 문서는 represent + `REG.build`(파싱 상태)로 성공 행을 쓰고, 그 몫의 시간을 마감 전에 남김.
  - `StandinPG`·structdb SQLite는 시험과 이미지 관문에만 — dev/prd 실행 중 조용히 대신하는 일은 없다.
- 0.2.0 구현 PR 순서(사용자 10-30, PR 1은 3a에 합침): 2a ∥ 2b → 2c → (DB 담당자 D-1~D-7) → 3a + 3b 연달아 병합 ∥ 4 → 2d → 5(SFDC 먼저, CRMS·LAS는 D-2 전까지 Other) → 6.
  - PR 4에 더할 것(#49 리뷰 10-30): ① 실패 문서 고르기 순서를 대장 `last_seen`(훑은 시각 — 실패 문서끼리 같아져 이름순이 됨) 대신 PR 4가 쓰는 마지막 시도 시각으로 ② `_registry_unparsed`의 대장 읽기는 같은 이름이 행 둘이면 마지막 행이 이김 — "한 행이라도 parsed면 성공"으로(또는 3a 뒤 s3_key당 한 행).
  - FAQ 원천 [pl-39](extract.md#pl-39)는 PR 3a 뒤(gold 칸이 필요).
  - reference 비교 행(10-30): 분류 단계 [pl-33](transform.md#pl-33)와 MCP [mc-16](mcp.md#mc-16)·[mc-17](mcp.md#mc-17)은 PR 5 뒤 — 정확한 자리는 허브가 정함. 파싱 p1 묶음 [pl-34](transform-cleanup.md#pl-34)·잔재 정리 [pl-35](transform-cleanup.md#pl-35)는 순서 미정(허브).
- 구조화 입력: 같은 실행 안에서는 로컬 작업 폴더를 읽고, 나중에 gold만 다시 만들 때는 Object Storage uuid 폴더에서 silver를 받는다.
- PC도 서버와 같은 흐름 — 대역만 다름(OS 폴더, EDW SQLite, PC pgvector), 따로 생기는 로컬 파일 없음.
- 파일: `pipeline/load/{publish_parse_result,parsing_meta}.py`, `pipeline/extract/run_all.py`(`runs.jsonl`·`_DONE`), `pipeline/stackcfg.py`·`pipeline/config.py`(`STACK_SNAPSHOT`), `pipeline/cli.py`(`nightly_plan`), `common/store/{registry,structdb}.py`(SQLite 대체), `deploy/host/scripts/run_docs.py`, `docs/architecture/db_schema.md`.
- (10-31 고침 — 더 새 행은 같은 doc_id, sha256으로 가름, 아래) 결정(사용자 10-30 PRD grill): A4 — 같은 `s3_key`의 여러 행 중 가장 늦은 행은 `FileStorageMap.created_at`이 가장 큰 행으로 고른다. PC 대역 EDW(`valid_env/edw`)의 FileStorageMap에 `created_at` 칸을 새로 만들고 값은 임의로 채운다. 실제 EDW에 이 칸이 있는지는 DB 담당자 답(D-1)으로 확인한다. 0.2.0.
- (사용자 10-31 다시 고침 — sha256, 아래) 결정(사용자 10-31 grill, A4 고침): 같은 `s3_key`의 기준은 `created_at`이 가장 늦은 `FileStorageMap` 행 그대로. 더 새 행이 오면 같은 `doc_id`를 유지하고 **다시 파싱하지 않는다**(같은 내용) — 저장된 기준·메타만 새 행으로 고친다. 밀려난 행은 새 EDW 예외 이력 표에 남긴다(어느 행이 어느 문서와 겹쳤는지, "파싱 대상 아님" — 표 이름·칸은 DB 담당자 D-9, `db_schema.md` §4).
- (10-31 다시 고침 — sha256 대신 file_size, 아래) 결정(사용자 10-31, A4 다시 고침): 같은 `s3_key`의 더 새 행은 같은 `doc_id`를 유지한다. `sha256`이 같으면 건너뛴다(기준·메타만 새 행으로). `sha256`이 다르면 같은 `doc_id`로 다시 파싱·다시 적재한다. 밀려난 행은 위처럼 EDW 이력 표에.
- 결정(사용자 10-31, A4 세 번째 — 최종): 원본을 내려받아 sha256을 비교하지 않는다. 같은 `s3_key`의 더 새 행은 `FileStorageMap.file_size`만 본다 — 크기가 같으면 같은 `doc_id`로 건너뛰고(기준·메타만 새 행으로), 크기가 조금이라도 다르면 같은 `doc_id`로 다시 파싱·다시 적재한다(EDW에 이미 있는 칸이라 내려받기 없음). 같은 키에 같은 크기로 덮어쓰는 드문 경우는 놓친다(받아들임).
- 결정(허브 10-31, 최신 결정 우선): 새 문서 = C10 — 모든 입구(run_docs·`night`·`parse --max-new`·`--source`)에서 EDW `FileStorageMap`에 있고 `ParsingMeta`에 없는 것([pl-23](ops.md#pl-23)). 위의 `nightly_plan()`(새 + 바뀐 문서)과 '문서 대장 성공 행으로 고르기'(허브 B — 2c)는 이 규칙으로 바꾼다. 문서 대장은 숨김·판 관리에만. 이미 ParsingMeta에 있는 `s3_key`를 다시 처리하는 길은 위 A4(`file_size`가 다른 더 새 행 — 10-31 최종)와 사람이 시작하는 전체 e2e뿐.
- Status: todo — 0.2.0.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 문서 대장 upsert, 게시 가드 | upsert에 PG 문법 오류, 가드 꺼짐(서버에 `source.json` 없음) | `structdb.py`, `publish_parse_result.py` | pl-12 |
| 임베딩 없이 구조화 | `PIPE_EMBED=none` → `vector(0)` 표 실패 | `build_bundle.py`, `pgvector_load.py` | pl-16 |
| compose `index_a`/`index_b`가 끝까지 돎 | 실패 | `deploy/host/` | pl-19 |
| 적재는 안 바뀐 문서만 건너뜀 | `file_path`로 건너뜀(sha 칸 없음) — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀 | `pgvector_load.py` | pl-07 |

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- Object Storage 시험 업로드(MinIO). `common/check/os_put.py`.

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| Object Storage + `AI.ParsingMeta` 게시 | `night`, run_docs, 이미지 `publish` 단계에서 기본 실행(모두 `--apply`, `NIGHTLY_PUBLISH=1`) | `PM_BUCKET`, `common.connections.rdb` 쓰기 계정(`PM_BUCKET` 없으면 종료) |

10-29 요청 "EDW와 Object Storage 적재를 기본으로 켬": 게시(Object Storage + `AI.ParsingMeta`)는 `PM_BUCKET`과 EDW 쓰기 계정만 있으면 이미 기본으로 돈다. 꺼져 있는 것은 밤 일정(`NIGHTLY_TIME` 비움 — 10-30 pl-32, 켤 때 시각을 적음). EDW 벡터 적재는 10-29에 지웠다(벡터는 pgvector에만 — [ops.md#op-03](ops.md#op-03)).
