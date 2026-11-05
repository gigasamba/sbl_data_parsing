# 0.2.0 배포 — 사람이 할 일(기록)

0.1.0 운영 서버를 0.2.0으로 올릴 때 쓴 절차와 설정 변경 목록이다. 지난 기록으로만 둔다 — 지금 판을 올리는 법은 [upgrade-guide.md](../operations/upgrade-guide.md).

**실제로 칠 명령은 8-3**, 되돌리기는 8-5. 항목별 근거·상태는 [refactor.md](../refactoring/refactor.md)의 C 표다. 값·비밀은 이 문서에 쓰지 않는다. 누가: 사용자 · 서버 운영 · DB 담당(공유 PostgreSQL) · EDW 담당(회사 DB) · devops(빌드·반입).

## 8-1. 꼭 알 것

- 운영 서버는 지금 0.1.0(settings.yaml 하나, 상주 컨테이너 `data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)이다. 0.2.0은 상주 컨테이너가 `data-pipeline`·`mcp-data-parsing`·`mcp-server`다.
- 0.2.0은 **새 실행 이미지가 필요 없다** — 코드의 `deploy/docker/DEPS_HASH`가 0.1.0 실행 이미지와 같다(`f0fcc30bd067bc2f`). dev는 `*-runtime:0.1.0`에 0.2.0 코드 폴더, prd는 그것을 구운 `*:0.2.0`.
- **prd는 반드시 새 `required.pg.pg_schema`**(판 0002가 기준 스키마의 옛 표를 지움 — C-74). 옛 스키마·옛 `struct` 스키마는 2주 뒤 DB 담당이 백업하고 지운다.
- 지문이 모두 바뀌므로(FINGERPRINT·레이어 code_fp·엔진 — 기준값 PRD [e2-02](../prd/test.md#e2-02)) 모든 문서가 다시 파싱·적재된다. **전체 문서 실행은 prd에서만**, dev는 settings.yaml이 가리키는 대상으로 e2e 한 번. 시간은 지난 `progress.log`의 문서당 시간 × 문서 수, 디스크는 `ops.host.host_output_dir`의 `parse/_rep`만큼 여유를 더 잡는다.
- 0.2.0은 **새 루트**에 놓는다 — 0.1.0 자리(코드 폴더·설정 폴더)는 그대로 두고 되돌리기에 쓴다. 검색 DB는 같은 PG다.
- prd 이미지에는 settings.yaml을 굽지 않는다 — dev처럼 `<루트>/settings.yaml`을 붙인다.
- 모델: dev·prd는 내부망 모델만(외부 모델 호출 거부).
- 원천별 하위 폴더 모양(`<원천>/<id>/<파일>`)의 폴더 원천(`required.source.input_source`가 폴더)은 맨 위에 둔 `*.md`를 원본으로 읽지 않는다(설명 파일로 보고 모양 판정에서도 뺌 — 예전에는 맨 위 파일 하나로 평평한 폴더로 읽었다). 그 자리에 파싱할 `.md` 문서가 있으면 원천 하위 폴더로 옮긴다.

## 8-2. 배포 전

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 판 전체 grill-me 검토 — 지문 전후(PRD [e2-02](../prd/test.md#e2-02))·DB 스키마(판 0002~0005·ParsingMeta DDL) | 사용자 | 등급 A |
| 2 | ParsingMeta DDL 한 번 — 칸 이름 바꾸기·`loaded_at`·판 칸 등(운영 분류 스크립트가 멈추므로 운영 담당에게 알림) | DB 담당·EDW 담당 | C-76 |
| 3 | PG — 새 `db_schema` 이름(50자 이하) · 권한(DB 수준 CREATE, 원천 스키마 5벌의 읽기·쓰기, `doc_id_seq`) | DB 담당 | C-74 |
| 4 | 서버 settings.yaml 준비 — 필수 경로·접속([README 꼭 채울 값](../../README.md#꼭-채울-값)) · EDW 읽기·쓰기 계정 · `required.tokens.fulltext_sign_key` · 예전에 `-e`로 주던 값은 settings.yaml 칸으로([8-6](#8-6-010--020에서-바꿀-설정)) · 새벽 배치 칸은 비워 둠 | 서버 운영 | C-70·C-73·C-75·C-76 |
| 5 | 노출됐던 운영 키 교체(아직 안 했으면) — 새 값은 settings.yaml에만 | 서버 운영 | C-10 |
| 6 | 서버 `/tmp` 정리 주기·권한 600 점검(덮기 설정 임시 파일) | 사용자·서버 운영 | C-46 |
| 7 | 폐쇄망 휠·`assets/` 채우고 빌드(release-and-patch §5-6 — `ALLOW_NO_ASSETS=1` 금지) | devops | — |
| 8 | `server-changes.md`를 읽고 새 코드에 들어 있는지 대조(release-and-patch §2) | 서버 운영·개발자 | — |
| 9 | EDW 표 설명 자료 폴더(`catalog.json`·`columns.jsonl` — 개인정보 없는 자료)를 루트 아래 결과 폴더 `<루트>/output/edw_meta/`에 복사(UID 10001이 읽게)하고 settings.yaml에 `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`. 없으면 `edw_meta` 도구만 `not_configured`(README §5-0 4) | 서버 운영 | C-91 |
| 10 | settings.yaml 칸 정리 — 지운 칸은 지우고, `search.server.fulltext_secret` 값은 `required.tokens.fulltext_sign_key`로, 토큰은 `required.tokens.mcp_token` 하나로 옮기고, `required.edw.edw_local_sqlite_file` 줄을 지우고(가짜 EDW는 PC 전용 — 남으면 시작 거부), 칸 이름을 새 이름으로 바꾼다(대응표 refactor.md C-95 — 옛 이름·지운 칸이 남으면 시작 거부) | 서버 운영 | C-92·C-95 |
| 11 | FAQ 교체 기록 옮기기 — 첫 `run_pipeline.py` 실행 전에 옛 `<작업 폴더>/batch_progress/faq_seen.txt`가 있으면 `<결과 폴더>/_faq_seen.txt`로 복사하고 UID 10001이 읽고 쓰게 한다(`cp -p <옛 파일> <결과 폴더>/_faq_seen.txt && chown 10001 <결과 폴더>/_faq_seen.txt`). 안 옮기면 첫 실행이 gold `faq`를 한 번 통째로 교체한다 | 서버 운영 | C-95 ⑨ |

## 8-3. 실행 순서 — 복사해 붙이는 명령(dev 먼저, 그다음 prd)

개발 서버(dev)에서 끝까지 한 번 돌린 뒤 운영 서버(prd)에서 같은 순서로 한다. 다른 곳은 **[dev]**·**[prd]**로 적었다. 명령은 root 셸. `<…>`는 그 서버 값으로 바꾸고, 값·비밀은 화면·기록에 남기지 않는다. `# 기대:` 줄이 나오지 않으면 다음 단계로 가지 않는다.

**0. 셸 준비** — 셸 변수는 settings.yaml에서 옮겨 적는다(파일을 화면에 띄우지 않는다).
```bash
export DOCKER=podman                                       # ops.host.container_cli 값(비우면 podman)
OLD_SF=<0.1.0이 쓰는 settings.yaml 경로>  OLD_CODE=<0.1.0 코드 폴더>  ROOT=<새 루트 — 예 /home/sbl/dev>
PG_C=<required.deploy.pg_container_name 값>  PG_U=<required.pg.pg_user 값>  PG_D=<required.pg.pg_database 값>
OLD_SCHEMA=<지금 required.pg.pg_schema 값>  NEW_SCHEMA=<새 스키마 이름 — DB 담당과 정함(C-74)>
mkdir -p "$ROOT" && TS=$(date +%Y%m%d-%H%M); BK=$ROOT/backup/0.2.0-$TS; mkdir -p "$BK" && chmod 700 "$ROOT/backup" "$BK"
```

**1. 멈추기** — 타이머를 멈추고, 도는 `run_pipeline.py`가 끝나길 기다린 뒤(죽이지 않는다) 옛 상주 컨테이너를 멈춘다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
systemctl is-active data-pipeline-nightly.timer mcp-server-keepalive.timer   # 기대: inactive 두 줄
pgrep -af run_pipeline.py                                                         # 기대: 아무것도 안 나옴(나오면 끝날 때까지 기다림)
$DOCKER stop data-pipeline-parse data-pipeline-structure mcp-server          # 기대: 이름 세 줄
```

**2. 백업** — 0.1.0 코드 폴더·설정 파일·옛 이미지는 지우지 않는다(되돌리기 — 8-5).
```bash
cp -p "$OLD_SF" "$BK/settings.yaml.0.1.0"                                    # 4단계 입력
$DOCKER images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -E 'data-pipeline|mcp-server' > "$BK/images.0.1.0"
$DOCKER exec "$PG_C" pg_dump -U "$PG_U" -d "$PG_D" -Fc -n "$OLD_SCHEMA" -n "${OLD_SCHEMA}_*" > "$BK/pg-0.1.0.dump"   # 우리 스키마만(공유 DB)
$DOCKER exec -i "$PG_C" pg_restore -l < "$BK/pg-0.1.0.dump" | head -5                 # 기대: ";" 머리 줄과 "TABLE" 목록 — 비면 덤프 실패
```
- 옛 `struct` 스키마도 백업하려면 `-n <그 스키마 이름>`을 더한다(이름은 DB 담당 확인). `pg_dump`가 암호를 물으면 DB 담당과 함께 한다.

**3. 새 판 놓기** — 새 루트에 푼다(`<코드>` = 코드 폴더 `sbl_data_parsing-0.2.0`).
- **[dev]** 0.1.0 실행 이미지 + 0.2.0 코드 zip:
```bash
cd "$ROOT" && unzip -q <코드 zip>                                         # 기대: $ROOT/<코드>/
(cd "$ROOT/.." && DOCKER=$DOCKER bash sbl_images-main/load.sh 0.1.0)    # 이미지 폴더는 루트 한 단계 위 공용 폴더 — 0.1.0 실행 이미지가 이미 있으면 건너뜀 — 기대: BUILD.txt(DEPS_HASH f0fcc30bd067bc2f)
cd "$ROOT/<코드>" && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   # 기대: "[host_ctl init] 루트: $ROOT" · output·backup · settings.yaml·edw_chain.yaml "만듦"
cat CODE_COMMIT                                                          # 기대: 그 커밋
```
- **[prd]** 개발 서버에서 굽고(release-and-patch §1-2 — 기대: `[판정] 통과` 뒤 `/var/tmp/bake/sbl_images/`) 운영 서버의 새 루트로 옮겨:
```bash
cd "$ROOT" && DOCKER=$DOCKER bash sbl_images/load.sh 0.2.0     # 기대: 조각 sha256 확인 → load → BUILD.txt
mkdir -p "$ROOT/<코드>" && tar -xzf sbl_images/0.2.0/code-0.2.0-<커밋>.tar.gz --no-same-owner -C "$ROOT/<코드>"
cd "$ROOT/<코드>" && bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   # edw_chain.yaml 사본(없으면 컨테이너가 안 뜸)
unset CODE_DIR                                                # 운영은 코드 폴더를 컨테이너에 붙이지 않는다
```
- 0.1.0이 고친 EDW 사슬 사본을 쓰고 있었다면 `cp -p <0.1.0 edw_chain.yaml> "$ROOT/edw_chain.yaml"`.

**4. 설정 옮기기** — 3단계 `init`이 놓은 새 `$ROOT/settings.yaml`(sample 사본)에 0.1.0 파일(`$BK/settings.yaml.0.1.0`)의 값을 칸마다 옮겨 적는다(옮기는 도구는 없다). 옛 자리·지운 칸·모르는 칸이 남으면 모든 명령이 시작을 거부하고 칸 이름만 알린다.
편집기로 고친다(화면에 통째로 띄우지 않는다) — 고칠 칸 목록은 [8-6](#8-6-010--020에서-바꿀-설정). 꼭:
- 이미지 칸 `required.deploy.pipeline_image`·`mcp_image` → **[dev]** `data-pipeline-runtime:0.1.0`·`mcp-server-runtime:0.1.0` · **[prd]** `data-pipeline:0.2.0`·`mcp-server:0.2.0`.
- `required.pg.pg_schema` → `$NEW_SCHEMA`.
- 새벽 배치 `ops.nightly.nightly_start_time`·`nightly_max_docs`·`nightly_stop_time`은 비워 둔다(8-4 3에서 켬).
- 칸 자리 찾기: `python -m common.config.sample --where <옛 env 이름 또는 칸>`(코드 폴더에서).
- 서버 EDW의 사슬 표·칸 이름이 기본값과 다를 때만 [release-and-patch §8](../operations/release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버).
```bash
chown 10001:<운영 그룹> "$ROOT/settings.yaml" && chmod 640 "$ROOT/settings.yaml"
bash deploy/host/scripts/load_settings.sh common.host >/dev/null && echo 설정-읽힘   # 기대: 설정-읽힘("[설정] …"이면 그 안내대로 고침)
```

**5. DB** — 파이프라인 상주 컨테이너부터 띄운다(`pipe_exec.sh`가 그 안에서 돈다).
```bash
$DOCKER rm data-pipeline-parse data-pipeline-structure mcp-server            # 기대: 이름 세 줄(1에서 멈춘 것)
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline                           # 기대: data-pipeline Started(또는 Running)
bash deploy/host/scripts/pipe_exec.sh migrate check --target all              # 새 스키마는 "표 없음(새 스키마 — up으로 만듦)", 종료 코드 1이 정상
bash deploy/host/scripts/pipe_exec.sh migrate up --target all --dim <임베딩 차원>   # 종료 코드 0 — 기대:
#   [migrate] search <NEW_SCHEMA>: 판 ['0005_search'] (끝 0005_search)
#   [migrate] applog applog: 판 ['0002_applog'] (끝 0002_applog)
#   [migrate] master <NEW_SCHEMA>_master: 판 ['0001_master'] (끝 0001_master)
#   "올린 뒤에도 차이:"가 나오면 멈추고 DB 담당과
bash deploy/host/scripts/pipe_exec.sh migrate master load                     # 기대: "[migrate] master <NEW_SCHEMA>_master: CSV로 채움 · 해시 <8자>"
bash deploy/host/scripts/pipe_exec.sh migrate check --target all              # 종료 코드 0 — 기대: 갈래마다 "  비교: 차이 없음"
```
- vector 확장이 없다고 멈추면 release-and-patch §5-5 ⓪.
- 마스터 표 행 수(git 샘플 CSV 기준, 서버 폴더 `--dir`로 넣었으면 다름): `client_master` 6 · `client_roster` 10 · `contract_master` 4 · `domain_terms` 124 · `id_patterns` 9 · `units` 23 · `master_meta` 1. 확인: `$DOCKER exec "$PG_C" psql -U "$PG_U" -d "$PG_D" -c "SELECT count(*) FROM ${NEW_SCHEMA}_master.client_roster"`.

**6. 띄우기**
```bash
bash deploy/host/scripts/host_ctl.sh up -d mcp-data-parsing mcp                   # 기대: 두 서비스 Started
bash deploy/host/scripts/host_ctl.sh ps                                             # 기대: data-pipeline·mcp-data-parsing·mcp-server 세 줄 Up
$DOCKER logs data-pipeline 2>&1 | grep -m1 '\[image\]'                        # 기대: "[image] 이미지 <이름 판 커밋> · 코드 <커밋> · 의존성 <지문>"
```

**7. 점검** — check_env → ping_models → `migrate check --target all` → 두 이미지 selftest → `mcp_keepalive.sh`(/health)를 차례로, 처음 실패에서 그 단계 이름과 안내를 찍고 멈춘다.
```bash
bash deploy/host/scripts/host_ctl.sh check                                          # 기대 마지막 줄: [host_ctl check] 통과 — 6개
```
- 실패하면(`[host_ctl check] 실패 — <단계>: <안내>`) 그 단계 출력을 읽고 고친 뒤 다시 부른다. check_env 출력은 PG 실패를 "건너뜀"으로 보일 수 있다.
- 그다음 MCP 클라이언트로 `search` 한 번(`source_system` 필수), `list_doc_fulltext` 한 번, `parse_document`에 시험 파일 하나(C-75·C-83).
- 타이머를 새 루트로: `bash deploy/host/scripts/host_ctl.sh timers` 뒤 `systemctl stop mcp-server-keepalive.timer data-pipeline-nightly.timer`(첫 실행이 끝날 때까지 — 9).

**8. [dev] 게시 확인 — 미리보기 → 실제 한 번 → Object Storage·EDW 행**(운영 Object Storage·EDW에 쓰는 첫 실행이라 dev에서 몇 건으로 먼저 본다)
```bash
bash deploy/host/scripts/pipe_exec.sh parse --source-limit 3                   # 원본 3건만 파싱 → <결과 폴더>/parse/_rep · 기대: 종료 코드 0
bash deploy/host/scripts/pipe_exec.sh publish --dry-run                        # 쓰기 0 — 기대: JSON 한 줄("mode": "dry-run" · bucket · prefix · rows_planned · upload_plan · sample_rows[].rep_key) + "[dry-run] 쓰기 0 …"
bash deploy/host/scripts/pipe_exec.sh publish                                  # 실제 한 번 — 기대: JSON 한 줄("mode": "apply" · "result") · 종료 코드 0
```
- **실제 publish는 한 번만** 한다. 다시 돌리면 Object Storage에 같은 결과를 새 시각 이름으로 또 올린다(EDW는 이미 있는 행을 건너뜀).
- 미리보기의 `bucket`·`prefix`·`rep_key`가 `required.publish` 칸(`publish_bucket`·`publish_prefix`)과 맞지 않으면 실제 publish를 하지 않고 settings.yaml을 고친다. DRM·실패로 빠진 문서는 `<결과 폴더>/publish/excluded_<날짜>.md`에 남는다.
- EDW 행 확인(읽기 계정 — 마지막에 쓴 행):
```bash
$DOCKER exec data-pipeline python -c "from common.store import mssql as M; kw,_=M.login('read'); c=M.connect(**kw); [print(r) for r in M.rows(c, 'SELECT TOP 5 original_filename, parse_status, rep_bucket, rep_key, parse_date FROM AI.ParsingMeta ORDER BY parse_meta_id DESC')]"
# 기대: 방금 게시한 문서 수만큼 행 · parse_status ok·partial · rep_key가 미리보기의 rep_key와 같음(표 이름이 다르면 required.edw.parsing_meta_table 값)
```
- Object Storage 확인(위 행의 `rep_bucket`·`rep_key` 하나로):
```bash
$DOCKER exec data-pipeline python -c "import sys; from common.store.objectstore import client; r=client().list_objects_v2(Bucket=sys.argv[1], Prefix=sys.argv[2]); [print(o['Key'], o['Size']) for o in r.get('Contents', [])]" <rep_bucket> <rep_key>
# 기대: <파일명>_<parse_date>.md · .json · _meta.json 과 engine/ 아래 파일 — 없으면 멈추고 publish 출력의 "result"를 본다
```

**9. 첫 실행 — FAQ 교체와 전체 재처리**
- **FAQ:** 첫 `run_pipeline.py` 실행은 FAQ 교체 기록(`<결과 폴더>/_faq_seen.txt`)이 없으므로 gold `faq`를 **한 번** 비운 뒤 FAQ 전체를 맨 앞에서 처리한다. `progress.log` 기대 줄: `FAQ 교체: 새 FAQ <N>건 — gold faq 문서 <M>건을 지우고 지금 FAQ <K>건 전체를 맨 앞에서 다시 처리`(새 스키마라 M=0). `--seqs`·`--limit` 실행은 교체를 건너뛴다.
- **[dev]** settings.yaml이 가리키는 대상으로 e2e 한 번(`--limit <N>`). **[prd]** 전체 문서를 새 스키마로:
```bash
cd "$ROOT/<코드>"
nohup python3 deploy/host/scripts/run_pipeline.py --start-offset 0 > "$ROOT/run_pipeline.0.2.0.out" 2>&1 &
tail -f <작업 폴더>/batch_progress/progress.log                               # 기대: 처음에 FAQ 교체 줄, 그다음 문서마다 "doc#<seq> …" 줄
```
- 이 전체 실행에는 `--skip-done`을 주지 않는다 — ParsingMeta에 `gold_version` 칸이 생기기 전(C-76)에는 0.1.0이 끝낸 문서를 "끝남"으로 보고 건너뛴다.
- 끝나면(종료 코드 0, 실패가 있으면 1 — [server-guide §2](../operations/server-guide.md#2-일상-실행--run_pipeline문서별-흐름)) `systemctl start mcp-server-keepalive.timer`(새벽 배치는 8-4 3).

## 8-4. 배포 뒤

| # | 할 일 | 누가 | C |
|---|---|---|---|
| 1 | 적재 기록 — 실행 기록의 `meta_missing`·`loaded_at_failed`가 0인지, ParsingMeta에 판·적재 시각이 채워지는지 | 서버 운영 | C-76 |
| 2 | 적재가 지우지 않는지 · 상주 컨테이너 `/tmp` · 좀비 프로세스 | 서버 운영 | C-68 |
| 3 | 새벽 배치 — `ops.nightly.nightly_start_time`·`nightly_max_docs`·`nightly_stop_time`을 모두 채울 때만 켬(마감은 시작보다 5분 넘게 뒤) → `systemctl start data-pipeline-nightly.timer` → `journalctl -u data-pipeline-nightly` | 서버 운영 | C-72 |
| 4 | 2주 뒤 옛 검색 스키마·옛 `struct` 스키마를 백업한 뒤 지움 | DB 담당 | C-74 |
| 5 | `versions.md`에 한 줄 · 되돌리기가 필요 없어진 뒤 `prune_images.sh --apply` | 서버 운영·devops | release-and-patch §6 |
| 6 | `query_edw` — 실제 업무 SELECT 몇 개(JOIN·`WITH`·대괄호 이름·한글 별칭·`TOP`)를 부른다. 기대: 행이 오거나 행·시간 상한 안내만. 정상 SELECT가 `rejected:*`로 거부되면 SQL과 오류 코드를 `issues.md`에 | 서버 운영 | — |
| 7 | `edw_meta` — 서버 카탈로그(`search.edw_meta.edw_meta_catalog_dir`의 `catalog.json`)에서 이름 끝에 공백이 있는 표를, 그 이름 그대로와 공백을 뺀 이름으로 각각 부른다. 기대: 둘 다 같은 표의 칸 목록 | 서버 운영 | — |
| 8 | 로그 DB — `search` 한 번 뒤 `applog.mcp_log`에 그 호출 한 행(`args`에 질문), `<루트>/output/logs/`가 비어 있음(있으면 DB 쓰기 실패 — 파일 안 오류 확인) | 서버 운영 | C-79 |

## 8-5. 되돌리기(0.2.0 → 0.1.0)

새 `db_schema`를 썼으므로 옛 스키마는 그대로 남아 있다 — 보통 DB는 되돌릴 것이 없다.
```bash
systemctl stop data-pipeline-nightly.timer mcp-server-keepalive.timer
cd "$ROOT/<코드>" && bash deploy/host/scripts/host_ctl.sh down                     # 0.2.0 컨테이너 셋 내림
```
- 0.1.0 자리(`$OLD_CODE`·`$OLD_SF`)는 그대로 남아 있다. 0.1.0 컨테이너(`data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`)와 0.1.0 타이머는 `$OLD_CODE`의 README §5-3·§5-5 방법으로 다시 띄우고, 시작 로그 첫 줄로 0.1.0인지 본다.
- 옛 스키마를 0.2.0이 바꿨다면(새 이름을 안 썼을 때만) 백업으로: `$DOCKER exec -i "$PG_C" pg_restore -U "$PG_U" -d "$PG_D" --clean < "$BK/pg-0.1.0.dump"`(DB 담당과 같이 — downgrade 명령은 없다).
- ParsingMeta에 0.2.0이 쓴 행·`gold_version`은 그대로 남는다(0.1.0은 그 칸을 읽지 않음).

## 8-6. 0.1.0 → 0.2.0에서 바꿀 설정

운영 서버(0.1.0)를 0.2.0으로 올릴 때 settings.yaml에서 할 일이다. 순서는 [8-3 4](#8-3-실행-순서--복사해-붙이는-명령dev-먼저-그다음-prd).

| 바뀐 것 | 할 일 |
|---|---|
| 칸 배치 — 맨 위 `required` → 역할 절 → `tuning`. 옛 배치·옛 자리·지운 칸·모르는 칸은 시작 거부(칸 이름만 알림) | `init`이 놓은 새 settings.yaml에 옛 값을 칸마다 옮겨 적는다(§8-3 4) |
| `required.pg` 접속 다섯 칸 필수(자동 탐지 없음) | 모두 채운다. `pg_schema`는 비우면 `data_parsing` — 운영은 **새 이름**(판 0002가 옛 표를 지움) |
| env로 준 값은 효과 없음(엔진·핸드오프 칸 포함) | 컨테이너에 `-e VLM_BASE_URL=…`·`OCR_DPI=…`처럼 주던 값은 settings.yaml 칸으로(`--where <이름>`으로 자리 확인) |
| 이미지 칸 `required.deploy.pipeline_image`·`mcp_image` | dev `data-pipeline-runtime:0.1.0`·`mcp-server-runtime:0.1.0` · prd `data-pipeline:0.2.0`·`mcp-server:0.2.0` |
| 새 칸 `required.deploy.pg_container_name`·`required.tokens.fulltext_sign_key` · 토큰은 `required.tokens.mcp_token` 하나(작업 서비스도 같은 값) | 채운다(README [꼭 채울 값](../../README.md#꼭-채울-값)) |
| 새벽 배치 `ops.nightly.nightly_start_time`·`nightly_max_docs`·`nightly_stop_time` — 셋 다 있어야 돎 | 배포 때는 비워 두고 배포 뒤 켠다(§8-4 3) |
| 거의 안 바꾸는 칸 53개가 `tuning` 절로(청크·순위 가중치·그림 고르기·로그 대기열·EDW 원천 열 이름 등) | 값을 적어 둔 칸만 `tuning.<옛 자리>`로 옮긴다(옛 자리는 시작 거부 — C-95) |
| 합친 칸 `extract.prefetch_workers` → `extract.source.source_fetch_threads` · `tuning.ops.nightly_run.workers` → `ops.runtime.vlm_parallel_docs` | 옛 칸 값을 새 칸에 적고 옛 칸은 지운다(남으면 시작 거부) |
| `parse_document` 크기 상한 칸이 `ops.services.data_parsing.mcp_parse_max_file_mb`(기본 100) | 옛 `ops.services.data_parsing.max_mb`가 있으면 지우고, 100이 아닌 값은 새 칸에. 리버스 프록시 본문 상한도 늘린다(C-85) |
| `query_edw` 행 상한 기본 1000(`search.edw_query.edw_query_max_rows`) | 다른 값을 쓰려면 적는다 |
| 용어집·고객 명부는 PG 마스터 표 | `migrate master load`(§8-3 5) · CSV를 고치면 다시 하고 검색 MCP 재시작 |
| 사슬 파일 칸 `ops.paths.edw_chain_file`(새 — 비우면 기본 파일) | 서버 EDW 이름이 다를 때만 release-and-patch §8 |
| 지운 칸(예 `ops.paths.glossary_dir`·`client_roster`·`mcp_bundle`, `common.models.transport.transport`, `required.env.run_mode`, `search.server.warmup`, `required.tokens.data_parsing`·`parse_proxy`, `ops.mcp_host.jobs_dir` — C-95) | 지운다 — 남으면 시작 거부(칸 이름만 알림) |
| run_pipeline이 `--set`으로 넘기던 값(VLM 동시 수·후처리 목록·CPU 문턱·임베딩 동시 수 등) → `ops.run_pipeline.*` | 비우면 지금 값 그대로 — 바꿀 때만 적는다 |
