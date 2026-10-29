# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF·Office·HWPX·이미지·메일 등)를 파싱해 대표 결과를 만들고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 내부망(폐쇄망, RHEL) 서버에서 Docker/podman 이미지 2개로 돌고, 개발은 macOS·Windows PC에서 한다.

```
원천 문서(Object Storage · 폴더 · RDB 목록)
   │  parse     — dedup → prepare → 엔진별 파싱 → 대표 결과(_rep)          [data-pipeline 이미지]
   │  structure — 청킹 · 사실 추출 · 임베딩 → 묶음(bundle)
   │  load      — 묶음 → PostgreSQL(pgvector) 적재
   │  publish   — 대표 결과 Object Storage 업로드 + 회사 DB(EDW) 메타
   ▼
검색 MCP 서버 — 도구 4개: search · query_edw · parse_document · edw_meta      [mcp-server 이미지]
```

- 모듈은 한 결과 폴더(`RAG_OUT` — 컨테이너 `/app/output`)를 파일로 주고받는다. 앞 모듈이 끝 표시를 남겨야 다음이 시작한다(없으면 종료 코드 3).
- MCP 도구 4개의 이름·입출력은 바깥과의 계약이라 바꾸지 않는다.

> 이 저장소는 서버 코드 사본을 리팩토링한 결과다(10-26~10-29, 단계 S0~S11). 무엇이 왜 바뀌었는지는 [docs/refactoring/refactor_plan.md](docs/refactoring/refactor_plan.md), **서버에 처음 넣기 전에 사람이 할 일**은 [refactor.md](refactor.md) 맨 앞 "최종 — 사람이 할 일"이 정본이다.

---

## 1. 폴더 구조와 역할

```
.
├─ common/              공용 코드 — 두 앱(pipeline·mcp_server)이 함께 쓰는 것만
│  ├─ core/             경로·지문(FINGERPRINT·code_fp)·인계 계약·글자 처리·실행 기록
│  ├─ ai/               LLM·VLM·임베딩 호출(OpenAI 호환), 예산 장부·외부 전송 가드
│  ├─ store/            저장소 — PostgreSQL·정형 저장소(struct)·회사 DB(SQL Server)·Object Storage
│  │  └─ db/            SQLAlchemy 표 정의 · pydantic 행 모델 · Alembic 마이그레이션 · `dbtool`(migrate 명령)
│  ├─ config/           설정 모델(settings.yaml 읽기) · 샘플 생성 · 옛 env 이관(migrate) · 덮기 파일 · `--set`
│  └─ check/            모듈 경계 점검(check_modules) · 모델 연결 확인
├─ pipeline/            데이터 파이프라인 앱(data-pipeline 이미지)
│  ├─ cli.py            실행기 — parse·structure·load·publish·night·selftest 등 하위 명령
│  ├─ config.py         pipeline 절 설정 모델
│  ├─ extract/          원천 읽기·dedup·prepare·파싱(engines/ — 엔진 27개, 바이트가 캐시 열쇠라 손대지 않음)
│  ├─ transform/        represent(대표 결과) · figures(그림) · structure(청킹·임베딩·묶음)
│  ├─ load/             pgvector 적재 · 게시(publish) · 회사 DB 메타 · 색인 빌더
│  ├─ shared/ · tools/  단계 공용 조각 · 운영 도구
│  ├─ eval/             채점·실행판(score_gold·run_board 등)
│  └─ trigger_server.py · mcp_parse_service.py · stream.py · parse_parallel.py   상주 트리거·MCP 파싱 작업·스트리밍
├─ mcp_server/          검색 MCP 앱(mcp-server 이미지) — FastMCP
│  ├─ main.py           진입점(앱 조립·토큰·서버 시작)
│  ├─ config.py         mcp 절 설정 모델
│  ├─ routers/          도구 4개·/health 등록(이름·서명 고정)
│  ├─ schemas/          출력 모양
│  ├─ services/         EDW 질의·파싱 중계·메타 · search/(하이브리드 검색·근거 다듬기·재순위)
│  └─ cli/              ask(질의 시험)·mcp_smoke·mcp_eval·registry_cli
├─ resources/           코드가 읽는 데이터(이미지에 들어감)
│  ├─ prompts/          AI 지시서 패키지 {common,pipeline,mcp}
│  ├─ config/           엔진 구성 pipeline_stack.json(PC용 — 서버는 DB 판 표) · 채점 기준 criteria.json · 보고서 틀
│  ├─ mappings/         원천 목록 sources.json(PC용 — 서버는 DB 판 표) · 문서 메타 대응
│  ├─ vocab/            집계 어휘·질문 유형·용어집
│  └─ sql/              DB 시드(판 번호가 붙은 사본 — 한 번 배포하면 고치지 않음)
├─ deploy/              배포
│  ├─ docker/           Dockerfile(타깃 pipeline·mcp) · requirements · entrypoint.sh · wheels/(폐쇄망 휠)
│  ├─ release/          이미지 빌드·전송(build_ship·ship_stage) · 덧씌우기 묶음(make_patch) · 반입 판정(selftest_gate·known_fail.txt)
│  └─ host/             서버 호스트에서 부르는 것 — compose/ · systemd/(새벽 배치·keepalive) · scripts/(trigger·run_tool·mcp_up·settings_env·run_docs 등)
├─ tests/               시험 — server/(이미지에 들어가 반입 판정) · general/(PC 전용) · fixtures/ · runner.py
├─ validation/          PC 전용 검증 도구(이미지에 안 들어감)
│  ├─ search_ui/        검증 페이지 — 검색 MCP·pgvector를 브라우저로 확인
│  └─ e2e/              평가·비교 도구(stack_matrix·model_matrix·graph_llm·answer_gen) · triple_extract 지시서
├─ valid_env/           PC 전용 데이터(내부망 배포에서는 쓰지 않음 — 한 곳에 모음)
│  ├─ unstructured/     합성 시험 문서와 정답(Object Storage 대역)
│  ├─ answer_test/      답변 점검 agent rag_qa
│  └─ docker/           PC 시험 Docker(compose.pg·compose.test·smoke_test)
├─ docs/                문서(지도: docs/index.md) — operations/(서버 운영) · architecture/ · requirements/ · refactoring/
├─ settings.sample.yaml 설정 칸 전부의 구조·설명(값 없음, 생성물 — 손으로 고치지 않음)
├─ settings.yaml        PC 로컬 설정(git 제외 · 권한 600 — 직접 만듦)
├─ refactor.md          서버·사람이 확인할 사항(C-xx) · "최종 — 사람이 할 일"
└─ CLAUDE.md            작업 규칙(지문·계약·경계·배포 환경 규칙·점검 명령)
```

