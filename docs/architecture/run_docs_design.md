# 문서별 Flow 파싱 러너 — 요구사항·설계·변경 이력 (2026-10-22 ~ 10-23)

## 1. 배경 요구사항 (사용자 지정)

기존 배치 방식(12건씩 파싱→구조화→적재→publish 순차)은 한 문서가 느려도 나머지가 다음 단계로 못 넘어갔다.
→ **문서 단위 flow + warm 대기열 + 3클래스 레인 워커** 구조로 전환.

### 핵심 원칙
- 문서 1개가 파싱 끝나면 **즉시** 구조화→적재→publish 진행 (배치 장벽 제거)
- 다운로드는 미리 warm 대기열로 12개 유지 (파싱과 비동기)
- 분류(probe)로 문서별 자원 특성 파악 → 워커 배분 최적화

---

## 2. 시스템 아키텍처 (2026-10-23 13:40 기준 최종)

```
[EDW FileStorageMap 4,031건] ← RFI/RFP/proposal/question 합집합, SFDC만
        │
   skip-done(EDW ok/pass) → 완료 문서 자동 제외
        │
   warm 다운로더 1스레드 ── 12개 선반(진행중 제외) ── probe 분류
        │                       ├ light (68% — 텍스트 형식·소형 문서)
        │                       ├ medium (3% — CPU 집중: 대형 텍스트)
        │                       └ vlm (29% — GPU 집중: 스캔/이미지 다수/pptx)
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  3클래스 레인 워커 (light 1 / medium 2 / vlm 1)      │
  │  ├─ steal: 자기 큐 비면 가장 긴 다른 큐에서 가져옴     │
  │  ├─ light는 medium steal 금지 (전담 가용성 유지)      │
  │  ├─ vlm은 medium steal 금지 (긴급 vlm 대기 가능)      │
  │  ├─ VLM_CAP=2 (gpu02 동시 상한)                     │
  │  ├─ MCP 우선: mcp_parse/jobs 활동 감지 시 medium pause │
  │  └─ 단일 컨테이너(data-pipeline-parse) + 격리      │
  └─────────────────────────────────────────────────────┘
        │
  구조화+적재 1스레드 (EMBED_BATCH=32 · EMBED_CONCURRENCY=6 · BM25_THREADS=3)
        │
  publish (OS 업로드 + EDW INSERT) → docflow/warm 임시 즉시 삭제
```

---

## 3. 파라미터 (2026-10-23 확정)

| 영역 | 파라미터 | 값 | 근거 |
|---|---|---|---|
| **워커 배분** | LANE_N | light 1 / medium 2 / vlm 1 (총 4) | 코어 4 정합 |
| | VLM_CAP | 2 | gpu02 예산 (6/doc × 2 = 12동시) |
| | steal 규칙 | light≠medium, vlm≠medium | 전담 가용성 |
| **게이트** | light | bypass(=9) | light 즉시 소화 |
| | medium/vlm | CPU_GATE=1.3 (조정 시 `--cpu-gate 1.1`) | 목표 밴드 75-85% 대비 |
| **OCR** | 사용 | **전면 OFF** (스캔 PDF만) | rapidocr 엔진 제외, PREPARE_ROTATE=0 |
| | RAPIDOCR_PAGE_WORKERS | 2 | (운영상 남아 있으나 스캔 레인에선 미사용) |
| | OCR_DPI | 120 | 렌더 비용 절감 |
| **VLM** | 문서당 동시 | **6** (vlm class) / 8 (light) | 3vlm×6=글로벌 18 |
| | FIGURES | VLM_FIGURES_MAX=10, FIG_OCR_BUDGET=0 | OCR분류 skip → 직접 VLM |
| | vlm_page | **스캔 PDF만 ON**, VLM_PAGE_MAX=무제한 | 내부 스캔판정 쪽만 |
| | VLM_PAGE_SLOW | 45s | 적응형 축소 |
| **파이프라인** | ~~PARSE_PHASES~~ | (10-29 삭제 — phase 없음, prd pl-22) | |
| | PARSE_QA_LIGHT | 1 | cer/order 생략(cross_recall 유지→doc_accuracy 무손상) |
| | PARSE_REP_SELECT | first | 첫 성공 엔진 사용 |
| | PARSE_MERGE_PAGES | 1 | 페이지 병합 |
| | PIPE_PROCS | 4 (기본) | light 엔진 병렬 |
| | FUSE_REREAD | MAX=3, DPI=120, P3=0 | reread 위치 재판독 |
| **구조화** | EMBED_BATCH / CONCURRENCY | 32 / 6 | 문서별 병렬 호출 |
| | BM25_THREADS | 3 | term 병렬 선계산 |
| | 구조화 워커 | 1 스레드 | 문서 경계 없이 연속 |
| **기동** | PYTHONDONTWRITEBYTECODE=0, PYTHONPYCACHEPREFIX=/tmp/pycache | import 시간 단축 | 0.5s→0.08s 실측 |
| **MCP 우선** | 감시 방식 | mcp_parse/jobs/ 5초 폴링 (공유 볼륨 mtime) | medium 일시 pause |

