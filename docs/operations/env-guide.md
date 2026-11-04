# 설정 작성 가이드 — `settings.yaml`(서버·PC)

↑ [server-guide.md](server-guide.md) · [release-and-patch.md](release-and-patch.md)

**원칙**
- 서버에서 손대는 것은 **설정 파일 하나**(`settings.yaml`)뿐이다. 값은 문서·채팅·로그에 쓰지 않는다 — 이 문서는 **이름만** 적는다.
- settings.yaml = `settings.sample.yaml`을 복사해 맨 위 `required`를 채운 것이다. 배치: `required`(꼭 채울 값, 묶음마다 `[PC·서버]`·`[서버만]`) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → `tuning`(보통 비워 둠). 적힌 값은 코드 기본값보다 이긴다 — 코드 기본값이 나중에 바뀌어도 settings.yaml에 적힌 값은 그대로다.
- 옛 배치(최상위 `common`·`pipeline`·`mcp`) 파일은 시작 거부다 — `python -m common.config.migrate <옛 settings.yaml> --out <새 파일>`로 바꾼다(지운 칸은 "삭제됨"으로 이름만 알림, pipeline·mcp 설정 모델이 다 있는 코드 폴더에서 실행). 자리가 바뀐 칸을 옛 자리에 쓰면 "자리가 다른 칸 … → 새 자리"로 거부한다.
- 이 문서의 표는 **옛 env 이름**으로 적는다. 파일 자리는 `python -m common.config.sample --where <이름>…`(예 `PG_HOST` → `required.pg.host`).

**서버 값으로 적는 칸** — 코드 기본값과 서버에서 쓰는 값이 다른 칸. 서버 settings.yaml에 적는다:

| 옛 이름 | 파일 자리 | 서버 값 |
|---|---|---|
| `RUN_MODE` | `required.env.run_mode` | `prod`(EDW `AI.ParsingMeta`를 못 읽으면 종료 4 — 서버는 `run_env`만으로도 같게 멈춤) |
| `PARSE_POST` | `transform.represent.post` | `all` |
| `EMBED_QUERY_CACHE` | `common.models.embed.query_cache` | `''`(빈 글자 — 비운 칸과 결과가 다름) |

## 0. 파일 위치 · 적용 방법

| 기계 | 파일 | 적용 | 모델 엔드포인트 |
|---|---|---|---|
| PC(개발) | 저장소 루트 `settings.yaml`(git 밖, 권한 600) | `RUN_ENV`가 없거나 `local`이면 코드가 이 파일을 찾음. 한 번만 몇 칸 바꿀 때는 오버레이 설정 파일 `SETTINGS_FILE=$(python -m common.config.overrides PIPE_OUT_ROOT=… EMBED_ALLOW_EXTERNAL=1 …)`(**PC 전용**) | 내부망 또는 OpenRouter(기능 시험만 — CLAUDE.md §7) |
| 수집·개발 서버 | `<루트>/settings.yaml`(루트 = 코드 폴더의 부모 — 코드 폴더 밖, README §5). **주인 UID 10001·그룹 운영 그룹·권한 640**(운영 계정 UID가 10001이면 600) | 컨테이너: compose가 `/etc/rag/settings.yaml`에 읽기 전용(`:ro,z`)으로 붙이고 env는 `SETTINGS_FILE`·`RUN_ENV`만 준다. **값을 바꿀 때는 이 파일을 직접 고친다.** 셸·systemd: `deploy/host/scripts/settings_env.sh`의 `load_settings`가 호스트 칸(이미지·자원·포트·`RAG_OUT`·`DOC_SRC`·`NIGHTLY_*` 등)을 셸 env로 내보내 compose가 치환한다 | 내부망만 |

### 0-0. 실행 기록(JSON 로그·DB 감사·성능 — op-01)

| 칸 | 기본 | 뜻 |
|---|---|---|
| `ops.log.level` | `INFO` | DEBUG·INFO·WARNING·ERROR·CRITICAL |
| `ops.log.dir` | 비움 | 비우면 PC `logs/<앱>.jsonl`, 서버 stdout(컨테이너 로그) |
| `ops.log.db_enabled` | 서버(두 이미지) 켬 · PC 끔 | DB(`applog` 스키마) 기록 — 서버 로그는 이것뿐. 먼저 `migrate up --target all`(applog 포함) |
| `ops.log.retention_days` | 90 | 월 파티션 보존 일수 |
| `ops.log.fallback_dir` | `output/logs` | DB 장애·시간 초과 때 대체 JSON Lines(자동 재적재 없음) — 파일은 이 한 곳 |
| `ops.log.shutdown_sec` | 5 | 종료 때 남은 기록을 쓰는 상한(초) |
| `search.audit.max_input_bytes` · `max_output_bytes` | 16384 · 65536 | MCP 감사 원문 저장 상한(바이트) |

