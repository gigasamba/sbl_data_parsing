#!/usr/bin/env python3
"""SI43③ — EDW 고객·제품 마스터(추출본) → CLIENT_ROSTER CSV(고객)·용어집 draft(제품) 자동 생성. 열 매핑만 바꾸는
식(SI41 modules/parse/source.py와 같은 틀 — 표 이름·열 이름은 사람이 적는 매핑 파일 하나, 코드는 안 바뀜) — 실제
EDW 접속 정보·열 이름(기밀)은 서버 전용(/srv/rag/env/)에서만 채우고, 이 코드는 어떤 매핑이든 그대로 돈다.

시험은 --source csv:<경로>로(합성 EDW 추출본, 실제 RDB·네트워크 없이 — modules/parse/source.py의 csv:<경로>
시험 모드와 같은 관례). --source rdb:<표>(RDB_ENGINE=mssql 기본·pg, 접속은 common.connections.rdb 읽기 계정 — source.py와 같은 접속
스위치)는 실제 EDW 접속이 있는 서버에서만 — 이 PC에는 접속 정보가 없어 시험 대상이 아니다(selftest는 csv:만).

mapping.json(필수 name, 선택 aliases·category): {"name": "<열 이름>", "aliases": "<열 이름>", "category": "<열 이름>"}
  GL3(사용자 10-15) — --kind client는 새 명부 양식(ROSTER_COLS, server-guide §5-1)으로 쓴다. 매핑에 그 칸 이름을
  키로 더 적으면(client_id·name_ko·client_type·segment·country·parent_client_id·status·description·updated) 마스터의
  그 열을 옮겨 적고, 안 적은 칸은 빈칸. source 칸은 --source 값. 예시 resources/vocab/glossary/client_master_map.example.json.

사용:
  python -m pipeline.transform.structure.gen_roster --kind client  --source csv:client_master.csv  --mapping map.json --out CLIENT_ROSTER.csv
  python -m pipeline.transform.structure.gen_roster --kind product --source csv:product_master.csv --mapping map.json --out output/glossary_draft/domain_terms_draft_product.csv

--kind product의 --out은 **GLOSSARY_DIR이 아니라 draft CSV 파일**(terms.write_draft_terms, 독립 검토 BLOCK 1,
10-13 — GLOSSARY_DIR에 바로 쓰면 서버에서 이미지 밖 실 운영 사전 폴더라 권한 오류가 날 수 있다). 사람이 검토해
domain_terms.csv로 옮겨야 검색에 반영된다(cli/glossary_suggest.py T6와 같은 관례)."""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서
from common.core.console import utf8_stdout

# isort: split
import argparse
import csv
import json
import re
from pathlib import Path

from common.core import terms as T
from pipeline import config as pc  # S7c: 설정 객체(pipeline 칸 RDB_*)

TABLE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")  # source.py·common/sources.py와 같은 화이트리스트
COL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ROSTER_COLS = [
    "client_id",
    "canonical_name",
    "name_ko",
    "aliases",
    "client_type",
    "segment",
    "country",
    "parent_client_id",
    "status",
    "description",
    "source",
    "updated",
]  # terms.py new roster format (10-15)
EXTRA_KEYS = [c for c in ROSTER_COLS if c not in ("canonical_name", "aliases", "source")]  # optional mapping keys


def load_mapping(path_or_dict):
    """매핑 파일(JSON 경로) 또는 이미 읽은 dict → 검증된 dict. name은 필수, aliases·category는 선택 — 열 이름은
    전부 화이트리스트(SQL 삽입 방지, rdb: 쓸 때 식별자로 그대로 들어감)."""
    m = json.loads(Path(path_or_dict).read_text(encoding="utf-8")) if not isinstance(path_or_dict, dict) else path_or_dict
    if not m.get("name") or not COL_ID_RE.match(m["name"]):
        raise ValueError(f"[gen_roster] mapping.name 필요(열 이름, 영문·숫자·_ 만): {m.get('name')!r}")
    for k in ("aliases", "category", *EXTRA_KEYS):
        if m.get(k) and not COL_ID_RE.match(m[k]):
            raise ValueError(f"[gen_roster] mapping.{k} 열 이름이 올바르지 않음: {m[k]!r}")
    return m


