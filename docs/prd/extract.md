# 수집 — 원천·가져오기·준비

[PRD.md](../PRD.md) 카테고리. 원천(폴더·`rdb:csv`)에서 문서를 가져오고(pl-01), 준비(중복·회전·DRM — pl-02), FAQ 원천(pl-39). 다음 단계는 [transform.md](transform.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-01 · pl-02 · pl-48 · pl-39. (EDW 고객 매핑 pl-29는 11-02에 [load.md](load.md#pl-29)로 옮김)

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기
- 이유: 문서는 폴더, Object Storage, 회사 RDB 목록에서 온다.
- 무엇: `input_source` = 폴더 · `rdb:csv:<경로>`(사용자 11-01 — `s3://`·`rdb:*`·`rdb:<이름>` 지움 · `rdb:<표>` 직접 질의·since/watermark·원천 목록 `sources.json`·`show-sources`도 함께). RDB 열 대응(`RDB_COL_*`), 미리 받기(warm).
- 파일: `pipeline/extract/source.py`, `pipeline/extract/rdb_discover.py`.
- Status: done

<a id="pl-02"></a>
## pl-02 · 준비
- 결정(사용자 10-31 범위 축소 grill): 비슷한 문서 묶기(이름·내용 유사도, dhash·shingle)를 **지운다**. 완전히 같은 파일(sha256)은 **파싱만 한 번**(결과 재사용)하고 문서는 S3 키마다 따로 둔다(U-7 유지 — 메타가 키마다 다름). 이 경우는 별도로 적어 둔다(같은 sha256 다른 키 → 파싱 재사용 기록).
- 이유: 비싼 파싱 전에 쓸모없는 것을 거른다.
- 무엇: sha256 중복 제거(이름·내용이 비슷한 후보는 11-01에 지움 — 아래), RapidOCR 점수로 스캔 쪽 회전, DRM·암호 감지(msoffcrypto/pikepdf 복호화는 수동 CLI — `python -m pipeline.extract.secure_docs decrypt`, prepare·stream에 들어 있지 않음), 압축 파일은 미지원 표시.
- 파일: `pipeline/extract/prepare.py`, `pipeline/extract/dedup.py`, `pipeline/extract/secure_docs.py`.
- 11-01(`feature/scope-cut-unused`, 허브 지시 — 위 10-31 결정의 앞부분): `dedup.py`의 이름·내용 유사 후보(파일명 유사도·텍스트 5-gram Jaccard·이미지 dHash — `candidate_pairs`·`name_ratio`·`dhash`·`shingles`·썸네일 report.html)를 지우고 완전 중복(sha256)만 묶는다. keep.txt는 원래 해시로만 정해져 파싱 대상 수는 그대로 — 단, 같은 내용 사본 중 남길 파일은 이제 해시마다 `_rep_select`(사본 표시 없는 이름 → 최신 → 큰 파일)로 고른다. 예전에는 이름이 비슷한 그룹에 다른 해시가 섞이면 대표 아닌 해시는 파일 이름 순 첫 파일이었다 — 그런 드문 경우 남는 파일 이름이 달라질 수 있다(독립 검토 11-01, 받아들임). 설정 `extract.dedup.fuzzy_max`·`common_max`는 지운 칸(남으면 경고만). 남음(0.2.0): 같은 sha256 다른 키는 파싱만 한 번(결과 재사용) + 기록.
- 결정(사용자 11-02 — 회전): 4방향(0·90·180·270도)을 **한 번에 함께**(병렬로) 비교해 가장 나은 방향을 고르는 판정 기능은 남긴다. 그러나 이미지·이미지 PDF 쪽마다 VLM 전에 늘 돌리는 기본 적용은 끈다 — 조건이 맞는 쪽에만 쓴다(조건부). 지금 코드(11-02 확인): `prepare.py` `best_angle`가 쪽마다 늘 돌고(AD18 "늘 켬"), 기대 각도·반대 두 방향을 먼저 보고 확신이 없을 때만 4방향을 **차례로** 계산한다(`prepare.py:270-290`). 조건 제안(사용자 확인 대기): 그 쪽의 0도 빠른 OCR 점수가 기존 문턱 `extract.prepare.rotate_s0_min`(150) 미만일 때만 4방향 판정 — 바로 선 쪽은 판정을 건너뛴다. 코드 변경은 운영 고침 묶음에서(todo).
- Status: done — 회전 기본 적용 끄기·4방향 병렬은 todo(사용자 11-02, 운영 고침 묶음)

<a id="pl-48"></a>
## pl-48 · 병렬 다운로드 — Object Storage에서 여러 파일을 동시에 받기
- 무엇: 목록 파일 하나에 든 여러 파일을 동시에 받는다 — `python -m pipeline.extract.source warm`(미리 받기, 동시 수 `extract.prefetch_workers` 기본 2 — `pipeline/extract/source.py` 스레드 풀)·`rdb:csv` 파싱 입력 받기(`extract.source.fetch_workers` 기본 1 = 차례대로).
- 이유: 큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 쓰지 않는다.
- 지금(11-02 확인): 서버 러너 `run_docs.py`는 문서마다 목록 파일 하나(한 줄)로 `source warm`을 부르고 받기 스레드도 하나라, 서버에서는 동시에 받지 않는다(파싱과는 겹쳐 돈다 — 미리 받기 20개, [pl-01](#pl-01)).
- 파일: `pipeline/extract/source.py`, `deploy/host/scripts/run_docs.py`(`downloader`·`warm_one`).
- 결정(사용자 11-02): 서버 러너도 병렬로 받는다. 받기 워커 수와 미리 받기 상한(`ops.run_docs.warm`, 기본 20 — 대기열 관리)은 함께 작동한다: 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리). 빈자리가 없으면 워커가 있어도 받지 않는다. `run_docs.py` `downloader` 변경은 운영 고침 묶음에서.
- Status: done — 코드(`source warm`·`rdb:csv` 받기)에 있음 · 서버 러너 병렬 받기는 todo(사용자 11-02)

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로
- 결정(G3·G8·T15 — 2차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 이번 범위에 넣는다.
  - 질의응답 엑셀: 시트 이름 = `FAQ_group`, 행 하나 = 청크 하나(칸: type, client question, answer, last modified date). 청크 메타에 `FAQ_group`, `search` 필터로 쓸 수 있게.
  - Object Storage에 `FAQ/<uuid>/<파일>`로 올리고 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록 — 다른 원천과 같은 길로 파싱·적재(EDW 담당자 협의, DB 담당자 D-8).
  - 분류(C7)·고객 연결은 하지 않는다. `created_at`은 FileStorageMap 등록 시각.
  - PC 예제: `valid_env/object_storage/FAQ/`(지금은 로컬에만 — 이 PR에는 넣지 않음).
  - 옮겨 올 참고 코드: GitHub `gigasamba/bio_data_parsing` 브랜치 `feature/qna-dataset-embedding`의 `_qna_rows.py`·`test_qna_rows.py`.
- 파일: `pipeline/extract/`(행 단위 엑셀 처리), `pipeline/transform/structure/`(청크 메타), `mcp_server/services/search/`(필터).
- 선행: PR 3a(gold 칸) 뒤([pl-32](load-schema.md#pl-32)).
- Status: todo — 0.2.0.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| DRM·암호 파일을 흐름 안에서 복호화 | 복호화는 수동 CLI(`python -m pipeline.extract.secure_docs decrypt`) | `secure_docs.py` | pl-02 |
