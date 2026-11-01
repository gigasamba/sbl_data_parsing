# AI 지시서(지시서 패키지)

LLM·VLM을 **부르는** 단계의 지시서 패키지 16개(`resources/prompts/` 15개 + `valid_env/answer_test/`의 `rag_qa` — 10-29 파싱 판단 에이전트 4개·`query_decompose`, S11 `research_check`, 10-30 `wiki_term_draft`·`triple_extract`·`figure_chart_raster`·`diagram_arrows`를 지움 — e2-18)를 한 표로 모았다. 검색·집계·청킹처럼 모델을 부르지 않는 결정적 단계는 지시서가 아니라 코드다(맨 아래 "도구" 표).
S2(10-26, refactor_plan D-019 — T-01)에 패키지마다 있던 `README.md` 26개와 폴더 설명(`common_tools/prompts/README.md`)을 이 문서 하나로 합쳤고, `cases.json`은 `tests/fixtures/prompts/<앱>/<패키지>.json`으로 옮겼다(읽는 곳이 없어 10-29에 지움 — `refactor.md` C-63). 호출부 경로는 S2 시점 코드 자리로 고쳤다(옛 README의 `dev/…`·`modules/…`·`deploy/data_parsing/…`는 낡은 경로였다).

## 1. 자리와 찾는 순서

| 자리 | 무엇 | 들어가는 이미지 |
|---|---|---|
| `resources/prompts/common/<패키지>/` | 여러 단계·이미지가 함께 쓰는 지시서, 공용 꼬리 `_common/` | 모든 이미지(`resources/` 폴더째) |
| `resources/prompts/pipeline/<패키지>/` | 파싱·구조화·평가 지시서(옛 `data_etl/agent/`) | 모든 이미지 |
| `resources/prompts/mcp/<패키지>/` | 검색 MCP 지시서(옛 `data_retrieval/prompts/`) — 11-01 지금은 비어 있음(`research_judge`·`agg_llm_route` 지움) | 모든 이미지 |

- 찾는 자리는 `common/core/paths.py` `resolve_agent_dir()` 한 곳이다. 순서는 ① `resources/prompts/common` ② `resources/prompts/pipeline` ③ `resources/prompts/mcp` ④ `validation/e2e`(`triple_extract` — PC 전용, S6a · 이미지에는 폴더가 없어 건너뜀) ⑤ `valid_env/answer_test`(`rag_qa` — PC 전용 데이터, S10에 `validation/e2e`로 옮겼다가 10-29 사용자 결정으로 되돌림 · 이미지에 없음) ⑥ 시험 고정물(`dev_tools/unit_test/fixtures` — 이 저장소에는 없음). 패키지 이름은 겹치지 않아 순서가 결과를 바꾸지는 않지만, 결정적이어야 캐시·로그가 재현된다.
- `resources/`는 저장소 루트 바로 아래이고, 이미지 안에서는 `/app/deploy/resources`다(`paths.RES_ROOT` = 코드 패키지들이 import되는 자리의 `resources/`).

## 2. 패키지 구성

