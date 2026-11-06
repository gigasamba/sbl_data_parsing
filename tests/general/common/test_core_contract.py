"""common.core.contract(인계 파일 — FINGERPRINT) 자기 점검 — 반입 판정 목록 밖의 일반 시험."""

import json
from pathlib import Path

from common import CONTRACT
from common.core.contract import check_parse


def selftest():
    import tempfile

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
    print("[selftest] 인계 계약 점검(파싱 _rep) 통과")


def test_main():
    selftest()
