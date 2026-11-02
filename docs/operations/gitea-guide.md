# 내부망 코드 관리 — gitea (P-08)

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md)

**결정(사용자 11-02 — P-08, 10-30의 "배포 번들 + 기록 문서 유지"를 바꿈):** 내부망 코드는 내부망 gitea 저장소로 관리한다. 외부망(PC) 흐름은 그대로다(CLAUDE.md §5-1 — `main`·`develop`·`feature/*`·`release/*`).

## 1. 사람마다 상주 컨테이너 4개 + 공용 main 묶음

| 묶음 | 컨테이너 | 코드 |
|---|---|---|
| 개발자마다 하나 | `pgvector` · `mcp-server` · `data-pipeline` · `data-pipeline-mcp`(상주 4개) | 자기 gitea 브랜치를 받은 자기 코드 폴더 |
| 공용 main 묶음 하나 | 위와 같은 4개 | gitea `main` |

- **포트와 스키마 이름은 사람마다 다르다 — settings.yaml로만 준다.** 컨테이너 이름·포트·PG 스키마(`PG_SCHEMA`)·결과 폴더를 코드나 compose에 사람별로 적지 않는다(사람마다 settings.yaml 하나 — [env-guide.md](env-guide.md)). 다른 사람의 포트·스키마를 쓰지 않는다.
- **gitea 전용 코드는 두지 않는다.** git 명령과 브랜치 규칙만 쓴다.

## 2. 그대로 남기는 것

- **오버레이 패치** — 개발 서버(dev)에서는 코드 폴더의 파일을 바꾸면 바로 반영된다(코드 없는 실행 이미지 + 코드 폴더 마운트 — [release-and-patch.md](release-and-patch.md) §1-1·§3).
- **`server-changes.md`** — 서버에서 생긴 문제·서버에서 직접 고친 것의 이슈 기록([server-guide.md](server-guide.md) §7 형식, [release-and-patch.md](release-and-patch.md) §3-4).
- **`versions.md`** — 판마다 패치 노트 한 줄([release-and-patch.md](release-and-patch.md) §7).

## 3. 아직 정할 것

- gitea 저장소 주소·계정·권한, 외부망 `main`을 내부망 gitea로 옮기는 방법과 때(반입 절차) — 사람이 정한다(주소·계정은 이 문서에 쓰지 않는다).
- 개발자별 포트·스키마 이름 목록을 어디에 둘지(값은 각자 settings.yaml).
