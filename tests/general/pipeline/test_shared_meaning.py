"""pipeline.shared.text_normalize 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.shared.text_normalize`."""

from pipeline.shared.text_normalize import canon_num_key


def test_main():  # 옛 `if __name__ == "__main__":` 몸통(인라인 점검)
    assert canon_num_key("430,000") == "430000" and canon_num_key("4,30,000") is None  # 순수 함수
    print("[selftest] canon_num_key 통과")
