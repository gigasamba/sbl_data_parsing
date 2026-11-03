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
- 결정(사용자 11-02 — 회전): 기본으로 끈다(`extract.prepare.rotate`, 기본 false — 꺼지면 회전용 OCR 없이 그대로 놓음). 기능만 남긴다: 켜면 쪽마다 4방향(0·90·180·270도) OCR 점수를 스레드 4개(스레드마다 RapidOCR 하나, CPU 몫을 4로 나눔)로 동시에 재 가장 높은 방향으로 돌린다(같으면 0도, 모두 0이면 그대로). 판단 규칙 — 빠른 경로(기대 각도·반대 각도 2번 비교)·`rotate_s0_min` 문턱·1.3배 비교·`rotate_lead`·`rotate_probe_fast`·명령 인자 `--min-gain` — 은 지웠다(설정은 `REMOVED` — 남아 있으면 경고만). `rotation.csv`는 남김(쪽 VLM `vlm_page`·원본 sha `contract.py`가 읽음). 11-02 `feature/ops-fix`.
- PC 실측(11-02, A4 200 dpi 합성 쪽 하나, OCR 스레드 상한 4): 4방향 동시(스레드 4 × 엔진 스레드 1) 8.2초/쪽, 같은 조건에서 차례 계산 11.6초/쪽, 옛 방식(엔진 하나 스레드 4로 차례 계산) 6.1초/쪽. CPU 상한이 작으면 동시 계산이 빨라지지 않는다.
- Status: done — 회전 기본 꺼짐·4방향 동시 판정(사용자 11-02, `feature/ops-fix`)

<a id="pl-48"></a>
## pl-48 · 병렬 다운로드 — Object Storage에서 여러 파일을 동시에 받기
- 무엇: 목록 파일 하나에 든 여러 파일을 동시에 받는다 — `python -m pipeline.extract.source warm`(미리 받기, 동시 수 `extract.prefetch_workers` 기본 2 — `pipeline/extract/source.py` 스레드 풀)·`rdb:csv` 파싱 입력 받기(`extract.source.fetch_workers` 기본 1 = 차례대로).
- 이유: 큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 쓰지 않는다.
- 전(11-02 확인): 서버 러너 `run_docs.py`는 문서마다 목록 파일 하나(한 줄)로 `source warm`을 부르고 받기 스레드도 하나라, 서버에서는 동시에 받지 않았다(파싱과는 겹쳐 돈다 — 미리 받기 20개, [pl-01](#pl-01)).
- 파일: `pipeline/extract/source.py`, `deploy/host/scripts/run_docs.py`(`downloader`·`warm_one`).
- 결정(사용자 11-02): 서버 러너도 병렬로 받는다. 받기 워커 수와 미리 받기 상한(`ops.run_docs.warm`, 기본 20 — 대기열 관리)은 함께 작동한다: 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리). 빈자리가 없으면 워커가 있어도 받지 않는다. `run_docs.py` `downloader` 변경은 운영 고침 묶음에서.
- Status: done — 코드(`source warm`·`rdb:csv` 받기) · 서버 러너 병렬 받기(`run_docs.py` `downloader`, `ops.run_docs.warm_workers` 기본 2 — 시험 `test_run_docs.test_parallel_warm_respects_free_slots`) 11-02 `feature/ops-fix`

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로
- 결정(G3·G8·T15 — 2차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 이번 범위에 넣는다.
  - 질의응답 엑셀: 시트 이름 = `FAQ_group`, 행 하나 = 청크 하나(칸: type, client question, answer, last modified date). 청크 메타에 `FAQ_group`, `search` 필터로 쓸 수 있게.
  - Object Storage에 `FAQ/<uuid>/<파일>`로 올리고 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록 — 다른 원천과 같은 길로 파싱·적재(EDW 담당자 협의, DB 담당자 D-8).
  - 분류(C7)·고객 연결은 하지 않는다. `created_at`은 FileStorageMap 등록 시각.
  - PC 예제: `valid_env/object_storage/FAQ/`(지금은 로컬에만 — 이 PR에는 넣지 않음).
  - 옮겨 올 참고 코드: GitHub `gigasamba/bio_data_parsing` 브랜치 `feature/qna-dataset-embedding`의 `_qna_rows.py`·`test_qna_rows.py`.
- 파일: `pipeline/transform/structure/{chunking,build_bundle}.py`(행 단위 엑셀 → 청크·`faq_group`), `pipeline/load/pgvector_load.py`·`mcp_server/services/search/search_svc.py`(이미 있던 적재·필터).
- 선행: PR 3a(gold 칸) 뒤([pl-32](load-schema.md#pl-32)).
- 결정(사용자 11-03): 행을 자르는 곳은 묶음 단계(`build_bundle` — code_fp s가 바뀜, 0.2.0 전체 재처리라 받아들임). 청크 본문은 `Q: <질문>` 줄 + `A: <답>` 줄, 절(section)은 `<시트> / <type>`(type·수정일은 본문에 넣지 않음). 빈 칸은 그 값만 비우고(null) 행은 남긴다(질문·답이 모두 빈 행은 건너뜀). 질문·답 머리글이 없는 시트는 건너뛰고 경고한다.
- 한 것(11-03 `feature/faq-source`): `chunking.faq_rows`(openpyxl — 시트의 첫 비지 않은 행이 머리글, 별칭 `client question`/`question`) → `build_bundle`이 원천이 FAQ인 `.xlsx`·`.xlsm`을 행마다 청크로 만들고 `faq_group`(= 시트 이름)을 넣는다. `line_start`·`line_end` = 엑셀 행 번호, 쪽·문자 범위·bbox는 비움. 적재(`_load_src`)와 `search`의 `FAQ_group` 필터는 이미 있던 길을 그대로 쓴다. 엑셀이 아니거나, 못 열거나(암호·깨짐), 남는 행이 없거나, 원본이 그 서버에 없으면 일반 청킹(그때는 `faq_group`이 비어 필터에 안 걸림 — 경고를 찍음). 시험 `tests/server/pipeline/test_faq_rows.py`.
- 하지 않은 것: 머리글은 시트의 첫 비지 않은 행만 보고 영어 이름만 안다(제목 줄·한글 머리글 FAQ가 오면 넓힘). `last modified date`는 gold에 칸이 없어 읽지 않는다(필요하면 faq.chunk 칸 추가 — DB 스키마 등급 A). 다시 올렸을 때 교체는 [pl-41](load.md#pl-41).
- Status: done (11-03 `feature/faq-source`)

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| DRM·암호 파일을 흐름 안에서 복호화 | 복호화는 수동 CLI(`python -m pipeline.extract.secure_docs decrypt`) | `secure_docs.py` | pl-02 |
