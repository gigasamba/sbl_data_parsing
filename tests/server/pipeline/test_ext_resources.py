"""pipeline.extract.resources 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.resources`."""

from pipeline.extract.resources import resolve_procs, thread_env, thread_share


def selftest():
    from common.config.settings import COMMON  # S7c — plan()이 설정 객체로 읽으므로 env 대신 객체를 덮어씀(os.environ은 안 바뀜)

    with COMMON.env(PIPE_PROCS="5"):
        assert resolve_procs("2") == 2 and resolve_procs("auto") == 5
    assert thread_share(8, 4, 1) == 2 and thread_share(8, 4, 2) == 1  # 동시 = procs × workers(조각마다 workers건)
    assert thread_share(8, 1, 2) == 4 and thread_share(16, 1, 1) == 16 and thread_share(3, 4, 1) == 1
    env = thread_env(3)
    assert env == {
        "OMP_NUM_THREADS": "3",
        "MKL_NUM_THREADS": "3",
        "OPENBLAS_NUM_THREADS": "3",
        "NUMEXPR_NUM_THREADS": "3",
        "TORCH_NUM_THREADS": "3",
    }, env
    print("[selftest] resolve_procs(명시값·auto)·thread_env(수치 라이브러리 스레드 고정) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
