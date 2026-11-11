# sbl_data_parsing — 문서 파싱 · 구조화 · 적재 · 근거 검색(MCP)

사내 문서(PDF, Office, HWPX, 이미지, 메일 등)를 파싱하고, 청킹·임베딩해 PostgreSQL(pgvector)에 적재한 뒤, **검색 MCP 서버**로 근거를 찾아 주는 파이프라인이다. 개발은 macOS·Windows PC에서 하고, 실행은 내부망(폐쇄망) RHEL 서버의 Docker 이미지 2개로 한다. 기능 요건은 [docs/PRD.md](docs/PRD.md), 문서 지도·용어집은 [docs/INDEX.md](docs/INDEX.md#glossary), 개발 규칙은 [CLAUDE.md](CLAUDE.md).

> **⚠️ `docker compose`를 직접 부르지 않는다.** 서버 컨테이너는 늘 `bash deploy/host/scripts/host_ctl.sh …`로 다룬다([dev.md](docs/operations/dev.md) · [prd.md](docs/operations/prd.md)).
>
> **⚠️ 실제 값(비밀번호·키·토큰·서버 주소)은 문서·채팅·커밋에 쓰지 않는다.** 문서의 예시 값은 모두 가짜다.
>
> **Windows PC는 WSL(리눅스)에서만 쓴다.** 명령은 모두 `.venv/bin/…` 꼴이다.

**PC 첫 실행** — 처음 받은 사람이 PC에서 검색까지 한 번 돌려 보는 길은 [docs/operations/local.md](docs/operations/local.md) 한 장이다: 가상환경 → `settings.yaml` → 시험 DB(pgvector) → 점검 → 문서 몇 건(파싱 → 구조화 → DB 표 → 적재 → 검색) → 검색 MCP → 검증 페이지.

**담당 연락처**(역할만 — 이름은 맡은 사람이 채운다. 연락처 값은 사내 기록에 둔다)

| 역할 | 맡는 일 | 담당 |
|---|---|---|
| 지금 담당자("사용자" — [INDEX 용어집](docs/INDEX.md#glossary)) | 결정·사람 검토(등급 A) 승인·이미지 저장소·릴리스 | `<이름>` |
| 서버 운영 | 개발·운영 서버 설치·판 올리기·타이머·로그 점검 | `<이름>` |
| DB 담당(PostgreSQL) | pgvector DB·계정·스키마·마이그레이션 합의·백업·복원 | `<이름>` |
| EDW 담당(회사 DB) | `AI.FileStorageMap` 등 원천 표와 읽기 계정 | `<이름>` |
| 모델 담당 | 내부망 LLM·VLM·임베딩 주소·모델·임베딩 차원 | `<이름>` |
| 스토리지 담당 | Object Storage 버킷·접근 키 | `<이름>` |
| MCP 클라이언트 담당 | 검색 MCP를 붙여 쓰는 쪽 — 도구 계약이 바뀌면 알림 받음 | `<이름>` |
| devops(빌드·반입) | 이미지 빌드·폐쇄망 반입(휠·`assets/`) | `<이름>` |

---

## 1. 처리 흐름

```
원천 문서(폴더 · rdb:csv 목록)
   │  ① parse     중복 제거 → 쪽 방향 보정 → 엔진별 파싱 → 대표 결과(문서마다 하나)     ┐
   │  ② publish   대표 결과를 Object Storage에 올리고 처리 기록을 남김                    │
   │  ③ (원본 삭제 — 게시가 성공한 문서만)                                            │ data-pipeline 이미지
   │  ④ structure 청킹 · 임베딩 → 번들                                                │
   │  ⑤ load      번들 → PostgreSQL(pgvector) 적재                                    ┘
   ▼
검색 MCP 서버 — 도구 6개: search · query_edw · parse_document · edw_meta ·              mcp-server 이미지
                          list_doc_fulltext · get_doc_fulltext
```

서버에서는 호스트의 `run_pipeline.py`가 문서마다 이 순서로 흘려 보낸다(DAG 엔진 없음 — 종료 코드는 [PRD pl-18](docs/prd/ops.md#pl-18)). MCP 도구 6개의 이름과 입출력은 외부 클라이언트와의 계약이다([mcp-guide](docs/operations/mcp-guide.md)). 단계별 파일·함수 지도는 [parse_flow.md](docs/architecture/parse_flow.md).

| 모듈 | 하는 일 | 진입점 | 결과 |
|---|---|---|---|
| **parse** | 원천 읽기 · 중복 제거 · 준비 · 엔진별 파싱 + 대표 결과 | `python -m pipeline.cli parse` | `<결과 폴더>/parse/_rep/`(끝나면 `_DONE.json`) |
| **publish** | Object Storage 업로드 + 처리 기록 파일 `publish/silver.jsonl`(EDW에는 쓰지 않음) | `python -m pipeline.load.publish_parse_result` | (운영 시스템에 기록) |
| **structure** | 청킹 · 임베딩 → 번들 | `python -m pipeline.transform.structure.gold_bundle` | 번들 폴더 |
| **load** | 번들 → pgvector | `python -m pipeline.load.pgvector_load` | (PostgreSQL 안) |

## 2. 이미지·실행 모드·DB

- **이미지 2개:** `data-pipeline`(parse·publish·structure·load — 상주 컨테이너 `data-pipeline`과 `parse_document` 전용 `mcp-data-parsing`) · `mcp-server`(검색 MCP). 모두 `deploy/docker/Dockerfile` 한 파일에서 나오고, 버전은 저장소 루트 `VERSION` 하나를 함께 쓴다(규칙 [CLAUDE.md §5-2](CLAUDE.md)).
- **실행 모드(`required.env.run_env`):** `local`(PC — 이미지 없이 Python으로, [local.md](docs/operations/local.md)) · `dev`(개발 서버 — 코드 없는 실행 이미지에 벌의 `app/` 코드 폴더를 붙임, [dev.md](docs/operations/dev.md)) · `prd`(운영 서버 — 개발 서버에서 시험한 코드를 실행 이미지에 구운 이미지, [prd.md](docs/operations/prd.md)). 실행 이미지 판은 그 판의 `BUILD.txt` `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 것을 쓴다([dev.md A-2](docs/operations/dev.md#a-2-실행-이미지-불러오기판마다-한-번)).
- **DB:** 표는 모두 Alembic 마이그레이션으로 만들고 명령은 `dbtool` 하나다 — 갈래·끝 판·명령은 [db_schema.md §7](docs/architecture/db_schema.md#7-판-올리기--dbtool), 표·칸은 같은 문서.

## 3. 폴더 구조

폴더마다 두는 것과 모듈 경계는 [CLAUDE.md §1](CLAUDE.md) 표에 있다(`python -m common.check.check_modules`가 경계를 확인).

## 4. 설정

모든 설정 값과 비밀값은 **settings.yaml 한 파일**에 둔다(코드는 환경변수에서 설정을 읽지 않는다). 칸 전체·기본값은 [settings.sample.yaml](settings.sample.yaml), 환경마다 채울 칸·PC 전용 칸·`--set 이름=값`은 [docs/operations/settings.md](docs/operations/settings.md).

## 5. 실행 안내 — 환경마다 한 장

그 기계에 들어가 위에서부터 친다.

| 환경 | 문서 |
|---|---|
| PC | [docs/operations/local.md](docs/operations/local.md) |
| 개발 서버 | [docs/operations/dev.md](docs/operations/dev.md) — 호스트 설치·운영(A) · 벌 컨테이너 안 시험(B) · 벌끼리 간섭 없이 일하기(C) · 출시 전 시험(D) |
| 운영 서버 | [docs/operations/prd.md](docs/operations/prd.md) — 설치·운영 반영(`promote.sh`)·판 올리기·되돌리기 |
| 설정 칸 | [docs/operations/settings.md](docs/operations/settings.md) |

`parse_document`는 서버당 Redis 하나(`compose-redis.yml`)를 쓴다 — 요건 [PRD op-19](docs/prd/ops.md#op-19).

## 6. 꼭 지킬 것 · 문서

규칙 전체는 [CLAUDE.md](CLAUDE.md) §2~§5(핑거프린트·계약·비밀값·운영 접속 가드·배포 환경·새 패키지). 문서 지도는 [docs/INDEX.md](docs/INDEX.md), 알려진 문제·미개발 항목은 [docs/PRD.md](docs/PRD.md) 표의 `todo` 행.
