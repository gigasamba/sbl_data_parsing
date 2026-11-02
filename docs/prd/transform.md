# 변환 — 파싱·represent·그림·구조화

[PRD.md](../PRD.md) 카테고리. [extract.md](extract.md) 다음, [load.md](load.md) 앞: 엔진 스택 파싱(pl-03·pl-22·pl-43·pl-42·pl-45) → represent(pl-04·pl-36·pl-37) → 그림(pl-05) → 구조화(pl-06·pl-15) → 분류(pl-33). 파싱 정리·지문 배치는 [transform-cleanup.md](transform-cleanup.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-03 · pl-22 · pl-43 · pl-42 · pl-45 · pl-20 · pl-17 · pl-04 · pl-36 · pl-37 · pl-05 · pl-06 · pl-15 · pl-33.

<a id="pl-03"></a>
## pl-03 · 엔진 스택 파싱
- 이유: 모든 형식을 잘 다루는 파서 하나는 없다.
- 무엇: 파일 형식마다 스택의 모든 엔진이 돈다(대체 사슬이 아님). 문서마다 병렬(형식당 상한은 0.2.0에 지움 — [transform-cleanup.md#pl-46](transform-cleanup.md#pl-46))(10-29부터 phase 없음 — [pl-22](#pl-22)). 엔진마다 격리. 엔진 스택은 서버·PC 모두 파일 `resources/config/pipeline_stack.json`이다(사용자 11-01 — [load.md#pl-08](load.md#pl-08)). 형식: pdf(글자/이미지), doc(x), ppt(x), xls(x/m), hwpx, txt, html/htm, mht, eml, msg, png, jpg. 미지원: 옛 `.hwp`, zip.
- 파일: `pipeline/extract/run_all.py`, `pipeline/extract/engines/`(엔진 핑거프린트 — 바꾸려면 사람 검토), `resources/config/pipeline_stack.json`, `docs/architecture/pipeline_stack.md`.
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P1): 엔진 범위는 `stack` 그대로(형식당 2개) — 서버 settings.yaml에 `all`을 적지 않는다.
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([test.md#e2-10](test.md#e2-10)) — 비교는 필요할 때 다시 만든다. 엔진 비교 실험은 그때 stack json을 고쳐서 한다.
- 결정(사용자 10-30(-c5 전달)): 엔진 범위는 `stack` 하나 — 유일한 방식이자 기본. 형식별 엔진은 `resources/config/pipeline_stack.json`에 명시한다. `PARSE_ENGINE_SCOPE` `all`과 `--engines all` 길을 지운다(`pipeline/cli.py` `_set_engine_scope_default`, `pipeline.extract.engine_scope`, `common/config/sample.py`의 옛 값). 비교 실험은 stack json을 고쳐서 한다. 참고: 운영 reference 서버는 `all`로 돌았지만 사용자는 stack만 골랐다.
- 11-01(`feature/scope-cut-unused`, 허브 지시): `run_docs.py`의 스캔용 엔진 목록(`scan_eng` — `--engines …`로 rapidocr_ko를 뺀 목록)을 지우고 `pipeline_stack.json`의 `.pdf_image`를 `["qwen_vlm"]` 하나로 — 같은 동작(스캔은 VLM만, `extract.ocr_engine` 기본 꺼짐이라 OCR 엔진은 원래 걸러짐). 서버는 코드 폴더의 같은 파일을 읽어(11-01 struct 판 표 없앰) 오버레이 패치로 반영. 이미지 확장자 행(`rapidocr_ko`·`qwen_vlm`)은 그대로 — 0.2.0에서 `ocr_engine` 스위치를 없앨 때 같이 바꾼다.
- Status: done — `all` 길 지움(11-01 `feature/pl03-stack-only`)

<a id="pl-22"></a>
## pl-22 · 파싱 phase 없애기 · 문서마다 엔진 병렬 · OCR 엔진 끔
- 이유(사용자 10-29): phase 1/2/3r은 쪽당 아주 짧은 제한으로 엔진을 다시 돌리고 시간 초과를 뒤로 미뤘다. `need_vlm` 규칙과 OCR 엔진이 이미지 문서를 느리게 하고 쪽 VLM과 겹쳤다.
- 실행: 문서마다 스택 엔진을 병렬로, 엔진마다 격리된 자식 하나. 문서끼리는 `--workers`와 `--procs`(문서 조각)로 병렬.
- 제한: 문서×엔진마다 = 쪽 수 × `pipeline.extract.text_page_sec`(10) 또는 VLM 엔진은 `vlm_page_sec`(120), 엔진의 첫 문서는 `warmup_sec` 이상, 여기에 `isolate_overhead`. 시간 초과면 제한을 두 배로 한 번 다시, 그다음 실패 기록. 옛 phase 시간 초과 기록은 다시 시도한다.
- OCR 엔진: `rapidocr_ko`는 파싱 엔진으로 돌지 않는다 — 이미지·스캔 문서는 VLM 엔진만(0.2.0 — 스위치 `pipeline.extract.ocr_engine`과 대표 결과의 OCR 대체 길을 지우고 구성의 이미지 행을 `qwen_vlm` 하나로, [transform-cleanup.md#pl-46](transform-cleanup.md#pl-46)). 엔진 파일은 남김(prepare·figures가 씀).
- 글자 PDF 안 스캔 쪽: 더는 `.pdf_image` 엔진이 없다. represent가 그 쪽을 쪽 VLM으로 채운다(`vlm_page.page_text_pages`, 스캔 신호가 있는 쪽만, 병렬).
- 이미지·스캔 문서: 쪽마다 VLM 한 번. 대표가 이미지·스캔 형식(`.pdf_image`, png, jpg — run_all과 같은 형식 키)에서 글이 비지 않은 VLM 엔진이면 represent는 쪽 VLM을 건너뛰고 쪽 전체 그림을 처리된 것으로 표시한다(그림 VLM 없음, `vlm_page`가 없어도). 쪽 VLM은 `PARSE_POST`에 `vlm_page`가 있을 때만, 문서당 한 번(실패한 쪽은 다시 부르지 않음).
- VLM 엔진 자식의 `VLM_TIMEOUT` = min(`models.vlm.timeout`, `vlm_page_sec`).
- 우선순위: 일괄 엔진 자식은 낮은 우선순위로 돈다(`pipeline.extract.low_priority` — nice +10 / Windows BELOW_NORMAL. 한 세션·autogroup 안에서만 효과, 컨테이너끼리는 cgroup CPU 가중치 — C-65 ⑥).
- 파싱 서비스(`parse_document`)는 우선순위 낮추기를 끄고 자기 제한을 쓴다(`pipeline.service.parse_mcp.text_page_sec` 1, `vlm_page_sec` 60, `warmup_sec` 20 — 엔진 첫 기동). 작업 시간 초과면 프로세스 그룹 전체를 죽인다. `PARSE_MCP_OCR`은 `PARSE_OCR_ENGINE`으로 합쳤다.
- 알려진 손실: 'hidden_overlap' 쪽의 AD47 숫자 고치기(아래 "코드와 다른 점"). "처리됨"은 문서 단위라, 그 조건이 맞으면 VLM 엔진이 비워 둔 쪽은 쪽 VLM을 받지 않고, 섞인 `.pdf_image`의 글자 쪽에 들어 있는 그림은 그림 VLM을 받지 않는다.
- 지움: `--phase(s)`, `--rescue`, `--vlm-all`, `--need-vlm`, `--timeout`, `PARSE_PHASES`, `PARSE_PHASE_SEC`, `PARSE_MCP_OCR`, `PHASE2_FAILED`.
- 파일: `pipeline/extract/run_all.py`, `pipeline/stackcfg.py`, `pipeline/config.py`, `pipeline/cli.py`, `pipeline/mcp_parse_service.py`, `pipeline/transform/represent/represent.py`, `pipeline/transform/figures/vlm_page.py`, `deploy/host/scripts/run_docs.py`.
- 시험: `tests/server/pipeline/test_run_all.py`(OCR 스위치, page_timeout, 옛 phase 시간 초과), `tests/server/pipeline/test_vlm_page.py`(`pick_pages`), `tests/general/pipeline/test_represent.py`(쪽 VLM 채우기).
- 열린 것: 글자 엔진은 쪽으로 나누지 않는다(문서×엔진마다 자식 하나, 쪽 병렬은 VLM 엔진 안에서만 `VLM_CONCURRENCY`로).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P7·P8): 그대로 둠 — 그림자 모드·스트리밍(e2-18 남김 — 10-31 op-08에서 기능째 지움), 복호화(수동 CLI 요건), figure_review(e2-10에서 판단), rapidocr_ko(다른 단계가 씀). 실행 구성(D-2~14)은 pl-22·rn-01·rn-02·mc-08 결정대로, 워커 6은 서버 실측(C-65) 뒤 조정.
- 결정(사용자 10-30 PRD grill): S1 — done으로 닫는다. 서버 확인은 refactor.md C 항목, 후속(VLM 동시 수 손잡이)은 새 todo 행으로.
- Status: done — `feature/r2-phase` 병합. 서버 확인은 refactor.md C-65·C-68, VLM 동시 수 손잡이는 [pl-43](#pl-43).

<a id="pl-43"></a>
## pl-43 · VLM 동시 수 손잡이
- 이유: pl-22(파싱 phase 없애기)에서 VLM 동시 수 손잡이는 병합하지 않고 후속으로 남겼다(사용자 10-30 PRD grill S1 — pl-22는 done으로 닫음).
- 무엇: VLM 엔진·쪽 VLM·그림 VLM이 함께 쓰는 동시 호출 수를 조정하는 설정(지금은 `VLM_CONCURRENCY`·전체 VLM 관문 기본 12 — [pl-05](#pl-05)).
- 결정(허브 10-31, 최신 결정 우선): VLM 동시 수는 `tuning`의 키 하나로 둔다(op-08 구조) — 엔진별 손잡이는 만들지 않는다.
- Status: done (10-31) — 키 하나(`VLM_CONCURRENCY`)로 닫음. 새 손잡이 없음.

<a id="pl-42"></a>
## pl-42 · 지원 확장자 더하기 — .jpeg·.tif·.tiff·.bmp·.mhtml(+ .hwpx 시험)
- 결정(사용자 10-30(-c5 전달)): `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.mhtml`을 지원 형식에 더하고 시험한다. `.hwpx`도 시험에 넣는다.
- 확장자마다 `tests/server`에 파싱 시험 하나 — `valid_env`에 그 형식 파일이 없으므로 시험이 임시 폴더에 샘플을 만든다(CLAUDE.md §6-4).
- 형식별 엔진은 `resources/config/pipeline_stack.json`에 명시([pl-03](#pl-03) — stack 하나). 스택 변경은 `resources/config/pipeline_stack.json`을 고쳐 오버레이 패치(서버·PC 같은 파일 — 사용자 11-01).
- 한 것(10-31): `pipeline_stack.json`에 `.jpeg`·`.tif`·`.tiff`·`.bmp` = `rapidocr_ko`·`qwen_vlm`(`.jpg`와 같음 — OCR은 `ocr_engine` 켤 때만), `.mhtml` = `mhtml`·`kreuzberg`(`.mht`와 같음). 엔진 코드·형식 판별 코드는 그대로(다섯 형식 모두 엔진 `FORMATS`와 represent·그림 목록에 이미 있음). 시험 `tests/server/pipeline/test_ext_formats.py` — 형식마다 임시 견본을 만들어 파싱(이미지는 VLM 호출만 가짜), 엔진 구성 목록·형식당 2개·고르는 엔진 확인.
- 서버: 따로 할 일 없음 — 서버도 같은 파일을 읽고 그 파일에 이미 pl-42 확장자가 있다(사용자 11-01, [load.md#pl-08](load.md#pl-08)). 옛 `set-stack` 단계(refactor.md C-69)는 이것으로 닫았다.
- 파일: `resources/config/pipeline_stack.json`, `tests/server/pipeline/test_ext_formats.py`, `docs/architecture/pipeline_stack.md` §3-1.
- Status: done (10-31, feature/pl42-more-ext)

<a id="pl-45"></a>
## pl-45 · 지원 확장자 2차 — .hwp·.docm·.pptm·.rtf·.csv·.tsv·.md·오픈문서·서식 파일·.json·.xml·.log
- 결정(사용자 11-01, 네 묶음 모두): 확장자와 엔진(우선순위 순)
  - 문서: `.hwp`(kreuzberg만 — 실제 문서 품질 시험 필요) · `.docm`·`.pptm`(kreuzberg, anydoc — **office 아님**: `office_stdlib/parser.py:242`가 `.docx`가 아니면 xlsx로 다룸) · `.rtf`(anydoc, kreuzberg).
  - 글자 자료: `.csv`(markitdown, kreuzberg) · `.tsv`(plaintext, kreuzberg) · `.md`(plaintext, markitdown).
  - 오픈문서·서식 파일: `.odt`·`.ods`(anydoc, kreuzberg) · `.odp`(anydoc) · `.xlsb`(kreuzberg) · `.dotx`·`.xltx`·`.potx`·`.ppsx`·`.dot`·`.xlt`·`.pot`(kreuzberg).
  - 데이터·기록: `.json`·`.xml`·`.log`(markitdown 또는 plaintext, kreuzberg).
  - 뺀 것: `.gif`·`.webp`(이미지 확장자 목록이 여러 곳에 박혀 있음) · `.heic`(새 패키지 필요) · 압축 파일([pl-02](extract.md#pl-02) 결정).
- 방법: `pipeline/extract/engines/registry.py`에 "엔진별 추가 확장자" 표를 두고 `engines_for()`가 함께 읽는다 — 엔진 `parser.py`의 `FORMATS`와 엔진 지문(p0 code_fp)은 그대로(핑거프린트 명령으로 확인). 그다음 `resources/config/pipeline_stack.json`, `pipeline/mcp_parse_service.py`(`ALLOWED_EXTS`), `tests/.../test_ext_formats`와 시험 표본.
- 검토 등급 A(엔진 폴더) · 0.2.0 묶음.
- Status: todo — 0.2.0.

<a id="pl-20"></a>
## pl-20 · 엔진 스택 사본 파일 방식 검토
- 이유: C-50.
- 파일: `pipeline/config.py`(`paths.stack_snapshot`), `docs/architecture/pipeline_stack.md`.
- 사용자 10-30: 스냅샷 파일 대신 silver는 Object Storage uuid 폴더, 메타는 EDW ParsingMeta(단계별·성공 시), gold는 pgvector만.
- Status: done — 대체됨(10-30): [load-schema.md#pl-32](load-schema.md#pl-32)가 대신함(`_stack/stack-v*.json`·`STACK_SNAPSHOT` 지움).

<a id="pl-17"></a>
## pl-17 · 파싱 단계 위치 — `extract` 또는 `transform`
- 결정(사용자 10-31 범위 축소 grill): 파싱 단계를 transform/parse/로 옮기기를 **하지 않는다**(속도·품질 영향 없음). 행 닫음.
- 이유: 옮기면 code_fp p0가 바뀐다. 첫 배포 전이 가장 싸다(C-61).
- 결정(사용자 10-29 grill): `pipeline/extract/{engines/,run_all.py,parse_one.py}` → `pipeline/transform/parse/`로 옮긴다. `run_all.py` → `run_parse.py`로 이름을 바꾼다(문서 × 엔진 파싱만 함 — "run all"은 e2e로 읽힘). `extract/`에는 source · rdb_discover · dedup · prepare가 남는다. 옮기는 커밋과 이름 바꾸는 커밋을 나눈다(CLAUDE.md §1). 엔진 핑거프린트는 `_LEGACY_NAMES`로 유지. code_fp p0는 바뀌지만 첫 적재가 전체 e2e라 지금은 공짜([ops.md#pl-23](ops.md#pl-23)).
- 파일: `pipeline/extract/`, `pipeline/transform/`, `common/core/artifacts.py`(`LAYER_CODE`), `pipeline/cli.py`, 문서와 명령 표.
- 결정(사용자 10-30 PRD grill): S6 — 0.2.0에 함께(전체 재처리라 추가 비용 없음). 파일 이동이 많아 0.2.0 작업의 마지막에 한다.
- Status: dropped (사용자 10-31 범위 축소)

<a id="pl-04"></a>
## pl-04 · represent — 가장 좋은 결과를 고르고 고치기
- 이유: 엔진마다 결과가 다르다. 핸드오프는 가장 정확한 글이어야 한다.
- 무엇: 대표 엔진 고르기(정확도 + 풍부함), 투표로 줄 단위 합치기, 다투는 곳 OCR/VLM 다시 읽기, 엔진 사이 라벨·값 교차 확인, 글자 PDF 안 스캔 쪽 채우기, 표준 표(`tables_std`), 기호·위첨자/아래첨자 표준화, 표 잇기, 파싱 QA.
- 파일: `pipeline/transform/represent/represent.py`, `fuse.py`, `crosscheck.py`, `table_std.py`, `parse_qa.py`(재판독 `reread.py`·`reread_stage3.py`는 [pl-34](transform-cleanup.md#pl-34)에 지움).
- Status: done

<a id="pl-36"></a>
## pl-36 · 메일 첨부 파싱
- 이유(reference 비교(사용자 grill 10-30, 원본은 git 밖) P9): 서버에서 켜져 있어 요건 앵커를 단다.
- 무엇: `.eml`·`.msg` 첨부를 재귀 파싱(형식별 엔진, 깊이 `ATTACH_MAX_DEPTH` 기본 1, 크기 `ATTACH_MAX_MB` 20, 개수 `ATTACH_MAX_N` 10 상한), 인용 스레드 단락화, 대표 본문에 `[첨부 <파일명>]` 절로 덧붙임, 결과는 P0 원본 층에 캐시. 인라인 그림(cid)은 그림 기능이 맡음.
- 파일: `pipeline/transform/represent/attachments.py`.
- Status: done

<a id="pl-37"></a>
## pl-37 · 그림 근처 맥락 기록(신호 기록)
- 이유(reference 비교(사용자 grill 10-30, 원본은 git 밖) P9): 서버에서 켜져 있어 요건 앵커를 단다.
- 무엇: 그림 근처 본문 후보정 — 캡션 연결, 본문 언급, 값 일치·충돌 표시 — 와 그림 기록을 본문 청크 한 덩어리로 렌더.
- 파일: `pipeline/transform/represent/context.py`.
- Status: done

<a id="pl-05"></a>
## pl-05 · 그림
- 결정(사용자 10-31 범위 축소 grill): 그림 부가 기능(도표 화살표·겹침 묶음·중첩 그림·pptx 도형 연결·도형 감지·Mermaid 따로 만들기)을 **줄인다**: 그림마다 VLM 한 번에 종류별 출력 지시를 함께 보냄 — 도표 → Mermaid, 표 → HTML 표, 차트 → 세부 값. 차트 XML·벡터 값(chart_values)과 스캔 쪽 VLM은 유지. p1 code_fp — 0.2.0 배치.
- 이유: 차트·도식·이미지에는 글자 추출이 놓치는 값이 있다.
- 무엇: 이미지 VLM 설명(pdf, docx, xlsx, pptx, eml), VLM 없이 원본 차트 XML과 벡터 차트 값, 규칙 기반 도식 연결선, Mermaid 출력, 겹친 그룹, 중첩 그림, 스캔은 쪽 전체 VLM, 도형·슬라이드는 soffice 렌더, 전체 VLM 관문(기본 12).
- 파일: `pipeline/transform/figures/figures.py`, `charts.py`, `pptx_render.py`, `vgate.py`, `resources/prompts/pipeline/`.
- 11-01(`feature/scope-cut-unused`, 허브 지시): 그림 기록 검토 루프 `pipeline/transform/figures/figure_review.py`(독립 재추출 → 대조 → VLM 판정)와 그것만 쓰던 지시서 `figure_extract`·`figure_judge`, 시험, 이미지 `tool` 목록 자리, 설정 `pipeline.eval.review_max_rounds`(남으면 경고만)를 지움 — 파싱 흐름은 부르지 않던 도구. `common/ai`의 `vlm_judge` 역할 표는 code_fp 파일이라 남김.
- Status: done

<a id="pl-06"></a>
## pl-06 · 구조화 — 청크·메타데이터·임베딩
- 결정(사용자 10-31 범위 축소 grill): 묶음의 지식 그래프(kg_nodes·kg_edges)·개념 청크·이미지 행·doc_facts 생성을 **지운다**(아무도 적재·조회 안 함). parse_document의 facts는 남김. 구조화 code_fp 변경 — 0.2.0 배치.
- 이유: 검색에는 출처가 달린 청크와 메타데이터가 필요하다.
- 무엇: 청크 나누기 structure(기본, 800자, 제목, 표는 통째) / fixed 512+64 / sentence / page, 큰 표는 25행씩. 요약(앞부분 발췌 — OpenViking 요약은 10-29, LLM 요약은 op-08에 지움). 고객·계약은 교차 확인된 것만 남긴다. (묶음의 지식 그래프·개념 청크·그림 행·집계 사실은 11-01에 지움 — 아래 Status. 사실 추출 `facts.py`는 `parse_document`가 돌려주므로 남김.) 임베딩은 로컬(e5, bge-m3) 또는 내부 `api`.
- 파일: `pipeline/transform/structure/build_bundle.py`, `chunking.py`, `facts.py`, `draft_terms.py`, `common/ai/embed.py`.
- Status: done — 11-01(`feature/scope-cut-pipeline`) `build_bundle.py`가 `kg_nodes`·`kg_edges`(그래프)·`concept_chunk.jsonl`(개념 청크)·`images.jsonl`(그림 행)·`facts.jsonl`(집계 사실)을 더 만들지 않는다(`build_graph`·`build_concept_chunk`·`image_record`·`doc_facts` 지움). `facts.jsonl`을 읽던 검색 쪽 집계(`aggregate.py`)는 [mcp.md#mc-04](mcp.md#mc-04)(`feature/scope-cut-search`)가 지운다 — 이 행의 PR은 그 뒤에 병합(그 사이 합계가 0으로 나오지 않게). 그림 청크와 청크의 `image_ids`는 남김(검색 근거가 읽음). `kg_nodes.jsonl`·`kg_edges.jsonl`은 **빈 파일**로만 쓴다 — 묶음 계약 `common/core/contract.py` `check_bundle`의 파일 목록이 요구하고, 그 파일은 핸드오프 지문 파일이라 이번에 고치지 않음(0.2.0 배치에서 목록과 빈 파일을 함께 지움 — 허브에 넘김). 구조화 code_fp `s`: develop `94dd9d5` 0d9aa10b1bb5 → 이 브랜치 397296fe358b(나머지 지문은 develop과 같음).

<a id="pl-15"></a>
## pl-15 · structure/load 계약 점검이 새 묶음을 거부
- 결정(사용자 10-31 범위 축소 grill): structure/load DOC_KEYS 계약 점검은 서버가 쓰지 않으므로 고치지 않고 **지운다**.
- 이유: `contract.py`의 `DOC_KEYS`가 지운 키를 아직 기대한다(서버는 이 모듈을 쓰지 않음).
- 파일: `common/core/contract.py`(핸드오프 핑거프린트 — 사람 검토), `pipeline/cli.py`.
- 결정(사용자 10-30 PRD grill): A5 — 구조화·적재 계약 `DOC_KEYS`를 새 묶음 키에 맞게 고친다. 핸드오프 지문 파일이라 등급 A(사람 검토)이고 0.2.0 재처리에 함께 싣는다.
- 결정(사용자 11-01): 계약 점검(`common/core/contract.py`의 `DOC_KEYS`·`check_bundle`)은 0.2.0 지문 배치에서 코드째 지운다 — [transform-cleanup.md#pl-46](transform-cleanup.md#pl-46).
- Status: dropped (사용자 10-31 범위 축소)

<a id="pl-33"></a>
## pl-33 · 분류 단계 — silver 뒤, gold 앞

### 무엇·왜
- 문서마다 종류 라벨 `doc_class`를 붙인다. 대상은 SFDC와 LAS뿐이다(CRMS·FAQ·그 밖은 NULL — FAQ는 시트 이름 `FAQ_group`을 쓴다, [extract.md#pl-39](extract.md#pl-39)).
- 사용자 11-02: **운영 분류와 결과가 같아야 한다.** 판단 논리(라벨 집합·지시문 구조·근거·경계 규칙·확신도 기준)는 운영 그대로 두고, 흐름·부르는 순서만 우리 파이프라인에 맞게 줄인다. 기준 자료: `reference/pipeline_261030/adjustments/`의 SFDC·LAS 분류 문서(.md — git 밖).
- 자리: 파싱 결과 저장본(silver — Object Storage) 뒤, 검색 DB(gold — pgvector) 적재 전에 같은 흐름 안에서 한다. 적재가 `doc_class`를 함께 넣는다([ops.md#pl-24](ops.md#pl-24) 순서). 운영은 gold 적재 뒤 따로 분류하고 동기화 스크립트로 gold에 옮기는데, 그 동기화는 두지 않는다 — 입력이 같으면 라벨도 같다.
- 결정 이력: 0.2.0에 유지(사용자 10-31), 같은 sha256 묶음은 LLM 한 번·라벨만 전파·고객은 전파 안 함(reference 비교 C1·C3~C9, 사용자 10-30), 운영 ParsingMeta의 옛 라벨은 쓰지 않고 0.2.0 전체 e2e에서 새로 분류.

### 규칙
1. 모델은 서버 내부 GLM(운영과 같은 모델 이름)을 OpenAI 호환 대화 호출로, `reasoning_effort=high`, 답 길이 상한 4096 토큰으로 부른다. 호출은 `llm.chat`으로 예산 장부를 거친다(CLAUDE.md §7). 제한 시간은 SFDC 120초·LAS 180초(운영 값).
2. 같은 sha256 묶음은 SFDC에서 LLM을 한 번만 부른다. 대표 행 = `parse_status` ok가 skipped_dup보다 먼저 → 늦은 `parsed_at` → `parse_meta_id`. 라벨은 묶음 안 같은 원천의 다른 문서에도 붙는다. LAS는 운영 문서에 묶음 규칙이 없다 — `[미정]`(아래 결정 대기).
3. 본문 근거는 대표 결과 `.md`의 앞 8,000자(UTF-8, 깨진 바이트는 대체 문자)다. 대표 `.md`가 없으면 그 문서는 건너뛴다(NULL).
4. **SFDC 지시문 구조:** 시스템 쪽에 라벨 정의(`RFI`·`RFP`·`RFI+RFP`·`Proposal`·`Other` — 글자 그대로), 회사 용어(견적 개체는 제안서 쪽, 기회 개체는 RFP 쪽, 보낸/받은 채널 방향, 로그·계약 개체는 Other 쪽, 한·영 용어 대응), 경계 규칙을 둔다. 경계 규칙(운영 규칙을 우리 말로):
   - 회사 안에서 만든 입찰 평가·방어 자료는 RFP 계열이 아니라 Other.
   - 우리가 채운 RFI 질문서는 RFI.
   - 견적 보조 파일(원가 계산·일정)은 제안 묶음의 일부일 때만 Proposal, 아니면 Other.
   - `RFI+RFP`는 한 문서가 두 요청을 정말 함께 담을 때만 — 이름만 그런 단일 단계 문서는 그 단계 라벨.
   - 누가 쓴 문서인지는 파일 이름이 아니라 문서 안의 머리·연락처·표지로 정한다(고객 머리 + 입찰 안내 = RFP, "RFP"라는 이름의 파일 안 우리 제안 = Proposal).
   - 고객 RFP를 인용하거나 답하는 우리 제안은 Proposal.
5. **SFDC 사용자 쪽 근거:** 문서 제목·원본 파일 이름(늘), 개체 정보 묶음(개체 종류·채널 제목과 방향·기회 단계·키워드 묶음·파일 형식 — 운영 근거 파일과 이어질 때만, 안 이어지면 묶음째 뺌), 본문 8,000자.
6. **LAS 지시문 구조:** 라벨 `MSA`·`PSA`·`QAG`·`LOI`·`Amendment`·`Assignment Letter`·`Other`. 규칙(우리 말로): 기존 계약을 바꾸는 것은 모두 Amendment(QAG·LOI·TTA/SoW 변경 포함), 자료만 더하는 QAG 추가분은 QAG, 경개(novation)는 Assignment Letter, SoW·NDA/CDA·MTA/TTA·MOU·검토 메모·부속 서한·공급/제조·해지·전자서명 감사 기록·LOU는 늘 Other(LOU는 LOI가 아님). 확신도 상한: 근거가 모두 맞으면 0.90 이상, 애매하면 0.80, 부딪히면 0.60, 검토 메모는 0.75.
7. **LAS 사용자 쪽 근거:** "문서 정보" 묶음(원본 파일 이름·파일 형식, 계약 대장과 관리 번호로 이어질 때만 품의 제목·상대방 — 암호화된 대장 칸은 근거로 쓰지 않음), "키워드 근거" 묶음(코드가 정규식으로 미리 찾아 보여 줌: ① 본문 앞 300자의 자기 이름("THIS … AGREEMENT"), ② 공백을 정리한 앞 2,000자의 계약 종류 전체 이름, ③ 파일 이름 키워드(`_`는 공백 — QAG·PSA·LOI 약어는 허용, MSA는 전체 이름만), ④ 파일 이름의 변경 키워드, 보고서·메모 같은 제목 경고, 두 종류 이상이 걸리면 경고 + 확신도 0.80 이하), 본문 8,000자.
8. 답은 JSON(`class`, `confidence` 0~1) 하나다. 코드 울타리를 벗기고 첫 JSON 객체를 읽는다. 라벨은 집합 안의 값만 받는다(대소문자·공백·`rfp+rfi` 같은 별칭은 바로잡음). 집합 밖·참거짓·NaN이면 다시 묻는다(최대 3번) — 그래도 틀리면 NULL.
9. 낮은 확신 표시(`low_conf`)는 어디에도 두지 않는다(사용자 11-02 — 운영의 `doc_class_low_conf`는 옮기지 않음). 라벨은 확신도와 상관없이 쓴다.
10. 모델 이름 글자(`doc_class_model`) = `<모델>-<effort>-<yyyymmdd>`(실행 시작 때 한 번 정함). 라벨·지시문·기준값·effort 중 하나라도 바뀌면 새 글자가 되어야 한다. 이 글자와 분류 시각은 칸으로 두지 않는다(사용자 11-02 — 라벨을 만든 판은 ParsingMeta `gold_version`이 대신함 — 되돌리기 열쇠).
11. 분류는 적재 안에서 적재의 보통 silver 고르기로 한다(사용자 11-02). 분류가 실패하면 그 문서의 적재가 실패로 세어져 `gold_version`이 안 써지고, 다음 실행에서 다시 대상이 된다(추출의 유일한 선택 규칙 — [load-schema.md#pl-25](load-schema.md#pl-25)). 따로 다시 시도하는 고리·분류 명령은 없다. 이미 gold에 올라간 문서는 다시 고르지 않으므로 라벨을 덮어쓰지 않는다(운영과 같음).

### 예시
- SFDC 파일 이름 `XX_RFP_response.pdf`, 본문 첫 장이 우리 회사 표지·제안 내용 → 규칙 4(작성자는 문서 안으로) → `Proposal`(확신도 0.86).
- LAS 파일 이름 `QAG_Addendum_2.pdf`, 본문에 품질 합의서에 자료를 더한다는 내용만 → 규칙 6 → `QAG`. 같은 이름에 기존 조항을 바꾼다는 내용이면 `Amendment`.
- 답이 `{"class": "RFP+RFI", "confidence": 0.65}` → 별칭 바로잡음 `RFI+RFP`(확신도가 낮아도 라벨 그대로 — 표시 없음).
- (시험 자료로 쓸 때는 합성 문서 — 실제 회사 문서가 아니다.)

### 데이터·약속
- 지시문 파일은 `resources/prompts/pipeline/<이름>/`(SFDC·LAS 따로) — 지시문 지문(바이트 그대로, LF). 운영 지시문 글자를 그대로 옮기지 않고 위 규칙대로 새로 쓴다.
- 검색 DB(gold) 시스템별 `doc.doc_class` 칸 — #86이 만든다([load-schema.md#pl-28](load-schema.md#pl-28)).
- 결정(사용자 11-02): 라벨 `doc_class`만 gold 시스템별 `doc`에 둔다(이미 있음). 모델 글자·분류 시각·`low_conf` 칸은 어디에도 두지 않는다 — 판은 ParsingMeta `silver_version`·`gold_version`이 대신한다([load-schema.md#pl-25](load-schema.md#pl-25)). 운영이 ParsingMeta에 쓰던 분류 네 칸(`doc_class`·`doc_class_low_conf`·`doc_class_at`·`doc_class_model`)은 0.2.0에 지운다(refactor.md C-76).

### 단계
1. 대상 — 이번 적재가 올리는 SFDC·LAS 문서(적재 안에서).
2. SFDC는 sha256 묶음마다 대표 한 건, LAS는 문서마다(묶음 규칙 결정 전).
3. 근거 모으기(규칙 5·7) → 부르기(규칙 1, 일시 오류 — 5xx·429·시간 초과 — 는 지수 대기로 3번까지 다시) → 답 읽기(규칙 8).
4. 라벨은 문서 메타에 넣어 적재가 gold `doc`에 쓴다. 감사 파일에 한 줄.
5. 분류가 실패한 문서는 적재 실패로 세어 다음 실행에서 다시 대상이 된다(규칙 11).
- 결정 대기(사용자): 10-30 G10 결정("실패한 분류는 자동으로 다시 하지 않고 수동 명령으로만")이 운영(호출 안 3번 재시도 + 매 실행 NULL 다시 쓸기)과 다르다. 운영과 같게 하라는 11-02 결정을 따르면 G10을 바꿔야 한다 — 위 단계 3·5는 운영 쪽으로 적었다.
- 결정 대기(사용자): 운영 SFDC의 개체 정보는 10-21에 고정한 근거 파일에서 온다(그 뒤 파싱한 문서는 제목·파일 이름만). 같은 결과를 내려면 그 고정 파일을 쓸지, 지금 EDW·SFDC 표에서 다시 만들지.
- 결정 대기(사용자): LAS도 sha256 묶음으로 한 번만 부를지, 운영 LAS의 두 코드판(NULL 채우기용 짧은 근거·다시 분류용 전체 근거) 중 어느 쪽을 따를지, 대표 `.md` 고르기 규칙(SFDC는 `engine/` 밖 하나, LAS는 가장 늦은 시각)을 하나로 할지, 운영이 묶음의 `not_parsed` 행에도 라벨을 붙이는 것을 따를지.
- 구현은 #86 병합 뒤(#86이 `doc_class` 칸을 만든다). 코드 자리: `pipeline/transform/structure/`(새 파일), `pipeline/load/`.

### QA
- [미정] 시험 이름 — 구현 때 만든다: 라벨 별칭 바로잡기·집합 밖 NULL·0.70 경계·모델 글자 규칙·이미 있는 라벨 안 덮기를 표 행으로(가짜 LLM 답). 결과 비교는 [test.md#e2-20](test.md#e2-20) 분류 수용 보고서(개발 서버 정답 샘플과 일치율·혼동표).
- Status: todo — 0.2.0, #86 병합 뒤 구현. 설계 11-02(`feature/ops-trim`).

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| `pipeline structure/load` 모듈이 새 묶음을 받음 | 계약 `DOC_KEYS`가 거부(서버는 이 모듈을 안 씀) | `common/core/contract.py` | pl-15 |
| 스캔 쪽 숫자 고치기(AD47 — 이미지 위 숨은 글자, 예: 430.000 ↔ 430,000) | 쪽 VLM에는 낱말 상자가 없어 'hidden_overlap' 쪽은 원래 글을 유지 — OCR 대체 없음(사용자 10-29: 지금은 받아들임) | `represent.py` `fill_scan_pages` | pl-22 |

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- 메일 첨부: `.eml`/`.msg` 첨부를 재귀 파싱(깊이 1, 20 MB, 10개)하고 인용 스레드 접기(`ATTACH_*`). `represent/attachments.py`.
- 용어집 도구(약어 제안, EDW 마스터로 만드는 고객 목록). `transform/structure/glossary_suggest.py`, `gen_roster.py`. (위키 도구는 10-30에 지움 — [test.md#e2-18](test.md#e2-18).)
- 없음(그림자 모드는 op-08에 지움).

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| 큰 표를 행으로 나누기 | `CHUNK_TABLE` 비움(표는 통째) | — |
| 임베딩 | 이미지 기본 `PIPE_EMBED=api` | `EMBED_BASE_URL`, `EMBED_MODEL` |
| VLM 엔진, 그림, 쪽 VLM | 켜짐(OCR 엔진은 파싱에 안 돎 — pl-22·pl-46) | VLM 주소. 슬라이드·도형은 soffice(`SOFFICE_BIN`) |

### 10-29에 지운 기능(사용자 결정)
- 파싱 판단 에이전트(`PARSE_AGENT`, 기본 shadow — 결과를 바꾸지 않으면서 서버에서 LLM 세션을 열었음) — `77433fe`.
