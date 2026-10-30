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
   warm 다운로더 1스레드 ── 20개 선반(진행중 제외) ── probe 분류
        │                       ├ light (68% — 텍스트 형식·소형 문서)
        │                       ├ medium (3% — CPU 집중: 대형 텍스트)
        │                       └ vlm (29% — GPU 집중: 스캔/이미지 다수/pptx)
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  3클래스 레인 워커 (레인마다 전담 1 + 공유 1 = 6)     │
  │  ├─ 전담: 자기 레인 문서만                            │
  │  ├─ 공유: 자기 레인 먼저, 비면 가장 긴 다른 레인       │
  │  ├─ VLM_CAP=2 (vlm 문서 동시 상한 — 전담도)          │
  │  ├─ 구조화 대기 ≥ STRUCT_BACKLOG(구조화×2)면 새 파싱 대기 │
  │  ├─ MCP 우선: mcp_parse/jobs 활동 감지 시 medium 전담 쉼 │
  │  └─ 단일 컨테이너(data-pipeline-parse) + 격리      │
  └─────────────────────────────────────────────────────┘
        │
  구조화+적재 2스레드 (EMBED_BATCH=32 · EMBED_CONCURRENCY=6 · BM25_THREADS=3)
        │
  publish (OS 업로드 + EDW INSERT) → docflow/warm 임시 즉시 삭제
```

---

## 3. 파라미터 (2026-10-23 확정)

| 영역 | 파라미터 | 값 | 근거 |
|---|---|---|---|
| **워커 배분**(10-29 — settings.yaml `pipeline.host.run_docs`) | 레인 워커 | 레인마다 전담 1 + 공유 1(`<레인>_dedicated`·`<레인>_shared`, 총 6) | 사용자 10-29 — 레인 전담 보장 + 남는 워커는 다른 레인 소화(rn-01) |
| | VLM_CAP | 2(`vlm_cap`) | gpu02 예산 (6/doc × 2 = 12동시) |
| | steal 규칙 | 공유 워커만, 자기 레인이 비었을 때 가장 긴 다른 레인 | `pick_lane()` 표 시험 |
| **대기열**(10-29) | 진입(warm) | 20(`warm`, `--warm`이 덮음) | 사용자 10-29 |
| | 중간(파싱 끝·구조화 대기) | 구조화 스레드 × 2(`struct_backlog`, 0 = 없음) — 닿으면 새 파싱 시작 안 함 | 사용자 10-29(rn-02) |
| | 구조화 스레드 | 2(`struct_workers`, `--struct-workers`가 덮음) | |
| | 깊이 기록 | `batch_progress/queue_depth.jsonl` — dispatch·pick·parse_end·struct_put·struct_get마다 한 줄 | rn-02 |
| **게이트** | light | bypass(=9) | light 즉시 소화 |
| | medium/vlm | CPU_GATE=1.3 (조정 시 `--cpu-gate 1.1`) | 목표 밴드 75-85% 대비 |
| **OCR** | 사용 | **전면 OFF** (스캔 PDF만) | rapidocr 엔진 제외, PREPARE_ROTATE=0 |
| | RAPIDOCR_PAGE_WORKERS | 2 | (운영상 남아 있으나 스캔 레인에선 미사용) |
| | OCR_DPI | 120 | 렌더 비용 절감 |
| **VLM** | 문서당 동시 | **6** (vlm class) / 8 (light) | 3vlm×6=글로벌 18 |
| | FIGURES | VLM_FIGURES_MAX=10 (`FIG_OCR_BUDGET`은 읽는 코드가 없어 10-30 지움 — pl-30) | OCR분류 skip → 직접 VLM |
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

## 4·5. 버그 수정 이력 · 속도 개선 성과
[../history/run_docs_history.md](../history/run_docs_history.md)로 옮김(10-30, do-04).

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
# 레인 워커 수는 settings.yaml pipeline.host.run_docs(light/medium/vlm 전담·공유) — --workers는 받기만 하고 안 씀(rn-04)
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
