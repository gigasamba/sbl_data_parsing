# 내부망 코드 관리 — gitea (P-08)

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md)

**결정(사용자 11-02 — P-08, 10-30의 "배포 번들 + 기록 문서 유지"를 바꿈):** 내부망 코드는 내부망 gitea 저장소로 관리한다. 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`).

## 1. 사람마다 코드 폴더 하나 + 공용 main 묶음

| 묶음 | 컨테이너 | 코드 |
|---|---|---|
| 개발자마다 하나 | `data-pipeline` · `data-pipeline-mcp` · `mcp-server`(상주 3개 — `dc.sh`) | 자기 gitea 브랜치를 받은 자기 코드 폴더 |
| 공용 main 묶음 하나 | 위와 같은 3개 | gitea `main` |

- **한계 — 한 서버(한 컨테이너 엔진)에는 묶음 하나만 동시에 띄운다.** compose 파일이 컨테이너 이름을 고정한다(`container_name: data-pipeline`·`data-pipeline-mcp`·`mcp-server` — `deploy/host/compose/`). 같은 엔진에서 두 번째 묶음을 띄우면 이름이 겹쳐 시작하지 않는다. 사람마다 묶음을 따로 띄우려면 서버(또는 계정마다 따로 도는 rootless podman)를 나누거나, 컨테이너 이름을 사람별로 나누는 방법을 먼저 정해야 한다(아직 없음 — §3).
- **pgvector는 우리 compose에 없다.** PG는 DB 담당이 주는 서버를 쓰고(`required.pg`), 사람마다 PG 스키마 이름(`required.pg.db_schema`)만 다르게 준다.
- **포트와 스키마 이름은 사람마다 다르다 — settings.yaml로만 준다.** 포트·PG 스키마·결과 폴더를 코드나 compose에 사람별로 적지 않는다(사람마다 settings.yaml 하나 — [env-guide.md](env-guide.md)). 다른 사람의 포트·스키마를 쓰지 않는다.
- **gitea 전용 코드는 두지 않는다.** git 명령과 브랜치 규칙만 쓴다.

## 2. 그대로 남기는 것

- **코드 폴더 바꾸기** — 개발 서버(dev)는 코드 없는 실행 이미지 + 코드 폴더 마운트(`CODE_DIR` — `dc.sh`가 자기가 든 코드 폴더를 붙임, 서버 배치는 `/srv/rag/code/live` 링크)라서 코드 폴더를 바꾸면 반영된다. 옛 오버레이 패치 길(`make_patch.sh`)은 이 길로 바뀌었다([release-and-patch.md](release-and-patch.md) §1-1·§3).
- **`server-changes.md`** — 서버에서 생긴 문제·서버에서 직접 고친 것의 이슈 기록([server-guide.md](server-guide.md) §7 형식, [release-and-patch.md](release-and-patch.md) §3-4).
- **`versions.md`** — 판마다 패치 노트 한 줄([release-and-patch.md](release-and-patch.md) §7).

## 3. 아직 정할 것

- gitea 저장소 주소·계정·권한, 외부망 `main`을 내부망 gitea로 옮기는 방법과 때(반입 절차) — 사람이 정한다(주소·계정은 이 문서에 쓰지 않는다).
- 개발자별 포트·스키마 이름 목록을 어디에 둘지(값은 각자 settings.yaml).
- 한 서버에 묶음을 여러 개 띄울지 — 띄운다면 컨테이너 이름을 사람별로 나누는 방법(§1 한계).
