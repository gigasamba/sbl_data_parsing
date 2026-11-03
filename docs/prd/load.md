# 적재 — pgvector·게시·저장 구조

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md) 다음: pgvector 적재(pl-07·pl-13·pl-14·pl-16·pl-19) → 게시(silver — pl-09·pl-26) → FAQ 다시 올리기(pl-41) → 지운 정형 DB·문서 대장(pl-08·pl-12)·마스터 CSV(pl-38). 저장 구조·DB 스키마는 [load-schema.md](load-schema.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-29 · pl-07 · pl-13 · pl-14 · pl-16 · pl-19 · pl-09 · pl-26 · pl-41 · pl-40 · pl-08 · pl-12 · pl-38. (저장 구조 pl-32는 [load-schema.md](load-schema.md#pl-32))

<a id="pl-29"></a>
## pl-29 · EDW 고객 매핑을 파이프라인이 직접 만든다
- 자리(사용자 11-02): 수집(extract)에서 적재(load)로 옮김 — 매핑 결과는 검색 DB `doc` 행(`client_edw`·`sf_*` 칸)을 쓸 때와 검색 필터만 쓰고, 파싱·구조화는 쓰지 않는다. 적재 때 붙이면 매핑이 바뀌거나 수동 갱신(pl-40)할 때 다시 파싱·구조화하지 않는다. 코드 이동(`build_bundle._file_meta`에서 적재 쪽으로)은 pl-29 구현 때 함께.
- 결정(사용자 10-31 범위 축소 grill): 고객 매핑은 **기회 직접 + 계정 직접만** 먼저(+CRMS). Task·Event·Quote 단계는 매칭률을 재 보고 낮으면 추가 — PC 가짜 Quote 표도 그때.
- 이유: 문서마다 EDW 고객 하나(`client_edw` — MCP 고객 거르기의 유일한 키, [pl-25](load-schema.md#pl-25))와 SFDC 칸(`sf_acc_name`·`sf_op_id`·`sf_op_name`·`project_code__c` 등)을 지금은 외부에서 뽑은 `file_meta_new.jsonl`(`pipeline.paths.file_meta_path`)에서 읽는데, 그 파일을 만드는 코드가 저장소에 없다(db_schema.md D-2).
- 결정(사용자 10-30 grill 7차): 파이프라인이 EDW 읽기 계정(`common.connections.rdb.read`)으로 조인을 직접 만든다. SFDC: `AI.FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`(고객 = Account 이름). CRMS·LAS 경로는 DB 담당자 확인(D-2). `file_meta_new.jsonl` 읽기를 대신한다.
- 결정(사용자 10-30 grill — pl-25 검토): 고객뿐 아니라 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 같은 자리에서 EDW에서 직접 읽는다 — 외부 파일 `file_meta_new.jsonl`은 없어진다.
- 파일: `pipeline/extract/source.py`(FileStorageMap 읽기), `pipeline/load/pgvector_load.py`(적재 때 EDW 조인 — 옛 `file_meta_path`·`FILE_META_PATH`는 11-02에 지움, pl-29), `docs/architecture/db_schema.md`.
- 선행: [pl-25](load-schema.md#pl-25)(스키마 — `client_edw` 칸), [pl-32](load-schema.md#pl-32)(저장 구조).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) C6·T7): 고객 연결은 운영 4단계를 따른다 — 출발점 `FileStorageMap`, 순서 기회 직접 > `Task.WhatId` > `Event.WhatId` > Quote 스냅샷, 계정 직접 연결도 포함. 결과는 pgvector doc에만. 같은 sha256 묶음에도 고객은 전파하지 않는다(C3).
- 열린 점: Quote 단계는 레플리카에 Quote 표가 없어 SFDC REST 스냅샷에 기댄다 — 서버에서 스냅샷을 어떻게 공급할지 정해야 함. → 해소(10-31 결정 — PC 대역 Quote 표, 아래).
- 결정(G2·T16 — 2차 grill(사용자 10-30, 원본은 git 밖)): `client_edw`(문서당 고객 하나)는 SFDC(4단계 연결)와 **CRMS**(`FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST` — DB 담당자 확인, D-2)에서 채운다. LAS는 상대사 출처가 정해질 때까지 비워 둔다. FAQ는 고객 연결 없음([pl-39](extract.md#pl-39)).
- 결정(G11 — 3차 grill(사용자 10-30, 원본은 git 밖)): 적재 뒤 바뀐 SFDC 연결(고객·`sf_op_id` 등)은 자동으로 갱신하지 않는다. 수동 요청 때 전체 문서를 갱신한다([pl-40](#pl-40)).
- 결정(사용자 10-30 PRD grill): A3 — 고객 연결의 마지막 단계(SFDC Quote 스냅샷)는 미정으로 둔다(서버 레플리카에 Quote 표 없음). 허브가 0.2.0 설계 확인 때 사용자에게 다시 묻는다. 그 전까지 구현은 기회 직접 > Task > Event 3단계(+계정 직접).
- 결정(사용자 10-31 grill): A3 — Quote 단계도 0.2.0에 넣는다. PC 대역 EDW(`valid_env/edw`)에 SFDC Quote 표를 예시 칸으로 새로 만들어 4단계(기회 직접 > Task > Event > Quote, +계정 직접)로 구현한다. 실제 표·칸 이름은 DB 담당자 답으로 맞춘다(A4 `created_at`과 같은 방식).
- 구현(11-02 `feature/mcp-ops-parity`): 사용자 11-02 — 매핑은 적재 몫. `pipeline/load/edw_meta.py`가 적재 때(PG 트랜잭션 밖, 읽기 계정) 원천별 사슬로 `client_edw`·원천 칸·`created_at`을 채운다(사슬은 [db_schema.md](../architecture/db_schema.md) §1 — 운영 gold 스키마 노트 기준, 칸 이름은 D-1 확인). SFDC 4단계(기회 직접 > Task > Event > Quote, +계정 직접 — 같은 단계 동률은 비움), CRMS(`RM_CM_PJTLIST`·`RM_CM_DOCU`), LAS(`LAS.Contract` 최신 판·`FileManager`). Quote는 운영처럼 EDW 표로 재현(사용자 11-02) — 서버 EDW에 표가 없으면 그 단계만 건너뜀(C-76: DB 담당자가 표를 만들고 REST 스냅샷으로 채움, 누가·언제는 미정). 외부 `file_meta_new.jsonl`·`FILE_META_PATH`·build_bundle의 `_file_meta`를 지웠다. EDW를 못 읽으면 메타 없이 적재(경고·`meta_missing`) — 자동 갱신 없음, `--replace`로 다시 적재해 채움. PC 가짜 EDW(`valid_env/edw`)에 가짜 사슬 표를 더했다. 시험: `tests/server/pipeline/test_edw_meta.py`.
- 결정·구현(사용자 11-02, `feature/edw-chain-config`): Quote 표는 지금 없다 — 기본 사슬은 기회 직접 > Task > Event(+계정 직접). 사슬의 표·칸 이름·SFDC 단계 순서·gold 칸 대응은 설정 파일 `resources/config/edw_chain.yaml`(운영 쪽이 고침 — 이미지·코드 폴더에 들어감)로 옮겼다(운영 서버에서 고치는 법: [server-guide §5-2](../operations/server-guide.md#5-2-edw-조인-사슬-고치기--edw_chainyaml)). Quote 표가 생기면 그 파일의 주석 줄 하나를 켠다(`optional: true` — 표를 못 읽으면 그 단계만 건너뜀). 적재 때 파일을 읽어 검사한다 — 빠진 이름·SQL에 넣을 수 없는 이름(표 `스키마.표`, 칸 영문·숫자·_, 접두 3자)·설정으로 채울 수 없는 gold 칸(원천 전용 칸과 `client_edw`만 — 문서 키·`created_at`은 안 됨)이면 이유를 모두 말하고 멈춤(값은 늘 바인딩). 사슬의 모양(단계 동률은 비움, 기회가 없을 때만 계정, LAS 최신 판·대체 값)은 코드(`pipeline/load/edw_meta.py`). 시험 `tests/server/pipeline/test_edw_meta.py`(Quote 켠 설정으로 24사례 그대로 + 기본 설정 Quote 없음 + 틀린 설정 7가지 거부).
- 결정·구현(사용자 11-03, `feature/edw-chain-path`): 사슬 파일 자리를 설정으로 — `ops.pipeline_paths.edw_chain`(`EDW_CHAIN_FILE`, 적재만 읽는 pipeline 칸 — 레이어 code_fp 안 바뀜). 비우면 기본 `resources/config/edw_chain.yaml`, 경로면 그 파일(같은 `load_chain` 검사). 없거나 틀린 파일이면 적재 시작 때 멈춤(기본 파일로 안 돌아감). 파일만 점검: `python -m pipeline.load.edw_meta --check [--file F]`(EDW·PG에 안 붙음). 서버 사본은 settings.yaml 옆 `<settings.yaml 폴더>/edw_chain.yaml` — 그 폴더를 `data-pipeline`에만 `/etc/rag/env`로 읽기 전용 마운트(`:ro,z`), settings.yaml이 실제로 있는 폴더(`SETTINGS_DIR` — load_settings가 냄)를 붙임, 폴더 root:10001 750(`dc.sh init` — 안 파일이 640보다 넓거나 주인이 root·10001이 아니면 멈춤, C-88). 쓰는 법은 [release-and-patch §8-6](../operations/release-and-patch.md#8-6-edw-조인-사슬-파일-고쳐-쓰기서버--pl-29). 시험 `tests/server/pipeline/test_edw_meta.py::test_chain_file_setting`.
- Status: done(11-03)

<a id="pl-07"></a>
## pl-07 · pgvector 적재
- 이유: 검색 서버는 PG를 읽는다.
- 무엇: 원천 스키마 5벌마다 표 `doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` + 뷰 `v_chunk_source`(Alembic으로만 — 11-02 판 0002, `load_run`은 지움). 이미 적재된 문서는 `file_path`로 건너뛴다(sha 열 없음 — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀). (`--prune`은 10-30에 없앰 — [pl-13](#pl-13).) (이름 붙은 색인 `index_id`는 11-01에 지움 — mc-16.) 벡터는 pgvector에만 둔다(EDW 벡터 적재는 10-29에 지움 — [ops.md#op-03](ops.md#op-03)).
- 파일: `pipeline/load/pgvector_load.py`, `common/store/db/migrations/`.
- 결정(허브 10-31, 최신 결정 우선): 이름 붙은 색인(`index_id`)은 0.2.0에 없앤다 — 원천(`source_system`)이 gold 스키마를 고르므로 색인 이름이 필요 없다(선택지 줄이기 원칙). 구현은 [pl-28](load-schema.md#pl-28)과 함께.
- 결정(사용자 10-31): PG 자동 찾기(`docker ps` pgvector·대체 포트·코드 기본 `127.0.0.1`/`5432`/`rag`)를 없애고 PG 접속은 필수 — [ops-settings.md#op-09](ops-settings.md#op-09).
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
- 한 것(11-03 `feature/fp-perf`): `pipeline/load/pgvector_load.py` `require_vectors(meta)` — 묶음 `meta.json`의 `dim`이 0·없음이거나 `embed`가 `none`이면 한 줄 안내(`build_bundle --embed api`로 다시) 뒤 종료 코드 2. `main()`(배포·적재 — 판 확인 전)과 `load()` 첫머리에서. 시험 `tests/server/pipeline/test_pgvector_load.py` `test_require_vectors`.
- Status: done — 11-03

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
- 파일: `deploy/host/scripts/run_docs.py`(`night`·`full` 입구는 11-01에 지움), `deploy/docker/entrypoint.sh`(`publish`), `pipeline/load/`의 게시, `pipeline/config.py`, `docs/operations/server-guide.md`.
- Status: done (11-03 확인) — 11-01 `full`·`night` 입구는 지움([pl-18](ops.md#pl-18)). run_docs는 문서마다 늘 게시하고([pl-24](ops.md#pl-24) — gold 전), 게시 버킷·접두(`pipeline.load.publish.bucket`·`prefix`)가 없으면 시작을 거부한다(`SETTINGS_REQUIRED`).

<a id="pl-41"></a>
## pl-41 · FAQ 다시 올리기 — 통째 교체
- 결정(사용자 11-03 — 최신 결정 우선): 판을 잇지 않는다(`content_id`·`content_version_id`·uuid 경로로 같은 FAQ를 찾지 않음). FAQ를 다시 올리면 gold faq 스키마의 **문서·청크를 모두** 지우고, 지금 FileStorageMap에 있는 FAQ 파일 **전체**를 다시 파싱·적재한다. 검토 등급 A(gold 지우기).
- 한 것(11-03 `feature/faq-source`):
  - 새 FAQ = FileStorageMap의 `FAQ/…` 키 중 호스트 진행 폴더의 `faq_seen.txt`(교체를 마친 키 목록)에 없는 것. `faq-sync --reset` 결과를 읽은 **뒤에만** 적는다 — 교체가 실패하면 다음 실행이 다시 시도한다. ParsingMeta는 판정에 쓰지 않는다(`--seqs`·`--limit` 실행이 교체 없이 기록할 수 있어서). 처음 실행(파일 없음)은 FAQ 전체를 한 번 교체한다. `--start-offset`이 대상 수보다 커도 FAQ 교체는 확인한다.
  - `run_docs.py` `faq_first`(처리 순서를 정한 뒤 — `--skip-done` 뒤, `--max-docs` 앞): FAQ 목록은 `--filter`와 상관없이 FileStorageMap에서 따로 읽는다(`edw_faq` — `edw_list`와 같은 질의, 없는 FAQ 행은 대상 목록 뒤에 덧붙임). 새 FAQ가 있으면 구조화 컨테이너에서 `pgvector_load faq-sync --reset`으로 gold faq의 문서·청크·키워드 색인을 한 트랜잭션에서 모두 지우고, FAQ 전체를 이번 처리 맨 앞에 넣는다(이미 끝난 FAQ도). 새 FAQ가 없으면 지우지 않고 gold에 없는 FAQ만 넣는다(완전 중복 `skipped_dup`은 gold에 안 올라가므로 뺌) — 중간에 멈춘 교체(`--max-docs`·`--deadline`·장애)와 파싱 실패는 다음 실행이 지우지 않고 채운다.
  - `faq-sync` 결과(`--out` JSON 파일 — 지운 수·남은 gold faq `file_path`)를 못 읽으면(실패·시간 초과 — 지웠는지 모름) 경고(오류 끝 200자)와 함께 FAQ 전체를 넣는다(적재는 이미 있는 문서를 건너뛰므로 어느 쪽이든 안전). `faq-sync --reset`은 우리 표식이 있는 스키마에서만, 실 PG는 `load`와 같은 판 확인 뒤에만 지운다.
  - `--seqs`·`--limit`(골라 돌리기·시험)에서는 FAQ 교체를 하지 않는다(로그 한 줄).
  - 남는 한계: 지우고 다시 넣는 사이(같은 실행 안)에는 검색에서 FAQ가 일부만 보인다. 시간 초과(1800초)면 컨테이너 안 명령이 늦게 지울 수 있다(다음 실행의 채움이 메움). FileStorageMap에서 사라진 FAQ는 지우지 않는다(pl-13 — 다음 새 FAQ 교체 때 함께 빠짐). 파싱에 계속 실패하는 FAQ는 매 실행 다시 시도한다.
  - 시험: `tests/server/pipeline/test_faq_rows.py::test_faq_sync`(SQLite 대역), `tests/general/deploy/test_run_docs.py::test_faq_first`. 서버 확인은 refactor.md C-84.
- 아래 10-30·10-31 결정(행 단위 비교, 같은 uuid 통째 교체)은 이 결정으로 대신한다.
- 결정(사용자 10-31 범위 축소 grill): 행 단위 비교 대신 **통째 교체** — FAQ 파일을 다시 올리면 그 FAQ 문서의 청크를 지우고 다시 적재.
- 결정(G13·T18 — 3차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 고쳐 새 `s3_key`로 올리면 기존 FAQ 청크와 **행(청크) 단위로** 비교한다.
  - 같은 항목 = `FAQ_group`과 질문 글이 같음.
  - 가장 최신 답만 남긴다 — `last modified date`, 없으면 새 파일. 예전 행은 gold에서 지우고 새 행을 더한다. 같은 질문이 없는 새 행은 더한다.
  - [pl-13](#pl-13)("적재는 지우지 않음")의 **FAQ 한정 예외** — 검토 등급 A(서버 적재 동작).
- 관련: [pl-39](extract.md#pl-39)(FAQ 원천).
- 결정(사용자 10-30 PRD grill): A7 — FAQ를 다시 올려 청크가 0개가 된 옛 `doc` 행은 적재 때 지운다(pl-13 '적재는 지우지 않음'의 FAQ 예외).
- Status: done (11-03 `feature/faq-source`)

<a id="pl-40"></a>
## pl-40 · 수동 갱신 명령 — 분류·시스템 메타를 따로
- 결정(사용자 10-31 범위 축소 grill): 수동 갱신 명령 2개를 **만들지 않는다** — load --replace나 다시 실행으로 대신.
- 결정(G10·G11·G12·T17 — 3차 grill(사용자 10-30, 원본은 git 밖)): 수동 갱신 명령은 두 갈래를 **각각 따로** 고른다(한 번에 둘을 같이 고치는 길은 없음).
  - ① LLM 갈래: 분류(`doc_class`) — 기본 대상은 `doc_class`가 NULL인 문서(G10).
  - ② 시스템 메타 갈래: EDW에서 오는 고객·`sf_op_id`·`created_at` 등 — 요청하면 전체 문서(G11).
  - 재파싱·재임베딩은 하지 않는다. 시스템별 gold `doc` 칸만 UPDATE한다(G19 — 파일 메타는 ParsingMeta에 없음).
- 관련: [pl-33](transform.md#pl-33)(분류), [pl-29](#pl-29)(고객 연결), [pl-25](load-schema.md#pl-25)(칸).
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
- 파일: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `pipeline/load/parsing_meta.py`.
- 결정(사용자 10-30 grill):
  - ① 문서 대장은 남기고 고친다 — `INSERT OR REPLACE`의 PG 번역(`structdb._pg_sql` 정규식 ↔ `registry.apply`의 여러 줄 SQL). [pl-25](load-schema.md#pl-25)와 함께 키를 `s3_key`로 바꾼다. 새 문서 판별은 FileStorageMap ↔ ParsingMeta 그대로([pl-23](ops.md#pl-23)).
  - ② 게시 가드는 `source.json` 사이드카 대신 EDW `AI.ParsingMeta`(`source_key` + `rep_bucket`/`rep_key`)를 읽는다. 같은 문서 → 같은 파일에 덮어씀(`-2`/`-3.md` 사본 없음). 다른 원천이 같은 결과 키로 오면 → 거부. 그러면 `test_publish_guard`가 통과 → `deploy/release/known_fail.txt`에서 뺀다.
- 결정(사용자 10-30 grill 12~13차): 원천에서 사라진 문서(deleted) 처리 길은 통째로 없앤다 — 지우기·숨기기·EDW `deleted` 표시 모두 없음, 로컬 기록만(refactor.md C-54).
- 10-30 [pl-32](load-schema.md#pl-32): PG `doc_registry`는 남고 로컬 SQLite 대체는 없앤다. 실패 횟수(`fail_count`)·재시도 설정(`registry_retry_max`)은 없앤다 — 성공했을 때만 갱신(사용자 10-30).
- 한 것(10-30, B1 — 개발 서버 반입 전 검토): deleted 길 없앰 — `registry.apply`가 관측에 없는 문서에 `status='deleted'`·자동 숨김을 쓰지 않고, `parsing_meta.apply_registry_status`가 EDW에 `deleted`를 쓰지 않는다(`diff["deleted"]`는 판 잇기 정보로만). 서버(dev·prd)는 SQLite·PG 스탠드인으로 대체하지 않고 멈춘다(`structdb.open_backend` — `run_mode: prod`·`struct_backend` pg/tsql 필수, `pg._warn_standin`). `common.store.run_mode`는 `prod`·`test`만. 시험 `tests/server/common/test_no_deleted.py`. code_fp p0·p1·r·s 바뀜(공용 `settings.py`·`pg.py`·`structdb.py`).
- 한 것(11-01 `feature/scope-cut-search`): `common/store/registry.py`·`registry_cli`·검색 `registry.py`·숨김 거르기(retriever·pgsearch)·게시의 대장 상태 갱신·ParsingMeta 상태 갱신 길 지움. 표는 struct 스키마와 함께 코드에서 없앰([pl-08](#pl-08)). 설정 `common.store.doc_registry`·`registry_etag_md5` 지움(남으면 경고).
- 11-02 C10 예외(사용자): ParsingMeta `loaded_at` 한 칸만 적재 때 UPDATE(`parsing_meta_db.mark_loaded`) — 다른 칸은 그대로 INSERT만(`test_no_deleted`가 UPDATE는 `SET loaded_at`뿐인지 본다).
- 결정(사용자 11-02): 알려진 실패를 0으로 — (아래 한 것) 쓰이지 않는 게시 가드(`source.json` `skip_exists`·키 충돌 거부)와 `tests/server/pipeline/test_publish_guard.py`를 지우고 `deploy/release/known_fail.txt`를 비운다.
- 한 것(11-02 `feature/publish-guard` — 사용자 11-02 known_fail 0): ②의 `source.json` 사이드카 가드(`apply()`의 `skip_exists`·`error_key_collision`·`key_collision_*` 건수·저장소 `get_text`)와 그 시험 `test_publish_guard`를 지웠다 — 서버가 source.json을 올리지 않아 늘 꺼져 있었다. ParsingMeta로 다시 만드는 안(위 ②)은 하지 않는다: 같은 문서를 다시 고르지 않는 것은 고르기([pl-25](load-schema.md#pl-25) — silver·gold 결과)가 맡고, 결과 파일 이름에 시각이 들어가 덮어쓰지 않는다. 남는 이론상 충돌(원본 키 sha1 10자)은 막지 않는다(`rep_md_key` 주석). `deploy/release/known_fail.txt`는 빈 목록.
- Status: done (11-01 `feature/scope-cut-search`)

<a id="pl-38"></a>
## pl-38 · 마스터 표 — 용어집·고객 명부를 PostgreSQL로(0.2.0)
- 결정(사용자 11-03 — 지문 배치와 같은 0.2.0 판, 등급 A: DB 스키마 + 핸드오프 지문):
  - **ETL 규칙:** 변환(Transform) = 문서 내용 + 고객 명부로 고객 알아보기(청크 머리에 고객이 들어가 임베딩 입력이 되므로 변환에 남김). 적재(Load) = EDW 조인([pl-29](#pl-29))·분류([pl-33](transform.md#pl-33))·DB 쓰기. 검색도 마스터를 읽는다. 대표 결과(silver)는 마스터를 읽지 않는다.
  - **옮기는 것:** `resources/vocab/glossary`의 데이터 CSV 여섯 개(`client_roster`·`client_master`·`contract_master`·`domain_terms`·`id_patterns`·`units`)를 검색 PG의 마스터 표로. `client_master.example.csv`·`client_master_map.example.json`·`client_roster_seed.json`(명부 초안 도구 입력·예시)은 파일로 남긴다(Q4).
  - **스키마:** `<PG_SCHEMA>_master`(기준 스키마에서 이름을 만듦 — 개발자마다 스키마가 갈림, 고정 이름 아님 · Q2). 표·칸은 Alembic 갈래 `master`로만(`dbtool up --target master`, `--target all`에 포함). CSV 하나에 표 하나 — 칸은 CSV 머리글 그대로(글자) + 파일 순서 `row_no`, 목록 칸은 지금처럼 `;`·`|` 글자(Q3). 해시·적재 시각은 `master_meta`.
  - **원본은 git CSV:** `dbtool master load`가 CSV로 표 내용을 한 트랜잭션에 통째로 바꾸고 내용 해시(표 이름·머리글·`row_no` 순서 행의 sha256)를 `master_meta`에 적는다. 초기화 순서 `dbtool up`(search·applog·master) → `dbtool master load` → …(README·release-and-patch §8·server-guide).
  - **읽는 곳:** `common/core/terms.py`의 용어 사전·ID 모양·고객 명부 로더가 PG 마스터를 읽는다(프로세스마다 한 번, 마스터 해시가 바뀌면 다시) — 구조화의 고객 판별(`build_bundle` `infer_clients`)과 검색(`terms`·`local`·`shaping`). PC·시험은 같은 CSV로 채운 SQLite 대역. 서버(dev·prd)는 마스터를 못 읽으면 시작하지 않는다(Q5). 설정 `glossary_dir`·`client_roster`는 지움(옛 설정 파일에 남으면 경고 — Q8), `gen_roster`는 `--dir` 그대로.
  - **지우는 것:** 대표 결과 융합의 용어집 그럴듯함 가산(`fuse.py` `term_plausibility` — [pl-04](transform.md#pl-04)) · 판 묶음(`docmeta.family_key`·묶음 `family`·검색 최신 순위의 family 사용 — `doc_date`·`version`·`superseded`는 남김, D2) · 묶음의 용어 초안 수집(`collect_draft_terms` → PG를 읽는 오프라인 도구, 검색은 초안 파일을 그대로 읽음 — D3) · 안 쓰는 `modalities()`·`build_bundle`의 쓰지 않는 고객·제품 값.
  - **판:** `gold_version` = `<VERSION>+m<해시 8자>` — 구조화가 읽은 마스터 해시를 묶음 `meta.json` `master_hash`로 넘기고 적재가 ParsingMeta에 쓴다(`master_hash`가 없는 묶음은 `<VERSION>`만). `silver_version`에는 붙이지 않는다. 마스터 해시는 캐시 열쇠·code_fp에 넣지 않는다(마스터가 바뀌어도 자동 전체 재처리 없음 — `gold_version`으로 추적).
- 결정(사용자 10-31 범위 축소 grill — 위로 고침): 마스터는 모두 별도 RDB로 관리 → 11-03: 별도 RDB가 아니라 검색 PG의 `<PG_SCHEMA>_master`.
- 결정(사용자 10-30): "contract_master, client_master 등 활용하는 방안 같이 설계하자. 후순위로 해줘." — 표로 옮기는 것까지 0.2.0, 쓰는 곳 넓히기(검색 거르기·분류 단서)는 후순위 그대로.
- 결정(허브 10-31): 고객 별칭 몫(고객 명부·별칭 그룹 — [mcp.md#mc-05](mcp.md#mc-05))은 0.2.0 — 위 읽는 곳에 포함.
- 잠재 문제(사용자 11-03): 같은 문서의 다른 판(`s3_key` 다름) 묶기 — 검색 '최신' 질문에서 옛 판이 위로 올 수 있음, 필요해지면 다시 설계.
- Status: done — `feature/pl38-master`(#135) 병합(0.2.0 지문 배치). 잠재 문제(판 묶기)는 위 줄 — PRD 표 todo 행.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작(알아 둘 동작 — 열린 결함 없음)
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 적재는 안 바뀐 문서만 건너뜀 | `file_path`로 건너뜀(sha 칸 없음) — 같은 경로에서 내용이 바뀌어도 `--replace` 없이는 건너뜀 | `pgvector_load.py` | — (pl-07 done) |

(정리 11-03: 문서 대장·게시 가드 pl-12, 임베딩 없는 구조화 pl-16, compose `index_a`/`index_b` pl-19는 모두 done — 코드째 지웠거나 고침.)

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- (없음 — MinIO 시험 업로드 `common/check/os_put.py`는 0.2.0에 지움, pl-46.)

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| Object Storage + `AI.ParsingMeta` 게시 | run_docs가 문서마다 늘 게시(끌 수 없음 — pl-26), 이미지 `publish` 명령도 있음 | 게시 버킷·접두(`pipeline.load.publish.bucket`·`prefix` — 없으면 시작 거부), EDW 쓰기 계정 |

10-29 요청 "EDW와 Object Storage 적재를 기본으로 켬": 게시(Object Storage + `AI.ParsingMeta`)는 `PM_BUCKET`과 EDW 쓰기 계정만 있으면 이미 기본으로 돈다. 꺼져 있는 것은 밤 일정(`NIGHTLY_TIME` 비움 — 10-30 pl-32, 켤 때 시각을 적음). EDW 벡터 적재는 10-29에 지웠다(벡터는 pgvector에만 — [ops.md#op-03](ops.md#op-03)).
