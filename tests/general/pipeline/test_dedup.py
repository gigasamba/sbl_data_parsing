"""pipeline.extract.deduplication — 완전 중복(sha256)만 묶음(11-01 — 이름·내용 유사 후보는 지움, PRD pl-02)."""

import tempfile
from pathlib import Path

from pipeline.extract.deduplication import run_folder


def test_exact_duplicates_only():
    """같은 내용 두 파일 → 대표 1개만 keep(이름에 사본 표시 없는 쪽) · 이름만 비슷한 다른 내용은 둘 다 keep, 그룹 없음 · names 밖 파일은 안 봄."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td)
        (src / "contract.txt").write_text("같은 내용", encoding="utf-8")
        (src / "contract(1).txt").write_text("같은 내용", encoding="utf-8")
        (src / "contract_v2.txt").write_text("다른 내용", encoding="utf-8")
        (src / "other.txt").write_text("같은 내용", encoding="utf-8")  # 이번 묶음 밖
        keep, rows = run_folder(src, {"contract.txt", "contract(1).txt", "contract_v2.txt"})
        assert sorted(keep) == ["contract.txt", "contract_v2.txt"], keep
        assert {r["file"]: r["representative"] for r in rows} == {"contract(1).txt": False, "contract.txt": True}, rows
        assert sorted(p.name for p in src.iterdir()) == [
            "contract(1).txt",
            "contract.txt",
            "contract_v2.txt",
            "other.txt",
        ]  # 아무것도 안 씀
