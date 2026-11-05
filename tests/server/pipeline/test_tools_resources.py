"""pipeline.tools.py_env_check 시험."""

import os
import sys

from pipeline.tools.py_env_check import py_env_problem


def selftest():
    ver = sys.version_info[:2]
    in_box = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    in_venv = sys.prefix != sys.base_prefix
    if ver == (3, 12) and (in_venv or in_box):
        assert py_env_problem() is None
    else:
        assert py_env_problem() is not None
    assert py_env_problem(want=(9, 9)) is not None  # 맞는 버전이 없으면 늘 문제로 봄(컨테이너 안이라도)
    print("[selftest] py_env_problem — python 버전·venv/컨테이너 안 여부 점검 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
