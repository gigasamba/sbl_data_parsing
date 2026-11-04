# 릴리스 — 실행 이미지 + 코드 폴더 바꾸기

↑ [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 처음 설치: [README §5-0 서버 설치 순서](../../README.md#서버-설치-순서)

**전제**: 개발 서버(dev)에는 코드 없는 실행 이미지 2개를 넣고, 코드 수정은 **새 루트에 새 코드 폴더를 풀어** 전달한다(§1-1). 운영 서버(prd)는 개발 서버에서 시험한 코드를 구운 이미지를 쓴다(§1-2). 의존성이 바뀔 때만 새 실행 이미지 버전을 만든다(§5).

## 1. 이미지와 코드 폴더

| 이미지 | 실행 이미지 `IMAGE_TARGET` | 코드가 든 이미지 `IMAGE_TARGET` | 안에 든 것 |
|---|---|---|---|
| `data-pipeline` | `pipeline-runtime` → `data-pipeline-runtime:<판>` | `pipeline` | 의존성 + LibreOffice + `assets/`(OCR 모델) |
| `mcp-server` | `mcp-runtime` → `mcp-server-runtime:<판>` | `mcp` | 의존성 |

- **루트** = 서버 아무 자리의 폴더 하나(예 `/home/dev/`) — 판마다 새로 만든다. **코드 폴더** = 그 안에 코드 zip(또는 코드 묶음)을 푼 폴더(`sbl_data_parsing-<판>`, 저장소 트리 그대로). 호스트 스크립트는 자기 자리에서 루트(코드 폴더의 부모)를 구해 `<루트>/settings.yaml`·`<루트>/edw_chain.yaml`·`<루트>/output/`을 쓴다. 사람·systemd는 코드 폴더에서 `bash deploy/host/scripts/…`를 부른다.
- **코드 폴더만으로 못 바꾸는 것**(바꾸면 새 실행 이미지 버전 — §5): `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일. 시작할 때 코드의 `deploy/docker/DEPS_HASH`(requirements 두 파일의 지문)가 이미지 지문과 다르면 컨테이너가 멈춘다. 휠·Dockerfile·assets만 바뀐 경우는 자동으로 막지 않으니 사람이 판을 올려 새로 빌드한다.

### 1-1. 개발 서버 — 새 루트로 코드 바꾸기

1. PC: `IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`(mcp는 `mcp-runtime`). 이미지 관문은 이 커밋의 코드 트리를 붙여 돌고, 코드 폴더 묶음 `output/ship/code-<버전>-<커밋>.tar.gz`(`CODE_OUT=`로 바꿈 — git 추적 파일 + `CODE_COMMIT`)을 만든다. 코드만 바뀐 판은 묶음만 보낸다. 이미지 저장소로 보낼 때: `CODE_BUNDLE=output/ship/code-<버전>-<커밋>.tar.gz bash deploy/release/ship_stage.sh <판> pipeline-runtime mcp-runtime`. (코드 git zip을 그대로 받아도 된다 — README §5-0.)
2. 서버: 새 루트를 만들고 코드 폴더로 풀기 — `mkdir -p <새 루트>/sbl_data_parsing-<버전> && tar -xzf code-….tar.gz --no-same-owner -C <새 루트>/sbl_data_parsing-<버전>`. 앞 루트의 `settings.yaml`·`edw_chain.yaml`을 `cp -p`로 새 루트에 복사한다.
3. 바꾸기(새 코드 폴더에서): `bash deploy/host/scripts/dc.sh init --group <운영 그룹>`(코드 폴더 a+rX · `output/` — 컨테이너 사용자 10001이 못 읽으면 "읽을 수 없음(권한)"으로 멈춤) → `bash deploy/host/scripts/dc.sh up -d --force-recreate data-pipeline data-pipeline-mcp mcp` → `bash deploy/host/scripts/dc.sh timers`(타이머를 새 루트로).
4. 확인: 컨테이너 로그 첫 줄 `[image] 이미지 <이름 버전 커밋> · 코드 <커밋> · 의존성 <지문>` → `bash deploy/host/scripts/dc.sh check`(마지막 줄 `[dc check] 통과 — 6개`). `의존성 지문이 다름`으로 멈추면 그 코드는 새 실행 이미지가 필요하다.
5. 되돌리기: 앞 루트를 지우지 않고 두었다가 그 코드 폴더에서 `dc.sh up -d --force-recreate …` → `dc.sh timers`. 루트는 최근 2개 이상 남긴다. 검색 DB는 두 루트가 같은 PG를 본다.

### 1-2. 개발 → 운영 — 시험한 그대로 굽기

운영 이미지는 PC에서 빌드하지 않는다. 개발 서버의 **실행 이미지 그 판** 위에 **시험한 코드 폴더**를 COPY만 해서 코드가 든 이미지를 만든다(`deploy/docker/Dockerfile.bake` — 패키지 설치·네트워크 없음). 구운 이미지는 코드 폴더 없이 뜬다.

1. 개발 서버(시험한 코드 폴더에서): `bash deploy/release/bake.sh <실행 이미지 판>`(예 `0.1.0`, 대상 하나만이면 뒤에 `pipeline` 또는 `mcp`). 코드 폴더는 스크립트가 든 폴더(다른 폴더면 `CODE_DIR=`), 새 태그는 코드 `VERSION`(다른 `TAG=`는 거부), 컨테이너 도구는 podman(없으면 docker — `DOCKER=`), 저장 폴더 `/var/tmp/bake`(`OUT=`).
2. 스크립트 순서: ① 코드 `DEPS_HASH` = 실행 이미지 지문인지(다르면 멈춤) ② 빌드 — 라벨 `org.opencontainers.image.revision`(코드 커밋)·`org.opencontainers.image.base.digest`(실행 이미지 ID) ③ `selftest_gate.sh` 판정(`[판정] 통과`가 아니면 멈춤) ④ 저장·45 MB 분할·sha256 → `/var/tmp/bake/sbl_images/`(`load.sh` · `<태그>/BUILD.txt` · `<태그>/<이미지>/` + 같은 태그 폴더에 코드 묶음 `code-<태그>-<커밋>.tar.gz`·sha256).
3. 운영 서버: 새 루트에 `sbl_images/`를 옮겨 `DOCKER=podman bash sbl_images/load.sh <태그>` → 코드 묶음을 `<새 루트>/sbl_data_parsing-<버전>`에 풀고 §1-1 2·3(호스트 스크립트만 씀). 셸·unit에 `CODE_DIR`을 두지 않는다(두면 compose가 코드 폴더를 덮어 붙임).
4. 어느 판인지: `podman image inspect <태그> --format '{{json .Config.Labels}}'`.

## 2. 서버에서 직접 고친 코드

서버에서는 되도록 코드를 고치지 않는다(설정이나 [이슈](server-guide.md#이슈-기록)로). 고쳤다면 그때마다 `server-changes.md`에 적는다(형식 [server-guide §7](server-guide.md#7-개발자에게-보고하는-법)).
- 새 판 폴더는 옛 판을 덮지 않으므로 서버 수정은 새 판에 **없다**. 링크를 옮기기 전에 `server-changes.md`의 `서버에만`·`PC 보냄` 행을 읽고, 새 코드에 이미 들어 있으면 `PC 반영됨 <커밋>`, 없으면 새 판 폴더에 다시 얹고 `다시 얹음 <커밋>`으로 바꾼다.
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
- `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 annotated 태그 `v<버전>`을 붙인다. 이미지 태그는 `v` 없이(`data-pipeline:0.2.0`).
- `build_ship.sh`·`ship_stage.sh`는 태그를 안 주면 `VERSION`을 쓴다. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`). 빌드 커밋은 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`).
- 회사 DB `AI.ParsingMeta`의 버전 칸(silver를 만든 판·`gold_version`)은 이미지 안 `/app/deploy/VERSION`(코드 폴더면 그 루트 `VERSION`)을 쓴다.

## 5. 새 이미지 버전이 필요할 때

### 5-1. 빌드 → 전송

PC 명령은 [README §5-2](../../README.md#5-2-pc에서--이미지-만들기와-이미지-저장소에-올리기)(실행 이미지 두 개 → `ship_stage.sh` → 이미지 git). 그 밖:
- 빌드만(selftest 판정·resources·비밀값 흔적 점검까지, 저장 없음): `BUILD_ONLY=1 IMAGE_TARGET=<타깃> bash deploy/release/build_ship.sh` — PC 시험 빌드는 `TAG=data-pipeline:<시험 태그>`.
- 빌드 컨텍스트는 저장소 루트, Dockerfile은 `deploy/docker/Dockerfile`. 루트 `.dockerignore`가 허용 목록이다(`common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`).
- Docker 23 미만은 Dockerfile의 heredoc을 못 읽는다 — `build_ship.sh`가 버전을 보고 `--build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7`을 붙인다(인터넷 필요, `BUILDKIT_SYNTAX=`로 바꿈).
- pipeline 이미지는 `assets/rapidocr/*.onnx`가 있어야 빌드된다(§5-6). 없으면 `build_ship.sh`가 멈춘다 — `ALLOW_NO_ASSETS=1`은 PC 확인 빌드만(그 이미지는 첫 실행에 모델을 받으려다 폐쇄망에서 실패). 새 체크아웃·worktree에는 `assets/`가 없으니 메인 체크아웃에서 복사한다.

### 5-2. 서버에서

- 이미지 불러오기는 `load.sh` 하나다(개발: README §5-0 2번 · 운영: §1-2 3).
- **이미지·코드 폴더·`run_docs.py`는 같은 때에 바꾼다**(서로 맞아야 함). 순서: 새벽 배치·상주 컨테이너 멈춤 → 이미지 적재 → 새 루트에 새 코드 폴더(§1-1) → 새 이미지로 다시 띄움(`run_docs.py`는 새 코드 폴더 안의 것 — §5-4).
- 이미지 이름은 settings.yaml `required.deploy.pipeline_image`·`required.deploy.mcp_image`에 적는다.
- 배포 뒤, 컨테이너 안 코드가 있는지 파일로 본다(bind 마운트 원본이 없으면 빈 폴더가 붙어 `test -d`는 통과하므로):
```bash
for c in data-pipeline data-pipeline-mcp; do $DOCKER exec $c test -f /app/deploy/pipeline/extract/run_engines.py && echo "$c OK" || echo "$c 코드 없음(빈 마운트?)"; done
```

### 5-3. 상주 컨테이너

| 서비스(`dc.sh`) | 컨테이너 | compose 파일(실행 이미지면 + 코드 폴더 파일) | 하는 일 |
|---|---|---|---|
| `data-pipeline` | `data-pipeline` | `compose.pipeline.yml`(+ `compose.code.yml`) | 일 없이 떠 있음(entrypoint `idle`) — `run_docs.py`·`trigger.sh`·`run_tool.sh`가 `exec` |
| `data-pipeline-mcp` | `data-pipeline-mcp` | `compose.pipeline-mcp.yml`(+ `compose.code.pipeline-mcp.yml`) | `parse_document` 작업 서비스(entrypoint `parse-service`) |
| `mcp` | `mcp-server` | `compose.mcp-server.yml`(+ `compose.code.mcp-server.yml`) | 검색 MCP |

- 모두 `bash deploy/host/scripts/dc.sh …`로 다룬다(compose 직접 호출 금지 — README §5-3 ①). 죽으면 `restart: unless-stopped`, 꺼져 있으면 keepalive 타이머(`mcp_up.sh`)가 `data-pipeline-mcp`·`mcp`를 다시 띄운다.
- `parse_document` 작업 서비스 토큰은 settings.yaml `required.tokens.parse_mcp`.

### 5-4. `run_docs.py` 자리와 설정

- 코드 폴더에서 `python3 deploy/host/scripts/run_docs.py …`로 실행한다(다른 자리에 복사해 돌리면 `--code <코드 폴더>`).
- 설정은 서버 settings.yaml(`--settings` · `SETTINGS_FILE` · `<루트>/settings.yaml` 순)에서 읽는다 — 호스트 python에 PyYAML 필요. 필요한 칸이 없으면 칸 경로만 찍고 종료 2.
  - 작업 폴더 `ops.pipeline_host.run_docs_dir`(비우면 스크립트 옆 `test_space/` — 진행 기록 `batch_progress/`)
  - 결과 폴더 `required.deploy.output_root`(컨테이너 `/app/output`의 원본 — 비우면 `<루트>/output`)
  - MCP 업로드 작업 폴더 `ops.mcp_host.jobs_dir`(기본 `<결과 폴더>/_mcp_parse/jobs`)
  - `required.env.run_env`가 `dev`·`prd`가 아니면 시작하지 않는다.
- **PC에서 실행하지 않는다**(운영 EDW·Object Storage에 접속).

### 5-5. DB 버전 관리 — `migrate`

pgvector의 우리 스키마(검색 `required.pg.db_schema`와 원천 스키마 5벌 `<스키마>_{sfdc,crms,las,faq,other}`, 로그 `applog`, 마스터 `<스키마>_master`)의 표·색인·뷰는 Alembic 리비전으로만 만든다(`common/store/db/migrations/versions/`). 버전 기록은 스키마마다 `<스키마>.alembic_version`. 명령은 상주 `data-pipeline` 안에서 돈다(먼저 `dc.sh up -d data-pipeline`).

```bash
# 코드 폴더에서
# ⓪ (DB마다 처음 한 번 — DB 관리자) vector 확장 — 없으면 "vector 확장 없음"으로 멈춤
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
bash deploy/host/scripts/run_tool.sh migrate current                    # 지금 판과 코드의 끝 판
bash deploy/host/scripts/run_tool.sh migrate check --target all         # 읽기만 — 표·컬럼·형식·NULL·기본값·키·색인·뷰 칸 비교(차이·끝 판 아님이면 종료 1). 컬럼 순서·뷰 정의 글자는 "(알림)"만
bash deploy/host/scripts/run_tool.sh migrate up --target all --dim <임베딩 차원>   # 끝 판까지. 표가 없는 새 스키마는 --dim 필수(임베딩 모델 출력 크기 — 모델 담당자 확인)
bash deploy/host/scripts/run_tool.sh migrate master load                # 마스터 표를 CSV로 통째로 바꿈(기본 resources/vocab/glossary, 서버 폴더면 --dir <컨테이너 안 경로>)
bash deploy/host/scripts/run_tool.sh migrate check --target all         # 기대: 갈래마다 "비교: 차이 없음"
bash deploy/host/scripts/run_tool.sh show-stack                         # 엔진 구성 파일(이름·sha·경로) — 못 읽으면 종료 2
```
- `--target`: `search`·`applog`·`master`·`all`(셋 모두). 끝 판: search `0005_search` · applog `0001_applog` · master `0001_master`.
- 기존 스키마인데 버전 기록이 없을 때: 차이 0이면 `migrate stamp --target search`(실행 없이 기록), 차이가 "표·색인·뷰 없음·뷰 칸 다름"뿐이면 `up`(없는 것만 만듦). 컬럼 이름·형식·NULL·기본값·키가 다르거나 남는 표·컬럼·색인이 있으면 `stamp`·`up` 모두 종료 2 — 멈추고 출력(이름만)을 DB 담당과 협의한다.
- ⚠ **0.1.0이 만든 스키마에 `up`하면 `0002_search`가 옛 표를 지운다** — 0.2.0은 새 `db_schema`로 올린다(§8-3).
- 적재(`pgvector_load`)는 새 스키마면 만들고 기록, 기록이 있으면 `up`, 기록 없는 기존 스키마면 경고만 하고 계속한다. DB 판이 코드보다 낮으면 종료 2(`migrate up` 안내), 코드가 모르는 리비전이 있으면(옛 이미지로 되돌린 뒤 등) 적재·`up`·`stamp` 모두 종료 2. 검색 MCP는 버전을 보지 않는다.
- 판을 바꾸는 리비전(표·컬럼)은 데이터 계약 변경이다 — DB 담당 협의가 먼저.
- applog를 켰으면(`ops.log.db_enabled: true`) 매일 `bash deploy/host/scripts/run_tool.sh migrate maintain --target applog`(월 파티션 준비·보존 기한 지난 파티션 삭제)를 예약한다.
- 엔진 구성 바꾸기: 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 코드 폴더째 바꾼다(§1-1). 이미지에 없는 엔진이 있으면 파이프라인 진입점이 종료 2. 검색 MCP는 시작 때 읽으므로 바꾼 뒤 `mcp_up.sh`로 다시 띄운다.
- PC: `python -m common.store.db.dbtool <up|stamp|current|check|master load> --target … [--schema S] [--dim N | --bundle B] [--create-extension]`(README §4-4).

### 5-6. 반입 자산(`assets/`) 준비 — 이미지 빌드 전

폐쇄망 서버는 첫 실행 때 모델을 받을 수 없으므로 pipeline 이미지를 빌드하기 전에 저장소 루트 `assets/`를 채운다. **이미지가 쓰는 자산은 `assets/rapidocr/*.onnx`뿐이다**(Dockerfile이 rapidocr 패키지의 `models/`로 복사). `assets/`는 git에 넣지 않는다.

```bash
# 1) (인터넷 되는 PC, rapidocr==3.9.2 설치) 한국어 PP-OCRv5 인식 모델을 한 번 받는다
python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Rec.lang_type': LangRec.KOREAN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})"
# 2) 채우기 — 설치된 rapidocr 패키지의 models/에서 복사(중국어 인식 PP-OCRv6_rec_small.onnx는 뺌). 원본 자리가 다르면 ASSET_SRC=<폴더>
PYTHONPATH=. python deploy/release/assets.py pack      # → assets/ + assets/MANIFEST.json(해시·크기, 90 MB 넘으면 .partNN 조각)
# 3) 확인
PYTHONPATH=. python deploy/release/assets.py check
ls assets/rapidocr/*.onnx                              # build_ship.sh가 보는 것
```

## 6. 보관 기준 — 디스크

| 대상 | 남길 것 | 명령 |
|---|---|---|
| 이미지(`data-pipeline`·`mcp-server`, 실행 이미지 포함) | 지금 버전 + 직전 버전 | `bash deploy/host/scripts/prune_old.sh --apply`(기본 dry-run, `--keep N`) — `docker system prune`은 쓰지 않음(남의 이미지 보호) |
| 루트 폴더(판마다 하나) | 지금 쓰는 루트 + 바로 앞 루트 | 새 판 확인 뒤 오래된 루트를 손으로 지움(`settings.yaml`·`backup/`에 비밀값·DB 내용 — 지우기 전에 확인) |

## 7. 릴리스 체크리스트

1. 서버에서 온 `server-changes.md`의 `PC 보냄` 행을 먼저 검토·병합(§2).
2. 테스트 통과(CLAUDE.md §5-2·§6) → `release/<버전>` → main 병합·태그(§4).
3. 코드만 바뀜 → §1-1 → §1-2. 의존성이 바뀜 → §5.
4. 서버: `server-changes.md` 대조(§2) → 적용 → DB 버전(§5-5 — 적재·selftest 앞에) → `dc.sh check` → `versions.md`에 한 줄(§3).
5. 문제는 [server-guide §7](server-guide.md#7-개발자에게-보고하는-법) 형식으로 이슈 → PC가 고침 → 다음 판.

## 8. 0.2.0 배포 — 사람이 할 일

**실제로 칠 명령은 8-3**, 되돌리기는 8-5. 항목별 근거·상태는 [refactor.md](../refactoring/refactor.md)의 C 표다. 값·비밀은 이 문서에 쓰지 않는다. 누가: 사용자 · 서버 운영 · DB 담당(공유 PostgreSQL) · EDW 담당(회사 DB) · devops(빌드·반입).

> ⚠️ 0.2.0은 아직 출시 전이다(`VERSION` 0.1.0, 태그 `v0.2.0` 없음). 태그가 붙기 전에는 운영 서버에서 8-3을 실행하지 않는다.

### 8-1. 꼭 알 것

- 운영 서버는 지금 0.1.0(settings.yaml 하나, 상주 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)이다. 0.2.0은 상주 컨테이너가 `data-pipeline`·`data-pipeline-mcp`·`mcp-server`다.
- 0.2.0은 **새 실행 이미지가 필요 없다** — 코드의 `deploy/docker/DEPS_HASH`가 0.1.0 실행 이미지와 같다(`f0fcc30bd067bc2f`). dev는 `*-runtime:0.1.0`에 0.2.0 코드 폴더, prd는 그것을 구운 `*:0.2.0`.
- **prd는 반드시 새 `required.pg.db_schema`**(판 0002가 기준 스키마의 옛 표를 지움 — C-74). 옛 스키마·옛 `struct` 스키마는 2주 뒤 DB 담당이 백업하고 지운다.
- 지문이 모두 바뀌므로(FINGERPRINT·레이어 code_fp·엔진 — 기준값 PRD [e2-02](../prd/test.md#e2-02)) 모든 문서가 다시 파싱·적재된다. **전체 문서 실행은 prd에서만**, dev는 settings.yaml이 가리키는 대상으로 e2e 한 번. 시간은 지난 `progress.log`의 문서당 시간 × 문서 수, 디스크는 `required.deploy.output_root`의 `parse/_rep`만큼 여유를 더 잡는다.
- 0.2.0은 **새 루트**에 놓는다(PRD [op-13](../prd/doc.md#op-13)) — 0.1.0 자리(코드 폴더·설정 폴더)는 그대로 두고 되돌리기에 쓴다. 검색 DB는 같은 PG다.
- prd 이미지에 settings.yaml을 굽는 것(PRD [op-07](../prd/doc.md#op-07))은 `bake.sh`가 아직 하지 않는다 — 지금은 dev처럼 `<루트>/settings.yaml`을 붙인다.
- 모델: dev·prd는 내부망 모델만(외부 모델 호출 거부).

### 8-2. 배포 전

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 판 전체 grill-me 검토 — 지문 전후(PRD [e2-02](../prd/test.md#e2-02))·DB 스키마(판 0002~0005·ParsingMeta DDL) | 사용자 | 등급 A |
| 2 | ParsingMeta DDL 한 번 — 칸 이름 바꾸기·`loaded_at`·판 칸 등(운영 분류 스크립트가 멈추므로 운영 담당에게 알림) | DB 담당·EDW 담당 | C-76 |
| 3 | PG — 새 `db_schema` 이름(50자 이하) · 권한(DB 수준 CREATE, 원천 스키마 5벌의 읽기·쓰기, `doc_id_seq`) | DB 담당 | C-74 |
| 4 | 서버 settings.yaml 준비 — 필수 경로·접속([README 꼭 채울 값](../../README.md#꼭-채울-값)) · EDW 읽기·쓰기 계정 · `required.tokens.fulltext` · 예전에 `-e`로 주던 값은 settings.yaml 칸으로([env-guide §5](env-guide.md#5-010--020에서-바꿀-설정)) · 새벽 배치 칸은 비워 둠 | 서버 운영 | C-70·C-73·C-75·C-76 |
| 5 | 노출됐던 운영 키 교체(아직 안 했으면) — 새 값은 settings.yaml에만 | 서버 운영 | C-10 |
| 6 | 서버 `/tmp` 정리 주기·권한 600 점검(덮기 설정 임시 파일) | 사용자·서버 운영 | C-46 |
| 7 | 폐쇄망 휠·`assets/` 채우고 빌드(§5-6 — `ALLOW_NO_ASSETS=1` 금지) | devops | — |
| 8 | `server-changes.md`를 읽고 새 코드에 들어 있는지 대조(§2) | 서버 운영·개발자 | — |
| 9 | EDW 표 설명 자료 폴더(`catalog.json`·`columns.jsonl` — 개인정보 없는 자료)를 루트 아래 결과 폴더 `<루트>/output/edw_meta/`에 복사(UID 10001이 읽게)하고 settings.yaml에 `search.edw_meta.dir: /app/output/edw_meta`. 없으면 `edw_meta` 도구만 `not_configured`(README §5-0 4) | 서버 운영 | C-91 |
| 10 | settings.yaml 칸 정리(op-05 11-04) — 지운 칸은 지우고(남아도 경고만), `search.server.fulltext_secret` 값은 `required.tokens.fulltext`로 옮긴다(옛 자리도 읽지만 안내 한 줄) | 서버 운영 | C-92 |

### 8-3. 실행 순서 — 복사해 붙이는 명령(dev 먼저, 그다음 prd)

개발 서버(dev)에서 끝까지 한 번 돌린 뒤 운영 서버(prd)에서 같은 순서로 한다. 다른 곳은 **[dev]**·**[prd]**로 적었다. 명령은 root 셸. `<…>`는 그 서버 값으로 바꾸고, 값·비밀은 화면·기록에 남기지 않는다. `# 기대:` 줄이 나오지 않으면 다음 단계로 가지 않는다.

**0. 셸 준비** — 셸 변수는 settings.yaml에서 옮겨 적는다(파일을 화면에 띄우지 않는다).
```bash
export DOCKER=podman                                       # ops.host.docker 값(비우면 podman)
OLD_SF=<0.1.0이 쓰는 settings.yaml 경로>  OLD_CODE=<0.1.0 코드 폴더>  ROOT=<새 루트 — 예 /home/dev>
PG_C=<required.deploy.pg_container 값>  PG_U=<required.pg.user 값>  PG_D=<required.pg.db 값>
OLD_SCHEMA=<지금 required.pg.db_schema 값>  NEW_SCHEMA=<새 스키마 이름 — DB 담당과 정함(C-74)>
mkdir -p "$ROOT" && TS=$(date +%Y%m%d-%H%M); BK=$ROOT/backup/0.2.0-$TS; mkdir -p "$BK" && chmod 700 "$ROOT/backup" "$BK"
```

**1. 멈추기** — 타이머를 멈추고, 도는 `run_docs.py`가 끝나길 기다린 뒤(죽이지 않는다) 옛 상주 컨테이너를 멈춘다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
systemctl is-active data-pipeline-nightly.timer mcp-server-keepalive.timer   # 기대: inactive 두 줄
pgrep -af run_docs.py                                                         # 기대: 아무것도 안 나옴(나오면 끝날 때까지 기다림)
$DOCKER stop data-pipeline-parse data-pipeline-structure mcp-server          # 기대: 이름 세 줄
```

**2. 백업** — 0.1.0 코드 폴더·설정 파일·옛 이미지는 지우지 않는다(되돌리기 — 8-5).
```bash
cp -p "$OLD_SF" "$BK/settings.yaml.0.1.0"                                    # 4단계 입력
$DOCKER images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -E 'data-pipeline|mcp-server' > "$BK/images.0.1.0"
$DOCKER exec "$PG_C" pg_dump -U "$PG_U" -d "$PG_D" -Fc -n "$OLD_SCHEMA" -n "${OLD_SCHEMA}_*" > "$BK/pg-0.1.0.dump"   # 우리 스키마만(공유 DB)
$DOCKER exec -i "$PG_C" pg_restore -l < "$BK/pg-0.1.0.dump" | head -5                 # 기대: ";" 머리 줄과 "TABLE" 목록 — 비면 덤프 실패
```
- 옛 `struct` 스키마도 백업하려면 `-n <그 스키마 이름>`을 더한다(이름은 DB 담당 확인). `pg_dump`가 암호를 물으면 DB 담당과 함께 한다.

**3. 새 판 놓기** — 새 루트에 푼다(`<코드>` = 코드 폴더 `sbl_data_parsing-0.2.0`).
- **[dev]** 0.1.0 실행 이미지 + 0.2.0 코드 zip:
```bash
cd "$ROOT" && unzip -q <코드 zip>                                         # 기대: $ROOT/<코드>/
DOCKER=$DOCKER bash sbl_images-main/load.sh 0.1.0                        # 0.1.0 실행 이미지가 이미 있으면 건너뜀 — 기대: BUILD.txt(DEPS_HASH f0fcc30bd067bc2f)
cd "$ROOT/<코드>" && bash deploy/host/scripts/dc.sh init --group <운영 그룹>   # 기대: "[dc init] 루트: $ROOT" · output·backup · settings.yaml·edw_chain.yaml "만듦"
cat CODE_COMMIT                                                          # 기대: 그 커밋
```
- **[prd]** 개발 서버에서 굽고(§1-2 — 기대: `[판정] 통과` 뒤 `/var/tmp/bake/sbl_images/`) 운영 서버의 새 루트로 옮겨:
```bash
cd "$ROOT" && DOCKER=$DOCKER bash sbl_images/load.sh 0.2.0     # 기대: 조각 sha256 확인 → load → BUILD.txt
mkdir -p "$ROOT/<코드>" && tar -xzf sbl_images/0.2.0/code-0.2.0-<커밋>.tar.gz --no-same-owner -C "$ROOT/<코드>"
cd "$ROOT/<코드>" && bash deploy/host/scripts/dc.sh init --group <운영 그룹>   # edw_chain.yaml 사본(없으면 컨테이너가 안 뜸)
unset CODE_DIR                                                # 운영은 코드 폴더를 컨테이너에 붙이지 않는다
```
- 0.1.0이 고친 EDW 사슬 사본을 쓰고 있었다면 `cp -p <0.1.0 edw_chain.yaml> "$ROOT/edw_chain.yaml"`.

**4. 설정 옮기기** — 0.1.0 settings.yaml을 0.2.0 배치로(이미지 안에서 — 호스트 python 불필요). 이미지는 **[dev]** `data-pipeline-runtime:0.1.0` · **[prd]** `data-pipeline:0.2.0`, 둘 다 코드 폴더를 붙여 돌린다(`migrate`는 pipeline·mcp 설정 모델이 다 있는 코드에서만 돈다).
```bash
$DOCKER run --rm -i --network none --entrypoint bash -v "$PWD:/app/deploy:ro,z" -e PYTHONPATH=/app/deploy <이미지> \
  -c 'umask 077 && cat > /tmp/old.yaml && cd /app/deploy && python -m common.config.migrate /tmp/old.yaml --out /tmp/new.yaml --summary >&2 && cat /tmp/new.yaml' \
  < "$BK/settings.yaml.0.1.0" > "$ROOT/settings.yaml.new"
# 기대(화면): [migrate] 옛 배치 → 새 배치: 옮긴 칸 N개 · 지운 칸 이름 줄 · [migrate] 씀: /tmp/new.yaml (권한 600)
```
그다음 `settings.yaml.new`를 편집기로 고친다(화면에 통째로 띄우지 않는다) — 고칠 칸 목록은 [env-guide §5](env-guide.md#5-010--020에서-바꿀-설정). 꼭:
- 이미지 칸 `required.deploy.pipeline_image`·`mcp_image` → **[dev]** `data-pipeline-runtime:0.1.0`·`mcp-server-runtime:0.1.0` · **[prd]** `data-pipeline:0.2.0`·`mcp-server:0.2.0`.
- `required.pg.db_schema` → `$NEW_SCHEMA`.
- 새벽 배치 `ops.nightly.time`·`max_docs`·`deadline`은 비워 둔다(8-4 3에서 켬).
- 새 필수 칸 자리: `python -m common.config.sample --where <칸 이름>`(위 이미지 안에서 같은 방법).
- 서버 EDW의 사슬 표·칸 이름이 기본값과 다를 때만 8-6.
```bash
chown 10001:<운영 그룹> "$ROOT/settings.yaml.new" && chmod 640 "$ROOT/settings.yaml.new"
mv "$ROOT/settings.yaml.new" "$ROOT/settings.yaml"                         # 3단계 init이 놓은 예시를 덮음
bash deploy/host/scripts/settings_env.sh common.host >/dev/null && echo 설정-읽힘   # 기대: 설정-읽힘("[설정] …"이면 그 안내대로 고침)
```

**5. DB** — 파이프라인 상주 컨테이너부터 띄운다(`run_tool.sh`가 그 안에서 돈다).
```bash
$DOCKER rm data-pipeline-parse data-pipeline-structure mcp-server            # 기대: 이름 세 줄(1에서 멈춘 것)
bash deploy/host/scripts/dc.sh up -d data-pipeline                           # 기대: data-pipeline Started(또는 Running)
bash deploy/host/scripts/run_tool.sh migrate check --target all              # 새 스키마는 "표 없음(새 스키마 — up으로 만듦)", 종료 코드 1이 정상
bash deploy/host/scripts/run_tool.sh migrate up --target all --dim <임베딩 차원>   # 종료 코드 0 — 기대:
#   [migrate] search <NEW_SCHEMA>: 판 ['0005_search'] (끝 0005_search)
#   [migrate] applog applog: 판 ['0001_applog'] (끝 0001_applog)
#   [migrate] master <NEW_SCHEMA>_master: 판 ['0001_master'] (끝 0001_master)
#   "올린 뒤에도 차이:"가 나오면 멈추고 DB 담당과
bash deploy/host/scripts/run_tool.sh migrate master load                     # 기대: "[migrate] master <NEW_SCHEMA>_master: CSV로 채움 · 해시 <8자>"
bash deploy/host/scripts/run_tool.sh migrate check --target all              # 종료 코드 0 — 기대: 갈래마다 "  비교: 차이 없음"
```
- vector 확장이 없다고 멈추면 §5-5 ⓪.
- 마스터 표 행 수(git 샘플 CSV 기준, 서버 폴더 `--dir`로 넣었으면 다름): `client_master` 6 · `client_roster` 10 · `contract_master` 4 · `domain_terms` 124 · `id_patterns` 9 · `units` 23 · `master_meta` 1. 확인: `$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT count(*) FROM ${NEW_SCHEMA}_master.client_roster"`.

**6. 띄우기**
```bash
bash deploy/host/scripts/dc.sh up -d data-pipeline-mcp mcp                   # 기대: 두 서비스 Started
bash deploy/host/scripts/dc.sh ps                                             # 기대: data-pipeline·data-pipeline-mcp·mcp-server 세 줄 Up
$DOCKER logs data-pipeline 2>&1 | grep -m1 '\[image\]'                        # 기대: "[image] 이미지 <이름 판 커밋> · 코드 <커밋> · 의존성 <지문>"
```

**7. 점검** — check_env → ping_models → `migrate check --target all` → 두 이미지 selftest → `mcp_up.sh`(/health)를 차례로, 처음 실패에서 그 단계 이름과 안내를 찍고 멈춘다.
```bash
bash deploy/host/scripts/dc.sh check                                          # 기대 마지막 줄: [dc check] 통과 — 6개
```
- 실패하면(`[dc check] 실패 — <단계>: <안내>`) 그 단계 출력을 읽고 고친 뒤 다시 부른다. check_env 출력은 PG 실패를 "건너뜀"으로 보일 수 있다.
- 그다음 MCP 클라이언트로 `search` 한 번(`source_system` 필수), `list_doc_fulltext` 한 번, `parse_document`에 시험 파일 하나(C-75·C-83).
- 타이머를 새 루트로: `bash deploy/host/scripts/dc.sh timers` 뒤 `systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer`(첫 실행이 끝날 때까지 — 9).

**8. [dev] 게시 확인 — 미리보기 → 실제 한 번 → Object Storage·EDW 행**(운영 Object Storage·EDW에 쓰는 첫 실행이라 dev에서 몇 건으로 먼저 본다)
```bash
bash deploy/host/scripts/trigger.sh parse --source-limit 3                   # 원본 3건만 파싱 → <결과 폴더>/parse/_rep · 기대: 종료 코드 0
bash deploy/host/scripts/trigger.sh publish --dry-run                        # 쓰기 0 — 기대: JSON 한 줄("mode": "dry-run" · bucket · prefix · rows_planned · upload_plan · sample_rows[].rep_key) + "[dry-run] 쓰기 0 …"
bash deploy/host/scripts/trigger.sh publish                                  # 실제 한 번 — 기대: JSON 한 줄("mode": "apply" · "result") · 종료 코드 0
```
- **실제 publish는 한 번만** 한다. 다시 돌리면 Object Storage에 같은 결과를 새 시각 이름으로 또 올린다(EDW는 이미 있는 행을 건너뜀).
- 미리보기의 `bucket`·`prefix`·`rep_key`가 `required.publish` 칸(`bucket`·`prefix`)과 맞지 않으면 실제 publish를 하지 않고 settings.yaml을 고친다. DRM·실패로 빠진 문서는 `<결과 폴더>/publish/excluded_<날짜>.md`에 남는다.
- EDW 행 확인(읽기 계정 — 마지막에 쓴 행):
```bash
$DOCKER exec data-pipeline python -c "from common.store import mssql as M; kw,_=M.login('read'); c=M.connect(**kw); [print(r) for r in M.rows(c, 'SELECT TOP 5 original_filename, parse_status, rep_bucket, rep_key, parse_date FROM AI.ParsingMeta ORDER BY parse_meta_id DESC')]"
# 기대: 방금 게시한 문서 수만큼 행 · parse_status ok·partial · rep_key가 미리보기의 rep_key와 같음(표 이름이 다르면 required.edw.parsing_meta_table 값)
```
- Object Storage 확인(위 행의 `rep_bucket`·`rep_key` 하나로):
```bash
$DOCKER exec data-pipeline python -c "import sys; from common.store.objectstore import client; r=client().list_objects_v2(Bucket=sys.argv[1], Prefix=sys.argv[2]); [print(o['Key'], o['Size']) for o in r.get('Contents', [])]" <rep_bucket> <rep_key>
# 기대: <파일명>_<parse_date>.md · .json · _meta.json 과 engine/ 아래 파일 — 없으면 멈추고 publish 출력의 "result"를 본다
```

**9. 첫 실행 — FAQ 교체와 전체 재처리**
- **FAQ:** 첫 `run_docs.py` 실행은 FAQ 교체 기록(`<작업 폴더>/batch_progress/faq_seen.txt`)이 없으므로 gold `faq`를 **한 번** 비운 뒤 FAQ 전체를 맨 앞에서 처리한다(pl-41). `progress.log` 기대 줄: `FAQ 교체: 새 FAQ <N>건 — gold faq 문서 <M>건을 지우고 지금 FAQ <K>건 전체를 맨 앞에서 다시 처리`(새 스키마라 M=0). `--seqs`·`--limit` 실행은 교체를 건너뛴다.
- **[dev]** settings.yaml이 가리키는 대상으로 e2e 한 번(`--limit <N>`). **[prd]** 전체 문서를 새 스키마로:
```bash
cd "$ROOT/<코드>"
nohup python3 deploy/host/scripts/run_docs.py --start-offset 0 > "$ROOT/run_docs.0.2.0.out" 2>&1 &
tail -f <작업 폴더>/batch_progress/progress.log                               # 기대: 처음에 FAQ 교체 줄, 그다음 문서마다 "doc#<seq> …" 줄
```
- 이 전체 실행에는 `--skip-done`을 주지 않는다 — ParsingMeta에 `gold_version` 칸이 생기기 전(C-76)에는 0.1.0이 끝낸 문서를 "끝남"으로 보고 건너뛴다.
- 끝나면(종료 코드 0, 실패가 있으면 1 — [server-guide §2](server-guide.md#2-일상-실행--run_docs문서별-흐름)) `systemctl start mcp-server-keepalive.timer`(새벽 배치는 8-4 3).

### 8-4. 배포 뒤

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 적재 기록 — 실행 기록의 `meta_missing`·`loaded_at_failed`가 0인지, ParsingMeta에 판·적재 시각이 채워지는지 | 서버 운영 | C-76 |
| 2 | 적재가 지우지 않는지 · 상주 컨테이너 `/tmp` · 좀비 프로세스 | 서버 운영 | C-68 |
| 3 | 새벽 배치 — `ops.nightly.time`·`max_docs`·`deadline`을 모두 채울 때만 켬(마감은 시작보다 5분 넘게 뒤) → `systemctl start data-pipeline-nightly.timer` → `journalctl -u data-pipeline-nightly` | 서버 운영 | C-72 |
| 4 | 2주 뒤 옛 검색 스키마·옛 `struct` 스키마를 백업한 뒤 지움 | DB 담당 | C-74 |
| 5 | `versions.md`에 한 줄 · 되돌리기가 필요 없어진 뒤 `prune_old.sh --apply` | 서버 운영·devops | §6 |
| 6 | `query_edw` — 실제 업무 SELECT 몇 개(JOIN·`WITH`·대괄호 이름·한글 별칭·`TOP`)를 부른다. 기대: 행이 오거나 행·시간 상한 안내만. 정상 SELECT가 `rejected:*`로 거부되면 SQL과 오류 코드를 `issues.md`에 | 서버 운영 | — |
| 7 | `edw_meta` — 서버 카탈로그(`search.edw_meta.dir`의 `catalog.json`)에서 이름 끝에 공백이 있는 표를, 그 이름 그대로와 공백을 뺀 이름으로 각각 부른다. 기대: 둘 다 같은 표의 칸 목록 | 서버 운영 | — |
| 8 | 로그 DB — `search` 한 번 뒤 `applog.mcp_call`에 그 호출 한 행(`args`에 질문), `<루트>/output/logs/`가 비어 있음(있으면 DB 쓰기 실패 — 파일 안 오류 확인) | 서버 운영 | C-79 |

### 8-5. 되돌리기(0.2.0 → 0.1.0)

새 `db_schema`를 썼으므로 옛 스키마는 그대로 남아 있다 — 보통 DB는 되돌릴 것이 없다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
cd "$ROOT/<코드>" && bash deploy/host/scripts/dc.sh down                     # 0.2.0 컨테이너 셋 내림
```
- 0.1.0 자리(`$OLD_CODE`·`$OLD_SF`)는 그대로 남아 있다. 0.1.0 컨테이너(`data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)와 0.1.0 타이머는 `$OLD_CODE`의 README §5-3·§5-5 방법으로 다시 띄우고, 시작 로그 첫 줄로 0.1.0인지 본다.
- 옛 스키마를 0.2.0이 바꿨다면(새 이름을 안 썼을 때만) 백업으로: `$DOCKER exec -i "$PG_C" pg_restore -U "$PG_U" -d "$PG_D" --clean < "$BK/pg-0.1.0.dump"`(DB 담당과 같이 — downgrade 명령은 없다).
- ParsingMeta에 0.2.0이 쓴 행·`gold_version`은 그대로 남는다(0.1.0은 그 칸을 읽지 않음).

### 8-6. EDW 조인 사슬 파일 고쳐 쓰기(서버 — pl-29)

적재가 문서 메타(고객 `client_edw`·등록 시각 `created_at`·원천 메타 `doc.attrs`)를 EDW에서 채울 때 따라가는 표·칸 이름과, 검색 MCP가 쓰는 `attrs` 키의 거르기 이름·근거 표시는 파일 하나에 있다(PRD [pl-52](../prd/load-schema.md#pl-52)). 기본 파일은 코드 폴더의 `resources/config/edw_chain.yaml`이고 **꼴과 칸의 뜻은 그 파일의 머리 주석이 정본**이다. 서버 EDW 이름이 다르거나 메타 키를 더하려면 코드를 고치지 않고 사본을 고친다.

**① 사본 고치기 · 칸 적기** — 사본은 `<루트>/edw_chain.yaml`(`dc.sh init`이 없을 때만 복사 — 10001, 640)이고, `data-pipeline`·`mcp-server`에 `/etc/rag/edw_chain.yaml`로 읽기 전용 붙는다. 설정 칸은 하나(`ops.paths.edw_chain` — 적재와 검색이 같은 칸)이고 **칸을 적었을 때만 사본이 쓰인다**(비우면 코드의 기본 파일).
```bash
vi <루트>/edw_chain.yaml                                             # 주인·권한은 그대로 10001, 640
# settings.yaml(편집기로):  ops: { paths: { edw_chain: /etc/rag/edw_chain.yaml } }
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

# (라) 메타 키 더하기 — 이미 읽는 단계의 칸이면 fields에 한 줄(새 표면 steps에 단계도). 이미 적재한 문서는 --replace로 다시 적재해야 값이 찬다
crms:
  fields:
    pm_name: {from: project.PM_NAME, filter: pm_name, evidence: true}   # search(attrs={"pm_name": "…"}) · 근거 attrs.pm_name
```
- 새 `filter` 이름은 `search`의 이름 있는 인자가 아니라 `attrs` 거르기로 쓴다(이름 있는 인자는 계약에 고정).
- **이름을 바꾸면 안 되는 키:** SFDC `sf_op_id`(`list_doc_fulltext`가 키 이름 그대로 읽음 — EDW 칸 `from`만 바꾼다), 분류 힌트 키(`title`·`entity_*`·`sent_received__c`·`subject`·`stagename`·`real_rfp__c`·`rfp_received_*`·LAS `approvalname` — 분류가 이름으로 읽음). `doc_class`는 분류가 쓰는 키라 사슬에 쓰지 않는다.

**③ 실제 실행 전에 점검** — 파일만 읽고 검사한다(EDW·PG에 붙지 않음).
```bash
$DOCKER exec data-pipeline python -m pipeline.load.edw_doc_meta --check                                   # 설정 칸이 가리키는 파일
$DOCKER exec data-pipeline python -m pipeline.load.edw_doc_meta --check --file /etc/rag/edw_chain.yaml   # 칸을 적기 전에 사본만
# 기대(기본 파일): [edw_meta] 사슬 설정 OK(…) — sfdc 단계 11·키 15(거르기 5) · crms 단계 4·키 4(거르기 2) · las 단계 4·키 3(거르기 2) · faq 단계 1·키 0(거르기 0) · other 단계 1·키 0(거르기 0)   (종료 코드 0)
# 틀리면: [edw_meta] 사슬 설정 오류(…): <원천>.<자리>: … — 틀린 곳을 모두 적음   (종료 코드 1)
```
칸 이름이 EDW에 실제로 있는지는 이 점검이 보지 않는다 — `edw_meta`·`query_edw`나 DB 담당으로 확인한다. 검색 쪽은 `edw_meta`를 인자 없이 불러 `search_attrs`에 고친 키가 보이는지 본다.

**④ 오류가 나면 · 되돌리기**
- 적재 시작 때 `[edw_meta] 사슬 설정 파일을 못 읽음(…)`·`사슬 설정 오류(…)`·`사슬 설정 YAML 오류(…)`로 멈춘다(기본 파일로 돌아가지 않음). 검색은 같은 글을 `search`의 `{"error"}`로 돌려준다. ③으로 고친 뒤 다시 돌린다.
- 칸 이름이 EDW에 없으면 적재는 계속되고 그 칸 메타만 비며(표를 못 읽으면 그 원천 메타 전체 — `optional` 단계면 그 단계만) 경고와 실행 기록 `meta_missing`이 남는다 — 고친 뒤 `--replace`로 다시 적재한다(다시 파싱하지 않음).
- 되돌리기: settings.yaml의 `ops.paths.edw_chain`을 **비우면** 기본 파일로 돌아간다. 사본 파일은 지우지 않는다(마운트 원본 — 없으면 `data-pipeline`·`mcp-server`가 안 뜸).

### 8-7. 서버에서 직접 만드는 파일

서버마다 값이 다른 파일은 코드 폴더 밖 **루트 바로 아래**에 둔다. `dc.sh init`이 **없을 때만** git의 예시를 복사한다(있으면 덮지 않음). 새 판(새 루트)에는 앞 루트에서 `cp -p`로 복사해 온다.

| 파일 | 자리(호스트 → 컨테이너) | 예시(복사 원본) | 읽는 곳 | 주인·권한 |
|---|---|---|---|---|
| `settings.yaml` | `<루트>/settings.yaml` → `/etc/rag/settings.yaml`(읽기 전용 — 세 컨테이너) | `settings.sample.yaml` | 모든 앱·호스트 스크립트 | 10001:<운영 그룹> 640(운영 계정 UID가 10001이면 600) |
| `edw_chain.yaml` | `<루트>/edw_chain.yaml` → `/etc/rag/edw_chain.yaml`(읽기 전용 — `data-pipeline`·`mcp-server`) | `resources/config/edw_chain.yaml` | 적재·검색 MCP — `ops.paths.edw_chain: /etc/rag/edw_chain.yaml`을 적었을 때만 | 10001:<운영 그룹> 640 |

- 백업 묶음 `<루트>/backup/0.2.0-<시각>/`(8-3 0·2 — 700): 0.1.0 설정 사본 `settings.yaml.0.1.0`(8-3 4 입력)·이미지 목록·`pg_dump`.
- 고객 명부·용어집은 서버 파일이 아니라 PG 마스터 표다(`migrate master load` — 8-3 5).
