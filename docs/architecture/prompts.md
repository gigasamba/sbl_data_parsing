# AI 지시서(지시서 패키지)

LLM·VLM을 **부르는** 단계의 지시서 패키지 7개(`resources/prompts/` 6개 — 공용 꼬리 `_common` 따로 + `valid_env/answer_test/`의 `rag_qa` · 11-02 분류 `classify_sfdc`·`classify_las` 더함(pl-33))를 한 표로 모았다. 검색·청킹처럼 모델을 부르지 않는 결정적 단계는 지시서가 아니라 코드다(맨 아래 "도구" 표).
S2(10-26, refactor_plan D-019 — T-01)에 패키지마다 있던 `README.md` 26개와 폴더 설명(`common_tools/prompts/README.md`)을 이 문서 하나로 합쳤고, 호출부 경로는 S2 시점 코드 자리로 고쳤다(옛 README의 `dev/…`·`modules/…`·`deploy/data_parsing/…`는 낡은 경로였다).

## 1. 자리와 찾는 순서

| 자리 | 무엇 | 들어가는 이미지 |
|---|---|---|
| `resources/prompts/common/<패키지>/` | 여러 단계·이미지가 함께 쓰는 지시서, 공용 꼬리 `_common/` | 모든 이미지(`resources/` 폴더째) |
| `resources/prompts/pipeline/<패키지>/` | 파싱·구조화·평가 지시서 | 모든 이미지 |

