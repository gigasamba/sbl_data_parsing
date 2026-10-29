"""pipeline.eval.make_questions 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.make_questions --selftest`."""

from collections import Counter

from pipeline.eval.make_questions import build_questions


# ── 자기 점검 ────────────────────────────────────────────────
def selftest():
    truth = {
        "d1.txt": {
            "variant_of": None,
            "values": [
                {"label": "계약 번호", "value": "CT-1", "kind": "id"},
                {"label": "고객사", "value": "가나상사", "kind": "text"},
                {"label": "공급사", "value": "다라물산", "kind": "text"},
                {"label": "단가", "value": "USD 10 / g", "kind": "num"},
                {"label": "유효 기간", "value": "2026-01-01", "kind": "date"},
                {"label": "할인율", "value": "5%", "kind": "num"},
            ],
            "tables": [[["항목", "단가", "수량(L)"], ["A", "USD 10", "1,000"], ["B", "USD 20", "500"]]],
        },
        "d1_rot90.txt": {
            "variant_of": "d1.txt",
            "values": [
                {"label": "계약 번호", "value": "CT-1", "kind": "id"},
                {"label": "고객사", "value": "가나상사", "kind": "text"},
            ],
            "tables": [],
        },
        "d2.txt": {
            "variant_of": None,
            "values": [
                {"label": "계약 번호", "value": "CT-2", "kind": "id"},
                {"label": "고객사", "value": "가나상사", "kind": "text"},
                {"label": "공급사", "value": "마바테크", "kind": "text"},
                {"label": "단가", "value": "USD 30 / g", "kind": "num"},
                {"label": "유효 기간", "value": "2026-06-01", "kind": "date"},
            ],
            "tables": [[["항목", "단가", "수량(L)"], ["A", "USD 30", "2,000"]]],
        },
    }
    rows = build_questions(truth, per_category=8, seed=0)
    by_cat = Counter(r["category"] for r in rows)
    assert by_cat["value"] >= 1, f"value 문항 없음: {by_cat}"
    assert by_cat["client"] >= 1, f"client 문항 없음: {by_cat}"
    assert by_cat["rfi"] >= 1, f"rfi 문항 없음: {by_cat}"
    print(f"[selftest] 유형별 문항 수: {dict(by_cat)}")

    count_row = next(r for r in rows if r["category"] == "count")
    assert count_row["answer"] == 2, f"count(사본 제외 중복 제거) 실패: {count_row}"  # d1·d1_rot90는 같은 계약
    assert set(count_row["docs"]) == {"d1.txt", "d1_rot90.txt", "d2.txt"}, f"count 근거 문서 목록 실패: {count_row}"
    print(f"[selftest] count 사본 중복 제외 확인: {count_row['answer']}건, docs={count_row['docs']}")

    sum_rows = [r for r in rows if r["category"] == "sum" and r.get("client") == "가나상사"]
    assert sum_rows, "가나상사 sum 문항 없음"
    assert abs(sum_rows[0]["answer"] - 3500) < 1e-9, f"sum(d1 1,500 + d2 2,000, 사본 표 중복 없음) 실패: {sum_rows[0]}"
    print(f"[selftest] sum 합계 확인: {sum_rows[0]['answer']}")

    rfi_row = next(r for r in rows if r["category"] == "rfi")
    assert len(rfi_row["key_points"]) >= 3, f"rfi key_points 3개 미만: {rfi_row}"
    print(f"[selftest] rfi key_points 확인: {rfi_row['key_points']}")

    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "문항 id 중복"
    rows2 = build_questions(truth, per_category=8, seed=0)
    assert rows == rows2, "같은 seed인데 결과가 달라짐(결정성 위반)"
    print("[selftest] id 유일성·결정성(seed 고정 재현) 확인")

    print("[selftest] 전부 통과")


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
