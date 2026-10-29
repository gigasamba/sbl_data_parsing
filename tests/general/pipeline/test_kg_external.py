"""pipeline.eval.kg_external 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.kg_external --selftest`."""

import json
from pathlib import Path

from common.config import settings as C
from pipeline.eval import anchors as A
from pipeline.eval import stages as S
from pipeline.eval.kg_external import run_stack

# ── 자기 점검 (--selftest) — mock LLM만, 실제 프레임워크는 미설치 에러 메시지만 확인 ──


def selftest():
    import contextlib
    import socket
    import tempfile
    import threading
    from http.server import ThreadingHTTPServer

    import mock_llm as M

    from common.ai import llm as L

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = ThreadingHTTPServer(("127.0.0.1", port), M.H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        # S7c — 설정 객체에 겹쳐 씀(os.environ 안 건드림 — llm.chat·_need_llm이 객체로 읽음)
        with (
            C.COMMON.env(LLM_BASE_URL=f"http://127.0.0.1:{port}/v1", LLM_MODEL="mock"),
            tempfile.TemporaryDirectory(prefix="kg_ext_selftest_") as tmp,
            contextlib.ExitStack() as es,
        ):
            tmp = Path(tmp)
            es.enter_context(C.COMMON.env(LLM_CACHE_DIR=str(tmp / "llm_cache")))
            corpus = {
                "doc1.txt": "계약번호: CT-9001\n공급업체: 가나다상사\n계약금액: 1,000,000원\n",
                "doc2.txt": "계약번호: CT-9002\n공급업체: 라마바상사\n계약금액: 2,000,000원\n",
            }
            anchors = [
                {
                    "id": "doc1.txt::a0",
                    "doc": "doc1.txt",
                    "docs": ["doc1.txt"],
                    "label": "계약번호",
                    "value": "CT-9001",
                    "query": "계약번호 가나다상사",
                    "source": "truth",
                }
            ]
            out_dir = tmp / "out_eval"
            A.write_anchors(anchors, out_dir / "anchors.jsonl")

            calls0 = L.usage()["calls"]
            if S.graph_mode_ready("llm"):  # S6a(T-02) — LLM 그래프 모드는 PC 전용 validation/e2e(서버 이미지에는 없음 → 건너뜀)
                out_path = run_stack("mockgraph", corpus, anchors, out_dir, out_dir / "work", k=5)
                lines = [json.loads(ln) for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                assert len(lines) == len(anchors), "jsonl 줄 수가 앵커 수와 다름"
                units_map = {d["anchor_id"]: d["units"] for d in lines}
                R, _ = S.eval_retrieval(anchors, lambda a: units_map.get(a["id"], []))
                assert R["r10"] == 1.0, f"mockgraph 외부 스택 채점 실패: {R}"
                print(f"[selftest] mockgraph build→search→jsonl→채점 R@10={R['r10']} · llm 호출 {L.usage()['calls'] - calls0}회")
            else:
                print("[selftest] mockgraph 건너뜀 — LLM 그래프 모드(validation/e2e/graph_llm.py, PC 전용)가 이 이미지에 없음")

            import importlib.util

            if (
                importlib.util.find_spec("lightrag") is not None
            ):  # 설치된 환경(개발 PC 일부)에서는 '미설치' 오류 점검을 건너뜀 — 백로그 P 10-02
                print("[selftest] lightrag 설치돼 있음 — 미설치 오류 점검 건너뜀")
            else:
                try:
                    run_stack("lightrag_hybrid", corpus, anchors, out_dir, out_dir / "work2", k=5)
                    raise AssertionError("lightrag가 설치돼 있지 않은데 에러가 안 남")
                except RuntimeError as e:
                    assert "미설치" in str(e), f"에러 메시지에 '미설치'가 없음: {e}"
                print("[selftest] lightrag 미설치 에러 메시지 확인")
            print("[selftest] 전부 통과")
    finally:
        srv.shutdown()
        th.join(timeout=5)


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
