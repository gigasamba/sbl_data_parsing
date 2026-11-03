# 테스트·평가

[PRD.md](../PRD.md)의 카테고리 하나 — 변경을 어떻게 증명하나: 스모크 실행, 시험 층, 품질 평가, 답변 점검, 시험 자료, 이미지 반입 판정(PC + 반입 관문).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서(주제별): 시험 층·반입 e2-02·e2-08·e2-14·e2-11·e2-15·e2-21 → 스모크·시험 자료 e2-01·e2-13·e2-09 → 평가·점검 e2-03·e2-04·e2-05·e2-12·e2-19·e2-20·e2-06·e2-07 → 정리 e2-10·e2-17·e2-18 → 코드와 다른 점.

<a id="e2-02"></a>
## e2-02 · 시험 층
- 이유: 반입 판정은 네트워크 없이 이미지 안에서 돌아야 한다.
- 무엇: `tests/server/`(이미지 반입 관문, `pipeline.cli selftest`가 `tests/runner.py`로 실행), `tests/general/`(PC 전용: PG, Docker, 느린 것). 알려진 실패는 목록에 두고, XPASS면 지우라고 경고.
- 파일: `tests/runner.py`, `tests/conftest.py`, `deploy/release/known_fail.txt`.
- 기준선(CLAUDE.md §4·§6-3에서 옮김, 10-30):
  - 지금(11-04, develop `191666d`, Windows PC·PG 없음): `selftest` **99개 모두 통과** · 알려진 실패 0(`deploy/release/known_fail.txt`·`tests/conftest.py` `GENERAL_KNOWN_FAIL` 모두 빔) · FINGERPRINT `18142592accca442` · p0 `e99101f19627` · p1 `9e2dcfd20f1e` · r `cd05c8301501` · s `179ef4cb0a4d`. `pytest tests/` 개수는 이번에 다시 재지 않았다 — 다음에 PC에서 잴 때 이 줄에 적는다.
  - 지난 기준선(0.1.0 반입 판정·11-02~11-03 브랜치별 값)은 [history/refactor_c_items.md](../history/refactor_c_items.md) "PRD에서 옮긴 옛 기록".
  - 공용·레이어 파일을 고친 커밋은 전후 값을 커밋 메시지에 적는다(CLAUDE.md §4). 0.1.0 때 값과 바뀐 과정은 [history/deploy_0_1_0.md](../history/deploy_0_1_0.md).
  - PC 시험 사례(자식 프로세스)는 개발자 루트 `settings.yaml`을 읽지 않는다 — `pipeline/cli.py` `case_env`가 시험 전용 바탕 설정(`run_env: local`만, 접속·키 없음)을 준다. 실 PG가 있어야 판정되는 사례만 `pipeline/cli.py`의 `_PC_SETTINGS_CASES`에 넣는다(지금은 비어 있음).
- Status: done

