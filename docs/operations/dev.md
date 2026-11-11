# 개발 서버(dev) 실행 순서

개발 서버에는 두 가지 묶음이 함께 돈다.

| 묶음 | compose 파일(묶음 이름) | 폴더 | 컨테이너 | 이미지 |
|---|---|---|---|---|
| 개발자 벌 1~4 | `compose-dev.yml`(`docker-dev`) | `/home/sbl/data_pipeline-<n>/{app,home}` | `data-pipeline-<n>`(SSH `802<n>`) | 실행 이미지 `data-pipeline-runtime` + 코드 폴더 |
| 출시 전 시험(운영 묶음과 같음) | `compose-prd.yml`(`sbl-prd`) | `/home/sbl/data_pipeline/{app,home}` | `data-pipeline`(SSH 8020) · `mcp-server`(SSH 8050 · HTTP 8051) · `mcp-data-parsing` | 구운 이미지 `data-pipeline`·`mcp-server` |

벌 하나의 폴더:
- `app/` → 컨테이너 `/app` — git 코드 + `settings.yaml` + `output/`(결과)
- `home/` → 컨테이너 `/root` — root 홈(opencode·VS Code 서버·git 설정)
- 원본 문서 폴더(`required.deploy.host_docs_dir`, 기본 `/data/docs`) → `/data/docs`(읽기 전용)

컨테이너 안에서 같은 폴더가 두 자리에 보이지 않는다. 이미지 부품은 `/opt/sbl/{docker,assets}`에 있다. 설정 칸 뜻은 [settings.md](settings.md).

- A — 서버 호스트 root 셸에서 설치·운영
- B — 벌 컨테이너 안(SSH)에서 시험
- C — 벌끼리 간섭 없이 일하기
- D — 출시 전 시험(운영 묶음, 문서 100건 안팎)

---

## A. 서버 호스트(root 셸)

```bash
export DOCKER=docker; S=/home/sbl          # 공용 폴더
```

### A-1. 벌 폴더 만들기
```bash
cd $S && unzip -q <코드 zip>                                   # 기대: sbl_data_parsing-<판>/ (git archive로 만든 zip — 커밋 표시가 들어감)
for b in data_pipeline-1 data_pipeline-2 data_pipeline-3 data_pipeline-4 data_pipeline; do
  mkdir -p $S/$b/home && cp -a sbl_data_parsing-<판> $S/$b/app; done
rm -rf sbl_data_parsing-<판> $S/data_pipeline*/app/valid_env    # 서버에는 PC 시험 데이터가 필요 없다
```

### A-2. 실행 이미지 불러오기(판마다 한 번)
```bash
cd $S && unzip -q <이미지 zip> && mv sbl_images-<이미지 판> sbl_images   # 이미지 저장소의 <이미지 판> 브랜치 zip
cat sbl_images/<이미지 판>/BUILD.txt                            # DEPS_HASH 확인
cat $S/data_pipeline-1/app/deploy/docker/DEPS_HASH             # 위와 같아야 함
bash sbl_images/load.sh <이미지 판>                             # 실행 이미지 2개 + redis
docker load -i <pgvector_pg16.tar>                              # PG 이미지 — 인터넷 PC에서 docker pull pgvector/pgvector:pg16 && docker save pgvector/pgvector:pg16 -o pgvector_pg16.tar
docker image ls | grep -E '^(data-pipeline-runtime|mcp-server-runtime|redis|pgvector/pgvector) '   # 기대: 4줄
```
compose 파일의 기본 판과 다르면 그 벌의 `app/deploy/host/compose/.env`에 `IMAGE_TAG=<이미지 판>` 한 줄.

### A-3. 개발 홈 묶음 풀기(컨테이너 띄우기 전)
```bash
cd $S/sbl_images/<이미지 판> && sha256sum -c --quiet devhome.sha256 && echo OK
for H in $S/data_pipeline-{1,2,3,4}/home $S/data_pipeline/home $S/data_pipeline/home/mcp; do
  mkdir -p "$H" && cat devhome.tar.gz.part* | tar -xzf - -C "$H"; done
ls -a $S/data_pipeline-1/home | grep -E 'vscode-server|config|bashrc'
```
접속 PC의 VS Code는 1.117, 자동 업데이트 끔(`update.mode: none`). opencode 권한은 저장소 맨 위 `opencode.jsonc`(git — `/app`에서 시작하면 적용)이고, 홈의 `home/.config/opencode/opencode.json`에는 모델 주소만 둔다.

