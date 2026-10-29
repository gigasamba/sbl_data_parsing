"""pipeline.transform.figures.mermaid 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.mermaid`."""

from pipeline.transform.figures.mermaid import to_mermaid


def selftest():
    assert to_mermaid([]) == "" and to_mermaid([{"from": None, "to": "B"}]) == ""
    m = to_mermaid([{"from": "Seed", "to": "Bioreactor", "label": None}, {"from": "Bioreactor", "to": "Harvest", "label": "48h"}])
    assert m.startswith("flowchart LR\n") and 'n0["Seed"] --> n1["Bioreactor"]' in m
    assert 'n1["Bioreactor"] -->|"48h"| n2["Harvest"]' in m
    m2 = to_mermaid([{"from": 'A"B', "to": "C"}])  # 따옴표는 라벨 안에서 이스케이프
    assert "A'B" in m2 and '"' in m2
    print("[selftest] edges → Mermaid flowchart LR(라벨·따옴표 이스케이프) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
