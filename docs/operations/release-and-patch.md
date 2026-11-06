# 릴리스 — 실행 이미지 + 코드 폴더 바꾸기

↑ [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 처음 설치: [README §5-0 서버 설치 순서](../../README.md#서버-설치-순서) · 운영 중인 서버 올리기: [upgrade-guide.md](upgrade-guide.md)

**전제**: 모드마다 이미지를 따로 빌드한다(모드별 이미지·코드·띄우는 법은 [README §1-3 실행 모드 표](../../README.md#실행-모드)). ① PC가 개발 서버용 실행 이미지 2개(코드 없음)를 빌드·시험해 개인 이미지 저장소 `jehunlee302/sbl_images`에 올린다(README §5-2) ② 개발 서버(dev)는 그 이미지를 불러오고 코드 수정은 **새 코드를 벌 폴더에 덮어써** 붙인다(§1-1) ③ 운영 서버(prd)는 개발 서버에서 시험한 코드를 구운 이미지를 쓴다(§1-2). 의존성이 바뀔 때만 새 실행 이미지 버전을 만든다(§5).

## 1. 이미지와 코드 폴더

| 이미지 | 실행 이미지 `IMAGE_TARGET` | 코드가 든 이미지 `IMAGE_TARGET` | 안에 든 것 |
|---|---|---|---|
| `data-pipeline` | `pipeline-runtime` → `data-pipeline-runtime:<판>` | `pipeline` | 의존성 + LibreOffice + `assets/`(OCR 모델) |
| `mcp-server` | `mcp-runtime` → `mcp-server-runtime:<판>` | `mcp` | 의존성 |

- **코드 폴더** = 코드 zip(또는 코드 묶음)을 푼 폴더(저장소 트리 그대로)를 벌 폴더 이름으로 바꾼 것(예 `/home/sbl/sbl_data_parsing-main-1` — 이름 끝 `-<숫자>`가 벌 번호, README §5-0). **루트** = 코드 폴더 자체 — 호스트 스크립트는 자기 자리에서 루트를 구해 `<루트>/settings.yaml`·`<루트>/edw_chain.yaml`·`<루트>/output/`을 쓴다. 사람·systemd는 코드 폴더에서 `bash deploy/host/scripts/…`를 부른다.
- **코드 폴더만으로 못 바꾸는 것**(바꾸면 새 실행 이미지 버전 — §5): `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일. 시작할 때 코드의 `deploy/docker/DEPS_HASH`(requirements 두 파일의 지문)가 이미지 지문과 다르면 컨테이너가 멈춘다. 휠·Dockerfile·assets만 바뀐 경우는 자동으로 막지 않으니 사람이 판을 올려 새로 빌드한다.

### 1-1. 개발 서버 — 코드 폴더 덮어쓰기

1. 코드: 코드 git의 그 판 zip(README §5-0)이면 된다. 실행 이미지는 서버에 있는 판 중 `BUILD.txt`의 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판을 그대로 쓴다(README [§1-3](../../README.md#실행-모드)) — 같은 판이 없을 때만 PC에서 새 실행 이미지를 만든다(README §5-2). PC의 `BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`는 코드 폴더 묶음 `output/ship/code-<버전>-<커밋>.tar.gz`(`CODE_OUT=`로 바꿈 — git 추적 파일 + `CODE_COMMIT`)도 만든다. 묶음을 이미지 저장소에 함께 둘 때: `CODE_BUNDLE=output/ship/code-<버전>-<커밋>.tar.gz bash deploy/release/stage_images.sh <판> pipeline-runtime mcp-runtime`.
2. 서버: 옛 벌 폴더를 벌 폴더 밖에 백업하고([upgrade-guide §2](upgrade-guide.md#2-백업)) 벌 폴더에서 옛 코드만 지우고(`.git`·`settings*`·`edw_chain.yaml`·`output/`·`home/`은 남김 — [upgrade-guide §4](upgrade-guide.md#4-벌-폴더에-새-코드-덮어쓰기)) 새 코드를 그 위에 푼다 — `tar -xzf code-….tar.gz --no-same-owner -C /home/sbl/sbl_data_parsing-main-<번호>`(코드 zip이면 공용 폴더에 풀어 `cp -a sbl_data_parsing-<판>/. sbl_data_parsing-main-<번호>/`). `settings.yaml`·`edw_chain.yaml`·`output/`·`home/`은 묶음·zip에 없어 그대로 남는다(지우지 않는다 — `output/`을 잃으면 전부 다시 처리). 옛 코드를 지우지 않으면 새 판에서 지운 파일(옛 시험 등)이 남아 selftest가 실패한다.
3. 바꾸기(벌 폴더에서): `bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>`(코드 a+rX · `output/` — 컨테이너 사용자 10001이 못 읽으면 "읽을 수 없음(권한)"으로 멈춤) → `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp` → `bash deploy/host/scripts/host_ctl.sh timers`(단위 틀이 바뀌었을 수 있어 다시 씀).
4. 확인: 컨테이너 로그 첫 줄 `[image] 이미지 <이름 버전 커밋> · 코드 <커밋> · 의존성 <지문>` → `bash deploy/host/scripts/host_ctl.sh check`(마지막 줄 `[host_ctl check] 통과 — 6개`). `의존성 지문이 다름`으로 멈추면 그 코드는 새 실행 이미지가 필요하다.
5. 되돌리기: 2의 백업을 벌 폴더 위에 다시 풀고 `host_ctl.sh up -d --force-recreate …` → `host_ctl.sh timers`. 새 판이 DB 판을 올렸으면 DB도 되돌린다([upgrade-guide §11](upgrade-guide.md#11-되돌리기)). 벌이 여럿이면 모든 벌을 같은 판으로 맞춘다(같은 기준 스키마).

### 1-2. 개발 → 운영 — 시험한 그대로 굽기

운영 이미지는 PC에서 빌드하지 않는다. 개발 서버에 불러온 **실행 이미지 그 판** 위에 **시험한 코드 폴더**를 COPY만 해서 앱마다 코드가 든 이미지 하나(`data-pipeline:<VERSION>`·`mcp-server:<VERSION>`)를 다시 빌드한다(`deploy/docker/Dockerfile.bake` — 패키지 설치·네트워크 없음). 구운 이미지는 코드 폴더 없이 뜬다. 순서: 개발 서버에서 굽기·판정 → 조각을 운영 서버로 옮김 → 운영 서버에서 불러오기·띄우기.

1. 개발 서버(시험한 코드 폴더에서): `bash deploy/release/bake_prod_image.sh <실행 이미지 판>`(개발 서버가 지금 쓰는 실행 이미지 판 — settings.yaml 이미지 칸의 태그, 대상 하나만이면 뒤에 `pipeline` 또는 `mcp`). 코드 폴더는 스크립트가 든 폴더(다른 폴더면 `CODE_DIR=`), 새 태그는 코드 `VERSION`(다른 `TAG=`는 거부), 컨테이너 도구는 podman(없으면 docker — `DOCKER=`), 저장 폴더 `/var/tmp/bake`(`OUT=`).
2. 스크립트 순서: ① 코드 `DEPS_HASH` = 실행 이미지 지문인지(다르면 멈춤) ② 빌드 — 라벨 `org.opencontainers.image.revision`(코드 커밋)·`org.opencontainers.image.base.digest`(실행 이미지 ID) ③ `selftest_gate.sh` 판정(`[판정] 통과`가 아니면 멈춤) ④ 저장·45 MB 분할·sha256 → `/var/tmp/bake/sbl_images/`(`load.sh` · `<태그>/BUILD.txt` · `<태그>/<이미지>/` + 같은 태그 폴더에 코드 묶음 `code-<태그>-<커밋>.tar.gz`·sha256). 코드 묶음에는 `.git`·`deploy/host/scripts/test_space/`·`valid_env/`·`validation/`·`settings*.yaml`(sample 빼고)·`output/`이 들어가지 않는다(코드 폴더가 git clone이면 `git archive`로 추적 파일만).
3. 옮기기: `/var/tmp/bake/sbl_images/`를 운영 서버로 옮긴다.
4. 운영 서버: `DOCKER=podman bash sbl_images/load.sh <태그>` → 코드 묶음을 벌 폴더(`/home/sbl/sbl_data_parsing-main` — 운영은 한 벌이라 번호 없이)에 풀고(호스트 스크립트만 씀) settings.yaml 이미지 칸을 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>`으로 → §1-1 2·3으로 띄우고 `host_ctl.sh check`. 셸·unit에 `CODE_DIR`을 두지 않는다(두면 compose가 코드 폴더를 덮어 붙임).
5. 어느 판인지: `podman image inspect <태그> --format '{{json .Config.Labels}}'`.

## 2. 서버에서 직접 고친 코드

서버에서는 되도록 코드를 고치지 않는다(설정이나 [이슈](server-guide.md#이슈-기록)로). 고쳤다면 그때마다 `server-changes.md`에 적는다(형식 [server-guide §7](server-guide.md#7-개발자에게-보고하는-법)).
- 새 판을 덮어쓰면 서버에서 고친 파일은 새 판 내용으로 바뀐다(옛 내용은 백업·gitea에만 남음). 덮어쓰기 전에 `server-changes.md`의 `서버에만`·`PC 보냄` 행을 읽고, 새 코드에 이미 들어 있으면 `PC 반영됨 <커밋>`, 없으면 덮어쓴 뒤 다시 얹고 `다시 얹음 <커밋>`으로 바꾼다.
- 서버에서 바꾼 옵션 값은 코드가 아니라 `settings.yaml`에 둔다 — 새 판이 기본값을 바꿔도 settings.yaml 값이 이긴다.
- 서버 수정은 PC(main)로 보내 받아들이는 것이 기본이다(`서버에만` 행 + `<ID>.diff` — 코드·숫자·오류만, 문서 본문·고객명·키 값 없음).

## 3. 배포 판정 — selftest

```bash
bash deploy/release/selftest_gate.sh $DOCKER run --rm <코드 폴더 옵션> <태그> selftest
```
- **selftest는 종료 코드로 판정하지 않는다**(FAIL이 하나라도 있으면 1). `selftest_gate.sh`가 FAIL 줄을 알려진 목록 `deploy/release/known_fail.txt`(이미지 안 `/app/docker/known_fail.txt`)와 대조해 마지막 `[판정]` 줄과 종료 코드를 낸다 — 목록 밖 FAIL 0이면 통과(0), 아니면 실패(1).
- 지금 기대값: 두 이미지 모두 `[판정] 통과 — FAIL 0`(알려진 FAIL 목록은 비어 있음).
- 실행 이미지(`*-runtime`)는 `-v "$PWD:/app/deploy:ro,z"`로 코드 폴더를 붙인다. 구운 이미지는 붙이지 않는다.
- 사례 하나만: `… selftest --only <이름 조각>`(사례 이름 = `tests/server/<common|pipeline|mcp>/test_*.py` 모듈 이름).
- 이미지 안 목록으로 판정: `$DOCKER run --rm --entrypoint bash <태그> /app/docker/selftest_gate.sh /app/docker/entrypoint.sh selftest`.

통과하면 운영 기록 `versions.md`에 한 줄: `날짜 · 서버 · 이미지 버전 · 코드 커밋 · 확인 결과`.

## 4. 버전

두 이미지는 같은 버전을 쓴다. 정본은 저장소 루트 `VERSION` 한 줄(SemVer).
- MAJOR = MCP 도구 계약·DB 스키마·핸드오프 형식이 깨질 때(1.0.0 전에는 MINOR로 올림) · MINOR = 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 · PATCH = 코드 폴더만 바꿈.
- PATCH인지 MINOR인지 가르기: `git diff v<앞 판>..HEAD -- deploy/docker/`를 본다. `requirements*.txt`가 그대로라 `DEPS_HASH`가 같고, 실행 이미지에 구워지는 파일(`Dockerfile`·`runtime_entry.sh`·`wheels/`)의 동작이 그대로면 PATCH — 서버의 실행 이미지를 그대로 쓰고 코드 폴더만 바꾼다. `entrypoint.sh`·`Dockerfile.bake`는 코드 폴더에서 읽히므로 바뀌어도 PATCH다. `DEPS_HASH`가 다르거나 실행 이미지에 구워지는 파일의 동작이 바뀌면 MINOR(새 실행 이미지 — §5).
- `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 annotated 태그 `v<버전>`을 붙인다. 이미지 태그는 `v` 없이(`data-pipeline:0.2.0`).
- `build_ship.sh`·`stage_images.sh`는 태그를 안 주면 `VERSION`을 쓴다. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`). 빌드 커밋은 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`).
- 검색 DB gold `doc`의 버전 칸(`silver_version`·`gold_version`)은 이미지 안 `/app/deploy/VERSION`(코드 폴더면 그 루트 `VERSION`)을 쓴다.

## 5. 새 이미지 버전이 필요할 때

### 5-1. 빌드 → 전송

PC 명령은 [README §5-2](../../README.md#5-2-pc에서--이미지-만들기와-이미지-저장소에-올리기)(실행 이미지 두 개 → `stage_images.sh` → 이미지 git). 그 밖:
- 빌드만(selftest 판정·resources·비밀값 흔적 점검까지, 저장 없음): `BUILD_ONLY=1 IMAGE_TARGET=<타깃> bash deploy/release/build_ship.sh` — PC 시험 빌드는 `TAG=data-pipeline:<시험 태그>`.
- 빌드 컨텍스트는 저장소 루트, Dockerfile은 `deploy/docker/Dockerfile`. 루트 `.dockerignore`가 허용 목록이다(`common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`).
- Docker 23 미만은 Dockerfile의 heredoc을 못 읽는다 — `build_ship.sh`가 버전을 보고 `--build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7`을 붙인다(인터넷 필요, `BUILDKIT_SYNTAX=`로 바꿈).
- pipeline 이미지는 `assets/rapidocr/*.onnx`가 있어야 빌드된다(§5-6). 없으면 `build_ship.sh`가 멈춘다 — `ALLOW_NO_ASSETS=1`은 PC 확인 빌드만(그 이미지는 첫 실행에 모델을 받으려다 폐쇄망에서 실패). 새 체크아웃·worktree에는 `assets/`가 없으니 메인 체크아웃에서 복사한다.

### 5-2. 서버에서

- 이미지 불러오기는 `load.sh` 하나다(개발: README §5-0 2번 · 운영: §1-2 4).
- **이미지·코드 폴더·`run_pipeline.py`는 같은 때에 바꾼다**(서로 맞아야 함). 순서: 새벽 배치·상주 컨테이너 멈춤 → 이미지 적재 → 벌 폴더에 새 코드 덮어쓰기(§1-1) → 새 이미지로 다시 띄움(`run_pipeline.py`는 덮어쓴 코드 폴더 안의 것 — §5-4).
- 이미지 이름은 settings.yaml `required.deploy.pipeline_image`·`required.deploy.mcp_image`에 적는다.
- 배포 뒤, 컨테이너 안 코드가 있는지 파일로 본다(bind 마운트 원본이 없으면 빈 폴더가 붙어 `test -d`는 통과하므로):
```bash
for c in data-pipeline mcp-data-parsing; do   # 여러 벌이면 이름 끝 -<벌 번호>(server-guide §1-3)
 $DOCKER exec $c test -f /app/deploy/pipeline/transform/parse/parse_engines.py && echo "$c OK" || echo "$c 코드 없음(빈 마운트?)"; done
```

### 5-3. 상주 컨테이너

| 서비스(`host_ctl.sh`) | 컨테이너 | compose 파일(실행 이미지면 + 코드 폴더 파일) | 하는 일 |
|---|---|---|---|
| `data-pipeline` | `data-pipeline` | `compose.pipeline.yml`(+ `compose.code.yml`) | 일 없이 떠 있음(entrypoint `idle`) — `run_pipeline.py`·`pipe_exec.sh`가 `exec` |
| `mcp-data-parsing` | `mcp-data-parsing` | `compose.data-parsing.yml`(+ `compose.code.data-parsing.yml`) | `parse_document` 작업 서비스(entrypoint `run-mcp-parsing`) |
| `mcp` | `mcp-server` | `compose.mcp-server.yml`(+ `compose.code.mcp-server.yml`) | 검색 MCP |

- 모두 `bash deploy/host/scripts/host_ctl.sh …`로 다룬다(compose 직접 호출 금지 — README §5-3 ①). 죽으면 `restart: unless-stopped`, 꺼져 있으면 keepalive 타이머(`mcp_keepalive.sh`)가 `mcp-data-parsing`·`mcp`를 다시 띄운다.
- `parse_document` 작업 서비스 토큰은 settings.yaml `required.tokens.mcp_token`(검색 MCP와 같은 칸).

### 5-4. `run_pipeline.py` 자리와 설정

- 코드 폴더에서 `python3 deploy/host/scripts/run_pipeline.py …`로 실행한다(다른 자리에 복사해 돌리면 `--code <코드 폴더>`).
- 대상은 기본으로 FileStorageMap의 모든 문서, 시작 자리 0(`--start-offset`). 이름으로 좁힐 때만 `--filter <키워드,…>`.
- 설정은 서버 settings.yaml(`--settings` · `SETTINGS_FILE` · `<루트>/settings.yaml` 순)에서 읽는다 — 호스트 python에 PyYAML 필요. 필요한 칸이 없으면 칸 경로만 찍고 종료 2.
  - 작업 폴더 `ops.run_pipeline.run_pipeline_work_dir`(비우면 스크립트 옆 `test_space/` — 진행 기록 `batch_progress/`)
  - 결과 폴더 `ops.host.host_output_dir`(컨테이너 `/app/output`의 원본 — 비우면 `<루트>/output`)
  - MCP 업로드 작업 폴더는 `<결과 폴더>/_mcp_parse/jobs`(고정)
  - 레인·동시 수 값 `ops.run_pipeline.*`(비우면 코드 기본값)
  - `required.env.run_env`가 `dev`·`prd`가 아니면 시작하지 않는다.
- **PC에서 실행하지 않는다**(운영 EDW·Object Storage에 접속).

### 5-5. DB 버전 관리 — `migrate`

pgvector의 우리 스키마(검색 `required.pg.pg_schema`와 원천 스키마 5벌 `<스키마>_{sfdc,crms,las,faq,other}`, 로그 `applog`, 마스터 `<스키마>_master`)의 표·색인·뷰는 Alembic 리비전으로만 만든다(`common/store/db/migrations/versions/`). 버전 기록은 스키마마다 `<스키마>.alembic_version`. 명령은 상주 `data-pipeline` 안에서 돈다(먼저 `host_ctl.sh up -d data-pipeline`).

```bash
# 코드 폴더에서
# ⓪ (DB마다 처음 한 번 — DB 관리자) vector 확장 — 없으면 "vector 확장 없음"으로 멈춤
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
bash deploy/host/scripts/pipe_exec.sh migrate current                    # 지금 판과 코드의 끝 판
bash deploy/host/scripts/pipe_exec.sh migrate check --target all         # 읽기만 — 갈래마다 판 상태(끝 판이 아니면 종료 1)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 끝 판까지. 표가 없는 새 스키마는 --dim 필수(임베딩 모델 출력 크기 — 모델 담당자 확인)
bash deploy/host/scripts/pipe_exec.sh migrate master load                # 마스터 표를 glossary.csv로 통째로 바꿈(기본 resources/vocab/glossary, 서버 폴더면 --dir <컨테이너 안 경로>)
bash deploy/host/scripts/pipe_exec.sh migrate check --target all         # 기대: 갈래마다 "판 끝", 종료 코드 0
bash deploy/host/scripts/pipe_exec.sh show-stack                         # 엔진 구성 파일(이름·sha·경로) — 못 읽으면 종료 2
```
- `--target`: `search`·`applog`·`master`·`all`(셋 모두). 끝 판: search `0007_search` · applog `0004_applog` · master `0002_master`. `up --sql <파일>`(+ 있는 DB는 `--from <지금 판>`)은 DB에 붙지 않고 실행할 SQL만 파일로 — DB 담당 검토용([upgrade-guide §6](upgrade-guide.md#6-db-판-올리기--migrate-up)).
- 표는 있는데 버전 기록이 없는 스키마(판 관리 전에 만든 것)에는 `up`이 종료 2로 멈춘다 — 새 `db_schema`로 올리고 전체를 다시 적재한다.
- ⚠ **0.1.0이 만든 스키마에 `up`하면 `0002_search`가 옛 표를 지운다** — 새 `required.pg.pg_schema`로 올린다([upgrade-guide §0](upgrade-guide.md#0-먼저-알-것)).
- 적재(`pgvector_load`)는 새 스키마면 만들고 기록, 기록이 있으면 `up`, 기록 없는 기존 스키마면 경고만 하고 계속한다. DB 판이 코드보다 낮으면 종료 2(`migrate up` 안내), 코드가 모르는 리비전이 있으면(옛 이미지로 되돌린 뒤 등) 적재·`up` 모두 종료 2. 검색 MCP는 버전을 보지 않는다.
- 판을 바꾸는 리비전(표·컬럼)은 데이터 계약 변경이다 — DB 담당 협의가 먼저.
- applog 월 파티션 준비·보존 기한 지난 파티션 삭제(`bash deploy/host/scripts/pipe_exec.sh migrate maintain --target applog`)는 새벽 배치(`nightly_batch.sh scheduled`)가 run_pipeline 앞에 매일 부른다(실패하면 경고만). 새벽 배치를 켜지 않은 서버는 이 명령을 따로 예약한다.
- 엔진 구성 바꾸기: 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 코드 폴더째 바꾼다(§1-1). 이미지에 없는 엔진이 있으면 파이프라인 진입점이 종료 2. 검색 MCP는 시작 때 읽으므로 바꾼 뒤 `mcp_keepalive.sh`로 다시 띄운다.
- PC: `python -m common.store.db.dbtool <up|current|check|master load> --target … [--schema S] [--dim N | --bundle B] [--create-extension]`(README §4-4).

### 5-6. 반입 자산(`assets/`) 준비 — 이미지 빌드 전

폐쇄망 서버는 첫 실행 때 모델을 받을 수 없으므로 pipeline 이미지를 빌드하기 전에 저장소 루트 `assets/`를 채운다. **이미지가 쓰는 자산은 `assets/rapidocr/*.onnx`(pipeline 이미지 — Dockerfile이 rapidocr 패키지의 `models/`로 복사)와 `assets/opencode/opencode`(네 이미지 — 개발 작업 공간의 opencode, linux-x64-baseline 실행 파일 하나)다.** `assets/`는 git에 넣지 않는다. 둘 중 없는 것이 있으면 `build_ship.sh`가 멈춘다(`ALLOW_NO_ASSETS=1`이면 빼고 빌드).

```bash
# 1) (인터넷 되는 PC, rapidocr==3.9.2 설치) 한국어 PP-OCRv5 인식 모델을 한 번 받는다
python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Rec.lang_type': LangRec.KOREAN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})"
# 2) 채우기 — 설치된 rapidocr 패키지의 models/에서 복사(중국어 인식 PP-OCRv6_rec_small.onnx는 뺌). 원본 자리가 다르면 ASSET_SRC=<폴더>
PYTHONPATH=. python deploy/release/assets.py pack      # → assets/ + assets/MANIFEST.json(해시·크기, 90 MB 넘으면 .partNN 조각)
# 3) 확인
PYTHONPATH=. python deploy/release/assets.py check
# opencode: <ASSET_SRC>/dl/opencode에 실행 파일을 두면 pack이 assets/opencode/opencode로 복사(조각으로 나누지 않음 — 없으면 "없음(건너뜀)")
ls assets/rapidocr/*.onnx assets/opencode/opencode    # build_ship.sh가 보는 것
```

## 6. 보관 기준 — 디스크

| 대상 | 남길 것 | 명령 |
|---|---|---|
| 이미지(`data-pipeline`·`mcp-server`, 실행 이미지 포함) | 지금 버전 + 직전 버전(컨테이너가 쓰는 태그는 늘 남김) | `bash deploy/host/scripts/prune_images.sh --apply`(기본 dry-run, `--keep N`) — `docker system prune`은 쓰지 않음(남의 이미지 보호) |
| 벌 폴더 백업(덮어쓰기 전에 사람이 만든 것) | 지금 판 + 바로 앞 판 | 새 판 확인 뒤 오래된 백업을 손으로 지움(`settings.yaml`·`pg_dump`에 비밀값·DB 내용 — 지우기 전에 확인) |

## 7. 릴리스 체크리스트

1. 서버에서 온 `server-changes.md`의 `PC 보냄` 행을 먼저 검토·병합(§2).
2. 테스트 통과(CLAUDE.md §5-2·§6) → `release/<버전>` → main 병합·태그(§4).
3. 코드만 바뀜 → §1-1 → §1-2. 의존성이 바뀜 → §5.
4. 서버: [upgrade-guide.md](upgrade-guide.md) 순서 — 백업 → `server-changes.md` 대조(§2) → 새 이미지·새 코드 덮어쓰기 → DB 판(§5-5 — 적재·selftest 앞에) → `host_ctl.sh check` → `versions.md`에 한 줄(§3).
5. 문제는 [server-guide §7](server-guide.md#7-개발자에게-보고하는-법) 형식으로 이슈 → PC가 고침 → 다음 판.

## 8. EDW 조인 사슬 파일 고쳐 쓰기(서버)

적재가 문서 메타(고객 `client_edw`·등록 시각 `created_at`·원천 메타 `doc.attrs`)를 EDW에서 채울 때 따라가는 표·칸 이름과, 검색 MCP가 쓰는 `attrs` 키의 거르기 이름·근거 표시는 파일 하나에 있다. 기본 파일은 코드 폴더의 `resources/config/edw_chain.yaml`이고 **꼴과 칸의 뜻은 그 파일의 머리 주석이 정본**이다. 서버 EDW 이름이 다르거나 메타 키를 더하려면 코드를 고치지 않고 사본을 고친다.

**① 사본 고치기 · 칸 적기** — 사본은 `<루트>/edw_chain.yaml`(`host_ctl.sh init`이 없을 때만 복사 — 10001, 640)이고, `data-pipeline`·`mcp-server`에 `/etc/rag/edw_chain.yaml`로 읽기 전용 붙는다. 설정 칸은 하나(`ops.paths.edw_chain_file` — 적재와 검색이 같은 칸)이고 **칸을 적었을 때만 사본이 쓰인다**(비우면 코드의 기본 파일).
```bash
vi <루트>/edw_chain.yaml                                             # 주인·권한은 그대로 10001, 640
# settings.yaml(편집기로):  ops: { paths: { edw_chain_file: /etc/rag/edw_chain.yaml } }
# 검색 MCP는 파일이 바뀌면 다음 호출부터 다시 읽음 · 적재는 다음 실행부터
```

**② 자주 하는 고침**
```yaml
# (가) EDW 표·칸 이름이 다를 때 — 단계의 table·on, fields의 from만 바꾼다(키 이름·filter는 그대로 → 검색 호출도 그대로)
sfdc:
  steps:
    ...
    - name: opportunity
      table: SFDC.Opportunity_v2
      on: {Id: [link.LinkedEntityId, task.WhatId, event.WhatId]}
      when: {prefix: "006"}
  fields:
    sf_op_name: {from: opportunity.OpportunityName, filter: sf_op_name, evidence: true}

# (나) Quote 표가 EDW에 생겼을 때 — 기본 파일의 주석 줄을 켜고 opportunity 열쇠 목록 끝에 quote.OpportunityId를 더한다
    - {name: quote, table: SFDC.Quote, on: {Id: link.LinkedEntityId}, when: {prefix: "0Q0"}, optional: true}
    - name: opportunity
      on: {Id: [link.LinkedEntityId, task.WhatId, event.WhatId, quote.OpportunityId]}

# (다) 우선순위 바꾸기 — 열쇠 목록 순서가 곧 우선순위(예: 일정을 할 일보다 먼저)
      on: {Id: [link.LinkedEntityId, event.WhatId, task.WhatId]}

# (라) 메타 키 더하기 — 이미 읽는 단계의 칸이면 fields에 한 줄(새 표면 steps에 단계도). 이미 적재한 문서는 --replace로 다시 적재해야 값이 찬다(upgrade-guide §8)
crms:
  fields:
    pm_name: {from: project.PM_NAME, filter: pm_name, evidence: true}   # search(attrs={"pm_name": "…"}) · 근거 attrs.pm_name
```
- 새 `filter` 이름은 `search`의 이름 있는 인자가 아니라 `attrs` 거르기로 쓴다(이름 있는 인자는 계약에 고정).
- **이름을 바꾸면 안 되는 키:** SFDC `sf_op_id`(`list_doc_fulltext`가 키 이름 그대로 읽음 — EDW 칸 `from`만 바꾼다), 분류 힌트 키(`title`·`entity_*`·`sent_received__c`·`subject`·`stagename`·`real_rfp__c`·`rfp_received_*`·LAS `approvalname` — 분류가 이름으로 읽음). `doc_class`는 분류가 쓰는 키라 사슬에 쓰지 않는다.

**③ 실제 실행 전에 점검** — 파일만 읽고 검사한다(EDW·PG에 붙지 않음). 컨테이너 이름 변수 `$PIPELINE_CNAME`·`$MCP_CNAME`·`$DATA_PARSING_CNAME`(settings.yaml 밑 이름 `ops.containers.*_container_name` + 벌 번호)은 벌 폴더에서 `. deploy/host/scripts/load_settings.sh && load_settings`가 낸다(DOCKER도 — 아래 명령은 그 셸에서).
```bash
$DOCKER exec $PIPELINE_CNAME python -m pipeline.load.edw_doc_meta --check                                   # 설정 칸이 가리키는 파일
$DOCKER exec $PIPELINE_CNAME python -m pipeline.load.edw_doc_meta --check --file /etc/rag/edw_chain.yaml   # 칸을 적기 전에 사본만
# 기대(기본 파일): [edw_meta] 사슬 설정 OK(…) — sfdc 단계 11·키 15(거르기 5) · crms 단계 4·키 4(거르기 2) · las 단계 4·키 3(거르기 2) · faq 단계 1·키 0(거르기 0) · other 단계 1·키 0(거르기 0)   (종료 코드 0)
# 틀리면: [edw_meta] 사슬 설정 오류(…): <원천>.<자리>: … — 틀린 곳을 모두 적음   (종료 코드 1)
```
칸 이름이 EDW에 실제로 있는지는 이 점검이 보지 않는다 — `edw_meta`·`query_edw`나 DB 담당으로 확인한다. 검색 쪽은 `edw_meta`를 인자 없이 불러 `search_attrs`에 고친 키가 보이는지 본다.

**④ 오류가 나면 · 되돌리기**
- 적재 시작 때 `[edw_meta] 사슬 설정 파일을 못 읽음(…)`·`사슬 설정 오류(…)`·`사슬 설정 YAML 오류(…)`로 멈춘다(기본 파일로 돌아가지 않음). 검색은 같은 글을 `search`의 `{"error"}`로 돌려준다. ③으로 고친 뒤 다시 돌린다.
- 칸 이름이 EDW에 없으면 적재는 계속되고 그 칸 메타만 비며(표를 못 읽으면 그 원천 메타 전체 — `optional` 단계면 그 단계만) 경고와 실행 기록 `meta_missing`이 남는다 — 고친 뒤 그 문서를 `--replace`로 다시 적재한다([upgrade-guide §8](upgrade-guide.md#8-다시-처리할-층과-명령)).
- 되돌리기: settings.yaml의 `ops.paths.edw_chain_file`을 **비우면** 기본 파일로 돌아간다. 사본 파일은 지우지 않는다(마운트 원본 — 없으면 `data-pipeline`·`mcp-server`가 안 뜸).

## 9. 서버에서 직접 만드는 파일

서버마다 값이 다른 파일은 **루트(코드 폴더) 바로 아래**에 둔다 — git·코드 zip에 없는 파일이라 새 판을 덮어써도 남는다. `host_ctl.sh init`이 **없을 때만** git의 예시를 복사한다(있으면 덮지 않음).

| 파일 | 자리(호스트 → 컨테이너) | 예시(복사 원본) | 읽는 곳 | 주인·권한 |
|---|---|---|---|---|
| `settings.yaml` | `<루트>/settings.yaml` → `/etc/rag/settings.yaml`(읽기 전용 — 세 컨테이너) | `settings.sample.yaml` | 모든 앱·호스트 스크립트 | 10001:<운영 그룹> 640(운영 계정 UID가 10001이면 600) |
| `edw_chain.yaml` | `<루트>/edw_chain.yaml` → `/etc/rag/edw_chain.yaml`(읽기 전용 — `data-pipeline`·`mcp-server`) | `resources/config/edw_chain.yaml` | 적재·검색 MCP — `ops.paths.edw_chain_file: /etc/rag/edw_chain.yaml`을 적었을 때만 | 10001:<운영 그룹> 640 |

- 백업 묶음(벌 폴더 밖, 700): 벌 폴더 사본·`pg_dump` — [upgrade-guide §2](upgrade-guide.md#2-백업).
- 고객 명부·용어집은 서버 파일이 아니라 PG 마스터 표다(`migrate master load` — §5-5).
