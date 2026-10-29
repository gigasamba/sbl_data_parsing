"""pipeline.trigger_server 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.trigger_server --selftest`."""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.trigger_server import make_server

PY = sys.executable


def selftest():
    """가짜 작업자(실제 parse·structure 안 돌림) + ephemeral 포트 + 루프백만 — 서버 뼈대(인증·큐·상태·업로드)만 확인."""
    import tempfile

    def fake_cmd(stage, job):
        return [PY, "-c", "import sys; sys.exit(0)"]

    with tempfile.TemporaryDirectory() as t:
        app_root = Path(t)
        token = "selftest-token"
        httpd, jm = make_server("parse", app_root, "127.0.0.1", 0, token, False, cmd_builder=fake_cmd, queue_max=2)
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
                assert json.loads(r.read())["module"] == "parse"
            try:
                urllib.request.urlopen(urllib.request.Request(f"{base}/jobs", data=b"{}", method="POST"), timeout=5)
                raise AssertionError("인증 없이 통과하면 안 됨")
            except urllib.error.HTTPError as e:
                assert e.code == 401
            src = app_root / "output" / "sample.txt"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("x", encoding="utf-8")
            req = urllib.request.Request(
                f"{base}/jobs", data=json.dumps({"source": str(src)}).encode(), method="POST", headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                jid = json.loads(r.read())["job_id"]
            bad = urllib.request.Request(
                f"{base}/jobs",
                data=json.dumps({"source": "../../etc/passwd"}).encode(),
                method="POST",
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                urllib.request.urlopen(bad, timeout=5)
                raise AssertionError("경로 탈출 source를 거부해야 함")
            except urllib.error.HTTPError as e:
                assert e.code == 400
            status = None
            for _ in range(100):
                req = urllib.request.Request(f"{base}/jobs/{jid}", headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    status = json.loads(r.read())["status"]
                if status in ("done", "failed"):
                    break
                time.sleep(0.05)
            assert status == "done", status
        finally:
            jm.close()
            httpd.shutdown()
            th.join(timeout=5)
    print("trigger_server --selftest OK")


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
