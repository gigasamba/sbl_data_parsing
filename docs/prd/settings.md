# 설정·운영 — settings.yaml·RUN_ENV·계정·로그·외부 모델

[PRD.md](../PRD.md)의 카테고리 하나. 두 앱이 함께 쓰는 설정, 실행 환경(`RUN_ENV`), EDW 계정, 로그, 외부 모델 호출 가드.
op-01~03의 출처: COMPANY 거버넌스 프로젝트별 검토, 10-29(임시 표준).

순서(주제별): 실행 환경·외부 모델 op-02·pl-11 → 계정 op-03 → 종료 정리 pl-27·pl-44 → 로그 op-01 → 미룬 설정 정리 pl-21·pl-30 → settings.yaml 하나 op-05 → 코드와 다른 점.

<a id="op-02"></a>
## op-02 · RUN_ENV는 `local`·`dev`·`prd` 셋(`stage` 없앰) · LLM_FAKE는 `local`에서만
- 무엇: `local`(PC), `dev`(개발 서버), `prd`(운영). `stage`는 없앤다.
- 이유: `stage`는 `prd`와 똑같이 동작했다(실행 기록에만 적힘). 허브가 방식 수를 줄이자고 했다(10-29). LLM_FAKE에는 RUN_ENV 확인이 없어 서버에서 가짜 답이 돌 수 있었다.
- 결정(사용자, grill-me 10-29):
  1. `local`을 PC 신호로 유지(저장소 루트 settings.yaml 찾기, 파일 기반 스택·원천, `paths.LOCAL_RUN`) — 새 설정도, 코드 위치 규칙도 없음. (허브는 dev/prd만 제안했고 사용자가 셋을 골랐다.)
  2. 외부 모델(OpenRouter 등)과 `LLM_FAKE`는 **`local`에서만** 허용. `dev`와 `prd`는 둘 다 거부.
  3. `dev`/`prd`에서 `LLM_FAKE`가 켜져 있으면 앱 시작에서 거부(`require_run_env` 관문), 호출마다가 아님.
  4. `stage`는 더는 받지 않는다: `local`·`dev`·`prd`만 받고, `stage`는 모르는 값처럼 거부(시작 거부, 메시지에 세 값을 보임). 대응 없음. 코드 검색 10-29: `stage` 전용 동작은 없고 값 목록·메시지·문서에만 나온다.
  5. RUN_ENV는 모든 곳에서(PC 포함) 필수 — 기본값 없음.
