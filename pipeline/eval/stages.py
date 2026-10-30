"""LLM 없는 조합 실험 단계 구현(eval-design.md §5) — 파싱결과→코퍼스, 청킹, 임베딩, 그래프(networkx), 검색, 지표.
폐쇄망 전제: 임베딩·재순위 모델은 로컬 캐시에서만 읽는다(HF_HUB_OFFLINE). 없으면 조용히 넘어가지 않고 바로 에러.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)

from common.ai.embed import ST_MODELS, _embed_api, _load_st_model, embed_texts  # noqa: F401 — 임베딩 호출도 common
from common.core.repfmt import _SECTION, RE_LABEL_LINE, extract_label_values, locate  # noqa: F401 — 쪽·줄 위치(파싱 결과 형식)
from common.core.text import _SPLIT, _TOK, id_terms, normalize_value, tokens  # noqa: F401 — 토큰 규칙은 common 한 곳(모듈 계약)
from pipeline.transform.structure.chunking import (  # noqa: F401
    CHUNKERS,
    RE_DATE,
    RE_EMAIL,
    RE_ID,
    chunk_all,
    chunk_fixed512,
    chunk_page,
    chunk_recursive,
    chunk_sentence3,
    chunk_structure,
    doc_ext,
    load_parse_doc,
)  # 청킹은 구조화 모듈 — 조합 실험도 같은 것

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


# ── 정규화·토큰화 (§3 공통) ──────────────────────────────────

_WORD = re.compile(r"[A-Za-z0-9가-힣]{2,}")


def words(s):
    """tf-idf·질의용 순수 단어 토큰(bigram 없음 — 사람이 읽는 질의라 원형 유지)."""
    return _WORD.findall(s.lower())


def tfidf_top_terms(doc, corpus, n=2):
    """문서별 tf-idf 상위 n개 단어 — 그 문서에만 많이 나오는 단어(앵커 질의용)."""
    doc_words = {d: words(t) for d, t in corpus.items()}
    df = Counter()
    for ws in doc_words.values():
        df.update(set(ws))
    ndocs = max(len(doc_words), 1)
    tf = Counter(doc_words.get(doc, []))
    # 숫자 조각('209'·'2026')은 문서를 구별하지 못하고 값 일부를 흘릴 수 있어 제외 — 글자가 든 단어(회사명·제품 코드)만
    scored = {w: c * math.log(1 + ndocs / (1 + df[w])) for w, c in tf.items() if len(w) >= 2 and re.search(r"[^\W\d_]", w)}
    return [w for w, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


# ── 엔티티·라벨:값 추출 (앵커 native/consensus 대용 + graph entity/table 모드 공용) ─

RE_NUM_UNIT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|원|건|명|개|년|월|일|kg|km|cm|mm|g|ml|L|㎡|평|억|만|천)?")


def extract_entities(text):
    """숫자+단위·ID·이메일·날짜·':' 앞 라벨 단어 — graph entity 모드용."""
    ents = set(RE_ID.findall(text)) | set(RE_EMAIL.findall(text)) | set(RE_DATE.findall(text))
    for line in text.splitlines():
        m = RE_LABEL_LINE.match(line)
        if m:
            ents.add(m.group(1).strip())
    for m in RE_NUM_UNIT.finditer(text):
        v = m.group().strip()
        if re.search(r"\d", v) and len(v) <= 20:
            ents.add(v)
    return sorted(ents)  # 정렬 — 집합 순서(PYTHONHASHSEED)에 따라 그래프 이웃 순서·결과가 흔들리지 않게


# ── 파싱결과 → 코퍼스 (parse 설정: route · route2 · <엔진>) ────


def load_route(parse_dir):
    f = Path(parse_dir) / "route.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def load_corpus(parse_dir, docs, parse_conf, route, used=None):
    """parse_conf: 'route'(형식별 1위 엔진, 실패 시 다음 순위로 폴백) · 'route2'(2위부터) · '<엔진명>'(그 엔진만,
    실패 문서는 빈 텍스트 → 그 문서의 앵커는 전부 미스로 집계됨)."""
    corpus, facts_by_doc = {}, {}
    for doc in docs:
        if parse_conf in ("route", "route2"):
            rank = route.get(doc_ext(doc, parse_dir), [])
            start = 0 if parse_conf == "route" else 1
            text, facts = "", []
            for eng in rank[start:]:
                text, facts = load_parse_doc(parse_dir, eng, doc)
                if text:
                    if used is not None:
                        used[doc] = eng
                    break
        else:
            text, facts = load_parse_doc(parse_dir, parse_conf, doc)
            if used is not None and text:
                used[doc] = parse_conf
        corpus[doc], facts_by_doc[doc] = text, facts
    return corpus, facts_by_doc


# ── 청킹 (§5) ────────────────────────────────────────────────


# ── 임베딩 (§5) — embed_texts는 common.ai.embed ──────────────


def cached_embed(embed, texts, kind, cache_dir):
    """output/eval/cache/<hash>.npy — hash(model + 청크 텍스트 전체)로 캐시(§2 캐시 키 규칙)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((embed + "\x1e" + "\x1f".join(texts)).encode("utf-8")).hexdigest()[:24]
    f = cache_dir / f"{key}.npy"
    if f.exists():
        return np.load(f)
    vecs = embed_texts(embed, texts, kind)
    np.save(f, vecs)
    return vecs


