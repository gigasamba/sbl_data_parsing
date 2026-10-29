# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱해 대표 결과를 만들고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 내부망(폐쇄망, RHEL) 서버에서 Docker/podman 이미지 2개로 실행되고, 개발은 macOS·Windows PC에서 한다.

```
원천 문서(Object Storage · 폴더 · RDB 목록)
   │  parse     — dedup → prepare → 엔진별 파싱 → 대표 결과(_rep)          [data-pipeline 이미지]
   │  structure — 청킹 · 사실 추출 · 임베딩 → 번들(bundle)
   │  load      — 번들 → PostgreSQL(pgvector) 적재
   │  publish   — 대표 결과 Object Storage 업로드 + 회사 DB(EDW) 메타데이터
   ▼
검색 MCP 서버 — 도구 4개: search · query_edw · parse_document · edw_meta      [mcp-server 이미지]
```

- 모듈들은 하나의 결과 폴더(`RAG_OUT` — 컨테이너 안에서는 `/app/output`)를 통해 파일로 결과를 주고받는다. 앞 모듈이 완료 표시를 남겨야 다음 모듈이 시작한다(없으면 종료 코드 3).
- MCP 도구 4개의 이름과 입출력은 외부와의 계약이므로 바꾸지 않는다.

> 이 저장소는 서버 코드 사본을 리팩토링한 결과다(10-26~10-29, 단계 S0~S12). 무엇이 왜 바뀌었는지는 [docs/refactoring/refactor_plan.md](docs/refactoring/refactor_plan.md)에 있고, **서버에 처음 배포하기 전에 사람이 할 일**은 [refactor.md](refactor.md) 맨 앞의 "최종 — 사람이 할 일"이 기준 문서다.

---

## 1. 폴더 구조와 역할

