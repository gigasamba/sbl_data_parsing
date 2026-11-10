# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱하고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 개발은 macOS·Windows PC에서 하고, 실행은 내부망(폐쇄망) RHEL 서버의 Docker/podman 이미지 2개로 한다. 기능 요건은 [docs/PRD.md](docs/PRD.md), 문서 지도·용어집은 [docs/INDEX.md](docs/INDEX.md), 개발 규칙은 [CLAUDE.md](CLAUDE.md).

### 0. 읽기 전에 — 꼭 알아 둘 것

> **⚠️ `docker compose`를 직접 부르지 않는다.** 서버 컨테이너는 늘 `bash deploy/host/scripts/host_ctl.sh …`로 다룬다(server-guide §1-7).
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
| `$DOCKER` | 컨테이너 명령 — 서버는 `docker`(root 셸). 셸에서 `export DOCKER=docker` |

**목차** — [1. 한눈에 보기](#1-한눈에-보기) · [2. 폴더 구조](#2-폴더-구조) · [3. 설정](#3-설정) · [4. PC에서 실행하기](#4-pc에서-실행하기) · [5. 서버(내부망)에 배포하고 실행하기](docs/operations/server-guide.md#1-새-서버-설치) · [6. 꼭 지킬 것](#6-꼭-지킬-것) · [7. 문서](#7-문서)

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

버전은 저장소 루트 `VERSION` 하나이고 두 이미지가 함께 쓴다(태그 `data-pipeline:<버전>` — 규칙: [server-guide §5-2](docs/operations/server-guide.md#5-2-버전)).

<a id="실행-모드"></a>
**실행 모드(`required.env.run_env`)마다 컨테이너를 띄우는 법이 다르다.** 이미지는 모두 `deploy/docker/Dockerfile` 한 파일에서 나온다 — 공통 `base` 단계(Python + `requirements-core.txt`) 위에 검색 MCP는 `mcp-runtime`, 파이프라인은 `parse-deps`(`requirements-image.txt` + LibreOffice) → `pipeline-runtime`(+ OCR 모델)을 쌓은 것이 **실행 이미지**(코드 없음)이고, 거기에 코드를 COPY한 것이 **코드가 든 이미지**다.

| | local(PC) | dev(개발 서버) | prd(운영 서버) |
|---|---|---|---|
| 이미지(태그 꼴) | 없음 — Python으로 직접(§4). 이미지 시험만 코드가 든 이미지 `data-pipeline:<시험 태그>`·`mcp-server:<시험 태그>` | 실행 이미지 `data-pipeline-runtime:<이미지 판>`·`mcp-server-runtime:<이미지 판>` | 코드가 든 이미지 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>` |
| 코드가 오는 곳 | 저장소 체크아웃 그대로 · 시험 이미지는 빌드 때 COPY(Dockerfile 타깃 `pipeline`·`mcp`) | 코드 폴더(코드 git zip을 푼 폴더 — 예 `sbl_data_parsing-main-1`)를 컨테이너 `/app/deploy`에 읽기 전용(`:ro,z`)으로 붙임 | 이미지 안(굽기 때 COPY) — 붙이지 않음. 함께 오는 코드 묶음은 호스트 스크립트(`deploy/host/`)용 |
| 만드는 법 | `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh`(mcp는 `IMAGE_TARGET=mcp TAG=mcp-server:<시험 태그>`) | PC: `BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`(+ `mcp-runtime` — 이 커밋 코드를 붙여 selftest 판정) → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) → 개발 서버 `load.sh <이미지 판>`(server-guide §5-3). 의존성이 같으면 다시 만들지 않는다 | 개발 서버의 시험한 코드 폴더에서 `bash deploy/release/bake_prod_image.sh <이미지 판>` — 그 실행 이미지 위에 코드만 COPY(`deploy/docker/Dockerfile.bake`, 네트워크 없음) → 운영 서버 `load.sh <VERSION>`([server-guide §5-4](docs/operations/server-guide.md#5-4-개발--운영--시험한-그대로-굽기)) |
| 띄우는 법 | `.venv/bin/python -m mcp_server.main` 등(§4-4·§4-5) · 이미지 시험 `bash valid_env/docker/smoke_test.sh`(`valid_env/docker/compose.test.yml` — §4-7) | 코드 폴더에서 `bash deploy/host/scripts/host_ctl.sh up -d`(`compose-dev.yml` — 실행 이미지 + 벌 폴더를 `/app/deploy`에). 시작 스크립트 `runtime_entry.sh`가 마운트·의존성 지문을 확인하고 코드의 `deploy/docker/entrypoint.sh`로 넘긴다 | 같은 `host_ctl.sh up -d`(`compose-prd.yml` — 구운 이미지, 코드 폴더 마운트 없음) |
| 이미지 | 셸 변수 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`(이미지 시험) | `compose-dev.yml`에 `data-pipeline-runtime:<이미지 판>` · `mcp-server-runtime:<이미지 판>`(셸 `IMAGE_TAG`) | `compose-prd.yml`에 `data-pipeline:<VERSION>` · `mcp-server:<VERSION>`(셸 `IMAGE_TAG`) |
| `run_env` | `local`(저장소 루트 `settings.yaml`) | `dev` | `prd` |

**실행 이미지 판 고르기(dev·굽기).** 실행 이미지 판은 코드 판과 다를 수 있다. **이미지 판의 `BUILD.txt`에 적힌 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판**을 쓴다(값 = `requirements-core.txt`·`requirements-image.txt`의 지문, `bash deploy/release/deps_hash.sh`). 다르면 컨테이너가 `의존성 지문이 다름`으로 멈추고(종료 2) `bake_prod_image.sh`도 멈춘다 — 같은 값인 판이 없으면 새 실행 이미지가 필요하다([server-guide §5-3](docs/operations/server-guide.md#5-3-pc에서--실행-이미지-만들기와-이미지-저장소에-올리기)).

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

처음 설치(PC §4-4 ④, 서버 server-guide §1-5 6번) · 마이그레이션이 바뀐 릴리스(적재 전에 `up`) · 새 검색 스키마(임베딩 차원이 바뀜 — 새 `db_schema`에 `up --target all --schema <새 스키마> --dim <차원>`)일 때 실행한다. 자동 동작·오류 분기는 [server-guide §1-8](docs/operations/server-guide.md#1-8-db-표-만들기--migrate).

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
| 파싱할 원천 | `required.source.source_systems` — 원천 목록(쉼표 구분 — 예 `DEV-1` · `DEV-1, DEV-2` · `SFDC, CRMS`, 대소문자 무관). 값은 `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`·`DEV-<1~99>`이고, 비우면 운영 5개 원천(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`)을 파싱한다(`DEV-<숫자>` 행은 뺌). 원천은 EDW `AI.FileStorageMap.source_system` 칸 값이다. `DEV-…`는 dev·local에서만 쓰며, prd에 적혀 있으면 시작하지 않는다. `DEV-<숫자>` 문서는 검색 스키마 `<기준>_dev_<숫자>`에 적재된다 — 목록에 새로 넣으면 먼저 `migrate up --target search`(없으면 적재가 멈춤). PC 폴더 원천은 맨 위 `DEV-<숫자>/` 폴더도 원천 폴더이고, 같은 목록으로 거른다 |
| 칸별 안내 | [docs/operations/env-guide.md](docs/operations/env-guide.md) |
| 서버용 파일 | git에 올리지 않는다. `settings.sample.yaml`을 복사해 `required`를 채운다(server-guide §1-6 "꼭 채울 값"). **PC 파일을 그대로 복사하지 않는다** — PC의 `run_env: local`·`allow_external: true`가 서버에서 외부 모델 호출을 연다 |

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
   until docker exec pgvector pg_isready -h 127.0.0.1 -U pgvector -d rag; do sleep 1; done   # -h: 처음 만들 때의 초기화용 서버에 속지 않게
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

서버 설치, 환경별 실행 명령(local · dev · prd), 일상 운영, 새 판 올리기, 릴리스는 [docs/operations/server-guide.md](docs/operations/server-guide.md#3-일상-운영) 한 문서에 있다.

---

---

## 6. 꼭 지킬 것

규칙 전체는 [CLAUDE.md](CLAUDE.md) §2~server-guide §1(핑거프린트·계약·비밀값·운영 접속 가드·배포 환경·새 패키지).

---

## 7. 문서

문서 지도는 [docs/INDEX.md](docs/INDEX.md). 알려진 문제·미개발 항목은 [docs/PRD.md](docs/PRD.md) 표의 `todo` 행.

`parse_document`는 서버당 Redis 하나(`compose-redis.yml` — 공식 이미지, 8010)를 쓴다. 검색 MCP·작업 컨테이너는 벌 0만 띄운다. 설치·자원·AOF 운영은 [서버 가이드](docs/operations/server-guide.md#1-3-1-parse_document-redis-큐113), 배포 확인은 [C-116](docs/refactoring/refactor.md)을 따른다.