### A-4. 벌 폴더 채우기
호스트 준비(한 번): `dnf install -y python3-pyyaml` · `groupadd <운영 그룹>`(없으면 init의 chown이 실패).
```bash
for b in data_pipeline-1 data_pipeline-2 data_pipeline-3 data_pipeline-4 data_pipeline; do
  (cd $S/$b/app && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>); done
```
끝에 빈 필수 칸 이름이 나온다.

### A-5. 설정 채우기
`app/settings.yaml`의 빈 칸을 채운다 — 칸 목록은 [settings.md](settings.md). 벌마다 다른 칸:

| 폴더 | `required.env.run_env` | `ops.host.pipeline_container` | `required.source.source_systems` |
|---|---|---|---|
| `data_pipeline-<n>/app` | `dev` | `data-pipeline-<n>` | `DEV-<n>` |
| `data_pipeline/app` | `prd` | 비움(= `data-pipeline`) | 시험할 운영 원천(예 `SFDC` — `DEV-*`는 prd가 시작 거부) |

비밀번호는 compose 파일의 `null` 칸에 직접 적는다 — 서버 사본에서만(저장소에는 `null`만 둔다). 값에 `$`가 있으면 `$$`로 적는다.

| 파일 | 채울 칸 |
|---|---|
| `deploy/host/compose/compose-dev.yml`(벌 1~4 모두 — 벌 1 폴더에서 띄우고, 나머지 벌은 판 올리기·다시 만들기 때 자기 폴더의 사본으로) | `configs.root_pw.content`(SSH root, 8자 이상) · `pgvector`의 `POSTGRES_DB`·`POSTGRES_USER`·`POSTGRES_PASSWORD` · `redis`의 `REDIS_PASSWORD` — PG·Redis는 settings.yaml `required.pg`·`common.connections.redis.redis_password`와 같은 값 |
| `deploy/host/compose/compose-prd.yml`(`data_pipeline/app`) | `configs.root_pw.content`만(개발 서버의 PG·Redis는 compose-dev.yml의 것) |

```bash
cd $S/data_pipeline-1/app && vi deploy/host/compose/compose-dev.yml && chmod 600 deploy/host/compose/compose-dev.yml
for n in 2 3 4; do cp -p deploy/host/compose/compose-dev.yml $S/data_pipeline-$n/app/deploy/host/compose/; done
cd $S/data_pipeline/app && vi deploy/host/compose/compose-prd.yml && chmod 600 deploy/host/compose/compose-prd.yml
```
git으로 받은 폴더(C절)는 `git update-index --skip-worktree deploy/host/compose/compose-dev.yml`(채운 값이 커밋되지 않게 — 그 파일이 새 판에서 바뀌면 직접 옮겨 적는다).

```bash
cd $S/data_pipeline-1/app && bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK
```

### A-6. PG·Redis 띄우기(서버에 한 번 — 벌 1 폴더에서)
```bash
cd $S/data_pipeline-1/app
mkdir -p /data/pg/pipeline /data/redis
bash deploy/host/scripts/host_ctl.sh --profile db up -d pgvector redis   # compose-dev.yml의 프로필 db — 벌을 내리거나 다시 만들어도 그대로
until docker exec pgvector pg_isready -h 127.0.0.1 -U <계정> -d <DB>; do sleep 1; done
docker exec pgvector psql -U <계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
docker ps --filter name=^redis$ --format '{{.Status}}'        # 기대: Up … (healthy)
```

### A-7. 방화벽
```bash
for p in 8020 8021 8022 8023 8024 8050 8051 8010 5433; do firewall-cmd --permanent --add-port=$p/tcp; done && firewall-cmd --reload
firewall-cmd --list-ports
```

