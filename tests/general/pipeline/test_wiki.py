"""pipeline.transform.structure.wiki 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.wiki --selftest`."""

import json
from pathlib import Path

from pipeline.transform.structure.wiki import build


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    sha = "d" * 64
    (d / "docs.jsonl").write_text(json.dumps({"file_path": "x", "file_name": "x.pdf", "file_sha256": sha}) + "\n", encoding="utf-8")
    chunks = [{"doc": 0, "seq": 0, "chunk_text": "DSP 수율은 85%"}, {"doc": 0, "seq": 1, "chunk_text": "다른 내용"}]
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
    cc = [{"concept_id": "B", "chunk_key": f"{sha}:0", "count": 2}]
    (d / "concept_chunk.jsonl").write_text(json.dumps(cc[0]) + "\n", encoding="utf-8")
    gdir = d / "glossary"
    gdir.mkdir()
    import csv

    fields = [
        "concept_id",
        "canonical",
        "category",
        "synonyms",
        "abbreviations",
        "weak_synonyms",
        "broader",
        "related",
        "context_required",
        "case_sensitive",
        "definition_ko",
        "definition_en",
        "source",
        "owner",
        "status",
        "updated",
    ]
    rows = [
        {
            "concept_id": "A",
            "canonical": "Upstream Process",
            "category": "process",
            "synonyms": "",
            "abbreviations": "USP",
            "weak_synonyms": "",
            "broader": "",
            "related": "B",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "",
            "definition_en": "",
            "source": "",
            "owner": "",
            "status": "approved",
            "updated": "",
        },
        {
            "concept_id": "B",
            "canonical": "Downstream Process",
            "category": "process",
            "synonyms": "",
            "abbreviations": "DSP",
            "weak_synonyms": "",
            "broader": "",
            "related": "A",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "하류 공정",
            "definition_en": "",
            "source": "",
            "owner": "",
            "status": "approved",
            "updated": "",
        },
    ]
    with (gdir / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    out = d / "wiki"
    changed = build(d, out, gdir)
    assert set(changed) == {"A", "B"}, changed  # 처음엔 둘 다 새로 씀
    b_md = (out / "B.md").read_text(encoding="utf-8")
    assert "하류 공정" in b_md and "x.pdf" in b_md and f"{sha}:0" in b_md and "DSP 수율은 85%" in b_md
    assert "[Upstream Process](A.md) (A)" in b_md  # 관련 개념 링크
    changed2 = build(d, out, gdir)
    assert changed2 == []  # 근거 안 바뀜 — 다시 안 씀
    cc.append({"concept_id": "B", "chunk_key": f"{sha}:1", "count": 1})
    (d / "concept_chunk.jsonl").write_text("\n".join(json.dumps(r) for r in cc) + "\n", encoding="utf-8")
    changed3 = build(d, out, gdir)
    assert changed3 == ["B"]  # B만 근거가 바뀜 — B만 다시 씀
    print("[selftest] 개념 위키 — 변경분만 다시 생성(X4) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