```
.
├─ common/              공용 코드 — 두 앱(pipeline, mcp_server)이 함께 쓰는 것만
│  ├─ core/             경로 · 핑거프린트(FINGERPRINT, code_fp) · 핸드오프 계약 · 문자열 처리 · 실행 기록
│  ├─ ai/               LLM·VLM·임베딩 호출(OpenAI 호환), 예산 장부, 외부 전송 가드
│  ├─ store/            저장소 — PostgreSQL · 정형 저장소(struct) · 회사 DB(SQL Server) · Object Storage
│  │  └─ db/            SQLAlchemy 테이블 정의 · pydantic 행 모델 · Alembic 마이그레이션 · `dbtool`(migrate 명령)
│  ├─ config/           설정 모델(settings.yaml 읽기) · 샘플 생성 · 옛 env 이관(migrate) · 오버레이 설정 파일 · `--set`
│  └─ check/            모듈 경계 점검(check_modules) · 모델 연결 확인
├─ pipeline/            데이터 파이프라인 앱(data-pipeline 이미지)
│  ├─ cli.py            실행기 — parse, structure, load, publish, night, selftest 등의 하위 명령
│  ├─ config.py         pipeline 섹션 설정 모델
│  ├─ extract/          원천 읽기 · dedup · prepare · 파싱(engines/ — 엔진 27개, 바이트가 캐시 키라서 건드리지 않음)
│  ├─ transform/        represent(대표 결과) · figures(그림) · structure(청킹·임베딩·번들)
│  ├─ load/             pgvector 적재 · 퍼블리시(publish) · 회사 DB 메타데이터 · 인덱스 빌더
│  ├─ shared/ · tools/  단계 공용 모듈 · 운영 도구
│  ├─ eval/             채점 · 실행 현황판(score_gold, run_board 등)
│  └─ trigger_server.py · mcp_parse_service.py · stream.py · parse_parallel.py   상주 트리거 · MCP 파싱 작업 · 스트리밍
├─ mcp_server/          검색 MCP 앱(mcp-server 이미지) — FastMCP
│  ├─ main.py           진입점(앱 조립 · 토큰 · 서버 시작)
│  ├─ config.py         mcp 섹션 설정 모델
│  ├─ routers/          도구 4개와 /health 등록(이름·시그니처 고정)
│  ├─ schemas/          출력 구조
│  ├─ services/         EDW 질의 · 파싱 중계 · 메타데이터 · search/(하이브리드 검색 · 근거 정리 · 재순위)
│  └─ cli/              ask(질의 테스트) · mcp_smoke · mcp_eval · registry_cli
├─ resources/           코드가 읽는 데이터(이미지에 포함)
│  ├─ prompts/          AI 프롬프트 패키지 {common,pipeline,mcp}
│  ├─ config/           엔진 구성 pipeline_stack.json(PC용 — 서버는 DB 버전 테이블) · 채점 기준 criteria.json · 보고서 템플릿
│  ├─ mappings/         원천 목록 sources.json(PC용 — 서버는 DB 버전 테이블) · 문서 메타데이터 매핑
│  ├─ vocab/            집계 어휘 · 질문 유형 · 용어집
│  └─ sql/              DB 시드(버전 번호가 붙은 사본 — 한 번 배포하면 고치지 않음)
├─ deploy/              배포
│  ├─ docker/           Dockerfile(타깃 pipeline, mcp) · requirements · entrypoint.sh · wheels/(폐쇄망용 휠)
│  ├─ release/          이미지 빌드·전송(build_ship, ship_stage) · 오버레이 패치 번들(make_patch) · 배포 판정(selftest_gate, known_fail.txt) · 커밋 전 점검(lint_changed.sh)
│  └─ host/             서버 호스트에서 실행하는 것 — compose/ · systemd/(새벽 배치, keepalive) · scripts/(trigger, run_tool, mcp_up, settings_env, run_docs 등)
├─ tests/               테스트 — server/(이미지에 포함, 배포 판정) · general/(PC 전용) · fixtures/(프롬프트 사례 — 읽는 테스트 없음, refactor.md C-63) · runner.py
├─ validation/          PC 전용 검증 도구(이미지에 포함되지 않음)
│  ├─ search_ui/        검증 페이지 — 검색 MCP와 pgvector를 브라우저로 확인
│  └─ e2e/              평가·비교 도구(stack_matrix, model_matrix, graph_llm, answer_gen) · triple_extract 프롬프트
├─ valid_env/           PC 전용 데이터(내부망 배포에서는 쓰지 않으므로 한 곳에 모음)
│  ├─ unstructured/     합성 테스트 문서와 정답(Object Storage 대용)
│  ├─ answer_test/      답변 점검 agent rag_qa
│  └─ docker/           PC 테스트 Docker(compose.pg, compose.test, smoke_test)
├─ docs/                문서(지도: docs/index.md) — operations/(서버 운영) · architecture/ · requirements/ · refactoring/
├─ VERSION             두 이미지(data-pipeline, mcp-server) 공통 버전(SemVer — 이미지 태그·DB 버전 표기에 쓰임)
├─ settings.sample.yaml 모든 설정 항목의 구조와 설명(값 없음, 자동 생성 — 손으로 고치지 않음)
├─ settings.yaml        PC 로컬 설정(git 제외 · 권한 600 — 직접 만듦)
├─ pyproject.toml · requirements-dev.txt · .githooks/   PC 개발 도구(ruff, mypy, pytest) 설정과 커밋 전 점검 hook
├─ refactor.md          서버·사람이 확인할 사항(C-xx) · "최종 — 사람이 할 일"
└─ CLAUDE.md            개발 규칙(폴더 배치 · 경로 · 설정 · 핑거프린트 · 커밋 전 점검)
```

**모듈 경계:** `pipeline`과 `mcp_server`는 서로 import하지 않고, 공용 코드는 `common`만 쓴다. 앱은 `validation`과 `tests`를 import하지 않는다. `python -m common.check.check_modules`가 이를 확인한다.

**서버 이미지 2개**

| 이미지 | 역할 | 실행하는 것 |
|---|---|---|
| `data-pipeline` | 파싱 · 구조화 · 적재 · 퍼블리시 | compose 서비스 `parse`, `structure`, `load`, `publish` · 상주 트리거 컨테이너 `data-pipeline-parse`, `data-pipeline-structure`(선택) |
| `mcp-server` | 검색 MCP(상주) + 도구 | 상주 컨테이너 `mcp-server` · 도구 job `retrieval` |

---

## 2. 설정 — `settings.yaml` 하나

