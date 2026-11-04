"""deploy.release.assets 자기 점검 — 조각 합치기·해시 확인."""

import os
from pathlib import Path

from deploy.release import assets as M
from deploy.release.assets import assemble, sha


def selftest():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        M.A, M.PART = Path(d) / "assets", 10
        src = Path(d) / "x.bin"
        src.write_bytes(os.urandom(35))
        (M.A / "k").mkdir(parents=True)
        for i in range(4):
            (M.A / "k" / f"x.bin.part{i:02d}").write_bytes(src.read_bytes()[i * 10 : (i + 1) * 10])
        meta = {"sha256": sha(src), "size": 35, "parts": [f"x.bin.part{i:02d}" for i in range(4)]}
        out = Path(d) / "o" / "x.bin"
        assemble("k/x.bin", meta, out)
        assert out.read_bytes() == src.read_bytes()
        (M.A / "k" / "x.bin.part03").write_bytes(b"bad")
        try:
            assemble("k/x.bin", meta, Path(d) / "o2" / "x.bin")
            raise AssertionError("손상 조각을 못 잡음")
        except SystemExit:
            pass
    print("[selftest] 조각 합치기·해시 확인 통과")


def test_main():
    selftest()