- 따라 나온 것(질문 불필요): RUN_ENV 없는 명령(이미지 안 `selftest`, 점검 명령)은 앱 시작이 아니라 시험 사례에서 LLM_FAKE로 계속 동작. PC Docker 스모크(`valid_env/docker/compose.test.yml`)는 `RUN_ENV: local` 유지. 외부 모델 규칙 `external_models_allowed` = `local`만(그대로).
- 파일: `common/config/settings.py`(RUN_ENVS, SERVER_ENVS, run_env Literal, stage 대응, 시작 관문), `common/ai/llm.py`/`adk.py`(시작 관문이 덮으면 그대로), `common/config/{migrate,keyscan,overrides,setarg}.py`, `deploy/host/compose/*.yml` 글, `deploy/host/scripts/settings_env.sh`, `deploy/docker/entrypoint.sh`, 문서(CLAUDE.md §3, README §3, env-guide, refactor.md), `settings.sample.yaml` 다시 만들기, 시험.
- 서버 할 일: `run_env: stage`인 서버 `settings.yaml`은 이 릴리스 전에 `prd`로 바꾼다(env-guide 행).
- 위험: `common/config/settings.py`는 모든 레이어의 code_fp에 들어간다 → 서버 재처리. 핑거프린트 전후를 기록. settings.py 변경은 작게(92와 r2-phase도 고침).
- 수용 기준: `RUN_ENV=stage`는 시작 거부(모르는 값). `RUN_ENV=dev`/`prd` + `LLM_FAKE=1`이면 앱 시작이 0이 아닌 코드로 끝남. `local` + `LLM_FAKE=1`은 시작. 외부 모델은 dev/prd에서 거부, local에서 허용. 이미지 안 selftest 통과. 전체 pytest + 린트 통과.
- Status: done (10-30, PR #6 병합 — 사용자 승인) — 서버 할 일은 refactor.md C-66.

<a id="pl-11"></a>
## pl-11 · 모델 호출, 비용, 외부 전송 가드(공용)
- 이유: 폐쇄망 서버는 외부 모델을 절대 부르면 안 되고, PC 호출은 싸게 유지해야 한다.
- 무엇: OpenAI 호환 역할 llm/vlm/embed(rerank는 10-29에, ocr_vlm은 10-30에 지움 — [parse.md#pl-31](parse.md#pl-31)). 서버(dev/prd)는 외부 모델 거부. 외부 전송은 `*_ALLOW_EXTERNAL` + `RUN_ENV=local`이어야 함. 예산, 호출 상한, RPM, 비용 장부, 응답 캐시, 시험용 가짜 LLM.
- 10-29(사용자): 합성 문서 선언 `LLM_SYNTHETIC_TRUTH` 잠금 삭제 · 외부 허용은 루트 settings.yaml에 둬도 됨(설정 창구는 하나).
- 파일: `common/ai/guard.py`, `common/ai/llm.py`, `common/ai/adk.py`, `common/config/settings.py`.
- Status: done

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
- 이유: pl-27은 정상·오류·SIGTERM 종료 때 덮기 설정 임시 파일을 지우지만, SIGKILL·OOM으로 끝나면 남는다(사용자 10-30 PRD grill S1 — pl-27은 done으로 닫음).
- 결정(사용자 10-30 grill 12~13차 — refactor.md C-46): 다음 시작 때, 만든 프로세스가 더는 없는 임시 설정 파일(`settings-*.yaml`)을 지운다.
- 파일: `common/core/exitclean.py`, `common/config/settings.py`.
- Status: todo

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록(두 앱)
- 이유: 지금 `common/core/runlog.py`는 실행마다 요약 하나(`output/runlog.jsonl`)와 날 콘솔 기록(`output/logs/*.log`, `_mask()`로 가림)을 쓰고, 러너는 `doc_stats.jsonl`, MCP 서버는 질의 jsonl을 쓴다. 공통 사건 줄(level, request id, duration)도 로그 수준 설정도 없다.
- 단계: (1) 표준 `logging` + `common/core/`에 작은 JSON 포매터 하나 — 키 `time, level, msg, request_id, duration_ms, err`, `_mask()` 재사용(새 패키지 없음). (2) 로그 수준은 **settings.yaml** 항목(검토의 `LOG_LEVEL` env는 CLAUDE.md §3과 충돌 — 옛 env 이름은 별칭으로만). (3) PC는 `logs/<앱>.jsonl`(git 제외), 서버는 stdout. (4) 비밀값과 개인정보를 가린다.
- 위험: `common/`을 고침 → code_fp가 바뀔 수 있음(서버 재처리). 설계 때 사용자에게 알리고 핑거프린트 전후를 커밋에. 검토 등급 A(비밀값 처리).
- 수용 기준: 줄마다 필수 키가 있는 JSON으로 읽힘, 예시 비밀 문자열이 가려짐, 수준 설정이 줄을 거름.
- 파일: `common/core/`(새 포매터), `common/config/settings.py`, `mcp_server/main.py`, `pipeline/cli.py`, `.gitignore`.
- 결정(사용자 10-30 grill): gold DB 변경([etl.md#pl-25](etl.md#pl-25))과 같은 판에 싣는다 — 재처리 한 번.
- Status: todo — 0.2.0(사용자 10-30 PRD grill C1).

<a id="pl-21"></a>
## pl-21 · 미룬 설정 지우기(핑거프린트)
- 이유: 안 쓰거나 은퇴한 설정인데 지우면 핑거프린트가 바뀌어 다음 이미지 판을 기다린다: `common.paths.korean_font`(settings.py → 모든 레이어 code_fp).
- 또(사용자 10-29 grill): `common.paths.eval_sets_dir` / `paths.EVAL_SETS_DIR`(과 `tests/server/common/test_paths.py`의 사례)을 지운다 — 읽는 곳은 `validation/e2e/stack_matrix.py`뿐(옛 묶음, [test.md#e2-10](test.md#e2-10)). 폴더 `valid_env/eval_sets/`는 그 문서 참조와 함께 [doc.md#do-03](doc.md#do-03)에서 지운다(그 파일을 읽는 코드 없음). 평가 자료는 나중에 `tests/` 아래로 돌아올 수 있다.
- 파일: `common/config/settings.py`, `pipeline/config.py`, `pipeline/extract/run_all.py`, `common/core/paths.py`.
- Status: done (10-30, `feature/fp-batch`) — 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `common.paths.korean_font`·`eval_sets_dir`(+ 상수 `paths.EVAL_SETS_DIR`), `common.dev.exp_store`·`llm_est_in_tokens`·`llm_est_out_tokens`·`min_gold_coverage`, `common.runtime.exp_max_workers`·`exp_proc_gb_answer/build/run`·`exp_reserve_gb`(+ `resources.plan_experiment`·`resolve_workers`·`resolve_inner_workers` — 쓰던 `stack_matrix`가 지워짐), 읽는 코드가 지워진 `common.models.llm.max_concurrency`(`LLM_MAX_CONCURRENCY`)·`pipeline.transform.structure.wiki_domain_phrase`·`pipeline.eval.diagram_raster_vlm`. 핑거프린트 바뀜(0.1.0 배치).

<a id="pl-30"></a>
## pl-30 · 아무도 안 읽는 env 이름 4개 지우기
- 이유: `FIG_OCR_BUDGET`, `SERVICE_MASTER_CSV`, `DIVISION_MASTER_CSV`, `PROD_MASTER_CSV`가 서버 env 파일에 있지만 읽는 코드가 없다(C-51).
- 결정(사용자 10-30 grill): 0.1.0 릴리스에서 지운다(핑거프린트가 바뀌는 다른 항목과 함께).
- 파일: 서버 env·settings 예시, `common/config/`(설정이나 별칭이 있으면), `refactor.md` C-51.
- Status: done (10-30, `feature/fp-batch`) — `deploy/host/scripts/run_docs.py`의 `UNREAD_PARSE_ENV`·`UNREAD_STRUCT_ENV`(4개 이름)를 명령에서 뺌, 시험 기대 명령도. 핑거프린트 그대로(호스트 스크립트).

<a id="op-05"></a>
## op-05 · settings.yaml 하나 — sample에 모든 키·기본값을 카테고리별로
- 결정(사용자 10-30): "resources/config로 분리하지 말고 그냥 하나의 settings.yaml로 관리하고, 아래 option, default 값 넣고, 카테고리 분류해서 넣으면 될 것 같아. 주석처리도 다 해제하고."
- 무엇:
  - `resources/config` 파라미터 파일은 만들지 않는다. 설정은 settings.yaml 하나에 모두 둔다.
  - `settings.sample.yaml` §2(옵션)·§3(파라미터)를 주석이 아닌 실제 YAML로 쓴다 — 모든 키를 기본값과 함께 섹션(`common`·`pipeline`·`mcp`) 아래에 넣고, 지금 2-1·2-2 … 묶음처럼 카테고리 제목 블록으로 묶는다. 설명·선택지·옛 env 이름은 줄 끝 주석으로 남긴다.
  - 서버·PC의 settings.yaml = sample을 복사해 필수값·비밀값을 채운 것.
  - 모델 연결 정보(모델별 값 — `common.models.embed.query_prefix`, `llm.extra_body`, `vlm.extra_body`)도 그 연결 블록과 함께 settings.yaml에 둔다. `ocrvlm.*`·`vlm.model_alt`는 0.1.0에서 지웠다([parse.md#pl-31](parse.md#pl-31)).
- 결과(알아 둘 것): settings.yaml에 적힌 값이 코드 기본값보다 이긴다. 나중에 코드 기본값을 바꿔도 settings.yaml(또는 sample을 다시 복사)을 고치지 않으면 반영되지 않는다. "키는 한 곳에만" 규칙은 이제 settings.yaml 안에서만의 뜻이다.
- 핑거프린트: 설정 값은 code_fp에 들어가지 않는다 — 값을 바꿔도 자동 재처리는 없고, 필요하면 사람이 재처리한다(10-30 결정 그대로).
- 대체됨(10-30): 앞서 정한 "파라미터 파일 3개(parsing·structure·mcp)로 분리, settings.yaml은 필수·비밀·서버값만, settings.yaml에 파라미터 키가 있으면 거부"는 이 결정으로 없앤다.
- 파일: `common/config/sample.py`(생성기), `settings.sample.yaml`, `common/config/{settings,keyscan}.py`, `pipeline/config.py`, `mcp_server/config.py`, `docs/operations/env-guide.md`.
- Status: done (10-30) — `python -m common.config.sample`이 모든 칸을 코드 기본값과 함께 `common`·`pipeline`·`mcp` 아래 카테고리 순서(제목 주석 `─── N. … ───`)로 낸다. 비우는 칸: 필수·비밀·기본 없음·빈 글자·이미지 기본값 칸(DOC_DIR 등 — 이미지·PC 값이 다름)·적었는지로 동작이 갈리는 칸(`sample.SET_MATTERS` — `given()`·`resources._f`·`model_matrix.own`이 읽는 이름, 예 `STRUCT_BACKEND`를 적으면 정형 저장소가 켜짐)·핑거프린트 칸(pinned — 적으면 `pin_env`가 env로 내어 자식 프로세스 설정을 덮음). 결과를 바꾸는 칸은 `[파라미터]` 표시. 시험: `tests/server/common/test_sample_yaml.py`(복사한 sample로 서버 STRICT 시작 · 적힌 값 = 코드 기본값), `appcheck`(sample 파일 대조).

<a id="op-08"></a>
## op-08 · 설정 구조 재편 — 필수 묶음 + 역할별 파라미터
- 이유(사용자 10-30): `settings.sample.yaml`(칸 약 443개)과 실제 쓰는 settings.yaml(필수만 모은 40여 줄)의 차이가 너무 크다. 필수 입력은 맨 위에 카테고리별로 모으고, 나머지는 역할별 파라미터로 나누고, 칸 수도 줄인다.
- 결정(사용자 10-30 grill):
  - 칸 경로를 바꾼다(보기만 정리하지 않음) — YAML은 같은 절을 두 번 쓰면 뒤가 앞을 덮으므로, 필수 묶음은 별도 최상위 절 `required`로 둔다.
  - 구조: 맨 위 `required`(필수 입력만 — 실행 환경 · PG(gold) · EDW · Object Storage · 모델 연결·키 · 서버 이미지 등, 카테고리마다 구분선과 `[PC·서버]`·`[서버만]`·`[PC만]` 표시를 칸마다가 아니라 카테고리 제목에 한 번) → 구분선 → 파라미터 절 7개 `common`·`extract`·`transform`·`load`·`search`(MCP 검색)·`ops`(실행 자원·스케줄·서비스·서버 컨테이너·경로)·`dev`(PC·시험·평가 전용).
  - 필수 = 운영자가 꼭 넣어야 하는 값(기본값이 쓸 수 없는 연결 주소·계정·비밀·이미지 태그). 기본값이 있으면 필수가 아니라 파라미터(예: EDW 포트 1433, Object Storage 리전).
  - 설명은 짧게(한 줄) — 옛 env 이름·판정 꼴 같은 내부 표시는 sample에서 뺀다(필요하면 env-guide).
  - 사용처가 없는 칸·뜻이 겹치는 칸은 코드에서 지운다(고정값이면 코드 상수로). 지울 목록은 지우기 전에 사용자 확인.
  - 시점: 0.2.0에 함께 — 설정 모델 파일은 모든 레이어의 code_fp에 들어가 서버 전체 재처리가 생기므로, 전체 재적재가 있는 gold 원천별 스키마(pl-28)와 한 번에 묶는다.
- 조사(10-30, 칸 443개): 필수 42(PC·서버 11, 서버만 31) · 파라미터 281 · 경로 49 · PC·시험 전용 61 · 사용처 없음 8 · 중복 2.
- 결정(사용자 10-30 2차):
  - 지운다(10개): `common.paths.criteria_file`(코드 상수 사용) · `pipeline.load.publish.source_system`(코드 고정값) · `mcp.search.ocr_dpi`(읽는 곳 없음) · `common.paths.config_dir`(셸은 `$SERVER_ENV_DIR`) · `pipeline.eval.e2e_qa_set`·`e2e_questions`(형식 점검만) · `common.dev.docker.postgres_db`·`postgres_user`(compose는 `PG_DB`·`PG_USER`) · 중복 `mcp.server.query_cache` → `common.models.embed.query_cache`, `pipeline.transform.structure.edw_embed` → `structure.embed`로 합침.
  - 켜기·끄기 스위치(약 40개)는 세분 카테고리로 모아 목록으로 보여 준다 — 기능이 없어진 스위치는 지운다. 파라미터 절의 카테고리는 더 세분해도 된다.
  - 운영 값(대기 시간·작업자 수·자원 한도·상한 등)은 파라미터로 두되, 기본값 말고 다른 값을 쓴 흔적이 없는 것을 "코드 상수 후보"로 추려 보여 준다.
- 조사(10-30, 켜기·끄기 스위치 91개): 기능 없어짐 0 · 되돌리기 전용(기본 켬, 끄면 옛 동작) 51 · 실험·기본 끔 27 · 양쪽 다 쓰임 13. 운영 값 254개 중 기본값 외 값을 쓴 흔적 없음 = 코드 상수 후보 103.
- 결정(사용자 10-30 3차):
  - 되돌리기 전용 스위치는 스위치와 옛 동작 코드를 지우고 항상 켠다. 단 엔진·핸드오프 지문 파일 안의 5개(`pipeline.extract.fill_merged`·`kreuzberg_prose_filter`·`ocr.table_grid`, `common.text.search_en_stem`·`token_num_norm`)는 재파싱을 피하려고 남기고 다음 엔진 개정 때 정리한다.
  - 스트리밍 파싱(`pipeline/stream.py`)은 기능째 지운다 — 스위치 `stream.stream`·`stream.fingerprint`·`cache.keep_raw_layer`·`cache.keep_engine_cache`·`dev.stream_test_crash`도 함께.
  - 쓰지 않는 실험 기능(기본 끔)은 기능째 지운다 — 목록은 지우기 전에 확인. 운영·보안 선택(고객 하드 격리, 표 허용 목록, 외부 허용, 가짜 LLM 등)과 run_docs가 실제로 켜는 칸(`qa_light`, `bucket_skip_overlap_check`)은 파라미터로 남긴다.
- 결정(사용자 10-30 4차):
  - 실험 기능 6개를 기능째 지운다: 그림자 모드(`transform.represent.shadow` + 평가 도구 `parse_shadow`) · 집계 LLM 분류(`mcp.search.agg.llm`·`llm_timeout`) · LLM 묶음 요약(`structure.edw_summary_llm`) · 글자 이미지 VLM 생략(`vlm.fig_text_skip`) · 키워드 통계 전체 재계산(`load.bm25_stat_rebuild`) · 원본 보관(`cache.keep_local_originals`). 남김: OCR 엔진, `qa_light`·`bucket_skip_overlap_check`(run_docs가 켬), `pg_create_extension`·`score_table_judge`(→ `dev`).
  - `common.models.embed.dim`은 지운다 — 적재·검색은 모델이 준 벡터 길이를 쓰고, 이 칸은 `ping_models`의 기대값 비교에만 쓰였다(점검은 받은 차원을 보여 주기만).
  - 코드 상수 후보는 바로 지우지 않고 sample 맨 아래 별도 절(구분선)에 모은다 — 내부 조정값 32개(재시도·내부 대기·묶음 크기·출력 상한 등)와 자원·대기·병렬 세부값 약 20개(자동 계산 내부 계수 `mem_*`·`pipe_max_procs`·`pipe_proc_gb`·`pipe_reserve_*`·`pipe_threads`·`cpu_max_load`, `llm.timeout`·`embed.timeout`·`attach.timeout`·`vlm.deadline`, `vlm.page_concurrency`·`page_min_concurrency`·`figures.vlm_parallel`·`night.vlm_concurrency`·`night.workers`·`parse_mcp.procs`). 상수로 내릴지는 그 절을 보고 나중에 정한다.
  - 프로세스 수·메모리는 필수 입력이 아니다 — 비우면 CPU·메모리로 자동 계산. 역할 절에 남기는 자원 칸: `pipe_procs`·`pipe_workers`·`vlm.max_concurrency`·`llm.rpm`, 새벽 배치 시각·마감, run_docs 레인 워커 수, 컨테이너 CPU·메모리 한도, 내부망 주소 범위.
  - 엔진 지문 파일이 읽는 `vlm.retry`·`vlm.timeout`도 다음 엔진 개정 때 정리한다.
  - 서버 settings.yaml은 `python -m common.config.migrate`가 옛 경로 → 새 경로로 바꿔 준다(지운 칸은 "삭제됨"으로 알림).
- 결정(사용자 10-30 5차 — 설계 확인): 지울 칸 68개 목록대로 진행(A 사용처 없음·중복 10 · B 되돌리기 스위치 45 · C 스트리밍 6 · D 실험 7 · E `embed.dim` 1). `represent.table_db`는 "항상 켬"이 아니라 기능째 지운다(정형 저장소 `doc_table`·`doc_cell`은 D-7로 0.2.0에 없어짐). 원칙: 스위치를 지울 때 그 스위치가 고르던 다른 길(옛 동작·옵션 기능) 코드도 함께 지운다 — 나중에 켜기·끄기가 필요하면 새 기능으로 다시 넣는다.
- 열린 질문: 없음.
- 진행: ① 칸·기능 삭제 커밋 → ② 경로 재편(`required`·역할 절·`tuning`) + migrate 변환 + sample 생성기 → ③ 문서(env-guide, README 설정 예시).
  - ①-1(10-30): A 10 + E 1 지움 — 옛 설정 파일의 지운 칸은 경고만(`REMOVED`), 옛 env 이름은 migrate가 "삭제 후보(삭제됨 op-08)"로 알림. 검색 MCP 질의 캐시 기본(`/tmp/mcp_query_cache.sqlite`)은 mcp 이미지의 `common.models.embed.query_cache` 기본값으로 옮김.
  - ①-2(10-30): B 되돌리기 스위치 45 지움 — 동작은 늘 기본값(켬), 옛 동작 코드·끔 경로 시험도 지움. `represent.table_db`는 표 정형 적재(`load_tables_db`·`structured tables`)째 지움 — 검색 쪽 `doc_table`·`doc_cell` 읽기 코드와 표 정의는 pl-28(D-7)에서. 빈 절 `mcp.search.query_expand`도 지움. 평가 도구 AR1(융합 켬/끔 비교)도 지움.
  - ①-3(10-30): C 스트리밍 6 지움 — `pipeline/stream.py`·`pipeline/tools/check_residue.py`·`dedup.record_fingerprint`와 그 시험, 빈 절 `pipeline.extract.stream`. 첨부 임시 폴더 `attach_dir`는 `represent/attachments.py`로 옮김(자리 그대로 — PARSE_TMP의 형제 `attach/`).
  - ①-4(10-30): D 실험 7 지움 — 그림자 모드(`represent/shadow.py`·`eval/parse_shadow.py`), 집계 LLM 분류(`aggregate.llm_plan`·`route`의 LLM 갈래), LLM 묶음 요약(`build_bundle --summary llm`·색인 설정 `summary: llm`), 글자 이미지 VLM 생략, 키워드 통계 전체 재계산 스위치, 원본 보관(보존 상한 경로 포함)과 그 시험. 쓰는 곳이 없어진 칸(`shadow_max`·`agg.llm_min`·`cache.parse_keep_max_gb`, C의 `parse_tmp_max_gb`·`disk_free_warn_gb`·`engine_cache_warn_gb`)은 ②에서 지움. 지시문 묶음 `parse_shadow`·`agg_llm_route`·`doc_summary`는 시험이 읽어 남김.
  - ②(10-31): 칸 자리 재편 — 새 모듈 `common/config/layout.py`(파일 자리 ↔ 모델 경로 표: `required` 41칸 · 역할 절 접두어 규칙 · `tuning` 58칸 = 내부 조정값 38 + 자원·대기·병렬 20). 설정 모델 경로(`common.*`·`pipeline.*`·`mcp.*`)는 그대로 두고 `read_settings`가 파일을 모델 배치로 바꿔 읽음(`export --section`·`data=`는 모델 경로). 옛 배치는 시작 거부 + migrate 안내, 자리가 다른 칸은 "자리가 다른 칸 … → 새 자리"로 거부. `migrate <옛 settings.yaml> --out <새 파일>` = 새 배치로 변환(값은 쓴 글자 그대로, 지운 칸은 "삭제됨"). 쓰는 곳 없는 6칸 지움(`parse_tmp_max_gb`·`parse_keep_max_gb`·`disk_free_warn_gb`·`engine_cache_warn_gb`·`shadow_max`·`agg.llm_min` — `REMOVED` 경고만). sample 주석 한 줄(설명·기본값·값) — 옛 env 이름·판정 꼴은 `python -m common.config.sample --where 이름`. 호스트 `run_docs.py`도 새 배치를 읽음. 칸 수 374 → 368(required 41 · common 44 · extract 54 · transform 26 · load 7 · search 30 · ops 73 · dev 35 · tuning 58). 문서(③): env-guide·README §4-2·서버 가이드 갱신(옛 서버 값 표는 env-guide로).
- 파일: `common/config/{layout,settings,sample,keyscan,migrate,export}.py`, `pipeline/config.py`, `mcp_server/config.py`, `settings.sample.yaml`, `deploy/host/`(설정 꺼내 쓰는 셸), `docs/operations/env-guide.md`.
- 결정(사용자 10-31 grill): tuning 절은 지금대로 — 운영 정책 값 6개(prepare.link·publish.upload_statuses·load.edw_path_prefix·mcp.server.instructions·search.pg.vector_search·trigger.upload_max_mb)는 역할 절, 내부 제한 시간·대기열 13개는 tuning. 옛 배치는 계속 거부한다. PC 루트 settings.yaml은 10-31에 `settings.yaml.bak-20261031`로 백업했고 op-08 병합 직후 migrate로 새 배치로 바꾼다. 서버 2곳 변환은 0.2.0 배포 절차(refactor.md)에 넣는다.
- Status: todo

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 외부(유료) 모델 | `*_ALLOW_EXTERNAL=0`, PC만(`RUN_ENV=local`) | 예산 상한(`LLM_BUDGET_USD`, `LLM_MAX_CALLS`) |