- 서버는 매일 `bash deploy/host/scripts/run_tool.sh migrate maintain --target applog`(PC: `python -m common.store.db.dbtool maintain --target applog`)를 예약한다 — 앞으로 2개월 파티션 준비, 보존 기한이 지난 파티션 삭제.
- ⚠️ MCP 감사 행(`applog.mcp_call`)과 대체 파일에는 문서 원문이 들어간다(`get_doc_fulltext` 결과는 파일당 `max_output_bytes`까지). `applog` DB·표와 `ops.log.fallback_dir`은 원본 문서와 같은 수준으로 접근을 제한한다(C-79). 대체 파일은 지우지 않으므로 디스크 회수도 운영에서 정한다.
- 서버(dev·prd)는 값이 있는 비밀 칸이 8자 미만이면 시작을 거부한다(종료 2, 칸 경로만 찍음).
- 파이프라인 성능 분석: `python -m pipeline.tools.perf [<run_id>]`(`--runs` 목록, `--compare` 비교, DB가 꺼져 있으면 `--file output/logs/*.jsonl`).

### 0-1. 읽는 규칙
- **비밀값**(비밀번호·키·토큰)과 **접속 정보**(주소·포트·DB 이름)는 전부 이 파일 하나에만. 각 컨테이너는 common + 자기 앱 절만 읽는다.
- **env로 준 값은 읽지 않는다** — 셸·compose·systemd·`docker exec -e`의 `X=값`은 효과가 없고 시작 때 이름만 경고한다.
- 서버(dev·prd)는 바꿀 값이 있으면 `settings.yaml`을 직접 고치고 상주 컨테이너를 다시 띄운다(또는 0-2 `--set`). 오버레이 설정 파일 도구는 서버에서 종료 2.
- 서버에서 설정 파일을 못 읽거나(권한) 그 이미지 절이 틀리면 컨테이너가 이유(칸 경로·오류 종류만)를 찍고 **시작하지 않는다**(종료 2).
- 호스트 칸만 꺼내 보기(비밀 없음 — 인자는 모델 경로): `bash deploy/host/scripts/settings_env.sh pipeline.host common.host`. 호스트 python에는 PyYAML만 있으면 된다(칸 목록 `deploy/host/scripts/host_keys.tsv` — 설정 모델을 고치면 `PYTHONPATH=. python deploy/release/hostkeys.py`로 다시 만듦).
- `run_docs.py`(서버 전용)도 같은 파일을 읽는다 — 필요한 칸이 없으면 칸 경로만 찍고 종료 2.
- 라이브러리가 읽는 env(`TZ`·`OMP_NUM_THREADS`·`HF_HUB_OFFLINE`·`TESSDATA_PREFIX` 등 — 허용 목록 `common.config.settings.LIB_ENV_NAMES`)는 `ops.runtime.lib_env` 사전에 적는다. 목록 밖 이름은 검증 오류.

### 0-2. 한 번 실행에만 다른 값 — `--set 이름=값`(서버 포함)
- `python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/x --set PARSE_POST=supsub parse …`처럼 진입 모듈(`pipeline.cli`·`pipeline.extract.source`·`pipeline.stackcfg`·`pipeline.transform.structure.build_bundle`·`pipeline.load.pgvector_load`·`pipeline.load.publish_parse_result`)에 여러 번 준다(같은 이름은 뒤 값).
- 모르는 이름·호스트 칸·**비밀 칸**은 모든 환경에서 종료 2. 값 형식 오류는 서버 종료 2·local 경고. 서버에서 `SETTINGS_FILE`이 없으면 종료 2.

