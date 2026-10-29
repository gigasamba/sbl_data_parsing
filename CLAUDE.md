# sbl_data_parsing — 개발 규칙(Claude·개발자 공통)

문서 파싱 → 구조화(청킹·임베딩) → 적재(pgvector) → 근거 검색(MCP) 파이프라인이다. 프로젝트 소개·폴더 그림·실행 방법은 [README.md](README.md), 문서 지도는 [docs/index.md](docs/index.md)다. **이 파일은 코드를 고칠 때 지키는 규칙과 하네스(점검 도구·명령)만 다룬다.** 코드를 고치기 전에 이 파일을 읽는다.

개발은 외부망 PC(macOS·Windows)에서 하고, 결과는 **내부망(폐쇄망) RHEL 서버**에서 Docker/podman 이미지 2개(`data-pipeline`·`mcp-server`)로 돈다. 그래서 "내 PC에서 된다"가 기준이 아니다 — **서버 리눅스 컨테이너에서 같은 결과가 나와야 한다.**

---

## 1. 폴더 성격과 코드 배치

새 코드는 아래 표의 **성격에 맞는 폴더**에 둔다. 애매하면 "누가 쓰나(파이프라인만·검색만·둘 다)"와 "서버 이미지에 들어가야 하나"로 고른다.

| 폴더 | 두는 것 | 두지 않는 것 | 서버 이미지 |
|---|---|---|---|
| `common/` | 두 앱이 **함께** 쓰는 것만 — `core/`(경로·지문·계약·글자 처리·실행 기록) · `ai/`(모델 호출·예산·외부 전송 가드) · `store/`(PG·struct·회사 DB·Object Storage, `db/` = SQLAlchemy·pydantic·Alembic) · `config/`(설정 모델·도구) · `check/`(점검) | 한 앱만 쓰는 코드 · 앱 import | 둘 다 |
| `pipeline/` | 파이프라인 앱 — `extract/`(원천·파싱 — `engines/`는 엔진) → `transform/`(represent·figures·structure) → `load/`(적재·게시) · `shared/`·`tools/`·`eval/` · 실행기 `cli.py` · 설정 `config.py` | `mcp_server` import · 검색 서빙 코드 | data-pipeline |
| `mcp_server/` | 검색 MCP 앱 — `main.py`(조립) · `routers/`(도구 등록 — 이름·서명 고정) · `schemas/`(출력 모양) · `services/`(업무 로직, `search/`) · `cli/`(MCP 도구 명령) · 설정 `config.py` | `pipeline` import · 파싱 코드 | mcp-server |
| `resources/` | 코드가 **읽는 데이터** — 지시서 `prompts/{common,pipeline,mcp}` · `config/` · `mappings/` · `vocab/` · `sql/`(DB 시드) | 코드(.py 로직) · 비밀 · 서버별 값 | 둘 다 |
| `deploy/docker/` | Dockerfile · requirements · entrypoint · `wheels/` | 앱 로직 | (빌드 원본) |
| `deploy/release/` | 빌드·전송·덧씌우기·반입 판정 스크립트 · `known_fail.txt` · `lint_changed.sh` | 앱 로직 | 일부(반입 판정 파일) |
| `deploy/host/` | **서버 호스트**에서 부르는 compose·systemd·셸·`run_docs.py` | 컨테이너 안에서 도는 코드 | 아니오 |
| `tests/` | 시험 — `server/`(이미지 안 반입 판정, 외부 접속 없이 도는 것) · `general/`(PC 전용 — PG·Docker·느린 것) · `fixtures/` · `runner.py` | 앱 코드 | `server/`만 |
| `validation/` | PC 전용 **검증 도구 코드** — `search_ui/`(검증 페이지) · `e2e/`(평가·비교·answer_gen) | 서버에서 도는 코드 · 데이터 묶음 | 아니오 |
| `valid_env/` | PC 전용 **데이터** — 시험 문서·정답(`unstructured/`) · 답변 점검 agent(`answer_test/`) · PC 시험 Docker(`docker/`) | 코드 로직 · 비밀 · 운영 데이터 | 아니오 |
| `docs/` | 사람이 읽는 문서(`operations/`·`architecture/`·`requirements/`·`refactoring/`) | 코드 | 아니오 |

