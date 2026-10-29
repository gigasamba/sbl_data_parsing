"""mcp_server.cli.search_checks 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.cli.search_checks --selftest`."""

import json
import types
from contextlib import contextmanager
from pathlib import Path

from mcp_server.cli.search_checks import _interpret_l8, cmd_br54, cmd_gh114


def selftest_br54():
    import importlib.util

    try:
        _has_retrieval = importlib.util.find_spec("mcp_server") is not None
    except ModuleNotFoundError:
        _has_retrieval = False
    if not _has_retrieval:  # 10-15 — br54는 검색 MCP를 부름: mcp-server 이미지(S6b — 옛 data-retrieval, 또는 PC)에서만
        print("[selftest] br54 건너뜀 — mcp_server(S5 전 data_retrieval)가 이 이미지에 없음")
        return
    questions = {"items": [{"id": f"Q{i}", "question": f"질문 {i}", "evidence": [{"doc": f"doc{i}.pdf"}]} for i in range(1, 5)]}
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        qpath = Path(td) / "qa.json"
        qpath.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")

        def fake_search(q, k):
            idx = int(q.split()[-1])
            # common.pdf가 모든 질문에서 상위5에 낌(허브) — Q3의 정답 doc3.pdf는 common.pdf에 밀려 상위5 밖
            top = ["common.pdf", f"doc{idx}.pdf", "x.pdf", "y.pdf", "z.pdf"]
            if idx == 3:
                top = ["common.pdf", "w.pdf", "x.pdf", "y.pdf", "z.pdf"]  # doc3.pdf 없음
            return {"evidence": [{"file_name": fn} for fn in top]}

        # S6a(VS5 R-1) — 결과도 임시 폴더에(전에는 out=None이라 진짜 output/server_checks/br54/ 보고서를 덮어씀)
        args = types.SimpleNamespace(questions=str(qpath), k=8, max_q=None, threshold=0.5, out=str(Path(td) / "br54"))
        rc = cmd_br54(args, search_fn=fake_search)
        assert rc == 0
        report = json.loads((Path(td) / "br54" / "hub_report.json").read_text(encoding="utf-8"))
        assert "common.pdf" in report["flagged_hubs"], report
        assert any(d["id"] == "Q3" for d in report["displaced"]), report
    print("[selftest] br54 — 허브 판정·정답 밀림 탐지 통과")


def selftest_l8():
    # (1) urllib Host 헤더 재정의가 실제로 전송되는지 — 표준 라이브러리 http.server로 직접 확인(네트워크는 127.0.0.1만)
    import http.server
    import threading
    import urllib.request

    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["host"] = self.headers.get("Host")
            self.rfile.read(int(self.headers.get("Content-Length") or 0))  # 본문을 읽고 닫음 — 안 읽으면 Windows가 RST(WinError 10053)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/"
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Host": "spoofed.example:1234"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        assert seen["host"] == "spoofed.example:1234", seen  # 실제로 보낸 Host가 override됨 확인
    finally:
        srv.shutdown()
        th.join(timeout=5)

    # (2) 상태 코드 해석 — 순수 함수(네트워크 없음)
    r_ok = _interpret_l8(200, 421, 403)
    assert r_ok["ok"] and r_ok["wrong_host_rejected"] and r_ok["foreign_origin_rejected"], r_ok
    r_bad = _interpret_l8(401, 200, 200)  # Host 검증이 전혀 안 걸린 상황(둘 다 통과)
    assert not r_bad["ok"] and not r_bad["wrong_host_rejected"] and not r_bad["foreign_origin_rejected"], r_bad
    print("[selftest] l8 — urllib Host 헤더 override 실동작 확인 · 상태코드 판정 함수 통과")


def selftest_gh114():
    from common.store import pg as pg_mod

    class _Col:
        def __init__(self, name):
            self.name = name

    class FakeCur:
        def __init__(self, conn):
            self.conn = conn
            self.description = None
            self._rows = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            if "SET LOCAL hnsw.ef_search" in sql:
                val = int(sql.rsplit("=", 1)[1].strip())
                self.conn.local["ef_search"] = val
                self.description, self._rows = None, []
            elif sql.strip().lower().startswith("show hnsw.ef_search"):
                self.description, self._rows = [_Col("hnsw.ef_search")], [(self.conn.local.get("ef_search"),)]
            else:
                self.description, self._rows = None, []

        def fetchall(self):
            return self._rows

    class FakeConn:
        def __init__(self):
            self.local = {}

        def cursor(self):
            return FakeCur(self)

        @contextmanager
        def transaction(self):
            try:
                yield self
            finally:
                self.local = {}  # GH1-14 — COMMIT 뒤 리셋

    class FakeDB:
        schema = "ai"

        def __init__(self):
            self.cn = FakeConn()

        @contextmanager
        def scope(self):
            with self.cn.transaction():
                yield pg_mod._ScopedConn(self.cn)

    import tempfile

    with tempfile.TemporaryDirectory() as td:  # S6a(VS5 R-1) — 진짜 output/server_checks/gh114/ 보고서를 덮어쓰지 않게
        args = types.SimpleNamespace(ef_search=150, pool=False, out=td)
        rc = cmd_gh114(args, db_factory=lambda: FakeDB())
        assert rc == 0
        args2 = types.SimpleNamespace(ef_search=999, pool=False, out=td)
        db2 = FakeDB()
        db2.cn.local["ef_search"] = 1  # 이전 호출의 리셋 안 됨 흔적이 있어도 SET LOCAL이 즉시 덮어씀을 확인
        rc2 = cmd_gh114(args2, db_factory=lambda: db2)
        assert rc2 == 0
    print("[selftest] gh114 — SET LOCAL hnsw.ef_search → 같은 스코프 SHOW로 확인(가짜 연결) 통과")


def test_main():  # 옛 `--selftest` 갈래(run_all_selftests — 세 사례를 SUBCOMMANDS 순서로)
    selftest_br54()
    selftest_l8()
    selftest_gh114()
    print("[selftest] search_checks — 전체(br54·l8·gh114) 통과")
