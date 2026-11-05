# 운영 — 설정(settings.yaml·RUN_ENV)

[PRD.md](../PRD.md) 카테고리. [ops.md](ops.md)의 하위 문서. 실행 환경 `RUN_ENV`(op-02), settings.yaml 하나(op-05)·배치(op-08)·하드코딩 0(op-09), 지운 칸(pl-21·pl-30). 전체 칸과 기본값: `settings.sample.yaml`(생성: `python -m common.config.sample`).

순서: op-02 · op-05 · op-08 · op-09 · op-14 · pl-21 · pl-30.

<a id="op-02"></a>
## op-02 · RUN_ENV는 `local`·`dev`·`prd` 셋 · 가짜 LLM은 `local`에서만
- 이유: 서버에서 외부 모델이나 가짜 답이 돌면 안 된다.
- 규칙:
  1. `required.env.run_env`는 모든 곳에서 필수(기본값 없음) — `local`(PC)·`dev`(개발 서버)·`prd`(운영). 다른 값(`stage` 포함)은 시작 거부, 메시지에 세 값을 보인다.
  2. 외부 모델과 `dev.fake_llm`는 `local`에서만. `dev`·`prd`에서 `fake_llm`이 켜져 있으면 앱 시작에서 거부(`require_run_env` 관문 — 0이 아닌 종료 코드).
  3. `local`은 PC 신호다 — 저장소 루트 settings.yaml 찾기, PC 전용 분기는 `paths.LOCAL_RUN` 하나.
  4. RUN_ENV가 없는 명령(이미지 안 `selftest`, 점검 명령)은 시험 사례에서 가짜 LLM으로 돈다.
- 파일: `common/config/settings.py`(`RUN_ENVS`·`SERVER_ENVS`·시작 관문), `common/ai/llm.py`.
- QA: `tests/server/common/test_settings.py`·`test_guard.py`·`test_llm.py`(stage 거부 · dev/prd + llm_fake 거부 · 외부 모델 dev/prd 거부) · 통과.
- Status: done