**경계(자동 점검 — `python -m common.check.check_modules`):**
- `pipeline`과 `mcp_server`는 서로 import하지 않는다. 함께 쓸 것은 `common`으로 올린다.
- 앱(`common`·`pipeline`·`mcp_server`)은 `validation`·`tests`를 import하지 않는다. PC에서만 쓰는 기능은 `importlib` 문자열로.
- `pipeline` 안에서는 extract → transform → load 방향을 지킨다(거꾸로 import하지 않음 — 아직 자동 점검은 없음, 리뷰에서 본다).
- 설정 값은 환경변수를 직접 읽지 않는다(⑩ "os.environ 0", ⑪ "자식 env에 설정 이름 0" — §3).
- `mcp_server/routers`는 등록만, 로직은 `services`에 둔다. 출력 모양은 `schemas`.

**파일·이름:**
- 새 파일 이름은 20자 이하. `utils`·`helpers`·`common`·`misc` 같은 이름 금지. 저장소 안에서 같은 파일 이름을 두 번 쓰지 않는다(예외: 엔진 파일, `tests/fixtures/prompts/<앱>/<패키지>.json`, systemd unit, 앱마다 `config.py`).
- 파일 이름·import 이름의 대소문자를 정확히 같게 쓴다(Linux는 구분, macOS·Windows는 구분 안 함).
- 큰 파일을 쪼갤 때는 **옮기기 커밋과 쪼개기 커밋을 나눈다**(먼저 그대로 옮겨 이력·지문 대응을 지킨다).

---

## 2. 여러 OS에서 짜고 RHEL에서 돈다 — 경로·글자·셸

- **절대 경로를 코드에 쓰지 않는다.** 저장소 안 파일은 `common/core/paths.py`의 기준 상수(`PROJ_ROOT`·`RES_ROOT`·`STACK_FILE`·`TEMPLATES_DIR` 등)에서 상대로 만든다. 새 기준 자리가 필요하면 `paths.py`에 하나 더한다(파일마다 `Path(__file__).parents[n]`을 새로 계산하지 않음).
- **환경마다 달라질 수 있는 경로(서버 폴더·컨테이너 마운트·외부 프로그램 위치·결과 폴더)는 설정 칸으로 뺀다** — `settings.yaml` 칸 + 코드 기본값(§3). 이 프로젝트에서 "환경변수화"는 settings.yaml 칸을 뜻한다(코드는 env로 설정을 읽지 않음).
  - 예외: 이미지 배치 약속 경로(`/data/docs`·`/app/output/prepared`·`/data/gold` 등)는 `common/config/settings.py`의 이미지 기본값 표 **한 곳에만** 둔다(D-029). 새로 필요하면 그 표에 더한다.
- 경로는 `pathlib.Path`로 잇는다(`Path(a) / "b"`). `"/"`·`"\\"`로 글자를 이어 붙이지 않는다. 경로 비교는 `resolve()` 뒤에.
- 파일은 **UTF-8로 읽고 쓰며 `encoding="utf-8"`을 늘 명시**한다(Windows cp949 기본값에 기대지 않음). CLI 진입점의 화면 출력은 `common.core.console.utf8_stdout()` 한 줄로 UTF-8로 켠다(`sys.stdout.reconfigure`를 파일마다 쓰지 않음). 줄끝은 LF — `.gitattributes`가 고정한다. 새 확장자를 들이면 `.gitattributes`에 더한다.
- `.sh`는 **bash 3.2(macOS)와 4/5(RHEL) 모두에서** 도는 문법만 쓴다 — `set -u`와 빈 배열을 조심하고, 변수 바로 뒤에 한글을 붙이지 않는다(`${N}개`처럼 중괄호 — bash 3.2는 한글을 변수 이름으로 읽음). Windows에서 만든 `.sh`에는 실행 비트를 준다(`git update-index --chmod=+x`).
- OS별 분기(잠금 `fcntl`/`msvcrt` 등)는 한 곳에만 둔다.
- 외부 프로그램(soffice·tesseract·글꼴)은 PATH와 설정 칸으로만 찾는다.
- 컨테이너: RHEL은 SELinux라 bind 마운트에 `:z`, 서버 기본은 podman — docker 전제 명령은 서버에서 확인한다. 컨테이너 사용자는 UID 10001.

