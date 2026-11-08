# 테스트·평가

[PRD.md](../PRD.md)의 카테고리 하나 — 변경을 어떻게 증명하나: 시험 층, 이미지 반입 판정, 스모크, 시험 자료, 답변 점검.

순서: 시험 층·반입 e2-02·e2-11·e2-08·e2-15·e2-21 → 스모크·시험 자료 e2-01·e2-13·e2-09 → 점검 e2-04·e2-05·e2-19·e2-20·e2-07 → 범위 e2-10·e2-17·e2-18 → DB 시험·경계 점검 e2-22·e2-23 → 코드와 다른 점.

<a id="e2-02"></a>
## e2-02 · 시험 층과 기준선
- 이유: 반입 판정은 네트워크 없이 이미지 안에서 돌아야 한다.
- 규칙:
  1. `tests/server/`(이미지 반입 관문 — `python -m pipeline.cli selftest`가 `tests/runner.py`로 실행, 외부 접속 없음) · `tests/general/`(PC 전용: PG, Docker, 느린 것 — pytest).
  2. 알려진 실패 목록: 반입 `deploy/release/known_fail.txt`, PC `tests/conftest.py` `GENERAL_KNOWN_FAIL`. 목록에 있는 시험이 통과하면 XPASS 경고(목록에서 지움).
  3. PC 시험 사례(자식 프로세스)는 개발자 루트 `settings.yaml`을 읽지 않는다 — `pipeline/cli.py` `case_env`가 시험 전용 바탕(`run_env: local`만, 접속·키 없음)을 준다. 실 PG가 있어야 판정되는 사례만 `_PC_SETTINGS_CASES`(지금 빔).
- 기준선(11-08, slim/load — 0.3.0 + 압축 원본 풀기·문서 안 문서 꺼내기 pl-63): `selftest` 110개 모두 통과 · `pytest tests/` 171 통과 · 3 건너뜀 · 알려진 실패 0(두 목록 모두 빔) · FINGERPRINT `5f5a59693e4fe477` · code_fp p0 `3be73ca0c7b1` · p1 `473436486461` · r `6a6ea6a4d469` · s `7ec731916ece`(기록용 — 0.3.0과 달라 서버는 다시 처리) · 엔진 지문(`engine_code_fp`, 기록용): anydoc `01d0d7813c77` · archive `563e19556b61`(새 엔진) · docx2python `9ba622227470` · html_stdlib·mhtml·msg_extract `6b86d3b876c3` · hwpx `1ce4058a3a0a` · kreuzberg `f8cf85542789` · markitdown `00fa7c1d36fc` · office `c18d228eb2e6` · plaintext `e61fe9d86b40` · pymupdf `8611e97ce9ec` · qwen_vlm `a0fd63c5062a`(엔진 폴더는 그대로 — 함께 셈하는 `pipeline/shared/vlmcall.py`의 설정 이름이 바뀜) · rapidocr_ko `1e08f27b5ddd`.
- 지문 확인 명령: [CLAUDE.md](../../CLAUDE.md) §4. 공용·레이어 파일을 고친 커밋은 전후 값을 커밋 메시지에 적는다.
- QA: `python -m pipeline.cli selftest` · `[판정]` 통과, 기준선보다 나빠지지 않음.
- Status: done

<a id="e2-11"></a>
## e2-11 · PC 일반 시험의 알려진 실패 0
- 규칙: `GENERAL_KNOWN_FAIL = {}`. 공용 개발 PG를 읽는 시험은 두지 않는다(임시 SQLite·스키마).
- QA: `pytest -q tests/general` · 알려진 실패 없이 통과.
- Status: done