- 모든 설정 값과 비밀값(DB 접속 정보, 비밀번호, API 키, 토큰)은 **settings.yaml 한 파일**에 둔다. 코드는 환경변수에서 설정을 읽지 않는다(옛 env 이름을 넘겨도 무시하고 이름만 경고한다).
- 구조, 항목 설명, 기본값은 [settings.sample.yaml](settings.sample.yaml)에 있다. 최상위 섹션은 `common`(공용), `pipeline`, `mcp`이고, 각 앱은 `common`과 자기 섹션만 읽는다.
- 실제 파일에는 **기본값과 다르게 쓸 항목만** 적는다. 비워 둔 항목은 코드 기본값을 쓴다.
- 위치: PC는 저장소 루트의 `settings.yaml`(git 제외, 권한 600), 서버는 `$SERVER_ENV_DIR/settings.yaml`(기본 `/srv/rag/env`, 소유자 UID 10001, 권한 640)이다. `SETTINGS_FILE`(env)로 다른 파일을 지정할 수 있다.
- `common.run_env`(또는 env `RUN_ENV`)는 필수다 — `local`(PC), `dev`, `stage`, `prd`(서버 — 외부 모델 호출을 거부하고, 설정 파일을 읽지 못하면 시작하지 않는다).
- 한 번만 다른 값으로 실행할 때는 명령 인자 `--set 이름=값`을 쓴다(이름은 sample의 `env=`, 비밀 항목과 호스트 항목은 거부된다). PC에서는 오버레이 설정 파일도 쓸 수 있다(`python -m common.config.overrides 이름=값 …` — 원본을 `base`로 가리키는 작은 yaml 파일을 만들고 그 경로를 출력한다).
- 항목별 설명과 버전마다 바뀐 설정은 [docs/operations/env-guide.md](docs/operations/env-guide.md)에 있다.

---

## 3. 로컬(PC)에서 실행

### 3-1. 준비
```bash
# Python 3.12 가상환경 — 서버 이미지와 같은 패키지
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt   # 마지막은 PC 개발 도구(ruff, mypy, pytest)
git config core.hooksPath .githooks   # 커밋할 때 바꾼 파일 점검(ruff, mypy, 모듈 경계)이 자동으로 실행됨 — CLAUDE.md §5-2

# 전용 pgvector(PG 16 + pgvector) — 127.0.0.1:55433, 처음 한 번만(이후에는 docker start sbl-mcp-pg / docker stop sbl-mcp-pg)
docker run -d --name sbl-mcp-pg -p 127.0.0.1:55433:5432 -v sbl_mcp_pgdata:/var/lib/postgresql/data \
  -e POSTGRES_DB=rag -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16
# (valid_env/docker/compose.pg.yml은 개발 서버용 단독 PG — 기본값이 포트 5432, 메모리 4GB)
```
저장소 루트에 `settings.yaml`을 만든다(`settings.sample.yaml`을 보고 필요한 항목만 적은 뒤 `chmod 600`). PC용 최소 예시(값은 각자 채운다):
```yaml
common:
  run_env: local
  connections:
    pg: {host: 127.0.0.1, port: 55433, db: <db>, user: <user>, password: <비밀번호>, db_schema: <스키마>}
  models:
    guard: {no_paid_calls: true}          # 기본은 유료 호출 차단 — 필요한 실행에서만 --set으로 해제
    embed: {base_url: <OpenAI 호환 주소>, model: <임베딩 모델>, api_key: <키>}
  store: {run_mode: prod}
  runtime: {cpu_max_load: 5}              # 부하가 높은 PC라면 올린다(기본 0.9)
```
> ⚠️ PG 접속 항목을 비워 두면 코드가 `docker ps`로 찾은 아무 pgvector에나 연결한다. 전용 PG 접속 정보를 항상 적어 둔다.

명령은 저장소 루트에서 `PYTHONPATH`를 지정해 실행한다:
```bash
export PYTHONPATH=$PWD
.venv/bin/python -m pipeline.config          # 어느 설정 파일을 읽는지와 요약(비밀값은 가림)
```

