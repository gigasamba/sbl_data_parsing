# 설정 작성 가이드 — `settings.yaml`(서버·PC)

↑ [server-guide.md](server-guide.md) · [release-and-patch.md](release-and-patch.md) · 옛 동작 기록: [env_guide_history.md](../history/env_guide_history.md)

**원칙**
- 코드는 이미지+패치로 관리하고, 서버에서 손대는 것은 **설정 파일 하나**(`settings.yaml` — D-015·D-028)뿐이다.
- 값은 문서·채팅·로그에 쓰지 않는다 — 이 문서는 **이름만** 적는다.
- settings.yaml = `settings.sample.yaml`을 복사해 맨 위 `required` 절을 채운 것이다(op-08 ② — 배치: `required`(꼭 채울 값, 카테고리마다 `[PC·서버]`·`[서버만]` 표시) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(코드 상수 후보 — 보통 비워 둠)). sample에 모든 항목이 코드 기본값과 함께 들어 있다. 값이 빈 항목은 적으면 동작이 바뀌는 것도 있으니 필요할 때만 채운다. 적힌 값은 코드 기본값보다 이긴다 — 나중에 코드 기본값이 바뀌어도 settings.yaml을 고치지(또는 새 sample을 다시 복사하지) 않으면 반영되지 않는다.
- 옛 배치(최상위 `common`·`pipeline`·`mcp` — op-08 전) 파일은 읽지 않는다(시작 거부 — 안내 메시지). `python -m common.config.migrate <옛 settings.yaml> --out <새 파일>`로 바꾼다(값은 쓴 글자 그대로, 지운 칸은 "삭제됨"으로 이름만 알림 — 두 앱 모델이 다 있는 코드 폴더·저장소에서 실행). 자리가 바뀐 칸을 옛 자리에 쓰면 "자리가 다른 칸 … → 새 자리"로 거부한다.
- 이 문서의 표는 **옛 env 이름**으로 적는다. 파일 자리·내부 표시(판정 꼴 `[켬: 1만]`·`[빈 글자 유지]`·`[엔진 지문]` 등 — sample에서는 뺌)는 `python -m common.config.sample --where <이름>…`로 찾는다(예 `PG_HOST` → `required.pg.host`).
- 옛 서버 값(옛 `options.conf`·compose가 서버 컨테이너에 주던 값 중 코드 기본값과 결과가 다른 것 — C-39·C-43·C-54) — 지금 동작을 지키려면 서버 settings.yaml에 이 값을 적는다:

| 옛 이름 | 파일 자리 | 서버 값 |
|---|---|---|
| `RUN_MODE` | `required.env.run_mode` | `prod`(모든 환경 — 빠뜨리면 PG 연결 실패 때 SQLite로 조용히 대체) |
| `PARSE_POST` | `transform.represent.post` | `all` |
| `EDW_QUERY_MAX_ROWS` | `search.edw_query.max_rows` | `1000` |
| `EDW_QUERY_TABLES` · `EMBED_QUERY_CACHE` | `search.edw_query.tables` · `common.models.embed.query_cache` | `''`(빈 글자 — 비운 칸과 결과가 다름) |

## 0. 파일 위치 · 적용 방법

| 기계 | 파일 | 적용 | 모델 엔드포인트 |
|---|---|---|---|
| PC(개발) | 저장소 루트 `settings.yaml`(git 밖, 권한 600). 구조·설명은 루트 `settings.sample.yaml`. 임베딩 키(`EMBED_*`)도 여기(CLAUDE.md §7) | `RUN_ENV`가 없거나 `local`이면 코드가 이 파일을 찾음(파일 안 `required.env.run_env: local`). 한 번 실행에 몇 항목만 바꿀 때는 오버레이 설정 파일: `SETTINGS_FILE=$(python -m common.config.overrides PIPE_OUT_ROOT=… EMBED_ALLOW_EXTERNAL=1 …)`(**PC 전용**) | 내부망 또는 OpenRouter(기능 테스트만) |
| 수집·개발 서버 | `$SERVER_ENV_DIR/settings.yaml` = `/srv/rag/env/settings.yaml`(코드 폴더 밖). **주인 UID 10001(컨테이너 사용자)·그룹 운영 계정 그룹·권한 640**(운영 계정 UID가 10001이면 600 — `refactor.md` C-09) | 컨테이너: compose가 `/etc/rag/settings.yaml`에 읽기 전용(`:ro,z`)으로 붙이고(+ `data-pipeline`에만 settings.yaml이 있는 폴더 통째로 `/etc/rag/env`에 읽기 전용 — EDW 사슬 사본 등, 폴더 root:10001 750·안 파일 640 이하, 사용자 11-03) env는 `SETTINGS_FILE`·`RUN_ENV`만 준다(비밀은 `docker inspect`에 안 나옴). **값을 바꿀 때는 이 파일을 직접 고친다**(오버레이 설정 파일 도구는 서버에서 막힘). 셸·systemd: `deploy/host/scripts/settings_env.sh`의 `load_settings`가 호스트 항목(이미지·자원·포트·`RAG_OUT`·`DOC_SRC`·`NIGHTLY_*` 등)을 셸 env로 내보내 compose가 치환한다(`--env-file` 없음) | 내부망만 |

### 0-0. JSON 사건·DB 감사/성능 기록(op-01)

아래 칸의 settings.yaml 자리는 `ops.log.*`(모델 `common.log.*`)와 `search.audit.*`(모델 `mcp.audit.*`)다.

`common.log.level`은 DEBUG/INFO/WARNING/ERROR/CRITICAL(기본 INFO), `common.log.dir`을 비우면 PC는 `logs/<앱>.jsonl`, 서버는 stdout이다. 상대 경로는 `paths.PROJ_ROOT` 기준이다. `common.log.db_enabled: true`로 DB 기록을 켠다(기본 false). DB 접속은 기존 `common.connections.pg`를 사용하며, 먼저 DBA가 `python -m common.store.db.dbtool up --target applog`와 `check --target applog`를 적용한다. PC 시험은 `--schema test_<이름>`으로 분리한다.

`mcp.audit.max_input_bytes`(16384)·`max_output_bytes`(65536)는 감사 원문 저장 상한, `common.log.retention_days`는 기본 90일이다. `python -m common.store.db.dbtool maintain --target applog`를 **매일 예약**한다. 이 명령만 Alembic 작업 안에서 현재+앞으로 2개월 파티션을 준비하고, 월 끝까지 보존 기한을 지난 파티션을 DROP한다(월 중간 데이터는 다음 정리까지 최대 한 달 더 남음). 작은 `pipe_run`은 ended_at/started_at 기준 DELETE한다. 앱의 INSERT 경로에서는 DDL을 하지 않는다.

DB 장애/문장 시간 초과(기본 2초)는 앱 호출을 기다리게 하지 않고 `common.log.fallback_dir`(기본 `output/applog`)에 마스킹된 `{table,row}` JSON Lines로 남는다. 경고는 프로세스당 한 번이며, `logsink.stats()`의 `dropped`·`fallback_errors`를 운영 점검에 포함한다. 파일 재적재는 자동으로 하지 않는다. 큐 상한 10000, 배치 200/1초이며 종료는 `common.log.shutdown_sec`(기본 5초) 한 deadline 안에 DB 대기와 파일 기록을 모두 수행한다. DB에는 남은 예산의 절반까지 기다리고 나머지는 파일 기록에 쓴다. 잠금·파일 쓰기가 막히면 deadline에 종료하고 미완료 행을 `dropped`로 집계하며 stderr에 한 번 경고한다(취소할 수 없는 OS 쓰기는 뒤늦게 끝날 수 있음). 종료 중 결과가 불명확한 DB 커밋과 대체 파일은 중복될 수 있어 request_id/run_id/span_id로 대조한다. 대체 파일/PC 로그는 삭제하지 않으므로 디스크 회수·접근 권한·보관 정책도 운영에서 정한다(C-79). 내부 신호 `APPLOG_CONTEXT`는 settings.child_env가 ID만 전달하며 사용자 설정 env가 아니다.

