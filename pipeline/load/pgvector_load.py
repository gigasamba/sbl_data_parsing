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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.contract import jl  # 묶음 읽기
from common.core.text import index_text, tokens  # 색인·토큰 규칙(모듈 계약)
from common.store.pg import HNSW_MAX, PG, conf, has_conn, vec  # noqa: F401
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.load.pg_load_connect import connect as pg_connect

# DROP/TRUNCATE/DELETE 대상 식별자 화이트리스트(XS3) — 우리 스키마의 우리 표만. 스키마명 자체는 common/pg.conf()가 이미 정규식으로 검증.
_OUR_TABLES = {"doc", "chunk", "chunk_term", "term_stat", "corpus_stat"}  # 원천 스키마마다 같은 표(pl-28 — load_run은 11-02에 지움)


def _tbl(s, name):
    if name not in _OUR_TABLES:
        raise SystemExit(f"허용 안 된 표(화이트리스트 밖): {name}")
    return f"{s}.{name}"


def _has_marker(db):
    """기준 스키마에 우리 판 표(alembic_version — deploy·migrate가 만듦)가 있는지(11-02 — load_run 표식을 대신)."""
    return bool(db.q("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name='alembic_version'", (db.schema,)))


def _require_marked_schema(db):
    """--replace는 우리가 만든 스키마(판 표가 있음)에서만(XS3) — 표식 없는 기존 스키마는 남의 것일 수 있어 거부."""
    if not _has_marker(db):
        raise SystemExit(
            f"--replace 거부: 스키마 {db.schema}에 우리 표식(판 표 alembic_version)이 없음 — "
            "남의 기존 스키마일 수 있음(deploy로 먼저 만들거나 다른 PG_SCHEMA 사용 · 판 기록 전 옛 우리 스키마면 migrate stamp)"
        )


class _Src:
    """기준 연결 하나로 원천 스키마 하나를 가리킴(실 PG — 한 연결·한 트랜잭션으로 5벌 모두에 쓴다). q·cn은 기준 연결 그대로."""

    def __init__(self, db, schema):
        self.db, self.schema = db, schema
        self.cn, self.q = db.cn, db.q


def src_dbs(db):
    """원천 이름 → 그 원천 스키마를 가리키는 연결(pl-28). SQLite 대역은 스키마마다 파일 하나라 원천마다 대역을 따로 연다."""
    from common.store.db.models import search_tables as ST

    if getattr(db, "is_standin", False):
        from common.store.pg_standin import StandinPG

        return {src: StandinPG(ST.src_schema(db.schema, src)) for src in ST.SOURCES}
    return {src: _Src(db, ST.src_schema(db.schema, src)) for src in ST.SOURCES}


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
    if standin:  # 원천 스키마마다 대역 파일 하나(pl-28)
        for sdb in src_dbs(db).values():
            with sdb.cn.cursor() as cur:
                cur.execute(dbtool.standin_script(sdb.schema, int(dim)))
            dbtool.check_dim(sdb.q, sdb.schema, dim)  # 대역 파일이 옛 차원으로 남아 있을 때(PG는 판 올리기 전 precheck가 봄)
    elif dbtool.status(db.q, "search", db.schema)[0] == "없음" and dbtool.has_tables(db.q, db.schema):
        # 판 기록 없는 기존 스키마(옛 코드가 만든 DB — stamp 전): DDL·비교 없이 경고 뒤 계속(Q5를 적재 앞 자동 길에도 — 코디네이터 10-28 a).
        # Q3 비교·거부는 사람이 돌리는 migrate up|stamp에서만. 옛 deploy가 IF NOT EXISTS로 빠진 표·색인을 채우던 것은 없음(check가 보임)
        dbtool.require_current(db.q, "search", db.schema)
        kind += "(확인 안 함 — 판 기록 없는 기존 스키마: migrate check)"  # 색인을 만들지도 보지도 않음(VS8a R-7)
    else:
        _upgrade(db.schema, int(dim))  # 새 스키마 = 만들고 판 기록 · 판 기록 있음 = 끝까지(끝이면 그대로, 모르는 판은 거부)
    return kind


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


