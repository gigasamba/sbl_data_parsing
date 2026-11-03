# 문서별 flow 러너 `run_docs.py`

설계·값·명령의 정본은 PRD에 있다 — 이 파일은 안내만 둔다.

- 입구·대상 고르기·문서별 `--set` 값·기록: [ops.md#pl-10](../prd/ops.md#pl-10)
- 새 문서 판정·새벽 배치: [ops.md#pl-23](../prd/ops.md#pl-23)
- 문서별 순서(파싱 → 게시 → 원본 삭제 → gold): [ops.md#pl-24](../prd/ops.md#pl-24)
- 종료 코드·겹침 잠금·마감: [ops.md#pl-18](../prd/ops.md#pl-18)
- 레인 분류·워커: [ops.md#rn-01](../prd/ops.md#rn-01) · 대기열: [ops.md#rn-02](../prd/ops.md#rn-02) · MCP 양보: [ops.md#rn-03](../prd/ops.md#rn-03)·[ops.md#rn-04](../prd/ops.md#rn-04)

실행 예(서버 호스트에서만 — PC에서는 실행하지 않는다):
```bash
nohup python3 run_docs.py --code <코드 폴더> --start-offset 0 --skip-done >> <작업 폴더>/batch_progress/runner.log 2>&1 &
tail -f <작업 폴더>/batch_progress/progress.log
```