---

## 3. 설정 — `settings.yaml` 하나

- **설정 값과 비밀값(DB 접속·비밀번호·API 키·토큰)은 모두 settings.yaml에만** 둔다. PC는 저장소 루트 `settings.yaml`(git 제외·권한 600), 서버는 `$SERVER_ENV_DIR/settings.yaml`(UID 10001·640). 구조·설명은 `settings.sample.yaml`(생성물).
- 코드는 설정 객체로 읽는다 — 공용 `common.config.settings.cfg()`, 파이프라인 `pipeline.config.cfg()`, 검색 `mcp_server.config.cfg()`. **`os.environ`·`os.getenv`로 설정을 읽지 않는다**(남은 env 줄은 라이브러리·하위 프로세스·내부 신호만, 분류 주석 필수 — check_modules ⑩).
- **새 설정 칸을 더할 때:** 맞는 절의 모델(`common/config/settings.py`·`pipeline/config.py`·`mcp_server/config.py`)에 칸·설명·기본값·옛 env 이름(alias) → `python -m common.config.sample`(sample 다시 생성) → `python -m common.config.keyscan --check` → 운영에 영향이 있으면 [docs/operations/env-guide.md](docs/operations/env-guide.md)·`refactor.md`.
- 기본값은 코드에, 환경마다 다른 값은 settings.yaml에. 비운 칸 = 코드 기본값.
- 자식 프로세스에 값을 넘길 때는 env dict가 아니라 `settings.child_env(base, X=…)`(그 자식만) 또는 `settings.put(X=…)`(이 프로세스와 뒤 자식). 한 번 실행에만 다른 값은 명령 인자 `--set 이름=값`(진입 모듈에서 `setarg.apply()`), PC에서는 덮기 파일 `python -m common.config.overrides`도 된다.
- `RUN_ENV`(`common.run_env`)는 `local`·`dev`·`stage`·`prd`. 서버(dev·stage·prd)는 외부 모델을 거부하고, 설정 파일을 못 읽으면 시작을 거부한다. PC 전용 분기는 `paths.LOCAL_RUN` 하나로 가른다.
- 비밀값은 문서·로그·커밋·채팅·오류 메시지에 쓰지 않는다. 화면에 키를 찍지 않는다.

---

## 4. 바꾸면 서버 결과가 틀어지는 것 — 계약·지문

| 무엇 | 왜 | 지킬 것 |
|---|---|---|
| **엔진 파일** `pipeline/extract/engines/` 바이트 | 결과 재사용 열쇠(엔진 지문) — 바뀌면 서버 모든 문서를 그 엔진으로 다시 파싱 | 포매터·린트 자동 수정 대상에서 뺌(pyproject 제외 목록). 고치려면 사람 검토 |
| **인계 파일** `common/core/{contract,repfmt,terms,text}.py` | 인계 지문 `FINGERPRINT` — 다르면 structure·load가 옛 결과를 거부 | 위와 같음 |
| **층 코드 지문(code_fp)** — 층 파일과 그 파일이 import하는 `common` 모듈(`settings.py`·`paths.py` 등 모든 층의 의존 포함) | 층 캐시 열쇠 — 공용 의존 한 줄만 바꿔도 서버 문서 전체가 다시 처리됨 | 공용 의존 파일을 고칠 때는 사람에게 먼저 알리고, 커밋에 전후 값을 적음 |
| **지시문** `resources/prompts/**`(+ `validation/e2e/triple_extract`·`valid_env/answer_test/rag_qa`) | 지시서 지문·LLM 캐시 열쇠 | 바이트 그대로, LF |
| **MCP 도구 계약** — `search`·`query_edw`·`parse_document`·`edw_meta`의 이름·입출력 | 바깥 클라이언트와의 계약 | 바꾸지 않음(바꾸려면 협의·새 판) |
| **DB 스키마** — pgvector 검색 스키마·`struct`, 회사 DB `AI.ParsingMeta` | 다른 서비스·담당자와 함께 쓰는 계약 | 표·칸은 **Alembic 마이그레이션**으로만(`common/store/db/migrations` — 실행 중 DDL 금지), DB 담당 협의 |

