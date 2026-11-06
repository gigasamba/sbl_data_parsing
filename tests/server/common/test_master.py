"""마스터 표 `<PG_SCHEMA>_master.glossary`(op-17 규칙 19~21): 판 0002_master ↔ 모델 칸 · 스키마 이름 · `master load`(한 트랜잭션·해시) ·
glossary(melt)에서 되돌린 옛 행 모양으로 terms.py가 옛 CSV와 같은 값을 냄 · 서버는 못 읽으면 멈춤 · gold_version 꼴. 임시 SQLite 대역만 — 외부 접속 없음."""

import csv
import importlib.util
import shutil
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from common.core import terms as T
from common.core.paths import GLOSSARY_ROOT
from common.store import master as M
from common.store import pg as PGC
from common.store.db import dbtool as D
from common.store.db.models.master_tables import COLS, master_metadata


def _standin(d):
    """임시 대역 폴더 + 접속 정보 없음(PC) — 끝나면 되돌림."""
    M.reset()
    stack = [COMMON.env(PG_STANDIN_DIR=str(d), RUN_ENV="local"), mock.patch.object(PGC, "has_conn", return_value=False)]
    for c in stack:
        c.__enter__()
    return stack


def _close(stack):
    for c in reversed(stack):
        c.__exit__(None, None, None)
    M.reset()


