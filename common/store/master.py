"""마스터 표 읽기·채우기(pl-38·op-17) — 용어집·고객 명부·ID 꼴의 원본은 git CSV `resources/vocab/glossary/glossary.csv`, 실행 중에는
검색 PG의 `<PG_SCHEMA>_master.glossary` 표만 읽는다. 읽는 곳: common.core.terms(구조화 고객 판별·검색) — 프로세스마다 한 번(get()).
마스터를 못 읽으면 멈춘다(SystemExit — PC도 같음: `dbtool up --target master` 뒤 `dbtool master load`).
glossary는 melt 꼴(유사값마다 한 줄 — 구분·원본 값·유사값·유사 종류·설명·문맥 필요·대소문자 구분). terms.py(핸드오프 파일 — 고치지 않음)가
읽던 행 모양(`rows("domain_terms")`·`rows("client_roster")`·`rows("id_patterns")`)으로 되돌려 넘긴다(op-17 규칙 21).
해시 = 머리글·row_no 순서 행의 sha256(16진) — 읽을 때 계산. `gold_version` `<VERSION>+m<앞 8자>`(적재 — 구조화가 읽은 값을 묶음 meta.json으로 넘김)."""

import hashlib
import json
import re
import threading
from pathlib import Path

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
# 구분 → (옛 표, 원본 값이 가는 칸, 머리 줄 유사 종류(설명을 가짐 — 한 고객·용어·ID 꼴의 시작), 설명이 가는 칸, {유사 종류: 옛 칸})
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
LISTS = {"alias", "category", "synonym", "abbr", "weak", "broader", "related"}  # 여러 줄 → 옛 칸 `|` 목록
FLAGS = ("context_required", "case_sensitive")  # 용어(term)만 — 그 용어의 줄 어디에 적어도 됨(변환본은 concept_id 줄)


def to_tables(rows):
    """glossary 행 → {옛 표: [행 사전…]}(파일 순서, 빈 칸은 ''). 고객·용어·ID 꼴 하나는 머리 줄(client_id·concept_id·regex)에서 시작하고
    바로 뒤따르는 같은 구분·원본 값 줄이 거기에 붙는다 — 이름이 같은 고객 둘·이름 없는 용어도 따로, ID 꼴은 regex 줄마다 하나(그 줄 순서).
    SystemExit: 모르는 구분·유사 종류 · 머리 줄 없이 나온 줄 · 값이 하나인 종류가 한 묶음에 두 줄."""
    groups, cur = [], {}  # cur: 구분 → 지금 묶음 (첫 줄 번호, 원본 값, [줄…])
    for i, r in enumerate(rows, 1):
        kind, vk = r["kind"], r["variant_kind"]
        if kind not in KINDS or vk not in KINDS[kind][4]:
            raise SystemExit(f"[master] glossary {i}번째 줄: 모르는 구분·유사 종류 {kind!r}·{vk!r}")
        head = KINDS[kind][2]
        if vk == head:
            cur[kind] = (i, r["canonical"], [])
            groups.append((kind, cur[kind]))
        elif kind not in cur or cur[kind][1] != r["canonical"]:
            raise SystemExit(f"[master] glossary {i}번째 줄: {kind} {r['canonical']!r} 앞에 {head} 줄이 없음(머리 줄 바로 뒤에 적음)")
        cur[kind][2].append(r)
    out: dict = {t: [] for t in SHAPES}
    for kind, (i, canon, rs) in groups:
        table, name_col, head, desc_col, cols = KINDS[kind]
        row = dict.fromkeys(SHAPES[table], "")
        row[name_col], row[desc_col] = canon, rs[0]["description"]
        vals: dict = {}
        for r in rs:
            if r["variant"] or r["variant_kind"] not in LISTS:
                vals.setdefault(r["variant_kind"], []).append(r["variant"])
            for f in FLAGS if kind == "term" else ():
                row[f] = row[f] or r[f]
        for vk, vs in vals.items():
            if vk not in LISTS and len(vs) > 1:
                raise SystemExit(f"[master] glossary {i}번째 줄부터 {kind} {canon!r}: {vk} 줄이 둘 이상")
            row[cols[vk]] = "|".join(vs)
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
    """git glossary.csv(폴더 또는 파일 경로) → [행 사전…]. 머리글이 표 정의와 다르면 거부(칸을 바꾸려면 새 Alembic 판)."""
    import csv

    from common.core.terms import _read_text

    path = Path(folder) / CSV_NAME if Path(folder).is_dir() else Path(folder)  # 폴더(glossary.csv) 또는 파일 경로
    rows = list(csv.reader(_read_text(path)[0].splitlines()))
    head = _head(rows[0] if rows else [])
    if head != COLS:
        raise SystemExit(f"[master] {path.name} 머리글이 표와 다름 — 칸을 바꾸려면 새 Alembic 판(master): {head}")
    return _rows(rows, head, path.name)


