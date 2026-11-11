# 테스트·평가

[PRD.md](../PRD.md)의 카테고리 하나 — 변경을 어떻게 증명하나: 시험 층, 이미지 반입 판정, 스모크, 시험 자료, 답변 점검.

순서: 시험 층·반입 e2-02·e2-11·e2-08·e2-15·e2-21 → 스모크·시험 자료 e2-01·e2-13·e2-09 → 점검 e2-04·e2-05·e2-19·e2-20·e2-07 → 범위 e2-10·e2-17·e2-18 → DB 시험·경계 점검 e2-22·e2-23 → 코드와 다른 점.

<a id="e2-02"></a>
## e2-02 · 시험 층과 기준선
- 이유: 반입 판정은 네트워크 없이 이미지 안에서 돌아야 한다.
- 규칙:
  1. `tests/server/`(이미지 반입 관문 — `python -m pipeline.cli selftest`가 `tests/runner.py`로 실행, PG 말고는 외부 접속 없음 — [e2-22](#e2-22)) · `tests/general/`(PC 전용: PG, Docker, 느린 것 — pytest).
  2. 알려진 실패 목록: 반입 `deploy/release/known_fail.txt`, PC `tests/conftest.py` `GENERAL_KNOWN_FAIL`. 목록에 있는 시험이 통과하면 XPASS 경고(목록에서 지움).
  3. PC 시험 사례(자식 프로세스)는 개발자 루트 `settings.yaml`을 읽지 않는다 — `pipeline/cli.py` `case_env`가 시험 전용 바탕(`run_env: local`과 부모의 PG 접속만, 다른 접속·키 없음)을 준다. 실 PG가 있어야 판정되는 사례만 `_PC_SETTINGS_CASES`(지금 빔).
- 기준선(11-08, slim/load — 0.3.0 + 압축 원본 풀기·문서 안 문서 꺼내기 pl-63·pl-65 · 옛 오피스 검사기 하나로 pl-66 · 실버만 게시 상태 기록 pl-68 · 대표 결과 교차 병합·엑셀 날짜 표기 통일 pl-67 · 검색 MCP 동시 요청 mc-09 · 배포 판정 DB 시험 실 pgvector e2-22): `selftest` 113개 모두 통과(시험 함수 SKIP 0 — e2-22 뒤) · `pytest tests/` 177 통과 · 0 건너뜀 · 알려진 실패 0(두 목록 모두 빔) · FINGERPRINT `50588adec5d6d525` · code_fp p0 `e46c37a6e03f` · p1 `7aaabd66a297` · r `16e085b9ff38` · s `ddaf805dc00a`(기록용 — 0.3.0과 달라 서버는 다시 처리, refactor.md C-114 · e2-22에서 공용 `settings.py`·`layout.py` 설명이 바뀜) · 엔진 지문(`engine_code_fp`, 기록용): anydoc `01d0d7813c77` · archive `563e19556b61`(새 엔진) · docx2python `9ba622227470` · html_stdlib·mhtml·msg_extract `6b86d3b876c3` · hwpx `1ce4058a3a0a` · kreuzberg `e7797391d046` · markitdown `c6263c0c0984` · office `3a5c3859de9c` · plaintext `e61fe9d86b40` · pymupdf `8611e97ce9ec` · qwen_vlm `a0fd63c5062a`(엔진 폴더는 그대로 — 함께 셈하는 `pipeline/shared/vlmcall.py`의 설정 이름이 바뀜) · rapidocr_ko `1e08f27b5ddd`.
- #113 재배치 뒤 기준선(11-10, develop `73ac9401` 위 Redis 큐): `selftest` 114/114 통과(시험 함수 SKIP 0) · `pytest tests/` 180 통과 · 0 건너뜀 · 알려진 실패 0. 바로 위 develop 기록(113/113 · 177 통과)에서 서버 Redis 큐 시험 1개와 PC Redis 통합·호스트 시험 2개가 늘었다. 실제 시험 PG `127.0.0.1:55433`·Redis `127.0.0.1:56379`로 확인했다. FINGERPRINT `50588adec5d6d525` 그대로 · code_fp p0 `7045fca5b2b7` · p1 `9af0ab324470` · r `28b358e02aa3` · s `e2346d4a3187`(설정 공용 의존 변경으로 서버 전체 재처리 — [C-116](../refactoring/refactor.md), 새 이미지 버전 필요). 엔진·핸드오프·프롬프트 파일 바이트는 develop 그대로다.
- #174 DLQ 적재·관리 범위 정리 뒤 기준선(11-11, october-03/feature-dlq 미커밋): `selftest` 115/115 통과(실패 0·시험 함수 SKIP 0) · `pytest tests/` 184 통과 · 실패 0 · 0 건너뜀 · 알려진 실패 0(두 목록 모두 빔). 자동 재시도 패스 시험을 제거하고 본 흐름 1회·pending 포함/dead 제외·3회 dead·수동 requeue·선행 하이픈 인자·성공/영구 뺌 뒤 기록 오류·명시 키 우선·NULL 메타데이터 보존·호스트만 DLQ 1회 기록·분류 실패 경고 전달·엔진 없는 rep 게시 제외의 종료 1을 확인했다. 이전 미커밋 재시도 패스 기준선 188개에서 pytest 직접 수집 사례 5개 제거·회귀 사례 1개 추가로 184개이며 서버 시험 모듈은 115개로 같다. HEAD를 `git archive HEAD`로 임시 폴더에 풀어 비교한 FINGERPRINT `50588adec5d6d525` · code_fp p0 `7045fca5b2b7` · p1 `9af0ab324470` · r `28b358e02aa3` · s `e2346d4a3187`는 현재와 모두 같다. DLQ로 인한 추가 전체 재처리는 없다. 코드 폴더만 교체하며 applog 판 0005 선적용이 필수다([C-119](../refactoring/refactor.md)). 엔진·핸드오프·프롬프트 파일 바이트는 HEAD 그대로다.
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
- 파일: `deploy/release/{build_ship.sh,selftest_gate.sh}`, `docs/operations/server-guide.md`.
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
- 반영: 11-08 slim/load — `common/store/pg_standin.py`·`has_conn` 갈림길 삭제(앱에 sqlite 대역 없음 — PC도 PG 필수). 시험 도우미 `tests/server/common/pgcase.py`(임시 스키마 `test_<임의 8자>` — `test_`인지 확인 뒤 DROP, `db_write_allowed()` local·dev만 참, prd는 `need_write()`가 SKIP). `tests/runner.py`가 SKIP을 FAIL로 세지 않고 selftest 요약에 `시험 함수 SKIP N`. 읽기 시험 `tests/server/common/test_pg_read.py`(접속·vector 확장·판 번호 끝·표·색인·검색 1회, 세션 읽기 전용). PG에 못 붙으면 DB 사례 FAIL(이유를 적음). 판정 명령: `host_ctl.sh`·`build_ship.sh`가 설정 파일·`--network host`·`RUN_ENV`를 넣는다(server-guide §5-5).
- QA: `python -m pipeline.cli selftest` 113/113 · `RUN_ENV=prd` 모의(이주한 임시 스키마)에서 쓰는 사례 SKIP·`test_pg_read` 통과.
- Status: done

<a id="e2-23"></a>
## e2-23 · 모듈 경계 점검 줄이기
- 요건: import 경계(①~⑨·⑫)는 남기고 ⑩⑪ 흐름 분석을 글자 검색(분류 주석 없는 `os.environ`·`os.getenv`)으로 바꾼다.
- 반영: `common/check/check_modules.py` `env_lines`·`env_violations` — 앱 코드(common·pipeline·mcp_server)만 본다. ⑩ 코드(주석·문자열 빼고)에서 `os.`·`_os.` 뒤 `environ`·`getenv` 등을 쓰는 줄은 그 문장이나 바로 위 주석 줄에 분류 주석 `env 남김 — <분류>`가 있어야 한다. ⑪ `env`가 든 줄에서 설정 이름을 글자로 env 사전 키·`env[…]`·`pop`·`setdefault`·`putenv`에 쓰면 위반(분류 `라이브러리`·`시험`·`호스트 도구`는 허용). 잡지 않는 것: `from os import environ`·다른 os 별칭, `dict(os.environ, X=…)` 키워드 꼴, 변수에 담은 이름(`for k in (…): env.pop(k)`), `env`가 안 든 이름의 사전을 나중에 자식에 넘기는 꼴, `tests/`·`validation/`·`deploy/`.
- QA: `tests/server/common/test_check_modules.py`(`ENV_CASES` 표 · 심은 위반 `pipeline/v_env.py`·`common/v_child.py`) · `python -m common.check.check_modules` · "모듈 경계 통과".
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