### A-8. 벌 띄우기
```bash
cd $S/data_pipeline-1/app
bash deploy/host/scripts/host_ctl.sh up -d                     # 벌 1~4 모두 — 네 벌의 settings.yaml을 다 채운 뒤(한 벌만이면 up -d data-pipeline-<n>)
bash deploy/host/scripts/host_ctl.sh ps                        # 기대: data-pipeline-1~4 Up
```
처음이면 A-9 전에 DB 표를 만든다(B-3 — 아무 벌 안에서 한 번, 없으면 A-9 migrate check가 실패).

### A-9. 점검(벌마다)
```bash
cd $S/data_pipeline-<n>/app && bash deploy/host/scripts/host_ctl.sh check   # 기대 마지막 줄: [host_ctl check] 통과 — 5개
```
벌 점검은 파이프라인만 본다(검색 MCP는 D의 운영 묶음에 있다).

### A-10. 한 번에 돌리기 — run_pipeline.py(EDW 목록 → 받기 → 파싱 → 게시 → 구조화·적재)
벌 컨테이너 **안에서**만 돈다(호스트에서 직접 부르면 거부). 순서: ① 사전 점검(설정·모델·DB 판·배포 시험) → ② 문서 처리 → ③ 적재·검색 확인. 첫 실패에서 멈추고 끝에 `[판정]` 줄을 남긴다.
벌의 ③은 실행 기록과 DB 검색까지다 — 운영 묶음의 검색 MCP는 DEV 원천을 검색하지 않는다(MCP까지는 B-9처럼 벌 안에 MCP를 띄워 확인).

호스트에서 한 줄로(`R` = 아래 표의 인자):
```bash
docker exec -w /app data-pipeline-<n> python3 deploy/host/scripts/run_pipeline.py R
tail -f $S/data_pipeline-<n>/app/deploy/host/scripts/test_space/batch_progress/progress.log   # 기대 끝 줄: [판정] 통과 — …
```
오래 걸리면 컨테이너 안(`ssh -p 802<n> root@<서버 IP>` → `cd /app`)에서 `nohup python3 deploy/host/scripts/run_pipeline.py R > run.out 2>&1 &`.

| 하고 싶은 일 | `R` |
|---|---|
| 시험(기본 2건 — `ops.run_pipeline.run_limit`) | (없음) |
| 전체 적재(끝난 문서는 건너뜀 — 새벽 배치와 같음) | `--limit 0 --skip-done` |
| 문서 하나 · 몇 개(번호는 B-5 목록의 순번) | `--seqs 7` · `--seqs 3,7,9` |
| 이름에 낱말이 든 문서만 | `--filter RFP,proposal --limit 0` |
| 새 문서 N건만(`--limit`은 목록 앞 N줄 — 끝난 문서도 셈) | `--limit 0 --skip-done --max-docs N` |
| 정해진 시각까지만 | `--limit 0 --skip-done --deadline 06:00`(`--max-docs N`도) |
| 문서별 임시 폴더 남기기 | `--no-cleanup` |
| 이번만 설정 바꾸기 | `--set RUN_PIPELINE_<칸>=값`(`ops.run_pipeline.*`) |

EDW가 아닌 **폴더의 파일**을 넣을 때는 run_pipeline이 아니라 B-6(파싱 `--source <폴더>`) → B-8(적재)을 쓴다.

