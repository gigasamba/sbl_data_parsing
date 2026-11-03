"""검색(모듈 ④) — 같은 질의 → 저장소(PostgreSQL+pgvector 또는 로컬 묶음)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF) + 그래프 이웃.
pipeline.py(ask·test-stack)와 검색 MCP(modules/search/mcp_server.py)가 같이 씀. 오케스트레이터(pipeline.py)를 import하지 않음(모듈 분리)."""

import json
import sys
import time
from pathlib import Path

from common.core.contract import (
    make_chunk_key,
    uri_from_path,  # 원본 위치 규칙(모듈 계약)
)
from mcp_server.services.search.local import BundleDocs, embed_query
from mcp_server.services.search.terms import (  # 용어 사전(X3·X4, 구조화와 같은 규칙) · SI43⑤ 벡터 질의 별칭 덧붙이기(10-16 검색 전용으로 분리)
    expand_query,
    vector_alias_text,
)


class Retriever:
    """같은 질의 → 본문·출처 저장소(pgvector 또는 로컬 묶음)에서 하이브리드(벡터 + BM25 + 드문 ID → RRF).
    벡터는 pgvector에만 둔다(사용자 10-29 — EDW 벡터 경로 삭제, docs/prd/ops.md#op-03)."""

    def __init__(self, bundle, retrieve="cosine", pg=None):
        self.bundle, self.retrieve = Path(bundle), retrieve
        self.meta = json.loads((self.bundle / "meta.json").read_text(encoding="utf-8"))
        self.local = BundleDocs(bundle)  # 문서·청크 목록만(검색은 PG — mc-01 11-01)
        self.key_local = {make_chunk_key(self.local.docs[c["doc"]]["doc_key"], c["seq"]): i for i, c in enumerate(self.local.chunks)}
        self.doc_meta = {
            d["doc_key"]: {
                "doc_date": d.get("doc_date"),
                "version": d.get("version"),
                "superseded": bool(d.get("superseded")),
            }
            for d in self.local.docs
        }  # L3-1: pgvector 저장소도 이 로컬 묶음 문서 메타로 최신성 순위(항상 로드됨)
        # 저장소는 PostgreSQL + pgvector(mc-01). pg = 원천 스키마 하나의 연결(pl-28 — server_state가 connect_sources.connect_sources로 만들어 줌).
        from mcp_server.services.search import pgsearch

        self.pgmod, self.pg = pgsearch, pg
        self._g = None

    def search(self, q, k, methods=None):
        """methods ⊂ {vector, bm25, id}(없으면 retrieve 설정대로) — 검색 MCP가 방법을 골라 씀(G3).
        단일 스레드 호출부용 — note류를 self 속성에도 채운다. 공유 인스턴스를 여러 스레드가 쓰면(검색 MCP) search_ex를 쓴다(S12)."""
        hits, ms, notes = self.search_ex(q, k, methods)
        self.expand_notes, self.note = notes.get("expand_notes"), notes.get("note")
        return hits, ms

    def search_ex(self, q, k, methods=None, scope=None):
        """search()와 같은 동작이지만 note류(expand_notes·note)를 반환값 notes(dict)로 준다 — 검색 MCP처럼 같은 Retriever를
        여러 스레드가 동시에 쓸 때 A 요청 응답에 B의 note가 섞이는 것을 막음(S12). (최신성 순위 recency_rerank는 pl-38에 지움.)
        scope = 하드 거르기 범위 **안** 문서 file_path 집합 — 주어지면 저장소 질의 단계부터 그 문서의 청크만 후보로(pgsearch._scope_restrict).
        고객은 거르기(client_edw 정확 일치 — search_svc 범위)로만 — 본문 고객 라벨로 앞으로 올리던 길(AD38·BR50)은 11-02에 지움(사용자 C6).
        반환: (hits, ms, notes)."""
        hits, ms, notes = self._search_ex(q, k, methods, scope=scope)
        if scope:  # 안전망 — 범위 밖 청크가 새지 않게
            hits = [h for h in hits if (h.get("file_path") or "") in scope]
        for h in hits:  # 로컬 묶음 문서 메타로(같은 규칙, 묶음은 항상 로드됨)
            m = self.doc_meta.get(h.get("doc_key")) or {}
            h["doc_date"], h["version"], h["superseded"] = m.get("doc_date"), m.get("version"), m.get("superseded")
        return hits[:k], ms, notes

    def _search_ex(self, q, k, methods=None, scope=None):
        # X3: BM25 쪽만 용어 사전으로 확장({토큰: 가중치}) — 벡터 질의(qv)는 원문 q 그대로 임베딩(아래, 바뀌지 않음)
        terms, expand_notes = expand_query(q)
        qv, note = None, None
        if not self.meta.get("dim"):  # 임베딩 없는 묶음(PIPE_EMBED=none)이면 키워드·ID만
            note = "임베딩 없는 묶음 — 키워드·ID 검색만"
        elif methods and "vector" not in methods:  # 벡터를 안 쓰는 요청은 질의 임베딩도 안 함(S85 — 임베딩 없는 이미지·비용)
            pass
        else:
            try:
                qv = embed_query(self.meta, vector_alias_text(q))  # SI43⑤ — 임베딩 입력에만 명부 별칭 덧붙임(q 자체는 안 바뀜)
            except (
                OSError,
                RuntimeError,
                ImportError,
            ) as ex:  # 임베딩 서버 장애·라이브러리 없음(rag-core 이미지) — 검색을 멈추지 않고 키워드·ID로(근거 via에 v 없음, G11)
                note = f"질의 임베딩 실패 — 키워드·ID 검색만: {type(ex).__name__}: {str(ex)[:120]}"
                print(f"({note})", file=sys.stderr, flush=True)
        if qv is None:
            want = set(methods) if methods else ({"vector"} if self.retrieve == "cosine" else {"vector", "bm25", "id"})
            methods = sorted(want - {"vector"}) or ["bm25", "id"]
        t0 = time.perf_counter()
        if True:  # PG 하나(mc-01)
            rows = self.pgmod.search(
                self.pg,
                qv,
                terms,
                k,
                retrieve=self.retrieve,
                methods=methods,
                question=q,
                scope=scope,
            )
            # URI는 file_path(Object Storage 원본 경로)에서 유도 · 고객은 client_edw(EDW 조인 — pl-29)
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
                    "chunk_key": f"{r['doc_id']}:{r['seq']}",  # 사용자 10-31 — <doc_id>:<seq>(5벌이 시퀀스 하나라 겹치지 않음, pl-28)
                    "doc_key": r["file_path"],
                    "doc_id": r["doc_id"],
                    "file_name": r["file_name"],
                    "source_uri": uri_from_path(r["file_path"]),
                    "client": r.get("client_edw"),
                    "via": r.get("via"),
                }
                for i, r in enumerate(rows)
            ]
        return hits, (time.perf_counter() - t0) * 1000, {"expand_notes": expand_notes, "note": note}
