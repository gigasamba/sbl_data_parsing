# sbl_data_parsing — 개발 규칙(Claude·개발자 공통)

문서 파싱 → 구조화(청킹·임베딩) → 적재(pgvector) → 근거 검색(MCP)으로 이어지는 파이프라인이다. 프로젝트 소개, 폴더 구조, 실행 방법은 [README.md](README.md)에, 문서 지도·용어집(약어, 옛 용어, 옛 절 번호)은 [docs/INDEX.md](docs/INDEX.md)에 있다. **이 파일은 코드를 고칠 때 지킬 규칙과 하네스(점검 도구·명령)만 다룬다.** 코드를 고치기 전에 이 파일을 읽는다.

개발은 외부망 PC(macOS, Windows)에서 하고, 결과물은 **내부망(폐쇄망) RHEL 서버**에서 Docker/podman 이미지 2개(`data-pipeline`, `mcp-server`)로 실행된다. 그래서 "내 PC에서 된다"는 기준이 될 수 없다. **서버의 리눅스 컨테이너에서 같은 결과가 나와야 한다.**

---

## 1. 폴더 성격과 코드 배치

새 코드는 아래 표에서 **성격이 맞는 폴더**에 둔다. 애매하면 "누가 쓰는가(파이프라인만, 검색만, 둘 다)"와 "서버 이미지에 들어가야 하는가"로 고른다.

| 폴더 | 두는 것 | 두지 않는 것 | 서버 이미지 |
|---|---|---|---|
| `common/` | 두 앱이 **함께** 쓰는 것만 — `core/`(경로, 핑거프린트, 계약, 문자열 처리, 실행 기록), `ai/`(모델 호출, 예산, 외부 전송 가드), `store/`(PG, 회사 DB, Object Storage — `db/`는 SQLAlchemy·pydantic·Alembic), `config/`(설정 모델과 도구), `check/`(점검) | 한 앱만 쓰는 코드, 앱 import | 둘 다 |
| `pipeline/` | 파이프라인 앱 — `extract/`(원본 고르기·받기·준비) → `transform/`(`parse/` 엔진 파싱 — `engines/`는 엔진, represent, figures, structure) → `load/`(적재·퍼블리시), `shared/`, `tools/`, `eval/`, 실행기 `cli.py`, 설정 `config.py` | `mcp_server` import, 검색 서빙 코드 | data-pipeline |
| `mcp_server/` | 검색 MCP 앱 — `main.py`(앱 조립), `routers/`(도구 등록 — 이름·시그니처 고정), `schemas/`(출력 구조), `services/`(업무 로직, `search/`), `cli/`(MCP 도구 명령), 설정 `config.py` | `pipeline` import, 파싱 코드 | mcp-server |
| `resources/` | 코드가 **읽는 데이터** — 프롬프트 `prompts/{common,pipeline,mcp}`, `config/`, `mappings/`, `vocab/` | 코드(.py 로직), 비밀값, 서버마다 다른 값 | 둘 다 |
| `deploy/docker/` | Dockerfile, requirements, entrypoint, `wheels/` | 앱 로직 | (빌드 원본) |
| `deploy/release/` | 빌드·전송·굽기·배포 판정 스크립트, `known_fail.txt`, `lint_changed.sh` | 앱 로직 | 일부(배포 판정 파일) |
| `deploy/host/` | **서버 호스트**에서 실행하는 compose, systemd, 셸 스크립트, `run_pipeline.py` | 컨테이너 안에서 실행되는 코드 | 아니요 |
| `tests/` | 테스트 — `server/`(이미지 안에서 배포 판정에 쓰는 테스트, 외부 접속 없이 실행됨), `general/`(PC 전용 — PG·Docker가 필요하거나 느린 테스트), `runner.py` | 앱 코드 | `server/`만 |
| `validation/` | PC 전용 **검증 도구 코드** — `search_ui/`(검증 페이지), `e2e/`(평가·비교·answer_gen) | 서버에서 실행되는 코드, 데이터 번들 | 아니요 |
| `valid_env/` | PC 전용 **데이터** — 외부 시스템 대역: 테스트 문서(`object_storage/` — 버킷 모양, `CRMS`·`SFDC`·`LAS`·`FAQ`), 합성 EDW·회사 DB 표(`edw/`), 답변 점검 agent(`answer_test/`), PC 테스트 Docker(`docker/`) | 코드 로직, 비밀값, 운영 데이터 | 아니요 |
| `docs/` | 사람이 읽는 문서 — `PRD.md`·`prd/`(요건), `operations/`, `architecture/`, `refactoring/`(`refactor.md` — 서버·사람 확인 사항), `history/`(지난 기록) | 코드 | 아니요 |

