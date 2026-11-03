#!/usr/bin/env python3
"""개발 서버 PostgreSQL + pgvector 저장소 — 대표 파싱·청크·벡터·그래프를 EDW 대신 개발 서버에서 관리.

PostgreSQL은 Docker로(이미지 = dev_server_pgvector 브랜치의 pgvector/pgvector:pg16 → docker load, 띄우기: valid_env/docker/compose.pg.yml — PC·단독 시험 전용, S6b).
접속: PG_CONN_FILE=<KEY=VALUE 파일> 또는 환경변수 PG_HOST(127.0.0.1) · PG_PORT(5432) · PG_DB(rag) · PG_USER(rag) · PG_PASSWORD · PG_SCHEMA(ai)
드라이버: psycopg 3(반입 휠 assets/wheels/psycopg*) — 비밀번호는 파일·환경변수에만.

명령: check · deploy · load(묶음 → 한 트랜잭션, 같은 문서 건너뜀, --replace) · faq-sync(pl-41) — 검색은 modules/search/pgsearch.py
load는 더하고 고치기만 한다 — 이번 묶음에 없는 문서를 지우지 않는다(pl-13, 사용자 10-29: 원천에서 지운 문서·파싱 실패는 로컬 기록만).
예외 faq-sync --reset(pl-41, 사용자 11-03): 새 FAQ가 올라오면 gold faq를 통째로 비우고 run_docs가 FAQ 전체를 다시 넣는다.
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

from common.core import span as SP  # op-01 성능 span
from common.core.console import utf8_stdout
from common.core.contract import jl  # 묶음 읽기
from common.core.text import index_text, tokens  # 색인·토큰 규칙(모듈 계약)
from common.store.pg import HNSW_MAX, PG, _standin_schema, _warn_standin, conf, has_conn, vec  # noqa: F401
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared import runtrace  # op-01 pipe_run 문서 수·직접 실행 run_id

# DROP/TRUNCATE/DELETE 대상 식별자 화이트리스트(XS3) — 우리 스키마의 우리 표만. 스키마명 자체는 common/pg.conf()가 이미 정규식으로 검증.
_OUR_TABLES = {"doc", "chunk", "chunk_term", "term_stat", "corpus_stat"}  # 원천 스키마마다 같은 표(pl-28 — load_run은 11-02에 지움)


def _tbl(s, name):
    if name not in _OUR_TABLES:
        raise SystemExit(f"허용 안 된 표(화이트리스트 밖): {name}")
    return f"{s}.{name}"


def _has_marker(db):
    """기준 스키마에 우리 판 표(alembic_version — deploy·migrate가 만듦)가 있는지(11-02 — load_run 표식을 대신)."""
    return bool(db.q("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name='alembic_version'", (db.schema,)))


def _require_marked_schema(db, what="--replace"):
    """--replace·faq-sync --reset은 우리가 만든 스키마(판 표가 있음)에서만(XS3) — 표식 없는 기존 스키마는 남의 것일 수 있어 거부."""
    if not _has_marker(db):
        raise SystemExit(
            f"{what} 거부: 스키마 {db.schema}에 우리 표식(판 표 alembic_version)이 없음 — "
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


def require_vectors(meta):
    """pl-16(사용자 10-30 A6) — 임베딩 없는 묶음(`--embed none` · dim 0)은 적재·배포를 시작하지 않는다(검색에 벡터 필수 — 옛 동작은
    vector(0) 표를 만들려다 PG 오류로 끝남). 종료 코드 2 + 무엇을 하라는 한 줄."""
    if meta.get("embed") == "none" or (not meta.get("dim") and meta.get("chunks")):  # 청크 0건 문서(빈·스캔만)는 dim 0이어도 문서 행은 적재
        print(
            f"[load] 임베딩 없는 묶음(embed={meta.get('embed')!r}, dim={meta.get('dim')!r}) — 적재 거부: build_bundle을 --embed api로 다시 만든다(pl-16)",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)


def load(db, bundle, replace=False, rep_dir=None):
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
    require_vectors(meta)
    docs, chunks = _nonul(jl(B / "docs.jsonl")), _nonul(jl(B / "chunks.jsonl"))
    vecs = np.load(B / "vectors.npy", mmap_mode="r")  # 필요한 청크만 읽음(전체를 메모리에 올리지 않음)
    t0 = time.time()
    from pipeline.load import edw_meta

    edw, meta_missing = edw_meta.fetch([(d.get("source_system"), d["file_path"]) for d in docs])  # pl-29 — EDW 조인(트랜잭션 밖, 읽기 계정)
    for d in docs:
        d.update({k: v for k, v in (edw.get(d["file_path"]) or {}).items() if v is not None})
    failed = _classify(db, B, docs, rep_dir, replace)  # pl-33 — SFDC·LAS 라벨(gold 넣기 전 · 이미 있는 라벨은 덮지 않음)
    by_src = {}
    for i, d in enumerate(docs):
        if d["file_path"] in failed:  # 분류 실패 = 이 문서의 적재 실패(gold에 안 넣음 — 다음 정상 실행이 다시 고름)
            continue
        by_src.setdefault(ST.source_of(d.get("source_system")), []).append(i)
    dbs = src_dbs(db)
    elsewhere = _elsewhere(dbs, docs, by_src)  # 같은 원본 경로가 다른 원천 스키마에 있는지(원천이 바뀐 문서 — 리뷰 #86)
    kept = []  # 이미 gold에 있어 건너뛴 문서 — ParsingMeta gold_version이 비었으면 채움(_mark_loaded)
    if not replace:  # 어디든 이미 있으면 건너뜀(두 스키마에 같은 문서가 생기지 않게)
        kept = [(d.get("source_system"), d["file_path"]) for d in docs if d["file_path"] in elsewhere]
        by_src = {src: [i for i in idx if docs[i]["file_path"] not in elsewhere] for src, idx in by_src.items()}
    counts = {"docs": 0, "chunks": 0, "terms": 0, "by_source": {}, "meta_missing": meta_missing}
    loaded = []
    if getattr(db, "is_standin", False):
        # 대역은 스키마마다 파일이라 공용 시퀀스가 없음 — 5벌의 가장 큰 doc_id 다음부터 번호를 줘 겹치지 않게(chunk_key·원문 도구 cursor)
        nxt = [1 + max(_max_doc_id(sdb) for sdb in dbs.values())]
        for src, ids in _drop_plan(elsewhere, replace).items():
            sdb = dbs[src]
            with sdb.cn.transaction(), sdb.cn.cursor() as cur:
                _drop_docs(cur, sdb.schema, ids, meta["dim"])
        for src, idx in by_src.items():
            sdb = dbs[src]
            with sdb.cn.transaction(), sdb.cn.cursor() as cur:
                c, ld, kp = _load_src(cur, sdb.schema, src, docs, idx, chunks, vecs, meta, replace, nxt)
            _add(counts, src, c)
            loaded += ld
            kept += kp
    else:
        with db.cn.transaction(), db.cn.cursor() as cur:  # 한 트랜잭션 — 실패하면 5벌 모두 되돌림
            for src, ids in _drop_plan(elsewhere, replace).items():
                _drop_docs(cur, dbs[src].schema, ids, meta["dim"])
            for src, idx in by_src.items():
                c, ld, kp = _load_src(cur, dbs[src].schema, src, docs, idx, chunks, vecs, meta, replace)
                _add(counts, src, c)
                loaded += ld
                kept += kp
    counts["sec"] = round(time.time() - t0, 1)
    counts["loaded_at_failed"] = _mark_loaded(loaded, kept, gold_version(meta))
    from common.core import runlog

    runlog.note(f"적재 {json.dumps({'bundle': str(B), 'meta': meta, 'counts': counts}, ensure_ascii=False, default=str)}")
    return counts


def _classify(db, bundle, docs, rep_dir, replace=False):
    """pl-33(사용자 11-02) — SFDC·LAS 문서에 doc_class. 이미 gold에 라벨이 있는 문서는 그 라벨 그대로(덮지 않음). --replace가 아니면
    이미 어느 원천 스키마에든 저장된 문서는 적재가 건너뛰므로 부르지 않는다(버릴 답에 LLM을 쓰지 않음). 본문은 게시가 올리는 .md와 같은
    글(rep_dir의 대표 결과 → render_md, 없으면 묶음 full_text). 반환: 분류에 실패한 file_path 집합(적재하지 않음)."""
    from common.store.db.models import search_tables as ST
    from pipeline.load import classify as CL

    targets = [d for d in docs if ST.source_of(d.get("source_system")) in CL.LABELS]
    if not targets:
        return set()
    paths = sorted(d["file_path"] for d in targets)
    existing, stored = {}, set()
    for src, sdb in src_dbs(db).items():
        cols = "file_path, doc_class" if src in CL.LABELS else "file_path, NULL AS doc_class"
        try:
            rows = sdb.q(f"SELECT {cols} FROM {sdb.schema}.doc WHERE file_path = ANY(%s)", (paths,))
        except Exception:  # 표가 아직 없음(처음 적재)
            rows = []
        stored.update(r["file_path"] for r in rows)
        existing.update({r["file_path"]: r["doc_class"] for r in rows if r["doc_class"]})
    if not replace:
        targets = [d for d in targets if d["file_path"] not in stored]
    todo = [d for d in targets if d["file_path"] not in existing and not d.get("doc_class")]  # 힌트는 문서 행(edw_meta가 채운 칸)
    return CL.apply(targets, CL.rep_inputs(todo, rep_dir), existing, audit_path=Path(bundle) / "classify_audit.jsonl")


def _elsewhere(dbs, docs, by_src):
    """원본 경로 → [(원천, doc_id)] — 이번 묶음 문서가 **목표가 아닌** 원천 스키마에 이미 있는 곳(원천이 바뀐 문서). 표가 없는 스키마는 건너뜀."""
    target = {docs[i]["file_path"]: src for src, idx in by_src.items() for i in idx}
    out = {}
    for src, sdb in dbs.items():
        try:
            rows = sdb.q(f"SELECT file_path, doc_id FROM {sdb.schema}.doc WHERE file_path = ANY(%s)", (sorted(target),))
        except Exception:
            continue
        for r in rows:
            if target.get(r["file_path"]) != src:
                out.setdefault(r["file_path"], []).append((src, r["doc_id"]))
    return out


def _drop_plan(elsewhere, replace):
    """--replace일 때만 — 원천 → 지울 doc_id들(다른 원천 스키마에 남은 옛 사본)."""
    plan = {}
    for locs in elsewhere.values() if replace else ():
        for src, did in locs:
            plan.setdefault(src, []).append(did)
    return plan


def _drop_docs(cur, s, ids, dim):
    """원천 스키마 s에서 문서들을 지움(키워드 색인·문서 빈도 포함, chunk는 CASCADE) — 그 스키마의 BM25 통계도 다시 셈."""
    drop_terms(cur, s, ids)
    cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id = ANY(%s)", (ids,))
    if dim is None:  # 통계 행이 없던 스키마(faq_sync) — 차원을 모르면 통계는 다음 적재가 씀
        return
    cur.execute(
        f"""INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len, dim) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0), %s FROM {s}.chunk
                    ON CONFLICT (id) DO UPDATE SET n_chunks = EXCLUDED.n_chunks, avg_len = EXCLUDED.avg_len, dim = EXCLUDED.dim""",
        (dim,),
    )


def faq_sync(db, reset):
    """pl-41(사용자 11-03) — FAQ는 판을 잇지 않고 통째로 바꾼다. reset이면 gold faq 스키마의 문서·청크·키워드 색인을 한 트랜잭션에서
    모두 지운다(새 FAQ가 올라온 실행 — 그 뒤 run_docs가 지금 FAQ 파일 전체를 다시 파싱·적재). 반환 = (지운 문서 수, 남은 gold faq file_path 목록).
    검토 등급 A(gold 지우기)."""
    sdb = src_dbs(db)["faq"]
    if not reset:
        return 0, sorted(r["file_path"] for r in sdb.q(f"SELECT file_path FROM {sdb.schema}.doc"))
    _require_marked_schema(db, "faq-sync --reset")
    dim = (sdb.q(f"SELECT dim FROM {sdb.schema}.corpus_stat WHERE id = 1") or [{"dim": None}])[0]["dim"]
    cn = (sdb if getattr(db, "is_standin", False) else db).cn  # 대역은 원천마다 파일
    with cn.transaction(), cn.cursor() as cur:
        cur.execute(f"SELECT doc_id FROM {sdb.schema}.doc")  # 트랜잭션 안에서 — 그사이 들어온 FAQ도 지움
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            _drop_docs(cur, sdb.schema, ids, dim)
    return len(ids), []


def _max_doc_id(sdb):
    """대역 원천 파일의 가장 큰 doc_id(표가 아직 없으면 0)."""
    try:
        return int(sdb.q(f"SELECT COALESCE(MAX(doc_id), 0) AS m FROM {sdb.schema}.doc")[0]["m"])
    except Exception:
        return 0


def _add(counts, src, c):
    for k in ("docs", "chunks", "terms"):
        counts[k] += c[k]
    counts["by_source"][src] = c


def _load_src(cur, s, src, docs, idx, chunks, vecs, meta, replace, nxt=None):
    """원천 스키마 s 하나에 문서 idx(docs.jsonl 줄 번호)를 적재 — 반환 (건수, 새로 넣은 문서, 이미 있어 건너뛴 문서 — 둘 다 [(source_system, file_path)])."""
    from common.store.db.models import search_tables as ST

    cols = ST.doc_columns(src)[1:]  # doc_id 빼고(실 PG는 공용 시퀀스 기본값)
    if nxt is not None:  # 대역 — 번호를 직접 줌
        cols = ["doc_id", *cols]
    chunk_extra = [n for n, _ in ST.CHUNK_EXTRA.get(src, ())]
    cur.execute(f"SELECT file_path, doc_id FROM {s}.doc")
    have = {r[0]: r[1] for r in cur.fetchall()}
    doc_id, loaded, kept = {}, [], []
    with SP.span("load.doc", "load", table="doc", source=src) as sp:  # op-01 — 표별 행 수·rows/sec
        for i in idx:
            d = docs[i]
            old = have.get(d["file_path"])
            if old and not replace:
                kept.append((d.get("source_system"), d["file_path"]))
                continue
            if old:
                drop_terms(cur, s, [old])
                cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id=%s", (old,))  # chunk는 ON DELETE CASCADE
            row = {
                **{c: d.get(c) for c in cols},
                "doc_id": nxt[0] if nxt is not None else None,
                "created_at": _kst(d.get("created_at")),
                "clients_doc": json.dumps(d["clients"], ensure_ascii=False) if d.get("clients") else None,
            }
            cur.execute(
                f"INSERT INTO {s}.doc({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING doc_id",
                tuple(row[c] for c in cols),
            )
            doc_id[i] = cur.fetchone()[0]
            if nxt is not None:
                nxt[0] += 1
            loaded.append((d.get("source_system"), d["file_path"]))
        sp.rows(len(doc_id))
    sel = [ci for ci, c in enumerate(chunks) if c["doc"] in doc_id]
    ci_db = {}
    ccols = ["doc_id", "seq", "page", "line_start", "line_end", "bbox", "section", "chunk_text", "n_terms", "embedding", *chunk_extra]
    ph = ["%s"] * 9 + ["%s::vector"] + ["%s"] * len(chunk_extra)
    with SP.span("load.chunk", "load", table="chunk", source=src) as sp:
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
        sp.rows(len(ci_db)).add(chars=sum(len(chunks[ci]["chunk_text"]) for ci in sel))
    # 2026-10-22 사용자 지정 — BM25 항목(term,tf) 계산 문서당 BM25_THREADS(기본 4) 병렬 선처리, COPY는 그대로 단일 트랜잭션
    with SP.span("load.chunk_term", "load", table="chunk_term", source=src) as sp:  # 키워드 색인 토큰화(병렬) + COPY
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
        sp.rows(n_terms)
    # 문서 빈도: 새 청크 단어만 더함(지운 문서는 drop_terms에서 뺌). 비었으면 전체 다시 셈
    with SP.span("load.stats", "load", table="term_stat/corpus_stat", source=src):
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
    return {"docs": len(doc_id), "chunks": len(sel), "terms": n_terms}, loaded, kept


def gold_version(meta):
    """gold_version(pl-38, 사용자 11-03) = `<VERSION>+m<마스터 해시 앞 8자>` — 구조화가 읽은 마스터 표 해시(묶음 meta.json master_hash).
    master_hash가 없는 묶음(옛 묶음)은 `<VERSION>`만. 캐시 열쇠·code_fp에는 넣지 않는다(마스터가 바뀌어도 자동 재처리 없음)."""
    from pipeline.load.parsing_meta import pipeline_version  # 게시(silver_version)와 같은 자리

    h = (meta or {}).get("master_hash")
    return f"{pipeline_version()}+m{h[:8]}" if h else pipeline_version()


def _mark_loaded(loaded, kept=(), version=None):
    """C10 예외(사용자 11-02) — 새로 적재한 문서의 ParsingMeta.loaded_at·gold_version을 적는다(쓰기 계정, PG 커밋 뒤). 못 열거나 실패하면 경고 한 줄과
    실패 건수만 돌려준다(적재는 그대로 — gold가 검색의 정본, loaded_at은 기록용. DB 담당자가 칸을 더하기 전에도 적재가 멈추지 않게)."""
    if not loaded and not kept:
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
        return PM.mark_loaded(pm, loaded, version or gold_version(None), kept)  # gold_version = 적재한 코드 판 + 마스터 해시(pl-38)
    except Exception as e:
        print(f"[pgstore] 경고: ParsingMeta loaded_at 못 적음 — {len(loaded)}건: {type(e).__name__}", file=sys.stderr, flush=True)
        return len(loaded)
    finally:
        pm.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "deploy", "load", "faq-sync"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--reset", action="store_true", help="faq-sync — gold faq 문서·청크를 모두 지움(pl-41 — 새 FAQ가 올라온 실행)")
    ap.add_argument("--out", default=None, help="faq-sync 결과 JSON 파일(지운 수·남은 gold faq file_path)")
    ap.add_argument("--rep-dir", default=None, help="대표 결과 폴더(_rep) — 분류 본문을 게시 .md와 같게(pl-33). 비우면 묶음 full_text")
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
    if a.cmd == "faq-sync" and not a.out:
        ap.error("faq-sync는 --out이 필요함")
    if a.cmd in ("load", "faq-sync") and not getattr(db, "is_standin", False):
        # S8a(Q5) — 판 기록 없음은 경고 뒤 계속, 끝보다 낮거나 모르는 판은 거부(종료 2) · faq-sync도 모르는 판에서는 지우지 않음
        from common.store.db import dbtool

        dbtool.require_current(db.q, "search", db.schema)
    if a.cmd == "faq-sync":
        n, gold = faq_sync(db, a.reset)
        Path(a.out).write_text(json.dumps({"faq_reset": n, "gold": gold}, ensure_ascii=False), encoding="utf-8")
        return
    meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
    require_vectors(meta)  # pl-16 — 판 확인·배포·적재 전에
    if a.cmd == "deploy":
        with SP.span("load.deploy", "load"):
            idx = deploy(db, meta["dim"])
        print(f"배포 완료: PostgreSQL 스키마 {db.schema} · vector({meta['dim']}) · {idx} 색인")
    elif a.cmd == "load":
        with SP.span("load.pgvector", "load", cpu=True) as sp:  # op-01 — 적재 전체 1행(표별 하위 span이 이 밑에)
            counts = load(db, a.bundle, a.replace, a.rep_dir)
            sp.add(**{k: v for k, v in counts.items() if k in ("docs", "chunks", "terms", "sec")})
            runtrace.docs(total=counts["docs"])  # op-01 — pipe_run 문서 수(이번에 새로 넣은 문서)
        print(json.dumps(counts, ensure_ascii=False))


# ---- PG 단일 연결 전환점(0.2.0 — 옛 pipeline/load/pg_load_connect.py, pl-46)
def pg_connect(c=None, pg_schema=None):
    """AD41 단일 전환점 — PG_PASSWORD·PG_CONN_FILE이 있으면 진짜 PG(PG 클래스), 없으면 스탠드인(StandinPG, sqlite ·
    PG_STANDIN_DIR, 기본 output/pg_standin). load/pgstore.py main()이 씀 — 서버는 pipeline.env에 연결 정보만 채우면
    코드 변경 없이 진짜 PG로 바뀐다. 한 줄 알림(모드)은 호출부(check_env.py·pgvector_load.py)가 찍는다 — 스탠드인을
    고를 때는 여기서도 WARNING 한 줄(_warn_standin, 서버에서 비밀번호를 빠뜨려도 조용히 안 넘어가게)."""
    if has_conn():
        c = c or conf()
        if pg_schema:
            c = {**c, "PG_SCHEMA": pg_schema}
        return PG(c)
    _warn_standin()
    from common.store.pg_standin import StandinPG

    return StandinPG(_standin_schema(pg_schema or (c or {}).get("PG_SCHEMA")))


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py 적재가 BM25_THREADS를 넘김)
    utf8_stdout()
    with runtrace.run("pgvector_load", sys.argv[1:]):  # op-01 — 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