### 3-2. 점검
```bash
.venv/bin/python -m common.check.check_modules      # 모듈 경계 — "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check   # 설정 키 대조 — "빠진 키 0개"
.venv/bin/python -m pipeline.cli selftest           # 서버 배포 테스트(tests/server) — 89개 중 88개 통과(알려진 실패 1개)
.venv/bin/python -m pytest -q tests/                 # 서버 배포 테스트 + PC 일반 테스트 — 142 passed · 8 xfailed(알려진 실패)
bash deploy/release/lint_changed.sh                  # 커밋 전 — 바꾼 .py만 ruff·mypy·모듈 경계 점검(FIX=1이면 자동 수정·포맷)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && PYTHONPATH=. .venv/bin/mypy   # 저장소 전체 린트·포맷·타입 — 모두 0(S12)
```
코드를 고칠 때의 규칙(폴더 배치, 경로, 설정, 핑거프린트, 커밋 전 점검, push 전 `/simplify`·`/code-review`)은 [CLAUDE.md](CLAUDE.md)에 있다.
알려진 실패는 모두 리팩토링 전부터 있던 것이다. 이유는 [refactor.md](refactor.md) C-54·C-58에, 목록은 `deploy/release/known_fail.txt`와 `tests/conftest.py`에 있다.

### 3-3. 파싱 → 임베딩 → 적재 → 검색(문서 몇 건)
서버의 실제 처리 순서와 같다. 실행마다 바뀌는 값은 `--set`으로 넘긴다(아래 예에서는 테스트 스키마, 결과 폴더, 외부 임베딩 허용, 예산). 외부 유료 호출은 두 가지 잠금(`EMBED_ALLOW_EXTERNAL`, 그리고 합성 테스트 문서라는 선언 파일 `LLM_SYNTHETIC_TRUTH`)과 예산 상한이 모두 있어야 실행된다.
```bash
O=$PWD/output/demo; mkdir -p $O/src; cp valid_env/unstructured/synth-realpat/{hidden_term,merged_table}.docx $O/src/
SETS=(--set PIPE_OUT_ROOT=$O --set PG_SCHEMA=demo --set EMBED_ALLOW_EXTERNAL=1 --set LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json>
      --set NO_PAID_CALLS=0 --set LLM_BUDGET_USD=0.10 --set LLM_MAX_CALLS=10 --set LLM_SPEND_FILE=$O/spend.json)

.venv/bin/python -m pipeline.cli "${SETS[@]}" parse --src $O/src                                   # 파싱 → $O/parse/_rep
.venv/bin/python -m pipeline.transform.structure.build_bundle "${SETS[@]}" \
    --parse-dir $O/parse --src $O/src --embed api --summary lead --out $O/bundle                     # 청킹·임베딩 → 번들
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle          # 테이블 생성·버전 기록(새 PG라면 --create-extension)
.venv/bin/python -m pipeline.load.pgvector_load "${SETS[@]}" load --bundle $O/bundle               # pgvector 적재
```
MCP 없이 검색을 확인할 때 — `ask`는 `--set`을 받지 않으므로, 루트 `settings.yaml`을 `base`로 하는 오버레이 설정 파일로 같은 값을 넘긴다:
```bash
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo EMBED_ALLOW_EXTERNAL=1 LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json> \
     NO_PAID_CALLS=0 LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json)
SETTINGS_FILE=$SF .venv/bin/python -m mcp_server.cli.ask ask --pg --bundle $O/bundle --k 3 --q "<질문>"
```
- 임베딩 캐시(`output/edw/embed_cache.sqlite`) 덕분에 같은 청크는 다시 호출하지 않는다. 실제 호출을 확인하려면 `--set EMBED_CACHE=<빈 sqlite 경로>`를 준다.
- 엔진 구성과 원천 목록은 PC에서는 `resources/config/pipeline_stack.json`, `resources/mappings/sources.json`을 읽는다(서버는 DB 버전 테이블).
- 이미 적재된 문서를 다시 적재할 때는 `--replace`를 준다. `--prune`만 주면 바뀌지 않아 건너뛴 문서까지 지워지는 알려진 결함이 있다(refactor.md C-60).

### 3-4. 검색 MCP 서버
MCP 서버 진입점도 `--set`을 받지 않으므로 오버레이 설정 파일로 띄운다(포트, 저장소, 번들 위치를 추가):
```bash
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo MCP_STORE=pg MCP_BUNDLE=$O/bundle MCP_PORT=18769 \
     EMBED_ALLOW_EXTERNAL=1 LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json> NO_PAID_CALLS=0 LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json)
SETTINGS_FILE=$SF nohup .venv/bin/python -m mcp_server.main > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
curl -s http://127.0.0.1:18769/health          # {"ok":true,"ready":true,"store":"pgvector",…}
kill $(cat $O/mcp.pid)                           # 종료 — PID로만
```
MCP 엔드포인트는 `http://127.0.0.1:<포트>/mcp`(streamable HTTP)다. 루프백 주소로 띄우면 토큰 없이 접속되고, 그 밖의 주소로 띄우면 `mcp.server.token`이 필요하다.

