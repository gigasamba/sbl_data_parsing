"""pipeline.transform.structure.draft_terms 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.draft_terms`."""

from pipeline.transform.structure.draft_terms import collect_candidate_org_names, extract_candidate_orgs


def selftest():
    text = (
        "미르하제약(주)과 신규 공급 계약을 검토 중이며, 같은 건에 Northfield Biologics Inc. 쪽 의견도 받았다. 미르하제약(주) 담당자 확인."
    )
    cands = extract_candidate_orgs(text)
    assert cands == ["미르하제약(주)", "Northfield Biologics Inc."], cands  # 중복 제거·등장 순

    docs = [{"full_text": text}, {"full_text": "Northfield Biologics Inc. 재계약"}]
    from common.core.terms import norm

    out = collect_candidate_org_names(docs, {norm("Celltrion")}, norm)
    assert out == ["Northfield Biologics Inc.", "미르하제약(주)"], out  # 2회 언급이 먼저(결정적 순서)
    out2 = collect_candidate_org_names(docs, {norm("미르하제약(주)"), norm("Northfield Biologics Inc.")}, norm)
    assert out2 == []  # 이미 아는 이름은 후보에서 빠짐
    print(
        "[selftest] SI43④ — extract_candidate_orgs(한글·영문 법인 접미사, 중복 제거·결정적 순서)·"
        "collect_candidate_org_names(이미 아는 이름 제외) 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
