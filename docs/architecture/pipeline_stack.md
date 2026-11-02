# 엔진 구성(pipeline_stack)·원천 목록(sources) — 파일

엔진 구성(어느 형식을 어느 파싱 엔진 순서로 · 청킹 · 임베딩 · 검색 방식 · 상위 k)과 원천 목록(문서 위치를 읽을 회사 DB 표·열)이 어디에 있고 어떻게 바꾸는지. **서버(dev·prd)와 PC 모두 저장소의 파일을 읽는다**(사용자 11-01: struct 스키마를 코드에서 모두 없앰, 파일만 — D-031·pl-08). 옛 파일의 메모 칸(`storage`·`candidates_note`·`embed_note`·`parse_note`)은 이 문서 [§4](#4-메모--옛-pipeline_stackjson-메모-칸)로 옮겼다(D-017 — 읽는 코드 없음).

## 1. 어디서 읽나

| | 파일(서버·PC 같음 — 두 이미지에 다 들어 있음) | 다른 파일을 쓰려면(설정) |
|---|---|---|
| 엔진 구성 | `resources/config/pipeline_stack.json` | `ops.paths.stack_file` |
| 못 읽을 때 | **시작 거부 — 종료 코드 2**(파일 없음·JSON 오류·모양이 틀림 — 한 줄 안내, 값은 찍지 않음) | |

- 읽는 곳은 `common/store/db/cfgfile.py` 한 곳이다. 읽을 때 pydantic으로 모양을 검사한다(`common/store/db/cfgfile.py`의 `StackFile` — 원천 항목은 `common/core/sources.py` `_validate_entry` 한 곳). `body_sha` = 정규 JSON(키 정렬·공백 없음·UTF-8)의 sha256 — 같은 구성이면 서버·PC가 같은 값이다.
- 프로세스마다 한 번 읽어 캐시한다. 오래 도는 것: 검색 MCP 서버는 시작 때만(파일을 바꾸면 다시 띄움), 파싱 MCP 서비스(`mcp_parse_service`)는 작업마다 다시 읽는다.
- 파싱·검색 MCP 컨테이너는 엔진 구성을 읽으려고 PostgreSQL에 접속하지 않는다(PG가 없어도 시작한다). PG는 적재·검색에만 필요하다.
- 서버에 남은 옛 `struct` 스키마(판 표 `stack_version`·`source_version` 등 — 쓰이지 않음)는 코드가 읽지 않는다. 그대로 두거나 DB 담당자가 지운다.
- `common/core/terms.py`(인계 파일 — 지문 때문에 고치지 않음)는 `client_aliases`를 `resources/config/pipeline_stack.json` 파일에서 읽는다(지금 파일에 그 키가 없음).

## 2. 파일 모양

- 엔진 구성: `name`(예 `dev-v1`) + `parse`(형식 → 엔진 목록 — 문서마다 그 엔진들이 동시에 돎)·`source`·`embed`·`chunk`·`graph`·`retrieve`·`k`(+ 선택 `updated`·`client_aliases` · 비교 후보 `candidates` 칸은 0.2.0에 지움 — pl-46).
- 원천 목록: 항목 목록(`name`·`table`·`bucket`·`enabled`·`columns`).

## 3. 바꾸기·되돌리기·보기

| 할 일 | 방법 |
|---|---|
| 바꾸기 | 코드 폴더의 파일을 고쳐 커밋 → 서버에는 **오버레이 패치**로 보낸다([release-and-patch.md](../operations/release-and-patch.md)) |
| 되돌리기 | git으로 이전 파일로 되돌려 다시 패치 |
| 보기 | `show-stack`(PC `python -m pipeline.cli …` · 이미지 `docker run … data-pipeline <명령>`) — 이름·sha·파일 경로와 내용 요약 |

- **이미지에 없는 엔진 거부(D-017):** `parse` 목록의 엔진마다 등록부(`pipeline/extract/engines`)에 있고 설치(REQUIRES 모듈·도구)됐는지 — 파이프라인 진입점(`pipeline.cli`·`mcp_parse_service`)이 시작 때 `pipeline.stackcfg.resolve()`로 검사한다(어긋나면 시작 안 함, 종료 2). REQUIRES_ENV(모델 주소 설정)는 설치 문제가 아니라 보지 않는다. 검색은 `retrieve`·`k`만 쓴다. `show-stack`·`show-sources`는 실행 기록을 `/app/output/logs`에 쓰므로 `/app/output:ro`인 상주 `mcp-server` 컨테이너에서는 entrypoint 쓰기 확인에서 종료 2다 — `data-pipeline` 컨테이너(`trigger.sh`·`run_tool.sh`의 load 등)에서 본다(VS8b R-9).
- **파싱과 구조화가 같은 구성:** 파일은 오버레이 패치로만 바뀌므로 한 실행 안에서는 그대로다. 호스트 `run_docs.py`는 시작 때 파싱 컨테이너 안에서 `show-stack`을 한 번 돌려 파일이 읽히는지 확인한다(못 읽으면 멈춤).
- **층과 code_fp:** 층 파일 `run_all`·`attachments`·`represent`·`build_bundle`은 `pipeline.config.stack()`으로 같은 파일을 읽는다. 파일 읽기 코드(`cfgfile`)는 층의 의존이 아니라 구성을 바꿔도 code_fp가 그대로다. `--stack <파일>`은 PC 실험(`validation/e2e/model_matrix`)·시험 전용이다. 구성의 sha(`cfgfile.sha` — 키 정렬 정규 JSON)는 서버·PC가 같고, 묶음 `meta.json`의 `stack_conf`에 구성이 남는다(색인 재빌드용 `stackcfg.snapshot_bytes`는 0.2.0에 지움 — pl-46). `pipeline_version()`은 저장소 `VERSION`이다(회사 DB `AI.ParsingMeta.silver_version`·`gold_version`).

### 3-1. 지원 형식 더하기(pl-42, 사용자 10-30)

- `resources/config/pipeline_stack.json`에 `.jpeg`·`.tif`·`.tiff`·`.bmp`(`.png`·`.jpg`와 같은 엔진 — 0.2.0부터 `qwen_vlm` 하나, OCR 스위치 지움 — pl-46)·`.mhtml`(`.mht`와 같은 `mhtml`·`kreuzberg`)을 더했다. `.hwpx`(`hwpx`)는 원래 있었다. 엔진 코드는 바꾸지 않았다(다섯 형식 모두 엔진이 이미 읽음).
- 서버도 같은 파일을 읽으므로 따로 할 일이 없다(옛 `set-stack` 단계 없음 — `refactor.md` C-69 닫음).
- 파일에 없는 형식은 핵심 엔진 합집합으로 대체돼 돌기는 한다(+형식별 1회 로그).

## 4. 메모 — 옛 `pipeline_stack.json` 메모 칸

S8b 전 `resources/config/pipeline_stack.json`(10-07 `dev-v1`)에 있던 글자 그대로. 경로·이름은 그때 것이다(예: `deploy/data_parsing/engines/` → 지금 `pipeline/extract/engines/`).

- **`storage`** — OpenViking 기반 지식 그래프 + 원문 청킹 하이브리드
- **`candidates_note`** — (11-01: 이 목록을 쓰던 비교 명령 compare-parse는 지움 — e2-10, `candidates` 칸 자체는 0.2.0에 지움 — [transform-cleanup.md#pl-46](../prd/transform-cleanup.md#pl-46)) 옛 단계 1 비교 후보 = 선정 엔진 + 이 목록. 이미지는 qwen_vlm 필수(세 번째 독립 계열), EasyOCR 제외(정확도 0.67), MarkItDown은 메일 형식에선 쓰지 않음 · 이미지 형식에서 paddleocr 제외(사용자 10-07, PaddleOCR·Cognee·Docling 모델 캐시·EasyOCR 모델·Surya(marker) 캐시는 스택에서 뺌) — 남은 독립 계열 2개(rapidocr_ko·qwen_vlm)뿐이라 교차 확인 모수 적음(low_n), 세 번째 계열(tesseract — 내부 OCRVLM 엔진 ocr_vlm은 10-30 지움, pl-31)은 backlog DP6 — 사람 결정 대기 · L11(10-13) — 'tesseract'를 이 목록에서 뺌: 등록된 엔진 모듈이 없어(archive로 이동, registry.engines()에 없음) compare-parse가 매 문서마다 ImportError만 반복(run_all이 1회 확인·로그로 거르게 고쳤지만 애초에 없는 이름은 후보에 안 두는 게 더 명확) · 다시 넣으려면 `deploy/data_parsing/engines/tesseract/parser.py`(ENGINES·FORMATS·REQUIRES) 추가 뒤 이 배열에 이름을 도로 적기
- **`embed_note`** — 서버: qwen3-vl-embedding(내부망 임베딩 API, EMBED_BASE_URL·EMBED_MODEL) → 이 파일의 `embed`를 `api`로(옛 `set-stack --embed`는 11-01에 없앰 — 파일을 고쳐 오버레이 패치)
- **`parse_note`** — .ppt = kreuzberg·anydoc(MarkItDown은 .ppt 못 읽음) · .msg = msg_extract 주(본문 포함, extract-msg GPL-3.0 — 내부 사용, 배포 시 소스 공개 의무), kreuzberg 예비(헤더만) — 백로그 E8·E9, 2026-10-01