**경계:** `pipeline`과 `mcp_server`는 서로 import하지 않고 공용 코드는 `common`만 쓴다. 앱은 `validation`·`tests`를 import하지 않는다. `python -m common.check.check_modules`가 확인한다.

**서버 이미지 2개**

| 이미지 | 역할 | 돌리는 것 |
|---|---|---|
| `data-pipeline` | 파싱·구조화·적재·게시 | compose 서비스 `parse`·`structure`·`load`·`publish` · 상주 트리거 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`(선택) |
| `mcp-server` | 검색 MCP(상주) + 도구 | 상주 컨테이너 `mcp-server` · 도구 job `retrieval` |

---

## 2. 설정 — `settings.yaml` 하나

- 모든 설정 값과 비밀값(DB 접속·비밀번호·API 키·토큰)은 **settings.yaml 한 파일**에 둔다. 코드는 환경변수로 설정을 읽지 않는다(옛 env 이름을 줘도 무시하고 이름만 경고).
- 구조·칸 설명·기본값은 [settings.sample.yaml](settings.sample.yaml)에 있다. 최상위 절은 `common`(공용)·`pipeline`·`mcp`이고, 각 앱은 `common` + 자기 절만 읽는다.
- 실제 파일에는 **기본값과 다르게 쓸 칸만** 적는다. 비운 칸은 코드 기본값을 쓴다.
- 자리: PC는 저장소 루트 `settings.yaml`(git 제외, 권한 600), 서버는 `$SERVER_ENV_DIR/settings.yaml`(기본 `/srv/rag/env`, 주인 UID 10001·권한 640). `SETTINGS_FILE`(env)로 다른 파일을 가리킬 수 있다.
- `common.run_env`(또는 env `RUN_ENV`)는 필수다 — `local`(PC)·`dev`·`stage`·`prd`(서버 — 외부 모델 거부, 설정 파일을 못 읽으면 시작 거부).
- 한 번 실행에만 다른 값: 명령 인자 `--set 이름=값`(이름은 sample의 `env=`, 비밀 칸·호스트 칸은 거부). PC에서는 덮기 파일도 된다(`python -m common.config.overrides 이름=값 …` — 원본을 `base`로 가리키는 작은 yaml 경로를 출력).
- 칸별 설명·판마다 바뀐 설정은 [docs/operations/env-guide.md](docs/operations/env-guide.md).

---

## 3. 로컬(PC)에서 실행

### 3-1. 준비
```bash
# Python 3.12 가상환경 — 서버 이미지와 같은 패키지
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt   # 마지막은 PC 개발 도구(ruff·mypy·pytest)
git config core.hooksPath .githooks   # 커밋할 때 바꾼 파일 점검(ruff·mypy·모듈 경계)이 자동으로 돎 — CLAUDE.md §5-2

