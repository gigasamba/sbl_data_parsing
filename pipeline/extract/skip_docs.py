"""영구 건너뜀 문서 기록(pl-58) — 파싱할 수 없는 원본(지원 안 하는 확장자·확장자 없음·DRM·암호)을 `applog.skip_doc_info`에
원본 키당 한 행으로 남기고(처음·마지막 본 시각·횟수), 대상 목록(`candidate_pick.list_targets --skip-done`)이 그 키를 뺀다 —
밤마다 같은 문서를 다시 받지 않게. 중복(`dup_*`)은 게시가 ParsingMeta `skipped_dup`로 쓰므로, 파싱 실패는 다시 시도하므로 여기 쓰지 않는다.
PG 접속 정보가 있으면 PG(`dbtool up --target applog` — 판 0002), 없으면 PC 대역 sqlite(`<standin_dir>/applog.sqlite` — 표를 바로 만듦,
서버는 대역을 쓰지 않고 멈춤)."""

from pathlib import Path

TABLE = "skip_doc_info"
PERMANENT = ("unsupported_", "drm_", "encrypted_")  # 이유 앞부분 — 원본이 바뀌지 않는 한 다시 받아도 같은 결과


def _schema():
    from common.store.db.dbtool import schema_of

    return schema_of("applog")


def standin():
    """PC 대역(sqlite) — 표가 없으면 표 정의(log_tables)에서 만든다."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from common.store.db.models.log_tables import log_metadata
    from common.store.pg_standin import StandinPG

    schema = _schema()
    db = StandinPG(schema)
    ddl = CreateTable(log_metadata(schema).tables[f"{schema}.{TABLE}"], if_not_exists=True).compile(dialect=postgresql.dialect())
    db.q(f"CREATE SCHEMA IF NOT EXISTS {schema};\n{str(ddl).strip()}")  # CREATE SCHEMA로 시작 = 대역의 DDL 묶음(DEFAULT now() 번역)
    return db


def _db():
    from common.store.pg import PG, _warn_standin, conf, has_conn

    if has_conn():
        return PG({**conf(), "PG_SCHEMA": _schema()})
    _warn_standin()  # 서버(dev·prd)는 여기서 SystemExit
    return standin()


def _close(db):
    (getattr(db, "sqlite", None) or db.cn).close()  # 대역은 sqlite 연결, PG는 psycopg 연결


def reason_of(name, reason):
    """skip_doc_info에 쓸 이유 — 영구 이유가 아니면 None. 확장자 없는 이름의 '지원 안 함'은 no_extension."""
    if not reason or not reason.startswith(PERMANENT):
        return None
    return "no_extension" if reason.startswith("unsupported_") and not Path(name).suffix else reason


def record(rows):
    """rows = [{source_key, source_system, file_name, reason}] — 영구 이유만 원본 키당 한 행 upsert(처음 본 시각은 그대로, 마지막 시각·횟수 갱신).
    반환: 쓴 행 수."""
    todo = [{**r, "reason": reason_of(r["file_name"], r["reason"])} for r in rows]
    todo = [r for r in todo if r["reason"] and r["source_key"]]
    if not todo:
        return 0
    s = _schema()
    sql = (
        f"INSERT INTO {s}.{TABLE} (source_key, source_system, file_name, reason, level, first_seen, last_seen, count) "
        "VALUES (%s, %s, %s, %s, 'error', now(), now(), 1) ON CONFLICT (source_key) DO UPDATE SET "
        f"source_system = EXCLUDED.source_system, file_name = EXCLUDED.file_name, reason = EXCLUDED.reason, "
        f"last_seen = EXCLUDED.last_seen, count = {TABLE}.count + 1"
    )
    db = _db()
    try:
        for r in todo:
            db.q(sql, (r["source_key"], r.get("source_system"), r["file_name"], r["reason"]))
    finally:
        _close(db)
    print(f"[skip] 영구 건너뜀 {len(todo)}건 기록({s}.{TABLE}) — 다음 대상 목록(--skip-done)에서 뺌", flush=True)
    return len(todo)


def skipped_keys():
    """skip_doc_info에 있는 원본 키 집합."""
    db = _db()
    try:
        return {r["source_key"] for r in db.q(f"SELECT source_key FROM {_schema()}.{TABLE}")}
    finally:
        _close(db)
