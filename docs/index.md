# 문서 지도

이 저장소의 사람이 읽는 문서를 한 표에 모았다. 문서는 `docs/` 아래 유형별 폴더에 둔다(refactor_plan 4-1 `docs/`). 문서를 더하거나 옮기면 이 표와 [CLAUDE.md](../CLAUDE.md) §8을 같은 커밋에서 고친다.

| 문서 | 무엇 | 언제 읽나 |
|---|---|---|
| [README.md](../README.md) | 프로젝트 소개 — 처리 흐름·실행 단위(모듈 4개·완료 표시)·이미지와 버전·폴더 구조·설정(settings.yaml)·PC 실행 단계(①~⑥)·서버 배포와 실행 방법 비교(trigger 하나씩·all·night·run_docs)(상세는 아래 운영 문서로 연결 — 10-29) | 처음 볼 때, 실행 방법을 찾을 때 |
| [PRD.md](PRD.md) · [prd/etl.md](prd/etl.md) · [prd/parse.md](prd/parse.md) · [prd/mcp.md](prd/mcp.md) · [prd/settings.md](prd/settings.md) · [prd/test.md](prd/test.md) · [prd/doc.md](prd/doc.md) | 기능 요건 — 카테고리 6개: ETL(수집·게시·적재·DB·서버 러너 레인·대기열), 파싱 실행(엔진·스택·represent), 검색 MCP, 설정·운영(settings.yaml·RUN_ENV·계정·로그), 테스트·평가, 문서·릴리스. ID(`mc`·`pl`·`e2`·`rn`·`op`·`do`)는 그대로이고 항목마다 한글 이름. PRD.md는 카테고리별 묶음 표(끝난 것 포함)와 지금 진행 중. 카테고리 파일 끝에 요건과 다른 코드·요건 없는 코드·기본 꺼짐 기능·10-29 삭제 목록(옛 gaps.md, 10-30) | 기능을 고치거나 더하기 전에, 할 일을 고를 때 |
| [CLAUDE.md](../CLAUDE.md) | 작업 규칙 — 지문·계약·운영 가드, 경계·이름, 배포 환경 규칙, 로컬 하네스·점검 명령 | 작업을 시작하기 전에 늘 |
| [refactoring/refactor.md](refactoring/refactor.md) | 서버·사람이 확인해야 할 사항(C-xx) — 저장소 안에서 끝낼 수 없는 확인·협의 · 머리의 **"최종 — 사람이 할 일"**(사람 할 일의 정본 — 검토 등급 A·반입 전·때·뒤·다음 판, 누가·언제·C) | 단계를 끝낼 때(새 확인 사항 덧붙임), 반입 준비·반입 때 |
| [operations/server-guide.md](operations/server-guide.md) | 서버 가이드 — 이미지 역할, 설치·첫 실행, 일상 실행, 결과 확인, 검색 MCP·EDW 질의 도구, 회사 맞춤, 문제 해결, 개발자에게 보고하는 법 | 서버를 설치·운영할 때 |
| [operations/env-guide.md](operations/env-guide.md) | 설정 작성 가이드 — 서버·PC `settings.yaml`(S7e1 — 옛 `pipeline.env`)의 자리·권한·키(옛 env 이름)·기본값, 판마다 바뀐 설정 | 설정 값을 채우거나 바꿀 때, 새 판 반입 때 |
| [operations/release-and-patch.md](operations/release-and-patch.md) | 릴리스·패치 — 이미지 기준판과 덧씌우기 만들기·적용·확인, selftest 반입 판정 | 새 이미지 판이나 덧씌우기를 만들거나 서버에 넣을 때 |
| [history/refactor_c_items.md](history/refactor_c_items.md) | 끝난·옛 확인 항목 이력(refactor.md에서 10-30 옮김 — do-04): C-05·06·13·14·15·18·20·22~26·28·30·35·38·40·57·63, C-41 합성 정답 부분, PRD로 옮긴 C-31·32·33·50·53의 옛 글 | 옛 확인 항목의 결정·경위를 찾을 때 |
| [operations/parsing_meta_mssql.sql](operations/parsing_meta_mssql.sql) | 회사 DB `AI.ParsingMeta` DDL — DBA가 1회 실행(코드는 표를 만들지 않음) | 첫 결과 게시(`publish --apply`) 전, DB 담당과 표를 맞출 때 |
| [history/](history/) | 지난 기록(do-04, 10-30) — [refactor_plan.md](history/refactor_plan.md)(리팩토링 가이드·결정 장부 D·미정 P·T·이동표 9-1·부록 D — `docs/refactoring/refactor_plan.md`는 안내만 남김) · [refactor_c_items.md](history/refactor_c_items.md)(닫은 C 항목) · [run_docs_req.md](history/run_docs_req.md)(flow 러너 사용자 발화 기록) · [run_docs_history.md](history/run_docs_history.md)(러너 버그·속도 이력) · [patch-history.md](history/patch-history.md)(긴급 패치 이력) · [release_history.md](history/release_history.md)(릴리스 §8–9) · 설정·서버 가이드에서 옮긴 이력([env_guide_history.md](history/env_guide_history.md)·[server_guide_history.md](history/server_guide_history.md)) | 옛 결정·이력을 찾을 때 |
| [architecture/run_docs_design.md](architecture/run_docs_design.md) | 문서별 flow 러너 설계·파라미터·변경 이력 | flow 러너 구조를 보거나 고칠 때 |
| [architecture/db_schema.md](architecture/db_schema.md) | DB 스키마 명세(pl-25 — 설계안, 사용자·DB 담당자 승인 전): gold(pgvector 검색)·struct·EDW(`AI.FileStorageMap`·`AI.ParsingMeta`) 표마다 칸·타입·뜻·쓰는 코드·읽는 코드·유지/삭제/새로, 마스터 CSV 파일(`resources/vocab/glossary/` — 사용자 10-30, 마스터 PG 없음)의 머리글 + DB 담당자·사용자 확인 목록. 시험 `tests/server/common/test_db_schema.py`가 지금 칸을 판·SQL과 대조 | DB 표·칸을 바꾸거나 DB 담당자와 협의할 때 |
| [architecture/pipeline_stack.md](architecture/pipeline_stack.md) | 엔진 구성·원천 목록 판 표(`struct.stack_version`·`source_version` — S8b) — 서버 DB·PC 파일·바꾸기·되돌리기 명령·엔진 거부·사본 파일 + 옛 `pipeline_stack.json` 메모 칸(D-017) | 엔진 구성·원천 목록을 바꾸거나 판을 되돌릴 때 |
| [architecture/prompts.md](architecture/prompts.md) | AI 지시서 패키지 20개(`resources/prompts/` 18 — 10-29에 5개 삭제 + PC 전용 `triple_extract`·답변 점검 agent `rag_qa`(S10 — `valid_env/answer_test/`) — S11에 `research_check` 삭제) — 자리(`resources/prompts/`)·찾는 순서·패키지 구성·캐시 열쇠·패키지마다 무엇·입출력·호출부·모델 역할(옛 패키지 `README.md` 합침, S2) | 지시문·지시서를 고치거나 LLM·VLM 호출부를 볼 때 |

