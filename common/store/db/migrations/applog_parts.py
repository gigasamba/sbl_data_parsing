"""Alembic 작업 안에서만 월 파티션 관리 — 쓰기 sink에서는 호출하지 않는다.
ensure_partitions(op, schema, now)는 현재 + 앞으로 두 달을 만든다.
maintain(op, schema, days, now)는 ensure 후 월 끝이 보존 경계 이하인 파티션을
DROP하고, 작은 일반 테이블 pipe_run은 ended_at/started_at 기준 DELETE한다.
운영은 dbtool maintain --target applog를 매일 예약한다(누락 시 파일 대체 기록).
"""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

PARENTS = {"mcp_log": "requested_at", "pipe_event": "ts_start"}
_SCHEMA = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def month_start(now=None):
    return (now or datetime.now(UTC)).astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(start):
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def ensure_partitions(op, schema="applog", now=None):
    if not _SCHEMA.fullmatch(schema):
        raise ValueError("invalid schema")
    op.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))").bindparams(key=f"{schema}.applog_parts"))
    start = month_start(now)
    created = []
    for _ in range(3):
        end = next_month(start)
        for parent in PARENTS:
            name = f"{parent}_{start:%Y%m}"
            op.execute(
                f"CREATE TABLE IF NOT EXISTS {schema}.{name} PARTITION OF {schema}.{parent} "
                f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
            )
            created.append(name)
        start = end
    return created


def maintain(op, schema="applog", days=90, now=None):
    if days < 1:
        raise ValueError("retention days must be positive")
    now = now or datetime.now(UTC)
    created = ensure_partitions(op, schema, now)
    cutoff = now - timedelta(days=days)
    rows = (
        op.get_bind()
        .execute(
            text("""
        SELECT child.relname AS name, parent.relname AS parent,
               pg_get_expr(child.relpartbound, child.oid) AS bounds
        FROM pg_inherits i JOIN pg_class child ON child.oid=i.inhrelid
        JOIN pg_class parent ON parent.oid=i.inhparent
        JOIN pg_namespace n ON n.oid=parent.relnamespace
        JOIN pg_namespace cn ON cn.oid=child.relnamespace
        WHERE n.nspname=:schema AND cn.nspname=:schema
    """),
            {"schema": schema},
        )
        .mappings()
    )
    dropped = []
    for row in rows:
        parent, name = row["parent"], row["name"]
        if parent not in PARENTS or not re.fullmatch(rf"{parent}_[0-9]{{6}}", name):
            continue
        try:
            start = datetime.strptime(name[-6:], "%Y%m").replace(tzinfo=UTC)
            # 이름뿐 아니라 실제 파티션 경계를 확인한 뒤 DROP.
            bound_values = re.findall(r"'([^']+)'", row["bounds"])
            actual = [datetime.fromisoformat(v).astimezone(UTC) for v in bound_values]
        except ValueError:
            continue
        end = next_month(start)
        if actual != [start, end] or end > cutoff:
            continue
        op.execute(f"DROP TABLE {schema}.{name}")
        dropped.append(name)
    op.execute(text(f"DELETE FROM {schema}.pipe_run WHERE coalesce(ended_at, started_at) < :cutoff").bindparams(cutoff=cutoff))
    return {"ensured": created, "dropped": dropped}
