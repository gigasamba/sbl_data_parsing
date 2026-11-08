"""mc-01 — test bundle → fresh search schema `test_<random>` in the real pgvector (e2-22 — no stand-in, no `pipeline` import: this
runs in the mcp-server image). Tables come from the migrations (dbtool), rows copy the minimum of pipeline/load/pgvector_load.py:load().

    d = mk_bundle(docs, chunks)      # bundle files + its temp schema (dropped when the test process ends — tests/server/common/pgcase.py)
    with use(d):                     # settings: PG_SCHEMA = that schema
        R = Retriever(pg=...)          # the search reads only PG (mc-19 — no bundle files)
"""

import contextlib
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from common.core.contract import jl
from common.core.text import index_text, tokens
from common.store.db import dbtool
from common.store.db.models import search_tables as ST
from common.store.pg import vec
from mcp_server import config as mc
from tests.server.common import pgcase

_JSON = ("attrs", "engines")  # jsonb columns


def schema_of(bundle):
    return (Path(bundle) / "schema.txt").read_text(encoding="utf-8")


def load(bundle, schema=None, fixed=True):
    """bundle (meta.json, docs.jsonl, chunks.jsonl, optional vectors.npy) → source schemas `<schema>_<src>` (default: the bundle's
    schema). pl-28 — a doc goes to the schema of its source_system: SFDC·CRMS·LAS·FAQ·DEV-<n>, anything else → other. Doc columns given
    in the doc dict are written when that schema has them (clients → clients_doc as JSON; attrs = the doc's `attrs` + doc_class — pl-52).
    fixed=False: only the DEV sources of this bundle (a DEV schema made after the first load — the 5 fixed ones are left as they are)."""
    B = Path(bundle)
    schema = schema or schema_of(B)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    docs, chunks = jl(B / "docs.jsonl"), jl(B / "chunks.jsonl")
    vecs = None
    if meta.get("dim") and (B / "vectors.npy").exists():
        import numpy as np

        vecs = np.load(B / "vectors.npy")
    by_src = {}
    for i, d in enumerate(docs):
        by_src.setdefault(ST.source_of(d.get("source_system")), []).append(i)
    devs = ST.dev_order(s for s in by_src if ST.is_dev(s))
    dim = meta.get("dim") or 1
    with dbtool.engine().begin() as conn:  # tables = migrations (5 fixed + the bundle's DEV sources — dbtool up)
        dbtool.upgrade("search", schema, dim, conn)
        for src in devs:
            dbtool.upgrade("search", schema, dim, conn, src)
    if fixed:
        pgcase.fill_master(schema)  # 검색이 읽는 마스터 표(`<schema>_master`)
    db = pgcase.connect(schema)
    try:
        with db.cn.transaction(), db.cn.cursor() as cur:
            cur.execute(f"SELECT nextval('{schema}.{ST.SEQ}')")
            n0 = cur.fetchone()[0]  # doc_id in bundle line order, not overlapping across the source schemas (shared sequence)
            cur.execute(f"SELECT setval('{schema}.{ST.SEQ}', %s)", (n0 + len(docs),))
            for src in [*(ST.SOURCES if fixed else ()), *devs]:
                _load_src(cur, ST.src_schema(schema, src), src, docs, by_src.get(src, []), chunks, vecs, meta, n0)
    finally:
        db.cn.close()