def _rows(lines, head, name):
    """CSV 줄(머리글 포함) → [행 사전…](빈 줄 건너뜀, 모자란 칸은 빈 값). 칸이 머리글보다 많으면 거부."""
    out = []
    for n, r in enumerate(lines[1:], 2):
        if not any(c.strip() for c in r):  # 빈 줄·Excel 끝 줄(',,,,,,')
            continue
        if any(c.strip() for c in r[len(head) :]):
            raise SystemExit(f"[master] {name} {n}번째 줄: 칸이 머리글보다 많음(따옴표 없는 쉼표?)")
        out.append(dict(zip(head, [*r, *[""] * len(head)])))
    return out


def _head(cells):
    """머리글 칸(앞뒤 공백·끝의 빈 칸 뺌 — Excel이 붙이는 빈 열)."""
    head = [h.strip() for h in cells]
    while head and not head[-1]:
        head.pop()
    return tuple(head)


def is_glossary(path):
    """CSV 머리글이 glossary 꼴인지(첫 칸이 `kind`) — 명부 점검·초안 도구가 옛 꼴과 가를 때."""
    import csv

    from common.core.terms import _read_text

    first = _read_text(path)[0].splitlines()[:1]
    return _head(next(csv.reader(first), []))[:1] == ("kind",)


def melt(tables):
    """옛 행 모양 {옛 표: [행 사전…]} → glossary 행(to_tables의 반대 — 같은 대응). 원본 값 = 정식 이름·표준 이름·ID 종류(빈 값도 그대로).
    목록 칸은 `|`(고객 별칭은 `;`도)로 나눠 한 줄씩, 빈 값은 줄을 만들지 않는다. 머리 줄(client_id·concept_id·regex)은 옛 행마다 늘 맨 앞에 만든다(ID의 정규식은 나누지 않음)."""
    out = []
    for kind, (table, name_col, head, desc_col, cols) in KINDS.items():
        for r in tables.get(table, []):
            r = {k: (v or "") for k, v in r.items() if k is not None}
            canon = r.get(name_col, "")
            flags = [r.get(f, "") for f in FLAGS] if kind == "term" else ["", ""]
            out.append(dict(zip(COLS, (kind, canon, r.get(cols[head], ""), head, r.get(desc_col, ""), *flags))))
            for vk, col in cols.items():
                v = r.get(col, "")
                if vk == head or not v:
                    continue
                items = re.split(r"[;|]" if vk == "alias" else r"\|", v) if vk in LISTS else [v]
                out += [dict(zip(COLS, (kind, canon, x.strip(), vk, "", "", ""))) for x in items if x.strip()]
    return out