**모듈 경계(자동 점검 — `python -m common.check.check_modules`):**
- `pipeline`과 `mcp_server`는 서로 import하지 않는다. 함께 쓸 코드는 `common`으로 올린다.
- 앱(`common`, `pipeline`, `mcp_server`)은 `validation`과 `tests`를 import하지 않는다. PC에서만 쓰는 기능은 `importlib`에 모듈 이름 문자열을 넘겨 불러온다.
- `pipeline` 안에서는 extract → transform → load 방향을 지킨다. 거꾸로 import하지 않는다(아직 자동 점검은 없고 코드 리뷰에서 확인한다).
- 설정 값을 환경변수에서 직접 읽지 않는다(⑩ "os.environ 0", ⑪ "자식 프로세스 env에 설정 이름 0" — §3).
- `mcp_server/routers`에는 도구 등록만 두고 로직은 `services`에, 출력 구조는 `schemas`에 둔다.

**파일·이름 규칙:**
- 새 파일 이름은 20자 이하로 짓는다. `utils`, `helpers`, `common`, `misc` 같은 이름은 쓰지 않는다. 저장소 안에서 같은 파일 이름을 두 번 쓰지 않는다(예외: 엔진 파일, systemd unit, 앱마다 하나씩 두는 `config.py`).
- 파일 이름과 import 이름의 대소문자를 정확히 같게 쓴다(Linux는 대소문자를 구분하고, macOS와 Windows는 구분하지 않는다).
- 큰 파일을 나눌 때는 **옮기는 커밋과 나누는 커밋을 따로 만든다**(먼저 그대로 옮겨서 변경 이력과 핑거프린트의 대응 관계를 유지한다).

---

## 2. 여러 OS에서 개발하고 RHEL에서 실행한다 — 경로·문자·셸

- **코드에 절대 경로를 쓰지 않는다.** 저장소 안 파일의 경로는 `common/core/paths.py`의 기준 상수(`PROJ_ROOT`, `RES_ROOT`, `STACK_FILE`, `TEMPLATES_DIR` 등)를 기준으로 한 상대 경로로 만든다. 새 기준 위치가 필요하면 `paths.py`에 상수를 하나 추가한다(파일마다 `Path(__file__).parents[n]`을 새로 계산하지 않는다).
- **환경마다 달라질 수 있는 경로(서버 폴더, 컨테이너 마운트 위치, 외부 프로그램 위치, 결과 폴더)는 설정 항목으로 분리한다** — `settings.yaml` 항목과 코드 기본값(§3). 이 프로젝트에서 "환경변수화"는 settings.yaml 항목으로 빼는 것을 뜻한다(코드는 env에서 설정을 읽지 않는다).
  - 예외: 이미지 배치에서 약속된 경로(`/data/docs`, `/app/output/prepared`, `/data/gold` 등)는 `common/config/settings.py`의 이미지 기본값 표 **한 곳에만** 둔다. 새로 필요하면 그 표에 추가한다.
