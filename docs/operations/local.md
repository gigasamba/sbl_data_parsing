# PC(local) 실행 순서

저장소 루트에서 차례로 친다. `<…>`는 바꿔 넣을 자리. 앱 컨테이너 없이 Python으로 직접 돌리고(Docker는 전용 pgvector만 — 서버와 같은 컨테이너 시험은 8), 순서는 서버의 처리 순서와 같다. 설정 칸 뜻은 [settings.md](settings.md).

## 1. 가상환경(처음 한 번)
```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt
git config core.hooksPath .githooks          # 커밋·push 때 점검 자동 실행
```

## 2. settings.yaml
```bash
cp settings.sample.yaml settings.yaml && chmod 600 settings.yaml
```
꼭 채울 칸: `required.env.run_env: local` · `required.pg`(아래 3의 값 — 다섯 칸 모두, 빈 칸이 있으면 시작 거부) · `required.models`(임베딩·LLM·VLM 주소·모델·키). EDW·Object Storage·토큰·배포 칸은 채우지 않는다(PC는 무시 — [settings.md](settings.md#pc-전용-칸)). 기본값과 다르게 쓸 칸만 적은 예:

```yaml
required:
  env: {run_env: local}
  pg: {pg_host: 127.0.0.1, pg_port: 55433, pg_database: rag, pg_user: pgvector, pg_password: <비밀번호>, pg_schema: demo}   # 적재·검색할 스키마
  models:
    embed_base_url: <OpenAI 호환 주소>
    embed_api_key: <키>
    embed_model: <임베딩 모델>
    llm_base_url: <주소>
    llm_model: <모델>
    vlm_base_url: <주소>
    vlm_model: <모델>
ops:
  paths: {container_output_dir: output/demo}     # 파이프라인 결과 폴더
search:
  server: {mcp_bind_host: 127.0.0.1, mcp_port: 18769}
dev:
  models:
    embed: {embed_allow_external: false}         # 평소 false — 임베딩이 필요한 실행 동안만 true
    guard: {daily_budget_usd: 0.1}               # 외부 모델 하루 지출 상한($)
  search_ui: {search_ui_mcp_url: "http://127.0.0.1:18769/mcp", search_ui_port: 8791}   # 검증 페이지(7)
tuning:
  ops:
    runtime: {max_cpu_load: 5}                   # 부하가 높은 PC라면(기본 0.9에서는 계속 대기함)
```

## 3. PC 시험 DB(pgvector)
배포 판정 시험(selftest)과 pytest의 DB 사례는 이 PG에 붙는다(sqlite 대역 없음). `required.deploy.pg_container_name: pgvector`와 `required.pg`가 채워져 있으면 시험이 붙지 못할 때 스스로 아래 만들기·켜기·기다리기를 한다 — 그래도 못 붙으면 그 사례가 FAIL. 손으로는 아래 순서. 폐쇄망 PC는 먼저 `docker load -i <pgvector tar>`.
```bash
docker ps -a --filter name=^pgvector$ --format '{{.Status}}'      # 빈 줄 = 없음 · Exited = 멈춤 · Up = 돌고 있음
docker run -d --name pgvector --restart no --memory 1g --cpus 2 -p 127.0.0.1:55433:5432 \
  -v sbl_mcp_pgdata:/var/lib/postgresql/data -e POSTGRES_DB=rag -e POSTGRES_USER=pgvector \
  -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16          # 없을 때만
docker start pgvector                                              # 멈췄을 때
until docker exec pgvector pg_isready -h 127.0.0.1 -U pgvector -d rag; do sleep 1; done   # -h: 처음 만들 때의 초기화용 서버에 속지 않게
```
settings.yaml: `pg_host: 127.0.0.1` · `pg_port: 55433` · `pg_database: rag` · `pg_user: pgvector` · `pg_password: <비밀번호>` · `required.deploy.pg_container_name: pgvector`.

`POSTGRES_PASSWORD`는 볼륨을 처음 만들 때만 걸린다. 볼륨이 이미 다른 비밀번호로 있으면 손으로 바꾼다(값은 화면·기록에 남기지 않는다):
```bash
docker exec -i pgvector psql -U pgvector -d rag -c "ALTER USER pgvector PASSWORD '<settings.yaml 값>'"
```

## 4. 점검
```bash
export PYTHONPATH=$PWD                                 # 작업 폴더(worktree)면 export RUN_ENV=local도 — 없으면 output/이 저장소 한 단계 위에 생김
.venv/bin/python -m pipeline.config                    # 읽은 settings.yaml과 요약(비밀은 가림)
.venv/bin/python -m common.check.check_modules         # 기대: 모듈 경계 통과
.venv/bin/python -m common.config.keyscan --check      # 기대: 빠진 키 0개
bash deploy/release/lint_changed.sh                    # 기대: [점검] 통과(FIX=1이면 자동 수정)
.venv/bin/python -m pipeline.cli selftest              # 기대: [판정] 통과(기준선 PRD e2-02)
.venv/bin/python -m pytest -q tests/                    # 기대: 실패 0
```

## 5. 문서 몇 건 돌리기(파싱 → 구조화 → DB 표 → 적재 → 검색)
임베딩을 부르므로 settings.yaml `dev.models.embed.embed_allow_external: true`로 바꾼다(끝나면 `false`). 분류(SFDC·LAS)·VLM까지 보려면 `llm_allow_external`·`vlm_allow_external`도(비우면 분류가 실패해 SFDC·LAS 문서는 적재되지 않음).

### 5-1. 문서 고르기
```bash
O=output/demo; SRC=$O/src
for s in SFDC CRMS; do mkdir -p $SRC/$s; for d in $(ls -d valid_env/object_storage/$s/*/ | head -2); do cp -r "$d" $SRC/$s/; done; done
cp valid_env/edw/edw.sqlite $O/edw.sqlite             # 가짜 EDW 사본
```
- 문서는 `valid_env/object_storage/<원천>/<uuid>/<파일>`(목록·목적: [test_doc_purpose.md](../../valid_env/object_storage/test_doc_purpose.md)). `<원천>/<uuid>/<파일>` 꼴 그대로 둔다 — 파싱이 상대 키로 원천을 알아본다.
- `valid_env`에는 쓰지 않는다 — 예외 둘: 가짜 EDW 사본 `valid_env/edw/edw_copy.sqlite`와 게시 폴더 `valid_env/object_storage/Parsing_Result/`(둘 다 PC 실행이 만들고 git이 무시함). 그 밖의 결과는 모두 `ops.paths.container_output_dir` 아래.

### 5-2. 적재 안 된 문서 표(처음 한 번)
```bash
.venv/bin/python -m common.store.db.dbtool up --target applog
```
받기가 DRM·암호·지원 안 함·내용 중복 문서를 `applog.except_doc_info`에 쓰는데, 표가 없으면 그 문서에서 파싱이 멈춘다. 5-5의 `up --target all`에도 들어 있다.

### 5-3. 파싱
```bash
.venv/bin/python -m pipeline.cli --set PIPE_OUT_ROOT=$O --set RDB_SQLITE=$O/edw.sqlite parse --source $SRC --src $O/prepared
```
- `--source`는 원본 폴더, `--src`는 준비된 파일이 놓이는 곳(`--src`만 주면 준비된 폴더로 보고 가져오기·중복 제거를 건너뜀). `--set RDB_SQLITE`를 빼면 `valid_env/edw/edw_copy.sqlite`를 쓴다.
- 끝난 문서는 검색 DB(gold `doc` 표)에서 읽는다 — 서버에서 PG를 못 읽으면 종료 4. 돌 문서가 없으면 `[parse] 이번 실행 0건 …` 한 줄과 종료 0.
- 결과: `$O/parse/<엔진>/`, `$O/parse/_rep/`(문서마다 하나 + `_DONE.json`).

### 5-4. 마스터 표 → 구조화·임베딩
구조화의 고객 판별이 마스터 표를 읽으므로 새 스키마면 먼저 만들어 채운다(서버는 마스터 표가 비었으면 구조화·검색이 시작하지 않음). `resources/vocab/glossary/glossary.csv`를 고치면 `master load`를 다시 돌린다(이미 적재한 문서는 자동으로 다시 처리하지 않음).
```bash
.venv/bin/python -m common.store.db.dbtool up --target master --schema demo
.venv/bin/python -m common.store.db.dbtool master load --schema demo
.venv/bin/python -m pipeline.transform.structure.gold_bundle --set PIPE_OUT_ROOT=$O \
  --parse-dir $O/parse --src $O/prepared --embed api --out $O/bundle
```
결과: `$O/bundle/`(docs.jsonl · chunks.jsonl · vectors.npy · meta.json). 같은 청크는 임베딩 캐시(`output/edw/embed_cache.sqlite`)로 다시 호출하지 않는다 — 실제 호출을 보려면 `--set EMBED_CACHE=<빈 sqlite 경로>`.

### 5-5. DB 표 만들기(스키마마다 처음 한 번)
```bash
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle --create-extension
.venv/bin/python -m common.store.db.dbtool current --target all   # 기대: search 0007_search · applog 0005_applog · master 0002_master
.venv/bin/python -m common.store.db.dbtool check --target all     # 기대: 종료 코드 0
```
`--bundle`은 벡터 차원을 `meta.json`에서 읽으려고 준다(또는 `--dim`), `--create-extension`은 새 PG일 때만. 명령 전체는 [db_schema.md §7](../architecture/db_schema.md#7-판-올리기--dbtool).

### 5-6. 적재
```bash
.venv/bin/python -m pipeline.load.pgvector_load --set PG_SCHEMA=demo load --bundle $O/bundle   # 다시 넣을 때 --replace
```
적재는 이번 묶음에 없는 문서를 지우지 않는다.

### 5-7. 검색(MCP 없이)
```bash
.venv/bin/python -m mcp_server.cli.search_ask --set PG_SCHEMA=demo ask --source CRMS --k 3 --q "<질문>"   # 원천 하나 필수
```

## 6. 검색 MCP 서버
```bash
nohup .venv/bin/python -m mcp_server.main --set PG_SCHEMA=demo > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
curl -s http://127.0.0.1:18769/health                  # 기대: {"ok":true,"ready":true,…}
.venv/bin/python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:18769/mcp --source CRMS --q "<질문>"   # 도구 목록·search 근거 칸
.venv/bin/python -m validation.e2e.answer_gen --url http://127.0.0.1:18769/mcp --q "<질문>"               # (선택) 답변 생성 — LLM 설정·예산 필요
kill $(cat $O/mcp.pid)                                 # PID로만 끈다(pkill -f 금지)
```
포트는 settings.yaml `search.server.mcp_port`(2의 예 18769), 엔드포인트 `/mcp`(streamable HTTP). 루프백(`127.0.0.1`)이면 토큰 없이 붙는다 — 다른 주소로 열면 `required.tokens.mcp_token`이 필요하고 `0.0.0.0`은 거부된다. 도구 입출력은 [mcp-guide.md](mcp-guide.md). 끝나면 `*_allow_external`을 `false`로 되돌린다.

## 7. 검증 페이지(브라우저)
설정은 2의 `search.server`·`dev.search_ui`·`required.pg` 그대로.
```bash
mkdir -p output/validation
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791  ·  /api/health · /api/tools · /api/chunk/<id>
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```
- 왼쪽 "검색 설정"에서 원천을 하나 고른다.
- `embed_allow_external: false`면 질의 임베딩도 막혀 키워드·ID 검색만 된다. 벡터 검색까지 보려면 `true`로 바꾸고 MCP를 다시 띄우고, 끝나면 되돌린다.
- 다른 적재 결과를 보려면 `required.pg.pg_schema`를 바꾸고 다시 띄운다.

## 8. 서버와 같은 컨테이너로 시험(compose-local)
운영 묶음과 같은 컨테이너 3개(`data-pipeline`·`mcp-server`·`mcp-data-parsing`)를 실행 이미지 + 이 저장소(코드 `/app` 읽기 전용 · 결과 `output/`)로 띄운다.
```bash
ALLOW_NO_ASSETS=1 IMAGE_TARGET=pipeline-runtime TAG=data-pipeline-runtime:<시험 태그> bash deploy/release/build_ship.sh   # 빌드 → 판정
ALLOW_NO_ASSETS=1 IMAGE_TARGET=mcp-runtime TAG=mcp-server-runtime:<시험 태그> bash deploy/release/build_ship.sh
export IMAGE_TAG=<시험 태그>
bash deploy/host/scripts/host_ctl.sh up -d             # run_env: local → compose-local.yml
bash deploy/host/scripts/host_ctl.sh ps                # 기대: data-pipeline · mcp-server · mcp-data-parsing Up
curl -s http://127.0.0.1:8051/health
bash deploy/host/scripts/pipe_exec.sh check_env        # 컨테이너 안 명령 하나(서버와 같은 입구)
bash deploy/host/scripts/host_ctl.sh down
```
빌드 기대 마지막 줄: `완료: <태그>`(그 앞 `[판정] 통과`). 서버로 옮기기는 `bash deploy/release/stage_images.sh <태그> pipeline-runtime mcp-runtime`(이미지 저장소 `output/ship/sbl_images` — push는 사람이).

코드가 든 시험 이미지(`IMAGE_TARGET=pipeline`·`mcp`, TAG를 빼면 배포용 `data-pipeline:<VERSION>`)로 이미지 배치 그대로 돌려 보기:
```bash
DATA_PIPELINE_IMAGE=data-pipeline:<시험 태그> MCP_SERVER_IMAGE=mcp-server:<시험 태그> DOC_SRC=<문서 폴더> RAG_OUT=<빈 폴더> \
  SMOKE_SETTINGS=<설정 파일> SMOKE_PG_PASSWORD=<시험용> SMOKE_SYSTEM=<원천> bash valid_env/docker/smoke_test.sh   # 값 설명은 스크립트 첫 줄
```
