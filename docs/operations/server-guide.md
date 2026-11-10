# 서버 가이드 — 설치 · 실행 · 운영 · 판 올리기 · 릴리스

대상: 서버(개발 `dev`·운영 `prd`)를 설치하고 돌리는 사람. 설정 칸 하나하나의 뜻은 [env-guide.md](env-guide.md), 검색 도구 쓰는 법은 [mcp-guide.md](mcp-guide.md)다.

| 하려는 일 | 볼 절 |
|---|---|
| 환경별(local · dev · prd) 띄우기·점검·타이머 — 직접 명령과 host_ctl.sh | [§0](#0-환경별-실행-명령--local--dev--prd) |
| 새 서버 설치(개발·운영 공통) | §1 — 순서는 [§1-5 서버 설치 순서](#서버-설치-순서) 하나 |
| 개발 서버에 내 벌 하나 만들기(차례로 따라 하기) | §2 |
| 매일 돌리기·점검·문제 해결 | §3 |
| 이미 돌고 있는 서버를 새 판으로 | §4 |
| 이미지 빌드·버전·운영 이미지 굽기 | §5 |
| 내부망 gitea로 코드 받기·고치기·올리기(컨테이너 안 git) | §6 |
| `<…>` 자리에 넣을 값 | [예 값 사전](#바꿔-넣을-자리--예-값-사전) |

## 바꿔 넣을 자리 — 예 값 사전

명령의 `<…>`는 바꿔 넣을 자리다. 줄 옆 주석에 예가 없으면 이 표를 본다. 예 값은 개발 서버 `/home/sbl` 아래 벌 둘(공용 main `-0`, 개발자 `-1`)을 기준으로 한다 — 자기 서버 값은 "확인하는 법"으로 찾는다.

| 자리 | 뜻 | 예 | 확인하는 법 |
|---|---|---|---|
| `<루트>` · `<벌 폴더>` · `<코드 폴더>` · `<시험한 벌 폴더>` · `$B` | 벌 폴더 = 코드 폴더(zip을 푼 곳 또는 git clone한 곳 — settings.yaml·output/이 바로 아래) | `/home/sbl/sbl_data_parsing-main-0` | `ls $B` → `deploy common pipeline … VERSION` |
| `<공용 폴더>` | 벌 폴더·이미지 폴더를 두는 부모 폴더 | `/home/sbl` | |
| `<옛 루트>` | 0.2.0 배치 서버의 루트(설정이 코드 폴더의 부모에 있던 때) | `/srv/rag` | `ls <옛 루트>` → `settings.yaml sbl_data_parsing-0.2.0/` |
| `<번호>` · `<벌 번호>` · `<벌>` · `-<숫자>` · `-<n>` | 벌 번호 — 벌 폴더 이름 끝 `-<숫자>` | `0`(공용 main) · `1`(개발자) | 컨테이너 이름 끝: `data-pipeline-1` |
| `DEV-<숫자>` · `<원천>` | 원천 시스템 이름(검색 원천 스키마 끝) | `DEV-2` · `SFDC` · `CRMS` | settings.yaml `required.source.source_systems` |
| `<운영 그룹>` · `<그룹>` | 결과·설정 파일을 같이 볼 서버 리눅스 그룹 | `sbl` | `id -gn sbl`(사람 계정의 그룹) |
| `<이미지 판>` · `<실행 이미지 판>` | 개발 서버 실행 이미지 판 — `BUILD.txt`의 DEPS_HASH가 코드와 같은 판 | `0.3.0` | `ls /home/sbl/sbl_images-main/` |
| `<VERSION>` · `<버전>` · `<판>` · `<새 판>` · `<지금 판>` · `<판 번호>` | 코드 판(저장소 루트 `VERSION`) | `0.3.1` | `cat $B/VERSION` |
| `<앞 판>` · `<끝 판>` | 비교하는 두 판 | `0.3.0` · `0.3.1` | `git tag -l 'v*'` |
| `<태그>` · `<이미지 태그>` · `<이미지>` | 이미지 이름:판 | 개발 `data-pipeline-runtime:0.3.0` · 운영 `data-pipeline:0.3.1` | `docker image ls` |
| `<시험 태그>` | PC 시험 빌드 태그(작업마다 새로) | `0.3.1-t1` | |
| `<결과 폴더>` | 벌의 결과 폴더(컨테이너 `/app/output`) | `/home/sbl/sbl_data_parsing-main-0/output` | `$B/output` |
| `<원본 문서 폴더>` · `<있는 호스트 폴더(절대 경로)>` | 서버의 원본 문서 폴더(컨테이너 `/data/docs`) | `/data/docs` | settings.yaml `required.deploy.host_docs_dir` |
| `<작업 폴더>` · `<run_pipeline 작업 폴더>` | 일괄 실행 임시 폴더(벌마다 다르게) | `/srv/rag/run_pipeline-0` | settings.yaml `ops.run_pipeline.run_pipeline_work_dir` |
| `<백업 폴더>` · `<백업 폴더 — 벌 폴더 밖>` | 판을 바꾸기 전 백업을 두는 부모 폴더(벌 폴더 밖) | `/home/sbl/backup` | |
| `<기록>` | 운영 기록 폴더(벌 폴더 밖 — `versions.md`·`issues.md`·`server-changes.md`) | `/home/sbl/ops_log` | |
| `<컨테이너>` · `<이름>` | 컨테이너 이름 | `data-pipeline-1` · `mcp-server-0` | `docker ps --format '{{.Names}}'` |
| `<단위>` | systemd 단위 이름 | `data-pipeline-nightly.service` | `systemctl list-timers` |
| `<PG 컨테이너>` · `<pg 컨테이너>` · `<PG 컨테이너 이름>` · `<required.deploy.pg_container_name>` | pgvector 컨테이너 이름 | `pgvector` | `docker ps --format '{{.Names}}'` |
| `<PG 주소>` · `<PG 포트>` | 우리 컨테이너가 붙는 PG 주소·포트(서버 쪽 포트) | `host.docker.internal` · `5433`(`compose-pgvector.yml`로 띄웠을 때) | `docker port pgvector` |
| `<계정>` · `<required.pg.pg_user>` | PG 앱 계정 | `rag_app` | settings.yaml `required.pg.pg_user` |
| `<관리자 계정>` · `<운영 계정>` | PG 관리자 계정(권한 주기용 — settings.yaml에 넣지 않음) | `postgres` | DB 담당 |
| `<DB>` · `<DB 이름>` · `<required.pg.pg_database>` | PG 데이터베이스 | `rag` | settings.yaml `required.pg.pg_database` |
| `<스키마>` · `<pg_schema>` · `<db_schema>` · `<기준>` · `<required.pg.pg_schema>` | 검색 기준 스키마 | `data_parsing` | settings.yaml `required.pg.pg_schema`(비우면 `data_parsing`) |
| `<임베딩 차원>` | 임베딩 모델 출력 길이 | `1024` | 모델 담당 · 묶음 `meta.json`의 `dim` |
| `<MCP 포트>` · `<search.server.mcp_port>` | 검색 MCP 컨테이너 안 포트(서버 포트는 8051) | `8051` | settings.yaml `search.server.mcp_port` |
| `<벌마다 다른 포트>` · `<내 포트>` | SSH 작업 공간 포트(서버 쪽) | `8020`(벌 0) · `8021`(벌 1) · `8050`(`mcp-server-0`) | `compose-<환경>.yml`의 `ports` |
| `<서버>` | 개발 서버 주소 | `10.0.0.12` | 서버 관리자 |
| `<버킷>` · `<silver_bucket>` | 게시 버킷 | `rag-silver` | settings.yaml `required.publish.publish_bucket` |
| `<커밋>` | git 커밋 번호(앞 7~8자) | `1281faf5` | `git log -1 --oneline` |
| `<코드 zip>` | 코드 판 zip | `sbl_data_parsing-0.3.1.zip`(풀면 `sbl_data_parsing-0.3.1/`) | GitHub 태그 `v0.3.1` |
| `<이미지 zip>` · `<새 이미지 저장소 zip>` | 이미지 조각 저장소 zip | `sbl_images-main.zip`(풀면 `sbl_images-main/`) | |
| `<seq>` · `<번호,…>` · `<번호,번호,…>` | 일괄 실행의 문서 번호(여럿이면 쉼표) | `1203` · `1203,1207` | `progress.log`의 `doc#1203` |
| `<키워드,…>` | 원본 파일 이름에 든 낱말(쉼표 — 하나라도 들면) | `계약서,견적` | |
| `<서비스>` | compose 서비스 이름(컨테이너 이름과 같음) | `data-pipeline-0` · `mcp-data-parsing-0` · `mcp-server-0` | `host_ctl.sh ps` |
| `<수집 서버 사내 IP>` · `<IP>` | 운영 서버 사내 주소 | `10.0.0.20` | 서버 관리자 · 서버에서 `hostname -I` |
| `<스키마.표>` | EDW 표 이름 | `CRMS.RM_MAS_CLIENT` | DB 담당 |
| `<묶음>` | 구조화 묶음 폴더 | `output/edw/bundle` | |
| `<옛 이름>` | 옛 env 이름(설정 칸 자리 찾기) | `PIPE_PROCS` | 오류 글자에 나온 이름 |
| `<타깃>` | 이미지 빌드 대상 | `pipeline-runtime` · `mcp-runtime` · `pipeline` · `mcp` | |
| `<이름 조각>` · `<이름 일부>` | selftest 사례 이름 일부 | `test_publish` | `ls tests/server/*/` |
| `<파일>` | 그 줄이 말하는 파일 | `migrate_search.sql`(`--sql`) · `edw_chain.yaml`(`git checkout HEAD --`) | |
| `<MMDD>` | 월일 4자리 | `1109` | |
| `<질문>` · `<낱말>` · `<처리한 문서에 있는 낱말>` | 검색 시험 문구 | `계약서 보관 기간은?` · `보관 기간` | 처리한 문서 아무거나 |
| `<모델>` · `<model id>` | 내부망 모델 이름 | 모델 담당이 준 이름(예 `qwen2.5-72b-instruct`) | 모델 담당 |
| `<내 공개 열쇠>` | 내 PC의 SSH 공개 열쇠 파일 | `~/.ssh/id_ed25519.pub` | 없으면 PC에서 `ssh-keygen -t ed25519` |
| `<gitea 주소>` | gitea 주소:포트 | `gitea.example.local:3000` | 브라우저 주소창 |
| `<gitea 저장소 주소>` | 저장소 HTTP 복제 주소 | `http://gitea.example.local:3000/sbl/sbl_data_parsing.git` | gitea 저장소 화면 "HTTP" 복제 칸 |
| `<내 gitea 아이디>` | gitea 가입 때 사용자 이름 | `jehun` | gitea 오른쪽 위 프로필 |
| `<커밋에 남길 이름>` · `<커밋에 남길 메일>` | git 커밋 이름·메일(메일은 gitea 계정 메일과 같게) | `jehun` · `jehun@sbl.local` | |
| `<기능명>` | 기능 브랜치 이름(영문·숫자·`-`) | `pdf-table` | |
| `<바꾼 파일들>` | 커밋할 파일 | `pipeline/load/publish.py docs/operations/server-guide.md` | `git status --short` |
| `<비밀>` · `<비밀번호>` · `<토큰>` · `<내 토큰>` · `<required.tokens.mcp_token>` | 비밀값 — 예를 문서에 쓰지 않는다 | (화면·문서에 쓰지 않음) | MCP 토큰·서명 키: 서버에서 `openssl rand -hex 32` · gitea 토큰: [§6-3](#6-3-개발자-한-벌-만들기) ① · PG 비밀번호: DB 담당 |

## 0. 환경별 실행 명령 — local · dev · prd

실행하는 곳은 셋이고, 이미지·코드·띄우는 컨테이너가 다르다. 환경마다 compose 파일이 하나다(`deploy/host/compose/compose-<환경>.yml`).

| 환경 | 어디서 | 이미지 | 코드 | 띄우는 컨테이너(compose 파일) |
|---|---|---|---|---|
| local | 개발 PC | (보통 이미지 없이 `.venv`) · 시험 이미지 | 저장소 그대로 | 시험 PG 하나 · 이미지로 시험할 때 `compose-local.yml`(0번 한 벌 셋) |
| dev | 개발 서버 — 개발자마다 벌 하나 | 실행 이미지 `data-pipeline-runtime`·`mcp-server-runtime:<이미지 판>`(코드 없음) | 벌 폴더를 `/app/deploy`에 붙임(쓰기 가능) | `compose-dev.yml` — `data-pipeline-0`·`data-pipeline-1` · `mcp-server-0` · `mcp-data-parsing-0` |
| prd | 운영 서버 — 한 벌 | 코드가 든 이미지 `data-pipeline:<VERSION>` · `mcp-server:<VERSION>` | 이미지 안(붙이지 않음) | `compose-prd.yml` — `data-pipeline-0` · `mcp-server-0` · `mcp-data-parsing-0` |

검색 DB `pgvector`(`compose-pgvector.yml`)와 Redis `redis`(`compose-redis.yml`)는 dev·prd 모두 서버마다 하나를 따로 한 번 띄운다(재시작 정책 `always` — [§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)).

**앱 컨테이너를 띄우는 길은 하나 — `deploy/host/scripts/host_ctl.sh`.**
- settings.yaml `required.env.run_env`로 compose 파일을 골라 `docker compose -f deploy/host/compose/compose-<run_env>.yml <인자…>`를 그대로 부른다(`up -d`·`ps`·`logs`·`stop`·`down`·`restart`·`config`).
- 컨테이너 이름·이미지·포트·CPU·메모리·볼륨은 그 compose 파일에 직접 적혀 있다(settings.yaml 칸 없음 — 바꾸는 법 [§2-14](#2-14-컨테이너-이름볼륨-바꾸기)). 서비스 이름 = 컨테이너 이름.
- `docker run`으로 따로 띄우지 않는다 — 이름이 겹쳐 compose가 멈춘다. 그런 컨테이너가 있으면 `docker rm -f <이름>`(예 `docker rm -f data-pipeline-1`) 뒤 `host_ctl.sh up -d`. 결과 폴더·DB는 그대로 남는다.
- 새벽 배치·MCP 살리기 타이머·`pipe_exec.sh`·`run_pipeline.py`는 0번 벌 컨테이너(`data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0`)만 본다.

공통 준비: root 셸, `export DOCKER=docker`, `B=<벌 폴더>`(예 `B=/home/sbl/sbl_data_parsing-main-0`), `cd $B`. `$B`는 이 벌 폴더 경로를 담은 셸 변수다 — `$B/settings.yaml` = `/home/sbl/sbl_data_parsing-main-0/settings.yaml`. 새 셸을 열면 다시 적는다.

읽는 법: `<…>`는 바꿔 넣을 자리(옆 주석에 예 — 없으면 [예 값 사전](#바꿔-넣을-자리--예-값-사전)), `$B`는 위 변수. compose 파일의 볼륨 줄 `<서버 경로>:<컨테이너 안 경로>:<옵션>`은 서버 폴더를 컨테이너 안에 붙인다 — 가운데(컨테이너 안 경로 — `/data/docs`·`/app/output` 등)는 이미지가 정한 자리라 그대로 둔다. 옵션 `ro` = 읽기만, `z` = RHEL SELinux가 컨테이너에 그 폴더를 허용. PG·Redis는 이미 떠 있다고 본다([서버 PG 띄우기](#서버-pg-띄우기)·[§6-7](#6-7-redis--compose-redisyml)). 설정 파일은 `$B/settings.yaml`(설치 순서 [3~4번](#서버-설치-순서)).

### 0-1. local — 개발 PC

```bash
# 시험 PG(pgvector) — 처음 한 번 띄우고, 멈췄으면 start
# 예: <PG 컨테이너> = pgvector(settings.yaml required.deploy.pg_container_name) · <계정> = rag_app(required.pg.pg_user) · <비밀번호> = required.pg.pg_password에 적은 값
docker run -d --name <PG 컨테이너> --restart unless-stopped -p 127.0.0.1:55433:5432 \
  -e POSTGRES_DB=rag -e POSTGRES_USER=<계정> -e POSTGRES_PASSWORD=<비밀번호> pgvector/pgvector:pg16
docker start <PG 컨테이너>
until docker exec <PG 컨테이너> pg_isready -h 127.0.0.1 -U <계정> -d rag; do sleep 1; done   # 기대: accepting connections

# 파이프라인·검색은 이미지 없이 .venv로
export PYTHONPATH=$PWD
.venv/bin/python -m pipeline.config          # 어느 settings.yaml을 읽는지
.venv/bin/python -m pipeline.cli selftest    # 기대: [판정] 통과

# 서버에 올릴 시험 이미지(필요할 때만)
ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh   # 예 <시험 태그> = 0.3.1-t1(작업마다 새로)
```
PC 설치·문서 몇 건 돌리기·검증 페이지는 [README §4](../../README.md#4-pc에서-실행하기)에 있다.

### 0-2. dev — 개발 서버, 개발자별 벌

개발자마다 벌 폴더 하나(`/home/sbl/sbl_data_parsing-main-<번호>`)와 컨테이너 `data-pipeline-<번호>` 하나다. 컨테이너는 root로 뜨고, 서버 바깥에서 root 비밀번호(이미지에 넣은 값)로 SSH 접속해 벌 폴더(`/app/deploy` — 쓰기 가능)에서 코드를 고치고 시험한다. 벌 0은 검색 MCP `mcp-server-0`과 parse_document 작업 컨테이너 `mcp-data-parsing-0`도 맡는다(벌 0과 같은 코드·설정·결과 폴더). 모두 `compose-dev.yml` 한 파일이다(묶음 이름 `sbl-devset`).

**① 이미지 불러오기**(서버에 한 번 — 공용 폴더에서)
`<이미지 판>`은 `sbl_images-main/` 아래 판 폴더 이름이다(실행 이미지를 만든 버전 — 예 `0.3.0`). 코드만 바뀐 판(PATCH — 예 코드 0.3.1)은 실행 이미지를 새로 만들지 않으므로 이미지 판은 그대로다. 고를 판은 그 폴더의 `BUILD.txt` DEPS_HASH가 코드의 `deploy/docker/DEPS_HASH`와 같은 판이다.
```bash
cd /home/sbl
ls sbl_images-main/                                   # 판 폴더 — 예: 0.3.0  load.sh
cat sbl_images-main/0.3.0/BUILD.txt                   # 빌드 커밋·DEPS_HASH
cat sbl_data_parsing-main-0/deploy/docker/DEPS_HASH   # 위 DEPS_HASH와 같아야 함
bash sbl_images-main/load.sh 0.3.0                    # 조각 확인 → 합치기 → docker load · 서버에 판마다 한 번(벌마다 아님 — 모든 벌이 같은 이미지를 씀)
docker image ls data-pipeline-runtime                 # 기대: TAG 칸에 0.3.0
```
- compose 파일의 이미지 판은 `${IMAGE_TAG:-<판>}`의 기본값이다. 불러온 판과 다르면 compose 파일 옆 `deploy/host/compose/.env`에 `IMAGE_TAG=<이미지 판>` 한 줄을 둔다(compose가 그 파일 옆 `.env`를 읽음 — MCP 살리기 타이머가 다시 띄울 때도 같은 판).

**② 띄우기**

먼저 서버 CPU·메모리와 이미 떠 있는 컨테이너가 쓰는 몫을 본다(`cpus`가 서버 CPU 수보다 크면 docker가 거부 — [§1-10](#1-10-자원)):
```bash
nproc                                                  # CPU 수 — 예: 16
free -g                                                # 메모리(GiB) — total·available 칸 · 예: total 62
docker info --format 'CPU {{.NCPU}} · 메모리 {{.MemTotal}}'   # 그대로 입력 — docker가 보는 CPU 수·메모리(바이트)
docker ps -q | xargs -r docker inspect --format '{{.Name}} cpus={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}}'
#   그대로 입력 — 떠 있는 컨테이너의 상한 · cpus 4000000000 = CPU 4개, memory 12884901888 = 12g, 0 = 상한 없음
docker stats --no-stream                               # 지금 쓰는 CPU %·메모리
```
- 정하는 법: 모든 컨테이너의 `cpus` 합 ≤ CPU 수, `mem_limit` 합 ≤ 메모리 total에서 운영체제 몫(예 4g)을 뺀 값. 값은 `compose-dev.yml`의 컨테이너 칸(`cpus`·`mem_limit`·`memswap_limit`)에 직접 적는다 — 기본값 표는 [§1-10](#1-10-자원).
- 칸 뜻: `mem_limit` = 이 컨테이너가 쓸 수 있는 메모리 상한(넘으면 이 컨테이너 안 프로세스가 멈춤 — 미리 떼어 두는 값이 아님) · `memswap_limit` = 메모리+스왑 합 상한(`mem_limit`과 같으면 스왑 안 씀) · `cpus` = CPU 몇 개 몫까지(서버 CPU 수보다 크면 거부) · `cpu_shares` = CPU가 모자랄 때 나눠 갖는 비율(기본 1024 — 작업 컨테이너만 4096) · `pids_limit` = 프로세스·스레드 수 상한 · `logging` = `docker logs` 기록 파일을 50MB마다 새로 쓰고 3개까지만 둠.

PG·Redis를 먼저 띄운다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh) ①·[§6-7](#6-7-redis--compose-redisyml)). 그다음 벌 폴더에서:
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh up -d            # settings.yaml run_env: dev → compose-dev.yml의 앱 컨테이너 넷
bash deploy/host/scripts/host_ctl.sh ps               # 기대: data-pipeline-0 · data-pipeline-1 · mcp-server-0 · mcp-data-parsing-0 Up
```
- 하나만 띄울 때는 서비스 이름을 적는다(예 `host_ctl.sh up -d data-pipeline-1`). 어느 벌 폴더에서 불러도 같은 `compose-dev.yml`이다(벌 폴더 자리는 `SBL_ROOT` — 기본 `/home/sbl`).
- 붙는 것: 벌 폴더 전체 → `/app/deploy`(쓰기 가능 — 코드·`edw_chain.yaml`), 그 안 `settings.yaml`만 다시 읽기 전용, `output/` → `/app/output`, `home/` → `/root`(root 홈), 원본 문서 폴더 → `/data/docs`(읽기만 — `DOC_SRC`, `host_ctl.sh`가 settings.yaml `required.deploy.host_docs_dir`에서 냄). 검색 MCP는 `output/`을 읽기 전용으로, `output/_mcp_parse/jobs`만 쓰기 가능으로 붙인다.
- 컨테이너 안 `127.0.0.1`은 컨테이너 자신이다 — 서버의 PG(5433)·Redis(8010)·모델은 `host.docker.internal`로 붙는다.

**③ 점검**

`host_ctl.sh`로: `bash deploy/host/scripts/host_ctl.sh check` — 기대 마지막 줄 `[host_ctl check] 통과 — 7개`(단계 뜻 [§2-7](#2-7-전체-점검--host_ctlsh-check)). 하나씩 볼 때(처음 실패에서 멈추는 앞 넷):
```bash
E=/app/docker/runtime_entry.sh                              # 실행 이미지의 시작 스크립트(운영 이미지는 /app/docker/entrypoint.sh)
docker exec data-pipeline-0 bash $E tool check_env          # FAIL 줄이 없어야 함
docker exec data-pipeline-0 bash $E tool ping_models        # 모델 주소 연결
docker exec data-pipeline-0 bash $E migrate check --target all   # DB 표 판이 끝 판
bash deploy/release/selftest_gate.sh docker run --rm --network host \
  -v $B/settings.yaml:/etc/rag/settings.yaml:ro,z -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=dev \
  -v $B:/app/deploy:ro,z data-pipeline-runtime:<이미지 판> selftest   # 예 <이미지 판> = 0.3.0 · 기대: [판정] 통과
```

**④ 검색·MCP 기능 시험**

검색만 볼 때(토큰·포트 없이 DB 검색):
```bash
docker exec data-pipeline-0 python -m mcp_server.cli.search_ask ask --source DEV-1 --k 3 --q "<처리한 문서에 있는 낱말>"   # 예 --q "보관 기간"
```
실제 클라이언트와 같은 길(HTTP — 벌 0의 `mcp-server-0`, 서버 8051):
```bash
curl -s http://127.0.0.1:8051/health                                 # 기대: {"ok":true,"ready":true,…}
docker exec data-pipeline-0 python -m mcp_server.cli.mcp_smoke --url http://<서버 IP>:8051/mcp --token "<토큰>" --source DEV-1 --q "<낱말>"   # 기대 끝 줄 MCP 바깥 호출 통과
docker exec data-pipeline-0 python -m validation.e2e.answer_gen --url http://<서버 IP>:8051/mcp --q "<질문>"                            # 답변 생성 점검(§3-3-4)
```
- `<토큰>` = settings.yaml `required.tokens.mcp_token` 값. 주소는 `search.server.mcp_allowed_hosts`에 적은 `<서버 IP>:8051`로 부른다(다른 Host는 거부).
- 벌 1이 자기 코드로 MCP를 시험할 때는 SSH 셸(`ssh -p 8021 root@<서버>`) 안에서 잠깐 연다 — `python -m mcp_server.main --set MCP_PORT=18771 --set MCP_HOST=127.0.0.1 & echo $! > /tmp/mcp.pid` → 같은 셸에서 `mcp_smoke --url http://127.0.0.1:18771/mcp …` → `kill $(cat /tmp/mcp.pid)`. 컨테이너 안에서만 보이고, 컨테이너를 다시 띄우면 사라진다.

**⑤ 타이머**(벌 0 폴더에서 — 새벽 배치 + MCP 살리기)
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh timers                 # 기대: "  씀  /etc/systemd/system/<단위>" 네 줄
systemctl list-timers 'data-pipeline-nightly*' 'mcp-server-keepalive*'   # 기대: 두 타이머의 다음 실행 시각
```

**⑥ 개발을 마치면** — 시험한 코드 폴더를 운영 이미지로 굽는다(아래 prd ①).

**⑦ 전체 e2e·성능·worker 수 시험** — 벌 0의 네 컨테이너가 운영과 같은 구성(검색 MCP·작업 컨테이너·Redis)이다. 전체 시험은 벌 0에서 한다. Redis 포트와 키 접두를 벌마다 나누지 않는다. worker·엔진·자원 설정은 [§1-3-1](#1-3-1-parse_document-redis-큐113).

### 0-3. prd — 운영 서버, 코드를 구운 이미지

운영 서버는 번호 없는 한 벌 폴더(`/home/sbl/sbl_data_parsing-main` — compose 파일의 `PRD_DIR`)이고 코드 폴더를 붙이지 않는다 — 코드(`edw_chain.yaml` 포함)는 이미지 안에 있다. `compose-prd.yml`이 `data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0`을 띄운다(묶음 이름 `sbl-prd`, 재시작 정책 `always`).

**① 굽기**(개발 서버에서 — 개발에 쓴 실행 이미지 판 + 시험한 코드 폴더 → 코드가 든 이미지)
```bash
cd <시험한 벌 폴더> && bash deploy/release/bake_prod_image.sh <실행 이미지 판>
#   예: cd /home/sbl/sbl_data_parsing-main-0 && bash deploy/release/bake_prod_image.sh 0.3.0
# 기대: 대상마다 [판정] 통과 → /var/tmp/bake/sbl_images/<VERSION>/(<VERSION> = 코드 폴더 VERSION 파일 값 — 예 0.3.1) 아래 조각·load.sh·BUILD.txt + code-<판>-<커밋>.tar.gz
```
조각 폴더와 코드 묶음을 운영 서버 공용 폴더로 옮긴다. 코드 묶음을 `sbl_data_parsing-main`에 풀어 쓴다(호스트 스크립트·compose 파일 자리 — 그 안의 `settings.yaml`·`output/`·`home/`을 compose가 붙인다).

**② 불러오기**(운영 서버)
```bash
cd /home/sbl && bash sbl_images/load.sh <VERSION>                # 예 <VERSION> = 0.3.1 · 굽기가 만든 sbl_images 폴더를 옮긴 자리
docker image ls | grep -E '^(data-pipeline|mcp-server) '        # 기대: 두 줄, TAG 칸에 <VERSION>(예 0.3.1)
```
- 이미지 판은 `compose-prd.yml`의 `${IMAGE_TAG:-<판>}` — 같은 판의 코드 묶음이면 기본값이 구운 판이다. 다르면 `deploy/host/compose/.env`에 `IMAGE_TAG=<VERSION>`.

**③ 띄우기** — PG·Redis → `data-pipeline-0` → (처음이면 DB 표 만들기 — [설치 순서 6번](#서버-설치-순서)) → 나머지(검색 MCP는 시작할 때 마스터 표를 읽음)
```bash
B=/home/sbl/sbl_data_parsing-main; cd $B
#   먼저 .env(코드 폴더 맨 위 — git 제외, chmod 600)에 REDIS_PASSWORD·PG_USER·PG_DB·PG_PASSWORD를 적는다(settings.yaml과 같은 값 — §6-6 ①)
docker compose --env-file .env -f deploy/host/compose/compose-pgvector.yml up -d    # 검색 DB(이미 떠 있으면 그대로) — DB 담당이 따로 둔 PG면 건너뜀
docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d       # Redis
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-0
bash deploy/host/scripts/host_ctl.sh up -d                          # 나머지 둘
bash deploy/host/scripts/host_ctl.sh ps                             # 기대: 세 줄 Up(mcp-data-parsing-0은 healthy)
```
- 컨테이너는 root로 뜬다. SSH: `ssh -p 8020 root@<서버 IP>`(data-pipeline-0) · `ssh -p 8050 root@<서버 IP>`(mcp-server-0) — [§6-6](#6-6-서버-묶음--compose-파일과-root-ssh).

**④ 점검** — `bash deploy/host/scripts/host_ctl.sh check` — 기대 마지막 줄 `[host_ctl check] 통과 — 7개`(운영 이미지는 코드 마운트 없이 selftest).

**⑤ 타이머 둘**(새벽 배치 + MCP 살리기) — `bash deploy/host/scripts/host_ctl.sh timers` — 기대 `  씀  /etc/systemd/system/<단위>` 네 줄(`<단위>` = data-pipeline-nightly.service 등 — 출력에 나오는 이름).

MCP 살리기 타이머(`mcp_keepalive.sh`)는 2분마다 `redis`(꺼졌으면 `compose-redis.yml`로 띄움 · 건강하지 않으면 restart) · `mcp-data-parsing-0`(꺼졌으면 `host_ctl.sh up -d`) · `mcp-server-0`(`http://127.0.0.1:8051/health`가 응답하지 않으면 떠 있는 컨테이너는 restart, 없으면 `host_ctl.sh up -d`)을 본다.

**⑥ 재부팅** — 운영의 앱 컨테이너와 PG·Redis는 `restart: always`라 docker 서비스가 다시 띄운다(`systemctl is-enabled docker` — 기대 `enabled`). 개발 서버의 앱 컨테이너는 `unless-stopped`(손으로 멈춘 것은 그대로 — `host_ctl.sh up -d`).

---

## 1. 새 서버 설치

서버 명령은 모두 **root 셸**의 코드 폴더에서 실행한다. 셸을 열면 먼저 `export DOCKER=docker`. 이미 돌고 있는 서버를 새 판으로 올리는 것은 §4다 — **0.1.0이 만든 DB에 `migrate up`을 그냥 하지 않는다**(검색 판 `0002_search`가 옛 표를 지움 — [§4-1](#4-1-먼저-알-것)).

### 1-1. 배포 단계

모드마다 이미지를 따로 빌드한다(이미지·코드·띄우는 법은 [README §1-3 실행 모드 표](../../README.md#실행-모드)). 순서는 셋이다.

| 단계 | 어디서 | 하는 일 | 확인 |
|---|---|---|---|
| ① 개발 이미지 만들기 | PC(`local`) | 실행 이미지 `data-pipeline-runtime`·`mcp-server-runtime`을 빌드 → 이 커밋 코드를 붙여 selftest → 통과하면 `stage_images.sh`로 조각을 만들어 개인 이미지 저장소 `jehunlee302/sbl_images`에 push(사람) — [§5-3](#5-3-pc에서--실행-이미지-만들기와-이미지-저장소에-올리기) | `build_ship.sh`의 `[판정] 통과` |
| ② 개발 서버에 띄우기 | 개발 서버(`dev`) | 이미지 저장소 zip을 받아 `load.sh <이미지 판>` → 코드 git zip을 공용 폴더에 풀어 벌 폴더 이름으로 바꾸고 `compose-dev.yml`이 그 벌 폴더를 `/app/deploy`에 붙여 띄움(`host_ctl.sh up -d` — [§1-5](#서버-설치-순서)). 코드만 바뀌면 새 코드 zip을 벌 폴더에 덮어씀([§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)) | `host_ctl.sh check` · e2e |
| ③ 운영 이미지 굽기·옮기기 | 개발 서버 → 운영 서버(`prd`) | 개발 서버에서 불러온 실행 이미지 위에 시험한 코드 폴더를 넣어 앱마다 코드가 든 이미지 `data-pipeline:<VERSION>`·`mcp-server:<VERSION>`를 다시 빌드(`bake_prod_image.sh`) → 조각을 운영 서버로 옮겨 `load.sh <VERSION>` → `host_ctl.sh up -d`(`compose-prd.yml` — 코드 폴더 마운트 없음) — [§5-4](#5-4-개발--운영--시험한-그대로-굽기) | 굽기의 `[판정] 통과` · 운영 `host_ctl.sh check` |

반입은 git 저장소 두 개를 **zip으로 받아** 공용 폴더에 푼다:
- 코드: `gigasamba/sbl_data_parsing`의 받을 판(태그·커밋). zip을 푼 폴더(`sbl_data_parsing-<판>`)를 벌 폴더 이름으로 바꾼 것이 코드 폴더다. zip은 `CODE_COMMIT`을 채운다(git clone은 안 채움 — 시작 로그의 커밋이 틀 그대로).
- 이미지: 비공개 `jehunlee302/sbl_images`. 판 폴더마다 실행 이미지를 분할한 조각과 `load.sh`가 있다.

운영 서버(`prd`)는 한 벌이고 세 컨테이너(`data-pipeline-0`·`mcp-data-parsing-0`·`mcp-server-0`)를 띄운다. 개발 서버(`dev`)는 개발자마다 벌을 하나씩 두고(벌마다 `data-pipeline-<번호>`), 공용 main 벌 0이 `mcp-server-0`·`mcp-data-parsing-0`도 띄운다(§2). 모두 `compose-<환경>.yml` 한 파일이 띄운다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)).

### 1-2. 폴더 배치

서버는 **공용 폴더 하나**(예 `/home/sbl/` — compose 파일의 `SBL_ROOT`) 아래에서 동작한다. 공용 폴더 바로 아래에 **이미지 폴더**(`sbl_images-main/` — 서버에 한 번 불러오면 모든 벌이 같이 씀)와 **벌 폴더**(한 벌 = 코드 zip을 푼 코드 폴더 하나)가 있다. 루트 = 코드 폴더 자체이고, 호스트 스크립트는 자기 자리에서 루트를 구한다. 코드 폴더 바로 아래에 코드와 함께 **설정 파일**(`settings.yaml`) **· PG·Redis 비밀번호**(`.env`) **· 결과 폴더**(`output/`) **· root 홈**(`home/`)이 있다 — 넷은 git·코드 zip에 없는 것이라 새 판을 덮어써도 남는다(§4-5). EDW 조인 사슬 `edw_chain.yaml`은 코드다(코드 폴더 맨 위 — git으로 고침).

```
<공용 폴더>/                                  ← 예 /home/sbl/
├── sbl_images-main/                         ← 공용 — load.sh · readme.md · <판>/BUILD.txt · <판>/<이미지>/*.tar.gz.part* + *.sha256(서버에 한 번 load)
├── sbl_data_parsing-main/                   ← 한 벌(운영 서버) = 코드 폴더 = 루트(코드 · edw_chain.yaml · VERSION · CODE_COMMIT · deploy/docker/DEPS_HASH)
│   ├── settings.yaml                        ← settings.sample.yaml을 host_ctl.sh init이 없을 때만 복사(비밀값 — 640)
│   ├── .env                                 ← PG·Redis 비밀번호(사람이 적음 — 600, git 제외 · compose-pgvector.yml·compose-redis.yml이 읽음)
│   ├── output/                              ← 결과 폴더(host_ctl.sh init이 만듦 — 컨테이너 안 /app/output · 파싱 캐시가 있어 잃으면 전부 다시 처리 · 아래 _ 붙은 폴더는 임시 자리)
│   │   ├── _docflow/<번호>/  _staging/  _faq_seen.txt  _mcp_parse/jobs/  _llm_spend/
│   │   └── logs/                            ← DB 로그를 못 쓸 때의 예비 파일만
│   ├── home/                                ← root 홈(컨테이너 /root — SSH 호스트 열쇠·git 계정·작업 기록 · home/mcp = mcp-server-0 홈 · 처음 띄울 때 생김)
│   └── deploy/host/scripts/test_space/      ← run_pipeline 진행 기록(batch_progress/)
├── sbl_data_parsing-main-0/                 ← (개발 서버) 벌 0 — 검색 MCP·작업 컨테이너도 이 벌(§2-1)
└── sbl_data_parsing-main-1/                 ← (개발 서버) 벌 1
```

검색 DB 데이터(`/data/pg/pipeline` — `PG_DATA`)와 Redis 데이터(`/data/redis` — `REDIS_DATA`)는 벌 폴더 밖이라 판이 바뀌어도 그대로이고, 모든 벌이 같은 기준 스키마(`required.pg.pg_schema`)를 함께 쓴다.

### 1-3. 미리 있어야 하는 것

서버에서 한 번 확인한다.

| 무엇 | 확인 명령 | 없으면 |
|---|---|---|
| Docker Engine과 compose 플러그인 | `docker version`(`Server: Docker Engine` 줄이 있어야 함 — `podman-docker` 꾸러미의 가짜 `docker`면 `Server:` 줄이 podman) · `docker compose version` | 서버 관리자에게 설치를 요청한다(폐쇄망은 `docker-ce`·`docker-ce-cli`·`containerd.io`·`docker-compose-plugin` rpm을 반입해 `dnf install ./*.rpm`) |
| docker 서비스가 부팅 때 켜짐 | `systemctl is-enabled docker` — 기대 `enabled` | `systemctl enable --now docker`(재부팅 때 컨테이너를 다시 띄우는 것이 이 서비스) |
| 호스트 python 3.9 이상과 PyYAML | `python3 --version` · `python3 -c 'import yaml'` | 3.9 이상은 서버 관리자에게 요청한다(호스트 스크립트가 읽는 `common/config/layout.py`가 3.9 문법을 씀 — RHEL 8의 기본 `python3`는 3.6). PyYAML은 `dnf install python3-pyyaml` |
| unzip | `unzip -v` | `dnf install unzip` |
| PostgreSQL 16 + pgvector, 우리 DB·계정 | DB 담당에게 확인 · `docker ps --filter name=pgvector` | DB 담당이 만들거나, 이 서버에 직접 띄운다([§1-4](#서버-pg-띄우기)). 확인할 것 셋: ① PG가 **이 서버에 컨테이너로** 떠 있다(백업·문서 수 세기가 그 컨테이너 안에서 `psql`을 씀 — 이름을 `required.deploy.pg_container_name`에 적음) ② 계정에 그 DB의 **스키마 만들기 권한**이 있다(`GRANT CREATE ON DATABASE <DB> TO <계정>` — `migrate up`이 `<pg_schema>`·`<pg_schema>_master`·`<pg_schema>_<원천>`·`applog`를, 개발 서버의 배포 판정 시험이 임시 `test_*`를 만듦) ③ `vector` 확장(관리자가 한 번 — [§1-8](#1-8-db-표-만들기--migrate) 0번) |
| 운영 그룹 | `id -gn <운영 계정>` · `getent group <그룹>` | 서버 관리자에게 받는다 |

**컨테이너 도구는 docker 하나로 쓴다.** 셸을 열면 먼저 `export DOCKER=docker`(운영 계정 `~/.bashrc`에 두어도 됨), settings.yaml에 `ops.host.container_cli: docker`. 일반 사용자 셸이면 `DOCKER="sudo docker"`. 같은 서버에 podman도 있으면 이미지를 podman에 불러오지 않는다(두 도구는 이미지를 따로 보관 — docker로 띄우면 podman에 넣은 이미지는 안 보임).

### 1-3-1. parse_document Redis 큐(#113)

앱 이미지 2개 외에 Redis(`compose-redis.yml` — 공식 `redis:7.4.8-alpine`, 컨테이너 `redis`, 서버마다 하나, 서버 8010)를 우리가 운영한다 — 띄우는 법·비밀번호는 [§6-7](#6-7-redis--compose-redisyml). 작업 폴더 `<결과 폴더>/_mcp_parse/jobs`는 `host_ctl.sh init --group <운영 그룹>`이 만든다(2775). 검색 MCP(`mcp-server-0`)는 결과 폴더를 읽기 전용으로, jobs만 쓰기 가능으로 붙인다. 작업 컨테이너는 0번 벌의 `mcp-data-parsing-0` 하나다.

현재 worker는 기본 2개이며 허용 범위는 1~2다. 상한을 늘릴 때는 CPU·메모리·worker마다 엔진 수를 함께 조정한다.

| 자원 칸 | 기본 | 산정·확인 |
|---|---|---|
| `ops.services.data_parsing.mcp_parse_workers` | 2(최대 2) | 독립 spawn 소비자 |
| `tuning.ops.services.data_parsing.mcp_parse_engine_processes` | 비움 | worker마다 max(1, min(2, CPU − 1)), 보통 2 × 2 = 총 엔진 4개 |
| compose 파일 `mcp-data-parsing-0`의 `cpus` | 4 | CPU 상한이며 예약이 아님 |
| 같은 칸 `mem_limit` | 12g(PC `compose-local.yml` 8g) | worker 2개와 엔진 자식에 필요한 메모리 여유 확인 |
| 같은 칸 `cpu_shares` | 4096 | 일괄 `data-pipeline-0`(1024)보다 CPU 우선순위가 높음 |

docker는 서버 CPU 수보다 큰 `cpus`를 거부한다. 4 CPU 미만이면 compose 파일의 `cpus`를 서버 이하로 낮추고 `mcp_parse_engine_processes`를 1로 적는다. `cpus=4`는 CPU 예약이 아니며 경합 때 `cpu_shares`가 우선순위를 정한다. 메모리는 컨테이너 상한 12g 외에 두 앱·Redis·호스트 여유까지 합산한다.

```bash
bash deploy/host/scripts/host_ctl.sh ps                                       # mcp-data-parsing-0 … (healthy)
$DOCKER exec mcp-data-parsing-0 python -m pipeline.run_mcp_parsing --health
$DOCKER exec -it redis redis-cli                                              # 들어가서 AUTH <비밀번호>(손으로) → 아래 명령
#   SCARD mcp_parse:active · XPENDING mcp_parse:queue mcp_parse:workers · HGETALL mcp_parse:job:<job_id>
```

비밀번호는 셸 명령 인자·로그에 적지 않는다 — 위처럼 `redis-cli` 안에서 `AUTH`로 친다. 접두는 설정값 그대로 사용한다(자동 접미사 없음). `KEYS *`·FLUSHALL 대신 해당 접두의 SCAN을 쓴다.

AOF 데이터는 `REDIS_DATA`(기본 `/data/redis`)에 남는다. `compose-redis.yml`이 코드 폴더 맨 위 `.env`의 `REDIS_PASSWORD`로 `redis-server --requirepass …`(`protected-mode yes` · `bind 0.0.0.0` · AOF)를 띄운다 — 공식 entrypoint가 Redis 계정으로 내린다. 데이터 폴더는 Redis 전용이며 운영 계정이 쓰지 않는다. 비밀번호를 바꾸면 `.env`·settings.yaml을 같이 고치고 Redis `up -d --force-recreate` 뒤 두 앱도 `host_ctl.sh restart mcp-server-0 mcp-data-parsing-0`(새 비밀번호를 읽게). AOF everysec는 장애 시 최근 약 1초 쓰기를 잃을 수 있다. 완료 STREAM 항목은 XACK+XDEL로 제거하고, AOF는 Redis 기본 auto-rewrite(100% 증가·최소 64MB)를 사용하므로 디스크 여유를 살핀다. 완료 HASH·LIST는 기본 하루 TTL, 폴더는 수정 시간순 최근 30개를 남기되 active와 최근 10분 폴더는 등록 전 업로드까지 보호한다. 미완료 작업은 pending에서 회수되며 최대 전달 횟수를 넘으면 failed 알림을 준다.

MCP 살리기(`mcp_keepalive.sh`)는 Redis·작업 컨테이너 기동이 실패해도 검색 MCP 확인과 재기동을 계속한다. parse health는 컨테이너 로컬 임시 폴더의 supervisor 식별자를 읽고 그 소비자의 heartbeat만 확인하므로 다른 컨테이너를 정상으로 오인하지 않는다.

상태 흐름: queued → running → done/failed/rejected. 완료 알림 전에 result-<attempts>.json을 쓴다. 제한 시간 응답을 받아도 worker는 작업을 계속한다. `service.json`에는 supervisor PID·Redis host:port·worker 수만 적고 비밀번호는 넣지 않는다. 작업·대기·파싱 추적과 `perf_report --mcp`는 §3-4-1을 따른다.

parse_document 회수 보강(#177): 종료 확인·running 소유권 변경은 WATCH로 묶고, 시도별 `a<n>/`에서 파싱한 뒤 HASH의 `result_file` 이름으로 결과를 읽는다. 배포 전환 중 옛 전체 경로의 마지막 요소가 result.json이면 받은 경로를 열지 않고 자기 job 폴더의 result.json만 읽는다(다음 판 제거, C-118). heartbeat 없음 연속 30초 + idle 60초를 모두 확인한 소비자는 한 건씩 회수하며, 살아 있지만 멈춘 소비자는 기존 (job_timeout+60)초 XAUTOCLAIM으로 회수한다. 손상된 HASH는 failed로 끝내고 일반 worker 오류는 traceback으로 기록한다.

parse_document 빠른 거절·제출 복구(#177): worker가 확장자·허용 루트(설정 경로의 normpath와 resolve된 실제 경로 모두)·크기 정책을 시작 때와 10초 heartbeat마다 Redis에 TTL 120초로 공개한다. proxy는 정책이 있으면 확장자와 정규화한 절대경로를 폴더 생성 전에 검사한다(존재·실제 크기·심볼릭 링크는 worker가 검사). 정책이 없으면 제출한다. 제출 EXEC 응답이 유실되면 새 EXISTS로 등록 여부를 확인해 등록된 작업은 계속 기다리고, 미등록이 확실할 때만 폴더를 지운다. 확인도 실패하면 폴더를 보존하고 job_id와 연결 오류 끝에 “— 제출 여부 확인 불가(job_id로 수집 서버 담당자 확인)”를 반환한다. 제출 전 연결 실패에는 job_id를 붙이지 않는다.

Redis 인증(#177): `common.connections.redis.redis_password`는 모든 서버에 반드시 채운다(기본값 없음 — 서버마다 새로 만든 값). 비움·공백은 앱 client가 거부하며(`.env`의 `REDIS_PASSWORD`가 비면 compose가 멈춤) worker 시작은 종료 코드 2다. Redis는 서버의 모든 주소(`0.0.0.0:8010`)에 열리므로 `protected-mode yes`와 비밀번호를 함께 쓴다. 비밀값 처리 변경은 검토 등급 A로 다른 사람의 승인이 필요하다(C-117).
<a id="서버-pg-띄우기"></a>
### 1-4. 서버 PG(pgvector) 띄우기

이 서버에 PG를 직접 띄울 때만 한다(DB 담당이 이미 띄웠으면 건너뛰고 접속 정보만 받는다). `compose-pgvector.yml` 한 파일이다(컨테이너 `pgvector`, 서버 `0.0.0.0:5433` → 컨테이너 5432, 재시작 정책 `always`). root 셸에서 차례로 친다 — 코드 폴더(`<루트>`)의 settings.yaml에 `required.pg.pg_password`·`common.connections.redis.redis_password`를 먼저 채운다(설치 순서 4번).
```bash
# ① (인터넷 PC에서) 이미지를 파일로 만든다 → 서버로 옮긴다
docker pull pgvector/pgvector:pg16 && docker save pgvector/pgvector:pg16 -o pgvector_pg16.tar

# ② (서버) 이미지 불러오기
docker load -i pgvector_pg16.tar                               # 기대: Loaded image: pgvector/pgvector:pg16

# ③ 데이터 폴더(컨테이너를 지워도 DB는 여기 남음 — 비어 있으면 처음 시작 때 DB를 만든다)
mkdir -p /data/pg/pipeline

# ④ 계정 — 코드 폴더 맨 위 .env(git 제외)에 settings.yaml과 같은 값을 손으로 적는다(값에 $·따옴표·줄바꿈 없음)
cd <루트> && vi .env && chmod 600 .env                        # PG_USER=rag · PG_DB=rag · PG_PASSWORD=<pg_password> · REDIS_PASSWORD=<redis_password>

# ⑤ 띄우기·기다리기
docker compose --env-file .env -f deploy/host/compose/compose-pgvector.yml up -d
until docker exec pgvector pg_isready -h 127.0.0.1 -U rag -d rag; do sleep 1; done   # 기대: 127.0.0.1:5432 - accepting connections
#   -h 127.0.0.1을 꼭 준다 — 처음 띄울 때 PG가 초기화용 서버를 잠깐 띄우는데, -h 없이 물으면 그때도 "준비됨"이 나와 ⑥이 "database does not exist"로 실패한다

# ⑥ vector 확장(DB마다 한 번)
docker exec pgvector psql -U rag -d rag -c 'CREATE EXTENSION IF NOT EXISTS vector'   # 기대: CREATE EXTENSION
```
- settings.yaml에 같은 값을 적는다: `required.pg.pg_host: host.docker.internal`(컨테이너에서 서버 자신) · `pg_port: 5433`(서버 쪽 포트) · `pg_database: rag` · `pg_user: rag` · `pg_password`(④의 `.env`와 같은 값) · `required.deploy.pg_container_name: pgvector`. 서버 바깥(DB 도구)에서는 `<서버 IP>:5433`.
- `POSTGRES_USER`로 만든 계정은 관리자 계정이라 스키마 만들기 권한이 있다.
- 메모리 값(`shared_buffers` 등)·`shm_size`·`cpus`·`mem_limit`은 파일 안 주석대로 서버 메모리에 맞춰 고친다.
- `.env`의 계정·비밀번호는 데이터 폴더가 비어 있을 때(처음)만 쓰인다. 비밀번호를 바꾸려면 `docker exec -it pgvector psql -U rag -d rag`에 들어가 `\password rag` 뒤 `.env`·settings.yaml 값을 같게 고친다.
- `.env`의 비밀번호는 환경 변수로 넘어가 `docker inspect`에 보인다 — 서버 root·docker 권한자만 볼 수 있다.
- 데이터를 다른 폴더에 두려면 셸에서 `PG_DATA=<폴더>`를 주고 띄운다(내릴 때도 같은 값).

<a id="서버-설치-순서"></a>
### 1-5. 서버 설치 순서

처음 한 번 — root 셸, `<루트>` = 벌 폴더 = 코드 폴더. 개발 서버에서 자기 벌을 만드는 사람은 같은 일을 단계마다 `cd`·성공 출력과 함께 적은 §2를 따른다.

0. `export DOCKER=docker` — [§1-3](#1-3-미리-있어야-하는-것)을 확인한다.
1. 공용 폴더를 만들고 이미지 zip과 코드 zip을 거기에 푼 뒤, 코드 폴더 이름을 벌 폴더 이름으로 바꾼다.
   ```bash
   mkdir -p /home/sbl && cd /home/sbl                # 공용 폴더(자리는 아무 곳)
   unzip -q <이미지 zip> && unzip -q <코드 zip>       # 기대: sbl_images-main/ · sbl_data_parsing-<판>/
   mv sbl_data_parsing-<판> sbl_data_parsing-main    # 운영 서버 — 한 벌, 번호 없음(compose-prd.yml의 PRD_DIR 기본값)
   B=/home/sbl/sbl_data_parsing-main                  # 아래 <루트> — 새 셸을 열면 다시 적는다
   ```
   개발 서버는 벌 폴더 이름 끝에 번호를 붙인다 — 공용 main `sbl_data_parsing-main-0`, 개발자 `-1`(`compose-dev.yml`이 이 이름으로 붙인다 — §2-1).
2. 이미지를 불러온다(공용 폴더에서 — 서버에 한 번, 이미 불러온 판이면 건너뜀). `<이미지 판>`은 `ls sbl_images-main/`에 보이는 판 폴더 이름이다: `cd /home/sbl && DOCKER=docker bash sbl_images-main/load.sh <이미지 판>` — 조각 sha256 확인 → 합치기 → load, 끝에 `<판>/BUILD.txt`(빌드 커밋·DEPS_HASH). **코드의 `deploy/docker/DEPS_HASH`가 `BUILD.txt`의 DEPS_HASH와 같은 판**을 고른다(확인 명령 — [README §1-3](../../README.md#실행-모드)).
3. 루트 채우기: `cd <루트> && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>` — `output/`·`output/_mcp_parse/jobs`(UID 10001, 2775), 코드 a+rX(`settings.yaml`·`output/`·`home/`은 빼고), `settings.sample.yaml` → `<루트>/settings.yaml`(없을 때만, 10001:<운영 그룹> 640). 끝에 빈 필수 칸 **이름**을 찍는다. 여러 번 불러도 안전하다.
4. 설정을 채운다 — `<루트>/settings.yaml` 맨 위 `required`의 빈 값([§1-6 꼭 채울 값](#꼭-채울-값)). 띄울 이미지 판은 compose 파일의 `IMAGE_TAG`(기본값 — 다르면 파일 옆 `.env`에 `IMAGE_TAG=<판>`)가 정한다. 자원 상한은 compose 파일에 있다([§1-10](#1-10-자원)). 다 채우면 같은 PG·Redis 비밀번호를 코드 폴더 맨 위 `.env`(`REDIS_PASSWORD`·`PG_USER`·`PG_DB`·`PG_PASSWORD`, 600)에 적고 PG·Redis를 띄운다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh) ①).
   - **개발 서버**는 `required.source.source_systems: DEV-<번호>`를 적는다(여러 개는 쉼표 — `DEV-1, DEV-2`) — 비우면 운영 5개 원천 전부를 파싱한다.
   - 운영 기준 결과를 내려면 `transform.represent.post_steps: all`([env-guide "서버 값으로 적는 칸"](env-guide.md)).
   - `required.deploy.host_docs_dir`는 서버에 **이미 있는 폴더**여야 한다(없으면 `mkdir -p` 후 UID 10001이 읽을 수 있게).
   - `init`이 찍는 "빈 필수 칸" 목록에는 비워도 되는 칸(`source_systems`·모델 `*_api_key` 등 — sample 주석 `[선택]`)도 섞여 있다. 무엇을 꼭 채울지는 §1-6 표로 판단한다.
   - 다 적은 뒤 칸 이름이 맞는지 한 번 읽어 본다 — [env-guide §4 "칸 이름 확인"](env-guide.md#4-확인)(기대 `설정-읽힘`). 틀린 칸이 있으면 5번에서 모든 컨테이너가 시작을 거부한다. 빠른 확인은 `bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK`.
   - EDW 표 설명 자료(`catalog.json`·`columns.jsonl` — 개인정보 없는 자료, 받는 곳은 refactor.md C-91)를 루트 아래 결과 폴더에 복사하고(`<루트>/output/edw_meta/`, UID 10001이 읽을 수 있게) `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`를 적는다. 없으면 `edw_meta` 도구만 `not_configured`로 답한다(나머지 도구는 그대로 — [§3-8-1](#3-8-1-edw-쿼리-도구-설정--edw_metaquery_edw)).
5. `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-0`(코드 폴더에서 — DB 도구가 그 안에서 돈다).
6. DB 표를 만든다 — [§1-8](#1-8-db-표-만들기--migrate)의 명령(검토용 SQL → `migrate up` → `migrate master load` → `migrate check`).
7. `bash deploy/host/scripts/host_ctl.sh up -d`(나머지 앱 컨테이너 — 검색 MCP는 시작할 때 마스터 표를 읽으므로 6 뒤).
8. `bash deploy/host/scripts/host_ctl.sh check` — .env 일치(`.env` = settings.yaml, 다른 이름만) → check_env → ping_models → migrate check → 이미지 selftest 둘 → 검색 MCP `/health`, 처음 실패에서 멈춘다. 기대 마지막 줄: `[host_ctl check] 통과 — 7개`. 단계별 뜻은 [§2-7](#2-7-전체-점검--host_ctlsh-check).
9. 첫 실행을 확인한다.
   - 판: `bash deploy/host/scripts/host_ctl.sh logs data-pipeline-0 2>&1 | grep -m1 '^\[image\]'` — 기대 `[image] 이미지 … · 코드 <커밋> · 의존성 …`.
   - 게시 미리보기: `bash deploy/host/scripts/pipe_exec.sh publish --dry-run`(쓰기 0 — [§1-9](#1-9-연결이미지-점검)).
   - 문서 2건: [핵심 명령](#핵심-명령) "파이프라인 한 번(시험 2건)" — 기대 `progress.log` 끝 줄 `… 종료 코드 0 ===`.
   - 검색: `mcp_smoke`([§3-8](#3-8-검색-mcp-사용)) — 기대 끝 줄 `MCP 바깥 호출 통과`. 개발자 벌은 `data-pipeline-<번호>` 안 `search_ask`([§2-10](#2-10-검색-확인)).
10. 자동 실행을 켠다 — `bash deploy/host/scripts/host_ctl.sh timers`([§3-1](#3-1-상주-컨테이너와-자동-실행)). 다른 서버의 AI 클라이언트가 붙어야 하면 [§1-11](#1-11-밖에서-붙기다른-서버의-ai-클라이언트).

<a id="꼭-채울-값"></a>
### 1-6. 꼭 채울 값과 포트

**꼭 채울 값 — 서버 settings.yaml.** "형식 예"는 모두 가짜 값이다. dev = 개발 서버, prd = 운영 서버.

| 칸 | 무엇 | 어디서 받나 | 형식 예(가짜) | 환경 | 틀리면 어디서 잡나 |
|---|---|---|---|---|---|
| `required.env.run_env` | 실행 환경 | 정해진 값 | `dev` · `prd` | PC·dev·prd | 모든 명령이 시작 거부 |
| `required.pg.pg_host`·`pg_port`·`pg_database`·`pg_user`·`pg_password`·`pg_schema` | 검색 DB(pgvector) — `pg_schema`는 비우면 `data_parsing` | DB 담당 · 이 서버에 띄우면 [§1-4](#서버-pg-띄우기) | `host.docker.internal` · `5433` · `rag` · `rag` · `<비밀>` · (비움) | PC·dev·prd | `host_ctl.sh check` ① check_env · ③ migrate check |
| `required.models.embed_base_url`·`embed_model`·`embed_api_key` | 임베딩 모델(`embed_model`은 적재·검색 때 같아야 함) | 모델 담당(내부망 주소) | `http://llm.example.local:8000/v1` · `<모델>` · `<비밀>` | PC·dev·prd | `host_ctl.sh check` ② ping_models |
| `required.models.llm_*`·`vlm_*` | LLM·VLM 모델 | 모델 담당 | `http://llm.example.local:8001/v1` · `<모델>` | dev·prd | `host_ctl.sh check` ② ping_models |
| `required.edw.edw_host`·`edw_port`·`edw_database`·`edw_read_*` | 회사 DB(EDW) 접속 — 읽기 계정(원천 목록·`query_edw`, EDW는 읽기만 함 — 쓰기 계정 칸은 없음) · `edw_port`는 비우면 1433 | DB 담당 | `edw.example.local` · (비움) · `EDW` · `<계정>` · `<비밀>` | dev·prd | `run_pipeline` 시작(빠지면 칸 이름을 찍고 멈춤) · `pipe_exec.sh publish --dry-run`(§1-9) |
| `required.edw.edw_file_table` | 파싱 대상 파일 목록을 읽을 EDW 표(`<스키마>.<표>` — 영문·숫자·_만) · 기본 `AI.FileStorageMap` | DB 담당 | `AI.FileStorageMap` | dev·prd | 설정을 읽을 때(꼴이 틀리면 시작 거부) · `run_pipeline` 대상 목록 |
| `dev.local.*` | PC 전용 값(가짜 EDW·게시 폴더·원본 폴더·새 문서 상한) — **서버는 읽지 않음**(`local_edw_sqlite_file`이 적혀 있으면 EDW를 쓸 때 거부) | — | (sample 그대로) | PC만 | — |
| `required.publish.publish_bucket`·`publish_prefix` | silver 게시 위치 — 버킷(원천 원본 버킷과 달라야 함)과 그 안 경로 접두. **둘 다 비우면 안 된다**(sample은 `publish_prefix`를 `[선택]`으로 적지만 `run_pipeline`은 비면 `설정 필요`로 멈춤). PC는 `publish_bucket` 대신 `dev.local.local_publish_dir` | 운영 담당 | `rag-silver` · `parse` | dev·prd | `run_pipeline` 시작 · publish 미리보기 |
| `required.object_storage.object_storage_endpoint`·`object_storage_access_key`·`object_storage_secret_key` | Object Storage(S3 호환) 접속 | 스토리지 담당 | `https://os.example.local:9000` · `<비밀>` · `<비밀>` | dev·prd | `run_pipeline` 시작 · publish `--apply` |
| `common.connections.object_storage.object_storage_region`·`object_storage_verify_tls` | 리전(비우면 `us-east-1`)·TLS 검증(비우면 `1` — 사내 CA면 CA 파일 경로). **`required` 아래가 아니다** | 스토리지 담당 | (비움) · (비움) | dev·prd | 설정을 읽을 때(자리가 틀리면 시작 거부) |
| `extract.source.source_input_location`·`source_default_bucket`·`source_uri_prefix` | 원본 위치 — `source_default_bucket`은 서버에서 **필수**(`run_pipeline`이 비면 멈춤) | 운영 담당 | `rdb:csv:<루트>/list.csv` · `<버킷>` · `s3://<버킷>/<접두>` | dev·prd | 첫 `run_pipeline` |
| `required.tokens.mcp_token` | MCP 토큰 하나 — 검색 MCP 외부 호출 인증에 씀(내부 전달은 Redis 권한) | `openssl rand -hex 32` | 64자 16진수 | dev·prd | `host_ctl.sh check` ⑥ `/health` · `parse_document` 호출이 토큰 오류 |
| `required.tokens.fulltext_sign_key` | 원문 도구(`list_doc_fulltext`·`get_doc_fulltext`)의 `sfid` 서명 키 — 비우면 두 도구가 `not_configured`, 바꾸면 이미 발급한 sfid가 모두 무효 | 같은 명령 | 64자 16진수 | dev·prd | 원문 도구 호출이 `not_configured` |
| `common.connections.redis.redis_password` | `parse_document` 작업 큐(Redis) 비밀번호 — 코드 폴더 맨 위 `.env`의 `REDIS_PASSWORD`와 같은 값(compose-redis.yml이 읽음). `redis_host`·`redis_port`는 비움(기본 `host.docker.internal`·`8010`) | `openssl rand -hex 32` | 64자 16진수 | dev·prd | `redis` 컨테이너 상태 검사 · `parse_document` 호출 |
| `search.server.mcp_bind_host` · `mcp_port` · `mcp_allowed_hosts` | 검색 MCP 바인드·컨테이너 안 포트·허용 Host(벌 0 — 운영은 그 한 벌) | 정해진 값 · 서버 관리자 | `auto` · `8051` · `<서버 IP>:8051` | dev·prd | `host_ctl.sh check` ⑥ `/health` |
| `required.deploy.host_docs_dir` | 원본 문서 폴더(서버에 이미 있는 폴더 — compose 파일의 `DOC_SRC`로 넘어감) | 서버 관리자 | `/data/docs` | dev·prd | `host_ctl.sh up`이 `:?` 안내로 멈춤 |
| `required.deploy.pg_container_name` | `pg_dump`·`psql`을 exec할 PG 컨테이너 이름 | DB 담당 | `<컨테이너>` | dev·prd | 백업 명령([§4-3](#4-3-백업)) |
| `ops.host.container_cli` | 컨테이너 도구 | 정해진 값 | `docker` | dev·prd | 호스트 스크립트가 다른 도구를 부름 |

그 밖 칸은 비워 두면 코드 기본값을 쓴다([env-guide "서버 값으로 적는 칸"](env-guide.md)도 본다). 모델 주소는 모두 내부망 주소여야 한다.

**포트 — 서버(바깥) 포트는 compose 파일 `ports` 칸**

| 무엇 | 서버 → 컨테이너 | 정하는 곳 | 누가 붙나 |
|---|---|---|---|
| SSH — `data-pipeline-0` · `data-pipeline-1`(개발) | 8020 · 8021 → 22 | compose 파일 `ports` | 개발자(root 비밀번호) |
| SSH — `mcp-server-0` | 8050 → 22 | 같음 | 개발자·운영자 |
| 검색 MCP | 8051(안팎 같음) | compose 파일 `ports` · 컨테이너 안 포트 `search.server.mcp_port: 8051`(바인드 `mcp_bind_host: auto`) | AI 클라이언트 · `mcp_keepalive.sh`(`127.0.0.1:8051/health`) |
| PostgreSQL(pgvector) | 5433 → 5432 | `compose-pgvector.yml` · 앱 `required.pg.pg_port: 5433` | 파이프라인·검색 MCP(`host.docker.internal`) · DB 도구 |
| Redis | 8010 → 6379 | `compose-redis.yml` · 앱 `common.connections.redis.redis_port`(기본 8010) | 검색 MCP·작업 컨테이너(`host.docker.internal`) |
| EDW(SQL Server) | — | `required.edw.edw_port`(주소·계정도 `required.edw`) — 기본 1433 | 파이프라인·`query_edw` |
| 검증 페이지(PC만) | — | `dev.search_ui.search_ui_port` — 기본 8790 | 사람(브라우저) |

포트는 서버의 모든 주소(`0.0.0.0`)에 열린다. 컨테이너는 docker 자체 네트워크(bridge)에 있어 컨테이너 안 `127.0.0.1`은 컨테이너 자신이다 — 서버에 있는 PG·Redis·모델은 `host.docker.internal`(compose `extra_hosts`)로 붙는다. 서버 방화벽은 밖에서 붙을 포트만 연다(예 8051 — [§1-11](#1-11-밖에서-붙기다른-서버의-ai-클라이언트)).

<a id="핵심-명령"></a>
<a id="compose-파일-읽는-법"></a>
### 1-7. 컨테이너 다루기 — `host_ctl.sh`와 핵심 명령

서버에서는 앱 컨테이너를 `docker run`으로 따로 띄우지 않는다. 이미지 불러오기는 `load.sh`, 앱 컨테이너는 `deploy/host/scripts/host_ctl.sh`가 맡는다 — settings.yaml `required.env.run_env`의 compose 파일(`deploy/host/compose/compose-<run_env>.yml`)로 `docker compose -f <그 파일> <인자…>`를 그대로 부른다(`up -d`·`ps`·`logs`·`stop`·`down`·`config`·`restart`). PG(`compose-pgvector.yml`)·Redis(`compose-redis.yml`)는 코드 폴더 맨 위에서 `docker compose --env-file .env -f deploy/host/compose/<그 파일> up -d`로 따로 띄운다(`down`·`logs`·`ps`도 `--env-file .env`를 붙인다)([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)). 컨테이너 도구는 셸 `DOCKER`(없으면 `ops.host.container_cli`). 서비스 이름 = 컨테이너 이름(`data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0` …). 서비스를 빼고 `up -d`하면 그 파일의 앱 컨테이너를 모두 띄운다.

**compose 파일 읽는 법**(`deploy/host/compose/*.yml`)
- 맨 위 `x-dev:`·`x-prd:`·`x-ssh:`·`x-local:`은 서비스가 아니라 함께 쓰는 YAML 조각이다(재시작 정책·root·`host.docker.internal`·로그 상한 — 서비스 칸의 `<<: *dev`가 그 조각을 붙임).
- 이름·이미지·포트·`cpus`·`mem_limit`·볼륨은 파일에 직접 적혀 있다. `${IMAGE_TAG:-0.4.0}` 같은 자리만 셸 env나 파일 옆 `.env`로 바꾼다 — `IMAGE_TAG`(이미지 판) · `SBL_ROOT`(공용 폴더 — 기본 `/home/sbl`) · `PRD_DIR`(운영 폴더) · `DOC_SRC`(원본 문서 폴더 — `host_ctl.sh`가 settings.yaml `required.deploy.host_docs_dir`에서 냄) · `PG_DATA`·`REDIS_DATA`(데이터 폴더).
- 파일을 고친 뒤 `host_ctl.sh up -d`가 바뀐 컨테이너만 다시 만든다. compose 파일은 코드라 git으로 커밋한다(§6-4).
- `nightly_batch.sh`·`pipe_exec.sh`·`mcp_keepalive.sh`·systemd unit은 `<루트>/settings.yaml`을 스스로 찾는다.

**핵심 명령**(root 셸 · `<루트>` = 벌 폴더 = 코드 폴더 · 아래 스크립트는 `deploy/host/scripts/`에 있다)

| 하고 싶은 일 | 들어갈 폴더(`cd`) | 명령 | 성공하면 보이는 것 |
|---|---|---|---|
| 이미지 불러오기(서버에 한 번) | 공용 폴더(`/home/sbl`) | `bash sbl_images-main/load.sh <이미지 판>` | `== <이미지> — load` 줄들 → `BUILD.txt` 내용 → `== 끝 — compose 파일(…)의 IMAGE_TAG가 위 판인지 확인…` |
| 벌 폴더 처음 채우기 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>` | `[host_ctl init] 루트: …` → `만듦 …settings.yaml` 등 → 빈 필수 칸 **이름** 목록 |
| PG·Redis 비밀번호 | `<루트>` | `vi .env && chmod 600 .env`(`REDIS_PASSWORD`·`PG_USER`·`PG_DB`·`PG_PASSWORD` — settings.yaml과 같은 값) | `ls -l .env` → `-rw-------` |
| 설정·compose 확인(값은 안 찍음) | `<루트>` | `bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK` | `설정 OK` |
| 띄우기 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh up -d` | 아래 `ps`에 앱 컨테이너(운영 셋 · 개발 넷) `Up` |
| 상태 · 로그 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh ps` · `… logs --tail 100 data-pipeline-0` | 그 compose 파일의 컨테이너만 · 그 컨테이너 로그 |
| 전체 점검 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh check` | 마지막 줄 `[host_ctl check] 통과 — 7개` |
| DB 표 만들기(처음 한 번 — 공용 DB) | `<루트>`(`data-pipeline-0`이 떠 있어야 함) | [§1-8](#1-8-db-표-만들기--migrate) 순서 — 검토용 SQL → `migrate up --target all --dim <임베딩 차원>` → `migrate master load` → `migrate check` | `[migrate] <갈래> <스키마>: 판 [...] (끝 …)` · `[pipe_exec] … 끝 (종료 코드 0)` |
| DB 담당 검토용 SQL(DB에 붙지 않음) | `<루트>` | 위 `migrate up` 명령 끝에 `--sql /app/output/up.sql` | `[migrate] SQL → /app/output/up.sql (DB에 붙지 않음 — …)` — 호스트에서는 `<루트>/output/up.sql` |
| 파이프라인 한 번(시험 2건) | `<루트>` | `nohup python3 deploy/host/scripts/run_pipeline.py --limit 2 > run_first.out 2>&1 &` | `deploy/host/scripts/test_space/batch_progress/progress.log` 끝 줄 `=== 문서별 flow 끝: 2건(완료 2 · …) · … · 종료 코드 0 ===` |
| 설정을 바꾼 뒤 | `<루트>` | `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate <서비스…>`(그냥 `up -d`는 settings.yaml만 바뀐 컨테이너를 다시 만들지 않음) | `ps`에 `Up`(방금 시작) |
| 멈추기 · 지우기 | `<루트>` | **타이머부터** — `systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer` → `bash deploy/host/scripts/host_ctl.sh stop`(지우기는 `down`) | `ps`에 `Exited`(`down`이면 줄 없음) |
| 자동 실행 타이머 켜기 | 벌 0 폴더(운영은 그 한 벌) | `bash deploy/host/scripts/host_ctl.sh timers` → 확인 `systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'` | `  씀  /etc/systemd/system/<단위>` 네 줄 · 목록에 타이머의 다음 실행 시각 |
| 새 판 올리기 | `<루트>` | [§4](#4-운영-중인-서버를-새-판으로-올리기) | `host_ctl.sh check` 통과 |
| 벌 늘리기(개발) | 벌 0 폴더 | [§2-15](#2-15-두-번째-벌-만들기) — `compose-dev.yml`에 칸 하나 | `host_ctl.sh ps`에 새 컨테이너 |

서버의 모든 컨테이너는 `docker ps`(일반 사용자 셸이면 `sudo docker ps`), 그 compose 파일의 앱 컨테이너만은 `host_ctl.sh ps`.

### 1-8. DB 표 만들기 — `migrate`

pgvector의 우리 스키마(검색 `required.pg.pg_schema`와 원천 스키마 5벌 `<스키마>_{sfdc,crms,las,faq,other}`, 로그 `applog`, 마스터 `<스키마>_master`)의 표·색인·뷰는 Alembic 리비전으로만 만든다(`common/store/db/migrations/versions/`). 버전 기록은 스키마마다 `<스키마>.alembic_version`. 적재·검색 전에 끝낸다. `pipe_exec.sh`는 상주 `data-pipeline` 안에서 돌므로 먼저 `host_ctl.sh up -d data-pipeline`.

> ⚠️ 0.1.0이 쓰던 스키마에 `up`하면 `0002_search`가 옛 표를 지운다. 새 서버가 아니면 §4를 따른다(새 `required.pg.pg_schema`로 올림 — [§4-1](#4-1-먼저-알-것)).

```bash
# 0. (DB마다 처음 한 번 — DB 관리자) vector 확장 — 없으면 migrate·적재가 "vector 확장 없음"으로 멈춘다
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
bash deploy/host/scripts/pipe_exec.sh migrate current                         # 지금 판과 코드의 끝 판
bash deploy/host/scripts/pipe_exec.sh migrate check --target all                # 지금 판(읽기만 — 끝 판이 아니면 종료 1)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원> --sql /app/output/up.sql   # DB 담당 검토용 SQL만 <루트>/output/up.sql에(DB에 붙지 않음)
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 담당 승인 뒤. 차원 = 임베딩 모델 출력 길이(모델 담당 확인 — 표가 없는 새 스키마는 필수, 이미 표가 있으면 DB 차원)
bash deploy/host/scripts/pipe_exec.sh migrate master load                      # 마스터 표를 glossary.csv로 통째로 바꿈(기본 resources/vocab/glossary, 서버 폴더면 --dir <컨테이너 안 경로>)
bash deploy/host/scripts/pipe_exec.sh migrate check --target all                # 기대: 갈래마다 "판 끝", 종료 코드 0
bash deploy/host/scripts/pipe_exec.sh show-stack                                # 엔진 구성 파일(이름·sha·경로)이 보이면 정상 — 못 읽으면 종료 2
```

- `--target`: `search`·`applog`·`master`·`all`(셋 모두). 끝 판: search `0007_search` · applog `0004_applog` · master `0002_master`. `up --sql <파일>`(+ 있는 DB는 `--from <지금 판>`)은 DB에 붙지 않고 실행할 SQL만 파일로 — DB 담당 검토용([§4-7](#4-7-db-판-올리기--migrate-up)).
- 표는 있는데 버전 기록이 없는 스키마(판 관리 전에 만든 것)에는 `up`이 종료 2로 멈춘다 — 새 `required.pg.pg_schema`로 올리고 전체를 다시 적재한다.
- 적재(`pgvector_load`)는 새 스키마면 만들고 기록, 기록이 있으면 `up`, 기록 없는 기존 스키마면 경고만 하고 계속한다. DB 판이 코드보다 낮으면 종료 2(`migrate up` 안내), 코드가 모르는 리비전이 있으면(옛 이미지로 되돌린 뒤 등) 적재·`up` 모두 종료 2. 검색 MCP는 버전을 보지 않는다.
- 판을 바꾸는 리비전(표·컬럼)은 데이터 계약 변경이다 — DB 담당 협의가 먼저.
- applog 월 파티션 준비·보존 기한 지난 파티션 삭제(`bash deploy/host/scripts/pipe_exec.sh migrate maintain --target applog`)는 새벽 배치(`nightly_batch.sh scheduled`)가 run_pipeline 앞에 매일 부른다(실패하면 경고만). 새벽 배치를 켜지 않은 서버는 이 명령을 따로 예약한다.
- PC: `python -m common.store.db.dbtool <up|current|check|master load> --target … [--schema S] [--dim N | --bundle B] [--create-extension]`(README §4-4).

### 1-9. 연결·이미지 점검

한 번에는 `bash deploy/host/scripts/host_ctl.sh check`(§1-5 8번). 하나씩 볼 때:

```bash
bash deploy/host/scripts/pipe_exec.sh ping_models     # 모델 주소(LLM·VLM·임베딩) — 하나라도 실패면 종료 1
bash deploy/host/scripts/pipe_exec.sh check_env       # PG·VLM·설정 요약(⚠️ PG 연결 실패를 "건너뜀"으로 보일 수 있음 — 출력을 읽는다)
bash deploy/host/scripts/pipe_exec.sh check           # 자원·쓰기 권한·디스크·PG·모델 요약(⚠️ 실패해도 종료 0 — 출력을 읽는다)
```

- EDW 로그인과 Object Storage 버킷을 따로 확인하는 명령은 없다. 첫 파싱 뒤 publish 미리보기(`bash deploy/host/scripts/pipe_exec.sh publish --dry-run` — 쓰기 0)로 확인하고, 실제 publish 한 번 뒤 Object Storage 파일을 본다 — 명령은 [§4-10](#4-10-올린-뒤-점검).
- ⚠️ 실제 publish(`pipe_exec.sh publish`)는 한 번만 한다. 다시 돌리면 Object Storage에 같은 결과를 새 시각 이름으로 또 올린다.

이미지 점검(손으로):
```bash
$DOCKER run --rm -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> check-modules
bash deploy/release/selftest_gate.sh $DOCKER run --rm --network host -v "$PWD/settings.yaml:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=dev -v "$PWD:/app/deploy:ro,z" data-pipeline-runtime:<판> selftest   # 기대: [판정] 통과 — FAIL 0
bash deploy/release/selftest_gate.sh $DOCKER run --rm --network host -v "$PWD/settings.yaml:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=dev -v "$PWD:/app/deploy:ro,z" mcp-server-runtime:<판> selftest      # 기대: [판정] 통과 — FAIL 0
```
selftest는 종료 코드가 아니라 `[판정]` 줄로 판정한다([§5-5](#5-5-배포-판정--selftest)). 운영 서버(구운 이미지)는 `-v "$PWD:/app/deploy…"` 없이 `data-pipeline:<판>`·`mcp-server:<판>`, `RUN_ENV=prd`.

검색 MCP 띄우기(운영) — `bash deploy/host/scripts/mcp_keepalive.sh`(여러 번 실행해도 안전 — `/health`가 응답하면 그대로, 꺼져 있으면 띄우고, 응답이 없으면 재시작).

### 1-10. 자원

기본 상한은 compose 파일의 컨테이너 칸(`cpus`·`mem_limit`·`memswap_limit`)에 직접 적혀 있다(settings.yaml 칸 없음 — 고친 뒤 `host_ctl.sh up -d`).

| 컨테이너 | 개발(`compose-dev.yml`) | 운영(`compose-prd.yml`) |
|---|---|---|
| `data-pipeline-0` | 4 · 12g(스왑 4g 더 — `memswap_limit` 16g) | 4 · 12g(`memswap_limit` 16g) |
| `data-pipeline-1` | 2 · 8g | — |
| `mcp-server-0` | 3 · 12g | 3 · 12g |
| `mcp-data-parsing-0` | 4 · 12g(CPU 나눔 비율 4096 — 일괄 1024보다 먼저) | 같음 |
| `pgvector`(`compose-pgvector.yml`) | 4 · 12g | 같음 |
| `redis`(`compose-redis.yml`) | 1 · 2g | 같음 |

서버 CPU 수보다 큰 `cpus`는 docker가 거부한다. CPU 4개 서버라면 예: `data-pipeline-0` 2, `mcp-data-parsing-0` 1(그러면 `tuning.ops.services.data_parsing.mcp_parse_engine_processes`도 1 이하), `mcp-server-0` 1. `cpus`는 예약이 아니라 상한이고, CPU가 모자랄 때는 `cpu_shares`가 나눈다. 모든 컨테이너의 `mem_limit` 합이 서버 메모리를 넘지 않게 줄인다.

### 1-11. 밖에서 붙기(다른 서버의 AI 클라이언트)

검색 MCP(`mcp-server-0`)에 다른 서버가 붙을 때.
- 컨테이너 안은 벌 0 settings.yaml `search.server.mcp_bind_host: auto`(컨테이너 사설 IP — `0.0.0.0`은 거부) · `mcp_port: 8051`이고, compose 파일이 서버 `0.0.0.0:8051`로 연다. 클라이언트 주소는 `http://<서버 IP>:8051/mcp`.
- `required.tokens.mcp_token`이 꼭 있어야 한다(없으면 시작 거부). 만들기: `openssl rand -hex 32`.
- `search.server.mcp_allowed_hosts`에 클라이언트가 보내는 Host를 적는다 — 예 `<서버 IP>:8051`(이름으로 붙으면 그 이름도, 쉼표 구분).
- 방화벽에서 8051을 연다 — 예: `firewall-cmd --add-port=8051/tcp --permanent && firewall-cmd --reload`.

---

## 2. 개발 서버 — 개발자 벌

대상: 개발 서버(`dev`)를 처음 맡은 사람. 서버 묶음(`compose-dev.yml` — 벌 0·1의 `data-pipeline-<번호>`, 벌 0의 검색 MCP·작업 컨테이너)을 띄우고 시험 원천 `DEV-1`의 문서를 파싱·게시·적재하고, 검색까지 확인한다. 설치 순서는 §1-5와 같고, 이 장은 개발 서버에서 단계마다 `cd`할 폴더·명령·성공 출력을 차례로 적은 것이다.

**표기**
- `/home/sbl` = 공용 폴더(예 — compose 파일의 `SBL_ROOT`). 서버마다 다를 수 있다 — 앞 담당자에게 확인한다.
- `<루트>` = 벌 폴더 = 코드 폴더 = 코드 zip을 푼 폴더(예 `/home/sbl/sbl_data_parsing-main-0`).
- `<…>` 꺾쇠 안은 직접 넣을 값이다. 실제 주소·계정·비밀번호는 문서·채팅·커밋에 적지 않는다.
- 명령은 모두 **root 셸**에서 친다. 각 단계 맨 앞의 `cd`를 꼭 먼저 한다 — 스크립트는 자기 자리(코드 폴더)에서 설정을 찾지만, 결과 파일 경로(`output/…`, `deploy/host/scripts/test_space/…`)는 지금 폴더 기준으로 적었다.

### 2-1. 폴더와 벌

```
/home/sbl/                                   ← 공용 폴더
├── sbl_images-main/                         ← 이미지 폴더(서버에 한 번 불러오면 모든 벌이 같이 씀)
├── sbl_data_parsing-main-0/                 ← 벌 0 = 코드 폴더 = <루트> — 검색 MCP·작업 컨테이너·새벽 배치도 이 벌
│   ├── settings.yaml                        ← 이 벌의 설정(init이 없을 때만 만듦 — 비밀값이 들어감, 권한 640)
│   ├── .env                                 ← 벌 0만 — PG·Redis 비밀번호(사람이 적음, 600 — compose-pgvector.yml·compose-redis.yml)
│   ├── output/                              ← 이 벌의 결과 폴더(컨테이너 안 /app/output)
│   ├── home/                                ← root 홈(컨테이너 /root — home/mcp = mcp-server-0 홈)
│   └── deploy/host/scripts/test_space/      ← run_pipeline 진행 기록(batch_progress/)
└── sbl_data_parsing-main-1/                 ← 벌 1(§2-15)
```

**벌은 `compose-dev.yml`의 칸 하나다** — 서비스 `data-pipeline-<번호>`가 벌 폴더 `<공용 폴더>/sbl_data_parsing-main-<번호>`를 붙이고 SSH 포트 하나를 연다. 번호·폴더·포트는 그 파일에 적혀 있다(settings.yaml 칸 없음). 이미지는 공용 폴더에서 한 번 불러오면 모든 벌이 같이 쓴다. PG·Redis는 서버마다 하나다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)).

| 벌 | 벌 폴더 | 컨테이너 | SSH(서버 포트) |
|---|---|---|---|
| 0 | `/home/sbl/sbl_data_parsing-main-0` | `data-pipeline-0` + 검색 MCP `mcp-server-0`(HTTP 8051) + 작업 컨테이너 `mcp-data-parsing-0` | 8020 · `mcp-server-0` 8050 |
| 1 | `/home/sbl/sbl_data_parsing-main-1` | `data-pipeline-1` | 8021 |

| 벌마다 settings.yaml로 정하는 것 | 어떻게 정하나 |
|---|---|
| 어떤 문서를 파싱하나 | settings.yaml `required.source.source_systems`(쉼표 구분 — 예 `DEV-1` · `DEV-1, DEV-2`) |
| 검색 DB 스키마 | 모든 벌이 같은 기준 스키마(`required.pg.pg_schema`, 비우면 `data_parsing`)를 함께 쓴다. 원천 `DEV-1` 문서는 그 아래 원천 스키마 `<기준>_dev_1`(기본이면 `data_parsing_dev_1`)에 들어간다 |

- **벌 번호와 `DEV-<숫자>`는 서로 다른 것이다.** 벌 번호는 컨테이너·폴더만, `DEV-<숫자>`는 문서와 스키마를 나눈다.
- 그 벌의 settings.yaml `required.source.source_systems`에 자기 원천 `DEV-<숫자>`를 적으면 그 문서만 파싱해 원천 스키마 `<기준>_dev_<숫자>`에 적재하고 `DEV-<숫자>/…`에 게시한다. **비우면 운영 5개 원천 전부를 파싱한다.**
- 원천 `DEV-<숫자>` 문서는 EDW 파일 목록 표(`required.edw.edw_file_table`, 기본 `AI.FileStorageMap`)의 `source_system` 칸이 `dev-1`(대소문자 무관)인 행이고, Object Storage 경로는 `DEV-1/…`이다. 시험 행과 파일은 DB·스토리지 담당이 넣는다 — 먼저 `dev-1` 행이 있는지 담당에게 확인한다.
- PG 스키마·EDW 기록 표·게시 경로는 벌마다 나뉘지 않는다 — 모든 벌이 같은 기준 스키마를 함께 쓴다. 그래서 **모든 벌이 같은 코드 판**이어야 한다(DB 표 판이 하나). `migrate up --target all`·`migrate master load`는 공용 DB에 한 번.
- `RUN_ENV`는 모든 벌이 `dev` 그대로다. `DEV-<숫자>`는 개발 서버에서만 쓴다 — 운영(`prd`)에서는 `DEV-…` 원천이 시작 거부다.
- 앱 컨테이너는 늘 `host_ctl.sh`로 다룬다 — 어느 벌 폴더에서 불러도 같은 `compose-dev.yml`(묶음 `sbl-devset`)이고, 서비스 이름으로 고른다.
- `pipe_exec.sh`·`run_pipeline.py`·새벽 배치·MCP 살리기는 벌 0 컨테이너(`data-pipeline-0`)만 다룬다 — 벌 0 settings.yaml의 원천. 벌 1은 SSH로 자기 컨테이너에 들어가 같은 도구를 안에서 부른다(`bash /app/docker/runtime_entry.sh tool check_env`·`… migrate check --target all`·`python -m pipeline.cli …`).
- 자동 실행(`host_ctl.sh timers`)은 벌 0 폴더에서 한 번.

### 2-2. 서버 준비 확인(처음 한 번)

```bash
export DOCKER=docker                      # 셸을 열 때마다(또는 root ~/.bashrc에)
docker compose version                    # 판 번호가 나오면 됨
python3 -c 'import yaml' && echo ok       # ok — 호스트 스크립트가 settings.yaml을 읽는 데 필요
docker images | grep -E 'data-pipeline-runtime|mcp-server-runtime'   # 불러온 실행 이미지 태그
```
- 하나라도 없으면 [§1-3](#1-3-미리-있어야-하는-것)대로 준비한다. 이미지가 없으면 [§1-5](#서버-설치-순서) 2번(`load.sh`)부터.
- compose 파일이 열 포트가 비었는지 본다(줄이 안 나오면 빈 포트):
```bash
ss -ltn | grep -E ':(8020|8021|8050|8051|8010|5433)\b'
```

### 2-3. 벌 폴더 만들기와 `init`

```bash
cd /home/sbl
unzip -q <코드 zip>                                         # → sbl_data_parsing-<판>/ (다른 벌과 같은 판)
mv sbl_data_parsing-<판> sbl_data_parsing-main-0            # 이름 끝 -0 = 벌 0(compose-dev.yml이 붙이는 폴더)
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
```
gitea에서 clone해 쓰는 경우는 [§6-3](#6-3-개발자-한-벌-만들기).

| 칸 | 넣을 값 | 어디서 |
|---|---|---|
| `<코드 zip>` | 코드 저장소의 그 판 zip(예 태그 `v0.3.0` → 풀면 `sbl_data_parsing-0.3.0/`) | GitHub `gigasamba/sbl_data_parsing` 태그 — 다른 벌과 같은 판 |
| `<운영 그룹>` | 결과·설정 파일을 사람 계정과 함께 쓰는 리눅스 그룹 | `id -gn <운영 계정>` — 모르면 서버 관리자. 다른 벌과 같은 그룹 |

**성공이면** 이렇게 찍힌다(값은 찍지 않는다):
```
[host_ctl init] 루트: /home/sbl/sbl_data_parsing-main-0
  만듦  /home/sbl/sbl_data_parsing-main-0/output
  만듦  /home/sbl/sbl_data_parsing-main-0/output/_mcp_parse/jobs
  권한  /home/sbl/sbl_data_parsing-main-0 (a+rX — 설정·결과·홈 빼고)
  만듦  /home/sbl/sbl_data_parsing-main-0/settings.yaml(settings.sample.yaml에서)
[host_ctl init] settings.yaml에서 아직 비어 있는 필수 칸(값을 채울 것 — 이름만):
  - required.env.run_env
  - required.pg.pg_host
  …
```
- 여러 번 불러도 안전하다. 이미 있는 파일은 `있음 …(덮지 않음)`으로 두고 넘어간다.
- `[host_ctl init] root로 실행할 것(sudo)` → root 셸에서 다시(종료 3).

### 2-4. 이 벌의 `settings.yaml` 채우기

```bash
cd /home/sbl/sbl_data_parsing-main-0
vi settings.yaml
```
`init`이 찍은 빈 칸을 모두 채운다([§1-6](#꼭-채울-값)). 접속·모델 칸은 다른 벌(또는 앞 담당자)의 settings.yaml과 같게 옮기고, **벌마다 다른 칸**만 바꾼다. 아래는 가짜 값으로 쓴 꼴이다 — 이미 있는 칸을 고치고, 같은 칸을 두 번 적지 않는다(두 번이면 시작 거부).

```yaml
required:
  env:
    run_env: dev                              # 개발 서버
  source:
    source_systems: DEV-1                     # 이 벌이 파싱할 원천 — 꼭 적는다(아래 주의)
  pg:
    pg_host: host.docker.internal             # 컨테이너에서 서버 자신(compose-pgvector.yml) — DB 담당이 따로 둔 PG면 그 주소
    pg_port: 5433
    pg_database: rag
    pg_user: rag
    pg_password: <비밀>
    pg_schema: data_parsing                   # 기준 스키마 — 모든 벌이 같게(바꾸지 않는다)
  # models · edw · publish · object_storage · tokens: 다른 벌과 같게
  deploy:
    host_docs_dir: <있는 호스트 폴더(절대 경로)>         # 컨테이너 /data/docs로 붙음
    pg_container_name: pgvector                         # run_pipeline이 문서 수를 셀 때 씀
common:
  connections:
    redis:
      redis_password: <비밀>                  # 서버에 하나 — 모든 벌이 같게(벌 0 .env의 REDIS_PASSWORD와 같은 값 · redis_host·redis_port는 비움 = host.docker.internal:8010)
search:
  server:                                     # 벌 0만(검색 MCP 컨테이너가 이 설정을 읽음)
    mcp_bind_host: auto
    mcp_port: 8051
    mcp_allowed_hosts: <서버 IP>:8051
ops:
  host:
    container_cli: docker
```

- ⚠️ **`required.source.source_systems`가 비어 있으면 "운영 5개 원천(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`) 전부"라는 뜻이다** — 그 벌은 운영 문서를 모두 파싱해 모든 벌이 함께 쓰는 스키마에 적재한다. 일부러 그렇게 만든 동작이라 코드가 막지 않는다. 개발자 벌은 꼭 자기 `DEV-<숫자>`(예 `DEV-1`)를 적는다.
- CPU 수가 적은 서버면 compose 파일의 `cpus`·`mem_limit`도 줄인다([§1-10](#1-10-자원)) — 모든 컨테이너의 합이 서버 CPU를 넘지 않게.
- 권한은 그대로 둔다(init이 640으로 만듦). 다른 편집기로 새로 저장해 권한이 바뀌었으면 `chmod 640 settings.yaml`.

**확인 — 설정이 읽히나:**
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK     # 값은 찍지 않고 compose 문법만
```
- `설정 OK`면 통과.
- `[설정] 설정 파일 없음: …` → 2-3 `init`을 이 폴더에서 했는지 본다.
- `[host_ctl] … 없음 — settings.yaml required.env.run_env는 local·dev·prd 중 하나` → `required.env.run_env`를 고친다.
- `host_ctl.sh config`를 `--quiet` 없이 부르면 경로·이름이 모두 찍힌다 — 남과 화면을 나눌 때는 쓰지 않는다.

### 2-5. `data-pipeline` 띄우기와 연결 점검

PG·Redis가 떠 있어야 한다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh) ①·②).
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-0
bash deploy/host/scripts/host_ctl.sh ps                      # data-pipeline-0이 Up
bash deploy/host/scripts/pipe_exec.sh check_env
bash deploy/host/scripts/pipe_exec.sh ping_models
```
- `pipe_exec.sh`는 앞뒤로 `[pipe_exec] <시각> <도구> 시작(data-pipeline-0 안에서)` · `[pipe_exec] <시각> <도구> 끝 (종료 코드 0)`을 찍는다. **끝 줄의 종료 코드가 0**이어야 한다.
- `check_env`: 항목마다 `[OK ]`(정상) 또는 `[-- ]`(문제·미설정) 줄. `[-- ]` 줄을 읽고 해당 칸을 고친다(PG 연결 실패가 "건너뜀"처럼 보일 수 있으니 PG 줄을 꼭 읽는다).
- `ping_models`: 표의 `결과` 칸이 임베딩·LLM·VLM 모두 `OK`. `FAIL`이 있으면 종료 코드 1 — `required.models`의 주소·모델 이름을 고친다(서버는 내부망 모델만).
- `[오류] 상주 컨테이너 data-pipeline-0가 떠 있지 않음` → 이 단계 첫 줄 `up -d data-pipeline-0`부터 다시.
- 컨테이너가 `Restarting`이면 `docker logs data-pipeline-0`의 `[devbox]` 줄을 본다 — `run_env is …`(settings.yaml `required.env.run_env`를 `dev`로) · 이미지에 root 비밀번호가 없음([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)).

### 2-6. DB 판 — 검토용 SQL 뽑기 → `migrate up`

검색 DB는 모든 벌이 같이 쓴다. 표를 만들거나 바꾸는 일은 **DB 담당과 협의한 뒤** 한다. 먼저 지금 상태를 본다(읽기만):

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/pipe_exec.sh migrate check --target all
```
출력 줄 꼴: `[migrate] <갈래> <스키마>: 판 <상태> [<판 번호>] · 코드의 끝 판 <끝 판>`. 상태는 `끝`(최신) · `낮음`(올려야 함) · `없음`(아직 표 없음) · `모름`(코드보다 새 판 — 멈추고 담당에게 묻는다). 모두 `끝`이면 종료 코드 0, 아니면 1.

어느 경우인지 고른다:

| 상황 | 할 일 |
|---|---|
| 서버의 첫 벌 — 갈래가 모두 `없음` | (가) |
| 이미 다른 벌이 쓰는 DB — 기준 스키마들은 `끝`이고 `<기준>_dev_1` 줄이 없음 | (나) |
| `낮음`이 있음 | 코드 판이 DB보다 새 것 — [§4-7](#4-7-db-판-올리기--migrate-up)을 따른다(모든 벌을 같은 판으로 맞춘 뒤 한 번) |

**(가) 첫 벌 — 표 전부 만들기**
```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원> --sql /app/output/up.sql
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>
bash deploy/host/scripts/pipe_exec.sh migrate master load
```
- `<임베딩 차원>` = 임베딩 모델이 내는 벡터 길이(예 1024 — 모델 담당에게 확인). 처음 표를 만들 때 정해지고 나중에 못 바꾼다.
- `vector` 확장이 없다고 멈추면 DB 관리자가 한 번 만든다([§1-8](#1-8-db-표-만들기--migrate)).

**(나) 이미 있는 DB — 이 벌의 DEV 원천 스키마만 더하기**
```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/pipe_exec.sh migrate up --target search --from <끝 판> --dim <임베딩 차원> --sql /app/output/dev_1.sql
bash deploy/host/scripts/pipe_exec.sh migrate up --target search
```
- `--sql`은 settings.yaml `source_systems`의 DEV 원천 스키마를 빈 스키마부터 만드는 SQL을 쓴다. 파일 안 `-- 수동:` 줄은 DB 담당이 직접 확인할 것(이미 있는 스키마인지 등)이다.
- ⚠️ **`migrate up --target search`(= `dbtool up --target search`)는 어느 벌에서 부르든 DB에 이미 있는 모든 `<기준>_dev_*` 스키마(다른 벌 것 포함)를 함께 끝 판으로 올린다.** 이 벌의 `<기준>_dev_1`만 올리는 것이 아니다. 일부러 그렇게 만든 동작이라 코드가 막지 않는다 — 그래서 모든 벌이 같은 코드 판이어야 하고, 올리기 전에 다른 벌 담당에게 알린다.
- 새 `DEV-<숫자>`를 넣은 벌은 이 명령을 한 번 해야 원천 스키마가 생긴다(없으면 적재가 멈춤). `migrate master load`는 하지 않는다(서버에 한 번이면 됨).

**성공이면**:
- `--sql`: `[migrate] SQL → /app/output/<파일> (DB에 붙지 않음 — 실행은 DB 담당이 직접)` — 호스트에서는 `<루트>/output/<파일>`. (가)처럼 `--from` 없이 뽑으면 `[migrate] 경고: … 빈 스키마부터 만드는 SQL …` 줄이 함께 나온다(첫 벌이면 정상).
- `up`: 스키마마다 `[migrate] search data_parsing_dev_1: 판 ['<끝 판>'] (끝 <끝 판>)` 꼴.
- 마지막으로 다시 확인:
```bash
bash deploy/host/scripts/pipe_exec.sh migrate check --target all    # 모든 줄이 "판 끝" — data_parsing_dev_1 줄도 보임
```

### 2-7. 전체 점검 — `host_ctl.sh check`

```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh check
```
`check`는 단계를 차례로 돌리고 처음 실패에서 멈춘다. 단계마다 `[host_ctl check] ── <이름>` 줄 뒤에 그 명령의 출력이 나온다. 개발·운영 모두 여섯 단계다.

| 순서 | 단계 이름 | 하는 일 |
|---|---|---|
| ① | `check_env` | 2-5와 같음(`data-pipeline-0` 안) |
| ② | `ping_models` | 2-5와 같음 |
| ③ | `migrate check` | 2-6 확인과 같음 |
| ④ | `selftest data-pipeline` | `data-pipeline-0`의 이미지로 서버 배포 시험(몇 분 걸림 — 실행 이미지면 이 코드 폴더를 붙임) — `[판정] 통과 — FAIL 0` 줄이 있어야 함 |
| ⑤ | `selftest mcp-server` | `mcp-server-0`의 이미지로 같음 |
| ⑥ | `검색 MCP` | `mcp_keepalive.sh` — `http://127.0.0.1:8051/health` 응답 확인(꺼져 있으면 띄우고 다시 봄) |

- **성공이면 마지막 줄** `[host_ctl check] 통과 — 7개`.
- 실패면 마지막 줄 `[host_ctl check] 실패 — <단계>: <안내>` — 안내대로 고치고 `check`를 다시 부른다. ③에서 멈추면 2-6, ④⑤에서 멈추면 `FAIL` 줄의 시험 이름으로 원인을 찾는다([§5-5](#5-5-배포-판정--selftest)).

### 2-8. `DEV-1` 문서 한 번 처리하기

`run_pipeline.py`가 문서마다 받기 → 파싱 → 게시(Object Storage — silver) → 원본 삭제 → 구조화·적재(PG — gold)를 끝까지 돌린다. 게시와 적재는 따로 부르지 않는다. 처음에는 `--limit`로 두세 건만 돌린다.

```bash
cd /home/sbl/sbl_data_parsing-main-1
python3 deploy/host/scripts/run_pipeline.py --help                  # 인자 목록이 나오면 호스트 준비 OK
nohup python3 deploy/host/scripts/run_pipeline.py --limit 2 > run_first.out 2>&1 &
tail -f deploy/host/scripts/test_space/batch_progress/progress.log  # Ctrl+C로 보기만 멈춤(실행은 계속)
```
- 대상은 settings.yaml `source_systems`(예 `DEV-1`)의 행만이다. 문서 이름으로 더 좁히려면 `--filter <키워드,…>`.
- 진행 줄(문서마다 셋): `doc#<번호> 파싱 OK(…)` → `doc#<번호> publish OK(…)` → `doc#<번호> 구조화+적재 OK(…)`.
- **성공이면 끝 줄**: `=== 문서별 flow 끝: 2건(완료 2 · 건너뜀 0 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 0) · … · 종료 코드 0 ===`.
- `처리할 문서 없음 — 종료` → EDW 목록에 `dev-1` 행이 없거나 이미 다 처리했다(2-1 — 담당에게 행 확인).
- `[중단] <칸 경로> …` → 그 settings.yaml 칸이 비었다(종료 2). 채우고 다시.
- `다른 run_pipeline이 도는 중(…) — 종료 코드 75` → 이 벌에서 이미 하나가 돈다(새벽 배치 포함). 끝난 뒤 다시.
- 종료 코드 뜻과 실패 문서 다시 돌리기는 [§3-3](#3-3-파이프라인-실행--run_pipeline)·[§3-6](#3-6-실패한-문서-찾기와-다시-돌리기). 다음부터 이어서 돌릴 때는 `--skip-done`(이미 적재한 문서와 영구 제외 문서는 건너뜀).

### 2-9. 게시·적재 결과 확인

적재 기록은 원천 스키마의 `doc` 표에 남는다(`<기준>_dev_1.doc`):
```bash
docker exec <PG 컨테이너> psql -U <계정> -d <DB 이름> -c "SELECT file_path, parse_status, silver_key, parsed_at, loaded_at, gold_version FROM data_parsing_dev_1.doc ORDER BY loaded_at DESC NULLS LAST LIMIT 5"
```
- **성공이면** 처리한 문서 수만큼 행, `parse_status`가 `ok` 또는 `partial`, `silver_key`·`loaded_at`·`gold_version`이 채워져 있다. `silver_key`는 Object Storage 게시 위치(`DEV-1/…` 아래)다.
- 행이 없으면 `progress.log`에서 그 문서의 `FAIL` 줄과 `doc_<번호>.log`를 본다(§2-11).
- 적재되지 않은 문서(파싱 실패·DRM·내용 중복 등)는 `applog.except_doc_info`에 남는다 — SQL은 [§3-12](#3-12-로그-db-살펴보기--applog-sql읽기만).

### 2-10. 검색 확인

`data-pipeline-0` 컨테이너 안에서 바로 검색한다 — 토큰 없이 DB 검색만 본다(실행 이미지가 `mcp_server`를 불러올 수 있음):
```bash
cd /home/sbl/sbl_data_parsing-main-0
docker exec data-pipeline-0 python -m mcp_server.cli.search_ask ask --source DEV-1 --k 3 --q "<처리한 문서에 있는 낱말>"
```
- **성공이면** `질문: … (원천 DEV-1 · 근거 <N>건)` 줄 뒤에 `[1] <파일 경로>  p.<쪽> L.<줄>`처럼 근거가 나온다. `[ask] …`로 끝나면 그 오류 글자를 읽는다(원천 스키마가 없으면 2-6).
- `근거 0건` → 2-9에서 `doc` 행이 있는지, 질문 낱말이 문서에 있는지 본다.
- 실제 클라이언트와 같은 길(HTTP — `mcp-server-0`, 서버 8051)로 부르는 시험(`mcp_smoke`)은 [§0-2 ④](#0-2-dev--개발-서버-개발자별-벌)·[mcp-guide.md](mcp-guide.md).

### 2-11. 로그 보기

```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh logs --tail 100 data-pipeline-0  # 서비스 이름 = 컨테이너 이름
bash deploy/host/scripts/host_ctl.sh logs -f mcp-server-0             # 계속 보기(Ctrl+C — 컨테이너는 그대로)
tail -n 50 deploy/host/scripts/test_space/batch_progress/progress.log # run_pipeline 진행 줄
ls deploy/host/scripts/test_space/batch_progress/                     # doc_<번호>.log — 문서별 파싱·게시·구조화 출력
cat run_first.out                                                     # 2-8 nohup 화면 출력
ls -la output/logs/                                                   # 비어 있어야 정상 — 파일이 있으면 DB 로그 쓰기 실패
journalctl -u data-pipeline-nightly.service -n 50                     # 타이머를 켠 뒤(§2-12)
```
- 실행 기록은 DB `applog` 스키마에 남는다 — [§3-12](#3-12-로그-db-살펴보기--applog-sql읽기만).

### 2-12. 자동 실행 켜기(선택)

```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh timers
systemctl list-timers 'data-pipeline-nightly*' 'mcp-server-keepalive*'
```
- **성공이면** `  씀  /etc/systemd/system/<단위>` 네 줄(`data-pipeline-nightly`·`mcp-server-keepalive`의 `.service`·`.timer`), 목록에 두 타이머의 다음 실행 시각. MCP 살리기 타이머는 벌 0의 Redis·작업 컨테이너·검색 MCP를 2분마다 본다.
- `data-pipeline-nightly.timer`는 settings.yaml `ops.nightly` 세 칸을 채우기 전에는 아무것도 하지 않는다([§3-3-2](#3-3-2-새벽-배치)) — 필요 없으면 `systemctl disable --now data-pipeline-nightly.timer`.
- 코드 폴더를 새 판으로 덮어쓴 뒤에도 다시 부른다.

### 2-13. 개발 작업 공간 — SSH·opencode(선택)

- 개발·운영 서버의 앱 컨테이너(`data-pipeline-*`·`mcp-server-0`)는 늘 SSH 작업 공간(명령 `devbox` — sshd)으로 뜬다. 사용자는 root, 비밀번호는 이미지에 넣은 값이다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)). 작업 컨테이너 `mcp-data-parsing-0`은 SSH가 없다. PC(`compose-local.yml`)는 SSH를 열지 않는다.
- 접속: `ssh -p 8020 root@<서버>`(벌 0) · `ssh -p 8021 root@<서버>`(벌 1) → `cd /app/deploy`(벌 폴더 — 쓰기 가능, `settings.yaml`만 읽기 전용). 홈 `/root` = `<벌 폴더>/home`(SSH 호스트 열쇠·git 계정·작업 기록 — 컨테이너를 다시 만들어도 남음). 열쇠 로그인을 쓰려면 `<벌 폴더>/home/.ssh/authorized_keys`에 내 공개 열쇠를 둔다(폴더 700 · 파일 600).
- 이미지에는 개발 도구(sshd·git·uv·ruff·mypy·pytest·ripgrep·sqlite3·tmux·vim 등)와 opencode(이미지를 만들 때 `assets/opencode/opencode`가 있으면)가 들어 있다. 앱은 이 도구를 쓰지 않는다.
- 저장소 루트 `opencode.jsonc`는 opencode 프로젝트 설정 자리다 — 외부망에는 빈 틀(`{}`)만 있고, 내부망 gitea에서 모델 주소·이름을 채워 커밋한다(키는 적지 않음 — 아래 `INTERNAL_LLM_API_KEY`). 외부망 새 판을 들여올 때 덮지 않는다([§6-1](#6-1-저장소-처음-만들기--관리자가-한-번) ⑥ `--exclude opencode.jsonc`).
- opencode는 내부망 모델만 쓴다(외부 모델 목록 받기·자동 업데이트 끔). 첫 시작에 홈의 `~/.config/opencode/opencode.json`에 틀이 복사되니 모델 주소(`baseURL` — OpenAI 호환 `/v1`)·이름(`<model id>` 두 곳)을 채운다. 키가 필요한 모델이면 SSH 셸에서 `export INTERNAL_LLM_API_KEY=<키>`(틀이 이 env를 읽음 — 컨테이너 env·settings.yaml에는 넣지 않는다).
- git 이름·메일(선택): `option.devbox`에 `git_user_name`·`git_user_email`을 적으면 작업 공간이 시작할 때 `git config --global user.name`·`user.email`을 쓴다. gitea 로그인은 컨테이너 안에서 처음 `git pull`·`push`할 때 직접 한다 — [§6-3](#6-3-개발자-한-벌-만들기).
- 컨테이너 안에서 root로 쓴 파일은 서버에서도 root 소유다 — 서버 계정으로 고치거나 지울 때는 `sudo`.

### 2-14. 컨테이너 이름·볼륨 바꾸기

이름·이미지·포트·CPU·메모리·볼륨은 compose 파일(`deploy/host/compose/compose-<환경>.yml`)에 직접 적혀 있다(settings.yaml 칸 없음). 바꾸려면 그 칸을 고친다 — compose 파일은 코드라 git으로 커밋해 모든 벌 폴더를 같게 둔다(§6-4).

```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh down                           # ① 이름(서비스·container_name)을 바꿀 때만 — 옛 이름을 먼저 내린다
vi deploy/host/compose/compose-dev.yml                              # ② 칸을 고침
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK  # ③
bash deploy/host/scripts/host_ctl.sh up -d                          # ④ 바뀐 컨테이너만 다시 만듦
bash deploy/host/scripts/host_ctl.sh ps
```
- ①을 빼먹으면 옛 이름의 컨테이너가 남아 포트를 잡고 새 컨테이너가 뜨지 못한다. 그때는 `docker rm -f <옛 이름>` 뒤 ④.
- 새벽 배치·MCP 살리기·`pipe_exec.sh`·`run_pipeline.py`는 이름 `data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0`·`redis`와 서버 포트 8051을 그대로 찾는다 — 이 이름과 포트는 바꾸지 않는다.
- 볼륨을 더할 때 호스트 경로는 절대 경로나 `${SBL_ROOT:-/home/sbl}`·`${PRD_DIR:-…}`로 시작하고 끝에 `:z`(읽기 전용이면 `:ro,z`).

### 2-15. 두 번째 벌 만들기

`compose-dev.yml`의 `data-pipeline-1` 칸을 복사해 번호·포트·폴더를 바꾼다(예 `data-pipeline-2` · `0.0.0.0:8022:22` · `sbl_data_parsing-main-2`). 모든 컨테이너의 `cpus` 합이 서버 CPU를 넘지 않게 한다([§1-10](#1-10-자원)). 코드는 벌 0과 같은 판이다.

```bash
cd /home/sbl
unzip -q <코드 zip> && mv sbl_data_parsing-<판> sbl_data_parsing-main-2
cd /home/sbl/sbl_data_parsing-main-2
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
cp ../sbl_data_parsing-main-0/settings.yaml settings.yaml.new      # 벌 0 설정을 틀로(아래 칸을 고친 뒤 settings.yaml로 바꿈)
```
`settings.yaml.new`에서 벌마다 다른 칸만 고친다:

| 칸 | 벌 0 | 새 벌 |
|---|---|---|
| `required.source.source_systems` | `DEV-1` | `DEV-2` |
| `option.devbox.git_user_*` | 벌 0 개발자 이름·메일 | 비우거나 새 벌 개발자 값 |
| `search.server.*` | 검색 MCP 값 | 지워도 된다(검색 MCP는 벌 0만) |

```bash
mv settings.yaml.new settings.yaml && chmod 640 settings.yaml
cd /home/sbl/sbl_data_parsing-main-0
vi deploy/host/compose/compose-dev.yml                                         # data-pipeline-2 칸을 더함(git 커밋 — 다른 벌 폴더도 같은 파일로)
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-2
ssh -p 8022 root@<서버>                                                         # 안에서: cd /app/deploy && bash /app/docker/runtime_entry.sh migrate up --target search
```
- 새 `DEV-<숫자>` 원천 스키마는 그 벌 컨테이너 안에서 `migrate up --target search`로 만든다(2-6 (나) — 검토용 SQL 먼저).
- 모든 벌을 한 번에 띄우기: `bash deploy/host/scripts/host_ctl.sh up -d`(서비스 이름 없이).

### 2-16. 멈추기·정리하기

**잠깐 멈추기(다시 켤 수 있게)** — 벌 0을 멈출 때는 타이머부터 끈다(안 그러면 MCP 살리기·새벽 배치가 다시 부른다):
```bash
cd /home/sbl/sbl_data_parsing-main-0
systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer      # 벌 0을 멈출 때만
bash deploy/host/scripts/host_ctl.sh stop data-pipeline-1                   # 서비스 이름 — 빼면 모두
bash deploy/host/scripts/host_ctl.sh ps                                     # data-pipeline-1이 Exited
```
다시 켜기: `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-1`(벌 0이면 이어서 `systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer`).

**벌 하나를 없애기** — 되돌릴 수 없으니 대상 번호를 두 번 확인하고, 지우기 전에 `settings.yaml`·`output/`을 백업할지 정한다:
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh rm -sf data-pipeline-2                 # 컨테이너 멈추고 지움(볼륨은 호스트 폴더라 남음)
vi deploy/host/compose/compose-dev.yml                                      # data-pipeline-2 칸을 지움(git 커밋)
cd /home/sbl && rm -rf /home/sbl/sbl_data_parsing-main-2                   # 설정(비밀값)·결과 폴더도 함께 지워짐
```
- DB의 `data_parsing_dev_2` 스키마는 남는다. 지우려면 DB 담당에게 요청한다(공용 DB — 직접 지우지 않는다). 남아 있으면 다른 벌의 `migrate up --target search`가 계속 판을 올리고, 검색의 원천 목록에도 남는다.
- Object Storage의 `DEV-2/…` 게시 결과도 스토리지 담당에게 요청한다.

### 2-17. 막혔을 때 — 메시지로 찾기

| 메시지(일부) | 뜻 | 할 일 |
|---|---|---|
| `[설정] 설정 파일 없음: …` | 이 폴더에 settings.yaml 없음 | 그 폴더에서 `host_ctl.sh init` |
| `[host_ctl] … 없음 — settings.yaml required.env.run_env는 local·dev·prd 중 하나` | run_env가 비었거나 틀림 | `required.env.run_env: dev` |
| `[오류] 상주 컨테이너 …가 떠 있지 않음` | `pipe_exec.sh`가 붙을 컨테이너가 꺼짐 | `host_ctl.sh up -d data-pipeline-0` |
| `docker logs <이름>`의 `[devbox] run_env is …` | SSH 컨테이너는 dev·prd에서만 뜸 | 그 벌 settings.yaml `required.env.run_env` |
| `[devbox] the image has no root password …` | 이미지에 root 비밀번호가 없음 | 비밀번호를 넣어 이미지를 다시 빌드([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)) |
| PG·Redis `compose up`이 `… .env에 REDIS_PASSWORD 필요`(PG_USER·PG_DB·PG_PASSWORD도 같은 꼴)로 멈춤 | 코드 폴더 맨 위 `.env`가 없거나 그 칸이 빔(또는 `--env-file .env`를 빼고 부름) | `.env`에 settings.yaml과 같은 값을 적고 `--env-file .env`로 다시 부름 |
| `… DEV 원천 스키마가 코드의 끝 판 …이 아님: 적재 전에 \`migrate up --target search\`` | `_dev_*` 스키마 판이 낮음 | 2-6 (나) |
| `…: 차원을 모름 — --dim N` | 새 스키마인데 차원을 안 줌 | `--dim <임베딩 차원>` |
| `[host_ctl check] 실패 — <단계>: …` | 그 단계 실패 | 2-7 표 |
| `다른 run_pipeline이 도는 중` | 이 서버에서 이미 실행 중 | 끝날 때까지 기다림 |

---

## 3. 일상 운영

대상: 서버 운영자. 명령은 모두 코드 폴더(`cd /home/sbl/sbl_data_parsing-main[-<번호>]`)에서, root 셸에서 실행한다. 컨테이너 다루는 명령은 [§1-7 핵심 명령](#핵심-명령).

### 3-1. 상주 컨테이너와 자동 실행

| 서비스 = 컨테이너 | compose 파일 | 하는 일 | 어디서 |
|---|---|---|---|
| `data-pipeline-<번호>` | `compose-<환경>.yml` | SSH 작업 공간(`devbox`) — `run_pipeline.py`·`pipe_exec.sh`가 `data-pipeline-0`에 `exec`(PC `compose-local.yml`은 `idle`) | 개발(벌마다)·운영(0번) |
| `mcp-data-parsing-0` | 같음 | `parse_document` 작업 서비스(`run-mcp-parsing` — SSH 없음) — 토큰은 `required.tokens.mcp_token`(검색 MCP와 같은 칸) | 개발(벌 0)·운영 |
| `mcp-server-0` | 같음 | SSH + 검색 MCP(`devbox mcp` — 서버 8051) | 개발(벌 0)·운영 |
| `redis` | `compose-redis.yml` | `parse_document` 작업 큐 | 서버마다 하나 |
| `pgvector` | `compose-pgvector.yml` | 검색 DB | 서버마다 하나(DB 담당이 따로 둔 PG면 없음) |

| 무엇 | 방법 |
|---|---|
| 검색 MCP·작업 컨테이너·Redis 상주 확인 | systemd `mcp-server-keepalive.timer` — 부팅 1분 뒤 + 2분마다 `mcp_keepalive.sh`: `redis`가 꺼졌으면 `compose-redis.yml`로 띄우고 건강하지 않으면 restart · `mcp-data-parsing-0`이 꺼졌으면 `host_ctl.sh up -d` · `http://127.0.0.1:8051/health`가 응답하면 그대로, `mcp-server-0`이 꺼져 있으면 띄우고, 응답이 없으면 재시작 |
| 새벽 배치 | systemd `data-pipeline-nightly.timer` — [§3-3-2](#3-3-2-새벽-배치) |
| 재부팅 뒤 되살리기 | docker 서비스(`systemctl enable docker`)가 부팅 때 컨테이너를 다시 띄운다 — 운영의 앱 컨테이너와 PG·Redis는 `restart: always`, 개발의 앱 컨테이너는 `unless-stopped`(사람이 `host_ctl.sh stop`으로 멈춘 것은 그대로 둠). keepalive 타이머가 2분마다 한 번 더 본다. 확인은 [§3-5](#3-5-서버를-다시-켠-뒤) |

systemd 설치(DB 판과 컨테이너를 확인한 뒤 — 벌 0 폴더(운영은 그 한 벌)에서, 새 판으로 덮어쓴 뒤에도 다시):

```bash
bash deploy/host/scripts/host_ctl.sh timers        # 단위의 코드 폴더 자리를 이 코드 폴더로 채워 /etc/systemd/system에 쓰고 두 타이머를 켬 — 단위 4개
```

- 검색 MCP가 응답하나: `curl -s http://127.0.0.1:8051/health`.
- 타이머 기록: `journalctl -u mcp-server-keepalive.service -n 50`.
- 끄고 다시 켜기: 끌 때는 타이머부터(안 그러면 2분 안에 검색 MCP를 다시 띄운다) → `host_ctl.sh stop`. 켤 때는 `host_ctl.sh up -d` → `systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer`.

### 3-2. 설정 값 바꾸기

| 바꿀 것 | 방법 |
|---|---|
| 설정 값 | settings.yaml을 직접 고치고 `host_ctl.sh up -d --force-recreate <서비스>`(서비스 이름 = 컨테이너 이름 — 예 `mcp-server-0`). 다시 띄우기 전에 [env-guide §4 "칸 이름 확인"](env-guide.md#4-확인) |
| 이번 실행만 다른 값 | `--set 이름=값`(아래) |
| 엔진 구성 | 코드 폴더의 `resources/config/pipeline_stack.json`(설정 칸 없음)을 고쳐 코드 폴더째 바꾼다([§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)) — 확인 `show-stack`([resources.md §1](../architecture/resources.md)). 이미지에 없는 엔진이 있으면 파이프라인 진입점이 종료 2. 검색 MCP는 시작 때 읽으므로 바꾼 뒤 `mcp_keepalive.sh`로 다시 띄운다. 원천은 폴더·`rdb:csv`만 |

- **한 번만 다른 값은 `--set 이름=값`** — 받는 진입점: `pipeline.cli`·`pipeline.extract.candidate_ready`·`gold_bundle`·`pgvector_load`·`publish_parse_result`·`mcp_server.main`·`mcp_server.cli.search_ask`. 예: `$DOCKER exec data-pipeline-0 python -m pipeline.cli --set PIPE_PROCS=2 parse …`. 이름은 옛 env 이름(`python -m common.config.sample --where`). 모르는 이름·호스트 칸·비밀 칸은 종료 2.
- 셸·compose·`docker exec -e`로 준 옛 env 이름은 효과가 없다(시작 때 이름만 경고). 셸 env로 덮을 수 있는 것은 compose 치환 값(이미지 태그·자원·포트·호스트 경로)뿐이다.
- 서버에서 바꾼 옵션 값은 코드가 아니라 `settings.yaml`에 둔다 — 새 판이 기본값을 바꿔도 settings.yaml 값이 이긴다. 바꿨으면 `server-changes.md`에 적는다([§3-11](#3-11-개발자에게-보고하는-법)).

### 3-3. 파이프라인 실행 — run_pipeline

| 방법 | 명령 | 순서 | 언제 |
|---|---|---|---|
| 문서별 흐름 | `python3 deploy/host/scripts/run_pipeline.py …`(코드 폴더에서, nohup) | 문서마다 파싱 → publish → 원본 삭제(게시 성공 뒤) → 구조화·적재 | 대량 처리 |
| 새벽 배치 | systemd `data-pipeline-nightly.timer` → `nightly_batch.sh scheduled` | §3-3-2 | 정기 운영 |
| 파싱·게시만 | `pipe_exec.sh parse` · `pipe_exec.sh publish [--dry-run]` | 상주 컨테이너 안에서 한 번 | 단계 확인 — §3-3-3 |

서버 입구는 `run_pipeline.py` 하나다 — 문서마다 파싱 → publish(Object Storage) → 원본 삭제 → 구조화·적재(PG — 처리 기록 포함)를 상주 컨테이너 안에서 `exec`로 돌린다. **PC에서는 실행하지 않는다**(운영 EDW·Object Storage에 접속).
- **자리:** 코드 폴더에서 `python3 deploy/host/scripts/run_pipeline.py …`로 실행한다(다른 자리에 복사해 돌리면 `--code <코드 폴더>`).
- **대상:** 기본은 FileStorageMap의 모든 문서를 처음(`--start-offset` 기본 0)부터. 이름으로 좁힐 때만 `--filter <키워드,…>`(하나라도 들면). 몇 개만은 `--limit N`·`--seqs <번호,…>`.
- **설정**은 서버 settings.yaml(`--settings` · `SETTINGS_FILE` · `<루트>/settings.yaml` 순)에서 읽는다 — 호스트 python에 PyYAML 필요. 필요한 칸이 없으면 칸 경로만 찍고 종료 2. `required.env.run_env`가 `dev`·`prd`가 아니면 시작하지 않는다.
  - 작업 폴더 `ops.run_pipeline.run_pipeline_work_dir`(비우면 스크립트 옆 `test_space/` — 진행 기록 `batch_progress/`)
  - 결과 폴더 `<루트>/output`(컨테이너 `/app/output`의 원본)
  - MCP 업로드 작업 폴더는 `<결과 폴더>/_mcp_parse/jobs`(고정)
  - 레인·동시 수 값 `ops.run_pipeline.*`(비우면 코드 기본값)
- **게시·EDW 설정**(settings.yaml `required` — 빠지면 run_pipeline이 칸 이름을 찍고 종료 2): 게시 위치 `required.publish.publish_bucket`·`publish_prefix`, Object Storage 접속 `required.object_storage.*`, EDW 접속 `required.edw.*` — 칸 뜻은 [§1-6](#꼭-채울-값). `dev.local.*`(가짜 EDW 등)은 PC 전용이라 서버에서는 읽지 않는다(`local_edw_sqlite_file`은 비운다).
- 파싱·publish·구조화가 실패하거나 시간 제한을 넘기면 그 문서의 컨테이너 안 프로세스도 끈다(다음 문서와 CPU·메모리를 다투지 않게).
- publish는 gold(PG 원천 스키마 `doc`)에 이미 끝난 문서를 Object Storage에 올리지 않는다(`--reparse` 목록만 새 날짜 폴더). 올린 문서의 처리 기록은 문서 폴더 `publish/silver.jsonl`에 쓰고, 적재가 그 값을 `doc` 칸으로 옮긴다.
- 원본(`_staging/*.bin`·그 ETag 파일 `*.etag`·`_docflow/<seq>/_source_files`)은 **publish가 성공한 뒤에만** 지운다. 파싱·publish가 실패한 문서는 원본이 남고 `batch_progress/progress.log`와 `applog.except_doc_info`(`error` 행)에 적힌다(다음 `--skip-done` 실행이 다시 고름). 구조화·적재가 실패하면 publish한 결과는 그대로이고 `doc` 행이 없으므로 다음 `--skip-done` 실행이 다시 고른다(`error` 행도 남김).
- **종료 코드**(PRD [pl-18](../prd/ops.md#pl-18)): `0` 대상 0건·모두 끝 · `1` 실패 문서가 하나라도 · `75` 마감(`--deadline`) 도달(실패 없음) 또는 다른 run_pipeline이 도는 중 · `2` 설정 문제. 실패와 마감이 함께면 `1`. 새벽 배치 unit은 `75`를 성공으로 친다.
- **겹침 잠금:** run_pipeline은 `batch_progress/run_pipeline.lock`을 `flock`으로 잡는다 — 새벽 배치와 사람이 직접 돌린 run_pipeline이 함께 돌지 않는다(뒤에 온 쪽이 75). 죽으면 잠금은 저절로 풀린다. 작업 폴더가 같아야 같은 잠금이다. 같은 결과 폴더에 두 작업이 겹치면 `/app/output/.pipeline.lock` 때문에 뒤쪽이 종료 75.
- 우선순위 낮추기(`tuning.extract.low_priority_engines` — 일괄 파싱 엔진 자식 nice +10)는 같은 세션·autogroup 안에서만 효과가 있다. 컨테이너끼리는 CPU 나눔 비율(compose 파일 `mcp-data-parsing-0`의 `cpu_shares` 4096 대 일괄 1024)이 정한다.

#### 3-3-1. 진행 보기

```bash
bash deploy/host/scripts/host_ctl.sh logs -f data-pipeline-0                # 상주 컨테이너 로그(Ctrl+C로 멈춤 — 컨테이너는 그대로)
tail -f <run_pipeline 작업 폴더>/batch_progress/progress.log              # 문서별 줄("doc#<seq> 구조화+적재 OK|FAIL")
tail -n 50 <결과 폴더>/_docflow/<seq>/structure.log                    # 그 문서의 구조화·적재 출력 — 문서가 끝나면 지워짐(남기려면 run_pipeline --no-cleanup)
```

**로그는 Postgres(`applog` 스키마)에 남는다.** 서버(두 이미지)는 `ops.log.log_db_enabled` 기본 켬이라 `migrate up --target all`(applog 포함)이 먼저다. DB에 못 쓰면 그 행만 `<결과 폴더>/logs/`에 JSON Lines로 남는다. 사람이 보는 실행 출력은 컨테이너 로그(`docker logs <컨테이너>`·`host_ctl.sh logs`), MCP 호출(질문·SQL 포함)은 `applog.mcp_log`이다. SQL은 [§3-12](#3-12-로그-db-살펴보기--applog-sql읽기만).

#### 3-3-2. 새벽 배치

- systemd `data-pipeline-nightly.timer`(5분마다 깨움) + settings.yaml `ops.nightly.nightly_start_time: "HH:MM"`(그 시각부터 5분 안에 시작) · `ops.nightly.nightly_max_docs`(새 문서 수 상한, 1 이상) · `ops.nightly.nightly_stop_time: "HH:MM"`(마감 — 시작보다 5분 넘게 뒤). **셋 중 하나라도 비면 돌지 않는다**(기본 비움 — 타이머가 켜져 있어도 아무것도 하지 않음).
- `nightly_batch.sh scheduled`가 시작 시각부터 5분 안일 때만 applog 파티션 정리(`pipe_exec.sh migrate maintain --target applog` — 실패하면 경고만 남기고 계속) 뒤 `run_pipeline.py --start-offset 0 --skip-done --max-docs <상한> --deadline <마감>`을 부른다(마감이 지나면 새 문서를 받지 않고, 받은 문서는 끝까지).
- 형식이 틀리면(HH:MM 아님 · 상한이 1 이상 정수 아님 · 마감이 시작보다 5분 이내) 종료 2. 지금 바로 돌리려면 run_pipeline을 직접 부른다.
- 개발자 벌은 새벽 배치가 필요 없으면 `systemctl disable --now data-pipeline-nightly-<번호>.timer`.

#### 3-3-3. 파싱·게시만 따로

```bash
bash deploy/host/scripts/pipe_exec.sh parse [--source-limit N]   # 파싱 → <결과 폴더>/parse/_rep. 임베딩·DB 없음
bash deploy/host/scripts/pipe_exec.sh publish --dry-run          # 무엇을 올리고 쓸지 표만(쓰기 0)
bash deploy/host/scripts/pipe_exec.sh publish                    # 대표 결과 Object Storage 업로드 — 한 번만
```
- 도구만 따로: `bash deploy/host/scripts/pipe_exec.sh <rdb_discover|check_env|ping_models|migrate|show-stack|check> [인자]`.

#### 3-3-4. 답변 생성 점검(개발 서버 — 컨테이너 안에서)
호스트 python에는 PyYAML만 있으므로 도구는 컨테이너 안에서 돌린다. `validation/`은 코드 폴더를 붙인 개발 서버의 실행 이미지에만 있다(운영 이미지에는 없음). 검색 MCP는 같은 컨테이너 안에서 먼저 연다([§0-2 ④](#0-2-dev--개발-서버-개발자별-벌)) — 그때 쓴 포트를 아래 `<search.server.mcp_port>` 자리에 넣는다.
```bash
$DOCKER exec data-pipeline-0 python -m validation.e2e.answer_gen --url http://127.0.0.1:<search.server.mcp_port>/mcp --q "<질문>"   # --concurrency N · 결과 /app/output/eval/answer_gen/
```
MCP 토큰은 settings.yaml `required.tokens.mcp_token`, 모델은 `required.models.llm_*`(서버는 내부 모델만). 결과는 호스트 `<결과 폴더>/eval/answer_gen/`.

### 3-4. 매일 점검

아침에 한 번, 코드 폴더에서(여러 벌이면 이름 끝 `-<벌>`):

| 무엇 | 명령 | 정상 |
|---|---|---|
| 새벽 배치 | `journalctl -u data-pipeline-nightly.service --since yesterday \| tail -20` | 시작·끝 줄, 종료 코드 0(실패 문서 있음 1 · 마감 75) |
| 실패 문서 | `grep FAIL <작업 폴더>/batch_progress/progress.log \| tail` | 줄 없음 — 있으면 §3-6 |
| 검색 MCP(운영) | `curl -s http://127.0.0.1:<search.server.mcp_port>/health` | `{"ok":true,"ready":true,…}` |
| 디스크 | `df -h <루트> <결과 폴더>` · `du -sh <결과 폴더>/_docflow <결과 폴더>/_staging` | 쓰기 여유 20% 넘음 · `_docflow`·`_staging`이 계속 늘지 않음 |
| 로그 예비 파일 | `ls -la <결과 폴더>/logs/` | 비어 있음 — 파일이 있으면 DB 로그 쓰기 실패(파일 안 오류를 보고 DB를 고친 뒤 지움) |
| 컨테이너 | `bash deploy/host/scripts/host_ctl.sh ps` | 운영 네 줄 · 개발 한 줄 Up |

- `<작업 폴더>` = `ops.run_pipeline.run_pipeline_work_dir`(비우면 코드 폴더 안 `deploy/host/scripts/test_space/`). `<결과 폴더>` = `<루트>/output`.
- 문제가 있으면 §3-11 형식으로 `issues.md`에 적는다. DB에서 더 보려면 §3-12의 SQL.

#### 3-4-1. MCP 파싱 작업 성능

`docker exec mcp-data-parsing-0 python -m pipeline.tools.perf_report --mcp --since 24 --top 10`으로 최근 작업 수·fail/timeout 수와 전체(큐 대기+파싱)·대기·파싱·주요 단계의 p50/p95/최대를 본다. `--since` 기본은 24시간이다. 파싱은 파일 복사·준비부터 대표 결과까지이고, 주요 단계(엔진·채점·대표 결과)는 `proc.run` 벽시계 시간이다(병렬 엔진별 시간의 합이 아님). 진행 중 실행은 건수만 세고 시간 표에서는 뺀다. VLM 미설정 스캔 PDF도 완료 작업으로 기록하며 `metrics.note`에 안내가 남는다. DB를 못 쓰는 PC는 `--file <logsink 대체 jsonl>…`, 원인별 단계·엔진 상세는 `perf_report <run_id>`로 본다. 모두 읽기 전용이다.

검색 MCP가 잰 총 응답 시간은 `mcp_log.duration_ms`, 서비스 큐 대기는 `mcp_parse.job.metrics.queue_wait_ms`, 파싱은 그 행의 `duration_ms`다. 같은 `job_id`로 아래처럼 잇는다(응답에는 업로드·Redis 대기 등도 포함되므로 서비스 전체와 차이가 날 수 있음). 실패 응답에 job_id가 없으면 작업 행만 따로 조회한다.

```sql
SELECT m.requested_at, m.request_id,
       e.metrics->>'job_id' AS job_id, e.doc_id, e.run_id,
       m.duration_ms AS response_ms,
       (e.metrics->>'queue_wait_ms')::numeric AS queue_wait_ms,
       e.duration_ms AS parsing_ms, e.status, e.metrics->>'note' AS note
FROM applog.mcp_log AS m
JOIN applog.pipe_event AS e
  ON e.stage = 'mcp_parse.job'
 AND e.metrics->>'job_id' = m.result_keys->>'job_id'
WHERE m.tool_name = 'parse_document'
  AND m.requested_at >= now() - interval '24 hours'
  AND e.ts_start >= now() - interval '24 hours'
ORDER BY m.requested_at DESC;
```

### 3-5. 서버를 다시 켠 뒤

docker 서비스가 부팅 때 컨테이너를 다시 띄운다(운영 앱·PG·Redis `always` · 개발 앱 `unless-stopped`). 사람은 떴는지 확인하고, 안 뜬 것만 띄운다. root 셸, 벌 0 폴더(운영은 그 한 벌)에서:
```bash
export DOCKER=docker
systemctl is-active docker                                                # 기대: active
docker ps --format '{{.Names}} {{.Status}}'                               # 기대: pgvector · redis · 앱 컨테이너(운영 셋 · 개발 넷) Up
bash deploy/host/scripts/host_ctl.sh up -d                                # 안 뜬 앱 컨테이너만 띄움
systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer   # 꺼져 있었으면
systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'   # 기대: 타이머 다음 실행 시각
bash deploy/host/scripts/host_ctl.sh check                                # 기대 마지막 줄: [host_ctl check] 통과 — 7개
```
- `pgvector`·`redis`가 없으면 `docker compose -f deploy/host/compose/compose-pgvector.yml up -d`·`… compose-redis.yml up -d`([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)). DB 담당이 따로 둔 PG면 `check`가 PG에서 멈출 때 DB 담당에게 알린다.
- 꺼지기 전에 돌던 `run_pipeline.py`는 다시 시작하지 않는다 — 다음 새벽 배치가 `--skip-done`으로 이어 가거나, 사람이 다시 부른다(§3-6).

### 3-6. 실패한 문서 찾기와 다시 돌리기

- **진행 기록:** `<작업 폴더>/batch_progress/progress.log` — 문서마다 `doc#<번호> 파싱 OK|FAIL` · `doc#<번호> publish OK|FAIL` · `doc#<번호> 구조화+적재 OK|FAIL` 줄. 문서별 로그(파싱·게시·구조화 출력)는 같은 폴더의 `doc_<번호>.log`.
- **작업 폴더 자리:** 비우면 코드 폴더 안 `deploy/host/scripts/test_space/` — 벌마다 따로다. 새 판을 덮어쓸 때 옛 코드를 지우는 명령이 `deploy/`와 함께 이 폴더도 지우므로, [§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)의 명령은 이 폴더를 잠시 밖으로 옮겼다 되돌린다 — 그 명령을 쓸 때만 기록과 잠금이 남는다. 다른 자리에 두려면 settings.yaml `ops.run_pipeline.run_pipeline_work_dir`에 호스트 절대 경로를 적는다(벌마다 다르게 — 같으면 두 벌이 한 잠금을 나눠 써 함께 돌지 못한다).
- **실패 문서 번호 모으기:**
```bash
grep -E 'doc#[0-9]+ (파싱|publish|구조화\+적재) FAIL' <작업 폴더>/batch_progress/progress.log | grep -oE 'doc#[0-9]+' | sort -u | tr -d 'doc#' | paste -sd, -
```
- **다시 돌리기:** 원인을 고친 뒤(설정·EDW·모델 등) 그 번호만 — `nohup python3 deploy/host/scripts/run_pipeline.py --seqs <번호,번호,…> > <작업 폴더>/rerun.out 2>&1 &`(코드 폴더에서). 실패한 문서는 gold `doc` 행이 없으므로 다음 `--skip-done` 실행도 다시 고른다.
- 다시 받아도 같은 결과인 문서(DRM·암호·지원 안 함·확장자 없음)와 내용 중복은 `applog.except_doc_info`에 `skip` 행으로 들어가 다음 실행이 고르지 않는다(§3-12 ④).
- **적재 거부 — 임베딩 모델이 다른 묶음.** 묶음의 임베딩 모델이 검색 스키마에 이미 적재된 문서의 모델과 다르면 적재는 아무것도 쓰지 않고 종료 2(`[load] 임베딩 모델이 다름 — 적재 거부 …`). `applog.pipe_event`에 남는다:
```sql
SELECT ts_start, run_id, model, err FROM applog.pipe_event
WHERE stage = 'load.embed_guard' AND ts_start > now() - interval '7 days' ORDER BY ts_start DESC;
```
  해결: 기존 문서와 같은 모델(`required.models.embed_model`)로 묶음을 다시 만들거나, 모델을 바꾸려면 새 검색 스키마에 적재한다([§4-8](#4-8-pgvector가-바뀔-때--두-경우) (나)).
- 이미 처리한 문서를 판·사슬·마스터가 바뀌어 다시 처리하는 법은 [§4-9](#4-9-다시-처리할-층과-명령).
- 검색 결과 품질은 PC의 검증 페이지(`validation/search_ui`)와 답변 점검(`valid_env/answer_test`)으로 본다.

### 3-7. 서버에 생기는 파일

서버마다 값이 다른 파일은 **루트(코드 폴더) 바로 아래 `settings.yaml`** 하나다 — git·코드 zip에 없는 파일이라 새 판을 덮어써도 남는다. `host_ctl.sh init`이 **없을 때만** `settings.sample.yaml`을 복사한다(있으면 덮지 않음). PG·Redis 비밀번호는 같은 값을 코드 폴더 맨 위 `.env`에 사람이 적는다. EDW 조인 사슬 `edw_chain.yaml`은 서버 파일이 아니라 코드다(코드 폴더 맨 위 — git으로 고치고 운영 이미지에도 들어감, [§3-9-2](#3-9-2-edw-조인-사슬-파일-고쳐-쓰기)).

| 파일 | 자리(호스트 → 컨테이너) | 만드는 것 | 읽는 곳 | 권한 |
|---|---|---|---|---|
| `settings.yaml` | `<루트>/settings.yaml` → 개발 `/app/deploy/settings.yaml` · 운영 `/etc/rag/settings.yaml`(읽기 전용 — 모든 앱 컨테이너) | `host_ctl.sh init`(`settings.sample.yaml`에서) | 모든 앱·호스트 스크립트 | 640 — **비밀값이 들어 있다**, 벌 폴더를 지울 때 함께 지운다 |
| `.env` | `<루트>/.env`(벌 0 — compose가 읽어 PG·Redis 컨테이너 설정으로) | 사람(`REDIS_PASSWORD`·`PG_USER`·`PG_DB`·`PG_PASSWORD` — settings.yaml과 같은 값) | `pgvector`·`redis` 컨테이너(compose `--env-file .env`) | 600 — 비밀번호가 들어 있다(git 제외) |

실행하면서 생기는 파일:

| 경로 | 왜 생기나 | 지워도 되나 |
|---|---|---|
| `<결과 폴더>/edw/embed_cache.sqlite` | 임베딩 캐시 | 지우면 다음 적재 때 임베딩을 모두 다시 부른다 — 지우지 않는다 |
| `<결과 폴더>/logs/*.jsonl` | DB 로그를 못 쓸 때의 예비 기록(`ops.log.log_fallback_dir`) | 문서 본문·질문이 들어갈 수 있다 — 밖으로 내보내지 않는다. DB가 돌아온 뒤 확인하고 지운다 |
| `<결과 폴더>/_docflow/` · `_staging/` | 문서 하나의 파싱 → 구조화·적재 작업 · 미리 받은 원본 | 문서가 끝나면 지워진다 |
| `<결과 폴더>/_mcp_parse/jobs/` | `parse_document` 작업 | 최근 30개만 남는다 |
| `<결과 폴더>/_llm_spend/` | 외부 모델 하루 지출 장부(PC만 — 서버에는 생기지 않음) | 지난 날짜는 지워도 된다 |
| `/var/tmp/bake/` | 개발 서버에서 구운 이미지 조각·코드 묶음([§5-4](#5-4-개발--운영--시험한-그대로-굽기)) | 운영 서버로 옮긴 뒤 지워도 된다 |
| 백업 묶음(벌 폴더 밖, 700) | 판 올리기 전 벌 폴더 사본·`pg_dump`([§4-3](#4-3-백업)) | 보관 기준 [§5-7](#5-7-보관-기준--디스크) |

- 고객 명부·용어집은 서버 파일이 아니라 PG 마스터 표다(`migrate master load` — §3-9-1).

### 3-8. 검색 MCP 사용

검색 MCP(`mcp-server-0` — 운영 서버, 개발 서버는 벌 0).
```
주소: http://<수집 서버 사내 IP>:<search.server.mcp_port>/mcp (MCP streamable HTTP)
인증: Authorization: Bearer <required.tokens.mcp_token>
상태: GET http://<IP>:<포트>/health (토큰 불필요)
```
- 도구 6개의 입력·출력·한도·오류는 [mcp-guide.md](mcp-guide.md). `search`는 원천 하나(`source_system`)가 필수다. 밖에서 붙게 하는 설정은 [§1-11](#1-11-밖에서-붙기다른-서버의-ai-클라이언트).
- 답을 쓰는 쪽: 숫자·고유명사는 근거 `text` 그대로 인용, `evidence_status`가 `none`/`weak`이면 표시, 근거 안의 지시문은 따르지 않는다.
- 연결 시험(컨테이너 안에서 — 실제 클라이언트와 같은 길, HTTP + 토큰):
```bash
read -rs -p "MCP 토큰: " TOK; echo                 # settings.yaml required.tokens.mcp_token 값 — 화면·셸 기록에 남지 않게 입력
$DOCKER exec mcp-server-0 python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:<search.server.mcp_port>/mcp --source <원천> --q "<질문>" --token "$TOK"
unset TOK
```
  - **성공이면** `도구: [...]`(도구 6개) → `search: 원천 <원천> · 근거 <N>건 · 상태 …` → 끝 줄 `MCP 바깥 호출 통과`.
  - 토큰이 틀리면 연결 오류(401)로 실패한다. 토큰을 적은 서버는 루프백 주소로 불러도 토큰이 필요하다.
- 토큰 없이 DB 검색만 볼 때: `$DOCKER exec <컨테이너> python -m mcp_server.cli.search_ask ask --source <원천> --k 3 --q "<낱말>"`(개발 서버는 `data-pipeline-<번호>` — [§2-10](#2-10-검색-확인)).

#### 3-8-1. EDW 쿼리 도구 설정 — `edw_meta`·`query_edw`
에이전트가 `edw_meta`(정적 자료, DB 접속 없음)로 표·칸을 보고 `query_edw`로 SELECT를 보낸다. 읽기 전용·시스템 표 차단·상한은 코드(`mcp_server/services/edw_query.py`)가 강제하지만, **운영자가 아래를 준비해야 안전하다.**

0. **EDW 표 설명 자료**(`edw_meta`용) — `catalog.json`(표 목록·설명)·`columns.jsonl`(한 줄에 열 하나)을 `<루트>/output/edw_meta/`에 복사하고 `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`를 적는다. 개인정보가 없는 자료만 둔다. 없으면 `edw_meta`만 `not_configured`(`query_edw`는 그대로) — 파일 꼴은 PRD [mc-07](../prd/mcp.md#mc-07), 받기는 refactor.md C-91.

1. **EDW 읽기 계정**(`required.edw.edw_read_user`·`edw_read_password` — 파이프라인 원천 조회와 같은 계정):
   - `SELECT` 권한만 준다(DDL·DML·`EXEC`·시스템 프로시저 없음).
   - DBA가 추가로: `DENY VIEW DEFINITION` · 다른 데이터베이스·연결 서버(linked server) 권한 없음 · 가능하면 Resource Governor 등으로 질의 시간·CPU 상한.
   - 같은 계정이라 `query_edw`도 `AI.FileStorageMap`을 읽을 수 있다 — 막으려면 2.
2. **표 범위** — 읽기 계정이 볼 수 있는 모든 표(`sys.*`·`INFORMATION_SCHEMA.*`는 늘 거부). 좁히려면 DBA가 읽기 계정의 `SELECT` 권한을 줄인다(설정의 허용 목록은 없다).
3. 확인: `query_edw({"sql": "DROP TABLE ..."})`·`sys.*`를 읽는 호출이 `rejected:*`로 막히는지 한 번 본다.

### 3-9. 회사 맞춤(도메인 튜닝)

바꿀 곳은 코드가 아니라 **데이터 파일·설정**이다. 기밀(실고객·실제품·계약 값)은 **서버 폴더에만** 둔다 — git·PC·외부 모델로 보내지 않는다. 바꾼 뒤에는 같은 질문 세트로 검색 결과를 전/후 비교한다.

| 무엇 | 위치 |
|---|---|
| 용어집 · 고객 명부 · ID 모양 | PG 마스터 표 `<db_schema>_master.glossary`. 원본 `glossary.csv`(`resources/vocab/glossary/` 또는 서버 폴더)를 고친 뒤 `pipe_exec.sh migrate master load [--dir <폴더>]`(§3-9-1) |
| 원천 표 열 이름 | settings.yaml `tuning.extract.source_columns.source_column_*` |
| 엔진 구성 | `resources/config/pipeline_stack.json`(확인 `show-stack` — §3-2) |
| MCP 안내 문구 | 코드 `mcp_server/main.py`의 `_DEFAULT_MCP_INSTRUCTIONS`(설정 칸 없음 — 바꾸면 코드 배포) |
| EDW 조인 사슬(고객·원천 메타·검색 attrs 키) | 코드 폴더 맨 위 `edw_chain.yaml`(git — §3-9-2) |

#### 3-9-1. 고객 명부·용어집 작성법

구조화·검색은 파일이 아니라 PG 마스터 표 `glossary`만 읽는다. `migrate master load`가 CSV 하나 `glossary.csv`(파일 이름·머리글 그대로)로 표를 통째로 바꾼다. 기본 폴더는 샘플(가상 회사·제품) `resources/vocab/glossary/`. 서버 실명 자료(고객 명부·용어집이 든 `glossary.csv`)는 **`<루트>/output/glossary/`**에 두고(UID 10001이 읽게) 컨테이너 안 자리로 넣는다: `bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary`. 표가 비었으면 서버의 구조화·검색이 시작하지 않는다.
- **`master load` 뒤에는 검색 MCP를 다시 시작한다** — `bash deploy/host/scripts/host_ctl.sh restart mcp`(검색은 시작할 때와 새 적재 판이 들어올 때만 마스터를 읽음). 이미 적재한 문서는 자동으로 다시 처리하지 않는다(새로 적재하는 문서의 `gold_version` `<VERSION>+m<해시 8자>`만 바뀜 — 다시 하려면 [§4-9](#4-9-다시-처리할-층과-명령)).
- `--dir`에는 **컨테이너 안에서 보이는** 폴더를 적는다 — 컨테이너에 붙는 서버 폴더는 결과 폴더(`/app/output`)뿐이다([env-guide §5](env-guide.md#5-서버-경로-칸--컨테이너-안-절대-경로)).
- 칸 설명은 `docs/architecture/db_schema.md` §3-4. UTF-8로 저장(Excel이면 "CSV UTF-8" — cp949도 읽힘). 머리글이 다르면 `master load`가 거부한다.

##### `glossary.csv` 꼴
머리글 `kind,canonical,variant,variant_kind,description,context_required,case_sensitive`. 한 줄 = 값 하나 — 고객·용어·ID 꼴 하나는 머리 줄(`client_id`·`concept_id`·`regex`)에서 시작하고, 바로 뒤따르는 같은 `kind`·`canonical` 줄이 거기에 붙는다(이름이 같은 고객 둘·이름이 빈 고객도 따로, ID 꼴은 `regex` 줄마다 하나 — `example`·`updated`는 그 앞 `regex` 줄 것). 머리 줄 없이 나온 줄, 값이 하나뿐인 종류(`status` 등)를 한 고객·용어에 두 줄 쓰면, 또는 모르는 `kind`·`variant_kind`를 쓰면 `master load`가 표를 바꾸지 않고 거부한다.

```csv
kind,canonical,variant,variant_kind,description,context_required,case_sensitive
client,Hanbit Biologics,C0001,client_id,항체 바이오시밀러 위탁생산 고객,,
client,Hanbit Biologics,한빛바이오,alias,,,
term,Contract Manufacturing Organization,BIZ.CMO,concept_id,고객이 확립한 공정으로 생산만 위탁 수행,위탁생산|생산|제조,N
term,Contract Manufacturing Organization,위탁생산,synonym,,,
term,Contract Manufacturing Organization,CMO,abbr,,,
id,contract_no,"C-[A-Z]{2,4}-\d{4}-\d{2}",regex,합성 데이터 형식,,
```

**고객(`client`)** — `canonical` = 정식 이름(비우면 `name_ko`가 이름). 첫 줄은 `client_id`(번호가 없어도 빈 값으로 둔다).

| `variant_kind` | 쓰는 법 |
|---|---|
| `client_id` | 고객 번호(SFDC 등) — `description`에 고객 설명 |
| `name_ko` | 한글 이름 — 별칭으로도 쓰임 |
| `alias` | 다른 표기 — 한 줄에 하나 |
| `client_type` | `customer`·`prospect` — 둘 다 똑같이 쓰임 |
| `segment`·`country`·`parent`(모회사 `client_id`)·`source`·`updated` | 참고용 — 빼도 됨 |
| `status` | 없으면 사용 · `inactive`·`deleted`면 무시 |

- 영문 3자 이하 별칭(예 `PFE`)은 오탐 때문에 무시된다 — 4자 이상이나 한글로. 같은 별칭을 두 고객에 쓰지 않는다.

**용어(`term`)** — `canonical` = 표준 이름(필수). 첫 줄은 `concept_id`.

| `variant_kind` | 쓰는 법 |
|---|---|
| `concept_id` | 겹치지 않는 영문 ID(`분야.이름`, 예 `QA.OOS`) — 없으면 `AUTO.<canonical>`. `description`에 한글 정의, `context_required`(동음이의 줄임말이면 주변에 함께 나와야 하는 단어들, `\|` 구분)·`case_sensitive`(`Y`면 대소문자 구분)도 이 줄에 |
| `category` | `org_client`(고객 — 명부에 합류)·`product_example`·`modality`·`modality_code`·`process`·`quality`·`contract`·`regulatory`·`business` 등 — 한 줄에 하나 |
| `synonym` · `abbr` | 같은 뜻의 다른 표기 · 줄임말 — 한 줄에 하나 |
| `weak` | 뜻이 넓어 약하게만 쓰는 말 |
| `broader`·`related` | 상위·관련 개념의 `concept_id`(없는 ID면 오류) |
| `definition_en`·`source`·`owner`·`updated` | 빼도 됨 |
| `status` | 없으면 반영 · 빼려면 `draft`·`rejected` |

**ID 꼴(`id`)** — `canonical` = 종류(`contract_no`·`product_code` 등). `regex` 줄 하나 = 정규식 하나(대소문자 무시, `description`에 메모), 바로 뒤 `example`·`updated`는 그 꼴의 참고용.

- 오류(조용히 넘기지 않음): 명시한 `concept_id` 중복 · 없는 ID를 가리키는 `broader`/`related` · 깨진 정규식.
- 초안 도구 `python -m pipeline.transform.structure.glossary_suggest`·`gen_roster --kind product`·`python -m pipeline.transform.structure.draft_terms --bundle <묶음>`은 `output/` 아래 초안(용어 사전 옛 칸 꼴 — 한 줄 = 개념 하나)만 만든다 — 사람이 확인해 `glossary.csv`의 `term` 줄로 옮긴다.

##### 고객 마스터에서 명부 만들기
SFDC·EDW 내보내기에서 `glossary.csv`의 고객(`client`) 줄을 만든다. 열 이름만 매핑 파일에 적는다(예제: `resources/vocab/glossary/client_master.example.csv` + `client_master_map.example.json`). 매핑 키 = 명부 칸: `name`(필수 → `canonical_name`) · `aliases`(`;`·`|`) · `client_id`·`name_ko`·`client_type`·`segment`·`country`·`parent_client_id`·`status`·`description`·`updated`(선택). 열 이름은 영문·숫자·`_`만. 같은 고객 여러 줄은 하나로 합친다(별칭은 합치고 다른 칸은 처음 값).
내보낸 파일과 매핑 파일을 `<루트>/output/glossary/`에 둔 뒤(컨테이너에서 `/app/output/glossary/`):
```bash
G=/app/output/glossary
$DOCKER exec data-pipeline-0 python -m pipeline.transform.structure.roster_from_edw --kind client \
  --source csv:$G/client_master.csv --mapping $G/client_master_map.json \
  --out $G/glossary.csv               # EDW 표에서 바로: --source rdb:<스키마.표>(읽기 계정)
$DOCKER exec data-pipeline-0 python -m pipeline.transform.structure.roster_from_edw --check $G/glossary.csv   # 오류 0 확인
```
`--out` 파일이 이미 있으면 고객 줄만 바꾸고 용어·ID 꼴 줄은 그대로 둔다(glossary 꼴이 아닌 파일이면 거부). 먼저 파일을 복사해 두고 바뀐 줄을 비교한 뒤 반영한다.

##### 옛 CSV를 `glossary.csv`로 옮기기
옛 판의 `client_roster.csv`·`domain_terms.csv`·`id_patterns.csv`가 있는 폴더를 한 번에 옮긴다(같은 대응 — 없는 파일은 건너뜀. 만들 파일이 이미 있거나, 머리글이 옛 꼴과 다르거나(없는·모르는 칸), 머리글보다 칸이 많은 줄이 있으면 아무것도 쓰지 않고 거부):
```bash
$DOCKER exec data-pipeline-0 python -m common.store.master convert --src /app/output/glossary --out /app/output/glossary/glossary.csv
```

##### 점검(반영 전)
```bash
$DOCKER exec data-pipeline-0 python -c "import sys; from pathlib import Path; from common.store import master as M; from common.core import terms as T; m = M.Master(M.read_csv(Path(sys.argv[1]))); print(len(T._master_glossary(m)), '개념 반영 ·', len(m.rows('client_roster')), '고객 ·', len(m.rows('id_patterns')), 'ID 꼴')" /app/output/glossary   # 오류면 여기서 멈춤
bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary && bash deploy/host/scripts/host_ctl.sh restart mcp   # 반영
```

#### 3-9-2. EDW 조인 사슬 파일 고쳐 쓰기

적재가 문서 메타(고객 `client_edw`·등록 시각 `created_at`·원천 메타 `doc.attrs`)를 EDW에서 채울 때 따라가는 표·칸 이름과, 검색 MCP가 쓰는 `attrs` 키의 거르기 이름·근거 표시는 파일 하나에 있다 — 코드 폴더 맨 위 `edw_chain.yaml`이고 **꼴과 칸의 뜻은 그 파일의 머리 주석이 정본**이다. 서버 EDW 이름이 다르거나 메타 키를 더하려면 이 파일을 고쳐 git으로 커밋한다(개발 서버 벌 폴더에서 — 운영 서버는 그 커밋으로 구운 이미지에 들어간다, [§5-4](#5-4-개발--운영--시험한-그대로-굽기)). 사슬을 바꿔도 이미 적재한 메타는 바뀌지 않는다 — 필요한 문서는 `--replace`로 다시 적재한다([§4-9](#4-9-다시-처리할-층과-명령)).

**① 고치기** — 벌 컨테이너 안(SSH — 벌 폴더가 `/app/deploy`에 쓰기 가능으로 붙음)에서 `vi /app/deploy/edw_chain.yaml` → 점검(③) → `git commit`. 설정 칸 `ops.paths.edw_chain_file`은 비워 둔다(비움 = 코드 폴더의 `edw_chain.yaml` — 다른 파일을 시험할 때만 컨테이너 안 경로).

**② 자주 하는 고침**
```yaml
sfdc:
  steps:
    ...
    - name: opportunity
      table: SFDC.Opportunity_v2
      on: {Id: [link.LinkedEntityId, task.WhatId, event.WhatId]}
      when: {prefix: "006"}
  fields:
    sf_op_name: {from: opportunity.OpportunityName, filter: sf_op_name, evidence: true}

    - {name: quote, table: SFDC.Quote, on: {Id: link.LinkedEntityId}, when: {prefix: "0Q0"}, optional: true}
    - name: opportunity
      on: {Id: [link.LinkedEntityId, task.WhatId, event.WhatId, quote.OpportunityId]}

      on: {Id: [link.LinkedEntityId, event.WhatId, task.WhatId]}

crms:
  fields:
    pm_name: {from: project.PM_NAME, filter: pm_name, evidence: true}   # search(attrs={"pm_name": "…"}) · 근거 attrs.pm_name
```
- 새 `filter` 이름은 `search`의 이름 있는 인자가 아니라 `attrs` 거르기로 쓴다(이름 있는 인자는 계약에 고정).
- **이름을 바꾸면 안 되는 키:** SFDC `sf_op_id`(`list_doc_fulltext`가 키 이름 그대로 읽음 — EDW 칸 `from`만 바꾼다), 분류 힌트 키(`title`·`entity_*`·`sent_received__c`·`subject`·`stagename`·`real_rfp__c`·`rfp_received_*`·LAS `approvalname` — 분류가 이름으로 읽음). `doc_class`는 분류가 쓰는 키라 사슬에 쓰지 않는다.

**③ 실제 실행 전에 점검** — 파일만 읽고 검사한다(EDW·PG에 붙지 않음).
```bash
$DOCKER exec data-pipeline-0 python -m pipeline.load.edw_doc_meta --check                                        # 설정 칸이 가리키는 파일(비우면 코드 폴더의 것)
$DOCKER exec data-pipeline-0 python -m pipeline.load.edw_doc_meta --check --file /app/deploy/edw_chain.yaml     # 파일을 직접 지정
```
칸 이름이 EDW에 실제로 있는지는 이 점검이 보지 않는다 — `edw_meta`·`query_edw`나 DB 담당으로 확인한다. 검색 쪽은 `edw_meta`를 인자 없이 불러 `search_attrs`에 고친 키가 보이는지 본다.

**④ 오류가 나면 · 되돌리기**
- 적재 시작 때 `[edw_meta] 사슬 설정 파일을 못 읽음(…)`·`사슬 설정 오류(…)`·`사슬 설정 YAML 오류(…)`로 멈춘다. 검색은 같은 글을 `search`의 `{"error"}`로 돌려준다. ③으로 고친 뒤 다시 돌린다.
- 칸 이름이 EDW에 없으면 적재는 계속되고 그 칸 메타만 비며(표를 못 읽으면 그 원천 메타 전체 — `optional` 단계면 그 단계만) 경고와 실행 기록 `meta_missing`이 남는다 — 고친 뒤 그 문서를 `--replace`로 다시 적재한다([§4-9](#4-9-다시-처리할-층과-명령)).
- 되돌리기: git으로 그 고침을 되돌린다(`git checkout HEAD -- edw_chain.yaml` — 커밋 전, 커밋 뒤면 `git revert <커밋>`).

### 3-10. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `check`가 "컨테이너 안의 PG_HOST는 컨테이너 자신" 경고 | `required.pg.pg_host`가 `127.0.0.1` | compose로 띄웠으면 무시(`network_mode: host`). `docker run`으로 따로 띄울 때만 `--network host`(+`-e NETWORK_HOST=1`) 또는 서버 IP |
| 적재·검색이 PostgreSQL에 못 붙음 | `required.pg` 칸이 비었거나 틀림 | 호스트·포트·계정 확인 |
| 파싱이 종료 4 | 서버에서 끝난 문서 기록(PG 원천 스키마 `doc`)을 못 읽음(전체 재파싱을 막으려고 멈춤) | `required.pg` 접속·PG 상태 확인 |
| 구조화·적재가 "인계 형식(핑거프린트) 다름"으로 거부 | 핑거프린트가 바뀐 옛 파싱 결과 | 그 문서를 다시 파싱 |
| 같은 결과 폴더에서 종료 75 | 다른 실행이 `.pipeline.lock`을 잡고 있음 | 끝날 때까지 기다리거나 다음 트리거에서 재시도 |
| 메모리 터짐(OOM), 큰 스캔 PDF | 쪽 이미지를 한꺼번에 올림 | `extract.page_render_dpi`(기본 150 — 더 낮추면 VLM 글 품질을 먼저 확인)·VLM 쪽 상한 `transform.vlm.vlm_max_pages_per_doc`·OCR 엔진 쪽 상한 `extract.ocr.ocr_max_pages_per_doc`·`extract.max_source_file_mb`·컨테이너 메모리 상한 확인 |
| CPU 폭주 | 컨테이너가 호스트 전체 코어로 스레드를 늘림 | `ops.runtime.engine_processes`는 `auto`(cgroup 한도 기준), 컨테이너 CPU 상한 지정 |
| MCP `/health` 503 | 기동 직후 예열 중 | 잠시 뒤 재시도 |
| MCP 401 | 호출 쪽 토큰이 없거나 `required.tokens.mcp_token`와 다름 | 호출 쪽 `Authorization: Bearer <토큰>`을 서버 값과 같게 |
| MCP가 안 뜸 | `required.models.embed_base_url`·`embed_model` 없음 · 컨테이너가 설정 파일을 못 읽음(권한) | 필수 값 채우기 · 주인 10001·권한 640 |
| 앱 컨테이너가 안 뜸("settings.yaml" 자리에 폴더) | `host_ctl.sh init` 전에 컨테이너를 띄워 빈 폴더가 생김 | 빈 폴더를 `rmdir` → `host_ctl.sh init` |
| 컨테이너가 `의존성 지문이 다름`으로 멈춤 | 코드의 `deploy/docker/DEPS_HASH`가 실행 이미지 지문과 다름 | 같은 지문의 실행 이미지를 불러온다([§4-4](#4-4-새-실행-이미지-불러오기--의존성-지문-확인)) |
| 포트 충돌 | 다른 서비스가 같은 포트 | `search.server.mcp_port` 등 포트 칸만 바꿈 |
| SELinux `Permission denied`(파일 권한·주인은 맞음) | 볼륨 라벨이 안 맞음 | 막힌 기록 보기 `ausearch -m avc -ts recent`(`denied { read }` 등과 파일 경로) · 라벨 보기 `ls -Z <폴더>`(`container_file_t`여야 함) · 우리 compose는 `:z`로 붙임 — 직접 붙인 볼륨이면 `:z` |
| SELinux — 원본 폴더가 NFS | NFS에는 `:z` 라벨을 붙일 수 없음 | `setsebool -P container_use_nfs 1`(서버 관리자) 뒤 컨테이너를 다시 띄움 |

### 3-11. 개발자에게 보고하는 법

운영 기록 폴더(벌 폴더 밖 — 판이 바뀌어도 이어 씀, 이하 `<기록>`)에 적는다.

#### 3-11-1. 서버 버전 기록
적용·업데이트마다(배포 판정이 통과하면) `<기록>/versions.md`에 한 줄: `날짜 · 서버 · 이미지 버전 · 코드 커밋 · 확인 결과`.

#### 3-11-2. 서버 자체 개발 기록
서버에서 코드를 직접 고치거나 새로 만들었거나 옵션 값을 바꿨으면 그때마다 `<기록>/server-changes.md`에 한 행 + diff를 `<기록>/server-changes/<ID>.diff`로(`diff -u <고치기 전> <고친 뒤>`, 새 파일이면 `diff -u /dev/null <파일>`). 새 판으로 바꿀 때 이 기록을 먼저 읽는다([§5-6](#5-6-서버에서-직접-고친-코드)).
```
| ID(SC-<MMDD>-<n>) | 날짜·시각 | 서버(수집/개발) | 바뀐 파일(코드 폴더 기준 경로) | 무엇·왜 한 줄 | 기준 버전(이미지+코드 커밋) | 테스트(명령·결과) | 상태(서버에만/PC 보냄/다시 얹음 <커밋>/PC 반영됨 <커밋>/폐기) |
```
지우지 않고 상태만 바꾼다. diff에는 코드만 — 비밀값·문서 본문·고객명은 넣지 않는다.

#### 3-11-3. 이슈 기록
문제가 나면 `<기록>/issues.md`에 한 행(지우지 않고 상태만 바꿈):
```
| ID(SI-<MMDD>-<n>) | 버전(이미지+코드 커밋) | 서버(수집/개발) | 단계·명령 | 증상 한 줄 | 종료 코드 | 로그 위치 | 상태(열림/수정됨/재확인 통과) |
```
반출 규칙: **오류 메시지·종료 코드·숫자·해시 이름만** — 문서 본문·고객명·원본 경로·키 값은 적지 않는다.

#### 3-11-4. 날짜별 요약
파싱이 끝날 때마다 `<기록>/<날짜>.md`에 버전(`versions.md` 줄)·단계·종료 코드·핵심 숫자(정답률·시간·건수)·막힌 곳·로그 마지막 20줄(비밀값 가림)을 적는다. 본문은 복사하지 않는다.

### 3-12. 로그 DB 살펴보기 — applog SQL(읽기만)

실행 기록은 PG `applog` 스키마에 있다(`pipe_run` 실행 1건 · `pipe_event` 단계 1건 · `mcp_log` MCP 호출 1건 · `except_doc_info` 적재 안 된 문서 — `skip` 영구 뺌·`error` 실패). 읽기 전용 거래 안에서만 본다:
```bash
$DOCKER exec -it <required.deploy.pg_container_name> psql -U <required.pg.pg_user> -d <required.pg.pg_database>
```
- ⚠️ `mcp_log.args`·`result`에는 질문·SQL·문서 원문이 들어 있다 — 아래처럼 필요한 칸만 고르고, 결과를 밖으로 옮기지 않는다.

**① 지난 7일 실패한 실행**
```sql
SELECT started_at, run_id, command, status, duration_ms / 60000 AS min,
       docs_total, docs_ok, docs_fail, docs_reused, app_version, host
FROM applog.pipe_run
WHERE started_at > now() - interval '7 days'
  AND (status IN ('fail', 'interrupted') OR docs_fail > 0)
ORDER BY started_at DESC;
```
`status`: `running`(도는 중 또는 죽음) · `ok` · `fail` · `stopped`(마감 도달) · `interrupted`.

**② 느린 단계** — 단계별 시간과, 하루 동안 가장 오래 걸린 단계 20건
```sql
SELECT layer, stage, count(*) AS n, round(avg(duration_ms)) AS avg_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms, max(duration_ms) AS max_ms
FROM applog.pipe_event
WHERE ts_start > now() - interval '7 days' AND duration_ms IS NOT NULL
GROUP BY layer, stage ORDER BY p95_ms DESC LIMIT 15;

SELECT ts_start, run_id, layer, stage, engine, model, doc_id, ext, file_bytes,
       duration_ms, wait_cpu_ms, wait_mem_ms, ext_call_ms, rss_peak_mb, status, err_kind
FROM applog.pipe_event
WHERE ts_start > now() - interval '1 day'
ORDER BY duration_ms DESC NULLS LAST LIMIT 20;
```
`wait_cpu_ms`·`wait_mem_ms`가 크면 자원 대기(CPU·메모리 문턱), `ext_call_ms`가 크면 모델 호출이 느린 것이다. 한 실행을 자세히: `$DOCKER exec data-pipeline-0 python -m pipeline.tools.perf_report <run_id>`.

**③ MCP 도구별 호출 수 · 오류율 · p95**
```sql
SELECT tool_name, count(*) AS calls,
       round(100.0 * count(*) FILTER (WHERE status <> 'ok') / count(*), 1) AS err_pct,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
FROM applog.mcp_log
WHERE requested_at > now() - interval '7 days' AND tool_name IS NOT NULL
GROUP BY tool_name ORDER BY calls DESC;

SELECT tool_name, status, error_code, count(*) AS n
FROM applog.mcp_log
WHERE requested_at > now() - interval '7 days' AND status <> 'ok'
GROUP BY tool_name, status, error_code ORDER BY n DESC;
```
`status`: `ok` · `error` · `denied` · `unauthorized`(토큰) · `busy`(동시 상한) · `timeout`.

**④ 적재 안 된 문서 — 종류·이유별**
```sql
SELECT except_type, reason, source_system, count(*) AS docs, sum(count) AS times_seen, max(last_seen) AS last_seen
FROM applog.except_doc_info
GROUP BY except_type, reason, source_system ORDER BY docs DESC;
```
`part`(수준 `warn`)는 안 문서를 일부 못 꺼낸 원본이다 — 이유에 못 꺼낸 안 파일 이름과 까닭(`encrypted`·`too_big`·`too_many`·`total_cap`·`no_unwrap`·`cannot_open`·`read_failed`)이 있고 문서 자체는 적재됐다. `silver`(수준 `warn`)는 실버만 게시되고 골드가 아직 없는 원본이다 — 골드 적재가 성공하면 그 행은 지워지므로, 남아 있으면 골드 실패·중단·실버까지만 실행이다. `skip` 풀어 주는 법(행 지우기 — DB 담당 승인)은 [env-guide 실행 기록](env-guide.md#0-0-실행-기록json-로그db-감사성능).

### 3-13. 건드리면 안 되는 것

서버에서 아래를 바꾸면 결과가 깨지거나 전체를 다시 처리해야 한다. 바꿔야 하면 먼저 승인을 받는다(역할은 [README 담당 연락처](../../README.md#0-읽기-전에--꼭-알아-둘-것)).

| 칸·파일 | 바꾸면 | 누가 승인 |
|---|---|---|
| `required.tokens.fulltext_sign_key` | 이미 발급한 원문 도구 `sfid`가 모두 무효 — 클라이언트가 가진 원문 링크가 깨진다 | 지금 담당자(클라이언트 담당에게 먼저 알림) |
| `required.models.embed_model` | 적재된 벡터와 모델이 달라 적재가 거부되고(종료 2) 벡터 검색이 막힌다 — 바꾸려면 새 스키마에 전부 다시 | 지금 담당자·모델 담당·DB 담당 |
| `required.pg.pg_schema` — 다른 판·다른 벌이 쓰던 스키마를 다시 쓰기 | 남의 표에 `migrate up`(0.1.0 스키마면 옛 표가 지워짐)·문서가 섞인다 | DB 담당 |
| 엔진 파일 `pipeline/transform/parse/engines/` | 엔진 지문이 바뀌어 그 엔진의 문서를 모두 다시 파싱한다 | 사람 검토 — 지금 담당자 |
| 프롬프트 `resources/prompts/` | 지시서 지문·LLM 캐시 열쇠가 바뀌어 모델을 다시 부르고 결과가 달라진다 | 사람 검토 — 지금 담당자 |
| MCP 도구 계약 — 도구 6개의 이름·입력·출력 | 외부 클라이언트가 깨진다 | 지금 담당자·클라이언트 담당 협의(새 판으로) |

---

## 4. 운영 중인 서버를 새 판으로 올리기

이미 돌고 있는 개발 서버(dev)·운영 서버(prd)를 새 판으로 바꾸는 순서다. 판은 **벌 폴더(코드 폴더)에 새 코드를 덮어써** 올린다. 판 번호와 상관없이 같은 순서이고, 예는 0.2.0 → 0.3.0이다. 명령은 root 셸, `<…>`는 그 서버 값으로 바꾼다. 값·비밀은 화면·기록에 남기지 않는다. `# 기대:` 줄이 나오지 않으면 다음 단계로 가지 않는다.

```
1 먼저 알 것 → 2 지금 판 확인 → 3 백업 → 4 새 실행 이미지 → 5 새 코드 덮어쓰기 → 6 설정 고치기
→ 7 DB 판 올리기 → 8 pgvector가 바뀔 때 → 9 다시 처리 → 10 올린 뒤 점검 → 11 되돌리기
```

### 4-1. 먼저 알 것

- 덮어쓰기 전에 벌 폴더를 벌 폴더 밖에 백업한다(§4-3 — 되돌리기용, 서버에서 고친 코드는 gitea에도 올린다). 예: 벌 폴더 `/home/sbl/sbl_data_parsing-main-1`.
- **이미지·코드 폴더·`run_pipeline.py`는 같은 때에 바꾼다**(서로 맞아야 함 — `run_pipeline.py`는 덮어쓴 코드 폴더 안의 것). 코드만 바뀐 판(`DEPS_HASH` 같음)은 이미지를 다시 만들지 않는다(§4-4의 이미지 두 줄만 건너뜀).
- 벌이 여럿이면 모두 같은 DB(기준 스키마)를 쓰므로 **모든 벌을 같은 판으로** 올린다. DB 판 올리기(§4-7)는 아무 벌 하나에서 한 번. 검색 DB는 같은 PG를 그대로 본다.
- 개발 서버에서 끝까지 한 번 한 뒤 운영 서버에서 같은 순서로 한다. 운영 서버는 개발 서버에서 구운 이미지를 쓴다([§5-4](#5-4-개발--운영--시험한-그대로-굽기)).
- 덮어쓰기 전에 `server-changes.md`의 `서버에만`·`PC 보냄` 행을 읽는다([§5-6](#5-6-서버에서-직접-고친-코드)).
- 그 판에서 무엇이 바뀌었는지는 [refactor.md](../refactoring/refactor.md)의 열린 C 항목(서버·사람이 할 일)과 릴리스 노트로 본다.
- 코드를 내부망 gitea에서 받거나 개발자별 벌로 바꾸려면 §6·§2-15(개발 서버만, 원할 때).
- **0.1.0 서버에서 올릴 때만:** 검색 판 `0002_search`가 0.1.0이 만든 옛 검색 표를 **지운다**. 0.1.0 DB에 그냥 `migrate up`을 하지 않는다 — 새 `required.pg.pg_schema`를 정하고 백업한 뒤 올린다. 그때 쓴 절차(옛 컨테이너 이름·설정 옮기기)는 [0.2.0 배포 기록](../history/deploy_0_2_0.md).

**0.3.0에서 바뀐 것(예)**

| 무엇 | 서버에 미치는 것 | 이 문서의 절 |
|---|---|---|
| 네 이미지에 개발 도구·opencode가 들어가고 패키지 목록이 바뀜 | 새 실행 이미지 필요(코드 폴더만으로는 못 바꿈) | §4-4 |
| applog 판 `0003_applog` — 적재 안 된 문서 표 `except_doc_info` · `0004_applog` — `pipe_event` 원천·`except_doc_info` 확장자·크기 칸 · 검색 판 `0006_search` — `doc` 처리 기록 칸 · `0007_search` — `doc` 찾기 색인 · EDW에 쓰지 않음(쓰기 계정·`parsing_meta_table` 칸 없앰) | 첫 `run_pipeline.py` 전에 `migrate up` · 옛 기록 옮기기 | §4-7 |
| 마스터 판 `0002_master` — 표 `glossary` 하나(옛 마스터 표 일곱 개를 지움), 원본 CSV 하나 `glossary.csv` | 서버 실명 자료를 `glossary.csv`로 옮김(`common.store.master convert`) · `migrate up --target master` 바로 뒤 `migrate master load` | §4-7 |
| settings.yaml 칸 이름 정리 · 맨 아래 선택 절 `option.devbox` | 옛 이름이 남으면 모든 명령이 시작 거부 | §4-6 |
| 벌 폴더 = 코드 폴더(`settings.yaml`·`output/`이 코드 폴더 안), 벌 번호 = 폴더 이름 끝 `-<숫자>`, 칸 `ops.host.instance_name` 지움 | 처음 한 번 옛 루트에서 옮김 · 그 칸이 남으면 시작 거부 | §4-5 · §4-6 |
| 개발자별 벌(폴더 이름 끝 번호)·gitea | 개발 서버만, 원할 때 | §2-15 · §6 |

**0.3.1에서 바뀐 것** — 코드 폴더만 바꾼다(실행 이미지·DB 판 그대로 — §4-4는 이미지 두 줄을 건너뛰고 §4-7은 `migrate check --target all`만).

| 무엇 | 서버에 미치는 것 | 이 문서의 절 |
|---|---|---|
| 코드가 읽지 않는 설정 칸 6개를 지움 | 서버 settings.yaml에 남으면 시작 거부 — §4-5 뒤, 컨테이너를 다시 띄우기 전에 지움 | §4-6 |
| 넘겨주기·레이어·엔진(office·kreuzberg·markitdown) 지문이 바뀜 | 모든 문서를 다시 처리(엑셀 날짜 칸이 `2026-11-29` 꼴로) | §4-9 |
| `except_doc_info`에 새 종류 `part`·`silver`, 골드 적재 성공 때 `silver` 행을 지움 | 적재 계정에 그 표 DELETE 권한(DB 담당 확인 — refactor.md C-111·C-112) | §4-7 |
| 배포 판정 시험이 서버 PG에 붙음(prd는 읽기만) | `host_ctl.sh check`에 PG 접속이 필요 | §4-10 |

**0.4.0에서 바뀐 것** — 새 실행 이미지가 필요하다(앱 컨테이너가 root로 돌고 root 비밀번호가 이미지에 들어감).

| 무엇 | 서버에 미치는 것 | 이 문서의 절 |
|---|---|---|
| 환경마다 compose 파일 하나(`compose-dev.yml`·`compose-prd.yml`·`compose-local.yml`) — 컨테이너 이름(`data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0` …)·이미지·포트·자원이 파일에 직접 | 옛 컨테이너를 내리고 새 이름으로 띄움 · 이미지·자원·컨테이너 칸을 settings.yaml에서 지움 | §4-6 · [§6-6](#6-6-서버-묶음--compose-파일과-root-ssh) |
| PG(`compose-pgvector.yml` — 서버 5433)·Redis(`compose-redis.yml` — 공식 `redis:7.4.8-alpine`, 서버 8010)를 서버마다 하나, 손으로 한 번 띄움 · 비밀번호는 코드 폴더 맨 위 `.env` | `mcp-redis`를 내리고 `redis`를 띄움 · `redis_password` 채움 | §4-6 · [§6-7](#6-7-redis--compose-redisyml) |
| 앱이 PG·Redis에 `host.docker.internal`로 붙음 · 검색 MCP는 컨테이너 안팎 8051 | settings.yaml `required.pg.pg_host`·`pg_port`, `search.server` 고침 | §4-6 · [§1-11](#1-11-밖에서-붙기다른-서버의-ai-클라이언트) |
| `edw_chain.yaml`이 코드 폴더 맨 위(git — 운영 이미지에 들어감) | 서버에서 고친 사본은 git 파일로 옮김 | §4-6 · [§3-9-2](#3-9-2-edw-조인-사슬-파일-고쳐-쓰기) |
| 타이머·keepalive·새벽 배치는 벌 0만(단위 이름 끝 번호 없음) | 옛 `-<번호>` 단위를 지우고 `host_ctl.sh timers` | §4-6 · §3-1 |

### 4-2. 지금 판 확인

```bash
export DOCKER=docker
cd <벌 폴더>                                                                  # 0.2.0 서버면 <옛 루트>/sbl_data_parsing-<앞 판>
cat VERSION CODE_COMMIT                                                       # 코드 폴더의 판·커밋
$DOCKER image inspect <이미지 태그> --format '{{json .Config.Labels}}'          # 이미지 라벨 — version(판)·revision(빌드 커밋)
$DOCKER logs data-pipeline-0 2>&1 | grep -m2 -E '^\[(image|code)\]'           # 시작 로그
bash deploy/host/scripts/pipe_exec.sh migrate current --target all            # DB 판
```
- 이미지 태그는 compose 파일의 `IMAGE_TAG`(파일 옆 `.env`가 있으면 그 값)다 — 떠 있는 것은 `docker ps --format '{{.Names}} {{.Image}}'`. 컨테이너 이름은 compose 파일에 적힌 그대로(`data-pipeline-<번호>`·`mcp-server-0`·`mcp-data-parsing-0`).

### 4-3. 백업

먼저 자동 실행을 멈추고, 도는 `run_pipeline.py`가 끝나길 기다린다(죽이지 않는다).
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer       # 서버에 하나씩(벌 0이 설치)
pgrep -af run_pipeline.py                                                     # 기대: 아무것도 안 나옴(나오면 끝날 때까지 기다림)

B=<벌 폴더>  PG_C=<required.deploy.pg_container_name>  PG_U=<required.pg.pg_user>  PG_D=<required.pg.pg_database>
S=<required.pg.pg_schema>
BK=<백업 폴더 — 벌 폴더 밖>/<앞 판>-$(date +%Y%m%d-%H%M); mkdir -p "$BK" && chmod 700 "$BK"
tar -czf "$BK/code.tar.gz" --exclude=./output --exclude=./home -C "$B" .      # 코드·settings.yaml(output/·home/은 덮어써도 남음)
$DOCKER exec "$PG_C" pg_dump -U "$PG_U" -d "$PG_D" -Fc -n "$S" -n "${S}_*" -n applog > "$BK/pg.dump"   # 검색(+ 원천 5벌·마스터)·applog
$DOCKER exec -i "$PG_C" pg_restore -l < "$BK/pg.dump" | grep -c ' TABLE '     # 기대: 0보다 큰 수 — 0이면 덤프 실패
```
- 0.2.0 서버는 설정이 코드 폴더의 부모에 있으므로 `B=<옛 루트>`로 루트째 묶는다(같은 명령).
- 벌마다 `code.tar.gz`, DB(`pg_dump`)는 모든 벌이 같이 쓰므로 한 번. PG·Redis 비밀번호 `.env`는 settings.yaml과 같은 값이라 settings.yaml과 함께 백업한다.
- 우리 스키마만 뜬다(공유 DB). `pg_dump`가 암호를 물으면 DB 담당과 함께 한다. applog는 MCP 호출 원문이 있어 클 수 있다 — 디스크를 먼저 본다(`df -h <백업 폴더>`).
- 백업 폴더에는 비밀값·DB 내용이 있다 — 권한 700 그대로, 밖으로 옮기지 않는다.

### 4-4. 새 실행 이미지 불러오기 · 의존성 지문 확인

새 코드가 요구하는 의존성 지문(`deploy/docker/DEPS_HASH`)과 같은 지문의 실행 이미지를 쓴다. 다르면 컨테이너가 `의존성 지문이 다름`으로 멈춘다.
```bash
cd <공용 폴더>                                                                # 예 /home/sbl
unzip -q <코드 zip>                                                           # 기대: sbl_data_parsing-<새 판>/ — §4-5가 이 폴더를 씀
cat sbl_data_parsing-<새 판>/deploy/docker/DEPS_HASH                          # 코드 지문
grep -H DEPS_HASH sbl_images-main/*/BUILD.txt                                 # 서버에 있는 이미지 판마다 지문 — 같은 값이 있으면 그 판을 쓰고 아래 두 줄은 건너뜀
unzip -q <새 이미지 저장소 zip>                                                # 같은 지문이 없을 때만 — sbl_images-main/
DOCKER=docker bash sbl_images-main/load.sh <이미지 판>                        # 기대: 조각 sha256 확인 → load → <판>/BUILD.txt(DEPS_HASH가 코드 지문과 같음)
```
- 0.3.0은 실행 이미지에 개발 도구가 들어가고 패키지 목록이 바뀌어 **새 실행 이미지가 꼭 필요하다**(0.2.0 실행 이미지로는 시작하지 않음). 코드만 바뀐 판(지문이 같음)은 이미지를 불러오는 두 줄만 건너뛴다(코드 zip 풀기는 한다). 같은 지문이 서버에 없으면 PC에서 새 실행 이미지를 만든다([§5-3](#5-3-pc에서--실행-이미지-만들기와-이미지-저장소에-올리기)).
- 운영 서버: 개발 서버에서 `bake_prod_image.sh`로 구운 조각을 옮겨 `load.sh <VERSION>`([§5-4](#5-4-개발--운영--시험한-그대로-굽기)).

### 4-5. 벌 폴더에 새 코드 덮어쓰기

> ⚠️ **0.2.0 서버(설정·결과가 코드 폴더의 부모에 있음)는 아래 첫 블록을 치지 않는다** — 옛 코드를 지워 되돌릴 수 없게 된다. 이 절 끝 "0.2.0 서버에서 처음 올릴 때만"으로 간다.

`B`는 §4-3에서 정한 벌 폴더다(새 셸이면 `B=<벌 폴더>`를 다시 적는다). §4-4에서 푼 `sbl_data_parsing-<새 판>/`이 공용 폴더에 있어야 한다.
```bash
cd <공용 폴더>
T=deploy/host/scripts/test_space
[ ! -e "$B.test_space" ] || { echo "[멈춤] $B.test_space가 이미 있음 — 아래 '중간에 끊겼을 때'대로 먼저 되돌린다" >&2; false; } &&
  { [ ! -d "$B/$T" ] || mv "$B/$T" "$B.test_space"; } &&   # run_pipeline 작업 폴더(진행 기록·잠금)를 잠시 밖으로 — 아래 find가 deploy/를 지움
  find "$B" -mindepth 1 -maxdepth 1 ! -name .git ! -name output ! -name home ! -name "settings*" ! -name .env -exec rm -rf {} + &&   # 옛 코드만 지움
  cp -a sbl_data_parsing-<새 판>/. "$B/" && rm -rf sbl_data_parsing-<새 판> &&   # 벌 폴더 위에 새 코드
  { [ ! -d "$B.test_space" ] || mv "$B.test_space" "$B/$T"; }   # 작업 폴더 되돌려 놓기
cd "$B"
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>                # 기대: "[host_ctl init] 루트: $B" — 있는 설정 파일은 덮지 않음 · 코드 a+rX(컨테이너 사용자 10001이 못 읽으면 "읽을 수 없음(권한)"으로 멈춤)
cat CODE_COMMIT                                                               # 기대: 그 판의 커밋
```
- 코드 zip 대신 코드 묶음(`code-<버전>-<커밋>.tar.gz` — [§5-3](#5-3-pc에서--실행-이미지-만들기와-이미지-저장소에-올리기))이면 `cp -a` 줄 대신 `tar -xzf code-….tar.gz --no-same-owner -C "$B"`.
- `settings.yaml`·`output/`(파싱 캐시·임베딩 캐시·FAQ 교체 기록 — 잃으면 전부 다시 처리)·`home/`은 zip에 없어 덮어써도 남는다. 지우거나 옮기지 않는다. `deploy/host/scripts/test_space/`(run_pipeline 진행 기록·잠금)는 `deploy/` 안이라 그대로 두면 find가 지운다 — 위 명령이 옮겼다 되돌려서 남는다(`ops.run_pipeline.run_pipeline_work_dir`를 코드 폴더 밖에 두었으면 그 단계는 아무것도 안 함).
- **중간에 끊겼을 때**(`[멈춤] … 이미 있음`): 지난 덮어쓰기가 되돌리기 전에 끊겼다는 뜻이다. `$B/$T`가 없으면 `mkdir -p "$B/deploy/host/scripts" && mv "$B.test_space" "$B/$T"`로 먼저 되돌린 뒤 위 명령을 다시 친다. `$B/$T`도 있으면 두 폴더의 `batch_progress/progress.log`를 보고 하나만 남긴다.
- 옛 코드를 먼저 지우는 까닭: 새 판에서 지운 파일(옛 시험 등)이 남으면 selftest(`host_ctl.sh check`)가 그 파일 때문에 실패한다.
- compose 파일 옆 `.env`(`deploy/host/compose/.env` — 이미지 판 `IMAGE_TAG` 등)를 두었으면 find가 지운다 — 덮어쓴 뒤 다시 만든다(새 판의 기본 `IMAGE_TAG`가 맞으면 두지 않는다).
- 서버에서 고친 파일은 새 판 내용으로 바뀐다 — 필요하면 덮어쓴 뒤 다시 얹는다([§5-6](#5-6-서버에서-직접-고친-코드)).
- **0.2.0 서버에서 처음 올릴 때만**(설정·결과가 코드 폴더의 부모 `<옛 루트>`에 있음): 덮어쓰지 않고 새 벌 폴더를 만들어 옛 루트에서 옮긴 뒤 위 `init`부터 한다. 옛 루트는 되돌리기용으로 그대로 둔다.
```bash
cd <공용 폴더> && unzip -q <코드 zip> && mv sbl_data_parsing-<새 판> sbl_data_parsing-main-0   # 운영 서버면 번호 없이 sbl_data_parsing-main
B=<공용 폴더>/sbl_data_parsing-main-0
cp -p <옛 루트>/settings.yaml "$B/" && cp -a <옛 루트>/output "$B/"
```
  옛 루트의 `edw_chain.yaml`을 고쳐 썼으면 그 내용을 새 코드 폴더 맨 위 `edw_chain.yaml`에 얹는다([§3-9-2](#3-9-2-edw-조인-사슬-파일-고쳐-쓰기)).
- 띄울 이미지 판은 compose 파일의 `IMAGE_TAG`다 — 새 판의 기본값과 다르면 `deploy/host/compose/.env`에 `IMAGE_TAG=<판>`을 적는다.

### 4-6. 설정 고치기

컨테이너를 새 코드로 띄우기(§4-7) 전에 한다. 벌 폴더의 `settings.yaml`을 새 판의 `settings.sample.yaml`과 대조해 고친다. 옛 이름·지운 칸·모르는 칸이 하나라도 있으면 모든 명령이 시작을 거부하고 칸 이름만 알린다(값은 안 찍음).

벌 폴더에서(§4-5 뒤 — 새 코드가 이미 벌 폴더에 있음) 순서대로 친다. 벌이 여럿이면 벌마다 한다. `B`·`DOCKER`는 §4-2·§4-3에서 정한 값이다(새 셸이면 다시 적는다).
```bash
cd "$B"
cp -p settings.yaml settings.yaml.bak-$(date +%Y%m%d-%H%M)

grep -noE '^[[:space:]]*(skipped_docs_log|secure_doc|source_column_content_version|embed_query_cache_file|embed_query_cache_max_rows|pg_standin|instance_name|edw_write_user|edw_write_password|parsing_meta_table|pipeline_image|mcp_image|compose_project|redis_image|redis_mem_limit|redis_data_dir|host_edw_chain_file|extra_compose|host_output_dir|containers|[a-z_]+_container_name|[a-z_]+_cpus|[a-z_]+_mem_limit|data_parsing_cpu_shares|ssh_port|opencode_config|home_dir|gitea_url|gitea_user|gitea_token)[[:space:]]*:' settings.yaml   # pg_container_name 줄은 남긴다

vi settings.yaml        # :<줄 번호> 로 가서 dd · 저장 :wq

IMG=<새 실행 이미지>    # dev: data-pipeline-runtime:<이미지 판> · prd: data-pipeline:<VERSION>
$DOCKER run --rm --entrypoint python -v "$PWD:/app/deploy:ro,z" \
  -v "$PWD/settings.yaml:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml \
  "$IMG" -m pipeline.config >/dev/null && echo 설정-읽힘

$DOCKER run --rm --entrypoint python -v "$PWD:/app/deploy:ro,z" "$IMG" -m common.config.sample --where <옛 이름>

chown 10001:<운영 그룹> settings.yaml && chmod 640 settings.yaml
```
- 호스트 스크립트(`load_settings.sh` — 호스트 셸이 쓰는 칸만 꺼냄)는 모르는 칸을 보지 않는다 — 설정 확인은 `설정-읽힘` 줄로 한다.
- 빈 절(예: 칸을 다 지워 `extract:`만 남음)은 그대로 두어도 된다.
- `설정-읽힘`이 나온 뒤 백업 파일 `settings.yaml.bak-*`은 §4-10 점검까지 끝나면 지운다(비밀값이 들어 있음).
- **칸 이름이 바뀌었다** — 옛 → 새 전체 표는 [refactor.md 부록 — 칸 이름 대응표](../refactoring/refactor.md#부록--설정-칸-이름-대응표)(1차 표의 새 이름이 2차 표의 옛 이름 — 둘 다 옮김).
- **서버 settings.yaml에서 지울 칸** — 코드가 읽지 않아 지운 칸이다(남으면 모르는 칸으로 시작 거부):

  | 지울 칸(전체 이름) | 언제 지운 칸 | 까닭 |
  |---|---|---|
  | `required.deploy.pipeline_image` · `required.deploy.mcp_image` | 0.4.0 | 이미지는 compose 파일의 `IMAGE_TAG` |
  | `ops.host.compose_project` | 0.4.0 | compose 묶음 이름은 파일의 `name:`(`sbl-devset`·`sbl-prd`) |
  | `ops.host.redis_image` · `ops.host.redis_mem_limit` · `ops.host.redis_data_dir` | 0.4.0 | Redis는 `compose-redis.yml`(공식 이미지 · 자원·데이터 폴더가 파일에) |
  | `ops.host.host_edw_chain_file` | 0.4.0 | `edw_chain.yaml`은 코드 폴더 맨 위(git — 이미지에 들어감) |
  | `ops.host.extra_compose` | 0.4.0 | 덧붙임 compose 파일 없음 — 볼륨·env는 `compose-<환경>.yml`에 직접 |
  | `ops.host.host_output_dir` | 0.4.0 | 결과 폴더는 늘 `<루트>/output` |
  | `ops.containers.pipeline.pipeline_container_name` · `pipeline_cpus` · `pipeline_mem_limit` | 0.4.0 | 컨테이너 이름·자원은 compose 파일에 직접 |
  | `ops.containers.data_parsing.data_parsing_container_name` · `data_parsing_cpus` · `data_parsing_mem_limit` · `data_parsing_cpu_shares` | 0.4.0 | 같음 |
  | `ops.containers.mcp.mcp_container_name` · `mcp_cpus` · `mcp_mem_limit` | 0.4.0 | 같음 |
  | `option.devbox.ssh_port` · `option.devbox.opencode_config` · `option.devbox.home_dir` | 0.4.0 | SSH 포트·홈은 compose 파일(홈 `<벌 폴더>/home` → `/root`) · opencode 설정은 저장소 루트 `opencode.jsonc` |
  | `option.devbox.gitea_url` · `gitea_user` · `gitea_token` | 0.4.0 | 쓰지 않음 — gitea 로그인은 컨테이너 안에서 직접(§6-3) |
  | `extract.skipped_docs_log` | 0.3.1 | 건너뛴 문서 기록은 늘 `<준비 폴더>/_records/skipped.jsonl`(게시 단계가 읽는 자리) |
  | `extract.secure_doc`(절 통째 — 안에 `secure_doc_passwords_file`) | 0.3.1 | 읽는 곳이 없음(암호 문서는 건너뜀) |
  | `tuning.extract.source_columns.source_column_content_version` | 0.3.1 | 판 ID 열은 읽지 않음(증분 판정 열은 `source_column_increment`) |
  | `common.models.embed.embed_query_cache_file` · `tuning.common.models.embed.embed_query_cache_max_rows` | 0.3.1 | 검색 질의 임베딩 캐시는 프로세스 안 메모리(2048개)라 파일·행 상한 칸이 없음 |
  | `dev.pg_standin`(절 통째) | 0.3.1 | sqlite 대역을 지웠다(PG 접속 필수) |
  | `ops.host.instance_name` | 0.3.0 | 벌 번호는 코드 폴더 이름 끝 `-<숫자>`. PG 스키마·게시 경로에 붙던 `_<벌>`도 없어져 모든 벌이 `required.pg.pg_schema` 그대로를 쓴다(옛 벌 스키마는 더 쓰지 않음 — 남은 스키마는 DB 담당과 정한다) |
  | `edw_write_user` · `edw_write_password` · `parsing_meta_table` | 0.3.0 | 파이프라인이 EDW에 쓰지 않음(§4-7) |

- **엔진 구성 파일** `resources/config/pipeline_stack.json`은 코드 폴더 안이라 §4-5에서 새 판으로 바뀐다. 서버에서 고친 옛 파일을 다시 덮어 쓰면 그 파일의 `retrieve`·`k` 칸을 지운다(모르는 칸이면 읽기 거부). 확인: `$DOCKER run --rm --entrypoint python -v "$PWD:/app/deploy:ro,z" "$IMG" -m pipeline.cli show-stack` — 엔진 표가 나오면 통과.
- **선택 절 `option.devbox`**(파일 맨 아래) — SSH 작업 공간의 git 이름·메일(`git_user_name`·`git_user_email`). 비우면 설정하지 않음. 옛 판의 `gitea_url`·`gitea_user`·`gitea_token` 줄이 남아 있으면 모르는 칸으로 시작이 거부되니 지운다. 쓰는 법은 [§2-13](#2-13-개발-작업-공간--sshopencode선택).
- **경로 칸은 컨테이너 안 절대 경로로** 적고, 쓰는 자리는 `/app/output/…` 아래여야 한다 — [env-guide §5](env-guide.md#5-서버-경로-칸--컨테이너-안-절대-경로).
- `설정-읽힘` 확인을 건너뛰어도 §4-7에서 컨테이너가 뜰 때 같은 칸 이름을 알리고 멈춘다 — 고치고 다시 띄운다.

**compose 파일 하나로 옮기기(한 번 — 옛 묶음을 쓰던 서버)** — 컨테이너 이름·이미지·자원을 settings.yaml 칸으로 정하던 옛 배치(덧붙임 compose 파일 여럿 · `mcp-redis`)에서 환경마다 compose 파일 하나(`compose-<환경>.yml`)와 서버마다 PG·Redis 하나로 옮긴다. 비밀번호 값은 어느 단계에서도 화면에 찍지 않는다.

1. **(§4-5 전에 — 옛 코드로)** 타이머를 끄고 옛 컨테이너를 내린다. 진행 중인 `parse_document` 작업이 끝난 뒤 한다.
   ```bash
   systemctl disable --now mcp-server-keepalive.timer data-pipeline-nightly.timer   # 옛 이름 끝 -<번호> 단위가 있으면 그것도 — 단위 파일은 rm /etc/systemd/system/<단위> 뒤 systemctl daemon-reload
   cd <옛 벌 폴더> && bash deploy/host/scripts/host_ctl.sh down                     # 벌마다 — 옛 묶음(data-pipeline·mcp-data-parsing·mcp-server·mcp-redis)
   docker ps -a --format '{{.Names}}'                                                # 남은 옛 컨테이너(예 data-pipeline-1)는 docker rm -f <이름> — 결과 폴더·DB는 남음
   ```
2. settings.yaml을 고친다 — 아래 "서버 settings.yaml에서 지울 칸"을 지우고, 채울 칸:
   - `common.connections.redis.redis_password` — 서버마다 새 값(`openssl rand -hex 32`). `redis_host`·`redis_port`는 비운다(기본 `host.docker.internal`·`8010`).
   - `required.pg.pg_host: host.docker.internal` · `pg_port: 5433`(`compose-pgvector.yml`로 띄울 때 — DB 담당이 따로 둔 PG면 그 값 그대로).
   - 벌 0(운영은 그 한 벌) `search.server`: `mcp_bind_host: auto` · `mcp_port: 8051` · `mcp_allowed_hosts: <서버 IP>:8051`.
   - `ops.paths.edw_chain_file`에 `/etc/rag/edw_chain.yaml`을 적었으면 지운다(비움 = 코드 폴더 맨 위 `edw_chain.yaml`).
3. 비밀번호: 벌 0 코드 폴더 맨 위에 `.env`를 만들어 `REDIS_PASSWORD`·`PG_USER`·`PG_DB`·`PG_PASSWORD`를 settings.yaml과 같은 값으로 적고 `chmod 600 .env`. 손으로 만든 옛 비밀번호 파일(`<공용 폴더>/pg_pw`·`redis_pw`·`root_pw`), 앞 판의 `<공용 폴더>/secrets/`, 옛 Redis 설정 폴더(`<루트>/redis-conf`), 앞 판이 Redis 데이터 폴더에 복사해 둔 `<REDIS_DATA>/redis.conf`(기본 `/data/redis/redis.conf` — 비밀번호가 들어 있음)는 더 쓰지 않으니 지운다. 비밀번호가 맞는지는 `host_ctl.sh check`의 첫 단계가 본다. root SSH 비밀번호는 이미지에 들어간다([§6-6](#6-6-서버-묶음--compose-파일과-root-ssh)).
4. PG: 옛 `pgvector` 컨테이너를 멈추고 지운 뒤(`docker stop pgvector && docker rm pgvector` — 데이터 폴더는 그대로) `docker compose --env-file .env -f deploy/host/compose/compose-pgvector.yml up -d`(같은 데이터 폴더 `PG_DATA` — 기본 `/data/pg/pipeline`). `.env`의 계정·비밀번호는 빈 데이터 폴더에서만 쓰이므로 `.env`·settings.yaml의 값이 기존 DB 계정·비밀번호와 같아야 한다. docker 볼륨이었으면 멈춘 뒤 `docker volume inspect <볼륨> --format '{{.Mountpoint}}'` 폴더의 내용을 데이터 폴더로 복사한다.
5. Redis: `docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d` → `docker ps --filter name=^redis$`(기대 `healthy`). 옛 `mcp-redis`의 데이터는 옮기지 않는다(작업 큐 — 1에서 작업이 끝난 뒤라 비어 있음).
6. EDW 사슬: 서버에서 고친 `<루트>/edw_chain.yaml` 사본이 있었으면 §4-5 전에 밖으로 복사해 두고, 그 내용을 새 코드 폴더 맨 위 `edw_chain.yaml`에 얹어 git으로 커밋한다([§3-9-2](#3-9-2-edw-조인-사슬-파일-고쳐-쓰기)) — 새 판은 사본을 따로 붙이지 않는다.
7. 덧붙임 compose 파일(`ops.host.extra_compose`로 붙이던 `compose.extra.yml` 등)이 있었으면 그 볼륨·env를 `compose-<환경>.yml`의 칸에 옮겨 적고(git 커밋) 지운다. 컨테이너 자원을 settings.yaml에 적어 두었으면 그 값을 compose 파일의 `cpus`·`mem_limit`에 옮긴다.
8. 앱: `bash deploy/host/scripts/host_ctl.sh up -d` → 벌 0 폴더(운영은 그 한 벌)에서 `host_ctl.sh timers`(이름 끝 번호 없는 단위 4개) → §4-10 점검.

새 판에서 없어진 파일: 옛 compose 파일 10개(`compose.pipeline.yml`·`compose.data-parsing.yml`·`compose.mcp-server.yml`·`compose.code.yml`·`compose.code.data-parsing.yml`·`compose.code.mcp-server.yml`·`compose.dev.yml`·`compose.opencode.yml`·`compose.redis.yml`·`extra.example.yml`), `deploy/docker/Dockerfile.redis`와 `deploy/docker/redis/`(이미지 `sbl-redis`는 더 쓰지 않음 — 공식 `redis:7.4.8-alpine`), `resources/config/edw_chain.yaml`(→ 코드 폴더 맨 위 `edw_chain.yaml`).

### 4-7. DB 판 올리기 — `migrate up`

```bash
bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline-0   # 벌 0 폴더(운영은 그 한 벌)에서 — pipe_exec.sh가 이 안에서 돈다
bash deploy/host/scripts/pipe_exec.sh migrate current --target all
bash deploy/host/scripts/pipe_exec.sh migrate up --target applog
bash deploy/host/scripts/pipe_exec.sh migrate up --target search                # 0.3.0: 원천 스키마 5벌 doc에 처리 기록 칸(0006_search)·찾기 색인(0007_search)
bash deploy/host/scripts/pipe_exec.sh migrate up --target master                # 0.3.0: 표 glossary 하나로(0002_master — 옛 마스터 표를 지움)
bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary   # 바로 채움(샘플이면 --dir 없이) — 비어 있으면 구조화·검색이 시작하지 않음
bash deploy/host/scripts/pipe_exec.sh migrate check --target all              # 기대: 갈래마다 "판 끝 [...] · 코드의 끝 판 ...", 종료 코드 0
```
- **applog는 모든 벌이 함께 쓴다 — 첫 벌에서 `migrate up --target applog`를 끝낸 뒤에 다른 벌을 새 코드로 바꾼다.** 첫 벌은 위 첫 줄로 새 코드를 띄운 다음 바로 올린다. 그 사이도 없애려면 DB 담당이 `--sql` 파일(아래)을 코드를 바꾸기 전에 손으로 실행한다. 판 `0004_applog` 전의 applog에는 새 코드의 사건 행(`source_system` 칸)이 들어가지 못해 그 벌의 applog 기록이 모두 파일 대체 기록(`output/logs/*.jsonl`)으로 가고, 적재 안 된 문서 기록(`except_doc_info`)은 칸 없음으로 실패한다.
- DB 담당이 SQL을 먼저 보고 손으로 실행하려면: `bash deploy/host/scripts/pipe_exec.sh migrate up --target applog --from 0001_applog --sql /app/output/up_applog.sql`(DB·접속 정보 없이 — 스키마 이름만 설정에서 · `<벌 폴더>/output/`에 다 만든 뒤 한 번에 씀 · `--from` = `migrate current`가 보인 지금 판, 갈래마다 — 없는 갈래는 빈 스키마부터라 경고 줄과 `-- 주의:` 주석이 나온다 · 차원을 읽는 판(`0001_search`·`0002_search`)이 들면 `--dim`이 필요). DB를 읽어야 하는 확인(지금 판·vector 확장·남의 스키마·차원)은 파일 안 `-- 수동:` 줄이다. 손으로 실행한 뒤 `migrate check --target all`.
- 갈래(`--target`)마다 따로 올리면 어느 갈래가 바뀌었는지 출력에서 바로 보인다. 한 번에는 `--target all`. 명령 하나하나의 뜻·오류 분기(종료 2)는 [§1-8](#1-8-db-표-만들기--migrate).
- 벌이 여럿이면 벌 0에서 한 번 — 다른 벌은 §4-5·§4-6 뒤 §4-10만 한다.
- 0.3.0의 applog `0003_applog`는 새 표 `except_doc_info`를 만들고 옛 `skip_doc_info` 행을 `skip`으로 옮긴다. `0004_applog`는 `pipe_event`에 `source_system`, `except_doc_info`에 `file_ext`·`file_size` 칸을 더한다(옛 행은 비움). search `0006_search`는 `doc`에 처리 기록 칸(`sha256`·`silver_bucket`·`silver_key`·`engines`·`parse_status`·`silver_version`·`gold_version`·`parsed_at`·`loaded_at`)을 더하고, `0007_search`는 `doc`에 찾기 색인 3개(`sha256` · `silver_bucket`+`silver_key` · `file_path`)를 만든다(행이 많으면 만드는 동안 그 `doc`에 쓰기가 잠깐 막힌다 — 실행 중인 적재가 없을 때). **첫 `run_pipeline.py` 전에** 둘 다 올린다 — 없으면 대상 목록·받기가 표 없음으로 멈춘다.
- 0.3.0 사람이 할 일(DB 담당과): EDW `AI.ParsingMeta`에 있던 처리 기록을 `doc` 새 칸으로 손으로 옮긴다(파이프라인은 EDW에 더 쓰지 않고, `doc` 행이 있으면 끝난 문서로 본다). 옮긴 것을 확인한 뒤 옛 표 `applog.skip_doc_info`를 지운다(마이그레이션은 지우지 않음). settings.yaml에 `edw_write_user`·`edw_write_password`·`parsing_meta_table` 칸이 남아 있으면 시작을 거부하므로 지운다.
- 0.3.0의 master `0002_master`는 표 `glossary`를 만들고 옛 마스터 표(`client_roster`·`domain_terms`·`id_patterns` 등 일곱 개)를 지운다(되돌리기 없음 — 먼저 마스터 스키마 백업). `master load`는 `glossary.csv` 하나만 읽으므로 **올리기 전에** 서버 실명 자료(옛 CSV)를 `glossary.csv`로 옮겨 둔다(`$DOCKER exec data-pipeline-0 python -m common.store.master convert --src /app/output/glossary --out /app/output/glossary/glossary.csv` — [§3-9-1](#3-9-1-고객-명부용어집-작성법), refactor.md C-108).
- `올린 뒤에도 차이:`가 나오거나 종료 2이면 멈추고 출력(이름만)을 DB 담당과 본다.

### 4-8. pgvector가 바뀔 때 — 두 경우

검색 DB에 들어가는 것을 바꾸는 방법은 둘이다. 어느 쪽으로 할지는 사람이 정한다.

**(가) 문서 메타 키만 — 스키마 그대로.** 문서 메타는 `doc.attrs`(JSON 칸) 하나에 들어가므로 키를 더하거나 EDW 칸을 바꿔도 표는 그대로다.
1. 코드 폴더 맨 위 `edw_chain.yaml`의 `fields`를 고쳐 커밋한다(법: [§3-9-2](#3-9-2-edw-조인-사슬-파일-고쳐-쓰기)).
2. 점검: `$DOCKER exec data-pipeline-0 python -m pipeline.load.edw_doc_meta --check` — 기대 `[edw_meta] 사슬 설정 OK(…)`, 종료 코드 0.
3. 이미 적재한 문서는 값이 저절로 차지 않는다 — 영향받는 원천의 문서를 §4-9의 순서로 `--replace` 다시 적재한다.

**(나) 표 구조(표·칸·색인)를 바꿀 때.** 새 마이그레이션 판(`common/store/db/migrations/versions/`)이 필요하다. DB 스키마 변경이라 **사람 검토와 DB 담당 합의가 먼저**다. 올리는 법은 둘 중 하나:

| 방법 | 순서 | 좋은 점 · 조심할 점 |
|---|---|---|
| 그 자리에서 올리기 | §4-3 백업 → §4-7 `migrate up --target search` → `migrate check` | 다시 적재가 필요 없을 수 있다 · 되돌리려면 백업 복원(§4-11) |
| 새 스키마에 전부 다시 | settings.yaml `required.pg.pg_schema`를 새 이름으로 → `migrate up --target all --dim <임베딩 차원>` → `migrate master load` → 전체 다시 처리(§4-9) → 검색 MCP를 새 스키마로 다시 띄움(`host_ctl.sh up -d --force-recreate mcp`) | 옛 스키마가 그대로 남아 되돌리기가 쉽다 · 전체 재처리 시간·디스크가 든다. 옛 스키마는 확인 뒤 DB 담당이 백업하고 지운다 |

- 임베딩 모델을 바꾸는 것도 (나)의 새 스키마 쪽이다 — 적재는 모델이 다른 묶음을 같은 스키마에 넣지 않는다.

### 4-9. 다시 처리할 층과 명령

판이 바뀌어도 **이미 처리한 문서는 저절로 다시 처리되지 않는다.** 레이어 코드 지문은 실행 기록(`applog.pipe_run.code_fp`)에 남기기만 하고 재처리를 일으키지 않는다. 다시 할 문서와 층은 사람이 정해 아래 명령으로 돌린다.

| 바뀐 것 | 다시 할 층 |
|---|---|
| 사슬 파일(문서 메타) · 마스터 표(고객 명부·용어집) | 구조화 + 적재(`--replace`) |
| 청크·임베딩 쪽 코드 · 임베딩 모델 | 구조화 + 적재(모델이면 새 스키마 — §4-8 (나)) |
| 파싱 엔진·대표 결과 고르기 | 파싱부터 전부(게시 포함) — `run_pipeline.py` |

**`--skip-done`:** 끝난 문서(원천 스키마 어디든 gold `doc` 행이 있는 원본 키)와 `applog.except_doc_info`의 `skip` 문서를 대상에서 뺀다. 새 문서만 돌릴 때 쓰고(새벽 배치가 이것), 다시 처리할 때는 주지 않는다.

**구조화 + 적재만 다시(게시 없이).** 서버는 문서가 끝나면 작업 폴더(`_docflow/<번호>/`)를 지우므로 묶음이 남아 있지 않다. 그 문서를 파싱해 묶음을 다시 만들고 `--replace`로 적재한다(Object Storage에는 다시 쓰지 않음).
```bash
R=/app/output/redo
$DOCKER exec data-pipeline-0 python -m pipeline.cli --set PIPE_OUT_ROOT=$R parse --source rdb:csv:$R/list.csv --src $R/prepared
$DOCKER exec data-pipeline-0 python -m pipeline.transform.structure.gold_bundle --set PIPE_OUT_ROOT=$R \
    --parse-dir $R/parse --src $R/prepared --out $R/bundle
$DOCKER exec data-pipeline-0 python -m pipeline.load.pgvector_load --set PIPE_OUT_ROOT=$R \
    load --bundle $R/bundle --rep-dir $R/parse/_rep --replace                  # 기대: 종료 코드 0
```
- 끝나면 `<결과 폴더>/redo/`를 지운다(원본 사본이 들어 있음).
- `--replace`는 판 표가 있는 우리 스키마에서만 된다. 적재는 묶음에 없는 문서를 지우지 않는다.

**파싱부터 전부.** `python3 deploy/host/scripts/run_pipeline.py`를 `--skip-done` 없이 돌린다(문서 몇 개만이면 `--seqs <번호,…>`). 게시를 다시 하므로 Object Storage에 같은 문서가 새 날짜 이름으로 한 벌 더 생긴다. 적재는 같은 문서를 건너뛰므로 gold까지 바꾸려면 새 스키마에 적재한다(§4-8 (나)).

### 4-10. 올린 뒤 점검

```bash
bash deploy/host/scripts/host_ctl.sh up -d --force-recreate                   # 그 compose 파일의 앱 컨테이너 모두
bash deploy/host/scripts/host_ctl.sh logs data-pipeline-0 2>&1 | grep -m1 '^\[image\]'   # 기대: [image] 이미지 <이름 버전 커밋> · 코드 <커밋> · 의존성 <지문>
bash deploy/host/scripts/host_ctl.sh check                                    # 기대 마지막 줄: [host_ctl check] 통과 — 7개
curl -s http://127.0.0.1:8051/health                                          # 기대: {"ok":true,"ready":true,"store":"pgvector",…}
bash deploy/host/scripts/pipe_exec.sh parse --source-limit 3                  # 원본 3건 파싱 — 기대: 종료 코드 0
bash deploy/host/scripts/pipe_exec.sh publish --dry-run > /tmp/dry.json; grep -c 'CRMS/CRMS/' /tmp/dry.json; rm /tmp/dry.json
```
- `의존성 지문이 다름`으로 멈추면 그 코드는 새 실행 이미지가 필요하다(§4-4).
- 컨테이너 안 코드가 있는지 파일로 본다(bind 마운트 원본이 없으면 빈 폴더가 붙어 `test -d`는 통과하므로):
```bash
for c in data-pipeline-0 mcp-data-parsing-0; do   # 개발 서버는 벌마다 data-pipeline-<번호>도
 $DOCKER exec $c test -f /app/deploy/pipeline/transform/parse/parse_engines.py && echo "$c OK" || echo "$c 코드 없음(빈 마운트?)"; done
```
- MCP 클라이언트로 `search` 한 번(원천 `source_system` 필수) 뒤 로그 행이 생기는지:
```bash
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT tool_name, status, requested_at FROM applog.mcp_log ORDER BY requested_at DESC LIMIT 3"
```
- 처음 게시하는 서버면 실제 처리(게시·적재) 한 번 뒤 `doc` 처리 기록과 Object Storage 파일을 본다:
```bash
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT file_path, parse_status, silver_bucket, silver_key, parsed_at, gold_version FROM <pg_schema>_<원천>.doc ORDER BY loaded_at DESC NULLS LAST LIMIT 5"
$DOCKER exec data-pipeline-0 python -c "import sys; from common.store.objectstore import client; r=client().list_objects_v2(Bucket=sys.argv[1], Prefix=sys.argv[2]); [print(o['Key'], o['Size']) for o in r.get('Contents', [])]" <silver_bucket> <silver_key의 폴더>
```
- 실제 publish는 한 번만 한다(다시 돌리면 Object Storage에 같은 결과가 새 시각 이름으로 또 올라감).
- 다 되면 자동 실행을 다시 켠다(단위 틀이 바뀌었을 수 있어 이 코드 폴더로 다시 씀): `bash deploy/host/scripts/host_ctl.sh timers` → `versions.md`에 한 줄([§3-11-1](#3-11-1-서버-버전-기록)).

### 4-11. 되돌리기

**코드·설정:** §4-3의 `code.tar.gz`로 벌 폴더를 되살린다. 새 판에만 있는 파일(새 마이그레이션 판 등)이 남지 않게 덮지 않고 새 폴더에 푼다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
pgrep -af run_pipeline.py                                                     # 기대: 없음(있으면 끝날 때까지 기다림)
cd "$B" && bash deploy/host/scripts/host_ctl.sh down
mv "$B" "$B.new" && mkdir "$B" && tar -xzf "$BK/code.tar.gz" -C "$B"         # 앞 판 코드·설정
mv "$B.new/output" "$B/"; [ -d "$B.new/home" ] && mv "$B.new/home" "$B/"     # 결과·홈은 그대로 옮김
cd "$B" && bash deploy/host/scripts/host_ctl.sh up -d --force-recreate        # 앞 판의 compose 파일로
bash deploy/host/scripts/host_ctl.sh timers
```
- `$B.new`(새 판 코드)는 확인 뒤 사람이 지운다.
- 벌이 여럿이면 모든 벌을 같은 판으로 맞춘다(같은 기준 스키마).
- 0.2.0에서 처음 올렸다면(§4-5 마지막) 옛 루트가 그대로 있다 — 새 벌 폴더에서 `host_ctl.sh down` 뒤 `<옛 루트>/sbl_data_parsing-<앞 판>`에서 `host_ctl.sh up -d --force-recreate …` → `host_ctl.sh timers`.

**DB:** 새 판이 DB 판을 올렸으면 옛 코드는 그 판을 모른다 — 적재·`migrate`가 "이 코드가 모르는 판"으로 종료 2(0.3.0의 applog `0004_applog`면 매일 하는 `migrate maintain --target applog`가 멈춘다). 내리는 명령(downgrade)은 없으니 **백업에서 그 스키마를 되살린다** — DB 담당과 함께.
```bash
SC=applog                                                                     # 판이 바뀐 스키마(검색이면 $S와 ${S}_<원천>…)
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "ALTER SCHEMA $SC RENAME TO ${SC}_rollback_$(date +%m%d)"   # 지우지 않고 비켜 둠
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "CREATE SCHEMA $SC"        # pg_restore -n은 스키마 자체를 만들지 않는다
$DOCKER exec -i "$PG_C" pg_restore -U "$PG_U" -d "$PG_D" -n "$SC" < "$BK/pg.dump"
bash deploy/host/scripts/pipe_exec.sh migrate check --target applog           # 기대: 앞 판 코드로 "판 끝 [...]", 종료 코드 0
```
- 권한(GRANT)은 DB 담당이 원래대로 맞춘다. 비켜 둔 스키마는 확인 뒤 DB 담당이 지운다.
- 그 사이 새 판이 쓴 applog 행·검색 적재는 되살린 스키마에 없다(비켜 둔 스키마에 남음).

**작업 폴더·잠금·진행 기록:** `run_pipeline.py`의 작업 폴더(`ops.run_pipeline.run_pipeline_work_dir`, 비우면 코드 폴더 안 `deploy/host/scripts/test_space/`)에 진행 기록 `batch_progress/progress.log`와 잠금 `batch_progress/run_pipeline.lock`이 있다. 작업 폴더를 비워 두었으면 코드 폴더 안이라 §4-5 명령이 잠시 밖으로 옮겼다 되돌려서 남지만(그대로 지우면 함께 지워짐), 되돌리기(위)는 백업할 때의 것으로 돌아간다 — 바꾸기 전에 `pgrep -af run_pipeline.py`로 도는 실행이 없는지 꼭 본다([§3-6](#3-6-실패한-문서-찾기와-다시-돌리기)).

---

## 5. 릴리스 — 실행 이미지 + 코드 폴더

① PC가 개발 서버용 실행 이미지 2개(코드 없음)를 빌드·시험해 개인 이미지 저장소 `jehunlee302/sbl_images`에 올린다(§5-3) ② 개발 서버(dev)는 그 이미지를 불러오고 코드 수정은 **새 코드를 벌 폴더에 덮어써** 붙인다([§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)) ③ 운영 서버(prd)는 개발 서버에서 시험한 코드를 구운 이미지를 쓴다(§5-4). 의존성이 바뀔 때만 새 실행 이미지 버전을 만든다(§5-2). 단계 표는 [§1-1](#1-1-배포-단계).

### 5-1. 이미지와 코드 폴더

| 이미지 | 역할 | `RAG_MODULE` | 실행 이미지 `IMAGE_TARGET` | 코드가 든 이미지 `IMAGE_TARGET` | 안에 든 것 | 상주 컨테이너(§3-1) |
|---|---|---|---|---|---|---|
| `data-pipeline` | 파싱·게시·구조화·적재 | `pipeline` | `pipeline-runtime` → `data-pipeline-runtime:<판>` | `pipeline` | 의존성 + LibreOffice + `assets/`(OCR 모델) | `data-pipeline-<번호>` · `mcp-data-parsing-0` |
| `mcp-server` | 검색 MCP | `mcp` | `mcp-runtime` → `mcp-server-runtime:<판>` | `mcp` | 의존성 | `mcp-server-0` |

- 이미지 시작 스크립트(`entrypoint.sh`)는 다른 이미지의 명령을 종료 64로 거부한다(맞는 이미지를 알려 줌). data-pipeline: `parse`·`publish`·`show-stack`·`idle`·`migrate`·`run-mcp-parsing` · mcp-server: `mcp`·`ask`·`show-stack`. 어느 이미지에서나: `help`·`check`·`resources`·`services`·`check-modules`·`tool <이름> [인자]`·`selftest`.
- **코드 폴더** = 코드 zip(또는 코드 묶음)을 푼 폴더(저장소 트리 그대로)를 벌 폴더 이름으로 바꾼 것(예 `/home/sbl/sbl_data_parsing-main-0` — 이름 끝 `-<숫자>`가 벌 번호, §2-1). **루트** = 코드 폴더 자체 — 호스트 스크립트는 자기 자리에서 루트를 구해 `<루트>/settings.yaml`·`<루트>/output/`을 쓴다. 사람·systemd는 코드 폴더에서 `bash deploy/host/scripts/…`를 부른다.
- 개발 서버는 실행 이미지(`*-runtime`)에 벌 폴더를 `/app/deploy`에 붙인다(`compose-dev.yml` — 쓰기 가능, `settings.yaml`만 읽기 전용). 코드 없이·의존성 지문이 다른 코드로 띄우면 시작 거부(종료 2) — 실행 이미지 판은 `BUILD.txt`의 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판을 쓴다. 운영 서버는 개발 서버에서 구운 코드가 든 이미지(§5-4)를 마운트 없이 쓴다.
- **코드 폴더만으로 못 바꾸는 것**(바꾸면 새 실행 이미지 버전): `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일. 시작할 때 코드의 `deploy/docker/DEPS_HASH`(requirements 두 파일의 지문)가 이미지 지문과 다르면 컨테이너가 멈춘다. 휠·Dockerfile·assets만 바뀐 경우는 자동으로 막지 않으니 사람이 판을 올려 새로 빌드한다.

### 5-2. 버전

두 이미지는 같은 버전을 쓴다. 정본은 저장소 루트 `VERSION` 한 줄(SemVer).
- MAJOR = MCP 도구 계약·DB 스키마·핸드오프 형식이 깨질 때(1.0.0 전에는 MINOR로 올림) · MINOR = 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 · PATCH = 코드 폴더만 바꿈.
- PATCH인지 MINOR인지 가르기: `git diff v<앞 판>..HEAD -- deploy/docker/`를 본다. `requirements*.txt`가 그대로라 `DEPS_HASH`가 같고, 실행 이미지에 구워지는 파일(`Dockerfile`·`runtime_entry.sh`·`wheels/`)의 동작이 그대로면 PATCH — 서버의 실행 이미지를 그대로 쓰고 코드 폴더만 바꾼다. `entrypoint.sh`·`Dockerfile.bake`는 코드 폴더에서 읽히므로 바뀌어도 PATCH다. `DEPS_HASH`가 다르거나 실행 이미지에 구워지는 파일의 동작이 바뀌면 MINOR(새 실행 이미지 — §5-3).
- `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 annotated 태그 `v<버전>`을 붙인다. 이미지 태그는 `v` 없이(`data-pipeline:0.2.0`).
- `build_ship.sh`·`stage_images.sh`는 태그를 안 주면 `VERSION`을 쓴다. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`). 빌드 커밋은 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`).
- 검색 DB gold `doc`의 버전 칸(`silver_version`·`gold_version`)은 이미지 안 `/app/deploy/VERSION`(코드 폴더면 그 루트 `VERSION`)을 쓴다.

### 5-3. PC에서 — 실행 이미지 만들기와 이미지 저장소에 올리기

[§1-1](#1-1-배포-단계) ① 단계다. PC가 하는 일은 개발 서버용 실행 이미지 두 개를 빌드·시험하고, 통과하면 개인 이미지 저장소 `jehunlee302/sbl_images`에 조각으로 올리는 것뿐이다. 코드만 바뀐 판(`deploy/docker/DEPS_HASH`가 같음)은 이미지를 다시 만들지 않는다 — 서버에 있는 판 중 `BUILD.txt`의 `DEPS_HASH`가 같은 판을 그대로 쓴다.

```bash
# 폐쇄망 빌드라면 먼저 deploy/docker/wheels/에 휠(linux/amd64, py3.12), assets/rapidocr/에 *.onnx(§5-3-1)
BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh   # 1) 빌드 data-pipeline-runtime:<VERSION> → 2) 이 커밋 코드를 붙여 selftest — [판정] 통과여야 다음으로
BUILD_ONLY=1 IMAGE_TARGET=mcp-runtime      bash deploy/release/build_ship.sh   #    mcp-server-runtime:<VERSION>
bash deploy/release/stage_images.sh pipeline-runtime mcp-runtime                 # 3) output/ship/sbl_images/ — load.sh · <판>/BUILD.txt · <판>/<이미지>/ 45MB 조각 + sha256
```

4) `output/ship/sbl_images/`를 개인 이미지 저장소 `jehunlee302/sbl_images`에 그대로 올린다(push는 사람). 개발 서버는 그 저장소 zip을 받아 `load.sh`로 불러온다([§1-5](#서버-설치-순서) 2). 같은 태그의 이미지가 이미 있으면 `build_ship.sh`가 멈춘다(버전을 올리거나, 꼭 다시 만들 때만 `FORCE_TAG=1`). 운영 서버 이미지는 PC에서 만들지 않는다(개발 서버에서 굽는다 — §5-4).

- `BUILD_ONLY=1 IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`는 코드 폴더 묶음 `output/ship/code-<버전>-<커밋>.tar.gz`(`CODE_OUT=`로 바꿈 — git 추적 파일 + `CODE_COMMIT`)도 만든다. 묶음을 이미지 저장소에 함께 둘 때: `CODE_BUNDLE=output/ship/code-<버전>-<커밋>.tar.gz bash deploy/release/stage_images.sh <판> pipeline-runtime mcp-runtime`. 서버에서 푸는 법은 [§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기).
- 빌드만(selftest 판정·resources·비밀값 흔적 점검까지, 저장 없음): `BUILD_ONLY=1 IMAGE_TARGET=<타깃> bash deploy/release/build_ship.sh` — PC 시험 빌드는 `TAG=data-pipeline:<시험 태그>`.
- 빌드 컨텍스트는 저장소 루트, Dockerfile은 `deploy/docker/Dockerfile`. 루트 `.dockerignore`가 허용 목록이다(`common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`).
- Docker 23 미만은 Dockerfile의 heredoc을 못 읽는다 — `build_ship.sh`가 버전을 보고 `--build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7`을 붙인다(인터넷 필요, `BUILDKIT_SYNTAX=`로 바꿈).
- pipeline 이미지는 `assets/rapidocr/*.onnx`가 있어야 빌드된다(§5-3-1). 없으면 `build_ship.sh`가 멈춘다 — `ALLOW_NO_ASSETS=1`은 PC 확인 빌드만(그 이미지는 첫 실행에 모델을 받으려다 폐쇄망에서 실패). 새 체크아웃·worktree에는 `assets/`가 없으니 메인 체크아웃에서 복사한다.

#### 5-3-1. 반입 자산(`assets/`) 준비 — 이미지 빌드 전

폐쇄망 서버는 첫 실행 때 모델을 받을 수 없으므로 pipeline 이미지를 빌드하기 전에 저장소 루트 `assets/`를 채운다. **이미지가 쓰는 자산은 `assets/rapidocr/*.onnx`(pipeline 이미지 — Dockerfile이 rapidocr 패키지의 `models/`로 복사)와 `assets/opencode/opencode`(네 이미지 — 개발 작업 공간의 opencode, linux-x64-baseline 실행 파일 하나)다.** `assets/`는 git에 넣지 않는다. 둘 중 없는 것이 있으면 `build_ship.sh`가 멈춘다(`ALLOW_NO_ASSETS=1`이면 빼고 빌드).

```bash
python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Rec.lang_type': LangRec.KOREAN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})"
PYTHONPATH=. python deploy/release/assets.py pack      # → assets/ + assets/MANIFEST.json(해시·크기, 90 MB 넘으면 .partNN 조각)
PYTHONPATH=. python deploy/release/assets.py check
ls assets/rapidocr/*.onnx assets/opencode/opencode    # build_ship.sh가 보는 것
```

### 5-4. 개발 → 운영 — 시험한 그대로 굽기

운영 이미지는 PC에서 빌드하지 않는다. 개발 서버에 불러온 **실행 이미지 그 판** 위에 **시험한 코드 폴더**를 COPY만 해서 앱마다 코드가 든 이미지 하나(`data-pipeline:<VERSION>`·`mcp-server:<VERSION>`)를 다시 빌드한다(`deploy/docker/Dockerfile.bake` — 패키지 설치·네트워크 없음). 구운 이미지는 코드 폴더 없이 뜬다. 순서: 개발 서버에서 굽기·판정 → 조각을 운영 서버로 옮김 → 운영 서버에서 불러오기·띄우기.

1. 개발 서버(시험한 코드 폴더에서): `bash deploy/release/bake_prod_image.sh <실행 이미지 판>`(개발 서버가 지금 쓰는 실행 이미지 판 — `docker ps --format '{{.Image}}'`에 보이는 태그, 대상 하나만이면 뒤에 `pipeline` 또는 `mcp`). 코드 폴더는 스크립트가 든 폴더(다른 폴더면 `CODE_DIR=`), 새 태그는 코드 `VERSION`(다른 `TAG=`는 거부), 컨테이너 도구는 docker(`DOCKER=`), 저장 폴더 `/var/tmp/bake`(`OUT=`).
2. 스크립트 순서: ① 코드 `DEPS_HASH` = 실행 이미지 지문인지(다르면 멈춤) ② 빌드 — 라벨 `org.opencontainers.image.revision`(코드 커밋)·`org.opencontainers.image.base.digest`(실행 이미지 ID) ③ `selftest_gate.sh` 판정(`[판정] 통과`가 아니면 멈춤) ④ 저장·45 MB 분할·sha256 → `/var/tmp/bake/sbl_images/`(`load.sh` · `<태그>/BUILD.txt` · `<태그>/<이미지>/` + 같은 태그 폴더에 코드 묶음 `code-<태그>-<커밋>.tar.gz`·sha256). 코드 묶음에는 `.git`·`deploy/host/scripts/test_space/`·`valid_env/`·`validation/`·`settings*.yaml`(sample 빼고)·`output/`이 들어가지 않는다(코드 폴더가 git clone이면 `git archive`로 추적 파일만).
3. 옮기기: `/var/tmp/bake/sbl_images/`를 운영 서버로 옮긴다.
4. 운영 서버: `DOCKER=docker bash sbl_images/load.sh <태그>` → 코드 묶음을 벌 폴더(`/home/sbl/sbl_data_parsing-main` — 운영은 한 벌이라 번호 없이)에 풀고(호스트 스크립트·compose 파일만 씀) `compose-prd.yml`의 `IMAGE_TAG`가 `<VERSION>`인지 본다(다르면 `deploy/host/compose/.env`에 `IMAGE_TAG=<VERSION>`) → [§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)·§4-10으로 띄우고 `host_ctl.sh check`.
5. 어느 판인지: `docker image inspect <태그> --format '{{json .Config.Labels}}'`.

### 5-5. 배포 판정 — selftest

```bash
bash deploy/release/selftest_gate.sh $DOCKER run --rm --network host -v "$SETTINGS_FILE:/etc/rag/settings.yaml:ro,z" -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=<local|dev|prd> <코드 폴더 옵션> <태그> selftest
```
- **판정 시험의 DB 사례는 그 서버의 PG에 붙는다**(sqlite 대역 없음 — [e2-22](../prd/test.md#e2-22)). 그래서 판정 명령에 상주 컨테이너와 같은 설정 파일(읽기 전용)·host 네트워크·`RUN_ENV`를 준다. `host_ctl.sh`(서버)와 `build_ship.sh`(빌드·원격 판정)가 이 옵션을 넣는다 — `build_ship.sh`의 원격 판정은 `REMOTE_SETTINGS_FILE`(수집 서버의 settings.yaml 절대 경로)·`REMOTE_RUN_ENV`(`dev`·`prd`)가 있어야 한다. PG에 못 붙으면 DB 사례가 FAIL(이유를 적음)이라 판정도 실패한다.
- PC 시험 빌드(`BUILD_ONLY=1`)는 루트 `settings.yaml`(또는 `SETTINGS_FILE`)을 붙이고 끝에 `--set PG_HOST=host.docker.internal`을 더한다(Docker Desktop 컨테이너의 `127.0.0.1`은 PC가 아님).
- local·dev: DB에 쓰는 사례는 임시 스키마 `test_<임의 8자>`를 만들어 쓰고 지운다(이름이 `test_`로 시작하는지 확인한 뒤 DROP). prd: 쓰는 사례는 SKIP(FAIL로 세지 않음 — 요약 줄 `시험 함수 SKIP N`), 읽기 시험 `test_pg_read`(접속·vector 확장·판 번호 끝·원천 스키마 표·색인·검색 질의 1회 — 세션을 읽기 전용으로)만 운영 DB를 읽는다.
- **selftest는 종료 코드로 판정하지 않는다**(FAIL이 하나라도 있으면 1). `selftest_gate.sh`가 FAIL 줄을 알려진 목록 `deploy/release/known_fail.txt`(이미지 안 `/app/docker/known_fail.txt`)와 대조해 마지막 `[판정]` 줄과 종료 코드를 낸다 — 목록 밖 FAIL 0이면 통과(0), 아니면 실패(1).
- 지금 기대값: 두 이미지 모두 `[판정] 통과 — FAIL 0`(알려진 FAIL 목록은 비어 있음).
- 실행 이미지(`*-runtime`)는 `-v "$PWD:/app/deploy:ro,z"`로 코드 폴더를 붙인다. 구운 이미지는 붙이지 않는다.
- 사례 하나만: `… selftest --only <이름 조각>`(사례 이름 = `tests/server/<common|pipeline|mcp>/test_*.py` 모듈 이름).
- 이미지 안 목록으로 판정: `$DOCKER run --rm --entrypoint bash <태그> /app/docker/selftest_gate.sh /app/docker/entrypoint.sh selftest`.

통과하면 운영 기록 `versions.md`에 한 줄([§3-11-1](#3-11-1-서버-버전-기록)).

### 5-6. 서버에서 직접 고친 코드

서버에서는 되도록 코드를 고치지 않는다(설정이나 [이슈](#3-11-3-이슈-기록)로). 고쳤다면 그때마다 `server-changes.md`에 적는다(형식 [§3-11-2](#3-11-2-서버-자체-개발-기록)).
- 새 판을 덮어쓰면 서버에서 고친 파일은 새 판 내용으로 바뀐다(옛 내용은 백업·gitea에만 남음). 덮어쓰기 전에 `server-changes.md`의 `서버에만`·`PC 보냄` 행을 읽고, 새 코드에 이미 들어 있으면 `PC 반영됨 <커밋>`, 없으면 덮어쓴 뒤 다시 얹고 `다시 얹음 <커밋>`으로 바꾼다.
- 서버에서 바꾼 옵션 값은 코드가 아니라 `settings.yaml`에 둔다 — 새 판이 기본값을 바꿔도 settings.yaml 값이 이긴다.
- 서버 수정은 PC(main)로 보내 받아들이는 것이 기본이다(`서버에만` 행 + `<ID>.diff` — 코드·숫자·오류만, 문서 본문·고객명·키 값 없음).

### 5-7. 보관 기준 — 디스크

| 대상 | 남길 것 | 명령 |
|---|---|---|
| 이미지(`data-pipeline`·`mcp-server`, 실행 이미지 포함) | 지금 버전 + 직전 버전(컨테이너가 쓰는 태그는 늘 남김) | `bash deploy/host/scripts/prune_images.sh --apply`(기본 dry-run, `--keep N`) — `docker system prune`은 쓰지 않음(남의 이미지 보호) |
| 벌 폴더 백업(덮어쓰기 전에 사람이 만든 것) | 지금 판 + 바로 앞 판 | 새 판 확인 뒤 오래된 백업을 손으로 지움(`settings.yaml`·`pg_dump`에 비밀값·DB 내용 — 지우기 전에 확인) |

### 5-8. 릴리스 체크리스트

1. 서버에서 온 `server-changes.md`의 `PC 보냄` 행을 먼저 검토·병합(§5-6).
2. 테스트 통과(CLAUDE.md §5-2·§5-6) → `release/<버전>` → main 병합·태그(§5-2).
3. 코드만 바뀜 → 개발 서버에 덮어쓰기([§4-5](#4-5-벌-폴더에-새-코드-덮어쓰기)) → 운영 굽기(§5-4). 의존성이 바뀜 → 새 실행 이미지(§5-3).
4. 서버: [§4](#4-운영-중인-서버를-새-판으로-올리기) 순서 — 백업 → `server-changes.md` 대조(§5-6) → 새 이미지·새 코드 덮어쓰기 → DB 판(§4-7 — 적재·selftest 앞에) → `host_ctl.sh check` → `versions.md`에 한 줄(§3-11-1).
5. 문제는 [§3-11](#3-11-개발자에게-보고하는-법) 형식으로 이슈 → PC가 고침 → 다음 판.

---

## 6. 내부망 코드 관리 — gitea

내부망 코드는 내부망 gitea의 **비공개 저장소** 하나로 관리한다. 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`). 저장소 주소·계정은 이 문서에 쓰지 않는다 — 아래 예(`gitea.example.local:3000`·조직 `sbl`·저장소 `sbl_data_parsing`·아이디 `jehun`)를 자기 값으로 바꿔 읽는다([예 값 사전](#바꿔-넣을-자리--예-값-사전)).

- **git은 컨테이너 안에서만 쓴다.** 서버에는 git이 없어도 된다 — 실행 이미지에 git·vim·opencode가 들어 있다. 코드 폴더(`$B`)를 컨테이너에 쓰기 가능으로 붙여, 컨테이너 안에서 고치고(opencode 포함) commit·push·pull한다. 그래서 코드 폴더 주인을 컨테이너 사용자 UID 10001로 맞춘다(아래 [git 셸](#git-셸--들어가는-두-길)).
- **저장소 주소는 settings.yaml에 적지 않는다.** 앱은 저장소를 읽지 않고, 주소는 clone할 때 git이 그 코드 폴더의 `.git/config`에 기억한다(`git remote -v`). settings.yaml에 적는 것은 작업 공간의 git 로그인 정보뿐이다(`option.devbox.gitea_url`·`gitea_user`·`gitea_token` — 주소·포트까지, 저장소 경로 없이 — [§6-3](#6-3-개발자-한-벌-만들기)).
- gitea 화면 이름은 판·언어 설정에 따라 조금 다르다(괄호 안 영어 이름).

#### git 셸 — 들어가는 두 길

| 길 | 언제 | 명령(예: 벌 1) |
|---|---|---|
| **(가) 떠 있는 벌 컨테이너에 들어가기** | 평소(코드 고치기·commit·push·pull) — 벌 폴더가 `/app/deploy`에 쓰기 가능으로 붙어 있음([§2-13](#2-13-개발-작업-공간--sshopencode선택)) | `ssh -p 8021 root@10.0.0.12` → `cd /app/deploy` · 서버 셸에서는 `docker exec -it data-pipeline-1 bash` → `cd /app/deploy` |
| **(나) git 전용 컨테이너를 잠깐 띄우기** | 처음(첫 반입·clone) — 벌 컨테이너가 아직 없을 때 | `docker run --rm -it --user 0 --network host --entrypoint bash -v $B:/work:z -w /work data-pipeline-runtime:0.3.0` → (이미 `/work`) |

- (가)의 홈은 `/root` = `$B/home`이라 git 로그인 정보·`git config --global`이 남는다(작업 공간이 만든 gitea 로그인 정보도 여기).
- (나)의 `--entrypoint bash`는 시작 점검을 건너뛰고 셸로 들어간다. `--rm`이라 나가면 컨테이너는 사라지고 `$B`의 파일·`.git`은 남는다. 홈이 이미지 안이라 로그인 정보는 남지 않는다(push·pull마다 아이디·토큰을 물음 — 한 번 쓰는 일에만 쓴다).
- 둘 다 root로 돈다 — 안에서 만든 파일은 서버에서도 root 소유다(서버 계정으로 고칠 때 `sudo`).

### 6-1. 저장소 처음 만들기 — 관리자가 한 번

**① 계정** — 사람마다 하나. 브라우저로 `http://gitea.example.local:3000` → 오른쪽 위 **가입**(Register): 사용자 이름(예 `jehun` — 로그인 아이디 = `gitea_user`)·메일(예 `jehun@sbl.local`)·비밀번호. 가입 버튼이 없으면 gitea 관리자가 사이트 관리(Site Administration) > 사용자 계정 > 새 계정으로 만든다. 메일은 실제 주소가 아니어도 된다 — 사람마다 다르게, 커밋 메일(`git_user_email`)과 같게.

**② 조직과 저장소**
1. 오른쪽 위 **+** → **새 조직**(New Organization) — 이름 `sbl`, 공개 범위 **비공개**(Private). 저장소를 개인 계정이 아니라 조직 아래에 두면 사람이 바뀌어도 주소가 그대로다.
2. **+** → **새 저장소**(New Repository) — 소유자 `sbl`, 이름 `sbl_data_parsing`, **비공개로 만들기**(Make Repository Private) 켬, 기본 브랜치 `main`. **저장소 초기화(README·.gitignore·라이선스)는 모두 비운다** — 이미 있는 코드를 올리므로, 여기서 파일을 만들면 첫 push가 충돌한다.
3. 만든 뒤 화면의 **HTTP 복제 주소**가 저장소 주소다 — 예 `http://gitea.example.local:3000/sbl/sbl_data_parsing.git`.

**③ 권한** — 비공개 저장소는 권한을 받은 사람만 보인다.
- 조직 `sbl` → **팀**(Teams) → **새 팀**: 이름 `developers`, 권한 **쓰기**(Write), 저장소 `sbl_data_parsing` → **팀원 추가**에 gitea 아이디(예 `jehun`). 관리자는 처음부터 있는 `Owners` 팀.
- 읽기만 줄 사람은 권한 **읽기**(Read)인 팀(예 `readers`)을 하나 더 만든다.
- 조직 없이 개인 저장소면: 저장소 → **설정**(Settings) → **협업자**(Collaborators) → 아이디 추가 → **쓰기**.

**④ 브랜치 보호** — 첫 push(⑤) **뒤에** 건다(먼저 걸면 첫 push가 막힌다). 저장소 → **설정** → **브랜치**(Branches) → **브랜치 보호 규칙 추가**:
- 브랜치 이름 `main`: **푸시 비활성화**(Disable Push — 직접 push 금지, PR로만), **병합 허용 목록**(Merge whitelist)에 판을 내는 사람(예 `jehun`), 필요하면 **필요한 승인 수**(Required approvals) `1`.
- `develop`에도 같은 규칙(병합 허용 목록은 팀 `developers`).

**⑤ 첫 반입** — 코드 zip을 푼 공용 main 벌 폴더(git 기록 없음)를 저장소의 첫 커밋으로 올린다.
서버 셸(root):
```bash
B=/home/sbl/sbl_data_parsing-main-0
docker run --rm -it --user 0 --network host --entrypoint bash -v $B:/work:z -w /work data-pipeline-runtime:0.3.0   # git 셸 (나)
```
git 셸 안(`/work`):
```bash
id -u                                                 # 기대: 0
echo '$Format:%H %h$' > CODE_COMMIT                    # zip이 채운 커밋 표시를 틀로 되돌림(gitea가 zip을 만들 때 다시 채움)
git init -b main
git config --global user.name jehun && git config --global user.email jehun@sbl.local   # 커밋·태그에 남길 이름·메일 — 이 셸에서만(git 셸 (나)는 나가면 사라짐)
git add .                                             # settings.yaml·output/·home/은 .gitignore에 있어 빠짐
git status --short | grep -E '^.. "?(settings[^/]*\.yaml|output/|home/)' | grep -v 'settings\.sample\.yaml' \
  && echo "멈춤 — 비밀·결과 파일이 들어감" || echo "확인 — 비밀·결과 파일 없음"
git commit -qm "Import 0.3.1 from external main"
git remote add origin http://gitea.example.local:3000/sbl/sbl_data_parsing.git
git push -u origin main                               # Username: jehun · Password: 토큰(또는 비밀번호)
git push origin main:develop                          # develop을 쓰면 — main과 같은 곳에서 시작
git tag -a v0.3.1 -m "0.3.1" && git push origin v0.3.1   # 반입한 판에 태그
exit
```
- "멈춤"이 나오면 커밋하지 않는다 — 그 파일 이름을 `.gitignore`에 넣고 `git rm --cached <파일>`(예 `git rm --cached "settings copy.yaml"`) 뒤 다시.
- 그다음 ④(브랜치 보호)를 건다.

**⑥ 외부망 새 판 들여오기** — 새 판 zip(예 `sbl_data_parsing-0.3.2.zip`)을 서버 `/home/sbl/incoming/`에 놓고, 내 벌(예 `-1`)에서 `release/<버전>` 브랜치로 바꿔 커밋한다. git이 관리하는 파일만 바꾸므로 settings.yaml·edw_chain.yaml·output/·home/은 그대로다.
```bash
B=/home/sbl/sbl_data_parsing-main-1                   # 서버 셸 — git 셸 (나)에 zip 폴더를 읽기 전용으로 더 붙임
docker run --rm -it --user 0 --network host --entrypoint bash -v $B:/work:z -v /home/sbl/incoming:/incoming:ro,z -w /work data-pipeline-runtime:0.3.0
```
git 셸 안:
```bash
git status --short                                    # 기대: 빈 줄(고치던 것이 있으면 먼저 commit)
git config --global user.name jehun && git config --global user.email jehun@sbl.local   # 커밋·태그에 남길 이름·메일 — 이 셸에서만(git 셸 (나)는 나가면 사라짐)
git fetch origin && git switch -c release/0.3.2 origin/main
rm -rf /tmp/new && unzip -q /incoming/sbl_data_parsing-0.3.2.zip -d /tmp/new
git ls-files -z | xargs -0 rm -f                      # git이 관리하는 파일만 지움(지운 파일이 새 판에 없으면 그대로 지워진 것으로 남음)
cp -a /tmp/new/sbl_data_parsing-0.3.2/. .             # 새 판으로 채움
echo '$Format:%H %h$' > CODE_COMMIT
git ls-files --error-unmatch opencode.jsonc >/dev/null 2>&1 && git checkout HEAD -- opencode.jsonc   # 내부망에서 채운 opencode 설정은 내부망 것 그대로(아직 커밋 전이면 새 판의 빈 틀)
git add -A && git status --short | head -30           # 바뀐 파일 확인 — 내부망에서만 고친 파일(예 edw_chain.yaml)이 보이면
#   외부망 판으로 덮인 것: 내부망 것을 살리려면 git checkout HEAD -- <파일> → 외부망에도 같은 고침을 넣어 다음 판부터 맞춘다
git commit -qm "Import 0.3.2 from external main" && git push -u origin release/0.3.2   # 그다음 §6-5 ④부터(PR → 병합 → 태그)
exit
```

### 6-2. 개발자마다 한 벌 + 공용 main 한 벌

개발 서버 한 대에 여러 벌을 띄운다. 벌 폴더(코드 폴더 = gitea clone) 하나가 한 벌이고, `compose-dev.yml`의 칸 `data-pipeline-<번호>`가 그 폴더를 붙인다([§2-1](#2-1-폴더와-벌)).

| 벌 | 벌 폴더(예) | 코드 | 컨테이너 |
|---|---|---|---|
| 공용 main(벌 0) | `/home/sbl/sbl_data_parsing-main-0` | gitea `main`의 태그 판(예 `v0.3.1`) | `data-pipeline-0` + `mcp-server-0` · `mcp-data-parsing-0` |
| 개발자마다 하나 | `/home/sbl/sbl_data_parsing-main-1` | 그 개발자의 `feature/*` 브랜치 | `data-pipeline-1` |

- **검색 DB는 서버마다 하나다**(`compose-pgvector.yml` 또는 DB 담당의 PG). 모든 벌이 같은 기준 스키마를 함께 쓴다 — 모든 벌을 같은 코드 판으로 둔다.
- **벌마다 다른 값**: 원천 `DEV-<숫자>`(예 `DEV-2`)·gitea 계정은 그 벌의 settings.yaml, 컨테이너 이름·SSH 포트·폴더는 `compose-dev.yml`의 칸(§2-15). 다른 사람의 포트·벌 번호를 쓰지 않는다.
- `settings.yaml`(사본 `settings copy.yaml` 등 포함)·`output/`·`home/`·`.worktrees/`는 clone 안에 있지만 git 제외 목록(`.gitignore`)에 있어 커밋되지 않는다. `edw_chain.yaml`·compose 파일·저장소 루트 `opencode.jsonc`(opencode 설정 — 키 없이)는 커밋한다.
- 이미지는 공용 폴더에 한 번 불러 두면 모든 벌이 같이 쓴다.
- gitea 전용 코드는 두지 않는다 — git 명령과 브랜치 규칙만 쓴다.

### 6-3. 개발자 한 벌 만들기

예: 벌 번호 `1`, 벌 폴더 `/home/sbl/sbl_data_parsing-main-1`, 원천 `DEV-2`, SSH 포트 `8021`(`compose-dev.yml`의 `data-pipeline-1` 칸 — 새 번호면 §2-15처럼 칸을 더한다).

**① 토큰**(선택 — 비밀번호로도 된다): gitea 웹 → 프로필 사진 → **설정**(Settings) → **응용**(Applications) → **새 토큰 만들기**(Generate New Token) — 이름 `devserver-main-1`, 권한 `repository` **읽기 및 쓰기**(Read and Write, 옛 판은 `repo` 체크) → 만들기. 토큰은 만들 때 한 번만 보이므로 바로 ⑤에서 쓴다. 잃어버리면 그 토큰을 지우고 새로 만든다. 토큰을 권하는 까닭: 컨테이너 홈의 `~/.git-credentials`에 글자 그대로 저장되는데, 토큰은 저장소 권한뿐이고 따로 지울 수 있다. 관리자가 비밀번호 로그인을 막았거나 2단계 인증을 켰으면 토큰만 된다.

**② clone** — 빈 벌 폴더를 만들어 git 셸 (나)에서 받는다.
서버 셸(root):
```bash
B=/home/sbl/sbl_data_parsing-main-1
mkdir -p $B
docker run --rm -it --user 0 --network host --entrypoint bash -v $B:/work:z -w /work data-pipeline-runtime:0.3.0
```
git 셸 안:
```bash
git clone -b develop http://gitea.example.local:3000/sbl/sbl_data_parsing.git .   # 끝의 . = 이 폴더에 · develop을 안 쓰면 -b main · Username: jehun · Password: 토큰
git rev-parse --short HEAD > CODE_COMMIT && git update-index --skip-worktree CODE_COMMIT   # 시작 로그의 커밋 표시용 — 바꾼 것을 git이 무시
exit
```
**③ 설정·폴더** — 서버 셸(root):
```bash
cd $B && bash deploy/host/scripts/host_ctl.sh init --group sbl   # settings.yaml·output/ 만듦(없을 때만)
```
공용 벌 settings.yaml을 틀로 벌마다 다른 칸을 고친다([§2-15](#2-15-두-번째-벌-만들기) 표 — 예 `required.source.source_systems: DEV-2`). 맨 아래에 git 이름·메일:
```yaml
option:
  devbox:
    git_user_name: jehun                      # 커밋에 남길 이름
    git_user_email: jehun@sbl.local           # gitea 계정 메일과 같게
```
```bash
chmod 640 $B/settings.yaml
mkdir -p $B/home/.ssh && cp /home/sbl/jehun_id_ed25519.pub $B/home/.ssh/authorized_keys   # 열쇠로 들어갈 때만 — 내 PC 공개 열쇠(~/.ssh/id_ed25519.pub)를 서버로 옮겨 둔 자리
chmod 700 $B/home/.ssh && chmod 600 $B/home/.ssh/authorized_keys
```
**④ 띄우기** — SSH 작업 공간(코드 쓰기 가능)으로:
```bash
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline-1   # compose-dev.yml의 칸 — 벌 폴더를 /app/deploy에 쓰기 가능으로(settings.yaml만 읽기 전용)
```

**⑤ 첫 확인** — git 셸 (가):
```bash
ssh -p 8021 root@<서버>                               # 또는 서버 셸에서 docker exec -it data-pipeline-1 bash
cd /app/deploy && git config --global credential.helper store   # 로그인 정보를 홈에 기억(한 번만)
git ls-remote origin | head -2                        # Username: jehun · Password: ①의 토큰 → 기대: 커밋 번호 줄(다음부터는 묻지 않음)
```
그다음은 [§2-15](#2-15-두-번째-벌-만들기)와 같다 — (새 `DEV-<숫자>`면) 컨테이너 안에서 `bash /app/docker/runtime_entry.sh migrate up --target search` → 벌 0 폴더에서 `host_ctl.sh check`(기대 마지막 줄 `[host_ctl check] 통과 — 7개`). DB 표가 아직 없는 서버의 첫 벌이면 [§2-6](#2-6-db-판--검토용-sql-뽑기--migrate-up) (가).

- `cat ~/.git-credentials`는 하지 않는다(토큰이 찍힘).
- 비밀번호·토큰을 바꿨으면 git 셸 (가)에서 `printf 'protocol=http\nhost=gitea.example.local:3000\n' | git credential reject` 뒤 `git pull`에서 새 값을 넣는다.
- `https`인데 `SSL certificate problem`이면 서버 관리자에게 사내 인증서를 받아 등록한다(검사 끄기 `sslVerify=false`는 쓰지 않는다).

### 6-4. 매일 쓰는 법 — 브랜치 따기·push·PR

모두 git 셸 (가)에서(`docker exec -it -e HOME=/home/rag data-pipeline-2 bash` → `cd /app/deploy`):
```bash
git fetch origin
git switch -c feature/pdf-table origin/develop        # ① 브랜치 따기 — 기능 하나에 하나(develop을 안 쓰면 origin/main)
opencode                                              #    고치기(opencode·vim) → 시험: python -m pipeline.cli selftest --only <이름 일부>(예 --only test_publish)
git status --short                                    # ② 바뀐 파일 확인 — settings.yaml·output/이 없어야 함
git add pipeline/load/publish.py && git commit -m "Retry publish on timeout"   # 바꾼 파일만
git push -u origin feature/pdf-table                  # ③ 올리기(처음엔 -u, 다음부터 git push)
```
④ **PR** — gitea 웹: 저장소 → **풀 리퀘스트**(Pull Requests) → **새 풀 리퀘스트** → 병합 대상 `develop` ← `feature/pdf-table` → 제목·내용(무엇을 왜, 서버 영향 '코드 폴더만 교체' 또는 '새 이미지 버전 필요') → 만들기. 다른 사람이 **파일 변경**(Files Changed) 탭에서 보고 **검토**(Review) → 승인.
⑤ **병합** — 승인 뒤 PR 화면 아래 **병합**(Merge) 버튼(병합 허용 목록에 있는 사람). 병합 뒤 "브랜치 삭제"를 누르면 gitea의 그 `feature/*`가 지워진다(`release/*`·`main`·`develop`은 지우지 않는다).
```bash
git switch develop && git pull                        # ⑥ 병합된 develop 받기
git branch -d feature/pdf-table                       #    다 쓴 브랜치 정리
git fetch --prune                                     #    gitea에서 지운 브랜치 표시 정리
```
- PR 하나는 기능 하나. 다른 사람 PR과 같은 파일을 고쳐 충돌하면 내 브랜치에서 `git pull origin develop` → 충돌 파일을 고쳐 커밋 → `git push`.
- 동시에 여러 기능을 고치려면 `git worktree add .worktrees/ocr-fix -b feature/ocr-fix origin/develop`(git 셸 (가)에서만 — worktree는 `/app/deploy` 절대 경로를 기억해 (나)의 `/work`에서는 깨진다 · 코드 폴더 안이라 컨테이너에서 보임 · `.gitignore`에 있음). 그 폴더 코드로는 시험 명령만 돈다(`cd .worktrees/ocr-fix && PYTHONPATH=$PWD python -m pipeline.cli selftest --only test_publish`) — 파이프라인 전체는 늘 `/app/deploy` 코드로 돈다.
- 고친 코드는 `data-pipeline-<번호>` 컨테이너 안에서 **다음 명령부터** 쓰인다. 같은 벌의 MCP 컨테이너는 다시 띄워야 반영된다(`host_ctl.sh up -d --force-recreate mcp-data-parsing-0 mcp-server-0`). 의존성 지문(`deploy/docker/DEPS_HASH`)이 바뀐 커밋은 새 실행 이미지가 필요하다([§4-4](#4-4-새-실행-이미지-불러오기--의존성-지문-확인)).
- 공용 main 벌은 gitea `main`에 붙인 태그 판(`v<버전>`, 예 `v0.3.2`)만 받는다([§6-5](#6-5-판-내기--release-브랜치와-태그)). 판을 바꿀 때는 [§4](#4-운영-중인-서버를-새-판으로-올리기) 순서(백업 → DB 판 → 점검) — 벌이 같은 DB를 쓰므로 모든 벌을 같은 판으로.
- **`server-changes.md`·`issues.md`·`versions.md`** — [§3-11](#3-11-개발자에게-보고하는-법) 형식.
- 외부망 `main`과 내부망 gitea를 오가는 때(판마다·정기)와 개발자별 벌 목록을 둘 곳은 [refactor.md](../refactoring/refactor.md)의 열린 항목에서 정한다.

### 6-5. 판 내기 — release 브랜치와 태그

외부망 새 판을 들여오는 경우는 [§6-1](#6-1-저장소-처음-만들기--관리자가-한-번) ⑥으로 `release/<버전>`을 만든 뒤 ④부터. 판 번호 규칙은 [§5-2](#5-2-버전)(코드 폴더만 바뀌면 PATCH `0.3.1 → 0.3.2`, 새 실행 이미지면 MINOR `0.3.x → 0.4.0`). 브랜치는 외부망과 같다 — `feature/<기능명>` → PR → `develop` → `release/<버전>` → PR → `main` → 태그 `v<버전>`. `develop`을 쓰지 않으면 아래 `origin/develop`을 `origin/main`으로 읽는다. 아래 예는 `0.3.1 → 0.3.2`, 모두 git 셸 (가)(`docker exec -it -e HOME=/home/rag data-pipeline-2 bash` → `cd /app/deploy`).

```bash
git fetch origin
git switch -c release/0.3.2 origin/develop            # ① release 브랜치 — 합칠 기능이 다 들어간 develop에서
cat VERSION                                           #    기대: 0.3.1
echo 0.3.2 > VERSION                                  # ② 판 올리기(이 브랜치에서만 — feature에서는 안 고침)
git commit -am "Release 0.3.2: VERSION 0.3.1 -> 0.3.2"
git push -u origin release/0.3.2                      # ③ 올리기 — 이 브랜치로 벌을 띄워 시험(§0)하고, 고칠 것은 이 브랜치에 커밋
```
④ gitea 웹: 저장소 → **풀 리퀘스트** → **새 풀 리퀘스트** → 병합 대상 `main` ← `release/0.3.2` → 만들기 → 검토 뒤 **병합**.
```bash
git switch main && git pull                           # ⑤ 병합된 main 받기
git log -1 --oneline                                  #    기대: 병합 커밋(release/0.3.2)
git tag -a v0.3.2 -m "0.3.2"                          # ⑥ 태그 — 병합 커밋에, annotated(-a), 이름은 v + VERSION
git push origin v0.3.2                                #    태그는 따로 올려야 gitea에 보인다
git tag -l 'v*'                                       #    기대: … v0.3.1 v0.3.2
```
⑦ (`develop`을 쓰면) release에서 고친 것을 `develop`에도 — gitea 웹에서 PR `develop` ← `main` → 병합.
- gitea 웹 **릴리스**(저장소 → 태그 → `v0.3.2` → 새 릴리스)에 바뀐 것을 적어 두면 판마다 기록이 남는다(선택).
- 공용 main 벌을 이 판으로 올릴 때는 [§4](#4-운영-중인-서버를-새-판으로-올리기) 순서 — 코드 받기는 공용 벌의 git 셸에서(공용 벌 컨테이너는 코드를 읽기 전용으로 붙이므로 (나) — `B=/home/sbl/sbl_data_parsing-main-1`) `git fetch origin --tags && git switch --detach v0.3.2 && git rev-parse --short HEAD > CODE_COMMIT && git update-index --skip-worktree CODE_COMMIT`(판에 고정 — 다음 판도 태그로 옮긴다).
- 태그는 한 번 올리면 옮기지 않는다. 잘못 붙였으면 다음 판 번호로 새로 낸다(남이 이미 받았을 수 있다).
- `release/*` 브랜치는 병합 뒤에도 지우지 않는다(그 판을 고칠 때 다시 씀).

### 6-6. 서버 묶음 — compose 파일과 root SSH

서버의 컨테이너는 compose 파일 다섯으로 띄운다(`deploy/host/compose/` — 이름·이미지·포트·CPU·메모리·볼륨이 파일에 직접 적혀 있음).

| 파일 | 묶음 이름 | 컨테이너 | 띄우는 법 | 재시작 정책 |
|---|---|---|---|---|
| `compose-dev.yml` | `sbl-devset` | `data-pipeline-0`·`data-pipeline-1` · `mcp-server-0` · `mcp-data-parsing-0` — 실행 이미지 `*-runtime` + 벌 폴더 | `host_ctl.sh up -d`(run_env `dev`) | `unless-stopped` |
| `compose-prd.yml` | `sbl-prd` | `data-pipeline-0` · `mcp-server-0` · `mcp-data-parsing-0` — 구운 이미지(코드 안) | `host_ctl.sh up -d`(run_env `prd`) | `always` |
| `compose-local.yml` | `sbl-local` | PC 시험 — 0번 한 벌 셋(SSH 없음 — `data-pipeline-0`은 `idle`) | `host_ctl.sh up -d`(run_env `local`) | 없음 |
| `compose-pgvector.yml` | `sbl-pgvector` | `pgvector`(검색 DB — 서버 5433) | `docker compose -f deploy/host/compose/compose-pgvector.yml up -d` — 한 번 | `always` |
| `compose-redis.yml` | `sbl-redis` | `redis`(작업 큐 — 서버 8010) | `docker compose -f deploy/host/compose/compose-redis.yml up -d` — 한 번 | `always` |

| 컨테이너 | 서버 포트 → 컨테이너 포트 | 개발 CPU · 메모리(파일에 적힌 값) |
|---|---|---|
| `data-pipeline-0` | 8020 → 22(SSH) | 4 · 12g(스왑 4g 더 — `memswap_limit` 16g) |
| `data-pipeline-1` | 8021 → 22(SSH) | 2 · 8g |
| `mcp-server-0` | 8050 → 22(SSH) · 8051(HTTP — 안팎 같음) | 3 · 12g |
| `mcp-data-parsing-0` | — | 4 · 12g(`cpu_shares` 4096) |
| `pgvector` | 5433 → 5432 | 4 · 12g |
| `redis` | 8010 → 6379 | 1 · 2g |

- 앱 컨테이너는 모두 root로 뜬다. SSH 컨테이너(`data-pipeline-*`·`mcp-server-0`)는 root 비밀번호 SSH를 연다 — 비밀번호는 **이미지에 넣은 값**이다(이미지 빌드 때 BuildKit 비밀 `BUILD_ARGS="--secret id=root_pw,src=<git 밖 파일>"` — 첫 줄 · 저장소·`docker history`에 남지 않음 · 바꾸려면 `--no-cache`로 다시 빌드). 벌 settings.yaml `required.env.run_env`가 `dev`·`prd`가 아니면 SSH 컨테이너가 시작을 거부한다.
- 포트는 서버의 모든 주소(`0.0.0.0`)에 열린다. 컨테이너는 docker 자체 네트워크(bridge)에 있어 컨테이너 안 `127.0.0.1`은 컨테이너 자신이다 — 서버에 있는 PG(5433)·Redis(8010)·모델은 `host.docker.internal`로 적는다(settings.yaml `required.pg.pg_host` · `common.connections.redis.redis_host` 기본값). 서버 바깥(DB 도구 등)에서는 `<서버 IP>:5433`.
- 검색 MCP: 벌 0(운영은 그 한 벌) settings.yaml `search.server` — `mcp_bind_host: auto` · `mcp_port: 8051` · `required.tokens.mcp_token`(루프백이 아니라 필수) · `mcp_allowed_hosts: <서버 IP>:8051`(예 `10.10.1.20:8051`). 서버의 `mcp_keepalive.sh`는 `http://127.0.0.1:8051/health`를 본다.
- CPU·메모리·포트를 바꾸려면 그 파일의 컨테이너 칸을 고친다([§2-14](#2-14-컨테이너-이름볼륨-바꾸기)). 모든 컨테이너의 `cpus` 합 ≤ 서버 CPU 수([§1-10](#1-10-자원)).

**① 준비(서버, 한 번)**
```bash
cd /home/sbl/sbl_data_parsing-main-0                         # 운영은 /home/sbl/sbl_data_parsing-main
#   먼저 settings.yaml에 required.pg.pg_password · common.connections.redis.redis_password를 채운다(설치 순서 4번)
vi .env && chmod 600 .env                                    # 같은 값을 손으로: REDIS_PASSWORD= · PG_USER= · PG_DB= · PG_PASSWORD=($·따옴표·줄바꿈 없이)
sudo mkdir -p /data/pg/pipeline /data/redis                   # 데이터 폴더 — PG는 비어 있으면 처음 시작 때 DB를 만든다(이 때만 .env 계정을 씀)
docker compose --env-file .env -f deploy/host/compose/compose-pgvector.yml up -d
docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d
docker ps --filter name=^redis$ --format '{{.Status}}'      # 기대: Up … (healthy)
```
- `.env`는 벌 0 코드 폴더(운영은 그 한 벌) 맨 위 하나다 — git 제외(`.gitignore`)라 새 판을 덮어써도 남는다. 값이 비어 있으면 compose가 `.env에 … 필요`로 멈춘다. 비밀번호는 Redis는 명령 인자, PG는 환경 변수로 넘어가 `docker inspect`에 보인다(서버 root·docker 권한자만).
- 비밀번호를 바꾸면 `.env`·settings.yaml을 같이 고치고 Redis를 `up -d --force-recreate`(두 앱 컨테이너도 `host_ctl.sh restart mcp-server-0 mcp-data-parsing-0`). PG는 이미 만든 DB에 `.env` 값을 다시 쓰지 않는다 — `psql`의 `\password`로 같게 바꾼다([§1-4](#서버-pg-띄우기)).
- 벌마다 settings.yaml `required.env.run_env`: `dev` · `required.pg`: `pg_host` `host.docker.internal` · `pg_port` `5433` · `pg_database`·`pg_user` = `rag`(compose `PG_DB`·`PG_USER`와 같게) · `pg_password`.

**② 띄우기·확인**
```bash
cd /home/sbl/sbl_data_parsing-main-0
bash deploy/host/scripts/host_ctl.sh up -d                    # 벌 폴더마다 코드·settings.yaml이 있어야 한다(§2-3·§2-4)
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'        # 그대로 입력 — 기대: 앱 넷 + pgvector · redis Up, 0.0.0.0:8020->22/tcp …
docker logs mcp-server-0 | tail -5                            # 기대: Server listening … port 22 + 검색 MCP 시작 줄
curl -s http://127.0.0.1:8051/health                          # 기대: {"ok":true,…}
```
- 컨테이너가 `Restarting (2)`면 `docker logs <이름>`의 `[devbox]` 줄을 본다 — `run_env is …`(벌 settings.yaml `required.env.run_env`를 `dev`로) · `the image has no root password …`(비밀번호를 넣어 이미지를 다시 빌드).

**③ 접속(서버 바깥 PC에서)**
```bash
ssh -p 8020 root@<서버 IP>     # data-pipeline-0 — 비밀번호 = 이미지에 넣은 값 · 예 ssh -p 8020 root@10.10.1.20
ssh -p 8021 root@<서버 IP>     # data-pipeline-1
ssh -p 8050 root@<서버 IP>     # mcp-server-0
curl http://<서버 IP>:8051/health   # 검색 MCP — 기대: 200
psql -h <서버 IP> -p 5433 -U rag -d rag -c 'select 1'   # 검색 DB(psql이 있는 PC에서) — 비밀번호 = settings.yaml required.pg.pg_password
```
- 들어가면 `/app/deploy`(벌 폴더 — 쓰기 가능)에서 고치고 git을 쓴다(§6-4). `sudo`·`su`도 있다.
- root로 쓴 파일은 서버에서도 root 소유다 — 서버 계정으로 고치거나 지울 때는 `sudo`.
- 검색 MCP는 sshd 옆에서 뒤로 돈다 — MCP만 멈춰도 컨테이너는 Up이다. 8051이 응답하지 않으면 MCP 살리기 타이머가 `docker restart mcp-server-0`을 한다(손으로는 `bash deploy/host/scripts/mcp_keepalive.sh`).
- 내리기: `bash deploy/host/scripts/host_ctl.sh down`(벌 폴더·결과는 그대로). PG·Redis는 `docker compose -f deploy/host/compose/compose-<pgvector|redis>.yml down`(데이터 폴더는 그대로).

#### 운영 서버 — compose-prd.yml
`compose-prd.yml`은 0번 `data-pipeline-0`·`mcp-server-0`·`mcp-data-parsing-0`을 띄운다. 포트·비밀 파일·PG·Redis는 개발과 같고, 다른 점은 아래뿐이다.

| | 개발(`compose-dev.yml`) | 운영(`compose-prd.yml`) |
|---|---|---|
| 컨테이너 | `data-pipeline-0`·`-1` · `mcp-server-0` · `mcp-data-parsing-0` | `data-pipeline-0` · `mcp-server-0` · `mcp-data-parsing-0` |
| 이미지 | 실행 이미지 `*-runtime:<판>` + 벌 폴더를 `/app/deploy`에(쓰기 가능) | 구운 이미지 `data-pipeline:<판>`·`mcp-server:<판>`([§0-3](#0-3-prd--운영-서버-코드를-구운-이미지)) — 코드(`edw_chain.yaml` 포함)는 이미지 안(고칠 수 없음) |
| 설정·결과 | 벌 폴더의 `settings.yaml`·`output/`·`home/` | 운영 폴더 `PRD_DIR`(기본 `/home/sbl/sbl_data_parsing-main`)의 `settings.yaml`·`output/`·`home/`(`home/mcp` = mcp-server-0 홈) |
| 재시작 | `unless-stopped`(손으로 멈추면 그대로) | `always`(손으로 멈춘 것도 docker가 다시 켜질 때 띄움) |
| 실행 환경 | `run_env: dev` | `run_env: prd` |

```bash
cd /home/sbl/sbl_data_parsing-main                              # 코드 묶음을 푼 운영 폴더(§0-3 ①)
bash deploy/host/scripts/host_ctl.sh up -d                      # run_env: prd → compose-prd.yml
docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}}' data-pipeline-0 mcp-server-0 mcp-data-parsing-0 pgvector redis   # 그대로 입력 — 기대: 모두 always
```
- 접속은 위 ③과 같다 — `ssh -p 8020 root@<서버 IP>`(data-pipeline-0) · `ssh -p 8050 root@<서버 IP>`(mcp-server-0) · `curl http://<서버 IP>:8051/health` · `psql -h <서버 IP> -p 5433 -U rag -d rag`.
- 구운 이미지의 시작 스크립트(`entrypoint.sh`)를 이 파일이 SSH 컨테이너만 작업 공간(`dev_entry.sh`)으로 바꿔 띄우고, 앱 명령은 `entrypoint.sh`로 넘긴다. 작업 컨테이너는 이미지 시작 스크립트 그대로다. 그래서 굽기 바탕이 sudo·root SSH가 든 실행 이미지여야 한다.

### 6-7. Redis — compose-redis.yml
`deploy/host/compose/compose-redis.yml` 한 파일로 Redis 하나(공식 이미지 `redis:7.4.8-alpine`, 컨테이너 `redis`)를 띄운다. 서버마다 하나이고 개발·운영이 같다. 앱의 기본 주소는 `host.docker.internal:8010`(settings.yaml `common.connections.redis.redis_host`·`redis_port` — 비워 둔다).

| 무엇 | 값 |
|---|---|
| 포트 | 서버 `0.0.0.0:8010` → 컨테이너 6379 |
| 보호 | `protected-mode yes` + `--requirepass`(코드 폴더 맨 위 `.env`의 `REDIS_PASSWORD` = settings.yaml `common.connections.redis.redis_password` — 필수, 기본값 없음) |
| 데이터 | `REDIS_DATA`(기본 `/data/redis`) → `/data`(AOF) |
| 상태 검사 | `redis-cli ping`이 `PONG` 또는 `NOAUTH`(떠 있음 — 비밀번호 없이) |
| 재시작 | `always` · MCP 살리기 타이머가 꺼졌으면 이 파일로 다시 띄움 |

**① 이미지 반입** — 인터넷 PC에서 `docker pull redis:7.4.8-alpine`으로 받은 뒤 `bash deploy/release/stage_images.sh`가 판 폴더에 조각(`redis/`)을 함께 만든다 → 서버에서 `bash sbl_images/load.sh <판>`이 다른 이미지와 함께 불러온다.

**② 준비·띄우기(서버)**
```bash
cd <루트>                                                     # 벌 0 코드 폴더 — .env에 REDIS_PASSWORD(settings.yaml redis_password와 같은 값)
mkdir -p /data/redis
docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d
docker ps --filter name=^redis$ --format '{{.Status}}'      # 기대: Up … (healthy)
```

**③ 확인(서버 바깥 PC에서)**
```bash
redis-cli -h <서버 IP> -p 8010 --askpass ping                  # 기대: PONG(비밀번호를 물으면 settings.yaml의 값)
```
- 비밀번호는 `redis-server` 명령 인자로 넘어가 `docker inspect`(Args)에 보인다 — 서버 root·docker 권한자만 볼 수 있다. 셸 명령·로그에는 적지 않는다.
- 비밀번호를 바꾸면: `.env`·settings.yaml을 같이 고치고 `docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d --force-recreate` → `host_ctl.sh restart mcp-server-0 mcp-data-parsing-0`.
- 키 보기·작업 추적은 [§1-3-1](#1-3-1-parse_document-redis-큐113).