### 3-5. 검증 페이지(브라우저로 검색 확인)
설정은 저장소 루트의 `settings.yaml` 하나다(검증 페이지 전용 설정 파일은 따로 없다 — 사용자 10-29). 페이지가 쓰는 항목을 루트 파일에 추가한다(비워 둔 항목은 코드 기본값 — 포트 8765·8790, 번들 없음):
```yaml
common:
  paths: {mcp_bundle: output/validation/bundle}   # 검색할 번들
  models:
    guard: {no_paid_calls: true, budget_usd: 0.1, max_calls: 40, spend_file: output/spend-ledger.json, synthetic_truth: <합성 문서 선언 json>}
    embed: {allow_external: true, …}             # 외부 허용 첫 번째 잠금(두 번째는 synthetic_truth)
mcp:
  dev: {mcp_url: "http://127.0.0.1:18767/mcp", ui_port: 8791}
  server: {host: 127.0.0.1, port: 18767, store: pg, warmup: false}
```
외부 임베딩 스위치는 `common.models.guard.no_paid_calls` 하나다. `true`이면 질의 임베딩을 포함한 모든 외부 호출을 거부하고, 검색은 키워드와 ID로만 동작한다(근거의 via에 `v`가 없음). 벡터 검색까지 보려면 `false`로 바꾸고 MCP를 다시 띄운다. 이 값은 PC의 다른 실행(테스트, 파이프라인)에도 적용되므로 확인이 끝나면 `true`로 되돌린다. 두 잠금(`allow_external`, `synthetic_truth`) 중 하나라도 비어 있으면 `false`여도 외부로 호출하지 않는다.
```bash
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791  ·  /api/health · /api/tools · /api/chunk/<id>
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```
다른 번들을 보려면 루트 파일의 `common.paths.mcp_bundle`(스키마가 다르면 `common.connections.pg.db_schema`도)을 바꾸고 다시 띄운다.

### 3-6. 그 밖
- 답변 생성 점검(PC 전용): `.venv/bin/python -m validation.e2e.answer_gen --url http://127.0.0.1:18767/mcp --q "<질문>"` — `valid_env/answer_test/rag_qa` agent로 답변, 인용, 인용 검증을 확인한다. LLM 설정(`common.models.llm`)과 예산 상한이 필요하다.
- PC 테스트 Docker(이미지 배치 그대로): `valid_env/docker/smoke_test.sh`.
- 이미지 로컬 빌드: `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh`(TAG를 빼면 `data-pipeline:<VERSION>` — 버전 태그는 배포용으로 남겨 둔다) → `bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest`(판정은 `[판정]` 줄로 한다). Docker 23 미만이면 `build_ship.sh`가 BuildKit 인자를 자동으로 붙인다.

---

## 4. 내부망(서버) 배포와 실행

서버는 이미지 2개, 코드 폴더(`PATCH_CODE`, 기본 `/srv/rag/code/live`), 설정 파일(`/srv/rag/env/settings.yaml`), 결과 폴더(`RAG_OUT`, 예: `/srv/rag/output`)로 동작한다. 자세한 내용은 [docs/operations/server-guide.md](docs/operations/server-guide.md)(설치, 일상 실행, 문제 해결)와 [docs/operations/release-and-patch.md](docs/operations/release-and-patch.md)(빌드, 전송, 오버레이 패치, DB 버전 관리)에 있다.

> **이번 리팩토링 버전(S2~S12 — 첫 배포)은 [refactor.md](refactor.md) 맨 앞 "최종 — 사람이 할 일"의 순서(①검토 → ②배포 전 → ③배포 때 → ④배포 후)를 그대로 따른다.** 엔진 핑거프린트, 핸드오프 핑거프린트, code_fp가 모두 바뀌어 서버 문서 전체를 다시 파싱해야 하므로(재파싱 시간 산정 C-08이 먼저), 설정 이관, DB 버전 기록, 옛 컨테이너와 systemd 정리가 함께 필요하다.

