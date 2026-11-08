"""pipeline.load.publish_parse_result 시험.
S9b(C-54 ②, 사용자 10-28 — 기록만): 기대값을 지금 서버 동작에 맞춤 — 업로드 폴더에 `<stem>_<date>_meta.json`·`source.json`이 없음
(pre-refactor 서버 사본이 일부러 뺌 — `source.json`은 내부용). source.json에 기대던 방어선(재실행 업로드 건너뜀
`skip_exists`·키 충돌 거부 `error_key_collision`)은 서버에서 늘 꺼져 있어 11-02에 코드째 지움(C-54 ② — test_publish_guard도 지움). 산출물 만들기는 `make_fixture()`로.
처리 기록(op-17): EDW에 쓰지 않고 `publish/silver.jsonl`(적재가 gold doc 칸으로) · 이미 gold에 있는 문서는 올리지 않음 · 파싱 실패는 except_doc_info error."""

import json
from pathlib import Path

from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.load.publish_parse_result import SILVER_FILE, rep_md_key, run
from tests.server.pipeline.goldseed import seed


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
    (out / "prepared" / "_records").mkdir(parents=True, exist_ok=True)
    (out / "prepared" / "_records" / "skipped.jsonl").write_text(
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
    assert all(reasons.values()) and "보고서로만" in reasons["failed"] and "보고서로만" in reasons["skipped_drm"], reasons
    assert r["sample_rows"][0]["rep_key"] == "FileStorageMap/docs/", r["sample_rows"][
        0
    ]  # S9 정리(Q7 a) — 서버가 rep_key 꼴을 바꿈(파일 이름 단 없음 — 기대값만 맞춤)

    import sqlite3

    os_dir = d / "os"
    with (
        pc.PIPE.env(PM_BUCKET=f"file://{os_dir}"),
        COMMON.env(PG_STANDIN_DIR=str(d / "pg"), RUN_ENV="local"),
    ):  # S7c — 시험하는 코드가 객체만 읽음(os.environ 안 건드림) · gold·applog는 PC 대역(임시 폴더) — 이미지에서도 시험 안에서만 local
        a.apply = True
        r1 = run(a)
        # SI39 — ok(a)만 .md 업로드 · failed·skipped_drm은 보고서로만
        assert r1["result"] == {
            "uploaded": 1,
            "upload_excluded": 3,
            "upload_skip_existing": 0,
            "excluded_drm_failed": 2,
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
        # S9b(C-54 ②) — 서버 동작: _meta.json·source.json은 안 올림
        assert not (folder / "a_2026-10-08_meta.json").exists() and not (folder / "source.json").exists(), got
        assert json.loads((folder / "engine" / "pymupdf_1.28.2_a.json").read_text(encoding="utf-8"))["text"] == "pymupdf 원본"
        assert json.loads((folder / "a_2026-10-08.json").read_text(encoding="utf-8"))["text"] == "본문 A"
        assert not list((Path(a.out) / "publish" / "_md_tmp").glob("*")), "임시 파일이 남음"
        excluded_md = Path(r1["excluded_report"]).read_text(encoding="utf-8")
        assert "failed" in excluded_md and "skipped_drm" in excluded_md and "docs/b.pdf" in excluded_md, excluded_md
        # op-17 — 처리 기록 파일: 올린 문서 한 줄(적재가 gold doc 칸으로)
        silver_f = Path(a.out) / "publish" / SILVER_FILE
        silver = [json.loads(x) for x in silver_f.read_text(encoding="utf-8").splitlines()]
        assert len(silver) == 1, silver
        rec = silver[0]
        assert (rec["doc_name"], rec["source_key"], rec["parse_status"], rec["silver_version"]) == ("a.pdf", "docs/a.pdf", "ok", "v1"), rec
        assert rec["silver_bucket"] == f"file://{os_dir}" and rec["silver_key"].endswith("/a_2026-10-08.md"), rec
        assert len(rec["sha256"]) == 64 and rec["parsed_at"].endswith("+09:00") and isinstance(rec["engines"], list), rec
        cn = sqlite3.connect(d / "pg" / "applog.sqlite")
        errs = cn.execute("select source_key, except_type, reason from except_doc_info").fetchall()
        cn.close()
        assert errs == [("docs/b.pdf", "error", "parse_failed")], errs  # 파싱 실패 — 기록만(다음 실행이 다시 고름)

        seed([{"file_path": "docs/a.pdf", "source_system": "FileStorageMap"}])  # a가 gold에 적재됨
        r2 = run(a)  # 같은 걸 재실행 — a는 이미 gold에 있음 → 올리지 않음(pl-61)
        assert r2["result"]["uploaded"] == 0 and r2["result"]["upload_skip_existing"] == 1, r2["result"]
        assert len(list(os_dir.rglob("*.md"))) == 1, list(os_dir.rglob("*.md"))
        assert silver_f.read_text(encoding="utf-8") == "", "올리지 않은 문서의 처리 기록"

        # SI39③ — 명시적 재파싱(--reparse)만 새 이름 · 옛 결과(a_2026-10-08.md)는 그대로
        reparse_f = d / "reparse.txt"
        reparse_f.write_text("docs/a.pdf\n", encoding="utf-8")
        a.reparse = str(reparse_f)
        old_md = next(os_dir.rglob("a_2026-10-08.md"))  # 처음 올린 결과
        old_content = old_md.read_text(encoding="utf-8")
        r4 = run(a)
        assert r4["result"]["uploaded"] == 1, r4["result"]  # 재파싱 1건만 새로 올라감
        new_md = [p for p in os_dir.rglob("a_*.md") if p != old_md]
        assert len(new_md) == 1, new_md  # 새 이름으로 따로 올림
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

        with pc.PIPE.env(PM_UPLOAD_STATUSES="ok,partial,failed"):  # PM1에서 넓히기로 정하면 env로 — failed도 업로드 대상이 됨
            a.apply = False
            r5 = run(a)
            assert r5["upload_plan"]["eligible"] == 1, r5  # ok(a)만 — failed(b)는 업로드 허용해도 render_md용 _rep/b.pdf.json이 없어 제외됨

    shutil.rmtree(d, ignore_errors=True)
    print(
        "[selftest] SI39 — dry-run 쓰기 0 · 대표 결과(.md)만 올라감(원본은 전혀 안 올라감) · 처리 기록 silver.jsonl · "
        "gold에 이미 있는 문서는 올리지 않음 · --reparse만 새 이름(옛 결과 보존) · _meta.json·source.json 안 올림(서버 동작) · "
        "DRM·실패는 보고서로만(실패는 except_doc_info error) 통과"
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
    """pl-02 — 받기(stage)가 뺀 문서만 든 문서 폴더(run_pipeline의 건너뜀 — parse/_rep·요약 없음): 중복(keep.txt에 없음)·DRM 모두
    올리지 않고 처리 기록도 없다(중복은 candidate_ready가 except_doc_info skip으로 남김 — op-17). DRM은 보고서로만."""
    import shutil
    import tempfile

    cases = [  # (파일, 내용, keep.txt에 있음, skipped.jsonl 이유, 기대 excluded_drm_failed)
        ("dup.pdf", "same-as-done", False, None, 0),
        ("drm.pdf", "<## FASOO", True, "drm_fasoo", 1),
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
        with pc.PIPE.env(PM_BUCKET=f"file://{d / 'os'}"), COMMON.env(PG_STANDIN_DIR=str(d / "pg"), RUN_ENV="local"):
            r = run(a)
        silver = (out / "publish" / SILVER_FILE).read_text(encoding="utf-8")
        assert r["result"]["uploaded"] == 0 and r["result"]["excluded_drm_failed"] == want and silver == "", (name, r, silver)
        shutil.rmtree(d, ignore_errors=True)
