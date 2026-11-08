"""mcp_server.services.search.rank_rules 시험."""

from mcp_server import config as mc
from mcp_server.services.search.rank_rules import IndexMismatch, embed_query, weights


def selftest():
    """rank_rules.py의 남은 도우미(weights·embed_query) — Local 검색 엔진은 mc-01(11-01)에 지움
    (그 BM25 가중·BR32 ID 문턱·OP1 숨김 시험은 PG 경로로 test_retriever에 옮김)."""
    # G14 — weights(question) 질문 유형별 가중치(SEARCH_W_BM25_TABLE)
    with mc.senv(SEARCH_W_BM25_TABLE=None, SEARCH_W_BM25=None):  # 설정 객체 덮기(S7d — 끝나면 되돌림)
        w0 = weights()
        assert w0 == {"vector": 1.0, "bm25": 1.0, "id": 2.0}, w0  # 기본값(BR58 1.3은 10-12 되돌림) — question 없음
        assert weights(None) == w0  # question 없으면(아무 데서나 호출) 그대로
        assert weights("단가는 얼마인가요?") == w0  # 집계형 아닌 질문 — 그대로
        w_table = weights("고객별 계약 건수 합계는?")  # 집계형(AGGREGATE_RE) — bm25만 낮춤
        assert w_table["vector"] == 1.0 and w_table["id"] == 2.0 and w_table["bm25"] == 0.2, w_table
        with mc.senv(SEARCH_W_BM25_TABLE="0.05"):
            assert weights("몇 건입니까?")["bm25"] == 0.05  # env로 값 바꿈
    print("[selftest] G14 weights(question) 질문 유형별 가중치(SEARCH_W_BM25_TABLE) 통과")

    _selftest_index_mismatch()


def _selftest_index_mismatch():
    """AD41 — api 색인의 embed_model과 이 프로세스 EMBED_MODEL이 다르면 임베딩 호출 전에 IndexMismatch(ValueError)."""
    with mc.senv(EMBED_MODEL="m-b"):  # 설정 객체 덮기(S7d — 끝나면 되돌림)
        try:
            embed_query({"embed": "api", "embed_model": "m-a", "dim": 4}, "q")
            raise AssertionError("불일치인데 통과")
        except IndexMismatch as e:
            assert "m-a" in str(e) and not isinstance(e, (RuntimeError, OSError))
        with mc.senv(EMBED_MODEL=None):
            try:
                embed_query({"embed": "api", "embed_model": "m-a", "dim": 4}, "q")
                raise AssertionError("EMBED_MODEL 없음인데 통과")
            except IndexMismatch:
                pass
    print("[selftest] AD41 — 질의 임베딩 모델 ≠ 색인 meta면 거부(키워드 검색으로 조용히 안 떨어짐) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
