# 운영 — 실행 관리·러너·계정·종료·로그

[PRD.md](../PRD.md) 카테고리. 실행 관리(pl-10·pl-23·pl-54·pl-24·pl-18), 서버 러너 `run_pipeline.py` 레인·대기열(rn-01~04), 종료 정리(pl-27), EDW 계정(op-03), 모델 호출 가드(pl-11), 로그(op-01). 설정 파일은 [ops-settings.md](ops-settings.md).

순서: pl-10 · pl-23 · pl-54 · pl-24 · pl-18 · rn-01 · rn-02 · rn-03 · rn-04 · pl-27 · op-03 · pl-11 · op-01 · rn-09 · rn-10.

<a id="pl-10"></a>
## pl-10 · 실행 관리 — 서버 입구는 `run_pipeline.py` 하나
- 이유: 서버는 문서 수천 건을 사람 없이 돌린다.
- 규칙:
  1. CLI `pipeline.cli`는 `parse`·`show-stack`·`selftest`. 이미지 entrypoint(`deploy/docker/entrypoint.sh`)가 `publish`·`migrate`·`check`·`services`·`resources`·`tool`·`ask`·`mcp`·`run-mcp-parsing`·`idle`을 더한다. `idle` = 상주 컨테이너가 떠 있기만 한다(run_pipeline이 `docker exec`).
  2. 서버 실행은 호스트 python의 `deploy/host/scripts/run_pipeline.py`(PyYAML·pymssql 필요)가 상주 컨테이너 `data-pipeline` 안에서 문서마다 명령을 `docker exec`로 돌린다. 컨테이너 명령은 settings.yaml `ops.host.container_cli`(없으면 podman). PC에서는 실행하지 않는다.
  3. 시작: 설정 파일 = `--settings` → `SETTINGS_FILE` → `<루트>/settings.yaml`(루트 = 코드 폴더 자체 — op-13). `required.env.run_env`가 dev·prd가 아니거나 필요한 칸이 없으면 칸 경로만 찍고 종료 2. 코드 폴더 = `--code`(없으면 스크립트가 든 코드 폴더) — 그 안의 `common/config/layout.py`·`deploy/host/scripts/host_settings.tsv`로 설정 배치와 컨테이너 안 경로를 읽는다.
  4. 대상 목록(컨테이너 안 `python -m pipeline.extract.candidate_pick list` — run_pipeline은 목록 파일 `<결과 자리>/_docflow/targets.json`만 읽음): EDW `SELECT id, s3_key, original_filename, file_size, source_system FROM AI.FileStorageMap WHERE (<이름 조건>) [AND UPPER(source_system) IN (<원천 목록>)] AND file_size IS NOT NULL ORDER BY file_size ASC`(원천 목록 = `required.source.source_systems` — 비우면 그 조건 없음, 원천 값은 대문자로 넘김). 이름 조건 = `--filter`의 낱말마다 `LOWER(original_filename) LIKE '%낱말%'`를 OR — `--filter`가 없으면 이름 조건 없이 모든 문서(기본). 순번(seq)은 이 순서. `--start-offset N`(기본 0)부터, `--seqs`면 그 순번만, `--skip-done`이면 끝난 문서([pl-23](#pl-23))를 빼고, FAQ 먼저([load.md#pl-41](load.md#pl-41)), `--max-docs`면 그 뒤 앞에서 N건, `--limit`은 시험용(그 전에 자름). `--filter`는 글자·숫자·`_` `,` `.` `-`만, `--seqs`는 숫자와 쉼표만(아니면 종료 2).
  5. 문서마다: 미리 받기(`candidate_ready stage` — 받기 → 중복 → 거르기) → 레인 분류 → 파싱 → 게시 → 원본 삭제 → gold(구조화+적재) → 임시 삭제([pl-24](#pl-24)). 배치 장벽 없이 끝나는 순서대로 흐른다.
  6. 레인·대기열은 [rn-01](#rn-01)·[rn-02](#rn-02), MCP 양보는 [rn-03](#rn-03)·[rn-04](#rn-04), 종료 코드는 [pl-18](#pl-18).
  7. 문서별 값은 컨테이너 명령에 `--set`으로 준다(같은 이름은 뒤 값이 이김):
     - 파싱 공통: `VLM_MAX_CONCURRENCY=8` · `VLM_CONCURRENCY=8` · `VLM_FIGURES_MAX=10` · `PARSE_POST=supsub,charts,figures,context,attachments` · `RAPIDOCR_PAGE_WORKERS=2` · `OCR_THREADS=1` · `PIPE_PROCS=4` · `PARSE_REP_SELECT=first` · `PARSE_QA_LIGHT=1`, 문서 출력 자리 `PIPE_OUT_ROOT`·`DOC_DIR_PREPARED`·`PARSE_IMAGES_ROOT`·`PARSE_RAW_ROOT` = `<결과 자리>/_docflow/<seq>/…`.
     - vlm 레인이면 덧붙임: `VLM_MAX_CONCURRENCY=6` · `VLM_CONCURRENCY=6` · `PARSE_POST=…,attachments,vlm_page` · `VLM_PAGE_MAX=`(상한 없음). 쪽 해상도는 settings.yaml `extract.page_render_dpi`(VLM 설정은 [pl-43](transform.md#pl-43)).
     - CPU 게이트 `CPU_MAX_LOAD` = light 레인 9(사실상 게이트 없음), 그 밖 `--cpu-gate`(기본 1.3).
     - 미리 받기: `SOURCE_STAGING=<결과 자리>/_staging` · `SOURCE_FETCH_WORKERS=2`로 `python -m pipeline.extract.candidate_ready stage --csv <_docflow/seq>/batch.csv --out <_docflow/seq> --prepared <_docflow/seq>/prepared`(`ops.run_pipeline.parse.batch_rotate_scans`가 꺼져 있으면 `--no-scan-rotate`), 제한 900초.
     - 파싱 명령: `python -m pipeline.cli parse --staged`(stage가 남긴 `parse/_source/only.txt`만), 제한 2700초.
     - 구조화·적재: `EMBED_CONCURRENCY=6` · `EMBED_BATCH=32` · `BM25_THREADS=3`으로 `pipeline.transform.structure.gold_bundle` → `pipeline.load.pgvector_load load`.
  8. 기록: 작업 폴더(`ops.run_pipeline.run_pipeline_work_dir`, 비우면 스크립트 옆 `test_space/`)의 `batch_progress/` — `progress.log`(진행), `doc_<seq>.log`(문서별 파싱), `queue_depth.jsonl`([rn-02](#rn-02)), 잠금 `run_pipeline.lock`. 받기(stage) 출력은 문서 폴더 `_docflow/<seq>/stage.log` — 동시 받기끼리 섞이지 않게 문서마다 따로 쓰고, 실패하면 그 파일 끝을 progress.log에 남긴다.
- 파일: `deploy/host/scripts/run_pipeline.py`, `pipeline/cli.py`, `deploy/docker/entrypoint.sh`.
- QA: `tests/general/deploy/test_run_pipeline.py`(명령 글자·설정 대조)·`test_docs_flow.py` · 통과.
- Status: done

<a id="pl-23"></a>
## pl-23 · 새 문서만 처리, 전체 재파싱은 사람이 시작
- 이유: 핑거프린트가 바뀌어도 밤 작업이 전체 재파싱으로 시간을 넘기지 않게.
- 규칙:
  1. "새 문서" = `AI.FileStorageMap`에 있고 gold `doc`에 행이 없는 것. 키 = `s3_key` = `doc.file_path`(갱신 시각은 보지 않음).
  2. "끝난 문서" = 원천 스키마 5벌 어디든 `doc` 행이 있는 원본 키([op-17](#op-17) 규칙 15). 파싱·게시·적재에 실패한 문서는 `doc` 행이 없어 다시 고른다. 영구 뺌(`applog.except_doc_info` `skip`)도 뺀다.
  3. 끝난 문서 빼기는 `pipeline/extract/candidate_pick.py` `done_keys` 하나(읽기는 `pipeline/shared/gold_docs.py`) — 서버는 `candidate_pick list --skip-done`, PC 직접 파싱(`pipeline.cli parse --source`)은 고르기 때. PG를 한 번 읽는다. 못 읽으면 RUN_ENV가 local이 아니면 종료 4, 그 밖은 받은 목록 그대로 + 로그 한 줄. 키 = 수집 manifest의 `key`(없으면 이름).
  4. 전체 재파싱은 사람이 전체 e2e를 시작할 때만([pl-54](#pl-54)).
  5. 새벽 배치: settings.yaml `ops.nightly.nightly_start_time`(시작 HH:MM)·`nightly_max_docs`(새 문서 수 상한, 1 이상)·`nightly_stop_time`(마감 HH:MM, 시작보다 5분 넘게 뒤) — 하나라도 비면 돌지 않는다. systemd `data-pipeline-nightly.timer`(`OnCalendar=*:0/5`)가 `nightly_batch.sh scheduled`를 부르고, 시작 시각부터 5분 안이면 applog 파티션 정리(`pipe_exec.sh migrate maintain --target applog` — 실패해도 경고만, 배치는 계속) 뒤 `run_pipeline.py --start-offset 0 --skip-done --max-docs <n> --deadline <hh:mm>`. 형식 오류면 종료 2. 서비스 `TimeoutStartSec=6h`.
- 파일: `pipeline/extract/candidate_pick.py`(`done_keys`·`list_targets`·`unparsed`), `pipeline/shared/gold_docs.py`, `deploy/host/scripts/{run_pipeline.py,nightly_batch.sh}`, `deploy/host/systemd/data-pipeline-nightly.{timer,service}`.
- QA: `tests/general/deploy/test_trigger_gate.py`·`tests/server/pipeline/test_nightly_time.py`·`test_run_pipeline`(`deadline_at`) · `tests/server/pipeline/test_target_list.py`·`test_parse_pick.py` · 통과. 서버 확인 refactor.md C-72.
- Status: done

<a id="pl-54"></a>
## pl-54 · 전체 e2e — local·dev·prd, prd 전체 문서 실행은 새 `PG_SCHEMA`로
- 이유: 판 0002가 기준 스키마의 옛 표를 지우고 0.2.0은 전체 다시 적재다.
- 할 일: 전체 e2e를 local·dev·prd에서 돌린다. 전체 문서 실행은 prd에서만, 새 기준 스키마 이름(`required.pg.pg_schema`)으로. 옛 gold·`struct` 스키마는 2주 뒤 DB 담당자가 백업하고 지운다.
- 절차: [server-guide §4-8](../operations/server-guide.md#4-8-pgvector가-바뀔-때--두-경우) (나)(새 스키마에 전부 다시) · 0.2.0 때 절차 [history/deploy_0_2_0.md](../history/deploy_0_2_0.md) · 서버 확인 refactor.md C-74.
- Status: todo

<a id="pl-24"></a>
## pl-24 · `run_pipeline` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 게시가 gold를 기다리지 않고, 원본은 게시가 성공했을 때만 지운다.
- 규칙:
  1. 파싱 성공 → 게시 대기열(게시 스레드 1개 — Object Storage 업로드 + 처리 기록 파일 `publish/silver.jsonl`).
  2. 게시 성공 → 원본(staging `.bin`·`_docflow/<seq>/_source_files`) 삭제(`drop_original()` — 원본을 지우는 곳은 여기 하나, 파싱 끝 `candidate_ready.finish()`는 처리 기록·sha256만 남김) → 구조화 대기열(`ops.run_pipeline.structure.structure_workers` 스레드 — gold_bundle·pgvector_load) → `_docflow/<seq>` 삭제(`--no-cleanup`이면 남김).
  3. 파싱 실패·게시 실패 → 원본을 남기고 로그와 `applog.except_doc_info` `error`(`parse_failed`·`publish_failed`)에(gold로 안 감). 파싱 실패면 그 문서 표지(`RUN_PIPELINE_DOC`)가 붙은 컨테이너 안 프로세스를 끈다.
  4. 받기가 뺀 문서(`_docflow/<seq>/parse/_source/only.txt`가 빔 — 중복·DRM·암호, pl-02) → 파싱 없이 건너뜀(`parse_one`이 `SKIP` — 영구 뺌 기록은 받기가 `except_doc_info` `skip`에 이미 씀) → 게시 없이 원본 삭제 → `_docflow/<seq>` 삭제. gold로 안 간다. 실패가 아니다 — 끝 요약에 `건너뜀`으로 따로 세고 종료 코드를 1로 만들지 않는다(pl-18).
  5. 미리 받기(`stage_one`)는 문서마다 늘 컨테이너 `candidate_ready stage`를 부른다 — ETag 확인·같은 밤 중복 표시는 stage 안에 있고, staging 원본의 ETag가 같으면 stage가 다시 받지 않는다. 앞 실행의 `_docflow/<seq>`는 지우고 새로 만든다(seq는 실행마다 바뀜). 게시 뒤 원본 삭제(`drop_original`)는 staging `<sha1>.bin`과 그 ETag 파일 `<sha1>.etag`를 함께 지운다.
  6. gold 실패 → 게시한 silver는 그대로, 로그와 `except_doc_info` `error`(`load_failed`)에. `doc` 행이 없어 다음 `--skip-done`이 다시 고른다(파싱·게시부터 다시).
- 파일: `deploy/host/scripts/run_pipeline.py`(`stage_one`, `parse_one`, `drop_original`, `drop_temp`, `main`) · `pipeline/extract/candidate_ready.py`(`finish`).
- 비고: PC에서 `pipeline.cli parse --source rdb:csv:…`로 돌리면 `drop_original`이 없어 받은 원본(`_source_files`·`prepared`·staging `.bin`)이 남는다 — 지금은 손으로 지운다. 
- QA: `tests/general/deploy/test_docs_flow.py`(`test_doc_order_and_exit_code` 표 — 건너뜀 → 게시·원본 삭제·gold 없음·종료 0) · `tests/general/deploy/test_run_pipeline.py`(`test_parse_one_skips_stage_dropped`·`test_stage_always_calls_stage`·`test_drop_original_removes_etag` 표) · 통과.
- Status: done

<a id="pl-18"></a>
## pl-18 · `run_pipeline` 종료 코드와 겹침 잠금
- 이유: 스케줄러가 실패를 봐야 한다.
- 규칙:
  1. 종료 코드: 0 = 대상 0건·모두 끝 · 1 = 실패 문서(파싱·게시·gold) 하나라도(받기가 뺀 건너뜀 문서는 실패 아님 — pl-24) · 75 = 마감 도달(실패 없음) 또는 다른 run_pipeline이 도는 중 · 2 = 설정 문제. 실패와 마감이 함께면 1.
  2. 겹침 잠금: `flock batch_progress/run_pipeline.lock`(프로세스가 죽으면 커널이 풂). 사람이 직접 돌려도 같은 잠금.
  3. `--deadline HH:MM`: 그 시각(지금보다 이르거나 같으면 다음 날)이 지나면 새 문서를 받지 않는다.
- 파일: `deploy/host/scripts/run_pipeline.py`, `deploy/host/scripts/nightly_batch.sh`.
- QA: `tests/general/deploy/test_docs_flow.py`(`test_exit_codes`·`test_lock_blocks_second_run` — Windows는 건너뜀) · 통과. 서버 확인 refactor.md C-72.
- Status: done

<a id="rn-01"></a>
## rn-01 · 레인 정책 — 담당 레인 먼저, 공유 워커만 가져오기
- 이유: 문서마다 자원 성격이 달라 레인으로 나누고, 남는 워커는 다른 레인을 돕는다.
- 규칙:
  1. 레인 분류(받은 뒤, 결과는 `s3_key`별로 저장해 다시 씀): `run_pipeline.classify_doc`이 컨테이너 안 `pipeline/extract/doc_lane_group.py`(원본 파일·원본 이름·크기 — 제한 60초)를 부르고, 규칙은 그 파일의 `doc_lane_group()` 하나에 있다. 답이 없으면 vlm. 규칙: 확장자가 `.txt .hwpx .hwp .csv .eml .msg .html .htm .tsv .md .json .xml .log .rtf`면 light. `.pptx .ppt`면 vlm. `.pdf .docx .doc .xlsx .xls .xlsm .docm`이면 내용을 본다 — PDF는 첫 3쪽 글자가 쪽당 평균 300자 미만, 오피스 zip은 내장 그림 8개 이상 또는 합계 800,000바이트 이상, 검사 실패도 heavy → vlm. 아니면 크기 기준(`.docx .doc` 300KB · `.xlsx .xlsm .xls` 500KB · `.pdf` 1024KB 이상)이면 medium, 그 밖 light. 다른 확장자는 vlm.
  2. 워커 수: settings.yaml `ops.run_pipeline.<레인>_dedicated`(자기 레인만)·`<레인>_shared`(자기 레인 먼저, 비면 대기열이 가장 긴 다른 레인), 기본 각 1(모두 6개).
  3. `ops.run_pipeline.vlm_lane.vlm_lane_max_concurrent_docs`(기본 2): 진행 중 vlm 문서가 이만큼이면 vlm 레인을 건너뛴다(전담 워커도).
  4. 고르기 = 순수 함수 `pick_lane(own, shared, queues, inflight, vlm_cap)`.
  5. 시작 때 거부(종료 2): 값이 0 이상 정수가 아님 · `staging.staging_max_docs`·`staging.staging_workers`·`vlm_lane.vlm_lane_max_concurrent_docs`가 1 미만 · 전담과 모든 공유 워커 합이 0인 레인.
- 파일: `deploy/host/scripts/run_pipeline.py`(`classify_doc`·`RUN_PIPELINE_DEFAULTS` — 설정 모델 `pipeline.config.PipelineHostRunPipeline`와 시험이 대조) · `pipeline/extract/doc_lane_group.py`(`doc_lane_group`).
- QA: `tests/general/deploy/test_run_pipeline.py`(`pick_lane` 표·`test_classify_cache_skips_probe`) · `tests/server/pipeline/test_doc_group.py`(그룹 규칙 표) · 통과.
- Status: done

<a id="rn-02"></a>
## rn-02 · 대기열 — 진입·중간 상한과 길이 기록
- 이유: 구조화가 느리면 파싱 결과가 쌓인다(디스크·대기 시간).
- 규칙:
  1. 진입 `ops.run_pipeline.staging.staging_max_docs`(기본 20, `--staging`이 덮음): 미리 받아 둘 문서 수(받는 중 포함, 파싱 중 제외). 동시 받기 = `min(staging_workers(기본 2), 빈자리)`.
  2. 구조화 스레드 `ops.run_pipeline.structure.structure_workers`(기본 2, `--struct-workers`가 덮음).
  3. 중간 상한 `ops.run_pipeline.structure.structure_max_backlog`(비우면 구조화 스레드 × 2, 0 = 없음): 게시 대기 + 구조화 대기가 이 수 이상이면 레인 워커가 새 파싱을 시작하지 않는다.
  4. `batch_progress/queue_depth.jsonl`에 dispatch·pick·parse_end·struct_put·struct_get마다 한 줄(`pub_wait` 포함). 쓰기 실패는 무시.
- 파일: `deploy/host/scripts/run_pipeline.py`.
- QA: `tests/general/deploy/test_run_pipeline.py`(`test_struct_backlog_holds_new_parses`) · 통과.
- Status: done

<a id="rn-03"></a>
## rn-03 · MCP `parse_document`에 CPU 먼저 주기
- 이유: 일괄 파싱이 CPU를 다 쓰면 사람이 기다리는 `parse_document`가 느려진다. 컨테이너끼리는 cgroup CPU 가중치가 정한다(nice는 한 세션 안에서만).
- 규칙: `parse_document` 작업 서비스는 전용 컨테이너 `mcp-data-parsing`(같은 이미지, entrypoint `run-mcp-parsing` = `pipeline.run_mcp_parsing`, Redis Streams 소비자). 자원 = settings.yaml `ops.containers.data_parsing.data_parsing_cpus`(기본 4)·`data_parsing_mem_limit`(12g)·`data_parsing_cpu_shares`(4096 — 일괄 `data-pipeline`은 1024). worker마다 엔진 기본 수는 max(1, min(2, CPU − 1))라 worker 2 × 엔진 2 = 총 4개다(사용자 결정 2026-11-09). 4 CPU 미만 호스트는 컨테이너 CPU 상한을 낮추고 worker마다 엔진 수를 1로 적는다. cpus는 예약이 아니라 상한이며, 4 vCPU 개발 서버에서 일괄 파싱·검색 MCP와 나눌 때 cpu_shares가 우선순위를 정한다. 결과 폴더를 붙인다. 검색 MCP는 `<결과 폴더>/_mcp_parse/jobs`에 업로드 파일·job.json을 쓰고 Redis HASH+active SET+STREAM에 한 트랜잭션으로 등록한다(#113). worker는 XREADGROUP(COUNT 1)으로 가져가 파싱하고 result-<attempts>.json을 쓴 뒤 완료 HASH+LIST+TTL+active 해제+XACK+XDEL을 한 트랜잭션으로 기록한다. 프록시는 BLPOP으로 즉시 깨어나며 1초 HTTP 폴링은 없다. `mcp_parse_workers`(기본 2, 허용 1~2)만큼 spawn 프로세스를 띄우고 죽은 자식은 주 프로세스가 재시작한다. 유실 작업은 (job_timeout+60)초 뒤 XAUTOCLAIM, 최대 3회 전달 뒤 포기한다. heartbeat(10초 갱신, TTL 30초)와 Redis PING으로 건강 상태를 확인한다. health는 컨테이너 로컬 supervisor 토큰에 해당하는 소비자만 확인한다. 등록 실패 업로드는 정리하고, 수정 시간 기준 최근 10분 폴더는 active 등록 전에도 purge에서 보호한다. 죽으면 `restart`, 꺼지면 `mcp_keepalive.sh`(keepalive 타이머)가 띄운다. 일괄 엔진 자식은 nice +10.
- 측정: 작업마다 새 `pipe_run(command=mcp_parse, args에 job_id)` 1건과 `pipe_event(stage=mcp_parse.job)` 1행을 남긴다. 파일 이름·확장자·바이트·동시 실행 수, `metrics.job_id`·`queue_wait_ms`·제출 때 앞 작업 수(`queue_position`)·mode·scan·빈 결과 note를 기록하고 자식 단계는 같은 run_id를 잇는다. 실패·시간 초과도 기록하며 worker는 다음 작업을 계속한다. `perf_report --mcp [--since 시간]`과 `mcp_log.result_keys.job_id` 조인으로 응답·대기·파싱 시간을 비교한다([서버 가이드 §3-4-1](../operations/server-guide.md#3-4-1-mcp-파싱-작업-성능)).
- 파일: `common/store/redisq.py`, `mcp_server/services/parse_proxy.py`, `pipeline/run_mcp_parsing.py`, `deploy/host/compose/{compose.redis.yml,compose.data-parsing.yml,compose.mcp-server.yml}`(개발 서버 앱 코드 짝은 그대로), 호스트 `host_ctl.sh`·`mcp_keepalive.sh`·`load_settings.sh`. Redis는 AOF everysec, 루프백 bind. 기동은 Redis → worker → MCP.
- QA: `tests/server/common/test_redisq.py`(원자성·상한·순번·TTL), `tests/general/pipeline/test_parse_redis.py`(실 Redis 완료·죽은 소비자 회수), `tests/general/deploy/test_compose.py` · `tests/server/pipeline/test_parse_svc.py`(작업별 자식 run_id·성공·실패·timeout·VLM 미설정) · `test_perf.py`(순수 집계·DB 읽기·대체 파일) · 통과.
- Status: dev — 서버에서 일괄 파싱 중 `parse_document` 응답 시간 확인(refactor.md C-83 ①)만 남음.

<a id="rn-04"></a>
## rn-04 · MCP 업로드 중 medium 전담 워커 쉬기
- 규칙: 5초마다 `mcp_busy()` — 작업 폴더(`<결과 폴더>/_mcp_parse/jobs` — 고정) 아래 이름 날짜(`<YYYYMMDD>-…`)가 어제·오늘·내일인 폴더만 보고, 30초 안에 바뀐 파일이 있으면 바쁨. 바쁘면 medium **전담** 워커가 새 문서를 집지 않는다. 폴더가 없으면 감지를 끄고 안내 한 줄. 레인 워커 수는 `ops.run_pipeline.*` 칸.
- 파일: `deploy/host/scripts/run_pipeline.py`.
- QA: `tests/general/deploy/test_docs_flow.py`(medium·vlm 레인, vlm 동시 상한, MCP 양보, `mcp_busy` 표) · 통과.
- Status: done

<a id="rn-05"></a>
## rn-05 · run_pipeline은 지휘만 — 판단은 파이프라인 함수, PC도 run_pipeline으로
- 이유(사용자 11-04): 같은 판단이 서버 러너와 파이프라인 두 곳에 있으면 어긋난다. PC E2E가 서버와 다른 길을 타면 PC 결과가 서버를 증명하지 못한다.
- 요건(되어야 할 모습):
  1. 서버 러너 `run_pipeline.py`는 지휘만 한다 — 레인·워커·임시 폴더 관리와 컨테이너 안 파이프라인 명령 호출(`docker exec`). 원천 목록 읽기, 끝난 문서 빼기, 중복, 레인 판정, FAQ 교체 판단, 게시 판단은 파이프라인(extract·transform·load) 함수가 한다.
  2. 대상 목록은 컨테이너 명령 하나 `python -m pipeline.extract.candidate_pick list`가 만든다 — EDW `FileStorageMap`에서 이름 키워드(`--filter`)·파일 크기 오름차순(크기 없는 행 뺌), `--start-offset`·`--limit`·`--seqs`, `--skip-done`이면 끝난 문서(gold `doc` 행 — `done_keys()` 한 곳)와 영구 뺌(`except_doc_info` `skip`)을 빼고, FAQ를 앞에(교체를 마친 키 `<결과 폴더>/_faq_seen.txt`), 앞 `--max-docs`개. 결과는 목록 파일 `--out`(JSON `total`·`start`·`docs`[`seq`·`id`·`s3_key`·`original_filename`·`file_size`·`source_system`])이고 러너는 그 파일만 읽는다. 러너의 이 호출 시간 제한(2400초)은 안쪽 FAQ 맞추기 시간 제한(`candidate_pick` — 1800초)보다 길다(안쪽이 먼저 끊겨 원인이 로그에 남음). EDW 접속은 `mssql`을 다시 쓴다.
  3. 원본 받기는 한 길이다 — `python -m pipeline.extract.candidate_ready stage`가 문서를 `_staging/`(`extract.source.source_staging_dir`)에 한 번 받고, 같은 실행에서 바로 중복 제외(받은 파일 SHA-256 — 같은 묶음·gold에 끝난 다른 원본, pl-02)와 형식·DRM·암호·미지원 거르기(`filter_and_rotate`)를 이 순서로 한다. 살아남은 문서만 파싱하고, 파싱(`parse --staged`)은 받아 둔 파일만 읽는다 — 받지 못한 문서는 파싱 실패, 받기가 뺀 문서(중복·DRM·암호)는 건너뜀이고 받기가 `except_doc_info` `skip`에 쓴다(pl-24). DRM 문서는 표시만 하고 건너뛴다(처리 단계 없음). 회전은 기본 꺼짐 그대로다. 원본은 게시가 성공한 뒤 `drop_original()`만 지운다(pl-24).
  4. PC(`RUN_ENV=local`)도 같은 `run_pipeline`로 E2E를 돈다 — 가짜 대상만(EDW sqlite·`file://` 게시 폴더·상대 경로, op-14). PC만의 분기는 접속 대상을 고르는 한 곳이다.
  5. 커밋 전 점검 스크립트는 점검 도구 자리 `common/check/`에 있다(`.githooks/pre-commit`·CLAUDE.md §5-2·README가 그 경로를 부른다).
- 비고(현재와 다른 점, 11-05 확인):
  - `configure()`가 `run_env`가 dev·prd가 아니면 거부하고, CLAUDE.md §4가 "run_pipeline은 PC에서 실행하지 않는다"고 적는다 — PC는 `python -m pipeline.cli parse`를 바로 부른다. 바꾸는 것은 등급 A(운영 접속 가드).
  - 점검 스크립트가 `deploy/release/lint_changed.sh`에 있다.
- QA: 바꾸기 전후 같은 문서 묶음의 결과(대표 결과·gold `doc` 처리 기록·게시 파일)가 같음 · 대상 목록 고르기 사례 표 `tests/server/pipeline/test_target_list.py`(키워드·크기순·시작 자리·골라 돌리기·끝난 문서·FAQ 교체·max-docs) · 받기·중복·거르기 `tests/server/pipeline/test_stage_batch.py`·`test_candidate.py::test_stage_batch` · PC에서 run_pipeline 한 번으로 gold 대역 `doc` 행과 `file://` 폴더 결과가 생김.
- Status: todo

<a id="rn-06"></a>
## rn-06 · 같은 일은 한 곳, 파일 이름은 하는 일로
- 이유(사용자 11-04): 같은 일을 하는 코드가 여러 곳에 있으면 한쪽만 고쳐져 어긋난다. 이름만 보고 하는 일을 알 수 있어야 한다.
- 요건(되어야 할 모습):
  1. 범위는 저장소 전체(`pipeline`·`common`·`mcp_server`·`deploy/host`·`deploy/release`·`validation`). 보호 파일(엔진 폴더, `common/core/{contract,repfmt,terms,text}.py`)은 이 규칙으로 고치지 않는다.
  2. 같은 일을 하는 코드는 한 벌이다 — 파싱 단계 사슬(준비 → 엔진 → 채점 → 대표 결과)과 프로세스 묶음 실행은 `pipeline/parse_steps.py` 하나를 `pipeline.cli parse`와 MCP 작업 서비스 `pipeline.run_mcp_parsing`가 함께 쓴다. 검색 MCP의 날짜 조건 해석(`_when`)도 한 벌.
  3. 서버·릴리스 스크립트 이름은 하는 일이다 — `host_ctl.sh`·`nightly_batch.sh`(새벽 배치만)·`pipe_exec.sh`(parse·publish 등 컨테이너 명령)·`mcp_keepalive.sh`·`in_container.sh`·`prune_images.sh`·`load_settings.sh`·`settings_to_env.py`·`host_settings.tsv`, `deploy/release/{bake_prod_image.sh,stage_images.sh,gen_host_keys.py}`. compose 호출은 서비스마다 자기 compose 파일만 쓴다. 예외: `load.sh`(이미지 저장소에 같은 이름), `assets.py`(Dockerfile이 복사 — 이름을 바꾸면 새 이미지), systemd 단위 이름.
  4. 저장소 안에서 같은 파일 이름을 두 번 쓰지 않는다(엔진 파일·앱마다 `config.py`·지시서 `agent.py` 예외 — CLAUDE.md §1).
  5. 공용 모듈(`common/**`)과 `pipeline/shared/**`는 이 규칙으로 이름·자리를 바꾸지 않는다(레이어 코드 핑거프린트 유지). 파이프라인 폴더 배치는 [rn-08](#rn-08).
  6. 스캔 PDF 규칙 둘은 목적이 달라 따로 둔다 — 레인 분류 `doc_lane_group`(앞 3쪽 평균 300자 미만)·엔진 선택 `pdf_kind`(쪽당 평균 20자 미만). 각 자리에 역할 주석.
  7. run_pipeline은 EDW를 읽지 않는다 — 문서 목록·끝난 문서·FAQ 순서는 컨테이너 안 `candidate_pick list` 한 곳([rn-05](#rn-05)). 호스트에 남은 사본은 staging 파일 이름 규칙 하나이고 컨테이너 쪽과 같은지 시험으로 견준다(`test_run_pipeline.py::test_staging_name_same`).
- QA: 바꾸기 전후 같은 문서 묶음의 대표 결과·gold `doc` 처리 기록·게시 파일이 같음 · selftest·pytest 기준선 유지 · `check_modules` 통과.
- Status: done

<a id="rn-07"></a>
## rn-07 · 서로 덮지 않는 여러 벌, 적은 설정 칸, 목적만 적은 주석
- 이유(사용자 11-05 점검): 개발 서버에 여러 벌이 EDW·게시·포트·스키마를 함께 쓰면 서로 덮는다. 같은 값 칸·늘 같은 스위치·옛 칸 표는 설정을 읽기 어렵게 한다.
- 요건(되어야 할 모습):
  1. 여러 벌은 코드 폴더 이름 끝 벌 번호로 컨테이너 이름이 갈린다([op-15](ops-settings.md#op-15)) · 포트는 기본값 그대로면 시작 거부 · `prd`에서 번호가 붙은 폴더면 시작 거부. PG 스키마·EDW 기록 표·게시 경로·버전에는 벌 표시를 붙이지 않는다.
  2. 파싱 MCP는 컨테이너·서비스·compose 파일 `mcp-data-parsing`, 설정 칸 `data_parsing`(env `DATA_PARSING_*`). 파싱 포트와 프록시 주소는 한 칸, 토큰은 `tokens.mcp` 하나.
  3. `run_pipeline.py`가 컨테이너 명령에 붙이는 `--set` 값(VLM 동시 수·워커 수 등, vlm 레인 값 포함)은 `ops.run_pipeline.*` 칸에서 온다(비우면 그 칸 기본값).
  4. 늘 같은 값인 스위치 칸과 옛 칸 표는 없다. VLM 동시 수 칸은 둘(`common.models.vlm.vlm_requests_per_doc`·`vlm_max_total_requests`). 옛 칸이 남은 settings.yaml은 시작 거부.
  5. 스캔 PDF 판정은 `pdf_kind` 하나(그림 VLM의 스캔 쪽 판정도).
  6. 쓰지 않는 코드·한 곳만 쓰는 감싸기는 없다. 주석은 목적 한 줄(이력은 git·`docs/history`).
- QA: selftest·pytest 기준선 유지(벌 번호 → 포트 거부, prd 거부 시험) · `check_modules`·`keyscan --check`·`sample --check`·`gen_host_keys --check` 통과 · 저장소 전체 ruff·mypy 0 · 옛 이름(`data-pipeline-mcp`·`parse_mcp`·`PARSE_MCP_`) 0건(docs/history 제외).
- Status: done

<a id="rn-08"></a>
## rn-08 · 파이프라인 폴더는 ETL 뜻대로, 파일 이름은 하는 일로
- 이유(사용자 11-05): 폴더만 보고 그 단계가 무엇을 하는지 알 수 있어야 한다. 엔진으로 글자를 뽑는 일은 정제(transform)이고, 그 결과가 silver다.
- 요건(되어야 할 모습):
  0. 층 이름: **staging** = Object Storage 원본을 임시 폴더로 받아 둔 것(원본은 이미 Object Storage에 있어 따로 보관하지 않음 — extract의 결과) · **silver** = 엔진별 파싱 결과 `parse/<엔진>/<문서>.json`과 대표 결과(transform의 첫 결과 — 실제 엔진 추출은 모두 transform) · **gold** = 검색용 묶음과 pgvector 적재.
  1. `pipeline/extract` = 원본을 고르고 받아 파싱 입력으로 준비하는 일만 — 대상 고르기(목록 − 끝난 문서, 받기 전) `candidate_pick.py`, 미리 받기·받기 `candidate_ready.py`, 같은 파일 정리 `deduplication.py`, 형식 거르기·회전 `filter_and_rotate.py`, 레인 나누기 `doc_lane_group.py`(엔진을 돌리지 않음 — 형식·크기·앞 3쪽 글자 수), 원천 열 찾기 `discover_columns.py`.
  2. `pipeline/transform/parse/` = 엔진 파싱 — 엔진 `engines/`(보호 파일), 엔진 준비 확인 `engine_check.py`, 엔진 실행은 한 파일(엔진마다 자식 프로세스로 분리), 엔진 버전·캐시 키(`engine_version`·`p0_key`·`engine_code_fp`)와 캐시 지우기. 그 뒤 `represent`(대표 결과) → `figures`(그림) → `structure`(gold 묶음 `gold_bundle.py`).
  3. `pipeline/shared`의 파일은 한 가지 일만 하고 이름이 그 일이다(원본 캐시·실패 단서·`pdf_kind` 각각). 한 단계만 쓰는 것은 그 단계 폴더에 둔다(차트 글자 → figures), 여러 단계가 읽는 설정 해석은 `pipeline/config.py`(후처리 스위치 `active_features` — represent·figures).
  4. 요건 행에 닿지 않는 코드(부르는 곳이 없거나 시험만 부르는 함수, 쓰지 않는 설정 칸·반환 칸)와 같은 일을 하는 두 번째 코드는 두지 않는다. `rep.meta`와 `parse_document` 출력(MCP 계약)은 그대로.
- 비고(남은 것, 11-05):
  - 보호 파일 `common/core/contract.py`의 설명 글에 옛 이름 `build_bundle`이 남음(핸드오프 지문 때문에 그대로).
  - 엔진 폴더를 옮겨 엔진 핑거프린트(상대 경로 포함)와 code_fp가 바뀜 — 기록용([test.md#e2-02](test.md#e2-02), 재처리는 gold `doc` 행으로만). 사람 검토 필요.
  - 이번에 하지 않음: 그림 부가 기능(pl-05), 글자 파싱 뒤 레인 나누기.
- QA: selftest·pytest 기준선 유지 · `check_modules`·`keyscan --check`·`sample --check` 통과 · 저장소 전체 ruff·mypy 0 · FINGERPRINT 그대로 · 비고의 옛 이름(`extract/engines`·`engine_stack`·`run_one_engine`·`fetch_docs`·`build_bundle`) 0건(docs/history 제외).
- Status: done

<a id="pl-27"></a>
## pl-27 · 프로세스 종료 정리 — 임시 설정 파일·PID 기록 지움, 자식 회수
- 이유: 덮기 설정 파일(`settings-*.yaml`)이 임시 폴더에 쌓이고, 시간 초과로 끝낸 자식의 손자가 좀비로 남았다.
- 규칙(`common/core/exitclean.py` 한 곳):
  1. `remove_at_exit(경로)` — 이 프로세스가 끝날 때(정상·오류·SIGTERM) 지운다. `track(Popen, group)` — 끝날 때 아직 돌면 끝내고 `wait`로 회수. `stop(p, group)` — POSIX는 (묶음째) SIGTERM → 10초 → SIGKILL, Windows는 `taskkill /T`.
  2. import 때 SIGTERM 처리기를 단다(기본 처리기일 때만): 바로 정리한 뒤 `SystemExit(143)`. 정리 중 두 번째 SIGTERM은 무시. 순서: 자식 전부 SIGTERM → 10초 → 남은 것 SIGKILL·회수 → 파일 지움. 정리를 시작한 뒤 띄운 자식은 바로 끝낸다.
  3. 파일 주인: `settings.put`·`child_env`의 덮기 파일 = 만든 프로세스 · `settings.isolated` = 블록 끝 · `--set`(`setarg` — POSIX는 `execve`로 다시 뜸) = 다시 뜬 프로세스.
  4. 연결: `resources.gated_popen`(파이프라인 자식 전부), `resources.kill_group`(→ `stop(group=True)`), `run_mcp_parsing` 작업 자식과 PID 기록 `service.json`.
  5. 한계: `subprocess.run`의 짧은 자식은 추적 안 함 · 주 스레드가 아닌 곳에서 처음 import되면 SIGTERM 처리기 없음 · SIGKILL·OOM은 정리 못 함 · 컨테이너 PID 1 고아 회수는 compose `init: true`.
- 파일: `common/core/exitclean.py`, `common/config/{settings,setarg}.py`, `common/core/resources.py`, `pipeline/run_mcp_parsing.py`.
- QA: `tests/server/common/test_exitclean.py`(SIGTERM·`--set` 사례는 POSIX만) · 통과. 서버 확인 refactor.md C-68.
- Status: done

<a id="op-03"></a>
## op-03 · EDW 접속 하나, 읽기 계정만
- 이유: FileStorageMap·RDB 원천 표·`query_edw`가 같은 EDW 서버·DB에 있다. 이 프로젝트는 EDW에 쓰지 않는다([op-17](#op-17) 규칙 18).
- 규칙:
  1. 벡터는 pgvector에만, EDW에는 넣지 않는다.
  2. 접속 블록 하나 — settings.yaml `required.edw`(`edw_host`·`edw_port`·`edw_database`·`edw_read_user`·`edw_read_password`, 모델 `common.connections.rdb`). 서버는 접속 칸을 채우고, PC는 아무것도 채우지 않는다(가짜 EDW — 5). 드라이버는 pymssql만(`common.store.mssql.login(role)`).
  3. 읽기 계정: RDB 원천 목록·discover·고객 목록·FileStorageMap·`run_pipeline.py` 읽기·MCP 전부. 쓰기 계정 칸은 없다 — `mssql.login()`은 읽기 계정만 낸다(질의 도구 `query_edw` 계정에 쓰기 권한을 두지 않음 — 사용자 11-05).
  4. PC 대역: `dev.local.local_edw_sqlite_file`의 sqlite 파일 하나(비우면 `valid_env/edw/edw_copy.sqlite` — 없으면 `valid_env/edw/edw.sqlite`를 복사, 원본 생성: `python -m validation.e2e.edw_standin`, `local`에서만 열림)를 `AI`·`CRMS`·`LAS`·`SFDC` 별칭으로 ATTACH(`mssql.standin`, 기본 읽기 전용). `query_edw`는 읽기 전용으로 연다.
- 파일: `common/store/mssql.py`, `common/config/settings.py`.
- QA: `tests/server/common/test_edw_login.py`·`tests/general/common/test_edw_standin.py` · 통과.
- Status: done

<a id="pl-11"></a>
## pl-11 · 모델 호출, 비용, 외부 전송 가드(공용)
- 이유: 폐쇄망 서버는 외부 모델을 부르면 안 되고, PC 호출은 싸게 유지해야 한다.
- 규칙:
  1. OpenAI 호환 역할 llm·vlm·embed. 서버(dev·prd)는 외부 모델을 거부한다. 외부 전송은 `<PREFIX>_ALLOW_EXTERNAL`이 켜지고 `RUN_ENV=local`일 때만. 개발 서버부터 내부망 모델, PC는 OpenRouter.
  2. 하루 지출 상한 `dev.models.guard.daily_budget_usd` 기본 0.1달러 — 외부 모델 호출의 하루(현지 날짜) 합계. 비운 칸은 기본값.
  3. 장부: 날짜마다 파일 하나 — `spend_ledger_file`이 있으면 이름 뒤에 날짜(`spend.json` → `spend-<날짜>.json`), 비우면 `<저장소>/output/_llm_spend/<날짜>.txt`. 같은 작업 폴더의 모든 프로세스가 파일 잠금으로 합계 하나를 나눠 쓴다. 정산·반환은 선차감한 날의 장부로 간다. 시험 자식(`case_env`)은 임시 장부.
  4. 외부 LLM은 단가(`PRICES` 또는 `LLM_PRICE_IN·OUT`)를 모르면 거부한다(`llm.chat`·`admit_turn` 같음). 한 번의 호출이 사후 정산으로 상한을 조금 넘을 수 있고, 다음 호출부터 거부된다.
  5. 응답 캐시, RPM, 시험용 가짜 LLM(`dev.fake_llm` — local만).
  6. 역할마다 설정 `dev.models.<llm|vlm|embed>.allow_external` 하나로 외부 허용을 정한다 — `llm.chat`을 부르는 모든 곳(분류 포함)이 `LLM_ALLOW_EXTERNAL`을 따른다(호출 인자 `allow_external=True`는 같은 효과). 내부망 서버(dev·prd)의 settings.yaml은 셋 다 `false`. 시험: `tests/server/common/test_llm.py`(local+1 허용 · local+없음 거부 · dev·prd+1 거부).
- 파일: `common/ai/guard.py`, `common/ai/llm.py`, `common/config/settings.py`.
- QA: `tests/server/common/test_guard.py`·`test_llm.py` · 통과. 서버 확인 refactor.md C-88.
- Status: done

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록과 DB 로그(두 앱)
- 이유: 두 앱의 사건·감사·성능 기록을 같은 형식으로 남긴다.
- 규칙 — JSON 줄:
  1. `common/core/jsonlog.py` `setup(app)` — 한 줄 키 `time, level, app, event, msg, request_id, run_id, span_id, duration_ms, err`. logger 이름 `applog.<앱>`. PC 기본 `logs/<앱>.jsonl`, 서버 stdout. 설정 `ops.log.log_level`(기본 INFO)·`ops.log.log_json_dir`. contextvars ID는 `settings.child_env()` 내부 신호로 자식에 전파.
  2. 비밀값 가림은 `jsonlog.masked(value)` 한 곳 — 라벨 패턴과 settings `SecretStr` 칸 값(4자 이상은 부분 문자열, 1~3자는 토큰 경계에서만). JSON 줄·sink·MCP args/result/err가 같은 함수를 쓴다.
  3. `err`는 allowlist — 예외 타입 이름(+errno 이름·CalledProcessError 종료 코드)과 `span.safe(...)` 고정 문구만. 외부 예외 문자열 원문은 남기지 않는다.
  4. dev·prd 시작 관문: 비어 있지 않은 비밀 설정이 8자(`MIN_SECRET_LENGTH`) 미만이면 칸 경로만 알리고 종료 2.
  5. MCP SDK 줄(`mcp.*`)은 stderr JSON으로만. 요청마다의 INFO는 `ops.log.log_level=DEBUG`일 때만. stdio 모드의 stdout은 JSON-RPC 전용.
- 규칙 — DB(`applog` 스키마, Alembic 갈래 `applog` — `common/store/db/migrations/versions/0001_applog_base.py`):
  1. 표: `mcp_log`(월 파티션, 키 `requested_at`) · `pipe_event`(월 파티션, 키 `ts_start`) · `pipe_run`(`run_id` PK, 시작 running → 종료 UPSERT). applog는 여러 벌이 함께 쓰므로 문서 사건(`doc_id` 있음) 행은 원천 `source_system`(판 `0004_applog`)을 채우고 빈 `ext`·`file_bytes`를 메운다(원천·크기는 이번 실행 manifest, 확장자는 이름 — 그 밖의 사건은 `source_system` NULL · 시험 `test_span_soft.py` `DOC_COLS`).
  2. `common/store/logsink.py` `emit(table,row)` → 제한 큐(`tuning.ops.log.log_queue_size` 10000, 차면 즉시 버리고 `dropped`) → 배치 INSERT(`log_batch_size` 200 · `log_flush_sec` 1 · `log_db_timeout_sec` 2). DB 실패면 `ops.log.log_fallback_dir`(기본 `output/logs`) jsonl, 프로세스당 경고 한 번. 파일 로그는 이 예비 한 곳뿐이다 — 실행 출력은 컨테이너 로그(서버 stdout), 실행 기록 파일(`RUNLOG.md`·`runlog.jsonl`·`logs/<시각>_<도구>.log`)·질의 기록 파일은 없다(op-13). 종료 flush는 `log_shutdown_sec` 5초 안.
  3. 켜기 `ops.log.log_db_enabled` — 서버(두 이미지) 기본 true, PC 기본 false(op-13). 서버는 새 코드를 띄우기 전에 `migrate up --target all`(applog 포함). 보존 `log_retention_days` 90. `dbtool up --target applog`(현재 달 + 2개월 준비), 매일 `dbtool maintain --target applog`(다음 달 준비·만료 파티션 DROP·`pipe_run` DELETE — 서버는 새벽 배치가 run_pipeline 앞에 부름, [pl-23](#pl-23)). sink는 DDL을 하지 않는다.
- 규칙 — MCP 감사(`mcp_server/services/call_log.py`):
  1. 도구 호출마다 `applog.mcp_log` 한 행 — 성공·도구 오류·busy·timeout·HTTP 인증 거부(rpc_method NULL), initialize(rpc_method=initialize, clientInfo 뺌). 칸은 [db_schema.md §6](../architecture/db_schema.md). sink 실패가 도구 응답을 바꾸지 않는다.
  2. 본문: 마스킹 뒤 앞부분만 — 입력 `tuning.search.audit.audit_max_input_bytes` 16384 · 출력 `audit_max_output_bytes` 65536. 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)는 출력 본문 대신 `result_keys` 요약만 저장한다(원문은 싣지 않음). `*_bytes`·`result_sha256`은 자르기 전 전체 응답 기준. 행 전체의 가림은 sink(`logsink.emit`)가 한 번 한다(본문은 자르기 전에 가림). `parse_document`의 `content_b64`는 디코딩한 파일 sha256·바이트 수로 바꿈.
  3. `result_keys`: search = chunk_keys(순위 순)·evidence_status·filter·scope_docs · list_doc_fulltext = 건수·next_cursor·doc_keys · get_doc_fulltext = 건수와 파일별 name/kind/size/sha256/skip_reason · query_edw = row_count·columns · parse_document = job_id·engine·rep_path·text_chars · edw_meta = 단계·표·칸 수.
  4. 컨텍스트: `X-MCP-User`(없으면 `params._meta.user`) → knox_id, `X-MCP-Client`는 호출자 표시·콘솔 로그에만 쓰고 DB에는 남기지 않음(agent_id는 인증 체계가 생긴 뒤), Mcp-Session-Id(stateless라 도구 행은 대개 null). 유효한 UUID `X-Request-Id`는 그대로, 아니면 새 UUID를 응답 헤더로. 접속 소켓 주소는 client_ip에 남기고(사용자 11-04, 프록시 뒤면 프록시 IP) clientInfo는 남기지 않는다.
  5. 감사는 전용 데몬 스레드 하나가 처리한다(도구는 기다리지 않음). 본문 대기 큐 64건 + 바이트 합계 `tuning.search.audit.audit_max_queue_bytes`(기본 268435456) — 넘으면 본문 없는 메타 행(`result_keys.audit_body_omitted=queue_full`, `error_code=audit_queue_full`).
- 규칙 — 파이프라인 추적:
  1. 실행 1건 = `pipe_run`(`pipeline/shared/runtrace.py` — code_fp·stack·settings_hash·문서 수·workers·cpu_max_load·mem_start_pct). 부모가 준 run_id가 있는 자식은 새로 시작하지 않는다. run_pipeline에서는 문서·단계마다 실행이 따로 생긴다.
  2. 문서×단계 = `pipe_event`(`common/core/span.py` `with span("extract.parse", doc_id=…) as s`) — 단계 이름 `extract.plan`·`extract.parse`(`attempt` — 시간 초과 재시도면 2)·`extract.shard`·`extract.staging`(미리 받기 1회)·`extract.classify`(run_pipeline 레인 분류 1건 — `pipeline.extract.doc_lane_group.main()`, `metrics.group`, 파일이 없으면 fail)·`extract.download`(파일=문서 1건 — `metrics`에 `head_ms`·`download_ms`·`mbps`(순수 전송)·`lock_wait_ms`, 실패는 `external`)·`extract.skip`(중복·DRM·암호·미지원으로 건너뛴 문서 1건 — `status=skip`, `err_kind=doc`, `metrics.reason`·`dup_of`, pl-02)·`transform.represent`·`transform.figures`·`transform.structure`·`embed.bundle`·`load.pgvector`·`load.doc/chunk/chunk_term/stats`·`load.publish`·`proc.run`·`model.<role>`(모델 호출 1건당 1행 — `layer=model`, 부모는 호출한 단계 span, `doc_id`는 부모에서 이어받음, `metrics`에 토큰 수. 성공·실패 모두). 오류는 `status`·`err_kind`(env/timeout/doc/external/db).
  3. 60초마다 `stage='run.progress'`(완료/전체·docs/min·남은 시간·부하·메모리, 임베딩 중에는 unit=chunk).
  4. `run_id`가 없으면(MCP 검색·시험) span은 아무것도 하지 않는다. 계측 안의 예외는 삼키고 업무 결과를 바꾸지 않는다(프로세스당 stderr 경고 한 번).
  5. `cpu_ms`·`rss_peak_mb`는 Linux에서 프로세스에 하나만 도는 span만 채우고, 겹치거나 측정 못 하면 NULL.
  6. 분석: `python -m pipeline.tools.perf_report [<run_id>] [--since <시간>] [--top N] [--compare <run_id>…] [--runs] [--file output/logs/*.jsonl]` — 읽기 전용.
     다운로드(`extract.download`)는 `--since` 요약에 ■ 다운로드 표(크기 구간별 순수 전송 mbps·head·잠금 대기)로 나온다. 서버에서는 `docker exec data-pipeline python -m pipeline.tools.perf_report --since <시간>`으로 본다.
  7. MCP 파싱 작업([rn-03](#rn-03)): 작업 1건 = `command=mcp_parse` 실행 1건(args에 job_id), 전체 작업 span `mcp_parse.job`의 열 `doc_id`·`ext`·`file_bytes`·`inflight`, metrics `job_id`·`queue_wait_ms`·`queue_position`·`mode`·`scan`·빈 결과 `note`. 예외 분류는 fail/timeout, VLM 미설정 빈 결과도 ok로 기록한다. 덮기 파일 캐시에는 컨텍스트를 넣지 않고 작업마다 자식 env에 현재 run/span을 싣는다. `perf_report --mcp [--since 시간] [--top K] [--file 파일…]`(기본 24시간)은 건수·실패·timeout, 전체(대기+파싱)·큐 대기·파싱·엔진/채점/대표 결과 단계 벽시계 시간 p50/p95/최대, 느린 작업 job_id·파일·대기·파싱을 DB와 대체 파일에서 같은 순수 함수로 집계한다. 진행 중 실행은 시간 표에서 제외하며, 실행하지 않은 단계는 0으로 채우지 않는다. `mcp_log` 조인 예시는 [서버 가이드 §3-4-1](../operations/server-guide.md#3-4-1-mcp-파싱-작업-성능).
- 파일: `common/core/{jsonlog,span,exitclean}.py`, `common/store/logsink.py`, `mcp_server/services/call_log.py`, `pipeline/shared/runtrace.py`, `pipeline/run_mcp_parsing.py`, `pipeline/tools/perf_report.py`, `pipeline/extract/{doc_lane_group,candidate_ready}.py`.
- QA: `tests/server/common/test_{jsonlog,logsink,span,span_soft,call_event}.py`·`tests/server/mcp/test_call_log.py`·`tests/server/pipeline/test_{runtrace,perf,span_stages,doc_group,parse_svc}.py`·`tests/general/common/test_applog_pg.py`(PC 임시 PG 스키마) · 통과. 서버 적용 refactor.md C-79·C-80·C-83 ①.
- Status: done

<a id="rn-09"></a>
## rn-09 · 서버 러너 명령 정리

### 무엇·왜
명령마다 env가 다르면 같은 코드가 다르게 돈다. 시간 초과 뒤 남은 프로세스는 다음 문서와 CPU·메모리를 다툰다.

### 규칙
1. `run_pipeline.py`의 컨테이너 명령(목록·받기·파싱·게시·구조화·분류)은 도우미 하나가 만든다 — `docker exec`·`umask`·작업 폴더·`PYTHONPATH`·라이브러리 env가 모두 같다.
2. 게시·구조화가 시간 초과면 → 파싱처럼 그 문서 표지를 가진 컨테이너 안 프로세스를 끈다.
3. 벌 번호(코드 폴더 이름 끝 `-<숫자>`) 규칙은 한 곳이다.
4. 스캔 문서 회전 정책은 설정 칸 하나를 컨테이너 안 거르기가 직접 읽는다(명령 인자로 여러 겹 전달하지 않음).
5. 레인 분류는 받기 단계 안에서 한다(문서마다 따로 `docker exec` 없음). 분류 캐시는 줄을 덧붙여 쓴다(문서마다 파일 전체를 다시 쓰지 않음).

### 비고(지금 코드와 다른 점)
- 규칙 1·2는 반영했다(컨테이너 명령 = `run_pipeline.pexec` 한 곳 · 파싱·게시·구조화가 실패·시간 초과면 `doc_sh`가 그 문서의 `sweep_cmd`). 남은 것은 규칙 3~5(아래).
- 스캔 회전 값이 run_pipeline → `stage --no-scan-rotate` → `stage_batch(scan_rotate)` → `filter_and_rotate --no-scan-rotate` 네 겹으로 전달된다.
- 분류는 문서마다 `docker exec`(`classify_doc`), 캐시(`docflow_class.json`)는 문서마다 통째로 다시 쓴다.

### QA
- 규칙 1·2: `tests/general/deploy/test_run_pipeline.py` — 명령 줄 표에서 모든 명령의 앞부분(env)이 같음(`test_one_env_for_every_command`) · 파싱·게시·구조화 실패·시간 초과 사례 → 정리 명령이 불림(`test_failed_stage_sweeps_doc`) · 통과.
- 정할 것(규칙 3~5): 벌 번호 규칙 한 곳 · 스캔 회전 설정 칸 하나 · 받기 안 분류·덧붙이는 캐시.
- Status: todo

<a id="rn-10"></a>
## rn-10 · 문서 1건의 반복 비용

### 무엇·왜
문서 수천 건에서 같은 일을 되풀이하지 않는다.

### 규칙
1. 원본 sha256은 문서마다 한 번 구하고 다음 단계는 그 값을 쓴다(중복 제외 → 거르기 → 게시 → 구조화).
2. 적재(`pgvector_load`)의 스키마 확인 질의는 원천 스키마 5벌을 한 질의(UNION)로 묻는다.
3. 설정 파일(settings.yaml)은 프로세스마다 한 번 읽는다.
4. `--set` 처리(`setarg.apply`)는 무거운 import 전에 한다.

### 비고(지금 코드와 다른 점)
- sha256은 받기가 한 번 구해 manifest에 두고 중복 제외·거르기·파싱(`parse_engines` 조각·작업 열쇠)·구조화(`gold_bundle`)·게시가 그 값을 쓴다(`pipeline/shared/srcsha.py` — 같은 파일일 때만). 대표 결과(`contract.source_record`)만 아직 프로세스에서 한 번 다시 구한다 — 핸드오프 파일(`contract.py`)이라 고치려면 사람 검토. `pgvector_load`가 원천 스키마마다 따로 묻는다.
- 아직 재지 않았다 — 줄일 크기는 `python -m pipeline.tools.perf_report`로 먼저 잰다.

### QA
- 정할 것: 같은 문서 1건 실행의 `pipe_event` 단계 시간 비교(`perf_report --compare`).
- Status: todo

<a id="op-16"></a>
## op-16 · 개발 작업 공간 — 이미지의 개발 도구·opencode(선택)

### 무엇·왜
개발 서버 컨테이너 안에서 바로 코드를 고치고 시험한다(사용자 11-05). opencode는 파이프라인이 부르는 프로그램이 아니라 개발자가 쓰는 선택 도구다.

### 규칙
1. 개발 도구는 Dockerfile `base` 단계에 있어 네 이미지(`data-pipeline-runtime`·`mcp-server-runtime`·`data-pipeline`·`mcp-server`)가 모두 담는다 — apt(openssh-server·git·curl·ripgrep·sqlite3·tini·tmux·vim 등) + pip `uv` + `requirements-dev.txt`(PC 개발 도구와 같은 판). 의존성 지문(`DEPS_HASH`)은 requirements-core·image만 본다(그대로).
2. opencode 실행 파일은 `assets/opencode/opencode`(git 밖 — `assets.py pack`이 `<ASSET_SRC>/dl/opencode`에서 채움). 없으면 opencode 없이 빌드(`ALLOW_NO_ASSETS=1`). 이미지 env로 외부 모델 목록 받기·자동 업데이트를 끄고, 설정 틀(`deploy/docker/devbox/opencode.json`)은 내부망 모델만(자리 표시만 — 주소·키 없음).
3. 이미지 ENTRYPOINT는 `tini -s -- dev_entry.sh`: `devbox`면 sshd(컨테이너 사용자 UID 10001, 열쇠 로그인만, 호스트 열쇠는 홈), 그 밖의 명령은 인자 그대로 이미지의 시작 스크립트(`APP_ENTRY` — 실행 이미지 `runtime_entry.sh`, 코드가 든 이미지 `entrypoint.sh`)로.
4. 설정은 settings.yaml 맨 아래 선택 절 `option.devbox` — `ssh_port`(비우면 끔)·`opencode_config`(opencode 설정 파일의 호스트 경로, 비우면 이미지의 틀). `host_ctl.sh`는 `ssh_port`가 있을 때만 `compose.dev.yml`(+ `opencode_config`면 `compose.opencode.yml`)을 더한다. prd·코드가 든 이미지면 종료 2. gitea 계정 `gitea_url`·`gitea_user`·`gitea_token`(비밀)·`git_user_name`·`git_user_email`(선택) — 주소·계정·토큰을 모두 적으면 `dev_entry.sh`가 `git_cred.py`로 붙인 settings.yaml에서 읽어 `~/.git-credentials`(600)의 그 호스트 줄만 바꾸고 `credential.helper store`, 비우면 그 줄을 지운다(토큰은 env로 안 넘김, 사용자 11-06).
5. `compose.dev.yml`: `data-pipeline` 명령 `devbox`, 코드 폴더를 `compose.code.yml`과 같은 자리에 쓰기 가능으로, `<루트>/home` → `/home/rag`(`host_ctl.sh init`이 만듦 — 10001, 700). 컨테이너 env에는 비밀이 없다(설정은 붙인 settings.yaml에서만) — SSH 접속 셸이 그 env를 홈에 저장해 다시 읽기 때문.

### 비고
- 운영용 굽기(`Dockerfile.bake`)는 ENTRYPOINT를 `entrypoint.sh` 그대로 둔다 — 운영은 작업 공간을 쓰지 않고, 굽는 바탕이 개발 도구가 없는 옛 실행 이미지일 수도 있어서.

### QA
- `tests/general/deploy/test_dc.py`(포트를 적으면 `compose.dev.yml`, opencode 설정이면 `compose.opencode.yml`, prd·코드가 든 이미지 종료 2) · `test_devbox.py`(`dev_entry.sh` 인자 넘김 표 · `compose.dev.yml` 마운트 자리 · `git_cred.py` 그 호스트 줄만 바꿈·다른 줄 유지·권한·비우면 지움·링크 안 따라감) · `test_dc_init.py`(`<루트>/home`) · 이미지 시험(`pipeline-runtime` 빌드 → 도구 확인·`selftest` `[판정] 통과`·`devbox` sshd) · 통과.
- Status: done

<a id="op-17"></a>
## op-17 · 개발 서버 개인 시험 벌 — 코드 폴더 = 벌, DEV 원천, 처리 기록은 pgvector

### 무엇·왜
개발 서버에서 개발자마다 자기 문서만 파싱·적재·검색해 시험한다(사용자 11-06). 벌끼리는 원천 이름(`DEV-1`·`DEV-2`)으로 나뉘고, 처리 기록은 EDW가 아니라 pgvector에서만 관리한다. 0.3.0에 넣는다.

### 정한 것(사용자 11-06)
1. 벌 폴더 = 코드 폴더 자체(`/home/sbl/sbl_data_parsing-main-1/`). 그 안에 `settings.yaml`·`edw_chain.yaml`·`output/`(+ SSH 작업 공간을 켜면 `home/`). `backup/`은 만들지 않는다. 공용 폴더(`/home/sbl/`)에는 이미지 폴더와 공용 `opencode.json`.
2. `init`의 권한 정리(`a+rX`)는 settings.yaml·edw_chain.yaml·output/·home/을 건드리지 않는다(비밀값 파일 640 유지). `home/`은 `ssh_port`를 켤 때만 만든다. git 제외 목록에 `edw_chain.yaml`(루트)·`home/`.
3. 판 올리기는 사람이 한다 — 새 zip을 풀어 `-main-N`으로 이름을 바꿔 덮어쓴다(옛 것은 각자 백업, gitea에도 올림).
4. 벌마다 compose 실행법(폴더 구조·명령)은 README "한 서버에 여러 벌" 절에 둔다.
5. 벌 번호는 코드 폴더 이름 끝 `-<숫자>`에서 저절로 정해지고(설정 칸 없음 — `ops.host.instance_name` 없앰) 컨테이너·compose 묶음·타이머 이름 끝(`-<숫자>`)에만 붙는다. PG 스키마·EDW 표·게시 경로에 붙이던 `_<벌>` 접미사는 없앤다. 적재 판(`gold_version`)에도 벌 표시를 붙이지 않는다.
6. 원천 `DEV-<숫자>`(대소문자 무관)를 dev 서버에서만 받는다. 원천 스키마는 `<기준 스키마>_dev_<숫자>` — 다른 원천과 같은 표·뷰. 메타는 Other처럼 없다(EDW 사슬 없음).
7. 원천 스키마는 설정에 따라 만든다(동적) — 마이그레이션 도구가 설정의 DEV 원천 스키마가 없으면 만들고, 뒤의 표 변경은 DB에 있는 `_dev_*` 스키마에도 적용한다. 검색 MCP의 원천 목록 = 5개 + DB에 있는 DEV 스키마.
8. 파싱할 원천은 settings.yaml 맨 위 `required`의 목록 칸. 비우면 운영 5개 원천 전부. prd에서 `DEV-…`이면 시작 거부.
9. 원천은 EDW `AI.FileStorageMap.source_system` 칸으로 정한다(시험 행은 `dev-1`·`dev-2`). Object Storage 경로도 `DEV-1/…`.
10. MCP `search`의 `source_system`: dev는 `DEV-<숫자>`도, prd는 지금처럼 5개 값.
11. `AI.ParsingMeta`는 더 쓰지 않는다(우리만 씀). 처리 정보는 원천 스키마마다 `doc` 표에 칸을 더해 둔다.
12. 적재되지 않은 문서(파싱 실패·내용 중복·DRM 등)의 기록은 applog 표 하나 — 규칙 16.
13. 서버에 쌓인 ParsingMeta 기록은 사람이 옮긴다(도구 없음).

14. `doc`에 더할 칸: `sha256`(내용 중복 판정) · silver 위치(버킷·키) · `engines`(수행한 엔진 전부 + 대표 표시) · `parse_status`(`ok`·`partial`) · `silver_version` · `gold_version` · `parsed_at`(silver — 파싱·게시 시각) · `loaded_at`(gold — 적재 시각). `gold_status`·`gold_reason`(EDW에서 gold 실패를 보려던 칸)은 두지 않는다.
15. 끝난 문서 = 원천 스키마 어디든 `doc`에 행이 있는 원본 키. 내용 중복 = 다른 원본 키의 `doc.sha256`이 같음.
16. 적재되지 않은 문서 기록은 `applog.except_doc_info` 하나(`skip_doc_info`를 바꿈) — `except_type` `skip`(영구 뺌 — 미지원·DRM·암호·내용 중복) · `error`(기록만, 다음 실행이 다시 고름 — 파싱·적재 실패). 처음·마지막 시각·횟수 유지.
17. 원천은 FileStorageMap `source_system` 값 하나로 고르기·구조화·적재·게시가 모두 정한다(목록 파일·manifest로 넘김). Object Storage 경로 = `<원천>/…`, PC = `valid_env/object_storage/<원천>/`. 원본 경로 첫 마디 규칙(pl-28 규칙 3)은 없앤다.
18. EDW는 읽기만(FileStorageMap·메타 사슬) — 쓰기 계정 칸은 없앤다.
19. 마스터 표는 `glossary` 하나(melt — 유사값마다 한 줄): 칸 = 구분(`client`·`term`·`id`) · 원본 값 · 유사값 · 유사 종류(동의어·약어·약한 동의어 — 용어 사전이 구분해 씀) · 설명 + 용어의 문맥 필요·대소문자 구분 표시. 고객 명부(`client_roster`)·용어 사전(`domain_terms`)·ID 꼴(`id_patterns`)을 합친다. `id` 줄은 원본 값 = 종류(`contract_no`·`product_code`), 유사값 = 정규식 — ID 우선 찾기는 그대로.
20. 안 쓰는 마스터 표 `client_master`·`contract_master`·`units`는 없앤다. `master_meta`(해시 1행)도 없애고 해시는 glossary를 읽을 때 계산한다(`gold_version` 꼴 그대로).
21. 핸드오프 파일 `common/core/terms.py`는 고치지 않는다 — `common/store/master.py`가 glossary를 읽어 지금과 같은 행 모양으로 넘긴다.
22. `doc`에 찾기용 색인 3개 — `sha256` · (`silver_bucket`, `silver_key`) · `file_path`(일반 btree — `file_path`에 UNIQUE는 없다). 0.3.0의 새 판으로 넣는다(이미 올린 판은 고치지 않음).

### 사람 검토
DB 스키마(마이그레이션 — `doc` 칸·`doc` 색인·`except_doc_info`·DEV 스키마), MCP 계약(dev 값), 비밀값 파일 권한(init), EDW 쓰기 중단.

- 비고: 규칙 1~5·8·9·11·12·14~22 반영 — 처리 기록 `doc` 칸(판 `0006_search` — `search_tables.DOC_RECORD`, 게시 `publish/silver.jsonl` → 적재 `--silver`), `doc` 찾기 색인 `ix_<스키마>_doc_sha256`·`_doc_silver`·`_doc_path`(판 `0007_search` — `search_tables.DOC_INDEX`), 끝난 문서·내용 중복 `pipeline/shared/gold_docs.py`, `applog.except_doc_info`(판 `0003_applog` — `pipeline/shared/except_docs.py` · 판 `0004_applog` `file_ext`·`file_size`), 원문 도구는 `doc` 칸에서 읽음, EDW 쓰기 없음. 규칙 6·7(DEV 원천 스키마) 반영 — `search_tables.source_of`(`DEV-<n>` → `dev_<n>` → `<기준>_dev_<n>`), `dbtool up --target search`·적재 deploy가 함께 쓰는 `dbtool.upgrade_search`가 설정의 DEV 원천 스키마를 만들고 DB에 있는 `_dev_*`도 올림(판 기록 표는 그 스키마 안 · 판 파일은 `migrations/search_parts.sources()`로 그 스키마만 — 시험이 판 파일마다 확인 · 적재 전 판 확인 `require_current`도 `_dev_*`를 봄 · prd는 DEV를 찾지 않음 · `--sql`은 설정의 DEV 스키마를 빈 스키마부터, DB에 있는 다른 `_dev_*`는 `-- 수동:` 줄), 적재는 스키마가 없으면 멈춤(DDL 없음)·EDW 메타 없음, 끝난 문서·원문 도구·run_pipeline 건수·PC 폴더 원천(`DEV-<n>/`, 원천 목록으로 거름)이 `_dev_*`를 봄, 원천 목록이 비면 운영 5개 원천만(규칙 8 — `candidate_pick.picked`)(시험 `tests/server/pipeline/test_dev_source.py`). 마스터 표 `glossary`(판 `0002_master` — 옛 마스터 표 일곱 개를 지움, 원본 `resources/vocab/glossary/glossary.csv`, 옛 행 모양으로 되돌리기 `common/store/master.py` `to_tables`, 해시는 읽을 때 계산, 시험 `test_master.py`). 옛 CSV → `glossary.csv` 옮기기 `python -m common.store.master convert`(시험 `test_convert_old_csv`), 명부 도구 `gen_roster --kind client`는 glossary 고객 줄을 씀(있는 파일은 고객 줄만 바꿈). 서버 `migrate up --target master`·실명 자료 옮기기 실행은 사람(refactor.md C-108). 규칙 7의 검색 MCP 원천 목록·10 반영 — 검색 MCP가 시작 때 5벌 + 있는 `_dev_*`를 싣고(`server_state.connect_sources` — `ST.all_sources`, prd는 5벌만), `DEV-<n>` 꼴 값이 오면 DB를 한 번 다시 찾아 그사이 생긴 스키마는 그 원천만 더하고 사라진 것은 뺌(`server_state.dev_served` — 재시작 없음, 표 없는 등 깨진 DEV 스키마는 경고 한 줄 뒤 그 원천만 뺌), `search`·`list_doc_fulltext`가 dev·local에서 있는 `DEV-<n>`을 받음(prd는 모르는 값과 같은 오류, 출력·메아리 `DEV-<n>`), 도구 설명에 "(개발 서버: DEV-<숫자>)", `edw_meta` `search_attrs`에 DEV 원천(빈 칸)(시험 `tests/server/mcp/test_dev_search.py`). 검증 페이지 원천 고르기는 고정 목록이라 그대로. 남은 것: 13(서버의 ParsingMeta 기록 옮기기 — 사람, refactor.md C-107). 쓰기 계정·`parsing_meta_table` 칸은 없앴다(남은 settings.yaml은 시작 거부 — C-107). 대상 목록 표는 `required.edw.edw_file_table`(기본 `AI.FileStorageMap`, `<스키마>.<표>`만 — 사용자 11-06, 시험 `test_target_list.py` `TABLES`).
- Status: todo

parse_document 회수 보강(#177): 종료 확인·running 소유권 변경은 WATCH로 묶고, 시도별 `a<n>/`에서 파싱한 뒤 HASH의 `result_file` 이름으로 결과를 읽는다. heartbeat가 없는 소비자는 idle 60초 뒤 한 건씩 회수하며, 살아 있지만 멈춘 소비자는 기존 (job_timeout+60)초 XAUTOCLAIM으로 회수한다. 손상된 HASH는 failed로 끝내고 일반 worker 오류는 traceback으로 기록한다.

parse_document 빠른 거절·제출 복구(#177): worker가 확장자·허용 루트·크기 정책을 시작 때와 10초 heartbeat마다 Redis에 TTL 120초로 공개한다. proxy는 정책이 있으면 확장자와 정규화한 절대경로를 폴더 생성 전에 검사한다(존재·실제 크기·심볼릭 링크는 worker가 검사). 정책이 없으면 제출한다. 제출 EXEC 응답이 유실되면 새 EXISTS로 등록 여부를 확인해 등록된 작업은 계속 기다리고, 미등록이 확실할 때만 폴더를 지운다. 확인도 실패하면 폴더를 보존하고 job_id와 연결 오류를 반환한다.
