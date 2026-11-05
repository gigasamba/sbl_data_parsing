# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱하고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 개발은 macOS·Windows PC에서 하고, 실행은 내부망(폐쇄망) RHEL 서버의 Docker/podman 이미지 2개로 한다. 기능 요건은 [docs/PRD.md](docs/PRD.md), 문서 지도·용어집은 [docs/INDEX.md](docs/INDEX.md), 개발 규칙은 [CLAUDE.md](CLAUDE.md).

### 0. 읽기 전에 — 꼭 알아 둘 것

> **⚠️ 0.1.0 DB에 `migrate up`을 그냥 하지 않는다.** 마이그레이션 `0002_search`는 0.1.0이 만든 옛 검색 표를 **지운다**. 운영 DB는 새 `required.pg.pg_schema`를 정하고 `pg_dump`로 백업한 뒤 올린다(release-and-patch §8-3).
>
> **⚠️ `docker compose`·`podman compose`를 직접 부르지 않는다.** 서버 컨테이너는 늘 `bash deploy/host/scripts/host_ctl.sh …`로 다룬다(§5-3 ①).
>
> **⚠️ 실제 값(비밀번호·키·토큰·서버 주소)은 문서·채팅·커밋에 쓰지 않는다.** 이 README의 예시 값은 모두 가짜다.
>
> **Windows PC는 WSL(리눅스)에서만 쓴다.** 명령은 모두 `.venv/bin/…` 꼴이다.

**용어**

| 말 | 뜻 |
|---|---|
| 원천 | 문서가 온 시스템 — `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`. 검색할 때는 원천을 꼭 하나 고른다 |
| 대표 결과(silver) | 문서 하나를 여러 엔진으로 파싱한 뒤 고른 결과 한 벌(`.md`·`.json`) |
| 번들(bundle) | 구조화 결과 폴더(`docs.jsonl`·`chunks.jsonl`·`vectors.npy`·`meta.json`) — 적재의 입력 |
| 적재(gold) | 번들을 PostgreSQL(pgvector)에 넣는 일 |
| 마스터 표 | 용어집·고객 명부 표(`<스키마>_master`) — 원본은 git의 `resources/vocab/glossary/*.csv` |
| 실행 이미지(`*-runtime`) | 코드가 없는 이미지 — 개발 서버는 코드 폴더를 붙여 쓴다 |
| 루트 · 코드 폴더 | 루트 = 서버 아무 자리의 폴더 하나(예 `/home/dev/` — 판마다 새로). 코드 폴더 = 그 안에 코드 zip을 푼 폴더(`sbl_data_parsing-<판>`) |
| 핑거프린트 | 결과를 다시 쓸지 정하는 값 — 바뀌면 서버가 문서를 다시 처리한다 |
| `$DOCKER` | 컨테이너 명령 — 서버는 `podman`(root 셸). 셸에서 `export DOCKER=podman` |