### 4-1. PC에서 — 빌드와 전송
**버전:** 두 이미지는 저장소 루트 `VERSION`(SemVer, 지금 `0.1.0`)을 함께 쓴다. 이미지 태그는 `data-pipeline:<버전>`, `mcp-server:<버전>`이고, 빌드한 커밋은 이미지 라벨(`org.opencontainers.image.revision`)에 남는다. 회사 DB `AI.ParsingMeta.pipeline_version`과 실행 보드에도 이 버전이 기록된다. 버전은 `release/<버전>` 브랜치에서 올린다 — MAJOR(계약·스키마가 깨질 때), MINOR(새 이미지 버전), PATCH(오버레이 패치). 자세한 규칙은 [release-and-patch.md](docs/operations/release-and-patch.md) §5.
```bash
# 폐쇄망 빌드라면 deploy/docker/wheels/에 휠(linux/amd64, py3.12)을, 저장소 루트 assets/rapidocr/에 *.onnx를 먼저 둔다
BUILD_ONLY=1 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh   # data-pipeline:<VERSION> 빌드 → selftest 판정 → 비밀값 흔적 점검
BUILD_ONLY=1 IMAGE_TARGET=mcp      bash deploy/release/build_ship.sh   # mcp-server:<VERSION>

TARGET=user@서버 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh             # 또는 한 번에: 빌드→점검→저장→전송→적재(SSH — 같은 태그가 이미 있으면 멈춤)
bash deploy/release/ship_stage.sh pipeline mcp                                      # 또는 저장만(95MB 조각 + sha256, 태그 = VERSION)
```

### 4-2. 서버 — 설치와 첫 실행
```bash
# ① 이미지 적재(조각 파일이면 그 폴더에서)
sha256sum -c pipeline.sha256 && cat pipeline.tar.gz.part* | gunzip -c | docker load        # mcp-server는 mcp.*

# ② 코드 폴더 — 저장소 내용을 /srv/rag/code/live에(전체를 덮어쓴다면 먼저 백업 · 서버에서 직접 고친 코드는 server-changes.md를 보고 다시 반영)

# ③ 설정 파일
sudo mkdir -p /srv/rag/env && sudo chmod 700 /srv/rag/env
cp settings.sample.yaml /srv/rag/env/settings.yaml                 # 필요한 항목만 값을 채움
sudo chown 10001:<운영 그룹> /srv/rag/env/settings.yaml && sudo chmod 640 /srv/rag/env/settings.yaml
sudo mkdir -p /srv/rag/output && sudo chown 10001 /srv/rag/output   # 컨테이너 사용자 UID 10001
export SERVER_ENV_DIR=/srv/rag/env
```
서버 settings.yaml에 **반드시 적을 항목**(빠지면 시작을 거부하거나 동작이 조용히 바뀐다 — 전체 표는 refactor.md "최종" ②-1):
`common.run_env`(dev·stage·prd) · **`common.store.run_mode: prod`**(빠지면 PG 장애 때 SQLite로 대체된다) · PG·EDW·Object Storage 접속 항목 · 토큰(`mcp.server.token`, `pipeline.service.parse_mcp.token`, `pipeline.service.trigger.token`) · 이미지 이름(`pipeline.host.image`, `mcp.host.image`) · `settings.sample.yaml`에 `[서버 옛 값: …]`으로 표시된 항목. 옛 `pipeline.env`가 있으면 이관·대조 도구를 쓴다: `python -m common.config.migrate <옛 env> --out <yaml>` → `--compare`(release-and-patch §5-4). 모델 주소는 모두 내부망 주소여야 한다(서버는 외부 모델 호출을 거부한다).

