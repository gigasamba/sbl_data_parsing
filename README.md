# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱하고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 개발은 macOS·Windows PC에서 하고, 실행은 내부망(폐쇄망) RHEL 서버의 Docker/podman 이미지 2개로 한다.

> 이 저장소는 서버 코드 사본을 리팩토링한 결과다(10-26~~10-29, 단계 S0~~S12). 무엇이 왜 바뀌었는지는 [docs/history/refactor_plan.md](docs/history/refactor_plan.md)에, **서버에 처음 배포하기 전에 사람이 할 일**은 [refactor.md](docs/refactoring/refactor.md) 맨 앞 "최종 — 사람이 할 일"에 있다.

**목차**

1. [한눈에 보기](#1-한눈에-보기) — 처리 흐름 · 실행 단위 · 이미지와 버전 · DB 마이그레이션
2. [폴더 구조](#2-폴더-구조)
3. [설정](#3-설정)
4. [PC에서 실행하기](#4-pc에서-실행하기) — 준비 → 파이프라인 → MCP 서버 → 검증 페이지
5. [서버(내부망)에 배포하고 실행하기](#5-서버내부망에-배포하고-실행하기)
6. [꼭 지킬 것](#6-꼭-지킬-것)
7. [문서와 알려진 문제](#7-문서와-알려진-문제)

---

## 1. 한눈에 보기

### 1-1. 처리 흐름

```
원천 문서(Object Storage · 폴더 · RDB 목록)
   │
   │  ① parse     중복 제거 → 쪽 방향 보정 → 엔진별 파싱 → 대표 결과(문서마다 하나)     ┐
   │  ② structure 청킹 · 사실 추출 · 임베딩 → 번들(bundle)                            │ data-pipeline 이미지
   │  ③ load      번들 → PostgreSQL(pgvector) 적재                                    │
   │  ④ publish   대표 결과를 Object Storage에 올리고 회사 DB(EDW)에 메타데이터 기록     ┘
   ▼
검색 MCP 서버 — 도구 4개: search · query_edw · parse_document · edw_meta                 mcp-server 이미지
```

MCP 도구 4개의 이름과 입출력은 외부 클라이언트와의 계약이라 바꾸지 않는다.

### 1-2. 실행 단위 — 모듈 4개는 폴더 3개와 1:1이 아니다

코드 폴더는 `extract` · `transform` · `load`로 나뉘지만, 실제로 실행되는 단위는 **모듈 4개**다.


| 모듈            | 하는 일                                    | 코드 폴더                                           | 결과(완료 표시)                           |
| ------------- | --------------------------------------- | ----------------------------------------------- | ----------------------------------- |
| **parse**     | 원천 읽기 · 중복 제거 · 준비 · **엔진별 파싱 + 대표 결과** | `extract/` 전체 + `transform/represent`·`figures` | `output/parse/_rep/` (`_DONE.json`) |
| **structure** | 청킹 · 사실 추출 · 임베딩 · 그래프 → 번들             | `transform/structure`                           | `output/edw/bundle/` (`_DONE.json`) |
| **load**      | 번들 → pgvector                           | `load/pgvector_load`                            | `output/edw/_LOADED.json`           |
| **publish**   | Object Storage 업로드 + EDW 메타데이터          | `load/publish_parse_result`                     | (운영 시스템에 기록)                        |


**순서는 "완료 표시 파일"로 지킨다.** DAG 엔진(Airflow 등)은 없다. 각 모듈은 시작할 때 앞 모듈의 `_DONE.json`을 확인한다(`pipeline/cli.py` `need()`).

- 앞 모듈의 완료 표시가 **없거나**, 다른 커밋으로 만든 결과(계약 버전·핸드오프 핑거프린트가 다름)면 → 종료 코드 **3**으로 멈춤
- 앞 결과를 **이미 처리했으면** → 아무것도 하지 않고 건너뜀(같은 명령을 여러 번 불러도 안전 — 다시 하려면 `--force`)
- 마감 시각에 걸리거나 같은 결과 폴더에서 다른 작업이 실행 중이면 → 종료 코드 **75**

> 파싱(엔진 실행)이 `extract`에 있는 것은 upstream 배치를 따른 결과다. 일반 ETL 기준(파싱 = transform)과 다르지만 옮기지 않기로 했다(사용자 10-31 범위 축소 — PRD [pl-17](docs/prd/transform.md#pl-17) dropped · 옛 논의는 [이력](docs/history/refactor_c_items.md) C-61).

### 1-3. 서버 이미지 2개와 버전


| 이미지             | 역할                                 | 컨테이너                                                                                                             |
| --------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `data-pipeline` | parse · structure · load · publish | 1회 실행 job(`parse`, `structure`, `load`, `publish`) · 상주(일 없이 떠 있음 — `run_docs.py`가 docker exec) `data-pipeline-parse`, `data-pipeline-structure` |
| `mcp-server`    | 검색 MCP(상주)                         | 상주 `mcp-server`                                                                                                  |


- **버전은 저장소 루트 `VERSION` 하나**(SemVer, 지금 `0.1.0`)이고 두 이미지가 함께 쓴다(D-036).
- 이미지 태그 = 버전(`data-pipeline:0.1.0`, `mcp-server:0.1.0`). 빌드한 커밋은 이미지 라벨 `org.opencontainers.image.revision`에 남는다.
- 회사 DB `AI.ParsingMeta.pipeline_version`과 실행 보드에도 이 버전이 기록된다(옛 값은 git 커밋 — DB 담당 협의 필요, refactor.md C-62).

### 1-4. DB — Alembic 마이그레이션

pgvector(PostgreSQL)의 테이블은 **코드가 실행 중에 만들지 않는다.** 모두 Alembic 마이그레이션(`common/store/db/migrations/versions/`)으로 만들고, 명령은 `dbtool`(PC: `python -m common.store.db.dbtool`, 서버: `compose run --rm load migrate`) 하나다. 스키마는 검색 스키마 하나다(`struct` 스키마는 사용자 11-01 결정으로 코드에서 없앴다 — pl-08).

| 마이그레이션 | 스키마 | 만드는 것 |
|---|---|---|
| `0001_search` | 기준 스키마(`required.pg.db_schema`, 예: `ai`) — `--target search` | 옛 한 벌 표(0002가 지움) |
| `0002_search` | 기준 스키마 + 원천 스키마 5벌(11-02 — pl-28) | 기준 `ai`: 판 표·공용 `doc_id_seq` · 원천마다 `ai_sfdc`·`ai_crms`·`ai_las`·`ai_faq`·`ai_other`: `doc` · `chunk` · `chunk_term` · `term_stat` · `corpus_stat` 테이블, 색인, 뷰 `v_chunk_source`(벡터 차원은 번들 `meta.json` 또는 `--dim`) |

- **엔진 구성은 DB가 아니라 파일이다** — 서버·PC 모두 `resources/config/pipeline_stack.json`을 읽는다(5-7). 원천 목록 `sources.json`은 11-01에 지웠다(원천은 폴더·`rdb:csv`만). 서버에 남은 옛 `struct` 스키마는 코드가 읽지 않는다(그대로 두거나 DB 담당자가 지움).
- **실행 기록은 파일이 아니라 DB에 남는다** — 스키마마다 `<스키마>.alembic_version`.

| 명령 | 하는 일 |
|---|---|
| `up --target search\|all` | 끝 버전까지 실행(테이블 생성). 옛 코드가 만든 기존 스키마는 먼저 비교해, 빠진 테이블·색인만 만들고 기록(컬럼 이름·형식이 다르면 거부) |
| `stamp --target …` | 이미 있는 DB에 **실행 없이 버전만 기록**(비교 차이 0일 때만) |
| `current --target …` | 지금 DB 버전과 코드의 끝 버전 |
| `check --target …` | 테이블 정의 ↔ 실제 DB 비교(읽기만 — 차이가 있거나 끝 버전이 아니면 종료 코드 1) |

**언제 실행하나**
- **처음 설치할 때** — PC 4-4 ④, 서버 5-3 ④.
- **마이그레이션이 바뀐 릴리스** — 패치 노트의 "DB 버전" 줄을 보고 적재 전에 `up`. 테이블·컬럼을 바꾸는 마이그레이션은 데이터 계약 변경이라 DB 담당 협의가 먼저다.
- **새 검색 스키마**(임베딩 차원이 바뀌어 새 `db_schema`를 쓸 때) — `up --target search --schema <새 스키마> --bundle <번들>`.

**자동으로 되는 것과 아닌 것**
- 검색 스키마: 적재(`pgvector_load` — run_docs가 문서마다 부름)가 새 스키마면 만들고 기록하며, 기록이 있으면 `up`한다. 기록이 없는 기존 스키마면 경고만 하고 적재를 계속한다.
- DB 버전이 코드보다 낮으면 적재가 종료 코드 2로 멈추고 `up`을 하라고 안내한다. DB가 코드보다 새 버전이면(이미지를 옛 버전으로 되돌린 뒤 등) 적재·`up`·`stamp` 모두 멈춘다.

---

## 2. 폴더 구조

```
.
├─ common/              공용 코드 — 두 앱(pipeline, mcp_server)이 함께 쓰는 것만
│  ├─ core/             경로 · 핑거프린트(FINGERPRINT, code_fp) · 핸드오프 계약 · 문자열 처리 · 실행 기록 · 버전 표기
│  ├─ ai/               LLM·VLM·임베딩 호출(OpenAI 호환) · 예산 장부 · 외부 전송 가드
│  ├─ store/            PostgreSQL(검색) · 회사 DB(SQL Server) · Object Storage
│  │  └─ db/            SQLAlchemy 테이블 정의 · Alembic 마이그레이션 · dbtool(migrate 명령)
│  ├─ config/           설정 모델(settings.yaml 읽기) · 샘플 생성 · 옛 env 이관 · 오버레이 설정 파일 · --set
│  └─ check/            모듈 경계 점검(check_modules) · 모델 연결 확인
├─ pipeline/            데이터 파이프라인 앱(data-pipeline 이미지)
│  ├─ cli.py            실행기 — parse, structure, load, publish, night, full, selftest, show-stack 등
│  ├─ config.py         pipeline 섹션 설정 모델
│  ├─ extract/          원천 읽기 · dedup · prepare · 엔진별 파싱(engines/ — 엔진 18개, 바이트가 캐시 키라 건드리지 않음)
│  ├─ transform/        represent(대표 결과) · figures(그림) · structure(청킹·임베딩·번들)
│  ├─ load/             pgvector 적재 · publish · 회사 DB 메타데이터 · 인덱스 빌더
│  ├─ shared/ · tools/  단계 공용 모듈 · 운영 도구
│  └─ mcp_parse_service.py                                                     MCP 파싱 작업
├─ mcp_server/          검색 MCP 앱(mcp-server 이미지, FastMCP)
│  ├─ main.py           진입점(앱 조립 · 토큰 · 서버 시작)
│  ├─ config.py         mcp 섹션 설정 모델
│  ├─ routers/          도구 4개와 /health 등록(이름·시그니처 고정)
│  ├─ schemas/          출력 구조
│  ├─ services/         EDW 질의 · 파싱 중계 · 메타데이터 · search/(하이브리드 검색 · 근거 정리 · 재순위)
│  └─ cli/              ask(질의 테스트) · mcp_smoke
├─ resources/           코드가 읽는 데이터(이미지에 포함)
│  ├─ prompts/          AI 프롬프트 패키지 {common,pipeline,mcp}
│  ├─ config/           엔진 구성 pipeline_stack.json(서버·PC 같음) · 채점 기준(criteria.json)
│  ├─ mappings/         문서 메타데이터 매핑
│  └─ vocab/            집계 어휘 · 질문 유형 · 용어집
├─ deploy/              배포
│  ├─ docker/           Dockerfile(타깃 pipeline, mcp) · requirements · entrypoint.sh · IMAGE_BASE · wheels/(폐쇄망용 휠)
│  ├─ release/          빌드·전송(build_ship, ship_stage) · 오버레이 패치 번들(make_patch) · 배포 판정(selftest_gate, known_fail.txt) · 커밋 전 점검(lint_changed.sh)
│  └─ host/             서버 호스트에서 쓰는 것 — compose/ · scripts/(trigger, run_tool, mcp_up, settings_env, run_docs 등) · systemd/(새벽 배치, keepalive)
├─ tests/               server/(이미지에 포함, 배포 판정) · general/(PC 전용) · runner.py
├─ validation/          PC 전용 검증 도구 — search_ui/(검증 페이지) · e2e/(평가·비교, answer_gen)
├─ valid_env/           PC 전용 데이터 — object_storage/(합성 테스트 문서, 버킷 모양) · edw/(합성 EDW sqlite) · answer_test/(답변 점검 agent) · docker/(PC 테스트 Docker)
├─ docs/                문서(지도: docs/INDEX.md) — PRD.md·prd/ · operations/ · architecture/ · refactoring/(refactor.md — 서버·사람 확인 사항 C-xx · "최종 — 사람이 할 일") · history/
├─ VERSION              두 이미지 공통 버전(SemVer)
├─ settings.sample.yaml 모든 설정 항목·코드 기본값·설명 — 복사해 settings.yaml로(자동 생성 — 손으로 고치지 않음)
├─ settings.yaml        PC 로컬 설정(git 제외 · 권한 600 — 직접 만듦)
├─ pyproject.toml · requirements-dev.txt · .githooks/   PC 개발 도구(ruff, mypy, pytest)와 커밋 전 점검 hook
└─ CLAUDE.md            개발 규칙(폴더 배치 · 경로 · 설정 · 핑거프린트 · 커밋 전 점검)
```

**모듈 경계:** `pipeline`과 `mcp_server`는 서로 import하지 않고, 함께 쓰는 코드는 `common`에 둔다. 앱은 `validation`과 `tests`를 import하지 않는다. `python -m common.check.check_modules`가 확인한다.

---

## 3. 설정

모든 설정 값과 비밀값(DB 접속 정보, 비밀번호, API 키, 토큰)은 **settings.yaml 한 파일**에 둔다. 코드는 환경변수에서 설정을 읽지 않는다(옛 env 이름을 넘기면 무시하고 이름만 경고한다).


| 항목     | 내용                                                                                                                                                          |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 위치     | PC: 저장소 루트 `settings.yaml`(git 제외, 권한 600) · 서버: `$SERVER_ENV_DIR/settings.yaml`(기본 `/srv/rag/env`, 소유자 UID 10001, 권한 640) · 다른 파일은 env `SETTINGS_FILE`로 지정 |
| 구조     | 맨 위 `required`(필수 접속·입력 — 묶음별 [PC·서버]·[서버만]) → 역할 절 `common`·`extract`·`transform`·`load`·`search`·`ops`·`dev` → 맨 아래 `tuning`(거의 안 바꾸는 값). 같은 절·칸을 두 번 쓰면 거부한다. 칸 자리 찾기: `python -m common.config.sample --where <옛 이름>`. 항목 설명과 기본값은 [settings.sample.yaml](settings.sample.yaml)                               |
| 쓰는 법   | **기본값과 다르게 쓸 항목만** 적는다. 비워 둔 항목은 코드 기본값을 쓴다                                                                                                                 |
| 필수     | `required.env.run_env` — `local`(PC) · `dev` · `prd`(서버 — 외부 모델 호출과 가짜 LLM(`llm_fake`)을 거부하고, 설정 파일을 못 읽으면 시작하지 않는다)                                                        |
| 항목별 안내 | [docs/operations/env-guide.md](docs/operations/env-guide.md)                                                                                                |
| **서버 반입** | `settings.yaml`은 **git에 올리지 않는다**(`.gitignore` — 비밀값·서버마다 다른 값). 반입 때 **사람이 서버용으로 직접 작성**한다: `settings.sample.yaml`을 복사해 맨 위 `required` 절(서버는 [서버만] 묶음까지)을 채우고(그 밖 칸은 코드 기본값이 적혀 있음 — op-05) `python -m pipeline.config --file <파일>`로 확인. **PC 파일을 그대로 복사하지 않는다** — PC의 `run_env: local`·`*_allow_external: true`가 서버에서 외부 모델 호출을 연다(알려진 위험, 사용자 10-29 수용) |


**실행할 때 값을 넘기는 방법 3가지**


| 방법                          | 언제                                                          | 받는 명령                                                                                                 |
| --------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **A. settings.yaml에 직접 적기** | 가장 간단. 계속 쓸 값                                               | 모든 명령                                                                                                 |
| **B. 명령 인자 `--set 이름=값`**   | 이번 실행에만 다른 값(파일은 그대로). 이름은 옛 env 이름([env-guide](docs/operations/env-guide.md)). 비밀·호스트 항목은 거부 | `pipeline.cli`, `build_bundle`, `pgvector_load` 등 파이프라인 진입점                                           |
| **C. 오버레이 설정 파일**(PC 전용)    | `--set`을 받지 않는 명령에 이번 실행만 다른 값                              | `mcp_server.main`, `mcp_server.cli.ask` — `SETTINGS_FILE=$(python -m common.config.overrides 이름=값 …)` |


---

## 4. PC에서 실행하기

Docker 없이 Python으로 직접 실행한다. 순서는 서버의 실제 처리 순서(`run_docs.py`)와 같다.

```
4-1 준비(처음 한 번) → 4-2 settings.yaml → 4-3 점검 → 4-4 파이프라인(①~⑥) → 4-5 MCP 서버 → 4-6 검증 페이지
```

### 4-1. 준비(처음 한 번)

```bash
# Python 3.12 가상환경 — 서버 이미지와 같은 패키지 + PC 개발 도구(ruff, mypy, pytest)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt
git config core.hooksPath .githooks      # 커밋할 때 바꾼 파일 점검(ruff, mypy, 모듈 경계)이 자동 실행 — CLAUDE.md §5-2

# 전용 pgvector(PG 16 + pgvector) — 처음만 run, 이후에는 docker start sbl-mcp-pg / docker stop sbl-mcp-pg
docker run -d --name sbl-mcp-pg -p 127.0.0.1:55433:5432 -v sbl_mcp_pgdata:/var/lib/postgresql/data \
  -e POSTGRES_DB=rag -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16
```

### 4-2. settings.yaml 작성

저장소 루트에 `settings.yaml`을 만들고 `chmod 600`한다. 칸 배치는 `settings.sample.yaml`과 같다 — 맨 위 `required`(꼭 채울 값), 그 아래 역할 절(`common`·`extract`·`transform`·`load`·`search`·`ops`·`dev`), 맨 아래 `tuning`(보통 비워 둠). 아래는 **방법 A**(파일에 모두 적기) 예시다.

```yaml
required:
  env: {run_env: local, run_mode: prod}
  pg: {host: 127.0.0.1, port: 55433, db: rag, user: rag, password: <비밀번호>, db_schema: demo}   # 적재·검색할 스키마
  embed: {base_url: <OpenAI 호환 주소>, model: <임베딩 모델>, api_key: <키>}
common:
  models:
    embed: {allow_external: true}
    guard:
      no_paid_calls: true                        # 평소에는 true(외부 호출 차단) — 임베딩이 필요한 실행 동안만 false
      budget_usd: 0.1                            # 비용 상한
      max_calls: 40
      spend_file: output/spend-ledger.json
ops:
  paths: {mcp_bundle: output/demo/bundle}        # MCP가 읽을 번들(검증 페이지 §4-6도 이 값)
  pipeline_paths: {out_root: output/demo}        # 파이프라인 결과 폴더
search:
  server: {host: 127.0.0.1, port: 18769, warmup: false}
dev:
  mcp: {mcp_url: "http://127.0.0.1:18769/mcp", ui_port: 8791}   # 검증 페이지(§4-6)·점검 도구가 붙을 주소
tuning:
  ops:
    runtime: {cpu_max_load: 5}                   # 부하가 높은 PC라면(기본 0.9에서는 계속 대기함)
```

- 옛 배치(최상위 `common`·`pipeline`·`mcp` — op-08 전) 파일은 읽지 않는다. `python -m common.config.migrate settings.yaml --out settings.new.yaml`로 바꾼 뒤 새 파일로 바꿔 넣는다(지운 칸은 "삭제됨"으로 이름만 알림).
- PG 접속값은 서버에서 꼭 채운다 — 비우면 시작을 거부한다(사용자 10-31, op-09 — 자동 탐지 없음). PC는 비우면 SQLite 대역으로 돈다. 검색 저장소는 PG 하나라 종류 칸은 없다(옛 `required.deploy.mcp_store`가 남아 있으면 경고만 — mc-01, 11-01).
- 같은 절(`search:` 등)이나 같은 칸을 두 번 쓰면 시작을 거부한다 — 칸을 더할 때는 이미 있는 절 안에 넣는다.
- **외부 임베딩은 세 조건이 모두 맞을 때만 호출된다:** `allow_external: true` · `run_env: local` · `no_paid_calls: false`. 하나라도 빠지면 호출하지 않는다(서버 dev·prd는 늘 거부).
- PG 접속 항목(`required.pg`의 host·port·db·user·password·db_schema)은 모두 필수다 — 비우면 채울 자리를 알려 주고 멈춘다(op-09, `docker ps` 자동 탐지와 코드 기본값은 없앰). 로컬 묶음만 쓸 때는 명령에 `--local`.

### 4-3. 점검

```bash
export PYTHONPATH=$PWD                                   # 명령은 저장소 루트에서
.venv/bin/python -m pipeline.config                      # 어느 settings.yaml을 읽는지와 요약(비밀은 가림)
.venv/bin/python -m common.check.check_modules           # "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check        # "빠진 키 0개"
.venv/bin/python -m pipeline.cli selftest                # 서버 배포 테스트 — 93개 중 92개 통과(알려진 실패 1개 — 기준선 PRD e2-02)
.venv/bin/python -m pytest -q tests/                      # 전체 테스트 — 146 passed · 3 xfailed(알려진 실패)
```

알려진 실패는 모두 리팩토링 전부터 있던 것이다(이유: refactor.md C-54·C-58 · 목록: `deploy/release/known_fail.txt`, `tests/conftest.py`).

### 4-4. 파이프라인 실행 — 문서 몇 건(①~⑥)

먼저 `settings.yaml`의 `no_paid_calls`를 `false`로 바꾼다(외부 임베딩 허용). 끝나면 ⑥에서 되돌린다.

**① 테스트 문서 고르기 — `valid_env/object_storage`에서 몇 건을 한 폴더로 모음**

```bash
mkdir -p output/demo/src && find valid_env/object_storage -type f ! -name '*.md' | head -10 | xargs -I{} cp {} output/demo/src/
SRC=output/demo/src     # --src는 폴더만 받음 — 문서를 한 폴더로 모아 넘긴다
```

- 문서는 서버 버킷 모양 `valid_env/object_storage/<원천>/<uuid>/<파일>`에 있다 — `CRMS/`(어려운 사례 21건) · `SFDC/`(RFP 12건). 정답·목록 세트(`valid_env/eval_sets/`)는 10-30 지웠다(사용자 — e2-10: 남기는 평가 도구는 검색 확인 페이지와 답변 점검뿐). 문서마다 왜 있는지는 [valid_env/object_storage/test_doc_purpose.md](valid_env/object_storage/test_doc_purpose.md), 전체 구조는 [valid_env/README.md](valid_env/README.md).
- `valid_env`에는 아무것도 쓰지 않는다(결과는 모두 `out_root` 아래). 내 문서로 하려면 `SRC=<문서 폴더>`.

**② 파싱 — 문서 → 대표 결과**

```bash
.venv/bin/python -m pipeline.cli parse --src $SRC
```

- 처리: 중복 제거 → 쪽 방향 보정 → 엔진별 파싱 → 대표 결과
- 결과: `output/demo/parse/<엔진>/`(엔진별), `output/demo/parse/_rep/`(문서마다 하나 + `_DONE.json`)

**③ 구조화·임베딩 — 대표 결과 → 번들**

```bash
.venv/bin/python -m pipeline.transform.structure.build_bundle \
  --parse-dir output/demo/parse --src $SRC --embed api --summary lead --out output/demo/bundle
```

- 결과: `output/demo/bundle/`(docs.jsonl · chunks.jsonl · vectors.npy · kg\_*.jsonl · meta.json)
- 같은 청크는 임베딩 캐시(`output/edw/embed_cache.sqlite`) 덕분에 다시 호출하지 않는다.
- `pipeline.cli structure`가 아니라 `build_bundle`을 직접 부른다. 서버의 실제 경로와 같고, `pipeline.cli structure`에는 축소 스키마 번들을 거부하는 알려진 문제가 있다([docs/PRD.md](docs/PRD.md) 표).

**④ DB 테이블 — Alembic 마이그레이션(스키마마다 처음 한 번 — 1-4)**

```bash
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle output/demo/bundle --create-extension
.venv/bin/python -m common.store.db.dbtool current --target all    # 기대: search 0002_search
.venv/bin/python -m common.store.db.dbtool check --target all      # 기대: 차이 없음
```

- 이 한 번으로 검색 테이블(`0001_search` → `0002_search`)이 만들어진다.
- `--bundle`은 벡터 차원을 `meta.json`에서 읽기 위해 준다. `--create-extension`은 새 PG일 때만 필요하다.
- 결과는 파일이 아니라 DB 안에 남는다(테이블 + `<스키마>.alembic_version`).

**⑤ 적재 — 번들 → pgvector**

```bash
.venv/bin/python -m pipeline.load.pgvector_load load --bundle output/demo/bundle
```

- 이미 적재한 문서를 다시 넣을 때는 `--replace`를 붙인다.
- 적재는 더하고 고치기만 한다 — 이번 묶음에 없는 문서(원천에서 지운 문서 포함)를 PostgreSQL에서 지우지 않는다(`--prune` 없앰 — pl-13, 사용자 10-29). 지워야 하면 사람이 따로 한다.

**(선택) MCP 없이 검색만 확인**

```bash
.venv/bin/python -m mcp_server.cli.ask ask --bundle output/demo/bundle --k 3 --q "<질문>"
```

**⑥ 정리** — 4-5에서 MCP까지 확인한 뒤 `settings.yaml`의 `no_paid_calls`를 `true`로 되돌린다(평소 테스트가 외부를 호출하지 않게).

<details>
<summary><b>방법 B — settings.yaml을 바꾸지 않고 <code>--set</code>으로 넘기기</b>(되돌릴 필요 없음)</summary>

`settings.yaml`은 `no_paid_calls: true`인 채로 두고, 이번 실행에만 필요한 값을 명령 인자로 준다.
```bash
O=$PWD/output/demo; SRC=$O/src     # ①과 같은 문서 폴더
SETS=(--set PIPE_OUT_ROOT=$O --set PG_SCHEMA=demo --set EMBED_ALLOW_EXTERNAL=1
      --set NO_PAID_CALLS=0 --set LLM_BUDGET_USD=0.10 --set LLM_MAX_CALLS=10 --set LLM_SPEND_FILE=$O/spend.json)

.venv/bin/python -m pipeline.cli "${SETS[@]}" parse --src $SRC
.venv/bin/python -m pipeline.transform.structure.build_bundle "${SETS[@]}" \
    --parse-dir $O/parse --src $SRC --embed api --summary lead --out $O/bundle
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle --create-extension
.venv/bin/python -m pipeline.load.pgvector_load "${SETS[@]}" load --bundle $O/bundle

# ask·MCP는 --set을 받지 않으므로 오버레이 설정 파일(방법 C)로 같은 값을 넘긴다
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo EMBED_ALLOW_EXTERNAL=1 \
     NO_PAID_CALLS=0 LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json MCP_BUNDLE=$O/bundle MCP_PORT=18769)
SETTINGS_FILE=$SF .venv/bin/python -m mcp_server.cli.ask ask --bundle $O/bundle --k 3 --q "<질문>"
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

- 엔드포인트: `http://127.0.0.1:18769/mcp`(streamable HTTP) — 도구 `search`, `query_edw`, `parse_document`, `edw_meta`
- 루프백(`127.0.0.1`)으로 띄우면 토큰 없이 접속된다. 다른 주소로 열면 `required.tokens.mcp`가 필요하고, `0.0.0.0`은 거부된다.

### 4-6. 검증 페이지(브라우저로 검색 확인)

검색 MCP와 pgvector를 브라우저로 보여 주는 PC 전용 페이지다. 설정은 루트 `settings.yaml` 하나이고(전용 설정 파일 없음), §4-2 예시의 `ops.paths.mcp_bundle`·`search.server`·`dev.mcp`를 그대로 쓴다(따로 더할 절 없음 — 다른 번들을 보려면 그 칸 값만 바꾼다).

```bash
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791  ·  /api/health · /api/tools · /api/chunk/<id>
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```

- `no_paid_calls: true`면 질의 임베딩도 막혀 키워드·ID 검색만 된다(근거의 via에 `v`가 없음). 벡터 검색까지 보려면 `false`로 바꾸고 MCP를 다시 띄우고, 끝나면 되돌린다.
- 다른 번들을 보려면 `ops.paths.mcp_bundle`(스키마가 다르면 `required.pg.db_schema`도)을 바꾸고 다시 띄운다.

### 4-7. 그 밖


| 하고 싶은 것                  | 명령                                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 답변 생성 점검(LLM 설정·예산 필요)   | `.venv/bin/python -m validation.e2e.answer_gen --url http://127.0.0.1:18769/mcp --q "<질문>"`                                                                           |
| 이미지 배치 그대로 PC Docker 테스트 | `bash valid_env/docker/smoke_test.sh`                                                                                                                                 |
| 이미지 로컬 빌드(시험 태그)         | `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh` — TAG를 빼면 `data-pipeline:<VERSION>`(배포용 태그라 남겨 둔다) |
| 커밋 전 점검                  | `bash deploy/release/lint_changed.sh`(바꾼 .py만 ruff·mypy·모듈 경계 — `FIX=1`이면 자동 수정)                                                                                      |


코드를 고칠 때의 규칙(폴더 배치, 경로, 설정, 핑거프린트, 커밋 전 점검, push 전 `/simplify`·`/code-review`)은 [CLAUDE.md](CLAUDE.md)에 있다.

---

## 5. 서버(내부망)에 배포하고 실행하기

서버는 **이미지 2개 · 코드 폴더**(`/srv/rag/code/live`) **· 설정 파일**(`/srv/rag/env/settings.yaml`) **· 결과 폴더**(`RAG_OUT`, 예: `/srv/rag/output`)로 동작한다. 서버 명령은 모두 코드 폴더 루트에서 실행한다.

> **이번 리팩토링 버전(0.1.0 — 첫 배포)은 [refactor.md](docs/refactoring/refactor.md) 맨 앞 "최종 — 사람이 할 일"의 순서(①검토 → ②배포 전 → ③배포 때 → ④배포 후)를 그대로 따른다.** 핑거프린트가 모두 바뀌어 서버 문서 전체를 다시 파싱해야 하고(재파싱 시간 산정 C-08이 먼저), 설정 이관 · DB 버전 기록 · 옛 컨테이너와 systemd 정리가 함께 필요하다.

### 5-0. 배포 단계 — 어디서 어디로, 어떤 이미지·코드로(op-06·op-07, 사용자 10-30)

| 단계 | 어디서 → 어디로 | run_env | 만드는 곳·스크립트 | 이미지 | 코드 | 컨테이너 구성 |
|---|---|---|---|---|---|---|
| ① 개발 반입 | PC → 개발 서버(폐쇄망) | `local` → `dev` | PC: `IMAGE_TARGET=pipeline-runtime`·`mcp-runtime bash deploy/release/build_ship.sh` → 이미지 git(`sbl_images`)에 분할 조각 | 실행 이미지 `data-pipeline-runtime`·`mcp-server-runtime`(코드 없음) | `main`(release 병합)의 커밋 — 코드 git zip을 푼 폴더(`CODE_COMMIT`) | 그 코드 폴더를 `/app/deploy`에 읽기 전용 마운트(스크립트가 자기 루트를 자동으로 — 아래). 코드만 바꿀 때 = 새 코드 zip + 다시 띄움 |
| ② 운영 반입 | 개발 서버 → 운영(수집) 서버 | `dev` → `prd` | 개발 서버: `bash <코드 폴더>/deploy/release/bake.sh <실행 이미지 판>` | 코드가 든 이미지 `data-pipeline`·`mcp-server`(개발에서 쓴 실행 이미지 그 판 + 코드) | 개발 서버에서 시험한 코드 폴더(코드 커밋은 이미지 라벨 `org.opencontainers.image.revision`) | 컨테이너에 코드 폴더 마운트 없음(`CODE_DIR` 두지 않음) — 호스트 스크립트(`deploy/host/`)만 같이 온 코드 묶음에서. 바꿀 때 = 새로 구운 이미지 |

- run_env는 `local`(PC)·`dev`(개발 서버)·`prd`(운영 서버) 셋뿐(`stage`는 10-29에 없앰).
- 어느 코드인가: ①은 PC의 git 커밋(묶음 안 `CODE_COMMIT`, 시작 로그 첫 줄 `[image] 이미지 … · 코드 … · 의존성 …`), ②는 개발 서버에서 시험한 코드 폴더 그대로(구운 이미지 라벨에 커밋·실행 이미지 ID).
- 의존성(`requirements*`·휠·Dockerfile·assets)이 바뀌면 ①에서 새 실행 이미지가 필요하다(코드의 `deploy/docker/DEPS_HASH`와 이미지 지문이 다르면 시작·굽기 모두 거부).
- PC에서 `IMAGE_TARGET=pipeline`·`mcp`로 코드가 든 이미지를 직접 빌드하는 길은 PC 시험(이미지 관문)·비상용으로만 남긴다 — 운영 반입은 ②(개발에서 시험한 그대로). 오버레이 패치(§5-8)도 운영 서버 비상 수정용.

#### 개발 서버 설치 — 코드 git·이미지 git을 zip으로 받아 한 폴더에(①, 사용자 10-30)

반입은 git 저장소 두 개를 **zip으로 받아 같은 폴더에 풀면** 끝난다.
- 코드: `gigasamba/sbl_data_parsing`의 `main`. 받을 판의 태그나 커밋으로 받는다.
- 이미지: 비공개 `jehunlee302/sbl_images`. 판마다 폴더가 있고, 실행 이미지를 분할한 조각이 들어 있다.

코드는 zip을 푼 폴더가 그대로 코드 폴더다(tar 묶음·`live` 링크·`CODE_DIR` 불필요).

```
/srv/rag/                                    ← 작업 폴더(아무 곳이나 — 두 zip을 여기 풂)
├── env/settings.yaml                        ← $SERVER_ENV_DIR · image: data-pipeline-runtime:<판> · mcp-server-runtime:<판>
├── sbl_data_parsing-<판>/                    ← 코드 zip을 푼 폴더 = 코드 폴더(컨테이너 /app/deploy에 읽기 전용)
│   ├── common/   pipeline/   mcp_server/   resources/
│   ├── deploy/host/scripts/trigger.sh · mcp_up.sh · run_tool.sh   ← 여기서 실행
│   ├── deploy/docker/DEPS_HASH                ← 실행 이미지 지문과 같아야 시작
│   └── VERSION   CODE_COMMIT                  ← CODE_COMMIT = zip이 채운 커밋(시작 로그에 찍힘)
└── sbl_images-main/                          ← 이미지 zip을 푼 폴더
    ├── load.sh                                ← sha256 확인 → 조각 합치기 → docker/podman load
    └── <판>/data-pipeline-runtime/ · mcp-server-runtime/   ← *.tar.gz.part000… + *.sha256
```

**컨테이너 도구는 root podman 하나로 쓴다.**
- 서버 명령은 모두 root 셸(`sudo -i`)에서 실행한다.
- settings.yaml에 `ops.host.docker: podman`을 적는다.
- 일반 사용자 셸에서 실행할 때는 `DOCKER="sudo podman"`을 앞에 붙인다.
- 이미지를 불러온 저장소와 컨테이너를 띄우는 저장소가 같아야 한다. 일반 사용자 podman(rootless)과 root podman은 이미지를 따로 보관하므로, 섞으면 이미지가 보이지 않는다.
- compose 실행기(`podman-compose`나 `docker-compose` 플러그인)가 깔려 있어야 한다. `podman compose version`으로 확인한다.
  - 폐쇄망에서 없으면: 사내 RHEL 저장소에 있으면 `dnf install podman-compose`. 없으면 인터넷 PC에서 서버와 같은 python 판으로 `pip download podman-compose -d pc-wheels`(의존 휠 `python-dotenv`·`PyYAML` 포함)로 휠을 받아 옮긴 뒤 서버에서 `python3 -m pip install --no-index --find-links pc-wheels podman-compose` → `podman compose version`으로 확인.

설치 순서(처음 한 번):
1. 두 zip을 같은 폴더에 푼다.
2. 코드 폴더를 준비한다.
   - 컨테이너 사용자(UID 10001)가 읽을 수 있게 한다: `chmod -R a+rX sbl_data_parsing-<판>`
   - 지금 쓰는 판을 링크로 건다: `mkdir -p /srv/rag/code && ln -sfn /srv/rag/sbl_data_parsing-<판> /srv/rag/code/live`. systemd unit과 아래 명령은 이 경로를 쓴다.
3. 이미지를 불러온다: `DOCKER=podman bash sbl_images-main/load.sh <판>` — 조각 sha256 확인 → 합치기 → load, 끝에 `<판>/BUILD.txt`(빌드 커밋·DEPS_HASH)를 보여 준다.
4. 설정을 채운다(§5-3 ②). `required.deploy.pipeline_image`·`required.deploy.mcp_image`에는 실행 이미지 태그(`data-pipeline-runtime:<판>`, `mcp-server-runtime:<판>`)를 적는다.
5. DB를 만들고, 연결을 점검하고, 이미지를 점검한다(§5-3 ③~⑤).
6. 실행한다: `bash /srv/rag/code/live/deploy/host/scripts/mcp_up.sh`, `… trigger.sh parse` 등.
   - 이미지 태그가 `*-runtime`이면 스크립트가 자기 코드 폴더 루트를 `/app/deploy`에 붙인다(`image_vars.sh`의 `code_dir_default`).
   - 셸이나 systemd에 `CODE_DIR`가 있으면 그 값이 우선한다.
   - 호스트 python이 설정을 읽지 못하면(RHEL 9 기본 python 3.9 등), 실행 이미지 `data-pipeline-runtime:<VERSION>` 안에서 이 코드 폴더를 붙여 읽는다(`settings_env.sh`).
7. 확인: 시작 로그 첫 줄 `[image] 이미지 … · 코드 <커밋> · 의존성 …`으로 어느 판이 도는지 본다.

- 코드만 바뀐 판: 새 코드 zip을 옆에 풀고, `live` 링크를 새 폴더로 옮긴 뒤 다시 띄운다. 의존성(`DEPS_HASH`)이 같으면 이미지는 그대로 둔다. 되돌리기는 링크를 옛 폴더로 되돌리면 된다.
- systemd unit(`deploy/host/systemd/`)은 `/srv/rag/code/live` 경로를 쓰므로 판을 바꿀 때 고칠 필요가 없다.
- git clone으로 받아도 동작은 같다. 다만 `CODE_COMMIT`이 채워지지 않아 시작 로그의 커밋이 틀 그대로 보인다(zip·`git archive`만 채움).
- tar 묶음(`build_ship.sh`의 `code-<버전>-<커밋>.tar.gz`) + `live` 링크 + `CODE_DIR` 방식도 그대로 쓸 수 있다.

### 5-1. 버전 올리기

- `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 git 태그 `v<버전>`(annotated)을 붙인다. 이미지 태그는 `v` 없이 버전만 쓴다.
- **MAJOR** — MCP 도구 계약 · DB 스키마 · 핸드오프 형식이 깨질 때 / **MINOR** — 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 / **PATCH** — 오버레이 패치(코드만 교체)
- 자세한 규칙: [release-and-patch.md](docs/operations/release-and-patch.md) §5

### 5-2. PC에서 — 이미지 만들기와 이미지 저장소에 올리기

서버 설치는 §5-0 "개발 서버 설치" 하나로 한다(op-10). PC가 하는 일은 실행 이미지 두 개를 만들어 이미지 git(`sbl_images`)에 조각으로 올리는 것뿐이다.

```bash
# 폐쇄망 빌드라면 먼저 deploy/docker/wheels/에 휠(linux/amd64, py3.12), 저장소 루트 assets/rapidocr/에 *.onnx를 둔다
#   (assets/ 준비: docs/operations/release-and-patch.md §5-6 — assets.py pack)
BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh   # data-pipeline-runtime:<VERSION> 빌드 → 이 커밋 코드를 붙여 selftest 판정
BUILD_ONLY=1 IMAGE_TARGET=mcp-runtime      bash deploy/release/build_ship.sh   # mcp-server-runtime:<VERSION>
bash deploy/release/ship_stage.sh pipeline-runtime mcp-runtime                 # output/ship/sbl_images/ — load.sh · <판>/BUILD.txt · <판>/<이미지>/ 45MB 조각 + sha256
```

`output/ship/sbl_images/`를 이미지 git에 그대로 올린다(push는 사람). 코드는 코드 git의 같은 판(태그)을 쓴다 — 이미지에 코드가 없다.

- 같은 태그의 이미지가 이미 있으면 `build_ship.sh`가 멈춘다(버전을 올리거나, 꼭 다시 만들어야 하면 `FORCE_TAG=1`).
- 코드만 바뀐 판은 이미지를 다시 만들지 않는다(`deploy/docker/DEPS_HASH`가 같으면 — 서버는 새 코드 zip만 받는다).
- 운영 서버 이미지(코드가 든 이미지)는 PC에서 만들지 않는다 — 개발 서버에서 굽는다(§5-0 ②, release-and-patch §1-2). PC의 `IMAGE_TARGET=pipeline`·`mcp`는 PC 시험·비상용.

### 5-3. 서버 — 처음 설치

**새 서버 첫 설치 순서(한눈에 — 자세한 명령은 아래 ①~⑥)**

1. pgvector 준비 — PG 16 + pgvector가 떠 있고, 우리 DB·계정이 있어야 한다(DB 담당자). 그 DB에 `vector` 확장을 관리자가 한 번 만든다(③ 0번).
2. 이미지와 코드 폴더 — 이미지 적재(`load.sh`), 코드 zip을 판 폴더에 풀고 `live` 링크(§5-0 1~3).
3. settings.yaml 만들기 — `settings.sample.yaml`을 복사해 `required:` 칸을 채운다(②). 언제: 컨테이너를 띄우기 전, 이미지·코드를 놓은 직후. 어디: ② 경로(소유 UID 10001, 권한 640). 칸마다 뜻은 sample의 주석과 [env-guide](docs/operations/env-guide.md) §1.
4. 결과 폴더 — UID 10001 · 운영 그룹 · `chmod 2775`(②).
5. DB 마이그레이션 — `migrate check` → `up`/`stamp`(③).
6. 연결 점검 — 모델 주소 `run_tool.sh ping_models`(LLM·VLM·임베딩 — 하나라도 실패면 종료 1), `run_tool.sh check_env`, PG `migrate check`(④).
7. 이미지 점검 — `check-modules`, `selftest`(⑤).
8. 띄우는 순서 — pgvector → 파이프라인 상주 컨테이너(`dc up -d data-pipeline-parse data-pipeline-structure`, §5-5) → MCP 파싱 작업 서비스(§5-5 표) → 검색 MCP(`mcp_up.sh`, ⑥). 띄운 뒤 MCP `/health`가 200이고 `parse_document` 시험 파일 1건이 결과를 돌려주는지 본다.

**포트 — 모두 settings.yaml 칸(서버·사용자마다 다르게 둘 수 있음, 비우면 기본값)**

| 무엇 | settings.yaml 칸 | 기본 | 누가 붙나 |
|---|---|---|---|
| PostgreSQL(pgvector) | `required.pg.port` | 없음(필수) | 파이프라인·검색 MCP |
| 검색 MCP 서버 | `search.server.port`(바인드 `search.server.host`) | 8765(127.0.0.1) | AI 클라이언트 |
| MCP 파싱 작업 서비스 | `ops.services.parse_mcp.port` — 검색 MCP가 부르는 주소는 `search.parse_proxy.url` | 8766 · `http://127.0.0.1:8766` | 검색 MCP의 `parse_document` |
| EDW(SQL Server) | `common.connections.rdb.port`(주소·계정은 `required.edw`) | 1433 | 파이프라인 목록·게시·`query_edw` |
| 검증 페이지(PC만) | `dev.mcp.ui_port` | 8790 | 사람(브라우저) |

두 포트를 바꿀 때는 짝을 함께 바꾼다: `ops.services.parse_mcp.port`를 바꾸면 `search.parse_proxy.url`도. 컨테이너는 host 네트워크라 포트가 서버에서 겹치지 않아야 한다.

**① 이미지와 코드 폴더** — §5-0 "개발 서버 설치" 1~3. 운영 서버(구운 이미지)는 §5-0 ②와 [release-and-patch](docs/operations/release-and-patch.md) §1-2.

아래 명령은 root 셸의 코드 폴더(`cd /srv/rag/code/live`)에서 실행한다. 먼저 이 셸에서만 쓸 함수 하나를 정의한다. 이 함수는 settings.yaml을 읽고, 실행 이미지면 코드 폴더를 붙여 compose를 부른다.

```bash
export SERVER_ENV_DIR=/srv/rag/env DOCKER=podman
dc() { ( . deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh && code_dir_default DATA_PIPELINE_IMAGE && \
         $DOCKER compose -f deploy/host/compose/compose.pipeline.yml ${CODE_DIR:+-f deploy/host/compose/compose.code.yml} "$@" ); }
```

**② 설정 파일과 결과 폴더**

```bash
mkdir -p /srv/rag/env && chmod 700 /srv/rag/env
cp settings.sample.yaml /srv/rag/env/settings.yaml                  # 필요한 항목만 값을 채움
chown 10001:<운영 그룹> /srv/rag/env/settings.yaml && chmod 640 /srv/rag/env/settings.yaml
mkdir -p /srv/rag/output && chown 10001:<운영 그룹> /srv/rag/output && chmod 2775 /srv/rag/output   # 컨테이너 UID 10001 · 그룹 = 운영 계정 그룹 · setgid(2) — 새 파일이 그 그룹을 물려받고, 컨테이너가 umask 0002로 써서 운영 계정도 고치고 지울 수 있다
```

서버 settings.yaml에 **반드시 적을 항목**이다. 빠지면 시작을 거부하거나 동작이 조용히 바뀐다(전체 표는 refactor.md "최종" ②-1).

| 항목 | 이유 |
|---|---|
| `required.env.run_env` | `dev`·`prd` — 없으면 앱·entrypoint·compose가 거부(`stage`는 없앰 — `prd`로 바꿈) |
| `required.env.run_mode: prod` | ⚠️ 빠지거나 오타가 나면 PG 장애 때 SQLite로 조용히 대체된다(PRD pl-12 — 고치기 전까지 꼭 확인) |
| `ops.host.docker: podman` | 호스트 스크립트의 컨테이너 도구(위 root podman) |
| `required.deploy.output_root` · `required.deploy.doc_src` | 결과 폴더(`/srv/rag/output`)·원천 문서 폴더 — 비면 compose가 `:?` 안내로 멈춤 |
| PG · EDW(`required.edw` — 읽기·쓰기 계정) · Object Storage 접속 항목 | 운영 접속 |
| 토큰 `required.tokens`(`mcp` · `parse_proxy` · `parse_mcp` · `trigger`) | 코드 기본 토큰 없음 |
| 이미지 `required.deploy.pipeline_image` · `required.deploy.mcp_image` | 예: `data-pipeline-runtime:0.1.0`, `mcp-server-runtime:0.1.0`(개발 서버) · 운영 서버는 `data-pipeline:0.1.0`, `mcp-server:0.1.0` |
| [env-guide](docs/operations/env-guide.md) "옛 서버 값" 표의 항목 | 옛 서버 동작 유지 |

모델 주소는 모두 내부망 주소여야 한다(서버는 외부 모델 호출을 거부). 옛 `pipeline.env`가 있으면 이관 도구를 쓴다: `python -m common.config.migrate <옛 env> --out <yaml>` → `--compare`로 대조(release-and-patch §5-4). 옛 배치 settings.yaml(op-08 전)은 `python -m common.config.migrate <옛 settings.yaml> --out <새 파일>`로 바꾼다.

**③ DB 마이그레이션** — 적재·검색을 하기 전에 끝낸다(파싱·검색 MCP 컨테이너는 PG 없이도 시작한다).

```bash
# 0. (DB마다 처음 한 번 — DB 관리자) vector 확장 — 서버 계정은 보통 우리 스키마 권한만 있어 직접 못 만든다. 없으면 migrate·적재가 "vector 확장 없음"으로 멈춘다
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
dc run --rm load migrate current
dc run --rm load migrate check --target all                # a. 지금 버전과 차이 확인(읽기만)

# b. 검색 스키마 — 옛 코드가 만든 스키마가 있고 차이가 0이면 실행 없이 기록만, 없거나 빠진 것만 있으면 up
#      dc run --rm load migrate stamp --target search     또는     dc run --rm load migrate up --target search
# c. 확인 — "차이 없음", 엔진 구성 파일이 읽히는지
#      dc run --rm load migrate check --target all
#      dc run --rm load show-stack                          # 엔진 구성 파일(이름·sha·경로)이 보이면 정상
```

- 컬럼 이름·형식·NULL·키가 다르거나 남는 테이블이 있으면 `stamp`·`up` 모두 거부된다(종료 코드 2). 멈추고 출력(이름만)을 DB 담당자와 협의한다.

**④ 연결 점검** — 파이프라인을 돌리기 전에 접속을 하나씩 확인한다.

```bash
bash deploy/host/scripts/run_tool.sh ping_models     # 모델 주소(LLM·VLM·임베딩) — 하나라도 실패면 종료 코드 1
bash deploy/host/scripts/run_tool.sh check_env       # PG·VLM·설정 요약(⚠️ PG 연결 실패를 "건너뜀"으로 보일 수 있음 — 출력을 읽는다)
dc run --rm load migrate check --target all          # PG 스키마(③ d와 같음)
dc run --rm parse check                              # PG·모델 요약(⚠️ 실패해도 종료 코드 0 — 출력을 읽는다)
```

- EDW 읽기·쓰기 로그인과 Object Storage 버킷을 따로 확인하는 명령은 아직 없다. 첫 파싱 뒤 publish 미리보기(`dc run --rm publish publish --dry-run`)로 확인한다.
- ⚠️ publish 실제 실행(`trigger.sh publish`)은 한 번만 한다. 다시 돌리면 Object Storage에 같은 파일을 또 올린다(PRD pl-12 ② — 고치기 전까지). EDW는 이미 있는 행을 건너뛴다.

**⑤ 이미지 점검**

```bash
$DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> check-modules
bash deploy/release/selftest_gate.sh $DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> selftest   # 기대: 알려진 실패 test_publish_guard 1개만
bash deploy/release/selftest_gate.sh $DOCKER run --rm -v "$PWD:/app/deploy:ro,z" mcp-server-runtime:<판> selftest      # 기대: 실패 0
```

selftest는 종료 코드가 아니라 `[판정]` 줄로 판정한다. 운영 서버(구운 이미지)는 `-v …` 없이 `data-pipeline:<판>`·`mcp-server:<판>`으로 실행한다.

> 💡 `dc`는 하위 셸 `( … )` 안에서 settings.yaml을 읽는다. 그래서 settings.yaml을 고치면 다음 `dc`부터 바로 반영된다. `trigger.sh` 같은 스크립트는 설정을 스스로 읽는다.

**⑥ 검색 MCP 띄우기**

```bash
bash deploy/host/scripts/mcp_up.sh     # 여러 번 실행해도 안전 — 꺼져 있으면 띄우고, 응답이 없으면 재시작
```

### 5-4. 서버 — 파이프라인 실행

**실행 방법 고르기**


| 방법     | 명령                                                   | 순서                                             | 언제     |
| ------ | ---------------------------------------------------- | ---------------------------------------------- | ------ |
| 문서별 흐름 | `python3 deploy/host/scripts/run_docs.py …`(nohup)   | 문서마다 파싱 → 구조화 → 적재 → publish(스트리밍)             | 대량 처리 |
| 새벽 배치  | systemd `data-pipeline-nightly.timer` → `trigger.sh scheduled` | `nightly.time` 시각에 `run_docs.py --start-offset 0 --skip-done` | 정기 운영 |
| 파싱·게시만 | `trigger.sh parse` · `trigger.sh publish`             | 1회 job(파싱 → `_rep` / 대표 결과 게시)                   | 단계 확인 |

서버 입구는 `run_docs` 하나다(사용자 10-31). 옛 1회 job 배치 `trigger.sh structure`·`load`·`all`·`night`와 이미지 명령 `night`·`run-stack`·`full`·`structure`·`load`는 11-01에 지웠다 — 구조화·적재는 run_docs가 `build_bundle`·`pgvector_load`를 문서마다 부른다.

```bash
bash deploy/host/scripts/trigger.sh parse       # 파싱 → output/parse/_rep(1회 job)
bash deploy/host/scripts/trigger.sh publish     # Object Storage 업로드 + EDW 메타데이터(운영 시스템에 씀)
```

- **문서별 흐름 `run_docs.py`** 는 `<운영자 작업 폴더>/run_docs.py`에 두고 실행한다(코드 폴더 안의 사본이 아니다). 설정 배치 모듈을 찾을 코드 폴더는 `--code`(기본 `/srv/rag/code/live`), 컨테이너 명령은 settings.yaml `ops.host.docker`(없으면 podman). 서버 settings.yaml의 운영 접속 항목을 읽고, 문서별 값은 상주 컨테이너에 `--set`으로 넘긴다 — 설계: [docs/architecture/run_docs_design.md](docs/architecture/run_docs_design.md). **PC에서는 실행하지 않는다**(운영 EDW·Object Storage에 접속).

### 5-5. 서버 — 상주 서비스와 자동 실행


| 무엇                                                 | 방법                                                                                                                                                            |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 검색 MCP 상주 확인                                       | systemd `mcp-server-keepalive.timer` — 부팅 1분 뒤 + 2분마다 `mcp_up.sh`                                                                                             |
| 새벽 배치                                              | systemd `data-pipeline-nightly.timer`(5분마다 깨움) + settings.yaml `ops.nightly.time: "HH:MM"`(그 시각부터 5분 안에 시작 — 비우면 새벽 배치 없음, 기본 비움 · pl-32) |
| 상주 컨테이너(`run_docs.py`가 docker exec — 일 없이 떠 있음, 11-01 trigger 서버 지움) | `dc up -d data-pipeline-parse data-pipeline-structure`(§5-3의 `dc` — 실행 이미지면 코드 폴더를 붙임). 여러 번 불러도 안전 — 꺼진 것만 띄움 |
| MCP `parse_document` 작업 서비스                        | compose가 띄우지 않으므로 파싱 컨테이너가 다시 시작될 때마다: `$DOCKER exec -d data-pipeline-parse bash -c 'umask 0002 && exec python -u -m pipeline.mcp_parse_service'`(`docker exec`는 entrypoint를 거치지 않아 umask를 여기서 준다) |
| 재부팅 뒤 되살리기(podman)                                | `systemctl enable --now podman-restart` — podman은 docker처럼 데몬이 없어 `restart: unless-stopped` 컨테이너(검색 MCP·상주 컨테이너)를 부팅 때 다시 띄우지 않는다. 이 서비스가 그 컨테이너들을 되살린다. 검색 MCP는 keepalive 타이머가 한 번 더 본다. 상주 트리거는 keepalive 타이머가 없으니, 재부팅 뒤 `$DOCKER ps`로 `data-pipeline-parse`·`data-pipeline-structure`가 떠 있는지 보고, 없으면 위 `dc up -d …`를 다시 실행한 뒤 `parse_document` 작업 서비스도 다시 띄운다 |


systemd 설치(한 번 — DB 버전과 컨테이너를 확인한 뒤):

```bash
sudo cp deploy/host/systemd/{mcp-server-keepalive,data-pipeline-nightly}.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now podman-restart                   # 재부팅 뒤 restart 정책 컨테이너 되살리기(podman)
sudo systemctl enable --now mcp-server-keepalive.timer
sudo systemctl enable --now data-pipeline-nightly.timer      # 새벽 배치를 쓸 때(settings.yaml 스위치도 켬)
```

### 5-6. 서버 — 결과 확인과 도구

```bash
bash deploy/host/scripts/run_tool.sh <도구> [인자]                                                    # rdb_discover · check_env · ping_models
# 실행 보드(run_board)·정답률(score_gold)·검색 평가(mcp_eval)는 11-01에 지움(PRD e2-10)
```

### 5-7. 서버 — 값 바꾸기


| 바꿀 것                     | 방법                                                                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 설정 값                     | settings.yaml을 직접 고치고 상주 컨테이너(`data-pipeline-parse`, `data-pipeline-structure`, `mcp-server`)를 다시 띄운다                                                                      |
| 이번 실행만 다른 값              | `--set 이름=값`(오버레이 설정 파일 도구는 PC 전용 — 서버에서는 종료 코드 2)                                                                                                                         |
| 엔진 구성(파일) | 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 오버레이 패치(5-8) — 되돌리기는 git, 확인은 `show-stack` — [docs/architecture/pipeline\_stack.md](docs/architecture/pipeline_stack.md) |


### 5-8. 코드만 고쳤을 때 — 오버레이 패치

의존성 · Dockerfile · 마운트 경로가 그대로라면 이미지를 다시 만들지 않고 코드 폴더만 바꾼다.

1. `VERSION`의 PATCH 자리를 올린다(예: `0.1.0` → `0.1.1` — 이미지 태그와 같으면 `make_patch.sh`가 멈춤).
2. PC에서 `bash deploy/release/make_patch.sh <시작점> <출력 폴더>`로 패치 번들을 만든다(바뀐 파일 + 매니페스트 + 설명서 + 재파싱 필요 판정).
3. 서버에서 적용한 뒤 `check-modules`와 `selftest_gate`로 확인한다(compose는 `compose.patch.yml`로 코드 폴더를 덮어 붙인다).

새 이미지 버전이 필요한지와 자세한 순서는 [release-and-patch.md](docs/operations/release-and-patch.md) §1~§5에 있다.

---

## 6. 꼭 지킬 것

요약이다. 전체 규칙은 [CLAUDE.md](CLAUDE.md) §2~§5.

- **결과 재사용 키를 함부로 바꾸지 않는다** — 엔진 파일(`pipeline/extract/engines/`)의 바이트, 핸드오프 핑거프린트(`FINGERPRINT`), 레이어 코드 핑거프린트(`code_fp`), 프롬프트 문구. 바뀌면 서버 문서가 다시 파싱된다. 확인:
`PYTHONPATH=. .venv/bin/python -c "import common as c; from common.core import artifacts as a; print(c.FINGERPRINT, {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)})"`
- **계약은 바꾸지 않는다** — MCP 도구 4개의 이름과 입출력, DB 테이블·컬럼의 이름과 형식(바꾸려면 협의 후 Alembic 마이그레이션으로).
- **비밀값은 settings.yaml에만** — 문서, 로그, 커밋, 채팅에 쓰지 않는다. `settings.yaml`은 git에 올리지 않는다.
- **PC에서 운영 시스템에 접속하지 않는다** — `run_docs.py` 로컬 실행 금지, `valid_env/structured/sales.sqlite`는 열지 않는다.
- **배포 환경 규칙** — 절대 경로 금지(서버·컨테이너 경로는 설정 값으로), 파일은 UTF-8·LF, 셸 스크립트는 bash 3.2/4/5 모두에서 동작하게, RHEL 마운트에는 `:z`, podman 사용을 전제로 확인.
- **새 외부 패키지는 승인 뒤에만** 도입하고, `deploy/docker/` 의존성이 바뀌면 새 이미지 버전(MINOR)으로 배포한다.

---

## 7. 문서와 알려진 문제


| 문서                                                                           | 내용                                                                     |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| [docs/PRD.md](docs/PRD.md) · [docs/prd/](docs/prd/)                          | **기능 요건** — 카테고리 6개(etl·parse·mcp·settings·test·doc)의 기능·목적·관련 파일, 카테고리별 묶음 표(끝난 것 포함) · 파일 끝에 요건과 다른 코드·안 쓰는 코드·꺼진 기능 |
| [docs/INDEX.md](docs/INDEX.md)                                               | 문서 지도                                                                  |
| [CLAUDE.md](CLAUDE.md)                                                       | 개발 규칙 · 로컬 하네스 · 점검 명령 · 핑거프린트 기준값                                     |
| [refactor.md](docs/refactoring/refactor.md)                                                   | 서버·사람이 확인할 사항(C-xx) · **"최종 — 사람이 할 일"**(첫 배포 순서)                      |
| [docs/operations/server-guide.md](docs/operations/server-guide.md)           | 서버 설치 · 운영 · 문제 해결                                                     |
| [docs/operations/release-and-patch.md](docs/operations/release-and-patch.md) | 버전 · 빌드 · 전송 · 오버레이 패치 · DB 버전 관리(migrate) · 배포 판정                     |
| [docs/operations/env-guide.md](docs/operations/env-guide.md)                 | 설정 항목 작성 가이드                                                           |
| [docs/architecture/](docs/architecture/)                                     | 프롬프트 패키지(prompts.md) · 엔진 구성 파일(pipeline\_stack.md) · run\_docs 설계 |
| [docs/history/refactor\_plan.md](docs/history/refactor_plan.md)      | 리팩토링 가이드 · 결정 기록(D-xxx) · 파일 이동표                                       |


**알려진 문제·미개발 항목** — [docs/PRD.md](docs/PRD.md) 표(축소 스키마 일부 반영 `mc-10`·`mc-11` · 테스트 알려진 실패 `e2-11` 등).

> 옛 문서와 코드 주석에는 리팩토링 중에 쓰던 용어가 남아 있다(시험=테스트, 반입=배포, 칸=항목·컬럼, 판=버전, 지문=핑거프린트, 열쇠=키, 층=레이어, 묶음=번들, 대장=레지스트리, 인계=핸드오프, 덧씌우기=오버레이 패치, 게시=퍼블리시, 지시서=프롬프트). 대응표는 CLAUDE.md 끝에 있다.