def _load_src(cur, s, src, docs, idx, chunks, vecs, meta, n0):
    dcols = ST.doc_columns(src)[1:]
    ccols = [n for n, _ in ST.CHUNK_EXTRA.get(src, ())]
    doc_id = {}
    for i in idx:
        d = dict(docs[i])
        names = [n for n in (d.get("clients") or ([d["client"]] if d.get("client") else [])) if n]
        d.setdefault("clients_doc", json.dumps(names, ensure_ascii=False) if names else None)
        d.setdefault("content_date", d.get("doc_date"))  # mc-19 — bundle doc_date → gold content_date
        d.setdefault("embed_model", meta.get("embed_model"))  # mc-19 — load writes the bundle's model on every doc
        a = {**(d.get("attrs") or {}), **{k: d[k] for k in ST.LOAD_ATTRS.get(src, ()) if d.get(k) is not None}}
        d["attrs"] = json.dumps(a, ensure_ascii=False)  # pl-52 — 적재 _attrs와 같게(사슬 키 attrs + 분류 doc_class)
        if isinstance(d.get("engines"), (list, dict)):
            d["engines"] = json.dumps(d["engines"], ensure_ascii=False)
        d["doc_id"] = n0 + i
        cols = ["doc_id"] + [k for k in dcols if d.get(k) is not None]
        cur.execute(
            f"INSERT INTO {s}.doc({', '.join(cols)}) VALUES ({', '.join('%s::jsonb' if k in _JSON else '%s' for k in cols)}) RETURNING doc_id",
            tuple(d[k] for k in cols),
        )
        doc_id[i] = cur.fetchone()[0]
    for ci, c in enumerate(chunks):
        if c["doc"] not in doc_id:
            continue
        text = c["chunk_text"]
        emb = vec(vecs[ci]) if vecs is not None else None
        extra = [n for n in ccols if c.get(n) is not None]
        cur.execute(
            f"""INSERT INTO {s}.chunk(doc_id, seq, page, line_start, line_end, bbox, section, chunk_text, n_terms, embedding{"".join(", " + n for n in extra)})
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector{",%s" * len(extra)}) RETURNING chunk_id""",
            (
                doc_id[c["doc"]],
                c["seq"],
                c["page"],
                c["line_start"],
                c["line_end"],
                c.get("bbox"),
                c.get("section"),
                text,
                c.get("n_terms") or len(tokens(text)),
                emb,
                *(c[n] for n in extra),
            ),
        )
        cid = cur.fetchone()[0]
        for term, tf in Counter(tokens(index_text(c))).items():
            cur.execute(f"INSERT INTO {s}.chunk_term(term, chunk_id, tf) VALUES (%s,%s,%s)", (term, cid, tf))
    cur.execute(f"INSERT INTO {s}.term_stat SELECT term, COUNT(*) FROM {s}.chunk_term GROUP BY term")
    cur.execute(f"INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0) FROM {s}.chunk")


def mk_bundle(docs, chunks, meta=None, vectors=None, load_pg=True):
    """Temp bundle dir (meta.json · docs.jsonl · chunks.jsonl · vectors.npy if given) + its temp schema name (schema.txt — loaded unless
    load_pg=False). Writes to PG: a prd run SKIPs here (tests/server/common/pgcase.need_write)."""
    name = pgcase.new_name()
    d = Path(tempfile.mkdtemp(prefix="pgfix_"))
    (d / "schema.txt").write_text(name, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta or {"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in docs), encoding="utf-8")
    (d / "chunks.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in chunks), encoding="utf-8")
    if vectors is not None:
        import numpy as np

        np.save(d / "vectors.npy", np.asarray(vectors, dtype="float32"))
    if load_pg:
        load(d)
    return d


def use(bundle, **names):
    """Settings for the schema of `bundle` + extra senv names; pg.connect (PG connection pick for parse tools) no-ops.
    Returns an ExitStack (with … or .close()); closing it closes the search pool opened meanwhile and removes the bundle's temp dir
    (the schema is dropped when the test process ends — another use() of the same bundle may follow)."""
    from common.store import pg as PGC
    from mcp_server.services.search import server_state

    def _close_pool():
        pool = server_state._STATE.pop("pool", None)
        if pool is not None:
            pool.pool.close()

    st = contextlib.ExitStack()
    st.callback(shutil.rmtree, bundle, ignore_errors=True)  # runs last
    st.callback(_close_pool)
    _close_pool()  # a pool of an earlier schema must not serve this one
    st.enter_context(mc.senv(PG_SCHEMA=schema_of(bundle), **names))
    st.enter_context(patch.object(PGC, "connect", lambda a: None))
    return st


@contextlib.contextmanager
def retriever(bundle, **names):
    """Retriever on the schema of `bundle` under use() (pool closed and temp dir removed after)."""
    from mcp_server.services.search import server_state as PGM
    from mcp_server.services.search.retriever import Retriever

    src = names.pop("src", "other")
    with use(bundle, **names):
        yield Retriever(pg=PGM.connect_sources()[src])
