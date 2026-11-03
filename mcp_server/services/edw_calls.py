"""EDW 도구 서비스 — query_edw(읽기 전용 SQL)·edw_meta(테이블·컬럼 메타 조회) 호출부.
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로.
"""

from common.store import edw_chain as EC
from common.store.db.models import search_tables as ST
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
    if schema is None and table is None and column_filter is None:  # 인자 없음 — 스키마 요약 + search attrs 키(pl-52)
        out = _lookup(EM, schema, table, column_filter)
        return {**out, "search_attrs": search_attrs()}
    return _lookup(EM, schema, table, column_filter)


def search_attrs():
    """원천별 search attrs 키(사슬 파일 — search와 같은 파일): {SFDC: {filter: {거르기 이름: attrs 키}, evidence: [근거 attrs 키]}}.
    filter 값 키들이 attrs 거르기에 줄 수 있는 키다. 사슬 파일이 틀리면 {"error"}."""
    from mcp_server.services.search.search_svc import chain

    try:
        ch = chain()
    except ValueError as e:
        return {"error": str(e)}
    return {("Other" if s == "other" else s.upper()): {"filter": EC.filters(ch, s), "evidence": EC.evidence(ch, s)} for s in ST.SOURCES}


def _lookup(EM, schema, table, column_filter):
    try:
        return EM.lookup(schema, table, column_filter)
    except EM.NotConfigured as e:
        return {"error": f"edw_meta 데이터셋 미구성 — {e}"}
    except Exception as e:  # 도구 하나가 서버 전체를 죽이지 않게
        print(f"[mcp] edw_meta failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return {"error": f"edw_meta 실패: {type(e).__name__}"}
