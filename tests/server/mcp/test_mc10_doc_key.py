"""mc-10 — 축소 스키마 묶음(docs.jsonl에 doc_key만, file_sha256 없음)으로 Retriever를 만들고 검색한다.
전에는 서버(LOCAL_RUN 아님)에서 d["file_sha256"]로 읽어 KeyError — 검색 MCP의 search가 매번 실패했다."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from mcp_server import config as mc
from mcp_server.services.search import retriever as RT


def _bundle(doc):
    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    c = {
        "doc": 0,
        "seq": 0,
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "chunk_text": "바이러스 불활화 공정",
        "n_terms": 3,
        "bbox": None,
        "section": None,
    }
    (d / "chunks.jsonl").write_text(json.dumps(c, ensure_ascii=False) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((1, 0), dtype="float32"))
    return d


def test_doc_key_bundle():
    path = "/data/docs/a.txt"
    cases = [  # (묶음 docs.jsonl 행, 기대 doc_key)
        ({"file_path": path, "doc_key": path}, path),  # 새 묶음 — doc_key만(file_name·file_sha256 없음, build_bundle 그대로)
        ({"file_path": path, "file_name": "a.txt", "file_sha256": "a" * 64}, "a" * 64),  # 옛 묶음 — file_sha256만
    ]
    with mc.senv(GLOSSARY_DIR=None):
        for doc, want in cases:
            R = RT.Retriever(_bundle(doc))
            assert list(R.doc_meta) == [want] and list(R.key_local) == [f"{want}:0"]
            hits, _ = R.search("바이러스", 5, methods=["bm25"])
            assert hits and hits[0]["doc_key"] == want and hits[0]["chunk_key"] == f"{want}:0", hits
            assert hits[0]["file_name"] == "a.txt" and R.client_map() == {"a.txt": None}, hits  # 고객 미상 = None(clientscope.doc_clients)

        class _PG:  # doc 표의 축소 열(file_path·clients)만 있음 — 없는 열을 고르면 실 PG처럼 오류
            schema = "ai"

            def q(self, sql, params=None):
                assert "client," not in sql and "file_name" not in sql, sql
                return [{"file_path": path, "clients": '["A사"]'}]

        R = RT.Retriever(_bundle(cases[0][0]))
        with patch.object(R, "pg", _PG()):
            assert R.client_map() == {"a.txt": ["A사"]}, R.client_map()
