"""mcp_server.services.search.server_state 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.server_state`."""

import json
import os
import time
from pathlib import Path

from mcp_server import config as mc
from mcp_server.services.search import server_state as M
from mcp_server.services.search.server_state import _STATE, _health, _retriever, _warmup_bg


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

        _STATE["R"] = _FakeR()
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


def _mk_bundle(docs, chunks):
    """R1·R3 selftest 공용 — 로컬 묶음 임시 디렉터리(임베딩 없음, dim 0)."""
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((len(chunks), 0), dtype="float32"))
    return d


def _selftest_reload():
    """load 뒤 재적재(S12) — 로컬 묶음 meta.json mtime이 바뀌면 Retriever를 다시 만들고, 안 바뀌면 그대로(매번 다시 안 만듦)."""
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text(
        json.dumps({"file_path": "a.txt", "file_name": "a.txt", "file_sha256": "e" * 64, "doc_format": ".txt"}) + "\n", encoding="utf-8"
    )
    (d / "chunks.jsonl").write_text(
        json.dumps(
            {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1, "bbox": None, "section": None}
        )
        + "\n",
        encoding="utf-8",
    )
    np.save(d / "vectors.npy", np.zeros((1, 0), dtype="float32"))
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_RELOAD_CHECK_SEC="0")  # 설정 객체 덮기(S7d)
    try:
        r1 = _retriever()
        os.utime(d / "meta.json", (time.time() + 2, time.time() + 2))
        r2 = _retriever()
        assert r2 is not r1, "mtime 바뀌었는데 다시 안 만듦"
        r3 = _retriever()
        assert r3 is r2, "안 바뀌었는데 또 만듦"
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] load 뒤 재적재 — meta.json mtime 바뀌면 다시 만들고, 안 바뀌면 그대로 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — server_state.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgtables

    cfgtables._CACHE.setdefault(
        "stack", cfgtables.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    _selftest_reload()
    _selftest_warmup_health()
    _selftest_warmup_bg_failure_keeps_server_up()
