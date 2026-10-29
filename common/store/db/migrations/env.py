"""Alembic 실행 환경(S8a, 5-4 — 사용자 10-28 Q1 a): 판 폴더 하나에 갈래 2개(search·struct). ini 파일 없이 dbtool이 Config를 만들고
config.attributes로 연결(connection)·갈래(target)·스키마(schema)·차원(dim, search만)을 넘긴다 — 접속 값은 settings.yaml(common.store.pg.conf).
판 기록 표는 스키마마다 <스키마>.alembic_version(검색 스키마가 여럿이라 — index --pg). 오프라인(SQL 글자만 내기) 모드는 쓰지 않는다."""

from alembic import context

attrs = context.config.attributes
if context.is_offline_mode():
    raise SystemExit("오프라인 모드는 쓰지 않음 — python -m common.store.db.dbtool로")
conn, schema = attrs["connection"], attrs["schema"]
if attrs.get("create_schema"):  # 판 표를 스키마 안에 두므로 스키마가 먼저 있어야 함(옛 schema.sql·PgBackend도 CREATE SCHEMA IF NOT EXISTS)
    conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
context.configure(connection=conn, version_table_schema=schema, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
