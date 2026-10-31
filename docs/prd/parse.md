# 파싱 실행 — 엔진·스택·represent

[PRD.md](../PRD.md)의 카테고리 하나. 수집([etl.md](etl.md)) 다음, 구조화 앞 단계: 준비 → 엔진 스택 파싱 → represent(대표 결과 고르기·고치기) → 그림.
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서(주제별): 준비 pl-02 → 엔진 스택 pl-03·pl-22·pl-43·pl-31·pl-20·pl-17 → 확장자 pl-42 → represent·그림 pl-34·pl-04·pl-05·pl-36·pl-37 → 잔재 pl-35 → 코드와 다른 점.

<a id="pl-02"></a>
## pl-02 · 준비
- 결정(사용자 10-31 범위 축소 grill): 비슷한 문서 묶기(이름·내용 유사도, dhash·shingle)를 **지운다**. 완전히 같은 파일(sha256)은 **파싱만 한 번**(결과 재사용)하고 문서는 S3 키마다 따로 둔다(U-7 유지 — 메타가 키마다 다름). 이 경우는 별도로 적어 둔다(같은 sha256 다른 키 → 파싱 재사용 기록).
- 이유: 비싼 파싱 전에 쓸모없는 것을 거른다.
- 무엇: sha256 중복 제거 + 이름·내용이 비슷한 후보, RapidOCR 점수로 스캔 쪽 회전, DRM·암호 감지(msoffcrypto/pikepdf 복호화는 수동 CLI — `python -m pipeline.extract.secure_docs decrypt`, prepare·stream에 들어 있지 않음), 압축 파일은 미지원 표시.
- 파일: `pipeline/extract/prepare.py`, `pipeline/extract/dedup.py`, `pipeline/extract/secure_docs.py`.
- Status: done

