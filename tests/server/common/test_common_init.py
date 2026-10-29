"""common(패키지 __init__) 자기 점검 — S9(D-018)에 모듈에서 옮김. 옛 사례 `python -m common.__init__ --selftest`(옛 __main__이 core/fingerprint.py의 selftest를 부름 — 그 함수는 tests/server/common/test_fingerprint.py로 옮겼음 — 그 파일도 따로 사례라 같은 점검이 두 번 돎: 옛 사례 이름을 지키려는 것, VS9 R-6)."""

from tests.server.common.test_fingerprint import selftest


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래(`fingerprint.selftest()`)
    selftest()
