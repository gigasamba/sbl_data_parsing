# 릴리스 · 패치 — 이미지 기준 버전 + 오버레이 패치

↑ [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 스크립트: `deploy/release/{make_patch,build_ship,ship_stage,selftest_gate}.sh` · `deploy/host/scripts/prune_old.sh`

**전제**: 서버에는 이미지 2개(기준 버전)를 한 번 넣고, 그 뒤 코드 수정은 **바뀐 파일만 오버레이 패치**로 전달한다. 의존성(패키지·시스템 라이브러리·모델 파일)이 바뀔 때만 새 이미지 버전을 만든다.

## 1. 이미지 vs 오버레이 패치 — 무엇이 어디 있나

| 이미지 | `--target` | 담는 코드(이미지 안 `/app/deploy/<폴더>` · `/app/docker`) |
|---|---|---|
| `data-pipeline` | `pipeline` | `common`·`pipeline`(엔진·검토 루프·구조화·적재·퍼블리시)·`resources` + `assets/`(OCR 모델) + LibreOffice |
| `mcp-server` | `mcp` | `common`·`mcp_server`·`resources` + `pipeline/cli.py`(명령용) |

Answer Agent 이미지는 없다(10-14 결정 — 개발 서버 네이티브, MCP 테스트는 `run_tool.sh mcp_eval`). 옛 타깃 `core`·`all`·`parse`·`structure`·`retrieval`과 옛 이미지 이름은 없어졌다(S6b, D-020).

두 이미지 모두 `/app/docker`에는 이미지 안에서 쓰는 것만 든다 — `entrypoint.sh`(저장소 `deploy/docker/`)·`selftest_gate.sh`·`known_fail.txt`·`assets.py`(저장소 `deploy/release/`). compose·systemd·호스트 스크립트는 저장소 `deploy/host/`에 있고 이미지에 들어가지 않는다.

**서버 코드 폴더(live, `PATCH_CODE` — 기본 `/srv/rag/code/live`)** — `live/app/` = 컨테이너 마운트 원본(`app/deploy/<폴더>`·`app/docker` — 이미지 안과 같은 모양) · `live/deploy/{host,release}/` = 호스트에서 부르는 것(compose·systemd·`trigger.sh`·`mcp_up.sh`·`run_tool.sh`·`selftest_gate.sh` 등 — 저장소와 같은 자리). 사람·systemd는 `live`에서 `bash deploy/host/scripts/trigger.sh …`처럼 부른다.

**오버레이 패치가 바꿀 수 있는 것**(이미지는 그대로, 코드 폴더만 교체):
- 저장소 `common/`·`pipeline/`·`mcp_server/`·`resources/` → live `app/deploy/<폴더>/`
- `deploy/docker/entrypoint.sh`·`deploy/release/{selftest_gate.sh,known_fail.txt,assets.py}` → live `app/docker/`
- `deploy/host/`·`deploy/release/` → live `deploy/…`(호스트 스크립트)

**오버레이 패치로 못 바꾸는 것**(바꾸면 새 이미지 버전) — `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일·**서버 배포 테스트 `tests/server`**(이미지 안 `/app/deploy/tests`에만 있고 compose.patch*.yml이 붙이지 않는다 — 앱 코드만 패치하면 이미지 안 테스트는 옛 버전이므로, 테스트가 바뀐 번들은 새 이미지 버전으로, `refactor.md` C-53). S6b 전 배치(옛 `docker/`·upstream `deploy/<폴더>`)에서 이 배치로 넘어가는 패치 번들은 만들지 않는다(§3-1).

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

**리팩토링 버전(I6·I7·S2~S11 한 이미지 버전)은 [refactor.md](../../refactor.md) 머리의 "최종 — 사람이 할 일" 절**(사람 할 일의 정본 — 검토 등급 A·배포 전·때·뒤·다음 버전, 누가·언제·`C-xx`)을 따른다 — §5-1~§5-5는 그 안의 단계별 명령이다.

**`deploy/docker/IMAGE_BASE`** — 한 줄 `<커밋 7자> <이미지 태그>`, `make_patch.sh image`·`last`의 기준. 지금은 upstream 10-16 버전 `e305b14 20261016-e305b14`([release_history.md](../history/release_history.md) §8)라 이 저장소에 없는 커밋이다(`make_patch.sh`가 종료 코드 3 "새 이미지 버전 필요"). 새 이미지 버전을 서버에 넣은 뒤 그 버전을 만든 이 저장소 커밋·태그로 고쳐 커밋한다 — 그 뒤부터 오버레이 패치를 만들 수 있다. 둘째 항목(이미지 태그)은 버전으로 적는다(예 `<커밋 7자> 0.1.0`).

**버전(D-036, 10-29)** — 두 이미지(`data-pipeline`·`mcp-server`)는 같은 버전을 쓴다. 정본은 저장소 루트 `VERSION` 한 줄(SemVer `MAJOR.MINOR.PATCH`, 첫 배포 `0.1.0`).
- 올리는 규칙(D-009): MAJOR = MCP 도구 계약·DB 스키마·핸드오프 형식처럼 서로 맞춰야 하는 것이 깨질 때 · MINOR = 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 · PATCH = 오버레이 패치(코드만 교체). `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 git 태그 `v<버전>`(annotated)을 붙인다.
- 이미지 태그 = 버전(`data-pipeline:0.1.0`·`mcp-server:0.1.0`). `build_ship.sh`·`ship_stage.sh`는 태그를 안 주면 `VERSION`을 쓰고, 빌드한 커밋은 이미지 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`)에 남긴다 — `docker inspect -f '{{json .Config.Labels}}' data-pipeline:0.1.0`. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`).
- 버전 표기(`common.pipeline_version()` — 회사 DB `AI.ParsingMeta.pipeline_version`·실행 보드)는 이미지 안 `/app/deploy/VERSION`과 오버레이 패치의 `common/PATCH_VERSION`(`make_patch.sh`가 HEAD의 `VERSION`을 적음 — 이미지 태그와 같으면 종료 2) 중 높은 버전이다(10-29 전에는 git 짧은 커밋 — `refactor.md` C-62).

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