def tfidf_vectors(texts):
    """embed=none일 때 knn 그래프용 — 단순 dense tf-idf(코퍼스가 크면 sparse로 교체할 것).
    ponytail: 평가용 소규모 코퍼스 전제, 어휘 수천 단어 이상이면 메모리 문제 — 그때 sparse 도입."""
    tok_lists = [words(t) for t in texts]
    vocab = {}
    for toks in tok_lists:
        for w in set(toks):
            vocab.setdefault(w, len(vocab))
    if not vocab:
        return np.zeros((len(texts), 1), dtype=np.float32)
    df = np.zeros(len(vocab))
    for toks in tok_lists:
        for w in set(toks):
            df[vocab[w]] += 1
    idf = np.log(1 + len(texts) / (1 + df))
    mat = np.zeros((len(texts), len(vocab)), dtype=np.float32)
    for i, toks in enumerate(tok_lists):
        for w, c in Counter(toks).items():
            mat[i, vocab[w]] = c * idf[vocab[w]]
        norm = np.linalg.norm(mat[i])
        if norm > 0:
            mat[i] /= norm
    return mat


# ── 그래프 (§5, §3-5) — networkx, mode="llm"만 LLM 사용(그 외 전부 LLM 없음) ─
# S6a(10-26, D-019 ③ · T-02) — LLM 그래프 모드("llm")와 그 지시문(triple_extract)은 PC 전용 validation/e2e/graph_llm.py로 쪼갬.
# 여기에는 모드 등록표만 — graph_mode_ready()가 처음 쓸 때 그 모듈을 importlib로 불러 등록한다(정적 import 없음 — pipeline은
# validation을 import하지 않음, check_modules). 서버 이미지에는 validation/이 없어 "llm"은 ValueError(그 밖 모드는 그대로).
GRAPH_MODES: dict = {}  # 모드 이름 → fn(G, chunks) → 지표 추가분(dict) — 등록 모듈이 채움
_PC_MODES: dict = {}  # PC 전용 모드 → 등록 모듈 · "llm"(validation/e2e/graph_llm.py)은 10-30 지움(e2-18 — 사용자 grill 11차)


def graph_mode_ready(mode):
    """PC 전용 그래프 모드(_PC_MODES)를 처음 쓸 때 그 모듈을 불러 GRAPH_MODES에 등록(import 부수 효과) — 쓸 수 있으면 True.
    모듈이 없으면(서버 이미지 — validation/ 없음) False."""
    if mode not in GRAPH_MODES and mode in _PC_MODES:
        import importlib
        import importlib.util

        try:
            spec = importlib.util.find_spec(_PC_MODES[mode])
        except ModuleNotFoundError:  # 부모 패키지(validation)가 없음
            spec = None
        if spec is not None:
            importlib.import_module(_PC_MODES[mode])
    return mode in GRAPH_MODES


