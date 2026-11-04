"""common.check.checker env 시험."""

import tempfile
from pathlib import Path

from common.check.checker import _parse_requirements, check_path_bundle, check_pg_schema, check_requirements
from common.config import settings as C
from pipeline import config as pc


def selftest():
    """requirements 대조 로직만 — 가짜 네이티브·이미지 파일 2개로 누락·버전 차이 검출을 확인(실제 설치·네트워크 불필요)."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "native.txt").write_text("foo==1.0.0\nbar==2.0.0\n# comment\nbaz\n", encoding="utf-8")
        (d / "image.txt").write_text("foo==1.0.0\nbar==2.5.0\nqux[extra]==9.9.9\nbaz\n", encoding="utf-8")
        rows, bad = check_requirements(native_path=d / "native.txt", docker_paths=[d / "image.txt"])
        got = {r[0]: r for r in rows}
        assert bad is True
        assert got["bar"][1:] == ("2.5.0", "2.0.0", "버전 다름")
        assert got["qux"][1:] == ("9.9.9", "없음", "이미지에만 있음")
        assert "foo" not in got and "baz" not in got  # 같은 버전·버전 미지정 둘 다 없음은 차이 아님

        rows2, bad2 = check_requirements(native_path=d / "image.txt", docker_paths=[d / "image.txt"])
        assert rows2 == [] and bad2 is False  # 같은 파일끼리는 차이 0
        assert _parse_requirements(d / "없는파일.txt") == {}  # 파일 없으면 빈 dict(죽지 않음)
    print("[selftest] check_env requirements 대조 통과")

    # OP15(c1) — 경로 묶음: 미설정(선택)·형식만 보는 값을 출력만으로 확인(죽지 않음)
    import contextlib
    import io

    # S7c — check_path_bundle이 설정 객체로 읽으므로 객체에 겹쳐 씀(os.environ 안 건드림)
    with pc.PIPE.env(PARSE_SOURCE="rdb:*"):
        # PARSE_SOURCE: 형식만(경로 존재 안 봄) · SOURCES_FILE 등: 미설정(선택)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_path_bundle()
        out = buf.getvalue()
        assert "미설정(선택)" in out  # SOURCES_FILE 등
        assert "rdb:*" in out
    print("[selftest] check_env 경로 묶음(OP15 c1) — 미설정·형식만 보는 값 통과")

    _selftest_pg_schema()


def _selftest_pg_schema():
    """OP22 — PG_SCHEMA 권한 조회(읽기만)를 가짜 psycopg.connect로: ①스키마 있음·권한 있음 ②스키마 없음·DB CREATE 없음
    ③PG_PASSWORD 없음(건너뜀) — 실제 연결 0."""
    import contextlib
    import io
    from types import SimpleNamespace

    import psycopg

    script = {}

    class FakeCursor:
        description = None

        def __init__(self):
            self._rows = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            if "pg_namespace" in sql:
                self._rows = [(1,)] if script["schema_exists"] else []
                self.description = [SimpleNamespace(name="x")]
            elif "has_schema_privilege" in sql:
                self._rows = [(script["usage_ok"], script["create_ok"])]
                self.description = [SimpleNamespace(name="usage_ok"), SimpleNamespace(name="create_ok")]
            elif "has_database_privilege" in sql:
                self._rows = [(script["create_db"],)]
                self.description = [SimpleNamespace(name="create_db")]
            else:
                self._rows, self.description = [], None

        def fetchall(self):
            return self._rows

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    real_connect = psycopg.connect
    psycopg.connect = lambda **kw: FakeConn()
    try:
        # S7c — pg.conf()·has_conn()가 설정 객체(COMMON)로 읽으므로 객체에 겹쳐 씀(os.environ 안 건드림)
        with C.COMMON.env(PG_HOST="x", PG_PORT="5432", PG_DB="x", PG_USER="x", PG_PASSWORD="x", PG_SCHEMA="ai_test"):
            script.update(schema_exists=True, usage_ok=True, create_ok=False, create_db=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                check_pg_schema()
            out = buf.getvalue()
            assert "USAGE 권한" in out and "CREATE 권한" in out

            script.update(schema_exists=False, create_db=True)
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                check_pg_schema()
            assert "없음 — DB에 새 스키마" in buf2.getvalue()

            with C.COMMON.env(PG_PASSWORD=None):  # conf()가 SystemExit → 건너뜀(연결 자체를 안 함)
                buf3 = io.StringIO()
                with contextlib.redirect_stdout(buf3):
                    check_pg_schema()
            assert "건너뜀" in buf3.getvalue()
    finally:
        psycopg.connect = real_connect
    print("[selftest] check_env PG_SCHEMA 권한(OP22) — 있음·없음·건너뜀 가짜 connect로 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()
