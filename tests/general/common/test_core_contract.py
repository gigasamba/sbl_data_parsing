"""common.core.contract(인계 파일 — FINGERPRINT) 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.contract --selftest`(반입 판정 목록 밖 — 일반 시험).
⚠️ 이 옮기기는 인계 지문(FINGERPRINT)을 바꾼다(사용자 10-28 — 인계 파일 옮기기 커밋 하나, 되돌리기는 그 커밋 revert · refactor.md C-52)."""

import json
from pathlib import Path

from common import CONTRACT
from common.core.contract import DOC_KEYS, check_bundle, check_parse


def selftest():
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    rep = d / "_rep"
    rep.mkdir()
    assert "_DONE.json 없음" in check_parse(rep)
    (rep / "_DONE.json").write_text(json.dumps({"contract": CONTRACT}), encoding="utf-8")
    (rep / "index.json").write_text(json.dumps({"docs": [{"doc": "a.pdf", "engine": "x"}]}), encoding="utf-8")
    (rep / "sources.jsonl").write_text(json.dumps({"doc_key": "k" * 64}) + "\n", encoding="utf-8")
    (rep / "a.pdf.json").write_text(json.dumps({"rep": {"engine": "x", "format": ".pdf_text", "meta": {}, "tried": {}}}), encoding="utf-8")
    assert any("source" in b for b in check_parse(rep))  # 원본 정보 빠짐 → 잡힘
    (rep / "a.pdf.json").write_text(
        json.dumps(
            {
                "rep": {
                    "engine": "x",
                    "format": ".pdf_text",
                    "meta": {},
                    "tried": {},
                    "source": {"doc_key": "k" * 64, "uri": "s3://b/a.pdf", "sha256": "k" * 64},
                }
            }
        ),
        encoding="utf-8",
    )
    assert check_parse(rep) == []
    b = d / "bundle"
    b.mkdir()
    (b / "meta.json").write_text(json.dumps({"dim": 4}), encoding="utf-8")
    (b / "docs.jsonl").write_text(json.dumps({k: "v" for k in DOC_KEYS}) + "\n", encoding="utf-8")
    (b / "chunks.jsonl").write_text(json.dumps({"doc": 0, "seq": 0, "chunk_text": "t", "n_terms": 1}) + "\n", encoding="utf-8")
    for f in ("kg_nodes.jsonl", "kg_edges.jsonl"):
        (b / f).write_text("", encoding="utf-8")
    np.save(b / "vectors.npy", np.zeros((2, 4), np.float32))
    assert any("벡터 2행" in x for x in check_bundle(b))  # 벡터·청크 수 어긋남 → 잡힘
    np.save(b / "vectors.npy", np.zeros((1, 4), np.float32))
    assert check_bundle(b) == []
    print("[selftest] 인계 계약 점검(파싱 _rep · 구조화 묶음) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
