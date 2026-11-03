# 테스트·평가

[PRD.md](../PRD.md)의 카테고리 하나 — 변경을 어떻게 증명하나: 스모크 실행, 시험 층, 품질 평가, 답변 점검, 시험 자료, 이미지 반입 판정(PC + 반입 관문).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서(주제별): 시험 층·반입 e2-02·e2-08·e2-14·e2-11·e2-15 → 스모크·시험 자료 e2-01·e2-13·e2-09 → 평가·점검 e2-03·e2-04·e2-05·e2-12·e2-19·e2-20·e2-06·e2-07·e2-16 → 정리 e2-10·e2-17·e2-18 → 코드와 다른 점.

<a id="e2-02"></a>
## e2-02 · 시험 층
- 이유: 반입 판정은 네트워크 없이 이미지 안에서 돌아야 한다.
- 무엇: `tests/server/`(이미지 반입 관문, `pipeline.cli selftest`가 `tests/runner.py`로 실행), `tests/general/`(PC 전용: PG, Docker, 느린 것). 알려진 실패는 목록에 두고, XPASS면 지우라고 경고.
- 파일: `tests/runner.py`, `tests/conftest.py`, `deploy/release/known_fail.txt`.
- 기준선(CLAUDE.md §4·§6-3에서 옮김, 10-30):
  - (11-03 `feature/pl38-master` — 마스터 표 pl-38, fp-perf `35800d9` 위) `selftest` **93개 모두 통과** · `pytest tests/` **142 passed · 3 skipped** · FINGERPRINT `18142592accca442` · p0 `cc4adb6b9e73` · p1 `f0f8be78addb` · r `bc65d6cd20d4` · s `a23bc5f8f227`(엔진 지문 13개는 그대로 — 핸드오프 `terms.py`가 바뀜).
  - (11-03 `feature/fp-perf` — 0.2.0 지문 배치 후속 pl-49, develop `8c4e078` 위) `selftest` **91개 모두 통과** · `pytest tests/` **140 passed · 3 skipped** · FINGERPRINT `dbdecec04862c89f` · p0 `b40736f407f2` · p1 `59cc9bec4676` · r `135ab4c59a54` · s `9a690d9273ef`(엔진 지문 13개는 그대로 — 엔진 파일 안 건드림).
  - (11-03 `feature/pl46-fp-batch` — 0.2.0 지문 배치, develop `e3c803c`(#104·#102·#87) 위) `selftest` **91개 모두 통과** · `pytest tests/` **140 passed · 3 skipped** · FINGERPRINT `543ade95fde0fcae` · p0 `39f4dc7e1231` · p1 `2e1e9dd3814a` · r `3ac22cd1c74e` · s `5eb430cc1cff`(층 a 지움).
  - (11-02 `feature/publish-guard` — 사용자 11-02 known_fail 0) `selftest` **79개 모두 통과**(`selftest_gate.sh` → `[판정] 통과 — FAIL 0`, 알려진 실패 목록 빔 — `test_publish_guard`를 source.json 게시 가드와 함께 지움) · `pytest tests/` **126 passed · 1 skipped**(develop e6a625f를 합친 뒤 · xfail 0 — 일반 테스트 알려진 실패는 `tests/conftest.py` `GENERAL_KNOWN_FAIL`) · 핑거프린트 `FINGERPRINT` `2f1da6a1567d24a8` · a `e3b0c44298fc` · p0 `1b137bdd8de2` · p1 `3e673ee31e56` · r `1f1138777df2` · s `8e2c3b5c8907`.
  - (11-03 `feature/logging` — develop `28ad892`을 합친 상태, Windows PC·PG 없음) `selftest` **90개 모두 통과**(`selftest_gate.sh` → `[판정] 통과 — FAIL 0`) · `pytest tests/` **140 passed · 3 skipped**(PG 필요 사례) · 핑거프린트 `FINGERPRINT 2f1da6a1567d24a8`(그대로) · a `e3b0c44298fc` · p0 `44417554ef91` · p1 `7a02ff0b3fc5` · r `e8a8fed0de61` · s `028e8415cd6e`(로깅 공용 파일·적재 span 때문에 develop과 다름) · MCP tools/list 11886바이트·SHA-256 `7d24d867…`(develop과 같음).
  - (10-31 `feature/op09-no-hardcode` — op-08 병합 뒤 develop을 합친 상태) `selftest` **94개 중 93개 통과**(알려진 실패 `test_publish_guard`) · `pytest tests/` **146 passed · 1 skipped(PG 설정 없는 작업 폴더 — `test_pl14_deploy`) · 3 xfailed** · 핑거프린트 `FINGERPRINT` `2f1da6a1567d24a8` · p0 `d7367309a2a8` · p1 `131b90a90659` · r `060344a6f429` · s `5db77013648f` · a `e3b0c44298fc`(엔진 18개 지문도 2a에서 바뀜 — 0.2.0 전체 재처리)
  - (10-31 `feature/op08-settings-layout` — op-08이 스트리밍·그림자·실험 기능과 그 시험을 지운 뒤) `selftest` **93개 중 92개 통과** · `pytest tests/` **146 passed · 3 xfailed**(작업 폴더 `settings.yaml`에 전용 PG) · 핑거프린트 `FINGERPRINT abe9b7b0799ceaae`(그대로) · a `e3b0c44298fc` · p0 `35df8d19cba6` · p1 `068c126e7a83` · r `8bfca1b178e8` · s `72dfe4177e78`(공용 `settings.py`·`paths.py` 등이 바뀜 — 0.2.0 전체 재처리). 아래는 그 전(10-30) 값.
  - `selftest`는 **94개 중 93개 통과**다(10-30 `feature/pl12-no-deleted` — #58이 시험 3개를 지우고 `test_no_deleted` 1개를 더한 뒤). 알려진 실패는 `tests.server.pipeline.test_publish_guard` 1개다(`deploy/release/known_fail.txt`, refactor.md C-54).
  - `pytest tests/`는 **148 passed · 3 xfailed**다(10-30 `release/0.1.0` E2E — 루트 `settings.yaml`에 전용 PG가 있을 때. 없으면 `test_pl14_deploy`가 건너뛰어 146 passed · 1 skipped). 위 1개와 일반 테스트 2개(`tests/conftest.py`의 `GENERAL_KNOWN_FAIL` — `test_run_combo`·`test_pub_registry`(C-54 ①))이며, 모두 리팩토링 전부터 있던 실패다.
  - 핑거프린트 10-30 값(`feature/pl12-no-deleted` — 공용 `settings.py`·`pg.py`·`structdb.py`가 바뀌어 p0·p1·r·s 모두 바뀜. 그 전 `feature/pl34-p1-cleanup` 값: p0 `2b4ad090d25e` · p1 `81cfe39fd09e` · r `7901ef34500b` · s `bcac3fe53d14`): `FINGERPRINT abe9b7b0799ceaae` · a `e3b0c44298fc` · p0 `0e6a5bc155b1` · p1 `1df0ba57214b` · r `bce50575a881` · s `10f13083e536`. 엔진 18개(재파싱 키 `run_all.engine_code_fp` — `qwen_vlm` `06f937fcc39e` · `kreuzberg` `7e7c9ac44287` · `rapidocr_ko` `990ebae04429`, 나머지는 refactor.md 부록 2). 공용·레이어 파일을 고친 커밋은 전후 값을 커밋 메시지에 적는다(CLAUDE.md §4).
  - PC 시험 사례(자식 프로세스)는 개발자 루트 `settings.yaml`을 읽지 않는다 — `pipeline/cli.py` `case_env`가 시험 전용 바탕 설정(`run_env: local`만, 접속·키 없음)을 준다. 실 PG가 있어야 판정되는 사례만 `_PC_SETTINGS_CASES`에 넣는다(지금 `test_pub_registry`).
  - 0.1.0 반입 판정(10-30, develop `0ef807f` 코드를 실행 이미지에 붙여 실행): `data-pipeline-runtime:0.1.0` **75개 중 74개 통과**(SKIP 19, 알려진 실패 1) · `mcp-server-runtime:0.1.0` **47개 모두 통과** · 의존성 지문 `f0fcc30bd067bc2f` 일치.
  - (`test_trigger_server`는 11-01에 trigger 서버와 함께 지움 — pl-10.)
- Status: done

<a id="e2-08"></a>
## e2-08 · 이미지 빌드와 반입 관문
- 이유: 서버는 selftest를 통과한 이미지만 받아야 한다.
- 무엇: 빌드·전송 스크립트, selftest 관문은 `[판정]` 줄을 읽음, 코드만 바뀌면 오버레이 패치.
- 파일: `deploy/release/build_ship.sh`, `deploy/release/selftest_gate.sh`, `docs/operations/release-and-patch.md`.
- Status: done

<a id="e2-14"></a>
## e2-14 · 반입 시험이 이미지 안에만 있음
- 이유: 오버레이 패치로 시험을 고칠 수 없다(C-53).
- 결정(사용자 10-30 grill): 시험을 바꾸는 변경은 새 이미지 판이 필요하다(초안 규칙 채택).
- 파일: `deploy/docker/Dockerfile`, `tests/server/`.
- 결정(사용자 10-30 PRD grill): S3 — 시험이 코드 폴더에서 돌므로(op-06 실행 이미지 + 코드 마운트) '시험을 바꾸면 새 이미지'가 필요 없어졌다 — 해소로 닫는다.
- Status: done — 해소(사용자 10-30 PRD grill S3: 시험이 코드 폴더에서 돌아 새 이미지가 필요 없음).

<a id="e2-11"></a>
## e2-11 · PC 일반 시험의 알려진 실패
- 이유: 일반 시험 7개가 리팩토링 전부터 실패한다(C-54 ①, C-58): 3개는 공용 개발 PG를 읽음(임시 SQLite·스키마를 쓸 것), 2개는 없는 패키지·모듈이 필요(건너뜀 표시 또는 고침), 1개는 EDW 필요, 1개는 `test_structured`의 `find_table_cells` 단언.
- 파일: `tests/conftest.py`(`GENERAL_KNOWN_FAIL`), `tests/general/`.
- 진행 10-29(`feature/test-cleanup`): 공용 개발 PG 실패 3개를 고쳤다 — PC 시험 자식 프로세스가 더는 개발 루트 `settings.yaml`을 읽지 않음(`pipeline/cli.py` `case_env`가 시험 전용 바탕 `run_env: local`을 줌). `test_structured`, `test_structdb`, `test_aggregate`를 목록에서 뺐다. 남음: `test_kg_external`, `test_run_combo`, `test_edwdb`, `test_pub_registry`(일부러 실 PG, C-54 ①).
- 결정(사용자 10-30 PRD grill): S4 — 이미 지운 모듈의 시험(`test_kg_external`, `test_edwdb`)은 목록과 함께 지운다. `test_run_combo`는 C7(e2-10, 평가 도구 둘만)에 따라 도구와 함께 지운다.
- Status: partly done

<a id="e2-15"></a>
## e2-15 · 에이전트 시험 패키지 경로가 상류를 가리킴
- 이유: `resolve_agent_dir`가 `example_agentic`을 `dev_tools/unit_test/fixtures/`(이 저장소에 없음)에서 찾아 `test_adk`의 `run_agent` 묶음이 건너뛰어지고, `test_paths`가 그 경로를 단언한다.
- 파일: `common/core/paths.py`(모든 레이어 의존 → code_fp), `tests/server/common/test_adk.py`, `tests/server/common/test_paths.py`.
- Status: todo — 0.2.0(사용자 10-30 PRD grill C1 — 다음 핑거프린트가 바뀌는 릴리스).

<a id="e2-01"></a>
## e2-01 · PC 스모크 — 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색
- 이유: 릴리스 전에 문서 2~3건으로 사슬 전체를 증명한다.
- 무엇: README §4-4 단계, 실행마다 다른 값은 `--set`, 임베딩 캐시 `output/edw/embed_cache.sqlite`.
- 파일: `pipeline/cli.py`(`smoke`), `mcp_server/cli/ask.py`, `valid_env/object_storage/`(시험 문서 — 목록 `list-smoke10.txt`는 10-30 `eval_sets/`와 함께 지움).
- Status: done

<a id="e2-13"></a>
## e2-13 · PC Docker 스모크가 retriever에서 멈춤
- 이유: [mcp.md#mc-10](mcp.md#mc-10)에 달려 있다.
- 파일: `valid_env/docker/compose.test.yml`, `valid_env/docker/smoke_test.sh`.
- [mcp.md#mc-10](mcp.md#mc-10)(PR #12)과 함께 고쳐짐. 병합 뒤 스모크를 다시 돌린다.
- Status: todo — mc-10은 10-30에 고침(`feature/search-path-fixes`). PC Docker 스모크를 다시 돌려 검색까지 가는지 확인할 것.

<a id="e2-09"></a>
## e2-09 · PwC_Structure `valid_env`의 PC 시험 자료
- 이유: PwC는 시험 자료를 서버처럼 배치한다 — 문서는 `object_storage/<시스템>/<uuid>/<파일>`, 정답·실행 목록은 `eval_sets/`, 합성 EDW sqlite는 `edw/`. 이 저장소에는 EDW 대역이 없었다.
- 무엇(10-29): `valid_env/unstructured/` 삭제(파일 781개, 40 MB). PwC HEAD에서 `git archive`로 `edw/`(sql + sqlite), `eval_sets/`, `object_storage/{CRMS,SFDC}` + `test_doc_purpose.md`를 가져옴(문서 33건, `object_keys.csv`와 sha256 일치). 서버 시험 셋이 읽어서 `unstructured/synth-meta-rdb/meta/`는 `edw/meta_rdb/`로 옮김.
- 파일: `valid_env/README.md`, `.gitattributes`, `tests/server/mcp/test_internal_docs.py`, `tests/server/mcp/test_search_svc.py`, `tests/server/pipeline/test_source.py`, README §4-4.
- `tests/fixtures/`는 10-29에 지움(refactor.md C-63) — 서버 배포 테스트는 데이터를 임시 폴더에 만든다.
- 남은 것: `EVAL_SETS_DIR` 기본값 → [ops-settings.md#pl-21](ops-settings.md#pl-21). 옛 묶음을 이름으로 부르는 PC 도구 → [e2-10](#e2-10).
- Status: done

<a id="e2-03"></a>
## e2-03 · 파싱 품질 평가
- 이유: 엔진·스택을 바꿔도 파싱 정확도가 떨어지면 안 된다.
- 무엇: CER, `criteria.json`과 사람 정답에 대한 값·표 재현율, 교차 확인된 값으로 자동 질문, 스택 빔 탐색, 단계 보드와 스택 보고서.
- 파일: `pipeline/eval/score_gold.py`, `auto_questions.py`, `run_combo.py`, `run_board.py`, `stack_report.py`, `pipeline/transform/represent/parse_qa.py`, `resources/config/criteria.json`.
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([e2-10](#e2-10)) — 비교는 필요할 때 다시 만든다. 이 행의 도구(`score_gold`·`run_combo`·`stack_report` 등)는 e2-10에 따라 지운다.
- Status: done

<a id="e2-04"></a>
## e2-04 · 검색 평가
- 이유: 찾기를 바꿔도 적중률이 떨어지면 안 된다.
- 무엇: hit@1/5/k, value_in_evidence, p50/p95 지연, `via` 구성. 도구 4개의 스모크, HTML/xlsx 보고서.
- 파일: `mcp_server/cli/mcp_eval.py`, `mcp_server/cli/mcp_smoke.py`, `mcp_server/cli/search_checks.py`(`qa_report.py`는 10-30 지움 — 사용자).
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([e2-10](#e2-10)) — 비교는 필요할 때 다시 만든다. `mcp_eval`·`mcp_smoke`·`search_checks`는 e2-10에 따라 지운다.
- Status: done

<a id="e2-05"></a>
## e2-05 · 답변 점검(PC 전용)
- 이유: MCP는 근거만 돌려준다. 그 근거로 만든 답에는 인용 점검이 필요하다.
- 무엇: `rag_qa` 에이전트가 `search`/`edw_meta`/`query_edw`를 부르고 결정적 인용 점검.
- 파일: `validation/e2e/answer_gen.py`, `valid_env/answer_test/rag_qa/`.
- Status: done

<a id="e2-12"></a>
## e2-12 · EDW 값 답변이 인용 검증에 실패
- 이유: `query_edw` 값을 인용한 답이 검증 실패로 기록된다(C-56 M-1).
- 무엇: (a) `kind="edw"` 인용 규칙 또는 (b) 프롬프트에서 EDW 값을 뺌 중에서 고른다.
- 파일: `valid_env/answer_test/rag_qa/`, `validation/e2e/answer_gen.py`.
- 결정(사용자 10-29/10-30 grill): 그대로 둔다 — 바꾸지 않음.
- Status: done

<a id="e2-19"></a>
## e2-19 · answer_gen 인용 버그 고치기
- 결정(사용자 10-30): 답변 점검(`answer_gen`)의 인용 버그를 지금 고친다(e2-12의 EDW 값 인용 규칙은 그대로). 출처: [history/deploy_0_1_0.md](../history/deploy_0_1_0.md) §1 ⑤ 행(옛 refactor.md "최종")(원 보고서 VS10-verify K-1·S11-impl·VS11-verify는 git 밖).
  - L-2·P-2·CR-2~4: `verify_note`가 문제 글의 앞부분(접두어)에 기댄다.
  - CR-5: `answer_gen.verify`가 JSON으로 못 바꾸는 인자에서 TypeError.
  - CR-6: `python -O`이면 `verify_citations.py`의 `assert`가 빠진다.
  - CR-7: dict를 직렬화했다가 다시 읽어, 인자를 펼쳐 넘기는 모델이면 시그니처 TypeError(실제로는 드묾).
- 파일: `validation/e2e/answer_gen.py`, `valid_env/answer_test/rag_qa/`.
- 반영(10-30 `7b0c3c6`·`89d7862`): `verify_note`는 글 머리 대신 `format_error`로 가른다(L-2·P-2·CR-2~4). JSON으로 못 바꾸는 값은 problems로 돌린다(CR-5). 객체가 아닌 답은 answer_gen이 먼저 거른다(CR-6 — `-O`와 무관, 잠긴 `verify_citations.py`는 그대로). 객체 인자는 다시 직렬화하지 않는다(CR-7). 테스트: `tests/general/e2e/test_answer_gen.py`.
- Status: done

<a id="e2-20"></a>
## e2-20 · 분류 수용 보고서
- 결정(G14·T19 — 3차 grill(사용자 10-30, 원본은 git 밖)):
  - local에는 기준을 두지 않는다.
  - dev: 사람이 단 정답 샘플과 대조한 보고서만 — 원천별·라벨별 일치율과 혼동표. 통과 기준은 첫 결과를 본 뒤 정한다.
- 열린 점: 정답 샘플의 자리와 형식 — 사용자 확인.
- 관련: [transform.md#pl-33](transform.md#pl-33)(분류 단계).
- 결정(사용자 10-30 PRD grill): A8 — 분류 정답 샘플은 회사 데이터라 git에 넣지 않고 개발 서버 폴더에 CSV로 둔다(칸: `s3_key`, 정답 분류).
- Status: todo

<a id="e2-06"></a>
## e2-06 · 스택·모델 비교
- 이유: 엔진과 모델을 측정 결과와 비용으로 고른다.
- 무엇: 스택 행렬·모델 행렬 실행과 예상 비용. 유료 호출은 승인 필요(CLAUDE.md §7).
- 파일: `validation/e2e/model_matrix.py`(`stack_matrix.py`·`stack_matrix.json`·보고서 `pipeline/eval/stack_report.py`는 10-30 지움 — [e2-18](#e2-18)).
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([e2-10](#e2-10)) — 비교는 필요할 때 다시 만든다. `model_matrix`는 e2-10에 따라 지운다.
- Status: done

<a id="e2-07"></a>
## e2-07 · 검색 점검 페이지
- 이유: 사람이 브라우저에서 근거를 살펴본다.
- 무엇: MCP 서버와 pgvector로 이어 주는 로컬 페이지(기본 포트 8790 — `mcp.dev.ui_port`, README 예시 설정은 8791).
- 파일: `validation/search_ui/serve.py`, `validation/search_ui/start_mcp.sh`, `start_ui.sh`.
- Status: done

<a id="e2-16"></a>
## e2-16 · 검색 점검 페이지가 고정 글 "10 documents (20 chunks)"를 보임
- 결정(사용자 10-31 범위 축소 grill): 검색 확인 페이지 고정 글 수정은 **뺀다**.
- 파일: `validation/search_ui/index.html`.
- Status: dropped (사용자 10-31 범위 축소)

<a id="e2-10"></a>
## e2-10 · PC 평가 도구를 줄이고 그 설정을 남길지 지울지
- 결정(사용자 10-31 범위 축소 grill): 남길 것 외의 PC 평가 도구(pipeline/eval·model_matrix·mcp_eval·search_checks·synth_score와 그 설정 칸)를 **지금 지운다** — 검색 확인 페이지와 답변 점검만 남김.
- 이유: 설정 약 50개가 PC 시험·실험에만 있다(`common.dev.*`, `pipeline.dev.*`, `pipeline.eval.*`, `mcp.dev.*`, `runtime.exp_*`, `graphiti.*`).
- 파일: `validation/e2e/`, `pipeline/eval/`, `mcp_server/cli/`, `common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`.
- 결정(사용자 10-30 grill): `validation/search_ui`(검색 점검 페이지)와 `valid_env/answer_test`(답변 점검)**만** 남긴다. 스택 비교, 자동 질문 만들기, 지운 묶음용 채점기(예: `chart_values_score.py`)와 그 설정은 지운다.
- 결정(사용자 10-30 PRD grill): C7 — PC 평가 도구는 이 행대로 둘만 남긴다. 스택·모델 비교 도구(`model_matrix`·`score_gold`·`mcp_eval`)를 전제로 한 다른 행(e2-03·e2-04·e2-06·pl-31·pl-32·pl-03)은 '비교는 필요할 때 다시 만든다'로 고치고, e2-11의 `test_run_combo`는 도구와 함께 지운다.
- Status: done (11-01, `feature/scope-cut-pipeline`) — 지움: `pipeline/eval/` 전부(report·run_board·score_gold·auto_questions·gold_draft·qa_draft·make_questions·run_combo·stages·anchors·explorer·server_checks), `pipeline/shared/phase_report.py`, `validation/e2e/model_matrix.{py,json}`, `mcp_server/cli/{mcp_eval,search_checks}.py`, `mcp_server/services/search/synth_score.py`, 그것만 쓰던 지시서 `gold_draft`·`qa_draft`·`table_struct_judge`, `pipeline.cli`의 `compare-parse`·`compare-all`, 이미지 `tool` 목록(`entrypoint.sh` TOOL_PKGS)·`run_tool.sh`의 평가 도구, 검색 도구 job 서비스 `retrieval`(compose), 시험 12개(`GENERAL_KNOWN_FAIL`의 `test_run_combo` 포함). 설정 칸(남으면 경고만): `pipeline.eval`의 정답·질문 초안·표 채점 5칸, `pipeline.paths.report_digest_dir`, `mcp.dev.eval_s_parts`, `mcp.host.tool_cpus`·`tool_mem_limit`. 남김: `validation/search_ui`, `valid_env/answer_test`, `validation/e2e/answer_gen`, `pipeline.eval.review_max_rounds`(그림 검토 `figure_review`가 읽음), 지시서 `mermaid_check`(`test_agent_prompts`의 예시), `mcp_server/cli/mcp_smoke.py`(10-31 결정 목록 밖), `check_env`의 `GOLD_DIR` 점검. `mcp_server/cli/ask.py test-stack`은 질문 파일이 없으면 멈춘다(자동 질문 생성 지움).

<a id="e2-17"></a>
## e2-17 · 10-29 감사에서 찾은 안 쓰는 함수 지우기
- 이유: 죽은 코드는 읽는 시간과 린트 관리 비용을 든다.
- 10-29에 지움(호출부 없음, 핑거프린트 그대로): `parse_env_file`(`common/config/migrate.py`), `_lane_push`(`deploy/host/scripts/run_docs.py`), `_bg_img`(`mcp_server/routers/dispatch.py`), `_scan_paren`(`mcp_server/services/edw_query.py`), `_local_sidecar_name`(`pipeline/load/parsing_meta.py`), 모듈 `pipeline/tools/check_runlog.py`(한 번 쓴 runs.jsonl 잠금 점검 — 필요하면 git에서 되살림).
- 남음: `fields_table`(`common/config/settings.py`) — 다음 핑거프린트 릴리스를 기다림(`checklist`는 `decompose.py`와 함께 갔음, 10-29). 시험만 부르는 것 — `do_evidence_image`, `do_related`(`internal_docs.py`), `eval_labels`(`qtype.py`), `availability_note`(`stack_report.py`), `raster_chart_values`(`chart_values.py`, 레이어 p1), `pool_distractor_files`(`stack_matrix.py`).
- 결정(사용자 10-30 grill): 시험만 부르는 것도 그 시험과 함께 지운다([e2-18](#e2-18)).
- Status: done (10-30, `feature/drop-unused`) — 지움: `do_evidence_image`·`do_related`(`internal_docs.py`), `availability_note`(`stack_report.py`), `pool_distractor_files`(`stack_matrix.py`) + 그 시험 줄. `eval_labels`는 앱 코드(`qtype.py`)에서 지우고 시험(`test_qtype.py`)으로 옮김 — 유형 라우터 정확도 점검은 남김.py`, 레이어 p1), `fields_table`(`common/config/settings.py`, 모든 레이어) — 지문을 바꾸는 판에서. · 0.1.0 지문 배치(`feature/fp-batch`)에서 나머지도 지움: `fields_table`, `raster_chart_values`(+ `enlarge`·`ratio_place`·지시서 `figure_chart_raster`), `retriever._concept_top`·`hidden_names`·`client_map`·`_client_rows`·`_chunk_key_hidden`, 상수 `EVAL_SETS_DIR`, 고아 지시서 `diagram_arrows`.

<a id="e2-18"></a>
## e2-18 · 요건 없는 코드 지우기
- 이유(사용자 10-30 grill): 안 쓰는 길이 아직 지운 칸을 읽고 관리 비용을 든다. 대상은 각 카테고리 파일 끝 "요건 없는 코드"(옛 gaps §2).
- 지움: `internal_docs.py` 숨김 문서 함수(6개, 지운 doc 칸을 아직 SELECT하는 문서 조회·목록 포함), 위키 도구, 외부 KG 어댑터, 시험만 부르는 함수([e2-17](#e2-17)), 지운 평가 묶음용 채점기([e2-10](#e2-10)).
- 남김: SQLite 대체(`MCP_EVIDENCE_PATHS`는 11-01 mc-15에 지움), 문서 대장 CLI, 메일 첨부, 용어집·고객 목록 도구, 밤 타이머, `os_put`, 서버 점검.
- 규칙: MCP 도구 이름과 입출력은 그대로. 하나라도 바뀌면 멈추고 묻는다.
- 남김 목록 고침(허브 10-31): `PARSE_STREAM`·그림자 모드·`SEARCH_TIE_BREAK` 스위치는 op-08에서 지워 남김에서 뺐다. 카테고리 파일 끝 '요건 없는 코드' 목록에서 이미 지운 것(이 행·fp-batch)을 뺐다(mcp·etl·test, 10-31).
- 11-01(`feature/scope-cut-unused`, 허브 지시): 호출부 없는 지시서 `pipeline/parse_shadow`·`mcp/research_judge`·`mcp/agg_llm_route`를 지움 — 지시서 시험(`test_agent_prompts`·`test_adk`의 output_schema 재요청)은 `nested_figure`로, `test_paths`는 남은 패키지로 바꿈. `common/core/paths.py:112` 주석의 `parse_shadow` 언급은 고치면 레이어 code_fp 4개가 모두 바뀌어 남김(0.2.0 배치에서).
- 11-01(`feature/scope-cut-unused`, 허브 지시): 부르는 곳 없는 코드 둘 — `pipeline/shared/summarize.py`의 엔진 비교 요약 명령 `main`(summary.md·engines.csv — `FAMILY`·`nums`는 represent가 써서 남김), `pipeline/mcp_parse_service.py`의 이미지 갈래 `_IMAGE_EXTS`·`IMAGE_NOTE`(이미지는 `ALLOWED_EXTS`에 없어 도달 불가).
- Status: done (10-30, `feature/drop-unused`, 사용자 grill 11차 포함) — 지움: `internal_docs.py`의 `do_get_document`·`do_get_image`·`do_evidence_image`·`do_lookup_term`·`do_related`·`do_list_documents`와 그것만 쓰던 도우미(MCP 도구 아님 — 도구 이름·입출력 그대로), `objectstore_access.py`, 위키 도구(`structure/wiki.py`·`wiki_draft.py` + 지시서 `wiki_term_draft`), 외부 KG 어댑터(`eval/kg_external.py`)·LLM 그래프 모드(`validation/e2e/graph_llm.py` + 지시서 `triple_extract`), 채점기 `chart_values_score.py`·`diagram_edges_score.py`(`score_gold`의 mermaid 재현율은 같은 규칙으로 그 안에), `search/terms.lookup_term`, `valid_env/eval_sets/`와 그것만 읽던 `validation/e2e/stack_matrix.py`(+ `stack_matrix.json`·보고서 `pipeline/eval/stack_report.py`), Q&A 보고서 `mcp_server/cli/qa_report.py`(사용자 10-30), 시험만 쓰던 함수(e2-17), 각 시험, 설정 칸 7개(`MCP_EVID_*`·`MCP_IMAGES`·`MCP_MAX_IMAGE_PX`)와 절 `pipeline.connections.graphiti`(경고만 — env-guide). 지문 그대로._concept_top`·`hidden_names`·`client_map`(r), 상수 `EVAL_SETS_DIR`([ops-settings.md#pl-21](ops-settings.md#pl-21)). · 0.1.0 지문 배치(`feature/fp-batch`)에서 나머지도 지움: `fields_table`, `raster_chart_values`(+ `enlarge`·`ratio_place`·지시서 `figure_chart_raster`), `retriever._concept_top`·`hidden_names`·`client_map`·`_client_rows`·`_chunk_key_hidden`, 상수 `EVAL_SETS_DIR`, 고아 지시서 `diagram_arrows`.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| PC 시험 통과 | 일반 시험 7개가 리팩토링 전부터 실패 | `tests/conftest.py` | e2-11 |
| `query_edw` 값을 인용한 답이 인용 점검 통과 | 검증 실패로 기록 | `valid_env/answer_test/rag_qa/` | e2-12 |
| PC Docker 스모크가 검색까지 감 | retriever에서 멈춤(mc-10 — 10-30 고침, 다시 돌려 확인 필요) | `valid_env/docker/` | e2-13 |
| 에이전트 시험 패키지를 찾음 | 상류 `dev_tools/unit_test/fixtures/`에서 찾음 → `run_agent` 시험 묶음 건너뜀 | `common/core/paths.py` | e2-15 |
| 검색 페이지가 실제 개수를 보임 | 고정 글 "10 documents (20 chunks)" | `validation/search_ui/index.html` | e2-16 |

### 요건 없는 코드 — 남길지 지울지([e2-10](#e2-10)과 함께 결정, [e2-18](#e2-18))
- 정답·질문 초안. `pipeline/eval/gold_draft.py`, `qa_draft.py`, `make_questions.py`.
- 탐색 HTML, 서버 측정 팩, 조합 보고서. `pipeline/eval/explorer.py`, `server_checks.py`, `report.py`.
- 지운 묶음(`synth-4clients` …)을 이름으로 부르는 모델 행렬. `validation/e2e/model_matrix.py`, `mcp_server/cli/mcp_eval.py`.
- 시험만 부르는 함수: `eval_labels`(`qtype.py`). (외부 KG 어댑터·묶음 채점기·스택 행렬·나머지 시험 전용 함수는 10-30에 지움 — [e2-18](#e2-18).)

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 답변 점검, 스택·모델 행렬 | — | LLM. 유료 실행은 승인 필요 |
