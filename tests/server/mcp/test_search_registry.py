"""mcp_server.services.search.registry 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.registry`."""

import json

from common.store import registry as REG
from mcp_server import config as mc
from mcp_server.services.search.registry import hidden_set, history, report_by_date, unhide


def selftest():
    with mc.senv(
        STRUCT_BACKEND="sqlite"
    ):  # PG를 전혀 건드리지 않음(시험 — 운영 DB 가드는 structdb.guard_not_prod가 별도로 봄) · 설정 객체 덮기(S7d — 끝나면 되돌림)
        _selftest_body()


def _selftest_body():
    import tempfile
    from pathlib import Path

    from common.store.structdb import SqliteBackend, ensure_registry_schema

    out = Path(tempfile.mkdtemp())
    db = SqliteBackend(str(Path(tempfile.mkdtemp()) / "registry.sqlite"))
    ensure_registry_schema(db)

    def w(rel, rows_or_obj):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(rows_or_obj, list):
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_or_obj), encoding="utf-8")
        else:
            p.write_text(json.dumps(rows_or_obj, ensure_ascii=False), encoding="utf-8")

    sa, sb, sd, sc = "a" * 64, "b" * 64, "d" * 64, "c" * 64

    # build 1(2026-10-01) — A(성공)·B(실패)·D(곧 사라질 문서) 전부 처음 관측
    w(
        "dedup/fingerprints.jsonl",
        [
            {"path": "/src/a.pdf", "sha": sa, "size": 100, "mtime": 1000.0},
            {"path": "/src/b.pdf", "sha": sb, "size": 200, "mtime": 2000.0},
            {"path": "/src/d.pdf", "sha": sd, "size": 300, "mtime": 3000.0},
        ],
    )
    w(
        "parse/_rep/sources.jsonl",
        [
            {"doc_key": sa, "uri": "file:///src/a.pdf", "file_name": "a.pdf", "engine": "pymupdf"},
            {"doc_key": sd, "uri": "file:///src/d.pdf", "file_name": "d.pdf", "engine": "pymupdf"},
        ],
    )
    w(
        "parse/_rep/index.json",
        {
            "docs": [
                {"doc": "a.pdf", "engine": "pymupdf", "doc_key": sa},
                {"doc": "b.pdf", "engine": None, "reason": "성공한 엔진 없음"},
                {"doc": "d.pdf", "engine": "pymupdf", "doc_key": sd},
            ]
        },
    )
    REG.build(out, db, build_id="b1", seen_at="2026-10-01T00:00:00Z")
    row_a, seen_a = history(db, sa)
    assert row_a["status"] == "parsed" and len(seen_a) == 1
    row_b, seen_b = history(db, sb)
    assert row_b["status"] == "failed" and len(seen_b) == 1

    # build 2(2026-10-02) — B 성공으로 바뀜(changed) · C 새 문서(new) · D는 원본에서 사라짐(deleted) → apply()가 자동 hide
    w(
        "dedup/fingerprints.jsonl",
        [
            {"path": "/src/a.pdf", "sha": sa, "size": 100, "mtime": 1000.0},
            {"path": "/src/b.pdf", "sha": sb, "size": 200, "mtime": 2000.0},
            {"path": "/src/c.pdf", "sha": sc, "size": 400, "mtime": 4000.0},
        ],
    )
    w(
        "parse/_rep/sources.jsonl",
        [
            {"doc_key": sa, "uri": "file:///src/a.pdf", "file_name": "a.pdf", "engine": "pymupdf"},
            {"doc_key": sb, "uri": "file:///src/b.pdf", "file_name": "b.pdf", "engine": "pymupdf"},
            {"doc_key": sc, "uri": "file:///src/c.pdf", "file_name": "c.pdf", "engine": "pymupdf"},
        ],
    )
    w(
        "parse/_rep/index.json",
        {
            "docs": [
                {"doc": "a.pdf", "engine": "pymupdf", "doc_key": sa},
                {"doc": "b.pdf", "engine": "pymupdf", "doc_key": sb},
                {"doc": "c.pdf", "engine": "pymupdf", "doc_key": sc},
            ]
        },
    )
    REG.build(out, db, build_id="b2", seen_at="2026-10-02T00:00:00Z")
    row_d, seen_d = history(db, sd)
    assert row_d["status"] == "deleted" and seen_d[-1]["status"] == "deleted"

    # OP1 — apply()의 자동 hide(sd, 색인 행 삭제 없음) · unhide로 되돌릴 수 있음(감사 필드 기록) · 다시 hide(공통 함수)
    assert hidden_set(db) == {sd}, hidden_set(db)
    unhide(db, sd, by="tester", reason="복구 시험")
    assert hidden_set(db) == set()
    REG.hide(db, sd, by="tester", reason="다시 숨김(시험)")
    assert hidden_set(db) == {sd}

    # DET1 Fix3 — 날짜별 보고(읽기만)
    rep1 = report_by_date(db, "2026-10-01")
    assert rep1["new"] == 3 and rep1["changed"] == 0 and rep1["deleted"] == 0 and rep1["touched"] == 0, rep1
    assert sorted(d["doc_key"] for d in rep1["docs"]) == sorted([sa, sb, sd])
    rep2 = report_by_date(db, "2026-10-02")
    assert rep2["new"] == 1 and rep2["changed"] == 1 and rep2["deleted"] == 1, rep2
    events = {d["doc_key"]: d["event"] for d in rep2["docs"]}
    assert events[sc] == "new" and events[sb] == "changed" and events[sd] == "deleted"
    rep_all = report_by_date(db, "2026-10-01", "2026-10-02")
    assert rep_all["new"] == 4 and rep_all["changed"] == 1 and rep_all["deleted"] == 1, rep_all

    # pl-32(사용자 10-30) — 재시도 횟수 상한 없음: 실패 문서(e)는 다음 밤에도 늘 파싱 대상, 보고에 "재시도 중단" 칸 없음
    se = "e" * 64
    w(
        "dedup/fingerprints.jsonl",
        [
            {"path": "/src/a.pdf", "sha": sa, "size": 100, "mtime": 1000.0},
            {"path": "/src/b.pdf", "sha": sb, "size": 200, "mtime": 2000.0},
            {"path": "/src/c.pdf", "sha": sc, "size": 400, "mtime": 4000.0},
            {"path": "/src/e.pdf", "sha": se, "size": 500, "mtime": 9000.0},
        ],
    )
    w(
        "parse/_rep/sources.jsonl",
        [
            {"doc_key": sa, "uri": "file:///src/a.pdf", "file_name": "a.pdf", "engine": "pymupdf"},
            {"doc_key": sb, "uri": "file:///src/b.pdf", "file_name": "b.pdf", "engine": "pymupdf"},
            {"doc_key": sc, "uri": "file:///src/c.pdf", "file_name": "c.pdf", "engine": "pymupdf"},
        ],
    )
    w(
        "parse/_rep/index.json",
        {
            "docs": [
                {"doc": "a.pdf", "engine": "pymupdf", "doc_key": sa},
                {"doc": "b.pdf", "engine": "pymupdf", "doc_key": sb},
                {"doc": "c.pdf", "engine": "pymupdf", "doc_key": sc},
                {"doc": "e.pdf", "engine": None, "reason": "실패"},
            ]
        },
    )
    REG.build(out, db, build_id="b3", seen_at="2026-10-03T00:00:00Z")
    rep3 = report_by_date(db, "2026-10-03")
    assert "retry_stopped" not in rep3 and "retry_stopped_docs" not in rep3, rep3
    for _ in range(3):  # 몇 밤 실패해도 멈추지 않음
        REG.build(out, db, seen_at="2026-10-04T00:00:00Z")
        assert "e.pdf" in REG.nightly_plan(db, REG.scan(out))["parse_names"]

    db.close()
    print("[selftest] AD16/OP1 — history(읽기 전용 조회) · hidden_set·unhide(색인 행 안 건드림, 복구 왕복) 통과")
    print("[selftest] DET1 Fix2/Fix3 — report_by_date(날짜별 new/changed/deleted·구간 합) · 실패 문서 늘 재시도(pl-32) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
