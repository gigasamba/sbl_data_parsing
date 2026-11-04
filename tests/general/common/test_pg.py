"""common.store.pg 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.pg`."""

from common.config.settings import COMMON
from common.store.pg import PG, PGPool, conf


def _selftest_pool():
    """PGPool — 가짜 연결 팩토리로 동시 획득·반납·상한(실제 PG 없이, psycopg_pool.ConnectionPool만 가짜로 바꿔 PGPool.q() 확인)."""
    import threading

    import psycopg_pool as _pp

    active, peak, lock = [0], [0], threading.Lock()

    class FakeCursor:
        description = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    class FakeCtx:
        def __init__(self, sem):
            self.sem = sem

        def __enter__(self):
            self.sem.acquire()
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            return FakeConn()

        def __exit__(self, *a):
            with lock:
                active[0] -= 1
            self.sem.release()
            return False

    class FakePool:
        def __init__(self, kwargs=None, min_size=1, max_size=4, open=True):
            self.sem = threading.Semaphore(max_size)

        def connection(self, timeout=None):
            return FakeCtx(self.sem)

    real = _pp.ConnectionPool
    _pp.ConnectionPool = FakePool
    try:
        pool = PGPool({"PG_HOST": "x", "PG_PORT": "5432", "PG_DB": "x", "PG_USER": "x", "PG_PASSWORD": "x", "PG_SCHEMA": "ai"}, max_size=2)
        done = []

        def worker():
            pool.q("SELECT 1")
            done.append(1)

        ths = [threading.Thread(target=worker) for _ in range(6)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        assert len(done) == 6 and peak[0] <= 2, (len(done), peak[0])
    finally:
        _pp.ConnectionPool = real
    print("[selftest] PGPool — 가짜 연결 팩토리로 동시 획득·반납·상한(<=2) 통과")


def _selftest_connect_timeout():
    """PG()·PGPool() 모두 psycopg connect_timeout을 넘기는지(env PG_CONNECT_TIMEOUT, 기본 10초) — 실제 접속 없이 psycopg.connect만 가짜로(XS4)."""
    import psycopg

    captured = []

    def fake_connect(**kwargs):
        captured.append(kwargs)
        raise SystemExit("가짜 connect — selftest는 연결 자체를 안 함")

    c = {"PG_HOST": "x", "PG_PORT": "5432", "PG_DB": "x", "PG_USER": "x", "PG_PASSWORD": "x", "PG_SCHEMA": "ai"}
    real = psycopg.connect
    psycopg.connect = fake_connect
    try:
        with COMMON.env(PG_CONNECT_TIMEOUT=None):
            try:
                PG(c)
            except SystemExit:
                pass
            assert captured[-1]["connect_timeout"] == 10, captured[-1]  # 기본값
        with COMMON.env(PG_CONNECT_TIMEOUT="3"):
            try:
                PG(c)
            except SystemExit:
                pass
            assert captured[-1]["connect_timeout"] == 3, captured[-1]  # env로 바꿈
    finally:
        psycopg.connect = real
    print("[selftest] PG() connect_timeout 전달(env PG_CONNECT_TIMEOUT, 기본 10초) 통과")


def _selftest_conf():
    """conf() — 준 접속 칸을 글자로 · 형식 틀린 PG_PORT는 옛처럼 실패(R-7). 가짜 값만, 실제 접속 없음."""
    full = dict(PG_HOST="h", PG_PORT="5432", PG_DB="d", PG_USER="u", PG_SCHEMA="ai")  # op-09 — 접속 칸 모두 필수
    with COMMON.env(**full, PG_PASSWORD="x2"):
        assert conf()["PG_PASSWORD"] == "x2" and conf()["PG_PORT"] == "5432"
    with COMMON.env(**{**full, "PG_PORT": "abc"}, PG_PASSWORD=None):
        try:
            conf()
            raise AssertionError("형식 틀린 PG_PORT가 통과함")
        except ValueError as e:
            assert "PG_PORT" in str(e) and "abc" not in str(e)
    print("[selftest] conf() — 빈 PG_PASSWORD는 접속 파일 값 유지·형식 틀린 PG_PORT 실패 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _selftest_pool()
    _selftest_connect_timeout()
    _selftest_conf()