MCP `--stdio` 모드에서는 콘솔 로그를 stderr로 보낸다(stdout은 JSON-RPC 전용, 명시 파일 로그는 유지). MCP는 호출당 `applog.mcp_call` 한 행(상태 ok/error/busy/timeout/unauthorized)을 남긴다. `X-MCP-Client`는 agent, `X-MCP-User`는 user_id(없으면 tools/call의 `_meta.user`)이며 자기신고 값이므로 인증 권한으로 쓰지 않는다. 유효한 UUID `X-Request-Id`를 보내면 로그와 응답 헤더에 전달되고, 없거나 형식이 다르면 서버가 UUID를 만든다. ASGI 감사용 메타데이터 추출은 최대 1MiB 안에서만 스레드로 파싱하며, 초과 요청의 `_meta.user`는 생략하므로 큰 요청은 `X-MCP-User` 헤더를 쓴다. SDK에 전달하는 원문과 도구 입력 계약은 그대로다. 감사는 도구 응답에서 기다리지 않으며 전용 데몬 스레드 하나(본문 대기 64건, 처리 중 포함 추정 바이트 합계 `mcp.audit.max_queue_bytes` 기본 268435456=256MiB)가 직렬화·마스킹·청크 해시·sink 전송을 맡는다. 건수/바이트 상한 초과는 본문 없이 args/result=NULL, result_keys.audit_body_omitted=queue_full·err=audit_queue_full인 메타 행을 기록하며 call_log.stats().body_omitted로 센다(sink도 포화면 logsink.stats().dropped). 추정은 문자열 4바이트/글자와 노드당 64바이트를 더하며, 바이트 상한 또는 65536노드를 넘으면 즉시 중단하고 같은 본문 생략 경로로 보낸다. 완료/취소된 큐 항목의 추정 바이트는 차감하며 `pending_bytes`로 남은 합계를 본다. 이 값은 실제 RSS·SDK 입력 크기의 상한이 아니다. 동기 마스킹 전 메타 문자열(err/agent/user_id 등)은 최대 2048자로 제한한다. 상한보다 긴 메타 문자열은 비밀값 일부가 남지 않도록 통째로 생략 표식으로 바꾼다. 입력 크기 제한이나 거부는 추가하지 않는다. 종료는 감사 워커→sink 순서로 위 shutdown_sec 한 deadline을 공유하며 미완료 감사는 call_log.stats().dropped다. 접속 IP와 clientInfo는 기록하지 않는다(initialize 행의 args에서도 뺀다). session_id도 요청 헤더가 없으면 null이다. 401은 본문 수신 없이 tool=http 행에 남긴다. DEBUG 수준에서 시간 초과 뒤 남은 스레드의 abandoned·실제 종료 시각을 볼 수 있다.

MCP args/result는 문서 원문을 포함할 수 있다. settings에서 비밀 칸(SecretStr)으로 표시된 실제 값과 기존 라벨 패턴을 공통 `jsonlog.masked(value)`로 가린 뒤 앞부분만 저장하며(4자 이상은 부분 문자열, 1~3자는 앞뒤가 문자·숫자가 아닌 토큰 경계만 일치; 문자·숫자에 붙은 짧은 값은 가려지지 않음), 서버(dev/prd)는 시작 관문에서 값이 있는 비밀 칸이 코드 상수 `MIN_SECRET_LENGTH=8` 미만이면 종료 코드 2로 거부한다(오류에는 칸 경로만, 값·길이 없음). 빈 칸은 대상이 아니며 JSON은 비밀 라벨 키의 문자열 값, URL DSN은 디코딩한 비밀번호 부분을 검사한다. local은 시작을 거부하지 않고 기존 1~3자 토큰 경계 정책과 칸 경로만 한 번 출력하는 경고를 유지한다. JSON 연결 옵션은 비밀 라벨 키의 값만 추가로 대조하며 driver/host와 라벨 없는 리스트는 제외한다. 잘린 TEXT는 JSON 파싱이 안 될 수 있다(`*_truncated` 확인). `result_sha256`와 `*_bytes`는 전체 원본 JSON 기준, result_keys는 자르지 않는다. parse_document의 content_b64는 파일 해시·크기로 치환한다. result_keys는 search가 근거 `chunk_key` 목록(목록 순서 = 순위)·`evidence_status`·`filter`·`scope_docs`, `list_doc_fulltext`가 batch 건수·`next_cursor`·`doc_key` 목록, `get_doc_fulltext`가 batch 건수와 파일별 이름·종류·크기·sha256·건너뛴 이유(본문 없음)다. **`get_doc_fulltext`의 result 본문은 문서 원문 전체**(파일당 상한 `mcp.audit.max_output_bytes`까지)이므로, `applog` DB·표와 대체 파일(`common.log.fallback_dir`)은 원본 문서와 같은 수준으로 접근을 제한해야 한다(C-79). 기존 qa_log.jsonl 기록·설정은 별개로 유지한다. 검증 UI는 `X-MCP-Client: test`·`X-MCP-User: test`를 보낸다.
파이프라인 성능·추적 기록(T2)은 별도 설정 없이 위 스위치(`common.log.db_enabled`)를 따른다. 실행 1건이 `applog.pipe_run` 1행, 문서×단계가 `applog.pipe_event` 행이고 60초마다 `stage='run.progress'`가 남는다(규모: 문서 수 × 엔진·단계 수 — 큐 상한 10000이 넘게 한꺼번에 쓰는 일이 없도록 재사용 판단은 문서마다가 아니라 `extract.plan` 1행으로 요약). 분석은 `python -m pipeline.tools.perf [<run_id>]`(`--runs` 목록, `--compare`로 실행 비교, DB가 꺼져 있으면 `--file output/applog/*.jsonl`). 내부 신호 `APPLOG_CONTEXT`는 `settings.child_env`뿐 아니라 `gated_popen`도 자식에 이어 붙인다(run_id가 있을 때만). 자식 프로세스(`run_all` 조각·`represent`·`build_bundle`·`pgvector_load`)는 각자 sink를 열어 같은 `run_id`로 쓴다.

### 0-1. 읽는 규칙
- **옛 `pipeline.env`는 읽지 않는다.** settings.yaml 없이 `pipeline.env`만 있으면 `trigger.sh`·`run_tool.sh`·`mcp_up.sh`·새벽 배치가 "설정 이관 필요"로 종료 코드 2. 0.1.0 전 이관 기록은 [history/deploy_0_1_0.md](../history/deploy_0_1_0.md) §3.
- **크리덴셜**(비밀번호·키·토큰)과 **접속 정보**(주소·포트·DB 이름)는 전부 이 파일 하나에만 둔다. 각 컨테이너는 common + 자기 앱 절(pipeline·mcp)만 읽는다(`RAG_MODULE`). 엔진·핸드오프 파일도 설정 객체로 읽는다(op-09 2단계 — 옛 영구 다리 `pin_env`가 env로 내주던 28칸은 없앰, 컨테이너 안 프로세스 env에도 안 나옴).
- 아래 표의 이름은 **옛 env 이름**이다. settings.yaml 자리는 `python -m common.config.sample --where <이름>`으로 찾는다(예 `PG_HOST` → `required.pg.host`). 코드·`export --section`·오류 안의 `common.connections.pg.host` 같은 경로는 **모델 경로**다(파일 자리와 다를 수 있음 — `--where`가 둘 다 보여 줌).
- **env로 준 값은 읽지 않는다** — 셸·compose·systemd·`docker exec -e`의 `X=값`은 효과가 없고 시작 때 이름만 경고한다.
- **서버(dev·prd)는 바꿀 값이 있으면 `settings.yaml`을 직접 고친다.** 한 번만 다르게 돌릴 값도 고쳐 돌린 뒤 되돌리고, 고친 뒤 상주 컨테이너는 다시 띄운다(또는 아래 `--set`).
- 오버레이 설정 파일 도구(`python -m common.config.overrides 이름=값 …` — 원본을 `base`로 가리키고 바뀐 항목만 든 임시 yaml)는 **PC 전용**이다. 서버에서는 안내 뒤 종료 2(compose는 그 파일만 컨테이너에 붙여 `base`가 컨테이너 안에 없음). 코드가 컨테이너 안에서 자식 프로세스에 값을 넘기는 오버레이 설정 파일(`settings.put`·`child_env` — 컨테이너 `/tmp`)은 그대로 쓰인다(`refactor.md` C-46).
- 서버(dev·prd)에서 설정 파일을 못 읽거나(권한) 그 이미지 절이 틀리면 컨테이너가 이유(항목 경로·오류 종류만)를 찍고 **시작하지 않는다**(종료 2).
- 호스트 항목만 꺼내 보기(비밀 없음 — 인자는 모델 경로): `bash deploy/host/scripts/settings_env.sh pipeline.host common.host`. 호스트 python에는 PyYAML만 있으면 된다(`deploy/host/scripts/host_env.py` — 칸 목록은 설정 모델에서 만든 `host_keys.tsv`, 설정 모델을 고치면 `PYTHONPATH=. python deploy/release/hostkeys.py`로 다시 만듦 — 사용자 11-02).
- `deploy/host/scripts/run_docs.py`(문서별 flow 러너 — 서버 전용)도 같은 파일을 읽는다(호스트 python에 PyYAML 필요). 필요한 항목이 없으면 항목 경로만 찍고 종료 코드 2 — 목록은 `refactor.md` C-45 ③.
- 라이브러리가 읽는 env(`TZ`·`OMP_NUM_THREADS`·`HF_HUB_OFFLINE`·`TESSDATA_PREFIX`·`PIPELINE_VERSION` 등 — 허용 목록 `common.config.settings.LIB_ENV_NAMES`, 비밀 아님)는 `ops.runtime.lib_env` 사전에 적는다. 컨테이너 entrypoint가 시작 때 env로 낸다(이미지 ENV 값은 덮고 `docker run -e`로 준 값은 안 덮음 — `refactor.md` C-47 ③). 목록 밖 이름은 검증 오류(이름만).

