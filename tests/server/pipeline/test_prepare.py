"""pipeline.extract.filter_and_rotate 시험."""

import json
import struct
from pathlib import Path

import pipeline.extract.filter_and_rotate as M
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


def _build_cfb(streams):
    """시험용 최소 CFB 파일 — Root Entry + 주어진 스트림들(512바이트 섹터 1개씩, FAT 1개, DIFAT 없음) — olefile 없이도
    _cfb_sectors·_ole_encrypted_reason을 선위험 시험(selftest)할 수 있게. streams = {스트림 이름: 바이트}(≤512바이트씩, ≤3개)."""
    names = list(streams)
    assert len(names) <= 3, "디렉터리 1섹터(Root Entry + 최대 3개)만 지원 — selftest 전용 헬퍼"
    header = bytearray(512)
    header[0:8] = CFB_SIG
    struct.pack_into("<H", header, 30, 9)  # sector shift = 9 → 섹터 512바이트
    struct.pack_into("<H", header, 32, 6)  # mini sector shift(안 씀)
    struct.pack_into("<I", header, 44, 1)  # FAT 섹터 1개
    struct.pack_into("<I", header, 48, 1)  # 디렉터리 시작 섹터 = 1
    struct.pack_into("<I", header, 56, 4096)  # 미니스트림 상한(이 헬퍼는 안 씀)
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)
    for i in range(109):
        struct.pack_into("<I", header, 76 + i * 4, 0 if i == 0 else 0xFFFFFFFF)
    data_secs = {name: 2 + i for i, name in enumerate(names)}
    fat = [0xFFFFFFFF] * 128
    fat[0], fat[1] = 0xFFFFFFFD, 0xFFFFFFFE
    for secid in data_secs.values():
        fat[secid] = 0xFFFFFFFE
    fat_sec = b"".join(struct.pack("<I", v) for v in fat)
    dirent = bytearray(512)

    def put_entry(i, name, etype, start, size):
        nm = name.encode("utf-16-le") + b"\x00\x00"
        dirent[i * 128 : i * 128 + len(nm)] = nm
        struct.pack_into("<H", dirent, i * 128 + 64, len(nm))
        dirent[i * 128 + 66] = etype
        struct.pack_into("<I", dirent, i * 128 + 116, start)
        struct.pack_into("<Q", dirent, i * 128 + 120, size)

    put_entry(0, "Root Entry", 5, 0xFFFFFFFE, 0)
    for i, name in enumerate(names, 1):
        put_entry(i, name, 2, data_secs[name], len(streams[name]))
    body = b"".join(streams[name] + b"\x00" * (512 - len(streams[name])) for name in names)
    return bytes(header) + fat_sec + bytes(dirent) + body


