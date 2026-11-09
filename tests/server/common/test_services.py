"""PG 연결 고르기(common.store.pg) 자기 점검.
PG 접속 칸이 비면 거부(채울 자리를 적음 — 자동 탐지 없음), 이름이 아니라 붙어서 능력 확인."""

import common.store.pg as _pgmod
from common.ai.guard import require_internal
from common.config.settings import isolated
from common.store.pg import _pg_capable, conf, detect_pg

_FULL = dict(PG_HOST="h", PG_PORT="5432", PG_DB="d", PG_USER="u", PG_PASSWORD="x", PG_SCHEMA="ai")


def _refused(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    raise AssertionError("거부되지 않음")


def selftest():
    for u in ("http://10.0.0.5:8000/v1", "http://localhost:8765/v1", "http://127.0.0.1:8000/v1"):
        require_internal(u, "EMBED")
    with isolated(EMBED_ALLOW_EXTERNAL=None):  # 기본(허용 없음) 고정 — PC 루트 settings.yaml에 허용이 있어도
        try:
            require_internal("https://api.openai.com/v1", "EMBED")
            raise AssertionError("외부 주소가 통과됨")
        except RuntimeError:
            pass

    # op-09 — 빈 접속 칸은 코드 기본값(127.0.0.1·5432·rag·ai)으로 채우지 않고 거부, 메시지에 settings.yaml 자리
    with isolated(**{**_FULL, "PG_HOST": None, "PG_DB": None}):
        msg = _refused(conf)
        assert "required.pg.pg_host" in msg and "required.pg.pg_database" in msg and "required.pg.pg_port" not in msg, msg
    with isolated(**_FULL):
        assert conf()["PG_HOST"] == "h" and conf()["PG_DB"] == "d"

    # 능력 확인(이름이 아니라 붙어서 vector 확장·스키마 확인)
    class _FakePG:
        """포트별로 다른 PG를 흉내(9999=확장 없는 다른 PostgreSQL, 9998=우리 pgvector)."""

        def __init__(self, c):
            self.schema, self._port = c["PG_SCHEMA"], c["PG_PORT"]

        def q(self, sql, params=None):
            if "pg_extension" in sql.lower():
                return [{"x": 1}] if self._port == "9998" else []
            return [{"x": 1}]

    real_pg = _pgmod.PG
    try:
        _pgmod.PG = _FakePG
        ok, why = _pg_capable({**_FULL, "PG_PORT": "9999"})
        assert not ok and "vector 확장 없음" in why
        with isolated(**{**_FULL, "PG_PORT": "9999"}):
            ok, why = detect_pg()
            assert not ok and why == "h:9999: vector 확장 없음", why
        with isolated(**{**_FULL, "PG_PORT": "9998"}):
            assert detect_pg() == (True, "h:9998")
    finally:
        _pgmod.PG = real_pg

    print("[selftest] PG 접속 칸 필수·자동 탐지 없음(op-09)·능력 확인(XS1)·내부망 가드 통과")


def test_main():
    selftest()