def _kst(v):
    """원천 등록 시각 글자 → 시간대 붙은 ISO 글자(시간대 없는 값은 KST — FileStorageMap 값, 운영 계약). 비었거나 형식이 틀리면 None(적재는 계속)."""
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).strip())
    except ValueError:
        print(f"[pgstore] created_at 형식이 아님 — 비워 둠: {v!r}", flush=True)
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone(timedelta(hours=9)))).isoformat()


def load(db, bundle, replace=False):
    """묶음 → 원천 스키마별로(pl-28 — 문서의 source_system으로 고름: SFDC·CRMS·LAS·FAQ, 그 밖은 other) 적재. 실 PG는 기준 연결 한 트랜잭션
    (실패하면 5벌 모두 되돌림), 대역은 원천마다 따로. 저장된 문서(file_path 같음)는 건너뜀(replace면 지우고 다시 넣음 — 고치기). 묶음에 없는
    저장 문서는 그대로 둠(pl-13). 실행 정보(묶음 meta·건수·시간)는 실행 기록에 남긴다(load_run 표는 11-02에 지움). 적재가 끝나면(커밋 뒤)
    ParsingMeta.loaded_at을 적는다(C10 예외 — 실패해도 적재는 그대로, 경고와 건수만)."""
    from common.store.db.models import search_tables as ST

    if replace:
        _require_marked_schema(db)  # XS3 — 남의 기존 스키마에 --replace 금지
    import numpy as np

    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    docs, chunks = _nonul(jl(B / "docs.jsonl")), _nonul(jl(B / "chunks.jsonl"))
    vecs = np.load(B / "vectors.npy", mmap_mode="r")  # 필요한 청크만 읽음(전체를 메모리에 올리지 않음)
    t0 = time.time()
    by_src = {}
    for i, d in enumerate(docs):
        by_src.setdefault(ST.source_of(d.get("source_system")), []).append(i)
    dbs = src_dbs(db)
    counts = {"docs": 0, "chunks": 0, "terms": 0, "by_source": {}}
    loaded = []
    if getattr(db, "is_standin", False):
        for src, idx in by_src.items():
            sdb = dbs[src]
            with sdb.cn.transaction(), sdb.cn.cursor() as cur:
                c, ld = _load_src(cur, sdb.schema, src, docs, idx, chunks, vecs, meta, replace)
            _add(counts, src, c)
            loaded += ld
    else:
        with db.cn.transaction(), db.cn.cursor() as cur:  # 한 트랜잭션 — 실패하면 5벌 모두 되돌림
            for src, idx in by_src.items():
                c, ld = _load_src(cur, dbs[src].schema, src, docs, idx, chunks, vecs, meta, replace)
                _add(counts, src, c)
                loaded += ld
    counts["sec"] = round(time.time() - t0, 1)
    counts["loaded_at_failed"] = _mark_loaded(loaded)
    from common.core import runlog

    runlog.note(f"적재 {json.dumps({'bundle': str(B), 'meta': meta, 'counts': counts}, ensure_ascii=False, default=str)}")
    return counts


def _add(counts, src, c):
    for k in ("docs", "chunks", "terms"):
        counts[k] += c[k]
    counts["by_source"][src] = c


