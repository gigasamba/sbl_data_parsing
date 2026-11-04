"""mc-01 — test bundle → fresh search schema in the SQLite stand-in (no real PG, no `pipeline` import: this runs in the
mcp-server image). Row building copies the minimum of pipeline/load/pgvector_load.py:load().

    d = mk_bundle(docs, chunks)      # bundle files + stand-in file under d/"pg"
    with use(d):                     # settings: stand-in dir d/"pg", no PG connection values
        R = Retriever(pg=...)          # the search reads only the stand-in (mc-19 — no bundle files)
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
from common.store import pg_standin as PS
from common.store.db.dbtool import standin_script
from common.store.db.models import search_tables as ST
from common.store.pg import vec
from mcp_server import config as mc

SCHEMA = "test_mcp"  # stand-in file <dir>/test_mcp.sqlite — a temp dir per bundle, never a shared one


def standin_of(bundle):
    return Path(bundle) / "pg"


def load(bundle, schema=SCHEMA, standin=None):
    """bundle (meta.json, docs.jsonl, chunks.jsonl, optional vectors.npy) → new stand-in source schemas `<schema>_<src>` in `standin`
    (pl-28 — a doc goes to the schema of its source_system: SFDC·CRMS·LAS·FAQ, anything else → other). Doc columns given in the doc dict
    are written when that schema has them (clients → clients_doc as JSON; attrs = the doc's `attrs` + doc_class — pl-52)."""
    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    docs, chunks = jl(B / "docs.jsonl"), jl(B / "chunks.jsonl")
    vecs = None
    if meta.get("dim") and (B / "vectors.npy").exists():
        import numpy as np

        vecs = np.load(B / "vectors.npy")
    by_src = {}
    for i, d in enumerate(docs):
        by_src.setdefault(ST.source_of(d.get("source_system")), []).append(i)
    for src in ST.SOURCES:  # 5벌 모두 만듦(빈 원천도 표는 있음 — 서버의 판 0002와 같게)
        idx = by_src.get(src, [])
        s = ST.src_schema(schema, src)
        with mc.senv(PG_STANDIN_DIR=str(standin or standin_of(B))):
            db = PS.StandinPG(s)
        try:
            with db.cn.cursor() as cur:
                cur.execute(standin_script(s, meta.get("dim") or 1))
            dcols = ST.doc_columns(src)[1:]
            ccols = [n for n, _ in ST.CHUNK_EXTRA.get(src, ())]
            with db.cn.transaction(), db.cn.cursor() as cur:
                doc_id = {}
                for i in idx:
                    d = dict(docs[i])
                    names = [n for n in (d.get("clients") or ([d["client"]] if d.get("client") else [])) if n]
                    d.setdefault("clients_doc", json.dumps(names, ensure_ascii=False) if names else None)
                    d.setdefault("content_date", d.get("doc_date"))  # mc-19 — bundle doc_date → gold content_date
                    d.setdefault("embed_model", meta.get("embed_model"))  # mc-19 — load writes the bundle's model on every doc
                    a = {**(d.get("attrs") or {}), **{k: d[k] for k in ST.LOAD_ATTRS.get(src, ()) if d.get(k) is not None}}
                    d["attrs"] = json.dumps(a, ensure_ascii=False)  # pl-52 — 적재 _attrs와 같게(사슬 키 attrs + 분류 doc_class)
                    d["doc_id"] = i + 1  # 공용 시퀀스 흉내(서버는 5벌이 시퀀스 하나 — 묶음 줄 순서대로 겹치지 않는 번호)
                    cols = ["doc_id"] + [k for k in dcols if d.get(k) is not None]
                    cur.execute(
                        f"INSERT INTO {s}.doc({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING doc_id",
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
                cur.execute(
                    f"INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0) FROM {s}.chunk"
                )
        finally:
            db.sqlite.close()


def mk_bundle(docs, chunks, meta=None, vectors=None, load_pg=True):
    """Temp bundle dir (meta.json · docs.jsonl · chunks.jsonl · vectors.npy if given) + its stand-in schema."""
    d = Path(tempfile.mkdtemp(prefix="pgfix_"))
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
    """Settings for the stand-in of `bundle` + extra senv names. Always the stand-in: PG connection values emptied,
    connect_pool's has_conn() forced False, pg.connect (PG connection pick, would put PG_HOST) and
    server_state.check_store (server guard: empty PG → refuse — tested on its own in test_server_state) no-ops.
    Returns an ExitStack (with … or .close()); closing it also closes every stand-in connection opened meanwhile
    (Windows keeps open sqlite files locked) and removes the bundle's temp dir."""
    from common.store import pg as PGC
    from mcp_server.services.search import server_state
    from mcp_server.services.search import server_state as PGM

    opened = []

    class _Tracked(PS.StandinPG):
        def __init__(self, schema):
            super().__init__(schema)
            opened.append(self)

    st = contextlib.ExitStack()
    st.callback(shutil.rmtree, bundle, ignore_errors=True)  # runs last
    st.callback(lambda: [db.sqlite.close() for db in opened])
    st.enter_context(mc.senv(PG_STANDIN_DIR=str(standin_of(bundle)), PG_SCHEMA=SCHEMA, PG_PASSWORD=None, PG_HOST=None, **names))
    st.enter_context(patch.object(PGM, "has_conn", return_value=False))
    st.enter_context(patch.object(PS, "StandinPG", _Tracked))  # connect_pool imports it at call time
    st.enter_context(patch.object(PGC, "connect", lambda a: None))
    st.enter_context(patch.object(server_state, "check_store", lambda: None))  # stand-in injected here — the image runs as a server
    return st


@contextlib.contextmanager
def retriever(bundle, *args, **names):
    """Retriever on the stand-in of `bundle` under use() (connections closed and temp dir removed after)."""
    from mcp_server.services.search import server_state as PGM
    from mcp_server.services.search.retriever import Retriever

    src = names.pop("src", "other")
    with use(bundle, **names):
        yield Retriever(*args, pg=PGM.connect_sources()[src])
