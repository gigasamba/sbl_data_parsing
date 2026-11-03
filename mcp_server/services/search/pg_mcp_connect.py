"""검색 MCP(mcp_server) 전용 PG 상주 풀 연결 전환점(10-14 함수별 분리 — common/store/pg.py에서 이전, 로직 바이트 동일).
검색 MCP 상주 Retriever만 쓴다(단일 연결 전환점은 pipeline/load/pg_load_connect.py의 connect)."""

from common.store.pg import PGPool, _standin_schema, _warn_standin, conf, has_conn


def connect_pool(c=None, pg_schema=None, max_size=None):
    """connect()와 같은 전환점 — 검색 MCP 상주 Retriever(PGPool 자리). 스탠드인은 연결 1개뿐이라 풀이 필요 없어
    StandinPG를 그대로(스레드 여러 개가 같은 스탠드인을 동시에 쓰는 경우는 PC 시험 범위 밖 — ponytail)."""
    if has_conn():
        c = c or conf()
        if pg_schema:
            c = {**c, "PG_SCHEMA": pg_schema}
        return PGPool(c, max_size=max_size)
    _warn_standin()
    from common.store.pg_standin import StandinPG

    return StandinPG(_standin_schema(pg_schema or (c or {}).get("PG_SCHEMA")))


class SchemaView:
    """연결 풀 하나로 원천 스키마 하나를 가리킴(pl-28 — 5벌이 풀 하나를 함께 씀, 스키마 이름만 다름). q·scope는 풀 그대로."""

    def __init__(self, pool, schema):
        self.pool_obj, self.schema = pool, schema
        self.q, self.scope = pool.q, pool.scope


def connect_sources():
    """원천 이름 → 그 원천 스키마 연결(`<PG_SCHEMA>_<원천>`). 실 PG는 풀 하나 + SchemaView, 대역은 스키마마다 파일 하나(StandinPG)."""
    from common.store.db.models import search_tables as ST

    if has_conn():
        pool = PGPool(conf())
        return {src: SchemaView(pool, ST.src_schema(pool.schema, src)) for src in ST.SOURCES}
    _warn_standin()
    from common.store.pg_standin import StandinPG

    base = _standin_schema(None)
    return {src: StandinPG(ST.src_schema(base, src)) for src in ST.SOURCES}
