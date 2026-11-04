"""pipeline.transform.represent.fragment_vote 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.fragment_vote`."""

from pipeline.transform.represent.fragment_vote import (
    _doc_locale_pref,
    _doc_value_graph,
    _graph_bonus,
    engine_kind,
    format_plausibility,
    fuse,
    fuse_facts,
    norm_key,
    trust_weight,
    vote_fragment,
)


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    # engine_kind·trust_weight — 텍스트 레이어 > VLM > OCR(AD26 (a))
    assert engine_kind("pdfplumber") == "text" and engine_kind("pymupdf") == "text" and engine_kind("office") == "text"
    assert engine_kind("rapidocr_ko") == "ocr" and engine_kind("tesseract") == "ocr"
    assert engine_kind("qwen_vlm") == "vlm"
    assert trust_weight("pdfplumber") > trust_weight("qwen_vlm") > trust_weight("rapidocr_ko")
    print("[selftest] engine_kind·trust_weight — text > vlm > ocr 통과")

    # format_plausibility — 깨짐 글 < 멀쩡한 글, 유효 3자리 묶음 > 무효 묶음
    assert format_plausibility("정상 문장 430,000원") > format_plausibility("�" * 10)
    assert format_plausibility("합계 1,520,000") > format_plausibility("합계 4,30,000")
    # AD26 (c) — 로캘 신호 없으면 쉼표·마침표 묶음은 기본 가산이 같다(둘 다 유효한 '묶음 모양')
    assert format_plausibility("430,000") == format_plausibility("430.000")
    # 문서 다수 구분자(locale_pref)와 같은 쪽에 추가 가산 — 두 표기가 신뢰도·형식에서 같을 때 이걸로 갈린다
    assert format_plausibility("430,000", locale_pref=",") > format_plausibility("430,000", locale_pref=".")
    assert format_plausibility("430.000", locale_pref=".") > format_plausibility("430.000", locale_pref=",")
    print("[selftest] format_plausibility — 깨짐·자릿수 묶음·AD26 로캘 신호 통과")

    # _doc_locale_pref(AD26 c) — 문서 다수 구분자, 동률·증거 없으면 None
    docs_comma = {"e": {"facts": [{"context": ["a"], "value": "1,000"}, {"context": ["b"], "value": "2,000"}]}}
    assert _doc_locale_pref(docs_comma) == ","
    # 마침표는 2묶음 이상(1.234.567)만 증거 — 1묶음(2.000)은 소수점과 모양이 같아 집계에서 안 셈(engine-qa ④)
    docs_tie_locale = {"e": {"facts": [{"context": ["a"], "value": "1,000"}, {"context": ["b"], "value": "1.234.567"}]}}
    assert _doc_locale_pref(docs_tie_locale) is None  # 둘 다 1묶음 증거라 동률
    docs_period_single_ignored = {"e": {"facts": [{"context": ["a"], "value": "1,000"}, {"context": ["b"], "value": "0.500"}]}}
    assert _doc_locale_pref(docs_period_single_ignored) == ","  # 0.500(1묶음, 순수 소수로도 보일 수 있음)은 증거에 안 들어가 쉼표가 이김
    print("[selftest] _doc_locale_pref — 다수 구분자·동률 None·마침표 1묶음(소수 모양)은 증거에서 제외 통과")

    # _doc_value_graph·_graph_bonus(AD29 ④ 그래프 타당성 대역) — 서로 다른 라벨에 같은 값이 교차 언급되면 가산
    docs_graph = {"e": {"facts": [{"context": ["a"], "value": "X1"}, {"context": ["b"], "value": "X1"}]}}
    vg = _doc_value_graph(docs_graph)
    assert vg[norm_key("X1")] == 2
    assert _graph_bonus(norm_key("X1"), vg) > 0.0 and _graph_bonus(norm_key("아무값"), vg) == 0.0
    print("[selftest] _doc_value_graph·_graph_bonus — 교차 언급 라벨 수만큼 가산 통과")

    # vote_fragment — 신뢰도 높은 두 엔진(텍스트)이 뭉치면 OCR 혼자보다 이긴다(에이전트 다수결 아님, 신뢰도 가중)
    cands = [
        {"engine": "pdfplumber", "text": "430,000"},
        {"engine": "pymupdf", "text": "430,000"},
        {"engine": "rapidocr_ko", "text": "430.000"},
    ]
    r = vote_fragment(cands)
    assert r["text"] == "430,000" and set(r["engines"]) == {"pdfplumber", "pymupdf"}
    assert r["losers"] and r["losers"][0]["engines"] == ["rapidocr_ko"]
    # 동점이면(한 엔진씩, 신뢰도 같음) 대표 엔진에 가산점 — 안정성(AD29 ⑤)
    cands3 = [{"engine": "pdfplumber", "text": "A"}, {"engine": "office", "text": "B"}]  # 같은 신뢰도(text) 다른 값
    r3 = vote_fragment(cands3, rep_engine="office")
    assert r3["text"] == "B"  # 신뢰도 동점 → 대표 엔진(office) 쪽이 이김
    r3b = vote_fragment(cands3)  # 대표 엔진 없으면 먼저 나온 후보(candidates 순서) 승
    assert r3b["text"] == "A"
    # r3는 tie_bonus(= "기본" 점수에 포함되는 안정화 장치)로 기본 점수부터 갈려 resolved_by="trust"·split=False
    # r3b는 기본 점수도 전체 점수도 동점(아무 신호 없음) → resolved_by=None·split=True(AD26 (f))
    assert r3["split"] is False and r3["resolved_by"] == "trust"
    assert r3b["split"] is True and r3b["resolved_by"] is None
    # 후보 전부 빈 문자열이면 None
    assert vote_fragment([{"engine": "a", "text": ""}, {"engine": "b", "text": "  "}]) is None
    print("[selftest] vote_fragment — 신뢰도 가중 투표·대표 엔진 동점 가산점·빈 후보 None·AD26 split·resolved_by 통과")

    # 신뢰도·형식(=기본 점수) 동점 두 후보 — 용어 사전 가산은 지움(pl-38)
    cands_term = [{"engine": "pdfplumber", "text": "Pfzer"}, {"engine": "office", "text": "Contoso"}]
    r_term_off = vote_fragment(cands_term)
    assert r_term_off["split"] is True and r_term_off["resolved_by"] is None  # 사전 신호 없으면 기본·전체 둘 다 동점
    print(
        "[selftest] vote_fragment — 사전 가산 없음(pl-38 — 대표 결과는 마스터를 읽지 않음): 기본·전체 동점이면 split=True·resolved_by=None 통과"
    )

    # vote_fragment + value_graph(AD29 ④ 그래프 대역) — 기본 점수는 동점, 교차 언급 가산(전체 점수)만 깬다 →
    # 같은 취지로 split=True·resolved_by="heuristic" 유지(대표 텍스트는 X1).
    cands_graph = [{"engine": "pdfplumber", "text": "X1"}, {"engine": "office", "text": "X2"}]
    r_graph_off = vote_fragment(cands_graph)
    assert r_graph_off["split"] is True and r_graph_off["resolved_by"] is None
    r_graph = vote_fragment(cands_graph, value_graph={norm_key("X1"): 2})
    assert r_graph["text"] == "X1" and r_graph["split"] is True and r_graph["resolved_by"] == "heuristic"
    print("[selftest] vote_fragment + value_graph — 대표는 교차 언급 가산 후보로 뽑되 split=True·resolved_by=heuristic로 남음 통과")

    # fuse_facts — 라벨 키로 자리 맞추기(좌표 없이), 숫자 표기가 갈리면(430,000 vs 430.000) 신뢰도 높은 쪽(두 텍스트
    # 레이어 엔진 동의)이 이기고 conflicts에 진 쪽(OCR)이 기록된다. 라벨이 겹치지 않는 조각(품질)은 한쪽에만 있어도
    # 보충된다(엔진이 하나뿐이라 투표가 아니라 그대로 채택 — AD19와 같은 취지).
    docs = {
        "pdfplumber": {"facts": [{"context": ["금액"], "value": "430,000"}, {"context": ["품질"], "value": "A등급"}]},
        "pymupdf": {"facts": [{"context": ["금액"], "value": "430,000"}]},
        "rapidocr_ko": {"facts": [{"context": ["금액"], "value": "430.000"}]},
    }
    facts, conflicts = fuse_facts(docs, "pdfplumber")
    by_label = {f["context"][0]: f for f in facts}
    assert by_label["금액"]["value"] == "430,000" and set(by_label["금액"]["engines"]) == {"pdfplumber", "pymupdf"}
    assert by_label["품질"]["value"] == "A등급" and by_label["품질"]["engines"] == ["pdfplumber"]
    assert len(conflicts) == 1 and conflicts[0]["label"] == "금액" and conflicts[0]["losers"][0]["engines"] == ["rapidocr_ko"]
    assert conflicts[0]["split"] is False and conflicts[0]["resolved_by"] == "trust"  # 신뢰도만으로 확실히 갈렸다(기본 점수 동점 아님)
    print("[selftest] fuse_facts — 라벨 키 자리 맞추기·신뢰도 투표·갈린 자리만 conflicts 기록·split·resolved_by 통과")

    # fuse_facts — AD29 ④ 그래프 대역(문서 내 교차 언급)이 동점을 깨는지.
    # engine-qa 10-08 (1)(2)(5): 교차 언급은 "신뢰도로 이긴 것"이 아니라 보조 신호라 split=True(resolved_by
    # ="heuristic")로 남는다(대표 텍스트만 X1로 뽑힘).
    docs3 = {
        "pdfplumber": {"facts": [{"context": ["금액1"], "value": "X1"}, {"context": ["금액2"], "value": "X1"}]},
        "office": {"facts": [{"context": ["금액1"], "value": "X2"}]},
    }
    _, conf_on = fuse_facts(docs3, None)
    assert conf_on[0]["winner"] == "X1" and conf_on[0]["split"] is True and conf_on[0]["resolved_by"] == "heuristic"
    print("[selftest] fuse_facts — 교차 언급만으로 깬 동점은 split=True·resolved_by=heuristic로 남음 통과")

    # fuse() 전체 — 결정적(두 번 불러도 같은 결과)
    out1, out2 = fuse(docs, "pdfplumber"), fuse(docs, "pdfplumber")
    assert out1 == out2 and out1["stats"] == {"fragments": 2, "conflicts": 1, "engines": ["pdfplumber", "pymupdf", "rapidocr_ko"]}
    print("[selftest] fuse — 결정적(같은 입력 → 같은 결과)·stats 통과")