# 전용 pgvector(PG 16 + pgvector) — 127.0.0.1:55433, 처음 한 번(뒤로는 docker start sbl-mcp-pg / docker stop sbl-mcp-pg)
docker run -d --name sbl-mcp-pg -p 127.0.0.1:55433:5432 -v sbl_mcp_pgdata:/var/lib/postgresql/data \
  -e POSTGRES_DB=rag -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16
# (valid_env/docker/compose.pg.yml은 개발 서버용 단독 PG — 포트 5432·메모리 4GB 기본값)
```
저장소 루트에 `settings.yaml`을 만든다(`settings.sample.yaml`을 보고 필요한 칸만, `chmod 600`). PC 최소 예(값은 각자):
```yaml
common:
  run_env: local
  connections:
    pg: {host: 127.0.0.1, port: 55433, db: <db>, user: <user>, password: <비밀번호>, db_schema: <스키마>}
  models:
    guard: {no_paid_calls: true}          # 기본은 유료 호출 막음 — 필요한 실행에서만 --set으로 풂
    embed: {base_url: <OpenAI 호환 주소>, model: <임베딩 모델>, api_key: <키>}
  store: {run_mode: prod}
  runtime: {cpu_max_load: 5}              # 부하가 높은 PC면 올림(기본 0.9)
```
> ⚠️ PG 접속 칸을 비우면 코드가 `docker ps`로 아무 pgvector에나 붙는다. 전용 PG 접속 값을 늘 적는다.

명령은 저장소 루트에서 `PYTHONPATH`를 주고 돌린다:
```bash
export PYTHONPATH=$PWD
.venv/bin/python -m pipeline.config          # 어느 설정 파일을 읽는지·요약(비밀 가림)
```

### 3-2. 점검
```bash
.venv/bin/python -m common.check.check_modules      # 모듈 경계 — "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check   # 설정 키 대조 — "빠진 키 0개"
.venv/bin/python -m pipeline.cli selftest           # 서버 반입 시험(tests/server) — 89개 중 88개(알려진 FAIL 1개)
.venv/bin/python -m pytest -q tests/                 # 반입 시험 + PC 일반 시험 — 142 passed · 8 xfailed(알려진 FAIL)
bash deploy/release/lint_changed.sh                  # 커밋 전 — 바꾼 .py만 ruff·mypy·모듈 경계(FIX=1이면 자동 수정·포맷)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && PYTHONPATH=. .venv/bin/mypy   # 저장소 전체 린트·포맷·타입 — 모두 0(S12)
```
코드를 고칠 때의 규칙(폴더 배치·경로·설정·지문·커밋 전 점검·push 전 `/simplify`·`/code-review`)은 [CLAUDE.md](CLAUDE.md)에 있다.
알려진 FAIL은 모두 리팩토링 전부터 있던 것이다 — 이유는 [refactor.md](refactor.md) C-54·C-58, 목록은 `deploy/release/known_fail.txt`·`tests/conftest.py`.

### 3-3. 파싱 → 임베딩 → 적재 → 검색(문서 몇 건)
서버 실제 경로와 같은 순서다. 실행마다 바뀌는 값은 `--set`으로 준다(아래는 시험 스키마·결과 폴더·외부 임베딩 허용·예산 — 외부 유료 호출은 두 잠금(`EMBED_ALLOW_EXTERNAL`·`LLM_SYNTHETIC_TRUTH` — 합성 시험 문서 선언 파일)과 예산 상한이 함께 있어야 나간다).
```bash
O=$PWD/output/demo; mkdir -p $O/src; cp valid_env/unstructured/synth-realpat/{hidden_term,merged_table}.docx $O/src/
SETS=(--set PIPE_OUT_ROOT=$O --set PG_SCHEMA=demo --set EMBED_ALLOW_EXTERNAL=1 --set LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json>
      --set NO_PAID_CALLS=0 --set LLM_BUDGET_USD=0.10 --set LLM_MAX_CALLS=10 --set LLM_SPEND_FILE=$O/spend.json)

