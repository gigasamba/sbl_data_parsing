# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱하고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 개발은 macOS·Windows PC에서 하고, 실행은 내부망(폐쇄망) RHEL 서버의 Docker/podman 이미지 2개로 한다. 기능 요건은 [docs/PRD.md](docs/PRD.md), 문서 지도·용어집은 [docs/INDEX.md](docs/INDEX.md), 개발 규칙은 [CLAUDE.md](CLAUDE.md).

### 0. 읽기 전에 — 꼭 알아 둘 것

> **⚠️ `docker compose`·`podman compose`를 직접 부르지 않는다.** 서버 컨테이너는 늘 `bash deploy/host/scripts/host_ctl.sh …`로 다룬다(§5-3 ①).
>
> **⚠️ 실제 값(비밀번호·키·토큰·서버 주소)은 문서·채팅·커밋에 쓰지 않는다.** 이 README의 예시 값은 모두 가짜다.
>
> **Windows PC는 WSL(리눅스)에서만 쓴다.** 명령은 모두 `.venv/bin/…` 꼴이다.

**PC 첫 실행** — 처음 받은 사람이 PC에서 검색까지 한 번 돌려 보는 길이다(자세한 것은 각 절).

1. 준비 — Python 3.12 가상환경·패키지·커밋 점검 hook·전용 pgvector 컨테이너([§4-1](#4-1-준비처음-한-번)).
2. 저장소 루트에 `settings.yaml`(권한 600) — `run_env: local`과 모델 접속 칸만 채워도 된다([§4-2](#4-2-settingsyaml-작성)).
3. 점검 — 모듈 경계·설정 키·selftest·pytest([§4-3](#4-3-점검)).
4. 테스트 문서 몇 건을 골라 파싱([§4-4](#4-4-파이프라인-실행--문서-몇-건①⑥) ①·②).
5. 구조화·DB 표·적재([§4-4](#4-4-파이프라인-실행--문서-몇-건①⑥) ③~⑤).
6. 검색 MCP를 띄우고 `/health`·`mcp_smoke`로 확인([§4-5](#4-5-검색-mcp-서버)).
7. 브라우저 검증 페이지로 검색해 보기([§4-6](#4-6-검증-페이지브라우저로-검색-확인)).
8. 외부 모델 허용(`*_allow_external`)을 `false`로 되돌리기([§4-4](#4-4-파이프라인-실행--문서-몇-건①⑥) ⑥).

**담당 연락처**(역할만 — 이름은 맡은 사람이 채운다. 연락처 값은 사내 기록에 둔다)

| 역할 | 맡는 일 | 담당 |
|---|---|---|
| 지금 담당자("사용자" — [INDEX 용어집](docs/INDEX.md#glossary)) | 결정·사람 검토(등급 A) 승인·이미지 저장소·릴리스 | `<이름>` |
| 서버 운영 | 개발·운영 서버 설치·판 올리기·타이머·로그 점검 | `<이름>` |
| DB 담당(PostgreSQL) | pgvector DB·계정·스키마·마이그레이션 합의·백업·복원 | `<이름>` |
| EDW 담당(회사 DB) | `AI.FileStorageMap` 등 원천 표와 읽기 계정 | `<이름>` |
| 모델 담당 | 내부망 LLM·VLM·임베딩 주소·모델·임베딩 차원 | `<이름>` |
| 스토리지 담당 | Object Storage 버킷·접근 키 | `<이름>` |
| MCP 클라이언트 담당 | 검색 MCP를 붙여 쓰는 쪽 — 도구 계약이 바뀌면 알림 받음 | `<이름>` |
| devops(빌드·반입) | 이미지 빌드·폐쇄망 반입(휠·`assets/`) | `<이름>` |

**용어**

| 말 | 뜻 |
|---|---|
| 원천 | 문서가 온 시스템 — `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`. 검색할 때는 원천을 꼭 하나 고른다 |
| 대표 결과(silver) | 문서 하나를 여러 엔진으로 파싱한 뒤 고른 결과 한 벌(`.md`·`.json`) |
| 번들(bundle) | 구조화 결과 폴더(`docs.jsonl`·`chunks.jsonl`·`vectors.npy`·`meta.json`) — 적재의 입력 |
| 적재(gold) | 번들을 PostgreSQL(pgvector)에 넣는 일 |
| 마스터 표 | 용어집·고객 명부·ID 꼴 표(`<스키마>_master.glossary`) — 원본은 git의 `resources/vocab/glossary/glossary.csv` |
| 실행 이미지(`*-runtime`) | 코드가 없는 이미지 — 개발 서버는 코드 폴더를 붙여 쓴다 |
| 루트 · 코드 폴더 · 벌 | 코드 폴더 = 코드 zip을 푼 폴더(예 `/home/sbl/sbl_data_parsing-main-1/`). 루트 = 코드 폴더 자체 — `settings.yaml`·`edw_chain.yaml`·`output/`이 그 안에 있다. 벌 = 한 서버에 따로 띄운 컨테이너 한 묶음(코드 폴더 하나) |
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
| **publish** | Object Storage 업로드 + 처리 기록 파일 `publish/silver.jsonl`(EDW에는 쓰지 않음) | `python -m pipeline.load.publish_parse_result` | (운영 시스템에 기록) |
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
| 코드가 오는 곳 | 저장소 체크아웃 그대로 · 시험 이미지는 빌드 때 COPY(Dockerfile 타깃 `pipeline`·`mcp`) | 코드 폴더(코드 git zip을 푼 폴더 — 예 `sbl_data_parsing-main-1`)를 컨테이너 `/app/deploy`에 읽기 전용(`:ro,z`)으로 붙임 | 이미지 안(굽기 때 COPY) — 붙이지 않음. 함께 오는 코드 묶음은 호스트 스크립트(`deploy/host/`)용 |
| 만드는 법 | `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh`(mcp는 `IMAGE_TARGET=mcp TAG=mcp-server:<시험 태그>`) | PC: `BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`(+ `mcp-runtime` — 이 커밋 코드를 붙여 selftest 판정) → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) → 개발 서버 `load.sh <이미지 판>`(§5-2). 의존성이 같으면 다시 만들지 않는다 | 개발 서버의 시험한 코드 폴더에서 `bash deploy/release/bake_prod_image.sh <이미지 판>` — 그 실행 이미지 위에 코드만 COPY(`deploy/docker/Dockerfile.bake`, 네트워크 없음) → 운영 서버 `load.sh <VERSION>`([release-and-patch §1-2](docs/operations/release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)) |
| 띄우는 법 | `.venv/bin/python -m mcp_server.main` 등(§4-4·§4-5) · 이미지 시험 `bash valid_env/docker/smoke_test.sh`(`valid_env/docker/compose.test.yml` — §4-7) | 코드 폴더에서 `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp` — 이미지가 `*-runtime:`이면 `host_ctl.sh`가 자기 코드 폴더를 `CODE_DIR`로 잡아 `compose.code*.yml`을 더한다. 시작 스크립트 `runtime_entry.sh`가 마운트·의존성 지문을 확인하고 코드의 `deploy/docker/entrypoint.sh`로 넘긴다 | 같은 `host_ctl.sh up -d …` — 이미지가 `*-runtime`이 아니므로 마운트 없이 이미지 안 `entrypoint.sh`로 뜬다. 셸·systemd에 `CODE_DIR`을 두지 않는다 |
| settings.yaml 이미지 칸(`required.deploy.pipeline_image`·`mcp_image`) | 쓰지 않음(이미지 시험은 셸 변수 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`) | `data-pipeline-runtime:<이미지 판>` · `mcp-server-runtime:<이미지 판>` | `data-pipeline:<VERSION>` · `mcp-server:<VERSION>` |
| `run_env` | `local`(저장소 루트 `settings.yaml`) | `dev` | `prd` |

**실행 이미지 판 고르기(dev·굽기).** 실행 이미지 판은 코드 판과 다를 수 있다. **이미지 판의 `BUILD.txt`에 적힌 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판**을 쓴다(값 = `requirements-core.txt`·`requirements-image.txt`의 지문, `bash deploy/release/deps_hash.sh`). 다르면 컨테이너가 `의존성 지문이 다름`으로 멈추고(종료 2) `bake_prod_image.sh`도 멈춘다 — 같은 값인 판이 없으면 새 실행 이미지가 필요하다([release-and-patch §5](docs/operations/release-and-patch.md#5-새-이미지-버전이-필요할-때)).

```bash
cat deploy/docker/DEPS_HASH                                                   # 코드 폴더에서 — 코드가 요구하는 지문
grep -H DEPS_HASH ../sbl_images-main/*/BUILD.txt                              # 이미지 판마다 지문 — 같은 값인 판을 load.sh <판>
$DOCKER run --rm --entrypoint cat data-pipeline-runtime:<판> /app/docker/deps_hash   # 이미 불러온 이미지의 지문
```

### 1-4. DB — Alembic 마이그레이션

pgvector의 표는 코드가 실행 중에 만들지 않는다. 모두 Alembic 마이그레이션(`common/store/db/migrations/versions/`)으로 만들고, 명령은 `dbtool`(PC: `python -m common.store.db.dbtool`, 서버: `bash deploy/host/scripts/pipe_exec.sh migrate`) 하나다.

| 갈래(`--target`) | 스키마 | 끝 판 |
|---|---|---|
| `search` | 기준 스키마(`required.pg.pg_schema`) + 원천 스키마 5벌 `<기준>_{sfdc,crms,las,faq,other}` + (개발 서버·PC) DEV 원천 스키마 `<기준>_dev_<숫자>` — settings.yaml `required.source.source_systems`의 `DEV-<숫자>`를 만들고 DB에 이미 있는 `_dev_*`도 올림 | `0007_search`(0001→0007 차례로 — 0006은 `doc` 처리 기록 칸, 0007은 `doc` 찾기 색인) |
| `applog` | `applog`(고정 이름 — 다른 `--schema`는 종료 2, PC 시험 스키마 `test_*`만 예외) | `0004_applog`(0001→0004 — 0003은 적재 안 된 문서 표 `except_doc_info`, 0004는 `pipe_event` 원천·`except_doc_info` 확장자·크기 칸) |
| `master` | `<기준>_master` | `0002_master`(0001→0002 — 0002는 표 `glossary` 하나로 바꿈) — 채우기는 `master load` |

| 명령 | 하는 일 |
|---|---|
| `up --target search\|applog\|master\|all` | 끝 판까지 실행 |
| `current --target …` | 지금 DB 판과 코드의 끝 판 |
| `check --target …` | `current`와 같고, 끝 판이 아니면 종료 1(읽기만) |
| `master load [--dir <폴더>]` | 마스터 표를 `glossary.csv`(기본 `resources/vocab/glossary/`)로 통째로 바꿈 |

처음 설치(PC §4-4 ④, 서버 §5-0 6번) · 마이그레이션이 바뀐 릴리스(적재 전에 `up`) · 새 검색 스키마(임베딩 차원이 바뀜 — 새 `db_schema`에 `up --target all --schema <새 스키마> --dim <차원>`)일 때 실행한다. 자동 동작·오류 분기는 [release-and-patch §5-5](docs/operations/release-and-patch.md#5-5-db-버전-관리--migrate).

---

## 2. 폴더 구조

폴더마다 두는 것과 모듈 경계는 [CLAUDE.md §1](CLAUDE.md) 표에 있다(`python -m common.check.check_modules`가 경계를 확인).

---

## 3. 설정

모든 설정 값과 비밀값은 **settings.yaml 한 파일**에 둔다. 코드는 환경변수에서 설정을 읽지 않는다(옛 env 이름을 넘기면 무시하고 이름만 경고).

| 항목 | 내용 |
|---|---|
| 위치 | PC: 저장소 루트 `settings.yaml`(git 제외, 권한 600) · 서버: `<루트>/settings.yaml`(루트 = 코드 폴더 자체, 주인 UID 10001, 권한 640) · 다른 파일은 env `SETTINGS_FILE` |
| 구조 | 맨 위 `required`(필수 접속·입력) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → 맨 아래 `tuning`. 같은 절·칸을 두 번 쓰면 시작 거부. 칸 자리 찾기: `python -m common.config.sample --where <옛 env 이름>`. 칸 설명·기본값은 [settings.sample.yaml](settings.sample.yaml) |
| 쓰는 법 | **기본값과 다르게 쓸 칸만** 적는다. 비운 칸은 코드 기본값 |
| 필수 | `required.env.run_env` — `local`(PC) · `dev` · `prd`(서버 — 외부 모델 호출과 가짜 LLM을 거부하고, 설정 파일을 못 읽으면 시작하지 않는다) |
| 파싱할 원천 | `required.source.source_systems` — 원천 목록(예 `[DEV-1]`, 대소문자 무관). 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`·`DEV-<1~99>`이고, 비우면 운영 5개 원천(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`)을 파싱한다(`DEV-<숫자>` 행은 뺌). 원천은 EDW `AI.FileStorageMap.source_system` 칸 값이다. `DEV-…`는 dev·local에서만 쓰며, prd에 적혀 있으면 시작하지 않는다. `DEV-<숫자>` 문서는 검색 스키마 `<기준>_dev_<숫자>`에 적재된다 — 목록에 새로 넣으면 먼저 `migrate up --target search`(없으면 적재가 멈춤). PC 폴더 원천은 맨 위 `DEV-<숫자>/` 폴더도 원천 폴더이고, 같은 목록으로 거른다 |
| 칸별 안내 | [docs/operations/env-guide.md](docs/operations/env-guide.md) |
| 서버용 파일 | git에 올리지 않는다. `settings.sample.yaml`을 복사해 `required`를 채운다(§5-3 ② "꼭 채울 값"). **PC 파일을 그대로 복사하지 않는다** — PC의 `run_env: local`·`allow_external: true`가 서버에서 외부 모델 호출을 연다 |

**실행할 때 값을 넘기는 방법 2가지**

| 방법 | 언제 | 받는 명령 |
|---|---|---|
| **A. settings.yaml에 적기** | 계속 쓸 값 | 모든 명령 |
| **B. 명령 인자 `--set 이름=값`** | 이번 실행에만(이름은 옛 env 이름). 비밀·호스트 칸은 거부 | `pipeline.cli`·`gold_bundle`·`pgvector_load`·`publish_parse_result` 등 파이프라인 진입점, `mcp_server.main`·`mcp_server.cli.search_ask` |

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
```

**PC 시험 DB(pgvector) 준비 — 없으면 띄우기.** 배포 판정 시험(selftest)과 pytest의 DB 사례는 이 PG에 붙는다(sqlite 대역 없음). PC(local)에서 settings.yaml `required.deploy.pg_container_name: pgvector`와 `required.pg`가 채워져 있으면 시험이 붙지 못할 때 스스로 2(만들기·켜기)·3(기다리기)을 한다 — 그래도 못 붙으면 그 사례가 FAIL. 손으로 할 때는 아래를 순서대로 한다. 이미지는 `docker run`이 내려받는다(폐쇄망 PC는 먼저 `docker load -i <pgvector tar>`).

1. 상태 보기 — 빈 줄이면 아직 안 만듦, `Exited …`면 멈춤, `Up …`이면 돌고 있음(3으로).
   ```bash
   docker ps -a --filter name=^pgvector$ --format '{{.Status}}'
   ```
2. 안 만들었으면 만들고, 멈췄으면 켠다.
   ```bash
   docker run -d --name pgvector --restart no --memory 1g --cpus 2 -p 127.0.0.1:55433:5432 \
     -v sbl_mcp_pgdata:/var/lib/postgresql/data -e POSTGRES_DB=rag -e POSTGRES_USER=pgvector \
     -e POSTGRES_PASSWORD=<settings.yaml required.pg.pg_password와 같은 값> pgvector/pgvector:pg16
   docker start pgvector      # 멈춘 것을 켤 때
   ```
3. 받을 준비가 될 때까지 기다린다.
   ```bash
   until docker exec pgvector pg_isready -U pgvector -d rag; do sleep 1; done
   ```
4. `POSTGRES_PASSWORD`는 볼륨을 처음 만들 때만 걸린다. 볼륨이 이미 다른 비밀번호로 있으면 직접 바꾼다(값은 화면·기록에 남기지 말고 손으로 친다).
   ```bash
   docker exec -i pgvector psql -U pgvector -d rag -c "ALTER USER pgvector PASSWORD '<settings.yaml 값>'"
   ```
5. settings.yaml `required.pg`를 모두 채운다 — `127.0.0.1` · `55433` · `rag`(DB) · `pgvector`(계정) · 같은 비밀번호(빈 칸이 있으면 시작 거부). 시험이 스스로 띄우게 하려면 `required.deploy.pg_container_name: pgvector`도 적는다.
6. 판 올리기 — §4-4 ④의 `dbtool up --target all --schema <이름> --bundle <묶음> --create-extension`, 그다음 확인.
   ```bash
   .venv/bin/python -m common.store.db.dbtool check --target all   # 최신 판이 아니면 종료 코드 1
   ```
7. §4-3 점검을 차례로 하나씩 돌린다(pipeline.config → check_modules → keyscan → selftest → pytest).

- 작업 폴더(git worktree)에는 `settings.yaml`이 없다. 거기서 점검·시험을 돌릴 때는 `export RUN_ENV=local`을 먼저 한다 — 없으면 실행 환경을 읽지 못해 결과 폴더 `output/`이 저장소 한 단계 위에 생긴다.

### 4-2. settings.yaml 작성

저장소 루트에 `settings.yaml`을 만들고 `chmod 600`한다(방법 A 예시):

```yaml
required:
  env: {run_env: local}
  pg: {pg_host: 127.0.0.1, pg_port: 55433, pg_database: rag, pg_user: pgvector, pg_password: <비밀번호>, pg_schema: demo}   # 적재·검색할 스키마
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

- `settings.sample.yaml`을 그대로 복사해 시작해도 된다 — **빈 칸**(`pg_host:` 뒤가 비어 있음)은 꼭 적을 값(주석의 `[필수 · 모드]`와 예), **`null`**은 비워 두면 코드 기본값을 쓰는 칸이다. **PC(local)에 꼭 필요한 칸은 `run_env: local`, 모델 접속(`embed_base_url`·`embed_model`·`llm_base_url`·`llm_model`·`vlm_base_url`·`vlm_model`), PG 접속이다.** PG 접속 칸도 꼭 채운다(PC는 전용 pgvector 컨테이너 — sqlite 대역 없음, `pg_schema`는 비우면 `data_parsing`). EDW·Object Storage·토큰·배포 칸은 PC에서 채우지 않는다.
- 옛 배치(최상위 `common`·`pipeline`·`mcp`)·옛 자리·지운 칸·모르는 칸이 있으면 시작하지 않고 그 칸 이름만 알린다 — `settings.sample.yaml`과 대조해 고친다(자리 찾기 `python -m common.config.sample --where <이름>`).
- PC 전용 칸(외부 모델 허용·지출 상한·단가, 시험 하네스)은 `dev` 절에 모여 있다(sample 맨 아래).
- **외부 임베딩은 `allow_external: true`이고 `run_env: local`일 때만** 호출된다(서버 dev·prd는 늘 거부).
- **LLM·VLM도 같다:** `required.models`의 `llm_*`·`vlm_*`(주소·모델·키)를 채우고 `dev.models.llm.llm_allow_external`·`dev.models.vlm.vlm_allow_external`을 `true`로 두면 PC에서 분류(SFDC·LAS)와 그림·스캔 쪽 VLM이 외부 모델을 부른다(`run_env: local`일 때만). 비우면 분류가 실패해 SFDC·LAS 문서는 적재되지 않는다. OpenRouter 하나로 임베딩·LLM·VLM을 모두 쓸 수 있다(같은 주소·키, 모델만 다름 — 단가표 `common/ai/llm.py` `PRICES`에 있는 모델이어야 예산 상한이 걸림).
- **VLM 설정은 한 벌:** 스캔·이미지 문서의 VLM 엔진(`qwen_vlm`)·쪽 VLM·그림 VLM이 같은 호출과 같은 칸(`common.models.vlm.*` — 동시 수·제한 시간·재시도·`vlm_extra_request_body`, 해상도 `extract.page_render_dpi` 150, 쪽 상한 `transform.vlm.vlm_max_pages_per_doc`)을 쓴다. 생각(추론) 모델이면 `common.models.vlm.vlm_extra_request_body`에 생각 끄기를 넣는다(OpenRouter는 `{"reasoning": {"enabled": false}}`) — 칸 설명은 [env-guide §2](docs/operations/env-guide.md), 규칙은 PRD [pl-43](docs/prd/transform.md#pl-43).
- **내부망 서버(dev·prd)에서 시험·운영할 때는 세 칸 `embed_allow_external`·`llm_allow_external`·`vlm_allow_external`을 모두 `false`(0)로 둔다.** 서버는 `run_env`가 dev·prd라 켜 두어도 외부 호출을 거부하지만, 서버 settings.yaml에는 외부 허용을 남기지 않는다.
- **게시(silver)·EDW·원본 — PC는 가짜 대상만 쓴다.** 값은 `dev.local` 묶음에 기본값으로 들어 있어 적지 않아도 된다(바꿀 때만 — 저장소 루트 기준 상대 경로 또는 절대 경로):
  ```yaml
  dev:
    local:
      local_edw_sqlite_file: null                          # 가짜 EDW(원본 목록 FileStorageMap) — 비우면 valid_env/edw/edw_copy.sqlite(없으면 edw.sqlite를 복사해 만듦)
      local_publish_dir: valid_env/object_storage/Parsing_Result   # 게시 폴더(가짜 Object Storage) — 처음 게시할 때 만듦
      local_source_dir: valid_env/object_storage           # 파싱 원본 — --source·source_input_location이 없을 때
      local_max_new_docs_per_run: 5                        # 한 번에 새로 파싱할 문서 수 — --max-new·max_new_docs_per_run이 없을 때
  ```
  게시 폴더에 `<prefix>/<출처>/<원본 경로>/<파일명>_<날짜>.md`로 쓴다(게시 폴더는 원본 목록에서 빠진다). 원본 폴더(`ops.paths.source_docs_dir`)·파싱 원본(`extract.source.source_input_location` — 폴더 또는 `rdb:csv:<경로>`)도 상대 경로를 받는다.
  `run_env: local`은 서버 전용 칸(`required.edw.edw_host`·EDW 계정, `required.object_storage.*`, 원천 버킷, `required.publish.publish_bucket`)을 **무시한다** — 적혀 있어도 비우고 `[settings] local(PC) — 서버 전용 칸을 무시함(비움): …` 한 줄에 칸 이름만 찍은 뒤 시작한다. 그래서 PC는 실제 EDW·Object Storage에 닿지 않는다. 서버(dev·prd)는 이 칸들을 쓰고 `dev.local`은 읽지 않는다.
- **PG 접속 칸을 채운 PC는 파싱 전에 한 번 `.venv/bin/python -m common.store.db.dbtool up --target applog`** — 받기가 DRM·암호·지원 안 함·내용 중복 문서를 적재 안 된 문서 표 `applog.except_doc_info`에 쓰는데, 표가 없으면 그 문서에서 파싱이 멈춘다(PG를 비운 PC는 SQLite 대역이 표를 만든다). ④의 `up --target all`에도 들어 있다.
- PG 접속 칸(`required.pg`의 `pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password` 다섯 칸)은 **모두 채운다.** 빈 칸이 있으면 채울 자리를 알려 주고 멈춘다(PC·서버 모두 — sqlite 대역 없음).

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
cp valid_env/edw/edw.sqlite output/demo/edw.sqlite   # EDW 대역 사본(원본 목록)
.venv/bin/python -m pipeline.cli --set RDB_SQLITE=output/demo/edw.sqlite parse --source $SRC --src output/demo/prepared
```

- PG 접속 칸을 채웠다면 이 단계 전에 `dbtool up --target applog`를 한 번(§4-2 — 적재 안 된 문서 표).
- `--source`는 원본 폴더, `--src`는 준비된 파일이 놓이는 곳(`--src`만 주면 준비된 폴더로 보고 가져오기·중복 제거를 건너뜀).
- 끝난 문서는 검색 DB(gold `doc` 표)에서 읽는다 — 서버에서 PG를 못 읽으면 종료 4. EDW 대역은 `--set RDB_SQLITE`를 빼면 `valid_env/edw/edw_copy.sqlite`를 쓴다(위처럼 주면 그 사본).
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
.venv/bin/python -m common.store.db.dbtool current --target all    # 기대: search 0007_search · applog 0004_applog · master 0002_master
.venv/bin/python -m common.store.db.dbtool check --target all      # 기대: 갈래마다 판 끝, 종료 코드 0
```

- 초기화 순서: `dbtool up`(search·applog·master) → `dbtool master load` → 파싱·구조화·적재. 서버는 마스터 표가 비었으면 구조화·검색이 시작하지 않는다. `resources/vocab/glossary/glossary.csv`를 고치면 `master load`를 다시 돌린다(이미 적재한 문서는 자동으로 다시 처리하지 않음).
- `--bundle`은 벡터 차원을 `meta.json`에서 읽으려고 준다(또는 `--dim`). `--create-extension`은 새 PG일 때만.
- DB에 붙지 않고 SQL만 보려면 같은 인자에 `--sql <파일>`(있는 DB는 `--from <지금 판>` — 갈래마다 하나) — DB 담당이 읽고 고쳐 손으로 실행한다. DB를 읽어야 하는 확인(지금 판·vector 확장·남의 스키마·차원)은 파일 안 `-- 수동:` 줄.

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

# ask·MCP도 같은 --set을 받는다
.venv/bin/python -m mcp_server.cli.search_ask "${SETS[@]}" ask --source CRMS --k 3 --q "<질문>"
nohup .venv/bin/python -m mcp_server.main "${SETS[@]}" --set MCP_PORT=18769 > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
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

서버는 **공용 폴더 하나**(예 `/home/sbl/`) 아래에서 동작한다. 공용 폴더 바로 아래에 **이미지 폴더**(`sbl_images-main/` — 서버에 한 번 불러오면 모든 벌이 같이 씀)와 **벌 폴더**(한 벌 = 코드 zip을 푼 코드 폴더 하나 — 예 `sbl_data_parsing-main-1/`)가 있다. 루트 = 코드 폴더 자체이고, 호스트 스크립트는 자기 자리에서 루트를 구한다. 코드 폴더 바로 아래에 코드와 함께 **설정 파일**(`settings.yaml`·`edw_chain.yaml`) **· 결과 폴더**(`output/`)(+ SSH 작업 공간을 켜면 `home/`)이 있다 — 모두 git·코드 zip에 없는 것이라 새 판을 덮어써도 남는다(§5-8). 서버 명령은 모두 root 셸의 코드 폴더에서 실행한다.

> 이미 돌고 있는 서버를 새 판으로 올리는 법(판 확인·백업·새 이미지·DB 판·되돌리기 — 복사해 붙이는 명령과 기대 출력)은 [upgrade-guide.md](docs/operations/upgrade-guide.md)다. **0.1.0이 만든 DB에 `migrate up`을 그냥 하지 않는다**(검색 판 `0002_search`가 옛 표를 지움 — 그 문서 §0). 아래는 새 서버 설치다.

> 개발 서버를 처음 맡았다면 [handover-guide.md](docs/operations/handover-guide.md)를 먼저 따라 한다 — 자기 벌 하나를 만들어 `DEV-<숫자>` 문서를 처리하고 검색까지, 단계마다 `cd`할 폴더·명령·성공 출력을 차례로 적었다.

<a id="핵심-명령"></a>
**핵심 명령**(root 셸 · 셸을 열면 먼저 `export DOCKER=podman` · `<루트>` = 벌 폴더 = 코드 폴더, 예 `/home/sbl/sbl_data_parsing-main-1`)

서버에서는 `docker run`·`docker start`·`docker compose`를 직접 치지 않는다. 이미지 불러오기는 `load.sh`, 컨테이너 띄우기·멈추기·로그는 `host_ctl.sh`가 맡는다 — `host_ctl.sh`는 compose를 감싸 settings.yaml에서 컨테이너 이름·포트·볼륨을 채우고, 컨테이너 도구는 `$DOCKER`(podman 또는 docker — 없으면 `ops.host.container_cli`)를 쓴다. 아래 `host_ctl.sh`·`pipe_exec.sh`는 `deploy/host/scripts/`에 있다.

| 하고 싶은 일 | 들어갈 폴더(`cd`) | 명령 | 성공하면 보이는 것 |
|---|---|---|---|
| 이미지 불러오기(서버에 한 번) | 공용 폴더(`/home/sbl`) | `bash sbl_images-main/load.sh <이미지 판>` | `== <이미지> — load` 줄들 → `BUILD.txt` 내용 → `== 끝 — settings.yaml 이미지 칸(…)을 위 태그로` |
| 벌 폴더 처음 채우기 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>` | `[host_ctl init] 루트: …` → `만듦 …settings.yaml` 등 → 빈 필수 칸 **이름** 목록 |
| 설정 확인(값은 안 찍음) | `<루트>` | `bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK` | `설정 OK` |
| 띄우기 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp`(서비스 하나만도 됨) | 아래 `ps`에 세 줄 `Up` |
| 상태 · 로그 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh ps` · `… logs --tail 100 mcp`(서비스 이름 `data-pipeline`·`mcp-data-parsing`·`mcp`) | 이 벌의 컨테이너만 · 그 컨테이너 로그 |
| 전체 점검 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh check` | 마지막 줄 `[host_ctl check] 통과 — 6개` |
| DB 표 만들기(처음 한 번 — 공용 DB) | `<루트>`(`data-pipeline`이 떠 있어야 함) | [§5-3 ③](#5-3-서버--처음-설치-자세히) 순서 — 검토용 SQL → `migrate up --target all --dim <임베딩 차원>` → `migrate master load` → `migrate check` | `[migrate] <갈래> <스키마>: 판 [...] (끝 …)` · `[pipe_exec] … 끝 (종료 코드 0)` |
| DB 담당 검토용 SQL(DB에 붙지 않음) | `<루트>` | 위 `migrate up` 명령 끝에 `--sql /app/output/up.sql` | `[migrate] SQL → /app/output/up.sql (DB에 붙지 않음 — …)` — 호스트에서는 `<루트>/output/up.sql` |
| 파이프라인 한 번(시험 2건) | `<루트>` | `nohup python3 deploy/host/scripts/run_pipeline.py --limit 2 > run_first.out 2>&1 &` | `deploy/host/scripts/test_space/batch_progress/progress.log` 끝 줄 `=== 문서별 flow 끝: 2건(완료 2 · …) · … · 종료 코드 0 ===` |
| 설정을 바꾼 뒤 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp`(그냥 `up -d`는 다시 만들지 않음) | `ps`에 세 줄 `Up`(방금 시작) |
| 멈추기 · 지우기 | `<루트>` | **타이머부터** `systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer` → `bash deploy/host/scripts/host_ctl.sh stop`(지우기는 `down`) | `ps`에 세 줄 `Exited`(`down`이면 줄 없음) |
| 자동 실행 타이머 켜기 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh timers` → 확인 `systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'` | `  씀  /etc/systemd/system/<단위>` 네 줄 · 목록에 두 타이머의 다음 실행 시각 |
| 새 판 올리기 | `<루트>` | [§5-8](#5-8-새-판-올리기--덮어쓰기) · 전체 순서 [upgrade-guide.md](docs/operations/upgrade-guide.md) | `host_ctl.sh check` 통과 |
| 두 번째 벌 | 공용 폴더 → 새 `<루트>` | [handover-guide §13](docs/operations/handover-guide.md#13-두-번째-벌-만들기) | 그 벌 폴더의 `host_ctl.sh ps`에 `-2` 컨테이너만 |

번호가 붙은 벌(`…-main-2`)이면 컨테이너·타이머 이름 끝에 `-<번호>`가 붙는다(예 `mcp-server-keepalive-2.timer`).

### 5-0. 배포 단계와 개발 서버 설치

모드마다 이미지를 따로 빌드한다(이미지·코드·띄우는 법은 [§1-3 실행 모드 표](#실행-모드)). 순서는 셋이다.

| 단계 | 어디서 | 하는 일 | 확인 |
|---|---|---|---|
| ① 개발 이미지 만들기 | PC(`local`) | 실행 이미지 `data-pipeline-runtime`·`mcp-server-runtime`을 빌드 → 이 커밋 코드를 붙여 selftest → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) — §5-2 | `build_ship.sh`의 `[판정] 통과` |
| ② 개발 서버에 띄우기 | 개발 서버(`dev`) | 이미지 저장소 zip을 받아 `load.sh <이미지 판>` → 코드 git zip을 공용 폴더에 풀어 벌 폴더 이름으로 바꾸고 그 코드 폴더를 `/app/deploy`에 읽기 전용으로 붙여 띄움(`host_ctl.sh`가 붙임 — 아래 설치 순서). 코드만 바뀌면 새 코드 zip을 벌 폴더에 덮어씀(§5-8) | `host_ctl.sh check` · e2e |
| ③ 운영 이미지 굽기·옮기기 | 개발 서버 → 운영 서버(`prd`) | 개발 서버에서 불러온 실행 이미지 위에 시험한 코드 폴더를 넣어 앱마다 코드가 든 이미지 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>`를 다시 빌드(`bake_prod_image.sh`) → 조각을 운영 서버로 옮겨 `load.sh <VERSION>` → `host_ctl.sh up`(마운트 없음, `CODE_DIR` 두지 않음) — [release-and-patch §1-2](docs/operations/release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기) | 굽기의 `[판정] 통과` · 운영 `host_ctl.sh check` |

반입은 git 저장소 두 개를 **zip으로 받아** 공용 폴더에 푼다:
- 코드: `gigasamba/sbl_data_parsing`의 받을 판(태그·커밋). zip을 푼 폴더(`sbl_data_parsing-<판>`)를 벌 폴더 이름(`sbl_data_parsing-main-<번호>` — 아래 "한 서버에 여러 벌")으로 바꾼 것이 코드 폴더다. zip은 `CODE_COMMIT`을 채운다(git clone은 안 채움 — 시작 로그의 커밋이 틀 그대로).
- 이미지: 비공개 `jehunlee302/sbl_images`. 판 폴더마다 실행 이미지를 분할한 조각과 `load.sh`가 있다.

```
<공용 폴더>/                                  ← 예 /home/sbl/
├── sbl_images-main/                         ← 공용 — load.sh · readme.md · <판>/BUILD.txt · <판>/<이미지>/*.tar.gz.part* + *.sha256(서버에 한 번 load)
├── opencode.json                            ← 공용 — 개발 작업 공간의 opencode 접속 설정(선택 — UID 10001, 640 · 아래 "개발 작업 공간")
├── sbl_data_parsing-main-1/                 ← 벌 1 = 코드 폴더 = 루트(코드 · VERSION · CODE_COMMIT · deploy/docker/DEPS_HASH)
│   ├── settings.yaml  edw_chain.yaml        ← settings.sample.yaml·기본 사슬을 host_ctl.sh init이 없을 때만 복사
│   ├── output/                              ← 결과 폴더(host_ctl.sh init이 만듦 — 파싱 캐시가 있어 잃으면 전부 다시 처리 · 아래 _ 붙은 폴더는 임시 자리)
│   │   ├── _docflow/<번호>/  _staging/  _faq_seen.txt  _mcp_parse/jobs/  _llm_spend/
│   │   └── logs/                            ← DB 로그를 못 쓸 때의 예비 파일만
│   └── home/                                ← 개발 작업 공간 홈(option.devbox.ssh_port를 적었을 때만 init이 만듦)
└── sbl_data_parsing-main-2/                 ← 벌 2(아래 "한 서버에 여러 벌")
```

검색 DB(pgvector — 따로 떠 있는 PG 컨테이너)는 벌 폴더 밖이라 판이 바뀌어도 같은 DB를 보고, 모든 벌이 같은 기준 스키마(`required.pg.pg_schema`)를 함께 쓴다.

**미리 있어야 하는 것(서버 — 한 번 확인)**

| 무엇 | 확인 명령 | 없으면 |
|---|---|---|
| podman과 compose 하위 명령 | `podman compose version` | `dnf install podman-compose`(사내 RHEL 저장소). 없으면 인터넷 PC에서 서버와 같은 python 판으로 `pip download podman-compose -d pc-wheels` → 서버에서 `python3 -m pip install --no-index --find-links pc-wheels podman-compose` |
| 호스트 python 3.9 이상과 PyYAML | `python3 --version` · `python3 -c 'import yaml'` | 3.9 이상은 서버 관리자에게 요청한다(호스트 스크립트가 읽는 `common/config/layout.py`가 3.9 문법을 씀 — RHEL 8의 기본 `python3`는 3.6). PyYAML은 `dnf install python3-pyyaml` |
| unzip | `unzip -v` | `dnf install unzip` |
| PostgreSQL 16 + pgvector, 우리 DB·계정 | DB 담당에게 확인 | DB 담당이 만든다. 확인할 것 셋: ① PG가 **이 서버에 컨테이너로** 떠 있다(백업·문서 수 세기가 그 컨테이너 안에서 `psql`을 씀 — 이름을 `required.deploy.pg_container_name`에 적음) ② 계정에 그 DB의 **스키마 만들기 권한**이 있다(`GRANT CREATE ON DATABASE <DB> TO <계정>` — `migrate up`이 `<pg_schema>`·`<pg_schema>_master`·`<pg_schema>_<원천>`·`applog`를, 개발 서버의 배포 판정 시험이 임시 `test_*`를 만듦) ③ `vector` 확장(관리자가 한 번 — §5-3 ③ 0번) |
| 운영 그룹 | `id -gn <운영 계정>` · `getent group <그룹>` | 서버 관리자에게 받는다 |

**컨테이너 도구는 root podman 하나로 쓴다.** 셸을 열면 먼저 `export DOCKER=podman`, settings.yaml에 `ops.host.container_cli: podman`. 일반 사용자 셸이면 `DOCKER="sudo podman"`. 이미지를 불러온 저장소와 띄우는 저장소가 같아야 한다(rootless와 root podman은 이미지를 따로 보관).

<a id="서버-설치-순서"></a>
**서버 설치 순서**(처음 한 번 — root 셸, `<루트>` = 벌 폴더 = 코드 폴더)

0. `export DOCKER=podman` — 위 "미리 있어야 하는 것"을 확인한다.
1. 공용 폴더를 만들고 이미지 zip과 코드 zip을 거기에 푼 뒤, 코드 폴더 이름을 벌 폴더 이름으로 바꾼다.
   ```bash
   mkdir -p /home/sbl && cd /home/sbl                # 공용 폴더(자리는 아무 곳)
   unzip -q <이미지 zip> && unzip -q <코드 zip>       # 기대: sbl_images-main/ · sbl_data_parsing-<판>/
   mv sbl_data_parsing-<판> sbl_data_parsing-main    # 한 벌 — 번호 없음(운영 서버는 늘 이것)
   B=/home/sbl/sbl_data_parsing-main                  # 아래 <루트> — 새 셸을 열면 다시 적는다
   ```
   개발자마다 벌을 나누는 개발 서버만 `sbl_data_parsing-main-1`처럼 끝에 번호를 붙인다. 번호가 있으면 4번의 포트 두 칸을 꼭 바꾼다(아래 "한 서버에 여러 벌").
2. 이미지를 불러온다(공용 폴더에서 — 서버에 한 번, 이미 불러온 판이면 건너뜀). `<이미지 판>`은 `ls sbl_images-main/`에 보이는 판 폴더 이름이다: `cd /home/sbl && DOCKER=podman bash sbl_images-main/load.sh <이미지 판>` — 조각 sha256 확인 → 합치기 → load, 끝에 `<판>/BUILD.txt`(빌드 커밋·DEPS_HASH). **코드의 `deploy/docker/DEPS_HASH`가 `BUILD.txt`의 DEPS_HASH와 같은 판**을 고른다(확인 명령 — [§1-3](#실행-모드)).
3. 루트 채우기: `cd <루트> && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>` — `output/`·`output/_mcp_parse/jobs`(UID 10001, 2775)(settings.yaml에 `option.devbox.ssh_port`가 있으면 `home/`도 — 10001, 700), 코드 a+rX(`settings.yaml`·`edw_chain.yaml`·`output/`·`home/`은 빼고), `settings.sample.yaml` → `<루트>/settings.yaml`, `resources/config/edw_chain.yaml` → `<루트>/edw_chain.yaml`(둘 다 없을 때만, 10001:<운영 그룹> 640). 끝에 빈 필수 칸 **이름**을 찍는다. 여러 번 불러도 안전하다.
4. 설정을 채운다 — `<루트>/settings.yaml` 맨 위 `required`의 빈 값(§5-3 ② "꼭 채울 값"). 이미지 칸에는 2에서 불러온 실행 이미지 태그(`data-pipeline-runtime:<이미지 판>`·`mcp-server-runtime:<이미지 판>`). 자원 상한도 본다(아래).
   - **번호가 붙은 벌 폴더**(`…-main-1`)면 `search.server.mcp_port`·`ops.services.data_parsing.data_parsing_port`를 기본값(8765·8766)이 아닌 값으로 적는다 — 그대로면 5번에서 `[설정] 여러 벌 — … 기본값 그대로`로 멈춘다.
   - **개발 서버**는 `required.source.source_systems: [DEV-<번호>]`를 적는다 — 비우면 운영 5개 원천 전부를 파싱한다.
   - 운영 기준 결과를 내려면 `transform.represent.post_steps: all`([env-guide "서버 값으로 적는 칸"](docs/operations/env-guide.md)).
   - `required.deploy.host_docs_dir`는 서버에 **이미 있는 폴더**여야 한다(없으면 `mkdir -p` 후 UID 10001이 읽을 수 있게).
   - `init`이 찍는 "빈 필수 칸" 목록에는 비워도 되는 칸(`source_systems`·모델 `*_api_key` 등 — sample 주석 `[선택]`)도 섞여 있다. 무엇을 꼭 채울지는 §5-3 ② 표로 판단한다.
   - 다 적은 뒤 칸 이름이 맞는지 한 번 읽어 본다 — [env-guide §4 "칸 이름 확인"](docs/operations/env-guide.md#4-확인)(기대 `설정-읽힘`). 틀린 칸이 있으면 5번에서 모든 컨테이너가 시작을 거부한다.
   - EDW 표 설명 자료(`catalog.json`·`columns.jsonl` — 개인정보 없는 자료, 받는 곳은 refactor.md C-91)를 루트 아래 결과 폴더에 복사하고(`<루트>/output/edw_meta/`, UID 10001이 읽을 수 있게) `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`를 적는다. 없으면 `edw_meta` 도구만 `not_configured`로 답한다(나머지 도구는 그대로).
5. `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline`(코드 폴더에서 — DB 도구가 그 안에서 돈다).
6. DB 표를 만든다 — [§5-3 ③](#5-3-서버--처음-설치-자세히)의 명령(검토용 SQL → `migrate up` → `migrate master load` → `migrate check`).
7. `bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp`(검색 MCP는 시작할 때 마스터 표를 읽으므로 6 뒤).
8. `bash deploy/host/scripts/host_ctl.sh check` — check_env → ping_models → migrate check → 두 이미지 selftest → 검색 MCP `/health`, 처음 실패에서 멈춘다. 기대 마지막 줄: `[host_ctl check] 통과 — 6개`. 실행 이미지(`*-runtime`)면 스크립트가 자기 코드 폴더를 `/app/deploy`에 붙인다(셸·systemd에 `CODE_DIR`가 있으면 그 값).
9. 첫 실행을 확인한다.
   - 판: `bash deploy/host/scripts/host_ctl.sh logs data-pipeline 2>&1 | grep -m1 '^\[image\]'` — 기대 `[image] 이미지 … · 코드 <커밋> · 의존성 …`.
   - 게시 미리보기: §5-3 ④의 `pipe_exec.sh publish --dry-run`(쓰기 0).
   - 문서 2건: [핵심 명령](#핵심-명령) "파이프라인 한 번(시험 2건)" — 기대 `progress.log` 끝 줄 `… 종료 코드 0 ===`.
   - 검색: 서버용 `mcp_smoke` 명령은 [server-guide §4](docs/operations/server-guide.md#4-검색-mcp-사용) — 기대 끝 줄 `MCP 바깥 호출 통과`.
10. 자동 실행을 켠다 — `bash deploy/host/scripts/host_ctl.sh timers`(§5-5). 다른 서버의 AI 클라이언트가 붙어야 하면 아래 "밖에서 붙기".

**자원(기본 상한 — 합계 CPU 9 · 메모리 36g)**

| 컨테이너 | CPU · 메모리 기본 | settings.yaml 칸 |
|---|---|---|
| `data-pipeline` | 5 · 24g | `ops.containers.pipeline.pipeline_cpus` · `pipeline_mem_limit` |
| `mcp-data-parsing` | 3 · 8g(CPU 나눔 비율 4096 — 일괄 1024보다 먼저) | `ops.containers.data_parsing.data_parsing_cpus` · `data_parsing_mem_limit` · `data_parsing_cpu_shares` |
| `mcp-server` | 1 · 4g | `ops.containers.mcp.mcp_cpus` · `mcp_mem_limit` |

서버 CPU 수보다 큰 값은 컨테이너 도구가 거부한다. CPU 4개 서버라면 예: `ops.containers.pipeline.pipeline_cpus: 2`, `data_parsing_cpus: 1`(그러면 `tuning.ops.services.data_parsing.mcp_parse_engine_processes`도 1 이하), `ops.containers.mcp.mcp_cpus: 1`. 바꾼 뒤 `host_ctl.sh up -d --force-recreate …`.

**밖에서 붙기(다른 서버의 AI 클라이언트)**
- 기본 바인드는 `127.0.0.1`. 밖에서 붙게 하려면 `search.server.mcp_bind_host`에 서버 IP를 적는다(`0.0.0.0`은 거부).
- 이때 `required.tokens.mcp_token`가 꼭 있어야 한다(없으면 시작 거부). 만들기: `openssl rand -hex 32`.
- 방화벽에서 `search.server.mcp_port`(기본 8765)를 연다 — 예: `firewall-cmd --add-port=8765/tcp --permanent && firewall-cmd --reload`.

**한 서버에 여러 벌 띄우기(개발자별 — 폴더 이름 끝 번호로 나뉨, 개발 서버만)**
- 벌 폴더(코드 폴더) 하나가 한 벌이다. 개발자마다 공용 폴더 아래 벌 폴더를 하나씩 둔다(`sbl_data_parsing-main-1/`·`sbl_data_parsing-main-2/` …). 이미지는 공용 폴더에서 이미 불러왔으므로 설치 순서 2번은 건너뛴다.
- 폴더 이름 끝 `-<숫자>`가 벌 번호다 — 컨테이너·compose 묶음·systemd 단위 이름 끝에 `-<숫자>`가 붙는다. 끝이 `-<숫자>`가 아니면(`sbl_data_parsing-main`·`sbl_data_parsing-0.3.0`) 한 벌 — 이름 그대로.

| 벌 폴더 | 컨테이너 | compose 묶음 | 타이머 |
|---|---|---|---|
| `sbl_data_parsing-main` | `data-pipeline` · `mcp-data-parsing` · `mcp-server` | `compose` | `data-pipeline-nightly.timer` · `mcp-server-keepalive.timer` |
| `sbl_data_parsing-main-2` | `data-pipeline-2` · `mcp-data-parsing-2` · `mcp-server-2` | `compose-2` | `data-pipeline-nightly-2.timer` · `mcp-server-keepalive-2.timer` |

- 포트는 벌마다 그 벌의 `settings.yaml`에 다르게 적는다 — `search.server.mcp_port`(검색 MCP, 기본 8765) · `ops.services.data_parsing.data_parsing_port`(작업 서비스, 기본 8766) · (작업 공간을 켜면) `option.devbox.ssh_port`. **번호가 붙은 벌은 `-1`이라도 앞 두 포트가 기본값 그대로면 시작 거부**(다른 벌과 겹침).
- 운영 서버(`prd`)에서 번호가 붙은 폴더면 시작 거부(종료 2 — 운영은 한 벌, 폴더 이름에서 번호를 뗀다).
- PG 스키마·EDW 기록 표·게시 경로는 벌마다 나뉘지 않는다 — 모든 벌이 같은 기준 스키마를 함께 쓴다. 그래서 **모든 벌이 같은 코드 판**이어야 한다(DB 표 판이 하나). `migrate up --target all`·`migrate master load`는 공용 DB에 아무 벌 하나에서 한 번.
- 개발 서버에서 개발자는 SSH로 `data-pipeline` 컨테이너 안에 들어가 작업한다(`option.devbox` — 아래 "개발 작업 공간"). `RUN_ENV`는 모든 벌이 `dev` 그대로이고, 벌은 폴더 끝 `-1`·`-2`와 자기 원천 `DEV-<숫자>`로 나뉜다.
- 벌마다 문서를 나누는 것은 원천이다 — 그 벌의 settings.yaml `required.source.source_systems`에 자기 원천 `DEV-<숫자>`(예 `[DEV-2]`)를 적으면 그 문서만 파싱해 원천 스키마 `<기준>_dev_<숫자>`에 적재하고 `DEV-<숫자>/…`에 게시한다. **비우면 운영 5개 원천 전부를 파싱한다.** 벌 번호와 `DEV-<숫자>`는 따로 정해지므로 같은 숫자로 맞춰 쓴다.
- 새 `DEV-<숫자>`를 넣은 벌은 `migrate up --target search`를 한 번 해 원천 스키마를 만든다(없으면 적재가 멈춤). ⚠️ 이 명령은 어느 벌에서 부르든 **DB에 있는 모든 `<기준>_dev_*` 스키마(다른 벌 것 포함)를 함께 끝 판으로 올린다.** 검토용 SQL·순서는 [handover-guide §5](docs/operations/handover-guide.md#5-db-판--검토용-sql-뽑기--migrate-up).
- compose를 직접 부르지 않는다 — `host_ctl.sh`가 폴더 이름과 settings.yaml로 이름·포트를 채운다. 컨테이너 명령은 셸 `DOCKER`가 있으면 그 값, 없으면 `ops.host.container_cli`.
- 만드는 명령(벌 폴더 → init → 칸 채우기 → 띄우기 → 점검)과 벌마다 다른 칸의 예는 [handover-guide §13](docs/operations/handover-guide.md#13-두-번째-벌-만들기), 칸 정리는 [server-guide §1-3](docs/operations/server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별).

**컨테이너 이름·볼륨 바꾸기**
- 이름은 settings.yaml의 밑 이름 + 벌 번호다 — `ops.containers.<pipeline|data_parsing|mcp>.<…>_container_name`(기본 `data-pipeline`·`mcp-data-parsing`·`mcp-server`) · `ops.host.compose_project`(기본 `compose`). 바꾸기 전에 옛 이름의 컨테이너를 `host_ctl.sh down`으로 내린다(새 이름으로 하나 더 뜨지 않게).
- 볼륨·env를 더하려면 compose 파일을 하나 더 만들고(틀: `deploy/host/compose/extra.example.yml` — 호스트 경로는 절대 경로나 `${RAG_ROOT}`로, 끝에 `:z`) `ops.host.extra_compose`에 적는다(상대 경로는 루트 기준 — 예 `compose.extra.yml` = `<루트>/compose.extra.yml`, 없는 파일이면 `host_ctl.sh` 종료 2). `host_ctl.sh`와 MCP 살리기 타이머(`mcp_keepalive.sh`)가 늘 맨 뒤에 붙인다.
- 사슬 사본·작업 공간 홈의 호스트 자리: `ops.host.host_edw_chain_file`(기본 `<루트>/edw_chain.yaml`) · `option.devbox.home_dir`(기본 `<루트>/home`) — 상대 경로는 루트 기준.
- 순서(옛 이름 `down` → 칸 적기 → `config --quiet` → `up -d`)는 [handover-guide §12](docs/operations/handover-guide.md#12-컨테이너-이름볼륨-바꾸기).

**개발 작업 공간(SSH·opencode — 개발 서버만, 선택)**
- 네 이미지 모두 개발 도구(sshd·git·uv·ruff·mypy·pytest·ripgrep·sqlite3·tmux·vim 등)와 opencode(이미지를 만들 때 `assets/opencode/opencode`가 있으면)를 담고 있다. 앱은 이 도구를 쓰지 않는다 — 켜지 않으면 이미지는 지금처럼 돈다.
- 켜기: 그 벌의 `settings.yaml` 맨 아래 `option.devbox.ssh_port`에 포트를 적고(개발자마다 다르게) `host_ctl.sh init --group <운영 그룹>`을 다시 불러 `<루트>/home`(10001, 700)을 만든다(없으면 `host_ctl.sh up`이 종료 2). 그러면 `host_ctl.sh`가 `data-pipeline`을 SSH 작업 공간으로 띄운다 — 명령 `devbox`(sshd, 컨테이너 사용자 UID 10001 · 열쇠 로그인만), 코드 폴더를 쓰기 가능으로, 홈 `/home/rag` = `<루트>/home`. 실행 이미지(`*-runtime`)에서만 되고, 운영(`prd`)이면 `host_ctl.sh`가 거부한다(종료 2).
- opencode는 내부망 모델만 쓴다(외부 모델 목록 받기·자동 업데이트 끔). 첫 시작에 홈의 `~/.config/opencode/opencode.json`에 틀이 복사되니 모델 주소(`baseURL` — OpenAI 호환 `/v1`)·이름(`<model id>` 두 곳)을 채운다. 키가 필요한 모델이면 SSH 셸에서 `export INTERNAL_LLM_API_KEY=<키>`(틀이 이 env를 읽음 — 컨테이너 env·settings.yaml에는 넣지 않는다). 연결 모듈은 opencode에 들어 있어 폐쇄망에서 따로 받지 않는다. 공용 폴더에 둔 설정 파일 하나(`<공용 폴더>/opencode.json`)를 모든 벌이 같이 쓰려면 벌마다 settings.yaml `option.devbox.opencode_config`에 그 호스트 경로를 적는다(읽기 전용으로 붙고 `OPENCODE_CONFIG`가 가리킨다). 이 파일은 코드 폴더 밖이라 키를 직접 적어도 된다 — 주인 UID 10001·권한 640(settings.yaml과 같게). 파일 하나를 붙이므로 고친 뒤에는 `host_ctl.sh restart data-pipeline`(편집기가 파일을 새로 바꿔 쓰면 컨테이너는 옛 내용을 계속 본다).

```bash
# <루트>/settings.yaml 맨 아래
#   option:
#     devbox:
#       ssh_port: 2222
#       opencode_config: /home/sbl/opencode.json   # 선택 — 공용 opencode 설정
mkdir -p <루트>/home/.ssh && cp <내 공개 열쇠>.pub <루트>/home/.ssh/authorized_keys   # init이 만든 <루트>/home(10001, 700)
chown -R 10001 <루트>/home/.ssh && chmod 700 <루트>/home/.ssh && chmod 600 <루트>/home/.ssh/authorized_keys
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline        # data-pipeline이 sshd로 뜸(호스트 네트워크 — 포트 게시 없음)
ssh -p 2222 rag@<서버>                                           # 접속 뒤 cd /app/deploy — 코드 폴더(쓰기 가능), 컨테이너와 같은 env
```
- git 계정(선택): `option.devbox`에 `gitea_url`(내부망 gitea 주소 — `https://` 권장, http면 토큰이 암호화 없이 감)·`gitea_user`·`gitea_token`(비밀)을 모두 적으면 작업 공간이 시작할 때 `~/.git-credentials`(권한 600)의 그 호스트 줄을 쓰고(다른 줄은 그대로) `credential.helper store`로 설정한다. `git_user_name`·`git_user_email`을 적으면 커밋 이름·메일도. 토큰은 컨테이너 env로 넘기지 않고 붙인 settings.yaml에서 직접 읽는다 — 셋 중 하나라도 비우면 전에 쓴 그 호스트 줄을 지운다. 채우는 법: [gitea-guide §2](docs/operations/gitea-guide.md#2-개발자-한-벌-만들기).
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

상주 컨테이너 3개(서비스 이름 `data-pipeline`·`mcp-data-parsing`·`mcp`)는 `deploy/host/scripts/host_ctl.sh`로 다룬다 — settings.yaml을 읽어 셸 변수로 넘기고, 실행 이미지면 코드 폴더를 붙여(`compose.code*.yml`) compose 파일을 함께 부른다. compose 하위 명령을 그대로 넘긴다(`up -d`·`ps`·`logs`·`stop`·`down`·`config` — [핵심 명령](#핵심-명령)).

<a id="compose-파일-읽는-법"></a>
**compose 파일 읽는 법**(`deploy/host/compose/*.yml`)
- 맨 위 `x-settings:`·`x-code:`는 서비스가 아니라 함께 쓰는 YAML 조각이다 — `x-settings`는 settings.yaml을 읽기 전용으로 붙이는 줄, `x-code`는 코드 폴더를 `/app/deploy`에 붙이는 줄.
- `${PARSE_CPUS:-5}` 같은 값은 `host_ctl.sh`가 settings.yaml에서 넘긴다(`load_settings.sh`). 비면 `:-` 뒤 기본값, `${…:?…}`는 꼭 있어야 하는 칸.
- 그래서 compose를 직접 부르면 값을 못 받아 `:?`에서 멈추거나 기본값으로 뜬다. 바꿀 값은 settings.yaml에 적고 `host_ctl.sh`로 다시 띄운다. `host_ctl.sh`는 부를 때마다 settings.yaml을 다시 읽는다.

**② 설정 파일과 결과 폴더** — `host_ctl.sh init`(§5-0 3번). 결과 폴더는 `<루트>/output`이다(다른 곳에 둘 때만 `ops.host.host_output_dir`를 먼저 적는다). 서버에서 직접 만드는 파일(자리·예시·권한)은 [release-and-patch §9](docs/operations/release-and-patch.md#9-서버에서-직접-만드는-파일).

<a id="꼭-채울-값"></a>
**꼭 채울 값 — 서버 settings.yaml.** "형식 예"는 모두 가짜 값이다. dev = 개발 서버, prd = 운영 서버.

| 칸 | 무엇 | 어디서 받나 | 형식 예(가짜) | 환경 | 틀리면 어디서 잡나 |
|---|---|---|---|---|---|
| `required.env.run_env` | 실행 환경 | 정해진 값 | `dev` · `prd` | PC·dev·prd | 모든 명령이 시작 거부 |
| `required.pg.pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password`·`pg_schema` | 검색 DB(pgvector) — `pg_schema`는 비우면 `data_parsing` | DB 담당 | `pg.example.local` · `5432` · `rag` · `rag_app` · `<비밀>` · (비움) | PC·dev·prd | `host_ctl.sh check` ① check_env · ③ migrate check |
| `required.models.embed_base_url`·`embed_model`·`embed_api_key` | 임베딩 모델(`embed_model`은 적재·검색 때 같아야 함) | 모델 담당(내부망 주소) | `http://llm.example.local:8000/v1` · `<모델>` · `<비밀>` | PC·dev·prd | `host_ctl.sh check` ② ping_models |
| `required.models.llm_*`·`vlm_*` | LLM·VLM 모델 | 모델 담당 | `http://llm.example.local:8001/v1` · `<모델>` | dev·prd | `host_ctl.sh check` ② ping_models |
| `required.edw.edw_host`·`edw_port`·`edw_database`·`edw_read_*` | 회사 DB(EDW) 접속 — 읽기 계정(원천 목록·`query_edw`, EDW는 읽기만 함 — 쓰기 계정 칸은 없음) · `edw_port`는 비우면 1433 | DB 담당 | `edw.example.local` · (비움) · `EDW` · `<계정>` · `<비밀>` | dev·prd | `run_pipeline` 시작(빠지면 칸 이름을 찍고 멈춤) · `pipe_exec.sh publish --dry-run`(④) |
| `required.edw.edw_file_table` | 파싱 대상 파일 목록을 읽을 EDW 표(`<스키마>.<표>` — 영문·숫자·_만) · 기본 `AI.FileStorageMap` | DB 담당 | `AI.FileStorageMap` | dev·prd | 설정을 읽을 때(꼴이 틀리면 시작 거부) · `run_pipeline` 대상 목록 |
| `dev.local.*` | PC 전용 값(가짜 EDW·게시 폴더·원본 폴더·새 문서 상한) — **서버는 읽지 않음**(`local_edw_sqlite_file`이 적혀 있으면 EDW를 쓸 때 거부) | — | (sample 그대로) | PC만 | — |
| `required.publish.publish_bucket`·`publish_prefix` | silver 게시 위치 — 버킷(원천 원본 버킷과 달라야 함)과 그 안 경로 접두. **둘 다 비우면 안 된다**(sample은 `publish_prefix`를 `[선택]`으로 적지만 `run_pipeline`은 비면 `설정 필요`로 멈춤). PC는 `publish_bucket` 대신 `dev.local.local_publish_dir` | 운영 담당 | `rag-silver` · `parse` | dev·prd | `run_pipeline` 시작 · publish 미리보기 |
| `required.object_storage.object_storage_endpoint`·`object_storage_access_key`·`object_storage_secret_key` | Object Storage(S3 호환) 접속 | 스토리지 담당 | `https://os.example.local:9000` · `<비밀>` · `<비밀>` | dev·prd | `run_pipeline` 시작 · publish `--apply` |
| `common.connections.object_storage.object_storage_region`·`object_storage_verify_tls` | 리전(비우면 `us-east-1`)·TLS 검증(비우면 `1` — 사내 CA면 CA 파일 경로). **`required` 아래가 아니다** | 스토리지 담당 | (비움) · (비움) | dev·prd | 설정을 읽을 때(자리가 틀리면 시작 거부) |
| `extract.source.source_input_location`·`source_default_bucket`·`source_uri_prefix` | 원본 위치 — `source_default_bucket`은 서버에서 **필수**(`run_pipeline`이 비면 멈춤) | 운영 담당 | `rdb:csv:<루트>/list.csv` · `<버킷>` · `s3://<버킷>/<접두>` | dev·prd | 첫 `run_pipeline` |
| `required.tokens.mcp_token` | MCP 토큰 하나 — 검색 MCP와 `parse_document` 작업 서비스가 함께 씀 | `openssl rand -hex 32` | 64자 16진수 | dev·prd | `host_ctl.sh check` ⑥ `/health` · `parse_document` 호출이 토큰 오류 |
| `required.tokens.fulltext_sign_key` | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 `sfid` 서명 키 — 비우면 두 도구가 `not_configured`, 바꾸면 이미 발급한 sfid가 모두 무효 | 같은 명령 | 64자 16진수 | dev·prd | 원문 도구 호출이 `not_configured` |
| `required.deploy.pipeline_image` · `mcp_image` | 띄울 이미지 태그(같은 배포 묶음) | §5-0 2번 `load.sh` | dev: `data-pipeline-runtime:<이미지 판>` · prd: `data-pipeline:<VERSION>` | dev·prd | `host_ctl.sh up`이 이미지 없음으로 멈춤 |
| `required.deploy.host_docs_dir` | 원본 문서 폴더(서버에 이미 있는 폴더) | 서버 관리자 | `/data/docs` | dev·prd | `host_ctl.sh up`이 `:?` 안내로 멈춤 |
| `ops.host.host_output_dir` | 결과 폴더 — 비우면 `<루트>/output` | 서버 관리자 | (비움) | dev·prd | — |
| `required.deploy.pg_container_name` | `pg_dump`·`psql`을 exec할 PG 컨테이너 이름 | DB 담당 | `<컨테이너>` | dev·prd | 백업 명령([upgrade-guide §2](docs/operations/upgrade-guide.md#2-백업)) |
| `ops.host.container_cli` | 컨테이너 도구 | 정해진 값 | `podman` | dev·prd | 호스트 스크립트가 다른 도구를 부름 |

그 밖 칸은 비워 두면 코드 기본값을 쓴다([env-guide "서버 값으로 적는 칸"](docs/operations/env-guide.md)도 본다). 모델 주소는 모두 내부망 주소여야 한다.

**③ DB 마이그레이션** — 적재·검색 전에 끝낸다. `pipe_exec.sh`는 상주 `data-pipeline` 안에서 돌므로 먼저 `host_ctl.sh up -d data-pipeline`.

> ⚠️ 0.1.0이 쓰던 스키마에 `up`하면 옛 표가 지워진다. 새 서버가 아니면 [upgrade-guide.md](docs/operations/upgrade-guide.md)를 따른다.

```bash
# 0. (DB마다 처음 한 번 — DB 관리자) vector 확장 — 없으면 migrate·적재가 "vector 확장 없음"으로 멈춘다
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
bash deploy/host/scripts/pipe_exec.sh migrate check --target all                # 지금 판(읽기만)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원> --sql /app/output/up.sql   # DB 담당 검토용 SQL만 <루트>/output/up.sql에(DB에 붙지 않음)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 담당 승인 뒤. 차원 = 임베딩 모델 출력 길이(모델 담당 확인 — 새 스키마만, 이미 표가 있으면 DB 차원)
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

- EDW 로그인과 Object Storage 버킷을 따로 확인하는 명령은 없다. 첫 파싱 뒤 publish 미리보기(`bash deploy/host/scripts/pipe_exec.sh publish --dry-run` — 쓰기 0)로 확인하고, 실제 publish 한 번 뒤 Object Storage 파일을 본다 — 명령은 [upgrade-guide §10](docs/operations/upgrade-guide.md#10-올린-뒤-점검).
- ⚠️ 실제 publish(`pipe_exec.sh publish`)는 한 번만 한다. 다시 돌리면 Object Storage에 같은 결과를 새 시각 이름으로 또 올린다.

**⑤ 이미지 점검**

```bash
$DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> check-modules
bash deploy/release/selftest_gate.sh $DOCKER run --rm --network host -v "$PWD/settings.yaml:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=dev -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> selftest   # 기대: [판정] 통과 — FAIL 0
bash deploy/release/selftest_gate.sh $DOCKER run --rm --network host -v "$PWD/settings.yaml:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=dev -v "$PWD:/app/deploy:ro,z" mcp-server-runtime:<판> selftest      # 기대: [판정] 통과 — FAIL 0
```

selftest는 종료 코드가 아니라 `[판정]` 줄로 판정한다. 운영 서버(구운 이미지)는 `-v …` 없이 `data-pipeline:<판>`·`mcp-server:<판>`.

**⑥ 검색 MCP 띄우기** — `bash deploy/host/scripts/mcp_keepalive.sh`(여러 번 실행해도 안전 — `/health`가 응답하면 그대로, 꺼져 있으면 띄우고, 응답이 없으면 재시작).

### 5-4. 서버 — 파이프라인 실행

| 방법 | 명령 | 순서 | 언제 |
|---|---|---|---|
| 문서별 흐름 | `python3 deploy/host/scripts/run_pipeline.py …`(코드 폴더에서, nohup) | 문서마다 파싱 → publish → 원본 삭제(게시 성공 뒤) → 구조화·적재 | 대량 처리 |
| 새벽 배치 | systemd `data-pipeline-nightly.timer` → `nightly_batch.sh scheduled` | `ops.nightly.nightly_start_time`에 `run_pipeline.py --start-offset 0 --skip-done --max-docs <상한> --deadline <마감>` | 정기 운영 |
| 파싱·게시만 | `bash deploy/host/scripts/pipe_exec.sh parse` · `pipe_exec.sh publish [--dry-run]` | 상주 컨테이너 안에서 한 번 | 단계 확인 |

`run_pipeline.py`는 기본으로 FileStorageMap의 모든 문서를 처음(시작 자리 0)부터 고른다 — 이름으로 좁힐 때만 `--filter <키워드,…>`. 새벽 배치는 run_pipeline 앞에 applog 파티션 정리(`migrate maintain --target applog` — 실패하면 경고만)를 돌린다.
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
| 새벽 배치 | systemd `data-pipeline-nightly.timer`(5분마다 깨움) + settings.yaml `ops.nightly.nightly_start_time: "HH:MM"`(그 시각부터 5분 안에 시작) · `ops.nightly.nightly_max_docs`(새 문서 수 상한, 1 이상) · `ops.nightly.nightly_stop_time: "HH:MM"`(마감 — 시작보다 5분 넘게 뒤). **셋 중 하나라도 비면 돌지 않는다**(기본 비움) |
| 재부팅 뒤 | 사람이 다시 띄운다(`podman-restart`는 켜지 않는다) — [server-guide §2-5](docs/operations/server-guide.md#2-5-서버를-다시-켠-뒤) 순서. 검색 MCP 두 개는 그 전에 keepalive 타이머(부팅 1분 뒤)가 먼저 띄울 수 있고, 일괄 `data-pipeline`은 사람이 띄우기 전까지 꺼져 있다 |

systemd 설치(DB 판과 컨테이너를 확인한 뒤 — 벌마다 그 벌 폴더에서, 새 판으로 덮어쓴 뒤에도 다시):

```bash
bash deploy/host/scripts/host_ctl.sh timers        # 단위 4개의 코드 폴더 자리를 이 코드 폴더로 채워 /etc/systemd/system에 쓰고 두 타이머를 켬
```

새벽 배치 타이머는 켜져 있어도 `ops.nightly` 세 칸을 채우기 전에는 아무것도 하지 않는다.

띄우기·멈추기·로그·설정 바꾼 뒤 다시 만들기는 [핵심 명령](#핵심-명령). 그 밖:
- 서버의 모든 컨테이너: `podman ps`(root로 띄웠으면 `sudo podman ps`) — 우리 벌만은 `host_ctl.sh ps`.
- 검색 MCP가 응답하나: `curl -s http://127.0.0.1:<search.server.mcp_port>/health`.
- 타이머 기록: `journalctl -u mcp-server-keepalive.service -n 50`.
- 다시 켜기: `host_ctl.sh up -d data-pipeline mcp-data-parsing mcp` → `systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer`(끌 때는 타이머부터 — 안 그러면 2분 안에 검색 MCP를 다시 띄운다).

### 5-6. 서버 — 생기는 파일

| 경로 | 왜 생기나 | 지워도 되나 |
|---|---|---|
| `<결과 폴더>/edw/embed_cache.sqlite` | 임베딩 캐시 | 지우면 다음 적재 때 임베딩을 모두 다시 부른다 — 지우지 않는다 |
| `<결과 폴더>/logs/*.jsonl` | DB 로그를 못 쓸 때의 예비 기록(`ops.log.log_fallback_dir`) | 문서 본문·질문이 들어갈 수 있다 — 밖으로 내보내지 않는다. DB가 돌아온 뒤 확인하고 지운다 |
| `<결과 폴더>/_docflow/` · `_staging/` | 문서 하나의 파싱 → 구조화·적재 작업 · 미리 받은 원본 | 문서가 끝나면 지워진다 |
| `<결과 폴더>/_mcp_parse/jobs/` | `parse_document` 작업 | 최근 30개만 남는다 |
| `<결과 폴더>/_llm_spend/` | 외부 모델 하루 지출 장부(PC만 — 서버에는 생기지 않음) | 지난 날짜는 지워도 된다 |
| `<루트>/settings.yaml` | 서버 설정 | **비밀값이 들어 있다** — 권한 640, 벌 폴더를 지울 때 함께 지운다 |
| `/var/tmp/bake/` | 개발 서버에서 구운 이미지 조각·코드 묶음 | 운영 서버로 옮긴 뒤 지워도 된다 |

### 5-7. 서버 — 값 바꾸기

| 바꿀 것 | 방법 |
|---|---|
| 설정 값 | settings.yaml을 직접 고치고 `host_ctl.sh up -d --force-recreate …`(서비스 이름 `mcp`, 컨테이너 이름 `mcp-server`). 다시 띄우기 전에 [env-guide §4 "칸 이름 확인"](docs/operations/env-guide.md#4-확인) |
| 이번 실행만 다른 값 | `--set 이름=값` |
| 엔진 구성 | 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 코드 폴더 바꾸기(§5-8) — 확인 `show-stack`([resources.md §1](docs/architecture/resources.md)) |

### 5-8. 새 판 올리기 — 덮어쓰기

벌 폴더(코드 폴더)에 새 코드를 덮어쓴다. **명령은 [upgrade-guide.md](docs/operations/upgrade-guide.md) 한 곳에만 있다** — 그 순서대로 복사해 친다. 큰 흐름:
1. 자동 실행을 멈추고 벌 폴더를 밖에 백업한다 — [upgrade-guide §2](docs/operations/upgrade-guide.md#2-백업)(서버에서 고친 코드는 gitea에도 올린다).
2. 실행 이미지가 바뀐 판이면 새 이미지를 불러온다 — [§3](docs/operations/upgrade-guide.md#3-새-실행-이미지-불러오기--의존성-지문-확인).
3. 옛 코드만 지우고 새 코드를 덮어쓴다 — [§4](docs/operations/upgrade-guide.md#4-벌-폴더에-새-코드-덮어쓰기).
4. 새 판에서 지운 설정 칸을 지우고 새 코드로 설정을 한 번 읽어 본다 — [§5](docs/operations/upgrade-guide.md#5-설정-고치기)(기대 `설정-읽힘` — 남은 칸이 있으면 모든 컨테이너가 시작을 거부한다).
5. DB 판을 올린다 — [§6](docs/operations/upgrade-guide.md#6-db-판-올리기--migrate-up).
6. 다시 띄우고 점검한다 — [§10](docs/operations/upgrade-guide.md#10-올린-뒤-점검)(`host_ctl.sh check` 마지막 줄 `[host_ctl check] 통과 — 6개`).
- 덮어써도 남는 것 — 지우거나 옮기지 않는다: `settings.yaml`·`edw_chain.yaml`·`output/`(파싱 캐시·임베딩 캐시·FAQ 교체 기록 — 잃으면 전부 다시 처리)·`home/`·`deploy/host/scripts/test_space/`(run_pipeline 진행 기록·잠금 — 위 명령이 옮겼다 되돌림).
- 옛 코드를 먼저 지우는 까닭: 새 판에서 지운 파일(옛 시험 등)이 남으면 `host_ctl.sh check`의 selftest가 그 파일 때문에 실패한다.
- 검색 DB는 같은 PG를 그대로 본다. 벌이 여럿이면 모두 같은 판으로 올린다(같은 기준 스키마).
- 되돌리기: 1의 백업을 벌 폴더 위에 다시 덮어쓰고 `host_ctl.sh up -d --force-recreate …`.
- 코드만 바뀐 판(`DEPS_HASH` 같음)은 이미지를 다시 만들지 않는다 — 개발 서버 [release-and-patch §1-1](docs/operations/release-and-patch.md#1-1-개발-서버--코드-폴더-덮어쓰기) → 운영 서버 §1-2(굽기).

---

## 6. 꼭 지킬 것

규칙 전체는 [CLAUDE.md](CLAUDE.md) §2~§5(핑거프린트·계약·비밀값·운영 접속 가드·배포 환경·새 패키지).

---

## 7. 문서

문서 지도는 [docs/INDEX.md](docs/INDEX.md). 알려진 문제·미개발 항목은 [docs/PRD.md](docs/PRD.md) 표의 `todo` 행.
