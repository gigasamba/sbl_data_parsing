# 설정(settings.yaml) — 사람이 채울 칸

설정 파일은 하나다. 전체 칸·기본값·설명은 `settings.sample.yaml`. 비밀값은 이 파일에만 두고 문서·채팅·로그에 쓰지 않는다.

| 환경 | 파일 | 권한 |
|---|---|---|
| PC | 저장소 루트 `settings.yaml` | 600 |
| 개발 서버 벌 | `/home/sbl/data_pipeline-<n>/app/settings.yaml`(컨테이너 안 `/app/settings.yaml` — 고칠 수 있음) | 640 |
| 운영 서버(개발 서버의 출시 전 시험도) | `/home/sbl/data_pipeline/app/settings.yaml`(컨테이너에는 읽기 전용 `/etc/rag/settings.yaml`) | 640 |

서버는 `host_ctl.sh init`이 sample을 복사해 둔다(없을 때만). 다른 파일을 읽히려면 env `SETTINGS_FILE`. **PC 파일을 서버로 복사하지 않는다** — PC의 `run_env: local`·`*_allow_external: true`가 서버에서 외부 모델 호출을 연다.

- **구조:** 맨 위 `required`(필수 접속·입력) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → 맨 아래 `tuning`. 같은 절·칸을 두 번 쓰면 시작 거부.
- **쓰는 법:** 기본값과 다르게 쓸 칸만 적는다. sample의 빈 칸(`pg_host:` 뒤가 빔)은 꼭 적을 값(주석의 `[필수 · 모드]`), `null`은 비워 두면 코드 기본값을 쓰는 칸이다.
- **옛 칸:** 옛 배치(최상위 `common`·`pipeline`·`mcp`)·옛 자리·지운 칸·모르는 칸이 있으면 시작하지 않고 칸 이름만 알린다 — sample과 대조해 고친다. 옛 env 이름을 env로 넘기면 무시하고 이름만 경고한다.

## 꼭 채울 칸

| 칸 | 무엇 | PC | dev | prd |
|---|---|---|---|---|
| `required.env.run_env` | 실행 환경 | `local` | `dev` | `prd` |
| `required.source.source_systems` | 파싱할 원천(쉼표) — 비우면 운영 5개 원천 | — | `DEV-<n>` | 비움 |
| `required.pg.pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password` | 검색 DB | `127.0.0.1` · `55433` | `<서버 IP>` · `5433` | `<서버 IP>` · `5433` |
| `required.pg.pg_schema` | 검색 스키마 — 비우면 `data_parsing` | ✓ | ✓ | ✓ |
| `required.models.embed_*`·`llm_*`·`vlm_*` | 모델 주소·모델·키(서버는 내부망 주소만) | ✓ | ✓ | ✓ |
| `required.edw.edw_host`·`edw_database`·`edw_read_user`·`edw_read_password` | 회사 DB(EDW) 읽기 계정 | — | ✓ | ✓ |
| `required.publish.publish_bucket`·`publish_prefix` | 게시 위치(Object Storage) | — | ✓ | ✓ |
| `required.object_storage.object_storage_endpoint`·`object_storage_access_key`·`object_storage_secret_key` | Object Storage 접속 | — | ✓ | ✓ |
| `extract.source.source_default_bucket` | 원본 버킷 | — | ✓ | ✓ |
| `required.tokens.mcp_token` | 검색 MCP 토큰(`openssl rand -hex 32`) | — | ✓ | ✓ |
| `required.tokens.fulltext_sign_key` | 원문 도구 서명 키(비우면 원문 도구 끔) | — | ✓ | ✓ |
| `required.deploy.host_docs_dir` | 서버의 원본 문서 폴더(컨테이너 `/data/docs`) | — | ✓ | ✓ |
| `required.deploy.pg_container_name` | PG 컨테이너 이름 | `pgvector` | `pgvector` | `pgvector` |
| `common.connections.redis.redis_host` | 작업 큐(Redis) 주소 — 포트는 비움(8010) | — | `<서버 IP>` | `<서버 IP>` |
| `common.connections.redis.redis_password` | Redis 비밀번호 = compose 파일 `redis`의 `REDIS_PASSWORD` | — | ✓ | ✓ |
| `search.server.mcp_bind_host` | 검색 MCP 주소(`0.0.0.0` 금지) | `127.0.0.1` | `<서버 IP>` | `<서버 IP>` |
| `search.server.mcp_port` | 검색 MCP 포트 | 예 `18769` | `8051` | `8051` |
| `transform.represent.post_steps` | 서버 값 `all` | — | `all` | `all` |
| `ops.host.container_cli` | 컨테이너 도구 | — | `docker` | `docker` |
| `ops.host.pipeline_container` | 호스트 스크립트(`run_pipeline.py`·`pipe_exec.sh`·`host_ctl.sh`)가 들어갈 파이프라인 컨테이너 — 비우면 `data-pipeline` | — | `data-pipeline-<n>` | 비움 |
| `ops.host.mcp_container`·`parse_container` | 검색 MCP·parse_document 작업 컨테이너 — 비우면 `mcp-server`·`mcp-data-parsing` | — | — | 비움 |