def rows_from_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def rows_from_rdb(table, select_cols):
    """실제 EDW 표 — modules/parse/source.py와 같은 엔진 스위치(RDB_ENGINE 기본 mssql·pg, 접속은 common.connections.rdb 읽기 계정).
    열 이름은 호출부(main)가 이미 COL_ID_RE로 검증한 것만 들어온다(SQL 삽입 방지, source.py와 같은 원칙)."""
    if not TABLE_ID_RE.match(table):
        raise ValueError(f"[gen_roster] 표 이름이 올바르지 않음(영문·숫자·_, 스키마.표만): {table!r}")
    rdb = pc.cfg().connections.rdb  # S7c — 설정 객체
    engine = rdb.engine  # blank keep: 옛 `get("RDB_ENGINE", "mssql")` — `RDB_ENGINE=`은 '' 유지
    cols_sql = ", ".join(f"[{c}]" if engine != "pg" else c for c in select_cols)
    if engine == "pg":
        from psycopg import sql as pgsql

        from common.store.pg import PG, conf

        db = PG(conf())
        ident = pgsql.SQL(".").join(pgsql.Identifier(p) for p in table.split("."))
        return db.q(pgsql.SQL("SELECT " + cols_sql + " FROM {}").format(ident))
    from common.store import mssql
    from pipeline.extract.source import rdb_connect  # S8b — SQLAlchemy 연결(접속 인자 옛 그대로 — RDB_CONNECT_KWARGS는 안 넘김)

    ident = ".".join(f"[{p}]" for p in table.split("."))
    with rdb_connect(extra_kwargs=False) as cn:
        return mssql.rows(cn, f"SELECT {cols_sql} FROM {ident}")


def build_roster(rows, mapping):
    """rows(dict 목록) + mapping(name·aliases 열) → {정식 이름: [별칭,...]}(결정적 — 이름 오름차순 dict), 같은
    이름의 여러 행은 별칭을 합침. 이름 없는 행은 건너뜀."""
    out = {}
    for r in rows:
        name = (r.get(mapping["name"]) or "").strip()
        if not name:
            continue
        al = []
        if mapping.get("aliases"):
            al = [x.strip() for x in re.split(r"[;|]", r.get(mapping["aliases"]) or "") if x.strip()]
        out[name] = sorted(set(out.get(name, [])) | set(al))
    return dict(sorted(out.items()))


def build_client_extra(rows, mapping):
    """GL3 — {정식 이름: {칸: 값}} for the optional roster columns the mapping names (first non-empty value wins
    when the master has several rows for one name)."""
    keys = [k for k in EXTRA_KEYS if mapping.get(k)]
    out = {}
    for r in rows:
        name = (r.get(mapping["name"]) or "").strip()
        if not name:
            continue
        d = out.setdefault(name, {})
        for k in keys:
            v = str(r.get(mapping[k]) or "").strip()
            if v and not d.get(k):
                d[k] = v
    return out


def write_client_roster(roster, out_path, extra=None, source=""):
    """CLIENT_ROSTER CSV in the new roster format (ROSTER_COLS — the same header as resources/vocab/glossary/client_roster.csv,
    aliases joined with |). extra = build_client_extra() result; source = where it came from (--source)."""
    extra = extra or {}
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ROSTER_COLS)
        for name, al in roster.items():
            row = {**extra.get(name, {}), "canonical_name": name, "aliases": "|".join(al), "source": source}
            w.writerow([row.get(c, "") for c in ROSTER_COLS])


