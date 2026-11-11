# 운영 서버(prd) 실행 순서

운영 폴더는 `/home/sbl/data_pipeline/{app,home}` 한 벌이다. 코드는 구운 이미지 안에 있고, 컨테이너에는 `app/settings.yaml`(읽기 전용)·`app/output/`·`home/`만 붙는다. `app/`의 나머지(코드 묶음)는 호스트 스크립트(compose·`host_ctl.sh`·`run_pipeline.py`·타이머)용이다.

| 컨테이너 | 하는 일 | 붙는 폴더 |
|---|---|---|
| `data-pipeline`(SSH 8020) | 파이프라인 — `run_pipeline.py`·`pipe_exec.sh`가 이 안에서 돈다 | `app/output` → `/app/output` · `home` → `/root` |
| `mcp-server`(SSH 8050 · HTTP 8051) | 검색 MCP | `app/output`(읽기 전용 · `_mcp_parse/jobs`만 쓰기) · `home/mcp` → `/root` |
| `mcp-data-parsing` | parse_document 작업 | `app/output` |

compose 묶음 이름은 `sbl-prd`(`deploy/host/compose/compose-prd.yml`). 개발 서버의 출시 전 시험([dev.md D](dev.md#d-출시-전-시험운영-묶음--문서-100건-안팎))도 같은 순서다. 설정 칸은 [settings.md](settings.md).

```bash
export DOCKER=docker; S=/home/sbl; P=$S/data_pipeline; B=$P/app
```

## 1. 굽기(개발 서버에서 — 시험한 벌 코드 + 실행 이미지 → 코드가 든 이미지)
```bash
cd <시험한 벌의 app 폴더> && bash deploy/release/bake_prod_image.sh <실행 이미지 판>
ls /var/tmp/bake/sbl_images/<VERSION>/                      # 조각 · load.sh · BUILD.txt
ls /var/tmp/bake/code-<VERSION>-*.tar.gz                    # 코드 묶음
```

## 2. 옮기기
`/var/tmp/bake/sbl_images`와 코드 묶음을 운영 서버 `$S`로 옮긴다.

## 3. 운영 폴더(처음)
```bash
mkdir -p $B $P/home && tar -xzf $S/code-<VERSION>-<커밋>.tar.gz --no-same-owner -C $B
cd $B && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
```
SSH를 쓰면 개발 홈 묶음을 `$P/home`과 `$P/home/mcp`에 푼다([dev.md A-3](dev.md#a-3-개발-홈-묶음-풀기컨테이너-띄우기-전)).

## 4. 설정 채우기
`$B/settings.yaml`의 빈 칸을 채운다(`required.env.run_env: prd` — 컨테이너 이름 칸 `ops.host.*_container`는 비워 둠). 확인:
```bash
bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK
```

## 5. PG·Redis(처음)
```bash
vi .env && chmod 600 .env       # PG_USER · PG_DB · PG_PASSWORD · REDIS_PASSWORD — settings.yaml과 같은 값
mkdir -p /data/pg/pipeline /data/redis
docker compose --env-file .env -f deploy/host/compose/compose-pgvector.yml up -d   # DB 담당이 따로 둔 PG면 건너뜀
docker compose --env-file .env -f deploy/host/compose/compose-redis.yml up -d
until docker exec pgvector pg_isready -h 127.0.0.1 -U <계정> -d <DB>; do sleep 1; done
docker exec pgvector psql -U <계정> -d <DB> -c 'CREATE EXTENSION IF NOT EXISTS vector'
```

## 6. 운영 반영 — promote.sh
명령 한 줄씩 차례로 찍고 돌리며, 처음 실패에서 멈춘다.

| 단계 | 명령 |
|---|---|
| ① 이미지 불러오기 | `bash <이미지 저장소>/load.sh <VERSION>` |
| ② 폴더 준비 | `mkdir -p app/output/_mcp_parse/jobs home/mcp` |
| ③ DB 판 올리기 | `docker run --rm --network host … data-pipeline:<VERSION> migrate up --target all [인자…]` |
| ④ 컨테이너 3개 띄우기 | `host_ctl.sh up -d --force-recreate` |
| ⑤ 배포 뒤 점검 | `host_ctl.sh check` — .env 일치 · check_env · ping_models · migrate check · 두 이미지 selftest · 검색 MCP /health |

```bash
cd $B && bash deploy/release/promote.sh <VERSION> $S/sbl_images --dim <임베딩 차원>   # --dim은 처음만
```
기대 마지막 줄: `[promote] 통과 — <VERSION>`. 처음이면 이어서:
```bash
bash deploy/host/scripts/pipe_exec.sh migrate master load
curl -s http://<서버 IP>:8051/health                        # 기대: {"ok":true,"ready":true,…}
bash deploy/host/scripts/pipe_exec.sh publish --dry-run     # 게시 미리 보기 — 쓰기 0
```
DB 담당이 먼저 SQL을 보려면 ③ 전에: `docker run --rm --network host -v $B/settings.yaml:/etc/rag/settings.yaml:ro,z -v $B/output:/app/output:z -e SETTINGS_FILE=/etc/rag/settings.yaml -e RUN_ENV=prd data-pipeline:<VERSION> migrate up --target all --dim <차원> --sql /app/output/up.sql`.

## 7. 한 번에 돌리기 — run_pipeline.py
```bash
nohup python3 deploy/host/scripts/run_pipeline.py --limit 2 > run_first.out 2>&1 &
tail -f deploy/host/scripts/test_space/batch_progress/progress.log   # 기대 끝 줄: === 문서별 flow 끝: … 종료 코드 0 ===
```
인자·종료 코드·실패 문서(DLQ) 다루기는 [dev.md A-10](dev.md#a-10-한-번에-돌리기--run_pipelinepyedw-목록--받기--파싱--게시--구조화적재)과 같다(컨테이너 이름만 `data-pipeline`). 단계 하나씩은 `pipe_exec.sh`([dev.md A-11](dev.md#a-11-단계-하나씩--pipe_execsh)).

## 8. 자동 실행 타이머
```bash
bash deploy/host/scripts/host_ctl.sh timers
systemctl list-timers 'data-pipeline-nightly*' 'mcp-server-keepalive*'
systemctl is-enabled docker                                 # 기대: enabled(재부팅 때 컨테이너를 다시 띄움)
```
- `data-pipeline-nightly` — 5분마다 깨어 `nightly_batch.sh scheduled`를 부른다. `ops.nightly.*` 세 칸(시작 시각·문서 수 상한·마감)이 모두 있고 지금이 시작 시각부터 5분 안일 때만 `run_pipeline.py --skip-done --max-docs … --deadline …`을 돌린다.
- `mcp-server-keepalive` — 2분마다 `mcp_keepalive.sh`: Redis·`mcp-data-parsing`·`mcp-server`가 꺼졌으면 띄우고, `/health` 응답이 없으면 다시 띄운다. 손으로도 부를 수 있다(여러 번 불러도 안전).

## 9. 이미지 정리(손으로, 가끔)
```bash
bash deploy/host/scripts/prune_images.sh                    # 지울 목록만 보기
bash deploy/host/scripts/prune_images.sh --apply            # 최신 ops.host.prune_keep_versions개(기본 2)만 남김
```

---

## 판 올리기

### U-1. 멈추기·백업
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
pgrep -af run_pipeline.py                                   # 기대: 없음(있으면 끝날 때까지 기다림)
BK=<백업 폴더>/$(cat $B/VERSION)-$(date +%Y%m%d-%H%M); mkdir -p "$BK" && chmod 700 "$BK"
tar -czf "$BK/code.tar.gz" --exclude=./output -C "$B" .
docker exec pgvector pg_dump -U <계정> -d <DB> -Fc -n <스키마> -n '<스키마>_*' -n applog > "$BK/pg.dump"
docker exec -i pgvector pg_restore -l < "$BK/pg.dump" | grep -c ' TABLE '   # 기대: 0보다 큰 수
```

### U-2. 새 굽기 결과 옮기기
1·2를 새 판으로.

### U-3. 운영 app 덮어쓰기(설정·결과·.env·진행 기록은 그대로)
```bash
T=deploy/host/scripts/test_space
{ [ ! -d "$B/$T" ] || mv "$B/$T" "$P/test_space.keep"; } &&
  find "$B" -mindepth 1 -maxdepth 1 ! -name output ! -name "settings*" ! -name .env -exec rm -rf {} + &&
  tar -xzf $S/code-<새 VERSION>-<커밋>.tar.gz --no-same-owner -C "$B" &&
  { [ ! -d "$P/test_space.keep" ] || mv "$P/test_space.keep" "$B/$T"; }
cd $B && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>
```

### U-4. 설정 맞추기
새 `settings.sample.yaml`과 대조해 칸을 더하거나 지운다 → `bash deploy/host/scripts/host_ctl.sh config --quiet && echo 설정 OK`.

### U-5. 운영 반영·타이머
```bash
bash deploy/release/promote.sh <새 VERSION> $S/sbl_images
bash deploy/host/scripts/host_ctl.sh logs data-pipeline 2>&1 | grep -m1 '^\[image\]'   # 새 판 커밋
bash deploy/host/scripts/host_ctl.sh timers
```

---

## 되돌리기

### R-1. 코드·설정
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
cd $B && bash deploy/host/scripts/host_ctl.sh down
mv "$B" "$B.new" && mkdir "$B" && tar -xzf "$BK/code.tar.gz" -C "$B" && mv "$B.new/output" "$B/"
cd $B && IMAGE_TAG=<앞 VERSION> bash deploy/host/scripts/host_ctl.sh up -d --force-recreate
bash deploy/host/scripts/host_ctl.sh check && bash deploy/host/scripts/host_ctl.sh timers
```
`$B.new`는 확인 뒤 지운다.

### R-2. DB(새 판이 DB 판을 올렸을 때 — DB 담당과 함께)
```bash
SC=<판이 바뀐 스키마>
docker exec pgvector psql -U <계정> -d <DB> -c "ALTER SCHEMA $SC RENAME TO ${SC}_rollback_$(date +%m%d)"
docker exec pgvector psql -U <계정> -d <DB> -c "CREATE SCHEMA $SC"
docker exec -i pgvector pg_restore -U <계정> -d <DB> -n "$SC" < "$BK/pg.dump"
bash deploy/host/scripts/pipe_exec.sh migrate check --target all
```