```bash
cd /srv/rag/code/live
# ④ DB 버전(컨테이너를 띄우고 selftest를 하기 전에) — 처음 한 번 버전을 기록하고, 버전이 바뀌는 릴리스마다 up
( . deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh && \
  DC="docker compose -f deploy/host/compose/compose.pipeline.yml" && \
  $DC run --rm load migrate current && $DC run --rm load migrate check --target all )
#   → 검색 스키마는 차이가 0이면 migrate stamp --target search, struct는 migrate up --target struct
#     (컬럼·형식에 차이가 있으면 멈추고 DB 담당자와 협의 — 자세한 내용은 release-and-patch §5-5)

# ⑤ 점검
( . deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh && \
  docker compose -f deploy/host/compose/compose.pipeline.yml run --rm parse check )
docker run --rm data-pipeline:<태그> check-modules
bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest     # 기대: 알려진 실패 test_publish_guard 1개만
bash deploy/release/selftest_gate.sh docker run --rm mcp-server:<태그> selftest        # 기대: 실패 0
```
대화형 셸에서 `load_settings`를 그대로 실행해 값을 export하면, 이후 settings.yaml을 고쳐도 그 셸에는 반영되지 않는다. 그래서 위처럼 하위 셸 `( … )`로 감싼다.

### 4-3. 서버 — 실행
```bash
cd /srv/rag/code/live
bash deploy/host/scripts/mcp_up.sh              # 검색 MCP(상주) — 여러 번 실행해도 안전, 꺼져 있으면 띄우고 응답이 없으면 재시작
bash deploy/host/scripts/trigger.sh parse       # 파싱 → 대표 결과
bash deploy/host/scripts/trigger.sh structure   # 청킹·임베딩 → 번들
bash deploy/host/scripts/trigger.sh load        # pgvector 적재(PG가 없으면 종료 코드 4)
bash deploy/host/scripts/trigger.sh publish     # Object Storage 업로드 + EDW 메타데이터(트리거로만 실행)
bash deploy/host/scripts/trigger.sh night       # 새벽 배치 순서(parse publish structure load — publish는 설정이 켜져 있을 때만)
bash deploy/host/scripts/run_tool.sh <도구> [인자]   # score_gold · run_board · rdb_discover · check_env · mcp_eval 등
```
- 같은 결과 폴더에서 작업이 겹치면 나중에 시작한 작업은 종료 코드 75(실행 중)로 바로 끝난다.
- **systemd 타이머**(한 번만 설치 — DB 버전과 컨테이너를 확인한 뒤 켠다):
  `sudo cp deploy/host/systemd/{mcp-server-keepalive,data-pipeline-nightly}.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now mcp-server-keepalive.timer`
  새벽 배치는 스위치가 두 개다 — `data-pipeline-nightly.timer`(실행 시각은 그 `.timer` 파일의 `OnCalendar`)와 settings.yaml의 `pipeline.host.nightly.enabled: true`.
- **상주 트리거 서버**(웹 업로드에서 파싱을 직접 호출할 때, 선택): `docker compose -f deploy/host/compose/compose.pipeline.yml up -d data-pipeline-parse data-pipeline-structure`.
- **MCP `parse_document` 작업 서비스**는 compose가 띄우지 않으므로 직접 띄운다(파싱 컨테이너가 다시 시작될 때마다): `docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service`.
- **문서별 flow 러너** `run_docs.py`는 `<운영자 작업 폴더>/run_docs.py`에 두고 실행한다(코드 폴더 안의 사본이 아니다). 서버 settings.yaml의 운영 접속 항목을 읽고, 문서별 값은 컨테이너에 `--set`으로 넘긴다. 설계와 파라미터는 [docs/architecture/run_docs_design.md](docs/architecture/run_docs_design.md)에 있다. **PC에서는 실행하지 않는다**(운영 EDW와 Object Storage에 접속한다).
- 값 바꾸기: settings.yaml을 직접 고치고 상주 컨테이너(`data-pipeline-parse`, `data-pipeline-structure`, `mcp-server`)를 다시 띄운다. 한 번만 다른 값으로 실행할 때는 `--set 이름=값`을 쓴다. 오버레이 설정 파일 도구는 PC 전용이다(서버에서는 종료 코드 2).
- 엔진 구성·원천 목록 바꾸기와 되돌리기(DB 버전 테이블): `set-stack`, `set-stack --activate <버전>`, `show-stack`, 원천 목록은 `set-sources`, `show-sources` — [docs/architecture/pipeline_stack.md](docs/architecture/pipeline_stack.md).

### 4-4. 결과 확인
```bash
docker run --rm -v "$RAG_OUT:/app/output:ro" data-pipeline:<태그> tool run_board --out /app/output   # → output/report/run_board.html
bash deploy/host/scripts/run_tool.sh mcp_eval --set <세트>                                          # 검색 근거 평가
```

