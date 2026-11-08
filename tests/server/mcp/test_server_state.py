"""mcp_server.services.search.server_state 시험."""

from mcp_server import config as mc
from mcp_server.services.search import server_state as M
from mcp_server.services.search.server_state import _STATE, _retriever, _warmup_bg, health_body
from tests.server.mcp import pgfix


def _selftest_warmup_health():
    """MC1 — 예열 끝나기 전 `/health`는 ready=False·warming=True(라우트 503) · 끝나면 ready=True ·
    예열(또는 색인 로드)이 실패해도 ready=True + warning만(서버는 안 죽음)."""
    saved = dict(_STATE)
    _STATE.clear()
    try:
        body = health_body()  # 스레드 시작 전(또는 아직 도는 중) — warmup_done 없음
        assert body["ready"] is False and body.get("warming") is True and "warning" not in body, body

        class _FakeR:
            pg = None

        _STATE["Rs"] = {"sfdc": _FakeR()}
        _STATE["warmup_done"], _STATE["warmup_ok"] = True, True
        body = health_body()
        assert body["ready"] is True and "warming" not in body and "warning" not in body, body

        _STATE["warmup_ok"] = False  # 예열 실패 — ready는 그대로 켜짐, 경고만
        body = health_body()
        assert body["ready"] is True and body.get("warning") == "warmup_failed", body

        _STATE["warmup_ok"] = None  # 예열 결과 없음 — 경고 아님
        body = health_body()
        assert body["ready"] is True and "warning" not in body, body
    finally:
        _STATE.clear()
        _STATE.update(saved)
    print("[selftest] MC1 — 예열 중 /health 503 'warming'→끝나면 ready, 실패는 경고만(기동 유지) 통과")


def _selftest_warmup_bg_failure_keeps_server_up():
    """MC1 — 백그라운드 예열 스레드에서 색인 로드(`_retriever`) 자체가 터져도 예외가 올라오지 않고
    상태만 기록(기동 유지) — serve_http가 이 함수를 스레드 target으로 그대로 씀."""
    saved = dict(_STATE)
    saved_retriever = M._retriever
    _STATE.clear()
    try:

        def _boom():
            raise RuntimeError("색인 로드 실패(가짜)")

        M._retriever = _boom
        _warmup_bg()  # 예외를 밖으로 던지면 실패
        assert _STATE.get("warmup_done") is True and _STATE.get("warmup_ok") is False
    finally:
        M._retriever = saved_retriever
        _STATE.clear()
        _STATE.update(saved)
    print("[selftest] MC1 — 예열 중 색인 로드 실패해도 예외 없이 기동 유지(경고만) 통과")


def _selftest_reload():
    """load 뒤 재적재(S12) — 적재 버전(원천 스키마마다 MAX(doc_id)·COUNT — 11-02, load_run 대신)이 바뀌면 Retriever를 다시 만들고,
    안 바뀌면 그대로. --replace처럼 개수는 같고 doc_id만 커진 경우도 잡는다. SQLite 대역(pgfix, 임시 폴더) — 원천 other."""
    c = {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1, "bbox": None, "section": None}
    d = pgfix.mk_bundle([{"file_path": "a.txt"}], [c])
    _env = pgfix.use(d, MCP_RELOAD_CHECK_SEC="0")  # 설정 객체 덮기(S7d) · 늘 대역
    try:
        r1 = _retriever("other")
        assert r1.pg.is_standin and health_body()["store"] == "pgvector"
        r1.pg.q(f"INSERT INTO {r1.pg.schema}.doc(file_path) VALUES (%s)", ("b.txt",))  # 새 적재 — 개수 바뀜
        r2 = _retriever("other")
        assert r2 is not r1, "적재 버전 바뀌었는데 다시 안 만듦"
        r3 = _retriever("other")
        assert r3 is r2, "안 바뀌었는데 또 만듦"
        r3.pg.q(f"DELETE FROM {r3.pg.schema}.doc WHERE file_path = %s", ("a.txt",))
        r3.pg.q(f"INSERT INTO {r3.pg.schema}.doc(file_path) VALUES (%s)", ("a.txt",))  # --replace 꼴 — 개수 같고 새 doc_id가 가장 큼
        r4 = _retriever("other")
        assert r4 is not r3, "같은 개수 다시 넣기(--replace)를 못 잡음"
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] load 뒤 재적재 — 적재 버전 바뀌면 다시 만들고, 안 바뀌면 그대로 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — server_state.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgfile

    cfgfile._CACHE.setdefault(
        "stack", cfgfile.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    _selftest_reload()
    _selftest_warmup_health()
    _selftest_warmup_bg_failure_keeps_server_up()


def test_reload_keeps_pool():
    """재적재 확인 — 확인 질의가 실패하면(None) 안 바뀜으로 보고 다시 만들지 않는다(풀·검색기 그대로) · 판이 바뀌면 다시 만든다 ·
    다시 만들어도 실 PG 풀은 프로세스에 하나(connect_sources가 새로 만들지 않음). 실 PG 없이 가짜 연결로."""
    from unittest import mock

    class DB:
        schema = "t_other"

        def __init__(self, row):
            self.row = row

        def q(self, sql, params=None):
            if self.row is None:
                raise OSError("db down")
            return [self.row]

    cases = [  # (확인 질의가 돌려줄 행 — None이면 실패, 다시 만들었나)
        (None, False),
        ({"m": 1, "n": 1}, False),
        ({"m": 2, "n": 2}, True),
    ]
    saved = dict(_STATE)
    try:
        with mc.senv(MCP_RELOAD_CHECK_SEC="0"):
            for row, rebuilt in cases:
                pool, R = object(), object()
                _STATE.clear()
                _STATE.update(Rs={"other": R}, dbs={"other": DB(row)}, version=(("other", 1, 1),), checked_at=0, pool=pool)
                with mock.patch.object(M, "_build_retriever") as build:
                    assert _retriever("other") is R
                assert build.called is rebuilt and _STATE["pool"] is pool, (row, build.called)

        made = []

        class Pool:
            schema = "t"

            def __init__(self, c, statement_timeout_sec=None):
                made.append(statement_timeout_sec)

            q = scope = None  # SchemaView가 묶기만 함(all_sources는 가짜)

        _STATE.clear()
        with (
            mock.patch.object(M, "has_conn", return_value=True),
            mock.patch.object(M, "conf", return_value={}),
            mock.patch.object(M, "PGPool", Pool),
            mock.patch.object(M.ST, "all_sources", lambda base, q=None: ["other"]),
        ):
            first, second = M.connect_sources(), M.connect_sources()
        # 풀 하나 · 질의 시간 제한은 MCP 칸(기본 25초 — 도구 30초 안), 파이프라인 칸(120초)이 아님
        assert made == [25] and first["other"].pool_obj is second["other"].pool_obj is _STATE["pool"]
    finally:
        _STATE.clear()
        _STATE.update(saved)


def test_check_store_server_guard():
    """op-09 — 서버(dev·prd)는 PG 접속 칸이 비면 시작 거부(대역으로 빠지지 않음), PC는 통과(대역)."""
    from unittest import mock

    from common.core import paths
    from mcp_server.services.search.server_state import check_store

    with mc.senv(PG_HOST=None, PG_PASSWORD=None):
        with mock.patch.object(paths, "LOCAL_RUN", False):
            try:
                check_store()
                raise AssertionError("서버에서 빈 PG 접속인데 거부 안 함")
            except SystemExit as e:
                assert "PG 접속 정보 없음" in str(e), e
        with mock.patch.object(paths, "LOCAL_RUN", True):
            check_store()  # PC — 대역으로 돎
