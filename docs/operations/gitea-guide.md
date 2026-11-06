# 내부망 코드 관리 — gitea

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · [upgrade-guide.md](upgrade-guide.md)

내부망 코드는 내부망 gitea 저장소로 관리한다. 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`). 저장소 주소·계정은 이 문서에 쓰지 않는다.

## 1. 개발자마다 한 벌 + 공용 main 한 벌

개발 서버 한 대에 여러 벌을 띄운다. 벌 폴더(코드 폴더 = gitea clone) 하나가 한 벌이고, 폴더 이름 끝 `-<숫자>`(벌 번호)로 컨테이너·compose 묶음·타이머 이름이 나뉜다([server-guide §1-3](server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별)).

| 벌 | 벌 폴더(예) | 코드 | 컨테이너 |
|---|---|---|---|
| 공용 main | `/home/sbl/sbl_data_parsing-main-1` | gitea `main` | `data-pipeline-1`·`mcp-data-parsing-1`·`mcp-server-1` |
| 개발자마다 하나 | `/home/sbl/sbl_data_parsing-main-2` | 그 개발자의 gitea 브랜치 | 끝 `-2` |

- **pgvector는 우리 compose에 없다.** PG는 DB 담당이 주는 서버를 쓰고, 모든 벌이 같은 기준 스키마를 함께 쓴다 — 모든 벌을 같은 코드 판으로 둔다.
- **포트는 그 벌의 settings.yaml로만 준다**(코드나 compose에 사람별로 적지 않음). 다른 사람의 포트·벌 번호를 쓰지 않는다.
- `settings.yaml`·`edw_chain.yaml`·`output/`·`home/`은 clone 안에 있지만 git 제외 목록(`.gitignore`)에 있어 커밋되지 않는다.
- 이미지는 공용 폴더에 한 번 불러 두면 모든 벌이 같이 쓴다.
- gitea 전용 코드는 두지 않는다 — git 명령과 브랜치 규칙만 쓴다.

## 2. 개발자 한 벌 만들기

root 셸에서(`<번호>` = 다른 벌과 겹치지 않는 벌 번호):
```bash
export DOCKER=podman
cd /home/sbl
git clone -b <내 브랜치> <gitea 저장소 주소> sbl_data_parsing-main-<번호>    # 벌 폴더 = 코드 폴더 = 내 작업 폴더
cd sbl_data_parsing-main-<번호> && git rev-parse --short HEAD > CODE_COMMIT   # clone은 CODE_COMMIT을 채우지 않음 — 시작 로그의 커밋 표시용
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>               # settings.yaml·edw_chain.yaml·output/(ssh_port를 적은 뒤 다시 부르면 home/)
```
그다음 `settings.yaml`에 공용 벌의 값(접속·모델·이미지 칸)을 옮기고, 벌마다 다른 칸을 적는다:
```yaml
ops:
  services:
    data_parsing: {data_parsing_port: <다른 벌과 겹치지 않는 포트>}   # 기본 8766 그대로면 시작 거부
search:
  server: {mcp_port: <다른 벌과 겹치지 않는 포트>}                    # 기본 8765 그대로면 시작 거부
```
이어서 띄운다([handover-guide §13](handover-guide.md#13-두-번째-벌-만들기)과 같다 — DB 표는 공용이라 이미 만든 서버면 `migrate` 두 줄은 건너뛴다):
```bash
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline                     # → data-pipeline-<번호>
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 공용 DB에 처음 한 번만
bash deploy/host/scripts/pipe_exec.sh migrate master load                    # 공용 DB에 처음 한 번만
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp
bash deploy/host/scripts/host_ctl.sh check                                   # 기대 마지막 줄: [host_ctl check] 통과 — 6개
```
- 자기 원천 `DEV-<숫자>`만 파싱하려면 `required.source.source_systems: [DEV-<숫자>]`를 적고(비우면 운영 5개 원천 전부), 처음 한 번 `bash deploy/host/scripts/pipe_exec.sh migrate up --target search`로 원천 스키마를 만든다 — 차례와 확인 출력은 [handover-guide.md](handover-guide.md).
- 새벽 배치가 필요 없는 벌은 `systemctl disable --now data-pipeline-nightly-<번호>.timer`.
- **SSH 작업 공간(선택):** `option.devbox.ssh_port`에 자기 포트를 적고 `host_ctl.sh init`을 다시 부르면 `data-pipeline-<번호>`가 SSH로 들어가 코드 폴더를 고칠 수 있는 작업 공간으로 뜬다 — 열쇠 놓기·접속·끄기는 README [§5-0 "개발 작업 공간"](../../README.md#5-0-배포-단계와-개발-서버-설치).
- **작업 공간의 gitea 계정(선택):** 작업 공간에서 바로 `git pull`·`push`하려면 그 벌의 settings.yaml 맨 아래 `option.devbox`에 적고 `host_ctl.sh up -d data-pipeline`으로 다시 띄운다 — 시작할 때 홈에 `~/.git-credentials`(권한 600)가 생긴다(토큰은 화면·로그·컨테이너 env에 나오지 않음). 토큰은 gitea 웹의 내 설정 > 응용 > 새 토큰(저장소 읽기·쓰기 권한)에서 만든다. `~/.git-credentials`의 다른 줄은 그대로 두고 그 gitea 호스트 줄만 바꾼다. 셋(`gitea_url`·`gitea_user`·`gitea_token`) 중 하나라도 비우면 전에 쓴 그 호스트 줄을 지운다. 주소 꼴은 `http(s)://호스트[:포트][/경로]` — 틀리면 경고만 남기고 아무것도 쓰지 않는다.
```yaml
option:
  devbox:
    ssh_port: <내 포트>
    gitea_url: https://<gitea 주소>:<포트>    # 예 https://gitea.example.local:3000 — http면 토큰이 암호화 없이 감
    gitea_user: <내 gitea 계정>
    gitea_token: <내 토큰>                   # 비밀 — settings.yaml에만
    git_user_name: <커밋에 남길 이름>         # 선택
    git_user_email: <커밋에 남길 메일>        # 선택
```

## 3. 매일 쓰는 법

- 코드 바꾸기 = 그 코드 폴더에서 `git pull`(또는 작업 공간에서 고쳐 커밋·push). 개발 서버는 실행 이미지 + 코드 폴더 마운트라 컨테이너를 다시 띄우면 반영된다 — `bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp`. 의존성 지문(`deploy/docker/DEPS_HASH`)이 바뀐 커밋은 새 실행 이미지가 필요하다([release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--코드-폴더-덮어쓰기)).
- 공용 main 벌은 gitea `main`만 받는다. 판을 바꿀 때는 [upgrade-guide.md](upgrade-guide.md) 순서(백업 → DB 판 → 점검) — 벌이 같은 DB를 쓰므로 모든 벌을 같은 판으로.
- **`server-changes.md`·`issues.md`·`versions.md`** — [server-guide §7](server-guide.md#7-개발자에게-보고하는-법) 형식.
- gitea 저장소·권한·외부망 `main`을 옮기는 방법, 개발자별 벌 목록을 둘 곳은 [refactor.md](../refactoring/refactor.md)의 열린 항목에서 정한다.
