"""검색 공용 도우미(pgsearch·retriever) — 질의 임베딩·가중치·ID 문턱. 검색은 PG 하나(PC는 SQLite 대역 pg_standin)."""

from common.ai.embed import embed_texts, query_model_mismatch
from mcp_server import config as mc

ID_MAX_DF = 5  # ID 우선 검색에 쓰는 ID: 이 수 이하의 "문서"에만 나오는 것(로컬·pgvector 같은 값).
# BR32 — 청크 수가 아니라 문서 수로 센다(원래 의도 "여러 문서에 흔한 제품 코드는 문서를 특정 못 함"은 문서 단위
# 개념인데, 예전엔 청크 단위로 셌다 — 같은 문서를 청크 여러 개로 쪼개면(G9 머리말은 그 문서의 모든 청크에 같은
# ID 토큰을 반복) 문서 1개뿐인데도 문턱을 넘어 제외됐다. 실측(QA074): 메일 스크린샷(mailshot_*.png)이 OCR로
# 조각 4개로 쪼개져 메일 ID 토큰이 청크 6개(eml 1·msg 1·png 4)에 나타남 → 청크 기준 df=6 > 5로 걸러져 정작
# .msg 사본이 후보에도 못 들었다. 문서 기준이면 df=3(eml·msg·png 각 1문서) — 문턱 안.


def weights(question=None):
    """RRF 가중치(검색 방법별) — SEARCH_W_VECTOR·SEARCH_W_BM25·SEARCH_W_ID(기본 1·1·2, 드문 ID 정확 일치를 우선).
    SEARCH_W_BM25 기본 1.3은 시도했다가 되돌림 — 상위5 적중은 올랐지만(합본 terms-hard .70→.80)
    1위 정답이 여러 세트에서 떨어짐(hard64 .772→.719·r2 .85→.80·distractors 1.0→.944, 답변 단계 QA095 미스) —
    근접 중복 문서 구분은 재정렬(BR54) 쪽에서. 측정: dev_tools/perform_test/retrieval/measure.py --pooled·--hard-core-manifest.
    G14 — question이 주어지고 집계 질문 단서(mcp_server.services.search.question_type.AGGREGATE_RE —
    건수·합계·최대/최소·평균)가 걸리면 SEARCH_W_BM25 대신 SEARCH_W_BM25_TABLE을
    bm25 가중으로 쓴다 — 표 집계 질문은 같은 양식의 다른 고객·연도 표가 키워드로 같이 올라와 BM25가 벡터 1위 근거를
    끌어내리는 문제(dev/docs/backlog/search.md G14). rank_rules.py·pgsearch.py 둘 다 이 함수 하나만 써서 가중치가
    갈라지지 않는다(pgsearch.py가 이 함수를 import)."""
    s = mc.cfg().search  # 한 번 묶음(가중치 칸들이 같은 판 값)
    w = {"vector": s.weights.vector, "bm25": s.weights.bm25, "id": s.weights.id}
    if question is not None:
        from mcp_server.services.search.question_type import AGGREGATE_RE

        if AGGREGATE_RE.search(question):
            w["bm25"] = s.weights.bm25_table
    return w


class IndexMismatch(ValueError):
    """질의 임베딩 모델이 색인(gold doc.embed_model)과 다름. RuntimeError·OSError가 아니라서 '키워드·ID만'으로 조용히 떨어지지 않고 오류로 드러남."""


def embed_query(meta, text):
    """질의 임베딩 — 모델은 색인 meta(embed·embed_model — pgsearch.index_meta)에서, 차원도 meta와 맞아야 함(AD41: 불일치면 거부)."""
    import numpy as np

    bad = query_model_mismatch(meta)  # api는 모델 이름이 이 프로세스 env(EMBED_MODEL) — 색인과 다르면 거부
    if bad:
        raise IndexMismatch(bad)
    v = embed_texts(meta["embed"], [text], "query")[0]
    if len(v) != meta["dim"]:  # 적재 뒤 임베딩 모델(EMBED_MODEL)을 바꾸면 차원이 달라 검색이 깨짐 — 다시 적재
        raise SystemExit(
            f"질의 임베딩 {len(v)}차원 ≠ 적재 {meta['dim']}차원(모델 {meta.get('embed_model')}) — 같은 모델로 묻거나 다시 적재"
        )
    return (v / (np.linalg.norm(v) or 1)).astype("float32")
