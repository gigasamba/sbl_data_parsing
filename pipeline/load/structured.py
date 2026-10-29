#!/usr/bin/env python3
"""로컬 정형 저장소(RDB) — 개발 PC·개발 서버에서 EDW 대신 계약 연결 검토(백로그 X1, 요건 S37 — W18 선행).
연결(저장소 자체) = common/structdb.py. 여기는 업무 로직만: EDW 형식 CSV 적재 + 문서↔계약 연결(linker).

연결 규칙(W18, 일반 규칙만 — 특정 데이터셋 문자열은 쓰지 않음):
  ⓪ doc_location(RDB 문서 위치 메타, AD45④)이 그 문서를 알면 **그게 우선값** — contract_id가 있으면 그 계약(확정),
     명시적으로 NULL(계약 없음 — RFI_ANSWER처럼 특정 계약에 안 묶이거나 실주)이면 아래 ①~③(본문 규칙)을 보지 않고 연결 안 함
     (V21 발견: 이걸 안 지켜 계약 무관 문서가 본문 일치만으로 잘못 연결됐었음). doc_location이 그 문서를 모르면(표가 비었거나
     옛 DB) 아래 본문 규칙 그대로.
  ① 문서에 계약 ID가 그대로 적혀 있으면 그 계약(가장 강한 근거, status=확정)
  ② '실주·타사 선정·미체결' 같은 표시가 있으면 연결하지 않음
  ③ 그 외에는 고객 별칭(common.core.terms 명부 + client_master.aliases)으로 후보 계약을 고르고
     제품 코드(공백·하이픈 등 구분자 무시 정규화, 예 'KST ADC-02' = 'KST-ADC-02') +3 · 제품 종류 +1 ·
     배치 수 +1 · 착수 시기(연월·분기·영문 월) +1 로 점수 — 합 CONFIRM_TH 이상이면 확정, 1 이상이면 후보(사람 확인), 0이면 연결 없음.

입력: EDW 형식 CSV(서버에서는 EDW 추출본) contract_master.csv · client_master.csv ·
      doc_location.csv(있을 때만 — AD45①·④, 열은 valid_env/unstructured/synth-meta-rdb·synth-edw doc_location.csv와 같음) ·
      문서 쪼갠 텍스트 = 구조화 묶음 docs.jsonl(full_text) 또는 파싱 인계 폴더 _rep/<문서>.json(text).

AD23 — 표 전 칸 DB 적재(doc_table·doc_cell, common/structdb.py TABLE_SCHEMA·ensure_table_schema()만 생성, load·link가
쓰는 ensure_schema()와는 분리 — AD16 BLOCK 이력과 같은 게이트): `tables --rep <_rep 폴더>`가 각 문서의
rep["tables_std"](modules/parse/post/table_std.py, PARSE_TABLE_STD 기본 켬)를 읽어 표 1개 = doc_table 1행 +
칸(머리글 포함)마다 doc_cell 1행으로 적재한다(값은 common.core.text.normalize_value로 정규화한 열도 함께 — 공백·대소문자
무시 조회용). 근거 MCP가 표 칸 질문에 쓸 조회는 `common/structdb.py`의 `find_table_cells()`·`find_table_row()`
(모듈 경계상 modules/load·modules/search 둘 다 쓸 수 있는 곳 — 여기선 호환용 재노출만) · 검색 쪽 라우팅은
`modules/search/aggregate.py`의 `table_cell_question()`·`table_cell_list()`(AD23 leftover).

명령:
  load --csv-dir <폴더> [--db <경로>]            contract_master·client_master 적재(같은 키는 덮어씀 — 재실행 안전)
  link (--bundle <묶음> | --rep <_rep 폴더>) [--db <경로>]   문서↔계약 연결 → doc_contract_link
  tables --rep <_rep 폴더> [--db <경로>]         AD23 — tables_std → doc_table·doc_cell(같은 table_key는 다시 지우고 적재 — 재실행 안전)
  --selftest                                     오프라인 임시 DB로 자체 검증(운영 DB 접근 없음)
"""

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]  # dev/
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.core.terms import _aliases, match_clients, modalities  # noqa: E402 — 고객 명부·모달리티(검색과 같은 규칙, DT1 c1: 용어집 modality_code 우선)
from common.core.text import normalize_value  # noqa: E402 — AD23 표 칸 값 정규화(검색·사실 추출과 같은 규칙, 기존 정규화 함수 재사용)
from common.store import structdb as SDB  # noqa: E402