<a id="pl-03"></a>
## pl-03 · 엔진 스택 파싱
- 이유: 모든 형식을 잘 다루는 파서 하나는 없다.
- 무엇: 파일 형식마다 스택의 모든 엔진이 돈다(대체 사슬이 아님). 형식당 최대 2개, 문서마다 병렬(10-29부터 phase 없음 — [pl-22](#pl-22)). 엔진마다 격리. 엔진 스택은 `struct.stack_version`에 판으로 둔다(PC: `pipeline_stack.json`). 형식: pdf(글자/이미지), doc(x), ppt(x), xls(x/m), hwpx, txt, html/htm, mht, eml, msg, png, jpg. 미지원: 옛 `.hwp`, zip.
- 파일: `pipeline/extract/run_all.py`, `pipeline/extract/engines/`(엔진 핑거프린트 — 바꾸려면 사람 검토), `resources/config/pipeline_stack.json`, `docs/architecture/pipeline_stack.md`.
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P1): 엔진 범위는 `stack` 그대로(형식당 2개) — 서버 settings.yaml에 `all`을 적지 않는다.
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([test.md#e2-10](test.md#e2-10)) — 비교는 필요할 때 다시 만든다. 엔진 비교 실험은 그때 stack json을 고쳐서 한다.
- 결정(사용자 10-30(-c5 전달)): 엔진 범위는 `stack` 하나 — 유일한 방식이자 기본. 형식별 엔진은 `resources/config/pipeline_stack.json`에 명시한다. `PARSE_ENGINE_SCOPE` `all`과 `--engines all` 길을 지운다(`pipeline/cli.py` `_set_engine_scope_default`, `pipeline.extract.engine_scope`, `common/config/sample.py`의 옛 값). 비교 실험은 stack json을 고쳐서 한다. 참고: 운영 reference 서버는 `all`로 돌았지만 사용자는 stack만 골랐다.
- Status: todo — `all` 길 지우기(10-30). 엔진 스택 파싱 자체는 done.

<a id="pl-22"></a>
## pl-22 · 파싱 phase 없애기 · 문서마다 엔진 병렬 · OCR 엔진 끔
- 이유(사용자 10-29): phase 1/2/3r은 쪽당 아주 짧은 제한으로 엔진을 다시 돌리고 시간 초과를 뒤로 미뤘다. `need_vlm` 규칙과 OCR 엔진이 이미지 문서를 느리게 하고 쪽 VLM과 겹쳤다.
- 실행: 문서마다 스택 엔진(형식당 최대 2개 — 넘으면 `stackcfg.over_limit` 설정 오류)을 병렬로, 엔진마다 격리된 자식 하나. 문서끼리는 `--workers`와 `--procs`(문서 조각)로 병렬.
- 제한: 문서×엔진마다 = 쪽 수 × `pipeline.extract.text_page_sec`(10) 또는 VLM 엔진은 `vlm_page_sec`(120), 엔진의 첫 문서는 `warmup_sec` 이상, 여기에 `isolate_overhead`. 시간 초과면 제한을 두 배로 한 번 다시, 그다음 실패 기록. 옛 phase 시간 초과 기록은 다시 시도한다.
- OCR 엔진: `rapidocr`, `rapidocr_ko`는 `pipeline.extract.ocr_engine`(기본 끔)일 때만 돈다 — 이미지·스캔 문서는 VLM 엔진만. 스택 표는 그대로.
- 글자 PDF 안 스캔 쪽: 더는 `.pdf_image` 엔진이 없다. represent가 그 쪽을 쪽 VLM으로 채운다(`vlm_page.page_text_pages`, 스캔 신호가 있는 쪽만, 병렬).
- 이미지·스캔 문서: 쪽마다 VLM 한 번. 대표가 이미지·스캔 형식(`.pdf_image`, png, jpg — run_all과 같은 형식 키)에서 글이 비지 않은 VLM 엔진이면 represent는 쪽 VLM을 건너뛰고 쪽 전체 그림을 처리된 것으로 표시한다(그림 VLM 없음, `vlm_page`가 없어도). 쪽 VLM은 `PARSE_POST`에 `vlm_page`가 있을 때만, 문서당 한 번(실패한 쪽은 다시 부르지 않음).
- VLM 엔진 자식의 `VLM_TIMEOUT` = min(`models.vlm.timeout`, `vlm_page_sec`).
- 우선순위: 일괄 엔진 자식은 낮은 우선순위로 돈다(`pipeline.extract.low_priority` — nice +10 / Windows BELOW_NORMAL. 한 세션·autogroup 안에서만 효과, 컨테이너끼리는 cgroup CPU 가중치 — C-65 ⑥).
- 파싱 서비스(`parse_document`)는 우선순위 낮추기를 끄고 자기 제한을 쓴다(`pipeline.service.parse_mcp.text_page_sec` 1, `vlm_page_sec` 60, `warmup_sec` 20 — 엔진 첫 기동). 작업 시간 초과면 프로세스 그룹 전체를 죽인다. `PARSE_MCP_OCR`은 `PARSE_OCR_ENGINE`으로 합쳤다.
- 알려진 손실: 'hidden_overlap' 쪽의 AD47 숫자 고치기(아래 "코드와 다른 점"). "처리됨"은 문서 단위라, 그 조건이 맞으면 VLM 엔진이 비워 둔 쪽은 쪽 VLM을 받지 않고, 섞인 `.pdf_image`의 글자 쪽에 들어 있는 그림은 그림 VLM을 받지 않는다.
- 지움: `--phase(s)`, `--rescue`, `--vlm-all`, `--need-vlm`, `--timeout`, `PARSE_PHASES`, `PARSE_PHASE_SEC`, `PARSE_MCP_OCR`, `PHASE2_FAILED`.
- 파일: `pipeline/extract/run_all.py`, `pipeline/stackcfg.py`, `pipeline/config.py`, `pipeline/cli.py`, `pipeline/mcp_parse_service.py`, `pipeline/transform/represent/represent.py`, `pipeline/transform/figures/vlm_page.py`, `deploy/host/scripts/run_docs.py`.
- 시험: `tests/server/pipeline/test_run_all.py`(over_limit, OCR 스위치, page_timeout, 옛 phase 시간 초과), `tests/server/pipeline/test_vlm_page.py`(`pick_pages`), `tests/general/pipeline/test_represent.py`(쪽 VLM 채우기).
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

<a id="pl-31"></a>
## pl-31 · ocr_vlm·vlm.model_alt 삭제
- 이유(사용자 10-30 grill): ocr_vlm은 엔진 스택(`pipeline_stack.json`)에 없어 쓰이지 않고, `vlm.model_alt`는 figure_review 판정이 이미 기본으로 `vlm.model`을 쓴다 — 설정·코드만 늘린다.
- ocr_vlm — 0.1.0에서 통째로 지운다:
  - 설정 `common.models.ocrvlm.*`(`OCRVLM_BASE_URL`·`OCRVLM_MODEL`·`OCRVLM_API_KEY`), 파이프라인 `ocrvlm_prompt`(`OCRVLM_PROMPT`).
  - `registry.py` 항목, `VLM_ENGINES`·`run_all`, `mcp_parse_service`의 ocr 묶음, `phase_report`·`summarize`·`report.py`의 라벨, `catalog.json` 행, `adk`·`llm`의 역할 표.
  - 엔진 파일 `pipeline/extract/engines/qwen_vlm/parser.py` 안의 ocr_vlm 코드 — qwen_vlm 엔진 핑거프린트가 바뀌어 이미지·스캔 문서를 다시 파싱한다. 0.1.0은 어차피 재처리라 받아들임. 검토 등급 A: 엔진 파일은 사용자가 검토. 스택은 그대로(ocr_vlm은 `pipeline_stack.json`에 없음).
- `vlm.model_alt`(`VLM_MODEL_ALT`) 지움: figure_review 판정은 `vlm.model`(지금 기본값 — 결과 그대로). `parsing_meta.py`의 대체 길을 고치고 `model_matrix`의 연결을 뺀다. 옛 키는 `Section.REMOVED`(경고만).
- settings.yaml에 남김: `llm.extra_body`·`vlm.extra_body`·`embed.query_prefix` — 값이 모델에 따라 달라짐(예: thinking 끄기, [settings.md#op-05](settings.md#op-05)).
- 파일(10-30 grep — ocr_vlm·ocrvlm·model_alt가 나오는 곳): `common/config/{settings,keyscan}.py`, `pipeline/config.py`, `common/ai/{adk,llm,guard}.py`, `common/check/ping_models.py`, `common/store/services.py`, `pipeline/extract/engines/{registry.py,qwen_vlm/parser.py}`, `pipeline/extract/run_all.py`, `pipeline/mcp_parse_service.py`, `pipeline/cli.py`, `pipeline/shared/{phase_report,summarize}.py`, `pipeline/eval/report.py`, `pipeline/transform/figures/figure_review.py`, `pipeline/transform/represent/parse_qa.py`, `pipeline/load/parsing_meta.py`, `resources/config/report_templates/catalog.json`, `deploy/docker/Dockerfile`, `validation/e2e/model_matrix.py`, `validation/search_ui/{serve.py,start_mcp.sh}`, `tests/server/common/test_settings.py`, `settings.sample.yaml`.
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P3·T11): 같은 0.1.0 엔진 묶음에서 설치·사용하지 않는 엔진도 지운다 — rapidocr v1, docling, unstructured, kreuzberg_ocr(+ ocr_vlm). **docx2python은 남김**(e2-06 비교용 — C7로 비교 도구는 지우므로 남길 이유는 다시 볼 것). 검토 등급 A. 파일: `pipeline/extract/engines/{docling,unstructured,rapidocr,kreuzberg,qwen_vlm}`, registry `CORE`, `pipeline/check_env.py`.
- C7(사용자 10-30 PRD grill): 비교 도구(`model_matrix`·`score_gold`·`mcp_eval` 등)는 두지 않는다([test.md#e2-10](test.md#e2-10)) — 비교는 필요할 때 다시 만든다.
- Status: done (10-30) — `vlm.model_alt`는 `feature/fp-batch`(#27), ocr_vlm은 `feature/drop-ocrvlm`: 엔진·설정(`common.models.ocrvlm`·`ocrvlm_prompt` → `Section.REMOVED`)·역할 표·라벨·`catalog.json` 행 지움. 엔진 재파싱 키(`run_all.engine_code_fp`): `qwen_vlm` `52ca47bc4c6e` → `7381bf2b79d2`, 나머지 25개 그대로, `ocr_vlm` 없어짐(27 → 26). 레이어 code_fp도 바뀜(공용·레이어 파일 — `engines/registry.py`의 CORE 목록 포함): p0 `840199fcacb6` → `2a828b0470c1` · p1 `08cd37047cbd` → `deb6efc4a5f0` · r `b706f28ce48e` → `0d4fcc7a4cbc` · s `eb0597ed7f7b` → `bd154d04467a`(FINGERPRINT `abe9b7b0799ceaae`·a 그대로). 검토 등급 A(엔진 파일·`engines/registry.py` — 사용자). · 남은 정리(`feature/ocrvlm-leftovers`, 등급 A): qwen_vlm 파서의 ocr_vlm용 인자 `pre`·`prompt` 지움(`qwen_vlm` `7381bf2b79d2` → `06f937fcc39e`) · fuse `_OCR_FAMS`의 `ocr-vlm` 지움(p1 `deb6efc4a5f0` → `9ee173300a82`) · VLM 엔진 집합은 `run_all.VLM_ENGINES` 한 곳(phase_report·report가 가져다 씀).
- 남은 일 — 끝(10-30 `feature/pl31-engines`, 등급 A): 엔진 8개 지움(18개 남음) · `marker_llm` 이름 정리 · 등록부 도구 API 지움 · CORE 정리 — refactor.md 부록 2.

<a id="pl-20"></a>
## pl-20 · 엔진 스택 사본 파일 방식 검토
- 이유: C-50.
- 파일: `pipeline/config.py`(`paths.stack_snapshot`), `docs/architecture/pipeline_stack.md`.
- 사용자 10-30: 스냅샷 파일 대신 silver는 Object Storage uuid 폴더, 메타는 EDW ParsingMeta(단계별·성공 시), gold는 pgvector만.
- Status: done — 대체됨(10-30): [etl.md#pl-32](etl.md#pl-32)가 대신함(`_stack/stack-v*.json`·`STACK_SNAPSHOT` 지움).

<a id="pl-17"></a>
## pl-17 · 파싱 단계 위치 — `extract` 또는 `transform`
- 결정(사용자 10-31 범위 축소 grill): 파싱 단계를 transform/parse/로 옮기기를 **하지 않는다**(속도·품질 영향 없음). 행 닫음.
- 이유: 옮기면 code_fp p0가 바뀐다. 첫 배포 전이 가장 싸다(C-61).
- 결정(사용자 10-29 grill): `pipeline/extract/{engines/,run_all.py,parse_one.py}` → `pipeline/transform/parse/`로 옮긴다. `run_all.py` → `run_parse.py`로 이름을 바꾼다(문서 × 엔진 파싱만 함 — "run all"은 e2e로 읽힘). `extract/`에는 source · rdb_discover · dedup · prepare가 남는다. 옮기는 커밋과 이름 바꾸는 커밋을 나눈다(CLAUDE.md §1). 엔진 핑거프린트는 `_LEGACY_NAMES`로 유지. code_fp p0는 바뀌지만 첫 적재가 전체 e2e라 지금은 공짜([etl.md#pl-23](etl.md#pl-23)).
- 파일: `pipeline/extract/`, `pipeline/transform/`, `common/core/artifacts.py`(`LAYER_CODE`), `pipeline/cli.py`, 문서와 명령 표.
- 결정(사용자 10-30 PRD grill): S6 — 0.2.0에 함께(전체 재처리라 추가 비용 없음). 파일 이동이 많아 0.2.0 작업의 마지막에 한다.
- Status: todo — 0.2.0(사용자 10-30 PRD grill C1·S6), 검토 등급 A(핑거프린트).

<a id="pl-34"></a>
## pl-34 · 파싱 p1 묶음 — 재판독(P2·P3)·scan_dedup·렌더 OCR 신호 지우기
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P2·P5·T10): 재판독 P3(`reread_stage3.py`, 프롬프트 `value_choice`)를 코드에서 지우고, 같은 p1 묶음에서 scan_dedup(`scan_dedup.py`)과 렌더 OCR 신호(`figures/vlm_page.py`의 신호 부분)도 지운다. `_page_texts`는 `fill_scan_pages`가 쓰므로 남긴다. [pl-04](#pl-04)(represent)의 일부를 걷어냄.
- code_fp p1이 바뀜 — 0.1.0 핑거프린트 묶음, 검토 등급 A.
- 한 것(10-30 `feature/pl34-p1-cleanup`):
  - 결정 보탬(사용자 10-30, 허브 전달): 재판독은 P3만이 아니라 **전부**(P2 `reread.py` 좌표 재판독 OCR 포함) 끄고 지운다 — 같은 PR(p1 한 번만 바뀜).
  - 지움: `reread.py`(재판독 P2 — 근소·한 계열 조각을 좌표로 다시 OCR) · `reread_stage3.py`(재판독 P3 — 그림 경계 OCR·VLM 선택형) · `scan_dedup.py`(스캔 쪽 OCR/VLM 중복 제거) · 프롬프트 `resources/prompts/common/value_choice` · `vlm_page.py`의 렌더 OCR 신호(`_render_ocr_chars`·`ocr_chars` 칸·이유 `ocr_gt_text`). `_page_texts`(+ `_doc_page_count`)는 `represent.py`로, 그림 crop OCR이 쓰던 `reread._default_ocr`(+ 임시 폴더 `output/_reread_tmp`)는 `figures.py`로 옮김(로직 그대로). `represent._engine_out_rank`(P2 폴백 전용)도 지움. 적재 `parsing_meta.py`의 role='reread' 행·요약 조각을 지움(표 구조는 그대로 — 그 행이 안 생길 뿐).
  - 설정 칸 지움(옛 설정 파일에 남아 있으면 경고만 — `REMOVED`): `pipeline.extract.{dedup_scan,signal_ocr,ocr_gt_max}`, `pipeline.transform.represent.fuse_reread_p3`, `pipeline.transform.represent.{fuse_reread,reread_fallback_best}`, 절 `pipeline.transform.represent.reread` 통째(dpi·margin·max·pad_pt·p3_img_max·vlm_max·vlm_max_tokens).
  - 같이 고침: `run_docs.py`가 넘기던 `--set PARSE_FUSE_REREAD_P3=0`·`FUSE_REREAD_MAX=3`·`FUSE_REREAD_DPI=120`과 `mcp_parse_service.py`의 `PARSE_FUSE_REREAD_P3=0`(칸이 없어져 `--set`이 거부할 것이라 지움 — **배포 때 코드와 `deploy/host/`를 같이 바꿀 것**, 옛 run_docs.py가 남으면 모든 파싱 레인이 종료 2) · 측정 도구 `server_checks ar1`의 재판독 설정(P2·P3)·`--run-vlm`·P3 호출 추정, `ar6`의 P3 충돌 추정.
  - 바뀐 동작: 재판독(P2·P3, 기본 켬)이 근소·미확인 조각을 다시 읽어 승자를 바꾸던 것이 없어짐 — 융합(P1) 결과의 split·미확인이 그대로 남고 rep.fused에 `reread` 칸이 안 생김(AI.ParsingMeta의 role='reread' 행도 안 생김). 렌더 OCR 신호·dedup은 기본 꺼짐이라 기본 동작 그대로. 쪽 신호 캐시(`page_signals@v3`)는 그대로 씀(옛 캐시의 `ocr_chars` 칸은 안 봄).
  - 핑거프린트: p1 `660fa1588e57` → `81cfe39fd09e`(서버 문서 후보정 다시 — 0.1.0 묶음). FINGERPRINT·p0·r·s·엔진 키 그대로.
  - 안 한 것: `common/ai/{adk,agent_prompts}.py` 주석의 `reread_stage3`·`value_choice` 언급은 그대로(`adk.py`는 p1·s·r 셋 모두의 지문에 들어가 주석만 고쳐도 서버 재청크·재임베딩 — 허브 10-30, s/r이 바뀌는 판에 같이). 옛 캐시 폴더 `_reread_p3/_vlm_cache`는 `purge_caches` 목록에 남겨 정리되게.
- 파일: `pipeline/transform/represent/{represent,fuse}.py`, `pipeline/transform/figures/{vlm_page,figures}.py`, `pipeline/load/parsing_meta.py`, `pipeline/shared/{meaning,artifacts}.py`, `pipeline/config.py`, `common/core/artifacts.py`(LAYER_CODE p1 목록), `common/config/sample.py`, `pipeline/{mcp_parse_service,eval/server_checks}.py`, `deploy/host/scripts/run_docs.py`, 시험(`test_vlm_page`·`test_server_checks`·`test_agent_prompts`·`test_paths`·`test_represent`·`test_run_docs`).
- Status: done (10-30 `feature/pl34-p1-cleanup`, 등급 A)

<a id="pl-35"></a>
## pl-35 · 핑거프린트 영향 없는 잔재 지우기
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P4·P6·T12): (registry 도구 API·`marker_llm` — pl-31로 옮겨 10-30 지움) `pipeline/parse_parallel.py`, `figures/figures_resume.py`, `shared/phase_report.py`, 고아 프롬프트 `parse_agent`·`parse_decide`·`parse_decide_vlm`, `AUTO_REPARSE_CHANGED`(pl-23 — 증분만)를 지운다.
- 파일: `pipeline/extract/engines/registry.py`, `pipeline/extract/run_all.py`, 위 모듈들, `resources/prompts/pipeline/`, `pipeline/config.py`.
- Status: done (10-30 `feature/pl35-leftovers`, 허브) — `pipeline/parse_parallel.py`(OP26 문서 단위 병렬)와 그 갈래·설정 절 `pipeline.extract.parallel`·`dev.parallel_test_crash` 지움(옛 칸은 경고만) · `AUTO_REPARSE_CHANGED`(`pipeline.extract.auto_reparse_changed`) 지움(pl-23 — 증분만) · `figures/figures_resume.py`는 pl-32 2c(#49)에서 지움 · 고아 프롬프트 `parse_agent`·`parse_decide`·`parse_decide_vlm`은 이미 폴더가 없음(주석에만 이름이 남음 — 공용·층 파일이라 핑거프린트 때문에 그대로) · `shared/phase_report.py`는 남김(운영 도구 `eval/run_board.py`가 `FIX`·`kind`를 씀 — 허브 규칙) · registry 도구 API·`marker_llm`은 엔진 핑거프린트 변경이라 [pl-31](#pl-31) 남은 일로 옮김. · figures_resume 남은 흔적: 층 파일 `figures.py`·`represent.py`의 주석과 `figures_max` 인자·`capped.jsonl` 쓰기(지우면 p1 핑거프린트가 바뀌어 이 행 범위 밖 — 다음 핑거프린트 묶음에서).

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

<a id="pl-42"></a>
## pl-42 · 지원 확장자 더하기 — .jpeg·.tif·.tiff·.bmp·.mhtml(+ .hwpx 시험)
- 결정(사용자 10-30(-c5 전달)): `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.mhtml`을 지원 형식에 더하고 시험한다. `.hwpx`도 시험에 넣는다.
- 확장자마다 `tests/server`에 파싱 시험 하나 — `valid_env`에 그 형식 파일이 없으므로 시험이 임시 폴더에 샘플을 만든다(CLAUDE.md §6-4).
- 형식별 엔진은 `resources/config/pipeline_stack.json`에 명시([pl-03](#pl-03) — stack 하나). 스택 표 변경은 `struct.stack_version` 새 판(`set-stack`).
- 한 것(10-31): PC 파일 `pipeline_stack.json`에 `.jpeg`·`.tif`·`.tiff`·`.bmp` = `rapidocr_ko`·`qwen_vlm`(`.jpg`와 같음 — OCR은 `ocr_engine` 켤 때만), `.mhtml` = `mhtml`·`kreuzberg`(`.mht`와 같음). 엔진 코드·형식 판별 코드는 그대로(다섯 형식 모두 엔진 `FORMATS`와 represent·그림 목록에 이미 있음). 시험 `tests/server/pipeline/test_ext_formats.py` — 형식마다 임시 견본을 만들어 파싱(이미지는 VLM 호출만 가짜), 엔진 구성 목록·형식당 2개·고르는 엔진 확인. 배포한 판 1 시드(`resources/sql/0002_stack_seed.json`)는 고치지 않음.
- 사람이 할 일(서버, refactor.md C-69): 새 판 넣기 — `dc run --rm load set-stack --parse ".jpeg=rapidocr_ko,qwen_vlm;.tif=rapidocr_ko,qwen_vlm;.tiff=rapidocr_ko,qwen_vlm;.bmp=rapidocr_ko,qwen_vlm;.mhtml=mhtml,kreuzberg" --reason "pl-42 확장자 추가"` → `dc run --rm load show-stack --history 3`(되돌리기 `set-stack --activate <앞 판> --reason …`). 넣기 전에는 이 형식들이 핵심 엔진 합집합으로 돈다.
- 파일: `resources/config/pipeline_stack.json`, `tests/server/pipeline/test_ext_formats.py`, `docs/architecture/pipeline_stack.md` §3-1.
- Status: done (10-31, feature/pl42-more-ext)

<a id="pl-04"></a>
## pl-04 · represent — 가장 좋은 결과를 고르고 고치기
- 이유: 엔진마다 결과가 다르다. 핸드오프는 가장 정확한 글이어야 한다.
- 무엇: 대표 엔진 고르기(정확도 + 풍부함), 투표로 줄 단위 합치기, 다투는 곳 OCR/VLM 다시 읽기, 엔진 사이 라벨·값 교차 확인, 글자 PDF 안 스캔 쪽 채우기, 표준 표(`tables_std`), 기호·위첨자/아래첨자 표준화, 표 잇기, 파싱 QA.
- 파일: `pipeline/transform/represent/represent.py`, `fuse.py`, `crosscheck.py`, `table_std.py`, `parse_qa.py`(재판독 `reread.py`·`reread_stage3.py`는 [pl-34](#pl-34)에 지움).
- Status: done

<a id="pl-05"></a>
## pl-05 · 그림
- 결정(사용자 10-31 범위 축소 grill): 그림 부가 기능(도표 화살표·겹침 묶음·중첩 그림·pptx 도형 연결·도형 감지·Mermaid 따로 만들기)을 **줄인다**: 그림마다 VLM 한 번에 종류별 출력 지시를 함께 보냄 — 도표 → Mermaid, 표 → HTML 표, 차트 → 세부 값. 차트 XML·벡터 값(chart_values)과 스캔 쪽 VLM은 유지. p1 code_fp — 0.2.0 배치.
- 이유: 차트·도식·이미지에는 글자 추출이 놓치는 값이 있다.
- 무엇: 이미지 VLM 설명(pdf, docx, xlsx, pptx, eml), VLM 없이 원본 차트 XML과 벡터 차트 값, 규칙 기반 도식 연결선, Mermaid 출력, 겹친 그룹, 중첩 그림, 스캔은 쪽 전체 VLM, 도형·슬라이드는 soffice 렌더, 전체 VLM 관문(기본 12).
- 파일: `pipeline/transform/figures/figures.py`, `charts.py`, `pptx_render.py`, `vgate.py`, `resources/prompts/pipeline/`.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| 스캔 쪽 숫자 고치기(AD47 — 이미지 위 숨은 글자, 예: 430.000 ↔ 430,000) | 쪽 VLM에는 낱말 상자가 없어 'hidden_overlap' 쪽은 원래 글을 유지 — OCR 대체 없음(사용자 10-29: 지금은 받아들임) | `represent.py` `fill_scan_pages` | pl-22 |
| DRM·암호 파일을 흐름 안에서 복호화 | 복호화는 수동 CLI(`python -m pipeline.extract.secure_docs decrypt`) | `secure_docs.py` | pl-02 |

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- 없음(그림자 모드는 op-08에 지움).

### 기본 꺼짐·설정 필요
| 기능 | 스위치 = 기본값 | 필요한 것 |
|---|---|---|
| VLM 엔진, 그림, 쪽 VLM | 켜짐(OCR 엔진은 꺼짐 — `PARSE_OCR_ENGINE=0`, pl-22) | VLM 주소. 슬라이드·도형은 soffice(`SOFFICE_BIN`) |

### 10-29에 지운 기능(사용자 결정)
- 파싱 판단 에이전트(`PARSE_AGENT`, 기본 shadow — 결과를 바꾸지 않으면서 서버에서 LLM 세션을 열었음) — `77433fe`.