### 0-2. 한 번 실행에만 다른 값 — `--set 이름=값`(서버 포함)
- `python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/x --set PARSE_POST=supsub parse …`처럼 진입 모듈(`pipeline.cli`·`pipeline.extract.source`·`pipeline.stackcfg`·`pipeline.transform.structure.build_bundle`·`pipeline.load.pgvector_load`·`pipeline.load.publish_parse_result`)에 여러 번 준다(같은 이름은 뒤 값).
- 그 프로세스가 오버레이 설정 파일(설정 파일을 `base`로 — 비밀 복사 없음)을 만들어 자기와 자식에 넘긴다(`common.config.setarg`).
- 모르는 이름·호스트 항목·**비밀 항목**(명령 줄은 ps·로그에 남음)은 모든 환경에서 종료 2. 값 형식 오류는 서버 종료 2·local 경고(이름만). 서버(dev·prd)에서 설정 파일(`SETTINGS_FILE`)이 없으면 종료 2.
- `run_docs.py`가 문서별 결과 폴더·동시 수를 이렇게 넘긴다.

### 0-3. 새 서버 설정 절차
**PC의 settings.yaml을 복사하지 않는다** — PC의 `run_env: local`·`*_allow_external`이 서버에서 외부 모델을 연다. settings.yaml은 git에 올리지 않는다.
1. `cp <저장소 ZIP>/settings.sample.yaml /srv/rag/env/settings.yaml`
2. 권한을 맞춘다(위 표 — 주인 10001·640).
3. `required` 절(`[서버만]` 카테고리 포함)과 아래 1절만 채운다(그 밖 항목은 코드 기본값이 적혀 있음 — 바꿀 것만 고침, 위 "옛 서버 값" 표 포함).
4. `bash deploy/host/scripts/run_tool.sh check_env`로 확인한다(코드 폴더 루트에서 — 컨테이너 안에서 돈다).

## 1. 꼭 채울 것 (영역별)

### 실행 환경 (필수 — D-028)
| 이름 | 뜻 | 기본 | 필수? |
|---|---|---|---|
| `RUN_ENV` | 실행 환경 — 서버 `dev`·`prd`(내부망 전용 · 가짜 LLM 거부), PC `local` | 없음 | **필수** — 없으면 compose가 멈추고(`${RUN_ENV:?…}`) 앱 명령(`pipeline.cli`·`mcp_server.main`·트리거·이미지 entrypoint 앱 명령)이 종료 코드 2로 거부. `selftest`·`check`·`help`·`tool check_env`는 없어도 돎(`tool ping_models`는 외부 모델을 부르므로 필요). env 대신 `SETTINGS_FILE`이 가리키는 settings.yaml의 `required.env.run_env`로 줘도 됨(파이썬·entrypoint 같은 규칙) |

**settings.yaml 하나** — 구조·설명은 루트 `settings.sample.yaml`. 0.1.0 settings.yaml(옛 배치)은 `python -m common.config.migrate <옛 settings.yaml> --out <새 파일>`로 바꾼다(release-and-patch.md §5-7·§8). env 파일 옮기기·`--compare`는 0.1.0 전 서버용이라 지운다(사용자 11-02 — 정리 3). 서버 compose·셸·systemd는 이 파일만 읽는다(`refactor.md` C-34·C-45).

**작성 규칙**
- 비운 항목·빈 글자 `''`은 코드 기본값이다. 예외: 기본값이 없는 글자 항목과 `--where`가 `[빈 글자 유지]`로 보여 주는 항목만 `''`이 빈 글자(옛 env `X=`과 같게).
- 글자 항목에 쓴 `yes`·`no`·`1`·`0`은 쓴 글자 그대로다(옛 env 줄과 같음).
- 켜기 항목은 YAML `true`·`false`. `--where`가 `[켬: …]`·`[끔: …]`로 보여 주는 항목(코드가 설정 객체로 읽는 항목)은 `0`·`1`도 되고 `yes`·`on`·`off` 등은 검증 오류(항목 이름만 찍음). env로 줄 때는 키마다 옛 판정 꼴 그대로(예 `NO_PAID_CALLS`는 `1`만 켬, `MCP_WARMUP`은 `0`만 끔).
- `pipe_procs`·`pipe_threads`는 숫자(소수 가능) 또는 `auto`(= 비움, 계산).
- `ops.nightly.modules`는 공백 목록(`parse publish structure load`) 또는 YAML 목록.
- 검증 오류 메시지는 항목 경로·오류 종류만 찍는다(값은 안 찍음). 빈 틀의 자리표시 값(`<여기에 기입>`)은 migrate가 비운 항목으로 옮긴다.
- ⚠ `transform.represent.post`(`PARSE_POST`)에 `''`·`[]`를 쓰면 **끔**(env `PARSE_POST=`과 같음). 기본(`all`)을 원하면 항목을 비우지 말고 지운다.
- 다리는 컨테이너마다 common + 자기 앱 절만 env로 내준다(`RAG_MODULE` — pipeline 이미지 = common·pipeline, mcp 이미지 = common·mcp, PC(없음) = 셋, 그 밖 글자 = 아무것도 안 냄). settings.yaml은 서버에 한 파일 그대로 두고, 다른 앱 절은 그 컨테이너에서 읽지도 검증하지도 않는다.

### 사내망 판정
| 이름 | 뜻 | 기본 | 필수? |
|---|---|---|---|
| `INTERNAL_HOST_SUFFIXES`(`common.models.guard.internal_host_suffixes`) | 사내 도메인 접미사 — **상위 도메인**을 적는다(예: 모델 주소가 `llm.corp.example`이면 `corp.example`). 앞에 점을 붙여 끝부분으로 맞추므로 전체 호스트 이름을 그대로 적으면 맞지 않는다 | 비움 | 모델 주소가 점 있는 호스트 이름이고 기본 접미(`.local`·`.internal`·`.corp`·`.lan`)로 끝나지 않을 때 — 사설 대역 여부와 별개(호스트 이름 확인과 IP 확인을 둘 다 통과해야 내부로 본다) |
| `INTERNAL_IP_RANGES`(`common.models.guard.internal_ip_ranges`) | 사내 IP 대역(/24처럼 좁게) | 비움 | 모델 서버 IP가 사설 대역(RFC1918) 밖일 때만 |

### 모델
| 이름 | 뜻 | 필수? |
|---|---|---|
| `LLM_BASE_URL`·`LLM_MODEL`·`LLM_API_KEY` | 내부망 LLM(생각 모델이면 `LLM_EXTRA_BODY`로 생각 끄기 권장) | 수집·개발 서버 ✓ |
| `VLM_BASE_URL`·`VLM_MODEL`·`VLM_API_KEY` | 이미지 문서·그림 판정 | 수집 서버 ✓ |
| `EMBED_BASE_URL`·`EMBED_MODEL`·`EMBED_API_KEY` | 임베딩(차원은 첫 응답에서 자동) — 운영 임베딩·재순위는 **API로만**(이미지에 로컬 추론 패키지 없음) | 수집 서버 ✓ |

모델 주소·이름·키는 이 세 묶음(`LLM_`·`VLM_`·`EMBED_` + `_BASE_URL`·`_MODEL`·`_API_KEY`)으로만 받는다(`common/ai/adk.py`·`llm.py`). Agent Platform 설정(`PLATFORM_CONFIG`·`PLATFORM_STATE_DIR`)은 읽지 않으니 settings.yaml에 적지 않는다(D-013 — 지운 경위는 [env_guide_history.md](../history/env_guide_history.md)).