CONTRACT_COLS = [
    "contract_id",
    "company",
    "company_id",
    "product_code",
    "modality",
    "site",
    "line_id",
    "batches_contracted",
    "contract_value_usd",
    "currency",
    "term_months",
    "signed_on",
    "start_date",
    "end_date",
    "status",
]
CLIENT_COLS = ["company_id", "company", "aliases"]
PROD_COLS = ["division", "prod_code", "prod_name", "pjt_name", "client_code"]
DOC_LOCATION_COLS = [
    "doc_id",
    "bucket",
    "object_key",
    "etag",
    "size_bytes",
    "content_type",
    "company_id",
    "doc_type",
    "contract_id",
    "version",
    "supersedes_doc_id",
    "language",
    "received_at",
    "updated_at",
    "is_deleted",
]  # AD45①·④ — valid_env/unstructured/synth-meta-rdb·synth-edw doc_location.csv와 같은 열
INT_COLS = {"batches_contracted", "contract_value_usd", "term_months", "size_bytes", "version", "is_deleted"}

EN_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
LOST_RE = re.compile(
    r"실주|타사\s*선정|미체결|계약\s*없음|lost\s+(the\s+)?deal|not\s+awarded|no\s+contract\b", re.I
)  # 업계 공통 표현(특정 샘플 문자열 아님)
CODE_W, MODALITY_W, BATCH_W, PERIOD_W = 3, 1, 1, 1
CONFIRM_TH, CANDIDATE_TH = 3, 1


def _norm_code(s):
    """제품 코드 비교용 — 공백·하이픈 등 구분자 무시(KST ADC-02 = KST-ADC-02). common.core.terms.norm은 공백만 지워 용도가 다름."""
    return re.sub(r"[^0-9a-z]", "", str(s or "").lower())


def _starts_mentioned(text, start):
    """계약 착수(연-월)가 본문에 언급됐는가 — 숫자 표기·한국어 'N년 M월'·분기·영문 월 이름."""
    if not start or len(start) < 7:
        return False
    y, m = int(start[:4]), int(start[5:7])
    q = (m - 1) // 3 + 1
    pats = [f"{y}-{m:02d}", f"{y}년 {m}월", f"{y}년{m}월", f"{y}.{m:02d}", f"{y} Q{q}", f"Q{q} {y}"]
    low = text.lower()
    if any(p.lower() in low for p in pats):
        return True
    return any(re.search(rf"{mon}\w*\s+{y}", low) for mon, i in EN_MON.items() if i == m)


def _modality_mentioned(text, modality):
    if not modality:
        return False
    names = {modality} | {k for k, v in modalities().items() if v == modality}
    return any(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text, re.I) for n in names)


def _match_written_id(text, contracts):
    """문서에 계약 ID가 그대로(exact substring) 적혀 있으면 그 계약 — 데이터셋 고유 정규식이 아니라 마스터에 있는 값으로 판정."""
    for c in contracts:
        if c.get("contract_id") and c["contract_id"] in text:
            return c
    return None


def _candidates(text, contracts, client_aliases):
    """고객 별칭이 문서에 나오는 계약들."""
    clients = {c["company"] for c in contracts if c.get("company")}
    hit = set(match_clients(text, clients, client_aliases))
    if not hit:
        return []
    return [c for c in contracts if c.get("company") in hit]


def _score(text, contract):
    norm_text = _norm_code(text)
    s = CODE_W * (bool(contract.get("product_code")) and _norm_code(contract["product_code"]) in norm_text)
    s += MODALITY_W * _modality_mentioned(text, contract.get("modality"))
    batches = contract.get("batches_contracted")
    if batches and re.search(rf"(?<!\d){batches}\s?(배치|batch)", text, re.I):
        s += BATCH_W
    if _starts_mentioned(text, contract.get("start_date")):
        s += PERIOD_W
    return s


