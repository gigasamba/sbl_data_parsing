# 서버 가이드 — 수집 서버 · 개발 서버

대상: 서버 운영자. 설치 순서는 [README §5-0](../../README.md#서버-설치-순서) 하나다. 설정 칸: [env-guide.md](env-guide.md) · 새 판(새 루트)·새 이미지·0.2.0 배포: [release-and-patch.md](release-and-patch.md).

## 0. 이미지 2개와 명령

| 이미지 | 역할 | `RAG_MODULE` | 상주 컨테이너(`deploy/host/compose/`) |
|---|---|---|---|
| `data-pipeline` | 파싱·게시·구조화·적재 | `pipeline` | `data-pipeline`(`compose.pipeline.yml` — 일 없이 떠 있음) · `data-pipeline-mcp`(`compose.pipeline-mcp.yml` — `parse_document` 작업 서비스) |
| `mcp-server` | 검색 MCP | `mcp` | `mcp-server`(서비스 이름 `mcp` — `compose.mcp-server.yml`) |

- 이미지 시작 스크립트(`entrypoint.sh`)는 다른 이미지의 명령을 종료 64로 거부한다(맞는 이미지를 알려 줌). data-pipeline: `parse`·`publish`·`show-stack`·`idle`·`migrate`·`parse-service` · mcp-server: `mcp`·`ask`·`show-stack`.
- 어느 이미지에서나: `help`·`check`·`resources`·`services`·`check-modules`·`tool <이름> [인자]`·`selftest`.
- 서버 배치: 공용 폴더(예 `/home/sbl/`) 아래 이미지 폴더 `sbl_images-main/`(서버에 한 번 load — 모든 벌이 같이 씀)와 루트(한 벌 — 예 `dev/`·`dev-hong/`). 루트 아래 `settings.yaml`·`edw_chain.yaml`·코드 폴더 `sbl_data_parsing-<판>/`·결과 폴더 `output/`·`backup/`. 루트 = 코드 폴더의 부모 — 호스트 스크립트가 자기 자리에서 구한다(README §5). 판마다 새 루트를 만든다([release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--새-루트로-코드-바꾸기)).
- 개발 서버는 실행 이미지(`*-runtime`)에 코드 폴더를 `/app/deploy`에 읽기 전용으로 붙인다 — `host_ctl.sh`·`mcp_keepalive.sh`가 자기 코드 폴더를 `CODE_DIR`로 잡는다(셸에 `CODE_DIR`가 있으면 그 값). 코드 없이·의존성 지문이 다른 코드로 띄우면 시작 거부(종료 2). 운영 서버는 코드가 든 이미지(`bake_prod_image.sh`)를 쓴다.
- 서버로 옮기기: 처음 설치(PC → 개발 서버)는 [README §5-0 서버 설치 순서](../../README.md#서버-설치-순서), 코드만 바꿀 때는 [release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--새-루트로-코드-바꾸기), 개발 서버 → 운영(수집) 서버는 [release-and-patch §1-2](release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)(`bake_prod_image.sh` → `load.sh` → `host_ctl.sh`). 컨테이너는 compose를 직접 부르지 않고 `host_ctl.sh`로 다룬다.
- 명령은 모두 코드 폴더(`cd <루트>/sbl_data_parsing-<판>`)에서, root 셸에서 실행한다.
- 컨테이너 상태: 서버 전체는 `podman ps`·`docker ps`(root로 띄웠으면 `sudo podman ps`), 우리 묶음만은 `bash deploy/host/scripts/host_ctl.sh ps`.

## 1. 설정

```bash
export DOCKER=podman                                   # 운영 계정 ~/.bashrc에 두거나 명령 앞에 붙인다
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   # 루트의 output/·backup/·settings.yaml·edw_chain.yaml(없을 때만) — README §5-0 3번
```
- 값은 `init`이 찍은 빈 필수 칸부터 채운다(README [꼭 채울 값](../../README.md#꼭-채울-값)). `nightly_batch.sh`·`pipe_exec.sh`·`mcp_keepalive.sh`·systemd unit은 `<루트>/settings.yaml`을 스스로 찾는다.
- **엔진 구성은 코드 폴더의 파일이다**(`resources/config/pipeline_stack.json` — 다른 파일이면 `ops.paths.stack_file`). 바꾸려면 코드 폴더째 바꾼다. 원천은 폴더·`rdb:csv`만.

### 1-1. 값 바꾸기
- 앱 설정은 `settings.yaml`을 직접 고치고 `host_ctl.sh up -d --force-recreate <서비스>`.
- **한 번만 다른 값은 `--set 이름=값`** — 받는 진입점: `pipeline.cli`·`pipeline.extract.fetch_docs`·`pipeline.engine_stack`·`build_bundle`·`pgvector_load`·`publish_parse_result`. 예: `$DOCKER exec data-pipeline python -m pipeline.cli --set PIPE_PROCS=2 parse …`. 이름은 옛 env 이름(`python -m common.config.sample --where`). 모르는 이름·호스트 칸·비밀 칸은 종료 2.
- 셸·compose·`docker exec -e`로 준 옛 env 이름은 효과가 없다(시작 때 이름만 경고). 셸 env로 덮을 수 있는 것은 compose 치환 값(이미지 태그·자원·포트·호스트 경로)뿐이다.
- 오버레이 설정 파일 도구 `python -m common.config.overrides`는 PC 전용이다(서버는 종료 2).

### 1-2. 기동 확인
README §5-3 ④ 연결 점검과 ⑤ 이미지 점검, 또는 한 번에 `bash deploy/host/scripts/host_ctl.sh check`(기대 마지막 줄 `[host_ctl check] 통과 — 6개`).

### 1-3. 한 서버에 여러 벌 띄우기(개발자별)
루트 하나가 한 벌이다. 개발자마다 루트를 따로 만들고(코드 zip을 풀고 `host_ctl.sh init`), 그 루트의 `settings.yaml`에 아래를 **벌마다 다르게** 적는다.

| 칸 | 하는 일 | 예(홍 개발자) |
|---|---|---|
| `ops.host.instance` | 컨테이너 이름·compose 묶음·systemd 타이머 이름 끝에 `-<이름>`을 붙인다(영소문자·숫자·`-`). 비우면 한 벌 — 이름 그대로 | `hong` → `data-pipeline-hong`·`data-pipeline-mcp-hong`·`mcp-server-hong`, 타이머 `data-pipeline-nightly-hong.timer` |
| `search.server.port` | 검색 MCP 포트 | `8775` |
| `ops.services.parse_mcp.port` | parse_document 작업 서비스 포트 | `8776` |
| `search.parse_proxy.url` | 검색 MCP가 부르는 작업 서비스 주소 — 위 포트와 같게 | `http://127.0.0.1:8776` |
| `required.pg.db_schema` | 검색 DB 스키마(벌마다 따로 적재) | `sbl_hong` |

- 컨테이너는 모두 호스트 네트워크라 포트가 겹치면 뒤에 띄운 쪽이 시작하지 못한다.
- 명령은 그 루트의 코드 폴더에서 `host_ctl.sh`로만 한다 — `host_ctl.sh`·`mcp_keepalive.sh`·`nightly_batch.sh`·`pipe_exec.sh`·`run_docs.py`가 `ops.host.instance`를 읽어 자기 벌의 컨테이너만 다룬다. compose를 직접 부르면 이름·포트 값이 채워지지 않는다.
- 자동 실행(`host_ctl.sh timers`)도 벌마다 따로 켜진다. 개발자 벌은 새벽 배치가 필요 없으면 `systemctl disable --now data-pipeline-nightly-<이름>.timer`.
- CPU·메모리 상한(§README 5-0 "자원")은 서버 전체 합계를 보고 벌마다 줄인다.

## 2. 일상 실행 — run_docs(문서별 흐름)

서버 입구는 `run_docs.py` 하나다 — 문서마다 파싱 → publish(Object Storage + EDW) → 원본 삭제 → 구조화·적재를 상주 컨테이너 안에서 `exec`로 돌린다(PRD [pl-24](../prd/ops.md#pl-24)). 자리·설정: [release-and-patch §5-4](release-and-patch.md#5-4-run_docspy-자리와-설정).
- 원본(`_warm/*.bin`·`_docflow/<seq>/_source_files`)은 **publish가 성공한 뒤에만** 지운다. 파싱·publish가 실패한 문서는 원본이 남고 `batch_progress/progress.log`에만 적힌다(EDW에 안 씀 — 다음 `--skip-done` 실행이 다시 고름). 구조화·적재가 실패하면 publish한 결과·EDW 행은 그대로이고 로그에만 적힌다.
- **게시·EDW 설정**(settings.yaml `required` — 빠지면 run_docs가 칸 이름을 찍고 종료 2): 게시 위치 `required.publish.bucket`·`prefix`, Object Storage 접속 `required.object_storage.endpoint`·`access_key`·`secret_key`(`region` 비우면 `us-east-1`, `verify_tls` 비우면 검증 켬 — 사내 CA면 CA 파일 경로), EDW 접속 `required.edw.host`·`database`·`read_*`·`write_*`(`port` 비우면 1433), 게시 표 `required.edw.parsing_meta_table`(비우면 `AI.ParsingMeta`). `required.edw.sqlite`는 PC 전용이라 서버에서는 비운다.
- **종료 코드**(PRD [pl-18](../prd/ops.md#pl-18)): `0` 대상 0건·모두 끝 · `1` 실패 문서가 하나라도 · `75` 마감(`--deadline`) 도달(실패 없음) 또는 다른 run_docs가 도는 중 · `2` 설정 문제. 실패와 마감이 함께면 `1`. 새벽 배치 unit은 `75`를 성공으로 친다.
- **겹침 잠금:** run_docs는 `batch_progress/run_docs.lock`을 `flock`으로 잡는다 — 새벽 배치와 사람이 직접 돌린 run_docs가 함께 돌지 않는다(뒤에 온 쪽이 75). 죽으면 잠금은 저절로 풀린다. 작업 폴더(`ops.pipeline_host.run_docs_dir`)가 같아야 같은 잠금이다.
- 파싱·게시만 따로:
```bash
bash deploy/host/scripts/pipe_exec.sh parse [--source-limit N]   # 파싱 → <결과 폴더>/parse/_rep. 임베딩·DB 없음
bash deploy/host/scripts/pipe_exec.sh publish --dry-run          # 무엇을 올리고 쓸지 표만(쓰기 0)
bash deploy/host/scripts/pipe_exec.sh publish                    # 대표 결과 Object Storage 업로드 + EDW 메타 — 한 번만
```
- 같은 결과 폴더에 두 작업이 겹치면 `/app/output/.pipeline.lock` 때문에 뒤쪽이 종료 75.
- 도구만 따로: `bash deploy/host/scripts/pipe_exec.sh <rdb_discover|check_env|ping_models|migrate|show-stack|check> [인자]`.
- 우선순위 낮추기(`tuning.extract.low_priority` — 일괄 파싱 엔진 자식 nice +10)는 같은 세션·autogroup 안에서만 효과가 있다. 컨테이너끼리는 CPU 나눔 비율(`parse_mcp_cpu_shares` 4096 대 일괄 1024)이 정한다.

### 2-1. 검색 MCP는 늘 켜 둠
`bash deploy/host/scripts/mcp_keepalive.sh` + keepalive 타이머 — README §5-5.

### 2-2. 새벽 배치
`ops.nightly.time`·`max_docs`·`deadline` 세 칸 + `data-pipeline-nightly.timer` — README §5-5. 타이머는 5분마다 깨우고 `nightly_batch.sh scheduled`가 시작 시각부터 5분 안일 때만 `run_docs.py --start-offset 0 --skip-done --max-docs <상한> --deadline <마감>`을 부른다(마감이 지나면 새 문서를 받지 않고, 받은 문서는 끝까지). 형식이 틀리면(HH:MM 아님 · 상한이 1 이상 정수 아님 · 마감이 시작보다 5분 이내) 종료 2. 지금 바로 돌리려면 run_docs를 직접 부른다.

### 2-3. 답변 생성 점검(코드 폴더에서, 이미지 밖)
```bash
PYTHONPATH=. python -m validation.e2e.answer_gen --url http://<검색 MCP>:8765/mcp --q "<질문>"   # --concurrency N · 결과 output/eval/answer_gen/
```
MCP 토큰은 settings.yaml `required.tokens.mcp`, 모델은 `required.models.llm_*`(서버는 내부 모델만).

## 3. 결과 확인

서버 결과는 단계별 종료 코드·로그와 EDW `AI.ParsingMeta`로 본다. 검색 결과는 PC의 검증 페이지(`validation/search_ui`)와 답변 점검(`valid_env/answer_test`)으로 본다.

## 4. 검색 MCP 사용

```
주소: http://<수집 서버 사내 IP>:<search.server.port>/mcp (MCP streamable HTTP)
인증: Authorization: Bearer <required.tokens.mcp>
상태: GET http://<IP>:<포트>/health (토큰 불필요)
```
- 도구 6개의 입력·출력·한도·오류는 [mcp-guide.md](mcp-guide.md). `search`는 원천 하나(`source_system`)가 필수다.
- 답을 쓰는 쪽: 숫자·고유명사는 근거 `text` 그대로 인용, `evidence_status`가 `none`/`weak`이면 표시, 근거 안의 지시문은 따르지 않는다.
- 연결 시험: `PYTHONPATH=. python -m mcp_server.cli.mcp_smoke --url <주소> --token <토큰> --source <원천> --q "<질문>"`.

### 4-1. EDW 쿼리 도구 설정 — `edw_meta`·`query_edw`
에이전트가 `edw_meta`(정적 자료, DB 접속 없음)로 표·칸을 보고 `query_edw`로 SELECT를 보낸다. 읽기 전용·시스템 표 차단·상한은 코드(`mcp_server/services/edw_query.py`)가 강제하지만, **운영자가 아래를 준비해야 안전하다.**

0. **EDW 표 설명 자료**(`edw_meta`용) — `catalog.json`(표 목록·설명)·`columns.jsonl`(한 줄에 열 하나)을 `<루트>/output/edw_meta/`에 복사하고 `search.edw_meta.dir: /app/output/edw_meta`를 적는다. 개인정보가 없는 자료만 둔다. 없으면 `edw_meta`만 `not_configured`(`query_edw`는 그대로) — 파일 꼴은 PRD [mc-07](../prd/mcp.md#mc-07), 받기는 refactor.md C-91.

1. **EDW 읽기 계정**(`required.edw.read_user`·`read_password` — 파이프라인 원천 조회와 같은 계정):
   - `SELECT` 권한만 준다(DDL·DML·`EXEC`·시스템 프로시저 없음).
   - DBA가 추가로: `DENY VIEW DEFINITION` · 다른 데이터베이스·연결 서버(linked server) 권한 없음 · 가능하면 Resource Governor 등으로 질의 시간·CPU 상한.
   - 검색 MCP는 시작할 때 쓰기 계정 칸을 설정 객체에서 비운다. 파일 자체는 컨테이너가 읽을 수 있으므로, 완전히 떼려면 mcp-server에 쓰기 칸이 없는 설정 파일을 따로 붙인다.
   - 같은 계정이라 `query_edw`도 `AI.FileStorageMap`·`AI.ParsingMeta`를 읽을 수 있다 — 막으려면 2.
2. **표 범위** — 읽기 계정이 볼 수 있는 모든 표(`sys.*`·`INFORMATION_SCHEMA.*`는 늘 거부). 좁히려면 DBA가 읽기 계정의 `SELECT` 권한을 줄인다(설정의 허용 목록은 없다).
3. 확인: `query_edw({"sql": "DROP TABLE ..."})`·`sys.*`를 읽는 호출이 `rejected:*`로 막히는지 한 번 본다.

## 5. 회사 맞춤(도메인 튜닝)

바꿀 곳은 코드가 아니라 **데이터 파일·설정**이다. 기밀(실고객·실제품·계약 값)은 **서버 폴더에만** 둔다 — git·PC·외부 모델로 보내지 않는다. 바꾼 뒤에는 같은 질문 세트로 검색 결과를 전/후 비교한다.

| 무엇 | 위치 |
|---|---|
| 용어집 · 고객 명부 · ID 모양 · 단위 · 계약·고객 마스터 | PG 마스터 표 `<db_schema>_master`. 원본 CSV(`resources/vocab/glossary/` 또는 서버 폴더)를 고친 뒤 `pipe_exec.sh migrate master load [--dir <폴더>]`(5-1) |
| 원천 표 열 이름 | settings.yaml `extract.connections.rdb.columns.*` |
| 엔진 구성 | `resources/config/pipeline_stack.json`(확인 `show-stack`) |
| MCP 안내 문구 | 코드 `mcp_server/main.py`의 `_DEFAULT_MCP_INSTRUCTIONS`(설정 칸 없음 — 바꾸면 코드 배포) |
| EDW 조인 사슬(고객·원천 메타·검색 attrs 키) | 서버 사본 `<루트>/edw_chain.yaml`(5-2) |

### 5-1. 고객 명부·용어집 작성법

구조화·검색은 파일이 아니라 PG 마스터 표만 읽는다. `migrate master load`가 CSV 여섯 개(`client_roster`·`client_master`·`contract_master`·`domain_terms`·`id_patterns`·`units` — 파일 이름·머리글 그대로)로 표를 통째로 바꾼다. 기본 폴더는 샘플(가상 회사·제품) `resources/vocab/glossary/`, 서버 실명 자료는 `--dir <폴더>`. 표가 비었으면 서버의 구조화·검색이 시작하지 않는다.
- **`master load` 뒤에는 검색 MCP를 다시 시작한다**(`$DOCKER restart mcp-server` — 검색은 시작할 때와 새 적재 판이 들어올 때만 마스터를 읽음). 이미 적재한 문서는 자동으로 다시 처리하지 않는다(새로 적재하는 문서의 `gold_version` `<VERSION>+m<해시 8자>`만 바뀜).
- ⚠️ compose는 서버 폴더(예 `<루트>/glossary/`)를 컨테이너에 붙이지 않는다. `--dir`에는 **컨테이너 안에서 보이는** 폴더를 적는다(그 전에는 코드 폴더 안 `resources/vocab/glossary/`를 고쳐 쓴다).
- 머리글은 `docs/architecture/db_schema.md` §4. UTF-8로 저장(Excel이면 "CSV UTF-8" — cp949도 읽힘). 머리글이 다르면 `master load`가 거부한다.

#### 고객 명부 `client_roster.csv`
한 줄 = 고객 하나. 필수는 `canonical_name` 또는 `name_ko` 하나.

| 칸 | 쓰는 법 |
|---|---|
| `client_id` | 고객 번호(SFDC 등) — 비워도 됨 |
| `canonical_name` | 정식 이름 — 비우면 `name_ko` |
| `name_ko` | 한글 이름 — 별칭으로도 쓰임 |
| `aliases` | 다른 표기를 `\|` 또는 `;`로 |
| `client_type` | `customer`·`prospect` — 둘 다 똑같이 쓰임 |
| `segment`·`country`·`parent_client_id`·`description`·`source`·`updated` | 참고용 — 비워도 됨 |
| `status` | 비우면 사용 · `inactive`·`deleted`면 무시 |

- 영문 3자 이하 별칭(예 `PFE`)은 오탐 때문에 무시된다 — 4자 이상이나 한글로. 같은 별칭을 두 고객에 쓰지 않는다.

#### 고객 마스터에서 명부 만들기
SFDC·EDW 내보내기에서 명부를 만든다. 열 이름만 매핑 파일에 적는다(예제: `resources/vocab/glossary/client_master.example.csv` + `client_master_map.example.json`). 매핑 키 = 명부 칸: `name`(필수 → `canonical_name`) · `aliases`(`;`·`|`) · `client_id`·`name_ko`·`client_type`·`segment`·`country`·`parent_client_id`·`status`·`description`·`updated`(선택). 열 이름은 영문·숫자·`_`만. 같은 고객 여러 줄은 하나로 합친다(별칭은 합치고 다른 칸은 처음 값).
```bash
PYTHONPATH=. python -m pipeline.transform.structure.roster_from_edw --kind client \
  --source csv:<루트>/client_master.csv --mapping <루트>/client_master_map.json \
  --out <루트>/client_roster.csv          # EDW 표에서 바로: --source rdb:<스키마.표>(읽기 계정)
PYTHONPATH=. python -m pipeline.transform.structure.roster_from_edw --check <루트>/client_roster.csv   # 오류 0 확인 후 반영
```

#### 용어집 `domain_terms.csv`
한 줄 = 개념 하나, 여러 값 칸은 `|` 구분.

| 칸 | 쓰는 법 |
|---|---|
| `concept_id` | 겹치지 않는 영문 ID(`분야.이름`, 예 `QA.OOS`) — 비우면 `AUTO.<canonical>`(같은 정식 이름이 ID 없이 또 나오면 뒤 줄은 건너뛰고 알림) |
| `canonical` | 표준 이름(필수) |
| `category` | `org_client`(고객 — 명부에 합류)·`product_example`·`modality`·`modality_code`·`process`·`quality`·`contract`·`regulatory`·`business` 등 |
| `synonyms` · `abbreviations` | 같은 뜻의 다른 표기 · 줄임말 |
| `weak_synonyms` | 뜻이 넓어 약하게만 쓰는 말 |
| `broader`·`related` | 상위·관련 개념의 `concept_id`(없는 ID면 오류) |
| `context_required` | 동음이의 줄임말이면 주변에 함께 나와야 하는 단어들 |
| `case_sensitive` | `Y`면 대소문자 구분 |
| `definition_ko`·`definition_en`·`source`·`owner`·`updated` | 비워도 됨 |
| `status` | 비우면 반영 · 빼려면 `draft`·`rejected` |

- 오류(조용히 넘기지 않음): 명시한 `concept_id` 중복 · 없는 ID를 가리키는 `broader`/`related` · `id_patterns.csv`의 깨진 정규식.
- 초안 도구 `python -m pipeline.transform.structure.glossary_suggest`·`gen_roster --kind product`·`python -m pipeline.transform.structure.draft_terms --bundle <묶음>`은 `output/` 아래 초안만 만든다 — 사람이 확인해 CSV로 옮긴다.

#### 점검(반영 전)
```bash
PYTHONPATH=. python -m pipeline.transform.structure.roster_from_edw --check <명부 파일>      # 오류 0이어야 함
PYTHONPATH=. python -c "from common.core import terms as T; import sys; g=T.load_glossary(sys.argv[1]); print(len(g), '개념 반영', sorted(g)[:5])" <용어집 폴더>   # 오류면 여기서 멈춤
```

### 5-2. EDW 조인 사슬 고치기 — `edw_chain.yaml`
고치는 곳·법·점검·되돌리기는 [release-and-patch §8-6](release-and-patch.md#8-6-edw-조인-사슬-파일-고쳐-쓰기서버--pl-29) 하나에 있다. 사슬을 바꿔도 이미 적재한 메타는 바뀌지 않는다 — 필요한 문서는 `--replace`로 다시 적재한다(다시 파싱하지 않음).

## 6. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `check`가 "컨테이너 안의 PG_HOST는 컨테이너 자신" 경고 | `required.pg.host`가 `127.0.0.1` | compose로 띄웠으면 무시(`network_mode: host`). `docker run`으로 따로 띄울 때만 `--network host`(+`-e NETWORK_HOST=1`) 또는 서버 IP |
| 적재·검색이 PostgreSQL에 못 붙음 | `required.pg` 칸이 비었거나 틀림 | 호스트·포트·계정 확인 |
| 파싱이 종료 4 | 서버에서 EDW `AI.ParsingMeta`를 못 읽음(전체 재파싱을 막으려고 멈춤) | `required.edw`(주소·읽기 계정)·EDW 연결 확인 |
| 구조화·적재가 "인계 형식(핑거프린트) 다름"으로 거부 | 핑거프린트가 바뀐 옛 파싱 결과 | 그 문서를 다시 파싱 |
| 같은 결과 폴더에서 종료 75 | 다른 실행이 `.pipeline.lock`을 잡고 있음 | 끝날 때까지 기다리거나 다음 트리거에서 재시도 |
| 메모리 터짐(OOM), 큰 스캔 PDF | 쪽 이미지를 한꺼번에 올림 | `extract.ocr.dpi`(기본 150 — 더 낮추면 VLM 글 품질을 먼저 확인)·VLM 쪽 상한 `transform.vlm.page_max`·OCR 엔진 쪽 상한 `extract.ocr.max_pages`·`extract.max_file_mb`·컨테이너 메모리 상한 확인 |
| CPU 폭주 | 컨테이너가 호스트 전체 코어로 스레드를 늘림 | `ops.runtime.pipe_procs`는 `auto`(cgroup 한도 기준), 컨테이너 CPU 상한 지정 |
| MCP `/health` 503 | 기동 직후 예열 중 | 잠시 뒤 재시도 |
| MCP 401 | 호출 쪽 토큰이 없거나 `required.tokens.mcp`와 다름 | 호출 쪽 `Authorization: Bearer <토큰>`을 서버 값과 같게 |
| MCP가 안 뜸 | `required.embed` 없음 · 컨테이너가 설정 파일을 못 읽음(권한) | 필수 값 채우기 · 주인 10001·권한 640 |
| `data-pipeline`·`mcp-server`가 안 뜸("edw_chain.yaml" 자리에 폴더) | `host_ctl.sh init` 전에 컨테이너를 띄워 빈 폴더가 생김 | 빈 폴더를 `rmdir` → `host_ctl.sh init` |
| 포트 충돌 | 다른 서비스가 같은 포트 | `search.server.port` 등 포트 칸만 바꿈 |
| SELinux `Permission denied` | 볼륨 라벨 안 맞음 | 볼륨에 `:z` |

## 7. 개발자에게 보고하는 법

### 서버 버전 기록
적용·업데이트마다 운영 기록 폴더(루트 밖 — 판이 바뀌어도 이어 씀, 이하 `<기록>`)의 `versions.md`에 한 줄: `날짜 · 서버 · 이미지 버전 · 코드 커밋 · 확인 결과`.

### 서버 자체 개발 기록
서버에서 코드를 직접 고치거나 새로 만들었거나 옵션 값을 바꿨으면 그때마다 `<기록>/server-changes.md`에 한 행 + diff를 `<기록>/server-changes/<ID>.diff`로(`diff -u <고치기 전> <고친 뒤>`, 새 파일이면 `diff -u /dev/null <파일>`). 새 판으로 바꿀 때 이 기록을 먼저 읽는다([release-and-patch §2](release-and-patch.md#2-서버에서-직접-고친-코드)).
```
| ID(SC-<MMDD>-<n>) | 날짜·시각 | 서버(수집/개발) | 바뀐 파일(코드 폴더 기준 경로) | 무엇·왜 한 줄 | 기준 버전(이미지+코드 커밋) | 테스트(명령·결과) | 상태(서버에만/PC 보냄/다시 얹음 <커밋>/PC 반영됨 <커밋>/폐기) |
```
지우지 않고 상태만 바꾼다. diff에는 코드만 — 비밀값·문서 본문·고객명은 넣지 않는다.

### 이슈 기록
문제가 나면 `<기록>/issues.md`에 한 행(지우지 않고 상태만 바꿈):
```
| ID(SI-<MMDD>-<n>) | 버전(이미지+코드 커밋) | 서버(수집/개발) | 단계·명령 | 증상 한 줄 | 종료 코드 | 로그 위치 | 상태(열림/수정됨/재확인 통과) |
```
반출 규칙: **오류 메시지·종료 코드·숫자·해시 이름만** — 문서 본문·고객명·원본 경로·키 값은 적지 않는다.

### 날짜별 요약
파싱이 끝날 때마다 `<기록>/<날짜>.md`에 버전(`versions.md` 줄)·단계·종료 코드·핵심 숫자(정답률·시간·건수)·막힌 곳·로그 마지막 20줄(비밀값 가림)을 적는다. 본문은 복사하지 않는다.
