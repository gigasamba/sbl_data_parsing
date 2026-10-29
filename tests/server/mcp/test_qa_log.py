"""mcp_server.services.search.qa_log 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.qa_log`."""

import json
import time
from pathlib import Path

from mcp_server import config as mc
from mcp_server.services.search.qa_log import _TIME_FMT, append, cleanup, log_path


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    import tempfile

    d = Path(tempfile.mkdtemp())
    _env = mc.senv(MCP_QUERY_LOG_DIR=str(d))  # 설정 객체 덮기(S7d — os.environ 안 건드림)
    p = log_path()
    append("배치 수는?", [{"chunk_id": "c1", "rank": 1, "via": "bm25"}], 12.3, "mcp:test", stack_name="dev-v1")
    recs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["question"] == "배치 수는?" and recs[0]["asked_by"] == "mcp:test"
    assert recs[0]["hits"] == [{"chunk_id": "c1", "rank": 1, "via": "bm25"}]
    with mc.senv(MCP_QUERY_LOG="0"):
        append("안 남아야 함", [], 1.0, "mcp:test")
        assert len(p.read_text(encoding="utf-8").splitlines()) == 1  # 끔 — 더 안 늘어남
    old = {
        "time": time.strftime(_TIME_FMT, time.localtime(time.time() - 91 * 86400)),
        "question": "오래됨",
        "stack_name": None,
        "k": 0,
        "hits": [],
        "search_ms": 1.0,
        "asked_by": "mcp:test",
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(old, ensure_ascii=False) + "\n")
    dropped = cleanup(p)
    assert dropped == 1, dropped
    recs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["question"] == "배치 수는?"  # 90일 안쪽은 남고, 지난 것만 지워짐
    with p.open("a", encoding="utf-8") as f:
        f.write("이건 json이 아님\n")
    assert cleanup(p) == 0  # 못 읽는 줄은 지우지 않음(알 수 없는 걸 지우지 않음)
    _env.close()
    print("[selftest] OP6 — 질의 기록·끔 스위치·90일 정리 통과")

    # engine-qa BLOCK 1 — output/qa_log 디렉터리 자리에 파일이 있어 mkdir가 실패(쓰기 불가 흉내)해도 append가 안 죽음
    blocked = d / "blocked"
    blocked.write_text("디렉터리가 아니라 파일", encoding="utf-8")  # p.parent가 이미 파일 — mkdir(exist_ok=True)도 OSError
    with mc.senv(MCP_QUERY_LOG_DIR=str(blocked)):
        append("쓰기 실패해도 살아야 함", [{"chunk_id": "x", "rank": 1, "via": "bm25"}], 1.0, "mcp:test")  # 예외 없이 반환
        assert not (blocked / "qa_log.jsonl").exists()  # 쓰기 자체가 안 됨(파일 자리라 디렉터리를 못 만듦)
    print("[selftest] engine-qa BLOCK 1 — output/qa_log 쓰기 실패해도 append가 예외를 올리지 않음 통과")
