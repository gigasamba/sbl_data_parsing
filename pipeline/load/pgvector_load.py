#!/usr/bin/env python3
"""개발 서버 PostgreSQL + pgvector 저장소 — 대표 파싱·청크·벡터·그래프를 EDW 대신 개발 서버에서 관리.

PostgreSQL은 Docker로(이미지 = dev_server_pgvector 브랜치의 pgvector/pgvector:pg16 → docker load, 띄우기: valid_env/docker/compose.pg.yml — PC·단독 시험 전용, S6b).
접속: PG_CONN_FILE=<KEY=VALUE 파일> 또는 환경변수 PG_HOST(127.0.0.1) · PG_PORT(5432) · PG_DB(rag) · PG_USER(rag) · PG_PASSWORD · PG_SCHEMA(ai)
드라이버: psycopg 3(반입 휠 assets/wheels/psycopg*) — 비밀번호는 파일·환경변수에만.

명령: check · deploy · load(묶음 → 한 트랜잭션, 같은 문서 건너뜀, --replace) — 검색은 modules/search/pgsearch.py
load는 더하고 고치기만 한다 — 이번 묶음에 없는 문서를 지우지 않는다(pl-13, 사용자 10-29: 원천에서 지운 문서·파싱 실패는 로컬 기록만).
S8a — deploy는 확인(vector 확장·남의 스키마·차원) 뒤 migrate(common.store.db.dbtool up --target search — Alembic 기준판)를 부른다.
load는 판 기록을 먼저 본다(없으면 경고 뒤 계속, 끝보다 낮거나 모르는 판이면 종료 2).
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.core.contract import jl  # noqa: E402 — 묶음 읽기
from common.core.text import index_text, tokens  # noqa: E402 — 색인·토큰 규칙(모듈 계약)
from common.store.pg import HNSW_MAX, PG, conf, has_conn, vec  # noqa: E402,F401
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)
from pipeline.load.pg_load_connect import connect as pg_connect  # noqa: E402

# DROP/TRUNCATE/DELETE 대상 식별자 화이트리스트(XS3) — 우리 스키마의 우리 표만. 스키마명 자체는 common/pg.conf()가 이미 정규식으로 검증.
_OUR_TABLES = {"load_run", "doc", "chunk", "chunk_term", "term_stat", "corpus_stat"}  # 2026-10-20 축소 — 검색(chunk+BM25)에 필요한 표만


def _tbl(s, name):
    if name not in _OUR_TABLES:
        raise SystemExit(f"허용 안 된 표(화이트리스트 밖): {name}")
    return f"{s}.{name}"


def _has_marker(db):
    """스키마에 우리 load_run 표(deploy가 만듦)가 있는지."""
    return bool(db.q("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name='load_run'", (db.schema,)))


def _require_marked_schema(db):
    """--replace는 우리가 만든 스키마(load_run 표가 있음)에서만(XS3) — 표식 없는 기존 스키마는 남의 것일 수 있어 거부."""
    if not _has_marker(db):
        raise SystemExit(
            f"--replace 거부: 스키마 {db.schema}에 우리 표식(load_run)이 없음 — "
            "남의 기존 스키마일 수 있음(deploy로 먼저 만들거나 다른 PG_SCHEMA 사용)"
        )


def _upgrade(schema, dim):
    """검색 스키마 판 올리기(S8a — migrate up). selftest가 가짜로 바꿔 끼운다."""
    from common.store.db import dbtool

    dbtool.upgrade("search", schema, dim)


def deploy(db, dim):
    """S8a(5-4, 사용자 10-28 Q4 a) — 표·색인·뷰는 migrate(Alembic 기준판 — 옛 schema.sql + 이 함수의 색인 DDL 글자 그대로)가 만든다.
    확인(vector 확장 — PG_CREATE_EXTENSION 옵트인·남의 스키마 거부·차원)과 backfill은 전처럼. SQLite 대역(pg_standin)은 판 관리 밖 —
    표 정의에서 만든 DDL로(HNSW·GIN 색인은 대역이 흉내 내지 않음). 실측(30k×4096, 개발 PC): 정확 180~220 ms · 이진 양자화 HNSW+재정렬
    5~7 ms(색인 24 MB, 생성 6.6 s)."""
    from common.store.db import dbtool

    dbtool.precheck_search(db.q, db.schema, dim, pc.cfg().load.pg_create_extension)  # S7c — 설정 객체 · 옵트인은 PC·단독 시험만
    standin = getattr(db, "is_standin", False)
    kind = dbtool.index_kind(dim)
    if standin:
        with db.cn.cursor() as cur:
            cur.execute(dbtool.standin_script(db.schema, int(dim)))
        dbtool.check_dim(db.q, db.schema, dim)  # 대역 파일이 옛 차원으로 남아 있을 때(PG는 판 올리기 전 precheck가 봄)
    elif dbtool.status(db.q, "search", db.schema)[0] == "없음" and dbtool.has_tables(db.q, db.schema):
        # 판 기록 없는 기존 스키마(옛 코드가 만든 DB — stamp 전): DDL·비교 없이 경고 뒤 계속(Q5를 적재 앞 자동 길에도 — 코디네이터 10-28 a).
        # Q3 비교·거부는 사람이 돌리는 migrate up|stamp에서만. 옛 deploy가 IF NOT EXISTS로 빠진 표·색인을 채우던 것은 없음(check가 보임)
        dbtool.require_current(db.q, "search", db.schema)
        kind += "(확인 안 함 — 판 기록 없는 기존 스키마: migrate check)"  # 색인을 만들지도 보지도 않음(VS8a R-7)
    else:
        _upgrade(db.schema, int(dim))  # 새 스키마 = 만들고 판 기록 · 판 기록 있음 = 끝까지(끝이면 그대로, 모르는 판은 거부)
    # 10-15 urgent — one-time backfill of rows loaded before chunk.clients existed (no re-load needed)
    if not standin:
        backfill_chunk_clients(db)
    return kind


def _doc_row_clients(clients):
    """doc.clients (JSON TEXT) -> label list, [] = unknown. Bad JSON never raises — 94 review: one broken row must not fail
    deploy(). pl-14 — the 10-20 reduced doc table has no client column, so there is no single-label fallback any more."""
    try:
        v = json.loads(clients or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in v if x] if isinstance(v, list) else []


def backfill_chunk_clients(db):
    """Fill chunk.clients for rows loaded before the column existed — in ONE transaction, parsed in Python (no SQL JSON cast
    that one bad row could abort). Idempotent: only rows with clients IS NULL. Search keeps the old (correct) path while any
    NULL remains (pgsearch._has_chunk_clients), so a half-done or failed backfill never makes strict queries return empty."""
    s = db.schema
    rows = db.q(f"SELECT DISTINCT d.doc_id, d.clients FROM {s}.doc d JOIN {s}.chunk c ON c.doc_id = d.doc_id WHERE c.clients IS NULL")
    if not rows:
        return 0
    for i in range(0, len(rows), 200):  # 94 review — commit every 200 docs (short row locks; partial progress is safe, NULL-gated)
        with db.cn.transaction(), db.cn.cursor() as cur:
            for r in rows[i : i + 200]:
                cur.execute(
                    f"UPDATE {s}.chunk SET clients = %s WHERE doc_id = %s AND clients IS NULL",
                    (_doc_row_clients(r["clients"]), r["doc_id"]),
                )
    return len(rows)


def _chunk_clients(d, standin=False):
    """10-15 — the doc's client labels for chunk.clients: doc clients list (strongest first) or the single client, [] = unknown.
    PostgreSQL gets a list (text[]); the SQLite stand-in gets JSON text (no arrays there)."""
    names = [n for n in (d.get("clients") or ([d["client"]] if d.get("client") else [])) if n]
    return json.dumps(names, ensure_ascii=False) if standin else names


def _nonul(o):
    """PostgreSQL 텍스트는 NUL(0x00)을 못 받음 — 깨진 PDF·OCR 본문에 섞여 오면 적재 전체가 멈추므로 지움."""
    if isinstance(o, str):
        return o.replace("\x00", "")
    if isinstance(o, list):
        return [_nonul(x) for x in o]
    if isinstance(o, dict):
        return {k: _nonul(v) for k, v in o.items()}
    return o


def drop_terms(cur, s, doc_ids):
    """문서들의 키워드 색인을 지우며 문서 빈도(term_stat)에서도 뺌 — 적재마다 전체 다시 세지 않게(T4)."""
    cur.execute(
        f"""UPDATE {_tbl(s, "term_stat")} t SET df = t.df - d.n FROM (SELECT term, COUNT(*) n FROM {_tbl(s, "chunk_term")}
                    WHERE chunk_id IN (SELECT chunk_id FROM {s}.chunk WHERE doc_id = ANY(%s)) GROUP BY term) d WHERE t.term = d.term""",
        (doc_ids,),
    )
    cur.execute(
        f"DELETE FROM {_tbl(s, 'chunk_term')} WHERE chunk_id IN (SELECT chunk_id FROM {s}.chunk WHERE doc_id = ANY(%s))", (doc_ids,)
    )
    cur.execute(f"DELETE FROM {_tbl(s, 'term_stat')} WHERE df <= 0")


def load(db, bundle, replace=False):
    """묶음 → 한 트랜잭션. 저장된 문서(file_path 같음)는 건너뜀(replace면 지우고 다시 넣음 — 고치기). 묶음에 없는 저장 문서는 그대로 둠(pl-13)."""
    if replace:
        _require_marked_schema(db)  # XS3 — 남의 기존 스키마에 --replace 금지
    import numpy as np

    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    docs, chunks = _nonul(jl(B / "docs.jsonl")), _nonul(jl(B / "chunks.jsonl"))
    vecs = np.load(B / "vectors.npy", mmap_mode="r")  # 필요한 청크만 읽음(전체를 메모리에 올리지 않음)
    s, t0 = db.schema, time.time()
    with db.cn.transaction(), db.cn.cursor() as cur:  # 한 트랜잭션 — 실패하면 전부 되돌림
        cur.execute(f"INSERT INTO {s}.load_run(params) VALUES (%s) RETURNING run_id", (json.dumps(meta, ensure_ascii=False),))
        run = cur.fetchone()[0]
        cur.execute(f"SELECT file_path, doc_id FROM {s}.doc")
        have = {r[0]: r[1] for r in cur.fetchall()}
        doc_id = {}
        for i, d in enumerate(docs):
            old = have.get(d["file_path"])
            if old and not replace:
                continue
            if old:
                drop_terms(cur, s, [old])
                cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id=%s", (old,))  # chunk는 ON DELETE CASCADE
            # 2026-10-20 축소 스키마 — 검색에 필요한 최소 컬럼만 (file_name은 뷰에서 file_path 유도)
            cur.execute(
                f"""INSERT INTO {s}.doc(file_path, summary, clients, run_id, source_system,
                            sf_acc_name, sf_op_id, sf_op_name, project_code__c,
                            contract_id, contract_date, prod_name, division, service_type)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING doc_id""",
                (
                    d["file_path"],
                    d.get("summary"),
                    json.dumps(d["clients"], ensure_ascii=False) if d.get("clients") else None,
                    run,
                    d.get("source_system"),
                    d.get("sf_acc_name"),
                    d.get("sf_op_id"),
                    d.get("sf_op_name"),
                    d.get("project_code__c"),
                    d.get("contract_id"),
                    d.get("contract_date"),
                    d.get("prod_name"),
                    d.get("division"),
                    d.get("service_type"),
                ),
            )
            doc_id[i] = cur.fetchone()[0]
        sel = [ci for ci, c in enumerate(chunks) if c["doc"] in doc_id]
        ci_db = {}
        doc_cl = {i: _chunk_clients(docs[i], getattr(db, "is_standin", False)) for i in doc_id}  # chunks.jsonl "doc" = docs.jsonl 줄 번호
        for ci in sel:
            c = chunks[ci]
            cur.execute(
                f"""INSERT INTO {s}.chunk(doc_id, seq, page, line_start, line_end, char_start, char_end, bbox, section, chunk_text,
                            n_chars, n_terms, embed_model, embedding, clients, source_system) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s) RETURNING chunk_id""",
                (
                    doc_id[c["doc"]],
                    c["seq"],
                    c["page"],
                    c["line_start"],
                    c["line_end"],
                    c["char_start"],
                    c["char_end"],
                    c["bbox"],
                    c["section"],
                    c["chunk_text"],
                    c["n_chars"],
                    c["n_terms"],
                    meta.get("embed_model"),
                    vec(vecs[ci]),
                    doc_cl[c["doc"]],
                    c.get("source_system"),
                ),
            )
            ci_db[ci] = cur.fetchone()[0]
        # 2026-10-20 축소 — doc_fact·doc_image·chunk_image·concept_chunk·kg_node·kg_edge는 더 이상 적재하지 않음(테이블 삭제됨)
        # 2026-10-22 사용자 지정 — BM25 항목(term,tf) 계산 문서당 BM25_THREADS(기본 4) 병렬 선처리, COPY는 그대로 단일 트랜잭션
        bthreads = max(1, int(pc.cfg().load.bm25_threads))
        sel_terms = {}
        if bthreads > 1 and len(sel) > 1:
            from concurrent.futures import ThreadPoolExecutor

            _tk = [ci for ci in sel]

            def _toks(ci):
                return ci, Counter(tokens(index_text(chunks[ci]))).items()

            with ThreadPoolExecutor(max_workers=bthreads) as ex:
                for ci, items in ex.map(_toks, _tk):
                    sel_terms[ci] = items
        with cur.copy(f"COPY {s}.chunk_term(term, chunk_id, tf) FROM STDIN") as cp:  # 키워드 색인 — 대량은 COPY
            n_terms = 0
            for ci in sel:
                for term, tf in (
                    sel_terms.get(ci) or Counter(tokens(index_text(chunks[ci]))).items()
                ):  # 머리말 포함(G9) — 규칙은 common.core.text
                    cp.write_row((term, ci_db[ci], min(tf, 32767)))
                    n_terms += 1
        # 문서 빈도: 새 청크 단어만 더함(지운 문서는 drop_terms에서 뺌). 비었으면 전체 다시 셈(BM25_STAT_REBUILD는 op-08에 지움)
        cur.execute(f"SELECT NOT EXISTS (SELECT 1 FROM {s}.term_stat)")
        if cur.fetchone()[0]:
            cur.execute(f"DELETE FROM {_tbl(s, 'term_stat')}")
            cur.execute(f"INSERT INTO {s}.term_stat SELECT term, COUNT(*) FROM {s}.chunk_term GROUP BY term")
        elif ci_db:
            cur.execute(
                f"""INSERT INTO {s}.term_stat SELECT term, COUNT(*) FROM {s}.chunk_term WHERE chunk_id = ANY(%s) GROUP BY term
                            ON CONFLICT (term) DO UPDATE SET df = {s}.term_stat.df + EXCLUDED.df""",
                (list(ci_db.values()),),
            )
        cur.execute(
            f"""INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len, dim) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0), %s FROM {s}.chunk
                        ON CONFLICT (id) DO UPDATE SET n_chunks = EXCLUDED.n_chunks, avg_len = EXCLUDED.avg_len, dim = EXCLUDED.dim""",
            (meta["dim"],),
        )
        counts = {"docs": len(doc_id), "chunks": len(sel), "terms": n_terms, "sec": round(time.time() - t0, 1)}
        cur.execute(f"UPDATE {s}.load_run SET finished_at = now(), counts = %s WHERE run_id = %s", (json.dumps(counts), run))
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "deploy", "load"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    db = pg_connect()
    print(
        f"[pgstore] 모드: {'실 PG(연결 정보 있음)' if has_conn() else '스탠드인(sqlite, 연결 정보 없음 — AD41)'} · 스키마 {db.schema}",
        file=sys.stderr,
        flush=True,
    )
    if a.cmd == "check":
        print(
            json.dumps(
                db.q("""SELECT version() AS pg, (SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector,
                                 (SELECT COUNT(*) FROM pg_available_extensions WHERE name='vector') AS vector_available, current_user AS usr"""),
                ensure_ascii=False,
                indent=1,
                default=str,
            )
        )
        return
    meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
    if a.cmd == "deploy":
        idx = deploy(db, meta["dim"])
        print(f"배포 완료: PostgreSQL 스키마 {db.schema} · vector({meta['dim']}) · {idx} 색인")
    elif a.cmd == "load":
        if not getattr(db, "is_standin", False):  # S8a(Q5) — 판 기록 없음은 경고 뒤 계속, 끝보다 낮거나 모르는 판은 거부(종료 2)
            from common.store.db import dbtool

            dbtool.require_current(db.q, "search", db.schema)
        print(json.dumps(load(db, a.bundle, a.replace), ensure_ascii=False))


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py 적재가 BM25_THREADS를 넘김)
    utf8_stdout()
    main()