**목차** — [1. 한눈에 보기](#1-한눈에-보기) · [2. 폴더 구조](#2-폴더-구조) · [3. 설정](#3-설정) · [4. PC에서 실행하기](#4-pc에서-실행하기) · [5. 서버(내부망)에 배포하고 실행하기](#5-서버내부망에-배포하고-실행하기) · [6. 꼭 지킬 것](#6-꼭-지킬-것) · [7. 문서](#7-문서)

---

## 1. 한눈에 보기

### 1-1. 처리 흐름

```
원천 문서(폴더 · rdb:csv 목록)
   │  ① parse     중복 제거 → 쪽 방향 보정 → 엔진별 파싱 → 대표 결과(문서마다 하나)     ┐
   │  ② publish   대표 결과를 Object Storage에 올리고 회사 DB(EDW)에 메타데이터 기록     │
   │  ③ (원본 삭제 — 게시가 성공한 문서만)                                            │ data-pipeline 이미지
   │  ④ structure 청킹 · 임베딩 → 번들                                                │
   │  ⑤ load      번들 → PostgreSQL(pgvector) 적재                                    ┘
   ▼
검색 MCP 서버 — 도구 6개: search · query_edw · parse_document · edw_meta ·              mcp-server 이미지
                          list_doc_fulltext · get_doc_fulltext
```

서버에서는 `run_pipeline.py`가 문서마다 이 순서로 흘려 보낸다. DAG 엔진은 없다. MCP 도구 6개의 이름과 입출력은 외부 클라이언트와의 계약이다([mcp-guide](docs/operations/mcp-guide.md)).

### 1-2. 실행 단위

| 모듈 | 하는 일 | 진입점 | 결과 |
|---|---|---|---|
| **parse** | 원천 읽기 · 중복 제거 · 준비 · 엔진별 파싱 + 대표 결과 | `python -m pipeline.cli parse` | `<결과 폴더>/parse/_rep/`(끝나면 `_DONE.json`) |
| **publish** | Object Storage 업로드 + EDW 메타데이터 | `python -m pipeline.load.publish_parse_result` | (운영 시스템에 기록) |
| **structure** | 청킹 · 임베딩 → 번들 | `python -m pipeline.transform.structure.gold_bundle` | 번들 폴더 |
| **load** | 번들 → pgvector | `python -m pipeline.load.pgvector_load` | (PostgreSQL 안) |

`run_pipeline` 종료 코드: 0 끝 · 1 실패 문서 있음 · 2 설정 문제 · 75 마감 도달·다른 run_pipeline 실행 중.

### 1-3. 서버 이미지 2개와 실행 모드

| 이미지 | 역할 | 상주 컨테이너 |
|---|---|---|
| `data-pipeline` | parse · publish · structure · load | 일괄 `data-pipeline`(일 없이 떠 있음 — `run_pipeline.py`·`pipe_exec.sh`가 exec) · `parse_document` 전용 `mcp-data-parsing` |
| `mcp-server` | 검색 MCP | `mcp-server` |

버전은 저장소 루트 `VERSION` 하나이고 두 이미지가 함께 쓴다(태그 `data-pipeline:<버전>` — 규칙: [release-and-patch §4](docs/operations/release-and-patch.md#4-버전)).

<a id="실행-모드"></a>
**실행 모드(`required.env.run_env`)마다 컨테이너를 띄우는 법이 다르다.** 이미지는 모두 `deploy/docker/Dockerfile` 한 파일에서 나온다 — 공통 `base` 단계(Python + `requirements-core.txt`) 위에 검색 MCP는 `mcp-runtime`, 파이프라인은 `parse-deps`(`requirements-image.txt` + LibreOffice) → `pipeline-runtime`(+ OCR 모델)을 쌓은 것이 **실행 이미지**(코드 없음)이고, 거기에 코드를 COPY한 것이 **코드가 든 이미지**다.

| | local(PC) | dev(개발 서버) | prd(운영 서버) |
|---|---|---|---|
| 이미지(태그 꼴) | 없음 — Python으로 직접(§4). 이미지 시험만 코드가 든 이미지 `data-pipeline:<시험 태그>`·`mcp-server:<시험 태그>` | 실행 이미지 `data-pipeline-runtime:<이미지 판>`·`mcp-server-runtime:<이미지 판>` | 코드가 든 이미지 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>` |
| 코드가 오는 곳 | 저장소 체크아웃 그대로 · 시험 이미지는 빌드 때 COPY(Dockerfile 타깃 `pipeline`·`mcp`) | 루트에 푼 코드 폴더 `sbl_data_parsing-<판>`(코드 git zip)을 컨테이너 `/app/deploy`에 읽기 전용(`:ro,z`)으로 붙임 | 이미지 안(굽기 때 COPY) — 붙이지 않음. 함께 오는 코드 묶음은 호스트 스크립트(`deploy/host/`)용 |
| 만드는 법 | `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh`(mcp는 `IMAGE_TARGET=mcp TAG=mcp-server:<시험 태그>`) | PC: `BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`(+ `mcp-runtime` — 이 커밋 코드를 붙여 selftest 판정) → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) → 개발 서버 `load.sh <이미지 판>`(§5-2). 의존성이 같으면 다시 만들지 않는다 | 개발 서버의 시험한 코드 폴더에서 `bash deploy/release/bake_prod_image.sh <이미지 판>` — 그 실행 이미지 위에 코드만 COPY(`deploy/docker/Dockerfile.bake`, 네트워크 없음) → 운영 서버 `load.sh <VERSION>`([release-and-patch §1-2](docs/operations/release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)) |
| 띄우는 법 | `.venv/bin/python -m mcp_server.main` 등(§4-4·§4-5) · 이미지 시험 `bash valid_env/docker/smoke_test.sh`(`valid_env/docker/compose.test.yml` — §4-7) | 코드 폴더에서 `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp` — 이미지가 `*-runtime:`이면 `host_ctl.sh`가 자기 코드 폴더를 `CODE_DIR`로 잡아 `compose.code*.yml`을 더한다. 시작 스크립트 `runtime_entry.sh`가 마운트·의존성 지문을 확인하고 코드의 `deploy/docker/entrypoint.sh`로 넘긴다 | 같은 `host_ctl.sh up -d …` — 이미지가 `*-runtime`이 아니므로 마운트 없이 이미지 안 `entrypoint.sh`로 뜬다. 셸·systemd에 `CODE_DIR`을 두지 않는다 |
| settings.yaml 이미지 칸(`required.deploy.pipeline_image`·`mcp_image`) | 쓰지 않음(이미지 시험은 셸 변수 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`) | `data-pipeline-runtime:<이미지 판>` · `mcp-server-runtime:<이미지 판>` | `data-pipeline:<VERSION>` · `mcp-server:<VERSION>` |
| `run_env` | `local`(저장소 루트 `settings.yaml`) | `dev` | `prd` |

**실행 이미지 판 고르기(dev·굽기).** 실행 이미지 판은 코드 판과 다를 수 있다. **이미지 판의 `BUILD.txt`에 적힌 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판**을 쓴다(값 = `requirements-core.txt`·`requirements-image.txt`의 지문, `bash deploy/release/deps_hash.sh`). 다르면 컨테이너가 `의존성 지문이 다름`으로 멈추고(종료 2) `bake_prod_image.sh`도 멈춘다 — 같은 값인 판이 없으면 새 실행 이미지가 필요하다([release-and-patch §5](docs/operations/release-and-patch.md#5-새-이미지-버전이-필요할-때)).

```bash
cat deploy/docker/DEPS_HASH                                                   # 코드 폴더에서 — 코드가 요구하는 지문
grep -H DEPS_HASH ../../sbl_images-main/*/BUILD.txt                           # 이미지 판마다 지문 — 같은 값인 판을 load.sh <판>
$DOCKER run --rm --entrypoint cat data-pipeline-runtime:<판> /app/docker/deps_hash   # 이미 불러온 이미지의 지문
```

### 1-4. DB — Alembic 마이그레이션

pgvector의 표는 코드가 실행 중에 만들지 않는다. 모두 Alembic 마이그레이션(`common/store/db/migrations/versions/`)으로 만들고, 명령은 `dbtool`(PC: `python -m common.store.db.dbtool`, 서버: `bash deploy/host/scripts/pipe_exec.sh migrate`) 하나다.

| 갈래(`--target`) | 스키마 | 끝 판 |
|---|---|---|
| `search` | 기준 스키마(`required.pg.pg_schema`) + 원천 스키마 5벌 `<기준>_{sfdc,crms,las,faq,other}` | `0005_search`(0001→0005 차례로) |
| `applog` | `applog`(고정 이름) | `0002_applog`(0001→0002 — 0002는 영구 건너뜀 표 `skip_doc_info`) |
| `master` | `<기준>_master` | `0001_master` — 채우기는 `master load` |

| 명령 | 하는 일 |
|---|---|
| `up --target search\|applog\|master\|all` | 끝 판까지 실행 |
| `current --target …` | 지금 DB 판과 코드의 끝 판 |
| `check --target …` | `current`와 같고, 끝 판이 아니면 종료 1(읽기만) |
| `master load [--dir <폴더>]` | 마스터 표를 CSV(기본 `resources/vocab/glossary/`)로 통째로 바꿈 |

처음 설치(PC §4-4 ④, 서버 §5-0 6번) · 마이그레이션이 바뀐 릴리스(적재 전에 `up`) · 새 검색 스키마(임베딩 차원이 바뀜 — 새 `db_schema`에 `up --target all --schema <새 스키마> --dim <차원>`)일 때 실행한다. 자동 동작·오류 분기는 [release-and-patch §5-5](docs/operations/release-and-patch.md#5-5-db-버전-관리--migrate).

---

## 2. 폴더 구조

폴더마다 두는 것과 모듈 경계는 [CLAUDE.md §1](CLAUDE.md) 표에 있다(`python -m common.check.check_modules`가 경계를 확인).

---

## 3. 설정

모든 설정 값과 비밀값은 **settings.yaml 한 파일**에 둔다. 코드는 환경변수에서 설정을 읽지 않는다(옛 env 이름을 넘기면 무시하고 이름만 경고).

| 항목 | 내용 |
|---|---|
| 위치 | PC: 저장소 루트 `settings.yaml`(git 제외, 권한 600) · 서버: `<루트>/settings.yaml`(루트 = 코드 폴더의 부모, 주인 UID 10001, 권한 640) · 다른 파일은 env `SETTINGS_FILE` |
| 구조 | 맨 위 `required`(필수 접속·입력) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → 맨 아래 `tuning`. 같은 절·칸을 두 번 쓰면 시작 거부. 칸 자리 찾기: `python -m common.config.sample --where <옛 env 이름>`. 칸 설명·기본값은 [settings.sample.yaml](settings.sample.yaml) |
| 쓰는 법 | **기본값과 다르게 쓸 칸만** 적는다. 비운 칸은 코드 기본값 |
| 필수 | `required.env.run_env` — `local`(PC) · `dev` · `prd`(서버 — 외부 모델 호출과 가짜 LLM을 거부하고, 설정 파일을 못 읽으면 시작하지 않는다) |
| 칸별 안내 | [docs/operations/env-guide.md](docs/operations/env-guide.md) |
| 서버용 파일 | git에 올리지 않는다. `settings.sample.yaml`을 복사해 `required`를 채운다(§5-3 ② "꼭 채울 값"). **PC 파일을 그대로 복사하지 않는다** — PC의 `run_env: local`·`allow_external: true`가 서버에서 외부 모델 호출을 연다 |

**실행할 때 값을 넘기는 방법 3가지**

| 방법 | 언제 | 받는 명령 |
|---|---|---|
| **A. settings.yaml에 적기** | 계속 쓸 값 | 모든 명령 |
| **B. 명령 인자 `--set 이름=값`** | 이번 실행에만(이름은 옛 env 이름). 비밀·호스트 칸은 거부 | `pipeline.cli`·`gold_bundle`·`pgvector_load`·`publish_parse_result` 등 파이프라인 진입점 |
| **C. 오버레이 설정 파일**(PC 전용) | `--set`을 받지 않는 명령 | `mcp_server.main`·`mcp_server.cli.search_ask` — `SETTINGS_FILE=$(python -m common.config.overrides 이름=값 …)` |

---

## 4. PC에서 실행하기

앱 컨테이너 없이 Python으로 직접 실행한다(Docker는 전용 pgvector만 — 이미지 시험은 §4-7, 모드별 차이는 [§1-3](#실행-모드)). 순서는 서버의 처리 순서와 같다.

```
4-1 준비(처음 한 번) → 4-2 settings.yaml → 4-3 점검 → 4-4 파이프라인(①~⑥) → 4-5 MCP 서버 → 4-6 검증 페이지
```

### 4-1. 준비(처음 한 번)

```bash
# Python 3.12 가상환경 — 서버 이미지와 같은 패키지 + PC 개발 도구(ruff, mypy, pytest)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt
git config core.hooksPath .githooks      # 커밋·push 때 점검 자동 실행(CLAUDE.md §5-2)

# 전용 pgvector(PG 16 + pgvector) — 처음만 run, 이후 docker start sbl-mcp-pg / docker stop sbl-mcp-pg
docker run -d --name sbl-mcp-pg -p 127.0.0.1:55433:5432 -v sbl_mcp_pgdata:/var/lib/postgresql/data \
  -e POSTGRES_DB=rag -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16
```

- 작업 폴더(git worktree)에는 `settings.yaml`이 없다. 거기서 점검·시험을 돌릴 때는 `export RUN_ENV=local`을 먼저 한다 — 없으면 실행 환경을 읽지 못해 결과 폴더 `output/`이 저장소 한 단계 위에 생긴다.

### 4-2. settings.yaml 작성

저장소 루트에 `settings.yaml`을 만들고 `chmod 600`한다(방법 A 예시):

```yaml
required:
  env: {run_env: local}
  pg: {pg_host: 127.0.0.1, pg_port: 55433, pg_database: rag, pg_user: rag, pg_password: <비밀번호>, pg_schema: demo}   # 적재·검색할 스키마
  models:
    # ---- 임베딩 모델 ----
    embed_base_url: <OpenAI 호환 주소>
    embed_api_key: <키>
    embed_model: <임베딩 모델>
    # ---- LLM·VLM(쓸 때만) ----
    llm_base_url: <주소>
    llm_model: <모델>
    vlm_base_url: <주소>
    vlm_model: <모델>
ops:
  paths: {container_output_dir: output/demo}     # 파이프라인 결과 폴더
search:
  server: {mcp_bind_host: 127.0.0.1, mcp_port: 18769}
dev:                                             # PC 전용 칸(RUN_ENV=local) — 서버 settings.yaml에는 두지 않는다
  models:
    embed: {embed_allow_external: false}         # 평소 false — 임베딩이 필요한 실행 동안만 true
    guard:
      daily_budget_usd: 0.1                      # 외부 모델 하루 지출 상한($) — 비우면 0.1. 장부 output/_llm_spend/<날짜>.txt
  search_ui: {search_ui_mcp_url: "http://127.0.0.1:18769/mcp", search_ui_port: 8791}   # 검증 페이지(§4-6)·점검 도구가 붙을 주소
tuning:
  ops:
    runtime: {max_cpu_load: 5}                   # 부하가 높은 PC라면(기본 0.9에서는 계속 대기함)
```

- `settings.sample.yaml`을 그대로 복사해 시작해도 된다 — **빈 칸**(`pg_host:` 뒤가 비어 있음)은 꼭 적을 값(주석의 `[필수 · 모드]`와 예), **`null`**은 비워 두면 코드 기본값을 쓰는 칸이다. **PC(local)에 꼭 필요한 칸은 `run_env: local`과 모델 접속(`embed_base_url`·`embed_model`·`llm_base_url`·`llm_model`·`vlm_base_url`·`vlm_model`)뿐이다.** PG는 접속 칸을 채우면 그 PG, 모두 비우면 SQLite 대역을 쓴다(`pg_schema`는 비우면 `data_parsing`). EDW·Object Storage·토큰·배포 칸은 PC에서 채우지 않는다.
- 옛 배치(최상위 `common`·`pipeline`·`mcp`)·옛 자리·지운 칸·모르는 칸이 있으면 시작하지 않고 그 칸 이름만 알린다 — `settings.sample.yaml`과 대조해 고친다(자리 찾기 `python -m common.config.sample --where <이름>`).
- PC 전용 칸(외부 모델 허용·지출 상한·단가, 로컬 대체 DB, 시험 하네스)은 `dev` 절에 모여 있다(sample 맨 아래).
- **외부 임베딩은 `allow_external: true`이고 `run_env: local`일 때만** 호출된다(서버 dev·prd는 늘 거부).
- **LLM·VLM도 같다:** `required.models`의 `llm_*`·`vlm_*`(주소·모델·키)를 채우고 `dev.models.llm.llm_allow_external`·`dev.models.vlm.vlm_allow_external`을 `true`로 두면 PC에서 분류(SFDC·LAS)와 그림·스캔 쪽 VLM이 외부 모델을 부른다(`run_env: local`일 때만). 비우면 분류가 실패해 SFDC·LAS 문서는 적재되지 않는다. OpenRouter 하나로 임베딩·LLM·VLM을 모두 쓸 수 있다(같은 주소·키, 모델만 다름 — 단가표 `common/ai/llm.py` `PRICES`에 있는 모델이어야 예산 상한이 걸림).
- **VLM 설정은 한 벌:** 스캔·이미지 문서의 VLM 엔진(`qwen_vlm`)·쪽 VLM·그림 VLM이 같은 호출과 같은 칸(`common.models.vlm.*` — 동시 수·제한 시간·재시도·`vlm_extra_request_body`, 해상도 `extract.page_render_dpi` 150, 쪽 상한 `transform.vlm.vlm_max_pages_per_doc`)을 쓴다. 생각(추론) 모델이면 `common.models.vlm.vlm_extra_request_body`에 생각 끄기를 넣는다(OpenRouter는 `{"reasoning": {"enabled": false}}`) — 칸 설명은 [env-guide §2](docs/operations/env-guide.md), 규칙은 PRD [pl-43](docs/prd/transform.md#pl-43).
- **내부망 서버(dev·prd)에서 시험·운영할 때는 세 칸 `embed_allow_external`·`llm_allow_external`·`vlm_allow_external`을 모두 `false`(0)로 둔다.** 서버는 `run_env`가 dev·prd라 켜 두어도 외부 호출을 거부하지만, 서버 settings.yaml에는 외부 허용을 남기지 않는다.
- **게시(silver)·EDW·원본 — PC는 가짜 대상만 쓴다.** 값은 `dev.local` 묶음에 기본값으로 들어 있어 적지 않아도 된다(바꿀 때만 — 저장소 루트 기준 상대 경로 또는 절대 경로):
  ```yaml
  dev:
    local:
      local_edw_sqlite_file: null                          # 가짜 EDW(ParsingMeta 포함) — 비우면 valid_env/edw/edw_copy.sqlite(없으면 edw.sqlite를 복사해 만듦)
      local_publish_dir: valid_env/object_storage/Parsing_Result   # 게시 폴더(가짜 Object Storage) — 처음 게시할 때 만듦
      local_source_dir: valid_env/object_storage           # 파싱 원본 — --source·source_input_location이 없을 때
      local_max_new_docs_per_run: 5                        # 한 번에 새로 파싱할 문서 수 — --max-new·max_new_docs_per_run이 없을 때
  ```
  게시 폴더에 `<prefix>/<출처>/<원본 경로>/<파일명>_<날짜>.md`로 쓴다(게시 폴더는 원본 목록에서 빠진다). 원본 폴더(`ops.paths.source_docs_dir`)·파싱 원본(`extract.source.source_input_location` — 폴더 또는 `rdb:csv:<경로>`)·PG 대체 폴더(`dev.pg_standin.pg_standin_dir`)도 상대 경로를 받는다.
  `run_env: local`은 서버 전용 칸(`required.edw.edw_host`·EDW 계정, `required.object_storage.*`, 원천 버킷, `required.publish.publish_bucket`)을 **무시한다** — 적혀 있어도 비우고 `[settings] local(PC) — 서버 전용 칸을 무시함(비움): …` 한 줄에 칸 이름만 찍은 뒤 시작한다. 그래서 PC는 실제 EDW·Object Storage에 닿지 않는다. 서버(dev·prd)는 이 칸들을 쓰고 `dev.local`은 읽지 않는다.
- **PG 접속 칸을 채운 PC는 파싱 전에 한 번 `.venv/bin/python -m common.store.db.dbtool up --target applog`** — 받기가 DRM·암호·지원 안 함 문서를 영구 건너뜀 표 `applog.skip_doc_info`에 쓰는데, 표가 없으면 그 문서에서 파싱이 멈춘다(PG를 비운 PC는 SQLite 대역이 표를 만든다). ④의 `up --target all`에도 들어 있다.
- PG 접속 칸(`required.pg`의 `pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password` 다섯 칸)은 **모두 채우거나 모두 비운다.** 일부만 채우면 채울 자리를 알려 주고 멈춘다. PC에서 host·password가 둘 다 비면 SQLite 대역(`output/pg_standin/`)으로 돌고 첫 줄에 `WARNING: PG 접속 정보 없음`을 찍는다(서버는 멈춤).

### 4-3. 점검

```bash
export PYTHONPATH=$PWD                                   # 명령은 저장소 루트에서
.venv/bin/python -m pipeline.config                      # 어느 settings.yaml을 읽는지와 요약(비밀은 가림)
.venv/bin/python -m common.check.check_modules           # "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check        # "빠진 키 0개"
.venv/bin/python -m pipeline.cli selftest                # 서버 배포 테스트 — 실패 0(기준선 PRD e2-02)
.venv/bin/python -m pytest -q tests/                      # 전체 테스트 — 실패 0
```

알려진 실패 목록(`deploy/release/known_fail.txt`, `tests/conftest.py` `GENERAL_KNOWN_FAIL`)은 둘 다 비어 있다.

### 4-4. 파이프라인 실행 — 문서 몇 건(①~⑥)

먼저 `settings.yaml`의 `dev.models.embed.embed_allow_external`을 `true`로 바꾼다. 끝나면 ⑥에서 되돌린다.

**① 테스트 문서 고르기**

```bash
for s in SFDC CRMS; do mkdir -p output/demo/src/$s; for d in $(ls -d valid_env/object_storage/$s/*/ | head -2); do cp -r "$d" output/demo/src/$s/; done; done
SRC=output/demo/src     # <원천>/<uuid>/<파일> 그대로 — 파싱이 상대 키로 원천을 알아본다
```

- 문서는 `valid_env/object_storage/<원천>/<uuid>/<파일>`에 있다(목록·목적: [valid_env/object_storage/test_doc_purpose.md](valid_env/object_storage/test_doc_purpose.md)). `valid_env`에는 쓰지 않는다 — 예외 둘: 가짜 EDW 사본 `valid_env/edw/edw_copy.sqlite`와 게시 폴더 `valid_env/object_storage/Parsing_Result/`(둘 다 PC 실행이 만들고 git이 무시함). 그 밖의 결과는 모두 `ops.paths.container_output_dir` 아래.

**② 파싱 — 문서 → 대표 결과**

```bash
cp valid_env/edw/edw.sqlite output/demo/edw.sqlite   # EDW 대역 사본 — 파싱이 ParsingMeta를 읽고 씀
.venv/bin/python -m pipeline.cli --set RDB_SQLITE=output/demo/edw.sqlite parse --source $SRC --src output/demo/prepared
```

- PG 접속 칸을 채웠다면 이 단계 전에 `dbtool up --target applog`를 한 번(§4-2 — 영구 건너뜀 표).
- `--source`는 원본 폴더, `--src`는 준비된 파일이 놓이는 곳(`--src`만 주면 준비된 폴더로 보고 가져오기·중복 제거를 건너뜀).
- EDW(`AI.ParsingMeta`)를 못 읽으면 서버는 종료 4, PC(local)는 받은 목록 그대로. PC는 `--set RDB_SQLITE`를 빼면 `valid_env/edw/edw_copy.sqlite`를 쓴다(위처럼 주면 그 사본).
- 돌 문서가 없으면 `[parse] 이번 실행 0건 …` 한 줄을 남기고 종료 0.
- 결과: `output/demo/parse/<엔진>/`, `output/demo/parse/_rep/`(문서마다 하나 + `_DONE.json`).

**③ 구조화·임베딩 — 대표 결과 → 번들**

구조화의 고객 판별이 마스터 표를 읽으므로, 새 스키마라면 먼저 마스터 표만 만들어 채운다:
```bash
.venv/bin/python -m common.store.db.dbtool up --target master --schema demo
.venv/bin/python -m common.store.db.dbtool master load --schema demo
.venv/bin/python -m pipeline.transform.structure.gold_bundle \
  --parse-dir output/demo/parse --src output/demo/prepared --embed api --out output/demo/bundle
```

- 결과: `output/demo/bundle/`(docs.jsonl · chunks.jsonl · vectors.npy · meta.json). 같은 청크는 임베딩 캐시(`output/edw/embed_cache.sqlite`)로 다시 호출하지 않는다.

**④ DB 표 — 마이그레이션(스키마마다 처음 한 번)**

```bash
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle output/demo/bundle --create-extension
.venv/bin/python -m common.store.db.dbtool master load --schema demo
.venv/bin/python -m common.store.db.dbtool current --target all    # 기대: search 0005_search · applog 0002_applog · master 0001_master
.venv/bin/python -m common.store.db.dbtool check --target all      # 기대: 갈래마다 판 끝, 종료 코드 0
```

- 초기화 순서: `dbtool up`(search·applog·master) → `dbtool master load` → 파싱·구조화·적재. 서버는 마스터 표가 비었으면 구조화·검색이 시작하지 않는다. `resources/vocab/glossary/*.csv`를 고치면 `master load`를 다시 돌린다(이미 적재한 문서는 자동으로 다시 처리하지 않음).
- `--bundle`은 벡터 차원을 `meta.json`에서 읽으려고 준다(또는 `--dim`). `--create-extension`은 새 PG일 때만.

**⑤ 적재 — 번들 → pgvector**

```bash
.venv/bin/python -m pipeline.load.pgvector_load load --bundle output/demo/bundle
```

- 이미 적재한 문서를 다시 넣을 때는 `--replace`. 적재는 이번 묶음에 없는 문서를 지우지 않는다.

**(선택) MCP 없이 검색만**

```bash
.venv/bin/python -m mcp_server.cli.search_ask ask --source CRMS --k 3 --q "<질문>"   # 원천 하나 필수(SFDC·CRMS·LAS·FAQ·Other)
```

**⑥ 정리** — 4-5에서 MCP까지 확인한 뒤 `*_allow_external`을 `false`로 되돌린다.

<details>
<summary><b>방법 B — settings.yaml을 바꾸지 않고 <code>--set</code>으로 넘기기</b></summary>

```bash
O=$PWD/output/demo; SRC=$O/src     # ①과 같은 문서 폴더
SETS=(--set PIPE_OUT_ROOT=$O --set PG_SCHEMA=demo --set EMBED_ALLOW_EXTERNAL=1
      --set LLM_BUDGET_USD=0.10 --set LLM_SPEND_FILE=$O/spend.json)

cp valid_env/edw/edw.sqlite $O/edw.sqlite
.venv/bin/python -m pipeline.cli "${SETS[@]}" --set RDB_SQLITE=$O/edw.sqlite parse --source $SRC --src $O/prepared
.venv/bin/python -m common.store.db.dbtool up --target master --schema demo
.venv/bin/python -m common.store.db.dbtool master load --schema demo
.venv/bin/python -m pipeline.transform.structure.gold_bundle "${SETS[@]}" \
    --parse-dir $O/parse --src $O/prepared --embed api --out $O/bundle
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle --create-extension
.venv/bin/python -m pipeline.load.pgvector_load "${SETS[@]}" load --bundle $O/bundle

# ask·MCP는 --set을 받지 않으므로 오버레이 설정 파일(방법 C)로 같은 값을 넘긴다
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo EMBED_ALLOW_EXTERNAL=1 \
     LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json MCP_PORT=18769)
SETTINGS_FILE=$SF .venv/bin/python -m mcp_server.cli.search_ask ask --source CRMS --k 3 --q "<질문>"
SETTINGS_FILE=$SF nohup .venv/bin/python -m mcp_server.main > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
```
실제 임베딩 호출을 확인하려면 `--set EMBED_CACHE=<빈 sqlite 경로>`를 더한다.
</details>

### 4-5. 검색 MCP 서버

```bash
nohup .venv/bin/python -m mcp_server.main > output/demo/mcp.log 2>&1 & echo $! > output/demo/mcp.pid
curl -s http://127.0.0.1:18769/health        # {"ok":true,"ready":true,"store":"pgvector",…}
kill $(cat output/demo/mcp.pid)              # 끄기 — PID로만(pkill -f 금지)
```

- 엔드포인트 `http://127.0.0.1:18769/mcp`(streamable HTTP) — 도구 입출력: [mcp-guide](docs/operations/mcp-guide.md).
- 밖에서 붙어 보기: `.venv/bin/python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:18769/mcp --source CRMS --q "<질문>"` — 도구 목록과 search 근거 칸 확인.
- 루프백(`127.0.0.1`)이면 토큰 없이 접속된다. 다른 주소로 열면 `required.tokens.mcp_token`가 필요하고, `0.0.0.0`은 거부된다.

### 4-6. 검증 페이지(브라우저로 검색 확인)

PC 전용. 설정은 루트 `settings.yaml`의 `search.server`·`dev.search_ui`·`required.pg`(§4-2 예시 그대로).

```bash
mkdir -p output/validation
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791  ·  /api/health · /api/tools · /api/chunk/<id>
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```

- 왼쪽 "검색 설정"에서 **원천**을 하나 고른다.
- `allow_external: false`면 질의 임베딩도 막혀 키워드·ID 검색만 된다. 벡터 검색까지 보려면 `true`로 바꾸고 MCP를 다시 띄우고, 끝나면 되돌린다.
- 다른 적재 결과를 보려면 `required.pg.pg_schema`를 바꾸고 다시 띄운다.

### 4-7. 그 밖

| 하고 싶은 것 | 명령 |
|---|---|
| 답변 생성 점검(LLM 설정·예산 필요) | `.venv/bin/python -m validation.e2e.answer_gen --url http://127.0.0.1:18769/mcp --q "<질문>"` |
| 이미지 배치 그대로 PC Docker 시험(코드가 든 시험 이미지 — 실행 이미지는 코드를 붙이지 않아 멈춤) | `DATA_PIPELINE_IMAGE=data-pipeline:<시험 태그> MCP_SERVER_IMAGE=mcp-server:<시험 태그> DOC_SRC=<문서 폴더> RAG_OUT=<빈 폴더> SMOKE_SETTINGS=<설정 파일> SMOKE_PG_PASSWORD=<시험용> SMOKE_SYSTEM=<원천> bash valid_env/docker/smoke_test.sh` — 필요한 값은 스크립트 첫 줄 설명 |
| 이미지 로컬 빌드(시험 태그) | `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh`(mcp는 `IMAGE_TARGET=mcp TAG=mcp-server:<시험 태그>`) — TAG를 빼면 배포용 `data-pipeline:<VERSION>` |
| 커밋 전 점검 | `bash deploy/release/lint_changed.sh`(`FIX=1`이면 자동 수정) |

---

## 5. 서버(내부망)에 배포하고 실행하기

서버는 **공용 폴더 하나**(예 `/home/sbl/`) 아래에서 동작한다. 공용 폴더 바로 아래에 **이미지 폴더**(`sbl_images-main/` — 서버에 한 번 불러오면 모든 벌이 같이 씀)와 **루트**(한 벌 = 루트 하나 — 예 `dev/`, 개발자별 `dev-hong/`)가 있다. 루트 = 코드 zip을 푼 폴더(코드 폴더)의 부모이고, 호스트 스크립트는 자기 자리에서 루트를 구한다. 루트 바로 아래에 **설정 파일**(`settings.yaml`·`edw_chain.yaml`) **· 코드 폴더**(`sbl_data_parsing-<판>/`) **· 결과 폴더**(`output/`) **· 백업**(`backup/`)이 있다. 판(버전)마다 새 루트를 만든다(§5-8). 서버 명령은 모두 root 셸의 코드 폴더에서 실행한다.

> 0.1.0 → 0.2.0 올리기는 [release-and-patch §8](docs/operations/release-and-patch.md#8-020-배포--사람이-할-일)(8-3 — 복사해 붙이는 명령과 기대 출력)을 따른다. 아래는 새 서버 설치다.

### 5-0. 배포 단계와 개발 서버 설치

모드마다 이미지를 따로 빌드한다(이미지·코드·띄우는 법은 [§1-3 실행 모드 표](#실행-모드)). 순서는 셋이다.

| 단계 | 어디서 | 하는 일 | 확인 |
|---|---|---|---|
| ① 개발 이미지 만들기 | PC(`local`) | 실행 이미지 `data-pipeline-runtime`·`mcp-server-runtime`을 빌드 → 이 커밋 코드를 붙여 selftest → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) — §5-2 | `build_ship.sh`의 `[판정] 통과` |
| ② 개발 서버에 띄우기 | 개발 서버(`dev`) | 이미지 저장소 zip을 받아 `load.sh <이미지 판>` → 코드 git zip을 루트에 풀고 그 코드 폴더를 `/app/deploy`에 읽기 전용으로 붙여 띄움(`host_ctl.sh`가 붙임 — 아래 설치 순서). 코드만 바뀌면 새 루트에 새 코드 zip(§5-8) | `host_ctl.sh check` · e2e |
| ③ 운영 이미지 굽기·옮기기 | 개발 서버 → 운영 서버(`prd`) | 개발 서버에서 불러온 실행 이미지 위에 시험한 코드 폴더를 넣어 앱마다 코드가 든 이미지 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>`를 다시 빌드(`bake_prod_image.sh`) → 조각을 운영 서버로 옮겨 `load.sh <VERSION>` → `host_ctl.sh up`(마운트 없음, `CODE_DIR` 두지 않음) — [release-and-patch §1-2](docs/operations/release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기) | 굽기의 `[판정] 통과` · 운영 `host_ctl.sh check` |

반입은 git 저장소 두 개를 **zip으로 받아** 이미지는 공용 폴더에, 코드는 루트에 푼다:
- 코드: `gigasamba/sbl_data_parsing`의 받을 판(태그·커밋). zip을 푼 폴더(`sbl_data_parsing-<판>`)가 그대로 코드 폴더다. zip은 `CODE_COMMIT`을 채운다(git clone은 안 채움 — 시작 로그의 커밋이 틀 그대로).
- 이미지: 비공개 `jehunlee302/sbl_images`. 판 폴더마다 실행 이미지를 분할한 조각과 `load.sh`가 있다.

```
<공용 폴더>/                                  ← 예 /home/sbl/
├── sbl_images-main/                         ← 공용 — load.sh · <판>/BUILD.txt · <판>/<이미지>/*.tar.gz.part* + *.sha256(서버에 한 번 load)
├── <루트>/                                   ← 한 벌 — 예 dev/ (판마다 새 루트 — dev-0.2.0/처럼)
│   ├── settings.yaml  edw_chain.yaml        ← settings.sample.yaml·기본 사슬을 host_ctl.sh init이 없을 때만 복사(새 판이면 앞 루트에서 복사해 옴)
│   ├── sbl_data_parsing-<판>/               ← 코드 폴더(VERSION · CODE_COMMIT · deploy/docker/DEPS_HASH)
│   ├── output/                              ← 결과 폴더(host_ctl.sh init이 만듦 — 아래 _ 붙은 폴더는 임시 자리)
│   │   ├── _docflow/<번호>/  _staging/  _faq_seen.txt  _mcp_parse/jobs/  _llm_spend/
│   │   └── logs/                            ← DB 로그를 못 쓸 때의 예비 파일만
│   └── backup/                              ← pg_dump 백업·설정 사본(700)
└── <다른 루트>/                              ← 개발자별 벌(예 dev-hong/ — 아래 "한 서버에 여러 벌")
```

검색 DB(pgvector — 따로 떠 있는 PG 컨테이너)는 루트 밖이라 판이 바뀌어도 같은 DB를 본다.

**미리 있어야 하는 것(서버 — 한 번 확인)**

| 무엇 | 확인 명령 | 없으면 |
|---|---|---|
| podman과 compose 하위 명령 | `podman compose version` | `dnf install podman-compose`(사내 RHEL 저장소). 없으면 인터넷 PC에서 서버와 같은 python 판으로 `pip download podman-compose -d pc-wheels` → 서버에서 `python3 -m pip install --no-index --find-links pc-wheels podman-compose` |
| 호스트 python의 PyYAML | `python3 -c 'import yaml'` | `dnf install python3-pyyaml` |
| PostgreSQL 16 + pgvector, 우리 DB·계정 | DB 담당에게 확인 | DB 담당이 만든다. `vector` 확장도 관리자가 한 번(§5-3 ③ 0번) |
| 운영 그룹 | `id -gn <운영 계정>` · `getent group <그룹>` | 서버 관리자에게 받는다 |

**컨테이너 도구는 root podman 하나로 쓴다.** 셸을 열면 먼저 `export DOCKER=podman`, settings.yaml에 `ops.host.container_cli: podman`. 일반 사용자 셸이면 `DOCKER="sudo podman"`. 이미지를 불러온 저장소와 띄우는 저장소가 같아야 한다(rootless와 root podman은 이미지를 따로 보관).

<a id="서버-설치-순서"></a>
**서버 설치 순서**(처음 한 번 — root 셸, `<루트>` = 만든 루트 폴더, `<코드>` = 코드 zip을 푼 폴더)

0. `export DOCKER=podman` — 위 "미리 있어야 하는 것"을 확인한다.
1. 공용 폴더와 루트를 만들고(`mkdir -p /home/sbl/dev`처럼 아무 자리) 이미지 zip은 공용 폴더(`/home/sbl/`)에, 코드 zip은 루트(`/home/sbl/dev/`)에 푼다.
2. 이미지를 불러온다(공용 폴더에서 — 서버에 한 번, 이미 불러온 판이면 건너뜀): `cd /home/sbl && DOCKER=podman bash sbl_images-main/load.sh <이미지 판>` — 조각 sha256 확인 → 합치기 → load, 끝에 `<판>/BUILD.txt`(빌드 커밋·DEPS_HASH). **코드의 `deploy/docker/DEPS_HASH`가 `BUILD.txt`의 DEPS_HASH와 같은 판**을 고른다(확인 명령 — [§1-3](#실행-모드)).
3. 루트 채우기: `cd <루트>/<코드> && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>` — `output/`·`output/_mcp_parse/jobs`(UID 10001, 2775)·`backup/`(700), 코드 폴더 a+rX, `settings.sample.yaml` → `<루트>/settings.yaml`, `resources/config/edw_chain.yaml` → `<루트>/edw_chain.yaml`(둘 다 없을 때만, 10001:<운영 그룹> 640). 끝에 빈 필수 칸 **이름**을 찍는다. 여러 번 불러도 안전하다.
4. 설정을 채운다 — `<루트>/settings.yaml` 맨 위 `required`의 빈 값(§5-3 ② "꼭 채울 값"). 이미지 칸에는 2에서 불러온 실행 이미지 태그(`data-pipeline-runtime:<이미지 판>`·`mcp-server-runtime:<이미지 판>`). 자원 상한도 본다(아래).
   - EDW 표 설명 자료(`catalog.json`·`columns.jsonl` — 개인정보 없는 자료, 받는 곳은 refactor.md C-91)를 루트 아래 결과 폴더에 복사하고(`<루트>/output/edw_meta/`, UID 10001이 읽을 수 있게) `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`를 적는다. 없으면 `edw_meta` 도구만 `not_configured`로 답한다(나머지 도구는 그대로).
5. `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline`(코드 폴더에서 — DB 도구가 그 안에서 돈다).
6. DB(§5-3 ③): `bash deploy/host/scripts/pipe_exec.sh migrate check --target all` → `… migrate up --target all --dim <임베딩 차원>`(차원 = 임베딩 모델 출력 크기, 모델 담당 확인) → `… migrate master load` → `… migrate check --target all`(기대: 갈래마다 판 끝).
7. `bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp`(검색 MCP는 시작할 때 마스터 표를 읽으므로 6 뒤).
8. `bash deploy/host/scripts/host_ctl.sh check` — check_env → ping_models → migrate check → 두 이미지 selftest → 검색 MCP `/health`, 처음 실패에서 멈춘다. 기대 마지막 줄: `[host_ctl check] 통과 — 6개`. 실행 이미지(`*-runtime`)면 스크립트가 자기 코드 폴더를 `/app/deploy`에 붙인다(셸·systemd에 `CODE_DIR`가 있으면 그 값).
9. 시작 로그 첫 줄 `[image] 이미지 … · 코드 <커밋> · 의존성 …`으로 판을 확인하고, 첫 게시는 §5-3 ④의 미리보기부터, 첫 문서를 넣은 뒤 `mcp_smoke --source <원천>`으로 검색 근거를 확인한다(§4-5).
10. 자동 실행을 켠다 — `bash deploy/host/scripts/host_ctl.sh timers`(§5-5). 다른 서버의 AI 클라이언트가 붙어야 하면 아래 "밖에서 붙기".

**자원(기본 상한 — 합계 CPU 9 · 메모리 36g)**

| 컨테이너 | CPU · 메모리 기본 | settings.yaml 칸 |
|---|---|---|
| `data-pipeline` | 5 · 24g | `ops.containers.pipeline.pipeline_cpus` · `pipeline_mem_limit` |
| `mcp-data-parsing` | 3 · 8g(CPU 나눔 비율 4096 — 일괄 1024보다 먼저) | `ops.containers.data_parsing.data_parsing_cpus` · `data_parsing_mem_limit` · `data_parsing_cpu_shares` |
| `mcp-server` | 1 · 4g | `ops.containers.mcp.mcp_cpus` · `mcp_mem_limit` |

서버 CPU 수보다 큰 값은 컨테이너 도구가 거부한다. CPU 4개 서버라면 예: `parse_cpus: 2`, `data_parsing_cpus: 1`(그러면 `tuning.ops.services.data_parsing.mcp_parse_engine_processes`도 1 이하), `ops.containers.mcp.mcp_cpus: 1`. 바꾼 뒤 `host_ctl.sh up -d --force-recreate …`.

**밖에서 붙기(다른 서버의 AI 클라이언트)**
- 기본 바인드는 `127.0.0.1`. 밖에서 붙게 하려면 `search.server.mcp_bind_host`에 서버 IP를 적는다(`0.0.0.0`은 거부).
- 이때 `required.tokens.mcp_token`가 꼭 있어야 한다(없으면 시작 거부). 만들기: `openssl rand -hex 24`.
- 방화벽에서 `search.server.mcp_port`(기본 8765)를 연다 — 예: `firewall-cmd --add-port=8765/tcp --permanent && firewall-cmd --reload`.

**한 서버에 여러 벌 띄우기(개발자별 — 벌 이름 하나로 나뉨, 개발 서버만)**
- 루트 하나가 한 벌이다. 개발자마다 공용 폴더 아래 루트를 새로 만들어(예 `/home/sbl/dev-hong/`) 위 설치 순서를 따로 한다. 이미지는 공용 폴더에서 이미 불러왔으므로 2번은 건너뛴다.
- 그 루트의 `settings.yaml`에 벌 이름(`ops.host.instance_name`)과 포트 두 칸만 벌마다 다르게 적는다. compose를 직접 부르지 않는다 — `host_ctl.sh`가 이 값으로 이름·포트를 채운다.
- 벌 이름을 적으면 저절로 나뉘는 것:

| 무엇 | 한 벌(이름 비움) | 벌 `hong` |
|---|---|---|
| 컨테이너·compose 묶음·타이머 | `data-pipeline` · `mcp-data-parsing` · `mcp-server` | 끝에 `-hong` |
| PG 스키마 | `required.pg.pg_schema`(예 `sbl`) | `sbl_hong`(원천 스키마 `sbl_hong_sfdc` …) |
| EDW 기록 표 | `required.edw.parsing_meta_table`(기본 `AI.ParsingMeta`) | `AI.ParsingMeta_hong` |
| 게시 경로(Object Storage) | `<prefix>/…` | 개발 서버(dev)에서만 `<prefix>/hong/…` |

- 이미 `_hong`으로 끝나게 적은 스키마·표 이름은 그대로 쓴다. 이름의 `-`는 스키마·표에서 `_`가 된다.
- 운영 서버(`prd`)에서 벌 이름을 적으면 시작 거부(운영은 한 벌). 벌 이름이 있는데 포트 두 칸이 기본값(8765·8766) 그대로면 시작 거부(다른 벌과 겹침).
- EDW 기록 표는 DB 담당자가 미리 만든다(실행 중 DDL 없음): `docs/operations/parsing_meta_mssql.sql`을 복사해 표 이름만 `AI.ParsingMeta_<벌>`로 바꿔 넘긴다(refactor.md C-94).

```yaml
ops:
  host:
    instance_name: hong                # 컨테이너 data-pipeline-hong · mcp-data-parsing-hong · mcp-server-hong, 타이머 data-pipeline-nightly-hong.timer
  services:
    data_parsing:
      data_parsing_port: 8776       # parse_document 작업 서비스 포트(기본 8766 — 검색 MCP도 이 값으로 부름)
search:
  server:
    mcp_port: 8775                # 검색 MCP 포트(기본 8765)
```
- 명령(root 셸 — 이미지는 서버에 한 번만 불러 두면 벌끼리 같이 쓴다):
```bash
mkdir -p /home/sbl/dev-hong && cd /home/sbl/dev-hong && unzip <코드 zip>  # 공용 폴더 아래 새 루트 + 코드 폴더
cd sbl_data_parsing-<판>
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>                    # <루트>/settings.yaml 생김 → 위 칸을 채움
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline                         # → data-pipeline-hong
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <차원>  # 새 스키마 sbl_hong에 표 만들기(설치 순서 6)
bash deploy/host/scripts/pipe_exec.sh migrate master load                   # 기준 표(고객 명부·용어) 넣기 — 검색 MCP가 시작할 때 읽음
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp                 # → mcp-data-parsing-hong · mcp-server-hong(포트 8776 · 8775)
bash deploy/host/scripts/host_ctl.sh check                                       # 마지막 줄 [host_ctl check] 통과 — 6개
bash deploy/host/scripts/host_ctl.sh ps                                          # 이 벌의 컨테이너만 보임
```
- 칸 값 찾기:

| 칸 | 넣을 값 | 어디서 |
|---|---|---|
| `<코드 zip>` | 코드 저장소의 그 판 zip(예 태그 `v0.2.0` → 풀면 `sbl_data_parsing-0.2.0/`) | GitHub `gigasamba/sbl_data_parsing` 태그 — 같은 서버에 이미 한 벌이 있으면 zip 대신 그 코드 폴더를 `cp -a`로 복사해도 된다 |
| `<운영 그룹>` | 컨테이너(UID 10001)와 사람 계정이 함께 쓰는 리눅스 그룹 | `id -gn <운영 계정>` — 모르면 서버 관리자. 첫 벌과 같은 그룹 |
| `<차원>` | 임베딩 모델이 내는 벡터 길이(숫자, 예 1024) | `required.models.embed_model` 담당 — 첫 벌과 같은 모델이면 같은 값. 표를 처음 만들 때만 씀(벡터 칸 길이가 그때 정해짐) |

- `migrate up`이 필요한 때:

| 상황 | `migrate up` |
|---|---|
| 새 벌이 새 스키마(`sbl_hong`)를 씀 | 처음 한 번 `--dim`과 함께, 이어서 `migrate master load` |
| 새 판에 표 변경(마이그레이션)이 있음 | 적재 전에 한 번(`--dim` 없이 — 있는 표는 DB의 차원을 씀) |

- `migrate`에 `--schema <이름>`을 직접 주어도 벌 접미가 붙는다(설정 칸과 같은 규칙 — `--schema demo` → `demo_hong`, 이미 `_hong`으로 끝나면 그대로). 다른 벌의 스키마를 건드리지 않게.

- `instance_name`을 비우면 한 벌(이름 그대로). 이름은 영소문자·숫자·`-`만, 앞은 글자·숫자(틀리면 `host_ctl.sh`·앱이 시작 거부). PG 스키마·EDW 기록 표 접미는 `-`를 `_`로 바꿔 붙인다(`kim-2` → `sbl_kim_2`·`AI.ParsingMeta_kim_2`). 벌 이름은 settings.yaml에서만 읽는다(셸 변수로 덮지 않음). 컨테이너 명령은 셸 `DOCKER`가 있으면 그 값, 없으면 `ops.host.container_cli`.
- 확인: `bash deploy/host/scripts/host_ctl.sh ps` — 그 벌의 컨테이너만 보인다. 자세한 것은 [server-guide §1-3](docs/operations/server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별).

**개발 작업 공간(SSH·opencode — 개발 서버만, 선택)**
- 네 이미지 모두 개발 도구(sshd·git·uv·ruff·mypy·pytest·ripgrep·sqlite3·tmux·vim 등)와 opencode(이미지를 만들 때 `assets/opencode/opencode`가 있으면)를 담고 있다. 앱은 이 도구를 쓰지 않는다 — 켜지 않으면 이미지는 지금처럼 돈다.
- 켜기: 그 루트의 `settings.yaml` 맨 아래 `option.devbox.ssh_port`에 포트를 적는다(개발자마다 다르게). 그러면 `host_ctl.sh`가 `data-pipeline`을 SSH 작업 공간으로 띄운다 — 명령 `devbox`(sshd, 컨테이너 사용자 UID 10001 · 열쇠 로그인만), 코드 폴더를 쓰기 가능으로, 홈 `/home/rag` = `<루트>/home`. 실행 이미지(`*-runtime`)에서만 되고, 운영(`prd`)이면 `host_ctl.sh`가 거부한다(종료 2).
- opencode는 내부망 모델만 쓴다(외부 모델 목록 받기·자동 업데이트 끔). 첫 시작에 홈의 `~/.config/opencode/opencode.json`에 틀이 복사되니 모델 주소·이름을 채운다. 루트에 따로 둔 설정 파일을 쓰려면 `option.devbox.opencode_config`에 그 호스트 경로를 적는다(읽기 전용으로 붙고 `OPENCODE_CONFIG`가 가리킨다).

```bash
# <루트>/settings.yaml 맨 아래
#   option:
#     devbox:
#       ssh_port: 2222
mkdir -p <루트>/home/.ssh && cp <내 공개 열쇠>.pub <루트>/home/.ssh/authorized_keys   # init이 만든 <루트>/home(10001, 700)
chown -R 10001 <루트>/home/.ssh && chmod 700 <루트>/home/.ssh && chmod 600 <루트>/home/.ssh/authorized_keys
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline        # data-pipeline이 sshd로 뜸(호스트 네트워크 — 포트 게시 없음)
ssh -p 2222 rag@<서버>                                           # 접속 뒤 cd /app/deploy — 코드 폴더(쓰기 가능), 컨테이너와 같은 env
```
- 끄기: `ssh_port`를 비우고 `host_ctl.sh up -d data-pipeline` — 다시 `idle`, 코드 폴더는 읽기 전용으로 돌아온다. 홈 폴더(열쇠·opencode 설정·작업 기록)는 남는다.
- 작업 공간에서 고친 코드는 `mcp-data-parsing`·`mcp`가 같은 코드 폴더를 읽기 전용으로 보므로 그 컨테이너를 다시 띄우면 반영된다.

### 5-1. 버전 올리기

규칙과 태그는 [release-and-patch §4](docs/operations/release-and-patch.md#4-버전).

### 5-2. PC에서 — 이미지 만들기와 이미지 저장소에 올리기

§5-0 ① 단계다. PC가 하는 일은 개발 서버용 실행 이미지 두 개를 빌드·시험하고, 통과하면 개인 이미지 저장소 `jehunlee302/sbl_images`에 조각으로 올리는 것뿐이다. 코드만 바뀐 판(`deploy/docker/DEPS_HASH`가 같음)은 이미지를 다시 만들지 않는다.

```bash
# 폐쇄망 빌드라면 먼저 deploy/docker/wheels/에 휠(linux/amd64, py3.12), assets/rapidocr/에 *.onnx(release-and-patch §5-6)
BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh   # 1) 빌드 data-pipeline-runtime:<VERSION> → 2) 이 커밋 코드를 붙여 selftest — [판정] 통과여야 다음으로
BUILD_ONLY=1 IMAGE_TARGET=mcp-runtime      bash deploy/release/build_ship.sh   #    mcp-server-runtime:<VERSION>
bash deploy/release/stage_images.sh pipeline-runtime mcp-runtime                 # 3) output/ship/sbl_images/ — load.sh · <판>/BUILD.txt · <판>/<이미지>/ 45MB 조각 + sha256
```

4) `output/ship/sbl_images/`를 개인 이미지 저장소 `jehunlee302/sbl_images`에 그대로 올린다(push는 사람). 개발 서버는 그 저장소 zip을 받아 `load.sh`로 불러온다(§5-0 설치 순서 2). 같은 태그의 이미지가 이미 있으면 `build_ship.sh`가 멈춘다(버전을 올리거나, 꼭 다시 만들 때만 `FORCE_TAG=1`). 운영 서버 이미지는 PC에서 만들지 않는다(개발 서버에서 굽는다 — §5-0 ③).

### 5-3. 서버 — 처음 설치 자세히

설치 순서는 §5-0 ["서버 설치 순서"](#서버-설치-순서) 하나다. 이 절은 각 단계를 푼 것이다.

**포트 — 모두 settings.yaml 칸**

| 무엇 | settings.yaml 칸 | 기본 | 누가 붙나 |
|---|---|---|---|
| PostgreSQL(pgvector) | `required.pg.pg_port` | 없음(필수) | 파이프라인·검색 MCP |
| 검색 MCP 서버 | `search.server.mcp_port`(바인드 `search.server.mcp_bind_host`) | 8765(127.0.0.1) | AI 클라이언트 |
| MCP 파싱 작업 서비스 | `ops.services.data_parsing.data_parsing_port` — 검색 MCP도 이 값으로 `http://127.0.0.1:<포트>`를 부름 | 8766 | 검색 MCP의 `parse_document` |
| EDW(SQL Server) | `required.edw.edw_port`(주소·계정도 `required.edw`) | 1433 | 파이프라인·`query_edw` |
| 검증 페이지(PC만) | `dev.search_ui.search_ui_port` | 8790 | 사람(브라우저) |

컨테이너는 host 네트워크라 포트가 서버에서 겹치지 않아야 한다.

**① 컨테이너 — `host_ctl.sh`**

상주 컨테이너 3개(서비스 이름 `data-pipeline`·`mcp-data-parsing`·`mcp`)는 `deploy/host/scripts/host_ctl.sh`로 다룬다 — settings.yaml을 읽어 셸 변수로 넘기고, 실행 이미지면 코드 폴더를 붙여(`compose.code*.yml`) compose 파일을 함께 부른다. compose 하위 명령을 그대로 넘긴다.

```bash
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp   # 서비스 하나만도 됨 · ps·logs·stop·down도 같은 방법
```

<a id="compose-파일-읽는-법"></a>
**compose 파일 읽는 법**(`deploy/host/compose/*.yml`)
- 맨 위 `x-settings:`·`x-code:`는 서비스가 아니라 함께 쓰는 YAML 조각이다 — `x-settings`는 settings.yaml을 읽기 전용으로 붙이는 줄, `x-code`는 코드 폴더를 `/app/deploy`에 붙이는 줄.
- `${PARSE_CPUS:-5}` 같은 값은 `host_ctl.sh`가 settings.yaml에서 넘긴다(`load_settings.sh`). 비면 `:-` 뒤 기본값, `${…:?…}`는 꼭 있어야 하는 칸.
- 그래서 compose를 직접 부르면 값을 못 받아 `:?`에서 멈추거나 기본값으로 뜬다. 바꿀 값은 settings.yaml에 적고 `host_ctl.sh`로 다시 띄운다. `host_ctl.sh`는 부를 때마다 settings.yaml을 다시 읽는다.

**② 설정 파일과 결과 폴더** — `host_ctl.sh init`(§5-0 3번). 결과 폴더는 `<루트>/output`이다(다른 곳에 둘 때만 `ops.host.host_output_dir`를 먼저 적는다). 서버에서 직접 만드는 파일(자리·예시·권한)은 [release-and-patch §8-7](docs/operations/release-and-patch.md#8-7-서버에서-직접-만드는-파일).

<a id="꼭-채울-값"></a>
**꼭 채울 값 — 서버 settings.yaml.** "형식 예"는 모두 가짜 값이다. dev = 개발 서버, prd = 운영 서버.

| 칸 | 무엇 | 어디서 받나 | 형식 예(가짜) | 환경 | 틀리면 어디서 잡나 |
|---|---|---|---|---|---|
| `required.env.run_env` | 실행 환경 | 정해진 값 | `dev` · `prd` | PC·dev·prd | 모든 명령이 시작 거부 |
| `required.pg.pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password`·`pg_schema` | 검색 DB(pgvector) — `pg_schema`는 비우면 `data_parsing` | DB 담당 | `pg.example.local` · `5432` · `rag` · `rag_app` · `<비밀>` · (비움) | PC·dev·prd | `host_ctl.sh check` ① check_env · ③ migrate check |
| `required.models.embed_base_url`·`embed_model`·`embed_api_key` | 임베딩 모델(`embed_model`은 적재·검색 때 같아야 함) | 모델 담당(내부망 주소) | `http://llm.example.local:8000/v1` · `<모델>` · `<비밀>` | PC·dev·prd | `host_ctl.sh check` ② ping_models |
| `required.models.llm_*`·`vlm_*` | LLM·VLM 모델 | 모델 담당 | `http://llm.example.local:8001/v1` · `<모델>` | dev·prd | `host_ctl.sh check` ② ping_models |
| `required.edw.edw_host`·`edw_port`·`edw_database`·`edw_read_*`·`edw_write_*` | 회사 DB(EDW) 접속 — 읽기 계정(원천 목록·ParsingMeta 조회·`query_edw`), 쓰기 계정(ParsingMeta 게시 — 필수, 읽기 계정으로 대신하지 않음) · `edw_port`는 비우면 1433 | DB 담당 | `edw.example.local` · (비움) · `EDW` · `<계정>` · `<비밀>` | dev·prd | `run_pipeline` 시작(빠지면 칸 이름을 찍고 멈춤) · `pipe_exec.sh publish --dry-run`(④) |
| `required.edw.parsing_meta_table` | 게시 행을 쓸 EDW 표 — 비우면 `AI.ParsingMeta` | DB 담당 | (비움) | dev·prd | publish `--apply` |
| `dev.local.*` | PC 전용 값(가짜 EDW·게시 폴더·원본 폴더·새 문서 상한) — **서버는 읽지 않음**(`local_edw_sqlite_file`이 적혀 있으면 EDW를 쓸 때 거부) | — | (sample 그대로) | PC만 | — |
| `required.publish.publish_bucket`·`publish_prefix` | silver 게시 위치 — 버킷(원천 원본 버킷과 달라야 함)과 그 안 경로 접두(PC는 `publish_bucket` 대신 `dev.local.local_publish_dir`) | 운영 담당 | `rag-silver` · `parse` | dev·prd | `run_pipeline` 시작 · publish 미리보기 |
| `required.object_storage.object_storage_endpoint`·`object_storage_region`·`object_storage_access_key`·`object_storage_secret_key`·`object_storage_verify_tls` | Object Storage(S3 호환) 접속 — `object_storage_region`은 비우면 `us-east-1`, `object_storage_verify_tls`는 비우면 `1`(사내 CA면 CA 파일 경로) | 스토리지 담당 | `https://os.example.local:9000` · (비움) · `<비밀>` · `<비밀>` · (비움) | dev·prd | `run_pipeline` 시작 · publish `--apply` |
| `extract.source.source_input_location`·`source_default_bucket`·`source_uri_prefix` | 원본 위치 | 운영 담당 | `rdb:csv:<루트>/list.csv` · `<버킷>` · `s3://<버킷>/<접두>` | dev·prd | 첫 `run_pipeline` |
| `required.tokens.mcp_token` | MCP 토큰 하나 — 검색 MCP와 `parse_document` 작업 서비스가 함께 씀 | `openssl rand -hex 24` | 48자 16진수 | dev·prd(밖에서 붙을 때 필수) | `host_ctl.sh check` ⑥ `/health` · `parse_document` 호출이 토큰 오류 |
| `required.tokens.fulltext_sign_key` | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 `sfid` 서명 키 — 비우면 두 도구가 `not_configured`, 바꾸면 이미 발급한 sfid가 모두 무효 | 같은 명령 | 48자 16진수 | dev·prd | 원문 도구 호출이 `not_configured` |
| `required.deploy.pipeline_image` · `mcp_image` | 띄울 이미지 태그(같은 배포 묶음) | §5-0 2번 `load.sh` | dev: `data-pipeline-runtime:<이미지 판>` · prd: `data-pipeline:<VERSION>` | dev·prd | `host_ctl.sh up`이 이미지 없음으로 멈춤 |
| `required.deploy.host_docs_dir` | 원본 문서 폴더 | 서버 관리자 | `/data/docs` | dev·prd | `host_ctl.sh up`이 `:?` 안내로 멈춤 |
| `ops.host.host_output_dir` | 결과 폴더 — 비우면 `<루트>/output` | 서버 관리자 | (비움) | dev·prd | — |
| `required.deploy.pg_container_name` | `pg_dump`·`psql`을 exec할 PG 컨테이너 이름 | DB 담당 | `<컨테이너>` | dev·prd | 백업 명령(release-and-patch §8-3 2) |
| `ops.host.container_cli` | 컨테이너 도구 | 정해진 값 | `podman` | dev·prd | 호스트 스크립트가 다른 도구를 부름 |

그 밖 칸은 비워 두면 코드 기본값을 쓴다([env-guide "서버 값으로 적는 칸"](docs/operations/env-guide.md)도 본다). 모델 주소는 모두 내부망 주소여야 한다.

**③ DB 마이그레이션** — 적재·검색 전에 끝낸다. `pipe_exec.sh`는 상주 `data-pipeline` 안에서 돌므로 먼저 `host_ctl.sh up -d data-pipeline`.

> ⚠️ 0.1.0이 쓰던 스키마에 `up`하면 옛 표가 지워진다(§0). 새 서버가 아니면 release-and-patch §8-3을 따른다.

```bash
# 0. (DB마다 처음 한 번 — DB 관리자) vector 확장 — 없으면 migrate·적재가 "vector 확장 없음"으로 멈춘다
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
bash deploy/host/scripts/pipe_exec.sh migrate check --target all                # 지금 판(읽기만)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 새 스키마는 차원 필요(이미 표가 있으면 DB 차원)
bash deploy/host/scripts/pipe_exec.sh migrate master load
bash deploy/host/scripts/pipe_exec.sh migrate check --target all                # 기대: 갈래마다 판 끝
bash deploy/host/scripts/pipe_exec.sh show-stack                                # 엔진 구성 파일(이름·sha·경로)이 보이면 정상
```

기존 스키마·오류 분기(종료 2)는 [release-and-patch §5-5](docs/operations/release-and-patch.md#5-5-db-버전-관리--migrate).

**④ 연결 점검**

```bash
bash deploy/host/scripts/pipe_exec.sh ping_models     # 모델 주소(LLM·VLM·임베딩) — 하나라도 실패면 종료 1
bash deploy/host/scripts/pipe_exec.sh check_env       # PG·VLM·설정 요약(⚠️ PG 연결 실패를 "건너뜀"으로 보일 수 있음 — 출력을 읽는다)
bash deploy/host/scripts/pipe_exec.sh check           # 자원·쓰기 권한·디스크·PG·모델 요약(⚠️ 실패해도 종료 0 — 출력을 읽는다)
```

- EDW 로그인과 Object Storage 버킷을 따로 확인하는 명령은 없다. 첫 파싱 뒤 publish 미리보기(`bash deploy/host/scripts/pipe_exec.sh publish --dry-run` — 쓰기 0)로 확인하고, 실제 publish 한 번 뒤 EDW 행과 Object Storage 파일을 본다 — 명령은 [release-and-patch §8-3 8](docs/operations/release-and-patch.md#8-3-실행-순서--복사해-붙이는-명령dev-먼저-그다음-prd).
- ⚠️ 실제 publish(`pipe_exec.sh publish`)는 한 번만 한다. 다시 돌리면 Object Storage에 같은 결과를 새 시각 이름으로 또 올린다(EDW는 이미 있는 행을 건너뜀).

**⑤ 이미지 점검**

```bash
$DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> check-modules
bash deploy/release/selftest_gate.sh $DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> selftest   # 기대: [판정] 통과 — FAIL 0
bash deploy/release/selftest_gate.sh $DOCKER run --rm -v "$PWD:/app/deploy:ro,z" mcp-server-runtime:<판> selftest      # 기대: [판정] 통과 — FAIL 0
```

selftest는 종료 코드가 아니라 `[판정]` 줄로 판정한다. 운영 서버(구운 이미지)는 `-v …` 없이 `data-pipeline:<판>`·`mcp-server:<판>`.

**⑥ 검색 MCP 띄우기** — `bash deploy/host/scripts/mcp_keepalive.sh`(여러 번 실행해도 안전 — `/health`가 응답하면 그대로, 꺼져 있으면 띄우고, 응답이 없으면 재시작).

### 5-4. 서버 — 파이프라인 실행

| 방법 | 명령 | 순서 | 언제 |
|---|---|---|---|
| 문서별 흐름 | `python3 deploy/host/scripts/run_pipeline.py …`(코드 폴더에서, nohup) | 문서마다 파싱 → publish → 원본 삭제(게시 성공 뒤) → 구조화·적재 | 대량 처리 |
| 새벽 배치 | systemd `data-pipeline-nightly.timer` → `nightly_batch.sh scheduled` | `ops.nightly.nightly_start_time`에 `run_pipeline.py --start-offset 0 --skip-done --max-docs <상한> --deadline <마감>` | 정기 운영 |
| 파싱·게시만 | `bash deploy/host/scripts/pipe_exec.sh parse` · `pipe_exec.sh publish [--dry-run]` | 상주 컨테이너 안에서 한 번 | 단계 확인 |

`run_pipeline.py` 자리·설정·종료 코드: [release-and-patch §5-4](docs/operations/release-and-patch.md#5-4-run_pipelinepy-자리와-설정) · [server-guide §2](docs/operations/server-guide.md#2-일상-실행--run_pipeline문서별-흐름). **PC에서는 실행하지 않는다.**

#### 진행 보기

```bash
bash deploy/host/scripts/host_ctl.sh logs -f data-pipeline                  # 상주 컨테이너 로그(Ctrl+C로 멈춤 — 컨테이너는 그대로)
tail -f <run_pipeline 작업 폴더>/batch_progress/progress.log              # 문서별 줄("doc#<seq> 구조화+적재 OK|FAIL")
tail -n 50 <결과 폴더>/_docflow/<seq>/structure.log                    # 그 문서의 구조화·적재 출력 — 문서가 끝나면 지워짐(남기려면 run_pipeline --no-cleanup)
```

**로그는 Postgres(`applog` 스키마)에 남는다.** 서버(두 이미지)는 `ops.log.log_db_enabled` 기본 켬이라 `migrate up --target all`(applog 포함)이 먼저다. DB에 못 쓰면 그 행만 `<결과 폴더>/logs/`에 JSON Lines로 남는다. 사람이 보는 실행 출력은 컨테이너 로그(`podman logs <컨테이너>`·`host_ctl.sh logs`), MCP 호출(질문·SQL 포함)은 `applog.mcp_log`이다.

**적재 거부 — 임베딩 모델이 다른 묶음.** 묶음의 임베딩 모델이 검색 스키마에 이미 적재된 문서의 모델과 다르면 적재는 아무것도 쓰지 않고 종료 2(`[load] 임베딩 모델이 다름 — 적재 거부 …`). `applog.pipe_event`에 남는다:

```sql
SELECT ts_start, run_id, model, err FROM applog.pipe_event
WHERE stage = 'load.embed_guard' AND ts_start > now() - interval '7 days' ORDER BY ts_start DESC;
```

해결: 기존 문서와 같은 모델(`required.models.embed_model`)로 묶음을 다시 만들거나, 모델을 바꾸려면 새 검색 스키마에 적재한다.

### 5-5. 서버 — 상주 서비스와 자동 실행

| 무엇 | 방법 |
|---|---|
| 검색 MCP·`mcp-data-parsing` 상주 확인 | systemd `mcp-server-keepalive.timer` — 부팅 1분 뒤 + 2분마다 `mcp_keepalive.sh` |
| 새벽 배치 | systemd `data-pipeline-nightly.timer`(5분마다 깨움) + settings.yaml `ops.nightly.nightly_start_time: "HH:MM"`(그 시각부터 5분 안에 시작) · `max_docs`(새 문서 수 상한, 1 이상) · `deadline: "HH:MM"`(마감 — 시작보다 5분 넘게 뒤). **셋 중 하나라도 비면 돌지 않는다**(기본 비움) |
| 재부팅 뒤 되살리기(podman) | `systemctl enable --now podman-restart` — `restart: unless-stopped` 컨테이너를 부팅 때 다시 띄운다. 일괄 `data-pipeline`은 keepalive가 보지 않으니 재부팅 뒤 `host_ctl.sh ps`로 보고 없으면 `host_ctl.sh up -d data-pipeline` |

systemd 설치(DB 판과 컨테이너를 확인한 뒤 — 새 루트로 옮길 때마다 그 루트의 코드 폴더에서 다시):

```bash
bash deploy/host/scripts/host_ctl.sh timers        # 단위 4개의 코드 폴더 자리를 이 코드 폴더로 채워 /etc/systemd/system에 쓰고 두 타이머를 켬
sudo systemctl enable --now podman-restart
```

새벽 배치 타이머는 켜져 있어도 `ops.nightly` 세 칸을 채우기 전에는 아무것도 하지 않는다.

**상태 보기 · 로그 · 끄기 · 켜기**(코드 폴더에서, root 셸)

| 하고 싶은 것 | 명령 |
|---|---|
| 서버의 모든 컨테이너 | `podman ps` 또는 `docker ps`(root로 띄웠으면 `sudo podman ps`) |
| 우리 컨테이너만 | `bash deploy/host/scripts/host_ctl.sh ps` |
| 컨테이너 로그 | `bash deploy/host/scripts/host_ctl.sh logs --tail 100 mcp`(서비스 이름 `data-pipeline` · `mcp-data-parsing` · `mcp`) |
| 검색 MCP가 응답하나 | `curl -s http://127.0.0.1:<search.server.mcp_port>/health` |
| 타이머 상태 | `systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'` · `journalctl -u mcp-server-keepalive.service -n 50` |
| 끄기 | **타이머부터** — `systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer` → `bash deploy/host/scripts/host_ctl.sh stop` |
| 켜기 | `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp` → `systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer` |
| 설정을 바꾼 뒤 | `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp`(그냥 `up -d`로는 다시 만들지 않음) |

### 5-6. 서버 — 생기는 파일

| 경로 | 왜 생기나 | 지워도 되나 |
|---|---|---|
| `<결과 폴더>/edw/embed_cache.sqlite` | 임베딩 캐시 | 지우면 다음 적재 때 임베딩을 모두 다시 부른다 — 지우지 않는다 |
| `<결과 폴더>/logs/*.jsonl` | DB 로그를 못 쓸 때의 예비 기록(`ops.log.log_fallback_dir`) | 문서 본문·질문이 들어갈 수 있다 — 밖으로 내보내지 않는다. DB가 돌아온 뒤 확인하고 지운다 |
| `<결과 폴더>/_docflow/` · `_staging/` | 문서 하나의 파싱 → 구조화·적재 작업 · 미리 받은 원본 | 문서가 끝나면 지워진다 |
| `<결과 폴더>/_mcp_parse/jobs/` | `parse_document` 작업 | 최근 30개만 남는다 |
| `<결과 폴더>/_llm_spend/` | 외부 모델 하루 지출 장부(PC만 — 서버에는 생기지 않음) | 지난 날짜는 지워도 된다 |
| `<루트>/settings.yaml` | 서버 설정 | **비밀값이 들어 있다** — 권한 640, 옛 루트를 지울 때 함께 지운다 |
| `<루트>/backup/` | `pg_dump` 백업 · 설정 사본 | **DB 내용·비밀값** — 권한 700 그대로, 밖으로 옮기지 않는다 |
| `/var/tmp/bake/` | 개발 서버에서 구운 이미지 조각·코드 묶음 | 운영 서버로 옮긴 뒤 지워도 된다 |

### 5-7. 서버 — 값 바꾸기

| 바꿀 것 | 방법 |
|---|---|
| 설정 값 | settings.yaml을 직접 고치고 `host_ctl.sh up -d --force-recreate …`(서비스 이름 `mcp`, 컨테이너 이름 `mcp-server`) |
| 이번 실행만 다른 값 | `--set 이름=값`(오버레이 설정 파일 도구는 PC 전용 — 서버에서는 종료 2) |
| 엔진 구성 | 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 코드 폴더 바꾸기(§5-8) — 확인 `show-stack`([resources.md §1](docs/architecture/resources.md)) |

### 5-8. 새 판 올리기 — 새 루트

판(버전)마다 새 루트를 만든다. 판끼리 파일이 섞이지 않고, 앞 루트가 그대로 남아 되돌리기가 쉽다.
1. 새 루트(예 `/home/dev-0.3.0/`)를 만들고 새 코드 zip(이미지가 바뀌었으면 이미지 zip도)을 푼다.
2. 앞 루트의 `settings.yaml`·`edw_chain.yaml`을 새 루트로 복사한다(`cp -p`).
3. 새 코드 폴더에서 `host_ctl.sh init --group <운영 그룹>` → `host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp` → `host_ctl.sh check` → `host_ctl.sh timers`(타이머를 새 루트로 옮김).
- 검색 DB는 같은 PG를 그대로 본다. 새 문서 판정은 EDW 기준이라 새 `output/`이 비어 있어도 이어서 돈다.
- 되돌리기: 앞 루트의 코드 폴더에서 `host_ctl.sh up -d --force-recreate …` → `host_ctl.sh timers`.
- 코드만 바뀐 판(`DEPS_HASH` 같음)은 이미지를 다시 만들지 않는다 — 개발 서버 [release-and-patch §1-1](docs/operations/release-and-patch.md#1-1-개발-서버--새-루트로-코드-바꾸기) → 운영 서버 §1-2(굽기).

---

## 6. 꼭 지킬 것

규칙 전체는 [CLAUDE.md](CLAUDE.md) §2~§5(핑거프린트·계약·비밀값·운영 접속 가드·배포 환경·새 패키지).

---

## 7. 문서

문서 지도는 [docs/INDEX.md](docs/INDEX.md). 알려진 문제·미개발 항목은 [docs/PRD.md](docs/PRD.md) 표의 `todo` 행.
