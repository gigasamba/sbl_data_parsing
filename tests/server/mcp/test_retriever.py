"""mcp_server.services.search.retriever — BM25 확장 경로·L3-1 최신성·AD38 고객 범위. mc-01(11-01) 로컬 묶음 검색을 지워
PG 검색(pgsearch)을 SQLite 대역(tests/server/mcp/pgfix.py — 임시 폴더, 실 PG 안 닿음)으로 돌린다."""

from mcp_server import config as mc
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
    with pgfix.retriever(d, GLOSSARY_DIR=None) as R:
        hits, _ = R.search("아무 질문", 5, methods=["bm25"])
        assert isinstance(hits, list)
        hits, _ = R.search("바이러스 불활화", 5, methods=["bm25"])
        assert [h["chunk_key"] for h in hits] == ["a.txt:0"], hits


def test_recency():
    """L3-1 — 같은 family 2건(구판·최신본) + 무관 문서 1건 → 최신본이 먼저, 구판은 뒤로(안 지움).
    SEARCH_RECENCY=0이면 순서 그대로. 메커니즘 점검이라 '늘' 모드(2)로. doc_key = file_path(PG 경로의 키 — 묶음 doc_meta와 맞음)."""
    docs = [
        {"file_path": "msa_old.docx", "doc_date": "2024-01", "version": None, "superseded": True, "family": "msa"},
        {"file_path": "msa.docx", "doc_date": "2026-05", "version": "2", "superseded": False, "family": "msa"},
        {"file_path": "nda.docx", "doc_date": None, "version": None, "superseded": False, "family": "nda"},
    ]
    d = pgfix.mk_bundle(docs, _ranked(3))
    with pgfix.retriever(d, SEARCH_RECENCY="2", GLOSSARY_DIR=None) as R:
        hits, _ = R.search("단가는?", 3, methods=["bm25"])
        assert [h["doc_key"] for h in hits] == ["msa.docx", "msa_old.docx", "nda.docx"], hits  # 최신본 먼저, 구판은 바로 뒤(L4-8)
        assert R.recency_note == "구판 1건 뒤로"
        assert hits[1]["superseded"] is True and hits[0]["doc_date"] == "2026-05"  # 근거 머리글용 날짜·구판 표시
        with mc.senv(SEARCH_RECENCY="0"):
            hits0, _ = R.search("단가는?", 3, methods=["bm25"])
            assert [h["doc_key"] for h in hits0] == ["msa_old.docx", "msa.docx", "nda.docx"]  # 꺼짐 — 저장소 순서 그대로
            assert R.recency_note is None


def test_client_hard():
    """AD38 — SEARCH_CLIENT_HARD=1 + client 인자: 저장소 질의 단계에서 진짜 제외(재순위 아님).
    문서 3건(Acme Co · Other Co · 고객 미상)이 bm25 점수 순(a > b > c) — 섞이면 바로 드러남."""
    docs = [{"file_path": "a.txt", "client": "Acme Co"}, {"file_path": "b.txt", "client": "Other Co"}, {"file_path": "c.txt"}]
    d = pgfix.mk_bundle(docs, _ranked(3))
    with pgfix.retriever(d, GLOSSARY_DIR=None, SEARCH_CLIENT_HARD=None, SEARCH_CLIENT_STRICT=None) as R:
        names = lambda hits: [h["file_name"] for h in hits]  # 짧은 시험 도우미
        base, _, _ = R.search_ex("단가는?", 5, methods=["bm25"])  # client 인자 없음 — 기준
        assert names(base) == ["a.txt", "b.txt", "c.txt"], base
        off, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # 끔(기본) — 앞으로만(다 있음)
        assert names(off) == ["a.txt", "c.txt", "b.txt"], off
        with mc.senv(SEARCH_CLIENT_HARD="1"):
            same, _, _ = R.search_ex("단가는?", 5, methods=["bm25"])  # client 없음 — 켜져도 영향 없음
            assert names(same) == ["a.txt", "b.txt", "c.txt"], same
            hard, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # Other Co 완전히 빠짐(미상 포함)
            assert names(hard) == ["a.txt", "c.txt"], hard
            with mc.senv(SEARCH_CLIENT_STRICT="1"):
                strict, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # 미상도 뺌
                assert names(strict) == ["a.txt"], strict
                # BR50 E — client_strict=False가 전역 STRICT를 이 호출만 무시(미상 c.txt 살아남음, Other Co는 여전히 빠짐)
                override, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co", client_strict=False)
                assert names(override) == ["a.txt", "c.txt"], override
        assert R.clients() == ["Acme Co", "Other Co"]  # 적재된 고객 이름(doc.clients)


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
    with pgfix.retriever(d, GLOSSARY_DIR=None) as R:
        hits, _ = R.search("mail-x-01", 5, methods=["id"])
        assert hits and hits[0]["via"] == "i", hits


def test_hidden():
    """OP1 — 숨김 doc_key(file_path) 문서의 청크는 저장소 질의 단계에서 완전 제외 · 빈 집합이면 그대로."""
    d = pgfix.mk_bundle([{"file_path": "a.txt"}, {"file_path": "b.txt"}], _ranked(2))
    with pgfix.retriever(d, GLOSSARY_DIR=None) as R:
        names = lambda: [h["file_name"] for h in R.search("단가는?", 5, methods=["bm25"])[0]]
        assert names() == ["a.txt", "b.txt"]
        R.hidden = {"a.txt"}
        assert names() == ["b.txt"]  # a(숨김) 완전 제외(소프트 아님)
        R.hidden = set()
        assert names() == ["a.txt", "b.txt"]  # 빈 집합 — 그대로
