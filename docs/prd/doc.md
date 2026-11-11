# 문서·릴리스

[PRD.md](../PRD.md)의 카테고리 하나 — 문서 배치, 버전, 이미지, 서버 설치.

순서: 문서 do-04·do-02·do-03·do-01 → 버전 op-04 → 이미지 op-06·op-07·op-12 → 서버 설치 op-10·op-11.

<a id="do-04"></a>
## do-04 · 문서 배치와 언어
- 규칙: 사람이 읽는 문서는 한국어. 기능 요건은 [PRD.md](../PRD.md)와 `docs/prd/<카테고리>.md`(extract·transform·transform-cleanup·load·load-schema·mcp·ops·ops-settings·test·doc)에만 — ID는 바꾸지 않는다. 카테고리 파일 끝에 "코드와 다른 점 · 지울 코드". 지난 기록은 `docs/history/`(보관만). CLAUDE.md는 규칙·하네스 명령만. 문서 지도는 [INDEX.md](../INDEX.md).
- Status: done

<a id="do-02"></a>
## do-02 · `docs/INDEX.md`의 `## Glossary`
- 규칙: 약어·프로젝트 용어는 [INDEX.md](../INDEX.md#glossary) 한 곳. CLAUDE.md는 링크 한 줄.
- Status: done

<a id="do-03"></a>
## do-03 · `refactor.md`는 열린 서버·사람 확인만
- 규칙: [refactor.md](../refactoring/refactor.md)에는 저장소 안에서 끝낼 수 없는 확인(C-xx) 중 열린 것만, 무엇을 돌리고 무엇이 통과인지로 적는다. 끝난 항목은 지운다(이력은 git). 등급 A 검토자 = 사용자.
- Status: done

<a id="do-01"></a>
## do-01 · `refactor.md` 자리
- 규칙: `docs/refactoring/refactor.md`(저장소 루트에는 입구 파일만). 코드 주석의 `refactor.md C-xx`는 이름만 가리킨다.
- Status: done

<a id="op-04"></a>
## op-04 · 버전과 릴리스 태그
- 규칙: 버전은 저장소 루트 `VERSION` 하나(SemVer, 지금 `0.1.0`) — 두 이미지와 DB 버전 표기(`common.pipeline_version()`)가 함께 쓴다. `release/<버전>`에서 올리고 `main`에 태그 `v<버전>` + GitHub release 노트. 1.0.0 전에는 MCP 계약·DB 스키마가 깨져도 MINOR.
- Status: done

<a id="op-06"></a>
## op-06 · 실행 이미지(코드 없음) — 개발 서버는 코드 폴더를 마운트
- 이유: 이미지와 코드를 따로 반입한다 — 코드만 바뀌면 코드 폴더만 바꾼다.
- 규칙:
  1. Dockerfile 타깃 `pipeline-runtime`·`mcp-runtime`(이미지 `data-pipeline-runtime`·`mcp-server-runtime`) = OS 패키지·LibreOffice·휠·`assets/` 모델·사용자 10001·ENV만. 코드가 든 `pipeline`·`mcp`는 그 위에 코드 COPY만 얹는다.
  2. 실행 이미지 시작 `deploy/docker/runtime_entry.sh`: ① `/app`에 코드 폴더가 없으면 종료 2 ② 이미지 의존성 지문(`/opt/sbl/docker/deps_hash`) ≠ 코드의 `deploy/docker/DEPS_HASH`(`deploy/release/deps_hash.sh` — requirements-core·image의 sha256)면 종료 2 ③ 이미지 판·코드 커밋(`CODE_COMMIT`)을 한 줄 남기고 코드 폴더의 `deploy/docker/entrypoint.sh`로 넘긴다.
  3. 코드 폴더 묶음 = 이 커밋의 git 추적 파일 + `CODE_COMMIT`, `valid_env/`·`validation/` 뺌 — `build_ship.sh`가 `output/ship/code-<버전>-<커밋>.tar.gz`로 만든다. `/app`에 읽기 전용(`:ro,z`)으로 붙인다.
  4. compose는 환경마다 파일 하나 — `compose-local.yml`·`compose-dev.yml`·`compose-prd.yml`(+ 따로 띄우는 `compose-pgvector.yml`·`compose-redis.yml`). `host_ctl.sh`가 settings.yaml `run_env`에 맞는 파일 하나로 부른다([ops.md#op-20](ops.md#op-20)).
  5. 반입: 이미지 git(`sbl_images` — 판 폴더마다 분할 조각 + `load.sh`)과 코드 git을 공용 폴더에 zip으로 받아 풀고, 코드 폴더는 벌마다 `data_pipeline-<n>/app`으로 복사한다. [dev.md A-1~A-2](../operations/dev.md#a-1-벌-폴더-만들기).
- 파일: `deploy/docker/{Dockerfile,runtime_entry.sh,DEPS_HASH}`, `deploy/release/{build_ship.sh,deps_hash.sh}`, `deploy/host/compose/`, `deploy/host/scripts/pipe_exec.sh`.
- QA: `tests/server/common/test_deps_hash.py`(DEPS_HASH ↔ requirements) · 통과. 실행 이미지에 코드 트리를 붙여 `selftest` `[판정]` 통과 · 코드 없이 띄우면 종료 2.
- Status: done

<a id="op-07"></a>
## op-07 · 개발 → 운영 굽기
- 이유: 운영에는 개발 서버에서 시험한 실행 이미지 그 판과 코드 폴더를 그대로 굽는다.
- 규칙:
  1. `deploy/docker/Dockerfile.bake`: `FROM ${RUNTIME_IMAGE}` + 코드 COPY(Dockerfile `pipeline`·`mcp` 타깃과 같은 자리), ENTRYPOINT `/opt/sbl/docker/entrypoint.sh`, 라벨 코드 커밋(`revision`)·실행 이미지 ID(`base.digest`). 패키지 설치·네트워크 없음.
  2. `bash deploy/release/bake_prod_image.sh <실행 이미지 판> [pipeline mcp]`(개발 서버): ① 코드 `DEPS_HASH` = 실행 이미지 지문 ② 빌드(문맥 = 코드 폴더) ③ `selftest_gate.sh` `[판정] 통과` ④ `stage_images.sh`로 저장·gzip·45m 조각·sha256 → `$OUT/sbl_images/<TAG>/<이미지>/` + `load.sh`·`BUILD.txt` + 시험한 코드 폴더 묶음. 태그 = 코드 `VERSION`(다르면 멈춤). `OUT` 기본 `/var/tmp/bake`. 컨테이너 도구 기본 docker.
  3. 구운 이미지 파일·조각에 비밀(settings.yaml)이 들면 비밀과 같이 다룬다 — 운영 서버와 권한 있는 반입 경로에만, 키를 바꾸면 다시 굽고 옛 이미지·조각을 지운다, 이미지 이력·`inspect`·시작 로그에 값이 안 보이는지 본다, 굽는 데 쓴 사본은 지운다([op-12](#op-12)).
- 파일: `deploy/docker/Dockerfile.bake`, `deploy/release/{bake_prod_image.sh,stage_images.sh,load.sh}`.
- Status: done

<a id="op-12"></a>
## op-12 · 운영(prd) 이미지에 settings.yaml 굽기
- 할 일: `bake_prod_image.sh`·`Dockerfile.bake`에 settings.yaml 굽기를 더한다(규칙은 op-07 ③). 지금 `bake_prod_image.sh`는 코드 묶음에서 settings.yaml을 뺀다. 🔒 검토 등급 A(비밀 처리) — 사람 검토.
- Status: todo

<a id="op-10"></a>
## op-10 · 서버 설치·업그레이드 — 길 하나, docker 기본
- 규칙:
  1. 설치 길은 환경마다 실행 안내 하나 — [local.md](../operations/local.md)·[dev.md](../operations/dev.md)·[prd.md](../operations/prd.md). 다른 문서는 링크한다. 운영 중인 서버의 판 올리기·되돌리기는 [prd.md](../operations/prd.md#판-올리기) 하나(판 번호와 상관없는 순서 — 지난 0.2.0 배포 절차는 [history/deploy_0_2_0.md](../history/deploy_0_2_0.md)).
  2. 컨테이너 도구 = 셸 `DOCKER` > settings.yaml `ops.host.container_cli` > docker > podman(`load_settings.sh` `docker_default`, 설정을 읽은 뒤 정함). `stage_images.sh`·`load.sh`도 podman 우선.
  3. 서버 상주 컨테이너 셋(운영 묶음 `compose-prd.yml`): 일괄 `data-pipeline`(파싱·구조화·적재 — 문서 폴더 읽기 전용 + 결과 폴더), `mcp-data-parsing`([ops.md#rn-03](ops.md#rn-03)), `mcp-server`. 개발 서버의 개발자 벌은 `data-pipeline-<n>`(`compose-dev.yml`). 호스트 스크립트가 들어갈 이름은 settings.yaml `ops.host.pipeline_container`·`mcp_container`·`parse_container`(기본 위 세 이름 — 개발 벌 N은 `pipeline_container: data-pipeline-N`). 자원(CPU·메모리)은 compose 파일에 직접. pgvector·Redis는 따로 띄우는 compose 파일.
  4. 운영 작업(`pipe_exec.sh parse|publish`, `pipe_exec.sh <도구>|migrate|show-stack|check`, `dbtool`)은 상주 파이프라인 컨테이너 안에서 `docker exec`(`pipe_exec.sh` — 안 떠 있으면 종료 2). 일회성 작업 컨테이너는 없다. 이미지 점검(`docker run --rm … selftest`)과 운영 반영의 DB 판 올리기(`promote.sh` — 새 이미지로 컨테이너를 띄우기 전)만 예외.
  5. `load_settings.sh`는 호스트 python(PyYAML만)의 `settings_to_env.py` + `host_settings.tsv`로 설정을 셸 env로 낸다.
  6. 재부팅 때 docker 서비스(`systemctl enable docker`)가 `restart: unless-stopped`·`always` 컨테이너를 다시 띄운다. keepalive 타이머 `mcp-server-keepalive`가 `mcp_keepalive.sh`로 `mcp-server`·`mcp-data-parsing`를 살핀다.
  7. 운영 반영(이미지 불러오기 → 폴더 → DB 판 → 띄우기 → 점검)은 `promote.sh` 하나([ops.md#op-21](ops.md#op-21)).
- 파일: `README.md` §5, `deploy/host/{scripts,compose,systemd}/`, `deploy/release/{stage_images.sh,load.sh,promote.sh}`.
- QA: `tests/general/deploy/test_compose.py`·`test_host_env.py`·`test_dc.py`·`test_promote.py` · 통과. 서버 확인 refactor.md C-71·C-82·C-83.
- Status: done

<a id="op-11"></a>
## op-11 · 사람 정답 폴더(`GOLD_DIR`) 칸 없음
- 이유: 상주 `data-pipeline`에 사람 정답 폴더가 붙지 않아 점검기의 이름 짝 점검이 늘 건너뛰어졌다.
- 결정(사용자 11-04): 칸 `GOLD_DIR`(`pipeline.paths.gold_dir`·`pipeline.host.gold_dir`)과 이미지 약속 경로 `gold_mount`를 지웠다. 점검기(`common/check/checker.py`)에 정답 폴더 점검이 없다. 옛 파일에 남은 칸은 시작 거부.
- 파일: `common/config/settings.py`, `pipeline/config.py`, `common/check/checker.py`.
- Status: done

<a id="op-13"></a>
## op-13 · 서버 벌 폴더 = `{app,home}` — app = 코드 폴더(루트), 새 판은 app 덮어쓰기, `/srv/rag`·`env/`·`code/live` 없음
- 이유: 서버 아무 자리에 벌 폴더 하나를 두고 그 안에서 실행한다. 코드·설정·결과(`app/`)와 root 홈(`home/`)을 나눠, 컨테이너 안에서 같은 폴더가 두 자리에 보이지 않게 하고 검색 DB(pgvector — 따로 떠 있는 PG 컨테이너)만 함께 본다.
- 규칙:
  1. 벌 폴더 = 개발 벌 `<SBL_ROOT>/data_pipeline-<n>/`(1~4) · 운영 묶음 `/home/sbl/data_pipeline/`(`PRD_DIR` — 운영 서버, 개발 서버의 출시 전 시험) — 그 아래 `app/`과 `home/` 둘. 루트 = `app/`(코드 zip을 푼 코드 폴더) 자체, PC는 저장소 루트. 호스트 스크립트는 자기 위치에서 루트를 구하고, `host_ctl.sh`가 그 부모에서 `SBL_ROOT`·`PRD_DIR`을 정한다(env·고정 경로 없음).
  2. `app/` 바로 아래 코드와 함께: `settings.yaml`(git의 `settings.sample.yaml`을 복사해 이름을 바꾸고, 맨 위 `required`의 빈 필수값을 직접 채움) · `output/`(결과 — `output/_mcp_parse/jobs` 포함) · `.env`(PG·Redis 비밀번호 — 사람이 적음). 모두 git 제외. `edw_chain.yaml`은 코드와 함께 git에 있다. `home/`은 `app/` 밖 — 컨테이너 `/root`(root 홈: opencode·VS Code 서버·git 설정, 운영 묶음의 검색 MCP는 `home/mcp`). 붙이는 자리: 개발 벌은 `app` → `/app`·`home` → `/root`, 운영 묶음은 `app/settings.yaml` → `/etc/rag/settings.yaml`(읽기 전용)·`app/output` → `/app/output`·`home` → `/root`(코드는 이미지 안). 이미지 부품은 `/opt/sbl/{docker,assets}`, 이미지에 VOLUME이 없다 — 무엇을 붙일지는 compose가 정한다. 서버 벌의 `app/`에는 `valid_env/`를 두지 않는다. `host_ctl.sh init`은 `backup/`을 만들지 않고, 권한 정리(`a+rX`)에서 settings.yaml·`.env`·output/을 뺀다. 이미지 폴더(`sbl_images-main/`)는 한 단계 위 공용 폴더(예 `/home/sbl/`)에 하나 — 여러 벌(op-15)이 같이 쓴다.
  3. `/srv/rag`, `env/`(`SERVER_ENV_DIR`), `code/live` 링크를 만들거나 쓰지 않는다.
  4. 새 판 = 사람이 새 코드를 벌의 `app/`에 덮어씀(옛 것은 각자 백업 — gitea에도 올림). `settings.yaml`·`output/`·`.env`는 zip에 없어 남고, `home/`은 `app/` 밖이라 그대로다. 새 판에서 지운 파일도 남는다. 검색 DB는 같은 PG를 그대로 본다. 되돌리기 = 백업을 되살려 다시 띄움([prd.md 되돌리기](../operations/prd.md#되돌리기)).
  5. 컨테이너는 compose로 띄운다(`host_ctl.sh up`). 상태 보기는 둘 다 안내 — 서버 전체는 `docker ps`(일반 사용자 셸이면 `sudo`), 우리 묶음만은 `host_ctl.sh ps`.
  6. systemd 타이머(새벽 배치·MCP 살리기)는 운영 묶음 `app/`에서 설치하고 경로를 그 폴더 기준으로 채운다 — 다른 폴더에서 다시 설치하면 그 폴더로 바뀐다.
  7. 로그는 Postgres(applog — op-01)만 쓴다. 서버 기본값 `ops.log.log_db_enabled: true`. 파일은 DB에 못 쓸 때의 예비 한 곳 `output/logs/`뿐 — 콘솔 기록 파일(`logs/<시각>_<도구>.log`·`RUNLOG.md`·`runlog.jsonl`)과 `qa_log/` 파일은 없앤다(사람이 보는 실행 출력은 컨테이너 로그 `docker logs`, 질의는 DB `mcp_log`). 외부 모델 하루 지출 상한(`dev.models.guard.daily_budget_usd`)을 지키려면 여러 프로세스가 같은 합계를 봐야 해서 장부 기록이 필요하다 — 장부는 임시 자리 `output/_llm_spend/<날짜>.txt`(외부 호출은 PC만이라 서버에는 생기지 않음).
  8. `output/` 안의 임시 자리는 이름 앞에 `_`를 붙여 역할이 보이게 한다: `_docflow/<번호>/`(문서 하나의 파싱 → 구조화·적재 작업 — 구조화·적재는 로컬 파싱 결과를 읽고, 끝나면 지움), `_staging/`(미리 받기), `_mcp_parse/jobs/`(`parse_document` 작업 — 결과는 호출한 쪽에 돌려주고 최근 30개만 보관), `_llm_spend/`(규칙 7). `_`가 없는 것은 `logs/`(DB 예비)뿐.
  9. 게시는 늘 한다(pl-09). 실제 Object Storage·EDW 없이 시험할 때는 가짜 EDW(sqlite)·가짜 Object Storage(`file://<폴더>`)를 상대 경로로 넣는다.
- 파일: `deploy/host/scripts/{load_settings.sh,host_ctl.sh,run_pipeline.py,prune_images.sh,…}`(루트 구하기·`host_ctl.sh init`·`host_ctl.sh timers`) · `deploy/host/compose/*.yml`(`SBL_ROOT`·`PRD_DIR` 아래 `app`·`home` 마운트) · `deploy/host/systemd/*.service`(`@CODE_DIR@` 틀) · `deploy/release/{bake_prod_image.sh,build_ship.sh,load.sh}` · `common/config/{settings.py,layout.py,sample.py,keyscan.py,setarg.py}`(서버 이미지 기본 `APPLOG_DB_ENABLED`·`log_fallback_dir` `output/logs`·지운 칸 경고) · `common/core/{runlog.py,paths.py}` · `common/ai/guard.py` · `mcp_server/services/{edw_query.py,search/search_svc.py}`(`qa_log.py` 삭제) · `pipeline/run_mcp_parsing.py` · `docs/operations/{local,dev,prd,settings,mcp-guide}.md`.
- QA: `tests/general/deploy/test_dc_init.py`(init 배치·루트 = 코드 폴더·app 안에 `home/`을 만들지 않음·`timers` 틀 채우기) · `test_compose.py`(벌 `app`·`home` 마운트) · `test_host_env.py` · `tests/server/common/test_layout.py`(지운 칸은 시작 거부) · `tests/server/common/test_settings.py`(서버 이미지 DB 로그 기본 켬). 서버 확인: [refactor.md C-90](../refactoring/refactor.md).
- Status: done

<a id="op-19"></a>
## op-19 · 서버 문서는 환경마다 실행 안내 하나
- 이유: 서버에 들어가서 문서의 명령을 위에서부터 차례로 치면 끝나야 한다. 같은 절차가 여러 곳에 있으면 한쪽만 고쳐져 어긋난다.
- 규칙:
  1. 환경마다 실행 안내 하나 — PC [local.md](../operations/local.md), 개발 서버 [dev.md](../operations/dev.md)(호스트 셸 + 벌 컨테이너 안 `python -m` 명령, 폴더·원천·파일 경로는 `--set`), 운영 서버 [prd.md](../operations/prd.md)(설치·판 올리기·되돌리기). 사람이 채울 설정 칸은 [settings.md](../operations/settings.md). 다른 문서는 링크만 둔다.
  2. 명령 위주 — 단계마다 번호, 명령 블록, 기대 출력 한 줄. 블록에서 쓰는 변수는 그 블록 첫 줄에서 정한다. 설명·배경은 짧게.
  3. 낱말(벌·벌 폴더·공용 폴더·판·갈래·원천·게시)은 `docs/INDEX.md` 용어집 한 곳에서 풀이한다.
  4. 지난 판의 긴 안내서(옛 server-guide·env-guide)와 지난 판에서만 하는 일은 `docs/history/`에 둔다.
  5. 문서와 코드가 다른 칸 설명(필수·선택)은 코드(설정 모델 설명)를 고쳐 맞춘다.
- 파일: `README.md` §5, `docs/operations/{local,dev,prd,settings}.md`, `docs/INDEX.md`, `common/config/settings.py`·`pipeline/config.py`(칸 설명), `deploy/host/scripts/host_ctl.sh`(init의 빈 필수 칸 목록).
- QA: 새 사람이 dev.md만 보고 개발 서버(또는 PC의 docker 시험 서버)에 설치해 `[host_ctl check] 통과`까지 간다. 문서 링크·앵커 점검이 0건.
- Status: todo
