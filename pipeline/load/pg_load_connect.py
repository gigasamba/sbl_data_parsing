"""pipeline 전용 PG 단일 연결 전환점(10-14 함수별 분리 — common/store/pg.py에서 이전, 로직 바이트 동일).
load/pgstore.py main()만 쓴다(검색 MCP의 상주 풀 전환점은 mcp_server/services/search/pg_mcp_connect.py의 connect_pool)."""

from common.store.pg import PG, _standin_schema, _warn_standin, conf, has_conn


def connect(c=None, pg_schema=None):
    """AD41 단일 전환점 — PG_PASSWORD·PG_CONN_FILE이 있으면 진짜 PG(PG 클래스), 없으면 스탠드인(StandinPG, sqlite ·
    PG_STANDIN_DIR, 기본 output/pg_standin). load/pgstore.py main()이 씀 — 서버는 pipeline.env에 연결 정보만 채우면
    코드 변경 없이 진짜 PG로 바뀐다. 한 줄 알림(모드)은 호출부(check_env.py·pgvector_load.py)가 찍는다 — 스탠드인을
    고를 때는 여기서도 WARNING 한 줄(_warn_standin, 서버에서 비밀번호를 빠뜨려도 조용히 안 넘어가게)."""
    if has_conn():
        c = c or conf()
        if pg_schema:
            c = {**c, "PG_SCHEMA": pg_schema}
        return PG(c)
    _warn_standin()
    from common.store.pg_standin import StandinPG

    return StandinPG(_standin_schema(pg_schema or (c or {}).get("PG_SCHEMA")))
