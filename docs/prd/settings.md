# 설정·운영 — settings.yaml·RUN_ENV·계정·로그·외부 모델

[PRD.md](../PRD.md)의 카테고리 하나. 두 앱이 함께 쓰는 설정, 실행 환경(`RUN_ENV`), EDW 계정, 로그, 외부 모델 호출 가드.
op-01~03의 출처: COMPANY 거버넌스 프로젝트별 검토, 10-29(임시 표준).

순서(주제별): 실행 환경·외부 모델 op-02·pl-11 → 계정 op-03 → 종료 정리 pl-27 → 로그 op-01 → 미룬 설정 정리 pl-21·pl-30 → settings.yaml 하나 op-05 → 코드와 다른 점.

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
- Status: dev — `feature/exit-cleanup`. code_fp 모든 레이어가 바뀜(`common/` 공용 의존). 남은 일(todo, 사용자 10-30 grill 12~13차 — refactor.md C-46): 강제 종료(SIGKILL·OOM)로 남은 덮기 설정 임시 파일은 다음 시작 때 지운다 — 만든 프로세스가 더는 없는 임시 설정 파일을 지움.

<a id="op-01"></a>
## op-01 · JSON Lines 사건 기록(두 앱)
- 이유: 기존 runlog·runs.jsonl·MCP 질의 기록을 유지하면서 두 앱의 사건·감사·성능 기록을 같은 형식으로 남긴다.
- 공통 구현(10-30, T0): `common/core/jsonlog.py`의 `setup(app)`은 표준 logging으로 `time, level, app, event, msg, request_id, run_id, span_id, duration_ms, err` JSON 한 줄을 쓴다. `_mask()` 재사용, PC 기본 `logs/<앱>.jsonl`, 서버 stdout. `common.log.level/dir`로 제어하며 contextvars ID는 `settings.child_env()`의 내부 신호로 자식에 전파된다.
- DB: `common/store/logsink.py`의 `emit(table,row)`/Handler → 제한 큐 → 백그라운드 배치 INSERT. DB 실패 시 `common.log.fallback_dir`(기본 `output/applog`) jsonl로 대체, 프로세스당 경고 한 번. 큐 포화는 즉시 드롭하고 `stats().dropped`로 집계한다. 종료는 exitclean에서 DB 대기와 대체 파일 I/O를 합한 단일 deadline(`shutdown_sec`)까지 flush한다. DB 대기는 남은 예산의 절반까지 하고 나머지 예산에 데몬 스레드가 파일 기록을 시도한다. 파일 잠금/쓰기가 막혀도 deadline에 반환하며 미완료 행은 `dropped`로 집계하고 stderr에 프로세스당 한 번 경고한다(이미 진행 중인 OS 쓰기는 나중에 끝날 수 있으므로 집계/재적재 시 상관 ID 대조). 종료 시 커밋 결과가 불명확하면 DB/파일에 중복될 수 있다(상관 ID 대조).
- 스키마: Alembic `0001_applog` / `dbtool up --target applog`. `mcp_call(ts)`·`pipe_event(ts_start)`는 월 파티션(복합 PK에 월 키 포함), `pipe_run`은 일반 테이블(run_id PK, 시작 running/종료 UPSERT). up/maintain은 현재 달+앞으로 2개월을 준비한다. `dbtool maintain --target applog`를 매일 예약해 다음 월 준비·90일 보존 정리(월 끝이 만료된 파티션 DROP, pipe_run DELETE). sink는 DDL을 실행하지 않는다.
- 설정: `common.log.db_enabled` 기본 false — 마이그레이션 후 true로 켬. `retention_days=90`, `queue_size=10000`, `batch_size=200`, `flush_sec=1`, `db_timeout_sec=2`, `shutdown_sec=5`. `mcp.audit.max_input_bytes=16384/max_output_bytes=65536` 제공(설정은 YAML만).
- MCP 구현(10-30, T1): `services/call_log.py`가 `_bg`/`_bg_long` 호출당 `applog.mcp_call` 한 행을 공통 sink에 보낸다. 성공·도구 오류·busy·timeout·HTTP 인증 거부를 기록하고 sink/직렬화 실패가 도구 응답·예외를 바꾸지 않는다. 본문은 JSON UTF-8 직렬화 후 비밀값 마스킹·앞부분 저장(기본 입력 16KB/출력 64KB, 중간에서 잘린 JSON은 완전한 JSON이 아닐 수 있음). `*_bytes`와 `result_sha256`는 상한 적용 전 전체 원본 JSON 기준이며 `*_truncated`는 마스킹된 본문을 잘랐는지 표시한다. parse_document의 content_b64는 디코딩한 파일 sha256·바이트 수로 대체(잘못된 base64면 인코딩 문자열 기준 표시). result_keys는 본문 상한과 별개로 search의 chunk_ids/rank/via/evidence_status/total_docs/total_chunks, query_edw의 row_count/columns, parse_document의 job_id/engine/rep_path/text_chars, edw_meta의 단계·테이블·컬럼 수를 추출한다.
- MCP 컨텍스트: HTTP `X-MCP-Client`→agent(기존 CALLER와 함께 유지), `X-MCP-User` 우선·없으면 `params._meta.user`, remote_addr·Mcp-Session-Id. 유효한 UUID `X-Request-Id`는 그대로 전달하고 없거나 UUID가 아니면 새 UUID를 만들어 응답 헤더에도 보낸다. stdio는 agent=stdio이며 콘솔 로그는 stderr로 보낸다(stdout은 JSON-RPC 전용, 명시 파일 로그는 유지). `jsonlog.setup(app, stream=...)`의 앱별 스트림 보존으로 logger 재설정 뒤 SDK 하위 로그도 보호한다(coordinator 승인, 기본 호출 동작 불변). **stateless_http이므로 도구 호출의 client_info/session_id는 같은 요청에서 알 수 없으면 null** — initialize 자체를 별도 행(tool=initialize)으로 기록하며 client_info는 clientInfo+protocolVersion이다(추정 캐시 연결 없음, coordinator 결정). 인증 거부는 본문을 기다리지 않고 tool=http로 기록한다. timeout 뒤 실행 중인 스레드는 DEBUG `mcp.thread.abandoned`와 `mcp.thread.finished`(실제 종료 시각)로만 추적하며 감사 행을 더 만들지 않는다. qa_log.jsonl은 기존 동작 그대로, 검증 UI 헤더는 test/test다.
- 교차 검토 수정(10-30 F1·11-01 F4 — P1-1/P1-3/P2): 공개 `jsonlog.masked(value)` 한 곳이 기존 라벨 패턴과 settings의 `SecretStr` 칸 값을 함께 가린다. 4자 이상은 부분 문자열을, 1~3자는 앞뒤가 문자·숫자가 아닌 토큰 경계에서만 가린다. 짧은 비밀값이 문자·숫자에 붙으면 값 대조로 가려지지 않는 한계가 있다. 설정 시작은 거부하지 않고 해당 설정 칸 경로만 프로세스당 한 번 stderr에 경고한다. JSON 형식 비밀 설정의 개별 문자열은 기존 `_LABEL` 비밀 라벨 키의 값만 추출하며 driver/host와 라벨 없는 리스트 문자열은 값 대조에 넣지 않는다. DSN 비밀번호·URL/JSON 이스케이프·중첩 값·분리 CLI 인자·오류/traceback에도 적용한다. 설정 캐시의 비밀 칸만 수집하며 원본을 바꾸지 않는다. JSON 줄과 sink DB/대체 파일 및 MCP args/result/err에 같은 API를 쓴다. 기존 DSN 패턴은 스킴 중간 재시작을 막아 긴 일반 문자열의 제곱 시간 역추적을 없앴다.
- 감사 지연 수정(F1·F4): ASGI는 수신 청크를 그대로 SDK에 전달하며 감사용 본문은 최대 1MiB만 모아 스레드에서 파싱한다. 초과하면 `_meta.user`/method/initialize 추출을 생략하고 헤더 컨텍스트를 쓰며, 도구 입력은 거부/제한하지 않는다(도구명·args는 dispatch에서 얻음). `_bg`/`_bg_long`은 감사 처리를 await하지 않는다. 시각·상태·소요 시간은 호출 시 확정하며 입력/결과 직렬화·상한 처리·해시·마스킹·emit은 도구 anyio limiter와 독립된 전용 데몬 스레드 하나가 맡는다. 본문 대기 큐는 64건이며 포화 시 args/result가 NULL이고 result_keys.audit_body_omitted=queue_full·err=audit_queue_full인 메타 행만 비차단 sink로 보내고 call_log.stats().body_omitted를 올린다(sink 포화는 기존 dropped). 감사 큐는 건수 상한이며 입력/결과 한 건의 크기를 제한하거나 거부하지 않는다. busy는 판정 즉시, timeout은 감사 지연 없이 기존 도구 시간 예산으로 반환한다. 종료는 감사 워커→sink 순서로 기존 shutdown_sec 단일 deadline을 공유하고 미완료 감사 행은 call_log.stats().dropped로 집계한다. JSON/base64 해시는 64KiB 청크로 누적해 전체 바이트 사본을 만들지 않는다.
- 수용 기준: JSON 필수 키·비밀 마스킹·수준 필터·컨텍스트 격리/자식 전파·DB 실패 파일 기록·큐 드롭 집계·정상/SIGTERM 종료 flush, PC 임시 PG 스키마 up/check·UPSERT·파티션 보존 정리 시험.
- 검증(10-30 T0): 새 서버 시험 2개·PC PG 시험 1개 통과, lint/mypy·모듈 경계·sample/keyscan 통과. 전체 selftest 94/96, pytest 148 passed·3 xfailed·1 failed — 새 실패 없음; 기존 publish_guard와 HEAD 538067a의 ParsingMeta 명세 불일치(test_db_schema, rep_engine/engines_used)를 coordinator 확인대로 유지.
- 검증(11-01 F4): 짧은 비밀값의 전체/분리 인자/토큰 경계와 비일치·stderr 1회(값 미포함), JSON driver/host·라벨 없는 리스트 오탐 제거, 실제 sink 마스킹, 감사 준비 0.3초 지연 중 timeout 0.05초·busy/정상 응답 독립성, anyio 공용 limiter 포화 독립성, 큐 초과 메타 1행/집계·sink 포화 비차단, 정상/lazy sink 종료 flush·막힌 감사의 0.08초 공유 deadline 시험 통과. tools/list 9,330바이트·SHA-256 불변, lint/모듈 경계/sample/keyscan 통과. 단독 전체 selftest 101/103(기존 test_db_schema·test_publish_guard), pytest 157 passed·3 xfailed·1 failed(기존 test_db_schema). 최초 동시 전체 시험의 시간 민감 실패는 단독 재실행에서 통과했다.
- 검증(10-30 F1): 설정 비밀값 중첩 args/result·err/traceback·DSN·분리 인자, DB/대체 파일, busy 후 스레드 처리 및 큰 content_b64 감사 중 /health 지연, ASGI 청크 동일성/1MiB 초과 파싱 생략, 막힌 fallback 잠금/쓰기 종료 상한, 기존 마스킹 예시 동일성·1/2MiB 선형 시간 시험 통과. tools/list 9,330바이트·SHA-256 불변. 전체 selftest 99/101(기존 test_db_schema·test_publish_guard), pytest 155 passed·3 xfailed·1 failed(기존 test_db_schema), 새 실패 없음.
- 검증(10-30 T1): tools/list가 T0와 9,330바이트·SHA-256까지 동일. 새 감사 서버 시험(실제 ASGI·stdio JSON-RPC 포함)·UI 헤더 시험 통과, 전체 selftest 95/97 및 pytest 150 passed·3 xfailed·1 failed(test_db_schema) — 기존 실패만 유지. 전용 PG에 test/test search 1행과 initialize 1행, args/result/result_keys/duration_ms를 SQL로 확인; PG 검색 스키마 0행을 확인한 뒤 준비된 번들을 읽기 전용 BM25로 검색해 chunk_ids=[0]/rank=[1]/via=[k]/evidence_status=found와 result_truncated=false도 확인. 승인된 stdio 스트림 보존 보완은 common jsonlog에만 적용(기본 호출 불변), 이에 따른 code_fp 전후는 T1 커밋에 기록.
- 위험: 공용 의존 변경으로 code_fp 변경(이번 판 pl-25와 묶음), 핸드오프/엔진 바이트 유지. 검토 등급 A(비밀값·DB 스키마). 서버 DBA 협의·마이그레이션·maintain 예약은 refactor.md C-68.
- 파일: `common/core/{jsonlog,exitclean}.py`, `common/store/logsink.py`, `common/store/db/`, 설정 모델/sample, `tests/server/common/test_{jsonlog,logsink}.py`, `tests/general/common/test_applog_pg.py`, `mcp_server/services/call_log.py`, `mcp_server/{main.py,routers/dispatch.py}`, `tests/server/mcp/test_call_log.py`, `validation/search_ui/serve.py`.
- 진행(10-30, T2 — 파이프라인 성능·추적): 기록 단위 3개. ① 실행 1건 = `applog.pipe_run`(`pipeline/cli.py` `__main__`의 `runtrace.run`이 `run_id`를 만들고 시작 `running`·종료 UPSERT, code_fp·stack·settings_hash·문서 수·workers·cpu_max_load·mem_start_pct — 부모가 이어준 run_id가 있는 자식은 새로 시작하지 않음). ② 문서×단계 span = `applog.pipe_event`(`common/core/span.py` — `with span("extract.parse", doc_id=…, engine=…) as s: s.add(pages=…)`; 중첩 `parent_id`, 오류는 `status`·`err_kind`(env/timeout/doc/external/db)로 기록하고 다시 던짐 — `err`는 예외 타입 이름(+OSError는 errno 이름)과 `span.safe()`로 표시한 우리 코드의 고정 문구만 저장하는 allowlist이며 외부 라이브러리·파서 예외 문자열 원문은 저장하지 않는다(`run_all.redact`의 `redact_text`는 runs.jsonl용으로만 남음)). ③ 60초마다 `stage='run.progress'`(`runtrace.Progress` — 완료/전체·docs/min·남은 시간 추정·단계별 진행 중 개수·부하·메모리). `run_id`가 없으면(MCP 검색·시험) span은 아무것도 안 하는 가짜라 DB·스레드·지연이 0이다(서버 시험으로 고정).
- 계측 지점: `common/core/resources.gated_popen`(메모리 문 `wait_mem_ms`·CPU 문 `wait_cpu_ms`를 열로, 다른 launcher 대기·settle은 metrics, 자식에 `APPLOG_CONTEXT`로 run/span ID 전달 — 스레드 풀은 `span.carry`) · `pipeline/cli.py`(`proc.run` — 하위 프로세스 1개) · `run_all.py`(`extract.plan`, 문서×엔진 `extract.parse`, 조각 `extract.shard`; 자식 `parse_one`이 stdout 끝에 남기는 cpu_ms·rss_peak_mb 한 줄을 부모 span이 옮김 — 엔진 파일은 그대로) · `represent.py`(`transform.represent`, `transform.figures`: VLM/OCR 호출 수·재시도·지연 p50/최대·토큰은 `common/ai/adk.complete` 래퍼가 열린 span의 metrics에 쌓음) · `build_bundle.py`(`transform.structure`: 청크 수·길이, `embed.bundle`: 캐시 적중/실패·배치 수·호출 지연·재시도·토큰 — `embed.py`) · `llm.py`(응답 캐시 적중·분당 상한 대기) · `pgvector_load.py`(`load.pgvector` + 표별 `load.doc/chunk/chunk_term/stats`: 행 수·rows/sec) · `publish_parse_result.py`(`load.publish`). INFO는 문서×단계 span까지, 개별 호출은 span.metrics 요약과 DEBUG만. 기존 `runs.jsonl`·`RUNLOG`·`PROGRESS.md`는 그대로. 최상위 진입점은 `pipeline.cli`(parse·structure·load·night·run-stack·compare-*)와, 직접 실행하는 `run_all`·`represent`·`build_bundle`·`pgvector_load`·`publish_parse_result`(부모가 `run_id`를 이어주지 않았을 때만 자기 `pipe_run`을 시작 — 서버 호스트 `run_docs.py`의 구조화+적재는 `build_bundle`·`pgvector_load`를 직접 불러 실행 2건으로 남는다). 점검·설정 명령(selftest·smoke·set-*·show-*)은 추적하지 않는다.
- 분석: `python -m pipeline.tools.perf [<run_id>]` — 단계·엔진별 p50/p95/최대·건수·실패율·wall/층 비율·wait 비율, 쪽당 시간, 느린 문서 N개(`--top`), 캐시 적중률·재시도율·실패율, `--compare <run_id>…`로 code_fp·stack·settings_hash 차이와 단계별 p50 비교, `--runs`로 최근 목록, DB가 꺼진 PC는 `--file output/applog/*.jsonl`. 읽기 전용.
- 검증(10-30 T2): 서버 시험 `test_span`·`test_runtrace`·`test_perf`·`test_span_stages` 4개(span 중첩·parent_id, 오류 status/err_kind, wait_mem/cpu 분리와 자식 프로세스 run/span ID 전달, run.progress 주기, perf 집계, 임베딩 캐시/배치/재시도·적재 표별 span — 임베딩은 `patch.object`, 적재는 가짜 커서, 검색 경로 no-op 고정)와 PC 시험 `tests/general/pipeline/test_perf_pg.py`(임시 스키마 `test_t2perf_*`). 실데이터 스모크는 `valid_env` 문서 3건으로 `pipeline.cli parse`(→ `build_bundle --embed none`)까지: `pipe_run`·`pipe_event`에 extract/transform 단계 행, `perf.py` 출력 확인. **사용자 결정(10-30): 외부 임베딩 호출 금지 — 캐시 적중이 1/27이라 임베딩·pgvector 적재의 PC 실데이터 스모크는 하지 않음(미검증).**
- 계측 fail-soft(10-30 F2, 교차 검토 P1-2): span 시작 측정·종료 기록·`pipe_run` 시작/종료·`run.progress` 스레드의 모든 예외는 계측 안에서 삼킨다 — 업무 코드의 정상 결과를 바꾸지 않고, 업무 예외가 있으면 원래 예외를 그대로 다시 던진다. 로그 디렉터리 권한 오류로 `jsonlog.setup`이 실패하면 30초간 다시 열지 않고 span을 가짜로 대체한다. 실패는 프로세스당 1회 stderr 경고(`[applog] 계측 실패…`, 예외 타입만)와 `span.failure_count()` 카운터로만 남는다. `Span.result()`의 status/err_kind 값 검증(프로그래머 오류)만 예외로 남김.
- 오류 필드(10-30 F2, P2-5): `pipe_event.err`와 JSON 로그의 `err`는 allowlist — 예외 타입 이름(+errno 이름·CalledProcessError 종료 코드)과 `span.safe(...)` 고정 문구. `sp.result(…, err)`에 그냥 글자를 주면 맨 앞 예외 클래스 이름만 남고 나머지는 버린다. 로컬 DEBUG에도 원문을 남기지 않는다. `err`와 `metrics`의 글자, `pipe_run.args`(인자별)는 저장 전에 `jsonlog.masked`를 거친다.
- 한계: `cpu_ms`는 이 프로세스(RUSAGE_SELF)와 span 안에서 끝나 회수(wait)된 자식 프로세스(RUSAGE_CHILDREN)의 CPU 시간 합이다(10-30 F2, P2-6 — subprocess 작업 포함). 서로 조상이 아닌 `cpu=True` span이 같은 프로세스에서 겹치면 둘 다 NULL(0으로 채우지 않음). `cpu=False` span과 겹치는 자식은 구분하지 못하므로 `cpu=True`는 호출부가 직렬일 때만 쓴다. span이 끝날 때까지 안 끝난 자식·손자의 CPU, Windows(`resource` 없음)·측정 실패는 NULL이다. `rss_peak_mb`는 이 프로세스만이다. `cpu_ms`·`rss_peak_mb`는 프로세스에서 하나만 도는 span(자식 프로세스 루트·represent 문서 직렬 실행·적재)과 `parse_one` 자식 값만 정확하다(스레드로 겹치는 span은 비움). macOS는 `mem_used_pct`가 비고(`/proc` 없음) Windows는 cpu_ms·부하가 빈다. 문서 수 `docs_reused`는 parse에서만 채운다(이번 run_id로 엔진을 돌린 기록이 없는 문서).
- 파일(T2·F2): `common/core/span.py`, `common/core/resources.py`, `common/ai/{adk,embed,llm}.py`, `pipeline/shared/runtrace.py`, `pipeline/tools/perf.py`, `pipeline/cli.py`, `pipeline/extract/{run_all,parse_one}.py`, `pipeline/transform/{represent/represent,figures/figures,figures/vlm_page,structure/build_bundle}.py`, `pipeline/load/{pgvector_load,publish_parse_result}.py`, `tests/server/common/test_span{,_soft}.py`, `tests/server/pipeline/test_{runtrace,perf}.py`.
- 결정(사용자 10-30 grill): gold DB 변경([etl.md#pl-25](etl.md#pl-25))과 같은 판에 싣는다 — 재처리 한 번.
- Status: partly done (10-30) — 공통 토대·DB 마이그레이션·MCP 감사 호출 계측(T1) 구현, 파이프라인 span/성능 분석(T2)은 후속 작업.

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

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 외부(유료) 모델 | `*_ALLOW_EXTERNAL=0`, PC만(`RUN_ENV=local`) | 예산 상한(`LLM_BUDGET_USD`, `LLM_MAX_CALLS`) |