PC만 쓰는 칸은 아래 [PC 전용 칸](#pc-전용-칸).

PG·Redis 컨테이너와 SSH root 비밀번호는 settings.yaml이 아니라 compose 파일(`compose-dev.yml`·`compose-prd.yml`)의 `null` 칸에 서버 사본에서 적는다 — PG 계정·비밀번호와 Redis 비밀번호는 위 칸과 같은 값([dev.md A-5](dev.md#a-5-설정-채우기)).

## 파싱할 원천 — `required.source.source_systems`

- 값: `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`·`DEV-<1~99>`(쉼표 구분, 대소문자 무관 — 예 `DEV-1, DEV-2`). 원천은 EDW `AI.FileStorageMap.source_system` 칸 값이다.
- 비우면 운영 5개 원천(`DEV-<숫자>` 행은 뺌).
- `DEV-…`는 dev·local에서만 — prd에 적혀 있으면 시작하지 않는다. `DEV-<숫자>` 문서는 검색 스키마 `<기준>_dev_<숫자>`에 적재되므로 목록에 새로 넣으면 먼저 `migrate up --target search`(없으면 적재가 멈춤).
- PC 폴더 원천은 맨 위 `DEV-<숫자>/` 폴더도 원천 폴더이고 같은 목록으로 거른다.

## PC 전용 칸

PC(local)에 꼭 필요한 칸은 `run_env: local`, 모델 접속(`required.models`), PG 접속이다(예: [local.md 2](local.md#2-settingsyaml)). PC 전용 칸은 `dev` 절에 모여 있다(sample 맨 아래).

- **서버 전용 칸은 무시:** `run_env: local`은 `required.edw.edw_host`·EDW 계정, `required.object_storage.*`, 원천 버킷, `required.publish.publish_bucket`을 비우고 `[settings] local(PC) — 서버 전용 칸을 무시함(비움): …` 한 줄에 칸 이름만 찍은 뒤 시작한다. 그래서 PC는 실제 EDW·Object Storage에 닿지 않는다. 서버(dev·prd)는 이 칸들을 쓰고 `dev.local`은 읽지 않는다.
- **가짜 대상 `dev.local`**(기본값이 있어 적지 않아도 됨 — 저장소 루트 기준 상대 경로 또는 절대 경로):

  | 칸 | 기본 |
  |---|---|
  | `local_edw_sqlite_file` | 가짜 EDW(원본 목록 FileStorageMap) — 비우면 `valid_env/edw/edw_copy.sqlite`(없으면 `edw.sqlite`를 복사해 만듦) |
  | `local_publish_dir` | `valid_env/object_storage/Parsing_Result`(가짜 Object Storage — 처음 게시할 때 만듦). `<prefix>/<출처>/<원본 경로>/<파일명>_<날짜>.md`로 쓰고, 원본 목록에서는 빠진다 |
  | `local_source_dir` | `valid_env/object_storage`(파싱 원본 — `--source`·`source_input_location`이 없을 때) |
  | `local_max_new_docs_per_run` | `5`(새로 파싱할 문서 수 — `--max-new`·`max_new_docs_per_run`이 없을 때) |

  원본 폴더(`ops.paths.source_docs_dir`)·파싱 원본(`extract.source.source_input_location` — 폴더 또는 `rdb:csv:<경로>`)도 상대 경로를 받는다.
- **외부 모델:** `dev.models.<embed|llm|vlm>.*_allow_external`이 `true`이고 `run_env: local`일 때만 부른다(서버는 늘 거부 — 서버 파일에는 셋 다 `false`). 평소 `false`, 쓰는 실행 동안만 `true`. LLM·VLM을 켜면 분류(SFDC·LAS)와 그림·스캔 VLM이 외부 모델을 부른다 — 비우면 분류가 실패해 SFDC·LAS 문서는 적재되지 않는다. OpenRouter 하나로 임베딩·LLM·VLM을 모두 쓸 수 있다(같은 주소·키, 모델만 다름 — 단가표 `common/ai/llm.py` `PRICES`에 있는 모델이어야 예산 상한이 걸림).
- **하루 지출 상한:** `dev.models.guard.daily_budget_usd`(비우면 0.1달러, 장부 `output/_llm_spend/<날짜>.txt`).
- **VLM 설정은 한 벌:** VLM 엔진(`qwen_vlm`)·쪽 VLM·그림 VLM이 같은 호출과 같은 칸(`common.models.vlm.*` — 동시 수·제한 시간·재시도·`vlm_extra_request_body`, 해상도 `extract.page_render_dpi`, 쪽 상한 `transform.vlm.vlm_max_pages_per_doc`)을 쓴다. 생각(추론) 모델이면 `vlm_extra_request_body`에 생각 끄기를 넣는다(OpenRouter는 `{"reasoning": {"enabled": false}}`) — 규칙 PRD [pl-43](../prd/transform.md#pl-43).

## 새벽 배치(셋 다 있어야 돈다)

| 칸 | 꼴 |
|---|---|
| `ops.nightly.nightly_start_time` | `HH:MM` |
| `ops.nightly.nightly_max_docs` | 1 이상 정수 |
| `ops.nightly.nightly_stop_time` | `HH:MM`(시작보다 5분 넘게 뒤) |

## 한 번만 다른 값 — `--set 이름=값`

```bash
python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/try --set SOURCE_SYSTEMS=DEV-1,DEV-2 parse --source /data/docs --src /app/output/try/prepared
```
- 이름은 칸의 옛 env 이름이다. 찾기: `python -m common.config.sample --where <이름>`(예 `PG_SCHEMA` → `required.pg.pg_schema`).
- 여러 번 줄 수 있고 같은 이름은 뒤 값이 이긴다. 하위 명령 앞뒤 어디든 된다.
- 받는 진입점: `pipeline.cli` · `pipeline.extract.candidate_pick` · `pipeline.extract.candidate_ready` · `pipeline.transform.structure.gold_bundle` · `pipeline.load.pgvector_load` · `pipeline.load.publish_parse_result` · `mcp_server.main` · `mcp_server.cli.search_ask`.
- 비밀 칸(`PG_PASSWORD` 등)과 호스트 칸(`DOC_SRC` 등)은 거부된다(종료 2).

자주 쓰는 이름:

| 이름 | 칸 |
|---|---|
| `PIPE_OUT_ROOT` | `ops.paths.container_output_dir`(결과 폴더) |
| `SOURCE_SYSTEMS` | `required.source.source_systems`(원천 — 쉼표) |
| `PARSE_SOURCE` | `extract.source.source_input_location`(읽을 문서 폴더 또는 `rdb:csv:<경로>`) |
| `DOC_DIR` | `ops.paths.source_docs_dir`(원본 폴더) |
| `DOC_DIR_PREPARED` | `ops.paths.prepared_docs_dir`(준비된 파일 폴더) |
| `PARSE_MAX_NEW` | `extract.max_new_docs_per_run`(새 문서 수 상한) |
| `PG_SCHEMA` | `required.pg.pg_schema`(검색 스키마) |
| `MCP_PORT` · `MCP_HOST` | `search.server.mcp_port` · `mcp_bind_host` |
| `EMBED_CACHE` | `transform.structure.embed_cache_file`(임베딩 캐시) |
| `EMBED_ALLOW_EXTERNAL` | `dev.models.embed.embed_allow_external`(PC만) |
| `RDB_SQLITE` | `dev.local.local_edw_sqlite_file`(PC 가짜 EDW) |

서버 경로 칸은 컨테이너 안 절대 경로로 적고, 쓰는 자리는 `/app/output/…` 아래로 둔다.

## 확인
```bash
python -m pipeline.config                    # 끝까지 읽힘(모르는 칸·지운 칸이면 칸 이름을 찍고 멈춤)
python -m common.check.checker env           # 빠진 필수 값·경로
python -m common.check.checker ping          # 모델 연결
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK   # 서버 호스트
```
PC는 `.venv/bin/python`으로, 개발 서버는 벌 컨테이너 안에서, 운영 서버는 `bash deploy/host/scripts/pipe_exec.sh check_env`.
