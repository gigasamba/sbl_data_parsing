"""pipeline.load.publish_parse_result 시험.
S9b(C-54 ②, 사용자 10-28 — 기록만): 기대값을 지금 서버 동작에 맞춤 — 업로드 폴더에 `<stem>_<date>_meta.json`·`source.json`이 없음
(pre-refactor 서버 사본이 일부러 뺌 — `_meta.json`은 EDW에, `source.json`은 내부용). source.json에 기대던 방어선(재실행 업로드 건너뜀
`skip_exists`·키 충돌 거부 `error_key_collision`)은 서버에서 늘 꺼져 있어 11-02에 코드째 지움(C-54 ② — test_publish_guard도 지움). 산출물 만들기는 `make_fixture()`로."""

import json
from pathlib import Path

from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.load.publish_parse_result import rep_md_key, run


class A:
    pass


def make_fixture():
    """publish 시험 산출물(문서 4개 — ok·failed·not_parsed·DRM)과 인자 a(dry-run) → (임시 폴더, out, a)."""
    import tempfile

    d = Path(tempfile.mkdtemp())
    out = d / "output"
    (out / "_source_files").mkdir(parents=True)
    (out / "parse" / "_source").mkdir(parents=True)
    (out / "parse" / "_rep").mkdir(parents=True)
    (out / "prepared").mkdir(parents=True)

    docs = {"a.pdf": "content-a", "b.pdf": "content-b", "c.pdf": "content-c", "d.pdf": "content-d-drm"}
    for name, content in docs.items():
        (out / "_source_files" / name).write_text(content, encoding="utf-8")
    manifest = [
        {"file_name": "a.pdf", "doc_id": "1", "key": "docs/a.pdf", "uri": "s3://bkt/docs/a.pdf", "original_filename": "a.pdf"},
        {"file_name": "b.pdf", "doc_id": "2", "key": "docs/b.pdf", "uri": "s3://bkt/docs/b.pdf", "original_filename": "b.pdf"},
        {"file_name": "c.pdf", "doc_id": "3", "key": "docs/c.pdf", "uri": "s3://bkt/docs/c.pdf", "original_filename": "c.pdf"},
        {"file_name": "d.pdf", "doc_id": "4", "key": "docs/d.pdf", "uri": "s3://bkt/docs/d.pdf", "original_filename": "d.pdf"},
    ]
    (out / "parse" / "_source" / "manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in manifest), encoding="utf-8"
    )
    rep_docs = [
        {"doc": "a.pdf", "engine": "pymupdf", "format": ".pdf_text", "acc": 0.99, "pages": 2, "doc_key": "k" * 64},
        {"doc": "b.pdf", "engine": None, "format": ".pdf_text", "reason": "성공한 엔진 없음"},
    ]
    # c.pdf는 색인에 없음 → not_parsed · d.pdf는 DRM이라 엔진에 안 보냄(prepare.py가 먼저 걸러 색인에도 없음)
    (out / "parse" / "_rep" / "index.json").write_text(json.dumps({"docs": rep_docs}, ensure_ascii=False), encoding="utf-8")
    (out / "parse" / "_rep" / "a.pdf.json").write_text(
        json.dumps({"text": "본문 A", "tables_std": []}, ensure_ascii=False), encoding="utf-8"
    )
    (out / "parse" / "parse_summary.json").write_text(json.dumps({"types": {}}), encoding="utf-8")
    # 사용자 10-14 — 엔진별 원본·그림 기록(VLM 모델·맥락)도 함께 올림 · signals/ 같은 엔진 아닌 폴더는 제외
    for eng, ver in (("pymupdf", "1.28.2"), ("rapidocr_ko", "3.9.2")):
        (out / "parse" / eng).mkdir(parents=True)
        (out / "parse" / eng / "a.pdf.json").write_text(
            json.dumps({"text": f"{eng} 원본", "provenance": {"engine": eng, "engine_version": ver}}, ensure_ascii=False), encoding="utf-8"
        )
    (out / "parse" / "runs.jsonl").write_text(
        json.dumps(  # pymupdf는 runs.jsonl로 · rapidocr_ko는 옛 산출물처럼 provenance로
            {"doc": "a.pdf", "engine": "pymupdf", "error": None, "engine_version": "1.28.2", "p0_key": "pk", "run_id": "r1"}
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "parse" / "signals").mkdir(parents=True)
    (out / "parse" / "signals" / "a.pdf.json").write_text("{}", encoding="utf-8")
    (out / "parse" / "_images").mkdir(parents=True)
    (out / "parse" / "_images" / "index.jsonl").write_text(
        json.dumps(
            {
                "image_id": "a.pdf#p1#i1",
                "doc": "a.pdf",
                "caption": "그림 1",
                "mentions": ["본문 언급"],
                "vlm": {"model": "qwen-vl", "summary": "요약"},
                "provenance": {"model": "qwen-vl", "prompt_id": "figure_describe@v3"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "prepared" / "skipped.jsonl").write_text(
        json.dumps({"file": "d.pdf", "reason": "drm_fasoo", "sha256": "x"}) + "\n", encoding="utf-8"
    )

    a = A()
    a.out, a.manifest, a.source_dir, a.rep, a.summary, a.skipped, a.keep = str(out), None, None, None, None, None, None
    a.source_system, a.version, a.parse_date, a.reparse, a.apply = "FileStorageMap", "v1", "2026-10-08", None, False
    return d, out, a


def selftest():
    import shutil

    d, out, a = make_fixture()
    r = run(a)
    assert r["rows_planned"] == 4 and r["missing_file"] == 0, r
    assert r["by_status"] == {"ok": 1, "failed": 1, "not_parsed": 1, "skipped_drm": 1}, r["by_status"]
    assert r["upload_statuses"] == ["ok", "partial"] and r["upload_plan"] == {"eligible": 1, "excluded": 3}, r
    no_up = {s["status"]: s["upload"] for s in r["sample_rows"]}
    assert no_up == {"ok": True, "failed": False, "not_parsed": False, "skipped_drm": False}, no_up
    reasons = {s["status"]: s["no_upload_reason"] for s in r["sample_rows"] if not s["upload"]}
    assert all(reasons.values()) and "EDW에도 안 들어감" in reasons["failed"] and "EDW에도 안 들어감" in reasons["skipped_drm"], reasons
    assert r["sample_rows"][0]["rep_key"] == "FileStorageMap/docs/", r["sample_rows"][
        0
    ]  # S9 정리(Q7 a) — 서버가 rep_key 꼴을 바꿈(파일 이름 단 없음 — 기대값만 맞춤)

    os_dir, db_path = d / "os", d / "edw.sqlite"
    with (
        pc.PIPE.env(PM_BUCKET=f"file://{os_dir}"),
        COMMON.env(RDB_SQLITE=str(db_path), RUN_ENV="local"),
    ):  # S7c — 시험하는 코드가 객체만 읽음(os.environ 안 건드림) · 가짜 EDW(RDB_SQLITE)는 local 전용 — 이미지(서버 RUN_ENV)에서도 시험 안에서만 local(이미지 관문 10-30)
        a.apply = True
        r1 = run(a)
        # SI39 — ok(a)만 .md 업로드 · EDW는 ok(a)+not_parsed(c) 2행(failed·skipped_drm은 ⑥로 EDW 제외, 보고서로만)
        assert r1["result"] == {
            "uploaded": 1,
            "upload_excluded": 3,
            "upload_skip_existing": 0,
            "inserted": 2,
            "edw_skip_existing": 0,
            "edw_excluded_drm_failed": 2,
            "rows": 4,
        }, r1["result"]
        md_files = [p for p in os_dir.rglob("*.md")]
        assert len(md_files) == 1 and md_files[0].name == "a_2026-10-08.md", md_files  # 원본(.pdf)은 전혀 안 올라감
        assert "본문 A" in md_files[0].read_text(encoding="utf-8")
        assert not any(p.is_file() and p.suffix == ".pdf" for p in os_dir.rglob("*")), "원본 파일이 올라감(SI39① 위반)"
        folder = md_files[0].parent
        got = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        assert got == [
            "a_2026-10-08.json",
            "a_2026-10-08.md",
            "engine/pymupdf_1.28.2_a.json",
            "engine/rapidocr_ko_3.9.2_a.json",
            "engine/vlm_qwen-vl_a.jsonl",
        ], got  # signals/는 엔진 아님 — 제외
        # S9b(C-54 ②) — 서버 동작: _meta.json·source.json은 안 올림(옛 기대값의 meta 내용 단언 3줄은 대상 파일이 없어 뺌)
        assert not (folder / "a_2026-10-08_meta.json").exists() and not (folder / "source.json").exists(), got
        assert json.loads((folder / "engine" / "pymupdf_1.28.2_a.json").read_text(encoding="utf-8"))["text"] == "pymupdf 원본"
        assert json.loads((folder / "a_2026-10-08.json").read_text(encoding="utf-8"))["text"] == "본문 A"
        assert not list((Path(a.out) / "publish" / "_md_tmp").glob("*")), "임시 파일이 남음"
        excluded_md = Path(r1["excluded_report"]).read_text(encoding="utf-8")
        assert "failed" in excluded_md and "skipped_drm" in excluded_md and "docs/b.pdf" in excluded_md, excluded_md

        r2 = run(a)  # 같은 걸 재실행 — a·c의 (source_system, 원본 키)가 이미 있음 → EDW 건너뜀
        assert r2["result"]["inserted"] == 0 and r2["result"]["edw_skip_existing"] == 2, r2  # SI39 — INSERT만, UPDATE 없음
        # pl-61 — KEY가 이미 있는 a는 올리기 전에 걸러 업로드 0(EDW 행 없는 고아 객체 없음)
        assert r2["result"]["uploaded"] == 0 and r2["result"]["upload_skip_existing"] == 1, r2["result"]
        assert len(list(os_dir.rglob("*.md"))) == 1, list(os_dir.rglob("*.md"))

        a.version = "v2"  # 판이 달라도 KEY(출처+원본 키)가 같으면 EDW는 그대로 건너뜀
        r3 = run(a)
        assert r3["result"]["inserted"] == 0, r3

        # SI39③ — 명시적 재파싱(--reparse)만 새 날짜 폴더 · 옛 결과(a_2026-10-08.md)는 그대로
        reparse_f = d / "reparse.txt"
        reparse_f.write_text("docs/a.pdf\n", encoding="utf-8")
        a.reparse = str(reparse_f)
        old_md = next(os_dir.rglob("a_2026-10-08.md"))  # 처음 올린 결과
        old_content = old_md.read_text(encoding="utf-8")
        r4 = run(a)
        assert r4["result"]["uploaded"] == 1 and r4["result"]["inserted"] == 1, r4["result"]  # 재파싱 1건만 새로 올라감·새 행
        # S9b(C-54 ②) — 옛 `len(md_files2) == 2`(r2·r3이 업로드를 건너뛴다는 전제 — 11-02에 지운 source.json 방어선)·재파싱 새 날짜의 meta 단언 대신:
        import sqlite3

        dates = {r[0] for r in sqlite3.connect(db_path).execute("select parse_date from ParsingMeta where source_key='docs/a.pdf'")}
        new_dates = dates - {"2026-10-08"}
        assert "2026-10-08" in dates and len(new_dates) == 1, dates  # 옛 행 그대로 + 재파싱 새 날짜 행 하나
        new_md = list(os_dir.rglob(f"a_{next(iter(new_dates))}.md"))
        assert len(new_md) == 1 and new_md[0] != old_md, new_md  # 새 날짜 이름으로 따로 올림
        assert old_md.read_text(encoding="utf-8") == old_content, "재파싱인데 옛 결과가 바뀜(덮어쓰기 금지 위반)"
        a.reparse = None
        a.apply = False
        assert run(a)["sample_rows"][0]["raw_files"] == [
            "<stem>_<date>.json",
            "engine/pymupdf_1.28.2_<stem>.json",
            "engine/rapidocr_ko_3.9.2_<stem>.json",
            "engine/vlm_qwen-vl_<stem>.jsonl",
        ]  # S9b(C-54 ②) — <stem>_<date>_meta.json 없음(서버 동작)
        a.apply = True

        total = sqlite3.connect(db_path).execute("select count(*) from ParsingMeta").fetchone()[0]
        assert total == 3, total  # a(최초) + c(not_parsed) + a(재파싱, 새 parse_date) = 3 — failed·skipped_drm은 전혀 안 들어감

        with pc.PIPE.env(
            PM_UPLOAD_STATUSES="ok,partial,failed"
        ):  # PM1에서 넓히기로 정하면 env로 — failed도 업로드 대상이 됨(EDW는 여전히 제외)
            a.apply = False
            r5 = run(a)
            assert r5["upload_plan"]["eligible"] == 1, (
                r5
            )  # ok(a)만 — failed(b)는 업로드 허용해도 EDW_EXCLUDED라 render_md용 _rep/b.pdf.json이 없어 제외됨

    shutil.rmtree(d, ignore_errors=True)
    print(
        "[selftest] SI39 — dry-run 쓰기 0 · 대표 결과(.md)만 올라감(원본은 전혀 안 올라감) · KEY(출처+원본 전체 "
        "키)가 이미 있으면 EDW는 건너뜀(UPDATE 없음 — source.json 방어선은 11-02에 지움, C-54 ②) · "
        "--reparse만 새 날짜 이름·새 EDW 행(옛 결과 보존) · _meta.json·source.json 안 올림(서버 동작) · "
        "DRM·실패는 EDW 제외하고 보고서로만 통과"
    )


def test_main():  # 옛 `if a.selftest:` 갈래(main() 안)
    selftest()


# (원천 이름, 원본 키, 기대 결과 키) — 원본 키가 이미 원천 이름으로 시작하면 원천 이름을 한 번만(PC 폴더 원천 · 대소문자 무시)
KEY_CASES = [
    ("CRMS", "CRMS/u1/a.pdf", "P/CRMS/u1/a_D.md"),
    ("CRMS", "crms/u1/a.pdf", "P/crms/u1/a_D.md"),
    ("FileStorageMap", "SFDC/u1/a.pdf", "P/FileStorageMap/SFDC/u1/a_D.md"),  # 서버 — 원천 이름이 키 첫 마디가 아님
    ("FileStorageMap", "docs/a.pdf", "P/FileStorageMap/docs/a_D.md"),
    ("CRMS", "CRMS.pdf", "P/CRMS/CRMS_D.md"),  # 첫 마디가 파일 이름뿐 — 폴더로 안 봄
]


def test_rep_md_key_prefix_once():
    for system, key, want in KEY_CASES:
        assert rep_md_key("P", system, key, "D") == want, (system, key)


def test_stage_dropped_docs():
    """pl-02 — 받기(stage)가 뺀 문서만 든 문서 폴더(run_pipeline의 건너뜀 — parse/_rep·요약 없음): 중복(keep.txt에 없음)은 EDW에
    skipped_dup 행, DRM은 행 없이 보고서로만. sha256은 중복 거르기와 같은 함수(contract.file_hash — 소문자 16진 64자)."""
    import re
    import shutil
    import sqlite3
    import tempfile

    from common.core.contract import file_hash

    cases = [  # (파일, 내용, keep.txt에 있음, skipped.jsonl 이유, 기대 EDW parse_status(None = 행 없음))
        ("dup.pdf", "same-as-done", False, None, "skipped_dup"),
        ("drm.pdf", "<## FASOO", True, "drm_fasoo", None),
    ]
    for name, body, in_keep, reason, want in cases:
        d = Path(tempfile.mkdtemp())
        out = d / "output"
        for sub in ("_source_files", "parse/_source", "dedup", "prepared/_records"):
            (out / sub).mkdir(parents=True)
        (out / "_source_files" / name).write_text(body, encoding="utf-8")
        man = {"file_name": name, "doc_id": "1", "key": f"docs/{name}", "uri": f"s3://bkt/docs/{name}", "original_filename": name}
        (out / "parse" / "_source" / "manifest.jsonl").write_text(json.dumps(man) + "\n", encoding="utf-8")
        (out / "dedup" / "keep.txt").write_text((name if in_keep else "") + "\n", encoding="utf-8")
        if reason:
            (out / "prepared" / "_records" / "skipped.jsonl").write_text(
                json.dumps({"file": name, "reason": reason}) + "\n", encoding="utf-8"
            )
        a = A()
        a.out, a.manifest, a.source_dir, a.rep, a.summary, a.skipped, a.keep = str(out), None, None, None, None, None, None
        a.source_system, a.version, a.parse_date, a.reparse, a.apply = "FileStorageMap", "v1", "2026-11-05", None, True
        db_path = d / "edw.sqlite"
        with pc.PIPE.env(PM_BUCKET=f"file://{d / 'os'}"), COMMON.env(RDB_SQLITE=str(db_path), RUN_ENV="local"):
            r = run(a)
        rows = sqlite3.connect(db_path).execute("select parse_status, sha256 from ParsingMeta").fetchall()
        if want is None:
            assert rows == [] and r["result"]["edw_excluded_drm_failed"] == 1, (name, rows, r)
        else:
            sha = file_hash(out / "_source_files" / name)
            assert rows == [(want, sha)] and re.fullmatch(r"[0-9a-f]{64}", sha), (name, rows)
        assert r["result"]["uploaded"] == 0, (name, r)
        shutil.rmtree(d, ignore_errors=True)
