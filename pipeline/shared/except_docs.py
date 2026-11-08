"""적재되지 않은 문서 기록(op-17) — `applog.except_doc_info`에 원본 키 + 종류(`except_type`)당 한 행(처음·마지막 본 시각·횟수).
- `skip` = 영구 뺌: 다시 받아도 파싱할 수 없는 원본(지원 안 하는 확장자·확장자 없음·DRM·암호)과 내용 중복(`duplicate_sha256` — 같은 묶음·
  이번 실행·끝난 문서와 같은 내용). 대상 목록(`candidate_pick.list_targets --skip-done`)이 그 키를 뺀다 — 밤마다 같은 문서를 다시 받지 않게.
- `error` = 파싱·적재 실패: 기록만 하고 다음 실행이 다시 고른다(`skipped_keys`에 들지 않음).
- `part`(수준 warn) = 안 문서(압축 안 파일·첨부·개체)를 일부 못 꺼냄(pl-65): 성한 안 파일은 붙여 적재됨, 기록만.
- `silver`(수준 warn) = 실버만 게시 — 골드 전(pl-68): 게시가 쓰고 골드 적재가 성공하면 지운다. 남아 있으면 골드 실패·중단·실버까지만 실행.
PG 접속 정보가 있으면 PG(`dbtool up --target applog` — 판 0003), 없으면 PC 대역 sqlite(`<standin_dir>/applog.sqlite` — 표를 바로 만듦,
서버는 대역을 쓰지 않고 멈춤). 명령 `python -m pipeline.shared.except_docs error --csv <문서 위치 표> --reason <이유>` — run_pipeline이
문서의 파싱·게시·적재 실패를 적는다."""

import csv
import sys
from pathlib import Path

TABLE = "except_doc_info"
PERMANENT = (
    "unsupported_",
    "drm_",
    "encrypted_",
    "duplicate_",
    "broken_archive",
    "archive_too_big",
)  # skip 이유 앞부분 — 원본이 바뀌지 않는 한 다시 받아도 같은 결과


def _schema():
    from common.store.db.dbtool import schema_of

    return schema_of("applog")


