# 0.1.0 배포 기록 — 사람이 할 일 · 부록 · 옛 설정 이관

11-02에 옮겼다(운영 서버가 0.1.0으로 돎 — 사용자). 0.2.0 배포 할 일은 [release-and-patch.md §8](../operations/release-and-patch.md#8-020-배포--사람이-할-일), 열린 확인 항목은 [refactor.md](../refactoring/refactor.md). 아래 글은 옮길 때 그대로 두었다(경로·링크·R§·C 번호는 그때 기준 — 옮긴 C 항목은 [refactor_c_items.md](refactor_c_items.md)).

## 1. 옛 refactor.md "최종 — 사람이 할 일"(0.1.0)

**결정(사용자 10-30) — PRD [pl-23](../prd/ops.md#pl-23)·[pl-25](../prd/load-schema.md#pl-25):** 버전 0.1.0에 모든 변경을 넣고 재처리는 한 번(첫 적재 = 전체 e2e — 새 스키마, 옛 스키마는 되돌리기용). 새벽 배치는 켜지 않는다.

S11(10-28)에 VS10 배포 준비 목록(`output/orca/VS10-verify.md` 끝 절)을 옮겨 와 사용자 결정(D-034)을 반영하고, 사용자 요청(10-28 "사람이 할 일도 refactor.md에 최종적으로")대로 이 절을 **사람 할 일의 정본**으로 묶었다(S11b — VS11 B-1·B-2·U-1·U-2·R-1~R-7 반영 · S11c — VS11b B-1 parse 작업 서비스 띄우기 ③-9·B-2 새벽 배치 스위치 ③-12·W-3·W-4 반영). 명령은 [docs/operations/release-and-patch.md](../operations/release-and-patch.md)(R§ — 그 문서 §5가 이 절을 가리킴). 항목마다 **할 일 · 누가 · 언제 · C**. 값·비밀은 쓰지 않는다. 이 절에는 할 일이 남은 것만 있다(①~④ 이번 배포 · ⑤ 다음 버전으로 미룬 것). "C" 열은 근거로 가리키는 항목이라, 결정만 된 C(C-43 등 — 상태는 아래 표 · 10-30·11-02에 옮긴 C는 [docs/history/refactor_c_items.md](refactor_c_items.md))도 배경·결정 내용을 보라는 뜻으로 들어 있다. 새 저장소에는 `output/`(보고서)과 옛 커밋이 가지 않으므로, 검토·되돌리기에 필요한 표는 맨 아래 **부록**(S11b)에 옮겼다.
- 누가: **사용자** · **서버 운영**(서버 운영 담당) · **DB 담당**(공유 PostgreSQL·회사 DB) · **EDW 담당**(운영 EDW 계정·데이터) · **사용자(grill-me 검토)**(검토 등급 A — Claude가 변경을 하나씩 설명하는 grill-me 세션에서 사용자가 검토·승인, C-07 · 옛 engine-qa·be-qa 자리) · **devops**(이미지 빌드·배포 번들) · **각 개발자**.

### ① 검토 등급 A — 사람 검토(🔒 Claude 검토로 갈음하지 않음)

| 할 일 | 누가 | 언제 | C |
|---|---|---|---|
| I6·I7·S2~S11 버전 전체 독립 검토 — code_fp 5개·핸드오프 핑거프린트·엔진 핑거프린트·DB 버전 테이블 변경 · I6·I7(임시 `adk`·`llm` 대체 구현 — CLAUDE.md 1절, 서버 배포 여부는 사용자 결정)도 포함(범위 C-07 상태 열 · 전후 표 CLAUDE.md §4·아래 부록 1·2) | 사용자(grill-me 검토) | 배포 전(빌드한 이미지로) | C-07 |
| 엔진 핑거프린트 27개·FINGERPRINT(`87588ce7c88d70ee` → `ffa201eed4aed21a`) 바뀜 수용 — 전 문서 재파싱을 받아들일지(엔진별 전후 = 부록 2 · 되돌리기 = 부록 3 파일 기준 — 옛 커밋은 옛 로컬 저장소에만) | 사용자(grill-me 검토) — 결정(사용자 10-29): 수용, 첫 적재 = 전체 e2e 한 번 → PRD [pl-23](../prd/ops.md#pl-23) | 배포 전 | C-52 |
| Alembic 버전 기록 테이블(`<스키마>.alembic_version`)을 공유 PG에 더하는 것·버전 승인·올리는 때 협의 · **결정(사용자 10-30) — PRD [pl-23](../prd/ops.md#pl-23): 새 스키마를 만들고 전체 e2e로 채움, 옛 스키마는 되돌리기용으로 남김(옛 스키마에 `stamp` 안 함)** | DB 담당 | 배포 전(협의) · 배포 때 새 스키마 `up`(③-7) | C-48 ③ |
| 회사 DB 연결이 SQLAlchemy로 바뀜 — 첫 연결 카탈로그 질의가 읽기 전용 계정에서 되는지 | DB 담당·EDW 담당·서버 운영 | 배포 전 확인 · 배포 때 한 번 실행 | C-49 ⑤ |
| 회사 DB `AI.ParsingMeta.pipeline_version` 값이 git 짧은 커밋 → 버전(`0.1.0` 꼴)으로 바뀜 — **결정(사용자 10-31 고침) — PRD [pl-25](../prd/load-schema.md#pl-25): 두 곳 모두 `pipeline_version`** — gold `doc` = 그 행을 만든 코드 판 · ParsingMeta = 그 문서를 gold에 올린 판 · 이 칸을 읽는 다른 서비스·보고가 있는지, 길이·형식 제약은 DB 담당 확인(`db_schema.md` 승인 때 함께) | DB 담당·EDW 담당·사용자 | 배포 전(협의) | C-62 (D-036) |
| **결정(사용자 10-30) — PRD [pl-12](../prd/load.md#pl-12): deleted 처리 길 없앰 — 코드 반영(10-30, B1: 서버는 SQLite·스탠드인 대체 없이 멈춤, `run_mode: prod` 필수)** · 새 판에서는 더 늘지 않음 — 서버 확인은 그대로 — 문서 레지스트리(서버가 SQLite 레지스트리로 동작하며 지금도 이전 문서를 deleted·숨김으로 만드는지) — 서버 `struct_backend`·`run_mode` · SQLite 레지스트리 파일 · `doc_registry` deleted 수·`doc_hidden` · 운영 EDW `status='deleted'` 수(ⓐ~ⓓ). 그랬으면 사람이 되돌림 | 서버 운영·DB 담당·EDW 담당·사용자 | **배포 전(지금 서버)** | C-54 |

### ② 배포 전

| 할 일 | 누가 | 언제 | C |
|---|---|---|---|
| **서버 settings.yaml에서 10-29에 지운 설정 칸 지우기** — 지운 칸은 `Section.REMOVED`에 올려 남아 있어도 경고 한 줄 뒤 무시(한 판 동안 — 시작은 됨), 그 밖 모르는 칸은 여전히 거부(`extra=forbid`) — 경고가 안 나오게 이번 판에 지운다. 지울 칸 목록은 env-guide §5 맨 위 줄(`PARSE_AGENT*`·`SEARCH_RERANK*`·`RERANK_*`·`MCP_DECOMPOSE`·`DECOMPOSE`·`SEARCH_GRAPH_CONCEPT_*`·`OV_*`·`STRUCTURE_TARGET`·`PADDLE_PYTHON`·`PHASE_REPORT_LEGACY` 등) · **질문 분해는 기본 켬이었다** — 서버 mcp-server 설정에 `common.models.llm`이 채워져 있고 `mcp.search.decompose`를 끄지 않았다면 긴·복합 질문의 근거 목록이 바뀐다(배포 전 서버 설정에서 확인) — `python -m pipeline.config --file <서버 settings.yaml>`로 확인 | 서버 운영 | 배포 전 | C-64 |
| **EDW 접속 다시 채우기(C-67)** — 서버 settings.yaml의 `common.connections.parsing_meta` 접속 칸·`pipeline.connections.rdb` 접속 칸·`mcp.edw_query` 접속 칸·`common.connections.edw`를 지우고 새 sample의 `common.connections.rdb`(host·database·`read`·`write`)를 채운다 — 검색 MCP는 시작 때 `write`를 자동으로 비움 · DBA와 읽기·쓰기 계정 권한 확인 | 서버 운영 · DB 담당 | 배포 전 | C-67 |
| **첫 전체 e2e 규모 — 사용자가 서버에서 나중에 정함(10-30).** 새벽 배치 마감은 없어짐(새벽 배치를 켜지 않음 — pl-23). 재파싱 시간·호출량 수치는 아직 없다 — 아래 "재파싱 범위"로 문서 수 × 엔진 27 × 평균 시간·VLM 호출량을 내어 규모를 정할 때 씀 | 사용자·서버 운영 | 첫 전체 e2e 전 | C-08 |
| 옛 `run_docs.py`에 평문으로 있던 운영 접속 키 교체 — 새 값은 서버 settings.yaml 항목에만 | 서버 운영(보안 담당) | 배포 전 | C-10 (D-034 ②) |
| 새 저장소로 이관 — HEAD 트리만(옛 이력 안 가져감 · HEAD 비밀 0 — VS10 A9) · `.claude/skills`는 git 밖이라 필요하면 각자 orca skill 설치 | 사용자·각 개발자 | 이관할 때 | C-10 · 옛 C-57(이력) |
| **지금 로컬 저장소(`refactor` 브랜치·태그 `pre-refactor` 이력 + git 밖 `output/orca/` 보고서)를 되돌리기·검토 자료로 보관** — 옛 `run_docs.py` 비밀이 이력에 있어 **절대 push·공유하지 않음**(원격 없음 · 사본은 암호화 저장소에만) · 부록 3(파일 기준 되돌리기)이 이 저장소의 옛 커밋에서 블록을 꺼냄 | 사용자(보관) — 지금 개발 PC 그 자리 | 이관 때부터 첫 배포 뒤까지 — **보관은 첫 배포가 끝나면 끝(사용자 10-30)** | C-52·C-10 · D-034 |
| 서버 자체 수정 기록 읽기 — `/srv/rag/reports/server-changes.md`(+ `server-changes/<ID>.diff`)와 서버 settings.yaml에서 상태 `서버에만`·`PC 보냄` 행마다 새 코드에 이미 들어 있는지(`PC 반영됨`) · ③-4 덮어쓴 뒤 다시 얹을 것인지 정함(전체 덮어쓰기는 서버에서 직접 고친 코드를 지움) | 서버 운영(PC 쪽 대조는 각 개발자) | 배포 전 | (R§4 · R§7 0단계 · R§3-2 원칙) |
| **서버에서 실제로 실행되는 `run_docs.py` 대조** — 저장소 버전은 `main()`이 파싱 스레드를 띄우지 않던 결함(pre-refactor부터)을 S12에 고쳤다. 서버 작업 폴더의 `run_docs.py`에서 `def lane_worker`가 `main()` 안(들여쓰기 4칸)인지, `server-changes.md`에 run_docs 수정 행이 있는지 보고 — 서버에 손으로 고친 정상 버전이 있으면 그 버전의 다른 수정을 새 버전에 합침(위 줄 규칙) | 서버 운영 | 배포 전 | C-59 |
| 첫 버전 태그·설명서 — `release/0.1.0` → 새 저장소 `main` 머지 커밋에 첫 버전 태그 `v0.1.0`(D-009 — annotated · 이미지 태그는 `v` 없이 `data-pipeline:0.1.0`·`mcp-server:0.1.0` = 저장소 루트 `VERSION`, D-036) · 이번 배포의 `RELEASE_NOTES.md`는 손으로 씀(시작점이 S6b 전 배치라 `make_patch.sh` 설명서 생성이 종료 3 — R§4) | devops·사용자 | 빌드 전 | (refactor_plan 6-1 "반입" · D-009 · R§4) |
| 서버 settings.yaml 이관과 꼭 적을 항목(아래 표 — `run_mode: prod`·EDW 계정·run_docs 항목 등) · `migrate --compare`가 "다름 0 · 옛에만 0 · 확인 필요 0" · 주인 UID 10001·640 | 서버 운영(EDW 계정은 EDW 담당) | 배포 전 준비 · 배포 때 5번 | C-09·C-34·C-43·C-45·C-47 |
| 폐쇄망 휠 — `deploy/docker/wheels/`에 linux/amd64·py3.12 휠(`SQLAlchemy`·`alembic`·`Mako`·`pydantic-settings`·`PyYAML` — 버전은 C-48 ①·C-16) · `assets/rapidocr/*.onnx`를 넣고 빌드(`ALLOW_NO_ASSETS=1` 금지) | devops | 빌드 전 | C-11·C-16·C-48 ① |
| DB 담당 협의 — 위 ①의 버전 기록 테이블 + 회사 DB `AI.ParsingMeta` DDL 전달(서버에 남은 옛 `struct` 스키마는 그대로 두거나 DB 담당자가 지움 — pl-08) | DB 담당·사용자 | 배포 전 | C-48·C-49·C-17 |
| 내부망 모델 — `*_ALLOW_EXTERNAL` 없음 · 모델 주소 모두 내부망(서버는 외부 거부) | 서버 운영 | 배포 전 | C-41 |
| 토큰 — parse 서비스 토큰 필수(코드 기본 토큰 삭제) · MCP 토큰 공백만 = 없음 · 옛 기본 토큰을 쓰던 곳은 교체 | 서버 운영 | 배포 전 | C-42·C-44 |
| 서버 쪽 확인 — `PATCH_CODE` 마운트(C-02) · 운영 문서 사본 자리(C-19) · 용어집·고객 명부 — **결정(사용자 10-30) — PRD [pl-25](../prd/load-schema.md#pl-25): 마스터 자료(용어집·고객 명부·계약·고객 마스터)는 CSV 파일로 git `resources/vocab/glossary/`에 두어 이미지에 함께 들어감 — 서버 폴더·마운트·마스터 Postgres 없음, `glossary_dir`는 이미지 경로** · 서버의 옛 `GLOSSARY_DIR` 폴더에 있던 CSV를 저장소로 옮김(C-21) · 출력 위치(C-01 — ②-1 "출력 위치" 항목) · `DOC_DIR` 없이 `DOC_SRC`에 기대던 도구(C-45 ④) · `migrate --compare`의 "모델 밖 — env 파일의 이름" 줄(C-45 ⑤) · 옛 새벽 unit이 실제로 실행됐는지 `systemctl status`(C-45 ⑥) | 서버 운영 | 배포 전 | C-01·C-02·C-19·C-21·C-45 ④⑤⑥ |
| 결정·검토 — podman 명령(C-04·C-36) · 오버레이 설정 파일 보안(C-46) | 사용자·서버 운영 | 배포 전 | C-04·C-36·C-46 |

#### ②-1 서버 settings.yaml에 꼭 적을 항목(`$SERVER_ENV_DIR/settings.yaml` — 주인 UID 10001·권한 640, C-09)

| 항목 | 값·이유 | C |
|---|---|---|
| `common.run_env` | dev·prd(없으면 앱·entrypoint·compose 거부 · `stage`는 없앰 — C-66) | C-34·C-09·C-66 |
| **`common.store.run_mode: prod`** | dev·prd 서버는 prod — EDW를 못 읽으면 종료 4(PRD [pl-12](../prd/load.md#pl-12) · 옛 이유였던 문서 레지스트리 SQLite 대체 길은 11-01에 없앰) | C-43·C-47 |
| `[서버 옛 값]` 항목 | `settings.sample.yaml`의 `[서버 옛 값: …]` 표시 그대로(`post: all`·`max_rows: 1000` 등) | C-45 ① |
| EDW 계정 | `common.connections.rdb`의 `read`·`write` 계정(+ 비밀번호) — EDW를 쓰면 필수(옛 `common.connections.edw`는 없앰 — C-67) | C-47 ④ · C-67 |
| 토큰 | `pipeline.service.parse_mcp.token` = `mcp.server.token` | C-42·C-44 |
| run_docs 항목 | 운영 접속·Object Storage·퍼블리시 버킷·PG 컨테이너·출력 루트 항목(없으면 항목 경로만 찍고 종료 2 — 목록은 C-45 ③) | C-45 ③ |
| 이미지 이름 | `pipeline.host.image`·`mcp.host.image`(옛 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`) | C-29 ⑤ |
| 출력 위치 | `common.host.output_root`(호스트 결과 폴더 — compose가 컨테이너 `/app/output`으로 붙이는 원본, 옛 `RAG_OUT`) · 앱 항목 `common.paths.output_root`는 비움(컨테이너 안 코드 기본 `/app/output` — 호스트 경로를 적지 않음) | C-01·C-29 ⑨ⓑ |
| 새벽 배치 | `pipeline.host.nightly.time`은 비운 채로(10-30 pl-32 — 옛 `nightly.enabled` 대신 시각 칸 하나, 비우면 없음) — **이번 배포에서 새벽 배치를 켜지 않음(사용자 10-30 — pl-23, 아래 ③-12)** · 옛 `modules`·`max_new`·`publish`는 11-01에 없앰(남으면 경고만 — C-72) | C-29 ⑥·C-72 |
| 그 밖 | `pipeline.host.gold_dir`만(앱 항목 `pipeline.paths.gold_dir`는 비움 — 컨테이너 안 `/data/gold`, S7e2 버전 migrate로 옮겼다면 지움 · C-47 ⑨) · `common.runtime.lib_env`(C-47 ③) | C-47 |

옮기기·대조·권한·옛 파일 이름 바꾸기 명령은 R§5-4(`migrate --compare`가 "다름 0 · 옛에만 0 · 확인 필요 0"이어야 함).

### ③ 배포 때(언제 = 배포 당일, 번호 순서 — 새 이미지·코드 폴더·`run_docs.py`·systemd를 같은 때 함께)

| # | 할 일 | 누가 | C · R§ |
|---|---|---|---|
| 1 | 타이머 끄기·옛 unit 백업 → 옛 `rag-nightly`·`data-retrieval-keepalive` disable | 서버 운영 담당 | C-29 ① |
| 2 | 옛 컨테이너 `data-parsing`·`data-structure`·`data-retrieval` 멈춤·삭제 | 서버 운영 담당 | C-29 ② |
| 3 | 새 이미지 2개(`data-pipeline`·`mcp-server`) sha256 확인 뒤 적재 | 서버 운영 담당 | C-29 ③ · R§5-2 |
| 4 | 코드 폴더 전체 덮어쓰기(먼저 `backup-<날짜시각>` 복사) — live에 `common`·`pipeline`·`mcp_server`·`resources`, 옛 `data_*`·`common_tools`·`agent_platform`·research 파일·중첩 사본·`resources/prompts/mcp/research_check/` 지움 → **덮어쓴 뒤 ②에서 고른 `server-changes.md` 행(서버에서 직접 고친 코드)을 다시 얹고 그 행 상태를 적음**(새 코드에 이미 있으면 `PC 반영됨`) · 다시 얹은 뒤 `find live/app/deploy/common -name '*.py'`를 저장소 목록과 대조 — `common/` 아래 분류 안 된 `.py`(편집기 백업 `*_old.py`·서버에서 더한 파일)가 있으면 `import common`이 모든 명령을 거부(C-23) | 서버 운영 담당 | 아래 "③-4 live에서 지울 것" · 옛 C-18·C-20·C-22~C-26·C-28(이력) · R§4·§3-2 |
| 5 | 설정 옮기기(위 ②·②-1) | 서버 운영 담당 | C-45·C-47 · R§5-4 |
| 6 | systemd unit 2개(`data-pipeline-nightly`·`mcp-server-keepalive`)를 새로 다시 복사·`daemon-reload`(호스트 python에 pydantic 없으면 `SETTINGS_IMAGE`) — **타이머 켜기는 12**(DB 버전·컨테이너 확인 뒤) | 서버 운영 담당 | C-29 ⑥·C-45 ⑦ |
| 7 | **DB(컨테이너 띄우기·selftest 전) — 결정(사용자 10-30) — PRD [pl-23](../prd/ops.md#pl-23): 새 gold 스키마를 옛 스키마 **옆에** 만들고 옛 스키마는 계속 서비스한다 — 새 스키마에 전체 e2e를 넣은 뒤 검색 MCP를 새 스키마로 바꾼다(사용자 10-30 grill 12~13차).** 옛 스키마에는 `stamp`·`up`을 하지 않는다 · settings.yaml의 PG 스키마 항목을 새 스키마로 적고(새 스키마 이름은 DB 담당자가 정함) data-pipeline 이미지로 `$DC run --rm load migrate up --target all`(검색 스키마 — struct 없음, pl-08 11-01) → `show-stack`(엔진 구성 파일이 읽히는지) → 마지막 `check --target all`(차이 없음) · 색인 스키마는 `--schema <PG_SCHEMA>_<index_id>`마다 새로 · 첫 적재는 전체 e2e 한 번(규모는 사용자가 정함 — C-08) · 그날 끝낼 수 없으면 C-29 "되돌리기"(옛 unit·`backup-<날짜시각>` 코드 폴더·옛 이미지·옛 스키마로 옛 compose) · 명령 꼴은 R§5-5 | 서버 운영 담당·DB 담당 | C-48 ②③ · R§5-5 |
| 8 | `check-modules` + `selftest_gate.sh` — 기대: data-pipeline 알려진 FAIL `test_publish_guard` **1개만**, mcp-server FAIL 0 | 서버 운영 담당 | C-54 · R§3-3 |
| 9 | 새 compose로 `mcp-server`·`data-pipeline-parse`·`-structure` 띄움 — 파싱 컨테이너가 시작하는지(11-01부터 파싱은 PG 없이 시작 — pl-08) → **parse 작업 서비스를 손으로 띄움:** `docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service`(`-e` 없이 — 토큰은 settings.yaml `pipeline.service.parse_mcp.token` = `mcp.server.token`, 없으면 시작 거부) · compose·entrypoint·keepalive 어느 것도 이 서비스를 띄우지 않음(리팩토링 전부터 손으로) — 안 띄우면 MCP `parse_document`가 오류 · `docker exec` 프로세스라 `data-pipeline-parse`가 다시 시작·다시 만들어질 때마다(호스트 재부팅·`restart: unless-stopped` 재시작·compose 다시 올림 포함) 다시 띄워야 함 | 서버 운영 담당 | C-29 ⑧·C-42·C-44·C-47 ⑥ |
| 10 | `run_docs.py`를 새 버전으로 같은 때 교체 — **실행 자리는 `<운영자 작업 폴더>/run_docs.py`**(live 안 사본 `live/deploy/host/scripts/run_docs.py`가 아님 — live에서 실행하면 진행 기록이 코드 폴더에 생겨 다음 덮어쓰기 때 지워짐, C-29 ⑨ⓐ) · 결과 폴더는 settings.yaml `common.host.output_root`(옛 `<작업 폴더>/test_space/rfp_all_output` — 컨테이너 `/app/output` 원본과 같은 폴더인지 확인, C-29 ⑨ⓑ·C-45 ③) · 작업 폴더를 옮기면 `pipeline.host.run_docs_dir` | 서버 운영 담당 | C-29 ⑨·C-45 ③·C-51 |
| 11 | 확인: C-29 ⑩~⑫ · `journalctl` 실행 줄(C-03) · 컨테이너가 설정 파일을 읽는지(C-09) · podman에서 `settings_env --image`(C-36) · `tool rdb_discover`·`query_edw` 한 번(C-49 ⑤) · 실행 보드 `run_board`(R§7 3단계) · MCP를 부르는 쪽에 이름 바뀜 알림(C-29 ⑪) · 운영자에게 새 이름·바뀐 명령 알림(C-29 ⑫ — 옛 `common_tools…`·`data_etl…`·`data_retrieval…` 모듈 명령과 `tool stack_matrix`·`tool model_matrix`·`tool assets`는 없어짐 — 옛 C-22·C-23·C-26·C-28, 이력) · 개발 서버에서 옛 `answer_gen_test.py`를 쓰던 사람에게 새 명령(C-55) · 운영자에게 **env로 덮던 습관은 효과 없음** 알림(`PIPE_PROCS=2 docker compose run …`·`docker exec -e …` 꼴 — 시작 때 이름만 경고, 바꿀 값은 settings.yaml을 직접 고치고 상주 컨테이너는 다시 띄움, C-47 ⑥) · MCP `parse_document` 한 번(9의 parse 작업 서비스 — C-29 ⑧) | 서버 운영 담당 | C-03·C-09·C-29·C-36·C-47 ⑥·C-49·C-55 |
| 12 | **타이머 켜기(11 확인 뒤):** `sudo systemctl enable --now mcp-server-keepalive.timer` · 켜지 않으면 keepalive가 조용히 실행되지 않음 · **새벽 배치는 켜지 않는다(사용자 10-30 — PRD pl-23):** `data-pipeline-nightly.timer`는 enable하지 않고 settings.yaml `pipeline.host.nightly.time`은 비운 채로(옛 `nightly.enabled`는 지움 — 남아 있으면 경고만) — 나중에 사람이 시각을 적고 타이머를 enable | 서버 운영 담당 | C-29 ⑥ · R§5-4 |

**③-4 live에서 지울 것**(옮긴 C 항목의 목록 그대로 — 10-30, 근거는 [이력](refactor_c_items.md)):
- C-18: 중첩 사본 `data_retrieval/data_retrieval/`(53개 — `$PATCH_CODE/app/deploy/data_retrieval/`)
- C-20: 옛 자리 `common_tools/prompts/` 중 `triple_extract` 밖·`common_tools/{pipeline_stack.json,glossary,report_templates}`·`common_tools/runtime/sources.json`·`data_etl/agent/`·`data_retrieval/prompts/`·`data_retrieval/agg_vocab.json`·`data_retrieval/tools/qtype_labels.json` — live에 `resources/`를 함께 풀었는지 확인한 뒤 compose를 올림
- C-22: 옛 자리 `common_tools/{contract,model,runtime,store}/`·`common_tools/{meaning,terms,text}.py`·`common_tools/cli/{check_modules,ping_models,os_put}.py`
- C-23: 옛 `data_etl/`과 옛 자리 도구 파일(`common_tools/cli/` 12개·`common_tools/evaluation/` 4개 + 빈 `evaluation/__init__.py`)
- C-24: `data_retrieval/research.py`·`common_tools/cli/eval_research.py`·프롬프트 `resources/prompts/mcp/{research_decompose,research_rewrite}/`(7개)
- C-25 ③: `resources/prompts/mcp/research_check/`
- C-26: 옛 `data_retrieval/`·`common_tools/cli/qa_report.py`·`common_tools/evaluation/mcp_eval.py`
- C-28: live `$PATCH_CODE/app/deploy/common_tools/` 전체(옛 live의 `options.conf`를 고쳐 쓰고 있었다면 그 값은 settings.yaml로 — `options.conf`는 S7e2에 삭제, C-39)

### 참고 — 재파싱 범위(② C-08 산정 입력 — 수치는 아직 없음)
- **엔진 핑거프린트 27개 모두 바뀜** → 모든 문서가 모든 엔진으로 P0부터 다시(가장 비쌈 — C-52).
- **FINGERPRINT `87588ce7c88d70ee` → `ffa201eed4aed21a`** → structure·load가 옛 끝 표시를 거부(종료 3 — parse부터, C-52 ⓑ).
- **code_fp 5개 모두 바뀜**(값 CLAUDE.md §4 "지금 값") → 레이어 캐시 전부 무효 · AD41 색인 한 번 다시 지음(C-50 ②).
- 프롬프트 패키지 핑거프린트(25 — S11에 `research_check` 삭제)는 LLM·VLM 캐시 키에 안 들어가 그 때문에 다시 계산되는 캐시는 없음(C-08 ①).
- → 문서 수 × 엔진 27 × 평균 시간과 VLM 호출량(서버 내부 모델)을 산정해 첫 전체 e2e 규모를 정할 때 쓴다(사용자가 서버에서 — 10-30, 새벽 배치 마감은 없어짐). **지금 저장소·서버 어디에도 이 수치가 없다.**

### ④ 배포 후 확인(첫 실행)

| 할 일 | 누가 | 언제 | C |
|---|---|---|---|
| 첫 전체 e2e·run_docs 첫 실행의 실제 재파싱 시간·호출량 기록(② 산정과 비교 — 새벽 배치는 켜지 않음) | 서버 운영 | 첫 실행 뒤 | C-08 |
| run_docs 첫 실행 뒤 문서별 `_rep`·`[envcheck] gate=` 줄(`--set` 값이 효과 있는지) | 서버 운영 | 첫 run_docs 뒤 | C-51 |
| run_docs 첫 실행이 문서를 실제로 파싱하는지 — `progress.log`에 문서별 `doc#<seq> 파싱 OK`·`구조화+적재 OK` 줄과 마지막 `=== 문서별 flow 끝: N건` 줄(S12 결함 고침 — 고치기 전 버전은 `=== 문서별 flow 시작` 줄만 찍고 끝남) | 서버 운영 | 첫 run_docs 뒤 | C-59 |
| 오버레이 설정 파일 `/tmp/settings-*.yaml`이 프로세스가 끝날 때 지워지는지(10-30 바뀜 — PRD [pl-27](../prd/ops.md#pl-27) · 옛 글: 상주 컨테이너에 쌓여 정리 절차가 필요했음) | 서버 운영 | 첫 run_docs 뒤 | C-46·C-51 |
| RDB 오류 로그 꼴이 `sqlalchemy.exc.*`로 바뀜(원천 목록·`rdb_discover`·`gen_roster`) — 로그 문구로 오류를 찾는 절차·grep이 있으면 새 꼴로 고침 | 서버 운영 | 첫 RDB 오류 확인 때 | C-49 ⑦ |
| 질의 임베딩 캐시 파일·크기(mcp-server 안 `/tmp/mcp_query_cache.sqlite`) | 서버 운영 | 검색 몇 번 뒤 | C-27 |
| systemd 실행 줄 펼침(`journalctl`) · 컨테이너가 설정 파일을 읽는지 · podman `settings_env --image` | 서버 운영 | 배포 당일 끝 | C-03·C-09·C-36 |
| 버전 표기가 `unknown`이 아닌지 — run_docs 로그의 버전·gold `doc.pipeline_version`(실행 보드 `run_board`는 11-01에 지움)(10-31 고침 — gold `doc`과 ParsingMeta 두 곳 모두, PRD pl-25 · C-62). 버전의 출처는 `VERSION` 하나다(사용자 10-30 grill 12~13차, D-036): `common.pipeline_version()`은 이미지의 `/app/deploy/VERSION` 또는 오버레이 패치의 `common/PATCH_VERSION`(둘 중 높은 것)을 읽고, gold `doc.pipeline_version`은 이 값으로 채운다. env `PIPELINE_VERSION`에만 기대면 안 된다(그 env는 둘 다 없을 때의 마지막 대체 — settings.yaml `common.runtime.lib_env`로 주면 entrypoint로 띄운 프로세스만 받고 `docker exec`로 도는 run_docs publish·parse 작업 서비스는 못 받음). `unknown`이면 기록하고 사용자에게 알림(C-62) | 서버 운영 | 첫 publish 뒤 | C-62 · 옛 C-22(이력) |
| 전환 확인 뒤에만 옛 이미지 정리 `prune_old.sh --apply`(이 뒤로 되돌리기 불가) | 서버 운영·사용자 | 위가 모두 끝난 뒤 | C-29 ⑬ |
| `deploy/docker/IMAGE_BASE`를 이 버전의 커밋·태그로 고쳐 커밋(한 줄 `<커밋 7자> 0.1.0` — 지금 값은 upstream 10-16 버전 — R§5 · D-036) · `/srv/rag/reports/versions.md` 버전 기록 한 줄 · 버전 태그 설명에 배포 기록(서버·날짜·배포 방법·담당자 — D-009) | devops·서버 운영 | 배포 확인 뒤 | (R§5·§7 · D-009) |

### ⑤ 다음 버전으로 미룬 것(이번 버전에서 안 함 — 기록)

| 할 일 | 누가 | 언제 | C |
|---|---|---|---|
| **0.1.0에 넣기로 함(사용자 10-30 — 핑거프린트가 어차피 바뀌는 판 · PRD [pl-23](../prd/ops.md#pl-23)·[pl-25](../prd/load-schema.md#pl-25)):** 코드 안 옛 `--selftest` 안내 글(42파일 — 아래 줄) · 미룬 설정 삭제 [pl-21](../prd/ops-settings.md#pl-21) · 안 쓰는 `fields_table` 삭제 [e2-17](../prd/test.md#e2-17) | 사용자·각 개발자 | 0.1.0 빌드 전 | 끝남 10-30(`feature/fp-batch` — 옛 `--selftest` 글·pl-21·pl-30·`fields_table` 등) |
| 문서 레지스트리 설계 — **결정(사용자 10-30) — PRD [pl-12](../prd/load.md#pl-12):** upsert 번역 고침 · deleted 처리 길 없앰 · 방어선은 EDW `AI.ParsingMeta`로 | 사용자·engine·DB 담당 | pl-25 뒤 | C-54 |
| compose `index_a`·`index_b` 끝까지 실행하면 실패 — 결정(사용자 10-30): 예시를 지움 → PRD [pl-19](../prd/load.md#pl-19) | engine | pl-19 | PRD pl-19 (옛 C-32 — [이력](refactor_c_items.md)) |
| **내부망 코드 관리 방식 정하기(P-08)** — A 내부망 git 저장소 / B 배포 번들 + 기록 문서(refactor_plan 5-6). 이번 배포는 지금 방식(B — 전체 덮어쓰기 + `server-changes.md`·`versions.md`)으로 함 — **이번 배포부터 A로 하려면 ② 배포 전에 정함** · **결정(사용자 10-30): B 유지 — 배포 번들 + 기록 문서. 닫음** | 사용자 | 닫음 10-30 | (refactor_plan P-08 · D-009 · D-034) |

## 2. 옛 refactor.md 부록 1~5

새 저장소에는 HEAD 트리만 가고(D-034) `output/`은 git 밖이라, 검토(C-52 — 사용자 grill-me 검토)·되돌리기에 쓰던 `output/orca/S2-impl.md`·`S9-impl.md`·`S9b-impl.md`의 표가 새 저장소에 없다. 그 표를 그대로 옮겼다(값 대조 — `output/orca/S11b-impl.md`). 커밋 해시는 모두 **옛 로컬 저장소**(최종 ② — 보관, push 안 함)의 것이다. 단계별 핑거프린트 기록은 CLAUDE.md §4.

### 부록 1. FINGERPRINT·code_fp 5개(기준선 → HEAD)

| 시점(옛 로컬 저장소 커밋) | FINGERPRINT | a | p0 | p1 | r | s |
|---|---|---|---|---|---|---|
| 기준선 — 태그 `pre-refactor` | `87588ce7c88d70ee` | `6bfce35c55ab` | `edbc43ff04e3` | `fbecc91af8b5` | `a9981de5dd6c` | `83763139d1ad` |
| S8b — S9 전(`f617f8c`) | `87588ce7c88d70ee` | `e3b0c44298fc` | `77e98f1656f0` | `f286b8232945` | `5fbd6b88962d` | `762abcd37fef` |
| S9 핸드오프 커밋 뒤(`ab5c3a9`) | `ffa201eed4aed21a` | `e3b0c44298fc` | `57cc6d1d1d69` | `d06c76a72cb1` | `0a00bb554ba8` | `64d262310c03` |
| S9b~S11c(`d65e1cd`) | `ffa201eed4aed21a` | `e3b0c44298fc` | `57cc6d1d1d69` | `9bbf62206d01` | `0a00bb554ba8` | `593985e1c9e9` |
| 10-29 PC 설정 파일을 저장소 루트 `settings.yaml`로(공용 의존 `settings.py` 경로 한 줄) | `ffa201eed4aed21a` | `e3b0c44298fc` | `3cda08a5a4ba` | `63e31f865885` | `f2e2f8788bc5` | `059e49f7f6e9` |
| 10-29 `rag_qa`를 `valid_env/answer_test/`로 되돌림 — 공용 의존 `paths.py` | `ffa201eed4aed21a` | `e3b0c44298fc` | `5f8d5eae9bd6` | `4a77e7ca8e4c` | `befacd4ca209` | `a0b41701ed8e` |
| 10-29 S12 저장소 전체 `ruff format`·`ruff check`·mypy 정리 — 레이어·공용 파일 글자가 바뀜, 동작 같음 · 엔진 27·프롬프트 25·FINGERPRINT 그대로) | `ffa201eed4aed21a` | `e3b0c44298fc` | `ef155dca1c26` | `16088cf465dd` | `c2e72c27826b` | `15de04cd2d0b` |
| 10-29 S12 `/simplify` — 공용 `common/core/console.py`(`utf8_stdout`)·안 쓰는 상수·noqa 정리, 동작 같음) | `ffa201eed4aed21a` | `e3b0c44298fc` | `bd17a3ce0b81` | `99ba3cabee79` | `acba3674ad06` | `4fa6a1943a0d` |
| 10-29 `feature/settings-cleanup` — 안 쓰는 설정 칸·파싱 판단 에이전트·재순위·질문 분해·검색 방식 graph/concept/image/openviking·OpenViking 삭제 — s는 `settings.py`·`services.py`·`build_bundle.py`, 엔진 27 그대로 · `feature/test-parallel`(합성 문서 잠금 삭제·병렬 시험) 병합 포함 | `ffa201eed4aed21a` | `e3b0c44298fc` | `93ec91af2426` | `95884df63474` | `5942c410d895` | `932af9fc8548` |
| develop `e8e062e`(10-30) | `ffa201eed4aed21a` | `e3b0c44298fc` | `5079ca066605` | `b9449353d848` | `f42d47226663` | `cc1ab18b7634` |
| 0.1.0 지문 배치(#27 `feature/fp-batch` — 10-30, 핸드오프 파일 포함) | `abe9b7b0799ceaae` | `e3b0c44298fc` | `840199fcacb6` | `08cd37047cbd` | `b706f28ce48e` | `eb0597ed7f7b` |
| `feature/drop-ocrvlm`(#30 — 10-30, pl-31 ocr_vlm 지움) | `abe9b7b0799ceaae` | `e3b0c44298fc` | `2a828b0470c1` | `deb6efc4a5f0` | `0d4fcc7a4cbc` | `bd154d04467a` |
| **HEAD — 지금 값**(`feature/ocrvlm-leftovers` — 10-30, pl-31 남은 정리: fuse `ocr-vlm` 계열) | `abe9b7b0799ceaae` | `e3b0c44298fc` | `2a828b0470c1` | `9ee173300a82` | `0d4fcc7a4cbc` | `bd154d04467a` |
| `d65e1cd`에 부록 3 ③(핸드오프 파일 3개)만 넣은 트리(code_fp는 그 트리 기준 — 지금 HEAD에서 하면 p1·r·s가 다르고 FINGERPRINT는 같음) | `87588ce7c88d70ee` | `e3b0c44298fc` | `57cc6d1d1d69` | `5f63791e5d23` | `60bf07f7948c` | `8438496dc10d` |

- code_fp는 되돌려도 옛 값으로 돌아가지 않는다(레이어 파일·공용 의존이 S2~S9에 많이 바뀜) — 레이어 캐시는 어느 쪽이든 다시 계산된다. 되돌리기의 뜻은 엔진 핑거프린트(P0 파싱 재사용)·FINGERPRINT(핸드오프 버전 확인)를 옛 값으로 되돌리는 것이다.

### 부록 2. 엔진 핑거프린트 27개(엔진별)

- 10-30 pl-31(`feature/drop-ocrvlm`, 0.1.0): `ocr_vlm` 엔진 지움(27 → 26 — 아래 표의 `ocr_vlm` 줄은 기록) · `qwen_vlm` `52ca47bc4c6e` → `7381bf2b79d2` · 나머지 25개 그대로. 이어 `feature/ocrvlm-leftovers`(qwen_vlm 파서의 안 쓰는 인자 지움): `qwen_vlm` `7381bf2b79d2` → `06f937fcc39e`, 나머지 25개 그대로.
- 10-30 pl-31 남은 일(`feature/pl31-engines`, 0.1.0, 등급 A): 엔진 8개 지움 — `docling`·`docling_ocr`·`docling_vlm`(`ce98b1e26c00`) · `unstructured`·`unstructured_auto`·`unstructured_ocr`(`92c1debb0683`) · `rapidocr`(1.x) · `kreuzberg_ocr` (26 → 18 — 아래 표의 그 줄은 기록) · 바뀜: `kreuzberg` `4220f1fbd3bb` → `7e7c9ac44287`, `rapidocr_ko` `926d70c2f65c` → `990ebae04429`(같은 parser.py에서 지운 엔진 몫이 빠짐) · 나머지 16개 그대로 · 등록부 `engines/registry.py` sha `5f390232f293` → `a3d948df71e0`(CORE에서 docling·unstructured_auto 빠짐, 도구 API TOOL_SPECS·call_tool 지움 — 엔진 키에는 안 들어감, p0만).

| 엔진 | 기준선 = S9 전(S8b) | S9 엔진 커밋 뒤(`0c23f06`) | S9b 엔진 커밋 뒤(`64af4a8`) = HEAD |
|---|---|---|---|
| anydoc | `167ffe64e162` | `dd40ada30826` | `d2d12c9bb2d1` |
| calamine | `bf14765aaecf` | `084e31dd0b8c` | `0a6e52284603` |
| docling | `59b83c154267` | `b63475149d4f` | `ce98b1e26c00` |
| docling_ocr | `59b83c154267` | `b63475149d4f` | `ce98b1e26c00` |
| docling_vlm | `59b83c154267` | `b63475149d4f` | `ce98b1e26c00` |
| docx2python | `6a3266428890` | `098f000877ef` | `649c41782da6` |
| html_stdlib | `73200c533de1` | `d395b61d8c25` | `cf6b1856feb1` |
| hwpx | `f55aeb8b4b49` | `63f30ba76750` | `d14a807dbb49` |
| kreuzberg | `f06af2382557` | `35b35bcaf8fb` | `4220f1fbd3bb` |
| kreuzberg_ocr | `f06af2382557` | `35b35bcaf8fb` | `4220f1fbd3bb` |
| markitdown | `d601b8ae7dd1` | `094c1c220604` | `e667b6e36825` |
| mhtml | `73200c533de1` | `d395b61d8c25` | `cf6b1856feb1` |
| msg_extract | `73200c533de1` | `d395b61d8c25` | `cf6b1856feb1` |
| ocr_vlm | `a7b0deaf74c3` | `ff5fdf23139b` | `52ca47bc4c6e` |
| office | `10c9c1c26bb5` | `6714532a1163` | `e651655dd678` |
| pdfplumber | `1fa82f3b675f` | `88f844478681` | `85291a9caa6f` |
| plaintext | `07c429a7c114` | `ba0856cfce1d` | `03ed4fd20ec3` |
| pptx | `fe112faafb63` | `b89c939484fd` | `189c5ea15dc0` |
| pymupdf | `3c54f068426d` | `e71261356830` | `b766afda6fad` |
| pymupdf4llm | `5ec8ad50685e` | `37367b4fd271` | `ef61e3f37751` |
| pypdf | `7190a4d62667` | `df7c661a3020` | `290c1ef26cc9` |
| qwen_vlm | `a7b0deaf74c3` | `ff5fdf23139b` | `52ca47bc4c6e` |
| rapidocr | `df5f2cd8d645` | `f298e200c424` | `926d70c2f65c` |
| rapidocr_ko | `df5f2cd8d645` | `f298e200c424` | `926d70c2f65c` |
| unstructured | `d25cf2e10b36` | `2c597190120f` | `92c1debb0683` |
| unstructured_auto | `d25cf2e10b36` | `2c597190120f` | `92c1debb0683` |
| unstructured_ocr | `d25cf2e10b36` | `2c597190120f` | `92c1debb0683` |

- 확인: 기준선 열 = `pre-refactor` 측정(VS10) = S9 보고서 "전" 열 · 가운데 열 = S9 "뒤" = S9b "전" · 오른쪽 = S9b "뒤" = HEAD 측정(S11b). 엔진 하나를 다시 재려면 `PYTHONPATH=$PWD .venv/bin/python -c "from pipeline.extract import run_all as R; from pipeline.extract.engines import registry; print({e: R.engine_code_fp(e) for e in sorted(registry.engines())})"`.

### 부록 3. 파일 기준 되돌리기(옛 핑거프린트로)

S9·S9b는 엔진·핸드오프 파일 안 자기 점검 블록을 `tests/`로 옮기며 **블록만 지웠다**(남은 줄은 바이트 그대로 — 아래 10개 파일 모두 그 커밋 뒤로 HEAD까지 안 바뀜). 되돌리기 = 지운 블록을 같은 자리에 다시 넣기. 옮긴 테스트(`tests/…`)는 그대로 둔다(같은 몸통이 두 곳 — 둘 다 통과, check_modules 통과 — S11b 확인).

- **꺼내는 법(옛 로컬 저장소에서):** 파일이 아래 "지금 블롭"과 같으면 통째로 `git -C <옛 로컬 저장소> show <커밋>^:<파일> > <새 저장소>/<파일>` → `git hash-object <파일>`이 "옛 블롭"과 같은지 확인. 새 저장소에서 그 파일을 그 뒤에 고쳤으면 블록만: `git -C <옛 로컬 저장소> diff <커밋> <커밋>^ -- <파일> | git apply`(새 저장소 루트에서 — 블록을 넣는 패치, 문맥이 맞아야 함). zsh에서 `EXTENDED_GLOB`이 켜져 있으면 `^`가 글롭으로 읽히므로 `'<커밋>^:<파일>'`·`'<커밋>^'`처럼 따옴표로 감싼다(bash는 그대로).
- **차례와 나와야 할 값:** ① S9b 5개 → 엔진 27 = 부록 2 가운데 열 ② 이어서 S9 2개 → 엔진 27 = 부록 2 기준선 열(①만 하고 ②를 안 하면 가운데 열에서 멈춤 — `_common/*`가 모든 엔진에 들어가므로 둘 다 해야 기준선) ③ 핸드오프 3개 → FINGERPRINT `87588ce7c88d70ee`(엔진과 무관 — 따로 해도 됨). ③ 뒤 code_fp는 부록 1 마지막 줄. 확인 명령은 CLAUDE.md §4 "지문 확인" 한 줄 + 부록 2의 엔진 한 줄.
- **이미지·배포:** 엔진·핸드오프 파일이 바뀌므로 새 이미지 버전(오버레이 패치로 넣어도 핑거프린트는 파일 바이트 기준). 🔒 검토 등급 A.

| # | 파일 | 지운 블록(첫 줄) | 넣을 자리(지금 파일) | 줄 수 | 옛 로컬 커밋 | 지금 블롭 | 옛 블롭(`<커밋>^`) |
|---|---|---|---|---|---|---|---|
| ① | `pipeline/extract/engines/_common/fields.py` | `if __name__ == "__main__":   # 자기점검` | 파일 끝(136행 `return out` 뒤) | 27 | `64af4a8` | `6058baf90a54` | `fdd1e8ba92a8` |
| ① | `pipeline/extract/engines/hwpx/parser.py` | `if __name__ == "__main__":   # 자기점검: 섹션 본문 + …` | `ENGINES =` 줄 앞 빈 줄 사이(39행 뒤) | 24 | `64af4a8` | `470ca697a93f` | `be9be4f6a650` |
| ① | `pipeline/extract/engines/mhtml/parser.py` | `if __name__ == "__main__":   # 자기점검: HTML 표 + …` | `ENGINES =` 줄 앞(155행 뒤) | 34 | `64af4a8` | `2054df724c63` | `dd6b08f25d80` |
| ① | `pipeline/extract/engines/plaintext/parser.py` | `if __name__ == "__main__":   # 자기점검: CP949·탭 표` | `ENGINES =` 줄 앞(40행 뒤) | 10 | `64af4a8` | `383741514eba` | `bc2b0c3faefb` |
| ① | `pipeline/extract/engines/rapidocr/parser.py` | `if __name__ == "__main__":   # 자기점검: 긴 변 상한 …` | `ENGINES =` 줄 앞(139행 뒤) | 27 | `64af4a8` | `07da31a266f0` | `653128ff3697` |
| ② | `pipeline/extract/engines/_common/contract.py` | `def selftest():`(AD24② 표 나눔 등) | 파일 끝(409행 뒤) | 96 | `0c23f06` | `1241de9b02af` | `472c8d3b4f1e` |
| ② | `pipeline/extract/engines/office_stdlib/parser.py` | `if __name__ == "__main__":   # 자기점검: 숨김 시트 …` | `ENGINES =` 줄 앞(258행 뒤) | 73 | `0c23f06` | `980f77defbad` | `4fc24d6185d8` |
| ③ | `common/core/text.py` | `if __name__ == "__main__":   # 자기점검: 첨자 토큰(T1) …` | 파일 끝(159행 뒤) | 86 | `ab5c3a9` | `8ef032a4403c` | `25a563e4e0a5` |
| ③ | `common/core/terms.py` | `def selftest():` | 파일 끝(493행 뒤) | 228 | `ab5c3a9` | `35502eb43cf2` | `aee1954a0e25` |
| ③ | `common/core/contract.py` | `def selftest():`(29줄) + `__main__` 안 `if "--selftest" in sys.argv:` 3줄 | 200행 뒤(`if __name__` 앞) · 202행 `sys.stdout.reconfigure` 줄 뒤 | 32 | `ab5c3a9` | `ccf985648d94` | `f7c28ebdf3de` |

### 부록 4. 옛 → 새 테스트 이름(S9 · S9b)

옛 `python -m <모듈> [--selftest]`·인자 없는 `__main__` 자기 점검 → 새 테스트 파일(S9 — 옛 PC selftest 82개 + 목록 밖 자기 점검 · 결과 열은 뺌, 모두 옛과 같은 PASS/FAIL·알려진 FAIL은 CLAUDE.md 6절). "옛 인자" 없음 = 인자 없는 `__main__`.

| 옛 모듈(옛 사례) | 옛 인자 | 새 테스트 파일 |
|---|---|---|
| `common.core.contract` | 없음 | `tests/general/common/test_core_contract.py` |
| `common.core.docmeta` | 없음 | `tests/general/common/test_docmeta.py` |
| `common.core.fingerprint` | 없음 | `tests/server/common/test_fingerprint.py` |
| `common.core.meaning` | 없음 | `tests/general/common/test_core_meaning.py` |
| `common.core.runlog` | 없음 | `tests/general/common/test_core_runlog.py` |
| `common.store.edwdb` | 없음 | `tests/general/common/test_edwdb.py` |
| `common.store.pg` | 없음 | `tests/general/common/test_pg.py` |
| `common.store.structdb` | 없음 | `tests/general/common/test_structdb.py` |
| `deploy.release.assets` | 없음 | `tests/general/deploy/test_assets.py` |
| `mcp_server.cli.registry_cli` | 없음 | `tests/general/mcp/test_registry_cli.py` |
| `mcp_server.routers.dispatch` | 없음 | `tests/server/mcp/test_dispatch.py` |
| `mcp_server.services.edw_meta` | 없음 | `tests/general/mcp/test_edw_meta.py` |
| `mcp_server.services.edw_query` | 없음 | `tests/general/mcp/test_edw_query.py` |
| `mcp_server.services.search.aggregate` | 없음 | `tests/general/mcp/test_aggregate.py` |
| `mcp_server.services.search.decompose` | 없음 | `tests/general/mcp/test_decompose.py` |
| `mcp_server.services.search.internal_docs` | 없음 | `tests/server/mcp/test_internal_docs.py` |
| `mcp_server.services.search.rerank` | 없음 | `tests/general/mcp/test_rerank.py` |
| `mcp_server.services.search.search_svc` | 없음 | `tests/server/mcp/test_search_svc.py` |
| `mcp_server.services.search.server_state` | 없음 | `tests/server/mcp/test_server_state.py` |
| `mcp_server.services.search.shaping` | 없음 | `tests/server/mcp/test_shaping.py` |
| `mcp_server.services.search.supersede` | 없음 | `tests/general/mcp/test_supersede.py` |
| `pipeline.eval.chart_values_score` | 없음 | `tests/general/pipeline/test_chart_score.py` |
| `pipeline.eval.diagram_edges_score` | 없음 | `tests/general/pipeline/test_diagram_score.py` |
| `pipeline.eval.kg_external` | 없음 | `tests/general/pipeline/test_kg_external.py` |
| `pipeline.eval.make_questions` | 없음 | `tests/general/pipeline/test_make_questions.py` |
| `pipeline.eval.qa_draft` | 없음 | `tests/general/pipeline/test_qa_draft.py` |
| `pipeline.eval.report` | 없음 | `tests/general/pipeline/test_report.py` |
| `pipeline.eval.run_board` | 없음 | `tests/general/pipeline/test_run_board.py` |
| `pipeline.eval.run_combo` | 없음 | `tests/general/pipeline/test_run_combo.py` |
| `pipeline.eval.score_gold` | 없음 | `tests/general/pipeline/test_score_gold.py` |
| `pipeline.eval.stack_report` | 없음 | `tests/general/pipeline/test_stack_report.py` |
| `pipeline.extract.dedup` | 없음 | `tests/general/pipeline/test_dedup.py` |
| `pipeline.extract.engines.office_stdlib.parser` | 없음 | `tests/general/pipeline/test_office_parser.py` |
| `pipeline.load.structured` | 없음 | `tests/general/pipeline/test_structured.py` |
| `pipeline.shared.meaning` | 없음 | `tests/general/pipeline/test_shared_meaning.py` |
| `pipeline.shared.postprocess` | 없음 | `tests/general/pipeline/test_postprocess.py` |
| `pipeline.transform.figures.charts` | 없음 | `tests/general/pipeline/test_charts.py` |
| `pipeline.transform.figures.mermaid` | 없음 | `tests/general/pipeline/test_mermaid.py` |
| `pipeline.transform.figures.vector` | 없음 | `tests/general/pipeline/test_vector.py` |
| `pipeline.transform.represent.attachments` | 없음 | `tests/general/pipeline/test_attachments.py` |
| `pipeline.transform.represent.context` | 없음 | `tests/general/pipeline/test_context.py` |
| `pipeline.transform.represent.parse_qa` | 없음 | `tests/general/pipeline/test_parse_qa.py` |
| `pipeline.transform.represent.represent` | 없음 | `tests/general/pipeline/test_represent.py` |
| `pipeline.transform.structure.chunking` | 없음 | `tests/general/pipeline/test_chunking.py` |
| `pipeline.transform.structure.facts` | 없음 | `tests/general/pipeline/test_facts.py` |
| `pipeline.transform.structure.wiki` | 없음 | `tests/general/pipeline/test_wiki.py` |
| `pipeline.transform.structure.wiki_draft` | 없음 | `tests/general/pipeline/test_wiki_draft.py` |
| `validation.e2e.model_matrix` | 없음 | `tests/general/e2e/test_model_matrix.py` |
| `validation.e2e.stack_matrix` | selftest | `tests/general/e2e/test_stack_matrix.py` |
| `common` | --selftest | `tests/server/common/test_common_init.py` |
| `common.ai.adk` | 없음 | `tests/server/common/test_adk.py` |
| `common.ai.agent_prompts` | 없음 | `tests/server/common/test_agent_prompts.py` |
| `common.ai.embed` | 없음 | `tests/server/common/test_embed.py` |
| `common.ai.guard` | --selftest | `tests/server/common/test_guard.py` |
| `common.ai.llm` | 없음 | `tests/server/common/test_llm.py` |
| `common.check.check_modules` | --selftest | `tests/server/common/test_check_modules.py` |
| `common.check.ping_models` | --selftest | `tests/server/common/test_ping_models.py` |
| `common.config.settings` | --selftest | `tests/server/common/test_settings.py` |
| `common.core.artifacts` | --selftest | `tests/server/common/test_core_artifacts.py` |
| `common.core.index_cfg` | 없음 | `tests/server/common/test_core_index_cfg.py` (11-01 지움 — mc-16) |
| `common.core.paths` | 없음 | `tests/server/common/test_paths.py` |
| `common.core.resources` | 없음 | `tests/server/common/test_core_resources.py` |
| `common.core.sources` | --selftest | `tests/server/common/test_sources.py` |
| `common.core.terms` | 없음 | `tests/server/common/test_core_terms.py` |
| `common.core.text` | 없음 | `tests/server/common/test_core_text.py` |
| `common.store.db.dbtool` | --selftest | `tests/server/common/test_dbtool.py` |
| `common.store.mssql` | --selftest | `tests/server/common/test_mssql.py` |
| `common.store.registry` | 없음 | `tests/server/common/test_store_registry.py` |
| `common.store.services` | --selftest | `tests/server/common/test_services.py` |
| `mcp_server.cli.mcp_eval` | --selftest | `tests/server/mcp/test_mcp_eval.py` |
| `mcp_server.cli.qa_report` | --selftest | `tests/server/mcp/test_qa_report.py` |
| `mcp_server.cli.search_checks` | --selftest | `tests/server/mcp/test_search_checks.py` |
| `mcp_server.config` | --selftest | `tests/server/mcp/test_mcp_config.py` |
| `mcp_server.main` | --selftest | `tests/server/mcp/test_mcp_main.py` |
| `mcp_server.services.search.index_cfg` | 없음 | `tests/server/mcp/test_srch_index_cfg.py` (11-01 지움 — mc-16) |
| `mcp_server.services.search.local` | 없음 | `tests/server/mcp/test_local.py` |
| `mcp_server.services.search.qa_log` | 없음 | `tests/server/mcp/test_qa_log.py` |
| `mcp_server.services.search.qtype` | 없음 | `tests/server/mcp/test_qtype.py` |
| `mcp_server.services.search.registry` | 없음 | `tests/server/mcp/test_search_registry.py` |
| `mcp_server.services.search.retriever` | 없음 | `tests/server/mcp/test_retriever.py` |
| `mcp_server.services.search.terms` | 없음 | `tests/server/mcp/test_search_terms.py` |
| `mcp_server.services.search.text` | 없음 | `tests/server/mcp/test_search_text.py` |
| `pipeline.check_env` | --selftest | `tests/server/pipeline/test_check_env.py` |
| `pipeline.config` | --selftest | `tests/server/pipeline/test_pipeline_config.py` |
| `pipeline.eval.auto_questions` | --selftest | `tests/server/pipeline/test_auto_questions.py` |
| `pipeline.eval.gold_draft` | --selftest | `tests/server/pipeline/test_gold_draft.py` |
| `pipeline.eval.server_checks` | --selftest | `tests/server/pipeline/test_server_checks.py` |
| `pipeline.extract.engines._common.contract` | 없음 | `tests/server/pipeline/test_engine_contract.py` |
| `pipeline.extract.prepare` | --selftest | `tests/server/pipeline/test_prepare.py` |
| `pipeline.extract.rdb_discover` | --selftest | `tests/server/pipeline/test_rdb_discover.py` |
| `pipeline.extract.resources` | 없음 | `tests/server/pipeline/test_ext_resources.py` |
| `pipeline.extract.run_all` | --selftest | `tests/server/pipeline/test_run_all.py` |
| `pipeline.extract.source` | --selftest | `tests/server/pipeline/test_source.py` |
| `pipeline.load.index` | --selftest | `tests/server/pipeline/test_index.py` (11-01 지움 — mc-16) |
| `pipeline.load.index_cfg` | 없음 | `tests/server/pipeline/test_load_index_cfg.py` (11-01 지움 — mc-16) |
| `pipeline.load.pgvector_load` | --selftest | `tests/server/pipeline/test_pgvector_load.py` |
| `pipeline.load.publish_parse_result` | --selftest | `tests/server/pipeline/test_publish_parse.py` |
| `pipeline.shared.artifacts` | --selftest | `tests/server/pipeline/test_sh_artifacts.py` |
| `pipeline.shared.runlog` | 없음 | `tests/server/pipeline/test_shared_runlog.py` |
| `pipeline.shared.text` | 없음 | `tests/server/pipeline/test_shared_text.py` |
| `pipeline.stackcfg` | --selftest | `tests/server/pipeline/test_stackcfg.py` |
| `pipeline.stream` | --selftest | `tests/server/pipeline/test_stream.py` |
| `pipeline.tools.resources` | 없음 | `tests/server/pipeline/test_tools_resources.py` |
| `pipeline.transform.figures.chart_values` | 없음 | `tests/server/pipeline/test_chart_values.py` |
| `pipeline.transform.figures.diagram_edges` | 없음 | `tests/server/pipeline/test_diagram_edges.py` |
| `pipeline.transform.figures.figure_review` | --selftest | `tests/server/pipeline/test_figure_review.py` |
| `pipeline.transform.figures.figures` | 없음 | `tests/server/pipeline/test_figures.py` |
| `pipeline.transform.figures.figures_resume` | --selftest | `tests/server/pipeline/test_figures_resume.py`(10-30 둘 다 지움 — pl-32 2c·pl-35) |
| `pipeline.transform.figures.nested` | 없음 | `tests/server/pipeline/test_nested.py` |
| `pipeline.transform.figures.overlay` | 없음 | `tests/server/pipeline/test_overlay.py` |
| `pipeline.transform.figures.pptx_edges` | 없음 | `tests/server/pipeline/test_pptx_edges.py` |
| `pipeline.transform.figures.pptx_render` | 없음 | `tests/server/pipeline/test_pptx_render.py` |
| `pipeline.transform.figures.shape_detect` | 없음 | `tests/server/pipeline/test_shape_detect.py` |
| `pipeline.transform.figures.vlm_page` | 없음 | `tests/server/pipeline/test_vlm_page.py` |
| `pipeline.transform.represent.agent_step` | 없음 | `tests/server/pipeline/test_agent_step.py` |
| `pipeline.transform.represent.agent_tools` | --selftest | `tests/server/pipeline/test_agent_tools.py` |
| `pipeline.transform.represent.fuse` | 없음 | `tests/server/pipeline/test_fuse.py` |
| `pipeline.transform.represent.parse_agent` | --selftest | `tests/server/pipeline/test_parse_agent.py` |
| `pipeline.transform.represent.reread` | 없음 | (pl-34 10-30 — 모듈·시험 지움) |
| `pipeline.transform.represent.reread_stage3` | 없음 | (pl-34 10-30 — 모듈·시험 지움) |
| `pipeline.transform.represent.scan_dedup` | 없음 | `tests/server/pipeline/test_scan_dedup.py` |
| `pipeline.transform.represent.supsub` | 없음 | `tests/server/pipeline/test_supsub.py` |
| `pipeline.transform.represent.table_inline` | 없음 | `tests/server/pipeline/test_table_inline.py` |
| `pipeline.transform.represent.table_std` | 없음 | `tests/server/pipeline/test_table_std.py` |
| `pipeline.transform.represent.trace` | 없음 | `tests/server/pipeline/test_trace.py` |
| `pipeline.transform.structure.build_bundle` | --selftest | `tests/server/pipeline/test_build_bundle.py` |
| `pipeline.transform.structure.draft_terms` | 없음 | `tests/server/pipeline/test_draft_terms.py` |
| `pipeline.transform.structure.gen_roster` | --selftest | `tests/server/pipeline/test_gen_roster.py` |
| `pipeline.trigger_server` | --selftest | `tests/server/pipeline/test_trigger_server.py` |
| (옛 `mcp_server.main` 사례 안) `dispatch`·`internal_docs`·`search_svc`·`server_state`·`shaping` | — | `tests/server/mcp/test_{dispatch,internal_docs,search_svc,server_state,shaping}.py`(+ `test_mcp_main`이 그대로 부름) |
| (옛 `common.__init__` 사례 안) `common.core.fingerprint` | — | `tests/server/common/test_fingerprint.py`(+ `test_common_init`이 부름) |
| `deploy/host/scripts/run_docs.py` 명령 줄(새 — Step A) | — | `tests/general/deploy/test_run_docs.py`(INPROCESS, 함수 5개) |

S9b(VS9 B-1) — `__main__` 자기 점검 7곳:

| 옛 자리 | 새 테스트 |
|---|---|
| `pipeline/extract/engines/_common/fields.py` | `tests/general/pipeline/test_fields.py` |
| `pipeline/extract/engines/hwpx/parser.py` | `tests/general/pipeline/test_hwpx_parser.py` |
| `pipeline/extract/engines/mhtml/parser.py` | `tests/general/pipeline/test_mhtml_parser.py` |
| `pipeline/extract/engines/plaintext/parser.py` | `tests/general/pipeline/test_plaintext.py` |
| `pipeline/extract/engines/rapidocr/parser.py` | `tests/general/pipeline/test_rapidocr_parser.py` |
| `pipeline/extract/engines/registry.py` | `tests/general/pipeline/test_engine_registry.py` |
| `pipeline/transform/figures/vgate.py` | `tests/general/pipeline/test_vgate.py` |

S10: `validation/e2e/rag_qa/verify_citations.py`(10-29부터 `valid_env/answer_test/rag_qa/`)의 `_demo()` → `tests/general/e2e/test_verify_cite.py`.

### 부록 5. 프롬프트 패키지 키(`_package_digest` — S2 표) · 26 → 25

S2(10-26)에 패키지에서 `README.md`·`cases.json`이 빠져 키가 모두 한 번 바뀌었다(프롬프트·`agent.json`·`agent.py` 바이트는 그대로). 이 키는 LLM·VLM 응답 캐시 키에 들어가지 않는다(C-08 ①). 지금 키 = S2 뒤 키(HEAD 측정과 같음 — S11b).

| 옛 자리(S1) | 지금 자리 | 옛 키(S1) | S2 뒤 = 지금 키 | 지금 |
|---|---|---|---|---|
| `common_tools/prompts/doc_summary` | `resources/prompts/common/doc_summary` | `fd68179f7f621501` | `3a04913cce0cdad1` | 있음 |
| `common_tools/prompts/figure_describe` | `resources/prompts/common/figure_describe` | `2139f57a61f4b079` | `ac08faa1611c0519` | 있음 |
| `common_tools/prompts/page_transcribe` | `resources/prompts/common/page_transcribe` | `3387c27388da70ea` | `4c4be61394c2e52f` | 있음 |
| `common_tools/prompts/research_judge` | `resources/prompts/mcp/research_judge` | `3ebb42ade974f218` | `f4008dd724a90a1d` | 있음 |
| `common_tools/prompts/triple_extract` | `validation/e2e/triple_extract`(S6a) | `c635be6d6638ea16` | `d7c05b47edc233a0` | 있음 |
| `common_tools/prompts/value_choice` | `resources/prompts/common/value_choice` | `917861ac34d58a6e` | `eaaeb4f977739c6b` | 있음 |
| `data_etl/agent/diagram_arrows` | `resources/prompts/pipeline/diagram_arrows` | `800b5af55b7ac00e` | `e3b8b50b8e4df8c3` | 있음 |
| `data_etl/agent/figure_chart_raster` | `resources/prompts/pipeline/figure_chart_raster` | `e24944a8d0b7e8ac` | `5e4b1e020664c10a` | 있음 |
| `data_etl/agent/figure_extract` | `resources/prompts/pipeline/figure_extract` | `64a5e23ec469a645` | `fea9999f09fc3c64` | 있음 |
| `data_etl/agent/figure_judge` | `resources/prompts/pipeline/figure_judge` | `04b38d9d2f8b18f7` | `3a9939880f50e957` | 있음 |
| `data_etl/agent/figure_overlay` | `resources/prompts/pipeline/figure_overlay` | `daa8e9dd154c1d7d` | `3c43a27b76e2ba29` | 있음 |
| `data_etl/agent/gold_draft` | `resources/prompts/pipeline/gold_draft` | `69c044f63bc443c0` | `ab84a4de89502ef4` | 있음 |
| `data_etl/agent/mermaid_check` | `resources/prompts/pipeline/mermaid_check` | `7bdd18b55ce30e22` | `926b8e8f6a70dc65` | 있음 |
| `data_etl/agent/nested_figure` | `resources/prompts/pipeline/nested_figure` | `effce8fee7652dff` | `4f7a0226626d5801` | 있음 |
| `data_etl/agent/parse_agent` | `resources/prompts/pipeline/parse_agent` | `8a42acfd664890dd` | `24d7711ce42aed8f` | 있음 |
| `data_etl/agent/parse_decide` | `resources/prompts/pipeline/parse_decide` | `78953ea3afb729b5` | `8267c8248fbb982f` | 있음 |
| `data_etl/agent/parse_decide_vlm` | `resources/prompts/pipeline/parse_decide_vlm` | `97c3cade7c7d7c44` | `e57064ed567149f4` | 있음 |
| `data_etl/agent/parse_shadow` | `resources/prompts/pipeline/parse_shadow` | `85de7df06d2b599a` | `a2c973c70747b368` | 있음 |
| `data_etl/agent/qa_draft` | `resources/prompts/pipeline/qa_draft` | `98794145c782cd92` | `17c0d5057284f87c` | 있음 |
| `data_etl/agent/table_struct_judge` | `resources/prompts/pipeline/table_struct_judge` | `29806b26e3a62a87` | `95f2418389df3c6f` | 있음 |
| `data_etl/agent/value_choice_ctx` | `resources/prompts/pipeline/value_choice_ctx` | `482766b85451e944` | `5e1ecee20010a08f` | 있음 |
| `data_etl/agent/wiki_term_draft` | `resources/prompts/pipeline/wiki_term_draft` | `f6d31b6dca848730` | `f9c144e1a5ac270a` | 있음 |
| `data_retrieval/prompts/agg_llm_route` | `resources/prompts/mcp/agg_llm_route` | `f3397baa2495e88a` | `2904ef772be7e246` | 있음 |
| `data_retrieval/prompts/query_decompose` | `resources/prompts/mcp/query_decompose` | `466af945c0be243d` | `4babd6eb12caaea5` | 있음 |
| `data_retrieval/prompts/research_check` | — | `72949460ff391356` | `9ff9e52d5cb3c77b` | S11 삭제(C-25 ③) |
| `data_retrieval/prompts/research_decompose` | — | `095d4ee4b0ee8d95` | `d11927f2fbf7b96a` | S5a 삭제(D-025) |
| `data_retrieval/prompts/research_rewrite` | — | `d56badad76aec307` | `e618f5e7fda26cd3` | S5a 삭제(D-025) |
| `valid_env/answer_test/rag_qa`(S2 표 밖) | `validation/e2e/rag_qa`(S10) → `valid_env/answer_test/rag_qa`(10-29 되돌림 — 핑거프린트 같음) | — | `2bd32eeef0002c76`(S10 뒤 · 10-29 옮긴 뒤 같음) | 있음(PC 전용) |

- 셈: S1 28(이 표 27 + `rag_qa`) → S5a 26(`research_decompose`·`research_rewrite` 삭제) → S11 **25**(`research_check` 삭제) = `resources/prompts/` 23 + PC 전용 `triple_extract`·`rag_qa`. 남은 25개 값은 S11 전과 같음(VS11).

## 3. 옛 release-and-patch §5-4 — `pipeline.env` → settings.yaml 이관(S7e1)

S7e1(사용자 10-27, D-028) 버전부터 compose·셸·systemd·`run_docs.py`는 `$SERVER_ENV_DIR/settings.yaml`만 읽는다(옛 `pipeline.env`가 있고 settings.yaml이 없으면 "설정 이관 필요"로 종료 코드 2). **새 이미지 적재 뒤·컨테이너를 새로 띄우기 전에** 한다. 호스트 python에 pydantic·PyYAML이 없으면 `python -m …` 대신 이미지 안에서(아래 `docker run` 꼴).
```bash
cd /srv/rag/code/live
# ① 옮기기 — 화면에는 비밀을 가림, 파일은 실제 값
PYTHONPATH=app/deploy python -m common.config.migrate /srv/rag/env/pipeline.env --out /srv/rag/env/settings.yaml   # 서버 배치 코드 폴더 live/app/deploy(저장소 배치면 PYTHONPATH=.)
#   이미지 안: docker run --rm -i --network none --entrypoint bash data-pipeline:<태그> -c 'cat > /tmp/p.env && python -m common.config.migrate /tmp/p.env --out /tmp/s.yaml >&2 && cat /tmp/s.yaml' < /srv/rag/env/pipeline.env > /srv/rag/env/settings.yaml
# ② env-guide.md "옛 서버 값" 표의 항목(옛 options.conf가 채우던 값 — run_mode: prod·parse_post: all·max_rows: 1000 등, C-39·C-43
#    + 옛 compose 기본값 chain_structure_url — C-47 · mcp.server.store는 11-01에 없앰) 중 pipeline.env에 같은 이름이 없던 것만 settings.yaml에 옮겨 적는다 ·
#    특히 common.store.run_mode: prod — 빠뜨리면 PG 연결 실패 때 문서 레지스트리가 SQLite로 조용히 대체돼 run_docs 문서별 publish가 그 전 문서를 deleted·숨김으로 만든다(C-54) ·
#    EDW를 쓰면 common.connections.rdb의 read·write 계정(필수 — C-67, 옛 common.connections.edw는 없앰) · run_docs.py를 쓰면 C-45 ③의 항목도
# ③ 대조 — 옛 실효 값(옛 카탈로그 값 + pipeline.env) ↔ 새 파일, 값은 안 찍음. "다름 0 · 옛에만 0 · 확인 필요 0"(종료 코드 0)일 때까지 ②를 고침
PYTHONPATH=app/deploy python -m common.config.migrate --compare /srv/rag/env/pipeline.env --settings /srv/rag/env/settings.yaml
# ④ 권한(C-09): 컨테이너 사용자 UID 10001이 읽어야 함
sudo chown 10001:<운영 계정 그룹> /srv/rag/env/settings.yaml && sudo chmod 640 /srv/rag/env/settings.yaml
# ⑤ 호스트 값 확인(비밀 없음) · 옛 파일은 되돌리기용으로 이름만 바꿔 남김
bash deploy/host/scripts/settings_env.sh common.run_env pipeline.host mcp.host common.host
sudo mv /srv/rag/env/pipeline.env /srv/rag/env/pipeline.env.before-s7e1
```
- **env 파일 읽는 규칙(VS7e1 B-3):** migrate는 옛 서버 컨테이너가 받던 값 그대로 옮기려고 docker compose v2의 `env_file` 규칙(compose-spec/compose-go `dotenv/parser.go`)으로 읽는다 — 따옴표 없음: 줄 끝까지·` #` 뒤 주석·`$` 치환 · 작은따옴표: 글자 그대로 · 큰따옴표: `\n`·`\t`·`\"`·`\\`·`\$` 등을 푼 뒤 `$` 치환. `$` 치환 값(같은 파일 앞 줄·compose를 띄운 셸 env)·podman-compose와 다른 꼴(`$X`)은 도구가 확실히 알 수 없어 **"확인 필요 <이름>: <이유>"**(값 없음)로 내고 `--compare`가 종료 1 — 그 이름의 옛 컨테이너 값(`docker exec <컨테이너> printenv <이름>` — 화면에 찍지 말고 견주기만)과 settings.yaml 값이 같은지 사람이 확인한다.
- **옛 이름 옮김(C-35):** `QA_CHAT_DECOMPOSE`·`SYNTHETIC_TRUTH`는 새 항목(`mcp.search.decompose_llm`·`common.models.guard.synthetic_truth`)으로 옮기고 "옛 이름 옮김" 줄에 이름만 낸다(새 이름이 같이 있으면 새 이름 값).
- **라이브러리 env(C-47 ③):** `TZ`·`OMP_NUM_THREADS`·`HF_HUB_OFFLINE` 등 허용 목록 이름은 `common.runtime.lib_env`로 옮긴다("라이브러리 env" 줄). 그 밖 "모델 밖" 줄은 settings.yaml로 옮길 수 없는 이름 — 서버가 쓰던 이름이면 알린다.
- **호스트 항목만(VS7e2 B-3):** 옛 env 파일에 `RUN_ENV=dev·stage·prd` 줄이 있으면(C-34 — 서버 env 파일 필수) `GOLD_DIR`는 "호스트 칸만" 줄로 `pipeline.host.gold_dir`에만 옮긴다. `RUN_ENV` 줄이 없는 파일이면 두 항목 모두에 넣고 "확인 필요(RUN_ENV 없는 파일 …)"로 알린다(`--compare`도 확인 필요로 종료 1 — VS7e3 R-3) — 서버가 `RUN_ENV`를 셸·systemd로만 주었다면 옛 env 파일 사본에 `RUN_ENV=<dev|stage|prd>` 줄을 적고 다시 옮긴다(앱 항목 `pipeline.paths.gold_dir`는 비움 — 컨테이너 앱은 `run_tool.sh`가 붙인 `/data/gold`를 읽음). `--compare`도 같은 규칙이라 "같음". S7e2 버전 migrate로 앱 항목까지 적었다면 지운다(`refactor.md` C-47 ⑨).
- 이관 뒤 값을 바꿀 때는 settings.yaml을 직접 고친다 — 오버레이 설정 파일 도구(`common.config.overrides`)는 PC 전용이라 서버에서 종료 2(D-029 ①).
- systemd unit 2개를 새 버전으로 다시 복사하고 `daemon-reload`(옛 `EnvironmentFile` 줄이 빠짐 — 호스트 python에 pydantic이 없으면 `Environment=SETTINGS_IMAGE=data-pipeline:<태그>`를 더함).
- 되돌리기: 옛 버전 코드 폴더(backup)·옛 이미지로 돌아갈 때 `pipeline.env.before-s7e1`을 `pipeline.env`로 되돌린다.
