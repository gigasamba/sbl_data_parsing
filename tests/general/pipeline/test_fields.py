"""pipeline.extract.engines._common.fields(엔진 공용 파일 — 엔진 지문 27개 모두) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.extract.engines._common.fields`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

from pipeline.extract.engines._common.fields import normalize_facts


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검` 몸통
    t = normalize_facts(
        [
            {"value": "USD 85 / g (표준가 대비 5% 할인 반영)", "context": ["단가"]},
            {"value": "USD 42,000,000 (확정 8 batches × 배치당 약 USD 5.2M 기준)", "context": ["총 계약 금액"]},
            {"value": "연 2 batches (계약 기간 누적 최소 6 batches)", "context": ["MTOP"]},
            {
                "value": "% per annum 0.03 PPI 연동 상한",
                "context": ["Price adjustment cap"],
                "cells": ["% per annum", "0.03", "PPI 연동 상한"],
            },
            {"value": "없음", "context": ["Price adjustment waivers"]},
        ]
    )
    assert t["proposed_price"]["value"] == 85 and t["proposed_price"]["unit"] == "USD/g"
    assert t["proposed_price"]["qualifiers"]["discount_pct"] == 5
    w = normalize_facts(
        [
            {"value": "간없음", "context": ["Price adjustment waiver 기"]},
            {"value": "1 batch / year (패널티 없음)", "context": ["Reserve batch"]},
            {"value": "2 (연간, 추가 할인 없음)", "context": ["MTOP"]},
        ]
    )
    assert w["price_adjustment_waivers"]["value"] == 0  # 라벨 넘침 잡음('간없음')
    assert w["reserve_batch"]["value"] == 1  # 숫자가 있으면 '없음'에 끌려가지 않음
    assert w["mtop"]["value"] is None  # 숫자는 있으나 단위 불명 → 0으로 오판하지 않고 미판정
    s = normalize_facts([{"value": "yes/no No", "context": ["Shared MTOP"], "cells": ["yes/no", "No"]}])
    assert s["shared_mtop"]["value"] is False  # 단위 열 'yes/no'를 값으로 읽던 버그 회귀
    p = normalize_facts([{"value": "USD 320 / g (list 기준, 할인 미적용)", "context": ["제안 단가"]}])
    assert p["proposed_price"]["value"] == 320 and p["proposed_price"]["qualifiers"]["discount_pct"] == 0
    assert t["contract_value"]["value"] == 42_000_000 and t["contract_value"]["unit"] == "USD"
    assert t["mtop"]["value"] == 2 and t["mtop"]["qualifiers"]["cumulative_min_batches"] == 6
    assert t["price_adjustment_cap"]["value"] == 3 and t["price_adjustment_waivers"]["value"] == 0
    print("fields self-check OK")
