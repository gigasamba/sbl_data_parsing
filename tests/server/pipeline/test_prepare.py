"""pipeline.extract.prepare 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.prepare --selftest`."""

import json
import struct
from pathlib import Path

import pipeline.extract.prepare as M
from pipeline.extract.prepare import (
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
    _selftest_rotate_fast()


def _selftest_rotate_fast():
    """AD18 — best_angle 지름길의 제어 흐름만 확인(실 OCR·글꼴 불필요 — score()를 흉내 내 호출 횟수·결과를 본다).
    핵심: hint 점수가 문턱(PREPARE_ROTATE_S0_MIN) 이상 **이고** 반대 각도(hint+180)보다 min_gain배 이상
    앞설 때만 2번(hint·반대)으로 확정 — 둘 중 하나라도 모자라면 안전하게 기존과 같은 전체 4방향 계산으로
    떨어져 정답을 그대로 찾는다(복원 정확도 불변, engine-qa CONCERN 10-08 반영: 문턱만 보고 반대와 안
    비교하면 뒤집힌 글도 가로로 읽혀 점수가 높게 나오는 경우를 확정해버릴 위험이 있었다) — 실제 회전
    복원율은 `vlm_page.py`·score_gold 쪽 실측(S17)이 맡는다."""
    # S9 — `global score`(모듈 전역 대입)를 모듈 바깥으로 옮긴 코드에서는 M.score(함수가 읽는 모듈 전역)로 바꿈
    from PIL import Image

    orig_score = M.score
    im = Image.new("RGB", (40, 40), "white")
    calls = []

    def fake(seq):
        it = iter(seq)

        def f(_im, _probe):
            calls.append(1)
            return next(it)

        return f

    try:
        calls.clear()  # 1) hint=0 충분히 높고(문턱 150↑) 반대(180)보다 압도적 → 2번(hint·반대)만, 나머지 생략
        M.score = fake([200.0, 10.0])
        ang, s = best_angle(im, 1280, 1.3, hint=0)
        assert ang == 0 and len(calls) == 2 and s == {0: 200.0, 180: 10.0}, (ang, s, calls)

        calls.clear()  # 2) hint=0 점수는 문턱을 넘지만 반대(180)도 거의 비슷(경쟁 비교 실패, CONCERN 사례)
        M.score = fake([200.0, 190.0, 0.0, 3.0, 500.0, 2.0])  # → 안전하게 전체 4방향으로 떨어져 정답(180) 그대로 찾음
        ang, s = best_angle(im, 1280, 1.3, hint=0)
        assert ang == 180 and len(calls) == 6 and s == {0: 0.0, 90: 3.0, 180: 500.0, 270: 2.0}, (ang, s, calls)

        calls.clear()  # 3) hint=0 문턱 미달(반대와 비교할 것도 없이 모자람) → 전체 4방향
        M.score = fake([10.0, 190.0, 0.0, 3.0, 500.0, 2.0])
        ang, s = best_angle(im, 1280, 1.3, hint=0)
        assert ang == 180 and len(calls) == 6, (ang, s, calls)

        calls.clear()  # 4) 문서 앞쪽에서 선 공통 각도(0이 아님)도 지름길 대상 — 반대는 hint+180(=270)
        M.score = fake([300.0, 5.0])
        ang, s = best_angle(im, 1280, 1.3, hint=90)
        assert ang == 90 and len(calls) == 2 and s == {90: 300.0, 270: 5.0}, (ang, s, calls)
    finally:
        M.score = orig_score
    print(
        "[selftest] AD18 — 방향 보정 빠른 경로(hint·반대 2번 비교 — 문턱+경쟁 둘 다 통과해야 확정, 하나라도 모자라면 "
        "기존과 같은 전체 4방향으로 안전하게 — 복원 정확도 불변) 통과"
    )


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