종료 코드([pl-18](../prd/ops.md#pl-18)): 0 끝 · 1 실패 문서 있음 · 2 설정 문제 · 3 사전 점검·적재 확인 실패 · 75 마감·다른 run_pipeline이 도는 중(같은 벌에서 두 번 동시에 돌리면 뒤의 것). 진행 기록은 `deploy/host/scripts/test_space/batch_progress/`(문서별 `doc_<번호>.log`).

실패 문서는 재시도 상태(DLQ)에 남는다 — 한 실행에서 한 번씩 다시 시도하고 3번 실패하면 dead(사람이 다시 넣을 때까지 `--skip-done` 목록에서 빠짐). 끝 줄에 `DLQ pending N건 · dead M건`이 나온다.
```bash
docker exec data-pipeline-<n> python -m pipeline.shared.dlq list --status dead      # dead 목록
docker exec data-pipeline-<n> python -m pipeline.shared.dlq requeue --key <원본 키>  # 다시 넣기(--all-dead는 전부)
```

### A-11. 단계 하나씩 — pipe_exec.sh
호스트에서 컨테이너 안 명령 하나를 돌린다(컨테이너 = `ops.host.pipeline_container`, 안 떠 있으면 종료 2).
```bash
bash deploy/host/scripts/pipe_exec.sh check_env                 # 설정·접속 점검(FAIL 줄 없어야)
bash deploy/host/scripts/pipe_exec.sh ping_models               # 모델 주소 연결
bash deploy/host/scripts/pipe_exec.sh parse --source /data/docs --source-limit 3    # 파싱
bash deploy/host/scripts/pipe_exec.sh publish --dry-run         # 게시 미리 보기(쓰기 0)
bash deploy/host/scripts/pipe_exec.sh migrate check --target all
bash deploy/host/scripts/pipe_exec.sh show-stack                # 엔진 구성
```

### A-12. 로그
```bash
bash deploy/host/scripts/host_ctl.sh logs --tail 100 data-pipeline-<n>
```

### A-13. 백업(코드를 바꾸기 전)
```bash
pgrep -af run_pipeline.py                                     # 기대: 없음(있으면 끝날 때까지 기다림)
B=$S/data_pipeline-<n>/app; BK=<백업 폴더>/$(cat $B/VERSION)-$(date +%Y%m%d-%H%M); mkdir -p "$BK" && chmod 700 "$BK"
tar -czf "$BK/code.tar.gz" --exclude=./output -C "$B" .
docker exec pgvector pg_dump -U <계정> -d <DB> -Fc -n <스키마> -n '<스키마>_*' -n applog > "$BK/pg.dump"   # DB는 한 번만
```

### A-14. 새 판 코드로 바꾸기(벌 app 덮어쓰기)
```bash
cd $S && unzip -q <코드 zip>
B=$S/data_pipeline-<n>/app; T=deploy/host/scripts/test_space; C=deploy/host/compose/compose-dev.yml
{ [ ! -d "$B/$T" ] || mv "$B/$T" "$B.test_space"; } && cp -p "$B/$C" "$B.compose.yml" &&   # 채운 비밀번호 보관
  find "$B" -mindepth 1 -maxdepth 1 ! -name .git ! -name output ! -name "settings*" -exec rm -rf {} + &&
  cp -a sbl_data_parsing-<판>/. "$B/" && rm -rf "$B/valid_env" &&
  { [ ! -d "$B.test_space" ] || mv "$B.test_space" "$B/$T"; }
vi "$B/$C" && chmod 600 "$B/$C" && rm "$B.compose.yml"   # 새 판 파일의 null 칸을 $B.compose.yml의 값으로 다시 채움
cd "$B" && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
bash deploy/host/scripts/host_ctl.sh up -d --force-recreate data-pipeline-<n>
```
DB 판이 바뀐 판이면 B-3, 끝나면 A-9. 모든 벌을 바꿨으면 `rm -rf $S/sbl_data_parsing-<판>`.

### A-15. 이미지 정리(손으로, 가끔)
```bash
bash deploy/host/scripts/prune_images.sh                       # 지울 목록만 보기
bash deploy/host/scripts/prune_images.sh --apply               # 저장소마다 최신 ops.host.prune_keep_versions개(기본 2)만 남김 · 조각 폴더는 --stage-dir
```

---

## B. 벌 컨테이너 안(SSH)

컨테이너 안에는 docker가 없다 — 모듈을 `python -m`으로 바로 부른다.
```bash
ssh -p 802<n> root@<서버 IP>          # 비밀번호 = compose-dev.yml configs.root_pw(바꾸면 host_ctl.sh up -d --force-recreate data-pipeline-<n>)
cd /app
```

### B-1. 설정 확인
```bash
python -m pipeline.config                     # 읽은 settings.yaml과 요약(비밀은 가림)
python -m common.check.checker env            # 기대: FAIL 줄 없음
python -m common.check.checker ping           # 모델 주소 연결 — 실패 있으면 종료 1
```

### B-2. 배포 판정 시험
```bash
python -m pipeline.cli selftest               # 기대: 끝 줄 N/N 통과(FAIL 없음) · 일부만: --only <이름 일부>
```

### B-3. DB 표(처음 · DB 판이 바뀐 판)
```bash
python -m common.store.db.dbtool current --target all
python -m common.store.db.dbtool up --target all --dim <임베딩 차원> --sql /app/output/up.sql   # DB 담당 검토용 SQL만
python -m common.store.db.dbtool up --target all --dim <임베딩 차원>   # 차원 = B-1 ping의 dim
python -m common.store.db.dbtool master load
python -m common.store.db.dbtool check --target all     # 기대: 갈래마다 판 끝, 종료 코드 0
```
원천을 새로 더했으면(`DEV-<숫자>`) `up --target search`로 그 원천 스키마를 만든다. 다른 스키마로 시험: `--schema <스키마>`.

### B-4. 결과 폴더 정하기
```bash
O=/app/output/try-<이름>            # 호스트에서는 data_pipeline-<n>/app/output/try-<이름>
```

### B-5. EDW 대상 목록 미리 보기(읽기만)
```bash
python -m pipeline.extract.candidate_pick --set SOURCE_SYSTEMS=DEV-1,DEV-2 list --limit 5 --out $O/targets.json
```

### B-6. 파싱
문서 폴더 꼴은 `<원천>/<폴더>/<파일>`(맨 위 폴더 이름 = 원천).
```bash
python -m pipeline.cli --set PIPE_OUT_ROOT=$O parse --source /data/docs --src $O/prepared --source-limit 3
```
바꿔 보기:
```bash
--set SOURCE_SYSTEMS=DEV-1,DEV-2              # 읽을 원천(쉼표)
--set PARSE_SOURCE=/data/docs                 # 읽을 문서 폴더(--source를 안 줄 때)
--set DOC_DIR_PREPARED=$O/prepared            # 준비된 파일 폴더(--src를 안 줄 때)
--set PARSE_MAX_NEW=3                         # 새로 파싱할 문서 수 상한
--set PIPE_OUT_ROOT=$O                        # 결과 폴더
```
파일 하나만(절대 경로):
```bash
mkdir -p $O/one/DEV-1/f1 && cp <파일 절대 경로> $O/one/DEV-1/f1/
python -m pipeline.cli --set PIPE_OUT_ROOT=$O parse --source $O/one --src $O/prepared
```
결과: `$O/parse/_rep/`(문서마다 대표 결과).

### B-7. 게시(Object Storage)
```bash
python -m pipeline.load.publish_parse_result --out $O            # 미리 보기 — 쓰기 0
python -m pipeline.load.publish_parse_result --out $O --apply    # 실제 업로드 — 한 번만
```

### B-8. 구조화·임베딩 → 적재
```bash
python -m pipeline.transform.structure.gold_bundle --set PIPE_OUT_ROOT=$O \
  --parse-dir $O/parse --src $O/prepared --out $O/bundle
python -m pipeline.load.pgvector_load --set PIPE_OUT_ROOT=$O load --bundle $O/bundle \
  --rep-dir $O/parse/_rep --silver $O/publish/silver.jsonl         # 게시를 건너뛰었으면 --silver 빼기 · 다시 넣을 때 --replace
```
시험 스키마에 넣기: 두 명령에 `--set PG_SCHEMA=<스키마>`(먼저 B-3을 `--schema <스키마>`로).

### B-9. 검색 확인
```bash
python -m mcp_server.cli.search_ask ask --source DEV-1 --k 3 --q "<처리한 문서에 있는 낱말>"   # DB 검색만
```
내 벌 코드로 MCP를 잠깐 열어 보기(벌마다 bridge 망이라 127.0.0.1이 벌마다 따로 — 끝자리 벌 번호는 구별용):
```bash
python -m mcp_server.main --set MCP_PORT=1877<n> --set MCP_HOST=127.0.0.1 & echo $! > /tmp/mcp.pid
python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:1877<n>/mcp --source DEV-1 --q "<낱말>"
kill $(cat /tmp/mcp.pid)
```

### B-10. 정리
```bash
rm -rf $O                                    # 원본 사본이 들어 있음
```

---

## C. 벌끼리 간섭 없이 일하기

컨테이너는 자기 벌 폴더(`/app` · `/root`)와 원본 문서(읽기 전용)만 본다 — 다른 벌 폴더는 컨테이너 안에서 보이지 않는다. 간섭은 대개 git 쪽에서 생긴다.

1. **출시 전 시험 폴더(`data_pipeline/app`)에서는 커밋하지 않는다.** 그 폴더는 시험할 판 그대로 둔다.
2. **벌마다 자기 `feature/*` 브랜치에서만 일한다.** `develop`·`main`에 직접 커밋·push하지 않는다.
3. **커밋 전에 바뀐 파일을 본다 — 내가 고친 파일만 올린다.**
   ```bash
   git status && git diff --stat
   git add <파일> <파일>          # git add -A · git add . · git commit -a 는 쓰지 않는다
   ```
4. **opencode는 `/app`에서 시작한다.** 그 밖의 폴더를 고치려 하면 묻는다. 커밋·push·되돌리기·지우기·포맷·docker·다른 컨테이너 접속(ssh·scp·nc 등)도 먼저 묻는다(`opencode.jsonc`).
5. **저장소 전체 포맷(`ruff format .` 등)을 돌리지 않는다.** 고친 파일만 `bash deploy/release/lint_changed.sh`로 본다.

"파일이 전부 바뀌었다"고 나올 때:
```bash
git diff --summary | grep -c "mode change"      # 실행 권한 비트만 바뀐 파일 수
git diff --ignore-cr-at-eol --stat              # 줄바꿈(CRLF)만 다른 파일을 빼고 본 변경
git config core.fileMode false                  # 권한 비트 차이를 무시(벌마다 한 번)
```
권한 비트·줄바꿈만 바뀐 파일은 `git checkout -- <파일>`로 되돌린다.

---

## D. 출시 전 시험(운영 묶음 — 문서 100건 안팎)

운영 서버와 같은 컨테이너 3개를 개발 서버의 `data_pipeline/{app,home}`에 띄워 본다. 순서는 [prd.md](prd.md)와 같고 다른 점만 적는다.

1. 시험한 벌에서 굽는다(prd.md 1): `cd $S/data_pipeline-<n>/app && bash deploy/release/bake_prod_image.sh <실행 이미지 판>`
2. 굽기 결과의 코드 묶음(`/var/tmp/bake/code-<VERSION>-<커밋>.tar.gz`)을 `data_pipeline/app`에 푼다(prd.md 판 올리기 U-3 — `P=$S/data_pipeline B=$P/app`, U-3의 `$S/code-…` 자리에 이 묶음).
3. 운영 반영 스크립트로 올린다(처음이면 `--dim <임베딩 차원>`):
   ```bash
   cd $S/data_pipeline/app && bash deploy/release/promote.sh <VERSION> /var/tmp/bake/sbl_images
   ```
   기대 마지막 줄: `[promote] 통과 — <VERSION>`. 처음이면 그다음 `bash deploy/host/scripts/pipe_exec.sh migrate master load`.
4. 문서 100건 안팎을 끝까지:
   ```bash
   nohup python3 deploy/host/scripts/run_pipeline.py --limit 0 --skip-done --max-docs 100 > run_100.out 2>&1 &
   tail -f deploy/host/scripts/test_space/batch_progress/progress.log
   ```
   끝 줄의 실패 수·DLQ dead 수를 보고, 실패 문서는 `doc_<번호>.log`로 원인을 찾는다.
5. 검색 MCP 확인:
   ```bash
   curl -s http://<서버 IP>:8051/health                           # 기대: {"ok":true,"ready":true,…}
   docker exec mcp-server python -m mcp_server.cli.mcp_smoke --source <원천> --q "<낱말>"   # 주소·토큰은 settings.yaml(ssh에 명령을 붙이면 로그인 셸이 아니라 설정 자리를 못 봄)
   ```
6. 통과하면 같은 이미지 조각·코드 묶음을 운영 서버로 옮긴다(prd.md 2부터).