<a id="e2-08"></a>
## e2-08 · 이미지 빌드와 반입 관문
- 이유: 서버는 selftest를 통과한 이미지만 받아야 한다.
- 규칙: 빌드 `deploy/release/build_ship.sh`, 판정 `deploy/release/selftest_gate.sh <명령>` — 종료 코드가 아니라 `[판정]` 줄로 판정한다. 코드만 바뀌면 코드 폴더를 바꾼다([doc.md#op-06](doc.md#op-06)).
- 파일: `deploy/release/{build_ship.sh,selftest_gate.sh}`, `docs/operations/release-and-patch.md`.
- QA: `bash deploy/release/selftest_gate.sh docker run --rm <이미지:시험 태그> selftest` · `[판정] 통과`.
- Status: done

<a id="e2-15"></a>
## e2-15 · 에이전트 지시서 폴더는 있는 갈래만 찾는다
- 이유: 없는 폴더를 찾는 갈래는 읽는 사람만 헷갈리게 한다.
- 요건: `common/core/paths.py` `resolve_agent_dir`는 `resources/prompts/common` → `resources/prompts/pipeline` → `valid_env/answer_test` 셋만 본다(`tests/server/common/test_paths.py`).
- 반영: 0.3.0(11-05).
- Status: todo

<a id="e2-21"></a>
## e2-21 · 옛 오버레이 패치 흔적 정리
- 이유: 오버레이 패치 길은 없어졌는데 그 길만 읽던 것이 남았다.
- 요건: ① 버전 표기 `common/core/fingerprint.py` `pipeline_version()`은 저장소 루트 `VERSION` 하나만 읽는다(`common/PATCH_VERSION` 후보 없음 — `tests/server/common/test_fingerprint.py` 사례 표). ② `deploy/docker/IMAGE_BASE`(읽는 곳 없음)와 그 `.gitattributes` 줄은 없다.
- 반영: 0.3.0(11-05) — 레이어 지문은 그대로(`fingerprint.py`는 레이어 지문에 들지 않음).
- 비고: `pipeline/load/publish_parse_result.py`의 설명·`--version` 도움말에 `PATCH_VERSION` 글자가 남아 있다(동작 무관).
- Status: done

<a id="e2-01"></a>
## e2-01 · PC 스모크 — 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색
- 이유: 릴리스 전에 문서 2~3건으로 사슬 전체를 증명한다.
- 규칙: README §4-4 단계(`pipeline.cli parse` · `gold_bundle` · `dbtool up` · `pgvector_load` · `mcp_server.cli.search_ask`). 실행마다 다른 값은 `--set`. 임베딩 캐시 `output/edw/embed_cache.sqlite`. 시험 문서 `valid_env/object_storage/`.
- QA: README §4-4 ①~⑥ · `ask`가 근거를 냄.
- Status: done

<a id="e2-13"></a>
## e2-13 · PC Docker 스모크를 검색까지 다시 확인
- 이유: 예전에 retriever에서 멈췄다 — [mcp.md#mc-10](mcp.md#mc-10)에서 고쳤고 다시 돌려 보지 않았다.
- 할 일: `valid_env/docker/smoke_test.sh`(`compose.test.yml`)를 돌려 검색까지 가는지 확인.
- Status: todo

<a id="e2-09"></a>
## e2-09 · `valid_env`의 PC 시험 자료
- 규칙: 외부 시스템 대역은 서버 배치 그대로 — 문서 `valid_env/object_storage/<시스템>/<uuid>/<파일>`(CRMS·SFDC, 문서 33건 — `object_keys.csv`와 sha256 일치), 합성 EDW `valid_env/edw/`(sql + `edw.sqlite`, `edw/meta_rdb/`), 답변 점검 `valid_env/answer_test/`. 서버 배포 시험은 `valid_env` 없이 돌게 자료를 임시 폴더에 만든다.
- 파일: `valid_env/README.md`, `tests/server/mcp/test_search_svc.py`, `tests/server/pipeline/test_candidate.py`.
- Status: done

<a id="e2-04"></a>
## e2-04 · 검색 스모크
- 규칙: `python -m mcp_server.cli.mcp_smoke --url <MCP 주소> --source <원천> [--token …] [--q "질문"]` — 도구 목록, `search` 근거 1건 이상, 근거마다 `EVIDENCE_KEYS` 13칸 그대로 + `chunk_key`·`file_path`가 있음.
- QA: 위 명령 · 종료 0.
- Status: done

<a id="e2-05"></a>
## e2-05 · 답변 점검(PC 전용)
- 이유: MCP는 근거만 돌려준다. 그 근거로 만든 답에는 인용 점검이 필요하다.
- 규칙: `rag_qa` 에이전트(`valid_env/answer_test/rag_qa/`)가 `search`·`edw_meta`·`query_edw`를 부르고(여러 턴은 `validation/e2e/tool_loop.py` — 턴마다 예산 확인) 결정적 인용 점검을 한다. `query_edw` 값을 인용한 답은 인용 점검 실패로 기록된다(바꾸지 않음). LLM 호출 — 유료 실행은 승인 필요(CLAUDE.md §7).
- 파일: `validation/e2e/answer_gen.py`, `valid_env/answer_test/rag_qa/`.
- Status: done

<a id="e2-19"></a>
## e2-19 · answer_gen 인용 판정
- 규칙: `verify_note`는 글 머리가 아니라 `format_error`로 가른다 · JSON으로 못 바꾸는 값은 problems로 돌린다 · 객체가 아닌 답은 answer_gen이 먼저 거른다(`python -O`와 무관) · 객체 인자는 다시 직렬화하지 않는다.
- QA: `tests/general/e2e/test_answer_gen.py`·`test_verify_cite.py` · 통과.
- Status: done

<a id="e2-20"></a>
## e2-20 · 분류 수용 보고서
- 할 일: dev에서 사람이 단 정답 샘플과 대조한 보고서 — 원천별·라벨별 일치율과 혼동표. local에는 기준을 두지 않는다. 정답 샘플은 회사 데이터라 git에 넣지 않고 개발 서버 폴더에 CSV(칸: `s3_key`, 정답 분류). 통과 기준은 첫 결과를 본 뒤 정한다.
- 관련: [transform.md#pl-33](transform.md#pl-33).
- Status: todo

<a id="e2-07"></a>
## e2-07 · 검색 점검 페이지
- 규칙: MCP 서버와 pgvector에 이어 근거를 보는 로컬 페이지 — `validation/search_ui/start_mcp.sh`·`start_ui.sh`, 포트 `dev.search_ui.search_ui_port`(기본 8790), MCP 주소 `dev.search_ui.search_ui_mcp_url`(기본 `http://127.0.0.1:8765/mcp`).
- 파일: `validation/search_ui/serve.py`.
- QA: 수동 — 페이지를 열어 질문 하나에 근거가 나옴.
- Status: done

<a id="e2-10"></a>
## e2-10 · PC 평가 도구 범위
- 규칙: PC 검증 도구는 `validation/search_ui`(e2-07), `valid_env/answer_test`·`validation/e2e/answer_gen`(e2-05), `mcp_server/cli/mcp_smoke.py`(e2-04), 점검기 `common/check/checker.py`만 둔다. 파싱 품질·검색 적중률·스택·모델 비교 도구는 없다.
- Status: done

<a id="e2-17"></a>
## e2-17 · 호출부 없는 함수 두지 않기
- 규칙: 호출부가 없거나 시험만 부르는 함수는 그 시험과 함께 지운다.
- Status: done

<a id="e2-18"></a>
## e2-18 · 요건 없는 코드 두지 않기
- 규칙: PRD 행이 요청하지 않은 코드는 카테고리 파일 끝 "요건 없는 코드"에 적고 지울지 사람이 정한다. 지울 때 MCP 도구 이름·입출력이 바뀌면 멈추고 묻는다.
- Status: done

<a id="e2-22"></a>
## e2-22 · 배포 판정 DB 시험은 진짜 pgvector
- 요건: PC·dev는 쓰는 시험(임시 스키마 만들고 지움), prd는 읽기만. sqlite 대역과 그 갈림길(`has_conn`)은 지운다.
- 반영: 없음(사용자 11-08 결정 — 다음 작업).
- Status: todo

<a id="e2-23"></a>
## e2-23 · 모듈 경계 점검 줄이기
- 요건: import 경계(①~⑨·⑫)는 남기고 ⑩⑪ 흐름 분석을 글자 검색(분류 주석 없는 `os.environ`·`os.getenv`)으로 바꾼다.
- 반영: 없음(사용자 11-08 결정 — 다음 작업).
- Status: todo

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
