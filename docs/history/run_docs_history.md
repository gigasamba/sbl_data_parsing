# 문서별 flow 러너 — 버그 수정 이력 · 속도 개선 성과

[../architecture/run_docs_design.md](../architecture/run_docs_design.md) §4·§5에서 옮김(10-30, do-04 2부). 지금 동작은 설계 문서와 [PRD etl.md](../prd/etl.md#pl-10)에 있다.

## 4. 버그 수정 이력

| 날짜 | 버그 | 원인 | 수정 |
|---|---|---|---|
| 10-22 19:11 | 파싱 전건 실패 | glossary/client_roster.csv 미마운트 | 마운트 추가 |
| 10-22 20:55 | figures index.jsonl 경합 크래시 (JSONDecodeError) | images_root()가 PIPE_OUT_ROOT 무시→공유 경로→4워커 read-modify-write 경합 | figures.py: PIPE_OUT_ROOT 따르게 수정 + PARSE_IMAGES_ROOT per-doc |
| 10-22 22:2x | 6시+ 실패 120건 폭증 | 위 경합 (원장 부풀며 악화) | 위 수정으로 해결 |
| 10-23 09:55 | docx 외부 링크 이미지 crash (ValueError) | python-docx _Relationship.target_part external 접근 | figures.py: is_external skip |
| 10-23 10:20 | probe stdout 경고 오염 | pymupdf fitz deprecated 경고가 stdout에 → 분류기 항상 heavy 폴백 | docflow_probe.py: pymupdf 직접 import + 마지막 줄만 판독 |
| 10-23 10:30 | light 슬롯 대기 오폭 | executor while 안에 shutdown 라인 (IndentationError) | for/shutdown을 while 밖으로 |
| 10-23 10:45 | dedup 36s | 게이트 0.9가 기본값 (env 미주입 세대) | --cpu-gate 노브 추가, 1.15→1.5→1.3 |
| 10-23 (I2) | 이미지 배치가 `data_etl/`로 바뀜 | 리팩토링 I2(`data_parsing`·`data_structure` → `data_etl`) | `docker exec … python -m data_etl.…`로 명령 이름만 바꿈 — 새 이미지 판과 같은 때에 교체([`docs/operations/server-guide.md`](../operations/server-guide.md#5-릴리스--실행-이미지--코드-폴더) §5-2) |
| 10-26 (I3) | 옛 이미지·코드 폴더로 돌면 중간에 실패 | 이미지·코드 폴더·러너 판이 어긋날 수 있음 | 시작할 때(EDW 접속 전) 코드 폴더·컨테이너 배치 확인 → 어긋나면 종료 코드 2 |
| 10-26 (I4) | 코드 폴더 확인이 쓰이지 않던 `patch_code/app/deploy`를 봄 · MCP 작업 폴더가 서버 절대 경로로 박힘 | `DEPLOY`·`IMAGE`는 처음부터 미사용 상수 · 경로 하드코딩 | 확인은 env `PATCH_CODE`(기본 `/srv/rag/code/live`, compose와 같음) — 호스트에서 안 보이면 건너뛰고 컨테이너 확인만 · `DEPLOY`·`IMAGE` 지움 · env `MCP_JOBS_DIR`(기본 `test_space/rfp_all_output/mcp_parse/jobs`, 이 파일 기준) |
| 10-26 (I4b) | 코드 폴더가 없어도 컨테이너 확인이 통과할 수 있음(V4 R2) | docker는 bind 마운트 원본이 없으면 빈 폴더를 만들어 붙여 `test -d /app/deploy/data_etl`이 통과 | 확인을 파일로 — 컨테이너 `test -f /app/deploy/data_etl/extract/run_all.py`, 코드 폴더도 같은 파일(`CODE_MARKER`) · 빈 폴더면 종료 코드 2 |
| 10-26 (S4) | 이미지 배치가 `pipeline/`으로 바뀜 · 컨테이너 안 `docflow_probe.py` 자리 | 리팩토링 S4(`data_etl/` → `pipeline/`, `docflow_probe.py`는 저장소 루트 → `pipeline/extract/` — 이미지에 함께 들어감, T-14) | `python -m pipeline.…`·`pipeline.cli`로 명령 이름만 바꿈 · `CODE_MARKER` = `pipeline/extract/run_all.py` · 무게 판별은 `python3 /app/deploy/pipeline/extract/docflow_probe.py` — 새 이미지 판과 같은 때에 교체(`refactor.md` C-23) |
| 10-27 (S6b) | 러너 자리·컨테이너 이름이 바뀜 | 리팩토링 S6b(D-020·D-026 — 파이프라인 이미지 합침 `data-pipeline`, 이름 사용자 10-27) | 저장소 자리 `run_script/run_docs.py` → `deploy/host/scripts/run_docs.py`(`test_space/`는 스크립트 옆 그대로) · docker exec·inspect 대상 `data-parsing`·`data-structure` → `data-pipeline-parse`·`data-pipeline-structure`(상수 `PARSE_C`·`STRUCT_C`) — 새 이미지 판과 같은 때에 교체(`refactor.md` C-29) |
| 10-28 (S9 Step A) | 문서별 결과 폴더(`PIPE_OUT_ROOT` 등)·채널별 VLM 동시 수·후보정·CPU 게이트가 효과 없음 — 문서별 파싱이 공용 `/app/output`에 쓰고 구조화가 그 결과를 못 찾음(VS8b U-1) | S7e2부터 앱이 env의 옛 설정 이름을 읽지 않는데 러너는 `docker exec … bash -c 'X=값 python …'` env로 줬음(VS7e3 셸 스캔은 `.sh`·compose만 보고 Python 문자열 안 셸 명령은 안 봄 — 로컬 실행 금지라 실행 확인도 없었음) | 설정 칸은 명령 인자 `--set 이름=값`(`common.config.setarg` — 사용자 10-28, 비밀·호스트 칸은 거부)으로 · 명령 줄은 함수(`warm_cmd`·`parse_cmd`·`struct_cmd`·`publish_cmd`·`sweep_cmd`)로 떼어 `tests/general/deploy/test_run_docs.py`가 글자를 고정 · 고아 정리 표지는 env `RUN_DOCS_DOC`(설정 칸 아님) · 구조화는 파싱이 그 문서 폴더에 쓴 엔진 구성 사본을 다시 씀(`stackcfg --path` — VS8b R-1) · `[envcheck]` 줄은 컨테이너 env 대신 준 게이트 값 · 읽는 코드 없는 env 4개(`FIG_OCR_BUDGET`·`*_MASTER_CSV`)는 그대로 |
| 10-29 (rn-01·rn-02) | 레인 배분·steal이 코드에 고정(1/2/1, 죽은 분기) · 구조화 대기열 상한 없음 · 대기 길이 기록 없음 | 사용자 10-29 — "lane은 담당, 일부 steal 허용, 우선순위는 담당 lane · 진입·중간 개수 관리" | settings.yaml `pipeline.host.run_docs`(레인마다 전담·공유 워커 수, warm 20, struct_workers 2, struct_backlog = 구조화×2, vlm_cap 2) · `pick_lane()`(자기 레인 먼저, 공유 워커만 가장 긴 다른 레인) · 상한에서 레인 워커 대기 · `queue_depth.jsonl` · 옛 상수(HEAVY_*·LIGHT_MAX·LANE_N) 지움 · `--workers`는 받기만 |

---

## 5. 속도 개선 성과

| 시대 | 완료/시간 | CPU 평균 | 주요 변경 |
|---|---:|---:|---|
| 어젯밤(배치, 게이트 0.9) | 57~76 | 57% | 8건 배치, phase 1+2, OCR 1쪽 |
| 오늘 오전(docflow, 게이트 1.15) | 106~137 | 86% | 12건 배치→개별, phase skip, OCR 2×2 |
| **현재(3클래스, 게이트 1.3)** | **~110** | **68%** | 3클래스 레인, steal, MCP 우선, OCR 제거 |

**문서당 중간 wall** (10:15 세션 대비):
- light: 149s → **81s** (-46%)
- scan/VLM: 9.13분 → **222s** (queueing 별도)  
- 전체 파이프라인 오버헤드: dedup 36s→1s, prepare ≈4s, phase2 ≈1s, qa ≈6s

## rn-01 전에 이미 있던 것(PRD etl.md rn-01에서 옮김, 10-30)
- 3레인 나누기: `classify_doc()`이 미리 받은 문서를 light/medium/vlm으로 가른다. 워커 `LANE_N` light 1 / medium 2 / vlm 1, 워커는 자기 레인부터 비운다([PRD pl-10](../prd/etl.md#pl-10)).
- 진입 대기열: `WARM_TARGET`개를 미리 받는다(10-29부터 20 — `pipeline.host.run_docs.warm`, `--warm`). 진행 중 문서는 세지 않고, 문서가 끝나면 임시 파일을 지운다.
- MCP 우선: `mcp_parse/jobs`가 움직이는 동안 `_mcp_pause_monitor()`가 medium 레인의 새 문서 받기를 멈춘다(서버 측정은 아직 — 설계 문서).

## rn-01·rn-02 처음 계획(PRD etl.md에서 옮김, 10-30 — 만든 것은 각 행의 "끝남 10-29")
- rn-01
  - 단계: (1) 레인마다 정책 표 하나: `workers`, `steal_from`(비면 전담 레인). 기본값 = 지금 동작. (2) 자기 대기열이 빌 때만 가져오고, 허용된 레인 중 가장 긴 것부터, `VLM_CAP`은 그대로. (3) 입력: 러너 인자 `--lanes`(호스트 스크립트 — settings.yaml 절이 필요한지는 설계 때 결정, env는 금지 — CLAUDE.md §3). (4) 죽은 분기를 지운다.
  - 수용 기준: `tests/general/deploy/test_run_docs.py`의 표 행 — (대기열, 정책) → 고른 문서. 전담 레인은 다른 문서가 기다려도 가져가지 않음, 자기 대기열이 차 있으면 가져오지 않음, 상한을 넘은 vlm은 건너뜀, 기본 정책은 지금과 같은 문서를 고름.
- rn-02
  - 단계: (1) `--struct-backlog N`: 구조화를 기다리는 문서가 N개면 레인 워커가 새 문서를 받지 않는다(`struct_q.put`이 아니라 `lane_worker`의 고르는 시점에서 막음 — 파싱 워커가 끝난 결과를 들고 있지 않게). 0 = 상한 없음(지금). (2) `mark()` 사건마다 한 줄 `{t, warm, lanes: {light: [대기, 실행], ...}, struct_wait}`을 진행 폴더에 쓴다(op-01이 먼저 들어오면 그 줄 형식을 따름).
  - 수용 기준: 구조화를 멈춘 가짜로 돌려도 구조화 대기가 N을 넘지 않음, N=0이면 지금과 같음, 길이 줄은 JSON으로 읽히고 본 문서 수와 맞음.