# 또는 저장만(95MB 조각 + sha256, 저장소 push는 사람이 따로)
bash deploy/release/ship_stage.sh pipeline mcp            # 태그 = VERSION(다른 태그면 첫 인자로: ship_stage.sh <태그> pipeline mcp)
```
**로컬 빌드** — 빌드 컨텍스트는 저장소 루트(Dockerfile은 `deploy/docker/Dockerfile` — 이미지 안 경로 `/app/deploy/<폴더>`·`/app/docker`). 루트 `.dockerignore`가 허용 목록이라 `common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`만 컨텍스트에 들어간다(`deploy/host`·`.venv`·`output`·`valid_env`·`.env.local`·코드 폴더 안 `output/`은 빠짐).
- Dockerfile pipeline 단계의 heredoc(`RUN python - <<'EOF'`) 때문에 **Docker 23 미만(예: 20.10)** 은 파일 전체를 못 읽는다 — `DOCKER_BUILDKIT=1 docker build --build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7 …`로 빌드한다(`docker/dockerfile` 이미지를 받으므로 인터넷 필요). `build_ship.sh`는 docker 버전을 보고 이 인자를 스스로 붙인다(`BUILDKIT_SYNTAX=<값>`으로 바꿀 수 있음). podman은 서버에서 확인한다.
- selftest 판정은 §3-3과 같다(`selftest_gate.sh` — 알려진 FAIL 밖 0).
- pipeline 이미지는 `assets/`(Git 제외, rapidocr 모델 — 준비는 §5-6)를 저장소 루트에 두고 빌드한다 — 새 체크아웃·worktree에서는 비어 있으니 먼저 복사한다. `build_ship.sh`는 pipeline 타깃에서 없으면 실패하고 `ALLOW_NO_ASSETS=1`로만 통과한다 — 그때 빈 `assets/`로 빌드되어 rapidocr 모델을 첫 실행에 받으려 한다(폐쇄망이면 실패). mcp는 assets를 쓰지 않는다.

### 5-2. 서버에서
```bash
# ship_stage.sh 조각(<repo>/images/<태그>/data-pipeline/pipeline.tar.gz.partNNN·pipeline.sha256 — mcp-server/는 mcp.*)이면 그 폴더에서:
cd <받은 폴더>/images/<태그>/data-pipeline
sha256sum -c pipeline.sha256 && cat pipeline.tar.gz.part* | gunzip -c | docker load    # mcp-server/에서는 mcp.sha256·mcp.tar.gz.part*
# build_ship.sh 한 파일(/var/tmp/data-pipeline_<태그>.tar.gz)이면: gunzip -c <그 파일> | docker load (build_ship.sh가 sha256 확인·적재까지 함)
```
그 뒤 패치 브랜치를 새 버전 기준으로 비운다(`make_patch.sh <새 기준 커밋>` — 바뀐 파일 0이어야 함).

**이미지·코드 폴더·`run_docs.py`는 같은 때에 바꾼다.** 셋 중 하나만 바꾸면 나머지가 깨진다(이미지의 패키지 배치·`compose.patch.yml`이 마운트하는 `app/deploy/<폴더>`·`run_docs.py`가 부르는 `python -m pipeline.…`가 서로 맞아야 함 — 확인 파일 `pipeline/extract/run_all.py`, `docflow_probe.py`는 이미지 안 `/app/deploy/pipeline/extract/`). 순서: 배치·상주 컨테이너 멈춤 → 이미지 적재 → 코드 폴더 전체 덮어쓰기(§4) → `run_docs.py` 교체 → 컨테이너를 새 이미지 + `compose.patch.yml`로 다시 띄움 — 한 번에 한다. 리팩토링 버전(I2·I4·S2~S11 — 패키지 `data_etl` → `pipeline`, 경로 정리)은 **한 이미지 버전으로만** 배포한다 — 나눠 배포하면 p1 code_fp가 두 번 바뀌어 서버 P1 캐시가 한 번 더 전부 빗나간다(refactor_plan 6-1 — `refactor.md` C-23). I4의 바뀐 설정·systemd 할 일은 [env-guide.md](env-guide.md) §5 I4 줄.

**S6b 전환(이미지 합침·`deploy/` 재배치 — 옛 3이미지 서버에 처음 넣을 때 한 번)** — 순서·되돌리기는 `refactor.md` C-04·C-29:
1. 새 이미지 2개(`data-pipeline`·`mcp-server`) 적재.
2. 옛 상주 컨테이너(`data-parsing`·`data-structure`·`data-retrieval`) 멈춤·삭제.
3. 코드 폴더 전체 덮어쓰기(§4 — 호스트 스크립트가 `live/deploy/host/`로).
4. 이미지 이름을 settings.yaml 항목 `pipeline.host.image`·`mcp.host.image`에 적는다(옛 env `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`). S7e1 버전부터 `pipeline.env`만 있으면 종료 코드 2, 옛 `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`(·`RAG_*`)는 안내 뒤 종료 코드 2 — 설정 옮기기는 §5-4.
5. systemd: 옛 `rag-nightly`·`data-retrieval-keepalive` unit disable·삭제, 새 `data-pipeline-nightly`·`mcp-server-keepalive` 설치(`daemon-reload`).
6. 새 compose(`deploy/host/compose/compose.pipeline.yml`·`compose.mcp.yml` + `compose.patch*.yml`)로 새 이름 컨테이너(`data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)를 띄운다.
7. MCP `parse_document`의 작업 서비스를 손으로 띄운다: `docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service`(`-e` 없이, 토큰은 settings.yaml `pipeline.service.parse_mcp.token`). compose·keepalive가 띄우지 않으므로 `data-pipeline-parse`가 다시 시작될 때마다 다시 띄운다.

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

