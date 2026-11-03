# 운영 — 실행 관리·러너·계정·종료·로그

[PRD.md](../PRD.md) 카테고리. 실행 관리(pl-10·pl-23·pl-24·pl-18), 서버 러너 `run_docs.py` 레인·대기열(rn-01~04), 종료 정리(pl-27·pl-44), EDW 계정(op-03), 모델 호출 가드(pl-11), 로그(op-01). 설정 파일은 [ops-settings.md](ops-settings.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-10 · pl-23 · pl-24 · pl-18 · rn-01 · rn-02 · rn-03 · rn-04 · pl-27 · pl-44 · op-03 · pl-11 · op-01.

<a id="pl-10"></a>
## pl-10 · 실행 관리(오케스트레이션)
- 결정(사용자 10-31 범위 축소 grill): trigger 서버(/jobs·/upload·CHAIN_STRUCTURE_URL·serve-trigger)를 **지운다** — 새 문서는 run_docs 정기 실행이 FileStorageMap으로 고름(C10). DRM과 무관(DRM 자동 복호화 기능은 없음).
- 이유: 서버는 문서 수천 건을 사람 없이 돌린다.
- 무엇: CLI `parse`·`structure`·`load`·`night`(마감 시각, 다음 밤에 이어서)·`run-stack`·`show-stack`·`smoke`·`selftest`. 이미지 entrypoint가 `dedup`·`prepare`·`publish`·`full`·`idle`(상주 컨테이너가 떠 있기만 — run_docs가 docker exec)·`migrate`·`check`를 더한다(`deploy/docker/entrypoint.sh`). 서버 flow 러너(EDW 목록, 12개 미리 받기, light/medium/vlm 레인, 문서마다 컨테이너, `parse_document` 작업에 양보). (trigger 서버 `/jobs`·`/upload`·`serve-trigger`·`CHAIN_STRUCTURE_URL`은 11-01에 지움 · `compare-parse`·`compare-all`은 11-01에 지움 — [test.md#e2-10](test.md#e2-10).) (문서별 병렬 파싱 `parse_parallel.py`는 10-30에 지움 — [transform-cleanup.md#pl-35](transform-cleanup.md#pl-35).)
- 서버 flow 러너 요구(사용자 10-22·10-23 — 원문 [../history/run_docs_req.md](../history/run_docs_req.md), 바뀐 값은 rn-01·rn-02·[transform.md#pl-22](transform.md#pl-22)):
  - 문서별 flow(배치 장벽 없음) · warm 12(진행 중 제외, 끝나면 tmp 지움 — 10-29부터 20) · 컨테이너 하나에 worker 4.
  - VLM 동시 12(figure·vlm_page 포함), 문서 병렬 4, 문서당 VLM 4·OCR 1, vlm_page 끔, OCR dpi 150. 구조화+적재도 문서 단위 — 임베딩 묶음 호출(32 → 12)·문서당 병렬 4, BM25 병렬 4, 단계별 시간 기록.
  - 튜닝: `PIPE_PROCS=3`, CPU 75~85%, `RAPIDOCR_PAGE_WORKERS`·OCR threads 3(→ 2 검토), CPU 게이트 1.15 → 1.3/1.1.
  - 3클래스: warm에서 무게 평가(과거 소요 시간 규칙), vlm_page는 스캔 PDF처럼 꼭 필요한 문서만, 1/2/1 + 빈 레인 가져가기, light 1개 강하게 점유, 전담 분류 먼저, light 전용 executor. MCP 업로드가 오면 medium 전담 1개를 멈추고 먼저.
  - 속도: phase 1 건너뛰기(→ pl-22), 끝난 문서 건너뛰기, parse_qa 가볍게, 10-23 OCR 끔. SSH가 끊겨도 작업은 계속(nohup 확인).
- 파일: `pipeline/cli.py`, `deploy/host/scripts/run_docs.py`(서버 전용 — PC에서 실행 금지), `docs/history/run_docs_req.md`, `docs/architecture/run_docs_design.md`.
- Status: done — trigger 서버 지움 11-01(`feature/scope-cut-pipeline`): `pipeline/trigger_server.py`·시험 `test_trigger_server`, entrypoint `serve-trigger`(→ `idle` — 상주 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`(11-03부터 `data-pipeline` 하나)는 run_docs의 docker exec 대상이라 남기고 떠 있기만), compose의 `TRIGGER_MODULE`·`/health` 검사, `deploy/host/scripts/parse_trigger_test.py`, 설정 절 `pipeline.service.trigger`(`required.tokens.trigger` 포함 — 남으면 경고만: `common/config/layout.py`의 자리는 옛 settings.yaml이 거부되지 않게 남기고 sample 대조에서만 뺌(`sample.LAYOUT_GONE`) — layout.py는 code_fp에 들어가 손대지 않음), `settings_env.sh`의 trigger 포트. `common/core/exitclean.py`의 SIGTERM 처리는 모든 프로세스가 쓰는 일반 처리라 그대로(주석의 trigger_server 예시만 남음 — 고치면 code_fp가 바뀜).

<a id="pl-23"></a>
## pl-23 · 증분 실행만, 전체 재파싱은 명시적인 전체 e2e
- 결정(사용자 10-31 범위 축소 grill): run_docs 하나로 합침(pl-18 결정).
- 이유: 엔진·핸드오프·코드 핑거프린트가 모든 문서에서 바뀌었다. 전체 자동 재파싱은 밤 작업 시간을 넘긴다(C-52, C-08).
- 결정(사용자 10-29 grill): 밤 작업과 `run_docs`는 핑거프린트가 바뀌어도 **새** 문서만 처리한다. "새" = `AI.FileStorageMap.s3_key`가 아직 `AI.ParsingMeta`에 없음(s3 키만 — 갱신 시각 확인 없음, `run_docs`는 이미 이렇게 동작). 전체 재파싱은 사람이 전체 e2e를 시작할 때만(가끔 — 로직을 바꾼 뒤, 결과를 검토). 이 판의 첫 적재는 전체 e2e 한 번.
- 결정(사용자 10-30 grill): 밤 배치는 꺼 둔다(systemd 타이머는 켜지 않음). 나중에 사람이 settings.yaml에서 켠다. → 켜기·끄기와 시각은 아래 새벽 일정 키 하나가 정한다(null = 끔) — 그 키를 구현하면 지금의 `pipeline.host.nightly.enabled`는 없어진다(그때까지 서버 절차는 enabled false).
- 결정(사용자 10-30): 새벽 배치 계획을 settings.yaml 키(파라미터)로 — null이면 새벽 배치 안 함, 값이 있으면 돈다([pl-32](load-schema.md#pl-32)). 켜기·끄기 스위치와 시각을 이 한 값이 정한다 — 구현(10-30 `feature/registry-success-only`): `pipeline.host.nightly.time`(`NIGHTLY_TIME`, HH:MM — 비우면 없음, 꼴이 틀리면 설정 읽기에서 거부) · 타이머 5분마다 + `trigger.sh scheduled` · `nightly.enabled` 지움(남아 있으면 경고만).
- 지금 안 씀: FileStorageMap 갱신 시각 — 가정한 칸 `last_modified_time`, 나중에 EDW 예시에 추가([pl-25](load-schema.md#pl-25)).
- 파일: `deploy/host/scripts/run_docs.py`(처리 끝난 집합), `pipeline/cli.py`(`night` — 같게 동작하는지 확인).
- 결정(사용자 10-30 PRD grill): C10 — '새 문서' 후보는 모든 입구(run_docs·night)에서 EDW `FileStorageMap`에 있고 `ParsingMeta`에 없는 것. 문서 대장은 숨김·판 관리에만 쓴다.
- C10 구현(11-01 `feature/scope-cut-search` — 사용자 11-01 Q1(a)): 파싱 `--source`·`--max-new` 고르기 = 원천 이름(FileStorageMap) 중 `s3_key`(manifest — 없으면 이름)에 ParsingMeta 끝난 행이 없는 것(`pipeline/cli.py` `_unparsed` · `parsing_meta_db.done_source_keys` — 읽기 계정, PC는 `RDB_SQLITE` 대역). **파싱 입구에 EDW 읽기가 생김** — 서버에서 못 읽으면 종료 4, PC는 받은 목록 그대로 + 로그 한 줄. 실패 문서(행 없음)는 다음 실행에 다시. 문서 대장 고르기(pl-32 2c)는 지움. "끝남" = `parse_status` ok·partial·skipped_dup(사용자 11-01) — not_parsed·skipped_disk_cap·실패·행 없음은 다시 고름. ParsingMeta 상태 갱신 길은 지운 채(게시는 넣기만 — 사용자 11-01).
- 결정(사용자 11-02): 전체 e2e는 local·dev·prd 셋에서 돈다. dev는 settings.yaml이 가리키는 대상(가짜 폴더든 실제든)에 쓴다. **전체 문서 실행은 prd에서만, 새 원천별 스키마 이름으로**(새 `PG_SCHEMA`) — 판 0002가 기준 스키마의 옛 표를 지우므로 prd는 반드시 새 `PG_SCHEMA`를 쓴다(refactor.md C-74). 옛 gold 스키마는 2주 남긴 뒤 DB 담당자가 백업하고 지운다. 옛 `struct` 스키마도 DB 담당자가 백업하고 지운다. 절차: [release-and-patch.md §8](../operations/release-and-patch.md#8-020-배포--사람이-할-일).
- 결정(사용자 11-02 — 새벽 배치): 시작 시각·문서 수 상한·마감 시각이 settings.yaml 칸이고, 비면 돌지 않는다. 칸 이름 어긋남 고침(아래 한 것) — 호스트 셸·systemd·시험은 `ops.nightly.time`, 설정 모델·시험(`tests/server/pipeline/test_nightly_time.py`)은 `pipeline.host.nightly.time`을 쓴다. 상한·마감 칸은 [pl-18](#pl-18)의 상한·마감과 함께.
- 한 것(11-02 `feature/nightly-key` — 사용자 11-02): 새벽 배치 칸 셋 — settings.yaml `ops.nightly.time`(시작)·`max_docs`(새 문서 수 상한)·`deadline`(마감, HH:MM) — 하나라도 비면 `trigger.sh scheduled`가 조용히 끝. `run_docs.py`에 `--max-docs`(끝난 문서를 뺀 뒤 앞에서 — 옛 `--limit`은 그 전에 잘라 시험용)·`--deadline`(지나면 새 문서를 받지 않음)을 더함. 칸 이름은 설정 파일 기준 `ops.nightly.*` 하나(모델 안 이름 `pipeline.host.nightly`는 코드만 — 문서·시험 문구를 맞춤). 시험 `test_trigger_gate`·`test_nightly_time`·`test_run_docs`(`deadline_at`).
- Status: done (11-03 `feature/rundocs-flow` 확인) — 고르기는 `pipeline/cli.py` `_unparsed`, run_docs `--skip-done`은 `DONE_STATUSES`(ok·partial — gold_version도, skipped_dup — `test_done_keys_match_parsing_meta`). 남은 서버 일(전체 e2e prd 실행·새벽 배치 켜기)은 사람 — refactor.md C-72·C-74.

<a id="pl-24"></a>
## pl-24 · `run_docs` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 지금은 게시가 gold를 기다리고, `cleanup_doc`이 실패해도 원본을 지운다.
- 결정(사용자 10-29 grill): 원본은 Object Storage에서 수집 서버로 받아 파싱하고, silver 게시가 성공한 뒤에만 지운다. 파싱 실패 → 원본은 남기고 원인 + 걸린 시간을 로컬에만 기록, EDW에는 아무것도 안 씀. gold 실패 → EDW 행은 남고 `gold_status` = failed(+ 이유). gold는 silver에서 다시 만들 수 있다.
- 새 EDW 칸 `AI.ParsingMeta.gold_status`(pending · ok · failed) + 이유 — DDL은 DB 담당자에게(회사 DB, Alembic 아님) — 검토 등급 A. 줄인 ParsingMeta 칸 목록은 [pl-25](load-schema.md#pl-25).
- `valid_env/`로 하는 로컬 시험은 문서를 먼저 임시 폴더로 복사해 거기서 돌린다(제자리에서 돌리지 않음).
- 파일: `deploy/host/scripts/run_docs.py`(`doc_flow`, `cleanup_doc`, 처리 끝난 질의), `docs/operations/parsing_meta_mssql.sql`, 게시(`parsing_meta`).
- 결정(사용자 10-30 PRD grill): C3 — 파싱이 통째로 실패하면 ParsingMeta에 쓰지 않는다(이 행 그대로). (허브 10-31 고침 — 아래) 실패는 로그·문서 대장에만 남고 다음 실행에서 다시 후보가 된다.
- 결정(허브 10-31, 최신 결정 우선): 문서 대장도 성공했을 때만 쓴다([pl-12](load.md#pl-12)·[pl-32](load-schema.md#pl-32) — 실패 횟수 없앰). 실패는 **로그에만** 남고, ParsingMeta에 행이 없으니 다음 실행에서 다시 후보가 된다(C10).
- 한 것(11-03 `feature/rundocs-flow`): `run_docs.py` 문서마다 파싱 → 게시 대기열(게시 스레드 1개 — 구조화가 업로드·EDW 쓰기를 기다리지 않음) → 게시 성공이면 원본(warm `.bin`·`docflow/<seq>/_source_files`) 삭제 → 구조화 대기열(gold — build_bundle·pgvector_load) → `docflow/<seq>` 임시 삭제. 파싱 실패·게시 실패 = 원본을 남기고 로그에만(gold로 안 감, EDW에 안 씀). gold 실패 = 게시한 silver·EDW 행은 그대로, 로그에만 — `gold_version` 칸(C-76 ③)이 있으면 비어 있어 다음 `--skip-done`이 다시 고른다(칸이 없으면 못 고름 — 이 판은 칸이 생긴 뒤 배포, C-81). 새 파싱을 멈추는 상한 `struct_backlog`는 게시 대기 + 구조화 대기를 본다(`queue_depth.jsonl`에 `pub_wait` 더함). 시험 `test_docs_flow.test_doc_order_and_exit_code`(표).
- 남음: `gold_status` 칸(DDL — DB 담당자, refactor.md C-81). 칸이 생기면 `gold_one()` 옆 TODO 자리에서 failed·이유를 적는다.
- Status: done — `gold_status` 칸 쓰기만 남음(C-81 — DB 담당자 DDL 뒤).

<a id="pl-18"></a>
## pl-18 · 중간에 멈춰도 `night`/`full`이 종료 코드 0
- 결정(사용자 10-31 범위 축소 grill): 서버 입구는 **run_docs 하나**. night·full 입구를 없애고, 정기 실행(새벽 배치)은 타이머가 run_docs를 부르는 꼴로(night = run_docs를 바깥에서 부르는 것).
- 이유: 스케줄러가 실패를 못 본다(C-33).
- 결정(사용자 10-30 grill): 종료 코드 — 대상 0건 = 0, 실패 = 1, 마감 시각 도달 = 75.
- 파일: `pipeline/cli.py`(`night`), `deploy/docker/entrypoint.sh`(`full`).
- 결정(사용자 11-01 기본값 — 허브 11-01): 새벽 run_docs에 문서 수 상한 · 마감 시각 · 사람이 따로 돌린 run_docs와 겹치지 않게 하는 잠금을 둔다(지금은 systemd `TimeoutStartSec=6h`뿐 — #83).
- Status: done(11-03) — 11-01(`feature/scope-cut-unused`) 옛 입구를 지움: `pipeline.cli`의 `night`·`run-stack`·`structure`·`load`(+ 끝 표시 확인 `need()`), 이미지 명령 `night`·`run-stack`·`full`·`structure`·`load`, `trigger.sh` `night`·`structure`·`load`·`all`, compose job `structure`(`load` 서비스는 `run_tool.sh` 도구용으로 남김 — 명령 `help`), 죽은 설정(`ops.nightly.max_new`·`modules`·`publish`, `ops.nightly_run.deadline`·`parse_deadline`, `dev.pipeline.allow_common_mismatch` — 남으면 경고만). 새벽 배치는 systemd 타이머 → `trigger.sh scheduled` → `run_docs.py --start-offset 0 --skip-done`(서버 확인 refactor.md C-72). 남음: 종료 코드 규칙(대상 0건 = 0, 실패 = 1, 마감 = 75)을 run_docs에 만든다.
- 한 것(11-03 `feature/rundocs-flow`): `run_docs.py`가 종료 코드를 돌려준다 — 0 = 대상 0건·모두 끝, 1 = 실패 문서(파싱·게시·gold) 하나라도, 75 = 마감 도달(실패 없음) 또는 다른 run_docs가 도는 중, 2 = 설정 문제(전과 같음). 실패와 마감이 함께면 1. 겹침 잠금은 `run_docs.py` 안 한 곳(`flock` `batch_progress/run_docs.lock` — 프로세스가 죽으면 커널이 풂, 사람이 trigger 없이 돌려도 같은 잠금). 문서 수 상한·마감은 11-02 `--max-docs`·`--deadline`. 시험 `test_docs_flow.test_exit_codes`·`test_lock_blocks_second_run`(Linux·macOS·WSL — Windows는 건너뜀).

<a id="rn-01"></a>
## rn-01 · 레인 정책을 표 하나로 — 담당 레인 먼저, 허용한 레인만 가져오기
- 범위: `deploy/host/scripts/run_docs.py`(서버 호스트에서 이미지 밖으로 실행 — 핑거프린트 영향 없음). 설계 [../architecture/run_docs_design.md](../architecture/run_docs_design.md), 발화 기록 [../history/run_docs_req.md](../history/run_docs_req.md).
- 사용자 10-29: "data-pipeline 하는데 3개 lane으로 해서, light/medium/vlm 구분해서 배분하고, 특정 lane은 담당, 일부 lane은 steal 허용하는 대신 우선순위는 담당 lane으로 지정. queue 관리해서 진입 시점 개수와 중간 개수 등을 관리."
- rn-01 전 러너(3레인 1/2/1·warm·MCP 멈춤): [../history/run_docs_history.md](../history/run_docs_history.md) 끝.
- 이유: 규칙이 `lane_worker()`에 하드코딩돼 있었다(light/vlm은 medium을 안 가져감, 가장 긴 다른 대기열 먼저, vlm은 `VLM_CAP` 상한) — 죽은 분기도 있고 워커 수가 상수라 조정하려면 코드를 고쳐야 했다.
- 파일: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`, `docs/architecture/run_docs_design.md`.
- 겹침: 파싱 phase 없애기([transform.md#pl-22](transform.md#pl-22), `feature/r2-phase`)는 러너에서 `PARSE_PHASES` `--set`만 뺐고 레인은 건드리지 않았다.
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
- 결정(사용자 10-31 범위 축소 grill): 선택지 1로 바꾼다(사용자): MCP parse_document 전용 컨테이너를 따로 띄우고(같은 이미지), extract 단계 없이 파싱 함수만 부르며, CPU 가중치(cpu_shares/cpu.weight)를 가장 높게 준다. nice는 그대로 둬도 됨.
- 이유: 일괄 파싱이 CPU를 다 쓰면 `parse_document`(사람이 기다리는 요청)가 느려진다. 일괄 엔진 자식은 nice +10(`pipeline.extract.low_priority`, [transform.md#pl-22](transform.md#pl-22))이지만 nice는 한 세션·autogroup 안에서만 듣고, 컨테이너끼리는 cgroup CPU 가중치가 정한다(refactor.md C-65 ⑥).
- 선택지:
  1. 같은 이미지로 컨테이너를 따로 띄우고 cgroup `cpu.weight`로 나눔(허브 추천). 장점: 컨테이너끼리도 확실히 먼저, 서버에서 숫자로 조정. 단점: 컨테이너·compose·systemd 하나 더, 메모리 더, 서버 설정 일.
  2. 같은 컨테이너(`data-pipeline-parse`) 안에서 nice(지금 결정 — 사용자 10-30). 장점: 구성 변경 없음, `low_priority` 재사용. 단점: 다른 컨테이너·세션과는 안 겨룸(`sched_autogroup_enabled=1`), 효과는 서버에서 재 봐야 앎.
- 서버 확인(C-65 ⑥): 일괄 파싱만 / + `parse_document` 동시의 응답 시간 비교 — 효과 없으면 선택지 1.
- 파일: `deploy/host/compose/`, `pipeline/mcp_parse_service.py`, `common/core/resources.py`.
- 결정 다시(사용자 11-03): 일괄 컨테이너를 하나(`data-pipeline` — 파싱·구조화·적재)로 합친 뒤에도 parse_document는 **전용 컨테이너**로 뗀다(선택지 1 재확인).
- 한 것(11-03 `feature/rundocs-flow` · 파일 나눔 `feature/compose-split` — 사용자 11-03 "컨테이너마다 compose로 각각 띄우기"): `compose.pipeline-mcp.yml`(개발 서버 짝 `compose.code.pipeline-mcp.yml`)에 `data-pipeline-mcp`(같은 이미지, entrypoint `parse-service` = `pipeline.mcp_parse_service`가 주 프로세스, 127.0.0.1:8766) — `cpu_shares` 4096(일괄 `data-pipeline` 1024 — cgroup v2는 `cpu.weight`로), 상한 CPU 2·메모리 8g, 결과 폴더만 붙임(작업 폴더 `mcp_parse/jobs`는 `run_docs.py`가 보고 medium 레인 양보). 옛 손 기동 `docker exec -d … mcp_parse_service` 없음 — 죽으면 `restart`, 꺼지면 `mcp_up.sh`(keepalive 타이머)가 띄움. 시험 `tests/general/deploy/test_compose.py`.
- 남은 것: ① 자원 칸(`PARSE_MCP_CPUS`·`PARSE_MCP_MEM_LIMIT`·`PARSE_MCP_CPU_SHARES`)은 settings.yaml 칸이 아직 없다 — 설정 모델이 지문 파일이라 0.2.0 지문 배치에서(refactor.md C-83). ② "extract 단계 없이 파싱 함수만"(10-31 결정)은 앱 코드 몫이라 안 함. ③ 서버 확인(C-65 ⑥): 일괄 파싱 중 `parse_document` 응답 시간.
- Status: dev — 컨테이너·CPU 비율 한 것, 서버 확인·자원 칸 남음.

<a id="rn-04"></a>
## rn-04 · run_docs 작은 수정·레인 테스트
- 결정(사용자 10-30, C-59 ⓑ): MCP 감시 루프의 5초마다 `jobs_dir` 전체 `rglob`·`stat` → 최근 작업 폴더만 또는 심장 박동 파일 · 효과 없는 `--workers`를 시작 로그에서 뺌 · 남은 빈 분기 정리 · 흐름 테스트에 medium·vlm 레인·MCP 양보 길.
- 파일: `run_docs.py`, `tests/general/deploy/test_docs_flow.py`.
- Status: done (10-30, `feature/rundocs-fixes`) — ① `mcp_busy`는 이름 날짜(`<YYYYMMDD>-…`)가 어제·오늘·내일인 작업 폴더만 본다(지난 날의 끝난 작업 파일은 stat 안 함 · 하루 넘게 도는 작업은 놓침 — 작업은 분 단위) ② 안 쓰는 `PARSE_WORKERS` 지움 — `--workers`는 옛 호출이 깨지지 않게 받기만(시작 로그에는 이미 안 찍힘) ③ `lane_worker`의 빈 분기 2개는 rn-01(`pick_lane`)에서 이미 없어짐 ④ 테스트: medium·vlm 레인과 vlm 동시 상한, MCP 양보(medium 전담 워커 쉼), `mcp_busy` 표.

<a id="pl-27"></a>
## pl-27 · 프로세스 종료 정리 — 임시 설정 파일·PID 기록 지움, 자식 회수
- 이유: 덮기 설정 파일(`settings-*.yaml`, refactor.md C-46)이 OS 임시 폴더에 쌓이고, 시간 초과로 끝낸 자식의 손자(soffice 등)가 고아·좀비로 남았다(사용자 10-30에 좀비 PID를 봄). 파이썬은 SIGTERM을 받으면 `finally`·`atexit` 없이 바로 끝나 아무것도 못 지웠다.
- 결정(사용자 10-30): ① 덮기 설정 파일은 그 파일을 만든 프로세스가 끝날 때 지운다 — 정상 종료·오류·SIGTERM 모두 ② 프로세스가 끝날 때 그 프로세스가 띄운 자식도 끝내고 회수한다(좀비 없음) · PID 기록 파일도 지운다.
- 한 곳: `common/core/exitclean.py` — `remove_at_exit(경로)`(이 프로세스가 끝날 때 지움) · `track(Popen, group)`(끝날 때 아직 돌면 끝내고 `wait`로 회수) · `stop(p, group)`(group=새 묶음으로 띄운 자식 — POSIX는 묶음째 SIGTERM → 10초 → SIGKILL, Windows는 `taskkill /T`). import 때 SIGTERM 처리기를 단다(기본값일 때만 — `trigger_server`처럼 이미 단 곳은 그대로): 처리기 안에서 바로 정리(작업 스레드 join보다 먼저)한 뒤 `SystemExit(143)`, 정리 중 두 번째 SIGTERM은 무시. 정리 순서: 자식 전부 SIGTERM → 한 마감(10초) → 남은 것 SIGKILL·회수 → 파일 지움. 정리를 시작한 뒤 띄운 자식은 바로 끝낸다.
- 누가 파일을 맡나: `settings.put`·`child_env`가 만든 덮기 파일 = 그 프로세스 · `settings.isolated` = 블록이 끝날 때 · `--set`(`setarg`, POSIX는 `execve`로 다시 뜸 — atexit가 안 돎) = 다시 뜬 프로세스(내부 신호 env로 넘김) · `python -m common.config.overrides` 출력 파일 = 지우지 않음(다른 프로세스가 읽음 — 사용법 `SETTINGS_FILE=$(…)`).
- 연결한 곳: `resources.gated_popen`(파이프라인 자식 전부 — `start_new_session`으로 띄웠으면 묶음째) · `pipeline/extract/resources.kill_group`(→ `stop(group=True)`) · `mcp_parse_service` 작업 자식과 PID 기록 `service.json`. 자식을 새 세션으로 옮기지는 않음 — 바깥 `kill_group`(`cli._run_until`·parse 서비스)의 묶음 SIGKILL이 손자까지 닿게(코드 리뷰 10-30).
- 남은 한계: `subprocess.run`으로 띄운 짧은 자식(`load/index.py`·`eval/server_checks`·`cli selftest` 등)은 추적 안 함 — SIGTERM 때 부모가 먼저 끝나면 그 자식이 읽던 덮기 파일이 먼저 지워질 수 있음 · 주 스레드가 아닌 곳에서 처음 import되면 SIGTERM 처리기를 못 닮(정상·오류 종료 정리만) · SIGKILL·OOM은 정리 못 함 · 컨테이너 PID 1 고아 회수는 compose `init: true`(이미 있음) · 호스트 `run_docs.py`는 파이썬 공용 코드를 안 씀(systemd가 cgroup째 정리) · `run_all`·`pptx_render`의 시간 초과는 전처럼 그 자식만 끝냄(손자는 바깥 묶음 정리·`init`이 맡음).
- 파일: `common/core/exitclean.py`, `common/config/settings.py`, `common/config/setarg.py`, `common/core/resources.py`, `common/core/fingerprint.py`(분류 목록), `pipeline/extract/resources.py`, `pipeline/mcp_parse_service.py`.
- 시험: `tests/server/common/test_exitclean.py` — 정상·오류 종료(모든 OS) · SIGTERM과 `--set`(execve)(POSIX 전용, Windows는 건너뜀 — python:3.12-slim에서 확인) · overrides 출력 파일은 남고 isolated는 블록 끝에서 지움.
- 결정(사용자 10-30 PRD grill): S1 — done으로 닫는다. 후속(임시 파일 정리)은 새 todo 행으로.
- 한 것: `feature/exit-cleanup` 병합. code_fp 모든 레이어가 바뀜(`common/` 공용 의존).
- Status: done — 서버 확인은 refactor.md C-68, 강제 종료로 남은 임시 파일 정리는 [pl-44](#pl-44).

<a id="pl-44"></a>
## pl-44 · 강제 종료로 남은 임시 설정 파일 정리
- 결정(사용자 10-31 범위 축소 grill): **요건에서 지운다** — 남은 임시 파일은 두어도 된다. 다시 돌릴 때는 Object Storage의 silver와 EDW의 silver 성공 시각으로 재사용(사용자).
- 이유: pl-27은 정상·오류·SIGTERM 종료 때 덮기 설정 임시 파일을 지우지만, SIGKILL·OOM으로 끝나면 남는다(사용자 10-30 PRD grill S1 — pl-27은 done으로 닫음).
- 결정(사용자 10-30 grill 12~13차 — refactor.md C-46): 다음 시작 때, 만든 프로세스가 더는 없는 임시 설정 파일(`settings-*.yaml`)을 지운다.
- 파일: `common/core/exitclean.py`, `common/config/settings.py`.
- Status: dropped (사용자 10-31 범위 축소)

<a id="op-03"></a>
## op-03 · EDW 접속 하나, 공용 계정 둘(읽기·쓰기)
- 이유: 사용자 10-29 "계정 하나로 합침" — 블록 넷(`common.connections.edw`, `common.connections.parsing_meta`, `pipeline.connections.rdb`, `mcp.edw_query`)이 EDW 하나에 대해 저마다 서버/포트/DB/사용자/비밀번호를 들고 있어 서버 파일에 같은 값이 네 번 반복된다.
- 정한 것(사용자 10-29, grill 1~2차):
  - 벡터는 pgvector에만, EDW에는 절대 안 넣음. EDW 벡터 길을 지운다: `pipeline/load/edw_insert.py`(`usp_vec_load`), `mcp_server/services/search/edw_search.py`, `retriever.py`의 EDW 분기, `common/store/edwdb.py`, 설정 블록 `common.connections.edw`(+ `EDW_LOAD`).
  - ParsingMeta, FileStorageMap, RDB 원천 표, `query_edw`는 같은 EDW 서버·DB에 있다 → 접속 블록 하나.
  - 공용 계정 둘: **읽기**와 **쓰기**. MCP 서버는 읽기만. 파이프라인은 기능별로 고른다: 읽기(RDB 원천 목록, discover, 고객 목록, FileStorageMap, ParsingMeta 상태) → 읽기, ParsingMeta 게시(INSERT/UPDATE) → 쓰기. 호스트 러너 `run_docs.py`의 읽기 → 읽기.
  - PC 대역: 모든 표(AI, CRMS, LAS, SFDC 표를 함께)를 담은 sqlite 파일 하나. `query_edw`는 계속 읽기 전용으로 연다.
  - 옛 키: 옮겨 주는 기능 없음 — sample을 다시 만들고 서버 파일을 다시 채운다. 옛 칸은 `Section.REMOVED`로(한 판 동안 경고만, 시작 거부 없음). env-guide + refactor.md C-xx에 서버 할 일을 적는다.
- 규칙에서 정한 것(묻지 않음):
  - 블록 `common.connections.rdb`(두 앱이 씀 → `common`, CLAUDE.md §1): `host`, `port`, `database`, `connect_kwargs`, `sqlite`, `read.{user,password}`, `write.{user,password}`. 드라이버는 pymssql만(pyodbc 선택지는 지운 벡터 길 것).
  - 목적별 항목은 제자리: `PM_TABLE`, RDB `engine`/`bucket`/`columns`/거르기, `query_edw` `enabled`/`tables`/`tables_strict`/상한.
  - `CONN_FILE`(`EDW_CONN_FILE`, `EDW_QUERY_CONN_FILE`) 없앰 — 비밀값은 settings.yaml에만(§3).
  - sqlite: 코드가 파일 하나를 스키마 별칭(`AI`, `CRMS`, `LAS`, `SFDC`)마다 ATTACH해 `AI.ParsingMeta` 같은 SQL이 그대로 돈다. RDB 원천에 PC 시험용 `engine: sqlite`를 더한다(지금은 csv만).
  - code_fp: `settings.py`와 `retriever.py`(레이어 r)가 바뀜 → 모든 레이어 code_fp가 바뀜. 이번 차례의 핑거프린트 변경에 함께 싣고 전후를 커밋에 적는다.
  - 검토 등급 A(DB 계정, 운영 접속): PR에서 사람 검토, Claude 검토로 대신하지 않음.
- 겹침: `deploy/host/scripts/run_docs.py` 116~134줄 근처가 PM 키를 날 YAML에서 읽는다 — parse-phase 작업 몫, 새 키 이름을 그 담당에게 넘긴다.
- 수용 기준: 길마다 표 시험 하나(읽기·쓰기 계정 선택, MCP는 쓰기 비밀을 받지 않음, sqlite 파일이 PM 쓰기 + query_edw 읽기 전용 + RDB 원천 읽기를 모두 받음). `common.config.sample --check`, `keyscan --check`, 전체 `pytest tests/`와 `selftest`가 기준선. `EDW_SERVER|PM_DB_|RDB_USER\b|EDW_QUERY_SERVER|usp_vec_load` grep = REMOVED·이력 밖에서 0.
- 파일: `common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`, `common/store/{parsing_meta_db,edwdb,mssql}.py`, `pipeline/extract/{source,rdb_discover}.py`, `pipeline/transform/structure/gen_roster.py`, `pipeline/load/{parsing_meta,edw_insert}.py`, `mcp_server/services/{edw_query,search/edw_search,search/retriever,search/shaping}.py`, `valid_env/edw/`, 시험, `docs/operations/{env-guide,server-guide}.md`.
- 만든 것: `common.store.mssql.login(role)`(계정) · `mssql.standin(path)`(파일 하나를 AI·CRMS·LAS·SFDC로 ATTACH, 기본 읽기 전용) · 빌더 `python -m validation.e2e.edw_standin` → `valid_env/edw/edw.sqlite`(스키마별 .sqlite 넷은 지움, .sql 원본은 유지) · `query_edw` sqlite 허용 목록 = 대역 표 아홉. 안 한 것(필요 없음): `rdb_discover`/`gen_roster`용 sqlite(서버 도구).
- MCP 프로세스: `mcp_server.main`이 먼저 `settings.edw_read_only()`를 불러, 공용 settings.yaml 하나여도 그 설정 객체의 쓰기 계정은 비어 있다(사용자 10-29 "정해진 항목만", 검토 P1). 파일 자체는 컨테이너 안에서 여전히 읽힌다.
- 시험: `tests/server/common/test_edw_login.py`, `tests/general/common/test_edw_standin.py`.
- Status: done (10-30, PR #5 병합) — 서버 설정 다시 채우기와 DBA 계정 준비는 refactor.md C-67.

<a id="pl-11"></a>
## pl-11 · 모델 호출, 비용, 외부 전송 가드(공용)
- 이유: 폐쇄망 서버는 외부 모델을 절대 부르면 안 되고, PC 호출은 싸게 유지해야 한다.
- 무엇: OpenAI 호환 역할 llm/vlm/embed(rerank는 10-29에, ocr_vlm은 10-30에 지움 — [transform-cleanup.md#pl-31](transform-cleanup.md#pl-31)). 서버(dev/prd)는 외부 모델 거부. 외부 전송은 `*_ALLOW_EXTERNAL` + `RUN_ENV=local`이어야 함. 예산, RPM, 비용 장부, 응답 캐시, 시험용 가짜 LLM.
- 10-29(사용자): 합성 문서 선언 `LLM_SYNTHETIC_TRUTH` 잠금 삭제 · 외부 허용은 루트 settings.yaml에 둬도 됨(설정 창구는 하나).
- 파일: `common/ai/guard.py`, `common/ai/llm.py`(옛 `adk.py` 합침 — 0.2.0), `common/config/settings.py`.
- 결정(사용자 11-02): 개발 서버(dev)부터 내부망 GLM, PC(local)는 OpenRouter(유료 — 상한은 CLAUDE.md §7).
- 11-03(사용자): PC 비용 스위치 `no_paid_calls`(NO_PAID_CALLS)·`max_calls`(LLM_MAX_CALLS)·`external_max_docs`·`external_max_questions`·`external_scope`를 지움 — 코드·설정·sample·시험·문서. 옛 설정 파일의 칸은 경고만(`layout.REMOVED`). 남긴 것: 지출 상한 `budget_usd`와 장부 `spend_file`(자식 프로세스·검증 페이지가 같은 장부를 나눠 쓰는 유일한 길이라 설정으로 둠), 모든 `*_ALLOW_EXTERNAL`, 서버(dev/prd)의 외부 모델 거부. answer_gen의 "외부 호출이면 예산 필수" 범위 검사(check_scope)도 함께 없어짐. 호출 수는 `usage()` 집계로만 센다.
- Status: done

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록(두 앱)
- 이유: 기존 runlog·runs.jsonl·MCP 질의 기록을 유지하면서 두 앱의 사건·감사·성능 기록을 같은 형식으로 남긴다.
- 공통 구현(10-30, T0): `common/core/jsonlog.py`의 `setup(app)`은 표준 logging으로 `time, level, app, event, msg, request_id, run_id, span_id, duration_ms, err` JSON 한 줄을 쓴다. `_mask()` 재사용, PC 기본 `logs/<앱>.jsonl`, 서버 stdout. `common.log.level/dir`로 제어하며 contextvars ID는 `settings.child_env()`의 내부 신호로 자식에 전파된다.
- DB: `common/store/logsink.py`의 `emit(table,row)`/Handler → 제한 큐 → 백그라운드 배치 INSERT. DB 실패 시 `common.log.fallback_dir`(기본 `output/applog`) jsonl로 대체, 프로세스당 경고 한 번. 큐 포화는 즉시 드롭하고 `stats().dropped`로 집계한다. 종료는 exitclean에서 DB 대기와 대체 파일 I/O를 합한 단일 deadline(`shutdown_sec`)까지 flush한다. DB 대기는 남은 예산의 절반까지 하고 나머지 예산에 데몬 스레드가 파일 기록을 시도한다. 파일 잠금/쓰기가 막혀도 deadline에 반환하며 미완료 행은 `dropped`로 집계하고 stderr에 프로세스당 한 번 경고한다(이미 진행 중인 OS 쓰기는 나중에 끝날 수 있으므로 집계/재적재 시 상관 ID 대조). 종료 시 커밋 결과가 불명확하면 DB/파일에 중복될 수 있다(상관 ID 대조).
- 스키마: Alembic `0001_applog` / `dbtool up --target applog`. `mcp_call(ts)`·`pipe_event(ts_start)`는 월 파티션(복합 PK에 월 키 포함), `pipe_run`은 일반 테이블(run_id PK, 시작 running/종료 UPSERT). up/maintain은 현재 달+앞으로 2개월을 준비한다. `dbtool maintain --target applog`를 매일 예약해 다음 월 준비·90일 보존 정리(월 끝이 만료된 파티션 DROP, pipe_run DELETE). sink는 DDL을 실행하지 않는다.
- 설정: `common.log.db_enabled` 기본 false — 마이그레이션 후 true로 켬. `retention_days=90`, `queue_size=10000`, `batch_size=200`, `flush_sec=1`, `db_timeout_sec=2`, `shutdown_sec=5`. `mcp.audit.max_input_bytes=16384/max_output_bytes=65536/max_queue_bytes=268435456` 제공(설정은 YAML만).
- 잔여 수정(11-01, G1): 서버 dev/prd 시작 관문은 비어 있지 않은 비밀 설정이 코드 상수 `MIN_SECRET_LENGTH=8` 미만이면 경로만 알리고 종료 2로 거부한다. JSON은 비밀 라벨 문자열, DSN은 디코딩한 비밀번호를 검사한다. local은 기존 경고·토큰 경계 마스킹을 유지한다. 감사 큐는 64건에 더해 활성 처리 포함 `max_queue_bytes` 합계 상한을 적용한다(문자열 최대 4바이트/글자+노드당 64바이트 추정, 65536노드 또는 바이트 초과 시 즉시 중단). 초과는 기존 본문 없는 메타 행·body_omitted, sink까지 포화면 dropped로 센다. 처리/취소 항목은 바이트를 차감한다. 동기 마스킹 전 메타 문자열은 2048자로 제한한다. 상한보다 긴 메타 문자열은 비밀값 일부가 남지 않도록 통째로 생략 표식으로 바꾼다. 전체 RSS나 수신 원문 크기 제한은 아니다.
- MCP 구현(10-30, T1): `services/call_log.py`가 `_bg`/`_bg_long` 호출당 `applog.mcp_call` 한 행을 공통 sink에 보낸다. 성공·도구 오류·busy·timeout·HTTP 인증 거부를 기록하고 sink/직렬화 실패가 도구 응답·예외를 바꾸지 않는다. 본문은 JSON UTF-8 직렬화 후 비밀값 마스킹·앞부분 저장(기본 입력 16KB/출력 64KB, 중간에서 잘린 JSON은 완전한 JSON이 아닐 수 있음). `*_bytes`와 `result_sha256`는 상한 적용 전 전체 원본 JSON 기준이며 `*_truncated`는 마스킹된 본문을 잘랐는지 표시한다. parse_document의 content_b64는 디코딩한 파일 sha256·바이트 수로 대체(잘못된 base64면 인코딩 문자열 기준 표시). result_keys는 본문 상한과 별개로 search의 chunk_keys(목록 순서 = 순위, mc-16 — 11-03 고침)/evidence_status/filter/scope_docs, list_doc_fulltext의 batch 건수·next_cursor·doc_keys, get_doc_fulltext의 batch 건수와 파일별 name/kind/size/sha256/skip_reason(본문 없음), query_edw의 row_count/columns, parse_document의 job_id/engine/rep_path/text_chars, edw_meta의 단계·테이블·컬럼 수를 추출한다. get_doc_fulltext의 result 본문은 문서 원문 전체이므로 applog 표·대체 파일은 원본 문서와 같은 접근 제한이 필요하다(C-79).
- MCP 컨텍스트: HTTP `X-MCP-Client`→agent(기존 CALLER와 함께 유지), `X-MCP-User` 우선·없으면 `params._meta.user`, Mcp-Session-Id. 접속 IP와 clientInfo는 기록하지 않는다(사용자 11-02, 칸 삭제). 유효한 UUID `X-Request-Id`는 그대로 전달하고 없거나 UUID가 아니면 새 UUID를 만들어 응답 헤더에도 보낸다. stdio는 agent=stdio이며 콘솔 로그는 stderr로 보낸다(stdout은 JSON-RPC 전용, 명시 파일 로그는 유지). `jsonlog.setup(app, stream=...)`의 앱별 스트림 보존으로 logger 재설정 뒤에도 stdio 콘솔 로그가 stderr에 남는다(coordinator 승인, 기본 호출 동작 불변). **stateless_http이므로 도구 호출의 session_id는 같은 요청에서 알 수 없으면 null** — initialize 자체를 별도 행(tool=initialize)으로 기록하고 args에서 clientInfo는 뺀다. 인증 거부는 본문을 기다리지 않고 tool=http로 기록한다. timeout 뒤 실행 중인 스레드는 DEBUG `mcp.thread.abandoned`와 `mcp.thread.finished`(실제 종료 시각)로만 추적하며 감사 행을 더 만들지 않는다. qa_log.jsonl은 기존 동작 그대로, 검증 UI 헤더는 test/test다.
- 교차 검토 수정(10-30 F1·11-01 F4 — P1-1/P1-3/P2): 공개 `jsonlog.masked(value)` 한 곳이 기존 라벨 패턴과 settings의 `SecretStr` 칸 값을 함께 가린다. 4자 이상은 부분 문자열을, 1~3자는 앞뒤가 문자·숫자가 아닌 토큰 경계에서만 가린다. 짧은 비밀값이 문자·숫자에 붙으면 값 대조로 가려지지 않는 한계가 있다. 설정 시작은 거부하지 않고 해당 설정 칸 경로만 프로세스당 한 번 stderr에 경고한다. JSON 형식 비밀 설정의 개별 문자열은 기존 `_LABEL` 비밀 라벨 키의 값만 추출하며 driver/host와 라벨 없는 리스트 문자열은 값 대조에 넣지 않는다. DSN 비밀번호·URL/JSON 이스케이프·중첩 값·분리 CLI 인자·오류/traceback에도 적용한다. 설정 캐시의 비밀 칸만 수집하며 원본을 바꾸지 않는다. JSON 줄과 sink DB/대체 파일 및 MCP args/result/err에 같은 API를 쓴다. 기존 DSN 패턴은 스킴 중간 재시작을 막아 긴 일반 문자열의 제곱 시간 역추적을 없앴다.
- 감사 지연 수정(F1·F4): ASGI는 수신 청크를 그대로 SDK에 전달하며 감사용 본문은 최대 1MiB만 모아 스레드에서 파싱한다. 초과하면 `_meta.user`/method/initialize 추출을 생략하고 헤더 컨텍스트를 쓰며, 도구 입력은 거부/제한하지 않는다(도구명·args는 dispatch에서 얻음). `_bg`/`_bg_long`은 감사 처리를 await하지 않는다. 시각·상태·소요 시간은 호출 시 확정하며 입력/결과 직렬화·상한 처리·해시·마스킹·emit은 도구 anyio limiter와 독립된 전용 데몬 스레드 하나가 맡는다. 본문 대기 큐는 64건이며 포화 시 args/result가 NULL이고 result_keys.audit_body_omitted=queue_full·err=audit_queue_full인 메타 행만 비차단 sink로 보내고 call_log.stats().body_omitted를 올린다(sink 포화는 기존 dropped). 감사 큐는 건수 상한이며 입력/결과 한 건의 크기를 제한하거나 거부하지 않는다. busy는 판정 즉시, timeout은 감사 지연 없이 기존 도구 시간 예산으로 반환한다. 종료는 감사 워커→sink 순서로 기존 shutdown_sec 단일 deadline을 공유하고 미완료 감사 행은 call_log.stats().dropped로 집계한다. JSON/base64 해시는 64KiB 청크로 누적해 전체 바이트 사본을 만들지 않는다.
- 수용 기준: JSON 필수 키·비밀 마스킹·수준 필터·컨텍스트 격리/자식 전파·DB 실패 파일 기록·큐 드롭 집계·정상/SIGTERM 종료 flush, PC 임시 PG 스키마 up/check·UPSERT·파티션 보존 정리 시험.
- 검증(10-30 T0): 새 서버 시험 2개·PC PG 시험 1개 통과, lint/mypy·모듈 경계·sample/keyscan 통과. 전체 selftest 94/96, pytest 148 passed·3 xfailed·1 failed — 새 실패 없음; 기존 publish_guard와 HEAD 538067a의 ParsingMeta 명세 불일치(test_db_schema, rep_engine/engines_used)를 coordinator 확인대로 유지.
- 검증(11-01 F4): 짧은 비밀값의 전체/분리 인자/토큰 경계와 비일치·stderr 1회(값 미포함), JSON driver/host·라벨 없는 리스트 오탐 제거, 실제 sink 마스킹, 감사 준비 0.3초 지연 중 timeout 0.05초·busy/정상 응답 독립성, anyio 공용 limiter 포화 독립성, 큐 초과 메타 1행/집계·sink 포화 비차단, 정상/lazy sink 종료 flush·막힌 감사의 0.08초 공유 deadline 시험 통과. tools/list 9,330바이트·SHA-256 불변, lint/모듈 경계/sample/keyscan 통과. 단독 전체 selftest 101/103(기존 test_db_schema·test_publish_guard), pytest 157 passed·3 xfailed·1 failed(기존 test_db_schema). 최초 동시 전체 시험의 시간 민감 실패는 단독 재실행에서 통과했다.
- 검증(10-30 F1): 설정 비밀값 중첩 args/result·err/traceback·DSN·분리 인자, DB/대체 파일, busy 후 스레드 처리 및 큰 content_b64 감사 중 /health 지연, ASGI 청크 동일성/1MiB 초과 파싱 생략, 막힌 fallback 잠금/쓰기 종료 상한, 기존 마스킹 예시 동일성·1/2MiB 선형 시간 시험 통과. tools/list 9,330바이트·SHA-256 불변. 전체 selftest 99/101(기존 test_db_schema·test_publish_guard), pytest 155 passed·3 xfailed·1 failed(기존 test_db_schema), 새 실패 없음.
- 검증(10-30 T1): tools/list가 T0와 9,330바이트·SHA-256까지 동일. 새 감사 서버 시험(실제 ASGI·stdio JSON-RPC 포함)·UI 헤더 시험 통과, 전체 selftest 95/97 및 pytest 150 passed·3 xfailed·1 failed(test_db_schema) — 기존 실패만 유지. 전용 PG에 test/test search 1행과 initialize 1행, args/result/result_keys/duration_ms를 SQL로 확인; PG 검색 스키마 0행을 확인한 뒤 준비된 번들을 읽기 전용 BM25로 검색해 chunk_ids=[0]/rank=[1]/via=[k]/evidence_status=found와 result_truncated=false도 확인. 승인된 stdio 스트림 보존 보완은 common jsonlog에만 적용(기본 호출 불변), 이에 따른 code_fp 전후는 T1 커밋에 기록.
- 위험: 공용 의존 변경으로 code_fp 변경(이번 판 pl-25와 묶음), 핸드오프/엔진 바이트 유지. 검토 등급 A(비밀값·DB 스키마). 서버 DBA 협의·마이그레이션·maintain 예약은 refactor.md C-79.
- 파일: `common/core/{jsonlog,exitclean}.py`, `common/store/logsink.py`, `common/store/db/`, 설정 모델/sample, `tests/server/common/test_{jsonlog,logsink}.py`, `tests/general/common/test_applog_pg.py`, `mcp_server/services/call_log.py`, `mcp_server/{main.py,routers/dispatch.py}`, `tests/server/mcp/test_call_log.py`, `validation/search_ui/serve.py`.
- 진행(10-30, T2 — 파이프라인 성능·추적): 기록 단위 3개. ① 실행 1건 = `applog.pipe_run`(`pipeline/cli.py` `__main__`의 `runtrace.run`이 `run_id`를 만들고 시작 `running`·종료 UPSERT, code_fp·stack·settings_hash·문서 수·workers·cpu_max_load·mem_start_pct — 부모가 이어준 run_id가 있는 자식은 새로 시작하지 않음). ② 문서×단계 span = `applog.pipe_event`(`common/core/span.py` — `with span("extract.parse", doc_id=…, engine=…) as s: s.add(pages=…)`; 중첩 `parent_id`, 오류는 `status`·`err_kind`(env/timeout/doc/external/db)로 기록하고 다시 던짐 — `err`는 예외 타입 이름(+OSError는 errno 이름)과 `span.safe()`로 표시한 우리 코드의 고정 문구만 저장하는 allowlist이며 외부 라이브러리·파서 예외 문자열 원문은 저장하지 않는다(`run_all.redact`의 `redact_text`는 runs.jsonl용으로만 남음)). ③ 60초마다 `stage='run.progress'`(`runtrace.Progress` — 완료/전체·docs/min·남은 시간 추정·단계별 진행 중 개수·부하·메모리). `run_id`가 없으면(MCP 검색·시험) span은 아무것도 안 하는 가짜라 DB·스레드·지연이 0이다(서버 시험으로 고정).
- 계측 지점: `common/core/resources.gated_popen`(메모리 문 `wait_mem_ms`·CPU 문 `wait_cpu_ms`를 열로, 다른 launcher 대기·settle은 metrics, 자식에 `APPLOG_CONTEXT`로 run/span ID 전달 — 스레드 풀은 `span.carry`) · `pipeline/cli.py`(`proc.run` — 하위 프로세스 1개) · `run_all.py`(`extract.plan`, 문서×엔진 `extract.parse`, 조각 `extract.shard`; 자식 `parse_one`이 stdout 끝에 남기는 cpu_ms·rss_peak_mb 한 줄을 부모 span이 옮김 — 엔진 파일은 그대로) · `represent.py`(`transform.represent`, `transform.figures`: VLM/OCR 호출 수·재시도·지연 p50/최대·토큰은 `common/ai/adk.complete` 래퍼가 열린 span의 metrics에 쌓음) · `build_bundle.py`(`transform.structure`: 청크 수·길이, `embed.bundle`: 캐시 적중/실패·배치 수·호출 지연·재시도·토큰 — `embed.py`) · `llm.py`(응답 캐시 적중·분당 상한 대기) · `pgvector_load.py`(`load.pgvector` + 표별 `load.doc/chunk/chunk_term/stats`: 행 수·rows/sec) · `publish_parse_result.py`(`load.publish`). INFO는 문서×단계 span까지, 개별 호출은 span.metrics 요약과 DEBUG만. 기존 `runs.jsonl`·`RUNLOG`·`PROGRESS.md`는 그대로. 최상위 진입점은 `pipeline.cli parse`와, 직접 실행하는 `run_all`·`represent`·`build_bundle`·`pgvector_load`·`publish_parse_result`(부모가 `run_id`를 이어주지 않았을 때만 자기 `pipe_run`을 시작 — 서버 호스트 `run_docs.py`의 구조화+적재는 `build_bundle`·`pgvector_load`를 직접 불러 실행 2건으로 남는다). 점검·설정 명령(selftest·smoke·set-*·show-*)은 추적하지 않는다.
- 분석: `python -m pipeline.tools.perf [<run_id>]` — 단계·엔진별 p50/p95/최대·건수·실패율·wall/층 비율·wait 비율, 쪽당 시간, 느린 문서 N개(`--top`), 캐시 적중률·재시도율·실패율, `--compare <run_id>…`로 code_fp·stack·settings_hash 차이와 단계별 p50 비교, `--runs`로 최근 목록, DB가 꺼진 PC는 `--file output/applog/*.jsonl`. 읽기 전용.
- 검증(10-30 T2): 서버 시험 `test_span`·`test_runtrace`·`test_perf`·`test_span_stages` 4개(span 중첩·parent_id, 오류 status/err_kind, wait_mem/cpu 분리와 자식 프로세스 run/span ID 전달, run.progress 주기, perf 집계, 임베딩 캐시/배치/재시도·적재 표별 span — 임베딩은 `patch.object`, 적재는 가짜 커서, 검색 경로 no-op 고정)와 PC 시험 `tests/general/pipeline/test_perf_pg.py`(임시 스키마 `test_t2perf_*`). 실데이터 스모크는 `valid_env` 문서 3건으로 `pipeline.cli parse`(→ `build_bundle --embed none`)까지: `pipe_run`·`pipe_event`에 extract/transform 단계 행, `perf.py` 출력 확인. **사용자 결정(10-30): 외부 임베딩 호출 금지 — 캐시 적중이 1/27이라 임베딩·pgvector 적재의 PC 실데이터 스모크는 하지 않음(미검증).**
- 계측 fail-soft(10-30 F2, 교차 검토 P1-2): span 시작 측정·종료 기록·`pipe_run` 시작/종료·`run.progress` 스레드의 모든 예외는 계측 안에서 삼킨다 — 업무 코드의 정상 결과를 바꾸지 않고, 업무 예외가 있으면 원래 예외를 그대로 다시 던진다. 로그 디렉터리 권한 오류로 `jsonlog.setup`이 실패하면 30초간 다시 열지 않고 span을 가짜로 대체한다. 실패는 프로세스당 1회 stderr 경고(`[applog] 계측 실패…`, 예외 타입만)와 `span.failure_count()` 카운터로만 남는다. `Span.result()`의 status/err_kind 값 검증(프로그래머 오류)만 예외로 남김.
- 오류 필드(10-30 F2, P2-5): `pipe_event.err`와 JSON 로그의 `err`는 allowlist — 예외 타입 이름(+errno 이름·CalledProcessError 종료 코드)과 `span.safe(...)` 고정 문구. `sp.result(…, err)`에 그냥 글자를 주면 맨 앞 예외 클래스 이름만 남고 나머지는 버린다. 로컬 DEBUG에도 원문을 남기지 않는다. `err`와 `metrics`의 글자, `pipe_run.args`(인자별)는 저장 전에 `jsonlog.masked`를 거친다.
- 한계: `cpu_ms`는 이 프로세스(RUSAGE_SELF)와 span 안에서 끝나 회수(wait)된 자식 프로세스(RUSAGE_CHILDREN)의 CPU 시간 합이다(10-30 F2, P2-6 — subprocess 작업 포함). 서로 조상이 아닌 `cpu=True` span이 같은 프로세스에서 겹치면 둘 다 NULL(0으로 채우지 않음). `cpu=False` span과 겹치는 자식은 구분하지 못하므로 `cpu=True`는 호출부가 직렬일 때만 쓴다. span이 끝날 때까지 안 끝난 자식·손자의 CPU, Windows(`resource` 없음)·측정 실패는 NULL이다. `rss_peak_mb`는 이 프로세스만이다. `cpu_ms`·`rss_peak_mb`는 프로세스에서 하나만 도는 span(자식 프로세스 루트·represent 문서 직렬 실행·적재)과 `parse_one` 자식 값만 정확하다(스레드로 겹치는 span은 비움). macOS는 `mem_used_pct`가 비고(`/proc` 없음) Windows는 cpu_ms·부하가 빈다. `docs_reused`는 비어 있다(실행마다 새로 파싱 — pl-32).
- 파일(T2·F2): `common/core/span.py`, `common/core/resources.py`, `common/ai/{adk,embed,llm}.py`, `pipeline/shared/runtrace.py`, `pipeline/tools/perf.py`, `pipeline/cli.py`, `pipeline/extract/{run_all,parse_one}.py`, `pipeline/transform/{represent/represent,figures/figures,figures/vlm_page,structure/build_bundle}.py`, `pipeline/load/{pgvector_load,publish_parse_result}.py`, `tests/server/common/test_span{,_soft}.py`, `tests/server/pipeline/test_{runtrace,perf}.py`.
- 결정(사용자 10-30 grill): gold DB 변경([load-schema.md#pl-25](load-schema.md#pl-25))과 같은 판에 싣는다 — 재처리 한 번.
- 로그 점검 후속(11-02): `extract.parse`의 `attempt`를 채운다(시간 초과 재시도면 2). 앱 logger 이름을 `applog.<앱>`으로 두어 SDK(`mcp.*`) 줄이 감사 로그에 섞이지 않는다. SDK 줄은 `mcp_server.main.build()`가 FastMCP 기본 처리(root의 INFO·일반 글자·stderr)에서 떼어 stderr JSON(`jsonlog.JsonFormatter`)으로만 낸다 — 요청마다의 INFO는 `common.log.level=DEBUG`일 때만, WARNING 이상·예외 줄은 항상 `jsonlog.masked`를 거쳐 비밀값이 가려진다(stdio의 stdout은 JSON-RPC 전용 그대로). 임베딩 호출 중에도 `run.progress`(unit=chunk)를 남긴다. `ext_call_ms`는 호출 시간의 합이라 병렬이면 `duration_ms`보다 클 수 있다.
- develop 병합(11-02): 서버 입구가 `run_docs`로 하나가 되어 파싱·구조화·적재·게시·warm이 문서마다 따로 실행된다. 그래서 실행(`pipe_run`)도 문서·단계마다 생기고 부모 run_id로 묶이지 않는다. 전체를 볼 때는 `python -m pipeline.tools.perf --since <시간>`을, 문서 하나는 `pipe_event.doc_id`를 쓴다. `source warm`에 `extract.warm`을 더했다. 설정 파일 자리는 `ops.log.*`·`search.audit.*`(모델 경로 `common.log.*`·`mcp.audit.*`).
- 결정(사용자 10-31 범위 축소 grill → 11-02): JSON Lines 사건 기록을 이 행에서 지우고 logging 시스템을 따로 만들기로 했던 것이 `feature/logging` 작업이다 — 그 구현을 이 행에 적는다.
- Status: dev — `feature/logging`(서버 적용 전, refactor.md C-79·C-80).

