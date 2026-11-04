"""pipeline.transform.figures.office_charts 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.office_charts`."""

from pathlib import Path

from pipeline.transform.represent.build_rep import chart_text


def selftest():
    assert chart_text(Path("no-such.txt")) == ""
    print("[selftest] 차트 XML 확장자 아닌 파일 → 빈 글자 통과(실제 chart*.xml 파싱은 parity 점검에서)")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