<a id="op-05"></a>
## op-05 · settings.yaml 하나 — sample에 모든 키·기본값
- 이유: 설정 창구를 하나로.
- 규칙:
  1. 설정은 settings.yaml 하나에 둔다(`resources/config` 파라미터 파일 없음). 서버·PC 파일 = sample을 복사해 필수값·비밀값을 채운 것.
  2. `python -m common.config.sample`이 모든 칸을 실제 YAML로 낸다. 절 순서 [op-08](#op-08), 절 안은 카테고리 제목 주석(`# ─── … ───`). 값 자리 = 코드 기본값. 칸마다 줄 끝 주석 한 줄 — 필수 칸은 `[필수 · 언제(어느 앱)]`(언제 = 모두·local·dev·prd, 앱 = pipeline·mcp·호스트 스크립트 — `layout.REQUIRED_GROUPS` 칸마다 조건), 그 밖 `[선택]`, 짧은 설명과 허용값 또는 예, 비밀은 `[비밀]`. 설명은 `sample.NOTES` 한 표(칸이 빠지면 sample이 멈춤).
  3. sample에서 `null`(비움)로 내는 칸: 사람이 채울 값(기본 없음)·비밀·빈 글자·이미지 기본값 칸(이미지·PC 값이 다름)·적었는지로 동작이 갈리는 칸(`sample.SET_MATTERS` — `PIPE_PROCS`·`PIPE_THREADS`·`PM_BUCKET`)·저장소 경로가 든 기본값. `null`은 빈 칸과 같다(호스트 스크립트도 같게 읽음).
  4. settings.yaml에 적힌 값이 코드 기본값보다 이긴다. 비운 칸은 코드 기본값.
  5. 설정 값은 code_fp에 들어가지 않는다 — 값을 바꿔도 자동 재처리는 없다.
  6. 옛 env 이름·판정 꼴은 `python -m common.config.sample --where <이름>`.
  7. `null`로 내는 선택 칸의 주석은 "null = …"(비운 동작)을 적는다. 적힌 기본값 = 코드가 읽는 기본값(`tests/server/common/test_sample_yaml.py`가 대조).
  8. PC 전용 칸(외부 모델 허용·예상 비용·단가·지출 상한, 로컬 대체 DB, 시험 하네스)은 맨 아래 `dev` 절에 모은다(`layout.LOCAL`). 서버 settings.yaml에는 두지 않는다. 예외: PC 가짜 EDW `required.edw.local_sqlite_file`는 게시·EDW 칸과 함께 `required`에 둔다(9).
  9. 게시(silver)·EDW 칸은 `required` 한곳에 — `publish`(`bucket`·`prefix`)·`object_storage`(`endpoint`·`region`·`access_key`·`secret_key`·`verify_tls`)·`edw`(`parsing_meta_table`·`host`·`port`·`database`·`read_*`·`write_*`·`local_sqlite_file`). 칸 주석의 `[필수 · …]` 조건이 환경마다 넣을 값을 알린다 — PC는 게시 버킷 `file://<폴더 절대 경로>`와 `local_sqlite_file`만, 서버는 접속 칸. 기본값이 있는 칸(`region`·`verify_tls`·`port`·`parsing_meta_table`)은 비우면 코드 기본값.
- 메모(사용자 11-04 — 칸 줄이기): 읽는 곳이 없거나 겹치는 칸을 지웠다 — `secure_doc.password`, `pg.conn_file`, `ops.paths.output_root`(공용), `transport.ping_timeout`(점검기 상수 60초), EDW 원천 표의 선택 열(`bucket`·`company`·`doc_type`·`etag` 등 10개)과 `company`·`doc_type` 거르기, `structure.embed`(`gold_bundle --embed` 기본 api), publish `parse_date`·`path_map`, `server.instructions`, `search.min_score`, `search.pg.vector_search`, `edw_query.tables`·`tables_strict`, `gold_dir` 두 칸(op-11). 옛 파일에 남으면 시작 거부(rn-07). `search.server.fulltext_secret`은 `required.tokens.fulltext_sign_key`로 옮겼다. 남긴 칸과 이유: `tuning.ops.runtime.glossary_lock_timeout_sec`(용어 초안 잠금 — 핸드오프 파일이 읽음), `price_in_usd_per_mtok`·`price_out_usd_per_mtok`(가격표에 없는 모델), `extract.max_new_docs_per_run`(명령 기본값), `upload_statuses`, `load.stored_path_prefix`, `search.edw_meta.catalog_dir`(mc-07).
- 파일: `common/config/{sample,settings,keyscan,layout}.py`, `pipeline/config.py`, `mcp_server/config.py`, `settings.sample.yaml`.
- QA: `python -m common.config.sample --check` · sample이 설정 모델과 같음. `tests/server/common/test_sample_yaml.py`(복사한 sample로 서버 STRICT 시작 · 적힌 값 = 코드 기본값) · 통과.
- Status: done

<a id="op-08"></a>
## op-08 · 설정 배치 — 필수 묶음 + 역할별 파라미터 + tuning
- 이유: 운영자가 꼭 넣을 값을 맨 위에 모으고 나머지를 역할별로 나눈다.
- 규칙:
  1. 최상위 절 순서: `required` → `common` · `extract` · `transform` · `load` · `search`(MCP 검색) · `ops`(실행 자원·스케줄·서비스·서버 컨테이너·경로) — 역할 절에는 환경마다 운영자가 정하는 값(주소·TLS·포트·경로·상한·서버 크기에 맞춘 병렬 수·기능 스위치·호스트 스크립트와 `run_pipeline.py --set`이 쓰는 칸)만 → `tuning`(거의 안 바꾸는 값 — 결과 파라미터·내부 제한 시간·대기열·자원 세부값, 사용자 11-04: 코드로 내리지 않고 sample 아래쪽에 공통·추출·변환·적재·검색·로그·실행 자원·새벽 배치·상주 서비스 분류 제목으로, 비우면 코드 기본값) → `dev`(PC 전용 — 외부 모델·로컬 대체 DB·시험 하네스, op-05 8).
  2. `required` = 운영자가 꼭 정할 값(연결 주소·계정·비밀·게시 위치·이미지 태그) — `env`·`pg`·`embed`·`edw`·`publish`·`object_storage`·`models`·`source`·`tokens`·`deploy`. 카테고리 제목에 `[PC·서버]`·`[서버만]`·`[PC만]`.
  3. 파일 자리 ↔ 설정 모델 경로(`common.*`·`pipeline.*`·`mcp.*`)의 표는 `common/config/layout.py` 하나. `read_settings`가 파일을 모델 배치로 바꿔 읽는다.
  4. 옛 배치 파일(최상위 앱 절)은 시작 거부. 모델에 있는 칸을 다른 자리에 쓰면 "자리가 다른 칸 … → 새 자리"로, 모델에 없는 칸(지운 칸·오타)은 "모르는 칸 …"으로 거부한다 — 칸 이름만 알리고 값은 안 찍는다. 옛 자리를 읽어 주는 표·옮기는 도구는 없다(rn-07 — 사용자 11-05).
  5. 11-04 합친 칸: `extract.prefetch_workers` → `extract.source.fetch_threads`, `tuning.ops.nightly_run.workers` → `ops.runtime.vlm_parallel_docs`.
- 파일: `common/config/{layout,settings,sample,keyscan,export}.py`, `pipeline/config.py`, `mcp_server/config.py`.
- QA: `python -m common.config.keyscan --check` · 빠진 키 0개. `tests/server/common/test_layout.py` · 통과.
- Status: done

<a id="op-09"></a>
## op-09 · 하드코딩 0 — 설정 값은 settings.yaml 또는 이미지 기본값 표에서만
- 이유: 경로·포트·주소가 여러 곳에 복사되면 한 곳만 바뀌어 어긋난다.
- 규칙:
  1. 설정 값은 settings.yaml(코드 기본값은 설정 모델에 한 번) 또는 이미지 기본값 표 `common/config/settings.py` `IMAGE_PATHS` 하나에서만 온다. 저장소 안 경로는 `common/core/paths.py` 상수로만.
  2. 환경마다 다른 경로·접속(게시 대상·Object Storage·EDW·PG·호스트 경로)은 필수 — 코드 기본값이 없고 비면 시작 거부. PG 자동 찾기는 없다.
  3. 컨테이너 안 경로(`output_root` `/app/output` · `code_root` `/app/deploy` 등)는 `IMAGE_PATHS`가 원본이다. `deploy/release/gen_host_keys.py`가 이 표를 `deploy/host/scripts/host_settings.tsv`(`image.<이름>`·`APP_<이름>` 줄)로 내고, `load_settings.sh`가 `APP_*` env로 내준다 — compose는 `${APP_OUTPUT_ROOT}`·`${APP_CODE_ROOT}`·`${APP_DOCS_MOUNT}`, `run_pipeline.py`는 코드 폴더의 표를 읽는다. 생성: `PYTHONPATH=. python deploy/release/gen_host_keys.py`.
  4. 호스트 스크립트는 `load_settings.sh`(`settings_to_env.py` — PyYAML만)가 내준 값만 쓴다. 컨테이너 명령 = settings.yaml `ops.host.container_cli` > podman > docker(벌 이름 `INSTANCE`와 함께 셸 env로 덮지 않음 — `run_pipeline.py`와 같게, rn-07).
  5. 앱은 env에서 설정을 읽지 않는다 — 남은 env 줄은 분류 주석 필수(`python -m common.check.check_modules` ⑩·⑪).
- 파일: `common/config/settings.py`(`IMAGE_PATHS`), `common/config/keyscan.py`, `deploy/release/gen_host_keys.py`, `deploy/host/scripts/{load_settings.sh,settings_to_env.py,host_settings.tsv}`.
- QA: `python -m common.check.check_modules` · "모듈 경계 통과". `tests/general/deploy/test_host_env.py` · 통과. 서버 확인 refactor.md C-70.
- Status: done

<a id="op-14"></a>
## op-14 · PC는 가짜 대상만 — 저장소 기준 상대 경로
- 이유: 나중에 PC에서 전체 흐름을 가짜 대상(sqlite EDW, 폴더 Object Storage)으로만 돌린다. 저장소 위치가 PC마다 달라 절대 경로를 적기 번거롭다.
- 규칙:
  1. 경로 칸 — `required.edw.local_sqlite_file`, `required.publish.bucket`의 `file://` 꼴, `ops.paths.docs_dir`·`prepared_docs_dir`, `extract.source.input_location`(폴더·`rdb:csv:<경로>`), `dev.pg_standin.dir` — 는 상대 경로를 저장소 루트(`paths.PROJ_ROOT`) 기준으로 푼다. 푸는 곳은 설정 모델 한 곳(`settings.repo_path` — 칸 표시 `F(repo=…)`)이라 읽는 코드는 그대로다. 절대 경로·`s3://`·버킷 이름은 바꾸지 않는다.
  2. 가짜/실제 판정은 `settings.pc_real_targets` 한 곳. `local`에서 `required.edw.host`, `required.object_storage.endpoint`, 원천 버킷(`extract.source.default_bucket`), `file://`가 아닌 게시 버킷이 적혀 있으면 시작 관문(`require_run_env`)이 칸 이름과 예시를 찍고 종료 코드 2.
  3. `dev`·`prd`는 바뀌지 않는다(작업 폴더 `/app` = `PROJ_ROOT`라 상대 경로 결과도 같다).
- 파일: `common/config/settings.py`, `pipeline/config.py`, `common/config/sample.py`.
- QA: `tests/server/common/test_pc_targets.py`(상대 sqlite · 상대 `file://` 버킷 · 절대 경로 · local 실제 호스트 거부 · dev 실제 호스트 허용) · 통과.
- Status: done

<a id="op-15"></a>
## op-15 · 한 서버에 여러 벌(개발자별) — 이름·포트를 설정으로
- 이유(사용자 11-04): 개발 서버에 개발자마다 컨테이너를 따로 띄운다. 컨테이너 이름(`data-pipeline` 등)·compose 묶음 이름·systemd 타이머 이름이 고정이라 두 번째 벌이 첫 벌을 덮었다.
- 규칙:
  1. 루트 하나 = 한 벌. 새 칸 `ops.host.instance_name`(영소문자·숫자·`-`) — 적으면 컨테이너 3개·compose 묶음(`compose-<이름>`)·systemd 단위 4개 이름 끝에 `-<이름>`. 비우면 이름 그대로(한 벌 — 지금 서버와 같음).
  2. 이름을 붙이는 곳은 `load_settings.sh load_settings`(`NAME_SUFFIX` — 틀린 꼴이면 종료 2) 한 곳, 호스트 스크립트(`host_ctl.sh`·`mcp_keepalive.sh`·`nightly_batch.sh`·`pipe_exec.sh`)와 compose 파일은 그 값을 쓴다. `run_pipeline.py`는 같은 규칙으로 `configure()`에서.
  3. 벌 이름 하나로 갈림(rn-07): PG 스키마 `<db_schema>_<벌>` · EDW 기록 표 `<parsing_meta_table>_<벌>`(이미 붙어 있으면 그대로 — `layout.per_instance` 한 곳, 앱 `CommonSettings`·`run_pipeline.py`가 같이 씀) · 게시 경로는 dev에서만 `<prefix>/<벌>`(`settings.publish_prefix`). 버전에는 붙이지 않음.
  4. 포트 두 칸(`search.server.port` · `ops.services.data_parsing.port` — 작업 서비스와 검색 MCP가 같은 칸)은 벌마다 다르게 — 벌 이름이 있는데 기본값이면 시작 거부. `prd`에서 벌 이름이면 시작 거부. 거부는 앱 시작 관문(`instance_problems`)·`load_settings.sh`·`run_pipeline.py configure()` 셋 — server-guide §1-3.
- 파일: `common/config/settings.py` · `deploy/host/scripts/{load_settings.sh,host_ctl.sh,mcp_keepalive.sh,nightly_batch.sh,pipe_exec.sh,run_pipeline.py,host_settings.tsv}` · `deploy/host/compose/compose.{pipeline,data-parsing,mcp-server}.yml`.
- QA: `tests/server/common/test_instance.py`(스키마·표·게시 경로·prd·기본 포트 거부) · `tests/general/deploy/test_run_pipeline.py`(`test_instance_names`) · `tests/general/deploy/test_dc.py`(묶음 이름 `compose`·`compose-hong` · 틀린 이름·기본 포트·prd 종료 2) · `test_dc_init.py`(타이머 단위 이름 끝) · `test_compose.py`(컨테이너 이름 끝 `${NAME_SUFFIX:-}`) · 통과.
- Status: done

<a id="pl-21"></a>
## pl-21 · 은퇴한 설정 칸 지우기
- 규칙: 아래 칸을 지웠다 — 남아 있으면 시작 거부(칸 이름만 알림) — `common.paths.korean_font`·`eval_sets_dir`, `common.dev.exp_store`·`llm_est_in_tokens`·`llm_est_out_tokens`·`min_gold_coverage`, `common.runtime.exp_max_workers`·`exp_proc_gb_answer/build/run`·`exp_reserve_gb`, `common.models.llm.max_concurrency`, `pipeline.transform.structure.wiki_domain_phrase`, `pipeline.eval.diagram_raster_vlm`.
- QA: `tests/server/common/test_layout.py` · 통과.
- Status: done

<a id="pl-30"></a>
## pl-30 · 아무도 안 읽는 env 이름 4개
- 규칙: 코드·호스트 스크립트는 `FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`를 쓰지 않는다.
- QA: `grep -rn "FIG_OCR_BUDGET\|SERVICE_MASTER_CSV\|DIVISION_MASTER_CSV\|PROD_MASTER_CSV" --include=*.py --include=*.sh --include=*.yml .` · `docs/` 밖 0줄.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건 없는 코드 — 남길지 지울지
- 설정 CLI `common/config/`(`export`·`overrides`·`show`), DB 도구 `common/store/db/`, 점검 `common/check/checker.py`(env·services·ping).
