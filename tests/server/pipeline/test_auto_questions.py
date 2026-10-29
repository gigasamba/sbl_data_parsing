"""pipeline.eval.auto_questions 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.auto_questions --selftest`."""

from pipeline.eval.auto_questions import (
    _contract,
    _garbled_doc,
    _lev1,
    confirmed_qty,
    gen,
    locate_value,
    pairs_of,
    title_client,
    trivial_label,
)


def selftest():
    d = {
        "text": "계약 번호: D-1\n고객사: 가나바이오\n단가: USD 10 / g\n품목 | 수량 (L)\nA-1 정제 | 3,000",
        "facts": [{"context": ["품목"], "cells": ["수량 (L)", "비고"]}, {"context": ["A-1 정제"], "cells": ["3,000", "A"]}],
    }
    ps = pairs_of(d)
    assert ("A-1 정제 / 수량 (L)", "3,000") in ps and ("고객사", "가나바이오") in ps, ps
    loc = locate_value(d["text"], "3000", "A-1 정제")
    assert loc and loc["line"] == 5, loc
    info = {"outs": {"x": d, "y": {"text": d["text"], "facts": []}}, "ref": "x", "fam": {"x": "fx", "y": "fy"}}
    assert confirmed_qty(info, 2) == [("A-1 정제 / 수량 (L)", "3,000", "L")], confirmed_qty(info, 2)
    assert _lev1("d-2024-132", "d-2024-182") and not _lev1("d-2024-132", "d-2024-190")
    info["fam"]["y"] = "fx"  # 같은 계열이면 확인 안 됨
    assert confirmed_qty(info, 2) == []
    print("[selftest] 교차 확인 쌍·표 수량·근거 위치 통과")

    # E12 — 글자 깨진 메일(cp949→utf-8 오해석 mojibake) 1건 + 정상 메일 1건: 깨진 쪽만 '미확인 문서'로 표시, 정상은 그대로
    normal_text = "계약 번호: D-2024-100\n고객사: 노스필드바이오\n단가: USD 10 / g"
    bad_clean = "계약 번호: D-2024-270\n노스필드바이오 담당자님께, 단가 문의드립니다."
    bad_garbled = bad_clean.encode("cp949").decode("utf-8", "replace")  # 실측 흔한 한글 메일 인코딩 오해석 재현
    assert "�" in bad_garbled and "노스필드바이오" not in bad_garbled, bad_garbled  # 고객명도 같이 깨짐 확인
    confirmed_pairs = [
        {"label": "계약 번호", "value": "D-2024-100", "fams": 2},
        {"label": "고객사", "value": "노스필드바이오", "fams": 2},
        {"label": "단가", "value": "USD 10 / g", "fams": 2},
    ]
    normal_doc = {
        "format": ".eml",
        "ref": "mhtml",
        "text": normal_text,
        "outs": {"mhtml": {"text": normal_text, "facts": []}, "kreuzberg": {"text": normal_text, "facts": []}},
        "fam": {"mhtml": "fam_mhtml", "kreuzberg": "fam_kreuz"},
        "pairs": confirmed_pairs,
        "all": confirmed_pairs,
    }
    bad_doc = {
        "format": ".eml",
        "ref": "mhtml",
        "text": bad_clean,
        "outs": {"mhtml": {"text": bad_clean, "facts": []}, "kreuzberg": {"text": bad_garbled, "facts": []}},
        "fam": {"mhtml": "fam_mhtml", "kreuzberg": "fam_kreuz"},
        "pairs": [],
        "all": [{"label": "계약 번호", "value": "D-2024-270", "fams": 1}],
    }

    qs_normal = gen({"normal.eml": normal_doc}, 10, 0, 2)
    r_normal = qs_normal["count"][0]
    assert "unverified_docs" not in r_normal and r_normal["gold_source"] == "자동(교차 확인 2계열 이상)", (
        r_normal
    )  # 정상 메일은 바이트 동일

    qs_mixed = gen({"normal.eml": normal_doc, "mail_bad.eml": bad_doc}, 10, 0, 2)
    r_mixed = next(r for r in qs_mixed["count"] if r["client"] == "노스필드바이오")
    assert r_mixed["answer"] == 1 and r_mixed["unverified_docs"] == ["mail_bad.eml"], r_mixed  # 집계는 그대로(확정 아닌 값은 안 더함)
    assert "미확인 문서" in r_mixed["gold_source"], r_mixed["gold_source"]
    print("[selftest] E12 글자 깨진 메일 '미확인 문서' 표시 통과")

    # E12 독립 검토 MAJOR — 메일이 아닌 형식(OCR 노이즈 섞인 스캔 PDF)은 글자가 깨져도 대상이 아님(오표시 방지)
    noisy_text = "\x0b\x0b��� 노\n이\n즈\n많은 스캔 OCR 결과"
    pdf_doc = {
        "format": ".pdf_image",
        "ref": "rapidocr_ko",
        "text": "계약 번호: D-2024-900\n노스필드바이오 스캔본",
        "outs": {
            "rapidocr_ko": {"text": "계약 번호: D-2024-900\n노스필드바이오 스캔본", "facts": []},
            "paddleocr": {"text": noisy_text, "facts": []},
        },
        "fam": {"rapidocr_ko": "fam_a", "paddleocr": "fam_b"},
        "pairs": [],
        "all": [{"label": "계약 번호", "value": "D-2024-900", "fams": 1}],
    }
    assert _garbled_doc(pdf_doc) is False, "메일 아닌 형식은 글자 깨짐 판정 대상이 아니어야 함(MAJOR)"
    qs_pdf = gen({"normal.eml": normal_doc, "scan.pdf": pdf_doc}, 10, 0, 2)
    r_pdf = next(r for r in qs_pdf["count"] if r["client"] == "노스필드바이오")
    assert not r_pdf.get("unverified_docs"), r_pdf  # OCR 노이즈 PDF는 '미확인 문서'로 안 붙음
    print("[selftest] E12 메일 아닌 형식(OCR 노이즈 PDF) 오표시 방지 통과")

    # AD34·AD36 A(10-14) — 제목 고객·ID 모양 계약·사소한 라벨·답 둘 제외·compare/latest/list·빠진 계약이 있으면 list·latest 안 만듦
    def contract_doc(cid, product, signed, price, title="Supply Agreement — Pfizer Inc. / {p} ({c})"):
        t = title.format(p=product, c=cid)
        text = f"{t}\nItem | Value\nContract value | 9 USD\nContract ID | {cid}\nProduct | {product}\nSigned | {signed}\nUnit price | {price}\nH3 | 12"
        ps = [
            {"label": k, "value": v, "fams": 2}
            for k, v in (
                ("Contract value", "9 USD"),
                ("Contract ID", cid),
                ("Product", product),
                ("Signed", signed),
                ("Unit price", price),
                ("H3", "12"),
            )
        ]
        return {
            "format": ".pdf_text",
            "ref": "a",
            "text": text,
            "outs": {"a": {"text": text, "facts": []}, "b": {"text": text, "facts": []}},
            "fam": {"a": "fa", "b": "fb"},
            "pairs": ps,
            "all": ps,
        }

    c = {
        "c1.pdf": contract_doc("C-PFE-2022-01", "PFE-MAB-01", "2022-03-01", "220,000 USD"),
        "c2.pdf": contract_doc("C-PFE-2024-02", "PFE-MAB-01", "2024-02-15", "250,000 USD"),
        "c3.pdf": contract_doc("C-PFE-2024-03", "PFE-MAB-02", "2024-06-10", "180,000 USD"),
    }
    assert (
        title_client(c["c1.pdf"], 2)["value"] == "Pfizer Inc." and _contract(c["c1.pdf"]["pairs"])["value"] == "C-PFE-2022-01"
    )  # 'Contract value'가 아니라 ID
    assert trivial_label("H3 / Our response") and trivial_label("FY2028") and not trivial_label("Unit price")
    q = gen(c, 10, 0, 2)
    assert [r["answer"] for r in q["count"]] == [3], q["count"]
    assert q["list"] and q["list"][0]["answer_keywords"] == ["C-PFE-2022-01", "C-PFE-2024-02", "C-PFE-2024-03"], q["list"]
    assert q["latest"] and q["latest"][0]["answer"] == "250,000 USD" and len(q["latest"][0]["docs"]) == 2, q[
        "latest"
    ]  # 같은 제품 중 늦은 체결일
    assert q["compare"] and q["compare"][0]["answer"] in {"C-PFE-2022-01", "C-PFE-2024-02", "C-PFE-2024-03"}
    hi = {"C-PFE-2022-01": 220000, "C-PFE-2024-02": 250000, "C-PFE-2024-03": 180000}
    a_, b_ = q["compare"][0]["question"].split("계약 ")[1].split(" 중")[0].split("와 ")
    assert q["compare"][0]["answer"] == max((a_, b_), key=hi.get), q["compare"]
    assert not any("'H3'" in r["question"] for r in q["value"]), q["value"]  # 표 좌표 라벨은 질문으로 안 씀
    # 고객명도 계약 확인도 못 한 스캔 계약 1건(OCR 1계열) → 어느 고객 것인지 몰라 list·latest 안 만들고 건수엔 미확인 표시
    scan_text = "계약ID| C-PFE-2025-05\n단가| 300,000 USD"
    c["scan.pdf"] = {
        "format": ".pdf_image",
        "ref": "o",
        "text": scan_text,
        "outs": {"o": {"text": scan_text, "facts": []}},
        "fam": {"o": "fo"},
        "pairs": [],
        "all": [{"label": "계약ID", "value": "C-PFE-2025-05", "fams": 1}],
    }
    q = gen(c, 10, 0, 2)
    assert not q["list"] and not q["latest"] and q["compare"], (q["list"], q["latest"])
    assert q["count"][0]["incomplete_docs"] == ["scan.pdf"] and "확인 못 한 계약 문서" in q["count"][0]["gold_source"], q["count"]
    assert not q["count"][0].get("unverified_docs"), q["count"]  # E12 '글자 깨짐' 칸과 섞지 않음
    # 독립 검토(10-14) MAJOR — 약하게 센 계약(계약 번호를 단일 엔진만 읽음)이 있으면 list·latest 안 만듦 · 다른 칸끼리는 비교 안 함
    w = {k: v for k, v in c.items() if k != "scan.pdf"}
    w4 = contract_doc("C-PFE-2025-07", "PFE-MAB-01", "2025-02-01", "260,000 USD")
    w4["pairs"] = [p for p in w4["pairs"] if p["label"] != "Contract ID"]  # 계약 번호는 all(단일 계열)에만
    w4["all"] = w4["pairs"] + [{"label": "Contract ID", "value": "C-PFE-2025-07", "fams": 1}]
    w["c4.pdf"] = w4
    q = gen(w, 10, 0, 2)
    assert q["count"][0]["answer"] == 4 and not q["list"] and not q["latest"], (q["count"], q["list"], q["latest"])
    m = {k: v for k, v in c.items() if k != "scan.pdf"}
    m["c2.pdf"] = {
        **m["c2.pdf"],
        "pairs": [({**p, "label": "Contract amount"} if p["label"] == "Unit price" else p) for p in m["c2.pdf"]["pairs"]],
    }
    for r in gen(m, 10, 0, 2)["compare"]:
        assert "C-PFE-2024-02" not in r["question"], r  # 'Contract amount'(c2)와 'Unit price'(c1·c3)는 짝짓지 않음
    # 같은 질문 글자에 정답이 둘(문서 지칭이 같은 두 문서) → 그 질문은 안 만듦
    dup = {
        k: {
            **contract_doc("C-X-1", "P-1", "2020-01-01", "1 USD", title="Spec sheet"),
            "pairs": [{"label": "Purity", "value": v, "fams": 2}],
            "all": [],
        }
        for k, v in (("d1.pdf", "95%"), ("d2.pdf", "97%"))
    }
    assert not [r for r in gen(dup, 10, 0, 2)["value"] if "Purity" in r["question"]]
    print("[selftest] AD34·AD36 A — 제목 고객·ID 계약·사소한 라벨·답 둘 제외·compare/latest/list·빠진 계약 시 미확인 통과")


def test_main():  # 옛 `if a.selftest:` 갈래(main() 안)
    selftest()


def test_check_truth():  # 10-29 — check_truth의 make_questions import가 맨 이름이라 못 찾던 것(합계·값 유형 대조가 끝까지 도는지)
    import json
    import tempfile
    from pathlib import Path

    from pipeline.eval.auto_questions import check_truth

    truth = {"d1": {"values": [{"value": "100"}], "tables": [[["item", "qty"], ["A", "3"], ["B", "4"]]]}}
    f = Path(tempfile.mkdtemp()) / "truth.json"
    f.write_text(json.dumps(truth), encoding="utf-8")
    qs = {"value": [{"doc": "d1", "answer": "100"}], "sum": [{"doc": "d1", "contract": "C1", "answer": "7"}]}
    res = check_truth(qs, f)
    assert res == {"value": (1, 1), "sum": (1, 1)}, res
