"""EDW 도구 서비스 — query_edw(읽기 전용 SQL)·edw_meta(테이블·컬럼 메타 조회) 호출부.
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로.
"""

from mcp_server.services.search.server_state import CALLER


def do_query_edw(sql, max_rows=1000):
    """EQ1 — thin controller wrapper over mcp_server.services.edw_query.query() (all SQL-guard/backend/
    size-cap logic lives there, not here)."""
    from mcp_server.services import edw_query as EQ

    return EQ.query(sql, max_rows, caller=CALLER.get())


def do_edw_meta(schema=None, table=None, column_filter=None):
    """EM1 — thin controller wrapper over mcp_server.services.edw_meta.lookup() (dataset load/reload/
    3-level hierarchy logic lives there, not here). import는 의도적으로 lazy(§8 R9 fail-soft) — 도구
    파일·데이터셋이 없어도 서버 부팅과 나머지 세 도구는 그대로, 이 도구만 {"error": …}로 응답한다."""
    try:
        from mcp_server.services import edw_meta as EM
    except Exception as e:  # 모듈 없음 = 기능 꺼짐(부팅 계속)
        print(f"[mcp] edw_meta 모듈 없음(기능 꺼짐): {type(e).__name__}: {e}", flush=True)
        return {"error": "edw_meta 도구 파일 미적용(EM1) — 패치·마운트 적용 후 재시도"}
    try:
        return EM.lookup(schema, table, column_filter)
    except EM.NotConfigured as e:
        return {"error": f"edw_meta 데이터셋 미구성 — {e}"}
    except Exception as e:  # 도구 하나가 서버 전체를 죽이지 않게
        print(f"[mcp] edw_meta failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return {"error": f"edw_meta 실패: {type(e).__name__}"}
