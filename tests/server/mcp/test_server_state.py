"""mcp_server.services.search.server_state 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.server_state`."""

from mcp_server.services.search import server_state as M
from mcp_server.services.search.server_state import _STATE, _health, _retriever, _warmup_bg
from tests.server.mcp import pgfix


def _selftest_warmup_health():
    """MC1 — 예열 끝나기 전 `/health`는 ready=False·warming=True(라우트 503) · 끝나면 ready=True ·
    예열(또는 색인 로드)이 실패해도 ready=True + warning만(서버는 안 죽음, MCP_WARMUP=0으로 끈 건 경고 아님)."""
    saved = dict(_STATE)
    _STATE.clear()
    try:
        body = _health()  # 스레드 시작 전(또는 아직 도는 중) — warmup_done 없음
        assert body["ready"] is False and body.get("warming") is True and "warning" not in body, body

        class _FakeR:
            pg = None

        _STATE["Rs"] = {"sfdc": _FakeR()}
        _STATE["warmup_done"], _STATE["warmup_ok"] = True, True
        body = _health()
        assert body["ready"] is True and "warming" not in body and "warning" not in body, body

        _STATE["warmup_ok"] = False  # 예열 실패 — ready는 그대로 켜짐, 경고만
        body = _health()
        assert body["ready"] is True and body.get("warning") == "warmup_failed", body

        _STATE["warmup_ok"] = None  # MCP_WARMUP=0(꺼짐) — 경고 아님
        body = _health()
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
    _env = pgfix.use(d, MCP_BUNDLE=str(d), MCP_RELOAD_CHECK_SEC="0")  # 설정 객체 덮기(S7d) · 늘 대역
    try:
        r1 = _retriever("other")
        assert r1.pg.is_standin and _health()["store"] == "pgvector"
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


def test_check_store_server_guard():
    """op-09 — 서버(dev·prd)는 PG 접속 칸이 비면 시작 거부(대역으로 빠지지 않음), PC는 통과(대역)."""
    from unittest import mock

    from common.core import paths
    from mcp_server import config as mc
    from mcp_server.services.search.server_state import check_store

    with mc.senv(PG_HOST=None, PG_PASSWORD=None, PG_CONN_FILE=None):
        with mock.patch.object(paths, "LOCAL_RUN", False):
            try:
                check_store()
                raise AssertionError("서버에서 빈 PG 접속인데 거부 안 함")
            except SystemExit as e:
                assert "PG 접속 정보 없음" in str(e), e
        with mock.patch.object(paths, "LOCAL_RUN", True):
            check_store()  # PC — 대역으로 돎
