"""common.store.services 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.services --selftest`."""

import socket

import common.store.services as M
from common.ai.guard import require_internal
from common.config.settings import cfg, isolated
from common.store.services import (
    PG_FALLBACK_PORTS,
    PORT_RE,
    _find,
    _pg_capable,
    _probe_pg_port,
    _tcp_open,
    detect_pg,
)


def selftest():
    rows = [
        ("gitea-db", "postgres:16", [("127.0.0.1", "5432", "5432")]),  # 확장 없는 다른 PostgreSQL — 잡으면 안 됨
        ("rag-postgres", "pgvector/pgvector:pg16", [("127.0.0.1", "15432", "5432")]),
    ]
    assert _find(rows, "pgvector", "5432") == ("rag-postgres", "127.0.0.1", "15432")  # 이름이 아니라 이미지로 찾음
    assert _find(rows, "redis") is None
    assert PORT_RE.findall("0.0.0.0:1933->1933/tcp, [::]:1933->1933/tcp")[0] == ("0.0.0.0", "1933", "1933")
    for u in ("http://10.0.0.5:8000/v1", "http://localhost:8765/v1", "http://127.0.0.1:8000/v1"):
        require_internal(u, "EMBED")
    with isolated(
        EMBED_ALLOW_EXTERNAL=None, LLM_SYNTHETIC_TRUTH=None
    ):  # 기본(잠금 없음) 고정 — PC 루트 settings.yaml에 두 잠금이 있어도(D-035)
        try:
            require_internal("https://api.openai.com/v1", "EMBED")
            raise AssertionError("외부 주소가 통과됨")
        except RuntimeError:
            pass

    # SI26 — docker 권한 오류/없음일 때 듣는 포트로 대체 탐지, docker 정상이면 기존 경로 그대로
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = str(srv.getsockname()[1])
    assert _tcp_open("127.0.0.1", open_port) is True
    srv.close()
    assert _tcp_open("127.0.0.1", open_port) is False  # 닫은 직후라 응답 없음(best-effort 전제와 일치)

    # S7e2 — detect_pg가 설정에 쓰는 값(put — 덮기 파일)을 확인. 시험 설정(isolated)은 끝나면 되돌림
    saved_probe = M._probe_pg_port
    blank = dict(PG_HOST=None, PG_PORT=None, PG_PASSWORD=None, PG_CONN_FILE=None)
    try:
        with isolated(**blank):
            M._probe_pg_port = lambda host, ports=PG_FALLBACK_PORTS: "15432"
            ok, why = detect_pg(docker=([], "denied"))  # docker 권한 오류 → 포트 대체 탐지
            assert not ok and why.startswith("포트 탐지") and "PG_PASSWORD" in why
            assert cfg().connections.pg.host == "127.0.0.1" and cfg().connections.pg.port == 15432
        with isolated(**blank):
            M._probe_pg_port = lambda host, ports=PG_FALLBACK_PORTS: None
            ok, why = detect_pg(docker=([], "missing"))  # docker 없고 포트도 응답 없음 → 실패
            assert not ok and "응답 없음" in why
            ok, why = detect_pg(docker=(rows, None))  # docker 정상 → 기존 경로(컨테이너 hit)
            assert not ok and why.startswith("docker rag-postgres")  # PG_PASSWORD 없어 접속은 실패해도 경로는 docker
    finally:
        M._probe_pg_port = saved_probe

    print("[selftest] Docker 서비스 찾기·포트 대체 탐지(SI26)·내부망 가드 통과")

    # XS1 — 능력 확인(이름이 아니라 붙어서 vector 확장·스키마 확인) 실패 후보는 건너뛰고 다음 포트로
    class _FakePG:
        """포트별로 다른 PG를 흉내(9999=확장 없는 다른 PostgreSQL, 9998=우리 pgvector)."""

        def __init__(self, c):
            self.schema, self._port = c["PG_SCHEMA"], c["PG_PORT"]

        def q(self, sql, params=None):
            low = sql.lower()
            if "pg_extension" in low:
                return [{"x": 1}] if self._port == "9998" else []
            if "information_schema.schemata" in low:
                return [{"x": 1}]
            return [{"x": 1}]

    import common.store.pg as _pgmod

    real_pg, real_tcp = _pgmod.PG, M._tcp_open
    try:
        _pgmod.PG = _FakePG
        M._tcp_open = lambda host, port, timeout=1.5: True  # 둘 다 포트는 열려 있다고 흉내
        with isolated(PG_HOST=None, PG_PORT=None, PG_PASSWORD="x", PG_CONN_FILE=None):  # S7e2 — 시험 설정(끝나면 되돌림)
            ok, why = _pg_capable({"PG_HOST": "x", "PG_PORT": "9999", "PG_DB": "x", "PG_USER": "x", "PG_PASSWORD": "x", "PG_SCHEMA": "ai"})
            assert not ok and "vector 확장 없음" in why
            port = _probe_pg_port("127.0.0.1", ports=("9999", "9998"))
            assert port == "9998", port  # 9999(확장 없음)는 건너뛰고 9998(우리 pgvector)을 고름
    finally:
        _pgmod.PG = real_pg
        M._tcp_open = real_tcp

    print("[selftest] XS1 — 능력 확인(vector 확장) 실패 후보 건너뛰고 다음 포트로 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()
