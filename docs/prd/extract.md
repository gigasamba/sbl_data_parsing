# 수집 — 원천·가져오기·준비

[PRD.md](../PRD.md) 카테고리. 원천(폴더·`rdb:csv`)에서 문서를 가져오고(pl-01), EDW 고객 매핑(pl-29), 준비(중복·회전·DRM — pl-02), FAQ 원천(pl-39). 다음 단계는 [transform.md](transform.md).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: pl-01 · pl-29 · pl-02 · pl-39.

<a id="pl-01"></a>
## pl-01 · 원천과 가져오기
- 이유: 문서는 폴더, Object Storage, 회사 RDB 목록에서 온다.
- 무엇: `input_source` = 폴더 · `rdb:csv:<경로>`(사용자 11-01 — `s3://`·`rdb:*`·`rdb:<이름>` 지움 · `rdb:<표>` 직접 질의·since/watermark·원천 목록 `sources.json`·`show-sources`도 함께). RDB 열 대응(`RDB_COL_*`), 미리 받기(warm).
- 파일: `pipeline/extract/source.py`, `pipeline/extract/rdb_discover.py`.
- Status: done

<a id="pl-29"></a>
## pl-29 · EDW 고객 매핑을 파이프라인이 직접 만든다
- 결정(사용자 10-31 범위 축소 grill): 고객 매핑은 **기회 직접 + 계정 직접만** 먼저(+CRMS). Task·Event·Quote 단계는 매칭률을 재 보고 낮으면 추가 — PC 가짜 Quote 표도 그때.
- 이유: 문서마다 EDW 고객 하나(`client_edw` — MCP 고객 거르기의 유일한 키, [pl-25](load-schema.md#pl-25))와 SFDC 칸(`sf_acc_name`·`sf_op_id`·`sf_op_name`·`project_code__c` 등)을 지금은 외부에서 뽑은 `file_meta_new.jsonl`(`pipeline.paths.file_meta_path`)에서 읽는데, 그 파일을 만드는 코드가 저장소에 없다(db_schema.md D-2).
- 결정(사용자 10-30 grill 7차): 파이프라인이 EDW 읽기 계정(`common.connections.rdb.read`)으로 조인을 직접 만든다. SFDC: `AI.FileStorageMap.sf_op_id → SFDC.Opportunity → SFDC.Account`(고객 = Account 이름). CRMS·LAS 경로는 DB 담당자 확인(D-2). `file_meta_new.jsonl` 읽기를 대신한다.
- 결정(사용자 10-30 grill — pl-25 검토): 고객뿐 아니라 나머지 문서 메타(`sf_*`, `project_code__c`, `contract_id`, `contract_date`, `prod_name`, `division`, `service_type`)도 같은 자리에서 EDW에서 직접 읽는다 — 외부 파일 `file_meta_new.jsonl`은 없어진다.
- 파일: `pipeline/extract/source.py`(FileStorageMap 읽기), `pipeline/transform/structure/build_bundle.py`(`_file_meta` → 조인 결과), `pipeline/config.py`(`file_meta_path`), `deploy/host/scripts/run_docs.py`(`FILE_META_PATH`), `docs/architecture/db_schema.md`.
- 선행: [pl-25](load-schema.md#pl-25)(스키마 — `client_edw` 칸), [pl-32](load.md#pl-32)(저장 구조).
- 결정(reference 비교(사용자 grill 10-30, 원본은 git 밖) C6·T7): 고객 연결은 운영 4단계를 따른다 — 출발점 `FileStorageMap`, 순서 기회 직접 > `Task.WhatId` > `Event.WhatId` > Quote 스냅샷, 계정 직접 연결도 포함. 결과는 pgvector doc에만. 같은 sha256 묶음에도 고객은 전파하지 않는다(C3).
- 열린 점: Quote 단계는 레플리카에 Quote 표가 없어 SFDC REST 스냅샷에 기댄다 — 서버에서 스냅샷을 어떻게 공급할지 정해야 함. → 해소(10-31 결정 — PC 대역 Quote 표, 아래).
- 결정(G2·T16 — 2차 grill(사용자 10-30, 원본은 git 밖)): `client_edw`(문서당 고객 하나)는 SFDC(4단계 연결)와 **CRMS**(`FileStorageMap_CRMS.rm_contract_code → CRMS.RM_CM_PJTLIST` — DB 담당자 확인, D-2)에서 채운다. LAS는 상대사 출처가 정해질 때까지 비워 둔다. FAQ는 고객 연결 없음([pl-39](#pl-39)).
- 결정(G11 — 3차 grill(사용자 10-30, 원본은 git 밖)): 적재 뒤 바뀐 SFDC 연결(고객·`sf_op_id` 등)은 자동으로 갱신하지 않는다. 수동 요청 때 전체 문서를 갱신한다([pl-40](load.md#pl-40)).
- 결정(사용자 10-30 PRD grill): A3 — 고객 연결의 마지막 단계(SFDC Quote 스냅샷)는 미정으로 둔다(서버 레플리카에 Quote 표 없음). 허브가 0.2.0 설계 확인 때 사용자에게 다시 묻는다. 그 전까지 구현은 기회 직접 > Task > Event 3단계(+계정 직접).
- 결정(사용자 10-31 grill): A3 — Quote 단계도 0.2.0에 넣는다. PC 대역 EDW(`valid_env/edw`)에 SFDC Quote 표를 예시 칸으로 새로 만들어 4단계(기회 직접 > Task > Event > Quote, +계정 직접)로 구현한다. 실제 표·칸 이름은 DB 담당자 답으로 맞춘다(A4 `created_at`과 같은 방식).
- 구현(11-02 `feature/mcp-ops-parity`): 사용자 11-02 — 매핑은 적재 몫. `pipeline/load/edw_meta.py`가 적재 때(PG 트랜잭션 밖, 읽기 계정) 원천별 사슬로 `client_edw`·원천 칸·`created_at`을 채운다(사슬은 [db_schema.md](../architecture/db_schema.md) §1 — 운영 gold 스키마 노트 기준, 칸 이름은 D-1 확인). SFDC 4단계(기회 직접 > Task > Event > Quote, +계정 직접 — 같은 단계 동률은 비움), CRMS(`RM_CM_PJTLIST`·`RM_CM_DOCU`), LAS(`LAS.Contract` 최신 판·`FileManager`). Quote는 운영처럼 EDW 표로 재현(사용자 11-02) — 서버 EDW에 표가 없으면 그 단계만 건너뜀(C-76: DB 담당자가 표를 만들고 REST 스냅샷으로 채움, 누가·언제는 미정). 외부 `file_meta_new.jsonl`·`FILE_META_PATH`·build_bundle의 `_file_meta`를 지웠다. EDW를 못 읽으면 메타 없이 적재(경고·`meta_missing`) — 자동 갱신 없음, `--replace`로 다시 적재해 채움. PC 가짜 EDW(`valid_env/edw`)에 가짜 사슬 표를 더했다. 시험: `tests/server/pipeline/test_edw_meta.py`.
- Status: done(11-02)

<a id="pl-02"></a>
## pl-02 · 준비
- 결정(사용자 10-31 범위 축소 grill): 비슷한 문서 묶기(이름·내용 유사도, dhash·shingle)를 **지운다**. 완전히 같은 파일(sha256)은 **파싱만 한 번**(결과 재사용)하고 문서는 S3 키마다 따로 둔다(U-7 유지 — 메타가 키마다 다름). 이 경우는 별도로 적어 둔다(같은 sha256 다른 키 → 파싱 재사용 기록).
- 이유: 비싼 파싱 전에 쓸모없는 것을 거른다.
- 무엇: sha256 중복 제거(이름·내용이 비슷한 후보는 11-01에 지움 — 아래), RapidOCR 점수로 스캔 쪽 회전, DRM·암호 감지(msoffcrypto/pikepdf 복호화는 수동 CLI — `python -m pipeline.extract.secure_docs decrypt`, prepare·stream에 들어 있지 않음), 압축 파일은 미지원 표시.
- 파일: `pipeline/extract/prepare.py`, `pipeline/extract/dedup.py`, `pipeline/extract/secure_docs.py`.
- 11-01(`feature/scope-cut-unused`, 허브 지시 — 위 10-31 결정의 앞부분): `dedup.py`의 이름·내용 유사 후보(파일명 유사도·텍스트 5-gram Jaccard·이미지 dHash — `candidate_pairs`·`name_ratio`·`dhash`·`shingles`·썸네일 report.html)를 지우고 완전 중복(sha256)만 묶는다. keep.txt는 원래 해시로만 정해져 파싱 대상 수는 그대로 — 단, 같은 내용 사본 중 남길 파일은 이제 해시마다 `_rep_select`(사본 표시 없는 이름 → 최신 → 큰 파일)로 고른다. 예전에는 이름이 비슷한 그룹에 다른 해시가 섞이면 대표 아닌 해시는 파일 이름 순 첫 파일이었다 — 그런 드문 경우 남는 파일 이름이 달라질 수 있다(독립 검토 11-01, 받아들임). 설정 `extract.dedup.fuzzy_max`·`common_max`는 지운 칸(남으면 경고만). 남음(0.2.0): 같은 sha256 다른 키는 파싱만 한 번(결과 재사용) + 기록.
- Status: done

<a id="pl-39"></a>
## pl-39 · FAQ 원천 — 질의응답 엑셀을 행 단위로
- 결정(G3·G8·T15 — 2차 grill(사용자 10-30, 원본은 git 밖)): FAQ를 이번 범위에 넣는다.
  - 질의응답 엑셀: 시트 이름 = `FAQ_group`, 행 하나 = 청크 하나(칸: type, client question, answer, last modified date). 청크 메타에 `FAQ_group`, `search` 필터로 쓸 수 있게.
  - Object Storage에 `FAQ/<uuid>/<파일>`로 올리고 `AI.FileStorageMap`에 `source_system='FAQ'`로 등록 — 다른 원천과 같은 길로 파싱·적재(EDW 담당자 협의, DB 담당자 D-8).
  - 분류(C7)·고객 연결은 하지 않는다. `created_at`은 FileStorageMap 등록 시각.
  - PC 예제: `valid_env/object_storage/FAQ/`(지금은 로컬에만 — 이 PR에는 넣지 않음).
  - 옮겨 올 참고 코드: GitHub `gigasamba/bio_data_parsing` 브랜치 `feature/qna-dataset-embedding`의 `_qna_rows.py`·`test_qna_rows.py`.
- 파일: `pipeline/extract/`(행 단위 엑셀 처리), `pipeline/transform/structure/`(청크 메타), `mcp_server/services/search/`(필터).
- 선행: PR 3a(gold 칸) 뒤([pl-32](load.md#pl-32)).
- Status: todo — 0.2.0.

## 코드와 다른 점 · 지울 코드

### 요건과 다르게 동작
| 요건 | 코드가 하는 일 | 위치 | ID |
|---|---|---|---|
| DRM·암호 파일을 흐름 안에서 복호화 | 복호화는 수동 CLI(`python -m pipeline.extract.secure_docs decrypt`) | `secure_docs.py` | pl-02 |