def _mig(name):
    sp = importlib.util.spec_from_file_location(name, D.MIGRATIONS / "versions" / f"{name}.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


def test_migration_matches_model():
    m1, m2 = _mig("0001_master_base"), _mig("0002_master_glossary")
    assert m2.COLS == COLS and m2.down_revision == m1.revision  # 판이 굳힌 칸 = 모델
    assert set(m2.OLD) == {*m1.TABLES, "master_meta"}  # 판 0001의 표를 모두 지움
    assert set(master_metadata("x").tables) == {"x.glossary"}
    head = next(csv.reader([(GLOSSARY_ROOT / M.CSV_NAME).read_text(encoding="utf-8-sig").splitlines()[0]]))
    assert tuple(h.strip() for h in head) == COLS, head  # 표 칸 = git CSV 머리글


def test_schema_names():
    cases = [  # (--target, --schema, 갈래 → 기대 스키마 인자)
        ("all", "demo", {"search": "demo", "applog": None, "master": "demo"}),
        ("master", "x", {"master": "x"}),
        ("applog", "test_a", {"applog": "test_a"}),
    ]
    for target, schema, want in cases:
        a = Namespace(target=target, schema=schema)
        assert {t: D._schema_arg(a, t) for t in want} == want, (target, schema)
    assert D.schema_of("master", "demo") == "demo_master" and D.head("master") == "0002_master"


# 옛 CSV 행(칸 일부 — 빠진 칸은 '') ↔ 같은 내용의 glossary 줄(구분, 원본 값, 유사값, 유사 종류, 설명, 문맥 필요, 대소문자 구분)
OLD = {
    "domain_terms": [
        {
            "concept_id": "BIZ.CMO", "canonical": "Contract Manufacturing Organization", "category": "business|org_cdmo",
            "synonyms": "위탁생산|수탁생산", "abbreviations": "CMO", "weak_synonyms": "", "broader": "", "related": "BIZ.X",
            "context_required": "생산|제조", "case_sensitive": "N", "definition_ko": "생산만 위탁", "definition_en": "Outsourced manufacturing",
            "source": "예제", "owner": "영업", "status": "approved", "updated": "2026-10-14",
        },
        {"concept_id": "BIZ.X", "canonical": "Hanbit", "category": "org_client", "synonyms": "한빛바이오|한빛", "abbreviations": "HB",
         "broader": "BIZ.CMO", "case_sensitive": "Y", "status": "approved"},
        {"concept_id": "D.1", "canonical": "Draft Term", "status": "draft"},
    ],
    "client_roster": [
        {"client_id": "C1", "canonical_name": "Argen Biopharma", "name_ko": "아르젠", "aliases": "Argen|ARG", "status": "active",
         "description": "샘플", "country": "US", "parent_client_id": "C0"},
        {"client_id": "C2", "canonical_name": "Old Bio", "aliases": "올드", "status": "inactive"},
    ],
    "id_patterns": [
        {"id_type": "contract_no", "regex": r"C-[A-Z]{2,4}-\d{4}", "example": "C-AB-2024", "note": "합성", "updated": "2026-10-02"},
        {"id_type": "lot_no", "regex": r"LOT-\d{4}"},
    ],
}  # fmt: skip
MELT = [
    ("term", "Contract Manufacturing Organization", "BIZ.CMO", "concept_id", "생산만 위탁", "생산|제조", "N"),
    ("term", "Contract Manufacturing Organization", "business", "category", "", "", ""),
    ("term", "Contract Manufacturing Organization", "org_cdmo", "category", "", "", ""),
    ("term", "Contract Manufacturing Organization", "위탁생산", "synonym", "", "", ""),
    ("term", "Contract Manufacturing Organization", "수탁생산", "synonym", "", "", ""),
    ("term", "Contract Manufacturing Organization", "CMO", "abbr", "", "", ""),
    ("term", "Contract Manufacturing Organization", "BIZ.X", "related", "", "", ""),
    ("term", "Contract Manufacturing Organization", "Outsourced manufacturing", "definition_en", "", "", ""),
    ("term", "Contract Manufacturing Organization", "예제", "source", "", "", ""),
    ("term", "Contract Manufacturing Organization", "영업", "owner", "", "", ""),
    ("term", "Contract Manufacturing Organization", "approved", "status", "", "", ""),
    ("term", "Contract Manufacturing Organization", "2026-10-14", "updated", "", "", ""),
    ("client", "Argen Biopharma", "C1", "client_id", "샘플", "", ""),
    ("client", "Argen Biopharma", "아르젠", "name_ko", "", "", ""),
    ("client", "Argen Biopharma", "Argen", "alias", "", "", ""),
    ("client", "Argen Biopharma", "ARG", "alias", "", "", ""),
    ("client", "Argen Biopharma", "US", "country", "", "", ""),
    ("client", "Argen Biopharma", "C0", "parent", "", "", ""),
    ("client", "Argen Biopharma", "active", "status", "", "", ""),
    ("term", "Hanbit", "BIZ.X", "concept_id", "", "", "Y"),
    ("term", "Hanbit", "org_client", "category", "", "", ""),
    ("term", "Hanbit", "한빛바이오", "synonym", "", "", ""),
    ("term", "Hanbit", "한빛", "synonym", "", "", ""),
    ("term", "Hanbit", "HB", "abbr", "", "", ""),
    ("term", "Hanbit", "BIZ.CMO", "broader", "", "", ""),
    ("term", "Hanbit", "approved", "status", "", "", ""),
    ("client", "Old Bio", "C2", "client_id", "", "", ""),
    ("client", "Old Bio", "올드", "alias", "", "", ""),
    ("client", "Old Bio", "inactive", "status", "", "", ""),
    ("id", "contract_no", r"C-[A-Z]{2,4}-\d{4}", "regex", "합성", "", ""),
    ("id", "contract_no", "C-AB-2024", "example", "", "", ""),
    ("id", "contract_no", "2026-10-02", "updated", "", "", ""),
    ("term", "Draft Term", "D.1", "concept_id", "", "", ""),
    ("term", "Draft Term", "draft", "status", "", "", ""),
    ("id", "lot_no", r"LOT-\d{4}", "regex", "", "", ""),
]


def _write_old(d):
    for name, cols in M.SHAPES.items():
        with (d / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows({c: r.get(c, "") for c in cols} for r in OLD[name])


def test_glossary_same_as_old_csv():
    """glossary 줄 → 옛 행 모양이 옛 CSV와 같고, terms.py 출력(용어 사전·ID 꼴·고객 별칭)도 옛 CSV로 읽은 값과 같다."""
    m = M.Master([dict(zip(COLS, r)) for r in MELT])
    for name, cols in M.SHAPES.items():
        assert m.rows(name) == [{c: r.get(c, "") for c in cols} for r in OLD[name]], name
    d = Path(tempfile.mkdtemp())
    _write_old(d)
    with mock.patch.object(M, "get", lambda: m):
        assert T.load_glossary() == T.load_glossary(d)
        assert [(t, p.pattern) for t, p in T.load_id_patterns_typed()] == [(t, p.pattern) for t, p in T.load_id_patterns_typed(d)]
        old = {}  # 파일 쪽 별칭: stack client_aliases + 명부 파일(read_roster) + 용어 사전 org_client(terms._build_aliases와 같은 순서)
        for c, al in T.read_roster(d / "client_roster.csv").items():
            old[c] = sorted(set(old.get(c, [])) | set(al))
        for r in T.load_glossary(d).values():
            if "org_client" in T.split_terms(r.get("category")):
                al = [x for x in T.split_terms(r.get("synonyms")) + T.split_terms(r.get("abbreviations")) if not T._SHORT_EN.fullmatch(x)]
                old[r["canonical"]] = sorted(set(old.get(r["canonical"], [])) | set(al))
        got = T._aliases()
        assert {c: got[c] for c in old} == old and "Old Bio" not in got, got
    bad = [  # 거부: 모르는 구분 · 모르는 유사 종류 · 한 값 종류가 두 줄
        [("unit", "g/L", "g/l", "variant", "", "", "")],
        [("term", "X", "x", "synonyms", "", "", "")],
        [("term", "X", "A", "concept_id", "", "", ""), ("term", "X", "B", "concept_id", "", "", "")],
    ]
    for rows in bad:
        try:
            M.Master([dict(zip(COLS, r)) for r in rows])
            raise AssertionError(f"거부 안 함: {rows}")
        except SystemExit:
            pass


def test_load_hash_and_transaction():
    d = Path(tempfile.mkdtemp())
    st = _standin(d)
    try:
        m1 = M.get()
        rows = M.read_csv()
        assert len(m1.glossary) == len(rows) and m1.hash == M.content_hash(rows) and m1.rows("domain_terms") and m1.rows("client_roster")
        M.reset()
        assert M.get().hash == m1.hash  # 같은 CSV — 같은 해시(다시 읽어도)
        db = M._standin("ai")
        g = d / "g"
        shutil.copytree(GLOSSARY_ROOT, g)
        p = g / M.CSV_NAME
        p.write_text(p.read_text(encoding="utf-8-sig") + "id,test_id,TST-\\d+,regex,,,\n", encoding="utf-8")
        h2 = M.load(db, M.read_csv(g))
        assert h2 != m1.hash and M.read(db).hash == h2 and len(M.read(db).rows("id_patterns")) == len(m1.rows("id_patterns")) + 1
        # 한 트랜잭션 — 중간에 실패하면 이전 내용 그대로
        real = db.cn.cursor
        calls = {"n": 0}

        def flaky():
            cur = real()
            ex = cur.execute

            def execute(sql, params=None):
                calls["n"] += 1
                if calls["n"] == 20:
                    raise RuntimeError("boom")
                return ex(sql, params)

            cur.execute = execute
            return cur

        with mock.patch.object(db.cn, "cursor", flaky):
            try:
                M.load(db)
                raise AssertionError("실패가 안 남")
            except RuntimeError:
                pass
        assert M.read(db).hash == h2  # 바뀌지 않음
        try:  # 읽을 때 거부될 내용은 쓰지 않음
            M.load(db, [dict(zip(COLS, ("unit", "g/L", "g/l", "variant", "", "", "")))])
            raise AssertionError("모르는 구분을 씀")
        except SystemExit:
            pass
        assert M.read(db).hash == h2
    finally:
        _close(st)


def test_server_refuses_and_empty_table():
    d = Path(tempfile.mkdtemp())
    M.reset()
    with COMMON.env(PG_STANDIN_DIR=str(d), RUN_ENV="dev"), mock.patch.object(PGC, "has_conn", return_value=False):
        try:
            M.get()
            raise AssertionError("서버가 대역으로 시작함")
        except SystemExit:
            pass
    st = _standin(d)
    try:
        db = M._standin("ai")
        db.q(f"DELETE FROM {db.schema}.glossary")
        try:
            M.read(db)
            raise AssertionError("빈 glossary를 읽음")
        except SystemExit as e:
            assert "master load" in str(e)
    finally:
        _close(st)


def test_gold_version():
    from pipeline.load import pgvector_load as L
    from pipeline.load.publish_parse_result import pipeline_version

    v = pipeline_version()
    cases = [({"master_hash": "58a24b0258b4a00772"}, f"{v}+m58a24b02"), ({}, v), (None, v)]
    for meta, want in cases:
        assert L.gold_version(meta) == want, (meta, L.gold_version(meta))
    assert len(f"{v}+m12345678") <= 64  # 판 표기 길이 상한 64자


def test_standin_follows_csv_and_mcp_preload():
    """PC 대역은 git CSV가 바뀌면 다시 채움(낡은 명부로 남지 않게) · 검색 MCP는 검색기를 만들 때 마스터를 미리 읽어, 못 읽으면 RuntimeError."""
    d = Path(tempfile.mkdtemp())
    st = _standin(d)
    try:
        h1 = M.get().hash
        changed = [*M.read_csv(), dict(zip(COLS, ("client", "Zeta Bio", "Z1", "client_id", "", "", "")))]
        with mock.patch.object(M, "read_csv", lambda folder=None: changed):
            M.reset()
            h2 = M.get().hash
        assert h2 != h1 and h2 == M.content_hash(changed), (h1, h2)
        M.reset()
        assert M.get().hash == h1  # 원래 CSV로 돌아오면 다시 맞춤
    finally:
        _close(st)
    from mcp_server.services.search import server_state as SS

    with mock.patch.object(SS, "check_store", lambda: None), mock.patch.object(M, "get", side_effect=SystemExit("[master] 비어 있음")):
        try:
            SS._build_retriever()
            raise AssertionError("마스터 못 읽는데 검색기를 만듦")
        except RuntimeError as e:
            assert "master" in str(e)