def link_doc(text, contracts, client_aliases, loc=None):
    """→ (contract_id 또는 None, score, how, status 확정|후보|None).
    loc: doc_location 행(dict, doc_id로 찾은 것) 또는 None — AD45④ V21 발견 반영: RDB가 이 문서의 계약을 안다고
    적어 두면(loc, doc_location이 그 문서를 알고 있음) 그게 본문보다 **우선값**이다 — contract_id가 있으면 그 계약을
    그대로 확정(본문은 더 안 봄), **명시적으로 NULL(계약 없음 — RFI_ANSWER처럼 특정 계약에 안 묶이거나 실주)이면
    본문 별칭·제품·배치 일치로 후보 연결을 시도하지 않는다**(V21: 그래서 계약 무관 문서가 잘못 연결됐었음).
    loc이 None(그 문서가 doc_location에 없음 — manifest 자체가 없거나 이 문서는 모름)이면 지금 동작(본문 규칙) 그대로.
    독립 검토 MAJOR(10-07) — loc의 contract_id는 **contract_master에 있는지 검증**한 뒤에만 '확정': 오타·삭제 등으로
    계약 마스터에 없는 ID면 '후보'로 강등(이유 기록) — RDB가 적어 둔 값이라도 존재 검증 없이 확정하지 않음."""
    if loc is not None:
        cid = loc.get("contract_id")
        if not cid:
            return None, 0, "RDB: 계약 없음(명시)", None
        if any(c.get("contract_id") == cid for c in contracts):
            return cid, CONFIRM_TH, SDB.HOW_RDB_LOCATION, "확정"
        return cid, CANDIDATE_TH, SDB.HOW_RDB_LOCATION + "(계약 마스터에 없음 — 오타·삭제 가능, 미검증)", "후보"
    if LOST_RE.search(text):
        return None, 0, "실주·미체결 표시", None
    hit = _match_written_id(text, contracts)
    if hit:
        return hit["contract_id"], CONFIRM_TH, SDB.HOW_ID_WRITTEN, "확정"
    cands = _candidates(text, contracts, client_aliases)
    if not cands:
        return None, 0, "고객 없음", None
    scored = {c["contract_id"]: _score(text, c) for c in cands}
    best_id = max(scored, key=scored.get)
    best = scored[best_id]
    if best < CANDIDATE_TH:
        return None, 0, "근거 부족", None
    status = "확정" if best >= CONFIRM_TH else "후보"
    return best_id, best, "별칭+제품코드+규모+시기", status


def _doc_locations(db):
    """doc_id(파일 stem) → doc_location 행 — 적재 안 했으면(표가 비었거나 옛 DB라 표 자체가 없으면) 빈 dict(AD45④, 기존 동작 그대로)."""
    try:
        return {r["doc_id"]: r for r in db.query("SELECT doc_id, contract_id FROM doc_location")}
    except Exception:
        return {}


def _client_aliases(db):
    """고객 명부 = common.core.terms 명부(stack.json·CLIENT_ROSTER·GLOSSARY_DIR) + client_master.aliases(합침)."""
    out = _aliases()
    for r in db.query("SELECT company, aliases FROM client_master"):
        al = [a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()]
        if al:
            out[r["company"]] = sorted(set(out.get(r["company"], [])) | set(al))
    return out


# ── 적재 ──────────────────────────────────────────────────────────
def load_csv(db, csv_dir):
    """EDW 형식 CSV(contract_master.csv · client_master.csv, '_synthetic' 열은 버림) → 적재(같은 키는 덮어씀).
    doc_location.csv(AD45①·④, RDB 문서 위치 메타)는 있을 때만 적재 — 없으면 건너뜀(out에 키 자체가 없음, 기존 호출자 불변)."""
    d = Path(csv_dir)
    out = {}
    for table, cols in (
        ("contract_master", CONTRACT_COLS),
        ("client_master", CLIENT_COLS),
        ("prod_master", PROD_COLS),
        ("doc_location", DOC_LOCATION_COLS),
    ):
        f = d / f"{table}.csv"
        if not f.exists():
            continue
        with f.open(encoding="utf-8-sig") as fh:
            rows = []
            for r in csv.DictReader(fh):
                row = {k: r.get(k) for k in cols}
                for k in INT_COLS & set(cols):
                    row[k] = int(row[k]) if row.get(k) not in (None, "") else None
                rows.append(row)
        placeholders = ",".join("?" * len(cols))
        db.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})", [tuple(r[k] for k in cols) for r in rows]
        )
        out[table] = len(rows)
    db.commit()
    return out


