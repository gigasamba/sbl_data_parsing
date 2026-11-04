# 운영 — 설정(settings.yaml·RUN_ENV)

[PRD.md](../PRD.md) 카테고리. [ops.md](ops.md)의 하위 문서. 실행 환경 `RUN_ENV`(op-02), settings.yaml 하나(op-05)·배치(op-08)·하드코딩 0(op-09), 지운 칸(pl-21·pl-30). 전체 칸과 기본값: `settings.sample.yaml`(생성: `python -m common.config.sample`).

순서: op-02 · op-05 · op-08 · op-09 · op-14 · pl-21 · pl-30.

<a id="op-02"></a>
## op-02 · RUN_ENV는 `local`·`dev`·`prd` 셋 · 가짜 LLM은 `local`에서만
- 이유: 서버에서 외부 모델이나 가짜 답이 돌면 안 된다.
- 규칙:
  1. `required.env.run_env`는 모든 곳에서 필수(기본값 없음) — `local`(PC)·`dev`(개발 서버)·`prd`(운영). 다른 값(`stage` 포함)은 시작 거부, 메시지에 세 값을 보인다.
  2. 외부 모델과 `dev.llm_fake`는 `local`에서만. `dev`·`prd`에서 `llm_fake`가 켜져 있으면 앱 시작에서 거부(`require_run_env` 관문 — 0이 아닌 종료 코드).
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
  2. `python -m common.config.sample`이 모든 칸을 코드 기본값과 함께 실제 YAML로 낸다. 절 순서 [op-08](#op-08), 절 안은 카테고리 제목 주석(`# ─── … ───`), 칸마다 줄 끝 주석 한 줄(설명·기본값·값). 결과를 바꾸는 칸은 `[파라미터]`, 비밀은 `[비밀]`.
  3. sample에서 비우는 칸: 필수·비밀·기본 없음·빈 글자·이미지 기본값 칸(이미지·PC 값이 다름)·적었는지로 동작이 갈리는 칸(`sample.SET_MATTERS`)·저장소 경로가 든 기본값.
  4. settings.yaml에 적힌 값이 코드 기본값보다 이긴다. 비운 칸은 코드 기본값.
  5. 설정 값은 code_fp에 들어가지 않는다 — 값을 바꿔도 자동 재처리는 없다.
  6. 옛 env 이름·판정 꼴은 `python -m common.config.sample --where <이름>`.
  7. 필수가 아닌 칸의 주석은 "비우면 …"(코드 기본값 또는 비운 동작)을 적고, 뜻이 바로 안 보이는 칸은 "예: …"를 붙인다. 기본값도 비운 동작도 없는 칸이 있으면 sample이 멈춘다(`sample.BLANK`·`sample.EXAMPLES`).
  8. PC 전용 칸(외부 모델 허용·예상 비용·단가·지출 상한, 로컬 대체 DB, `pg_create_extension`, 시험 하네스)은 맨 아래 `dev` 절에 모은다(`layout.LOCAL`). 서버 settings.yaml에는 두지 않는다. 예외: PC 가짜 EDW `required.edw.sqlite`는 게시·EDW 칸과 함께 `required`에 둔다(9).
  9. 게시(silver)·EDW 칸은 `required` 한곳에 — `publish`(`bucket`·`prefix`)·`object_storage`(`endpoint`·`region`·`access_key`·`secret_key`·`verify_tls`)·`edw`(`parsing_meta_table`·`host`·`port`·`database`·`read_*`·`write_*`·`sqlite`). 칸 주석에 "서버: … · PC(local): …"로 환경마다 넣을 값을 적는다(`sample.REQ_NOTES`) — PC는 게시 버킷 `file://<폴더 절대 경로>`와 `sqlite`만, 서버는 접속 칸. 기본값이 있는 칸(`region`·`verify_tls`·`port`·`parsing_meta_table`)은 비우면 코드 기본값.
- 메모(사용자 11-04 — 칸 줄이기): 읽는 곳이 없거나 겹치는 칸을 지웠다 — `secure_doc.password`, `pg.conn_file`, `ops.paths.output_root`(공용), `transport.ping_timeout`(점검기 상수 60초), EDW 원천 표의 선택 열(`bucket`·`company`·`doc_type`·`etag` 등 10개)과 `company`·`doc_type` 거르기, `structure.embed`(`build_bundle --embed` 기본 api), publish `parse_date`·`path_map`, `server.instructions`, `search.min_score`, `search.pg.vector_search`, `edw_query.tables`·`tables_strict`, `gold_dir` 두 칸(op-11). 옛 파일에 남으면 경고만(`layout.REMOVED`). `search.server.fulltext_secret`은 `required.tokens.fulltext`로 옮겼다. 남긴 칸과 이유: `search.parse_proxy.url`(검색 MCP는 파이프라인 절의 포트를 못 읽음), `ops.mcp_host.jobs_dir`(호스트 스크립트가 읽는 호스트 경로), `bucket_skip_overlap_check`(`run_docs.py`가 켬), `draft_terms_*`(용어 초안 — 핸드오프 파일이 읽음), `price_in`·`price_out`(가격표에 없는 모델), `max_new`·`source_limit`(명령 기본값), `upload_statuses`, `edw_path_prefix`, `search.edw_meta.dir`(mc-07).
- 파일: `common/config/{sample,settings,keyscan,layout}.py`, `pipeline/config.py`, `mcp_server/config.py`, `settings.sample.yaml`.
- QA: `python -m common.config.sample --check` · sample이 설정 모델과 같음. `tests/server/common/test_sample_yaml.py`(복사한 sample로 서버 STRICT 시작 · 적힌 값 = 코드 기본값) · 통과.
- Status: done

<a id="op-08"></a>
## op-08 · 설정 배치 — 필수 묶음 + 역할별 파라미터 + tuning
- 이유: 운영자가 꼭 넣을 값을 맨 위에 모으고 나머지를 역할별로 나눈다.
- 규칙:
  1. 최상위 절 순서: `required` → `common` · `extract` · `transform` · `load` · `search`(MCP 검색) · `ops`(실행 자원·스케줄·서비스·서버 컨테이너·경로) — 역할 절에는 환경마다 운영자가 정하는 값(주소·TLS·포트·경로·상한·서버 크기에 맞춘 병렬 수·기능 스위치·호스트 스크립트와 `run_docs.py --set`이 쓰는 칸)만 → `tuning`(거의 안 바꾸는 값 — 결과 파라미터·내부 제한 시간·대기열·자원 세부값, 사용자 11-04: 코드로 내리지 않고 sample 아래쪽에 공통·추출·변환·적재·검색·로그·실행 자원·새벽 배치·상주 서비스 분류 제목으로, 비우면 코드 기본값) → `dev`(PC 전용 — 외부 모델·로컬 대체 DB·시험 하네스, op-05 8).
  2. `required` = 운영자가 꼭 정할 값(연결 주소·계정·비밀·게시 위치·이미지 태그) — `env`·`pg`·`embed`·`edw`·`publish`·`object_storage`·`models`·`source`·`tokens`·`deploy`. 카테고리 제목에 `[PC·서버]`·`[서버만]`·`[PC만]`.
  3. 파일 자리 ↔ 설정 모델 경로(`common.*`·`pipeline.*`·`mcp.*`)의 표는 `common/config/layout.py` 하나. `read_settings`가 파일을 모델 배치로 바꿔 읽는다.
  4. 옛 배치 파일은 시작 거부 + migrate 안내. 자리가 다른 칸은 "자리가 다른 칸 … → 새 자리"로 거부. 예외: 11-04에 옮긴 칸(PC 전용 칸의 역할 절 자리, `search.server.fulltext_secret`, 역할 절에서 `tuning`으로 옮긴 53칸 `layout.TUNING_RARE`, `required`로 옮긴 게시·EDW 칸 — `layout.TO_REQUIRED`의 역할 절 자리와 `layout.ALIASES`의 `required.source.publish_*`·`dev.connections.rdb.sqlite`)은 옛 자리도 읽고 "옛 자리 칸 읽음 … 로 옮길 것" 한 줄을 낸다(`layout.MOVED`, 값은 출력 안 함).
  5. 지운 칸(`layout.REMOVED`)이 남아 있으면 경고 한 줄만(시작은 함) — `dev`·`tuning` 안 옛 자리에 있어도 같다. 11-04 합친 칸: `extract.prefetch_workers` → `extract.source.fetch_workers`, `tuning.ops.nightly_run.workers` → `ops.runtime.pipe_workers`.
  6. `python -m common.config.migrate <옛 settings.yaml> --out <새 파일>` = 옛 배치 → 새 배치(값은 글자 그대로, 지운 칸은 "삭제됨"). `.yaml`·`.yml` 파일 하나만 받는다(다르면 종료 2). 서버 절차 [release-and-patch.md §8](../operations/release-and-patch.md#8-020-배포--사람이-할-일).
- 파일: `common/config/{layout,settings,sample,keyscan,migrate,export}.py`, `pipeline/config.py`, `mcp_server/config.py`.
- QA: `python -m common.config.keyscan --check` · 빠진 키 0개. `tests/server/common/test_removed_cols.py`·`test_layout.py` · 통과.
- Status: done

<a id="op-09"></a>
## op-09 · 하드코딩 0 — 설정 값은 settings.yaml 또는 이미지 기본값 표에서만
- 이유: 경로·포트·주소가 여러 곳에 복사되면 한 곳만 바뀌어 어긋난다.
- 규칙:
  1. 설정 값은 settings.yaml(코드 기본값은 설정 모델에 한 번) 또는 이미지 기본값 표 `common/config/settings.py` `IMAGE_PATHS` 하나에서만 온다. 저장소 안 경로는 `common/core/paths.py` 상수로만.
  2. 환경마다 다른 경로·접속(게시 대상·Object Storage·EDW·PG·호스트 경로)은 필수 — 코드 기본값이 없고 비면 시작 거부. PG 자동 찾기는 없다.
  3. 컨테이너 안 경로(`output_root` `/app/output` · `code_root` `/app/deploy` 등)는 `IMAGE_PATHS`가 원본이다. `deploy/release/hostkeys.py`가 이 표를 `deploy/host/scripts/host_keys.tsv`(`image.<이름>`·`APP_<이름>` 줄)로 내고, `settings_env.sh`가 `APP_*` env로 내준다 — compose는 `${APP_OUTPUT_ROOT}`·`${APP_CODE_ROOT}`·`${APP_DOCS_MOUNT}`, `run_docs.py`는 코드 폴더의 표를 읽는다. 생성: `PYTHONPATH=. python deploy/release/hostkeys.py`.
  4. 호스트 스크립트는 `settings_env.sh`(`host_env.py` — PyYAML만)가 내준 값만 쓴다. 컨테이너 명령 = 셸 env `DOCKER` > settings.yaml `ops.host.docker` > podman > docker.
  5. 앱은 env에서 설정을 읽지 않는다 — 남은 env 줄은 분류 주석 필수(`python -m common.check.check_modules` ⑩·⑪).
- 파일: `common/config/settings.py`(`IMAGE_PATHS`), `common/config/keyscan.py`, `deploy/release/hostkeys.py`, `deploy/host/scripts/{settings_env.sh,host_env.py,host_keys.tsv}`.
- QA: `python -m common.check.check_modules` · "모듈 경계 통과". `tests/general/deploy/test_host_env.py` · 통과. 서버 확인 refactor.md C-70.
- Status: done

<a id="op-14"></a>
## op-14 · PC는 가짜 대상만 — 저장소 기준 상대 경로
- 이유: 나중에 PC에서 전체 흐름을 가짜 대상(sqlite EDW, 폴더 Object Storage)으로만 돌린다. 저장소 위치가 PC마다 달라 절대 경로를 적기 번거롭다.
- 규칙:
  1. 경로 칸 — `required.edw.sqlite`(`common.connections.rdb.sqlite`), `required.publish.bucket`의 `file://` 꼴, `common.paths.doc_dir`·`doc_dir_prepared`, `pipeline.extract.input_source`(폴더·`rdb:csv:<경로>`), `common.connections.pg.standin_dir` — 는 상대 경로를 저장소 루트(`paths.PROJ_ROOT`) 기준으로 푼다. 푸는 곳은 설정 모델 한 곳(`settings.repo_path` — 칸 표시 `F(repo=…)`)이라 읽는 코드는 그대로다. 절대 경로·`s3://`·버킷 이름은 바꾸지 않는다.
  2. 가짜/실제 판정은 `settings.pc_real_targets` 한 곳. `local`에서 `required.edw.host`, `required.object_storage.endpoint`, 원천 버킷(`pipeline.connections.rdb.bucket`), `file://`가 아닌 게시 버킷이 적혀 있으면 시작 관문(`require_run_env`)이 칸 이름과 예시를 찍고 종료 코드 2.
  3. `dev`·`prd`는 바뀌지 않는다(작업 폴더 `/app` = `PROJ_ROOT`라 상대 경로 결과도 같다).
- 파일: `common/config/settings.py`, `pipeline/config.py`, `common/config/sample.py`.
- QA: `tests/server/common/test_pc_targets.py`(상대 sqlite · 상대 `file://` 버킷 · 절대 경로 · local 실제 호스트 거부 · dev 실제 호스트 허용) · 통과.
- Status: done

<a id="pl-21"></a>
## pl-21 · 은퇴한 설정 칸 지우기
- 규칙: 아래 칸은 지운 칸 목록(`layout.REMOVED`)에 있어 남아 있으면 경고만 한다 — `common.paths.korean_font`·`eval_sets_dir`, `common.dev.exp_store`·`llm_est_in_tokens`·`llm_est_out_tokens`·`min_gold_coverage`, `common.runtime.exp_max_workers`·`exp_proc_gb_answer/build/run`·`exp_reserve_gb`, `common.models.llm.max_concurrency`, `pipeline.transform.structure.wiki_domain_phrase`, `pipeline.eval.diagram_raster_vlm`.
- QA: `tests/server/common/test_removed_cols.py` · 통과.
- Status: done

<a id="pl-30"></a>
## pl-30 · 아무도 안 읽는 env 이름 4개
- 규칙: 코드·호스트 스크립트는 `FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`를 쓰지 않는다.
- QA: `grep -rn "FIG_OCR_BUDGET\|SERVICE_MASTER_CSV\|DIVISION_MASTER_CSV\|PROD_MASTER_CSV" --include=*.py --include=*.sh --include=*.yml .` · `docs/` 밖 0줄.
- Status: done

## 코드와 다른 점 · 지울 코드

### 요건 없는 코드 — 남길지 지울지
- 설정 CLI `common/config/`(`export`·`overrides`·`show`), DB 도구 `common/store/db/`, 점검 `common/check/checker.py`(env·services·ping).
