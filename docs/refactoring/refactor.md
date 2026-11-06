# 서버·사람이 확인해야 할 사항(C)

저장소 안에서 끝낼 수 없는 확인(서버에서 볼 것, 다른 담당자와 협의할 것, 사용자가 정할 것) 중 **열린 것만** 둔다. 끝나면 줄을 지운다(이력은 git). 판을 올리는 순서는 [upgrade-guide.md](../operations/upgrade-guide.md)가 정본이고, 이 표는 항목별로 무엇을 돌리고 무엇이 통과인지 적는다. 지난 0.2.0 배포 절차는 [history/deploy_0_2_0.md](../history/deploy_0_2_0.md).

- 새 항목은 다음 번호(`C-xx`)로 덧붙인다. 번호는 다시 쓰지 않는다. "누가"는 역할로 적는다.
- 비밀값·접속 값은 이 문서에 쓰지 않는다.

| ID | 무엇을 | 왜 | 언제 | 누가 | 근거 | 상태 |
|---|---|---|---|---|---|---|
| C-10 | **노출된 운영 키 교체** — 옛 `run_pipeline.py` git 이력(첫 커밋부터)에 평문으로 있던 운영 접속 값(ParsingMeta DB 비밀번호·Object Storage 접근 키·비밀 키)을 교체하고, 새 값은 서버 settings.yaml(`required.edw.*_password`·`required.object_storage.{access_key,secret_key}`)에만 적는다. 통과: 옛 값으로 접속이 거부된다. | 비밀값이 git 이력에 남아 있다(이력은 정리하지 않음 — 새 저장소에는 HEAD 트리만) | 배포 전 | 보안·서버 운영 담당 | CLAUDE.md §4 | 열림 |
| C-46 | **덮기 설정 파일 보안 검토** — 프로세스가 자식에게 값을 넘길 때(`settings.put`·`child_env`)와 `python -m common.config.overrides`가 임시 폴더(`/tmp`)에 `settings-*.yaml`(권한 600 — `base:` 원본 경로 + 바뀐 칸만)을 만든다. 만든 프로세스가 끝날 때 지운다([ops.md#pl-27](../prd/ops.md#pl-27)) — `overrides` 출력과 SIGKILL·OOM만 남는다. 확인: 서버 `/tmp` 정리 주기, 다른 계정이 그 파일을 못 읽는지(`ls -l /tmp/settings-*.yaml`). | 바뀐 칸이 비밀이면 그 값이 파일에 든다 | 배포 전 | 사용자·서버 운영 담당 | `common/config/settings.py` `overlay_file` | 열림 |
| C-68 | **닫은 행의 서버 확인** — ① [pl-13](../prd/load.md#pl-13): 첫 적재 뒤 건너뛴 문서가 지워지지 않았는지, `file_path`가 바뀐 같은 내용의 옛 행은 사람이 지운다. ② [pl-22](../prd/transform.md#pl-22): 이미지·스캔 문서는 VLM 엔진만 돈다 — 첫 전체 e2e 뒤 성공 엔진이 0개인 이미지·스캔 문서가 없는지. ③ [pl-27](../prd/ops.md#pl-27): 상주 컨테이너 `/tmp`에 `settings-*.yaml`이 쌓이지 않는지, 시간 초과 뒤 좀비가 없는지(`ps -eo stat,pid,cmd`에 상태 `Z`인 줄이 0). | 서버에서만 볼 수 있다 | 배포 뒤 | 서버 운영 | pl-13 · pl-22 · pl-27 | 열림 |
| C-70 | **`-e`로 넘기던 값 옮기기** — 엔진·인계 파일은 env 대신 설정 객체로 읽는다. `docker run -e VLM_*`·`-e OCR_*`·`-e GLOSSARY_DIR` 등은 경고만 나오고 쓰이지 않으므로 settings.yaml 해당 칸(`python -m common.config.sample --where <이름>`)에 적는다. 통과: 시작 로그에 env를 무시한다는 경고가 없다. | `-e` 값이 조용히 버려진다 | 0.2.0 배포 전 | 서버 운영 담당 | [op-09](../prd/ops-settings.md#op-09) | 열림 |
| C-71 | **0.2.0 서버 올리기·되돌리기** — 절차는 [0.2.0 배포 기록](../history/deploy_0_2_0.md) 8-3·8-5(판 번호 없는 순서는 [upgrade-guide.md](../operations/upgrade-guide.md)): 새벽 배치 멈춤 → 재처리 시간·디스크 산정 → `settings.yaml.0.1.0`·`pg_dump` 백업 → 새 코드·이미지 zip(`load.sh`) → `init`이 놓은 새 settings.yaml에 옛 값 옮겨 적기(C-95) → `chown 10001`·`chmod 640` → `migrate check`·`up --target all`·`check` → 띄우기·확인. 호스트 준비: `systemctl enable --now podman-restart`, `podman compose version`(없으면 README §5-0 폐쇄망 설치). 통과: `check` 판 끝, 상주 컨테이너 셋이 뜬다. | 0.2.0은 설정 배치가 바뀌어 옛 settings.yaml로는 시작하지 않는다 | 0.2.0 배포 때 | 서버 운영·DB 담당 | [op-10](../prd/doc.md#op-10) | 열림 |
| C-72 | **새벽 배치 = run_pipeline** — ① 타이머 설치 뒤 `ops.nightly.time`을 몇 분 뒤로 적고 `journalctl -u data-pipeline-nightly`에 run_pipeline 시작·끝 줄 ② `--skip-done`이 ParsingMeta 끝난 문서를 건너뜀 ③ 기본 대상이 모든 문서(시작 자리 0 — 사용자 11-05)라 첫 새벽 배치들이 `nightly_max_docs`만큼씩 남은 문서를 처리하는지, 시작 전 applog 파티션 정리 줄에 경고가 없는지 ④ `TimeoutStartSec=6h` 안에 끝나고 종료 코드가 0·1·75 중 하나. 옛 `NIGHTLY_MODULES`·`NIGHTLY_PUBLISH`·`NIGHTLY_MAX_NEW`·`PARSE_DEADLINE`은 settings.yaml에서 지운다(남으면 시작 거부). | 새벽 배치는 서버 타이머에서만 돈다 | 0.2.0 배포 뒤 | 서버 운영 | [pl-23](../prd/ops.md#pl-23) · [pl-18](../prd/ops.md#pl-18) | 열림 |
| C-73 | **원천 칸 확인** — 개발 서버 settings.yaml `required.source.input_source`가 `s3://`·`rdb:*`·`rdb:<이름>`·`rdb:<표>`이면 폴더 또는 `rdb:csv:<경로>`로 바꾼다(그대로면 `pipe_exec.sh parse`가 "원천은 rdb:csv:<경로>만" 오류로 멈춤). `ops.paths.sources_file`·옛 설정 폴더의 `sources.json`은 지워도 된다. | 지운 원천 형식이 남으면 파싱이 시작 때 멈춘다 | 이 판 배포 전 | 서버 운영 | [pl-01](../prd/extract.md#pl-01) | 열림 |
| C-74 | **검색 스키마 판 0002 — 원천별 스키마 5벌(등급 A)** — 판 `0002_search`가 기준 스키마의 옛 표(`doc`·`chunk`·BM25 표·뷰·`load_run`)를 **지우고** `<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`와 공용 `doc_id_seq`를 만든다(되돌리기 없음). ① DB 담당자 승인과 백업 뒤 `bash deploy/host/scripts/pipe_exec.sh migrate up --target search` ② 판 기록이 없는 옛 스키마는 맞출 수 없다 — 새 `required.pg.db_schema`(50자 이하)로 올리고 전체 다시 적재([pl-54](../prd/ops.md#pl-54)) ③ DB 권한: 마이그레이션 계정은 DB 수준 CREATE, 검색 MCP 계정은 5벌의 USAGE·SELECT(+ 앞으로 만들 표의 기본 권한), 적재 계정은 5벌 쓰기와 `<PG_SCHEMA>.doc_id_seq` USAGE. 통과: `migrate check` 판 끝. | 판 0002가 옛 표를 지운다 | 이 판 배포 전 | 서버 운영·DB 담당 | [pl-28](../prd/load-schema.md#pl-28) | 열림 |
| C-75 | **원문 도구 설정** — ① `required.tokens.fulltext`(긴 무작위 글자) — 비면 두 도구가 `not_configured`, 바꾸면 발급된 sfid가 모두 무효(사용자에게 먼저 알림) ② `mcp-server` settings.yaml에 Object Storage 읽기 접속(`required.object_storage`) — 없으면 `source_storage_unavailable` ③ EDW 읽기 계정(`required.edw.read_*`) — 없으면 `registry_unavailable`. 통과: `list_doc_fulltext(source_system="SFDC", limit=1)`이 파일 하나를 낸다. | 새 도구가 설정·계정 없이는 돌지 않는다 | 이 판 배포 때 | 서버 운영 | [mc-17](../prd/mcp.md#mc-17) | 열림 |
| C-76 | **EDW 쪽 DB 담당자 할 일과 적재 계정(등급 A)** — 한 번에 실행하는 `AI.ParsingMeta` DDL(전체 칸은 `docs/operations/parsing_meta_mssql.sql`·`docs/architecture/db_schema.md` §3): ① 칸 이름 `source_key` → `s3_key`(계산 칸 `source_key_hash`와 유일 색인 `UQ_ParsingMeta_key`를 지우고 다시 만듦 — 코드는 전후 모두 돎) ② `ADD loaded_at DATETIME2(0) NULL`(적재가 PG 커밋 뒤 UPDATE) ③ `pipeline_version` → `silver_version` 이름 바꾸기 + `ADD gold_version NVARCHAR(64) NULL` ④ 운영이 더한 분류·고객 칸(`doc_class`·`doc_class_low_conf`·`doc_class_at`·`doc_class_model`·`sf_op_id`·`created_at`·`sf_acc_name` 등) 지우기 — 운영 분류 스크립트가 멈추므로 운영 담당에게 알림. 판 글자·시각 꼴은 DB 담당자와 정한다. ⑤ data-pipeline settings.yaml에 EDW 읽기 계정(적재 때 EDW 조인)과 쓰기 계정(`loaded_at`)이 있는지 — 읽기가 없으면 메타가 빈 채(`meta_missing`) 적재되므로 계정을 넣은 뒤 `--replace`로 다시 적재. ⑥ 운영이 EDW에 SFDC Quote 표(`Id`·`OpportunityId`·`AccountId`)를 만들면 `resources/config/edw_chain.yaml`의 Quote 주석 줄을 켠다. ⑦ 사슬 표·칸 이름이 운영과 같은지: `FileStorageMap.content_version_id`·`FileStorageMap_CRMS`(`s3_key`·`rm_contract_code`·`gate_code`·`gate_version`·`docu_seq`)·`FileStorageMap_LAS`(`s3_key`·`manage_no`·`las_file_id`·`signed_date`)·`SFDC.ContentVersion`·`ContentDocumentLink`·`Task`·`Event`·`Opportunity.Record_Type__c`·`X1st_Contract_Execution_Date__c`·`CRMS.RM_CM_PJTLIST`·`RM_CM_DOCU`·`LAS.Contract`·`LAS.FileManager`(`FileID`) — 다르면 사슬 파일만 고친다. ⑧ 원본 파일 이름 = 원본 경로 끝 조각인지: `SELECT TOP 20 s3_key, original_filename FROM AI.FileStorageMap WHERE RIGHT(s3_key, LEN(original_filename)) <> original_filename` — 0행이면 맞음. ⑨ `SFDC.ContentVersion.CreatedDate`가 UTC인지(같은 문서의 운영 값과 9시간 차이면 맞음 — 아니면 사슬의 `tz: UTC`를 뺌). ⑩ 한 문서의 `Task.WhatId`·`Event.WhatId`가 서로 다른 계정을 가리키는 경우가 있는지(있으면 고객이 비므로 Task 먼저 쓸지 정함). | EDW 표·칸은 DB 담당자만 바꾸고 실제 이름은 서버에서만 확인된다 | 이 판 배포 전 | DB 담당·서버 운영 | [pl-29](../prd/load.md#pl-29) · [pl-25](../prd/load-schema.md#pl-25) | 열림 |
| C-77 | **SFDC 사용자 정의 개체 접두 확인** — `resources/mappings/sfdc_prefix.json`의 `IF_Log__c`(a14)·`EventLogFile__c`(a1G)는 조직마다 다르다. SFDC 관리자가 운영 조직의 접두(와 문서가 붙는 다른 사용자 정의 개체)를 확인해 파일을 고치고 `unconfirmed`에서 뺀다(틀리면 힌트가 `Unknown:<접두>`). EDW 담당은 `ContentVersion.Title`·`Task/Event.Subject·Sent_Received__c`·`Opportunity.StageName·Real_RFP__c·RFP_Received_*`·`LAS.Contract.ApprovalName` 칸이 있는지 보고, 이름이 다르면 `edw_chain.yaml`의 `fields`를 고친다. | 접두는 조직마다 다르다 | 이 판 배포 전 | SFDC 관리자·EDW 담당 | [pl-33](../prd/transform.md#pl-33) | 열림 |
| C-78 | **0.2.0 지문 배치 — 서버 엔진 구성·설정** — ① 저장소 밖 엔진 구성 파일(`ops.paths.stack_file`)을 쓰면 그 파일에 `candidates` 칸이나 지운 엔진(`pdfplumber`·`pypdf`·`calamine`·`pptx`·`pymupdf4llm`)이 없게 한다(있으면 시작 거부, 종료 2). 이미지 행은 `qwen_vlm` 하나. ② settings.yaml의 지운 칸(`ocr_engine`·`sources_file`·`index_root`·`index_conf`·`index_conf_dir`·load·publish 컨테이너 자원 칸·시험 MinIO·`smoke_*`)을 지운다(남으면 시작 거부). 통과: 시작이 거부되지 않는다. 지문이 모두 바뀌어 전 문서를 다시 처리한다([pl-54](../prd/ops.md#pl-54)). | 옛 사본·칸이 남으면 시작 거부 | 0.2.0 배포 때 | 서버 운영 | [pl-46](../prd/transform-cleanup.md#pl-46) | 열림 |
| C-79 | **applog 로깅 DB 적용(등급 A)** — ① DBA와 `applog` 스키마·월 파티션·90일 보존·접근 권한 합의(`get_doc_fulltext` 응답 본문은 문서 원문 전체 — `applog` 표와 대체 폴더 `output/logs`는 원본 문서와 같은 접근 제한) ② `migrate up --target applog` → `check --target applog`(판 끝) — 서버는 `ops.log.db_enabled` 기본 켬(op-13)이라 이 단계가 새 코드를 띄우기 전이다 ③ `dbtool maintain --target applog`를 매일 예약 ④ 운영 비밀 설정의 비어 있지 않은 값이 모두 8자 이상인지(dev·prd 시작 거부 조건 — 값은 기록하지 않음) ⑤ PG 비밀번호는 settings.yaml `required.pg.password`에만 둔다(접속 파일 칸 없음) ⑥ 이미지 안에서 dev·prd 설정으로 `selftest`를 돌려 `[판정] 통과` ⑦ 운영 중 감사 `body_omitted`·`dropped`와 sink `dropped`·`fallback_errors`가 0에 가까운지. | DB 스키마·감사 원문·보존 정책은 담당 협의가 필요 | 배포 전·후 | 서버 운영·DBA·사람 검토 | [op-01](../prd/ops.md#op-01) | 열림 |
| C-80 | **파이프라인 추적 로그 서버 확인** — C-79 뒤 실제 실행 1건으로 `pipe_run` 1행·`pipe_event` 단계 행(extract·transform·embed·load)이 들어오고 `python -m pipeline.tools.perf_report <run_id>`가 읽는지. ① `cpu_ms`·`rss_peak_mb`·`load1_per_cpu`가 채워지는지 ② 대량 배치에서 큐 `dropped`(10000 상한)·`fallback_errors` ③ stdout JSON 줄이 `docker logs`·trigger 출력 해석을 방해하지 않는지(`ops.log.dir`을 줄지 정함) ④ `pipe_event` 월 파티션 크기와 90일 보존. | 서버 접속·DBA 협의가 필요 | 배포 뒤 첫 실행 | 서버 운영·DBA | [op-01](../prd/ops.md#op-01) | 열림 |
| C-81 | **`AI.ParsingMeta.gold_status` 칸** — DB 담당자가 `gold_status`(pending·ok·failed)와 이유 칸을 더할지·꼴을 정하고 DDL을 실행한다(그 뒤 [pl-55](../prd/ops.md#pl-55) PR). 배포 순서: run_pipeline 새 판은 `gold_version` 칸(C-76 ③)이 생긴 뒤에 올린다 — 칸이 없으면 gold가 실패한 문서도 끝난 것으로 쳐 다시 고르지 않는다. 서버 확인: 새벽 배치 하루 뒤 `batch_progress/progress.log`의 'publish FAIL — 원본 남김'·'구조화+적재 FAIL — silver는 남김' 줄, 남은 `_staging/*.bin` 수, `journalctl`의 종료 코드(0·1·75). 남은 한계: gold만 실패한 문서를 다시 고르면 파싱·게시부터 다시 해 Object Storage에 날짜 폴더가 하나 더 생긴다. | gold 실패를 EDW에서 볼 칸이 없다 | 칸을 더하기 전·후 | DB 담당·서버 운영 | [pl-24](../prd/ops.md#pl-24) | 열림 |
| C-82 | **상주 컨테이너 하나로** — ① 0.2.0 배포 때 옛 `data-pipeline-parse`·`data-pipeline-structure`를 멈추고 지운 뒤(`$DOCKER rm -f …`) `host_ctl.sh up -d data-pipeline`([0.2.0 배포 기록](../history/deploy_0_2_0.md) 8-3). ② 자원은 `ops.pipeline_host.parse_cpus`·`parse_mem_limit`(비우면 5·24g) — docker·podman은 호스트 CPU 수보다 큰 `cpus`를 거부하므로 CPU 4개 서버는 `parse_cpus`를 3 이하로. 통과: `data-pipeline` 하나가 뜨고 run_pipeline이 exec한다. | 0.2.0은 상주 컨테이너가 하나로 바뀐다 | 0.2.0 배포 때 | 서버 운영 | [op-10](../prd/doc.md#op-10) | 열림 |
| C-83 | **parse_document 전용 컨테이너·오버레이 패치 없음** — ① `host_ctl.sh up -d data-pipeline mcp-data-parsing`(작업 서비스는 `mcp-data-parsing`의 주 프로세스 — 손 기동 안 함), `mcp-server-keepalive` 타이머가 `mcp-data-parsing`도 살핀다. 일괄 파싱 중 `parse_document` 응답 시간을 잰다([rn-03](../prd/ops.md#rn-03) — 통과 기준은 사용자가 첫 값을 보고 정함). ② 오버레이 패치 compose(`compose.patch.yml`·`compose.patch.mcp.yml`)로 띄운 컨테이너가 있으면 `compose.pipeline.yml`(+ 실행 이미지면 `compose.code.yml`)로 다시 띄운다. 패치 번들은 더 오지 않는다 — 서버 자체 변경과 합칠 때 바뀐 파일은 `git diff --name-status <직전 판 커밋> <새 판 커밋>`, 설명은 `RELEASE_NOTES.md`(release-and-patch §3-2). ③ settings.yaml의 옛 칸(`common.host.patch_code`·`structure_cpus`·`structure_mem_limit`)을 지운다(남으면 시작 거부). | 0.2.0은 parse_document 전용 컨테이너로 바뀐다 | 0.2.0 배포 때 | 서버 운영 | [rn-03](../prd/ops.md#rn-03) · [op-10](../prd/doc.md#op-10) | 열림 |
| C-84 | **FAQ 통째 교체 서버 확인(등급 A — gold 지우기)** — ① 개발 서버에서 FAQ 파일 하나를 새 uuid로 다시 올리고 `run_pipeline.py`를 돌려 로그에 `FAQ 교체: gold faq 문서 N건을 지움`, 끝난 뒤 `<스키마>_faq.doc.file_path`가 FileStorageMap의 FAQ `s3_key`와 같은지 ② FAQ를 바꾸지 않고 다시 돌리면 `FAQ 교체` 로그가 없는지 ③ 실 PG에서 `faq-sync --reset`이 한 트랜잭션인지(중간 실패 시 되돌림) ④ 운영 MSSQL에서 `candidate_pick.faq_status`(ParsingMeta `status_like`)의 `LIKE 'FAQ/%'`가 FAQ 키를 모두 잡는지(정렬 규칙). | 실 PG·FileStorageMap에서만 확인 가능 | 0.2.0 배포 뒤 첫 FAQ 다시 올리기 | 서버 운영 | [pl-41](../prd/load.md#pl-41) | 열림 |
| C-85 | **MCP 도구 상한 서버 확인(등급 A — 도구 계약)** — ① tools/list가 바뀜(`query_edw` 기본 `max_rows` 1000, `parse_document` "기본 100MB 상한") — 클라이언트 담당에게 알림 ② `ops.runtime.parse_max_mb`를 검색 MCP와 `mcp-data-parsing`가 같은 값으로 읽는지, 옛 `ops.services.data_parsing.max_mb`는 지움 ③ 저장소 밖 막힘: 검색 MCP 앞 리버스 프록시의 요청 본문 상한(base64라 100 MB 파일 ≈ 134 MB 본문 — nginx `client_max_body_size` 기본 1 MB)과 읽기 제한 시간, 클라이언트 MCP 라이브러리의 요청 크기·제한 시간 ④ 메모리: 99 MB base64 1건에 검색 MCP 최대 약 620 MB, 파싱 서비스 약 500 MB + 엔진 자식 약 370 MB(PC 실측) — `mcp-server` `mem_limit` 4g에서 큰 업로드가 겹치는지 ⑤ 99 MB·101 MB 파일로 두 길(path·content_b64) 한 번씩 — 99 MB 받음, 101 MB 크기 상한 오류. | 저장소 안 시험은 루프백·PC만 | 0.2.0 배포 때 | 서버 운영·클라이언트 담당 | [mc-08](../prd/mcp.md#mc-08) · [mc-06](../prd/mcp.md#mc-06) | 열림 |
| C-86 | **마스터 표 `<PG_SCHEMA>_master`(등급 A — DB 스키마)** — 표 6개(`client_roster`·`client_master`·`contract_master`·`domain_terms`·`id_patterns`·`units` — CSV 머리글 그대로 `TEXT` + `row_no`)와 `master_meta`, Alembic 갈래 `master`(`0001_master_base`). ① DB 담당자 승인 ② `migrate up --target all` 뒤 `migrate master load`(기본 코드 폴더 `resources/vocab/glossary`, 서버 실명 자료는 컨테이너에 붙인 폴더를 `--dir`로) — **비어 있으면 구조화·검색이 시작하지 않음** ③ 옛 칸 `common.paths.glossary_dir`·`client_roster`·`common.text.search_recency`를 지운다(남으면 시작 거부) ④ `gold_version`이 `<VERSION>+m<해시 8자>` 꼴이 된다(C-76 ③ 꼴 협의에 포함). 통과: 구조화·검색이 시작한다. | 새 스키마는 DB 담당 협의가 필요 | 이 판 배포 때 | DB 담당·서버 운영 | [pl-38](../prd/load.md#pl-38) | 열림 |
| C-87 | **검색 PG만 서버 확인(등급 A — DB 스키마)** — ① `migrate up --target all` 뒤 5벌 `doc`에 `content_date`·`embed_model` 칸이 있고 `corpus_stat`에 `dim`이 없는지 ② 전체 적재 뒤 `SELECT DISTINCT embed_model FROM <스키마>_<원천>.doc`이 원천마다 서버 임베딩 모델 하나인지(NULL·여러 값이면 그 원천의 벡터 검색이 거부됨) ③ 묶음 폴더 마운트 없이 띄운 검색 MCP에서 `search`(원천 하나)가 모델 불일치 오류 없이 근거와 `doc_date`를 내는지 ④ 옛 `ops.paths.mcp_bundle`은 지운다(남으면 시작 거부). | 실 PG·서버 임베딩 모델에서만 확인 가능 | 0.2.0 배포 당일(배포 기록 8-3 5) | 서버 운영·DB 담당 | [mc-19](../prd/mcp.md#mc-19) | 열림 |
| C-88 | **PC 비용 스위치 삭제(돈)** — `no_paid_calls`·`max_calls`·`external_max_docs`·`external_max_questions`·`external_scope`가 없어졌다. ① 서버·PC settings.yaml에 남은 칸을 지운다(남으면 시작 거부) ② `max_calls`로 호출 수를 막던 서버는 그 상한이 없어진다(지출 상한 `budget_usd`만 — 내부망 모델은 선차감 대상 아님) ③ PC에서 `allow_external: true`를 두면 외부 호출이 열린다 — 평소에는 false ④ `budget_usd`를 비운 PC는 하루 0.1달러 상한이 걸린다. | 저장소 밖 설정 파일 | 0.2.0 배포 당일 | 서버 운영·PC 개발자 | [pl-11](../prd/ops.md#pl-11) | 열림 |
| C-89 | **문서 메타 `doc.attrs` JSONB · 사슬 파일 새 꼴 · search `attrs`(PRD [pl-52](../prd/load-schema.md#pl-52), 사용자 11-03 `feature/attrs-jsonb` — 🔒 등급 A: DB 스키마·MCP 도구 계약)** — ① DB 담당자 승인: 마이그레이션 `0005_search` — 5벌 `doc`에 `attrs JSONB` + GIN 색인 `ix_<원천>_doc_attrs`, 원천 전용 칸(0002·0003의 `sf_op_id`…`approvalname`)을 값 그대로 `attrs`에 옮긴 뒤 지움, `v_chunk_source`에 `attrs`(downgrade는 칸을 되살림 — **최선만**: 되살린 칸은 표 끝에 붙어 칸 순서가 0004와 다르고, 옛 칸에 없던 attrs 키는 버려지며, DATE 칸은 실제 날짜인 'YYYY-MM-DD' 글자만 날짜로 바꾸고 그 밖(2024-99-99·2024-02-30 등)은 NULL). PC 개발 PG의 임시 시험 스키마에서 확인함(11-04 — 확인 뒤 지움): 올리기가 값을 잃지 않고 옮기고 GIN 색인이 생김 · 되돌리기(0005 → 0004)가 멈추지 않고 `2024-02-29`는 날짜로 남기고 `2023-02-29`·`2024-02-30`·`2024-99-99`·`not a date`는 NULL, 모르는 키는 버림 · 다시 올리기 뒤 `dbtool check` 차이 0. 남은 것은 개발 서버에서 같은 순서를 한 번 돌려 보는 것뿐. ② `migrate up --target all` 뒤 `migrate check`가 "판 끝 0005_search". ③ **0.1.x 때 고친 사슬 사본을 쓰던 서버**는 새 꼴로 옮겨 적는다(옛 꼴이면 적재·검색이 "사슬 설정 오류"로 멈춤) — [release-and-patch §8](../operations/release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버) ① 상자. ④ `mcp-server`도 `<루트>/edw_chain.yaml`을 붙인다(compose) — 파일이 없으면 안 뜸(`host_ctl.sh init`이 만듦). 사본을 쓰면 settings.yaml `ops.paths.edw_chain`(적재·검색이 함께 읽는 칸 하나) — 옛 `ops.pipeline_paths.edw_chain`에 값이 있던 서버는 새 칸으로 옮겨 적는다(옛 칸이 남으면 시작 거부). ⑤ 도구 계약 바뀜(tools/list 11894 → 12810바이트 — 11-04 search 설명 고침 포함): `search` 입력 `attrs`·근거 `attrs`(13칸, 근거 키가 없는 FAQ·Other는 null)·`contract_no` 채움, `edw_meta` 인자 없음에 `search_attrs` — 클라이언트(GLM 등) 담당에게 알림. ⑥ 전체 적재 뒤 `SELECT attrs FROM <스키마>_sfdc.doc LIMIT 5`에 `sf_op_id`·힌트 키가 차 있고, `search(source_system="SFDC", attrs={"project_code__c": …})`·`edw_meta()`의 `search_attrs`가 맞는지. ⑦ **EDW 메타 적중 수 대조** — 0.1.x는 SQL 조인(MSSQL 기본 정렬 규칙 CI·CHAR 끝 공백 무시)이었고 새 해결기는 파이썬에서 열쇠를 맞춘다(앞뒤 공백 빼고 대소문자 무시 — `pipeline/load/edw_doc_meta.py` `_norm`). 같은 문서 묶음을 적재한 뒤 원천마다 메타가 찬 문서 수(`SELECT count(*) FROM <스키마>_<원천>.doc WHERE attrs ? 'contract_id' OR attrs ? 'sf_op_id' OR attrs ? 'division'`·`client_edw IS NOT NULL`)를 0.1.x 스키마의 같은 칸 수와 대조한다 — 줄었으면 열쇠 꼴(형식·정렬 규칙)이 다른 것이니 줄어든 원천의 사슬 단계를 확인. ⑧ 거르기가 GIN 색인을 타는지 — `EXPLAIN SELECT … FROM <스키마>_sfdc.v_chunk_source WHERE attrs @> '{"sf_op_id": "…"}'`에 `ix_…_doc_attrs`(문서가 적으면 순차 읽기가 나올 수 있음). | 실 PG·서버 EDW·외부 클라이언트에서만 확인된다. 새 판(0005) — MINOR(새 이미지 판 + `migrate up`). | 0.2.0 배포 당일(배포 기록 8-3 5) | DB 담당·서버 운영·클라이언트 담당 | [load-schema.md#pl-52](../prd/load-schema.md#pl-52) · db_schema `gold.doc.attrs` | 열림 |
| C-90 | **서버 확인: 루트 폴더 배치·타이머 설치·DB 로그 기본 켬**(PRD [op-13](../prd/doc.md#op-13), 사용자 11-04) — ① 개발 서버에 새 루트(예 `/home/sbl/dev/`)를 만들고 코드 zip을 풀어 `host_ctl.sh init --group <운영 그룹>` → `<루트>/settings.yaml`·`edw_chain.yaml`·`output/`·`output/_mcp_parse/jobs`(10001, 2775)·`backup/`이 생기고 `env/`·`code/`·`live`가 없는지 ② `host_ctl.sh up -d …` 뒤 `podman inspect data-pipeline mcp-server --format '{{range .Mounts}}{{.Source}} {{end}}'`에 `<루트>/settings.yaml`·`<루트>/edw_chain.yaml`·`<루트>/output`이 보이는지 ③ `host_ctl.sh timers` → `systemctl cat mcp-server-keepalive.service data-pipeline-nightly.service`의 `WorkingDirectory`가 그 코드 폴더 · `systemctl list-timers`에 두 타이머 · 다른 루트에서 다시 부르면 그 루트로 바뀌는지 ④ 새 코드를 띄우기 전에 `migrate up --target all`(applog) → `search` 한 번 뒤 `applog.mcp_log`에 행이 생기고 `<루트>/output/logs/`가 비어 있는지 · 파이프라인 한 건 뒤 `applog.pipe_run`·`pipe_event` 행 ⑤ `<루트>/output`에 `RUNLOG.md`·`runlog.jsonl`·`logs/*.log`·`qa_log/`가 생기지 않는지 ⑥ `parse_document` 도구 설명의 허용 폴더가 `/app/output/_mcp_parse/inbox`로 바뀌었다(도구 목록 바이트 바뀜 — 등급 A) — MCP 클라이언트 담당에게 새 경로를 알린다. | PC에는 podman·systemd·서버 PG가 없어 배치·타이머·DB 로그를 끝까지 볼 수 없다 | 다음 판 배포 때 | 서버 운영·사용자(⑥) | [op-13](../prd/doc.md#op-13) | 열림 |
| C-91 | **EDW 표 설명 자료 받기**(PRD [mc-07](../prd/mcp.md#mc-07), 사용자 11-04) — 저장소에 자료와 만드는 스크립트가 없다. ① 자료 담당에게서 `catalog.json`·`columns.jsonl`(개인정보를 뺀 판)을 받는다 ② 서버 `<루트>/output/edw_meta/`에 복사(UID 10001이 읽게) ③ settings.yaml `search.edw_meta.dir: /app/output/edw_meta` ④ 통과: 검색 MCP에서 `edw_meta()`(인자 없음)가 `not_configured`가 아닌 스키마 목록을 낸다. | 없으면 에이전트가 EDW 표·열 설명을 못 찾음(`query_edw`는 동작) | 이 판 배포 때 | 사용자·서버 운영 | [mc-07](../prd/mcp.md#mc-07) | 열림 |
| C-92 | **settings.yaml 칸 정리 반영**(PRD [op-05](../prd/ops-settings.md#op-05) 메모, 사용자 11-04) — ① 서버·PC settings.yaml에서 지운 칸을 지운다(남으면 시작 거부 — C-95) ② `search.server.fulltext_secret` 값을 `required.tokens.fulltext`로 옮긴다 ③ PC 파일은 외부 모델·지출 상한·로컬 대체 DB 칸을 `dev` 절로 옮긴다 ④ EDW 원천 표(`FileStorageMap`)는 다섯 열(문서 ID·키·크기·파일 이름·내용 판)만 읽는다 — `company`·`doc_type` 거르기를 쓰던 서버는 그 거르기가 없어진다 ⑤ 표 허용 목록(`edw_query.tables`)이 없어졌다 — 표를 좁히려면 DBA가 읽기 계정 권한으로 ⑥ 거의 안 바꾸는 칸 53개(청크 길이·검색 순위 가중치·그림 고르기 상한·로그 DB 대기열·EDW 원천 열 이름 등)를 `tuning` 절로 옮겼다 — 값을 적어 둔 칸만 `tuning.<옛 자리>`로 옮긴다 ⑦ 합친 칸: `extract.prefetch_workers` → `extract.source.fetch_workers`(미리 받기의 기본 동시 수가 2 → 1), `tuning.ops.nightly_run.workers` → `ops.runtime.pipe_workers`. 통과: `host_ctl.sh check`가 통과(옛 자리가 남으면 ① check_env에서 거부). | 저장소 밖 설정 파일 | 이 판 배포 때 | 서버 운영 | [op-05](../prd/ops-settings.md#op-05) | 열림 |
| C-93 | **VLM 처리 통일 뒤 서버 확인**(PRD [pl-43](../prd/transform.md#pl-43), 사용자 11-04 — 🔒 등급 A: 엔진 `qwen_vlm` 지문) — ① 엔진 `qwen_vlm` 지문이 바뀌어 스캔·이미지 문서가 다시 파싱된다 — 문서 수 × 쪽 수만큼 VLM 호출이 늘어나는 시간을 잡고, 첫 몇 건의 대표 결과 글을 0.2.0 결과와 견준다(지시문이 쪽 VLM과 같은 `page_transcribe`로 바뀌어 끝에 `[그림]` 절이 붙을 수 있음). ② 해상도 150(엔진·그림은 200이었음) — 작은 글자·표가 많은 스캔 몇 건에서 숫자·표 칸이 빠지지 않는지 본다. 모자라면 settings.yaml `extract.ocr.dpi`를 올린다(쪽 VLM 캐시 열쇠가 바뀌어 다시 부름). ③ 생각 모델이면 settings.yaml `common.models.vlm.extra_body`에 생각 끄기를 넣는다(예 `{"chat_template_kwargs": {"enable_thinking": false}}`) — 코드에 고정해 두던 그림·중첩 그림의 생각 끄기를 지웠다. 비워 두면 그림 VLM이 출력 상한을 추론에 다 써 빈 답이 될 수 있다. ④ settings.yaml에서 지운 칸(`extract.vlm_page_sec`·`transform.vlm.global_concurrency`·`transform.vlm.page_slow`와 `tuning` 아래 `vlm_page_sec`·`deadline`·`page_concurrency`·`page_min_concurrency`·`vlm_parallel`·`vlm_concurrency`)을 지운다(남으면 시작 거부). 호출 1건 제한이 360초(쪽 VLM·그림) → 180초(`common.models.vlm.timeout`)로 줄었다 — 시간 초과가 늘면 이 값을 올린다. ⑤ run_pipeline 문서 1건 파싱의 엔진 자식 VLM 동시 수가 2 → 8(vlm 레인 6)로 늘었다(결함 수정) — GPU 서버 부하를 본다. ⑥ **배포 순서: 호스트의 `run_pipeline.py`를 새 코드와 같은 판으로 먼저 바꾼다** — 옛 run_pipeline이 주던 `--set VLM_GLOBAL_CONCURRENCY`·`FIGURES_VLM_PARALLEL`·`VLM_PAGE_SLOW`는 새 코드가 모르는 이름이라 시작을 거부한다(모든 파싱 실패). ⑦ OCR 엔진(rapidocr — 지금 구성에서는 파싱 엔진으로 돌지 않음)도 같은 `extract.ocr.dpi`를 읽어 120·200 → 150이 된다 — OCR 엔진 지문은 그대로라 예전 결과와 섞일 수 있다(쓰는 곳이 생기면 다시 파싱). ⑧ parse MCP 서비스의 VLM 쪽당 제한 60초가 없어지고 호출 1건 제한 180초(`common.models.vlm.timeout`)를 쓴다 — 대화형 작업이 오래 기다리면 작업 제한(`job_timeout_sec` 600)을 본다. 쪽 상한(`transform.vlm.page_max`)을 걸면 VLM 엔진도 앞 N쪽만 읽고 성공으로 남는다(대표 결과 trace `pages_total`에 원래 쪽 수). | PC에는 실제 Qwen VLM·서버 문서가 없어 품질·시간을 볼 수 없다 | 다음 판 배포 때 | 서버 운영·사용자(②·③) | [pl-43](../prd/transform.md#pl-43) | 열림 |
| C-94 | **여러 벌 EDW 기록 표 만들기**(PRD [rn-07](../prd/ops.md#rn-07), 사용자 11-05) — 개발 서버에서 `ops.host.instance_name`(예 `hong`)을 쓰는 벌마다 EDW 기록 표 `<parsing_meta_table>_<벌>`(기본 `AI.ParsingMeta_hong`)이 있어야 게시·끝난 문서 조회가 된다(실행 중 DDL 없음). ① `docs/operations/parsing_meta_mssql.sql`을 복사해 표·색인 이름의 `ParsingMeta`를 `ParsingMeta_<벌>`로 바꾼다 ② DB 담당자가 개발 EDW에서 실행 — 읽기 계정 SELECT·쓰기 계정 INSERT/UPDATE 권한도 원본 표와 같게 ③ 통과: 그 벌의 `run_pipeline.py --skip-done --limit 1`이 표 없음 오류 없이 끝나고, 게시 행이 `AI.ParsingMeta_<벌>`에 생긴다(원본 표에는 안 생김). PG 스키마 `<db_schema>_<벌>`은 `migrate up --target all --dim <차원>`이 만든다. | 운영 EDW DDL은 DB 담당 몫 | 벌을 처음 띄울 때 | DB 담당·개발자 | [rn-07](../prd/ops.md#rn-07) | 열림 |
| C-95 | **설정 칸 정리 — 옛 칸은 시작 거부**(PRD [rn-07](../prd/ops.md#rn-07), 사용자 11-05) — ① 옛 칸 표와 `common.config.migrate`를 지웠다. settings.yaml에 옛 배치·옛 자리·지운 칸·모르는 칸이 하나라도 있으면 모든 명령이 시작을 거부하고 칸 이름만 알린다(값은 안 찍음). 배포 전에 서버 settings.yaml을 새 `settings.sample.yaml`과 대조해 고친다. ② 지운 칸: `required.env.run_mode`·`required.tokens.data_parsing`·`parse_proxy`·`trigger`·`search.server.warmup`·`search.edw_query.enabled`·`load.publish.bucket_skip_overlap_check`·`extract.connections.rdb.engine`·`extract.prepare.link`·`ops.mcp_host.jobs_dir`·`ops.services.data_parsing.jobs_dir`·`dev.load.pg_create_extension`·`tuning.structure.chunk_overlap`·`tuning.structure.page_chunk_max`(청커는 `structure` 하나 — rn-08). ③ 토큰 하나: 검색 MCP·`parse_document` 작업 서비스·검증 도구가 모두 `required.tokens.mcp`를 쓴다 — 옛 `data_parsing`·`parse_proxy`에 다른 값을 썼다면 그 값을 쓰던 호출 쪽을 `mcp` 값으로 바꾼다. ④ MCP 업로드 작업 폴더는 `<결과 폴더>/_mcp_parse/jobs`로 고정. ⑤ `run_pipeline.py`가 `--set`으로 넘기던 값 17개(VLM 동시 수·그림 상한·후처리 목록·OCR 스레드·엔진 프로세스 수·대표 선택·CPU 문턱·임베딩 동시 수·배치 등)가 `ops.run_pipeline.*` 칸 — 비우면 지금 값 그대로. ⑥ 게시 버킷 겹침 검사를 지웠다(run_pipeline이 늘 껐음) — `required.publish.bucket`을 원천 버킷과 다르게 두는 것은 운영자 몫. ⑦ **배포 순서: 호스트 `run_pipeline.py`를 새 코드와 같은 판으로** — 옛 run_pipeline은 지운 `PM_BUCKET_SKIP_OVERLAP_CHECK`를 `--set`으로 넘겨 게시가 거부된다. ⑧ 이름을 바꾼 칸(rn-05, 11-05 — 옛 이름이 남으면 시작 거부): `ops.run_docs.*` → `ops.run_pipeline.*`(env 옛 이름 `RUN_DOCS_*` → `RUN_PIPELINE_*`), 그 안의 `warm` → `staging`·`warm_workers` → `staging_workers`, `ops.pipeline_host.run_docs_dir` → `run_pipeline_dir`, `extract.source.warm` → `extract.source.staging`(`SOURCE_WARM` → `SOURCE_STAGING`). 호스트 러너 파일도 `run_docs.py` → `run_pipeline.py`(타이머·`nightly_batch.sh`가 새 이름을 부름, 잠금 `batch_progress/run_pipeline.lock`). ⑨ FAQ 교체 기록이 `batch_progress/faq_seen.txt` → `<결과 폴더>/_faq_seen.txt`(컨테이너 `candidate_pick list`가 읽고 씀) — 배포 때 옮기지 않으면 첫 실행이 FAQ를 한 번 통째로 교체한다. 옛 `_warm/` 폴더는 쓰지 않으니 배포 뒤 지운다. ⑩ `parse_document` 작업 서비스 명령 이름이 `parse-service` → `run-mcp-parsing`(모듈 `pipeline.run_mcp_parsing`) — 호스트 `compose.data-parsing.yml`을 새 코드와 같은 판으로 올린다(옛 compose면 컨테이너가 모르는 명령으로 종료 64). ⑪ **칸 이름 정리(사용자 11-05)** — settings.yaml 칸 189개의 이름을 뜻이 보이게 바꿨다(옛 이름이 남으면 시작 거부 — 옛 자리면 새 자리를 알려 줌). env 이름·`--set` 이름·`host_settings.tsv`는 그대로. 옛 → 새 전체 표는 [부록 — 칸 이름 대응표](#c-95-칸-이름-대응표). 필수 묶음도 바뀌었다: `required.models.llm_*`·`vlm_*` → `required.llm.*`·`required.vlm.*`, `required.source.*` → `extract.source.*`(선택), `required.object_storage.region`·`verify_tls` → `common.connections.object_storage.*`, `required.deploy.output_root` → `ops.host.output_dir`, `ops.pipeline_paths.*` → `ops.paths.*`, 컨테이너 자원 → `ops.containers.<pipeline·data_parsing·mcp>.*`, `ops.run_pipeline.*` → `staging`·`structure`·`parse`·`<레인>_lane` 묶음. ⑫ 지운 칸(남으면 시작 거부): `dev.docker.pg_bind`·`pg_effective_cache`·`pg_maint_mem`·`pg_max_conn`·`pg_mem_limit`·`pg_parallel`·`pg_shared_buffers`·`pg_shm`·`pg_work_mem`(PC 시험 PG compose가 고정값을 씀), `extract.source_limit`(`pipeline.cli --source-limit` 기본 0), `ops.paths.stack_file`(엔진 구성은 늘 `resources/config/pipeline_stack.json`), `tuning.ops.runtime.mem_start_pct`(env `MEM_START_PCT` — 메모리 대기는 `MEM_MAX_PCT`를 씀. DB 열 `applog.pipe_run.mem_start_pct`는 그대로). `draft_terms_lock_timeout`은 읽는 곳이 핸드오프 파일(`common/core/terms.py` — 지문 보호)이라 지우지 않고 `tuning.ops.runtime.glossary_lock_timeout_sec`로 이름만 바꿨다. ⑬ sample은 필수가 아닌 칸에 코드 기본값을 적고 사람이 채울 값·비밀·이미지 기본값 칸은 `null`이다 — `null`은 빈 칸과 같다(호스트 스크립트도). **배포 순서**: 새 코드를 올리기 전에 서버 settings.yaml 칸 이름을 대응표대로 바꾸고 ⑫ 칸을 지운다. 이 표의 다른 행(C-92·C-93 등)에 나온 옛 칸 이름도 대응표로 읽는다. ⑭ **잎 이름 하나씩(사용자 11-05 2차)** — 칸 이름 181개를 한 번 더 바꿨다: 잎 이름이 파일 전체에서 하나뿐이고 절 경로 없이도 뜻이 보이게(`pg_host`·`edw_host`, `embed_base_url`·`llm_base_url`·`vlm_base_url`, 컨테이너 `pipeline_cpus`·`data_parsing_cpus`·`mcp_cpus`, run_pipeline 덮기 `batch_*`, parse MCP 작업 서비스 `mcp_parse_*`). 세 모델 접속 칸은 `required.embed`·`required.llm`·`required.vlm` → `required.models` 한 절. env 이름·`--set` 이름은 그대로. 옛 → 새는 [부록 — 2차 대응표](#c-95-2차-대응표) — 1차 표의 새 이름이 2차 표의 옛 이름이다(둘 다 옮김). ⑮ **모드별 설정(사용자 11-05 3차 — op-14)**: PC 가짜 EDW 칸 `required.edw.edw_local_sqlite_file` → `dev.local.local_edw_sqlite_file`(빈 줄이라도 옛 자리가 남으면 "옛 자리 → 새 자리"로 시작 거부 — 서버 settings.yaml은 그 줄을 지운다). `required.pg.pg_schema`는 비우면 `data_parsing`(서버에 적힌 값은 그대로), `run_pipeline.py`는 `pg_schema`를 더는 요구하지 않는다(EDW 쓰기 계정은 서버 필수 그대로 — 읽기 계정으로 대신하지 않음, 사용자 11-05). PC(local)는 서버 전용 칸을 비우고 경고만 한다(시작 거부 없음). 통과: `host_ctl.sh check` 통과, run_pipeline 1건이 게시까지 간다. | 저장소 밖 설정 파일 — 옛 칸이 남으면 시작하지 않는다 | 이 판 배포 때 | 서버 운영 | [rn-07](../prd/ops.md#rn-07) | 열림 |
| C-96 | **영구 건너뜀 표 `applog.skip_doc_info`(PRD [pl-58](../prd/extract.md#pl-58) — 🔒 등급 A: DB 스키마)** — ① DB 담당자 승인: applog 판 `0002_applog`는 새 표 하나만 만든다(기존 표는 그대로, 되돌리기 없음). 칸은 [db_schema.md](../architecture/db_schema.md) `applog.skip_doc_info`. PC 개발 PG의 임시 스키마 `test_skip_1105`에서 `up`·`check`(차이 없음)·upsert(같은 키 두 번 → `count` 증가)를 확인함 — 그 스키마는 지우지 않고 남겨 둠(사람이 지움). ② 개발·운영 서버는 코드 폴더를 바꾼 뒤 `migrate up --target applog`(또는 `all`) — 안 하면 `candidate_pick list --skip-done`과 받기(stage)가 표 없음으로 실패한다. 이 표는 `ops.log.log_db_enabled`와 관계없이 쓴다. ③ 한 번 들어간 키는 `--skip-done`이 계속 뺀다(기한 없음). 풀 때는 DB 담당자 승인 뒤 `DELETE` — 새 엔진이 확장자를 받게 되면 이유 단위(`reason`), DRM 오탐·같은 `s3_key`로 고친 파일이 올라오면 키 단위(`source_key`). 절차와 SQL은 [env-guide](../operations/env-guide.md) 로그 절. ④ PG 접속 칸을 채운 PC도 파싱 전에 `dbtool up --target applog`(README §4-2). | 실 PG·DB 담당 협의가 필요 | 다음 배포 | DB 담당·서버 운영 | [pl-58](../prd/extract.md#pl-58) | 열림 |
| C-97 | **개발 작업 공간 서버 확인**(PRD [op-16](../prd/ops.md#op-16), 사용자 11-05) — 개발 서버에서 실행 이미지 0.3.0으로 `option.devbox.ssh_port`를 적고 `host_ctl.sh up -d data-pipeline` 뒤 확인한다. ① **podman compose에서도** 덧붙인 `compose.dev.yml`이 `compose.code.yml`의 코드 폴더 마운트(같은 자리)를 바꿔 쓰기 가능이 되는지 — `podman exec data-pipeline touch /app/deploy/.w && rm /app/deploy/.w`가 되고, `mcp-data-parsing`·`mcp`에서는 읽기 전용 그대로인지(docker compose에서만 확인함). ② 비루트 sshd가 SELinux·podman에서 뜨는지 — `ssh -p <포트> rag@<서버>` 열쇠 로그인, 접속 셸에 `RUN_ENV`·`SETTINGS_FILE`·`PYTHONPATH`가 있는지. ③ `<루트>/home`의 주인 10001·700이 컨테이너 안에서도 맞는지(sshd StrictModes). ④ 개발자마다 다른 포트를 방화벽에서 연다(바깥 PC에서 붙을 때). ⑤ opencode가 내부망 모델 주소로 답하는지(외부 접속 없음). | podman compose·SELinux는 PC에서 시험할 수 없음 | 0.3.0 개발 서버 배포 때 | 서버 운영·개발자 | [op-16](../prd/ops.md#op-16) | 열림 |
| C-98 | **같은 밤 중복·staging ETag 서버 확인**(PRD [pl-59](../prd/extract.md#pl-59), 사용자 11-05) — 코드 폴더만 교체. ① 러너는 `stage_one()`이 늘 `stage`를 부르고(ETag 비교·이번 실행 표지를 거침) `drop_original()`이 `<sha1>.etag`도 지운다. ② 개발 서버 한 밤 실행 뒤: 같은 내용 두 문서 중 하나가 ParsingMeta `skipped_dup`, `applog.skip_doc_info`에 `reason = 'duplicate_sha256'` 행, `applog.pipe_event` `extract.skip` 행의 `metrics.dup_of`가 먼저 받은 원본 키인지 본다. `_docflow/_seen_sha`가 컨테이너 사용자(10001)로 만들어지는지(러너가 `_docflow`를 777로 만듦). ③ 원본을 바꿔 다시 올린 문서(크기 같음)가 다시 받아지는지(`extract.download` 행에 `reused` 없음). | 같은 밤 중복·ETag는 서버 Object Storage·실행에서만 확인됨 | 0.3.0 개발 서버 배포 때 | 서버 운영·개발자 | [pl-59](../prd/extract.md#pl-59) | 열림 |
| C-101 | **게시 키·러너 정리 서버 확인**(0.3.0, 사용자 11-05) — ① 개발 서버에서 문서 1~2건 게시 뒤 Object Storage 결과 키가 `<publish_prefix>/FileStorageMap/<s3_key 폴더>/<이름>_<날짜>.md`이고 원천 이름이 두 번 나오지 않는지(코드는 FileStorageMap `s3_key`가 `SFDC/<uuid>/<파일>`처럼 원천 이름으로 시작한다고 봄 — PC 대역 기준, 실제 표 모양은 db_schema D-1) ② 같은 문서를 다시 게시하면 publish 출력 `upload_skip_existing`이 1이고 새 객체가 없는지 ③ 게시·구조화 시간 초과 뒤 `podman exec data-pipeline ps -ef`에 그 문서 프로세스가 남지 않는지 ④ 실행 이미지 시작 로그 `[image] … 코드 <짧은 커밋>`(git clone 코드 폴더) ⑤ 운영 코드 묶음 `tar -tzf code-*.tar.gz`에 `.git`·`valid_env`·`validation`·`test_space`가 없는지. | 서버 Object Storage·EDW·podman은 PC에서 볼 수 없다 | 0.3.0 개발 서버 배포 때 | 서버 운영 | [pl-09](../prd/load.md#pl-09) · [pl-61](../prd/load.md#pl-61) · [rn-09](../prd/ops.md#rn-09) | 열림 |
| C-102 | **0.3.0 새 실행 이미지 — 안 쓰는 패키지 뺌**(PRD [pl-53](../prd/transform-cleanup.md#pl-53)) — `google-adk`·`litellm`을 두 이미지 의존성에서 뺐다(의존성 지문 `f0fcc30bd067bc2f` → `da796674b39fd674`). ① PC에서 `*-runtime:0.3.0` 두 이미지를 새로 빌드해 `selftest_gate.sh`가 `[판정] 통과` ② 폐쇄망 휠 폴더는 새로 받을 것 없음(빼기만) ③ 서버에 새 실행 이미지를 올리고 0.3.0 코드 폴더로 띄운다(지문이 다르면 시작 때 멈춤). | 의존성 지문이 바뀌면 옛 실행 이미지에서는 새 코드가 시작하지 않는다 | 0.3.0 배포 때 | 서버 운영·사용자 | [pl-53](../prd/transform-cleanup.md#pl-53) | 열림 |
| C-103 | **내부망 gitea 준비** — gitea 저장소 주소·계정·권한(개발자마다 읽기·자기 브랜치 쓰기, `main`은 지정한 사람만)을 정하고, 외부망 `main`을 내부망 gitea로 옮기는 방법(판 zip을 가져와 커밋으로 올림 등)과 때(판마다·정기)를 정한다. 주소·계정은 문서에 쓰지 않는다. 통과: 개발자 한 명이 [gitea-guide](../operations/gitea-guide.md) 2절대로 clone·push까지 된다. | 개발자별 코드 폴더가 gitea를 전제로 한다 | 개발자별 벌을 처음 띄우기 전 | 서버 운영(gitea 관리자)·사용자 | gitea-guide | 열림 |
| C-104 | **개발자별 벌 목록을 둘 곳** — 벌 이름(`ops.host.instance_name`)·포트 두 칸·PG 스키마·EDW 기록 표 이름을 개발자마다 한 줄로 적는 표를 서버 운영 기록 폴더(`<기록>/instances.md` 등)에 둘지 정한다(값만 — 비밀 없음). 통과: 새 개발자가 그 표를 보고 겹치지 않는 포트·이름을 고른다. | 포트·이름이 겹치면 뒤에 띄운 벌이 시작하지 못한다 | 두 번째 개발자 벌을 띄우기 전 | 서버 운영 | [server-guide §1-3](../operations/server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별) | 열림 |
| C-105 | **이미지 저장소 인수인계** — 개발 서버용 실행 이미지 조각이 지금 개인 비공개 저장소 `jehunlee302/sbl_images`(README §5-2)에 있다. 팀·조직 저장소로 옮기고(이력·`load.sh`·판 폴더 그대로), 새 담당자·서버 운영에게 읽기 권한, 빌드 담당에게 쓰기 권한을 준다. README·release-and-patch의 저장소 이름을 새 이름으로 바꾼다. 통과: 새 담당자가 자기 계정으로 zip을 받아 `load.sh <판>`이 된다. | 개인 계정에만 있으면 담당이 바뀌면 이미지를 못 받는다 | 인수인계 전 | 지금 담당자 | README §5-2 | 열림 |
| C-106 | **0.3.0 첫 새벽 배치 — 실행기·레인 병렬·staging 전체 흐름 서버 확인**(PRD [rn-01](../prd/ops.md#rn-01)·[pl-59](../prd/extract.md#pl-59), 사용자 11-06) — PC는 `run_pipeline.py`를 돌리지 않아(운영 접속) 레인 병렬·staging은 단위 시험과 컨테이너 E2E(파싱 → 적재 → 검색 → 게시, 이미지 `rc030-1106b`)까지만 확인했다. 개발 서버에서 문서 20~30건(가벼운·중간·스캔 섞어)으로 한 밤 실행 뒤: ① 세 레인(light·medium·vlm)이 모두 문서를 받고, 진행 중 vlm 문서가 `vlm_lane.vlm_lane_max_concurrent_docs`를 넘지 않는다(`applog.pipe_event` 시작·끝 시각) ② 공유 워커가 빈 레인에서 대기열이 긴 레인을 돕는다 ③ 엔진 시간 초과·실패 0(동시 수가 서버 CPU에 맞는지 — PC는 동시 수가 많으면 시간 초과가 났다) ④ staging이 `staging.staging_max_docs`만큼만 미리 받고 끝난 문서를 지운다 ⑤ pptx·txt·csv는 엔진 하나만 돈다(`pl-03` 규칙 8). | PC에서 실행기를 돌릴 수 없어 병렬 구조·staging은 서버에서만 확인됨 | 0.3.0 개발 서버 첫 밤 | 배포 담당 | [upgrade-guide.md](../operations/upgrade-guide.md) | 열림 |

## 부록 — 설정 칸 이름 대응표

C-95의 칸 이름 바꾸기 표다. 앞 판의 settings.yaml을 새 판으로 옮길 때 본다([upgrade-guide §5](../operations/upgrade-guide.md#5-설정-고치기)).

### C-95 칸 이름 대응표

옛 칸(settings.yaml 자리) → 새 칸. 값은 그대로 옮긴다.

| 옛 칸 | 새 칸 |
|---|---|
| `common.connections.rdb.connect_kwargs` | `common.connections.edw.extra_connect_args` |
| `common.models.embed.query_cache` | `common.models.embed.query_cache_file` |
| `common.models.embed.query_prefix` | `common.models.embed.query_instruction` |
| `common.models.llm.cache_dir` | `common.models.llm.response_cache_dir` |
| `common.models.llm.extra_body` | `common.models.llm.extra_request_body` |
| `common.models.llm.rpm` | `common.models.llm.max_calls_per_minute` |
| `common.models.vlm.concurrency` | `common.models.vlm.requests_per_doc` |
| `common.models.vlm.extra_body` | `common.models.vlm.extra_request_body` |
| `common.models.vlm.max_concurrency` | `common.models.vlm.max_total_requests` |
| `common.models.vlm.timeout` | `common.models.vlm.timeout_sec` |
| `dev.connections.pg.standin_dir` | `dev.pg_standin.dir` |
| `dev.connections.pg.standin_schema` | `dev.pg_standin.schema` |
| `dev.docker.smoke_keep` | `dev.docker.smoke_keep_pg` |
| `dev.docker.smoke_limit` | `dev.docker.smoke_max_docs` |
| `dev.docker.smoke_settings` | `dev.docker.smoke_settings_file` |
| `dev.llm_fake` | `dev.fake_llm` |
| `dev.mcp.mcp_url` | `dev.search_ui.mcp_url` |
| `dev.mcp.ui_port` | `dev.search_ui.port` |
| `dev.models.embed.est_usd` | `dev.models.embed.est_usd_per_call` |
| `dev.models.guard.budget_usd` | `dev.models.guard.daily_budget_usd` |
| `dev.models.guard.spend_file` | `dev.models.guard.spend_ledger_file` |
| `dev.models.llm.est_usd` | `dev.models.llm.est_usd_per_turn` |
| `dev.models.llm.price_in` | `dev.models.llm.price_in_usd_per_mtok` |
| `dev.models.llm.price_out` | `dev.models.llm.price_out_usd_per_mtok` |
| `dev.models.vlm.est_usd` | `dev.models.vlm.est_usd_per_call` |
| `extract.connections.secure_doc.passwords_file` | `extract.secure_doc.passwords_file` |
| `extract.doc_parallel` | `transform.represent.parallel_docs` |
| `extract.max_new` | `extract.max_new_docs_per_run` |
| `extract.ocr.dpi` | `extract.page_render_dpi` |
| `extract.ocr.max_pages` | `extract.ocr.max_pages_per_doc` |
| `extract.ocr.threads` | `extract.ocr.onnx_threads` |
| `extract.prepare.rotate` | `extract.prepare.rotate_pages` |
| `extract.rapidocr_page_workers` | `extract.ocr.rapidocr_page_threads` |
| `extract.skipped_log` | `extract.skipped_docs_log` |
| `extract.source.fetch_workers` | `extract.source.fetch_threads` |
| `extract.source.staging` | `extract.source.staging_dir` |
| `load.edw_path_prefix` | `load.stored_path_prefix` |
| `ops.host.docker` | `ops.host.container_cli` |
| `ops.host.image_stage_dir` | `ops.host.prune_stage_dir` |
| `ops.host.instance` | `ops.host.instance_name` |
| `ops.host.prune_keep` | `ops.host.prune_keep_versions` |
| `ops.log.dir` | `ops.log.json_dir` |
| `ops.mcp_host.cpus` | `ops.containers.mcp.cpus` |
| `ops.mcp_host.mem_limit` | `ops.containers.mcp.mem_limit` |
| `ops.nightly.deadline` | `ops.nightly.stop_time` |
| `ops.nightly.time` | `ops.nightly.start_time` |
| `ops.paths.doc_dir` | `ops.paths.docs_dir` |
| `ops.paths.doc_dir_prepared` | `ops.paths.prepared_docs_dir` |
| `ops.paths.draft_terms_out` | `ops.paths.glossary_draft_file` |
| `ops.paths.edw_chain` | `ops.paths.edw_chain_file` |
| `ops.paths.source_manifest` | `ops.paths.source_manifest_file` |
| `ops.pipeline_host.data_parsing_cpu_shares` | `ops.containers.data_parsing.cpu_shares` |
| `ops.pipeline_host.data_parsing_cpus` | `ops.containers.data_parsing.cpus` |
| `ops.pipeline_host.data_parsing_mem_limit` | `ops.containers.data_parsing.mem_limit` |
| `ops.pipeline_host.parse_cpus` | `ops.containers.pipeline.cpus` |
| `ops.pipeline_host.parse_mem_limit` | `ops.containers.pipeline.mem_limit` |
| `ops.pipeline_host.run_pipeline_dir` | `ops.run_pipeline.work_dir` |
| `ops.pipeline_paths.images_root` | `ops.paths.figure_images_dir` |
| `ops.pipeline_paths.out_root` | `ops.paths.output_dir` |
| `ops.pipeline_paths.parse_tmp` | `ops.paths.parse_temp_dir` |
| `ops.pipeline_paths.raw_root` | `ops.paths.raw_cache_dir` |
| `ops.pipeline_paths.soffice_bin` | `ops.paths.soffice_path` |
| `ops.run_pipeline.bm25_threads` | `ops.run_pipeline.structure.bm25_threads` |
| `ops.run_pipeline.cpu_gate` | `ops.run_pipeline.parse.max_cpu_load` |
| `ops.run_pipeline.embed_batch` | `ops.run_pipeline.structure.embed_batch_size` |
| `ops.run_pipeline.embed_concurrency` | `ops.run_pipeline.structure.embed_concurrency` |
| `ops.run_pipeline.fetch_workers` | `ops.run_pipeline.staging.fetch_threads` |
| `ops.run_pipeline.figures_max` | `ops.run_pipeline.parse.max_figures_per_doc` |
| `ops.run_pipeline.light_cpu_gate` | `ops.run_pipeline.light_lane.max_cpu_load` |
| `ops.run_pipeline.light_dedicated` | `ops.run_pipeline.light_lane.dedicated_workers` |
| `ops.run_pipeline.light_shared` | `ops.run_pipeline.light_lane.shared_workers` |
| `ops.run_pipeline.medium_dedicated` | `ops.run_pipeline.medium_lane.dedicated_workers` |
| `ops.run_pipeline.medium_shared` | `ops.run_pipeline.medium_lane.shared_workers` |
| `ops.run_pipeline.ocr_threads` | `ops.run_pipeline.parse.onnx_threads` |
| `ops.run_pipeline.parse_post` | `ops.run_pipeline.parse.post_steps` |
| `ops.run_pipeline.pipe_procs` | `ops.run_pipeline.parse.engine_processes` |
| `ops.run_pipeline.qa_light` | `ops.run_pipeline.parse.skip_full_qa` |
| `ops.run_pipeline.rapidocr_page_workers` | `ops.run_pipeline.parse.rapidocr_page_threads` |
| `ops.run_pipeline.rep_select` | `ops.run_pipeline.parse.engine_pick` |
| `ops.run_pipeline.scan_rotate` | `ops.run_pipeline.parse.rotate_scans` |
| `ops.run_pipeline.staging` | `ops.run_pipeline.staging.max_docs` |
| `ops.run_pipeline.staging_workers` | `ops.run_pipeline.staging.workers` |
| `ops.run_pipeline.struct_backlog` | `ops.run_pipeline.structure.max_backlog` |
| `ops.run_pipeline.struct_workers` | `ops.run_pipeline.structure.workers` |
| `ops.run_pipeline.vlm_cap` | `ops.run_pipeline.vlm_lane.max_concurrent_docs` |
| `ops.run_pipeline.vlm_concurrency` | `ops.run_pipeline.parse.vlm_requests_per_doc` |
| `ops.run_pipeline.vlm_dedicated` | `ops.run_pipeline.vlm_lane.dedicated_workers` |
| `ops.run_pipeline.vlm_lane_concurrency` | `ops.run_pipeline.vlm_lane.vlm_requests_per_doc` |
| `ops.run_pipeline.vlm_lane_post` | `ops.run_pipeline.vlm_lane.post_steps` |
| `ops.run_pipeline.vlm_shared` | `ops.run_pipeline.vlm_lane.shared_workers` |
| `ops.runtime.data_parsing_port` | `ops.services.data_parsing.port` |
| `ops.runtime.lib_env` | `ops.runtime.library_env` |
| `ops.runtime.parse_max_mb` | `ops.services.data_parsing.max_file_mb` |
| `ops.runtime.pipe_procs` | `ops.runtime.engine_processes` |
| `ops.runtime.pipe_workers` | `ops.runtime.vlm_parallel_docs` |
| `ops.services.data_parsing.roots` | `ops.services.data_parsing.allowed_roots` |
| `required.deploy.doc_src` | `required.deploy.host_docs_dir` |
| `required.deploy.output_root` | `ops.host.output_dir` |
| `required.deploy.pg_container` | `required.deploy.pg_container_name` |
| `required.edw.sqlite` | `required.edw.local_sqlite_file` |
| `required.models.llm_api_key` | `required.llm.api_key` |
| `required.models.llm_base_url` | `required.llm.base_url` |
| `required.models.llm_model` | `required.llm.model` |
| `required.models.vlm_api_key` | `required.vlm.api_key` |
| `required.models.vlm_base_url` | `required.vlm.base_url` |
| `required.models.vlm_model` | `required.vlm.model` |
| `required.object_storage.region` | `common.connections.object_storage.region` |
| `required.object_storage.verify_tls` | `common.connections.object_storage.verify_tls` |
| `required.pg.db` | `required.pg.database` |
| `required.source.input_source` | `extract.source.input_location` |
| `required.source.source_bucket` | `extract.source.default_bucket` |
| `required.source.source_uri_prefix` | `extract.source.uri_prefix` |
| `required.tokens.fulltext` | `required.tokens.fulltext_sign_key` |
| `search.edw_meta.dir` | `search.edw_meta.catalog_dir` |
| `search.server.host` | `search.server.bind_host` |
| `search.server.manifest` | `search.server.manifest_file` |
| `search.server.max_concurrency` | `search.server.max_concurrent_tools` |
| `transform.represent.post` | `transform.represent.post_steps` |
| `transform.represent.qa_light` | `transform.represent.skip_full_qa` |
| `transform.represent.rep_select` | `transform.represent.engine_pick` |
| `transform.structure.embed_cache` | `transform.structure.embed_cache_file` |
| `transform.vlm.figures_max` | `transform.vlm.max_figures_per_doc` |
| `transform.vlm.page_max` | `transform.vlm.max_pages_per_doc` |
| `tuning.common.connections.pg.connect_timeout` | `tuning.common.connections.pg.connect_timeout_sec` |
| `tuning.common.connections.pg.pool_max` | `tuning.common.connections.pg.pool_max_connections` |
| `tuning.common.models.embed.query_cache_max` | `tuning.common.models.embed.query_cache_max_rows` |
| `tuning.common.models.embed.timeout` | `tuning.common.models.embed.timeout_sec` |
| `tuning.common.models.llm.empty_retry_max` | `tuning.common.models.llm.empty_retry_max_tokens` |
| `tuning.common.models.llm.timeout` | `tuning.common.models.llm.timeout_sec` |
| `tuning.common.models.transport.connect_timeout` | `tuning.common.models.transport.connect_timeout_sec` |
| `tuning.common.models.transport.down_after` | `tuning.common.models.transport.down_after_failures` |
| `tuning.common.models.transport.down_cooldown` | `tuning.common.models.transport.down_cooldown_sec` |
| `tuning.common.models.vlm.retry` | `tuning.common.models.vlm.retries` |
| `tuning.common.text.draft_terms_max` | `tuning.common.text.glossary_draft_max_rows` |
| `tuning.common.text.search_en_stem` | `tuning.common.text.english_singularize` |
| `tuning.common.text.token_num_norm` | `tuning.common.text.number_unit_normalize` |
| `tuning.extract.attach.max_n` | `tuning.extract.attach.max_count` |
| `tuning.extract.attach.timeout` | `tuning.extract.attach.timeout_sec` |
| `tuning.extract.cache.parse_cache_max_gb` | `tuning.extract.cache.max_gb` |
| `tuning.extract.connections.rdb.columns.content_version` | `tuning.extract.source_columns.content_version` |
| `tuning.extract.connections.rdb.columns.doc_id` | `tuning.extract.source_columns.doc_id` |
| `tuning.extract.connections.rdb.columns.filename` | `tuning.extract.source_columns.filename` |
| `tuning.extract.connections.rdb.columns.key` | `tuning.extract.source_columns.storage_key` |
| `tuning.extract.connections.rdb.columns.size` | `tuning.extract.source_columns.file_size` |
| `tuning.extract.connections.rdb.increment_col` | `tuning.extract.source_columns.increment` |
| `tuning.extract.engine_retry` | `tuning.extract.engine_retries` |
| `tuning.extract.fill_merged` | `tuning.extract.fill_merged_cells` |
| `tuning.extract.hidden_overlap_max` | `tuning.extract.max_hidden_overlap_pages` |
| `tuning.extract.isolate_overhead` | `tuning.extract.isolate_startup_sec` |
| `tuning.extract.low_priority` | `tuning.extract.low_priority_engines` |
| `tuning.extract.ocr.table_grid` | `tuning.extract.ocr.table_grid_from_boxes` |
| `tuning.extract.rotated_max` | `tuning.extract.max_rotated_pages` |
| `tuning.extract.text_page_sec` | `tuning.extract.text_engine_page_timeout_sec` |
| `tuning.extract.warmup_sec` | `tuning.extract.first_doc_min_timeout_sec` |
| `tuning.ops.runtime.cpu_max_load` | `tuning.ops.runtime.max_cpu_load` |
| `tuning.ops.runtime.draft_terms_lock_timeout` | `tuning.ops.runtime.glossary_lock_timeout_sec` |
| `tuning.ops.runtime.mem_settle_margin` | `tuning.ops.runtime.mem_settle_margin_pct` |
| `tuning.ops.runtime.pipe_max_procs` | `tuning.ops.runtime.max_engine_processes` |
| `tuning.ops.runtime.pipe_proc_gb` | `tuning.ops.runtime.gb_per_engine_process` |
| `tuning.ops.runtime.pipe_reserve_cpus` | `tuning.ops.runtime.reserved_cpus` |
| `tuning.ops.runtime.pipe_reserve_gb` | `tuning.ops.runtime.reserved_gb` |
| `tuning.ops.runtime.pipe_threads` | `tuning.ops.runtime.threads_per_process` |
| `tuning.ops.services.data_parsing.procs` | `tuning.ops.services.data_parsing.engine_processes` |
| `tuning.ops.services.data_parsing.queue_max` | `tuning.ops.services.data_parsing.max_queued_jobs` |
| `tuning.ops.services.data_parsing.text_page_sec` | `tuning.ops.services.data_parsing.text_engine_page_timeout_sec` |
| `tuning.ops.services.data_parsing.warmup_sec` | `tuning.ops.services.data_parsing.first_try_min_timeout_sec` |
| `tuning.search.edw_meta.max_bytes` | `tuning.search.edw_meta.max_response_bytes` |
| `tuning.search.edw_query.max_bytes` | `tuning.search.edw_query.max_response_bytes` |
| `tuning.search.methods` | `tuning.search.default_methods` |
| `tuning.search.output.max_chars` | `tuning.search.output.max_response_bytes` |
| `tuning.search.pg.filter_exact_max` | `tuning.search.pg.exact_search_max_chunks` |
| `tuning.search.server.max_queue` | `tuning.search.server.max_queued_tools` |
| `tuning.transform.figures.ocr_parallel` | `tuning.transform.figures.ocr_threads` |
| `tuning.transform.figures.pptx_convert_sec` | `tuning.transform.figures.soffice_timeout_sec` |
| `tuning.transform.figures.pptx_render_max` | `tuning.transform.figures.pptx_max_rendered_slides` |
| `tuning.transform.figures.pptx_shapes_max` | `tuning.transform.figures.pptx_max_shape_slides` |
| `tuning.transform.figures.pptx_smartart_max` | `tuning.transform.figures.pptx_max_smartart_slides` |
| `tuning.transform.figures.vectors_max` | `tuning.transform.figures.max_vector_pages` |
| `tuning.transform.structure.chunk_size` | `tuning.transform.structure.chunk_target_chars` |
| `tuning.transform.structure.chunk_table` | `tuning.transform.structure.split_tables` |
| `tuning.transform.structure.chunk_table_rows` | `tuning.transform.structure.table_rows_per_chunk` |
| `tuning.transform.structure.embed_batch` | `tuning.transform.structure.embed_batch_size` |
| `tuning.transform.structure.embed_retry` | `tuning.transform.structure.embed_retries` |
| `tuning.transform.vlm.fig_min_px` | `tuning.transform.figures.min_side_px` |
| `tuning.transform.vlm.fig_ocr_max` | `tuning.transform.figures.max_ocr_per_doc` |
| `tuning.transform.vlm.fig_photo_area_min` | `tuning.transform.figures.photo_min_area_ratio` |
| `tuning.transform.vlm.fig_photo_max_tokens` | `tuning.transform.figures.photo_max_tokens` |
| `tuning.transform.vlm.fig_photo_ocr_max` | `tuning.transform.figures.photo_max_ocr_chars` |
| `tuning.transform.vlm.fig_text_ocr_min` | `tuning.transform.figures.text_image_min_ocr_chars` |

### C-95 2차 대응표

1차 표의 새 칸(옛) → 2차 새 칸. 값은 그대로 옮긴다.

| 옛 칸 | 새 칸 |
|---|---|
| `common.connections.edw.extra_connect_args` | `common.connections.edw.edw_extra_connect_args` |
| `common.connections.object_storage.region` | `common.connections.object_storage.object_storage_region` |
| `common.connections.object_storage.verify_tls` | `common.connections.object_storage.object_storage_verify_tls` |
| `common.models.embed.query_cache_file` | `common.models.embed.embed_query_cache_file` |
| `common.models.embed.query_instruction` | `common.models.embed.embed_query_instruction` |
| `common.models.llm.extra_request_body` | `common.models.llm.llm_extra_request_body` |
| `common.models.llm.max_calls_per_minute` | `common.models.llm.llm_max_calls_per_minute` |
| `common.models.llm.response_cache_dir` | `common.models.llm.llm_response_cache_dir` |
| `common.models.vlm.extra_request_body` | `common.models.vlm.vlm_extra_request_body` |
| `common.models.vlm.max_total_requests` | `common.models.vlm.vlm_max_total_requests` |
| `common.models.vlm.requests_per_doc` | `common.models.vlm.vlm_requests_per_doc` |
| `common.models.vlm.timeout_sec` | `common.models.vlm.vlm_timeout_sec` |
| `dev.docker.pg_image` | `dev.docker.smoke_pg_image` |
| `dev.models.embed.allow_external` | `dev.models.embed.embed_allow_external` |
| `dev.models.embed.est_usd_per_call` | `dev.models.embed.embed_est_usd_per_call` |
| `dev.models.llm.allow_external` | `dev.models.llm.llm_allow_external` |
| `dev.models.llm.est_usd_per_turn` | `dev.models.llm.llm_est_usd_per_turn` |
| `dev.models.llm.price_in_usd_per_mtok` | `dev.models.llm.llm_price_in_usd_per_mtok` |
| `dev.models.llm.price_out_usd_per_mtok` | `dev.models.llm.llm_price_out_usd_per_mtok` |
| `dev.models.vlm.allow_external` | `dev.models.vlm.vlm_allow_external` |
| `dev.models.vlm.est_usd_per_call` | `dev.models.vlm.vlm_est_usd_per_call` |
| `dev.pg_standin.dir` | `dev.pg_standin.pg_standin_dir` |
| `dev.pg_standin.schema` | `dev.pg_standin.pg_standin_schema` |
| `dev.search_ui.mcp_url` | `dev.search_ui.search_ui_mcp_url` |
| `dev.search_ui.port` | `dev.search_ui.search_ui_port` |
| `extract.max_file_mb` | `extract.max_source_file_mb` |
| `extract.ocr.max_pages_per_doc` | `extract.ocr.ocr_max_pages_per_doc` |
| `extract.ocr.onnx_threads` | `extract.ocr.ocr_onnx_threads` |
| `extract.secure_doc.passwords_file` | `extract.secure_doc.secure_doc_passwords_file` |
| `extract.source.default_bucket` | `extract.source.source_default_bucket` |
| `extract.source.fetch_threads` | `extract.source.source_fetch_threads` |
| `extract.source.input_location` | `extract.source.source_input_location` |
| `extract.source.staging_dir` | `extract.source.source_staging_dir` |
| `extract.source.uri_prefix` | `extract.source.source_uri_prefix` |
| `ops.containers.data_parsing.cpu_shares` | `ops.containers.data_parsing.data_parsing_cpu_shares` |
| `ops.containers.data_parsing.cpus` | `ops.containers.data_parsing.data_parsing_cpus` |
| `ops.containers.data_parsing.mem_limit` | `ops.containers.data_parsing.data_parsing_mem_limit` |
| `ops.containers.mcp.cpus` | `ops.containers.mcp.mcp_cpus` |
| `ops.containers.mcp.mem_limit` | `ops.containers.mcp.mcp_mem_limit` |
| `ops.containers.pipeline.cpus` | `ops.containers.pipeline.pipeline_cpus` |
| `ops.containers.pipeline.mem_limit` | `ops.containers.pipeline.pipeline_mem_limit` |
| `ops.host.output_dir` | `ops.host.host_output_dir` |
| `ops.log.db_enabled` | `ops.log.log_db_enabled` |
| `ops.log.fallback_dir` | `ops.log.log_fallback_dir` |
| `ops.log.json_dir` | `ops.log.log_json_dir` |
| `ops.log.level` | `ops.log.log_level` |
| `ops.log.retention_days` | `ops.log.log_retention_days` |
| `ops.nightly.max_docs` | `ops.nightly.nightly_max_docs` |
| `ops.nightly.start_time` | `ops.nightly.nightly_start_time` |
| `ops.nightly.stop_time` | `ops.nightly.nightly_stop_time` |
| `ops.paths.docs_dir` | `ops.paths.source_docs_dir` |
| `ops.paths.output_dir` | `ops.paths.container_output_dir` |
| `ops.run_pipeline.light_lane.dedicated_workers` | `ops.run_pipeline.light_lane.light_lane_dedicated_workers` |
| `ops.run_pipeline.light_lane.max_cpu_load` | `ops.run_pipeline.light_lane.light_lane_max_cpu_load` |
| `ops.run_pipeline.light_lane.shared_workers` | `ops.run_pipeline.light_lane.light_lane_shared_workers` |
| `ops.run_pipeline.medium_lane.dedicated_workers` | `ops.run_pipeline.medium_lane.medium_lane_dedicated_workers` |
| `ops.run_pipeline.medium_lane.shared_workers` | `ops.run_pipeline.medium_lane.medium_lane_shared_workers` |
| `ops.run_pipeline.parse.engine_pick` | `ops.run_pipeline.parse.batch_engine_pick` |
| `ops.run_pipeline.parse.engine_processes` | `ops.run_pipeline.parse.batch_engine_processes` |
| `ops.run_pipeline.parse.max_cpu_load` | `ops.run_pipeline.parse.batch_max_cpu_load` |
| `ops.run_pipeline.parse.max_figures_per_doc` | `ops.run_pipeline.parse.batch_max_figures_per_doc` |
| `ops.run_pipeline.parse.onnx_threads` | `ops.run_pipeline.parse.batch_ocr_onnx_threads` |
| `ops.run_pipeline.parse.post_steps` | `ops.run_pipeline.parse.batch_post_steps` |
| `ops.run_pipeline.parse.rapidocr_page_threads` | `ops.run_pipeline.parse.batch_rapidocr_page_threads` |
| `ops.run_pipeline.parse.rotate_scans` | `ops.run_pipeline.parse.batch_rotate_scans` |
| `ops.run_pipeline.parse.skip_full_qa` | `ops.run_pipeline.parse.batch_skip_full_qa` |
| `ops.run_pipeline.parse.vlm_requests_per_doc` | `ops.run_pipeline.parse.batch_vlm_requests_per_doc` |
| `ops.run_pipeline.staging.fetch_threads` | `ops.run_pipeline.staging.staging_fetch_threads` |
| `ops.run_pipeline.staging.max_docs` | `ops.run_pipeline.staging.staging_max_docs` |
| `ops.run_pipeline.staging.workers` | `ops.run_pipeline.staging.staging_workers` |
| `ops.run_pipeline.structure.bm25_threads` | `ops.run_pipeline.structure.batch_bm25_threads` |
| `ops.run_pipeline.structure.embed_batch_size` | `ops.run_pipeline.structure.batch_embed_batch_size` |
| `ops.run_pipeline.structure.embed_concurrency` | `ops.run_pipeline.structure.batch_embed_concurrency` |
| `ops.run_pipeline.structure.max_backlog` | `ops.run_pipeline.structure.structure_max_backlog` |
| `ops.run_pipeline.structure.workers` | `ops.run_pipeline.structure.structure_workers` |
| `ops.run_pipeline.vlm_lane.dedicated_workers` | `ops.run_pipeline.vlm_lane.vlm_lane_dedicated_workers` |
| `ops.run_pipeline.vlm_lane.max_concurrent_docs` | `ops.run_pipeline.vlm_lane.vlm_lane_max_concurrent_docs` |
| `ops.run_pipeline.vlm_lane.post_steps` | `ops.run_pipeline.vlm_lane.vlm_lane_post_steps` |
| `ops.run_pipeline.vlm_lane.shared_workers` | `ops.run_pipeline.vlm_lane.vlm_lane_shared_workers` |
| `ops.run_pipeline.vlm_lane.vlm_requests_per_doc` | `ops.run_pipeline.vlm_lane.vlm_lane_requests_per_doc` |
| `ops.run_pipeline.work_dir` | `ops.run_pipeline.run_pipeline_work_dir` |
| `ops.services.data_parsing.allowed_roots` | `ops.services.data_parsing.mcp_parse_allowed_roots` |
| `ops.services.data_parsing.max_file_mb` | `ops.services.data_parsing.mcp_parse_max_file_mb` |
| `ops.services.data_parsing.port` | `ops.services.data_parsing.data_parsing_port` |
| `required.edw.database` | `required.edw.edw_database` |
| `required.edw.host` | `required.edw.edw_host` |
| `required.edw.local_sqlite_file` | `required.edw.edw_local_sqlite_file` |
| `required.edw.edw_local_sqlite_file`(⑮ 3차) | `dev.local.local_edw_sqlite_file` |
| `required.edw.port` | `required.edw.edw_port` |
| `required.edw.read_password` | `required.edw.edw_read_password` |
| `required.edw.read_user` | `required.edw.edw_read_user` |
| `required.edw.write_password` | `required.edw.edw_write_password` |
| `required.edw.write_user` | `required.edw.edw_write_user` |
| `required.embed.api_key` | `required.models.embed_api_key` |
| `required.embed.base_url` | `required.models.embed_base_url` |
| `required.embed.model` | `required.models.embed_model` |
| `required.llm.api_key` | `required.models.llm_api_key` |
| `required.llm.base_url` | `required.models.llm_base_url` |
| `required.llm.model` | `required.models.llm_model` |
| `required.object_storage.access_key` | `required.object_storage.object_storage_access_key` |
| `required.object_storage.endpoint` | `required.object_storage.object_storage_endpoint` |
| `required.object_storage.secret_key` | `required.object_storage.object_storage_secret_key` |
| `required.pg.database` | `required.pg.pg_database` |
| `required.pg.db_schema` | `required.pg.pg_schema` |
| `required.pg.host` | `required.pg.pg_host` |
| `required.pg.password` | `required.pg.pg_password` |
| `required.pg.port` | `required.pg.pg_port` |
| `required.pg.user` | `required.pg.pg_user` |
| `required.publish.bucket` | `required.publish.publish_bucket` |
| `required.publish.prefix` | `required.publish.publish_prefix` |
| `required.tokens.mcp` | `required.tokens.mcp_token` |
| `required.vlm.api_key` | `required.models.vlm_api_key` |
| `required.vlm.base_url` | `required.models.vlm_base_url` |
| `required.vlm.model` | `required.models.vlm_model` |
| `search.edw_meta.catalog_dir` | `search.edw_meta.edw_meta_catalog_dir` |
| `search.edw_query.max_rows` | `search.edw_query.edw_query_max_rows` |
| `search.server.allowed_hosts` | `search.server.mcp_allowed_hosts` |
| `search.server.bind_host` | `search.server.mcp_bind_host` |
| `search.server.manifest_file` | `search.server.mcp_manifest_file` |
| `search.server.max_concurrent_tools` | `search.server.mcp_max_concurrent_tools` |
| `search.server.port` | `search.server.mcp_port` |
| `transform.represent.parallel_docs` | `transform.represent.represent_parallel_docs` |
| `transform.vlm.max_figures_per_doc` | `transform.vlm.vlm_max_figures_per_doc` |
| `transform.vlm.max_pages_per_doc` | `transform.vlm.vlm_max_pages_per_doc` |
| `tuning.common.connections.pg.connect_timeout_sec` | `tuning.common.connections.pg.pg_connect_timeout_sec` |
| `tuning.common.connections.pg.pool_max_connections` | `tuning.common.connections.pg.pg_pool_max_connections` |
| `tuning.common.models.embed.query_cache_max_rows` | `tuning.common.models.embed.embed_query_cache_max_rows` |
| `tuning.common.models.embed.timeout_sec` | `tuning.common.models.embed.embed_timeout_sec` |
| `tuning.common.models.llm.empty_retry_max_tokens` | `tuning.common.models.llm.llm_empty_retry_max_tokens` |
| `tuning.common.models.llm.timeout_sec` | `tuning.common.models.llm.llm_timeout_sec` |
| `tuning.common.models.transport.connect_timeout_sec` | `tuning.common.models.transport.model_connect_timeout_sec` |
| `tuning.common.models.transport.down_after_failures` | `tuning.common.models.transport.model_down_after_failures` |
| `tuning.common.models.transport.down_cooldown_sec` | `tuning.common.models.transport.model_down_cooldown_sec` |
| `tuning.common.models.vlm.retries` | `tuning.common.models.vlm.vlm_retries` |
| `tuning.extract.attach.max_count` | `tuning.extract.attach.attachment_max_count` |
| `tuning.extract.attach.max_depth` | `tuning.extract.attach.attachment_max_depth` |
| `tuning.extract.attach.max_mb` | `tuning.extract.attach.attachment_max_mb` |
| `tuning.extract.attach.timeout_sec` | `tuning.extract.attach.attachment_timeout_sec` |
| `tuning.extract.cache.max_gb` | `tuning.extract.cache.parse_cache_max_gb` |
| `tuning.extract.isolate_startup_sec` | `tuning.extract.engine_isolate_startup_sec` |
| `tuning.extract.source_columns.content_version` | `tuning.extract.source_columns.source_column_content_version` |
| `tuning.extract.source_columns.doc_id` | `tuning.extract.source_columns.source_column_doc_id` |
| `tuning.extract.source_columns.file_size` | `tuning.extract.source_columns.source_column_file_size` |
| `tuning.extract.source_columns.filename` | `tuning.extract.source_columns.source_column_filename` |
| `tuning.extract.source_columns.increment` | `tuning.extract.source_columns.source_column_increment` |
| `tuning.extract.source_columns.storage_key` | `tuning.extract.source_columns.source_column_storage_key` |
| `tuning.load.publish.upload_statuses` | `tuning.load.publish.publish_upload_statuses` |
| `tuning.ops.log.batch_size` | `tuning.ops.log.log_batch_size` |
| `tuning.ops.log.db_timeout_sec` | `tuning.ops.log.log_db_timeout_sec` |
| `tuning.ops.log.flush_sec` | `tuning.ops.log.log_flush_sec` |
| `tuning.ops.log.queue_size` | `tuning.ops.log.log_queue_size` |
| `tuning.ops.log.shutdown_sec` | `tuning.ops.log.log_shutdown_sec` |
| `tuning.ops.runtime.threads_per_process` | `tuning.ops.runtime.engine_threads_per_process` |
| `tuning.ops.services.data_parsing.engine_processes` | `tuning.ops.services.data_parsing.mcp_parse_engine_processes` |
| `tuning.ops.services.data_parsing.first_try_min_timeout_sec` | `tuning.ops.services.data_parsing.mcp_parse_first_try_min_timeout_sec` |
| `tuning.ops.services.data_parsing.job_timeout_sec` | `tuning.ops.services.data_parsing.mcp_parse_job_timeout_sec` |
| `tuning.ops.services.data_parsing.max_queued_jobs` | `tuning.ops.services.data_parsing.mcp_parse_max_queued_jobs` |
| `tuning.ops.services.data_parsing.text_engine_page_timeout_sec` | `tuning.ops.services.data_parsing.mcp_parse_text_engine_page_timeout_sec` |
| `tuning.search.audit.max_input_bytes` | `tuning.search.audit.audit_max_input_bytes` |
| `tuning.search.audit.max_output_bytes` | `tuning.search.audit.audit_max_output_bytes` |
| `tuning.search.audit.max_queue_bytes` | `tuning.search.audit.audit_max_queue_bytes` |
| `tuning.search.default_methods` | `tuning.search.search_default_methods` |
| `tuning.search.edw_meta.max_response_bytes` | `tuning.search.edw_meta.edw_meta_max_response_bytes` |
| `tuning.search.edw_query.max_response_bytes` | `tuning.search.edw_query.edw_query_max_response_bytes` |
| `tuning.search.edw_query.timeout_sec` | `tuning.search.edw_query.edw_query_timeout_sec` |
| `tuning.search.output.max_response_bytes` | `tuning.search.output.tool_max_response_bytes` |
| `tuning.search.server.max_queued_tools` | `tuning.search.server.mcp_max_queued_tools` |
| `tuning.search.server.reload_check_sec` | `tuning.search.server.mcp_reload_check_sec` |
| `tuning.search.server.tool_timeout_sec` | `tuning.search.server.mcp_tool_timeout_sec` |
| `tuning.search.weights.bm25` | `tuning.search.weights.bm25_weight` |
| `tuning.search.weights.bm25_table` | `tuning.search.weights.bm25_table_weight` |
| `tuning.search.weights.id` | `tuning.search.weights.id_match_weight` |
| `tuning.search.weights.vector` | `tuning.search.weights.vector_weight` |
| `tuning.transform.figures.max_ocr_per_doc` | `tuning.transform.figures.figure_max_ocr_per_doc` |
| `tuning.transform.figures.max_vector_pages` | `tuning.transform.figures.figure_max_vector_pages` |
| `tuning.transform.figures.min_side_px` | `tuning.transform.figures.figure_min_side_px` |
| `tuning.transform.figures.ocr_fallback_min_chars` | `tuning.transform.figures.figure_ocr_fallback_min_chars` |
| `tuning.transform.figures.ocr_threads` | `tuning.transform.figures.figure_ocr_threads` |
| `tuning.transform.figures.photo_max_ocr_chars` | `tuning.transform.figures.figure_photo_max_ocr_chars` |
| `tuning.transform.figures.photo_max_tokens` | `tuning.transform.figures.figure_photo_max_tokens` |
| `tuning.transform.figures.photo_min_area_ratio` | `tuning.transform.figures.figure_photo_min_area_ratio` |
| `tuning.transform.figures.text_image_min_ocr_chars` | `tuning.transform.figures.figure_text_image_min_ocr_chars` |
