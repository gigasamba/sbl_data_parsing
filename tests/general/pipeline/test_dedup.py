"""pipeline.extract.deduplication — 완전 중복(sha256)만 묶음(11-01 — 이름·내용 유사 후보는 지움, PRD pl-02)."""

import tempfile
from pathlib import Path

from pipeline.extract.deduplication import find_duplicate, record_duplicate, run_folder


def test_exact_duplicates_only():
    """같은 내용 두 파일 → 대표 1개만 keep(이름에 사본 표시 없는 쪽) · 이름만 비슷한 다른 내용은 둘 다 keep, 그룹 없음."""
    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "src", Path(td) / "out"
        src.mkdir()
        (src / "contract.txt").write_text("같은 내용", encoding="utf-8")
        (src / "contract(1).txt").write_text("같은 내용", encoding="utf-8")
        (src / "contract_v2.txt").write_text("다른 내용", encoding="utf-8")
        keep, rows, gid = run_folder(src, out)
        assert sorted(keep) == ["contract.txt", "contract_v2.txt"], keep
        assert gid == 1 and {r["file"]: r["decision"] for r in rows} == {
            "contract(1).txt": "중복(자동 제외)",
            "contract.txt": "해시 대표",
        }, rows
        assert (out / "keep.txt").read_text(encoding="utf-8").split() == ["contract.txt", "contract_v2.txt"]
        assert (out / "groups.csv").exists() and (out / "report.md").exists()
        keep2, _, _ = run_folder(src, out)  # 캐시(fingerprints.jsonl)로 다시 — 같은 결과
        assert sorted(keep2) == sorted(keep)


def test_manifest_duplicates():
    """받기 중 확인 — 다른 원천의 같은 sha만 중복(자기 원천·다른 sha·매니페스트 없음은 아님). 잠금 파일은 남지 않는다."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "dedup" / "manifest.jsonl"
        assert find_duplicate(m, "b", sha="s1") is None  # 매니페스트 없음
        record_duplicate(m, "a", "z", etag="e", size=3, sha="s1")
        assert not Path(str(m) + ".lock").exists()
        cases = [("b", "s1", "a"), ("a", "s1", None), ("b", "s2", None)]  # (찾는 원천, sha, 찾은 원천)
        for src, sha, want in cases:
            hit = find_duplicate(m, src, sha=sha)
            assert (hit and hit["source_id"]) == want, (src, sha, hit)
        assert find_duplicate(m, "b", sha="s1")["duplicate_of"] == "z"
