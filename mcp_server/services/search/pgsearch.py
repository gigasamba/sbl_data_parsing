#!/usr/bin/env python3
"""PostgreSQL(pgvector) 검색(검색 모듈) — 코사인(HNSW·4096차원은 이진 양자화+재정렬) + BM25 + 드문 ID → RRF.
명령: search --q(옛 bench — 로컬 대 pgvector 비교는 mc-01 11-01에 지움). 적재·배포는 modules/load/pgstore.py."""

import argparse
import json
from collections import Counter
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.text import id_terms, tokens  # 토큰 규칙(모듈 계약)
from common.store.pg import HNSW_MAX, PG, conf, vec
from mcp_server import config as mc  # 설정 객체(S7d)
from mcp_server.services.search.local import ID_MAX_DF, embed_query, tie_break, weights  # BR41 동점 깨기(local과 공용)
from mcp_server.services.search.text import term_weights  # X3(10-16 검색 전용으로 분리)

RERANK = 200  # 이진 양자화 후보 수 → 원 벡터 코사인으로 재정렬


def dim_of(db):
    if not hasattr(db, "_dim"):
        db._dim = db.q(
            "SELECT atttypmod AS d FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'embedding'", (f"{db.schema}.chunk",)
        )[0]["d"]
    return db._dim


def _scope_restrict(db, scope):
    """(2026-10-20 통합 search) 하드 필터 범위에 **포함될** 문서(file_path 집합)의 chunk_id 허용 집합.
    question+하드 필터 검색이 저장소 질의 단계부터 그 문서들 안에서만 돌게 한다 — 후치 필터로는 좁은 범위가 전역 상위 풀에 못 들어 근거가 0건이 되는 문제(실측: E29H 1문서)를 고침."""
    s = db.schema
    rows = db.q(f"SELECT c.chunk_id FROM {s}.chunk c JOIN {s}.doc d ON d.doc_id = c.doc_id WHERE d.file_path = ANY(%s)", (sorted(scope),))
    return {r["chunk_id"] for r in rows}


def vector_top(db, q, n, exact=None, restrict=None):
    """코사인 상위 n chunk_id. PG_VECTOR_SEARCH=exact(또는 exact=True)면 색인 없이 정확 검색(재현율 기준선).
    restrict(AD38) = 허용 chunk_id 집합(없으면 제한 없음 — 전과 바이트 동일).
    GH1-14 — SET(인덱스 끔·ef_search)과 그 뒤 SELECT를 db.scope()로 한 연결·한 트랜잭션에 묶는다(SET LOCAL).
    PGPool(검색 MCP 상주 Retriever)은 q() 호출마다 풀에서 다른 연결을 꺼내 와, SET이 그 질의에 안 먹거나
    다음 요청(다른 연결 체크아웃)에 새는 문제가 있었다 — scope()는 끝나면(COMMIT) 자동 리셋."""
    s, d = db.schema, dim_of(db)
    pgc = mc.cfg().search.pg  # 한 번 묶음(S7d — 두 칸이 같은 판 값)
    exact = pgc.vector_search == "exact" if exact is None else exact
    # 10-15 urgent — HNSW reads ef_search candidates first and filters after, so a narrow client filter can return fewer
    # than n hits. A small allowed set is cheaper to scan exactly anyway (chunk_id primary key) and never loses hits.
    if restrict is not None and len(restrict) <= pgc.filter_exact_max:
        exact = True
    where, rparam = (" WHERE chunk_id = ANY(%s)", [sorted(restrict)]) if restrict is not None else ("", [])
    with db.scope() as c:
        if exact:
            c.q("SET LOCAL enable_indexscan = off")
            return [
                r["chunk_id"]
                for r in c.q(f"SELECT chunk_id FROM {s}.chunk{where} ORDER BY embedding <=> %s::vector LIMIT %s", (*rparam, q, n))
            ]
        c.q(f"SET LOCAL hnsw.ef_search = {max(100, RERANK if d > HNSW_MAX else n)}")
        if d <= HNSW_MAX:
            return [
                r["chunk_id"]
                for r in c.q(f"SELECT chunk_id FROM {s}.chunk{where} ORDER BY embedding <=> %s::vector LIMIT %s", (*rparam, q, n))
            ]
        return [
            r["chunk_id"]
            for r in c.q(
                f"""SELECT chunk_id FROM (SELECT chunk_id, embedding FROM {s}.chunk{where}
                        ORDER BY binary_quantize(embedding)::bit({d}) <~> binary_quantize(%s::vector) LIMIT %s) c
                        ORDER BY embedding <=> %s::vector LIMIT %s""",
                (*rparam, q, max(RERANK, n), q, n),
            )
        ]


