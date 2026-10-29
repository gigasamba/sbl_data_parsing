# ETL — 수집·퍼블리시·적재·DB

[PRD.md](../PRD.md)의 카테고리 하나. 흐름: 수집(원천 → 준비) → 파싱([parse.md](parse.md)) → 구조화 → 적재(pgvector · 정형 DB) · 게시(silver). 서버 문서별 실행기(`run_docs.py`)의 레인·대기열도 여기 둔다.
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서(주제별): 수집 pl-01·pl-29 → 구조화 pl-06·pl-15·pl-16 → 적재 pl-07·pl-13·pl-14·pl-19 → 정형 DB·문서 대장 pl-08·pl-12 → 게시 pl-09·pl-26 → 실행·흐름 러너 pl-10·pl-18·pl-23·pl-24·rn-01·rn-02 → DB 스키마 pl-25·pl-28 → 코드와 다른 점.

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
- 파일: `pipeline/extract/source.py`(FileStorageMap 읽기), `pipeline/transform/structure/build_bundle.py`(`_file_meta` → 조인 결과), `pipeline/config.py`(`file_meta_path`), `deploy/host/scripts/run_docs.py`(`FILE_META_PATH`), `docs/architecture/db_schema.md`.
- 선행: [pl-25](#pl-25)(스키마 — `client_edw` 칸).
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
- Status: todo

<a id="pl-16"></a>
## pl-16 · `PIPE_EMBED=none`이면 `vector(0)`을 만든다
- 이유: 차원 0으로는 표를 만들 수 없어 임베딩 없는 구조화가 실패한다.
- 파일: `pipeline/transform/structure/build_bundle.py`, `pipeline/load/pgvector_load.py`.
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
- Status: dev — `feature/load-no-prune`: `prune`·`--prune`·`PRUNE_*` 설정 없앰(옛 설정 칸은 경고만), `cli load`·`run-stack`·색인 빌드 `--pg`가 더는 안 붙임, `--no-prune`은 옛 호출 호환으로 받기만, 색인 빌드 `--pg`는 `--replace`로(다시 빌드 때 고침). 남은 한계: `file_path`가 바뀐 같은 내용은 옛 행이 남음(사람이 지움 — 사용자 확인). 시험 `tests/server/pipeline/test_pl13_no_prune.py`. 검토 등급 A(서버 적재 동작).

<a id="pl-14"></a>
## pl-14 · 배포 backfill이 지운 `doc.client`를 읽음
- 이유: 10-20 축소 스키마 뒤 `pgvector_load deploy`의 `backfill_chunk_clients`가 실패한다(표와 색인은 그래도 만들어짐).
- 파일: `pipeline/load/pgvector_load.py`.
- Status: done (10-30, `feature/search-path-fixes`) — backfill은 남기고(사용자 10-30) `doc.clients`만 읽음(없는 `doc.client` 안 고름, `_doc_row_clients`도 `clients`만 받음). NULL인 청크만 채우고 멱등인 것은 그대로. 동작은 같음 — 축소 스키마의 고객 라벨은 원래 `clients`에만 있음. 시험: `tests/server/pipeline/test_pl14_backfill.py`(가짜 DB, 이미지) · `tests/general/pipeline/test_pl14_deploy.py`(실 PG 임시 스키마에서 `deploy()` — PG 설정 없으면 건너뜀).

<a id="pl-19"></a>
## pl-19 · compose `index_a`/`index_b`가 끝까지 돌면 실패
- 이유: C-32.
- 파일: `deploy/host/`.
- Status: todo

<a id="pl-08"></a>
## pl-08 · 정형 DB와 문서 대장
- 이유: 계약·고객·문서 판이 정형 질문에 답하고 증분 실행을 이끈다.
- 무엇: `contract_master`·`client_master`·`prod_master`·`doc_contract_link`(점수 매기는 연결기)·`doc_location`·`doc_registry`·`doc_hidden`·`doc_table`·`doc_cell`. PG 또는 SQLite.
- 파일: `pipeline/load/structured.py`, `common/store/structdb.py`.
- Status: done

<a id="pl-12"></a>
## pl-12 · 문서 대장 upsert와 게시 가드
- 이유: 문서 대장 upsert에 PG 문법 오류가 있다(C-54 ①). 서버가 `source.json`을 올리지 않아 게시 가드가 꺼져 있다(C-54 ②).
- 파일: `common/store/structdb.py`, `pipeline/load/publish_parse_result.py`, `tests/server/pipeline/test_publish_guard.py`(알려진 실패).
- 결정(사용자 10-30 grill):
  - ① 문서 대장은 남기고 고친다 — `INSERT OR REPLACE`의 PG 번역(`structdb._pg_sql` 정규식 ↔ `registry.apply`의 여러 줄 SQL). [pl-25](#pl-25)와 함께 키를 `s3_key`로 바꾼다. 새 문서 판별은 FileStorageMap ↔ ParsingMeta 그대로([pl-23](#pl-23)).
  - ② 게시 가드는 `source.json` 사이드카 대신 EDW `AI.ParsingMeta`(`source_key` + `rep_bucket`/`rep_key`)를 읽는다. 같은 문서 → 같은 파일에 덮어씀(`-2`/`-3.md` 사본 없음). 다른 원천이 같은 결과 키로 오면 → 거부. 그러면 `test_publish_guard`가 통과 → `deploy/release/known_fail.txt`에서 뺀다.
- Status: todo — [pl-25](#pl-25) 뒤.

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
- 파일: `pipeline/cli.py`, `deploy/host/scripts/run_docs.py`(서버 전용 — PC에서 실행 금지), `pipeline/trigger_server.py`, `pipeline/parse_parallel.py`, `docs/requirements/run_docs_req.md`, `docs/architecture/run_docs_design.md`.
- Status: done

<a id="pl-18"></a>
## pl-18 · 중간에 멈춰도 `night`/`full`이 종료 코드 0
- 이유: 스케줄러가 실패를 못 본다(C-33).
- 파일: `pipeline/cli.py`(`night`), `deploy/docker/entrypoint.sh`(`full`).
- Status: todo

<a id="pl-23"></a>
## pl-23 · 증분 실행만, 전체 재파싱은 명시적인 전체 e2e
- 이유: 엔진·핸드오프·코드 핑거프린트가 모든 문서에서 바뀌었다. 전체 자동 재파싱은 밤 작업 시간을 넘긴다(C-52, C-08).
- 결정(사용자 10-29 grill): 밤 작업과 `run_docs`는 핑거프린트가 바뀌어도 **새** 문서만 처리한다. "새" = `AI.FileStorageMap.s3_key`가 아직 `AI.ParsingMeta`에 없음(s3 키만 — 갱신 시각 확인 없음, `run_docs`는 이미 이렇게 동작). 전체 재파싱은 사람이 전체 e2e를 시작할 때만(가끔 — 로직을 바꾼 뒤, 결과를 검토). 이 판의 첫 적재는 전체 e2e 한 번.
- 결정(사용자 10-30 grill): 밤 배치는 꺼 둔다(systemd 타이머와 `pipeline.host.nightly.enabled` false). 나중에 사람이 settings.yaml에서 켠다. 실행 시각은 지금 정하지 않는다.
- 지금 안 씀: FileStorageMap 갱신 시각 — 가정한 칸 `last_modified_time`, 나중에 EDW 예시에 추가([pl-25](#pl-25)).
- 파일: `deploy/host/scripts/run_docs.py`(처리 끝난 집합), `pipeline/cli.py`(`night` — 같게 동작하는지 확인).
- Status: todo

<a id="pl-24"></a>
## pl-24 · `run_docs` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 지금은 게시가 gold를 기다리고, `cleanup_doc`이 실패해도 원본을 지운다.
- 결정(사용자 10-29 grill): 원본은 Object Storage에서 수집 서버로 받아 파싱하고, silver 게시가 성공한 뒤에만 지운다. 파싱 실패 → 원본은 남기고 원인 + 걸린 시간을 로컬에만 기록, EDW에는 아무것도 안 씀. gold 실패 → EDW 행은 남고 `gold_status` = failed(+ 이유). gold는 silver에서 다시 만들 수 있다.
- 새 EDW 칸 `AI.ParsingMeta.gold_status`(pending · ok · failed) + 이유 — DDL은 DB 담당자에게(회사 DB, Alembic 아님) — 검토 등급 A. 줄인 ParsingMeta 칸 목록은 [pl-25](#pl-25).
- `valid_env/`로 하는 로컬 시험은 문서를 먼저 임시 폴더로 복사해 거기서 돌린다(제자리에서 돌리지 않음).
- 파일: `deploy/host/scripts/run_docs.py`(`doc_flow`, `cleanup_doc`, 처리 끝난 질의), `docs/operations/parsing_meta_mssql.sql`, 게시(`parsing_meta`).
- Status: todo — [pl-25](#pl-25) 뒤.

<a id="rn-01"></a>
## rn-01 · 레인 정책을 표 하나로 — 담당 레인 먼저, 허용한 레인만 가져오기
- 범위: `deploy/host/scripts/run_docs.py`(서버 호스트에서 이미지 밖으로 실행 — 핑거프린트 영향 없음). 설계 [../architecture/run_docs_design.md](../architecture/run_docs_design.md), 발화 기록 [../requirements/run_docs_req.md](../requirements/run_docs_req.md).
- 사용자 10-29: "data-pipeline 하는데 3개 lane으로 해서, light/medium/vlm 구분해서 배분하고, 특정 lane은 담당, 일부 lane은 steal 허용하는 대신 우선순위는 담당 lane으로 지정. queue 관리해서 진입 시점 개수와 중간 개수 등을 관리."
- 이미 있던 것(행 없음):
  - 3레인 나누기: `classify_doc()`이 미리 받은 문서를 light/medium/vlm으로 가른다. 워커 `LANE_N` light 1 / medium 2 / vlm 1, 워커는 자기 레인부터 비운다([pl-10](#pl-10) 서버 flow 러너).
  - 진입 대기열: `WARM_TARGET`개를 미리 받는다(10-29부터 20 — `pipeline.host.run_docs.warm`, `--warm`). 진행 중 문서는 세지 않고, 문서가 끝나면 임시 파일을 지운다.
  - MCP 우선: `mcp_parse/jobs`가 움직이는 동안 `_mcp_pause_monitor()`가 medium 레인의 새 문서 받기를 멈춘다(서버 측정은 아직 — 설계 문서).
- 이유: 규칙이 `lane_worker()`에 하드코딩돼 있었다(light/vlm은 medium을 안 가져감, 가장 긴 다른 대기열 먼저, vlm은 `VLM_CAP` 상한) — 죽은 분기도 있고 워커 수가 상수라 조정하려면 코드를 고쳐야 했다.
- 단계: (1) 레인마다 정책 표 하나: `workers`, `steal_from`(비면 전담 레인). 기본값 = 지금 동작. (2) 자기 대기열이 빌 때만 가져오고, 허용된 레인 중 가장 긴 것부터, `VLM_CAP`은 그대로. (3) 입력: 러너 인자 `--lanes`(호스트 스크립트 — settings.yaml 절이 필요한지는 설계 때 결정, env는 금지 — CLAUDE.md §3). (4) 죽은 분기를 지운다.
- 수용 기준: `tests/general/deploy/test_run_docs.py`의 표 행 — (대기열, 정책) → 고른 문서. 전담 레인은 다른 문서가 기다려도 가져가지 않음, 자기 대기열이 차 있으면 가져오지 않음, 상한을 넘은 vlm은 건너뜀, 기본 정책은 지금과 같은 문서를 고름.
- 파일: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`, `docs/architecture/run_docs_design.md`.
- 겹침: 파싱 phase 없애기([parse.md#pl-22](parse.md#pl-22), `feature/r2-phase`)는 러너에서 `PARSE_PHASES` `--set`만 뺐고 레인은 건드리지 않았다.
- 끝남 10-29(사용자 grill): settings.yaml `pipeline.host.run_docs` — 레인마다 `<레인>_dedicated`(자기 레인만)와 `<레인>_shared`(자기 레인 먼저, 비면 가장 긴 다른 레인), 기본 각 1 + 1(워커 6개). `vlm_cap` 2는 전담 워커에도 적용. 배치가 끝나지 않을 설정은 시작 때 거부(`warm`이나 `vlm_cap`이 1 미만, 또는 전담·공유 워커가 하나도 없는 레인). MCP 멈춤은 medium 전담 워커를 잡아 둔다. `pick_lane()`은 순수 함수이고 표 시험이 있다. 죽은 상수는 지웠고 `--workers`는 받기만 하고 쓰지 않는다.
- Status: done

<a id="rn-02"></a>
## rn-02 · 중간 대기열 상한(파싱 끝 → 구조화 대기)과 대기열 길이 기록
- 이유: `struct_q`에 상한이 없어 구조화가 느리면 파싱 결과가 쌓인다(디스크, 대기 시간). 10-22 질문 "queue 더 쌓이면 구조화 대기가 더 오래 걸리는지"에 답할 길이 자료가 없다 — `doc_stats.jsonl`의 문서별 `queue_wait`뿐.
- 단계: (1) `--struct-backlog N`: 구조화를 기다리는 문서가 N개면 레인 워커가 새 문서를 받지 않는다(`struct_q.put`이 아니라 `lane_worker`의 고르는 시점에서 막음 — 파싱 워커가 끝난 결과를 들고 있지 않게). 0 = 상한 없음(지금). (2) `mark()` 사건마다 한 줄 `{t, warm, lanes: {light: [대기, 실행], ...}, struct_wait}`을 진행 폴더에 쓴다(op-01이 먼저 들어오면 그 줄 형식을 따름).
- 수용 기준: 구조화를 멈춘 가짜로 돌려도 구조화 대기가 N을 넘지 않음, N=0이면 지금과 같음, 길이 줄은 JSON으로 읽히고 본 문서 수와 맞음.
- 파일: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`.
- 끝남 10-29(사용자 grill): `pipeline.host.run_docs.warm` 20(진입), `struct_workers` 2, `struct_backlog` 기본 = struct_workers × 2(0 = 끔). 레인 워커는 고르는 시점에서 상한을 본다(`test_struct_backlog_holds_new_parses`). `batch_progress/queue_depth.jsonl`에 dispatch / pick / parse_end / struct_put / struct_get마다 한 줄.
- Status: done

<a id="pl-25"></a>
## pl-25 · DB 스키마 명세 — pl-26·pl-23·pl-24를 만들기 전에 먼저
- 이유: 표·칸 정의가 Alembic 마이그레이션(`common/store/db/migrations/versions/`), `docs/operations/parsing_meta_mssql.sql`(ParsingMeta만), `AI.FileStorageMap`을 읽는 코드(정의 없음)에 흩어져 있다. 10-20 축소 스키마는 코드에 반만 반영됐다(mc-10, mc-11, pl-14, pl-15).
- 결정(사용자 10-29 grill): 문서 하나 `docs/architecture/db_schema.md` — 표마다 칸, 타입, 뜻, 어느 코드가 쓰고 읽는지. 대상: EDW `AI.FileStorageMap`(id, s3_key, original_filename, file_size, `last_modified_time` 가정), `AI.ParsingMeta`(+ `gold_status`), pgvector 검색 스키마, `struct`. 10-20 축소 스키마가 정답이고 다른 코드는 mc-10/mc-11/pl-14/pl-15에서 고친다. 시험 하나가 문서의 칸을 마이그레이션·mssql SQL과 대조한다. 구현 전에 사용자와 DB 담당자가 승인하고, DB 담당자는 이 문서를 받는다.
- 결정(사용자 10-30 grill — gold 스키마):
  - 키: 문서 키는 `s3_key` 하나. sha256 `doc_key`를 없애고 문서 대장·`doc_hidden`·`doc_contract_link`의 키를 `s3_key`로 바꾼다([mcp.md#mc-14](mcp.md#mc-14)·[mcp.md#mc-15](mcp.md#mc-15)를 풂 — `ParsingMeta.source_key`로 rep_uri 조회). 검색 `doc`/`chunk`에 `s3_key`가 있어야 한다.
  - 지금 gold: 표 한 벌(`doc`, `chunk`, `chunk_term`, `term_stat`, `corpus_stat`). 나중(지금 설계, 만들기는 나중): 모든 표를 원천 시스템별로 — SFDC · CRMS · LAS · Other, 원천마다 칸이 다를 수 있음. 나눌 때 MCP `search`가 원천을 필수로 받는다(계약 변경 한 번, 새 판, 등급 A). 그 전에는 선택 입력 `source`를 두지 않는다.
  - 원천 = `AI.FileStorageMap.source_system`. 비었거나 SFDC/CRMS/LAS가 아니면 → `Other`. s3_key 접두와 다르면 → 경고 기록만.
  - SFDC 전용 칸(`sf_acc_name`, `sf_op_id`, `sf_op_name`, `project_code__c`)은 `doc` 표 하나에 둔다(다른 원천은 빈 값). 나눌 때 SFDC doc 표로 옮긴다.
  - `load_run`과 Alembic 판 표는 gold에 남고, 나눈 뒤에도 공용. `chunk`는 `source_system`과 `clients[]`를 유지(고객 격리, 원천 거르기).
  - `AI.ParsingMeta`는 읽는 칸만 남긴다: `source_system`, `source_key`(s3_key), `parse_date`, `parse_status`, `status`, `status_at`, `rep_bucket`, `rep_key`, 새 `gold_status` + 이유([pl-24](#pl-24)). `doc_key`와 안 읽는 칸 14개는 없앤다.
  - `struct`: 문서에서 나온 표 `doc_location`, `doc_contract_link`, `doc_table`, `doc_cell`과 그 쓰기·읽기 코드(structured link/tables, `load_tables_db`, `find_table_cells`, 집계 `doc_link_list`/`table_cell_list`/`doc_location_list`, `AG.struct` 서버 길)를 지운다 — 그 내용은 청크 글에만 있다. `stack_version`/`source_version`은 남긴다(MCP 시작 때 읽음).
  - 마스터 `contract_master`, `client_master`는 **따로** Postgres로 옮긴다(검색 PG가 아닌 자기 접속 설정). 사람이 CSV로 채운다(`structured load` 방식). 읽는 코드 `gen_roster`(client_master)와 `terms.py`(contract_master)는 새 접속을 쓴다.
  - EDW 벡터 표(`chunk_vec`, `edw_insert`, `edw_search`)는 PR #5가 지운다.
- 결정(사용자 10-30 — 고객 칸): 문서당 고객 하나는 EDW 조인 사슬에서 온다(값 하나). 문서 글에서 찾은 고객은 별도 목록. MCP 고객 거르기는 EDW 고객**만** 쓰고, EDW 고객이 없는 문서는 고객 거르기를 걸면 빠진다. 글에서 찾은 고객을 거르기에 쓰는 것은 나중([pl-28](#pl-28)). 지금은 둘이 `clients[]`에 섞여 있고(`build_bundle.infer_clients`) `chunk.clients`가 하드 거르기를 이끈다 — 이 행과 함께 고친다.
- 이름 규칙(사용자 10-30): EDW와 문서 파싱 양쪽에서 올 수 있는 칸은 출처를 이름에 넣어 두 칸으로 둔다(예: `client_edw`, `clients_doc`). 정확한 접미어는 `db_schema.md`가 정한다.
- 나누는 시점(사용자 10-30): B — 지금은 표 한 벌. 원천별 나누기는 [pl-28](#pl-28).
- 결정(사용자 10-30 grill 7차): `db_schema.md` U-1..U-6은 초안대로. U-7: `s3_key`당 `doc` 행 하나, `doc_alias` 없음 — `build_bundle`의 같은 파일 내용 해시 합치기(첫 키로 모음, `aliases`)를 지운다. 같은 내용이 두 키에 있으면 문서 둘(임베딩 캐시가 벡터를 재사용). D-2: EDW 고객 조인은 파이프라인이 직접 만든다 → [pl-29](#pl-29).
- 파일: `docs/architecture/db_schema.md`(새), `docs/index.md`, `common/store/db/migrations/versions/`, `docs/operations/parsing_meta_mssql.sql`, `tests/server/common/`(시험 하나).
- Status: dev — `docs/architecture/db_schema.md` 설계안 + 시험 `tests/server/common/test_db_schema.py`(`feature/db-schema-spec`) — 사용자·DB 담당자 승인 대기(코드·스키마 변경 없음).

<a id="pl-28"></a>
## pl-28 · 원천별 gold 표(설계는 pl-25, 만들기는 나중)
- 이유: SFDC · CRMS · LAS · Other는 메타데이터가 다르다. 원천마다 표 하나면 칸이 깔끔하다.
- 무엇(사용자 10-30): gold 표 묶음 — `doc`, `chunk`, BM25 표(`chunk_term`, `term_stat`, `corpus_stat`) — 이 원천마다 한 벌씩(4벌). 원천마다 칸이 다를 수 있다(SFDC 전용 `sf_*`, `project_code__c`는 SFDC doc 표로). `load_run`과 Alembic 판 표는 공용. 그때 MCP `search`가 원천을 필수로 받는다 — 계약 변경 한 번, 새 판, 검토 등급 A. 또 나중에: 글에서 찾은 고객(`clients_doc`)도 고객 거르기에 허용.
- Status: todo — 나중 판, 전체 다시 적재 필요.

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
| 스트리밍 파싱 · 문서별 병렬 파이프라인 | `PARSE_STREAM=0` · `PARSE_PARALLEL_PIPELINE=0` | — |
| 큰 표를 행으로 나누기 | `CHUNK_TABLE` 비움(표는 통째) | — |
| LLM 요약 | `EDW_SUMMARY_LLM=0`(앞부분) | LLM |
| 임베딩 | 이미지 기본 `PIPE_EMBED=api` | `EMBED_BASE_URL`, `EMBED_MODEL` |
| Object Storage + `AI.ParsingMeta` 게시 | `night`, run_docs, 이미지 `publish` 단계에서 기본 실행(모두 `--apply`, `NIGHTLY_PUBLISH=1`) | `PM_BUCKET`, `common.connections.rdb` 쓰기 계정(`PM_BUCKET` 없으면 종료) |
| 밤 일정 | `NIGHTLY_ENABLED=0` | — |
| `--prune`, `vector` 확장 만들기 | 선택 · `PG_CREATE_EXTENSION=0` | — |
| trigger 서버 | — | `TRIGGER_TOKEN`(없으면 시작 거부) |

10-29 요청 "EDW와 Object Storage 적재를 기본으로 켬": 게시(Object Storage + `AI.ParsingMeta`)는 `PM_BUCKET`과 EDW 쓰기 계정만 있으면 이미 기본으로 돈다. 꺼져 있는 것은 밤 일정(`NIGHTLY_ENABLED=0`) — 아직 안 바꿈, 사용자 선택 필요. EDW 벡터 적재는 10-29에 지웠다(벡터는 pgvector에만 — [settings.md#op-03](settings.md#op-03)).
