"""pipeline.extract.candidate_ready 시험."""

import contextlib
import json
from pathlib import Path

import pipeline.extract.candidate_ready as M
from common.core.contract import jl
from pipeline import config as pc
from pipeline.extract.candidate_ready import (
    _safe_join,
    _safe_name,
    finish,
    resolve,
)


def mark_done(state, done_names, is_s3):
    """시험용 — 파싱이 끝난 것처럼 처리 기록(processed.jsonl)만 남긴다(운영은 finish()가 같은 줄을 쓰고 원본도 지움)."""
    assert is_s3
    man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
    with (state / "processed.jsonl").open("a", encoding="utf-8") as f:
        for n in done_names:
            r = man[n]
            f.write(json.dumps({"key": r["key"], "etag": r["etag"], "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")


def selftest():
    import tempfile

    dest = Path(tempfile.mkdtemp())  # 11-01 — 시험 표본(sample)·스트리밍 plan() 사례는 기능과 함께 지움

    # 독립 보안 검토 BLOCKER 2: S3 키의 `\`·`:`·`/`를 전부 지워 평면 이름으로 — 윈도 절대경로·상위 폴더 조작 방지
    cleaned = _safe_name(r"pre/fix/C:\Windows\doc.pdf", "pre/fix/")
    assert "\\" not in cleaned and ":" not in cleaned and cleaned.endswith("doc.pdf")  # 구분자·드라이브 표기 다 지움
    assert "/" not in _safe_name("pre/../../etc/passwd", "pre/")  # "/"를 전부 지워 실제 경로 구분자가 안 남음
    # 독립 검토 MAJOR: Windows 예약 장치 이름 — 대소문자 무시·확장자 있어도 적용
    assert _safe_name("docs/CON.pdf", "docs/") == "_CON.pdf"
    assert _safe_name("docs/con", "docs/") == "_con"
    assert _safe_name("docs/Com1.docx", "docs/") == "_Com1.docx"
    assert _safe_name("docs/contract.pdf", "docs/") == "contract.pdf"  # CON으로 시작해도 전체 이름이 다르면 그대로
    f = _safe_join(dest, "normal.pdf")
    assert f == dest / "normal.pdf"
    try:
        _safe_join(dest, "..")  # 정리돼도 만약을 대비한 마지막 방어선(해석 결과가 dest 밖이면 거부)
        raise AssertionError("범위 밖 이름을 받아들임")
    except ValueError:
        pass
    print("[selftest] X2 — S3 키 이름 정리(\\·:·/ 제거)·받는 폴더 밖 쓰기 거부 통과")

    _selftest_rdb_cols()
    _selftest_filestoragemap()
    _selftest_same_key_new_version()
    _selftest_finish_keep()


class _FakeS3:
    """가짜 Object Storage(selftest 전용) — {(bucket,key): (etag, bytes)}만 앎. 실제 네트워크·boto3 없이 head_object·
    download_file만. head_object는 ETag·ContentLength(= bytes 길이) 둘 다 돌려줌 — etag 열이 없는 표의 크기 대조 시험용."""

    def __init__(self, objs):
        self.objs = objs

    def head_object(self, Bucket, Key):
        etag, content = self.objs[(Bucket, Key)]
        return {"ETag": f'"{etag}"', "ContentLength": len(content)}

    def download_file(self, Bucket, Key, path):
        _, content = self.objs[(Bucket, Key)]
        Path(path).write_bytes(content)


def _selftest_rdb_cols():
    """AD44 — 열 이름이 다른 표(extract.connections.rdb.columns로 맞춤) · key가 s3://버킷/… 꼴이면 그 버킷 · 2회차 0건."""
    import tempfile

    real_s3 = M._s3
    d = Path(tempfile.mkdtemp())
    p = d / "loc.csv"
    p.write_text("doc_id,object_key,size_bytes\n" + "".join(f"d{i},s3://rag-docs/clients/d{i}.pdf,4\n" for i in range(3)), encoding="utf-8")
    M._s3 = lambda: _FakeS3({("rag-docs", f"clients/d{i}.pdf"): ("unused", b"docA") for i in range(3)})
    try:
        with pc.PIPE.env(RDB_COL_DOC_ID="doc_id", RDB_COL_KEY="object_key", RDB_COL_SIZE="size_bytes"):
            _, names, state = resolve(f"rdb:csv:{p}", d)
            assert names == ["d0", "d1", "d2"], names
            man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
            assert all(r["uri"] == f"s3://rag-docs/clients/{n}.pdf" for n, r in man.items()), man
            mark_done(state, names, is_s3=True)
            assert resolve(f"rdb:csv:{p}", d)[1] == []
    finally:
        M._s3 = real_s3
    print("[selftest] AD44 — 열 이름 맞춤(columns)·s3:// 키의 버킷·2회차 0건 통과")


def _selftest_filestoragemap():
    """AD44(c) — 실 EDW 표 AI.FileStorageMap 꼴(id·content_version_id·s3_key·original_filename·file_size, etag·
    bucket 열 없음) 합성 csv로: 받기(이름 충돌 구분 포함) → 2회차 0건 → 크기 불일치 참고 기록 → source_uri 형식 ·
    TABLE_ID_RE가 AI.FileStorageMap(대소문자 섞인 스키마.표)을 통과하는지."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3

    state_root = Path(tempfile.mkdtemp())
    csv_path = state_root / "file_storage_map.csv"
    # 5행 — id=1·4는 같은 original_filename(report.pdf, 이름 충돌 구분 시험)
    rows = [
        ("1", "101", "docs/a.pdf", "report.pdf", "4"),
        ("2", "102", "docs/b.pdf", "summary.pdf", "4"),
        ("3", "103", "docs/c.pdf", "contract.pdf", "4"),
        ("4", "104", "docs/d.pdf", "report.pdf", "4"),
        ("5", "105", "docs/e.pdf", "notes.pdf", "4"),
    ]
    csv_path.write_text(
        "id,content_version_id,s3_key,original_filename,file_size\n" + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8"
    )
    objs = {("fsm-bucket", f"docs/{c}.pdf"): (f"etag-unused-{c}", b"docA") for c in "abcde"}  # 4바이트 = file_size와 일치
    M._s3 = lambda: _FakeS3(objs)
    env = contextlib.ExitStack()
    env.enter_context(pc.PIPE.env(RDB_BUCKET="fsm-bucket"))  # S7c — 설정 객체 덮어쓰기(os.environ은 안 바뀜)
    try:
        table = f"csv:{csv_path}"
        local_dir, names1, state = resolve(f"rdb:{table}", state_root)
        assert len(names1) == 5, names1
        assert {"1__report.pdf", "4__report.pdf"} <= set(names1), names1  # 이름 충돌 — doc_id 접두로 구분
        assert "summary.pdf" in names1 and "contract.pdf" in names1 and "notes.pdf" in names1
        from common.core import contract as ids

        man1 = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
        for n in names1:
            uri = ids.make_source_uri(n, local_dir / n)
            assert uri == man1[n]["uri"] and uri == f"s3://fsm-bucket/{man1[n]['key']}", uri  # 요건 ⑤ source_uri 형식
            assert man1[n]["original_filename"] and man1[n]["content_version_id"], man1[n]  # 요건 ⑦ — 있는 칸은 그대로
        mark_done(state, names1, is_s3=True)

        # 2회차 — 전부 처리 기록됐으니 0건(ETag 없는 표라도 _rdb_is_done이 키 존재만으로 판정)
        _, names2, _ = resolve(f"rdb:{table}", state_root)
        assert names2 == [], names2
        print("[selftest] AD44(c) — FileStorageMap: 전부 받기(이름 충돌 구분)·2회차 0건·source_uri 통과")

        # 크기 불일치 — 별도 소규모 표(etag 열도 없음 → 크기 대조 경로)
        state2 = state_root / "mismatch"
        state2.mkdir()
        bad_csv = state_root / "mismatch.csv"
        bad_csv.write_text(
            "id,content_version_id,s3_key,original_filename,file_size\n10,201,docs/good.pdf,good.pdf,4\n11,202,docs/bad.pdf,bad.pdf,999\n",
            encoding="utf-8",
        )
        M._s3 = lambda: _FakeS3(
            {("fsm-bucket", "docs/good.pdf"): ("x", b"good"), ("fsm-bucket", "docs/bad.pdf"): ("x", b"bad!")}
        )  # 실제 길이 4 ≠ RDB 999
        local3, names3, state3 = resolve(f"rdb:csv:{bad_csv}", state2)
        assert names3 == ["bad.pdf", "good.pdf"], (
            names3
        )  # 2026-10-15(운영) — 크기 불일치는 참고 기록만 남기고 그대로 받음(식별은 key·sha256, 옛 거부 동작 폐지)
        mm = jl(state3 / "size_mismatch.log")
        assert len(mm) == 1 and mm[0]["size_rdb"] == 999 and mm[0]["size_store"] == 4, mm
        print(
            "[selftest] AD44(c) — FileStorageMap: etag 열 없어 크기(ContentLength) 대조 → 불일치는 참고 기록(size_mismatch.log)·다운로드 진행 통과"
        )
    finally:
        M._s3 = real_s3
        env.close()


def _selftest_same_key_new_version():
    """AD44(c) — 독립 검토 BLOCK: etag 없는 표에서 같은 s3_key에 새 id(새 content_version_id)가 들어오면(같은 경로에
    새 파일을 올리는 EDW 흐름) 키만 보고 "이미 처리됨"으로 오판해 영영 못 받던 버그. id=1(key=a) 처리 → id=2 같은
    key(새 판) 추가 → 2회차에 1건(id=2) 받음 → 3회차 0건(둘 다 처리 기록됐으니 since 전진)."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3

    state_root = Path(tempfile.mkdtemp())
    csv_path = state_root / "versions.csv"
    header = "id,content_version_id,s3_key,original_filename,file_size\n"
    csv_path.write_text(header + "1,101,docs/same.pdf,same.pdf,4\n", encoding="utf-8")
    objs = {("fsm-bucket", "docs/same.pdf"): ("etag-unused", b"docA")}  # 4바이트 = file_size
    M._s3 = lambda: _FakeS3(objs)
    env = contextlib.ExitStack()
    env.enter_context(pc.PIPE.env(RDB_BUCKET="fsm-bucket"))  # S7c — 설정 객체 덮어쓰기(os.environ은 안 바뀜)
    try:
        table = f"csv:{csv_path}"
        _, names1, state = resolve(f"rdb:{table}", state_root)
        assert names1 == ["same.pdf"], names1
        mark_done(state, names1, is_s3=True)

        # id=2 — 같은 s3_key에 새 content_version_id(새 판) 추가(원본 object는 새 내용으로 덮였다고 가정, 길이는 같음)
        csv_path.write_text(header + "1,101,docs/same.pdf,same.pdf,4\n2,102,docs/same.pdf,same.pdf,4\n", encoding="utf-8")
        _, names2, state2 = resolve(f"rdb:{table}", state_root)
        assert names2 == ["same.pdf"], names2  # 키만 보면 0건이 돼야 하지만 새 판(id=2)이므로 1건 받아야 함
        mark_done(state2, names2, is_s3=True)

        _, names3, _ = resolve(f"rdb:{table}", state_root)
        assert names3 == [], names3  # 둘 다 처리 기록됐으니 since가 2까지 전진 — 3회차는 0건
        print("[selftest] AD44(c) — 같은 s3_key에 새 id(새 판): 키만으론 영구 누락됐을 것 → 2회차 1건 받음·3회차 0건 통과")
    finally:
        M._s3 = real_s3
        env.close()


def _selftest_finish_keep():
    """SI39 요건⑧(2026-10-08) — 파싱이 끝나면 원본을 즉시 지운다(보존 스위치 KEEP_LOCAL_ORIGINALS는 op-08에 지움).
    지우기 전에 sha256을 manifest에 남겨 publish_parse가 로컬 없이도 EDW 행을 쓸 수 있게 한다."""
    import tempfile

    d = Path(tempfile.mkdtemp())
    state, local = d / "state", d / "local"
    state.mkdir()
    local.mkdir()
    (local / "a.txt").write_text("x", encoding="utf-8")
    (state / "manifest.jsonl").write_text(
        json.dumps({"file_name": "a.txt", "key": "k1", "etag": "e1", "updated_at": None}) + chr(10), encoding="utf-8"
    )
    rep = d / "index.json"
    rep.write_text(json.dumps({"docs": [{"doc": "a.txt", "engine": "eng1"}]}), encoding="utf-8")
    finish(state, local, rep)
    man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
    assert not (local / "a.txt").exists(), "SI39 요건⑧ — 원본이 즉시 지워지지 않음"
    assert man["a.txt"].get("sha256"), "지우기 전에 sha256을 manifest에 안 남김(publish_parse가 로컬 없이 EDW 행을 못 씀)"
    print("[selftest] SI39 요건⑧ — 파싱 끝나면 원본 즉시 삭제 + sha256 기록 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()


def test_folder_tree():
    """F2(11-03 PC 시험) — 원천별 하위 폴더(`SFDC/<uuid>/<파일>`)면 평평한 폴더에 복사하고 manifest에 상대 키·원본 주소. 평평한 폴더는 그대로."""
    import tempfile

    root = Path(tempfile.mkdtemp())
    src, out = root / "src", root / "out"
    for rel in ("SFDC/u1/a.txt", "CRMS/u2/b.txt", "CRMS/u3/a.txt"):  # a.txt 이름 겹침 → `<상위 폴더>__a.txt`
        (src / rel).parent.mkdir(parents=True)
        (src / rel).write_text(rel, encoding="utf-8")
    with pc.PIPE.env(SOURCE_MANIFEST=None):
        local, names, state = resolve(str(src), out)
    man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
    assert local == out / "_source_files" and sorted(names) == sorted(man), (local, names)
    assert sorted(r["key"] for r in man.values()) == ["CRMS/u2/b.txt", "CRMS/u3/a.txt", "SFDC/u1/a.txt"], man
    for n, r in man.items():
        assert (local / n).read_text(encoding="utf-8") == r["key"], r  # 복사본 = 그 키의 원본
        assert r["uri"] == (src / r["key"]).resolve().as_uri(), r
        assert r["source_system"] == r["key"].split("/", 1)[0], r  # SFDC·CRMS(키 첫 마디)
    flat = root / "flat"
    flat.mkdir()
    (flat / "c.txt").write_text("c", encoding="utf-8")
    (flat / "sub").mkdir()
    (flat / "sub" / ".DS_Store").write_text("x", encoding="utf-8")  # 흘린 하위 파일 — 평평한 폴더 그대로
    (flat / "__MACOSX").mkdir()
    (flat / "__MACOSX" / "c.txt").write_text("x", encoding="utf-8")
    local2, names2, _ = resolve(str(flat), root / "out2")
    assert local2 == flat and names2 == ["c.txt"], (local2, names2)  # 평평한 폴더는 키 = 파일 이름(옛 그대로)
    odd = root / "odd"  # 원천 이름이 아닌 하위 폴더 — 평평한 폴더로(맨 위 파일만 = 0개)
    (odd / "_archive" / "u").mkdir(parents=True)
    (odd / "_archive" / "u" / "d.txt").write_text("d", encoding="utf-8")
    assert resolve(str(odd), root / "out3")[:2] == (odd, [])


def test_prepare_batch():
    """파싱 전 extract — 같은 내용은 하나만, ParsingMeta에 끝난 문서(unparsed가 뺀 것)는 빠짐 · pick_new는 상한·목록 안에서만."""
    import tempfile
    from unittest import mock

    from pipeline.extract import deduplication as dedup

    root = Path(tempfile.mkdtemp())
    src = root / "src"
    src.mkdir()
    for name, body in (("a.txt", "same"), ("b.txt", "same"), ("c.txt", "done")):
        (src / name).write_text(body, encoding="utf-8")
    steps = []

    def run_step(args):  # 여러 건 중복 확인은 자식 대신 같은 함수로
        steps.append(args[0])
        dedup.run_folder(src, root / "out" / "dedup")
        return 0

    with mock.patch.object(M, "unparsed", lambda names, out: [n for n in names if n != "c.txt"]):
        local, keep, state = M.prepare_batch(str(src), root / "out", 0, run_step)
        assert steps == ["pipeline.extract.deduplication"] and Path(local) == src
        assert len(keep) == 1 and keep[0] in ("a.txt", "b.txt"), keep
        assert (state / "selected.txt").read_text(encoding="utf-8").split() == ["a.txt", "b.txt", "c.txt"]
        only = root / "only.txt"
        only.write_text("b.txt\n", encoding="utf-8")
        for max_new, sel, want in ((1, None, ["a.txt"]), (5, only, ["b.txt"])):
            f = M.pick_new(src, root / "out", max_new, sel)
            assert f.read_text(encoding="utf-8").split() == want, (max_new, want)
