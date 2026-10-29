"""pipeline.transform.figures.vector 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.vector`."""

from pipeline.transform.figures.vector import vector_regions


def selftest():
    import fitz

    doc = fitz.open()
    pg = doc.new_page()
    assert vector_regions(pg) == []  # 빈 쪽 — 영역 0
    print("[selftest] 빈 쪽은 벡터 영역 0(표 격자·오탐 회귀는 parity 점검에서 실PDF로)")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
