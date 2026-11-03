"""pl-39 — FAQ 엑셀 1행 = 청크 1개(질문+답), 시트 이름 = faq_group. 빈 칸은 None(행은 남김), 머리글 없는 시트는 건너뜀."""

import json
import tempfile
from pathlib import Path

from openpyxl import Workbook

from common.core.paths import STACK_FILE
from pipeline.transform.structure.build_bundle import main
from pipeline.transform.structure.chunking import faq_rows


def _book(path, sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)


HEAD = ["type", "client question", "answer", "last modified date"]


def test_faq_rows():
    with tempfile.TemporaryDirectory() as t:
        _rows(Path(t))


def _rows(d):
    f = d / "q.xlsx"
    _book(
        f,
        {
            "DS": [
                HEAD,
                ["capability", "Q1?", "A1", "2026-09-14"],
                [None, None, None, None],
                [None, "Q2?", None, None],
                ["divider", None, None, None],
            ],
            "memo": [["just", "notes"]],  # 머리글 없음 → 건너뜀
            "DP": [[None], ["Type", "Question", "Answer"], ["quality", "Q3?", "A3"]],  # 머리글 앞 빈 행 · 별칭 · 대소문자
        },
    )
    rows = faq_rows(f)
    assert [(r["group"], r["type"], r["question"], r["answer"], r["row"]) for r in rows] == [
        ("DS", "capability", "Q1?", "A1", 2),
        ("DS", None, "Q2?", None, 4),  # 빈 칸은 None, 통째로 빈 3행·질문·답 없는 5행은 건너뜀
        ("DP", "quality", "Q3?", "A3", 3),
    ]
    g = d / "n.xlsx"
    _book(g, {"memo": [["just", "notes"]]})
    assert faq_rows(g) is None  # 머리글 있는 시트가 없음 → 일반 문서
    assert faq_rows(d / "a.pdf") is None
    h = d / "h.xlsx"
    _book(h, {"DS": [HEAD]})
    assert faq_rows(h) is None  # 머리글만 → 일반 문서(청크 0개 문서를 만들지 않음)
    (d / "bad.xlsx").write_bytes(b"not a zip")
    assert faq_rows(d / "bad.xlsx") is None  # 못 여는 파일 → 일반 청킹(묶음 전체를 멈추지 않음)


def test_bundle_faq():
    with tempfile.TemporaryDirectory() as t:
        _bundle(Path(t))


def _bundle(root):
    pd, sd, out = root / "parse", root / "src", root / "bundle"
    (pd / "_rep").mkdir(parents=True)
    (pd / "_source").mkdir(parents=True)
    sd.mkdir()
    doc = "q.xlsx"
    _book(sd / doc, {"DS": [HEAD, ["capability", "Q1?", "A1", "2026-09-14"]], "DP": [HEAD, [None, "Q2?", "A2", None]]})
    rep = {"engine": "office_stdlib", "source": {}, "format": ".xlsx", "pages": 1, "meta": {"pairs": [], "all": []}}
    (pd / "_rep" / f"{doc}.json").write_text(json.dumps({"text": "DS type Q1? A1", "rep": rep}), encoding="utf-8")
    (pd / "_rep" / "index.json").write_text(json.dumps({"docs": [{"doc": doc, "engine": "office_stdlib"}]}), encoding="utf-8")
    (pd / "_source" / "manifest.jsonl").write_text(json.dumps({"file_name": doc, "key": "FAQ/u1/q.xlsx"}) + "\n", encoding="utf-8")
    main(["--parse-dir", str(pd), "--src", str(sd), "--embed", "none", "--stack", str(STACK_FILE), "--out", str(out)])
    cs = [json.loads(ln) for ln in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [(c["seq"], c["faq_group"], c["section"], c["chunk_text"], c["line_start"]) for c in cs] == [
        (0, "DS", "DS / capability", "Q: Q1?\nA: A1", 2),
        (1, "DP", "DP", "Q: Q2?\nA: A2", 2),  # 유형이 비면 절 = 시트 이름만
    ]
    assert {c["source_system"] for c in cs} == {"FAQ"}


def test_faq_sync():
    """pl-41(사용자 11-03) — faq_sync(reset)이 faq 스키마를 통째로 비움(reset 아니면 gold 목록만). 적재는 faq_group을 넣음."""
    import numpy as np

    from common.config.settings import COMMON
    from common.store import pg_standin as PS
    from common.store.db.dbtool import standin_script
    from pipeline.load import pgvector_load as M

    S, dim = "orca_pl41_t", 4
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:  # Windows — 열린 sqlite 대역 파일
        tmp = Path(t)
        b = tmp / "b"
        b.mkdir()
        (b / "meta.json").write_text(json.dumps({"dim": dim, "embed_model": "test"}), encoding="utf-8")
        keys = ["FAQ/u1/a.xlsx", "FAQ/u2/b.xlsx"]
        docs = [{"file_path": k, "source_system": "FAQ", "summary": "s", "full_text": "Q"} for k in keys]
        chunks = [
            {
                "doc": i,
                "seq": 0,
                "page": None,
                "line_start": 2,
                "line_end": 2,
                "bbox": None,
                "section": "DS",
                "chunk_text": "Q: q\nA: a",
                "n_terms": 2,
                "faq_group": "DS",
            }
            for i in range(2)
        ]
        (b / "docs.jsonl").write_text("".join(json.dumps(x) + "\n" for x in docs), encoding="utf-8")
        (b / "chunks.jsonl").write_text("".join(json.dumps(x) + "\n" for x in chunks), encoding="utf-8")
        np.save(b / "vectors.npy", np.ones((2, dim), dtype="float32"))
        with COMMON.env(PG_STANDIN_DIR=str(tmp / "pg")):
            db, fq = PS.StandinPG(S), PS.StandinPG(f"{S}_faq")
            with fq.cn.cursor() as cur:
                cur.execute(standin_script(f"{S}_faq", dim))
            M.load(db, b)
            assert {r["faq_group"] for r in fq.q(f"SELECT faq_group FROM {S}_faq.chunk")} == {"DS"}
            assert M.faq_sync(db, False) == (0, keys)  # 지우지 않고 gold 목록만
            assert M.faq_sync(db, True) == (2, [])  # 새 FAQ — 통째로 비움
            assert fq.q(f"SELECT COUNT(*) AS n FROM {S}_faq.doc")[0]["n"] == 0
            assert fq.q(f"SELECT COUNT(*) AS n FROM {S}_faq.chunk")[0]["n"] == 0
            assert M.faq_sync(db, True) == (0, [])  # 빈 스키마 — 그대로
