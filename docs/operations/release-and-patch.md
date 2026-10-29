# 릴리스 · 패치 — 이미지 기준판 + 덧씌우기

↑ [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 스크립트: `deploy/release/{make_patch,build_ship,ship_stage,selftest_gate}.sh` · `deploy/host/scripts/prune_old.sh`(S6b — 옛 `docker/`)

**전제**: 서버에는 이미지 2개(기준판 — S6b D-020, 전에는 3개)가 한 번 들어가고, 그 뒤 코드 수정은 **바뀐 파일만 덧씌우기**로 전달한다. 의존성(패키지·시스템 라이브러리·모델 파일)이 바뀔 때만 새 이미지 판을 만든다.

## 1. 이미지 vs 덧씌우기 — 무엇이 어디 있나

| 이미지 | `--target` | 담는 코드(이미지 안 `/app/deploy/<폴더>` · `/app/docker`) |
|---|---|---|
| `data-pipeline` | `pipeline` | `common`·`pipeline`(엔진·검토 루프·구조화·적재·게시)·`resources` + `assets/`(OCR 모델) + LibreOffice — S6b(D-020)에 옛 `data-parsing`(`parse`)·`data-structure`(`structure`)를 합침 |
| `mcp-server` | `mcp` | `common`·`mcp_server`·`resources` + `pipeline/cli.py`(명령용) — S6b에 옛 `data-retrieval`(`retrieval`)에서 이름만 바뀜(사용자 10-27) |
| (`answer-agent`) | — | 10-14 사용자 결정으로 제외 — Answer Agent는 개발 서버 네이티브, MCP 시험은 `run_tool.sh mcp_eval`(mcp-server) |

두 이미지 모두 `/app/docker`에는 이미지 안에서 쓰는 것만 든다 — `entrypoint.sh`(저장소 `deploy/docker/`)·`selftest_gate.sh`·`known_fail.txt`·`assets.py`(저장소 `deploy/release/`). compose·systemd·호스트 스크립트는 저장소 `deploy/host/`에 있고 이미지에 들어가지 않는다(S6b). (옛 타깃 `core`·`all`은 10-14, `parse`·`structure`·`retrieval`은 S6b에 없어짐.)

**서버 코드 폴더(live, `PATCH_CODE` — 기본 `/srv/rag/code/live`) 배치(S6b, 코디네이터 답 Q3 a)** — `live/app/` = 컨테이너 마운트 원본(`app/deploy/<폴더>`·`app/docker` — 이미지 안과 같은 모양, 전과 같음) · `live/deploy/{host,release}/` = 호스트에서 부르는 것(compose·systemd·`trigger.sh`·`mcp_up.sh`·`run_tool.sh`·`selftest_gate.sh` 등 — 저장소와 같은 자리, 전에는 `live/app/docker/`에 섞여 있었음). 사람·systemd는 `live`에서 `bash deploy/host/scripts/trigger.sh …`처럼 부른다.

**덧씌우기(패치 오버레이)가 바꿀 수 있는 것** — 저장소 `common/`·`pipeline/`·`mcp_server/`·`resources/`(→ live `app/deploy/<폴더>/`), `deploy/docker/entrypoint.sh`·`deploy/release/{selftest_gate.sh,known_fail.txt,assets.py}`(→ live `app/docker/`), `deploy/host/`·`deploy/release/`(→ live `deploy/…` — 호스트 스크립트)(이미지는 그대로, 코드 폴더만 교체). **덧씌우기로 못 바꾸는 것**(바꾸면 새 이미지 판 필요) — `deploy/docker/requirements*.txt`·`Dockerfile`·`wheels/`·시스템 패키지·`assets/` 모델 파일·**서버 반입 시험 `tests/server`**(S9 — 이미지 안 `/app/deploy/tests`에만 있고 compose.patch*.yml이 붙이지 않음: 덧씌우기로 앱 코드만 바꾸면 이미지 안 시험은 옛 판이라, 시험이 바뀐 묶음은 새 이미지 판으로 — `refactor.md` C-53). S6b 전 배치(옛 `docker/`·upstream `deploy/<폴더>`)에서 이 배치로 넘는 묶음은 만들지 않는다(§3-1).

## 2. 코드를 고칠 때 지킬 것 (덧씌우기로 전달 가능하게)

| # | 규칙 |
|---|---|
| C1 | 새 외부 패키지 import 금지(표준 라이브러리·이미 `requirements*.txt`에 있는 것만) |
| C2 | `requirements*.txt`·`Dockerfile`·`wheels`·`assets/` 모델 파일은 바꾸지 않는다(바꾸면 `make_patch.sh`가 종료 코드 3) |
| C3 | 이미지 경계를 넘는 import 금지 — `mcp_server`(mcp-server — S5 전 `data_retrieval`)가 `pipeline`(data-pipeline — S4 전 `data_etl`)을 import하면 안 됨, 그 반대도. `python -m common.check.check_modules`가 잡음 |
| C4 | 경로는 `__file__` 기준 상대 경로·env로만 — 절대 경로 금지, 쓰기는 `output/`(볼륨)에만 |
| C5 | `agent_platform/`은 10-26에 지웠다(I5, D-013) — LLM·VLM·임베딩 호출은 `common/ai/adk.py`·`llm.py`의 임시 대체 구현(I6)이 맡으므로 그 두 파일을 고친다. 옛 판 live의 `agent_platform`·`common_tools`·`data_*` 폴더는 S6b 새 이미지 판의 전체 덮어쓰기(§4)로 지운다(덧씌우기 묶음은 S6b 배치 뒤부터) |
| C6 | 새 모듈 폴더를 만들면 §1 표의 어느 이미지 경로인지 정하고, 서버 연결 옵션(아래 §3-2)이 그 폴더를 덮는지 확인 |
| C7 | 설정 기본값을 바꿀 때는 env로(코드 상수 변경은 덧씌우기로 되지만 커밋 메시지에 이유 한 줄) |
| C8 | 커밋 메시지·백로그에 **'덧씌우기 가능/새 이미지 판 필요'** 한 단어 |

## 3. 패치 오버레이 — 만들기 → 적용 → 확인

### 3-1. PC에서 묶음 만들기
```bash
bash deploy/release/make_patch.sh last <출력 폴더> ["이유 한 줄"] [이번 묶음 요약.md]
#   last(기본) = 직전에 올린 패치 이후(증분) · image = 이미지 기준판 이후 전부 · <커밋> = 그 커밋 이후 누적
```
의존성(§2 C2)이 기준판 뒤 바뀌었거나, 기준판·시작점이 이 저장소 배치(S6b — `deploy/docker/Dockerfile`·`common/core/fingerprint.py`가 있는 판)가 아니면(S6b 전 `docker/` 배치·upstream `deploy/<폴더>` 배치·이 저장소에 없는 기준판 커밋) 종료 코드 3 → §5(새 이미지 판)·§4(전체 덮어쓰기)로 — 이미지 COPY·compose 마운트·호스트 스크립트 자리가 달라 파일 교체·삭제로는 안 맞는다. 성공하면 출력 폴더에(경로는 **live 기준 그대로** — S6b):
- 바뀐 파일: `app/deploy/<common|pipeline|mcp_server|resources>/…`·`app/docker/…`(컨테이너 마운트 원본) · `deploy/host/…`·`deploy/release/…`(호스트 스크립트)
- `prev/`(바뀌기 직전 판 — 서버가 그 파일을 직접 고쳤는지 비교용)
- **`PATCH_MANIFEST.txt`** — `M <경로>`(교체)·`D <경로>`(삭제) 줄(live 기준) + 기준판·범위·전제(서버가 어느 커밋이어야 하는지)
- **`PATCH_NOTES.md`** — 서버 LLM이 먼저 읽는 설명서: 적용 규칙·"재파싱 필요?"·바뀐 env·커밋별 목적. "재파싱 필요?"는 **지문 값 비교**다(S6b, VS3 R-2): 시작점·HEAD 코드를 임시 폴더에 풀어 인계 지문 `FINGERPRINT`(다르면 parse부터 다시)·엔진 지문 27개(다르면 그 엔진 원문 재파싱)·참고로 code_fp 5개를 계산해 비교한다(계산에 `PY` — 기본 저장소 `.venv/bin/python`; 계산이 안 되면 "판정 불가"로 적힘)
- `CHANGES.md` — 패치 브랜치의 누적 이력(이번 절 추가)

`PATCH_COMMIT=1`이면 출력을 패치 브랜치(기본 `dev_server_patch`)에 새 커밋으로 쌓는다(push는 사람).

### 3-2. 서버에서 적용

**원칙 — 서버에서 자체로 진행한 것이 먼저다.** 서버는 실데이터로 돌려 보고 고친 곳이라, 서버 쪽 코드 수정·옵션 값·서버 전용 스크립트는 그대로 살리고 패치의 새 코드를 그 위에 합친다(패치가 서버 변경을 덮어 없애지 않게). 병합은 서버 LLM이 직접 끝까지 한다 — 충돌이 나도 멈추지 않고 아래 기준으로 합친 뒤, 무엇을 어떻게 합쳤는지 기록에 남긴다.

**먼저 서버 자체 개발 기록을 읽는다** — `/srv/rag/reports/server-changes.md`(서버에서 코드를 고치거나 옵션을 바꾼 건마다 한 행 + `server-changes/<ID>.diff`, 형식 [server-guide.md](server-guide.md) §7)와 서버 설정 파일 `/srv/rag/env/settings.yaml`(S7e2부터 — 옛 `pipeline.env`는 읽지 않음). 상태가 `서버에만`·`PC 보냄`인 행마다:

| 그 행의 파일이 이번 `PATCH_MANIFEST.txt`에 | 할 일 |
|---|---|
| 없음 | 그대로 둔다(덧씌우기가 안 건드림) |
| `M`(교체)로 있음 | 새 파일에 그 변경이 이미 들어 있으면(PC가 반영 — `PATCH_NOTES.md` 커밋 목적에 그 ID) 새 파일로 교체하고 `PC 반영됨 <커밋>`. 없으면 **새 파일 위에 서버 변경을 다시 얹는다**: `<ID>.diff`가 그대로 안 얹히면 그 변경의 뜻(행의 '무엇·왜')을 새 코드 구조에 맞게 손으로 옮긴다. 패치와 서버가 같은 줄·같은 동작을 다르게 바꿨으면 **서버 쪽 동작을 남기고**, 패치의 나머지 새 기능은 그 둘레에 붙인다. 행에 `다시 얹음 <패치 커밋>` + 합친 방법 한 줄 |
| `D`(삭제)로 있음 | 패치 노트에서 그 코드가 어디로 옮겨졌는지 보고, 옮겨진 곳에 서버 변경을 다시 얹는다. 옮겨진 곳이 없으면(기능 삭제) 서버가 그 파일을 쓰고 있는지 보고 쓰면 파일을 남긴다. 행에 처리 한 줄 |

**옵션(설정) 변경도 같은 원칙** — 서버에서 바꾼 옵션 값이 패치 뒤에도 그대로 동작해야 한다:
- 서버 `settings.yaml`에 적은 값은 패치가 기본값을 바꿔도 그대로 둔다(설정 파일이 코드 기본값보다 우선 — 손대지 않음).
- 서버가 코드 안 기본값(상수·설정 모델 기본값 등)을 직접 바꿨다면 그 값을 `settings.yaml`의 같은 칸(칸 자리는 저장소 `settings.sample.yaml` — 옛 env 이름으로 찾음)으로 옮겨 둔 뒤 새 파일로 교체한다(다음 패치부터는 코드 안 값이 덮여도 유지됨). 설정 칸이 없는 값이면 위 표대로 코드에 다시 얹는다. 옛 `options.conf`는 S7e2에 없어졌다.
- 패치가 설정 칸 이름·자리를 바꾸거나 없앴으면(`PATCH_NOTES.md` '바뀐 env'·`settings.sample.yaml` 차이) 서버가 쓰던 옛 칸의 값을 새 칸으로 옮긴다. 새로 생긴 칸은 기본값으로 두되, 서버에서 일부러 끈 기능(false)과 겹치면 끈 상태를 유지한다.
- 옮기거나 유지한 옵션은 모두 `server-changes.md` 행(또는 새 행)에 적는다.

기록이 없는데 `live`와 `prev/`가 다른 파일(기록 안 된 서버 수정)이 나오면 그것도 서버 자체 변경으로 보고 같은 방식으로 합치고, 그 자리에서 기록에 행을 추가한다.

```bash
cp -a <받은 폴더>/app <받은 폴더>/deploy /srv/rag/code/live/    # 묶음 경로 = live 경로(S6b) — 있는 쪽만
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
**selftest는 종료 코드로 판정하지 않는다** — selftest는 FAIL이 하나라도 있으면 종료 코드 1인데, pipeline 이미지(옛 structure 이미지의 사례를 포함 — S6b)는 리팩토링 전부터 있던 알려진 FAIL(S9b부터 1개 — `test_publish_guard`: 서버가 source.json을 안 올려 꺼진 방어선, `refactor.md` C-54 ② — PG 문서 대장 갱신 실패(C-54 ①)는 반입 판정 밖 일반 시험 `test_pub_registry` · 전에는 `build_bundle`·`publish_parse_result` 기대값 2개) 때문에 늘 1이라 고장과 구별이 안 된다. `selftest_gate.sh`가 selftest를 돌린 뒤 FAIL 줄을 알려진 목록 `deploy/release/known_fail.txt`(git 안, 이미지 안 `/app/docker/known_fail.txt`, 사례 이름 한 줄씩 + 이유 주석)와 대조해 마지막 `[판정]` 줄과 종료 코드를 낸다 — **목록 밖 FAIL 0이면 통과(0)**, 하나라도 있거나 요약 줄이 없으면 실패(1). 지금 기대값: data-pipeline FAIL 1(목록 안 `test_publish_guard` — S9b, 전에는 옛 structure의 2개 · 옛 parse 이미지의 `parse_agent` FAIL은 S6b에 시험을 고침) · mcp-server FAIL 0. **S9(10-28)부터 사례 = 서버 반입 시험 파일**(`tests/server/<common|pipeline|mcp>/test_*.py` — 이미지 안 `/app/deploy/tests/server`, 사례 이름 = 시험 모듈 이름 예 `tests.server.pipeline.test_build_bundle`). 옛 모듈 이름(`pipeline.transform.structure.build_bundle` 등)의 `python -m <모듈> --selftest`는 없어졌다 — 한 사례만 볼 때 `docker run --rm <태그> selftest --only <이름 조각>`. 이미지 안 목록으로 보려면 `docker run --rm --entrypoint bash <태그> /app/docker/selftest_gate.sh /app/docker/entrypoint.sh selftest`.

통과하면 `/srv/rag/reports/versions.md`에 한 줄: `날짜 · 서버 · 이미지 판 + patch <커밋> · 확인 결과`(다시 얹은 서버 변경 ID·유지한 옵션도). 실패하면 먼저 합친 곳을 다시 본다 — 서버 변경은 살린 채 패치 쪽 연결(새 함수 이름·인자·import)을 맞춰 고치고 다시 확인. 그래도 안 되면 그 패치 항목만 빼고(서버 쪽 판 유지) 나머지를 적용한 뒤 뺀 항목과 이유를 `issues.md`에 적는다. 서버 변경을 버려서 통과시키지는 않는다.

### 3-4. 서버 자체 개발을 PC(main)로 가져오기
서버에서만 고친 코드는 다음 패치·전체 덮어쓰기 때마다 다시 얹어야 하므로, PC가 main에 받아들이는 것이 기본이다.
1. 서버 → PC: `server-changes.md`의 `서버에만` 행과 `<ID>.diff`를 보낸다(반출 규칙은 이슈와 같음 — 코드·숫자·오류만, 문서 본문·고객명·키 값 없음). 보낸 행은 `PC 보냄`.
2. PC: 외부 PR처럼 읽고 검토하되 **서버가 실데이터로 고친 것이라 받아들이는 쪽이 기본** — diff·이유·서버 시험 결과를 보고 그대로 또는 PC 구조에 맞게 고쳐서 받아들이고, 버리는 것은 같은 문제를 PC 코드가 이미 다르게 풀었을 때만. 서버가 바꾼 옵션 값은 그 값을 기본값으로 올릴지(모든 서버에 맞는지) 따로 판단. 받아들이면 `jh/<ID>` 브랜치 → 시험 → main. 판단과 근거는 `docs/backlog/dev_his.md` '외부 PR·이슈 검토' 절에 한 행.
3. 다음 패치의 커밋 메시지에 그 서버 변경 ID를 적는다(`PATCH_NOTES.md` 커밋 목적에 나옴 → 서버가 §3-2에서 `PC 반영됨`으로 닫음). 버린 변경은 이유와 함께 서버에 알리고 행을 `폐기`로.

## 4. 전체 덮어쓰기 — 경로가 크게 바뀌었을 때(서버 기본값보다 단순)

덧씌우기가 비교 작업이 필요 없는 대신 "서버에서 직접 고친 코드"가 **사라진다** — 그래서 서버에서는 되도록 코드를 고치지 않고(설정이나 PC에 알리는 이슈로), 고쳤다면 반드시 `server-changes.md`에 기록한다. 덮어쓰기 전에 그 기록과 서버 설정 파일(`/srv/rag/env/settings.yaml` — S7e1 전 판은 `pipeline.env`)을 읽어 `서버에만`·`PC 보냄` 행을 확인하고, 덮어쓴 뒤 §3-2의 원칙(서버 자체 진행 우선 — 코드 변경 다시 얹기·옵션 값 유지)대로 합친다(새 코드에 이미 들어 있으면 `PC 반영됨`).
```bash
# 서버
cp -a /srv/rag/code/live /srv/rag/code/backup-<날짜시각>
rm -rf /srv/rag/code/live && mkdir -p /srv/rag/code/live/app/deploy /srv/rag/code/live/app/docker /srv/rag/code/live/deploy
Z=<받은 ZIP을 푼 저장소 루트>
cp -a $Z/common $Z/pipeline $Z/mcp_server $Z/resources /srv/rag/code/live/app/deploy/          # 컨테이너 /app/deploy/<폴더>
cp -a $Z/deploy/docker/entrypoint.sh $Z/deploy/release/selftest_gate.sh $Z/deploy/release/known_fail.txt $Z/deploy/release/assets.py /srv/rag/code/live/app/docker/   # 컨테이너 /app/docker(이미지 안과 같은 4개)
cp -a $Z/deploy/host $Z/deploy/release /srv/rag/code/live/deploy/                                 # 호스트 스크립트(S6b — 옛 live/app/docker/)
```
PC 쪽: push 전에 **RELEASE_NOTES.md**(이번 묶음 목적·바뀐 코드·바뀐 env·재파싱 필요 여부)를 같이 커밋 — `NOTES_ONLY=1 NOTES_NAME=RELEASE_NOTES.md bash deploy/release/make_patch.sh <직전 반입 커밋> <출력>`로 설명서만 생성(매니페스트·`prev/` 없음, 전체 모드 — 시작점이 S6b 전 배치면 종료 코드 3이므로 S6b 첫 반입의 설명서는 손으로 쓴다).

## 5. 새 이미지 판이 필요할 때

의존성(§2 C1·C2)이 바뀌었거나 덧씌우기가 너무 커졌을 때.

**리팩토링 판(I6·I7·S2~S11 한 이미지 판)은 [refactor.md](../../refactor.md) 머리의 "최종 — 사람이 할 일" 절**(사람 할 일의 정본 — 검토 등급 A·반입 전·때·뒤·다음 판, 누가·언제·`C-xx`)을 따른다 — 이 절(§5-1~§5-5)은 그 안의 단계별 명령이다.
- **`deploy/docker/IMAGE_BASE`**(한 줄 `<커밋 7자> <이미지 태그>` — `make_patch.sh image`·`last`의 기준)는 지금 upstream 판 `e305b14 20261016-e305b14`(10-16 판 — §8)라 이 저장소에 없는 커밋이다(`make_patch.sh`가 종료 코드 3 "새 이미지 판 필요"). 새 이미지 판을 서버에 넣은 뒤 그 판을 만든 이 저장소 커밋·태그로 고쳐 커밋한다 — 그 뒤부터 덧씌우기를 만들 수 있다.

**버전(D-036, 10-29)** — 두 이미지(`data-pipeline`·`mcp-server`)는 같은 버전을 쓴다. 정본은 저장소 루트 `VERSION` 한 줄(SemVer `MAJOR.MINOR.PATCH`, 첫 배포 `0.1.0`)이다.
- 올리는 규칙(D-009): MAJOR = MCP 도구 계약·DB 스키마·핸드오프 형식처럼 서로 맞춰야 하는 것이 깨질 때 · MINOR = 새 이미지 버전(의존성·Dockerfile·마운트 경로) 또는 큰 기능 · PATCH = 오버레이 패치(코드만 교체). `release/<버전>` 브랜치에서 `VERSION`을 고치고, main 머지 커밋에 git 태그 `v<버전>`(annotated)을 붙인다.
- 이미지 태그 = 버전(`data-pipeline:0.1.0`·`mcp-server:0.1.0`). `build_ship.sh`·`ship_stage.sh`가 태그를 안 주면 `VERSION`을 쓰고, 빌드한 커밋은 이미지 라벨 `org.opencontainers.image.revision`(커밋 안 한 변경이 섞이면 `-dirty`)에 남긴다 — `docker inspect -f '{{json .Config.Labels}}' data-pipeline:0.1.0`. 같은 태그가 이미 있으면 `build_ship.sh`가 멈춘다(다시 만들 때만 `FORCE_TAG=1`).
- 버전 표기(`common.pipeline_version()` — 회사 DB `AI.ParsingMeta.pipeline_version`·실행 보드)는 이미지 안 `/app/deploy/VERSION`과 오버레이 패치의 `common/PATCH_VERSION`(`make_patch.sh`가 HEAD의 `VERSION`을 적음 — 이미지 태그와 같으면 종료 2) 중 높은 버전이다. 10-29 전에는 git 짧은 커밋이었다(`refactor.md` C-62).
- `deploy/docker/IMAGE_BASE` 둘째 칸(이미지 태그)도 버전으로 적는다(예 `<커밋 7자> 0.1.0`).

### 5-1. 빌드 → 전송 → 적재
```bash
# 저장소 루트에서 — 2개(또는 바뀐 것만, S6b D-020). Docker 23 미만이면 아래 '로컬 빌드' 인자를 붙인다
V=$(cat VERSION)   # 두 이미지 같은 버전 태그(D-036) — 라벨까지 넣으려면 build_ship.sh(아래)를 쓴다
docker build -f deploy/docker/Dockerfile --target pipeline --build-arg APP_VERSION=$V -t data-pipeline:$V .
docker build -f deploy/docker/Dockerfile --target mcp      --build-arg APP_VERSION=$V -t mcp-server:$V .
# ↑ 직접 빌드는 assets/rapidocr가 없어도 멈추지 않고 빈 assets/로 빌드된다(S6b부터 — 전에는 COPY 실패). 먼저 `ls assets/rapidocr/*.onnx`로 확인하거나 build_ship.sh를 쓴다(아래 — 없으면 멈춤)

# 빌드만(빌드→selftest 판정→resources→비밀값 흔적 점검, 저장·전송 없음 — PC 확인용)
BUILD_ONLY=1 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh            # 태그 = data-pipeline:<VERSION> · 시험 빌드는 TAG=data-pipeline:<다른 태그>

# 한 번에(빌드→점검→저장→전송→적재→원격 점검, SSH 쪽으로)
TARGET=user@수집서버 IMAGE_TARGET=pipeline bash deploy/release/build_ship.sh

# 또는 저장만(95MB 조각 + sha256, 저장소 push는 사람이 따로)
bash deploy/release/ship_stage.sh pipeline mcp            # 태그 = VERSION(다른 태그면 첫 인자로: ship_stage.sh <태그> pipeline mcp)
```
**로컬 빌드(I3, 10-26 · S6b 10-27)** — 빌드 컨텍스트는 이 저장소 루트다(Dockerfile은 `deploy/docker/Dockerfile` — 이미지 안 경로 `/app/deploy/<폴더>`·`/app/docker`는 그대로). 루트 `.dockerignore`가 허용 목록이라 `common`·`pipeline`·`mcp_server`·`resources`·`deploy/docker`·`deploy/release`·`assets`만 컨텍스트에 들어간다(`deploy/host`·`.venv`·`output`·`valid_env`·`.env.local`·코드 폴더 안 `output/`은 빠짐 · 빈 틀 `common/config/*.example` 예외는 그 파일이 S7e2에 없어져 S11에 지움). Dockerfile pipeline 단계의 heredoc(`RUN python - <<'EOF'`) 때문에 **Docker 23 미만(예: 20.10)** 은 파일 전체를 못 읽는다 — `DOCKER_BUILDKIT=1 docker build --build-arg BUILDKIT_SYNTAX=docker/dockerfile:1.7 …`로 빌드한다(`docker/dockerfile` 이미지를 받으므로 인터넷 필요). `build_ship.sh`는 docker 판을 보고 이 인자를 스스로 붙이고(`BUILDKIT_SYNTAX=<값>`으로 바꿀 수 있음), podman은 서버에서 확인한다. selftest 판정은 §3-3과 같다(`selftest_gate.sh` — 알려진 FAIL 밖 0).

pipeline 이미지는 `assets/`(Git 제외, rapidocr 모델)를 저장소 루트에 두고 빌드한다 — 새 체크아웃·worktree에서는 비어 있으니 먼저 복사한다(`build_ship.sh`는 pipeline 타깃에서 없으면 기본 실패, `ALLOW_NO_ASSETS=1`로만 통과 — 그때 Dockerfile은 빈 `assets/`로 빌드하고 rapidocr 모델은 첫 실행에 받으려 함(폐쇄망이면 실패). mcp는 assets를 쓰지 않음).

### 5-2. 서버에서
```bash
# ship_stage.sh 조각(<repo>/images/<태그>/data-pipeline/pipeline.tar.gz.partNNN·pipeline.sha256 — mcp-server/는 mcp.*)이면 그 폴더에서:
cd <받은 폴더>/images/<태그>/data-pipeline
sha256sum -c pipeline.sha256 && cat pipeline.tar.gz.part* | gunzip -c | docker load    # mcp-server/에서는 mcp.sha256·mcp.tar.gz.part*
# build_ship.sh 한 파일(/var/tmp/data-pipeline_<태그>.tar.gz)이면: gunzip -c <그 파일> | docker load (build_ship.sh가 sha256 확인·적재까지 함)
```
그 뒤 패치 브랜치를 새 판 기준으로 비운다(`make_patch.sh <새 기준 커밋>` — 바뀐 파일 0이어야 함).

**I2(`data_etl`) 판부터 — 이미지·코드 폴더·`run_docs.py`를 같은 때에 바꾼다(V2-R4, I3).** 새 이미지는 `data_etl/` 배치이고(옛 `data_parsing/`·`data_structure/` 없음), `compose.patch.yml`은 코드 폴더의 `app/deploy/data_etl`을 마운트하며, `run_script/run_docs.py`는 `docker exec … python -m data_etl.…`를 부른다. 셋 중 하나만 바꾸면 나머지가 깨진다 — 배치·상주 컨테이너 멈춤 → 이미지 적재 → 코드 폴더 전체 덮어쓰기(§4) → `run_docs.py` 교체 → 컨테이너를 새 이미지 + `compose.patch.yml`로 다시 띄움 순서로 한 번에 한다. **I4(경로 정리, 10-26)는 I2(`data_etl`)와 같은 새 이미지 판으로만 반입한다 — I4만 따로 반입하지 않는다.** I4는 p1 층 파일(`vlm_page.py`)을 고쳐 p1 code_fp를 바꾼다. I2와 함께 가면 I2가 이미 바꾼 p1 캐시(`fbecc91af8b5`→`ae16de47e4d6`→`2c61c7375905`)를 한 번만 다시 돌지만, 따로 가면 서버 P1 캐시가 한 번 더 전부 빗나간다. I4의 바뀐 env·systemd 할 일은 [env-guide.md](env-guide.md) §5 I4 줄.
**S4(`pipeline`, 10-26)도 같은 방식이다.** 이미지(parse·structure는 `pipeline/` COPY, retrieval은 `pipeline/cli.py`만)·코드 폴더(`app/deploy/pipeline` — 옛 `app/deploy/data_etl`은 지움)·`run_docs.py`(`python -m pipeline.…`, 확인 파일 `pipeline/extract/run_all.py`, `docflow_probe.py`는 이미지 안 `/app/deploy/pipeline/extract/`)를 같은 때에 바꾼다. S2~S9는 한 판으로 반입한다(refactor_plan 6-1 — `refactor.md` C-23).
**S6b(이미지 합침·`deploy/` 재배치, 10-27)도 같은 판이다.** 새 이미지 2개(`data-pipeline`·`mcp-server`) 적재 → 옛 상주 컨테이너(`data-parsing`·`data-structure`·`data-retrieval`) 멈춤·삭제 → 코드 폴더 전체 덮어쓰기(§4 — 호스트 스크립트가 `live/deploy/host/`로) → 이미지 이름을 settings.yaml 칸 `pipeline.host.image`·`mcp.host.image`에 적음(옛 env `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE` — S7e1 판부터 `pipeline.env`는 읽지 않고 그것만 있으면 종료 코드 2, 옛 `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`(·`RAG_*`)는 안내 뒤 종료 코드 2 — 설정 옮기기는 §5-4) → systemd: 옛 `rag-nightly`·`data-retrieval-keepalive` unit disable·삭제, 새 `data-pipeline-nightly`·`mcp-server-keepalive` 설치(`daemon-reload`) → 새 compose(`deploy/host/compose/compose.pipeline.yml`·`compose.mcp.yml` + `compose.patch*.yml`)로 새 이름 컨테이너(`data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)를 띄움 → MCP `parse_document`의 작업 서비스를 손으로 띄움(`docker exec -d data-pipeline-parse python -u -m pipeline.mcp_parse_service` — `-e` 없이, 토큰은 settings.yaml `pipeline.service.parse_mcp.token` · compose·keepalive가 띄우지 않으므로 `data-pipeline-parse`가 다시 시작될 때마다 다시). 순서·되돌리기는 `refactor.md` C-04·C-29.

반입 **전** 확인(V4 R1) — `run_docs.py`·compose·systemd가 보는 `PATCH_CODE`(기본 `/srv/rag/code/live`)가 파싱 상주 컨테이너(S6b 반입 전에는 옛 이름 `data-parsing`, 뒤에는 `data-pipeline-parse`)가 지금 실제로 마운트하는 코드 폴더와 같은지 본다. 출력의 원본이 `<PATCH_CODE>/app/deploy/pipeline`(S4 전 판이면 `…/data_etl`)이 아니면(예: `<운영자 작업 폴더>/patch_code/…`) 운영 절차에서 `run_docs.py`를 `PATCH_CODE=<원본에서 /app/deploy/<폴더>를 뺀 앞부분>`으로 띄운다(반입 전 옛 배치 컨테이너면 `data_parsing`·`common_tools` 줄로 본다). 출력이 비면 덧씌우기 마운트 없이 이미지 안 코드로 떠 있는 것이다 — 반입 때 `compose.patch.yml`로 다시 띄운다:
```bash
docker inspect data-parsing --format '{{range .Mounts}}{{if eq .Destination "/app/deploy/pipeline" "/app/deploy/data_etl" "/app/deploy/data_parsing" "/app/deploy/common" "/app/deploy/common_tools"}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}{{end}}'   # 반입 전 = 옛 컨테이너 이름(S6b 뒤는 data-pipeline-parse)
```

반입 뒤 확인(`<코드 폴더>` = `PATCH_CODE`, 서버 기본 배치 `/srv/rag/code/live` — compose·systemd·`mcp_up.sh`·`run_docs.py`가 모두 같은 env를 본다). 폴더가 아니라 파일로 본다 — docker는 bind 마운트 원본이 없으면 빈 폴더를 만들어 붙이므로 `test -d`는 빈 폴더도 통과한다(V4 R2):
```bash
D=<코드 폴더>/app/deploy; test -f $D/pipeline/extract/run_all.py && test ! -e $D/data_etl && test ! -e $D/data_parsing && test ! -e $D/data_structure && echo "배치 OK(pipeline)" || echo "배치 어긋남 — pipeline 코드 없음 또는 옛 폴더 남음"
for c in data-pipeline-parse data-pipeline-structure; do docker exec $c test -f /app/deploy/pipeline/extract/run_all.py && echo "$c OK" || echo "$c 코드 없음(빈 마운트?)"; done
```
`run_docs.py`도 시작할 때 같은 확인(코드 폴더 `$PATCH_CODE/app/deploy` + 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`(S6b — 옛 `data-parsing`·`data-structure`) 안 `/app/deploy/pipeline/extract/run_all.py` 파일 — S4 전 판은 `data_etl/…`)을 하고, 어긋나면 이유를 찍고 종료 코드 2로 멈춘다(EDW·Object Storage 접속 전). 코드 폴더를 그 호스트에서 볼 수 없으면 폴더 확인은 건너뛰고(`[안내]` 한 줄) 컨테이너 확인(실제 마운트)만 믿는다(I4). 컨테이너 확인은 I4b부터 폴더(`test -d`)가 아니라 파일(`test -f`)이라 빈 마운트 폴더에서도 멈춘다.

`run_docs.py` 자리 — 서버에서 `<운영자 작업 폴더>/run_docs.py`로 두고 그 아래 `test_space/`(진행 기록 `batch_progress/`)를 쓴다(지금 예: `/home/<운영 계정>/dev/parsing_module/`). **S7e1(사용자 10-27 Q8)부터** 설정은 서버 settings.yaml(`--settings`·`SETTINGS_FILE`·`$SERVER_ENV_DIR/settings.yaml`, 호스트 python에 PyYAML 필요)에서 읽는다 — 운영 EDW·Object Storage 접속 값·비밀은 코드와 docker exec 명령 줄에서 지웠고(컨테이너는 붙인 설정 파일에서 읽음) 필요한 칸이 없으면 칸 경로만 찍고 종료 코드 2(목록 `refactor.md` C-45 ③). 작업 폴더는 `pipeline.host.run_docs_dir`(비우면 스크립트 옆 `test_space/`), 결과 공유 폴더(옛 `test_space/rfp_all_output`)는 `common.host.output_root`(`RAG_OUT` — 컨테이너 `/app/output` 원본 그대로), MCP 업로드 작업 폴더는 `mcp.host.jobs_dir`(기본 `<결과 폴더>/mcp_parse/jobs`), 코드 폴더 확인은 `common.host.patch_code`. `common.run_env`가 dev·stage·prd가 아니면 시작하지 않는다(로컬 실행 금지).

### 5-3. 작게 더할 때 — 이미지를 통째로 바꿔야 하나?

| 더하는 것 | 방법(작은 순) |
|---|---|
| 순수 Python 패키지(wheel) | 서버에서 덧층 빌드: wheel만 반입 → `FROM data-pipeline:<판>` + `pip install --no-index --find-links /wheels <패키지>` 2줄 Dockerfile → 새 태그 `<이름>:<판>+ocr1`(큰 이미지 재전송 없음) |
| 모델 파일(가중치) | 이미지 안 바꿈 — `-v /srv/rag/models/<엔진>:/app/assets/<엔진>:ro`로 연결 |
| 시스템 프로그램(바이너리) | 위 덧층에 오프라인 rpm/deb 설치 |
| 큰 프레임워크(torch 등 수 GB) | 새 이미지 판(§5-1) |

### 5-4. 설정 이관 — 옛 `pipeline.env` → `settings.yaml`(S7e1 판, 한 번)

S7e1(사용자 10-27, D-028) 판부터 compose·셸·systemd·`run_docs.py`는 `$SERVER_ENV_DIR/settings.yaml`만 읽는다(옛 `pipeline.env`가 있고 settings.yaml이 없으면 "설정 이관 필요"로 종료 코드 2). 새 이미지 적재 뒤·컨테이너를 새로 띄우기 전에 한다. 호스트 python에 pydantic·PyYAML이 없으면 `python -m …` 대신 이미지 안에서(아래 `docker run` 꼴).
```bash
cd /srv/rag/code/live
# ① 옮기기 — 화면에는 비밀을 가림, 파일은 실제 값
PYTHONPATH=app/deploy python -m common.config.migrate /srv/rag/env/pipeline.env --out /srv/rag/env/settings.yaml   # 서버 배치 코드 폴더 live/app/deploy(VS7e1 B-1 — 저장소 배치면 PYTHONPATH=.)
#   이미지 안: docker run --rm -i --network none --entrypoint bash data-pipeline:<태그> -c 'cat > /tmp/p.env && python -m common.config.migrate /tmp/p.env --out /tmp/s.yaml >&2 && cat /tmp/s.yaml' < /srv/rag/env/pipeline.env > /srv/rag/env/settings.yaml
# ② settings.sample.yaml에서 [서버 옛 값: …] 칸(옛 options.conf가 채우던 값 — run_mode: prod·engine_scope: all·parse_post: all·max_rows: 1000 등, C-39·C-43
#    + 옛 compose 기본값 chain_structure_url·mcp.server.store: pg — C-47)을 pipeline.env에 같은 이름이 없던 것만 settings.yaml에 옮겨 적는다 ·
#    특히 common.store.run_mode: prod — 빠뜨리면 PG 연결 실패 때 문서 대장이 SQLite로 조용히 대체돼 run_docs 문서별 publish가 그 전 문서를 deleted·숨김으로 만든다(C-54 — 옛 options.conf가 늘 채워 막던 길) ·
#    EDW를 쓰면 common.connections.edw.user(S7e2부터 필수 — C-47 ④) · run_docs.py를 쓰면 C-45 ③의 칸도
# ③ 대조 — 옛 실효 값(옛 카탈로그 값 + pipeline.env) ↔ 새 파일, 값은 안 찍음. "다름 0 · 옛에만 0 · 확인 필요 0"(종료 코드 0)일 때까지 ②를 고침
PYTHONPATH=app/deploy python -m common.config.migrate --compare /srv/rag/env/pipeline.env --settings /srv/rag/env/settings.yaml
# ④ 권한(C-09): 컨테이너 사용자 UID 10001이 읽어야 함
sudo chown 10001:<운영 계정 그룹> /srv/rag/env/settings.yaml && sudo chmod 640 /srv/rag/env/settings.yaml
# ⑤ 호스트 값 확인(비밀 없음) · 옛 파일은 되돌리기용으로 이름만 바꿔 남김
bash deploy/host/scripts/settings_env.sh common.run_env pipeline.host mcp.host common.host
sudo mv /srv/rag/env/pipeline.env /srv/rag/env/pipeline.env.before-s7e1
```
- **env 파일 읽는 규칙(S7e2 — VS7e1 B-3):** migrate는 옛 서버 컨테이너가 받던 값 그대로 옮기려고 docker compose v2의 `env_file` 규칙(compose-spec/compose-go `dotenv/parser.go`)으로 읽는다 — 따옴표 없음: 줄 끝까지·` #` 뒤 주석·`$` 치환 · 작은따옴표: 글자 그대로 · 큰따옴표: `\n`·`\t`·`\"`·`\\`·`\$` 등을 푼 뒤 `$` 치환. `$` 치환 값(같은 파일 앞 줄·compose를 띄운 셸 env)·podman-compose와 다른 꼴(`$X`)은 도구가 확실히 알 수 없어 **"확인 필요 <이름>: <이유>"**(값 없음)로 내고 `--compare`가 종료 1 — 그 이름의 옛 컨테이너 값(`docker exec <컨테이너> printenv <이름>` — 화면에 찍지 말고 견주기만)과 settings.yaml 값이 같은지 사람이 확인한다.
- **옛 이름 옮김(S7e2 — C-35):** `QA_CHAT_DECOMPOSE`·`SYNTHETIC_TRUTH`는 새 칸(`mcp.search.decompose_llm`·`common.models.guard.synthetic_truth`)으로 옮기고 "옛 이름 옮김" 줄에 이름만 낸다(새 이름이 같이 있으면 새 이름 값).
- **라이브러리 env(S7e2 — C-47 ③):** `TZ`·`OMP_NUM_THREADS`·`HF_HUB_OFFLINE` 등 허용 목록 이름은 `common.runtime.lib_env`로 옮긴다("라이브러리 env" 줄). 그 밖 "모델 밖" 줄은 settings.yaml로 옮길 수 없는 이름 — 서버가 쓰던 이름이면 알린다.
- **호스트 칸만(S7e3 — VS7e2 B-3):** 옛 env 파일에 `RUN_ENV=dev·stage·prd` 줄이 있으면(C-34 — 서버 env 파일 필수) `GOLD_DIR`는 "호스트 칸만" 줄로 `pipeline.host.gold_dir`에만 옮긴다. `RUN_ENV` 줄이 없는 파일이면 두 칸 모두에 넣고 "확인 필요(RUN_ENV 없는 파일 …)"로 알린다(`--compare`도 확인 필요로 종료 1 — S8a, VS7e3 R-3) — 서버가 `RUN_ENV`를 셸·systemd로만 주었다면 옛 env 파일 사본에 `RUN_ENV=<dev|stage|prd>` 줄을 적고 다시 옮긴다(앱 칸 `pipeline.paths.gold_dir`는 비움 — 컨테이너 앱은 `run_tool.sh`가 붙인 `/data/gold`를 읽음, 옛 `-e GOLD_DIR=/data/gold`와 같음). `--compare`도 같은 규칙이라 "같음". S7e2 판 migrate로 앱 칸까지 적었다면 지운다(`refactor.md` C-47 ⑨). 이관 뒤 값을 바꿀 때는 settings.yaml을 직접 고친다 — 덮기 파일 도구(`common.config.overrides`)는 PC 전용이라 서버에서 종료 2(D-029 ①).
- systemd unit 2개를 새 판으로 다시 복사하고 `daemon-reload`(옛 `EnvironmentFile` 줄이 빠짐 — 호스트 python에 pydantic이 없으면 `Environment=SETTINGS_IMAGE=data-pipeline:<태그>`를 더함).
- 되돌리기: 옛 판 코드 폴더(backup)·옛 이미지로 돌아갈 때 `pipeline.env.before-s7e1`을 `pipeline.env`로 되돌린다.

### 5-5. DB 판 관리 — `migrate`(S8a 판부터 — 처음 한 번 판 기록 + 판이 바뀔 때)

S8a(사용자 10-28, D-030) 판부터 pgvector의 우리 스키마 두 개(검색 `PG_SCHEMA` — 색인 빌더 `index --pg`의 `<PG_SCHEMA>_<index_id>` 포함, `struct`)의 표·색인·뷰는 **Alembic 판**으로 만든다. 실행 중 자동 DDL은 없다 — `pgvector_load deploy`(= `trigger.sh load`·`night`가 load 앞에 부름)는 확인 뒤 새 스키마면 만들고 판 기록, 판 기록 있는 스키마면 판 올리기(migrate up — 끝이면 그대로), **판 기록 없는 기존 스키마면 비교·DDL 없이 경고만 찍고 적재를 계속**한다(옛 deploy가 IF NOT EXISTS로 빠진 표·색인을 채우던 동작은 없음 — 빠진 것은 ②의 check가 보여 주고 ③-b의 up이 만듦, D-030 ④). struct는 표가 없으면 만들지 않고 "migrate로 만든다"고 알린다(문서 대장·표 칸 적재가 그 자리에서 실패 — 호출자 처리 그대로). 판 기록 표는 스키마마다 `<스키마>.alembic_version`(DB 담당 협의 — `refactor.md` C-48). 새 이미지(SQLAlchemy·alembic — 폐쇄망 휠, §5-1)를 적재한 뒤, 다음 적재(새벽 배치) 전에 한다. 값·비밀은 찍지 않는다(카탈로그·판 번호만).
```bash
cd /srv/rag/code/live
. deploy/host/scripts/settings_env.sh && load_settings && . deploy/host/scripts/image_vars.sh
DC="docker compose -f deploy/host/compose/compose.pipeline.yml"   # 덧씌우기 판이면 -f deploy/host/compose/compose.patch.yml도(§5-2)
# ① 지금 판 — 처음엔 "판 없음"(옛 코드가 만든 DB)
$DC run --rm load migrate current
# ② 비교(읽기만 — 잠금 없음) — 표 정의 ↔ 실제 DB: 표·칸·형식·NULL·기본값·키 + 색인 정의 글자 + 뷰 칸. 칸 순서·뷰 정의 글자(PostgreSQL 판마다 꼴이 다름)는 "(알림)"만(판정 밖)
$DC run --rm load migrate check --target all
# ③-a 차이 0 → 실행 없이 판만 기록 — S8b 판부터 struct는 판 표 2개가 늘 "표 없음"이라 stamp가 거부(종료 2): 검색만 stamp(--target search), struct는 ③-b(up --target struct — 아래 S8b 줄)
#      (--target all이면 갈래 차례(search → struct)로 돌아 search는 stamp·기록되고 struct에서 종료 2 — 쓰지 않는다)
$DC run --rm load migrate stamp --target search
# ③-b 차이가 "표 없음·색인 없음·뷰 없음·뷰 칸 다름"뿐(예: struct에 쓴 기능의 표만 있음) → 없는 것만 만들고(뷰는 다시 만듦) 판 기록(기준판이 IF NOT EXISTS)
$DC run --rm load migrate up --target struct          # 검색 스키마도 ②에서 이런 차이뿐이면 up --target search(③-a stamp 대신) — refactor.md "최종" ③-7과 같은 꼴
# ③-c 칸 이름·형식·NULL·기본값·키가 다르거나 남는 표·칸·색인 → stamp·up 모두 거부(종료 2) — 멈추고 출력(이름만)을 DB 담당과 협의
# ④ 색인 빌더 스키마(index_a·index_b)도 스키마마다: migrate check|stamp|up --target search --schema <PG_SCHEMA>_<index_id>
# ⑤ 확인 — "판 끝 ['0001_search'] · 코드의 끝 판 0001_search … 비교: 차이 없음"·"판 끝 ['0002_struct'] · 코드의 끝 판 0002_struct … 비교: 차이 없음"(S8b 판부터 — S8a 판은 '0001_struct')
$DC run --rm load migrate check --target all
```
- **판 기록 전에 적재가 돌면:** `pgvector_load deploy`·`load`(trigger load·night·run_docs)는 "판 기록 없음" 경고를 찍고 계속한다(기준판 = 지금 스키마 — 결과 같음). 코드보다 낮은 판이면 적재 전에 `migrate up`을 하라고 종료 2, DB가 코드보다 새 판(모르는 판)이면 이미지·코드 판을 맞추라고 종료 2(D-030 ⑤). 검색 MCP(읽기)는 판을 보지 않는다.
- **새 검색 스키마(차원이 바뀜 — 새 `PG_SCHEMA`):** `migrate up --target search --schema <새 스키마> --bundle <묶음>`(차원은 묶음 meta.json — 또는 `--dim N`). vector 확장이 없으면 관리자 설치(공유 PG에서 `--create-extension`·`PG_CREATE_EXTENSION`을 켜지 않음).
- **판이 바뀌는 릴리스(S8b 판 표 등):** 패치 노트의 "DB 판" 줄을 보고 적재 전에 `migrate up --target <갈래>` — 표·칸을 바꾸는 판은 데이터 계약 변경(검토 등급 A·DB 담당 협의 — D-008).
- **S8b 판(struct `0002_struct` — 판 표 2개, D-031 · 🔒 검토 등급 A · `refactor.md` C-49):** struct에 엔진 구성 `stack_version`·원천 목록 `source_version`이 새로 생기고 판 1(시드 — `resources/sql/0002_*_seed.json`, 그때의 git 파일 설정 칸)이 활성으로 들어간다. **새 이미지의 컨테이너(파싱·구조화·검색 MCP·파싱 MCP 서비스·트리거)는 이 판 표를 못 읽으면 시작하지 않는다(종료 코드 4 — 사용자 10-28 Q7) — 파싱도 이제 PostgreSQL이 필요하다.** 그래서 새 이미지를 적재한 뒤 **컨테이너를 새 이미지로 띄우기 전에** 이 절의 ①~⑤를 끝낸다(struct는 ②에서 "표 없음: stack_version·source_version"·"색인 없음" 4개가 보이고 판 기록 전이면 stamp가 거부 → ③-b `up`, 판 0001 기록이 있으면 `up`이 0002만 돈다).
  ```bash
  $DC run --rm load migrate up --target struct          # 판 0002 — 표 2개 + 판 1(시드) 활성
  $DC run --rm load show-stack --history 5             # "stack 판 1 dev-v1 · sha …" — git 파일과 같은 구성
  $DC run --rm load show-sources --history 5
  # 서버 덮어쓰기 원천 목록($SERVER_ENV_DIR/sources.json — C-12)이 있고 git 기본과 다르면 판 2로(컨테이너에 읽기 전용으로 붙여서)
  $DC run --rm -v "$SERVER_ENV_DIR/sources.json:/tmp/server_sources.json:ro,z" load \
      set-sources --file /tmp/server_sources.json --check-columns --reason "서버 덮어쓰기 이관(C-12)" --by "<사람>"
  ```
  - 바꾸기·되돌리기: `set-stack --parse … --reason …`(새 판 + 활성 — 이미지에 없는 엔진이면 종료 2) · `set-stack --activate <판 번호> --reason …`(되돌리기) · 원천 목록도 같은 꼴(`set-sources`). 오래 도는 검색 MCP는 시작 때 읽으므로 판을 바꾼 뒤 다시 띄운다(`mcp_up.sh`) — 파싱 MCP 서비스는 작업마다 다시 읽는다. 자세히 [docs/architecture/pipeline_stack.md](../architecture/pipeline_stack.md).
  - 재사용 열쇠: 엔진 지문·지시서 지문·인계 지문은 그대로. 파이프라인은 판 사본 `_stack/stack-v<판>-<sha8>.json`을 쓰므로 **첫 실행에 AD41 색인(`index`)이 한 번 다시 지어진다**(입력 지문이 git 파일 바이트 → 사본 바이트 — `refactor.md` C-50). 회사 DB `AI.ParsingMeta.pipeline_version`은 사본과 무관(판 표기 규칙 `pipeline_version()` 그대로 — git → env `PIPELINE_VERSION` → `common/PATCH_VERSION`, 이미지에는 `.git`이 없음 — `refactor.md` C-22·"최종" ④).
- **계정의 기본 스키마가 우리 스키마여도 같음(VS8a B-1 — S8b Step A):** DB 계정의 `search_path`가 우리 스키마로 정해져 있거나(`ALTER ROLE … SET search_path`), 계정 이름 = 스키마 이름(`"$user"`), `PG_SCHEMA=public`이어도 ②가 표·칸을 그대로 비교한다(S8a 판은 이때 "표 없음"만 보이고 ③-b가 칸이 다른 스키마도 판 기록했음 — S8a 판으로 판을 기록했다면 이 판에서 ②를 다시 돌려 차이 0인지 확인).
- **모르는 판:** 판 표에 코드가 모르는 판이 하나라도 있으면(새 이미지 → 옛 이미지로 되돌린 뒤 등) 적재·`up`·`stamp` 모두 종료 2.
- PC: `python -m common.store.db.dbtool <up|stamp|current|check> --target …`([CLAUDE.md](../../CLAUDE.md) §6 — 전용 PG에 처음 한 번 `up --target struct`) · 기본 스키마·vector 확장 자리 사례 `--pg-cases orca_<새 이름>`(새 시험 DB를 만듦 — PC 전용).

## 6. 보관 기준 — 디스크

| 대상 | 남길 것 | 명령 |
|---|---|---|
| 이미지(2개 — `data-pipeline`·`mcp-server`) | 지금 판 + 직전 판(새 판 검증 중 되돌리기용) · 옛 이름(`data-parsing`·`data-structure`·`data-retrieval`·`rag-*`)은 0개(S6c — S6b 전환 확인 뒤, `refactor.md` C-29 ⑬) | `bash deploy/host/scripts/prune_old.sh --apply`(기본 dry-run, `--keep N`은 새 이름에만) — `docker system prune`·`-a`는 쓰지 않음(남의 이미지 보호) |
| 업데이트 폴더 `/srv/rag/code/updates/*` | 최근 2개 | 적용·확인 끝난 뒤 지움 |
| 코드 백업 `/srv/rag/code/backup-*` | 최근 2개 | 새 판이 단계 1(샘플 기능)을 통과한 뒤 |

## 7. 릴리스 체크리스트 (고정 단계)

0. 서버에서 받은 서버 자체 개발 기록(`server-changes.md`의 `PC 보냄` 행)을 먼저 검토·병합(§3-4).
1. L0~L3 시험 통과(upstream `docs/testing.md` — 이 저장소에는 없음, 점검은 [CLAUDE.md](../../CLAUDE.md) §5-2·§6) → main 병합.
2. 바뀐 파일만 → §3(패치) 또는 §5(새 이미지) 중 맞는 경로로 전달.
3. 서버: 서버 자체 개발 기록 읽기(§3-2) → (새 이미지 판이면 §5-2 반입 전 `docker inspect <파싱 상주 컨테이너>` 마운트 원본 = `PATCH_CODE` 대조) → 적용(필요하면 서버 변경 다시 얹기·검토) → `check-modules` → DB 판(`migrate check --target all` — 판 기록 전이면 §5-5 처음 한 번, 판이 바뀌는 릴리스면 `migrate up`, S8a — selftest 앞: selftest의 struct 사례가 settings.yaml PG의 struct 표를 씀, 표가 없으면 "migrate로 만든다"로 FAIL · S8b — 컨테이너를 새 이미지로 띄우기 전: 판 표 2개가 없으면 시작 거부(종료 4)) → `selftest` 1개(`selftest_gate.sh` 판정 — 알려진 FAIL 밖 0, §3-3) → 실행판(`run_board`) 확인.
4. `/srv/rag/reports/versions.md`에 판 기록 한 줄 · 새 이미지 판이면 `deploy/docker/IMAGE_BASE`를 그 판의 커밋·태그로(§5).
5. 문제가 있으면 [server-guide.md](server-guide.md) §7 형식으로 이슈 기록 → PC가 수정 → 다음 패치로.

## 8. 10-16 판 설치 순서(1회 — 폴더 분리·output·3이미지)

> **기록(10-16 판)** — 아래 표의 이미지 3개·`docker/` 경로·`DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`는 그 판의 것이다. S6b(10-27, D-020)부터 이미지는 `data-pipeline`·`mcp-server` 2개, 스크립트는 `deploy/{docker,release,host}/`, 이미지 변수는 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`, 컨테이너는 `data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`, systemd는 `data-pipeline-nightly`·`mcp-server-keepalive`다 — 전환 절차는 §5-2 S6b 줄과 `refactor.md` C-04·C-29.

이번 판은 경로가 전부 바뀌어 덧씌우기가 아니라 **새 이미지 판 + 전체 재배포**다(§4·§5). 기준 커밋은 PC가 알려 준 main(10-14 컷 d82d6519 이후 통합 시험 수정 포함). 순서대로:

| # | 할 일 | 확인 |
|---|---|---|
| 1 | PC: 이미지 3개 빌드(`--target parse`·`structure`·`retrieval`, §5-1) — 옛 rag-core·rag-all·answer-agent 이미지는 없음(Answer Agent는 개발 서버 네이티브) | `bash docker/selftest_gate.sh docker run --rm <이미지> selftest` 3개 다 `[판정] 통과`(알려진 FAIL 밖 0, §3-3 — 10-16 당시 기준 "종료 코드 0"은 structure의 알려진 FAIL 2개 때문에 I3에서 바꿈) |
| 2 | 서버: 배치(systemd 타이머)·MCP·상주 트리거 컨테이너 멈춤 | `docker ps`에 data-*/rag-* 없음 |
| 3 | 서버: `sudo mv /srv/rag/out /srv/rag/output` · `pipeline.env`의 `RAG_OUT=/srv/rag/output`(결과 경로를 적어 둔 다른 값·systemd·cron도) | `ls /srv/rag/output` |
| 4 | 서버: 새 `pipeline.env.example`과 비교해 새·바뀐 키 반영 — `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`(옛 `RAG_*_IMAGE`는 한 판 동안 별칭) · 결과 게시 키는 예시 파일에 없음 — [env-guide.md](env-guide.md) 표의 `PM_*`(새 `PM_PATH_MAP` = 결과 경로 앞부분 바꾸기, 옛 PM_STRIP_PREFIX 대체) | `docker run --rm --env-file … data-parsing:<태그> check` |
| 5 | 서버: 이미지 적재(§5-2) | `docker images | grep data-` 3개 |
| 6 | **DBA**: EDW에 [`docs/operations/parsing_meta_mssql.sql`](parsing_meta_mssql.sql) 1회 실행(S1부터 저장소 문서 자리 — 코드 폴더·덧씌우기 묶음에 없으므로 DBA에게 따로 전달)(AI.ParsingMeta — `parse_date` 글자형 `YYYY-MM-DD_HHMMSS`, `rep_key` = 문서 폴더 URI) — **첫 `publish`(= `data_etl.load.publish_parse_result --apply`) 전에**. **PM2(10-15) 반영 — DBA가 이 표를 아직 한 번도 안 돌렸으면 지금 이 최신 판(필수 열은 `doc_key` 하나뿐, `engines_used`·`engines_summary` 포함)을 그대로 실행 — 옛 판 먼저 돌리지 않음** | 표·필터 유일 색인 두 개(source_key 있음/없음) 생성됨 |
| 7 | 서버: `docker port`로 기존 pgvector·OpenViking이 호스트 포트를 열었는지 확인(열려 있으면 host 네트워크 그대로 — XS5) · 실행 계정 docker 그룹(SI12) | 연결 점검 `services` |
| 8 | 서버: 샘플 몇 건 `smoke --src <폴더>`(data-parsing → data-structure → data-retrieval) | 요약에 단계 실패 없음 |
| 9 | 서버: 첫 실파싱 = **전체 재파싱 1회**(TB6로 27개 엔진 지문이 바뀜 · CT1로 인계 FINGERPRINT도 바뀌어 옛 `_DONE` 표식은 불일치 종료 코드 3 — 정상, 다시 돌리면 됨) + 구조화 1회 재실행 — 실행 시간을 미리 잡을 것 | `run_board` 실행판 |
| 10 | 서버: MCP 상주(`compose.mcp.yml`)·필요하면 상주 트리거(`serve-trigger`) 기동 · 자정 배치 다시 켬 | `/health` ready · `mcp_smoke` |
| 11 | 확인: G17(고객명 교차언어 별칭) 기본 켬 — 실문서에서 1위 정답 하락이면 `SEARCH_VECTOR_ALIAS_EXPAND=0` (10-21 판단) | 실문서 질문 몇 개 |
| 12 | `/srv/rag/reports/versions.md`에 판 기록(이미지 태그·기준 커밋) | — |

10-21: 위 9·11 결과와 긴급 수정을 담아 재설치·재시험(§7).

**알려진 차이(10-15 PC Docker 점검, 태그 20261016-4737a95)** — 한국어 OCR(rapidocr_ko)이 같은 모델 파일인데도 컨테이너(Linux)와 PC(Windows)에서 스캔 쪽 하나를 다르게 읽음(`scan_report.pdf` 2쪽 — PC "월간 생산 보고(2쪽)", 컨테이너 "() "). 통합 22문서를 컨테이너로 파싱해 PC 채점기로 매기면 값 재현율 0.9813·표 칸 1.0·검색 hit1 0.75·hit5 0.90은 기준선과 같고 글자 정확도만 0.7942 → 0.7912(−0.003, 그 문서 0.577 → 0.512) — 회귀 문턱 0.01 안. 라이브러리 버전은 numpy 2.5.4 vs 2.5.3 외 같음 → onnxruntime·opencv의 OS별 수치 차이로 보고 버전 고정은 안 함. 서버(Linux)에서 정답률을 잴 때 기준은 **컨테이너 결과**로 잡을 것.

**이미지 크기(같은 점검)**: data-parsing 3.25 GB(전송 tar.gz 858 MB, 95 MB 조각 10개) · data-structure 1.29 GB(286 MB, 4조각) · data-retrieval 1.29 GB(286 MB, 4조각) — 구조화·검색은 공통 기반 층을 같이 써서 서버 디스크엔 한 번만 올라감.

**10-16 최종 판(10-15 확정)** — 이미지 태그 `20261016-e305b14` · 기준 커밋 main `e305b14`(`deploy/docker/IMAGE_BASE`에 기록 — 이후 `make_patch.sh image`·`last`의 기준) · 전송 파일 `output/ship/data_parsing_split/images/20261016-e305b14/{data-parsing 858 MB·10조각, data-structure 286 MB·4조각, data-retrieval 286 MB·4조각}` + 각 `.sha256`.
PC 확인(10-15): 이미지 3개 컨테이너 selftest rc=0(parse 55/55·structure 30/30·retrieval 35/35, 건너뜀은 다른 이미지 모듈과 PC 전용 평가 도구 3개뿐) · 서버 받기 모의(sha256 확인→재조립→rmi→load→selftest) 3개 모두 통과 · 컨테이너 문서 3건(office·kreuzberg·rapidocr_ko) 파싱 · 같은 커밋 네이티브 전체 시험 920 통과·check_modules 통과 · 통합 22문서 e2e(고정 질문) 기준선과 같음(컨테이너는 위 '알려진 차이' −0.003만).
이미지에 없는 것(PC 전용): `openpyxl` — `mcp_eval --xlsx`(엑셀 보고서)는 서버에서 안 됨, 보고서는 PC에서.

## 9. 10-16 판 위 덧씌우기 묶음(10-21 반영 예정 — 기준 `IMAGE_BASE` = e305b14)

`make_patch.sh image <출력>`이 아래 파일을 모은다(바뀐 파일만, 새 이미지 판 아님). 적용 뒤 서버 단계까지 같이.

날짜·시각이 붙은 이력: [patch-history.md](patch-history.md)(이 절에서 자동 생성 — `backlog_xlsx.py`).

| 항목 | 커밋 | 파일(이미지) | 서버에서 할 일 |
|---|---|---|---|
| GL1 고객 명부 새 양식·용어집 빈칸 | 0e7d64cd | `common_tools/terms.py`(3개 모두) | 명부(`CLIENT_ROSTER`)·용어집(`GLOSSARY_DIR`)을 새 양식으로 — env-guide 해당 행 |
| GL2 검색 DB 고객 칸·OpenViking 머리말 | 45dd78f1 | `data_structure/pg/schema.sql`·`pgvector_load.py`·`openviking_load.py`(structure) · `data_retrieval/pgsearch.py`(retrieval) · `common_tools/store/pg_standin.py`(3개 모두) | 구조화 적재 1회(고객 칸·GIN 색인·기존 데이터 채우기, 200문서마다 저장) → **검색 MCP 재시작** · 끄기 `OV_TAGS=0` |
| PM2 파싱 메타 열·키 최소화 + 엔진 전부 기록 | 1db61d7f | `data_structure/sql/parsing_meta_mssql.sql`·`data_structure/tools/parsing_meta.py`·`data_structure/publish_parse_result.py`(structure) · `common_tools/store/parsing_meta_db.py`(3개 모두) · `data_parsing/represent.py`(parse — `tried`에 엔진 판, `post.vlm_models` 추가) | **DBA가 AI.ParsingMeta DDL을 아직 한 번도 안 돌렸으면** 이 판을 그대로 1회 실행(§8 단계 6) — 이미 PM1 옛 판을 돌렸다면 이 패치는 DBA 재작업이 더 생김(사람 조정 필요, 코드가 ALTER는 안 함) |
| OC1 OCR 스레드 상한 | 583127cb | `data_parsing/engines/rapidocr/parser.py`·`data_parsing/prepare.py`(parse) | 없음(자동 — 프로세스당 CPU 몫, 덮어쓰기 `OCR_THREADS`) |
| OC2 3단계(VLM) 스레드 몫 | 21365ffe | `data_parsing/run_all.py`·`data_parsing/tools/resources.py`(parse) | 없음(CPU ÷ (procs × workers)) |
| DT2 명부·용어집 예시 | eaafbc70 | `common_tools/glossary/*.example.csv`(3개 모두) | 예시 보고 명부·용어집 작성 — server-guide 5-1 |
| GL1b 명부 줄에 칸이 더 있어도 안 죽음 | 43f17721 | `common_tools/terms.py`·`common_tools/options.conf`(3개 모두) | 없음 |
| TA1 표 영역 조립(엔진 격자 모아 본문 제자리 표) | 9c3c9085 | `data_parsing/postprocess/table_inline.py`(새 파일)·`data_parsing/represent.py`(parse) · `data_structure/tools/parsing_meta.py`(structure) · `common_tools/cli/pipeline.py`·`options.conf`(3개 모두) | 파싱 본문이 바뀜 — 표가 있는 문서는 다음 재파싱 때 반영(급하면 해당 문서 `--force`) · 끄기 `PARSE_TABLE_INLINE=0` |
| TS1 표 구조 채점(평가 도구) | ebc92cca | `data_parsing/evaluation/score_gold.py`·`prompts/table_struct_judge/`(parse) · `common_tools/report_templates/criteria.json` | 없음(평가 때만, LLM 판정 기본 끔) |
| EQ1 EDW SQL 질의 도구(검색 MCP `describe_edw`·`query_edw`) | bc5facb3 | `data_retrieval/tools/edw_query.py`(새 파일)·`data_retrieval/mcp_server.py`·`data_retrieval/tools/qa_log.py`(retrieval) · `common_tools/options.conf`·`agent_platform/export_mcp_tool_schema.py`(3개 모두) | **DBA**: EDW 읽기 전용 계정(허용 표 SELECT만·`DENY VIEW DEFINITION`·다른 DB/연결 서버 권한 없음) → `pipeline.env`에 `EDW_QUERY_CONN_FILE`(또는 `EDW_QUERY_SERVER`)·`EDW_QUERY_TABLES`(비우면 전부 거부) → **검색 MCP 재시작** · 끄기 `EDW_QUERY=0` — server-guide 4-1 |
| GL3 명부 생성기 새 양식·상태 대소문자 무시·고객 마스터 예시 | 5da9bea9 | `common_tools/cli/gen_roster.py`·`common_tools/terms.py`·`common_tools/glossary/client_master.example.csv`·`client_master_map.example.json`(3개 모두) | 고객 마스터 → 명부 만들기 — server-guide 5-1 |

이 묶음에서 빠짐(사용자 10-15 결정 — 다음 묶음):

| 항목 | 브랜치 | 남은 일 |
|---|---|---|
| QM1 문서 단위 대기열 | jh/QM1-doc-queue @dc3e6a85 · jh/QM1b-doc-chain @3bc8000f | 묶어 넘기기(B) 검토 통과, 대기열(A)·서버 연결 미완·미검토 |
| OC3 OCR 실패여도 VLM으로 | (아직 없음) | 설계만 — docs/backlog/parse.md OC3 행. 그때까지 수집 서버는 OCR을 꺼 두고 운영 |
| OL1 확장자 위장 문서 판별 | jh/OL1-real-format-sniff @21e9fd31 | 구현 중 보류 |