- 경로는 `pathlib.Path`로 잇는다(`Path(a) / "b"`). `"/"`나 `"\\"`로 문자열을 이어 붙이지 않는다. 경로를 비교할 때는 `resolve()`를 먼저 한다.
- 파일은 **UTF-8로 읽고 쓰며 `encoding="utf-8"`을 항상 명시**한다(Windows의 cp949 기본값에 기대지 않는다). CLI 진입점의 화면 출력은 `common.core.console.utf8_stdout()` 한 줄로 UTF-8로 설정한다(`sys.stdout.reconfigure`를 파일마다 쓰지 않는다). 줄바꿈 문자는 LF이며 `.gitattributes`가 고정한다. 새 확장자를 쓰게 되면 `.gitattributes`에 추가한다.
- `.sh`는 **bash 3.2(macOS)와 bash 4/5(RHEL) 모두에서 동작하는** 문법만 쓴다. `set -u`와 빈 배열의 조합을 조심하고, 변수 바로 뒤에 한글을 붙이지 않는다(`${N}개`처럼 중괄호로 감싼다 — bash 3.2는 뒤에 붙은 한글까지 변수 이름으로 읽는다). Windows에서 만든 `.sh`에는 실행 권한을 준다(`git update-index --chmod=+x`).
- OS별 분기(파일 잠금의 `fcntl`/`msvcrt` 등)는 한 곳에만 둔다.
- 외부 프로그램(soffice, tesseract, 글꼴)은 PATH와 설정 항목으로만 찾는다.
- 컨테이너: RHEL은 SELinux를 쓰므로 bind 마운트에 `:z`를 붙인다. 서버의 기본 컨테이너 도구는 podman이므로 docker를 전제로 한 명령은 서버에서 확인한다. 컨테이너 사용자는 UID 10001이다.

---

## 3. 설정 — `settings.yaml` 하나

- 설정은 settings.yaml 하나에 둔다. `settings.sample.yaml`에는 모든 키가 기본값과 함께 카테고리별로 들어 있다 — 복사해서 필수값·비밀값을 채운다(PRD op-05).
- **비밀값(DB 접속 정보, 비밀번호, API 키, 토큰)은 settings.yaml에만** 둔다. PC는 저장소 루트의 `settings.yaml`(git 제외, 권한 600), 서버는 `$SERVER_ENV_DIR/settings.yaml`(UID 10001, 권한 640)이다. 구조와 설명은 `settings.sample.yaml`(자동 생성 파일)에 있다.
- 코드는 설정 객체로 값을 읽는다 — 공용은 `common.config.settings.cfg()`, 파이프라인은 `pipeline.config.cfg()`, 검색은 `mcp_server.config.cfg()`. **`os.environ`이나 `os.getenv`로 설정을 읽지 않는다**(남은 env 줄은 라이브러리용, 하위 프로세스용, 내부 신호용뿐이며 분류 주석이 필수다 — check_modules ⑩).
- **새 설정 항목을 추가할 때:** 해당 섹션의 모델(`common/config/settings.py`, `pipeline/config.py`, `mcp_server/config.py`)에 항목·설명·기본값·옛 env 이름(alias)을 넣는다 → `python -m common.config.sample`로 sample을 다시 만든다 → `python -m common.config.keyscan --check`를 실행한다 → 운영에 영향이 있으면 [docs/operations/env-guide.md](docs/operations/env-guide.md)와 `refactor.md`에 적는다.
- 기본값은 코드에, 환경마다 다른 값은 settings.yaml에 둔다. 비워 둔 항목은 코드 기본값을 쓴다.
- 자식 프로세스에 값을 넘길 때는 env dict가 아니라 `settings.child_env(base, X=…)`(그 자식에게만) 또는 `settings.put(X=…)`(현재 프로세스와 이후 자식 모두)를 쓴다. 한 번만 다른 값으로 실행할 때는 명령 인자 `--set 이름=값`을 쓴다(진입 모듈에서 `setarg.apply()`). PC에서는 덮어쓰기 설정 파일 `python -m common.config.overrides`도 쓸 수 있다.
- `RUN_ENV`(`required.env.run_env`)는 `local`, `dev`, `prd` 중 하나다(그 밖의 값이면 시작 거부). 서버(dev, prd)는 외부 모델 호출을 거부하고, `dev.fake_llm`(가짜 LLM 응답)가 켜져 있으면 시작하지 않으며, 설정 파일을 읽지 못하면 시작하지 않는다. 외부 모델·가짜 LLM은 `local`에서만 쓴다. PC 전용 분기는 `paths.LOCAL_RUN` 하나로만 가른다.
- 비밀값은 문서, 로그, 커밋, 채팅, 오류 메시지에 쓰지 않는다. 화면에 키를 출력하지 않는다.

---

## 4. 바꾸면 서버 결과가 달라지는 것 — 계약과 핑거프린트

