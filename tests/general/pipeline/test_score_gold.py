"""pipeline.eval.score_gold 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.score_gold --selftest`."""

import json
import tempfile
from pathlib import Path

from common.config import settings as C
from pipeline import config as pc
from pipeline.eval.score_gold import (
    HAS_RAPIDFUZZ,
    _num_key,
    _table_judge_fn,
    _tcell_match,
    canon,
    canon_gold,
    load_gold,
    load_spec_must_not,
    md_tables,
    mermaid_recall,
    metrics,
    must_not_hits,
    score,
    scored,
    summary_html,
    summary_md,
    table_struct,
)


def selftest():
    """가짜 파싱 결과(엔진 2개 + _rep)와 정답 txt·values.csv로 지표·이름 맞추기·선택 일치를 확인."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pd, gd = d / "parse", d / "gold"
        for p in (pd / "pymupdf", pd / "rapidocr_ko", pd / "_rep", gd):
            p.mkdir(parents=True)
        doc = "Quote 2026.pdf"
        good = "견적서\n| 품목 | 단가 |\n| 필터 | 1,250,000 |\n납기 30일"
        bad = "견적서\n품목 단가\n필터 1.250.000\n납기 3O일 999"
        runs = [
            {"doc": doc, "engine": "pymupdf", "error": None, "sec": 0.1, "phase": 1},
            {"doc": doc, "engine": "rapidocr_ko", "error": None, "sec": 1, "phase": 1},
        ]
        (pd / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs), encoding="utf-8")
        (pd / "pymupdf" / f"{doc}.json").write_text(json.dumps({"text": good}), encoding="utf-8")
        (pd / "rapidocr_ko" / f"{doc}.json").write_text(json.dumps({"text": bad}), encoding="utf-8")
        (pd / "_rep" / f"{doc}.json").write_text(json.dumps({"text": good, "rep": {"engine": "pymupdf"}}), encoding="utf-8")
        (gd / "quote_2026.md").write_text(good, encoding="utf-8")  # 이름: 공백·밑줄·대소문자 달라도 맞춤
        (gd / "values.csv").write_text("문서,라벨,값\nQuote 2026.pdf,납기,30일\n", encoding="utf-8")
        (gd / "없는문서.txt").write_text("x", encoding="utf-8")
        res = score(pd, d / "none", gd)
        r = res["docs"][doc]
        assert r["engines"]["pymupdf"]["value_recall"] == 1.0 and r["engines"]["pymupdf"]["char_acc"] == 1.0, r
        assert r["engines"]["rapidocr_ko"]["value_recall"] < 1.0 and r["engines"]["rapidocr_ko"]["num_halluc"] > 0, r
        assert r["engines"]["pymupdf"]["table_cell_recall"] == 1.0
        assert r["best_engine"] == "pymupdf" and r["rep_is_best"] and res["rep"]["selection_match"] == 1.0
        assert res["unmatched_gold"] == ["없는문서.txt"]
        md = summary_md(res, {doc: "doc-x"})
        assert "doc-x" in md and doc not in md  # 요약에 원래 이름 안 나옴
        assert md_tables("a\n| x | y |\n|---|---|\n| 1 | 2 |\nb") == [[["x", "y"], ["1", "2"]]]
        assert "<table>" in summary_html(md) and doc not in summary_html(md)
    # 같은 이름의 .docx·.pdf — 확장자까지 적은 정답은 각각 맞고, 확장자 없는 정답은 모호로 보고
    with tempfile.TemporaryDirectory() as td2:
        g2d = Path(td2)
        (g2d / "spec.docx.md").write_text("a", encoding="utf-8")
        (g2d / "spec.pdf.md").write_text("b", encoding="utf-8")
        (g2d / "spec.md").write_text("c", encoding="utf-8")
        tr, um = load_gold(g2d, ["spec.docx", "spec.pdf"])
        assert set(tr) == {"spec.docx", "spec.pdf"} and tr["spec.pdf"]["text"] == "b", (tr, um)
        assert len(um) == 1 and "같은 이름 2개" in um[0], um
    # 정규화: Symbol 글꼴 ≥ · 첨자 · 대시 · 전각 % · 특수 공백
    assert canon("\uf0b3 1.0\u00d710^6 cells") == canon("≥ 1.0×10⁶ cells") == ">= 1.0x106 cells"  # SI47: × → x · ≥ → >=
    assert canon("CO_2 5\uff05") == canon("CO₂ 5%") == "CO2 5%"
    assert canon("B\u20131") == canon("B\u22121") == "B-1" and canon("a\u00a0b") == "a b"
    # SI47 \u2014 ASCII\ub85c \uace0\uccd0 \uc4f4 \uc0ac\ub78c \uc815\ub2f5\uacfc \uac19\uc740 \uaf34(\uc591\ucabd \uc811\uae30)
    assert (
        canon("\u201c1.0\u00d710\u201d \u2192 \u2022 \uc644\ub8cc")
        == canon('"1.0x10" -> * \uc644\ub8cc')
        == canon("1.0x10 -> \uc644\ub8cc")
        == "1.0x10 -> \uc644\ub8cc"
    )
    assert canon("2*3") == "2*3" and canon("Pfizer\u2019s") == canon("Pfizer's") == "Pfizers"
    assert (
        canon("원료·부자재") == canon("원료, 부자재") == canon("원료/부자재") == canon("원료 부자재") == "원료 부자재"
    )  # 가운뎃점 = 콤마(10-09)
    assert canon("1.5, 2,000") == "1.5, 2,000"  # 숫자 사이 구분은 그대로
    assert canon("완료.\n다음 문단") == "완료.\n다음 문단"  # 줄바꿈은 지키기(order 지표)
    assert len({canon("AB.CD"), canon("AB/CD"), canon("AB,CD")}) == 3 and canon("Seed·Harvest") == canon(
        "Seed, Harvest"
    )  # 영문 ID 구분자는 그대로, 가운뎃점만 콤마
    assert (
        canon("5'2\" height") == "5'2\" height"
        and canon("100'") == "100'"
        and canon("'\ud488\uc9c8 \uae30\uc900'") == "\ud488\uc9c8 \uae30\uc900"
    )  # \ud504\ub77c\uc784 \ubcf4\uc874
    assert canon_gold({"text": "", "values": ["\uc644\ub8cc."], "tables": [[["A\u00d7B."]]]}) == {
        "text": "",
        "values": ["\uc644\ub8cc"],
        "tables": [[["AxB"]]],
    }
    g = {"text": "", "values": [{"value": "≥ 1.0×10^6"}], "tables": [[["CO₂", "5%"]]]}
    o = {"text": "\uf0b3 1.0\u00d710\u2076\nCO_2 5\uff05"}
    m = scored(g, o)
    assert m["value_recall"] == 1.0 and m["table_cell_recall"] == 1.0 and m["raw_value_recall"] == 0.0, m
    assert canon("1.0×10<sup>6</sup> &amp; CO<sub>2</sub><br>a") == "1.0x106 & CO2 a"
    # 독립 검토 MAJOR 2 — 각주형(마커 앞뒤가 영숫자가 아닌 경우)도 옛 동작처럼 마커가 안 남아야 함
    assert canon("값: <sup>6</sup>") == "값: 6" and canon("(참고 <sup>a</sup>)") == "(참고 a)" and canon("<sup>6</sup>항목") == "6항목"
    g2 = {"text": "", "values": [], "tables": [[["Product code", "GSK011 PUS"], ["Infliximab 100 mg", "≥ 95%"]]]}
    o2 = {
        "text": "{Product code, GSK011\nPUS}\n{Infliximab 100\nmg, \uf0b3 95%}"
    }  # 칸이 줄바꿈으로 갈리고 {,,} 형식 — 칸은 맞고 행 구조만 깨짐
    m2 = scored(g2, o2)
    assert m2["table_cell_recall"] == 1.0 and m2["table_cell_token_recall"] == 1.0 and m2["table_row_recall"] == 0.0, m2
    o3 = {"text": "Product Infliximab code 100 GSK011 mg\nPUS \uf0b3 95%"}  # 다열이 섞여 읽힘 — 엄격은 놓치고 느슨은 잡음
    m3 = scored(g2, o3)
    assert m3["table_cell_token_recall"] == 1.0 and m3["table_cell_recall"] < 1.0, m3
    if HAS_RAPIDFUZZ:  # SI24 — 부분 정답(앞부분만)은 출력 나머지를 벌점으로 안 셈 · 전체 정답이면 예전 CER 그대로
        body = "본문 첫 문단 단가 430,000원 수량 12개 " + "뒤쪽 본문이 길게 이어짐 " * 20
        mp = metrics({"text": "본문 첫 문단 단가 430,000원", "values": [], "tables": []}, {"text": body})
        assert mp["gold_partial"] and mp["char_acc"] == 1.0 and mp["char_acc_full"] < 0.5, mp
        mf = metrics({"text": body, "values": [], "tables": []}, {"text": body})
        assert "gold_partial" not in mf and mf["char_acc"] == 1.0, mf
    hs = {"a": {0, 1}, "b": {1, 2}}  # 구제 집계 규칙 — a만 0, b만 2
    assert {e: len(h - set().union(*[x for k, x in hs.items() if k != e])) for e, h in hs.items()} == {"a": 1, "b": 1}
    print(
        "[selftest] score_gold — 이름 맞추기·지표·선택 일치·이름 해시·정규화(기호·첨자·대시·%·공백·HTML 태그)·표 칸 엄격/느슨·HTML·부분 정답 글자 정확도 통과"
    )

    # TS1 — 표 구조 재현율: 같은 md 표 → 1.0 · 한 칸씩 줄로 풀려도 tables[]/grid 있으면 여전히 0.0(TA1 회귀를 score_gold만으로 재현)
    gold_md = "| 품목 | 단가 |\n| 필터 | 1,250,000 |\n| 펌프 | 980,000 |"
    same_md = "견적서\n" + gold_md
    assert table_struct(gold_md, same_md)["table_struct_recall"] == 1.0
    flat_body = {
        "text": "견적서\n품목 단가\n필터 1,250,000\n펌프 980,000",
        "tables": [
            {"text": "품목 단가\n필터 1,250,000\n펌프 980,000", "grid": [["품목", "단가"], ["필터", "1,250,000"], ["펌프", "980,000"]]}
        ],
    }
    ts_flat = table_struct(gold_md, flat_body["text"])  # table_struct는 text만 받음 — tables[]/grid를 아예 보지 않음(인자 자체에 없음)
    assert ts_flat["table_struct_recall"] == 0.0, ts_flat
    assert table_struct("본문만, 표 없음", same_md) == {
        "table_struct_recall": None,
        "table_struct_tables": None,
        "table_struct_judged": 0,
    }  # 정답에 표 없으면 None
    # 칸 2개 미만 행은 빼고 비교 · 사소한 표기 차이(쉼표 없음)는 허용 · 값이 다른 행으로 옮겨가면 매칭 깨짐
    gold_md2 = "| 제목만 |\n| 품목 | 단가 |\n| 필터 | 1250000 |"
    assert table_struct(gold_md2, "| 품목 | 단가 |\n| 필터 | 1,250,000 |")["table_struct_recall"] == 1.0  # 쉼표 차이 허용(정규화)
    assert (
        table_struct(gold_md2, "| 품목 | 펌프 |\n| 단가 | 1,250,000 |")["table_struct_recall"] == 0.0
    )  # 값이 다른 행(칸 짝)으로 옮겨감 — 매칭 깨짐
    # 2단 머리글(출력에 머리글 역할 줄이 하나 더 있어도 데이터 행 매칭은 안 깨짐) — 모든 출력 행을 한 풀로 모아 비교
    two_level = "| 견적 | 견적 |\n| 품목 | 단가 |\n| 필터 | 1,250,000 |"
    assert table_struct(gold_md, two_level)["table_struct_recall"] == round(2 / 3, 4)  # 품목·단가 2행 매칭, 펌프 행은 없음
    # table_struct_tables — 표 하나 단위 ≥50% 매칭 비율
    assert table_struct(gold_md, "| 품목 | 단가 |\n| 필터 | 1,250,000 |")["table_struct_tables"] == 1.0  # 2/3 매칭 ≥ 0.5
    # SCORE_TABLE_JUDGE=llm — 경계 표(2/3=0.67, TABLE_JUDGE_LO~HI 안)만 판정자가 승격 가능, 기본(judge=None)은 안 바뀜
    border_out = "| 품목 | 단가 |\n| 필터 | 1,250,000 |"
    assert table_struct(gold_md, border_out, judge=lambda g, o: True)["table_struct_recall"] == 1.0
    assert table_struct(gold_md, border_out, judge=lambda g, o: True)["table_struct_judged"] == 1
    assert table_struct(gold_md, border_out, judge=lambda g, o: False)["table_struct_recall"] == round(
        2 / 3, 4
    )  # 판정자가 거부하면 결정적 결과 그대로
    print(
        "[selftest] score_gold TS1 — 표 구조 재현율(md 표 일치·tables[]/grid 무시·표 없는 정답 None·2단 머리글·경계 판정자 승격/거부) 통과"
    )

    # 독립 검토(9cc7465a) 지적 1 — 숫자 칸은 fuzzy 대신 정확한 수치 일치만(자릿수 하나 다른 큰 수가 ratio>=90로 통과하던 문제)
    assert _tcell_match(("1234567890123", _num_key("1234567890123")), ("1234567890124", _num_key("1234567890124"))) is False
    assert table_struct("| 계약 A | 1234567890123 |", "| 계약 A | 1234567890124 |")["table_struct_recall"] == 0.0
    assert _tcell_match(("1.20", _num_key("1.20")), ("1.25", _num_key("1.25"))) is False
    assert table_struct("| 순도 | 1.20 |", "| 순도 | 1.25 |")["table_struct_recall"] == 0.0
    assert _tcell_match(("1,000", _num_key("1,000")), ("1000", _num_key("1000"))) is True  # 쉼표만 다르면 그대로 같음
    assert table_struct("| 항목 | 금액 |\n| 필터 | 1,000 |", "| 항목 | 금액 |\n| 필터 | 1000 |")["table_struct_recall"] == 1.0
    # 독립 검토 지적 2 — 라벨 행(합계·Total)이 무관한 다른 표의 같은 라벨 행과 우연히 맞아떨어지면 안 됨(검토자 재현: 0/3 → 1/3)
    label_gold = "| 필터 | 1,000 |\n| 펌프 | 2,000 |\n| 합계 | 1,000 |"  # 마지막이 합계(값은 우연히 필터와 같음)
    unrelated_out = "| 세금 | 2,000 |\n| 합계 | 1,000 |"  # 무관한 표 — 필터·펌프는 없고 합계만 우연히 같음
    ts_label = table_struct(label_gold, unrelated_out)
    assert ts_label["table_struct_recall"] == 0.0 and ts_label["table_struct_tables"] == 0.0, ts_label
    corroborated_out = "본문\n" + label_gold  # 같은 표 전체가 그대로 있으면(다른 행도 매칭) 합계 행도 인정
    assert table_struct(label_gold, corroborated_out)["table_struct_recall"] == 1.0
    # 독립 검토 지적 3 — 정답에 표는 있지만 비교할 행이 하나도 없으면(전부 제목·구분 줄) None이 아니라 0.0
    assert table_struct("| 제목만 |\n| 또 다른 제목만 |", "아무 본문") == {
        "table_struct_recall": 0.0,
        "table_struct_tables": 0.0,
        "table_struct_judged": 0,
    }
    print("[selftest] score_gold TS1 독립 검토 — 숫자 칸 정확 일치·라벨 행 corroboration·표는 있지만 행 없으면 0.0 통과")

    # TS1 c) — mermaid edge 재현율: 같은 edge → 1.0 · 정답에 mermaid 없으면 None
    gm = "```mermaid\nflowchart LR\n  A[접수] --> B[검토]\n```"
    assert mermaid_recall(gm, "본문\n" + gm) == 1.0
    assert mermaid_recall(gm, "본문만, mermaid 없음") == 0.0
    assert mermaid_recall("mermaid 없는 정답", gm) is None
    print("[selftest] score_gold TS1 c) — mermaid edge 재현율(일치·빠짐·정답 없음) 통과")

    # SCORE_TABLE_JUDGE — env 게이트(기본 0=없음·llm만 켬·NO_PAID_CALLS=1이면 llm.chat의 내부망 가드가 그대로 집행)
    # S7c — 시험은 설정 객체에 겹쳐 씀(os.environ 안 건드림 — pipeline 칸은 PIPE, common 칸 LLM_FAKE는 COMMON)
    with pc.PIPE.env(SCORE_TABLE_JUDGE=None):
        assert _table_judge_fn() is None  # env 미설정
    with pc.PIPE.env(SCORE_TABLE_JUDGE="llm"):
        judge_fn = _table_judge_fn()
        assert judge_fn is not None
        with C.COMMON.env(LLM_FAKE="1"):  # 네트워크 0 — fake_reply가 JSON이 아니므로 parse_json 실패 → False(승격 안 함, 조용히 거부만)
            assert judge_fn([["품목", "단가"]], [["품목", "단가"]]) is False
    with pc.PIPE.env(SCORE_TABLE_JUDGE=None):
        assert _table_judge_fn() is None  # SCORE_TABLE_JUDGE 비우면 다시 없음(복원 확인)
    with pc.PIPE.env(SCORE_TABLE_JUDGE="vlm"):  # vlm은 아직 TODO — 결정적 결과로 대체(문서화, 이번 범위 밖)
        assert _table_judge_fn() is None
    print("[selftest] score_gold TS1 — SCORE_TABLE_JUDGE 게이트(기본 없음·llm 켬·LLM_FAKE 경로·vlm TODO) 통과")

    # W20① — spec.json must_not(금지 값) 위반 — value_recall과 같은 정규화·비교
    assert load_spec_must_not(None) == {} and load_spec_must_not("") == {}
    with tempfile.TemporaryDirectory() as tdm:
        specd = Path(tdm)
        spec = {"documents": [{"file": "a.pdf", "must_not": ["3,360,000", "2023년"]}, {"file": "b.pdf", "must_not": []}]}
        (specd / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        mn = load_spec_must_not(specd)
        assert mn == {"a.pdf": ["3,360,000", "2023년"]}, mn  # must_not 빈 문서(b.pdf)는 칸 안 둠
        assert load_spec_must_not(specd / "없음") == {}  # spec.json 없으면 빈 dict
        assert must_not_hits([], {"text": "아무거나"}) == []
        assert must_not_hits(mn["a.pdf"], {"text": "본사 계약 금액 3360000 USD, 2023년 실험."}) == [
            "3,360,000",
            "2023년",
        ]  # 쉼표 무시(value_recall과 같은 정규화)
        assert must_not_hits(mn["a.pdf"], {"text": "2026년 계약, 금액은 다름."}) == []  # 금지 값이 없으면 빈 목록

        # score() --spec 연동: 사람 정답이 없는 문서(합성 세트)도 위반만 집계되고, 기존 대표·엔진 평균은 안 건드림
        pd2, gd2 = specd / "parse", specd / "gold"
        for p in (pd2 / "eng1", pd2 / "_rep", gd2):
            p.mkdir(parents=True)
        runs2 = [{"doc": "a.pdf", "engine": "eng1", "error": None, "sec": 0.1, "phase": 1}]
        (pd2 / "runs.jsonl").write_text(json.dumps(runs2[0]), encoding="utf-8")
        (pd2 / "eng1" / "a.pdf.json").write_text(json.dumps({"text": "본사 계약 금액 3,360,000 USD"}), encoding="utf-8")
        (pd2 / "_rep" / "a.pdf.json").write_text(
            json.dumps({"text": "본사 계약 금액 3,360,000 USD", "rep": {"engine": "eng1"}}), encoding="utf-8"
        )
        res_spec = score(pd2, specd / "none-src", gd2, spec_dir=specd)
        assert res_spec["docs"] == {}, res_spec["docs"]  # 사람 정답 없음 — 기존 out["docs"] 그대로 빔
        assert res_spec["must_not_docs"]["a.pdf"]["rep"]["must_not_violations"] == ["3,360,000"], res_spec["must_not_docs"]
        assert res_spec["must_not_violations_total"] == 1, res_spec
        md_spec = summary_md(res_spec, {})
        assert "금지 값 위반" in md_spec and "| a.pdf | eng1 | — | — | — | — | — | 1 |" in md_spec, md_spec

        res_nospec = score(pd2, specd / "none-src", gd2)  # --spec 안 주면 기존과 바이트 동일(새 키 자체가 없음)
        assert "must_not_docs" not in res_nospec and "must_not_violations_total" not in res_nospec, res_nospec
        assert "금지 값 위반" not in summary_md(res_nospec, {})
    print("[selftest] score_gold W20① — must_not 위반(정규화 공유·--spec 분리 집계·기존 출력 바이트 불변) 통과")
    return 0


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
