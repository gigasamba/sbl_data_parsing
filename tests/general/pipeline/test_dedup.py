"""pipeline.extract.deduplication — 완전 중복(sha256)만 묶음(11-01 — 이름·내용 유사 후보는 지움, PRD pl-02)."""

import tempfile
from pathlib import Path

from pipeline.extract.deduplication import run_folder


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