- 설정 작성 가이드(refactor_plan 4-1·6-1 — S7 D-015)는 [operations/env-guide.md](operations/env-guide.md)다(S7에 그 문서를 settings.yaml 기준으로 고침 — 새 문서 없음).
- 작업 보고서(`output/orca/`)는 git 밖이라 이 표에 넣지 않는다.

## Glossary

**약어**
| 말 | 뜻 |
|---|---|
| PRD | 기능 요건 문서 — [PRD.md](PRD.md)와 `prd/<카테고리>.md` |
| L4 · L5 | PRD 표의 묶음(L4)과 그 안의 단계(L5) — agent-ops 작업 레벨 |
| ID 접두 | `mc` 검색 MCP · `pl` 데이터 파이프라인 · `e2` e2e·시험·평가 · `rn` 서버 flow 러너 · `op` 운영(설정·계정·로그·릴리스) · `do` 문서 — 파일 자리는 카테고리가 정함 |
| C-xx · D-xxx · P-xx | `refactor.md`의 서버·사람 확인 사항 · refactor_plan 7절 결정 · 8절 미정 |
| EDW | 회사 DB(SQL Server) — `AI.FileStorageMap`(원본 목록)·`AI.ParsingMeta`(게시 기록)·원천 표 |
| OS | Object Storage — 원본과 파싱 결과(silver) 파일 |
| silver · gold | 게시한 파싱 결과(OS + ParsingMeta) · 검색용 적재 결과(pgvector `doc`·`chunk`…) |
| MCP | 검색 서버(Model Context Protocol) — 도구 `search`·`query_edw`·`parse_document`·`edw_meta` |
| VLM · OCR | 이미지를 읽는 언어 모델 · 글자 인식 엔진 |
| BM25 · RRF · HNSW | 낱말 점수 검색 · 순위 합치기 · pgvector 근사 최근접 색인 |
| code_fp · FINGERPRINT | 레이어 코드 핑거프린트(a·p0·p1·r·s) · 핸드오프 핑거프린트 — 바뀌면 서버 재처리(CLAUDE.md §4) |
| RUN_ENV | 실행 환경 `local`(PC)·`dev`·`prd` |
| 등급 A | 사람 검토가 필요한 변경(핑거프린트·계약·DB·운영 접속·비밀값) |

