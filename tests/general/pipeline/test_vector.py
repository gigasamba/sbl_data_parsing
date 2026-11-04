"""pipeline.transform.figures.vector_regions 시험."""

from pipeline.transform.figures.vector_regions import vector_regions


def selftest():
    import fitz

    doc = fitz.open()
    pg = doc.new_page()
    assert vector_regions(pg) == []  # 빈 쪽 — 영역 0
    print("[selftest] 빈 쪽은 벡터 영역 0(표 격자·오탐 회귀는 parity 점검에서 실PDF로)")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
