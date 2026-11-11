# 설정(settings.yaml) — 사람이 채울 칸

설정 파일은 하나다. 전체 칸·기본값·설명은 `settings.sample.yaml`. 비밀값은 이 파일에만 두고 문서·채팅·로그에 쓰지 않는다.

| 환경 | 파일 | 권한 |
|---|---|---|
| PC | 저장소 루트 `settings.yaml` | 600 |
| 개발 서버 벌 | `/home/sbl/data_pipeline-<n>/app/settings.yaml`(컨테이너 안 `/app/settings.yaml` — 고칠 수 있음) | 640 |
| 운영 서버(개발 서버의 출시 전 시험도) | `/home/sbl/data_pipeline/app/settings.yaml`(컨테이너에는 읽기 전용 `/etc/rag/settings.yaml`) | 640 |

서버는 `host_ctl.sh init`이 sample을 복사해 둔다(없을 때만). PC 파일을 서버로 복사하지 않는다.

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
| `common.connections.redis.redis_password` | Redis 비밀번호 = `.env`의 `REDIS_PASSWORD` | — | ✓ | ✓ |
| `search.server.mcp_bind_host` | 검색 MCP 주소(`0.0.0.0` 금지) | `127.0.0.1` | `<서버 IP>` | `<서버 IP>` |
| `search.server.mcp_port` | 검색 MCP 포트 | 예 `18769` | `8051` | `8051` |
| `transform.represent.post_steps` | 서버 값 `all` | — | `all` | `all` |
| `ops.host.container_cli` | 컨테이너 도구 | — | `docker` | `docker` |
| `ops.host.pipeline_container` | 호스트 스크립트(`run_pipeline.py`·`pipe_exec.sh`·`host_ctl.sh`)가 들어갈 파이프라인 컨테이너 — 비우면 `data-pipeline` | — | `data-pipeline-<n>` | 비움 |
| `ops.host.mcp_container`·`parse_container` | 검색 MCP·parse_document 작업 컨테이너 — 비우면 `mcp-server`·`mcp-data-parsing` | — | — | 비움 |

PC만: `dev.models.<embed|llm|vlm>.*_allow_external`(외부 모델 허용 — 평소 `false`) · `dev.models.guard.daily_budget_usd`(하루 지출 상한). 서버 파일에는 `dev` 절의 외부 허용을 켜 두지 않는다.

`.env`(PG·Redis를 띄우는 `app` 폴더 맨 위 — 개발 서버는 `data_pipeline/app`, 600): `PG_USER`·`PG_DB`·`PG_PASSWORD`·`REDIS_PASSWORD` — settings.yaml과 같은 값. `host_ctl.sh check` 첫 단계가 대조한다.

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
