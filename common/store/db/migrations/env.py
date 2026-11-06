"""Alembic 실행 환경: 판 폴더 하나에 갈래 search·applog·master. ini 파일 없이 dbtool이 Config를 만들고
config.attributes로 연결(connection)·갈래(target)·스키마(schema)·차원(dim, search만)을 넘긴다 — 접속 값은 settings.yaml(common.store.pg.conf).
판 기록 표는 스키마마다 <스키마>.alembic_version(검색 스키마가 여럿이라 — index --pg). DEV 원천 스키마 하나만 올릴 때(op-17)는
sources = (그 원천,)·version_schema = 그 원천 스키마 — 판 기록 표가 그 스키마에 따로 있다(판 파일은 기준 스키마 몫을 건너뜀).
오프라인(SQL 글자만 내기 — `dbtool up --sql <파일>`): DB에 붙지 않고 attributes["out"]에 SQL을 쓴다. 판 파일의
`op.get_bind().exec_driver_sql(글자)`는 글자 그대로 내보낸다(가짜 연결에 exec_driver_sql이 없어서)."""

from alembic import context

attrs = context.config.attributes
schema = attrs["schema"]
version_schema = attrs.get("version_schema") or schema
if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql",
        output_buffer=attrs["out"],
        version_table_schema=version_schema,
        transactional_ddl=True,
        literal_binds=True,
    )
    impl = context.get_context().impl
    if attrs.get("create_schema"):
        impl.static_output(f"CREATE SCHEMA IF NOT EXISTS {version_schema};")
    context.get_bind().exec_driver_sql = lambda sql, *a, **k: impl.static_output(sql.strip().rstrip(";") + ";")  # type: ignore[method-assign,assignment]  # 가짜 연결(MockConnection)에 글자 그대로 내기를 붙임
    with context.begin_transaction():
        context.run_migrations()
else:
    conn = attrs["connection"]
    if attrs.get("create_schema"):  # 판 표를 스키마 안에 두므로 스키마가 먼저 있어야 함
        conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {version_schema}")
    context.configure(connection=conn, version_table_schema=version_schema, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