지문 확인(공용·층 파일을 고친 커밋 전후):
```bash
PYTHONPATH=. .venv/bin/python -c "import common as c; from common.core import artifacts as a; print(c.FINGERPRINT, {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)})"
```
지금 값(10-29 S12 린트·타입 정리 + `/simplify` 뒤): `FINGERPRINT ffa201eed4aed21a` · a `e3b0c44298fc` · p0 `bd17a3ce0b81` · p1 `99ba3cabee79` · r `acba3674ad06` · s `4fa6a1943a0d`. 리팩토링 중 값의 변천과 되돌리는 법은 [refactor.md](refactor.md) 부록 1~3.

**운영 접속 가드(필수):**
- `deploy/host/scripts/run_docs.py`는 **PC에서 실행하지 않는다**(운영 EDW·Object Storage 접속). PC 확인은 문법·`--help`·`configure()`까지.
- 운영 정형 DB(`valid_env/structured/sales.sqlite`)는 승인 없이 열지 않는다(`common/store/structdb.py` `PROD_DBS`가 막음).
- PC에서 운영 DB·운영 EDW에 접속하지 않는다.

---

## 5. 작업 흐름 — 커밋 전·push 전

### 5-1. 브랜치(외부망 git flow — D-009)
`main`(내부망에 넣을 최종 — `release/*`에서만 머지·버전 태그) · `develop`(통합 — PR로만) · `feature/<기능명>`(develop에서 따서 develop로) · `release/<버전>`(빌드·반입 오류 수정만). `main`·`develop`에 직접 push하지 않는다. 내부망 쪽 관리 방식(P-08)은 아직 미정 — `refactor.md` "최종" ⑤.

### 5-2. 커밋 전 점검(필수)
```bash
bash deploy/release/lint_changed.sh          # 바꾼 .py만: ruff check · ruff format --check · mypy + 모듈 경계 — "[점검] 통과"여야 커밋
FIX=1 bash deploy/release/lint_changed.sh    # ruff 자동 수정·포맷(지문 보호 파일은 늘 제외)
git config core.hooksPath .githooks          # 한 번 — 커밋할 때 위 점검이 자동으로 돎(.githooks/pre-commit)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && PYTHONPATH=. .venv/bin/mypy   # 저장소 전체(push 전·판 만들기 전) — 셋 다 0
```
- **ruff·mypy는 저장소 전체가 경고 0이다**(S12, 10-29 — 지문 보호 파일 제외, mypy 범위는 pyproject `files`). 바꾼 파일 점검(`lint_changed.sh`·커밋 hook)도 0이어야 커밋한다 — 새 경고를 들이지 않는다. 고치지 않을 경고는 줄 단위 `# noqa: <코드> — <이유>`·`# type: ignore[<코드>]  # <이유>`로 한다. 규칙을 저장소 전체에서 끄는 것은 `pyproject.toml` `ignore`에 이유 주석과 함께, 고쳐도 동작이 같고 표시만 늘어나는 규칙에만(지금 E501·E731·B905) — 끌 때는 사람에게 알린다. 쓸모없어진 `noqa`는 RUF100이 잡는다(자동 수정은 이유 설명까지 지워서 꺼 둠 — 코드만 빼고 이유는 주석으로). 포맷과 기능 변경은 다른 커밋으로 한다. 포맷·린트 일괄 정리는 code_fp를 바꾸므로(서버 재처리) 사람 승인을 받아 판 단위로 한다.
- 설정 모델을 고쳤으면 `python -m common.config.sample --check`·`python -m common.config.keyscan --check`.
- 동작을 바꿨으면 시험: `python -m pipeline.cli selftest`(서버 반입 시험)·`pytest -q tests/`(전체) — 기준선보다 나빠지지 않아야 한다(§6-3).
- 공용·층 파일을 고쳤으면 지문 확인(§4)과 커밋 메시지에 전후 값.
- 문서는 기능을 바꾼 **같은 커밋에서** 고친다.
- 커밋 메시지에 서버 반입 영향을 적는다: **'덧씌우기 가능'**(코드 폴더만 바꾸면 됨) 또는 **'새 이미지 판 필요'**(`deploy/docker/` 의존성·Dockerfile·마운트 경로·`PYTHONPATH`가 바뀜).
- 새 외부 패키지는 **사용자 승인 뒤에만** 들인다. 서버 이미지용은 `deploy/docker/requirements*`(+ 폐쇄망 휠 `wheels/`), PC 개발 도구는 `requirements-dev.txt`.