### 저장소 (PostgreSQL + pgvector, 기존 컨테이너에 접속만)
| 이름 | 기본 | 메모 |
|---|---|---|
| `PG_HOST`·`PG_PORT` | 필수 | 서버 IP 또는 `--network host`+`NETWORK_HOST=1`(op-09 — 자동 탐지 없음) |
| `PG_DB`·`PG_USER`·`PG_PASSWORD` | 필수 | 우리 스키마 권한만 있는 계정 |
| `PG_SCHEMA` | 필수 | 개발 서버 검증대는 `ai_test` 별도 스키마 |

### 근거 MCP(상주)
| 이름 | 기본 | 메모 |
|---|---|---|
| `MCP_SERVER_IMAGE` | — | `mcp-server:<태그>`(옛 `DATA_RETRIEVAL_IMAGE`·`RAG_IMAGE`는 읽지 않음, 남아 있으면 스크립트가 멈춤) |
| `RAG_OUT` | — | 결과 폴더(모든 모듈 공용) |
| `MCP_HOST` | `127.0.0.1` | 사내 IP로 열면 `MCP_TOKEN` 필수, `0.0.0.0`은 거부 |
| `FULLTEXT_SIGN_SECRET`(`search.server.fulltext_secret`) | 비움 | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 파일 손잡이 sfid 서명 키 — 비밀 칸(settings.yaml에만). 비면 두 도구가 `not_configured`. 바꾸면 이미 발급된 sfid가 모두 무효(사용자에게 먼저 알림 — mc-17, refactor.md C-75) |
| `MCP_PORT`·`MCP_TOKEN` | `8765`·비움 | 토큰은 호출부 env에만 · 공백만인 토큰은 없음과 같음 · `MCP_PORT` 형식이 틀리면 시작 실패(값은 안 찍음) |
| `PARSE_SERVICE_TOKEN` | 비움(→ `MCP_TOKEN`) | `parse_document`가 parse 작업 서비스를 부를 때 쓰는 토큰 — data-pipeline-mcp(11-03 — 옛 data-pipeline-parse)의 `PARSE_MCP_TOKEN`과 같은 값. 이것도 `MCP_TOKEN`도 없으면(공백만 포함) `parse_document`가 "parse 서비스 토큰 없음" 오류를 돌려줌(코드 대체 토큰 없음 — `refactor.md` C-44) |
| `PARSE_MCP_MAX_MB`(`ops.runtime.parse_max_mb`) | `100` | `parse_document` 파일 1건 크기 상한(MB) — 검색 MCP와 파싱 서비스가 같은 칸을 읽음(두 컨테이너의 settings.yaml에 같은 값). 옛 `ops.services.parse_mcp.max_mb`(기본 64)는 지움 |
| `MCP_METHODS` | `vector,bm25,id` | 이 셋만 있음 |
| `MCP_ALLOWED_HOSTS` | 비움 | `MCP_HOST`가 루프백이 아닐 때, 리버스 프록시 등 다른 Host로도 부르면 쉼표로 추가 |

