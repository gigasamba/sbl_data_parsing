# 서버 가이드 — 수집 서버 · 개발 서버

대상: 서버 운영자. 설치 순서는 [README §5-0](../../README.md#서버-설치-순서) 하나다. 설정 칸: [env-guide.md](env-guide.md) · 운영 중인 서버를 새 판으로: [upgrade-guide.md](upgrade-guide.md) · 이미지·코드 폴더·굽기: [release-and-patch.md](release-and-patch.md).

## 0. 이미지 2개와 명령

| 이미지 | 역할 | `RAG_MODULE` | 상주 컨테이너(`deploy/host/compose/`) |
|---|---|---|---|
| `data-pipeline` | 파싱·게시·구조화·적재 | `pipeline` | `data-pipeline`(`compose.pipeline.yml` — 일 없이 떠 있음) · `mcp-data-parsing`(`compose.data-parsing.yml` — `parse_document` 작업 서비스) |
| `mcp-server` | 검색 MCP | `mcp` | `mcp-server`(서비스 이름 `mcp` — `compose.mcp-server.yml`) |

- 이미지 시작 스크립트(`entrypoint.sh`)는 다른 이미지의 명령을 종료 64로 거부한다(맞는 이미지를 알려 줌). data-pipeline: `parse`·`publish`·`show-stack`·`idle`·`migrate`·`run-mcp-parsing` · mcp-server: `mcp`·`ask`·`show-stack`.
- 어느 이미지에서나: `help`·`check`·`resources`·`services`·`check-modules`·`tool <이름> [인자]`·`selftest`.
- 서버 배치: 공용 폴더(예 `/home/sbl/`) 아래 이미지 폴더 `sbl_images-main/`(서버에 한 번 load — 모든 벌이 같이 씀)·공용 `opencode.json`(선택)과 벌 폴더(한 벌 = 코드 폴더 하나 — 예 `sbl_data_parsing-main-1/`). 루트 = 코드 폴더 자체 — 그 안에 `settings.yaml`·`edw_chain.yaml`·결과 폴더 `output/`(+ SSH 작업 공간을 켜면 `home/`). 호스트 스크립트가 자기 자리에서 구한다(README §5). 새 판은 벌 폴더에 덮어쓴다([release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--코드-폴더-덮어쓰기)).
- 개발 서버는 실행 이미지(`*-runtime`)에 코드 폴더를 `/app/deploy`에 읽기 전용으로 붙인다 — `host_ctl.sh`·`mcp_keepalive.sh`가 자기 코드 폴더를 `CODE_DIR`로 잡는다(셸에 `CODE_DIR`가 있으면 그 값). 코드 없이·의존성 지문이 다른 코드로 띄우면 시작 거부(종료 2) — 실행 이미지 판은 `BUILD.txt`의 `DEPS_HASH`가 코드의 `deploy/docker/DEPS_HASH`와 같은 판을 쓴다. 운영 서버는 개발 서버에서 구운 코드가 든 이미지(`bake_prod_image.sh`)를 마운트 없이 쓴다. 모드(local·dev·prd)별 이미지·코드·띄우는 명령은 [README §1-3 실행 모드 표](../../README.md#실행-모드).
- 서버로 옮기기: 처음 설치(PC → 개발 서버)는 [README §5-0 서버 설치 순서](../../README.md#서버-설치-순서), 코드만 바꿀 때는 [release-and-patch §1-1](release-and-patch.md#1-1-개발-서버--코드-폴더-덮어쓰기), 개발 서버 → 운영(수집) 서버는 [release-and-patch §1-2](release-and-patch.md#1-2-개발--운영--시험한-그대로-굽기)(`bake_prod_image.sh` → `load.sh` → `host_ctl.sh`). 컨테이너는 compose를 직접 부르지 않고 `host_ctl.sh`로 다룬다.
- 명령은 모두 코드 폴더(`cd /home/sbl/sbl_data_parsing-main-<번호>`)에서, root 셸에서 실행한다.
- 컨테이너 상태: 서버 전체는 `podman ps`·`docker ps`(root로 띄웠으면 `sudo podman ps`), 우리 묶음만은 `bash deploy/host/scripts/host_ctl.sh ps`.

## 1. 설정

```bash
export DOCKER=podman                                   # 운영 계정 ~/.bashrc에 두거나 명령 앞에 붙인다
bash deploy/host/scripts/host_ctl.sh init --group <운영 그룹>   # 코드 폴더 안 output/·settings.yaml·edw_chain.yaml(없을 때만)·home/(ssh_port를 적었을 때만) — README §5-0 3번
```
- 값은 `init`이 찍은 빈 필수 칸부터 채운다(README [꼭 채울 값](../../README.md#꼭-채울-값)). `nightly_batch.sh`·`pipe_exec.sh`·`mcp_keepalive.sh`·systemd unit은 `<루트>/settings.yaml`을 스스로 찾는다.
- **엔진 구성은 코드 폴더의 파일이다**(`resources/config/pipeline_stack.json` 하나 — 설정 칸 없음). 바꾸려면 코드 폴더째 바꾼다. 원천은 폴더·`rdb:csv`만.

### 1-1. 값 바꾸기
- 앱 설정은 `settings.yaml`을 직접 고치고 `host_ctl.sh up -d --force-recreate <서비스>`.
- **한 번만 다른 값은 `--set 이름=값`** — 받는 진입점: `pipeline.cli`·`pipeline.extract.candidate_ready`·`gold_bundle`·`pgvector_load`·`publish_parse_result`. 예: `$DOCKER exec data-pipeline python -m pipeline.cli --set PIPE_PROCS=2 parse …`. 이름은 옛 env 이름(`python -m common.config.sample --where`). 모르는 이름·호스트 칸·비밀 칸은 종료 2.
- 셸·compose·`docker exec -e`로 준 옛 env 이름은 효과가 없다(시작 때 이름만 경고). 셸 env로 덮을 수 있는 것은 compose 치환 값(이미지 태그·자원·포트·호스트 경로)뿐이다.
- 오버레이 설정 파일 도구 `python -m common.config.overrides`는 PC 전용이다(서버는 종료 2).

### 1-2. 기동 확인
README §5-3 ④ 연결 점검과 ⑤ 이미지 점검, 또는 한 번에 `bash deploy/host/scripts/host_ctl.sh check`(기대 마지막 줄 `[host_ctl check] 통과 — 6개`).

### 1-3. 한 서버에 여러 벌 띄우기(개발자별)
개발 서버(dev)만. 벌 폴더(코드 폴더) 하나가 한 벌이다. 폴더 배치·명령은 [README §5-0 "한 서버에 여러 벌"](../../README.md#5-0-배포-단계와-개발-서버-설치).

| 무엇 | 정하는 곳 | 예(벌 2) |
|---|---|---|
| 벌 번호 | 코드 폴더 이름 끝 `-<숫자>`(끝이 숫자가 아니면 한 벌 — 이름 그대로) | `sbl_data_parsing-main-2` → `2` |
| `search.server.mcp_port` | 그 벌의 settings.yaml — 번호가 붙은 벌인데 기본값(8765)이면 시작 거부 | `8775` |
| `ops.services.data_parsing.data_parsing_port` | 그 벌의 settings.yaml — parse_document 작업 서비스 포트(검색 MCP도 이 값으로 부름), 번호가 붙은 벌인데 기본값(8766)이면 시작 거부 | `8776` |
| `option.devbox.ssh_port` | 그 벌의 settings.yaml — 개발 작업 공간을 켤 때만 | `2223` |

벌 번호 `2`면 저절로:
- 컨테이너·compose 묶음·systemd 단위 이름 끝에 `-2`(`data-pipeline-2`·`mcp-data-parsing-2`·`mcp-server-2`, 묶음 `compose-2`, 타이머 `data-pipeline-nightly-2.timer`).
- PG 스키마·EDW 기록 표·게시 경로에는 아무것도 붙지 않는다 — 모든 벌이 같은 기준 스키마를 함께 쓰므로 모든 벌을 같은 코드 판으로 둔다. `migrate up`·`migrate master load`는 아무 벌 하나에서 한 번.
- 운영(prd)에서 번호가 붙은 폴더면 시작 거부(종료 2 — `load_settings.sh`·`run_pipeline.py`).

- 컨테이너는 모두 호스트 네트워크라 포트가 겹치면 뒤에 띄운 쪽이 시작하지 못한다.
- 명령은 그 벌 폴더에서 `host_ctl.sh`로만 한다 — `host_ctl.sh`·`mcp_keepalive.sh`·`nightly_batch.sh`·`pipe_exec.sh`·`run_pipeline.py`가 자기 코드 폴더 이름에서 벌 번호를 구해 자기 벌의 컨테이너만 다룬다(컨테이너 명령은 셸 `DOCKER`가 `ops.host.container_cli`를 이김). compose를 직접 부르면 이름·포트 값이 채워지지 않는다.
- 자동 실행(`host_ctl.sh timers`)도 벌마다 따로 켜진다. 개발자 벌은 새벽 배치가 필요 없으면 `systemctl disable --now data-pipeline-nightly-<번호>.timer`.
- CPU·메모리 상한(§README 5-0 "자원")은 서버 전체 합계를 보고 벌마다 줄인다.

## 2. 일상 실행 — run_pipeline(문서별 흐름)

서버 입구는 `run_pipeline.py` 하나다 — 문서마다 파싱 → publish(Object Storage) → 원본 삭제 → 구조화·적재(PG — 처리 기록 포함)를 상주 컨테이너 안에서 `exec`로 돌린다. 자리·설정: [release-and-patch §5-4](release-and-patch.md#5-4-run_pipelinepy-자리와-설정).
- **대상:** 기본은 FileStorageMap의 모든 문서를 처음(`--start-offset` 기본 0)부터. 이름으로 좁힐 때만 `--filter <키워드,…>`(하나라도 들면).
- 파싱·publish·구조화가 실패하거나 시간 제한을 넘기면 그 문서의 컨테이너 안 프로세스도 끈다(다음 문서와 CPU·메모리를 다투지 않게).
- publish는 gold(PG 원천 스키마 `doc`)에 이미 끝난 문서를 Object Storage에 올리지 않는다(`--reparse` 목록만 새 날짜 폴더). 올린 문서의 처리 기록은 문서 폴더 `publish/silver.jsonl`에 쓰고, 적재가 그 값을 `doc` 칸으로 옮긴다.
- 원본(`_staging/*.bin`·그 ETag 파일 `*.etag`·`_docflow/<seq>/_source_files`)은 **publish가 성공한 뒤에만** 지운다. 파싱·publish가 실패한 문서는 원본이 남고 `batch_progress/progress.log`와 `applog.except_doc_info`(`error` 행)에 적힌다(다음 `--skip-done` 실행이 다시 고름). 구조화·적재가 실패하면 publish한 결과는 그대로이고 `doc` 행이 없으므로 다음 `--skip-done` 실행이 다시 고른다(`error` 행도 남김).
- **게시·EDW 설정**(settings.yaml `required` — 빠지면 run_pipeline이 칸 이름을 찍고 종료 2): 게시 위치 `required.publish.publish_bucket`·`publish_prefix`, Object Storage 접속 `required.object_storage.object_storage_endpoint`·`object_storage_access_key`·`object_storage_secret_key`(`object_storage_region` 비우면 `us-east-1`, `object_storage_verify_tls` 비우면 검증 켬 — 사내 CA면 CA 파일 경로), EDW 접속 `required.edw.edw_host`·`edw_database`·`edw_read_*`(`edw_port` 비우면 1433 · EDW는 읽기만 하므로 쓰기 계정 칸은 없음). `dev.local.*`(가짜 EDW 등)은 PC 전용이라 서버에서는 읽지 않는다(`local_edw_sqlite_file`은 비운다).
- **종료 코드**(PRD [pl-18](../prd/ops.md#pl-18)): `0` 대상 0건·모두 끝 · `1` 실패 문서가 하나라도 · `75` 마감(`--deadline`) 도달(실패 없음) 또는 다른 run_pipeline이 도는 중 · `2` 설정 문제. 실패와 마감이 함께면 `1`. 새벽 배치 unit은 `75`를 성공으로 친다.
- **겹침 잠금:** run_pipeline은 `batch_progress/run_pipeline.lock`을 `flock`으로 잡는다 — 새벽 배치와 사람이 직접 돌린 run_pipeline이 함께 돌지 않는다(뒤에 온 쪽이 75). 죽으면 잠금은 저절로 풀린다. 작업 폴더(`ops.run_pipeline.run_pipeline_work_dir`)가 같아야 같은 잠금이다.
- 파싱·게시만 따로:
```bash
bash deploy/host/scripts/pipe_exec.sh parse [--source-limit N]   # 파싱 → <결과 폴더>/parse/_rep. 임베딩·DB 없음
bash deploy/host/scripts/pipe_exec.sh publish --dry-run          # 무엇을 올리고 쓸지 표만(쓰기 0)
bash deploy/host/scripts/pipe_exec.sh publish                    # 대표 결과 Object Storage 업로드 + EDW 메타 — 한 번만
```
- 같은 결과 폴더에 두 작업이 겹치면 `/app/output/.pipeline.lock` 때문에 뒤쪽이 종료 75.
- 도구만 따로: `bash deploy/host/scripts/pipe_exec.sh <rdb_discover|check_env|ping_models|migrate|show-stack|check> [인자]`.
- 우선순위 낮추기(`tuning.extract.low_priority_engines` — 일괄 파싱 엔진 자식 nice +10)는 같은 세션·autogroup 안에서만 효과가 있다. 컨테이너끼리는 CPU 나눔 비율(`ops.containers.data_parsing.data_parsing_cpu_shares` 4096 대 일괄 1024)이 정한다.

### 2-1. 검색 MCP는 늘 켜 둠
`bash deploy/host/scripts/mcp_keepalive.sh` + keepalive 타이머 — README §5-5.

### 2-2. 새벽 배치
`ops.nightly.nightly_start_time`·`nightly_max_docs`·`nightly_stop_time` 세 칸 + `data-pipeline-nightly.timer` — README §5-5. 타이머는 5분마다 깨우고 `nightly_batch.sh scheduled`가 시작 시각부터 5분 안일 때만 applog 파티션 정리(`pipe_exec.sh migrate maintain --target applog` — 실패하면 경고만 남기고 계속) 뒤 `run_pipeline.py --start-offset 0 --skip-done --max-docs <상한> --deadline <마감>`을 부른다(마감이 지나면 새 문서를 받지 않고, 받은 문서는 끝까지). 형식이 틀리면(HH:MM 아님 · 상한이 1 이상 정수 아님 · 마감이 시작보다 5분 이내) 종료 2. 지금 바로 돌리려면 run_pipeline을 직접 부른다.

### 2-3. 답변 생성 점검(개발 서버 — 컨테이너 안에서)
호스트 python에는 PyYAML만 있으므로 도구는 컨테이너 안에서 돌린다. `validation/`은 코드 폴더를 붙인 개발 서버의 실행 이미지에만 있다(운영 이미지에는 없음).
```bash
$DOCKER exec data-pipeline python -m validation.e2e.answer_gen --url http://127.0.0.1:<search.server.mcp_port>/mcp --q "<질문>"   # --concurrency N · 결과 /app/output/eval/answer_gen/
```
MCP 토큰은 settings.yaml `required.tokens.mcp_token`, 모델은 `required.models.llm_*`(서버는 내부 모델만). 결과는 호스트 `<결과 폴더>/eval/answer_gen/`.

### 2-4. 매일 점검
아침에 한 번, 코드 폴더에서(여러 벌이면 이름 끝 `-<벌>`):

| 무엇 | 명령 | 정상 |
|---|---|---|
| 새벽 배치 | `journalctl -u data-pipeline-nightly.service --since yesterday \| tail -20` | 시작·끝 줄, 종료 코드 0(실패 문서 있음 1 · 마감 75) |
| 실패 문서 | `grep FAIL <작업 폴더>/batch_progress/progress.log \| tail` | 줄 없음 — 있으면 §3 |
| 검색 MCP | `curl -s http://127.0.0.1:<search.server.mcp_port>/health` | `{"ok":true,"ready":true,…}` |
| 디스크 | `df -h <루트> <결과 폴더>` · `du -sh <결과 폴더>/_docflow <결과 폴더>/_staging` | 쓰기 여유 20% 넘음 · `_docflow`·`_staging`이 계속 늘지 않음 |
| 로그 예비 파일 | `ls -la <결과 폴더>/logs/` | 비어 있음 — 파일이 있으면 DB 로그 쓰기 실패(파일 안 오류를 보고 DB를 고친 뒤 지움) |
| 컨테이너 | `bash deploy/host/scripts/host_ctl.sh ps` | 세 줄 Up |

- `<작업 폴더>` = `ops.run_pipeline.run_pipeline_work_dir`(비우면 코드 폴더 안 `deploy/host/scripts/test_space/`). `<결과 폴더>` = `<루트>/output`(또는 `ops.host.host_output_dir`).
- 문제가 있으면 §7 형식으로 `issues.md`에 적는다. DB에서 더 보려면 §8의 SQL.

### 2-5. 서버를 다시 켠 뒤
컨테이너·타이머를 사람이 다시 띄운다(자동 재시작에 맡기지 않는다). root 셸, 그 벌 폴더(코드 폴더)에서:
```bash
export DOCKER=podman
bash deploy/host/scripts/host_ctl.sh up -d data-pipeline mcp-data-parsing mcp
bash deploy/host/scripts/host_ctl.sh ps                                   # 기대: 세 줄 Up
systemctl start mcp-server-keepalive.timer data-pipeline-nightly.timer   # 꺼져 있었으면
systemctl list-timers 'mcp-server-keepalive*' 'data-pipeline-nightly*'   # 기대: 두 타이머 다음 실행 시각
bash deploy/host/scripts/host_ctl.sh check                                # 기대 마지막 줄: [host_ctl check] 통과 — 6개
```
- 여러 벌이면 벌마다(그 벌 폴더에서) 같은 순서로 한다. PG 컨테이너는 DB 담당 몫이다 — `check`가 PG에서 멈추면 DB 담당에게 알린다.
- 꺼지기 전에 돌던 `run_pipeline.py`는 다시 시작하지 않는다 — 다음 새벽 배치가 `--skip-done`으로 이어 가거나, 사람이 다시 부른다(§3).

## 3. 실패한 문서 찾기와 다시 돌리기

- **진행 기록:** `<작업 폴더>/batch_progress/progress.log` — 문서마다 `doc#<번호> 파싱 OK|FAIL` · `doc#<번호> publish OK|FAIL` · `doc#<번호> 구조화+적재 OK|FAIL` 줄. 문서별 로그(파싱·게시·구조화 출력)는 같은 폴더의 `doc_<번호>.log`.
- **작업 폴더 자리:** 비우면 코드 폴더 안 `deploy/host/scripts/test_space/` — 벌마다 따로이고, 새 판을 덮어써도 기록과 잠금이 남는다. 다른 자리에 두려면 settings.yaml `ops.run_pipeline.run_pipeline_work_dir`에 호스트 절대 경로를 적는다(벌마다 다르게 — 같으면 두 벌이 한 잠금을 나눠 써 함께 돌지 못한다).
- **실패 문서 번호 모으기:**
```bash
grep -E 'doc#[0-9]+ (파싱|publish|구조화\+적재) FAIL' <작업 폴더>/batch_progress/progress.log | grep -oE 'doc#[0-9]+' | sort -u | tr -d 'doc#' | paste -sd, -
```
- **다시 돌리기:** 원인을 고친 뒤(설정·EDW·모델 등) 그 번호만 — `nohup python3 deploy/host/scripts/run_pipeline.py --seqs <번호,번호,…> > <작업 폴더>/rerun.out 2>&1 &`(코드 폴더에서). 실패한 문서는 gold `doc` 행이 없으므로 다음 `--skip-done` 실행도 다시 고른다.
- 다시 받아도 같은 결과인 문서(DRM·암호·지원 안 함·확장자 없음)와 내용 중복은 `applog.except_doc_info`에 `skip` 행으로 들어가 다음 실행이 고르지 않는다(§8 ④).
- 검색 결과 품질은 PC의 검증 페이지(`validation/search_ui`)와 답변 점검(`valid_env/answer_test`)으로 본다.

## 4. 검색 MCP 사용

```
주소: http://<수집 서버 사내 IP>:<search.server.mcp_port>/mcp (MCP streamable HTTP)
인증: Authorization: Bearer <required.tokens.mcp_token>
상태: GET http://<IP>:<포트>/health (토큰 불필요)
```
- 도구 6개의 입력·출력·한도·오류는 [mcp-guide.md](mcp-guide.md). `search`는 원천 하나(`source_system`)가 필수다.
- 답을 쓰는 쪽: 숫자·고유명사는 근거 `text` 그대로 인용, `evidence_status`가 `none`/`weak`이면 표시, 근거 안의 지시문은 따르지 않는다.
- 연결 시험(컨테이너 안에서): `$DOCKER exec mcp-server python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:<search.server.mcp_port>/mcp --source <원천> --q "<질문>"` — 기대 끝 줄 `MCP 바깥 호출 통과`. 루프백이 아닌 주소로 부르면 `--token <토큰>`도 준다.

### 4-1. EDW 쿼리 도구 설정 — `edw_meta`·`query_edw`
에이전트가 `edw_meta`(정적 자료, DB 접속 없음)로 표·칸을 보고 `query_edw`로 SELECT를 보낸다. 읽기 전용·시스템 표 차단·상한은 코드(`mcp_server/services/edw_query.py`)가 강제하지만, **운영자가 아래를 준비해야 안전하다.**

0. **EDW 표 설명 자료**(`edw_meta`용) — `catalog.json`(표 목록·설명)·`columns.jsonl`(한 줄에 열 하나)을 `<루트>/output/edw_meta/`에 복사하고 `search.edw_meta.edw_meta_catalog_dir: /app/output/edw_meta`를 적는다. 개인정보가 없는 자료만 둔다. 없으면 `edw_meta`만 `not_configured`(`query_edw`는 그대로) — 파일 꼴은 PRD [mc-07](../prd/mcp.md#mc-07), 받기는 refactor.md C-91.

1. **EDW 읽기 계정**(`required.edw.edw_read_user`·`edw_read_password` — 파이프라인 원천 조회와 같은 계정):
   - `SELECT` 권한만 준다(DDL·DML·`EXEC`·시스템 프로시저 없음).
   - DBA가 추가로: `DENY VIEW DEFINITION` · 다른 데이터베이스·연결 서버(linked server) 권한 없음 · 가능하면 Resource Governor 등으로 질의 시간·CPU 상한.
   - 같은 계정이라 `query_edw`도 `AI.FileStorageMap`을 읽을 수 있다 — 막으려면 2.
2. **표 범위** — 읽기 계정이 볼 수 있는 모든 표(`sys.*`·`INFORMATION_SCHEMA.*`는 늘 거부). 좁히려면 DBA가 읽기 계정의 `SELECT` 권한을 줄인다(설정의 허용 목록은 없다).
3. 확인: `query_edw({"sql": "DROP TABLE ..."})`·`sys.*`를 읽는 호출이 `rejected:*`로 막히는지 한 번 본다.

## 5. 회사 맞춤(도메인 튜닝)

바꿀 곳은 코드가 아니라 **데이터 파일·설정**이다. 기밀(실고객·실제품·계약 값)은 **서버 폴더에만** 둔다 — git·PC·외부 모델로 보내지 않는다. 바꾼 뒤에는 같은 질문 세트로 검색 결과를 전/후 비교한다.

| 무엇 | 위치 |
|---|---|
| 용어집 · 고객 명부 · ID 모양 | PG 마스터 표 `<db_schema>_master.glossary`. 원본 `glossary.csv`(`resources/vocab/glossary/` 또는 서버 폴더)를 고친 뒤 `pipe_exec.sh migrate master load [--dir <폴더>]`(5-1) |
| 원천 표 열 이름 | settings.yaml `tuning.extract.source_columns.source_column_*` |
| 엔진 구성 | `resources/config/pipeline_stack.json`(확인 `show-stack`) |
| MCP 안내 문구 | 코드 `mcp_server/main.py`의 `_DEFAULT_MCP_INSTRUCTIONS`(설정 칸 없음 — 바꾸면 코드 배포) |
| EDW 조인 사슬(고객·원천 메타·검색 attrs 키) | 서버 사본 `<루트>/edw_chain.yaml`(5-2) |

### 5-1. 고객 명부·용어집 작성법

구조화·검색은 파일이 아니라 PG 마스터 표 `glossary`만 읽는다. `migrate master load`가 CSV 하나 `glossary.csv`(파일 이름·머리글 그대로)로 표를 통째로 바꾼다. 기본 폴더는 샘플(가상 회사·제품) `resources/vocab/glossary/`. 서버 실명 자료(고객 명부·용어집이 든 `glossary.csv`)는 **`<루트>/output/glossary/`**에 두고(UID 10001이 읽게) 컨테이너 안 자리로 넣는다: `bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary`. 표가 비었으면 서버의 구조화·검색이 시작하지 않는다.
- **`master load` 뒤에는 검색 MCP를 다시 시작한다** — `bash deploy/host/scripts/host_ctl.sh restart mcp`(검색은 시작할 때와 새 적재 판이 들어올 때만 마스터를 읽음). 이미 적재한 문서는 자동으로 다시 처리하지 않는다(새로 적재하는 문서의 `gold_version` `<VERSION>+m<해시 8자>`만 바뀜 — 다시 하려면 [upgrade-guide §8](upgrade-guide.md#8-다시-처리할-층과-명령)).
- `--dir`에는 **컨테이너 안에서 보이는** 폴더를 적는다 — 컨테이너에 붙는 서버 폴더는 결과 폴더(`/app/output`)뿐이다([env-guide §5](env-guide.md#5-서버-경로-칸--컨테이너-안-절대-경로)).
- 칸 설명은 `docs/architecture/db_schema.md` §4. UTF-8로 저장(Excel이면 "CSV UTF-8" — cp949도 읽힘). 머리글이 다르면 `master load`가 거부한다.

#### `glossary.csv` 꼴
머리글 `kind,canonical,variant,variant_kind,description,context_required,case_sensitive`. 한 줄 = 값 하나 — 고객·용어·ID 꼴 하나는 머리 줄(`client_id`·`concept_id`·`regex`)에서 시작하고, 바로 뒤따르는 같은 `kind`·`canonical` 줄이 거기에 붙는다(이름이 같은 고객 둘·이름이 빈 고객도 따로, ID 꼴은 `regex` 줄마다 하나 — `example`·`updated`는 그 앞 `regex` 줄 것). 머리 줄 없이 나온 줄, 값이 하나뿐인 종류(`status` 등)를 한 고객·용어에 두 줄 쓰면, 또는 모르는 `kind`·`variant_kind`를 쓰면 `master load`가 표를 바꾸지 않고 거부한다.

```csv
kind,canonical,variant,variant_kind,description,context_required,case_sensitive
client,Hanbit Biologics,C0001,client_id,항체 바이오시밀러 위탁생산 고객,,
client,Hanbit Biologics,한빛바이오,alias,,,
term,Contract Manufacturing Organization,BIZ.CMO,concept_id,고객이 확립한 공정으로 생산만 위탁 수행,위탁생산|생산|제조,N
term,Contract Manufacturing Organization,위탁생산,synonym,,,
term,Contract Manufacturing Organization,CMO,abbr,,,
id,contract_no,"C-[A-Z]{2,4}-\d{4}-\d{2}",regex,합성 데이터 형식,,
```

**고객(`client`)** — `canonical` = 정식 이름(비우면 `name_ko`가 이름). 첫 줄은 `client_id`(번호가 없어도 빈 값으로 둔다).

| `variant_kind` | 쓰는 법 |
|---|---|
| `client_id` | 고객 번호(SFDC 등) — `description`에 고객 설명 |
| `name_ko` | 한글 이름 — 별칭으로도 쓰임 |
| `alias` | 다른 표기 — 한 줄에 하나 |
| `client_type` | `customer`·`prospect` — 둘 다 똑같이 쓰임 |
| `segment`·`country`·`parent`(모회사 `client_id`)·`source`·`updated` | 참고용 — 빼도 됨 |
| `status` | 없으면 사용 · `inactive`·`deleted`면 무시 |

- 영문 3자 이하 별칭(예 `PFE`)은 오탐 때문에 무시된다 — 4자 이상이나 한글로. 같은 별칭을 두 고객에 쓰지 않는다.

**용어(`term`)** — `canonical` = 표준 이름(필수). 첫 줄은 `concept_id`.

| `variant_kind` | 쓰는 법 |
|---|---|
| `concept_id` | 겹치지 않는 영문 ID(`분야.이름`, 예 `QA.OOS`) — 없으면 `AUTO.<canonical>`. `description`에 한글 정의, `context_required`(동음이의 줄임말이면 주변에 함께 나와야 하는 단어들, `\|` 구분)·`case_sensitive`(`Y`면 대소문자 구분)도 이 줄에 |
| `category` | `org_client`(고객 — 명부에 합류)·`product_example`·`modality`·`modality_code`·`process`·`quality`·`contract`·`regulatory`·`business` 등 — 한 줄에 하나 |
| `synonym` · `abbr` | 같은 뜻의 다른 표기 · 줄임말 — 한 줄에 하나 |
| `weak` | 뜻이 넓어 약하게만 쓰는 말 |
| `broader`·`related` | 상위·관련 개념의 `concept_id`(없는 ID면 오류) |
| `definition_en`·`source`·`owner`·`updated` | 빼도 됨 |
| `status` | 없으면 반영 · 빼려면 `draft`·`rejected` |

**ID 꼴(`id`)** — `canonical` = 종류(`contract_no`·`product_code` 등). `regex` 줄 하나 = 정규식 하나(대소문자 무시, `description`에 메모), 바로 뒤 `example`·`updated`는 그 꼴의 참고용. `regex` 줄 순서가 검색 동점 처리 순서다.

- 오류(조용히 넘기지 않음): 명시한 `concept_id` 중복 · 없는 ID를 가리키는 `broader`/`related` · 깨진 정규식.
- 초안 도구 `python -m pipeline.transform.structure.glossary_suggest`·`gen_roster --kind product`·`python -m pipeline.transform.structure.draft_terms --bundle <묶음>`은 `output/` 아래 초안(용어 사전 옛 칸 꼴 — 한 줄 = 개념 하나)만 만든다 — 사람이 확인해 `glossary.csv`의 `term` 줄로 옮긴다.

#### 고객 마스터에서 명부 만들기
SFDC·EDW 내보내기에서 `glossary.csv`의 고객(`client`) 줄을 만든다. 열 이름만 매핑 파일에 적는다(예제: `resources/vocab/glossary/client_master.example.csv` + `client_master_map.example.json`). 매핑 키 = 명부 칸: `name`(필수 → `canonical_name`) · `aliases`(`;`·`|`) · `client_id`·`name_ko`·`client_type`·`segment`·`country`·`parent_client_id`·`status`·`description`·`updated`(선택). 열 이름은 영문·숫자·`_`만. 같은 고객 여러 줄은 하나로 합친다(별칭은 합치고 다른 칸은 처음 값).
내보낸 파일과 매핑 파일을 `<루트>/output/glossary/`에 둔 뒤(컨테이너에서 `/app/output/glossary/`):
```bash
G=/app/output/glossary
$DOCKER exec data-pipeline python -m pipeline.transform.structure.roster_from_edw --kind client \
  --source csv:$G/client_master.csv --mapping $G/client_master_map.json \
  --out $G/glossary.csv               # EDW 표에서 바로: --source rdb:<스키마.표>(읽기 계정)
$DOCKER exec data-pipeline python -m pipeline.transform.structure.roster_from_edw --check $G/glossary.csv   # 오류 0 확인
```
`--out` 파일이 이미 있으면 고객 줄만 바꾸고 용어·ID 꼴 줄은 그대로 둔다(glossary 꼴이 아닌 파일이면 거부). 먼저 파일을 복사해 두고 바뀐 줄을 비교한 뒤 반영한다.

#### 옛 CSV를 `glossary.csv`로 옮기기
옛 판의 `client_roster.csv`·`domain_terms.csv`·`id_patterns.csv`가 있는 폴더를 한 번에 옮긴다(같은 대응 — 없는 파일은 건너뜀. 만들 파일이 이미 있거나, 머리글이 옛 꼴과 다르거나(없는·모르는 칸), 머리글보다 칸이 많은 줄이 있으면 아무것도 쓰지 않고 거부):
```bash
$DOCKER exec data-pipeline python -m common.store.master convert --src /app/output/glossary --out /app/output/glossary/glossary.csv
```

#### 점검(반영 전)
```bash
$DOCKER exec data-pipeline python -c "import sys; from pathlib import Path; from common.store import master as M; from common.core import terms as T; m = M.Master(M.read_csv(Path(sys.argv[1]))); print(len(T._master_glossary(m)), '개념 반영 ·', len(m.rows('client_roster')), '고객 ·', len(m.rows('id_patterns')), 'ID 꼴')" /app/output/glossary   # 오류면 여기서 멈춤
bash deploy/host/scripts/pipe_exec.sh migrate master load --dir /app/output/glossary && bash deploy/host/scripts/host_ctl.sh restart mcp   # 반영
```

### 5-2. EDW 조인 사슬 고치기 — `edw_chain.yaml`
고치는 곳·법·점검·되돌리기는 [release-and-patch §8](release-and-patch.md#8-edw-조인-사슬-파일-고쳐-쓰기서버) 하나에 있다. 사슬을 바꿔도 이미 적재한 메타는 바뀌지 않는다 — 필요한 문서는 `--replace`로 다시 적재한다([upgrade-guide §8](upgrade-guide.md#8-다시-처리할-층과-명령)).

## 6. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `check`가 "컨테이너 안의 PG_HOST는 컨테이너 자신" 경고 | `required.pg.pg_host`가 `127.0.0.1` | compose로 띄웠으면 무시(`network_mode: host`). `docker run`으로 따로 띄울 때만 `--network host`(+`-e NETWORK_HOST=1`) 또는 서버 IP |
| 적재·검색이 PostgreSQL에 못 붙음 | `required.pg` 칸이 비었거나 틀림 | 호스트·포트·계정 확인 |
| 파싱이 종료 4 | 서버에서 끝난 문서 기록(PG 원천 스키마 `doc`)을 못 읽음(전체 재파싱을 막으려고 멈춤) | `required.pg` 접속·PG 상태 확인 |
| 구조화·적재가 "인계 형식(핑거프린트) 다름"으로 거부 | 핑거프린트가 바뀐 옛 파싱 결과 | 그 문서를 다시 파싱 |
| 같은 결과 폴더에서 종료 75 | 다른 실행이 `.pipeline.lock`을 잡고 있음 | 끝날 때까지 기다리거나 다음 트리거에서 재시도 |
| 메모리 터짐(OOM), 큰 스캔 PDF | 쪽 이미지를 한꺼번에 올림 | `extract.page_render_dpi`(기본 150 — 더 낮추면 VLM 글 품질을 먼저 확인)·VLM 쪽 상한 `transform.vlm.vlm_max_pages_per_doc`·OCR 엔진 쪽 상한 `extract.ocr.ocr_max_pages_per_doc`·`extract.max_source_file_mb`·컨테이너 메모리 상한 확인 |
| CPU 폭주 | 컨테이너가 호스트 전체 코어로 스레드를 늘림 | `ops.runtime.engine_processes`는 `auto`(cgroup 한도 기준), 컨테이너 CPU 상한 지정 |
| MCP `/health` 503 | 기동 직후 예열 중 | 잠시 뒤 재시도 |
| MCP 401 | 호출 쪽 토큰이 없거나 `required.tokens.mcp_token`와 다름 | 호출 쪽 `Authorization: Bearer <토큰>`을 서버 값과 같게 |
| MCP가 안 뜸 | `required.models.embed_base_url`·`embed_model` 없음 · 컨테이너가 설정 파일을 못 읽음(권한) | 필수 값 채우기 · 주인 10001·권한 640 |
| `data-pipeline`·`mcp-server`가 안 뜸("edw_chain.yaml" 자리에 폴더) | `host_ctl.sh init` 전에 컨테이너를 띄워 빈 폴더가 생김 | 빈 폴더를 `rmdir` → `host_ctl.sh init` |
| 포트 충돌 | 다른 서비스가 같은 포트 | `search.server.mcp_port` 등 포트 칸만 바꿈 |
| SELinux `Permission denied`(파일 권한·주인은 맞음) | 볼륨 라벨이 안 맞음 | 막힌 기록 보기 `ausearch -m avc -ts recent`(`denied { read }` 등과 파일 경로) · 라벨 보기 `ls -Z <폴더>`(`container_file_t`여야 함) · 우리 compose는 `:z`로 붙임 — 직접 붙인 볼륨이면 `:z` |
| SELinux — 원본 폴더가 NFS | NFS에는 `:z` 라벨을 붙일 수 없음 | `setsebool -P container_use_nfs 1`(서버 관리자) 뒤 컨테이너를 다시 띄움 |

## 7. 개발자에게 보고하는 법

### 서버 버전 기록
적용·업데이트마다 운영 기록 폴더(벌 폴더 밖 — 판이 바뀌어도 이어 씀, 이하 `<기록>`)의 `versions.md`에 한 줄: `날짜 · 서버 · 이미지 버전 · 코드 커밋 · 확인 결과`.

### 서버 자체 개발 기록
서버에서 코드를 직접 고치거나 새로 만들었거나 옵션 값을 바꿨으면 그때마다 `<기록>/server-changes.md`에 한 행 + diff를 `<기록>/server-changes/<ID>.diff`로(`diff -u <고치기 전> <고친 뒤>`, 새 파일이면 `diff -u /dev/null <파일>`). 새 판으로 바꿀 때 이 기록을 먼저 읽는다([release-and-patch §2](release-and-patch.md#2-서버에서-직접-고친-코드)).
```
| ID(SC-<MMDD>-<n>) | 날짜·시각 | 서버(수집/개발) | 바뀐 파일(코드 폴더 기준 경로) | 무엇·왜 한 줄 | 기준 버전(이미지+코드 커밋) | 테스트(명령·결과) | 상태(서버에만/PC 보냄/다시 얹음 <커밋>/PC 반영됨 <커밋>/폐기) |
```
지우지 않고 상태만 바꾼다. diff에는 코드만 — 비밀값·문서 본문·고객명은 넣지 않는다.

### 이슈 기록
문제가 나면 `<기록>/issues.md`에 한 행(지우지 않고 상태만 바꿈):
```
| ID(SI-<MMDD>-<n>) | 버전(이미지+코드 커밋) | 서버(수집/개발) | 단계·명령 | 증상 한 줄 | 종료 코드 | 로그 위치 | 상태(열림/수정됨/재확인 통과) |
```
반출 규칙: **오류 메시지·종료 코드·숫자·해시 이름만** — 문서 본문·고객명·원본 경로·키 값은 적지 않는다.

### 날짜별 요약
파싱이 끝날 때마다 `<기록>/<날짜>.md`에 버전(`versions.md` 줄)·단계·종료 코드·핵심 숫자(정답률·시간·건수)·막힌 곳·로그 마지막 20줄(비밀값 가림)을 적는다. 본문은 복사하지 않는다.

## 8. 로그 DB 살펴보기 — applog SQL(읽기만)

실행 기록은 PG `applog` 스키마에 있다(`pipe_run` 실행 1건 · `pipe_event` 단계 1건 · `mcp_log` MCP 호출 1건 · `except_doc_info` 적재 안 된 문서 — `skip` 영구 뺌·`error` 실패). 읽기 전용 거래 안에서만 본다:
```bash
$DOCKER exec -it <required.deploy.pg_container_name> psql -U <required.pg.pg_user> -d <required.pg.pg_database>
# psql 안에서 먼저:  BEGIN READ ONLY;      끝나면:  ROLLBACK;
```
- ⚠️ `mcp_log.args`·`result`에는 질문·SQL·문서 원문이 들어 있다 — 아래처럼 필요한 칸만 고르고, 결과를 밖으로 옮기지 않는다.

**① 지난 7일 실패한 실행**
```sql
SELECT started_at, run_id, command, status, duration_ms / 60000 AS min,
       docs_total, docs_ok, docs_fail, docs_reused, app_version, host
FROM applog.pipe_run
WHERE started_at > now() - interval '7 days'
  AND (status IN ('fail', 'interrupted') OR docs_fail > 0)
ORDER BY started_at DESC;
```
`status`: `running`(도는 중 또는 죽음) · `ok` · `fail` · `stopped`(마감 도달) · `interrupted`.

**② 느린 단계** — 단계별 시간과, 하루 동안 가장 오래 걸린 단계 20건
```sql
SELECT layer, stage, count(*) AS n, round(avg(duration_ms)) AS avg_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms, max(duration_ms) AS max_ms
FROM applog.pipe_event
WHERE ts_start > now() - interval '7 days' AND duration_ms IS NOT NULL
GROUP BY layer, stage ORDER BY p95_ms DESC LIMIT 15;

SELECT ts_start, run_id, layer, stage, engine, model, doc_id, ext, file_bytes,
       duration_ms, wait_cpu_ms, wait_mem_ms, ext_call_ms, rss_peak_mb, status, err_kind
FROM applog.pipe_event
WHERE ts_start > now() - interval '1 day'
ORDER BY duration_ms DESC NULLS LAST LIMIT 20;
```
`wait_cpu_ms`·`wait_mem_ms`가 크면 자원 대기(CPU·메모리 문턱), `ext_call_ms`가 크면 모델 호출이 느린 것이다. 한 실행을 자세히: `$DOCKER exec data-pipeline python -m pipeline.tools.perf_report <run_id>`.

**③ MCP 도구별 호출 수 · 오류율 · p95**
```sql
SELECT tool_name, count(*) AS calls,
       round(100.0 * count(*) FILTER (WHERE status <> 'ok') / count(*), 1) AS err_pct,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
FROM applog.mcp_log
WHERE requested_at > now() - interval '7 days' AND tool_name IS NOT NULL
GROUP BY tool_name ORDER BY calls DESC;

SELECT tool_name, status, error_code, count(*) AS n
FROM applog.mcp_log
WHERE requested_at > now() - interval '7 days' AND status <> 'ok'
GROUP BY tool_name, status, error_code ORDER BY n DESC;
```
`status`: `ok` · `error` · `denied` · `unauthorized`(토큰) · `busy`(동시 상한) · `timeout`.

**④ 적재 안 된 문서 — 종류·이유별**
```sql
SELECT except_type, reason, source_system, count(*) AS docs, sum(count) AS times_seen, max(last_seen) AS last_seen
FROM applog.except_doc_info
GROUP BY except_type, reason, source_system ORDER BY docs DESC;
```
`skip` 풀어 주는 법(행 지우기 — DB 담당 승인)은 [env-guide 실행 기록](env-guide.md#0-0-실행-기록json-로그db-감사성능).

## 9. 건드리면 안 되는 것

서버에서 아래를 바꾸면 결과가 깨지거나 전체를 다시 처리해야 한다. 바꿔야 하면 먼저 승인을 받는다(역할은 [README 담당 연락처](../../README.md#0-읽기-전에--꼭-알아-둘-것)).

| 칸·파일 | 바꾸면 | 누가 승인 |
|---|---|---|
| `required.tokens.fulltext_sign_key` | 이미 발급한 원문 도구 `sfid`가 모두 무효 — 클라이언트가 가진 원문 링크가 깨진다 | 지금 담당자(클라이언트 담당에게 먼저 알림) |
| `required.models.embed_model` | 적재된 벡터와 모델이 달라 적재가 거부되고(종료 2) 벡터 검색이 막힌다 — 바꾸려면 새 스키마에 전부 다시 | 지금 담당자·모델 담당·DB 담당 |
| `required.pg.pg_schema` — 다른 판·다른 벌이 쓰던 스키마를 다시 쓰기 | 남의 표에 `migrate up`(0.1.0 스키마면 옛 표가 지워짐)·문서가 섞인다 | DB 담당 |
| 엔진 파일 `pipeline/transform/parse/engines/` | 엔진 지문이 바뀌어 그 엔진의 문서를 모두 다시 파싱한다 | 사람 검토 — 지금 담당자 |
| 프롬프트 `resources/prompts/` | 지시서 지문·LLM 캐시 열쇠가 바뀌어 모델을 다시 부르고 결과가 달라진다 | 사람 검토 — 지금 담당자 |
| MCP 도구 계약 — 도구 6개의 이름·입력·출력 | 외부 클라이언트가 깨진다 | 지금 담당자·클라이언트 담당 협의(새 판으로) |
