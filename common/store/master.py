"""마스터 표 읽기·채우기(pl-38·op-17) — 용어집·고객 명부·ID 꼴의 원본은 git CSV `resources/vocab/glossary/glossary.csv`, 실행 중에는
검색 PG의 `<PG_SCHEMA>_master.glossary` 표만 읽는다. 읽는 곳: common.core.terms(구조화 고객 판별·검색) — 프로세스마다 한 번(get()).
서버(dev·prd)는 마스터를 못 읽으면 멈춘다(SystemExit). PC·시험(PG 접속 없음)은 같은 CSV로 채운 SQLite 대역(output/pg_standin/<스키마>_master.sqlite).
glossary는 melt 꼴(유사값마다 한 줄 — 구분·원본 값·유사값·유사 종류·설명·문맥 필요·대소문자 구분). terms.py(핸드오프 파일 — 고치지 않음)가
읽던 행 모양(`rows("domain_terms")`·`rows("client_roster")`·`rows("id_patterns")`)으로 되돌려 넘긴다(op-17 규칙 21).
해시 = 머리글·row_no 순서 행의 sha256(16진) — 읽을 때 계산. `gold_version` `<VERSION>+m<앞 8자>`(적재 — 구조화가 읽은 값을 묶음 meta.json으로 넘김)."""

import hashlib
import json
import threading

from common.core.paths import RES_ROOT
from common.store.db.models.master_tables import COLS, TABLE

GLOSSARY = RES_ROOT / "vocab" / "glossary"
CSV_NAME = "glossary.csv"
_GOT: dict = {}  # 프로세스마다 한 번 — {"m": Master}
_GOT_LOCK = threading.Lock()  # 검색 MCP는 여러 스레드 — 확인·채우기·비우기를 한 잠금으로

# terms.py가 읽는 옛 행 모양(칸 순서 = 옛 CSV 머리글)
SHAPES = {
    "client_roster": (
        "client_id", "canonical_name", "name_ko", "aliases", "client_type", "segment",
        "country", "parent_client_id", "status", "description", "source", "updated",
    ),
    "domain_terms": (
        "concept_id", "canonical", "category", "synonyms", "abbreviations", "weak_synonyms", "broader", "related",
        "context_required", "case_sensitive", "definition_ko", "definition_en", "source", "owner", "status", "updated",
    ),
    "id_patterns": ("id_type", "regex", "example", "note", "updated"),
}  # fmt: skip
# 구분 → (옛 표, 원본 값이 가는 칸, 설명을 가진 유사 종류, 설명이 가는 칸, {유사 종류: 옛 칸})
KINDS = {
    "client": ("client_roster", "canonical_name", "client_id", "description", {
        "client_id": "client_id", "name_ko": "name_ko", "alias": "aliases", "client_type": "client_type", "segment": "segment",
        "country": "country", "parent": "parent_client_id", "status": "status", "source": "source", "updated": "updated",
    }),
    "term": ("domain_terms", "canonical", "concept_id", "definition_ko", {
        "concept_id": "concept_id", "category": "category", "synonym": "synonyms", "abbr": "abbreviations", "weak": "weak_synonyms",
        "broader": "broader", "related": "related", "definition_en": "definition_en", "source": "source", "owner": "owner",
        "status": "status", "updated": "updated",
    }),
    "id": ("id_patterns", "id_type", "regex", "note", {"regex": "regex", "example": "example", "updated": "updated"}),
}  # fmt: skip
# 여러 줄 → 옛 칸 `|` 목록(id의 regex는 줄마다 한 행)
LISTS = {"alias", "category", "synonym", "abbr", "weak", "broader", "related", "regex"}
FLAGS = ("context_required", "case_sensitive")  # 용어(term)만 — 그 용어의 줄 어디에 적어도 됨(변환본은 concept_id 줄)


def to_tables(rows):
    """glossary 행 → {옛 표: [행 사전…]}(원본 값 처음 나온 순서, 빈 칸은 ''). 모르는 구분·유사 종류, 한 값 종류가 두 줄이면 SystemExit."""
    groups: dict = {}
    for i, r in enumerate(rows, 1):
        kind, vk = r["kind"], r["variant_kind"]
        if kind not in KINDS or vk not in KINDS[kind][4]:
            raise SystemExit(f"[master] glossary {i}번째 줄: 모르는 구분·유사 종류 {kind!r}·{vk!r}")
        groups.setdefault((kind, r["canonical"]), []).append(r)
    out: dict = {t: [] for t in SHAPES}
    for (kind, canon), rs in groups.items():
        table, name_col, head, desc_col, cols = KINDS[kind]
        row = dict.fromkeys(SHAPES[table], "")
        row[name_col] = canon
        vals: dict = {}
        for r in rs:
            if r["variant"] or r["variant_kind"] not in LISTS:
                vals.setdefault(r["variant_kind"], []).append(r["variant"])
            if r["variant_kind"] == head and r["description"]:
                row[desc_col] = r["description"]
            for f in FLAGS if kind == "term" else ():
                row[f] = row[f] or r[f]
        for vk, vs in vals.items():
            if vk not in LISTS and len(vs) > 1:
                raise SystemExit(f"[master] glossary {kind} {canon!r}: {vk} 줄이 둘 이상")
            row[cols[vk]] = "|".join(vs)
        if kind == "id":  # 정규식 줄마다 한 행(설명 = 그 줄 메모)
            out[table] += [
                {**row, "regex": r["variant"], "note": r["description"]} for r in rs if r["variant_kind"] == "regex" and r["variant"]
            ]
        else:
            out[table].append(row)
    return out


