"""mcp_server.services.search.retriever — BM25 확장 경로·L3-1 최신성·AD38 고객 범위. mc-01(11-01) 로컬 묶음 검색을 지워
PG 검색(pgsearch)을 SQLite 대역(tests/server/mcp/pgfix.py — 임시 폴더, 실 PG 안 닿음)으로 돌린다."""

from tests.server.mcp import pgfix


def _chunk(i, text, seq=0, n_terms=None):  # n_terms None = 적재가 토큰 수로 셈
    return {
        "doc": i,
        "seq": seq,
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "chunk_text": text,
        "n_terms": n_terms,
        "bbox": None,
        "section": None,
    }


def _ranked(n):
    """청크 n개 — 같은 질의어, 뒤로 갈수록 길어 BM25 점수가 순서대로 낮음(동점이면 저장소마다 순서가 달라 순서 시험이 헛돎)."""
    return [_chunk(i, "단가는 100 USD" + " 안내" * i) for i in range(n)]


def test_bm25_no_embedding():
    """임베딩 없는 작은 묶음(dim 0)으로 BM25 확장 경로(X3)가 이어지는지."""
    d = pgfix.mk_bundle([{"file_path": "a.txt"}], [_chunk(0, "바이러스 불활화 공정 설명", 0), _chunk(0, "다른 내용 문서", 1)])
    with pgfix.retriever(d) as R:
        hits, _ = R.search("아무 질문", 5, methods=["bm25"])
        assert isinstance(hits, list)
        hits, _ = R.search("바이러스 불활화", 5, methods=["bm25"])
        assert [h["chunk_key"] for h in hits] == [f"{hits[0]['doc_id']}:0"], hits  # <doc_id>:<seq>(11-02)


# test_recency(L3-1 최신성 순위)는 pl-38(사용자 11-03)에 판 묶음(family)과 함께 지움


def test_bm25_weights():
    """X3 — 가중 질의어({토큰: 가중치}): 전부 1.0이면 목록과 같고, b 가중을 올리면 b만 있는 청크가 1위(옛 Local.bm25 시험을 PG로)."""
    from mcp_server.services.search import pgsearch

    d = pgfix.mk_bundle([{"file_path": f"{n}.txt"} for n in "xyz"], [_chunk(0, "alpha beta"), _chunk(1, "alpha alpha"), _chunk(2, "beta")])
    with pgfix.retriever(d) as R:
        top = lambda terms: [r["file_name"] for r in pgsearch.search(R.pg, None, terms, 3, methods=["bm25"])]
        plain = top(["alpha", "beta"])
        assert plain == top({"alpha": 1.0, "beta": 1.0}), plain  # 확장 없음(전부 1.0) — 목록과 같음
        weighted = top({"alpha": 1.0, "beta": 10.0})
        assert weighted[0] == "z.txt" and weighted != plain, (plain, weighted)  # 가중이 실제로 반영됨


def test_id_doc_level():
    """BR32 — ID_MAX_DF 문턱은 문서 단위: 한 문서가 청크 6개(> ID_MAX_DF 5)로 쪼개져도 문서 기준 df=1이면 id 방법이 찾음(실측 QA074)."""
    d = pgfix.mk_bundle([{"file_path": "mail-x-01.msg"}], [_chunk(0, "mail-x-01 단가 협상", seq=i) for i in range(6)])
    with pgfix.retriever(d) as R:
        hits, _ = R.search("mail-x-01", 5, methods=["id"])
        assert hits and hits[0]["via"] == "i", hits