def check_roster(path):
    """E15 — 서버에서 내보낸 CLIENT_ROSTER 파일 점검(적용 전에 사람이 돌림) → (오류 목록, 경고 목록, 고객 수).
    오류 = 적용하면 안 됨(읽기 실패·고객 0건) · 경고 = 적용은 되지만 확인할 것(cp949·같은 이름 여러 줄·무시될 짧은
    영문 별칭·여러 고객이 같이 쓰는 별칭·다른 고객의 정식 이름과 같은 별칭)."""
    errs, warns = [], []
    try:
        rows, enc = T._roster_rows(path)
    except Exception as e:  # 어떤 읽기 실패든 '적용 불가'로 보고
        return [f"읽기 실패: {type(e).__name__}: {e}"], [], 0
    if enc != "utf-8":
        warns.append(f"인코딩 {enc}로 읽음 — 읽히긴 하지만 UTF-8로 다시 저장 권장")
    roster = T.read_roster(path)
    if not roster:
        errs.append("고객 0건(머리글만 있거나 1열이 비어 있음)")
    names = [n for n, _ in rows]
    for n in sorted({n for n in names if names.count(n) > 1}):
        warns.append(f"같은 이름 {names.count(n)}줄 — 별칭 합쳐 1건으로: {n}")
    short = sorted({x for _, al in rows for x in al if T._SHORT_EN.fullmatch(x)})
    if short:
        warns.append(f"영문·숫자 3자 이하 별칭 {len(short)}개는 무시됨(부분 일치 오탐): {', '.join(short[:10])}")
    owners = {}
    for n, al in roster.items():
        for x in al:
            owners.setdefault(x.lower(), set()).add(n)
    for x, ns in sorted(owners.items()):
        if len(ns) > 1:
            warns.append(f"별칭 '{x}'를 고객 {len(ns)}곳이 같이 씀 — 어느 고객인지 못 가름: {', '.join(sorted(ns))}")
    lower_names = {n.lower(): n for n in roster}
    for x, ns in sorted(owners.items()):
        if x in lower_names and lower_names[x] not in ns:
            warns.append(f"별칭 '{x}'가 다른 고객의 정식 이름과 같음: {lower_names[x]} ↔ {', '.join(sorted(ns))}")
    return errs, warns, len(roster)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kind", choices=["client", "product"])
    ap.add_argument("--source", help="csv:<경로> 또는 rdb:<표>(서버 전용, RDB_ENGINE · 접속은 common.connections.rdb)")
    ap.add_argument("--mapping", help="매핑 JSON 경로({name, aliases?, category?})")
    ap.add_argument(
        "--out",
        help="--kind client — CLIENT_ROSTER CSV 출력 경로 · --kind product — draft CSV 출력 경로"
        "(GLOSSARY_DIR 아님, 독립 검토 BLOCK 1 — output/ 아래에 쓸 것)",
    )
    ap.add_argument("--check", metavar="CLIENT_ROSTER", help="E15 — 내보낸 고객 명부 파일 점검만(오류 있으면 종료 코드 1)")
    a = ap.parse_args(argv)
    if a.check:
        errs, warns, n = check_roster(a.check)
        print(f"[gen_roster] 고객 {n}건 · 오류 {len(errs)} · 경고 {len(warns)}", flush=True)
        for m in errs:
            print(f"  오류: {m}", flush=True)
        for m in warns:
            print(f"  경고: {m}", flush=True)
        return 1 if errs else 0
    if not (a.kind and a.source and a.mapping):
        ap.error("--kind·--source·--mapping 필요")
    mapping = load_mapping(a.mapping)
    if a.source.startswith("csv:"):
        rows = rows_from_csv(a.source[4:])
    elif a.source.startswith("rdb:"):
        needed = [mapping["name"]] + [mapping[k] for k in ("aliases", "category", *EXTRA_KEYS) if mapping.get(k)]
        rows = rows_from_rdb(a.source[4:], needed)
    else:
        raise ValueError(f"[gen_roster] --source는 csv:<경로> 또는 rdb:<표>만: {a.source!r}")
    roster = build_roster(rows, mapping)
    if a.kind == "client":
        if not a.out:
            ap.error("--kind client는 --out(CLIENT_ROSTER 경로) 필요")
        write_client_roster(roster, a.out, build_client_extra(rows, mapping), source=a.source)
        print(f"[gen_roster] CLIENT_ROSTER {len(roster)}건 → {a.out}", flush=True)
    else:
        if not a.out:
            ap.error("--kind product는 --out(draft CSV 경로) 필요")
        added = T.write_draft_terms(sorted(roster), a.out, category="product_example")
        print(f"[gen_roster] 제품 용어 draft {len(added)}건 추가(추출본 {len(roster)}건 중, 나머지는 이미 있던 이름) → {a.out}", flush=True)


if __name__ == "__main__":
    utf8_stdout()
    main()