def standin():
    """PC 대역(sqlite) — 표가 없으면 표 정의(log_tables)에서 만들고, 앞서 만든 대역 파일에 없는 칸(판 0004 file_ext·file_size)은 더한다."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from common.store.db.models.log_tables import log_metadata
    from common.store.pg_standin import StandinPG

    schema = _schema()
    db = StandinPG(schema)
    table = log_metadata(schema).tables[f"{schema}.{TABLE}"]
    ddl = CreateTable(table, if_not_exists=True).compile(dialect=postgresql.dialect())
    db.q(f"CREATE SCHEMA IF NOT EXISTS {schema};\n{str(ddl).strip()}")  # CREATE SCHEMA로 시작 = 대역의 DDL 묶음(DEFAULT now() 번역)
    have = {r[1] for r in db.sqlite.execute(f"PRAGMA table_info({TABLE})")}
    for col in table.columns:
        if col.name not in have:
            db.sqlite.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col.name} {col.type.compile(dialect=postgresql.dialect())}")
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
    """skip 행에 쓸 이유 — 영구 이유가 아니면 None. 확장자 없는 이름의 '지원 안 함'은 no_extension."""
    if not reason or not reason.startswith(PERMANENT):
        return None
    return "no_extension" if reason.startswith("unsupported_") and not Path(name).suffix else reason


def _upsert(rows, kind, level="error"):
    s = _schema()
    sql = (
        f"INSERT INTO {s}.{TABLE} (source_key, except_type, source_system, file_name, file_ext, file_size, reason, level, first_seen, last_seen, count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now(), 1) ON CONFLICT (source_key, except_type) DO UPDATE SET "
        f"source_system = EXCLUDED.source_system, file_name = EXCLUDED.file_name, file_ext = EXCLUDED.file_ext, "
        f"file_size = COALESCE(EXCLUDED.file_size, {TABLE}.file_size), reason = EXCLUDED.reason, last_seen = EXCLUDED.last_seen, "
        f"count = {TABLE}.count + 1"  # 크기를 모르는 기록(게시·적재 실패)이 앞서 안 크기를 지우지 않게
    )
    db = _db()
    try:
        for r in rows:
            ext = Path(r.get("file_name") or r["source_key"]).suffix.lower().lstrip(".") or None  # 소문자, 점 없음(판 0004)
            size = r.get("file_size")
            size = int(size) if size not in (None, "") else None
            db.q(sql, (r["source_key"], kind, r.get("source_system"), r.get("file_name"), ext, size, r["reason"], level))
    finally:
        _close(db)
    return len(rows)


def record(rows):
    """rows = [{source_key, source_system, file_name, reason, file_size(있으면)}] — 영구 이유만 skip 행으로 upsert(처음 본 시각은 그대로, 마지막 시각·횟수 갱신).
    반환: 쓴 행 수."""
    todo = [{**r, "reason": reason_of(r["file_name"], r["reason"])} for r in rows]
    todo = [r for r in todo if r["reason"] and r["source_key"]]
    if not todo:
        return 0
    _upsert(todo, "skip")
    print(f"[except] 영구 뺌 {len(todo)}건 기록({_schema()}.{TABLE} skip) — 다음 대상 목록(--skip-done)에서 뺌", flush=True)
    return len(todo)


def record_error(rows, kind="error", level="error", what="실패"):
    """rows = [{source_key, source_system, file_name, reason, file_size(있으면)}] — 파싱·적재 실패를 error 행으로 upsert(다음 실행은 다시 고름). 반환: 쓴 행 수.
    kind·level은 record_part(part·warn)가 바꿔 쓴다."""
    todo = [r for r in rows if r.get("source_key") and r.get("reason")]
    if todo:
        _upsert(todo, kind, level)
        print(f"[except] {what} {len(todo)}건 기록({_schema()}.{TABLE} {kind})", flush=True)
    return len(todo)


def note_error(rows, **kw):
    """record_error — 적어 두는 기록일 뿐이라 실패해도 부른 쪽(게시·적재·받기)은 계속(경고 한 줄 — run_pipeline.note_error와 같은 뜻)."""
    try:
        return record_error(rows, **kw)
    except Exception as ex:
        print(f"[except] 기록 못 씀({type(ex).__name__}) — 계속", file=sys.stderr, flush=True)
        return 0


def record_part(rows):
    """안 문서를 못 꺼낸 원본(pl-65 — 성한 안 파일은 붙여 적재됨)을 part 행(수준 warn)으로 — 기록만(대상 목록에서 빼지 않음, 실패해도 받기는 계속)."""
    return note_error(rows, kind="part", level="warn", what="안 문서 못 꺼냄")


SILVER_REASON = "실버만 게시 — 골드 전"


def record_silver(rows):
    """실버를 게시한 원본(pl-68)을 silver 행(수준 warn)으로 — 골드 적재가 성공하면 clear_silver가 지운다. 남은 행 = 골드 실패·중단·실버까지만 실행.
    기록만(대상 목록에서 빼지 않음, 실패해도 게시는 계속)."""
    return note_error([{**r, "reason": SILVER_REASON} for r in rows], kind="silver", level="warn", what="실버만 게시")


def clear_silver(keys):
    """골드 적재가 끝난 원본 키의 silver 행을 지운다(pl-68). 기록일 뿐이라 실패해도 적재는 계속(경고 한 줄). 반환: 받은 키 수."""
    keys = sorted({k for k in keys if k})
    if not keys:
        return 0
    try:
        db = _db()
        try:
            db.q(f"DELETE FROM {_schema()}.{TABLE} WHERE except_type = 'silver' AND source_key = ANY(%s)", (keys,))
        finally:
            _close(db)
    except Exception as ex:
        print(f"[except] silver 행 못 지움({type(ex).__name__}) — 계속", file=sys.stderr, flush=True)
    return len(keys)


def skipped_keys():
    """skip 행(영구 뺌)의 원본 키 집합 — error 행은 들지 않음."""
    db = _db()
    try:
        return {r["source_key"] for r in db.q(f"SELECT source_key FROM {_schema()}.{TABLE} WHERE except_type = 'skip'")}
    finally:
        _close(db)


def _error_cmd(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="pipeline.shared.except_docs error")
    ap.add_argument("--csv", required=True, help="문서 위치 표(run_pipeline batch.csv — s3_key·original_filename·source_system)")
    ap.add_argument("--reason", required=True, help="실패 이유(예 parse_failed·publish_failed·load_failed)")
    a = ap.parse_args(argv)
    with Path(a.csv).open(encoding="utf-8-sig", newline="") as fh:
        rows = [
            {
                "source_key": r["s3_key"],
                "source_system": r.get("source_system"),
                "file_name": r.get("original_filename"),
                "file_size": r.get("file_size"),
                "reason": a.reason,
            }
            for r in csv.DictReader(fh)
        ]
    record_error(rows)
    return 0


if __name__ == "__main__":
    from common.config import setarg
    from common.core.console import utf8_stdout

    setarg.apply()
    utf8_stdout()
    if sys.argv[1:2] != ["error"]:
        raise SystemExit("사용: python -m pipeline.shared.except_docs error --csv <문서 위치 표> --reason <이유>")
    raise SystemExit(_error_cmd(sys.argv[2:]))