# ── 문서 읽기(묶음 또는 파싱 인계 폴더) ─────────────────────────────
def _jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(p).exists() else []


def docs_from_bundle(bundle_dir):
    """구조화 묶음 docs.jsonl → [{doc_key, text, file_name}]."""
    return [
        {"doc_key": d.get("file_sha256"), "text": d.get("full_text") or "", "file_name": d.get("file_name")}
        for d in _jl(Path(bundle_dir) / "docs.jsonl")
    ]


def docs_from_rep(rep_dir):
    """파싱 인계 폴더 _rep/<문서>.json → [{doc_key, text, file_name, tables_std}](구조화 전에도 연결·표 적재 가능).
    tables_std(AD23)는 top-level 칸(modules/parse/represent.py가 `rep["tables_std"] = ...`로 둠) — 없으면 빈 목록."""
    out = []
    for f in sorted(Path(rep_dir).glob("*.json")):
        if f.name == "index.json":
            continue
        j = json.loads(f.read_text(encoding="utf-8"))
        src = (j.get("rep") or {}).get("source") or {}
        out.append(
            {
                "doc_key": src.get("doc_key") or f.stem,
                "text": j.get("text") or "",
                "file_name": f.stem,
                "tables_std": j.get("tables_std") or [],
            }
        )
    return out


# ── AD23: tables_std → doc_table·doc_cell ──────────────────────────
def load_tables_docs(db, docs):
    """tables_std(rep.tables_std, table_std.build_tables 형식: id·page·source_engine·header·rows·merged)를
    doc_table 1행(표마다) + doc_cell(머리글 포함, 칸마다) 행으로 적재한다. db는 SDB.ensure_table_schema(db)가
    이미 돈 연결(이 함수는 게이트를 안 침 — AD16 BLOCK과 같은 이유로 _main_cmd의 `tables` 명령에서만 호출).
    재실행 안전: 같은 table_key(doc_key:표id)의 doc_cell을 먼저 지우고 다시 쓴다(doc_table은 INSERT OR REPLACE).
    칸 값은 common.core.text.normalize_value로 정규화한 열(value_norm)도 같이 넣어 공백·대소문자 무시 조회가 되게 한다."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    n_tables = n_cells = 0
    for d in docs:
        for t in d.get("tables_std") or []:
            table_key = f"{d['doc_key']}:{t['id']}"
            header, rows = t.get("header") or [], t.get("rows") or []
            db.execute("DELETE FROM doc_cell WHERE table_key=?", (table_key,))
            db.execute(
                "INSERT OR REPLACE INTO doc_table "
                "(table_key, doc_key, table_id, page, source_engine, n_rows, n_cols, header_json, merged_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    table_key,
                    d["doc_key"],
                    t["id"],
                    t.get("page"),
                    t.get("source_engine"),
                    len(rows),
                    len(header),
                    json.dumps(header, ensure_ascii=False),
                    json.dumps(t.get("merged") or [], ensure_ascii=False),
                    now,
                ),
            )
            cells = [(table_key, 0, ci, h, h, normalize_value(h)) for ci, h in enumerate(header)]
            for ri, row in enumerate(rows, start=1):
                for ci, v in enumerate(row):
                    label = header[ci] if ci < len(header) else None
                    cells.append((table_key, ri, ci, label, v, normalize_value(v)))
            db.executemany("INSERT INTO doc_cell (table_key, row_idx, col_idx, col_label, value, value_norm) VALUES (?,?,?,?,?,?)", cells)
            n_tables += 1
            n_cells += len(cells)
    db.commit()
    return {"tables": n_tables, "cells": n_cells}


# AD23 leftover — find_table_cells()는 모듈 경계상 modules/search(aggregate.py)도 써야 해서 common/structdb.py로
# 옮겼다(적재·집계 둘 다 common만 보는 기존 구조, ①모듈 경계). 여기서는 호환용 재노출만.
find_table_cells = SDB.find_table_cells


def link_docs(db, docs):
    """문서 목록 → doc_contract_link 적재(연결 없는 문서는 쓰지 않음 — 실주·근거 부족·RDB 계약 없음 명시).
    doc_location이 그 문서(파일 stem)를 알면(AD45④) 그 contract_id를 본문 규칙보다 먼저 쓴다.
    # ponytail: evidence_chunk_keys는 지금 문서 단위라 비워 둠 — 청크 단위 근거는 검색(mcp search)이 doc_key로 보강, 필요해지면 chunks.jsonl을 함께 읽어 채움."""
    contracts = db.query("SELECT * FROM contract_master")
    aliases = _client_aliases(db)
    locs = _doc_locations(db)
    now = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for d in docs:
        loc = locs.get(Path(d.get("file_name") or "").stem)
        cid, score, how, status = link_doc(d["text"], contracts, aliases, loc)
        if cid:
            rows.append((d["doc_key"], cid, score, how, status, json.dumps([]), now))
    db.executemany(
        "INSERT OR REPLACE INTO doc_contract_link "
        "(doc_key, contract_id, score, how, status, evidence_chunk_keys, created_at) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    db.commit()
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["load", "link", "tables"])
    ap.add_argument("--csv-dir")
    ap.add_argument("--bundle")
    ap.add_argument("--rep")
    ap.add_argument("--db")
    a = ap.parse_args(argv)
    try:
        _main_cmd(a)
    except SDB.StructDBError as e:  # CLI만 종료 코드로 바꿈 — 서버(mcp_server)는 StructDBError를 직접 잡아 처리(X1b 리뷰)
        raise SystemExit(f"정형 저장소 연결 실패: {e}") from e


