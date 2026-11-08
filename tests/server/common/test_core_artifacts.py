"""common.core.artifacts 자기 점검."""

from pathlib import Path

from common.core.artifacts import code_fp


def selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:  # 줄바꿈만 다르면 같은 지문, 내용이 다르면 다른 지문
        f = Path(td) / "pipeline" / "transform" / "represent" / "doc_represent.py"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"a=1\nb=2\n")
        lf = code_fp("p1", root=td)
        f.write_bytes(b"a=1\r\nb=2\r\n")
        crlf = code_fp("p1", root=td)
        f.write_bytes(b"a=1\nb=3\n")
        check("code_fp — CRLF/LF 무관·내용 변화엔 반응", lf == crlf and lf != code_fp("p1", root=td))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pipeline" / "transform" / "structure").mkdir(parents=True)
        (root / "common" / "core").mkdir(parents=True)
        (root / "pipeline" / "transform" / "structure" / "gold_bundle.py").write_text(
            "from common.core import text\nx = 1\n", encoding="utf-8"
        )
        (root / "common" / "core" / "text.py").write_text("y = 1\n", encoding="utf-8")
        (root / "common" / "core" / "unused.py").write_text("z = 1\n", encoding="utf-8")

        fp1 = code_fp("s", root=root)
        check("code_fp: 같은 내용 → 같은 지문", fp1 == code_fp("s", root=root))
        (root / "pipeline" / "transform" / "structure" / "gold_bundle.py").write_text(
            "from common.core import text\nx = 2\n", encoding="utf-8"
        )
        fp2 = code_fp("s", root=root)
        check("code_fp: 파일 내용이 바뀌면 → 다른 지문", fp1 != fp2)
        (root / "common" / "core" / "text.py").write_text("y = 2\n", encoding="utf-8")
        fp3 = code_fp("s", root=root)
        check("code_fp: 층이 import하는 common 변경은 지문에 반영", fp2 != fp3)
        (root / "common" / "core" / "unused.py").write_text("z = 2\n", encoding="utf-8")
        check("code_fp: 층이 안 쓰는 common 변경은 지문 그대로(10-05)", fp3 == code_fp("s", root=root))

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():
    selftest()
