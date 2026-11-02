# 문서·릴리스

[PRD.md](../PRD.md)의 카테고리 하나 — 문서 배치와 릴리스 표시.
do-01~03의 출처: COMPANY 거버넌스 프로젝트별 검토, 10-29(임시 표준 — `agent-ops/docs/project-review.md#s_bio_data_parsing`).

순서(주제별): 문서 정리 do-04·do-02·do-03·do-01 → 릴리스 op-04 → 이미지 op-06·op-07 → 서버 설치·업그레이드 op-10.

<a id="do-04"></a>
## do-04 · 문서 재구성 · `docs/history/` · 한국어
- 이유(사용자 10-29/10-30): 겹치는 문서가 너무 많고 요건이 PRD 밖에 흩어져 있다.
- 무엇: 문서를 줄이고 짧게, 결정과 요건은 남김. 긴 문서는 소제목을 둔다. 사람이 읽는 문서는 한국어. `docs/history/`에 이력(refactor_plan, refactor.md의 낡은 C 항목 — C-35, C-41 합성 부분, C-63, C-05/06, C-18/20/22/23/24/26/28, C-25/30 — run_docs 버그·속도 이력, 패치 이력, 릴리스 §8–9)을 둔다. `docs/requirements/*`는 PRD로 옮긴다. CLAUDE.md에서 규칙이 아닌 내용은 PRD/README/INDEX로 옮긴다. PRD와 겹치는 C 항목(C-31/32/33/50/53/58)은 "PRD xx-nn으로 옮김" 한 줄과 남은 서버 확인만 남긴다. 크기 상한은 안내일 뿐.
- 1부(10-30): PRD를 카테고리로 — ID는 그대로, ID마다 한글 이름(`<a id>` + `## pl-24 · 이름`), `docs/PRD.md`와 `docs/prd/`를 카테고리 파일 6개(etl, parse, mcp, settings, test, doc)로 나누고 gaps.md는 각 파일 끝 "코드와 다른 점 · 지울 코드"로 흩음.
- 2부(10-30, `feature/doc-cleanup-2`): CLAUDE.md는 규칙·하네스 명령만(기준선·핑거프린트 값 → [test.md#e2-02](test.md#e2-02), 옛 절 번호 → `docs/INDEX.md` Glossary, 지난 기록 → `docs/history/`). `docs/requirements/run_docs_req.md` → [ops.md#pl-10](ops.md#pl-10) 요약 + `docs/history/run_docs_req.md` 원문. `docs/operations/*` 압축(절 번호 유지 — 코드 주석이 가리킴). `refactor_plan.md`·run_docs 버그·속도 이력·patch-history·release §8–9 → `docs/history/`.
- 결정(사용자 10-31 grill): 3부 카테고리 재편(etl·parse → extract·transform·load, settings·실행 관리 → ops — ID 그대로, 위치·링크만)은 열린 문서 브랜치(op-08, prd-grill-1031, gold-per-system)가 develop에 들어간 직후 한 PR로 한다. 새 행(op-08, pl-42·43·44)도 그때 배정한다. -3a의 pl-03은 그 뒤 rebase. CLAUDE.md §6-5 스모크 경로는 S5(10-30)로 이미 고침 — 확인 대기 아님.
- Status: dev — 1부 병합(PR #21). 2부는 `feature/doc-cleanup-2`. 3부(카테고리 재편) 11-01 `feature/do04-reorg` — etl·parse·settings → extract·transform(+ transform-cleanup)·load(+ load-schema)·ops(+ ops-settings), ID 그대로. CLAUDE.md §6-5(`list-smoke10`)는 사용자 확인 대기로 그대로.

<a id="do-02"></a>
## do-02 · `docs/INDEX.md`의 `## Glossary`
- 이유: 옛 용어(지문, 판, 칸 …)가 주석과 기록에 아직 나온다. 한곳에서 찾게 한다.
- 단계: CLAUDE.md의 "용어 대응" 블록을 `docs/INDEX.md` `## Glossary`로 옮기고, CLAUDE.md에는 링크 한 줄만 남긴다.
- 수용 기준: 옛 블록의 용어가 용어집에 한 번씩 나온다.
- 끝남 10-30(do-04 1부와 함께): `docs/INDEX.md` `## Glossary` — 약어·프로젝트 용어 + 옛 용어 대응. CLAUDE.md는 링크 한 줄.
- Status: done

<a id="do-03"></a>
## do-03 · `refactor.md`를 10-29 병합과 맞추기
- 이유: PR #4 교차 확인에서 낡은 줄이 나왔다.
- 고칠 것: C-35/C-39/C-41이 지운 `SYNTHETIC_TRUTH`/`PADDLE_PYTHON`/`PHASE_REPORT_LEGACY`를 아직 부름("10-29 지움, 옮기지 않음" 표시). "CLAUDE.md 3절" 링크 9개 → §4. 부록 1 HEAD 행 = CLAUDE.md §4 값. C 항목이 PRD 행을 가리키게(C-31 pl-26, C-52 pl-23, C-54 pl-12, C-60 pl-13, C-61 pl-17, C-56 e2-12, C-53 e2-14, C-33 pl-18, C-32 pl-19, C-50 pl-20). pl-21에서 `paddle_python`/`phase_report_legacy`를 뺌(8d211bf에서 이미 지움).
- 검토자 역할(사용자 10-29 grill): "engine-qa / be-qa"는 사람이 없는 역할 이름이었다. 등급 A 검토 = 사용자, Claude가 변경을 설명하는 grill-me 세션으로. refactor.md(8줄과 C 행)의 역할 이름을 바꾸고 CLAUDE.md §5-3에 그렇게 적는다.
- `valid_env/eval_sets/` 지움([ops-ops-settings.md#pl-21](ops-ops-settings.md#pl-21)) — CLAUDE.md §6-5(`list-smoke10.txt`), `valid_env/README.md`, `docs/prd/test.md`의 참조를 고친다.
- 또: CLAUDE.md §6-3 기준선을 다시 잰다(selftest 89/88, pytest 142/8 — 10-29에 시험 파일을 지움).
- 끝남 10-30(`feature/refactor-sync`, PR #20 병합): refactor.md 동기화(do-04의 refactor.md 몫 포함 — 옛 항목은 `docs/history/refactor_c_items.md`로). CLAUDE.md 몫(§5-3 검토자 줄·§6-3 기준선·§4 지문 줄·§6-5 `list-smoke10.txt`)은 사용자 확인 뒤 따로(다른 세션 요청만으로 CLAUDE.md를 고치지 않음).
- Status: done

<a id="do-01"></a>
## do-01 · 루트 `refactor.md`(184 KB)를 `docs/refactoring/`으로 옮기기
- 이유: 저장소 루트에는 입구 파일만 둬야 하고 검토가 요청했다.
- 단계: 사용자와 설계 확인 → 옮기기만 하는 커밋 하나 → 링크를 고치는 커밋 하나(`grep -rn "refactor.md"`: CLAUDE.md, README, docs/INDEX.md, 코드 주석).
- 여기서 안 함: `settings.sample.yaml`도 옮기라고 했지만 `common/config/sample.py`가 루트에 쓰고 `appcheck`, `setarg`, `migrate`, env-guide, CLAUDE.md가 그 경로를 읽는다 — settings-cleanup 작업·사용자 몫. 옮기면 code_fp가 바뀔 수 있다(CLAUDE.md §4).
- 기다림: feature/test-parallel과 feature/settings-cleanup 병합(둘 다 refactor.md와 CLAUDE.md를 고침).
- 수용 기준: 깨진 링크 없음(옛 경로 `grep` = 0), `selftest` 그대로.
- 끝남 10-30(`feature/do01-docs-batch`): `git mv refactor.md docs/refactoring/refactor.md`(옮기기만 하는 커밋) → 링크 고치는 커밋(CLAUDE.md, README, docs/index.md, release-and-patch, prd/test.md, history/refactor_c_items.md, 옮긴 파일 안의 상대 링크). 코드 주석의 `refactor.md C-xx`는 이름만 가리키므로 고치지 않음(code_fp). 저장소 전체 링크 점검 0건.
- Status: done

<a id="op-04"></a>
## op-04 · 첫 릴리스 태그 `v0.1.0`과 릴리스 노트
- 이유: `VERSION`과 이미지 태그는 있지만 태그나 릴리스 노트를 만든 적이 없다.
- 무엇: `release/0.1.0`에서 `main`에 태그, `RELEASE_NOTES`(변경, 채울 설정, 핑거프린트 변경, refactor.md "최종"의 서버 할 일)를 쓴다.
- 릴리스 노트 후보: MCP `search` 근거 출력의 `file_path` 키 제거 — [mcp.md#mc-16](mcp.md#mc-16)(사용자 10-30 PRD grill D1).
- 끝남 10-30: `main` 7910257에 태그 `v0.1.0`을 만들었다. 릴리스 노트는 GitHub release v0.1.0.
- Status: done

<a id="op-06"></a>
## op-06 · 실행 이미지(코드 없음) — 개발 서버는 코드 폴더를 마운트
- 결정(사용자 10-30): "이미지는 따로 만들어두고, 이미지 안에는 코드가 같이 묶여있으면 안돼. 코드는 지금 폴더 구조 그대로 넣어둘거야." 보완(10-30): 한 Dockerfile에서 두 갈래 — 개발 서버(폐쇄망)는 코드 없는 **실행 이미지**에 코드 폴더를 마운트, 수집 서버는 지금처럼 **코드가 든 이미지**.
- 무엇:
  - Dockerfile 타깃 `pipeline-runtime`·`mcp-runtime`(이미지 `data-pipeline-runtime`·`mcp-server-runtime`) = OS 패키지·LibreOffice·휠·assets/rapidocr 모델·사용자 10001·ENV만. 코드가 든 `pipeline`·`mcp`는 그 위에 코드 COPY만 얹음(`FROM <실행 이미지>` — 바탕·의존성이 어긋나지 않음).
  - 실행 이미지의 시작 스크립트 `deploy/docker/runtime_entry.sh`(이미지 안 `/app/docker/`): ① `/app/deploy`에 코드 폴더가 없으면 종료 2 ② 이미지 의존성 지문(`/app/docker/deps_hash`)과 코드가 선언한 `deploy/docker/DEPS_HASH`(`deploy/release/deps_hash.sh` — requirements-core·image의 sha256)가 다르면 종료 2 ③ 이미지 판(`/app/docker/image_ref`)·코드 커밋(`CODE_COMMIT`)을 한 줄 남기고 코드 폴더의 `deploy/docker/entrypoint.sh`로 넘김.
  - 코드 폴더 = 저장소 트리 그대로(`build_ship.sh`가 실행 이미지를 만들 때 이 커밋의 git 추적 파일 + `CODE_COMMIT`, `valid_env/`·`validation/` 뺌 — `code-<버전>-<커밋>.tar.gz`). `/app/deploy`에 읽기 전용(`:ro,z`)으로 — 이미지 안 경로·`common/core/paths.py`·핑거프린트는 그대로.
  - compose: 개발 서버는 `compose.pipeline.yml` + `compose.code.yml`(`compose.mcp.yml` + `compose.code.mcp.yml`) — 셸에 `CODE_DIR`가 있으면 `trigger.sh`·`run_tool.sh`·`mcp_up.sh`가 덧붙인다. 빠뜨리면 ①로 바로 멈춤. 수집 서버(코드가 든 이미지)는 지금 그대로.
  - zip 배치(사용자 10-30): 코드 git과 이미지 git(`jehunlee302/sbl_images`, 비공개 — 판 폴더마다 분할 조각 + `load.sh`)을 zip으로 받아 한 폴더에 푼다. 이미지가 `*-runtime` 태그인데 `CODE_DIR`가 비면 `trigger.sh`·`run_tool.sh`·`mcp_up.sh`가 자기 코드 폴더 루트를 마운트(`image_vars.sh` `code_dir_default`). 커밋 표시는 `CODE_COMMIT`(`export-subst` — zip·`git archive`가 채움). README §5-0.
  - 이미지 관문: 실행 이미지는 이 커밋의 코드 트리를 붙여 `selftest`(`[판정]`)·코드 없이 띄우면 멈추는지까지 본다. 시험 `tests/server/common/test_deps_hash.py`(DEPS_HASH ↔ requirements).
- 하지 않은 것: 설정 칸 추가 없음(공용 설정 파일을 고치면 code_fp가 바뀜 — `CODE_DIR`은 호스트 셸 env) · `pipeline_version()`은 그대로(코드 커밋은 시작 줄·`CODE_COMMIT`으로 남김 — 공용 파일을 고치면 핑거프린트가 바뀜).
- 파일: `deploy/docker/{Dockerfile,runtime_entry.sh,DEPS_HASH}`, `deploy/release/{build_ship.sh,image_names.sh,deps_hash.sh}`, `deploy/host/compose/compose.code{,.mcp}.yml`, `deploy/host/scripts/{trigger.sh,run_tool.sh,mcp_up.sh,run_docs.py}`, `tests/server/common/test_deps_hash.py`, README §5, `docs/operations/release-and-patch.md` §1-1.
- Status: done (10-30 `feature/code-free-image`)

<a id="op-07"></a>
## op-07 · 개발 → 운영 굽기 — 개발 서버에서 시험한 실행 이미지 + 코드 폴더 그대로
- 결정(사용자 10-30): 두 단계 — 로컬 → 개발은 실행 이미지 + 코드 폴더([op-06](#op-06)), 개발 → 운영은 폐쇄망 개발 서버에서 **개발에서 쓴 실행 이미지 그 판**과 **시험한 코드 폴더 그대로**를 운영용 이미지(코드 폴더 없이 뜸)로 굽는다. Dockerfile의 `pipeline`·`mcp` 타깃은 의존성 단계부터 다시 빌드(휠·apt 필요)라 이 용도에 안 맞음.
- 무엇:
  - `deploy/docker/Dockerfile.bake`: `ARG RUNTIME_IMAGE` → `FROM ${RUNTIME_IMAGE}` + 코드 COPY(Dockerfile의 `pipeline`·`mcp` 타깃과 같은 줄 — 같은 파일이 같은 자리에), ENTRYPOINT `/app/docker/entrypoint.sh`(마운트 확인 없음), 라벨 코드 커밋(`revision`)·실행 이미지 ID(`base.digest`). 패키지 설치·네트워크 없음(`--network=none`).
  - `deploy/release/bake.sh <실행 이미지 판> [pipeline mcp]`(개발 서버, podman 또는 docker): 코드 `DEPS_HASH` = 실행 이미지 지문 확인 → 빌드(문맥 = 코드 폴더) → `selftest_gate.sh`(`[판정] 통과`) → `ship_stage.sh`로 저장·gzip·95m 분할·sha256.
  - 같은지 확인: PC에서 실행 이미지로 구운 이미지와 Dockerfile `pipeline`·`mcp` 타깃의 `/app/deploy`·`/app/docker` 파일 목록·sha256 비교(10-30 — 같음: pipeline 352개·mcp 237개).
- 하지 않은 것: 설정 칸·코드 변경 없음(핑거프린트 그대로) · 운영 서버 반입 자동화 없음(조각 옮기기·load는 사람).
- 검토 반영(10-30): `ship_stage.sh` 저장 실패를 실패로(전에는 `if stage_one` 안이라 잘린 조각에 sha256을 만들고 성공으로 끝남) · 태그 = 코드 VERSION만(D-036) · 저장 기본 `/var/tmp/bake`(코드 폴더 밖) · 운영 서버 호스트 스크립트용으로 시험한 코드 폴더 묶음도 같이 저장(컨테이너엔 마운트 안 함).
- 같이 고친 것(허브 10-30): `build_ship.sh` 코드 묶음 기본 위치 `output/ship/`(옛 `/var/tmp`는 Windows Git Bash에 없음) · `ship_stage.sh`가 실행 이미지(`pipeline-runtime`·`mcp-runtime`)와 `CODE_BUNDLE`(코드 묶음 + sha256)도 받음 · README §5-0 배포 단계 표(사용자 10-30).
- 파일: `deploy/docker/Dockerfile.bake`, `deploy/release/{bake.sh,build_ship.sh,ship_stage.sh}`, `.gitattributes`, README §5-0, `docs/operations/release-and-patch.md` §1-1·§1-2, `docs/operations/server-guide.md` §0-1.
- Status: done (10-30 `feature/bake-image`)

<a id="op-10"></a>
## op-10 · 서버 설치·업그레이드 절차 — 길 하나, podman 기본, 0.2.0 업그레이드·되돌리기
- 이유(허브 전체 점검, 사용자 10-31): 설치 절차가 여러 문서에 흩어져 서로 다르고, 스크립트는 settings를 읽기 전에 docker를 기본으로 잡는다. 0.2.0은 DB·EDW·전체 재처리가 함께 바뀌는데 업그레이드·되돌리기 절차가 없다.
- 무엇:
  - 설치 길은 하나 — README §5-0·§5-3에만 쓰고, 다른 문서(server-guide·env-guide·release)는 거기로 링크한다.
  - 컨테이너 도구 기본은 podman(서버 기본 — CLAUDE.md §2).
  - 0.2.0 업그레이드·되돌리기 절차를 쓴다.
- 고칠 곳(허브 점검 10-31 — 줄 번호는 그날 기준):
  - settings를 읽기 전에 `DOCKER=docker`로 잡는 스크립트 5개 — `deploy/host/scripts/settings_env.sh:48`, `mcp_up.sh:12`, `run_tool.sh:20`, `trigger.sh:42`, `deploy/release/ship_stage.sh:21` → `$(command -v podman || echo docker)`.
  - `run_docs.py`에 `--code <dir>` 인자와 `DOCKER` 설정이 필요(지금은 맨 `docker exec`).
  - `deploy/host/compose/compose.pipeline.yml`의 `${INDEX_CONF_DIR:?}`가 모든 podman-compose 실행을 깨뜨림 — `index_a`/`index_b` 정리는 [load.md#pl-19](load.md#pl-19)와 함께.
  - `load.sh`가 저장소에 없고, `ship_stage.sh`의 저장소 이름·폴더 구조가 README와 다름.
  - README:439 앞에 `mkdir -p /srv/rag/code`가 필요.
  - env-guide의 check_env 명령 → `run_tool.sh`로.
  - `NIGHTLY_PUBLISH` 0/1 어긋남 — [load.md#pl-26](load.md#pl-26)이 이 칸을 지운다(링크만).
  - 재부팅 대비 `podman-restart.service`, parse 서비스 keepalive.
  - podman-compose 폐쇄망 설치가 문서에 없음.
- 0.2.0 업그레이드에 넣을 것: 이미지 안 `migrate` + `chown 10001`·권한 640(settings.yaml), 되돌리기는 `settings.yaml.0.1.0` 복원, DB 백업 → `migrate check` → `up`, 전체 재처리 시간·디스크 계획, 그동안 밤 타이머 멈춤.
- 파일: `README.md` §5, `docs/operations/{server-guide,env-guide}.md`, `deploy/host/scripts/`, `deploy/host/compose/`, `deploy/host/systemd/`, `deploy/release/ship_stage.sh`.
- 한 것(10-31·11-01 `feature/op10-server-install`):
  - `DOCKER`: 셸 env > settings.yaml `ops.host.docker` > podman > docker(`settings_env.sh` `docker_default` — 설정을 읽은 뒤 정함). `mcp_up.sh`가 설정 전에 docker로 못 박던 것 지움. `ship_stage.sh`·`load.sh`도 podman 우선.
  - `run_docs.py`: `--code <dir>`(설정 배치 모듈 찾기 — 기본 이 스크립트의 코드 폴더, 없으면 `/srv/rag/code/live`) · `docker exec`·`inspect` 12곳이 `ops.host.docker`를 따름.
  - `index_a`·`index_b` → `deploy/host/compose/compose.index.yml`(쓸 때만 덧붙임 — [pl-19](load.md#pl-19)에서 지움) — `INDEX_CONF_DIR` 없이 compose가 돎.
  - `deploy/release/load.sh` 커밋 · `ship_stage.sh`가 이미지 저장소 배치 하나(`sbl_images/load.sh` · `<판>/BUILD.txt` · `<판>/<이미지>/` 45MB 조각) — 개발·운영(bake) 같은 배치.
  - 문서: README §5-0·§5-2·§5-3·§5-5(설치 길 하나 · `mkdir -p /srv/rag/code` · podman-compose 폐쇄망 설치 · `podman-restart` · 상주 트리거 재부팅 뒤 확인), server-guide·env-guide·release-and-patch는 링크, release-and-patch §5-7 0.2.0 올리기·되돌리기(이미지 안 migrate 표준 입력·출력 — PC에서 확인), refactor.md C-71.
  - 남김: 상주 파싱 서비스 전용 keepalive 타이머는 만들지 않음(재부팅은 `podman-restart`, 그 뒤 확인 절차만) · `NIGHTLY_PUBLISH`는 [pl-26](load.md#pl-26) 몫.
- Status: done (11-01, feature/op10-server-install)
