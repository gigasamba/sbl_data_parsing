"""mc-01 — test bundle → fresh search schema in the SQLite stand-in (no real PG, no `pipeline` import: this runs in the
mcp-server image). Row building copies the minimum of pipeline/load/pgvector_load.py:load().

    d = mk_bundle(docs, chunks)      # bundle files + stand-in file under d/"pg"
    with use(d):                     # settings: stand-in dir d/"pg", no PG connection values
        R = Retriever(d)
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
from common.store.pg import vec
from mcp_server import config as mc

SCHEMA = "test_mcp"  # stand-in file <dir>/test_mcp.sqlite — a temp dir per bundle, never a shared one


def standin_of(bundle):
    return Path(bundle) / "pg"


def load(bundle, schema=SCHEMA, standin=None):
    """bundle (meta.json, docs.jsonl, chunks.jsonl, optional vectors.npy) → new stand-in schema `schema` in `standin`."""
    B = Path(bundle)
    meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
    docs, chunks = jl(B / "docs.jsonl"), jl(B / "chunks.jsonl")
    vecs = None
    if meta.get("dim") and (B / "vectors.npy").exists():
        import numpy as np

        vecs = np.load(B / "vectors.npy")
    with mc.senv(PG_STANDIN_DIR=str(standin or standin_of(B))):
        db = PS.StandinPG(schema)
    try:
        with db.cn.cursor() as cur:
            cur.execute(standin_script(schema, meta.get("dim") or 1))
        s = schema
        with db.cn.transaction(), db.cn.cursor() as cur:
            cur.execute(f"INSERT INTO {s}.load_run(params) VALUES (%s) RETURNING run_id", (json.dumps(meta),))
            run = cur.fetchone()[0]
            doc_id = {}
            for i, d in enumerate(docs):
                names = [n for n in (d.get("clients") or ([d["client"]] if d.get("client") else [])) if n]
                cl = json.dumps(names, ensure_ascii=False) if names else None
                cur.execute(
                    f"INSERT INTO {s}.doc(file_path, summary, clients, run_id) VALUES (%s,%s,%s,%s) RETURNING doc_id",
                    (d["file_path"], d.get("summary"), cl, run),
                )
                doc_id[i] = (cur.fetchone()[0], json.dumps(names, ensure_ascii=False))
            for ci, c in enumerate(chunks):
                did, cl = doc_id[c["doc"]]
                text = c["chunk_text"]
                emb = vec(vecs[ci]) if vecs is not None else None
                cur.execute(
                    f"""INSERT INTO {s}.chunk(doc_id, seq, page, line_start, line_end, char_start, char_end, bbox, section,
                        chunk_text, n_chars, n_terms, embedding, clients) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s) RETURNING chunk_id""",
                    (
                        did,
                        c["seq"],
                        c["page"],
                        c["line_start"],
                        c["line_end"],
                        c.get("char_start", 0),
                        c.get("char_end", len(text)),
                        c.get("bbox"),
                        c.get("section"),
                        text,
                        len(text),
                        c.get("n_terms") or len(tokens(text)),
                        emb,
                        cl,
                    ),
                )
                cid = cur.fetchone()[0]
                for term, tf in Counter(tokens(index_text(c))).items():
                    cur.execute(f"INSERT INTO {s}.chunk_term(term, chunk_id, tf) VALUES (%s,%s,%s)", (term, cid, tf))
            cur.execute(f"INSERT INTO {s}.term_stat SELECT term, COUNT(*) FROM {s}.chunk_term GROUP BY term")
            cur.execute(
                f"INSERT INTO {s}.corpus_stat(id, n_chunks, avg_len, dim) SELECT 1, COUNT(*), COALESCE(AVG(n_terms), 0), %s FROM {s}.chunk",
                (meta.get("dim") or 0,),
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
    connect_pool's has_conn() forced False and services.connect (Docker pgvector discovery, would put PG_HOST) a no-op.
    Returns an ExitStack (with … or .close()); closing it also closes every stand-in connection opened meanwhile
    (Windows keeps open sqlite files locked) and removes the bundle's temp dir."""
    from common.store import services
    from mcp_server.services.search import pg_mcp_connect as PGM

    opened = []

    class _Tracked(PS.StandinPG):
        def __init__(self, schema):
            super().__init__(schema)
            opened.append(self)

    st = contextlib.ExitStack()
    st.callback(shutil.rmtree, bundle, ignore_errors=True)  # runs last
    st.callback(lambda: [db.sqlite.close() for db in opened])
    st.enter_context(
        mc.senv(PG_STANDIN_DIR=str(standin_of(bundle)), PG_SCHEMA=SCHEMA, PG_PASSWORD=None, PG_CONN_FILE=None, PG_HOST=None, **names)
    )
    st.enter_context(patch.object(PGM, "has_conn", return_value=False))
    st.enter_context(patch.object(PS, "StandinPG", _Tracked))  # connect_pool imports it at call time
    st.enter_context(patch.object(services, "connect", lambda a: None))
    return st


@contextlib.contextmanager
def retriever(bundle, *args, **names):
    """Retriever on the stand-in of `bundle` under use() (connections closed and temp dir removed after)."""
    from mcp_server.services.search.retriever import Retriever

    with use(bundle, **names):
        yield Retriever(bundle, *args)