### 5-4. 설정 이관 — 옛 `pipeline.env` → `settings.yaml`(S7e1 버전, 한 번)

S7e1(사용자 10-27, D-028) 버전부터 compose·셸·systemd·`run_docs.py`는 `$SERVER_ENV_DIR/settings.yaml`만 읽는다(옛 `pipeline.env`가 있고 settings.yaml이 없으면 "설정 이관 필요"로 종료 코드 2). **새 이미지 적재 뒤·컨테이너를 새로 띄우기 전에** 한다. 호스트 python에 pydantic·PyYAML이 없으면 `python -m …` 대신 이미지 안에서(아래 `docker run` 꼴).
```bash
cd /srv/rag/code/live
# ① 옮기기 — 화면에는 비밀을 가림, 파일은 실제 값
PYTHONPATH=app/deploy python -m common.config.migrate /srv/rag/env/pipeline.env --out /srv/rag/env/settings.yaml   # 서버 배치 코드 폴더 live/app/deploy(저장소 배치면 PYTHONPATH=.)
#   이미지 안: docker run --rm -i --network none --entrypoint bash data-pipeline:<태그> -c 'cat > /tmp/p.env && python -m common.config.migrate /tmp/p.env --out /tmp/s.yaml >&2 && cat /tmp/s.yaml' < /srv/rag/env/pipeline.env > /srv/rag/env/settings.yaml
# ② settings.sample.yaml의 [서버 옛 값: …] 항목(옛 options.conf가 채우던 값 — run_mode: prod·engine_scope: all·parse_post: all·max_rows: 1000 등, C-39·C-43
#    + 옛 compose 기본값 chain_structure_url·mcp.server.store: pg — C-47) 중 pipeline.env에 같은 이름이 없던 것만 settings.yaml에 옮겨 적는다 ·
#    특히 common.store.run_mode: prod — 빠뜨리면 PG 연결 실패 때 문서 레지스트리가 SQLite로 조용히 대체돼 run_docs 문서별 publish가 그 전 문서를 deleted·숨김으로 만든다(C-54) ·
#    EDW를 쓰면 common.connections.edw.user(필수 — C-47 ④) · run_docs.py를 쓰면 C-45 ③의 항목도
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

### 5-5. DB 버전 관리 — `migrate`(처음 한 번 버전 기록 + 버전이 바뀔 때)

S8a(사용자 10-28, D-030) 버전부터 pgvector의 우리 스키마 두 개(검색 `PG_SCHEMA` — 색인 빌더 `index --pg`의 `<PG_SCHEMA>_<index_id>` 포함, `struct`)의 표·색인·뷰는 **Alembic 리비전**으로 만든다. 실행 중 자동 DDL은 없다.
- `pgvector_load deploy`(= `trigger.sh load`·`night`가 load 앞에 부름): 새 스키마면 만들고 버전 기록, 버전 기록 있는 스키마면 버전 올리기(migrate up — 끝이면 그대로), **버전 기록 없는 기존 스키마면 비교·DDL 없이 경고만 찍고 적재를 계속**한다(빠진 표·색인은 ②의 check가 보여 주고 ③-b의 up이 만듦 — D-030 ④).
- struct는 표가 없으면 만들지 않고 "migrate로 만든다"고 알린다(문서 레지스트리·표 항목 적재가 그 자리에서 실패 — 호출자 처리 그대로).
- 버전 기록 표는 스키마마다 `<스키마>.alembic_version`(DB 담당 협의 — `refactor.md` C-48).
- 새 이미지(SQLAlchemy·alembic — 폐쇄망 휠, §5-1)를 적재한 뒤, 다음 적재(새벽 배치) 전에 한다. 값·비밀은 찍지 않는다(카탈로그·버전 번호만).
```bash
cd /srv/rag/code/live
. deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh
DC="docker compose -f deploy/host/compose/compose.pipeline.yml"   # 오버레이 패치 버전이면 -f deploy/host/compose/compose.patch.yml도(§3-2)
# ① 지금 버전 — 처음엔 "판 없음"(옛 코드가 만든 DB)
$DC run --rm load migrate current
# ② 비교(읽기만 — 잠금 없음) — 표 정의 ↔ 실제 DB: 표·컬럼·형식·NULL·기본값·키 + 색인 정의 글자 + 뷰 컬럼. 컬럼 순서·뷰 정의 글자(PostgreSQL 버전마다 꼴이 다름)는 "(알림)"만(판정 밖)
$DC run --rm load migrate check --target all
# ③-a 차이 0 → 실행 없이 버전만 기록 — struct는 S8b부터 버전 표 2개가 늘 "표 없음"이라 stamp가 거부(종료 2): 검색만 stamp(--target search), struct는 ③-b
#      (--target all로 stamp하면 search → struct 차례로 돌아 search는 기록되고 struct에서 종료 2 — 쓰지 않는다)
$DC run --rm load migrate stamp --target search
# ③-b 차이가 "표 없음·색인 없음·뷰 없음·뷰 칸 다름"뿐(예: struct에 쓴 기능의 표만 있음) → 없는 것만 만들고(뷰는 다시 만듦) 버전 기록(기준 리비전이 IF NOT EXISTS)
$DC run --rm load migrate up --target struct          # 검색 스키마도 ②에서 이런 차이뿐이면 up --target search(③-a stamp 대신) — refactor.md "최종" ③-7과 같은 꼴
# ③-c 컬럼 이름·형식·NULL·기본값·키가 다르거나 남는 표·컬럼·색인 → stamp·up 모두 거부(종료 2) — 멈추고 출력(이름만)을 DB 담당과 협의
# ④ 색인 빌더 스키마(index_a·index_b)도 스키마마다: migrate check|stamp|up --target search --schema <PG_SCHEMA>_<index_id>
# ⑤ 확인 — "판 끝 ['0001_search'] · 코드의 끝 판 0001_search … 비교: 차이 없음"·"판 끝 ['0002_struct'] · 코드의 끝 판 0002_struct … 비교: 차이 없음"(S8a 버전은 '0001_struct')
$DC run --rm load migrate check --target all
```
- **버전 기록 전에 적재가 돌면:** `pgvector_load deploy`·`load`(trigger load·night·run_docs)는 "판 기록 없음" 경고를 찍고 계속한다(기준 리비전 = 지금 스키마 — 결과 같음). 코드보다 낮은 버전이면 적재 전에 `migrate up`을 하라고 종료 2, DB가 코드보다 새 버전(모르는 리비전)이면 이미지·코드 버전을 맞추라고 종료 2(D-030 ⑤). 검색 MCP(읽기)는 버전을 보지 않는다.
- **새 검색 스키마(차원이 바뀜 — 새 `PG_SCHEMA`):** `migrate up --target search --schema <새 스키마> --bundle <번들>`(차원은 번들 meta.json — 또는 `--dim N`). vector 확장이 없으면 관리자 설치(공유 PG에서 `--create-extension`·`PG_CREATE_EXTENSION`을 켜지 않음).
- **버전이 바뀌는 릴리스:** 패치 노트의 "DB 판" 줄을 보고 적재 전에 `migrate up --target <갈래>` — 표·컬럼을 바꾸는 리비전은 데이터 계약 변경(검토 등급 A·DB 담당 협의 — D-008).
- **S8b 리비전(struct `0002_struct` — 버전 표 2개, D-031 · 🔒 검토 등급 A · `refactor.md` C-49):** struct에 엔진 구성 `stack_version`·원천 목록 `source_version`이 새로 생기고 버전 1(시드 — `resources/sql/0002_*_seed.json`, 그때의 git 파일 설정 항목)이 활성으로 들어간다. **새 이미지의 컨테이너(파싱·구조화·검색 MCP·파싱 MCP 서비스·트리거)는 이 버전 표를 못 읽으면 시작하지 않는다(종료 코드 4 — 사용자 10-28 Q7) — 파싱도 이제 PostgreSQL이 필요하다.** 그래서 새 이미지를 적재한 뒤 **컨테이너를 새 이미지로 띄우기 전에** 이 절의 ①~⑤를 끝낸다(struct는 ②에서 "표 없음: stack_version·source_version"·"색인 없음" 4개가 보이고 버전 기록 전이면 stamp가 거부 → ③-b `up`, 0001 기록이 있으면 `up`이 0002만 돈다).
  ```bash
  $DC run --rm load migrate up --target struct          # 0002 — 표 2개 + 버전 1(시드) 활성
  $DC run --rm load show-stack --history 5             # "stack 판 1 dev-v1 · sha …" — git 파일과 같은 구성
  $DC run --rm load show-sources --history 5
  # 서버 덮어쓰기 원천 목록($SERVER_ENV_DIR/sources.json — C-12)이 있고 git 기본과 다르면 버전 2로(컨테이너에 읽기 전용으로 붙여서)
  $DC run --rm -v "$SERVER_ENV_DIR/sources.json:/tmp/server_sources.json:ro,z" load \
      set-sources --file /tmp/server_sources.json --check-columns --reason "서버 덮어쓰기 이관(C-12)" --by "<사람>"
  ```
  - 바꾸기·되돌리기: `set-stack --parse … --reason …`(새 버전 + 활성 — 이미지에 없는 엔진이면 종료 2) · `set-stack --activate <버전 번호> --reason …`(되돌리기) · 원천 목록도 같은 꼴(`set-sources`). 오래 도는 검색 MCP는 시작 때 읽으므로 버전을 바꾼 뒤 다시 띄운다(`mcp_up.sh`) — 파싱 MCP 서비스는 작업마다 다시 읽는다. 자세히 [docs/architecture/pipeline_stack.md](../architecture/pipeline_stack.md).
  - 재사용 키: 엔진·프롬프트·핸드오프 핑거프린트는 그대로. 파이프라인은 버전 사본 `_stack/stack-v<버전>-<sha8>.json`을 쓰므로 **첫 실행에 AD41 색인(`index`)이 한 번 다시 지어진다**(입력 핑거프린트가 git 파일 바이트 → 사본 바이트 — `refactor.md` C-50). 회사 DB `AI.ParsingMeta.pipeline_version`은 사본과 무관(버전 표기 `pipeline_version()` — §5 "버전" · D-036 · `refactor.md` C-62).
- **계정의 기본 스키마가 우리 스키마여도 같음(VS8a B-1):** DB 계정의 `search_path`가 우리 스키마로 정해져 있거나(`ALTER ROLE … SET search_path`), 계정 이름 = 스키마 이름(`"$user"`), `PG_SCHEMA=public`이어도 ②가 표·컬럼을 그대로 비교한다. S8a 버전으로 버전을 기록했다면(그때는 "표 없음"만 보이고 ③-b가 컬럼이 다른 스키마도 기록했음) 지금 버전에서 ②를 다시 돌려 차이 0인지 확인한다.
- **모르는 리비전:** 버전 표에 코드가 모르는 리비전이 하나라도 있으면(새 이미지 → 옛 이미지로 되돌린 뒤 등) 적재·`up`·`stamp` 모두 종료 2.
- PC: `python -m common.store.db.dbtool <up|stamp|current|check> --target …`([CLAUDE.md](../../CLAUDE.md) §6 — 전용 PG에 처음 한 번 `up --target struct`) · 기본 스키마·vector 확장 자리 사례 `--pg-cases orca_<새 이름>`(새 테스트 DB를 만듦 — PC 전용).

### 5-6. 반입 자산(`assets/`) 준비 — 이미지 빌드 전

폐쇄망 서버는 첫 실행 때 모델을 인터넷에서 받을 수 없다. 그래서 pipeline 이미지를 빌드하기 전에 저장소 루트 `assets/`를 채운다. `build_ship.sh`는 `IMAGE_TARGET=pipeline`에서 `assets/rapidocr/*.onnx`가 없으면 멈춘다(`ALLOW_NO_ASSETS=1`이면 경고만 — PC 확인 빌드용, 서버에 올릴 이미지에는 쓰지 않음).

**지금 이미지가 쓰는 것은 `assets/rapidocr/*.onnx` 하나뿐이다**(Dockerfile이 `/app/assets/rapidocr/`를 rapidocr 패키지의 `models/`로 복사). 나머지 항목은 옛 서버 설치 길(`assets.py install`)에만 쓰이고 이미지 빌드에는 들어가지 않는다.

| `assets/` 안 | 무엇·누가 쓰나 | 받는 곳(공식 공개 배포) | 원본을 둘 자리(`assets.py pack`이 읽음) | 0.1.0 |
|---|---|---|---|---|
| `rapidocr/*.onnx` | RapidOCR 검출·방향·**한국어 PP-OCRv5 인식** 모델 — `rapidocr_ko` 엔진([PRD pl-22](../prd/parse.md#pl-22) — OCR 엔진은 기본 꺼짐)과 준비 단계 쪽 회전 판정([pl-02](../prd/parse.md#pl-02)) | `pip install rapidocr==3.9.2`(검출·방향·중국어 인식은 패키지에 들어 있음) → 한국어 인식 모델은 **첫 실행 때 받음**: 인터넷이 되는 PC에서 `python -c "from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType; RapidOCR(params={'Rec.lang_type': LangRec.KOREAN, 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE})"` 한 번 | 설치된 rapidocr 패키지의 `models/`(자동 — `PP-OCRv6_rec_small.onnx` 중국어 인식은 뺌) | **필요** |
| `tessdata/{kor,eng,osd}.traineddata` | Tesseract 한국어·영어·방향(LSTM 정확도 우선 `tessdata_best`) — `kreuzberg_ocr` 엔진만(`TESSDATA_PREFIX`) | GitHub `tesseract-ocr/tessdata_best` | `tessdata_best/` | 필요 없음 — `kreuzberg_ocr`은 스택에 없고 [pl-31](../prd/parse.md#pl-31)에서 지움 |
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
| 이미지(2개 — `data-pipeline`·`mcp-server`) | 지금 버전 + 직전 버전(새 버전 검증 중 되돌리기용) · 옛 이름(`data-parsing`·`data-structure`·`data-retrieval`·`rag-*`)은 S6b 전환 확인 뒤 0개(S6c, `refactor.md` C-29 ⑬) | `bash deploy/host/scripts/prune_old.sh --apply`(기본 dry-run, `--keep N`은 새 이름에만) — `docker system prune`·`-a`는 쓰지 않음(남의 이미지 보호) |
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
   4. DB 버전: `migrate check --target all` — 버전 기록 전이면 §5-5 처음 한 번, 버전이 바뀌는 릴리스면 `migrate up`. **selftest 앞에** 한다(selftest의 struct 사례가 settings.yaml PG의 struct 표를 씀 — 표가 없으면 "migrate로 만든다"로 FAIL). S8b부터는 **컨테이너를 새 이미지로 띄우기 전에**(버전 표 2개가 없으면 시작 거부 — 종료 4).
   5. `selftest` 1개(`selftest_gate.sh` 판정 — 알려진 FAIL 밖 0, §3-3) → 실행 보드(`run_board`) 확인.
4. `/srv/rag/reports/versions.md`에 버전 기록 한 줄 · 새 이미지 버전이면 `deploy/docker/IMAGE_BASE`를 그 버전의 커밋·태그로(§5).
5. 문제가 있으면 [server-guide.md](server-guide.md) §7 형식으로 이슈 기록 → PC가 수정 → 다음 패치로.

## 8–9. (옮김)

10-16 버전 설치 순서(옛 §8 — AI.ParsingMeta DDL `parsing_meta_mssql.sql` DBA 1회 실행, OCR OS 차이 측정, 이미지 크기 포함)와 10-21 오버레이 패치 번들(옛 §9)은 [docs/history/release_history.md](../history/release_history.md)로, 긴급 패치 이력은 [docs/history/patch-history.md](../history/patch-history.md)로 옮겼다(10-30, do-04).
