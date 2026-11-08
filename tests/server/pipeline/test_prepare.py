"""pipeline.extract.filter_and_rotate 시험."""

import json
import struct
from pathlib import Path

import pipeline.extract.filter_and_rotate as M
from common.core.paths import PROJ_ROOT
from pipeline.extract.filter_and_rotate import (
    _ENCRYPTED_PACKAGE,
    CFB_SIG,
    ZIP_SIG,
    _drm_reason,
    _ole_encrypted_reason,
    _record_skip,
    _unsupported_reason,
    best_angle,
)


def _build_cfb(streams, mini=()):
    """시험용 CFB(MS-CFB 규격대로, olefile 없이 만듦) — 섹터 512바이트, FAT 1섹터, 디렉터리 1섹터(Root Entry + 최대 3개).
    `mini`에 든 이름은 미니 스트림(64바이트 칸)에, 나머지는 일반 섹터에 4096바이트 이상으로 채워 둔다(규격: 4096 미만은 미니 스트림)."""
    names = list(streams)
    assert len(names) <= 3, "디렉터리 1섹터만 — 시험 전용"
    end, free = 0xFFFFFFFE, 0xFFFFFFFF
    sectors, fat = [b""], {0: 0xFFFFFFFD}  # 섹터 0 = FAT(끝에 채움)

    def alloc(blob):
        start, n = len(sectors), max(1, -(-len(blob) // 512))
        for i in range(n):
            sectors.append(blob[i * 512 : (i + 1) * 512].ljust(512, b"\x00"))
            fat[start + i] = start + i + 1 if i < n - 1 else end
        return start

    dir_sec = alloc(b"")
    ents, mini_blob, minifat = [], b"", []
    for name in names:
        data = streams[name]
        if name in mini:
            k = max(1, -(-len(data) // 64))
            ents.append((name, len(mini_blob) // 64, len(data)))
            minifat += [len(mini_blob) // 64 + i + 1 for i in range(k - 1)] + [end]
            mini_blob += data.ljust(k * 64, b"\x00")
        else:
            data = data.ljust(4096, b"\x00")
            ents.append((name, alloc(data), len(data)))
    root, minifat_sec = (end, 0), end
    if mini_blob:
        root = (alloc(mini_blob), len(mini_blob))
        minifat_sec = alloc(struct.pack(f"<{len(minifat)}I", *minifat).ljust(512, b"\xff"))
    sectors[0] = struct.pack("<128I", *(fat.get(i, free) for i in range(128)))
    dirent = bytearray(512)
    for i in range(len(names) + 1, 4):
        struct.pack_into("<III", dirent, i * 128 + 68, free, free, free)  # 빈 항목

    def put(i, name, etype, start, size, right, child):
        nm = name.encode("utf-16-le") + b"\x00\x00"
        dirent[i * 128 : i * 128 + len(nm)] = nm
        struct.pack_into("<HBB", dirent, i * 128 + 64, len(nm), etype, 1)  # 이름 길이·종류·검정(색)
        struct.pack_into("<III", dirent, i * 128 + 68, free, right, child)  # 왼쪽·오른쪽 형제·자식
        struct.pack_into("<IQ", dirent, i * 128 + 116, start, size)

    put(0, "Root Entry", 5, *root, free, 1 if names else free)
    for i, (name, start, size) in enumerate(ents, 1):  # 형제는 오른쪽으로 한 줄
        put(i, name, 2, start, size, i + 1 if i < len(names) else free, free)
    sectors[dir_sec] = bytes(dirent)
    header = bytearray(512)
    header[0:8] = CFB_SIG
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)  # 판·바이트 순서·섹터 512·미니 섹터 64
    struct.pack_into("<II", header, 44, 1, dir_sec)  # FAT 섹터 수·디렉터리 시작
    struct.pack_into("<IIIII", header, 56, 4096, minifat_sec, int(bool(mini_blob)), end, 0)  # 미니 상한·미니 FAT·DIFAT 없음
    struct.pack_into("<109I", header, 76, 0, *([free] * 108))
    return bytes(header) + b"".join(sectors)


_FIB_ENC = struct.pack("<10sH4x", b"", 0x0100)  # .doc FIB flags1(10번째 바이트) fEncrypted만 켬
_FIB_PLAIN = bytes(16)
_BIFF_ENC = struct.pack("<HH4xHH4x", 0x0809, 4, 0x2F, 4)  # BOF + FILEPASS(0x2F)
_BIFF_PLAIN = struct.pack("<HH4xHH4x", 0x0809, 4, 0x42, 4)  # BOF + 다른 레코드


def _ole_cases():
    """(파일 이름, 바이트, 기대 판정) — pl-66: 직접 짠 CFB 판독기와 olefile을 견줘 고른 사례(이제 olefile 하나로 같은 판정)."""
    doc_enc = _build_cfb({"WordDocument": _FIB_ENC})
    xls_enc = _build_cfb({"Workbook": _BIFF_ENC})
    return [
        ("doc_plain.doc", _build_cfb({"WordDocument": _FIB_PLAIN}), None),
        ("doc_enc.doc", doc_enc, "encrypted_doc"),
        ("doc_enc_mini.doc", _build_cfb({"WordDocument": _FIB_ENC}, mini={"WordDocument"}), "encrypted_doc"),
        ("xls_plain.xls", _build_cfb({"Workbook": _BIFF_PLAIN}), None),
        ("xls_enc.xls", xls_enc, "encrypted_xls"),
        ("xls_book_enc.xls", _build_cfb({"Book": _BIFF_ENC}), "encrypted_xls"),  # 옛 BIFF는 "Book" 스트림 이름도 씀
        ("xls_enc_mini.xls", _build_cfb({"Workbook": _BIFF_ENC}, mini={"Workbook"}), "encrypted_xls"),  # 직접 짠 판독기는 놓쳤음
        ("xls_plain_mini.xls", _build_cfb({"Workbook": _BIFF_PLAIN}, mini={"Workbook"}), None),
        ("ppt_plain.ppt", _build_cfb({"PowerPoint Document": bytes(8)}), None),
        (
            "ppt_enc.ppt",
            _build_cfb({"PowerPoint Document": bytes(8), "EncryptedSummary": bytes(8)}, mini={"EncryptedSummary"}),
            "encrypted_ppt",
        ),
        ("drm_fasoo.doc", b"<## FASOO DRM WRAPPED ##>" + bytes(600), None),  # 옛 형식은 DRM 머리를 보지 않음(_drm_reason은 OOXML·PDF만)
        ("drm_in_cfb.doc", doc_enc[:600] + b"<## FASOO" + bytes(100), None),
        ("not_cfb.doc", b"this is not a CFB file at all", None),
        ("header_only.xls", xls_enc[:512], None),
        ("trunc_no_data.doc", doc_enc[:1536], None),  # 머리말·FAT·디렉터리만 남고 스트림 칸이 잘림
        ("garbage.ppt", CFB_SIG + b"\xff" * 2000, None),
    ]


def test_ole_encrypted_cases():
    """pl-66 — 옛 형식 오피스 암호 판정 표(규격대로 만든 CFB·미니 스트림·DRM 흉내·깨진 파일). PC에는 valid_env 견본 4건과
    반으로 자른 사본도 함께(이미지에는 valid_env 없음)."""
    import tempfile

    samples = PROJ_ROOT / "valid_env" / "object_storage" / "CRMS"
    expect = {"encrypted_ole.doc": "encrypted_doc", "legacy_report.doc": None, "legacy_sheet.xls": None, "legacy_deck.ppt": None}
    cases = _ole_cases()
    for f in sorted(samples.glob("*/*")) if samples.is_dir() else []:
        if f.name in expect:
            data = f.read_bytes()
            cases += [(f.name, data, expect[f.name]), ("trunc_" + f.name, data[: len(data) // 2], None)]
    with tempfile.TemporaryDirectory() as td:
        for name, data, want in cases:
            f = Path(td) / name
            f.write_bytes(data)
            assert _ole_encrypted_reason(f) == want, (name, _ole_encrypted_reason(f), want)


def selftest():
    """D4 — 가짜 Fasoo 머리·OLE EncryptedPackage·정상 docx/pdf·머리 깨진 pdf로 오프라인 자기 점검(네트워크·실제 문서 없음).
    SI44 — 압축·미지원 확장자도 함께(옛 OLE 암호는 test_ole_encrypted_cases 표)."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        def w(name, data):
            f = td / name
            f.write_bytes(data)
            return f

        fasoo = w("a.docx", b"<## FASOO DRM WRAPPED ##>" + b"\x00" * 100)
        assert _drm_reason(fasoo) == "drm_fasoo", _drm_reason(fasoo)
        markany = w("f.xlsx", b"MarkAny" + b"\x00" * 50)
        assert _drm_reason(markany) == "drm_markany", _drm_reason(markany)
        softcamp = w("g.pptx", b"SCDSA" + b"\x00" * 50)
        assert _drm_reason(softcamp) == "drm_softcamp", _drm_reason(softcamp)
        ole_encrypted = w("b.docx", CFB_SIG + b"\x00" * 64 + _ENCRYPTED_PACKAGE + b"\x00" * 64)
        assert _drm_reason(ole_encrypted) == "encrypted_ooxml", _drm_reason(ole_encrypted)
        ole_other = w("h.docx", CFB_SIG + b"\x00" * 200)  # OLE인데 EncryptedPackage 없음 — 제품 특정 안 함
        assert _drm_reason(ole_other) == "drm_unknown", _drm_reason(ole_other)
        normal_docx = w("c.docx", ZIP_SIG + b"\x00" * 200)
        assert _drm_reason(normal_docx) is None, _drm_reason(normal_docx)
        good_pdf = w("d.pdf", b"%PDF-1.4\n%...")
        assert _drm_reason(good_pdf) is None, _drm_reason(good_pdf)
        bad_pdf = w("e.pdf", b"\x00\x01\x02not a pdf")
        assert _drm_reason(bad_pdf) == "drm_unknown", _drm_reason(bad_pdf)

        assert _ole_encrypted_reason(normal_docx) is None, "OOXML(.docx)은 OLE_EXT 밖 — 손대지 않음"

        # SI44② — 압축·처리 엔진 없는 확장자(파싱 대상 아님, 암호·손상과 다른 사유)
        assert _unsupported_reason(w("p.zip", b"PK\x03\x04" + b"\x00" * 20)) is None  # zip은 압축 엔진이 풂(pl-57 — 깨짐은 archive.check)
        assert _unsupported_reason(w("q.rar", b"Rar!" + b"\x00" * 20)) == "unsupported_archive"
        assert _unsupported_reason(w("r.xyz", b"\x00" * 20)) == "unsupported_format"
        assert _unsupported_reason(good_pdf) is None and _unsupported_reason(normal_docx) is None  # 처리 엔진 있음

        log = td / "skipped.jsonl"
        skipped = []
        _record_skip(fasoo, "drm_fasoo", skipped, log)
        recs = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1 and recs[0]["reason"] == "drm_fasoo" and recs[0]["file"] == "a.docx", recs
        assert skipped == [{"file": "a.docx", "reason": "drm_fasoo"}], skipped
    print(
        "selftest OK — DRM·암호 머리 바이트 판별(Fasoo·MarkAny·SoftCamp·OLE EncryptedPackage·PDF 머리 깨짐 → drm_unknown, "
        "정상 docx·pdf는 통과) + skipped.jsonl 누적 기록 + SI44 압축·미지원 확장자"
    )
    _selftest_rotate()


def _selftest_rotate():
    """pl-02(사용자 11-02) — best_angle은 4방향 점수를 스레드 4개로 동시에 재고 가장 높은 각도를 고른다(같으면 0도, 모두 0이면 0도).
    문턱·비율·기대 각도 없음. 실 OCR·글꼴 없이 — score()를 흉내 낸다: 흰 점 하나를 둔 이미지를 돌리면 점이 다른 모서리로 가므로
    그 자리로 각도를 알아내 표의 점수를 돌려준다(병렬이라 부르는 순서는 상관없음)."""
    import threading

    from PIL import Image

    im = Image.new("L", (40, 40), 0)
    im.putpixel((0, 0), 255)  # 0도: 왼쪽 위 → 90도(반시계): 왼쪽 아래 → 180도: 오른쪽 아래 → 270도: 오른쪽 위
    corner = {(0, 0): 0, (0, 39): 90, (39, 39): 180, (39, 0): 270}
    orig_score = M.score
    threads = set()

    def fake(table):
        def f(x, _probe):
            threads.add(threading.current_thread().name)
            xy = next(xy for xy in corner if x.getpixel(xy) == 255)
            return table[corner[xy]]

        return f

    try:
        for table, want in (
            ({0: 10.0, 90: 3.0, 180: 500.0, 270: 2.0}, 180),  # 가장 높은 각도로 돌림 — 문턱·비율 없음
            ({0: 300.0, 90: 0.0, 180: 290.0, 270: 0.0}, 0),  # 0도가 가장 높으면 그대로
            ({0: 5.0, 90: 5.0, 180: 5.0, 270: 5.0}, 0),  # 모두 같으면 0도
            ({0: 0.0, 90: 0.0, 180: 0.0, 270: 0.0}, 0),  # 글자가 없으면 0도
            ({0: 1.0, 90: 2.0, 180: 0.0, 270: 0.0}, 90),  # 차이가 작아도 가장 높은 쪽(옛 1.3배 비교 없음)
        ):
            M.score = fake(table)
            ang, s = best_angle(im, 1280)
            assert ang == want and s == table, (table, ang, s)
        assert len(threads) > 1 and all(t.startswith("rotate") for t in threads), threads  # 4방향을 풀 스레드에서 동시에
    finally:
        M.score = orig_score
    print("[selftest] pl-02 — 회전 판정 4방향 동시(스레드 풀)·가장 높은 각도·같으면 0도 통과")


def test_rotation_off_by_default():
    """pl-02(사용자 11-02) — 회전은 기본 꺼짐: 이미지 문서도 회전용 OCR(score) 없이 그대로 놓고, rotation.csv는 머리 줄만."""
    import sys
    import tempfile
    from unittest import mock

    from PIL import Image

    from pipeline import config as pc

    assert pc.cfg().extract.prepare.rotate is False
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "src", Path(d) / "prepared"
        src.mkdir()
        Image.new("RGB", (30, 20), "white").save(src / "scan.png")

        def boom(*a, **k):
            raise AssertionError("회전이 꺼졌는데 OCR 점수를 잼")

        with mock.patch.object(M, "score", boom), mock.patch.object(sys, "argv", ["prepare", "--src", str(src), "--out", str(out)]):
            M.main()
        assert (out / "scan.png").exists()
        assert (out / "rotation.csv").read_text(encoding="utf-8-sig").strip() == "file,page,angle,orig_sha256,s0,s90,s180,s270"


def test_main():  # 옛 `if a.selftest:` 갈래(main() 안)
    selftest()


def test_records_outside_scanned_folder():
    """운영 고침 10(11-02) — 건너뛴 문서 기록(skipped.csv·skipped.jsonl)은 prepared/_records/에. 파싱(run_all)이 훑는 맨 위에는
    문서와 rotation.csv만 남아, 기록 파일이 "건너뜀(처리 엔진 없음) .csv"로 세지지 않는다."""
    import sys
    import tempfile
    from unittest import mock

    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "src", Path(d) / "prepared"
        src.mkdir()
        out.mkdir()
        (src / "a.txt").write_text("hello", encoding="utf-8")
        (src / "b.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 20)  # 깨진 압축 — 건너뜀(broken_archive — pl-57)
        (out / "skipped.csv").write_text("file,reason\n", encoding="utf-8")  # 맨 위 옛 기록 — 문서가 아니라 지워짐
        with mock.patch.object(sys, "argv", ["prepare", "--src", str(src), "--out", str(out)]):
            M.main()
        top = sorted(p.name for p in out.iterdir() if p.is_file())
        assert top == ["a.txt", "rotation.csv"], top
        recs = [json.loads(ln) for ln in (out / "_records" / "skipped.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["file"] for r in recs] == ["b.zip"], recs
        assert "b.zip" in (out / "_records" / "skipped.csv").read_text(encoding="utf-8-sig")
