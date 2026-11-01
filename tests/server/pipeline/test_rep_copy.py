"""mc-15(C8) — 적재가 ParsingMeta(source_system + source_key)의 대표 결과 위치를 gold doc(rep_bucket·rep_key·parsed_at)에 복사.
검색 스키마 SQLite 대역 + 가짜 ParsingMeta(외부 접속 없음, 임시 폴더만)."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.config.settings import COMMON
from common.store import parsing_meta_db as PMDB
from common.store import pg_standin as PS
from common.store.db.dbtool import standin_script
from pipeline.load import pgvector_load as M

DIM = 4


class FakePM:
    def __init__(self, rows):
        self.rows, self.closed = rows, False

    def find_by_source(self, source_key):
        return [r for r in self.rows if r["source_key"] == source_key]

    def close(self):
        self.closed = True


ROWS = [
    {
        "source_system": "SFDC",
        "source_key": "SFDC/u1/a.pdf",
        "parse_date": "2025-04-01_090000",
        "status": "changed",
        "rep_bucket": "b",
        "rep_key": "PR/a1/",
        "parsed_at": "2025-04-01 00:00:00",
    },
    {
        "source_system": "SFDC",
        "source_key": "SFDC/u1/a.pdf",
        "parse_date": "2025-04-02_090000",
        "status": "active",
        "rep_bucket": "b",
        "rep_key": "PR/a2/",
        "parsed_at": "2025-04-02 00:00:00",
    },
    {
        "source_system": "FileStorageMap",
        "source_key": "LAS/u2/c.pdf",
        "parse_date": "2025-04-03_090000",
        "status": "active",
        "rep_bucket": "b",
        "rep_key": "PR/c/",
        "parsed_at": None,
    },
    {
        "source_system": "SFDC",
        "source_key": "SFDC/u3/d.pdf",
        "parse_date": "2025-04-03_090000",
        "status": "active",
        "rep_bucket": None,
        "rep_key": None,
        "parsed_at": None,
    },
]


def test_find_rep():
    pm = FakePM(ROWS)
    cases = [  # (source_system, source_key, 기대 rep_key)
        ("SFDC", "SFDC/u1/a.pdf", "PR/a2/"),  # active 중 가장 늦은 parse_date
        ("LAS", "LAS/u2/c.pdf", "PR/c/"),  # 원천 표기가 다른 옛 행 — source_key로 대체
        ("SFDC", "SFDC/u3/d.pdf", None),  # 결과 위치가 빈 행
        ("SFDC", "none", None),
    ]
    for sys_, key, want in cases:
        got = PMDB.find_rep(pm, sys_, key)
        assert (got or {}).get("rep_key") == want, (sys_, key, got)


def test_load_copies_rep():
    S = "orca_mc15_t"
    tmp = Path(tempfile.mkdtemp())
    try:
        d = tmp / "bundle"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"dim": DIM, "embed_model": "test"}), encoding="utf-8")
        docs = [
            {"file_path": "/d/a.pdf", "source_system": "SFDC", "s3_key": "SFDC/u1/a.pdf"},
            {"file_path": "/d/x.pdf", "source_system": "SFDC"},  # 원본 키 없음 — 비움
        ]
        chunks = [
            {
                "doc": i,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "char_start": 0,
                "char_end": 1,
                "bbox": None,
                "section": None,
                "chunk_text": "x",
                "n_chars": 1,
                "n_terms": 1,
            }
            for i in range(2)
        ]
        (d / "docs.jsonl").write_text("".join(json.dumps(x) + "\n" for x in docs), encoding="utf-8")
        (d / "chunks.jsonl").write_text("".join(json.dumps(x) + "\n" for x in chunks), encoding="utf-8")
        np.save(d / "vectors.npy", np.ones((2, DIM), dtype="float32"))
        with COMMON.env(PG_STANDIN_DIR=str(tmp / "pg")):
            db = PS.StandinPG(S)
            with db.cn.cursor() as cur:
                cur.execute(standin_script(S, DIM))
        pm = FakePM(ROWS)
        with patch.object(M, "pg_connect", return_value=db), patch.object(PMDB, "make_db", return_value=pm):
            M.main(["load", "--bundle", str(d)])
        got = {
            r["file_path"]: (r["rep_bucket"], r["rep_key"], r["parsed_at"])
            for r in db.q(f"SELECT file_path, rep_bucket, rep_key, parsed_at FROM {S}.doc")
        }
        assert got == {"/d/a.pdf": ("b", "PR/a2/", "2025-04-02T00:00:00+00:00"), "/d/x.pdf": (None, None, None)}, got  # parsed_at은 UTC
        assert pm.closed
        # ParsingMeta를 못 열어도 적재는 계속(값만 비움)
        with patch.object(PMDB, "make_db", side_effect=SystemExit("no conn")):
            assert M._pm_reader(docs) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[시험] mc-15 — 적재가 ParsingMeta 대표 결과 위치(active·최신)를 gold doc에 복사 · 못 열면 비우고 계속")
