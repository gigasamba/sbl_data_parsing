"""BM25 질의어 가중치(검색 전용) — term_weights(X3 용어 사전 확장). common.core.text.tokens()가 만드는 토큰
목록을 common.core.terms.expand_query()의 {토큰: 가중치} 확장 결과와 같은 모양으로 맞춘다(local.py·pgsearch.py 공용)."""


def term_weights(terms):
    """BM25 질의어 가중치(X3 용어 사전 확장) — dict{term: weight}면 그대로, 아니면(list·set·generator) 전부 1.0(확장 없을 때 기존 동작과 동일)."""
    return terms if isinstance(terms, dict) else {t: 1.0 for t in terms}
