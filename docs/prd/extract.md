# 수집 — 원천·가져오기·준비

[PRD.md](../PRD.md) 카테고리. 원천에서 문서를 받아(pl-01·pl-48) 준비(중복·회전·DRM — pl-02)하기까지와 FAQ 원천(pl-39). 다음 단계는 [transform.md](transform.md).

순서: pl-01 · pl-02 · pl-58 · pl-59 · pl-48 · pl-39 · pl-65 · pl-66.

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기

### 무엇·왜
파싱 입력을 정한다. 문서 목록의 기준은 EDW `AI.FileStorageMap`이고, 파일은 Object Storage에서 `s3_key`로 받는다.

### 규칙
1. 파싱 입력(`--source`, 설정 `extract.source.source_input_location`)은 둘 중 하나여야 한다 — 폴더, 또는 `rdb:csv:<경로>`(문서 위치 표 CSV). 그 밖의 값이면 → 오류로 멈춘다.
2. `rdb:csv`의 칸 이름은 설정 `tuning.extract.source_columns`가 정한다 — 기본 `source_column_doc_id`=`id`, `source_column_storage_key`=`s3_key`, `source_column_filename`=`original_filename`, `source_column_file_size`=`file_size`, `source_column_source_system`=`source_system`.
3. 대상 목록은 컨테이너 안 `python -m pipeline.extract.candidate_pick list`가 FileStorageMap에서 고른다(파일 이름 키워드 `--filter`, 작은 파일부터 — 규칙은 [ops.md#pl-10](ops.md#pl-10)·[pl-23](ops.md#pl-23)). 설정 `required.source.source_systems`(원천 목록)가 있으면 `source_system` 칸이 그 값인 행만 고른다(대소문자 무관 — 목록에 `FAQ`가 없으면 FAQ 먼저·교체 확인도 하지 않음, 비우면 운영 5개 원천 `SFDC`·`CRMS`·`LAS`·`FAQ`·`Other` — `DEV-<숫자>` 행은 뺀다, [ops.md#op-17](ops.md#op-17) 규칙 8 · 판정 `candidate_pick.picked`). PC `rdb:csv` 받기(`rdb_pick`)·PC 폴더 원천(맨 위 `DEV-<숫자>/` 폴더 포함)도 같은 목록으로 거르고, 목록 밖 행은 건너뜀으로 기록하지 않는다. 원천 값은 들어오는 자리에서 대문자로 바꾼다(`FAQ`·`DEV-1`). 목록 파일·`batch.csv`(칸 `source_system` — 이름은 `tuning.extract.source_columns.source_column_source_system`)·manifest는 그 행의 `source_system` 값을 그대로 넘긴다([load-schema.md#pl-28](load-schema.md#pl-28) 규칙 3). 서버 러너 `run_pipeline.py`는 그 목록 파일을 읽어 문서마다 `batch.csv`(한 줄)를 만든다. 끝난 문서(gold `doc.file_path`)·영구 건너뜀(`except_doc_info` `skip`)을 뺄 때는 FileStorageMap `s3_key`를 그대로 비교한다 — 그 두 표의 원본 키는 `s3://버킷/` 앞머리가 없는 키라, FileStorageMap `s3_key`도 앞머리 없이 적혀 있어야 빠진다(앞머리가 붙은 행은 받기는 되지만 매번 다시 고름).
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
6. DRM·암호 파일은 감지해서 표시하고 건너뛴다(상태 `skipped_drm`, `prepared/_records/skipped.jsonl`). 복호화는 하지 않는다 — 수동 명령도 없다(사용자 11-08).
7. 압축 원본 `.zip`·`.tar`·`.tgz`·`.tar.gz`는 풀어 파싱하고(암호·깨짐·안전 상한은 `pipeline.extract.archive.check`가 거름 — [pl-57](#pl-57)), `.7z`·`.rar`·`.bz2`·`.xz`는 지원하지 않는다고 표시한다(`unsupported_archive`). 처리 엔진 없는 확장자(`registry.engines_for`가 빈 것)는 두 곳에서만 거른다 — 받기 전 `candidate_pick.rdb_pick`(`_filter_unsupported_rows` — rdb:csv 대상 고르기), 받은 뒤 `filter_and_rotate`(`unsupported_*`). 파일 크기 상한(`extract.max_source_file_mb`)은 파싱(`parse_engines`)이 본다.
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
## pl-57 · 압축 원본은 풀어서 안 파일의 글을 그 문서에
- 이유(사용자 11-05): zip으로 올라온 원본 안의 문서도 검색되어야 한다. 메일 첨부 zip은 이미 풀어 파싱한다(pl-36).

### 규칙(사용자 11-06 결정)
1. 압축 원본 하나 = 검색 문서 하나(메일 첨부와 같은 방식 — [transform.md#pl-36](transform.md#pl-36)). 안 파일은 형식별 엔진으로 글을 뽑아 대표 본문에 `[파일 <안 경로>]` 절로 덧붙인다(글자만 — 표 구조·그림 설명 없음, 안의 그림 파일은 읽지 않음). 문서 키·처리 기록은 압축 원본 하나(`s3_key` 그대로).
2. 푸는 형식: `.zip`·`.tar`·`.tgz`·`.tar.gz`(표준 라이브러리, 확장자로 고름). `.7z`·`.rar`·`.bz2`·`.xz`, tar가 아닌 `.gz`는 `unsupported_archive`.
3. 압축 엔진 `archive`(엔진 폴더 `engines/archive` — 새 엔진이라 다른 엔진의 엔진 지문은 그대로, 사람 검토 등급 A)는 맨 바깥 파일 목록을 본문으로 낸다. 안 파일은 받기 단계가 준비 폴더에 풀어 두고([pl-63](#pl-63)), 대표 결과의 첨부 단계(`mail_attachments`, 후보정 `attachments`)가 파싱한다(P0 캐시 같음). 엔진 구성 `parse`에 `.zip`·`.tar`·`.tgz`·`.gz` → `archive`.
4. 깊이는 [pl-63](#pl-63) 규칙 2(원본에서 2단계 — 안의 압축은 한 단계 더 풀림). 안의 압축이 풀리지 않으면(tar 아닌 `.gz`·깨짐) 보통 파일로 두고 바깥 압축은 그대로 처리한다.
5. 안전 상한(평소엔 걸리지 않을 큰 값, 설정 칸): 풀린 크기 합계 `tuning.extract.archive.archive_max_total_mb`(2048), 파일 수 `archive_max_files`(1000). 안의 압축은 크기가 합계 상한 안일 때만 열어 본다. 안 파일 하나의 크기 상한은 없다.
6. 받기의 거르기(`filter_and_rotate` — `archive.check`)가 목록만 읽어 판정하고, 걸리면 `applog.except_doc_info`에 `skip`으로 남겨 다음 실행도 건너뛴다: 암호 `encrypted_archive` · 깨짐 `broken_archive` · 상한 넘음 `archive_too_big`. 상한을 올렸거나 원본을 다시 올렸으면 그 행을 지워야 다시 고른다.
7. 압축 읽기(목록·상한·암호 판정·꺼내기)는 받기 단계 `pipeline/extract/archive.py` 한 곳(사용자 11-06 — shared 아님. 엔진은 엔진 지문을 지키려고 엔진 폴더 안에서 목록만 따로 읽음). 나중에 안 파일마다 문서 하나로 바꿀 때도 풀어 둔 `_parts/`를 쓴다.
8. 검색 MCP의 `parse_document`는 압축을 받지 않는다(`engine_check.allowed_exts`에서 뺌).

### QA
- `tests/server/pipeline/test_archive.py` 사례 표: zip·tar.gz 풀림 → `[파일 …]` 절 · 안 zip 한 단계 · 두 단계 밑은 안 풂 · 안 `.gz`·깨진 안 zip은 보통 파일 · 끝에 zip 든 tar · 안 그림 건너뜀 · 암호 → `encrypted_archive` · 깨짐 → `broken_archive` · 파일 수·합계 넘음 → `archive_too_big` · `.7z` → `unsupported_archive`.

- Status: done

<a id="pl-63"></a>
## pl-63 · 문서 안 문서는 받기 단계에서 풀어 둔다(압축·메일 첨부·오피스 개체)
- 이유(사용자 11-06): 압축 안 문서, 메일에 붙은 문서, 문서 안에 개체로 넣은 문서가 같은 길로 가야 한다. 겉 상자만 열면 찾을 수 있는 것은 받기 단계에서 미리 꺼내 두고, 변환 단계는 꺼낸 파일만 읽는다.

### 규칙(사용자 11-06 결정)
1. 받기 단계(`filter_and_rotate` — 준비 폴더에 원본을 둔 뒤)가 원본 안의 문서를 `<준비 폴더>/_parts/<원본 이름>/`에 파일로 꺼내 두고, 목록 `parts.json`(꺼낸 파일 이름·안 경로·깊이·종류 `파일`·`첨부`·`개체`·위치 — 부모는 안 경로의 앞부분)을 쓴다. 꺼내는 것: 압축 안 파일([pl-57](#pl-57)), 메일 첨부와 메일 안 메일([transform.md#pl-36](transform.md#pl-36)), 새 형식 오피스 안 개체(규칙 5). 꺼낸 파일이 또 상자면 같은 규칙으로 다시 연다. 풀린 안 압축과 `.eml` 안의 메일은 목록에서 그 안 파일로 대신한다 — 압축 엔진 글은 목록뿐이고, `.eml` 엔진은 안 메일의 글까지 이미 본문에 읽는다(같은 글이 두 번 들어가지 않게 — PC E2E 11-06). `.msg` 안의 메일은 `[첨부 <첨부 이름(없으면 제목)>.msg]` 절로 둔다.
2. 깊이: 원본에서 2단계까지 — 종류가 섞여도 같이 센다(메일 → 첨부 docx → 그 안 엑셀 = 2, zip → 안 zip → 파일 = 2). 설정 `tuning.extract.attach.attachment_max_depth` 기본 2(압축도 이 값). 그 밑은 파일 그대로 둔다.
3. 상한은 지금 값 그대로: 압축은 [pl-57](#pl-57) 안전 상한(합계 2 GB·1000개), 메일 첨부와 오피스 개체는 메일 첨부 상한(하나 20 MB 넘으면 건너뜀, 메일·오피스 파일 하나에서 10개 — 단계마다 따로 셈).
4. 꺼내지 않는 것: 그림 파일(그림 기능이 맡음), 차트에 딸린 엑셀(차트 단계가 이미 숫자를 읽음 — 중복), 개체 아이콘 그림, 연결만 된 개체(파일 경로만 있음).
5. 오피스 개체(`.docx`·`.docm`·`.dotx`·`.pptx`·`.pptm`·`.potx`·`.ppsx`·`.xlsx`·`.xlsm`·`.xltx`): `word/`·`ppt/`·`xl/` 아래 `embeddings/`의 파일 중 문서·슬라이드·시트의 연결 정보(`_rels`)가 개체로 가리키는 것. 붙은 곳(슬라이드 번호·시트 이름·워드는 개체가 든 문단 글 끝 40자 — 비면 앞 문단)을 위치로 적는다. `oleObject*.bin`은 olefile(extract-msg와 함께 설치됨)로 벗겨 원래 파일을 꺼내고, 못 벗기면 건너뛴다. 새 형식 오피스에 넣은 개체는 무엇이든(PDF·옛 형식 문서 포함) 꺼낸다 — 옛 형식·PDF·한글 **문서 안의** 개체는 [pl-64](#pl-64).
6. 변환 단계의 첨부 처리(`mail_attachments`)는 `parts.json`의 파일만 읽어 형식별 엔진으로 파싱하고(P0 캐시 같음 — 안 파일 sha256 + 엔진@버전), 본문 끝에 `## [파일 …]`(압축)·`## [첨부 …]`(메일)·`## [개체 …]`(오피스) 제목 줄로 시작하는 절로 덧붙인다([pl-65](#pl-65)). 오피스 개체는 있던 자리에 위치 표시 `[개체 <이름>]` 한 줄을 넣는다 — 파워포인트는 그 슬라이드 끝, 엑셀은 그 시트 끝, 워드는 그 문단 글이 든 줄 뒤. 자리를 못 찾으면 위치 표시 없이 끝 절만. 파싱 엔진은 고치지 않는다(엔진 지문 그대로).
7. `_parts/`는 준비 원본과 같이 지운다(서버는 문서 폴더를 지울 때 함께). 파싱 단계는 준비 폴더 맨 위 파일만 문서로 보므로 `_parts/` 안 파일이 따로 문서가 되지 않는다.
8. 메일 인용 스레드 접기는 본문 글이 있어야 하므로 변환 단계에 남는다. 검색 MCP `parse_document`도 받기 단계를 거쳐 `_parts/`를 만들지만, 후보정 기본값(`supsub`)에 `attachments`가 없어 첨부·개체를 붙이지 않는다(지금과 같음).

### QA
- `tests/server/pipeline/test_unpack.py` 사례 표: eml 첨부 · eml 안 eml(이름 없는 전달 메일 — 그 첨부만) · 메일 → 첨부 docx → 안 엑셀(깊이 2) · 깊이 3은 파일 그대로 · pptx 둘째 슬라이드 개체(발표 순서로 셈) · 차트 엑셀은 안 꺼냄 · xlsx 개체에 시트 위치 · 못 벗기는 `.bin` 건너뜀 · 그림 개체 안 꺼냄 · 그림은 개수 상한을 쓰지 않음 · 파일로 붙은 `.eml`은 첨부로 남음 · `Ole10Native` 벗김 · 위치 표시 표(슬라이드 끝·시트 끝·워드 문단 뒤·못 찾으면 끝 절만). zip 안 docx → `[파일 …]`는 `test_archive.py`.
- PC E2E: `pipeline.cli parse`로 위 견본 문서를 돌려 본문의 `[개체 …]`·`[첨부 …]`·`[파일 …]` 절과 위치 표시를 확인.
- Status: done

<a id="pl-64"></a>
## pl-64 · 옛 형식·PDF·한글 안 개체
- 요건: 옛 형식(`.doc`·`.xls`·`.ppt` — `ObjectPool`, olefile), PDF 첨부 파일·첨부 주석(pymupdf), 한글 `.hwpx` `BinData` 개체도 [pl-63](#pl-63)과 같이 꺼낸다.
- 반영: 없음(사용자 11-06 — 이번에는 새 형식 오피스만).
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
4. 원천 이름은 FileStorageMap `source_system` 칸 값 하나다(PC 폴더는 맨 위 폴더 이름 — [load-schema.md#pl-28](load-schema.md#pl-28) 규칙 3). 게시·구조화·건너뜀 기록이 모두 manifest로 넘어온 그 값을 쓰고, 원본 키에서 다시 구하지 않는다. manifest는 받기마다 앞 실행 행을 남기고 이번 문서 행만 고쳐 쓴다(rdb·PC 폴더 같음) — 같은 결과 폴더를 다시 쓰면 구조화가 앞 문서의 원천·원본 키도 그대로 찾는다. 문서 이름(rdb·PC 폴더)은 앞 실행 행과도 겹치지 않는다(`candidate_ready._rerun_names`) — 같은 원본 키면 앞 이름 그대로, 다른 키가 쓴 이름이면 `<상위 폴더>__<이름>`(그래도 겹치면 원본 키의 `/`를 `__`로).

### 비고(지금 코드와 다른 점)
- 러너 `run_pipeline.stage_one`은 앞 실행의 문서 폴더를 원본 키만 보고 다시 쓴다(`stage`를 부르지 않음 — ETag 비교 없음, 이번 실행 표지도 만들지 않아 같은 밤 같은 내용 문서가 뒤에 오면 둘 다 파싱). 원본을 지울 때 `.etag` 옆 파일은 남는다(`drop_original`이 `.bin`만 지움).
- `candidate_pick._filter_unsupported_rows`·`filter_and_rotate`가 `transform.parse.engines.registry`를 import한다.

### QA
- `tests/server/pipeline/test_stage_batch.py` `test_same_night_dup`(문서마다 stage 사례 표: 같은 밤 같은 내용 → `dup_run`·`except_doc_info` `skip` `duplicate_sha256`, 같은 원본 다시 받기·다른 내용 → 남음, 1건 중복 제외는 `keep.txt`만) · `test_rdb_stage_once`(크기 같고 ETag 다름 → 다시 받음, 같은 ETag → 다시 씀, manifest 한 번·sha256 담음) · `test_skip_docs.py`(`list`가 표지 폴더를 비움) · `test_candidate.py` `test_rerun_keeps_source`(같은 결과 폴더 다시 실행 사례 표: 이번 목록은 이번 문서만, 묶음의 앞 문서는 원천·원본 키 그대로 — other로 안 감, 실행 사이 같은 파일 이름·같은 키 다시).
- 정할 것: `check_modules`에 extract → transform import 거부 규칙.
- Status: todo

<a id="pl-65"></a>
## pl-65 · 안 문서를 못 꺼낸 경우의 기록과 꺼내기 바로잡기
- 요건: pl-63 꺼내기에서 빠지는 것이 보이고, 이름·크기·목록이 안전하게(사용자 11-08). 꺼내는 깊이는 pl-63 규칙 2(2단계) 그대로, 속도(안 파일마다 한 프로세스)는 이번에 다루지 않는다.
- 반영: 아래 규칙대로(사용자 11-08).

### 규칙
1. 못 꺼낸 안 파일(안 열리는 안 상자 `cannot_open`·압축 안 암호 항목 `encrypted`·크기 상한 `too_big`·개수 상한 `too_many`·원본 하나의 꺼낸 합계 상한 `total_cap`·못 벗긴 `.bin` `no_unwrap`·읽는 도중 깨진 압축 `read_failed`)은 `parts.json`의 `failed`에 `{name, why}`로 남고, 성한 안 파일은 그대로 붙는다. 맨 바깥 원본이 안 열리는 것은 엔진이 판정한다(기록 안 함). 압축 안 파일이 합계·개수 상한에 닿으면 거기서 멈추고 첫 이름 하나에 `외 N개`를 붙여 한 줄로 적는다. 그림·차트 엑셀·깊이 상한 밑·tar 아닌 `.gz`(보통 파일로 둠)·같은 내용 두 번째는 일부러 꺼내지 않는 것이라 적지 않는다.
2. 거르기(`filter_and_rotate`)가 이번 실행 문서마다 `failed`를 `_records/parts_failed.csv`(`file`·`reason`)에 적고, 받기(`candidate_ready._record_filtered`)가 skip 행과 같은 길로 `applog.except_doc_info`에 원본 키당 한 행을 upsert한다 — `except_type = part`·`level = warn`·이유 = 앞 10개 `이름(까닭)`을 `; `로 잇고 나머지는 `외 N개`(예 `in.zip/a.txt(encrypted); oleObject1.bin(no_unwrap)`). 다시 풀지 않은 재실행도 적어 마지막 시각·횟수가 오른다. 대상 목록에서 빼는 키가 아니다. 표 구조는 그대로(새 값 `part` — refactor.md C-111).
3. 이름: zip은 utf-8 표시(플래그 11번 비트)가 있으면 그대로, 없으면 원래 바이트를 utf-8 → cp949 → cp437 차례로 읽는다. tar도 원래 바이트에서 같은 차례(cp949 이름에서 받기가 멈추지 않음). 줄바꿈·제어 문자는 빈칸, 글자로 못 쓰는 조각은 `?`.
4. 원본 하나에서 꺼낸 합계 크기 상한 = 압축 안전 상한 `tuning.extract.archive.max_total_mb`(2 GB — 새 설정 없음). 오피스 개체·안 압축으로 된 크기 폭탄도 여기서 멈춘다. 목록에서 안 파일로 대신하는 상자(열린 안 압축·안 메일)는 합계에 넣지 않는다(같은 바이트를 두 번 세지 않게).
5. `parts.json` = `{"sha256": 원본 sha256, "parts": [...], "failed": [...]}`. 다 쓴 임시 파일을 `os.replace`로 바꿔 놓고, 신선도는 고친 시각이 아니라 원본 sha256으로 본다(옛 목록 형식은 다시 품).
6. 같은 내용(sha256)의 안 파일은 처음 것만 꺼낸다(같은 개체가 두 자리에 있으면 위치 표시도 첫 자리만).
7. 붙인 절은 제목 줄 `## [첨부 <이름>]`·`## [파일 <이름>]`·`## [개체 <이름>]`로 시작하고(조각·절이 첨부마다 나뉨), 첨부 글의 쪽 나눔(`\f`)은 줄바꿈으로 바꾼다(원본 쪽 번호를 밀지 않게). 원본 위치(`sources`)는 그대로.
8. 워드 개체 위치: 개체 앞 문단 글이 문서에 여러 번 나오면 몇 번째인지(`nth`)도 적어 그 차례 자리에 표시한다(모자라면 마지막 자리).
9. 첨부 파싱 임시 파일은 부를 때마다 새 이름(문서 둘이 같은 첨부를 동시에 파싱해도 겹치지 않음).

### QA
- `tests/server/pipeline/test_unpack.py`: 사례 표 `CASES`(같은 글 문단 둘 → `nth`, 같은 내용 첨부 한 번) · `FAILED` 표(못 벗기는 `.bin`·안 열리는 안 docx · 첨부 압축 안 암호 항목 · 합계 상한 · 개수 상한 · 안 압축은 합계에 안 파일만 · 같은 내용은 상한보다 먼저 · tar 아닌 안 .gz · 압축 개수 상한 한 줄) · `MARKS`(같은 글 둘째 자리) · 제목 줄·쪽 나눔 · 임시 이름 · `parts.json` 원자 쓰기 · sha256 신선도. `test_archive.py` 사례 표: cp949 tar · cp949 zip · 이름 속 줄바꿈. `test_skip_docs.py::test_part_row`: 거르기 → part 행(warn) · 재실행 횟수 2.
- Status: done

<a id="pl-66"></a>
## pl-66 · 옛 형식 오피스 검사기 하나로
- 요건: 같은 검사를 두 벌로 두지 않는다. 남길 쪽은 olefile — 견본 `.doc`·`.xls`·`.ppt`(암호 있음·없음)로 두 코드 결과가 같은지 먼저 시험.
- 반영: 없음(사용자 11-08 결정 — 다음 작업).
- Status: todo
