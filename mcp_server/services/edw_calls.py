"""EDW 도구 서비스 — query_edw(읽기 전용 SQL)·edw_meta(테이블·컬럼 메타 조회) 호출부."""

from common.store import edw_chain as EC
from common.store.db.models import search_tables as ST
from mcp_server.schemas.evidence import SEARCH_FILTERS


def do_query_edw(sql, max_rows=1000):
    """Thin controller wrapper over mcp_server.services.edw_query.query() (all SQL-guard/backend/
    size-cap logic lives there, not here)."""
    from mcp_server.services import edw_query as EQ

    return EQ.query(sql, max_rows)


def do_edw_meta(schema=None, table=None, column_filter=None):
    """EM1 — thin controller wrapper over mcp_server.services.edw_meta.lookup() (dataset load/reload/
    3-level hierarchy logic lives there, not here). import는 의도적으로 lazy(§8 R9 fail-soft) — 도구
    파일·데이터셋이 없어도 서버 부팅과 나머지 세 도구는 그대로, 이 도구만 {"error": …}로 응답한다."""
    try:
        from mcp_server.services import edw_meta as EM
    except Exception as e:  # 모듈 없음 = 기능 꺼짐(부팅 계속)
        print(f"[mcp] edw_meta 모듈 없음(기능 꺼짐): {type(e).__name__}: {e}", flush=True)
        return {"error": "edw_meta 도구 파일 미적용(EM1) — 패치·마운트 적용 후 재시도"}
    if schema is None and table is None and column_filter is None:  # 인자 없음 — 스키마 요약 + search attrs 키
        out = _lookup(EM, schema, table, column_filter)
        return out if "error" in out else {**out, "search_attrs": search_attrs()}  # 오류 응답에는 붙이지 않음
    return _lookup(EM, schema, table, column_filter)


def search_attrs():
    """원천별 search attrs 키(사슬 파일 — search와 같은 파일): {SFDC: {filter: {search 인자: attrs 키}, attrs: [attrs 거르기 키],
    evidence: [근거 attrs 키]}}. filter에는 search 인자(SEARCH_FILTERS)인 이름만 — 사슬의 다른 filter 이름은 attrs 키로만 쓴다. 사슬 파일이 틀리면 {"error"}."""
    from mcp_server.services.search.search_svc import chain

    try:
        ch = chain()
    except ValueError as e:
        return {"error": str(e)}
    from mcp_server.services.search.server_state import dev_served

    out = {}
    try:
        dev = dev_served()  # 검색하는 DEV 원천(op-17 — prd는 없음). DEV는 사슬이 없어 빈 칸
    except (Exception, SystemExit) as e:  # 검색 DB를 못 읽어도(PG 접속 칸 없음 등) EDW 메타 도구는 5벌로
        print(f"[mcp] search_attrs DEV 원천 못 읽음: {type(e).__name__}", flush=True)
        dev = []
    for s in [*ST.SOURCES, *dev]:
        fm = EC.filters(ch, s) if s in ch else {}
        out[ST.label(s)] = {
            "filter": {n: k for n, k in fm.items() if n in SEARCH_FILTERS},
            "attrs": sorted(set(fm.values())),
            "evidence": EC.evidence(ch, s) if s in ch else [],
        }
    return out


def _lookup(EM, schema, table, column_filter):
    try:
        return EM.lookup(schema, table, column_filter)
    except EM.NotConfigured as e:
        return {"error": f"edw_meta 데이터셋 미구성 — {e}"}
    except Exception as e:  # 도구 하나가 서버 전체를 죽이지 않게
        print(f"[mcp] edw_meta failed: {type(e).__name__}: {str(e)[:100]}", flush=True)
        return {"error": f"edw_meta 실패: {type(e).__name__}"}
