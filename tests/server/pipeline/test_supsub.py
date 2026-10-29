"""pipeline.transform.represent.supsub 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.supsub`."""

from pathlib import Path

import pipeline.transform.represent.supsub as M
from pipeline.transform.represent.supsub import merge_supsub


def selftest():
    import tempfile
    import zipfile as zf

    d = Path(tempfile.mkdtemp())
    docx = d / "x.docx"
    xml = (
        '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>a</w:t></w:r>'
        '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>2</w:t></w:r></w:p></w:body></w:document>'
    )
    with zf.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", xml)
    assert M.supsub_text(docx) == "a^2"
    assert M.supsub_text(d / "no-such-ext.txt") == ""
    print("[selftest] 서식 첨자(docx) ^ 표기 통과")

    xlsx = d / "x.xlsx"  # AD24① — xlsx sharedStrings 숫자 문자 참조(&#45453; = '농')
    with zf.ZipFile(xlsx, "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst><si><r><t>CO_2 &#45453;&#46020;</t></r></si></sst>")
    assert M.supsub_text(xlsx) == "CO_2 농도"
    print("[selftest] xlsx 숫자 문자 참조 해제(AD24①) 통과")

    docx2 = d / "m.docx"  # AD37 — 첨자 있는 줄만 바꿔 넣기(본문 중복 방지)
    xml2 = (
        '<w:document xmlns:w="w"><w:body>'
        "<w:p><w:r><w:t>머릿말 줄</w:t></w:r></w:p>"
        '<w:p><w:r><w:t>CO</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="subscript"/></w:rPr><w:t>2</w:t></w:r>'
        '<w:r><w:t> 농도는 10</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>6</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>끝 줄</w:t></w:r></w:p></w:body></w:document>"
    )
    with zf.ZipFile(docx2, "w") as z:
        z.writestr("word/document.xml", xml2)
    base = "머릿말 줄\nCO2 농도는 106\n끝 줄"  # 대표 엔진 원문(첨자 표기 없이 숫자만 뽑음)
    merged, full, n_unmatched = merge_supsub(base, docx2)
    assert merged == "머릿말 줄\nCO_2 농도는 10^6\n끝 줄", merged  # 그 줄만 바뀜 — 안 바뀐 두 줄은 그대로
    assert len(merged) - len(base) <= 4 and n_unmatched == 0  # 본문 길이 비율 ≈ 1(문서 전체 덧붙기 없음)
    assert "CO_2 농도는 10^6" in full  # 첨자 표기본 전체는 따로(rep.post 보관용) — 그대로 반환
    merged0, full0, n0 = merge_supsub("첨자 없는 문서", d / "plain.txt")  # 확장자 미지원 → supsub_text 빈 글자
    assert merged0 == "첨자 없는 문서" and full0 == "" and n0 == 0  # 첨자 없는 문서 → 본문 불변
    print("[selftest] AD37 — 첨자 있는 줄만 본문에 치환(문서 중복 안 생김)·첨자 없으면 본문 불변 통과")

    # 독립 검토 MAJOR 1 — 퍼지 점수만 보고 바꾸면 첨자와 무관한 값(수량 1→7)까지 덮어쓰던 재현 사례
    _orig_supsub_text = M.supsub_text
    try:

        def _fake(_p):  # 표기본 쪽 줄이 첨자 말고도 다른 글자(수량 1↔7)가 다름 — 퍼지 점수는 높아도 치환하면 안 됨
            return "단가 500 원 수량 7 비고 없음^0\n첨자 있는 줄 10^6"

        M.supsub_text = _fake
        base2 = "단가 500 원 수량 1 비고 없음\n첨자 있는 줄 106"
        merged2, full2, n2 = merge_supsub(base2, d / "whatever.docx")
        assert merged2.splitlines()[0] == "단가 500 원 수량 1 비고 없음"  # 숫자만 다른 줄은 안 바뀜(base 유지)
        assert merged2.splitlines()[1] == "첨자 있는 줄 10^6"  # 첨자만 다른 줄은 바뀜
        assert n2 == 1 and "수량 7" not in merged2  # 못 맞춘 1줄로만 세고, 끝에 덧붙지도 않음(재중복 방지)
        base3 = "1쪽 본문\n\f\n2쪽 첨자 있는 줄 106\n\f3쪽 끝"  # A9 — 쪽 나눔(\f)은 그대로 남아야 함
        merged3, _, _ = merge_supsub(base3, d / "whatever.docx")
        assert merged3.count("\f") == 2, merged3
    finally:
        M.supsub_text = _orig_supsub_text
    print("[selftest] 독립 검토 MAJOR 1 — 숫자만 다른 줄은 안 바뀌고 첨자만 다른 줄만 바뀜(끝에 덧붙지 않음) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