def build_graph(mode, chunks, embeddings=None, facts_by_doc=None):
    import networkx as nx

    graph_mode_ready(mode)  # PC 전용 모드 등록(모듈 import·지시문 읽기)은 시간 재기 전에 — 옛 stages import 때 하던 일
    t0 = time.perf_counter()
    G = nx.Graph()
    llm_extra = {}
    for c in chunks:
        m = c.get("meta") or {}
        G.add_node(("chunk", c["id"]), kind="chunk", doc=c["doc"], page=m.get("page"), line=m.get("line"), section=m.get("section"))
    if mode == "none":
        pass
    elif mode == "struct":
        by_doc = defaultdict(list)
        for c in chunks:
            by_doc[c["doc"]].append(c)
        for doc, cs in by_doc.items():
            G.add_node(("doc", doc), kind="doc")
            for c in cs:
                G.add_edge(("doc", doc), ("chunk", c["id"]), type="doc-chunk")
            for a, b in zip(cs, cs[1:]):
                G.add_edge(("chunk", a["id"]), ("chunk", b["id"]), type="seq")
    elif mode == "entity":
        for c in chunks:
            for ent in extract_entities(c["text"]):
                node = ("entity", ent)
                G.add_node(node, kind="entity")
                G.nodes[node].setdefault("src", set()).add(c["id"])  # 근거 청크(→ meta로 파일·쪽·줄)
                G.add_edge(node, ("chunk", c["id"]), type="mentions")
    elif mode == "knn":
        vecs = embeddings if embeddings is not None else tfidf_vectors([c["text"] for c in chunks])
        sims = vecs @ vecs.T
        for i in range(len(chunks)):
            order = np.argsort(-sims[i])
            k = 0
            for j in order:
                j = int(j)
                if j == i or sims[i, j] < 0.8:
                    continue
                G.add_edge(("chunk", chunks[i]["id"]), ("chunk", chunks[j]["id"]), type="knn", weight=float(sims[i, j]))
                k += 1
                if k >= 5:
                    break
    elif mode == "table":
        for c in chunks:
            pairs = list(extract_label_values(c["text"]))
            for f in (facts_by_doc or {}).get(c["doc"], []):
                for ctx in f.get("context", []):
                    pairs.append((ctx, f.get("value", "")))
            for label, value in pairs:
                ln, vn = ("label", label), ("value", value)
                G.add_node(ln, kind="label")
                G.add_node(vn, kind="value")
                for nd in (ln, vn):
                    G.nodes[nd].setdefault("src", set()).add(c["id"])
                G.add_edge(ln, vn, type="fact")
                G.add_edge(("chunk", c["id"]), ln, type="has-label")
    elif graph_mode_ready(mode):  # S6a(T-02) — "llm"은 PC 전용 validation/e2e/graph_llm.py(GRAPH_MODES에 등록)
        llm_extra = GRAPH_MODES[mode](G, chunks)
    else:
        raise ValueError(f"모르는 그래프 모드: {mode}" + (" — PC 전용(validation/e2e, 서버 이미지에 없음)" if mode in _PC_MODES else ""))
    m = graph_metrics(G, time.perf_counter() - t0)
    m.update(llm_extra)
    return G, m


def graph_metrics(G, sec):
    """G1(노드·엣지 유형별 수) · G3(고립 노드율·최대 연결요소 비율) · G4(적재 시간). G2는 anchor_path_rate()에서."""
    import networkx as nx

    kinds = Counter(nx.get_node_attributes(G, "kind").values())
    edge_types = Counter(d.get("type", "") for _, _, d in G.edges(data=True))
    n = G.number_of_nodes()
    isolated = sum(1 for node in G if G.degree(node) == 0)
    largest = max((len(c) for c in nx.connected_components(G)), default=0)
    return {
        "n_nodes": n,
        "n_edges": G.number_of_edges(),
        "nodes_by_kind": dict(kinds),
        "edges_by_type": dict(edge_types),
        "isolated_ratio": (isolated / n) if n else 0.0,
        "largest_cc_ratio": (largest / n) if n else 0.0,
        "build_sec": round(sec, 4),
    }


def anchor_path_rate(anchors, G, chunks):
    """G2 — 앵커의 라벨을 담은 노드에서 값을 담은 노드까지 2홉 안에 경로가 있는 비율."""
    import networkx as nx

    if not anchors:
        return None
    by_doc = defaultdict(list)
    for c in chunks:
        by_doc[c["doc"]].append(c)
    hit = 0
    for a in anchors:
        lab_n, val_n = normalize_value(a["label"]), normalize_value(a["value"])
        label_nodes = [("chunk", c["id"]) for c in _group_chunks(by_doc, a) if lab_n and lab_n in normalize_value(c["text"])]
        value_nodes = [("chunk", c["id"]) for c in _group_chunks(by_doc, a) if val_n and val_n in normalize_value(c["text"])]
        if ("label", a["label"]) in G:
            label_nodes.append(("label", a["label"]))
        if ("value", a["value"]) in G:
            value_nodes.append(("value", a["value"]))
        value_set = set(value_nodes)
        ok = False
        for ln in label_nodes:
            if ln in value_set:
                ok = True
                break
            if ln not in G:
                continue
            reach = nx.single_source_shortest_path_length(G, ln, cutoff=2)
            if any(vn in reach for vn in value_nodes):
                ok = True
                break
        hit += ok
    return hit / len(anchors)