- `agent.json`(manifest — `model_role`·`output_schema`·`common_tail`·`agentic`·`budget`·`local_tools`) · `agent.py`(`create_agent(model, tools)` → `LlmAgent(instruction="", mode="single_turn")`) · 지시문 `prompt.md`(1개) 또는 `<prompt_id>.md`(여러 개 — 지금은 그런 패키지가 없음, S5a에 지운 `research_decompose`가 `decompose.md`·`decompose_context.md`를 썼음 · 로더 `common/ai/agent_prompts.py`는 그대로 지원) · 여러 턴 패키지(`parse_agent`·`parse_decide`·`parse_decide_vlm`)는 설계 절 `instructions.md`.
- **지시문:** `common/ai/agent_prompts.py` `load(agent_id, prompt_id)`가 읽어 호출부 모듈 상수를 만든다. 찾는 순서는 ① 패키지에 지시문이 하나면 `prompt.md` ② `<prompt_id>.md` ③ 옛 `prompts/<prompt_id>.md`(한 판 폴백). `.format()` 자리표시는 호출부가 채운다. 글자는 바이트 그대로 두고(지시문 지문 — CLAUDE.md §4), 줄끝은 LF다(`.gitattributes`).
- **지시서 캐시 열쇠:** `common/ai/adk.py` `_package_digest()` — 패키지 폴더 안 모든 파일의 상대 경로·sha256을 다시 해시한다(옛 `agent_platform.pipeline`과 같은 값, I6). 패키지 모듈 이름·로그에 들어간다. 패키지 안 파일을 더하거나 빼거나 고치면 바뀐다 — S2에서 `README.md`·`cases.json`이 빠져 한 번 바뀌었다(`refactor.md` C-08). 모델 응답 캐시 열쇠(모델·메시지 해시)는 지시문 글자가 같으면 그대로다.
- **output_schema:** JSON을 돌려주는 패키지는 `agent.json`에 `output_schema`를 둔다(호출부 파서가 기대하던 키·형식 그대로, 더 엄격하지 않게). `adk.complete(..., agent=...)`가 응답을 이 스키마로 검사하고, 어긋나면 원 메시지 + 안내 한 줄로 1회만 다시 묻는다(새 메시지라 원 캐시는 그대로). 그래도 어긋나면 호출부 기본값 처리에 맡긴다. 집계는 `adk.schema_stats()`(`invalid`·`retry_ok`·`retry_failed`). `LLM_FAKE=1` 경로(`common/ai/llm.py`)는 `adk.complete`를 거치지 않아 검사 대상이 아니다.
- **공용 꼬리(ADK14 P1, 인젝션 방어):** `resources/prompts/common/_common/tail.md`(패키지 아님 — 꼬리 파일만) — 자료 속 지시 무시·지어내기 금지·형식 준수 3줄을 `load()`가 지시문 **맨 끝**에 붙인다. `agent.json` `common_tail`: 칸 없음 = `tail.md` · `false` = 안 붙음 · `"free_text"` = `tail_free.md`(JSON 전용 3번째 줄을 뺀 것 — 출력이 자유 글인 패키지). 자료를 문자열 이어붙이기로 템플릿 뒤에 붙이는 호출부는 `load()` 대신 `template()`(꼬리 없음) + 자료 + `tail(agent_id)`를 써서 꼬리가 항상 자료 뒤에 오게 한다(아래 표 "꼬리" 칸 `template+tail`).
- **실행:** `adk.py` `_load_pipeline_agent`·`_run_once`·`_run_agentic`(I6 임시 대체 구현 — 옛 `agent_platform`은 D-013으로 지움). `complete(..., agent=<id>)`가 가드·캐시·재시도·사용량·형식 검사를 감싼다. 1회 호출 패키지는 local_tools가 없다(되돌이·분기는 호출자 파이썬 코드).
- **사례:** 옛 패키지 `cases.json`(S2에 `tests/fixtures/prompts/`로 옮김)은 읽는 코드·테스트가 없어 10-29에 지웠다(사용자 — `refactor.md` C-63).

## 3. 패키지 표

호출부는 지금 코드 자리다(S3~S10에 `common/`·`pipeline/`·`mcp_server/`·`validation/e2e/`로 옮기며 함께 고침). 꼬리: 기본 = `tail.md`, free = `tail_free.md`, `template+tail` = 호출부가 직접 꼬리를 붙임. 스키마: `agent.json` `output_schema` 유무.

| 패키지 | 자리(`resources/prompts/…`) | 모델 역할 | 무엇 | 입력 → 출력 | 호출부 | 꼬리 · 스키마 |
|---|---|---|---|---|---|---|
| `doc_summary` | `common/` | llm | 문서 본문을 한국어 3문장 이내로 요약 | 지시문(시스템) + 문서 본문 앞부분(사용자) → 요약 글자 | `pipeline/transform/structure/build_bundle.py` `llm_summary()` · `pipeline/transform/represent/agent_tools.py` `summarize_document()` | free · 없음 |
| `figure_describe` | `common/` | vlm | 그림 1장 → 검색용 기록(종류·요약·글자·값·연결·표) | 그림 PNG(data: URL) + 지시문(사용자, 생각 끔) → figure-v1 JSON | `pipeline/transform/figures/figures.py` `vlm_fig()`(`P_FIGJ`) | 기본 · 있음 |
| `page_transcribe` | `common/` | vlm | 스캔·이미지 쪽 1장 → 마크다운(OCR 교차 확인용) | 쪽 PNG + 지시문(사용자, 출력 상한 없음) → 마크다운 | `pipeline/transform/figures/vlm_page.py` `vlm_page()`(`P_PAGE`) | free · 없음 |
| `rag_qa` | (`valid_env/answer_test/` — PC 전용, S10에 `validation/e2e/`로 옮겼다가 10-29 되돌림) | llm | 검색 MCP 도구(`search`·`edw_meta`·`query_edw`)를 스스로 골라 근거를 찾고 숫자마다 인용을 붙여 답함(agentic — `max_turns` 12, 로컬 도구 `verify_citations`: 답의 숫자가 인용 `quote`에 있고 그 quote가 이번 질문의 검색 근거에 있는지) | 질문(사용자) → `{answer, status: found\|partial\|not_found, citations}` | `validation/e2e/answer_gen.py`(`common.ai.adk.run_agent(per_turn_admit=True)` — 도구 함수·근거 pool은 호출자, 지시문 `instructions.md` + 출력 스키마, 옛 패키지 README는 S10에 지움) | 없음(instruction에 지시문) · 있음 |
| `figure_overlay` | `pipeline/` | vlm | 겹친 개체 묶음(그림 + 글상자·화살표·도형) 1장 → 검색용 기록(F12) | 묶음 union bbox 크롭 + 지시문(생각 끔) → figure-v1 JSON | `pipeline/transform/figures/figures.py` `vlm_fig_overlay()`(`P_FIGOVERLAY`) | 기본 · 있음 |
| `mermaid_check` | `pipeline/` | vlm | (부르는 코드는 11-01에 지움 — e2-10, 지시서 시험 `test_agent_prompts`의 예시로만 남음) `gold_draft`가 옮긴 흐름도를 원본 이미지에 블라인드 질문으로 2차 확인 | 쪽 PNG + `template()` + 단계 이름 목록 + `tail()` → `{"is_flowchart", "next"}` | `pipeline/eval/gold_draft.py` `_vlm_check_mermaid()`(끄기 `GOLD_DRAFT_MERMAID_CHECK=0`) | 기본(template+tail) · 없음 |
| `nested_figure` | `pipeline/` | vlm | 쪽 전체 그림 안의 자식 그림 bbox 찾기(F7) | 쪽 그림 + 지시문 → `{"regions": [{bbox, kind, …}]}` | `pipeline/transform/figures/nested.py` `bbox_regions()`(`P_BBOX`) | 기본 · 있음 |

