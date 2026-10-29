"""pl-13 — 적재(pgvector_load.load)는 더하고 고치기만 한다: 이번 묶음에 없는 저장 문서(원천에서 지움·이번에 건너뜀)는 그대로 남는다.
전에는 --prune(cli load·run-stack·색인 빌드 --pg가 기본으로 붙임)이 바뀌지 않아 건너뛴 문서까지 지웠다(C-60). 검색 스키마 SQLite 대역 —
외부 접속 없음, 임시 폴더만."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from common.config.settings import COMMON
from common.store import pg_standin as PS
from common.store.db.dbtool import standin_script
from pipeline.load import pgvector_load as M

DIM = 4


def _bundle(paths):
    d = Path(tempfile.mkdtemp())
    (d / "meta.json").write_text(json.dumps({"dim": DIM, "embed_model": "test"}), encoding="utf-8")
    docs = [{"file_path": p, "summary": p, "clients": ["A사"]} for p in paths]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "char_start": 0,
            "char_end": 9,
            "bbox": None,
            "section": None,
            "chunk_text": f"바이러스 불활화 {p}",
            "n_chars": 9,
            "n_terms": 3,
        }
        for i, p in enumerate(paths)
    ]
    (d / "docs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in docs), encoding="utf-8")
    (d / "chunks.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in chunks), encoding="utf-8")
    np.save(d / "vectors.npy", np.ones((len(paths), DIM), dtype="float32"))
    return d


def _count(db, sql):
    return int(db.q(sql)[0]["n"] or 0)


def test_load_keeps_docs_not_in_run():
    """호출부가 쓰는 명령 입구(main load — cli load·run-stack·색인 빌드 --pg가 부름)로 두 번 적재."""
    S = "orca_pl13_t"
    with COMMON.env(PG_STANDIN_DIR=tempfile.mkdtemp()):
        db = PS.StandinPG(S)
        with db.cn.cursor() as cur:
            cur.execute(standin_script(S, DIM))
    with patch.object(M, "pg_connect", return_value=db):  # 늘 대역 — 설정 파일에 실 PG가 있어도 닿지 않게
        M.main(["load", "--bundle", str(_bundle(["/d/a.txt", "/d/b.txt"]))])
        M.main(["load", "--bundle", str(_bundle(["/d/c.txt", "/d/a.txt"]))])  # b는 이번 묶음에 없음 · a는 이미 있음(건너뜀)
        docs = sorted(str(r["file_path"]) for r in db.q(f"SELECT file_path FROM {S}.doc"))
        n_chunks = _count(db, f"SELECT COUNT(*) AS n FROM {S}.chunk")
        b_terms = _count(
            db,
            f"SELECT COUNT(*) AS n FROM {S}.chunk_term t JOIN {S}.chunk c ON c.chunk_id = t.chunk_id "
            f"JOIN {S}.doc d ON d.doc_id = c.doc_id WHERE d.file_path = '/d/b.txt'",
        )
        try:
            M.main(["load", "--prune"])
            raise AssertionError("--prune이 아직 받아짐(지우는 길이 남음)")
        except SystemExit as e:
            assert e.code == 2, e.code  # argparse — 모르는 인자
    assert docs == ["/d/a.txt", "/d/b.txt", "/d/c.txt"], docs  # 묶음에 없던 b도 남음
    assert n_chunks == 3 and b_terms > 0, (n_chunks, b_terms)  # b의 청크·키워드 색인도 그대로
    print("[시험] 적재 — 묶음에 없는 저장 문서(청크·키워드 색인 포함)는 지우지 않음 · --prune 없음")