### 5-3. push 전(적극 권장)
- **Claude `/simplify`** — 겹친 코드·필요 없는 우회·재사용 기회를 걷어낸다.
- **Claude `/code-review`** — 동작·버그 검토. 계약·지문·설정·DB를 건드린 변경은 `/code-review high`. PR에는 `/code-review --comment`로 줄 단위 의견.
- **검토 등급 A(사람 검토 필수):** 지문(엔진·인계·code_fp)·MCP 도구 계약·DB 스키마·운영 접속·비밀 처리를 건드린 변경은 작성자와 다른 사람이 보고 승인한다 — Claude 검토로 갈음하지 않는다.
- PR 본문: 무엇을 왜 · 바뀐 동작 · 안 바꾼 것 · '덧씌우기 가능/새 이미지 판 필요' · 지문 전후(바뀌었으면).

---

## 6. 로컬 하네스(PC)

### 6-1. 환경
```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt
export PYTHONPATH=$PWD            # 명령은 저장소 루트에서(자식 프로세스가 다른 폴더에서 돌 때도 되게 절대 경로)
.venv/bin/python -m pipeline.config   # 어느 settings.yaml을 읽는지·요약(비밀 가림)
```
- 루트 `settings.yaml`: `common.run_env: local` · 전용 PG 접속 값 · `no_paid_calls: true` · 임베딩 모델·키 · `store.run_mode: prod` · (부하 높은 PC면) `runtime.cpu_max_load` — 예는 README §3-1.
- 전용 pgvector 컨테이너(PG 16 + pgvector, 예 `127.0.0.1:55433`). ⚠️ PG 접속 칸을 비우면 코드가 `docker ps`로 아무 pgvector에나 붙는다 — 늘 적어 둔다. 다른 작업의 DB·포트를 쓰지 않는다.
- 백그라운드 프로세스는 PID를 파일에 남기고 **PID로만** 끈다(`pkill -f` 패턴 금지).
- 새 PG면 처음 한 번 `python -m common.store.db.dbtool up --target struct`(표는 migrate가 만든다).

### 6-2. 점검 명령
```bash
.venv/bin/python -m common.check.check_modules              # 모듈 경계 — "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check           # 설정 키 대조 — "빠진 키 0개"
.venv/bin/python -m common.config.sample --check            # sample이 설정 모델과 같은지
.venv/bin/python -m pipeline.cli selftest                   # 서버 반입 시험(tests/server) — --only <이름 조각>
.venv/bin/python -m pytest -q tests/                         # 반입 시험 + 일반 시험(tests/general만도 됨)
.venv/bin/python -m common.store.db.dbtool check --target all   # 표 정의 ↔ 실제 DB(차이·판이 끝이 아니면 종료 1)
```

### 6-3. 시험 기준선(10-29)과 알려진 실패
- `selftest` **88/89** — 알려진 FAIL `tests.server.pipeline.test_publish_guard` 1개(`deploy/release/known_fail.txt`, refactor.md C-54).
- `pytest tests/` **142 passed · 8 xfailed**(S12에 run_docs 흐름 시험 1개 더함) — 위 1개 + 일반 시험 7개(`tests/conftest.py` `GENERAL_KNOWN_FAIL` — C-54 ①·C-58). 모두 리팩토링 전부터 있던 것이다.
- 알려진 FAIL이 통과하면 "XPASS — 목록에서 지울 수 있음" 경고가 나온다 → 목록에서 지운다. **새 실패를 알려진 목록에 더하는 것은 고장을 숨기는 일이다** — 원인·결정을 refactor.md에 적고 사람 승인 뒤에만.
- Mac 부하가 높으면 `test_trigger_server`가 시간 초과로 실패할 수 있다(환경 문제).

