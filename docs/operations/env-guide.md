# 설정 작성 가이드 — `settings.yaml`(서버·PC)

↑ [server-guide.md](server-guide.md) · [release-and-patch.md](release-and-patch.md) · [upgrade-guide.md](upgrade-guide.md)

**원칙**
- 서버에서 손대는 것은 **설정 파일 하나**(`settings.yaml`)뿐이다. 값은 문서·채팅·로그에 쓰지 않는다 — 이 문서는 **이름만** 적는다.
- settings.yaml = `settings.sample.yaml`을 복사해 맨 위 `required`를 채운 것이다. 배치: `required`(꼭 채울 값, 묶음마다 `[PC·서버]`·`[서버만]`) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(보통 비워 둠). 적힌 값은 코드 기본값보다 이긴다 — 코드 기본값이 나중에 바뀌어도 settings.yaml에 적힌 값은 그대로다.
- 옛 배치(최상위 `common`·`pipeline`·`mcp`) 파일·지운 칸·모르는 칸은 시작 거부다(칸 이름만 알림 — 값은 안 찍음). 자리가 바뀐 칸을 옛 자리에 쓰면 "자리가 다른 칸 … → 새 자리"로 거부한다. 옮기는 도구는 없다 — `settings.sample.yaml`과 대조해 고친다.
- 이 문서의 표는 **옛 env 이름**으로 적는다. 파일 자리는 `python -m common.config.sample --where <이름>…`(예 `PG_HOST` → `required.pg.pg_host`).

**서버 값으로 적는 칸** — 코드 기본값과 서버에서 쓰는 값이 다른 칸. 서버 settings.yaml에 적는다:

| 옛 이름 | 파일 자리 | 서버 값 |
|---|---|---|
| `PARSE_POST` | `transform.represent.post_steps` | `all` |
| `EMBED_QUERY_CACHE` | `common.models.embed.embed_query_cache_file` | `''`(빈 글자 — 비운 칸과 결과가 다름) |

## 0. 파일 위치 · 적용 방법

| 기계 | 파일 | 적용 | 모델 엔드포인트 |
|---|---|---|---|
| PC(개발) | 저장소 루트 `settings.yaml`(git 밖, 권한 600) | `RUN_ENV`가 없거나 `local`이면 코드가 이 파일을 찾음. 한 번만 몇 칸 바꿀 때는 오버레이 설정 파일 `SETTINGS_FILE=$(python -m common.config.overrides PIPE_OUT_ROOT=… EMBED_ALLOW_EXTERNAL=1 …)`(**PC 전용**) | 내부망 또는 OpenRouter(기능 시험만 — CLAUDE.md §7) |
| 수집·개발 서버 | `<루트>/settings.yaml`(루트 = 코드 폴더 자체 — git·코드 zip에 없는 파일이라 새 판을 덮어써도 남음, README §5). **주인 UID 10001·그룹 운영 그룹·권한 640**(운영 계정 UID가 10001이면 600) | 컨테이너: compose가 `/etc/rag/settings.yaml`에 읽기 전용(`:ro,z`)으로 붙이고 env는 `SETTINGS_FILE`·`RUN_ENV`만 준다. **값을 바꿀 때는 이 파일을 직접 고친다.** 셸·systemd: `deploy/host/scripts/load_settings.sh`의 `load_settings`가 호스트 칸(이미지·자원·포트·`RAG_OUT`·`DOC_SRC`·`NIGHTLY_*` 등)을 셸 env로 내보내 compose가 치환한다 | 내부망만 |

### 0-0. 실행 기록(JSON 로그·DB 감사·성능)

| 칸 | 기본 | 뜻 |
|---|---|---|
| `ops.log.log_level` | `INFO` | DEBUG·INFO·WARNING·ERROR·CRITICAL |
| `ops.log.log_json_dir` | 비움 | 비우면 PC `output/logs/<앱>.jsonl`, 서버 stdout(컨테이너 로그) |
| `ops.log.log_db_enabled` | 서버(두 이미지) 켬 · PC 끔 | DB(`applog` 스키마) 기록 — 서버 로그는 이것뿐. 먼저 `migrate up --target all`(applog 포함) |
| `ops.log.log_retention_days` | 90 | 월 파티션 보존 일수 |
| `ops.log.log_fallback_dir` | `output/logs` | DB 장애·시간 초과 때 대체 JSON Lines(자동 재적재 없음) — 파일은 이 한 곳 |
| `tuning.ops.log.log_shutdown_sec` | 5 | 종료 때 남은 기록을 쓰는 상한(초) |
| `tuning.search.audit.audit_max_input_bytes` · `audit_max_output_bytes` | 16384 · 65536 | MCP 감사 원문 저장 상한(바이트) |

