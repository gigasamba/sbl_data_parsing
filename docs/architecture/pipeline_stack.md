# 엔진 구성(pipeline_stack) — 파일

엔진 구성(형식마다 파싱 엔진 · 청킹 · 임베딩 · 검색 방식 · 상위 k)이 어디에 있고 어떻게 바꾸는지. 파싱 규칙은 [prd/transform.md#pl-03](../prd/transform.md#pl-03).

## 1. 어디서 읽나

| | 파일(서버·PC 같음 — 두 이미지에 다 들어 있음) | 다른 파일을 쓰려면(설정) |
|---|---|---|
| 엔진 구성 | [`resources/config/pipeline_stack.json`](../../resources/config/pipeline_stack.json) | `common.paths.stack_file` |
| 못 읽을 때 | **시작 거부 — 종료 코드 2**(파일 없음·JSON 오류·모양이 틀림 — 한 줄 안내, 값은 찍지 않음) | |

- 읽는 곳은 `common/store/db/cfgfile.py` 한 곳이다. 읽을 때 pydantic `StackFile`로 모양을 검사한다. `body_sha` = 정규 JSON(키 정렬·공백 없음·UTF-8)의 sha256 — 같은 구성이면 서버·PC가 같은 값이다.
- 프로세스마다 한 번 읽어 캐시한다. 검색 MCP 서버는 시작 때만(파일을 바꾸면 다시 띄움), 파싱 서비스(`pipeline.parse_service`)는 작업마다 다시 읽는다.
- 파싱·검색 MCP 컨테이너는 엔진 구성을 읽으려고 PostgreSQL에 접속하지 않는다.

## 2. 파일 모양

- `name`(예 `dev-v1`) · `parse`(형식 키 → 엔진 목록 — 문서마다 그 엔진들이 동시에 돎) · `source` · `embed` · `chunk` · `graph` · `retrieve` · `k`, 선택 `updated` · `client_aliases`(`common/core/terms.py`가 읽음 — 지금 파일에 없음).
- 형식 키는 확장자, PDF는 `.pdf_text`·`.pdf_image`.

## 3. 바꾸기·되돌리기·보기

| 할 일 | 방법 |
|---|---|
| 바꾸기 | 저장소의 파일을 고쳐 커밋 → 서버에는 **코드 폴더 바꾸기**로 보낸다([release-and-patch.md](../operations/release-and-patch.md) §1) |
| 되돌리기 | git으로 이전 파일로 되돌려 다시 코드 폴더를 바꾼다 |
| 보기 | `show-stack`(PC `python -m pipeline.cli show-stack` · 이미지 `data-pipeline` 컨테이너) — 이름·sha·파일 경로와 내용 요약 |

- **이미지에 없는 엔진 거부:** `parse` 목록의 엔진마다 등록부(`pipeline/extract/engines`)에 있고 설치(REQUIRES 모듈·도구)됐는지 — 파이프라인 진입점(`pipeline.cli`·`pipeline.parse_service`)이 시작 때 `pipeline.engine_stack.resolve()`로 검사한다(어긋나면 종료 2). 모델 주소 설정(REQUIRES_ENV)은 보지 않는다. 검색은 `retrieve`·`k`만 쓴다.
- `show-stack`은 실행 기록을 `/app/output/logs`에 쓰므로 `/app/output`이 읽기 전용인 `mcp-server` 컨테이너에서는 종료 2다 — `data-pipeline` 컨테이너에서 본다.
- **파싱과 구조화가 같은 구성:** 호스트 `run_docs.py`는 시작 때 `data-pipeline` 컨테이너 안에서 `show-stack`을 한 번 돌려 파일이 읽히는지 확인한다(못 읽으면 멈춤).
- **층과 code_fp:** 층 파일 `run_engines`·`mail_attachments`·`build_rep`·`build_bundle`은 `pipeline.config.stack()`으로 같은 파일을 읽는다. 파일 읽기 코드(`cfgfile`)는 층의 의존이 아니라 구성을 바꿔도 code_fp가 그대로다. `--stack <파일>`(`represent`·`build_bundle`)은 PC 실험·시험 전용이다. 묶음 `meta.json`의 `stack_conf`에 구성이 남는다.
- **형식 더하기:** 엔진 `parser.py`의 `FORMATS`는 두고 등록부 `pipeline/extract/engines/registry.py`의 `EXTRA_FORMATS`에 더한 뒤 구성 파일에 형식 키를 넣는다([prd/transform.md#pl-45](../prd/transform.md#pl-45)).
