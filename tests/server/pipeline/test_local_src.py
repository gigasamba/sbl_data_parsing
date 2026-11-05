"""PC 원본 폴더(op-14 — valid_env/object_storage) 목록 — 게시 폴더(file:// 게시 버킷 — Parsing_Result)·맨 위 설명 파일(*.md)은 원본이 아니다."""

import tempfile
from pathlib import Path

from pipeline import config as pc
from pipeline.extract import candidate_pick as CP


def test_local_source_skips_publish_dir():
    """원천별 하위 폴더 모양(`SFDC/<id>/<파일>`)에 게시 폴더·설명 파일이 같이 있어도 원본은 SFDC 파일만."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d)
        for rel in ("SFDC/id1/a.pdf", "Parsing_Result/SFDC/id1/a.json", "readme.md"):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        res, other = (src / "Parsing_Result").as_posix(), (src.parent / "elsewhere").as_posix()
        # (게시 버킷, PC 게시 폴더, 기대 원본 목록 — None = 평평한 폴더로 봄)
        for bucket, local_dir, want in (
            (f"file://{res}", other, ["SFDC/id1/a.pdf"]),  # 지금 게시 폴더
            ("rag-silver", res, ["SFDC/id1/a.pdf"]),  # 버킷을 바꿔도 남은 PC 게시 폴더는 원본 아님
            ("rag-silver", other, None),  # 게시 폴더가 아니면 Parsing_Result도 맨 위 폴더 — 원천 이름이 아니라 평평한 폴더
        ):
            with pc.PIPE.env(PM_BUCKET=bucket, LOCAL_PM_DIR=local_dir):
                files = CP._tree_files(src)
            assert (None if files is None else [p.relative_to(src).as_posix() for p in files]) == want, (bucket, files)
