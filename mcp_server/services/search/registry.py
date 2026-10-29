#!/usr/bin/env python3
"""문서 대장(doc_registry) — 검색 MCP(R) 전용 조회·숨김 복구·날짜별 보고(AD16/OP1/DET1 Fix3, 10-14 common.store.registry
에서 옮김 — 검색 이미지(R)만 쓴다: registry_cli.py의 show·report·hide·unhide, retriever.py의 hidden_set). 핵심 집계
(scan·diff_against·apply·build, 파싱·구조화도 쓴다)·hide()·retry_max()는 common.store.registry에 그대로 남아 있다."""

import json
import time

from common.store import registry as REG


def unhide(db, doc_key, by, reason=None, at=None):
    """숨김 복구(사람 조치) — 같은 표에 hidden=0으로 upsert(되돌릴 수 있게, 색인 행은 건드린 적이 없어 그대로)."""
    at = at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    db.execute("INSERT OR REPLACE INTO doc_hidden (doc_key, hidden, reason, by, at) VALUES (?,?,?,?,?)", (doc_key, 0, reason, by, at))


def hidden_set(db):
    """지금 숨김 상태(hidden=1)인 doc_key 집합 — doc_hidden 표가 아직 없으면(build·hide를 한 번도 안 했음) 빈 집합
    (검색은 필터 없이 그대로, 바이트 동일 — 읽기 전용 호출자(검색)가 ensure_registry_schema를 부르지 않게)."""
    try:
        rows = db.query("SELECT doc_key FROM doc_hidden WHERE hidden=1")
    except Exception:
        return set()
    return {r["doc_key"] for r in rows}


def history(db, doc_key):
    """→ (doc_registry 행 또는 None, doc_registry_seen 행 목록 — build_id 순)."""
    row = db.query("SELECT * FROM doc_registry WHERE doc_key=?", (doc_key,))
    seen = db.query("SELECT * FROM doc_registry_seen WHERE doc_key=? ORDER BY build_id", (doc_key,))
    return (row[0] if row else None), seen


def report_by_date(db, since, until=None):
    """DET1 Fix3 — 날짜별 변경 보고(읽기만, 스키마 안 바꿈·`cli/registry.py report`). doc_registry_seen(doc_key,
    build_id,names,status,seen_at)을 seen_at 날짜(YYYY-MM-DD, UTC 그대로 — 저장된 문자열의 앞 10자)로 걸러
    new·changed·deleted를 센다: 그 doc_key의 **전체 이력 중 가장 이른** 행이면 new(날짜 필터와 무관하게 전체
    이력을 봄 — 그래야 "지난달 등록·이번 달 변경"을 changed로, "이번 달 처음 등록"만 new로 올바르게 가름),
    status=='deleted'면 deleted, 그 밖(같은 doc_key의 두 번째 이후 행, 삭제 아님)이면 changed.
    touched(AD17①, 원본 바이트가 안 바뀌고 날짜만 바뀜)는 모듈 docstring대로 **애초에** doc_registry_seen에
    행이 안 남는다(의도적 설계 — 재처리·변경 보고 대상이 아님) — 이 보고도 그 설계를 그대로 따르므로 touched는
    늘 0(과거 일별로 추적할 이력이 없다는 뜻이지 이 함수가 놓친 게 아님).
    retries stopped(DET1 Fix2) — doc_registry_seen에 쌓이는 이력이 아니라 nightly_plan()과 같은 **지금** 상태
    (doc_registry.fail_count ≥ retry_max())의 스냅숏 — last_seen이 [since,until] 구간인 문서만 이 날짜 구간
    보고에 넣는다(과거 그 날짜에 실제로 멈췄었는지의 이력이 아니라 "그 구간에 마지막으로 관측됐고 지금 멈춰
    있는" 문서 — retry_max()==0이면 기능 자체가 꺼져 있어 늘 0).
    → {"since","until","new","changed","touched","deleted","retry_stopped", "docs"(날짜 구간 new/changed/deleted
    문서 목록, doc_key·names·event·seen_at), "retry_stopped_docs"(doc_key·names·fail_count)}."""
    until = until or since
    rows = db.query("SELECT doc_key, build_id, names, status, seen_at FROM doc_registry_seen ORDER BY seen_at, build_id")
    first_build = {}
    for r in rows:
        first_build.setdefault(r["doc_key"], r["build_id"])
    docs = []
    for r in rows:
        d = (r["seen_at"] or "")[:10]
        if not (since <= d <= until):
            continue
        if r["status"] == "deleted":
            event = "deleted"
        elif first_build.get(r["doc_key"]) == r["build_id"]:
            event = "new"
        else:
            event = "changed"
        docs.append({"doc_key": r["doc_key"], "names": json.loads(r["names"] or "[]"), "event": event, "seen_at": r["seen_at"]})
    from collections import Counter

    counts = Counter(d["event"] for d in docs)
    cap = REG.retry_max()
    stopped_docs = []
    if cap:
        for row in db.query("SELECT doc_key, names, fail_count, last_seen FROM doc_registry"):
            ls = (row.get("last_seen") or "")[:10]
            if (row.get("fail_count") or 0) >= cap and since <= ls <= until:
                stopped_docs.append(
                    {"doc_key": row["doc_key"], "names": json.loads(row.get("names") or "[]"), "fail_count": row.get("fail_count")}
                )
    return {
        "since": since,
        "until": until,
        "new": counts.get("new", 0),
        "changed": counts.get("changed", 0),
        "touched": 0,
        "deleted": counts.get("deleted", 0),
        "retry_stopped": len(stopped_docs),
        "docs": sorted(docs, key=lambda d: (d["seen_at"], d["doc_key"])),
        "retry_stopped_docs": stopped_docs,
    }