# ── 검색 (§5, §3-4) ─────────────────────────────────────────


def bm25_scores(query, texts, k1=1.5, b=0.75):
    tfs = [Counter(tokens(t)) for t in texts]
    dls = [sum(tf.values()) for tf in tfs]
    avg = sum(dls) / len(dls) if dls else 1
    df = Counter()
    for tf in tfs:
        df.update(tf.keys())
    n = len(texts)
    q_tokens = set(tokens(query))
    scores = []
    for tf, dl in zip(tfs, dls):
        s = 0.0
        for q in q_tokens:
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * dl / avg))
        scores.append(s)
    return scores


def rrf_fuse(rank_lists, k=60):
    score = defaultdict(float)
    for ranks in rank_lists:
        for i, idx in enumerate(ranks):
            score[idx] += 1.0 / (k + i + 1)
    return sorted(score, key=lambda i: -score[i])


def _mmr(order, chunks, vecs, qv, lam=0.7, k=10, pool=30):
    cand = order[:pool]
    sims_q = vecs[cand] @ qv
    selected, remaining = [], list(range(len(cand)))
    while remaining and len(selected) < k:
        best_ri, best_score = None, -1e9
        for ri, ci in enumerate(remaining):
            div = max((float(vecs[cand[ci]] @ vecs[cand[s]]) for s in selected), default=0.0)
            score = lam * float(sims_q[ci]) - (1 - lam) * div
            if score > best_score:
                best_ri, best_score = ri, score
        selected.append(remaining.pop(best_ri))
    return [chunks[cand[i]] for i in selected]


def _graph_expand(base, G, by_id, per=3):
    """상위 청크마다 그래프 이웃 청크(직접 연결 → 개체·사실·문서 노드를 거친 2홉 순, 최대 per개)를 **합친 컨텍스트 단위**로.
    적중은 합친 조각(parts) 중 하나가 앵커 문서의 값을 담으면 — 이웃이 다른 문서여도 근거가 컨텍스트에 들어간 것."""
    if G is None:
        return list(base)
    out = []
    for c in base:
        node = ("chunk", c["id"])
        nbs = []
        if node in G:
            direct = [nb[1] for nb in G.neighbors(node) if nb[0] == "chunk"]
            via = [x[1] for nb in G.neighbors(node) if nb[0] != "chunk" for x in G.neighbors(nb) if x[0] == "chunk"]
            for cid in direct + via:  # ponytail: 흔한 숫자 개체는 허브가 됨 — per개 상한으로 막음, 가중치 순위는 필요해지면
                if cid != c["id"] and cid in by_id and cid not in nbs:
                    nbs.append(cid)
                if len(nbs) >= per:
                    break
        parts = [(c["doc"], c["text"])] + [(by_id[n]["doc"], by_id[n]["text"]) for n in nbs]
        out.append(
            {**c, "text": "\n".join(t for _, t in parts), "parts": parts, "metas": [c.get("meta")] + [by_id[n].get("meta") for n in nbs]}
        )
    return out


_RERANKER = None


def _get_reranker():
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder

        try:
            _RERANKER = CrossEncoder(RERANK_MODEL, device="cpu")
        except Exception as e:
            raise RuntimeError(f"재순위 모델({RERANK_MODEL}) 로드 실패 — 폐쇄망 로컬 캐시에 없음: {e}") from e
    return _RERANKER


def _rerank(query, cand):
    if not cand:
        return cand
    model = _get_reranker()
    scores = model.predict([[query, c["text"]] for c in cand])
    order = sorted(range(len(cand)), key=lambda i: -scores[i])
    return [cand[i] for i in order]


