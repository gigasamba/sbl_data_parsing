# 문서·릴리스

[PRD.md](../PRD.md)의 카테고리 하나 — 문서 배치, 버전, 이미지, 서버 설치.

순서: 문서 do-04·do-02·do-03·do-01 → 버전 op-04 → 이미지 op-06·op-07·op-12 → 서버 설치 op-10·op-11.

<a id="do-04"></a>
## do-04 · 문서 배치와 언어
- 규칙: 사람이 읽는 문서는 한국어. 기능 요건은 [PRD.md](../PRD.md)와 `docs/prd/<카테고리>.md`(extract·transform·transform-cleanup·load·load-schema·mcp·ops·ops-settings·test·doc)에만 — ID는 바꾸지 않는다. 카테고리 파일 끝에 "코드와 다른 점 · 지울 코드". 지난 기록은 `docs/history/`(보관만). CLAUDE.md는 규칙·하네스 명령만. 문서 지도는 [INDEX.md](../INDEX.md).
- Status: done

<a id="do-02"></a>
## do-02 · `docs/INDEX.md`의 `## Glossary`
- 규칙: 약어·프로젝트 용어는 [INDEX.md](../INDEX.md#glossary) 한 곳. CLAUDE.md는 링크 한 줄.
- Status: done

<a id="do-03"></a>
## do-03 · `refactor.md`는 열린 서버·사람 확인만
- 규칙: [refactor.md](../refactoring/refactor.md)에는 저장소 안에서 끝낼 수 없는 확인(C-xx) 중 열린 것만, 무엇을 돌리고 무엇이 통과인지로 적는다. 끝난 항목은 지운다(이력은 git). 등급 A 검토자 = 사용자.
- Status: done

<a id="do-01"></a>
## do-01 · `refactor.md` 자리
- 규칙: `docs/refactoring/refactor.md`(저장소 루트에는 입구 파일만). 코드 주석의 `refactor.md C-xx`는 이름만 가리킨다.
- Status: done

<a id="op-04"></a>
## op-04 · 버전과 릴리스 태그
- 규칙: 버전은 저장소 루트 `VERSION` 하나(SemVer, 지금 `0.1.0`) — 두 이미지와 DB 버전 표기(`common.pipeline_version()`)가 함께 쓴다. `release/<버전>`에서 올리고 `main`에 태그 `v<버전>` + GitHub release 노트. 1.0.0 전에는 MCP 계약·DB 스키마가 깨져도 MINOR.
- Status: done

<a id="op-06"></a>
## op-06 · 실행 이미지(코드 없음) — 개발 서버는 코드 폴더를 마운트
- 이유: 이미지와 코드를 따로 반입한다 — 코드만 바뀌면 코드 폴더만 바꾼다.
- 규칙:
  1. Dockerfile 타깃 `pipeline-runtime`·`mcp-runtime`(이미지 `data-pipeline-runtime`·`mcp-server-runtime`) = OS 패키지·LibreOffice·휠·`assets/` 모델·사용자 10001·ENV만. 코드가 든 `pipeline`·`mcp`는 그 위에 코드 COPY만 얹는다.
  2. 실행 이미지 시작 `deploy/docker/runtime_entry.sh`: ① `/app/deploy`에 코드 폴더가 없으면 종료 2 ② 이미지 의존성 지문(`/app/docker/deps_hash`) ≠ 코드의 `deploy/docker/DEPS_HASH`(`deploy/release/deps_hash.sh` — requirements-core·image의 sha256)면 종료 2 ③ 이미지 판·코드 커밋(`CODE_COMMIT`)을 한 줄 남기고 코드 폴더의 `deploy/docker/entrypoint.sh`로 넘긴다.
  3. 코드 폴더 묶음 = 이 커밋의 git 추적 파일 + `CODE_COMMIT`, `valid_env/`·`validation/` 뺌 — `build_ship.sh`가 `output/ship/code-<버전>-<커밋>.tar.gz`로 만든다. `/app/deploy`에 읽기 전용(`:ro,z`)으로 붙인다.
  4. compose는 컨테이너마다 파일 하나 — `compose.pipeline.yml`·`compose.pipeline-mcp.yml`·`compose.mcp-server.yml`, 개발 서버는 각각 `compose.code.yml`·`compose.code.pipeline-mcp.yml`·`compose.code.mcp-server.yml`을 덧붙인다(셸에 `CODE_DIR`가 있거나, 이미지가 `*-runtime`이고 `CODE_DIR`가 비면 자기 코드 폴더 — `image_vars.sh` `code_dir_default`).
  5. 반입: 코드 git과 이미지 git(`sbl_images` — 판 폴더마다 분할 조각 + `load.sh`)을 zip으로 받아 한 폴더에 푼다. README §5-0.
- 파일: `deploy/docker/{Dockerfile,runtime_entry.sh,DEPS_HASH}`, `deploy/release/{build_ship.sh,deps_hash.sh}`, `deploy/host/compose/`, `deploy/host/scripts/image_vars.sh`.
- QA: `tests/server/common/test_deps_hash.py`(DEPS_HASH ↔ requirements) · 통과. 실행 이미지에 코드 트리를 붙여 `selftest` `[판정]` 통과 · 코드 없이 띄우면 종료 2.
- Status: done

<a id="op-07"></a>
## op-07 · 개발 → 운영 굽기
- 이유: 운영에는 개발 서버에서 시험한 실행 이미지 그 판과 코드 폴더를 그대로 굽는다.
- 규칙:
  1. `deploy/docker/Dockerfile.bake`: `FROM ${RUNTIME_IMAGE}` + 코드 COPY(Dockerfile `pipeline`·`mcp` 타깃과 같은 자리), ENTRYPOINT `/app/docker/entrypoint.sh`, 라벨 코드 커밋(`revision`)·실행 이미지 ID(`base.digest`). 패키지 설치·네트워크 없음.
  2. `bash deploy/release/bake.sh <실행 이미지 판> [pipeline mcp]`(개발 서버): ① 코드 `DEPS_HASH` = 실행 이미지 지문 ② 빌드(문맥 = 코드 폴더) ③ `selftest_gate.sh` `[판정] 통과` ④ `ship_stage.sh`로 저장·gzip·45m 조각·sha256 → `$OUT/sbl_images/<TAG>/<이미지>/` + `load.sh`·`BUILD.txt` + 시험한 코드 폴더 묶음. 태그 = 코드 `VERSION`(다르면 멈춤). `OUT` 기본 `/var/tmp/bake`. 컨테이너 도구 기본 podman.
  3. 구운 이미지 파일·조각에 비밀(settings.yaml)이 들면 비밀과 같이 다룬다 — 운영 서버와 권한 있는 반입 경로에만, 키를 바꾸면 다시 굽고 옛 이미지·조각을 지운다, 이미지 이력·`inspect`·시작 로그에 값이 안 보이는지 본다, 굽는 데 쓴 사본은 지운다([op-12](#op-12)).
- 파일: `deploy/docker/Dockerfile.bake`, `deploy/release/{bake.sh,ship_stage.sh,load.sh}`.
- Status: done

<a id="op-12"></a>
## op-12 · 운영(prd) 이미지에 settings.yaml 굽기
- 할 일: `bake.sh`·`Dockerfile.bake`에 settings.yaml 굽기를 더한다(규칙은 op-07 ③). 지금 `bake.sh`는 코드 묶음에서 settings.yaml을 뺀다. 🔒 검토 등급 A(비밀 처리) — 사람 검토.
- Status: todo

<a id="op-10"></a>
## op-10 · 서버 설치·업그레이드 — 길 하나, podman 기본
- 규칙:
  1. 설치 길은 README §5-0·§5-3에만 쓰고 다른 문서는 링크한다. 0.2.0 올리기·되돌리기는 [release-and-patch.md §8-3·§8-5](../operations/release-and-patch.md), 배포 사람 할 일은 §8.
  2. 컨테이너 도구 = 셸 `DOCKER` > settings.yaml `ops.host.docker` > podman > docker(`settings_env.sh` `docker_default`, 설정을 읽은 뒤 정함). `ship_stage.sh`·`load.sh`도 podman 우선.
  3. 서버 상주 컨테이너 셋: 일괄 `data-pipeline`(파싱·구조화·적재 — 문서 폴더 읽기 전용 + 결과 폴더, 자원 `ops.pipeline_host.parse_cpus` 5·`parse_mem_limit` 24g), `data-pipeline-mcp`([ops.md#rn-03](ops.md#rn-03)), `mcp-server`. pgvector·redis는 우리 것이 아니다.
  4. 운영 작업(`trigger.sh parse|publish`, `run_tool.sh <도구>|migrate|show-stack|check`, `dbtool`)은 상주 `data-pipeline` 안에서 `docker exec`(`image_vars.sh` `in_pipeline` — 안 떠 있으면 종료 2). 일회성 작업 컨테이너는 없다. 이미지 점검(`docker run --rm … selftest`)만 예외.
  5. `settings_env.sh`는 호스트 python(PyYAML만)의 `host_env.py` + `host_keys.tsv`로 설정을 셸 env로 낸다.
  6. 재부팅 대비 `systemctl enable --now podman-restart`, keepalive 타이머 `mcp-server-keepalive`가 `mcp_up.sh`로 `mcp-server`·`data-pipeline-mcp`를 살핀다.
- 파일: `README.md` §5, `deploy/host/{scripts,compose,systemd}/`, `deploy/release/{ship_stage.sh,load.sh}`.
- QA: `tests/general/deploy/test_compose.py`·`test_host_env.py`·`test_dc.py` · 통과. 서버 확인 refactor.md C-71·C-82·C-83.
- Status: done

<a id="op-11"></a>
## op-11 · 사람 정답 폴더(`GOLD_DIR`) 마운트 — 붙일지 칸을 지울지
- 이유: 상주 `data-pipeline`에 사람 정답 폴더(`GOLD_DIR` → 컨테이너 `/data/gold`)가 붙지 않아 점검기(`common/check/checker.py`)의 `GOLD_DIR` 이름 짝 점검이 건너뛰어진다.
- 할 일: compose에 선택 마운트로 붙일지, 칸 `ops.pipeline_host.gold_dir`과 이미지 약속 경로(`IMAGE_PATHS.gold_mount`)를 지울지 사람이 정한다(`settings.py`는 code_fp 파일 — 지문 배치에).
- Status: todo