| 대상 | 이유 | 지킬 것 |
|---|---|---|
| **엔진 파일** `pipeline/transform/parse/engines/`의 바이트 | 결과 재사용 키(엔진 핑거프린트) — 바뀌면 서버의 모든 문서를 그 엔진으로 다시 파싱한다 | 포매터·린트 자동 수정 대상에서 뺀다(pyproject 제외 목록). 고치려면 사람 검토를 받는다 |
| **핸드오프 파일** `common/core/{contract,repfmt,terms,text}.py` | 핸드오프 핑거프린트 `FINGERPRINT` — 값이 다르면 structure·load가 이전 결과를 거부한다 | 위와 같다 |
| **레이어 코드 핑거프린트(code_fp)** — 레이어 파일과 그 파일이 import하는 `common` 모듈(`settings.py`, `paths.py` 등 모든 레이어의 공용 의존 포함) | 레이어 캐시 키 — 공용 의존 파일을 한 줄만 바꿔도 서버 문서 전체가 다시 처리된다 | 공용 의존 파일을 고칠 때는 사람에게 먼저 알리고, 커밋 메시지에 변경 전후 값을 적는다 |
| **프롬프트** `resources/prompts/**`(+ `valid_env/answer_test/rag_qa`) | 프롬프트 핑거프린트와 LLM 캐시 키 | 바이트 그대로 두고 줄바꿈은 LF |
| **MCP 도구 계약** — `search`, `query_edw`, `edw_meta`, `parse_document`, `list_doc_fulltext`, `get_doc_fulltext`의 이름과 입출력 | 외부 클라이언트와의 계약 | 바꾸지 않는다(바꾸려면 협의 후 새 버전으로) |
| **DB 스키마** — pgvector 검색 스키마와 회사 DB `AI.ParsingMeta` | 다른 서비스·담당자와 함께 쓰는 계약 | 테이블·컬럼은 **Alembic 마이그레이션으로만** 바꾸고(`common/store/db/migrations` — 실행 중 DDL 금지), DB 담당자와 협의한다 |