### EDW 쿼리 도구(`describe_edw`·`query_edw` — 읽기 전용 SQL, 근거 MCP의 별도 도구 2개)
접속은 `common.connections.rdb`의 **읽기 계정**(`RDB_READ_*`)만 쓴다 — 검색 MCP에는 쓰기 계정을 주지 않는다([ops.md#op-03](../prd/ops.md#op-03)). 이 읽기 계정은 파이프라인의 원천 조회와 함께 쓴다. 서버 설정 절차는 [server-guide.md](server-guide.md) "EDW 쿼리 도구" 참고.

| 이름 | 기본 | 메모 |
|---|---|---|
| `EDW_QUERY` | `1`(켬) | `=0`이면 두 도구 모두 `not_configured`로 강제 꺼짐(기동엔 영향 없음) |
| `RDB_SQLITE` | 비움 | PC 테스트용 SQLite 대역 파일 하나(모든 표 — `valid_env/edw/edw.sqlite`, `python -m validation.e2e.edw_standin`으로 다시 만듦) — 설정돼 있으면 원천 조회·퍼블리시·`query_edw` 모두 이게 먼저 |
| `RDB_HOST`·`RDB_PORT`·`RDB_DATABASE`·`RDB_READ_USER`·`RDB_READ_PASSWORD` | 비움·`1433`·비움·비움·비움 | 서버 EDW 접속(pymssql) — `common.connections.rdb` |
| `EDW_QUERY_TABLES` | 비움(PC 대역은 그 안의 표 9개) | 읽기 허용 `schema.table` 쉼표 목록 — 서버는 실제 EDW 표 이름으로 반드시 바꿔 적음 |
| `EDW_QUERY_MAX_ROWS` | `1000` | `query_edw(max_rows=)` 호출값의 상한 |
| `EDW_QUERY_TIMEOUT_SEC` | `20` | 넘으면 `{"ok": false, "error": "timeout: ..."}`  |
| `EDW_QUERY_MAX_BYTES` | `2000000`(2MB) | 응답 JSON 크기 상한 — 넘으면 뒤에서부터 행을 줄이고 `truncated: true` |

### 이미지 태그 (compose 치환용)
| 이름 | 메모 |
|---|---|
| `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE` | `data-pipeline:<태그>`·`mcp-server:<태그>`(D-020 — 이미지 2개). 옛 이름 `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`·`RAG_PARSE_IMAGE`·`RAG_STRUCTURE_IMAGE`·`RAG_RETRIEVAL_IMAGE`·`RAG_IMAGE`는 별칭으로 읽지 않는다 — 새 이름 없이 옛 이름만 있으면 `trigger.sh`·`run_tool.sh`·`mcp_up.sh`가 "새 이미지 버전 필요"로 멈춘다(종료 코드 2) |
| `DOC_SRC` | 원본 문서 폴더(호스트 경로, `compose.pipeline.yml`이 `/data/docs:ro`로 연결) |

### 원천·경로 묶음 (도구가 기본으로 읽음 — 명령에 경로를 따로 안 줘도 됨)
코드 주석의 "env-guide 1-2"가 이 절이다.

| 이름 | 무엇 | 형식 |
|---|---|---|
| `DOC_DIR` | 원본 문서 폴더 | 하드코딩 기본값 없음 — 비우면 실행 때 안내 후 종료(legacy 별칭 `DOC_SRC`도 받음) |
| `PARSE_SOURCE` | 이번에 읽을 원천 | 폴더 · `rdb:csv:<경로>`(사용자 11-01 — `s3://`·`rdb:*`·`rdb:<이름>`·`rdb:<표>` 지움) |
| `SOURCES_FILE` | (11-01 지움 — 원천 목록 `sources.json`과 함께. 칸은 남아 있어도 읽지 않음) | 엔진 구성 파일은 `PIPELINE_STACK_FILE`(`ops.paths.stack_file`) |
| `SERVER_ENV_DIR` | 서버 설정 폴더(코드 폴더 밖) | 서버 기본 배치 `/srv/rag/env` — `trigger.sh`·`run_tool.sh`·`mcp_up.sh`·systemd가 이 값으로 넘김. 컨테이너는 이 폴더를 마운트하지 않는다. 운영 계정 `~/.bashrc` 등에 영구로 export([server-guide.md](server-guide.md) §1-2) |
| `GOLD_DIR` | 사람 정답 폴더 | `<원본 파일 이름>.txt`(원문에 있는 글자만). ⚠ 서버는 호스트 항목 `ops.pipeline_host.gold_dir`에만 적는다 — `run_tool.sh`가 컨테이너 `/data/gold`로 붙이고, 앱은 앱 항목 `ops.pipeline_paths.gold_dir`가 비었으면 그 자리를 읽음(앱 항목에 호스트 경로를 적으면 컨테이너 안에 없는 자리를 봄. migrate도 서버 env 파일의 `GOLD_DIR`를 호스트 항목에만 옮김) |
| ~~`CLIENT_ROSTER`~~ | (11-03 지움 — pl-38) 고객 명부는 PG 마스터 표 `<PG_SCHEMA>_master.client_roster` | `resources/vocab/glossary/client_roster.csv`(또는 서버 폴더)를 고친 뒤 `migrate master load [--dir <폴더>]` — 설정 파일에 남아 있으면 경고만 |
| ~~`GLOSSARY_DIR`~~ | (11-03 지움 — pl-38) 용어집·ID 모양은 PG 마스터 표(`domain_terms`·`id_patterns` 등) | `migrate master load [--dir <폴더>]` — 설정 파일에 남아 있으면 경고만 |
| `PG_FILTER_EXACT_MAX` | 고객 필터 검색 | 적재(`structure`·`load`) 한 번이면 `chunk.clients`(고객 라벨 배열)·GIN 색인·옛 행 채우기가 자동 — **그 뒤 검색 MCP를 재시작**(빠른 경로 사용 여부를 프로세스마다 한 번만 확인) · 고객으로 좁힌 청크가 `PG_FILTER_EXACT_MAX`(기본 20000) 이하면 정확 검색(HNSW 거르기로 결과가 빠지지 않게). `OV_TAGS`는 OpenViking과 함께 지워져 읽지 않는다(§5 10-29 줄) |
| `REPORT_DIGEST_DIR` | 날짜·버전 요약 폴더 | 예 `/srv/rag/reports/parse_digest` |
| 변경 뒤 확인 | — | `python -m common.check.checker env`(경로 존재까지 점검, 값은 안 찍힘 — 서버는 `run_tool.sh check_env`) |

### 원천 Object Storage·EDW (선택, 승인 뒤)
| 이름 | 메모 |
|---|---|
| `OS_ENDPOINT`·`OS_ACCESS_KEY`·`OS_SECRET_KEY`·`OS_VERIFY_TLS` | 읽기 전용 — 사내 CA면 `OS_VERIFY_TLS=<CA 파일>` |
| `RDB_HOST`·`RDB_PORT`·`RDB_DATABASE`·`RDB_CONNECT_KWARGS` | EDW 접속 하나(`common.connections.rdb` — [ops.md#op-03](../prd/ops.md#op-03)). 원천 목록·FileStorageMap·ParsingMeta 조회·`query_edw`는 같은 서버·DB(어느 표·열은 `SOURCES_FILE`) |
| `RDB_READ_USER`·`RDB_READ_PASSWORD` | 읽기 계정 — 원천 조회·호스트 러너 조회·검색 MCP(근거 경로·`query_edw`) |
| `RDB_WRITE_USER`·`RDB_WRITE_PASSWORD` | 쓰기 계정 — ParsingMeta 퍼블리시(INSERT·UPDATE)만, 파이프라인 이미지에만 |
| `EDW_CHAIN_FILE` (`ops.pipeline_paths.edw_chain`) | EDW 조인 사슬 설정 파일(적재만 읽음 — pl-29). 비우면 코드의 기본 파일 `resources/config/edw_chain.yaml`. 서버에서 표·칸 이름을 고쳐 쓰려면 사본을 settings.yaml 옆 `$SERVER_ENV_DIR/edw_chain.yaml`(10001, 640)에 두고 값 `/etc/rag/env/edw_chain.yaml`을 적는다(그 폴더는 `data-pipeline`에만 읽기 전용으로 붙음). 없거나 틀린 파일이면 적재가 시작할 때 멈춘다(기본 파일로 돌아가지 않음). 쓰는 법·점검: [release-and-patch.md §8-6](release-and-patch.md#8-6-edw-조인-사슬-파일-고쳐-쓰기서버--pl-29) |
| `PM_PATH_MAP` | 결과 키 앞부분 바꾸기 `이전 앞부분=새 앞부분`(쉼표 목록, 짝 없으면 `source_system/원본 폴더`) — 문서 폴더 = `<PM_PREFIX>/<새 앞부분>/<나머지 폴더>/<원본파일명>/`(EDW rep_key) · 대표 결과 `<파일명>_<YYYY-MM-DD_HHMMSS>.md`·엔진별 원본 `engine/` · 예 `SFDC=Parsing-Result/SFDC`면 `.../SFDC/<UUID>/a.pdf` → `.../Parsing-Result/SFDC/<UUID>/a.pdf/` |
| `PM_BUCKET`·`PM_PREFIX` | 결과 퍼블리시(쓰기, 마지막 단계) — EDW는 위 쓰기 계정. 폴더 저장소로 먼저 테스트: `PM_BUCKET=file://…` · ⚠ **첫 퍼블리시 전 EDW 표를 DBA가 1회 생성**: [`docs/operations/parsing_meta_mssql.sql`](parsing_meta_mssql.sql)(저장소 문서 자리 — 코드 폴더·오버레이 패치 번들에는 없음. DBA가 아직 한 번도 실행 안 함 — 이 최신 버전을 그대로 1회. 코드는 표를 만들지 않으며 없으면 첫 INSERT에서 실패) · 필수 열은 `doc_key`(원본 sha256) 하나뿐, `source_system`·`source_key`·`parse_date`는 비어도 됨(비면 각각 'unknown'·NULL·처리 시각) · `parse_date`는 글자 `YYYY-MM-DD_HHMMSS`, `rep_key`는 문서 폴더(끝 `/`) · `engines_used`(JSON 배열)·`engines_summary`(한 줄) — 이 문서에 쓰인 엔진 전부(VLM·OCR 포함, `pipeline/load/parsing_meta.py`의 `engines_used()`) |

(상주 트리거 서버의 `TRIGGER_*`·`CHAIN_STRUCTURE_URL`은 11-01에 지움 — PRD pl-10. 옛 서버 settings.yaml의 `ops.services.trigger` 절은 남아 있으면 경고만.)

### 새벽 배치 (systemd `data-pipeline-nightly`)
코드 주석의 "env-guide 1-3"이 이 절이다(settings.yaml `ops.nightly.*` — 아래 셋이 모두 있어야 돎, 하나라도 비면 없음 — pl-32 10-30·사용자 11-02).

| 이름 | 켜면 | 기본 |
|---|---|---|
| `NIGHTLY_TIME`(`ops.nightly.time`) | 그 시각(HH:MM, 서버 시간)에 새벽 배치(`run_docs.py --start-offset 0 --skip-done`) 시작 — 타이머는 5분마다 깨우고 `trigger.sh scheduled`가 시각을 봄 | 비움(새벽 배치 없음) |
| `NIGHTLY_MAX_DOCS`(`ops.nightly.max_docs`) | 한 번에 처리할 새 문서 수 상한(끝난 문서를 뺀 뒤 앞에서 — `--max-docs`) | 비움(새벽 배치 없음) |
| `NIGHTLY_DEADLINE`(`ops.nightly.deadline`) | 마감 시각(HH:MM — 시작보다 이르면 다음 날) — 지나면 새 문서를 받기 시작하지 않음, 받은 문서는 끝까지(`--deadline`) | 비움(새벽 배치 없음) |

(11-01 지움 — 남아 있으면 경고만: `NIGHTLY_MODULES`·`NIGHTLY_PUBLISH`·`NIGHTLY_MAX_NEW`(`ops.nightly.*`)·`NIGHT_DEADLINE`·`PARSE_DEADLINE`(`ops.nightly_run.*`)·`ALLOW_COMMON_MISMATCH` — night 모듈 배치·structure·load 모듈과 함께.)

### 회사 맞춤 문구 (선택 — [server-guide.md](server-guide.md) §5)
| 이름 | 메모 |
|---|---|
| `MCP_INSTRUCTIONS` | MCP 안내 문구 |

## 2. 자원·병렬 (보통 안 건드림 — 버거울 때만 낮춤)

`PIPE_PROCS`(기본 `auto` — CPU·메모리로 자동)·`PIPE_WORKERS`·`VLM_CONCURRENCY`·`OCR_DPI`·`OCR_MAX_PAGES`·`MAX_FILE_MB`·`MEM_MAX_PCT`(90)·`CPU_MAX_LOAD`(0.9)·`EMBED_BATCH`·`EMBED_TIMEOUT`·`VLM_TIMEOUT` — 전체 설명·기본값은 루트 `settings.sample.yaml`(항목을 비워 두면 코드 기본값과 같음). 자동 계산 내부 계수(`MEM_*`·`PIPE_MAX_PROCS`·`PIPE_PROC_GB`·`PIPE_RESERVE_*`·`PIPE_THREADS`·`CPU_MAX_LOAD`)와 호출 제한 시간·병렬 세부값은 `tuning` 절에 있다(코드 상수 후보 — op-08).

## 3. 새 기능 스위치 — 기본 켬, 끌 때만 `=0`

- 새 기능은 기본 켬이다. 되돌리기 전용 스위치는 op-08(10-30)에 지웠다 — 그 동작은 늘 켬. 끌 수 있는 것: `MCP_QUERY_LOG` 등 운영 선택. `REGISTRY_ETAG_MD5`는 SSE-KMS·SSE-C 암호화 버킷처럼 ETag가 MD5가 아닐 수 있는 원천에서 끈다(§5 10-08 AD17① 줄).
- **전체 목록은 `settings.sample.yaml`**(생성 `python -m common.config.sample` — 모든 항목을 코드 기본값과 함께 절·세부 카테고리별로, 줄 끝 주석에 설명·기본값·넣을 수 있는 값·`[파라미터]`·`[비밀]`). 옛 env 이름·켜기 판정 꼴은 `--where <이름>`. 서버에서 바꿀 옵션은 settings.yaml의 그 항목 값을 고친다. 코드 기본값과 다르게 채우던 서버 값은 맨 위 "옛 서버 값" 표(C-39).
- 읽는 순서: 테스트 값 > 오버레이 설정 파일 `overrides` > settings.yaml > 코드 기본값(env의 옛 이름은 읽지 않음 — 이름만 경고).

## 4. 확인

```bash
python -m common.check.checker env    # 빠진 필수 값·사내망 판정·경로 존재(값은 안 찍음)
python -m common.check.checker ping   # LLM·VLM·EMBED 실호출(OK/FAIL·지연·응답 모델) — 실패 있으면 종료 코드 1
```
- 덮어쓰기 뒤 설정 파일이 그대로인지: `ls -l /srv/rag/env/settings.yaml`(수정 시각이 덮어쓰기 전인지 · 주인 10001·권한 640 — C-09).

## 5. 이번 판에서 바뀐 env (판마다 위에 한 줄씩 추가 — `deploy/release/make_patch.sh`가 이 표의 새 줄을 PATCH_NOTES에 옮김)

| 판 | 바뀐 것 | 서버 할 일 |
|---|---|---|
| EDW 사슬 파일 칸(사용자 11-03 — pl-29) | 새 칸 `ops.pipeline_paths.edw_chain`(`EDW_CHAIN_FILE`) — 비우면 지금과 같음(코드의 기본 파일) · 파일만 점검하는 명령 `python -m pipeline.load.edw_meta --check [--file F]` | 서버에서 사슬을 고칠 때만 — release-and-patch §8-6 |
| MCP 도구 상한(사용자 11-03 — mc-06·mc-08, 등급 A) | ① `query_edw` 행 상한 기본 2000 → 1000(`search.edw_query.max_rows`·도구 기본값 `max_rows` 함께) ② `parse_document` 파일 크기 상한 칸을 `ops.services.parse_mcp.max_mb`(기본 64) → `ops.runtime.parse_max_mb`(기본 100, 검색 MCP와 파싱 서비스가 같이 읽음)로 옮김 — 옛 칸은 남아 있으면 경고만 | 서버 settings.yaml에 `ops.services.parse_mcp.max_mb`가 있으면 지우고, 100이 아닌 값을 쓰려면 `ops.runtime.parse_max_mb`에 적음 · `search.edw_query.max_rows`를 적어 두었으면 그 값이 이김 · 리버스 프록시 본문 상한(refactor.md C-85) |
| struct 스키마 코드에서 모두 없앰 — 엔진 구성·원천 목록은 파일만(사용자 11-01 — pl-08·D-031) | ① Alembic struct 갈래(`0001_struct`·`0002_struct`·`0003_struct`)·시드 `resources/sql/` 지움 — `migrate --target`은 `search`·`all`만 ② 서버도 `resources/config/pipeline_stack.json`·`resources/mappings/sources.json`을 읽음(`ops.paths.stack_file`·`sources_file`로 바꿀 수 있음 — 못 읽거나 모양이 틀리면 종료 2) ③ 명령 `set-stack`·`set-sources` 없앰(`show-stack`·`show-sources`는 파일을 보여 줌) ④ 내부 칸 `pipeline.paths.stack_version`(`STACK_VERSION`)·`represent`·`build_bundle`의 `--stack-version` 지움(`Section.REMOVED` — 남아 있어도 경고만) — `run_docs.py`는 시작 때 `show-stack`으로 확인만 ⑤ 파싱·검색 MCP 컨테이너는 PG 없이 시작(종료 4 "판 표 없음" 없음) | 서버에 남은 `struct` 스키마는 그대로 두거나 DB 담당자가 지움(코드는 읽지 않음) · 엔진 구성·원천 목록을 바꿀 때는 코드 폴더의 파일을 고쳐 오버레이 패치 · settings.yaml에 `stack_version`을 적었으면 지움 |
| 정형 저장소·struct 표 10개 지움(사용자 10-31 — pl-08, 11-01에 struct 스키마 전체 없앰으로 바뀜 — 위 줄) | ① `pipeline/load/structured.py`(계약 연결 `load`·`link`)·`common/store/structdb.py`(SQLite 대체 포함) 지움 ② struct 표 10개(`contract_master`·`client_master`·`prod_master`·`doc_contract_link`·`doc_location`·`doc_registry`·`doc_registry_seen`·`doc_hidden`·`doc_table`·`doc_cell`)를 쓰는 코드 지움 ③ 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `common.store.struct_backend`(`STRUCT_BACKEND`)·`common.store.struct_db`(`STRUCT_DB`) | settings.yaml에서 두 칸을 지움(안 지워도 경고만) · struct 마이그레이션은 없음(위 줄) |
| 문서 대장·숨김 지움(사용자 10-31 — pl-12 C10) | ① 문서 대장(`doc_registry`)·숨김(`doc_hidden`)·`registry_cli`(hide·unhide) 지움 — 검색은 숨김 필터 없음, publish는 EDW에 INSERT만(status UPDATE 없음) ② 파싱 `--max-new`·`--source` 고르기 = FileStorageMap ∖ ParsingMeta(ok·partial 행이 있는 원본 키는 안 고름) — 파싱 입구가 EDW ParsingMeta를 읽기 계정으로 한 번 읽음, 못 읽으면 서버는 종료 4 ③ 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `common.store.doc_registry`(`DOC_REGISTRY`)·`common.store.registry_etag_md5`(`REGISTRY_ETAG_MD5`) | settings.yaml에서 두 칸을 지움(안 지워도 경고만) · 파싱 컨테이너에 EDW 읽기 계정(`common.connections.rdb` 읽기)이 있어야 함 · PG 표는 다음 마이그레이션(0003)이 지움 |
| 0.2.0 하드코딩 0 1단계(사용자 10-31 — op-09) | ① PG 자동 탐지 지움(`docker ps`·포트 5432·15432 탐지, 코드 기본값 `127.0.0.1`·`5432`·`rag`·`rag`·`ai`) — `required.pg` 여섯 칸(또는 `conn_file`)이 필수, 비면 채울 자리를 적고 멈춤 ② `required.deploy.mcp_store`(`pg`·`local`) 필수(11-01 mc-01에 칸 없앰 — 검색은 PG 하나, 남아 있으면 경고만) — 비면 검색 MCP 시작 거부, 로컬 묶음으로 조용히 빠지지 않음 · 파이프라인·`ask` 명령은 `--local`이 아니면 PG 필수 ③ 새 칸 `dev.eval.rerank_model`(`RERANK_MODEL`, 기본 `BAAI/bge-reranker-v2-m3`) ④ 이미지 entrypoint는 `DOC_DIR`·`DOC_DIR_PREPARED` 기본값을 셸에 두지 않음(이미지 기본값은 `common/config/settings.py` `IMAGE_PATHS` 한 곳) ⑤ soffice는 설정 `soffice_bin`(`SOFFICE_BIN`) → PATH만 찾음 — 흔한 설치 경로(Program Files·`/usr/lib/libreoffice`·`/opt/libreoffice*`) 추측을 지움(p1 지문 바뀜) ⑥ 새 칸 `common.connections.pg.standin_schema`(`PG_STANDIN_SCHEMA`, 기본 `ai` — PC 로컬 대체 DB만) | settings.yaml `required.pg` 여섯 칸과 `required.deploy.mcp_store`를 채움(비어 있으면 시작 거부) · **PATH에 soffice가 없는 Windows PC는 `soffice_bin`을 채움**(예: `C:\Program Files\LibreOffice\program\soffice.exe` — 안 채우면 pptx 슬라이드 렌더를 건너뜀) |
| 0.2.0 하드코딩 0 2단계(사용자 10-31 — op-09, 검토 등급 A) | ① 영구 다리(`pin_env` — 엔진·인계 칸 28개를 import 때 env로 내주던 것) 지움: 엔진 파일(`pipeline/extract/engines/*`)·인계 파일(`common/core/{contract,terms,text}.py`)도 설정 객체(`cfg()`)로 읽음 ② 그 이름(`VLM_*`·`OCR_*`·`GLOSSARY_DIR`·`CLIENT_ROSTER`·`SOURCE_*` 등)을 env로 주면 효과 없음(시작 때 이름만 경고) ③ 남은 env 줄은 라이브러리 `OMP_NUM_THREADS` 하나(rapidocr) ④ 핸드오프 FINGERPRINT·엔진 지문·레이어 code_fp 모두 바뀜(서버 전 문서 다시 처리 — 0.2.0에 함께) | 컨테이너에 `-e VLM_BASE_URL=…`·`OCR_DPI=…`처럼 주던 값은 settings.yaml 칸으로 옮김(`python -m common.config.sample --where <이름>`) |
| 0.2.0 설정 배치 재편(사용자 10-30 — op-08 ②) | ① settings.yaml 칸 자리가 바뀜: 맨 위 `required`(실행 환경·PG·임베딩 [PC·서버] / EDW·Object Storage·LLM·VLM·원천·게시·토큰·서버 배포 [서버만]) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(코드 상수 후보 58칸). 옛 배치(최상위 `common`·`pipeline`·`mcp`)는 시작 거부 ② 읽는 곳이 없어진 6칸 지움(`Section.REMOVED` — 경고만): `pipeline.extract.cache.parse_tmp_max_gb`(`PARSE_TMP_MAX_GB`)·`parse_keep_max_gb`(`PARSE_KEEP_MAX_GB`)·`pipeline.extract.disk_free_warn_gb`(`DISK_FREE_WARN_GB`)·`engine_cache_warn_gb`(`ENGINE_CACHE_WARN_GB`)·`pipeline.transform.represent.shadow_max`(`PARSE_SHADOW_MAX`)·`mcp.search.agg.llm_min`(`SEARCH_AGG_LLM_MIN`) ③ sample 주석은 한 줄(설명·기본값·값) — 옛 env 이름·판정 꼴은 `python -m common.config.sample --where` | 코드 폴더에서 `python -m common.config.migrate /srv/rag/env/settings.yaml --out /srv/rag/env/settings.new.yaml` → 보고(옮긴 칸 수·삭제됨·모름 — 이름만) 확인 → 옛 파일을 보관하고 새 파일로 바꿈(주인 10001·권한 640 다시 맞춤) · 호스트 `run_docs.py`·`settings_env.sh`(`export --section`은 모델 경로 그대로)도 새 배치를 읽음 |
| 0.1.0 ocr_vlm 지움(사용자 10-30 — pl-31) | ① 엔진 `ocr_vlm`(OCR 전용 소형 VLM — 스택에 없어 쓰이지 않던 것) 지움: 엔진 26개 · `qwen_vlm` 엔진 핑거프린트 바뀜(이미지·스캔 문서 재파싱 — 0.1.0 재처리에 포함) · 레이어 code_fp p0·p1·r·s도 바뀜(전후 값 = transform-cleanup.md#pl-31) ② 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `common.models.ocrvlm.*`(`OCRVLM_BASE_URL`·`OCRVLM_MODEL`·`OCRVLM_API_KEY`·`OCRVLM_ALLOW_EXTERNAL`·`OCRVLM_EST_USD`)·`pipeline.transform.figures.ocrvlm_prompt`(`OCRVLM_PROMPT`) ③ `ping_models`는 LLM·VLM·EMBED만 | 서버 settings.yaml에서 위 칸을 지움(남아 있으면 경고만) · 옛 env 이름(`OCRVLM_*`)은 읽지 않음 · 덮기 파일 `overrides`·`--set`에 옛 이름을 쓰면 모르는 이름으로 거부 |
| 0.1.0 엔진 8개 지움(사용자 10-30 — pl-31, 등급 A) | 설치·사용하지 않던 엔진 `docling`·`docling_ocr`·`docling_vlm`·`unstructured`·`unstructured_auto`·`unstructured_ocr`·`rapidocr`(1.x)·`kreuzberg_ocr` 지움(엔진 18개) · `kreuzberg`·`rapidocr_ko` 엔진 핑거프린트 바뀜(그 엔진 결과 재파싱 — 0.1.0 재처리 한 번에 포함) · `check_env`의 docling·unstructured·marker 모델 점검 줄 없음 | settings.yaml·스택 판에 지운 엔진 이름이 있으면 지움(판 표 `set-stack`(11-01에 없앰 — 지금은 파일 읽을 때)이 없는 엔진을 거부) |
| 0.1.0 새벽 배치 시각·재시도 상한(사용자 10-30 — pl-32) | ① `pipeline.host.nightly.enabled`(`NIGHTLY_ENABLED`) 지움 → `pipeline.host.nightly.time`(`NIGHTLY_TIME`, HH:MM — 비우면 새벽 배치 없음) 하나로 · 타이머는 5분마다 깨우고 `trigger.sh scheduled`가 시각을 봄(옛 고정 01:00) ② `common.store.registry_retry_max`(`REGISTRY_RETRY_MAX`) 지움 — 실패 문서는 횟수 상한 없이 다음 실행에서 늘 다시 · `registry report`·`diff`의 "재시도 중단" 줄 없음 | 서버 settings.yaml에서 `nightly.enabled`·`registry_retry_max`를 지움(남아 있으면 경고만) · 새 `data-pipeline-nightly.timer`(5분 주기)·`.service`(`trigger.sh scheduled`) **둘 다** /etc/systemd/system에 다시 복사하고 `systemctl daemon-reload`(오버레이 패치는 unit 파일을 안 바꿈 — 하나만 바꾸면 새벽 배치가 조용히 안 돎) · 켤 때 `nightly.time`에 시각을 적음(꼴이 틀리면 설정 읽기에서 거부) · 타이머는 새벽 배치를 쓸 때만 enable(5분마다 설정을 읽음) |
| 0.1.0 엔진 구성 사본 파일 없앰(사용자 10-30 — pl-32) | ① 결과 폴더 `_stack/stack-v*.json` 사본과 내부 칸 `pipeline.paths.stack_snapshot`(`STACK_SNAPSHOT`) 지움 → 진입점이 활성 판 번호를 `STACK_VERSION`(내부 칸)으로 자식에 넘기고 자식은 판 표에서 그 판을 읽음 ② 호스트 `run_docs.py`는 시작 때 `python -m pipeline.stackcfg --version`으로 판 번호를 한 번 받아 그 실행의 모든 문서에 씀(옛 `stackcfg --path <문서 폴더>` 없음) ③ 따로 도구를 돌릴 때는 `--set STACK_VERSION=$(python -m pipeline.stackcfg --version)` | 서버 결과 폴더에 남은 `_stack/` 폴더는 지워도 됨(읽는 코드 없음) · settings.yaml에 `stack_snapshot`을 적었으면 지움(남아 있으면 경고만) |
| 0.1.0 지문 배치(사용자 10-30 — pl-21·pl-30) | ① 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `KOREAN_FONT`·`EVAL_SETS_DIR`·`EXP_STORE`·`LLM_EST_IN_TOKENS`·`LLM_EST_OUT_TOKENS`·`MIN_GOLD_COVERAGE`·`EXP_MAX_WORKERS`·`EXP_PROC_GB_*`·`EXP_RESERVE_GB`·`LLM_MAX_CONCURRENCY`·`WIKI_DOMAIN_PHRASE`·`DIAGRAM_RASTER_VLM` ② `run_docs.py`가 `FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`를 더는 안 넘김(읽는 코드 없었음) | 서버 settings.yaml·env 파일에서 위 이름을 지움(경고 끔) |
| 10-30 요건 없는 코드 지움(사용자 10-30 — e2-18) | ① MCP에 노출하지 않던 내부 조회 지움: 문서 단건·그림·근거 이미지·용어·개념·문서 목록(`internal_docs.py` — MCP 도구 4개의 이름·입출력은 그대로) ② 칸 지움: `mcp.output.evid_local_roots`(`MCP_EVID_LOCAL_ROOTS`)·`evid_max_concurrency`·`evid_max_mb`·`evid_timeout_sec`·`images`(`MCP_IMAGES`)·`max_image_px`(`MCP_MAX_IMAGE_PX`), 절 `pipeline.connections.graphiti`(`GRAPHITI_NEO4J_*`) — `Section.REMOVED`라 남아 있어도 경고만 ③ 개념 위키(`structure/wiki.py`)·외부 KG 어댑터(`eval/kg_external.py`)·채점기 `chart_values_score.py` 지움 | 서버 settings.yaml에서 위 칸을 지움(경고 끔) |
| 10-30 적재는 안 지움(사용자 10-29 — pl-13) | ① `pgvector_load load --prune` 없앰 — 적재는 더하고 고치기만, 이번 묶음에 없는 문서(원천에서 지운 문서·이번에 건너뛴 문서)를 지우지 않음(전에는 `cli load`·`run-stack --pg`·색인 빌드 `--pg`가 늘 `--prune`을 붙여 바뀌지 않은 문서까지 지웠음 — C-60) ② 칸 지움: `pipeline.load.prune_force`(`PRUNE_FORCE`)·`prune_min_ratio`(`PRUNE_MIN_RATIO`) — `Section.REMOVED`라 남아 있어도 경고만 ③ 색인 빌드(`pipeline.load.index --pg`)는 `load --replace`로 적재(다시 빌드 때 같은 문서도 새 묶음으로 고침) ④ `pipeline.cli load·run-stack`의 `--no-prune`은 받기만 하고 아무것도 안 함(옛 호출·트리거 허용 목록 호환) | 서버 settings.yaml에서 `prune_force`·`prune_min_ratio`를 지움(경고 끔) · 지운 문서를 검색에서 빼야 하면 숨김(`registry_cli hide`)이나 사람이 직접 · ⚠️ 같은 내용의 `file_path`가 바뀌면(`EDW_PATH_PREFIX`·`--path-prefix` 변경, 원본 이동·이름 변경) 옛 행이 남아 검색에 겹쳐 나옴 — 사람이 지움 |
| RUN_ENV 셋으로(10-29, 사용자 — op-02) | ① `RUN_ENV`는 `local`·`dev`·`prd`만 — `stage`를 주면 모르는 값으로 시작 거부(옛 `stage`도 동작은 `prd`와 같았음) ② 서버(`dev`·`prd`)에서 `common.dev.llm_fake`(env 이름 `LLM_FAKE`)가 켜져 있으면 앱 시작 관문이 종료 2, 관문을 안 거치는 모듈(`docker exec … python -m …`)은 호출 때 거부(`guard.fake_llm`) — 가짜 LLM 응답은 `local` 전용 ③ 외부 모델은 지금처럼 `local`만 ④ code_fp 바뀜(settings.py — 이번 판 재처리에 포함) | 서버 settings.yaml·env에 `run_env: stage`(`RUN_ENV=stage`)가 있으면 **반입 전에 `prd`로 바꿈** · `llm_fake`가 켜져 있지 않은지 확인 |
| 10-29 parse phase 없앰(사용자 결정 — `feature/r2-phase`, PRD pl-22) | ① **칸 지움**: `pipeline.extract.phases`(`PARSE_PHASES`)·`phase_sec`(`PARSE_PHASE_SEC`) — `Section.REMOVED`라 남아 있어도 경고만 ② **새 칸**: `pipeline.extract.text_page_sec`(`PARSE_TEXT_PAGE_SEC`, 기본 10 — 글자 엔진 쪽당 초) · `vlm_page_sec`(`PARSE_VLM_PAGE_SEC`, 기본 120 — VLM 엔진 쪽당 초) · `ocr_engine`(`PARSE_OCR_ENGINE`, 기본 끔 — rapidocr·rapidocr_ko를 엔진으로 돌릴지, parse MCP 서비스도 이 칸을 따름 — `pipeline.service.parse_mcp.ocr`(`PARSE_MCP_OCR`) 지움·경고만) · `low_priority`(`PARSE_LOW_PRIORITY`, 기본 켬 — 일괄 파싱 엔진 자식 nice +10 · Windows BELOW_NORMAL, parse MCP 작업은 끔 · 한계: 우선순위 낮추기(`pipeline.extract.low_priority` — 일괄 파싱 엔진 자식 nice +10)는 **같은 세션·autogroup 안에서만** 효과가 있다: Linux가 `sched_autogroup_enabled=1`이면 CPU를 세션(autogroup)끼리 먼저 나눠 다른 컨테이너·세션의 parse MCP 서비스와는 nice로 겨루지 않고, 컨테이너끼리는 cgroup CPU 가중치(`cpu.weight`)가 정한다, server-guide §2) · `parse_mcp.warmup_sec`(`PARSE_MCP_WARMUP_SEC`, 기본 20 — 새 프로세스 엔진 콜드 시작의 첫 시도 하한) · `pipeline.service.parse_mcp.text_page_sec`(`PARSE_MCP_TEXT_PAGE_SEC`, 기본 1)·`vlm_page_sec`(`PARSE_MCP_VLM_PAGE_SEC`, 기본 60) — parse MCP 작업의 쪽당 제한. VLM 엔진 자식의 `VLM_TIMEOUT`은 min(`common.models.vlm.timeout`, `vlm_page_sec`)로 덮음(값만, 엔진 코드 그대로) ③ 명령 인자 `--phases`(cli parse·night·compare-parse·run-stack)·run_all `--phase`·`--rescue`·`--vlm-all`·`--need-vlm`·`--timeout` 삭제 ④ 문서마다 엔진(형식당 최대 2개)을 동시에, 시간 초과면 제한 두 배로 한 번 더 ⑤ 이미지·스캔 문서는 VLM 엔진만(OCR 끔), 글자 PDF 안 스캔 쪽은 대표 결과의 쪽 VLM이 채움 | settings.yaml에서 `phases`·`phase_sec` 지움 · `run_docs.py`·cron에 `--phases`·`PARSE_PHASES`가 있으면 지움 · 첫 실행 뒤 refactor.md C-65 확인 |
| 10-29 기능 정리(사용자 결정 — `feature/settings-cleanup`) | **설정 칸 지움**: 파싱 판단 에이전트 `PARSE_AGENT*`(12) · 재순위 `SEARCH_RERANK*`·`RERANK_*`(12) · 질문 분해 `MCP_DECOMPOSE`·`DECOMPOSE`(옛 `QA_CHAT_DECOMPOSE`) · 그래프·개념 검색 `SEARCH_GRAPH_CONCEPT_*`(3) · OpenViking `OV_*`(12)·`STRUCTURE_TARGET` · `SOFFICE_CANDIDATES`·`MINERU_BIN`·`GRAPHITI_NEO4J_URI`·`MCP_LIST_DOCS_MAX`·`PADDLE_PYTHON`·`PHASE_REPORT_LEGACY` — settings.yaml에 남아 있으면 경고 한 줄 뒤 무시(`Section.REMOVED` — 한 판 동안, 시작은 됨) — 다음 판 전에 지운다. **질문 분해는 기본 켬이었다** — LLM이 설정된 서버면 긴·복합 질문의 근거 목록이 바뀐다. `search` 도구 입력은 그대로(`methods`의 vector·bm25·id 밖 값과 `decompose`는 무시) | settings.yaml에서 위 칸 지우기 · 첫 실행에 구조화·색인 다시 만들기(code_fp s 바뀜 — 임베딩 캐시 재사용) |
| 합성 문서 선언 잠금 삭제(10-29, 사용자 — 같은 새 이미지 판) | ① `common.models.guard.synthetic_truth`(env `LLM_SYNTHETIC_TRUTH`·옛 `SYNTHETIC_TRUTH`) 칸 삭제 — 외부 모델 허용은 `<PREFIX>_ALLOW_EXTERNAL=1` + `RUN_ENV=local`만 ② 설정 파일에 그 칸이 남아 있으면 경고 한 줄 뒤 무시(시작은 됨 — 한 판 동안, `Section.REMOVED`) ③ migrate가 옛 이름을 더 옮기지 않음 ④ code_fp p0·p1·r·s 바뀜(이번 판 재처리에 포함) | 서버 settings.yaml에 `synthetic_truth` 줄이 있으면 지움 · `run_env`가 dev·prd인지 확인(서버는 외부 모델 늘 거부) |
| 10-29 EDW 접속 하나(op-03 — 사용자 10-29) | ① EDW 벡터 경로 삭제 — `common.connections.edw`(`EDW_SERVER`·`EDW_USER`·`EDW_CONN_FILE` 등)·`EDW_LOAD`·`ask --edw`/`--edw-client` 없음(벡터는 pgvector만) ② 접속 칸 넷(`common.connections.parsing_meta` 접속 칸 `PM_DB_*`·`pipeline.connections.rdb` 접속 칸 `RDB_USER`·`RDB_PASSWORD` 등·`mcp.edw_query` 접속 칸 `EDW_QUERY_SERVER`·`EDW_QUERY_SQLITE`·`EDW_QUERY_CONN_FILE` 등)을 `common.connections.rdb` 하나로 — 계정은 `read`·`write` 둘, 검색 MCP는 `read`만 ③ 옮겨 주는 기능 없음 — 서버 settings.yaml을 새 sample대로 다시 채움(옛 칸은 한 판 동안 경고만) ④ PC 대역은 `RDB_SQLITE` 하나 | refactor.md C-67 |

0.1.0 전 판(10-08~10-16 줄과 S·I 단계 — 10-16~10-28)의 줄은 [env_guide_history.md](../history/env_guide_history.md) "판별 서버 할 일(0.1.0 전)"로 옮겼다(11-02 — 운영 서버는 0.1.0).
