"""pipeline.transform.represent.text_normalize 시험."""

from pipeline.transform.represent.text_normalize import canon_num_key


def test_main():  # 옛 `if __name__ == "__main__":` 몸통(인라인 점검)
    assert canon_num_key("430,000") == "430000" and canon_num_key("4,30,000") is None  # 순수 함수
    print("[selftest] canon_num_key 통과")
