# sbl_data_parsing — PRD

목표: 폐쇄망 회사 문서에서 출처 달린 근거를 찾는다 — 파싱 → 구조화 → 적재(pgvector) → 검색 MCP, 서버와 PC에서 같게.
행 = 묶음 하나(끝난 것 포함). 상태: todo · dev · done(그 밖에 partly done) · dropped(요건에서 뺌 — 행은 남김, 사용자 10-31 범위 축소). ID는 그대로 두고 카테고리 파일이 자리를 정한다(do-04 3부 11-01 — 수집·변환·적재·검색·운영·테스트·문서, 2만 자 넘는 카테고리는 `<분류>-<하위>.md`). 상세는 ID 링크.

## 지금 진행 중
- pl-25 DB 스키마 명세 — dev: `docs/architecture/db_schema.md` 병합됨 → 사용자·DB 담당자 승인 대기(`ParsingMeta.stack_version` 칸 — 판 표가 없어져 무엇을 둘지 결정 대기, 사용자).
- 0.2.0 묶음(todo — 순서는 허브가 정함): 저장 구조 [pl-32](prd/load.md#pl-32) · 원천별 gold 스키마 [pl-28](prd/load-schema.md#pl-28) · run_docs 순서 [pl-24](prd/ops.md#pl-24) · 게시 필수 [pl-26](prd/load.md#pl-26) · 분류 [pl-33](prd/transform.md#pl-33) · FAQ [pl-39](prd/extract.md#pl-39)·[pl-41](prd/load.md#pl-41) · 지문 배치 [pl-46](prd/transform-cleanup.md#pl-46)·[pl-47](prd/transform-cleanup.md#pl-47) · 확장자 2차 [pl-45](prd/transform.md#pl-45) · `search` 계약 [mc-16](prd/mcp.md#mc-16) · 원문 도구 [mc-17](prd/mcp.md#mc-17).
- 검색 — PG만, 실행 중 묶음 없음 [mc-19](prd/mcp.md#mc-19)(todo, 자기 PR + 평가).
- do-04 문서 재구성 — 3부 카테고리 재편 `feature/do04-reorg`(이 PR).

## 수집 (extract)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 원천과 가져오기 | done | 폴더·`rdb:csv`(11-01 — S3·RDB 직접 지움) · 증분 · warm | [pl-01](prd/extract.md#pl-01) |
| EDW 고객 매핑을 파이프라인이 만듦 | todo | FileStorageMap 조인 · `file_meta` 대체 | [pl-29](prd/extract.md#pl-29) |
| 준비 | done | 중복 · 회전 · DRM 감지 | [pl-02](prd/extract.md#pl-02) |
| FAQ 원천 — 질의응답 엑셀 행 단위 | todo | 시트 = FAQ_group · 행 = 청크 · FileStorageMap FAQ · 0.2.0 | [pl-39](prd/extract.md#pl-39) |

## 변환 — 파싱·represent·그림·구조화 (transform)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 엔진 스택 파싱 | done | 형식별 엔진 · 격리 · stack 하나(`all` 길 지움 — PR #80) | [pl-03](prd/transform.md#pl-03) |
| 파싱 phase 없애기 · OCR 엔진 끔 | done | 병렬 엔진 · 제한 · 쪽 VLM · 서버 확인 | [pl-22](prd/transform.md#pl-22) |
| VLM 동시 수 손잡이 | done | `tuning` 키 하나로 닫음 | [pl-43](prd/transform.md#pl-43) |
| 지원 확장자 더하기 — .jpeg·.tif·.tiff·.bmp·.mhtml | done | 스택 표 · 확장자마다 시험(임시 샘플) · .hwpx 시험 | [pl-42](prd/transform.md#pl-42) |
| 지원 확장자 2차 — .hwp·.docm·.rtf·.csv·오픈문서 등 | todo | registry 추가 확장자 표(엔진 지문 그대로) · 스택 표 · ALLOWED_EXTS · 시험 · 0.2.0(등급 A) | [pl-45](prd/transform.md#pl-45) |
| 엔진 스택 사본 파일 검토 | done | 대체됨 → pl-32 | [pl-20](prd/transform.md#pl-20) |
| 파싱 단계를 `transform/parse/`로 | dropped | 옮기기 · 이름 바꾸기 · code_fp | [pl-17](prd/transform.md#pl-17) |
| represent — 고르고 고치기 | done | 대표 · 합치기 · 다시 읽기 · 표 | [pl-04](prd/transform.md#pl-04) |
| 메일 첨부 파싱 | done | 재귀 · 상한 · 인용 단락화 | [pl-36](prd/transform.md#pl-36) |
| 그림 근처 맥락 기록 | done | 캡션 · 본문 언급 · 값 확인 | [pl-37](prd/transform.md#pl-37) |
| 그림 | done | VLM 설명 · 차트 값 · 도식 | [pl-05](prd/transform.md#pl-05) |
| 구조화 — 청크·메타·임베딩 | done | 청크 · 요약 · 임베딩 · 그래프·개념·그림 행·사실 지움(사용자 10-31, 11-01) | [pl-06](prd/transform.md#pl-06) |
| structure/load 계약이 새 묶음 거부 | dropped | `DOC_KEYS` 고침(사람 검토) | [pl-15](prd/transform.md#pl-15) |
| 분류 단계 — silver 뒤, gold 앞 | todo | SFDC·LAS 라벨 · sha256 묶음 전파 · `doc_class` | [pl-33](prd/transform.md#pl-33) |
| ocr_vlm·vlm.model_alt 삭제 | done | 0.1.0 · 엔진 핑거프린트 바뀜(등급 A) | [pl-31](prd/transform-cleanup.md#pl-31) |
| 파싱 p1 묶음 — 재판독(P2·P3)·scan_dedup·렌더 OCR 신호 | done | 0.1.0 · p1 바뀜(등급 A) | [pl-34](prd/transform-cleanup.md#pl-34) |
| 핑거프린트 영향 없는 잔재 지우기 | done | parse_parallel · AUTO_REPARSE_CHANGED · figures_resume(pl-32) · phase_report 남김 | [pl-35](prd/transform-cleanup.md#pl-35) |
| 0.2.0 지문 배치 정리 | todo | 안 쓰는 엔진 5개 · 묶음 계약 · OCR 대체 길 · 이미지 행 qwen_vlm(등급 A) | [pl-46](prd/transform-cleanup.md#pl-46) |
| 엔진 지문(p0) 범위 확인 | todo | 다른 이름 폴더 엔진(html_stdlib·msg_extract·rapidocr_ko·office·pptx) · 0.2.0(등급 A) | [pl-47](prd/transform-cleanup.md#pl-47) |

## 적재 — pgvector·게시·저장 구조·DB 스키마 (load)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| pgvector 적재 | done | Alembic 표 · 건너뛰기 · 색인 | [pl-07](prd/load.md#pl-07) |
| 적재는 지우지 않음(`--prune` 없앰) | done | prune 길 없앰 · 시험 | [pl-13](prd/load.md#pl-13) |
| 배포 backfill이 `doc.clients`만 읽음 | done | backfill 고침 · 시험 | [pl-14](prd/load.md#pl-14) |
| `PIPE_EMBED=none`이면 `vector(0)` | todo | 차원 0 처리 | [pl-16](prd/load.md#pl-16) |
| compose `index_a`/`index_b` 실패 | done | 11-01 이름 있는 색인째 지움(mc-16) | [pl-19](prd/load.md#pl-19) |
| 파싱 결과 게시 | done | Object Storage · ParsingMeta | [pl-09](prd/load.md#pl-09) |
| `full`은 늘 게시, 대상 필수 | todo | `--no-publish` 없앰 · 시작 거부 | [pl-26](prd/load.md#pl-26) |
| FAQ 다시 올리기 — 행 단위 비교 | todo | 같은 그룹·질문 · 최신 답만 · pl-13 FAQ 예외(등급 A) | [pl-41](prd/load.md#pl-41) |
| 수동 갱신 명령 — 분류·시스템 메타 따로 | dropped | LLM 갈래(NULL 기본) · 메타 갈래(전체) · UPDATE만 | [pl-40](prd/load.md#pl-40) |
| 정형 DB와 문서 대장 | done | struct 스키마를 코드에서 모두 없앰 — 파일만(11-01) | [pl-08](prd/load.md#pl-08) |
| 문서 대장 upsert·게시 가드 | done | **지움**(사용자 10-31) · deleted 길 없앰·서버 대체 금지 ✓ · PG 번역 · ParsingMeta 가드 | [pl-12](prd/load.md#pl-12) |
| 마스터 CSV 활용 방안 설계 | todo | 고객 별칭 CSV 0.2.0 · 나머지 후순위 · grill | [pl-38](prd/load.md#pl-38) |
| 저장 구조 — silver OS uuid 폴더 · 메타 EDW · gold pgvector | todo | uuid5 폴더 · 최신 행만 · 로컬 상태 지움 · 0.2.0 | [pl-32](prd/load.md#pl-32) |
| DB 스키마 명세 | dev | `db_schema.md` · 시험 · 승인 | [pl-25](prd/load-schema.md#pl-25) |
| 원천 시스템별 gold 스키마(0.2.0) | todo | 시스템별 PG 스키마 · 메타는 `doc`에만 · `source_system` 필수 하나 · ParsingMeta는 파싱 정보만 | [pl-28](prd/load-schema.md#pl-28) |

## 검색 MCP (mcp)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| `search` 도구 | done | **일부 지움**(PC 묶음 검색·PG 대역 — 사용자 10-31) · 세 방식 · 혼합 찾기 · 근거 출력 | [mc-01](prd/mcp.md#mc-01) |
| 질문 넓히기 | done | 용어집 · 고객별 나누기 · 질문 유형 | [mc-02](prd/mcp.md#mc-02) |
| 고객 범위·판·중복 | todo | 고객 범위 · 숨김 · 최신 판 | [mc-05](prd/mcp.md#mc-05) |
| 집계 답 | done | **지움**(사용자 10-31) · 규칙 집계 · 통화 · LLM 라우터 | [mc-04](prd/mcp.md#mc-04) |
| 집계 길이 지운 칸을 고름 | done | `aggregate.pg()` 지움(mc-12와 함께) | [mc-11](prd/mcp.md#mc-11) |
| 사실 집계가 지운 `doc_fact` 질의 | done | PG 집계 길 지움 · 숫자는 `query_edw` | [mc-12](prd/mcp.md#mc-12) |
| retriever가 지운 칸을 읽음 | done | 묶음 `doc_key` · PG 열 | [mc-10](prd/mcp.md#mc-10) |
| 질의 기록은 jsonl만 | done | PG `qa_log` INSERT 지움 | [mc-13](prd/mcp.md#mc-13) |
| 숨김 문서가 검색에서 안 빠짐 | dropped | pl-25 대기 · `s3_key`로 비교 | [mc-14](prd/mcp.md#mc-14) |
| 근거의 `rep_uri`가 늘 빔 | done | 원문 도구가 부를 때 ParsingMeta에서 읽음(C8, 사용자 11-01) | [mc-15](prd/mcp.md#mc-15) |
| `search` 운영 계약 구현 | done | question 필수 · 거르기 13칸 · 5칸·근거 12칸 · 판 0002(등급 A) | [mc-16](prd/mcp.md#mc-16) |
| 원문 전송 도구 2개 | done | `list_doc_fulltext` · `get_doc_fulltext` · gold 거르기 + ParsingMeta 읽기 + sfid 서명(등급 A) | [mc-17](prd/mcp.md#mc-17) |
| 검색 — PG만, 실행 중 묶음 없음 | todo | 문서 메타·임베딩 정보 PG에서 · 검색 동작 바뀜(자기 PR + 평가) | [mc-19](prd/mcp.md#mc-19) |
| `parse_document` 스캔 PDF 다시 지원 | todo | 지금은 건너뜀 + 안내 · 엔진·응답 시간 정하기(등급 A) | [mc-18](prd/mcp.md#mc-18) |
| `query_edw` 도구 | done | SELECT만 · 허용 목록 · 상한 | [mc-06](prd/mcp.md#mc-06) |
| `edw_meta` 도구 | done | 스키마 → 표 → 칸 | [mc-07](prd/mcp.md#mc-07) |
| `parse_document` 도구 | done | 파싱 서비스 전달 · `job_id` | [mc-08](prd/mcp.md#mc-08) |
| 서버 실행과 안전 | done | 토큰 · health · 동시 수 · 기록 | [mc-09](prd/mcp.md#mc-09) |

## 운영 — 실행 관리·러너·설정 (ops)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 실행 관리(오케스트레이션) | done | CLI · entrypoint · flow 러너 · trigger 서버 지움(사용자 10-31, 11-01) | [pl-10](prd/ops.md#pl-10) |
| 증분만, 전체 재파싱은 전체 e2e | todo | 새 문서 = s3_key · 밤 배치 끔 | [pl-23](prd/ops.md#pl-23) |
| `run_docs` 순서: silver → 원본 삭제 → gold | todo | 순서 · `gold_status` · 임시 폴더 | [pl-24](prd/ops.md#pl-24) |
| 중간 멈춤에도 종료 코드 0 | todo | `night` · `full` 종료 코드 | [pl-18](prd/ops.md#pl-18) |
| 레인 정책 — 담당 먼저, 허용 레인만 | done | 전담·공유 워커 · `pick_lane` | [rn-01](prd/ops.md#rn-01) |
| 중간 대기열 상한·길이 기록 | done | `struct_backlog` · `queue_depth.jsonl` | [rn-02](prd/ops.md#rn-02) |
| MCP `parse_document`에 CPU 먼저 | todo | 지금 nice(같은 컨테이너) · 논의: 컨테이너 분리 | [rn-03](prd/ops.md#rn-03) |
| run_docs 작은 수정·레인 테스트 | done | 감시 루프 · 로그 · 흐름 테스트 · 0.1.0 | [rn-04](prd/ops.md#rn-04) |
| 프로세스 종료 정리 | done | 덮기 파일 지움 · 자식 회수 · SIGTERM | [pl-27](prd/ops.md#pl-27) |
| 강제 종료로 남은 임시 설정 파일 정리 | dropped | 다음 시작 때 주인 없는 파일 지움 | [pl-44](prd/ops.md#pl-44) |
| EDW 접속 하나·계정 둘 | done | `common.connections.rdb` · 읽기·쓰기 · sqlite 대역 | [op-03](prd/ops.md#op-03) |
| 모델 호출·비용·외부 전송 가드 | done | 역할 · 외부 거부 · 예산 | [pl-11](prd/ops.md#pl-11) |
| JSON Lines 사건 기록 | dropped | 포매터 · 수준 설정 · 가림 | [op-01](prd/ops.md#op-01) |
| RUN_ENV 셋 · LLM_FAKE는 local만 | done | `stage` 거부 · 시작 관문 | [op-02](prd/ops-ops-settings.md#op-02) |
| settings.yaml 하나 · sample에 모든 키·기본값 | done | 주석 해제 · 카테고리 묶음 · 생성기 · 0.1.0 · op-08로 대체 | [op-05](prd/ops-ops-settings.md#op-05) |
| 설정 구조 재편 — 필수 묶음 + 역할별 파라미터 | done | `required` 맨 위 · 7개 역할 절 · 죽은 칸 삭제 · 0.2.0 | [op-08](prd/ops-ops-settings.md#op-08) |
| 하드코딩 0 | done | 서버 경로·PG·MCP 주소 한 곳 · 지문 파일 env 읽기 · PG 자동 찾기 없앰 · 0.2.0 | [op-09](prd/ops-ops-settings.md#op-09) |
| 미룬 설정 지우기 | done | `korean_font` · `eval_sets_dir`(fp-batch) | [pl-21](prd/ops-ops-settings.md#pl-21) |
| 안 읽는 env 이름 4개 지우기 | done | run_docs의 안 읽는 env 4개(fp-batch) | [pl-30](prd/ops-ops-settings.md#pl-30) |

## 테스트·평가 (test)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|

## 문서·릴리스 (doc)
| 묶음 (L4) | 상태 | 단계 (L5) | ID |
|---|---|---|---|
| 문서 재구성 · 한국어 | dev | 1부 PRD 카테고리 · 2부 CLAUDE.md | [do-04](prd/doc.md#do-04) |
| `docs/INDEX.md` 용어집 | done | 용어 대응 옮김 · 링크 한 줄 | [do-02](prd/doc.md#do-02) |
| `refactor.md`를 병합과 맞춤 | done | 낡은 줄 · PRD 링크 · 검토자 | [do-03](prd/doc.md#do-03) |
| `refactor.md`를 `docs/refactoring/`으로 | done | 옮기기 · 링크 | [do-01](prd/doc.md#do-01) |
| 첫 릴리스 태그 `v0.1.0` | done | 태그 · 릴리스 노트 | [op-04](prd/doc.md#op-04) |
| 실행 이미지(코드 없음) · 코드 폴더 마운트 | done | 개발 서버 · 의존성 지문 · 코드 커밋 표시 | [op-06](prd/doc.md#op-06) |
| 개발 → 운영 굽기(실행 이미지 + 시험한 코드) | done | `Dockerfile.bake` · `bake.sh` · 반입 판정 · 저장·분할 | [op-07](prd/doc.md#op-07) |
| 서버 설치·업그레이드 절차 | done | 설치 길 하나 · podman 기본 · 0.2.0 업그레이드·되돌리기 | [op-10](prd/doc.md#op-10) |
