# sbl_data_parsing — PRD

목표: 폐쇄망 회사 문서에서 출처 달린 근거를 찾는다 — 파싱 → 구조화 → 적재(pgvector) → 검색 MCP, 서버와 PC에서 같게.
행 = 묶음 하나(끝난 것 포함). 상태: todo · dev · done(그 밖에 partly done). ID는 그대로 두고 카테고리 파일이 자리를 정한다. 상세는 ID 링크.

## 지금 진행 중
- pl-13 적재가 지우지 않음 — dev, `feature/load-no-prune` 병합됨(#17) → 상태 정리.
- pl-22 파싱 phase 없애기 — dev, `feature/r2-phase` 병합됨 → 서버 확인(refactor.md C-65), VLM 동시 수 손잡이는 후속.
- pl-27 프로세스 종료 정리 — dev, `feature/exit-cleanup` 병합됨 → code_fp 모든 레이어 바뀜(다음 반입에서 재처리).
- pl-25 DB 스키마 명세 — dev, `docs/architecture/db_schema.md` 병합됨 → 사용자·DB 담당자 승인.
- do-04 문서 재구성 2부 — `feature/doc-cleanup-2` → PR(1부는 PR #21로 병합).

## ETL — 수집·퍼블리시·적재·DB (etl)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 원천과 가져오기 | done | 폴더·S3·RDB · 증분 · 스트리밍 · warm | [pl-01](prd/etl.md#pl-01) |
| EDW 고객 매핑을 파이프라인이 만듦 | todo | FileStorageMap 조인 · `file_meta` 대체 | [pl-29](prd/etl.md#pl-29) |
| 구조화 — 청크·메타·임베딩 | done | 청크 · 요약 · 사실 · 임베딩 | [pl-06](prd/etl.md#pl-06) |
| structure/load 계약이 새 묶음 거부 | todo | `DOC_KEYS` 고침(사람 검토) | [pl-15](prd/etl.md#pl-15) |
| `PIPE_EMBED=none`이면 `vector(0)` | todo | 차원 0 처리 | [pl-16](prd/etl.md#pl-16) |
| pgvector 적재 | done | Alembic 표 · 건너뛰기 · 색인 | [pl-07](prd/etl.md#pl-07) |
| 적재는 지우지 않음(`--prune` 없앰) | dev | prune 길 없앰 · 시험 | [pl-13](prd/etl.md#pl-13) |
| 배포 backfill이 `doc.clients`만 읽음 | done | backfill 고침 · 시험 | [pl-14](prd/etl.md#pl-14) |
| compose `index_a`/`index_b` 실패 | todo | 원인 · 고침 | [pl-19](prd/etl.md#pl-19) |
| 정형 DB와 문서 대장 | done | 마스터 · 연결 · 대장 | [pl-08](prd/etl.md#pl-08) |
| 마스터 CSV 활용 방안 설계 | todo | 후순위 · 사용자와 grill · 0.1.0 아님 | [pl-38](prd/etl.md#pl-38) |
| 문서 대장 upsert·게시 가드 | todo | PG 번역 · ParsingMeta 가드 | [pl-12](prd/etl.md#pl-12) |
| 파싱 결과 게시 | done | Object Storage · ParsingMeta | [pl-09](prd/etl.md#pl-09) |
| `full`은 늘 게시, 대상 필수 | todo | `--no-publish` 없앰 · 시작 거부 | [pl-26](prd/etl.md#pl-26) |
| 실행 관리(오케스트레이션) | done | CLI · entrypoint · flow 러너 · trigger | [pl-10](prd/etl.md#pl-10) |
| 중간 멈춤에도 종료 코드 0 | todo | `night` · `full` 종료 코드 | [pl-18](prd/etl.md#pl-18) |
| 증분만, 전체 재파싱은 전체 e2e | todo | 새 문서 = s3_key · 밤 배치 끔 | [pl-23](prd/etl.md#pl-23) |
| `run_docs` 순서: silver → 원본 삭제 → gold | todo | 순서 · `gold_status` · 임시 폴더 | [pl-24](prd/etl.md#pl-24) |
| 레인 정책 — 담당 먼저, 허용 레인만 | done | 전담·공유 워커 · `pick_lane` | [rn-01](prd/etl.md#rn-01) |
| 중간 대기열 상한·길이 기록 | done | `struct_backlog` · `queue_depth.jsonl` | [rn-02](prd/etl.md#rn-02) |
| MCP `parse_document`에 CPU 먼저 | todo | 지금 nice(같은 컨테이너) · 논의: 컨테이너 분리 | [rn-03](prd/etl.md#rn-03) |
| run_docs 작은 수정·레인 테스트 | done | 감시 루프 · 로그 · 흐름 테스트 · 0.1.0 | [rn-04](prd/etl.md#rn-04) |
| DB 스키마 명세 | dev | `db_schema.md` · 시험 · 승인 | [pl-25](prd/etl.md#pl-25) |
| 저장 구조 — silver OS uuid 폴더 · 메타 EDW · gold pgvector | todo | uuid5 폴더 · 최신 행만 · 로컬 상태 지움 · 0.1.0 | [pl-32](prd/etl.md#pl-32) |
| 분류 단계 — silver 뒤, gold 앞 | todo | SFDC·LAS 라벨 · sha256 묶음 전파 · `doc_class` | [pl-33](prd/etl.md#pl-33) |
| FAQ 원천 — 질의응답 엑셀 행 단위 | todo | 시트 = FAQ_group · 행 = 청크 · FileStorageMap FAQ · 0.1.0 | [pl-39](prd/etl.md#pl-39) |
| FAQ 다시 올리기 — 행 단위 비교 | todo | 같은 그룹·질문 · 최신 답만 · pl-13 FAQ 예외(등급 A) | [pl-41](prd/etl.md#pl-41) |
| 수동 갱신 명령 — 분류·시스템 메타 따로 | todo | LLM 갈래(NULL 기본) · 메타 갈래(전체) · UPDATE만 | [pl-40](prd/etl.md#pl-40) |
| 원천별 gold 표(나중) | todo | 원천 4벌 · `search` 원천 필수 | [pl-28](prd/etl.md#pl-28) |

## 파싱 실행 — 엔진·스택·represent (parse)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 준비 | done | 중복 · 회전 · DRM 감지 | [pl-02](prd/parse.md#pl-02) |
| 엔진 스택 파싱 | done | 형식별 엔진 · 격리 · 스택 판 | [pl-03](prd/parse.md#pl-03) |
| 파싱 phase 없애기 · OCR 엔진 끔 | dev | 병렬 엔진 · 제한 · 쪽 VLM · 서버 확인 | [pl-22](prd/parse.md#pl-22) |
| ocr_vlm·vlm.model_alt 삭제 | done | 0.1.0 · 엔진 핑거프린트 바뀜(등급 A) | [pl-31](prd/parse.md#pl-31) |
| 파싱 p1 묶음 — 재판독(P2·P3)·scan_dedup·렌더 OCR 신호 | done | 0.1.0 · p1 바뀜(등급 A) | [pl-34](prd/parse.md#pl-34) |
| 핑거프린트 영향 없는 잔재 지우기 | done | parse_parallel · AUTO_REPARSE_CHANGED · figures_resume(pl-32) · phase_report 남김 | [pl-35](prd/parse.md#pl-35) |
| 메일 첨부 파싱 | done | 재귀 · 상한 · 인용 단락화 | [pl-36](prd/parse.md#pl-36) |
| 그림 근처 맥락 기록 | done | 캡션 · 본문 언급 · 값 확인 | [pl-37](prd/parse.md#pl-37) |
| 엔진 스택 사본 파일 검토 | done | 대체됨 → pl-32 | [pl-20](prd/parse.md#pl-20) |
| 파싱 단계를 `transform/parse/`로 | todo | 옮기기 · 이름 바꾸기 · code_fp | [pl-17](prd/parse.md#pl-17) |
| represent — 고르고 고치기 | done | 대표 · 합치기 · 다시 읽기 · 표 | [pl-04](prd/parse.md#pl-04) |
| 그림 | done | VLM 설명 · 차트 값 · 도식 | [pl-05](prd/parse.md#pl-05) |

## 검색 MCP (mcp)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| `search` 도구 | done | 세 방식 · 혼합 찾기 · 근거 출력 | [mc-01](prd/mcp.md#mc-01) |
| 질문 넓히기 | done | 용어집 · 고객별 나누기 · 질문 유형 | [mc-02](prd/mcp.md#mc-02) |
| 고객 범위·판·중복 | todo | 고객 범위 · 숨김 · 최신 판 | [mc-05](prd/mcp.md#mc-05) |
| 집계 답 | done | 규칙 집계 · 통화 · LLM 라우터 | [mc-04](prd/mcp.md#mc-04) |
| 집계 길이 지운 칸을 고름 | done | `aggregate.pg()` 지움(mc-12와 함께) | [mc-11](prd/mcp.md#mc-11) |
| 사실 집계가 지운 `doc_fact` 질의 | done | PG 집계 길 지움 · 숫자는 `query_edw` | [mc-12](prd/mcp.md#mc-12) |
| retriever가 지운 칸을 읽음 | done | 묶음 `doc_key` · PG 열 | [mc-10](prd/mcp.md#mc-10) |
| 질의 기록은 jsonl만 | done | PG `qa_log` INSERT 지움 | [mc-13](prd/mcp.md#mc-13) |
| 숨김 문서가 검색에서 안 빠짐 | todo | pl-25 대기 · `s3_key`로 비교 | [mc-14](prd/mcp.md#mc-14) |
| 근거의 `rep_uri`가 늘 빔 | todo | pl-25 대기 · `source_key` 조회 | [mc-15](prd/mcp.md#mc-15) |
| `search` 운영 계약 구현 | todo | question 필수 · 필터 11종 · 출력 축소(등급 A) | [mc-16](prd/mcp.md#mc-16) |
| 원문 전송 도구 2개 | todo | `list_doc_fulltext` · `get_doc_fulltext`(등급 A) | [mc-17](prd/mcp.md#mc-17) |
| `query_edw` 도구 | done | SELECT만 · 허용 목록 · 상한 | [mc-06](prd/mcp.md#mc-06) |
| `edw_meta` 도구 | done | 스키마 → 표 → 칸 | [mc-07](prd/mcp.md#mc-07) |
| `parse_document` 도구 | done | 파싱 서비스 전달 · `job_id` | [mc-08](prd/mcp.md#mc-08) |
| 서버 실행과 안전 | done | 토큰 · health · 동시 수 · 기록 | [mc-09](prd/mcp.md#mc-09) |

## 설정·운영 (settings)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| RUN_ENV 셋 · LLM_FAKE는 local만 | done | `stage` 거부 · 시작 관문 | [op-02](prd/settings.md#op-02) |
| 모델 호출·비용·외부 전송 가드 | done | 역할 · 외부 거부 · 예산 | [pl-11](prd/settings.md#pl-11) |
| EDW 접속 하나·계정 둘 | done | `common.connections.rdb` · 읽기·쓰기 · sqlite 대역 | [op-03](prd/settings.md#op-03) |
| 프로세스 종료 정리 | dev | 덮기 파일 지움 · 자식 회수 · SIGTERM | [pl-27](prd/settings.md#pl-27) |
| JSON Lines 사건 기록 | todo | 포매터 · 수준 설정 · 가림 | [op-01](prd/settings.md#op-01) |
| settings.yaml 하나 · sample에 모든 키·기본값 | done | 주석 해제 · 카테고리 묶음 · 생성기 · 0.1.0 | [op-05](prd/settings.md#op-05) |
| 미룬 설정 지우기 | done | `korean_font` · `eval_sets_dir`(fp-batch) | [pl-21](prd/settings.md#pl-21) |
| 안 읽는 env 이름 4개 지우기 | done | run_docs의 안 읽는 env 4개(fp-batch) | [pl-30](prd/settings.md#pl-30) |

## 테스트·평가 (test)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 시험 층 | done | server · general · 알려진 실패 | [e2-02](prd/test.md#e2-02) |
| 이미지 빌드·반입 관문 | done | build_ship · `[판정]` · 오버레이 | [e2-08](prd/test.md#e2-08) |
| 반입 시험이 이미지 안에만 | todo | 오버레이로 시험 갱신(C-53) | [e2-14](prd/test.md#e2-14) |
| PC 일반 시험 알려진 실패 | partly done | 공용 PG 3개 고침 · 남은 4개 | [e2-11](prd/test.md#e2-11) |
| 에이전트 시험 패키지 경로 | todo | `resolve_agent_dir`(code_fp) | [e2-15](prd/test.md#e2-15) |
| PC 스모크 | done | 파싱 → 검색 2~3건 | [e2-01](prd/test.md#e2-01) |
| PC Docker 스모크가 retriever에서 멈춤 | todo | mc-10 뒤 다시 돌림 | [e2-13](prd/test.md#e2-13) |
| PwC `valid_env` 시험 자료 | done | 옛 자료 삭제 · EDW 대역 | [e2-09](prd/test.md#e2-09) |
| 파싱 품질 평가 | done | CER · 재현율 · 스택 보고서 | [e2-03](prd/test.md#e2-03) |
| 검색 평가 | done | hit@k · 지연 · 보고서 | [e2-04](prd/test.md#e2-04) |
| 답변 점검 | done | `rag_qa` · 인용 점검 | [e2-05](prd/test.md#e2-05) |
| EDW 값 답변 인용 실패 | done | 그대로 둠(결정) | [e2-12](prd/test.md#e2-12) |
| answer_gen 인용 버그 | todo | L-2 · P-2 · CR-2~7 | [e2-19](prd/test.md#e2-19) |
| 분류 수용 보고서 | todo | dev 정답 샘플 대조 · 일치율 · 혼동표 | [e2-20](prd/test.md#e2-20) |
| 스택·모델 비교 | done | 행렬 · 예상 비용 | [e2-06](prd/test.md#e2-06) |
| 검색 점검 페이지 | done | 로컬 페이지 · 포트 | [e2-07](prd/test.md#e2-07) |
| 검색 페이지 고정 글 | todo | 실제 개수 표시 | [e2-16](prd/test.md#e2-16) |
| PC 평가 도구 줄이기 | todo | 둘만 남김 · 설정 지움 | [e2-10](prd/test.md#e2-10) |
| 안 쓰는 함수 지우기 | done | 시험만 부르는 것도(drop-unused) | [e2-17](prd/test.md#e2-17) |
| 요건 없는 코드 지우기 | done | 지움 · 남김 목록(drop-unused) | [e2-18](prd/test.md#e2-18) |

## 문서·릴리스 (doc)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 문서 재구성 · 한국어 | dev | 1부 PRD 카테고리 · 2부 CLAUDE.md | [do-04](prd/doc.md#do-04) |
| `docs/index.md` 용어집 | done | 용어 대응 옮김 · 링크 한 줄 | [do-02](prd/doc.md#do-02) |
| `refactor.md`를 병합과 맞춤 | done | 낡은 줄 · PRD 링크 · 검토자 | [do-03](prd/doc.md#do-03) |
| `refactor.md`를 `docs/refactoring/`으로 | todo | 옮기기 · 링크 | [do-01](prd/doc.md#do-01) |
| 첫 릴리스 태그 `v0.1.0` | todo | 태그 · 릴리스 노트 | [op-04](prd/doc.md#op-04) |
| 실행 이미지(코드 없음) · 코드 폴더 마운트 | done | 개발 서버 · 의존성 지문 · 코드 커밋 표시 | [op-06](prd/doc.md#op-06) |
| 개발 → 운영 굽기(실행 이미지 + 시험한 코드) | done | `Dockerfile.bake` · `bake.sh` · 반입 판정 · 저장·분할 | [op-07](prd/doc.md#op-07) |
