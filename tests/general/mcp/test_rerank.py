"""mcp_server.services.search.rerank 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.rerank`."""

from mcp_server import config as mc
from mcp_server.services.search import rerank as M
from mcp_server.services.search.rerank import rerank, should_rerank


def selftest():
    RR = M  # 직접 실행(__main__)·모듈 임포트 양쪽에서 같은 모듈 객체를 패치하게
    hits = [{"text": f"doc{i}", "rank": i + 1} for i in range(5)]

    with mc.senv(SEARCH_RERANK="off"):  # S7d — 설정 객체 덮기(os.environ 안 건드림)
        out, info = rerank("q", hits, 3)
        assert [h["text"] for h in out] == ["doc0", "doc1", "doc2"] and info["backend"] == "off" and "fallback" not in info

    _env = mc.senv(SEARCH_RERANK="stub-model")
    orig_local = RR._score_local
    RR._score_local = lambda q, texts: [texts.index(t) * 1.0 for t in texts]  # 뒤에 있던 문서(doc4)가 점수 최고 → 1위로
    try:
        out, info = rerank("q", hits, 5)
        assert [h["text"] for h in out] == ["doc4", "doc3", "doc2", "doc1", "doc0"] and "fallback" not in info
        assert [h["rank"] for h in out] == [1, 2, 3, 4, 5]

        out, info = rerank("q", hits, 2)  # top_n 자르기
        assert len(out) == 2 and [h["text"] for h in out] == ["doc4", "doc3"]

        def boom(q, texts):
            raise RuntimeError("모델 없음")

        RR._score_local = boom
        out, info = rerank("q", hits, 5)
        assert [h["text"] for h in out] == [h["text"] for h in hits] and "fallback" in info
    finally:
        RR._score_local = orig_local
        _env.close()
    print("[selftest] 재순위 — off=동일·재정렬·top_n 자르기·오류 fallback 통과")

    _selftest_gate()


def _selftest_gate():
    """AD4 — SEARCH_RERANK_WHEN=cond: (a) 점수차 (b) 문서 흩어짐 (c) 비교·최신 질문 중 하나면 적용, 전부 아니면 건너뜀.
    기본(always)은 게이트 없이 항상 적용(기존 동작 그대로)."""
    hits_tight = [{"text": f"d{i}", "doc_key": "same-doc"} for i in range(3)]  # 문서 1개(흩어짐 없음)
    hits_spread = [{"text": f"d{i}", "doc_key": f"doc{i}"} for i in range(4)]  # 문서 4개(흩어짐)

    # (a) 점수차 작음 → 적용
    apply, reason = should_rerank("단가는?", hits_tight, fused_top2=[1.0, 0.99])
    assert apply and "점수차" in reason, reason
    # 점수차 큼 + 문서 집중 + 일반형 질문 → 건너뜀
    apply, reason = should_rerank("단가는?", hits_tight, fused_top2=[1.0, 0.5])
    assert not apply, reason
    # (b) 문서 흩어짐(기본 문턱 3) → 적용(fused_top2 없이도)
    apply, reason = should_rerank("단가는?", hits_spread, fused_top2=None)
    assert apply and "흩어짐" in reason, reason
    # (c) 비교·최신 질문 → 적용(점수차 크고 문서 집중이어도)
    apply, reason = should_rerank("A와 B 단가 비교는?", hits_tight, fused_top2=[1.0, 0.5])
    assert apply and "질문 유형" in reason, reason
    apply, reason = should_rerank("현재 유효한 단가는?", hits_tight, fused_top2=[1.0, 0.5])
    assert apply and "질문 유형" in reason, reason
    # fused_top2 비어있어도(벡터 전용 외부 순위 등) 예외 없이 (b)(c)로 판단
    apply, reason = should_rerank("단가는?", hits_tight, fused_top2=[])
    assert not apply, reason

    RR = M
    hits = [{"text": f"doc{i}", "doc_key": "same-doc"} for i in range(5)]
    _env = mc.senv(SEARCH_RERANK="stub-model")
    orig_local = RR._score_local
    RR._score_local = lambda q, texts: [texts.index(t) * 1.0 for t in texts]
    try:
        _env.enter_context(mc.senv(SEARCH_RERANK_WHEN="cond"))
        out, info = rerank("단가는?", hits, 5, fused_top2=[1.0, 0.99])  # 점수차 작음 → 적용, 재정렬됨
        assert info.get("applied") is True and [h["text"] for h in out] == ["doc4", "doc3", "doc2", "doc1", "doc0"]

        out, info = rerank("단가는?", hits, 5, fused_top2=[1.0, 0.5])  # 신호 없음 → 건너뜀, 원 순서 그대로
        assert info.get("applied") is False and [h["text"] for h in out] == [h["text"] for h in hits]

        _env.enter_context(mc.senv(SEARCH_RERANK_WHEN="always"))  # 기본값 — 신호 없어도 항상 적용(기존 동작)
        out, info = rerank("단가는?", hits, 5, fused_top2=[1.0, 0.5])
        assert info.get("applied") is True and [h["text"] for h in out] == ["doc4", "doc3", "doc2", "doc1", "doc0"]
        out, info = rerank("단가는?", hits, 5)  # fused_top2 안 줘도(기본 None) always는 그대로 동작
        assert info.get("applied") is True
    finally:
        RR._score_local = orig_local
        _env.close()
    print("[selftest] AD4 조건부 재순위(SEARCH_RERANK_WHEN=cond) — 점수차·문서흩어짐·비교/최신만 적용, always=기존과 동일 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