.venv/bin/python -m pipeline.cli "${SETS[@]}" parse --src $O/src                                   # 파싱 → $O/parse/_rep
.venv/bin/python -m pipeline.transform.structure.build_bundle "${SETS[@]}" \
    --parse-dir $O/parse --src $O/src --embed api --summary lead --out $O/bundle                     # 청킹·임베딩 → 묶음
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle          # 표 만들기·판 기록(새 PG면 --create-extension)
.venv/bin/python -m pipeline.load.pgvector_load "${SETS[@]}" load --bundle $O/bundle               # pgvector 적재
```
검색 확인(MCP 없이) — `ask`는 `--set`을 받지 않으므로 루트 `settings.yaml`을 `base`로 하는 덮기 파일로 같은 값을 준다:
```bash
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo EMBED_ALLOW_EXTERNAL=1 LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json> \
     NO_PAID_CALLS=0 LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json)
SETTINGS_FILE=$SF .venv/bin/python -m mcp_server.cli.ask ask --pg --bundle $O/bundle --k 3 --q "<질문>"
```
- 임베딩 캐시(`output/edw/embed_cache.sqlite`) 덕분에 같은 청크는 다시 호출하지 않는다. 실제 호출을 보려면 `--set EMBED_CACHE=<빈 sqlite 경로>`.
- 엔진 구성·원천 목록은 PC에서는 `resources/config/pipeline_stack.json`·`resources/mappings/sources.json`을 읽는다(서버는 DB 판 표).

### 3-4. 검색 MCP 서버
MCP 서버 진입점도 `--set`을 받지 않으므로 덮기 파일로 띄운다(포트·저장소·묶음 자리를 더함):
```bash
SF=$(.venv/bin/python -m common.config.overrides PG_SCHEMA=demo MCP_STORE=pg MCP_BUNDLE=$O/bundle MCP_PORT=18769 \
     EMBED_ALLOW_EXTERNAL=1 LLM_SYNTHETIC_TRUTH=<합성 문서 선언 json> NO_PAID_CALLS=0 LLM_BUDGET_USD=0.10 LLM_SPEND_FILE=$O/spend.json)
SETTINGS_FILE=$SF nohup .venv/bin/python -m mcp_server.main > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
curl -s http://127.0.0.1:18769/health          # {"ok":true,"ready":true,"store":"pgvector",…}
kill $(cat $O/mcp.pid)                           # 끄기 — PID로만
```
MCP 엔드포인트는 `http://127.0.0.1:<포트>/mcp`(streamable HTTP)다. 루프백이면 토큰 없이 붙고, 그 밖에 바인드하면 `mcp.server.token`이 필요하다.

### 3-5. 검증 페이지(브라우저로 검색 확인)
설정은 저장소 루트 `settings.yaml` 하나다(따로 두는 페이지 설정 파일 없음 — 사용자 10-29). 페이지가 쓰는 칸을 루트 파일에 더한다(비운 칸은 코드 기본값 — 포트 8765·8790, 묶음 없음):
```yaml
common:
  paths: {mcp_bundle: output/validation/bundle}   # 검색할 묶음
  models:
    guard: {no_paid_calls: true, budget_usd: 0.1, max_calls: 40, spend_file: output/spend-ledger.json, synthetic_truth: <합성 문서 선언 json>}
    embed: {allow_external: true, …}             # 외부 허용 첫째 잠금(둘째는 synthetic_truth)
mcp:
  dev: {mcp_url: "http://127.0.0.1:18767/mcp", ui_port: 8791}
  server: {host: 127.0.0.1, port: 18767, store: pg, warmup: false}
```
외부 임베딩 스위치는 `common.models.guard.no_paid_calls` 하나다. `true`면 질의 임베딩을 포함한 외부 호출을 모두 거부하고, 검색은 키워드·ID로만 돈다(근거 via에 `v` 없음). 벡터 검색까지 보려면 `false`로 바꾸고 MCP를 다시 띄운다. 이 값은 PC의 다른 실행(시험·파이프라인)에도 걸리므로 확인이 끝나면 `true`로 되돌린다. 두 잠금(`allow_external`·`synthetic_truth`) 중 하나라도 비우면 `false`여도 외부로 나가지 않는다.
```bash
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791  ·  /api/health · /api/tools · /api/chunk/<id>
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```
다른 묶음을 보려면 루트 파일의 `common.paths.mcp_bundle`(과 다른 스키마면 `common.connections.pg.db_schema`)을 바꾸고 다시 띄운다.

