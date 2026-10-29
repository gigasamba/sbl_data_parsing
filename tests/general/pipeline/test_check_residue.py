"""pipeline.tools.check_residue 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.tools.check_residue --selftest`."""

import json
from pathlib import Path

from pipeline.tools.check_residue import check


def selftest():
    import tempfile

    out_dir = Path(tempfile.mkdtemp()) / "parse"
    (out_dir / "_rep").mkdir(parents=True)
    (out_dir / "_rep" / "index.json").write_text(
        json.dumps({"docs": [{"doc": "a.pdf", "engine": "eng1", "uri": "s3://b/a.pdf"}]}), encoding="utf-8"
    )
    tmp = Path(tempfile.mkdtemp()) / "stream"
    tmp.mkdir()
    assert check(out_dir, tmp, "1") == []  # 깨끗함

    from pipeline.stream import attach_dir_of

    adir = attach_dir_of(tmp)  # tmp의 형제(독립 보안 검토 재검토 6번) — tmp 안이 아님
    adir.mkdir()
    assert adir.parent == tmp.parent and adir != tmp  # PARSE_TMP 자체 안이 아니라 옆
    (adir / "attach-deadbeef.docx").write_bytes(b"x")
    issues = check(out_dir, tmp, "1")
    assert any("첨부 임시 폴더" in x for x in issues)
    (adir / "attach-deadbeef.docx").unlink()

    (out_dir / "eng1").mkdir()  # 처리 끝난 문서의 엔진별 중간 결과가 남음
    (out_dir / "eng1" / "a.pdf.json").write_text("{}", encoding="utf-8")
    issues = check(out_dir, tmp, "1")
    assert any("엔진별 중간 결과" in x for x in issues)
    (out_dir / "eng1" / "a.pdf.json").unlink()

    (out_dir.parent / "_source_files").mkdir()  # Object Storage 원본·사본이 남음
    (out_dir.parent / "_source_files" / "a.pdf").write_bytes(b"x")
    issues = check(out_dir, tmp, "1")
    assert any("원본·사본" in x for x in issues)
    (out_dir.parent / "_source_files" / "a.pdf").unlink()

    (out_dir / "raw").mkdir()  # KEEP_RAW_LAYER=0인데 raw 캐시 남음
    (out_dir / "raw" / "x.json").write_text("{}", encoding="utf-8")
    assert check(out_dir, tmp, "1") == []  # 1(유지)이면 문제 아님
    assert any("원본 층 캐시" in x for x in check(out_dir, tmp, "0"))  # 0(즉시 삭제)이면 잔여
    print("[selftest] X2 — check_residue: 임시 폴더·첨부 임시 폴더(형제)·엔진별 중간 결과·원본·P0 캐시 잔여 각각 검출 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
