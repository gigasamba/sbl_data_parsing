# 내부망 코드 관리 — gitea

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md)

내부망 코드는 내부망 gitea 저장소로 관리한다(P-08). 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`).

## 1. 사람마다 코드 폴더 하나 + 공용 main 묶음

| 묶음 | 컨테이너 | 코드 |
|---|---|---|
| 개발자마다 하나 | `data-pipeline` · `mcp-data-parsing` · `mcp-server`(`host_ctl.sh`) | 자기 gitea 브랜치를 받은 자기 코드 폴더 |
| 공용 main 묶음 하나 | 위와 같은 3개 | gitea `main` |

- **한계 — 한 서버(한 컨테이너 엔진)에는 묶음 하나만 동시에 띄운다.** compose 파일이 컨테이너 이름을 고정한다(`container_name: data-pipeline`·`mcp-data-parsing`·`mcp-server`). 사람마다 묶음을 따로 띄우려면 서버(또는 계정마다 따로 도는 rootless podman)를 나눈다.
- **pgvector는 우리 compose에 없다.** PG는 DB 담당이 주는 서버를 쓰고, 사람마다 `required.pg.db_schema`만 다르게 준다.
- **포트·PG 스키마·결과 폴더는 사람마다 settings.yaml로만 준다**(코드나 compose에 사람별로 적지 않음). 다른 사람의 포트·스키마를 쓰지 않는다.
- gitea 전용 코드는 두지 않는다 — git 명령과 브랜치 규칙만 쓴다.

## 2. 그대로 쓰는 것

- **코드 폴더 바꾸기** — 개발 서버는 실행 이미지 + 코드 폴더 마운트라서 코드 폴더를 바꾸면 반영된다([release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--코드-폴더-바꾸기)).
- **`server-changes.md`·`issues.md`·`versions.md`** — [server-guide §7](server-guide.md#7-개발자에게-보고하는-법) 형식.

## 3. 아직 정할 것

- gitea 저장소 주소·계정·권한, 외부망 `main`을 내부망 gitea로 옮기는 방법과 때(주소·계정은 이 문서에 쓰지 않는다).
- 개발자별 포트·스키마 이름 목록을 어디에 둘지(값은 각자 settings.yaml).
- 한 서버에 묶음을 여러 개 띄울지 — 띄운다면 컨테이너 이름을 사람별로 나누는 방법.
