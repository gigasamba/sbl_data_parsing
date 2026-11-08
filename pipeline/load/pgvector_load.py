#!/usr/bin/env python3
"""PostgreSQL + pgvector 적재 — 묶음(문서·청크·벡터)을 원천 스키마별 검색 표에 넣는다.

PC·단독 시험용 PG: valid_env/docker/compose.pg.yml(pgvector/pgvector:pg16).
접속: settings.yaml required.pg(host·port·db·user·password·db_schema) · 드라이버 psycopg 3 — 비밀번호는 settings.yaml에만.

명령: check · deploy · load(묶음 → 한 트랜잭션, 같은 문서 건너뜀, --replace) · faq-sync — 검색은 mcp_server.services.search.pgsearch.
load는 더하고 고치기만 한다 — 이번 묶음에 없는 문서를 지우지 않는다(원천에서 지운 문서·파싱 실패는 로컬 기록만).
예외 faq-sync --reset: 새 FAQ가 올라오면 gold faq를 통째로 비우고 run_pipeline이 FAQ 전체를 다시 넣는다.
deploy는 확인(vector 확장·남의 스키마·차원) 뒤 migrate(common.store.db.dbtool up --target search — Alembic 기준판)를 부른다.
load는 판 기록을 먼저 본다(없으면 경고 뒤 계속, 끝보다 낮거나 모르는 판이면 종료 2).
처리 기록(op-17): 문서 행에 게시 기록(--silver — publish_parse_result의 silver.jsonl: sha256·silver 위치·엔진·상태·silver 판·게시 시각)과
적재 판(gold_version)·적재 시각(loaded_at)을 함께 쓴다. 분류에 실패한 문서는 applog.except_doc_info error(다음 실행이 다시 고름).
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from common.core import span as SP  # 성능 span
from common.core.console import utf8_stdout
from common.core.contract import jl  # 묶음 읽기
from common.core.text import index_text, tokens  # 색인·토큰 규칙(모듈 계약)
from common.store.pg import PG, conf, vec
from pipeline import config as pc
from pipeline.shared import runtrace  # pipe_run 문서 수·직접 실행 run_id

# DROP/TRUNCATE/DELETE 대상 식별자 화이트리스트(XS3) — 우리 스키마의 우리 표만. 스키마명 자체는 common/pg.conf()가 이미 정규식으로 검증.
_OUR_TABLES = {"doc", "chunk", "chunk_term", "term_stat", "corpus_stat"}  # 원천 스키마마다 같은 표
_KST = timezone(timedelta(hours=9))  # loaded_at 표기(created_at과 같은 시간대)
# 게시 처리 기록(silver.jsonl)에서 doc 칸으로 옮기는 키(op-17 — 이름 = 칸 이름) · JSONB 칸
SILVER_COLS = ("sha256", "silver_bucket", "silver_key", "engines", "parse_status", "silver_version", "parsed_at")
JSON_COLS = ("attrs", "engines")


def _tbl(s, name):
    if name not in _OUR_TABLES:
        raise SystemExit(f"허용 안 된 표(화이트리스트 밖): {name}")
    return f"{s}.{name}"


def _has_marker(db):
    """기준 스키마에 우리 판 표(alembic_version — deploy·migrate가 만듦)가 있는지."""
    return bool(db.q("SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name='alembic_version'", (db.schema,)))


def _require_marked_schema(db, what="--replace"):
    """--replace·faq-sync --reset은 우리가 만든 스키마(판 표가 있음)에서만(XS3) — 표식 없는 기존 스키마는 남의 것일 수 있어 거부."""
    if not _has_marker(db):
        raise SystemExit(
            f"{what} 거부: 스키마 {db.schema}에 우리 표식(판 표 alembic_version)이 없음 — "
            "남의 기존 스키마일 수 있음(deploy로 먼저 만들거나 다른 PG_SCHEMA 사용)"
        )


class _Src:
    """기준 연결 하나로 원천 스키마 하나를 가리킴(실 PG — 한 연결·한 트랜잭션으로 5벌 모두에 쓴다). q·cn은 기준 연결 그대로."""

    def __init__(self, db, schema):
        self.db, self.schema = db, schema
        self.cn, self.q = db.cn, db.q


def src_dbs(db, need=()):
    """원천 이름 → 그 원천 스키마를 가리키는 연결 — 5벌 + 있는 DEV 원천 스키마(op-17).
    need = 이번 묶음의 DEV 원천: 그 스키마가 없으면 멈춤(적재는 DDL을 하지 않음 — dbtool up이 만듦)."""
    from common.store.db.models import search_tables as ST

    srcs = ST.all_sources(db.schema, db.q)
    missing = sorted(set(need) - set(srcs))
    if missing:
        names = ", ".join(ST.src_schema(db.schema, s) for s in missing)
        raise SystemExit(
            f"[load] DEV 원천 스키마 없음: {names} — 적재는 표를 만들지 않음. settings.yaml required.source.source_systems에 그 원천을 넣고 "
            "`migrate up --target search`(PC: python -m common.store.db.dbtool up --target search) 뒤 다시"
        )
    return {src: _Src(db, ST.src_schema(db.schema, src)) for src in srcs}


def _upgrade(schema, dim):
    """검색 스키마 판 올리기(migrate up — 기준 + DEV 원천 스키마, dbtool.upgrade_search). selftest가 가짜로 바꿔 끼운다."""
    from common.store.db import dbtool

    dbtool.upgrade_search(schema, dim)


def deploy(db, dim):
    """표·색인·뷰는 migrate(Alembic 기준판)가 만든다.
    확인(vector 확장·남의 스키마 거부·차원)은 이 함수가. 실측(30k×4096, 개발 PC): 정확 180~220 ms · 이진 양자화 HNSW+재정렬
    5~7 ms(색인 24 MB, 생성 6.6 s)."""
    from common.store.db import dbtool

    dbtool.precheck_search(db.q, db.schema, dim)  # 확장 직접 생성은 dbtool up --create-extension(PC·단독 시험)만
    kind = dbtool.index_kind(dim)
    if dbtool.status(db.q, "search", db.schema)[0] == "없음" and dbtool.has_tables(db.q, db.schema):
        # 판 기록 없는 기존 스키마: DDL 없이 경고 뒤 계속(migrate up은 이런 스키마를 거부 — 새 스키마로 다시 적재). 빠진 표·색인은 채우지 않음
        dbtool.require_current(db.q, "search", db.schema)
        kind += "(확인 안 함 — 판 기록 없는 기존 스키마)"  # 색인을 만들지도 보지도 않음
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
    return (t if t.tzinfo else t.replace(tzinfo=_KST)).isoformat()


def require_vectors(meta):
    """임베딩 없는 묶음(`--embed none` · dim 0)은 적재·배포를 시작하지 않는다(검색에 벡터 필수 —
    vector(0) 표는 PG 오류). 종료 코드 2 + 무엇을 하라는 한 줄."""
    if meta.get("embed") == "none" or (not meta.get("dim") and meta.get("chunks")):  # 청크 0건 문서(빈·스캔만)는 dim 0이어도 문서 행은 적재
        print(
            f"[load] 임베딩 없는 묶음(embed={meta.get('embed')!r}, dim={meta.get('dim')!r}) — 적재 거부: gold_bundle을 --embed api로 다시 만든다(pl-16)",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)


def require_same_model(dbs, meta, bundle):
    """묶음의 임베딩 모델이 검색 스키마(원천 5벌)에 이미 있는 문서의 모델(doc.embed_model)과 다르면 아무것도 쓰기 전에
    거부(종료 코드 2). 검색은 원천마다 doc.embed_model이 하나여야 하고(pgsearch.index_meta — 섞이면 벡터 검색 거부) 한 MCP가 한 질의 모델로
    5벌을 모두 보므로, 기준은 설정이 아니라 이미 적재된 문서다. 비교 규칙은 검색과 같다(embed.model_key). 모델 칸이 빈 문서는 보지 않는다.
    거부는 stderr 한 줄 + applog.pipe_event 한 행(common.log.db_enabled일 때 — 표의 CHECK 값 안: status fail · err_kind env)."""
    from common.ai.embed import model_key

    got = set()
    for sdb in dbs.values():
        try:
            rows = sdb.q(f"SELECT DISTINCT embed_model AS m FROM {sdb.schema}.doc WHERE embed_model IS NOT NULL")
        except Exception:  # 표가 아직 없음(처음 적재)
            continue
        got.update(model_key(r["m"]) for r in rows)
    new = model_key(meta.get("embed_model"))
    if not got or got == {new}:
        return
    expected = ",".join(sorted(got))
    print(
        f"[load] 임베딩 모델이 다름 — 적재 거부(아무것도 쓰지 않음): 검색 스키마의 문서는 {expected}, 묶음 {bundle}은 {new}. "
        "같은 모델로 묶음을 다시 만들거나 새 검색 스키마에 적재한다(pl-51)",
        file=sys.stderr,
        flush=True,
    )
    from common.core import jsonlog
    from common.store import logsink

    logsink.emit(
        "pipe_event",
        {
            "ts_start": datetime.now(UTC),
            "run_id": jsonlog.get_context().get("run_id"),
            "layer": "load",
            "stage": "load.embed_guard",
            "model": new,
            "status": "fail",
            "err_kind": "env",
            "err": f"embed_model_mismatch: expected {expected}, got {new} (bundle {bundle})",
        },
    )
    raise SystemExit(2)


def load(db, bundle, replace=False, rep_dir=None, silver=None):
    """묶음 → 원천 스키마별로(문서의 source_system으로 고름: SFDC·CRMS·LAS·FAQ·DEV-<n>(`<기준>_dev_<n>` — 없으면 멈춤), 그 밖은 other) 적재. 실 PG는 기준 연결 한 트랜잭션
    (실패하면 5벌 모두 되돌림). 저장된 문서(file_path 같음)는 건너뜀(replace면 지우고 다시 넣음 — 고치기). 묶음에 없는
    저장 문서는 그대로 둠. 실행 정보(묶음 meta·건수·시간)는 실행 기록에 남긴다.
    silver = 게시 처리 기록 파일(silver.jsonl — 원본 키 source_key = 묶음 문서 file_path로 이음). 그 문서 줄이 있으면 새로 넣는 행에 쓰고
    이미 있는 행(건너뜀 — 재게시)은 그 칸만 UPDATE. 줄이 없으면 --replace는 옛 행의 처리 기록을 그대로 옮기고, 새 문서는 NULL."""
    from common.store.db.models import search_tables as ST
    from pipeline.shared import except_docs

    if replace:
        _require_marked_schema(db)  # XS3 — 남의 기존 스키마에 --replace 금지
    import numpy as np

    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    require_vectors(meta)
    docs, chunks = _nonul(jl(B / "docs.jsonl")), _nonul(jl(B / "chunks.jsonl"))
    need = {s for s in (ST.source_of(d.get("source_system")) for d in docs) if ST.is_dev(s)}  # DEV 원천 스키마 — 없으면 멈춤(op-17)
    dbs = src_dbs(db, need)
    require_same_model(dbs, meta, B)  # EDW 조인·분류·쓰기 전에
    rec = {r["source_key"]: r for r in jl(Path(silver))} if silver and Path(silver).is_file() else {}
    for d in docs:  # 게시 처리 기록 → doc 칸(op-17) — 이 묶음에서 줄이 있었는지는 _silver
        r = rec.get(d["file_path"])
        if r:
            d.update({k: r.get(k) for k in SILVER_COLS}, _silver=True)
    vecs = np.load(B / "vectors.npy", mmap_mode="r")  # 필요한 청크만 읽음(전체를 메모리에 올리지 않음)
    t0 = time.time()
    from pipeline.load import edw_doc_meta as edw_meta

    edw, meta_missing = edw_meta.fetch([(d.get("source_system"), d["file_path"]) for d in docs])  # EDW 조인(트랜잭션 밖, 읽기 계정)
    for d in docs:  # 고정 칸(created_at·client_edw)은 문서 행, 원천 메타는 attrs(분류 힌트 포함 — 분류가 attrs에서 읽음)
        m = edw.get(d["file_path"]) or {}
        d.update({k: m[k] for k in ("created_at", "client_edw") if m.get(k) is not None})
        d["attrs"] = dict(m.get("attrs") or {})
    failed = _classify(db, B, docs, rep_dir, replace)  # SFDC·LAS 라벨(gold 넣기 전 · 이미 있는 라벨은 덮지 않음)
    if failed:  # 분류 실패 = 적재 실패 — 기록만(다음 실행이 다시 고름)
        except_docs.note_error(  # 기록만 — 실패해도 적재는 계속
            [
                {
                    "source_key": d["file_path"],
                    "source_system": d.get("source_system"),
                    "file_name": d.get("doc_name"),
                    "reason": "classify_failed",
                }
                for d in docs
                if d["file_path"] in failed
            ]
        )
    by_src = {}
    for i, d in enumerate(docs):
        if d["file_path"] in failed:  # 분류 실패 = 이 문서의 적재 실패(gold에 안 넣음 — 다음 정상 실행이 다시 고름)
            continue
        by_src.setdefault(ST.source_of(d.get("source_system")), []).append(i)
    elsewhere = _elsewhere(dbs, docs, by_src)  # 같은 원본 경로가 다른 원천 스키마에 있는지(원천이 바뀐 문서)
    if not replace:  # 어디든 이미 있으면 건너뜀(두 스키마에 같은 문서가 생기지 않게)
        by_src = {src: [i for i in idx if docs[i]["file_path"] not in elsewhere] for src, idx in by_src.items()}
    counts = {"docs": 0, "chunks": 0, "terms": 0, "by_source": {}, "meta_missing": meta_missing}
    meta = {**meta, "gold_version": gold_version(meta), "loaded_at": datetime.now(_KST).isoformat(timespec="seconds")}  # 이번 적재의 doc 칸
    with db.cn.transaction(), db.cn.cursor() as cur:  # 한 트랜잭션 — 실패하면 5벌 모두 되돌림
        for src, ids in _drop_plan(elsewhere, replace).items():
            _drop_docs(cur, dbs[src].schema, ids)
        for src, idx in by_src.items():
            _add(counts, src, _load_src(cur, dbs[src].schema, src, docs, idx, chunks, vecs, meta, replace))
    except_docs.clear_silver(
        d["file_path"] for d in docs if d["file_path"] not in failed
    )  # pl-68 — 이제 gold에 있음(분류 실패는 silver 행 남김)
    counts["sec"] = round(time.time() - t0, 1)
    return counts


def _classify(db, bundle, docs, rep_dir, replace=False):
    """SFDC·LAS 문서에 doc_class. 이미 gold에 라벨이 있는 문서는 그 라벨 그대로(덮지 않음). --replace가 아니면
    이미 어느 원천 스키마에든 저장된 문서는 적재가 건너뛰므로 부르지 않는다(버릴 답에 LLM을 쓰지 않음). 본문은 게시가 올리는 .md와 같은
    글(rep_dir의 대표 결과 → render_md, 없으면 묶음 full_text). 반환: 분류에 실패한 file_path 집합(적재하지 않음)."""
    from common.store.db.models import search_tables as ST
    from pipeline.load import doc_classify as CL

    targets = [d for d in docs if ST.source_of(d.get("source_system")) in CL.LABELS]
    if not targets:
        return set()
    paths = sorted(d["file_path"] for d in targets)
    existing, stored = {}, set()
    for src, sdb in src_dbs(db).items():
        cols = "file_path, attrs->>'doc_class' AS doc_class" if src in CL.LABELS else "file_path, NULL AS doc_class"
        try:
            rows = sdb.q(f"SELECT {cols} FROM {sdb.schema}.doc WHERE file_path = ANY(%s)", (paths,))
        except Exception:  # 표가 아직 없음(처음 적재)
            rows = []
        stored.update(r["file_path"] for r in rows)
        existing.update({r["file_path"]: r["doc_class"] for r in rows if r["doc_class"]})
    if not replace:
        targets = [d for d in targets if d["file_path"] not in stored]
    todo = [d for d in targets if d["file_path"] not in existing and not d.get("doc_class")]  # 힌트는 문서 attrs(edw_meta가 채운 키)
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
    """--replace일 때만 — 원천 → 지울 doc_id들(다른 원천 스키마에 남은 이전 사본)."""
    plan = {}
    for locs in elsewhere.values() if replace else ():
        for src, did in locs:
            plan.setdefault(src, []).append(did)
    return plan


def _drop_docs(cur, s, ids):
    """원천 스키마 s에서 문서들을 지움(키워드 색인·문서 빈도 포함, chunk는 CASCADE) — 그 스키마의 BM25 통계도 다시 셈."""
    drop_terms(cur, s, ids)
    cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id = ANY(%s)", (ids,))
    cur.execute(_corpus_stat_sql(s))


def _corpus_stat_sql(s):
    """BM25 통계 한 행(청크 수·평균 길이) 다시 셈 — 차원은 chunk.embedding 칸 형식이 정한다."""
    return f"""INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0) FROM {s}.chunk
                    ON CONFLICT (id) DO UPDATE SET n_chunks = EXCLUDED.n_chunks, avg_len = EXCLUDED.avg_len"""


def faq_sync(db, reset):
    """FAQ는 판을 잇지 않고 통째로 바꾼다. reset이면 gold faq 스키마의 문서·청크·키워드 색인을 한 트랜잭션에서
    모두 지운다(새 FAQ가 올라온 실행 — 그 뒤 run_pipeline이 지금 FAQ 파일 전체를 다시 파싱·적재). 반환 = (지운 문서 수, 남은 gold faq file_path 목록).
    검토 등급 A(gold 지우기)."""
    sdb = src_dbs(db)["faq"]
    if not reset:
        return 0, sorted(r["file_path"] for r in sdb.q(f"SELECT file_path FROM {sdb.schema}.doc"))
    _require_marked_schema(db, "faq-sync --reset")
    with db.cn.transaction(), db.cn.cursor() as cur:
        cur.execute(f"SELECT doc_id FROM {sdb.schema}.doc")  # 트랜잭션 안에서 — 그사이 들어온 FAQ도 지움
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            _drop_docs(cur, sdb.schema, ids)
    return len(ids), []


def _add(counts, src, c):
    for k in ("docs", "chunks", "terms"):
        counts[k] += c[k]
    counts["by_source"][src] = c


def _attrs(d, src):
    """문서 → doc.attrs JSON 글자 — EDW 사슬이 채운 키(d["attrs"]) + 적재가 쓰는 키(분류 doc_class — LOAD_ATTRS). 값 없는 키는 뺌, 날짜는 ISO 글자."""
    from common.store.db.models import search_tables as ST

    a = {**(d.get("attrs") or {}), **{k: d.get(k) for k in ST.LOAD_ATTRS.get(src, ())}}
    return json.dumps({k: v for k, v in a.items() if v is not None}, ensure_ascii=False, default=lambda v: v.isoformat())


def _db_val(col, v):
    """처리 기록 칸 값 → DB에 넣을 값(JSONB 칸은 JSON 글자 — 옛 행에서 읽은 값은 목록)."""
    if col not in JSON_COLS or v is None or isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _load_src(cur, s, src, docs, idx, chunks, vecs, meta, replace):
    """원천 스키마 s 하나에 문서 idx(docs.jsonl 줄 번호)를 적재 — 반환 건수. 이미 있는 문서는 건너뜀(replace면 지우고 다시)."""
    from common.store.db.models import search_tables as ST

    cols = ST.doc_columns(src)[1:]  # doc_id 빼고(공용 시퀀스 기본값)
    chunk_extra = [n for n, _ in ST.CHUNK_EXTRA.get(src, ())]
    cur.execute(f"SELECT file_path, doc_id, {', '.join(SILVER_COLS)} FROM {s}.doc")
    have = {r[0]: (r[1], dict(zip(SILVER_COLS, r[2:]))) for r in cur.fetchall()}  # 원본 경로 → (doc_id, 옛 처리 기록)
    doc_id = {}
    with SP.span("load.doc", "load", table="doc", source=src) as sp:  # 표별 행 수·rows/sec
        for i in idx:
            d = docs[i]
            old, old_rec = have.get(d["file_path"]) or (None, {})
            if old and not replace:
                if d.get("_silver"):  # 재게시(--reparse) — 문서는 그대로, 처리 기록만 새 게시로(since/until·parse_date가 맞게)
                    sets = ", ".join(f"{c} = %s::jsonb" if c in JSON_COLS else f"{c} = %s" for c in SILVER_COLS)
                    cur.execute(
                        f"UPDATE {_tbl(s, 'doc')} SET {sets} WHERE doc_id = %s", (*(_db_val(c, d.get(c)) for c in SILVER_COLS), old)
                    )
                continue
            if old and not d.get("_silver"):  # --replace인데 이번 게시 기록이 없음 — 옛 처리 기록을 그대로 옮김
                d.update(old_rec)
            if old:
                drop_terms(cur, s, [old])
                cur.execute(f"DELETE FROM {_tbl(s, 'doc')} WHERE doc_id=%s", (old,))  # chunk는 ON DELETE CASCADE
            row = {
                **{c: d.get(c) for c in cols},
                "created_at": _kst(d.get("created_at")),
                "clients_doc": json.dumps(d["clients"], ensure_ascii=False) if d.get("clients") else None,
                "content_date": d.get("doc_date"),  # 묶음 doc_date(문서에 적힌 날짜) → gold content_date
                "embed_model": meta.get("embed_model"),  # 묶음의 임베딩 모델(검색의 질의 모델 확인 · 문서 단위 guard)
                ST.ATTRS: _attrs(d, src),  # 원천 메타(사슬 fields + 분류 doc_class)
                "engines": _db_val("engines", d.get("engines")),  # 게시 기록(op-17)
                "gold_version": meta.get("gold_version"),  # 이번 적재 판·시각(load()가 meta에)
                "loaded_at": meta.get("loaded_at"),
            }
            cur.execute(
                f"INSERT INTO {s}.doc({', '.join(cols)}) VALUES ({', '.join('%s::jsonb' if c in JSON_COLS else '%s' for c in cols)}) RETURNING doc_id",
                tuple(row[c] for c in cols),
            )
            doc_id[i] = cur.fetchone()[0]
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
    # BM25 항목(term,tf) 계산 문서당 BM25_THREADS(기본 4) 병렬 선처리, COPY는 그대로 단일 트랜잭션
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
        cur.execute(_corpus_stat_sql(s))
    return {"docs": len(doc_id), "chunks": len(sel), "terms": n_terms}


def gold_version(meta):
    """gold_version = `<VERSION>+m<마스터 해시 앞 8자>` — 구조화가 읽은 마스터 표 해시(묶음 meta.json master_hash).
    master_hash가 없는 묶음은 `<VERSION>`만. 캐시 열쇠·code_fp에는 넣지 않는다(마스터가 바뀌어도 자동 재처리 없음)."""
    from common.core.fingerprint import pipeline_version  # 게시(silver_version)와 같은 자리

    h = (meta or {}).get("master_hash")
    return f"{pipeline_version()}+m{h[:8]}" if h else pipeline_version()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "deploy", "load", "faq-sync"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--reset", action="store_true", help="faq-sync — gold faq 문서·청크를 모두 지움(pl-41 — 새 FAQ가 올라온 실행)")
    ap.add_argument("--out", default=None, help="faq-sync 결과 JSON 파일(지운 수·남은 gold faq file_path)")
    ap.add_argument("--rep-dir", default=None, help="대표 결과 폴더(_rep) — 분류 본문을 게시 .md와 같게(pl-33). 비우면 묶음 full_text")
    ap.add_argument("--silver", default=None, help="게시 처리 기록(publish/silver.jsonl) — doc의 sha256·silver 위치·엔진·상태 칸(op-17)")
    a = ap.parse_args(argv)
    db = PG(conf())  # required.pg 접속 정보 — 비면 conf()가 채울 자리를 적고 멈춘다(로컬 대체 DB 없음)
    print(
        f"[pgstore] PG · 스키마 {db.schema}",
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
    if a.cmd in ("load", "faq-sync"):
        # 판 기록 없음은 경고 뒤 계속, 끝보다 낮거나 모르는 판은 거부(종료 2) · faq-sync도 모르는 판에서는 지우지 않음
        from common.store.db import dbtool

        dbtool.require_current(db.q, "search", db.schema)
    if a.cmd == "faq-sync":
        n, gold = faq_sync(db, a.reset)
        Path(a.out).write_text(json.dumps({"faq_reset": n, "gold": gold}, ensure_ascii=False), encoding="utf-8")
        return
    meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
    require_vectors(meta)  # 판 확인·배포·적재 전에
    if a.cmd == "deploy":
        with SP.span("load.deploy", "load"):
            idx = deploy(db, meta["dim"])
        print(f"배포 완료: PostgreSQL 스키마 {db.schema} · vector({meta['dim']}) · {idx} 색인")
    elif a.cmd == "load":
        with SP.span("load.pgvector", "load", cpu=True) as sp:  # 적재 전체 1행(표별 하위 span이 이 밑에)
            counts = load(db, a.bundle, a.replace, a.rep_dir, a.silver)
            sp.add(**{k: v for k, v in counts.items() if k in ("docs", "chunks", "terms", "sec")})
            runtrace.docs(total=counts["docs"])  # pipe_run 문서 수(이번에 새로 넣은 문서)
        print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(호스트 run_pipeline.py 적재가 BM25_THREADS를 넘김)
    utf8_stdout()
    with runtrace.run("pgvector_load", sys.argv[1:]):  # 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
