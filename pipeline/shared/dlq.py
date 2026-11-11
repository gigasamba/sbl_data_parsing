"""실패 문서 관리 상태(pl-69) — applog.dlq_doc. 로그 이력(except_doc_info)과 별도로 관리한다."""

import argparse
import json
import sys

import common
from pipeline.shared import except_docs

TABLE = "dlq_doc"
MAX_ATTEMPTS = 3
STATUSES = ("pending", "dead", "resolved")


def _query(sql, params=None):
    """DLQ 조회·변경은 연결을 반드시 닫는다. 오류 정책은 호출자가 정한다."""
    db = except_docs._db()
    try:
        return db.q(sql, params)
    finally:
        except_docs._close(db)


def record_failure(rows, *, max_attempts=MAX_ATTEMPTS):
    """호스트 CLI의 실패 upsert(호출당 1회). resolved는 새 실패 주기, dead는 사람이 requeue할 때까지 유지."""
    todo = {r["source_key"]: r for r in rows if r.get("source_key") and r.get("reason")}
    if not todo:
        return 0
    # ON CONFLICT 자체가 행 잠금을 잡아 동시 실패도 유실되지 않는다. dead_at은 전이 때만 바꾼다.
    count = f"CASE WHEN {TABLE}.status = 'resolved' THEN 1 WHEN {TABLE}.status = 'dead' THEN {TABLE}.attempts ELSE {TABLE}.attempts + 1 END"
    dead = f"({TABLE}.status = 'dead' OR ({count}) >= %(maximum)s)"
    sql = (
        f"INSERT INTO {except_docs._schema()}.{TABLE} "
        "(source_key, source_system, file_name, stage, last_reason, attempts, status, dead_at, pipeline_version) "
        "VALUES (%(key)s, %(system)s, %(name)s, %(stage)s, %(reason)s, 1, "
        "CASE WHEN %(maximum)s <= 1 THEN 'dead' ELSE 'pending' END, "
        "CASE WHEN %(maximum)s <= 1 THEN now() END, %(version)s) "
        "ON CONFLICT (source_key) DO UPDATE SET "
        f"source_system = COALESCE(EXCLUDED.source_system, {TABLE}.source_system), "
        f"file_name = COALESCE(EXCLUDED.file_name, {TABLE}.file_name), stage = EXCLUDED.stage, "
        "last_reason = EXCLUDED.last_reason, pipeline_version = EXCLUDED.pipeline_version, "
        f"attempts = {count}, status = CASE WHEN {dead} THEN 'dead' ELSE 'pending' END, "
        f"dead_at = CASE WHEN {TABLE}.status = 'dead' THEN {TABLE}.dead_at WHEN {dead} THEN now() END, "
        f"first_failed_at = CASE WHEN {TABLE}.status = 'resolved' THEN now() ELSE {TABLE}.first_failed_at END, "
        "last_failed_at = now(), resolved_at = NULL "
        "RETURNING source_key, attempts, status, last_reason, (status = 'dead' AND dead_at = last_failed_at) AS became_dead"
    )
    for key, r in todo.items():
        result = _query(
            sql,
            {
                "key": key,
                "system": r.get("source_system"),
                "name": r.get("file_name"),
                "stage": r.get("stage") or r["reason"].split("_", 1)[0],
                "reason": r["reason"],
                "maximum": max_attempts,
                "version": common.pipeline_version(),
            },
        )[0]
        if result["became_dead"]:
            print(
                f"[DLQ] 확인 필요 — {key} ({result['attempts']}회 실패, 마지막 이유 {result['last_reason']}) — "
                "조회: python -m pipeline.shared.dlq list --status dead",
                flush=True,
            )
    return len(todo)


def resolve(keys):
    """gold 완료·영구 뺌 키를 resolved로 보존한다. 기록 실패는 경고 한 줄 뒤 계속(clear_silver와 같은 정책)."""
    keys = sorted({k for k in keys if k})
    if not keys:
        return 0
    try:
        _query(
            f"UPDATE {except_docs._schema()}.{TABLE} SET status = 'resolved', resolved_at = now() "
            "WHERE source_key = ANY(%s) AND status IN ('pending','dead')",
            (keys,),
        )
    except (Exception, SystemExit) as ex:
        print(f"[DLQ] 해소 기록 못 씀({type(ex).__name__}) — 계속", file=sys.stderr, flush=True)
    return len(keys)


def list_rows(status="all"):
    statuses = tuple(status.split(",")) if isinstance(status, str) else tuple(status)
    if statuses != ("all",) and (not statuses or any(s not in STATUSES for s in statuses)):
        raise ValueError("모르는 DLQ 상태")
    filtered = statuses != ("all",)
    return _query(
        f"SELECT * FROM {except_docs._schema()}.{TABLE} "
        + ("WHERE status = ANY(%s) " if filtered else "")
        + "ORDER BY last_failed_at, source_key",
        (list(statuses),) if filtered else None,
    )


def excluded_keys():
    """pending ∪ dead 키 → 행 사전(완료 해소·dead 제외에 사용)."""
    return {r["source_key"]: r for r in list_rows(("pending", "dead"))}


def requeue(keys=None, all_dead=False):
    """사람이 dead를 pending(attempts=0)으로 되돌린다. 다음 실패는 첫 실패로 센다."""
    keys = sorted(set(keys or []))
    if not keys and not all_dead:
        return 0
    rows = _query(
        f"UPDATE {except_docs._schema()}.{TABLE} SET status = 'pending', attempts = 0, "
        "dead_at = NULL, resolved_at = NULL WHERE status = 'dead' "
        + ("" if all_dead else "AND source_key = ANY(%s) ")
        + "RETURNING source_key",
        None if all_dead else (keys,),
    )
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.shared.dlq")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="실패 문서 상태 조회")
    ls.add_argument("--status", default="dead", help="pending·dead·resolved(쉼표로 여러 값) 또는 all")
    ls.add_argument("--json", action="store_true")
    rq = sub.add_parser("requeue", help="dead 문서를 사람이 다시 넣기")
    choice = rq.add_mutually_exclusive_group(required=True)
    choice.add_argument("--key", action="append")
    choice.add_argument("--all-dead", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "requeue":
        print(f"[DLQ] 다시 넣음 {requeue(a.key, a.all_dead)}건", flush=True)
    else:
        rows = list_rows(a.status)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, default=str))
        else:
            print(f"[DLQ] {a.status} {len(rows)}건", flush=True)
            for r in rows:
                print(f"{r['source_key']}\t{r['status']}\t{r['attempts']}회\t{r['stage']}\t{r['last_reason']}")
    return 0


if __name__ == "__main__":
    from common.config import setarg
    from common.core.console import utf8_stdout

    setarg.apply()
    utf8_stdout()
    raise SystemExit(main())