- `applog.except_doc_info`(적재 안 된 문서 — `skip` 영구 뺌·`error` 실패 기록)는 `ops.log.log_db_enabled`와 관계없이 쓰고 읽는다(대상 목록이 `skip` 키를 뺌, `error` 행은 다음 실행이 다시 고름). 서버는 `migrate up --target applog`(판 `0004_applog`)가 먼저다 — 없으면 대상 목록·받기가 멈춘다. PG 접속 칸을 채운 PC도 파싱 전에 `dbtool up --target applog`. 보존 정리 대상이 아니다.
- **영구 뺌 풀기(기한 없음 — 사람이 지움).** 한 번 들어간 `skip` 키는 `candidate_pick list --skip-done`이 계속 뺀다. 다시 고르게 할 때 — 새 엔진이 확장자를 받게 됐을 때(그 이유 전체), DRM 오탐·고친 파일이 같은 `s3_key`로 다시 올라왔을 때(그 키만) — DB 담당자 승인을 받고 `skip` 행을 지운다. 지운 키는 다음 실행이 다시 고른다(다시 못 읽으면 다시 들어감):
  ```sql
  SELECT reason, count(*) FROM applog.except_doc_info WHERE except_type = 'skip' GROUP BY reason;   -- 먼저 대상 확인
  DELETE FROM applog.except_doc_info WHERE except_type = 'skip' AND reason = 'unsupported_format';   -- 이유 단위(새 엔진이 받는 확장자 — 필요하면 AND file_name LIKE '%.hwpx')
  DELETE FROM applog.except_doc_info WHERE except_type = 'skip' AND source_key = '<s3_key>';         -- 키 단위(DRM 오탐·고친 파일)
  ```
- 서버는 매일 `bash deploy/host/scripts/pipe_exec.sh migrate maintain --target applog`(PC: `python -m common.store.db.dbtool maintain --target applog`)를 돌린다 — 앞으로 2개월 파티션 준비, 보존 기한이 지난 파티션 삭제. 새벽 배치(`nightly_batch.sh scheduled`)가 run_pipeline 앞에 부르고(실패하면 경고만), 새벽 배치를 켜지 않은 서버는 따로 예약한다.
- ⚠️ MCP 감사 행(`applog.mcp_log`)과 대체 파일에는 문서 원문이 들어간다(`get_doc_fulltext` 결과는 파일당 `audit_max_output_bytes`까지). `applog` DB·표와 `ops.log.log_fallback_dir`은 원본 문서와 같은 수준으로 접근을 제한한다. 대체 파일은 지우지 않으므로 디스크 회수도 운영에서 정한다.
- 서버(dev·prd)는 값이 있는 비밀 칸이 8자 미만이면 시작을 거부한다(종료 2, 칸 경로만 찍음).
- 파이프라인 성능 분석: `python -m pipeline.tools.perf_report [<run_id>]`(`--runs` 목록, `--compare` 비교, DB가 꺼져 있으면 `--file output/logs/*.jsonl`).

