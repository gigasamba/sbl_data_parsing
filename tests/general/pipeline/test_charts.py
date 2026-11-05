"""pipeline.transform.figures.chart_values.chart_text 시험."""

from pathlib import Path

from pipeline.transform.figures.chart_values import chart_text


def selftest():
    assert chart_text(Path("no-such.txt")) == ""
    print("[selftest] 차트 XML 확장자 아닌 파일 → 빈 글자 통과(실제 chart*.xml 파싱은 parity 점검에서)")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
