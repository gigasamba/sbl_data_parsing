"""op-17 — 처리 기록은 gold `doc` 칸(판 0006): 적재(`load --silver`)가 게시 기록 파일(silver.jsonl)의 sha256·silver 위치·엔진·상태·silver 판·
게시 시각과 적재 판(gold_version)·적재 시각을 쓰고, 고르기(gold_docs)가 그 행으로 끝난 문서·내용 중복을 판정한다. PC 대역(임시 폴더)만 — 외부 접속 없음."""

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.config.settings import COMMON
from common.store import pg_standin as PS
from common.store.db.dbtool import standin_script
from pipeline.extract import candidate_pick as CP
from pipeline.load import pgvector_load as M
from pipeline.shared import except_docs as ED
from pipeline.shared import gold_docs as GD
from tests.server.pipeline.test_pl13_no_prune import DIM, _bundle

S = "test_op17"
ENG = [{"engine": "pymupdf", "role": "rep", "status": "ok", "version_or_model": "1.28.2", "calls": 1}]
# (원본 키, 처리 기록 줄(None = silver.jsonl에 없음), 기대 doc 칸)
CASES = [
    (
        "SFDC/u/a.pdf",
        {
            "sha256": "a" * 64,
            "silver_bucket": "rag-publish",
            "silver_key": "PR/SFDC/u/a_2026-11-06_013000.md",
            "engines": ENG,
            "parse_status": "ok",
            "silver_version": "0.3.0",
            "parsed_at": "2026-11-06T01:30:00+09:00",
        },
        {"sha256": "a" * 64, "silver_key": "PR/SFDC/u/a_2026-11-06_013000.md", "parse_status": "ok", "silver_version": "0.3.0"},
    ),
    ("SFDC/u/b.pdf", {"sha256": "b" * 64, "parse_status": "partial"}, {"sha256": "b" * 64, "parse_status": "partial"}),
    ("SFDC/u/c.pdf", None, {"sha256": None, "silver_key": None, "parse_status": None}),  # 기록 줄 없음 — 그 칸은 NULL
]
# done_by_sha(shas) → 기대 — 다른 원본 키가 같은 sha256이면 고르기가 내용 중복으로 본다
SHA_CASES = [
    (["a" * 64], {"a" * 64: ("SFDC/u/a.pdf", "ok")}),
    (["b" * 64, "f" * 64], {"b" * 64: ("SFDC/u/b.pdf", "partial")}),
    ([], {}),
]


# 두 번째 적재 — (replace, 처리 기록 줄 {원본 키: 줄}, 기대 {원본 키: 칸}) — 재게시 줄은 이미 있는 행의 칸만 고침, --replace인데 줄 없으면 옛 값
AGAIN = [
    (
        False,
        {"SFDC/u/a.pdf": {"silver_key": "PR/SFDC/u/a_2026-11-07_013000.md", "parsed_at": "2026-11-07T01:30:00+09:00"}},
        {"SFDC/u/a.pdf": {"silver_key": "PR/SFDC/u/a_2026-11-07_013000.md", "sha256": None}, "SFDC/u/b.pdf": {"sha256": "b" * 64}},
    ),
    (
        True,
        {},
        {
            "SFDC/u/a.pdf": {"silver_key": "PR/SFDC/u/a_2026-11-07_013000.md"},
            "SFDC/u/b.pdf": {"sha256": "b" * 64, "parse_status": "partial"},
        },
    ),
]


def _silver(tmp, lines):
    f = tmp / "silver.jsonl"
    f.write_text("".join(json.dumps({**r, "source_key": k}) + "\n" for k, r in lines.items()), encoding="utf-8")
    return str(f)


def test_doc_record():
    tmp = Path(tempfile.mkdtemp())
    try:
        with COMMON.env(RUN_ENV="local", PG_STANDIN_DIR=str(tmp / "pg"), PG_SCHEMA=S):
            db, sf = PS.StandinPG(S), PS.StandinPG(f"{S}_sfdc")
            with sf.cn.cursor() as cur:
                cur.execute(standin_script(f"{S}_sfdc", DIM))
            paths = [k for k, _, _ in CASES]
            M.load(db, _bundle(paths, tmp), silver=_silver(tmp, {k: r for k, r, _ in CASES if r}))
            rows = {r["file_path"]: r for r in sf.q(f"SELECT * FROM {S}_sfdc.doc")}
            for key, _, want in CASES:
                r = rows[key]
                assert {k: r[k] for k in want} == want, (key, r)
                assert r["gold_version"] and r["loaded_at"], (key, r)  # 적재 판·시각은 모든 문서
            a = rows["SFDC/u/a.pdf"]
            assert json.loads(a["engines"]) == ENG and a["silver_bucket"] == "rag-publish" and a["parsed_at"].startswith("2026-11-06"), a
            assert CP.done_keys() == set(paths)  # 끝난 문서 = doc 행이 있는 원본 키
            for shas, want in SHA_CASES:
                assert CP.done_by_sha(shas) == want, shas
            for replace, lines, want in AGAIN:
                M.load(db, _bundle(paths, tmp), replace=replace, silver=_silver(tmp, lines))
                rows = {r["file_path"]: r for r in sf.q(f"SELECT * FROM {S}_sfdc.doc")}
                for key, w in want.items():
                    assert {k: rows[key][k] for k in w} == w, (replace, key, rows[key])
            assert json.loads(rows["SFDC/u/a.pdf"]["engines"] or "null") is None  # 재게시 줄에 없던 칸은 그 줄 값(NULL)으로
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _PgErr(Exception):
    def __init__(self, code):
        self.sqlstate = code


# gold_docs._rows가 받은 오류 → 0건으로 넘김(True) / 그대로 올림(False — 서버 종료 4, pl-12)
ERR_CASES = [
    (sqlite3.OperationalError("no such table: x.doc"), True),
    (sqlite3.OperationalError("no such column: sha256"), True),
    (_PgErr("42P01"), True),
    (_PgErr("42703"), True),
    (_PgErr("28P01"), False),  # 로그인 실패
    (sqlite3.OperationalError("database is locked"), False),
    (OSError("connection refused"), False),
]


def test_gold_rows_errors():
    for ex, swallowed in ERR_CASES:

        def q(sql, params, ex=ex):
            raise ex

        with patch.object(GD, "_schemas", lambda: iter([(q, "s")])):
            try:
                got = GD._rows("SELECT 1 FROM {S}.doc") == []
            except Exception as e:
                got = e is not ex
        assert got == swallowed, ex
    with patch.object(ED, "record_error", side_effect=OSError("down")):
        assert ED.note_error([{"source_key": "k"}]) == 0  # 실패 기록은 적어 두는 것뿐 — 못 써도 계속