핑거프린트 확인(공용·레이어 파일을 고친 커밋의 전후에 실행):
```bash
PYTHONPATH=. .venv/bin/python -c "import common as c; from common.core import artifacts as a; print(c.FINGERPRINT, {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)})"
```
지금 기준값은 PRD [e2-02](docs/prd/test.md#e2-02)에 있다.

**운영 접속 가드(필수):**
- `deploy/host/scripts/run_pipeline.py`는 **PC에서 실행하지 않는다**(운영 EDW와 Object Storage에 접속한다). PC에서는 문법 확인, `--help`, `configure()`까지만 확인한다.
- PC에서 운영 DB나 운영 EDW에 접속하지 않는다.

---

## 5. 작업 흐름 — 커밋 전과 push 전

### 5-1. 브랜치(외부망 git flow)
`main`(내부망에 배포할 최종 코드 — `release/*`에서만 머지하고 버전 태그를 붙인다), `develop`(통합 브랜치 — PR로만 머지), `feature/<기능명>`(develop에서 분기해 develop으로 머지), `release/<버전>`(빌드·배포 오류 수정만). `main`과 `develop`에는 직접 push하지 않는다. 내부망 쪽 코드 관리 방식(P-08)은 내부망 gitea로 정했다 — [docs/operations/gitea-guide.md](docs/operations/gitea-guide.md).

### 5-2. 커밋 전 점검(필수)
```bash
bash deploy/release/lint_changed.sh          # 바꾼 .py만: ruff check · ruff format --check · mypy + 모듈 경계 — "[점검] 통과"가 나와야 커밋
FIX=1 bash deploy/release/lint_changed.sh    # ruff 자동 수정·포맷(핑거프린트 보호 파일은 항상 제외)
git config core.hooksPath .githooks          # 처음 한 번 — 커밋할 때 위 점검(.githooks/pre-commit), push할 때 저장소 전체 ruff·mypy·모듈 경계 + selftest 판정(.githooks/pre-push — 걸리면 push 멈춤, GitHub Actions는 쓰지 않음)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && PYTHONPATH=. .venv/bin/mypy   # 저장소 전체(push 전, 버전을 만들기 전) — 셋 다 0
```
- **ruff와 mypy는 저장소 전체에서 경고 0이다**(핑거프린트 보호 파일 제외, mypy 범위는 pyproject의 `files`). 바꾼 파일만 보는 점검(`lint_changed.sh`, 커밋 hook)도 0이어야 커밋할 수 있다 — 새 경고를 만들지 않는다.
- 고치지 않을 경고는 줄 단위로 `# noqa: <코드> — <이유>` 또는 `# type: ignore[<코드>]  # <이유>`를 붙인다. 규칙을 저장소 전체에서 끄는 것은 `pyproject.toml`의 `ignore`에 이유 주석과 함께 적되, 고쳐도 동작은 같고 경고 표시만 늘어나는 규칙에만 쓴다(현재 E501, E731, B905). 끌 때는 사람에게 알린다.
- 쓸모없어진 `noqa`는 RUF100이 잡는다. RUF100의 자동 수정은 이유 설명까지 지우므로 꺼 두었다 — 코드만 지우고 이유는 일반 주석으로 남긴다.
- 포맷 변경과 기능 변경은 다른 커밋으로 나눈다. 포맷·린트 일괄 정리는 code_fp를 바꾸므로(서버 재처리) 사람 승인을 받아 버전 단위로 한다.
- 설정 모델을 고쳤으면 `python -m common.config.sample --check`와 `python -m common.config.keyscan --check`를 실행한다.
- 동작을 바꿨으면 테스트를 실행한다: `python -m pipeline.cli selftest`(서버 배포 테스트), `pytest -q tests/`(전체). 기준선보다 나빠지지 않아야 한다(§6-3).
- 공용·레이어 파일을 고쳤으면 핑거프린트를 확인하고(§4) 커밋 메시지에 변경 전후 값을 적는다.
- 문서는 기능을 바꾼 **같은 커밋에서** 고친다.
- 커밋 메시지에 서버 배포 영향을 적는다: **'코드 폴더만 교체'** 또는 **'새 이미지 버전 필요'**(`deploy/docker/`의 의존성, Dockerfile, 마운트 경로, `PYTHONPATH`가 바뀜).
- **버전은 저장소 루트 `VERSION` 하나**(SemVer — 두 이미지 `data-pipeline`, `mcp-server`가 함께 씀). 이미지 태그(`<이미지>:<버전>`)와 DB의 버전 표기(`common.pipeline_version()`)가 이 값을 쓴다. feature 브랜치에서는 고치지 않고 `release/<버전>` 브랜치에서 올린다: MAJOR(MCP 도구 계약·DB 스키마·핸드오프 형식이 깨질 때), MINOR(새 이미지 버전), PATCH(코드 폴더만 바꿈). 1.0.0 전에는 MCP 도구 계약·DB 스키마가 깨져도 MINOR로 올린다(SemVer 0.x 관례, 운영이 안정되면 1.0.0).
- 새 외부 패키지는 **사용자 승인을 받은 뒤에만** 도입한다. 서버 이미지용은 `deploy/docker/requirements*`(+ 폐쇄망 휠 `wheels/`), PC 개발 도구는 `requirements-dev.txt`에 넣는다.

### 5-3. push 전(적극 권장)
- **Claude `/simplify`** — 중복 코드와 불필요한 우회를 걷어내고, 기존 코드를 재사용할 수 있는 곳을 찾는다.
- **Claude `/code-review`** — 동작과 버그를 검토한다. 계약, 핑거프린트, 설정, DB를 건드린 변경은 `/code-review high`로 본다. PR에는 `/code-review --comment`로 줄 단위 의견을 단다.
- **검토 등급 A(사람 검토 필수):** 핑거프린트(엔진, 핸드오프, code_fp), MCP 도구 계약, DB 스키마, 운영 접속, 비밀값 처리를 건드린 변경은 작성자가 아닌 다른 사람이 보고 승인한다. Claude의 검토로 대신하지 않는다.
- PR 본문에는 무엇을 왜 바꿨는지, 바뀐 동작, 바꾸지 않은 것, '코드 폴더만 교체/새 이미지 버전 필요', 핑거프린트 전후 값(바뀌었다면)을 적는다.

---

## 6. 로컬 하네스(PC)

### 6-1. 환경
```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r deploy/docker/requirements-core.txt -r deploy/docker/requirements-image.txt -r requirements-dev.txt
export PYTHONPATH=$PWD            # 명령은 저장소 루트에서 실행(자식 프로세스가 다른 폴더에서 실행될 때도 찾도록 절대 경로)
.venv/bin/python -m pipeline.config   # 어느 settings.yaml을 읽는지와 요약(비밀값은 가림)
```
- 루트 `settings.yaml`에는 `required.env.run_env: local`, 전용 PG 접속 정보(`required.pg`), 임베딩·LLM·VLM 주소·모델·키(`required.models`), (부하가 높은 PC라면) `tuning.ops.runtime.max_cpu_load`를 둔다. 예시는 README §4-2에 있다.
- 작업 폴더(worktree)에는 `settings.yaml`이 없다 — 거기서 점검·시험은 `export RUN_ENV=local`을 먼저(없으면 `output/`이 저장소 한 단계 위에 생긴다 — `paths.PROJ_ROOT`). 하위 에이전트 지시에도 넣는다.
- 전용 pgvector 컨테이너(PG 16 + pgvector, 예: `127.0.0.1:55433`)를 쓴다. PG 접속 항목(`required.pg`)은 모두 채우거나 모두 비운다 — 일부만 채우면 시작을 거부한다(자동 탐색 없음). 다른 작업의 DB와 포트를 쓰지 않는다.
- 백그라운드 프로세스는 PID를 파일에 남기고 **PID로만** 종료한다(`pkill -f` 패턴 금지).
- 검색 스키마 테이블은 마이그레이션이 만든다(`dbtool up --target all --schema <이름> --bundle <묶음>` — README §4-4).

### 6-2. 점검 명령
```bash
.venv/bin/python -m common.check.check_modules              # 모듈 경계 — "모듈 경계 통과"
.venv/bin/python -m common.config.keyscan --check           # 설정 키 대조 — "빠진 키 0개"
.venv/bin/python -m common.config.sample --check            # sample이 설정 모델과 같은지
.venv/bin/python -m pipeline.cli selftest                   # 서버 배포 테스트(tests/server) — 일부만: --only <이름 일부>
.venv/bin/python -m pytest -q tests/                         # 서버 배포 테스트 + 일반 테스트(tests/general만도 가능)
.venv/bin/python -m common.store.db.dbtool check --target all   # 테이블 정의 ↔ 실제 DB(차이가 있거나 최신 버전이 아니면 종료 코드 1)
```

### 6-3. 테스트 기준선과 알려진 실패
- 지금 기준선(selftest·pytest 개수, 알려진 실패 목록)은 PRD [e2-02](docs/prd/test.md#e2-02)에 있다. 바꾼 뒤 결과가 기준선보다 나빠지면 안 된다.
- 알려진 실패 목록: 배포 판정은 `deploy/release/known_fail.txt`, PC 일반 테스트는 `tests/conftest.py`의 `GENERAL_KNOWN_FAIL`. 실 PG가 있어야 판정되는 PC 사례만 `_PC_SETTINGS_CASES`에 넣는다.
- 알려진 실패가 통과하면 "XPASS — 목록에서 지울 수 있음" 경고가 나온다. 그때는 목록에서 지운다. **새 실패를 알려진 실패 목록에 추가하는 것은 고장을 숨기는 일이다** — 원인과 결정을 refactor.md에 적고 사람의 승인을 받은 뒤에만 추가한다.

### 6-4. 테스트 작성
- 서버 이미지 안에서 외부 접속 없이 실행되고 배포 판정에 쓰는 테스트는 `tests/server/<common|pipeline|mcp>/`에, PC 전용(PG·Docker·외부 모델이 필요하거나 느린 것) 테스트는 `tests/general/<…>/`에 둔다. 파일 이름은 `test_<모듈>.py`다(20자 규칙 — 길면 줄인다).
- 테스트는 pytest 형식(`test_*` 함수 + `assert`)으로 쓴다. 이미지에서는 `pipeline.cli selftest`(`tests/runner.py`)가, PC에서는 pytest가 실행한다. 이미지에는 pytest가 없다.
- 테스트는 **멱등**하게 만든다. 공용 개발 PG에 흔적을 남기지 말고 임시 SQLite나 임시 스키마(`orca_*`, `test_*`)를 쓰며, 이름을 다시 확인한 뒤 정리한다. 설정은 `with pc.PIPE.env(X=…)`, `settings.isolated()` 같은 테스트 도우미로 덮어쓴다(os.environ을 건드리지 않는다). 함수를 바꿔 끼울 때는 `unittest.mock.patch.object`를 쓴다.
- 앱 모듈 안에 `selftest()`나 `if __name__ == "__main__":` 점검 코드를 새로 두지 않는다. 테스트는 `tests/`에 둔다.
- 고정 데이터: 외부 시스템을 흉내 내는 데이터(문서·정답·EDW 대역)는 `valid_env/`에 둔다([e2-09](docs/prd/test.md#e2-09)). 서버 배포 테스트는 `valid_env`가 없는 이미지에서도 돌게 데이터를 임시 폴더에 만들어 쓴다.

### 6-5. 스모크 테스트 — 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색
README §4-4(①~⑥)·§4-5의 순서대로 문서 2~3건으로 확인한다. 실행마다 다른 값은 `--set`(파이프라인 진입점)이나 덮어쓰기 설정 파일(`python -m common.config.overrides` — `mcp_server.main`, `ask`처럼 `--set`을 받지 않는 명령)로 준다. 테스트 문서는 `valid_env/object_storage/{SFDC,CRMS}/`에 있고(문서 목록은 README §4-4), 임베딩 캐시는 `output/edw/embed_cache.sqlite`다(같은 청크는 다시 호출하지 않는다 — 실제 호출을 확인하려면 `EMBED_CACHE=<빈 sqlite>`).

### 6-6. 검증 페이지와 이미지 빌드
- 검증 페이지: `validation/search_ui/start_mcp.sh`와 `start_ui.sh`로 띄운다(설정은 루트 `settings.yaml` 하나 — `search.server`, `dev.search_ui`, PG 접속 `required.pg`, 외부 임베딩 `dev.models.embed.embed_allow_external` — README §4-2 예시). 주소는 http://127.0.0.1:8791 이다. 자세한 내용은 README §4-6.
- 서버에 올릴 이미지를 빌드하기 전에 `assets/`를 채운다(`PYTHONPATH=. python deploy/release/assets.py pack` — [release-and-patch §5-6](docs/operations/release-and-patch.md#5-6-반입-자산assets-준비--이미지-빌드-전)).
- 이미지: `ALLOW_NO_ASSETS=1 BUILD_ONLY=1 IMAGE_TARGET=pipeline TAG=data-pipeline:<시험 태그> bash deploy/release/build_ship.sh` → `bash deploy/release/selftest_gate.sh docker run --rm data-pipeline:<태그> selftest`(판정은 종료 코드가 아니라 `[판정]` 줄로 한다). PC 시험 빌드는 태그를 작업마다 새로 붙인다(TAG를 빼면 `data-pipeline:<VERSION>` — 배포용 버전 태그이고, 이미 있으면 `build_ship.sh`가 멈춘다). push와 서버 배포는 사람이 한다.
- **배포 단계마다 이미지와 코드의 구성이 다르다**(README §5-0). ① PC(local) → 개발 서버(dev): 코드가 없는 실행 이미지(`IMAGE_TARGET=pipeline-runtime|mcp-runtime`) + PC 커밋의 코드 묶음을 개발 서버 코드 폴더(`CODE_DIR`/`live`)로 마운트한다. ② 개발 서버 → 운영 서버(prd): 개발 서버에서 `deploy/release/bake_prod_image.sh`로 같은 실행 이미지 + 시험한 코드 폴더를 묶어 코드가 든 이미지를 만든다(코드 폴더 없이 실행). Dockerfile의 코드 포함 타깃(`pipeline`·`mcp`)은 PC 시험과 비상용이다.

---

## 7. 외부 모델(OpenRouter 등 유료) — 비용 규칙

- 외부 호출은 역할마다 `dev.models.<embed|llm|vlm>.<embed|llm|vlm>_allow_external`(기본 false)이 켜지고 `RUN_ENV=local`일 때만 된다. 개발 중에는 **기능 확인만** 한다(문서 2~3건, 질문 몇 개).
- 하루 지출 상한 `dev.models.guard.daily_budget_usd`(기본 0.1달러 — 장부 `spend_ledger_file`, 여러 프로세스가 합계 하나를 나눠 씀). 단가(`PRICES`)를 모르는 외부 LLM은 거부한다.
- 외부 허용은 루트 settings.yaml에 둔다. 한 번만 풀 때는 `--set`을 쓴다. 내부망 서버(dev·prd)의 settings.yaml은 셋 다 false.
- 모델 호출은 `llm.chat`·`llm.complete`만 쓴다(예산 장부·가드를 거침). PC 답변 점검의 여러 턴 도구 반복은 `validation/e2e/tool_loop.py`가 맡는다(턴마다 예산 확인 — `llm.admit_turn()`).
- 기술 스택 비교처럼 호출이 많은 작업은 예상 비용(호출 수 × 평균 토큰 × 단가)을 먼저 보고하고 승인을 받는다. 서버는 내부망 모델만 쓴다(외부 모델은 거부).

---

## 8. 문서

- 기능 요건·미개발 항목은 [docs/PRD.md](docs/PRD.md)와 `docs/prd/<카테고리>.md`에 있다(§10).
- 문서 지도는 [docs/INDEX.md](docs/INDEX.md)다. 문서를 추가하거나 옮기면 같은 커밋에서 이 지도를 고친다. 새 문서는 꼭 필요할 때만 만들고, 먼저 기존 문서의 섹션으로 넣을 수 있는지 본다.
- 서버나 사람이 확인해야 하는 일(저장소 안에서 끝낼 수 없는 것)은 [refactor.md](docs/refactoring/refactor.md)에 `C-xx`로 추가하고, 배포 순서는 [release-and-patch.md](docs/operations/release-and-patch.md) §8(0.2.0 배포 — 사람이 할 일)에 둔다.
- 결정 사항(`D-xxx`)·미정 사항은 PRD 행과 refactor.md에 둔다(옛 결정 장부는 [docs/history/refactor_plan.md](docs/history/refactor_plan.md) 7·8절). 지난 기록은 `docs/history/`에 둔다. 운영 절차는 `docs/operations/`(서버 가이드, 릴리스, 설정 가이드)에 있다.

## 9. Claude로 작업할 때

- **판단이 필요한 일은 사용자에게 묻는다** — 규칙이나 결정에 없는 것, 동작이 바뀌는 것, 무언가를 지우는 것, 계약·스키마·핑거프린트에 관한 것. 물을 때는 배경, 선택지, 영향, 추천안을 쉬운 한국어로 설명한다.
- 하위 에이전트에게 일을 맡길 때는 이 파일의 §2~§5와 §7을 지시 사항에 그대로 넣는다(경계, 경로, 설정, 핑거프린트, 점검, 비용).
- 되돌리기 어려운 일(push, 서버 배포, DB 변경, 파일 삭제)은 하기 전에 확인을 받는다. 지울 때는 대상을 먼저 확인한다.
- 결과는 있는 그대로 보고한다. 테스트가 실패하면 출력과 함께 알리고, 건너뛴 단계는 건너뛰었다고 밝힌다.

## 10. 기능 요건 — `docs/PRD.md`

- 기능 요건(무엇·왜·관련 파일)과 미개발·고장 항목(진행 상황)은 이 파일이 아니라 [docs/PRD.md](docs/PRD.md)와 `docs/prd/<카테고리>.md`에 둔다. 작업 전에 PRD 표에서 맡은 행을 찾는다.
- 항목마다 `<a id>` + `## ID · 한글 이름`과 `- Status:` 줄. ID는 바꾸지 않는다.
- 기능을 더하거나 고치면 같은 커밋에서 해당 앵커를 고친다. 끝난 항목도 PRD 표에 남기고 상태를 done으로, 앵커에 `- Status: done`을 남긴다.
- (카테고리 설명·옛 §10 알려진 문제가 옮겨 간 ID: [docs/INDEX.md](docs/INDEX.md) 문서 지도·Glossary)

---

옛 절 번호·용어 대응은 [docs/INDEX.md](docs/INDEX.md#glossary) Glossary로 옮겼다.
