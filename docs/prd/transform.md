# 변환 — 파싱·represent·그림·구조화

[PRD.md](../PRD.md) 카테고리. [extract.md](extract.md) 다음, [load.md](load.md) 앞: 엔진 구성 파싱(pl-03·pl-22·pl-43·pl-42·pl-45) → represent(pl-04·pl-36·pl-37) → 그림(pl-05) → 구조화(pl-06) → 분류(pl-33). 지문이 바뀌는 정리 묶음은 [transform-cleanup.md](transform-cleanup.md).

순서: pl-03 · pl-22 · pl-43 · pl-42 · pl-45 · pl-04 · pl-36 · pl-37 · pl-05 · pl-06 · pl-33 · pl-60.

<a id="pl-03"></a>
## pl-03 · 엔진 구성 파싱

### 무엇·왜
모든 형식을 잘 읽는 파서는 없다. 형식마다 정해 둔 엔진을 모두 돌리고 represent가 고른다.

### 규칙
1. 엔진 구성은 파일 하나 `resources/config/pipeline_stack.json`이다(설정 칸 없음) — 서버·PC 같은 파일. 모양·읽기·바꾸기는 [resources.md §1](../architecture/resources.md).
2. 문서마다 그 형식 키의 `parse` 목록에 있는 엔진을 **모두** 돌린다(하나씩 차례로 시도하지 않음).
3. 형식 키 = 확장자(소문자). 단 `.pdf`는 글자층이 쪽당 평균 20자 미만이면 `.pdf_image`(스캔), 아니면 `.pdf_text` — 판정은 `<out>/_types.json`에 크기·수정 시각과 함께 캐시한다. 판정 함수는 `pipeline.shared.pdf_kind.pdf_kind()` 하나 — 쪽 VLM의 문서 전체 스캔 판정(`scan_page_vlm.is_scan`)과 `parse_document`도 같은 함수를 쓴다(레인 분류 `doc_lane_group`의 앞 3쪽 규칙은 목적이 달라 따로).
4. 만약 형식 키가 구성에 없으면 → 그 확장자를 읽는 등록 엔진 모두(OCR 엔진 제외)로 돌리고 형식마다 한 번 로그를 남긴다.
5. 지원 형식 = 구성의 `parse` 키 43개: `.pptx` `.doc` `.docx` `.hwpx` `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp` `.eml` `.mht` `.mhtml` `.txt` `.html` `.htm` `.pdf_image` `.pdf_text` `.xls` `.xlsm` `.xlsx` `.ppt` `.msg` `.docm` `.pptm` `.rtf` `.csv` `.tsv` `.md` `.odt` `.ods` `.odp` `.xlsb` `.dotx` `.xltx` `.potx` `.ppsx` `.dot` `.xlt` `.pot` `.json` `.xml` `.log`. `.hwp`는 아직 아니다([pl-45](#pl-45)), 압축 파일은 지원하지 않는다.
6. 구성의 엔진이 등록부(`pipeline/transform/parse/engines`)에 없거나 설치되지 않았으면 → 시작하지 않는다(종료 2).
7. 파싱(`parse_engines`)은 입력 폴더의 파일을 그대로 문서로 본다 — 같은 내용 사본을 한 번만 돌려 복사하는 일과 확장자 거르기를 하지 않는다(중복 제외·미지원 거르기는 [pl-02](extract.md#pl-02)). 처리 엔진 없는 확장자 파일이 들어오면 엔진 후보가 없어 그 문서는 작업 0건이다. `--shard i/k`는 내용 sha256으로 문서를 나눈다.

### QA
- `tests/server/pipeline/test_engine_check.py` · `tests/server/pipeline/test_engine_run.py`.
- Status: done

<a id="pl-22"></a>
## pl-22 · 문서마다 엔진 병렬 · 시간 제한 · OCR 엔진 끔

### 무엇·왜
엔진 하나가 느리거나 죽어도 다른 엔진·문서를 막지 않게 한다. 큰 문서는 쪽 수만큼 시간을 받는다.

### 규칙
1. 문서마다 구성의 엔진을 동시에, 엔진마다 따로 떨어진 자식 프로세스 하나로 돌린다. 문서끼리는 `--workers`·`--procs`로 병렬.
2. 문서×엔진 제한 시간(초) = round(max(max(1, 쪽 수) × 쪽당 초, 첫 문서면 `tuning.extract.first_doc_min_timeout_sec`(60)) + `tuning.extract.engine_isolate_startup_sec`(10), 2). 쪽당 초 = VLM 엔진은 VLM 호출 1건 제한 `common.models.vlm.vlm_timeout_sec`(180), 그 밖 `tuning.extract.text_engine_page_timeout_sec`(10).
3. 시간을 넘기면 제한을 두 배로 한 번 더 돌리고, 그래도 넘으면 실패로 기록한다.
4. OCR 엔진 `rapidocr_ko`는 파싱 엔진으로 돌지 않는다 — 이미지·스캔 문서는 VLM 엔진 `qwen_vlm`만.
5. 글자 PDF 속 스캔 쪽은 represent가 쪽 전체를 VLM으로 읽어 채운다(`vlm_page`) — 회전된 쪽(`tuning.extract.max_rotated_pages` 20)·숨은 글자가 그림과 겹친 쪽(`tuning.extract.max_hidden_overlap_pages` 20) 각각 최대 20쪽. 쪽 VLM은 `PARSE_POST`에 `vlm_page`가 있을 때만, 문서당 한 번(실패한 쪽은 다시 부르지 않음).
6. 대표 결과가 이미지·스캔 형식(`.pdf_image`·png·jpg 등)의 VLM 엔진이고 글이 비어 있지 않으면 → 쪽 VLM을 건너뛰고 쪽 그림은 처리된 것으로 표시한다(그림 VLM 없음).
7. VLM 엔진·쪽 VLM·그림 VLM의 호출 1건 제한은 모두 `common.models.vlm.vlm_timeout_sec` 하나다([pl-43](#pl-43)).
8. 일괄 엔진 자식은 낮은 우선순위로 돈다(`tuning.extract.low_priority_engines` — POSIX nice +10). 컨테이너끼리의 CPU 순위는 [ops.md#rn-03](ops.md#rn-03).
9. 파싱 서비스(`parse_document`)는 우선순위를 낮추지 않고 자기 제한을 쓴다 — `tuning.ops.services.data_parsing.mcp_parse_text_engine_page_timeout_sec` 1 · `mcp_parse_first_try_min_timeout_sec` 20(VLM 엔진은 파이프라인과 같은 `common.models.vlm.vlm_timeout_sec`), 작업 제한 `mcp_parse_job_timeout_sec` 600. 작업 시간을 넘기면 프로세스 그룹 전체를 끝낸다.
10. 알려진 한계: 숨은 글자가 그림과 겹친 쪽(`hidden_overlap`)은 쪽 VLM에 낱말 상자가 없어 숫자 표기 차이(예: 430.000 ↔ 430,000)를 고치지 않고 원래 글을 둔다. 글자 엔진은 쪽으로 나누지 않는다(쪽 병렬은 VLM 엔진 안에서만).

### 예시
- 글자 엔진, 5쪽, 엔진의 첫 문서 아님 → 5 × 10 + 10 = 60초. 같은 문서가 엔진의 첫 문서 → max(50, 60) + 10 = 70초. 넘으면 140초로 한 번 더.

### QA
- `tests/server/pipeline/test_engine_run.py`(page_timeout·OCR 끔) · `tests/server/pipeline/test_vlm_page.py`(`pick_pages`) · `tests/general/pipeline/test_represent.py`(쪽 VLM 채우기).
- Status: done

<a id="pl-43"></a>
## pl-43 · VLM 처리 한 길 — 호출·동시 수·제한 시간·해상도

### 무엇·왜
공유 VLM 서버의 동시 요청을 설정 몇 개로 묶어 조절한다(엔진마다 손잡이를 두지 않음). 11-04(사용자): 스캔 쪽이 엔진 `qwen_vlm`·쪽 VLM 후보정·그림 VLM 세 길로 각자 요청을 만들어 해상도(200·150·200)·생각 끄기·제한 시간·재시도·동시 수가 길마다 달랐다 — 한 함수·한 설정으로 합친다.

### 규칙
1. 모든 VLM 호출(엔진 `qwen_vlm`·쪽 VLM·pptx 슬라이드·그림 VLM·중첩 그림)은 `pipeline/shared/vlmcall.py`의 `ask()` 하나로 `common.ai.llm.complete('vlm')`를 부른다 — 내부망 가드·예산 장부·모델 다운 감지가 같고, 요청 본문에 `common.models.vlm.vlm_extra_request_body`(생각 끄기 등)를 합친다. 코드에 고정한 생각 끄기는 없다.
2. 호출 1건 제한 시간 = `common.models.vlm.vlm_timeout_sec`(180초). 실패(시간 초과·연결 오류·429·5xx) 재시도 = `tuning.common.models.vlm.vlm_retries`(1 — 시도는 retry + 1번).
3. 렌더 해상도 = `extract.page_render_dpi`(150) 하나 — 엔진·쪽 VLM·pptx·그림·`prepare --dpi` 기본값. 긴 변은 2000 px로 줄인다.
4. 쪽 수 상한 = `transform.vlm.vlm_max_pages_per_doc`(비움 = 전부, 0 = 끔) — 엔진과 쪽 VLM 공통. `extract.ocr.ocr_max_pages_per_doc`는 OCR 엔진(VLM 아님)에만 남는다(엔진 공용 파일 `engines/_common`을 바꾸면 모든 엔진 지문이 바뀌어 두었다).
5. 엔진과 쪽 VLM은 같은 쪽 옮기기 함수(`transcribe` — 같은 지시문 `page_transcribe`·렌더·캐시 열쇠)를 써서, 엔진이 옮긴 쪽은 후보정이 캐시로 다시 쓴다. 엔진은 쪽 하나라도 호출이 실패하면 문서×엔진 실패로 남긴다(빈 답은 빈 쪽).
6. 동시 수: 한 프로세스 안 모든 VLM 호출의 합 상한 = `common.models.vlm.vlm_max_total_requests`(8, 호출 한 건이 자리 하나). 문서 하나 안 = `common.models.vlm.vlm_requests_per_doc`(4 — 쪽·그림 공통). 쪽 옮기기는 가장 느린 호출이 60초를 넘으면 다음 묶음 병렬 수를 절반(최소 2)으로 줄였다가 빨라지면 되돌린다(코드 상수).
7. 일괄 파싱(`pipeline.cli parse`)은 엔진 자식에 `VLM_CONCURRENCY` = max(1, min(`vlm_requests_per_doc`, `vlm_max_total_requests` ÷ 동시 문서 수))를 넘긴다. 동시 문서 수 = min(이번 문서 수, 조각 `--procs` × `--workers`).

### 현재 상태(11-04)
- 지운 칸(남아 있으면 시작 거부): `extract.vlm_page_sec`·`tuning.ops.services.data_parsing.vlm_page_sec` → `common.models.vlm.vlm_timeout_sec` · `tuning.transform.vlm.deadline` → `vlm_timeout_sec` · `transform.vlm.global_concurrency` → `vlm_max_total_requests` · `tuning.transform.vlm.page_concurrency`·`tuning.transform.figures.vlm_parallel`·`tuning.ops.nightly_run.vlm_concurrency`(명령 인자 `--vlm-concurrency`) → `vlm_requests_per_doc` · `transform.vlm.page_slow`·`tuning.transform.vlm.page_min_concurrency` → 코드 상수.
- 고친 결함: run_pipeline이 `--set VLM_CONCURRENCY=8`(vlm 레인 6)을 줘도 `--workers` 기본 4로 나눠 문서 1건 실행의 엔진 자식이 늘 2였다(`8 ÷ 4`). 이제 동시 문서 수(문서 1건이면 1)로 나눈다.
- 결과가 바뀜: 엔진 `qwen_vlm` 지문이 바뀌어 스캔·이미지 문서는 다시 파싱된다(지시문이 쪽 VLM과 같은 `page_transcribe`로, 해상도 200 → 150). 그림 해상도 200 → 150이라 그림 캐시도 새로 만든다. 서버 확인은 [refactor.md C-93](../refactoring/refactor.md).

### QA
- `tests/server/pipeline/test_vlmcall.py` — 가짜 로컬 VLM 서버로 표 한 줄 = 한 길(엔진·쪽 VLM 후보정·그림·중첩 그림): 같은 `vlm_extra_request_body`·제한 시간·해상도, 엔진이 옮긴 쪽은 후보정이 호출 0, 재시도 횟수·쪽 상한·실패 시 엔진 실패.
- `tests/general/pipeline/test_vgate.py` — 합 상한만큼만 동시 진입.
- Status: done

<a id="pl-42"></a>
## pl-42 · 지원 확장자 1차 — .jpeg·.tif·.tiff·.bmp·.mhtml(+ .hwpx 시험)

### 규칙
1. `.jpeg`·`.tif`·`.tiff`·`.bmp`는 `.jpg`와 같은 구성(`qwen_vlm`), `.mhtml`은 `.mht`와 같은 구성(`mhtml`·`kreuzberg`)이다.

### QA
- `tests/server/pipeline/test_ext_formats.py` — 형식마다 임시 견본을 만들어 파싱(이미지는 VLM 호출만 가짜), 구성 목록과 고르는 엔진 확인. `.hwpx` 포함.
- Status: done

<a id="pl-45"></a>
## pl-45 · 지원 확장자 2차 — .hwp·.docm·.pptm·.rtf·.csv·.tsv·.md·오픈문서·서식 파일·.json·.xml·.log

### 무엇·왜
회사 문서에 나오는 나머지 형식을 읽는다. 엔진 파일(엔진 지문)은 바꾸지 않는다.

### 규칙
1. 엔진 `parser.py`의 `FORMATS`는 두고, 등록부 `pipeline/transform/parse/engines/registry.py`의 `EXTRA_FORMATS`(엔진별 추가 확장자)에 더한다 — `formats(엔진)` = `FORMATS` + `EXTRA_FORMATS`, `engines_for()`·`parse_engines --one --list`가 이것을 읽는다.
2. 구성(우선순위 순): `.docm`·`.pptm`(kreuzberg, anydoc) · `.rtf`·`.odt`·`.ods`(anydoc, kreuzberg) · `.odp`(anydoc) · `.csv`(markitdown, kreuzberg) · `.tsv`(plaintext, kreuzberg) · `.md`(plaintext, markitdown) · `.xlsb`·`.dotx`·`.xltx`·`.potx`·`.ppsx`·`.dot`·`.xlt`·`.pot`(kreuzberg) · `.json`·`.xml`·`.log`(plaintext 하나 — 글 그대로).
3. `.docm`·`.pptm`은 `office` 엔진에 주지 않는다(`office_stdlib`는 `.docx`가 아니면 xlsx로 다룸).
4. 파싱 서비스가 받는 확장자(`pipeline.transform.parse.engine_check.allowed_exts()`) = 구성의 `parse` 키(`.pdf_*` → `.pdf`) − 이미지 확장자.

### 단계
1. `.hwp` — kreuzberg로 실제 `.hwp` 문서를 읽어 글이 나오는지 시험한 뒤 `EXTRA_FORMATS["kreuzberg"]`와 구성에 더한다.
2. 사람 결정 대기: ① 암호·DRM 사전 판정(`filter_and_rotate.py` — `OOXML_EXTS`·OLE 목록)에 서식 파일·`.xlsb`·오픈문서가 없음 ② `.pptm`·`.ppsx`·`.potx`·`.docm`·`.dotx`·`.xltx`가 그림 추출·쪽 수·FAQ 행의 `.docx`·`.pptx`·`.xlsx` 정확 비교 분기를 못 탐 ③ `resources/config/criteria.json` `groups.native`에 새 형식이 없어 파싱 QA 판정이 빔 ④ `parse_document` 도구 설명(`mcp_server/routers/parse_tool.py` — MCP 계약)의 형식 목록이 옛것 ⑤ plaintext가 `.log`·`.json`의 `|`·탭 줄을 표로 볼 수 있음 ⑥ 옛 이진 4종(`.xlsb`·`.dot`·`.xlt`·`.pot`) 자동 파싱 시험 없음.

### QA
- `tests/server/pipeline/test_ext_formats.py` `EXT2` 표 — 형식마다 임시 견본을 구성의 엔진마다 파싱(옛 이진 4종은 구성·등록부만 확인).
- Status: todo

<a id="pl-04"></a>
## pl-04 · represent — 가장 좋은 결과를 고르고 고치기

### 무엇·왜
엔진마다 결과가 다르다. 다음 단계로 넘기는 글(대표 결과 `_rep/<문서>.json`)은 가장 정확해야 한다.

### 규칙
1. 대표 엔진은 정확도 + 풍부함으로 고른다(`transform.represent.engine_pick`, 기본 best).
2. 줄 단위 투표로 합치고(`fragment_vote.py`), 엔진 사이 라벨·값을 서로 확인한다(`crosscheck.py`).
3. 후보정 `PARSE_POST`(일괄 파싱 기본 `all` = `vlm_page,supsub,charts,figures,context,attachments`, 파싱 서비스 기본 `supsub`): 쪽 VLM 채우기([pl-22](#pl-22)), 윗첨자 `^`·아래첨자 `_`, 차트·그림([pl-05](#pl-05)), 그림 근처 맥락([pl-37](#pl-37)), 메일 첨부([pl-36](#pl-36)).
4. 여러 엔진의 표를 본문 제자리에 넣고(`table_inline.py`), 표준 표(`tables_std`)를 만든다.
5. 파싱 QA(`parse_scoring.py`): 교차 정확도가 `resources/config/criteria.json` `run.cross_acc_full`(0.95) 미만이면 상태 `partial`, 아니면 `ok`.
6. 대표 결과는 마스터(용어집·고객 명부)를 읽지 않는다.

### QA
- `tests/general/pipeline/test_represent.py` · `tests/server/pipeline/test_fuse.py` · `tests/server/pipeline/test_table_inline.py` · `tests/server/pipeline/test_table_std.py` · `tests/server/pipeline/test_supsub.py` · `tests/general/pipeline/test_parse_qa.py`.
- Status: done

<a id="pl-36"></a>
## pl-36 · 메일 첨부 파싱

### 무엇·왜
메일의 핵심 내용이 첨부에 있는 경우가 많다.

### 규칙
1. `.eml`·`.msg`의 첨부(zip 첨부는 풀어서)를 형식별 엔진으로 재귀 파싱한다 — 깊이 `tuning.extract.attach.attachment_max_depth`(1), 첨부 하나 `attachment_max_mb`(20 MB) 넘으면 건너뜀, 문서당 `attachment_max_count`(10)개까지.
2. 결과는 대표 본문에 `[첨부 <파일명>]` 절로 덧붙이고, 인용 스레드는 접는다.
3. 인라인 그림(cid)은 그림 기능([pl-05](#pl-05))이 맡는다.

### QA
- `tests/general/pipeline/test_attachments.py`.
- Status: done

<a id="pl-37"></a>
## pl-37 · 그림 근처 맥락

### 무엇·왜
그림 설명을 본문과 함께 찾게 한다.

### 규칙
1. 그림마다 캡션·본문 언급을 연결하고, 그림 기록의 값이 본문 값과 맞는지·부딪히는지 표시한다(`represent/figure_context.py` `value_check` — 모델 호출 없음).
2. 그림 기록은 본문 청크 한 덩어리로 렌더한다.

### QA
- `tests/general/pipeline/test_context.py`.
- Status: done

<a id="pl-05"></a>
## pl-05 · 그림

### 무엇·왜
차트·도식·이미지에는 글자 추출이 놓치는 값이 있다.

### 규칙
1. 이미지(pdf·docx·xlsx·pptx·eml)마다 VLM 한 번(`figure_describe` 지시서)으로 검색용 기록을 만든다 — 문서당 최대 `transform.vlm.vlm_max_figures_per_doc`(20)개.
2. 후보에서 뺀다(기록은 남김): 쪽 면적 1% 미만, 짧은 변 `tuning.transform.figures.figure_min_side_px`(64 px) 미만, 같은 sha로 반복되는 이미지(로고).
3. 원본 차트 XML·벡터 차트 값은 VLM 없이 읽는다(`chart_values.py`).
4. 슬라이드·도형은 soffice로 그려 읽는다 — 문서당 `PARSE_PPTX_RENDER_MAX`(10)쪽, 변환 제한 `PARSE_PPTX_CONVERT_SEC`(60초).
5. 지금 코드는 도식 연결선·겹친 개체 묶음(`figure_overlay`)·중첩 그림(`nested_figure`)·pptx 도형 연결·도형 감지·Mermaid 출력도 따로 만든다(`figures/figure_extract.py`) — 아래 단계에서 줄인다.

### 단계
1. 부가 기능(도식 화살표·겹침 묶음·중첩 그림·pptx 도형 연결·도형 감지·Mermaid 따로 만들기)을 VLM 한 번의 종류별 출력으로 바꾼다 — 도표 → Mermaid, 표 → HTML 표, 차트 → 세부 값. 차트 XML·벡터 값과 쪽 VLM은 그대로. 대표 결과 지문(p1)이 바뀐다.

### QA
- `tests/server/pipeline/test_figures.py` · `tests/server/pipeline/test_chart_values.py` · `tests/server/pipeline/test_pptx_render.py`.
- Status: todo

<a id="pl-06"></a>
## pl-06 · 구조화 — 청크·메타데이터·임베딩

### 무엇·왜
검색은 출처가 달린 짧은 조각(청크) 단위로 한다.

### 규칙
1. 청크 나누기 방식은 구성의 `chunk`(지금 `structure`): 목표 `CHUNK_SIZE`(기본 800자), 제목 기준으로 나누고 표는 통째로 둔다. `CHUNK_TABLE=rows`일 때만 큰 표를 `CHUNK_TABLE_ROWS`(25)행씩 나눈다. FAQ 원천은 [extract.md#pl-39](extract.md#pl-39).
2. 그림 설명은 그림 청크 하나(캡션 + 요약 + 그림 글자 + 값·연결·표)가 된다.
3. 문서 요약 = 앞부분 발췌: 쪽 번호 줄을 뺀 줄 중 `[가-힣A-Za-z0-9]{2,}`가 든 줄을 앞에서부터 공백으로 잇고, 합이 300자 이상이 되면 멈춰 300자로 자른다(`gold_bundle.lead_summary`).
4. 본문 고객(`clients_doc`, `infer_clients`): 알려진 고객(명부 + 별칭 + 공개 이름 seed `client_roster_seed.json`) 이름·별칭이 본문에 2번 이상 나오거나 제목·첫 400자에 나오면 고객으로 본다. 순서 = 제목·머리 등장 먼저 → 등장 횟수 → 이름순. 비면 다른 문서에서 그 고객과 함께 나온 제품 코드 접두로 채운다. 명부·별칭은 PG 마스터에서 읽는다([load.md#pl-38](load.md#pl-38)).
5. 문서 날짜 `content_date` = 본문 앞 2,000자, 없으면 파일 이름에서 찾은 날짜(`common/core/docmeta.py` — 꼴은 [db_schema.md](../architecture/db_schema.md) gold.doc).
6. 임베딩은 내부망 API(`required.models.embed_base_url`·`embed_model`)만 쓴다. `gold_bundle --embed none`은 시험용(적재는 거부 — [load.md#pl-16](load.md#pl-16)). 한 번에 `EMBED_BATCH`(32)개, 입력은 `EMBED_MAX_CHARS`(8,000자)에서 자른다. 같은 청크는 캐시(`EMBED_CACHE` sqlite)에서 다시 쓴다.
7. 묶음 `meta.json`에 구성(`stack_conf`)·임베딩 모델·차원·읽은 마스터 해시(`master_hash`)를 남긴다.

### QA
- `tests/server/pipeline/test_gold_bundle.py` · `tests/general/pipeline/test_chunking.py` · `tests/server/common/test_embed.py` · `tests/general/common/test_docmeta.py`.
- Status: done

<a id="pl-33"></a>
## pl-33 · 분류 — 적재 안에서, gold에 넣기 전

### 무엇·왜
- SFDC·LAS 문서마다 종류 라벨 `doc_class`를 붙인다(CRMS·FAQ·그 밖은 없음). **운영 분류와 결과가 같아야 한다**: 지시문은 운영 글자 그대로(바이트 같음), 사용자 쪽 글(문서 정보·LAS 키워드 근거·본문)도 운영 코드와 같은 모양.
- 적재(`pipeline/load/pgvector_load.py` `load`)가 EDW 메타를 붙인 직후, gold에 넣기 전에 한다. 고르는 규칙을 따로 두지 않는다 — 적재 대상이 곧 분류 대상.

### 규칙
1. 모델은 `llm.chat`(역할 llm — 예산 장부)으로 부른다. effort는 `common.models.llm.llm_extra_request_body`(서버는 `{"reasoning_effort": "high"}`), 답 길이 상한 4,096 토큰.
2. 본문 근거 = 대표 결과 `.md`(`render_md` — 게시본과 같은 글)의 앞 8,000자. `run_pipeline`가 적재에 `--rep-dir <문서 폴더>/parse/_rep`를 넘긴다(없으면 묶음의 본문). 본문이 없으면 부르지 않고 실패.
3. **SFDC 지시문**(`resources/prompts/pipeline/classify_sfdc/`, 공용 꼬리 없음 `common_tail: false`): 라벨 `RFI`·`RFP`·`RFI+RFP`·`Proposal`·`Other`, 경계 규칙 6개(내부 입찰 평가 자료는 Other · 우리가 채운 RFI 질문서는 RFI · 견적 보조 파일은 제안 묶음일 때만 Proposal · `RFI+RFP`는 한 문서가 두 요청을 정말 함께 담을 때만 · 작성자는 파일 이름이 아니라 문서 안의 머리·표지로 · 고객 RFP에 답하는 우리 제안은 Proposal).
4. **SFDC 문서 정보** = gold `<기준>_sfdc.doc.attrs`의 분류 힌트 키([db_schema.md](../architecture/db_schema.md) gold.doc.attrs 키 — 적재 때 EDW 조인, 표·칸 이름은 `resources/config/edw_chain.yaml` `sfdc.fields`) + 원본 파일 이름 + 형식·대표 엔진(대표 결과의 `format`·`engine`) + 제목 키워드 묶음(`classify.fams`). 제목이 비면 원본 파일 이름. 서버 EDW에 힌트 칸이 없으면 그 힌트만 빈다(경고 한 줄).
5. **LAS 지시문**(`resources/prompts/pipeline/classify_las/`, PSA = Product Specific Agreement): 라벨 `MSA`·`PSA`·`QAG`·`LOI`·`Amendment`·`Assignment Letter`·`Other`.
6. **LAS 근거**: 원본 파일 이름·형식, 품의 제목 `attrs.approvalname`, 상대방 `client_edw` + 키워드 근거(운영 `extract_evidence` 그대로 — ① 본문 앞 300자 자기 이름 ② 앞 2,000자의 계약 종류 전체 이름·경개·Other 종류 ③ 파일 이름 키워드(전체 이름·약어)·DR ④ 변경 키워드, 두 종류 이상·변경·보고서·메모 경고) + 본문 8,000자(`classify.las_evidence`·`las_user`).
7. 답 읽기: 코드 울타리(```)를 벗기고 `class`(SFDC는 `doc_class`도)가 있는 첫 JSON 객체를 찾는다. SFDC는 소문자·공백 뺀 값을 별칭표 `rfi`·`rfp`·`rfi+rfp`·`rfp+rfi`(→ `RFI+RFP`)·`proposal`·`other`로 바꾼다. LAS는 앞뒤 공백만 정리한 글자가 라벨 집합 안이어야 한다. 집합 밖·문자열 아님·없음이면 실패. 확신도는 읽지 않는다.
8. 재시도·수동 명령 없음. 분류 실패(모델 장애·예산 초과·집합 밖·본문 없음)는 **그 문서의 적재 실패**다 — gold에 넣지 않아 `gold_version`이 적히지 않고, 다음 실행에서 다시 대상이 된다.
9. 같은 sha256은 묶음이 한 문서만 남기므로 한 번만 부른다. 파싱되지 않은 문서는 gold에 오지 않아 라벨도 없다.
10. 이미 라벨이 있는 문서(gold 또는 묶음)는 덮지 않는다 — `--replace`로 다시 적재해도 옛 라벨 유지.

### 예시
- SFDC 답 `{"class": "RFP+RFI"}` → 별칭 → `RFI+RFP`. 답 `{"class": "Others"}` → 집합 밖 → 실패, 그 문서는 이번에 gold에 넣지 않음.
- LAS 답 ```` ```json {"class": " QAG "} ``` ```` → `QAG`. 답 `{"class": "qag"}` → 집합 밖 → 실패.

### 데이터·약속
- 라벨은 gold `<기준>_sfdc.doc.attrs.doc_class`·`<기준>_las.doc.attrs.doc_class`에만 둔다. 모델 이름·분류 시각·낮은 확신 표시는 어디에도 두지 않는다(판은 ParsingMeta `silver_version`·`gold_version`).
- 감사 기록: `<묶음>/classify_audit.jsonl` — 문서마다 한 줄(`at`·`file_path`·`source`·`doc_class`·`error`).
- 지시문은 바이트 그대로, LF(지시문 지문). `output_schema`는 두지 않는다(어긋나면 자동으로 한 번 더 묻는 길이 생겨서).

### QA
- `tests/server/pipeline/test_classify.py`(가짜 LLM): 답 읽기 표, 제목 키워드 묶음, LAS 키워드 근거(운영 글과 바이트 같음), 사용자 쪽 글, 부른 횟수(재시도 없음)·실패 집합·라벨 안 덮음·본문 없음·대상 아닌 원천·`-test` 표기, 적재가 실패 문서를 넣지 않음.
- `tests/server/pipeline/test_edw_meta.py::test_hints`(실제 SQLite EDW — 힌트 칸 갈래). EDW 대역 `valid_env/edw/sfdc.sql`(LAS 대역 문서는 없음).
- 운영 결과와의 비교는 [test.md#e2-20](test.md#e2-20).
- Status: done

<a id="pl-60"></a>
## pl-60 · 쪽 수 세기는 함수 하나

### 무엇·왜
쪽 수가 자리마다 다르면 제한 시간·쪽 VLM 상한이 어긋난다.

### 규칙
1. 문서 쪽 수는 함수 하나가 센다(`pipeline/shared` — `pdf_kind.doc_pages`와 `vlmcall.page_count`를 합침).
2. `pipeline/shared/vlmcall.py`는 엔진 지문(`engine_code_fp`)에 들어간다 — 바꾸면 그 엔진 결과를 다시 만든다. 사람 검토(등급 A) 뒤 지문 배치에서 바꾼다.

### 비고(지금 코드와 다른 점)
- `pdf_kind.doc_pages`와 `vlmcall.page_count`가 따로 있다.

### QA
- 정할 것: 같은 문서 표(PDF·pptx·이미지)에서 두 자리가 같은 쪽 수.
- Status: todo