def _open(path):
    """S8a — 쓰기 전 struct 판 확인(PostgreSQL만 — 판 기록 없음은 경고 뒤 계속, 낮거나 모르는 판은 StructDBError)."""
    from common.store.db import dbtool

    db = SDB.open_backend(path)
    try:
        return dbtool.require_struct(db)
    except BaseException:
        db.close()  # 판 거부 때 연결을 닫고 끝냄(VS8a R-8)
        raise


def _main_cmd(a):
    if a.cmd == "load":
        if not a.csv_dir:
            raise SystemExit("--csv-dir 필요")
        db = _open(a.db)
        SDB.ensure_schema(db)
        out = load_csv(db, a.csv_dir)
        if db.notes:
            out = {**out, "notes": db.notes}
        print(json.dumps(out, ensure_ascii=False))
        db.close()
    elif a.cmd == "link":
        if not (a.bundle or a.rep):
            raise SystemExit("--bundle 또는 --rep 필요")
        db = _open(a.db)
        SDB.ensure_schema(db)
        docs = docs_from_bundle(a.bundle) if a.bundle else docs_from_rep(a.rep)
        rows = link_docs(db, docs)
        out = {"docs": len(docs), "linked": len(rows)}
        if db.notes:
            out["notes"] = db.notes
        print(json.dumps(out, ensure_ascii=False))
        db.close()
    elif a.cmd == "tables":
        if not a.rep:
            raise SystemExit("--rep 필요")
        db = _open(a.db)
        SDB.ensure_table_schema(db)  # AD23 — load·link의 ensure_schema()와 분리된 게이트(AD16 BLOCK 이력)
        out = load_tables_docs(db, docs_from_rep(a.rep))
        if db.notes:
            out = {**out, "notes": db.notes}
        print(json.dumps(out, ensure_ascii=False))
        db.close()
    else:
        raise SystemExit("cmd 필요: load|link|tables")


if __name__ == "__main__":
    utf8_stdout()
    main()
