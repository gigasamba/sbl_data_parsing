# 개발 서버 인수인계 — 처음부터 차례로 따라 하기

대상: 개발 서버(`dev`)를 처음 맡은 사람. 자기 벌(개발자 한 사람 몫의 컨테이너 묶음) 하나를 만들어 시험 원천 `DEV-1`의 문서를 파싱·게시·적재하고, 검색까지 확인한다. 이 문서는 순서만 잡아 준다 — 칸 하나하나의 뜻은 [README §5](../../README.md#5-서버내부망에-배포하고-실행하기)·[env-guide.md](env-guide.md), 일상 운영은 [server-guide.md](server-guide.md), 새 판 올리기는 [upgrade-guide.md](upgrade-guide.md)를 본다.

**표기**
- `/home/sbl` = 공용 폴더(예). 서버마다 다를 수 있다 — 앞 담당자에게 확인한다.
- `<루트>` = 벌 폴더 = 코드 폴더 = 코드 zip을 푼 폴더(예 `/home/sbl/sbl_data_parsing-main-1`).
- `<…>` 꺾쇠 안은 직접 넣을 값이다. 실제 주소·계정·비밀번호는 문서·채팅·커밋에 적지 않는다.
- 명령은 모두 **root 셸**에서 친다. 각 단계 맨 앞의 `cd`를 꼭 먼저 한다 — 스크립트는 자기 자리(코드 폴더)에서 설정을 찾지만, 결과 파일 경로(`output/…`, `deploy/host/scripts/test_space/…`)는 지금 폴더 기준으로 적었다.

---

## 0. 먼저 알 것 — 폴더와 벌

```
/home/sbl/                                   ← 공용 폴더
├── sbl_images-main/                         ← 이미지 폴더(서버에 한 번 불러오면 모든 벌이 같이 씀)
├── opencode.json                            ← (선택) 개발 작업 공간 공용 opencode 설정
├── sbl_data_parsing-main-1/                 ← 벌 1 = 코드 폴더 = <루트>
│   ├── settings.yaml  edw_chain.yaml        ← 이 벌의 설정(init이 없을 때만 만듦 — 비밀값이 들어감, 권한 640)
│   ├── output/                              ← 이 벌의 결과 폴더(컨테이너 안 /app/output)
│   ├── home/                                ← (작업 공간을 켰을 때만) SSH 작업 공간 홈
│   └── deploy/host/scripts/test_space/      ← run_pipeline 진행 기록(batch_progress/)
└── sbl_data_parsing-main-2/                 ← 벌 2(§13)
```

**폴더 이름 끝 `-<숫자>`(1~99)가 벌 번호다.** 설정 칸은 따로 없다. 끝이 `-<숫자>`가 아니면(`sbl_data_parsing-main`, `sbl_data_parsing-20261106` 같은 날짜) 한 벌로 본다.

| 벌 번호가 저절로 정하는 것(벌 1의 예) | 기본 이름 → 벌 1 |
|---|---|
| 컨테이너 이름 | `data-pipeline` → `data-pipeline-1` · `mcp-data-parsing` → `mcp-data-parsing-1` · `mcp-server` → `mcp-server-1` |
| compose 묶음 이름 | `compose` → `compose-1` |
| systemd 타이머·서비스 이름 | `data-pipeline-nightly.timer` → `data-pipeline-nightly-1.timer` · `mcp-server-keepalive.timer` → `mcp-server-keepalive-1.timer` |

| 벌 번호가 정하지 **않는** 것 | 어떻게 정하나 |
|---|---|
| 포트 | 벌마다 settings.yaml에 직접 다르게 적는다 — `search.server.mcp_port`(검색 MCP, 기본 8765) · `ops.services.data_parsing.data_parsing_port`(파싱 작업 서비스, 기본 8766) · (작업 공간을 켜면) `option.devbox.ssh_port`. **번호가 붙은 벌은 벌 1이라도 앞 두 포트가 기본값 그대로면 모든 스크립트가 시작을 거부한다.** |
| 어떤 문서를 파싱하나 | settings.yaml `required.source.source_systems`(예 `[DEV-1]`) |
| 검색 DB 스키마 | 모든 벌이 같은 기준 스키마(`required.pg.pg_schema`, 비우면 `data_parsing`)를 함께 쓴다. 원천 `DEV-1` 문서는 그 아래 원천 스키마 `<기준>_dev_1`(기본이면 `data_parsing_dev_1`)에 들어간다 |

- **벌 번호와 `DEV-<숫자>`는 서로 다른 것이다.** 벌 번호는 컨테이너 이름만, `DEV-<숫자>`는 문서와 스키마를 나눈다. 헷갈리지 않게 벌 1은 `DEV-1`, 벌 2는 `DEV-2`처럼 같은 숫자를 쓴다.
- 원천 `DEV-<숫자>` 문서는 EDW 파일 목록 표(`required.edw.edw_file_table`, 기본 `AI.FileStorageMap`)의 `source_system` 칸이 `dev-1`(대소문자 무관)인 행이고, Object Storage 경로는 `DEV-1/…`이다. 시험 행과 파일은 DB·스토리지 담당이 넣는다 — 먼저 `dev-1` 행이 있는지 담당에게 확인한다.
- `DEV-<숫자>`는 개발 서버(`dev`)에서만 쓴다. 운영(`prd`)에서는 번호 붙은 폴더도, `DEV-…` 원천도 시작 거부다.
- compose를 직접 부르지 않는다. 늘 `deploy/host/scripts/host_ctl.sh`를 쓴다 — 폴더 이름과 settings.yaml로 이름·포트·마운트를 채운다.

---

## 1. 서버 준비 확인(처음 한 번)

```bash
export DOCKER=docker                      # 셸을 열 때마다(또는 root ~/.bashrc에)
docker compose version                    # 판 번호가 나오면 됨
python3 -c 'import yaml' && echo ok       # ok — 호스트 스크립트가 settings.yaml을 읽는 데 필요
docker images | grep -E 'data-pipeline-runtime|mcp-server-runtime'   # 불러온 실행 이미지 태그 — 3단계에서 씀
```
- 하나라도 없으면 [README §5-0 "미리 있어야 하는 것"](../../README.md#5-0-배포-단계와-개발-서버-설치)대로 준비한다. 이미지가 없으면 같은 절 "서버 설치 순서" 2번(`load.sh`)부터.
- 다른 벌이 쓰는 포트를 피한다 — 쓸 포트가 비었는지 본다(줄이 안 나오면 빈 포트):
```bash
ss -ltn | grep -E ':(8771|8772)\b'
```

---

## 2. 벌 폴더 만들기와 `init`

```bash
cd /home/sbl
unzip -q <코드 zip>                                         # → sbl_data_parsing-<판>/ (다른 벌과 같은 판)
mv sbl_data_parsing-<판> sbl_data_parsing-main-1            # 이름 끝 -1 = 벌 1
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
```
gitea에서 clone해 쓰는 경우는 [gitea-guide §2](gitea-guide.md#2-개발자-한-벌-만들기).

| 칸 | 넣을 값 | 어디서 |
|---|---|---|
| `<코드 zip>` | 코드 저장소의 그 판 zip(예 태그 `v0.3.0` → 풀면 `sbl_data_parsing-0.3.0/`) | GitHub `gigasamba/sbl_data_parsing` 태그 — 다른 벌과 같은 판 |
| `<운영 그룹>` | 컨테이너(UID 10001)와 사람 계정이 함께 쓰는 리눅스 그룹 | `id -gn <운영 계정>` — 모르면 서버 관리자. 다른 벌과 같은 그룹 |

**성공이면** 이렇게 찍힌다(값은 찍지 않는다):
```
[host_ctl init] 루트: /home/sbl/sbl_data_parsing-main-1
  만듦  /home/sbl/sbl_data_parsing-main-1/output
  만듦  /home/sbl/sbl_data_parsing-main-1/output/_mcp_parse/jobs
  권한  /home/sbl/sbl_data_parsing-main-1 (a+rX — 설정·결과·홈 빼고)
  만듦  /home/sbl/sbl_data_parsing-main-1/settings.yaml(settings.sample.yaml에서)
  만듦  /home/sbl/sbl_data_parsing-main-1/edw_chain.yaml(resources/config/edw_chain.yaml에서)
[host_ctl init] settings.yaml에서 아직 비어 있는 필수 칸(값을 채울 것 — 이름만):
  - required.env.run_env
  - required.pg.pg_host
  …
```
- 여러 번 불러도 안전하다. 이미 있는 파일은 `있음 …(덮지 않음)`으로 두고 넘어간다.
- `[host_ctl init] root로 실행할 것(sudo)` → root 셸에서 다시(종료 3).
- `… 자리에 폴더가 있음 — 컨테이너를 init 전에 띄운 흔적` → 그 빈 폴더를 `rmdir`로 지우고 다시(종료 4).

---

## 3. 이 벌의 `settings.yaml` 채우기

```bash
cd /home/sbl/sbl_data_parsing-main-1
vi settings.yaml
```
`init`이 찍은 빈 칸을 모두 채운다. 접속·모델·이미지 칸은 다른 벌(또는 앞 담당자)의 settings.yaml과 같게 옮기고, **벌마다 다른 칸**만 바꾼다. 아래는 가짜 값으로 쓴 꼴이다 — 이미 있는 칸을 고치고, 같은 칸을 두 번 적지 않는다(두 번이면 시작 거부).

```yaml
required:
  env:
    run_env: dev                              # 개발 서버
  source:
    source_systems: [DEV-1]                   # 이 벌이 파싱할 원천 — 꼭 적는다(아래 주의)
  pg:
    pg_host: <PG 주소>                        # 다른 벌과 같게(DB 담당이 준 값)
    pg_port: <PG 포트>
    pg_database: <DB 이름>
    pg_user: <계정>
    pg_password: <비밀>
    pg_schema: data_parsing                   # 기준 스키마 — 모든 벌이 같게(바꾸지 않는다)
  # models · edw · publish · object_storage · tokens: 다른 벌과 같게
  deploy:
    pipeline_image: data-pipeline-runtime:<이미지 판>   # 1단계 docker images에서 본 태그
    mcp_image: mcp-server-runtime:<이미지 판>
    host_docs_dir: <있는 호스트 폴더(절대 경로)>         # 컨테이너 /data/docs로 붙음
    pg_container_name: <PG 컨테이너 이름>               # run_pipeline이 문서 수를 셀 때 씀
search:
  server:
    mcp_port: 8771                            # 검색 MCP — 벌마다 다르게(8765 그대로면 시작 거부)
ops:
  host:
    container_cli: docker
  services:
    data_parsing:
      data_parsing_port: 8772                 # 파싱 작업 서비스 — 벌마다 다르게(8766 그대로면 시작 거부)
# 아래는 필요할 때만(§12):
#  host: {compose_project: …, extra_compose: [compose.extra.yml]}
#  containers: {pipeline: {pipeline_container_name: …}, …}
option:
  devbox:
    ssh_port: null                            # SSH 작업 공간을 쓸 때만 포트(예 2201 — 벌마다 다르게)
    home_dir: null                            # 비우면 <루트>/home
```

- ⚠️ **`required.source.source_systems`가 비어 있으면 "운영 5개 원천(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`) 전부"라는 뜻이다** — 그 벌은 운영 문서를 모두 파싱해 모든 벌이 함께 쓰는 스키마에 적재한다. 일부러 그렇게 만든 동작이라 코드가 막지 않는다. 개발자 벌은 꼭 자기 `DEV-<숫자>`(예 `[DEV-1]`)를 적는다.
- CPU 수가 적은 서버면 자원 칸도 줄인다([README §5-0 "자원"](../../README.md#5-0-배포-단계와-개발-서버-설치)) — 모든 벌의 합이 서버 CPU를 넘지 않게.
- 권한은 그대로 둔다(init이 640, 주인 10001로 만듦). 다른 편집기로 새로 저장해 주인이 바뀌었으면 `chown 10001:<운영 그룹> settings.yaml && chmod 640 settings.yaml`.

**확인 — 설정이 읽히나:**
```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK     # 값은 찍지 않고 compose 문법·필수 칸만
```
- `설정 OK`면 통과.
- `[설정] 여러 벌 — search.server.mcp_port가 기본값(8765) 그대로: 벌마다 다른 포트를 적음` → 위 `mcp_port`(또는 같은 꼴의 `data_parsing_port` 안내)를 고친다.
- `[설정] 설정 파일 없음: …` → 2단계 `init`을 이 폴더에서 했는지 본다.
- `…:? … 필요` 안내 → 그 안내에 적힌 칸(예 `required.deploy.host_docs_dir`)을 채운다.
- `host_ctl.sh config`를 `--quiet` 없이 부르면 경로·이름이 모두 찍힌다 — 남과 화면을 나눌 때는 쓰지 않는다.

---

## 4. `data-pipeline` 띄우기와 연결 점검

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline
bash deploy/host/scripts/host_ctl.sh ps                      # data-pipeline-1 한 줄이 Up
bash deploy/host/scripts/pipe_exec.sh check_env
bash deploy/host/scripts/pipe_exec.sh ping_models
```
- `pipe_exec.sh`는 앞뒤로 `[pipe_exec] <시각> <도구> 시작(data-pipeline 안에서)` · `[pipe_exec] <시각> <도구> 끝 (종료 코드 0)`을 찍는다. **끝 줄의 종료 코드가 0**이어야 한다.
- `check_env`: 항목마다 `[OK ]`(정상) 또는 `[-- ]`(문제·미설정) 줄. `[-- ]` 줄을 읽고 해당 칸을 고친다(PG 연결 실패가 "건너뜀"처럼 보일 수 있으니 PG 줄을 꼭 읽는다).
- `ping_models`: 표의 `결과` 칸이 임베딩·LLM·VLM 모두 `OK`. `FAIL`이 있으면 종료 코드 1 — `required.models`의 주소·모델 이름을 고친다(서버는 내부망 모델만).
- `[오류] 상주 컨테이너 data-pipeline-1가 떠 있지 않음` → 이 단계 첫 줄 `up -d data-pipeline`부터 다시.

---

## 5. DB 판 — 검토용 SQL 뽑기 → `migrate up`

검색 DB는 모든 벌이 같이 쓴다. 표를 만들거나 바꾸는 일은 **DB 담당과 협의한 뒤** 한다. 먼저 지금 상태를 본다(읽기만):

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/pipe_exec.sh migrate check --target all
```
출력 줄 꼴: `[migrate] <갈래> <스키마>: 판 <상태> [<판 번호>] · 코드의 끝 판 <끝 판>`. 상태는 `끝`(최신) · `낮음`(올려야 함) · `없음`(아직 표 없음) · `모름`(코드보다 새 판 — 멈추고 담당에게 묻는다). 모두 `끝`이면 종료 코드 0, 아니면 1.

어느 경우인지 고른다:

| 상황 | 할 일 |
|---|---|
| 서버의 첫 벌 — 갈래가 모두 `없음` | (가) |
| 이미 다른 벌이 쓰는 DB — 기준 스키마들은 `끝`이고 `<기준>_dev_1` 줄이 없음 | (나) |
| `낮음`이 있음 | 코드 판이 DB보다 새 것 — [upgrade-guide §6](upgrade-guide.md#6-db-판-올리기--migrate-up)을 따른다(모든 벌을 같은 판으로 맞춘 뒤 한 번) |

**(가) 첫 벌 — 표 전부 만들기**
```bash
cd /home/sbl/sbl_data_parsing-main-1
# 1) DB 담당 검토용 SQL만 쓴다(DB에 붙지 않음) → <루트>/output/up.sql
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원> --sql /app/output/up.sql
# 2) 담당이 승인하면 실제로 올린다
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>
bash deploy/host/scripts/pipe_exec.sh migrate master load
```
- `<임베딩 차원>` = 임베딩 모델이 내는 벡터 길이(예 1024 — 모델 담당에게 확인). 처음 표를 만들 때 정해지고 나중에 못 바꾼다.
- `vector` 확장이 없다고 멈추면 DB 관리자가 한 번 만든다([README §5-3 ③](../../README.md#5-3-서버--처음-설치-자세히)).

**(나) 이미 있는 DB — 이 벌의 DEV 원천 스키마만 더하기**
```bash
cd /home/sbl/sbl_data_parsing-main-1
# 1) 검토용 SQL — --from은 위 check 출력의 search 기준 스키마 판(끝 판), --dim은 그 DB의 차원
bash deploy/host/scripts/pipe_exec.sh migrate up --target search --from <끝 판> --dim <임베딩 차원> --sql /app/output/dev_1.sql
# 2) 담당이 승인하면 실제로 올린다(차원은 있는 표에서 읽으므로 --dim 없이)
bash deploy/host/scripts/pipe_exec.sh migrate up --target search
```
- `--sql`은 settings.yaml `source_systems`의 DEV 원천 스키마를 빈 스키마부터 만드는 SQL을 쓴다. 파일 안 `-- 수동:` 줄은 DB 담당이 직접 확인할 것(이미 있는 스키마인지 등)이다.
- ⚠️ **`migrate up --target search`(= `dbtool up --target search`)는 어느 벌에서 부르든 DB에 이미 있는 모든 `<기준>_dev_*` 스키마(다른 벌 것 포함)를 함께 끝 판으로 올린다.** 이 벌의 `<기준>_dev_1`만 올리는 것이 아니다. 일부러 그렇게 만든 동작이라 코드가 막지 않는다 — 그래서 모든 벌이 같은 코드 판이어야 하고, 올리기 전에 다른 벌 담당에게 알린다.
- `migrate master load`는 하지 않는다(서버에 한 번이면 됨).

**성공이면**:
- `--sql`: `[migrate] SQL → /app/output/<파일> (DB에 붙지 않음 — 실행은 DB 담당이 직접)` — 호스트에서는 `<루트>/output/<파일>`. (가)처럼 `--from` 없이 뽑으면 `[migrate] 경고: … 빈 스키마부터 만드는 SQL …` 줄이 함께 나온다(첫 벌이면 정상).
- `up`: 스키마마다 `[migrate] search data_parsing_dev_1: 판 ['<끝 판>'] (끝 <끝 판>)` 꼴.
- 마지막으로 다시 확인:
```bash
bash deploy/host/scripts/pipe_exec.sh migrate check --target all    # 모든 줄이 "판 끝" — data_parsing_dev_1 줄도 보임
```

---

## 6. 나머지 컨테이너 띄우기와 전체 점검

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp     # 검색 MCP는 시작할 때 마스터 표를 읽으므로 5단계 뒤
bash deploy/host/scripts/host_ctl.sh ps                             # data-pipeline-1 · mcp-data-parsing-1 · mcp-server-1 세 줄 Up
curl -s http://127.0.0.1:8771/health                                # {"ok":true,"ready":true,…} — 막 띄운 직후는 잠깐 준비 중일 수 있음
bash deploy/host/scripts/host_ctl.sh check
```
`check`는 6단계를 차례로 돌리고 처음 실패에서 멈춘다. 단계마다 `[host_ctl check] ── <이름>` 줄 뒤에 그 명령의 출력이 나온다.

| 순서 | 단계 이름 | 하는 일 |
|---|---|---|
| ① | `check_env` | 4단계와 같음 |
| ② | `ping_models` | 4단계와 같음 |
| ③ | `migrate check` | 5단계 확인과 같음 |
| ④ | `selftest data-pipeline` | 서버 배포 시험(몇 분 걸림) — `[판정] 통과 — FAIL 0` 줄이 있어야 함 |
| ⑤ | `selftest mcp-server` | 같음 |
| ⑥ | `검색 MCP` | `/health` 응답 확인(꺼져 있으면 띄우고 다시 봄) |

- **성공이면 마지막 줄** `[host_ctl check] 통과 — 6개`.
- 실패면 마지막 줄 `[host_ctl check] 실패 — <단계>: <안내>` — 안내대로 고치고 `check`를 다시 부른다. ③에서 멈추면 5단계, ④⑤에서 멈추면 `FAIL` 줄의 시험 이름으로 원인을 찾는다([release-and-patch §3](release-and-patch.md#3-배포-판정--selftest)).

---

## 7. `DEV-1` 문서 한 번 처리하기

`run_pipeline.py`가 문서마다 받기 → 파싱 → 게시(Object Storage — silver) → 원본 삭제 → 구조화·적재(PG — gold)를 끝까지 돌린다. 게시와 적재는 따로 부르지 않는다. 처음에는 `--limit`로 두세 건만 돌린다.

```bash
cd /home/sbl/sbl_data_parsing-main-1
python3 deploy/host/scripts/run_pipeline.py --help                  # 인자 목록이 나오면 호스트 준비 OK
nohup python3 deploy/host/scripts/run_pipeline.py --limit 2 > run_first.out 2>&1 &
tail -f deploy/host/scripts/test_space/batch_progress/progress.log  # Ctrl+C로 보기만 멈춤(실행은 계속)
```
- 대상은 settings.yaml `source_systems`(`[DEV-1]`)의 행만이다. 문서 이름으로 더 좁히려면 `--filter <키워드,…>`.
- 진행 줄(문서마다 셋): `doc#<번호> 파싱 OK(…)` → `doc#<번호> publish OK(…)` → `doc#<번호> 구조화+적재 OK(…)`.
- **성공이면 끝 줄**: `=== 문서별 flow 끝: 2건(완료 2 · 건너뜀 0 · 파싱실패 0 · 게시실패 0 · gold실패 0 · 스레드 예외 0) · … · 종료 코드 0 ===`.
- `처리할 문서 없음 — 종료` → EDW 목록에 `dev-1` 행이 없거나 이미 다 처리했다(0단계 — 담당에게 행 확인).
- `[중단] <칸 경로> …` → 그 settings.yaml 칸이 비었다(종료 2). 채우고 다시.
- `다른 run_pipeline이 도는 중(…) — 종료 코드 75` → 이 벌에서 이미 하나가 돈다(새벽 배치 포함). 끝난 뒤 다시.
- 종료 코드 뜻: `0` 모두 끝 · `1` 실패 문서 있음 · `75` 마감 도달·겹침 · `2` 설정 문제. 실패 문서 다시 돌리기는 [server-guide §3](server-guide.md#3-실패한-문서-찾기와-다시-돌리기).
- 다음부터 이어서 돌릴 때는 `--skip-done`(이미 적재한 문서와 영구 제외 문서는 건너뜀).

---

## 8. 게시·적재 결과 확인

적재 기록은 원천 스키마의 `doc` 표에 남는다(`<기준>_dev_1.doc`):
```bash
docker exec <PG 컨테이너> psql -U <계정> -d <DB 이름> -c "SELECT file_path, parse_status, silver_key, parsed_at, loaded_at, gold_version FROM data_parsing_dev_1.doc ORDER BY loaded_at DESC NULLS LAST LIMIT 5"
```
- **성공이면** 처리한 문서 수만큼 행, `parse_status`가 `ok` 또는 `partial`, `silver_key`·`loaded_at`·`gold_version`이 채워져 있다. `silver_key`는 Object Storage 게시 위치(`DEV-1/…` 아래)다.
- 행이 없으면 `progress.log`에서 그 문서의 `FAIL` 줄과 `doc_<번호>.log`를 본다(§10).
- 적재되지 않은 문서(파싱 실패·DRM·내용 중복 등)는 `applog.except_doc_info`에 남는다 — SQL은 [server-guide §8](server-guide.md#8-로그-db-살펴보기--applog-sql읽기만).

---

## 9. 검색 확인

**(1) 컨테이너 안에서 바로 검색** — 토큰 없이 DB 검색만 본다:
```bash
cd /home/sbl/sbl_data_parsing-main-1
docker exec mcp-server-1 python -m mcp_server.cli.search_ask ask --source DEV-1 --k 3 --q "<처리한 문서에 있는 낱말>"
```
**성공이면** `질문: … (원천 DEV-1 · 근거 <N>건)` 줄 뒤에 `[1] <파일 경로>  p.<쪽> L.<줄>`처럼 근거가 나온다. `[ask] …`로 끝나면 그 오류 글자를 읽는다(원천 스키마가 없으면 5단계).

**(2) MCP로 바깥처럼 불러 보기** — 실제 클라이언트와 같은 길(HTTP + 토큰):
```bash
read -rs -p "MCP 토큰: " TOK; echo                 # settings.yaml required.tokens.mcp_token 값 — 화면·셸 기록에 남지 않게 입력
docker exec mcp-server-1 python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:8771/mcp --source DEV-1 --q "<낱말>" --token "$TOK"
unset TOK
```
- **성공이면** `도구: [...]`(도구 6개) → `search: 원천 DEV-1 · 근거 <N>건 · 상태 …` → 끝 줄 `MCP 바깥 호출 통과`.
- 토큰이 틀리면 연결 오류(401)로 실패한다. 토큰을 적은 서버는 루프백 주소로 불러도 토큰이 필요하다.
- `근거 0건` → 8단계에서 `doc` 행이 있는지, 질문 낱말이 문서에 있는지 본다.
- 다른 서버의 AI 클라이언트를 붙이는 법·도구 입출력은 [server-guide §4](server-guide.md#4-검색-mcp-사용)·[mcp-guide.md](mcp-guide.md).

---

## 10. 로그 보기

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh logs --tail 100 mcp              # 서비스 이름: data-pipeline · mcp-data-parsing · mcp
bash deploy/host/scripts/host_ctl.sh logs -f data-pipeline            # 계속 보기(Ctrl+C — 컨테이너는 그대로)
tail -n 50 deploy/host/scripts/test_space/batch_progress/progress.log # run_pipeline 진행 줄
ls deploy/host/scripts/test_space/batch_progress/                     # doc_<번호>.log — 문서별 파싱·게시·구조화 출력
cat run_first.out                                                     # 7단계 nohup 화면 출력
ls -la output/logs/                                                   # 비어 있어야 정상 — 파일이 있으면 DB 로그 쓰기 실패
journalctl -u mcp-server-keepalive-1.service -n 50                    # 타이머를 켠 뒤(§11)
```
- `host_ctl.sh logs`에는 컨테이너 이름(`mcp-server-1`)이 아니라 **서비스 이름**(`mcp`)을 준다.
- 실행 기록·MCP 호출 기록은 DB `applog` 스키마에 남는다 — [server-guide §8](server-guide.md#8-로그-db-살펴보기--applog-sql읽기만).

---

## 11. 자동 실행 켜기(선택)

```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh timers
systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'
```
- **성공이면** `  씀  /etc/systemd/system/<단위>-1.<service|timer>` 네 줄, 목록에 `-1`이 붙은 두 타이머의 다음 실행 시각.
- `mcp-server-keepalive-1.timer`는 2분마다 검색 MCP를 살펴 꺼졌으면 띄운다. `data-pipeline-nightly-1.timer`는 settings.yaml `ops.nightly` 세 칸을 채우기 전에는 아무것도 하지 않는다 — 필요 없으면 `systemctl disable --now data-pipeline-nightly-1.timer`.
- 코드 폴더를 새 판으로 덮어쓴 뒤에도 다시 부른다.

---

## 12. 컨테이너 이름·볼륨 바꾸기

이름은 "밑 이름 + 벌 번호"다. 밑 이름은 settings.yaml에서 바꾼다.

```yaml
ops:
  host:
    compose_project: rag                       # 묶음 → rag-1
    extra_compose: [compose.extra.yml]         # 더 붙일 compose 파일(= <루트>/compose.extra.yml)
  containers:
    pipeline: {pipeline_container_name: rag-pipeline}         # → rag-pipeline-1
    data_parsing: {data_parsing_container_name: rag-parsing}  # → rag-parsing-1
    mcp: {mcp_container_name: rag-mcp}                        # → rag-mcp-1
```
```bash
cd /home/sbl/sbl_data_parsing-main-1
bash deploy/host/scripts/host_ctl.sh down                           # ① 옛 이름을 먼저 내린다(settings.yaml을 고치기 전에)
vi settings.yaml                                                    # ② 위 칸을 적음
cp deploy/host/compose/extra.example.yml compose.extra.yml          # ③ 볼륨·env를 더할 때만 — 파일 안 규칙대로 고침
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK  # ④
bash deploy/host/scripts/host_ctl.sh up -d                          # ⑤ → rag-pipeline-1 · rag-parsing-1 · rag-mcp-1
bash deploy/host/scripts/host_ctl.sh ps
bash deploy/host/scripts/host_ctl.sh timers                         # ⑥ 타이머를 켰으면 다시(새 이름을 보게)
```
- ①을 빼먹으면 옛 이름의 컨테이너가 남아 포트를 잡고 있어 새 컨테이너가 뜨지 못한다. 그때는 이름을 되돌려 `down` 한 뒤 다시 한다.
- `extra_compose`의 서비스 이름은 `data-pipeline`·`mcp-data-parsing`·`mcp`(컨테이너 이름 아님). 호스트 경로는 절대 경로나 `${RAG_ROOT}`로 시작하고 끝에 `:z`(읽기 전용이면 `:ro,z`). 적은 파일이 없으면 `[host_ctl] ops.host.extra_compose 파일 없음: …`(종료 2).
- 이 칸들의 설명: [README §5-0 "컨테이너 이름·볼륨 바꾸기"](../../README.md#5-0-배포-단계와-개발-서버-설치).

---

## 13. 두 번째 벌 만들기

벌 1과 같은 판의 코드 zip으로, 2~11단계를 번호만 바꿔 되풀이한다. 이미지는 이미 불러왔으므로 1단계의 이미지 확인만 한다.

```bash
cd /home/sbl
unzip -q <코드 zip> && mv sbl_data_parsing-<판> sbl_data_parsing-main-2
cd /home/sbl/sbl_data_parsing-main-2
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
cp ../sbl_data_parsing-main-1/settings.yaml settings.yaml.new      # 벌 1 설정을 틀로(아래 칸을 고친 뒤 settings.yaml로 바꿈)
```
`settings.yaml.new`에서 벌마다 다른 칸만 고친다:

| 칸 | 벌 1 | 벌 2 |
|---|---|---|
| `required.source.source_systems` | `[DEV-1]` | `[DEV-2]` |
| `search.server.mcp_port` | `8771` | `8781` |
| `ops.services.data_parsing.data_parsing_port` | `8772` | `8782` |
| `option.devbox.ssh_port`(쓸 때만) | `2201` | `2202` |
| `option.devbox.gitea_*`·`git_user_*` | 벌 1 개발자 계정 | 비우거나 벌 2 개발자 값 — 남의 gitea 토큰을 그대로 두지 않는다 |
| `ops.run_pipeline.run_pipeline_work_dir` | 비움(또는 벌 1 전용 경로) | 비움 또는 벌 2 전용 경로 — 같으면 두 벌이 한 잠금·진행 기록을 나눠 써 함께 돌지 못한다 |
| `ops.host.host_output_dir` | 비움(또는 벌 1 전용 경로) | 비움 또는 벌 2 전용 경로 — 같으면 결과·캐시가 섞인다 |
| `ops.host.host_edw_chain_file` | 비움(또는 벌 1 경로) | 비움(벌 2 폴더의 `edw_chain.yaml`) 또는 벌 2 경로 |
| `option.devbox.home_dir`(쓸 때만) | 비움(또는 벌 1 전용 경로) | 비움 또는 벌 2 전용 경로 — 같으면 두 작업 공간이 한 홈을 쓴다 |

경로 칸은 비우면 그 벌 폴더 안(`<루트>/output` 등)이라 저절로 나뉜다. 벌 1에서 절대 경로를 적어 두었으면 복사한 틀에 그 경로가 그대로 남으니 꼭 고친다.

```bash
mv settings.yaml.new settings.yaml && chown 10001:<운영 그룹> settings.yaml && chmod 640 settings.yaml
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline                       # → data-pipeline-2
bash deploy/host/scripts/pipe_exec.sh migrate up --target search               # data_parsing_dev_2를 만듦(5단계 (나) — 검토용 SQL 먼저)
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp                # → mcp-data-parsing-2 · mcp-server-2
bash deploy/host/scripts/host_ctl.sh check                                     # [host_ctl check] 통과 — 6개
bash deploy/host/scripts/host_ctl.sh ps                                        # 이 벌의 컨테이너만 보임
```
- 벌 2 폴더에서 부른 스크립트는 벌 2의 settings.yaml과 `-2` 컨테이너만 다룬다. 벌 1을 다룰 때는 벌 1 폴더로 `cd` 한다.
- 모든 벌을 한 번에 띄우기: `for d in /home/sbl/sbl_data_parsing-main-*; do bash $d/deploy/host/scripts/host_ctl.sh up -d; done`.

---

## 14. 멈추기·정리하기

**잠깐 멈추기(다시 켤 수 있게)** — 타이머부터 끈다(안 그러면 2분 안에 검색 MCP를 다시 띄운다):
```bash
cd /home/sbl/sbl_data_parsing-main-1
systemctl stop mcp-server-keepalive-1.timer data-pipeline-nightly-1.timer   # 타이머를 켠 벌만
bash deploy/host/scripts/host_ctl.sh stop
bash deploy/host/scripts/host_ctl.sh ps                                     # 세 줄 모두 Exited
```
다시 켜기: `bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp` → `systemctl start mcp-server-keepalive-1.timer data-pipeline-nightly-1.timer`.

**벌 하나를 없애기** — 되돌릴 수 없으니 대상 번호를 두 번 확인하고, 지우기 전에 `settings.yaml`·`output/`을 백업할지 정한다:
```bash
cd /home/sbl/sbl_data_parsing-main-2
systemctl disable --now mcp-server-keepalive-2.timer data-pipeline-nightly-2.timer
bash deploy/host/scripts/host_ctl.sh down                                   # 컨테이너 지움(볼륨은 호스트 폴더라 남음)
ls /etc/systemd/system/*-2.service /etc/systemd/system/*-2.timer           # 지울 단위 파일 확인 — 이 벌 것만인지
rm /etc/systemd/system/mcp-server-keepalive-2.service /etc/systemd/system/mcp-server-keepalive-2.timer \
   /etc/systemd/system/data-pipeline-nightly-2.service /etc/systemd/system/data-pipeline-nightly-2.timer
systemctl daemon-reload
cd /home/sbl && rm -rf /home/sbl/sbl_data_parsing-main-2                   # 설정(비밀값)·결과 폴더도 함께 지워짐
```
- DB의 `data_parsing_dev_2` 스키마는 남는다. 지우려면 DB 담당에게 요청한다(공용 DB — 직접 지우지 않는다). 남아 있으면 다른 벌의 `migrate up --target search`가 계속 판을 올리고, 검색 MCP의 원천 목록에도 남는다.
- Object Storage의 `DEV-2/…` 게시 결과도 스토리지 담당에게 요청한다.

---

## 15. 막혔을 때 — 메시지로 찾기

| 메시지(일부) | 뜻 | 할 일 |
|---|---|---|
| `[설정] 여러 벌 — … 기본값(…) 그대로: 벌마다 다른 포트를 적음` | 번호 붙은 벌인데 포트가 기본값 | 3단계 포트 두 칸 |
| `[설정] 코드 폴더 이름 끝 -<n>(벌 번호)는 개발 서버(dev)에서만` | `run_env: prd`인데 번호 붙은 폴더 | 개발 서버면 `run_env: dev` |
| `[설정] 설정 파일 없음: …` | 이 폴더에 settings.yaml 없음 | 그 폴더에서 `host_ctl.sh init` |
| `[오류] 상주 컨테이너 …가 떠 있지 않음` | `pipe_exec.sh`가 붙을 컨테이너가 꺼짐 | `host_ctl.sh up -d data-pipeline` |
| `[host_ctl] … 없음(option.devbox.home_dir) — ssh_port를 적은 뒤 host_ctl.sh init …을 다시` | 작업 공간 홈이 없음 | `host_ctl.sh init --group <운영 그룹>` 한 번 더 |
| `… DEV 원천 스키마가 코드의 끝 판 …이 아님: 적재 전에 \`migrate up --target search\`` | `_dev_*` 스키마 판이 낮음 | 5단계 (나) |
| `…: 차원을 모름 — --dim N` | 새 스키마인데 차원을 안 줌 | `--dim <임베딩 차원>` |
| `[host_ctl check] 실패 — <단계>: …` | 그 단계 실패 | 6단계 표 |
| `다른 run_pipeline이 도는 중` | 이 벌에서 이미 실행 중 | 끝날 때까지 기다림 |