- 찾는 자리는 `common/core/paths.py` `resolve_agent_dir()` 한 곳이다. 순서는 ① `resources/prompts/common` ② `resources/prompts/pipeline` ③ `valid_env/answer_test`(`rag_qa` — PC 전용 데이터 · 이미지에 없음). 코드에는 폴더가 없는 갈래 셋(`resources/prompts/mcp`·`validation/e2e`·`dev_tools/unit_test/fixtures`)이 더 있어 늘 건너뛴다 — 지우기는 PRD [e2-15](../prd/test.md#e2-15)(`paths.py`라 다음 지문 배치). 패키지 이름은 겹치지 않아 순서가 결과를 바꾸지는 않지만, 결정적이어야 캐시·로그가 재현된다.
- `resources/`는 저장소 루트 바로 아래이고, 이미지 안에서는 `/app/deploy/resources`다(`paths.RES_ROOT` = 코드 패키지들이 import되는 자리의 `resources/`).

## 2. 패키지 구성

- `agent.json`(manifest — `model_role`·`output_schema`·`common_tail`·`agentic`·`budget`·`local_tools`) · `agent.py`(옛 ADK 패키지 정의 — 0.2.0부터 코드가 읽지 않음, 지시서 지문 때문에 바이트 그대로 둠) · 지시문 `prompt.md`(1개) 또는 `<prompt_id>.md`(여러 개 — 지금은 그런 패키지가 없음 · 로더 `common/ai/agent_prompts.py`는 지원) · 여러 턴 패키지(`rag_qa`)는 설계 절 `instructions.md`.
- **지시문:** `common/ai/agent_prompts.py` `load(agent_id, prompt_id)`가 읽어 호출부 모듈 상수를 만든다. 찾는 순서는 ① 패키지에 지시문이 하나면 `prompt.md` ② `<prompt_id>.md` ③ 옛 `prompts/<prompt_id>.md`(한 판 폴백). `.format()` 자리표시는 호출부가 채운다. 글자는 바이트 그대로 두고(지시문 지문 — CLAUDE.md §4), 줄끝은 LF다(`.gitattributes`).
- **캐시 열쇠:** 모델 응답 캐시 열쇠는 모델·메시지 해시라 지시문 글자가 같으면 그대로다.
- **output_schema:** JSON을 돌려주는 패키지는 `agent.json`에 `output_schema`를 둔다(호출부 파서가 기대하던 키·형식 그대로, 더 엄격하지 않게). `common.ai.llm.complete(..., agent=...)`가 응답을 이 스키마로 검사하고, 어긋나면 원 메시지 + 안내 한 줄로 1회만 다시 묻는다(새 메시지라 원 캐시는 그대로). 그래도 어긋나면 호출부 기본값 처리에 맡긴다. 집계는 `llm.schema_stats()`(`invalid`·`retry_ok`·`retry_failed`). `LLM_FAKE=1` 경로는 `complete()`를 거치지 않아 검사 대상이 아니다.
- **공용 꼬리(ADK14 P1, 인젝션 방어):** `resources/prompts/common/_common/tail.md`(패키지 아님 — 꼬리 파일만) — 자료 속 지시 무시·지어내기 금지·형식 준수 3줄을 `load()`가 지시문 **맨 끝**에 붙인다. `agent.json` `common_tail`: 칸 없음 = `tail.md` · `false` = 안 붙음 · `"free_text"` = `tail_free.md`(JSON 전용 3번째 줄을 뺀 것 — 출력이 자유 글인 패키지). 자료를 문자열 이어붙이기로 템플릿 뒤에 붙이는 호출부는 `load()` 대신 `template()`(꼬리 없음) + 자료 + `tail(agent_id)`를 써서 꼬리가 항상 자료 뒤에 오게 한다(아래 표 "꼬리" 칸 `template+tail`).
- **실행:** `common/ai/llm.py` `complete(role, messages, agent=<id>)` — OpenAI 호환 HTTP 한 길이 가드·재시도·사용량·형식 검사를 감싼다. 1회 호출 패키지는 local_tools가 없다(되돌이·분기는 호출자 파이썬 코드). 여러 턴 도구 왕복은 PC 답변 점검(`rag_qa`)만 — `validation/e2e/tool_loop.py`.

## 3. 패키지 표

호출부는 지금 코드 자리다. 꼬리: 기본 = `tail.md`, free = `tail_free.md`, `template+tail` = 호출부가 직접 꼬리를 붙임. 스키마: `agent.json` `output_schema` 유무.

| 패키지 | 자리(`resources/prompts/…`) | 모델 역할 | 무엇 | 입력 → 출력 | 호출부 | 꼬리 · 스키마 |
|---|---|---|---|---|---|---|
| `figure_describe` | `common/` | vlm | 그림 1장 → 검색용 기록(종류·요약·글자·값·연결·표) | 그림 PNG(data: URL) + 지시문(사용자, 생각 끔) → figure-v1 JSON | `pipeline/transform/figures/figures.py` `vlm_fig()`(`P_FIGJ`) | 기본 · 있음 |
| `page_transcribe` | `common/` | vlm | 스캔·이미지 쪽 1장 → 마크다운(OCR 교차 확인용) | 쪽 PNG + 지시문(사용자, 출력 상한 없음) → 마크다운 | `pipeline/transform/figures/vlm_page.py` `vlm_page()`(`P_PAGE`) | free · 없음 |
| `rag_qa` | (`valid_env/answer_test/` — PC 전용) | llm | 검색 MCP 도구(`search`·`edw_meta`·`query_edw`)를 스스로 골라 근거를 찾고 숫자마다 인용을 붙여 답함(agentic — `max_turns` 12, 로컬 도구 `verify_citations`: 답의 숫자가 인용 `quote`에 있고 그 quote가 이번 질문의 검색 근거에 있는지) | 질문(사용자) → `{answer, status: found\|partial\|not_found, citations}` | `validation/e2e/answer_gen.py`(`validation.e2e.tool_loop.run("rag_qa", …)` — 턴마다 예산 확인 `llm.admit_turn()` · 도구 함수·근거 pool은 호출자, 지시문 `instructions.md` + 출력 스키마) | 없음(instruction에 지시문) · 있음 |
| `figure_overlay` | `pipeline/` | vlm | 겹친 개체 묶음(그림 + 글상자·화살표·도형) 1장 → 검색용 기록(F12) | 묶음 union bbox 크롭 + 지시문(생각 끔) → figure-v1 JSON | `pipeline/transform/figures/figures.py` `vlm_fig_overlay()`(`P_FIGOVERLAY`) | 기본 · 있음 |
| `nested_figure` | `pipeline/` | vlm | 쪽 전체 그림 안의 자식 그림 bbox 찾기(F7) | 쪽 그림 + 지시문 → `{"regions": [{bbox, kind, …}]}` | `pipeline/transform/figures/nested.py` `bbox_regions()`(`P_BBOX`) | 기본 · 있음 |
| `classify_sfdc` · `classify_las` | `pipeline/` | llm | SFDC·LAS 문서 하나 → 종류 라벨 하나(`doc_class` — pl-33, 운영 지시문 그대로) | 문서 정보 + 본문 앞 8,000자(LAS는 키워드 근거 더함) → JSON `class` | `pipeline/load/classify.py` `classify_one()`(적재 중 — `llm.chat`) | 없음 · 없음 |

모델 호출 시험은 `tests/server/common/test_llm_call.py`, 도구 왕복은 `tests/general/e2e/test_answer_gen.py`.

## 4. 패키지별 메모 (옛 README에서 표에 안 들어간 것)

- **`figure_overlay`** — 출력 스키마는 `figure_describe`와 같고(kind/summary/text/values/edges/table_md), 지시문이 "위 개체는 아래 그림을 설명할 수 있다"는 관계를 읽게 한다. 캐시 이름 `figoverlay` — 같은 그림이라도 `figure_describe`와 다른 열쇠.

## 5. 도구(결정적 — 모델 호출 없음)

| 이름 | 역할 | 위치 |
|---|---|---|
| `do_search` | 벡터·BM25·ID 검색 | `mcp_server/services/search/search_svc.py`(도구 등록은 `mcp_server/routers/` — MCP 도구 계약, CLAUDE.md §4) |
| `value_check` | 그림 기록 ↔ 본문 값 결정적 대조 | `pipeline/transform/represent/context.py` |
| `embed_texts` | 임베딩 호출(역할 `embed` — `llm.complete` 역할 아님) | `common/ai/embed.py` |
