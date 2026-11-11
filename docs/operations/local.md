# PC(local) 실행 순서

저장소 루트에서 차례로 친다. `<…>`는 바꿔 넣을 자리. 설정 칸 뜻은 [settings.md](settings.md).

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
꼭 채울 칸: `required.env.run_env: local` · `required.pg`(아래 3의 값) · `required.models`(임베딩·LLM·VLM 주소·모델·키). 예시는 [README §4-2](../../README.md#4-2-settingsyaml-작성).

## 3. PC 시험 DB(pgvector)
```bash
docker ps -a --filter name=^pgvector$ --format '{{.Status}}'      # 빈 줄 = 없음 · Exited = 멈춤 · Up = 돌고 있음
docker run -d --name pgvector --restart no --memory 1g --cpus 2 -p 127.0.0.1:55433:5432 \
  -v sbl_mcp_pgdata:/var/lib/postgresql/data -e POSTGRES_DB=rag -e POSTGRES_USER=pgvector \
  -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16          # 없을 때만
docker start pgvector                                              # 멈췄을 때
until docker exec pgvector pg_isready -h 127.0.0.1 -U pgvector -d rag; do sleep 1; done
```
settings.yaml: `pg_host: 127.0.0.1` · `pg_port: 55433` · `pg_database: rag` · `pg_user: pgvector` · `pg_password: <비밀번호>` · `required.deploy.pg_container_name: pgvector`.

## 4. 점검
```bash
export PYTHONPATH=$PWD                                 # 작업 폴더(worktree)면 export RUN_ENV=local도
.venv/bin/python -m pipeline.config                    # 읽은 settings.yaml과 요약(비밀은 가림)
.venv/bin/python -m common.check.check_modules         # 기대: 모듈 경계 통과
.venv/bin/python -m common.config.keyscan --check      # 기대: 빠진 키 0개
bash deploy/release/lint_changed.sh                    # 기대: [점검] 통과
.venv/bin/python -m pipeline.cli selftest              # 기대: [판정] 통과
.venv/bin/python -m pytest -q tests/                    # 기대: 실패 0
```

## 5. 문서 몇 건 돌리기(파싱 → 구조화 → DB 표 → 적재 → 검색)
임베딩을 부르므로 settings.yaml `dev.models.embed.embed_allow_external: true`로 바꾼다(끝나면 `false`).

### 5-1. 문서 고르기
```bash
O=output/demo; SRC=$O/src
for s in SFDC CRMS; do mkdir -p $SRC/$s; for d in $(ls -d valid_env/object_storage/$s/*/ | head -2); do cp -r "$d" $SRC/$s/; done; done
cp valid_env/edw/edw.sqlite $O/edw.sqlite             # 가짜 EDW 사본
```

### 5-2. 적재 안 된 문서 표(처음 한 번)
```bash
.venv/bin/python -m common.store.db.dbtool up --target applog
```

### 5-3. 파싱
```bash
.venv/bin/python -m pipeline.cli --set PIPE_OUT_ROOT=$O --set RDB_SQLITE=$O/edw.sqlite parse --source $SRC --src $O/prepared
```

### 5-4. 마스터 표 → 구조화·임베딩
```bash
.venv/bin/python -m common.store.db.dbtool up --target master --schema demo
.venv/bin/python -m common.store.db.dbtool master load --schema demo
.venv/bin/python -m pipeline.transform.structure.gold_bundle --set PIPE_OUT_ROOT=$O \
  --parse-dir $O/parse --src $O/prepared --embed api --out $O/bundle
```

### 5-5. DB 표 만들기(스키마마다 처음 한 번)
```bash
.venv/bin/python -m common.store.db.dbtool up --target all --schema demo --bundle $O/bundle --create-extension
.venv/bin/python -m common.store.db.dbtool check --target all     # 기대: 종료 코드 0
```

### 5-6. 적재
```bash
.venv/bin/python -m pipeline.load.pgvector_load --set PG_SCHEMA=demo load --bundle $O/bundle   # 다시 넣을 때 --replace
```

### 5-7. 검색(MCP 없이)
```bash
.venv/bin/python -m mcp_server.cli.search_ask --set PG_SCHEMA=demo ask --source CRMS --k 3 --q "<질문>"
```

## 6. 검색 MCP 서버
```bash
nohup .venv/bin/python -m mcp_server.main --set PG_SCHEMA=demo > $O/mcp.log 2>&1 & echo $! > $O/mcp.pid
curl -s http://127.0.0.1:18769/health                  # 기대: {"ok":true,"ready":true,…}
.venv/bin/python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:18769/mcp --source CRMS --q "<질문>"
kill $(cat $O/mcp.pid)                                 # PID로만 끈다
```
포트는 settings.yaml `search.server.mcp_port`(README 예시 18769). 도구 입출력은 [mcp-guide.md](mcp-guide.md).

## 7. 검증 페이지(브라우저)
```bash
mkdir -p output/validation
nohup bash validation/search_ui/start_mcp.sh > output/validation/mcp.log 2>&1 & echo $! > output/validation/mcp.pid
nohup bash validation/search_ui/start_ui.sh  > output/validation/ui.log  2>&1 & echo $! > output/validation/ui.pid
# 브라우저: http://127.0.0.1:8791
kill $(cat output/validation/mcp.pid) $(cat output/validation/ui.pid)
```

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
