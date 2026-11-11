"""pl-68 — 실버 먼저 적재의 상태 기록: 게시(publish_parse_result.apply)가 올린 원본마다 `applog.except_doc_info` silver 행(수준 warn)을 쓰고,
골드 적재(pgvector_load.load)가 그 문서를 gold에 넣으면 지운다. 골드 실패(분류 실패 — gold에 안 넣음)·실버까지만 실행은 silver 행이 남는다.
실 pgvector 임시 스키마(goldseed.gold — applog도 `<기준>_applog`, 시험 뒤 지움)."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pipeline.load import doc_classify as CL
from pipeline.load import pgvector_load as M
from pipeline.load import publish_parse_result as P
from pipeline.shared import dlq
from pipeline.shared import except_docs as SD
from tests.server.common import pgcase
from tests.server.pipeline.goldseed import gold as gold_schema

KEY, DIM = "SFDC/u/a.pdf", 4
CASES = [  # (경우, 골드 적재를 돌림, 분류 답(실패면 gold에 안 넣음), silver 행이 남음)
    ("gold ok", True, '{"class": "RFP"}', False),
    ("gold fails", True, '{"class": "Others"}', True),
    ("silver only", False, None, True),
]


def _entry():
    row = {"source_key": KEY, "source_system": "SFDC", "parse_date": "2026-11-08", "rep_bucket": "file://x", "sha256": "0" * 64}
    row.update({"engines": [], "parse_status": "ok", "pipeline_version": "v1"})
    return {"row": row, "upload": True, "reparse": False, "doc_name": "a.pdf", "md_text": "본문", "raw": []}


def _bundle(d):
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"dim": DIM, "embed_model": "test"}), encoding="utf-8")
    doc = {"file_path": KEY, "source_system": "SFDC", "summary": "s", "full_text": "Request for Proposal"}
    ch = {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "char_start": 0, "char_end": 3, "bbox": None}
    ch.update({"section": None, "chunk_text": "RFP", "n_chars": 3, "n_terms": 1})
    (d / "docs.jsonl").write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text(json.dumps(ch, ensure_ascii=False) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.ones((1, DIM), dtype="float32"))
    return d


def _silver_rows():
    db = pgcase.connect(SD._schema())
    try:
        rows = db.q(f"SELECT source_key, reason, level FROM {db.schema}.{SD.TABLE} WHERE except_type = 'silver'")
        return [(r["source_key"], r["reason"], r["level"]) for r in rows]
    finally:
        db.cn.close()


def test_silver_row_table():
    for name, gold, answer, stays in CASES:
        tmp = Path(tempfile.mkdtemp())
        try:
            with gold_schema(DIM) as S:
                dlq.record_failure([{"source_key": KEY, "file_name": "a.pdf", "reason": "load_failed"}])
                P.apply([_entry()], P.LocalFolderStore(tmp / "os"), tmp / "md")
                assert _silver_rows() == [(KEY, SD.SILVER_REASON, "warn")], (name, _silver_rows())
                if gold:
                    db = sf = pgcase.connect(S)
                    with (
                        patch.object(CL, "_system", lambda src: "system"),
                        patch("common.ai.llm.chat", return_value=answer),
                        patch("pipeline.load.edw_doc_meta.fetch", return_value=({}, 0)),
                    ):
                        M.load(db, _bundle(tmp / "bundle"))
                    in_gold = [r["file_path"] for r in sf.q(f"SELECT file_path FROM {S}_sfdc.doc")]
                    assert in_gold == ([] if stays else [KEY]), (name, in_gold)
                    db.cn.close()
                assert bool(_silver_rows()) == stays, (name, _silver_rows())
                assert dlq.list_rows()[0]["status"] == ("pending" if stays else "resolved"), name
                assert dlq.list_rows()[0]["attempts"] == 1, "게시·적재의 컨테이너 이력은 DLQ 횟수를 늘리지 않음"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("[selftest] pl-68 — 게시가 silver 행을 쓰고 골드 성공이 지움 · 골드 실패·실버까지만은 남음 통과")
