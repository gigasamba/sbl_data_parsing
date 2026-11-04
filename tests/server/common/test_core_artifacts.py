"""common.core.artifacts 자기 점검."""

from pathlib import Path

from common.core.artifacts import code_fp, is_stale, key, manifest


def selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:  # 줄바꿈만 다르면 같은 지문, 내용이 다르면 다른 지문
        f = Path(td) / "pipeline" / "transform" / "represent" / "build_rep.py"
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

        parts = {"chunker": "structure", "k": 800}
        k1 = key("s", parts, root=root)
        k2 = key("s", {"k": 800, "chunker": "structure"}, root=root)  # 키 순서만 다름
        check("key: dict 키 순서 안 탐(안정)", k1 == k2)
        check("key: 16자 hex", len(k1) == 16 and all(c in "0123456789abcdef" for c in k1))

        out = root / "store" / "s" / "x"
        m = manifest(out, "s", parts, root=root)
        check("manifest: _manifest.json 생성", (out / "_manifest.json").exists())
        check("manifest: code_fp 기록", m["code_fp"] == fp3)
        stale, reason = is_stale(out, root=root)
        check("is_stale: 갓 만든 저장본은 안 낡음", stale is False and reason == "")

        (root / "pipeline" / "transform" / "structure" / "gold_bundle.py").write_text(
            "from common.core import text\nx = 3\n", encoding="utf-8"
        )
        stale2, reason2 = is_stale(out, root=root)
        check("is_stale: 코드가 바뀌면 낡음으로 바뀜", stale2 is True and "code_fp" in reason2)

        missing, why = is_stale(root / "store" / "s" / "없음", root=root)
        check("is_stale: manifest 없는 폴더는 낡음(버전 미상)", missing is True and "없음" in why)

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():
    selftest()
