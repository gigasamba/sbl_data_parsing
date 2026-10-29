# valid_env/ — 외부 데이터 환경 대체(PC 시험용)

> **upstream 사본(S11, 10-28 — VS10 D-12):** 이 파일과 `valid_env/unstructured/**/README.md`는 upstream(개발 원본)에서 그대로 가져온 글이라, 그 안의 `dev_tools/…`(시험·생성기 — 이 저장소에 없음)·`deploy/data_parsing/…`·`deploy/common_tools/…` 경로는 **upstream 자리**다(시험 문서 묶음 README는 바이트 그대로 둠). 이 저장소에서는: `deploy/common_tools/evaluation/mcp_eval.py` → `python -m mcp_server.cli.mcp_eval` · `deploy/data_parsing/run_all.py` → `python -m pipeline.extract.run_all` · `deploy/data_parsing/evaluation/{score_gold,run_board}.py` → `pipeline/eval/` · `deploy/data_parsing/prepare.py` → `pipeline/extract/prepare.py` · `deploy/data_parsing/engines/…` → `pipeline/extract/engines/…` · 시험은 `tests/`(CLAUDE.md §6). 운영 DB 가드는 CLAUDE.md §4.

NM16(사용자 10-14): 서버의 외부 시스템을 PC에서 흉내 내는 데이터는 모두 여기 한 곳.

| 폴더 | 무엇을 대신하나 | 내용 | Git |
|---|---|---|---|
| `unstructured/` | **Object Storage**(원본 문서가 있는 곳) | 합성 시험 문서 + 세트별 정답(qa.json·spec.json)·카탈로그·통합 시험 목록 | 추적 |
| `structured/` | 정형 DB(옛 업무 파이프라인 운영 DB) | `sales.sqlite` — 운영 DB 가드 대상, **절대 직접 열지 않음** | 제외 |
| `answer_test/rag_qa/` | 서빙 Answer Agent(PC 답변 점검용) | 답변 점검 agent 패키지(매니페스트·지시문·질문 4개·인용 검사) — `python -m validation.e2e.answer_gen`이 씀(S10, 10-29 사용자: PC 전용 데이터는 이 폴더 한 곳에) | 추적 |

시험 코드는 `dev_tools/unit_test/`, 측정 도구는 `dev_tools/perform_test/`(결과는 `output/bench/`). 다음 단계(NM16 후속): PC 실행이 폴더 직접 읽기 대신 `unstructured/`를 Object Storage처럼 읽게.

NM17(10-14, 파일 수 줄이기): 새 worktree에는 git이 무시하는(다시 만드는) 세트가 없다 — 측정·시험 전에 먼저
`python dev_tools/synthetic_data_gen/prepare_ci_fixtures.py`(또는 pytest 세션 시작 때 자동, `dev_tools/unit_test/conftest.py`)를 돌릴 것.

| 세트 | 상태 | 비고 |
|---|---|---|
| `synth-src-problem`·`synth-4clients-cmp`(docs/만) | **git 추적 해제, 생성기로 복원**(byte-identity 확인) | `python dev_tools/synthetic_data_gen/prepare_ci_fixtures.py` — 누락분만 채움, 안전 |
| `light-hard`·`synth-gold-human2`·`judge-conflicts` | **archive로 이동**(소비자 없음, 10-14 감사) | 로컬 사본만 `archive/valid_env/unstructured/<세트>/`(git 제외) — 복구는 `git log`로 삭제 커밋 찾아 `git show <커밋>^:<경로>` |
| `synth-meta-rdb`·`synth-fsm`·`synth-distractors`·`synth-distractors-v2`·`synth-4clients` | **그대로 추적**(byte-identity 실패/미확인, 10-14 감사) | `synth-meta-rdb`·`synth-fsm`: docx/xlsx zip 타임스탬프가 결정적이지 않음(`_stable_zip` 없음) · `synth-distractors`·`synth-distractors-v2`: 지금 생성기로 다시 만들면 두 스냅샷과도 안 맞음(원본 세트가 그 뒤 바뀜) · `synth-4clients`: 생성기 입력 픽스처(`tests/samples/rfi_answer/samples/supplier_facts_2026Q3.csv(git 기록에만)`)가 10-12 archive 분리로 없어져 실행 자체가 안 됨 |
| 그 밖의 모든 세트 | 그대로 추적 | 변경 없음 |

| 경로 | 내용 |
| --- | --- |
| `structured/sales.sqlite` | archive로 뺀 가격·법무·딜·RFI 파이프라인의 **운영 정본 DB** — **열지도 쓰지도 않는다**(CLAUDE.md 운영 DB 가드, `common/store/structdb.py PROD_DBS`(S3 — 옛 `deploy/common_tools/structdb.py`)·`dev_tools/unit_test/conftest.py`가 막음). 검토가 필요할 때만 사람 승인 뒤 사본으로. |
| `structured/input/` | 그 DB의 원천 CSV·스키마(거래이력 등) |
