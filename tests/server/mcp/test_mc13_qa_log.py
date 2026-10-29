"""mc-13 — 검색 질의 기록은 qa_log.jsonl 파일만(사용자 10-30). PG 저장소여도 PG에 아무것도 쓰지 않고(qa_log 표 없음),
jsonl 한 줄은 그대로 남는다. 전에는 없는 표에 INSERT를 보내 오류를 삼켰다."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from mcp_server import config as mc
from mcp_server.services.search import search_svc as S
from mcp_server.services.search.server_state import _STATE


class _PG:  # qa_log 표가 없는 PG — 어떤 질의든 받으면 기록(받으면 안 됨)
    schema = "ai"

    def __init__(self):
        self.calls = []

    def q(self, sql, params=None):
        self.calls.append(sql)
        raise RuntimeError('relation "ai.qa_log" does not exist')


class _R:
    def __init__(self):
        self.pg = _PG()


def test_log_file_only():
    d = Path(tempfile.mkdtemp())
    R = _R()
    with mc.senv(MCP_QUERY_LOG_DIR=str(d)), patch.dict(_STATE, {"R": R, "stack": {"name": "dev-v1"}}):
        S._log("배치 수는?", [{"chunk_id": 7, "rank": 1, "via": "bm25"}], 12.34)
        recs = [json.loads(x) for x in (d / "qa_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert R.pg.calls == [], R.pg.calls  # PG에 질의 기록을 보내지 않음
    assert len(recs) == 1 and recs[0]["question"] == "배치 수는?" and recs[0]["stack_name"] == "dev-v1", recs
    assert recs[0]["hits"] == [{"chunk_id": 7, "rank": 1, "via": "bm25"}] and recs[0]["search_ms"] == 12.3, recs
