# 운영 — 실행 관리·러너·계정·종료·로그

[PRD.md](../PRD.md) 카테고리. 실행 관리(pl-10·pl-23·pl-54·pl-24·pl-55·pl-18), 서버 러너 `run_docs.py` 레인·대기열(rn-01~04), 종료 정리(pl-27), EDW 계정(op-03), 모델 호출 가드(pl-11), 로그(op-01). 설정 파일은 [ops-settings.md](ops-settings.md).

순서: pl-10 · pl-23 · pl-54 · pl-24 · pl-55 · pl-18 · rn-01 · rn-02 · rn-03 · rn-04 · pl-27 · op-03 · pl-11 · op-01.

<a id="pl-10"></a>
## pl-10 · 실행 관리 — 서버 입구는 `run_docs.py` 하나
- 이유: 서버는 문서 수천 건을 사람 없이 돌린다.
- 규칙:
  1. CLI `pipeline.cli`는 `parse`·`show-stack`·`selftest`. 이미지 entrypoint(`deploy/docker/entrypoint.sh`)가 `publish`·`migrate`·`check`·`services`·`resources`·`tool`·`ask`·`mcp`·`parse-service`·`idle`을 더한다. `idle` = 상주 컨테이너가 떠 있기만 한다(run_docs가 `docker exec`).
  2. 서버 실행은 호스트 python의 `deploy/host/scripts/run_docs.py`(PyYAML·pymssql 필요)가 상주 컨테이너 `data-pipeline` 안에서 문서마다 명령을 `docker exec`로 돌린다. 컨테이너 명령은 settings.yaml `ops.host.docker`(없으면 podman). PC에서는 실행하지 않는다.
  3. 시작: 설정 파일 = `--settings` → `SETTINGS_FILE` → `<루트>/settings.yaml`(루트 = 코드 폴더의 부모 — op-13). `required.env.run_env`가 dev·prd가 아니거나 필요한 칸이 없으면 칸 경로만 찍고 종료 2. 코드 폴더 = `--code`(없으면 스크립트가 든 코드 폴더) — 그 안의 `common/config/layout.py`·`deploy/host/scripts/host_settings.tsv`로 설정 배치와 컨테이너 안 경로를 읽는다.
  4. 대상 목록: EDW `SELECT id, s3_key, original_filename, file_size FROM AI.FileStorageMap WHERE (<이름 조건>) AND file_size IS NOT NULL ORDER BY file_size ASC`. 이름 조건 = `--filter`(기본 `RFP,proposal`)의 낱말마다 `LOWER(original_filename) LIKE '%낱말%'`를 OR. 순번(seq)은 이 순서. `--start-offset N`(기본 1072 — 새벽 배치는 0)부터, `--seqs`면 그 순번만, `--skip-done`이면 끝난 문서([pl-23](#pl-23))를 빼고, `--max-docs`면 그 뒤 앞에서 N건, `--limit`은 시험용(그 전에 자름).
  5. 문서마다: warm(미리 받기) → 레인 분류 → 파싱 → 게시 → 원본 삭제 → gold(구조화+적재) → 임시 삭제([pl-24](#pl-24)). 배치 장벽 없이 끝나는 순서대로 흐른다.
  6. 레인·대기열은 [rn-01](#rn-01)·[rn-02](#rn-02), MCP 양보는 [rn-03](#rn-03)·[rn-04](#rn-04), 종료 코드는 [pl-18](#pl-18).
  7. 문서별 값은 컨테이너 명령에 `--set`으로 준다(같은 이름은 뒤 값이 이김):
     - 파싱 공통: `VLM_MAX_CONCURRENCY=8` · `VLM_CONCURRENCY=8` · `VLM_FIGURES_MAX=10` · `PARSE_POST=supsub,charts,figures,context,attachments` · `RAPIDOCR_PAGE_WORKERS=2` · `OCR_THREADS=1` · `PIPE_PROCS=4` · `SOURCE_WARM=<결과 자리>/_warm` · `SOURCE_FETCH_WORKERS=2` · `PARSE_REP_SELECT=first` · `PARSE_QA_LIGHT=1`, 문서 출력 자리 `PIPE_OUT_ROOT`·`DOC_DIR_PREPARED`·`PARSE_IMAGES_ROOT`·`PARSE_RAW_ROOT` = `<결과 자리>/_docflow/<seq>/…`.
     - vlm 레인이면 덧붙임: `VLM_MAX_CONCURRENCY=6` · `VLM_CONCURRENCY=6` · `PARSE_POST=…,attachments,vlm_page` · `VLM_PAGE_MAX=`(상한 없음). 스캔 PDF면 `PREPARE_ROTATE=0`. 쪽 해상도는 settings.yaml `extract.ocr.dpi`(VLM 설정은 [pl-43](transform.md#pl-43)).
     - CPU 게이트 `CPU_MAX_LOAD` = light 레인 9(사실상 게이트 없음), 그 밖 `--cpu-gate`(기본 1.3).
     - 파싱 명령: `python -m pipeline.cli parse --source rdb:csv:<_docflow/seq>/batch.csv`, 제한 2700초.
     - 구조화·적재: `EMBED_CONCURRENCY=6` · `EMBED_BATCH=32` · `BM25_THREADS=3`으로 `pipeline.transform.structure.build_bundle` → `pipeline.load.pgvector_load load`.
  8. 기록: 작업 폴더(`ops.pipeline_host.run_docs_dir`, 비우면 스크립트 옆 `test_space/`)의 `batch_progress/` — `progress.log`(진행), `doc_<seq>.log`(문서별 파싱), `queue_depth.jsonl`([rn-02](#rn-02)), 잠금 `run_docs.lock`.
- 파일: `deploy/host/scripts/run_docs.py`, `pipeline/cli.py`, `deploy/docker/entrypoint.sh`.
- QA: `tests/general/deploy/test_run_docs.py`(명령 글자·설정 대조)·`test_docs_flow.py` · 통과.
- Status: done

<a id="pl-23"></a>
## pl-23 · 새 문서만 처리, 전체 재파싱은 사람이 시작
- 이유: 핑거프린트가 바뀌어도 밤 작업이 전체 재파싱으로 시간을 넘기지 않게.
- 규칙:
  1. "새 문서" = `AI.FileStorageMap`에 있고 `AI.ParsingMeta`에 끝난 행이 없는 것. 키 = `s3_key`(갱신 시각은 보지 않음).
  2. "끝난 행" = `parse_status`가 `skipped_dup`, 또는 `ok`·`partial`이면서 `gold_version`이 있음(`gold_version` 칸이 없는 EDW에서는 `parse_status`만 봄). `not_parsed`·`skipped_disk_cap`·실패·행 없음은 다시 고른다. 코드 두 곳이 같은 목록을 쓴다 — `common/store/parsing_meta_db.DONE_STATUSES`·`run_docs.py DONE_STATUSES`.
  3. 파싱 입구(`pipeline.cli parse` → `pipeline/extract/fetch_docs.py` `unparsed`)는 EDW를 한 번 읽는다(읽기 계정, PC는 sqlite 대역). 못 읽으면 RUN_ENV가 local이 아니면 종료 4, 그 밖은 받은 목록 그대로 + 로그 한 줄. 키 = 수집 manifest의 `key`(없으면 이름).
  4. 전체 재파싱은 사람이 전체 e2e를 시작할 때만([pl-54](#pl-54)).
  5. 새벽 배치: settings.yaml `ops.nightly.time`(시작 HH:MM)·`max_docs`(새 문서 수 상한, 1 이상)·`deadline`(마감 HH:MM, 시작보다 5분 넘게 뒤) — 하나라도 비면 돌지 않는다. systemd `data-pipeline-nightly.timer`(`OnCalendar=*:0/5`)가 `nightly_batch.sh scheduled`를 부르고, 시작 시각부터 5분 안이면 `run_docs.py --start-offset 0 --skip-done --max-docs <n> --deadline <hh:mm>`. 형식 오류면 종료 2. 서비스 `TimeoutStartSec=6h`.
- 파일: `pipeline/extract/fetch_docs.py`(`unparsed`), `common/store/parsing_meta_db.py`, `deploy/host/scripts/{run_docs.py,nightly_batch.sh}`, `deploy/host/systemd/data-pipeline-nightly.{timer,service}`.
- QA: `tests/general/deploy/test_trigger_gate.py`·`tests/server/pipeline/test_nightly_time.py`·`test_run_docs`(`deadline_at`, `test_done_keys_match_parsing_meta`) · 통과. 서버 확인 refactor.md C-72.
- Status: done

<a id="pl-54"></a>
## pl-54 · 전체 e2e — local·dev·prd, prd 전체 문서 실행은 새 `PG_SCHEMA`로
- 이유: 판 0002가 기준 스키마의 옛 표를 지우고 0.2.0은 전체 다시 적재다.
- 할 일: 전체 e2e를 local·dev·prd에서 돌린다. 전체 문서 실행은 prd에서만, 새 기준 스키마 이름(`required.pg.db_schema`)으로. 옛 gold·`struct` 스키마는 2주 뒤 DB 담당자가 백업하고 지운다.
- 절차: [release-and-patch.md §8](../operations/release-and-patch.md#8-020-배포--사람이-할-일) · 서버 확인 refactor.md C-74.
- Status: todo

<a id="pl-24"></a>
## pl-24 · `run_docs` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 게시가 gold를 기다리지 않고, 원본은 게시가 성공했을 때만 지운다.
- 규칙:
  1. 파싱 성공 → 게시 대기열(게시 스레드 1개 — Object Storage 업로드 + ParsingMeta INSERT).
  2. 게시 성공 → 원본(warm `.bin`·`_docflow/<seq>/_source_files`) 삭제 → 구조화 대기열(`struct_workers` 스레드 — build_bundle·pgvector_load) → `_docflow/<seq>` 삭제(`--no-cleanup`이면 남김).
  3. 파싱 실패·게시 실패 → 원본을 남기고 로그에만(gold로 안 감, EDW에 안 씀). 파싱 실패면 그 문서 표지(`RUN_DOCS_DOC`)가 붙은 컨테이너 안 프로세스를 끈다.
  4. gold 실패 → 게시한 silver·ParsingMeta 행은 그대로, 로그에만. `gold_version`이 비어 다음 `--skip-done`이 다시 고른다(파싱·게시부터 다시).
- 파일: `deploy/host/scripts/run_docs.py`(`doc_flow`, `cleanup_doc`).
- QA: `tests/general/deploy/test_docs_flow.py`(`test_doc_order_and_exit_code` 표) · 통과.
- Status: done

<a id="pl-55"></a>
## pl-55 · gold 실패를 ParsingMeta `gold_status`에 적기
- 이유: gold가 실패해도 ParsingMeta 행은 남는다 — EDW에서 실패를 볼 칸이 필요하다.
- 할 일: DB 담당자가 `AI.ParsingMeta`에 `gold_status`(pending · ok · failed)·이유 칸을 더하면(회사 DB DDL — Alembic 아님, 등급 A), `run_docs.py` `gold_one()` 옆 TODO 자리에서 failed·이유를 쓴다.
- 파일: `deploy/host/scripts/run_docs.py`, `docs/operations/parsing_meta_mssql.sql`.
- Status: todo — 칸이 생긴 뒤(refactor.md C-81).

<a id="pl-18"></a>
## pl-18 · `run_docs` 종료 코드와 겹침 잠금
- 이유: 스케줄러가 실패를 봐야 한다.
- 규칙:
  1. 종료 코드: 0 = 대상 0건·모두 끝 · 1 = 실패 문서(파싱·게시·gold) 하나라도 · 75 = 마감 도달(실패 없음) 또는 다른 run_docs가 도는 중 · 2 = 설정 문제. 실패와 마감이 함께면 1.
  2. 겹침 잠금: `flock batch_progress/run_docs.lock`(프로세스가 죽으면 커널이 풂). 사람이 직접 돌려도 같은 잠금.
  3. `--deadline HH:MM`: 그 시각(지금보다 이르거나 같으면 다음 날)이 지나면 새 문서를 받지 않는다.
- 파일: `deploy/host/scripts/run_docs.py`, `deploy/host/scripts/nightly_batch.sh`.
- QA: `tests/general/deploy/test_docs_flow.py`(`test_exit_codes`·`test_lock_blocks_second_run` — Windows는 건너뜀) · 통과. 서버 확인 refactor.md C-72.
- Status: done

<a id="rn-01"></a>
## rn-01 · 레인 정책 — 담당 레인 먼저, 공유 워커만 가져오기
- 이유: 문서마다 자원 성격이 달라 레인으로 나누고, 남는 워커는 다른 레인을 돕는다.
- 규칙:
  1. 레인 분류(warm 때, 결과는 `s3_key`별로 저장해 다시 씀): `run_docs.classify_doc`이 컨테이너 안 `pipeline/extract/doc_lane_group.py`(원본 파일·원본 이름·크기 — 제한 60초)를 부르고, 규칙은 그 파일의 `doc_lane_group()` 하나에 있다. 답이 없으면 vlm. 규칙: 확장자가 `.txt .hwpx .hwp .csv .eml .msg .html .htm .tsv .md .json .xml .log .rtf`면 light. `.pptx .ppt`면 vlm. `.pdf .docx .doc .xlsx .xls .xlsm .docm`이면 내용을 본다 — PDF는 첫 3쪽 글자가 쪽당 평균 300자 미만, 오피스 zip은 내장 그림 8개 이상 또는 합계 800,000바이트 이상, 검사 실패도 heavy → vlm(vlm PDF는 스캔 표시). 아니면 크기 기준(`.docx .doc` 300KB · `.xlsx .xlsm .xls` 500KB · `.pdf` 1024KB 이상)이면 medium, 그 밖 light. 다른 확장자는 vlm.
  2. 워커 수: settings.yaml `ops.run_docs.<레인>_dedicated`(자기 레인만)·`<레인>_shared`(자기 레인 먼저, 비면 대기열이 가장 긴 다른 레인), 기본 각 1(모두 6개).
  3. `vlm_cap`(기본 2): 진행 중 vlm 문서가 이만큼이면 vlm 레인을 건너뛴다(전담 워커도).
  4. 고르기 = 순수 함수 `pick_lane(own, shared, queues, inflight, vlm_cap)`.
  5. 시작 때 거부(종료 2): 값이 0 이상 정수가 아님 · `warm`·`warm_workers`·`vlm_cap`이 1 미만 · 전담과 모든 공유 워커 합이 0인 레인.
- 파일: `deploy/host/scripts/run_docs.py`(`classify_doc`·`RUN_DOCS_DEFAULTS` — 설정 모델 `pipeline.config.PipelineHostRunDocs`와 시험이 대조) · `pipeline/extract/doc_lane_group.py`(`doc_lane_group`).
- QA: `tests/general/deploy/test_run_docs.py`(`pick_lane` 표·`test_classify_cache_skips_probe`) · `tests/server/pipeline/test_doc_group.py`(그룹 규칙 표) · 통과.
- Status: done

<a id="rn-02"></a>
## rn-02 · 대기열 — 진입·중간 상한과 길이 기록
- 이유: 구조화가 느리면 파싱 결과가 쌓인다(디스크·대기 시간).
- 규칙:
  1. 진입 `ops.run_docs.warm`(기본 20, `--warm`이 덮음): 미리 받아 둘 문서 수(받는 중 포함, 파싱 중 제외). 동시 받기 = `min(warm_workers(기본 2), 빈자리)`.
  2. 구조화 스레드 `struct_workers`(기본 2, `--struct-workers`가 덮음).
  3. 중간 상한 `struct_backlog`(비우면 구조화 스레드 × 2, 0 = 없음): 게시 대기 + 구조화 대기가 이 수 이상이면 레인 워커가 새 파싱을 시작하지 않는다.
  4. `batch_progress/queue_depth.jsonl`에 dispatch·pick·parse_end·struct_put·struct_get마다 한 줄(`pub_wait` 포함). 쓰기 실패는 무시.
- 파일: `deploy/host/scripts/run_docs.py`.
- QA: `tests/general/deploy/test_run_docs.py`(`test_struct_backlog_holds_new_parses`) · 통과.
- Status: done

<a id="rn-03"></a>
## rn-03 · MCP `parse_document`에 CPU 먼저 주기
- 이유: 일괄 파싱이 CPU를 다 쓰면 사람이 기다리는 `parse_document`가 느려진다. 컨테이너끼리는 cgroup CPU 가중치가 정한다(nice는 한 세션 안에서만).
- 규칙: `parse_document` 작업 서비스는 전용 컨테이너 `mcp-data-parsing`(같은 이미지, entrypoint `parse-service` = `pipeline.parse_service`, 127.0.0.1:8766). 자원 = settings.yaml `ops.pipeline_host.parse_mcp_cpus`(기본 3)·`parse_mcp_mem_limit`(8g)·`parse_mcp_cpu_shares`(4096 — 일괄 `data-pipeline`은 1024). 결과 폴더만 붙인다. 죽으면 `restart`, 꺼지면 `mcp_keepalive.sh`(keepalive 타이머)가 띄운다. 일괄 엔진 자식은 nice +10.
- 파일: `deploy/host/compose/compose.data-parsing.yml`(개발 서버 짝 `compose.code.data-parsing.yml`), `pipeline/parse_service.py`, `common/core/resources.py`.
- QA: `tests/general/deploy/test_compose.py` · 통과.
- Status: dev — 서버에서 일괄 파싱 중 `parse_document` 응답 시간 확인(refactor.md C-83 ①)만 남음.

<a id="rn-04"></a>
## rn-04 · MCP 업로드 중 medium 전담 워커 쉬기
- 규칙: 5초마다 `mcp_busy()` — 작업 폴더(`<결과 폴더>/_mcp_parse/jobs` — 고정) 아래 이름 날짜(`<YYYYMMDD>-…`)가 어제·오늘·내일인 폴더만 보고, 30초 안에 바뀐 파일이 있으면 바쁨. 바쁘면 medium **전담** 워커가 새 문서를 집지 않는다. 폴더가 없으면 감지를 끄고 안내 한 줄. 레인 워커 수는 `ops.run_docs.*` 칸.
- 파일: `deploy/host/scripts/run_docs.py`.
- QA: `tests/general/deploy/test_docs_flow.py`(medium·vlm 레인, vlm 동시 상한, MCP 양보, `mcp_busy` 표) · 통과.
- Status: done

<a id="rn-05"></a>
## rn-05 · run_docs는 지휘만 — 판단은 파이프라인 함수, PC도 run_docs로(0.2.0 다음)
- 이유(사용자 11-04): run_docs.py(1천여 줄·함수 50여 개)가 레인·중복·게시 판단까지 직접 한다. 같은 판단이 파이프라인과 두 곳에 있고, PC E2E는 run_docs 없이 pipeline.cli를 단계별로 돌려 서버와 다른 길을 탄다.
- 할 일:
  1. run_docs 함수를 "파이프라인 함수로 옮김 / 지움 / 지휘로 남김"으로 나눈 표를 먼저 사람에게 보인다. 판단·처리(원천 목록, 중복, 레인, 게시 판단)는 extract·transform·load 함수로 옮기고, run_docs는 레인·워커·임시 폴더와 `docker exec` 호출만 남긴다.
  2. PC(`RUN_ENV=local`)에서도 run_docs로 E2E를 돈다 — 가짜 대상만(EDW sqlite·`file://` 게시 폴더·상대 경로, op-14). PC만의 분기는 접속 대상을 고르는 한 곳. CLAUDE.md §4의 "run_docs는 PC에서 실행하지 않는다" 문구를 이 규칙으로 고친다(등급 A — 운영 접속 가드).
  3. 커밋 전 점검 `deploy/release/lint_changed.sh`를 점검 도구 자리 `common/check/`로 옮긴다 — `.githooks/pre-commit`·CLAUDE.md §5-2·README 명령 줄을 같이 고친다.
- 파일: `deploy/host/scripts/run_docs.py` · `pipeline/extract/*` · `pipeline/load/*` · `deploy/release/lint_changed.sh` · `.githooks/pre-commit` · `CLAUDE.md`.
- QA: run_docs 정리 전후 같은 문서 묶음의 결과(대표 결과·ParsingMeta 행·게시 파일)가 같음 · PC에서 run_docs 한 번으로 가짜 EDW `ParsingMeta` 행과 `file://` 폴더 결과가 생김.
- Status: todo

<a id="rn-06"></a>
## rn-06 · 저장소 전체 정리 — 중복 기능 하나로, 파싱 코드는 ETL 폴더로, 파일 이름은 하는 일로
- 이유(사용자 11-04): 같은 일을 하는 코드가 여러 곳에 있고, 파싱 코드가 `pipeline/extract`·`transform`·`load` 밖(파이프라인 루트·`shared`·`run_docs.py`)에 흩어져 있으며, 이름만 보고 하는 일을 알기 어려운 파일이 남았다.
- 정한 것(11-04 질의):
  1. 범위는 저장소 전체(`pipeline`·`common`·`mcp_server`·`deploy/host`·`deploy/release`·`validation`). 보호 파일(`pipeline/extract/engines/**`, `common/core/{contract,repfmt,terms,text}.py`)은 손대지 않는다.
  2. "ETL 폴더" = `pipeline/` 안 `extract`·`transform`·`load`. 최상위 폴더 이름 `pipeline/`은 그대로(이미지·명령 이름 그대로 — 코드 폴더만 교체).
  3. `run_docs.py`는 서버 호스트에서 `docker exec`로 지휘만 하고, 판단(원천 목록·중복·레인·게시)은 ETL 함수로 옮긴다 — rn-05를 이 행과 함께 한다.
  4. 서버 배치: 이미지 폴더(`sbl_images-main/`)는 루트 한 단계 위 공용 폴더에 하나(예 `/home/sbl/`), 벌마다 루트(`dev/`·`dev-hong/`) — 문서만(op-13 규칙 2, README §5-0).
  5. (11-04 둘째 질의) 스캔 PDF 규칙 두 개(레인 분류 `doc_lane_group` — 앞 3쪽 평균 300자 미만 · 엔진 선택 `parse_run.pdf_kind` — 쪽당 평균 20자 미만)는 목적이 달라 그대로 두고 역할만 주석으로 적는다(결과 변화 없음).
  6. run_docs의 EDW 읽기(문서 목록·끝난 문서·FAQ)와 warm 파일 이름은 호스트 사본을 그대로 둔다 — 컨테이너 쪽과 같은지 견주는 시험만 더한다(운영 접속 변경 없음) — `tests/general/deploy/test_edw_copies.py`(끝난 문서 상태 목록·SQL 조건·키 칸 규칙·warm 이름).
  7. 서버·릴리스 스크립트 이름을 하는 일로 바꾼다(문서·systemd 단위 함께).
  8. 공용 모듈(`common/**`)과 `pipeline/shared/**`는 이름·자리를 바꾸지 않는다(레이어 코드 핑거프린트 값 유지 — 기록용이지만 이번엔 제외). 파이프라인 루트의 파싱 코드를 ETL 폴더로 옮기는 것은 한다.
- 할 일(조사 11-04 — 표는 커밋 메시지·PR 본문):
  - 서버·릴리스 스크립트: `dc.sh`→`host_ctl.sh` · `trigger.sh`→`nightly_batch.sh`(새벽 배치만) · `run_tool.sh`→`pipe_exec.sh`(parse·publish도) · `mcp_up.sh`→`mcp_keepalive.sh`(compose 호출은 서비스마다 자기 파일만 — `host_ctl.sh`로 합치면 모든 이미지 칸이 필요해져 되돌림) · `image_vars.sh`→`in_container.sh`(쓰지 않는 `need_image` 지움) · `prune_old.sh`→`prune_images.sh` · `settings_env.sh`→`load_settings.sh` · `host_env.py`→`settings_to_env.py` · `host_keys.tsv`→`host_settings.tsv` · `deploy/release/{assets.py→offline_assets.py, bake.sh→bake_prod_image.sh, ship_stage.sh→stage_images.sh, hostkeys.py→gen_host_keys.py}`. `load.sh`는 이미지 저장소에 이미 같은 이름으로 있어 그대로.
  - 파이프라인: 단계 사슬(`cli.parse_module`·`parse_service._worker`의 filter_and_rotate→run_engines→parse_scoring→build_rep)과 프로세스 묶음 실행(`cli._run_until`·`parse_service._run_group`)을 하나로. 파싱 코드를 ETL로: `cli._unparsed`→extract, 완료 표시(`read_mark`·`write_mark`)→transform/represent, `_vlm_doc_concurrency`→extract/run_engines, `engine_stack.py`→extract. 쓰지 않는 `cli parse --deadline`·전달만 하는 함수 지움.
  - 검색 MCP: 같은 파일 이름 3건(`services/fulltext.py`·`search/text.py`·`search/terms.py`)과 뜻이 흐린 이름(`local.py`·`qtype.py`·`shaping.py`·`routers/dispatch.py`·`cli/ask.py`) 바꿈, 날짜 조건 `_when` 두 벌 하나로.
- QA: 정리 전후 같은 문서 묶음의 대표 결과·ParsingMeta 행·게시 파일이 같음 · selftest·pytest 기준선 유지 · `check_modules` 통과.
- Status: todo

<a id="rn-07"></a>
## rn-07 · 다시 덜어내기 — 벌 이름 하나로 갈리는 여러 벌, 설정 칸 줄이기, 중복·이력 주석 정리
- 이유(사용자 11-05 점검): rn-06 뒤에도 여러 벌이 EDW·게시·포트·스키마를 함께 쓰고, settings.yaml에 같은 값 칸·늘 같은 스위치·옛 칸 표가 남았으며, `run_docs.py`가 설정 값 약 15칸을 `--set`으로 덮고, 코드에 중복·한 곳만 쓰는 감싸기·이력 주석(약 700줄)이 남았다.
- 정한 것(11-05 질의):
  1. 여러 벌: `ops.host.instance` 한 칸만 적으면 갈린다 — 컨테이너 이름(이미 됨) · PG 스키마 `<db_schema>_<벌>`(따로 적으면 그 값) · EDW 기록 표 `<parsing_meta_table>_<벌>`(예 `AI.ParsingMeta_hong` — DB 담당이 미리 만듦, 실행 중 DDL 없음) · 게시 경로는 dev에서만 `<prefix>/<벌>/…` · 포트는 기본값 그대로면 시작 거부. 버전 칸에는 접미를 붙이지 않는다. `prd`에서 벌 이름을 쓰면 시작 거부.
  2. 파싱 MCP 컨테이너·서비스·compose 파일 `data-pipeline-mcp` → `mcp-data-parsing`, 설정 칸 `parse_mcp` → `data_parsing`(env `PARSE_MCP_*` → `DATA_PARSING_*`). 파싱 포트와 프록시 주소는 한 칸. 토큰 `tokens.parse_mcp`·`parse_proxy`는 `tokens.mcp` 하나로.
  3. `run_docs.py`의 `--set` 값은 `ops.run_docs.*` 칸 기본값으로 옮긴다(서버 결과 같음).
  4. 늘 같은 스위치 칸 지움(`run_mode`·`bucket_skip_overlap_check`·`rdb.engine`·`prepare.link`·`pg_create_extension`·`check_env_any_py`·`warmup`·`edw_query.enabled`·draft_terms 칸 등), VLM 동시 수 칸 4 → 2. 옛 칸 표(`REMOVED`·`ALIASES`·`TO_REQUIRED`·`RETIRED`·`migrate.py`)도 지금 지움 — 옛 칸이 남은 settings.yaml은 시작 거부(서버 확인 refactor.md).
  5. 스캔 PDF 판정은 `pdf_kind` 하나(그림 VLM의 `scan_page_vlm.is_scan`도) — 스캔 쪽이 섞인 PDF는 결과가 달라질 수 있음.
  6. 중복·쓰지 않는 코드 지움, `pdf_kind`를 extract로, `cli.parse_module`의 extract 일은 `fetch_docs`로, 한 곳만 쓰는 감싸기·작은 파일 합침, 주석은 목적 한 줄(이력은 git·docs/history).
- QA: selftest·pytest 기준선 유지(새 시험: 벌 이름 → 스키마·EDW 표·게시 경로·포트 거부, prd 거부) · `check_modules`·`keyscan --check`·`sample --check`·`gen_host_keys --check` 통과 · 저장소 전체 ruff·mypy 0 · 옛 이름(`data-pipeline-mcp`·`parse_mcp`·`PARSE_MCP_`) 0건(docs/history 제외).
- Status: done

<a id="rn-08"></a>
## rn-08 · 파이프라인 폴더는 ETL 뜻대로, 파일 이름은 하는 일로
- 이유(사용자 11-05): 폴더만 보고 그 단계가 무엇을 하는지 알 수 있어야 한다. 엔진으로 글자를 뽑는 일은 정제(transform)이고, 그 결과가 silver다.
- 요건(되어야 할 모습):
  0. 층 이름: **staging** = Object Storage 원본을 임시 폴더로 받아 둔 것(원본은 이미 Object Storage에 있어 따로 보관하지 않음 — extract의 결과) · **silver** = 엔진별 파싱 결과 `parse/<엔진>/<문서>.json`과 대표 결과(transform의 첫 결과 — 실제 엔진 추출은 모두 transform) · **gold** = 검색용 묶음과 pgvector 적재.
  1. `pipeline/extract` = 원본을 고르고 받아 파싱 입력으로 준비하는 일만 — 대상 고르기(목록 − 끝난 문서, 받기 전) `candidate_pick.py`, 미리 받기·받기 `candidate_ready.py`, 같은 파일 정리 `deduplication.py`, 형식 거르기·회전 `filter_and_rotate.py`, 레인 나누기 `doc_lane_group.py`(엔진을 돌리지 않음 — 형식·크기·앞 3쪽 글자 수), DRM 감지 `protected_docs.py`, 원천 열 찾기 `discover_columns.py`.
  2. `pipeline/transform/parse/` = 엔진 파싱 — 엔진 `engines/`(보호 파일), 엔진 준비 확인 `engine_check.py`, 엔진 실행은 한 파일(엔진마다 자식 프로세스로 분리), 엔진 버전·캐시 키(`engine_version`·`p0_key`·`engine_code_fp`)와 캐시 지우기. 그 뒤 `represent`(대표 결과) → `figures`(그림) → `structure`(gold 묶음 `gold_bundle.py`).
  3. `pipeline/shared`의 파일은 한 가지 일만 하고 이름이 그 일이다(원본 캐시·실패 단서·`pdf_kind` 각각). 한 단계만 쓰는 것은 그 단계 폴더에 둔다(후처리 스위치 → represent, 차트 글자 → figures).
  4. 요건 행에 닿지 않는 코드(부르는 곳이 없거나 시험만 부르는 함수, 쓰지 않는 설정 칸·반환 칸)와 같은 일을 하는 두 번째 코드는 두지 않는다. `rep.meta`와 `parse_document` 출력(MCP 계약)은 그대로.
- 비고(현재와 다른 점, 11-05 조사):
  - 엔진·엔진 실행이 `pipeline/extract/{engines,run_engines.py,run_one_engine.py,engine_stack.py}`에 있고, 엔진 실행이 두 파일로 나뉨.
  - `extract/fetch_docs.py` 하나가 고르기·받기·중복 정리를 함께 하고, 끝난 문서 빼기가 받은 뒤에 한 번 더 돈다.
  - `shared/parse_run.py`가 원본 캐시·엔진 버전·캐시 지우기·실패 단서·`pdf_kind`를 함께 가짐. 묶음 파일 이름 `build_bundle.py`.
  - 닿지 않는 코드: 쓰지 않는 청커 5개와 `chunk_overlap` 칸, `infer_clients`의 닿지 않는 갈래, `select_final`·`selection.json`·`--no-rep` 옛 길, `page_text`(시험만), `crosscheck`·`meta.engines`·`n_sum["llm"]`의 읽지 않는 칸. 중복: `figure_extract`의 `_png`·`_model_dir`·`_host`(= `vlmcall`), 쪽 수 세기 두 벌. 오류: `apply_post` 표시 이름. `draft_terms`가 레이어 s 코드 지문에 들어감.
  - 엔진 폴더를 옮기면 엔진 핑거프린트(상대 경로 포함)와 code_fp가 바뀐다 — 기록용(재처리는 ParsingMeta 끝난 상태로만). 사람 검토 필요.
  - 이번에 하지 않음: 그림 부가 기능(pl-05), 글자 파싱 뒤 레인 나누기.
- QA: selftest·pytest 기준선 유지 · `check_modules`·`keyscan --check`·`sample --check` 통과 · 저장소 전체 ruff·mypy 0 · FINGERPRINT 그대로 · 비고의 옛 이름(`extract/engines`·`engine_stack`·`run_one_engine`·`fetch_docs`·`build_bundle`) 0건(docs/history 제외).
- Status: todo

<a id="pl-27"></a>
## pl-27 · 프로세스 종료 정리 — 임시 설정 파일·PID 기록 지움, 자식 회수
- 이유: 덮기 설정 파일(`settings-*.yaml`)이 임시 폴더에 쌓이고, 시간 초과로 끝낸 자식의 손자가 좀비로 남았다.
- 규칙(`common/core/exitclean.py` 한 곳):
  1. `remove_at_exit(경로)` — 이 프로세스가 끝날 때(정상·오류·SIGTERM) 지운다. `track(Popen, group)` — 끝날 때 아직 돌면 끝내고 `wait`로 회수. `stop(p, group)` — POSIX는 (묶음째) SIGTERM → 10초 → SIGKILL, Windows는 `taskkill /T`.
  2. import 때 SIGTERM 처리기를 단다(기본 처리기일 때만): 바로 정리한 뒤 `SystemExit(143)`. 정리 중 두 번째 SIGTERM은 무시. 순서: 자식 전부 SIGTERM → 10초 → 남은 것 SIGKILL·회수 → 파일 지움. 정리를 시작한 뒤 띄운 자식은 바로 끝낸다.
  3. 파일 주인: `settings.put`·`child_env`의 덮기 파일 = 만든 프로세스 · `settings.isolated` = 블록 끝 · `--set`(`setarg` — POSIX는 `execve`로 다시 뜸) = 다시 뜬 프로세스 · `python -m common.config.overrides` 출력 = 지우지 않음.
  4. 연결: `resources.gated_popen`(파이프라인 자식 전부), `resources.kill_group`(→ `stop(group=True)`), `parse_service` 작업 자식과 PID 기록 `service.json`.
  5. 한계: `subprocess.run`의 짧은 자식은 추적 안 함 · 주 스레드가 아닌 곳에서 처음 import되면 SIGTERM 처리기 없음 · SIGKILL·OOM은 정리 못 함 · 컨테이너 PID 1 고아 회수는 compose `init: true`.
- 파일: `common/core/exitclean.py`, `common/config/{settings,setarg}.py`, `common/core/resources.py`, `pipeline/parse_service.py`.
- QA: `tests/server/common/test_exitclean.py`(SIGTERM·`--set` 사례는 POSIX만) · 통과. 서버 확인 refactor.md C-68.
- Status: done

<a id="op-03"></a>
## op-03 · EDW 접속 하나, 공용 계정 둘(읽기·쓰기)
- 이유: ParsingMeta·FileStorageMap·RDB 원천 표·`query_edw`가 같은 EDW 서버·DB에 있다.
- 규칙:
  1. 벡터는 pgvector에만, EDW에는 넣지 않는다.
  2. 접속 블록 하나 — settings.yaml `required.edw`(`host`·`port`·`database`·`read_user`·`read_password`·`write_user`·`write_password`, 모델 `common.connections.rdb` · 게시 표 `parsing_meta_table` — 비우면 `AI.ParsingMeta`). 서버는 접속 칸을, PC는 `sqlite` 하나만 채운다. 드라이버는 pymssql만(`common.store.mssql.login(role)`).
  3. 읽기 계정: RDB 원천 목록·discover·고객 목록·FileStorageMap·ParsingMeta 상태·`run_docs.py` 읽기·MCP 전부. 쓰기 계정: ParsingMeta 게시(INSERT/UPDATE)·`loaded_at` UPDATE.
  4. MCP 프로세스는 `settings.edw_read_only()`를 먼저 불러 설정 객체의 쓰기 계정을 비운다.
  5. PC 대역: `required.edw.sqlite`에 적은 sqlite 파일 하나(`valid_env/edw/edw.sqlite`의 사본 — 생성: `python -m validation.e2e.edw_standin`, `local`에서만 열림)를 `AI`·`CRMS`·`LAS`·`SFDC` 별칭으로 ATTACH(`mssql.standin`, 기본 읽기 전용). `query_edw`는 읽기 전용으로 연다.
- 파일: `common/store/{mssql,parsing_meta_db}.py`, `common/config/settings.py`.
- QA: `tests/server/common/test_edw_login.py`·`tests/general/common/test_edw_standin.py` · 통과.
- Status: done

<a id="pl-11"></a>
## pl-11 · 모델 호출, 비용, 외부 전송 가드(공용)
- 이유: 폐쇄망 서버는 외부 모델을 부르면 안 되고, PC 호출은 싸게 유지해야 한다.
- 규칙:
  1. OpenAI 호환 역할 llm·vlm·embed. 서버(dev·prd)는 외부 모델을 거부한다. 외부 전송은 `<PREFIX>_ALLOW_EXTERNAL`이 켜지고 `RUN_ENV=local`일 때만. 개발 서버부터 내부망 모델, PC는 OpenRouter.
  2. 하루 지출 상한 `dev.models.guard.budget_usd` 기본 0.1달러 — 외부 모델 호출의 하루(현지 날짜) 합계. 비운 칸은 기본값.
  3. 장부: 날짜마다 파일 하나 — `spend_file`이 있으면 이름 뒤에 날짜(`spend.json` → `spend-<날짜>.json`), 비우면 `<저장소>/output/_llm_spend/<날짜>.txt`. 같은 작업 폴더의 모든 프로세스가 파일 잠금으로 합계 하나를 나눠 쓴다. 정산·반환은 선차감한 날의 장부로 간다. 시험 자식(`case_env`)은 임시 장부.
  4. 외부 LLM은 단가(`PRICES` 또는 `LLM_PRICE_IN·OUT`)를 모르면 거부한다(`llm.chat`·`admit_turn` 같음). 한 번의 호출이 사후 정산으로 상한을 조금 넘을 수 있고, 다음 호출부터 거부된다.
  5. 응답 캐시, RPM, 시험용 가짜 LLM(`dev.llm_fake` — local만).
  6. 역할마다 설정 `dev.models.<llm|vlm|embed>.allow_external` 하나로 외부 허용을 정한다 — `llm.chat`을 부르는 모든 곳(분류 포함)이 `LLM_ALLOW_EXTERNAL`을 따른다(호출 인자 `allow_external=True`는 같은 효과). 내부망 서버(dev·prd)의 settings.yaml은 셋 다 `false`. 시험: `tests/server/common/test_llm.py`(local+1 허용 · local+없음 거부 · dev·prd+1 거부).
- 파일: `common/ai/guard.py`, `common/ai/llm.py`, `common/config/settings.py`.
- QA: `tests/server/common/test_guard.py`·`test_llm.py` · 통과. 서버 확인 refactor.md C-88.
- Status: done

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록과 DB 로그(두 앱)
- 이유: 두 앱의 사건·감사·성능 기록을 같은 형식으로 남긴다.
- 규칙 — JSON 줄:
  1. `common/core/jsonlog.py` `setup(app)` — 한 줄 키 `time, level, app, event, msg, request_id, run_id, span_id, duration_ms, err`. logger 이름 `applog.<앱>`. PC 기본 `logs/<앱>.jsonl`, 서버 stdout. 설정 `ops.log.level`(기본 INFO)·`ops.log.dir`. contextvars ID는 `settings.child_env()` 내부 신호로 자식에 전파.
  2. 비밀값 가림은 `jsonlog.masked(value)` 한 곳 — 라벨 패턴과 settings `SecretStr` 칸 값(4자 이상은 부분 문자열, 1~3자는 토큰 경계에서만). JSON 줄·sink·MCP args/result/err가 같은 함수를 쓴다.
  3. `err`는 allowlist — 예외 타입 이름(+errno 이름·CalledProcessError 종료 코드)과 `span.safe(...)` 고정 문구만. 외부 예외 문자열 원문은 남기지 않는다.
  4. dev·prd 시작 관문: 비어 있지 않은 비밀 설정이 8자(`MIN_SECRET_LENGTH`) 미만이면 칸 경로만 알리고 종료 2.
  5. MCP SDK 줄(`mcp.*`)은 stderr JSON으로만. 요청마다의 INFO는 `ops.log.level=DEBUG`일 때만. stdio 모드의 stdout은 JSON-RPC 전용.
- 규칙 — DB(`applog` 스키마, Alembic 갈래 `applog` — `common/store/db/migrations/versions/0001_applog_base.py`):
  1. 표: `mcp_log`(월 파티션, 키 `requested_at`) · `pipe_event`(월 파티션, 키 `ts_start`) · `pipe_run`(`run_id` PK, 시작 running → 종료 UPSERT).
  2. `common/store/logsink.py` `emit(table,row)` → 제한 큐(`tuning.ops.log.queue_size` 10000, 차면 즉시 버리고 `dropped`) → 배치 INSERT(`batch_size` 200 · `flush_sec` 1 · `db_timeout_sec` 2). DB 실패면 `ops.log.fallback_dir`(기본 `output/logs`) jsonl, 프로세스당 경고 한 번. 파일 로그는 이 예비 한 곳뿐이다 — 실행 출력은 컨테이너 로그(서버 stdout), 실행 기록 파일(`RUNLOG.md`·`runlog.jsonl`·`logs/<시각>_<도구>.log`)·질의 기록 파일은 없다(op-13). 종료 flush는 `shutdown_sec` 5초 안.
  3. 켜기 `ops.log.db_enabled` — 서버(두 이미지) 기본 true, PC 기본 false(op-13). 서버는 새 코드를 띄우기 전에 `migrate up --target all`(applog 포함). 보존 `retention_days` 90. `dbtool up --target applog`(현재 달 + 2개월 준비), 매일 `dbtool maintain --target applog`(다음 달 준비·만료 파티션 DROP·`pipe_run` DELETE). sink는 DDL을 하지 않는다.
- 규칙 — MCP 감사(`mcp_server/services/call_log.py`):
  1. 도구 호출마다 `applog.mcp_log` 한 행 — 성공·도구 오류·busy·timeout·HTTP 인증 거부(rpc_method NULL), initialize(rpc_method=initialize, clientInfo 뺌). 칸은 [db_schema.md §6](../architecture/db_schema.md). sink 실패가 도구 응답을 바꾸지 않는다.
  2. 본문: 마스킹 뒤 앞부분만 — 입력 `tuning.search.audit.max_input_bytes` 16384 · 출력 `max_output_bytes` 65536. `*_bytes`·`result_sha256`은 자르기 전 전체 기준. `parse_document`의 `content_b64`는 디코딩한 파일 sha256·바이트 수로 바꿈.
  3. `result_keys`: search = chunk_keys(순위 순)·evidence_status·filter·scope_docs · list_doc_fulltext = 건수·next_cursor·doc_keys · get_doc_fulltext = 건수와 파일별 name/kind/size/sha256/skip_reason · query_edw = row_count·columns · parse_document = job_id·engine·rep_path·text_chars · edw_meta = 단계·표·칸 수.
  4. 컨텍스트: `X-MCP-User`(없으면 `params._meta.user`) → knox_id, `X-MCP-Client`는 호출자 표시·콘솔 로그에만 쓰고 DB에는 남기지 않음(agent_id는 인증 체계가 생긴 뒤), Mcp-Session-Id(stateless라 도구 행은 대개 null). 유효한 UUID `X-Request-Id`는 그대로, 아니면 새 UUID를 응답 헤더로. 접속 소켓 주소는 client_ip에 남기고(사용자 11-04, 프록시 뒤면 프록시 IP) clientInfo는 남기지 않는다.
  5. 감사는 전용 데몬 스레드 하나가 처리한다(도구는 기다리지 않음). 본문 대기 큐 64건 + 바이트 합계 `tuning.search.audit.max_queue_bytes`(기본 268435456) — 넘으면 본문 없는 메타 행(`result_keys.audit_body_omitted=queue_full`, `error_code=audit_queue_full`).
- 규칙 — 파이프라인 추적:
  1. 실행 1건 = `pipe_run`(`pipeline/shared/runtrace.py` — code_fp·stack·settings_hash·문서 수·workers·cpu_max_load·mem_start_pct). 부모가 준 run_id가 있는 자식은 새로 시작하지 않는다. run_docs에서는 문서·단계마다 실행이 따로 생긴다.
  2. 문서×단계 = `pipe_event`(`common/core/span.py` `with span("extract.parse", doc_id=…) as s`) — 단계 이름 `extract.plan`·`extract.parse`(`attempt` — 시간 초과 재시도면 2)·`extract.shard`·`extract.warm`(프리페치 1회)·`extract.classify`(run_docs 레인 분류 1건 — `pipeline.extract.doc_lane_group.main()`, `metrics.group`, 파일이 없으면 fail)·`extract.download`(파일=문서 1건 — `metrics`에 `head_ms`·`download_ms`·`mbps`(순수 전송)·`lock_wait_ms`, 실패는 `external`)·`transform.represent`·`transform.figures`·`transform.structure`·`embed.bundle`·`load.pgvector`·`load.doc/chunk/chunk_term/stats`·`load.publish`·`proc.run`·`model.<role>`(모델 호출 1건당 1행 — `layer=model`, 부모는 호출한 단계 span, `doc_id`는 부모에서 이어받음, `metrics`에 토큰 수. 성공·실패 모두). 오류는 `status`·`err_kind`(env/timeout/doc/external/db).
  3. 60초마다 `stage='run.progress'`(완료/전체·docs/min·남은 시간·부하·메모리, 임베딩 중에는 unit=chunk).
  4. `run_id`가 없으면(MCP 검색·시험) span은 아무것도 하지 않는다. 계측 안의 예외는 삼키고 업무 결과를 바꾸지 않는다(프로세스당 stderr 경고 한 번).
  5. `cpu_ms`·`rss_peak_mb`는 Linux에서 프로세스에 하나만 도는 span만 채우고, 겹치거나 측정 못 하면 NULL.
  6. 분석: `python -m pipeline.tools.perf_report [<run_id>] [--since <시간>] [--top N] [--compare <run_id>…] [--runs] [--file output/logs/*.jsonl]` — 읽기 전용.
     다운로드(`extract.download`)는 `--since` 요약에 ■ 다운로드 표(크기 구간별 순수 전송 mbps·head·잠금 대기)로 나온다. 서버에서는 `podman exec data-pipeline python -m pipeline.tools.perf_report --since <시간>`으로 본다.
- 파일: `common/core/{jsonlog,span,exitclean}.py`, `common/store/logsink.py`, `mcp_server/services/call_log.py`, `pipeline/shared/runtrace.py`, `pipeline/tools/perf_report.py`, `pipeline/extract/{doc_lane_group,fetch_docs}.py`.
- QA: `tests/server/common/test_{jsonlog,logsink,span,span_soft,call_event}.py`·`tests/server/mcp/test_call_log.py`·`tests/server/pipeline/test_{runtrace,perf,span_stages,doc_group}.py`·`tests/general/common/test_applog_pg.py`(PC 임시 PG 스키마) · 통과. 서버 적용 refactor.md C-79·C-80.
- Status: done
