"""pipeline.transform.structure.facts 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.facts`."""

from pipeline.transform.structure.facts import contract_facts


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    pairs = [
        {"label": "Contract ID", "value": "C-PFE-2024-03"},
        {"label": "Product", "value": "PFE-MAB-02"},
        {"label": "Signed", "value": "2024-06-10"},
        {"label": "Unit price", "value": "180,000 USD"},
        {"label": "Contract value", "value": "720,000 USD"},
    ]
    cf = contract_facts(pairs, "Supply Agreement · Pfizer Inc. / PFE-MAB-02 (C-PFE-2024-03)", "C-PFE-2024-03")
    assert cf == {
        "product_code": "PFE-MAB-02",
        "modality": "mAb",
        "signed_on": "2024-06-10",
        "unit_price": 180000.0,
        "currency": "USD",
        "amount": 720000.0,
        "batches": 4,
        "values_from": "label",
    }, cf
    garbled = "··· (C-MRH-2023-03) · 2026-03-02 · 2023-01-23 · MRH-BSA-01 · 491,000,000 KRW · 15,712,000,000 KRW"
    g = contract_facts([], garbled + "\nMTOP | 6 batches/year\n·· ·· | 8 batches/year", "C-MRH-2023-03")
    assert (g["batches"], g["signed_on"], g["amount"], g["values_from"]) == (8, "2023-01-23", 15712000000.0, "pattern"), g
    assert contract_facts([], garbled, "C-X") == {}
    d = contract_facts([{"label": "Unit price", "value": "300,000 USD"}, {"label": "Annual volume", "value": "3 batches/year"}], "", None)
    assert (d["amount"], d["values_from"]) == (900000.0, "derived"), d
    print("[selftest] 계약 사실 추출 통과")