### 3-6. 그 밖
- 답변 생성 점검(PC 전용): `.venv/bin/python -m validation.e2e.answer_gen --url http://127.0.0.1:18767/mcp --q "<질문>"` — `valid_env/answer_test/rag_qa` agent로 답·인용·인용 검증. LLM 설정(`common.models.llm`)과 예산 상한이 필요하다.
- PC 시험 Docker(이미지 배치 그대로): `valid_env/docker/smoke_test.sh`.
- 이미지 로컬 빌드: `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<태그> bash deploy/release/build_ship.sh` → `bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest`(판정은 `[판정]` 줄). Docker 23 미만은 `build_ship.sh`가 BuildKit 인자를 스스로 붙인다.

---

## 4. 내부망(서버) 배포와 실행

서버는 이미지 2개 + 코드 폴더(`PATCH_CODE`, 기본 `/srv/rag/code/live`) + 설정 파일(`/srv/rag/env/settings.yaml`) + 결과 폴더(`RAG_OUT`, 예 `/srv/rag/output`)로 돈다. 상세는 [docs/operations/server-guide.md](docs/operations/server-guide.md)(설치·일상 실행·문제 해결)와 [docs/operations/release-and-patch.md](docs/operations/release-and-patch.md)(빌드·전송·덧씌우기·DB 판)다.

> **이번 리팩토링 판(S2~S11 — 첫 반입)은 [refactor.md](refactor.md) 맨 앞 "최종 — 사람이 할 일"의 순서(①검토 → ②반입 전 → ③반입 때 → ④반입 뒤)를 그대로 따른다.** 엔진 지문·인계 지문·code_fp가 모두 바뀌어 서버 문서 전체를 다시 파싱하므로(재파싱 시간 산정 C-08이 먼저), 설정 이관·DB 판 기록·옛 컨테이너·systemd 정리가 함께 필요하다.

### 4-1. PC에서 — 빌드·전송
```bash
# 폐쇄망 빌드면 deploy/docker/wheels/에 휠(linux/amd64·py3.12), 저장소 루트 assets/rapidocr/*.onnx를 먼저 둔다
docker build -f deploy/docker/Dockerfile --target pipeline -t data-pipeline:<태그> .
docker build -f deploy/docker/Dockerfile --target mcp      -t mcp-server:<태그> .
bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest   # [판정] 통과 확인(알려진 FAIL 밖 0)

TARGET=user@서버 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh             # 빌드→점검→저장→전송→적재(SSH)
bash deploy/release/ship_stage.sh <태그> pipeline mcp                                # 또는 저장만(95MB 조각 + sha256)
```

### 4-2. 서버 — 설치·첫 실행
```bash
# ① 이미지 적재(조각이면 그 폴더에서)
sha256sum -c pipeline.sha256 && cat pipeline.tar.gz.part* | gunzip -c | docker load        # mcp-server는 mcp.*

# ② 코드 폴더 — 저장소 내용을 /srv/rag/code/live에(전체 덮어쓰기면 먼저 백업 · 서버에서 직접 고친 코드는 server-changes.md를 보고 다시 얹음)

# ③ 설정 파일
sudo mkdir -p /srv/rag/env && sudo chmod 700 /srv/rag/env
cp settings.sample.yaml /srv/rag/env/settings.yaml                 # 값 채우기 — 필요한 칸만
sudo chown 10001:<운영 그룹> /srv/rag/env/settings.yaml && sudo chmod 640 /srv/rag/env/settings.yaml
sudo mkdir -p /srv/rag/output && sudo chown 10001 /srv/rag/output   # 컨테이너 사용자 UID 10001
export SERVER_ENV_DIR=/srv/rag/env
```
서버 settings.yaml에 **꼭 적을 칸**(빠지면 시작 거부하거나 조용히 동작이 바뀜 — 전체 표는 refactor.md "최종" ②-1):
`common.run_env`(dev·stage·prd) · **`common.store.run_mode: prod`**(빠지면 PG 장애 때 SQLite로 대체됨) · PG·EDW·Object Storage 접속 칸 · 토큰(`mcp.server.token`·`pipeline.service.parse_mcp.token`·`pipeline.service.trigger.token`) · 이미지 이름(`pipeline.host.image`·`mcp.host.image`) · `settings.sample.yaml`의 `[서버 옛 값: …]` 표시 칸. 옛 `pipeline.env`가 있으면 옮기기·대조 도구: `python -m common.config.migrate <옛 env> --out <yaml>` → `--compare`(release-and-patch §5-4). 모델 주소는 모두 내부망(서버는 외부 모델 거부).

