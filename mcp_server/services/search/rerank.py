"""재순위(선택 단계, 백로그 G8) — RRF 상위 후보를 질문과 함께 읽는 모델(cross-encoder)로 다시 정렬.
기본 꺼짐(SEARCH_RERANK=off) — 켜기 전까지 검색 결과·성능 그대로. 실패해도 검색은 멈추지 않고 원 순서로(info['fallback']).

AD4(조건부 재순위) — SEARCH_RERANK_WHEN=always(기본)|cond. always면 지금과 동일(항상 재순위). cond면 효과가 있을 때만
켠다(지연 절감): (a) 상위1·2 융합(RRF) 점수 차가 작음(SEARCH_RERANK_GAP) (b) 후보가 여러 문서·고객에 흩어짐
(SEARCH_RERANK_SPREAD) (c) 질문 유형이 비교·최신(qtype.classify) — 하나라도면 재순위, 전부 아니면 건너뜀(결정적).
should_rerank()가 게이트(로컬·PG 공용 — retriever.py 한 곳에서만 부름)."""

import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.ai.guard import require_internal
from common.ai.guard import urlopen as _g_urlopen
from common.config import settings as C  # 설정 객체(common 칸 — RERANK_BASE_URL·RERANK_API_KEY, S7d)
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H) · 폐쇄망 전제(common/embed.py와 같은 규칙) — 미리 반입된 캐시만
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
_CE, _CE_LOCK = None, threading.Lock()
_POOL = ThreadPoolExecutor(
    max_workers=4
)  # ponytail: 프로세스 공유 풀 — 시간 초과 요청의 스레드는 계속 돎(취소 불가), 처리량 문제 되면 요청별 풀로


def enabled():
    return (mc.cfg().search.rerank.mode or "off") != "off"  # S7d — 설정 객체


def _cand_n():
    return mc.cfg().search.rerank.top_n


def _get_ce():
    """프로세스당 한 번(스레드 안전 — 더블체크 락)."""
    global _CE
    if _CE is None:
        with _CE_LOCK:
            if _CE is None:
                from sentence_transformers import CrossEncoder

                _CE = CrossEncoder(RERANK_MODEL, device="cpu")
    return _CE


def _score_local(query, texts):
    model = _get_ce()
    return [float(s) for s in model.predict([[query, t] for t in texts])]


def _score_api(query, texts, model_name, timeout_s):
    """TEI/Cohere 호환 /rerank — {query, documents, top_n} → results:[{index, relevance_score}]. 내부망만(DONT 13).
    timeout_s: rerank()가 한 번 묶어 읽은 RERANK_TIMEOUT_MS(초 — VS7d R-2, 요청 안에서 다시 읽지 않음)."""
    rm = C.cfg().models.rerank  # S7d — 설정 객체(common 칸, 한 번 묶어 읽음)
    base = rm.base_url
    if not base:
        raise RuntimeError("SEARCH_RERANK=api:<model>은 RERANK_BASE_URL 필요")
    require_internal(base, "RERANK")
    req = urllib.request.Request(
        base.rstrip("/") + "/rerank",
        data=json.dumps({"model": model_name, "query": query, "documents": texts, "top_n": len(texts)}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    key = C.reveal(rm.api_key)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with _g_urlopen(req, timeout_s, "RERANK") as r:
        data = json.load(r)
    scores = [0.0] * len(texts)
    for item in data.get("results", data.get("data", [])):
        scores[item["index"]] = item.get("relevance_score", item.get("score", 0.0))
    return scores


def _score(backend, query, texts, timeout_s):
    return _score_api(query, texts, backend.split(":", 1)[1], timeout_s) if backend.startswith("api:") else _score_local(query, texts)


def _gap_th():
    # ponytail: 기본 0.02 — RRF 융합 점수(1/(60+rank) 합)는 구조상 상위 등수 사이 상대 차가 작다(synth-4clients
    # 115문항 실측 median 0.007 · 0.1 이상은 거의 안 나옴, AD4) — 서버 실 재순위기·지연 예산으로 재조정(초안).
    return mc.cfg().search.rerank.gap


def _spread_th():
    return mc.cfg().search.rerank.spread


def _spread(hits):
    """후보가 몇 개의 문서(문서 키 없으면 고객)로 흩어졌나 — 결정적(집합 크기만)."""
    keys = {h.get("doc_key") or h.get("client") for h in hits}
    keys.discard(None)
    return len(keys)


def should_rerank(question, hits, fused_top2=None):
    """SEARCH_RERANK_WHEN=cond 게이트 — (적용, 이유). 로컬·PG 공용(fused_top2·hits만 보고 판단, 저장소 모름).
    (a) 상위1·2 융합 점수 차(상대)가 작음 (b) 후보가 여러 문서·고객으로 흩어짐 (c) 질문 유형이 비교·최신 — 하나면 적용."""
    if fused_top2 and len(fused_top2) >= 2 and fused_top2[0]:
        gap = (fused_top2[0] - fused_top2[1]) / fused_top2[0]
        if gap < _gap_th():
            return True, f"점수차 작음({gap:.3f}<{_gap_th()})"
    n_docs = _spread(hits)
    if n_docs >= _spread_th():
        return True, f"문서 흩어짐({n_docs}개)"
    from mcp_server.services.search import qtype as QT  # 늦은 임포트 — rerank.py는 off 경로에서 qtype 의존 없음(기존 동작 유지)

    qt, _ = QT.classify(question or "")
    if qt in ("compare", "latest"):
        return True, f"질문 유형({qt})"
    return False, "점수차 큼·문서 집중·일반형"


def rerank(query, hits, top_n, fused_top2=None):
    """RRF 후보(hits, 랭킹순) → (재정렬 상위 top_n, info). SEARCH_RERANK=off면 그대로 top_n개(동작 불변).
    SEARCH_RERANK_WHEN=cond(기본 always)면 should_rerank()가 효과 있을 때만 켠다 — 건너뛰면 info={applied: False, reason}.
    후보 RERANK_TOP_N개만 모델에 넣고(나머지는 원 순서 뒤에 이어 붙임) — 모델 없음·시간초과·오류는 원 순서 + info['fallback']."""
    rc = mc.cfg().search.rerank  # S7d — 설정 객체(이 함수에서 읽는 칸을 한 번에 묶음)
    backend = rc.mode or "off"
    if backend == "off" or not hits:
        return hits[:top_n], {"backend": "off", "n": 0, "ms": 0.0}
    if (rc.when or "always") == "cond":
        apply, reason = should_rerank(query, hits[:top_n], fused_top2)  # top-k(요청한 top_n)만 — 넓힌 후보(RERANK_TOP_N) 전체가 아님
        if not apply:
            return hits[:top_n], {"backend": backend, "n": 0, "ms": 0.0, "applied": False, "reason": reason}
    else:
        reason = "always"
    cand = hits[: rc.top_n]
    texts = [(h.get("text") or "")[: rc.max_chars] for h in cand]
    t0 = time.perf_counter()
    info = {"backend": backend, "n": len(cand), "applied": True, "reason": reason}
    try:
        timeout_s = rc.timeout_ms / 1000
        scores = _POOL.submit(_score, backend, query, texts, timeout_s).result(timeout=timeout_s)
        order = sorted(range(len(cand)), key=lambda i: -scores[i])
        ordered = [cand[i] for i in order]
    except Exception as ex:
        info["fallback"] = f"{type(ex).__name__}: {str(ex)[:120]}"
        ordered = cand
    info["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out = (ordered + hits[len(cand) :])[:top_n]
    return [{**h, "rank": i + 1} for i, h in enumerate(out)], info