### 0-3. 새 서버 설정
`dc.sh init`이 `settings.sample.yaml`을 복사해 둔다(README [서버 설치 순서](../../README.md#서버-설치-순서) 3번). **PC의 settings.yaml을 복사하지 않는다.** `required`(`[서버만]` 포함)와 위 "서버 값으로 적는 칸"만 채우고 `bash deploy/host/scripts/run_tool.sh check_env`로 확인한다.

## 1. 칸 (영역별)

**작성 규칙**
- 비운 칸·빈 글자 `''`은 코드 기본값이다. 예외: 기본값이 없는 글자 칸과 `--where`가 `[빈 글자 유지]`로 보여 주는 칸만 `''`이 빈 글자.
- 글자 칸에 쓴 `yes`·`no`·`1`·`0`은 쓴 글자 그대로다.
- 켜기 칸은 YAML `true`·`false`. `--where`가 `[켬: …]`·`[끔: …]`로 보여 주는 칸은 `0`·`1`도 되고 `yes`·`on`·`off` 등은 검증 오류.
- `pipe_procs`·`pipe_threads`는 숫자(소수 가능) 또는 `auto`(= 비움, 계산).
- 검증 오류 메시지는 칸 경로·오류 종류만 찍는다(값은 안 찍음).
- ⚠ `transform.represent.post`(`PARSE_POST`)에 `''`·`[]`를 쓰면 **끔**.

### 실행 환경
| 이름 | 뜻 | 필수? |
|---|---|---|
| `RUN_ENV`(`required.env.run_env`) | `local`(PC) · `dev`·`prd`(서버 — 내부망 전용 · 가짜 LLM 거부) | **필수** — 없으면 compose가 멈추고 앱 명령이 종료 2. `selftest`·`check`·`help`·`tool check_env`는 없어도 돎 |

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
| `PG_HOST`·`PG_PORT`·`PG_DB`·`PG_USER`·`PG_PASSWORD`·`PG_SCHEMA` | 모두 필수(자동 탐지 없음 — 비면 채울 자리를 적고 멈춤). compose는 `network_mode: host`라 `127.0.0.1`이 서버 자신. 계정은 우리 스키마 권한만 |

### 검색 MCP
| 이름 | 기본 | 메모 |
|---|---|---|
| `MCP_HOST`(`search.server.host`) | `127.0.0.1` | 사내 IP로 열면 `MCP_TOKEN` 필수, `0.0.0.0`은 거부 |
| `MCP_PORT`·`MCP_TOKEN` | `8765`·비움 | 토큰은 `required.tokens.mcp`(호출 쪽은 같은 값을 `Authorization: Bearer`로) · 공백만인 토큰은 없음과 같음 |
| `FULLTEXT_SIGN_SECRET`(`search.server.fulltext_secret`) | 비움 | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 `sfid` 서명 키(비밀). 비면 두 도구가 `not_configured`. 바꾸면 이미 발급된 `sfid`가 모두 무효 |
| `PARSE_SERVICE_TOKEN`(`required.tokens.parse_proxy`) | 비움(→ `MCP_TOKEN`) | `parse_document`가 작업 서비스를 부를 때 쓰는 토큰 — `required.tokens.parse_mcp`와 같은 값. 둘 다 없으면 "parse 서비스 토큰 없음" 오류 |
| `PARSE_MCP_MAX_MB`(`ops.runtime.parse_max_mb`) | `100` | `parse_document` 파일 1건 크기 상한(MB) — 검색 MCP와 파싱 서비스가 같은 칸을 읽음 |
| `MCP_METHODS` | `vector,bm25,id` | 이 셋만 있음 |
| `MCP_ALLOWED_HOSTS` | 비움 | 루프백이 아닐 때, 리버스 프록시 등 다른 Host로도 부르면 쉼표로 추가 |
| `MCP_INSTRUCTIONS`(`search.server.instructions`) | 비움 | MCP 안내 문구 교체 |

### EDW 쿼리 도구(`query_edw`·`edw_meta`)
`required.edw`의 **읽기 계정**만 쓴다(파이프라인 원천 조회와 같은 계정 — 운영 준비는 [server-guide §4-1](server-guide.md#4-1-edw-쿼리-도구-설정--edw_metaquery_edw)).

| 이름 | 기본 | 메모 |
|---|---|---|
| `EDW_QUERY` | 켬 | `0`이면 `query_edw`가 `not_configured` |
| `RDB_HOST`·`RDB_PORT`·`RDB_DATABASE`·`RDB_READ_USER`·`RDB_READ_PASSWORD` | 비움·`1433`·비움 | `required.edw`(포트는 `common.connections.rdb.port`) |
| `RDB_SQLITE` | 비움 | PC 전용 EDW 대역 파일(`valid_env/edw/edw.sqlite`, 다시 만들기 `python -m validation.e2e.edw_standin`) — 서버 설정에 있으면 실패 |
| `EDW_QUERY_TABLES_STRICT`(`search.edw_query.tables_strict`) | `false` | `true`면 `EDW_QUERY_TABLES` 목록만 허용 |
| `EDW_QUERY_TABLES`(`search.edw_query.tables`) | 비움 | 허용 `schema.table` 쉼표 목록 — 비면 모두 거부 |
| `EDW_QUERY_MAX_ROWS` | `1000` | 도구 `max_rows`의 상한 |
| `EDW_QUERY_TIMEOUT_SEC` | `20` | 넘으면 `timeout` |
| `EDW_QUERY_MAX_BYTES` | `2000000` | 응답 JSON 크기 상한 — 넘으면 끝 행부터 버리고 `truncated: true` |
| `EDW_META_DIR`(`search.edw_meta.dir`) | 비움 | `edw_meta` 데이터셋(`catalog.json`·`columns.jsonl`) 폴더 |

### 이미지 태그·호스트 경로 (compose 치환용)
| 이름 | 메모 |
|---|---|
| `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`(`required.deploy.pipeline_image`·`mcp_image`) | dev `*-runtime:<판>` · prd `*:<판>` |
| `RAG_OUT`(`required.deploy.output_root`) | 결과 폴더(컨테이너 `/app/output`) |
| `DOC_SRC`(`required.deploy.doc_src`) | 원본 문서 폴더(컨테이너 `/data/docs:ro`) |

### 원천·경로 묶음
코드 주석의 "env-guide 1-2"가 이 절이다.

| 이름 | 무엇 | 형식 |
|---|---|---|
| `PARSE_SOURCE`(`required.source.input_source`) | 이번에 읽을 원천 | 폴더 · `rdb:csv:<경로>` |
| `PG_FILTER_EXACT_MAX` | 고객 필터 정확 검색 문턱 | 고객으로 좁힌 청크가 이 수(기본 20000) 이하면 정확 검색 |
| 변경 뒤 확인 | — | `python -m common.check.checker env`(서버는 `run_tool.sh check_env`) |

### 원천 Object Storage·EDW·게시
| 이름 | 메모 |
|---|---|
| `OS_ENDPOINT`·`OS_ACCESS_KEY`·`OS_SECRET_KEY`·`OS_VERIFY_TLS` | `required.object_storage` · 사내 CA면 `OS_VERIFY_TLS=<CA 파일>`(`0`이면 검증 끔 — 경고) |
| `RDB_CONNECT_KWARGS` | EDW 연결 추가 인자(JSON — 비밀) |
| `RDB_WRITE_USER`·`RDB_WRITE_PASSWORD` | 쓰기 계정 — ParsingMeta 게시(INSERT·UPDATE)만, 파이프라인 이미지에만 |
| `PM_BUCKET`·`PM_PREFIX`(`required.source.publish_bucket`·`publish_prefix`) | 결과 게시 대상. 폴더 저장소로 먼저 시험: `PM_BUCKET=file://…`. ⚠ **첫 게시 전 EDW 표를 DBA가 한 번 만든다**: [`parsing_meta_mssql.sql`](parsing_meta_mssql.sql)(코드는 표를 만들지 않음 — 없으면 첫 INSERT에서 실패) |
| `PM_PATH_MAP` | 결과 키 앞부분 바꾸기 `이전=새`(쉼표 목록) — 문서 폴더 = `<PM_PREFIX>/<새 앞부분>/<나머지 폴더>/<원본파일명>/` · 예 `SFDC=Parsing-Result/SFDC`면 `.../SFDC/<UUID>/a.pdf` → `.../Parsing-Result/SFDC/<UUID>/a.pdf/` |
| `PM_TABLE`(`common.connections.parsing_meta.table`) | 게시할 EDW 표(기본 `AI.ParsingMeta`) |
| `EDW_CHAIN_FILE`(`ops.paths.edw_chain`) | EDW 조인 사슬 파일 — 적재와 검색 MCP가 같은 칸을 읽는다. 비우면 코드의 `resources/config/edw_chain.yaml`, 서버 사본을 쓰려면 `/etc/rag/edw_chain.yaml`. 쓰는 법: [release-and-patch §8-6](release-and-patch.md#8-6-edw-조인-사슬-파일-고쳐-쓰기서버--pl-29) |

### 새벽 배치 (systemd `data-pipeline-nightly`)
코드 주석의 "env-guide 1-3"이 이 절이다. **세 칸이 모두 있어야 돈다**(하나라도 비면 없음).

| 이름 | 뜻 |
|---|---|
| `NIGHTLY_TIME`(`ops.nightly.time`) | 시작 시각 HH:MM(서버 시간) — 타이머는 5분마다 깨우고 그 시각부터 5분 안에 `run_docs.py --start-offset 0 --skip-done` |
| `NIGHTLY_MAX_DOCS`(`ops.nightly.max_docs`) | 한 번에 처리할 새 문서 수 상한(1 이상) |
| `NIGHTLY_DEADLINE`(`ops.nightly.deadline`) | 마감 HH:MM(시작보다 이르면 다음 날, 시작보다 5분 넘게 뒤) — 지나면 새 문서를 받지 않고 받은 문서는 끝까지 |

## 2. 자원·병렬 (보통 안 건드림)

`PIPE_PROCS`(기본 `auto`)·`PIPE_WORKERS`·`VLM_CONCURRENCY`·`OCR_DPI`·`OCR_MAX_PAGES`·`MAX_FILE_MB`·`MEM_MAX_PCT`(90)·`CPU_MAX_LOAD`(0.9)·`EMBED_BATCH`·`EMBED_TIMEOUT`·`VLM_TIMEOUT` — 설명·기본값은 `settings.sample.yaml`. 자동 계산 계수와 호출 제한 시간·병렬 세부값은 `tuning` 절. 컨테이너 CPU·메모리 상한은 README §5-0 "자원".

## 3. 전체 목록과 읽는 순서

- **전체 목록은 `settings.sample.yaml`**(생성 `python -m common.config.sample` — 칸마다 설명·기본값·값·`[파라미터]`·`[비밀]`). 옛 env 이름·켜기 판정 꼴은 `--where <이름>`.
- 읽는 순서: 테스트 값 > 오버레이 설정 파일·`--set` > settings.yaml > 코드 기본값.

## 4. 확인

```bash
python -m common.check.checker env    # 빠진 필수 값·사내망 판정·경로 존재(값은 안 찍음) — 서버: run_tool.sh check_env
python -m common.check.checker ping   # LLM·VLM·EMBED 실호출 — 실패 있으면 종료 1 — 서버: run_tool.sh ping_models
ls -l ../settings.yaml                # 서버(코드 폴더에서): 주인 10001·권한 640
```

## 5. 0.1.0 → 0.2.0에서 바꿀 설정

운영 서버(0.1.0)를 0.2.0으로 올릴 때 settings.yaml에서 할 일이다. 순서는 [release-and-patch §8-3 4](release-and-patch.md#8-3-실행-순서--복사해-붙이는-명령dev-먼저-그다음-prd).

| 바뀐 것 | 할 일 |
|---|---|
| 칸 배치 — 맨 위 `required` → 역할 절 → `tuning`. 옛 배치는 시작 거부 | `python -m common.config.migrate`로 옮긴다(이미지 안에서 — §8-3 4) |
| `required.pg` 여섯 칸 필수(자동 탐지 없음) | 모두 채운다. `db_schema`는 **새 이름**(판 0002가 옛 표를 지움) |
| env로 준 값은 효과 없음(엔진·핸드오프 칸 포함) | 컨테이너에 `-e VLM_BASE_URL=…`·`OCR_DPI=…`처럼 주던 값은 settings.yaml 칸으로(`--where <이름>`으로 자리 확인) |
| 이미지 칸 `required.deploy.pipeline_image`·`mcp_image` | dev `data-pipeline-runtime:0.1.0`·`mcp-server-runtime:0.1.0` · prd `data-pipeline:0.2.0`·`mcp-server:0.2.0` |
| 새 칸 `required.deploy.pg_container`·`required.tokens.parse_mcp`·`parse_proxy`·`search.server.fulltext_secret` | 채운다(README [꼭 채울 값](../../README.md#꼭-채울-값)) |
| 새벽 배치 `ops.nightly.time`·`max_docs`·`deadline` — 셋 다 있어야 돎 | 배포 때는 비워 두고 배포 뒤 켠다(§8-4 3) |
| `parse_document` 크기 상한 칸이 `ops.runtime.parse_max_mb`(기본 100) | 옛 `ops.services.parse_mcp.max_mb`가 있으면 지우고, 100이 아닌 값은 새 칸에. 리버스 프록시 본문 상한도 늘린다(C-85) |
| `query_edw` 행 상한 기본 1000(`search.edw_query.max_rows`) | 다른 값을 쓰려면 적는다 |
| 용어집·고객 명부는 PG 마스터 표 | `migrate master load`(§8-3 5) · CSV를 고치면 다시 하고 검색 MCP 재시작 |
| 사슬 파일 칸 `ops.paths.edw_chain`(새 — 비우면 기본 파일) | 서버 EDW 이름이 다를 때만 §8-6 |
| 지운 칸(`common/config/layout.py` `REMOVED` — 예 `ops.paths.glossary_dir`·`client_roster`·`mcp_bundle`, `common.models.transport.transport`) | 남아 있어도 경고 한 줄 뒤 무시 — 지워도 되고 두어도 된다 |