def _parent(bm_ranked, corpus, k=3):
    out, seen = [], []
    for c in bm_ranked:
        if c["doc"] in seen:
            continue
        seen.append(c["doc"])
        t = corpus.get(c["doc"], "")
        out.append(
            {"doc": c["doc"], "text": t, "meta": {"file": c["doc"], "engine": (c.get("meta") or {}).get("engine"), **locate(t, 0, len(t))}}
        )
        if len(seen) >= k:
            break
    return out


def retrieve_grep(query, corpus, topk=10):
    """질의 단어가 가장 많이 걸리는 줄 ±2줄 — 에이전트식 grep 흉내."""
    q_tokens = set(tokens(query))
    hits = []
    for doc, text in corpus.items():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            score = len(q_tokens & set(tokens(line)))
            if score > 0:
                hits.append((score, doc, i))
    hits.sort(key=lambda x: (-x[0], x[1], x[2]))
    out = []
    for _score, doc, i in hits[:topk]:
        lines = corpus[doc].splitlines()
        lo, hi = max(0, i - 2), min(len(lines), i + 3)
        s0 = sum(len(x) + 1 for x in lines[:lo])
        t = "\n".join(lines[lo:hi])
        out.append({"doc": doc, "text": t, "meta": {"file": doc, "engine": None, **locate(corpus[doc], s0, s0 + len(t))}})
    return out


NEEDS_EMBED = {"dense", "hybrid", "hybrid_mmr", "rerank"}  # graph는 임베딩 없으면 BM25 상위에서 확장


def retrieve(method, query, chunks, corpus, embed_vecs=None, embed_fn=None, G=None, rerank_ok=False, topk=10):
    """검색 방식 하나 실행 → 랭킹된 단위(unit: {doc, text, ...}) 목록."""
    if method == "grep":
        return retrieve_grep(query, corpus, topk)
    texts = [c["text"] for c in chunks]
    bm = bm25_scores(query, texts)
    bm_order = sorted(range(len(chunks)), key=lambda i: (-bm[i], chunks[i]["id"]))
    if method == "bm25":
        return [chunks[i] for i in bm_order[:topk]]
    if method == "parent":
        return _parent([chunks[i] for i in bm_order], corpus)
    if method == "graph" and (embed_vecs is None or embed_fn is None):
        return _graph_expand([chunks[i] for i in bm_order[:5]], G, {c["id"]: c for c in chunks})[:topk]
    if method not in NEEDS_EMBED | {"graph"}:
        raise ValueError(f"모르는 검색 방식: {method}")
    if embed_vecs is None or embed_fn is None:
        raise ValueError(f"검색 방식 '{method}'은 embed != none 이 필요합니다")
    qv = np.asarray(embed_fn([query], "query"))[0]
    ds = embed_vecs @ qv
    d_order = sorted(range(len(chunks)), key=lambda i: (-float(ds[i]), chunks[i]["id"]))
    if method == "dense":
        return [chunks[i] for i in d_order[:topk]]
    fused = rrf_fuse([bm_order, d_order])
    if method == "hybrid":
        return [chunks[i] for i in fused[:topk]]
    if method == "hybrid_mmr":
        return _mmr(fused, chunks, embed_vecs, qv, k=topk)
    if method == "graph":
        base = [chunks[i] for i in fused[:5]]
        return _graph_expand(base, G, {c["id"]: c for c in chunks})[:topk]
    if method == "rerank":
        if not rerank_ok:
            raise ValueError("rerank은 --rerank 지정 시에만 실행합니다")
        cand = [chunks[i] for i in fused[:30]]
        return _rerank(query, cand)[:topk]
    raise ValueError(f"모르는 검색 방식: {method}")


# ── 지표 (§3-4 R, §3-3 C) ─────────────────────────────────────


def _group_chunks(by_doc, a):
    """앵커의 내용 묶음(사본 포함) 청크 — anchors.content_groups."""
    return [c for d in (a.get("docs") or [a["doc"]]) for c in by_doc.get(d, [])]


def meaningful_chars(texts):
    """유의미 글자 수(ctx5m) — 규칙은 common/meaning.py 한 곳. 조합 정렬 3순위(R@5 → MRR → 이 값, 많을수록 좋음)."""
    from common.core.meaning import chars

    return chars(texts)


def rank_key(R):
    """조합 순위 정렬키 — R@5 → MRR → 유의미 글자 수(많을수록 좋음). run_combo·run_answers·explorer·finalize 공용."""
    return (
        -(R.get("r5") or 0),
        -(R.get("mrr") or 0),
        -(R.get("ctx5m") or 0),
    )  # ctx5m 없는 옛 실행 = 0(글자 수 ctx5로 대신하지 않음 — 뜻이 다름)


