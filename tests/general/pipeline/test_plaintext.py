"""pipeline.transform.parse.engines.plaintext.parser(엔진 파일 — 엔진 지문) 자기 점검 — S9b(VS9 B-1, D-018)에 모듈 `__main__`에서 옮김(줄 글자 그대로).
옛 명령 `python -m pipeline.transform.parse.engines.plaintext.parser`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 엔진 지문을 바꾼다(사용자 10-28 — 엔진 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

import re

from pipeline.transform.parse.engines.plaintext.parser import parse_plaintext


def test_main():  # 옛 `if __name__ == "__main__":   # 자기점검: CP949·탭 표` 몸통
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write("항목\t값\n단가\tUSD 85 / g\nMTOP\t2 batches\n".encode("cp949"))
    r = parse_plaintext(f.name)
    assert r["trace"]["encoding"] == "cp949" and r["tables"][0]["rows"] == 3, r
    assert re.search("단가", r["text"])
    print("plaintext self-check OK")