### 0-1. 읽는 규칙
- **비밀값**(비밀번호·키·토큰)과 **접속 정보**(주소·포트·DB 이름)는 전부 이 파일 하나에만. 각 컨테이너는 common + 자기 앱 절만 읽는다.
- **env로 준 값은 읽지 않는다** — 셸·compose·systemd·`docker exec -e`의 `X=값`은 효과가 없고 시작 때 이름만 경고한다.
- 서버(dev·prd)는 바꿀 값이 있으면 `settings.yaml`을 직접 고치고 상주 컨테이너를 다시 띄운다(또는 0-2 `--set`). 오버레이 설정 파일 도구는 서버에서 종료 2.
- 서버에서 설정 파일을 못 읽거나(권한) 그 이미지 절이 틀리면 컨테이너가 이유(칸 경로·오류 종류만)를 찍고 **시작하지 않는다**(종료 2).
- 호스트 칸만 꺼내 보기(비밀 없음 — 인자는 모델 경로): `bash deploy/host/scripts/load_settings.sh pipeline.host common.host`. 호스트 python에는 PyYAML만 있으면 된다(칸 목록 `deploy/host/scripts/host_settings.tsv` — 설정 모델을 고치면 `PYTHONPATH=. python deploy/release/gen_host_keys.py`로 다시 만듦).
- `run_pipeline.py`(서버 전용)도 같은 파일을 읽는다 — 필요한 칸이 없으면 칸 경로만 찍고 종료 2.
- **모드마다 꼭 채울 칸**(sample 주석 `[필수 · …]`와 같음):
  - `local`(PC): `required.env.run_env`, 모델 접속 `required.models`(`embed_base_url`·`embed_model`·`llm_base_url`·`llm_model`·`vlm_base_url`·`vlm_model`). PG(`required.pg` 접속 다섯 칸)는 채우면 그 PG, 모두 비우면 sqlite 대역. EDW·Object Storage·토큰·배포 칸은 채우지 않는다 — 적혀 있어도 EDW 주소·계정, Object Storage 주소·키, 원천 버킷, 서버 게시 버킷은 비우고 `[settings] local(PC) — 서버 전용 칸을 무시함(비움): <칸 이름>` 한 줄을 찍는다(값 없음). 대신 `dev.local`(가짜 EDW `local_edw_sqlite_file` · 게시 폴더 `local_publish_dir` · 원본 폴더 `local_source_dir` · 새 문서 상한 `local_max_new_docs_per_run`)의 기본값을 쓴다.
  - `dev`·`prd`(서버): 위에 더해 PG 접속 다섯 칸, EDW(`edw_host`·`edw_database`·`edw_read_user`·`edw_read_password`), `publish_bucket`, Object Storage 세 칸, 토큰(`mcp_token`·원문 도구를 쓰면 `fulltext_sign_key`), 배포 네 칸(`pipeline_image`·`mcp_image`·`host_docs_dir`·`pg_container_name`). `pg_schema`는 비우면 `data_parsing`. EDW는 읽기만 하므로 쓰기 계정 칸은 없다.
- 라이브러리가 읽는 env(`TZ`·`OMP_NUM_THREADS`·`HF_HUB_OFFLINE`·`TESSDATA_PREFIX` 등 — 허용 목록 `common.config.settings.LIB_ENV_NAMES`)는 `ops.runtime.library_env` 사전에 적는다. 목록 밖 이름은 검증 오류.

### 0-2. 한 번 실행에만 다른 값 — `--set 이름=값`(서버 포함)
- `python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/x --set PARSE_POST=supsub parse …`처럼 진입 모듈(`pipeline.cli`·`pipeline.extract.candidate_ready`·`pipeline.transform.structure.gold_bundle`·`pipeline.load.pgvector_load`·`pipeline.load.publish_parse_result`)에 여러 번 준다(같은 이름은 뒤 값).
- 모르는 이름·호스트 칸·**비밀 칸**은 모든 환경에서 종료 2. 값 형식 오류는 서버 종료 2·local 경고. 서버에서 `SETTINGS_FILE`이 없으면 종료 2.

