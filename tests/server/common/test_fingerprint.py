"""common.core.fingerprint 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.fingerprint --selftest`."""

from pathlib import Path

from common.core.fingerprint import EXCLUDED_FILES, HANDOFF_FILES, _unclassified, fingerprint, pipeline_version
from common.core.paths import DEPLOY_ROOT


def selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "handoff.py").write_text("x = 1\n", encoding="utf-8")
        (root / "excluded.py").write_text("y = 1\n", encoding="utf-8")
        fake_handoff, fake_excluded = ("handoff.py",), ("excluded.py",)
        check("_unclassified: 가짜 목록 둘에 다 있으면 빈 목록", _unclassified(root, fake_handoff, fake_excluded) == [])

        fp1 = fingerprint(root, handoff=fake_handoff)
        check("fingerprint: 같은 내용 → 같은 지문", fp1 == fingerprint(root, handoff=fake_handoff))
        (root / "excluded.py").write_text("y = 2\n", encoding="utf-8")
        check("fingerprint: HANDOFF_FILES 밖(excluded.py) 변경은 지문 그대로", fp1 == fingerprint(root, handoff=fake_handoff))
        (root / "handoff.py").write_text("x = 2\n", encoding="utf-8")
        check("fingerprint: HANDOFF_FILES 안(handoff.py) 변경은 지문이 바뀜", fp1 != fingerprint(root, handoff=fake_handoff))

        (root / "new_file.py").write_text("z = 1\n", encoding="utf-8")  # 분류 안 된 새 파일
        missing = _unclassified(root, fake_handoff, fake_excluded)
        check("_unclassified: 새 .py가 HANDOFF·EXCLUDED 둘 다에 없으면 잡힘", missing == ["new_file.py"])
        (root / "new_file.py").unlink()
        (root / "sub").mkdir()
        (root / "sub" / "deep.py").write_text("w = 1\n", encoding="utf-8")  # S4 — 하위 폴더의 새 파일도
        (root / "sub" / "__pycache__").mkdir()
        (root / "sub" / "__pycache__" / "junk.py").write_text("", encoding="utf-8")
        check(
            "_unclassified: 하위 폴더의 새 .py도 상대 경로로 잡힘(__pycache__ 제외)",
            _unclassified(root, fake_handoff, fake_excluded) == ["sub/deep.py"],
        )

    check("_unclassified: 실제 common/ 폴더는 전부 분류됨(새 파일 추가 시 깜빡하면 import부터 거부)", _unclassified() == [])
    check("HANDOFF_FILES·EXCLUDED_FILES는 겹치지 않음", not (set(HANDOFF_FILES) & set(EXCLUDED_FILES)))

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()


def test_version_file():
    """저장소 루트 VERSION(이미지 /app/deploy/VERSION) — 두 이미지 공통 SemVer(D-036). pipeline_version()이 그 값을 낸다."""
    root = DEPLOY_ROOT
    v = (root / "VERSION").read_text(encoding="utf-8").strip()
    parts = v.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), v
    if not (root / "common" / "PATCH_VERSION").exists():  # 오버레이 패치가 올라가 있으면 그 버전이 더 높을 수 있음
        assert pipeline_version() == v


def test_pipeline_version_picks_higher():
    """VERSION과 PATCH_VERSION 중 높은 버전 — 오버레이 패치(0.1.1)는 이미지(0.1.0)를 이기고, 새 이미지(0.2.0) 뒤 남은 옛 패치는 지지 않는다."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        common = Path(td) / "common"
        common.mkdir()
        (Path(td) / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        assert pipeline_version(common) == "0.1.0"
        (common / "PATCH_VERSION").write_text("0.1.1\n", encoding="utf-8")
        assert pipeline_version(common) == "0.1.1"
        (Path(td) / "VERSION").write_text("0.2.0\n", encoding="utf-8")
        assert pipeline_version(common) == "0.2.0"
        (common / "PATCH_VERSION").write_text("20261016-e305b14+patch-abc1234\n", encoding="utf-8")  # 옛 꼴은 무시
        assert pipeline_version(common) == "0.2.0"
