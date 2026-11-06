# 수집 — 원천·가져오기·준비

[PRD.md](../PRD.md) 카테고리. 원천에서 문서를 받아(pl-01·pl-48) 준비(중복·회전·DRM — pl-02)하기까지와 FAQ 원천(pl-39). 다음 단계는 [transform.md](transform.md).

순서: pl-01 · pl-02 · pl-58 · pl-59 · pl-48 · pl-39.

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기

### 무엇·왜
파싱 입력을 정한다. 문서 목록의 기준은 EDW `AI.FileStorageMap`이고, 파일은 Object Storage에서 `s3_key`로 받는다.

### 규칙
1. 파싱 입력(`--source`, 설정 `extract.source.source_input_location`)은 둘 중 하나여야 한다 — 폴더, 또는 `rdb:csv:<경로>`(문서 위치 표 CSV). 그 밖의 값이면 → 오류로 멈춘다.
2. `rdb:csv`의 칸 이름은 설정 `tuning.extract.source_columns`가 정한다 — 기본 `source_column_doc_id`=`id`, `source_column_storage_key`=`s3_key`, `source_column_filename`=`original_filename`, `source_column_file_size`=`file_size`, `source_column_content_version`=`content_version_id`, `source_column_source_system`=`source_system`.
3. 대상 목록은 컨테이너 안 `python -m pipeline.extract.candidate_pick list`가 FileStorageMap에서 고른다(파일 이름 키워드 `--filter`, 작은 파일부터 — 규칙은 [ops.md#pl-10](ops.md#pl-10)·[pl-23](ops.md#pl-23)). 설정 `required.source.source_systems`(원천 목록)가 있으면 `source_system` 칸이 그 값인 행만 고른다(대소문자 무관 — 목록에 `FAQ`가 없으면 FAQ 먼저·교체 확인도 하지 않음, 비우면 모든 행). PC `rdb:csv` 받기(`rdb_pick`)도 같은 목록으로 거르고, 목록 밖 행은 건너뜀으로 기록하지 않는다. 원천 값은 들어오는 자리에서 대문자로 바꾼다(`FAQ`·`DEV-1`). 목록 파일·`batch.csv`(칸 `source_system` — 이름은 `tuning.extract.source_columns.source_column_source_system`)·manifest는 그 행의 `source_system` 값을 그대로 넘긴다([load-schema.md#pl-28](load-schema.md#pl-28) 규칙 3). 서버 러너 `run_pipeline.py`는 그 목록 파일을 읽어 문서마다 `batch.csv`(한 줄)를 만든다. 끝난 문서(gold `doc.file_path`)·영구 건너뜀(`except_doc_info` `skip`)을 뺄 때는 FileStorageMap `s3_key`를 그대로 비교한다 — 그 두 표의 원본 키는 `s3://버킷/` 앞머리가 없는 키라, FileStorageMap `s3_key`도 앞머리 없이 적혀 있어야 빠진다(앞머리가 붙은 행은 받기는 되지만 매번 다시 고름).
4. 받기는 staging 하나다: `python -m pipeline.extract.candidate_ready stage --csv <batch.csv> --out <문서 폴더> --prepared <준비 폴더>`가 원본을 `extract.source.source_staging_dir` 폴더(`<sha1(버킷|키)>.bin`)에 받고(받아 둔 판의 ETag가 지금과 같을 때만 다시 받지 않음), 문서 폴더 `_source_files/`에 하드 링크로 놓은 뒤 같은 단계에서 중복·거르기([pl-02](#pl-02))까지 해 파싱할 이름을 `parse/_source/only.txt`에 적는다. 파싱은 `pipeline.cli parse --staged`로 그 목록만 읽는다. staging 칸이 비었거나 받지 못한 문서는 멈춘다(따로 받는 길 없음). PC의 `pipeline.cli parse --source`도 같은 함수(`stage_batch`)를 부른다.

### QA
- `tests/server/pipeline/test_candidate.py`(`test_stage_batch` 등) · `tests/server/pipeline/test_span_stages.py::test_staging_span_counts` · `tests/server/pipeline/test_rdb_discover.py` · `tests/server/pipeline/test_target_list.py`(원천 목록 거르기·시작 관문).
- Status: done

<a id="pl-02"></a>
## pl-02 · 준비 — 중복·회전·DRM

### 무엇·왜
비싼 파싱 전에 같은 파일·읽을 수 없는 파일을 거르고, 돌아간 스캔을 바로잡는다. 받기와 같은 단계(`candidate_ready.stage_batch`)에서 하고, 거르기를 지난 문서만 파싱한다.

### 규칙
1. `stage_batch`는 세 단계를 이 순서로 한 번씩 한다 — ① 받기(`resolve` → rdb:csv는 `download`로 staging에 받음) ② 중복 제외(`_dedup` — 이번 묶음 이름만, 받은 파일의 sha256 — 문서 1건이면 묶을 것이 없어 지문·보고서를 쓰지 않음) ③ 거르기(`filter_and_rotate` — DRM·암호·미지원, 회전). 각 단계는 앞 단계를 지난 문서만 본다. 거르기를 지난 이름은 `<결과 폴더>/parse/_source/only.txt`에 남고 `pipeline.cli parse --staged`가 그것만 파싱한다. MCP 파싱 작업(`run_mcp_parsing`)도 같은 거르기(`filter_and_rotate`)를 직접 부른다. 같은 내용 거르기는 이 ② 한 곳이다(파싱 `parse_engines`는 사본 복사를 하지 않음 — pl-03).
2. 중복 판정 키는 **받은 파일 내용의 sha256**이다(S3 키·이름이 달라도 내용이 같으면 중복). 두 가지를 뺀다.
   - 같은 묶음 안: 이번에 고른 이름만 해시한다(받는 폴더에 앞 실행이 남긴 파일은 보지 않음). 같은 sha256 묶음에서 하나만 남긴다. 남길 파일은 `deduplication.py` `run_folder()` 순서로 고른다: 이름에 사본 표시(`(1)`·`사본` 등)가 없는 것 → 수정 시각이 늦은 것 → 큰 파일.
   - 이미 끝난 문서: gold `doc` 행(원천 스키마 5벌 어디든)이 같은 `sha256`을 **다른 원본 키**로 가지면 뺀다(`candidate_pick.done_by_sha` — `pipeline/shared/gold_docs.py`). sha256(`contract.file_hash` — 소문자 16진 64자)은 받기(`resolve`)가 문서마다 한 번 구해 `manifest.jsonl`(`sha256`·해시한 파일의 [크기, 고친 시각 ns] `sha256_stat`)에 적고, 중복 거르기·거르기·파싱(`parse_engines`)·구조화(`gold_bundle`)·게시는 같은 파일이면 그 값을 쓴다(`pipeline/shared/srcsha.py` `sha_of`). manifest는 묶음마다 한 번 쓴다. 같은 원본 키면 그 문서의 재처리라 남긴다. gold를 못 읽으면 `done_keys()`와 같다(서버는 종료 4, PC는 이 확인 없이 진행).
3. 빠진 중복은 `<결과 폴더>/dedup/keep.txt`에 없고(나머지 폴더 파일은 그대로 있음), `applog.except_doc_info`에 `skip` `duplicate_sha256`으로 남는다(다음 실행이 다시 고르지 않음 — [pl-58](#pl-58)). 서버 러너는 받기가 뺀 문서(`only.txt`가 빔 — 중복·DRM·암호)를 파싱 실패가 아니라 건너뜀으로 세고 게시와 원본 삭제를 그대로 한다(pl-24). 문서는 S3 키마다 따로 둔다(키마다 메타가 다름).
4. 회전 바로잡기는 `extract.prepare.rotate_pages`(기본 `false`)가 켜졌을 때만 한다. 꺼져 있으면 회전용 OCR을 하지 않고 파일을 그대로 놓는다. 서버 러너는 `ops.run_pipeline.parse.batch_rotate_scans`(기본 `false`)가 꺼져 있으면 `stage --no-scan-rotate`로 이미지 PDF(스캔)는 돌리지 않는다.
5. 켜져 있으면 이미지·스캔 PDF 쪽마다 4방향(0·90·180·270도) RapidOCR 점수를 스레드 4개로 동시에 재고 가장 높은 방향으로 돌린다 — 같으면 0도, 모두 0이면 그대로. 기록은 `output/prepared/rotation.csv`(파일·쪽·각도·네 방향 점수·회전 전 원본 sha256 `orig_sha256`).
6. DRM·암호 파일은 감지해서 표시하고 건너뛴다(상태 `skipped_drm`, `prepared/_records/skipped.jsonl`). 복호화는 흐름 안에서 하지 않고 수동 명령 `python -m pipeline.extract.protected_docs decrypt`로만 한다.
7. 압축 파일(zip)은 지원하지 않는다고 표시한다. 처리 엔진 없는 확장자(`registry.engines_for`가 빈 것)는 두 곳에서만 거른다 — 받기 전 `candidate_pick.rdb_pick`(`_filter_unsupported_rows` — rdb:csv 대상 고르기), 받은 뒤 `filter_and_rotate`(`unsupported_*`). 파일 크기 상한(`extract.max_source_file_mb`)은 파싱(`parse_engines`)이 본다.
8. 중복·DRM·암호·미지원으로 건너뛴 문서는 문서마다 `applog.pipe_event`에 한 행을 남긴다(`pipeline/shared/runtrace.py` `skip_event` — 단계 `extract.skip`, `doc_id` = 파일 이름, `status=skip`, `err_kind=doc`, `err`·`metrics.reason` = 이유 `dup_batch`·`dup_done`·`dup_run`·`drm_*`·`encrypted_*`·`unsupported_*`, 중복이면 `metrics.dup_of` = 남긴 문서 — 같은 묶음은 파일 이름, 끝난 문서·이번 실행은 원본 키). 받기 전(`rdb_pick`)에 뺀 지원 안 하는 확장자도 같은 행을 남긴다. 다시 받아도 같은 결과인 문서는 [pl-58](#pl-58).

### QA
- `tests/server/pipeline/test_stage_batch.py`(받기 → 중복 제외 → 거르기 사례 표: 같은 묶음 중복·끝난 문서 중복(gold 대역)·같은 키 재처리·DRM·미지원·보통 문서, 건너뜀 행·`skip` 행) · `tests/server/pipeline/test_doc_record.py`(`done_by_sha`) · `tests/server/pipeline/test_publish_parse.py::test_stage_dropped_docs`(받기가 뺀 문서 → 올림·처리 기록 없음) · `tests/server/pipeline/test_prepare.py`(`test_rotation_off_by_default` 등) · `tests/general/pipeline/test_dedup.py`(`run_folder` 대표 고르기).
- Status: done

<a id="pl-58"></a>
## pl-58 · 영구 건너뜀 문서는 다시 고르지 않음

### 무엇·왜
지원 안 하는 확장자·확장자 없음·DRM·암호 문서는 다시 받아도 파싱할 수 없다. 기록이 없으면 밤마다 같은 문서를 다시 받고 `--max-docs` 자리를 차지한다(사용자 11-05).

### 규칙
1. 건너뛴 이유가 `unsupported_*`·`drm_*`·`encrypted_*`·`duplicate_sha256`(같은 묶음·이번 실행·끝난 문서와 같은 내용 — [pl-02](#pl-02)·[pl-59](#pl-59))이면 → `applog.except_doc_info`에 원본 키(`source_key` — `s3_key`, 폴더 원천은 상대 경로·이름)당 `except_type` `skip` 한 행을 쓴다. 칸: `source_system`(그 행의 FileStorageMap `source_system` 값 — manifest에서)·`file_name`·`reason`(확장자 없는 이름의 지원 안 함은 `no_extension`)·`level`(`error`)·`first_seen`·`last_seen`·`count`. 같은 키·종류가 다시 오면 `last_seen`·`count`·이유만 바꾼다(`pipeline/shared/except_docs.py` `record`).
2. 쓰는 곳은 세 곳이다 — 받기 전 `candidate_pick.rdb_pick`(`_record_source_skipped`), 받은 뒤 `candidate_ready.stage_batch`(`_record_filtered` — `filter_and_rotate`의 `prepared/_records/skipped.csv`), 내용 중복 `candidate_ready._dedup`.
3. 파싱·게시·적재 실패는 `except_type` `error` 행(`record_error` — 기록만, 다음 실행이 다시 시도 — [ops.md#op-17](ops.md#op-17) 규칙 16).
4. `candidate_pick list --skip-done`은 gold에 끝난 키와 함께 이 표의 `skip` 키를 뺀다(`skipped_keys` — `error` 키는 빼지 않음). `--skip-done`이 없으면 빼지 않는다(사람이 다시 돌려 볼 때).
5. 표는 applog 판 `0003_applog`(Alembic — 옛 `skip_doc_info` 행을 `skip`으로 옮김)가 만든다 — 앱은 DDL을 실행하지 않는다. PG 접속 정보가 없으면(PC) 대역 sqlite `<standin_dir>/applog.sqlite`에 표 정의로 바로 만든다. 서버(dev·prd)는 대역을 쓰지 않고 멈춘다. `ops.log.log_db_enabled`와 관계없이 쓴다.

### QA
- `tests/server/pipeline/test_skip_docs.py`(이유 사례 표 → 쓴 행·횟수 · `error` 행은 따로·빼지 않음 · rdb:csv가 모두 지원 안 함이면 0건으로 끝남 · `list --skip-done`이 `skip`만 뺌) · `tests/server/pipeline/test_stage_batch.py`(거르기가 뺀 DRM·압축과 내용 중복이 표에 들어감) · `dbtool check --target applog`(DB 판).
- Status: dev

<a id="pl-48"></a>
## pl-48 · 병렬 다운로드

### 무엇·왜
큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 쓰지 않는다.

### 규칙
1. `candidate_ready`의 staging 받기(`download`)는 `extract.source.source_fetch_threads`(기본 1 = 차례대로)개 스레드로 받는다(서버 러너는 `ops.run_pipeline.staging.staging_fetch_threads`를 `--set`으로 넘김).
2. 서버 러너 `run_pipeline.py`는 받기 워커 `ops.run_pipeline.staging.staging_workers`(기본 2)개가 차례대로 집어 받는다. 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리). 미리 받기 상한은 `ops.run_pipeline.staging.staging_max_docs`(기본 20, 받는 중 포함) — 빈자리가 없으면 워커가 있어도 받지 않는다.

### QA
- `tests/general/deploy/test_run_pipeline.py::test_parallel_stage_respects_free_slots`.
- Status: done

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로

### 무엇·왜
질의응답을 문서 통째가 아니라 질문 하나 단위로 찾는다. FAQ 파일은 Object Storage `FAQ/<uuid>/<파일>`에 올리고 `AI.FileStorageMap`에 등록한다 — 다른 원천과 같은 길로 파싱·적재. 분류·고객 연결은 하지 않는다. 다시 올렸을 때 교체는 [load.md#pl-41](load.md#pl-41).

### 규칙
1. 원천이 FAQ이고 원본이 `.xlsx`·`.xlsm`이면 묶음 단계(`gold_bundle` → `chunking.faq_rows`)가 엑셀 행 하나를 청크 하나로 만든다.
2. 시트마다 첫 비지 않은 행이 머리글이다. 머리글 이름은 소문자로 바꾸고 공백·`_`를 공백 하나로 모은 뒤 대응한다: `type` → 유형, `client question`·`question` → 질문, `answer` → 답. 같은 머리글이 둘이면 앞의 것.
3. 질문·답 머리글이 없는 시트는 건너뛰고 경고한다. 질문·답이 모두 빈 행은 건너뛴다. 빈 칸은 그 값만 빈다.
4. 청크 본문 = `Q: <질문>` 줄 + `A: <답>` 줄(빈 값은 빈 글자). 절(section) = `<시트 이름> / <유형>`(유형이 없으면 시트 이름만). `faq_group` = 시트 이름. `line_start`·`line_end` = 엑셀 행 번호, 쪽·bbox는 비운다.
5. 만약 엑셀이 아니거나, 열 수 없거나(암호·깨짐), 남는 행이 없거나, 원본 파일이 없으면 → 일반 청킹으로 처리하고 경고한다(그때 `faq_group`은 비어 `FAQ_group` 거르기에 걸리지 않는다).
6. `created_at`은 FileStorageMap 등록 시각이다.

### 예시
- 시트 `DS`, 머리글 `type | client question | answer | last modified date`, 2행 = `capability | Q1? | A1 | 2026-09-14` → 청크 `Q: Q1?
A: A1`, 절 `DS / capability`, `faq_group` `DS`, 줄 2–2. 4행 = `(빈) | Q2? | (빈)` → `Q: Q2?
A: `, 절 `DS`. 5행 = `divider`만 → 건너뜀. 머리글 없는 시트 `memo` → 건너뜀(시험 픽스처 `test_faq_rows.py`).

### QA
- `tests/server/pipeline/test_faq_rows.py`.
- Status: done

<a id="pl-57"></a>
## pl-57 · 원본 zip은 풀어서 안의 문서를 파싱
- 이유(사용자 11-05): zip으로 올라온 원본 안의 문서도 검색되어야 한다. 메일 첨부 zip은 이미 풀어 파싱한다(pl-36).
- 요건(되어야 할 모습): 받은 원본이 zip이면 `candidate_ready`가 풀어 안의 문서를 각각 파싱 입력으로 둔다. 안 파일의 키·처리 기록·깊이·크기·개수 상한·암호 zip 처리는 설계 때 정해 여기 적는다.
- 비고(현재와 다른 점): 원본 zip은 "지원하지 않음"(`skipped_unsupported`)으로 표시만 한다(`filter_and_rotate.ARCHIVE_EXT` — pl-02).
- Status: todo

<a id="pl-59"></a>
## pl-59 · 같은 밤 중복·staging 재사용·extract 경계

### 무엇·왜
같은 파일을 두 번 파싱·적재하지 않고, 크기만 같은 새 판을 옛 파일로 파싱하지 않으며, 수집 단계가 변환 코드에 기대지 않게 한다.

### 규칙
1. 서버 흐름(문서마다 `stage`)에서도 이번 실행에서 이미 받은 원본과 sha256이 같으면 → 뒤의 문서는 건너뛰고, `applog.except_doc_info`에 `skip` `duplicate_sha256`으로 남긴다(다음 대상 목록이 뺌 — [pl-58](#pl-58)). 먼저 받은 원본 키는 `applog.pipe_event` `extract.skip` 행의 `metrics.dup_of`(이유 `dup_run`).
   - 이번 실행의 표지: 문서 폴더(`_docflow/<순번>`) 위의 `_seen_sha/<sha256>`(내용 = 먼저 받은 원본 키). 대상 목록(`candidate_pick list`)이 실행을 시작할 때 비우고, `stage`가 중복 제외에서 만든다(임시 파일을 `os.link`로 붙여 — 동시에 받는 둘 중 하나만 이김). 같은 원본 키면(받기 다시 시도) 중복이 아니다.
2. staging 파일을 다시 쓸 때는 내용이 같을 때만이다 — Object Storage ETag(받은 판 옆 `<이름>.etag`)가 지금과 같아야 한다. 크기만 같거나 ETag가 없으면 다시 받는다.
3. `pipeline/extract`는 `pipeline/transform`을 import하지 않는다. 지원 확장자 목록(엔진이 있는 확장자)은 `pipeline/shared`의 한 곳에서 읽는다.
4. 원천 이름은 FileStorageMap `source_system` 칸 값 하나다(PC 폴더는 맨 위 폴더 이름 — [load-schema.md#pl-28](load-schema.md#pl-28) 규칙 3). 게시·구조화·건너뜀 기록이 모두 manifest로 넘어온 그 값을 쓰고, 원본 키에서 다시 구하지 않는다.

### 비고(지금 코드와 다른 점)
- 러너 `run_pipeline.stage_one`은 앞 실행의 문서 폴더를 원본 키만 보고 다시 쓴다(`stage`를 부르지 않음 — ETag 비교 없음, 이번 실행 표지도 만들지 않아 같은 밤 같은 내용 문서가 뒤에 오면 둘 다 파싱). 원본을 지울 때 `.etag` 옆 파일은 남는다(`drop_original`이 `.bin`만 지움).
- `candidate_pick._filter_unsupported_rows`·`filter_and_rotate`가 `transform.parse.engines.registry`를 import한다.

### QA
- `tests/server/pipeline/test_stage_batch.py` `test_same_night_dup`(문서마다 stage 사례 표: 같은 밤 같은 내용 → `dup_run`·`except_doc_info` `skip` `duplicate_sha256`, 같은 원본 다시 받기·다른 내용 → 남음, 1건 중복 제외는 `keep.txt`만) · `test_rdb_stage_once`(크기 같고 ETag 다름 → 다시 받음, 같은 ETag → 다시 씀, manifest 한 번·sha256 담음) · `test_skip_docs.py`(`list`가 표지 폴더를 비움).
- 정할 것: `check_modules`에 extract → transform import 거부 규칙.
- Status: todo
