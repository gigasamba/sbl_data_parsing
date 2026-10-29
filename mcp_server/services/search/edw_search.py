#!/usr/bin/env python3
"""EDW 벡터 검색(검색 모듈) — EDW에는 벡터만 있으므로 키(chunk_key)를 개발 서버 청크로 바꿔 본문·출처는 개발 서버에서.
명령: search --q · bench(로컬 vs EDW 안 vs EDW→개발 서버 캐시)."""

import argparse
import json
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.core.contract import bundle_chunk_keys  # noqa: E402
from common.store.edwdb import DB, conf, vec_table  # noqa: E402
from mcp_server.services.search.local import Local, embed_query  # noqa: E402


def edw_topk(db, qv, k=50):
    """EDW 안에서 코사인 상위 k → [(chunk_key, score)]."""
    rows = db.q(f"EXEC [{db.schema}].[usp_vec_topk] @qvec=%s, @k=%s", (json.dumps([round(float(x), 6) for x in qv]), k))
    return [(r["chunk_key"], float(r["score"])) for r in rows]


class EdwClient:
    """EDW 벡터를 개발 서버로 가져와(캐시) 코사인 → 상위 chunk_key(현재 서버 방식 — EDW에는 벡터만 있으므로 본문은 개발 서버에서).
    캐시 키 = 벡터 테이블의 (행 수, 키 체크섬) — 적재가 바뀌면 다시 가져옴."""

    def __init__(self, db, cache="output/edw/vec_cache.npz"):
        import numpy as np

        self.db, self.cache = db, Path(cache)
        mode, t = vec_table(db)
        if not t:
            raise SystemExit("EDW 벡터 테이블 없음 — 먼저 python -m pipeline.load.edw_insert deploy · load")
        s = db.schema
        sig = db.q(
            f"SELECT COUNT(*) AS n, ISNULL(CHECKSUM_AGG(CHECKSUM(chunk_key)), 0) AS c FROM [{s}].[{t}]"
            + (" WHERE d = 0" if mode == "narrow" else "")
        )[0]
        key = f"{mode}:{sig['n']}:{sig['c']}"
        t0 = time.perf_counter()
        if self.cache.exists() and str(np.load(self.cache)["key"]) == key:
            z = np.load(self.cache)
            self.keys, self.v, self.pulled = list(z["keys"]), z["v"], False
        else:
            if mode == "native":
                rows = db.q(f"SELECT chunk_key, CAST(emb AS NVARCHAR(MAX)) AS v FROM [{s}].[chunk_vec] ORDER BY chunk_key")
                self.keys = [r["chunk_key"] for r in rows]
                self.v = np.array([json.loads(r["v"]) for r in rows], dtype="float32")
            else:
                rows = db.q(f"SELECT chunk_key, d, v FROM [{s}].[chunk_vec_n] ORDER BY chunk_key, d")
                self.keys = sorted({r["chunk_key"] for r in rows})
                pos = {c: i for i, c in enumerate(self.keys)}
                dim = max(r["d"] for r in rows) + 1 if rows else 0
                self.v = np.zeros((len(self.keys), dim), dtype="float32")
                for r in rows:
                    self.v[pos[r["chunk_key"]], r["d"]] = r["v"]
            nrm = np.linalg.norm(self.v, axis=1, keepdims=True)
            self.v = self.v / np.where(nrm == 0, 1, nrm)
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            np.savez(self.cache, keys=np.array(self.keys), v=self.v, key=key)
            self.pulled = True
        self.load_ms = (time.perf_counter() - t0) * 1000

    def topk(self, qv, k=50):
        import numpy as np

        sc = self.v @ qv
        return [(self.keys[i], float(sc[i])) for i in np.argsort(-sc)[:k]]


def bench(db, bundle, questions, k=10, limit=50, out="output/edw"):
    """같은 질의: 로컬 numpy 코사인 vs EDW 안 usp_vec_topk vs EDW→개발 서버(캐시) — 지연과 로컬 상위 k 일치(정확 검색끼리라 1.0이 정상)."""
    meta = json.loads((Path(bundle) / "meta.json").read_text(encoding="utf-8"))
    L, keys = Local(bundle), bundle_chunk_keys(bundle)
    qs = [json.loads(x) for x in Path(questions).read_text(encoding="utf-8").splitlines() if x.strip()][:limit]
    C = EdwClient(db)
    res, agree = {"local": [], "edw": [], "edw-client": []}, {"edw": [], "edw-client": []}
    for q in qs:
        qv = embed_query(meta, q.get("query") or q["question"])
        t0 = time.perf_counter()
        lo = {keys[i] for i in L.search(qv, [], k, retrieve="cosine")[0]}
        res["local"].append(time.perf_counter() - t0)
        for m, f in (("edw", lambda: edw_topk(db, qv, k)), ("edw-client", lambda: C.topk(qv, k))):  # noqa: B023 — 같은 반복 안에서 바로 부름
            t0 = time.perf_counter()
            got = {key for key, _ in f()}
            res[m].append(time.perf_counter() - t0)
            agree[m].append(len(got & lo) / max(len(lo), 1))
    pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] * 1000
    lines = [
        f"# 벡터 검색 속도 — 로컬 vs EDW(벡터만) ({time.strftime('%Y-%m-%d %H:%M')})",
        "",
        f"질의 {len(qs)}개 · 상위 k={k} · 청크 {L.n}개 · 차원 {meta['dim']} · 벡터 저장 {vec_table(db)[0]} · "
        f"EDW 벡터 가져오기(첫 1회, 이후 캐시) {C.load_ms:.0f} ms",
        "",
        "| 방식 | p50 ms | p95 ms | 로컬 상위 k 일치 |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {m} | {pct(ts, 0.5):.1f} | {pct(ts, 0.95):.1f} | " + (f"{statistics.mean(agree[m]):.2f}" if m in agree else "—") + " |"
        for m, ts in res.items()
    ]
    lines += [
        "",
        "EDW에는 벡터만 있으므로 본문·BM25·ID·출처는 어느 방식이든 개발 서버(pgvector/로컬)에서. EDW 시간에는 네트워크 왕복 포함.",
    ]
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "bench.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "bench"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--q", help="search 질의")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--questions", default="output/eval/questions.jsonl")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args(argv)
    with DB(conf()) as db:  # VS8b R-7 — 끝나면 연결 닫음
        meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
        if a.cmd == "search":
            L, keys = Local(a.bundle), bundle_chunk_keys(a.bundle)
            pos = {k: i for i, k in enumerate(keys)}
            for key, sc in edw_topk(db, embed_query(meta, a.q), a.k):
                c = L.chunks[pos[key]] if key in pos else None
                d = L.docs[c["doc"]] if c else {}
                print(
                    f"[{sc:.4f}] {d.get('file_path', '(묶음에 없는 키)')} p.{c and c['page']} L.{c and c['line_start']} · "
                    f"{(c or {}).get('chunk_text', '')[:120]!r}"
                )
        else:
            bench(db, a.bundle, a.questions, a.k, a.limit)


if __name__ == "__main__":
    utf8_stdout()
    main()
