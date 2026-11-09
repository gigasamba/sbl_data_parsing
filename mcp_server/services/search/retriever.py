"""검색 — 질의 → PostgreSQL(pgvector)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF). 검색 MCP가 씀."""

import sys
import time

from common.core.contract import uri_from_path  # 원본 위치 규칙(모듈 계약)
from mcp_server.services.search import pgsearch
from mcp_server.services.search.query_expand import (  # 용어 사전(구조화와 같은 규칙) · 벡터 질의 별칭 덧붙이기
    expand_query,
    vector_alias_text,
)
from mcp_server.services.search.rank_rules import embed_query


class Retriever:
    """같은 질의 → 원천 스키마 하나(PostgreSQL + pgvector)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF).
    벡터는 pgvector에만 둔다(docs/prd/ops.md#op-03). 묶음 파일은 읽지 않는다(색인 정보·문서 날짜는 PG)."""

    def __init__(self, *, pg):
        # pg = 원천 스키마 하나의 연결(server_state가 connect_sources로 만들어 줌)
        self.pg = pg
        self.meta = pgsearch.index_meta(pg)  # 임베딩 모델·차원(검색기를 다시 만들 때 — 적재 판이 바뀌면 — 새로 읽음)

    def search(self, q, k, methods=None, scope=None):
        """methods ⊂ {vector, bm25, id}(없으면 셋 다) — 검색 MCP가 방법을 골라 씀(G3).
        scope = 하드 거르기 범위 **안** 문서 file_path 집합 — 주어지면 저장소 질의 단계부터 그 문서의 청크만 후보로(pgsearch._scope_restrict).
        고객은 거르기(client_edw 정확 일치 — search_svc 범위)로만. 반환: (hits, ms)."""
        # X3: BM25 쪽만 용어 사전으로 확장({토큰: 가중치}) — 벡터 질의(qv)는 원문 q 그대로 임베딩(아래, 바뀌지 않음)
        terms, _ = expand_query(q)
        qv = None
        # 벡터가 없는 스키마(빈 원천)·벡터를 안 쓰는 요청은 질의 임베딩도 안 함(키워드·ID만 — 임베딩 없는 이미지·비용)
        if self.meta.get("dim") and (not methods or "vector" in methods):
            try:
                qv = embed_query(self.meta, vector_alias_text(q))  # SI43⑤ — 임베딩 입력에만 명부 별칭 덧붙임(q 자체는 안 바뀜)
            except (
                OSError,
                RuntimeError,
                ImportError,
            ) as ex:  # 임베딩 서버 장애·라이브러리 없음(rag-core 이미지) — 검색을 멈추지 않고 키워드·ID로(근거 via에 v 없음, G11)
                print(f"(질의 임베딩 실패 — 키워드·ID 검색만: {type(ex).__name__}: {str(ex)[:120]})", file=sys.stderr, flush=True)
        if qv is None:
            want = set(methods) if methods else pgsearch.METHODS
            methods = sorted(want - {"vector"}) or ["bm25", "id"]
        t0 = time.perf_counter()
        rows = pgsearch.search(self.pg, qv, terms, k, methods=methods, question=q, scope=scope)
        # URI는 file_path(Object Storage 원본 경로)에서 유도 · 고객은 client_edw(EDW 조인)
        hits = [
            {
                "rank": i + 1,
                "score": r["rrf"],
                "file_path": r["file_path"],
                "page": r["page"],
                "line": f"{r['line_start']}-{r['line_end']}",
                "bbox": r["bbox"],
                "section": r["section"],
                "summary": r["summary"],
                "text": r["chunk_text"],
                "chunk_ref": r["chunk_id"],
                "chunk_key": f"{r['doc_id']}:{r['seq']}",  # <doc_id>:<seq>(5벌이 시퀀스 하나라 겹치지 않음)
                "doc_key": r["file_path"],
                "doc_id": r["doc_id"],
                "file_name": r["file_name"],
                "source_uri": uri_from_path(r["file_path"]),
                "client": r.get("client_edw"),
                "via": r.get("via"),
                "doc_date": r.get("doc_date"),
            }
            for i, r in enumerate(rows)
        ]
        ms = (time.perf_counter() - t0) * 1000
        if scope:  # 안전망 — 범위 밖 청크가 새지 않게
            hits = [h for h in hits if (h.get("file_path") or "") in scope]
        return hits[:k], ms
