# 릴리스 · 패치 — 이미지 기준 버전 + 오버레이 패치

↑ [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 스크립트: `deploy/release/{make_patch,build_ship,ship_stage,selftest_gate}.sh` · `deploy/host/scripts/prune_old.sh`

**전제**: 서버에는 이미지 2개(기준 버전)를 한 번 넣고, 그 뒤 코드 수정은 **바뀐 파일만 오버레이 패치**로 전달한다. 의존성(패키지·시스템 라이브러리·모델 파일)이 바뀔 때만 새 이미지 버전을 만든다.

## 1. 이미지 vs 오버레이 패치 — 무엇이 어디 있나

| 이미지 | `--target` | 담는 코드(이미지 안 `/app/deploy/<폴더>` · `/app/docker`) |
|---|---|---|
| `data-pipeline` | `pipeline` | `common`·`pipeline`(엔진·검토 루프·구조화·적재·퍼블리시)·`resources` + `assets/`(OCR 모델) + LibreOffice |
| `mcp-server` | `mcp` | `common`·`mcp_server`·`resources` + `pipeline/cli.py`(명령용) |

Answer Agent 이미지는 없다(10-14 결정 — 개발 서버 네이티브. MCP 평가 도구 `mcp_eval`은 11-01에 지움 — e2-10). 옛 타깃 `core`·`all`·`parse`·`structure`·`retrieval`과 옛 이미지 이름은 없어졌다(S6b, D-020).

두 이미지 모두 `/app/docker`에는 이미지 안에서 쓰는 것만 든다 — `entrypoint.sh`(저장소 `deploy/docker/`)·`selftest_gate.sh`·`known_fail.txt`·`assets.py`(저장소 `deploy/release/`). compose·systemd·호스트 스크립트는 저장소 `deploy/host/`에 있고 이미지에 들어가지 않는다.

**서버 코드 폴더(live, `PATCH_CODE` — 기본 `/srv/rag/code/live`)** — `live/app/` = 컨테이너 마운트 원본(`app/deploy/<폴더>`·`app/docker` — 이미지 안과 같은 모양) · `live/deploy/{host,release}/` = 호스트에서 부르는 것(compose·systemd·`trigger.sh`·`mcp_up.sh`·`run_tool.sh`·`selftest_gate.sh` 등 — 저장소와 같은 자리). 사람·systemd는 `live`에서 `bash deploy/host/scripts/trigger.sh …`처럼 부른다.

**오버레이 패치가 바꿀 수 있는 것**(이미지는 그대로, 코드 폴더만 교체):
- 저장소 `common/`·`pipeline/`·`mcp_server/`·`resources/` → live `app/deploy/<폴더>/`
- `deploy/docker/entrypoint.sh`·`deploy/release/{selftest_gate.sh,known_fail.txt,assets.py}` → live `app/docker/`
- `deploy/host/`·`deploy/release/` → live `deploy/…`(호스트 스크립트)

**오버레이 패치로 못 바꾸는 것**(바꾸면 새 이미지 버전) — `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일·**서버 배포 테스트 `tests/server`**(이미지 안 `/app/deploy/tests`에만 있고 compose.patch*.yml이 붙이지 않는다 — 앱 코드만 패치하면 이미지 안 테스트는 옛 버전이므로, 테스트가 바뀐 번들은 새 이미지 버전으로 — 옛 C-53, [이력](../history/refactor_c_items.md) · 코드 폴더를 마운트하는 실행 이미지(op-06)에서는 해소됨, PRD [e2-14](../prd/test.md#e2-14)). S6b 전 배치(옛 `docker/`·upstream `deploy/<폴더>`)에서 이 배치로 넘어가는 패치 번들은 만들지 않는다(§3-1).

### 1-1. 개발 서버 — 실행 이미지 + 코드 폴더(op-06, 사용자 10-30)

개발 서버는 코드 없는 실행 이미지(`data-pipeline-runtime`·`mcp-server-runtime`)에 코드 폴더를 읽기 전용으로 붙여 쓴다. 코드 바꾸기 = 코드 폴더 바꾸기.

1. PC: `IMAGE_TARGET=pipeline-runtime bash deploy/release/build_ship.sh`(mcp는 `mcp-runtime`) — 이미지 관문은 이 커밋의 코드 트리를 붙여 돌고, 코드 폴더 묶음 `output/ship/code-<버전>-<커밋>.tar.gz`(`CODE_OUT=`로 바꿈 — git 추적 파일 + `CODE_COMMIT`, `valid_env/`·`validation/` 없음)을 만든다. 코드만 바뀐 판은 이미지를 다시 보낼 필요가 없다 — 묶음만 보낸다(같은 커밋의 `deploy/docker/DEPS_HASH`가 서버 이미지와 같아야 함). 이미지 저장소로 보낼 때: `CODE_BUNDLE=output/ship/code-<버전>-<커밋>.tar.gz bash deploy/release/ship_stage.sh <판> pipeline-runtime mcp-runtime`(조각·sha256 + 태그 폴더에 묶음과 그 sha256).
2. 서버: 판 폴더로 풀기 — `mkdir -p /srv/rag/code/<버전>-<커밋> && tar -xzf code-….tar.gz --no-same-owner -C /srv/rag/code/<버전>-<커밋>` → `chown -R 10001:10001 /srv/rag/code/<버전>-<커밋>`(root 권한이 없으면 `chmod -R a+rX`로 모두가 읽게). 컨테이너 사용자 10001이 읽지 못하면 실행 이미지가 "읽을 수 없음(권한)"으로 멈춘다(종료 2).
3. 바꾸기 — `ln -sfn /srv/rag/code/<버전>-<커밋> /srv/rag/code/live` → 상주 서비스 다시 띄움(`mcp_up.sh`, 트리거 상주 컨테이너 `docker compose … up -d --force-recreate`). 셸·unit에는 `CODE_DIR=/srv/rag/code/live`.
4. 확인 — 컨테이너 로그 첫 줄 `[image] 이미지 <이름 버전 커밋> · 코드 <커밋> · 의존성 <지문>`. `의존성 지문이 다름`으로 멈추면 그 코드는 새 실행 이미지가 필요하다(requirements·휠·Dockerfile·assets가 바뀜).
5. 되돌리기 — 바로 앞 판 폴더를 지우지 않고 두었다가 `ln -sfn /srv/rag/code/<앞 판> /srv/rag/code/live` → 다시 띄움. 판 폴더는 최근 2개 이상 남긴다.

### 1-2. 개발 → 운영 — 개발 서버에서 시험한 그대로 굽기(op-07, 사용자 10-30)

운영 이미지는 PC에서 다시 빌드하지 않는다. 개발 서버에서 쓰던 **실행 이미지 그 판**과 **시험한 코드 폴더 그대로**를 묶어 코드가 든 이미지를 만든다(`deploy/docker/Dockerfile.bake` — 실행 이미지 위에 코드 COPY만, 패키지 설치·네트워크 없음). 만든 이미지는 코드 폴더 없이 뜬다(`/app/deploy`·`/app/docker`가 Dockerfile의 `pipeline`·`mcp` 타깃과 같은 파일).

1. 개발 서버에서: `bash /srv/rag/code/live/deploy/release/bake.sh <실행 이미지 판>`(예 `0.1.0` — `data-pipeline-runtime:0.1.0`·`mcp-server-runtime:0.1.0`, 대상 하나만이면 뒤에 `pipeline` 또는 `mcp`). 코드 폴더는 스크립트가 든 폴더(다른 폴더면 `CODE_DIR=`), 새 태그는 코드 `VERSION`(태그 = 버전 — 다른 `TAG=`는 거부, 다시 구우려면 VERSION을 올린 코드로), 컨테이너 도구는 podman(없으면 docker — `DOCKER=`), 저장 폴더는 `/var/tmp/bake`(`OUT=`). 한 대상만 실패했으면 그 대상만 다시(`… <판> mcp`).
2. 스크립트가 차례로: ① 코드 `deploy/docker/DEPS_HASH` = 실행 이미지 의존성 지문(다르면 멈춤) ② 빌드 — 라벨 `org.opencontainers.image.revision`(코드 커밋 `CODE_COMMIT`)·`org.opencontainers.image.base.digest`(실행 이미지 ID) ③ 반입 판정 `selftest_gate.sh`(코드 폴더 마운트 없이 — `[판정] 통과`가 아니면 멈춤) ④ 저장·gzip·45m 분할·sha256(`ship_stage.sh`) → `/var/tmp/bake/sbl_images/` — 개발 서버와 같은 배치(`load.sh` · `<태그>/BUILD.txt` · `<태그>/<이미지>/`) + 같은 태그 폴더에 시험한 코드 폴더 묶음 `code-<태그>-<커밋>.tar.gz`(+ sha256).
3. 운영 서버: `sbl_images/` 폴더째 옮겨 `DOCKER=podman bash sbl_images/load.sh <태그>`(조각 sha256 확인 → 합치기 → load → BUILD.txt) → 태그 확인. 호스트 스크립트(`deploy/host/` — trigger.sh·compose·systemd)는 같이 온 코드 폴더 묶음을 `/srv/rag/code/<버전>-<커밋>`에 풀고 `live` 링크로(§1-1 2·3과 같은 방법 — 이미지와 같은 커밋). 컨테이너에는 코드 폴더를 붙이지 않는다 — 셸·unit에 `CODE_DIR`을 두지 않는다(두면 compose가 코드 폴더를 덮어 붙임). 띄우는 법은 §5-2.
4. 어느 판이 운영에 있는지: `docker image inspect <태그> --format '{{json .Config.Labels}}'` — 코드 커밋·실행 이미지 ID.

배포 단계 표(어디서 어디로·어떤 이미지·코드)는 README §5-0. 운영(수집) 서버의 새 이미지는 §1-2(개발 서버에서 굽기)가 기본이고, 아래 §2~§5(PC 빌드·오버레이 패치)는 PC 시험·비상 수정용이다.

## 2. 코드를 고칠 때 지킬 것 (오버레이 패치로 전달 가능하게)

| # | 규칙 |
|---|---|
| C1 | 새 외부 패키지 import 금지(표준 라이브러리·이미 `requirements*.txt`에 있는 것만) |
| C2 | `requirements*.txt`·`Dockerfile`·`wheels`·`assets/` 모델 파일은 바꾸지 않는다(바꾸면 `make_patch.sh`가 종료 코드 3) |
| C3 | 이미지 경계를 넘는 import 금지 — `mcp_server`(mcp-server)와 `pipeline`(data-pipeline)은 서로 import하지 않는다. `python -m common.check.check_modules`가 잡음 |
| C4 | 절대 경로 금지 — 저장소 안은 `common/core/paths.py` 기준 상수, 환경마다 다른 경로는 settings.yaml 항목([CLAUDE.md](../../CLAUDE.md) §2). 쓰기는 `output/`(볼륨)에만 |
| C5 | `agent_platform/`은 10-26에 지웠다(I5, D-013) — LLM·VLM·임베딩 호출은 `common/ai/adk.py`·`llm.py`(임시 대체 구현, I6)를 고친다. 서버 live에 남은 옛 `agent_platform`·`common_tools`·`data_*` 폴더는 새 이미지 버전의 전체 덮어쓰기(§4)로 지운다(오버레이 패치 번들은 S6b 배치 뒤부터) |
| C6 | 새 모듈 폴더를 만들면 §1 표의 어느 이미지 경로인지 정하고, 서버 연결 옵션(§3-2)이 그 폴더를 덮는지 확인 |
| C7 | 설정 기본값을 바꿀 때는 settings.yaml 항목으로(코드 상수 변경도 오버레이 패치로 되지만 커밋 메시지에 이유 한 줄) |
| C8 | 커밋 메시지에 **'오버레이 패치 가능' / '새 이미지 버전 필요'** |

## 3. 오버레이 패치 — 만들기 → 적용 → 확인

### 3-1. PC에서 번들 만들기
```bash
bash deploy/release/make_patch.sh last <출력 폴더> ["이유 한 줄"] [이번 번들 요약.md]
#   last(기본) = 직전에 올린 패치 이후(증분) · image = 이미지 기준 버전 이후 전부 · <커밋> = 그 커밋 이후 누적
```
종료 코드 3 → §5(새 이미지 버전)·§4(전체 덮어쓰기)로: 의존성(§2 C2)이 기준 버전 뒤에 바뀌었거나, 기준 버전·시작점이 이 저장소 배치(`deploy/docker/Dockerfile`·`common/core/fingerprint.py`가 있는 버전)가 아닐 때(S6b 전 `docker/` 배치·upstream `deploy/<폴더>` 배치·이 저장소에 없는 기준 커밋). 이미지 COPY·compose 마운트·호스트 스크립트 자리가 달라 파일 교체·삭제로는 맞출 수 없다.

성공하면 출력 폴더에(경로는 **live 기준 그대로**):
- 바뀐 파일: `app/deploy/<common|pipeline|mcp_server|resources>/…`·`app/docker/…`(컨테이너 마운트 원본) · `deploy/host/…`·`deploy/release/…`(호스트 스크립트)
- `prev/`(바뀌기 직전 버전 — 서버가 그 파일을 직접 고쳤는지 비교용)
- **`PATCH_MANIFEST.txt`** — `M <경로>`(교체)·`D <경로>`(삭제) 줄(live 기준) + 기준 버전·범위·전제(서버가 어느 커밋이어야 하는지)
- **`PATCH_NOTES.md`** — 서버 LLM이 먼저 읽는 설명서: 적용 규칙·"재파싱 필요?"·바뀐 설정·커밋별 목적. "재파싱 필요?"는 **핑거프린트 값 비교**다: 시작점·HEAD 코드를 임시 폴더에 풀어 핸드오프 `FINGERPRINT`(다르면 parse부터 다시)·엔진 핑거프린트 27개(다르면 그 엔진 원문 재파싱)·참고로 code_fp 5개를 계산해 비교한다(계산에 `PY` — 기본 저장소 `.venv/bin/python`; 계산이 안 되면 "판정 불가")
- `CHANGES.md` — 패치 브랜치의 누적 이력(이번 절 추가)

`PATCH_COMMIT=1`이면 출력을 패치 브랜치(기본 `dev_server_patch`)에 새 커밋으로 쌓는다(push는 사람).

### 3-2. 서버에서 적용

**원칙 — 서버에서 자체로 진행한 것이 먼저다.** 서버는 실데이터로 돌려 보고 고친 곳이라, 서버 쪽 코드 수정·옵션 값·서버 전용 스크립트는 그대로 살리고 패치의 새 코드를 그 위에 합친다(패치가 서버 변경을 덮어 없애지 않게). 병합은 서버 LLM이 끝까지 한다 — 충돌이 나도 멈추지 않고 아래 기준으로 합친 뒤, 무엇을 어떻게 합쳤는지 기록에 남긴다.

**먼저 서버 자체 개발 기록을 읽는다** — `/srv/rag/reports/server-changes.md`(서버에서 코드를 고치거나 옵션을 바꾼 건마다 한 행 + `server-changes/<ID>.diff`, 형식 [server-guide.md](server-guide.md) §7)와 서버 설정 파일 `/srv/rag/env/settings.yaml`(옛 `pipeline.env`는 읽지 않음). 상태가 `서버에만`·`PC 보냄`인 행마다:

| 그 행의 파일이 이번 `PATCH_MANIFEST.txt`에 | 할 일 |
|---|---|
| 없음 | 그대로 둔다(패치가 안 건드림) |
| `M`(교체)로 있음 | 새 파일에 그 변경이 이미 들어 있으면(PC가 반영 — `PATCH_NOTES.md` 커밋 목적에 그 ID) 새 파일로 교체하고 `PC 반영됨 <커밋>`. 없으면 **새 파일 위에 서버 변경을 다시 얹는다**: `<ID>.diff`가 그대로 안 얹히면 그 변경의 뜻(행의 '무엇·왜')을 새 코드 구조에 맞게 손으로 옮긴다. 패치와 서버가 같은 줄·같은 동작을 다르게 바꿨으면 **서버 쪽 동작을 남기고**, 패치의 나머지 새 기능은 그 둘레에 붙인다. 행에 `다시 얹음 <패치 커밋>` + 합친 방법 한 줄 |
| `D`(삭제)로 있음 | 패치 노트에서 그 코드가 어디로 옮겨졌는지 보고, 옮겨진 곳에 서버 변경을 다시 얹는다. 옮겨진 곳이 없으면(기능 삭제) 서버가 그 파일을 쓰는지 보고 쓰면 남긴다. 행에 처리 한 줄 |

**옵션(설정) 변경도 같은 원칙** — 서버에서 바꾼 옵션 값이 패치 뒤에도 그대로 동작해야 한다:
- 서버 `settings.yaml`에 적은 값은 패치가 기본값을 바꿔도 그대로 둔다(설정 파일이 코드 기본값보다 우선).
- 서버가 코드 안 기본값(상수·설정 모델 기본값 등)을 직접 바꿨다면 그 값을 `settings.yaml`의 같은 항목(자리는 저장소 `settings.sample.yaml` — 옛 env 이름으로 찾음)으로 옮긴 뒤 새 파일로 교체한다(다음 패치부터 코드 안 값이 덮여도 유지됨). 설정 항목이 없는 값이면 위 표대로 코드에 다시 얹는다.
- 패치가 설정 항목 이름·자리를 바꾸거나 없앴으면(`PATCH_NOTES.md` '바뀐 env'·`settings.sample.yaml` 차이) 서버가 쓰던 옛 항목의 값을 새 항목으로 옮긴다. 새로 생긴 항목은 기본값으로 두되, 서버에서 일부러 끈 기능(false)과 겹치면 끈 상태를 유지한다.
- 옮기거나 유지한 옵션은 모두 `server-changes.md` 행(또는 새 행)에 적는다.

기록이 없는데 `live`와 `prev/`가 다른 파일(기록 안 된 서버 수정)이 나오면 그것도 서버 자체 변경으로 보고 같은 방식으로 합치고, 그 자리에서 기록에 행을 추가한다.

```bash
cp -a <받은 폴더>/app <받은 폴더>/deploy /srv/rag/code/live/    # 번들 경로 = live 경로 — 있는 쪽만
grep '^D ' <받은 폴더>/PATCH_MANIFEST.txt | cut -c3- | xargs -r -I{} rm -f /srv/rag/code/live/{}
```
적용 전에 `/srv/rag/code/live`를 `backup-<날짜시각>/`로 복사해 둔다. 위 `cp`는 서버 변경이 없는 파일(`live == prev/`)에만 그대로 쓰고, 서버 변경이 있는 파일은 위 표대로 합친 결과를 넣는다. `D` 파일도 `live == prev/`일 때만 그냥 지운다.

컨테이너는 이 코드 폴더를 읽기 전용으로 연결해서 띄운다(이미지는 그대로) — `deploy/host/compose/compose.patch.yml`을 덧붙여서(`live`에서):
```bash
docker compose -f deploy/host/compose/compose.pipeline.yml -f deploy/host/compose/compose.patch.yml run --rm parse ...
docker compose -f deploy/host/compose/compose.mcp.yml -f deploy/host/compose/compose.patch.mcp.yml up -d
```
`PATCH_CODE`(기본 `/srv/rag/code/live`)가 `/app/deploy/*`·`/app/docker`를 덮는다 — entrypoint도 함께 덮이므로 기준 이미지에 없던 새 명령도 쓸 수 있다.

### 3-3. 확인
```bash
docker run --rm <연결 옵션> <태그> check-modules
bash <코드 폴더>/deploy/release/selftest_gate.sh docker run --rm <연결 옵션> <태그> selftest
```
**selftest는 종료 코드로 판정하지 않는다.** selftest는 FAIL이 하나라도 있으면 종료 코드 1인데, data-pipeline 이미지는 리팩토링 전부터 있던 알려진 FAIL 때문에 늘 1이라 고장과 구별이 안 된다. `selftest_gate.sh`가 selftest를 돌린 뒤 FAIL 줄을 알려진 목록 `deploy/release/known_fail.txt`(git 안, 이미지 안 `/app/docker/known_fail.txt`, 사례 이름 한 줄씩 + 이유 주석)와 대조해 마지막 `[판정]` 줄과 종료 코드를 낸다 — **목록 밖 FAIL 0이면 통과(0)**, 하나라도 있거나 요약 줄이 없으면 실패(1).
- 지금 기대값: data-pipeline FAIL 1(목록 안 `test_publish_guard` — 서버가 source.json을 안 올려 꺼진 방어선, `refactor.md` C-54 ②. PG 문서 레지스트리 갱신 실패(C-54 ①)는 배포 판정 밖 일반 테스트 `test_pub_registry`) · mcp-server FAIL 0.
- 사례 = 서버 배포 테스트 파일(`tests/server/<common|pipeline|mcp>/test_*.py` — 이미지 안 `/app/deploy/tests/server`, 사례 이름 = 테스트 모듈 이름 예 `tests.server.pipeline.test_build_bundle`). 옛 `python -m <모듈> --selftest`는 없다.
- 한 사례만: `docker run --rm <태그> selftest --only <이름 조각>`.
- 이미지 안 목록으로 판정: `docker run --rm --entrypoint bash <태그> /app/docker/selftest_gate.sh /app/docker/entrypoint.sh selftest`.

통과하면 `/srv/rag/reports/versions.md`에 한 줄: `날짜 · 서버 · 이미지 버전 + patch <커밋> · 확인 결과`(다시 얹은 서버 변경 ID·유지한 옵션도). 실패하면 먼저 합친 곳을 다시 본다 — 서버 변경은 살린 채 패치 쪽 연결(새 함수 이름·인자·import)을 맞춰 고치고 다시 확인. 그래도 안 되면 그 패치 항목만 빼고(서버 쪽 버전 유지) 나머지를 적용한 뒤 뺀 항목과 이유를 `issues.md`에 적는다. **서버 변경을 버려서 통과시키지는 않는다.**

### 3-4. 서버 자체 개발을 PC(main)로 가져오기
서버에서만 고친 코드는 다음 패치·전체 덮어쓰기 때마다 다시 얹어야 하므로, PC가 main에 받아들이는 것이 기본이다.
1. 서버 → PC: `server-changes.md`의 `서버에만` 행과 `<ID>.diff`를 보낸다(반출 규칙은 이슈와 같음 — 코드·숫자·오류만, 문서 본문·고객명·키 값 없음). 보낸 행은 `PC 보냄`.
2. PC: 외부 PR처럼 읽고 검토하되 **서버가 실데이터로 고친 것이라 받아들이는 쪽이 기본** — diff·이유·서버 테스트 결과를 보고 그대로 또는 PC 구조에 맞게 고쳐 받아들이고, 버리는 것은 같은 문제를 PC 코드가 이미 다르게 풀었을 때만. 서버가 바꾼 옵션 값은 기본값으로 올릴지(모든 서버에 맞는지) 따로 판단. 받아들이면 `jh/<ID>` 브랜치 → 테스트 → main. 판단과 근거는 `docs/backlog/dev_his.md` '외부 PR·이슈 검토' 절에 한 행.
3. 다음 패치의 커밋 메시지에 그 서버 변경 ID를 적는다(`PATCH_NOTES.md` 커밋 목적에 나옴 → 서버가 §3-2에서 `PC 반영됨`으로 닫음). 버린 변경은 이유와 함께 서버에 알리고 행을 `폐기`로.

## 4. 전체 덮어쓰기 — 경로가 크게 바뀌었을 때(서버 기본값보다 단순)

비교 작업이 필요 없는 대신 "서버에서 직접 고친 코드"가 **사라진다** — 그래서 서버에서는 되도록 코드를 고치지 않고(설정이나 PC에 알리는 이슈로), 고쳤다면 반드시 `server-changes.md`에 기록한다. 덮어쓰기 전에 그 기록과 서버 설정 파일(`/srv/rag/env/settings.yaml` — S7e1 전 버전은 `pipeline.env`)을 읽어 `서버에만`·`PC 보냄` 행을 확인하고, 덮어쓴 뒤 §3-2의 원칙(서버 자체 진행 우선 — 코드 변경 다시 얹기·옵션 값 유지)대로 합친다(새 코드에 이미 들어 있으면 `PC 반영됨`).
```bash
# 서버
cp -a /srv/rag/code/live /srv/rag/code/backup-<날짜시각>
rm -rf /srv/rag/code/live && mkdir -p /srv/rag/code/live/app/deploy /srv/rag/code/live/app/docker /srv/rag/code/live/deploy
Z=<받은 ZIP을 푼 저장소 루트>
cp -a $Z/common $Z/pipeline $Z/mcp_server $Z/resources /srv/rag/code/live/app/deploy/          # 컨테이너 /app/deploy/<폴더>
cp -a $Z/deploy/docker/entrypoint.sh $Z/deploy/release/selftest_gate.sh $Z/deploy/release/known_fail.txt $Z/deploy/release/assets.py /srv/rag/code/live/app/docker/   # 컨테이너 /app/docker(이미지 안과 같은 4개)
cp -a $Z/deploy/host $Z/deploy/release /srv/rag/code/live/deploy/                                 # 호스트 스크립트
```
PC 쪽: push 전에 **RELEASE_NOTES.md**(이번 번들 목적·바뀐 코드·바뀐 설정·재파싱 필요 여부)를 같이 커밋 — `NOTES_ONLY=1 NOTES_NAME=RELEASE_NOTES.md bash deploy/release/make_patch.sh <직전 배포 커밋> <출력>`로 설명서만 만든다(매니페스트·`prev/` 없음, 전체 모드). 시작점이 S6b 전 배치면 종료 코드 3이므로 S6b 첫 배포의 설명서는 손으로 쓴다.

## 5. 새 이미지 버전이 필요할 때

의존성(§2 C1·C2)이 바뀌었거나 오버레이 패치가 너무 커졌을 때.

**0.2.0은 §8 "0.2.0 배포 — 사람이 할 일"**(사람 할 일의 정본 — 결정·배포 전·당일·뒤, 누가·`C-xx`)을 따른다 — §5-1~§5-7은 그 안의 단계별 명령이다(0.1.0 판은 [history/deploy_0_1_0.md](../history/deploy_0_1_0.md)).

**`deploy/docker/IMAGE_BASE`** — 한 줄 `<커밋 7자> <이미지 태그>`, `make_patch.sh image`·`last`의 기준. 지금은 upstream 10-16 버전 `e305b14 20261016-e305b14`([release_history.md](../history/release_history.md) §8)라 이 저장소에 없는 커밋이다(`make_patch.sh`가 종료 코드 3 "새 이미지 버전 필요"). 새 이미지 버전을 서버에 넣은 뒤 그 버전을 만든 이 저장소 커밋·태그로 고쳐 커밋한다 — 그 뒤부터 오버레이 패치를 만들 수 있다. 둘째 항목(이미지 태그)은 버전으로 적는다(예 `<커밋 7자> 0.1.0`).

**버전(D-036, 10-29)** — 두 이미지(`data-pipeline`·`mcp-server`)는 같은 버전을 쓴다. 정본은 저장소 루트 `VERSION` 한 줄(SemVer `MAJOR.MINOR.PATCH`, 첫 배포 `0.1.0`).
- 올리는 규칙(D-009): MAJOR = MCP 도구 계약·DB 스키마·핸드오프 형식처럼 서로 맞춰야 하는 것이 깨질 때(1.0 전에는 예외 — MINOR에서도 계약·스키마를 깰 수 있고, 운영이 안정되면 1.0.0으로 올림, 사용자 10-30 PRD grill C2) · MINOR = 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 · PATCH = 오버레이 패치(코드만 교체). `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 git 태그 `v<버전>`(annotated)을 붙인다.
- 이미지 태그 = 버전(`data-pipeline:0.1.0`·`mcp-server:0.1.0`). `build_ship.sh`·`ship_stage.sh`는 태그를 안 주면 `VERSION`을 쓰고, 빌드한 커밋은 이미지 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`)에 남긴다 — `docker inspect -f '{{json .Config.Labels}}' data-pipeline:0.1.0`. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`).
- 버전 표기(`common.pipeline_version()` — 회사 DB `AI.ParsingMeta.silver_version`(지금 이름 `pipeline_version`)·`gold_version` — 사용자 11-02)는 이미지 안 `/app/deploy/VERSION`과 오버레이 패치의 `common/PATCH_VERSION`(`make_patch.sh`가 HEAD의 `VERSION`을 적음 — 이미지 태그와 같으면 종료 2) 중 높은 버전이다(10-29 전에는 git 짧은 커밋 — `refactor.md` C-62).

### 5-1. 빌드 → 전송 → 적재
```bash
# 저장소 루트에서 — 2개(또는 바뀐 것만). Docker 23 미만이면 아래 '로컬 빌드' 인자를 붙인다
V=$(cat VERSION)   # 두 이미지 같은 버전 태그(D-036) — 라벨까지 넣으려면 build_ship.sh(아래)를 쓴다
docker build -f deploy/docker/Dockerfile --target pipeline --build-arg APP_VERSION=$V -t data-pipeline:$V .
docker build -f deploy/docker/Dockerfile --target mcp      --build-arg APP_VERSION=$V -t mcp-server:$V .
# ↑ 직접 빌드는 assets/rapidocr가 없어도 멈추지 않고 빈 assets/로 빌드된다. 먼저 `ls assets/rapidocr/*.onnx`로 확인하거나 build_ship.sh를 쓴다(없으면 멈춤)

# 빌드만(빌드→selftest 판정→resources→비밀값 흔적 점검, 저장·전송 없음 — PC 확인용)
BUILD_ONLY=1 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh            # 태그 = data-pipeline:<VERSION> · 테스트 빌드는 TAG=data-pipeline:<다른 태그>

# 한 번에(빌드→점검→저장→전송→적재→원격 점검, SSH 쪽으로)
TARGET=user@수집서버 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh

# 또는 저장만(45MB 조각 + sha256 — output/ship/sbl_images/, 저장소 push는 사람이 따로)
bash deploy/release/ship_stage.sh pipeline mcp            # 태그 = VERSION(다른 태그면 첫 인자로: ship_stage.sh <태그> pipeline mcp)
```
**로컬 빌드** — 빌드 컨텍스트는 저장소 루트(Dockerfile은 `deploy/docker/Dockerfile` — 이미지 안 경로 `/app/deploy/<폴더>`·`/app/docker`). 루트 `.dockerignore`가 허용 목록이라 `common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`만 컨텍스트에 들어간다(`deploy/host`·`.venv`·`output`·`valid_env`·`.env.local`·코드 폴더 안 `output/`은 빠짐).
- Dockerfile pipeline 단계의 heredoc(`RUN python - <<'EOF'`) 때문에 **Docker 23 미만(예: 20.10)** 은 파일 전체를 못 읽는다 — `DOCKER_BUILDKIT=1 docker build --build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7 …`로 빌드한다(`docker/dockerfile` 이미지를 받으므로 인터넷 필요). `build_ship.sh`는 docker 버전을 보고 이 인자를 스스로 붙인다(`BUILDKIT_SYNTAX=<값>`으로 바꿀 수 있음). podman은 서버에서 확인한다.
- selftest 판정은 §3-3과 같다(`selftest_gate.sh` — 알려진 FAIL 밖 0).
- pipeline 이미지는 `assets/`(Git 제외, rapidocr 모델 — 준비는 §5-6)를 저장소 루트에 두고 빌드한다 — 새 체크아웃·worktree에서는 비어 있으니 먼저 복사한다. `build_ship.sh`는 pipeline 타깃에서 없으면 실패하고 `ALLOW_NO_ASSETS=1`로만 통과한다 — 그때 빈 `assets/`로 빌드되어 rapidocr 모델을 첫 실행에 받으려 한다(폐쇄망이면 실패). mcp는 assets를 쓰지 않는다.

### 5-2. 서버에서
이미지 불러오기는 README §5-0 "개발 서버 설치"(코드 zip + `sbl_images` zip → `load.sh`) 한 길이다(op-10). 운영 서버(구운 이미지)도 같은 `load.sh`(§1-2). 판을 올릴 때의 순서·되돌리기는 §5-7.
그 뒤 패치 브랜치를 새 버전 기준으로 비운다(`make_patch.sh <새 기준 커밋>` — 바뀐 파일 0이어야 함).

**이미지·코드 폴더·`run_docs.py`는 같은 때에 바꾼다.** 셋 중 하나만 바꾸면 나머지가 깨진다(이미지의 패키지 배치·`compose.patch.yml`이 마운트하는 `app/deploy/<폴더>`·`run_docs.py`가 부르는 `python -m pipeline.…`가 서로 맞아야 함 — 확인 파일 `pipeline/extract/run_all.py`, `docflow_probe.py`는 이미지 안 `/app/deploy/pipeline/extract/`). 순서: 배치·상주 컨테이너 멈춤 → 이미지 적재 → 코드 폴더 전체 덮어쓰기(§4) → `run_docs.py` 교체 → 컨테이너를 새 이미지 + `compose.patch.yml`로 다시 띄움 — 한 번에 한다. 리팩토링 버전(I2·I4·S2~S11 — 패키지 `data_etl` → `pipeline`, 경로 정리)은 **한 이미지 버전으로만** 배포한다 — 나눠 배포하면 p1 code_fp가 두 번 바뀌어 서버 P1 캐시가 한 번 더 전부 빗나간다(refactor_plan 6-1 — `refactor.md` C-23). I4의 바뀐 설정·systemd 할 일은 [env-guide.md](env-guide.md) §5 I4 줄.

**S6b 전환(이미지 합침·`deploy/` 재배치 — 옛 3이미지 서버에 처음 넣을 때 한 번)** — 순서·되돌리기는 `refactor.md` C-04·C-29:
1. 새 이미지 2개(`data-pipeline`·`mcp-server`) 적재.
2. 옛 상주 컨테이너(`data-parsing`·`data-structure`·`data-retrieval`) 멈춤·삭제.
3. 코드 폴더 전체 덮어쓰기(§4 — 호스트 스크립트가 `live/deploy/host/`로).
4. 이미지 이름을 settings.yaml 항목 `required.deploy.pipeline_image`·`required.deploy.mcp_image`(op-08 배치 — 옛 `pipeline.host.image`·`mcp.host.image`)에 적는다(옛 env `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`). S7e1 버전부터 `pipeline.env`만 있으면 종료 코드 2, 옛 `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`(·`RAG_*`)는 안내 뒤 종료 코드 2 — 0.1.0 → 0.2.0 설정 옮기기는 §5-7 3단계.
5. systemd: 옛 `rag-nightly`·`data-retrieval-keepalive` unit disable·삭제, 새 `data-pipeline-nightly`·`mcp-server-keepalive` 설치(`daemon-reload`).
6. 새 compose로 새 이름 컨테이너를 띄운다 — 파싱 상주 `data-pipeline-parse`·`data-pipeline-structure`는 `deploy/host/compose/compose.pipeline.yml`(+ `compose.patch.yml`), 검색 MCP `mcp-server`는 `compose.mcp.yml`(+ `compose.patch.mcp.yml` — `mcp_up.sh`가 씀, 11-01부터 검색 MCP 정의는 이 파일 하나).
7. MCP `parse_document`의 작업 서비스를 손으로 띄운다: `docker exec -d data-pipeline-parse bash -c 'umask 0002 && exec python -u -m pipeline.mcp_parse_service'`(`-e` 없이 · umask는 결과를 운영 계정도 고치게, 토큰은 settings.yaml `pipeline.service.parse_mcp.token`). compose·keepalive가 띄우지 않으므로 `data-pipeline-parse`가 다시 시작될 때마다 다시 띄운다.

**배포 전 확인(V4 R1)** — `run_docs.py`·compose·systemd가 보는 `PATCH_CODE`(기본 `/srv/rag/code/live`)가 파싱 상주 컨테이너(S6b 배포 전에는 옛 이름 `data-parsing`, 뒤에는 `data-pipeline-parse`)가 지금 실제로 마운트하는 코드 폴더와 같은지 본다. 출력의 원본이 `<PATCH_CODE>/app/deploy/pipeline`(옛 버전이면 `…/data_etl`, 옛 배치 컨테이너면 `data_parsing`·`common_tools` 줄)이 아니면(예: `<운영자 작업 폴더>/patch_code/…`) 운영 절차에서 `run_docs.py`를 `PATCH_CODE=<원본에서 /app/deploy/<폴더>를 뺀 앞부분>`으로 띄운다. 출력이 비면 오버레이 패치 마운트 없이 이미지 안 코드로 떠 있는 것이다 — 배포 때 `compose.patch.yml`로 다시 띄운다:
```bash
docker inspect data-parsing --format '{{range .Mounts}}{{if eq .Destination "/app/deploy/pipeline" "/app/deploy/data_etl" "/app/deploy/data_parsing" "/app/deploy/common" "/app/deploy/common_tools"}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}{{end}}'   # 배포 전 = 옛 컨테이너 이름(S6b 뒤는 data-pipeline-parse)
```

**배포 뒤 확인**(`<코드 폴더>` = `PATCH_CODE`, 서버 기본 `/srv/rag/code/live` — compose·systemd·`mcp_up.sh`·`run_docs.py`가 모두 같은 값을 본다). 폴더가 아니라 파일로 본다 — docker는 bind 마운트 원본이 없으면 빈 폴더를 만들어 붙이므로 `test -d`는 빈 폴더도 통과한다(V4 R2):
```bash
D=<코드 폴더>/app/deploy; test -f $D/pipeline/extract/run_all.py && test ! -e $D/data_etl && test ! -e $D/data_parsing && test ! -e $D/data_structure && echo "배치 OK(pipeline)" || echo "배치 어긋남 — pipeline 코드 없음 또는 옛 폴더 남음"
for c in data-pipeline-parse data-pipeline-structure; do docker exec $c test -f /app/deploy/pipeline/extract/run_all.py && echo "$c OK" || echo "$c 코드 없음(빈 마운트?)"; done
```
`run_docs.py`도 시작할 때 같은 확인(코드 폴더 `$PATCH_CODE/app/deploy` + 컨테이너 `data-pipeline-parse`·`data-pipeline-structure` 안 `/app/deploy/pipeline/extract/run_all.py` 파일)을 하고, 어긋나면 이유를 찍고 종료 코드 2로 멈춘다(EDW·Object Storage 접속 전). 코드 폴더를 그 호스트에서 볼 수 없으면 폴더 확인은 건너뛰고(`[안내]` 한 줄) 컨테이너 확인(실제 마운트, `test -f` — 빈 마운트 폴더에서도 멈춤)만 믿는다.

**`run_docs.py` 자리와 설정** — 서버에서 `<운영자 작업 폴더>/run_docs.py`로 두고 그 아래 `test_space/`(진행 기록 `batch_progress/`)를 쓴다(지금 예: `/home/<운영 계정>/dev/parsing_module/`). 설정은 서버 settings.yaml(`--settings`·`SETTINGS_FILE`·`$SERVER_ENV_DIR/settings.yaml`, 호스트 python에 PyYAML 필요)에서 읽는다(S7e1, 사용자 10-27 Q8) — 운영 EDW·Object Storage 접속 값·비밀은 코드와 docker exec 명령 줄에 없고(컨테이너는 붙인 설정 파일에서 읽음) 필요한 항목이 없으면 항목 경로만 찍고 종료 코드 2(목록 `refactor.md` C-45 ③).
- 작업 폴더 `pipeline.host.run_docs_dir`(비우면 스크립트 옆 `test_space/`)
- 결과 공유 폴더(옛 `test_space/rfp_all_output`) `common.host.output_root`(`RAG_OUT` — 컨테이너 `/app/output` 원본 그대로)
- MCP 업로드 작업 폴더 `mcp.host.jobs_dir`(기본 `<결과 폴더>/mcp_parse/jobs`)
- 코드 폴더 확인 `common.host.patch_code`
- `common.run_env`가 dev·prd가 아니면 시작하지 않는다(로컬 실행 금지).

**OCR 결과의 OS 차이** — 같은 모델 파일이어도 rapidocr_ko가 컨테이너(Linux)와 PC(Windows)에서 일부 스캔을 다르게 읽는다(onnxruntime·opencv의 OS별 수치 차이 — 10-15 측정, 회귀 문턱 안이라 버전 고정은 안 함). 서버에서 정답률을 잴 때 기준은 **컨테이너 결과**로 잡는다(측정값은 [release_history.md](../history/release_history.md) §8).

### 5-3. 작게 더할 때 — 이미지를 통째로 바꿔야 하나?

| 더하는 것 | 방법(작은 순) |
|---|---|
| 순수 Python 패키지(wheel) | 서버에서 레이어 추가 빌드: wheel만 배포 → `FROM data-pipeline:<버전>` + `pip install --no-index --find-links /wheels <패키지>` 2줄 Dockerfile → 새 태그 `<이름>:<버전>+ocr1`(큰 이미지 재전송 없음) |
| 모델 파일(가중치) | 이미지 안 바꿈 — `-v /srv/rag/models/<엔진>:/app/assets/<엔진>:ro`로 연결 |
| 시스템 프로그램(바이너리) | 위 추가 레이어에 오프라인 rpm/deb 설치 |
| 큰 프레임워크(torch 등 수 GB) | 새 이미지 버전(§5-1) |

### 5-4. (옮김) 옛 `pipeline.env` → `settings.yaml` 이관

0.1.0 전 서버용(S7e1 버전에서 한 번)이었다. 운영 서버는 0.1.0(settings.yaml 하나)으로 돌아 더 쓰지 않는다 — 옛 절은 [history/deploy_0_1_0.md](../history/deploy_0_1_0.md) §3. 0.1.0 → 0.2.0 설정 옮기기는 §5-7 3단계.

### 5-5. DB 버전 관리 — `migrate`(처음 한 번 버전 기록 + 버전이 바뀔 때)

S8a(사용자 10-28, D-030) 버전부터 pgvector의 우리 스키마(검색 `PG_SCHEMA` — 색인 빌더 `index --pg`의 `<PG_SCHEMA>_<index_id>` 포함)의 표·색인·뷰는 **Alembic 리비전**으로 만든다. 실행 중 자동 DDL은 없다.
- `pgvector_load deploy`(run_docs가 문서마다 부르는 적재 — 옛 `trigger.sh load`·`night`는 11-01에 지움): 새 스키마면 만들고 버전 기록, 버전 기록 있는 스키마면 버전 올리기(migrate up — 끝이면 그대로), **버전 기록 없는 기존 스키마면 비교·DDL 없이 경고만 찍고 적재를 계속**한다(빠진 표·색인은 ②의 check가 보여 주고 ③-b의 up이 만듦 — D-030 ④).
- `struct` 스키마는 코드에서 모두 없앴다(사용자 11-01 — pl-08·D-031). `--target`은 `search`·`all`(= search)뿐이고, 서버에 남은 옛 `struct` 스키마는 코드가 읽지 않는다(그대로 두거나 DB 담당자가 지움). 엔진 구성·원천 목록은 코드 폴더의 파일이다([pipeline_stack.md](../architecture/pipeline_stack.md)).
- 버전 기록 표는 스키마마다 `<스키마>.alembic_version`(DB 담당 협의 — `refactor.md` C-48).
- 새 이미지(SQLAlchemy·alembic — 폐쇄망 휠, §5-1)를 적재한 뒤, 다음 적재(새벽 배치) 전에 한다. 값·비밀은 찍지 않는다(카탈로그·버전 번호만).
```bash
cd /srv/rag/code/live
. deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh
DC="docker compose -f deploy/host/compose/compose.pipeline.yml"   # 오버레이 패치 버전이면 -f deploy/host/compose/compose.patch.yml도(§3-2)
# ⓪ (DB마다 처음 한 번 — DB 관리자) vector 확장: 서버 계정은 우리 스키마 권한만이라 직접 못 만든다(없으면 "vector 확장 없음"으로 멈춤)
#    $DOCKER exec <pg 컨테이너> psql -U <관리자 계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
# ① 지금 버전 — 처음엔 "판 없음"(옛 코드가 만든 DB)
$DC run --rm load migrate current
# ② 비교(읽기만 — 잠금 없음) — 표 정의 ↔ 실제 DB: 표·컬럼·형식·NULL·기본값·키 + 색인 정의 글자 + 뷰 컬럼. 컬럼 순서·뷰 정의 글자(PostgreSQL 버전마다 꼴이 다름)는 "(알림)"만(판정 밖)
$DC run --rm load migrate check --target all
# ③-a 차이 0 → 실행 없이 버전만 기록
$DC run --rm load migrate stamp --target search
# ③-b 차이가 "표 없음·색인 없음·뷰 없음·뷰 칸 다름"뿐 → 없는 것만 만들고(뷰는 다시 만듦) 버전 기록(기준 리비전이 IF NOT EXISTS) — ③-a 대신
#      $DC run --rm load migrate up --target search
# ③-c 컬럼 이름·형식·NULL·기본값·키가 다르거나 남는 표·컬럼·색인 → stamp·up 모두 거부(종료 2) — 멈추고 출력(이름만)을 DB 담당과 협의
# ⑤ 확인 — "판 끝 ['0003_search'] · 코드의 끝 판 0003_search … 비교: 차이 없음" + 엔진 구성 파일이 읽히는지
$DC run --rm load migrate check --target all
$DC run --rm load show-stack                           # 이름·sha·파일 경로 — 못 읽으면 종료 2
```
- **버전 기록 전에 적재가 돌면:** `pgvector_load deploy`·`load`(trigger load·night·run_docs)는 "판 기록 없음" 경고를 찍고 계속한다(기준 리비전 = 지금 스키마 — 결과 같음). 코드보다 낮은 버전이면 적재 전에 `migrate up`을 하라고 종료 2, DB가 코드보다 새 버전(모르는 리비전)이면 이미지·코드 버전을 맞추라고 종료 2(D-030 ⑤). 검색 MCP(읽기)는 버전을 보지 않는다.
- **새 검색 스키마(차원이 바뀜 — 새 `PG_SCHEMA`):** `migrate up --target search --schema <새 스키마> --bundle <번들>`(차원은 번들 meta.json — 또는 `--dim N`). vector 확장이 없으면 관리자 설치(공유 PG에서 `--create-extension`·`PG_CREATE_EXTENSION`을 켜지 않음).
- **버전이 바뀌는 릴리스:** 패치 노트의 "DB 판" 줄을 보고 적재 전에 `migrate up --target <갈래>` — 표·컬럼을 바꾸는 리비전은 데이터 계약 변경(검토 등급 A·DB 담당 협의 — D-008).
- **엔진 구성 바꾸기(사용자 11-01):** 코드 폴더의 `resources/config/pipeline_stack.json`을 고쳐 오버레이 패치로 보낸다(되돌리기 = git). 이미지에 없는 엔진이 있으면 파이프라인 진입점이 시작하지 않는다(종료 2). 오래 도는 검색 MCP는 시작 때 읽으므로 패치 뒤 다시 띄운다(`mcp_up.sh`) — 파싱 MCP 서비스는 작업마다 다시 읽는다. (원천 목록 `sources.json`은 11-01에 지웠다 — 원천은 폴더·`rdb:csv`만.)
- **계정의 기본 스키마가 우리 스키마여도 같음(VS8a B-1):** DB 계정의 `search_path`가 우리 스키마로 정해져 있거나(`ALTER ROLE … SET search_path`), 계정 이름 = 스키마 이름(`"$user"`), `PG_SCHEMA=public`이어도 ②가 표·컬럼을 그대로 비교한다. S8a 버전으로 버전을 기록했다면(그때는 "표 없음"만 보이고 ③-b가 컬럼이 다른 스키마도 기록했음) 지금 버전에서 ②를 다시 돌려 차이 0인지 확인한다.
- **모르는 리비전:** 버전 표에 코드가 모르는 리비전이 하나라도 있으면(새 이미지 → 옛 이미지로 되돌린 뒤 등) 적재·`up`·`stamp` 모두 종료 2.
- PC: `python -m common.store.db.dbtool <up|stamp|current|check> --target …`([CLAUDE.md](../../CLAUDE.md) §6 — 전용 PG에 처음 한 번 `up --target search`) · 기본 스키마·vector 확장 자리 사례 `--pg-cases orca_<새 이름>`(새 테스트 DB를 만듦 — PC 전용).

### 5-7. 판 올리기(0.2.0) · 되돌리기 — 서버(op-10)

0.1.0 → 0.2.0처럼 설정 배치가 바뀌는 판(op-08 — `required`·역할 절·`tuning`)은 아래 순서로 한 번에 한다. 명령은 root 셸, 새 코드 폴더 루트(`cd /srv/rag/code/live` — 링크를 옮긴 뒤)에서.

**0. 미리 정할 것**
- 새벽 배치를 멈춘다: `systemctl stop data-pipeline-nightly.timer`(끝나면 `start`). 진행 중인 배치·`run_docs.py`는 끝날 때까지 기다린다.
- 전체 재처리 시간·디스크를 잡는다 — 판에 따라 후보정(p1)·구조화(s) 지문이 바뀌면 서버 문서 전부가 다시 처리된다(바뀐 지문은 릴리스 노트·PRD e2-02). 시간은 지난 run_docs `progress.log`의 문서당 시간 × 문서 수(실행 보드 `run_board`는 11-01에 지움), 디스크는 `required.deploy.output_root`의 `parse/_rep`·묶음 크기만큼 여유를 더 둔다(옛 결과는 다 돌 때까지 남김).

**1. 백업(되돌리기용)**
```bash
mkdir -p /srv/rag/backup && cp -p /srv/rag/env/settings.yaml /srv/rag/env/settings.yaml.0.1.0   # 옛 설정 — 되돌릴 때 그대로 씀
$DOCKER exec <required.deploy.pg_container 값> pg_dump -U <required.pg.user 값> -d <required.pg.db 값> -Fc > /srv/rag/backup/pg-0.1.0.dump   # DB(값은 화면에 남기지 않게 셸 변수로)
```
옛 코드 폴더(`sbl_data_parsing-0.1.0`)와 옛 이미지(`*-runtime:0.1.0`)는 지우지 않는다.

**2. 새 판 받기** — README §5-0 1~3(새 코드 zip 풀기 · `chmod -R a+rX` · `ln -sfn` 새 폴더 · `load.sh 0.2.0`).

**3. 설정 옮기기(이미지 안에서 — 호스트 python 불필요)** — 옛 파일을 표준 입력으로 넘기고 새 파일을 표준 출력으로 받는다(마운트·권한·SELinux와 무관). 화면(표준 오류)에는 옮긴 칸 수와 지운 칸 이름만 나온다(값은 안 찍음).
```bash
podman run --rm -i --network none --entrypoint bash -v "$PWD:/app/deploy:ro,z" -e PYTHONPATH=/app/deploy data-pipeline-runtime:0.2.0 \
  -c 'umask 077 && cat > /tmp/old.yaml && cd /app/deploy && python -m common.config.migrate /tmp/old.yaml --out /tmp/new.yaml --summary >&2 && cat /tmp/new.yaml' \
  < /srv/rag/env/settings.yaml.0.1.0 > /srv/rag/env/settings.yaml.new
chown 10001:<운영 그룹> /srv/rag/env/settings.yaml.new && chmod 640 /srv/rag/env/settings.yaml.new
mv /srv/rag/env/settings.yaml.new /srv/rag/env/settings.yaml
```
- 운영 서버(구운 이미지)는 `-v …`·`-e PYTHONPATH` 없이 `data-pipeline:0.2.0`(코드가 이미지 안 `/app/deploy`).
- 이미지 칸(`required.deploy.pipeline_image`·`mcp_image`)을 `…:0.2.0`으로 고친다. 새 판에서 생긴 필수 칸이 있으면 채운다(`python -m common.config.sample --where <이름>`으로 자리 확인).

**4. DB** — 버전 차이 확인 → 올리기 → 다시 확인(README §5-3 ③과 같은 `dc`):
```bash
dc run --rm load migrate check --target all     # 차이·버전 확인(읽기만)
dc run --rm load migrate up --target all        # 새 판 마이그레이션(없으면 아무것도 안 함)
dc run --rm load migrate check --target all     # "차이 없음"
```

**5. 띄우기·확인** — README §5-3 ④ 연결 점검 · ⑤ 이미지 점검 → `mcp_up.sh` · 상주 트리거 `dc up -d …`(§5-5) → 시작 로그 첫 줄 `[image] … · 코드 <커밋> …`이 새 판인지 → 새벽 배치 다시 켬(`systemctl start data-pipeline-nightly.timer`).

**되돌리기(0.2.0 → 0.1.0)**
1. 새벽 배치·상주 컨테이너를 멈춘다(`systemctl stop data-pipeline-nightly.timer`, `$DOCKER stop data-pipeline-parse data-pipeline-structure mcp-server`).
2. `ln -sfn /srv/rag/sbl_data_parsing-0.1.0 /srv/rag/code/live` · `cp -p /srv/rag/env/settings.yaml.0.1.0 /srv/rag/env/settings.yaml`(이미지 칸이 `…:0.1.0` 그대로).
3. 4단계 `migrate up`이 무언가를 바꿨으면 DB를 백업으로 되돌린다(`pg_restore --clean -d <db> pg-0.1.0.dump` — DB 담당자와 같이). 되돌림 명령(downgrade)은 없다.
4. 5단계와 같이 띄우고 시작 로그로 0.1.0인지 확인한다. 0.2.0에서 새로 만든 결과(`output_root` 아래)는 옛 판이 낡음으로 보고 다시 만든다.

### 5-6. 반입 자산(`assets/`) 준비 — 이미지 빌드 전

폐쇄망 서버는 첫 실행 때 모델을 인터넷에서 받을 수 없다. 그래서 pipeline 이미지를 빌드하기 전에 저장소 루트 `assets/`를 채운다. `build_ship.sh`는 `IMAGE_TARGET=pipeline`에서 `assets/rapidocr/*.onnx`가 없으면 멈춘다(`ALLOW_NO_ASSETS=1`이면 경고만 — PC 확인 빌드용, 서버에 올릴 이미지에는 쓰지 않음).

**지금 이미지가 쓰는 것은 `assets/rapidocr/*.onnx` 하나뿐이다**(Dockerfile이 `/app/assets/rapidocr/`를 rapidocr 패키지의 `models/`로 복사). 나머지 항목은 옛 서버 설치 길(`assets.py install`)에만 쓰이고 이미지 빌드에는 들어가지 않는다.

| `assets/` 안 | 무엇·누가 쓰나 | 받는 곳(공식 공개 배포) | 원본을 둘 자리(`assets.py pack`이 읽음) | 0.1.0 |
|---|---|---|---|---|
| `rapidocr/*.onnx` | RapidOCR 검출·방향·**한국어 PP-OCRv5 인식** 모델 — `rapidocr_ko` 엔진([PRD pl-22](../prd/transform.md#pl-22) — OCR 엔진은 기본 꺼짐)과 준비 단계 쪽 회전 판정([pl-02](../prd/extract.md#pl-02)) | `pip install rapidocr==3.9.2`(검출·방향·중국어 인식은 패키지에 들어 있음) → 한국어 인식 모델은 **첫 실행 때 받음**: 인터넷이 되는 PC에서 `python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Rec.lang_type': LangRec.KOREAN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})"` 한 번 | 설치된 rapidocr 패키지의 `models/`(자동 — `PP-OCRv6_rec_small.onnx` 중국어 인식은 뺌) | **필요** |
| `tessdata/{kor,eng,osd}.traineddata` | Tesseract 한국어·영어·방향(LSTM 정확도 우선 `tessdata_best`) — `kreuzberg_ocr(10-30 지움 — pl-31, 지금 이 자산을 쓰는 엔진 없음)` 엔진만(`TESSDATA_PREFIX`) | GitHub `tesseract-ocr/tessdata_best` | `tessdata_best/` | 필요 없음 — `kreuzberg_ocr`은 스택에 없고 [pl-31](../prd/transform-cleanup.md#pl-31)에서 지움 |
| `fonts/GoNotoCurrent-Regular.ttf` | marker 렌더링 글꼴 | GitHub `satbyy/go-noto-universal` 릴리스 | `dl/` | 필요 없음 — marker 엔진은 이 저장소에 없음 |
| `wheels/en_core_web_sm-3.8.0-py3-none-any.whl` | spaCy 영어 모델 — `unstructured` 토큰화 | GitHub `explosion/spacy-models` 릴리스 `en_core_web_sm-3.8.0` | `dl/` | 필요 없음 — `unstructured`는 pl-31에서 지움 |
| `wheels/psycopg*.whl` 등 | PostgreSQL 드라이버(Linux x86_64·Python 3.12) | `pip download "psycopg[binary]==3.3.6" --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: -d dl/wheels_pg` | `dl/wheels_pg/` | 이미지 빌드에는 필요 없음 — 이미지는 `deploy/docker/wheels/`(폐쇄망 휠, §5-1)에서 설치 |

```bash
# 1) (인터넷 되는 PC) rapidocr 한국어 모델을 한 번 받는다 — 위 표의 python -c 한 줄
# 2) 채우기 — 원본 자리 기본은 저장소 루트(다른 곳이면 ASSET_SRC=<폴더>); 없는 원본은 "없음(건너뜀)"으로 넘어감
PYTHONPATH=. python deploy/release/assets.py pack      # → assets/ + assets/MANIFEST.json(해시·크기, 90 MB 넘으면 .partNN 조각)
# 3) 확인 — 설치 상태 표
PYTHONPATH=. python deploy/release/assets.py check
ls assets/rapidocr/*.onnx                              # build_ship.sh가 보는 것
```
- **git:** `assets/`·`dl/`·`tessdata_best/`는 git에 넣지 않는다(`.gitignore`). 이미지에는 `.dockerignore` 허용 목록(`!assets`)으로 들어간다. 새 체크아웃·worktree에서는 비어 있으니 메인 체크아웃의 `assets/`를 복사한다(§5-1).
- 모델 파일을 바꾸는 것은 새 이미지 버전이다(§2 C2).

## 6. 보관 기준 — 디스크

| 대상 | 남길 것 | 명령 |
|---|---|---|
| 이미지(2개 — `data-pipeline`·`mcp-server`) | 지금 버전 + 직전 버전(새 버전 검증 중 되돌리기용) · 옛 이름(`data-parsing`·`data-structure`·`data-retrieval`·`rag-*`)은 S6b 전환 확인 뒤 0개(S6c, 이력 C-29 ⑬ — [refactor_c_items.md](../history/refactor_c_items.md)) | `bash deploy/host/scripts/prune_old.sh --apply`(기본 dry-run, `--keep N`은 새 이름에만) — `docker system prune`·`-a`는 쓰지 않음(남의 이미지 보호) |
| 업데이트 폴더 `/srv/rag/code/updates/*` | 최근 2개 | 적용·확인 끝난 뒤 지움 |
| 코드 백업 `/srv/rag/code/backup-*` | 최근 2개 | 새 버전이 단계 1(샘플 기능)을 통과한 뒤 |

## 7. 릴리스 체크리스트 (고정 단계)

0. 서버에서 받은 서버 자체 개발 기록(`server-changes.md`의 `PC 보냄` 행)을 먼저 검토·병합(§3-4).
1. 테스트 통과(점검은 [CLAUDE.md](../../CLAUDE.md) §5-2·§6) → main 병합.
2. 바뀐 파일만 → §3(패치) 또는 §5(새 이미지) 중 맞는 경로로 전달.
3. 서버, 이 순서로:
   1. 서버 자체 개발 기록 읽기(§3-2).
   2. 새 이미지 버전이면 §5-2 배포 전 확인(`docker inspect <파싱 상주 컨테이너>` 마운트 원본 = `PATCH_CODE`).
   3. 적용(필요하면 서버 변경 다시 얹기·검토) → `check-modules`.
   4. DB 버전: `migrate check --target all` — 버전 기록 전이면 §5-5 처음 한 번, 버전이 바뀌는 릴리스면 `migrate up`. **적재·selftest 앞에** 한다(파싱·검색 MCP 컨테이너는 PG 없이도 시작한다).
   5. `selftest` 1개(`selftest_gate.sh` 판정 — 알려진 FAIL 밖 0, §3-3) → 로그·종료 코드 확인(실행 보드 `run_board`는 11-01에 지움 — e2-10).
4. `/srv/rag/reports/versions.md`에 버전 기록 한 줄 · 새 이미지 버전이면 `deploy/docker/IMAGE_BASE`를 그 버전의 커밋·태그로(§5).
5. 문제가 있으면 [server-guide.md](server-guide.md) §7 형식으로 이슈 기록 → PC가 수정 → 다음 패치로.

## 8. 0.2.0 배포 — 사람이 할 일

옛 refactor.md "최종 — 사람이 할 일"(0.1.0 — [history/deploy_0_1_0.md](../history/deploy_0_1_0.md))을 0.2.0에 맞게 다시 썼다(11-02). **지금 운영 서버는 0.1.0(settings.yaml 하나)으로 돈다**(사용자 11-02). 항목별 근거·상태는 [refactor.md](../refactoring/refactor.md)의 C 표다. 값·비밀은 이 문서에 쓰지 않는다. 누가: 사용자 · 서버 운영 · DB 담당(공유 PostgreSQL) · EDW 담당(회사 DB) · devops(빌드·반입).

### 8-1. 결정(사용자 11-02)

| 결정 | 내용 | PRD |
|---|---|---|
| 환경마다 다른 경로·접속은 settings.yaml 필수 | 게시 대상·Object Storage·EDW·PG·호스트 경로는 코드 기본값 없이 settings.yaml에만 적는다(비면 시작 거부). 컨테이너 안 경로는 이미지 기본값 표(`common/config/settings.py`) 한 곳만 — 호스트 기본값 `PATCH_CODE=/srv/rag/code/live`는 지운다(정리 3b) | [op-09](../prd/ops-settings.md#op-09) |
| 전체 e2e는 local·dev·prd 셋에서 | dev는 settings.yaml이 가리키는 대상(가짜 폴더든 실제든)에 쓴다. **전체 문서 실행은 prd에서만, 새 원천별 스키마 이름으로**(새 `PG_SCHEMA`). 판 0002가 기준 스키마의 옛 표를 지우므로 prd는 반드시 새 `PG_SCHEMA`를 쓴다(C-74). 옛 gold 스키마는 2주 남긴 뒤 DB 담당자가 백업하고 지운다. 옛 `struct` 스키마도 DB 담당자가 백업하고 지운다 | [pl-23](../prd/ops.md#pl-23) |
| 알려진 실패 0 | 배포 판정의 알려진 실패(`deploy/release/known_fail.txt`)를 비운다 — 쓰이지 않는 게시 가드(`source.json` 대조)와 `test_publish_guard`를 지움(정리 3c, C-54) | [pl-12](../prd/load.md#pl-12) |
| 이미지와 코드 | dev까지는 코드 없는 실행 이미지 + 코드 폴더. dev → prd는 이미지 + 시험한 코드를 굽는다(`bake.sh`). **prd는 settings.yaml(비밀 포함)도 이미지에 굽는다(사용자 선택) — 🔒 검토 등급 A(비밀 처리).** 다루는 규칙: ① 구운 이미지 파일(저장한 `.tar`·45 MB 조각 포함)은 비밀과 같다 — 운영 서버와 권한 있는 반입 경로에만 두고, 공용 레지스트리·공유 폴더·메일·채팅에 올리지 않는다 ② 키를 바꿀 때마다 다시 굽고, 옛 키가 든 이미지·조각은 지운다 ③ 굽고 나서 이미지 이력(`history`)·`inspect`·시작 로그에 값이 보이지 않는지 본다 ④ 굽는 데 쓴 settings.yaml 사본은 굽고 나서 지운다 | [op-07](../prd/doc.md#op-07) |
| 모델 | dev부터 내부망 GLM, PC(local)는 OpenRouter(유료 — CLAUDE.md §7 상한) | [pl-11](../prd/ops.md#pl-11) |
| 배포 전 검토 | 판 전체를 grill-me로 한 번 검토한다(사용자) | — |
| 새벽 배치 | 시작 시각·문서 수 상한·마감 시각이 settings.yaml 칸 — 비면 돌지 않는다. 칸 이름 어긋남(`pipeline.host.nightly.time` ↔ `ops.nightly.time`)을 고친다 | [pl-23](../prd/ops.md#pl-23) |
| Quote 표 · 고객 조인 사슬 | Quote 표는 지금 없다(그 단계만 건너뜀). 고객 조인 사슬은 운영 쪽이 고칠 수 있는 설정 파일로 바꾼다(정리 3d) | [pl-29](../prd/load.md#pl-29) |
| `adk.py` | 지시문은 두고 장치는 `llm.py` 호출 하나로 줄인다 — 0.2.0 지문 배치에서 CPU 부하 고침과 함께 | [pl-46](../prd/transform-cleanup.md#pl-46) |
| 설정 이관 | 0.1.0 settings.yaml → 0.2.0은 `common.config.migrate`의 옛 배치 바꾸기만 남긴다(env 파일 옮기기·`--compare`는 정리 3에서 지움) | [op-08](../prd/ops-settings.md#op-08) |
| 일회성 작업 컨테이너 | compose 작업 서비스(`parse`·`index_a`·`index_b`)와 `compose run --rm`을 지우고, 운영 작업·`dbtool`·`migrate`는 상주 `data-pipeline` 컨테이너에 `exec`로 돌린다. 빌드·반입 이미지 점검(`docker run --rm <새 이미지> selftest`)은 그대로(정리 3a) | [op-10](../prd/doc.md#op-10) |
| 내부망 코드 관리(P-08) | 내부망 gitea — [gitea-guide.md](gitea-guide.md) | — |

### 8-2. 배포 전

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 판 전체 grill-me 검토 — 지문 전후(릴리스 노트·PRD [e2-02](../prd/test.md#e2-02) — 바뀌면 서버 문서 재처리)·DB 스키마(판 0002·ParsingMeta DDL)·prd 비밀 굽기(8-1) | 사용자 | 등급 A |
| 2 | ParsingMeta DDL 한 번 — 칸 이름 바꾸기·`loaded_at`·판 칸·운영이 더한 분류·고객 칸 지우기(운영 분류 스크립트가 멈추므로 운영 담당에게 알림) | DB 담당·EDW 담당 | C-76 |
| 3 | PG — 새 `PG_SCHEMA` 이름(50자 이하) · 권한(DB 수준 CREATE, 원천 스키마 5벌의 읽기·쓰기, `doc_id_seq`) | DB 담당 | C-74 |
| 4 | 서버 settings.yaml 준비 — 필수 경로·접속(코드 기본값 없음 — 8-1) · EDW 읽기·쓰기 계정 · `search.server.fulltext_secret`·mcp-server의 Object Storage 읽기와 EDW 읽기 · `extract.input_source` 꼴 · 예전에 `-e`로 주던 값은 settings.yaml 칸으로 · 새벽 배치 칸은 비워 둠 | 서버 운영 | C-70·C-73·C-75·C-76 |
| 5 | 노출됐던 운영 키 교체(아직 안 했으면) — 새 값은 settings.yaml에만 | 서버 운영(보안) | C-10 |
| 6 | 덮기 설정 임시 파일 보안 검토 — 서버 `/tmp` 정리 주기·권한 600 | 사용자·서버 운영 | C-46 |
| 7 | 폐쇄망 휠·반입 자산(`assets/`) 채우고 빌드(§5-6 — `ALLOW_NO_ASSETS=1` 금지) | devops | — |
| 8 | 서버 이슈 기록(`server-changes.md`)을 읽고 새 코드에 들어 있는지 대조(§3-4) | 서버 운영(대조는 개발자) | — |

### 8-3. 배포 당일 — 개발 서버(dev) 먼저, 그다음 운영 서버(prd)

| # | 할 일 | 누가 | 명령 · C |
|---|---|---|---|
| 1 | 새벽 배치 멈춤, 진행 중인 `run_docs.py`가 끝나길 기다림 | 서버 운영 | §5-7 0 |
| 2 | 백업 — `settings.yaml.0.1.0` · `pg_dump` · 옛 코드 폴더·옛 이미지는 남김 | 서버 운영·DB 담당 | §5-7 1 |
| 3 | 새 판 받기 — dev: 실행 이미지 + 코드 폴더 · prd: 구운 이미지(8-1) | 서버 운영 | §5-7 2 · README §5-0 |
| 4 | 설정 옮기기 — `python -m common.config.migrate <0.1.0 settings.yaml> --out <새 파일>`(이미지 안에서) → 화면 보고서(옮긴 칸 수·지운 칸 이름)를 확인 → 새 파일로 바꿈(주인 UID 10001·권한 640) → 새 필수 칸·이미지 칸(`…:0.2.0`)을 채움 | 서버 운영 | §5-7 3 |
| 5 | DB — settings.yaml의 `PG_SCHEMA`를 새 이름으로 → `migrate check` → `migrate up --target all` → `check`(차이 없음) | 서버 운영·DB 담당 | §5-7 4 · C-74 |
| 6 | `selftest_gate.sh` — 알려진 실패 밖 FAIL 0(정리 3c 뒤에는 알려진 실패도 0개) | 서버 운영 | §3-3 · C-54 |
| 7 | 띄우기·확인 — 시작 로그 첫 줄의 판 · MCP `search`(원천 필수)와 원문 도구 한 번 | 서버 운영 | §5-7 5 · C-75 |
| 8 | 전체 e2e — dev: settings.yaml이 가리키는 대상으로 · prd: 전체 문서를 새 원천별 스키마로 → 검색 MCP를 새 스키마로 | 서버 운영·사용자 | 8-1 · [pl-23](../prd/ops.md#pl-23) |

되돌리기는 §5-7 "되돌리기(0.2.0 → 0.1.0)".

### 8-4. 배포 뒤

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 적재 기록 — 실행 기록의 `meta_missing`·`loaded_at_failed`가 0인지, ParsingMeta에 판·적재 시각이 채워지는지 | 서버 운영 | C-76 |
| 2 | 적재가 지우지 않는지·상주 컨테이너 `/tmp`·좀비 프로세스 | 서버 운영 | C-68 |
| 3 | 새벽 배치 — 시각·상한·마감 칸을 채울 때만 켬, `journalctl -u data-pipeline-nightly` | 서버 운영 | C-72 |
| 4 | 2주 뒤 옛 gold 스키마·옛 `struct` 스키마를 백업한 뒤 지움 | DB 담당 | C-74 |
| 5 | `versions.md`에 판 한 줄 · `deploy/docker/IMAGE_BASE` · 되돌리기가 필요 없어진 뒤 옛 이미지 정리(`prune_old.sh --apply`) | 서버 운영·devops | §6·§7 |
| 6 | 문제는 `server-changes.md`에 이슈로 → PC가 고침 → 다음 오버레이 패치 | 서버 운영·개발자 | [server-guide.md](server-guide.md) §7 |
| 7 | `query_edw` 오탐(T14 — [mc-06](../prd/mcp.md#mc-06)) — **확인:** 서버 MCP에서 실제 업무 SELECT 몇 개(JOIN·`WITH`·대괄호 이름·한글 별칭·`TOP`이 든 것)를 `query_edw`로 부른다. **기대:** 모두 행이 오거나 행·시간 상한 안내만 나온다 — 정상 SELECT가 `error`(`unterminated_*`·판단 못 함·허용 목록 밖)로 거부되면 그 SQL과 오류 코드를 `server-changes.md`에 적는다 | 서버 운영 | — |
| 8 | `edw_meta` 표 이름 끝 공백(T14 — [mc-07](../prd/mcp.md#mc-07)) — **확인:** 서버 카탈로그(`search.edw_meta.dir`의 `catalog.json`)에서 이름 끝에 공백이 있는 표를 찾아, `edw_meta`를 그 이름 그대로와 공백을 뺀 이름으로 각각 부른다. **기대:** 둘 다 같은 표의 칸 목록이 나온다(조회 키는 앞뒤 공백을 빼고 소문자로 맞춤 — `mcp_server/services/edw_meta.py`). "모르는 이름" 제안이 나오면 실패 | 서버 운영 | — |
| 9 | 질의 기록 쓰기(T14 — [mc-09](../prd/mcp.md#mc-09)) — **확인:** settings.yaml `search.query_log.dir`(비우면 이미지 안 `output/qa_log`) 폴더가 mcp-server 컨테이너에서 UID 10001로 쓰이는지 — `docker exec <mcp 컨테이너> sh -c 'id -u; touch <폴더>/.w && rm <폴더>/.w && echo ok'`, 그다음 `search`를 한 번 부르고 `qa_log.jsonl` 줄 수를 본다. **기대:** `10001`·`ok`가 나오고 줄이 하나 늘어난다. 권한 오류면 호스트 폴더 주인을 10001로(bind 마운트는 `:z`) | 서버 운영 | — |

## 9. (옮김 — 옛 §8·§9)

10-16 버전 설치 순서(옛 §8 — AI.ParsingMeta DDL `parsing_meta_mssql.sql` DBA 1회 실행, OCR OS 차이 측정, 이미지 크기 포함)와 10-21 오버레이 패치 번들(옛 §9)은 [docs/history/release_history.md](../history/release_history.md)로, 긴급 패치 이력은 [docs/history/patch-history.md](../history/patch-history.md)로 옮겼다(10-30, do-04).
