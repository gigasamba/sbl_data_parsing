# 운영 중인 서버를 새 판으로 올리기

↑ [release-and-patch.md](release-and-patch.md) · [server-guide.md](server-guide.md) · [env-guide.md](env-guide.md) · 처음 설치는 [README §5-0](../../README.md#서버-설치-순서)

이미 돌고 있는 개발 서버(dev)·운영 서버(prd)를 새 판으로 바꾸는 순서다. 판 번호와 상관없이 같은 순서이고, 예는 0.2.0 → 0.3.0이다. 명령은 root 셸, `<…>`는 그 서버 값으로 바꾼다. 값·비밀은 화면·기록에 남기지 않는다. `# 기대:` 줄이 나오지 않으면 다음 단계로 가지 않는다.

```
0 먼저 알 것 → 1 지금 판 확인 → 2 백업 → 3 새 실행 이미지 → 4 새 코드 덮어쓰기 → 5 설정 고치기
→ 6 DB 판 올리기 → 7 pgvector가 바뀔 때 → 8 다시 처리 → 9 gitea·개발자별 벌 → 10 올린 뒤 점검 → 11 되돌리기
```

## 0. 먼저 알 것

- 판은 **벌 폴더(코드 폴더)에 새 코드를 덮어써** 올린다. 덮어쓰기 전에 벌 폴더를 벌 폴더 밖에 백업한다(§2 — 되돌리기용). 예: 벌 폴더 `/home/sbl/sbl_data_parsing-main-1`.
- 벌이 여럿이면 모두 같은 DB(기준 스키마)를 쓰므로 **모든 벌을 같은 판으로** 올린다. DB 판 올리기(§6)는 아무 벌 하나에서 한 번.
- 개발 서버에서 끝까지 한 번 한 뒤 운영 서버에서 같은 순서로 한다. 운영 서버는 개발 서버에서 구운 이미지를 쓴다([release-and-patch §1-2](release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)).
- 그 판에서 무엇이 바뀌었는지는 [refactor.md](../refactoring/refactor.md)의 열린 C 항목(서버·사람이 할 일)과 릴리스 노트로 본다.
- **0.1.0 서버에서 올릴 때만:** 검색 판 `0002_search`가 0.1.0이 만든 옛 검색 표를 **지운다**. 0.1.0 DB에 그냥 `migrate up`을 하지 않는다 — 새 `required.pg.pg_schema`를 정하고 백업한 뒤 올린다. 그때 쓴 절차(옛 컨테이너 이름·설정 옮기기)는 [0.2.0 배포 기록](../history/deploy_0_2_0.md).

**0.3.0에서 바뀐 것(예)**

| 무엇 | 서버에 미치는 것 | 이 문서의 절 |
|---|---|---|
| 네 이미지에 개발 도구·opencode가 들어가고 패키지 목록이 바뀜 | 새 실행 이미지 필요(코드 폴더만으로는 못 바꿈) | §3 |
| applog 판 `0003_applog` — 적재 안 된 문서 표 `except_doc_info` · `0004_applog` — `pipe_event` 원천·`except_doc_info` 확장자·크기 칸 · 검색 판 `0006_search` — `doc` 처리 기록 칸 · EDW에 쓰지 않음(쓰기 계정·`parsing_meta_table` 칸 없앰) | 첫 `run_pipeline.py` 전에 `migrate up` · 옛 기록 옮기기 | §6 |
| 마스터 판 `0002_master` — 표 `glossary` 하나(옛 마스터 표 일곱 개를 지움), 원본 CSV 하나 `glossary.csv` | 서버 실명 자료를 `glossary.csv`로 옮김(`common.store.master convert`) · `migrate up --target master` 바로 뒤 `migrate master load` | §6 |
| settings.yaml 칸 이름 정리 · 맨 아래 선택 절 `option.devbox` | 옛 이름이 남으면 모든 명령이 시작 거부 | §5 |
| 벌 폴더 = 코드 폴더(`settings.yaml`·`edw_chain.yaml`·`output/`이 코드 폴더 안), 벌 번호 = 폴더 이름 끝 `-<숫자>`, 칸 `ops.host.instance_name` 지움 | 처음 한 번 옛 루트에서 옮김 · 그 칸이 남으면 시작 거부 | §4 · §5 |
| 개발자별 벌(폴더 이름 끝 번호)·gitea | 개발 서버만, 원할 때 | §9 |

## 1. 지금 판 확인

```bash
export DOCKER=podman
cd <벌 폴더>                                                                  # 0.2.0 서버면 <옛 루트>/sbl_data_parsing-<앞 판>
cat VERSION CODE_COMMIT                                                       # 코드 폴더의 판·커밋
$DOCKER image inspect <이미지 태그> --format '{{json .Config.Labels}}'          # 이미지 라벨 — version(판)·revision(빌드 커밋)
$DOCKER logs data-pipeline 2>&1 | grep -m2 -E '^\[(image|code)\]'           # 시작 로그
# 기대: [image] 이미지 <이름 판 커밋> · 코드 <커밋> · 의존성 <지문>   (실행 이미지만 — 운영 이미지는 이 줄이 없음)
#       [code] 판 <판> · 커밋 <커밋>                                         (실제로 도는 코드)
bash deploy/host/scripts/pipe_exec.sh migrate current --target all            # DB 판
# 기대(0.2.0): search … 판 끝 ['0005_search'] · applog … 판 끝 ['0001_applog'] · master … 판 끝 ['0001_master']
```
- 이미지 태그는 settings.yaml `required.deploy.pipeline_image`·`mcp_image` 값이다. 여러 벌이면 컨테이너 이름 끝에 `-<벌 번호>`가 붙는다.

## 2. 백업

먼저 자동 실행을 멈추고, 도는 `run_pipeline.py`가 끝나길 기다린다(죽이지 않는다).
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer       # 여러 벌이면 벌마다(이름 끝 -<벌 번호>)
pgrep -af run_pipeline.py                                                     # 기대: 아무것도 안 나옴(나오면 끝날 때까지 기다림)

B=<벌 폴더>  PG_C=<required.deploy.pg_container_name>  PG_U=<required.pg.pg_user>  PG_D=<required.pg.pg_database>
S=<required.pg.pg_schema>
BK=<백업 폴더 — 벌 폴더 밖>/<앞 판>-$(date +%Y%m%d-%H%M); mkdir -p "$BK" && chmod 700 "$BK"
tar -czf "$BK/code.tar.gz" --exclude=./output --exclude=./home -C "$B" .      # 코드·settings.yaml·edw_chain.yaml(output/·home/은 덮어써도 남음)
$DOCKER exec "$PG_C" pg_dump -U "$PG_U" -d "$PG_D" -Fc -n "$S" -n "${S}_*" -n applog > "$BK/pg.dump"   # 검색(+ 원천 5벌·마스터)·applog
$DOCKER exec -i "$PG_C" pg_restore -l < "$BK/pg.dump" | grep -c ' TABLE '     # 기대: 0보다 큰 수 — 0이면 덤프 실패
```
- 0.2.0 서버는 설정이 코드 폴더의 부모에 있으므로 `B=<옛 루트>`로 루트째 묶는다(같은 명령).
- 벌마다 `code.tar.gz`, DB(`pg_dump`)는 모든 벌이 같이 쓰므로 한 번.
- 우리 스키마만 뜬다(공유 DB). `pg_dump`가 암호를 물으면 DB 담당과 함께 한다. applog는 MCP 호출 원문이 있어 클 수 있다 — 디스크를 먼저 본다(`df -h <백업 폴더>`).
- 백업 폴더에는 비밀값·DB 내용이 있다 — 권한 700 그대로, 밖으로 옮기지 않는다.

## 3. 새 실행 이미지 불러오기 · 의존성 지문 확인

새 코드가 요구하는 의존성 지문(`deploy/docker/DEPS_HASH`)과 같은 지문의 실행 이미지를 쓴다. 다르면 컨테이너가 `의존성 지문이 다름`으로 멈춘다.
```bash
cd <공용 폴더>    # 예 /home/sbl — 새 이미지 저장소 zip을 여기에 푼다(sbl_images-main/)
DOCKER=podman bash sbl_images-main/load.sh <이미지 판>                        # 기대: 조각 sha256 확인 → load → <판>/BUILD.txt
grep DEPS_HASH sbl_images-main/<이미지 판>/BUILD.txt                          # 이미지 지문
cat sbl_data_parsing-<새 판>/deploy/docker/DEPS_HASH                          # 코드 지문(§4 첫 줄로 푼 뒤) — 기대: 두 값이 같음
```
- 0.3.0은 실행 이미지에 개발 도구가 들어가고 패키지 목록이 바뀌어 **새 실행 이미지가 꼭 필요하다**(0.2.0 실행 이미지로는 시작하지 않음). 코드만 바뀐 판(지문이 같음)은 이 절을 건너뛴다.
- 운영 서버: 개발 서버에서 `bake_prod_image.sh`로 구운 조각을 옮겨 `load.sh <VERSION>`([release-and-patch §1-2](release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)).

## 4. 벌 폴더에 새 코드 덮어쓰기

```bash
cd <공용 폴더> && unzip -q <코드 zip>                                        # 기대: <공용 폴더>/sbl_data_parsing-<새 판>/
find "$B" -mindepth 1 -maxdepth 1 ! -name .git ! -name output ! -name home ! -name edw_chain.yaml ! -name "settings*" -exec rm -rf {} +   # 옛 코드만 지움
cp -a sbl_data_parsing-<새 판>/. "$B/" && rm -rf sbl_data_parsing-<새 판>    # 벌 폴더 위에 새 코드
cd "$B"
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>                # 기대: "[host_ctl init] 루트: $B" — 있는 설정 파일은 덮지 않음
cat CODE_COMMIT                                                               # 기대: 그 판의 커밋
```
- `settings.yaml`·`edw_chain.yaml`·`output/`(파싱 캐시·임베딩 캐시·FAQ 교체 기록 — 잃으면 전부 다시 처리)·`home/`은 zip에 없어 덮어써도 남는다. 지우거나 옮기지 않는다.
- 옛 코드를 먼저 지우는 까닭: 새 판에서 지운 파일(옛 시험 등)이 남으면 selftest(`host_ctl.sh check`)가 그 파일 때문에 실패한다.
- **0.2.0 서버에서 처음 올릴 때만**(설정·결과가 코드 폴더의 부모 `<옛 루트>`에 있음): 덮어쓰지 않고 새 벌 폴더를 만들어 옛 루트에서 옮긴 뒤 위 `init`부터 한다. 옛 루트는 되돌리기용으로 그대로 둔다.
```bash
cd <공용 폴더> && unzip -q <코드 zip> && mv sbl_data_parsing-<새 판> sbl_data_parsing-main-1   # 운영 서버·한 벌이면 번호 없이 sbl_data_parsing-main
B=<공용 폴더>/sbl_data_parsing-main-1
cp -p <옛 루트>/settings.yaml <옛 루트>/edw_chain.yaml "$B/" && cp -a <옛 루트>/output "$B/"
```
  `ops.host.host_output_dir`로 결과 폴더를 루트 밖에 두었으면 `output`은 복사하지 않는다.
- settings.yaml 이미지 칸을 새 태그로 고친다(§5) — dev `data-pipeline-runtime:<이미지 판>`·`mcp-server-runtime:<이미지 판>`, prd `data-pipeline:<VERSION>`·`mcp-server:<VERSION>`.

## 5. 설정 고치기

컨테이너를 새 코드로 띄우기(§6) 전에 한다. 벌 폴더의 `settings.yaml`을 새 판의 `settings.sample.yaml`과 대조해 고친다. 옛 이름·지운 칸·모르는 칸이 하나라도 있으면 모든 명령이 시작을 거부하고 칸 이름만 알린다(값은 안 찍음).
```bash
bash deploy/host/scripts/load_settings.sh common.host >/dev/null && echo 설정-읽힘   # 기대: 설정-읽힘("[설정] …"이면 그 안내대로 고침)
$DOCKER run --rm --entrypoint python -v "$PWD:/app/deploy:ro,z" <새 실행 이미지> -m common.config.sample --where <옛 이름>   # 칸의 새 자리(운영 이미지는 -v 없이)
```
- **칸 이름이 바뀌었다** — 옛 → 새 전체 표는 [refactor.md 부록 — 칸 이름 대응표](../refactoring/refactor.md#부록--설정-칸-이름-대응표)(1차 표의 새 이름이 2차 표의 옛 이름 — 둘 다 옮김).
- **`ops.host.instance_name` 줄을 지운다** — 벌 번호는 코드 폴더 이름 끝 `-<숫자>`라 이 칸은 모르는 칸이다(남으면 시작 거부). PG 스키마·게시 경로에 붙던 `_<벌>`도 없어져 모든 벌이 `required.pg.pg_schema` 그대로를 쓴다(옛 벌 스키마는 더 쓰지 않음 — 남은 스키마는 DB 담당과 정한다).
- **새 선택 절 `option.devbox`**(파일 맨 아래) — 개발 서버의 SSH 작업 공간. 비우면 끔. 쓰는 법은 [README §5-0 "개발 작업 공간"](../../README.md#5-0-배포-단계와-개발-서버-설치).
- **경로 칸은 컨테이너 안 절대 경로로** 적고, 쓰는 자리는 `/app/output/…` 아래여야 한다 — [env-guide §5](env-guide.md#5-서버-경로-칸--컨테이너-안-절대-경로).
- 남은 옛 칸은 §6에서 컨테이너가 뜰 때 칸 이름으로 알려 준다 — 고치고 다시 띄운다.
- 고친 뒤 주인·권한: `chown 10001:<운영 그룹> "$B/settings.yaml" && chmod 640 "$B/settings.yaml"`.

## 6. DB 판 올리기 — `migrate up`

```bash
bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline     # 벌 폴더에서 — pipe_exec.sh가 이 안에서 돈다
bash deploy/host/scripts/pipe_exec.sh migrate current --target all
# 기대(0.2.0 → 0.3.0): applog applog: 판 낮음 ['0001_applog'] · 코드의 끝 판 0004_applog · search도 판 낮음(끝 판 0006_search) · master도 판 낮음(끝 판 0002_master)
bash deploy/host/scripts/pipe_exec.sh migrate up --target applog
# 기대: [migrate] applog applog: 판 ['0004_applog'] (끝 0004_applog)
bash deploy/host/scripts/pipe_exec.sh migrate up --target search                # 0.3.0: 원천 스키마 5벌 doc에 처리 기록 칸(0006_search)
bash deploy/host/scripts/pipe_exec.sh migrate up --target master                # 0.3.0: 표 glossary 하나로(0002_master — 옛 마스터 표를 지움)
bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary   # 바로 채움(샘플이면 --dir 없이) — 비어 있으면 구조화·검색이 시작하지 않음
bash deploy/host/scripts/pipe_exec.sh migrate check --target all              # 기대: 갈래마다 "판 끝 [...] · 코드의 끝 판 ...", 종료 코드 0
```
- **applog는 모든 벌이 함께 쓴다 — 어느 벌이든 0.3.0 코드 폴더로 바꾸기 전에 `migrate up --target applog`(또는 `--sql` 파일을 손으로 실행)를 먼저 끝낸다.** 판 `0004_applog` 전의 applog에는 새 코드의 사건 행(`source_system` 칸)이 들어가지 못해 그 벌의 applog 기록이 모두 파일 대체 기록(`output/logs/*.jsonl`)으로 가고, 적재 안 된 문서 기록(`except_doc_info`)은 칸 없음으로 실패한다.
- DB 담당이 SQL을 먼저 보고 손으로 실행하려면: `bash deploy/host/scripts/pipe_exec.sh migrate up --target applog --from 0001_applog --sql /app/output/up_applog.sql`(DB·접속 정보 없이 — 스키마 이름만 설정에서 · `<벌 폴더>/output/`에 다 만든 뒤 한 번에 씀 · `--from` = `migrate current`가 보인 지금 판, 갈래마다 — 없는 갈래는 빈 스키마부터라 경고 줄과 `-- 주의:` 주석이 나온다 · 차원을 읽는 판(`0001_search`·`0002_search`)이 들면 `--dim`이 필요). DB를 읽어야 하는 확인(지금 판·vector 확장·남의 스키마·차원)은 파일 안 `-- 수동:` 줄이다. 손으로 실행한 뒤 `migrate check --target all`.
- 갈래(`--target`)마다 따로 올리면 어느 갈래가 바뀌었는지 출력에서 바로 보인다. 한 번에는 `--target all`.
- 벌이 여럿이면 아무 벌 하나에서 한 번 — 다른 벌은 §4·§5 뒤 §10만 한다.
- 0.3.0의 applog `0003_applog`는 새 표 `except_doc_info`를 만들고 옛 `skip_doc_info` 행을 `skip`으로 옮긴다. `0004_applog`는 `pipe_event`에 `source_system`, `except_doc_info`에 `file_ext`·`file_size` 칸을 더한다(옛 행은 비움). search `0006_search`는 `doc`에 처리 기록 칸(`sha256`·`silver_bucket`·`silver_key`·`engines`·`parse_status`·`silver_version`·`gold_version`·`parsed_at`·`loaded_at`)을 더한다. **첫 `run_pipeline.py` 전에** 둘 다 올린다 — 없으면 대상 목록·받기가 표 없음으로 멈춘다.
- 0.3.0 사람이 할 일(DB 담당과): EDW `AI.ParsingMeta`에 있던 처리 기록을 `doc` 새 칸으로 손으로 옮긴다(파이프라인은 EDW에 더 쓰지 않고, `doc` 행이 있으면 끝난 문서로 본다). 옮긴 것을 확인한 뒤 옛 표 `applog.skip_doc_info`를 지운다(마이그레이션은 지우지 않음). settings.yaml에 `edw_write_user`·`edw_write_password`·`parsing_meta_table` 칸이 남아 있으면 시작을 거부하므로 지운다.
- 0.3.0의 master `0002_master`는 표 `glossary`를 만들고 옛 마스터 표(`client_roster`·`domain_terms`·`id_patterns` 등 일곱 개)를 지운다(되돌리기 없음 — 먼저 마스터 스키마 백업). `master load`는 `glossary.csv` 하나만 읽으므로 **올리기 전에** 서버 실명 자료(옛 CSV)를 `glossary.csv`로 옮겨 둔다(`$DOCKER exec data-pipeline python -m common.store.master convert --src /app/output/glossary --out /app/output/glossary/glossary.csv` — [server-guide §5-1](server-guide.md#5-1-고객-명부용어집-작성법), refactor.md C-108).
- `올린 뒤에도 차이:`가 나오거나 종료 2이면 멈추고 출력(이름만)을 DB 담당과 본다. 오류 분기는 [release-and-patch §5-5](release-and-patch.md#5-5-db-버전-관리--migrate).

## 7. pgvector가 바뀔 때 — 두 경우

검색 DB에 들어가는 것을 바꾸는 방법은 둘이다. 어느 쪽으로 할지는 사람이 정한다.

**(가) 문서 메타 키만 — 스키마 그대로.** 문서 메타는 `doc.attrs`(JSON 칸) 하나에 들어가므로 키를 더하거나 EDW 칸을 바꿔도 표는 그대로다.
1. `<루트>/edw_chain.yaml`의 `fields`를 고친다(법: [release-and-patch §8](release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버)).
2. 점검: `$DOCKER exec data-pipeline python -m pipeline.load.edw_doc_meta --check` — 기대 `[edw_meta] 사슬 설정 OK(…)`, 종료 코드 0.
3. 이미 적재한 문서는 값이 저절로 차지 않는다 — 영향받는 원천의 문서를 §8의 순서로 `--replace` 다시 적재한다.

**(나) 표 구조(표·칸·색인)를 바꿀 때.** 새 마이그레이션 판(`common/store/db/migrations/versions/`)이 필요하다. DB 스키마 변경이라 **사람 검토와 DB 담당 합의가 먼저**다. 올리는 법은 둘 중 하나:

| 방법 | 순서 | 좋은 점 · 조심할 점 |
|---|---|---|
| 그 자리에서 올리기 | §2 백업 → §6 `migrate up --target search` → `migrate check` | 다시 적재가 필요 없을 수 있다 · 되돌리려면 백업 복원(§11) |
| 새 스키마에 전부 다시 | settings.yaml `required.pg.pg_schema`를 새 이름으로 → `migrate up --target all --dim <임베딩 차원>` → `migrate master load` → 전체 다시 처리(§8) → 검색 MCP를 새 스키마로 다시 띄움(`host_ctl.sh up -d --force-recreate mcp`) | 옛 스키마가 그대로 남아 되돌리기가 쉽다 · 전체 재처리 시간·디스크가 든다. 옛 스키마는 확인 뒤 DB 담당이 백업하고 지운다 |

- 임베딩 모델을 바꾸는 것도 (나)의 새 스키마 쪽이다 — 적재는 모델이 다른 묶음을 같은 스키마에 넣지 않는다.

## 8. 다시 처리할 층과 명령

판이 바뀌어도 **이미 처리한 문서는 저절로 다시 처리되지 않는다.** 레이어 코드 지문은 실행 기록(`applog.pipe_run.code_fp`)에 남기기만 하고 재처리를 일으키지 않는다. 다시 할 문서와 층은 사람이 정해 아래 명령으로 돌린다.

| 바뀐 것 | 다시 할 층 |
|---|---|
| 사슬 파일(문서 메타) · 마스터 표(고객 명부·용어집) | 구조화 + 적재(`--replace`) |
| 청크·임베딩 쪽 코드 · 임베딩 모델 | 구조화 + 적재(모델이면 새 스키마 — §7 (나)) |
| 파싱 엔진·대표 결과 고르기 | 파싱부터 전부(게시 포함) — `run_pipeline.py` |

**`--skip-done`:** 끝난 문서(원천 스키마 어디든 gold `doc` 행이 있는 원본 키)와 `applog.except_doc_info`의 `skip` 문서를 대상에서 뺀다. 새 문서만 돌릴 때 쓰고(새벽 배치가 이것), 다시 처리할 때는 주지 않는다.

**구조화 + 적재만 다시(게시 없이).** 서버는 문서가 끝나면 작업 폴더(`_docflow/<번호>/`)를 지우므로 묶음이 남아 있지 않다. 그 문서를 파싱해 묶음을 다시 만들고 `--replace`로 적재한다(Object Storage에는 다시 쓰지 않음).
```bash
# 1) 다시 할 문서 목록 CSV — EDW AI.FileStorageMap의 다섯 칸(id·s3_key·original_filename·file_size·content_version_id)
#    query_edw 등으로 뽑아 <결과 폴더>/redo/list.csv 에 둔다(컨테이너에서 /app/output/redo/list.csv)
R=/app/output/redo
$DOCKER exec data-pipeline python -m pipeline.cli --set PIPE_OUT_ROOT=$R parse --source rdb:csv:$R/list.csv --src $R/prepared
$DOCKER exec data-pipeline python -m pipeline.transform.structure.gold_bundle --set PIPE_OUT_ROOT=$R \
    --parse-dir $R/parse --src $R/prepared --out $R/bundle
$DOCKER exec data-pipeline python -m pipeline.load.pgvector_load --set PIPE_OUT_ROOT=$R \
    load --bundle $R/bundle --rep-dir $R/parse/_rep --replace                  # 기대: 종료 코드 0
```
- 끝나면 `<결과 폴더>/redo/`를 지운다(원본 사본이 들어 있음).
- `--replace`는 판 표가 있는 우리 스키마에서만 된다. 적재는 묶음에 없는 문서를 지우지 않는다.

**파싱부터 전부.** `python3 deploy/host/scripts/run_pipeline.py`를 `--skip-done` 없이 돌린다(문서 몇 개만이면 `--seqs <번호,…>`). 게시를 다시 하므로 Object Storage에 같은 문서가 새 날짜 이름으로 한 벌 더 생긴다. 적재는 같은 문서를 건너뛰므로 gold까지 바꾸려면 새 스키마에 적재한다(§7 (나)).

## 9. gitea·개발자별 벌로 바꾸기(개발 서버만, 원할 때)

- 코드를 내부망 gitea에서 받는 법: [gitea-guide.md](gitea-guide.md).
- 개발자마다 벌 폴더 하나(`<공용 폴더>/sbl_data_parsing-main-<번호>`): 폴더 이름 끝 번호로 컨테이너·compose 묶음·타이머 이름이 나뉘고, 그 벌의 settings.yaml에 포트 두 칸(`search.server.mcp_port`·`ops.services.data_parsing.data_parsing_port`)을 벌마다 다르게 적는다 — [server-guide §1-3](server-guide.md#1-3-한-서버에-여러-벌-띄우기개발자별). PG 스키마·EDW 기록 표는 모든 벌이 함께 쓴다.
- DB 표는 공용이라 새 벌에서 `migrate`를 다시 하지 않는다(서버의 첫 벌만 `migrate up --target all --dim <임베딩 차원>` → `migrate master load`).

## 10. 올린 뒤 점검

```bash
bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp
bash deploy/host/scripts/host_ctl.sh check                                    # 기대 마지막 줄: [host_ctl check] 통과 — 6개
curl -s http://127.0.0.1:<search.server.mcp_port>/health                      # 기대: {"ok":true,"ready":true,"store":"pgvector",…}
bash deploy/host/scripts/pipe_exec.sh parse --source-limit 3                  # 원본 3건 파싱 — 기대: 종료 코드 0
bash deploy/host/scripts/pipe_exec.sh publish --dry-run > /tmp/dry.json; grep -c 'CRMS/CRMS/' /tmp/dry.json; rm /tmp/dry.json
# 기대: 0 — 게시 열쇠(rep_key)에 원천 이름이 두 번(CRMS/CRMS/) 들어가면 실제 publish를 하지 않는다
```
- MCP 클라이언트로 `search` 한 번(원천 `source_system` 필수) 뒤 로그 행이 생기는지:
```bash
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT tool_name, status, requested_at FROM applog.mcp_log ORDER BY requested_at DESC LIMIT 3"
# 기대: 방금 부른 search 한 행(status ok) · <벌 폴더>/output/logs/ 가 비어 있음(파일이 있으면 DB 쓰기 실패)
```
- 처음 게시하는 서버면 실제 처리(게시·적재) 한 번 뒤 `doc` 처리 기록과 Object Storage 파일을 본다:
```bash
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT file_path, parse_status, silver_bucket, silver_key, parsed_at, gold_version FROM <pg_schema>_<원천>.doc ORDER BY loaded_at DESC NULLS LAST LIMIT 5"
# 기대: 처리한 문서 수만큼 행 · parse_status ok·partial · silver_key·gold_version이 채워짐 (<원천> = sfdc·crms·las·faq·other)
$DOCKER exec data-pipeline python -c "import sys; from common.store.objectstore import client; r=client().list_objects_v2(Bucket=sys.argv[1], Prefix=sys.argv[2]); [print(o['Key'], o['Size']) for o in r.get('Contents', [])]" <silver_bucket> <silver_key의 폴더>
# 기대: <파일명>_<날짜>.md · .json · _meta.json 과 engine/ 아래 파일
```
- 실제 publish는 한 번만 한다(다시 돌리면 Object Storage에 같은 결과가 새 시각 이름으로 또 올라감).
- 다 되면 자동 실행을 다시 켠다(단위 틀을 이 코드 폴더로 다시 씀): `bash deploy/host/scripts/host_ctl.sh timers` → `versions.md`에 한 줄([release-and-patch §3](release-and-patch.md#3-배포-판정--selftest)).

## 11. 되돌리기

**코드·설정:** §2의 `code.tar.gz`로 벌 폴더를 되살린다. 새 판에만 있는 파일(새 마이그레이션 판 등)이 남지 않게 덮지 않고 새 폴더에 푼다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
pgrep -af run_pipeline.py                                                     # 기대: 없음(있으면 끝날 때까지 기다림)
cd "$B" && bash deploy/host/scripts/host_ctl.sh down
mv "$B" "$B.new" && mkdir "$B" && tar -xzf "$BK/code.tar.gz" -C "$B"         # 앞 판 코드·설정
mv "$B.new/output" "$B/"; [ -d "$B.new/home" ] && mv "$B.new/home" "$B/"     # 결과·홈은 그대로 옮김
cd "$B" && bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline mcp-data-parsing mcp
bash deploy/host/scripts/host_ctl.sh timers
```
- `$B.new`(새 판 코드)는 확인 뒤 사람이 지운다.
- 0.2.0에서 처음 올렸다면(§4 마지막) 옛 루트가 그대로 있다 — 새 벌 폴더에서 `host_ctl.sh down` 뒤 `<옛 루트>/sbl_data_parsing-<앞 판>`에서 `host_ctl.sh up -d --force-recreate …` → `host_ctl.sh timers`.

**DB:** 새 판이 DB 판을 올렸으면 옛 코드는 그 판을 모른다 — 적재·`migrate`가 "이 코드가 모르는 판"으로 종료 2(0.3.0의 applog `0004_applog`면 매일 하는 `migrate maintain --target applog`가 멈춘다). 내리는 명령(downgrade)은 없으니 **백업에서 그 스키마를 되살린다** — DB 담당과 함께.
```bash
SC=applog                                                                     # 판이 바뀐 스키마(검색이면 $S와 ${S}_<원천>…)
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "ALTER SCHEMA $SC RENAME TO ${SC}_rollback_$(date +%m%d)"   # 지우지 않고 비켜 둠
$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "CREATE SCHEMA $SC"        # pg_restore -n은 스키마 자체를 만들지 않는다
$DOCKER exec -i "$PG_C" pg_restore -U "$PG_U" -d "$PG_D" -n "$SC" < "$BK/pg.dump"
bash deploy/host/scripts/pipe_exec.sh migrate check --target applog           # 기대: 앞 판 코드로 "판 끝 [...]", 종료 코드 0
```
- 권한(GRANT)은 DB 담당이 원래대로 맞춘다. 비켜 둔 스키마는 확인 뒤 DB 담당이 지운다.
- 그 사이 새 판이 쓴 applog 행·검색 적재는 되살린 스키마에 없다(비켜 둔 스키마에 남음).

**작업 폴더·잠금·진행 기록:** `run_pipeline.py`의 작업 폴더(`ops.run_pipeline.run_pipeline_work_dir`, 비우면 코드 폴더 안 `deploy/host/scripts/test_space/`)에 진행 기록 `batch_progress/progress.log`와 잠금 `batch_progress/run_pipeline.lock`이 있다. 작업 폴더를 비워 두었으면 코드 폴더 안이라 덮어써도 남지만, 되돌리기(위)는 백업할 때의 것으로 돌아간다 — 바꾸기 전에 `pgrep -af run_pipeline.py`로 도는 실행이 없는지 꼭 본다([server-guide §3](server-guide.md#3-실패한-문서-찾기와-다시-돌리기)).
