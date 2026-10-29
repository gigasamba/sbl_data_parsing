"""common.store.edwdb 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.edwdb`."""

from pathlib import Path

from common.store.edwdb import conf


def _selftest_conf():
    """conf() — 빈 EDW_PASSWORD=는 접속 파일 비밀번호를 덮지 않음(VS7b BLOCK-1) · 형식 틀린 EDW_PORT는 옛처럼 실패(R-7). 가짜 값만, 접속 없음."""
    import tempfile

    from common.config.settings import COMMON

    f = Path(tempfile.mkdtemp()) / "edw.conn"
    f.write_text("EDW_SERVER=s\nEDW_DATABASE=d\nEDW_PASSWORD=from-file\n", encoding="utf-8")
    with COMMON.env(EDW_CONN_FILE=str(f), EDW_PASSWORD="", EDW_SERVER=None, EDW_DATABASE=None, EDW_PORT=None):
        assert conf()["EDW_PASSWORD"] == "from-file"
    with COMMON.env(EDW_CONN_FILE=str(f), EDW_PASSWORD=None, EDW_PORT="14330x"):
        try:
            conf()
            raise AssertionError("형식 틀린 EDW_PORT가 통과함")
        except ValueError as e:
            assert "EDW_PORT" in str(e) and "14330x" not in str(e)
    print("[selftest] conf() — 빈 EDW_PASSWORD는 접속 파일 값 유지·형식 틀린 EDW_PORT 실패 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _selftest_conf()
