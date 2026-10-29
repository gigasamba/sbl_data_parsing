"""common.store.registry 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.registry`."""

import json
from pathlib import Path

from common.config.settings import COMMON
from common.store.registry import build, classify, diff_against, nightly_plan, scan


def selftest():
    import contextlib
    import tempfile

    from common.store.structdb import SqliteBackend, ensure_registry_schema

    out = Path(tempfile.mkdtemp())
    db_path = Path(tempfile.mkdtemp()) / "registry.sqlite"
    _env = contextlib.ExitStack()
    _env.enter_context(
        COMMON.env(STRUCT_BACKEND="sqlite")
    )  # PG를 전혀 건드리지 않음(시험 — 운영 DB 가드는 structdb.guard_not_prod가 별도로 봄) — 아래 _selftest_editions까지
    db = SqliteBackend(str(db_path))
    ensure_registry_schema(db)  # SCHEMA(ensure_schema)가 아님 — 독립 검토 BLOCK(10-08), doc_registry는 이 표 전용 함수로만

    def w(rel, rows_or_obj):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(rows_or_obj, list):
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_or_obj), encoding="utf-8")
        else:
            p.write_text(json.dumps(rows_or_obj, ensure_ascii=False), encoding="utf-8")

    def _row(db, key):
        """history()와 같은 조회(10-14 — history()는 mcp_server.services.search.registry로 옮김, 이 시험은 공통
        apply()·build()가 만든 doc_registry·doc_registry_seen 상태만 직접 봐야 해 로컬로 둠)."""
        rows = db.query("SELECT * FROM doc_registry WHERE doc_key=?", (key,))
        seen = db.query("SELECT * FROM doc_registry_seen WHERE doc_key=? ORDER BY build_id", (key,))
        return (rows[0] if rows else None), seen

    def _hidden(db):
        """hidden_set()과 같은 조회(옮긴 자리는 위 _row 참고) — hide()는 공통에 남아 있어 그 결과만 직접 확인."""
        return {r["doc_key"] for r in db.query("SELECT doc_key FROM doc_hidden WHERE hidden=1")}

    sa, sb, sd = "a" * 64, "b" * 64, "d" * 64  # 가짜 doc_key(64자 sha256 모양)

    # build 1 — A(성공 파싱)·B(실패 파싱)·D(곧 사라질 문서) 전부 처음 관측
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
    # a.pdf만 RDB 질의로 받음(doc_id 있음) — source=rdb · b.pdf는 doc_id 없는 S3 목록 건 — source=s3(독립 검토 minor 10-08)
    w(
        "parse/_source/manifest.jsonl",
        [
            {
                "file_name": "a.pdf",
                "uri": "s3://bkt/a.pdf",
                "key": "k/a.pdf",
                "etag": "e1",
                "size": 101,
                "doc_id": "FSM-1",
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {"file_name": "b.pdf", "uri": "s3://bkt/b.pdf", "key": "k/b.pdf", "etag": "e2", "size": 201},
        ],
    )
    diff1, b1 = build(out, db, build_id="b1")
    assert diff1["new"] == sorted([sa, sb, sd]) and diff1["changed"] == [] and diff1["deleted"] == [], diff1
    row_a, seen_a = _row(db, sa)
    assert row_a["status"] == "parsed" and row_a["first_seen"] == row_a["last_seen"] and len(seen_a) == 1
    assert row_a["source"] == "rdb" and row_a["doc_id"] == "FSM-1", row_a  # manifest에 doc_id 있음 → rdb
    row_b, _ = _row(db, sb)
    assert row_b["status"] == "failed"
    assert row_b["source"] == "s3", row_b  # manifest에 doc_id 없음(순수 s3 목록) → s3(local로 잘못 안 남음)

    # build 2 — A 그대로(unchanged) · B 재시도로 성공(changed) · C 새 문서(new) · D는 원본에서 사라짐(deleted)
    w(
        "dedup/fingerprints.jsonl",
        [
            {"path": "/src/a.pdf", "sha": sa, "size": 100, "mtime": 1000.0},
            {"path": "/src/b.pdf", "sha": sb, "size": 200, "mtime": 2000.0},
            {"path": "/src/c.pdf", "sha": "c" * 64, "size": 400, "mtime": 4000.0},
        ],
    )
    w(
        "parse/_rep/sources.jsonl",
        [
            {"doc_key": sa, "uri": "file:///src/a.pdf", "file_name": "a.pdf", "engine": "pymupdf"},
            {"doc_key": sb, "uri": "file:///src/b.pdf", "file_name": "b.pdf", "engine": "pymupdf"},
            {"doc_key": "c" * 64, "uri": "file:///src/c.pdf", "file_name": "c.pdf", "engine": "pymupdf"},
        ],
    )
    w(
        "parse/_rep/index.json",
        {
            "docs": [
                {"doc": "a.pdf", "engine": "pymupdf", "doc_key": sa},
                {"doc": "b.pdf", "engine": "pymupdf", "doc_key": sb},
                {"doc": "c.pdf", "engine": "pymupdf", "doc_key": "c" * 64},
            ]
        },
    )
    # OP9 — nightly_plan(읽기만, apply() 전): new(c.pdf)만 파싱 대상 · changed(b.pdf)·deleted(d.pdf)는 빠짐(사람 조치 전까지)
    observed2 = scan(out)
    plan2 = nightly_plan(db, observed2)
    assert plan2["parse_names"] == ["c.pdf"], plan2
    assert plan2["new"] == ["c" * 64] and plan2["changed"] == [sb] and plan2["deleted"] == [sd], plan2
    diff2, b2 = build(out, db, build_id="b2")
    assert diff2["new"] == ["c" * 64] and diff2["changed"] == [sb] and diff2["unchanged"] == [sa] and diff2["deleted"] == [sd], diff2
    row_d, seen_d = _row(db, sd)
    assert row_d["status"] == "deleted" and seen_d[-1]["status"] == "deleted"
    row_b2, seen_b = _row(db, sb)
    assert row_b2["status"] == "parsed" and len(seen_b) == 2  # b1(failed)·b2(parsed) — 바뀔 때만 늘어남

    # OP1 — apply()가 deleted(d)를 자동 hide(색인 행 삭제 없이, doc_registry 행도 그대로) — unhide·hidden_set은
    # mcp_server.services.search.registry로 옮김(10-14, R만 씀) — 이 시험은 hide() 자체(공통에 남음)와 doc_hidden 상태만 확인,
    # unhide 복구 왕복은 mcp_server.services.search.registry.selftest()가 맡음
    assert _hidden(db) == {sd}, _hidden(db)
    row_d_hidden, _ = _row(db, sd)
    assert row_d_hidden is not None and row_d_hidden["status"] == "deleted"  # doc_registry 행 삭제 없음(그대로 조회됨)

    # build 3 — 아무것도 안 바뀜 → 전부 unchanged, 이력 행이 안 늘어남(멱등)
    diff3, b3 = build(out, db, build_id="b3")
    assert diff3["new"] == [] and diff3["changed"] == [] and diff3["deleted"] == []
    assert sorted(diff3["unchanged"]) == sorted([sa, sb, "c" * 64])
    _, seen_a3 = _row(db, sa)
    assert len(seen_a3) == 1  # b1 그대로 — b3가 새 이력을 안 더함

    # build 4 — AD17① 준비: e·f·g 새 문서(원본 바이트 비교 시험용) · e는 단일 파트 MD5 ETag · f·g는 멀티파트(대시 포함) ETag
    se, sf, sg = "e" * 64, "f" * 64, "g" * 64
    w(
        "dedup/fingerprints.jsonl",
        [
            {"path": "/src/a.pdf", "sha": sa, "size": 100, "mtime": 1000.0},
            {"path": "/src/b.pdf", "sha": sb, "size": 200, "mtime": 2000.0},
            {"path": "/src/c.pdf", "sha": "c" * 64, "size": 400, "mtime": 4000.0},
            {"path": "/src/e.pdf", "sha": se, "size": 500, "mtime": 5000.0},
            {"path": "/src/f.pdf", "sha": sf, "size": 600, "mtime": 6000.0},
            {"path": "/src/g.pdf", "sha": sg, "size": 700, "mtime": 7000.0},
        ],
    )
    w(
        "parse/_rep/sources.jsonl",
        [
            {"doc_key": sa, "uri": "file:///src/a.pdf", "file_name": "a.pdf", "engine": "pymupdf"},
            {"doc_key": sb, "uri": "file:///src/b.pdf", "file_name": "b.pdf", "engine": "pymupdf"},
            {"doc_key": "c" * 64, "uri": "file:///src/c.pdf", "file_name": "c.pdf", "engine": "pymupdf"},
            {"doc_key": se, "uri": "file:///src/e.pdf", "file_name": "e.pdf", "engine": "pymupdf"},
            {"doc_key": sf, "uri": "file:///src/f.pdf", "file_name": "f.pdf", "engine": "pymupdf"},
            {"doc_key": sg, "uri": "file:///src/g.pdf", "file_name": "g.pdf", "engine": "pymupdf"},
        ],
    )
    w(
        "parse/_rep/index.json",
        {
            "docs": [
                {"doc": "a.pdf", "engine": "pymupdf", "doc_key": sa},
                {"doc": "b.pdf", "engine": "pymupdf", "doc_key": sb},
                {"doc": "c.pdf", "engine": "pymupdf", "doc_key": "c" * 64},
                {"doc": "e.pdf", "engine": "pymupdf", "doc_key": se},
                {"doc": "f.pdf", "engine": "pymupdf", "doc_key": sf},
                {"doc": "g.pdf", "engine": "pymupdf", "doc_key": sg},
            ]
        },
    )
    w(
        "parse/_source/manifest.jsonl",
        [
            {
                "file_name": "a.pdf",
                "uri": "s3://bkt/a.pdf",
                "key": "k/a.pdf",
                "etag": "e1",
                "size": 101,
                "doc_id": "FSM-1",
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {"file_name": "b.pdf", "uri": "s3://bkt/b.pdf", "key": "k/b.pdf", "etag": "e2", "size": 201},
            {
                "file_name": "e.pdf",
                "uri": "s3://bkt/e.pdf",
                "key": "k/e.pdf",
                "etag": "0123456789abcdef0123456789abcdef",
                "size": 501,
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {
                "file_name": "f.pdf",
                "uri": "s3://bkt/f.pdf",
                "key": "k/f.pdf",
                "etag": "0123456789abcdef0123456789abcdef-2",
                "size": 601,
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {
                "file_name": "g.pdf",
                "uri": "s3://bkt/g.pdf",
                "key": "k/g.pdf",
                "etag": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-3",
                "size": 701,
                "updated_at": "2026-10-01T00:00:00Z",
            },
        ],
    )
    diff4, b4 = build(out, db, build_id="b4")
    assert sorted(diff4["new"]) == sorted([se, sf, sg]), diff4
    assert diff4["changed"] == [] and diff4["touched"] == [], diff4

    # build 5 — e·f·g는 updated_at(mtime)만 바뀜, ETag·크기는 그대로(원본 바이트는 안 바뀜):
    #   e(단일 파트 MD5 ETag 같음) → touched 바로 확정 · f(멀티파트 ETag) → fetch_sha256으로 원본 바이트를 받아
    #   doc_key(원본 sha256)와 같아서 touched · g(멀티파트 ETag) → fetch_sha256이 다른 sha256을 돌려줘 changed(안전 쪽)
    w(
        "parse/_source/manifest.jsonl",
        [
            {
                "file_name": "a.pdf",
                "uri": "s3://bkt/a.pdf",
                "key": "k/a.pdf",
                "etag": "e1",
                "size": 101,
                "doc_id": "FSM-1",
                "updated_at": "2026-10-01T00:00:00Z",
            },
            {"file_name": "b.pdf", "uri": "s3://bkt/b.pdf", "key": "k/b.pdf", "etag": "e2", "size": 201},
            {
                "file_name": "e.pdf",
                "uri": "s3://bkt/e.pdf",
                "key": "k/e.pdf",
                "etag": "0123456789abcdef0123456789abcdef",
                "size": 501,
                "updated_at": "2026-10-02T00:00:00Z",
            },
            {
                "file_name": "f.pdf",
                "uri": "s3://bkt/f.pdf",
                "key": "k/f.pdf",
                "etag": "0123456789abcdef0123456789abcdef-2",
                "size": 601,
                "updated_at": "2026-10-02T00:00:00Z",
            },
            {
                "file_name": "g.pdf",
                "uri": "s3://bkt/g.pdf",
                "key": "k/g.pdf",
                "etag": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-3",
                "size": 701,
                "updated_at": "2026-10-02T00:00:00Z",
            },
        ],
    )
    observed5 = scan(out)

    def fake_fetch(cur_row):
        """가짜 Object Storage 바이트 조회(시험 전용 — 실접속 금지, 가짜 값만) — f는 doc_key와 같은 sha256(원본
        바이트 그대로) · g는 다른 sha256(원본 바이트가 실제로 바뀜) 반환."""
        return {sf: sf, sg: "0" * 64}.get(cur_row["doc_key"])

    diff5 = diff_against(db, observed5, fetch_sha256=fake_fetch)
    assert diff5["touched"] == sorted([se, sf]), diff5  # e: ETag 단일 파트 MD5라 바로 확정 · f: 멀티파트라 sha256 대조해 같음 확인
    assert sg in diff5["changed"], diff5  # g: 멀티파트 + sha256도 달라 changed
    diff5_nofetch = diff_against(db, observed5)  # fetch_sha256 없이 — f는 애매해서 changed(검증 전 touched로 단정 안 함)
    assert se in diff5_nofetch["touched"] and sf in diff5_nofetch["changed"] and sg in diff5_nofetch["changed"], diff5_nofetch

    # REGISTRY_ETAG_MD5=0(engine-qa 독립 검토 10-08) — ETag가 32자 16진수(MD5 형식)여도 그것만으로 touched 확정 안 함
    # (SSE-KMS·SSE-C 버킷은 형식이 같아도 내용 MD5가 아닐 수 있음) · 꺼도 멀티파트 fetch_sha256 대조 경로는 그대로 동작.
    current5 = {r["doc_key"]: r for r in db.query("SELECT * FROM doc_registry")}
    with COMMON.env(REGISTRY_ETAG_MD5="0"):
        assert classify(current5[se], observed5[se]) == "changed", "꺼진 상태 — fetch_sha256 없이 ETag 형식만으로 touched 금지"
        assert classify(current5[se], observed5[se], fetch_sha256=fake_fetch) == "changed"  # fake_fetch는 se를 모름(None)
        assert classify(current5[sf], observed5[sf], fetch_sha256=fake_fetch) == "touched"  # 멀티파트는 원래부터 sha256 대조 경로
    assert classify(current5[se], observed5[se]) == "touched"  # 기본(켬)으로 복귀 — 원래대로 ETag 형식만으로 확정

    diff5b, b5 = build(out, db, build_id="b5", fetch_sha256=fake_fetch)
    assert diff5b["touched"] == sorted([se, sf]) and sg in diff5b["changed"], diff5b
    row_e, seen_e = _row(db, se)
    assert row_e["mtime"] == "2026-10-02T00:00:00Z" and len(seen_e) == 1  # touched — mtime은 갱신되지만 판 이력은 안 늘어남(b4 1건 그대로)
    row_f, seen_f = _row(db, sf)
    assert row_f["mtime"] == "2026-10-02T00:00:00Z" and len(seen_f) == 1
    row_g, seen_g = _row(db, sg)
    assert row_g["mtime"] == "2026-10-02T00:00:00Z" and len(seen_g) == 2  # changed — 판 이력 1건 추가(b4 new, b5 changed)

    # OP9 — nightly_plan: touched는 unchanged와 같이 다룸(이미 성공했으면 재파싱 대상 아님) · changed는 reparse_keys 없으면 그대로 빠짐
    plan5 = nightly_plan(db, observed5, fetch_sha256=fake_fetch)
    assert se not in plan5["parse_names"] and sf not in [n for n in plan5["parse_names"]], plan5  # 이미 parsed — 재시도 대상 아님
    assert "e.pdf" not in plan5["parse_names"] and "f.pdf" not in plan5["parse_names"] and "g.pdf" not in plan5["parse_names"], plan5
    db.close()
    print(
        "[selftest] AD16/OP1/OP9 — scan·diff(new/changed/deleted)·build 멱등 · 자동 hide(색인 행 "
        "삭제 없음, unhide·history·hidden_set은 mcp_server.services.search.registry 몫)·nightly_plan(new만 파싱) 통과"
    )
    print(
        "[selftest] AD17① — 원본 바이트 비교: touched(ETag·크기 같음/멀티파트 ETag+sha256 같음) vs "
        "changed(sha256 다름·fetch_sha256 없이 애매) · touched는 판 이력·재파싱 대상 제외 통과"
    )

    _selftest_editions()
    _env.close()


def _selftest_editions():
    """AD17②·AD15(10-08) — 파싱 뒤 대표 글 비교(판 관계)·같은 내용 다른 형식 묶음. 위 selftest()와 다른
    out·DB(독립) — 기존 a~g 판정 시험 상태를 건드리지 않음."""
    import tempfile

    from common.store.structdb import SqliteBackend, ensure_registry_schema

    out = Path(tempfile.mkdtemp())
    db = SqliteBackend(str(Path(tempfile.mkdtemp()) / "registry2.sqlite"))
    ensure_registry_schema(db)

    def w(rel, rows_or_obj):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(rows_or_obj, list):
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_or_obj), encoding="utf-8")
        else:
            p.write_text(json.dumps(rows_or_obj, ensure_ascii=False), encoding="utf-8")

    def w_rep(name, text):
        p = out / "parse" / "_rep" / f"{name}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")

    def _row(db, key):
        """history()와 같은 조회(10-14 — mcp_server.services.search.registry로 옮김, 위 selftest()의 _row와 같은 이유)."""
        rows = db.query("SELECT * FROM doc_registry WHERE doc_key=?", (key,))
        seen = db.query("SELECT * FROM doc_registry_seen WHERE doc_key=? ORDER BY build_id", (key,))
        return (rows[0] if rows else None), seen

    sh, sh2 = "h" * 64, "h1" * 32  # 같은 문서(h.pdf), 바이트만 바뀜, 대표 글 완전히 같음 → same
    si, si2 = "i" * 64, "i1" * 32  # 같은 문서(i.pdf), 라벨은 같고 숫자(단가)만 바뀜 → changed_values
    sj, sj2 = "j" * 64, "j1" * 32  # 같은 문서(j.pdf), 글 자체가 달라짐(구조화 가능한 라벨:값이 없음) → different
    sk, sk2 = "k" * 64, "k1" * 32  # AD15 — 형식만 다른(.eml/.msg) 같은 내용, 대표 글 완전 일치 → content_group
    sl, sl2 = "l" * 64, "l1" * 32  # AD15 — 형식만 다른(.pdf/.docx) 같은 내용, 대표 글이 살짝 다름 → 5-gram 근접

    def fp(items):
        return [{"path": f"/src/{n}", "sha": s, "size": 100, "mtime": m} for n, s, m in items]

    def src(items):
        return [{"doc_key": s, "uri": f"file:///src/{n}", "file_name": n, "engine": "pymupdf"} for n, s in items]

    def idx(items):
        return {"docs": [{"doc": n, "engine": "pymupdf", "doc_key": s} for n, s in items]}

    v1 = [("h.pdf", sh), ("i.pdf", si), ("j.pdf", sj), ("k.eml", sk), ("k2.msg", sk2), ("l.pdf", sl), ("l2.docx", sl2)]
    w("dedup/fingerprints.jsonl", fp([(n, s, 1000.0) for n, s in v1]))
    w("parse/_rep/sources.jsonl", src(v1))
    w("parse/_rep/index.json", idx(v1))

    # CONTENT_GROUP_MIN_LEN(40) 넘기기 — 줄바꿈으로 분리(한 줄에 붙이면 extract_label_values가 "라벨: 값" 줄의
    # 값에 이 꼬리까지 통째로 집어삼켜 숫자만 다른 값 비교(changed_values)가 깨짐)
    long_tail = "\n추가 설명 문단이 이어지고 같은 문서를 조금 더 길게 채우기 위한 문장입니다"
    w_rep("h.pdf", "계약 금액: 1,000,000원" + long_tail)
    w_rep("i.pdf", "단가: 500" + long_tail)
    w_rep("j.pdf", "오리지널 문서 내용입니다" + long_tail)
    email_body = "이메일 본문 안내: 제품 배송 일정을 알려드립니다" + long_tail
    w_rep("k.eml", email_body)
    w_rep("k2.msg", email_body)  # 형식만 다름(.eml/.msg) — 대표 글이 완전히 같음(exact rep_sha 그룹)
    w_rep("l.pdf", "분기 보고서 초안 내용 전체" + long_tail)
    w_rep("l2.docx", "분기 보고서 초안 내용 전체" + long_tail + " 꼬리말")  # 형식만 다름(.pdf/.docx) — 거의 같지만 완전히는 안 같음

    diff1, b1 = build(out, db, build_id="e1")
    assert sorted(diff1["new"]) == sorted([sh, si, sj, sk, sk2, sl, sl2]), diff1
    row_h, _ = _row(db, sh)
    assert row_h["rep_sha"] and row_h["rep_pairs"], row_h  # update_rep_fingerprints가 new를 바로 채움
    row_k, _ = _row(db, sk)
    assert row_k["content_group"] == row_k["doc_key"] or row_k["content_group"] is not None  # k·k2 완전 일치 그룹
    row_k2, _ = _row(db, sk2)
    assert row_k["content_group"] == row_k2["content_group"], (row_k, row_k2)
    row_l, _ = _row(db, sl)
    row_l2, _ = _row(db, sl2)
    assert row_l["content_group"] == row_l2["content_group"], (row_l, row_l2)  # 5-gram 근접(완전 일치 아님)으로도 묶임
    row_j, _ = _row(db, sj)
    assert row_j["content_group"] != row_k["content_group"], "서로 다른 문서가 묶이면 안 됨(오탐)"

    # build 2 — h·i·j는 바이트가 바뀌어 새 doc_key(이름은 그대로), k·k2·l·l2는 안 바뀜
    v2 = [("h.pdf", sh2), ("i.pdf", si2), ("j.pdf", sj2), ("k.eml", sk), ("k2.msg", sk2), ("l.pdf", sl), ("l2.docx", sl2)]
    w("dedup/fingerprints.jsonl", fp([(n, s, 2000.0) for n, s in v2]))
    w("parse/_rep/sources.jsonl", src(v2))
    w("parse/_rep/index.json", idx(v2))
    w_rep("h.pdf", "계약 금액: 1,000,000원" + long_tail)  # 대표 글 완전히 같음(다시 저장만 함) → same
    w_rep("i.pdf", "단가: 600" + long_tail)  # 단가만 500→600(숫자만) → changed_values
    w_rep("j.pdf", "전혀 다른 내용으로 교체된 문서" + long_tail)  # 구조화 라벨:값 없음(글 자체가 다름) → different

    diff2, b2 = build(out, db, build_id="e2")
    assert sorted(diff2["new"]) == sorted([sh2, si2, sj2]) and sorted(diff2["deleted"]) == sorted([sh, si, sj]), diff2
    editions = diff2["editions"]
    assert editions[sh2] == "same", editions
    assert editions[si2] == "changed_values", editions
    assert editions[sj2] == "different", editions
    row_h2, _ = _row(db, sh2)
    assert row_h2["edition_of"] == sh and not row_h2["value_changes"], row_h2
    row_i2, _ = _row(db, si2)
    assert row_i2["edition_of"] == si, row_i2
    changes = json.loads(row_i2["value_changes"])
    assert len(changes) == 1 and changes[0]["before"] == "500" and changes[0]["after"] == "600", changes
    row_j2, _ = _row(db, sj2)
    assert row_j2["edition_of"] is None, row_j2  # 글이 다름 — 판 연결 없음(보통 새 판)

    # engine-qa MAJOR(10-08) ① — 견적서처럼 라벨(단가)이 품목마다 반복되는 표: 2번째 행만 바뀌어도 검출돼야 함
    # (라벨만으로 중복 제거하던 예전 코드는 첫 행만 남겨 이 변화를 통째로 놓치고 'same'으로 오판했다).
    sq, sq2 = "q" * 64, "q1" * 32
    w("dedup/fingerprints.jsonl", fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq, 1000.0)]))
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq)]))
    w_rep("q.pdf", "단가: 100\n단가: 200" + long_tail)
    build(out, db, build_id="e2b")  # q.pdf 첫 등록(new)

    w("dedup/fingerprints.jsonl", fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq2, 3000.0)]))
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq2)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq2)]))
    w_rep("q.pdf", "단가: 100\n단가: 250" + long_tail)  # 1번째 단가(100)는 그대로, 2번째 단가만 200→250
    diff2b, _ = build(out, db, build_id="e2c")
    assert diff2b["editions"][sq2] == "changed_values", diff2b["editions"]
    row_q2, _ = _row(db, sq2)
    q_changes = json.loads(row_q2["value_changes"])
    assert len(q_changes) == 1 and q_changes[0]["before"] == "200" and q_changes[0]["after"] == "250", q_changes

    # engine-qa MAJOR(10-08) ① 안전망 — rep_sha가 다른데 추적한 (라벨,순번) 쌍이 전부 값까지 같으면(자유 문장처럼
    # 구조화 못 하는 부분만 바뀜) 'same'으로 단정하지 않고 'different'로 보낸다(이전엔 'same'을 돌려줬음).
    sr, sr2 = "r" * 64, "r1" * 32
    w("dedup/fingerprints.jsonl", fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq2, 3000.0), ("r.pdf", sr, 1000.0)]))
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq2), ("r.pdf", sr)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq2), ("r.pdf", sr)]))
    w_rep("r.pdf", "오리지널 서두 문장입니다\n단가: 500" + long_tail)
    build(out, db, build_id="e2d")
    w("dedup/fingerprints.jsonl", fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq2, 3000.0), ("r.pdf", sr2, 4000.0)]))
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq2), ("r.pdf", sr2)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq2), ("r.pdf", sr2)]))
    w_rep("r.pdf", "완전히 바뀐 서두 문장입니다\n단가: 500" + long_tail)  # 추적되는 "단가: 500"은 그대로, 자유 문장만 바뀜
    diff2d, _ = build(out, db, build_id="e2e")
    assert diff2d["editions"][sr2] == "different", diff2d["editions"]  # 'same'이 아님(안전 쪽)
    row_r2, _ = _row(db, sr2)
    assert row_r2["edition_of"] is None, row_r2

    # engine-qa MAJOR(10-08) ② — 다른 고객·폴더의 같은 파일 이름(베이스네임만 같음)은 이어지면 안 됨
    sdupA, sdupB = "dupa" * 16, "dupb" * 16
    w(
        "dedup/fingerprints.jsonl",
        fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq2, 3000.0), ("r.pdf", sr2, 4000.0)])
        + [{"path": "/src/customerA/dup.pdf", "sha": sdupA, "size": 100, "mtime": 1000.0}],
    )
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq2), ("r.pdf", sr2), ("dup.pdf", sdupA)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq2), ("r.pdf", sr2), ("dup.pdf", sdupA)]))
    w_rep("dup.pdf", "고객A 전용 보고서 내용" + long_tail)
    build(out, db, build_id="e2f")  # customerA/dup.pdf 등록(new)

    w(
        "dedup/fingerprints.jsonl",
        fp([(n, s, 2000.0) for n, s in v2] + [("q.pdf", sq2, 3000.0), ("r.pdf", sr2, 4000.0)])
        + [{"path": "/src/customerB/dup.pdf", "sha": sdupB, "size": 100, "mtime": 1000.0}],
    )  # customerA 쪽은 사라짐(deleted)
    w("parse/_rep/sources.jsonl", src(v2 + [("q.pdf", sq2), ("r.pdf", sr2), ("dup.pdf", sdupB)]))
    w("parse/_rep/index.json", idx(v2 + [("q.pdf", sq2), ("r.pdf", sr2), ("dup.pdf", sdupB)]))
    w_rep("dup.pdf", "고객B 전용 보고서 내용(전혀 다른 고객)" + long_tail)  # 같은 베이스네임, 다른 폴더·다른 내용
    diff_dup, _ = build(out, db, build_id="e2g")
    assert sdupA in diff_dup["deleted"] and sdupB in diff_dup["new"], diff_dup
    assert sdupB not in diff_dup["editions"], diff_dup["editions"]  # 이름만 같다고 이어지면 안 됨(전엔 이어졌을 버그)
    row_dupB, _ = _row(db, sdupB)
    assert row_dupB["edition_of"] is None, row_dupB

    # REGISTRY_EDITIONS=0 — 이 단계 전체를 안 돌림(새 doc_key여도 rep_sha 등은 그대로 NULL, diff에 editions 키 없음)
    sm = "m" * 64
    base_fp = fp([(n, s, 2000.0) for n, s in v2]) + [
        {"path": "/src/customerB/dup.pdf", "sha": sdupB, "size": 100, "mtime": 1000.0},
        {"path": "/src/q.pdf", "sha": sq2, "size": 100, "mtime": 3000.0},
        {"path": "/src/r.pdf", "sha": sr2, "size": 100, "mtime": 4000.0},
    ]
    w("dedup/fingerprints.jsonl", base_fp + [{"path": "/src/m.pdf", "sha": sm, "size": 100, "mtime": 3000.0}])
    tail_docs = [
        ("q.pdf", sq2),
        ("r.pdf", sr2),
        ("dup.pdf", sdupB),
        ("m.pdf", sm),
    ]  # status='seen'으로 안 꺼지게(무관한 부수효과 방지) 유지
    w("parse/_rep/sources.jsonl", src(v2 + tail_docs))
    w("parse/_rep/index.json", idx(v2 + tail_docs))
    w_rep("m.pdf", "새 문서" + long_tail)
    with COMMON.env(REGISTRY_EDITIONS="0"):
        diff3, b3 = build(out, db, build_id="e3")
    assert diff3["new"] == [sm] and "editions" not in diff3, diff3
    row_m, _ = _row(db, sm)
    assert row_m["rep_sha"] is None and row_m["content_group"] is None, row_m  # 꺼짐 — 바이트 동일(새 칸 그대로 NULL)

    db.close()
    print(
        "[selftest] AD17②(10-08) — 파싱 뒤 대표 글 비교: same(글 완전히 같음·새 판 아님)·changed_values(숫자만 "
        "바뀜·바뀐 값 목록)·different(글 자체가 다름) 통과"
    )
    print(
        "[selftest] AD15(10-08) — 같은 내용 다른 형식(.eml/.msg·.pdf/.docx) content_group 묶음(완전 일치·5-gram "
        "근접) · 서로 다른 문서 오탐 없음 · REGISTRY_EDITIONS=0 바이트 동일 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
