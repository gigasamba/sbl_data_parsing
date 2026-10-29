# AI 지시서(지시서 패키지)

LLM·VLM을 **부르는** 단계의 지시서 패키지 20개(`resources/prompts/` 18개 — 10-29 파싱 판단 에이전트 4개·`query_decompose` 삭제 + PC 전용 `validation/e2e/`의 `triple_extract`·`valid_env/answer_test/`의 `rag_qa` — S11에 `research_check` 삭제)를 한 표로 모았다. 검색·집계·청킹처럼 모델을 부르지 않는 결정적 단계는 지시서가 아니라 코드다(맨 아래 "도구" 표).
S2(10-26, refactor_plan D-019 — T-01)에 패키지마다 있던 `README.md` 26개와 폴더 설명(`common_tools/prompts/README.md`)을 이 문서 하나로 합쳤고, `cases.json`은 `tests/fixtures/prompts/<앱>/<패키지>.json`으로 옮겼다(읽는 곳이 없어 10-29에 지움 — `refactor.md` C-63). 호출부 경로는 S2 시점 코드 자리로 고쳤다(옛 README의 `dev/…`·`modules/…`·`deploy/data_parsing/…`는 낡은 경로였다).

## 1. 자리와 찾는 순서

| 자리 | 무엇 | 들어가는 이미지 |
|---|---|---|
| `resources/prompts/common/<패키지>/` | 여러 단계·이미지가 함께 쓰는 지시서, 공용 꼬리 `_common/` | 모든 이미지(`resources/` 폴더째) |
| `resources/prompts/pipeline/<패키지>/` | 파싱·구조화·평가 지시서(옛 `data_etl/agent/`) | 모든 이미지 |
| `resources/prompts/mcp/<패키지>/` | 검색 MCP 지시서(옛 `data_retrieval/prompts/`) · `research_judge`(D-019 ④) | 모든 이미지 |
| `validation/e2e/triple_extract/` | 평가 실험(LLM 그래프 모드 — `validation/e2e/graph_llm.py`, T-02로 `stages.py`에서 쪼갬) 지시서 — S6a에 쓰는 도구와 함께 옮김(D-019 ③) | 없음 — PC 전용(서버 이미지에 안 들어감) |

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
| `value_choice` | `common/` | vlm | 조각 재판독 후보 중 이미지에 보이는 값 하나 고르기(AD29 P3) | 크롭 PNG + 지시문(후보 목록 포함) → `{"answer": "<후보 하나 또는 NONE>"}` | `pipeline/transform/represent/reread_stage3.py` `_default_vlm_call()` | template+tail · 있음 |
| `research_judge` | `mcp/` | llm | 근거 조각이 하위 질문에 답하는지 판정 | 하위 질문 + 번호 붙은 근거 조각 → status/answer/cite JSON | 시험만 — `tests/server/common/test_adk.py`·`test_agent_prompts.py`·`test_paths.py`(S9 전 각 모듈 selftest · 호출부 `research.py`는 S5a 삭제 — D-025) | 기본 · 있음 |
| `triple_extract` | (`validation/e2e/` — PC 전용) | llm | 청크 글자 → (주어, 관계, 목적어) 삼중항(지식그래프 간선) | 지시문(시스템) + 문서명·청크 글자 → triples JSON | `validation/e2e/graph_llm.py` `build_llm_graph`(`_TRIPLE_SYSTEM`, 모듈 import 때 읽음 — `stages.build_graph("llm")`가 PC에서만 불러 등록, S6a) | 기본 · 있음 |
| `rag_qa` | (`valid_env/answer_test/` — PC 전용, S10에 `validation/e2e/`로 옮겼다가 10-29 되돌림) | llm | 검색 MCP 도구(`search`·`edw_meta`·`query_edw`)를 스스로 골라 근거를 찾고 숫자마다 인용을 붙여 답함(agentic — `max_turns` 12, 로컬 도구 `verify_citations`: 답의 숫자가 인용 `quote`에 있고 그 quote가 이번 질문의 검색 근거에 있는지) | 질문(사용자) → `{answer, status: found\|partial\|not_found, citations}` | `validation/e2e/answer_gen.py`(`common.ai.adk.run_agent(per_turn_admit=True)` — 도구 함수·근거 pool은 호출자, 지시문 `instructions.md` + 출력 스키마, 옛 패키지 README는 S10에 지움) | 없음(instruction에 지시문) · 있음 |
| `diagram_arrows` | `pipeline/` | vlm | 래스터 그림 속 화살표를 전부 세어 edges로(셀프체크: 화살표 개수) | 2~3배 확대 크롭 + 지시문(생각 끔) → `{"edges", "arrow_count"}` | `pipeline/eval/diagram_edges_score.py` `raster_stub_extract()`(`DIAGRAM_RASTER_VLM=1`일 때만) | 기본 · 있음 |
| `figure_chart_raster` | `pipeline/` | vlm | 래스터 차트 값을 단계식으로(눈금·격자 → 비율 → 보간) 읽기(F14 b) | 2~3배 확대 크롭 + 지시문 → `{y_ticks, log_axis, items}` | `pipeline/transform/figures/chart_values.py` `raster_chart_values()`(`RASTER_PROMPT` — 운영 파이프라인에 배선 안 됨, 시험은 가짜 `call_fn`) | 기본 · 있음 |
| `figure_extract` | `pipeline/` | vlm | 그림만 보고 독립 재추출(검토 루프 — 원본 기록은 안 보여 줌) | 그림 PNG + 지시문 + 근처 맥락·이전 지적 → figure-v1 JSON | `pipeline/transform/figures/figure_review.py` `extract()`·`_vlm_call(which="extract")`(`P_EXTRACT`) | template+tail · 있음 |
| `figure_judge` | `pipeline/` | vlm_judge | 독립 추출과 우리 기록의 자동 diff 감사(검토 루프 판정자) | 그림 PNG + 지시문 + 우리 기록·대조 결과·맥락 → items/verdict JSON | `pipeline/transform/figures/figure_review.py` `_vlm_call(which="judge")`(`P_JUDGE`) | template+tail · 있음 |
| `figure_overlay` | `pipeline/` | vlm | 겹친 개체 묶음(그림 + 글상자·화살표·도형) 1장 → 검색용 기록(F12) | 묶음 union bbox 크롭 + 지시문(생각 끔) → figure-v1 JSON | `pipeline/transform/figures/figures.py` `vlm_fig_overlay()`(`P_FIGOVERLAY`) | 기본 · 있음 |
| `gold_draft` | `pipeline/` | vlm | 쪽 이미지 + 파싱 참고 글 → 정답 초안 마크다운(GS2) | 쪽 PNG + `template()` + 참고 글 + `tail()` → 마크다운(병합 칸 채움·흐름도는 Mermaid) | `pipeline/eval/gold_draft.py` `_vlm_gold()` | free(template+tail) · 없음 |
| `mermaid_check` | `pipeline/` | vlm | `gold_draft`가 옮긴 흐름도를 원본 이미지에 블라인드 질문으로 2차 확인 | 쪽 PNG + `template()` + 단계 이름 목록 + `tail()` → `{"is_flowchart", "next"}` | `pipeline/eval/gold_draft.py` `_vlm_check_mermaid()`(끄기 `GOLD_DRAFT_MERMAID_CHECK=0`) | 기본(template+tail) · 없음 |
| `nested_figure` | `pipeline/` | vlm | 쪽 전체 그림 안의 자식 그림 bbox 찾기(F7) | 쪽 그림 + 지시문 → `{"regions": [{bbox, kind, …}]}` | `pipeline/transform/figures/nested.py` `bbox_regions()`(`P_BBOX`) | 기본 · 있음 |
| `parse_shadow` | `pipeline/` | llm | PA2 그림자 모드 — 규칙이 내린 결정 지점마다 "다음 행동" 제안만(기록만) | PA0 context·decisions 줄인 JSON → `{"proposals": [{step, action, reason, confidence}]}` | `pipeline/eval/parse_shadow.py` `_default_llm_complete()` ← `pipeline/transform/represent/shadow.py` `propose_llm()`(끄기 `PARSE_SHADOW=0`) | 기본 · 있음 |
| `qa_draft` | `pipeline/` | vlm | 쪽 이미지 → 표·그래프·흐름도 구조를 읽어야 맞출 수 있는 질문-답변 초안(QA1) | 쪽 PNG + `template()`(`{max_items}`) + `tail()` → `{"items": [...]}` | `pipeline/eval/qa_draft.py` `_vlm_qa()` | 기본(template+tail) · 없음 |
| `table_struct_judge` | `pipeline/` | llm | 표 구조 채점(TS1) 경계 표를 한 번 더 봐서 승격만 하는 보조 판정자 | 정답 표 + 출력 표(`{gold_table}`·`{out_table}`) → `{"pass", "reason"}` | `pipeline/eval/score_gold.py` `_table_judge_fn()._judge()`(켜기 `SCORE_TABLE_JUDGE=llm`) | 기본 · 있음 |
| `wiki_term_draft` | `pipeline/` | llm | 미등록 용어 1개의 사전 행 초안(자동 승인 없음 — status=draft) | 용어(사용자) → canonical/definition_ko 등 JSON | `pipeline/transform/structure/wiki_draft.py` `propose_term()`·`main()`(`_PROMPT`) | 기본 · 있음 |
| `agg_llm_route` | `mcp/` | llm | 집계(SQL 틀) 질문인지 검색 질문인지 분류 + 인자(고객·기간·지표·모양) 추출 | 분류 지시문 + 질문 → JSON(`aggregate.llm_plan`이 검증) | `mcp_server/services/search/aggregate.py` `llm_plan()`(`_AGG_LLM_PROMPT`) ← `mcp_server/services/search/internal_docs.py` `_agg_llm_complete()`(`SEARCH_AGG_LLM=1`, `detect()` 정규식이 못 걸렸을 때만) | 기본 · 있음 |