시험 고정물(`example_agentic`·`example_agentic_vlm_sub` — `tests/server/common/test_adk.py`(S9 전 `adk.py` selftest)의 `run_agent` 묶음)은 upstream `dev_tools/unit_test/fixtures/`에 있고 이 저장소에는 없다. 없으면 시험이 그 묶음을 건너뛴다.

## 4. 패키지별 메모 (옛 README에서 표에 안 들어간 것)

- **`figure_overlay`** — 출력 스키마는 `figure_describe`와 같고(kind/summary/text/values/edges/table_md), 지시문이 "위 개체는 아래 그림을 설명할 수 있다"는 관계를 읽게 한다. 캐시 이름 `figoverlay` — 같은 그림이라도 `figure_describe`와 다른 열쇠.
- **`mermaid_check`** — 옮긴 화살표 목록은 보여 주지 않고 단계 이름만 준다(앵커링 방지) → 단계별 '나가는 화살표' 답과 Mermaid를 코드로 대조. 흐름도가 아닌 그림이면 `is_flowchart=false` → Mermaid 블록을 뺀다.
- **`table_struct_judge`** — 결정적 결과를 먼저 계산하고 판정자는 **승격만**(0 → 1) 한다. 가드(`NO_PAID_CALLS`·`LLM_FAKE`·내부망 전용)는 `common.ai.llm.chat()`이 집행(`allow_external`을 주지 않아 내부망 LLM만). 판정자 호출 실패는 조용히 "승격 안 함". `vlm` 모드는 아직 TODO.
- **`doc_summary`** — 호출부(LLM 묶음 요약)는 op-08(10-30)에 지웠다(시험 `test_agent_prompts`·`test_paths`가 free_text 꼬리 예시로 씀). `parse_shadow`·`agg_llm_route`·`research_judge`는 11-01에 지움(호출부 없음). 지시문 묶음은 프롬프트 바이트 규칙과 시험(`test_paths`·`test_adk`·`test_agent_prompts`)이 읽어 남긴다.

## 5. 도구(결정적 — 모델 호출 없음)

| 이름 | 역할 | 위치 |
|---|---|---|
| `do_search` / `do_aggregate` | 벡터·BM25·그래프 검색·SQL 집계 | `mcp_server/services/search/search_svc.py` · `internal_docs.py`(도구 등록은 `mcp_server/routers/` — MCP 도구 계약, CLAUDE.md §4) |
| `split_question` / `keep_context` / `gather` | 하위 질문 검색어 만들기·병합(LLM 없이) | `mcp_server/services/search/decompose.py` |
| `compare` / `value_check` | 그림 기록 ↔ VLM 추출 결정적 대조 | (`figure_review.py`는 11-01에 지움) · `pipeline/transform/represent/context.py` |
| `embed_texts` | 임베딩 호출(역할 `embed` — ADK 역할 아님) | `common/ai/embed.py` |