**프로젝트 용어**
| 말 | 뜻 |
|---|---|
| 묶음(번들) | 구조화 결과 폴더(`docs.jsonl`·청크·벡터) — 로컬 검색과 적재의 입력 |
| 대역 | PC에서 외부 시스템을 흉내 내는 것(EDW sqlite `valid_env/edw/edw.sqlite`, PG 대역 SQLite) |
| 스택 | 파일 형식마다 도는 엔진 목록(`struct.stack_version`) |
| represent | 엔진 결과 중 대표를 고르고 고치는 단계 |
| flow 러너 | 서버 호스트의 문서별 실행기 `run_docs.py` — 레인 light·medium·vlm, warm(미리 받기) |
| selftest | 이미지 안 반입 시험(`tests/server/`) — `[판정]` 줄로 판정 |
| 오버레이 패치 | 코드 폴더만 바꿔 서버에 넣는 패치(이미지는 그대로) |

**옛 용어 대응**(옛 문서와 코드 주석에는 리팩토링 중에 쓰던 말이 남아 있다)
시험=테스트 · 반입=(폐쇄망) 배포 · 칸=항목/컬럼 · 판=버전 · 지문=핑거프린트 · 열쇠=키 · 층=레이어 · 묶음=번들 · 대장=레지스트리 · 인계=핸드오프 · 덧씌우기=오버레이 패치 · 덮기 파일=오버레이 설정 파일 · 게시=퍼블리시 · 지시서/지시문=프롬프트.

**옛 CLAUDE.md 절 번호**(코드 주석이나 기록 문서의 옛 참조를 찾을 때 — CLAUDE.md에서 옮김, 10-30)
옛 1절(저장소·이름 대응) → README·refactor_plan 9절 · 옛 2절(문서) → §8 · 옛 3절(지켜야 할 규칙) → §2(배포 환경)·§3(설정)·§4(핑거프린트·계약·운영 가드) · 옛 4절(작업 절차) → §5·§9 · 옛 5절(OpenRouter) → §7 · 옛 6절(로컬 하네스) → §6 · 옛 7절(알려진 문제) → §10 · 옛 8절(사용자 결정 대기) → refactor.md "최종" ⑤·refactor_plan 8절. 코드 주석 속 옛 번호는 일부러 고치지 않았다(공용·레이어 파일은 고치면 code_fp가 바뀌고, 그 밖의 파일은 주석 한 줄 때문에 옛 린트 경고까지 정리해야 해서 — §5-2).
옛 §10 알려진 문제(10-20 축소 스키마 일부 반영 등)는 `mc-10`·`mc-11`·`pl-12`~`pl-16`·`e2-13`·`e2-16`으로 옮겼다.