### 4-5. 코드만 고쳤을 때 — 오버레이 패치
의존성, Dockerfile, 마운트 경로가 그대로라면 이미지를 다시 만들지 않고 코드 폴더만 바꾼다: PC에서 `deploy/release/make_patch.sh`로 패치 번들을 만들고 → 서버에서 적용한 뒤 → `check-modules`와 `selftest_gate`로 확인한다. 새 이미지 버전이 필요한지와 순서는 [release-and-patch.md](docs/operations/release-and-patch.md) §1~§5에 있다.

---

## 5. 꼭 지킬 것(요약 — 전체는 [CLAUDE.md](CLAUDE.md) §2~§5)

- **결과 재사용 키를 함부로 바꾸지 않는다:** 엔진 파일(`pipeline/extract/engines/`)의 바이트, 핸드오프 핑거프린트(`FINGERPRINT`), 레이어 코드 핑거프린트(`code_fp`), 프롬프트 문구. 바뀌면 서버 문서가 다시 파싱된다. 확인 명령:
  `PYTHONPATH=. .venv/bin/python -c "import common as c; from common.core import artifacts as a; print(c.FINGERPRINT, {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)})"`
- **MCP 도구 4개의 이름과 입출력, DB 테이블·컬럼의 이름과 형식은 계약이다** — 바꾸려면 협의가 필요하다(DB는 Alembic 마이그레이션으로).
- **비밀값은 settings.yaml에만 둔다** — 문서, 로그, 커밋, 채팅에 쓰지 않는다. `settings.yaml`은 git에 올리지 않는다.
- PC에서 운영 DB나 운영 EDW에 접속하지 않는다(`run_docs.py` 로컬 실행 금지, `valid_env/structured/sales.sqlite`는 열지 않음).
- 배포 환경 규칙: 절대 경로 금지(서버·컨테이너 경로는 설정 값으로 — 이미지 배치에서 약속된 경로만 예외), 파일은 UTF-8·LF, 셸 스크립트는 bash 3.2/4/5 모두에서 동작하게, RHEL 마운트에는 `:z`, podman 사용을 전제로 확인.
- 새 외부 패키지는 승인을 받은 뒤에만 도입하고, `deploy/docker/` 의존성이 바뀌면 새 이미지 버전으로 배포한다.

## 6. 문서

| 문서 | 내용 |
|---|---|
| [docs/index.md](docs/index.md) | 문서 지도 |
| [CLAUDE.md](CLAUDE.md) | 개발 규칙 · 로컬 하네스 · 점검 명령 · 핑거프린트 기준값 |
| [refactor.md](refactor.md) | 서버·사람이 확인할 사항(C-xx) · **"최종 — 사람이 할 일"**(첫 배포 순서) |
| [docs/operations/server-guide.md](docs/operations/server-guide.md) | 서버 설치 · 운영 · 문제 해결 |
| [docs/operations/release-and-patch.md](docs/operations/release-and-patch.md) | 빌드 · 전송 · 오버레이 패치 · DB 버전 관리(migrate) · 배포 판정 |
| [docs/operations/env-guide.md](docs/operations/env-guide.md) | 설정 항목 작성 가이드 |
| [docs/architecture/](docs/architecture/) | 프롬프트 패키지(prompts.md) · 엔진 구성 버전 테이블(pipeline_stack.md) · run_docs 설계 |
| [docs/refactoring/refactor_plan.md](docs/refactoring/refactor_plan.md) | 리팩토링 가이드 · 결정 기록(D-xxx) · 파일 이동표 |

**알려진 문제(리팩토링 전부터):** 검색 결과의 "집계 경로 오류" 메모(축소 스키마에 없는 컬럼을 조회 — 검색 자체는 정상) 등은 CLAUDE.md §10에, 테스트의 알려진 실패는 refactor.md C-54·C-58에 있다.

> 옛 문서와 코드 주석에는 리팩토링 중에 쓰던 용어가 남아 있다(시험=테스트, 반입=배포, 칸=항목·컬럼, 판=버전, 지문=핑거프린트, 열쇠=키, 층=레이어, 묶음=번들, 대장=레지스트리, 인계=핸드오프, 덧씌우기=오버레이 패치, 게시=퍼블리시, 지시서=프롬프트). 대응표는 CLAUDE.md 끝에 있다.
