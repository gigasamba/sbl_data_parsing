# 변환 — 파싱 정리·지문 배치

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md)의 하위 문서. 엔진·p1 지문이 바뀌는 정리 묶음(pl-31·pl-34·pl-35)과 0.2.0 지문 배치(pl-46·pl-47) — 모두 검토 등급 A(CLAUDE.md §4).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-31 · pl-34 · pl-35 · pl-46 · pl-47 · pl-49 · pl-50.

<a id="pl-31"></a>
## pl-31 · ocr_vlm·vlm.model_alt 삭제
- 이유(사용자 10-30 grill): ocr_vlm은 엔진 스택(`pipeline_stack.json`)에 없어 쓰이지 않고, `vlm.model_alt`는 figure_review 판정이 이미 기본으로 `vlm.model`을 쓴다 — 설정·코드만 늘린다.
- ocr_vlm — 0.1.0에서 통째로 지운다:
  - 설정 `common.models.ocrvlm.*`(`OCRVLM_BASE_URL`·`OCRVLM_MODEL`·`OCRVLM_API_KEY`), 파이프라인 `ocrvlm_prompt`(`OCRVLM_PROMPT`).
  - `registry.py` 항목, `VLM_ENGINES`·`run_all`, `mcp_parse_service`의 ocr 묶음, `phase_report`·`summarize`·`report.py`의 라벨, `catalog.json` 행, `adk`·`llm`의 역할 표.
  - 엔진 파일 `pipeline/extract/engines/qwen_vlm/parser.py` 안의 ocr_vlm 코드 — qwen_vlm 엔진 핑거프린트가 바뀌어 이미지·스캔 문서를 다시 파싱한다. 0.1.0은 어차피 재처리라 받아들임. 검토 등급 A: 엔진 파일은 사용자가 검토. 스택은 그대로(ocr_vlm은 `pipeline_stack.json`에 없음).
