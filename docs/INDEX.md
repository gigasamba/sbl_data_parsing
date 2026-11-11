# 문서 지도

사람이 읽는 문서를 한 표에 모았다. 문서를 더하거나 옮기면 이 표와 [CLAUDE.md](../CLAUDE.md) §8을 같은 커밋에서 고친다.

| 문서 | 무엇 | 언제 읽나 |
|---|---|---|
| [README.md](../README.md) | 프로젝트 소개 — 처리 흐름·모듈·이미지와 실행 모드 요약·담당 역할, 환경별 실행 안내로 가는 링크 | 처음 볼 때 |
| [PRD.md](PRD.md) · [prd/extract.md](prd/extract.md) · [prd/transform.md](prd/transform.md) · [prd/transform-cleanup.md](prd/transform-cleanup.md) · [prd/load.md](prd/load.md) · [prd/load-schema.md](prd/load-schema.md) · [prd/mcp.md](prd/mcp.md) · [prd/ops.md](prd/ops.md) · [prd/ops-settings.md](prd/ops-settings.md) · [prd/test.md](prd/test.md) · [prd/doc.md](prd/doc.md) | 기능 요건 — 카테고리 7개: 수집, 변환(정리·지문 배치는 transform-cleanup), 적재(DB 스키마는 load-schema), 검색 MCP, 운영(설정은 ops-settings), 테스트, 문서·릴리스. PRD.md는 묶음 표와 지금 진행 중. 카테고리 파일 끝에 요건과 다른 코드·요건 없는 코드 | 기능을 고치거나 더하기 전에, 할 일을 고를 때 |
| [CLAUDE.md](../CLAUDE.md) | 작업 규칙 — 지문·계약·운영 가드, 경계·이름, 배포 환경 규칙, 로컬 하네스·점검 명령 | 작업을 시작하기 전에 늘 |
| [refactoring/refactor.md](refactoring/refactor.md) | 서버·사람이 확인할 열린 사항(C-xx) — 무엇을 돌리고 무엇이 통과인지 | 서버 배포 전후, 담당자와 협의할 때 |
| [operations/local.md](operations/local.md) | PC 실행 순서 — 가상환경·settings.yaml(예시)·시험 DB·점검·문서 몇 건(파싱 → 구조화 → DB 표 → 적재 → 검색)·검색 MCP·검증 페이지·compose-local·코드가 든 시험 이미지 | PC에서 처음 돌리거나 시험할 때 |
| [operations/dev.md](operations/dev.md) | 개발 서버 실행 순서 — A 호스트(벌 폴더 `data_pipeline-<n>/{app,home}`·이미지·PG·Redis·홈 묶음·방화벽·띄우기·점검·`run_pipeline.py` 한 번에·`pipe_exec.sh` 단계 하나씩·백업·코드 바꾸기·이미지 정리) · B 벌 컨테이너 안(`python -m`으로 설정 확인·selftest·DB 표·파싱·게시·적재·검색) · C 벌끼리 간섭 없이 일하기(git·opencode) · D 출시 전 시험(운영 묶음) | 개발 서버를 설치하거나 벌에서 시험할 때 |
| [operations/prd.md](operations/prd.md) | 운영 서버 실행 순서 — 굽기·옮기기·운영 폴더 `data_pipeline/{app,home}`·운영 반영(`promote.sh`)·`run_pipeline.py`·타이머(새벽 배치·MCP 살리기)·이미지 정리, 판 올리기, 되돌리기 | 운영 서버를 설치하거나 새 판으로 올릴 때 |
| [operations/settings.md](operations/settings.md) | 설정 파일 구조·쓰는 법, 환경마다 사람이 채울 칸, 파싱할 원천, PC 전용 칸(가짜 대상·외부 모델·VLM), 새벽 배치 칸, `--set 이름=값` 쓰는 법 | 설정 값을 채우거나 한 번만 바꿔 돌릴 때 |
| [operations/mcp-guide.md](operations/mcp-guide.md) | 검색 MCP 도구 6개의 입력·출력·한도·오류·예(표는 `tests/general/mcp/test_mcp_guide.py`가 코드와 대조) | MCP 클라이언트를 붙이거나 도구 입출력을 바꿀 때 |
| [architecture/db_schema.md](architecture/db_schema.md) | DB 스키마 명세 — gold(원천별 5벌 — 처리 기록 칸 포함)·EDW(`AI.FileStorageMap` — 읽기만)·마스터(`<스키마>_master`)·`applog`, 판 올리기 `dbtool`(§7), 아직 없는 표(§8). 시험 `tests/server/common/test_db_schema.py`가 판·SQL과 대조 | DB 표·칸을 바꾸거나 DB 담당자와 협의할 때 |
| [architecture/resources.md](architecture/resources.md) | 코드가 읽는 자료 — §1 엔진 구성 파일(`resources/config/pipeline_stack.json` — 모양 검사·바꾸기·되돌리기·엔진 거부) · §2 AI 지시서 패키지(`resources/prompts/` + 답변 점검 `rag_qa` — 찾는 순서·구성·캐시 열쇠·입출력·호출부) | 엔진 구성을 바꾸거나 지시서·LLM·VLM 호출부를 볼 때 |
| [architecture/parse_flow.md](architecture/parse_flow.md) | 파싱 실행 흐름 — 입구(`run_pipeline.py`·`pipeline.cli`) → extract → transform → load → 검색 MCP를 단계별 그림(mermaid)과 파일 역할 표로, 단계별 산출물·캐시 열쇠, 설정·로그·출력 폴더 | 코드가 실제로 어떤 순서로 도는지, 결과가 어디에 쌓이는지 볼 때 |
| [history/](history) | 지난 기록(보관만 — 고치지 않음) — 예 0.2.0 배포 절차 [history/deploy_0_2_0.md](history/deploy_0_2_0.md), 0.4까지의 긴 서버 가이드 [history/server-guide-0.4.md](history/server-guide-0.4.md)·설정 가이드 [history/env-guide-0.4.md](history/env-guide-0.4.md), C-95 설정 칸 이름 대응표 [history/c95_key_map.md](history/c95_key_map.md). [refactoring/refactor_plan.md](refactoring/refactor_plan.md)는 옮긴 곳 안내 | 옛 결정(`D-xxx`·`P-xx`)·이력을 찾을 때 |

