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
- Status: done — trigger 서버 지움 11-01(`feature/scope-cut-pipeline`): `pipeline/trigger_server.py`·시험 `test_trigger_server`, entrypoint `serve-trigger`(→ `idle` — 상주 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`는 run_docs의 docker exec 대상이라 남기고 떠 있기만), compose의 `TRIGGER_MODULE`·`/health` 검사, `deploy/host/scripts/parse_trigger_test.py`, 설정 절 `pipeline.service.trigger`(`required.tokens.trigger` 포함 — 남으면 경고만: `common/config/layout.py`의 자리는 옛 settings.yaml이 거부되지 않게 남기고 sample 대조에서만 뺌(`sample.LAYOUT_GONE`) — layout.py는 code_fp에 들어가 손대지 않음), `settings_env.sh`의 trigger 포트. `common/core/exitclean.py`의 SIGTERM 처리는 모든 프로세스가 쓰는 일반 처리라 그대로(주석의 trigger_server 예시만 남음 — 고치면 code_fp가 바뀜).

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
- Status: todo

<a id="pl-24"></a>
## pl-24 · `run_docs` 문서별 순서: 파싱 → silver 게시 → 원본 삭제 → gold
- 이유: 지금은 게시가 gold를 기다리고, `cleanup_doc`이 실패해도 원본을 지운다.
- 결정(사용자 10-29 grill): 원본은 Object Storage에서 수집 서버로 받아 파싱하고, silver 게시가 성공한 뒤에만 지운다. 파싱 실패 → 원본은 남기고 원인 + 걸린 시간을 로컬에만 기록, EDW에는 아무것도 안 씀. gold 실패 → EDW 행은 남고 `gold_status` = failed(+ 이유). gold는 silver에서 다시 만들 수 있다.
- 새 EDW 칸 `AI.ParsingMeta.gold_status`(pending · ok · failed) + 이유 — DDL은 DB 담당자에게(회사 DB, Alembic 아님) — 검토 등급 A. 줄인 ParsingMeta 칸 목록은 [pl-25](load-schema.md#pl-25).
- `valid_env/`로 하는 로컬 시험은 문서를 먼저 임시 폴더로 복사해 거기서 돌린다(제자리에서 돌리지 않음).
- 파일: `deploy/host/scripts/run_docs.py`(`doc_flow`, `cleanup_doc`, 처리 끝난 질의), `docs/operations/parsing_meta_mssql.sql`, 게시(`parsing_meta`).
- 결정(사용자 10-30 PRD grill): C3 — 파싱이 통째로 실패하면 ParsingMeta에 쓰지 않는다(이 행 그대로). (허브 10-31 고침 — 아래) 실패는 로그·문서 대장에만 남고 다음 실행에서 다시 후보가 된다.
- 결정(허브 10-31, 최신 결정 우선): 문서 대장도 성공했을 때만 쓴다([pl-12](load.md#pl-12)·[pl-32](load-schema.md#pl-32) — 실패 횟수 없앰). 실패는 **로그에만** 남고, ParsingMeta에 행이 없으니 다음 실행에서 다시 후보가 된다(C10).
- Status: todo — [pl-25](load-schema.md#pl-25) 뒤.

<a id="pl-18"></a>
## pl-18 · 중간에 멈춰도 `night`/`full`이 종료 코드 0
- 결정(사용자 10-31 범위 축소 grill): 서버 입구는 **run_docs 하나**. night·full 입구를 없애고, 정기 실행(새벽 배치)은 타이머가 run_docs를 부르는 꼴로(night = run_docs를 바깥에서 부르는 것).
- 이유: 스케줄러가 실패를 못 본다(C-33).
- 결정(사용자 10-30 grill): 종료 코드 — 대상 0건 = 0, 실패 = 1, 마감 시각 도달 = 75.
- 파일: `pipeline/cli.py`(`night`), `deploy/docker/entrypoint.sh`(`full`).
- 결정(사용자 11-01 기본값 — 허브 11-01): 새벽 run_docs에 문서 수 상한 · 마감 시각 · 사람이 따로 돌린 run_docs와 겹치지 않게 하는 잠금을 둔다(지금은 systemd `TimeoutStartSec=6h`뿐 — #83).
- Status: todo — 11-01(`feature/scope-cut-unused`) 옛 입구를 지움: `pipeline.cli`의 `night`·`run-stack`·`structure`·`load`(+ 끝 표시 확인 `need()`), 이미지 명령 `night`·`run-stack`·`full`·`structure`·`load`, `trigger.sh` `night`·`structure`·`load`·`all`, compose job `structure`(`load` 서비스는 `run_tool.sh` 도구용으로 남김 — 명령 `help`), 죽은 설정(`ops.nightly.max_new`·`modules`·`publish`, `ops.nightly_run.deadline`·`parse_deadline`, `dev.pipeline.allow_common_mismatch` — 남으면 경고만). 새벽 배치는 systemd 타이머 → `trigger.sh scheduled` → `run_docs.py --start-offset 0 --skip-done`(서버 확인 refactor.md C-72). 남음: 종료 코드 규칙(대상 0건 = 0, 실패 = 1, 마감 = 75)을 run_docs에 만든다.

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
- Status: todo — 논의 대상(지금 2).

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
- 무엇: OpenAI 호환 역할 llm/vlm/embed(rerank는 10-29에, ocr_vlm은 10-30에 지움 — [transform-cleanup.md#pl-31](transform-cleanup.md#pl-31)). 서버(dev/prd)는 외부 모델 거부. 외부 전송은 `*_ALLOW_EXTERNAL` + `RUN_ENV=local`이어야 함. 예산, 호출 상한, RPM, 비용 장부, 응답 캐시, 시험용 가짜 LLM.
- 10-29(사용자): 합성 문서 선언 `LLM_SYNTHETIC_TRUTH` 잠금 삭제 · 외부 허용은 루트 settings.yaml에 둬도 됨(설정 창구는 하나).
- 파일: `common/ai/guard.py`, `common/ai/llm.py`, `common/ai/adk.py`, `common/config/settings.py`.
- Status: done

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록(두 앱)
- 결정(사용자 10-31 범위 축소 grill): JSON Lines 사건 기록은 logging 기능 — 나중에 logging 시스템을 따로 만들므로 **요건에서 지운다**.
- 이유: 지금 `common/core/runlog.py`는 실행마다 요약 하나(`output/runlog.jsonl`)와 날 콘솔 기록(`output/logs/*.log`, `_mask()`로 가림)을 쓰고, 러너는 `doc_stats.jsonl`, MCP 서버는 질의 jsonl을 쓴다. 공통 사건 줄(level, request id, duration)도 로그 수준 설정도 없다.
- 단계: (1) 표준 `logging` + `common/core/`에 작은 JSON 포매터 하나 — 키 `time, level, msg, request_id, duration_ms, err`, `_mask()` 재사용(새 패키지 없음). (2) 로그 수준은 **settings.yaml** 항목(검토의 `LOG_LEVEL` env는 CLAUDE.md §3과 충돌 — 옛 env 이름은 별칭으로만). (3) PC는 `logs/<앱>.jsonl`(git 제외), 서버는 stdout. (4) 비밀값과 개인정보를 가린다.
- 위험: `common/`을 고침 → code_fp가 바뀔 수 있음(서버 재처리). 설계 때 사용자에게 알리고 핑거프린트 전후를 커밋에. 검토 등급 A(비밀값 처리).
- 수용 기준: 줄마다 필수 키가 있는 JSON으로 읽힘, 예시 비밀 문자열이 가려짐, 수준 설정이 줄을 거름.
- 파일: `common/core/`(새 포매터), `common/config/settings.py`, `mcp_server/main.py`, `pipeline/cli.py`, `.gitignore`.
- 결정(사용자 10-30 grill): gold DB 변경([load-schema.md#pl-25](load-schema.md#pl-25))과 같은 판에 싣는다 — 재처리 한 번.
- Status: dropped (사용자 10-31 범위 축소)

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 중간에 멈추면 보임 | 중간에 멈춰도 `night`/`full` 종료 코드 0 | `pipeline/cli.py`, `entrypoint.sh` | pl-18 |

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- 밤 호스트 타이머(`NIGHTLY_*`). `deploy/host/`. (trigger 연결은 11-01에 지움 — [pl-10](#pl-10).)

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 밤 일정 | `NIGHTLY_TIME` 비움 | 시각(HH:MM) |
| 외부(유료) 모델 | `*_ALLOW_EXTERNAL=0`, PC만(`RUN_ENV=local`) | 예산 상한(`LLM_BUDGET_USD`, `LLM_MAX_CALLS`) |
