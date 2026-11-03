# 수집 — 원천·가져오기·준비

[PRD.md](../PRD.md) 카테고리. 원천에서 문서를 받아(pl-01·pl-48) 준비(중복·회전·DRM — pl-02)하기까지와 FAQ 원천(pl-39). 다음 단계는 [transform.md](transform.md).

순서: pl-01 · pl-02 · pl-48 · pl-39.

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기

### 무엇·왜
파싱 입력을 정한다. 문서 목록의 기준은 EDW `AI.FileStorageMap`이고, 파일은 Object Storage에서 `s3_key`로 받는다.

### 규칙
1. 파싱 입력(`--source`, 설정 `pipeline.extract.input_source`)은 둘 중 하나여야 한다 — 폴더, 또는 `rdb:csv:<경로>`(문서 위치 표 CSV). 그 밖의 값이면 → 오류로 멈춘다.
2. `rdb:csv`의 칸 이름은 설정 `pipeline.connections.rdb.columns`가 정한다 — 기본 `doc_id`=`id`, `key`=`s3_key`, `filename`=`original_filename`, `size`=`file_size`, `content_version`=`content_version_id`.
3. 서버 러너 `run_docs.py`가 FileStorageMap에서 대상(파일 이름 키워드 `--filter`, 작은 파일부터)을 골라 `batch.csv`를 만들고 `rdb:csv`로 넘긴다(대상 고르기 규칙은 [ops.md#pl-23](ops.md#pl-23)).
4. 미리 받기: `python -m pipeline.extract.source warm`이 표의 파일을 `pipeline.extract.source.warm` 폴더에 먼저 받는다(비면 미리 받기 꺼짐). 받기에 실패한 파일은 파싱 때 직접 받는다.

### QA
- `tests/server/pipeline/test_source.py` · `tests/server/pipeline/test_rdb_discover.py`.
- Status: done

<a id="pl-02"></a>
## pl-02 · 준비 — 중복·회전·DRM

### 무엇·왜
비싼 파싱 전에 같은 파일·읽을 수 없는 파일을 거르고, 돌아간 스캔을 바로잡는다.

### 규칙
1. 완전히 같은 파일(sha256 같음)은 한 번만 파싱하고 결과를 재사용한다. 문서는 S3 키마다 따로 둔다(키마다 메타가 다름).
2. 같은 해시 묶음에서 남길 파일은 `dedup.py` `_rep_select` 순서로 고른다: 이름에 사본 표시(`(1)`·`사본` 등)가 없는 것 → 수정 시각이 늦은 것 → 큰 파일.
3. 회전 바로잡기는 `pipeline.extract.prepare.rotate`(기본 `false`)가 켜졌을 때만 한다. 꺼져 있으면 회전용 OCR을 하지 않고 파일을 그대로 놓는다.
4. 켜져 있으면 이미지·스캔 PDF 쪽마다 4방향(0·90·180·270도) RapidOCR 점수를 스레드 4개로 동시에 재고 가장 높은 방향으로 돌린다 — 같으면 0도, 모두 0이면 그대로. 기록은 `output/prepared/rotation.csv`(파일·쪽·각도·네 방향 점수·회전 전 원본 sha256 `orig_sha256`).
5. DRM·암호 파일은 감지해서 표시만 한다(상태 `skipped_drm`). 복호화는 흐름 안에서 하지 않고 수동 명령 `python -m pipeline.extract.secure_docs decrypt`로만 한다.
6. 압축 파일(zip)은 지원하지 않는다고 표시한다.

### QA
- `tests/server/pipeline/test_prepare.py`(`test_rotation_off_by_default` 등) · `tests/general/pipeline/test_dedup.py`.
- Status: done

<a id="pl-48"></a>
## pl-48 · 병렬 다운로드

### 무엇·왜
큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 쓰지 않는다.

### 규칙
1. `source warm`은 `pipeline.extract.prefetch_workers`(기본 2)개 스레드로 동시에 받는다.
2. `rdb:csv` 파싱 입력 받기는 `pipeline.extract.source.fetch_workers`(기본 1 = 차례대로)개 스레드로 받는다.
3. 서버 러너 `run_docs.py`는 받기 워커 `ops.run_docs.warm_workers`(기본 2)개가 차례대로 집어 받는다. 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리). 미리 받기 상한은 `ops.run_docs.warm`(기본 20, 받는 중 포함) — 빈자리가 없으면 워커가 있어도 받지 않는다.

### QA
- `tests/general/deploy/test_run_docs.py::test_parallel_warm_respects_free_slots`.
- Status: done

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로

### 무엇·왜
질의응답을 문서 통째가 아니라 질문 하나 단위로 찾는다. FAQ 파일은 Object Storage `FAQ/<uuid>/<파일>`에 올리고 `AI.FileStorageMap`에 등록한다 — 다른 원천과 같은 길로 파싱·적재. 분류·고객 연결은 하지 않는다. 다시 올렸을 때 교체는 [load.md#pl-41](load.md#pl-41).

### 규칙
1. 원천이 FAQ이고 원본이 `.xlsx`·`.xlsm`이면 묶음 단계(`build_bundle` → `chunking.faq_rows`)가 엑셀 행 하나를 청크 하나로 만든다.
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
