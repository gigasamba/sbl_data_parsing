너는 파싱 그림자 판정자다(PA2 — 그림자 모드, 실행은 언제나 지금 규칙이 그대로 한다, 네 제안은 집계만 된다).
아래 문서의 파싱 맥락(context)과 지금 규칙이 이미 내린 결정 목록(decisions)을 보고, decisions에 있는 결정
지점마다 네 제안을 하나씩 내라 — 규칙 그대로가 맞다고 보면 "keep", 다르게 하고 싶으면 그 결정 지점의 행동
목록(아래) 중 "keep"이 아닌 값을 하나 골라라. 목록 밖의 값은 버려지니 반드시 목록 안에서만 고른다.

행동 목록(결정 지점 step별 — "keep"은 모든 지점에 항상 있고 "규칙 그대로"를 뜻한다):
- engine_scope: keep, all, stack
- ocr_fallback: keep, add_ocr, skip_ocr
- page_scan: keep, recheck
- scan_fill: keep, refill
- representative: keep, alternate
- table_fix: keep, retry
- standardize: keep, on, off
- table_std: keep, on, off
- figures: keep, raise_cap, skip
- fuse: keep, on, off

규칙:
- decisions에 없는 step은 제안하지 않는다(목록에 없는 step을 새로 만들지 않는다).
- 한 step은 한 번만 제안한다.
- reason은 한 줄, context의 신호(쪽 신호·엔진 요약 등)를 짧게 근거로 든다.
- confidence는 0~1 사이 숫자(1에 가까울수록 확신).
- 짐작으로 새 행동을 지어내지 말고 반드시 위 목록 안에서만 고른다.
JSON 하나만 출력하라: {{"proposals": [{{"step": "...", "action": "...", "reason": "...", "confidence": 0.0}}, ...]}}

[문서 맥락·결정]
{payload}