```bash
cd /srv/rag/code/live
# ④ DB 판(컨테이너 띄우기·selftest 전) — 처음 한 번 판 기록, 판이 바뀌는 릴리스마다 up
( . deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh && \
  DC="docker compose -f deploy/host/compose/compose.pipeline.yml" && \
  $DC run --rm load migrate current && $DC run --rm load migrate check --target all )
#   → 검색 스키마는 차이 0이면 migrate stamp --target search · struct는 migrate up --target struct
#     (차이가 칸·형식이면 멈추고 DB 담당과 협의 — 상세 release-and-patch §5-5)

# ⑤ 점검
( . deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh && \
  docker compose -f deploy/host/compose/compose.pipeline.yml run --rm parse check )
docker run --rm data-pipeline:<태그> check-modules
bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest     # 기대: 알려진 FAIL test_publish_guard 1개만
bash deploy/release/selftest_gate.sh docker run --rm mcp-server:<태그> selftest        # 기대: FAIL 0
```
대화형 셸에 `load_settings`를 그대로 export하면 그 뒤 settings.yaml을 고쳐도 그 셸에는 안 먹으므로, 위처럼 하위 셸 `( … )`로 감싼다.

### 4-3. 서버 — 실행
```bash
cd /srv/rag/code/live
bash deploy/host/scripts/mcp_up.sh              # 검색 MCP(상주) — 멱등, 꺼져 있으면 띄우고 응답 없으면 재시작
bash deploy/host/scripts/trigger.sh parse       # 파싱 → 대표 결과
bash deploy/host/scripts/trigger.sh structure   # 청킹·임베딩 → 묶음
bash deploy/host/scripts/trigger.sh load        # pgvector 적재(PG 없으면 종료 4)
bash deploy/host/scripts/trigger.sh publish     # Object Storage 업로드 + EDW 메타(트리거로만)
bash deploy/host/scripts/trigger.sh night       # 새벽 배치 순서(parse publish structure load — publish는 설정이 켜져 있을 때만)
bash deploy/host/scripts/run_tool.sh <도구> [인자]   # score_gold · run_board · rdb_discover · check_env · mcp_eval 등
```
- 같은 결과 폴더에 작업이 겹치면 뒤쪽은 종료 코드 75(실행 중)로 바로 끝난다.
- **systemd 타이머**(설치 1회 — DB 판·컨테이너 확인 뒤 켬):
  `sudo cp deploy/host/systemd/{mcp-server-keepalive,data-pipeline-nightly}.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now mcp-server-keepalive.timer`
  새벽 배치는 스위치가 둘이다 — `data-pipeline-nightly.timer`(실행 시각은 그 `.timer`의 `OnCalendar`)와 settings.yaml `pipeline.host.nightly.enabled: true`.