---

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
| 10-23 (I2) | 이미지 배치가 `data_etl/`로 바뀜 | 리팩토링 I2(`data_parsing`·`data_structure` → `data_etl`) | `docker exec … python -m data_etl.…`로 명령 이름만 바꿈 — 새 이미지 판과 같은 때에 교체([`docs/operations/release-and-patch.md`](../operations/release-and-patch.md) §5-2) |
| 10-26 (I3) | 옛 이미지·코드 폴더로 돌면 중간에 실패 | 이미지·코드 폴더·러너 판이 어긋날 수 있음 | 시작할 때(EDW 접속 전) 코드 폴더·컨테이너 배치 확인 → 어긋나면 종료 코드 2 |
| 10-26 (I4) | 코드 폴더 확인이 쓰이지 않던 `patch_code/app/deploy`를 봄 · MCP 작업 폴더가 서버 절대 경로로 박힘 | `DEPLOY`·`IMAGE`는 처음부터 미사용 상수 · 경로 하드코딩 | 확인은 env `PATCH_CODE`(기본 `/srv/rag/code/live`, compose와 같음) — 호스트에서 안 보이면 건너뛰고 컨테이너 확인만 · `DEPLOY`·`IMAGE` 지움 · env `MCP_JOBS_DIR`(기본 `test_space/rfp_all_output/mcp_parse/jobs`, 이 파일 기준) |
| 10-26 (I4b) | 코드 폴더가 없어도 컨테이너 확인이 통과할 수 있음(V4 R2) | docker는 bind 마운트 원본이 없으면 빈 폴더를 만들어 붙여 `test -d /app/deploy/data_etl`이 통과 | 확인을 파일로 — 컨테이너 `test -f /app/deploy/data_etl/extract/run_all.py`, 코드 폴더도 같은 파일(`CODE_MARKER`) · 빈 폴더면 종료 코드 2 |
| 10-26 (S4) | 이미지 배치가 `pipeline/`으로 바뀜 · 컨테이너 안 `docflow_probe.py` 자리 | 리팩토링 S4(`data_etl/` → `pipeline/`, `docflow_probe.py`는 저장소 루트 → `pipeline/extract/` — 이미지에 함께 들어감, T-14) | `python -m pipeline.…`·`pipeline.cli`로 명령 이름만 바꿈 · `CODE_MARKER` = `pipeline/extract/run_all.py` · 무게 판별은 `python3 /app/deploy/pipeline/extract/docflow_probe.py` — 새 이미지 판과 같은 때에 교체(`refactor.md` C-23) |
| 10-27 (S6b) | 러너 자리·컨테이너 이름이 바뀜 | 리팩토링 S6b(D-020·D-026 — 파이프라인 이미지 합침 `data-pipeline`, 이름 사용자 10-27) | 저장소 자리 `run_script/run_docs.py` → `deploy/host/scripts/run_docs.py`(`test_space/`는 스크립트 옆 그대로) · docker exec·inspect 대상 `data-parsing`·`data-structure` → `data-pipeline-parse`·`data-pipeline-structure`(상수 `PARSE_C`·`STRUCT_C`) — 새 이미지 판과 같은 때에 교체(`refactor.md` C-29) |
| 10-28 (S9 Step A) | 문서별 결과 폴더(`PIPE_OUT_ROOT` 등)·채널별 VLM 동시 수·후보정·CPU 게이트가 효과 없음 — 문서별 파싱이 공용 `/app/output`에 쓰고 구조화가 그 결과를 못 찾음(VS8b U-1) | S7e2부터 앱이 env의 옛 설정 이름을 읽지 않는데 러너는 `docker exec … bash -c 'X=값 python …'` env로 줬음(VS7e3 셸 스캔은 `.sh`·compose만 보고 Python 문자열 안 셸 명령은 안 봄 — 로컬 실행 금지라 실행 확인도 없었음) | 설정 칸은 명령 인자 `--set 이름=값`(`common.config.setarg` — 사용자 10-28, 비밀·호스트 칸은 거부)으로 · 명령 줄은 함수(`warm_cmd`·`parse_cmd`·`struct_cmd`·`publish_cmd`·`sweep_cmd`)로 떼어 `tests/general/deploy/test_run_docs.py`가 글자를 고정 · 고아 정리 표지는 env `RUN_DOCS_DOC`(설정 칸 아님) · 구조화는 파싱이 그 문서 폴더에 쓴 엔진 구성 사본을 다시 씀(`stackcfg --path` — VS8b R-1) · `[envcheck]` 줄은 컨테이너 env 대신 준 게이트 값 · 읽는 코드 없는 env 4개(`FIG_OCR_BUDGET`·`*_MASTER_CSV`)는 그대로 |

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

---

## 6. 운영 명령

```bash
# 이어서 실행 (완료 문서 자동 pass)
nohup python3 run_docs.py --filter "rfi,rfp,proposal,question" \
  --start-offset 0 --skip-done --struct-workers 1 \
  >> test_space/batch_progress/runner.log 2>&1 &

# 모니터링
python3 analyze_docflow.py [--detail]
tail -f test_space/batch_progress/progress.log
tail -5 test_space/batch_progress/cpu_mem_trend.csv

# 조정 노브
--cpu-gate 1.1        # 게이트 조정값
--workers 5           # 총 워커 수
--seqs "141,237"      # 특정 문서만
--limit 20            # 시험용
```

---

## 7. 남은 과제

1. **light 슬롯 대기 247s** — light 68% demand vs 1 lane. light 2 + medium 1 (총 5) 또는 steal 정책 조정 검토
2. **vlm 슬롯 대기 969s** — vlm lane 1이 222s/건 처리. VLM_CAP=3으로 상향 검토
3. **CPU 68%** — 목표 밴드(75~85%) 하회. 워커 5개로 증설 여지
4. **실패 6건** (seq 586,888,960-962,1198) — 재시도해도 계속 실패. 원인 별도 분석 필요
5. **MCP pause 실측** — 실제 MCP 업로드 발생 시 medium pause 동작 검증
