"""압축 원본 풀기(pl-57) — pipeline.extract.archive(거르기) + 꺼내기(unpack — 안 파일 `_parts/`) + 압축 엔진 + 첨부 단계의 `[파일 …]` 절."""

import gzip
import io
import tarfile
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from pipeline import config as pc
from pipeline.extract import archive, unpack
from pipeline.extract.filter_and_rotate import _unsupported_reason
from pipeline.transform.parse.engines import registry
from pipeline.transform.represent import mail_attachments


def _zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _tgz_bytes(files, mode="w:gz"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as t:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _encrypted(data):
    """zip의 '암호' 표시(일반 목적 플래그 0번 비트)만 켬 — 표준 라이브러리는 암호 zip을 못 만든다."""
    b = bytearray(data)
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = b.find(sig)
        b[i + off] |= 1
    return bytes(b)


def _cp949_tar():
    """한국어 윈도 tar — 이름 바이트가 cp949(옛 GNU 형식, utf-8 아님)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT, encoding="cp949") as t:
        ti = tarfile.TarInfo("보고서.txt")
        ti.size = 1
        t.addfile(ti, io.BytesIO(b"r"))
    return buf.getvalue()


def _cp949_zip():
    """한국어 윈도 zip — 이름이 cp949이고 utf-8 표시(플래그 11번 비트)가 없음. 같은 길이 ASCII 이름으로 만든 뒤 바이트만 바꿈."""
    raw = "보고서.txt".encode("cp949")
    return _zip_bytes({"A" * (len(raw) - 4) + ".txt": b"r"}).replace(b"A" * (len(raw) - 4) + b".txt", raw)


A = {"a.txt": b"alpha", "sub/b.txt": b"beta"}
CASES = [  # (이름, 파일 이름, 내용, 거르기 이유, 안 파일 이름들)
    ("zip", "x.zip", _zip_bytes(A), None, ["a.txt", "sub/b.txt"]),
    ("tar.gz", "x.tar.gz", _tgz_bytes(A), None, ["a.txt", "sub/b.txt"]),
    (
        "안 zip 한 단계",
        "x.zip",
        _zip_bytes({"in.zip": _zip_bytes({"c.txt": b"gamma"}), "a.txt": b"alpha"}),
        None,
        ["in.zip/c.txt", "a.txt"],
    ),
    (
        "두 단계 밑은 그대로",
        "x.zip",
        _zip_bytes({"in.zip": _zip_bytes({"deep.zip": _zip_bytes({"d.txt": b"d"})})}),
        None,
        ["in.zip/deep.zip"],
    ),
    ("안 gz는 보통 파일", "x.zip", _zip_bytes({"a.txt": b"alpha", "app.log.gz": gzip.compress(b"log")}), None, ["a.txt", "app.log.gz"]),
    ("안 zip 깨짐은 보통 파일", "x.zip", _zip_bytes({"bad.zip": b"PK\x03\x04junk"}), None, ["bad.zip"]),
    (
        "끝에 zip 든 tar",
        "y.tar",
        _tgz_bytes({"doc.txt": b"d", "last.zip": _zip_bytes({"in.txt": b"i"})}, "w"),
        None,
        ["doc.txt", "last.zip/in.txt"],
    ),
    ("암호", "x.zip", _encrypted(_zip_bytes(A)), "encrypted_archive", None),
    ("깨짐", "x.zip", b"PK\x03\x04" + b"\x00" * 30, "broken_archive", None),
    ("tar 아닌 gz", "x.gz", _tgz_bytes(A)[:10] + b"\x00" * 20, "unsupported_archive", None),
    ("파일 수 넘음", "x.zip", _zip_bytes({f"f{i}.txt": b"x" for i in range(4)}), "archive_too_big", None),
    ("cp949 tar 이름 — 받기가 멈추지 않음(pl-65 ①)", "k.tar", _cp949_tar(), None, ["보고서.txt"]),
    ("cp949 zip 이름(pl-65 ⑪)", "k.zip", _cp949_zip(), None, ["보고서.txt"]),
    ("이름 속 줄바꿈은 빈칸(pl-65 ⑩)", "n.zip", _zip_bytes({"x\n## y.txt": b"y"}), None, ["x ## y.txt"]),
]


def test_archive_cases():
    with (
        tempfile.TemporaryDirectory() as td,
        pc.PIPE.env(ARCHIVE_MAX_FILES="3", ATTACH_MAX_DEPTH="2"),
    ):  # 표는 기본 깊이 2 기준 — 서버 settings.yaml 값과 상관없이
        for label, fname, data, reason, names in CASES:
            p = Path(td) / label.replace(" ", "_") / fname
            p.parent.mkdir()
            p.write_bytes(data)
            assert _unsupported_reason(p) is None, label  # 압축 엔진이 있음 — 받기 전 거르기에서 빠지지 않음
            assert archive.check(p) == reason, (label, archive.check(p))
            if names is not None:
                assert [it["name"] for it in unpack.unpack(p, p.parent / "_parts")] == names, label


def test_too_big_total():
    with tempfile.TemporaryDirectory() as td, pc.PIPE.env(ARCHIVE_MAX_TOTAL_MB="0.001"):
        p = Path(td) / "big.zip"
        p.write_bytes(_zip_bytes({"a.txt": b"x" * 2000}))
        assert archive.check(p) == "archive_too_big"


def test_unpacked_kinds():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "q.7z"
        p.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 20)
        assert _unsupported_reason(p) == "unsupported_archive"
        assert archive.check(p) is None  # 푸는 형식이 아님 — 거르기는 _unsupported_reason이 맡음
        assert "archive" in registry.engines_for(".zip") and "archive" in registry.engines_for(".gz")


def test_engine_and_blocks():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "pack.tar.gz"
        p.write_bytes(_tgz_bytes({**A, "pic.png": b"\x89PNG"}))  # 압축 안 그림은 읽지 않음
        out = registry.run("archive", str(p))
        assert out["text"] == "압축 안 파일 3개\na.txt\nsub/b.txt\npic.png", out["text"]
        y = Path(td) / "y.tar"  # 확장자로 고름 — 끝에 zip이 든 tar도 tar로
        y.write_bytes(_tgz_bytes({"doc.txt": b"d", "last.zip": _zip_bytes({"in.txt": b"i"})}, "w"))
        assert registry.run("archive", str(y))["text"] == "압축 안 파일 2개\ndoc.txt\nlast.zip"

        def fake(entry, store=None):
            return f"본문 {entry['bytes'].decode()} 입니다 열다섯 글자 넘게", False, "plaintext"

        unpack.unpack(p, p.parent / "_parts")
        with patch.object(mail_attachments, "parse_attachment", fake):
            text, blocks, stats = mail_attachments.mail_blocks(p, out["text"])
        assert text == out["text"]  # 압축은 위치 표시 없음
        assert blocks == [
            "## [파일 a.txt]\n본문 alpha 입니다 열다섯 글자 넘게",
            "## [파일 sub/b.txt]\n본문 beta 입니다 열다섯 글자 넘게",
        ], blocks
        assert stats["parsed"] == 2 and stats["sources"] == ["pack.tar.gz#a.txt", "pack.tar.gz#sub/b.txt"], stats