### 6-4. 시험 작성
- 서버 이미지 안에서 외부 접속 없이 돌고 반입 판정에 쓸 시험은 `tests/server/<common|pipeline|mcp>/`, PC 전용(PG·Docker·외부 모델·느린 것)은 `tests/general/<…>/`. 파일 이름 `test_<모듈>.py`(20자 규칙 — 길면 줄임).
- 시험은 pytest 꼴(`test_*` 함수 + `assert`) — 이미지에서는 `pipeline.cli selftest`(`tests/runner.py`)가, PC에서는 pytest가 돌린다. 이미지에는 pytest가 없다.
- 시험은 **멱등**하게 — 공용 개발 PG에 흔적을 남기지 말고 임시 SQLite·임시 스키마(`orca_*`·`test_*`)를 쓰고 이름을 다시 확인한 뒤 정리한다. 설정은 `with pc.PIPE.env(X=…)`·`settings.isolated()` 같은 시험 도우미로 덮는다(os.environ을 건드리지 않음).
- 앱 모듈 안에 `selftest()`·`if __name__ == "__main__":` 점검을 새로 두지 않는다 — 시험은 `tests/`에.
- 고정 데이터: 지시서 시험 `tests/fixtures/prompts/<앱>/<패키지>.json`, 시험 문서 `valid_env/unstructured/`.

### 6-5. 스모크 — 파싱 → 임베딩 → migrate → 적재 → 검색
README §3-3·§3-4 순서대로(문서 2~3건). 실행마다 다른 값은 `--set`(파이프라인 진입점) 또는 덮기 파일(`mcp_server.main`·`ask`처럼 `--set`이 없는 명령). 시험 문서는 `valid_env/unstructured/`(목록 `list-smoke10.txt`), 임베딩 캐시는 `output/edw/embed_cache.sqlite`(같은 청크는 다시 호출 안 함 — 실제 호출을 보려면 `EMBED_CACHE=<빈 sqlite>`).

### 6-6. 검증 페이지·이미지 빌드
- 검증 페이지: `validation/search_ui/start_mcp.sh`·`start_ui.sh`(설정은 루트 `settings.yaml` 하나 — `mcp` 절·`common.paths.mcp_bundle`, 외부 임베딩 스위치 `no_paid_calls`) → http://127.0.0.1:8791. 상세 README §3-5.
- 이미지: `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<태그> bash deploy/release/build_ship.sh` → `bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest`(판정은 종료 코드가 아니라 `[판정]` 줄). 태그는 작업마다 새로, push·서버 반입은 사람이.

---

## 7. 외부 모델(OpenRouter 등 유료) — 비용 규칙

- 기본은 유료 호출 막음(`no_paid_calls: true`). 개발 중에는 **기능 확인만**(문서 2~3건, 질문 몇 개).
- 실행마다 상한을 건다 — `LLM_BUDGET_USD`·`LLM_MAX_CALLS`·`LLM_SPEND_FILE`(장부). 외부 전송에는 두 잠금이 함께 필요하다: `EMBED_ALLOW_EXTERNAL`과 `LLM_SYNTHETIC_TRUTH`(합성 시험 문서라는 선언 파일). 두 잠금은 루트 settings.yaml에 둬도 되지만(사용자 10-29 — 설정 창구 하나), 그때는 `no_paid_calls: true`를 기본으로 두고 외부 호출이 필요한 동안만 `false`로 바꾼 뒤 되돌린다(평소 시험이 외부를 부르지 않게). 한 번 실행에만 풀 때는 `--set`.
- `role=llm`을 `adk.complete`로 직접 부르면 예산 장부를 거치지 않는다 — 실호출은 `llm.chat`·`run_agent(per_turn_admit=True)`로.
- 기술 스택 비교처럼 호출이 많은 일은 예상 비용(호출 수 × 평균 토큰 × 단가)을 먼저 보고하고 승인받는다. 서버는 내부망 모델만 쓴다(외부 거부).