<a id="e2-08"></a>
## e2-08 · 이미지 빌드와 반입 관문
- 이유: 서버는 selftest를 통과한 이미지만 받아야 한다.
- 무엇: 빌드·전송 스크립트, selftest 관문은 `[판정]` 줄을 읽음, 코드만 바뀌면 코드 폴더 바꾸기(남은 옛 흔적 정리는 [e2-21](#e2-21)).
- 파일: `deploy/release/build_ship.sh`, `deploy/release/selftest_gate.sh`, `docs/operations/release-and-patch.md`.
- Status: done

<a id="e2-14"></a>
## e2-14 · 반입 시험이 이미지 안에만 있음
- 이유: 오버레이 패치로 시험을 고칠 수 없다(C-53).
- 파일: `deploy/docker/Dockerfile`, `tests/server/`.
- 결정(사용자 10-30 PRD grill): S3 — 시험이 코드 폴더에서 돌므로(op-06 실행 이미지 + 코드 마운트) '시험을 바꾸면 새 이미지'가 필요 없어졌다 — 해소로 닫는다.
- Status: done — 해소(사용자 10-30 PRD grill S3: 시험이 코드 폴더에서 돌아 새 이미지가 필요 없음).

<a id="e2-11"></a>
## e2-11 · PC 일반 시험의 알려진 실패
- 이유: 일반 시험 7개가 리팩토링 전부터 실패한다([C-54](../history/refactor_c_items.md) ①, C-58): 3개는 공용 개발 PG를 읽음(임시 SQLite·스키마를 쓸 것), 2개는 없는 패키지·모듈이 필요(건너뜀 표시 또는 고침), 1개는 EDW 필요, 1개는 `test_structured`의 `find_table_cells` 단언.
- 파일: `tests/conftest.py`(`GENERAL_KNOWN_FAIL`), `tests/general/`.
- 진행 10-29(`feature/test-cleanup`): 공용 개발 PG 실패 3개를 고쳤다 — PC 시험 자식 프로세스가 더는 개발 루트 `settings.yaml`을 읽지 않음(`pipeline/cli.py` `case_env`가 시험 전용 바탕 `run_env: local`을 줌). `test_structured`, `test_structdb`, `test_aggregate`를 목록에서 뺐다. 남음: `test_kg_external`, `test_run_combo`, `test_edwdb`, `test_pub_registry`(일부러 실 PG, [C-54](../history/refactor_c_items.md) ①).
- 결정(사용자 10-30 PRD grill): S4 — 이미 지운 모듈의 시험(`test_kg_external`, `test_edwdb`)은 목록과 함께 지운다. `test_run_combo`는 C7(e2-10, 평가 도구 둘만)에 따라 도구와 함께 지운다.
- Status: done — 남은 알려진 실패 0(`tests/conftest.py` `GENERAL_KNOWN_FAIL = {}`, `deploy/release/known_fail.txt` 빔).

<a id="e2-15"></a>
## e2-15 · 에이전트 시험 패키지 경로가 상류를 가리킴
- 이유: `resolve_agent_dir`가 폴더가 없는 갈래 셋(`resources/prompts/mcp`·`validation/e2e`(`triple_extract` 지움)·`dev_tools/unit_test/fixtures`)도 본다(늘 못 찾음). `test_paths`가 그 경로를 단언한다.
- 파일: `common/core/paths.py`(모든 레이어 의존 → code_fp), `tests/server/common/test_paths.py`.
- Status: todo — 죽은 갈래 지우기. `paths.py`를 고치면 레이어 지문이 모두 바뀌므로 다음 지문 배치에서(사용자 10-30 PRD grill C1).

<a id="e2-21"></a>
## e2-21 · 옛 오버레이 패치 흔적 정리
- 이유: `deploy/release/make_patch.sh`를 지웠다(사용자 11-03 `feature/drift-followup` — 코드 폴더 바꾸기로 대체). 그 스크립트만 만들거나 읽던 것이 남았다.
- 한 것(11-03 `feature/drift-followup`): `deploy/host/scripts/run_docs.py`·`host_env.py`의 옛 `app/deploy/common` 찾기 갈래를 지움(호스트 스크립트 — 레이어 지문 밖).
- 남은 것: ① `common/core/fingerprint.py` `pipeline_version()`의 `common/PATCH_VERSION` 후보(와 `tests/server/common/test_fingerprint.py`의 그 사례·`keyscan.py` `PIPELINE_VERSION` 설명) — 레이어 지문(code_fp) 파일이라 허브가 릴리스 지문 배치에서 지운다. ② `deploy/docker/IMAGE_BASE`(+ `.gitattributes` 줄) — 읽는 곳이 없다, 지울지 사용자가 정한다.
- 파일: `common/core/fingerprint.py`, `deploy/docker/IMAGE_BASE`.
- Status: todo

<a id="e2-01"></a>
## e2-01 · PC 스모크 — 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색
- 이유: 릴리스 전에 문서 2~3건으로 사슬 전체를 증명한다.
- 무엇: README §4-4 단계, 실행마다 다른 값은 `--set`, 임베딩 캐시 `output/edw/embed_cache.sqlite`.
- 파일: README §4-4 명령(`pipeline.cli parse` · `build_bundle` · `dbtool` · `pgvector_load`), `mcp_server/cli/ask.py`, `valid_env/object_storage/`(시험 문서).
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
- 파일: `valid_env/README.md`, `.gitattributes`, `tests/server/mcp/test_search_svc.py`, `tests/server/pipeline/test_source.py`, README §4-4.
- 서버 배포 테스트는 데이터를 임시 폴더에 만든다.
- Status: done

<a id="e2-03"></a>
## e2-03 · 파싱 품질 평가
- 이유: 엔진·스택을 바꿔도 파싱 정확도가 떨어지면 안 된다.
- 평가 도구는 [e2-10](#e2-10)에 따라 지웠다 — 비교는 필요할 때 다시 만든다. 파싱 품질 점검은 `pipeline/transform/represent/parse_qa.py`·`resources/config/criteria.json`.
- Status: done

<a id="e2-04"></a>
## e2-04 · 검색 평가
- 이유: 찾기를 바꿔도 적중률이 떨어지면 안 된다.
- 평가 도구는 [e2-10](#e2-10)에 따라 지웠다 — 비교는 필요할 때 다시 만든다. 남은 스모크 `mcp_server/cli/mcp_smoke.py` — `--source <원천>` 필수(search가 원천 하나를 요구)이고 근거 칸은 `EVIDENCE_KEYS` 13칸을 본다.
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
- 비교 도구는 [e2-10](#e2-10)에 따라 지웠다 — 비교는 필요할 때 다시 만든다(유료 호출은 승인 필요 — CLAUDE.md §7).
- Status: done

<a id="e2-07"></a>
## e2-07 · 검색 점검 페이지
- 이유: 사람이 브라우저에서 근거를 살펴본다.
- 무엇: MCP 서버와 pgvector로 이어 주는 로컬 페이지(기본 포트 8790 — `mcp.dev.ui_port`, README 예시 설정은 8791).
- 파일: `validation/search_ui/serve.py`, `validation/search_ui/start_mcp.sh`, `start_ui.sh`.
- Status: done

<a id="e2-10"></a>
## e2-10 · PC 평가 도구를 줄이고 그 설정을 남길지 지울지
- 이유: 설정 약 50개가 PC 시험·실험에만 있다(`common.dev.*`, `pipeline.dev.*`, `pipeline.eval.*`, `mcp.dev.*`, `runtime.exp_*`, `graphiti.*`).
- 파일: `validation/e2e/`, `pipeline/eval/`, `mcp_server/cli/`, `common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`.
- 결정(사용자 10-30 grill): `validation/search_ui`(검색 점검 페이지)와 `valid_env/answer_test`(답변 점검)**만** 남긴다. 스택 비교, 자동 질문 만들기, 지운 묶음용 채점기(예: `chart_values_score.py`)와 그 설정은 지운다.
- Status: done (11-01, `feature/scope-cut-pipeline`) — 남김: `validation/search_ui`, `valid_env/answer_test`, `validation/e2e/answer_gen`, `mcp_server/cli/mcp_smoke.py`, 점검기 `common/check/checker.py`의 `GOLD_DIR` 점검.

<a id="e2-17"></a>
## e2-17 · 10-29 감사에서 찾은 안 쓰는 함수 지우기
- 이유: 죽은 코드는 읽는 시간과 린트 관리 비용을 든다.
- 10-29에 지움(호출부 없음, 핑거프린트 그대로): `parse_env_file`(`common/config/migrate.py`), `_lane_push`(`deploy/host/scripts/run_docs.py`), `_bg_img`(`mcp_server/routers/dispatch.py`), `_scan_paren`(`mcp_server/services/edw_query.py`), `_local_sidecar_name`(`pipeline/load/parsing_meta.py`), 모듈 `pipeline/tools/check_runlog.py`(한 번 쓴 runs.jsonl 잠금 점검 — 필요하면 git에서 되살림).
- 결정(사용자 10-30 grill): 시험만 부르는 것도 그 시험과 함께 지운다([e2-18](#e2-18)).
- Status: done (10-30, `feature/drop-unused` · 0.1.0 지문 배치 `feature/fp-batch`) — 호출부 없는 함수와 시험만 부르던 함수를 지웠다. `eval_labels`는 시험(`tests/server/mcp/test_qtype.py`)으로 옮겼다.

<a id="e2-18"></a>
## e2-18 · 요건 없는 코드 지우기
- 이유(사용자 10-30 grill): 안 쓰는 길이 아직 지운 칸을 읽고 관리 비용을 든다. 대상은 각 카테고리 파일 끝 "요건 없는 코드"(옛 gaps §2).
- 지움: `internal_docs.py` 숨김 문서 함수(6개, 지운 doc 칸을 아직 SELECT하는 문서 조회·목록 포함), 위키 도구, 외부 KG 어댑터, 시험만 부르는 함수([e2-17](#e2-17)), 지운 평가 묶음용 채점기([e2-10](#e2-10)).
- 남김: SQLite 대체(PG 대역), 메일 첨부, 용어집·고객 목록 도구, 밤 타이머.
- 규칙: MCP 도구 이름과 입출력은 그대로. 하나라도 바뀌면 멈추고 묻는다.
- 11-01(`feature/scope-cut-unused`, 허브 지시): 호출부 없는 지시서 `pipeline/parse_shadow`·`mcp/research_judge`·`mcp/agg_llm_route`를 지움 — 지시서 시험(`test_agent_prompts`·`test_adk`의 output_schema 재요청)은 `nested_figure`로, `test_paths`는 남은 패키지로 바꿈.
- 11-01(`feature/scope-cut-unused`, 허브 지시): 부르는 곳 없는 코드 둘 — `pipeline/shared/summarize.py`의 엔진 비교 요약 명령 `main`(summary.md·engines.csv — `FAMILY`·`nums`는 represent가 써서 남김), `pipeline/mcp_parse_service.py`의 이미지 갈래 `_IMAGE_EXTS`·`IMAGE_NOTE`(이미지는 `ALLOWED_EXTS`에 없어 도달 불가).
- Status: done (10-30, `feature/drop-unused` · 11-01 `feature/scope-cut-unused` · 0.1.0 `feature/fp-batch`) — MCP 도구 이름·입출력은 그대로.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| `query_edw` 값을 인용한 답이 인용 점검 통과 | 검증 실패로 기록 | `valid_env/answer_test/rag_qa/` | e2-12 |
| PC Docker 스모크가 검색까지 감 | retriever에서 멈춤(mc-10 — 10-30 고침, 다시 돌려 확인 필요) | `valid_env/docker/` | e2-13 |
| 에이전트 지시서 폴더는 저장소 안에서만 찾음 | 폴더가 없는 갈래 셋(`resources/prompts/mcp`·`validation/e2e`(`triple_extract` 지움)·`dev_tools/unit_test/fixtures`)도 봄(죽은 갈래 — 시험이 단언) | `common/core/paths.py` | e2-15 |

### 요건 없는 코드 — 남길지 지울지([e2-10](#e2-10)과 함께 결정, [e2-18](#e2-18))
- (없음)

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 답변 점검 | — | LLM. 유료 실행은 승인 필요 |
