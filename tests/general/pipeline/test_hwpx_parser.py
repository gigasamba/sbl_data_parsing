"""pipeline.extract.engines.hwpx.parser(엔진 파일 — 엔진 지문) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.extract.engines.hwpx.parser`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

import zipfile

from pipeline.extract.engines.hwpx.parser import parse_hwpx


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: 섹션 본문 + 섹션 없을 때 PrvText 대체` 몸통
    import tempfile

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>제목</hp:t></hp:run></hp:p>'
        "<hp:p><hp:run><hp:t>2026-01-01 공지</hp:t></hp:run></hp:p></hs:sec>"
    )
    with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as f:
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("mimetype", "application/hwp+zip", zipfile.ZIP_STORED)
            z.writestr("Contents/section0.xml", xml)
            z.writestr("Preview/PrvText.txt", "미리보기 텍스트")
        tmp = f.name
    r = parse_hwpx(tmp)
    assert "제목" in r["text"] and "2026-01-01 공지" in r["text"], r

    with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as f2:
        with zipfile.ZipFile(f2, "w") as z:
            z.writestr("mimetype", "application/hwp+zip", zipfile.ZIP_STORED)
            z.writestr("Preview/PrvText.txt", "미리보기만 있음")
        tmp2 = f2.name
    r2 = parse_hwpx(tmp2)
    assert r2["text"] == "미리보기만 있음", r2
    print("hwpx self-check OK")