def search(
    db,
    qv,
    terms,
    k=10,
    n=50,
    retrieve="cosine",
    vr=None,
    methods=None,
    question=None,
    scope=None,
):
    """코사인(기본) 또는 하이브리드(코사인 + BM25 + 드문 ID → RRF). 결과 = v_chunk_source 행 + rrf·via.
    vr = 벡터 순위(chunk_id 목록)를 밖에서 줄 때(EDW 벡터 검색 결과) — 없으면 pgvector로 계산.
    methods = 쓸 방법 {vector, bm25, id}(없으면 retrieve대로) · 가중치 weights(question)(SEARCH_W_*, G14 —
    local.py와 같은 함수를 import해 씀, 가중치가 두 저장소에서 갈라지지 않음).
    scope(2026-10-20 통합 search) = 하드 필터 범위 **안** 문서 file_path 집합 — _scope_restrict로 저장소 질의 단계부터
    그 문서의 청크만 후보로(vector·bm25·ID 전부). None이면 전과 바이트 동일.
    question(G14) = 원문 질문 글자(weights()에 그대로 건넴 — 안 주면 전과 바이트 동일, BR41 tie_break에도 그대로 건넴).
    BR41 — 최종 top-k 안에서(멤버십 불변, 추가 질의 없음) 동점(상대 오차 TIE_EPS_REL)이면 질문 엔티티(고객·계약번호·
    제품코드)와 맞는 문서를 앞으로(local.py tie_break 공용)."""
    s = db.schema
    q = vec(qv) if qv is not None else None  # 질의 임베딩이 없으면(장애) 키워드·ID만 — 부르는 쪽이 methods에서 vector를 뺌
    m = set(methods) if methods else ({"vector"} if retrieve == "cosine" else {"vector", "bm25", "id"})
    w = weights(question)
    restrict = _scope_restrict(db, scope) if scope else None  # 하드 거르기 범위 안 문서만(고객도 이 범위로 — client_edw, 11-02)
    lists = []
    if "vector" in m:
        if vr is None:
            vr = vector_top(db, q, k if m == {"vector"} else n, restrict=restrict)
        else:
            vr = [x for x in vr if restrict is None or x in restrict][: k if m == {"vector"} else n]
        lists.append((vr, w["vector"], "v"))
    if m & {"bm25", "id"}:
        tw = term_weights(terms)  # X3: {토큰: 가중치}(용어 사전 확장) — 확장 없으면 전부 1.0(기존 점수와 동일)
        bm25_where = " WHERE t.chunk_id = ANY(%s)" if restrict is not None else ""
        id_and = " AND t.chunk_id = ANY(%s)" if restrict is not None else ""
        rparam = [sorted(restrict)] if restrict is not None else []
        kr = (
            [
                r["chunk_id"]
                for r in db.q(
                    f"""
            WITH st AS (SELECT n_chunks AS n, avg_len AS a FROM {s}.corpus_stat WHERE id = 1),
                 qw AS (SELECT * FROM unnest(%s::text[], %s::float8[]) AS w(term, weight))
            SELECT t.chunk_id, SUM(qw.weight * LN(1 + (st.n - ts.df + 0.5) / (ts.df + 0.5)) * (t.tf * 2.5) / (t.tf + 1.5 * (0.25 + 0.75 * c.n_terms / NULLIF(st.a, 0)))) AS score
            FROM {s}.chunk_term t JOIN {s}.term_stat ts ON ts.term = t.term JOIN {s}.chunk c ON c.chunk_id = t.chunk_id JOIN qw ON qw.term = t.term, st
            {bm25_where}
            GROUP BY t.chunk_id ORDER BY score DESC LIMIT %s""",
                    (list(tw), list(tw.values()), *rparam, n),
                )
            ]
            if tw
            else []
        )
        ids = id_terms(terms)
        # BR32 — 문턱은 "문서" 수 기준(local.py doc_df와 같은 규칙). term_stat.df는 적재 때 쌓인 청크 기준 수라
        # 안 쓴다 — 한 문서가 청크 여러 개로 쪼개지면(메일 스크린샷 OCR 등) 문서는 하나인데도 청크 기준은 문턱을
        # 넘어 걸렸다(실측 QA074). doc_id 중복 제거 집계는 질의 때 바로.
        ir = (
            [
                r["chunk_id"]
                for r in db.q(
                    f"""WITH ddf AS (
                                                  SELECT ct.term, COUNT(DISTINCT c.doc_id) AS d
                                                  FROM {s}.chunk_term ct JOIN {s}.chunk c ON c.chunk_id = ct.chunk_id
                                                  WHERE ct.term = ANY(%s) GROUP BY ct.term)
                                             SELECT t.chunk_id FROM {s}.chunk_term t JOIN ddf ON ddf.term = t.term
                                             WHERE t.term = ANY(%s) AND ddf.d <= %s{id_and} GROUP BY t.chunk_id ORDER BY COUNT(*) DESC, t.chunk_id LIMIT %s""",
                    (ids, ids, ID_MAX_DF, *rparam, n),
                )
            ]
            if ids
            else []
        )
        lists += ([(kr, w["bm25"], "k")] if "bm25" in m else []) + ([(ir, w["id"], "i")] if "id" in m else [])
    rrf, via = Counter(), {}
    for lst, w, tag in lists:
        for r, cid in enumerate(lst, 1):
            rrf[cid] += w / (60 + r)
            via[cid] = via.get(cid, "") + tag
    top = [cid for cid, _ in sorted(rrf.items(), key=lambda x: (-x[1], x[0]))[:k]]
    if not top:
        return []
    rows = {r["chunk_id"]: r for r in db.q(f"SELECT * FROM {s}.v_chunk_source WHERE chunk_id = ANY(%s)", (top,))}
    top = [c for c in top if c in rows]  # BR41 — rows를 이미 가져온 뒤 재배열(추가 질의 없음), local.py와 같은 tie_break
    # v_chunk_source에 product_code·contract_no 열이 없음 — rows[c].get()은 그대로 None(죽지 않음, 그 축은 안 씀)
    docmeta = {
        c: (rows[c].get("file_name"), rows[c].get("client_edw"), rows[c].get("contract_no"), rows[c].get("product_code")) for c in top
    }
    top = tie_break(top, {c: rrf[c] for c in top}, docmeta, question)
    return [{**rows[c], "rrf": round(rrf[c], 5), "via": via[c]} for c in top]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search"])
    ap.add_argument("--bundle", default="output/edw/bundle")
    ap.add_argument("--q")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--retrieve", default="cosine", choices=["cosine", "hybrid"])
    a = ap.parse_args(argv)
    db = PG(conf())
    meta = json.loads((Path(a.bundle) / "meta.json").read_text(encoding="utf-8"))
    for r in search(db, embed_query(meta, a.q), tokens(a.q), a.k, retrieve=a.retrieve):
        print(
            f"[{r['rrf']:.4f} {r['via']}] {r['file_path']} p.{r['page']} L.{r['line_start']} bbox={r['bbox']} · {r['chunk_text'][:120]!r}"
        )


if __name__ == "__main__":
    utf8_stdout()
    main()