class Master:
    """읽은 마스터 — glossary 행(row_no 순서) · hash(16진 64자) · tables {옛 표: [행 사전…]}."""

    def __init__(self, rows):
        self.glossary = [{c: r.get(c) or "" for c in COLS} for r in rows]
        self.hash = content_hash(self.glossary)
        self.tables = to_tables(self.glossary)

    def rows(self, name):
        return self.tables.get(name, [])


def schema_name(base):
    return f"{base}_master"


def content_hash(rows):
    """머리글·행(row_no 순서)으로 만든 sha256 — 같은 CSV면 같은 값(PG·대역 어디서 읽어도)."""
    body = [list(COLS), [[r.get(c) or "" for c in COLS] for r in rows]]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_csv(folder=GLOSSARY):
    """git glossary.csv → [행 사전…]. 머리글이 표 정의와 다르면 거부(칸을 바꾸려면 새 Alembic 판)."""
    import csv

    from common.core.terms import _read_text

    rows = list(csv.reader(_read_text(folder / CSV_NAME)[0].splitlines()))
    head = tuple(h.strip() for h in rows[0])
    if head != COLS:
        raise SystemExit(f"[master] {CSV_NAME} 머리글이 표와 다름 — 칸을 바꾸려면 새 Alembic 판(master): {head}")
    return [dict(zip(COLS, [*r, *[""] * len(COLS)][: len(COLS)])) for r in rows[1:] if r]


def load(db, rows=None):
    """glossary 내용을 CSV로 통째로 바꾼다(한 트랜잭션). db = PG·StandinPG(schema = 마스터 스키마). 반환: 해시.
    쓰기 전에 옛 행 모양으로 되돌려 본다 — 읽을 때 거부될 내용(모르는 구분·유사 종류 등)은 표를 바꾸지 않고 SystemExit."""
    rows = read_csv() if rows is None else rows
    to_tables(rows)
    s = db.schema
    sql = f"INSERT INTO {s}.{TABLE} (row_no, {', '.join(COLS)}) VALUES ({', '.join(['%s'] * (len(COLS) + 1))})"
    with db.cn.transaction():
        cur = db.cn.cursor()
        cur.execute(f"DELETE FROM {s}.{TABLE}")
        for i, r in enumerate(rows, 1):
            cur.execute(sql, (i, *(r.get(c) or "" for c in COLS)))
    return content_hash(rows)


def _select(db):
    return db.q(f"SELECT {', '.join(COLS)} FROM {db.schema}.{TABLE} ORDER BY row_no")


def read(db):
    """glossary → Master(SELECT 한 번 — `master load`가 그 사이 커밋돼도 이전·새 내용이 섞이지 않음). 표가 없거나 비었으면(master load 전) SystemExit."""
    s = db.schema
    try:
        rows = _select(db)
    except Exception as e:  # 표 없음·권한 등 — 원인은 메시지에
        raise SystemExit(
            f"[master] 마스터 표를 못 읽음({s} — {type(e).__name__}): `dbtool up --target master` 뒤 `dbtool master load`"
        ) from e
    if not rows:
        raise SystemExit(f"[master] {s}.{TABLE}이 비어 있음 — `dbtool master load`로 채움")
    return Master(rows)


def _standin(base):
    """PC 대역 — 표가 없으면 만들고 CSV로 채움(실 PG와 같은 칸). git CSV가 바뀌었으면 다시 채움(PC 대역만 — 서버는 `dbtool master load`)."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from common.store.db.models.master_tables import master_metadata
    from common.store.pg_standin import StandinPG

    db = StandinPG(schema_name(base))
    if not db.q("SELECT name FROM sqlite_master WHERE type='table' AND name=%s", (TABLE,)):
        d = postgresql.dialect()
        for t in master_metadata(db.schema).tables.values():
            db.q(str(CreateTable(t).compile(dialect=d)).strip())
    rows = read_csv()
    if content_hash(_select(db)) != content_hash(rows):
        load(db, rows)
    return db


def get():
    """이 프로세스의 마스터(처음 한 번 읽음). 실 PG(common.store.pg 접속)는 `<PG_SCHEMA>_master`, 접속 정보가 없으면 PC 대역 — 서버는 대역을 쓰지 않고 멈춤."""
    with _GOT_LOCK:
        m = _GOT.get("m")
        if m is None:
            from common.store.pg import PG, _standin_schema, _warn_standin, conf, has_conn

            if has_conn():
                c = conf()
                db = PG({**c, "PG_SCHEMA": schema_name(c["PG_SCHEMA"])})
                try:
                    m = read(db)
                finally:
                    db.cn.close()
            else:
                _warn_standin()  # 서버(dev·prd)는 여기서 SystemExit
                m = read(_standin(_standin_schema(None)))
            _GOT["m"] = m
        return m


def reset():
    """다시 읽게(검색 서버가 적재 판 바뀜을 볼 때·시험)."""
    with _GOT_LOCK:
        _GOT.clear()