---

## 8. 문서

- 문서 지도 [docs/index.md](docs/index.md) — 문서를 더하거나 옮기면 같은 커밋에서 고친다. 새 문서는 꼭 필요할 때만(기존 문서의 절로 먼저).
- 서버·사람이 확인할 일(저장소 안에서 끝낼 수 없는 것)은 [refactor.md](refactor.md)에 `C-xx`로 더하고, 반입 순서는 그 파일 "최종 — 사람이 할 일"에 둔다.
- 결정은 [docs/refactoring/refactor_plan.md](docs/refactoring/refactor_plan.md) 7절 `D-xxx`, 미정은 8절. 운영 절차는 `docs/operations/`(서버 가이드·릴리스·설정 가이드).

## 9. Claude로 작업할 때

- **판단이 필요한 일은 사용자에게 묻는다** — 규칙·결정에 없는 것, 동작이 바뀌는 것, 지우는 것, 계약·스키마·지문. 물을 때는 배경·선택지·영향·추천을 쉬운 한국어로.
- 하위 에이전트에 맡길 때는 이 파일 §2~§5·§7을 계약에 그대로 넣는다(경계·경로·설정·지문·점검·비용).
- 되돌리기 어려운 일(push·서버 반입·DB 변경·파일 삭제)은 하기 전에 확인받는다. 지울 때는 먼저 대상을 본다.
- 결과는 있는 그대로 보고한다 — 시험이 실패하면 출력과 함께, 건너뛴 단계는 건너뛰었다고.

## 10. 알려진 문제(리팩토링 전부터)

10-20 축소 스키마(`file_sha256`·`client`·`file_name`·`s3_key` 제거)가 일부에만 반영됐다.
- 검색기 생성(`mcp_server/services/search/retriever.py`)이 `file_sha256`을 읽어 새 묶음에서 실패한다 — PC는 로컬 배치 분기(`paths.LOCAL_RUN`)로 피하고 서버는 PG 경로만 쓴다. PC 시험 Docker 스모크도 여기서 멈춘다.
- 집계 경로가 없는 칸 `file_sha256`을 조회해 검색 결과에 "집계 경로 오류" 메모가 붙는다(검색 근거는 정상).
- `pgvector_load deploy`의 `backfill_chunk_clients`가 `doc.client`를 읽어 실패한다(표·색인 생성에는 영향 없음).
- `pipeline structure/load` 모듈의 계약 점검(`contract.py` DOC_KEYS)이 새 묶음을 거부한다(서버는 이 모듈을 쓰지 않음).
- `pipeline structure`에 `PIPE_EMBED=none`이면 차원 0이라 `vector(0)` 표를 못 만든다.
- 문서 대장 upsert가 PG에서 문법 오류(C-54 ①) · 게시 방어선이 꺼져 있음(C-54 ②) — 다음 판에 설계.
- `validation/search_ui/index.html` 첫 화면 "10개 문서(20개 청크)"는 고정 문구다.

---

### 옛 절 번호(10-29 전 판 CLAUDE.md) — 코드 주석·기록 문서의 옛 참조를 찾을 때
옛 1절(저장소·이름 대응) → README·refactor_plan 9절 · 옛 2절(문서) → §8 · 옛 3절(지켜야 할 규칙) → §2(배포 환경)·§3(설정)·§4(지문·계약·운영 가드) · 옛 4절(작업 절차) → §5·§9 · 옛 5절(OpenRouter) → §7 · 옛 6절(로컬 하네스) → §6 · 옛 7절(알려진 문제) → §10 · 옛 8절(사용자 결정 대기) → refactor.md "최종" ⑤·refactor_plan 8절. 코드 주석 속 옛 번호는 일부러 고치지 않았다(공용·층 파일은 code_fp가 바뀌고, 그 밖 파일은 주석 한 줄 때문에 옛 린트 경고를 정리해야 해서 — §5-2).
