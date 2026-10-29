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
