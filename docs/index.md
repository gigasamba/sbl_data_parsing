# 문서 지도

이 저장소의 사람이 읽는 문서를 한 표에 모았다. 문서는 `docs/` 아래 유형별 폴더에 둔다(refactor_plan 4-1 `docs/`). 문서를 더하거나 옮기면 이 표와 [CLAUDE.md](../CLAUDE.md) §8을 같은 커밋에서 고친다.

| 문서 | 무엇 | 언제 읽나 |
|---|---|---|
| [README.md](../README.md) | 프로젝트 소개 — 처리 흐름·실행 단위(모듈 4개·완료 표시)·이미지와 버전·폴더 구조·설정(settings.yaml)·PC 실행 단계(①~⑥)·서버 배포와 실행 방법 비교(trigger 하나씩·all·night·run_docs)(상세는 아래 운영 문서로 연결 — 10-29) | 처음 볼 때, 실행 방법을 찾을 때 |
| [PRD.md](PRD.md) · [prd/mcp.md](prd/mcp.md) · [prd/pipeline.md](prd/pipeline.md) · [prd/e2e.md](prd/e2e.md) · [prd/runner.md](prd/runner.md) · [prd/doc.md](prd/doc.md) · [prd/ops.md](prd/ops.md) · [prd/gaps.md](prd/gaps.md) | 기능 요건 — 검색 MCP(`mc-xx`)·데이터 파이프라인(`pl-xx`)·e2e 실행·테스트·평가(`e2-xx`)·서버 flow 러너 레인·대기열(`rn-xx`)·문서 배치(`do-xx`)·로그(`op-xx`)의 기능마다 무엇·왜·관련 코드 파일, PRD.md는 미개발·미해결 항목 표(10-29 — 옛 CLAUDE.md §10 알려진 문제 포함), gaps.md는 요건과 다른 코드·요건 없는 코드·기본 꺼짐 기능·10-29 삭제 목록 | 기능을 고치거나 더하기 전에, 할 일을 고를 때 |
| [CLAUDE.md](../CLAUDE.md) | 작업 규칙 — 지문·계약·운영 가드, 경계·이름, 배포 환경 규칙, 로컬 하네스·점검 명령 | 작업을 시작하기 전에 늘 |
| [refactoring/refactor_plan.md](refactoring/refactor_plan.md) | 리팩토링 가이드·결정 장부 — 원칙·목표 구조·단계(6-1 S0~S11)·결정(7절 D)·미정(8절 P·T)·이동표(9-1 — pre-refactor 파일의 이동 기록) | 작업 전에 0~3절, 맡은 단계의 절·9절 |
| [../refactor.md](../refactor.md) | 서버·사람이 확인해야 할 사항(C-xx) — 저장소 안에서 끝낼 수 없는 확인·협의 · 머리의 **"최종 — 사람이 할 일"**(사람 할 일의 정본 — 검토 등급 A·반입 전·때·뒤·다음 판, 누가·언제·C) | 단계를 끝낼 때(새 확인 사항 덧붙임), 반입 준비·반입 때 |
| [operations/server-guide.md](operations/server-guide.md) | 서버 가이드 — 이미지 역할, 설치·첫 실행, 일상 실행, 결과 확인, 검색 MCP·EDW 질의 도구, 회사 맞춤, 문제 해결, 개발자에게 보고하는 법 | 서버를 설치·운영할 때 |
| [operations/env-guide.md](operations/env-guide.md) | 설정 작성 가이드 — 서버·PC `settings.yaml`(S7e1 — 옛 `pipeline.env`)의 자리·권한·키(옛 env 이름)·기본값, 판마다 바뀐 설정 | 설정 값을 채우거나 바꿀 때, 새 판 반입 때 |
| [operations/release-and-patch.md](operations/release-and-patch.md) | 릴리스·패치 — 이미지 기준판과 덧씌우기 만들기·적용·확인, selftest 반입 판정 | 새 이미지 판이나 덧씌우기를 만들거나 서버에 넣을 때 |
| [operations/patch-history.md](operations/patch-history.md) | 긴급 패치 이력(생성물 — 원본은 release-and-patch §9) | 서버에 무엇이 들어간 판인지 볼 때 |
| [operations/parsing_meta_mssql.sql](operations/parsing_meta_mssql.sql) | 회사 DB `AI.ParsingMeta` DDL — DBA가 1회 실행(코드는 표를 만들지 않음) | 첫 결과 게시(`publish --apply`) 전, DB 담당과 표를 맞출 때 |
| [requirements/run_docs_req.md](requirements/run_docs_req.md) | 문서별 flow 러너(`deploy/host/scripts/run_docs.py`) 요구사항 — 사용자 발화 기록 | flow 러너를 고치기 전에 |
| [architecture/run_docs_design.md](architecture/run_docs_design.md) | 문서별 flow 러너 설계·파라미터·변경 이력 | flow 러너 구조를 보거나 고칠 때 |
| [architecture/pipeline_stack.md](architecture/pipeline_stack.md) | 엔진 구성·원천 목록 판 표(`struct.stack_version`·`source_version` — S8b) — 서버 DB·PC 파일·바꾸기·되돌리기 명령·엔진 거부·사본 파일 + 옛 `pipeline_stack.json` 메모 칸(D-017) | 엔진 구성·원천 목록을 바꾸거나 판을 되돌릴 때 |
| [architecture/prompts.md](architecture/prompts.md) | AI 지시서 패키지 20개(`resources/prompts/` 18 — 10-29에 5개 삭제 + PC 전용 `triple_extract`·답변 점검 agent `rag_qa`(S10 — `valid_env/answer_test/`) — S11에 `research_check` 삭제) — 자리(`resources/prompts/`)·찾는 순서·패키지 구성·캐시 열쇠·패키지마다 무엇·입출력·호출부·모델 역할(옛 패키지 `README.md` 합침, S2) | 지시문·지시서를 고치거나 LLM·VLM 호출부를 볼 때 |

- 설정 작성 가이드(refactor_plan 4-1·6-1 — S7 D-015)는 [operations/env-guide.md](operations/env-guide.md)다(S7에 그 문서를 settings.yaml 기준으로 고침 — 새 문서 없음).
- 작업 보고서(`output/orca/`)는 git 밖이라 이 표에 넣지 않는다.
