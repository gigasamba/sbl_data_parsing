# 내부망 코드 관리 — gitea

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · [upgrade-guide.md](upgrade-guide.md)

내부망 코드는 내부망 gitea 저장소로 관리한다. 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`). 저장소 주소·계정은 이 문서에 쓰지 않는다.

## 1. 개발자마다 한 벌 + 공용 main 한 벌

개발 서버 한 대에 여러 벌을 띄운다. 루트 하나가 한 벌이고, 벌 이름(`ops.host.instance_name`) 하나로 컨테이너·PG 스키마·EDW 기록 표가 나뉜다([server-guide §1-3](server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별)).

| 벌 | 루트(예) | 코드 | 벌 이름 |
|---|---|---|---|
| 공용 main | `/home/sbl/dev` | gitea `main` | 비움(컨테이너 `data-pipeline`·`mcp-data-parsing`·`mcp-server`) |
| 개발자마다 하나 | `/home/sbl/dev-hong` | 그 개발자의 gitea 브랜치 | `hong`(컨테이너 끝 `-hong`) |

- **pgvector는 우리 compose에 없다.** PG는 DB 담당이 주는 서버를 쓰고, 벌마다 스키마가 `<pg_schema>_<벌>`로 갈린다.
- **포트·벌 이름은 그 루트의 settings.yaml로만 준다**(코드나 compose에 사람별로 적지 않음). 다른 사람의 포트·이름을 쓰지 않는다.
- 이미지는 공용 폴더에 한 번 불러 두면 모든 벌이 같이 쓴다.
- gitea 전용 코드는 두지 않는다 — git 명령과 브랜치 규칙만 쓴다.

## 2. 개발자 한 벌 만들기

root 셸에서(`<이름>` = 벌 이름 — 영소문자·숫자·`-`):
```bash
export DOCKER=podman
mkdir -p /home/sbl/dev-<이름> && cd /home/sbl/dev-<이름>
git clone -b <내 브랜치> <gitea 저장소 주소> sbl_data_parsing-<이름>          # 루트 아래 코드 폴더 = 내 작업 폴더
cd sbl_data_parsing-<이름> && git rev-parse --short HEAD > CODE_COMMIT       # clone은 CODE_COMMIT을 채우지 않음 — 시작 로그의 커밋 표시용
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>               # <루트>/settings.yaml·edw_chain.yaml·output/·home/
```
그다음 `<루트>/settings.yaml`에 공용 벌의 값(접속·모델·이미지 칸)을 옮기고, 벌마다 다른 세 칸을 적는다:
```yaml
ops:
  host: {instance_name: <이름>}
  services:
    data_parsing: {data_parsing_port: <다른 벌과 겹치지 않는 포트>}   # 기본 8766 그대로면 시작 거부
search:
  server: {mcp_port: <다른 벌과 겹치지 않는 포트>}                    # 기본 8765 그대로면 시작 거부
```
이어서 띄우고 DB 표를 만든다(README [§5-0 "한 서버에 여러 벌"](../../README.md#5-0-배포-단계와-개발-서버-설치)과 같다):
```bash
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline                     # → data-pipeline-<이름>
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 새 스키마 <pg_schema>_<이름>
bash deploy/host/scripts/pipe_exec.sh migrate master load
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp
bash deploy/host/scripts/host_ctl.sh check                                   # 기대 마지막 줄: [host_ctl check] 통과 — 6개
```
- EDW 기록 표 `AI.ParsingMeta_<이름>`은 DB 담당이 미리 만든다(`parsing_meta_mssql.sql`의 표 이름만 바꿔서).
- 새벽 배치가 필요 없는 벌은 `systemctl disable --now data-pipeline-nightly-<이름>.timer`.
- **SSH 작업 공간(선택):** `option.devbox.ssh_port`에 자기 포트를 적으면 `data-pipeline-<이름>`이 SSH로 들어가 코드 폴더를 고칠 수 있는 작업 공간으로 뜬다 — 열쇠 놓기·접속·끄기는 README [§5-0 "개발 작업 공간"](../../README.md#5-0-배포-단계와-개발-서버-설치).

## 3. 매일 쓰는 법

- 코드 바꾸기 = 그 코드 폴더에서 `git pull`(또는 작업 공간에서 고쳐 커밋·push). 개발 서버는 실행 이미지 + 코드 폴더 마운트라 컨테이너를 다시 띄우면 반영된다 — `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp`. 의존성 지문(`deploy/docker/DEPS_HASH`)이 바뀐 커밋은 새 실행 이미지가 필요하다([release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--새-루트로-코드-바꾸기)).
- 공용 main 벌은 gitea `main`만 받는다. 판을 바꿀 때는 새 루트로([upgrade-guide.md](upgrade-guide.md)).
- **`server-changes.md`·`issues.md`·`versions.md`** — [server-guide §7](server-guide.md#7-개발자에게-보고하는-법) 형식.
- gitea 저장소·권한·외부망 `main`을 옮기는 방법, 개발자별 벌 목록을 둘 곳은 [refactor.md](../refactoring/refactor.md)의 열린 항목에서 정한다.