def eval_retrieval(anchors, run_query):
    """run_query(anchor) -> ranked units. 앵커 전체를 넘겨 외부 스택(anchor_id 매칭)도 같은 함수로 채점한다.
    반환: (R 지표 dict(§3-4), 앵커별 hit 상세 목록) — 후자는 output/eval/hits/<key>.jsonl로 그대로 저장된다.
    hit 상세: {"anchor_id", "rank": 첫 적중 순위(1부터) 또는 None, "top": 상위 5개 단위별 {doc, text(300자), hit}}."""
    if not anchors:
        return {"r1": 0.0, "r5": 0.0, "r10": 0.0, "mrr": 0.0, "ctx5": 0, "ctx5m": 0, "p50_ms": 0.0, "p95_ms": 0.0, "n_anchors": 0}, []
    hits, rr_sum, ctx5_total, ctx5m_total, lat, hit_rows = {1: 0, 5: 0, 10: 0}, 0.0, 0, 0, [], []
    for a in anchors:
        t0 = time.perf_counter()
        ranked = run_query(a)
        lat.append((time.perf_counter() - t0) * 1000)
        val_n = normalize_value(a["value"])
        rank, top5 = None, []
        for i, u in enumerate(ranked[:10]):
            docs_ok = a.get("docs") or [a["doc"]]
            is_hit = bool(val_n) and any(
                d in docs_ok and val_n in normalize_value(t) for d, t in (u.get("parts") or [(u.get("doc"), u.get("text", ""))])
            )
            if rank is None and is_hit:
                rank = i + 1
            if i < 5:
                top5.append({"doc": u.get("doc"), "text": u.get("text", "")[:300], "hit": is_hit})
        for k in (1, 5, 10):
            if rank is not None and rank <= k:
                hits[k] += 1
        if rank is not None:
            rr_sum += 1.0 / rank
        ctx5_total += sum(len(u.get("text", "")) for u in ranked[:5])
        ctx5m_total += meaningful_chars(u.get("text", "") for u in ranked[:5])
        hit_rows.append({"anchor_id": a["id"], "rank": rank, "top": top5})
    n = len(anchors)
    lat.sort()

    def pct(p):
        return round(lat[min(len(lat) - 1, int(p * len(lat)))], 2) if lat else 0.0

    R = {
        "r1": hits[1] / n,
        "r5": hits[5] / n,
        "r10": hits[10] / n,
        "mrr": rr_sum / n,
        "ctx5": ctx5_total // n,
        "ctx5m": ctx5m_total // n,
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "n_anchors": n,
    }
    return R, hit_rows


def chunk_metrics(chunks, anchors, truth=None):
    """C1(크기 분포)·C2(근거 온전율)·C3(표 절단율 — truth 표 있을 때만)."""
    lens = sorted(len(c["text"]) for c in chunks)
    c1 = {
        "n_chunks": len(chunks),
        "mean_chars": round(sum(lens) / len(lens), 1) if lens else 0,
        "p95_chars": lens[int(0.95 * (len(lens) - 1))] if lens else 0,
    }
    by_doc = defaultdict(list)
    for c in chunks:
        by_doc[c["doc"]].append(c)
    c2 = None
    if anchors:
        intact = 0
        for a in anchors:
            lab_n, val_n = normalize_value(a["label"]), normalize_value(a["value"])
            if any(lab_n in normalize_value(c["text"]) and val_n in normalize_value(c["text"]) for c in _group_chunks(by_doc, a)):
                intact += 1
        c2 = intact / len(anchors)
    c3 = None
    if truth:
        split, total = 0, 0
        for doc, info in truth.items():
            if not isinstance(info, dict):
                continue
            for table in info.get("tables") or []:
                for row in table[1:] if len(table) > 1 else []:  # 첫 행은 헤더로 취급
                    cells = [str(x).strip() for x in row if str(x).strip()]
                    if len(cells) < 2:
                        continue
                    total += 1
                    cell_ns = [normalize_value(x) for x in cells]
                    if not any(all(cn in normalize_value(c["text"]) for cn in cell_ns) for c in by_doc.get(doc, [])):
                        split += 1
        c3 = (split / total) if total else None
    return {"C1": c1, "C2": c2, "C3": c3}
