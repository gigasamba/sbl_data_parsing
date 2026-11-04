"""mc-13 · op-13 규칙 7(사용자 11-04) — 검색·EDW 질의는 파일 기록(qa_log.jsonl)을 남기지 않는다. 호출 기록은 DB applog.mcp_call(op-01)뿐.
질의 기록 모듈과 설정 칸(search.query_log)이 없고, 옛 settings.yaml에 그 칸이 남아도 경고만 하고 무시한다(layout.REMOVED)."""

import importlib.util

from common.config import layout as L
from mcp_server import config as mc
from mcp_server.services import edw_query
from mcp_server.services.search import search_svc


def test_no_query_log_file():
    assert importlib.util.find_spec("mcp_server.services.search.qa_log") is None
    assert "query_log" not in mc.McpSettings.model_fields and "query_log" in L.REMOVED["McpSettings"]
    assert not hasattr(search_svc, "_log") and not hasattr(edw_query, "_log")