def write_csv(rows, path):
    """glossary 행 → CSV(UTF-8·LF, 머리글 COLS)."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLS)
    w.writerows([r.get(c) or "" for c in COLS] for r in rows)
    Path(path).write_text(buf.getvalue(), encoding="utf-8", newline="")


def convert(src, out):
    """옛 마스터 CSV 폴더(client_roster.csv·domain_terms.csv·id_patterns.csv — 없는 파일은 건너뜀) → glossary.csv. 반환: 줄 수.
    out이 이미 있으면 거부(덮어쓰지 않음) · 되돌려 읽기(to_tables)가 거부하는 내용이면 쓰지 않음."""
    import csv

    from common.core.terms import _read_text

    out, src = Path(out), Path(src)
    if out.exists():
        raise SystemExit(f"[master] {out}가 이미 있음 — 덮어쓰지 않음(다른 이름으로)")
    have = {n: src / f"{n}.csv" for n in SHAPES if (src / f"{n}.csv").is_file()}
    if not have:
        raise SystemExit(f"[master] {src}에 옛 마스터 CSV(client_roster·domain_terms·id_patterns)가 없음")
    tables = {}
    for n, f in have.items():
        lines = list(csv.reader(_read_text(f)[0].splitlines()))
        head = _head(lines[0] if lines else [])
        if set(head) != set(SHAPES[n]) or len(head) != len(SHAPES[n]):
            missing, extra = sorted(set(SHAPES[n]) - set(head)), sorted(set(head) - set(SHAPES[n]))
            raise SystemExit(f"[master] {f.name} 머리글이 옛 꼴과 다름 — 없는 칸 {missing} · 모르는(또는 겹친) 칸 {extra or list(head)}")
        tables[n] = _rows(lines, head, f.name)
    rows = melt(tables)
    to_tables(rows)
    write_csv(rows, out)
    return len(rows)


def load(db, rows=None):
    """glossary 내용을 CSV로 통째로 바꾼다(한 트랜잭션). db = PG(schema = 마스터 스키마). 반환: 해시.
    쓰기 전에 옛 행 모양으로 되돌려 본다 — 읽을 때 거부될 내용(모르는 구분·유사 종류 등)은 표를 바꾸지 않고 SystemExit."""
    rows = read_csv() if rows is None else rows
    to_tables(rows)
    s = db.schema
    sql = f"INSERT INTO {s}.{TABLE} (row_no, {', '.join(COLS)}) VALUES ({', '.join(['%s'] * (len(COLS) + 1))})"
    with db.cn.transaction():
        cur = db.cn.cursor()
        cur.execute(f"DELETE FROM {s}.{TABLE}")
        cur.executemany(sql, [(i, *(r.get(c) or "" for c in COLS)) for i, r in enumerate(rows, 1)])
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


def get():
    """이 프로세스의 마스터(처음 한 번 읽음) — common.store.pg 접속의 `<PG_SCHEMA>_master`."""
    with _GOT_LOCK:
        m = _GOT.get("m")
        if m is None:
            from common.store.pg import PG, conf

            c = conf()
            db = PG({**c, "PG_SCHEMA": schema_name(c["PG_SCHEMA"])})
            try:
                m = read(db)
            finally:
                db.cn.close()
            _GOT["m"] = m
        return m


def main(argv=None):
    """python -m common.store.master convert --src <옛 CSV 폴더> --out <glossary.csv> — 옛 마스터 CSV를 glossary 꼴로(op-17)."""
    import argparse

    from common.core.console import utf8_stdout

    utf8_stdout()
    ap = argparse.ArgumentParser(description="옛 마스터 CSV(client_roster·domain_terms·id_patterns) → glossary.csv")
    ap.add_argument("cmd", choices=["convert"])
    ap.add_argument("--src", required=True, help="옛 CSV가 있는 폴더")
    ap.add_argument("--out", required=True, help="만들 glossary.csv 경로(이미 있으면 거부)")
    a = ap.parse_args(argv)
    print(f"[master] {convert(a.src, a.out)}줄 → {a.out}")
    return 0


def reset():
    """다시 읽게(검색 서버가 적재 판 바뀜을 볼 때·시험)."""
    with _GOT_LOCK:
        _GOT.clear()


if __name__ == "__main__":
    raise SystemExit(main())