## 예외

- `deploy/host/compose/` compose 파일: 환경마다 하나 `compose-local.yml`·`compose-dev.yml`·`compose-prd.yml` + 따로 띄우는 `compose-pgvector.yml`·`compose-redis.yml`.

## Glossary

**약어**
| 말 | 뜻 |
|---|---|
| PRD | 기능 요건 문서 — [PRD.md](PRD.md)와 `prd/<카테고리>.md` |
| ID 접두 | `mc` 검색 MCP · `pl` 데이터 파이프라인 · `e2` 시험·평가 · `rn` 서버 flow 러너 · `op` 운영(설정·계정·로그·릴리스) · `do` 문서 — 파일 자리는 카테고리가 정함 |
| C-xx · D-xxx · P-xx | `refactor.md`의 서버·사람 확인 사항 · [history/refactor_plan.md](history/refactor_plan.md) 7절 결정 · 8절 미정 |
| EDW | 회사 DB(SQL Server) — `AI.FileStorageMap`(원본 목록)·원천 표 — 이 프로젝트는 읽기만 함 |
| OS | Object Storage — 원본과 파싱 결과(silver) 파일 |
| staging · silver · gold | Object Storage 원본을 임시 폴더로 받아 둔 것(원본은 OS에 있으니 따로 보관하지 않음) · 엔진별 파싱 결과 `parse/<엔진>/<문서>.json`과 대표 결과(게시하면 OS) · 검색용 적재 결과(pgvector `doc`·`chunk`… — `doc`에 처리 기록) |
| MCP | 검색 서버(Model Context Protocol) — 도구 `search`·`query_edw`·`parse_document`·`edw_meta`·`list_doc_fulltext`·`get_doc_fulltext` |
| VLM · OCR | 이미지를 읽는 언어 모델 · 글자 인식 엔진 |
| BM25 · RRF · HNSW | 낱말 점수 검색 · 순위 합치기 · pgvector 근사 최근접 색인 |
| code_fp · FINGERPRINT | 레이어 코드 핑거프린트(p0·p1·r·s) · 핸드오프 핑거프린트 — 바뀌면 서버 재처리(CLAUDE.md §4) |
| RUN_ENV | 실행 환경 `local`(PC)·`dev`·`prd` |
| 등급 A | 사람 검토가 필요한 변경(핑거프린트·계약·DB·운영 접속·비밀값) |
| 사용자 | 이 프로젝트의 결정을 내린 사람(지금 담당자). 문서·주석의 "사용자 MM-DD"는 그 사람이 그날 정한 것이라는 뜻 — 바꾸려면 지금 담당자와 정한다 |