- **상주 트리거 서버**(웹 업로드가 파싱을 직접 부를 때, 선택): `docker compose -f deploy/host/compose/compose.pipeline.yml up -d data-pipeline-parse data-pipeline-structure`.
- **MCP `parse_document` 작업 서비스**는 compose가 띄우지 않으므로 손으로 띄운다(파싱 컨테이너가 다시 시작될 때마다): `docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service`.
- **문서별 flow 러너** `run_docs.py`는 `<운영자 작업 폴더>/run_docs.py`에 두고 돌린다(코드 폴더 안 사본이 아님). 서버 settings.yaml의 운영 접속 칸을 읽고, 문서별 값은 컨테이너에 `--set`으로 넘긴다. 설계·파라미터는 [docs/architecture/run_docs_design.md](docs/architecture/run_docs_design.md). **PC에서는 실행하지 않는다**(운영 EDW·Object Storage에 접속).
- 값 바꾸기: settings.yaml을 직접 고치고 상주 컨테이너(`data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)를 다시 띄운다. 한 번 실행에만 다른 값은 `--set 이름=값`. 덮기 파일 도구는 PC 전용(서버는 종료 2).
- 엔진 구성·원천 목록 바꾸기·되돌리기(DB 판 표): `set-stack`·`set-stack --activate <판>`·`show-stack`, 원천 목록은 `set-sources`·`show-sources` — [docs/architecture/pipeline_stack.md](docs/architecture/pipeline_stack.md).

### 4-4. 결과 확인
```bash
docker run --rm -v "$RAG_OUT:/app/output:ro" data-pipeline:<태그> tool run_board --out /app/output   # → output/report/run_board.html
bash deploy/host/scripts/run_tool.sh mcp_eval --set <세트>                                          # 검색 근거 평가
```

### 4-5. 코드만 고친 때 — 덧씌우기(패치)
의존성·Dockerfile·마운트 경로가 그대로면 이미지를 다시 만들지 않고 코드 폴더만 바꾼다: PC에서 `deploy/release/make_patch.sh`로 묶음 → 서버에서 적용 → `check-modules`·`selftest_gate`. 새 이미지 판이 필요한지·순서는 [release-and-patch.md](docs/operations/release-and-patch.md) §1~§5.

---

## 5. 꼭 지킬 것(요약 — 전체는 [CLAUDE.md](CLAUDE.md) §2~§5)

- **결과 재사용 열쇠를 함부로 바꾸지 않는다:** 엔진 파일(`pipeline/extract/engines/`) 바이트 · 인계 지문(`FINGERPRINT`) · 층 코드 지문(`code_fp`) · 지시문 글자. 바뀌면 서버 문서가 다시 파싱된다. 확인:
  `PYTHONPATH=. .venv/bin/python -c "import common as c; from common.core import artifacts as a; print(c.FINGERPRINT, {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)})"`
- **MCP 도구 4개의 이름·입출력, DB 표·칸 이름·형식은 계약이다** — 바꾸려면 협의(DB는 Alembic 마이그레이션으로).
- **비밀값은 settings.yaml에만** — 문서·로그·커밋·채팅에 쓰지 않는다. `settings.yaml`은 git에 올리지 않는다.
- 운영 DB·운영 EDW에 PC에서 접속하지 않는다(`run_docs.py` 로컬 실행 금지 · `valid_env/structured/sales.sqlite` 열지 않음).
- 배포 환경 규칙: 절대 경로 금지(서버·컨테이너 경로는 설정 값으로 — 이미지 배치 약속 경로만 예외), 파일은 UTF-8·LF, 셸은 bash 3.2/4/5 모두에서, RHEL 마운트에 `:z`, podman 전제 확인.
- 새 외부 패키지는 승인 뒤에만, `deploy/docker/` 의존성이 바뀌면 새 이미지 판.

## 6. 문서

| 문서 | 무엇 |
|---|---|
| [docs/index.md](docs/index.md) | 문서 지도 |
| [CLAUDE.md](CLAUDE.md) | 작업 규칙 · 로컬 하네스 · 점검 명령 · 지문 기준선 |
| [refactor.md](refactor.md) | 서버·사람 확인 사항(C-xx) · **"최종 — 사람이 할 일"**(첫 반입 순서) |
| [docs/operations/server-guide.md](docs/operations/server-guide.md) | 서버 설치·운영·문제 해결 |
| [docs/operations/release-and-patch.md](docs/operations/release-and-patch.md) | 빌드·전송·덧씌우기·DB 판(migrate)·반입 판정 |
| [docs/operations/env-guide.md](docs/operations/env-guide.md) | 설정 칸 작성 가이드 |
| [docs/architecture/](docs/architecture/) | 지시서 패키지(prompts.md) · 엔진 구성 판 표(pipeline_stack.md) · run_docs 설계 |
| [docs/refactoring/refactor_plan.md](docs/refactoring/refactor_plan.md) | 리팩토링 가이드·결정 장부(D-xxx)·이동표 |

**알려진 문제(리팩토링 전부터):** 검색 결과의 "집계 경로 오류" 메모(축소 스키마에 없는 칸 조회 — 검색 자체는 정상) 등은 CLAUDE.md §10, 시험의 알려진 FAIL은 refactor.md C-54·C-58.