def _load_src(cur, s, src, docs, idx, chunks, vecs, meta, replace):
    """원천 스키마 s 하나에 문서 idx(docs.jsonl 줄 번호)를 적재 — 반환 (건수, [(source_system, file_path) — 새로 넣은 문서])."""
    from common.store.db.models import search_tables as ST

    cols = ST.doc_columns(src)[1:]  # doc_id 빼고
    chunk_extra = [n for n, _ in ST.CHUNK_EXTRA.get(src, ())]
    cur.execute(f"SELECT file_path, doc_id FROM {s}.doc")
    have = {r[0]: r[1] for r in cur.fetchall()}
    doc_id, loaded = {}, []
    for i in idx:
        d = docs[i]
        old = have.get(d["file_path"])
        if old and not replace:
            continue
        if old:
            drop_terms(cur, s, [old])
            cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id=%s", (old,))  # chunk는 ON DELETE CASCADE
        row = {
            **{c: d.get(c) for c in cols},
            "created_at": _kst(d.get("created_at")),
            "clients_doc": json.dumps(d["clients"], ensure_ascii=False) if d.get("clients") else None,
        }
        cur.execute(
            f"INSERT INTO {s}.doc({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING doc_id",
            tuple(row[c] for c in cols),
        )
        doc_id[i] = cur.fetchone()[0]
        loaded.append((d.get("source_system"), d["file_path"]))
    sel = [ci for ci, c in enumerate(chunks) if c["doc"] in doc_id]
    ci_db = {}
    ccols = ["doc_id", "seq", "page", "line_start", "line_end", "bbox", "section", "chunk_text", "n_terms", "embedding", *chunk_extra]
    ph = ["%s"] * 9 + ["%s::vector"] + ["%s"] * len(chunk_extra)
    for ci in sel:
        c = chunks[ci]
        cur.execute(
            f"INSERT INTO {s}.chunk({', '.join(ccols)}) VALUES ({', '.join(ph)}) RETURNING chunk_id",
            (
                doc_id[c["doc"]],
                c["seq"],
                c["page"],
                c["line_start"],
                c["line_end"],
                c["bbox"],
                c["section"],
                c["chunk_text"],
                c["n_terms"],
                vec(vecs[ci]),
                *(c.get(n) for n in chunk_extra),
            ),
        )
        ci_db[ci] = cur.fetchone()[0]
    # 2026-10-22 사용자 지정 — BM25 항목(term,tf) 계산 문서당 BM25_THREADS(기본 4) 병렬 선처리, COPY는 그대로 단일 트랜잭션
    bthreads = max(1, int(pc.cfg().load.bm25_threads))
    sel_terms = {}
    if bthreads > 1 and len(sel) > 1:
        from concurrent.futures import ThreadPoolExecutor

        def _toks(ci):
            return ci, Counter(tokens(index_text(chunks[ci]))).items()

        with ThreadPoolExecutor(max_workers=bthreads) as ex:
            for ci, items in ex.map(_toks, sel):
                sel_terms[ci] = items
    n_terms = 0
    with cur.copy(f"COPY {s}.chunk_term(term, chunk_id, tf) FROM STDIN") as cp:  # 키워드 색인 — 대량은 COPY
        for ci in sel:
            for term, tf in (
                sel_terms.get(ci) or Counter(tokens(index_text(chunks[ci]))).items()
            ):  # 머리말 포함(G9) — 규칙은 common.core.text
                cp.write_row((term, ci_db[ci], min(tf, 32767)))
                n_terms += 1
    # 문서 빈도: 새 청크 단어만 더함(지운 문서는 drop_terms에서 뺌). 비었으면 전체 다시 셈
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
    return {"docs": len(doc_id), "chunks": len(sel), "terms": n_terms}, loaded


def _mark_loaded(loaded):
    """C10 예외(사용자 11-02) — 새로 적재한 문서의 ParsingMeta.loaded_at을 적는다(쓰기 계정, PG 커밋 뒤). 못 열거나 실패하면 경고 한 줄과
    실패 건수만 돌려준다(적재는 그대로 — gold가 검색의 정본, loaded_at은 기록용. DB 담당자가 칸을 더하기 전에도 적재가 멈추지 않게)."""
    if not loaded:
        return 0
    from common.store import parsing_meta_db as PM

    try:
        pm = PM.make_db("write")
    except (Exception, SystemExit) as e:  # make_db는 접속 정보가 없으면 SystemExit
        print(
            f"[pgstore] 경고: ParsingMeta loaded_at 못 적음(연결 없음) — {len(loaded)}건: {type(e).__name__}", file=sys.stderr, flush=True
        )
        return len(loaded)
    try:
        return PM.mark_loaded(pm, loaded)
    except Exception as e:
        print(f"[pgstore] 경고: ParsingMeta loaded_at 못 적음 — {len(loaded)}건: {type(e).__name__}", file=sys.stderr, flush=True)
        return len(loaded)
    finally:
        pm.close()


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