**프로젝트 용어**
| 말 | 뜻 |
|---|---|
| 원천 | 문서가 온 시스템 — `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`(개발 서버·PC는 `DEV-<숫자>`도). 검색할 때는 원천을 꼭 하나 고른다 |
| 마스터 표 | 용어집·고객 명부·ID 꼴 표(`<스키마>_master.glossary`) — 원본은 git의 `resources/vocab/glossary/glossary.csv` |
| 실행 이미지(`*-runtime`) | 코드가 없는 이미지 — 개발 서버는 코드 폴더를 붙여 쓰고, 운영 서버는 코드를 구워 넣은 이미지를 쓴다 |
| 벌 · 코드 폴더(루트) | 벌 = 한 서버에 따로 띄운 컨테이너 한 묶음 — 폴더 `<벌>/{app,home}`(개발 벌 `/home/sbl/data_pipeline-<n>/`, 운영 묶음 `/home/sbl/data_pipeline/`). 코드 폴더 = 루트 = `app/`(코드 zip을 푼 폴더 — `settings.yaml`·`edw_chain.yaml`·`output/`이 그 안, 컨테이너 `/app`). `home/`은 root 홈(컨테이너 `/root`) |
| `$DOCKER` | 컨테이너 명령 — 서버는 `docker`(root 셸). 셸에서 `export DOCKER=docker` |
| 묶음(번들) | 구조화 결과 폴더(`docs.jsonl`·청크·벡터) — 적재의 입력(검색은 PG만 읽는다) |
| 대역 | PC에서 외부 시스템을 흉내 내는 것(EDW sqlite `valid_env/edw/edw.sqlite` — PG는 대역 없이 PC 시험 pgvector 컨테이너) |
| 스택 | 파일 형식마다 도는 엔진 목록(`resources/config/pipeline_stack.json`) |
| represent | 엔진 결과 중 대표를 고르고 고치는 단계 |
| flow 러너 | 서버 호스트의 문서별 실행기 `run_pipeline.py` — 레인 light·medium·vlm, staging(미리 받기) |
| selftest | 이미지 안 반입 시험(`tests/server/`) — `[판정]` 줄로 판정 |
| 사슬 파일 | EDW 조인 사슬 `edw_chain.yaml`(저장소 맨 위) — 원천별 메타 키·거르기·근거 키 |

**같은 뜻의 말**(문서와 코드 주석에 섞여 나온다)
시험=테스트 · 반입=(폐쇄망) 배포 · 칸=항목/컬럼 · 판=버전 · 지문=핑거프린트 · 열쇠=키 · 층=레이어 · 묶음=번들 · 대장=레지스트리 · 인계=핸드오프 · 덮기 파일=오버레이 설정 파일 · 게시=퍼블리시 · 지시서/지시문=프롬프트.

**옛 CLAUDE.md 절 번호**(코드 주석에 남음 — 공용·레이어 파일 주석은 고치면 code_fp가 바뀌어 그대로 둔다)
옛 3절 → §2·§3·§4 · 옛 4절 → §5·§9 · 옛 5절 → §7 · 옛 6절 → §6.
