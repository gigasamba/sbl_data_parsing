# 운영 — 설정(settings.yaml·RUN_ENV)

[PRD.md](../PRD.md) 카테고리. [ops.md](ops.md)의 하위 문서. 실행 환경 `RUN_ENV`(op-02), settings.yaml 하나(op-05)·구조 재편(op-08)·하드코딩 0(op-09), 미룬 설정 정리(pl-21·pl-30).
항목마다 무엇·왜·관련 파일. 끝나지 않은 항목은 `Status:` 줄에 진행 상황을 적는다.

순서: op-02 · op-05 · op-08 · op-09 · pl-21 · pl-30.

<a id="op-02"></a>
## op-02 · RUN_ENV는 `local`·`dev`·`prd` 셋(`stage` 없앰) · LLM_FAKE는 `local`에서만
- 무엇: `local`(PC), `dev`(개발 서버), `prd`(운영). `stage`는 없앤다.
- 이유: `stage`는 `prd`와 똑같이 동작했다(실행 기록에만 적힘). 허브가 방식 수를 줄이자고 했다(10-29). LLM_FAKE에는 RUN_ENV 확인이 없어 서버에서 가짜 답이 돌 수 있었다.
- 결정(사용자, grill-me 10-29):
  1. `local`을 PC 신호로 유지(저장소 루트 settings.yaml 찾기, 파일 기반 스택·원천, `paths.LOCAL_RUN`) — 새 설정도, 코드 위치 규칙도 없음.
  2. 외부 모델(OpenRouter 등)과 `LLM_FAKE`는 **`local`에서만** 허용. `dev`와 `prd`는 둘 다 거부.
  3. `dev`/`prd`에서 `LLM_FAKE`가 켜져 있으면 앱 시작에서 거부(`require_run_env` 관문), 호출마다가 아님.
  4. `stage`는 더는 받지 않는다: `local`·`dev`·`prd`만 받고, `stage`는 모르는 값처럼 거부(시작 거부, 메시지에 세 값을 보임).
  5. RUN_ENV는 모든 곳에서(PC 포함) 필수 — 기본값 없음.