시험 고정물(`example_agentic`·`example_agentic_vlm_sub` — `tests/server/common/test_adk.py`(S9 전 `adk.py` selftest)의 `run_agent` 묶음)은 upstream `dev_tools/unit_test/fixtures/`에 있고 이 저장소에는 없다. 없으면 시험이 그 묶음을 건너뛴다.

## 4. 패키지별 메모 (옛 README에서 표에 안 들어간 것)

- **`value_choice`** — 답이 후보 목록 밖이거나 `NONE`이면 호출부가 미확인으로 둔다(값을 지어내지 않음, AD19 "지우지 않음"과 같은 원칙).
- **`figure_overlay`** — 출력 스키마는 `figure_describe`와 같고(kind/summary/text/values/edges/table_md), 지시문이 "위 개체는 아래 그림을 설명할 수 있다"는 관계를 읽게 한다. 캐시 이름 `figoverlay` — 같은 그림이라도 `figure_describe`와 다른 열쇠.
- **`figure_chart_raster`** — `figure_extract`(눈대중 values)와 별개 패키지. 실 VLM 호출 없음(`call_fn`은 시험에서만 가짜로 주입 — CLAUDE.md §7 비용 규칙).
- **`diagram_arrows`** — 개발 중에는 가짜 모델만. 실 VLM 호출은 비용 추정 + 사용자 승인 뒤(CLAUDE.md §7).
- **`gold_draft`** — `page_transcribe`와 별도 지시문·캐시 열쇠라 이 패키지를 바꿔도 파싱 VLM 캐시·동작은 그대로다.
- **`mermaid_check`** — 옮긴 화살표 목록은 보여 주지 않고 단계 이름만 준다(앵커링 방지) → 단계별 '나가는 화살표' 답과 Mermaid를 코드로 대조. 흐름도가 아닌 그림이면 `is_flowchart=false` → Mermaid 블록을 뺀다.
- **`qa_draft`** — 유형: table_cell(행×열 칸) · chart_value(x → y, 어림이면 범위 + confidence low) · flow_next · flow_input · flow_order.
- **`table_struct_judge`** — 결정적 결과를 먼저 계산하고 판정자는 **승격만**(0 → 1) 한다. 가드(`NO_PAID_CALLS`·`LLM_FAKE`·내부망 전용)는 `common.ai.llm.chat()`이 집행(`allow_external`을 주지 않아 내부망 LLM만). 판정자 호출 실패는 조용히 "승격 안 함". `vlm` 모드는 아직 TODO.
- **`parse_shadow`** — 제안은 저장·집계만 되고 파싱 결과·점수에는 손대지 않는다. `action`은 step마다 고정된 행동 목록(`shadow.STEP_ACTIONS`, "keep" = 규칙 그대로) 중 하나만 유효하고, 목록 밖이거나 decisions에 없는 step은 `shadow.parse_proposals`가 버린다. `shadow.py`는 adk를 모르고 `llm_complete` 콜백만 받는다(CLI가 `llm.chat(..., agent="parse_shadow")`를 주입). 캐시는 `llm.chat()`의 (모델·메시지·온도) 해시 그대로. `--mode rules`는 LLM 없이 규칙 결정을 "keep"으로 echo(배선 시험용).
- **`agg_llm_route`** — 인자는 기존 집계 틀(`aggregate._apply`)에만 대입하고 자유 SQL은 만들지 않는다(R1, AD42·AD45②). 거부(→ None, 검색 폴백): 확신 미달(`SEARCH_AGG_LLM_MIN`) · 모르는 고객/계약/모달리티 · window 날짜 형식 오류 · 지표 전부 거짓 · 고객·계약 둘 다 없음 · JSON 깨짐 · SQL처럼 보이는 글자(`_SQLISH_RE`) · route="search".
- **`research_judge`** — 호출부 `research.py`는 S5a(10-26)에 지웠지만(D-025), `tests/server/common/test_agent_prompts.py`·`test_adk.py`(S9 전 각 모듈 selftest)가 모든 이미지에서 이 id로 지시문 읽기·`model_role`·`output_schema` 가드를 시험해 남긴다. `resources/`는 폴더째 모든 이미지에 들어가므로 `mcp/`에 있어도 찾는다. 같이 쓰던 `research_decompose`·`research_rewrite`는 S5a에, 호출부 없이 자리 확인만 남았던 `research_check`는 S11(10-28, 사용자 — `refactor.md` C-25 ③)에 지웠다.

## 5. 도구(결정적 — 모델 호출 없음)

| 이름 | 역할 | 위치 |
|---|---|---|
| `do_search` / `do_aggregate` | 벡터·BM25·그래프 검색·SQL 집계 | `mcp_server/services/search/search_svc.py` · `internal_docs.py`(도구 등록은 `mcp_server/routers/` — MCP 도구 계약, CLAUDE.md §4) |
| `split_question` / `keep_context` / `gather` | 하위 질문 검색어 만들기·병합(LLM 없이) | `mcp_server/services/search/decompose.py` |
| `compare` / `value_check` | 그림 기록 ↔ VLM 추출 결정적 대조 | `pipeline/transform/figures/figure_review.py` · `pipeline/transform/represent/context.py` |
| `embed_texts` | 임베딩 호출(역할 `embed` — ADK 역할 아님) | `common/ai/embed.py` |