### 0-3. 새 서버 설정
`host_ctl.sh init`이 `settings.sample.yaml`을 복사해 둔다(README [서버 설치 순서](../../README.md#서버-설치-순서) 3번). **PC의 settings.yaml을 복사하지 않는다.** `required`(`[서버만]` 포함)와 위 "서버 값으로 적는 칸"만 채우고 `bash deploy/host/scripts/pipe_exec.sh check_env`로 확인한다.

## 1. 칸 (영역별)

**작성 규칙**
- `settings.sample.yaml`의 **빈 칸**(`pg_host:` 뒤가 비어 있음)은 사람이 꼭 적을 값이다(`[필수 · 모드]` — 주석의 예를 보고 채움). **`null`**은 비워 두면 되는 칸이다(코드 기본값·계산값·끔 — 주석의 "null = …"). 읽을 때는 둘 다 "값 없음"으로 같다.
- 비운 칸·빈 글자 `''`은 코드 기본값이다. 예외: 기본값이 없는 글자 칸과 `--where`가 `[빈 글자 유지]`로 보여 주는 칸만 `''`이 빈 글자.
- 글자 칸에 쓴 `yes`·`no`·`1`·`0`은 쓴 글자 그대로다.
- 켜기 칸은 YAML `true`·`false`. `--where`가 `[켬: …]`·`[끔: …]`로 보여 주는 칸은 `0`·`1`도 되고 `yes`·`on`·`off` 등은 검증 오류.
- `ops.runtime.engine_processes`·`tuning.ops.runtime.engine_threads_per_process`는 숫자(소수 가능) 또는 `auto`(= 비움, 계산).
- 검증 오류 메시지는 칸 경로·오류 종류만 찍는다(값은 안 찍음).
- ⚠ `transform.represent.post_steps`(`PARSE_POST`)에 `''`·`[]`를 쓰면 **끔**.

### 실행 환경
| 이름 | 뜻 | 필수? |
|---|---|---|
| `RUN_ENV`(`required.env.run_env`) | `local`(PC) · `dev`·`prd`(서버 — 내부망 전용 · 가짜 LLM 거부) | **필수** — 없으면 compose가 멈추고 앱 명령이 종료 2. `selftest`·`check`·`help`·`tool check_env`는 없어도 돎 |
| `SOURCE_SYSTEMS`(`required.source.source_systems`) | 파싱할 원천 목록 — EDW `AI.FileStorageMap.source_system` 값(대소문자 무관). `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`·`DEV-<1~99>`. 목록에 `FAQ`가 없으면 FAQ 교체 확인도 하지 않는다 | 선택 — 비우면 운영 5개 원천(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other` — `DEV-<숫자>` 행은 뺌). `DEV-…`는 dev·local만(prd면 종료 2), 모르는 값이면 종료 2. `DEV-<숫자>`를 새로 넣으면 `migrate up --target search`로 검색 스키마 `<기준>_dev_<숫자>`를 먼저 만든다(없으면 적재가 멈춤) |

### 사내망 판정
| 이름 | 뜻 | 기본 | 언제 채우나 |
|---|---|---|---|
| `INTERNAL_HOST_SUFFIXES`(`common.models.guard.internal_host_suffixes`) | 사내 도메인 접미사 — **상위 도메인**(모델 주소가 `llm.corp.example`이면 `corp.example`) | 비움(늘 `.local`·`.internal`·`.corp`·`.lan` 인정) | 모델 주소가 점 있는 호스트 이름이고 기본 접미로 끝나지 않을 때 — 호스트 이름 확인과 IP 확인을 둘 다 통과해야 내부로 본다 |
| `INTERNAL_IP_RANGES`(`common.models.guard.internal_ip_ranges`) | 사내 IP 대역(CIDR) | 비움 | 모델 서버 IP가 사설 대역(RFC1918) 밖일 때만 |

### 모델
| 이름 | 뜻 | 필수? |
|---|---|---|
| `LLM_BASE_URL`·`LLM_MODEL`·`LLM_API_KEY` | 내부망 LLM(생각 모델이면 `LLM_EXTRA_BODY`로 생각 끄기 권장) | 서버 ✓ |
| `VLM_BASE_URL`·`VLM_MODEL`·`VLM_API_KEY` | 이미지 문서·그림 판정 | 서버 ✓ |
| `EMBED_BASE_URL`·`EMBED_MODEL`·`EMBED_API_KEY` | 임베딩(차원은 첫 응답에서) — API로만 | PC·서버 ✓ |

### 저장소 (PostgreSQL + pgvector)
| 이름 | 메모 |
|---|---|
| `PG_HOST`·`PG_PORT`·`PG_DB`·`PG_USER`·`PG_PASSWORD`·`PG_SCHEMA` | 서버는 접속 다섯 칸 필수(자동 탐지 없음 — 비면 채울 자리를 적고 멈춤) · `PG_SCHEMA`(`pg_schema`)는 비우면 `data_parsing`(여러 벌도 같은 스키마) · PC(local)는 접속 칸을 모두 비우면 sqlite 대역. compose는 `network_mode: host`라 `127.0.0.1`이 서버 자신. 계정은 우리 스키마 권한만 |

### 검색 MCP
| 이름 | 기본 | 메모 |
|---|---|---|
| `MCP_HOST`(`search.server.mcp_bind_host`) | `127.0.0.1` | 사내 IP로 열면 `MCP_TOKEN` 필수, `0.0.0.0`은 거부 |
| `MCP_PORT`·`MCP_TOKEN` | `8765`·비움 | 토큰은 `required.tokens.mcp_token` 하나 — 검색 MCP·`parse_document` 작업 서비스가 함께 쓴다(호출 쪽은 같은 값을 `Authorization: Bearer`로) · 공백만인 토큰은 없음과 같음 |
| `FULLTEXT_SIGN_SECRET`(`required.tokens.fulltext_sign_key`) | 비움 | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 `sfid` 서명 키(비밀). 비면 두 도구가 `not_configured`. 바꾸면 이미 발급된 `sfid`가 모두 무효 |
| `DATA_PARSING_PORT`(`ops.services.data_parsing.data_parsing_port`) | `8766` | `parse_document` 작업 서비스 포트(127.0.0.1) — 작업 서비스가 듣고 검색 MCP가 이 값으로 부름(칸 하나). 여러 벌이면 벌마다 다르게(기본값이면 시작 거부) |
| `DATA_PARSING_MAX_MB`(`ops.services.data_parsing.mcp_parse_max_file_mb`) | `100` | `parse_document` 파일 1건 크기 상한(MB) — 검색 MCP와 파싱 서비스가 같은 칸을 읽음 |
| `MCP_METHODS` | `vector,bm25,id` | 이 셋만 있음 |
| `MCP_ALLOWED_HOSTS` | 비움 | 루프백이 아닐 때, 리버스 프록시 등 다른 Host로도 부르면 쉼표로 추가 |

### EDW 쿼리 도구(`query_edw`·`edw_meta`)
`required.edw`의 **읽기 계정**만 쓴다(파이프라인 원천 조회와 같은 계정 — 운영 준비는 [server-guide §4-1](server-guide.md#4-1-edw-쿼리-도구-설정--edw_metaquery_edw)).

| 이름 | 기본 | 메모 |
|---|---|---|
| `RDB_HOST`·`RDB_PORT`·`RDB_DATABASE`·`RDB_READ_USER`·`RDB_READ_PASSWORD` | 비움·`1433`·비움 | `required.edw`(`edw_host`·`edw_port`·`edw_database`·`edw_read_user`·`edw_read_password`) — 서버만. PC(local)는 적혀 있어도 주소·계정을 비우고 경고(칸 이름만) |
| `RDB_FILE_TABLE`(`required.edw.edw_file_table`) | `AI.FileStorageMap` | 파싱 대상 파일 목록을 읽을 EDW 표 — `<스키마>.<표>`(영문·숫자·_만, SQL에 그대로 들어가므로 꼴이 틀리면 시작 거부). 대상 목록(`candidate_pick list`)만 쓴다 — 적재 메타 사슬의 표 이름은 `edw_chain.yaml` |
| `RDB_SQLITE`(`dev.local.local_edw_sqlite_file`) | 비움 | PC(local) 전용 가짜 EDW 파일 — 비우면 `valid_env/edw/edw_copy.sqlite`(없으면 git의 `valid_env/edw/edw.sqlite`를 복사해 만듦 — 원본은 다시 만들기 `python -m validation.e2e.edw_standin`). local은 늘 이 대역을 쓴다 · 서버 설정에 있으면 EDW를 쓸 때 실패 |
| `EDW_QUERY_MAX_ROWS` | `1000` | 도구 `max_rows`의 상한 |
| `EDW_QUERY_TIMEOUT_SEC` | `20` | 넘으면 `timeout` |
| `EDW_QUERY_MAX_BYTES` | `2000000` | 응답 JSON 크기 상한 — 넘으면 끝 행부터 버리고 `truncated: true` |
| `EDW_META_DIR`(`search.edw_meta.edw_meta_catalog_dir`) | 비움(`/app/config/edw_meta` — 서버 compose는 안 붙임) | `edw_meta` 자료(`catalog.json`·`columns.jsonl`, 개인정보 없는 자료) 폴더. 서버는 `<루트>/output/edw_meta/`에 복사하고 `/app/output/edw_meta`로 적는다. 없으면 `edw_meta`만 `not_configured` |

### 이미지 태그·호스트 경로 (compose 치환용)
| 이름 | 메모 |
|---|---|
| `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`(`required.deploy.pipeline_image`·`mcp_image`) | dev `*-runtime:<판>` · prd `*:<판>` |
| `RAG_OUT`(`ops.host.host_output_dir`) | 결과 폴더(컨테이너 `/app/output`) |
| `DOC_SRC`(`required.deploy.host_docs_dir`) | 원본 문서 폴더(컨테이너 `/data/docs:ro`) |
| `EDW_CHAIN_SRC`(`ops.host.host_edw_chain_file`) | EDW 사슬 사본(컨테이너 `/etc/rag/edw_chain.yaml:ro`) — 비우면 `<루트>/edw_chain.yaml`, 상대 경로는 루트 기준 |
| `EXTRA_COMPOSE`(`ops.host.extra_compose`) | 더 붙일 compose 파일 목록(볼륨·env 더하기 — 틀 `deploy/host/compose/extra.example.yml`) — `host_ctl.sh`·`mcp_keepalive.sh`가 맨 뒤에 붙임. 상대 경로는 루트 기준(예 `compose.extra.yml` = `<루트>/compose.extra.yml`) · 없는 파일이면 `host_ctl.sh` 종료 2 |
| `COMPOSE_PROJECT`(`ops.host.compose_project`) | compose 묶음 밑 이름(기본 `compose`) — 실제 이름은 끝에 벌 번호(`-<숫자>`) |
| `PIPELINE_CONTAINER`·`DATA_PARSING_CONTAINER`·`MCP_CONTAINER`(`ops.containers.<pipeline·data_parsing·mcp>.<…>_container_name`) | 컨테이너 밑 이름(기본 `data-pipeline`·`mcp-data-parsing`·`mcp-server`) — 실제 이름은 끝에 벌 번호. 바꾸기 전에 `host_ctl.sh down` |

### 원천·경로 묶음
코드 주석의 "env-guide 1-2"가 이 절이다.

| 이름 | 무엇 | 형식 |
|---|---|---|
| `PARSE_SOURCE`(`extract.source.source_input_location`) | 이번에 읽을 원천 | 폴더 · `rdb:csv:<경로>` |
| `LOCAL_PARSE_SOURCE`(`dev.local.local_source_dir`) | PC(local) 원천 — `PARSE_SOURCE`·`--source`가 없을 때. 게시 폴더·맨 위 `*.md`는 원본으로 읽지 않음 | 폴더(기본 `valid_env/object_storage`) |
| `LOCAL_PARSE_MAX_NEW`(`dev.local.local_max_new_docs_per_run`) | PC(local) 한 번에 새로 파싱할 문서 수 — `PARSE_MAX_NEW`(`extract.max_new_docs_per_run`)·`--max-new`가 없을 때 | 정수(기본 5, 0 = 제한 없음) |
| `PG_FILTER_EXACT_MAX` | 고객 필터 정확 검색 문턱 | 고객으로 좁힌 청크가 이 수(기본 20000) 이하면 정확 검색 |
| 변경 뒤 확인 | — | `python -m common.check.checker env`(서버는 `pipe_exec.sh check_env`) |

### 원천 Object Storage·EDW·게시
| 이름 | 메모 |
|---|---|
| `OS_ENDPOINT`·`OS_REGION`·`OS_ACCESS_KEY`·`OS_SECRET_KEY`·`OS_VERIFY_TLS` | `required.object_storage`(`object_storage_endpoint`·`object_storage_region`·`object_storage_access_key`·`object_storage_secret_key`·`object_storage_verify_tls`) — 서버만. PC(local)는 적혀 있어도 주소·키를 비우고 경고(게시는 `dev.local.local_publish_dir` 폴더). `object_storage_region` 비우면 `us-east-1` · `object_storage_verify_tls` 비우면 `1`, 사내 CA면 CA 파일 경로(`0`이면 검증 끔 — 경고) |
| `RDB_CONNECT_KWARGS` | EDW 연결 추가 인자(JSON — 비밀) |
| `PM_BUCKET`·`PM_PREFIX`(`required.publish.publish_bucket`·`publish_prefix`) | silver 게시 위치 — 서버: 버킷 이름(원천 원본 버킷과 달라야 함) · PC(local): 이 칸은 무시하고 `dev.local.local_publish_dir`(`LOCAL_PM_DIR` — 폴더 경로, 기본 `valid_env/object_storage/Parsing_Result`, 처음 게시할 때 만듦)에 쓴다. `publish_prefix`는 버킷(폴더) 안 경로 접두(비우면 맨 위). |
| `EDW_CHAIN_FILE`(`ops.paths.edw_chain_file`) | EDW 조인 사슬 파일 — 적재와 검색 MCP가 같은 칸을 읽는다. 비우면 코드의 `resources/config/edw_chain.yaml`, 서버 사본을 쓰려면 `/etc/rag/edw_chain.yaml`. 쓰는 법: [release-and-patch §8](release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버) |

### 새벽 배치 (systemd `data-pipeline-nightly`)
코드 주석의 "env-guide 1-3"이 이 절이다. **세 칸이 모두 있어야 돈다**(하나라도 비면 없음).

| 이름 | 뜻 |
|---|---|
| `NIGHTLY_TIME`(`ops.nightly.nightly_start_time`) | 시작 시각 HH:MM(서버 시간) — 타이머는 5분마다 깨우고 그 시각부터 5분 안에 `run_pipeline.py --start-offset 0 --skip-done` |
| `NIGHTLY_MAX_DOCS`(`ops.nightly.nightly_max_docs`) | 한 번에 처리할 새 문서 수 상한(1 이상) |
| `NIGHTLY_DEADLINE`(`ops.nightly.nightly_stop_time`) | 마감 HH:MM(시작보다 이르면 다음 날, 시작보다 5분 넘게 뒤) — 지나면 새 문서를 받지 않고 받은 문서는 끝까지 |

### 선택 기능 — 개발 작업 공간 (`option`, 파일 맨 아래)
앱은 이 절을 읽지 않는다 — 호스트 스크립트(`host_ctl.sh`)와 작업 공간 시작 스크립트(`dev_entry.sh` → `git_cred.py`)만 쓴다. 비우면 끔. 쓰는 법: README §5-0 "개발 작업 공간".

| 이름 | 기본 | 뜻 |
|---|---|---|
| `DEVBOX_SSH_PORT`(`option.devbox.ssh_port`) | 비움(끔) | 적으면 `data-pipeline`을 SSH 작업 공간(`devbox`)으로 띄움 — 그 포트에서 sshd(호스트 네트워크 그대로, 개발자마다 다르게) · 코드 폴더 쓰기 가능 · 홈 `<루트>/home`(포트를 적은 뒤 `host_ctl.sh init`이 만듦 — 없으면 `host_ctl.sh up` 종료 2). 개발 서버(dev)의 실행 이미지에서만 — prd·코드가 든 이미지면 `host_ctl.sh` 종료 2 |
| `DEVBOX_HOME`(`option.devbox.home_dir`) | 비움(`<루트>/home`) | 작업 공간 홈의 호스트 폴더 — `/home/rag`로 붙임. `host_ctl.sh init`이 만듦(UID 10001, 700) · 상대 경로는 루트 기준 |
| `DEVBOX_OPENCODE_CONFIG`(`option.devbox.opencode_config`) | 비움(이미지의 틀) | opencode 설정 파일의 호스트 경로 — 읽기 전용으로 붙이고 `OPENCODE_CONFIG`로 가리킴. 비우면 홈의 `~/.config/opencode/opencode.json`(첫 시작에 틀 복사 — 내부망 모델만) |
| `DEVBOX_GITEA_URL`·`DEVBOX_GITEA_USER`·`DEVBOX_GITEA_TOKEN`(`option.devbox.gitea_url`·`gitea_user`·`gitea_token` — 토큰은 비밀) | 비움(설정 안 함) | 셋 다 적으면 작업 공간 시작 때 `~/.git-credentials`(권한 600)에서 그 호스트 줄 `<scheme>://<계정>:<토큰>@<호스트[:포트]>`만 바꾸고(다른 줄 그대로) `git config --global credential.helper store` — 하나라도 비우면 전에 쓴 줄(`~/.devbox/gitea_host`)을 지움. 주소는 `http(s)://호스트[:포트][/경로]`(`https://` 권장 — http면 토큰이 암호화 없이 감). 컨테이너 안에서 붙인 settings.yaml을 직접 읽는다(토큰은 env로 안 넘김) |
| `DEVBOX_GIT_USER_NAME`·`DEVBOX_GIT_USER_EMAIL`(`option.devbox.git_user_name`·`git_user_email`) | 비움 | 적으면 작업 공간 시작 때 `git config --global user.name`·`user.email` |

## 2. 자원·병렬 (보통 안 건드림)

`PIPE_PROCS`(기본 `auto`)·`PIPE_WORKERS`·`VLM_CONCURRENCY`·`OCR_DPI`·`OCR_MAX_PAGES`·`MAX_FILE_MB`·`MEM_MAX_PCT`(90)·`CPU_MAX_LOAD`(0.9)·`EMBED_BATCH`·`EMBED_TIMEOUT`·`VLM_TIMEOUT` — 설명·기본값은 `settings.sample.yaml`. 자동 계산 계수와 호출 제한 시간·병렬 세부값은 `tuning` 절. 컨테이너 CPU·메모리 상한은 README §5-0 "자원".

**VLM(그림 읽는 모델) 설정은 한 벌이다**(엔진 `qwen_vlm`·쪽 VLM·그림 VLM 공통):

| 칸 | 뜻 |
|---|---|
| `common.models.vlm.vlm_requests_per_doc`(`VLM_CONCURRENCY`, 4) | 문서 하나 안의 동시 요청 수 |
| `common.models.vlm.vlm_max_total_requests`(`VLM_MAX_CONCURRENCY`, 8) | 한 프로세스 안 모든 VLM 호출의 합 상한 · 일괄 파싱은 동시 문서 수로 나눠 문서당 수를 줄임 |
| `common.models.vlm.vlm_timeout_sec`(`VLM_TIMEOUT`, 180초) | 호출 1건 제한 · VLM 엔진의 문서 제한 = 쪽 수 × 이 값 |
| `tuning.common.models.vlm.vlm_retries`(`VLM_RETRY`, 1) | 실패한 호출 재시도 횟수 |
| `common.models.vlm.vlm_extra_request_body`(`VLM_EXTRA_BODY`) | 요청 본문에 합칠 JSON — 생각 모델이면 생각 끄기 권장(예 `{"chat_template_kwargs": {"enable_thinking": false}}` · OpenRouter `{"reasoning": {"enabled": false}}`). 비우면 아무것도 안 더함 |
| `extract.page_render_dpi`(`OCR_DPI`, 150) | 쪽·그림 렌더 해상도(OCR 엔진도 같은 값) |
| `transform.vlm.vlm_max_pages_per_doc`(`VLM_PAGE_MAX`) | 문서당 VLM으로 옮길 쪽 수(비움 = 전부, 0 = 끔) · `extract.ocr.ocr_max_pages_per_doc`는 OCR 엔진에만 |

지운 칸(남아 있으면 시작 거부): `extract.vlm_page_sec`·`tuning.ops.services.data_parsing.vlm_page_sec`·`tuning.transform.vlm.deadline`·`transform.vlm.global_concurrency`·`transform.vlm.page_slow`·`tuning.transform.vlm.page_concurrency`·`tuning.transform.vlm.page_min_concurrency`·`tuning.transform.figures.vlm_parallel`·`tuning.ops.nightly_run.vlm_concurrency`. 이 이름(`VLM_DEADLINE`·`VLM_GLOBAL_CONCURRENCY`·`FIGURES_VLM_PARALLEL`·`VLM_PAGE_SLOW` 등)을 `--set`으로 주면 거부된다.

## 3. 전체 목록과 읽는 순서

- **전체 목록은 `settings.sample.yaml`**(생성 `python -m common.config.sample` — 값 자리 = 코드 기본값(`null` = 비움), 줄 끝 주석 = `[필수 · 언제(어느 앱)]`·`[선택]`·설명·허용값 또는 예·`[비밀]`). 옛 env 이름·켜기 판정 꼴은 `--where <이름>`.
- 읽는 순서: 테스트 값 > 오버레이 설정 파일·`--set` > settings.yaml > 코드 기본값.

## 4. 확인

```bash
python -m common.check.checker env    # 빠진 필수 값·사내망 판정·경로 존재(값은 안 찍음) — 서버: pipe_exec.sh check_env
python -m common.check.checker ping   # LLM·VLM·EMBED 실호출 — 실패 있으면 종료 1 — 서버: pipe_exec.sh ping_models
ls -l ../settings.yaml                # 서버(코드 폴더에서): 주인 10001·권한 640
```

## 5. 서버 경로 칸 — 컨테이너 안 절대 경로

- 컨테이너 안에서 **상대 경로는 `/app` 기준**이다(`/app/deploy`가 아님 — 작업 자리가 `/app`이고 코드는 `/app/deploy`). `file://` 꼴도 같다: `file://output/x` → `/app/output/x`.
- 컨테이너 사용자(UID 10001)가 **쓸 수 있는 곳은 붙인 폴더뿐**이다 — 결과 폴더 `/app/output`(호스트 `<루트>/output` 또는 `ops.host.host_output_dir`). 그 밖(`/app`·`/app/deploy`·`/etc/rag`)은 쓰기가 안 된다. 예: `file://x` → `/app/x`는 권한 오류로 멈춘다.
- 그래서 서버 settings.yaml의 경로 칸(`ops.paths.*`·`ops.log.log_fallback_dir`·`search.edw_meta.edw_meta_catalog_dir` 등)은 **컨테이너 안 절대 경로**로 적고, 무엇이든 쓰는 자리는 `/app/output/…` 아래로 둔다(예 `/app/output/edw_meta`). 비워 두면 기본값이 이미 `/app/output` 아래다.
- 호스트 쪽 칸(`ops.host.host_output_dir`·`required.deploy.host_docs_dir`·`ops.run_pipeline.run_pipeline_work_dir`·`option.devbox.opencode_config`)은 **호스트 절대 경로**다.
- PC에서 Docker로 시험할 때 `valid_env`의 자료를 쓰려면 `/app/valid_env/…`에 붙이고, 시험 설정의 경로도 그 자리(절대 경로)로 적는다.