- 따라 나온 것(질문 불필요): RUN_ENV 없는 명령(이미지 안 `selftest`, 점검 명령)은 앱 시작이 아니라 시험 사례에서 LLM_FAKE로 계속 동작. PC Docker 스모크(`valid_env/docker/compose.test.yml`)는 `RUN_ENV: local` 유지. 외부 모델 규칙 `external_models_allowed` = `local`만(그대로).
- 파일: `common/config/settings.py`(RUN_ENVS, SERVER_ENVS, run_env Literal, stage 대응, 시작 관문), `common/ai/llm.py`(시작 관문이 덮으면 그대로), `common/config/{migrate,keyscan,overrides,setarg}.py`, `deploy/host/compose/*.yml` 글, `deploy/host/scripts/settings_env.sh`, `deploy/docker/entrypoint.sh`, 문서(CLAUDE.md §3, README §3, env-guide, refactor.md), `settings.sample.yaml` 다시 만들기, 시험.
- 서버 할 일: `run_env: stage`인 서버 `settings.yaml`은 이 릴리스 전에 `prd`로 바꾼다(env-guide 행).
- 위험: `common/config/settings.py`는 모든 레이어의 code_fp에 들어간다 → 서버 재처리. 핑거프린트 전후를 기록. settings.py 변경은 작게(92와 r2-phase도 고침).
- 수용 기준: `RUN_ENV=stage`는 시작 거부(모르는 값). `RUN_ENV=dev`/`prd` + `LLM_FAKE=1`이면 앱 시작이 0이 아닌 코드로 끝남. `local` + `LLM_FAKE=1`은 시작. 외부 모델은 dev/prd에서 거부, local에서 허용. 이미지 안 selftest 통과. 전체 pytest + 린트 통과.
- Status: done (10-30, PR #6 병합 — 사용자 승인) — 서버 할 일은 refactor.md C-66.

<a id="op-05"></a>
## op-05 · settings.yaml 하나 — sample에 모든 키·기본값을 카테고리별로
- 결정(사용자 10-30): "resources/config로 분리하지 말고 그냥 하나의 settings.yaml로 관리하고, 아래 option, default 값 넣고, 카테고리 분류해서 넣으면 될 것 같아. 주석처리도 다 해제하고."
- 무엇:
  - `resources/config` 파라미터 파일은 만들지 않는다. 설정은 settings.yaml 하나에 모두 둔다.
  - `settings.sample.yaml` §2(옵션)·§3(파라미터)를 주석이 아닌 실제 YAML로 쓴다 — 모든 키를 기본값과 함께 섹션(`common`·`pipeline`·`mcp`) 아래에 넣고, 지금 2-1·2-2 … 묶음처럼 카테고리 제목 블록으로 묶는다. 설명·선택지·옛 env 이름은 줄 끝 주석으로 남긴다.
  - 서버·PC의 settings.yaml = sample을 복사해 필수값·비밀값을 채운 것.
  - 모델 연결 정보(모델별 값 — `common.models.embed.query_prefix`, `llm.extra_body`, `vlm.extra_body`)도 그 연결 블록과 함께 settings.yaml에 둔다.
- 결과(알아 둘 것): settings.yaml에 적힌 값이 코드 기본값보다 이긴다. 나중에 코드 기본값을 바꿔도 settings.yaml(또는 sample을 다시 복사)을 고치지 않으면 반영되지 않는다. "키는 한 곳에만" 규칙은 이제 settings.yaml 안에서만의 뜻이다.
- 핑거프린트: 설정 값은 code_fp에 들어가지 않는다 — 값을 바꿔도 자동 재처리는 없고, 필요하면 사람이 재처리한다(10-30 결정 그대로).
- 파일: `common/config/sample.py`(생성기), `settings.sample.yaml`, `common/config/{settings,keyscan}.py`, `pipeline/config.py`, `mcp_server/config.py`, `docs/operations/env-guide.md`.
- Status: done (10-30 · 파일 배치는 [op-08](#op-08)로 대체 — 10-31) — `python -m common.config.sample`이 모든 칸을 코드 기본값과 함께 `common`·`pipeline`·`mcp` 아래 카테고리 순서(제목 주석 `─── N. … ───`)로 낸다. 비우는 칸: 필수·비밀·기본 없음·빈 글자·이미지 기본값 칸(DOC_DIR 등 — 이미지·PC 값이 다름)·적었는지로 동작이 갈리는 칸(`sample.SET_MATTERS`)·핑거프린트 칸(pinned — 적으면 `pin_env`가 env로 내어 자식 프로세스 설정을 덮음). 결과를 바꾸는 칸은 `[파라미터]` 표시. 시험: `tests/server/common/test_sample_yaml.py`(복사한 sample로 서버 STRICT 시작 · 적힌 값 = 코드 기본값), `appcheck`(sample 파일 대조).

<a id="op-08"></a>
## op-08 · 설정 구조 재편 — 필수 묶음 + 역할별 파라미터
- 이유(사용자 10-30): `settings.sample.yaml`(칸 약 443개)과 실제 쓰는 settings.yaml(필수만 모은 40여 줄)의 차이가 너무 크다. 필수 입력은 맨 위에 카테고리별로 모으고, 나머지는 역할별 파라미터로 나누고, 칸 수도 줄인다.
- 결정(사용자 10-30 grill):
  - 칸 경로를 바꾼다(보기만 정리하지 않음) — YAML은 같은 절을 두 번 쓰면 뒤가 앞을 덮으므로, 필수 묶음은 별도 최상위 절 `required`로 둔다.
  - 구조: 맨 위 `required`(필수 입력만 — 실행 환경 · PG(gold) · EDW · Object Storage · 모델 연결·키 · 서버 이미지 등, 카테고리마다 구분선과 `[PC·서버]`·`[서버만]`·`[PC만]` 표시를 칸마다가 아니라 카테고리 제목에 한 번) → 구분선 → 파라미터 절 7개 `common`·`extract`·`transform`·`load`·`search`(MCP 검색)·`ops`(실행 자원·스케줄·서비스·서버 컨테이너·경로)·`dev`(PC·시험·평가 전용).
  - 필수 = 운영자가 꼭 넣어야 하는 값(기본값이 쓸 수 없는 연결 주소·계정·비밀·이미지 태그). 기본값이 있으면 필수가 아니라 파라미터(예: EDW 포트 1433, Object Storage 리전).
  - 설명은 짧게(한 줄) — 옛 env 이름·판정 꼴 같은 내부 표시는 sample에서 뺀다(필요하면 env-guide).
  - 사용처가 없는 칸·뜻이 겹치는 칸은 코드에서 지운다(고정값이면 코드 상수로). 지울 목록은 지우기 전에 사용자 확인.
  - 시점: 0.2.0에 함께 — 설정 모델 파일은 모든 레이어의 code_fp에 들어가 서버 전체 재처리가 생기므로, 전체 재적재가 있는 gold 원천별 스키마(pl-28)와 한 번에 묶는다.
- 조사(10-30, 칸 443개): 필수 42(PC·서버 11, 서버만 31) · 파라미터 281 · 경로 49 · PC·시험 전용 61 · 사용처 없음 8 · 중복 2.
- 결정(사용자 10-30 2차):
  - 지운다(10개): `common.paths.criteria_file`(코드 상수 사용) · `pipeline.load.publish.source_system`(코드 고정값) · `mcp.search.ocr_dpi`(읽는 곳 없음) · `common.paths.config_dir`(셸은 `$SERVER_ENV_DIR`) · `pipeline.eval.e2e_qa_set`·`e2e_questions`(형식 점검만) · `common.dev.docker.postgres_db`·`postgres_user`(compose는 `PG_DB`·`PG_USER`) · 중복 `mcp.server.query_cache` → `common.models.embed.query_cache`, `pipeline.transform.structure.edw_embed` → `structure.embed`로 합침.
  - 켜기·끄기 스위치(약 40개)는 세분 카테고리로 모아 목록으로 보여 준다 — 기능이 없어진 스위치는 지운다. 파라미터 절의 카테고리는 더 세분해도 된다.
  - 운영 값(대기 시간·작업자 수·자원 한도·상한 등)은 파라미터로 두되, 기본값 말고 다른 값을 쓴 흔적이 없는 것을 "코드 상수 후보"로 추려 보여 준다.
- 조사(10-30, 켜기·끄기 스위치 91개): 기능 없어짐 0 · 되돌리기 전용(기본 켬, 끄면 옛 동작) 51 · 실험·기본 끔 27 · 양쪽 다 쓰임 13. 운영 값 254개 중 기본값 외 값을 쓴 흔적 없음 = 코드 상수 후보 103.
- 결정(사용자 10-30 3차):
  - 되돌리기 전용 스위치는 스위치와 옛 동작 코드를 지우고 항상 켠다. 단 엔진·핸드오프 지문 파일 안의 5개(`pipeline.extract.fill_merged`·`kreuzberg_prose_filter`·`ocr.table_grid`, `common.text.search_en_stem`·`token_num_norm`)는 재파싱을 피하려고 남기고 다음 엔진 개정 때 정리한다.
  - 쓰지 않는 실험 기능(기본 끔)은 기능째 지운다 — 목록은 지우기 전에 확인. 운영·보안 선택(고객 하드 격리, 표 허용 목록, 외부 허용, 가짜 LLM 등)과 run_docs가 실제로 켜는 칸(`qa_light`, `bucket_skip_overlap_check`)은 파라미터로 남긴다.
- 결정(사용자 10-30 4차):
  - 코드 상수 후보는 바로 지우지 않고 sample 맨 아래 별도 절(구분선)에 모은다 — 내부 조정값 32개(재시도·내부 대기·묶음 크기·출력 상한 등)와 자원·대기·병렬 세부값 약 20개(자동 계산 내부 계수 `mem_*`·`pipe_max_procs`·`pipe_proc_gb`·`pipe_reserve_*`·`pipe_threads`·`cpu_max_load`, `llm.timeout`·`embed.timeout`·`attach.timeout`·`vlm.deadline`, `vlm.page_concurrency`·`page_min_concurrency`·`figures.vlm_parallel`·`night.vlm_concurrency`·`night.workers`·`parse_mcp.procs`). 상수로 내릴지는 그 절을 보고 나중에 정한다.
  - 프로세스 수·메모리는 필수 입력이 아니다 — 비우면 CPU·메모리로 자동 계산. 역할 절에 남기는 자원 칸: `pipe_procs`·`pipe_workers`·`vlm.max_concurrency`·`llm.rpm`, 새벽 배치 시각·마감, run_docs 레인 워커 수, 컨테이너 CPU·메모리 한도, 내부망 주소 범위.
  - 엔진 지문 파일이 읽는 `vlm.retry`·`vlm.timeout`도 다음 엔진 개정 때 정리한다.
  - 서버 settings.yaml은 `python -m common.config.migrate`가 옛 경로 → 새 경로로 바꿔 준다(지운 칸은 "삭제됨"으로 알림).
- 결정(사용자 10-30 5차 — 설계 확인): 지울 칸 68개 목록대로 진행(A 사용처 없음·중복 10 · B 되돌리기 스위치 45 · C 스트리밍 6 · D 실험 7 · E `embed.dim` 1). `represent.table_db`는 "항상 켬"이 아니라 기능째 지운다(정형 저장소 `doc_table`·`doc_cell`은 D-7로 0.2.0에 없어짐). 원칙: 스위치를 지울 때 그 스위치가 고르던 다른 길(옛 동작·옵션 기능) 코드도 함께 지운다 — 나중에 켜기·끄기가 필요하면 새 기능으로 다시 넣는다.
- 열린 질문: 없음.
- 진행: ① 칸·기능 삭제 커밋 → ② 경로 재편(`required`·역할 절·`tuning`) + migrate 변환 + sample 생성기 → ③ 문서(env-guide, README 설정 예시).
  - ①(10-30): 지운 칸은 옛 설정 파일에 남아 있으면 경고만(`REMOVED`). 검색 MCP 질의 캐시 기본(`/tmp/mcp_query_cache.sqlite`)은 mcp 이미지의 `common.models.embed.query_cache` 기본값. 첨부 임시 폴더 `attach_dir`는 `represent/attachments.py`(PARSE_TMP의 형제 `attach/`).
  - ②(10-31): 칸 자리 재편 — 새 모듈 `common/config/layout.py`(파일 자리 ↔ 모델 경로 표: `required` 41칸 · 역할 절 접두어 규칙 · `tuning` 58칸 = 내부 조정값 38 + 자원·대기·병렬 20). 설정 모델 경로(`common.*`·`pipeline.*`·`mcp.*`)는 그대로 두고 `read_settings`가 파일을 모델 배치로 바꿔 읽음(`export --section`·`data=`는 모델 경로). 옛 배치는 시작 거부 + migrate 안내, 자리가 다른 칸은 "자리가 다른 칸 … → 새 자리"로 거부. `migrate <옛 settings.yaml> --out <새 파일>` = 새 배치로 변환(값은 쓴 글자 그대로, 지운 칸은 "삭제됨"). 쓰는 곳 없는 6칸 지움(`parse_tmp_max_gb`·`parse_keep_max_gb`·`disk_free_warn_gb`·`engine_cache_warn_gb`·`shadow_max`·`agg.llm_min` — `REMOVED` 경고만). sample 주석 한 줄(설명·기본값·값) — 옛 env 이름·판정 꼴은 `python -m common.config.sample --where 이름`. 호스트 `run_docs.py`도 새 배치를 읽음. 칸 수 374 → 368(required 41 · common 44 · extract 54 · transform 26 · load 7 · search 30 · ops 73 · dev 35 · tuning 58). 문서(③): env-guide·README §4-2·서버 가이드 갱신(옛 서버 값 표는 env-guide로).
- 파일: `common/config/{layout,settings,sample,keyscan,migrate,export}.py`, `pipeline/config.py`, `mcp_server/config.py`, `settings.sample.yaml`, `deploy/host/`(설정 꺼내 쓰는 셸), `docs/operations/env-guide.md`.
- 결정(사용자 10-31 grill): tuning 절은 지금대로 — 운영 정책 값 6개(prepare.link·publish.upload_statuses·load.edw_path_prefix·mcp.server.instructions·search.pg.vector_search·trigger.upload_max_mb)는 역할 절, 내부 제한 시간·대기열 13개는 tuning. 옛 배치는 계속 거부한다. PC 루트 settings.yaml은 10-31에 `settings.yaml.bak-20261031`로 백업했고 op-08 병합 직후 migrate로 새 배치로 바꾼다. 서버 2곳 변환은 0.2.0 배포 절차(refactor.md)에 넣는다.
- 결정(사용자 11-02 — 운영 서버는 0.1.0, settings.yaml 하나): `common.config.migrate`는 옛 배치 settings.yaml → 새 배치(①)만 남긴다. `migrate`는 `.yaml`·`.yml` 파일 하나만 받는다(다른 파일이면 종료 2). 서버 절차: [release-and-patch.md §8](../operations/release-and-patch.md#8-020-배포--사람이-할-일).
- Status: done (11-01, PR #75 병합)

<a id="op-09"></a>
## op-09 · 하드코딩 0 — 설정 값은 settings.yaml 또는 이미지 기본값 표 하나에서만
- 이유(허브 전체 점검, 사용자 10-31): 서버 경로·포트·주소·모델 이름이 코드·호스트 스크립트·compose·systemd 여러 곳에 복사돼 있고, env를 직접 읽는 줄이 남아 있다. 한 곳을 바꾸면 나머지가 어긋난다.
- 규칙: 설정 값은 settings.yaml(코드 기본값은 설정 모델에 한 번) 또는 이미지 기본값 표(`common/config/settings.py` — D-029) 하나에서만 온다. 호스트 스크립트는 `settings_env.sh`가 내준 값만 쓴다. 저장소 안 경로는 `common/core/paths.py` 상수로만.
- 결정(사용자 10-31): 핑거프린트 보호 파일도 0.2.0에서 고친다 — 엔진 파일과 `common/core/{contract,terms,text}.py`의 env 직접 읽기(약 49곳), `paths.py` 밖 `Path(__file__).parents[n]`(34곳). 0.2.0은 어차피 전부 다시 처리한다. 검토 등급 A(엔진·핸드오프 핑거프린트 — 사람 검토).
- 결정(사용자 10-31): PG 자동 찾기를 지운다 — `docker ps`로 pgvector 찾기, 대체 포트, 코드 기본값 `127.0.0.1`/`5432`/`rag`. PG 접속 정보는 필수이고(서버), 비어 있으면 시작을 거부한다. 검색은 PG 하나([mc-01](mcp.md#mc-01)) — 로컬 묶음으로 조용히 바꿔 타지 않는다.
- 고칠 곳(허브 점검 10-31 — 줄 번호는 그날 기준):
  - `/srv/rag/code/live`가 15곳에 복사됨 — `deploy/host/scripts/mcp_up.sh:15`, `run_docs.py:141`, systemd unit.
  - `SERVER_ENV_DIR` 기본 `/srv/rag/env`가 4곳 — `settings_env.sh:54` 하나만 기본값으로 남긴다.
  - PG 기본값·자동 찾기 — `common/store/pg.py:37-41`, `common/store/pg.py`(`detect_pg`·`connect` — 0.2.0에 services.py에서 옮김), `pipeline/cli.py:854`(위 결정).
  - MCP 호스트·포트·주소 중복 — `mcp_server/main.py:104/192`, `mcp_server/cli/mcp_smoke.py:54`, `validation/search_ui/serve.py:32/119`.
  - soffice 경로 추측 — `pipeline/transform/figures/pptx_render.py:63-69` → PATH와 `SOFFICE_BIN`만(§2).
  - `deploy/docker/entrypoint.sh`의 `${DOC_DIR:-/data/docs}` 같은 기본값 → `${…:?}`(이미지 기본값 표가 넘김).
  - `/etc/rag/settings.yaml`이 `IMAGE_PATHS`(이미지 기본값 표)에 없음.
  - `CODE_DIR`에 설정 키가 없음.
  - `keyscan` 빠진 키 7개 — `APP_VERSION`·`BAKE_TEST`·`CODE_BUNDLE`·`CODE_DIR`·`CODE_OUT`·`VCS_REF`는 빌드 인자 → 빌드 인자로 표시, `NF`는 awk 오탐.
  - systemd `User=root` — 그대로 둘지 확인.
- 파일: 위 목록, `common/config/settings.py`(이미지 기본값 표), `common/config/keyscan.py`, `deploy/host/`, `pipeline/extract/engines/`(등급 A), `common/core/`.
- 결정(사용자 11-02): 환경마다 다른 경로·접속(게시 대상·Object Storage·EDW·PG·호스트 경로)은 settings.yaml 필수 — 코드 기본값 없음(비면 시작 거부). todo(정리 3b): 컨테이너 안 경로는 이미지 기본값 표(`common/config/settings.py`) 한 곳만 원본으로 — `run_docs.py`·compose·셸이 그 표를 읽고, 다른 곳의 `/app/output`·`/app/deploy` 글자는 없앤다.
- 한 것(11-02 `feature/image-paths` — 등급 A: 공용 `settings.py`를 고쳐 code_fp가 바뀜): ① `settings.IMAGE_PATHS`에 `output_root`(`/app/output`)·`code_root`(`/app/deploy`)를 더하고 `prepared_out`은 그 아래로 만든다. ② `deploy/release/hostkeys.py`가 이 표를 `deploy/host/scripts/host_keys.tsv`의 고정값 줄(`image.<이름>`·`APP_<이름>`)로 내고, `settings_env.sh` load_settings가 `APP_*` env로 낸다 — compose는 컨테이너 쪽 자리를 `${APP_OUTPUT_ROOT}`·`${APP_CODE_ROOT}`·`${APP_DOCS_MOUNT}`로 쓰고, `run_docs.py`는 코드 폴더의 표를 읽는다(`_img` — 명령 글자는 그대로, 시험 `test_run_docs`). ③ `run_docs.py`의 기본 코드 폴더(`/srv/rag/code/live`)를 지움(`--code` 또는 코드 폴더 안에서). 남김: 이미지 쪽(`Dockerfile`·`entrypoint.sh`·`runtime_entry.sh`·`build_ship.sh`)의 `/app/…` 글자 — 이미지 배치를 정하는 쪽이라 그대로, 설명 주석의 경로 글자도 그대로.
- Status: done (11-01, PR #77 병합 — stage 1·2a·2b).

<a id="pl-21"></a>
## pl-21 · 미룬 설정 지우기(핑거프린트)
- 이유: 안 쓰거나 은퇴한 설정인데 지우면 핑거프린트가 바뀌어 다음 이미지 판을 기다린다: `common.paths.korean_font`(settings.py → 모든 레이어 code_fp).
- 또(사용자 10-29 grill): `common.paths.eval_sets_dir` / `paths.EVAL_SETS_DIR`(과 `tests/server/common/test_paths.py`의 사례)을 지운다 — 읽는 곳은 `validation/e2e/stack_matrix.py`뿐(옛 묶음, [test.md#e2-10](test.md#e2-10)). 폴더 `valid_env/eval_sets/`는 그 문서 참조와 함께 [doc.md#do-03](doc.md#do-03)에서 지운다(그 파일을 읽는 코드 없음). 평가 자료는 나중에 `tests/` 아래로 돌아올 수 있다.
- 파일: `common/config/settings.py`, `pipeline/config.py`, `pipeline/extract/run_all.py`, `common/core/paths.py`.
- Status: done (10-30, `feature/fp-batch`) — 칸 지움(`Section.REMOVED` — 남아 있어도 경고만): `common.paths.korean_font`·`eval_sets_dir`(+ 상수 `paths.EVAL_SETS_DIR`), `common.dev.exp_store`·`llm_est_in_tokens`·`llm_est_out_tokens`·`min_gold_coverage`, `common.runtime.exp_max_workers`·`exp_proc_gb_answer/build/run`·`exp_reserve_gb`(+ `resources.plan_experiment`·`resolve_workers`·`resolve_inner_workers` — 쓰던 `stack_matrix`가 지워짐), 읽는 코드가 지워진 `common.models.llm.max_concurrency`(`LLM_MAX_CONCURRENCY`)·`pipeline.transform.structure.wiki_domain_phrase`·`pipeline.eval.diagram_raster_vlm`. 핑거프린트 바뀜(0.1.0 배치).

<a id="pl-30"></a>
## pl-30 · 아무도 안 읽는 env 이름 4개 지우기
- 이유: `FIG_OCR_BUDGET`, `SERVICE_MASTER_CSV`, `DIVISION_MASTER_CSV`, `PROD_MASTER_CSV`가 서버 env 파일에 있지만 읽는 코드가 없다(C-51).
- 결정(사용자 10-30 grill): 0.1.0 릴리스에서 지운다(핑거프린트가 바뀌는 다른 항목과 함께).
- 파일: 서버 env·settings 예시, `common/config/`(설정이나 별칭이 있으면), `refactor.md` C-51.
- Status: done (10-30, `feature/fp-batch`) — `deploy/host/scripts/run_docs.py`의 `UNREAD_PARSE_ENV`·`UNREAD_STRUCT_ENV`(4개 이름)를 명령에서 뺌, 시험 기대 명령도. 핑거프린트 그대로(호스트 스크립트).

## 코드와 다른 점 · 지울 코드

### 요건 없는 코드 — 남길지 지울지([test.md#e2-18](test.md#e2-18))
- 공용 도구 — 설정 CLI `common/config/`, DB 도구 `common/store/db/`, 점검 `common/check/checker.py`(env·services·ping — 0.2.0 합침), `common/check/`.

전체 스위치와 기본값: `settings.sample.yaml` 2부, "[기능 켬/끔]" 묶음.