- `vlm.model_alt`(`VLM_MODEL_ALT`) 지움: figure_review 판정은 `vlm.model`(지금 기본값 — 결과 그대로). `parsing_meta.py`의 대체 길을 고치고 `model_matrix`의 연결을 뺀다. 옛 키는 `Section.REMOVED`(경고만).
- settings.yaml에 남김: `llm.extra_body`·`vlm.extra_body`·`embed.query_prefix` — 값이 모델에 따라 달라짐(예: thinking 끄기, [ops-settings.md#op-05](ops-settings.md#op-05)).
- 파일(10-30 당시 grep — ocr_vlm·ocrvlm·model_alt가 나오는 곳. 그 뒤 `adk.py`·`ping_models.py`·`services.py`·`pipeline/eval/`·`summarize.py`·`model_matrix.py` 등은 지움 — 지금 위치는 코드에서 찾을 것): `common/config/{settings,keyscan}.py`, `pipeline/config.py`, `common/ai/{adk,llm,guard}.py`, `common/check/ping_models.py`, `common/store/services.py`, `pipeline/extract/engines/{registry.py,qwen_vlm/parser.py}`, `pipeline/extract/run_all.py`, `pipeline/mcp_parse_service.py`, `pipeline/cli.py`, `pipeline/shared/{phase_report,summarize}.py`, `pipeline/eval/report.py`, `pipeline/transform/figures/figure_review.py`, `pipeline/transform/represent/parse_qa.py`, `pipeline/load/parsing_meta.py`, `resources/config/report_templates/catalog.json`, `deploy/docker/Dockerfile`, `validation/e2e/model_matrix.py`, `validation/search_ui/{serve.py,start_mcp.sh}`, `tests/server/common/test_settings.py`, `settings.sample.yaml`.
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P3·T11): 같은 0.1.0 엔진 묶음에서 설치·사용하지 않는 엔진도 지운다 — rapidocr v1, docling, unstructured, kreuzberg_ocr(+ ocr_vlm). **docx2python은 남김**(e2-06 비교용 — C7로 비교 도구는 지우므로 남길 이유는 다시 볼 것). 검토 등급 A. 파일: `pipeline/extract/engines/{docling,unstructured,rapidocr,kreuzberg,qwen_vlm}`, registry `CORE`, `pipeline/check_env.py`.
- Status: done (10-30) — `vlm.model_alt`는 `feature/fp-batch`(#27), ocr_vlm은 `feature/drop-ocrvlm`: 엔진·설정(`common.models.ocrvlm`·`ocrvlm_prompt` → `Section.REMOVED`)·역할 표·라벨·`catalog.json` 행 지움. 엔진 재파싱 키(`run_all.engine_code_fp`): `qwen_vlm` `52ca47bc4c6e` → `7381bf2b79d2`, 나머지 25개 그대로, `ocr_vlm` 없어짐(27 → 26). 레이어 code_fp도 바뀜(공용·레이어 파일 — `engines/registry.py`의 CORE 목록 포함): p0 `840199fcacb6` → `2a828b0470c1` · p1 `08cd37047cbd` → `deb6efc4a5f0` · r `b706f28ce48e` → `0d4fcc7a4cbc` · s `eb0597ed7f7b` → `bd154d04467a`(FINGERPRINT `abe9b7b0799ceaae`·a 그대로). 검토 등급 A(엔진 파일·`engines/registry.py` — 사용자). · 남은 정리(`feature/ocrvlm-leftovers`, 등급 A): qwen_vlm 파서의 ocr_vlm용 인자 `pre`·`prompt` 지움(`qwen_vlm` `7381bf2b79d2` → `06f937fcc39e`) · fuse `_OCR_FAMS`의 `ocr-vlm` 지움(p1 `deb6efc4a5f0` → `9ee173300a82`) · VLM 엔진 집합은 `run_all.VLM_ENGINES` 한 곳(phase_report·report가 가져다 씀).
- 남은 일 — 끝(10-30 `feature/pl31-engines`, 등급 A): 엔진 8개 지움(18개 남음) · `marker_llm` 이름 정리 · 등록부 도구 API 지움 · CORE 정리 — refactor.md 부록 2.

<a id="pl-34"></a>
## pl-34 · 파싱 p1 묶음 — 재판독(P2·P3)·scan_dedup·렌더 OCR 신호 지우기
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P2·P5·T10): 재판독 P3(`reread_stage3.py`, 프롬프트 `value_choice`)를 코드에서 지우고, 같은 p1 묶음에서 scan_dedup(`scan_dedup.py`)과 렌더 OCR 신호(`figures/vlm_page.py`의 신호 부분)도 지운다. `_page_texts`는 `fill_scan_pages`가 쓰므로 남긴다. [pl-04](transform.md#pl-04)(represent)의 일부를 걷어냄.
- code_fp p1이 바뀜 — 0.1.0 핑거프린트 묶음, 검토 등급 A.
- 한 것(10-30 `feature/pl34-p1-cleanup`):
  - 결정 보탬(사용자 10-30, 허브 전달): 재판독은 P3만이 아니라 **전부**(P2 `reread.py` 좌표 재판독 OCR 포함) 끄고 지운다 — 같은 PR(p1 한 번만 바뀜).
  - 지움: `reread.py`(재판독 P2 — 근소·한 계열 조각을 좌표로 다시 OCR) · `reread_stage3.py`(재판독 P3 — 그림 경계 OCR·VLM 선택형) · `scan_dedup.py`(스캔 쪽 OCR/VLM 중복 제거) · 프롬프트 `resources/prompts/common/value_choice` · `vlm_page.py`의 렌더 OCR 신호(`_render_ocr_chars`·`ocr_chars` 칸·이유 `ocr_gt_text`). `_page_texts`(+ `_doc_page_count`)는 `represent.py`로, 그림 crop OCR이 쓰던 `reread._default_ocr`(+ 임시 폴더 `output/_reread_tmp`)는 `figures.py`로 옮김(로직 그대로). `represent._engine_out_rank`(P2 폴백 전용)도 지움. 적재 `parsing_meta.py`의 role='reread' 행·요약 조각을 지움(표 구조는 그대로 — 그 행이 안 생길 뿐).
  - 설정 칸 지움(옛 설정 파일에 남아 있으면 경고만 — `REMOVED`): `pipeline.extract.{dedup_scan,signal_ocr,ocr_gt_max}`, `pipeline.transform.represent.fuse_reread_p3`, `pipeline.transform.represent.{fuse_reread,reread_fallback_best}`, 절 `pipeline.transform.represent.reread` 통째(dpi·margin·max·pad_pt·p3_img_max·vlm_max·vlm_max_tokens).
  - 같이 고침: `run_docs.py`가 넘기던 `--set PARSE_FUSE_REREAD_P3=0`·`FUSE_REREAD_MAX=3`·`FUSE_REREAD_DPI=120`과 `mcp_parse_service.py`의 `PARSE_FUSE_REREAD_P3=0`(칸이 없어져 `--set`이 거부할 것이라 지움 — **배포 때 코드와 `deploy/host/`를 같이 바꿀 것**, 옛 run_docs.py가 남으면 모든 파싱 레인이 종료 2) · 측정 도구 `server_checks ar1`의 재판독 설정(P2·P3)·`--run-vlm`·P3 호출 추정, `ar6`의 P3 충돌 추정.
  - 바뀐 동작: 재판독(P2·P3, 기본 켬)이 근소·미확인 조각을 다시 읽어 승자를 바꾸던 것이 없어짐 — 융합(P1) 결과의 split·미확인이 그대로 남고 rep.fused에 `reread` 칸이 안 생김(AI.ParsingMeta의 role='reread' 행도 안 생김). 렌더 OCR 신호·dedup은 기본 꺼짐이라 기본 동작 그대로. 쪽 신호 캐시(`page_signals@v3`)는 그대로 씀(옛 캐시의 `ocr_chars` 칸은 안 봄).
  - 핑거프린트: p1 `660fa1588e57` → `81cfe39fd09e`(서버 문서 후보정 다시 — 0.1.0 묶음). FINGERPRINT·p0·r·s·엔진 키 그대로.
- 파일: `pipeline/transform/represent/{represent,fuse}.py`, `pipeline/transform/figures/{vlm_page,figures}.py`, `pipeline/load/parsing_meta.py`, `pipeline/shared/{meaning,artifacts}.py`, `pipeline/config.py`, `common/core/artifacts.py`(LAYER_CODE p1 목록), `common/config/sample.py`, `pipeline/{mcp_parse_service,eval/server_checks}.py`, `deploy/host/scripts/run_docs.py`, 시험(`test_vlm_page`·`test_server_checks`·`test_agent_prompts`·`test_paths`·`test_represent`·`test_run_docs`).
- Status: done (10-30 `feature/pl34-p1-cleanup`, 등급 A)

<a id="pl-35"></a>
## pl-35 · 핑거프린트 영향 없는 잔재 지우기
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) P4·P6·T12): (registry 도구 API·`marker_llm` — pl-31로 옮겨 10-30 지움) `pipeline/parse_parallel.py`, `figures/figures_resume.py`, `shared/phase_report.py`, 고아 프롬프트 `parse_agent`·`parse_decide`·`parse_decide_vlm`, `AUTO_REPARSE_CHANGED`(pl-23 — 증분만)를 지운다.
- 파일: `pipeline/extract/engines/registry.py`, `pipeline/extract/run_all.py`, 위 모듈들, `resources/prompts/pipeline/`, `pipeline/config.py`.
- Status: done (10-30 `feature/pl35-leftovers`, 허브) — `pipeline/parse_parallel.py`(OP26 문서 단위 병렬)와 그 갈래·설정 절 `pipeline.extract.parallel`·`dev.parallel_test_crash` 지움(옛 칸은 경고만) · `AUTO_REPARSE_CHANGED`(`pipeline.extract.auto_reparse_changed`) 지움(pl-23 — 증분만) · `figures/figures_resume.py`는 pl-32 2c(#49)에서 지움 · 고아 프롬프트 `parse_agent`·`parse_decide`·`parse_decide_vlm`은 이미 폴더가 없음(주석에만 이름이 남음 — 공용·층 파일이라 핑거프린트 때문에 그대로) · registry 도구 API·`marker_llm`은 엔진 핑거프린트 변경이라 [pl-31](#pl-31) 남은 일로 옮김.

<a id="pl-46"></a>
## pl-46 · 0.2.0 지문 배치 정리 — 안 쓰는 엔진·묶음 계약·OCR 대체 길
- 결정(사용자 11-01, reference ↔ 저장소 비교): 0.2.0 지문 배치에서 함께 지운다(코드는 그때 — 지금은 기록만, 검토 등급 A).
  - 한 번도 안 돈 엔진 `pdfplumber`·`pypdf`·`calamine`·`python_pptx`·`pymupdf4llm`과 `registry` `CORE` 항목, 엔진 구성의 `candidates` 칸. **`docx2python`은 남긴다**(사용자 — 비교용).
  - 묶음 계약 `common/core/contract.py`의 `DOC_KEYS`·`check_bundle`(빈 `kg_nodes.jsonl`·`kg_edges.jsonl` 포함), 그림 `capped.jsonl` 잔재.
  - `extract.ocr_engine` 스위치와 대표 결과의 OCR 대체 길(`represent`의 `_ocr_pages`·`_hidden_overlap_conflict`). `rapidocr` 엔진 파일은 남김(`prepare.py`·`figures.py`가 씀). 이 스위치를 없앨 때 `pipeline_stack.json`의 이미지 확장자 행(지금 `rapidocr_ko`·`qwen_vlm`)도 같은 변경에서 `qwen_vlm` 하나로(11-01 `.pdf_image`는 이미 바꿈 — [pl-03](transform.md#pl-03)).
  - `common/core/paths.py:112` 주석의 `parse_shadow` 언급(11-01 지시서 지움 — 고치면 레이어 code_fp가 바뀌어 미룸), `common/ai/{adk,llm}.py`의 `vlm_judge` 역할 표(11-01 `figure_review` 지움 — 부르는 곳 없음).
- 결정(사용자 11-01, reference ↔ 저장소 2차 비교 — 같은 0.2.0 지문 배치):
  - `common/core/fingerprint.py`의 `_LEGACY_NAMES`·`_HANDOFF_LEGACY` 옛 이름 대응을 정리(이름 바꾸기 — 핸드오프 지문이 바뀜).
  - 첫 이관용 호환 코드를 지운다 — (11-02 한 것: `common/config/migrate.py`의 env 변환·`--compare`·`settings_env.sh`의 `pipeline.env` 안내 — `feature/migrate-trim`) `keyscan`의 지울 후보, `image_vars.sh`의 옛 이미지 이름, `trigger.sh`의 `pipeline.env` 거부, entrypoint `legacy_tool_name`, 절마다 둔 `REMOVED` 목록, `pin_env`의 옛 env 경고. **두 서버가 settings.yaml로 옮긴 뒤**(refactor.md 37행 — 이관 확인)에만.
  - 로컬 임베딩 모델 길 — `common/ai/embed.py`의 sentence-transformers, `build_bundle`의 `bge-m3` 기본값, `check_env`의 HF 점검.
  - `common/core/paths.py`의 `TEMPLATES_DIR`·`PIPELINE_ROOT`·`RETRIEVAL_ROOT` 상수(11-01 보고서 틀 폴더는 지움).
  - `pipeline/transform/structure/facts.py`의 `contract_facts`·`MONEY_RE`·`DATE_RE`·`L_*`.
  - `build_bundle`의 같은 뜻 선택지 `--summary auto|lead`(둘 다 앞부분 발췌).
  - 빈 레이어 `a`(code_fp `e3b0c44298fc` = 빈 집합).
  - `run_all`·`progress.py`의 `PROGRESS.md` 쓰기(`is_env_error`는 남김).
  - `common.store.run_mode`의 `Literal` 값 `test`(11-01 `--mode test` 표본 모드 지움 뒤).
  - 낡은 `# noqa — 영구 다리` 주석.
  - `deploy/docker/requirements-image.txt` 머리 주석의 옛 `requirements-models.txt` 언급(11-01 파일 지움 — 고치면 `deps_hash`가 바뀌어 다음 이미지 빌드 때).
- 결정(사용자 11-01 — 같은 배치의 구조 단순화):
  - 점검 셋(`check_env`·`services`·`ping_models`)을 점검기 하나로.
  - 작게 나뉜 파일을 합친다 — `pipeline/shared/{artifacts,meaning,text}.py`, `pipeline/extract/resources.py`, `pg_load_connect.py`, `pg_mcp_connect.py`.
  - 지운 칸 목록(`REMOVED`)을 `common/config/layout.py` 표 하나로.
  - entrypoint `TOOL_PKGS`를 고정 표로.
  - compose 덧씌우기 파일을 4개에서 2개로.
- 11-01(`feature/scope-cut-unused2`): 원천 목록 `sources.json`을 지우며 설정 칸 `common.paths.sources_file`은 남겼다 — `common/config/settings.py`를 고치면 레이어 code_fp 4개가 바뀌어 이 배치에서 지운다. `common/core/fingerprint.py` `EXCLUDED_FILES`의 `core/sources.py` 줄도 같이.
- 11-01(같은 브랜치): PC Docker 스모크에서 `s3://` 원천(MinIO 대역·게시 ⑥)과 자정 배치 모양을 지우며 쓰이지 않게 된 설정 칸 `smoke_source`·`smoke_nightly`(`common/config/settings.py`)와 MinIO 올리기 도구 `common/check/os_put.py`도 이 배치에서 지운다.
- 11-01(`feature/mcp-ops-parity`, mc-16): 이름 있는 색인(AD41)을 지우며 설정 칸 `common.paths.index_root`(`INDEX_ROOT`)·`INDEX_CONF`·`INDEX_CONF_DIR`은 남겼다(`common/config/settings.py`를 고치면 레이어 code_fp 4개가 바뀜 — 이 배치에서). `common/core/fingerprint.py` `EXCLUDED_FILES`의 `core/index_cfg.py` 줄도 같이.
- 결정(사용자 11-02 — 허브 전달, 같은 0.2.0 지문 배치):
  - 죽은 설정 칸 `minio_image`·`minio_publish_port`·`smoke_pm_bucket`(`common/config/settings.py:1244·1245·1268` — 11-01 PC 스모크에서 MinIO를 지운 뒤 읽는 곳 없음).
  - `settings.py`의 `__main__`(설정 확인 명령)이 `common.config.show`를 import하고 `show`가 `export`를 import해서(`settings.py:1637`, `show.py:11`), 두 도구 파일이 모든 레이어의 code_fp 의존이 된다 — 명령 입구를 `settings.py` 밖으로 옮겨 이 import를 끊는다(그 뒤 `show`·`export`를 고쳐도 레이어 지문이 바뀌지 않음).
  - 형식당 엔진 수 상한 `MAX_PER_TYPE`·`over_limit`를 지운다(`pipeline/stackcfg.py:9·17`, `pipeline/extract/run_all.py:51·197·251·466` — run_all은 p0 지문 의존).
- 할 일(#86 병합 뒤 — todo):
  - 엔진 구성 읽기를 `pipeline.config.stack()` 하나로 — `stackcfg.snapshot_bytes`, `cfgfile`의 `body_sha`·`label`, `schemas/config_body.py` 모양 검사를 그 안으로 합친다.
  - 0.2.0이 서버에 배포된 뒤: `dbtool`의 비교(`dbcompare`)와 `stamp`(옛 코드가 만든 스키마에 실행 없이 판만 기록 — 첫 이관용)를 지운다.
- 더할 것(사용자 11-02): `common/ai/adk.py` — 지시문(프롬프트)은 두고 장치(에이전트 실행 틀)는 `llm.py` 호출 하나로 줄인다(`adk.py`는 p1·s·r 지문에 들어가 이 배치에서). CPU 부하 고침도 이 배치에 함께 싣는다.
- 한 것(11-03 `feature/pl46-fp-batch` — #104 위, 허브 지시 · 등급 A): 안 쓰는 엔진 5개·`candidates` 칸 · `MAX_PER_TYPE`·`over_limit` · `extract.ocr_engine` 스위치·대표 결과의 OCR 대체 길(`_ocr_pages`·`_hidden_overlap_conflict`·`vlm_page.hidden_overlap_spans`)·구성의 이미지 행 `qwen_vlm` 하나 · 묶음 계약 `DOC_KEYS`·`CHUNK_KEYS`·`check_bundle`·빈 kg 파일·`capped.jsonl` · 죽은 설정 칸(`sources_file`·`index_root`·`INDEX_CONF`·`INDEX_CONF_DIR`·`smoke_source`·`smoke_nightly`·`minio_image`·`minio_publish_port`·`smoke_pm_bucket`·load·publish 컨테이너 자원 칸 — `REMOVED`로, 남으면 경고만)·`os_put.py`·`run_mode` 값 `test` · `settings.py` `__main__` → `python -m common.config.show` · `paths.py` 상수 3개·`parse_shadow` 주석·`vlm_judge` · `_LEGACY_NAMES`·`_HANDOFF_LEGACY`·`legacy_names` · `contract_facts` 등·`--summary`·`PROGRESS.md` 쓰기·낡은 영구 다리 주석·빈 층 `a` · 엔진 구성 모양 검사를 `cfgfile.py` 한 곳으로·`stackcfg.snapshot_bytes`. 지문(전 develop `e3c803c` — #104·#102·#87 → 후): FINGERPRINT `2f1da6a1567d24a8` → `543ade95fde0fcae` · p0 `49a4f1ef727b` → `39f4dc7e1231` · p1 `00f70a8d23b4` → `2e1e9dd3814a` · r `b0c120bd58ec` → `3ac22cd1c74e` · s `53d3357d2208` → `5eb430cc1cff` · 층 a 지움 · 엔진 지문 13개 모두 바뀜(표는 PR 본문).
- 한 것 2(11-03 — 사용자 답, 허브 전달): CPU 부하 고침(`common/core/resources.py` `cpu_load` — cgroup CPU 한도가 있으면 그 컨테이너 사용량, 없으면 부하 평균 ÷ 호스트 코어) · 첫 이관용 호환 코드 지움(`image_vars.sh` 옛 이미지 이름·`pipeline.env` 문구·entrypoint `legacy_tool_name`·`pin_env` 옛 env 알림·`keyscan` 지울 후보) · 절마다 두던 `REMOVED`를 `common/config/layout.py` `REMOVED` 표 하나로(0.1.0 settings.yaml은 여전히 경고만) · 점검기 하나 `common/check/checker.py`(env·services·ping — 옛 `check_env`·`services`·`ping_models`, PG 연결 고르기는 `common/store/pg.py`) · entrypoint `tool` 고정 표 · 작은 파일 합침(`pipeline/shared/canon.py`·`parse_run.py`, `pipeline/extract/resources.py` → `common/core/resources.py`, `pg_load_connect` → `pgvector_load`, `pg_mcp_connect` → `server_state`) · 로컬 임베딩 길 지움 · `common/ai/adk.py` 지움 — 모델 호출은 `common/ai/llm.py` `complete()` HTTP 한 길, PC 답변 점검의 도구 왕복은 `validation/e2e/tool_loop.py`.
- 남은 것: 0.2.0 배포 뒤 `dbcompare`·`stamp` 지우기(todo).
- 할 일(todo, 다음 이미지 빌드 때 — 사용자 11-03): `deploy/docker/requirements*`에서 `sentence-transformers`(로컬 임베딩 길 지움)와, 쓰지 않게 되면 `google-adk`·`litellm`(`adk.py` 장치 지움 — 아래)을 뺀다. `deps_hash`가 바뀌어 새 이미지 버전이 필요하다(지금 브랜치는 requirements를 건드리지 않음).
- Status: done — `feature/pl46-fp-batch`(#106) 병합(0.2.0 — 엔진·핸드오프·레이어 지문 바뀜, 사람 검토). 남은 것(todo): 0.2.0 배포 뒤 `dbcompare`·`stamp` 지우기 · 다음 이미지 빌드 때 requirements에서 `sentence-transformers`·`google-adk`·`litellm` 빼기(`deps_hash` 바뀜 — 새 이미지 버전).

<a id="pl-47"></a>
## pl-47 · 엔진 지문(p0) 범위가 다른 이름 폴더의 엔진을 놓치는지 확인
- 이유(허브 점검 11-01): `common/core/artifacts.py:24` p0 범위는 `pipeline/extract/engines/{engine}/**`다. 엔진 이름과 폴더 이름이 다른 엔진 — `html_stdlib`·`msg_extract`(`mhtml/` 안), `rapidocr_ko`, `office`, `pptx` — 은 그 엔진 파일을 고쳐도 다시 파싱되지 않을 수 있다.
- 할 일: 엔진마다 실제 파서 파일이 p0 범위에 드는지 확인하고, 빠지면 범위를 고친다(엔진 지문이 바뀜).
- 검토 등급 A · 0.2.0.
- 확인(11-03 `feature/fp-perf`): 문서×엔진 재사용 열쇠(`run_all.engine_code_fp` — 등록부의 스택 폴더 + `_common`)는 이름이 다른 엔진도 제 폴더(`mhtml/`·`office_stdlib/`·`rapidocr/`)를 이미 해시하고 있었다(`pptx` 엔진은 pl-46에 지움). 문제는 층 지문 p0 범위였다 — `pipeline/extract/engines/{engine}/**`의 `{engine}`이 글자 그대로 남아 엔진 파일을 **하나도** 담지 않았다(`run_all.py`·common 의존만).
- 한 것: p0 범위를 `pipeline/extract/engines/**/*.py` + `run_all.py`로 고쳤다(엔진 파일은 그대로 — 층 지문 p0만 바뀜). 쓰는 곳이 없던 `code_fp("p0:<엔진>")` 형태는 지웠다. 시험: `tests/server/pipeline/test_run_all.py` `test_p0_layer_covers_every_engine_folder`(등록부의 모든 엔진 스택 폴더가 p0 범위 안).
- Status: done — 11-03 `feature/fp-perf`(0.2.0 지문 배치 후속, 등급 A).

<a id="pl-49"></a>
## pl-49 · 0.2.0 지문 배치 후속 — 같은 결과로 덜 읽고 덜 띄우기(fp-perf)
- 무엇·왜(사용자 11-03 "최대한 다 0.2.0에"): 허브 점검(develop d7ae4e6)에서 찾은 같은 일 되풀이를 줄인다. 결과(대표 결과·묶음)는 바이트 그대로 —
  같은 문서로 전·후를 돌려 비교한다(아래 확인). 지문이 바뀌는 파일을 건드리므로 pl-46과 같은 0.2.0 배치에 싣는다(등급 A).
- 한 것(`feature/fp-perf`):
  - 고객 명부·용어 사전을 파일(경로·고친 시각)마다 한 번만 읽음 — `common/core/terms.py` `_aliases`·`load_glossary`(B2).
  - 대표 결과: 엔진마다 문단 나누기 한 번(B3) · 그림 근처 맥락의 문장 나누기를 문서마다 한 번(B4, `represent/context.py`) · 끝 요약에서 `_rep/<문서>.json`을 문서마다 한 번(B6).
  - 엔진 지문(`engine_code_fp`)·엔진 버전을 프로세스마다 한 번, 목록 찾기를 집합으로(B5).
  - 문서 1건 폴더(run_docs 흐름)의 중복 확인을 자식 프로세스 없이(B7).
  - 원본 파일 sha256을 프로세스마다 파일당 한 번 — `common/core/contract.py` `file_hash`(경로·크기·고친 시각으로 기억, C2) · 중복 확인 매니페스트도 파일이 그대로면 한 번만 읽음(C5).
  - 엔진 결과 JSON을 자식(`parse_one`)이 출처(provenance)까지 넣어 한 번에 씀 — 부모가 다시 읽고 다시 쓰던 것 없앰(C4).
  - 메모리·CPU 문 기다림을 띄우기 잠금 밖에서(C6 — 잠금 안 재확인으로 "한 번에 하나씩" 규칙은 그대로).
- 확인: 같은 문서 4건(docx·xlsx·eml·pdf)으로 파싱 → 묶음(임베딩 없음)을 전·후 돌려 대표 결과·엔진 결과·묶음 JSON을 비교(시각·지문 칸만 뺌) — 같음.
- Status: done — 11-03 `feature/fp-perf`(0.2.0 지문 배치, 등급 A).

<a id="pl-50"></a>
## pl-50 · 층 지문 범위 바로잡기 + 단계 방향 자동 점검
- 이유(구조 검토 11-03): ① 결과를 바꾸는 파일 2개 — 대표 결과 점수 `pipeline/transform/represent/repfmt.py`, 고객 이름 찾기 `pipeline/transform/structure/terms.py` — 가 층 목록(`common/core/artifacts.py` `LAYER_CODE`)에 없어 고쳐도 p1·s 지문이 그대로였다(임시 복사본에서 확인). ② 기록(`jsonlog`) → DB 기록(`logsink`) → 표 정의(`store/db/`)로 이어져 DB 표 칸 하나만 고쳐도 네 층 지문이 모두 바뀌었다. ③ extract → transform → load 방향은 리뷰에서만 확인했다.
- 참고: 문서별 엔진 결과 재사용은 층 지문이 아니라 엔진 폴더만 보는 `run_all.engine_code_fp`로 정한다. 서버가 문서를 다시 처리할지는 `run_docs.py`가 ParsingMeta의 끝난 키로 정한다(코드가 바뀌어도 저절로 다시 처리하지 않음 — 전체 재처리는 판 올릴 때 사람이 정함). 층 지문은 실행 기록·대표 결과 정보에 남는 값이다.
- 한 것:
  - 층 목록에 두 파일을 넣음. 결과를 만들지 않는 오프라인 도구는 `NOT_LAYER`에 적음. `tests/server/common/test_code_fp.py`가 `pipeline/transform` 아래 빠진 파일을 잡는다.
  - `CODE_FP_SKIP` — 기록·DB 연결·표 정의·설정 도구 파일은 지문 계산에서 따라가지 않음. 설정 모델(`config/settings.py`)은 기본값이 결과를 바꿀 수 있어 그대로 둠. 같은 시험이 "표 정의·기록 파일은 지문 그대로, 위 두 파일은 p1·s만 바뀜"을 확인한다.
  - `common/check/check_modules.py` ⑫ — 뒤 단계를 import하면 위반(함수 안 늦은 import 포함). 지금 예외 1곳: `qwen_vlm` 엔진 → `transform.figures.vgate`(엔진 파일을 옮기면 엔진 지문이 바뀌어 0.3.0 지문 배치로).
- 검토 등급 A(code_fp) · 0.2.0(어차피 전체 재처리).
- Status: done — 11-03 `feature/stage-direction`.
