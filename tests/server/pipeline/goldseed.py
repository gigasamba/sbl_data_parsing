"""시험 도우미 — PC 대역 gold `doc` 행(op-17 처리 기록)을 원천 스키마에 심는다. `COMMON.env(PG_STANDIN_DIR=<임시>)` 안에서 부른다."""

from common.store import pg_standin as PS
from common.store.db.dbtool import standin_script
from common.store.db.models import search_tables as ST
from common.store.pg import _standin_schema


def seed(rows, dim=4):
    """rows = [{file_path, source_system?(기본 SFDC), sha256?, parse_status?(기본 ok)}] — 그 원천 스키마의 doc에 한 행씩."""
    base = _standin_schema()
    for r in rows:
        schema = ST.src_schema(base, ST.source_of(r.get("source_system", "SFDC")))
        db = PS.StandinPG(schema)
        try:
            with db.cn.cursor() as cur:  # 표가 있으면 그대로(IF NOT EXISTS)
                cur.execute(standin_script(schema, dim))
            db.q(
                f"INSERT INTO {schema}.doc (file_path, sha256, parse_status) VALUES (%s, %s, %s)",
                (r["file_path"], r.get("sha256"), r.get("parse_status", "ok")),
            )
        finally:
            db.sqlite.close()
