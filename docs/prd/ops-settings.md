# 운영 — 설정(settings.yaml·RUN_ENV)

[PRD.md](../PRD.md) 카테고리. [ops.md](ops.md)의 하위 문서. 실행 환경 `RUN_ENV`(op-02), settings.yaml 하나(op-05)·배치(op-08)·하드코딩 0(op-09), 지운 칸(pl-21·pl-30). 전체 칸과 기본값: `settings.sample.yaml`(생성: `python -m common.config.sample`).

순서: op-02 · op-05 · op-08 · op-09 · op-14 · pl-21 · pl-30 · op-18.

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
  2. `python -m common.config.sample`이 모든 칸을 실제 YAML로 낸다. 절 순서 [op-08](#op-08), 절 안은 카테고리 제목 주석(`# ---- … ----` — `required.models` 안은 모델마다 작은 제목). 값 자리 = 코드 기본값. 칸마다 줄 끝 주석 한 줄 — 필수 칸은 `[필수 · 언제(어느 앱)]`(언제 = 모두·local·dev·prd, 앱 = pipeline·mcp·호스트 스크립트 — `layout.REQUIRED_GROUPS` 칸마다 조건), 그 밖 `[선택]`, 짧은 설명과 허용값 또는 예, 비밀은 `[비밀]`. 설명은 `sample.NOTES` 한 표(칸이 빠지면 sample이 멈춤).
  3. sample에서 사람이 꼭 적을 `[필수]` 칸(비워 두면 그 모드에서 시작 거부나 기능 실패 — `layout.NEED`가 "필수")은 **빈 칸**(`pg_host:` 뒤가 비어 있음, 주석에 예)으로 낸다. 비워 두면 코드 기본값·계산값·끔이 되는 칸은 `null`로 낸다 — 기본 없음·비밀·빈 글자·이미지 기본값 칸(이미지·PC 값이 다름)·적었는지로 동작이 갈리는 칸(`sample.SET_MATTERS` — `PIPE_PROCS`·`PIPE_THREADS`·`PM_BUCKET`)·저장소 경로가 든 기본값. 읽을 때는 빈 칸·`null`이 같다(앱 설정·호스트 `settings_to_env.py`·`load_settings.sh`·`host_ctl.sh init`·`run_pipeline.py` 모두 비움). sample을 그대로 복사해 빈 칸만 채우면 시작된다(`tests/server/common/test_sample_copy.py`).
  4. settings.yaml에 적힌 값이 코드 기본값보다 이긴다. 비운 칸은 코드 기본값.
  5. 설정 값은 code_fp에 들어가지 않는다 — 값을 바꿔도 자동 재처리는 없다.
  6. 옛 env 이름·판정 꼴은 `python -m common.config.sample --where <이름>`.
  7. `null`로 내는 선택 칸의 주석은 "null = …"(비운 동작)을 적는다. 적힌 기본값 = 코드가 읽는 기본값(`tests/server/common/test_sample_yaml.py`가 대조).
  8. PC 전용 칸(외부 모델 허용·예상 비용·단가·지출 상한, 로컬 대체 DB, 시험 하네스)은 맨 아래 `dev` 절에 모은다(`layout.LOCAL`). 서버 settings.yaml에는 두지 않는다. local 전용 값(가짜 EDW·게시 폴더·원본 폴더·새 문서 상한)은 `dev.local` 묶음(sample 제목 `# ---- local(PC) 전용 … ----`)에 모은다 — op-14.
  9. 게시(silver)·EDW 칸은 `required` 한곳에 — `publish`(`publish_bucket`·`publish_prefix`)·`object_storage`(`object_storage_endpoint`·`object_storage_access_key`·`object_storage_secret_key`)·`edw`(`edw_host`·`edw_port`·`edw_database`·`edw_read_*`). 서버(dev·prd)가 채우는 칸이고 local은 무시한다(op-14). 기본값이 있는 칸(`edw_port`·`pg_schema` `data_parsing`)은 비우면 코드 기본값 — 서버(dev·prd)에서 `pg_schema`를 비우면 칸 자리와 쓰는 기본값을 경고 한 줄로 알린다(`pg.conf`). EDW 계정은 읽기 계정 하나다(EDW는 읽기만 — op-17 · 쓰기 계정 칸은 없다).
  10. 칸(잎) 이름은 파일 전체에서 하나뿐이고 절 경로 없이도 뜻이 보인다 — 역할을 이름 앞에 붙인다(`pg_host`·`edw_host`, `embed_base_url`·`llm_base_url`·`vlm_base_url`, run_pipeline 덮기 칸은 `batch_`, parse MCP 작업 서비스 칸은 `mcp_parse_`). 줄임은 흔한 것만(pg·edw·mcp·vlm·llm·ocr·cpu). 세 모델의 접속 칸은 `required.models` 한 곳에 모델마다 묶는다. 시험 `tests/server/common/test_leaf_names.py`가 지킨다.
  11. 칸 주석은 100자 안팎, 허용값 또는 예를 하나 넣는다 — 켜기·고른 글자·숫자 칸은 sample이 꼴(`true·false`·값 목록·`정수`·`숫자`)을 붙인다.
  12. 모드마다 꼭 채울 칸: local = `run_env`·모델 접속(`embed_base_url`·`embed_model`·`llm_base_url`·`llm_model`·`vlm_base_url`·`vlm_model`)·PG(접속 5칸 — 모두 비우면 sqlite 대역). dev·prd = 그 위에 PG 접속 5칸·EDW(`edw_host`·`edw_database`·`edw_read_user`·`edw_read_password`)·`publish_bucket`·Object Storage 3칸·토큰(`mcp_token`·원문 도구를 쓰면 `fulltext_sign_key`)·배포 4칸(`pipeline_image`·`mcp_image`·`host_docs_dir`·`pg_container_name`). sample 칸 주석의 `[필수 · …]`가 이 표와 같다.
- 메모(사용자 11-04 — 칸 줄이기): 읽는 곳이 없거나 겹치는 칸을 지웠다 — `secure_doc.password`, `pg.conn_file`, `ops.paths.output_root`(공용), `transport.ping_timeout`(점검기 상수 60초), EDW 원천 표의 선택 열(`bucket`·`company`·`doc_type`·`etag` 등 10개)과 `company`·`doc_type` 거르기, `structure.embed`(`gold_bundle --embed` 기본 api), publish `parse_date`·`path_map`, `server.instructions`, `search.min_score`, `search.pg.vector_search`, `edw_query.tables`·`tables_strict`, `gold_dir` 두 칸(op-11). 옛 파일에 남으면 시작 거부(rn-07). `search.server.fulltext_secret`은 `required.tokens.fulltext_sign_key`로 옮겼다. 남긴 칸과 이유: `tuning.ops.runtime.glossary_lock_timeout_sec`(용어 초안 잠금 — 핸드오프 파일이 읽음), `llm_price_in_usd_per_mtok`·`llm_price_out_usd_per_mtok`(가격표에 없는 모델), `extract.max_new_docs_per_run`(명령 기본값), `publish_upload_statuses`, `load.stored_path_prefix`, `search.edw_meta.edw_meta_catalog_dir`(mc-07).
- 파일: `common/config/{sample,settings,keyscan,layout}.py`, `pipeline/config.py`, `mcp_server/config.py`, `settings.sample.yaml`.
- QA: `python -m common.config.sample --check` · sample이 설정 모델과 같음. `tests/server/common/test_sample_yaml.py`(복사한 sample로 서버 STRICT 시작 · 적힌 값 = 코드 기본값)·`test_leaf_names.py`(잎 이름 하나씩)·`test_sample_copy.py`(복사 뒤 빈 칸만 채워 시작 — local은 run_env·모델만, local에 적힌 서버 칸은 비우고 경고, dev는 pg_schema 비우면 data_parsing + 경고 · local 가짜 EDW 사본) · 통과.
- Status: done

<a id="op-08"></a>
## op-08 · 설정 배치 — 필수 묶음 + 역할별 파라미터 + tuning
- 이유: 운영자가 꼭 넣을 값을 맨 위에 모으고 나머지를 역할별로 나눈다.
- 규칙:
  1. 최상위 절 순서: `required` → `common` · `extract` · `transform` · `load` · `search`(MCP 검색) · `ops`(실행 자원·스케줄·서비스·서버 컨테이너·경로) — 역할 절에는 환경마다 운영자가 정하는 값(주소·TLS·포트·경로·상한·서버 크기에 맞춘 병렬 수·기능 스위치·호스트 스크립트와 `run_pipeline.py --set`이 쓰는 칸)만 → `tuning`(거의 안 바꾸는 값 — 결과 파라미터·내부 제한 시간·대기열·자원 세부값, 사용자 11-04: 코드로 내리지 않고 sample 아래쪽에 공통·추출·변환·적재·검색·로그·실행 자원·새벽 배치·상주 서비스 분류 제목으로, 비우면 코드 기본값) → `dev`(PC 전용 — 외부 모델·로컬 대체 DB·시험 하네스, op-05 8).
  2. `required` = 운영자가 꼭 정할 값(연결 주소·계정·비밀·게시 위치·이미지 태그) — `env`·`pg`·`embed`·`edw`·`publish`·`object_storage`·`models`·`source`·`tokens`·`deploy`. 카테고리 제목에 `[PC·서버]`·`[서버만]`·`[PC만]`.
  3. 파일 자리 ↔ 설정 모델 경로(`common.*`·`pipeline.*`·`mcp.*`)의 표는 `common/config/layout.py` 하나. `read_settings`가 파일을 모델 배치로 바꿔 읽는다.
  4. 옛 배치 파일(최상위 앱 절)은 시작 거부. 모델에 있는 칸을 다른 자리에 쓰면 "자리가 다른 칸 … → 새 자리"로, 모델에 없는 칸(지운 칸·오타)은 "모르는 칸 …"으로 거부한다 — 칸 이름만 알리고 값은 안 찍는다. 옛 자리를 읽어 주는 표·옮기는 도구는 없다(rn-07 — 사용자 11-05).
  5. 11-04 합친 칸: `extract.prefetch_workers` → `extract.source.source_fetch_threads`, `tuning.ops.nightly_run.workers` → `ops.runtime.vlm_parallel_docs`.
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
  4. 호스트 스크립트는 `load_settings.sh`(`settings_to_env.py` — PyYAML만)가 내준 값만 쓴다. 컨테이너 명령 = settings.yaml `ops.host.container_cli` > podman > docker(`run_pipeline.py`와 같게, rn-07).
  5. 앱은 env에서 설정을 읽지 않는다 — 남은 env 줄은 분류 주석 필수(`python -m common.check.check_modules` ⑩·⑪).
- 파일: `common/config/settings.py`(`IMAGE_PATHS`), `common/config/keyscan.py`, `deploy/release/gen_host_keys.py`, `deploy/host/scripts/{load_settings.sh,settings_to_env.py,host_settings.tsv}`.
- QA: `python -m common.check.check_modules` · "모듈 경계 통과". `tests/general/deploy/test_host_env.py` · 통과. 서버 확인 refactor.md C-70.
- Status: done

<a id="op-14"></a>
## op-14 · PC는 가짜 대상만 — 서버 전용 칸은 무시, 저장소 기준 상대 경로
- 이유: PC에서 전체 흐름을 가짜 대상(sqlite EDW, 폴더 Object Storage)으로만 돌린다. PC 시험에 EDW·Object Storage·토큰·배포 값이 필요 없어야 하고, 서버 값을 적어 둔 파일로도 실제 EDW·Object Storage에 닿을 수 없어야 한다(사용자 11-05).
- 규칙:
  1. local 전용 값은 `dev.local` 한 묶음 — `local_edw_sqlite_file`(비우면 `valid_env/edw/edw_copy.sqlite` — 없으면 git의 `valid_env/edw/edw.sqlite`를 복사해 만들고 원본에는 쓰지 않음 — 여러 프로세스가 같이 만들어도 먼저 생긴 사본을 덮지 않음, `mssql.standin_path`), `local_publish_dir`(기본 `valid_env/object_storage/Parsing_Result` — 폴더 경로, 처음 게시할 때 만듦), `local_source_dir`(기본 `valid_env/object_storage` — `source_input_location`·`--source`가 없을 때 파싱 원본), `local_max_new_docs_per_run`(기본 5 — `max_new_docs_per_run`·`--max-new`가 없을 때). `valid_env`에 생기는 것은 이 둘(가짜 EDW 사본·게시 폴더)뿐이고 `.gitignore`가 뺀다. 원본 폴더 목록은 게시 폴더와 맨 위 설명 파일(`*.md`)을 원본으로 읽지 않는다(`candidate_pick._tree_files`).
  2. local은 서버 전용 칸을 무시한다 — `required.edw.edw_host`·`edw_read_*`, `required.object_storage.*` 3칸, 원천 버킷(`extract.source.source_default_bucket`), 서버 게시 버킷 `required.publish.publish_bucket`(`settings.LOCAL_IGNORED` 한 곳). 설정 파일·덮기 파일(`--set` 포함)에 적혀 있어도 설정 객체에서 비우고 경고 한 줄에 칸 자리만 찍는다(값 없음). 시작은 거부하지 않는다. 게시는 늘 `local_publish_dir`(`file://`로 바꿔 씀). 비우기는 `run_env`가 `local`로 정해진 뒤에만 한다 — `run_env`를 안 적으면 앱 시작 관문이 거부하고, 관문을 거치지 않는 느슨한 읽기(`load(strict=False)`)는 이 비우기 대상이 아니다.
  3. 경로 칸 — `dev.local.*` 폴더·파일, `ops.paths.source_docs_dir`·`prepared_docs_dir`, `extract.source.source_input_location`(폴더·`rdb:csv:<경로>`), `dev.pg_standin.pg_standin_dir` — 는 상대 경로를 저장소 루트(`paths.PROJ_ROOT`) 기준으로 푼다(`settings.repo_path` 한 곳). 절대 경로·`s3://`·버킷 이름은 바꾸지 않는다.
  4. `dev`·`prd`는 바뀌지 않는다 — 서버 칸을 그대로 쓰고 `dev.local` 값은 읽지 않으며, 가짜 EDW 파일을 적으면 거부(작업 폴더 `/app` = `PROJ_ROOT`라 상대 경로 결과도 같다).
  5. local은 Object Storage(S3)에 접속하지 않는다 — 모든 S3 접속이 거치는 `common.store.objectstore.client()`가 local이면 거부한다(칸을 비워도 boto3 기본값으로 실제 S3에 닿을 수 있어서 — `rdb:csv`의 `s3://` 원천도 여기서 멈춤).
- 파일: `common/config/settings.py`, `common/config/layout.py`, `common/config/sample.py`, `pipeline/config.py`, `common/store/mssql.py`, `common/store/objectstore.py`, `pipeline/extract/candidate_pick.py`, `.gitignore`.
- QA: `tests/server/common/test_pc_targets.py`(상대 sqlite · 절대 경로 · local 서버 게시 버킷·EDW 주소 무시 + 경고 · dev 그대로 · local S3 접속 거부) · `test_sample_copy.py`(run_env·모델만으로 시작 · 가짜 EDW 사본 · 서버 칸 비움 · 덮기 파일로 준 `LOCAL_IGNORED` 전 칸 비움 + 경고) · `tests/server/pipeline/test_local_src.py`(게시 폴더·설명 파일은 원본 아님) · 통과.
- Status: done

<a id="op-15"></a>
## op-15 · 한 서버에 여러 벌(개발자별) — 벌 번호는 폴더 이름, 포트는 설정으로
- 이유(사용자 11-04): 개발 서버에 개발자마다 컨테이너를 따로 띄운다. 컨테이너 이름(`data-pipeline` 등)·compose 묶음 이름·systemd 타이머 이름이 고정이라 두 번째 벌이 첫 벌을 덮었다. 벌 번호를 폴더 이름에서 읽어 설정 칸 없이 나눈다(사용자 11-06).
- 규칙:
  1. 벌 폴더(코드 폴더 = 루트) 하나 = 한 벌. 벌 번호 = 코드 폴더 이름 끝 `-<숫자>`(예 `sbl_data_parsing-main-2` → `2`) — 있으면 컨테이너 3개·compose 묶음(`compose-<번호>`)·systemd 단위 4개 이름 끝에 `-<번호>`. 없으면(`sbl_data_parsing-main`·`sbl_data_parsing-0.3.0`) 이름 그대로(한 벌). 벌 이름 설정 칸은 없다(`ops.host.instance_name`이 남으면 모르는 칸으로 시작 거부).
  2. 번호를 구하는 곳은 `load_settings.sh load_settings`(`INSTANCE`·`NAME_SUFFIX`) 한 곳, 호스트 스크립트(`host_ctl.sh`·`mcp_keepalive.sh`·`nightly_batch.sh`·`pipe_exec.sh`)와 compose 파일은 그 값을 쓴다. `run_pipeline.py`는 같은 규칙(`instance_of`)으로 `configure()`에서.
  3. PG 스키마·EDW 기록 표·게시 경로·버전에는 벌 표시를 붙이지 않는다 — 모든 벌이 같은 기준 스키마를 함께 쓰므로 모든 벌이 같은 코드 판이어야 한다(벌끼리 데이터를 나누는 길은 [op-17](ops.md#op-17)).
  4. 포트 두 칸(`search.server.mcp_port` · `ops.services.data_parsing.data_parsing_port` — 작업 서비스와 검색 MCP가 같은 칸)은 벌마다 다르게 — 번호가 붙은 벌인데 기본값이면 시작 거부. `prd`에서 번호가 붙은 폴더면 시작 거부(종료 2). 거부는 `load_settings.sh`·`run_pipeline.py configure()` 둘 — server-guide §1-3.
- 파일: `deploy/host/scripts/{load_settings.sh,host_ctl.sh,mcp_keepalive.sh,nightly_batch.sh,pipe_exec.sh,run_pipeline.py}` · `deploy/host/compose/compose.{pipeline,data-parsing,mcp-server}.yml` · README §5-0 "한 서버에 여러 벌".
- QA: `tests/general/deploy/test_dc.py`(묶음 이름 `compose`·`compose-2` · 판 번호 폴더 `sbl_data_parsing-0.3.0`은 한 벌 · 기본 포트·prd 종료 2) · `test_dc_init.py`(루트 = 코드 폴더 · 타이머 단위 이름 끝) · `test_run_pipeline.py::test_instance_names` · `test_compose.py`(컨테이너 이름 끝 `${NAME_SUFFIX:-}`) · 통과.
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

<a id="op-18"></a>
## op-18 · 안 읽는 설정 칸 없음 · 덮어쓰기는 `--set` 하나
- 요건: 지운 칸은 upgrade-guide에 적는다(서버 `settings.yaml`에 남으면 모르는 칸으로 시작 거부). 한 번만 다른 값은 모든 진입점(`mcp_server.main`·`ask` 포함)의 `--set` 하나다(PC 덮기 파일 도구 없음).
- 반영: 지운 칸 — `extract.skipped_docs_log`(건너뜀 기록은 늘 `<준비 폴더>/_records/skipped.jsonl`) · `extract.secure_doc.secure_doc_passwords_file` · `tuning.extract.source_columns.source_column_content_version` · 구성 파일 `retrieve`·`k`. 남긴 칸 — `extract.source.source_fetch_threads`(`candidate_ready` 받기 스레드)·`ops.run_pipeline.staging.staging_fetch_threads`(서버 러너가 넘김)·`source_column_increment`(증분 판정). 서버에서 지울 줄: [upgrade-guide §5](../operations/upgrade-guide.md#5-설정-고치기) · C-110. 덮기 파일 도구 `common.config.overrides`를 지웠다 — `mcp_server.main`·`mcp_server.cli.search_ask`가 `--set`을 받는다(시험 `tests/server/mcp/test_mcp_setarg.py`).
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건 없는 코드 — 남길지 지울지
- 설정 CLI `common/config/`(`export`·`setarg`·`show`), DB 도구 `common/store/db/`, 점검 `common/check/checker.py`(env·services·ping).
