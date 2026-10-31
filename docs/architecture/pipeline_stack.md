# 엔진 구성(pipeline_stack)·원천 목록(sources) — 판 표

엔진 구성(어느 형식을 어느 파싱 엔진 순서로 · 청킹 · 임베딩 · 검색 방식 · 상위 k)과 원천 목록(문서 위치를 읽을 회사 DB 표·열)이 어디에 있고 어떻게 바꾸는지. S8b(10-28 — D-017·D-031)부터 서버는 pgvector의 **판 표**, PC는 파일이다. 옛 파일의 메모 칸(`storage`·`candidates_note`·`embed_note`·`parse_note`)은 이 문서 [§4](#4-메모--옛-pipeline_stackjson-메모-칸)로 옮겼다(D-017 — 읽는 코드 없음).

## 1. 어디서 읽나

| | 서버(RUN_ENV dev·prd · 이미지 배치 — PC 시험 Docker 포함) | PC(`RUN_ENV=local` + 저장소 배치 — `paths.LOCAL_RUN`) |
|---|---|---|
| 엔진 구성 | `struct.stack_version`의 활성 판(`is_active`) | `common.paths.stack_file`(비우면 `resources/config/pipeline_stack.json`) |
| 원천 목록 | `struct.source_version`의 활성 판 | `common.paths.sources_file`(비우면 `resources/mappings/sources.json`) |
| 못 읽을 때 | **시작 거부 — 종료 코드 4**(PostgreSQL 없음·판 표 없음(migrate 전)·활성 판 없음·body_sha 어긋남) — git 기본 파일로 넘어가지 않는다(사용자 10-28 Q7) | 파일 오류 그대로 |

- 프로세스마다 한 번 읽어 캐시한다(`common.store.db.cfgtables.active`). 오래 도는 것: 검색 MCP 서버는 시작 때만(판을 바꾸면 다시 띄움), 파싱 MCP 서비스(`mcp_parse_service`)는 작업마다 다시 읽는다.
- 옛 서버 덮어쓰기 `$SERVER_ENV_DIR/sources.json`과 env `SOURCES_FILE` 우선순위는 없앴다(서버는 판 표 — 그 파일이 있으면 `set-sources --file`로 판을 넣음, `refactor.md` C-12).
- `common/core/terms.py`(인계 파일 — 지문 때문에 고치지 않음)는 `client_aliases`를 `resources/config/pipeline_stack.json` **파일**에서만 읽는다(지금 파일에 그 키가 없음 — 판 표 밖).

## 2. 판 표 (struct 판 `0002_struct` — 🔒 데이터 계약, 검토 등급 A)

두 표(`stack_version`·`source_version`)는 같은 모양이다. 판 행은 고치지 않는다 — 바꾸기 = 새 행 + 활성 옮기기(한 트랜잭션), 되돌리기 = 옛 판을 다시 활성으로(활성 표시·`activated_*`만 바뀜).

| 칸 | 형식 | 뜻 |
|---|---|---|
| `version_id` | SERIAL PK | 판 번호 |
| `name` | TEXT NOT NULL | 판 이름(엔진 구성 `name`, 예 `dev-v1` · 원천 목록 시드는 `seed`) |
| `body` | JSONB NOT NULL | 설정 전체 — 엔진 구성 = `parse`·`source`·`embed`·`chunk`·`graph`·`retrieve`·`k`·`candidates` · 원천 목록 = 항목 목록(`name`·`table`·`bucket`·`enabled`·`columns`). 모양 검사는 pydantic(`common/store/db/schemas/config_body.py` — 원천 항목은 `common/core/sources.py` `_validate_entry` 한 곳) |
| `body_sha` | CHAR(64) NOT NULL UNIQUE | 정규 JSON(키 정렬·공백 없음·UTF-8) sha256 — 같은 body는 한 판(다시 넣으면 그 판을 활성으로) |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | 활성 판 — 표마다 하나(`ux_<표>_active` — `WHERE is_active` 유일 색인) |
| `created_at`·`created_by`·`reason` | TIMESTAMPTZ DEFAULT now() · TEXT · TEXT | 넣은 때·사람·이유 |
| `activated_at`·`activated_by` | TIMESTAMPTZ · TEXT | 마지막으로 활성이 된 때·사람(되돌리기 기록) |

- 시드: 판 `0002_struct`(Alembic — `common/store/db/migrations/versions/0002_struct_config.py`)가 표를 만들며 판 1을 활성으로 넣는다 — 판 번호 붙인 사본 `resources/sql/0002_stack_seed.json`·`0002_sources_seed.json`(그때의 PC 파일 설정 칸 — 정규화 JSON 같음, 한 번 배포하면 고치지 않음). PC 파일은 그 뒤에도 고칠 수 있다.
- SQLite 대체(structdb)에는 이 표가 없다(PC는 파일).

## 3. 바꾸기·되돌리기·보기

| 명령(PC `python -m pipeline.cli …` · 이미지 `docker run … data-pipeline <명령>`) | 서버 | PC |
|---|---|---|
| `set-stack --parse ".pdf_text=pymupdf,kreuzberg;…"`·`--from-selection`·`--embed`·`--chunk`·`--graph`·`--retrieve`·`--k`·`--name` + **`--reason` 필수**·`--by` | 활성 판에서 시작해 바꾼 body를 새 판으로 넣고 활성으로(같은 body면 그 판을 활성으로) | 파일을 고침(지금처럼) |
| `set-stack --activate <판 번호> --reason …` | 그 판을 다시 활성으로(되돌리기) | 없음(파일 — git으로) |
| `show-stack [--history N]` | 활성 판 + 최근 판 목록 | 파일 |
| `set-sources --file <json> --reason …`·`--activate <판 번호>`·`--check-columns`(선택 — 회사 DB INFORMATION_SCHEMA로 표·열 이름이 있는지, 값은 안 읽음) | 새 판·활성 옮기기 | 파일을 고침 |
| `show-sources [--history N]` | 활성 판 + 최근 판 | 파일 |

- **이미지에 없는 엔진 거부(D-017):** `parse` 목록 ∪ `candidates`의 엔진마다 등록부(`pipeline/extract/engines`)에 있고 설치(REQUIRES 모듈·도구)됐는지 — `set-stack` 때(넣지 않음, 종료 2)와 파이프라인 진입점이 판을 읽을 때(시작 안 함, 종료 2) 둘 다. REQUIRES_ENV(모델 주소 설정)는 설치 문제가 아니라 보지 않는다. `mcp-server` 이미지는 등록부가 없어 `set-stack`을 거부하고, 검색은 `retrieve`·`k`만 쓴다. `show-stack`·`show-sources`도 실행 기록을 `/app/output/logs`에 쓰므로 `/app/output:ro`인 상주 `mcp-server` 컨테이너에서는 entrypoint 쓰기 확인에서 종료 2다 — `data-pipeline` 컨테이너(`trigger.sh`·`run_tool.sh`의 load 등)에서 본다(VS8b R-9).
- **파싱과 구조화가 같은 판(VS8b R-1 · C-50 · pl-32):** 호스트 `run_docs.py`는 시작 때 `python -m pipeline.stackcfg --version`으로 활성 판 번호를 한 번 받아 파싱(`--set STACK_VERSION=N`)·구조화(`--stack-version N`)에 같이 준다 — 그 실행의 모든 문서가 한 판. 동시에 `set-stack`·`set-sources`를 해서 진 쪽과 `set-stack`이 읽은 판이 쓰기 전에 바뀐 쪽은 넣지 않고 종료 2("다른 사람이 방금 판을 바꿈")다.
- **누가:** 서버에서는 `--by <사람>`을 늘 준다(없으면 컨테이너 안 이미지 계정 이름이 남음). 같은 body로 되돌리면(`set-stack` 결과가 옛 판과 같음) 새 행 없이 그 판을 활성으로 — 판 행의 이름·이유는 그대로, 이번 이유는 실행 기록(`runlog`)에만.
- **판 번호로 넘김(code_fp — Q10 · pl-32 사용자 10-30, 사본 파일 `_stack/stack-v*.json`·`STACK_SNAPSHOT` 없앰):** 파이프라인 진입점(`pipeline.cli`·`mcp_parse_service`·`load.index`·`eval.server_checks`)이 활성 판을 읽어 엔진을 검사하고 판 번호를 설정 칸 `STACK_VERSION`으로 자식에 넘긴다(이미 받았으면 그 판). 층 파일 `run_all`·`attachments`와 `represent`·`build_bundle`은 `pipeline.config.stack()`으로 그 판을 판 표에서 읽는다(`represent`·`build_bundle`은 `--stack-version N`도 받음) — 서버에서 판 번호 없이 읽으면 거부(종료 2), PC는 파일. 판 표를 읽는 코드(`cfgtables`)는 층의 의존이 아니라 판을 더하거나 고쳐도 code_fp가 그대로다. `--stack <파일>`은 PC 실험(`validation/e2e/model_matrix`)·시험 전용으로 남고 생산 경로는 주지 않는다(둘 다 주면 종료 2). 색인 재빌드 지문은 판의 정규 바이트(`stackcfg.snapshot_bytes` — 옛 사본과 같은 바이트, 키 정렬). 판 번호·sha는 묶음 `meta.json`의 `stack_conf`에 남는다. `pipeline_version()`(회사 DB `AI.ParsingMeta.pipeline_version` 칸)은 그대로 git 커밋 — 판 번호를 붙이지 않는다. 다시 볼 것은 `refactor.md` C-50.

### 3-1. 지원 형식 더하기(pl-42, 사용자 10-30)

- PC 파일 `resources/config/pipeline_stack.json`에 `.jpeg`·`.tif`·`.tiff`·`.bmp`(`.png`·`.jpg`와 같은 `rapidocr_ko`·`qwen_vlm` — OCR 엔진은 `pipeline.extract.ocr_engine`을 켤 때만)·`.mhtml`(`.mht`와 같은 `mhtml`·`kreuzberg`)을 더했다. `.hwpx`(`hwpx`)는 원래 있었다. 엔진 코드는 바꾸지 않았다(다섯 형식 모두 엔진이 이미 읽음).
- 판 1 시드(`resources/sql/0002_stack_seed.json`)는 고치지 않는다(배포한 판). 서버는 새 판으로 반영한다:
  `dc run --rm load set-stack --parse ".jpeg=rapidocr_ko,qwen_vlm;.tif=rapidocr_ko,qwen_vlm;.tiff=rapidocr_ko,qwen_vlm;.bmp=rapidocr_ko,qwen_vlm;.mhtml=mhtml,kreuzberg" --reason "pl-42 확장자 추가"` → `show-stack --history 3`으로 확인(되돌리기 `set-stack --activate <앞 판> --reason …`).
- 판에 없는 형식은 지금처럼 핵심 엔진 합집합으로 대체돼 돌기는 한다(+형식별 1회 로그) — 새 판을 넣어야 형식당 엔진 2개 규칙대로 돈다.

## 4. 메모 — 옛 `pipeline_stack.json` 메모 칸

S8b 전 `resources/config/pipeline_stack.json`(10-07 `dev-v1`)에 있던 글자 그대로. 경로·이름은 그때 것이다(예: `deploy/data_parsing/engines/` → 지금 `pipeline/extract/engines/`).

- **`storage`** — OpenViking 기반 지식 그래프 + 원문 청킹 하이브리드
- **`candidates_note`** — 단계 1 비교 후보 = 선정 엔진 + 이 목록(compare-parse --engines candidates). 이미지는 qwen_vlm 필수(세 번째 독립 계열), EasyOCR 제외(정확도 0.67), MarkItDown은 메일 형식에선 쓰지 않음 · 이미지 형식에서 paddleocr 제외(사용자 10-07, PaddleOCR·Cognee·Docling 모델 캐시·EasyOCR 모델·Surya(marker) 캐시는 스택에서 뺌) — 남은 독립 계열 2개(rapidocr_ko·qwen_vlm)뿐이라 교차 확인 모수 적음(low_n), 세 번째 계열(tesseract — 내부 OCRVLM 엔진 ocr_vlm은 10-30 지움, pl-31)은 backlog DP6 — 사람 결정 대기 · L11(10-13) — 'tesseract'를 이 목록에서 뺌: 등록된 엔진 모듈이 없어(archive로 이동, registry.engines()에 없음) compare-parse가 매 문서마다 ImportError만 반복(run_all이 1회 확인·로그로 거르게 고쳤지만 애초에 없는 이름은 후보에 안 두는 게 더 명확) · 다시 넣으려면 `deploy/data_parsing/engines/tesseract/parser.py`(ENGINES·FORMATS·REQUIRES) 추가 뒤 이 배열에 이름을 도로 적기
- **`embed_note`** — 서버: qwen3-vl-embedding(내부망 임베딩 API, EMBED_BASE_URL·EMBED_MODEL) → set-stack --embed api
- **`parse_note`** — .ppt = kreuzberg·anydoc(MarkItDown은 .ppt 못 읽음) · .msg = msg_extract 주(본문 포함, extract-msg GPL-3.0 — 내부 사용, 배포 시 소스 공개 의무), kreuzberg 예비(헤더만) — 백로그 E8·E9, 2026-10-01