def selftest():
    """D4 — 가짜 Fasoo 머리·OLE EncryptedPackage·정상 docx/pdf·머리 깨진 pdf로 오프라인 자기 점검(네트워크·실제 문서 없음).
    SI44 — 옛 OLE 암호(.doc FIB fEncrypted·.xls BIFF FILEPASS·.ppt EncryptedSummary)·압축·미지원 확장자도 함께."""
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

        # SI44① — 옛 OLE 암호: .doc FIB flags1 bit8(fEncrypted) · .xls BIFF FILEPASS(0x2F) · .ppt EncryptedSummary 스토리지
        fib_enc = bytearray(16)
        struct.pack_into("<H", fib_enc, 10, 0x0100)  # flags1 offset 10 — fEncrypted만 켬
        doc_enc = w("i.doc", _build_cfb({"WordDocument": bytes(fib_enc)}))
        assert _ole_encrypted_reason(doc_enc) == "encrypted_doc", _ole_encrypted_reason(doc_enc)
        fib_plain = bytearray(16)  # fEncrypted 꺼짐 — 정상 .doc
        doc_plain = w("j.doc", _build_cfb({"WordDocument": bytes(fib_plain)}))
        assert _ole_encrypted_reason(doc_plain) is None, _ole_encrypted_reason(doc_plain)

        biff_enc = struct.pack("<HH", 0x0809, 4) + b"\x00" * 4 + struct.pack("<HH", 0x2F, 4) + b"\x00" * 4  # BOF + FILEPASS
        xls_enc = w("k.xls", _build_cfb({"Workbook": biff_enc}))
        assert _ole_encrypted_reason(xls_enc) == "encrypted_xls", _ole_encrypted_reason(xls_enc)
        biff_plain = struct.pack("<HH", 0x0809, 4) + b"\x00" * 4 + struct.pack("<HH", 0x42, 4) + b"\x00" * 4  # BOF + 다른 레코드(0x2F 아님)
        xls_plain = w("l.xls", _build_cfb({"Book": biff_plain}))  # 옛 BIFF는 "Book" 스트림 이름도 씀
        assert _ole_encrypted_reason(xls_plain) is None, _ole_encrypted_reason(xls_plain)

        ppt_enc = w("m.ppt", _build_cfb({"EncryptedSummary": b"\x00" * 8}))
        assert _ole_encrypted_reason(ppt_enc) == "encrypted_ppt", _ole_encrypted_reason(ppt_enc)
        ppt_plain = w("n.ppt", _build_cfb({"PowerPoint Document": b"\x00" * 8}))
        assert _ole_encrypted_reason(ppt_plain) is None, _ole_encrypted_reason(ppt_plain)
        not_ole_doc = w("o.doc", b"this is not a CFB file at all")  # OLE 컨테이너 아님 — 엔진이 각자 판정
        assert _ole_encrypted_reason(not_ole_doc) is None, _ole_encrypted_reason(not_ole_doc)
        assert _ole_encrypted_reason(normal_docx) is None, "OOXML(.docx)은 OLE_EXT 밖 — 손대지 않음"

        # SI44② — 압축·처리 엔진 없는 확장자(파싱 대상 아님, 암호·손상과 다른 사유)
        assert _unsupported_reason(w("p.zip", b"PK\x03\x04" + b"\x00" * 20)) == "unsupported_archive"
        assert _unsupported_reason(w("q.rar", b"Rar!" + b"\x00" * 20)) == "unsupported_archive"
        assert _unsupported_reason(w("r.xyz", b"\x00" * 20)) == "unsupported_format"
        assert _unsupported_reason(good_pdf) is None and _unsupported_reason(normal_docx) is None  # 처리 엔진 있음

        log = td / "skipped.jsonl"
        skipped = []
        _record_skip(fasoo, "drm_fasoo", skipped, log)
        recs = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1 and recs[0]["reason"] == "drm_fasoo" and recs[0]["file"] == "a.docx" and recs[0]["sha256"], recs
        assert skipped == [{"file": "a.docx", "reason": "drm_fasoo"}], skipped
    print(
        "selftest OK — DRM·암호 머리 바이트 판별(Fasoo·MarkAny·SoftCamp·OLE EncryptedPackage·PDF 머리 깨짐 → drm_unknown, "
        "정상 docx·pdf는 통과) + skipped.jsonl 누적 기록 + SI44 옛 OLE 암호(.doc·.xls·.ppt)·압축·미지원 확장자"
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
    문서와 rotation.csv만 남아, 기록 파일이 "건너뜀(처리 엔진 없음) .csv"로 세지지 않는다. 옛 자리의 누적 기록은 옮겨 이어 쓴다."""
    import sys
    import tempfile
    from unittest import mock

    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "src", Path(d) / "prepared"
        src.mkdir()
        out.mkdir()
        (src / "a.txt").write_text("hello", encoding="utf-8")
        (src / "b.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 20)  # 압축 — 건너뜀(unsupported_archive)
        (out / "skipped.jsonl").write_text(json.dumps({"file": "old.pdf", "reason": "drm_fasoo"}) + "\n", encoding="utf-8")
        (out / "skipped.csv").write_text("file,reason\n", encoding="utf-8")
        with mock.patch.object(sys, "argv", ["prepare", "--src", str(src), "--out", str(out)]):
            M.main()
        top = sorted(p.name for p in out.iterdir() if p.is_file())
        assert top == ["a.txt", "rotation.csv"], top
        recs = [json.loads(ln) for ln in (out / "_records" / "skipped.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [r["file"] for r in recs] == ["old.pdf", "b.zip"], recs
        assert "b.zip" in (out / "_records" / "skipped.csv").read_text(encoding="utf-8-sig")
