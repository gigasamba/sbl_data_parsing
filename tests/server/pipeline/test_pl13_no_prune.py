"""pl-13 — 적재(pgvector_load.load)는 더하고 고치기만 한다: 이번 묶음에 없는 저장 문서(원천에서 지움·이번에 건너뜀)는 그대로 남는다.
전에는 --prune(cli load·run-stack·색인 빌드 --pg가 기본으로 붙임)이 바뀌지 않아 건너뛴 문서까지 지웠다(C-60). 검색 스키마는 실 pgvector 임시 스키마
(goldseed.gold — test_*, 시험 뒤 지움) · 묶음은 임시 폴더."""

import json
import shutil
import tempfile
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pipeline.load import pgvector_load as M
from tests.server.common import pgcase
from tests.server.pipeline.goldseed import gold

DIM = 4


def _bundle(paths, tmp, source_system="SFDC"):
    d = Path(tempfile.mkdtemp(dir=tmp))
    (d / "meta.json").write_text(json.dumps({"dim": DIM, "embed_model": "test"}), encoding="utf-8")
    docs = [
        {
            "file_path": p,
            "source_system": source_system,
            "summary": p,
            "clients": ["A사"],
            "doc_class": "RFP",
            "created_at": "2025-03-01 10:00:00",
        }
        for p in paths
    ]
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


def kst(v):
    """DB 시각(timestamptz) → KST ISO 글자."""
    return v.astimezone(timezone(timedelta(hours=9))).isoformat()


def _callers_no_prune():
    """호출부(cli load·run-stack)가 만드는 명령에 --prune이 없음(C-60은 호출부가 붙이던 결함) — 그 파일 글자로 확인(색인 빌더는 11-01에 지움)."""
    from pipeline import cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert '"--prune"' not in src, "pipeline.cli가 아직 --prune을 붙임"


def test_load_keeps_docs_not_in_run():
    """명령 입구(main load — 호출부가 부르는 것)로 두 번 적재. 임시 폴더는 끝나면 지움."""
    _callers_no_prune()
    tmp = Path(tempfile.mkdtemp())
    try:
        _run_twice(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_twice(tmp):
    with gold(DIM) as S:
        db = pgcase.connect(S)
        sf = M._Src(db, f"{S}_sfdc")  # 원천 스키마(pl-28) — SFDC 문서가 들어감
        la = M._Src(db, f"{S}_las")  # 원천이 바뀐 문서가 옮겨 갈 곳
        with patch.object(M, "PG", return_value=db):
            M.main(["load", "--bundle", str(_bundle(["SFDC/u/a.txt", "SFDC/u/b.txt"], tmp))])
            M.main(
                ["load", "--bundle", str(_bundle(["SFDC/u/c.txt", "SFDC/u/a.txt"], tmp))]
            )  # b는 이번 묶음에 없음 · a는 이미 있음(건너뜀)
            counts = M.load(db, _bundle(["SFDC/u/d.txt"], tmp))
            S2 = f"{S}_sfdc"
            docs = sorted(str(r["file_path"]) for r in sf.q(f"SELECT file_path FROM {S2}.doc"))
            meta = {
                (r["doc_class"], kst(r["created_at"]), r["clients_doc"])
                for r in sf.q(f"SELECT attrs->>'doc_class' AS doc_class, created_at, clients_doc FROM {S2}.doc")  # pl-52 — attrs 키
            }
            loaded = sf.q(f"SELECT loaded_at, gold_version FROM {S2}.doc WHERE file_path = 'SFDC/u/a.txt'")[0]  # op-17 — 적재 시각·판
            n_chunks = _count(sf, f"SELECT COUNT(*) AS n FROM {S2}.chunk")
            b_terms = _count(
                sf,
                f"SELECT COUNT(*) AS n FROM {S2}.chunk_term t JOIN {S2}.chunk c ON c.chunk_id = t.chunk_id "
                f"JOIN {S2}.doc d ON d.doc_id = c.doc_id WHERE d.file_path = 'SFDC/u/b.txt'",
            )
            moved = []  # (경우, sfdc에 있나, las에 있나) — 같은 원본 경로의 원천이 SFDC → LAS로 바뀜(리뷰 #86)
            for case, rep_ in (("replace 없음 — 어디든 있으면 건너뜀", False), ("--replace — 옛 스키마에서 지우고 새 스키마에", True)):
                M.load(db, _bundle(["SFDC/u/b.txt"], tmp, source_system="LAS"), replace=rep_)
                inn = lambda x, p="SFDC/u/b.txt": bool(x.q(f"SELECT 1 AS o FROM {x.schema}.doc WHERE file_path = %s", (p,)))
                moved.append((case, inn(sf), inn(la)))
            try:
                M.main(["load", "--prune"])
                raise AssertionError("--prune이 아직 받아짐(지우는 길이 남음)")
            except SystemExit as e:
                assert e.code == 2, e.code  # argparse — 모르는 인자
        db.cn.close()
    assert docs == ["SFDC/u/a.txt", "SFDC/u/b.txt", "SFDC/u/c.txt", "SFDC/u/d.txt"], docs  # 묶음에 없던 b도 남음
    assert n_chunks == 4 and b_terms > 0, (n_chunks, b_terms)  # b의 청크·키워드 색인도 그대로
    assert meta == {("RFP", "2025-03-01T10:00:00+09:00", '["A사"]')}, meta  # 분류·등록 시각(시간대 없는 값은 KST)·본문 고객 라벨
    assert loaded["loaded_at"] and loaded["gold_version"] and counts["by_source"]["sfdc"]["docs"] == 1, (loaded, counts)
    assert counts["meta_missing"] == 1, counts
    assert moved == [("replace 없음 — 어디든 있으면 건너뜀", True, False), ("--replace — 옛 스키마에서 지우고 새 스키마에", False, True)], (
        moved
    )  # pl-29 — EDW 계정 없음: 메타를 비운 채 적재(건수만)
    print("[시험] 적재 — 원천 스키마로 · 묶음에 없는 저장 문서는 지우지 않음 · --prune 없음 · doc loaded_at·gold_version")
